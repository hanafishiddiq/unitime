"""
Comprehensive unit and integration test suite for UniTime AI Gateway Slicers.
"""

from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path
from typing import Iterator

import openpyxl
import pytest
from PIL import Image
import pymupdf

from slicers import (
    PageDimensions,
    PageSlice,
    PDFSlicer,
    TableChunk,
    TableSlicer,
    TextChunk,
    TextSlicer,
)
from core.slicer import DocumentSlicer


# ============================================================================
# Model Unit Tests
# ============================================================================

def test_page_dimensions() -> None:
    dims = PageDimensions(width=1920, height=1080)
    assert dims.width == 1920
    assert dims.height == 1080
    assert dims.as_tuple() == (1920, 1080)


def test_page_slice_save_and_dict(tmp_path: Path) -> None:
    fake_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    slice_obj = PageSlice(
        page_index=0,
        page_number=1,
        total_pages=5,
        dimensions=PageDimensions(width=800, height=600),
        dpi=200,
        format="png",
        image_bytes=fake_bytes,
        metadata={"note": "test"},
    )
    dest_file = tmp_path / "saved_page.png"
    result_path = slice_obj.save_image(dest_file)
    assert result_path.exists()
    assert result_path.read_bytes() == fake_bytes

    d = slice_obj.to_dict()
    assert d["page_index"] == 0
    assert d["page_number"] == 1
    assert d["total_pages"] == 5
    assert d["dimensions"] == (800, 600)
    assert "image_bytes" not in d  # raw bytes omitted from dict


def test_table_chunk_models() -> None:
    chunk = TableChunk(
        sheet_name="Prodi_Informatika",
        chunk_index=0,
        total_chunks=2,
        start_row=0,
        end_row=50,
        total_rows=75,
        headers=["Kode", "Matkul", "SKS"],
        rows=[["IF101", "Dasar Pemrograman", "3"]],
        markdown="| Kode | Matkul | SKS |\n| --- | --- | --- |\n| IF101 | Dasar Pemrograman | 3 |",
        csv_content="Kode,Matkul,SKS\nIF101,Dasar Pemrograman,3",
    )
    assert chunk.row_count == 1
    d = chunk.to_dict()
    assert d["sheet_name"] == "Prodi_Informatika"
    assert d["chunk_index"] == 0
    assert d["total_chunks"] == 2


def test_text_chunk_models() -> None:
    chunk = TextChunk(
        chunk_index=0,
        total_chunks=1,
        title="PROGRAM STUDI: TEKNIK INFORMATIKA",
        content="Kurikulum 2026/2027 mencakup AI dan IoT.",
        char_count=40,
        token_estimate=10,
    )
    assert chunk.title == "PROGRAM STUDI: TEKNIK INFORMATIKA"
    assert chunk.token_estimate == 10
    d = chunk.to_dict()
    assert d["char_count"] == 40


# ============================================================================
# PDF Slicer Tests
# ============================================================================

@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample_schedule.pdf"
    doc = pymupdf.open()
    for i in range(3):
        p = doc.new_page(width=595, height=842)
        p.insert_text((50, 50), f"Schedule Page {i + 1} - Department of CS")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_image(tmp_path: Path) -> Path:
    img_path = tmp_path / "sample_schedule_scan.png"
    img = Image.new("RGB", (640, 480), color=(240, 240, 240))
    img.save(img_path)
    return img_path


def test_pdf_slicer_streaming(sample_pdf: Path) -> None:
    slicer = PDFSlicer(dpi=200, save_to_disk=True, keep_in_memory=True)
    assert slicer.get_page_count(sample_pdf) == 3

    slices_iter = slicer.slice(sample_pdf)
    assert isinstance(slices_iter, Iterator)

    slices = list(slices_iter)
    assert len(slices) == 3

    for idx, page_slice in enumerate(slices):
        assert page_slice.page_index == idx
        assert page_slice.page_number == idx + 1
        assert page_slice.total_pages == 3
        assert page_slice.dpi == 200
        assert page_slice.dimensions.width > 1000
        assert page_slice.dimensions.height > 1000
        assert page_slice.image_path is not None
        assert page_slice.image_path.exists()
        assert page_slice.image_bytes is not None
        assert f"Schedule Page {idx + 1}" in page_slice.metadata.get("extracted_text", "")

    slicer.cleanup()


