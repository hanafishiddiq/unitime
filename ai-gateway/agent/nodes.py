"""UniTime AI Ingestion Gateway - LangGraph Workflow Nodes.

Implements all node execution logic for the curriculum ingestion pipeline:
- slice_node: Chunks input documents using DocumentSlicer.
- extract_chunk_node: Extracts structured curriculum JSON one chunk at a time via LLM Extractor.
- merge_node: Combines partial payloads into unified payload using Merger.
- reason_validate_node: ReAct reasoning, schema & semantic validation, memory checks, conflict detection.
- human_interrupt_node: Pauses workflow via LangGraph interrupt() when ambiguities exist.
- apply_feedback_node: Incorporates human resolutions into payload and persists them to AgentMemory.
- submit_node: Submits verified payload to UniTime REST API.
- admin_reporter_node: Generates executive Markdown audit reports.
"""

from __future__ import annotations

import copy
import datetime
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.types import interrupt

from core.client import UniTimeClient
from core.extractor import BaseExtractor, get_extractor
from core.merger import Merger
from core.slicer import DocumentSlicer
from core.validator import Validator
from .memory import AgentMemory
from .reporter import write_admin_report
from .state import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_PROCESSING,
    STATUS_WAITING_FOR_HUMAN,
    IngestAgentState,
)
from .tools import (
    check_time_conflict,
    inspect_room_capacity,
    resolve_instructor_identity,
)

logger = logging.getLogger(__name__)


def _create_log(level: str, message: str) -> Dict[str, Any]:
    """Helper to construct structured audit log entry."""
    return {
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": level.upper(),
        "message": message,
    }


