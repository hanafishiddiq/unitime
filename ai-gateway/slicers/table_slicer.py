"""
High-performance Table Slicer for UniTime AI Ingestion Gateway.

Parses Excel (.xlsx, .xls) and CSV (.csv, .tsv) files with multi-sheet support,
smart row batching (default 40-50 rows), and strict header preservation across
all chunks to prevent LLM schema hallucination.
"""

from __future__ import annotations

import csv
import datetime
import io
import math
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Union

import openpyxl

try:
    import xlrd
except ImportError:
    xlrd = None  # type: ignore[assignment]

from .models import TableChunk


class TableSlicer:
    """
    Slices multi-sheet spreadsheets and delimited CSV files into semantically intact chunks.

    Guarantees:
    - Multi-sheet isolation: Sheets (e.g. per Prodi / Department / Semester) are processed independently.
    - Header preservation: Every chunk always prepends the complete column header row.
    - Format conversion: Each chunk provides both clean Markdown table and standard CSV string representations.
    """

    SUPPORTED_EXCEL_OPENPYXL: Set[str] = {".xlsx", ".xlsm", ".xltx", ".xltm"}
    SUPPORTED_EXCEL_XLRD: Set[str] = {".xls"}
    SUPPORTED_CSV: Set[str] = {".csv", ".tsv", ".txt"}

    ACADEMIC_HEADER_KEYWORDS: Set[str] = {
        "kode",
        "mata kuliah",
        "matakuliah",
        "mk",
        "sks",
        "komponen",
        "kelas",
        "kapasitas",
        "hari",
        "waktu",
        "jam",
        "gedung",
        "ruang",
        "dosen",
        "pengampu",
        "course",
        "subject",
        "time",
        "room",
        "instructor",
        "section",
        "capacity",
        "day",
        "building",
        "title",
        "crn",
        "credits",
        "type",
    }

    def __init__(
        self,
        batch_size: int = 50,
        header_row_index: Optional[int] = None,
        max_header_scan_rows: int = 10,
        skip_empty_sheets: bool = True,
        csv_delimiter: Optional[str] = None,
    ) -> None:
        """
        Initialize the TableSlicer.

        Args:
            batch_size: Number of data rows per chunk batch (default 50).
            header_row_index: Explicit 0-indexed row containing table headers.
                              If None, auto-detects first structured non-empty row.
            max_header_scan_rows: Max rows to inspect when auto-detecting header row.
            skip_empty_sheets: If True, sheets without tabular data are skipped.
            csv_delimiter: Explicit delimiter for CSV parsing. If None, auto-sniffed.
        """
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got: {batch_size}")

        self.batch_size = batch_size
        self.header_row_index = header_row_index
        self.max_header_scan_rows = max_header_scan_rows
        self.skip_empty_sheets = skip_empty_sheets
        self.csv_delimiter = csv_delimiter

    def get_sheet_names(self, file_path: Union[str, Path]) -> List[str]:
        """
        Inspect spreadsheet sheet names without loading full table contents into memory.

        Args:
            file_path: Path to target Excel or CSV document.

        Returns:
            List of sheet names (e.g. ['Prodi_TI', 'Prodi_SI']).
        """
        path = self._validate_file_path(file_path)
        ext = path.suffix.lower()

        if ext in self.SUPPORTED_CSV:
            return [path.stem]

        if ext in self.SUPPORTED_EXCEL_OPENPYXL:
            wb = openpyxl.load_workbook(path, read_only=True, keep_links=False)
            try:
                return list(wb.sheetnames)
            finally:
                wb.close()

        if ext in self.SUPPORTED_EXCEL_XLRD:
            if xlrd is None:
                raise ImportError("xlrd library is required to read .xls legacy Excel files.")
            wb_xls = xlrd.open_workbook(str(path), on_demand=True)
            try:
                return list(wb_xls.sheet_names())
            finally:
                wb_xls.release_resources()

        raise ValueError(f"Unsupported file format '{ext}' for file {path}")

    def slice(
        self,
        file_path: Union[str, Path],
        sheet_names: Optional[List[str]] = None,
    ) -> Iterator[TableChunk]:
        """
        Slice tabular document into batched TableChunk objects.

        Args:
            file_path: Path to input Excel or CSV document.
            sheet_names: Optional subset of sheet names to slice. If None, slices all sheets.

        Yields:
            TableChunk objects with prepended header and markdown/CSV representations.
        """
        path = self._validate_file_path(file_path)
        ext = path.suffix.lower()

        sheets_data = self._read_sheets(path, ext, target_sheets=sheet_names)

        for sheet_name, raw_rows in sheets_data.items():
            if not raw_rows:
                if self.skip_empty_sheets:
                    continue

            headers, data_rows, detected_header_idx = self._extract_headers_and_data(raw_rows)

            if not headers and not data_rows:
                if self.skip_empty_sheets:
                    continue

            total_data_rows = len(data_rows)
            if total_data_rows == 0:
                if self.skip_empty_sheets:
                    continue
                # Handle header-only sheet
                total_chunks = 1
                markdown = self._build_markdown_table(headers, [])
                csv_str = self._build_csv_string(headers, [])
                yield TableChunk(
                    sheet_name=sheet_name,
                    chunk_index=0,
                    total_chunks=1,
                    start_row=0,
                    end_row=0,
                    total_rows=0,
                    headers=headers,
                    rows=[],
                    markdown=markdown,
                    csv_content=csv_str,
                    source_file=path,
                    metadata={
                        "sheet_name": sheet_name,
                        "header_row_index": detected_header_idx,
                        "is_empty": True,
                    },
                )
                continue

            total_chunks = math.ceil(total_data_rows / self.batch_size)

            for chunk_idx in range(total_chunks):
                start = chunk_idx * self.batch_size
                end = min(start + self.batch_size, total_data_rows)
                chunk_data = data_rows[start:end]

                markdown = self._build_markdown_table(headers, chunk_data)
                csv_str = self._build_csv_string(headers, chunk_data)

                # 1-indexed row tracking for administrative auditability
                excel_row_start = detected_header_idx + 2 + start
                excel_row_end = detected_header_idx + 1 + end

                metadata: Dict[str, Any] = {
                    "sheet_name": sheet_name,
                    "header_row_index": detected_header_idx,
                    "excel_header_row": detected_header_idx + 1,
                    "excel_data_row_start": excel_row_start,
                    "excel_data_row_end": excel_row_end,
                    "columns_count": len(headers),
                }

                yield TableChunk(
                    sheet_name=sheet_name,
                    chunk_index=chunk_idx,
                    total_chunks=total_chunks,
                    start_row=start,
                    end_row=end,
                    total_rows=total_data_rows,
                    headers=headers,
                    rows=chunk_data,
                    markdown=markdown,
                    csv_content=csv_str,
                    source_file=path,
                    metadata=metadata,
                )

    def slice_all(
        self,
        file_path: Union[str, Path],
        sheet_names: Optional[List[str]] = None,
    ) -> List[TableChunk]:
        """Convenience method to collect all table chunks into an in-memory list."""
        return list(self.slice(file_path, sheet_names=sheet_names))

    def slice_sheet(
        self,
        file_path: Union[str, Path],
        sheet_name: str,
    ) -> List[TableChunk]:
        """Slice only a single specified sheet."""
        return list(self.slice(file_path, sheet_names=[sheet_name]))

    def _validate_file_path(self, file_path: Union[str, Path]) -> Path:
        """Ensure file exists, is regular file, and not empty."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a regular file: {path}")
        if path.stat().st_size == 0:
            raise ValueError(f"File is empty (0 bytes): {path}")
        return path

    def _read_sheets(
        self,
        file_path: Path,
        ext: str,
        target_sheets: Optional[List[str]] = None,
    ) -> Dict[str, List[List[Any]]]:
        """Dispatch table reading to the appropriate backend."""
        if ext in self.SUPPORTED_EXCEL_OPENPYXL:
            return self._read_excel_openpyxl(file_path, target_sheets)
        if ext in self.SUPPORTED_EXCEL_XLRD:
            return self._read_excel_xlrd(file_path, target_sheets)
        if ext in self.SUPPORTED_CSV:
            return self._read_csv(file_path)
        raise ValueError(
            f"Unsupported spreadsheet format '{ext}'. "
            f"Supported formats: {sorted(self.SUPPORTED_EXCEL_OPENPYXL | self.SUPPORTED_EXCEL_XLRD | self.SUPPORTED_CSV)}"
        )

    def _read_excel_openpyxl(
        self,
        file_path: Path,
        target_sheets: Optional[List[str]] = None,
    ) -> Dict[str, List[List[Any]]]:
        """Read .xlsx workbook using openpyxl in read-only data mode for high performance."""
        wb = openpyxl.load_workbook(file_path, read_only=False, data_only=True, keep_links=False)
        result: Dict[str, List[List[Any]]] = {}
        try:
            available_sheets = wb.sheetnames
            sheets_to_process = (
                [s for s in target_sheets if s in available_sheets]
                if target_sheets is not None
                else available_sheets
            )

            for s_name in sheets_to_process:
                ws = wb[s_name]
                
                merged_dict = {}
                for merged_range in ws.merged_cells.ranges:
                    min_col, min_row, max_col, max_row = merged_range.bounds
                    top_left_val = ws.cell(row=min_row, column=min_col).value
                    for r in range(min_row, max_row + 1):
                        for c in range(min_col, max_col + 1):
                            merged_dict[(r, c)] = top_left_val

                rows: List[List[Any]] = []
                for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                    row_vals = []
                    for col_idx, cell_val in enumerate(row, start=1):
                        if (row_idx, col_idx) in merged_dict:
                            row_vals.append(merged_dict[(row_idx, col_idx)])
                        else:
                            row_vals.append(cell_val)
                            
                    # Filter out purely None/empty rows
                    if any(c is not None and str(c).strip() != "" for c in row_vals):
                        rows.append(row_vals)
                result[s_name] = rows
        finally:
            wb.close()
        return result

    def _read_excel_xlrd(
        self,
        file_path: Path,
        target_sheets: Optional[List[str]] = None,
    ) -> Dict[str, List[List[Any]]]:
        """Read legacy .xls files using xlrd."""
        if xlrd is None:
            raise ImportError("xlrd library is required to read .xls legacy Excel files.")

        wb = xlrd.open_workbook(str(file_path), on_demand=True)
        result: Dict[str, List[List[Any]]] = {}
        try:
            available_sheets = wb.sheet_names()
            sheets_to_process = (
                [s for s in target_sheets if s in available_sheets]
                if target_sheets is not None
                else available_sheets
            )

            for s_name in sheets_to_process:
                sheet = wb.sheet_by_name(s_name)
                rows: List[List[Any]] = []
                for row_idx in range(sheet.nrows):
                    row_vals = sheet.row_values(row_idx)
                    if any(c is not None and str(c).strip() != "" for c in row_vals):
                        rows.append(row_vals)
                result[s_name] = rows
        finally:
            wb.release_resources()
        return result

    def _read_csv(self, file_path: Path) -> Dict[str, List[List[Any]]]:
        """Read CSV/TSV files with robust delimiter detection."""
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            return {file_path.stem: []}

        delimiter = self.csv_delimiter
        if delimiter is None:
            try:
                sample = content[:4096]
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(sample, delimiters=",\t;|")
                delimiter = dialect.delimiter
            except Exception:
                delimiter = ","

        reader = csv.reader(io.StringIO(content), delimiter=delimiter)
        rows: List[List[Any]] = []
        for row in reader:
            if any(c.strip() != "" for c in row):
                rows.append(row)

        return {file_path.stem: rows}

    def _extract_headers_and_data(
        self,
        raw_rows: List[List[Any]],
    ) -> Tuple[List[str], List[List[str]], int]:
        """
        Identify header row and separate data rows.

        Handles common academic spreadsheets with preamble title lines and merged
        banner titles by detecting uniform/merged banner rows and scoring candidate
        rows against academic domain keywords and column diversity.
        """
        if not raw_rows:
            return [], [], -1

        # Explicit header index provided by caller
        if self.header_row_index is not None:
            header_idx = self.header_row_index
            if header_idx < 0 or header_idx >= len(raw_rows):
                raise IndexError(
                    f"Specified header_row_index {header_idx} out of range (0..{len(raw_rows)-1})"
                )
        else:
            scan_limit = min(len(raw_rows), self.max_header_scan_rows)
            max_cols = max(len(r) for r in raw_rows) if raw_rows else 0
            best_idx = 0
            best_score = -1.0
            max_non_empty = 0

            for idx in range(scan_limit):
                if idx == len(raw_rows) - 1 and len(raw_rows) > 1 and best_score > 0:
                    continue

                row = raw_rows[idx]
                non_empty_cells = [
                    str(cell).strip()
                    for cell in row
                    if cell is not None and str(cell).strip() != ""
                ]
                non_empty_count = len(non_empty_cells)
                if non_empty_count > max_non_empty:
                    max_non_empty = non_empty_count

                if not non_empty_cells:
                    continue

                unique_vals = set(non_empty_cells)

                # Full-width title banner / uniform row check:
                # Rows with <= 1 unique value across multiple columns are merged title banners,
                # NOT table headers.
                if max_cols > 1 and len(unique_vals) <= 1:
                    continue

                # Count matches with domain-specific academic header keywords
                academic_matches = sum(
                    1
                    for val in unique_vals
                    if any(kw in val.lower() for kw in self.ACADEMIC_HEADER_KEYWORDS)
                )

                # Scoring heuristic:
                # - Academic keyword matches carry high priority (10.0 points each)
                # - Number of distinct columns carries base weight (1.0 point each)
                score = (academic_matches * 10.0) + float(len(unique_vals))

                if score > best_score:
                    best_score = score
                    best_idx = idx

            # Fallback if no candidate scored above 0 (e.g. non-academic general tables)
            if best_score <= 0:
                best_idx = 0
                for idx in range(scan_limit):
                    row = raw_rows[idx]
                    count = sum(1 for c in row if c is not None and str(c).strip() != "")
                    if count == max_non_empty and count > 0:
                        best_idx = idx
                        break

            header_idx = best_idx

        raw_headers = list(raw_rows[header_idx])
        raw_data = raw_rows[header_idx + 1 :]

        # Ensure headers cover the maximum column width across all rows to prevent data truncation
        max_cols = max(len(r) for r in raw_rows) if raw_rows else len(raw_headers)
        if len(raw_headers) < max_cols:
            raw_headers.extend([""] * (max_cols - len(raw_headers)))

        # Normalize headers
        headers: List[str] = []
        for col_idx, cell in enumerate(raw_headers):
            val = self._format_cell_value(cell).strip()
            if not val:
                val = f"Column_{col_idx + 1}"
            headers.append(val)

        # Disambiguate duplicate header names
        seen_headers: Dict[str, int] = {}
        unique_headers: List[str] = []
        for h in headers:
            if h in seen_headers:
                seen_headers[h] += 1
                unique_headers.append(f"{h}_{seen_headers[h]}")
            else:
                seen_headers[h] = 1
                unique_headers.append(h)

        col_count = len(unique_headers)

        # Normalize data rows to match header column count
        formatted_data: List[List[str]] = []
        for r in raw_data:
            formatted_row: List[str] = []
            for col_idx in range(col_count):
                cell_val = r[col_idx] if col_idx < len(r) else ""
                formatted_row.append(self._format_cell_value(cell_val))
            formatted_data.append(formatted_row)

        return unique_headers, formatted_data, header_idx

    def _format_cell_value(self, val: Any) -> str:
        """Format raw cell values into clean, predictable string representations."""
        if val is None:
            return ""

        if isinstance(val, bool):
            return str(val)

        if isinstance(val, (int,)):
            return str(val)

        if isinstance(val, float):
            # Convert whole numbers like 4.0 to "4" (common in SKS or room IDs)
            if val.is_integer():
                return str(int(val))
            return f"{val:.4f}".rstrip("0").rstrip(".")

        if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
            if isinstance(val, datetime.datetime):
                return val.strftime("%Y-%m-%d %H:%M")
            if isinstance(val, datetime.date):
                return val.strftime("%Y-%m-%d")
            return val.strftime("%H:%M")

        text = str(val).strip()
        # Flatten intra-cell newlines to prevent broken markdown tables
        text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        return text

    def _build_markdown_table(self, headers: List[str], rows: List[List[str]]) -> str:
        """
        Render table chunk in clean GitHub-Flavored Markdown.

        Escapes pipe characters in cell content to preserve table column integrity.
        """
        if not headers:
            return ""

        escaped_headers = [h.replace("|", "\\|") for h in headers]
        header_line = "| " + " | ".join(escaped_headers) + " |"
        separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"

        lines = [header_line, separator_line]

        for row in rows:
            escaped_row = [cell.replace("|", "\\|") for cell in row]
            lines.append("| " + " | ".join(escaped_row) + " |")

        return "\n".join(lines)

    def _build_csv_string(self, headers: List[str], rows: List[List[str]]) -> str:
        """Render table chunk as standard RFC 4180 CSV string with header prepended."""
        if not headers:
            return ""

        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)

        return out.getvalue().strip()
