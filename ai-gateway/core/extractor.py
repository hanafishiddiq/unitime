"""UniTime AI Ingestion Gateway - Multi-Modal Extractor.

Extracts structured academic timetabling JSON payloads from text and page images
using LLM providers (Gemini, OpenAI, Anthropic) or a deterministic Mock mode.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "Documentation"
    / "ai-integration"
    / "ai-system-prompt.md"
)


class ExtractionError(Exception):
    """Base exception for extraction failures."""


class ExtractionParsingError(ExtractionError):
    """Exception raised when LLM output cannot be parsed into valid JSON."""


@dataclass
class ExtractionResult:
    """Encapsulates the structured output and metadata of an extraction operation."""

    payload: Dict[str, Any]
    provider: str
    model: str
    raw_response: str
    tokens_used: Optional[int] = None
    warnings: List[str] = field(default_factory=list)


def load_system_prompt(custom_path: Optional[Path | str] = None) -> str:
    """Load the UniTime system prompt from file or fallback to embedded instructions."""
    candidates = [
        Path(custom_path) if custom_path else None,
        DEFAULT_SYSTEM_PROMPT_PATH,
        Path(__file__).resolve().parent.parent / "schema" / "ai-system-prompt.md",
        Path("/app/schema/ai-system-prompt.md"),
        Path("/Documentation/ai-integration/ai-system-prompt.md"),
    ]
    for p in candidates:
        if p and p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("Failed to read system prompt from %s: %s", p, exc)

    return (
        "You are UniTime Ingestion AI. Extract academic curriculum and class schedules "
        "into strict JSON adhering to unitime-smart-ingest-schema.json. "
        "Return pure JSON without markdown fences."
    )


def repair_and_parse_json(raw_text: str) -> Dict[str, Any]:
    """Extract and repair JSON from raw LLM output strings."""
    if not raw_text or not raw_text.strip():
        raise ExtractionParsingError("Empty response received from LLM.")

    text = raw_text.strip()

    # 1. Remove markdown code block fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    # 2. Extract substring between first '{' and last '}'
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        text = text[first_brace : last_brace + 1]

    # 3. Direct parse attempt
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 4. Apply common structural repairs
    repaired = text
    # Replace single quotes handling empty strings, arrays, escaped single quotes, keys, values
    repaired = re.sub(r"(?<=[\:\,\{\[\s])'((?:\\.|[^'\\])*)'", r'"\1"', repaired)
    repaired = repaired.replace("\\'", "'")
    # Remove trailing commas before } or ]
    repaired = re.sub(r",\s*([\]}])", r"\1", repaired)
    # Fix python literals
    repaired = re.sub(r"\bTrue\b", "true", repaired)
    repaired = re.sub(r"\bFalse\b", "false", repaired)
    repaired = re.sub(r"\bNone\b", "null", repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        snippet = text[:200] + ("..." if len(text) > 200 else "")
        raise ExtractionParsingError(
            f"Failed to parse LLM response into JSON: {exc}. Snippet: {snippet}"
        ) from exc


def _build_vision_user_prompt(
    base_prompt: str, context: Optional[Dict[str, Any]] = None
) -> str:
    """Include document filename and page/chunk metadata into vision prompt."""
    if not context:
        return base_prompt

    doc_name = (
        context.get("sourceDocumentName")
        or context.get("document_name")
        or context.get("filename")
    )
    page = context.get("page")
    total_pages = context.get("total_pages")
    chunk_id = context.get("chunk_id")
    total_chunks = context.get("total_chunks")

    context_parts: List[str] = []
    if doc_name:
        context_parts.append(f"Source Document: {doc_name}")

    if page is not None:
        if total_pages:
            context_parts.append(f"Page: {page}/{total_pages}")
        else:
            context_parts.append(f"Page: {page}")
    elif chunk_id is not None:
        if total_chunks:
            context_parts.append(f"Chunk/Page: {chunk_id}/{total_chunks}")
        else:
            context_parts.append(f"Chunk/Page: {chunk_id}")

    if context_parts:
        header = " | ".join(context_parts)
        return f"{header}\n\n{base_prompt}"
    return base_prompt


class BaseExtractor(ABC):
    """Abstract interface for LLM extraction providers."""

    def __init__(self, system_prompt: Optional[str] = None) -> None:
        self.system_prompt = system_prompt or load_system_prompt()

    @abstractmethod
    def extract_text(
        self, text_chunk: str, context: Optional[Dict[str, Any]] = None
    ) -> ExtractionResult:
        """Extract structured payload from a text chunk."""

    @abstractmethod
    def extract_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """Extract structured payload from a page image."""


class MockExtractor(BaseExtractor):
    """Deterministic mock extractor for unit tests, offline dry-runs, and CI."""

    def __init__(self, system_prompt: Optional[str] = None) -> None:
        super().__init__(system_prompt)
        self.name = "mock"
        self.model = "mock-engine-v1"

    def extract_text(
        self, text_chunk: str, context: Optional[Dict[str, Any]] = None
    ) -> ExtractionResult:
        payload = self._generate_mock_payload(text_chunk, context)
        raw_json = json.dumps(payload, indent=2)
        return ExtractionResult(
            payload=payload,
            provider="mock",
            model=self.model,
            raw_response=raw_json,
            tokens_used=120,
        )

    def extract_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        dummy_text = f"Mock Image ({len(image_bytes)} bytes, {mime_type})"
        return self.extract_text(dummy_text, context)

    @staticmethod
    def _generate_mock_payload(
        text_chunk: str, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generate schema-compliant payload matching contents of the input chunk."""
        source_doc = (
            context.get("sourceDocumentName", "input_data.txt")
            if context
            else "input_data.txt"
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        courses: List[Dict[str, Any]] = []

        # Detect courses mentioned in text or return standard mock courses
        has_if2110 = "IF2110" in text_chunk or "Algoritma" in text_chunk
        has_if2120 = "IF2120" in text_chunk or "Diskrit" in text_chunk
        has_if3150 = "IF3150" in text_chunk or "Manajemen Proyek" in text_chunk

        # If no specific recognized course is present, default to IF2110
        if not (has_if2110 or has_if2120 or has_if3150):
            has_if2110 = True

        if has_if2110:
            courses.append(
                {
                    "courseNumber": "IF2110",
                    "title": "Algoritma dan Struktur Data",
                    "credit": {
                        "units": 4,
                        "creditType": "collegiate",
                        "creditUnitType": "sks",
                        "format": "fixedUnit",
                    },
                    "projectedDemand": 90,
                    "consentType": "None",
                    "scheduleBookNote": "Mata kuliah wajib semester 3",
                    "controlling": True,
                    "configurations": [
                        {
                            "name": "Teori + Praktikum",
                            "durationType": "MIN_PER_WEEK",
                            "instructionalMethod": "Standard",
                            "subparts": [
                                {
                                    "type": "Lecture",
                                    "minPerWeek": 150,
                                    "classes": [
                                        {
                                            "sectionName": "K01",
                                            "capacity": 45,
                                            "roomRatio": 1.0,
                                            "scheduleNote": "Kelas Paralel 1",
                                            "instructors": [
                                                {
                                                    "id": "198503152010122001",
                                                    "name": "Dr. Eng. Ayu Pratama, S.T., M.T.",
                                                    "email": "ayu.pratama@univ.ac.id",
                                                    "isLead": True,
                                                    "sharePercentage": 50,
                                                },
                                                {
                                                    "id": "197808202003121002",
                                                    "name": "Budi Raharjo, S.T., M.Kom.",
                                                    "email": "budi.raharjo@univ.ac.id",
                                                    "isLead": False,
                                                    "sharePercentage": 50,
                                                },
                                            ],
                                            "timePreferences": [
                                                {
                                                    "days": "M",
                                                    "startTime": "07:00",
                                                    "endTime": "09:30",
                                                    "level": "REQUIRED",
                                                }
                                            ],
                                            "roomPreferences": [
                                                {
                                                    "building": "Labtek V",
                                                    "roomNumber": "7601",
                                                    "feature": "Projector",
                                                    "level": "REQUIRED",
                                                }
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "type": "Lab",
                                    "minPerWeek": 120,
                                    "parentSubpartType": "Lecture",
                                    "classes": [
                                        {
                                            "sectionName": "L01",
                                            "capacity": 25,
                                            "roomRatio": 1.0,
                                            "parentClassSection": "K01",
                                            "scheduleNote": "Praktikum Lab 1",
                                            "instructors": [
                                                {
                                                    "id": "198503152010122001",
                                                    "name": "Dr. Eng. Ayu Pratama, S.T., M.T.",
                                                    "email": "ayu.pratama@univ.ac.id",
                                                    "isLead": True,
                                                    "sharePercentage": 100,
                                                }
                                            ],
                                            "timePreferences": [
                                                {
                                                    "days": "T",
                                                    "startTime": "13:00",
                                                    "endTime": "15:00",
                                                    "level": "REQUIRED",
                                                }
                                            ],
                                            "roomPreferences": [
                                                {
                                                    "building": "Labtek V",
                                                    "roomNumber": "Lab-1",
                                                    "feature": "ComputerLab",
                                                    "level": "REQUIRED",
                                                }
                                            ],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            )

        if has_if2120:
            courses.append(
                {
                    "courseNumber": "IF2120",
                    "title": "Matematika Diskrit",
                    "credit": {
                        "units": 3,
                        "creditType": "collegiate",
                        "creditUnitType": "sks",
                        "format": "fixedUnit",
                    },
                    "projectedDemand": 100,
                    "consentType": "None",
                    "scheduleBookNote": "Mata kuliah dasar informatika",
                    "controlling": True,
                    "configurations": [
                        {
                            "name": "Default",
                            "durationType": "MIN_PER_WEEK",
                            "instructionalMethod": "Standard",
                            "subparts": [
                                {
                                    "type": "Lecture",
                                    "minPerWeek": 150,
                                    "classes": [
                                        {
                                            "sectionName": "K01",
                                            "capacity": 50,
                                            "roomRatio": 1.0,
                                            "scheduleNote": "Kelas Reguler A",
                                            "instructors": [
                                                {
                                                    "id": "197505121998021001",
                                                    "name": "Prof. Dr. Hendra Wijaya",
                                                    "email": "hendra.w@univ.ac.id",
                                                    "isLead": True,
                                                    "sharePercentage": 100,
                                                }
                                            ],
                                            "timePreferences": [
                                                {
                                                    "days": "T",
                                                    "startTime": "07:00",
                                                    "endTime": "09:30",
                                                    "level": "REQUIRED",
                                                }
                                            ],
                                            "roomPreferences": [
                                                {
                                                    "building": "GK-1",
                                                    "roomNumber": "9001",
                                                    "level": "REQUIRED",
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            )

        distribution_constraints = [
            {
                "type": "PRECEDENCE",
                "level": "REQUIRED",
                "courseNumber": "IF2110",
                "classes": [
                    {
                        "courseNumber": "IF2110",
                        "subpartType": "Lecture",
                        "sectionName": "K01",
                    },
                    {
                        "courseNumber": "IF2110",
                        "subpartType": "Lab",
                        "sectionName": "L01",
                    },
                ],
                "structure": "Progressive",
                "note": "Kuliah teori harus mendahului praktikum",
            }
        ]

        return {
            "ingestControl": {
                "mode": "incremental",
                "actionOnDuplicate": "upsert",
                "sourceDocumentName": source_doc,
                "extractedAt": now_iso,
                "validationStrictness": "strict",
            },
            "academicSession": {
                "year": "2024-2025",
                "term": "Ganjil",
                "campus": "Kampus Ganesha",
            },
            "department": {
                "code": "IF",
                "name": "Teknik Informatika",
            },
            "subjectArea": {
                "abbreviation": "IF",
                "title": "Teknik Informatika",
                "externalId": "SA_IF_01",
            },
            "courses": courses,
            "distributionConstraints": distribution_constraints,
        }


class GeminiExtractor(BaseExtractor):
    """Google Gemini LLM extractor supporting multimodal text and vision."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        super().__init__(system_prompt)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable or argument is required.")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-1.5-pro-latest")
        raw_base = (
            base_url
            or os.getenv("GEMINI_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        self.endpoint = (
            f"{raw_base}/models/{self.model}:generateContent?key={self.api_key}"
        )

    def extract_text(
        self, text_chunk: str, context: Optional[Dict[str, Any]] = None
    ) -> ExtractionResult:
        user_prompt = f"Source Document: {context.get('sourceDocumentName', 'Unknown')}\n\nAcademic Data:\n{text_chunk}"
        body = {
            "system_instruction": {"parts": [{"text": self.system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        }
        return self._send_request(body)

    def extract_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        user_prompt = _build_vision_user_prompt(
            "Extract all courses, schedules, instructors, and preferences from this document image.",
            context,
        )
        body = {
            "system_instruction": {"parts": [{"text": self.system_prompt}]},
            "contents": [
                {
                    "parts": [
                        {"text": user_prompt},
                        {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        }
        return self._send_request(body)

    def _send_request(self, body: Dict[str, Any]) -> ExtractionResult:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(self.endpoint, json=body)
            if resp.status_code != 200:
                raise ExtractionError(
                    f"Gemini API returned HTTP {resp.status_code}: {resp.text}"
                )
            data = resp.json()

        try:
            candidates = data.get("candidates", [])
            text_content = candidates[0]["content"]["parts"][0]["text"]
        except (IndexError, KeyError) as exc:
            raise ExtractionError(f"Unexpected Gemini response structure: {data}") from exc

        payload = repair_and_parse_json(text_content)
        return ExtractionResult(
            payload=payload,
            provider="gemini",
            model=self.model,
            raw_response=text_content,
        )


class OpenAIExtractor(BaseExtractor):
    """OpenAI GPT extractor supporting text and vision via standard chat completions."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        super().__init__(system_prompt)
        raw_base = (
            base_url
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or os.getenv("LLM_ENDPOINT")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        # If custom base_url (like Antigravity Gateway) is used, default api_key to 'antigravity'
        default_key = "antigravity" if any(h in raw_base for h in ("host.docker.internal", "localhost", "127.0.0.1", "172.")) else None
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or default_key
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable or argument is required.")
        self.model = model or os.getenv("OPENAI_MODEL") or os.getenv("DEFAULT_LLM_MODEL") or os.getenv("LLM_MODEL", "gemini-flash-latest")
        if raw_base.endswith("/chat/completions"):
            self.endpoint = raw_base
        else:
            self.endpoint = f"{raw_base}/chat/completions"

    def extract_text(
        self, text_chunk: str, context: Optional[Dict[str, Any]] = None
    ) -> ExtractionResult:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Extract the following academic schedule into UniTime JSON:\n{text_chunk}",
            },
        ]
        body = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        return self._send_request(body)

    def extract_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64_data}"
        user_prompt = _build_vision_user_prompt(
            "Extract all academic courses and timetables into UniTime JSON format.",
            context,
        )
        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ]
        body = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        return self._send_request(body)

    def _send_request(self, body: Dict[str, Any]) -> ExtractionResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(self.endpoint, headers=headers, json=body)
            if resp.status_code != 200:
                raise ExtractionError(
                    f"OpenAI API returned HTTP {resp.status_code}: {resp.text}"
                )
            data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens")
        except (KeyError, IndexError) as exc:
            raise ExtractionError(f"Unexpected OpenAI response structure: {data}") from exc

        payload = repair_and_parse_json(content)
        return ExtractionResult(
            payload=payload,
            provider="openai",
            model=self.model,
            raw_response=content,
            tokens_used=tokens,
        )


class AnthropicExtractor(BaseExtractor):
    """Anthropic Claude extractor supporting text and vision messages."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        super().__init__(system_prompt)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("LLM_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable or argument is required.")
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        raw_base = (
            base_url
            or os.getenv("ANTHROPIC_BASE_URL")
            or os.getenv("LLM_BASE_URL")
            or "https://api.anthropic.com"
        ).rstrip("/")
        if raw_base.endswith("/messages"):
            self.endpoint = raw_base
        elif raw_base.endswith("/v1"):
            self.endpoint = f"{raw_base}/messages"
        else:
            self.endpoint = f"{raw_base}/v1/messages"

    def extract_text(
        self, text_chunk: str, context: Optional[Dict[str, Any]] = None
    ) -> ExtractionResult:
        body = {
            "model": self.model,
            "system": self.system_prompt,
            "max_tokens": 4096,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": f"Extract following schedule into UniTime JSON:\n{text_chunk}",
                }
            ],
        }
        return self._send_request(body)

    def extract_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/png",
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        user_prompt = _build_vision_user_prompt(
            "Extract all courses, classes, instructors, and preferences into UniTime JSON format.",
            context,
        )
        body = {
            "model": self.model,
            "system": self.system_prompt,
            "max_tokens": 4096,
            "temperature": 0.1,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": user_prompt,
                        },
                    ],
                }
            ],
        }
        return self._send_request(body)

    def _send_request(self, body: Dict[str, Any]) -> ExtractionResult:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(self.endpoint, headers=headers, json=body)
            if resp.status_code != 200:
                raise ExtractionError(
                    f"Anthropic API returned HTTP {resp.status_code}: {resp.text}"
                )
            data = resp.json()

        try:
            content_blocks = data.get("content", [])
            text = "".join(b.get("text", "") for b in content_blocks)
        except Exception as exc:
            raise ExtractionError(f"Unexpected Anthropic response structure: {data}") from exc

        payload = repair_and_parse_json(text)
        return ExtractionResult(
            payload=payload,
            provider="anthropic",
            model=self.model,
            raw_response=text,
        )


def get_extractor(
    provider: str = "mock",
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    base_url: Optional[str] = None,
) -> BaseExtractor:
    """Factory creating an extractor instance based on provider name."""
    prov = (provider or "mock").strip().lower()

    if prov == "mock":
        return MockExtractor(system_prompt=system_prompt)
    if prov in ("antigravity", "antigravity-gateway", "openai", "gpt", "custom", "openrouter", "ollama", "vllm", "proxy", "local"):
        return OpenAIExtractor(api_key=api_key, model=model, system_prompt=system_prompt, base_url=base_url)
    if prov in ("gemini", "google"):
        # If GEMINI_API_KEY is not set but OPENAI_BASE_URL is configured (e.g. Antigravity Gateway proxying Gemini), route to OpenAIExtractor!
        if not (api_key or os.getenv("GEMINI_API_KEY")) and os.getenv("OPENAI_BASE_URL"):
            target_model = model or os.getenv("OPENAI_MODEL") or "gemini-flash-latest"
            return OpenAIExtractor(
                api_key=api_key or os.getenv("OPENAI_API_KEY") or "antigravity",
                model=target_model,
                system_prompt=system_prompt,
                base_url=base_url or os.getenv("OPENAI_BASE_URL"),
            )
        return GeminiExtractor(api_key=api_key, model=model, system_prompt=system_prompt, base_url=base_url)
    if prov in ("anthropic", "claude"):
        return AnthropicExtractor(api_key=api_key, model=model, system_prompt=system_prompt, base_url=base_url)

    raise ValueError(
        f"Unsupported provider '{provider}'. Must be one of: 'mock', 'gemini', 'openai', 'anthropic', or OpenAI-compatible ('custom', 'openrouter', 'ollama', 'vllm', 'proxy')."
    )
