"""UniTime AI Ingestion Gateway - FastAPI REST Server.

Provides a production-ready HTTP interface for the Next.js/Vercel frontend and external clients:
- Health check & UniTime connectivity status
- Document upload (PDF, Excel, CSV, TXT, JSON) with asynchronous background processing
- Job status polling with progress metrics, Human-in-the-Loop ambiguities, and course summary
- Administrative resolution of scheduling and capacity ambiguities
- Direct submission of canonical timetable payloads to the UniTime server
- Audit report listing and content retrieval
"""

from __future__ import annotations

import concurrent.futures
import copy
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import hmac
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure gateway root is in sys.path
GATEWAY_DIR = Path(__file__).resolve().parent
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))

# Load environment configuration
load_dotenv(GATEWAY_DIR / ".env")

from agent.chat_agent import ChatReActAgent
from agent.graph import build_ingest_graph
from agent.memory import AgentMemory
from agent.nodes import _create_log, _extract_all_classes
from agent.reporter import write_admin_report
from agent.state import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_PROCESSING,
    STATUS_WAITING_FOR_HUMAN,
    create_initial_state,
)
from agent.tools import check_time_conflict, inspect_room_capacity
from core.client import (
    UniTimeClient,
    UniTimeClientError,
    UniTimeConnectionError,
    UniTimeResponseError,
)
from core.validator import Validator
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

logger = logging.getLogger("ai-gateway.server")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", str(GATEWAY_DIR / "reports")))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DB_PATH = Path(os.getenv("UNITIME_AGENT_MEMORY_DB", str(GATEWAY_DIR / "data" / "agent_memory.db")))
MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".xlsx",
    ".xlsm",
    ".xls",
    ".csv",
    ".tsv",
    ".txt",
    ".md",
    ".json",
    ".log",
}

# Thread pool for asynchronous background job execution
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)


# =============================================================================
# Pydantic Request & Response Schemas
# =============================================================================


class UniTimeStatus(BaseModel):
    """Health check status for UniTime REST connectivity."""

    connected: bool = Field(..., description="Whether UniTime server is reachable.")
    url: str = Field(..., description="Target UniTime API URL checked.")
    details: Optional[Dict[str, Any]] = Field(None, description="Response metadata from UniTime health check.")
    error: Optional[str] = Field(None, description="Error message if connectivity check failed.")


class HealthResponse(BaseModel):
    """System health response model."""

    status: str = Field("ok", description="Overall gateway status.")
    provider: str = Field(..., description="Configured default LLM provider.")
    unitime: UniTimeStatus = Field(..., description="UniTime server connectivity check.")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp of the health check.")


class UploadResponse(BaseModel):
    """Response returned upon initiating a file upload."""

    job_id: str = Field(..., description="Unique ingestion job identifier.")
    filename: str = Field(..., description="Original name of the uploaded document.")
    status: str = Field(..., description="Initial job state ('queued' or 'processing').")
    message: str = Field(..., description="Human-readable acknowledgement message.")


class ProgressMetrics(BaseModel):
    """Progress metrics for an ongoing or completed ingestion job."""

    stage: str = Field("queued", description="Current pipeline stage.")
    current_chunk: int = Field(0, description="Index of the chunk currently being processed.")
    total_chunks: int = Field(0, description="Total number of document chunks.")
    percent: int = Field(0, description="Estimated completion percentage (0-100).")
    message: str = Field("", description="Status message describing the current stage.")


class CourseSummaryItem(BaseModel):
    """Condensed course offering information."""

    course_number: str = Field(..., description="Course code/number (e.g. IF2110).")
    title: str = Field("", description="Descriptive title of the course.")
    subject_area: str = Field("", description="Subject area abbreviation.")
    configurations_count: int = Field(0, description="Total configuration structures.")
    classes_count: int = Field(0, description="Total class sections generated.")
    instructors: List[str] = Field(default_factory=list, description="Unique instructor names.")


class CourseSummary(BaseModel):
    """Aggregated curriculum summary metrics extracted from document."""

    academic_session: Dict[str, Any] = Field(default_factory=dict, description="Session details.")
    department: Dict[str, Any] = Field(default_factory=dict, description="Department info.")
    subject_area: Dict[str, Any] = Field(default_factory=dict, description="Subject area info.")
    total_courses: int = Field(0, description="Total courses identified.")
    total_configurations: int = Field(0, description="Total configurations.")
    total_classes: int = Field(0, description="Total class sections.")
    total_distribution_constraints: int = Field(0, description="Total distribution constraints.")
    courses: List[CourseSummaryItem] = Field(default_factory=list, description="List of course offerings.")


