"""Tests for UniTime AI Ingestion Gateway - Validator."""

import json
from pathlib import Path
import pytest

from core.validator import Validator, ValidationResult

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "Documentation" / "ai-integration" / "unitime-smart-ingest-schema.json"
SAMPLE_PAYLOAD_PATH = Path(__file__).resolve().parent.parent.parent / "Documentation" / "ai-integration" / "sample-valid-payload.json"


@pytest.fixture
def validator():
    return Validator(schema_path=SCHEMA_PATH)


@pytest.fixture
def sample_payload():
    with open(SAMPLE_PAYLOAD_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_validator_sample_payload_passes(validator, sample_payload):
    result = validator.validate(sample_payload)
    assert result.is_valid is True
    assert len(result.errors) == 0


def test_validator_rejects_missing_required_fields(validator):
    incomplete = {
        "academicSession": {"year": "2024-2025", "term": "Ganjil", "campus": "Kampus Ganesha"}
    }
    result = validator.validate(incomplete)
    assert result.is_valid is False
    assert len(result.errors) >= 3
    error_msgs = " ".join(result.error_messages)
    assert "ingestControl" in error_msgs
    assert "department" in error_msgs
    assert "courses" in error_msgs


def test_validator_detects_invalid_time_order(validator, sample_payload):
    # Set endTime before startTime
    bad_payload = json.loads(json.dumps(sample_payload))
    tp = bad_payload["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["timePreferences"][0]
    tp["startTime"] = "10:00"
    tp["endTime"] = "08:00"

    result = validator.validate(bad_payload)
    assert result.is_valid is False
    assert any("earlier than endTime" in err.message for err in result.errors)


def test_validator_detects_invalid_instructor_share_percentage(validator, sample_payload):
    payload = json.loads(json.dumps(sample_payload))
    # Change first class instructors shares to 30% and 30% (sum 60% != 100%)
    instructors = payload["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["instructors"]
    instructors[0]["sharePercentage"] = 30
    instructors[1]["sharePercentage"] = 30

    result = validator.validate(payload)
    assert any("expected 100%" in w for w in result.warnings)


def test_validator_partial_payload(validator):
    partial = {
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
                                "classes": [{"sectionName": "K01", "capacity": 45}]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    result = validator.validate_partial(partial)
    assert result.is_valid is True


def test_validator_partial_payload_strict_elevates_warnings():
    strict_val = Validator(schema_path=SCHEMA_PATH, strict_semantics=True)
    partial_with_invalid_share = {
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
                                        "sectionName": "K01",
                                        "instructors": [
                                            {"id": "1", "name": "A", "sharePercentage": 40},
                                            {"id": "2", "name": "B", "sharePercentage": 40},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    result = strict_val.validate_partial(partial_with_invalid_share)
    assert result.is_valid is False
    assert any("expected 100%" in err.message for err in result.errors)

