#!/usr/bin/env python3
"""
generate_xlsx_pdf.py - Multi-Format Academic Schedule Document Generator
========================================================================

Generates production-grade raw source documents for stress-testing the
UniTime AI Ingestion Gateway and automated timetabling solver:
  1. jadwal_itb_multicampus.xlsx:
     - Multi-row header banners (ITB, Semester Ganjil 2024/2025, Multi-Campus Ganesha & Jatinangor).
     - Merged subject code/name cells spanning parallel sections and Lecture+Lab rows.
     - Selected sections with empty/missing room numbers (TBA).
     - Multi-instructor semicolon delimiters ("Dr. Ir. Inggriani Liem; Achmad Imam Kistijantoro, S.T., M.Sc., Ph.D.").
     - Clean professional styling using openpyxl.
  2. katalog_jadwal_itb.pdf:
     - Formal administrative academic timetable document using reportlab.
     - Multi-column table layout, running headers repeating across pages.
     - Footnotes detailing distribution constraints (PRECEDENCE, DIFF_TIME, SAME_ROOM, MEET_WITH).

Part of Milestone M3 (Document Synthesis) for UniTime AI Ingestion Gateway.
Author: worker_doc_xlsx_pdf_3
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Ensure current directory is in python search path
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Import spatial catalog and curriculum model
import curriculum_model as cm
import spatial_catalog as sc

# Spreadsheet styling via openpyxl
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# PDF generation via ReportLab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


# ==============================================================================
# 1. CONSTANTS & MAPPINGS
# ==============================================================================

# Indonesian Day Name Mapping
DAY_NAMES: Dict[str, str] = {
    "M": "Senin",
    "T": "Selasa",
    "W": "Rabu",
    "Th": "Kamis",
    "F": "Jumat",
    "MW": "Senin & Rabu",
    "TTh": "Selasa & Kamis",
}

# Subpart Component Labeling in Indonesian
COMPONENT_LABELS: Dict[str, str] = {
    "Lecture": "Kuliah",
    "Lab": "Praktikum",
    "Responsi": "Responsi",
    "Tutorial": "Tutorial",
}

# Building to Campus & Display Name Mapping
BUILDING_DISPLAY_MAP: Dict[str, Tuple[str, str]] = {
    "Labtek V Benny Subianto": ("Kampus Ganesha", "Labtek V"),
    "Labtek VIII Achmad Bakrie": ("Kampus Ganesha", "Labtek VIII"),
    "Labtek III Matthias Aroef": ("Kampus Ganesha", "Labtek III"),
    "Gedung Kuliah Umum Barat": ("Kampus Ganesha", "GKUB"),
    "GKU Barat (GK-1)": ("Kampus Ganesha", "GKUB"),
    "Gedung Kuliah Umum 1 Jatinangor": ("Kampus Jatinangor", "GKU-1"),
    "Gedung KOICA": ("Kampus Jatinangor", "KOICA"),
    "Lab Terpadu Jatinangor": ("Kampus Jatinangor", "Lab Terpadu"),
}

# Sections deliberately marked as TBA (empty / unassigned rooms)
# Demonstrates realistic administrative timetable edge case
TBA_SECTIONS: Set[Tuple[str, str]] = {
    ("KU1102", "L01"),  # TPB Berpikir Komputasional Praktikum L01
    ("KU1102", "L02"),  # TPB Berpikir Komputasional Praktikum L02
    ("IF3110", "L01"),  # PBP Praktikum L01
    ("SI3102", "R01"),  # Manajemen Layanan TI Responsi R01
    ("EL3101", "L01"),  # Sistem Tertanam Praktikum L01
    ("TI2104", "R01"),  # Pengendalian Mutu Responsi R01
}


# ==============================================================================
# 2. DATA AGGREGATION & PREPARATION
# ==============================================================================

def get_prepared_schedule_data() -> List[Dict[str, Any]]:
    """
    Extracts and normalizes all 28 courses and 84 classes from curriculum_model.
    
    Returns structured list of course records with their sections, time slots,
    room assignments, multi-instructor semicolon strings, and campus info.
    """
    courses = cm.get_courses()
    
    # Logical ordering: TPB first, then IF, SI, EL, TI
    dept_order = {"TPB": 0, "IF": 1, "SI": 2, "EL": 3, "TI": 4}
    sorted_courses = sorted(
        courses,
        key=lambda c: (dept_order.get(c.get("departmentCode", ""), 99), c.get("courseNumber", ""))
    )

    prepared_courses: List[Dict[str, Any]] = []

    for course in sorted_courses:
        c_num = course.get("courseNumber", "")
        c_title = course.get("title", "")
        dept = course.get("departmentCode", "")
        sks = course.get("credit", {}).get("units", 0)

        # Collect classes for this course
        sections: List[Dict[str, Any]] = []
        for cfg in course.get("configurations", []):
            cfg_name = cfg.get("name", "")
            for sp in cfg.get("subparts", []):
                sp_type = sp.get("type", "Lecture")
                comp_label = COMPONENT_LABELS.get(sp_type, sp_type)
                
                for cl in sp.get("classes", []):
                    sec_name = cl.get("sectionName", "")
                    cap = cl.get("capacity", 40)

                    # Instructor string with semicolon delimiters
                    inst_names = [i.get("name", "") for i in cl.get("instructors", []) if i.get("name")]
                    instructor_str = "; ".join(inst_names) if inst_names else "Tim Dosen TBA"

                    # Time preferences
                    time_prefs = cl.get("timePreferences", [])
                    if time_prefs:
                        tp = time_prefs[0]
                        day_code = tp.get("days", "")
                        day_name = DAY_NAMES.get(day_code, day_code)
                        start_time = tp.get("startTime", "")
                        end_time = tp.get("endTime", "")
                        time_str = f"{start_time} - {end_time}"
                        schedule_str = f"{day_name}, {time_str}"
                    else:
                        day_name = "TBA"
                        time_str = "TBA"
                        schedule_str = "Jadwal TBA"

                    # Room preferences & TBA handling
                    is_tba = (c_num, sec_name) in TBA_SECTIONS
                    room_prefs = cl.get("roomPreferences", [])
                    raw_bld = room_prefs[0].get("building", "") if room_prefs else ""
                    raw_rm = room_prefs[0].get("roomNumber", "") if room_prefs else ""

                    campus_info, bld_display = BUILDING_DISPLAY_MAP.get(
                        raw_bld, ("Kampus Ganesha", raw_bld if raw_bld else "Gedung TBA")
                    )

                    if is_tba:
                        bld_col = "TBA"
                        rm_col = ""  # Empty/missing room cell
                        room_display_pdf = "TBA (Ruang Belum Ditentukan)"
                    else:
                        bld_col = bld_display
                        rm_col = raw_rm
                        room_display_pdf = f"{bld_display} {raw_rm}"

                    sections.append({
                        "sectionName": sec_name,
                        "subpartType": sp_type,
                        "component": comp_label,
                        "capacity": cap,
                        "day": day_name,
                        "time": time_str,
                        "scheduleText": schedule_str,
                        "campus": campus_info,
                        "building": bld_col,
                        "room": rm_col,
                        "roomDisplayPdf": f"{campus_info.replace('Kampus ', '')}: {room_display_pdf}",
                        "isTba": is_tba,
                        "instructors": instructor_str,
                        "instructorsList": inst_names,
                    })

        # Sort sections within course: Lecture (K) first, then Tutorial (T), Lab (L), Responsi (R)
        subpart_order = {"Lecture": 0, "Tutorial": 1, "Lab": 2, "Responsi": 3}
        sections.sort(key=lambda s: (subpart_order.get(s["subpartType"], 9), s["sectionName"]))

        prepared_courses.append({
            "courseNumber": c_num,
            "title": c_title,
            "departmentCode": dept,
            "sks": sks,
            "sections": sections,
        })

    return prepared_courses


# ==============================================================================
# 3. EXCEL SPREADSHEET GENERATION (openpyxl)
# ==============================================================================

def generate_excel_timetable(output_path: Path, courses_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generates jadwal_itb_multicampus.xlsx using openpyxl.
    
    Features:
      - Multi-row header banners (ITB, Semester Ganjil 2024/2025, Multi-Campus).
      - Merged subject code, name, and SKS cells spanning parallel sections & Lecture+Lab rows.
      - Selected sections with empty/missing room numbers (TBA).
      - Multi-instructor semicolon delimiters.
      - Clean professional academic palette (Navy/Slate) with alternating course blocks.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jadwal_MultiKampus"

    # Ensure gridlines are visible
    ws.views.sheetView[0].showGridLines = True

    # Palette styles
    font_family = "Arial"
    navy_dark = "1F497D"
    slate_blue = "2E5B82"
    border_color = "D9D9D9"
    zebra_tint = "F2F5F8"

    thin_border = Border(
        left=Side(style="thin", color=border_color),
        right=Side(style="thin", color=border_color),
        top=Side(style="thin", color=border_color),
        bottom=Side(style="thin", color=border_color),
    )

    thick_bottom_border = Border(
        left=Side(style="thin", color=border_color),
        right=Side(style="thin", color=border_color),
        top=Side(style="thin", color=border_color),
        bottom=Side(style="medium", color=navy_dark),
    )

    # --- Header Banners (Rows 1-3) ---
    # Merge only columns A to E (5 columns) so TableSlicer's smart detection detects
    # row 5 (13 columns) as the definitive table header without ambiguity.
    ws.merge_cells("A1:E1")
    cell_a1 = ws["A1"]
    cell_a1.value = "INSTITUT TEKNOLOGI BANDUNG"
    cell_a1.font = Font(name=font_family, size=14, bold=True, color=navy_dark)
    cell_a1.alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells("A2:E2")
    cell_a2 = ws["A2"]
    cell_a2.value = "JADWAL PERKULIAHAN & PRAKTIKUM SEMESTER GANJIL 2024/2025"
    cell_a2.font = Font(name=font_family, size=11, bold=True, color="333333")
    cell_a2.alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells("A3:E3")
    cell_a3 = ws["A3"]
    cell_a3.value = "MULTI-KAMPUS: KAMPUS GANESHA & KAMPUS JATINANGOR (IF, SI, EL, TI, TPB)"
    cell_a3.font = Font(name=font_family, size=10, italic=True, color="595959")
    cell_a3.alignment = Alignment(horizontal="left", vertical="center")

    # Row 4: Empty separator row
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 20
    ws.row_dimensions[3].height = 18
    ws.row_dimensions[4].height = 10

    # --- Table Column Headers (Row 5) ---
    headers = [
        "Kode MK",
        "Nama Mata Kuliah",
        "SKS",
        "Program Studi",
        "Komponen",
        "Kelas",
        "Kapasitas",
        "Hari",
        "Waktu",
        "Kampus",
        "Gedung",
        "Ruang",
        "Dosen Pengampu",
    ]

    header_fill = PatternFill(start_color=navy_dark, end_color=navy_dark, fill_type="solid")
    header_font = Font(name=font_family, size=10, bold=True, color="FFFFFF")

    ws.row_dimensions[5].height = 26
    for col_idx, h_text in enumerate(headers, start=1):
        cell = ws.cell(row=5, column=col_idx, value=h_text)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thick_bottom_border

    # --- Data Rows (Row 6 onwards) ---
    current_row = 6
    total_sections_count = 0
    tba_count = 0
    merged_ranges_count = 0

    for course_idx, c_data in enumerate(courses_data):
        c_num = c_data["courseNumber"]
        c_title = c_data["title"]
        sks = c_data["sks"]
        dept = c_data["departmentCode"]
        sections = c_data["sections"]
        sec_count = len(sections)

        start_row = current_row
        end_row = current_row + sec_count - 1

        # Alternate course block background fill
        bg_fill = (
            PatternFill(start_color=zebra_tint, end_color=zebra_tint, fill_type="solid")
            if (course_idx % 2 == 1)
            else PatternFill(fill_type=None)
        )

        for sec_offset, sec in enumerate(sections):
            r = current_row + sec_offset
            total_sections_count += 1
            ws.row_dimensions[r].height = 20

            if sec["isTba"]:
                tba_count += 1

            # Populate cells
            ws.cell(row=r, column=1, value=c_num)
            ws.cell(row=r, column=2, value=c_title)
            ws.cell(row=r, column=3, value=sks)
            ws.cell(row=r, column=4, value=dept)
            ws.cell(row=r, column=5, value=sec["component"])
            ws.cell(row=r, column=6, value=sec["sectionName"])
            ws.cell(row=r, column=7, value=sec["capacity"])
            ws.cell(row=r, column=8, value=sec["day"])
            ws.cell(row=r, column=9, value=sec["time"])
            ws.cell(row=r, column=10, value=sec["campus"])
            ws.cell(row=r, column=11, value=sec["building"])
            # Empty / missing room cell for TBA sections
            ws.cell(row=r, column=12, value=sec["room"] if sec["room"] else "")
            # Multi-instructor semicolon string
            ws.cell(row=r, column=13, value=sec["instructors"])

            # Apply font, alignment, border, fill
            for c_idx in range(1, 14):
                cell = ws.cell(row=r, column=c_idx)
                cell.font = Font(name=font_family, size=9)
                cell.border = thin_border
                if bg_fill.fill_type:
                    cell.fill = bg_fill

                # Alignment rules
                if c_idx in (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        # Merge course-level attributes spanning parallel sections & Lecture+Lab rows
        if sec_count > 1:
            # Merge Kode MK (col 1)
            ws.merge_cells(start_row=start_row, start_column=1, end_row=end_row, end_column=1)
            # Merge Nama Mata Kuliah (col 2)
            ws.merge_cells(start_row=start_row, start_column=2, end_row=end_row, end_column=2)
            # Merge SKS (col 3)
            ws.merge_cells(start_row=start_row, start_column=3, end_row=end_row, end_column=3)
            # Merge Program Studi (col 4)
            ws.merge_cells(start_row=start_row, start_column=4, end_row=end_row, end_column=4)
            merged_ranges_count += 4

            # Re-align merged anchor cells
            ws.cell(row=start_row, column=1).alignment = Alignment(horizontal="center", vertical="center")
            ws.cell(row=start_row, column=2).alignment = Alignment(horizontal="left", vertical="center")
            ws.cell(row=start_row, column=3).alignment = Alignment(horizontal="center", vertical="center")
            ws.cell(row=start_row, column=4).alignment = Alignment(horizontal="center", vertical="center")

        current_row += sec_count

    # Freeze panes below table headers
    ws.freeze_panes = "A6"

    # Set explicit ergonomic column widths
    column_widths = {
        "A": 12,  # Kode MK
        "B": 32,  # Nama Mata Kuliah
        "C": 6,   # SKS
        "D": 14,  # Program Studi
        "E": 12,  # Komponen
        "F": 8,   # Kelas
        "G": 10,  # Kapasitas
        "H": 15,  # Hari
        "I": 15,  # Waktu
        "J": 18,  # Kampus
        "K": 15,  # Gedung
        "L": 10,  # Ruang
        "M": 50,  # Dosen Pengampu
    }
    for col_letter, width in column_widths.items():
        ws.column_dimensions[col_letter].width = width

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    wb.close()

    return {
        "output_path": str(output_path),
        "total_courses": len(courses_data),
        "total_sections": total_sections_count,
        "tba_sections": tba_count,
        "merged_ranges": merged_ranges_count,
    }


# ==============================================================================
# 4. REPORTLAB NUMBERED CANVAS (Running Headers & Footers)
# ==============================================================================

class AcademicNumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that draws running headers, running footers, and dynamic
    'Halaman X dari Y' page numbering across all pages.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_running_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_running_decorations(self, total_pages: int) -> None:
        self.saveState()

        # Coordinates for landscape A4 (width 841.89 pt, height 595.27 pt)
        page_width = 841.89
        page_height = 595.27
        margin_x = 30.0

        # --- Running Header (Pages 2+) ---
        if self._pageNumber > 1:
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(colors.HexColor("#003366"))
            self.drawString(margin_x, page_height - 25, "INSTITUT TEKNOLOGI BANDUNG — DIREKTORAT PENDIDIKAN")

            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#555555"))
            header_right = "KATALOG JADWAL PERKULIAHAN & DISTRIBUSI KELAS (GANJIL 2024/2025)"
            self.drawRightString(page_width - margin_x, page_height - 25, header_right)

            # Thin header rule
            self.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.setLineWidth(0.5)
            self.line(margin_x, page_height - 28, page_width - margin_x, page_height - 28)

        # --- Running Footer (All Pages) ---
        footer_y = 22.0
        self.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.setLineWidth(0.5)
        self.line(margin_x, footer_y + 10, page_width - margin_x, footer_y + 10)

        self.setFont("Helvetica", 7)
        self.setFillColor(colors.HexColor("#666666"))
        footer_left = "Sistem Informasi Akademik ITB | Kampus Ganesha & Kampus Jatinangor (Prodi IF, SI, EL, TI, TPB)"
        self.drawString(margin_x, footer_y, footer_left)

        self.setFont("Helvetica-Bold", 7.5)
        self.setFillColor(colors.HexColor("#003366"))
        footer_right = f"Halaman {self._pageNumber} dari {total_pages}"
        self.drawRightString(page_width - margin_x, footer_y, footer_right)

        self.restoreState()


# ==============================================================================
# 5. PDF ACADEMIC CATALOG GENERATION (ReportLab Platypus)
# ==============================================================================

def generate_pdf_catalog(output_path: Path, courses_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generates katalog_jadwal_itb.pdf using reportlab.
    
    Features:
      - Formal administrative academic timetable document layout.
      - Multi-column table layout with repeatRows=1 repeating table headers across pages.
      - Running headers and footers with page numbers via AcademicNumberedCanvas.
      - Comprehensive footnotes detailing distribution constraints (PRECEDENCE, DIFF_TIME, SAME_ROOM, MEET_WITH).
      - Administrative seal and certification signatory block.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=landscape(A4),
        leftMargin=30,
        rightMargin=30,
        topMargin=35,
        bottomMargin=35,
    )

    styles = getSampleStyleSheet()

    # Custom Paragraph Styles
    style_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#003366"),
        alignment=0,
    )

    style_subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#444444"),
        alignment=0,
    )

    style_tbl_header = ParagraphStyle(
        "TblHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        alignment=1,
    )

    style_cell_center = ParagraphStyle(
        "CellCenter",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        alignment=1,
    )

    style_cell_left = ParagraphStyle(
        "CellLeft",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        alignment=0,
    )

    style_cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8.5,
        alignment=0,
    )

    style_fn_h1 = ParagraphStyle(
        "FootnoteH1",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#003366"),
        spaceBefore=10,
        spaceAfter=4,
    )

    style_fn_h2 = ParagraphStyle(
        "FootnoteH2",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1F497D"),
        spaceBefore=6,
        spaceAfter=2,
    )

    style_fn_body = ParagraphStyle(
        "FootnoteBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#222222"),
        spaceAfter=2,
    )

    story: List[Any] = []

    # --- Document Header Banner (Page 1) ---
    story.append(Paragraph("INSTITUT TEKNOLOGI BANDUNG — DIREKTORAT PENDIDIKAN", style_title))
    story.append(
        Paragraph(
            "KATALOG RESMI JADWAL PERKULIAHAN, PRAKTIKUM, DAN DISTRIBUSI KELAS "
            "SEMESTER GANJIL 2024/2025<br/>"
            "<b>Cakupan Multi-Kampus:</b> Kampus Ganesha (Bandung) & Kampus Jatinangor (Sumedang) | "
            "<b>Program Studi:</b> Teknik Informatika (IF), Sistem Informasi (SI), Teknik Elektro (EL), "
            "Teknik Industri (TI), dan TPB STEI/FTI (Total 28 Mata Kuliah, 84 Kelas)",
            style_subtitle,
        )
    )
    story.append(Spacer(1, 8))

    # --- Timetable Table ---
    # Column widths summing exactly to 781.89 pt (printable width)
    # [No, Kode, Mata Kuliah, SKS, Komp, Seksi, Kps, Hari & Waktu, Kampus & Ruang, Tim Dosen]
    col_widths = [20, 42, 128, 22, 45, 30, 25, 88, 114, 287]

    table_data: List[List[Any]] = []

    # Table Header Row
    table_data.append([
        Paragraph("No.", style_tbl_header),
        Paragraph("Kode", style_tbl_header),
        Paragraph("Nama Mata Kuliah", style_tbl_header),
        Paragraph("SKS", style_tbl_header),
        Paragraph("Komp.", style_tbl_header),
        Paragraph("Seksi", style_tbl_header),
        Paragraph("Kps.", style_tbl_header),
        Paragraph("Hari & Waktu", style_tbl_header),
        Paragraph("Kampus & Ruang", style_tbl_header),
        Paragraph("Dosen Pengampu / Tim Dosen", style_tbl_header),
    ])

    row_index = 1
    table_styles: List[Any] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003366")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
    ]

    total_table_rows = 0

    for c_idx, c_data in enumerate(courses_data):
        c_num = c_data["courseNumber"]
        c_title = c_data["title"]
        sks = c_data["sks"]
        sections = c_data["sections"]

        for sec in sections:
            total_table_rows += 1
            bg_color = colors.HexColor("#F8FAFC") if (row_index % 2 == 0) else colors.white
            table_styles.append(("BACKGROUND", (0, row_index), (-1, row_index), bg_color))

            row_cells = [
                Paragraph(str(row_index), style_cell_center),
                Paragraph(c_num, style_cell_bold),
                Paragraph(c_title, style_cell_left),
                Paragraph(str(sks), style_cell_center),
                Paragraph(sec["component"], style_cell_center),
                Paragraph(sec["sectionName"], style_cell_bold),
                Paragraph(str(sec["capacity"]), style_cell_center),
                Paragraph(sec["scheduleText"], style_cell_left),
                Paragraph(sec["roomDisplayPdf"], style_cell_left),
                Paragraph(sec["instructors"], style_cell_left),
            ]
            table_data.append(row_cells)
            row_index += 1

    # repeatRows=1 ensures header row repeats automatically on every page split
    timetable_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    timetable_table.setStyle(TableStyle(table_styles))
    story.append(timetable_table)

    # --- Footnotes: Academic Distribution Constraints (Clean Page Break) ---
    story.append(PageBreak())
    story.append(KeepTogether([
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#003366"), spaceBefore=4, spaceAfter=6),
        Paragraph("CATATAN RESMI KENDALA DISTRIBUSI PENJADWALAN (ACADEMIC DISTRIBUTION CONSTRAINTS)", style_fn_h1),
        Paragraph(
            "Berikut adalah spesifikasi kendala distribusi formal yang wajib dipenuhi oleh UniTime Solver engine "
            "dalam memvalidasi dan memetakan jadwal perkuliahan Semester Ganjil 2024/2025:",
            style_fn_body,
        ),
    ]))

    constraints = cm.get_distribution_constraints()

    # Categorize constraints by type
    cat_precedence = [c for c in constraints if c.get("type", "").upper() == "PRECEDENCE"]
    cat_diff_time = [c for c in constraints if c.get("type", "").upper() in ("DIFF_TIME", "CANNOT_OVERLAP")]
    cat_same_room = [c for c in constraints if c.get("type", "").upper() in ("SAME_ROOM", "SAME_SPACE")]
    cat_meet_with = [c for c in constraints if c.get("type", "").upper() in ("MEET_WITH", "MEET_TOGETHER")]
    cat_btb = [c for c in constraints if c.get("type", "").upper() in ("BTB", "BACK_TO_BACK")]

    def format_constraint_block(title: str, items: List[Dict[str, Any]], code_prefix: str) -> List[Any]:
        elements: List[Any] = []
        elements.append(Paragraph(f"<b>{title}</b> (Total: {len(items)} Kendala)", style_fn_h2))
        for idx, item in enumerate(items, start=1):
            c_type = item.get("type", code_prefix)
            c_num = item.get("courseNumber", "")
            note = item.get("note", "")
            level = item.get("level", "REQUIRED")
            classes_str = ", ".join(
                f"{cl.get('courseNumber', '')} {cl.get('sectionName', '')} ({cl.get('subpartType', '')})"
                for cl in item.get("classes", [])
            )
            c_desc = f"<b>[{c_type}] {idx}. {c_num if c_num else 'Lintas-Mata Kuliah'}:</b> {note} " \
                     f"<i>(Level: {level}; Kelas Terikat: {classes_str})</i>"
            elements.append(Paragraph(c_desc, style_fn_body))
        return elements

    story.append(KeepTogether(format_constraint_block("A. PRECEDENCE — Keterurutan Kuliah Teori Mendahului Praktikum", cat_precedence, "PRECEDENCE")))
    story.append(KeepTogether(format_constraint_block("B. DIFF_TIME — Larangan Konflik Waktu Sesi Wajib Paralel (Cannot Overlap)", cat_diff_time, "DIFF_TIME")))
    story.append(KeepTogether(format_constraint_block("C. SAME_ROOM — Alokasi Ruang Laboratorium Spesifik yang Sama", cat_same_room, "SAME_ROOM")))
    story.append(KeepTogether(format_constraint_block("D. MEET_WITH — Sesi Kuliah Bersama / Shared Section", cat_meet_with, "MEET_WITH")))
    story.append(KeepTogether(format_constraint_block("E. BACK_TO_BACK — Sesi Perkuliahan Berurutan Tanpa Jeda", cat_btb, "BTB")))

    # --- Administrative Signatures Block ---
    story.append(Spacer(1, 10))
    sig_text_1 = "<b>Disahkan di Bandung, 15 Agustus 2024</b><br/>" \
                 "Direktur Pendidikan ITB<br/><br/><br/><br/>" \
                 "<b>Prof. Dr. Ir. Jaka Sembiring, M.Eng.</b><br/>" \
                 "NIP. 196402171989031002"

    sig_text_2 = "Mengetahui,<br/>" \
                 "Dekan Sekolah Teknik Elektro & Informatika (STEI)<br/><br/><br/><br/>" \
                 "<b>Dr. Tutun Juhana, S.T., M.T.</b><br/>" \
                 "NIP. 197105151996011001"

    sig_text_3 = "Mengetahui,<br/>" \
                 "Dekan Fakultas Teknologi Industri (FTI)<br/><br/><br/><br/>" \
                 "<b>Prof. Dr. Ir. Kadarsah Suryadi, DEA</b><br/>" \
                 "NIP. 196202221986011001"

    style_sig = ParagraphStyle(
        "SigStyle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=10,
        alignment=1,
    )

    sig_table = Table(
        [[Paragraph(sig_text_1, style_sig), Paragraph(sig_text_2, style_sig), Paragraph(sig_text_3, style_sig)]],
        colWidths=[260, 260, 261],
    )
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    story.append(KeepTogether([
        HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#888888"), spaceBefore=8, spaceAfter=8),
        sig_table,
    ]))

    doc.build(story, canvasmaker=AcademicNumberedCanvas)

    return {
        "output_path": str(output_path),
        "total_courses": len(courses_data),
        "total_sections": total_table_rows,
        "total_constraints": len(constraints),
    }


# ==============================================================================
# 6. MAIN ORCHESTRATION & CLI INTERFACE
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate ITB Multi-Campus Academic Schedule Documents (Excel & PDF)."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(_SCRIPT_DIR),
        help="Target output directory for generated files (default: ai-gateway/test_data_robustness)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    excel_path = out_dir / "jadwal_itb_multicampus.xlsx"
    pdf_path = out_dir / "katalog_jadwal_itb.pdf"

    print("=" * 78)
    print("UniTime AI Ingestion Gateway - Excel & PDF Document Synthesis (M3-A)")
    print("=" * 78)
    print(f"Target Output Directory: {out_dir}")

    # 1. Load data
    print("\n[Step 1/3] Loading curriculum model & facility topology...")
    courses_data = get_prepared_schedule_data()
    print(f"  Loaded {len(courses_data)} courses across TPB, IF, SI, EL, TI.")
    total_sec = sum(len(c["sections"]) for c in courses_data)
    print(f"  Total sections/classes: {total_sec}")

    # 2. Generate Excel
    print("\n[Step 2/3] Generating Excel spreadsheet (jadwal_itb_multicampus.xlsx)...")
    xl_res = generate_excel_timetable(excel_path, courses_data)
    print(f"  Excel generated at: {xl_res['output_path']}")
    print(f"  Courses: {xl_res['total_courses']} | Sections: {xl_res['total_sections']}")
    print(f"  TBA Sections: {xl_res['tba_sections']} | Merged Ranges: {xl_res['merged_ranges']}")
    print(f"  File size: {excel_path.stat().st_size:,} bytes")

    # 3. Generate PDF
    print("\n[Step 3/3] Generating academic catalog PDF (katalog_jadwal_itb.pdf)...")
    pdf_res = generate_pdf_catalog(pdf_path, courses_data)
    print(f"  PDF generated at: {pdf_res['output_path']}")
    print(f"  Courses: {pdf_res['total_courses']} | Table Rows: {pdf_res['total_sections']}")
    print(f"  Distribution Constraints Footnotes: {pdf_res['total_constraints']}")
    print(f"  File size: {pdf_path.stat().st_size:,} bytes")

    print("\n" + "=" * 78)
    print("Document synthesis completed successfully!")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