class JobStatusResponse(BaseModel):
    """Complete status report of an ingestion job."""

    job_id: str = Field(..., description="Unique job identifier.")
    state: str = Field(
        ...,
        description="Job state ('queued', 'processing', 'waiting_disambiguation', 'completed', 'failed').",
    )
    filename: str = Field(..., description="Uploaded file name.")
    progress: ProgressMetrics = Field(..., description="Real-time execution progress.")
    ambiguities: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Pending Human-in-the-Loop ambiguity/conflict questions.",
    )
    course_summary: Optional[CourseSummary] = Field(
        None, description="Extracted course summary metrics."
    )
    validation_result: Optional[Dict[str, Any]] = Field(
        None, description="Schema & semantic validation outcome."
    )
    error: Optional[str] = Field(None, description="Error message if job failed.")
    created_at: str = Field(..., description="Job creation timestamp (ISO 8601).")
    updated_at: str = Field(..., description="Last modification timestamp (ISO 8601).")


class ResolveRequest(BaseModel):
    """Administrative resolution input for ambiguous items."""

    resolutions: Optional[Dict[str, Any]] = Field(
        None, description="Mapping of ambiguity IDs to chosen resolution options."
    )
    resolution: Optional[Any] = Field(
        None, description="Single resolution choice applied to pending ambiguities."
    )

    model_config = {"extra": "allow"}


class ResolveResponse(BaseModel):
    """Response returned when disambiguation resolutions are accepted."""

    job_id: str = Field(..., description="Job identifier.")
    status: str = Field("processing", description="Updated job state.")
    message: str = Field(..., description="Status message.")


class SubmitRequest(BaseModel):
    """Optional submission overrides."""

    unitime_url: Optional[str] = Field(
        None, description="Optional override for target UniTime Smart Ingest URL."
    )


class SubmitResponse(BaseModel):
    """Outcome of submitting canonical payload to UniTime REST server."""

    job_id: str = Field(..., description="Job identifier.")
    status: str = Field(..., description="UniTime response status (e.g. SUCCESS, FAILED).")
    http_status_code: int = Field(..., description="HTTP status code returned by UniTime.")
    is_success: bool = Field(..., description="Whether ingestion was fully successful.")
    summary: str = Field(..., description="Human-readable submission summary.")
    details: Optional[Dict[str, Any]] = Field(None, description="Raw UniTime response details.")


class ReportItem(BaseModel):
    """Metadata item for an audit report."""

    filename: str = Field(..., description="Name of the markdown report file.")
    size_bytes: int = Field(..., description="File size in bytes.")
    created_at: str = Field(..., description="File creation timestamp.")
    modified_at: str = Field(..., description="File modification timestamp.")


class ReportDetailResponse(BaseModel):
    """Content and metadata of an audit report."""

    filename: str = Field(..., description="Report filename.")
    content: str = Field(..., description="Full markdown report content.")
    size_bytes: int = Field(..., description="Size in bytes.")
    modified_at: str = Field(..., description="Modification timestamp.")


class ChatMessageInput(BaseModel):
    """Message item in conversational chat history."""

    role: str = Field(..., description="Role of the sender: user, assistant, or system.")
    content: str = Field(..., description="Text content of the message.")


class ChatRequest(BaseModel):
    """Inbound chat message payload for conversational ReAct agent."""

    message: str = Field(..., description="User message text.")
    history: Optional[List[ChatMessageInput]] = Field(
        default=None, description="Recent conversation turns."
    )
    job_id: Optional[str] = Field(
        default=None, description="Optional active job ID for timetable context grounding."
    )


class ChatResponse(BaseModel):
    """Outbound chat response with ReAct reasoning metadata."""

    reply: str = Field(..., description="AI assistant response message in Indonesian Markdown.")
    thought_process: List[str] = Field(
        default_factory=list, description="Reasoning steps executed by the agent."
    )
    tools_used: List[str] = Field(
        default_factory=list, description="List of tools invoked during reasoning."
    )
    timestamp: str = Field(..., description="UTC ISO timestamp of the response.")
    error: Optional[str] = Field(None, description="Optional error detail if degraded.")


# =============================================================================
# In-Memory Job Management
# =============================================================================


