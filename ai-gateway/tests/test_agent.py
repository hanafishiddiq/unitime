"""Unit tests for UniTime AI Gateway Agent State, Memory, and Tools subsystems."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from langgraph.types import Command

from agent import (
    ALL_TOOLS,
    AgentMemory,
    IngestAgentState,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_PROCESSING,
    STATUS_WAITING_FOR_HUMAN,
    build_ingest_graph,
    check_time_conflict,
    create_initial_state,
    generate_admin_summary,
    inspect_room_capacity,
    record_learned_resolution,
    resolve_instructor_identity,
    run_agent_pipeline,
    write_admin_report,
)


# =============================================================================
# State Subsystem Tests
# =============================================================================


def test_create_initial_state_defaults() -> None:
    """Test initial state creation with default values."""
    doc_path = "/path/to/schedule.pdf"
    state = create_initial_state(doc_path)

    assert state["document_path"] == doc_path
    assert state["document_type"] == "auto"
    assert state["slices"] == []
    assert state["current_slice_index"] == 0
    assert state["partial_payloads"] == []
    assert state["unified_payload"] is None
    assert state["validation_result"] is None
    assert state["memory_context"] == {}
    assert state["ambiguities"] == []
    assert state["human_response"] is None
    assert state["audit_logs"] == []
    assert state["ingest_result"] is None
    assert state["status"] == STATUS_PROCESSING
    assert state["messages"] == []


def test_state_langgraph_compatibility() -> None:
    """Verify that IngestAgentState can be registered in a LangGraph StateGraph."""
    graph = StateGraph(IngestAgentState)

    def dummy_node(state: IngestAgentState) -> Dict[str, Any]:
        return {
            "current_slice_index": state["current_slice_index"] + 1,
            "status": STATUS_COMPLETED,
        }

    graph.add_node("step1", dummy_node)
    graph.set_entry_point("step1")
    graph.set_finish_point("step1")
    compiled = graph.compile()

    init_state = create_initial_state("doc.txt", "text")
    final_state = compiled.invoke(init_state)

    assert final_state["current_slice_index"] == 1
    assert final_state["status"] == STATUS_COMPLETED


# =============================================================================
# Memory Subsystem Tests
# =============================================================================


def test_memory_room_alias_and_capacity() -> None:
    """Test setting and retrieving room aliases and seating capacities."""
    with AgentMemory(":memory:") as mem:
        # Initial lookup returns None
        assert mem.get_room_alias("IF", "Lab Komputer 1") is None
        assert mem.get_room_capacity("Labtek V", "7601") is None

        # Register alias and verify case insensitivity
        mem.set_room_alias("IF", "Lab Komputer 1", "Labtek V 7601")
        assert mem.get_room_alias("IF", "Lab Komputer 1") == "Labtek V 7601"
        assert mem.get_room_alias("if", "lab komputer 1") == "Labtek V 7601"
        assert mem.get_room_alias("IF", "  LAB KOMPUTER 1  ") == "Labtek V 7601"

        # Department isolation vs wildcard fallback
        assert mem.get_room_alias("EL", "Lab Komputer 1") is None
        mem.set_room_alias("*", "Lab Kimia", "Labtek I 101")
        assert mem.get_room_alias("IF", "Lab Kimia") == "Labtek I 101"

        # Room capacity
        mem.set_room_capacity("Labtek V", "7601", 65)
        assert mem.get_room_capacity("Labtek V", "7601") == 65
        assert mem.get_room_capacity("labtek v", "7601") == 65


def test_memory_instructor_quirks() -> None:
    """Test saving and retrieving instructor quirks and preferences."""
    with AgentMemory(":memory:") as mem:
        assert mem.get_instructor_preference("CS", "Alan Turing") is None

        prefs = {
            "preferred_days": ["M", "W", "F"],
            "preferred_rooms": ["HAAS G066", "LWSN B155"],
            "max_hours": 9.5,
            "notes": "Prefers morning slots before 12:00",
        }
        mem.set_instructor_preference("CS", "Alan Turing", prefs)

        saved = mem.get_instructor_preference("CS", "Alan Turing")
        assert saved is not None
        assert saved["department_code"] == "CS"
        assert saved["instructor_name"] == "Alan Turing"
        assert saved["preferred_days"] == ["M", "W", "F"]
        assert saved["preferred_rooms"] == ["HAAS G066", "LWSN B155"]
        assert saved["max_hours"] == 9.5
        assert saved["notes"] == "Prefers morning slots before 12:00"

        # Case-insensitive lookup
        saved_lower = mem.get_instructor_preference("cs", "alan turing")
        assert saved_lower is not None
        assert saved_lower["instructor_name"] == "Alan Turing"


def test_memory_resolution_history() -> None:
    """Test storing learned human choices and querying prior resolutions."""
    with AgentMemory(":memory:") as mem:
        assert mem.find_previous_resolution("IF", "ambiguous_room_l01") is None

        fix_payload = {"room": "Labtek V 7601", "constraint": "SAME_ROOM"}
        record_id = mem.save_resolution(
            dept="IF",
            issue_sig="ambiguous_room_l01",
            question="Which room for IF2110 L01?",
            choice="Labtek V 7601",
            fix=fix_payload,
        )
        assert record_id > 0

        # Retrieve prior resolution
        resolved = mem.find_previous_resolution("IF", "ambiguous_room_l01")
        assert resolved is not None
        assert "Labtek V 7601" in resolved


def test_memory_audit_journal() -> None:
    """Test audit log persistence and retrieval."""
    with AgentMemory(":memory:") as mem:
        mem.log_audit("INFO", "test_doc.pdf", "Parsing page 1", {"page": 1})
        mem.log_audit("WARNING", "test_doc.pdf", "Room capacity warning", {"room": "7601"})

        logs = mem.get_audit_logs(limit=10)
        assert len(logs) == 2
        assert logs[0]["level"] == "WARNING"
        assert logs[0]["source_doc"] == "test_doc.pdf"
        assert logs[0]["metadata"]["room"] == "7601"
        assert logs[1]["level"] == "INFO"


def test_memory_disk_persistence() -> None:
    """Test SQLite creation on physical disk and directory auto-creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "sub" / "dir" / "agent_memory.db"
        assert not db_path.exists()

        mem = AgentMemory(db_path)
        mem.set_room_alias("CS", "Room A", "HAAS 101")
        mem.close()

        assert db_path.exists()

        # Reopen and check persistence
        mem2 = AgentMemory(db_path)
        alias = mem2.get_room_alias("CS", "Room A")
        mem2.close()
        assert alias == "HAAS 101"


