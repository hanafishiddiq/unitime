"""UniTime AI Ingestion Gateway - HTTP Client.

Communicates with UniTime's SmartIngestConnector (/api/smart-ingest), providing
health check verification, authenticated payload submission, and response parsing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_UNITIME_URL = "http://localhost:8080/unitime/api/smart-ingest"


class UniTimeClientError(Exception):
    """Base exception for UniTime client operations."""


class UniTimeConnectionError(UniTimeClientError):
    """Raised when connecting to UniTime server fails."""


class UniTimeResponseError(UniTimeClientError):
    """Raised when UniTime returns an HTTP error status code or invalid payload."""


@dataclass
class IngestSummary:
    """Summary metrics of the ingestion transaction returned by UniTime."""

    courses_count: int = 0
    classes_count: int = 0
    distribution_constraints_count: int = 0
    warnings_count: int = 0
    errors_count: int = 0


@dataclass
class CourseImportSummary:
    """Import details for an individual course offering."""

    course_number: str
    title: str
    configurations_count: int = 0
    classes_count: int = 0


@dataclass
class LogEntry:
    """Log entry emitted by UniTime data exchange import process."""

    level: str
    message: str
    timestamp: Optional[str] = None
    stack_trace: Optional[str] = None


@dataclass
class IngestClientResponse:
    """Structured response returned by UniTime SmartIngestConnector."""

    status: str
    http_status_code: int
    raw_json: Dict[str, Any]
    error: Optional[str] = None
    timestamp: Optional[str] = None
    academic_session: Dict[str, str] = field(default_factory=dict)
    department: Optional[str] = None
    subject_area: Optional[str] = None
    summary: IngestSummary = field(default_factory=IngestSummary)
    courses_imported: List[CourseImportSummary] = field(default_factory=list)
    logs: List[LogEntry] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        """Returns True if status is SUCCESS and no fatal error occurred."""
        return self.status.upper() == "SUCCESS"

    @property
    def has_warnings(self) -> bool:
        """Returns True if ingestion finished with warnings."""
        return self.status.upper() == "WARNINGS"

    def summary_text(self) -> str:
        """Generate a formatted human-readable summary of the ingestion result."""
        lines = [
            f"Ingestion Result: {self.status.upper()} (HTTP {self.http_status_code})",
            f"Timestamp: {self.timestamp or 'N/A'}",
        ]
        if self.academic_session:
            sess = self.academic_session
            lines.append(
                f"Session: {sess.get('term', '')} {sess.get('year', '')} ({sess.get('campus', '')})"
            )
        if self.subject_area:
            lines.append(f"Subject Area: {self.subject_area}")
        if self.department:
            lines.append(f"Department: {self.department}")

        lines.append(
            f"Counts: {self.summary.courses_count} courses, {self.summary.classes_count} classes, "
            f"{self.summary.distribution_constraints_count} constraints | "
            f"Warnings: {self.summary.warnings_count}, Errors: {self.summary.errors_count}"
        )

        if self.error:
            lines.append(f"Fatal Error: {self.error}")

        if self.courses_imported:
            lines.append("Imported Courses:")
            for c in self.courses_imported:
                lines.append(
                    f"  - {c.course_number} ({c.title}): {c.configurations_count} configs, {c.classes_count} classes"
                )

        if self.logs:
            warning_or_error_logs = [l for l in self.logs if l.level.upper() in ("WARN", "ERROR")]
            if warning_or_error_logs:
                lines.append(f"Server Logs ({len(warning_or_error_logs)} warnings/errors):")
                for l in warning_or_error_logs[:10]:
                    lines.append(f"  [{l.level}] {l.message}")
                if len(warning_or_error_logs) > 10:
                    lines.append(f"  ... and {len(warning_or_error_logs) - 10} more log entries.")

        return "\n".join(lines)


class UniTimeClient:
    """Client for interacting with UniTime Smart Ingest REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        token: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        """Initialize UniTime API client.

        Credentials and URL default to environment variables if omitted.
        """
        self.base_url = (
            base_url or os.getenv("UNITIME_API_URL") or DEFAULT_UNITIME_URL
        ).rstrip("/")
        self.username = username or os.getenv("UNITIME_USERNAME")
        self.password = password or os.getenv("UNITIME_PASSWORD")
        self.token = token or os.getenv("UNITIME_API_TOKEN")

        try:
            env_timeout = float(os.getenv("UNITIME_TIMEOUT_SECONDS", ""))
        except (ValueError, TypeError):
            env_timeout = timeout_seconds
        self.timeout = env_timeout or timeout_seconds

    def _build_headers(
        self, extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, str]:
        """Construct standard HTTP headers for UniTime API requests."""
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _get_auth(self) -> Optional[httpx.BasicAuth]:
        """Return BasicAuth if username/password are supplied and token is not used."""
        if not self.token and self.username and self.password:
            return httpx.BasicAuth(self.username, self.password)
        return None

    def health_check(self) -> Dict[str, Any]:
        """Perform a GET request to UniTime endpoint to check availability and schema metadata."""
        headers = self._build_headers()
        auth = self._get_auth()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self.base_url, headers=headers, auth=auth)
        except httpx.ConnectError as exc:
            raise UniTimeConnectionError(
                f"Failed to connect to UniTime endpoint at {self.base_url}: Connection refused or host unreachable."
            ) from exc
        except httpx.TimeoutException as exc:
            raise UniTimeConnectionError(
                f"Timeout connecting to UniTime endpoint at {self.base_url} after {self.timeout}s."
            ) from exc
        except Exception as exc:
            raise UniTimeClientError(f"HTTP request error: {exc}") from exc

        if response.status_code != 200:
            raise UniTimeResponseError(
                f"UniTime GET endpoint returned HTTP {response.status_code}: {response.text}"
            )

        try:
            return response.json()
        except Exception as exc:
            raise UniTimeResponseError(
                f"Failed to parse UniTime response JSON: {response.text}"
            ) from exc

    def submit_ingest(
        self,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> IngestClientResponse:
        """Submit full payload to UniTime Smart Ingest API (POST /api/smart-ingest)."""
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dictionary.")

        headers = self._build_headers(extra_headers)
        auth = self._get_auth()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.base_url, json=payload, headers=headers, auth=auth
                )
        except httpx.ConnectError as exc:
            raise UniTimeConnectionError(
                f"Failed to connect to UniTime endpoint at {self.base_url}: Connection refused."
            ) from exc
        except httpx.TimeoutException as exc:
            raise UniTimeConnectionError(
                f"UniTime request timed out after {self.timeout} seconds."
            ) from exc
        except Exception as exc:
            raise UniTimeClientError(f"Network error while submitting to UniTime: {exc}") from exc

        try:
            resp_data = response.json()
        except Exception:
            resp_data = {
                "status": "FAILED" if response.status_code >= 400 else "UNKNOWN",
                "error": f"Server returned non-JSON response (HTTP {response.status_code}): {response.text[:300]}",
            }

        return self._parse_ingest_response(resp_data, response.status_code)

    @staticmethod
    def _parse_ingest_response(
        data: Dict[str, Any], status_code: int
    ) -> IngestClientResponse:
        """Parse raw response JSON from UniTime SmartIngestConnector into typed response object."""
        status = data.get("status", "FAILED" if status_code >= 400 else "SUCCESS")
        error_msg = data.get("error")
        timestamp = data.get("timestamp")

        session_raw = data.get("academicSession", {})
        academic_session = {}
        if isinstance(session_raw, dict):
            academic_session = {
                "year": session_raw.get("year", ""),
                "term": session_raw.get("term", ""),
                "campus": session_raw.get("campus", ""),
            }

        department = data.get("department")
        subject_area = data.get("subjectArea")

        # Parse summary counts
        summary_raw = data.get("summary", {})
        summary = IngestSummary(
            courses_count=summary_raw.get("coursesCount", 0),
            classes_count=summary_raw.get("classesCount", 0),
            distribution_constraints_count=summary_raw.get("distributionConstraintsCount", 0),
            warnings_count=summary_raw.get("warningsCount", 0),
            errors_count=summary_raw.get("errorsCount", 0),
        )

        # Parse imported courses list
        courses_imported: List[CourseImportSummary] = []
        for c in data.get("coursesImported", []):
            if isinstance(c, dict):
                courses_imported.append(
                    CourseImportSummary(
                        course_number=c.get("courseNumber", ""),
                        title=c.get("title", ""),
                        configurations_count=c.get("configurationsCount", 0),
                        classes_count=c.get("classesCount", 0),
                    )
                )

        # Parse log entries
        logs: List[LogEntry] = []
        for l in data.get("logs", []):
            if isinstance(l, dict):
                logs.append(
                    LogEntry(
                        level=l.get("level", "INFO"),
                        message=l.get("message", ""),
                        stack_trace=l.get("stackTrace"),
                        timestamp=l.get("timestamp"),
                    )
                )

        return IngestClientResponse(
            status=status,
            http_status_code=status_code,
            raw_json=data,
            error=error_msg,
            timestamp=timestamp,
            academic_session=academic_session,
            department=department,
            subject_area=subject_area,
            summary=summary,
            courses_imported=courses_imported,
            logs=logs,
        )