def test_pdf_slicer_slice_single_page(sample_pdf: Path) -> None:
    slicer = PDFSlicer(dpi=200)
    page_1 = slicer.slice_page(sample_pdf, page_index=1)
    assert page_1.page_index == 1
    assert page_1.page_number == 2
    assert "Schedule Page 2" in page_1.metadata.get("extracted_text", "")

    with pytest.raises(IndexError):
        slicer.slice_page(sample_pdf, page_index=99)

    slicer.cleanup()


def test_pdf_slicer_direct_image(sample_image: Path) -> None:
    slicer = PDFSlicer(dpi=200, save_to_disk=True)
    assert slicer.get_page_count(sample_image) == 1

    slices = slicer.slice_all(sample_image)
    assert len(slices) == 1
    s = slices[0]
    assert s.page_index == 0
    assert s.page_number == 1
    assert s.total_pages == 1
    assert s.dimensions.width == 640
    assert s.dimensions.height == 480
    assert s.metadata["is_direct_image"] is True
    slicer.cleanup()


def test_pdf_slicer_jpeg_and_cleanup(sample_pdf: Path, tmp_path: Path) -> None:
    custom_out = tmp_path / "rendered_output"
    with PDFSlicer(dpi=150, image_format="jpeg", output_dir=custom_out, auto_cleanup=False) as slicer:
        slices = slicer.slice_all(sample_pdf)
        assert len(slices) == 3
        assert slices[0].format == "jpeg"
        assert slices[0].image_path is not None
        assert slices[0].image_path.suffix.lower() == ".jpg"
        assert slices[0].image_path.exists()


def test_pdf_slicer_error_handling(tmp_path: Path) -> None:
    slicer = PDFSlicer()
    with pytest.raises(FileNotFoundError):
        list(slicer.slice(tmp_path / "non_existent.pdf"))

    empty_file = tmp_path / "empty.pdf"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError, match="0 bytes"):
        list(slicer.slice(empty_file))

    bad_ext = tmp_path / "document.xyz"
    bad_ext.write_text("random")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        list(slicer.slice(bad_ext))


# ============================================================================
# Table Slicer Tests
# ============================================================================

@pytest.fixture
def multi_sheet_excel(tmp_path: Path) -> Path:
    wb_path = tmp_path / "university_schedule.xlsx"
    wb = openpyxl.Workbook()

    # Sheet 1: Teknik Informatika (85 rows)
    ws1 = wb.active
    ws1.title = "Teknik_Informatika"
    ws1.append(["UNIVERSITAS AIRLANGGA - JADWAL SEMESTER GASAL"])
    ws1.append(["Kode MK", "Nama Mata Kuliah", "SKS", "Hari", "Jam", "Ruang"])
    for i in range(1, 86):
        ws1.append([f"IF{100+i}", f"Mata Kuliah {i}", 3, "Senin", "08:00-10:30", f"R.{300+i%5}"])

    # Sheet 2: Sistem Informasi (25 rows)
    ws2 = wb.create_sheet(title="Sistem_Informasi")
    ws2.append(["Kode MK", "Nama Mata Kuliah", "SKS", "Hari", "Jam", "Ruang"])
    for i in range(1, 26):
        ws2.append([f"SI{200+i}", f"Sistem Info {i}", 2, "Selasa", "13:00-14:40", f"Lab.{i%3}"])

    wb.save(str(wb_path))
    wb.close()
    return wb_path


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    csv_file = tmp_path / "schedule_export.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Course | Special", "Lecturer", "Enrolled"])
        for i in range(1, 65):
            writer.writerow([i, f"Course | Topic {i}", f"Dr. Lecturer {i}", 40])
    return csv_file


def test_table_slicer_multi_sheet_excel(multi_sheet_excel: Path) -> None:
    slicer = TableSlicer(batch_size=40)
    sheets = slicer.get_sheet_names(multi_sheet_excel)
    assert sheets == ["Teknik_Informatika", "Sistem_Informasi"]

    chunks = slicer.slice_all(multi_sheet_excel)
    # Teknik_Informatika: 85 rows with batch_size=40 -> 3 chunks (40, 40, 5)
    # Sistem_Informasi: 25 rows with batch_size=40 -> 1 chunk (25)
    # Total = 4 chunks
    assert len(chunks) == 4

    ti_chunks = [c for c in chunks if c.sheet_name == "Teknik_Informatika"]
    assert len(ti_chunks) == 3
    assert ti_chunks[0].chunk_index == 0
    assert ti_chunks[0].total_chunks == 3
    assert ti_chunks[0].row_count == 40
    assert ti_chunks[1].row_count == 40
    assert ti_chunks[2].row_count == 5

    # Check that EVERY chunk has the prepended headers
    expected_headers = ["Kode MK", "Nama Mata Kuliah", "SKS", "Hari", "Jam", "Ruang"]
    for c in ti_chunks:
        assert c.headers == expected_headers
        assert "| Kode MK | Nama Mata Kuliah | SKS | Hari | Jam | Ruang |" in c.markdown
        assert "| --- | --- | --- | --- | --- | --- |" in c.markdown
        assert "Kode MK,Nama Mata Kuliah,SKS,Hari,Jam,Ruang" in c.csv_content

    # Check 1-indexed audit metadata
    assert ti_chunks[0].metadata["excel_header_row"] == 2
    assert ti_chunks[0].metadata["excel_data_row_start"] == 3
    assert ti_chunks[0].metadata["excel_data_row_end"] == 42


