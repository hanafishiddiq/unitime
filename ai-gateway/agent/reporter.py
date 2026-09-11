"""UniTime AI Ingestion Gateway - Executive Audit Reporter.

Generates comprehensive timestamped Markdown audit reports summarizing curriculum
extraction, schema validation, human disambiguation resolutions, scheduling anomalies,
UniTime server persistence, and actionable administrative recommendations.
"""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def _format_courses_table(unified_payload: Optional[Dict[str, Any]]) -> str:
    """Generate Markdown table detailing all extracted courses and class sections."""
    if not unified_payload or not isinstance(unified_payload, dict):
        return "_No curriculum courses extracted._\n"

    courses = unified_payload.get("courses", [])
    if not courses:
        return "_No courses present in unified payload._\n"

    subject_default = (
        unified_payload.get("subjectArea", {}).get("abbreviation")
        or unified_payload.get("department", {}).get("code")
        or "N/A"
    )

    lines = [
        "| Course Number | Subject | Title | Configs | Subparts | Classes | Instructors |",
        "|---|---|---|:---:|:---:|:---:|---|",
    ]

    for c in courses:
        if not isinstance(c, dict):
            continue
        c_num = c.get("courseNumber") or c.get("course_code") or "Unknown"
        subj = c.get("subjectArea", subject_default)
        title = c.get("title") or c.get("courseTitle") or "-"
        configs = c.get("configurations", [])
        total_configs = len(configs)

        subparts_count = 0
        classes_count = 0
        instructors: set[str] = set()

        for cfg in configs:
            if not isinstance(cfg, dict):
                continue
            for sp in cfg.get("subparts", []):
                if not isinstance(sp, dict):
                    continue
                subparts_count += 1
                for cls in sp.get("classes", []):
                    if not isinstance(cls, dict):
                        continue
                    classes_count += 1
                    raw_ins = cls.get("instructors", [])
                    if isinstance(raw_ins, list):
                        for ins in raw_ins:
                            if isinstance(ins, dict) and ins.get("name"):
                                instructors.add(str(ins["name"]))
                            elif isinstance(ins, str) and ins.strip():
                                instructors.add(ins.strip())
                    elif cls.get("instructor"):
                        instructors.add(str(cls["instructor"]).strip())

        ins_display = ", ".join(sorted(instructors)) if instructors else "_None assigned_"
        lines.append(
            f"| **{c_num}** | {subj} | {title} | {total_configs} | {subparts_count} | {classes_count} | {ins_display} |"
        )

    return "\n".join(lines) + "\n"


def _generate_recommendations(
    validation_result: Optional[Dict[str, Any]],
    ambiguities: List[Dict[str, Any]],
    unified_payload: Optional[Dict[str, Any]],
    ingest_result: Optional[Dict[str, Any]],
) -> List[str]:
    """Derive actionable recommendations for academic department administrators."""
    recs: List[str] = []

    # 1. Validation recommendations
    if validation_result:
        errors = validation_result.get("errors", [])
        warnings = validation_result.get("warnings", [])
        if errors:
            recs.append(
                f"**Resolve Critical Schema Errors**: Address {len(errors)} validation failure(s) "
                "before re-attempting live semester timetabling synchronization."
            )
        if warnings:
            recs.append(
                f"**Review Semantic Warnings**: Inspect {len(warnings)} soft warning(s) "
                "(such as unlinked class sections or zero-credit courses) to prevent scheduling gaps."
            )
    else:
        recs.append(
            "**Perform Schema Validation**: Ensure full schema conformance check is completed."
        )

    # 2. Ambiguity & Disambiguation recommendations
    if ambiguities:
        recs.append(
            f"**Complete Human Review**: {len(ambiguities)} open scheduling/identity ambiguity "
            "requires administrative confirmation."
        )
    else:
        recs.append(
            "**Persist Disambiguation Choices**: Human resolutions have been saved to local memory; "
            "review agent memory periodically to maintain alias hygiene."
        )

    # 3. Scheduling & Distribution recommendations
    if unified_payload and isinstance(unified_payload, dict):
        constraints = unified_payload.get("distributionConstraints", [])
        if not constraints:
            recs.append(
                "**Add Distribution Constraints**: Consider adding CANNOT_OVERLAP or SAME_ROOM constraints "
                "to ensure high solver quality in UniTime Course Timetabling."
            )
        else:
            recs.append(
                f"**Verify Distribution Rules**: Confirm that the {len(constraints)} distribution constraint(s) "
                "accurately reflect department policy and instructor availability."
            )

    # 4. Server Ingest recommendations
    if ingest_result:
        status = str(ingest_result.get("status", "")).upper()
        if status in ("SUCCESS", "OK"):
            recs.append(
                "**Review in UniTime Web UI**: Curriculum successfully ingested. "
                "Proceed to Course Timetabling -> Class Assignment to review the generated schedule."
            )
        elif status == "DRY_RUN":
            recs.append(
                "**Submit for Live Ingestion**: Dry-run validation succeeded. "
                "Run with `--submit` to commit changes to the live UniTime server."
            )
        else:
            err_msg = ingest_result.get("error") or ingest_result.get("message") or "Check server logs."
            recs.append(
                f"**Investigate UniTime Ingest Failure**: UniTime server returned error: {err_msg}"
            )
    else:
        recs.append(
            "**Finalize Live Ingestion**: Execute UniTime submission to synchronize database offerings."
        )

    return recs


