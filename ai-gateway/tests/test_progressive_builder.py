"""Unit and multi-turn integration tests for the Progressive Conversational Data Builder.

Validates:
1. AgentMemory draft state CRUD methods (isolated in :memory: SQLite).
2. The 6 progressive builder mutation tools in agent/tools.py.
3. Multi-turn conversational ReAct agent flow (Turn 1 topology -> Turn 2 building -> Turn 3 course -> Turn 4 preference -> Turn 5 commit).
4. FastAPI /api/chat endpoint with session_id support.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

import server
from agent.chat_agent import ChatReActAgent
from agent.memory import AgentMemory
from agent.tools import (
    commit_draft_to_unitime,
    draft_course_offering,
    get_draft_summary,
    record_building_and_rooms,
    record_campus_topology,
    record_scheduling_preference,
)
from core.client import CourseImportSummary, IngestClientResponse, IngestSummary


@pytest.fixture
def mem() -> AgentMemory:
    """Provide an isolated, in-memory SQLite AgentMemory store."""
    memory = AgentMemory(":memory:")
    yield memory
    memory.close()


# =============================================================================
# 1. AgentMemory Draft State CRUD Tests
# =============================================================================


def test_draft_state_empty_default(mem: AgentMemory) -> None:
    """Verify get_draft_state returns a well-formed empty structure when session is new."""
    state = mem.get_draft_state("new_session_123")
    assert state["session_id"] == "new_session_123"
    assert state["campus_topology"] == {"regions": [], "travel_times": {}}
    assert state["buildings"] == []
    assert state["courses"] == []
    assert state["preferences"] == []
    assert state["metadata"] == {}
    assert state["updated_at"] is None


def test_draft_topology_crud(mem: AgentMemory) -> None:
    """Verify upsert_draft_topology creates and updates campus topology with merging."""
    sid = "sess_topology"

    # Initial insert
    s1 = mem.upsert_draft_topology(sid, ["Depok", "Salemba"], {"Depok_Salemba": 45})
    assert "Depok" in s1["campus_topology"]["regions"]
    assert "Salemba" in s1["campus_topology"]["regions"]
    assert s1["campus_topology"]["travel_times"]["Depok_Salemba"] == 45
    assert s1["updated_at"] is not None

    # Merge additional region and travel time, test deduplication
    s2 = mem.upsert_draft_topology(sid, ["Salemba", "Ganesha"], {"Depok_Ganesha": 120})
    regs = s2["campus_topology"]["regions"]
    assert len(regs) == 3
    assert set(regs) == {"Depok", "Salemba", "Ganesha"}
    assert s2["campus_topology"]["travel_times"]["Depok_Salemba"] == 45
    assert s2["campus_topology"]["travel_times"]["Depok_Ganesha"] == 120


def test_draft_building_rooms_crud(mem: AgentMemory) -> None:
    """Verify upsert_draft_building_rooms registers buildings and merges room details."""
    sid = "sess_building"

    # Insert first building
    rooms_1 = [
        {"room_number": "101", "capacity": 40, "type": "lab"},
        {"room_number": "102", "capacity": 50, "type": "classroom"},
    ]
    s1 = mem.upsert_draft_building_rooms(sid, "Gedung Fasilkom A", "Depok", rooms_1)
    assert len(s1["buildings"]) == 1
    bldg = s1["buildings"][0]
    assert bldg["name"] == "Gedung Fasilkom A"
    assert bldg["campus"] == "Depok"
    assert len(bldg["rooms"]) == 2

    # Update building: update room 101 capacity and add room 103
    rooms_update = [
        {"room_number": "101", "capacity": 45},  # updated capacity
        {"room_number": "103", "capacity": 60, "type": "seminar"},  # new room
    ]
    s2 = mem.upsert_draft_building_rooms(sid, "Gedung Fasilkom A", "Depok", rooms_update)
    assert len(s2["buildings"]) == 1
    updated_rooms = s2["buildings"][0]["rooms"]
    assert len(updated_rooms) == 3

    r101 = next(r for r in updated_rooms if r["room_number"] == "101")
    assert r101["capacity"] == 45
    assert r101["type"] == "lab"  # preserved previous attribute

    r103 = next(r for r in updated_rooms if r["room_number"] == "103")
    assert r103["capacity"] == 60


def test_draft_course_crud(mem: AgentMemory) -> None:
    """Verify upsert_draft_course records courses and handles updates properly."""
    sid = "sess_course"

    course_data = {
        "subject": "CS",
        "course_number": "CS101",
        "title": "Pengantar Ilmu Komputer",
        "sks": 3,
        "classes": [{"section": "01", "room": "Lab 101"}],
    }
    s1 = mem.upsert_draft_course(sid, course_data)
    assert len(s1["courses"]) == 1
    c1 = s1["courses"][0]
    assert c1["course_number"] == "CS101"
    assert c1["sks"] == 3

    # Update the same course with new class section and changed title
    updated_course_data = {
        "course_number": "CS101",
        "title": "Pengantar Ilmu Komputer & Pemrograman",
        "sks": 3,
        "classes": [
            {"section": "01", "room": "Lab 101"},
            {"section": "02", "room": "Lab 102"},
        ],
    }
    s2 = mem.upsert_draft_course(sid, updated_course_data)
    assert len(s2["courses"]) == 1
    assert s2["courses"][0]["title"] == "Pengantar Ilmu Komputer & Pemrograman"
    assert len(s2["courses"][0]["classes"]) == 2


def test_draft_preference_crud(mem: AgentMemory) -> None:
    """Verify upsert_draft_preference tracks and updates domain constraints."""
    sid = "sess_prefs"

    pref = {
        "entity_type": "instructor",
        "entity_name": "Dr. Alan Turing",
        "preference_type": "unavailable_time",
        "details": "Tidak dapat mengajar pada Jumat sore.",
    }
    s1 = mem.upsert_draft_preference(sid, pref)
    assert len(s1["preferences"]) == 1
    p1 = s1["preferences"][0]
    assert p1["entity_name"] == "Dr. Alan Turing"
    assert "Jumat sore" in p1["details"]

    # Update existing preference
    pref_update = {
        "entity_type": "instructor",
        "entity_name": "Dr. Alan Turing",
        "preference_type": "unavailable_time",
        "details": "Tidak dapat mengajar pada Jumat setelah pukul 11:00.",
    }
    s2 = mem.upsert_draft_preference(sid, pref_update)
    assert len(s2["preferences"]) == 1
    assert "11:00" in s2["preferences"][0]["details"]


def test_clear_draft_state_and_clear_all(mem: AgentMemory) -> None:
    """Verify individual session purge and bulk clear_all_for_testing."""
    sid1 = "sess_clear_1"
    sid2 = "sess_clear_2"

    mem.upsert_draft_topology(sid1, ["Depok"])
    mem.upsert_draft_topology(sid2, ["Salemba"])

    # Clear sid1 only
    ok = mem.clear_draft_state(sid1)
    assert ok is True
    assert mem.get_draft_state(sid1)["campus_topology"]["regions"] == []
    assert mem.get_draft_state(sid2)["campus_topology"]["regions"] == ["Salemba"]

    # Clear all
    mem.clear_all_for_testing()
    assert mem.get_draft_state(sid2)["campus_topology"]["regions"] == []


# =============================================================================
# 2. Builder Tools in agent/tools.py Tests
# =============================================================================


def test_tool_record_campus_topology(mem: AgentMemory) -> None:
    """Verify record_campus_topology tool execution and markdown output."""
    sid = "tool_top_test"
    result = record_campus_topology(
        session_id=sid,
        regions=["Depok", "Salemba"],
        travel_times={"Depok_Salemba": 45},
        memory_instance=mem,
    )
    assert "Wilayah Kampus Berhasil Dicatat" in result
    assert "Depok" in result
    assert "Salemba" in result
    assert "45 menit" in result

    # Check persistence
    draft = mem.get_draft_state(sid)
    assert set(draft["campus_topology"]["regions"]) == {"Depok", "Salemba"}


def test_tool_record_building_and_rooms(mem: AgentMemory) -> None:
    """Verify record_building_and_rooms tool execution and room capacity registration."""
    sid = "tool_bldg_test"
    rooms = [
        {"room_number": "7601", "capacity": 60, "type": "Lab Komputer"},
        {"room_number": "7602", "capacity": 40, "type": "Kelas Reguler"},
    ]
    result = record_building_and_rooms(
        session_id=sid,
        building="Labtek V",
        campus_region="Ganesha",
        rooms=rooms,
        memory_instance=mem,
    )
    assert "Gedung & Ruangan Berhasil Dicatat" in result
    assert "Labtek V" in result
    assert "7601" in result
    assert "60 kursi" in result

    # Cross-tool inspection: capacity should be registered in memory knowledge base
    cap = mem.get_room_capacity("Labtek V", "7601")
    assert cap == 60


def test_tool_draft_course_offering(mem: AgentMemory) -> None:
    """Verify draft_course_offering tool formats course offering confirmation."""
    sid = "tool_course_test"
    classes = [
        {
            "section": "01",
            "time": "Senin 08:00-10:00",
            "room": "Labtek V 7601",
            "instructor": "Dr. Turing",
        }
    ]
    result = draft_course_offering(
        session_id=sid,
        subject="IF",
        course_number="IF2110",
        title="Algoritma & Pemrograman",
        sks=3,
        classes=classes,
        memory_instance=mem,
    )
    assert "Penawaran Mata Kuliah Berhasil Dicatat" in result
    assert "IF2110" in result
    assert "Algoritma & Pemrograman" in result
    assert "3 SKS" in result
    assert "Dr. Turing" in result


def test_tool_record_scheduling_preference(mem: AgentMemory) -> None:
    """Verify record_scheduling_preference persists rule and syncs instructor quirks."""
    sid = "tool_pref_test"
    result = record_scheduling_preference(
        session_id=sid,
        entity_type="instructor",
        entity_name="Dr. Turing",
        preference_type="unavailable_time",
        details="Tidak bisa mengajar hari Jumat siang.",
        memory_instance=mem,
    )
    assert "Preferensi Penjadwalan Berhasil Dicatat" in result
    assert "Dr. Turing" in result
    assert "Jumat siang" in result

    # Cross-check instructor quirks table
    pref = mem.get_instructor_preference("*", "Dr. Turing")
    assert pref is not None
    assert "Jumat siang" in (pref.get("notes") or "")


def test_tool_get_draft_summary(mem: AgentMemory) -> None:
    """Verify get_draft_summary produces complete markdown summary of session state."""
    sid = "tool_sum_test"
    mem.upsert_draft_topology(sid, ["Depok"])
    mem.upsert_draft_building_rooms(
        sid, "Gedung A", "Depok", [{"room_number": "101", "capacity": 50}]
    )
    mem.upsert_draft_course(
        sid,
        {
            "course_number": "IF2110",
            "title": "Struktur Data",
            "sks": 3,
            "classes": [{"section": "01"}],
        },
    )

    summary = get_draft_summary(sid, memory_instance=mem)
    assert f"Ringkasan Draft Akademik Sesi `{sid}`" in summary
    assert "Depok" in summary
    assert "Gedung A" in summary
    assert "IF2110" in summary
    assert "Siap Disinkronkan ke UniTime" in summary


def test_tool_commit_draft_to_unitime(mem: AgentMemory) -> None:
    """Verify commit_draft_to_unitime handles empty drafts, dry runs, and live commits."""
    sid = "tool_commit_test"

    # 1. Empty draft error
    empty_res = commit_draft_to_unitime(sid, dry_run=True, memory_instance=mem)
    assert "Tidak Dapat Melakukan Sinkronisasi" in empty_res

    # Populate minimum required draft data
    mem.upsert_draft_topology(sid, ["Depok"])
    mem.upsert_draft_building_rooms(
        sid, "Labtek V", "Depok", [{"room_number": "7601", "capacity": 60}]
    )
    mem.upsert_draft_course(
        sid,
        {
            "subject": "IF",
            "course_number": "IF2110",
            "title": "Algoritma & Pemrograman",
            "sks": 3,
            "classes": [
                {
                    "section": "01",
                    "time": "Senin 08:00-10:00",
                    "room": "Labtek V 7601",
                    "instructor": "Dr. Alan Turing",
                }
            ],
        },
    )

    # 2. Dry run validation success
    dry_res = commit_draft_to_unitime(sid, dry_run=True, memory_instance=mem)
    assert "Validasi Dry-Run Berhasil" in dry_res
    assert "VALID" in dry_res
    assert "IF2110" in dry_res or "1 mata kuliah" in dry_res

    # 3. Live commit with simulated successful response
    mock_resp = IngestClientResponse(
        status="SUCCESS",
        http_status_code=200,
        raw_json={"status": "SUCCESS"},
        summary=IngestSummary(courses_count=1, classes_count=1),
        courses_imported=[
            CourseImportSummary(course_number="IF2110", title="Algoritma & Pemrograman")
        ],
    )

    with patch("core.client.UniTimeClient.submit_ingest", return_value=mock_resp):
        live_res = commit_draft_to_unitime(sid, dry_run=False, memory_instance=mem)
        assert "Sinkronisasi ke UniTime Berhasil!" in live_res
        assert "SUCCESS" in live_res


# =============================================================================
# 3. Multi-Turn Conversational ReAct Agent Test
# =============================================================================


def test_multi_turn_conversational_builder_flow(mem: AgentMemory) -> None:
    """Test full multi-turn conversational progression from topology to UniTime commit.

    Turn 1: Topology definition (Depok & Salemba)
    Turn 2: Building & classrooms definition (Gedung Fasilkom)
    Turn 3: Course offering definition (CS101)
    Turn 4: Scheduling preference (Dr. Turing unavailable Friday)
    Turn 5: Summary & commit
    """
    sid = "multi_turn_session_99"
    agent = ChatReActAgent(memory=mem)

    # Turn 1: Topology
    turn1_llm = (
        "Thought: Pengguna menyebutkan wilayah kampus dan estimasi waktu tempuh. "
        "Saya harus mencatat topologi kampus ini ke dalam draft memory.\n"
        'Action: record_campus_topology\n'
        'Action Input: {"regions": ["Depok", "Salemba"], "travel_times": {"Depok_Salemba": 45}}'
    )
    turn1_llm_post = (
        "Thought: Observasi menunjukkan wilayah kampus berhasil dicatat.\n"
        "Final Answer: Wilayah kampus Depok dan Salemba (waktu tempuh 45 menit) telah dicatat. "
        "Apakah ada gedung dan ruangan yang ingin didaftarkan di wilayah tersebut?"
    )

    with patch.object(agent, "_call_llm", side_effect=[turn1_llm, turn1_llm_post]):
        res1 = agent.run_chat(
            message="Kampus kita ada 2: Depok dan Salemba. Waktu tempuh antar kampus 45 menit.",
            session_id=sid,
        )
        assert "record_campus_topology" in res1["tools_used"]
        assert "Depok dan Salemba" in res1["reply"]

    # Verify Turn 1 State
    state1 = mem.get_draft_state(sid)
    assert set(state1["campus_topology"]["regions"]) == {"Depok", "Salemba"}

    # Turn 2: Building & Rooms
    turn2_llm = (
        "Thought: Pengguna memberikan informasi gedung dan ruangan di kampus Depok.\n"
        'Action: record_building_and_rooms\n'
        'Action Input: {"building": "Gedung Fasilkom", "campus_region": "Depok", "rooms": [{"room_number": "Lab 101", "capacity": 40, "type": "lab"}]}'
    )
    turn2_llm_post = (
        "Thought: Observasi menunjukkan gedung dan ruangan berhasil dicatat.\n"
        "Final Answer: Gedung Fasilkom dengan Lab 101 (kapasitas 40 kursi) telah dicatat di kampus Depok. "
        "Selanjutnya, mata kuliah apa yang akan dijadwalkan di ruangan ini?"
    )

    with patch.object(agent, "_call_llm", side_effect=[turn2_llm, turn2_llm_post]):
        res2 = agent.run_chat(
            message="Di Depok ada Gedung Fasilkom dengan Lab 101 kapasitas 40 orang.",
            session_id=sid,
        )
        assert "record_building_and_rooms" in res2["tools_used"]
        assert "Gedung Fasilkom" in res2["reply"]

    # Verify Turn 2 State
    state2 = mem.get_draft_state(sid)
    assert len(state2["buildings"]) == 1
    assert state2["buildings"][0]["name"] == "Gedung Fasilkom"

    # Turn 3: Course Offering
    turn3_llm = (
        "Thought: Pengguna mendaftarkan penawaran mata kuliah CS101.\n"
        'Action: draft_course_offering\n'
        'Action Input: {"subject": "CS", "course_number": "CS101", "title": "Pengantar Pemrograman", "sks": 3, "classes": [{"section": "01", "time": "Senin 08:00-10:00", "room": "Gedung Fasilkom Lab 101", "instructor": "Dr. Alan Turing"}]}'
    )
    turn3_llm_post = (
        "Thought: Observasi menunjukkan mata kuliah berhasil dicatat.\n"
        "Final Answer: Mata kuliah CS101 Pengantar Pemrograman (3 SKS, Seksi 01 di Lab 101) berhasil dicatat. "
        "Apakah ada aturan atau preferensi khusus dosen yang perlu diperhatikan?"
    )

    with patch.object(agent, "_call_llm", side_effect=[turn3_llm, turn3_llm_post]):
        res3 = agent.run_chat(
            message="Tolong tambahkan mata kuliah CS101 Pengantar Pemrograman 3 SKS, jadwal Senin 08:00-10:00 di Lab 101 dengan Dr. Alan Turing.",
            session_id=sid,
        )
        assert "draft_course_offering" in res3["tools_used"]
        assert "CS101" in res3["reply"]

    # Verify Turn 3 State
    state3 = mem.get_draft_state(sid)
    assert len(state3["courses"]) == 1
    assert state3["courses"][0]["course_number"] == "CS101"

    # Turn 4: Scheduling Preference
    turn4_llm = (
        "Thought: Pengguna menetapkan batasan jadwal untuk Dr. Alan Turing.\n"
        'Action: record_scheduling_preference\n'
        'Action Input: {"entity_type": "instructor", "entity_name": "Dr. Alan Turing", "preference_type": "unavailable_time", "details": "Tidak bisa mengajar hari Jumat"}'
    )
    turn4_llm_post = (
        "Thought: Observasi menunjukkan preferensi berhasil dicatat.\n"
        "Final Answer: Batasan jadwal Dr. Alan Turing (tidak bisa mengajar Jumat) telah dicatat. "
        "Jika data sudah cukup lengkap, Anda dapat meminta ringkasan atau sinkronisasi ke UniTime."
    )

    with patch.object(agent, "_call_llm", side_effect=[turn4_llm, turn4_llm_post]):
        res4 = agent.run_chat(
            message="Dr. Alan Turing tidak bisa mengajar hari Jumat.",
            session_id=sid,
        )
        assert "record_scheduling_preference" in res4["tools_used"]

    # Verify Turn 4 State
    state4 = mem.get_draft_state(sid)
    assert len(state4["preferences"]) == 1
    assert "Jumat" in state4["preferences"][0]["details"]

    # Turn 5: Commit to UniTime (Dry Run)
    turn5_llm = (
        "Thought: Pengguna meminta untuk memeriksa dan melakukan validasi dry run draft ke UniTime.\n"
        'Action: commit_draft_to_unitime\n'
        'Action Input: {"dry_run": true}'
    )
    turn5_llm_post = (
        "Thought: Observasi menunjukkan validasi dry-run berhasil dan valid.\n"
        "Final Answer: Seluruh draft telah divalidasi dengan sukses (Status: VALID). "
        "Data siap disinkronkan langsung ke server UniTime kapan saja."
    )

    with patch.object(agent, "_call_llm", side_effect=[turn5_llm, turn5_llm_post]):
        res5 = agent.run_chat(
            message="Apakah draft ini sudah lengkap dan valid untuk UniTime?",
            session_id=sid,
        )
        assert "commit_draft_to_unitime" in res5["tools_used"]
        assert "VALID" in res5["reply"]


# =============================================================================
# 4. FastAPI /api/chat with session_id Test
# =============================================================================


def test_api_chat_with_session_id() -> None:
    """Verify POST /api/chat endpoint accepts session_id and routes properly."""
    client = TestClient(server.app)

    mock_llm_reply = (
        "Thought: Pengguna menanyakan ringkasan draft sesi tertentu.\n"
        "Final Answer: Draft sesi sid_test_456 memiliki 1 kampus dan 1 mata kuliah."
    )

    with patch.object(server.chat_agent, "_call_llm", return_value=mock_llm_reply):
        response = client.post(
            "/api/chat",
            json={
                "message": "Bagaimana isi draft saya saat ini?",
                "history": [],
                "session_id": "sid_test_456",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert "sid_test_456" in data["reply"]
