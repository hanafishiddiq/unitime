"""Tests for UniTime AI Ingestion Gateway - Client."""

import pytest
from core.client import UniTimeClient, IngestClientResponse


def test_client_headers_basic():
    client = UniTimeClient(username="testuser", password="secretpassword")
    headers = client._build_headers()
    assert headers["Content-Type"] == "application/json"
    auth = client._get_auth()
    assert auth is not None
    assert auth._auth_header.startswith("Basic ")


def test_client_headers_token():
    client = UniTimeClient(token="jwt-or-api-token")
    headers = client._build_headers()
    assert headers["Authorization"] == "Bearer jwt-or-api-token"
    auth = client._get_auth()
    assert auth is None


def test_client_parse_success_response():
    data = {
        "status": "SUCCESS",
        "timestamp": "2026-09-11T12:00:00Z",
        "academicSession": {"year": "2024-2025", "term": "Ganjil", "campus": "Kampus Ganesha"},
        "department": "Teknik Informatika",
        "subjectArea": "IF",
        "summary": {
            "coursesCount": 3,
            "classesCount": 6,
            "distributionConstraintsCount": 2,
            "warningsCount": 0,
            "errorsCount": 0,
        },
        "coursesImported": [
            {"courseNumber": "IF2110", "title": "Algoritma", "configurationsCount": 1, "classesCount": 2}
        ],
        "logs": [
            {"level": "INFO", "message": "Import finished successfully."}
        ],
    }
    resp = UniTimeClient._parse_ingest_response(data, 200)
    assert resp.is_success is True
    assert resp.has_warnings is False
    assert resp.summary.courses_count == 3
    assert len(resp.courses_imported) == 1
    assert "SUCCESS" in resp.summary_text()


def test_client_parse_failure_response():
    data = {
        "status": "FAILED",
        "error": "Session not found",
        "summary": {"errorsCount": 1},
    }
    resp = UniTimeClient._parse_ingest_response(data, 400)
    assert resp.is_success is False
    assert resp.error == "Session not found"
