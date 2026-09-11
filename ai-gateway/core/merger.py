"""UniTime AI Ingestion Gateway - Payload Merger / Reducer.

Provides smart aggregation, merging, and deduplication of partial payloads
originating from multi-page documents, segmented tables, or batched chunks.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Constraint alias mappings between friendly aliases and native UniTime codes
CONSTRAINT_ALIAS_MAP: Dict[str, str] = {
    "CANNOT_OVERLAP": "DIFF_TIME",
    "SAME_INSTRUCTOR": "SAME_INSTR",
    "DIFF_INSTRUCTOR": "DIFF_INSTR",
    "BACK_TO_BACK": "BTB",
    "MEET_TOGETHER": "MEET_WITH",
    "PRECEDENCE": "PRECEDENCE",
    "BTB_PRECEDENCE": "BTB_PRECEDENCE",
    "SPREAD_DAYS": "SPREAD",
    "AT_MOST_2_HOURS_APART": "NHB(2)",
    "SAME_ROOM": "SAME_ROOM",
    "SAME_DAYS": "SAME_DAYS",
    "SAME_TIME": "SAME_TIME",
    "SAME_START": "SAME_START",
    "SAME_STUDENTS": "SAME_STUDENTS",
    "CAN_SHARE_ROOM": "CAN_SHARE_ROOM",
}

PREFERENCE_PRIORITY: Dict[str, int] = {
    "REQUIRED": 10,
    "R": 10,
    "STRONGLY_PREFERRED": 8,
    "2": 8,
    "PREFERRED": 6,
    "1": 6,
    "NEUTRAL": 4,
    "0": 4,
    "DISCOURAGED": 2,
    "-1": 2,
    "STRONGLY_DISCOURAGED": 1,
    "-2": 1,
    "PROHIBITED": 0,
    "P": 0,
}


class Merger:
    """Aggregates and deduplicates partial UniTime ingestion payloads."""

    def __init__(self, normalize_constraint_aliases: bool = False) -> None:
        """Initialize merger.

        Args:
            normalize_constraint_aliases: If True, transforms friendly aliases
                like CANNOT_OVERLAP to native UniTime code DIFF_TIME.
        """
        self.normalize_constraint_aliases = normalize_constraint_aliases
        self.conflicts: List[str] = []

    def merge(self, payloads: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge a sequence of partial payloads into a single unified payload.

        Args:
            payloads: An iterable of partial payload dictionaries.

        Returns:
            A unified, deduplicated payload dictionary.
        """
        self.conflicts = []
        payload_list = [p for p in payloads if isinstance(p, dict) and p]
        if not payload_list:
            return {}

        base = copy.deepcopy(payload_list[0])
        if self.normalize_constraint_aliases:
            for dc in base.get("distributionConstraints", []):
                if isinstance(dc, dict):
                    c_type = dc.get("type", "").strip().upper()
                    if c_type in CONSTRAINT_ALIAS_MAP:
                        dc["type"] = CONSTRAINT_ALIAS_MAP[c_type]

        for incoming in payload_list[1:]:
            base = self.merge_two(base, incoming)

        # Global instructor cross-course consistency cleanup
        self._standardize_global_instructors(base)

        return base

    def merge_two(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
        """Merge two payload objects into one.

        Args:
            left: The base/accumulator payload.
            right: The incoming payload to merge into base.

        Returns:
            The combined payload.
        """
        if not left:
            return copy.deepcopy(right)
        if not right:
            return copy.deepcopy(left)

        merged = copy.deepcopy(left)

        # 1. Merge Ingest Control
        self._merge_ingest_control(merged, right.get("ingestControl"))

        # 2. Merge Academic Session
        self._merge_academic_session(merged, right.get("academicSession"))

        # 3. Merge Department
        self._merge_department(merged, right.get("department"))

        # 4. Merge Subject Area
        self._merge_subject_area(merged, right.get("subjectArea"))

        # 5. Merge Courses / Offerings
        self._merge_courses(merged, right.get("courses", []))

        # 6. Merge Distribution Constraints
        self._merge_distribution_constraints(
            merged, right.get("distributionConstraints", [])
        )

        return merged

    # -------------------------------------------------------------------------
    # Internal Header / Envelope Merging
    # -------------------------------------------------------------------------

    @staticmethod
    def _merge_ingest_control(
        target: Dict[str, Any], incoming_ctrl: Optional[Dict[str, Any]]
    ) -> None:
        if not incoming_ctrl or not isinstance(incoming_ctrl, dict):
            return

        target_ctrl = target.setdefault("ingestControl", {})
        for key, val in incoming_ctrl.items():
            if val is not None and (key not in target_ctrl or not target_ctrl[key]):
                target_ctrl[key] = val

    def _merge_academic_session(
        self, target: Dict[str, Any], incoming_session: Optional[Dict[str, Any]]
    ) -> None:
        if not incoming_session or not isinstance(incoming_session, dict):
            return

        target_session = target.setdefault("academicSession", {})
        for field in ("year", "term", "campus"):
            inc_val = incoming_session.get(field)
            if inc_val:
                cur_val = target_session.get(field)
                if not cur_val:
                    target_session[field] = inc_val
                elif cur_val != inc_val:
                    msg = (
                        f"Academic session conflict for '{field}': '{cur_val}' vs '{inc_val}'. "
                        f"Retaining '{cur_val}'."
                    )
                    logger.warning(msg)
                    self.conflicts.append(msg)

    def _merge_department(
        self, target: Dict[str, Any], incoming_dept: Optional[Dict[str, Any]]
    ) -> None:
        if not incoming_dept or not isinstance(incoming_dept, dict):
            return

        target_dept = target.setdefault("department", {})
        for field in ("code", "name"):
            inc_val = incoming_dept.get(field)
            if inc_val:
                cur_val = target_dept.get(field)
                if not cur_val:
                    target_dept[field] = inc_val
                elif cur_val != inc_val:
                    msg = (
                        f"Department conflict for '{field}': '{cur_val}' vs '{inc_val}'. "
                        f"Retaining '{cur_val}'."
                    )
                    logger.warning(msg)
                    self.conflicts.append(msg)

    def _merge_subject_area(
        self, target: Dict[str, Any], incoming_sa: Optional[Dict[str, Any]]
    ) -> None:
        if not incoming_sa or not isinstance(incoming_sa, dict):
            return

        target_sa = target.setdefault("subjectArea", {})
        for field in ("abbreviation", "title", "externalId"):
            inc_val = incoming_sa.get(field)
            if inc_val:
                cur_val = target_sa.get(field)
                if not cur_val:
                    target_sa[field] = inc_val
                elif cur_val != inc_val:
                    msg = (
                        f"Subject area conflict for '{field}': '{cur_val}' vs '{inc_val}'. "
                        f"Retaining '{cur_val}'."
                    )
                    logger.warning(msg)
                    self.conflicts.append(msg)

    # -------------------------------------------------------------------------
    # Courses & Instructional Hierarchy Merging
    # -------------------------------------------------------------------------

    def _merge_courses(
        self, target: Dict[str, Any], incoming_courses: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(incoming_courses, list) or not incoming_courses:
            return

        target_courses: List[Dict[str, Any]] = target.setdefault("courses", [])

        # Index existing courses by normalized course number
        course_map: Dict[str, Dict[str, Any]] = {}
        for c in target_courses:
            c_num = c.get("courseNumber", "").strip().upper()
            if c_num:
                course_map[c_num] = c

        for inc_course in incoming_courses:
            if not isinstance(inc_course, dict):
                continue
            c_num = inc_course.get("courseNumber", "").strip().upper()
            if not c_num:
                continue

            if c_num in course_map:
                # Merge existing course offering
                self._merge_single_course(course_map[c_num], inc_course)
            else:
                new_c = copy.deepcopy(inc_course)
                target_courses.append(new_c)
                course_map[c_num] = new_c

    def _merge_single_course(
        self, target_c: Dict[str, Any], inc_c: Dict[str, Any]
    ) -> None:
        # Merge scalar metadata: prefer non-empty / more detailed values
        for key in ("title", "scheduleBookNote", "consentType"):
            inc_val = inc_c.get(key)
            cur_val = target_c.get(key)
            if inc_val and not cur_val:
                target_c[key] = inc_val
            elif (
                inc_val
                and cur_val
                and key == "title"
                and len(inc_val) > len(cur_val)
            ):
                target_c[key] = inc_val

        # Projected demand: take higher value
        inc_demand = inc_c.get("projectedDemand")
        cur_demand = target_c.get("projectedDemand")
        if inc_demand is not None:
            if cur_demand is None or inc_demand > cur_demand:
                target_c["projectedDemand"] = inc_demand

        # Merge Credit
        self._merge_credit(target_c, inc_c.get("credit"))

        # Merge Configurations
        self._merge_configurations(target_c, inc_c.get("configurations", []))

    @staticmethod
    def _merge_credit(
        target_c: Dict[str, Any], inc_credit: Optional[Dict[str, Any]]
    ) -> None:
        if not inc_credit or not isinstance(inc_credit, dict):
            return

        cur_credit = target_c.setdefault("credit", {})
        for field in (
            "units",
            "creditType",
            "creditUnitType",
            "format",
            "minimumUnits",
            "maximumUnits",
        ):
            inc_val = inc_credit.get(field)
            if inc_val is not None and field not in cur_credit:
                cur_credit[field] = inc_val

    def _merge_configurations(
        self, target_c: Dict[str, Any], inc_configs: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(inc_configs, list) or not inc_configs:
            return

        target_configs: List[Dict[str, Any]] = target_c.setdefault("configurations", [])
        config_map: Dict[str, Dict[str, Any]] = {
            cfg.get("name", "Default").strip().lower(): cfg
            for cfg in target_configs
            if isinstance(cfg, dict)
        }

        for inc_cfg in inc_configs:
            if not isinstance(inc_cfg, dict):
                continue
            cfg_name_key = inc_cfg.get("name", "Default").strip().lower()

            if cfg_name_key in config_map:
                cur_cfg = config_map[cfg_name_key]
                # Merge subparts under this config
                self._merge_subparts(cur_cfg, inc_cfg.get("subparts", []))
            else:
                new_cfg = copy.deepcopy(inc_cfg)
                target_configs.append(new_cfg)
                config_map[cfg_name_key] = new_cfg

    def _merge_subparts(
        self, target_cfg: Dict[str, Any], inc_subparts: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(inc_subparts, list) or not inc_subparts:
            return

        def _get_subpart_key(sp: Dict[str, Any]) -> str:
            sp_type = sp.get("type", "").strip().lower()
            sp_suffix = sp.get("suffix", "").strip().lower()
            sp_parent = sp.get("parentSubpartType", "").strip().lower()
            return f"{sp_type}::{sp_suffix}::{sp_parent}"

        target_subparts: List[Dict[str, Any]] = target_cfg.setdefault("subparts", [])
        subpart_map: Dict[str, Dict[str, Any]] = {
            _get_subpart_key(sp): sp
            for sp in target_subparts
            if isinstance(sp, dict) and sp.get("type")
        }

        for inc_sp in inc_subparts:
            if not isinstance(inc_sp, dict):
                continue
            if not inc_sp.get("type"):
                continue
            sp_type_key = _get_subpart_key(inc_sp)

            if sp_type_key in subpart_map:
                cur_sp = subpart_map[sp_type_key]
                # Update minPerWeek if current is 0
                if (
                    not cur_sp.get("minPerWeek")
                    and inc_sp.get("minPerWeek") is not None
                ):
                    cur_sp["minPerWeek"] = inc_sp["minPerWeek"]
                if (
                    not cur_sp.get("parentSubpartType")
                    and inc_sp.get("parentSubpartType")
                ):
                    cur_sp["parentSubpartType"] = inc_sp["parentSubpartType"]

                # Merge classes under this subpart
                self._merge_classes(cur_sp, inc_sp.get("classes", []))
            else:
                new_sp = copy.deepcopy(inc_sp)
                target_subparts.append(new_sp)
                subpart_map[sp_type_key] = new_sp

    def _merge_classes(
        self, target_sp: Dict[str, Any], inc_classes: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(inc_classes, list) or not inc_classes:
            return

        target_classes: List[Dict[str, Any]] = target_sp.setdefault("classes", [])
        class_map: Dict[str, Dict[str, Any]] = {
            cls_obj.get("sectionName", "").strip().upper(): cls_obj
            for cls_obj in target_classes
            if isinstance(cls_obj, dict) and cls_obj.get("sectionName")
        }

        for inc_cls in inc_classes:
            if not isinstance(inc_cls, dict):
                continue
            sec_name_key = inc_cls.get("sectionName", "").strip().upper()
            if not sec_name_key:
                continue

            if sec_name_key in class_map:
                # Merge existing class section
                cur_cls = class_map[sec_name_key]
                self._merge_single_class(cur_cls, inc_cls)
            else:
                # Append new class section (e.g. K01 was on page 1, K02 is on page 2)
                new_cls = copy.deepcopy(inc_cls)
                target_classes.append(new_cls)
                class_map[sec_name_key] = new_cls

    def _merge_single_class(
        self, target_cls: Dict[str, Any], inc_cls: Dict[str, Any]
    ) -> None:
        # Scalar fields: update capacity if target has default or smaller
        inc_cap = inc_cls.get("capacity")
        if inc_cap and inc_cap > target_cls.get("capacity", 0):
            target_cls["capacity"] = inc_cap

        for field in ("scheduleNote", "parentClassSection", "roomRatio"):
            inc_val = inc_cls.get(field)
            if inc_val is not None:
                if field not in target_cls:
                    target_cls[field] = inc_val
                elif field == "scheduleNote":
                    existing_notes = [n.strip() for n in target_cls[field].split(";") if n.strip()]
                    if inc_val.strip() not in existing_notes:
                        target_cls[field] = f"{target_cls[field]}; {inc_val.strip()}"

        # Merge instructors
        self._merge_instructors(target_cls, inc_cls.get("instructors", []))

        # Merge timePreferences
        self._merge_time_preferences(
            target_cls, inc_cls.get("timePreferences", [])
        )

        # Merge roomPreferences
        self._merge_room_preferences(
            target_cls, inc_cls.get("roomPreferences", [])
        )

    @staticmethod
    def _merge_instructors(
        target_cls: Dict[str, Any], inc_instructors: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(inc_instructors, list) or not inc_instructors:
            return

        target_instructors: List[Dict[str, Any]] = target_cls.setdefault(
            "instructors", []
        )
        instructor_map: Dict[str, Dict[str, Any]] = {}
        for ins in target_instructors:
            if not isinstance(ins, dict):
                continue
            ins_id = str(ins.get("id", "")).strip().upper()
            if ins_id:
                instructor_map[ins_id] = ins

        for inc_ins in inc_instructors:
            if not isinstance(inc_ins, dict):
                continue
            ins_id = str(inc_ins.get("id", "")).strip().upper()
            if not ins_id:
                ins_id = inc_ins.get("name", "").strip().upper()

            if ins_id in instructor_map:
                cur_ins = instructor_map[ins_id]
                for fld in ("email", "isLead"):
                    if inc_ins.get(fld) is not None and fld not in cur_ins:
                        cur_ins[fld] = inc_ins[fld]
            else:
                new_ins = copy.deepcopy(inc_ins)
                target_instructors.append(new_ins)
                instructor_map[ins_id] = new_ins

        # Recalculate teaching share percentages according to generalized formula if multiple instructors
        Merger._recalculate_shares(target_instructors)

    @staticmethod
    def _recalculate_shares(instructors: List[Dict[str, Any]]) -> None:
        """Apply deterministic N-instructor teaching share formula if shares are missing or invalid."""
        if not instructors:
            return
        n = len(instructors)
        if n == 1:
            instructors[0]["sharePercentage"] = 100
            if "isLead" not in instructors[0]:
                instructors[0]["isLead"] = True
            return

        # Check if existing shares already sum to 100%
        valid_shares = []
        for ins in instructors:
            sp = ins.get("sharePercentage")
            if isinstance(sp, (int, float)) and int(sp) == sp:
                valid_shares.append(int(sp))
                ins["sharePercentage"] = int(sp)

        if len(valid_shares) == n and sum(valid_shares) == 100:
            return

        # Allocate per N-instructor formula: member = floor(100/N), lead = 100 - (N-1)*member
        member_share = 100 // n
        lead_share = 100 - (n - 1) * member_share

        lead_found = False
        for ins in instructors:
            if ins.get("isLead") is True and not lead_found:
                ins["sharePercentage"] = lead_share
                lead_found = True
            else:
                ins["isLead"] = False
                ins["sharePercentage"] = member_share

        if not lead_found:
            instructors[0]["isLead"] = True
            instructors[0]["sharePercentage"] = lead_share

    @staticmethod
    def _merge_time_preferences(
        target_cls: Dict[str, Any], inc_tps: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(inc_tps, list) or not inc_tps:
            return

        target_tps: List[Dict[str, Any]] = target_cls.setdefault("timePreferences", [])
        seen_tps = {
            (
                tp.get("days", "").strip(),
                tp.get("startTime", "").strip(),
                tp.get("endTime", "").strip(),
            )
            for tp in target_tps
            if isinstance(tp, dict)
        }

        for inc_tp in inc_tps:
            if not isinstance(inc_tp, dict):
                continue
            key = (
                inc_tp.get("days", "").strip(),
                inc_tp.get("startTime", "").strip(),
                inc_tp.get("endTime", "").strip(),
            )
            if key not in seen_tps:
                target_tps.append(copy.deepcopy(inc_tp))
                seen_tps.add(key)

    @staticmethod
    def _merge_room_preferences(
        target_cls: Dict[str, Any], inc_rps: List[Dict[str, Any]]
    ) -> None:
        if not isinstance(inc_rps, list) or not inc_rps:
            return

        target_rps: List[Dict[str, Any]] = target_cls.setdefault("roomPreferences", [])
        seen_rps = {
            (
                rp.get("building", "").strip(),
                rp.get("roomNumber", "").strip(),
                rp.get("feature", "").strip(),
            )
            for rp in target_rps
            if isinstance(rp, dict)
        }

        for inc_rp in inc_rps:
            if not isinstance(inc_rp, dict):
                continue
            key = (
                inc_rp.get("building", "").strip(),
                inc_rp.get("roomNumber", "").strip(),
                inc_rp.get("feature", "").strip(),
            )
            if key not in seen_rps:
                target_rps.append(copy.deepcopy(inc_rp))
                seen_rps.add(key)

    # -------------------------------------------------------------------------
    # Distribution Constraints Merging & Deduplication
    # -------------------------------------------------------------------------

    def _merge_distribution_constraints(
        self,
        target: Dict[str, Any],
        incoming_constraints: List[Dict[str, Any]],
    ) -> None:
        if not isinstance(incoming_constraints, list) or not incoming_constraints:
            return

        target_constraints: List[Dict[str, Any]] = target.setdefault(
            "distributionConstraints", []
        )

        # Index existing constraints by canonical signature
        constraint_map: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for dc in target_constraints:
            sig = self._constraint_signature(dc)
            if sig:
                constraint_map[sig] = dc

        for inc_dc in incoming_constraints:
            if not isinstance(inc_dc, dict):
                continue
            sig = self._constraint_signature(inc_dc)
            if not sig:
                continue

            if sig in constraint_map:
                # Merge duplicate constraint details (e.g. elevate preference level or combine notes)
                existing_dc = constraint_map[sig]
                cur_lvl = existing_dc.get("level", "REQUIRED")
                inc_lvl = inc_dc.get("level", "REQUIRED")
                if PREFERENCE_PRIORITY.get(inc_lvl, 0) > PREFERENCE_PRIORITY.get(
                    cur_lvl, 0
                ):
                    existing_dc["level"] = inc_lvl

                inc_note = inc_dc.get("note", "").strip()
                cur_note = existing_dc.get("note", "").strip()
                if inc_note and inc_note not in cur_note:
                    existing_dc["note"] = (
                        f"{cur_note}; {inc_note}" if cur_note else inc_note
                    )
            else:
                new_dc = copy.deepcopy(inc_dc)
                if self.normalize_constraint_aliases:
                    c_type = new_dc.get("type", "").strip().upper()
                    new_dc["type"] = CONSTRAINT_ALIAS_MAP.get(c_type, new_dc.get("type"))
                target_constraints.append(new_dc)
                constraint_map[sig] = new_dc

    def _constraint_signature(self, dc: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
        """Generate a canonical order-independent signature for a distribution constraint."""
        raw_type = dc.get("type", "").strip().upper()
        if not raw_type:
            return None

        # Canonicalize type for comparison (CANNOT_OVERLAP and DIFF_TIME match)
        norm_type = CONSTRAINT_ALIAS_MAP.get(raw_type, raw_type)
        structure = dc.get("structure", "AllClasses")

        classes = dc.get("classes", [])
        if not isinstance(classes, list) or len(classes) < 2:
            return None

        # Build sorted tuple of class references
        class_refs: List[Tuple[str, str]] = []
        for cr in classes:
            if not isinstance(cr, dict):
                continue
            c_num = cr.get("courseNumber", "").strip().upper()
            sec = cr.get("sectionName", "").strip().upper()
            if c_num and sec:
                class_refs.append((c_num, sec))

        if len(class_refs) < 2:
            return None

        # For undirected constraints (CANNOT_OVERLAP, SAME_ROOM, SAME_TIME), sort class refs
        # For directed constraints (PRECEDENCE, BTB_PRECEDENCE), preserve order!
        is_directed = "PRECEDENCE" in norm_type or structure == "Progressive"
        if not is_directed:
            class_refs.sort()

        return (norm_type, structure, tuple(class_refs))

    # -------------------------------------------------------------------------
    # Cross-Offering Instructor Standardization
    # -------------------------------------------------------------------------

    @staticmethod
    def _standardize_global_instructors(payload: Dict[str, Any]) -> None:
        """Ensure identical instructors across different courses share consistent metadata."""
        courses = payload.get("courses", [])
        if not isinstance(courses, list):
            return

        # Build instructor master catalog
        catalog: Dict[str, Dict[str, Any]] = {}
        for c in courses:
            if not isinstance(c, dict):
                continue
            for cfg in c.get("configurations", []):
                for sp in cfg.get("subparts", []):
                    for cls_obj in sp.get("classes", []):
                        for ins in cls_obj.get("instructors", []):
                            ins_id = str(ins.get("id", "")).strip().upper()
                            if not ins_id:
                                continue
                            if ins_id not in catalog:
                                catalog[ins_id] = {
                                    "id": ins.get("id"),
                                    "name": ins.get("name"),
                                    "email": ins.get("email"),
                                }
                            else:
                                master = catalog[ins_id]
                                if ins.get("email") and not master.get("email"):
                                    master["email"] = ins.get("email")
                                if ins.get("name") and len(ins.get("name")) > len(
                                    master.get("name", "")
                                ):
                                    master["name"] = ins.get("name")

        # Apply master catalog back to all instances
        for c in courses:
            if not isinstance(c, dict):
                continue
            for cfg in c.get("configurations", []):
                for sp in cfg.get("subparts", []):
                    for cls_obj in sp.get("classes", []):
                        for ins in cls_obj.get("instructors", []):
                            ins_id = str(ins.get("id", "")).strip().upper()
                            if ins_id in catalog:
                                master = catalog[ins_id]
                                if master.get("name"):
                                    ins["name"] = master["name"]
                                if master.get("email") and not ins.get("email"):
                                    ins["email"] = master["email"]
