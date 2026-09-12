"""Integration tests for the UniTime AI Ingestion Gateway FastAPI server.

Verifies end-to-end functionality of all REST endpoints:
- GET /api/health (connectivity checks, provider metadata)
- POST /api/ingest/upload (file validation, async job initiation, canonical JSON bypass)
- GET /api/ingest/status/{job_id} (real-time progress, ambiguity tracking, course summaries)
- POST /api/ingest/resolve/{job_id} (HITL disambiguation resolution and resumption)
- POST /api/ingest/submit/{job_id} (UniTime persistence submission and error handling)
- GET /api/reports (audit report listing)
- GET /api/reports/{filename} (markdown report retrieval and traversal protection)
- CORS header verification for Vercel origins
"""

from __future__ import annotations

import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import server
from core.client import (
    IngestClientResponse,
    IngestSummary,
    UniTimeClientError,
    UniTimeConnectionError,
)

client = TestClient(server.app)


# =============================================================================
# Health Endpoint Tests
# =============================================================================


def test_health_check_connected() -> None:
    """Verify health endpoint returns status 'ok' and reports UniTime connected when reachable."""
    mock_health_data = {"status": "UP", "version": "4.8", "database": "healthy"}

    with patch("server.UniTimeClient.health_check", return_value=mock_health_data):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert "provider" in data
        assert data["unitime"]["connected"] is True
        assert data["unitime"]["details"] == mock_health_data
        assert data["unitime"]["error"] is None
        assert "timestamp" in data


def test_health_check_disconnected() -> None:
    """Verify health endpoint handles unreachable UniTime without crashing, reporting connected=False."""
    with patch(
        "server.UniTimeClient.health_check",
        side_effect=UniTimeConnectionError("Connection refused by target host"),
    ):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "ok"
        assert data["unitime"]["connected"] is False
        assert "Connection refused" in data["unitime"]["error"]


# =============================================================================
# Upload & Status Endpoint Tests
# =============================================================================