# =============================================================================
# Tools Subsystem Tests
# =============================================================================


def test_inspect_room_capacity_catalog_and_fallback() -> None:
    """Test inspect_room_capacity tool with catalog, memory, and heuristics."""
    # 1. Known catalog room
    res_pass = inspect_room_capacity("Labtek V", "7601", 50)
    assert res_pass["is_sufficient"] is True
    assert res_pass["actual_capacity"] == 60
    assert res_pass["status"] == "PASS"

    res_fail = inspect_room_capacity("Labtek V", "7601", 80)
    assert res_fail["is_sufficient"] is False
    assert res_fail["deficit"] == 20
    assert res_fail["status"] == "FAIL_CAPACITY_EXCEEDED"

    # 2. Heuristic room
    res_aud = inspect_room_capacity("Building", "Main Auditorium", 150)
    assert res_aud["is_sufficient"] is True
    assert res_aud["actual_capacity"] >= 200

    # 3. Persistent memory integration
    with AgentMemory(":memory:") as mem:
        mem.set_room_capacity("CustBldg", "101", 42)
        res_mem = inspect_room_capacity("CustBldg", "101", 40, memory_instance=mem)
        assert res_mem["actual_capacity"] == 42
        assert res_mem["is_sufficient"] is True


def test_resolve_instructor_identity() -> None:
    """Test cleaning academic titles and resolving instructor names."""
    # 1. Cleaning academic titles without memory
    res1 = resolve_instructor_identity("CS", "Prof. Dr. Alan Turing, Ph.D.")
    assert res1["canonical_name"] == "Alan Turing"
    assert res1["is_resolved"] is True

    res2 = resolve_instructor_identity("IF", "Ir. Budi Rahardjo, M.Sc., Ph.D.")
    assert res2["canonical_name"] == "Budi Rahardjo"

    # 2. Empty input handling
    res_empty = resolve_instructor_identity("CS", "")
    assert res_empty["is_resolved"] is False

    # 3. Memory quirks integration
    with AgentMemory(":memory:") as mem:
        mem.set_instructor_preference("CS", "Ada Lovelace", {"preferred_days": ["T", "R"]})
        res_mem = resolve_instructor_identity("CS", "Dr. Ada Lovelace", memory_instance=mem)
        assert res_mem["canonical_name"] == "Ada Lovelace"
        assert res_mem["confidence"] == 1.0
        assert res_mem["preferences"]["preferred_days"] == ["T", "R"]


