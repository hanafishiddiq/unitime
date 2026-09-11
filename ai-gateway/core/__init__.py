"""UniTime AI Ingestion Gateway - Core Module Exports."""

from .client import (
    CourseImportSummary,
    IngestClientResponse,
    IngestSummary,
    LogEntry,
    UniTimeClient,
    UniTimeClientError,
    UniTimeConnectionError,
    UniTimeResponseError,
)
from .extractor import (
    AnthropicExtractor,
    BaseExtractor,
    ExtractionError,
    ExtractionParsingError,
    ExtractionResult,
    GeminiExtractor,
    MockExtractor,
    OpenAIExtractor,
    get_extractor,
    load_system_prompt,
    repair_and_parse_json,
)
from .merger import Merger
from .slicer import DocumentSlicer, SliceChunk
from .validator import (
    ValidationErrorDetail,
    ValidationResult,
    Validator,
)

__all__ = [
    # Validator
    "Validator",
    "ValidationResult",
    "ValidationErrorDetail",
    # Merger
    "Merger",
    # Extractor
    "BaseExtractor",
    "MockExtractor",
    "GeminiExtractor",
    "OpenAIExtractor",
    "AnthropicExtractor",
    "get_extractor",
    "ExtractionResult",
    "ExtractionError",
    "ExtractionParsingError",
    "load_system_prompt",
    "repair_and_parse_json",
    # Client
    "UniTimeClient",
    "IngestClientResponse",
    "IngestSummary",
    "CourseImportSummary",
    "LogEntry",
    "UniTimeClientError",
    "UniTimeConnectionError",
    "UniTimeResponseError",
    # Slicer
    "DocumentSlicer",
    "SliceChunk",
]
