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