def test_table_slicer_single_sheet_filter(multi_sheet_excel: Path) -> None:
    slicer = TableSlicer(batch_size=50)
    si_chunks = slicer.slice_sheet(multi_sheet_excel, "Sistem_Informasi")
    assert len(si_chunks) == 1
    assert si_chunks[0].sheet_name == "Sistem_Informasi"
    assert si_chunks[0].row_count == 25


def test_table_slicer_csv_and_escaping(sample_csv: Path) -> None:
    slicer = TableSlicer(batch_size=50)
    chunks = slicer.slice_all(sample_csv)
    assert len(chunks) == 2  # 50 rows and 14 rows

    c0 = chunks[0]
    assert c0.row_count == 50
    assert "Course \\| Special" in c0.markdown  # pipe properly escaped in markdown!
    assert c0.headers == ["ID", "Course | Special", "Lecturer", "Enrolled"]

    c1 = chunks[1]
    assert c1.row_count == 14
    assert c1.headers == ["ID", "Course | Special", "Lecturer", "Enrolled"]


# ============================================================================
# Text Slicer Tests
# ============================================================================

def test_text_slicer_narrative_headers() -> None:
    content = """
# Panduan Kurikulum UniTime 2026

## Kebijakan Umum Perkuliahan
Perkuliahan semester baru akan dilaksanakan secara luring penuh.
Setiap dosen pengampu wajib mengunggah silabus ke sistem portal.

## Distribusi Ruang Laboratorium
Laboratorium komputer dialokasikan khusus untuk program studi saintek.
Kapasitas masing-masing lab adalah 30 mahasiswa.

### Prosedur Peminjaman
Pengajuan dilakukan maksimal 3 hari kerja sebelum jadwal perkuliahan.
"""
    slicer = TextSlicer(max_chunk_chars=1000)
    chunks = slicer.slice_text(content)

    assert len(chunks) == 4
    assert chunks[0].title == "Panduan Kurikulum UniTime 2026"
    assert chunks[1].title == "Kebijakan Umum Perkuliahan"
    assert chunks[2].title == "Distribusi Ruang Laboratorium"
    assert chunks[3].title == "Prosedur Peminjaman"


def test_text_slicer_department_and_memo_boundaries() -> None:
    memo_text = """
MEMORANDUM: PENJADWALAN MATA KULIAH TAHUN AJARAN 2026/2027
Kepada Seluruh Ketua Program Studi dan Tim Penjadwal.
Mohon memperhatikan ketersediaan ruang dan batas SKS.

PROGRAM STUDI: TEKNIK BIOMEDIS
Program studi ini membutuhkan ruang kuliah terintegrasi alat praktikum.
Total ada 14 rombel yang perlu dijadwalkan pada hari Senin-Kamis.

FAKULTAS: KEDOKTERAN GIGI
Jadwal klinik kepaniteraan tidak boleh bertabrakan dengan jadwal kuliah tatap muka.

BAB II: SANKSI KETERLAMBATAN PENGINPUTAN
Keterlambatan input data jadwal akan dikenakan penalti pengalihan ruangan secara otomatis.
"""
    slicer = TextSlicer(max_chunk_chars=1500)
    chunks = slicer.slice_text(memo_text)

    assert len(chunks) == 4
    assert "PENJADWALAN MATA KULIAH" in chunks[0].title
    assert chunks[1].title == "TEKNIK BIOMEDIS"
    assert chunks[2].title == "KEDOKTERAN GIGI"
    assert "BAB II" in chunks[3].title


