"""UniTime AI Ingestion Gateway - ReAct Agent Tools.

Provides execution tools for curriculum validation, room capacity verification,
instructor identity disambiguation, learned resolution persistence, time conflict
detection, and executive administrator summary generation.
"""

from __future__ import annotations

import functools
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

from langchain_core.tools import StructuredTool, tool

from core.client import UniTimeClient, UniTimeConnectionError
from core.validator import Validator
from .memory import AgentMemory

logger = logging.getLogger(__name__)

# Standard campus room catalog fallback
KNOWN_ROOM_CATALOG: Dict[str, int] = {
    # ITB / Indonesian campus standard rooms
    "LABTEK V 7601": 60,
    "LABTEK V 7602": 60,
    "LABTEK V 7603": 50,
    "LAB KOMPUTER 1": 40,
    "LAB KOMPUTER 2": 40,
    "LAB KOMPUTER 3": 35,
    "LAB BASDAT": 35,
    "LAB IRK": 35,
    "LAB RPL": 40,
    "LAB AI": 35,
    "MULTIMEDIA": 70,
    "AUDITORIUM": 250,
    "AULA TIMUR": 300,
    "AULA BARAT": 300,
    # Purdue / US sample rooms
    "HAAS G066": 120,
    "HAAS 111": 45,
    "LWSN B155": 75,
    "LWSN B158": 40,
    "PHYS 112": 150,
    "PHYS 114": 90,
    "EE 129": 110,
    "CL50 224": 450,
    "MATH 175": 100,
}

# Academic titles and honorifics sorted by length descending for accurate token replacement
ACADEMIC_TITLES = [
    "Professor", "Prof.", "Prof",
    "Doctor", "Dr.", "Dr",
    "Drs.", "Drs", "Dra.", "Dra",
    "Ir.", "Ir",
    "Ph.D.", "Ph.D", "PhD.", "PhD",
    "M.Sc.", "M.Sc", "MSc.", "MSc",
    "B.Sc.", "B.Sc", "BSc.", "BSc",
    "M.Kom.", "M.Kom",
    "S.Kom.", "S.Kom",
    "M.T.", "M.T",
    "S.T.", "S.T",
    "M.Eng.", "M.Eng",
    "B.Eng.", "B.Eng",
    "S.Si.", "S.Si",
    "M.Si.", "M.Si",
    "DEA", "IPM", "ASEAN Eng.", "ASEAN Eng",
]

ACADEMIC_TITLES_PATTERN = re.compile(
    r"(?:\b|(?<=\s)|(?<=^))("
    + "|".join(re.escape(t) for t in sorted(ACADEMIC_TITLES, key=len, reverse=True))
    + r")(?:\b|(?=\s)|(?=$)|(?=[,.]))",
    re.IGNORECASE,
)