@dataclass
class IngestJob:
    """Internal model tracking the lifecycle and state of an ingestion job."""

    job_id: str
    file_path: Path
    filename: str
    provider: str
    state: str = "queued"
    model: Optional[str] = None
    dry_run: bool = True
    strict: bool = False
    render_images: bool = False
    unitime_url: Optional[str] = None
    temp_dir: Optional[Path] = None
    progress: Dict[str, Any] = field(
        default_factory=lambda: {
            "stage": "queued",
            "current_chunk": 0,
            "total_chunks": 0,
            "percent": 0,
            "message": "Job queued for processing",
        }
    )
    ambiguities: List[Dict[str, Any]] = field(default_factory=list)
    course_summary: Optional[Dict[str, Any]] = None
    payload: Optional[Dict[str, Any]] = None
    validation_result: Optional[Dict[str, Any]] = None
    ingest_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    graph: Any = None
    config: Optional[Dict[str, Any]] = None
    total_chunks: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class JobManager:
    """Thread-safe in-memory store for tracking and querying ingestion jobs."""

    def __init__(self) -> None:
        self._jobs: Dict[str, IngestJob] = {}
        self.lock = threading.Lock()

    def create_job(self, **kwargs: Any) -> IngestJob:
        """Register a new job entry."""
        with self.lock:
            job = IngestJob(**kwargs)
            self._jobs[job.job_id] = job
            return job

    def get_job(self, job_id: str) -> Optional[IngestJob]:
        """Fetch job by ID."""
        with self.lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[IngestJob]:
        """Return list of all registered jobs."""
        with self.lock:
            return list(self._jobs.values())


job_manager = JobManager()
chat_agent = ChatReActAgent(job_manager_ref=job_manager)


# =============================================================================
# Helper Utilities
# =============================================================================