def test_record_learned_resolution() -> None:
    """Test recording learned disambiguations and automatic room alias update."""
    with AgentMemory(":memory:") as mem:
        res = record_learned_resolution(
            dept="IF",
            issue_sig="room_alias:Lab1",
            question="Which lab does Lab1 refer to?",
            choice="Labtek V 7601",
            fix={"canonical_room": "Labtek V 7601"},
            memory_instance=mem,
        )
        assert res["success"] is True
        assert res["record_id"] > 0

        # Check that room alias was automatically recorded
        assert mem.get_room_alias("IF", "Lab1") == "Labtek V 7601"

        # Check resolution history
        prev = mem.find_previous_resolution("IF", "room_alias:Lab1")
        assert "Labtek V 7601" in prev


def test_check_time_conflict() -> None:
    """Test detecting room and instructor scheduling overlaps."""
    # 1. Room collision
    overlapping_classes = [
        {
            "course": "CS101",
            "section": "1",
            "days": "MWF",
            "startTime": "08:00",
            "endTime": "09:30",
            "room": "HAAS G066",
            "instructor": "Alice",
        },
        {
            "course": "CS201",
            "section": "1",
            "days": "M",
            "startTime": "09:00",
            "endTime": "10:30",
            "room": "HAAS G066",
            "instructor": "Bob",
        },
    ]
    res_conflict = check_time_conflict(overlapping_classes)
    assert res_conflict["has_conflict"] is True
    assert res_conflict["total_conflicts"] == 1
    assert res_conflict["conflicts"][0]["conflict_type"] == "room_double_booking"

    # 2. Instructor collision
    instructor_conflict = [
        {
            "course": "MATH101",
            "section": "1",
            "days": "TR",
            "startTime": "10:00",
            "endTime": "11:30",
            "room": "PHYS 112",
            "instructor": "Dr. Euler",
        },
        {
            "course": "MATH201",
            "section": "1",
            "days": "T",
            "startTime": "10:30",
            "endTime": "12:00",
            "room": "PHYS 114",
            "instructor": "Dr. Euler",
        },
    ]
    res_ins = check_time_conflict(instructor_conflict)
    assert res_ins["has_conflict"] is True
    assert res_ins["conflicts"][0]["conflict_type"] == "instructor_double_booking"

    # 3. No conflict (different days or separated time)
    clear_classes = [
        {
            "course": "CS101",
            "section": "1",
            "days": "M",
            "startTime": "08:00",
            "endTime": "09:00",
            "room": "HAAS 111",
        },
        {
            "course": "CS102",
            "section": "1",
            "days": "T",
            "startTime": "08:00",
            "endTime": "09:00",
            "room": "HAAS 111",
        },
    ]
    res_clear = check_time_conflict(clear_classes)
    assert res_clear["has_conflict"] is False


def test_generate_admin_summary() -> None:
    """Test generating administrator summary from agent state."""
    state = create_initial_state("/data/courses.pdf", "pdf")
    state["unified_payload"] = {
        "courses": [
            {
                "courseNumber": "CS101",
                "configurations": [
                    {
                        "subparts": [
                            {"classes": [{"sectionName": "1"}, {"sectionName": "2"}]}
                        ]
                    }
                ],
            }
        ],
        "distributionConstraints": [{"type": "SAME_ROOM"}],
    }
    state["validation_result"] = {
        "is_valid": False,
        "errors": [{"message": "startTime must be earlier than endTime."}],
        "warnings": ["Duplicate instructor share."],
    }
    state["ambiguities"] = [{"question": "Assign room for Section 1?"}]
    state["status"] = STATUS_WAITING_FOR_HUMAN

    summary = generate_admin_summary(state)
    assert summary["status"] == STATUS_WAITING_FOR_HUMAN
    assert summary["stats"]["total_courses"] == 1
    assert summary["stats"]["total_classes"] == 2
    assert summary["stats"]["validation_passed"] is False
    assert summary["stats"]["errors_count"] == 1
    assert summary["stats"]["ambiguities_count"] == 1

    md = summary["summary_markdown"]
    assert "UniTime Smart Ingestion - Administrative Summary" in md
    assert "WAITING FOR HUMAN REVIEW" in md
    assert "startTime must be earlier than endTime." in md
    assert "Assign room for Section 1?" in md


