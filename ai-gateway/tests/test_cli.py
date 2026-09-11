"""Tests for UniTime AI Ingestion Gateway - CLI."""

import json
from pathlib import Path
import subprocess
import sys

GATEWAY_DIR = Path(__file__).resolve().parent.parent
SAMPLE_MEMO = GATEWAY_DIR / "sample_inputs" / "memo_jadwal_if.txt"
SAMPLE_EXCEL = GATEWAY_DIR / "sample_inputs" / "jadwal_kuliah_if.xlsx"
SAMPLE_PDF = GATEWAY_DIR / "sample_inputs" / "jadwal_kuliah_if.pdf"


def test_cli_dry_run_memo(tmp_path):
    out_json = tmp_path / "memo_out.json"
    cmd = [
        sys.executable,
        str(GATEWAY_DIR / "ingest.py"),
        "-i", str(SAMPLE_MEMO),
        "--dry-run",
        "--mock",
        "-o", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Schema and Semantic Validation PASSED" in res.stdout
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "courses" in payload
    assert len(payload["courses"]) >= 1


def test_cli_dry_run_excel(tmp_path):
    out_json = tmp_path / "excel_out.json"
    cmd = [
        sys.executable,
        str(GATEWAY_DIR / "ingest.py"),
        "-i", str(SAMPLE_EXCEL),
        "--dry-run",
        "--mock",
        "-o", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Schema and Semantic Validation PASSED" in res.stdout
    assert out_json.exists()


def test_cli_dry_run_pdf(tmp_path):
    out_json = tmp_path / "pdf_out.json"
    cmd = [
        sys.executable,
        str(GATEWAY_DIR / "ingest.py"),
        "-i", str(SAMPLE_PDF),
        "--dry-run",
        "--mock",
        "-o", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Schema and Semantic Validation PASSED" in res.stdout
    assert out_json.exists()


def test_cli_agent_mode(tmp_path):
    out_json = tmp_path / "agent_out.json"
    cmd = [
        sys.executable,
        str(GATEWAY_DIR / "ingest.py"),
        "-i", str(SAMPLE_MEMO),
        "-a",
        "--mock",
        "--dry-run",
        "--no-interactive",
        "-o", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "UniTime Smart Ingestion Agent" in res.stdout
    assert "COMPLETED" in res.stdout
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "courses" in payload
    assert len(payload["courses"]) >= 1


def test_cli_agent_mode_with_custom_dirs(tmp_path):
    out_json = tmp_path / "custom_agent_out.json"
    rep_dir = tmp_path / "custom_reports"
    mem_db = tmp_path / "custom_memory.db"

    cmd = [
        sys.executable,
        str(GATEWAY_DIR / "ingest.py"),
        "-i", str(SAMPLE_MEMO),
        "-a",
        "--mock",
        "--dry-run",
        "--no-interactive",
        "--reports-dir", str(rep_dir),
        "--memory-db", str(mem_db),
        "-o", str(out_json),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "COMPLETED" in res.stdout
    assert out_json.exists()
    assert mem_db.exists()
    assert rep_dir.exists()
    assert len(list(rep_dir.glob("audit_report_*.md"))) == 1

