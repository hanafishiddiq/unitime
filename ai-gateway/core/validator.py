"""UniTime AI Ingestion Gateway - Payload Validator.

Validates partial and full academic curriculum payloads against the official
UniTime Smart Ingest JSON Schema (Draft 2020-12) and applies domain-specific
semantic checks.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

logger = logging.getLogger(__name__)

def _resolve_default_schema_path() -> Path:
    """Find schema path across local dev, Docker container, or custom env."""
    env_path = os.getenv("UNITIME_SCHEMA_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    candidates = [
        Path(__file__).resolve().parent.parent / "schema" / "unitime-smart-ingest-schema.json",
        Path(__file__).resolve().parent.parent.parent / "Documentation" / "ai-integration" / "unitime-smart-ingest-schema.json",
        Path("/app/schema/unitime-smart-ingest-schema.json"),
        Path("/Documentation/ai-integration/unitime-smart-ingest-schema.json"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


DEFAULT_SCHEMA_PATH = _resolve_default_schema_path()


@dataclass
class ValidationErrorDetail:
    """Detailed information for a single validation failure."""

    path: str
    message: str
    validator: str
    invalid_value: Any = None

    def format_line(self) -> str:
        """Format the error as a readable single line."""
        location = f"[{self.path}]" if self.path else "[root]"
        return f"{location} {self.message}"


@dataclass
class ValidationResult:
    """Structured result of schema and semantic validation."""

    is_valid: bool
    errors: List[ValidationErrorDetail] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def error_messages(self) -> List[str]:
        """Return human-readable line-by-line error messages."""
        return [err.format_line() for err in self.errors]

    def summary(self) -> str:
        """Return a formatted multi-line summary of the result."""
        status = "VALID" if self.is_valid else "INVALID"
        lines = [
            f"Validation Status: {status}",
            f"Errors: {len(self.errors)}",
            f"Warnings: {len(self.warnings)}",
        ]
        if self.errors:
            lines.append("Error Details:")
            for err in self.errors:
                lines.append(f"  - {err.format_line()}")
        if self.warnings:
            lines.append("Warnings:")
            for warn in self.warnings:
                lines.append(f"  * {warn}")
        return "\n".join(lines)


class Validator:
    """Validates UniTime smart ingest payloads against JSON schema and domain rules."""

    def __init__(
        self,
        schema_path: Optional[Path | str] = None,
        strict_semantics: bool = False,
    ) -> None:
        """Initialize validator with schema file.

        Args:
            schema_path: Optional custom path to unitime-smart-ingest-schema.json.
            strict_semantics: If True, semantic warnings (like invalid references)
                are elevated to validation errors.
        """
        self.strict_semantics = strict_semantics
        self.schema_path = self._resolve_schema_path(schema_path)
        self.schema = self._load_schema(self.schema_path)

        Draft202012Validator.check_schema(self.schema)
        self._full_validator = Draft202012Validator(self.schema)
        self._partial_validator = self._build_partial_validator(self.schema)

    @staticmethod
    def _resolve_schema_path(custom_path: Optional[Path | str]) -> Path:
        """Resolve path to the JSON schema file."""
        if custom_path is not None:
            resolved = Path(custom_path).resolve()
            if not resolved.is_file():
                raise FileNotFoundError(f"Custom schema not found at: {resolved}")
            return resolved

        if DEFAULT_SCHEMA_PATH.is_file():
            return DEFAULT_SCHEMA_PATH

        env_path = os.getenv("UNITIME_SCHEMA_PATH")
        if env_path:
            resolved = Path(env_path).resolve()
            if resolved.is_file():
                return resolved

        raise FileNotFoundError(
            f"UniTime schema not found at default location: {DEFAULT_SCHEMA_PATH}"
        )

    @staticmethod
    def _load_schema(path: Path) -> Dict[str, Any]:
        """Load and parse the JSON schema file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            raise RuntimeError(f"Failed to read schema file at {path}: {exc}") from exc

    @staticmethod
    def _build_partial_validator(base_schema: Dict[str, Any]) -> Draft202012Validator:
        """Construct a validator for partial payloads with relaxed root requirements."""
        partial_schema = copy.deepcopy(base_schema)
        partial_schema.pop("required", None)
        return Draft202012Validator(partial_schema)

    def validate(self, payload: Dict[str, Any]) -> ValidationResult:
        """Validate a full ingest payload against the complete schema and semantic rules."""
        if not isinstance(payload, dict):
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationErrorDetail(
                        path="[root]",
                        message=f"Payload must be a JSON object (dict), got {type(payload).__name__}",
                        validator="type",
                    )
                ],
            )

        errors: List[ValidationErrorDetail] = []
        for err in sorted(self._full_validator.iter_errors(payload), key=lambda e: e.path):
            errors.append(self._format_jsonschema_error(err))

        warnings: List[str] = []
        semantic_errors, semantic_warnings = self._validate_semantics(payload)

        if self.strict_semantics:
            errors.extend(semantic_errors)
            errors.extend(
                [
                    ValidationErrorDetail(
                        path="[semantics]",
                        message=warn,
                        validator="semantic_strict",
                    )
                    for warn in semantic_warnings
                ]
            )
        else:
            errors.extend(semantic_errors)
            warnings.extend(semantic_warnings)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def validate_partial(self, partial_payload: Dict[str, Any]) -> ValidationResult:
        """Validate a partial payload or chunk (e.g. single page extracted data)."""
        if not isinstance(partial_payload, dict):
            return ValidationResult(
                is_valid=False,
                errors=[
                    ValidationErrorDetail(
                        path="[root]",
                        message=f"Partial payload must be a dict, got {type(partial_payload).__name__}",
                        validator="type",
                    )
                ],
            )

        errors: List[ValidationErrorDetail] = []
        for err in sorted(self._partial_validator.iter_errors(partial_payload), key=lambda e: e.path):
            errors.append(self._format_jsonschema_error(err))

        warnings: List[str] = []
        semantic_errors, semantic_warnings = self._validate_semantics(partial_payload)

        if self.strict_semantics:
            errors.extend(semantic_errors)
            errors.extend(
                [
                    ValidationErrorDetail(
                        path="[semantics]",
                        message=warn,
                        validator="semantic_strict",
                    )
                    for warn in semantic_warnings
                ]
            )
        else:
            errors.extend(semantic_errors)
            warnings.extend(semantic_warnings)

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _format_jsonschema_error(err: ValidationError) -> ValidationErrorDetail:
        """Transform a jsonschema ValidationError into a clean ValidationErrorDetail."""
        path_segments: List[str] = []
        for elem in err.absolute_path:
            if isinstance(elem, int):
                path_segments.append(f"[{elem}]")
            else:
                if path_segments:
                    path_segments.append(f".{elem}")
                else:
                    path_segments.append(str(elem))

        formatted_path = "".join(path_segments)
        return ValidationErrorDetail(
            path=formatted_path,
            message=err.message,
            validator=err.validator or "unknown",
            invalid_value=err.instance if not isinstance(err.instance, (dict, list)) else None,
        )

    def _validate_semantics(
        self, payload: Dict[str, Any]
    ) -> tuple[List[ValidationErrorDetail], List[str]]:
        """Run deep semantic consistency checks on the payload."""
        errors: List[ValidationErrorDetail] = []
        warnings: List[str] = []

        courses = payload.get("courses", [])
        if not isinstance(courses, list):
            return errors, warnings

        # Track existing course numbers and class section keys
        existing_classes: set[tuple[str, str]] = set()  # (courseNumber, sectionName)
        seen_courses: set[str] = set()

        for c_idx, course in enumerate(courses):
            if not isinstance(course, dict):
                continue
            c_num = course.get("courseNumber")
            if not c_num:
                continue

            if c_num in seen_courses:
                warnings.append(
                    f"Duplicate courseNumber '{c_num}' detected in courses[{c_idx}]. Courses should be consolidated."
                )
            seen_courses.add(c_num)

            for cfg_idx, config in enumerate(course.get("configurations", [])):
                if not isinstance(config, dict):
                    continue
                for sp_idx, subpart in enumerate(config.get("subparts", [])):
                    if not isinstance(subpart, dict):
                        continue
                    for cl_idx, cls_obj in enumerate(subpart.get("classes", [])):
                        if not isinstance(cls_obj, dict):
                            continue
                        sec_name = cls_obj.get("sectionName")
                        if sec_name:
                            existing_classes.add((c_num, sec_name))

                        # Check instructor teaching shares
                        instructors = cls_obj.get("instructors", [])
                        if isinstance(instructors, list) and instructors:
                            shares = [
                                ins.get("sharePercentage")
                                for ins in instructors
                                if isinstance(ins, dict)
                                and isinstance(ins.get("sharePercentage"), (int, float))
                            ]
                            if len(shares) == len(instructors):
                                total_share = sum(shares)
                                if total_share != 100:
                                    warnings.append(
                                        f"Course '{c_num}' Section '{sec_name}': instructor share percentages sum to {total_share}%, expected 100%."
                                    )

                        # Check time preferences logic (startTime < endTime)
                        time_prefs = cls_obj.get("timePreferences", [])
                        if isinstance(time_prefs, list):
                            for tp in time_prefs:
                                if isinstance(tp, dict):
                                    st = tp.get("startTime", "")
                                    et = tp.get("endTime", "")
                                    if st and et and st >= et:
                                        errors.append(
                                            ValidationErrorDetail(
                                                path=f"courses[{c_idx}].configurations[{cfg_idx}].subparts[{sp_idx}].classes[{cl_idx}].timePreferences",
                                                message=f"startTime '{st}' must be earlier than endTime '{et}'.",
                                                validator="time_order",
                                            )
                                        )

        # Validate distribution constraints refer to known courses/classes
        constraints = payload.get("distributionConstraints", [])
        if isinstance(constraints, list):
            for idx, dc in enumerate(constraints):
                if not isinstance(dc, dict):
                    continue
                dc_classes = dc.get("classes", [])
                if isinstance(dc_classes, list):
                    for ref_idx, ref in enumerate(dc_classes):
                        if not isinstance(ref, dict):
                            continue
                        rc_num = ref.get("courseNumber")
                        r_sec = ref.get("sectionName")
                        if rc_num and r_sec and (rc_num, r_sec) not in existing_classes:
                            warnings.append(
                                f"distributionConstraints[{idx}].classes[{ref_idx}] references undefined class section '{rc_num} {r_sec}'."
                            )

        return errors, warnings