def test_all_tools_in_toolnode() -> None:
    """Verify that all exported tools integrate properly with LangGraph ToolNode."""
    tool_node = ToolNode(ALL_TOOLS)
    assert tool_node is not None
    assert len(ALL_TOOLS) == 11

    # Direct positional execution
    room_check = inspect_room_capacity("HAAS", "G066", 50)
    assert room_check["is_sufficient"] is True

    # Tool invoke execution
    room_invoke = inspect_room_capacity.invoke(
        {"building": "HAAS", "room_number": "G066", "required_cap": 50}
    )
    assert room_invoke["is_sufficient"] is True


def test_check_time_conflict_nested_schema() -> None:
    """Test check_time_conflict with full UniTime schema structure."""
    nested_classes = [
        {
            "courseNumber": "CS180",
            "sectionName": "Lecture 1",
            "timePreferences": [
                {"dayCode": "MWF", "startTime": "09:30", "endTime": "10:20"}
            ],
            "roomPreferences": [
                {"building": "HAAS", "roomNumber": "G066", "preference": "REQUIRED"}
            ],
            "instructors": [{"name": "Prof. Smith", "sharePercentage": 100}],
        },
        {
            "courseNumber": "CS240",
            "sectionName": "Lecture 1",
            "timePreferences": [
                {"dayCode": "W", "startTime": "09:00", "endTime": "10:00"}
            ],
            "roomPreferences": [
                {"building": "HAAS", "roomNumber": "G066", "preference": "REQUIRED"}
            ],
            "instructors": [{"name": "Prof. Jones", "sharePercentage": 100}],
        },
    ]
    res = check_time_conflict(nested_classes)
    assert res["has_conflict"] is True
    assert res["total_conflicts"] == 1
    assert res["conflicts"][0]["conflict_type"] == "room_double_booking"
    assert "HAAS G066" in res["conflicts"][0]["resource"]


def test_agent_memory_custom_department_knowledge() -> None:
    """Test generic department knowledge setting and retrieval."""
    with AgentMemory(":memory:") as mem:
        mem.set_department_knowledge("CS", "curriculum_rule", "max_sks_semester", "24")
        val = mem.get_department_knowledge("CS", "curriculum_rule", "max_sks_semester")
        assert val == "24"

        # Wildcard knowledge
        mem.set_department_knowledge("*", "university_policy", "term", "Fall 2026")
        term_val = mem.get_department_knowledge("MATH", "university_policy", "term")
        assert term_val == "Fall 2026"


# =============================================================================
# Graph, Reporter & Runner Integration Tests
# =============================================================================


def test_write_admin_report_output(tmp_path: Path) -> None:
    """Verify executive markdown report generation with all required sections."""
    state = create_initial_state("/path/to/test_curriculum.txt")
    state["unified_payload"] = {
        "department": {"code": "IF", "name": "Teknik Informatika"},
        "subjectArea": {"abbreviation": "IF", "title": "Teknik Informatika"},
        "courses": [
            {
                "courseNumber": "IF2110",
                "title": "Algoritma dan Pemrograman",
                "configurations": [
                    {
                        "subparts": [
                            {
                                "classes": [
                                    {
                                        "sectionName": "K01",
                                        "instructors": [{"name": "Dr. Ayu Pratama"}],
                                    },
                                    {
                                        "sectionName": "K02",
                                        "instructors": [{"name": "Budi Raharjo"}],
                                    },
                                ]
                            }
                        ]
                    }
                ],
            }
        ],
        "distributionConstraints": [{"type": "CANNOT_OVERLAP"}],
    }
    state["validation_result"] = {
        "is_valid": True,
        "errors": [],
        "warnings": ["Section K02 room assignment pending"],
    }
    state["ambiguities"] = [
        {
            "id": "room_cap_1",
            "issue_signature": "room_capacity:Labtek V 7601",
            "type": "room_capacity",
            "question": "Room capacity exceeded for section K01. Allow overflow?",
            "options": ["Allow overflow", "Reassign room"],
        }
    ]
    state["human_response"] = "Allow overflow"
    state["ingest_result"] = {
        "status": "SUCCESS",
        "http_status_code": 200,
        "message": "Committed successfully",
    }
    state["status"] = STATUS_COMPLETED
    state["audit_logs"] = [
        {"timestamp": "2026-09-11 12:00:00", "level": "INFO", "message": "Pipeline started"},
        {"timestamp": "2026-09-11 12:00:05", "level": "FIX", "message": "Applied room alias"},
    ]

    report_path = write_admin_report(state, output_dir=tmp_path)
    assert report_path.is_file()
    assert report_path.name.startswith("audit_report_")
    assert report_path.suffix == ".md"

    content = report_path.read_text(encoding="utf-8")
    assert "UniTime AI Ingestion Gateway - Executive Audit Report" in content
    assert "IF2110" in content
    assert "Algoritma dan Pemrograman" in content
    assert "Dr. Ayu Pratama" in content
    assert "Allow overflow" in content
    assert "Actionable Administrator Recommendations" in content
    assert "Execution Audit Journal" in content