def _build_course_summary(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Generate high-level course and class metrics from a canonical curriculum payload."""
    if not payload or not isinstance(payload, dict):
        return None

    session = payload.get("academicSession", {})
    dept = payload.get("department", {})
    sa = payload.get("subjectArea", {})
    courses = payload.get("courses", [])
    constraints = payload.get("distributionConstraints", [])

    total_configs = 0
    total_classes = 0
    course_items: List[Dict[str, Any]] = []

    for c in courses:
        if not isinstance(c, dict):
            continue
        c_num = c.get("courseNumber") or c.get("course_code") or "Unknown"
        title = c.get("title") or c.get("courseTitle") or ""
        subj = c.get("subjectArea") or sa.get("abbreviation") or ""

        c_configs = c.get("configurations", [])
        total_configs += len(c_configs)

        c_classes_count = 0
        instructors: set[str] = set()

        for cfg in c_configs:
            if not isinstance(cfg, dict):
                continue
            for sp in cfg.get("subparts", []):
                if not isinstance(sp, dict):
                    continue
                for cls in sp.get("classes", []):
                    if not isinstance(cls, dict):
                        continue
                    c_classes_count += 1
                    raw_ins = cls.get("instructors", [])
                    if isinstance(raw_ins, list):
                        for ins in raw_ins:
                            if isinstance(ins, dict) and ins.get("name"):
                                instructors.add(str(ins["name"]))
                            elif isinstance(ins, str) and ins.strip():
                                instructors.add(ins.strip())
                    elif cls.get("instructor"):
                        instructors.add(str(cls["instructor"]).strip())

        total_classes += c_classes_count
        course_items.append(
            {
                "course_number": c_num,
                "title": title,
                "subject_area": subj,
                "configurations_count": len(c_configs),
                "classes_count": c_classes_count,
                "instructors": sorted(instructors),
            }
        )

    return {
        "academic_session": session,
        "department": dept,
        "subject_area": sa,
        "total_courses": len(courses),
        "total_configurations": total_configs,
        "total_classes": total_classes,
        "total_distribution_constraints": len(constraints),
        "courses": course_items,
    }


def _is_canonical_payload(file_path: Path) -> Optional[Dict[str, Any]]:
    """Check if the uploaded file is already a canonical UniTime JSON payload."""
    if file_path.suffix.lower() != ".json":
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "courses" in data and "academicSession" in data:
            return data
    except Exception:
        return None
    return None


# =============================================================================
# Background Execution Engine
# =============================================================================


def _run_canonical_json_job(
    job: IngestJob,
    raw_payload: Dict[str, Any],
    resume_payload: Optional[Any] = None,
) -> None:
    """Process a directly uploaded canonical JSON document."""
    with job_manager.lock:
        job.state = "processing"
        job.progress = {
            "stage": "validating",
            "current_chunk": 1,
            "total_chunks": 1,
            "percent": 40,
            "message": "Validating canonical JSON schema and semantics...",
        }
        job.updated_at = datetime.now(timezone.utc).isoformat()

    validator = Validator(strict_semantics=job.strict)
    val_res = validator.validate(raw_payload)

    val_dict = {
        "is_valid": val_res.is_valid,
        "errors_count": len(val_res.errors),
        "warnings_count": len(val_res.warnings),
        "errors": [
            {"path": e.path, "validator": e.validator, "message": e.message}
            for e in val_res.errors
        ],
        "warnings": val_res.warnings,
    }

    job.validation_result = val_dict
    job.payload = raw_payload
    job.course_summary = _build_course_summary(raw_payload)

    # Check for room capacity or temporal conflicts
    all_classes = _extract_all_classes(raw_payload)
    ambiguities: List[Dict[str, Any]] = []

    with AgentMemory(str(MEMORY_DB_PATH)) as mem:
        for cls in all_classes:
            req_cap = cls.get("capacity") or 30
            room_prefs = cls.get("roomPreferences", [])
            if room_prefs and isinstance(room_prefs[0], dict):
                bldg = room_prefs[0].get("building", "")
                rnum = room_prefs[0].get("roomNumber", "")
                cap_check = inspect_room_capacity(
                    building=bldg, room_number=rnum, required_cap=req_cap, memory_instance=mem
                )
                if not cap_check["is_sufficient"]:
                    sig = f"room_capacity:{cls.get('courseNumber')}:{cap_check['room_name']}:{cls.get('sectionName')}"
                    if not mem.find_previous_resolution(raw_payload.get("department", {}).get("code", "*"), sig):
                        ambiguities.append(
                            {
                                "id": f"capacity_{cls.get('courseNumber')}_{cls.get('sectionName')}",
                                "issue_signature": sig,
                                "type": "room_capacity",
                                "question": (
                                    f"Class '{cls.get('courseNumber')} {cls.get('sectionName')}' requires "
                                    f"{req_cap} seats, but room '{cap_check['room_name']}' capacity is "
                                    f"{cap_check['actual_capacity']}."
                                ),
                                "options": [
                                    "Allow overflow (keep room)",
                                    "Reassign to larger hall",
                                    "Split into two sections",
                                ],
                                "context": cap_check,
                            }
                        )

    # Handle Human-in-the-Loop disambiguation
    if ambiguities and resume_payload is None:
        with job_manager.lock:
            job.state = "waiting_disambiguation"
            job.ambiguities = ambiguities
            job.progress = {
                "stage": "waiting_disambiguation",
                "current_chunk": 1,
                "total_chunks": 1,
                "percent": 80,
                "message": f"Paused: {len(ambiguities)} ambiguity/ies require administrative review.",
            }
            job.updated_at = datetime.now(timezone.utc).isoformat()
        return

    # If resumed, persist chosen resolution
    if resume_payload:
        with AgentMemory(str(MEMORY_DB_PATH)) as mem:
            dept_code = raw_payload.get("department", {}).get("code", "*")
            for amb in job.ambiguities:
                amb_id = amb.get("id")
                sig = amb.get("issue_signature") or amb_id or "sig"
                choice = (
                    resume_payload.get(amb_id, "Approved")
                    if isinstance(resume_payload, dict)
                    else str(resume_payload)
                )
                mem.save_resolution(
                    dept=dept_code,
                    issue_sig=sig,
                    question=amb.get("question", ""),
                    choice=choice,
                    fix=choice,
                )

    is_failed = (not val_res.is_valid) and job.strict
    job_status = STATUS_ERROR if is_failed else STATUS_COMPLETED

    # Generate administrative audit report
    state_report: Dict[str, Any] = {
        "document_path": str(job.file_path),
        "document_type": "json",
        "status": job_status,
        "slices": [],
        "partial_payloads": [raw_payload],
        "unified_payload": raw_payload,
        "validation_result": val_dict,
        "ambiguities": [],
        "human_response": resume_payload,
        "audit_logs": [],
        "ingest_result": {"status": "READY"},
        "memory_context": {},
    }
    write_admin_report(state_report, output_dir=REPORTS_DIR)

    with job_manager.lock:
        job.state = "failed" if is_failed else "completed"
        job.ambiguities = []
        job.progress = {
            "stage": job.state,
            "current_chunk": 1,
            "total_chunks": 1,
            "percent": 100,
            "message": "Canonical JSON processing finished successfully." if job.state == "completed" else "Validation failed under strict mode.",
        }
        job.updated_at = datetime.now(timezone.utc).isoformat()


def _run_agent_graph(job: IngestJob, resume_payload: Optional[Any] = None) -> None:
    """Execute or resume the LangGraph autonomous ingestion workflow."""
    if resume_payload is not None and job.graph is not None and job.config is not None:
        current_input: Any = Command(resume=resume_payload)
        graph = job.graph
        config = job.config
    else:
        memory_context = {
            "provider": job.provider,
            "model": job.model,
            "dry_run": True,  # Keep dry-run in background extraction; explicit submission is via /submit
            "submit": False,
            "unitime_url": job.unitime_url or os.getenv("UNITIME_API_URL"),
            "reports_dir": str(REPORTS_DIR),
            "memory_db_path": str(MEMORY_DB_PATH),
            "render_images": job.render_images,
            "strict": job.strict,
        }
        initial_state = create_initial_state(
            document_path=str(job.file_path),
            document_type="auto",
            memory_context=memory_context,
        )
        checkpointer = MemorySaver()
        graph = build_ingest_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job.job_id}}
        job.graph = graph
        job.config = config
        current_input = initial_state

    while True:
        interrupted = False
        interrupt_payload: Any = None

        for event in graph.stream(current_input, config=config):
            if not isinstance(event, dict):
                continue

            for node_name, node_output in event.items():
                if not isinstance(node_output, dict) and node_name != "__interrupt__":
                    continue

                with job_manager.lock:
                    job.updated_at = datetime.now(timezone.utc).isoformat()

                    if node_name == "__interrupt__":
                        interrupted = True
                        if isinstance(node_output, (list, tuple)) and len(node_output) > 0:
                            interrupt_payload = getattr(node_output[0], "value", node_output[0])
                        else:
                            interrupt_payload = node_output
                    elif node_name == "slice":
                        slices = node_output.get("slices", [])
                        job.total_chunks = len(slices)
                        job.progress = {
                            "stage": "slicing",
                            "current_chunk": 0,
                            "total_chunks": len(slices),
                            "percent": 20,
                            "message": f"Sliced into {len(slices)} document chunk(s).",
                        }
                    elif node_name == "extract_chunk":
                        idx = node_output.get("current_slice_index", 1)
                        tot = job.total_chunks or max(idx, 1)
                        pct = min(20 + int(45 * (idx / tot)), 65)
                        job.progress = {
                            "stage": "extracting",
                            "current_chunk": idx,
                            "total_chunks": tot,
                            "percent": pct,
                            "message": f"Extracted slice chunk {idx}/{tot}.",
                        }
                    elif node_name == "merge":
                        unified = node_output.get("unified_payload") or {}
                        job.payload = unified
                        job.course_summary = _build_course_summary(unified)
                        job.progress = {
                            "stage": "merging",
                            "current_chunk": job.total_chunks,
                            "total_chunks": job.total_chunks,
                            "percent": 70,
                            "message": "Unified course offerings into single payload.",
                        }
                    elif node_name == "reason_validate":
                        val_res = node_output.get("validation_result") or {}
                        ambiguities = node_output.get("ambiguities", [])
                        job.validation_result = val_res
                        job.ambiguities = ambiguities
                        unified = node_output.get("unified_payload") or job.payload
                        if unified:
                            job.payload = unified
                            job.course_summary = _build_course_summary(unified)
                        job.progress = {
                            "stage": "validating",
                            "current_chunk": job.total_chunks,
                            "total_chunks": job.total_chunks,
                            "percent": 80,
                            "message": f"Validation complete ({len(ambiguities)} conflicts found).",
                        }
                    elif node_name == "apply_feedback":
                        unified = node_output.get("unified_payload") or job.payload
                        if unified:
                            job.payload = unified
                            job.course_summary = _build_course_summary(unified)
                        job.progress = {
                            "stage": "applying_feedback",
                            "current_chunk": job.total_chunks,
                            "total_chunks": job.total_chunks,
                            "percent": 85,
                            "message": "Human feedback applied.",
                        }
                    elif node_name == "submit":
                        ingest_res = node_output.get("ingest_result") or {}
                        job.ingest_result = ingest_res
                        job.progress = {
                            "stage": "submitting",
                            "current_chunk": job.total_chunks,
                            "total_chunks": job.total_chunks,
                            "percent": 90,
                            "message": "Submission phase validated.",
                        }
                    elif node_name == "admin_reporter":
                        job.progress = {
                            "stage": "reporting",
                            "current_chunk": job.total_chunks,
                            "total_chunks": job.total_chunks,
                            "percent": 95,
                            "message": "Audit report generated.",
                        }

        graph_state = graph.get_state(config)

        # Natural workflow completion
        if not graph_state.next:
            final_values = graph_state.values
            with job_manager.lock:
                status_str = final_values.get("status")
                job.state = "failed" if status_str == STATUS_ERROR else "completed"
                job.payload = final_values.get("unified_payload") or job.payload
                job.validation_result = final_values.get("validation_result") or job.validation_result
                if job.payload:
                    job.course_summary = _build_course_summary(job.payload)
                job.ambiguities = []
                job.progress = {
                    "stage": job.state,
                    "current_chunk": job.total_chunks,
                    "total_chunks": job.total_chunks,
                    "percent": 100,
                    "message": (
                        "Ingestion pipeline completed successfully."
                        if job.state == "completed"
                        else "Pipeline failed on validation or extraction error."
                    ),
                }
                job.updated_at = datetime.now(timezone.utc).isoformat()
            break

        # Check for pause on task interrupt
        if graph_state.tasks:
            for task in graph_state.tasks:
                if task.interrupts:
                    interrupted = True
                    interrupt_payload = task.interrupts[0].value
                    break

        if interrupted:
            with job_manager.lock:
                job.state = "waiting_disambiguation"
                raw_amb = []
                if isinstance(interrupt_payload, dict):
                    raw_amb = interrupt_payload.get("ambiguities", [])
                elif isinstance(interrupt_payload, list):
                    raw_amb = interrupt_payload
                job.ambiguities = raw_amb or job.ambiguities
                job.progress = {
                    "stage": "waiting_disambiguation",
                    "current_chunk": job.total_chunks,
                    "total_chunks": job.total_chunks,
                    "percent": 80,
                    "message": f"Waiting for human disambiguation ({len(job.ambiguities)} conflicts pending).",
                }
                job.updated_at = datetime.now(timezone.utc).isoformat()
            break
        else:
            break


def _run_job(job_id: str, resume_payload: Optional[Any] = None) -> None:
    """Top-level job worker executing either canonical JSON processing or LangGraph agent."""
    job = job_manager.get_job(job_id)
    if not job:
        return

    with job_manager.lock:
        job.state = "processing"
        job.progress["stage"] = "processing"
        job.progress["message"] = "Processing document..."
        job.updated_at = datetime.now(timezone.utc).isoformat()

    try:
        canonical = _is_canonical_payload(job.file_path)
        if canonical:
            _run_canonical_json_job(job, canonical, resume_payload=resume_payload)
        else:
            _run_agent_graph(job, resume_payload=resume_payload)
    except Exception as exc:
        logger.exception("Job %s execution encountered unhandled error: %s", job_id, exc)
        with job_manager.lock:
            job.state = "failed"
            job.error = str(exc)
            job.progress = {
                "stage": "failed",
                "current_chunk": 0,
                "total_chunks": 0,
                "percent": 0,
                "message": f"Job failed: {exc}",
            }
            job.updated_at = datetime.now(timezone.utc).isoformat()


# =============================================================================
# FastAPI Application & Lifespan
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager ensuring clean thread pool and resource disposal."""
    yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="UniTime AI Ingestion Gateway API",
    description="Production-grade REST server for autonomous academic schedule extraction, validation, and UniTime synchronization.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration: Allow all origins to seamlessly support Vercel deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Security & Authentication Dependencies
# =============================================================================


def verify_gateway_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> None:
    """Validate incoming API key against configured GATEWAY_API_KEY.

    If GATEWAY_API_KEY is not configured or empty, access is unrestricted.
    If configured, validates against X-API-Key or Authorization Bearer header.
    Returns HTTP 403 if missing or mismatched.
    """
    configured_key = os.getenv("GATEWAY_API_KEY", "").strip()
    if not configured_key:
        return

    provided_key: Optional[str] = None
    if x_api_key and x_api_key.strip():
        provided_key = x_api_key.strip()
    elif authorization and authorization.strip():
        auth_str = authorization.strip()
        parts = auth_str.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_key = parts[1].strip()
        elif len(parts) == 1:
            provided_key = parts[0].strip()

    if not provided_key or not hmac.compare_digest(provided_key, configured_key):
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing Gateway API Key",
        )