def test_text_slicer_long_paragraph_packing() -> None:
    # Generate text with 1 large section containing 6 distinct paragraphs
    para_1 = "Paragraf 1: " + ("Aturan perkuliahan mahasiswa tingkat pertama. " * 15)
    para_2 = "Paragraf 2: " + ("Ketentuan praktikum di ruang laboratorium komputer. " * 15)
    para_3 = "Paragraf 3: " + ("Prosedur ujian tengah semester dan akhir semester. " * 15)

    full_text = f"# KETENTUAN AKADEMIK\n\n{para_1}\n\n{para_2}\n\n{para_3}"

    # Set max_chunk_chars to 800 to force splitting
    slicer = TextSlicer(max_chunk_chars=800, preserve_context_breadcrumbs=True)
    chunks = slicer.slice_text(full_text)

    assert len(chunks) > 1
    for c in chunks:
        assert c.char_count <= 1000
        assert c.title == "KETENTUAN AKADEMIK"
    # Breadcrumb verification on continuation chunks
    assert "Lanjutan" in chunks[1].content


def test_text_slicer_file_input(tmp_path: Path) -> None:
    memo_file = tmp_path / "memo.md"
    memo_file.write_text("# UniTime Memo\n\nIsi memorandum penting.", encoding="utf-8")

    slicer = TextSlicer()
    chunks = slicer.slice_file(memo_file)
    assert len(chunks) == 1
    assert chunks[0].title == "UniTime Memo"
    assert chunks[0].source_file == memo_file.resolve()


# ============================================================================
# Regression & Edge Case Tests
# ============================================================================

def test_document_slicer_specialized_dispatch(tmp_path: Path) -> None:
    # 1. Excel dispatch
    wb_path = tmp_path / "test_sched.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Schedule"
    ws.append(["Code", "Course", "Room"])
    ws.append(["IF101", "Programming", "7601"])
    wb.save(str(wb_path))
    wb.close()

    doc_slicer = DocumentSlicer()
    chunks = doc_slicer.slice_file(wb_path)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "text"
    assert "| Code | Course | Room |" in chunks[0].text_content

    # 2. Text memo dispatch
    memo_path = tmp_path / "memo.txt"
    memo_path.write_text("# Formal Notice\nContent of notice.", encoding="utf-8")
    chunks = doc_slicer.slice_file(memo_path)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "text"
    assert "Content of notice." in chunks[0].text_content
    assert chunks[0].metadata["header"] == "Formal Notice"


def test_table_slicer_malformed_csv_extra_columns(tmp_path: Path) -> None:
    # CSV where row 2 has 5 columns while header row only has 3 columns
    csv_file = tmp_path / "ragged.csv"
    csv_file.write_text(
        "Col1,Col2,Col3\n"
        "A,B,C,ExtraVal1,ExtraVal2\n",
        encoding="utf-8",
    )
    slicer = TableSlicer()
    chunks = slicer.slice_all(csv_file)
    assert len(chunks) == 1
    chunk = chunks[0]
    # Verify no columns were dropped and default headers were generated
    assert len(chunk.headers) == 5
    assert chunk.headers[3] == "Column_4"
    assert chunk.headers[4] == "Column_5"
    assert chunk.rows[0][3] == "ExtraVal1"
    assert chunk.rows[0][4] == "ExtraVal2"


def test_text_slicer_giant_sentence_splitting() -> None:
    # 2500-char continuous sentence with max_chunk_chars=500
    huge_sentence = "Rule " + ("ABCDE " * 450) + "end."
    slicer = TextSlicer(max_chunk_chars=500, min_chunk_chars=100)
    chunks = slicer.slice_text(huge_sentence)
    assert len(chunks) > 1
    for c in chunks:
        assert c.char_count <= 500


def test_pdf_slicer_managed_temp_dir_cleanup_on_exit(sample_pdf: Path) -> None:
    temp_dir_path = None
    with PDFSlicer(dpi=150, save_to_disk=True) as slicer:
        temp_dir_path = slicer._managed_temp_dir
        assert temp_dir_path is not None
        assert temp_dir_path.exists()
        _ = slicer.slice_all(sample_pdf)

    # After exiting context manager, managed temp directory must be removed
    assert temp_dir_path is not None
    assert not temp_dir_path.exists()


def test_table_slicer_merged_cells(tmp_path: Path) -> None:
    wb_path = tmp_path / "merged.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MergedSheet"
    
    ws.append(["Department", "", "Code"])
    ws.merge_cells("A1:B1")
    
    ws.append(["Dept A", "Prog 1", "C101"])
    wb.save(str(wb_path))
    wb.close()
    
    slicer = TableSlicer()
    chunks = slicer.slice_all(wb_path)
    assert len(chunks) == 1
    chunk = chunks[0]
    
    assert chunk.headers[0] == "Department"
    assert chunk.headers[1] == "Department_2"