def test_graph_execution_clean_document(tmp_path: Path) -> None:
    """Verify full end-to-end LangGraph execution on a clean document without interrupts."""
    sample_file = tmp_path / "clean_memo.txt"
    sample_file.write_text(
        "MATA KULIAH TEKNIK INFORMATIKA\n"
        "IF2110 Algoritma dan Struktur Data (4 SKS)\n"
        "Kelas K01: Senin 07.00 - 09.30, Ruang Labtek V 7601, Dosen: Dr. Eng. Ayu Pratama\n",
        encoding="utf-8",
    )

    reports_dir = tmp_path / "reports"
    db_file = tmp_path / "agent_memory.db"

    state = create_initial_state(
        document_path=str(sample_file),
        memory_context={
            "provider": "mock",
            "dry_run": True,
            "reports_dir": str(reports_dir),
            "memory_db_path": str(db_file),
        },
    )

    app = build_ingest_graph()
    config = {"configurable": {"thread_id": "clean_doc_thread"}}

    events = list(app.stream(state, config=config))
    assert len(events) >= 5

    final_state = app.get_state(config)
    assert final_state.next == ()
    values = final_state.values

    assert values["status"] == STATUS_COMPLETED
    assert len(values["slices"]) >= 1
    assert values["current_slice_index"] == len(values["slices"])
    assert values["unified_payload"] is not None
    assert len(values["unified_payload"]["courses"]) >= 1
    assert values["validation_result"]["is_valid"] is True
    assert values["ambiguities"] == []
    assert values["ingest_result"]["status"] == "DRY_RUN"

    # Verify report was generated
    report_files = list(reports_dir.glob("audit_report_*.md"))
    assert len(report_files) == 1
    assert "IF2110" in report_files[0].read_text(encoding="utf-8")


