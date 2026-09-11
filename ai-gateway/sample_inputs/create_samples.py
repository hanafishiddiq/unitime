#!/usr/bin/env python3
"""UniTime AI Ingestion Gateway - Sample Input Generator.

Generates realistic sample input files (.txt, .xlsx, .pdf) for testing the
UniTime AI Ingestion Gateway end-to-end pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pandas as pd
import pymupdf  # fitz

SAMPLE_DIR = Path(__file__).resolve().parent


def create_sample_excel(output_path: Path) -> None:
    """Generate realistic Excel timetable spreadsheet."""
    data = [
        # IF2110
        ["IF2110", "Algoritma & Struktur Data", 4, "Teori", "K01", 45, "Senin", "07.00 - 09.30", "Labtek V", "7601", "Dr. Eng. Ayu Pratama (PJMK), Budi Raharjo, M.Kom."],
        ["IF2110", "Algoritma & Struktur Data", 4, "Teori", "K02", 45, "Rabu", "07.00 - 09.30", "Labtek V", "7602", "Dr. Eng. Ayu Pratama (PJMK), Ahmad Fauzi, M.Cs."],
        ["IF2110", "Algoritma & Struktur Data", 4, "Praktikum", "L01", 25, "Selasa", "13.00 - 15.00", "Labtek V", "Lab-1", "Dr. Eng. Ayu Pratama (PJMK)"],
        ["IF2110", "Algoritma & Struktur Data", 4, "Praktikum", "L02", 25, "Kamis", "13.00 - 15.00", "Labtek V", "Lab-1", "Dr. Eng. Ayu Pratama (PJMK)"],
        # IF2120
        ["IF2120", "Matematika Diskrit", 3, "Teori", "K01", 50, "Selasa", "07.00 - 09.30", "GK-1", "9001", "Prof. Dr. Hendra Wijaya"],
        ["IF2120", "Matematika Diskrit", 3, "Teori", "K02", 50, "Kamis", "07.00 - 09.30", "GK-1", "9002", "Prof. Dr. Hendra Wijaya"],
        # IF3150
        ["IF3150", "Manajemen Proyek PL", 3, "Teori", "K01", 40, "Senin", "10.00 - 11.40", "Labtek V", "7601", "Dr. Bambang Supeno"],
        ["IF3150", "Manajemen Proyek PL", 3, "Teori", "K02", 40, "Rabu", "10.00 - 11.40", "Labtek V", "7601", "Dr. Bambang Supeno"],
        ["IF3150", "Manajemen Proyek PL", 3, "Responsi", "R01", 40, "Senin", "13.00 - 14.00", "Labtek V", "7601", "Dr. Bambang Supeno"],
    ]

    columns = [
        "Kode MK",
        "Mata Kuliah",
        "SKS",
        "Komponen",
        "Kelas",
        "Kapasitas",
        "Hari",
        "Waktu",
        "Gedung",
        "Ruang",
        "Dosen Pengampu",
    ]

    df = pd.DataFrame(data, columns=columns)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jadwal Ganjil 2024"

    # Title block
    ws.merge_cells("A1:K1")
    title_cell = ws["A1"]
    title_cell.value = "JADWAL PERKULIAHAN SEMESTER GANJIL 2024/2025 - TEKNIK INFORMATIKA"
    title_cell.font = Font(name="Arial", size=13, bold=True, color="1F497D")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("A2:K2")
    sub_cell = ws["A2"]
    sub_cell.value = "INSTITUT TEKNOLOGI BANDUNG - KAMPUS GANESHA"
    sub_cell.font = Font(name="Arial", size=10, italic=True, color="595959")
    sub_cell.alignment = Alignment(horizontal="center", vertical="center")

    # Header row
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    for col_idx, col_name in enumerate(columns, start=1):
        cell = ws.cell(row=4, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Data rows
    zebra_fill = PatternFill(start_color="F2F5F8", end_color="F2F5F8", fill_type="solid")
    for row_idx, row_data in enumerate(data, start=5):
        fill = zebra_fill if row_idx % 2 == 0 else PatternFill(fill_type=None)
        for col_idx, val in enumerate(row_data, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = Font(name="Arial", size=9)
            cell.border = thin_border
            if fill.fill_type:
                cell.fill = fill
            align_h = "center" if col_idx in (1, 3, 4, 5, 6, 7, 8, 10) else "left"
            cell.alignment = Alignment(horizontal=align_h, vertical="center")

    # Auto-adjust column widths
    for col_idx, col in enumerate(ws.columns, start=1):
        col_letter = openpyxl.utils.get_column_letter(col_idx)
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 10)

    wb.save(str(output_path))
    print(f"Created sample Excel file at: {output_path}")


def create_sample_pdf(output_path: Path) -> None:
    """Generate realistic PDF schedule document using PyMuPDF."""
    doc = pymupdf.open()

    # Page 1: Official Header & Semester 3 Courses (IF2110 & IF2120)
    page1 = doc.new_page(width=595, height=842)  # A4

    header_text = (
        "KEMENTERIAN PENDIDIKAN, KEBUDAYAAN, RISET, DAN TEKNOLOGI\n"
        "INSTITUT TEKNOLOGI BANDUNG - SEKOLAH TEKNIK ELEKTRO DAN INFORMATIKA\n"
        "PROGRAM STUDI TEKNIK INFORMATIKA (KAMPUS GANESHA)\n"
        "----------------------------------------------------------------------------------------------------\n"
        "JADWAL PERKULIAHAN & PRAKTIKUM SEMESTER GANJIL 2024/2025\n"
        "Halaman 1 dari 2: Mata Kuliah Tingkat II (Semester 3)\n"
        "----------------------------------------------------------------------------------------------------\n\n"
        "1. IF2110 ALGORITMA DAN STRUKTUR DATA (4 SKS: 3 SKS Kuliah + 1 SKS Praktikum)\n"
        "   - Kelas K01 (Teori) : Senin, 07:00 - 09:30 | Ruang: Labtek V 7601 | Kuota: 45 mhs\n"
        "     Dosen: Dr. Eng. Ayu Pratama, S.T., M.T. (PJMK, 50%), Budi Raharjo, M.Kom. (50%)\n"
        "   - Kelas K02 (Teori) : Rabu, 07:00 - 09:30  | Ruang: Labtek V 7602 | Kuota: 45 mhs\n"
        "     Dosen: Dr. Eng. Ayu Pratama, S.T., M.T. (PJMK, 50%), Ahmad Fauzi, M.Cs. (50%)\n"
        "   - Kelas L01 (Lab)   : Selasa, 13:00 - 15:00| Ruang: Labtek V Lab-1| Kuota: 25 mhs\n"
        "     Dosen/Asisten: Dr. Eng. Ayu Pratama (100%)\n"
        "   - Kelas L02 (Lab)   : Kamis, 13:00 - 15:00 | Ruang: Labtek V Lab-1| Kuota: 25 mhs\n"
        "     Dosen/Asisten: Dr. Eng. Ayu Pratama (100%)\n\n"
        "2. IF2120 MATEMATIKA DISKRIT (3 SKS Kuliah)\n"
        "   - Kelas K01 (Teori) : Selasa, 07:00 - 09:30 | Ruang: GK-1 9001 | Kuota: 50 mhs\n"
        "     Dosen: Prof. Dr. Hendra Wijaya (100%)\n"
        "   - Kelas K02 (Teori) : Kamis, 07:00 - 09:30  | Ruang: GK-1 9002 | Kuota: 50 mhs\n"
        "     Dosen: Prof. Dr. Hendra Wijaya (100%)\n\n"
        "Catatan Distribusi Semester 3:\n"
        "* Kuliah IF2110 K01 dan K02 diajar oleh Dr. Eng. Ayu Pratama: WAKTU TIDAK BOLEH BENTROK (DIFF_TIME).\n"
        "* Kuliah teori IF2110 K01 harus mendahului praktikum L01 (PRECEDENCE).\n"
        "* Praktikum L01 dan L02 harus di ruangan Lab Komputer 1 (SAME_ROOM).\n"
    )

    page1.insert_text(pymupdf.Point(40, 50), header_text, fontsize=9, fontname="helv")

    # Page 2: Semester 5 Courses (IF3150) & Approval Signatures
    page2 = doc.new_page(width=595, height=842)

    page2_text = (
        "INSTITUT TEKNOLOGI BANDUNG - TEKNIK INFORMATIKA\n"
        "JADWAL PERKULIAHAN SEMESTER GANJIL 2024/2025\n"
        "Halaman 2 dari 2: Mata Kuliah Tingkat III (Semester 5)\n"
        "----------------------------------------------------------------------------------------------------\n\n"
        "3. IF3150 MANAJEMEN PROYEK PERANGKAT LUNAK (3 SKS: 2 SKS Kuliah + 1 SKS Responsi)\n"
        "   - Kelas K01 (Teori)   : Senin, 10:00 - 11:40 | Ruang: Labtek V 7601 | Kuota: 40 mhs\n"
        "     Dosen: Dr. Bambang Supeno (100%)\n"
        "   - Kelas K02 (Teori)   : Rabu, 10:00 - 11:40  | Ruang: Labtek V 7601 | Kuota: 40 mhs\n"
        "     Dosen: Dr. Bambang Supeno (100%)\n"
        "   - Kelas R01 (Responsi): Senin, 13:00 - 14:00 | Ruang: Labtek V 7601 | Kuota: 40 mhs\n"
        "     Dosen: Dr. Bambang Supeno (100%)\n\n"
        "Catatan Distribusi Semester 5:\n"
        "* Kuliah IF2110 K01 dan IF3150 K01 diusahakan berturutan (BACK_TO_BACK) di Labtek V 7601.\n"
        "* Jeda antara kuliah IF3150 K01 dan responsi R01 maksimal 2 jam (AT_MOST_2_HOURS_APART).\n\n"
        "----------------------------------------------------------------------------------------------------\n"
        "Disahkan di Bandung pada 15 Agustus 2024\n"
        "Ketua Program Studi Sarjana Teknik Informatika\n\n\n"
        "Dr. Ir. Rinaldi Munir, M.T.\n"
        "NIP. 196611081993021001\n"
    )

    page2.insert_text(pymupdf.Point(40, 50), page2_text, fontsize=9, fontname="helv")

    doc.save(str(output_path))
    doc.close()
    print(f"Created sample PDF file at: {output_path}")


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    excel_path = SAMPLE_DIR / "jadwal_kuliah_if.xlsx"
    pdf_path = SAMPLE_DIR / "jadwal_kuliah_if.pdf"

    create_sample_excel(excel_path)
    create_sample_pdf(pdf_path)
    print("All sample input files generated successfully!")


if __name__ == "__main__":
    main()