# =============================================================================
# REST Endpoints
# =============================================================================


@app.get("/", tags=["System"])
def root() -> Dict[str, Any]:
    """Root status endpoint."""
    return {
        "service": "UniTime AI Ingestion Gateway",
        "status": "online",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Check gateway health, loaded LLM provider, and UniTime REST connectivity."""
    provider = os.getenv("DEFAULT_LLM_PROVIDER", "mock")
    unitime_url = os.getenv("UNITIME_API_URL", "http://localhost:8888/api/smart-ingest")
    client = UniTimeClient(base_url=unitime_url, timeout_seconds=3.0)

    unitime_status: Dict[str, Any] = {
        "connected": False,
        "url": unitime_url,
        "details": None,
        "error": None,
    }

    try:
        details = client.health_check()
        unitime_status["connected"] = True
        unitime_status["details"] = details
    except Exception as exc:
        unitime_status["connected"] = False
        unitime_status["error"] = str(exc)

    return HealthResponse(
        status="ok",
        provider=provider,
        unitime=UniTimeStatus(**unitime_status),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.post(
    "/api/ingest/upload",
    response_model=UploadResponse,
    dependencies=[Depends(verify_gateway_api_key)],
)
async def upload_file(
    file: UploadFile = File(...),
    provider: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    dry_run: bool = Form(True),
    strict: bool = Form(False),
    render_images: bool = Form(False),
    sync: bool = False,
) -> UploadResponse:
    """Accept an uploaded curriculum document and initialize an asynchronous background extraction job."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must include a filename.")

    filename = file.filename
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{suffix}'. Allowed formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="unitime_ingest_"))
    saved_file_path = temp_dir / filename

    try:
        content = await file.read()
        saved_file_path.write_bytes(content)
    except Exception as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {exc}")

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    active_provider = (provider or os.getenv("DEFAULT_LLM_PROVIDER", "mock")).lower()

    job = job_manager.create_job(
        job_id=job_id,
        file_path=saved_file_path,
        filename=filename,
        provider=active_provider,
        model=model,
        dry_run=dry_run,
        strict=strict,
        render_images=render_images,
        temp_dir=temp_dir,
    )

    if sync:
        _run_job(job_id)
    else:
        _executor.submit(_run_job, job_id)

    return UploadResponse(
        job_id=job_id,
        filename=filename,
        status=job.state,
        message="File uploaded successfully. Ingestion pipeline initialized.",
    )