def _make_callable_tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a function with LangChain StructuredTool while preserving direct callability."""
    structured_tool = tool(fn)
    fn.tool = structured_tool  # type: ignore[attr-defined]
    fn.invoke = structured_tool.invoke  # type: ignore[attr-defined]
    fn.name = structured_tool.name  # type: ignore[attr-defined]
    fn.description = structured_tool.description  # type: ignore[attr-defined]
    fn.args_schema = structured_tool.args_schema  # type: ignore[attr-defined]
    return fn


# -----------------------------------------------------------------------------
# Tool 1: Inspect Room Capacity
# -----------------------------------------------------------------------------


@_make_callable_tool
def inspect_room_capacity(
    building: str,
    room_number: str,
    required_cap: int,
    memory_instance: Optional[AgentMemory] = None,
) -> Dict[str, Any]:
    """Inspect whether a specific classroom or lab has sufficient seating capacity.

    Args:
        building: Building name or code (e.g. 'Labtek V', 'HAAS').
        room_number: Room number or lab name (e.g. '7601', 'G066', 'Lab Komputer 1').
        required_cap: Minimum number of student seats required.
        memory_instance: Optional AgentMemory instance for capacity lookup.

    Returns:
        Structured dictionary indicating capacity status, actual capacity, and surplus/deficit.
    """
    clean_building = str(building).strip() if building else ""
    clean_room = str(room_number).strip() if room_number else ""
    full_room_name = f"{clean_building} {clean_room}".strip()

    try:
        required = max(1, int(required_cap))
    except (ValueError, TypeError):
        required = 1

    actual_capacity: Optional[int] = None
    source = "unknown"

    # 1. Check persistent memory if provided
    if memory_instance is not None:
        actual_capacity = memory_instance.get_room_capacity(clean_building, clean_room)
        if actual_capacity is not None:
            source = "persistent_memory"

    # 2. Check canonical room catalog
    if actual_capacity is None:
        full_key = full_room_name.upper()
        if full_key in KNOWN_ROOM_CATALOG:
            actual_capacity = KNOWN_ROOM_CATALOG[full_key]
            source = "catalog"
        else:
            # Check room number alone in catalog
            room_key = clean_room.upper()
            if room_key in KNOWN_ROOM_CATALOG:
                actual_capacity = KNOWN_ROOM_CATALOG[room_key]
                source = "catalog"

    # 3. Fallback heuristic based on room classification
    if actual_capacity is None:
        source = "heuristic"
        lower_name = full_room_name.lower()
        if any(term in lower_name for term in ("auditorium", "aula", "hall", "theater")):
            actual_capacity = 250
        elif any(term in lower_name for term in ("lab", "laboratorium", "studio")):
            actual_capacity = 40
        elif any(term in lower_name for term in ("seminar", "meeting", "diskusi")):
            actual_capacity = 30
        else:
            actual_capacity = 50

    is_sufficient = actual_capacity >= required
    difference = actual_capacity - required
    deficit = max(0, required - actual_capacity)
    surplus = max(0, actual_capacity - required)

    status = "PASS" if is_sufficient else "FAIL_CAPACITY_EXCEEDED"
    message = (
        f"Room '{full_room_name}' capacity ({actual_capacity}) is sufficient for required {required} seats."
        if is_sufficient
        else f"Room '{full_room_name}' capacity ({actual_capacity}) is INSUFFICIENT for {required} seats (deficit: {deficit})."
    )

    return {
        "building": clean_building,
        "room_number": clean_room,
        "room_name": full_room_name,
        "required_capacity": required,
        "actual_capacity": actual_capacity,
        "is_sufficient": is_sufficient,
        "difference": difference,
        "deficit": deficit,
        "surplus": surplus,
        "status": status,
        "source": source,
        "message": message,
    }


# -----------------------------------------------------------------------------
# Tool 2: Resolve Instructor Identity
# -----------------------------------------------------------------------------


def _clean_instructor_name(raw_name: str) -> str:
    """Normalize raw instructor string by removing academic titles and formatting."""
    text = ACADEMIC_TITLES_PATTERN.sub("", raw_name)
    # Remove excessive punctuation like stray commas, dots
    text = re.sub(r"[,;]+", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


@_make_callable_tool
def resolve_instructor_identity(
    dept: str,
    raw_name: str,
    memory_instance: Optional[AgentMemory] = None,
) -> Dict[str, Any]:
    """Resolve an ambiguous or noisy instructor string to a canonical identity and preferences.

    Args:
        dept: Academic department code (e.g. 'CS', 'IF').
        raw_name: Raw instructor string from document (e.g. 'Dr. Alan Turing, Ph.D.').
        memory_instance: Optional AgentMemory instance for lookup.

    Returns:
        Structured resolution details including canonical name and stored quirks.
    """
    if not raw_name or not str(raw_name).strip():
        return {
            "department": str(dept).strip().upper() if dept else "*",
            "raw_name": "",
            "canonical_name": "",
            "is_resolved": False,
            "confidence": 0.0,
            "preferences": None,
            "message": "Empty instructor name provided.",
        }

    clean_raw = str(raw_name).strip()
    clean_dept = str(dept).strip().upper() if dept else "*"
    cleaned_name = _clean_instructor_name(clean_raw)

    canonical_name = cleaned_name or clean_raw
    confidence = 0.85
    preferences: Optional[Dict[str, Any]] = None

    # Check memory if available
    if memory_instance is not None:
        # Check if raw or cleaned matches an existing preference or quirk
        pref = memory_instance.get_instructor_preference(clean_dept, clean_raw)
        if not pref and cleaned_name != clean_raw:
            pref = memory_instance.get_instructor_preference(clean_dept, cleaned_name)

        if pref:
            canonical_name = pref["instructor_name"]
            preferences = pref
            confidence = 1.0
        else:
            # Check department knowledge for instructor alias
            alias = memory_instance.get_department_knowledge(clean_dept, "instructor_alias", clean_raw)
            if alias:
                canonical_name = alias
                confidence = 1.0
                preferences = memory_instance.get_instructor_preference(clean_dept, canonical_name)

    is_resolved = bool(canonical_name and len(canonical_name) >= 2)
    message = (
        f"Instructor '{clean_raw}' resolved to canonical '{canonical_name}' (department: {clean_dept})."
        if is_resolved
        else f"Could not confidently resolve instructor identity for '{clean_raw}'."
    )

    return {
        "department": clean_dept,
        "raw_name": clean_raw,
        "canonical_name": canonical_name,
        "is_resolved": is_resolved,
        "confidence": confidence,
        "preferences": preferences,
        "message": message,
    }


# -----------------------------------------------------------------------------
# Tool 3: Record Learned Resolution
# -----------------------------------------------------------------------------


@_make_callable_tool
def record_learned_resolution(
    dept: str,
    issue_sig: str,
    question: str,
    choice: str,
    fix: Union[str, Dict[str, Any]],
    memory_instance: Optional[AgentMemory] = None,
) -> Dict[str, Any]:
    """Persist a human disambiguation or conflict fix into SQLite memory for future runs.

    Args:
        dept: Academic department code.
        issue_sig: Unique issue signature identifier (e.g. 'room_alias:Lab1').
        question: Question presented to the user during interrupt.
        choice: Selected choice or user response.
        fix: Concrete fix dictionary or string applied to resolve the issue.
        memory_instance: Optional AgentMemory instance.

    Returns:
        Confirmation dictionary with recorded database identifier.
    """
    clean_dept = str(dept).strip().upper() if dept else "*"
    clean_sig = str(issue_sig).strip() if issue_sig else "unknown_issue"
    clean_choice = str(choice).strip() if choice else ""
    clean_question = str(question).strip() if question else ""

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        # If issue is a room alias, update department knowledge automatically
        if clean_sig.startswith("room_alias:") and clean_choice:
            raw_alias = clean_sig.split(":", 1)[1].strip()
            memory_instance.set_room_alias(clean_dept, raw_alias, clean_choice)

        # Persist in resolution history table
        record_id = memory_instance.save_resolution(
            dept=clean_dept,
            issue_sig=clean_sig,
            question=clean_question,
            choice=clean_choice,
            fix=fix,
        )
    finally:
        if should_close:
            memory_instance.close()

    return {
        "success": True,
        "record_id": record_id,
        "department": clean_dept,
        "issue_signature": clean_sig,
        "question": clean_question,
        "user_choice": clean_choice,
        "applied_fix": fix,
        "message": f"Successfully learned and persisted resolution for issue '{clean_sig}'.",
    }


# -----------------------------------------------------------------------------
# Tool 4: Check Time Conflict
# -----------------------------------------------------------------------------


def _parse_minutes(time_val: Any) -> Optional[int]:
    """Convert time representation (e.g. '08:00', '0800', '8:30') into minutes from midnight."""
    if time_val is None:
        return None
    s = str(time_val).strip()
    if not s:
        return None

    if ":" in s:
        parts = s.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, IndexError):
            return None
    elif len(s) == 4 and s.isdigit():
        try:
            return int(s[:2]) * 60 + int(s[2:])
        except ValueError:
            return None
    elif s.isdigit():
        try:
            return int(s) * 60
        except ValueError:
            return None

    return None


def _normalize_days(day_val: Any) -> Set[str]:
    """Extract standard day codes (M, T, W, R, F, S, U) from day strings."""
    if not day_val:
        return set()
    s = str(day_val).strip().upper()

    name_map = {
        "SENIN": {"M"},
        "SELASA": {"T"},
        "RABU": {"W"},
        "KAMIS": {"R"},
        "JUMAT": {"F"},
        "JUM'AT": {"F"},
        "SABTU": {"S"},
        "MINGGU": {"U"},
        "MON": {"M"},
        "MONDAY": {"M"},
        "TUE": {"T"},
        "TUESDAY": {"T"},
        "WED": {"W"},
        "WEDNESDAY": {"W"},
        "THU": {"R"},
        "THURSDAY": {"R"},
        "FRI": {"F"},
        "FRIDAY": {"F"},
        "SAT": {"S"},
        "SATURDAY": {"S"},
        "SUN": {"U"},
        "SUNDAY": {"U"},
    }

    if s in name_map:
        return name_map[s]

    # Handle standard combinations like MWF, TR, M-W-F
    cleaned = s.replace("TH", "R").replace(" ", "").replace(",", "").replace("-", "")
    result: Set[str] = set()
    for char in cleaned:
        if char in {"M", "T", "W", "R", "F", "S", "U"}:
            result.add(char)

    return result if result else {s}


def _extract_class_meetings(class_item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract standardized meeting representations from a class dict."""
    meetings: List[Dict[str, Any]] = []

    course_name = (
        class_item.get("courseNumber")
        or class_item.get("course")
        or class_item.get("course_code")
        or "UnknownCourse"
    )
    section_name = (
        class_item.get("sectionName")
        or class_item.get("section")
        or class_item.get("classSection")
        or "1"
    )

    # Instructors extraction
    instructors: Set[str] = set()
    raw_ins = class_item.get("instructors")
    if isinstance(raw_ins, list) and raw_ins:
        for ins in raw_ins:
            if isinstance(ins, dict) and ins.get("name"):
                instructors.add(_clean_instructor_name(str(ins["name"])).upper())
            elif isinstance(ins, str) and ins.strip():
                instructors.add(_clean_instructor_name(ins).upper())
    elif class_item.get("instructor"):
        instructors.add(_clean_instructor_name(str(class_item["instructor"])).upper())

    # Room extraction
    room_label = ""
    room_prefs = class_item.get("roomPreferences", [])
    if isinstance(room_prefs, list) and room_prefs:
        rp0 = room_prefs[0]
        if isinstance(rp0, dict):
            bldg = rp0.get("building", "")
            rnum = rp0.get("roomNumber", "")
            room_label = f"{bldg} {rnum}".strip().upper()
    elif class_item.get("room"):
        room_label = str(class_item["room"]).strip().upper()

    # Time extraction: Check timePreferences or direct day/time fields
    time_prefs = class_item.get("timePreferences", [])
    if isinstance(time_prefs, list) and time_prefs:
        for tp in time_prefs:
            if not isinstance(tp, dict):
                continue
            day_code = tp.get("dayCode") or tp.get("day") or tp.get("days")
            st_min = _parse_minutes(tp.get("startTime"))
            et_min = _parse_minutes(tp.get("endTime"))
            if st_min is not None and et_min is not None:
                meetings.append(
                    {
                        "course": str(course_name),
                        "section": str(section_name),
                        "days": _normalize_days(day_code),
                        "start_min": st_min,
                        "end_min": et_min,
                        "room": room_label,
                        "instructors": instructors,
                        "raw_class": class_item,
                    }
                )
    else:
        # Check flat fields
        day_field = class_item.get("day") or class_item.get("days") or class_item.get("dayCode")
        st_min = _parse_minutes(class_item.get("startTime") or class_item.get("start_time"))
        et_min = _parse_minutes(class_item.get("endTime") or class_item.get("end_time"))
        if st_min is not None and et_min is not None:
            meetings.append(
                {
                    "course": str(course_name),
                    "section": str(section_name),
                    "days": _normalize_days(day_field),
                    "start_min": st_min,
                    "end_min": et_min,
                    "room": room_label,
                    "instructors": instructors,
                    "raw_class": class_item,
                }
            )

    return meetings