def test_upload_invalid_file_extension() -> None:
    """Reject unsupported file formats with HTTP 400."""
    fake_file = io.BytesIO(b"ELF binary payload")
    response = client.post(
        "/api/ingest/upload",
        files={"file": ("malicious.exe", fake_file, "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_upload_text_file_synchronous_and_status() -> None:
    """Upload a text memo with sync=True and verify status reports completed with course summary."""
    memo_content = "Kuliah IF2110 Algoritma dan Pemrograman 4 SKS\nKelas K01 Labtek V 7601"
    file_bytes = io.BytesIO(memo_content.encode("utf-8"))

    response = client.post(
        "/api/ingest/upload?sync=true",
        files={"file": ("memo_if.txt", file_bytes, "text/plain")},
        data={"provider": "mock", "dry_run": "true"},
    )
    assert response.status_code == 200
    upload_data = response.json()

    job_id = upload_data["job_id"]
    assert job_id.startswith("job_")
    assert upload_data["filename"] == "memo_if.txt"

    # Poll status endpoint
    status_resp = client.get(f"/api/ingest/status/{job_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()

    assert status_data["job_id"] == job_id
    assert status_data["state"] == "completed"
    assert status_data["progress"]["percent"] == 100
    assert status_data["progress"]["stage"] == "completed"
    assert status_data["course_summary"] is not None
    assert status_data["course_summary"]["total_courses"] >= 1
    assert len(status_data["course_summary"]["courses"]) >= 1
    assert status_data["course_summary"]["courses"][0]["course_number"] == "IF2110"


def test_upload_async_background_polling() -> None:
    """Upload a text memo asynchronously and poll status until completion."""
    memo_content = "IF2210 Pemrograman Berorientasi Objek 3 SKS"
    file_bytes = io.BytesIO(memo_content.encode("utf-8"))

    response = client.post(
        "/api/ingest/upload",
        files={"file": ("async_memo.txt", file_bytes, "text/plain")},
        data={"provider": "mock"},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    # Poll for completion with bounded timeout
    deadline = time.time() + 10.0
    final_state = None

    while time.time() < deadline:
        st_resp = client.get(f"/api/ingest/status/{job_id}")
        assert st_resp.status_code == 200
        st_data = st_resp.json()
        if st_data["state"] in ("completed", "waiting_disambiguation", "failed"):
            final_state = st_data["state"]
            break
        time.sleep(0.1)

    assert final_state in ("completed", "waiting_disambiguation")


def test_upload_canonical_json_bypass() -> None:
    """Directly uploaded canonical JSON payloads are validated and summarized accurately."""
    canonical_payload = {
        "ingestControl": {
            "mode": "incremental",
            "sourceDocumentName": "direct_curriculum.json",
        },
        "academicSession": {
            "year": "2024-2025",
            "term": "Ganjil",
            "campus": "Kampus Ganesha",
        },
        "department": {
            "code": "IF",
            "name": "Teknik Informatika",
        },
        "subjectArea": {
            "abbreviation": "IF",
            "title": "Informatika",
        },
        "courses": [
            {
                "courseNumber": "IF3110",
                "title": "Pengembangan Berbasis Web",
                "controlling": True,
                "configurations": [
                    {
                        "name": "Default",
                        "subparts": [
                            {
                                "type": "Lecture",
                                "minPerWeek": 150,
                                "classes": [
                                    {
                                        "sectionName": "K01",
                                        "capacity": 40,
                                        "roomPreferences": [
                                            {"building": "Labtek V", "roomNumber": "7602"}
                                        ],
                                        "instructors": [
                                            {"name": "Dr. Ayu", "isLead": True}
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    file_bytes = io.BytesIO(json.dumps(canonical_payload).encode("utf-8"))
    response = client.post(
        "/api/ingest/upload?sync=true",
        files={"file": ("direct_curriculum.json", file_bytes, "application/json")},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    status_resp = client.get(f"/api/ingest/status/{job_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()

    assert status_data["state"] == "completed"
    assert status_data["course_summary"]["total_courses"] == 1
    assert status_data["course_summary"]["courses"][0]["course_number"] == "IF3110"
    assert status_data["course_summary"]["courses"][0]["instructors"] == ["Dr. Ayu"]


def test_get_job_status_not_found() -> None:
    """Requesting non-existent job ID returns HTTP 404."""
    response = client.get("/api/ingest/status/non_existent_job_999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# =============================================================================
# Disambiguation (HITL) Endpoint Tests
# =============================================================================


def test_disambiguation_resolution_lifecycle(tmp_path: Path) -> None:
    """Test full cycle: detection of capacity ambiguity -> pause -> resolution -> completion."""
    temp_mem = tmp_path / "isolated_memory.db"
    with patch("server.MEMORY_DB_PATH", temp_mem):
        # Create canonical payload with deliberate capacity deficit (req: 100, capacity: 40)
        conflict_payload = {
            "academicSession": {"year": "2024-2025", "term": "Ganjil", "campus": "Kampus Ganesha"},
            "department": {"code": "IF", "name": "Teknik Informatika"},
            "courses": [
                {
                    "courseNumber": "IF4090",
                    "title": "Tugas Akhir I",
                    "controlling": True,
                    "configurations": [
                        {
                            "name": "Default",
                            "subparts": [
                                {
                                    "type": "Lecture",
                                    "classes": [
                                        {
                                            "sectionName": "K01",
                                            "capacity": 100,
                                            "roomPreferences": [
                                                {"building": "Labtek V", "roomNumber": "7601"}
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        file_bytes = io.BytesIO(json.dumps(conflict_payload).encode("utf-8"))
        response = client.post(
            "/api/ingest/upload?sync=true",
            files={"file": ("conflict_doc.json", file_bytes, "application/json")},
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]

        # Verify job is paused in waiting_disambiguation state
        status_resp = client.get(f"/api/ingest/status/{job_id}")
        assert status_resp.status_code == 200
        status_data = status_resp.json()

        assert status_data["state"] == "waiting_disambiguation"
        assert len(status_data["ambiguities"]) >= 1
        amb_id = status_data["ambiguities"][0]["id"]
        assert "IF4090" in amb_id

        # Resolve ambiguity
        resolve_resp = client.post(
            f"/api/ingest/resolve/{job_id}?sync=true",
            json={"resolutions": {amb_id: "Allow overflow (keep room)"}},
        )
        assert resolve_resp.status_code == 200
        assert resolve_resp.json()["status"] == "processing"

        # Verify job resumes and completes
        final_status = client.get(f"/api/ingest/status/{job_id}").json()
        assert final_status["state"] == "completed"
    assert len(final_status["ambiguities"]) == 0


def test_resolve_job_not_found() -> None:
    """Resolving a non-existent job ID returns HTTP 404."""
    response = client.post(
        "/api/ingest/resolve/job_ghost_404",
        json={"resolutions": {"q1": "Approve"}},
    )
    assert response.status_code == 404


def test_resolve_job_not_in_waiting_state() -> None:
    """Resolving a job that is already completed returns HTTP 400."""
    memo = io.BytesIO(b"IF2110 ASD 4 SKS")
    upload_res = client.post(
        "/api/ingest/upload?sync=true",
        files={"file": ("sample.txt", memo, "text/plain")},
    )
    job_id = upload_res.json()["job_id"]

    response = client.post(
        f"/api/ingest/resolve/{job_id}",
        json={"resolutions": {"q1": "Approve"}},
    )
    assert response.status_code == 400
    assert "not awaiting disambiguation" in response.json()["detail"]


# =============================================================================
# UniTime Submission Endpoint Tests
# =============================================================================


def test_submit_to_unitime_success() -> None:
    """Submit a completed job payload to UniTime and verify successful response."""
    memo = io.BytesIO(b"IF2110 ASD 4 SKS")
    upload_res = client.post(
        "/api/ingest/upload?sync=true",
        files={"file": ("ready_memo.txt", memo, "text/plain")},
    )
    job_id = upload_res.json()["job_id"]

    mock_resp = IngestClientResponse(
        status="SUCCESS",
        http_status_code=200,
        raw_json={"status": "SUCCESS", "message": "Saved 1 course offering."},
        timestamp="2026-09-12T10:00:00Z",
        summary=IngestSummary(courses_count=1, classes_count=1),
    )

    with patch("server.UniTimeClient.submit_ingest", return_value=mock_resp):
        sub_resp = client.post(f"/api/ingest/submit/{job_id}")
        assert sub_resp.status_code == 200
        sub_data = sub_resp.json()

        assert sub_data["job_id"] == job_id
        assert sub_data["status"] == "SUCCESS"
        assert sub_data["http_status_code"] == 200
        assert sub_data["is_success"] is True
        assert "Saved 1 course offering" in str(sub_data["details"])


def test_submit_job_not_found() -> None:
    """Submitting a non-existent job returns HTTP 404."""
    response = client.post("/api/ingest/submit/ghost_job_000")
    assert response.status_code == 404


def test_submit_job_still_waiting_disambiguation() -> None:
    """Submitting a job that still has unresolved ambiguities returns HTTP 400."""
    conflict_payload = {
        "academicSession": {"year": "2024-2025", "term": "Ganjil"},
        "department": {"code": "IF", "name": "Teknik Informatika"},
        "courses": [
            {
                "courseNumber": "IF9999",
                "configurations": [
                    {
                        "subparts": [
                            {
                                "classes": [
                                    {
                                        "sectionName": "K01",
                                        "capacity": 200,
                                        "roomPreferences": [
                                            {"building": "Labtek V", "roomNumber": "7601"}
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        ],
    }
    file_bytes = io.BytesIO(json.dumps(conflict_payload).encode("utf-8"))
    upload_res = client.post(
        "/api/ingest/upload?sync=true",
        files={"file": ("conflict_pause.json", file_bytes, "application/json")},
    )
    job_id = upload_res.json()["job_id"]

    sub_resp = client.post(f"/api/ingest/submit/{job_id}")
    assert sub_resp.status_code == 400
    assert "pending ambiguities" in sub_resp.json()["detail"]


def test_submit_unitime_connection_error() -> None:
    """UniTime connection failure returns HTTP 502 Bad Gateway."""
    memo = io.BytesIO(b"IF2110 ASD 4 SKS")
    upload_res = client.post(
        "/api/ingest/upload?sync=true",
        files={"file": ("offline_unitime.txt", memo, "text/plain")},
    )
    job_id = upload_res.json()["job_id"]

    with patch(
        "server.UniTimeClient.submit_ingest",
        side_effect=UniTimeConnectionError("Target port 8888 unreachable"),
    ):
        sub_resp = client.post(f"/api/ingest/submit/{job_id}")
        assert sub_resp.status_code == 502
        assert "Failed to connect to UniTime server" in sub_resp.json()["detail"]


# =============================================================================
# Audit Reports Endpoint Tests
# =============================================================================


def test_reports_listing() -> None:
    """Verify listing recent executive markdown audit reports."""
    response = client.get("/api/reports")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        assert "filename" in data[0]
        assert "size_bytes" in data[0]
        assert "modified_at" in data[0]


def test_report_detail_json_and_raw() -> None:
    """Verify retrieving specific report content in both JSON and raw markdown modes."""
    test_report_file = server.REPORTS_DIR / "test_report_sample.md"
    test_report_file.write_text("# Executive Timetabling Report\n\nAll courses valid.", encoding="utf-8")

    try:
        # 1. JSON retrieval
        res_json = client.get(f"/api/reports/{test_report_file.name}")
        assert res_json.status_code == 200
        json_data = res_json.json()
        assert json_data["filename"] == test_report_file.name
        assert "Executive Timetabling Report" in json_data["content"]
        assert json_data["size_bytes"] > 0

        # 2. Raw markdown retrieval
        res_raw = client.get(f"/api/reports/{test_report_file.name}?raw=true")
        assert res_raw.status_code == 200
        assert "text/markdown" in res_raw.headers["content-type"]
        assert "# Executive Timetabling Report" in res_raw.text
    finally:
        if test_report_file.exists():
            test_report_file.unlink()


def test_report_not_found() -> None:
    """Non-existent report file returns HTTP 404."""
    response = client.get("/api/reports/ghost_report_99999.md")
    assert response.status_code == 404


def test_report_traversal_protection() -> None:
    """Attempting path traversal is blocked with HTTP 400."""
    response = client.get("/api/reports/..test.md")
    assert response.status_code == 400
    assert "Invalid filename format" in response.json()["detail"]


# =============================================================================
# CORS Preflight Tests
# =============================================================================


def test_cors_preflight_for_vercel() -> None:
    """OPTIONS request from Vercel domain receives appropriate CORS headers."""
    response = client.options(
        "/api/health",
        headers={
            "Origin": "https://unitime-copilot.vercel.app",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://unitime-copilot.vercel.app"
    assert response.headers["access-control-allow-credentials"] == "true"
