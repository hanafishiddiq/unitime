"""
UniTime AI Ingestion Gateway - Curriculum & Personnel Data Model (Milestone M2)
==============================================================================

This module models the academic structure for Indonesian Higher Education (ITB Multi-Campus)
across 4 engineering study programs (IF, SI, EL, TI) and Common First-Year (TPB) courses,
spanning exactly 28 courses, multi-tier subparts, parallel sections, a 32-member faculty
roster with realistic team-teaching shares and SKS workload caps, and distribution constraints.

Author: worker_curriculum_2 (UniTime Teamwork Subagent)
Directory: ai-gateway/test_data_robustness/
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple


_CATALOG_FILE = os.path.join(os.path.dirname(__file__), "curriculum_catalog.json")

# In-memory cache for catalog
_CATALOG_CACHE: Optional[Dict[str, Any]] = None


def load_catalog() -> Dict[str, Any]:
    """Loads and caches the raw curriculum catalog from curriculum_catalog.json."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    if os.path.exists(_CATALOG_FILE):
        with open(_CATALOG_FILE, "r", encoding="utf-8") as f:
            _CATALOG_CACHE = json.load(f)
            return _CATALOG_CACHE
    else:
        raise FileNotFoundError(f"Curriculum catalog file not found at {_CATALOG_FILE}")


def get_catalog_metadata() -> Dict[str, Any]:
    """Returns catalog metadata including academic session, campuses, and ingest control."""
    return load_catalog().get("metadata", {})


def get_departments() -> List[Dict[str, Any]]:
    """Returns the list of department definitions."""
    return load_catalog().get("departments", [])


def get_department(dept_code: str) -> Optional[Dict[str, Any]]:
    """Returns department definition matching dept_code (e.g. 'IF', 'SI', 'EL', 'TI', 'TPB')."""
    for dept in get_departments():
        if dept.get("code") == dept_code:
            return dept
    return None


def get_student_cohorts() -> List[Dict[str, Any]]:
    """Returns student cohort definitions (e.g. IF_2024, TPB_STEI_2024)."""
    return load_catalog().get("studentCohorts", [])


