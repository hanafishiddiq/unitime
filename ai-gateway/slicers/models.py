"""
Data structures and models for the UniTime AI Ingestion Gateway Slicer & Chunker subsystem.

Provides standardized, strongly-typed representations for sliced document artifacts
including PDF/image page slices, tabular row chunks, and narrative text chunks.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


class PageDimensions(BaseModel):
    """Spatial pixel dimensions of a rendered document page or image."""

    model_config = ConfigDict(frozen=True)

    width: int = Field(..., description="Width in pixels at the specified DPI", ge=1)
    height: int = Field(..., description="Height in pixels at the specified DPI", ge=1)

    def as_tuple(self) -> Tuple[int, int]:
        """Return dimensions as (width, height) tuple."""
        return (self.width, self.height)


class PageSlice(BaseModel):
    """
    Represents a single page slice extracted from a PDF or single-page image.

    Designed for 1-page-at-a-time streaming ingestion into Vision-Language Models (VLMs)
    or OCR engines, keeping memory footprint minimal even for 500+ page documents.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    page_index: int = Field(
        ...,
        description="0-indexed page index within the source document",
        ge=0,
    )
    page_number: int = Field(
        ...,
        description="1-indexed human-readable page number",
        ge=1,
    )
    total_pages: int = Field(
        ...,
        description="Total page count of the source document",
        ge=1,
    )
    dimensions: PageDimensions = Field(
        ...,
        description="Rendered image pixel dimensions (width, height)",
    )
    dpi: int = Field(
        default=200,
        description="Resolution (dots per inch) used when rendering the page",
        ge=72,
        le=600,
    )
    format: str = Field(
        default="png",
        description="Image encoding format, e.g., 'png', 'jpeg', 'webp'",
    )
    image_path: Optional[Path] = Field(
        default=None,
        description="Path to rendered image file on disk (temporary or persistent)",
    )
    image_bytes: Optional[bytes] = Field(
        default=None,
        repr=False,
        description="Raw image bytes in memory (optional for streaming or API payload)",
    )
    source_file: Optional[Path] = Field(
        default=None,
        description="Path to the original source PDF or image document",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional contextual metadata (e.g. extracted text, OCR, layout info)",
    )

    def save_image(self, dest_path: Path | str, overwrite: bool = True) -> Path:
        """
        Persist or copy the page slice image to a specified destination path.

        Args:
            dest_path: Target destination file path.
            overwrite: Whether to overwrite existing file at destination.

        Returns:
            The resolved Path of the saved image.

        Raises:
            FileNotFoundError: If neither image_bytes nor image_path is available.
            FileExistsError: If destination exists and overwrite is False.
        """
        target = Path(dest_path).resolve()
        if target.exists() and not overwrite:
            raise FileExistsError(f"Destination image already exists at {target}")

        target.parent.mkdir(parents=True, exist_ok=True)

        if self.image_bytes is not None:
            target.write_bytes(self.image_bytes)
            self.image_path = target
            return target

        if self.image_path is not None and self.image_path.exists():
            shutil.copyfile(self.image_path, target)
            return target

        raise FileNotFoundError(
            f"Cannot save PageSlice {self.page_number}/{self.total_pages}: "
            "neither valid image_bytes nor existing image_path is present."
        )

    def to_dict(self) -> Dict[str, Any]:
        """Export slice metadata as serializable dictionary (omitting raw bytes)."""
        data = self.model_dump(exclude={"image_bytes"})
        data["dimensions"] = self.dimensions.as_tuple()
        if self.image_path:
            data["image_path"] = str(self.image_path)
        if self.source_file:
            data["source_file"] = str(self.source_file)
        return data


class TableChunk(BaseModel):
    """
    Represents a batched slice of rows from a tabular sheet with preserved headers.

    Guarantees that every chunk contains the complete table header definition,
    ensuring downstream LLMs retain full column semantics without hallucinating schemas.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sheet_name: str = Field(
        ...,
        description="Name of the spreadsheet sheet or CSV source label",
    )
    chunk_index: int = Field(
        ...,
        description="0-indexed chunk batch number for this sheet",
        ge=0,
    )
    total_chunks: int = Field(
        ...,
        description="Total chunks generated for this sheet",
        ge=1,
    )
    start_row: int = Field(
        ...,
        description="0-indexed start index of data rows in this chunk (excluding header)",
        ge=0,
    )
    end_row: int = Field(
        ...,
        description="0-indexed end index of data rows in this chunk (exclusive)",
        ge=0,
    )
    total_rows: int = Field(
        ...,
        description="Total data rows present in this sheet",
        ge=0,
    )
    headers: List[str] = Field(
        ...,
        description="Sanitized column headers prepended to this chunk",
    )
    rows: List[List[str]] = Field(
        ...,
        description="Batch data rows contained in this chunk",
    )
    markdown: str = Field(
        ...,
        description="Formatted markdown table with headers and separators ready for LLM prompt",
    )
    csv_content: str = Field(
        ...,
        description="Formatted CSV string with headers and escaped cell values",
    )
    source_file: Optional[Path] = Field(
        default=None,
        description="Path to original Excel or CSV source file",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional contextual metadata (e.g. academic prodi, semester)",
    )

    @property
    def row_count(self) -> int:
        """Number of data rows in this chunk."""
        return len(self.rows)

    def to_dict(self) -> Dict[str, Any]:
        """Export chunk as serializable dictionary."""
        data = self.model_dump()
        if self.source_file:
            data["source_file"] = str(self.source_file)
        return data


class TextChunk(BaseModel):
    """
    Represents a semantic chunk of narrative text, memo, or curriculum guidelines.

    Parsed along semantic boundaries (headers, departments, faculties, paragraphs)
    to prevent splitting critical academic rules across chunk seams.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    chunk_index: int = Field(
        ...,
        description="0-indexed sequence number of this text chunk",
        ge=0,
    )
    total_chunks: int = Field(
        ...,
        description="Total number of text chunks extracted from source document",
        ge=1,
    )
    title: Optional[str] = Field(
        default=None,
        description="Detected section title, header, or department boundary (e.g. 'FAKULTAS TEKNIK')",
    )
    content: str = Field(
        ...,
        description="Clean narrative text content of this chunk",
    )
    char_count: int = Field(
        ...,
        description="Length of content in characters",
        ge=0,
    )
    token_estimate: int = Field(
        ...,
        description="Heuristic token estimation (~ char_count / 4)",
        ge=0,
    )
    source_file: Optional[Path] = Field(
        default=None,
        description="Path to source document",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed section hierarchy, boundary tags, or paragraph line ranges",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Export chunk as serializable dictionary."""
        data = self.model_dump()
        if self.source_file:
            data["source_file"] = str(self.source_file)
        return data
