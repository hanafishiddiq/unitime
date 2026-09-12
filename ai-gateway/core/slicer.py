"""UniTime AI Ingestion Gateway - Document Slicer.

Chunks and slices PDF documents, Excel spreadsheets, and text memos into
manageable page or section-level units for LLM extraction.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import openpyxl
import pandas as pd
import pymupdf  # fitz

logger = logging.getLogger(__name__)


@dataclass
class SliceChunk:
    """A sliced unit of input document (text chunk or page image)."""

    chunk_id: int
    total_chunks: int
    chunk_type: str  # "text" or "image"
    source_filename: str
    text_content: Optional[str] = None
    image_bytes: Optional[bytes] = None
    mime_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


try:
    from slicers import PDFSlicer, TableSlicer, TextSlicer

    HAS_SLICERS_PKG = True
except ImportError:
    HAS_SLICERS_PKG = False


def _dataframe_to_text(df: pd.DataFrame) -> str:
    """Format dataframe as markdown or readable text without requiring tabulate."""
    try:
        return df.to_markdown(index=False)
    except Exception:
        # Markdown table fallback
        headers = [str(c) for c in df.columns]
        rows = [[str(val) if pd.notna(val) else "" for val in row] for row in df.itertuples(index=False)]
        header_line = " | ".join(headers)
        separator_line = " | ".join(["---"] * len(headers))
        row_lines = [" | ".join(row) for row in rows]
        return f"| {header_line} |\n| {separator_line} |\n" + "\n".join(f"| {r} |" for r in row_lines)


class DocumentSlicer:
    """Detects file type and slices documents into chunks for extraction."""

    def __init__(
        self,
        text_chunk_lines: int = 60,
        excel_rows_per_chunk: int = 40,
        render_pdf_as_images: bool = False,
        pdf_dpi: int = 200,
    ) -> None:
        self.text_chunk_lines = text_chunk_lines
        self.excel_rows_per_chunk = excel_rows_per_chunk
        self.render_pdf_as_images = render_pdf_as_images
        self.pdf_dpi = pdf_dpi

    def slice_file(self, file_path: Path | str) -> List[SliceChunk]:
        """Slice any supported document file into chunks."""
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Input file not found: {path}")

        suffix = path.suffix.lower()

        # If specialized slicers package is available, use it
        if HAS_SLICERS_PKG:
            try:
                if suffix == ".pdf" and self.render_pdf_as_images:
                    with PDFSlicer(dpi=self.pdf_dpi, auto_cleanup=True) as pdf_slicer:
                        page_slices = list(pdf_slicer.slice(path))
                        return [
                            SliceChunk(
                                chunk_id=ps.page_number,
                                total_chunks=ps.total_pages,
                                chunk_type="image",
                                source_filename=path.name,
                                image_bytes=ps.image_bytes,
                                mime_type=f"image/{ps.format}",
                                metadata=ps.metadata,
                            )
                            for ps in page_slices
                        ]
                if suffix in (".xlsx", ".xlsm", ".xltx", ".xltm", ".xls", ".csv", ".tsv"):
                    table_slicer = TableSlicer(batch_size=self.excel_rows_per_chunk)
                    table_chunks = list(table_slicer.slice(path))
                    total_table_chunks = len(table_chunks)
                    return [
                        SliceChunk(
                            chunk_id=idx + 1,
                            total_chunks=total_table_chunks,
                            chunk_type="text",
                            source_filename=path.name,
                            text_content=f"# Sheet: {tc.sheet_name}\n\n{tc.markdown}",
                            metadata={**(tc.metadata or {}), "sheet_name": tc.sheet_name},
                        )
                        for idx, tc in enumerate(table_chunks)
                    ]
                if suffix in (".txt", ".md", ".log"):
                    text_slicer = TextSlicer()
                    txt_chunks = list(text_slicer.slice_file(path))
                    return [
                        SliceChunk(
                            chunk_id=tc.chunk_index + 1,
                            total_chunks=tc.total_chunks,
                            chunk_type="text",
                            source_filename=path.name,
                            text_content=tc.content,
                            metadata={"header": tc.title},
                        )
                        for tc in txt_chunks
                    ]
            except Exception as exc:
                logger.warning(
                    "Specialized slicer failed (%s). Falling back to built-in slicer.",
                    exc,
                )

        if suffix == ".pdf":
            return self._slice_pdf(path)
        if suffix in (".xlsx", ".xlsm", ".xltx", ".xltm"):
            return self._slice_excel(path)
        if suffix in (".csv", ".tsv"):
            return self._slice_delimited(path, delimiter="," if suffix == ".csv" else "\t")
        if suffix in (".txt", ".md", ".json", ".log"):
            return self._slice_text(path)

        # Fallback: attempt reading as plain text
        try:
            return self._slice_text(path)
        except Exception as exc:
            raise ValueError(
                f"Unsupported file format '{suffix}' for {path.name}: {exc}"
            ) from exc

    def _slice_pdf(self, path: Path) -> List[SliceChunk]:
        """Slice PDF by page, either as text or rendered images."""
        chunks: List[SliceChunk] = []
        doc = pymupdf.open(str(path))
        total_pages = len(doc)

        try:
            for page_idx in range(total_pages):
                page = doc[page_idx]
                page_num = page_idx + 1

                if self.render_pdf_as_images:
                    zoom = self.pdf_dpi / 72.0
                    mat = pymupdf.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_bytes = pix.tobytes("png")
                    chunks.append(
                        SliceChunk(
                            chunk_id=page_num,
                            total_chunks=total_pages,
                            chunk_type="image",
                            source_filename=path.name,
                            image_bytes=img_bytes,
                            mime_type="image/png",
                            metadata={"page": page_num, "total_pages": total_pages},
                        )
                    )
                else:
                    text = page.get_text("text").strip()
                    if not text:
                        # Fallback to image rendering if page has no extractable text
                        pix = page.get_pixmap(dpi=self.pdf_dpi, alpha=False)
                        img_bytes = pix.tobytes("png")
                        chunks.append(
                            SliceChunk(
                                chunk_id=page_num,
                                total_chunks=total_pages,
                                chunk_type="image",
                                source_filename=path.name,
                                image_bytes=img_bytes,
                                mime_type="image/png",
                                metadata={
                                    "page": page_num,
                                    "total_pages": total_pages,
                                    "note": "fallback_ocr",
                                },
                            )
                        )
                    else:
                        chunks.append(
                            SliceChunk(
                                chunk_id=page_num,
                                total_chunks=total_pages,
                                chunk_type="text",
                                source_filename=path.name,
                                text_content=text,
                                metadata={"page": page_num, "total_pages": total_pages},
                            )
                        )
        finally:
            doc.close()

        return chunks

    def _slice_excel(self, path: Path) -> List[SliceChunk]:
        """Slice Excel spreadsheet sheets and rows into markdown chunks."""
        chunks: List[SliceChunk] = []
        excel_file = pd.ExcelFile(str(path))
        sheet_names = excel_file.sheet_names

        temp_chunks: List[Dict[str, Any]] = []

        for sheet in sheet_names:
            df = excel_file.parse(sheet)
            if df.empty:
                continue

            # Drop completely empty rows and columns
            df = df.dropna(how="all").dropna(how="all", axis=1)
            total_rows = len(df)

            if total_rows <= self.excel_rows_per_chunk:
                markdown_table = _dataframe_to_text(df)
                temp_chunks.append(
                    {
                        "text": f"# Sheet: {sheet}\n\n{markdown_table}",
                        "meta": {"sheet": sheet, "sheet_name": sheet, "rows": total_rows},
                    }
                )
            else:
                for start_idx in range(0, total_rows, self.excel_rows_per_chunk):
                    chunk_df = df.iloc[start_idx : start_idx + self.excel_rows_per_chunk]
                    markdown_table = _dataframe_to_text(chunk_df)
                    temp_chunks.append(
                        {
                            "text": f"# Sheet: {sheet} (Rows {start_idx + 1}-{min(start_idx + self.excel_rows_per_chunk, total_rows)})\n\n{markdown_table}",
                            "meta": {
                                "sheet": sheet,
                                "sheet_name": sheet,
                                "start_row": start_idx + 1,
                                "end_row": min(
                                    start_idx + self.excel_rows_per_chunk, total_rows
                                ),
                            },
                        }
                    )

        total = len(temp_chunks)
        for idx, item in enumerate(temp_chunks):
            chunks.append(
                SliceChunk(
                    chunk_id=idx + 1,
                    total_chunks=total,
                    chunk_type="text",
                    source_filename=path.name,
                    text_content=item["text"],
                    metadata=item["meta"],
                )
            )

        return chunks

    def _slice_delimited(self, path: Path, delimiter: str = ",") -> List[SliceChunk]:
        """Slice CSV / TSV files."""
        df = pd.read_csv(str(path), delimiter=delimiter)
        total_rows = len(df)
        temp_chunks: List[str] = []

        if total_rows <= self.excel_rows_per_chunk:
            temp_chunks.append(_dataframe_to_text(df))
        else:
            for start_idx in range(0, total_rows, self.excel_rows_per_chunk):
                sub_df = df.iloc[start_idx : start_idx + self.excel_rows_per_chunk]
                temp_chunks.append(_dataframe_to_text(sub_df))

        total = len(temp_chunks)
        return [
            SliceChunk(
                chunk_id=idx + 1,
                total_chunks=total,
                chunk_type="text",
                source_filename=path.name,
                text_content=txt,
            )
            for idx, txt in enumerate(temp_chunks)
        ]

    def _slice_text(self, path: Path) -> List[SliceChunk]:
        """Slice text documents by section headers or line boundaries."""
        raw_text = path.read_text(encoding="utf-8")
        lines = raw_text.splitlines()

        if len(lines) <= self.text_chunk_lines:
            return [
                SliceChunk(
                    chunk_id=1,
                    total_chunks=1,
                    chunk_type="text",
                    source_filename=path.name,
                    text_content=raw_text,
                )
            ]

        # Chunk by line blocks
        chunks: List[SliceChunk] = []
        raw_chunks: List[str] = []
        for i in range(0, len(lines), self.text_chunk_lines):
            block = "\n".join(lines[i : i + self.text_chunk_lines])
            raw_chunks.append(block)

        total = len(raw_chunks)
        for idx, block in enumerate(raw_chunks):
            chunks.append(
                SliceChunk(
                    chunk_id=idx + 1,
                    total_chunks=total,
                    chunk_type="text",
                    source_filename=path.name,
                    text_content=block,
                    metadata={"line_start": idx * self.text_chunk_lines + 1},
                )
            )

        return chunks