@app.get(
    "/api/ingest/status/{job_id}",
    response_model=JobStatusResponse,
    dependencies=[Depends(verify_gateway_api_key)],
)
def get_job_status(job_id: str) -> JobStatusResponse:
    """Return real-time state, progress metrics, ambiguity questions, and extracted course summary."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job '{job_id}' not found.")

    course_summary_obj = (
        CourseSummary(**job.course_summary) if job.course_summary else None
    )

    return JobStatusResponse(
        job_id=job.job_id,
        state=job.state,
        filename=job.filename,
        progress=ProgressMetrics(**job.progress),
        ambiguities=job.ambiguities,
        course_summary=course_summary_obj,
        validation_result=job.validation_result,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.post(
    "/api/ingest/resolve/{job_id}",
    response_model=ResolveResponse,
    dependencies=[Depends(verify_gateway_api_key)],
)
def resolve_ambiguities(
    job_id: str,
    payload: Optional[ResolveRequest] = None,
    sync: bool = False,
) -> ResolveResponse:
    """Accept administrative resolution choices for ambiguous items and resume processing."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job '{job_id}' not found.")

    if job.state != "waiting_disambiguation":
        raise HTTPException(
            status_code=400,
            detail=f"Job '{job_id}' is not awaiting disambiguation (current state: '{job.state}').",
        )

    resolutions: Any = {}
    if payload:
        if payload.resolutions is not None:
            resolutions = payload.resolutions
        elif payload.resolution is not None:
            resolutions = payload.resolution
        elif payload.model_extra:
            resolutions = payload.model_extra

    if not resolutions:
        resolutions = "Approved"

    with job_manager.lock:
        job.state = "processing"
        job.progress = {
            "stage": "resuming",
            "current_chunk": job.total_chunks,
            "total_chunks": job.total_chunks,
            "percent": 82,
            "message": "Resuming execution with provided disambiguation resolutions...",
        }
        job.updated_at = datetime.now(timezone.utc).isoformat()

    if sync:
        _run_job(job_id, resume_payload=resolutions)
    else:
        _executor.submit(_run_job, job_id, resume_payload=resolutions)

    return ResolveResponse(
        job_id=job_id,
        status="processing",
        message="Disambiguation resolutions accepted. Ingestion resumed.",
    )


