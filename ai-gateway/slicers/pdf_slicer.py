"""
High-performance PDF and image slicer for UniTime AI Ingestion Gateway.

Renders multi-page PDF documents strictly one page at a time into high-resolution
images (default 200 DPI) using PyMuPDF (fitz), preventing high RAM spikes on large
schedules. Seamlessly handles single-page image files as 1-page slices.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Union

from PIL import Image

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore[no-redef]

from .models import PageDimensions, PageSlice


class PDFSlicer:
    """
    Slices multi-page PDF documents and standalone image files into PageSlice objects.

    Guarantees strict single-page sequential processing to prevent excessive memory
    consumption during high-resolution rendering of lengthy timetables or academic memos.
    """

    SUPPORTED_PDF_EXTENSIONS: Set[str] = {".pdf"}
    SUPPORTED_IMAGE_EXTENSIONS: Set[str] = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tiff",
        ".tif",
    }

    def __init__(
        self,
        dpi: int = 200,
        image_format: str = "png",
        output_dir: Optional[Union[str, Path]] = None,
        save_to_disk: bool = True,
        keep_in_memory: bool = True,
        extract_text_metadata: bool = True,
        auto_cleanup: bool = False,
    ) -> None:
        """
        Initialize the PDF and Image slicer.

        Args:
            dpi: Resolution for rendered images. Recommended range 200-300 DPI for OCR/VLM.
            image_format: Output image format ('png', 'jpeg', or 'jpg').
            output_dir: Optional directory to store rendered page files.
                        If None and save_to_disk is True, a temporary directory is created.
            save_to_disk: Whether to write rendered page images to disk.
            keep_in_memory: Whether to attach raw image bytes directly to PageSlice.
            extract_text_metadata: Whether to extract embedded page text in slice metadata.
            auto_cleanup: If True, temporary files created by this instance will be deleted
                          when calling cleanup() or exiting a context manager.
        """
        if dpi < 72 or dpi > 600:
            raise ValueError(f"DPI must be between 72 and 600, got: {dpi}")

        normalized_format = image_format.lower().lstrip(".")
        if normalized_format in ("jpg", "jpeg"):
            self.image_format = "jpeg"
            self.file_extension = "jpg"
        elif normalized_format == "png":
            self.image_format = "png"
            self.file_extension = "png"
        elif normalized_format == "webp":
            self.image_format = "webp"
            self.file_extension = "webp"
        else:
            raise ValueError(
                f"Unsupported image format '{image_format}'. Allowed: 'png', 'jpeg', 'webp'."
            )

        if not save_to_disk and not keep_in_memory:
            raise ValueError("At least one of save_to_disk or keep_in_memory must be True.")

        self.dpi = dpi
        self.save_to_disk = save_to_disk
        self.keep_in_memory = keep_in_memory
        self.extract_text_metadata = extract_text_metadata
        self.auto_cleanup = auto_cleanup

        self._managed_temp_dir: Optional[Path] = None
        if output_dir is not None:
            self.output_dir = Path(output_dir).resolve()
            self.output_dir.mkdir(parents=True, exist_ok=True)
        elif self.save_to_disk:
            self._managed_temp_dir = Path(
                tempfile.mkdtemp(prefix="unitime_pdf_slices_")
            ).resolve()
            self.output_dir = self._managed_temp_dir
        else:
            self.output_dir = None  # type: ignore[assignment]

    def __enter__(self) -> PDFSlicer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.auto_cleanup or self._managed_temp_dir is not None:
            self.cleanup()

    def __del__(self) -> None:
        try:
            if hasattr(self, "_managed_temp_dir") and self._managed_temp_dir is not None:
                self.cleanup()
        except Exception:
            pass

    def cleanup(self) -> None:
        """Remove managed temporary directory and all generated page images."""
        if self._managed_temp_dir is not None and self._managed_temp_dir.exists():
            shutil.rmtree(self._managed_temp_dir, ignore_errors=True)
            self._managed_temp_dir = None

    def get_page_count(self, file_path: Union[str, Path]) -> int:
        """
        Quickly inspect total page count of a document without rendering pages.

        Args:
            file_path: Path to the target PDF or image.

        Returns:
            Number of pages (always 1 for standalone image files).
        """
        path = self._validate_file_path(file_path)
        ext = path.suffix.lower()

        if ext in self.SUPPORTED_IMAGE_EXTENSIONS:
            return 1

        if ext in self.SUPPORTED_PDF_EXTENSIONS:
            doc = fitz.open(path)
            try:
                return len(doc)
            finally:
                doc.close()

        raise ValueError(f"Unsupported file extension '{ext}' for file: {path}")

    def slice(self, file_path: Union[str, Path]) -> Iterator[PageSlice]:
        """
        Slice a document strictly one page at a time, yielding PageSlice objects.

        Memory safe: Only one page pixmap is resident in memory at any point.

        Args:
            file_path: Path to input PDF or image file.

        Yields:
            PageSlice for each sequential page.

        Raises:
            FileNotFoundError: If input file does not exist.
            ValueError: If file is corrupted, encrypted, or unsupported.
        """
        path = self._validate_file_path(file_path)
        ext = path.suffix.lower()

        if ext in self.SUPPORTED_IMAGE_EXTENSIONS:
            yield self._slice_image_file(path)
            return

        if ext in self.SUPPORTED_PDF_EXTENSIONS:
            yield from self._slice_pdf_stream(path)
            return

        raise ValueError(
            f"Unsupported file extension '{ext}' for file {path}. "
            f"Supported: {sorted(self.SUPPORTED_PDF_EXTENSIONS | self.SUPPORTED_IMAGE_EXTENSIONS)}"
        )

    def slice_all(self, file_path: Union[str, Path]) -> List[PageSlice]:
        """
        Convenience method to slice all pages of a document into an in-memory list.

        Args:
            file_path: Path to input document.

        Returns:
            List of all PageSlice objects.
        """
        return list(self.slice(file_path))

    def slice_page(self, file_path: Union[str, Path], page_index: int) -> PageSlice:
        """
        Render and return a single specific page slice on demand.

        Args:
            file_path: Path to input PDF or image file.
            page_index: 0-indexed page number to render.

        Returns:
            PageSlice for the requested page.

        Raises:
            IndexError: If page_index is out of range.
        """
        path = self._validate_file_path(file_path)
        ext = path.suffix.lower()

        if ext in self.SUPPORTED_IMAGE_EXTENSIONS:
            if page_index != 0:
                raise IndexError(f"Image has only 1 page (index 0), requested index: {page_index}")
            return self._slice_image_file(path)

        if ext in self.SUPPORTED_PDF_EXTENSIONS:
            return self._render_single_pdf_page(path, page_index)

        raise ValueError(f"Unsupported file format '{ext}' for file {path}")

    def _validate_file_path(self, file_path: Union[str, Path]) -> Path:
        """Validate that file exists, is a regular file, and has non-zero size."""
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a regular file: {path}")
        if path.stat().st_size == 0:
            raise ValueError(f"File is empty (0 bytes): {path}")
        return path

    def _slice_image_file(self, image_path: Path) -> PageSlice:
        """Handle standalone image files as a single-page document slice."""
        try:
            with Image.open(image_path) as img:
                width, height = img.size
                orig_format = (img.format or image_path.suffix.lstrip(".")).lower()
                image_bytes: Optional[bytes] = None

                # Determine whether conversion is necessary
                needs_conversion = orig_format != self.image_format
                if self.keep_in_memory:
                    if needs_conversion:
                        buffer = io.BytesIO()
                        # Handle RGBA to RGB for JPEG
                        converted_img = img.convert("RGB") if self.image_format == "jpeg" and img.mode in ("RGBA", "LA", "P") else img
                        converted_img.save(buffer, format=self.image_format.upper())
                        image_bytes = buffer.getvalue()
                    else:
                        image_bytes = image_path.read_bytes()

                saved_path: Optional[Path] = None
                if self.save_to_disk and self.output_dir is not None:
                    dest_name = f"{image_path.stem}_page_0001.{self.file_extension}"
                    saved_path = self.output_dir / dest_name
                    if needs_conversion:
                        converted_img = img.convert("RGB") if self.image_format == "jpeg" and img.mode in ("RGBA", "LA", "P") else img
                        converted_img.save(saved_path, format=self.image_format.upper())
                    else:
                        shutil.copyfile(image_path, saved_path)
                elif not self.save_to_disk:
                    saved_path = None

                metadata: Dict[str, Any] = {
                    "original_format": orig_format,
                    "color_mode": img.mode,
                    "is_direct_image": True,
                }

                return PageSlice(
                    page_index=0,
                    page_number=1,
                    total_pages=1,
                    dimensions=PageDimensions(width=width, height=height),
                    dpi=self.dpi,
                    format=self.image_format,
                    image_path=saved_path,
                    image_bytes=image_bytes,
                    source_file=image_path,
                    metadata=metadata,
                )
        except Exception as exc:
            raise ValueError(f"Failed to process image file '{image_path}': {exc}") from exc

    def _slice_pdf_stream(self, pdf_path: Path) -> Iterator[PageSlice]:
        """Stream PDF pages strictly one by one to keep memory minimal."""
        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            raise ValueError(f"Failed to open PDF document '{pdf_path}': {exc}") from exc

        try:
            if doc.is_encrypted:
                raise ValueError(f"PDF document '{pdf_path}' is encrypted and cannot be processed.")

            total_pages = len(doc)
            if total_pages == 0:
                raise ValueError(f"PDF document '{pdf_path}' contains 0 pages.")

            for page_idx in range(total_pages):
                yield self._render_page_from_doc(doc, pdf_path, page_idx, total_pages)
        finally:
            doc.close()

    def _render_single_pdf_page(self, pdf_path: Path, page_index: int) -> PageSlice:
        """Render a single page directly from a PDF file."""
        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            raise ValueError(f"Failed to open PDF document '{pdf_path}': {exc}") from exc

        try:
            if doc.is_encrypted:
                raise ValueError(f"PDF document '{pdf_path}' is encrypted.")

            total_pages = len(doc)
            if page_index < 0 or page_index >= total_pages:
                raise IndexError(
                    f"Page index {page_index} out of range (document has {total_pages} pages, valid 0..{total_pages - 1})"
                )

            return self._render_page_from_doc(doc, pdf_path, page_index, total_pages)
        finally:
            doc.close()

    def _render_page_from_doc(
        self,
        doc: fitz.Document,
        pdf_path: Path,
        page_index: int,
        total_pages: int,
    ) -> PageSlice:
        """Render an individual page from an open PyMuPDF document instance."""
        page = doc.load_page(page_index)

        # Render to pixmap with target DPI
        pix = page.get_pixmap(dpi=self.dpi, alpha=False)
        dims = PageDimensions(width=pix.width, height=pix.height)

        # Extract textual content if enabled
        extracted_text = page.get_text("text").strip() if self.extract_text_metadata else ""

        metadata: Dict[str, Any] = {
            "source_type": "pdf",
            "has_text": bool(extracted_text),
        }
        if extracted_text:
            metadata["extracted_text"] = extracted_text

        # Generate bytes if configured
        image_bytes: Optional[bytes] = None
        if self.keep_in_memory:
            image_bytes = pix.tobytes(self.image_format)

        # Save to disk if configured
        image_path: Optional[Path] = None
        if self.save_to_disk and self.output_dir is not None:
            dest_name = f"{pdf_path.stem}_page_{page_index + 1:04d}.{self.file_extension}"
            target_file = self.output_dir / dest_name
            pix.save(str(target_file))
            image_path = target_file

        # Explicitly clean up MuPDF objects
        del pix
        del page

        return PageSlice(
            page_index=page_index,
            page_number=page_index + 1,
            total_pages=total_pages,
            dimensions=dims,
            dpi=self.dpi,
            format=self.image_format,
            image_path=image_path,
            image_bytes=image_bytes,
            source_file=pdf_path,
            metadata=metadata,
        )