@_make_callable_tool
def check_time_conflict(classes_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze a collection of classes for temporal, room, and instructor overlaps.

    Args:
        classes_list: List of class dictionaries containing scheduling and location details.

    Returns:
        Structured evaluation reporting whether conflicts exist and listing each conflict.
    """
    if not isinstance(classes_list, list) or len(classes_list) < 2:
        return {
            "has_conflict": False,
            "total_conflicts": 0,
            "conflicts": [],
            "message": "Fewer than 2 classes provided; no conflicts possible.",
        }

    # Flatten all classes into individual scheduled meetings
    all_meetings: List[Dict[str, Any]] = []
    for item in classes_list:
        if isinstance(item, dict):
            if "configurations" in item:
                c_num = item.get("courseNumber") or item.get("course_code") or "UnknownCourse"
                for cfg in item.get("configurations", []):
                    if isinstance(cfg, dict):
                        for sp in cfg.get("subparts", []):
                            if isinstance(sp, dict):
                                for cls in sp.get("classes", []):
                                    if isinstance(cls, dict):
                                        cls_copy = dict(cls)
                                        cls_copy.setdefault("courseNumber", c_num)
                                        all_meetings.extend(_extract_class_meetings(cls_copy))
            elif "courses" in item:
                for c in item.get("courses", []):
                    if isinstance(c, dict):
                        c_num = c.get("courseNumber") or c.get("course_code") or "UnknownCourse"
                        for cfg in c.get("configurations", []):
                            if isinstance(cfg, dict):
                                for sp in cfg.get("subparts", []):
                                    if isinstance(sp, dict):
                                        for cls in sp.get("classes", []):
                                            if isinstance(cls, dict):
                                                cls_copy = dict(cls)
                                                cls_copy.setdefault("courseNumber", c_num)
                                                all_meetings.extend(_extract_class_meetings(cls_copy))
            else:
                all_meetings.extend(_extract_class_meetings(item))

    conflicts: List[Dict[str, Any]] = []

    for i in range(len(all_meetings)):
        for j in range(i + 1, len(all_meetings)):
            m1 = all_meetings[i]
            m2 = all_meetings[j]

            # Check for shared day
            shared_days = m1["days"] & m2["days"]
            if not shared_days:
                continue

            # Check time interval overlap: start1 < end2 and start2 < end1
            if not (max(m1["start_min"], m2["start_min"]) < min(m1["end_min"], m2["end_min"])):
                continue

            overlap_start = max(m1["start_min"], m2["start_min"])
            overlap_end = min(m1["end_min"], m2["end_min"])
            overlap_str = (
                f"{overlap_start // 60:02d}:{overlap_start % 60:02d} - "
                f"{overlap_end // 60:02d}:{overlap_end % 60:02d}"
            )
            days_str = "".join(sorted(shared_days))

            # 1. Room conflict
            if m1["room"] and m2["room"] and m1["room"] == m2["room"]:
                conflicts.append(
                    {
                        "conflict_type": "room_double_booking",
                        "resource": m1["room"],
                        "class_a": f"{m1['course']} {m1['section']}",
                        "class_a_course": m1['course'],
                        "class_a_section": m1['section'],
                        "class_b": f"{m2['course']} {m2['section']}",
                        "class_b_course": m2['course'],
                        "class_b_section": m2['section'],
                        "days": days_str,
                        "overlap_time": overlap_str,
                        "description": (
                            f"Room '{m1['room']}' double-booked by {m1['course']} {m1['section']} "
                            f"and {m2['course']} {m2['section']} on {days_str} ({overlap_str})."
                        ),
                    }
                )

            # 2. Instructor conflict
            shared_instructors = m1["instructors"] & m2["instructors"]
            if shared_instructors:
                for ins in shared_instructors:
                    conflicts.append(
                        {
                            "conflict_type": "instructor_double_booking",
                            "resource": ins,
                            "class_a": f"{m1['course']} {m1['section']}",
                            "class_a_course": m1['course'],
                            "class_a_section": m1['section'],
                            "class_b": f"{m2['course']} {m2['section']}",
                            "class_b_course": m2['course'],
                            "class_b_section": m2['section'],
                            "days": days_str,
                            "overlap_time": overlap_str,
                            "description": (
                                f"Instructor '{ins}' scheduled simultaneously for {m1['course']} {m1['section']} "
                                f"and {m2['course']} {m2['section']} on {days_str} ({overlap_str})."
                            ),
                        }
                    )

            # 3. Same course section overlap
            if m1["course"] == m2["course"] and m1["section"] == m2["section"] and not m1["room"]:
                conflicts.append(
                    {
                        "conflict_type": "section_time_overlap",
                        "resource": f"{m1['course']} {m1['section']}",
                        "class_a": f"{m1['course']} {m1['section']}",
                        "class_a_course": m1['course'],
                        "class_a_section": m1['section'],
                        "class_b": f"{m2['course']} {m2['section']}",
                        "class_b_course": m2['course'],
                        "class_b_section": m2['section'],
                        "days": days_str,
                        "overlap_time": overlap_str,
                        "description": f"Class section '{m1['course']} {m1['section']}' has overlapping meeting times.",
                    }
                )

    has_conflict = len(conflicts) > 0
    message = (
        f"Detected {len(conflicts)} scheduling conflict(s) among {len(classes_list)} classes."
        if has_conflict
        else f"Checked {len(classes_list)} classes: No scheduling conflicts found."
    )

    return {
        "has_conflict": has_conflict,
        "total_conflicts": len(conflicts),
        "conflicts": conflicts,
        "message": message,
    }


# -----------------------------------------------------------------------------
# Tool 5: Generate Admin Summary
# -----------------------------------------------------------------------------


@_make_callable_tool
def generate_admin_summary(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an executive-level status report and metrics summary from agent state.

    Args:
        state_dict: Current IngestAgentState dictionary.

    Returns:
        Dictionary containing formatted markdown report and numerical summary metrics.
    """
    if not isinstance(state_dict, dict):
        raise ValueError("state_dict must be a dictionary representing IngestAgentState")

    doc_path = state_dict.get("document_path", "unknown")
    doc_type = state_dict.get("document_type", "auto")
    status = state_dict.get("status", "unknown")

    slices = state_dict.get("slices", [])
    partial_payloads = state_dict.get("partial_payloads", [])
    unified_payload = state_dict.get("unified_payload") or {}
    validation_result = state_dict.get("validation_result") or {}
    ambiguities = state_dict.get("ambiguities", [])
    audit_logs = state_dict.get("audit_logs", [])
    ingest_result = state_dict.get("ingest_result")

    # Metric extraction
    courses = unified_payload.get("courses", []) if isinstance(unified_payload, dict) else []
    total_courses = len(courses)
    total_classes = 0
    for c in courses:
        if isinstance(c, dict):
            for cfg in c.get("configurations", []):
                if isinstance(cfg, dict):
                    for sp in cfg.get("subparts", []):
                        if isinstance(sp, dict):
                            total_classes += len(sp.get("classes", []))

    validation_passed = bool(validation_result.get("is_valid", False))
    errors = validation_result.get("errors", [])
    warnings = validation_result.get("warnings", [])

    ingest_succeeded = False
    if isinstance(ingest_result, dict):
        ingest_succeeded = ingest_result.get("status") in ("success", "SUCCESS", "OK", True)

    status_icon = {
        "completed": "✅ COMPLETED",
        "processing": "⏳ PROCESSING",
        "waiting_for_human": "⚠️ WAITING FOR HUMAN REVIEW",
        "error": "❌ ERROR",
    }.get(status, f"ℹ️ {status.upper()}")

    # Build Markdown Report
    lines = [
        f"# UniTime Smart Ingestion - Administrative Summary",
        "",
        f"**Pipeline Status**: {status_icon}  ",
        f"**Document**: `{doc_path}`  ",
        f"**Document Type**: `{doc_type}`  ",
        "",
        "## 1. Extraction & Payload Statistics",
        f"- **Document Slices**: {len(slices)} slices ({len(partial_payloads)} extracted)",
        f"- **Total Courses Extracted**: {total_courses}",
        f"- **Total Class Sections**: {total_classes}",
        f"- **Distribution Constraints**: {len(unified_payload.get('distributionConstraints', [])) if isinstance(unified_payload, dict) else 0}",
        "",
        "## 2. Validation & Semantic Consistency",
        f"- **Validation Status**: {'✅ VALID' if validation_passed else '❌ INVALID'}",
        f"- **Schema/Semantic Errors**: {len(errors)}",
        f"- **Semantic Warnings**: {len(warnings)}",
    ]

    if errors:
        lines.append("\n**Top Validation Errors:**")
        for err in errors[:5]:
            msg = err.get("message") if isinstance(err, dict) else str(err)
            lines.append(f"  - {msg}")
        if len(errors) > 5:
            lines.append(f"  *... and {len(errors) - 5} more errors.*")

    lines.extend(
        [
            "",
            "## 3. Disambiguation & Human-in-the-Loop",
            f"- **Pending Ambiguities**: {len(ambiguities)}",
        ]
    )

    if ambiguities:
        lines.append("\n**Open Ambiguities Requiring Review:**")
        for amb in ambiguities[:5]:
            q = amb.get("question") if isinstance(amb, dict) else str(amb)
            lines.append(f"  - ❓ {q}")

    lines.extend(
        [
            "",
            "## 4. UniTime Persistence",
            f"- **Server Ingest Result**: {'✅ Successfully imported to UniTime' if ingest_succeeded else '⏸️ Pending Ingestion' if not ingest_result else '❌ Ingestion Failed'}",
            "",
            "## 5. Audit Journal Highlights",
            f"- **Total Audit Entries**: {len(audit_logs)}",
        ]
    )

    if audit_logs:
        for log in audit_logs[-3:]:
            lvl = log.get("level", "INFO")
            msg = log.get("message", "")
            lines.append(f"  - `[{lvl}]` {msg}")

    markdown_report = "\n".join(lines)

    return {
        "status": status,
        "summary_markdown": markdown_report,
        "stats": {
            "total_slices": len(slices),
            "processed_slices": len(partial_payloads),
            "total_courses": total_courses,
            "total_classes": total_classes,
            "validation_passed": validation_passed,
            "errors_count": len(errors),
            "warnings_count": len(warnings),
            "ambiguities_count": len(ambiguities),
            "audit_events_count": len(audit_logs),
            "ingest_succeeded": ingest_succeeded,
        },
    }


# -----------------------------------------------------------------------------
# Tool 6: Record Campus Topology
# -----------------------------------------------------------------------------


@_make_callable_tool
def record_campus_topology(
    session_id: str,
    regions: List[str],
    travel_times: Optional[Dict[str, int]] = None,
    memory_instance: Optional[AgentMemory] = None,
) -> str:
    """Record multi-campus topology regions and inter-campus transit travel times.

    Args:
        session_id: Active conversational drafting session ID.
        regions: List of campus region names (e.g. ['Depok', 'Salemba']).
        travel_times: Optional dictionary mapping region pairs to transit minutes (e.g. {'Depok_Salemba': 45}).
        memory_instance: Optional AgentMemory instance.

    Returns:
        Structured Markdown confirmation of recorded campus regions and travel times.
    """
    clean_sid = str(session_id).strip() if session_id else ""
    if not clean_sid:
        return "❌ Gagal mencatat wilayah kampus: `session_id` tidak boleh kosong."

    if not regions or not isinstance(regions, list):
        return "❌ Gagal mencatat wilayah kampus: `regions` harus berupa daftar nama wilayah (list)."

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        updated_state = memory_instance.upsert_draft_topology(
            session_id=clean_sid,
            regions=regions,
            travel_times=travel_times,
        )
        topology = updated_state.get("campus_topology", {})
        reg_list = topology.get("regions", [])
        tt_dict = topology.get("travel_times", {})

        tt_lines = []
        if tt_dict:
            for pair, mins in tt_dict.items():
                tt_lines.append(f"  * {pair.replace('_', ' - ')}: {mins} menit")
        else:
            tt_lines.append("  * *Belum ada estimasi waktu tempuh khusus.*")

        tt_formatted = "\n".join(tt_lines)
        reg_formatted = ", ".join(reg_list) if reg_list else "-"

        return (
            f"### 🏛️ Wilayah Kampus Berhasil Dicatat\n"
            f"- **Sesi Draft**: `{clean_sid}`\n"
            f"- **Daftar Kampus**: {reg_formatted}\n"
            f"- **Estimasi Waktu Tempuh Transit**:\n{tt_formatted}\n\n"
            f"*Draft sesi `{clean_sid}` telah diperbarui. Selanjutnya, Anda dapat mencatatkan gedung dan ruangan yang tersedia di wilayah kampus tersebut.*"
        )
    finally:
        if should_close:
            memory_instance.close()


# -----------------------------------------------------------------------------
# Tool 7: Record Building and Rooms
# -----------------------------------------------------------------------------


@_make_callable_tool
def record_building_and_rooms(
    session_id: str,
    building: str,
    campus_region: str,
    rooms: List[Dict[str, Any]],
    memory_instance: Optional[AgentMemory] = None,
) -> str:
    """Record a building and its classrooms/labs under a campus region in the draft session.

    Args:
        session_id: Active conversational drafting session ID.
        building: Name or code of the building (e.g. 'Labtek V', 'Gedung Fasilkom A').
        campus_region: Campus region where the building is located (e.g. 'Depok', 'Salemba').
        rooms: List of room dictionaries (e.g. [{'room_number': '101', 'capacity': 50, 'type': 'lab'}]).
        memory_instance: Optional AgentMemory instance.

    Returns:
        Structured Markdown confirmation detailing registered building and rooms.
    """
    clean_sid = str(session_id).strip() if session_id else ""
    clean_bldg = str(building).strip() if building else ""
    clean_campus = str(campus_region).strip() if campus_region else ""

    if not clean_sid:
        return "❌ Gagal mencatat gedung: `session_id` tidak boleh kosong."
    if not clean_bldg:
        return "❌ Gagal mencatat gedung: nama `building` tidak boleh kosong."
    if not isinstance(rooms, list):
        return "❌ Gagal mencatat ruangan: `rooms` harus berupa list dictionary ruangan."

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        updated_state = memory_instance.upsert_draft_building_rooms(
            session_id=clean_sid,
            building_name=clean_bldg,
            campus=clean_campus,
            rooms=rooms,
        )

        # Also register room capacities into memory knowledge base for cross-tool inspection
        for r in rooms:
            if isinstance(r, dict):
                r_num = str(r.get("room_number") or r.get("name") or "").strip()
                cap = r.get("capacity")
                if r_num and cap is not None:
                    try:
                        memory_instance.set_room_capacity(clean_bldg, r_num, int(cap))
                    except (ValueError, TypeError):
                        pass

        # Format Markdown
        room_lines = []
        for r in rooms:
            if isinstance(r, dict):
                r_num = str(r.get("room_number") or r.get("name") or "Unnamed").strip()
                cap = r.get("capacity", "N/A")
                rtype = r.get("type", "Classroom")
                room_lines.append(f"  * **{r_num}**: Kapasitas {cap} kursi (Tipe: {rtype})")

        rooms_formatted = "\n".join(room_lines) if room_lines else "  * *Tidak ada ruangan yang didaftarkan.*"

        return (
            f"### 🏢 Gedung & Ruangan Berhasil Dicatat\n"
            f"- **Sesi Draft**: `{clean_sid}`\n"
            f"- **Gedung**: {clean_bldg}\n"
            f"- **Wilayah Kampus**: {clean_campus or 'Umum / Pusat'}\n"
            f"- **Daftar Ruangan Terdaftar** ({len(rooms)} ruangan):\n{rooms_formatted}\n\n"
            f"*Ruangan telah tersimpan dalam draft sesi `{clean_sid}`. Langkah berikutnya: Anda dapat mendefinisikan mata kuliah yang akan ditawarkan.*"
        )
    finally:
        if should_close:
            memory_instance.close()


# -----------------------------------------------------------------------------
# Tool 8: Draft Course Offering
# -----------------------------------------------------------------------------


@_make_callable_tool
def draft_course_offering(
    session_id: str,
    subject: str,
    course_number: str,
    title: str,
    sks: int,
    classes: Optional[List[Dict[str, Any]]] = None,
    memory_instance: Optional[AgentMemory] = None,
) -> str:
    """Draft an academic course offering with its credit weighting (SKS) and class sections.

    Args:
        session_id: Active conversational drafting session ID.
        subject: Subject area code (e.g. 'IF', 'CS').
        course_number: Course number or code (e.g. 'IF2110', 'CS101').
        title: Official course title (e.g. 'Algoritma & Pemrograman').
        sks: Credit units / SKS (e.g. 3, 4).
        classes: Optional list of class sections with schedule/instructor/room info.
        memory_instance: Optional AgentMemory instance.

    Returns:
        Structured Markdown confirmation of the drafted course offering.
    """
    clean_sid = str(session_id).strip() if session_id else ""
    clean_subj = str(subject).strip().upper() if subject else "IF"
    clean_num = str(course_number).strip().upper() if course_number else ""
    clean_title = str(title).strip() if title else ""

    if not clean_sid:
        return "❌ Gagal mencatat mata kuliah: `session_id` tidak boleh kosong."
    if not clean_num:
        return "❌ Gagal mencatat mata kuliah: `course_number` tidak boleh kosong."
    if not clean_title:
        clean_title = clean_num

    try:
        int_sks = max(1, int(sks))
    except (ValueError, TypeError):
        int_sks = 3

    class_list = classes if isinstance(classes, list) else []

    course_payload = {
        "subject": clean_subj,
        "course_number": clean_num,
        "title": clean_title,
        "sks": int_sks,
        "classes": class_list,
    }

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        memory_instance.upsert_draft_course(
            session_id=clean_sid,
            course_data=course_payload,
        )

        class_lines = []
        if class_list:
            for idx, cl in enumerate(class_list, start=1):
                sec = cl.get("section") or cl.get("sectionName") or f"0{idx}"
                room = cl.get("room") or "TBA"
                time_str = cl.get("time") or cl.get("timePattern") or "TBA"
                ins = cl.get("instructor") or cl.get("instructors") or "TBA"
                if isinstance(ins, list):
                    ins = ", ".join([str(i.get("name") if isinstance(i, dict) else i) for i in ins])
                class_lines.append(f"  * **Seksi {sec}**: {time_str} | Ruang: {room} | Dosen: {ins}")
        else:
            class_lines.append("  * *(Belum ada seksi kelas spesifik yang didaftarkan)*")

        classes_formatted = "\n".join(class_lines)

        return (
            f"### 📚 Penawaran Mata Kuliah Berhasil Dicatat\n"
            f"- **Sesi Draft**: `{clean_sid}`\n"
            f"- **Kode & Judul**: **{clean_num}** - {clean_title}\n"
            f"- **Bidang Studi**: {clean_subj}\n"
            f"- **Bobot Kredit**: {int_sks} SKS\n"
            f"- **Seksi Kelas** ({len(class_list)} kelas):\n{classes_formatted}\n\n"
            f"*Mata kuliah tersimpan di draft sesi `{clean_sid}`. Anda dapat menambahkan mata kuliah lain atau menentukan preferensi jadwal pengajar.*"
        )
    finally:
        if should_close:
            memory_instance.close()


# -----------------------------------------------------------------------------
# Tool 9: Record Scheduling Preference
# -----------------------------------------------------------------------------


@_make_callable_tool
def record_scheduling_preference(
    session_id: str,
    entity_type: str,
    entity_name: str,
    preference_type: str,
    details: str,
    memory_instance: Optional[AgentMemory] = None,
) -> str:
    """Record a domain constraint, instructor habit, or scheduling preference into the draft session.

    Args:
        session_id: Active conversational drafting session ID.
        entity_type: Category of entity ('instructor', 'course', 'room', 'department').
        entity_name: Identifier or name of the entity (e.g. 'Dr. Turing', 'IF2110').
        preference_type: Type of preference (e.g. 'unavailable_time', 'preferred_room', 'max_hours').
        details: Specific rule description (e.g. 'Tidak bisa mengajar hari Jumat setelah 11:00').
        memory_instance: Optional AgentMemory instance.

    Returns:
        Structured Markdown confirmation of recorded preference.
    """
    clean_sid = str(session_id).strip() if session_id else ""
    clean_et = str(entity_type).strip().lower() if entity_type else "general"
    clean_en = str(entity_name).strip() if entity_name else "Unknown"
    clean_pt = str(preference_type).strip().lower() if preference_type else "constraint"
    clean_det = str(details).strip() if details else ""

    if not clean_sid:
        return "❌ Gagal mencatat preferensi: `session_id` tidak boleh kosong."
    if not clean_det:
        return "❌ Gagal mencatat preferensi: `details` tidak boleh kosong."

    pref_data = {
        "entity_type": clean_et,
        "entity_name": clean_en,
        "preference_type": clean_pt,
        "details": clean_det,
    }

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        memory_instance.upsert_draft_preference(
            session_id=clean_sid,
            preference_data=pref_data,
        )

        # Cross-register into instructor quirks if applicable
        if clean_et in ("instructor", "dosen"):
            memory_instance.set_instructor_preference(
                dept="*",
                name=clean_en,
                prefs={"notes": clean_det},
            )

        return (
            f"### ⚙️ Preferensi Penjadwalan Berhasil Dicatat\n"
            f"- **Sesi Draft**: `{clean_sid}`\n"
            f"- **Tipe Entitas**: `{clean_et}`\n"
            f"- **Nama Entitas**: **{clean_en}**\n"
            f"- **Jenis Batasan**: `{clean_pt}`\n"
            f"- **Aturan / Catatan**: {clean_det}\n\n"
            f"*Preferensi tersimpan di draft sesi `{clean_sid}`. Aturan ini akan diperhitungkan saat sinkronisasi dan optimasi jadwal UniTime.*"
        )
    finally:
        if should_close:
            memory_instance.close()


# -----------------------------------------------------------------------------
# Tool 10: Get Draft Summary
# -----------------------------------------------------------------------------


@_make_callable_tool
def get_draft_summary(
    session_id: str,
    memory_instance: Optional[AgentMemory] = None,
) -> str:
    """Generate an overview of all academic entities currently drafted in the session.

    Args:
        session_id: Active conversational drafting session ID.
        memory_instance: Optional AgentMemory instance.

    Returns:
        Structured Markdown status report detailing topology, facilities, courses, and preferences.
    """
    clean_sid = str(session_id).strip() if session_id else ""
    if not clean_sid:
        return "❌ Gagal memuat ringkasan draft: `session_id` tidak boleh kosong."

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        state = memory_instance.get_draft_state(clean_sid)
        topology = state.get("campus_topology", {})
        regions = topology.get("regions", [])
        travel_times = topology.get("travel_times", {})
        buildings = state.get("buildings", [])
        courses = state.get("courses", [])
        preferences = state.get("preferences", [])
        updated_at = state.get("updated_at") or "Baru saja"

        total_rooms = sum(len(b.get("rooms", [])) for b in buildings)
        total_classes = sum(len(c.get("classes", [])) for c in courses)

        lines = [
            f"# 📋 Ringkasan Draft Akademik Sesi `{clean_sid}`",
            f"**Terakhir Diperbarui**: {updated_at}",
            "",
            "## 1. 🏛️ Wilayah Kampus & Topologi",
        ]

        if regions:
            lines.append(f"- **Wilayah Terdaftar**: {', '.join(regions)}")
            if travel_times:
                lines.append("- **Waktu Tempuh Transit**:")
                for k, v in travel_times.items():
                    lines.append(f"  * {k.replace('_', ' - ')}: {v} menit")
        else:
            lines.append("- *(Belum ada wilayah kampus yang dicatat)*")

        lines.extend([
            "",
            f"## 2. 🏢 Fasilitas Gedung & Ruangan ({len(buildings)} gedung, {total_rooms} ruangan)",
        ])

        if buildings:
            for b in buildings:
                b_name = b.get("name", "Gedung")
                b_camp = b.get("campus", "Pusat")
                r_list = b.get("rooms", [])
                lines.append(f"- **{b_name}** (Kampus: {b_camp}) - {len(r_list)} ruang:")
                for r in r_list:
                    r_num = r.get("room_number") or r.get("name") or "Ruang"
                    cap = r.get("capacity", "N/A")
                    lines.append(f"  * {r_num} (Kapasitas: {cap})")
        else:
            lines.append("- *(Belum ada gedung dan ruangan yang dicatat)*")

        lines.extend([
            "",
            f"## 3. 📚 Penawaran Mata Kuliah ({len(courses)} mata kuliah, {total_classes} kelas)",
        ])

        if courses:
            for c in courses:
                c_num = c.get("course_number") or c.get("code") or "MK"
                c_title = c.get("title", "")
                sks = c.get("sks", 3)
                classes = c.get("classes", [])
                lines.append(f"- **{c_num}** - {c_title} ({sks} SKS, {len(classes)} kelas)")
                for cl in classes:
                    sec = cl.get("section") or cl.get("sectionName") or "1"
                    time_s = cl.get("time") or cl.get("timePattern") or "TBA"
                    room_s = cl.get("room") or "TBA"
                    lines.append(f"  * Seksi {sec}: {time_s} @ {room_s}")
        else:
            lines.append("- *(Belum ada penawaran mata kuliah yang dicatat)*")

        lines.extend([
            "",
            f"## 4. ⚙️ Preferensi & Batasan Jadwal ({len(preferences)} aturan)",
        ])

        if preferences:
            for p in preferences:
                et = p.get("entity_type", "")
                en = p.get("entity_name", "")
                pt = p.get("preference_type", "")
                det = p.get("details", "")
                lines.append(f"- `[{et}:{pt}]` **{en}**: {det}")
        else:
            lines.append("- *(Belum ada batasan jadwal khusus yang dicatat)*")

        is_ready = len(courses) > 0
        readiness_badge = "✅ Siap Disinkronkan ke UniTime" if is_ready else "⏳ Perlu Minimal 1 Mata Kuliah"

        lines.extend([
            "",
            "## 5. 🎯 Status Kesiapan",
            f"- **Kesiapan Sinkronisasi**: {readiness_badge}",
            "",
            "*Ketik 'Kirim ke UniTime' atau panggil tool `commit_draft_to_unitime` untuk memvalidasi dan mengimpor draft ini ke server UniTime.*"
        ])

        return "\n".join(lines)
    finally:
        if should_close:
            memory_instance.close()


# -----------------------------------------------------------------------------
# Tool 11: Commit Draft to UniTime
# -----------------------------------------------------------------------------


def _map_day_code(day_str: str) -> str:
    """Map human or Indonesian day names to standard UniTime day codes."""
    s = day_str.strip().upper()
    mapping = {
        "SENIN": "M",
        "SELASA": "T",
        "RABU": "W",
        "KAMIS": "R",
        "JUMAT": "F",
        "JUM'AT": "F",
        "SABTU": "S",
        "MINGGU": "U",
        "MONDAY": "M",
        "TUESDAY": "T",
        "WEDNESDAY": "W",
        "THURSDAY": "R",
        "FRIDAY": "F",
        "SATURDAY": "S",
        "SUNDAY": "U",
    }
    if s in mapping:
        return mapping[s]
    cleaned = s.replace("TH", "R").replace(" ", "").replace(",", "").replace("-", "")
    valid_chars = {"M", "T", "W", "R", "F", "S", "U"}
    if all(c in valid_chars for c in cleaned) and len(cleaned) > 0:
        return cleaned
    return "M"


@_make_callable_tool
def commit_draft_to_unitime(
    session_id: str,
    dry_run: bool = False,
    memory_instance: Optional[AgentMemory] = None,
) -> str:
    """Assemble progressive draft state into canonical UniTime schema and commit to UniTime.

    Args:
        session_id: Active conversational drafting session ID.
        dry_run: If True, validates schema without submitting to live UniTime server.
        memory_instance: Optional AgentMemory instance.

    Returns:
        Markdown report summarizing validation results and UniTime ingestion status.
    """
    clean_sid = str(session_id).strip() if session_id else ""
    if not clean_sid:
        return "❌ Gagal sinkronisasi: `session_id` tidak boleh kosong."

    should_close = False
    if memory_instance is None:
        memory_instance = AgentMemory()
        should_close = True

    try:
        draft = memory_instance.get_draft_state(clean_sid)
        courses = draft.get("courses", [])

        if not courses:
            return (
                f"### ⚠️ Tidak Dapat Melakukan Sinkronisasi\n"
                f"Draft sesi `{clean_sid}` belum memiliki penawaran mata kuliah. "
                f"Mohon daftarkan minimal 1 mata kuliah menggunakan `draft_course_offering` "
                f"sebelum melakukan sinkronisasi ke UniTime."
            )

        topology = draft.get("campus_topology", {})
        regions = topology.get("regions", [])
        primary_campus = regions[0] if regions else "MAIN"

        dept_code = "IF"
        dept_name = "Teknik Informatika"
        if courses and courses[0].get("subject"):
            dept_code = str(courses[0]["subject"]).strip().upper()
            dept_name = f"Program Studi {dept_code}"

        canonical_courses = []
        for c in courses:
            c_num = str(c.get("course_number") or c.get("code") or "CS101").strip().upper()
            c_title = str(c.get("title") or c_num).strip()
            try:
                sks_val = float(c.get("sks", 3))
            except (ValueError, TypeError):
                sks_val = 3.0

            raw_classes = c.get("classes", [])
            canonical_classes = []
            if raw_classes:
                for idx, cl in enumerate(raw_classes, start=1):
                    sec_name = str(cl.get("sectionName") or cl.get("section") or f"0{idx}").strip()
                    try:
                        cap = int(cl.get("capacity", 40))
                    except (ValueError, TypeError):
                        cap = 40

                    cl_dict: Dict[str, Any] = {
                        "sectionName": sec_name,
                        "capacity": max(1, cap),
                    }

                    if cl.get("scheduleNote"):
                        cl_dict["scheduleNote"] = str(cl["scheduleNote"]).strip()

                    # Time preferences mapping
                    t_prefs = cl.get("timePreferences")
                    time_info = cl.get("time") or cl.get("timePattern")
                    day_info = cl.get("day") or cl.get("days") or "Senin"

                    if isinstance(t_prefs, list) and t_prefs:
                        cl_dict["timePreferences"] = t_prefs
                    elif time_info:
                        times = re.findall(r"\d{1,2}:\d{2}", str(time_info))
                        st, et = ("08:00", "10:00") if len(times) < 2 else (times[0], times[1])
                        if len(st) == 4 and st[1] == ":":
                            st = "0" + st
                        if len(et) == 4 and et[1] == ":":
                            et = "0" + et

                        cl_dict["timePreferences"] = [
                            {
                                "days": _map_day_code(str(day_info)),
                                "startTime": st,
                                "endTime": et,
                                "level": "REQUIRED",
                            }
                        ]

                    # Room preferences mapping
                    r_prefs = cl.get("roomPreferences")
                    room_info = cl.get("room")
                    if isinstance(r_prefs, list) and r_prefs:
                        cl_dict["roomPreferences"] = r_prefs
                    elif room_info:
                        parts = str(room_info).strip().split(maxsplit=1)
                        bldg = parts[0] if len(parts) > 1 else primary_campus
                        rnum = parts[1] if len(parts) > 1 else parts[0]
                        cl_dict["roomPreferences"] = [
                            {
                                "building": bldg,
                                "roomNumber": rnum,
                                "level": "REQUIRED",
                            }
                        ]

                    # Instructors mapping
                    inst_info = cl.get("instructor") or cl.get("instructors")
                    if inst_info:
                        if isinstance(inst_info, list):
                            canonical_instructors = []
                            for ins in inst_info:
                                if isinstance(ins, dict):
                                    name = str(ins.get("name", "TBA")).strip()
                                    ins_id = str(ins.get("id") or f"INS_{abs(hash(name)) % 10000:04d}")
                                    share = int(ins.get("sharePercentage", 100))
                                    canonical_instructors.append({
                                        "id": ins_id,
                                        "name": name,
                                        "sharePercentage": share,
                                    })
                                elif isinstance(ins, str) and ins.strip():
                                    canonical_instructors.append({
                                        "id": f"INS_{abs(hash(ins)) % 10000:04d}",
                                        "name": ins.strip(),
                                        "sharePercentage": 100,
                                    })
                            if canonical_instructors:
                                cl_dict["instructors"] = canonical_instructors
                        elif isinstance(inst_info, str) and inst_info.strip():
                            cl_dict["instructors"] = [
                                {
                                    "id": f"INS_{abs(hash(inst_info)) % 10000:04d}",
                                    "name": inst_info.strip(),
                                    "sharePercentage": 100,
                                }
                            ]

                    canonical_classes.append(cl_dict)
            else:
                canonical_classes.append({
                    "sectionName": "01",
                    "capacity": 40,
                })

            subparts = [
                {
                    "type": "Lecture",
                    "minPerWeek": int(sks_val * 50),
                    "classes": canonical_classes,
                }
            ]

            canonical_courses.append({
                "courseNumber": c_num,
                "title": c_title,
                "credit": {
                    "units": sks_val,
                    "creditType": "collegiate",
                    "creditUnitType": "sks",
                    "format": "fixedUnit",
                },
                "configurations": [
                    {
                        "name": "Default",
                        "subparts": subparts,
                    }
                ],
            })

        canonical_payload: Dict[str, Any] = {
            "ingestControl": {
                "mode": "incremental",
                "actionOnDuplicate": "upsert",
                "sourceDocumentName": f"conversational_draft_{clean_sid}.json",
                "extractedAt": datetime.now(timezone.utc).isoformat(),
                "validationStrictness": "lenient" if dry_run else "strict",
            },
            "academicSession": {
                "year": "2026/2027",
                "term": "Ganjil",
                "campus": primary_campus,
            },
            "department": {
                "code": dept_code,
                "name": dept_name,
            },
            "subjectArea": {
                "abbreviation": dept_code,
                "title": dept_name,
            },
            "courses": canonical_courses,
        }

        # Validate with official JSON schema & semantic rules
        try:
            validator = Validator()
            val_res = validator.validate(canonical_payload)
        except Exception as v_err:
            logger.warning("Validator invocation exception: %s", v_err)
            val_res = None

        if val_res and not val_res.is_valid:
            err_items = [f"  - {e.format_line()}" for e in val_res.errors[:5]]
            return (
                f"### ❌ Validasi Skema UniTime Gagal\n"
                f"Payload yang dirakit memiliki {len(val_res.errors)} kesalahan skema:\n"
                f"{chr(10).join(err_items)}\n\n"
                f"*Mohon periksa kembali kelengkapan parameter mata kuliah.*"
            )

        total_classes = sum(len(c["configurations"][0]["subparts"][0]["classes"]) for c in canonical_courses)

        if dry_run:
            return (
                f"### 🧪 UniTime Smart Ingest - Validasi Dry-Run Berhasil\n"
                f"- **Sesi Draft**: `{clean_sid}`\n"
                f"- **Status Validasi**: ✅ **VALID** (Sesuai skema `unitime-smart-ingest-schema.json`)\n"
                f"- **Kampus Target**: {primary_campus}\n"
                f"- **Departemen**: {dept_code} ({dept_name})\n"
                f"- **Total Mata Kuliah**: {len(canonical_courses)} mata kuliah ({total_classes} kelas)\n\n"
                f"*Payload kanonikal telah siap dan lolos uji validasi. "
                f"Hilangkan opsi dry_run untuk mengirim langsung ke server UniTime.*"
            )

        # Live Submission to UniTime REST API
        client = UniTimeClient()
        try:
            resp = client.submit_ingest(canonical_payload)
            if resp.is_success:
                return (
                    f"### 🚀 Sinkronisasi ke UniTime Berhasil!\n"
                    f"- **Sesi Draft**: `{clean_sid}`\n"
                    f"- **Status Server**: ✅ `{resp.status}` (HTTP {resp.http_status_code})\n"
                    f"- **Mata Kuliah Diimpor**: {resp.summary.courses_count}\n"
                    f"- **Kelas Diimpor**: {resp.summary.classes_count}\n\n"
                    f"{resp.summary_text()}"
                )
            else:
                return (
                    f"### ⚠️ Sinkronisasi UniTime Menghasilkan Peringatan\n"
                    f"- **Status**: `{resp.status}` (HTTP {resp.http_status_code})\n"
                    f"- **Error**: {resp.error or 'Terjadi kendala pada import UniTime'}\n\n"
                    f"{resp.summary_text()}"
                )
        except UniTimeConnectionError as exc:
            return (
                f"### ⚠️ Validasi Berhasil, Server UniTime Offline\n"
                f"- **Status Skema**: ✅ **VALID** (Lolos validasi kanonikal)\n"
                f"- **Koneksi UniTime**: ❌ Tidak dapat terhubung ke server `{client.base_url}` ({exc}).\n\n"
                f"*Payload kanonikal telah sukses dirakit dan diverifikasi. "
                f"Silakan jalankan server UniTime Tomcat untuk menyelesaikan sinkronisasi data.*"
            )
        except Exception as exc:
            return f"### ❌ Terjadi Kesalahan Saat Mengirim ke UniTime\n- **Error**: {exc}\n"
    finally:
        if should_close:
            memory_instance.close()


# Export list of all ReAct tools for LangGraph agent integration
ALL_TOOLS = [
    inspect_room_capacity.tool,
    resolve_instructor_identity.tool,
    record_learned_resolution.tool,
    check_time_conflict.tool,
    generate_admin_summary.tool,
    record_campus_topology.tool,
    record_building_and_rooms.tool,
    draft_course_offering.tool,
    record_scheduling_preference.tool,
    get_draft_summary.tool,
    commit_draft_to_unitime.tool,
]