def get_courses(department: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns courses from the curriculum catalog.
    
    :param department: Optional department filter ('IF', 'SI', 'EL', 'TI', 'TPB').
    :return: List of course dictionaries.
    """
    all_courses = load_catalog().get("courses", [])
    if department is None:
        return all_courses
    dept_upper = department.upper()
    return [c for c in all_courses if c.get("departmentCode", "").upper() == dept_upper]


def get_course(course_number: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a course by its courseNumber (e.g. 'IF2110', 'MA1101').
    """
    c_num_upper = course_number.strip().upper()
    for c in get_courses():
        if c.get("courseNumber", "").upper() == c_num_upper:
            return c
    return None


def get_courses_by_department(department_code: str) -> List[Dict[str, Any]]:
    """Convenience alias for get_courses(department=department_code)."""
    return get_courses(department=department_code)


def get_instructors(department: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns faculty members from the roster.
    
    :param department: Optional department filter ('IF', 'SI', 'EL', 'TI', 'TPB').
    :return: List of faculty member dictionaries.
    """
    roster = load_catalog().get("facultyRoster", [])
    if department is None:
        return roster
    dept_upper = department.upper()
    return [f for f in roster if f.get("department", "").upper() == dept_upper]


def get_instructor(instructor_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves an instructor by their unique ID / NIP."""
    inst_clean = instructor_id.strip()
    for inst in get_instructors():
        if inst.get("id") == inst_clean:
            return inst
    return None


def get_distribution_constraints(
    constraint_type: Optional[str] = None,
    course_number: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Returns distribution constraints from the catalog.
    
    :param constraint_type: Optional filter by constraint type (e.g. 'DIFF_TIME', 'SAME_ROOM', 'PRECEDENCE', 'BTB', 'MEET_WITH').
    :param course_number: Optional filter by course number if defined.
    :return: List of distribution constraint dictionaries.
    """
    constraints = load_catalog().get("distributionConstraints", [])
    result = constraints
    if constraint_type:
        c_type_upper = constraint_type.upper()
        # Support aliases
        alias_map = {
            "CANNOT_OVERLAP": "DIFF_TIME",
            "BACK_TO_BACK": "BTB",
            "MEET_TOGETHER": "MEET_WITH",
            "SAME_INSTRUCTOR": "SAME_INSTR",
        }
        canonical_target = alias_map.get(c_type_upper, c_type_upper)
        result = [
            dc for dc in result
            if alias_map.get(dc.get("type", "").upper(), dc.get("type", "").upper()) == canonical_target
        ]

    if course_number:
        c_num_upper = course_number.strip().upper()
        filtered = []
        for dc in result:
            if dc.get("courseNumber", "").upper() == c_num_upper:
                filtered.append(dc)
            else:
                for cl in dc.get("classes", []):
                    if cl.get("courseNumber", "").upper() == c_num_upper:
                        filtered.append(dc)
                        break
        result = filtered

    return result


def get_classes(course_number: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns a flattened list of all class sections across courses and subparts.
    Each item contains section details along with courseNumber and subpartType.
    """
    courses_to_inspect = [get_course(course_number)] if course_number else get_courses()
    flat_classes = []
    for c in courses_to_inspect:
        if not c:
            continue
        c_num = c.get("courseNumber")
        c_title = c.get("title")
        dept = c.get("departmentCode")
        for cfg in c.get("configurations", []):
            cfg_name = cfg.get("name")
            for sp in cfg.get("subparts", []):
                sp_type = sp.get("type")
                min_per_wk = sp.get("minPerWeek")
                parent_sp = sp.get("parentSubpartType")
                for cls_obj in sp.get("classes", []):
                    entry = dict(cls_obj)
                    entry["courseNumber"] = c_num
                    entry["courseTitle"] = c_title
                    entry["departmentCode"] = dept
                    entry["configurationName"] = cfg_name
                    entry["subpartType"] = sp_type
                    entry["minPerWeek"] = min_per_wk
                    entry["parentSubpartType"] = parent_sp
                    flat_classes.append(entry)
    return flat_classes


def get_faculty_workloads() -> Dict[str, Dict[str, Any]]:
    """
    Calculates nominal and weighted SKS teaching workloads per faculty member.
    Weighted SKS is calculated as: sum(course.credit.units * (sharePercentage / 100)).
    Nominal SKS is sum of credit units for distinct courses taught.
    """
    roster = get_instructors()
    workloads: Dict[str, Dict[str, Any]] = {
        inst["id"]: {
            "id": inst["id"],
            "name": inst["name"],
            "title": inst.get("title", ""),
            "department": inst.get("department", ""),
            "weighted_sks": 0.0,
            "distinct_courses": set(),
            "sections": [],
        }
        for inst in roster
    }

    courses = get_courses()
    course_credits = {c["courseNumber"]: float(c.get("credit", {}).get("units", 0.0)) for c in courses}

    for cls_obj in get_classes():
        c_num = cls_obj["courseNumber"]
        sec_name = cls_obj.get("sectionName")
        sp_type = cls_obj.get("subpartType")
        c_units = course_credits.get(c_num, 0.0)

        for ins in cls_obj.get("instructors", []):
            ins_id = ins.get("id")
            if ins_id not in workloads:
                workloads[ins_id] = {
                    "id": ins_id,
                    "name": ins.get("name", "Unknown"),
                    "title": "",
                    "department": "",
                    "weighted_sks": 0.0,
                    "distinct_courses": set(),
                    "sections": [],
                }
            share = float(ins.get("sharePercentage", 100))
            weighted_contribution = c_units * (share / 100.0)
            workloads[ins_id]["weighted_sks"] += weighted_contribution
            workloads[ins_id]["distinct_courses"].add(c_num)
            workloads[ins_id]["sections"].append({
                "courseNumber": c_num,
                "sectionName": sec_name,
                "subpartType": sp_type,
                "isLead": ins.get("isLead", False),
                "sharePercentage": share,
                "contributionSks": round(weighted_contribution, 2)
            })

    # Finalize dict
    for inst_id, d in workloads.items():
        d["weighted_sks"] = round(d["weighted_sks"], 2)
        d["nominal_sks"] = sum(course_credits.get(cn, 0.0) for cn in d["distinct_courses"])
        d["courseCount"] = len(d["distinct_courses"])
        d["distinct_courses"] = sorted(list(d["distinct_courses"]))

    return workloads


def export_canonical_department_payload(
    department_code: str,
    campus: str = "Kampus Ganesha",
    year: str = "2024-2025",
    term: str = "Ganjil",
    include_cross_department: bool = False
) -> Dict[str, Any]:
    """
    Generates a complete canonical JSON payload conforming to unitime-smart-ingest-schema.json
    for a specific study program / department.
    
    :param department_code: Department code ('IF', 'SI', 'EL', 'TI', 'TPB').
    :param campus: Campus name.
    :param year: Academic year string.
    :param term: Term string.
    :param include_cross_department: Whether to include constraints spanning other departments.
    :return: Canonical JSON payload dictionary.
    """
    dept_def = get_department(department_code.upper())
    if not dept_def:
        raise ValueError(f"Unknown department code: {department_code}")

    dept_courses = get_courses_by_department(department_code)
    # Filter course payloads to conform to schema (remove helper departmentCode key)
    cleaned_courses = []
    for c in dept_courses:
        c_copy = dict(c)
        c_copy.pop("departmentCode", None)
        cleaned_courses.append(c_copy)

    # Collect distribution constraints that apply to this department's courses
    dept_course_nums = {c["courseNumber"] for c in dept_courses}
    relevant_constraints = []
    for dc in load_catalog().get("distributionConstraints", []):
        classes = dc.get("classes", [])
        if include_cross_department:
            matches = any(cl.get("courseNumber") in dept_course_nums for cl in classes)
        else:
            matches = all(cl.get("courseNumber") in dept_course_nums for cl in classes)
        if matches:
            relevant_constraints.append(dc)

    payload: Dict[str, Any] = {
        "ingestControl": {
            "mode": "incremental",
            "actionOnDuplicate": "upsert",
            "sourceDocumentName": f"curriculum_catalog_{department_code.lower()}.json",
            "validationStrictness": "strict"
        },
        "academicSession": {
            "year": year,
            "term": term,
            "campus": campus
        },
        "department": {
            "code": dept_def["code"],
            "name": dept_def["name"]
        },
        "subjectArea": {
            "abbreviation": dept_def["subjectArea"]["abbreviation"],
            "title": dept_def["subjectArea"]["title"]
        },
        "courses": cleaned_courses
    }

    if relevant_constraints:
        payload["distributionConstraints"] = relevant_constraints

    return payload


def export_canonical_full_payload(
    campus: str = "Kampus Ganesha",
    year: str = "2024-2025",
    term: str = "Ganjil"
) -> Dict[str, Any]:
    """
    Exports a canonical multi-department payload grouping all 28 courses.
    Primary department is STEI / Informatika.
    """
    all_courses = get_courses()
    cleaned_courses = []
    for c in all_courses:
        c_copy = dict(c)
        c_copy.pop("departmentCode", None)
        cleaned_courses.append(c_copy)

    payload: Dict[str, Any] = {
        "ingestControl": {
            "mode": "incremental",
            "actionOnDuplicate": "upsert",
            "sourceDocumentName": "unitime_smart_ingest_dataset.json",
            "validationStrictness": "strict"
        },
        "academicSession": {
            "year": year,
            "term": term,
            "campus": campus
        },
        "department": {
            "code": "STEI",
            "name": "Sekolah Teknik Elektro dan Informatika"
        },
        "subjectArea": {
            "abbreviation": "STEI",
            "title": "Teknologi Elektro dan Informatika"
        },
        "courses": cleaned_courses,
        "distributionConstraints": load_catalog().get("distributionConstraints", [])
    }
    return payload


def verify_curriculum_integrity() -> Tuple[bool, List[str]]:
    """
    Rigorously verifies the curriculum catalog against all structural, pedagogical,
    mathematical, and relational constraints defined in Milestone M2.
    
    Returns:
        (passed: bool, diagnostics: List[str])
    """
    diagnostics: List[str] = []
    catalog = load_catalog()
    courses = catalog.get("courses", [])
    faculty_roster = catalog.get("facultyRoster", [])
    distribution_constraints = catalog.get("distributionConstraints", [])

    # 1. Course counts
    total_courses = len(courses)
    if total_courses != 28:
        diagnostics.append(f"Course count mismatch: expected exactly 28, found {total_courses}")

    dept_counts: Dict[str, int] = {}
    for c in courses:
        dept = c.get("departmentCode", "UNKNOWN")
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    expected_counts = {"TPB": 4, "IF": 6, "SI": 6, "EL": 6, "TI": 6}
    for dept, exp in expected_counts.items():
        actual = dept_counts.get(dept, 0)
        if actual != exp:
            diagnostics.append(f"Department '{dept}' count mismatch: expected {exp}, found {actual}")

    # 2. Credit units & subparts
    existing_classes: Set[Tuple[str, str]] = set()
    all_sections_by_course: Dict[str, Set[str]] = {}
    lead_per_class: Dict[Tuple[str, str], int] = {}
    team_teaching_categories: Set[str] = set()

    for c_idx, c in enumerate(courses):
        c_num = c.get("courseNumber", "")
        if not c_num:
            diagnostics.append(f"Course at index {c_idx} missing courseNumber")
            continue
        all_sections_by_course[c_num] = set()

        credit = c.get("credit", {})
        units = credit.get("units")
        if units is None or not (1.0 <= units <= 10.0):
            diagnostics.append(f"Course '{c_num}' has invalid credit units: {units}")

        for cfg in c.get("configurations", []):
            subparts = cfg.get("subparts", [])
            subpart_types = [sp.get("type") for sp in subparts]

            for sp in subparts:
                sp_type = sp.get("type")
                min_per_wk = sp.get("minPerWeek", 0)
                parent_sp = sp.get("parentSubpartType")

                # Validate contact minutes
                if sp_type == "Lecture":
                    if min_per_wk not in [50, 100, 150, 200]:
                        diagnostics.append(f"Course '{c_num}' Lecture minPerWeek={min_per_wk} does not align with 50 min/SKS rule")
                elif sp_type == "Lab":
                    if not (100 <= min_per_wk <= 170):
                        diagnostics.append(f"Course '{c_num}' Lab minPerWeek={min_per_wk} out of standard 100-170 min range")
                    if parent_sp != "Lecture":
                        diagnostics.append(f"Course '{c_num}' Lab child subpart must have parentSubpartType='Lecture', got '{parent_sp}'")
                elif sp_type in ["Responsi", "Tutorial"]:
                    if not (50 <= min_per_wk <= 100):
                        diagnostics.append(f"Course '{c_num}' {sp_type} minPerWeek={min_per_wk} out of standard 50-100 min range")
                    if parent_sp != "Lecture":
                        diagnostics.append(f"Course '{c_num}' {sp_type} must have parentSubpartType='Lecture', got '{parent_sp}'")

                for cls_obj in sp.get("classes", []):
                    sec_name = cls_obj.get("sectionName")
                    if not sec_name:
                        diagnostics.append(f"Course '{c_num}' has class with missing sectionName")
                        continue
                    existing_classes.add((c_num, sec_name))
                    all_sections_by_course[c_num].add(sec_name)

                    # Check parentClassSection binding
                    parent_sec = cls_obj.get("parentClassSection")
                    if parent_sp is not None and not parent_sec:
                        diagnostics.append(f"Course '{c_num}' child class '{sec_name}' missing parentClassSection")

                    # Capacity
                    cap = cls_obj.get("capacity", 0)
                    if cap < 1:
                        diagnostics.append(f"Course '{c_num}' section '{sec_name}' invalid capacity: {cap}")

                    # Time preference checks
                    for tp in cls_obj.get("timePreferences", []):
                        st = tp.get("startTime", "")
                        et = tp.get("endTime", "")
                        if st >= et:
                            diagnostics.append(f"Course '{c_num}' section '{sec_name}' invalid time window: {st} >= {et}")

                    # Instructors & shares
                    instructors = cls_obj.get("instructors", [])
                    if instructors:
                        lead_count = sum(1 for ins in instructors if ins.get("isLead", False))
                        if lead_count != 1:
                            diagnostics.append(f"Course '{c_num}' section '{sec_name}' must have exactly 1 lead instructor, found {lead_count}")

                        shares = [ins.get("sharePercentage") for ins in instructors if "sharePercentage" in ins]
                        total_share = sum(shares)
                        if total_share != 100:
                            diagnostics.append(f"Course '{c_num}' section '{sec_name}' instructor shares sum to {total_share}%, expected 100%")

                        # Categorize team teaching pattern
                        sorted_shares = tuple(sorted(shares, reverse=True))
                        if sorted_shares == (50, 50):
                            team_teaching_categories.add("50:50")
                        elif sorted_shares == (70, 30):
                            team_teaching_categories.add("70:30")
                        elif sorted_shares == (34, 33, 33):
                            team_teaching_categories.add("34:33:33")
                        elif sorted_shares == (100,):
                            team_teaching_categories.add("100")

    # Verify parentClassSection resolves to an actual section in the parent subpart
    for c in courses:
        c_num = c.get("courseNumber")
        for cfg in c.get("configurations", []):
            for sp in cfg.get("subparts", []):
                for cls_obj in sp.get("classes", []):
                    parent_sec = cls_obj.get("parentClassSection")
                    if parent_sec:
                        if parent_sec not in all_sections_by_course.get(c_num, set()):
                            diagnostics.append(f"Course '{c_num}' section '{cls_obj.get('sectionName')}' references unknown parentClassSection '{parent_sec}'")

    # 3. Faculty roster verification
    if len(faculty_roster) < 25:
        diagnostics.append(f"Faculty roster has {len(faculty_roster)} members, expected >= 25")

    roster_ids = {f["id"]: f for f in faculty_roster}
    # Check that some instructors have missing email and some have surrogate IDs
    missing_emails = [f["id"] for f in faculty_roster if f.get("email") is None]
    surrogate_ids = [f["id"] for f in faculty_roster if f["id"].startswith("DOSEN_")]
    if not missing_emails:
        diagnostics.append("Missing optional metadata check failed: expected at least one instructor with missing email")
    if not surrogate_ids:
        diagnostics.append("Missing institutional ID check failed: expected at least one instructor with surrogate DOSEN_ ID")

    # Check that all instructors assigned to classes exist in roster
    for c in courses:
        c_num = c.get("courseNumber")
        for cfg in c.get("configurations", []):
            for sp in cfg.get("subparts", []):
                for cls_obj in sp.get("classes", []):
                    for ins in cls_obj.get("instructors", []):
                        ins_id = ins.get("id")
                        if ins_id not in roster_ids:
                            diagnostics.append(f"Course '{c_num}' section '{cls_obj.get('sectionName')}' references unknown instructor ID '{ins_id}'")

    # 4. Team-teaching categories check
    required_team_patterns = {"50:50", "70:30", "34:33:33", "100"}
    missing_patterns = required_team_patterns - team_teaching_categories
    if missing_patterns:
        diagnostics.append(f"Missing required team-teaching share patterns: {missing_patterns}")

    # 5. Workload caps (12-16 SKS)
    workloads = get_faculty_workloads()
    for inst_id, wl in workloads.items():
        w_sks = wl["weighted_sks"]
        if w_sks > 16.0:
            diagnostics.append(f"Instructor '{wl['name']}' ({inst_id}) exceeds SKS workload cap: {w_sks} > 16.0 SKS")

    # 6. Distribution constraints verification
    dc_types_present: Set[str] = set()
    for idx, dc in enumerate(distribution_constraints):
        dc_type = dc.get("type", "")
        dc_types_present.add(dc_type)
        dc_classes = dc.get("classes", [])
        if len(dc_classes) < 2:
            diagnostics.append(f"Distribution constraint at index {idx} has fewer than 2 target classes")

        for cl_idx, cl_ref in enumerate(dc_classes):
            rc_num = cl_ref.get("courseNumber")
            r_sec = cl_ref.get("sectionName")
            if (rc_num, r_sec) not in existing_classes:
                diagnostics.append(f"Distribution constraint [{idx}] ({dc_type}) references unknown class: '{rc_num} {r_sec}'")

        # Directed constraint PRECEDENCE check
        if dc_type == "PRECEDENCE":
            if len(dc_classes) >= 2:
                first = dc_classes[0]
                second = dc_classes[1]
                if first.get("subpartType") != "Lecture" or second.get("subpartType") not in ["Lab", "Responsi"]:
                    diagnostics.append(f"PRECEDENCE constraint [{idx}] should have Lecture preceding Lab/Responsi, found {first.get('subpartType')} -> {second.get('subpartType')}")

    required_dc_types = {"DIFF_TIME", "SAME_ROOM", "PRECEDENCE", "MEET_WITH"}
    # Check BTB or BACK_TO_BACK
    has_btb = "BTB" in dc_types_present or "BACK_TO_BACK" in dc_types_present
    if not has_btb:
        diagnostics.append("Missing required BTB / BACK_TO_BACK distribution constraint")
    missing_dc = required_dc_types - dc_types_present
    if missing_dc:
        diagnostics.append(f"Missing required distribution constraint types: {missing_dc}")

    # 7. Spatial room reference verification
    allowed_rooms = {
        ("Labtek V Benny Subianto", "7601"),
        ("Labtek V Benny Subianto", "7602"),
        ("Labtek V Benny Subianto", "7603"),
        ("Labtek V Benny Subianto", "Lab-1"),
        ("Labtek VIII Achmad Bakrie", "8201"),
        ("Labtek VIII Achmad Bakrie", "8202"),
        ("Labtek VIII Achmad Bakrie", "Lab-El"),
        ("Labtek III Matthias Aroef", "3101"),
        ("Labtek III Matthias Aroef", "3102"),
        ("GKU Barat (GK-1)", "9001"),
        ("GKU Barat (GK-1)", "9002"),
        ("GKU Barat (GK-1)", "9101"),
        ("GKU Barat (GK-1)", "9102"),
        ("GKU 1 Jatinangor", "101"),
        ("Gedung KOICA", "201"),
        ("Lab Terpadu Jatinangor", "Lab-01"),
        ("Lab Terpadu Jatinangor", "Lab-02"),
        ("Lab Terpadu Jatinangor", "102"),
        ("GKU 2 Jatinangor", "201"),
        ("GKU 2 Jatinangor", "202"),
    }
    for c in courses:
        for cfg in c.get("configurations", []):
            for sp in cfg.get("subparts", []):
                for cls_obj in sp.get("classes", []):
                    for rp in cls_obj.get("roomPreferences", []):
                        bld = rp.get("building")
                        rm = rp.get("roomNumber")
                        if bld and rm and (bld, rm) not in allowed_rooms:
                            diagnostics.append(f"Course '{c.get('courseNumber')}' section '{cls_obj.get('sectionName')}' references unknown room: {bld} {rm}")

    passed = (len(diagnostics) == 0)
    return passed, diagnostics


# ==============================================================================
# PYTEST UNIT TESTS
# ==============================================================================


def test_total_course_counts():
    """Verify total courses count is exactly 28."""
    courses = get_courses()
    assert len(courses) == 28, f"Expected 28 courses, got {len(courses)}"


def test_department_course_distribution():
    """Verify exact breakdown: 4 TPB + 6 IF + 6 SI + 6 EL + 6 TI."""
    expected = {"TPB": 4, "IF": 6, "SI": 6, "EL": 6, "TI": 6}
    for dept, exp_count in expected.items():
        courses = get_courses_by_department(dept)
        assert len(courses) == exp_count, f"Expected {exp_count} courses for {dept}, got {len(courses)}"


def test_contact_minutes_and_sks():
    """Verify SKS contact minutes rules across subparts."""
    for c in get_courses():
        for cfg in c.get("configurations", []):
            for sp in cfg.get("subparts", []):
                sp_type = sp.get("type")
                min_pw = sp.get("minPerWeek", 0)
                if sp_type == "Lecture":
                    assert min_pw in [50, 100, 150, 200]
                elif sp_type == "Lab":
                    assert 100 <= min_pw <= 170
                    assert sp.get("parentSubpartType") == "Lecture"
                elif sp_type in ["Responsi", "Tutorial"]:
                    assert 50 <= min_pw <= 100
                    assert sp.get("parentSubpartType") == "Lecture"


def test_parallel_classes_and_parent_child_hierarchy():
    """Verify K01, K02 parallel sections and parent-child links."""
    for c in get_courses():
        classes = get_classes(c["courseNumber"])
        sec_names = {cl["sectionName"] for cl in classes}
        assert "K01" in sec_names and "K02" in sec_names
        for cl in classes:
            parent_sec = cl.get("parentClassSection")
            if cl.get("subpartType") != "Lecture":
                assert parent_sec in ["K01", "K02"], f"Child section {cl['sectionName']} has invalid parent {parent_sec}"


def test_faculty_roster_and_metadata():
    """Verify faculty roster size >= 25 and realistic missing optional metadata."""
    roster = get_instructors()
    assert len(roster) >= 25, f"Expected >= 25 faculty members, got {len(roster)}"
    missing_emails = [f for f in roster if f.get("email") is None]
    surrogate_ids = [f for f in roster if f["id"].startswith("DOSEN_")]
    assert len(missing_emails) >= 1, "Expected at least one instructor with missing email"
    assert len(surrogate_ids) >= 1, "Expected at least one instructor with surrogate ID"


def test_instructor_shares_sum_strictly_to_100():
    """Verify all class sections with instructors have shares summing strictly to 100% and 1 lead."""
    team_patterns = set()
    for cl in get_classes():
        instructors = cl.get("instructors", [])
        if instructors:
            leads = [ins for ins in instructors if ins.get("isLead")]
            assert len(leads) == 1, f"Class {cl['courseNumber']} {cl['sectionName']} has {len(leads)} leads"
            shares = [ins["sharePercentage"] for ins in instructors]
            assert sum(shares) == 100, f"Shares sum to {sum(shares)} in {cl['courseNumber']} {cl['sectionName']}"
            sorted_shares = tuple(sorted(shares, reverse=True))
            if sorted_shares in [(50, 50), (70, 30), (34, 33, 33), (100,)]:
                team_patterns.add(sorted_shares)

    assert (50, 50) in team_patterns
    assert (70, 30) in team_patterns
    assert (34, 33, 33) in team_patterns
    assert (100,) in team_patterns


def test_faculty_workload_caps():
    """Verify no faculty member exceeds 16.0 SKS weighted workload cap."""
    workloads = get_faculty_workloads()
    for inst_id, wl in workloads.items():
        assert wl["weighted_sks"] <= 16.0, f"Instructor {wl['name']} exceeded workload cap: {wl['weighted_sks']} SKS"


def test_distribution_constraints_comprehensive():
    """Verify presence of all 5 distribution constraint types and zero orphaned references."""
    constraints = get_distribution_constraints()
    types_found = {dc["type"] for dc in constraints}
    assert "DIFF_TIME" in types_found
    assert "SAME_ROOM" in types_found
    assert "BTB" in types_found or "BACK_TO_BACK" in types_found
    assert "PRECEDENCE" in types_found
    assert "MEET_WITH" in types_found or "MEET_TOGETHER" in types_found

    all_classes = {(cl["courseNumber"], cl["sectionName"]) for cl in get_classes()}
    for dc in constraints:
        for cl_ref in dc.get("classes", []):
            assert (cl_ref["courseNumber"], cl_ref["sectionName"]) in all_classes


def test_spatial_room_references():
    """Verify all room preferences reference valid rooms from the 20-room spatial catalog."""
    allowed_rooms = {
        ("Labtek V Benny Subianto", "7601"),
        ("Labtek V Benny Subianto", "7602"),
        ("Labtek V Benny Subianto", "7603"),
        ("Labtek V Benny Subianto", "Lab-1"),
        ("Labtek VIII Achmad Bakrie", "8201"),
        ("Labtek VIII Achmad Bakrie", "8202"),
        ("Labtek VIII Achmad Bakrie", "Lab-El"),
        ("Labtek III Matthias Aroef", "3101"),
        ("Labtek III Matthias Aroef", "3102"),
        ("GKU Barat (GK-1)", "9001"),
        ("GKU Barat (GK-1)", "9002"),
        ("GKU Barat (GK-1)", "9101"),
        ("GKU Barat (GK-1)", "9102"),
        ("GKU 1 Jatinangor", "101"),
        ("Gedung KOICA", "201"),
        ("Lab Terpadu Jatinangor", "Lab-01"),
        ("Lab Terpadu Jatinangor", "Lab-02"),
        ("Lab Terpadu Jatinangor", "102"),
        ("GKU 2 Jatinangor", "201"),
        ("GKU 2 Jatinangor", "202"),
    }
    for cl in get_classes():
        for rp in cl.get("roomPreferences", []):
            bld = rp.get("building")
            rm = rp.get("roomNumber")
            if bld and rm:
                assert (bld, rm) in allowed_rooms, f"Unknown room reference: {bld} {rm}"


def test_time_preferences_validity():
    """Verify all time preferences have startTime < endTime and valid 24h format."""
    time_regex = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
    for cl in get_classes():
        for tp in cl.get("timePreferences", []):
            st = tp.get("startTime", "")
            et = tp.get("endTime", "")
            assert time_regex.match(st), f"Invalid startTime: {st}"
            assert time_regex.match(et), f"Invalid endTime: {et}"
            assert st < et, f"startTime '{st}' must be earlier than endTime '{et}'"


def test_canonical_payload_schema_and_semantic_validation():
    """Verify all canonical payloads pass schema and semantic validation with zero errors."""
    try:
        from core.validator import Validator
    except ImportError:
        # Fallback to local import if ai-gateway is in parent path
        ai_gw_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if ai_gw_dir not in sys.path:
            sys.path.insert(0, ai_gw_dir)
        from core.validator import Validator

    v = Validator()
    for dept in ["IF", "SI", "EL", "TI", "TPB"]:
        p = export_canonical_department_payload(dept)
        res = v.validate(p)
        assert res.is_valid, f"Department {dept} failed validation: {res.error_messages}"
        assert len(res.errors) == 0, f"Department {dept} has errors: {res.error_messages}"
        assert len(res.warnings) == 0, f"Department {dept} has warnings: {res.warnings}"

    full_p = export_canonical_full_payload()
    res_full = v.validate(full_p)
    assert res_full.is_valid, f"Full payload failed validation: {res_full.error_messages}"
    assert len(res_full.errors) == 0, f"Full payload has errors: {res_full.error_messages}"
    assert len(res_full.warnings) == 0, f"Full payload has warnings: {res_full.warnings}"


if __name__ == "__main__":
    print("================================================================================")
    print("           UNITIME AI INGESTION GATEWAY - CURRICULUM MODEL VALIDATOR            ")
    print("================================================================================")
    
    passed, diagnostics = verify_curriculum_integrity()
    courses = get_courses()
    instructors = get_instructors()
    constraints = get_distribution_constraints()
    workloads = get_faculty_workloads()

    print(f"\n[+] Total Courses Loaded: {len(courses)}")
    print(f"    - TPB: {len(get_courses_by_department('TPB'))}")
    print(f"    - IF:  {len(get_courses_by_department('IF'))}")
    print(f"    - SI:  {len(get_courses_by_department('SI'))}")
    print(f"    - EL:  {len(get_courses_by_department('EL'))}")
    print(f"    - TI:  {len(get_courses_by_department('TI'))}")

    print(f"\n[+] Total Faculty Roster: {len(instructors)} lecturers")
    print(f"[+] Total Distribution Constraints: {len(constraints)}")
    
    print("\n[+] Top Faculty Teaching Loads (Max 16.0 SKS):")
    sorted_workloads = sorted(workloads.values(), key=lambda x: x["weighted_sks"], reverse=True)
    for wl in sorted_workloads[:8]:
        print(f"    * {wl['name']:<45} | Weighted: {wl['weighted_sks']:>4.1f} SKS | Courses: {', '.join(wl['distinct_courses'])}")

    print("\n[+] Integrity Verification Result:")
    if passed:
        print("    >>> 100% CURRICULUM INTEGRITY VERIFIED (0 ERRORS, 0 WARNINGS) <<<")
    else:
        print(f"    >>> INTEGRITY CHECK FAILED WITH {len(diagnostics)} ISSUES <<<")
        for diag in diagnostics:
            print(f"    - [!] {diag}")
        sys.exit(1)
