"""Tests for UniTime AI Ingestion Gateway - Extractor."""

import pytest
from core.extractor import MockExtractor, get_extractor, repair_and_parse_json, ExtractionParsingError


def test_repair_and_parse_json_valid():
    raw = '{"courses": [{"courseNumber": "IF2110"}]}'
    result = repair_and_parse_json(raw)
    assert result["courses"][0]["courseNumber"] == "IF2110"


def test_repair_and_parse_json_with_fences_and_trailing_commas():
    raw = """```json
    {
      "department": {"code": "IF", "name": "Informatika",},
      "courses": [
        {"courseNumber": "IF2110", "title": 'Algoritma',}
      ],
    }
    ```"""
    result = repair_and_parse_json(raw)
    assert result["department"]["code"] == "IF"
    assert result["courses"][0]["courseNumber"] == "IF2110"


def test_repair_and_parse_json_invalid_raises():
    with pytest.raises(ExtractionParsingError):
        repair_and_parse_json("This is purely conversational text with no JSON braces.")


def test_mock_extractor_text():
    extractor = get_extractor("mock")
    assert isinstance(extractor, MockExtractor)
    result = extractor.extract_text("Kuliah IF2110 Algoritma dan Struktur Data")
    assert result.provider == "mock"
    assert len(result.payload["courses"]) >= 1
    assert result.payload["courses"][0]["courseNumber"] == "IF2110"


def test_mock_extractor_image():
    extractor = MockExtractor()
    dummy_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    result = extractor.extract_image(dummy_bytes, mime_type="image/png")
    assert result.provider == "mock"
    assert "courses" in result.payload

def test_repair_and_parse_json_escaped_single_quotes():
    raw = "{'title': 'O\\'Reilly\\'s Book', 'desc': 'A \\'great\\' read'}"
    result = repair_and_parse_json(raw)
    assert result["title"] == "O'Reilly's Book"
    assert result["desc"] == "A 'great' read"

def test_repair_and_parse_json_empty_strings_and_arrays():
    raw = "{'empty': '', 'arr': ['a', 'b']}"
    result = repair_and_parse_json(raw)
    assert result["empty"] == ""
    assert result["arr"] == ["a", "b"]
