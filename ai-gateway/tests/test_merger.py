"""Tests for UniTime AI Ingestion Gateway - Merger."""

import pytest
from core.merger import Merger


@pytest.fixture
def merger():
    return Merger()


def test_merger_combines_same_course_different_classes(merger):
    chunk1 = {
        "academicSession": {"year": "2024-2025", "term": "Ganjil", "campus": "Kampus Ganesha"},
        "department": {"code": "IF", "name": "Teknik Informatika"},
        "subjectArea": {"abbreviation": "IF", "title": "Informatika"},
        "courses": [
            {
                "courseNumber": "IF2110",
                "title": "Algoritma dan Pemrograman",
                "credit": {"units": 4},
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
                                        "capacity": 45,
                                        "instructors": [{"id": "1001", "name": "Dosen A", "isLead": True, "sharePercentage": 100}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }

    chunk2 = {
        "courses": [
            {
                "courseNumber": "IF2110",
                "configurations": [
                    {
                        "name": "Default",
                        "subparts": [
                            {
                                "type": "Lecture",
                                "classes": [
                                    {
                                        "sectionName": "K02",
                                        "capacity": 45,
                                        "instructors": [{"id": "1002", "name": "Dosen B", "isLead": True, "sharePercentage": 100}],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    merged = merger.merge([chunk1, chunk2])
    assert len(merged["courses"]) == 1
    course = merged["courses"][0]
    subpart = course["configurations"][0]["subparts"][0]
    assert len(subpart["classes"]) == 2
    section_names = [c["sectionName"] for c in subpart["classes"]]
    assert "K01" in section_names
    assert "K02" in section_names


def test_merger_deduplicates_distribution_constraints(merger):
    chunk1 = {
        "distributionConstraints": [
            {
                "type": "CANNOT_OVERLAP",
                "level": "REQUIRED",
                "classes": [
                    {"courseNumber": "IF2110", "sectionName": "K01"},
                    {"courseNumber": "IF2110", "sectionName": "K02"},
                ],
                "note": "First note",
            }
        ]
    }
    chunk2 = {
        "distributionConstraints": [
            {
                "type": "DIFF_TIME",
                "level": "REQUIRED",
                "classes": [
                    {"courseNumber": "IF2110", "sectionName": "K02"},
                    {"courseNumber": "IF2110", "sectionName": "K01"},
                ],
                "note": "Second note",
            }
        ]
    }

    merged = merger.merge([chunk1, chunk2])
    constraints = merged["distributionConstraints"]
    assert len(constraints) == 1
    assert "First note" in constraints[0]["note"]
    assert "Second note" in constraints[0]["note"]


def test_merger_recalculates_teaching_shares(merger):
    # Class with 3 instructors without predefined valid shares
    instructors = [
        {"id": "101", "name": "Lead", "isLead": True},
        {"id": "102", "name": "Member 1", "isLead": False},
        {"id": "103", "name": "Member 2", "isLead": False},
    ]
    merger._recalculate_shares(instructors)
    # N=3: lead=34%, members=33% each -> sum = 100%
    assert instructors[0]["sharePercentage"] == 34
    assert instructors[1]["sharePercentage"] == 33
    assert instructors[2]["sharePercentage"] == 33
    assert sum(i["sharePercentage"] for i in instructors) == 100


def test_merger_cross_chunk_conflict_detection(merger):
    chunk1 = {
        "academicSession": {"year": "2024-2025", "term": "Ganjil", "campus": "Kampus Ganesha"},
        "department": {"code": "IF", "name": "Teknik Informatika"},
        "subjectArea": {"abbreviation": "IF", "title": "Informatika"},
    }
    chunk2 = {
        "academicSession": {"year": "2024-2025", "term": "Genap", "campus": "Kampus Ganesha"},
        "department": {"code": "EL", "name": "Teknik Elektro"},
        "subjectArea": {"abbreviation": "EL", "title": "Elektro"},
    }
    merged = merger.merge([chunk1, chunk2])
    assert len(merger.conflicts) == 5
    assert any("Academic session conflict for 'term'" in c for c in merger.conflicts)
    assert any("Department conflict for 'code'" in c for c in merger.conflicts)
    assert any("Subject area conflict for 'abbreviation'" in c for c in merger.conflicts)
    # Target retains base values
    assert merged["academicSession"]["term"] == "Ganjil"
    assert merged["department"]["code"] == "IF"
    assert merged["subjectArea"]["abbreviation"] == "IF"


def test_merger_normalizes_base_payload_constraint_aliases():
    merger = Merger(normalize_constraint_aliases=True)
    chunk = {
        "distributionConstraints": [
            {
                "type": "CANNOT_OVERLAP",
                "classes": [
                    {"courseNumber": "IF2110", "sectionName": "K01"},
                    {"courseNumber": "IF2110", "sectionName": "K02"},
                ],
            }
        ]
    }
    merged = merger.merge([chunk])
    assert merged["distributionConstraints"][0]["type"] == "DIFF_TIME"


def test_merger_enforces_single_lead_instructor(merger):
    # Multiple instructors marked as isLead=True
    instructors = [
        {"id": "101", "name": "Prof A", "isLead": True},
        {"id": "102", "name": "Dr B", "isLead": True},
        {"id": "103", "name": "Dr C", "isLead": False},
    ]
    merger._recalculate_shares(instructors)
    lead_count = sum(1 for ins in instructors if ins.get("isLead") is True)
    assert lead_count == 1
    assert instructors[0]["isLead"] is True
    assert instructors[1]["isLead"] is False
    assert instructors[2]["isLead"] is False
    assert sum(ins["sharePercentage"] for ins in instructors) == 100


def test_merger_n_instructors_shares_all_n(merger):
    for n in range(1, 15):
        instructors = [{"id": f"ins_{i}", "name": f"Teacher {i}"} for i in range(n)]
        merger._recalculate_shares(instructors)
        total = sum(ins["sharePercentage"] for ins in instructors)
        assert total == 100, f"Failed for N={n}: sum is {total}"
        assert instructors[0]["isLead"] is True
        for ins in instructors[1:]:
            assert ins["isLead"] is False


def test_merger_concatenates_schedule_notes(merger):
    chunk1 = {
        "courses": [{"courseNumber": "IF2110", "configurations": [{"name": "Default", "subparts": [{"type": "Lecture", "classes": [{"sectionName": "K01", "scheduleNote": "First part"}]}]}]}]
    }
    chunk2 = {
        "courses": [{"courseNumber": "IF2110", "configurations": [{"name": "Default", "subparts": [{"type": "Lecture", "classes": [{"sectionName": "K01", "scheduleNote": "Second part"}]}]}]}]
    }
    merged = merger.merge([chunk1, chunk2])
    cls = merged["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]
    assert cls["scheduleNote"] == "First part; Second part"

def test_merger_sequential_repeated_note_merging(merger):
    chunk1 = {
        "courses": [{"courseNumber": "IF2110", "configurations": [{"name": "Default", "subparts": [{"type": "Lecture", "classes": [{"sectionName": "K01", "scheduleNote": "First part"}]}]}]}]
    }
    chunk2 = {
        "courses": [{"courseNumber": "IF2110", "configurations": [{"name": "Default", "subparts": [{"type": "Lecture", "classes": [{"sectionName": "K01", "scheduleNote": "Second part"}]}]}]}]
    }
    chunk3 = {
        "courses": [{"courseNumber": "IF2110", "configurations": [{"name": "Default", "subparts": [{"type": "Lecture", "classes": [{"sectionName": "K01", "scheduleNote": "Second part"}]}]}]}]
    }
    merged = merger.merge([chunk1, chunk2, chunk3])
    cls = merged["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]
    assert cls["scheduleNote"] == "First part; Second part"

