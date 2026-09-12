"""Integration and unit tests for UniTime ReAct Chat Agent and /api/chat endpoint."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import server
from agent.chat_agent import ChatReActAgent

client = TestClient(server.app)


def test_chat_agent_direct_answer() -> None:
    """Verify ReAct agent handles direct queries with Final Answer properly."""
    agent = ChatReActAgent()

    mock_llm_reply = (
        "Thought: Pengguna memberikan salam pembuka. Tidak memerlukan eksekusi tools.\n"
        "Final Answer: Halo! Saya adalah Asisten AI Penjadwalan UniTime berbasis ReAct. "
        "Ada yang bisa saya bantu terkait jadwal kuliah atau ruangan hari ini?"
    )

    with patch.object(agent, "_call_llm", return_value=mock_llm_reply):
        result = agent.run_chat(message="Halo, siapa kamu?")
        assert "Asisten AI Penjadwalan UniTime" in result["reply"]
        assert len(result["thought_process"]) >= 1
        assert len(result["tools_used"]) == 0


def test_chat_agent_tool_execution_room_capacity() -> None:
    """Verify ReAct agent executes inspect_room_capacity tool when checking capacity."""
    agent = ChatReActAgent()

    # Step 1: Model decides to invoke inspect_room_capacity
    step1_reply = (
        "Thought: Saya perlu memeriksa kapasitas ruangan LABTEK V 7601.\n"
        'Action: inspect_room_capacity\n'
        'Action Input: {"building": "LABTEK V", "room_number": "7601", "required_cap": 70}'
    )
    # Step 2: After observation, model produces final answer
    step2_reply = (
        "Thought: Observasi menunjukkan kapasitas hanya 60 kursi, sedangkan dibutuhkan 70 kursi.\n"
        "Final Answer: Ruangan LABTEK V 7601 hanya memiliki kapasitas 60 kursi, sehingga tidak mencukupi untuk 70 mahasiswa (kurang 10 kursi)."
    )

    with patch.object(agent, "_call_llm", side_effect=[step1_reply, step2_reply]):
        result = agent.run_chat(message="Apakah Labtek V 7601 cukup untuk 70 mahasiswa?")
        assert "inspect_room_capacity" in result["tools_used"]
        assert "hanya memiliki kapasitas 60 kursi" in result["reply"]
        assert len(result["thought_process"]) >= 2


def test_chat_agent_get_active_schedule_context() -> None:
    """Verify get_active_schedule_context tool retrieves course details from active job."""
    agent = ChatReActAgent(job_manager_ref=server.job_manager)

    # Register a sample completed job in job_manager
    sample_payload = {
        "department": {"code": "IF"},
        "academicSession": {"term": "Ganjil 2026/2027"},
        "courses": [
            {
                "courseNumber": "IF2110",
                "courseTitle": "Algoritma & Pemrograman",
                "configurations": [
                    {
                        "subparts": [
                            {
                                "instructionalType": "Lecture",
                                "classes": [
                                    {
                                        "sectionNumber": "01",
                                        "timePattern": "Senin 08:00-10:00",
                                        "room": "LABTEK V 7601",
                                        "instructors": [{"name": "Dr. Alan Turing"}],
                                    }
                                ],
                            }
                        ]
                    }
                ],
            }
        ],
    }

    job = server.job_manager.create_job(
        job_id="test_job_123",
        file_path=server.GATEWAY_DIR / "dummy.pdf",
        filename="dummy.pdf",
        provider="gemini",
        payload=sample_payload,
    )

    step1_reply = (
        "Thought: Saya perlu mengecek jadwal yang aktif di dashboard.\n"
        'Action: get_active_schedule_context\n'
        'Action Input: {"job_id": "test_job_123"}'
    )
    step2_reply = (
        "Thought: Data jadwal ditemukan dengan 1 mata kuliah: IF2110 Algoritma & Pemrograman.\n"
        "Final Answer: Terdapat 1 mata kuliah dalam jadwal aktif, yaitu IF2110 Algoritma & Pemrograman (Kelas 01 di LABTEK V 7601)."
    )

    with patch.object(agent, "_call_llm", side_effect=[step1_reply, step2_reply]):
        result = agent.run_chat(message="Apa mata kuliah di jadwal ini?", job_id="test_job_123")
        assert "get_active_schedule_context" in result["tools_used"]
        assert "IF2110" in result["reply"]


def test_api_chat_endpoint() -> None:
    """Verify POST /api/chat endpoint through FastAPI TestClient."""
    mock_llm_reply = (
        "Thought: Pertanyaan mengenai status sistem UniTime.\n"
        "Final Answer: Server UniTime Tomcat aktif 24/7 dan terhubung ke MySQL."
    )

    with patch.object(server.chat_agent, "_call_llm", return_value=mock_llm_reply):
        response = client.post(
            "/api/chat",
            json={
                "message": "Bagaimana status UniTime?",
                "history": [],
                "job_id": None,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "UniTime Tomcat aktif" in data["reply"]
        assert "tools_used" in data
        assert "timestamp" in data