def test_graph_execution_with_interrupt_and_resume(tmp_path: Path) -> None:
    """Verify LangGraph pause on interrupt and successful resume with human feedback."""
    from unittest.mock import MagicMock, patch

    sample_file = tmp_path / "conflict_doc.txt"
    sample_file.write_text("Curriculum with conflict", encoding="utf-8")

    reports_dir = tmp_path / "reports"
    db_file = tmp_path / "agent_memory.db"

    # Seed mock payload with room capacity exceeding capacity (100 seats needed in 60-seat room)
    mock_conflict_payload = {
        "department": {"code": "IF", "name": "Informatika"},
        "courses": [
            {
                "courseNumber": "IF2110",
                "title": "Algoritma",
                "configurations": [
                    {
                        "subparts": [
                            {
                                "classes": [
                                    {
                                        "sectionName": "K01",
                                        "capacity": 100,
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

    state = create_initial_state(
        document_path=str(sample_file),
        memory_context={
            "provider": "mock",
            "dry_run": True,
            "reports_dir": str(reports_dir),
            "memory_db_path": str(db_file),
        },
    )

    app = build_ingest_graph()
    config = {"configurable": {"thread_id": "interrupt_resume_thread"}}

    with patch("agent.nodes.get_extractor") as mock_get_ext:
        mock_ext = MagicMock()
        mock_ext.extract_text.return_value = MagicMock(
            payload=mock_conflict_payload,
            provider="mock",
            model="mock-v1",
        )
        mock_get_ext.return_value = mock_ext

        # 1. Stream until interrupt triggers
        initial_events = list(app.stream(state, config=config))
        interrupted_state = app.get_state(config)

        assert interrupted_state.next == ("human_interrupt",)
        assert len(interrupted_state.tasks) > 0
        task = interrupted_state.tasks[0]
        assert task.interrupts is not None and len(task.interrupts) > 0
        interrupt_val = task.interrupts[0].value
        assert "ambiguities" in interrupt_val
        assert len(interrupt_val["ambiguities"]) == 1
        assert interrupt_val["ambiguities"][0]["type"] == "room_capacity"

        # 2. Resume execution using Command(resume=...)
        resume_events = list(app.stream(Command(resume="Allow overflow (keep room)"), config=config))
        assert len(resume_events) >= 3

        # 3. Verify cyclic re-validation and successful completion
        final_state = app.get_state(config)
        assert final_state.next == ()
        final_values = final_state.values

        assert final_values["status"] == STATUS_COMPLETED
        assert final_values["ambiguities"] == []
        assert final_values["ingest_result"]["status"] == "DRY_RUN"

        # Verify resolution was persisted into persistent SQLite memory
        with AgentMemory(db_file) as mem:
            sig = interrupt_val["ambiguities"][0]["issue_signature"]
            res = mem.find_previous_resolution("IF", sig)
            assert res == "Allow overflow (keep room)"


def test_run_agent_pipeline_execution(tmp_path: Path) -> None:
    """Verify runner.py run_agent_pipeline integration in auto-resolve mode."""
    sample_file = tmp_path / "pipeline_doc.txt"
    sample_file.write_text("IF2110 ASD 4 SKS", encoding="utf-8")

    reports_dir = tmp_path / "reports"
    db_file = tmp_path / "memory.db"

    final_state = run_agent_pipeline(
        document_path=sample_file,
        provider="mock",
        dry_run=True,
        interactive=False,
        reports_dir=reports_dir,
        memory_db_path=db_file,
    )

    assert final_state["status"] == STATUS_COMPLETED
    assert final_state["unified_payload"] is not None
    assert len(list(reports_dir.glob("audit_report_*.md"))) == 1


def test_record_learned_resolution_resource_cleanup(tmp_path: Path, monkeypatch) -> None:
    """Verify that record_learned_resolution safely manages and closes local AgentMemory."""
    db_file = tmp_path / "cleanup_test.db"
    monkeypatch.setenv("UNITIME_AGENT_MEMORY_DB", str(db_file))

    res = record_learned_resolution(
        dept="CS",
        issue_sig="room_alias:CL50",
        question="Which room?",
        choice="CL50 224",
        fix={"canonical_room": "CL50 224"},
        memory_instance=None,
    )
    assert res["success"] is True
    assert res["record_id"] > 0
    assert db_file.exists()

    # Verify data was committed and connection can be reopened without lock
    with AgentMemory(db_file) as mem:
        canon = mem.get_room_alias("CS", "CL50")
        assert canon == "CL50 224"


def test_check_time_conflict_with_course_and_payload_dicts() -> None:
    """Verify that check_time_conflict extracts meetings from course and payload dictionaries."""
    course_item = {
        "courseNumber": "IF2210",
        "configurations": [
            {
                "subparts": [
                    {
                        "classes": [
                            {
                                "sectionName": "K01",
                                "roomPreferences": [{"building": "Labtek V", "roomNumber": "7601"}],
                                "timePreferences": [{"dayCode": "M", "startTime": "08:00", "endTime": "10:00"}],
                            }
                        ]
                    }
                ]
            }
        ],
    }
    payload_item = {
        "courses": [
            {
                "courseNumber": "IF2220",
                "configurations": [
                    {
                        "subparts": [
                            {
                                "classes": [
                                    {
                                        "sectionName": "K01",
                                        "roomPreferences": [{"building": "Labtek V", "roomNumber": "7601"}],
                                        "timePreferences": [{"dayCode": "M", "startTime": "09:00", "endTime": "11:00"}],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    res = check_time_conflict([course_item, payload_item])
    assert res["has_conflict"] is True
    assert res["total_conflicts"] == 1
    assert res["conflicts"][0]["conflict_type"] == "room_double_booking"
    assert "LABTEK V 7601" in res["conflicts"][0]["resource"]


def test_graph_error_propagation_on_slice_failure(tmp_path: Path) -> None:
    """Verify that slicing error preserves STATUS_ERROR, bypasses submit, and writes error report."""
    non_existent = tmp_path / "does_not_exist.pdf"
    reports_dir = tmp_path / "err_reports"

    state = create_initial_state(
        document_path=str(non_existent),
        memory_context={
            "provider": "mock",
            "dry_run": False,
            "submit": True,  # Submit enabled, but must be bypassed on error
            "reports_dir": str(reports_dir),
        },
    )

    app = build_ingest_graph()
    config = {"configurable": {"thread_id": "error_propagation_thread"}}

    events = list(app.stream(state, config=config))
    assert len(events) >= 3

    final_state = app.get_state(config)
    assert final_state.next == ()
    values = final_state.values

    assert values["status"] == STATUS_ERROR
    # Verify submit was not successfully executed
    assert values["ingest_result"] is None or values["ingest_result"]["status"] == "ABORTED_ON_ERROR"

    # Verify error report was generated
    err_reports = list(reports_dir.glob("audit_report_*.md"))
    assert len(err_reports) == 1
    content = err_reports[0].read_text(encoding="utf-8")
    assert "Executive Audit Report" in content
    assert "Status: Error" in content or "ERROR" in content



# =============================================================================
# Advanced Feature Fixes Tests
# =============================================================================

def test_phantom_fix_mutation() -> None:
    from agent.nodes import apply_feedback_node
    from agent.state import create_initial_state
    
    state = create_initial_state("doc.txt")
    
    state["unified_payload"] = {
        "courses": [{
            "courseNumber": "CS101",
            "configurations": [{"subparts": [{"classes": [{"sectionName": "1", "capacity": 100}]}]}]
        }]
    }
    state["ambiguities"] = [{
        "id": "capacity_CS101_1",
        "type": "room_capacity",
        "issue_signature": "room_capacity:CS101:HAAS:1",
        "context": {"courseNumber": "CS101", "room_name": "HAAS"}
    }]
    state["human_response"] = {"capacity_CS101_1": "Reassign HAAS 101"}
    
    res = apply_feedback_node(state)
    payload = res["unified_payload"]
    cls = payload["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]
    
    assert cls.get("capacity_override") is True

def test_phantom_fix_time_conflict_mutation() -> None:
    from agent.nodes import apply_feedback_node
    from agent.state import create_initial_state
    
    state = create_initial_state("doc.txt")
    
    state["unified_payload"] = {
        "courses": [{
            "courseNumber": "CS101",
            "configurations": [{"subparts": [{"classes": [{"sectionName": "1", "capacity": 100}]}]}]
        }]
    }
    state["ambiguities"] = [{
        "id": "conflict_room",
        "type": "time_conflict",
        "issue_signature": "time_conflict:room:1:2:3",
        "context": {"class_a": "1", "class_b": "2"}
    }]
    state["human_response"] = {"conflict_room": "Reschedule Class A"}
    
    res = apply_feedback_node(state)
    payload = res["unified_payload"]
    cls = payload["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]
    
    # We check if it marked resolved time preferences
    assert len(cls.get("timePreferences", [])) > 0
    assert cls["timePreferences"][0]["resolved"] is True


def test_strict_course_scoping_for_mutations() -> None:
    from agent.nodes import apply_feedback_node
    from agent.state import create_initial_state
    
    state = create_initial_state("doc.txt")
    
    state["unified_payload"] = {
        "courses": [
            {
                "courseNumber": "CS101",
                "configurations": [{"subparts": [{"classes": [{"sectionName": "1", "capacity": 100}]}]}]
            },
            {
                "courseNumber": "MATH202",
                "configurations": [{"subparts": [{"classes": [{"sectionName": "1", "capacity": 100}]}]}]
            }
        ]
    }
    
    # We resolve a conflict for CS101 Section 1, MATH202 Section 1 should NOT be touched
    state["ambiguities"] = [{
        "id": "conflict_room",
        "type": "time_conflict",
        "issue_signature": "time_conflict:room:CS101:2:3",
        "context": {"class_a": "1", "class_a_course": "CS101", "class_a_section": "1"}
    }]
    state["human_response"] = {"conflict_room": "Reschedule Class A"}
    
    res = apply_feedback_node(state)
    payload = res["unified_payload"]
    
    cs_cls = payload["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]
    math_cls = payload["courses"][1]["configurations"][0]["subparts"][0]["classes"][0]
    
    # CS101 was rescheduled
    assert len(cs_cls.get("timePreferences", [])) > 0
    assert cs_cls["timePreferences"][0]["resolved"] is True
    
    # MATH202 was untouched
    assert "timePreferences" not in math_cls