def _extract_all_classes(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Traverse unified payload and extract flat list of class section dictionaries."""
    if not payload or not isinstance(payload, dict):
        return []

    classes: List[Dict[str, Any]] = []
    courses = payload.get("courses", [])

    for c in courses:
        if not isinstance(c, dict):
            continue
        c_num = c.get("courseNumber") or c.get("course_code") or "UnknownCourse"
        configs = c.get("configurations", [])
        for cfg in configs:
            if not isinstance(cfg, dict):
                continue
            for sp in cfg.get("subparts", []):
                if not isinstance(sp, dict):
                    continue
                for cls in sp.get("classes", []):
                    if not isinstance(cls, dict):
                        continue
                    # Create enriched copy with course number and subpart context
                    cls_copy = dict(cls)
                    cls_copy.setdefault("courseNumber", c_num)
                    classes.append(cls_copy)

    return classes


# -----------------------------------------------------------------------------
# Node 1: Slicing
# -----------------------------------------------------------------------------


def slice_node(state: IngestAgentState) -> Dict[str, Any]:
    """Document slicing node: Chunks input document into pages or sections."""
    doc_path = Path(state["document_path"]).resolve()
    memory_ctx = state.get("memory_context") or {}
    render_pdf_as_images = bool(memory_ctx.get("render_images", False))

    logger.info("slice_node: Processing %s (render_images=%s)", doc_path, render_pdf_as_images)

    slicer = DocumentSlicer(render_pdf_as_images=render_pdf_as_images)
    try:
        chunks = slicer.slice_file(doc_path)
    except Exception as exc:
        err_msg = f"Failed to slice document '{doc_path.name}': {exc}"
        logger.error(err_msg, exc_info=True)
        return {
            "status": STATUS_ERROR,
            "audit_logs": list(state.get("audit_logs", [])) + [_create_log("ERROR", err_msg)],
        }

    slices_data: List[Dict[str, Any]] = [
        {
            "chunk_id": c.chunk_id,
            "total_chunks": c.total_chunks,
            "chunk_type": c.chunk_type,
            "source_filename": c.source_filename,
            "text_content": c.text_content,
            "image_bytes": c.image_bytes,
            "mime_type": c.mime_type,
            "metadata": c.metadata,
        }
        for c in chunks
    ]

    log_entry = _create_log(
        "INFO",
        f"Sliced document into {len(slices_data)} chunk(s) from '{doc_path.name}'",
    )

    return {
        "slices": slices_data,
        "current_slice_index": 0,
        "status": STATUS_PROCESSING,
        "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
    }


# -----------------------------------------------------------------------------
# Node 2: Extract Chunk (Cyclic 1-by-1)
# -----------------------------------------------------------------------------


def extract_chunk_node(state: IngestAgentState) -> Dict[str, Any]:
    """Extraction node: Extracts structured data from exactly one chunk at a time."""
    slices = state.get("slices", [])
    idx = state.get("current_slice_index", 0)

    if idx >= len(slices):
        logger.info("extract_chunk_node: All %d slice(s) already extracted.", len(slices))
        return {}

    chunk = slices[idx]
    memory_ctx = state.get("memory_context") or {}
    provider = memory_ctx.get("provider") or os.getenv("DEFAULT_LLM_PROVIDER", "mock")
    model = memory_ctx.get("model") or os.getenv("DEFAULT_LLM_MODEL")

    logger.info(
        "extract_chunk_node: Extracting slice %d/%d (type: %s, provider: %s)",
        idx + 1,
        len(slices),
        chunk.get("chunk_type"),
        provider,
    )

    extractor: BaseExtractor = get_extractor(provider=provider, model=model)

    context = {
        "sourceDocumentName": chunk.get("source_filename", "input_data"),
        "chunk_id": chunk.get("chunk_id", idx + 1),
        "total_chunks": chunk.get("total_chunks", len(slices)),
        **(chunk.get("metadata") or {}),
    }

    try:
        if chunk.get("chunk_type") == "image" and chunk.get("image_bytes"):
            try:
                res = extractor.extract_image(
                    chunk["image_bytes"],
                    mime_type=chunk.get("mime_type", "image/png"),
                    context=context,
                )
            except Exception as vision_err:
                extracted_text = (chunk.get("metadata") or {}).get("extracted_text")
                if extracted_text and str(extracted_text).strip():
                    logger.warning(
                        "Vision extraction failed for chunk %d/%d (%s). Falling back to extracted text metadata.",
                        idx + 1,
                        len(slices),
                        vision_err,
                    )
                    res = extractor.extract_text(str(extracted_text), context=context)
                else:
                    raise vision_err
        else:
            text = chunk.get("text_content") or ""
            res = extractor.extract_text(text, context=context)

        updated_partials = list(state.get("partial_payloads", []))
        if res and res.payload:
            updated_partials.append(res.payload)

        log_entry = _create_log(
            "INFO",
            f"Extracted chunk {idx + 1}/{len(slices)} using provider '{provider}' ({extractor.model})",
        )

        return {
            "partial_payloads": updated_partials,
            "current_slice_index": idx + 1,
            "status": STATUS_PROCESSING,
            "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
        }

    except Exception as exc:
        err_msg = f"Extraction error on chunk {idx + 1}/{len(slices)}: {exc}"
        logger.error(err_msg, exc_info=True)
        log_entry = _create_log("ERROR", err_msg)
        return {
            "current_slice_index": idx + 1,
            "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
        }


# -----------------------------------------------------------------------------
# Node 3: Merge Partial Payloads
# -----------------------------------------------------------------------------


def merge_node(state: IngestAgentState) -> Dict[str, Any]:
    """Consolidation node: Combines partial payloads into unified curriculum payload."""
    partials = state.get("partial_payloads", [])
    logger.info("merge_node: Merging %d partial payload(s)", len(partials))

    merger = Merger()
    unified = merger.merge(partials)

    # Guarantee source document name is preserved in ingestControl
    doc_path = Path(state.get("document_path", "curriculum")).name
    unified.setdefault("ingestControl", {})["sourceDocumentName"] = doc_path

    courses = unified.get("courses", [])
    log_entry = _create_log(
        "INFO",
        f"Consolidated {len(partials)} partial payload(s) into {len(courses)} course offerings",
    )

    current_status = state.get("status")
    status = STATUS_ERROR if current_status == STATUS_ERROR else STATUS_PROCESSING

    return {
        "unified_payload": unified,
        "status": status,
        "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
    }


# -----------------------------------------------------------------------------
# Node 4: ReAct Reason & Validate Node
# -----------------------------------------------------------------------------


def reason_validate_node(state: IngestAgentState) -> Dict[str, Any]:
    """Reasoning & Validation node:

    - Validates unified_payload against schema and domain rules.
    - Inspects room seating capacities vs student enrollments.
    - Analyzes temporal, room, and instructor scheduling overlaps.
    - Queries persistent SQLite memory for existing learned resolutions or aliases.
    - Formulates ambiguities if unresolved conflicts are identified.
    """
    unified_payload = state.get("unified_payload") or {}
    memory_ctx = state.get("memory_context") or {}
    db_path = memory_ctx.get("memory_db_path")

    dept_code = (
        unified_payload.get("department", {}).get("code")
        or unified_payload.get("subjectArea", {}).get("departmentCode")
        or "*"
    )

    audit_entries: List[Dict[str, Any]] = []

    # 1. Schema & Semantic Validation
    validator = Validator(strict_semantics=bool(memory_ctx.get("strict", False)))
    val_res = validator.validate(unified_payload)
    val_dict = {
        "is_valid": val_res.is_valid,
        "errors": [
            {"path": err.path, "validator": err.validator, "message": err.message}
            for err in val_res.errors
        ],
        "warnings": list(val_res.warnings),
    }

    audit_entries.append(
        _create_log(
            "INFO",
            f"Schema validation {'PASSED' if val_res.is_valid else 'FAILED'} "
            f"({len(val_res.errors)} errors, {len(val_res.warnings)} warnings)",
        )
    )

    ambiguities: List[Dict[str, Any]] = []

    with AgentMemory(db_path) as mem:
        # 2. Check and Apply Known Room Aliases from Persistent Memory
        courses = unified_payload.get("courses", [])
        for c in courses:
            if not isinstance(c, dict):
                continue
            for cfg in c.get("configurations", []):
                if not isinstance(cfg, dict):
                    continue
                for sp in cfg.get("subparts", []):
                    if not isinstance(sp, dict):
                        continue
                    for cls in sp.get("classes", []):
                        if not isinstance(cls, dict):
                            continue
                        room_prefs = cls.get("roomPreferences", [])
                        for rp in room_prefs:
                            if not isinstance(rp, dict):
                                continue
                            raw_bldg = rp.get("building", "").strip()
                            raw_rnum = rp.get("roomNumber", "").strip()
                            raw_full = f"{raw_bldg} {raw_rnum}".strip()

                            # Check if alias exists in department memory
                            canon = mem.get_room_alias(dept_code, raw_full)
                            if not canon and raw_rnum:
                                canon = mem.get_room_alias(dept_code, raw_rnum)

                            if canon and canon.upper() != raw_full.upper():
                                # Apply canonical alias
                                parts = canon.split(" ", 1)
                                if len(parts) == 2:
                                    rp["building"], rp["roomNumber"] = parts[0], parts[1]
                                else:
                                    rp["roomNumber"] = canon
                                audit_entries.append(
                                    _create_log(
                                        "FIX",
                                        f"Auto-applied learned room alias: '{raw_full}' -> '{canon}'",
                                    )
                                )

                        # Resolve instructor identities
                        ins_list = cls.get("instructors", [])
                        if isinstance(ins_list, list):
                            for ins in ins_list:
                                if isinstance(ins, dict) and ins.get("name"):
                                    res_ins = resolve_instructor_identity(
                                        dept=dept_code,
                                        raw_name=ins["name"],
                                        memory_instance=mem,
                                    )
                                    if (
                                        res_ins["is_resolved"]
                                        and res_ins["canonical_name"] != ins["name"]
                                    ):
                                        old_name = ins["name"]
                                        ins["name"] = res_ins["canonical_name"]
                                        audit_entries.append(
                                            _create_log(
                                                "FIX",
                                                f"Resolved instructor identity: '{old_name}' -> '{res_ins['canonical_name']}'",
                                            )
                                        )

        # 3. Room Seating Capacity Verification
        all_classes = _extract_all_classes(unified_payload)
        for cls in all_classes:
            req_cap = (
                cls.get("capacity")
                or cls.get("maxEnrollment")
                or cls.get("expectedEnrollment")
                or cls.get("quota")
                or 30
            )
            room_prefs = cls.get("roomPreferences", [])
            if room_prefs and isinstance(room_prefs[0], dict):
                bldg = room_prefs[0].get("building", "")
                rnum = room_prefs[0].get("roomNumber", "")
                cap_check = inspect_room_capacity(
                    building=bldg,
                    room_number=rnum,
                    required_cap=req_cap,
                    memory_instance=mem,
                )

                if not cap_check["is_sufficient"]:
                    sig = f"room_capacity:{cls.get('courseNumber')}:{cap_check['room_name']}:{cls.get('sectionName')}"
                    # Check if previous resolution learned
                    prev_res = mem.find_previous_resolution(dept_code, sig)
                    if prev_res:
                        audit_entries.append(
                            _create_log(
                                "INFO",
                                f"Reusing learned resolution for {sig}: '{prev_res}'",
                            )
                        )
                    else:
                        ambiguities.append(
                            {
                                "id": f"capacity_{cls.get('courseNumber')}_{cls.get('sectionName')}",
                                "issue_signature": sig,
                                "type": "room_capacity",
                                "question": (
                                    f"Class '{cls.get('courseNumber')} {cls.get('sectionName')}' requires "
                                    f"{req_cap} seats, but room '{cap_check['room_name']}' capacity is "
                                    f"{cap_check['actual_capacity']} (deficit: {cap_check['deficit']} seats). "
                                    "How would you like to resolve this?"
                                ),
                                "options": [
                                    "Allow overflow (keep room)",
                                    "Reassign to larger hall",
                                    "Split into two sections",
                                ],
                                "context": cap_check,
                            }
                        )

        # 4. Scheduling Time Conflicts Analysis
        time_conf = check_time_conflict(all_classes)
        if time_conf["has_conflict"]:
            for conf in time_conf["conflicts"]:
                course_num = conf.get('class_a_course', '')
                sig = f"time_conflict:{conf['conflict_type']}:{course_num}:{conf['resource']}:{conf['days']}:{conf.get('class_a', '')}:{conf.get('class_b', '')}"
                prev_res = mem.find_previous_resolution(dept_code, sig)
                if prev_res:
                    audit_entries.append(
                        _create_log(
                            "INFO",
                            f"Reusing learned resolution for scheduling conflict {sig}: '{prev_res}'",
                        )
                    )
                else:
                    conf['courseNumber'] = course_num  # ensure courseNumber is in context
                    ambiguities.append(
                        {
                            "id": f"conflict_{conf['conflict_type']}_{conf['resource']}_{course_num}".replace(" ", "_"),
                            "issue_signature": sig,
                            "type": "time_conflict",
                            "question": f"{conf['description']} Please specify resolution strategy:",
                            "options": [
                                "Keep as-is (override)",
                                "Reschedule Class A",
                                "Reschedule Class B",
                                "Reassign room",
                            ],
                            "context": conf,
                        }
                    )

    # 5. Determine Workflow State
    if state.get("status") == STATUS_ERROR:
        status = STATUS_ERROR
        audit_entries.append(
            _create_log("ERROR", "Prior pipeline error preserved in reasoning node.")
        )
    elif ambiguities:
        logger.warning(
            "reason_validate_node: %d ambiguity/conflict(s) detected requiring review.",
            len(ambiguities),
        )
        status = STATUS_WAITING_FOR_HUMAN
        audit_entries.append(
            _create_log(
                "WARNING",
                f"Identified {len(ambiguities)} ambiguity/conflict(s) requiring human confirmation",
            )
        )
    elif not val_res.is_valid and bool(memory_ctx.get("strict", False)):
        status = STATUS_ERROR
        audit_entries.append(
            _create_log(
                "ERROR",
                f"Strict schema validation failed with {len(val_res.errors)} error(s).",
            )
        )
    else:
        status = STATUS_PROCESSING
        audit_entries.append(
            _create_log("INFO", "Reasoning & validation complete. Zero blocking ambiguities.")
        )

    return {
        "unified_payload": unified_payload,
        "validation_result": val_dict,
        "ambiguities": ambiguities,
        "status": status,
        "audit_logs": list(state.get("audit_logs", [])) + audit_entries,
    }


# -----------------------------------------------------------------------------
# Node 5: Human-in-the-Loop Interruption Node
# -----------------------------------------------------------------------------


def human_interrupt_node(state: IngestAgentState) -> Dict[str, Any]:
    """Interruption node: Pauses execution using LangGraph interrupt() when ambiguities exist."""
    ambiguities = state.get("ambiguities", [])
    if not ambiguities:
        return {"status": STATUS_PROCESSING}

    logger.info(
        "human_interrupt_node: Interrupting workflow for %d open ambiguities",
        len(ambiguities),
    )

    # LangGraph interrupt primitive halts execution until Command(resume=...) is passed
    human_response = interrupt(
        {
            "type": "human_disambiguation_required",
            "count": len(ambiguities),
            "ambiguities": ambiguities,
            "message": f"{len(ambiguities)} scheduling/identity conflict(s) require administrative review.",
        }
    )

    logger.info("human_interrupt_node: Resumed with human response: %s", human_response)

    return {
        "human_response": human_response,
        "status": STATUS_PROCESSING,
    }


# -----------------------------------------------------------------------------
# Node 6: Apply Feedback & Persist Node
# -----------------------------------------------------------------------------


def apply_feedback_node(state: IngestAgentState) -> Dict[str, Any]:
    human_resp = state.get("human_response")
    ambiguities = state.get("ambiguities", [])
    memory_ctx = state.get("memory_context") or {}
    db_path = memory_ctx.get("memory_db_path")

    unified = copy.deepcopy(state.get("unified_payload") or {})
    dept_code = (
        unified.get("department", {}).get("code")
        or unified.get("subjectArea", {}).get("departmentCode")
        or "*"
    )

    logger.info("apply_feedback_node: Incorporating feedback '%s'", human_resp)
    audit_entries: List[Dict[str, Any]] = []

    with AgentMemory(db_path) as mem:
        for amb in ambiguities:
            amb_id = amb.get("id")
            sig = amb.get("issue_signature") or amb_id or "unknown_ambiguity"
            q = amb.get("question", "")
            
            if isinstance(human_resp, dict):
                choice = str(human_resp.get(amb_id, "Approved"))
            else:
                choice = str(human_resp) if human_resp else "Approved"

            amb_type = amb.get("type")
            ctx = amb.get("context", {})

            # 1. Eliminate the "Phantom Fix" Vulnerability
            # Mutate `state["unified_payload"]` based on the resolution
            courses = unified.get("courses", [])
            for c in courses:
                if not isinstance(c, dict): continue
                c_num = c.get("courseNumber") or c.get("course_code") or ""
                
                for cfg in c.get("configurations", []):
                    if not isinstance(cfg, dict): continue
                    for sp in cfg.get("subparts", []):
                        if not isinstance(sp, dict): continue
                        for cls in sp.get("classes", []):
                            if not isinstance(cls, dict): continue
                            
                            sec_name = cls.get("sectionName", "")
                            
                            if amb_type == "room_capacity":
                                # Match using course and section from signature or ID
                                if sig == f"room_capacity:{c_num}:{ctx.get('room_name', '')}:{sec_name}":
                                    cls["capacity_override"] = True
                                    if "Override" not in choice and "overflow" not in choice.lower() and choice != "Keep as-is (override)":
                                        # User provided an alternative room name, or "Reassign to LAW-101"
                                        parts = choice.replace("Reassign ", "").replace("to ", "").split()
                                        if parts and parts[0] != "larger" and parts[0] != "Split":
                                            bldg = parts[0]
                                            rnum = parts[1] if len(parts) > 1 else ""
                                            cls["roomPreferences"] = [{"building": bldg, "roomNumber": rnum}]
                            
                            elif amb_type == "time_conflict":
                                a_course = ctx.get("class_a_course") or ctx.get("courseNumber") or ""
                                a_sec = ctx.get("class_a_section") or ctx.get("class_a", "")
                                b_course = ctx.get("class_b_course") or ctx.get("courseNumber") or ""
                                b_sec = ctx.get("class_b_section") or ctx.get("class_b", "")
                                
                                is_class_a = (c_num == a_course or not a_course) and (sec_name == a_sec or a_sec.endswith(sec_name))
                                is_class_b = (c_num == b_course or not b_course) and (sec_name == b_sec or b_sec.endswith(sec_name))
                                
                                if is_class_a or is_class_b:
                                    if "Reschedule" in choice or choice not in ["Keep as-is (override)", "Reassign room"]:
                                        # Update timePreferences or meetings with new time slot
                                        cls.setdefault("timePreferences", []).append({"new_slot": choice, "resolved": True})
                                    else:
                                        cls["time_override"] = True
                                        
                            elif amb_type == "instructor_identity":
                                for instr in cls.get("instructors", []):
                                    if instr.get("name") == ctx.get("raw_name", ""):
                                        instr["name"] = choice

            # Persist learned decision for automatic future resolution
            mem.save_resolution(
                dept=dept_code,
                issue_sig=sig,
                question=q,
                choice=choice,
                fix=choice,
            )

            # If the issue was a room alias or reassignment, update department alias table
            if amb_type == "room_alias" or "room_alias:" in sig:
                raw_label = ctx.get("raw_room")
                if raw_label:
                    mem.set_room_alias(dept_code, raw_label, choice)

            audit_entries.append(
                _create_log(
                    "INFO",
                    f"Saved persistent resolution for '{sig}': {choice}",
                )
            )

    audit_entries.append(
        _create_log(
            "INFO",
            f"Applied human feedback for {len(ambiguities)} ambiguity/ies",
        )
    )

    return {
        "unified_payload": unified,
        "ambiguities": [],
        "human_response": None,
        "status": STATUS_PROCESSING,
        "audit_logs": list(state.get("audit_logs", [])) + audit_entries,
    }


# -----------------------------------------------------------------------------
# Node 7: UniTime Submission Node
# -----------------------------------------------------------------------------


def submit_node(state: IngestAgentState) -> Dict[str, Any]:
    """UniTime persistence node: Sends unified payload to UniTime REST API."""
    unified = state.get("unified_payload") or {}
    memory_ctx = state.get("memory_context") or {}

    is_dry_run = bool(memory_ctx.get("dry_run", False))
    should_submit = bool(memory_ctx.get("submit", False))
    unitime_url = memory_ctx.get("unitime_url")

    logger.info("submit_node: Submitting (dry_run=%s, should_submit=%s)", is_dry_run, should_submit)

    if state.get("status") == STATUS_ERROR:
        ingest_result = {
            "status": "ABORTED_ON_ERROR",
            "http_status_code": 400,
            "message": "Submission aborted due to prior pipeline errors.",
        }
        log_entry = _create_log("ERROR", "Submission aborted due to prior pipeline errors.")
        return {
            "ingest_result": ingest_result,
            "status": STATUS_ERROR,
            "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
        }

    if is_dry_run or not should_submit:
        ingest_result = {
            "status": "DRY_RUN",
            "http_status_code": 200,
            "message": "Dry-run execution active. Payload validated without live server commit.",
        }
        log_entry = _create_log("INFO", "Dry-run completed successfully (server commit skipped)")
        return {
            "ingest_result": ingest_result,
            "status": STATUS_COMPLETED,
            "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
        }

    client = UniTimeClient(base_url=unitime_url)
    try:
        resp = client.submit_ingest(unified)
        ingest_dict = {
            "status": resp.status,
            "http_status_code": resp.http_status_code,
            "raw_json": resp.raw_json,
            "summary": resp.summary_text(),
        }
        final_status = STATUS_COMPLETED if resp.is_success else STATUS_ERROR
        log_entry = _create_log(
            "INFO" if resp.is_success else "ERROR",
            f"UniTime server response: {resp.status} (HTTP {resp.http_status_code})",
        )
        return {
            "ingest_result": ingest_dict,
            "status": final_status,
            "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
        }
    except Exception as exc:
        err_msg = f"UniTime submission failure: {exc}"
        logger.error(err_msg, exc_info=True)
        ingest_dict = {
            "status": "ERROR",
            "http_status_code": 500,
            "error": str(exc),
        }
        log_entry = _create_log("ERROR", err_msg)
        return {
            "ingest_result": ingest_dict,
            "status": STATUS_ERROR,
            "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
        }


# -----------------------------------------------------------------------------
# Node 8: Executive Admin Reporter Node
# -----------------------------------------------------------------------------


def admin_reporter_node(state: IngestAgentState) -> Dict[str, Any]:
    """Audit reporter node: Generates timestamped executive Markdown report."""
    memory_ctx = state.get("memory_context") or {}
    reports_dir = memory_ctx.get("reports_dir")

    logger.info("admin_reporter_node: Writing executive audit report")

    report_path = write_admin_report(state, output_dir=reports_dir)
    log_entry = _create_log(
        "INFO",
        f"Executive audit report generated at '{report_path}'",
    )

    return {
        "audit_logs": list(state.get("audit_logs", [])) + [log_entry],
    }
