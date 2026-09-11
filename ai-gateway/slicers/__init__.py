"""
UniTime AI Ingestion Gateway - Slicers & Chunkers Subsystem.

Provides high-performance document parsing and spatial chunking:
- PDFSlicer: Renders multi-page PDFs strictly 1 page at a time to high-res images (200-300 DPI)
  and seamlessly ingests standalone image files.
- TableSlicer: Multi-sheet Excel (.xlsx, .xls) and CSV parser with smart row batching and
  guaranteed header preservation in markdown and CSV formats.
- TextSlicer: Semantic narrative parser splitting curriculum memos by headers, department boundaries,
  and paragraphs.
"""

from __future__ import annotations

from .models import (
    PageDimensions,
    PageSlice,
    TableChunk,
    TextChunk,
)
from .pdf_slicer import PDFSlicer
from .table_slicer import TableSlicer
from .text_slicer import TextSlicer

__all__ = [
    "PageDimensions",
    "PageSlice",
    "TableChunk",
    "TextChunk",
    "PDFSlicer",
    "TableSlicer",
    "TextSlicer",
]