def write_admin_report(
    state: Dict[str, Any],
    output_dir: Optional[str | Path] = None,
) -> Path:
    """Generate executive Markdown audit report from current agent state.

    Args:
        state: Execution state dictionary (IngestAgentState).
        output_dir: Target directory for saving report. Defaults to `ai-gateway/reports`.

    Returns:
        Path to the generated Markdown report file.
    """
    target_dir = Path(output_dir).resolve() if output_dir else DEFAULT_REPORTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.datetime.now()
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    report_path = target_dir / f"audit_report_{timestamp_str}.md"

    # Extract state fields
    doc_path = state.get("document_path", "N/A")
    doc_type = state.get("document_type", "auto")
    status = state.get("status", "unknown")
    slices = state.get("slices", [])
    partial_payloads = state.get("partial_payloads", [])
    unified_payload = state.get("unified_payload")
    validation_result = state.get("validation_result")
    ambiguities = state.get("ambiguities", [])
    human_response = state.get("human_response")
    audit_logs = state.get("audit_logs", [])
    ingest_result = state.get("ingest_result")
    memory_context = state.get("memory_context", {})

    # Compute high-level metrics
    courses = unified_payload.get("courses", []) if isinstance(unified_payload, dict) else []
    total_courses = len(courses)
    total_classes = 0
    total_configs = 0
    for c in courses:
        if isinstance(c, dict):
            for cfg in c.get("configurations", []):
                if isinstance(cfg, dict):
                    total_configs += 1
                    for sp in cfg.get("subparts", []):
                        if isinstance(sp, dict):
                            total_classes += len(sp.get("classes", []))

    constraints_count = (
        len(unified_payload.get("distributionConstraints", []))
        if isinstance(unified_payload, dict)
        else 0
    )

    # Normalize validation result
    val_is_valid = False
    val_errors: List[Any] = []
    val_warnings: List[Any] = []
    if isinstance(validation_result, dict):
        val_is_valid = bool(validation_result.get("is_valid", False))
        val_errors = validation_result.get("errors", [])
        val_warnings = validation_result.get("warnings", [])
    elif hasattr(validation_result, "is_valid"):
        val_is_valid = bool(getattr(validation_result, "is_valid"))
        val_errors = getattr(validation_result, "errors", [])
        val_warnings = getattr(validation_result, "warnings", [])

    # Status formatting
    status_badges = {
        "completed": "![Status: Completed](https://img.shields.io/badge/Status-Completed-success?style=flat-square)",
        "processing": "![Status: Processing](https://img.shields.io/badge/Status-Processing-yellow?style=flat-square)",
        "waiting_for_human": "![Status: Review Required](https://img.shields.io/badge/Status-Review_Required-orange?style=flat-square)",
        "error": "![Status: Error](https://img.shields.io/badge/Status-Error-red?style=flat-square)",
    }
    status_badge = status_badges.get(
        status.lower(),
        f"![Status: {status}](https://img.shields.io/badge/Status-{status}-blue?style=flat-square)",
    )

    # Submission status description
    submission_summary = "⏸️ Pending / Not Submitted"
    if ingest_result:
        if isinstance(ingest_result, dict):
            ingest_status = str(ingest_result.get("status", "")).upper()
            if ingest_status in ("SUCCESS", "OK"):
                submission_summary = "✅ Committed Successfully to UniTime"
            elif ingest_status == "DRY_RUN":
                submission_summary = "🟡 Dry-Run Completed (No Live Persistence)"
            else:
                submission_summary = f"❌ Failed: {ingest_result.get('error') or ingest_result.get('message', 'Unknown error')}"
        elif hasattr(ingest_result, "is_success"):
            if getattr(ingest_result, "is_success"):
                submission_summary = "✅ Committed Successfully to UniTime"
            else:
                submission_summary = f"❌ Failed: {getattr(ingest_result, 'error', 'Server error')}"

    # Build Markdown document
    doc_lines: List[str] = [
        "# 🎓 UniTime AI Ingestion Gateway - Executive Audit Report",
        "",
        f"> **Generated on:** {now.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> **Pipeline Status:** {status_badge}  ",
        f"> **Submission Status:** {submission_summary}  ",
        "",
        "---",
        "",
        "## 1. Executive Summary & Document Metadata",
        "",
        "| Attribute | Details |",
        "|---|---|",
        f"| **Source Document** | `{Path(doc_path).name}` |",
        f"| **Document Full Path** | `{doc_path}` |",
        f"| **Format Classification** | `{doc_type}` |",
        f"| **Document Slices** | {len(slices)} total chunk(s) |",
        f"| **Extracted Payloads** | {len(partial_payloads)} partial chunk(s) |",
        f"| **Total Courses Extracted** | **{total_courses}** course offerings |",
        f"| **Total Configurations** | {total_configs} configuration(s) |",
        f"| **Total Class Sections** | **{total_classes}** class sections |",
        f"| **Distribution Constraints** | {constraints_count} constraint(s) |",
        f"| **Schema Validation** | {'✅ PASS' if val_is_valid else '❌ FAIL'} ({len(val_errors)} error(s), {len(val_warnings)} warning(s)) |",
        "",
        "---",
        "",
        "## 2. Extracted Curriculum Offerings",
        "",
        _format_courses_table(unified_payload),
        "",
        "---",
        "",
        "## 3. Human-in-the-Loop Disambiguation & Memory Resolutions",
        "",
    ]

    # Human-in-the-loop section
    if ambiguities or human_response:
        doc_lines.append(f"**Total Ambiguities Logged:** {len(ambiguities)}  ")
        if human_response:
            doc_lines.append(f"**Applied Human Decision:** `{human_response}`  \n")

        doc_lines.append("| ID / Signature | Type | Issue / Question | Options Available |")
        doc_lines.append("|---|---|---|---|")
        for amb in ambiguities:
            if isinstance(amb, dict):
                amb_id = amb.get("issue_signature") or amb.get("id") or "ambiguity"
                amb_type = amb.get("type", "general")
                q = amb.get("question", "-")
                opts = ", ".join(amb.get("options", [])) if amb.get("options") else "Free text"
                doc_lines.append(f"| `{amb_id}` | `{amb_type}` | {q} | {opts} |")
            else:
                doc_lines.append(f"| - | general | {amb} | - |")
        doc_lines.append("")
    else:
        doc_lines.append("✅ **Clean Ingestion**: No ambiguities required human intervention.\n")

    # Learned memory entries / quirks
    if memory_context:
        doc_lines.extend(
            [
                "### Active Agent Memory & Context",
                "```json",
                f"{json.dumps(memory_context, indent=2, default=str)}",
                "```",
                "",
            ]
        )

    doc_lines.extend(
        [
            "---",
            "",
            "## 4. Validation, Anomalies & Scheduling Conflicts",
            "",
        ]
    )

    # Validation errors & warnings
    if val_errors:
        doc_lines.append("### ❌ Schema Validation Errors")
        for err in val_errors:
            if isinstance(err, dict):
                p = err.get("path") or "[root]"
                msg = err.get("message", "Validation error")
                doc_lines.append(f"- **`{p}`**: {msg}")
            elif hasattr(err, "format_line"):
                doc_lines.append(f"- {err.format_line()}")
            else:
                doc_lines.append(f"- {err}")
        doc_lines.append("")
    else:
        doc_lines.append("✅ **Schema Conformance**: All courses conform to UniTime Smart Ingest Schema.\n")

    if val_warnings:
        doc_lines.append("### ⚠️ Semantic Warnings & Soft Constraints")
        for warn in val_warnings:
            doc_lines.append(f"- ⚠️ {warn}")
        doc_lines.append("")

    # UniTime Ingestion Section
    doc_lines.extend(
        [
            "---",
            "",
            "## 5. UniTime Server Persistence Status",
            "",
        ]
    )

    if ingest_result:
        doc_lines.append("```json")
        try:
            if hasattr(ingest_result, "raw_json"):
                doc_lines.append(json.dumps(ingest_result.raw_json, indent=2))
            elif isinstance(ingest_result, dict):
                doc_lines.append(json.dumps(ingest_result, indent=2))
            else:
                doc_lines.append(str(ingest_result))
        except (TypeError, ValueError) as exc:
            logger.debug("Failed to serialize ingest_result JSON: %s", exc)
            doc_lines.append(str(ingest_result))
        doc_lines.append("```\n")
    else:
        doc_lines.append("_Payload has not been submitted to UniTime server (dry-run or local mode)._\n")

    # Recommendations Section
    recs = _generate_recommendations(
        validation_result=validation_result if isinstance(validation_result, dict) else None,
        ambiguities=ambiguities,
        unified_payload=unified_payload,
        ingest_result=ingest_result if isinstance(ingest_result, dict) else None,
    )

    doc_lines.extend(
        [
            "---",
            "",
            "## 6. Actionable Administrator Recommendations",
            "",
        ]
    )
    for i, rec in enumerate(recs, 1):
        doc_lines.append(f"{i}. {rec}")
    doc_lines.append("")

    # Audit Trail Journal
    if audit_logs:
        doc_lines.extend(
            [
                "---",
                "",
                "## 7. Execution Audit Journal",
                "",
                "| Timestamp | Level | Event / Decision |",
                "|---|---|---|",
            ]
        )
        for log in audit_logs:
            if isinstance(log, dict):
                ts = log.get("timestamp", "-")
                lvl = log.get("level", "INFO")
                msg = log.get("message", "")
                doc_lines.append(f"| {ts} | `{lvl}` | {msg} |")
            else:
                doc_lines.append(f"| - | `INFO` | {log} |")
        doc_lines.append("")

    content = "\n".join(doc_lines)
    report_path.write_text(content, encoding="utf-8")
    logger.info("Admin executive audit report written to %s", report_path)

    return report_path
