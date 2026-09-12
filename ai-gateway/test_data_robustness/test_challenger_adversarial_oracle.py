"""
test_challenger_adversarial_oracle.py
======================================
Independent Adversarial Test Suite & Oracle Verifier
Author: challenger_2 (Empirical Challenger Agent)

This module provides an independent oracle and verification harness that does
NOT rely on self-reported annotations or worker claims. It evaluates raw data
from first principles to:
1. Empirically detect and quantify all human scheduling flaws in pre_unitime_legacy_schedule.json.
2. Empirically verify 100% resolution of all flaws in postUnitimeOptimizedTimetable.
3. Verify the mathematical correctness of all metrics published in benchmark_comparison_report.md.
4. Execute adversarial stress boundary checks (referential integrity, cohort overlaps, faculty transit, invariants).
"""

import json
from pathlib import Path
from collections import defaultdict
import pytest

DATA_DIR = Path(__file__).resolve().parent
LEGACY_FILE = DATA_DIR / "pre_unitime_legacy_schedule.json"
CURRICULUM_FILE = DATA_DIR / "curriculum_catalog.json"
CAMPUS_FILE = DATA_DIR / "campus_topology.json"
REPORT_FILE = DATA_DIR / "benchmark_comparison_report.md"


@pytest.fixture(scope="module")
def dataset():
    assert LEGACY_FILE.exists(), f"File missing: {LEGACY_FILE}"
    with open(LEGACY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def curriculum():
    assert CURRICULUM_FILE.exists(), f"File missing: {CURRICULUM_FILE}"
    with open(CURRICULUM_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="module")
def campus_topology():
    assert CAMPUS_FILE.exists(), f"File missing: {CAMPUS_FILE}"
    with open(CAMPUS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def time_to_minutes(time_str: str) -> int:
    h, m = map(int, time_str.split(":"))
    return h * 60 + m


# ==============================================================================
# 1. ORACLE VERIFIER: DETECTING LEGACY FLAWS FROM RAW DATA
# ==============================================================================

class TimetableOracle:
    """Independent oracle for detecting timetable anomalies from raw schedule data."""

    @staticmethod
    def detect_instructor_double_bookings(timetable):
        instr_classes = defaultdict(lambda: defaultdict(list))
        for c in timetable:
            for instr in c.get("instructors", []):
                instr_classes[instr["id"]][c["day"]].append(c)

        overlaps = []
        for iid, days in instr_classes.items():
            for day, clist in days.items():
                for i in range(len(clist)):
                    for j in range(i + 1, len(clist)):
                        cA, cB = clist[i], clist[j]
                        sA, eA = time_to_minutes(cA["startTime"]), time_to_minutes(cA["endTime"])
                        sB, eB = time_to_minutes(cB["startTime"]), time_to_minutes(cB["endTime"])
                        ov = max(0, min(eA, eB) - max(sA, sB))
                        if ov > 0:
                            overlaps.append({
                                "instructorId": iid,
                                "day": day,
                                "classA": cA["classId"],
                                "classB": cB["classId"],
                                "overlapMinutes": ov
                            })
        return overlaps

    @staticmethod
    def detect_room_double_bookings(timetable):
        room_classes = defaultdict(lambda: defaultdict(list))
        for c in timetable:
            rid = c.get("roomExternalId") or f"{c['buildingAbbreviation']}_{c['roomNumber']}"
            room_classes[rid][c["day"]].append(c)

        overlaps = []
        for rid, days in room_classes.items():
            for day, clist in days.items():
                for i in range(len(clist)):
                    for j in range(i + 1, len(clist)):
                        cA, cB = clist[i], clist[j]
                        sA, eA = time_to_minutes(cA["startTime"]), time_to_minutes(cA["endTime"])
                        sB, eB = time_to_minutes(cB["startTime"]), time_to_minutes(cB["endTime"])
                        ov = max(0, min(eA, eB) - max(sA, sB))
                        if ov > 0:
                            overlaps.append({
                                "room": rid,
                                "day": day,
                                "classA": cA["classId"],
                                "classB": cB["classId"],
                                "overlapMinutes": ov
                            })
        return overlaps

    @staticmethod
    def detect_precedence_violations(timetable, precedence_constraints):
        tb_map = {c["classId"]: c for c in timetable}
        inverted = []
        valid = []
        for pc in precedence_constraints:
            c0 = f"{pc['classes'][0]['courseNumber']}_{pc['classes'][0]['sectionName']}"
            c1 = f"{pc['classes'][1]['courseNumber']}_{pc['classes'][1]['sectionName']}"
            if c0 in tb_map and c1 in tb_map:
                t0 = tb_map[c0]
                t1 = tb_map[c1]
                time0 = t0["dayOfWeek"] * 24 * 60 + time_to_minutes(t0["startTime"])
                time1 = t1["dayOfWeek"] * 24 * 60 + time_to_minutes(t1["startTime"])
                if time1 < time0:
                    inverted.append({
                        "course": pc["classes"][0]["courseNumber"],
                        "theoryClass": c0,
                        "labClass": c1,
                        "inversionHours": (time0 - time1) / 60.0
                    })
                else:
                    valid.append({
                        "course": pc["classes"][0]["courseNumber"],
                        "theoryClass": c0,
                        "labClass": c1,
                        "precedenceGapHours": (time1 - time0) / 60.0
                    })
        return inverted, valid

    @staticmethod
    def detect_cross_campus_travel_violations(timetable, min_required_buffer=60):
        cohort_classes = defaultdict(lambda: defaultdict(list))
        for c in timetable:
            cohort_classes[c["cohort"]][c["day"]].append(c)

        violations = []
        transfers = []
        for coh, days in cohort_classes.items():
            for day, clist in days.items():
                clist_sorted = sorted(clist, key=lambda x: time_to_minutes(x["startTime"]))
                for i in range(len(clist_sorted) - 1):
                    cA, cB = clist_sorted[i], clist_sorted[i + 1]
                    if cA["campus"] != cB["campus"]:
                        eA = time_to_minutes(cA["endTime"])
                        sB = time_to_minutes(cB["startTime"])
                        buf = sB - eA
                        info = {
                            "cohort": coh,
                            "day": day,
                            "originClass": cA["classId"],
                            "originCampus": cA["campus"],
                            "destClass": cB["classId"],
                            "destCampus": cB["campus"],
                            "bufferMinutes": buf
                        }
                        transfers.append(info)
                        if buf < min_required_buffer:
                            info["deficitMinutes"] = min_required_buffer - buf
                            violations.append(info)
        return violations, transfers

    @staticmethod
    def detect_utilization_anomalies(timetable):
        overcrowded = []
        underutilized = []
        for c in timetable:
            enr = c["enrolledStudents"]
            cap = c["roomCapacity"]
            pct = (enr / cap * 100.0) if cap > 0 else 0.0
            if enr > cap:
                overcrowded.append({
                    "classId": c["classId"],
                    "enrolled": enr,
                    "capacity": cap,
                    "occupancyPercent": pct
                })
            if pct <= 15.0:
                underutilized.append({
                    "classId": c["classId"],
                    "enrolled": enr,
                    "capacity": cap,
                    "occupancyPercent": pct
                })
        return overcrowded, underutilized

    @staticmethod
    def detect_idle_gaps(timetable, dead_time_threshold=120):
        cohort_classes = defaultdict(lambda: defaultdict(list))
        for c in timetable:
            cohort_classes[c["cohort"]][c["day"]].append(c)

        all_gaps = []
        gaps_over_threshold = []
        for coh, days in cohort_classes.items():
            for day, clist in days.items():
                clist_sorted = sorted(clist, key=lambda x: time_to_minutes(x["startTime"]))
                for i in range(len(clist_sorted) - 1):
                    cA, cB = clist_sorted[i], clist_sorted[i + 1]
                    eA = time_to_minutes(cA["endTime"])
                    sB = time_to_minutes(cB["startTime"])
                    gap = sB - eA
                    if gap > 0:
                        gap_info = {
                            "cohort": coh,
                            "day": day,
                            "classA": cA["classId"],
                            "classB": cB["classId"],
                            "gapMinutes": gap
                        }
                        all_gaps.append(gap_info)
                        if gap >= dead_time_threshold:
                            gaps_over_threshold.append(gap_info)

        peak_gap = max(all_gaps, key=lambda x: x["gapMinutes"]) if all_gaps else None
        return all_gaps, gaps_over_threshold, peak_gap


# ==============================================================================
# TEST 1: EMPIRICAL FLAW DETECTION IN PRE-UNITIME LEGACY SCHEDULE
# ==============================================================================

def test_oracle_detects_legacy_instructor_double_booking(dataset):
    """Oracle verifies exactly 1 instructor collision in legacy schedule."""
    legacy = dataset["timetable"]
    overlaps = TimetableOracle.detect_instructor_double_bookings(legacy)
    assert len(overlaps) == 1, f"Expected exactly 1 instructor overlap, found {len(overlaps)}"
    clash = overlaps[0]
    assert clash["instructorId"] == "197210151998021001"
    assert clash["day"] == "Monday"
    assert set([clash["classA"], clash["classB"]]) == {"IF2130_K02", "IF3110_K01"}
    assert clash["overlapMinutes"] == 100


def test_oracle_detects_legacy_room_double_booking(dataset):
    """Oracle verifies exactly 1 room collision in legacy schedule."""
    legacy = dataset["timetable"]
    overlaps = TimetableOracle.detect_room_double_bookings(legacy)
    assert len(overlaps) == 1, f"Expected exactly 1 room overlap, found {len(overlaps)}"
    clash = overlaps[0]
    assert clash["room"] == "RM_LTV_7601"
    assert clash["day"] == "Wednesday"
    assert set([clash["classA"], clash["classB"]]) == {"IF2130_K01", "TI2101_K02"}
    assert clash["overlapMinutes"] == 100


def test_oracle_detects_legacy_inverted_precedence(dataset, curriculum):
    """Oracle verifies exactly 1 inverted precedence in legacy schedule."""
    legacy = dataset["timetable"]
    prec_constraints = [c for c in curriculum.get("distributionConstraints", []) if c.get("type") == "PRECEDENCE"]
    inverted, valid = TimetableOracle.detect_precedence_violations(legacy, prec_constraints)
    assert len(inverted) == 1, f"Expected exactly 1 inverted precedence, found {len(inverted)}"
    assert len(valid) == 4, f"Expected 4 valid precedences, found {len(valid)}"
    inv = inverted[0]
    assert inv["course"] == "IF2110"
    assert inv["theoryClass"] == "IF2110_K01"
    assert inv["labClass"] == "IF2110_L01"
    assert inv["inversionHours"] == 67.0


def test_oracle_detects_legacy_impossible_campus_travel(dataset):
    """Oracle verifies exactly 1 impossible travel transition (<60 min) in legacy schedule."""
    legacy = dataset["timetable"]
    violations, transfers = TimetableOracle.detect_cross_campus_travel_violations(legacy, min_required_buffer=60)
    assert len(transfers) == 2, f"Expected 2 total campus transfers, found {len(transfers)}"
    assert len(violations) == 1, f"Expected 1 travel violation, found {len(violations)}"
    v = violations[0]
    assert v["cohort"] == "SI_2024"
    assert v["day"] == "Thursday"
    assert v["originClass"] == "SI2103_K01"
    assert v["destClass"] == "SI2102_L01"
    assert v["bufferMinutes"] == 10
    assert v["deficitMinutes"] == 50


def test_oracle_detects_legacy_utilization_anomalies(dataset):
    """Oracle verifies 2 overcrowded and 1 severely under-utilized sections in legacy schedule."""
    legacy = dataset["timetable"]
    overcrowded, underutilized = TimetableOracle.detect_utilization_anomalies(legacy)
    assert len(overcrowded) == 2, f"Expected 2 overcrowded sections, found {len(overcrowded)}"
    oc_classes = {o["classId"] for o in overcrowded}
    assert oc_classes == {"TI2101_K01", "TI2101_K02"}
    ti1 = next(o for o in overcrowded if o["classId"] == "TI2101_K01")
    assert ti1["enrolled"] == 55 and ti1["capacity"] == 40
    assert pytest.approx(ti1["occupancyPercent"], 0.01) == 137.5

    assert len(underutilized) == 1, f"Expected 1 severely under-utilized section, found {len(underutilized)}"
    u = underutilized[0]
    assert u["classId"] == "IF2130_L01"
    assert u["enrolled"] == 20 and u["capacity"] == 200
    assert pytest.approx(u["occupancyPercent"], 0.01) == 10.0


def test_oracle_detects_legacy_student_dead_time_gap(dataset):
    """Oracle verifies 240-minute peak dead-time gap in legacy schedule."""
    legacy = dataset["timetable"]
    all_gaps, gaps_over_120, peak_gap = TimetableOracle.detect_idle_gaps(legacy, dead_time_threshold=120)
    assert peak_gap is not None
    assert peak_gap["cohort"] == "TI_2024"
    assert peak_gap["day"] == "Tuesday"
    assert peak_gap["gapMinutes"] == 240
    assert peak_gap["classA"] == "TI2102_K01"
    assert peak_gap["classB"] == "TI2101_R01"
    # Gaps >= 240 min
    gaps_240 = [g for g in all_gaps if g["gapMinutes"] >= 240]
    assert len(gaps_240) == 1


# ==============================================================================
# TEST 2: EMPIRICAL VERIFICATION OF 100% FLAW RESOLUTION IN POST-UNITIME
# ==============================================================================

def test_post_unitime_resolves_all_instructor_conflicts(dataset):
    """Empirically verify 0 instructor double bookings in Post-UniTime."""
    post = dataset["postUnitimeOptimizedTimetable"]
    overlaps = TimetableOracle.detect_instructor_double_bookings(post)
    assert len(overlaps) == 0, f"Expected 0 instructor overlaps in Post-UniTime, found {len(overlaps)}"


def test_post_unitime_resolves_all_room_conflicts(dataset):
    """Empirically verify 0 room double bookings in Post-UniTime."""
    post = dataset["postUnitimeOptimizedTimetable"]
    overlaps = TimetableOracle.detect_room_double_bookings(post)
    assert len(overlaps) == 0, f"Expected 0 room overlaps in Post-UniTime, found {len(overlaps)}"


def test_post_unitime_resolves_inverted_precedence(dataset, curriculum):
    """Empirically verify 100% valid precedence constraints in Post-UniTime."""
    post = dataset["postUnitimeOptimizedTimetable"]
    prec_constraints = [c for c in curriculum.get("distributionConstraints", []) if c.get("type") == "PRECEDENCE"]
    inverted, valid = TimetableOracle.detect_precedence_violations(post, prec_constraints)
    assert len(inverted) == 0, f"Expected 0 inverted precedences in Post-UniTime, found {len(inverted)}"
    assert len(valid) == 5, f"Expected all 5 precedences valid, found {len(valid)}"

    # Check IF2110 specifically
    if2110 = next(v for v in valid if v["course"] == "IF2110")
    assert if2110["precedenceGapHours"] == 79.5


def test_post_unitime_resolves_cross_campus_travel(dataset):
    """Empirically verify 0 cross-campus travel violations in Post-UniTime."""
    post = dataset["postUnitimeOptimizedTimetable"]
    violations, transfers = TimetableOracle.detect_cross_campus_travel_violations(post, min_required_buffer=60)
    assert len(violations) == 0, f"Expected 0 travel violations, found {len(violations)}"
    assert len(transfers) == 2, f"Expected 2 transfers, found {len(transfers)}"
    # All transfers have at least 110 min buffer
    for t in transfers:
        assert t["bufferMinutes"] >= 110, f"Transfer {t} has insufficient buffer"


def test_post_unitime_resolves_room_misallocations(dataset):
    """Empirically verify 0 overcrowded and 0 severely under-utilized sections in Post-UniTime."""
    post = dataset["postUnitimeOptimizedTimetable"]
    overcrowded, underutilized = TimetableOracle.detect_utilization_anomalies(post)
    assert len(overcrowded) == 0, f"Expected 0 overcrowded sections in Post-UniTime, found {len(overcrowded)}"
    assert len(underutilized) == 0, f"Expected 0 under-utilized sections in Post-UniTime, found {len(underutilized)}"


def test_post_unitime_compresses_peak_dead_time_gap(dataset):
    """Empirically verify that the 240-minute flaw for TI_2024 is compressed to 20 minutes."""
    post = dataset["postUnitimeOptimizedTimetable"]
    post_map = {c["classId"]: c for c in post}
    c_a = post_map["TI2102_K01"]
    c_b = post_map["TI2101_R01"]
    assert c_a["day"] == "Tuesday" and c_b["day"] == "Tuesday"
    assert c_a["endTime"] == "08:40"
    assert c_b["startTime"] == "09:00"
    gap = time_to_minutes(c_b["startTime"]) - time_to_minutes(c_a["endTime"])
    assert gap == 20, f"Expected gap to be compressed to 20 min, found {gap} min"

    # Verify zero dead-time gaps >= 240 min in post
    all_gaps, _, _ = TimetableOracle.detect_idle_gaps(post, dead_time_threshold=240)
    gaps_240 = [g for g in all_gaps if g["gapMinutes"] >= 240]
    assert len(gaps_240) == 0, f"Expected 0 gaps >= 240 min, found {len(gaps_240)}"


# ==============================================================================
# TEST 3: MATHEMATICAL CORRECTNESS OF BENCHMARK REPORT METRICS
# ==============================================================================

def test_benchmark_metrics_mathematical_correctness(dataset):
    """
    Independently calculate all metrics from raw JSON and verify against
    published values in benchmark_comparison_report.md.
    """
    legacy = dataset["timetable"]
    post = dataset["postUnitimeOptimizedTimetable"]

    def calc_util(tb):
        tot_enr = sum(c["enrolledStudents"] for c in tb)
        tot_cap = sum(c["roomCapacity"] for c in tb)
        tot_classes = len(tb)
        avg_occ = sum((c["enrolledStudents"] / c["roomCapacity"]) * 100.0 for c in tb) / tot_classes
        global_fill = (tot_enr / tot_cap) * 100.0
        seat_hours = sum(c["roomCapacity"] * (c["durationMinutes"] / 60.0) for c in tb)
        student_hours = sum(c["enrolledStudents"] * (c["durationMinutes"] / 60.0) for c in tb)
        wasted_seat_hours = sum(max(0, c["roomCapacity"] - c["enrolledStudents"]) * (c["durationMinutes"] / 60.0) for c in tb)
        overcrowded = sum(1 for c in tb if c["enrolledStudents"] > c["roomCapacity"])
        underutil = sum(1 for c in tb if (c["enrolledStudents"] / c["roomCapacity"] * 100.0) <= 15.0)
        return {
            "enrolled": tot_enr,
            "capacity": tot_cap,
            "avg_occ": round(avg_occ, 2),
            "global_fill": round(global_fill, 2),
            "seat_hours": round(seat_hours, 1),
            "student_hours": round(student_hours, 1),
            "wasted_seat_hours": round(wasted_seat_hours, 1),
            "overcrowded": overcrowded,
            "underutil": underutil
        }

    u_leg = calc_util(legacy)
    u_post = calc_util(post)

    # 1. Total student hours must be strictly invariant
    assert u_leg["student_hours"] == 5880.0
    assert u_post["student_hours"] == 5880.0
    assert u_leg["enrolled"] == 3512
    assert u_post["enrolled"] == 3512

    # 2. Seat hours offered and wasted seat hours
    assert u_leg["seat_hours"] == 7998.3
    assert u_post["seat_hours"] == 7756.7
    assert round(u_post["seat_hours"] - u_leg["seat_hours"], 1) == -241.6

    assert u_leg["wasted_seat_hours"] == 2151.7
    assert u_post["wasted_seat_hours"] == 1876.7
    wasted_delta = round(u_post["wasted_seat_hours"] - u_leg["wasted_seat_hours"], 1)
    assert wasted_delta == -275.0
    wasted_pct = round((275.0 / 2151.7) * 100.0, 2)
    assert wasted_pct == 12.78  # 12.78% reduction

    # 3. Fill ratios
    assert u_leg["global_fill"] == 73.00
    assert u_post["global_fill"] == 75.27
    fill_diff = round(u_post["global_fill"] - u_leg["global_fill"], 2)
    assert fill_diff == 2.27

    assert u_leg["avg_occ"] == 84.73
    assert u_post["avg_occ"] == 84.92

    # 4. Weekly cohort idle hours
    def calc_idle(tb):
        cohort_classes = defaultdict(lambda: defaultdict(list))
        for c in tb:
            cohort_classes[c["cohort"]][c["day"]].append(c)
        tot_min = 0
        for coh, days in cohort_classes.items():
            for day, clist in days.items():
                s = sorted(clist, key=lambda x: time_to_minutes(x["startTime"]))
                for i in range(len(s) - 1):
                    gap = time_to_minutes(s[i+1]["startTime"]) - time_to_minutes(s[i]["endTime"])
                    if gap > 0:
                        tot_min += gap
        return tot_min

    leg_idle = calc_idle(legacy)
    post_idle = calc_idle(post)
    assert leg_idle == 2310  # 38.50 hours
    assert post_idle == 2235  # 37.25 hours
    assert leg_idle / 60.0 == 38.5
    assert post_idle / 60.0 == 37.25
    assert (post_idle - leg_idle) / 60.0 == -1.25


# ==============================================================================
# TEST 4: ADVERSARIAL STRESS BOUNDARY CHECKS & EMPIRICAL DISCOVERIES
# ==============================================================================

def test_stress_dataset_referential_completeness(dataset, campus_topology):
    """Adversarial check: Exactly 84 classes, all room capacities match topology."""
    legacy = dataset["timetable"]
    post = dataset["postUnitimeOptimizedTimetable"]
    assert len(legacy) == 84
    assert len(post) == 84

    # Build room capacity ground truth using external_id from campus_topology.json
    topo_rooms = {}
    for camp in campus_topology.get("campuses", []):
        for b in camp.get("buildings", []):
            for r in b.get("rooms", []):
                rid = r.get("external_id")
                topo_rooms[rid] = r["capacity"]

    assert len(topo_rooms) == 20, f"Expected 20 rooms in topology, found {len(topo_rooms)}"

    # Verify every class in post uses a valid room with exact capacity
    for c in post:
        rid = c.get("roomExternalId")
        assert rid in topo_rooms, f"Room {rid} not found in campus_topology.json"
        assert c["roomCapacity"] == topo_rooms[rid], f"Capacity mismatch for {rid}: {c['roomCapacity']} vs {topo_rooms[rid]}"


def test_adversarial_empirical_discovery_cohort_overlap(dataset):
    """
    Empirical Discovery 1: Rescheduling IF2110_K01 to Monday 08:00-10:30
    introduced a 30-minute student cohort overlap with IF2120_K01 (10:00-11:40).
    """
    post = dataset["postUnitimeOptimizedTimetable"]
    cohort_classes = defaultdict(lambda: defaultdict(list))
    for c in post:
        cohort_classes[c["cohort"]][c["day"]].append(c)

    cohort_overlaps = []
    for coh, days in cohort_classes.items():
        for day, clist in days.items():
            for i in range(len(clist)):
                for j in range(i + 1, len(clist)):
                    cA, cB = clist[i], clist[j]
                    sA, eA = time_to_minutes(cA["startTime"]), time_to_minutes(cA["endTime"])
                    sB, eB = time_to_minutes(cB["startTime"]), time_to_minutes(cB["endTime"])
                    ov = max(0, min(eA, eB) - max(sA, sB))
                    if ov > 0:
                        cohort_overlaps.append({
                            "cohort": coh,
                            "day": day,
                            "classA": cA["classId"],
                            "classB": cB["classId"],
                            "overlapMinutes": ov
                        })

    # Assert exact empirical discovery: exactly 1 cohort overlap of 30 minutes
    assert len(cohort_overlaps) == 1
    co = cohort_overlaps[0]
    assert co["cohort"] == "IF_2024"
    assert co["day"] == "Monday"
    assert set([co["classA"], co["classB"]]) == {"IF2110_K01", "IF2120_K01"}
    assert co["overlapMinutes"] == 30


def test_adversarial_empirical_discovery_faculty_transit_buffer(dataset):
    """
    Empirical Discovery 2: Faculty team-teaching TPB courses have 20-minute
    buffers between Ganesha and Jatinangor (18.4 km).
    """
    post = dataset["postUnitimeOptimizedTimetable"]
    instr_classes = defaultdict(lambda: defaultdict(list))
    for c in post:
        for instr in c.get("instructors", []):
            instr_classes[instr["id"]][c["day"]].append(c)

    faculty_travel_deficits = []
    for iid, days in instr_classes.items():
        for day, clist in days.items():
            clist_sorted = sorted(clist, key=lambda x: time_to_minutes(x["startTime"]))
            for i in range(len(clist_sorted) - 1):
                cA, cB = clist_sorted[i], clist_sorted[i + 1]
                if cA["campus"] != cB["campus"]:
                    buf = time_to_minutes(cB["startTime"]) - time_to_minutes(cA["endTime"])
                    if buf < 60:
                        faculty_travel_deficits.append({
                            "instructorId": iid,
                            "day": day,
                            "classA": cA["classId"],
                            "campusA": cA["campus"],
                            "classB": cB["classId"],
                            "campusB": cB["campus"],
                            "bufferMinutes": buf,
                            "deficitMinutes": 60 - buf
                        })

    # Exactly 4 faculty travel deficits (2 instructors for MA1101 on Mon, 2 instructors for FI1101 on Tue)
    assert len(faculty_travel_deficits) == 4
    for fd in faculty_travel_deficits:
        assert fd["bufferMinutes"] == 20
        assert fd["deficitMinutes"] == 40


def test_adversarial_stress_invariants_across_timetables(dataset):
    """Verify that student enrollments and course durations are invariant."""
    legacy = dataset["timetable"]
    post = dataset["postUnitimeOptimizedTimetable"]
    leg_map = {c["classId"]: c for c in legacy}
    post_map = {c["classId"]: c for c in post}

    assert set(leg_map.keys()) == set(post_map.keys())
    for cid in leg_map:
        l = leg_map[cid]
        p = post_map[cid]
        assert l["enrolledStudents"] == p["enrolledStudents"], f"Enrolled mismatch for {cid}"
        assert l["durationMinutes"] == p["durationMinutes"], f"Duration mismatch for {cid}"
