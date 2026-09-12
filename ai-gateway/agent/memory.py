"""UniTime AI Ingestion Gateway - Persistent Agent Memory.

Provides SQLite-backed persistent memory store for department knowledge,
room aliases, instructor quirks, human-in-the-loop resolution histories,
and audit logs.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# Default location for persistent agent SQLite memory
DEFAULT_MEMORY_DB_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "agent_memory.db"
)


class AgentMemory:
    """Persistent SQLite-backed knowledge and audit memory for the ingestion agent.

    Maintains long-term state across ingestion sessions:
    - Department quirks, room aliases, capacity records (`department_knowledge`)
    - Instructor preferences, teaching constraints, day/room habits (`instructor_quirks`)
    - Human disambiguation choices and learned fixes (`resolution_history`)
    - Structured audit logs and decisions (`audit_journal`)
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize SQLite memory store with automatic directory and table setup.

        Args:
            db_path: Path to SQLite database file. If None, checks UNITIME_AGENT_MEMORY_DB
                     or falls back to 'ai-gateway/data/agent_memory.db'.
                     Special value ':memory:' is supported for transient testing.
        """
        if db_path is None:
            env_db = os.getenv("UNITIME_AGENT_MEMORY_DB")
            self.db_path: Path | str = Path(env_db).resolve() if env_db else DEFAULT_MEMORY_DB_PATH
        elif str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path).resolve()

        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._shared_conn: Optional[sqlite3.Connection] = None

        # For in-memory databases, keep a persistent shared connection
        if str(self.db_path) == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
            try:
                self._shared_conn.execute("PRAGMA foreign_keys = ON;")
            except sqlite3.Error as exc:
                logger.debug("PRAGMA foreign_keys error on in-memory db: %s", exc)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Obtain thread-safe connection to the SQLite database."""
        if self._shared_conn is not None:
            return self._shared_conn

        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign keys for high-performance concurrent access
            try:
                with contextlib.closing(conn.execute("PRAGMA journal_mode = WAL;")):
                    pass
                with contextlib.closing(conn.execute("PRAGMA synchronous = NORMAL;")):
                    pass
                with contextlib.closing(conn.execute("PRAGMA foreign_keys = ON;")):
                    pass
            except sqlite3.Error as exc:
                logger.debug("PRAGMA configuration notice: %s", exc)
            self._local.conn = conn

        return self._local.conn

    def _init_db(self) -> None:
        """Create database tables and performance indices if they do not exist."""
        conn = self._get_connection()
        with conn:
            conn.executescript(
                """
                -- Table 1: Department-level knowledge (aliases, quirks, room capacities)
                CREATE TABLE IF NOT EXISTS department_knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    department_code TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(department_code, entity_type, key)
                );

                CREATE INDEX IF NOT EXISTS idx_dept_knowledge_lookup 
                ON department_knowledge (department_code, entity_type, key);

                -- Table 2: Instructor habits, room/time preferences, max teaching loads
                CREATE TABLE IF NOT EXISTS instructor_quirks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    department_code TEXT NOT NULL,
                    instructor_name TEXT NOT NULL,
                    preferred_days TEXT,
                    preferred_rooms TEXT,
                    max_hours REAL,
                    notes TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(department_code, instructor_name)
                );

                CREATE INDEX IF NOT EXISTS idx_instructor_lookup 
                ON instructor_quirks (department_code, instructor_name);

                -- Table 3: Learned disambiguation decisions & resolution history
                CREATE TABLE IF NOT EXISTS resolution_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_signature TEXT NOT NULL,
                    question TEXT,
                    user_choice TEXT,
                    applied_fix TEXT,
                    department_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_resolution_lookup 
                ON resolution_history (department_code, issue_signature);

                -- Table 4: Chronological audit journal for agent reasoning and actions
                CREATE TABLE IF NOT EXISTS audit_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level TEXT NOT NULL,
                    source_doc TEXT,
                    message TEXT NOT NULL,
                    metadata_json TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_audit_timestamp 
                ON audit_journal (timestamp DESC);

                -- Table 5: Progressive draft academic state for turn-by-turn conversational ingestion
                CREATE TABLE IF NOT EXISTS draft_academic_state (
                    session_id TEXT PRIMARY KEY,
                    campus_topology JSON,
                    buildings JSON,
                    courses JSON,
                    preferences JSON,
                    metadata JSON,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_draft_updated_at 
                ON draft_academic_state (updated_at DESC);
                """
            )

    # -------------------------------------------------------------------------
    # Room Alias & Department Knowledge
    # -------------------------------------------------------------------------

    def get_room_alias(self, dept: str, raw_name: str) -> Optional[str]:
        """Look up canonical room name for a given raw alias within a department.

        Args:
            dept: Department code (e.g., 'CS', 'IF', '*').
            raw_name: Raw string found in input document (e.g., 'Lab Komputer 1').

        Returns:
            Canonical room identifier (e.g., 'Labtek V 7601') or None if not registered.
        """
        if not raw_name or not str(raw_name).strip():
            return None

        clean_raw = str(raw_name).strip()
        clean_dept = str(dept).strip().upper() if dept else "*"

        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT value FROM department_knowledge
            WHERE entity_type = 'room_alias'
              AND LOWER(key) = LOWER(?)
              AND (UPPER(department_code) = ? OR department_code = '*')
            ORDER BY CASE WHEN department_code = '*' THEN 1 ELSE 0 END, updated_at DESC
            LIMIT 1
            """,
            (clean_raw, clean_dept),
        )) as cursor:
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_room_alias(self, dept: str, raw_name: str, canonical_name: str) -> None:
        """Register or update a room alias mapping for a department.

        Args:
            dept: Department code (e.g., 'CS', 'IF', '*').
            raw_name: Raw room label appearing in documents.
            canonical_name: Standardized UniTime room name.
        """
        if not raw_name or not str(raw_name).strip():
            raise ValueError("raw_name cannot be empty")
        if not canonical_name or not str(canonical_name).strip():
            raise ValueError("canonical_name cannot be empty")

        clean_dept = str(dept).strip().upper() if dept else "*"
        clean_raw = str(raw_name).strip()
        clean_canon = str(canonical_name).strip()

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO department_knowledge (department_code, entity_type, key, value, updated_at)
                VALUES (?, 'room_alias', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(department_code, entity_type, key)
                DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (clean_dept, clean_raw, clean_canon),
            )) as cursor:
                pass

    def get_room_capacity(self, building: str, room_number: str) -> Optional[int]:
        """Fetch recorded seating capacity for a room if known in knowledge base."""
        key = f"{building.strip().upper()} {room_number.strip().upper()}".strip()
        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT value FROM department_knowledge
            WHERE entity_type = 'room_capacity'
              AND UPPER(key) = ?
            LIMIT 1
            """,
            (key,),
        )) as cursor:
            row = cursor.fetchone()
            if row and row["value"]:
                try:
                    return int(row["value"])
                except ValueError:
                    return None
            return None

    def set_room_capacity(
        self, building: str, room_number: str, capacity: int, dept: str = "*"
    ) -> None:
        """Store or update the seating capacity for a room."""
        key = f"{building.strip().upper()} {room_number.strip().upper()}".strip()
        clean_dept = str(dept).strip().upper() if dept else "*"
        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO department_knowledge (department_code, entity_type, key, value, updated_at)
                VALUES (?, 'room_capacity', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(department_code, entity_type, key)
                DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (clean_dept, key, str(int(capacity))),
            )) as cursor:
                pass

    def get_department_knowledge(
        self, dept: str, entity_type: str, key: str
    ) -> Optional[str]:
        """Generic lookup for department knowledge records."""
        clean_dept = str(dept).strip().upper() if dept else "*"
        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT value FROM department_knowledge
            WHERE LOWER(entity_type) = LOWER(?)
              AND LOWER(key) = LOWER(?)
              AND (UPPER(department_code) = ? OR department_code = '*')
            ORDER BY CASE WHEN department_code = '*' THEN 1 ELSE 0 END, updated_at DESC
            LIMIT 1
            """,
            (entity_type.strip(), key.strip(), clean_dept),
        )) as cursor:
            row = cursor.fetchone()
            return row["value"] if row else None

    def set_department_knowledge(
        self, dept: str, entity_type: str, key: str, value: str
    ) -> None:
        """Generic upsert for department knowledge records."""
        clean_dept = str(dept).strip().upper() if dept else "*"
        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO department_knowledge (department_code, entity_type, key, value, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(department_code, entity_type, key)
                DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
                """,
                (clean_dept, entity_type.strip(), key.strip(), str(value)),
            )) as cursor:
                pass

    # -------------------------------------------------------------------------
    # Instructor Quirks & Preferences
    # -------------------------------------------------------------------------

    def get_instructor_preference(self, dept: str, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored quirks and scheduling preferences for an instructor.

        Args:
            dept: Department code (e.g. 'CS', 'IF', '*').
            name: Instructor name.

        Returns:
            Dictionary containing instructor preferences, or None if not found.
        """
        if not name or not str(name).strip():
            return None

        clean_name = str(name).strip()
        clean_dept = str(dept).strip().upper() if dept else "*"

        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT * FROM instructor_quirks
            WHERE LOWER(instructor_name) = LOWER(?)
              AND (UPPER(department_code) = ? OR department_code = '*')
            ORDER BY CASE WHEN department_code = '*' THEN 1 ELSE 0 END, updated_at DESC
            LIMIT 1
            """,
            (clean_name, clean_dept),
        )) as cursor:
            row = cursor.fetchone()
            if not row:
                return None

            preferred_days = row["preferred_days"]
            if preferred_days and preferred_days.startswith("[") and preferred_days.endswith("]"):
                try:
                    preferred_days = json.loads(preferred_days)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Failed to deserialize preferred_days: %s", exc)

            preferred_rooms = row["preferred_rooms"]
            if preferred_rooms and preferred_rooms.startswith("[") and preferred_rooms.endswith("]"):
                try:
                    preferred_rooms = json.loads(preferred_rooms)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Failed to deserialize preferred_rooms: %s", exc)

            return {
                "id": row["id"],
                "department_code": row["department_code"],
                "instructor_name": row["instructor_name"],
                "preferred_days": preferred_days,
                "preferred_rooms": preferred_rooms,
                "max_hours": row["max_hours"],
                "notes": row["notes"],
                "updated_at": row["updated_at"],
            }

    def set_instructor_preference(
        self, dept: str, name: str, prefs: Dict[str, Any]
    ) -> None:
        """Store or update quirks and preferences for an instructor.

        Args:
            dept: Department code.
            name: Instructor name.
            prefs: Dictionary containing preferred_days, preferred_rooms, max_hours, notes.
        """
        if not name or not str(name).strip():
            raise ValueError("Instructor name cannot be empty")

        clean_dept = str(dept).strip().upper() if dept else "*"
        clean_name = str(name).strip()

        raw_days = prefs.get("preferred_days")
        if isinstance(raw_days, (list, tuple, set)):
            pref_days_str = json.dumps(list(raw_days))
        elif raw_days is not None:
            pref_days_str = str(raw_days)
        else:
            pref_days_str = None

        raw_rooms = prefs.get("preferred_rooms")
        if isinstance(raw_rooms, (list, tuple, set)):
            pref_rooms_str = json.dumps(list(raw_rooms))
        elif raw_rooms is not None:
            pref_rooms_str = str(raw_rooms)
        else:
            pref_rooms_str = None

        max_hours = prefs.get("max_hours")
        if max_hours is not None:
            try:
                max_hours = float(max_hours)
            except (ValueError, TypeError):
                max_hours = None

        notes = str(prefs.get("notes")) if prefs.get("notes") is not None else None

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO instructor_quirks (
                    department_code, instructor_name, preferred_days, preferred_rooms, max_hours, notes, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(department_code, instructor_name)
                DO UPDATE SET
                    preferred_days = excluded.preferred_days,
                    preferred_rooms = excluded.preferred_rooms,
                    max_hours = excluded.max_hours,
                    notes = excluded.notes,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (clean_dept, clean_name, pref_days_str, pref_rooms_str, max_hours, notes),
            )) as cursor:
                pass

    # -------------------------------------------------------------------------
    # Resolution History (Learned Disambiguations)
    # -------------------------------------------------------------------------

    def find_previous_resolution(self, dept: str, issue_sig: str) -> Optional[str]:
        """Search for a prior human resolution matching the given issue signature.

        Args:
            dept: Department code.
            issue_sig: Unique signature string representing the ambiguity/issue.

        Returns:
            The previously applied fix or user choice string, or None if not found.
        """
        if not issue_sig or not str(issue_sig).strip():
            return None

        clean_sig = str(issue_sig).strip()
        clean_dept = str(dept).strip().upper() if dept else "*"

        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT applied_fix, user_choice FROM resolution_history
            WHERE issue_signature = ?
              AND (UPPER(department_code) = ? OR department_code IS NULL OR department_code = '' OR department_code = '*')
            ORDER BY CASE WHEN UPPER(department_code) = ? THEN 0 ELSE 1 END, created_at DESC
            LIMIT 1
            """,
            (clean_sig, clean_dept, clean_dept),
        )) as cursor:
            row = cursor.fetchone()
            if not row:
                return None
            return row["applied_fix"] if row["applied_fix"] else row["user_choice"]

    def save_resolution(
        self,
        dept: str,
        issue_sig: str,
        question: str,
        choice: str,
        fix: Union[str, Dict[str, Any], List[Any]],
    ) -> int:
        """Persist a human resolution choice and applied fix for future automatic reuse.

        Args:
            dept: Department code.
            issue_sig: Unique issue signature.
            question: Human-readable question presented to the user.
            choice: User selection or input text.
            fix: Fix payload or instruction applied (serialized to JSON if dict/list).

        Returns:
            The inserted database record ID.
        """
        if not issue_sig or not str(issue_sig).strip():
            raise ValueError("issue_sig cannot be empty")

        clean_dept = str(dept).strip().upper() if dept else "*"
        clean_sig = str(issue_sig).strip()
        clean_question = str(question).strip() if question else ""
        clean_choice = str(choice).strip() if choice else ""

        if isinstance(fix, (dict, list)):
            fix_str = json.dumps(fix)
        else:
            fix_str = str(fix) if fix is not None else ""

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO resolution_history (
                    issue_signature, question, user_choice, applied_fix, department_code
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (clean_sig, clean_question, clean_choice, fix_str, clean_dept),
            )) as cursor:
                record_id = cursor.lastrowid

        # Also write an audit entry for tracking
        self.log_audit(
            level="INFO",
            doc=None,
            message=f"Learned resolution saved for '{clean_sig}': {clean_choice}",
            meta={
                "department": clean_dept,
                "issue_signature": clean_sig,
                "choice": clean_choice,
                "applied_fix": fix,
            },
        )
        return record_id

    # -------------------------------------------------------------------------
    # Audit Journal
    # -------------------------------------------------------------------------

    def log_audit(
        self,
        level: str,
        doc: Optional[str],
        message: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Append an entry to the agent's persistent audit journal.

        Args:
            level: Severity or event level ('INFO', 'WARNING', 'ERROR', 'DEBUG', 'FIX').
            doc: Document path or name triggering the event.
            message: Descriptive log text explaining the event or reasoning.
            meta: Optional structured metadata dictionary to serialize as JSON.

        Returns:
            The inserted audit record ID.
        """
        clean_level = str(level).strip().upper()
        clean_doc = str(doc).strip() if doc else None
        clean_msg = str(message).strip()
        meta_json = json.dumps(meta) if meta is not None else None

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO audit_journal (level, source_doc, message, metadata_json)
                VALUES (?, ?, ?, ?)
                """,
                (clean_level, clean_doc, clean_msg, meta_json),
            )) as cursor:
                return cursor.lastrowid

    def get_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent audit journal logs in reverse chronological order.

        Args:
            limit: Maximum number of records to return (defaults to 100).

        Returns:
            List of parsed audit log dictionaries with deserialized metadata.
        """
        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT id, timestamp, level, source_doc, message, metadata_json
            FROM audit_journal
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )) as cursor:
            rows = cursor.fetchall()
        results: List[Dict[str, Any]] = []

        for row in rows:
            meta = None
            if row["metadata_json"]:
                try:
                    meta = json.loads(row["metadata_json"])
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.debug("Failed to deserialize metadata_json: %s", exc)
                    meta = {"raw": row["metadata_json"]}

            results.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "level": row["level"],
                    "source_doc": row["source_doc"],
                    "message": row["message"],
                    "metadata": meta,
                }
            )

        return results

    # -------------------------------------------------------------------------
    # Progressive Draft Academic State (Turn-by-Turn Ingestion)
    # -------------------------------------------------------------------------

    def get_draft_state(self, session_id: str) -> Dict[str, Any]:
        """Fetch the current progressive draft state for a given session.

        Args:
            session_id: Unique identifier for the conversational drafting session.

        Returns:
            Dictionary containing campus_topology, buildings, courses, preferences,
            metadata, and updated_at.
        """
        clean_sid = str(session_id).strip()
        default_state: Dict[str, Any] = {
            "session_id": clean_sid,
            "campus_topology": {"regions": [], "travel_times": {}},
            "buildings": [],
            "courses": [],
            "preferences": [],
            "metadata": {},
            "updated_at": None,
        }
        if not clean_sid:
            return default_state

        conn = self._get_connection()
        with contextlib.closing(conn.execute(
            """
            SELECT session_id, campus_topology, buildings, courses, preferences, metadata, updated_at
            FROM draft_academic_state
            WHERE session_id = ?
            LIMIT 1
            """,
            (clean_sid,),
        )) as cursor:
            row = cursor.fetchone()
            if not row:
                return default_state

            def _parse_field(val: Any, default: Any) -> Any:
                if val is None:
                    return default
                if isinstance(val, (dict, list)):
                    return val
                try:
                    return json.loads(val)
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    logger.debug("Failed to deserialize draft field: %s", exc)
                    return default

            topology = _parse_field(row["campus_topology"], {"regions": [], "travel_times": {}})
            if not isinstance(topology, dict):
                topology = {"regions": [], "travel_times": {}}
            topology.setdefault("regions", [])
            topology.setdefault("travel_times", {})

            buildings = _parse_field(row["buildings"], [])
            if not isinstance(buildings, list):
                buildings = []

            courses = _parse_field(row["courses"], [])
            if not isinstance(courses, list):
                courses = []

            preferences = _parse_field(row["preferences"], [])
            if not isinstance(preferences, list):
                preferences = []

            metadata = _parse_field(row["metadata"], {})
            if not isinstance(metadata, dict):
                metadata = {}

            return {
                "session_id": row["session_id"],
                "campus_topology": topology,
                "buildings": buildings,
                "courses": courses,
                "preferences": preferences,
                "metadata": metadata,
                "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
            }

    def upsert_draft_topology(
        self,
        session_id: str,
        regions: List[str],
        travel_times: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Update or initialize campus topology (regions and inter-campus transit times).

        Args:
            session_id: Session identifier.
            regions: List of campus region names (e.g. ['Depok', 'Salemba']).
            travel_times: Optional transit duration mappings.

        Returns:
            Updated draft state dictionary.
        """
        clean_sid = str(session_id).strip()
        if not clean_sid:
            raise ValueError("session_id cannot be empty")

        current = self.get_draft_state(clean_sid)
        topology = current["campus_topology"]

        # Merge regions preserving order without duplicates
        existing_regions = topology.get("regions", [])
        new_regions = [str(r).strip() for r in regions if r and str(r).strip()]
        combined_regions = list(dict.fromkeys(existing_regions + new_regions))

        # Merge travel times
        existing_tt = dict(topology.get("travel_times", {}))
        if travel_times and isinstance(travel_times, dict):
            for k, v in travel_times.items():
                existing_tt[str(k).strip()] = v

        updated_topology = {
            "regions": combined_regions,
            "travel_times": existing_tt,
        }

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO draft_academic_state (
                    session_id, campus_topology, buildings, courses, preferences, metadata, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    campus_topology = excluded.campus_topology,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    clean_sid,
                    json.dumps(updated_topology),
                    json.dumps(current["buildings"]),
                    json.dumps(current["courses"]),
                    json.dumps(current["preferences"]),
                    json.dumps(current["metadata"]),
                ),
            )):
                pass

        return self.get_draft_state(clean_sid)

    def upsert_draft_building_rooms(
        self,
        session_id: str,
        building_name: str,
        campus: str,
        rooms: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Register or update a building and its classrooms/labs within a campus region.

        Args:
            session_id: Session identifier.
            building_name: Name or code of the building.
            campus: Campus region name where building is located.
            rooms: List of room dictionaries (e.g. [{'room_number': '101', 'capacity': 50}]).

        Returns:
            Updated draft state dictionary.
        """
        clean_sid = str(session_id).strip()
        clean_bldg = str(building_name).strip()
        clean_campus = str(campus).strip()
        if not clean_sid:
            raise ValueError("session_id cannot be empty")
        if not clean_bldg:
            raise ValueError("building_name cannot be empty")

        current = self.get_draft_state(clean_sid)
        buildings = list(current["buildings"])

        # Locate existing building
        target_bldg: Optional[Dict[str, Any]] = None
        for b in buildings:
            if str(b.get("name", "")).strip().lower() == clean_bldg.lower():
                target_bldg = b
                break

        if target_bldg is None:
            target_bldg = {
                "name": clean_bldg,
                "campus": clean_campus,
                "rooms": [],
            }
            buildings.append(target_bldg)
        else:
            if clean_campus:
                target_bldg["campus"] = clean_campus

        # Merge rooms within building
        existing_rooms: List[Dict[str, Any]] = target_bldg.setdefault("rooms", [])
        for new_r in rooms:
            if not isinstance(new_r, dict):
                continue
            r_num = str(new_r.get("room_number") or new_r.get("name") or "").strip()
            found_room = False
            for ex_r in existing_rooms:
                ex_num = str(ex_r.get("room_number") or ex_r.get("name") or "").strip()
                if ex_num and ex_num.lower() == r_num.lower():
                    ex_r.update(new_r)
                    found_room = True
                    break
            if not found_room:
                existing_rooms.append(dict(new_r))

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO draft_academic_state (
                    session_id, campus_topology, buildings, courses, preferences, metadata, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    buildings = excluded.buildings,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    clean_sid,
                    json.dumps(current["campus_topology"]),
                    json.dumps(buildings),
                    json.dumps(current["courses"]),
                    json.dumps(current["preferences"]),
                    json.dumps(current["metadata"]),
                ),
            )):
                pass

        return self.get_draft_state(clean_sid)

    def upsert_draft_course(
        self,
        session_id: str,
        course_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Add or update a course offering in the draft timetable.

        Args:
            session_id: Session identifier.
            course_data: Course information including course_number, title, sks, and classes.

        Returns:
            Updated draft state dictionary.
        """
        clean_sid = str(session_id).strip()
        if not clean_sid:
            raise ValueError("session_id cannot be empty")
        if not isinstance(course_data, dict):
            raise ValueError("course_data must be a dictionary")

        c_num = str(
            course_data.get("course_number")
            or course_data.get("courseNumber")
            or course_data.get("code")
            or ""
        ).strip().upper()

        if not c_num:
            raise ValueError("course_data must contain a valid course_number or code")

        current = self.get_draft_state(clean_sid)
        courses = list(current["courses"])

        # Match existing course by course_number
        found_idx: Optional[int] = None
        for idx, c in enumerate(courses):
            existing_num = str(
                c.get("course_number")
                or c.get("courseNumber")
                or c.get("code")
                or ""
            ).strip().upper()
            if existing_num == c_num:
                found_idx = idx
                break

        if found_idx is not None:
            existing_course = courses[found_idx]
            merged_course = dict(existing_course)
            merged_course.update(course_data)
            merged_course["course_number"] = c_num
            courses[found_idx] = merged_course
        else:
            new_course = dict(course_data)
            new_course["course_number"] = c_num
            courses.append(new_course)

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO draft_academic_state (
                    session_id, campus_topology, buildings, courses, preferences, metadata, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    courses = excluded.courses,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    clean_sid,
                    json.dumps(current["campus_topology"]),
                    json.dumps(current["buildings"]),
                    json.dumps(courses),
                    json.dumps(current["preferences"]),
                    json.dumps(current["metadata"]),
                ),
            )):
                pass

        return self.get_draft_state(clean_sid)

    def upsert_draft_preference(
        self,
        session_id: str,
        preference_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Record or update a scheduling constraint or entity preference in draft state.

        Args:
            session_id: Session identifier.
            preference_data: Preference specification (entity_type, entity_name, preference_type, details).

        Returns:
            Updated draft state dictionary.
        """
        clean_sid = str(session_id).strip()
        if not clean_sid:
            raise ValueError("session_id cannot be empty")
        if not isinstance(preference_data, dict):
            raise ValueError("preference_data must be a dictionary")

        entity_type = str(preference_data.get("entity_type", "")).strip().lower()
        entity_name = str(preference_data.get("entity_name", "")).strip().lower()
        pref_type = str(preference_data.get("preference_type", "")).strip().lower()

        current = self.get_draft_state(clean_sid)
        preferences = list(current["preferences"])

        found = False
        for ex_pref in preferences:
            ex_et = str(ex_pref.get("entity_type", "")).strip().lower()
            ex_en = str(ex_pref.get("entity_name", "")).strip().lower()
            ex_pt = str(ex_pref.get("preference_type", "")).strip().lower()
            if ex_et == entity_type and ex_en == entity_name and ex_pt == pref_type:
                ex_pref.update(preference_data)
                found = True
                break

        if not found:
            preferences.append(dict(preference_data))

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                """
                INSERT INTO draft_academic_state (
                    session_id, campus_topology, buildings, courses, preferences, metadata, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET
                    preferences = excluded.preferences,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    clean_sid,
                    json.dumps(current["campus_topology"]),
                    json.dumps(current["buildings"]),
                    json.dumps(current["courses"]),
                    json.dumps(preferences),
                    json.dumps(current["metadata"]),
                ),
            )):
                pass

        return self.get_draft_state(clean_sid)

    def clear_draft_state(self, session_id: str) -> bool:
        """Purge draft state for a given session.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if draft was deleted or empty, False on invalid session_id.
        """
        clean_sid = str(session_id).strip()
        if not clean_sid:
            return False

        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute(
                "DELETE FROM draft_academic_state WHERE session_id = ?",
                (clean_sid,),
            )) as cursor:
                return cursor.rowcount >= 0

    def clear_all_for_testing(self) -> None:
        """Utility method to clear all tables during unit testing."""
        conn = self._get_connection()
        with conn:
            with contextlib.closing(conn.execute("DELETE FROM department_knowledge;")):
                pass
            with contextlib.closing(conn.execute("DELETE FROM instructor_quirks;")):
                pass
            with contextlib.closing(conn.execute("DELETE FROM resolution_history;")):
                pass
            with contextlib.closing(conn.execute("DELETE FROM audit_journal;")):
                pass
            with contextlib.closing(conn.execute("DELETE FROM draft_academic_state;")):
                pass

    def close(self) -> None:
        """Close active database connections."""
        if self._shared_conn is not None:
            self._shared_conn.close()
            self._shared_conn = None
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def __enter__(self) -> AgentMemory:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