@app.post(
    "/api/ingest/submit/{job_id}",
    response_model=SubmitResponse,
    dependencies=[Depends(verify_gateway_api_key)],
)
def submit_to_unitime(
    job_id: str,
    submit_req: Optional[SubmitRequest] = None,
) -> SubmitResponse:
    """Submit the extracted and validated canonical timetable payload directly to the UniTime server."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Ingestion job '{job_id}' not found.")

    if job.state in ("queued", "processing"):
        raise HTTPException(
            status_code=400,
            detail=f"Job '{job_id}' is still in progress (state: '{job.state}'). Please wait for completion.",
        )

    if job.state == "waiting_disambiguation":
        raise HTTPException(
            status_code=400,
            detail=f"Job '{job_id}' has pending ambiguities that must be resolved before submitting.",
        )

    if not job.payload:
        raise HTTPException(
            status_code=400,
            detail=f"Job '{job_id}' has no extracted payload available for submission.",
        )

    target_url = (submit_req and submit_req.unitime_url) or job.unitime_url or os.getenv("UNITIME_API_URL")
    client = UniTimeClient(base_url=target_url)

    try:
        resp = client.submit_ingest(job.payload)
    except UniTimeConnectionError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to UniTime server at {target_url}: {exc}",
        )
    except UniTimeClientError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"UniTime client error during submission: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error submitting payload to UniTime: {exc}",
        )

    with job_manager.lock:
        job.ingest_result = resp.raw_json
        job.updated_at = datetime.now(timezone.utc).isoformat()

    return SubmitResponse(
        job_id=job_id,
        status=resp.status,
        http_status_code=resp.http_status_code,
        is_success=resp.is_success,
        summary=resp.summary_text(),
        details=resp.raw_json,
    )


@app.get(
    "/api/reports",
    response_model=List[ReportItem],
    dependencies=[Depends(verify_gateway_api_key)],
)
def list_reports() -> List[ReportItem]:
    """List recent executive markdown audit reports."""
    reports: List[ReportItem] = []
    if not REPORTS_DIR.exists():
        return reports

    for path in REPORTS_DIR.glob("*.md"):
        if path.is_file():
            stat = path.stat()
            reports.append(
                ReportItem(
                    filename=path.name,
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                )
            )

    reports.sort(key=lambda r: r.modified_at, reverse=True)
    return reports


@app.get(
    "/api/reports/{filename}",
    response_model=None,
    dependencies=[Depends(verify_gateway_api_key)],
)
def get_report(
    filename: str,
    request: Request,
    raw: bool = False,
):
    """Retrieve content of a specific markdown audit report."""
    # Directory traversal prevention
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename format.")

    report_path = (REPORTS_DIR / filename).resolve()
    try:
        report_path.relative_to(REPORTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied.")

    if not report_path.is_file():
        raise HTTPException(status_code=404, detail=f"Audit report '{filename}' not found.")

    try:
        content = report_path.read_text(encoding="utf-8")
        stat = report_path.stat()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error reading report '{filename}': {exc}")

    accept_header = request.headers.get("accept", "") if request else ""
    if raw or "text/markdown" in accept_header or "text/plain" in accept_header:
        return Response(content=content, media_type="text/markdown")

    return ReportDetailResponse(
        filename=filename,
        content=content,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    )


@app.post(
    "/api/chat",
    response_model=ChatResponse,
    tags=["Chat"],
    dependencies=[Depends(verify_gateway_api_key)],
)
def chat_with_agent(
    payload: ChatRequest,
):
    """Engage with UniTime ReAct AI Assistant with scheduling tools and active timetable grounding."""
    history_dicts = (
        [item.model_dump() for item in payload.history] if payload.history else []
    )
    result = chat_agent.run_chat(
        message=payload.message,
        history=history_dicts,
        job_id=payload.job_id,
    )
    return ChatResponse(
        reply=result.get("reply", ""),
        thought_process=result.get("thought_process", []),
        tools_used=result.get("tools_used", []),
        timestamp=result.get("timestamp", datetime.now(timezone.utc).isoformat()),
        error=result.get("error"),
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("server:app", host=host, port=port, reload=True)
