"""
generate_txt_json.py - Milestone M3 Part B: Narrative Text & Canonical Schema JSON
===================================================================================
UniTime AI Ingestion Gateway Robustness Test Suite & Benchmark

This module imports `spatial_catalog` and `curriculum_model` to synthesize:
1. `memo_dekan_jadwal.txt`:
   - Formal administrative directive / memorandum from the Dean of STEI & FTI ITB.
   - Room preference requests (e.g. Labtek V 7601, Lab-1 for GPU workstations, Labtek VIII Lab-El).
   - Instructor day-off/time constraints (Friday senate meetings, morning-only senior faculty).
   - Inter-campus transfer considerations between Kampus Ganesha and Kampus Jatinangor.
   - Strict structural administrative paragraph headers recognized by `text_slicer.py`.
2. `unitime_smart_ingest_dataset.json`:
   - Complete canonical dataset populated with all 28 courses, subparts, parallel sections,
     instructors, team shares, time/room preferences, and distribution constraints.
   - Strictly conforms to `unitime-smart-ingest-schema.json` (Draft 2020-12).

Author: worker_doc_txt_json_4 (UniTime Teamwork Subagent)
Exclusive File Ownership:
- ai-gateway/test_data_robustness/generate_txt_json.py
- ai-gateway/test_data_robustness/memo_dekan_jadwal.txt
- ai-gateway/test_data_robustness/unitime_smart_ingest_dataset.json
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure current directory and ai-gateway root are in sys.path
_CURRENT_DIR = Path(__file__).resolve().parent
_GATEWAY_ROOT = _CURRENT_DIR.parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))
if str(_GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_ROOT))

# Import sibling data modules
import spatial_catalog
import curriculum_model

# Import AI Gateway core modules
try:
    from core.validator import Validator
    from slicers.text_slicer import TextSlicer
    from jsonschema import Draft202012Validator
except ImportError as exc:
    Validator = None  # type: ignore
    TextSlicer = None  # type: ignore
    Draft202012Validator = None  # type: ignore


# Output File Targets
MEMO_TXT_FILENAME = "memo_dekan_jadwal.txt"
DATASET_JSON_FILENAME = "unitime_smart_ingest_dataset.json"
SCHEMA_PATH = _GATEWAY_ROOT / "schema" / "unitime-smart-ingest-schema.json"


def generate_memo_text() -> str:
    """
    Constructs the authoritative narrative memorandum from the Deans of STEI and FTI ITB.
    
    The document features:
    - Formal institutional headers conforming to Indonesian administrative protocol.
    - Structural chapter headings (BAB I - VI, LAMPIRAN) matching TextSlicer regex patterns.
    - Specific room preferences matching the spatial topology catalog.
    - Time-window restrictions, Friday senate meeting exclusions, and senior professor morning preferences.
    - Inter-campus transfer constraints (minimum 60 minutes between Ganesha and Jatinangor).
    - Pedagogical precedence and distribution constraint directives.
    """
    # Query spatial topology and curriculum data to ensure 100% authentic synchronization
    rooms = spatial_catalog.ALL_ROOMS
    buildings = spatial_catalog.BUILDINGS
    campuses = spatial_catalog.CAMPUSES
    courses = curriculum_model.get_courses()
    faculty = curriculum_model.get_instructors()
    constraints = curriculum_model.get_distribution_constraints()

    # Dynamic counts
    total_courses = len(courses)
    total_rooms = len(rooms)
    total_faculty = len(faculty)

    memo_lines = [
        "INSTITUT TEKNOLOGI BANDUNG",
        "SEKOLAH TEKNIK ELEKTRO DAN INFORMATIKA & FAKULTAS TEKNOLOGI INDUSTRI",
        "Jalan Ganesha Nomor 10 Bandung 40132 | Jalan Letjen Purn. Dr. (HC) Mashudi No. 1 Jatinangor 45363",
        "Telepon: +62-22-2508135 | Laman Resmi: https://stei.itb.ac.id | https://fti.itb.ac.id",
        "",
        "MEMORANDUM: Arahan Kebijakan Penjadwalan Perkuliahan Semester Ganjil 2024/2025 Multi-Kampus",
        "NOMOR: 0428/IT1.C01/PP.00/2024",
        "FAKULTAS: Sekolah Teknik Elektro dan Informatika (STEI) dan Fakultas Teknologi Industri (FTI)",
        "PROGRAM STUDI: Teknik Informatika, Sistem Informasi, Teknik Elektro, Teknik Industri, dan Tahap Bersama",
        "PERIHAL: Pedoman Penetapan Preferensi Ruang, Batasan Waktu Dosen, Konektivitas Multi-Kampus, dan Distribusi Jadwal",
        "TANGGAL: 15 Agustus 2024",
        "",
        "Kepada Yth.,",
        "1. Para Ketua Program Studi di Lingkungan STEI dan FTI ITB",
        "2. Para Ketua Kelompok Keahlian (KK) / Laboratorium",
        "3. Seluruh Dosen Pengampu Mata Kuliah Semester Ganjil 2024/2025",
        "4. Tim Timetabling & Academic Scheduling Administrator",
        "",
        "Dengan hormat,",
        "Dalam rangka mempersiapkan pelaksanaan kegiatan pembelajaran tatap muka Semester Ganjil Tahun Akademik 2024/2025 secara tertib, efisien, dan berbasis sistem cerdas UniTime AI Ingestion Gateway, Pimpinan STEI dan FTI ITB menetapkan arahan kebijakan operasional penjadwalan multi-kampus sebagaimana tertuang dalam butir-butir ketentuan di bawah ini.",
        "",
        "BAB I KETENTUAN UMUM DAN PRINSIP OPERASIONAL MULTI-KAMPUS",
        "1. Lingkup Operasional Akademik:",
        "   Perkuliahan Semester Ganjil 2024/2025 diselenggarakan secara simultan di dua kampus utama:",
        "   a. Kampus ITB Ganesha (Kota Bandung) sebagai sentra utama prodi Teknik Informatika (IF), Teknik Elektro (EL), dan Teknik Industri (TI).",
        "   b. Kampus ITB Jatinangor (Kabupaten Sumedang) sebagai sentra operasional prodi Sistem Informasi (SI), sarana laboratorium terpadu, dan sebagian rombongan belajar Tahap Bersama (TPB).",
        f"   Total kurikulum aktif mencakup tepat {total_courses} mata kuliah dengan sebaran 4 mata kuliah TPB umum, 6 mata kuliah Informatika, 6 mata kuliah Sistem Informasi, 6 mata kuliah Teknik Elektro, dan 6 mata kuliah Teknik Industri.",
        "",
        "2. Satuan Kredit Semester (SKS) dan Beban Jam Kontak Mingguan:",
        "   Sesuai Peraturan Standar Nasional Pendidikan Tinggi (SN-Dikti) dan Pedoman Akademik ITB:",
        "   a. 1 SKS Perkuliahan Teori (Lecture) ekuivalen dengan 50 menit pembelajaran tatap muka per minggu.",
        "   b. 1 SKS Praktikum Laboratorium (Lab) ekuivalen dengan 100 hingga 170 menit tatap muka terstruktur per minggu.",
        "   c. 1 SKS Responsi / Tutorial tatap muka ekuivalen dengan 50 hingga 100 menit per minggu.",
        "   Setiap subpart wajib mematuhi parameter menit per minggu (minPerWeek) yang terdaftar pada katalog kurikulum.",
        "",
        "BAB II BATASAN WAKTU MENGAJAR DAN HARI LIBUR DOSEN",
        "1. Hari dan Jendela Waktu Bebas Mengajar (Hard Day-Off Exclusion):",
        "   a. Rapat Senat Akademik ITB dan Rapat Pleno Fakultas:",
        "      Setiap hari Jumat pukul 09.00 s.d. 11.30 WIB dialokasikan secara wajib untuk rapat institusional Senat Akademik ITB dan koordinasi pimpinan fakultas. Seluruh dosen dilarang dijadwalkan mengajar pada jendela waktu tersebut tanpa terkecuali.",
        "   b. Jeda Ibadah Sholat Jumat:",
        "      Setiap hari Jumat pukul 11.30 s.d. 13.00 WIB dikosongkan secara total dari seluruh aktivitas akademik perkuliahan, tutorial, maupun praktikum laboratorium di seluruh kampus.",
        "",
        "2. Preferensi Sesi Pagi Hari (Morning-Only Preferences) Dosen Senior dan Guru Besar:",
        "   Berdasarkan pertimbangan tugas tridharma dan komitmen institusional, ditetapkan preferensi waktu mengajar pagi bagi dosen senior sebagai berikut:",
        "   a. Prof. Dr. Ir. Rinaldi Munir, M.T. (NIP: 196608141992031002, Pengampu IF2110 dan IF2120): hanya bersedia mengajar sesi pagi (07.00 - 10.00 WIB).",
        "   b. Prof. Dr. Ir. Kadarsah Suryadi, DEA (NIP: 196202221986011001, Pengampu TI2101 dan TI3101): sesi pagi (07.00 - 09.30 WIB).",
        "   c. Prof. Dr. Ir. Bambang Riyanto Trilaksono (NIP: 196205261987031002, Pengampu EL2101 dan EL3102): sesi pagi (07.30 - 10.00 WIB).",
        "   d. Prof. Dr. Ir. Jaka Sembiring, M.Eng. (NIP: 196402171989031002, Pengampu SI2101 dan SI3101): sesi pagi (08.00 - 10.30 WIB).",
        "   e. Koordinator Dosen TPB (Dr. Warsoma Djohan, Prof. Hendra Gunawan, Dr. Alamta Singarimbun, Dr. Sparisoma Viridi): memprioritaskan sesi pagi (07.00 - 09.00 WIB) untuk kelas besar MA1101 Kalkulus I dan FI1101 Fisika Dasar I.",
        "",
        "3. Batasan Beban Kerja Dosen (BKD) dan Skema Tim Pengajar (Team-Teaching):",
        f"   a. Dari {total_faculty} orang dosen yang terdaftar dalam roster fakultas, beban mengajar kumulatif dibatasi maksimum 12.0 s.d. 16.0 SKS tertimbang per semester.",
        "   b. Setiap kelas yang diampu oleh tim pengajar (multi-instructor) wajib menetapkan tepat 1 orang Dosen Penanggung Jawab / Koordinator (isLead: true).",
        "   c. Pembagian persentase beban mengajar wajib berjumlah persis 100% mengikuti formula deterministik: 50:50 (2 dosen), 70:30 (tim asimetris), 34:33:33 (3 dosen), atau 100% (dosen tunggal).",
        "",
        "BAB III KONEKTIVITAS DAN JADWAL PERPINDAHAN ANTAR KAMPUS GANESHA - JATINANGOR",
        "1. Parameter Geografis dan Waktu Tempuh:",
        "   a. Jarak geodetik WGS84 garis lurus antar pusat koordinat Kampus Ganesha (-6.8915, 107.6107) dan Kampus Jatinangor (-6.9312, 107.7725) tercatat 18.41 km, atau setara dengan 27 hingga 32 kilometer rute darat melalui Tol Pasteur - Cisumdawu.",
        "   b. Waktu tempuh perjalanan darat dalam kondisi operasional normal dengan mempertimbangkan jadwal keberangkatan Shuttle Bus Resmi ITB membutuhkan waktu berkisar 50 hingga 75 menit.",
        "",
        "2. Kebijakan Jeda Minimum Lintas Kampus (Inter-Campus Transfer Travel Window):",
        "   a. Waktu jeda minimum (minimum travel buffer) yang diwajibkan antara kelas di Kampus Ganesha dan Kampus Jatinangor adalah 60 menit.",
        "   b. DILARANG KERAS menjadwalkan kelas berurutan (back-to-back) pada hari yang sama di dua kampus berbeda bagi dosen yang mengajar di kedua kampus maupun mahasiswa yang mengambil mata kuliah lintas program studi tanpa jeda perjalanan minimum 60 menit.",
        "",
        "3. Kebijakan Hari Klaster Kampus (Campus Day Clustering):",
        "   Program studi diinstruksikan untuk menerapkan pengelompokan jadwal berbasis hari utuh (misal: Senin-Rabu di Ganesha, Selasa-Kamis di Jatinangor) guna meminimalisasi kebutuhan mobilisasi lintas kota pada hari yang sama.",
        "",
        "BAB IV PREFERENSI ALOKASI RUANG DAN LABORATORIUM KHUSUS",
        "1. Alokasi Ruang Kuliah Teori Kampus Ganesha:",
        "   a. Gedung Labtek V Benny Subianto (LTV):",
        "      - Ruang 7601 (kapasitas 50 kursi) dan Ruang 7602 (kapasitas 45 kursi) diprioritaskan untuk kelas paralel Teknik Informatika (IF2110 K01/K02, IF2120 K01/K02, IF3130 K01/K02, IF3150 K01/K02).",
        "      - Ruang 7603 (kapasitas 20 kursi) dialokasikan sebagai ruang seminar dan kelas khusus tingkat lanjut.",
        "   b. Gedung Labtek VIII Achmad Bakrie (LTVIII):",
        "      - Ruang 8201 (kapasitas 45 kursi) dan Ruang 8202 (kapasitas 50 kursi) dialokasikan untuk kuliah teori Teknik Elektro (EL2101 K01/K02, EL2102 K01/K02, EL3102 K01/K02, EL3103 K01/K02).",
        "   c. Gedung Labtek III Matthias Aroef (LTIII):",
        "      - Ruang 3101 (kapasitas 60 kursi) dan Ruang 3102 (kapasitas 45 kursi) dialokasikan untuk kuliah teori Teknik Industri (TI2101 K01/K02, TI2102 K01/K02, TI3101 K01/K02, TI3102 K01/K02).",
        "",
        "2. Laboratorium Khusus dan Komputasi Berkinerja Tinggi (High-Performance GPU Labs):",
        "   a. Labtek V Lab-1 (Lab Komputer AI):",
        "      Dilengkapi dengan 30 unit GPU Workstations berpendingin presisi tinggi. Ruangan ini dialokasikan khusus untuk praktikum komputasi intensif:",
        "      - Praktikum IF2110 Algoritma dan Pemrograman (L01)",
        "      - Praktikum IF3110 Pengembangan Berbasis Platform (L01)",
        "      Diberlakukan konstrain distribusi SAME_ROOM untuk pemanfaatan GPU Workstations antara IF2110 L01 dan IF3110 L01.",
        "   b. Labtek VIII Lab-El (Lab Elektronika & Hardware):",
        "      Dilengkapi dengan 28 unit Hardware Stations (logic analyzer, oscilloscope, FPGA board). Ruangan ini dialokasikan khusus untuk:",
        "      - Praktikum IF2130 Arsitektur Komputer (L01)",
        "      - Praktikum EL3101 Sistem Tertanam (L01)",
        "      - Praktikum EL2103 Elektronika I (L01)",
        "      Diberlakukan konstrain distribusi SAME_ROOM antara IF2130 L01 dan EL3101 L01.",
        "",
        "3. Fasilitas Ruang Kuliah Umum dan Amphitheatre Kampus Ganesha:",
        "   Gedung Kuliah Umum Barat (GKUB):",
        "   - Ruang 9001 (Auditorium, kapasitas 150 kursi, Audio System, Projector).",
        "   - Ruang 9002 (Amphitheatre, kapasitas 200 kursi, Audio System, Projector).",
        "   Kedua ruangan ini dialokasikan khusus untuk mata kuliah gabungan Tahap Bersama (TPB) lintas fakultas (KU1011 Pengantar Rekayasa & Desain, MA1101 Kalkulus I, FI1101 Fisika Dasar I, KU1102 Berpikir Komputasional).",
        "",
        "4. Alokasi Fasilitas Akademik Kampus Jatinangor:",
        "   a. Gedung KOICA:",
        "      - Ruang 201 dan Ruang 202 (kapasitas masing-masing 40 komputer desktop) dialokasikan sebagai Laboratorium Komputer Sistem Informasi (SI2101, SI2102, SI2103, SI3101, SI3102, SI3103).",
        "   b. Gedung Kuliah Umum 1 Jatinangor (GKU1J):",
        "      - Ruang 101 (kapasitas 60 kursi) dan Ruang 102 (kapasitas 50 kursi) untuk perkuliahan teori program studi Sistem Informasi dan rombongan belajar Jatinangor.",
        "   c. Lab Terpadu Jatinangor (LABTJ):",
        "      - Ruang Lab-01 (kapasitas 30 hardware stations) dan Ruang Lab-02 (kapasitas 32 workstations) untuk praktikum terpadu komputasi dan elektronika.",
        "      - Ruang 301, 302, dan 303 untuk perkuliahan pendukung di Kampus Jatinangor.",
        "",
        "BAB V BATASAN DISTRIBUSI DAN PRESEDENSI PEDAGOGIS (DISTRIBUTION CONSTRAINTS)",
        "Tim penjadwalan wajib mengonfigurasi dan mematuhi 5 ragam batasan distribusi berikut:",
        "1. Presedensi Pedagogis (PRECEDENCE):",
        "   Sesi perkuliahan teori (Lecture) harus dijadwalkan mendahului sesi praktikum (Lab) dalam siklus mingguan yang sama. Larangan keras bagi mahasiswa melaksanakan praktikum sebelum materi konsep dasar diajarkan.",
        "   Daftar kelas dengan aturan PRECEDENCE mutlak:",
        "   a. IF2110 K01 (Kuliah Teori) mendahului IF2110 L01 (Praktikum Lab).",
        "   b. FI1101 K01 (Kuliah Fisika) mendahului FI1101 L01 (Praktikum Fisika).",
        "   c. EL2103 K01 (Kuliah Elektronika) mendahului EL2103 L01 (Praktikum Elektronika).",
        "   d. TI2103 K01 (Kuliah Ergonomi) mendahului TI2103 L01 (Praktikum Ergonomi).",
        "   e. KU1102 K01 (Kuliah Berpikir Komputasional) mendahului KU1102 L01 (Praktikum Komputasi).",
        "",
        "2. Kuliah dan Responsi Berurutan (BACK_TO_BACK / BTB):",
        "   Sesi perkuliahan teori dan sesi responsi/tutorial harus dijadwalkan bersambung tanpa jeda waktu kosong pada hari yang sama:",
        "   a. IF3150 K01 (Manajemen Proyek Perangkat Lunak) dan IF3150 R01 (Responsi).",
        "   b. SI3102 K01 (Manajemen Layanan TI) dan SI3102 R01 (Responsi).",
        "   c. TI2101 K01 (Penelitian Operasional I) dan TI2101 R01 (Responsi pada hari Senin).",
        "",
        "3. Larangan Bentrok Waktu Mata Kuliah Wajib Seangkatan (DIFF_TIME):",
        "   Mata kuliah wajib semester 3 pada program studi yang sama dilarang dijadwalkan pada slot waktu yang tumpang-tindih:",
        "   a. Teknik Informatika Semester 3: IF2110 K01 dan IF2120 K01 tidak boleh bentrok waktu.",
        "   b. Sistem Informasi Semester 3: SI2101 K01 dan SI2102 K01 tidak boleh bentrok waktu.",
        "   c. Teknik Elektro Semester 3: EL2101 K01 dan EL2102 K01 tidak boleh bentrok waktu.",
        "   d. Teknik Industri Semester 3: TI2101 K01 dan TI2102 K01 tidak boleh bentrok waktu.",
        "",
        "4. Alokasi Fasilitas Khusus pada Ruang yang Sama (SAME_ROOM):",
        "   a. IF2110 L01 dan IF3110 L01 wajib menggunakan ruang Labtek V Lab-1 (GPU Workstations).",
        "   b. IF2130 L01 dan EL3101 L01 wajib menggunakan ruang Labtek VIII Lab-El (Hardware Stations).",
        "",
        "5. Perkuliahan Gabungan Paralel (MEET_WITH / MEET_TOGETHER):",
        "   a. KU1011 Pengantar Rekayasa & Desain (K01 dan K02) dijadwalkan bersamaan di Amphitheatre GKUB 9002.",
        "   b. MA1101 Kalkulus I (K01 dan K02) sesi kuliah tamu gabungan dijadwalkan bersamaan di Auditorium GKUB 9001.",
        "",
        "BAB VI KETENTUAN AMANDEMEN DAN PENYESUAIAN JADWAL",
        "1. Prosedur Permohonan Amandemen:",
        "   Perubahan jadwal perkuliahan setelah penetapan versi rilis (baseline) hanya dapat diajukan oleh Dosen Koordinator Mata Kuliah melalui persetujuan tertulis Ketua Program Studi dan Wakil Dekan Bidang Akademik.",
        "2. Batas Waktu Amandemen:",
        "   Pengajuan perubahan jadwal dapat diproses selambat-lambatnya 1 (satu) pekan sebelum perkuliahan hari pertama Semester Ganjil dimulai.",
        "3. Kepatuhan Validasi Sistem:",
        "   Seluruh penyesuaian jadwal harus divalidasi melalui sistem UniTime AI Ingestion Gateway dan tidak diperkenankan menghasilkan konflik kapasitas maupun pelanggaran aturan distribusi.",
        "",
        "Demikian memorandum arahan operasional ini diterbitkan untuk dipedomani dan dilaksanakan dengan penuh tanggung jawab demi kelancaran tridharma perguruan tinggi di Institut Teknologi Bandung.",
        "",
        "Ditetapkan di: Bandung",
        "Pada tanggal: 15 Agustus 2024",
        "",
        "Dekan Sekolah Teknik Elektro dan Informatika",
        "Institut Teknologi Bandung",
        "",
        "ttd.",
        "",
        "Prof. Dr. Ir. Jaka Sembiring, M.Eng.",
        "NIP. 196402171989031002",
        "",
        "Dekan Fakultas Teknologi Industri",
        "Institut Teknologi Bandung",
        "",
        "ttd.",
        "",
        "Prof. Dr. Ir. Kadarsah Suryadi, DEA",
        "NIP. 196202221986011001",
        "",
        "LAMPIRAN I DAFTAR RUANGAN DAN FASILITAS MULTI-KAMPUS ITB",
        "Tabel Inventaris Ruang Kuliah dan Laboratorium Terpadu (20 Ruang):",
        "------------------------------------------------------------------------------------------------------------------------",
        "No | Kampus     | Gedung                    | Ruangan | Kapasitas | Klasifikasi    | Fasilitas / Fitur Unggulan",
        "------------------------------------------------------------------------------------------------------------------------",
    ]

    for idx, r in enumerate(rooms, start=1):
        c_name = r.get("campus", "").replace("Kampus ", "")
        b_name = r.get("building", "")
        r_num = r.get("room_number", "")
        cap = r.get("capacity", 0)
        cls_type = r.get("room_classification", "")
        feats = ", ".join(r.get("features", [])) or "Standar"
        memo_lines.append(f"{idx:02d} | {c_name:<10} | {b_name:<25} | {r_num:<7} | {cap:<9} | {cls_type:<14} | {feats}")

    memo_lines.extend([
        "------------------------------------------------------------------------------------------------------------------------",
        "",
        "LAMPIRAN II REKAPITULASI 28 MATA KULIAH KURIKULUM ITB",
        "Daftar Sebaran 28 Mata Kuliah Terpadu STEI & FTI ITB:",
        "------------------------------------------------------------------------------------------------------------------------",
        "No | Kode MK | Nama Mata Kuliah                        | SKS | Subparts               | Target Ruang Preferensi",
        "------------------------------------------------------------------------------------------------------------------------",
    ])

    for idx, c in enumerate(courses, start=1):
        c_num = c.get("courseNumber", "")
        c_title = c.get("title", "")
        units = c.get("credit", {}).get("units", 0)
        subparts_list = []
        room_list = []
        for cfg in c.get("configurations", []):
            for sp in cfg.get("subparts", []):
                subparts_list.append(sp.get("type", ""))
                for cl in sp.get("classes", []):
                    for rp in cl.get("roomPreferences", []):
                        b_abbr = rp.get("building", "").split()[0]
                        rm = rp.get("roomNumber", "")
                        room_list.append(f"{b_abbr} {rm}".strip())
        sub_str = "+".join(sorted(list(set(subparts_list))))
        room_str = ", ".join(sorted(list(set(room_list))))[:30] or "General"
        memo_lines.append(f"{idx:02d} | {c_num:<7} | {c_title:<39} | {units:<3} | {sub_str:<22} | {room_str}")

    memo_lines.extend([
        "------------------------------------------------------------------------------------------------------------------------",
        "",
        "--- AKHIR DOKUMEN MEMORANDUM RESMI ---",
    ])

    return "\n".join(memo_lines)


def generate_canonical_json(
    campus: str = "Kampus Ganesha",
    year: str = "2024-2025",
    term: str = "Ganjil"
) -> Dict[str, Any]:
    """
    Constructs the complete, schema-compliant canonical JSON payload.
    
    Populated with:
    - All 28 courses across IF, SI, EL, TI, and TPB.
    - Full subpart hierarchy (Lecture, Lab, Responsi, Tutorial).
    - Parallel sections (K01, K02) and linked child sections (L01, R01).
    - Instructors with IDs, names, emails, isLead, and 100% load shares.
    - Time and room preferences aligned with spatial topology.
    - All 16 distribution constraints (DIFF_TIME, SAME_ROOM, BTB, PRECEDENCE, MEET_WITH).
    """
    # Use curriculum_model export with deep copy
    payload = curriculum_model.export_canonical_full_payload(
        campus=campus,
        year=year,
        term=term,
    )

    # Ensure metadata timestamps and exact strictness
    payload_clean = copy.deepcopy(payload)
    payload_clean["ingestControl"]["extractedAt"] = "2024-08-15T08:00:00Z"
    payload_clean["ingestControl"]["sourceDocumentName"] = DATASET_JSON_FILENAME
    payload_clean["ingestControl"]["validationStrictness"] = "strict"

    return payload_clean


def validate_canonical_json(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates canonical JSON dataset against:
    1. jsonschema.Draft202012Validator with unitime-smart-ingest-schema.json
    2. ai-gateway core Validator (strict semantics enabled)
    
    Returns:
        (is_valid: bool, error_messages: List[str])
    """
    errors: List[str] = []

    # 1. Draft 2020-12 Schema Validation
    if not SCHEMA_PATH.is_file():
        errors.append(f"Schema file not found at: {SCHEMA_PATH}")
        return False, errors

    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_data = json.load(f)

        draft_validator = Draft202012Validator(schema_data)
        schema_errs = list(draft_validator.iter_errors(payload))
        for err in schema_errs:
            errors.append(f"Draft202012 Schema Error at '{err.json_path}': {err.message}")
    except Exception as exc:
        errors.append(f"Exception during Draft202012 schema validation: {exc}")

    # 2. AI Gateway Core Validator (Strict Semantics)
    try:
        core_val = Validator(schema_path=SCHEMA_PATH, strict_semantics=True)
        val_result = core_val.validate(payload)
        if not val_result.is_valid:
            for err in val_result.errors:
                errors.append(f"Core Validator Error: {err.format_line()}")
        if val_result.warnings:
            for warn in val_result.warnings:
                errors.append(f"Core Validator Strict Warning: {warn}")
    except Exception as exc:
        errors.append(f"Exception during Core Validator validation: {exc}")

    return (len(errors) == 0), errors


def validate_memo_text_slicing(memo_content: str) -> Tuple[bool, List[str], List[Any]]:
    """
    Verifies that the generated memorandum is correctly partitioned by TextSlicer
    into semantic chunks matching administrative boundaries.
    
    Returns:
        (is_valid: bool, diagnostics: List[str], chunks: List[TextChunk])
    """
    diagnostics: List[str] = []
    if TextSlicer is None:
        diagnostics.append("TextSlicer class could not be imported from slicers.text_slicer")
        return False, diagnostics, []

    slicer = TextSlicer()
    chunks = slicer.slice_text(memo_content)

    if not chunks:
        diagnostics.append("TextSlicer produced 0 chunks from memorandum text")
        return False, diagnostics, []

    # Check that key administrative boundaries were identified
    boundary_types = {c.metadata.get("boundary_type") for c in chunks}
    required_boundaries = {"administrative_heading", "department_boundary", "chapter_section"}
    missing_boundaries = required_boundaries - boundary_types
    if missing_boundaries:
        diagnostics.append(f"TextSlicer failed to detect boundary types: {missing_boundaries}")

    # Check that chapters BAB I to BAB VI are captured
    titles = [c.title or "" for c in chunks]
    all_titles_str = " ".join(titles)
    for bab in ["BAB I", "BAB II", "BAB III", "BAB IV", "BAB V", "BAB VI"]:
        if bab not in all_titles_str:
            diagnostics.append(f"Chapter header '{bab}' not found among sliced chunk titles")

    # Check character counts
    empty_chunks = [c.chunk_index for c in chunks if len(c.content.strip()) == 0]
    if empty_chunks:
        diagnostics.append(f"Found empty text chunks at indices: {empty_chunks}")

    passed = (len(diagnostics) == 0)
    return passed, diagnostics, chunks


def run_dry_run_ingest(file_path: Path) -> Tuple[bool, str]:
    """
    Executes ai-gateway/ingest.py in dry-run mock mode:
    `python3 ai-gateway/ingest.py -i <file_path> --dry-run --mock`
    
    Verifies it completes with exit code 0 without crashes.
    """
    ingest_script = _GATEWAY_ROOT / "ingest.py"
    if not ingest_script.is_file():
        return False, f"ingest.py not found at: {ingest_script}"

    cmd = [
        sys.executable,
        str(ingest_script),
        "-i",
        str(file_path),
        "--dry-run",
        "--mock",
    ]

    res = subprocess.run(
        cmd,
        cwd=str(_GATEWAY_ROOT.parent),
        capture_output=True,
        text=True,
    )

    combined_output = f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    success = (res.returncode == 0)
    return success, combined_output


def write_artifacts(target_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    """
    Generates and saves memo_dekan_jadwal.txt and unitime_smart_ingest_dataset.json.
    
    Returns:
        (memo_path: Path, dataset_path: Path)
    """
    out_dir = Path(target_dir).resolve() if target_dir else _CURRENT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    memo_path = out_dir / MEMO_TXT_FILENAME
    dataset_path = out_dir / DATASET_JSON_FILENAME

    # 1. Generate and write memorandum text
    memo_text = generate_memo_text()
    memo_path.write_text(memo_text, encoding="utf-8")

    # 2. Generate and write canonical dataset JSON
    dataset_payload = generate_canonical_json()
    dataset_path.write_text(
        json.dumps(dataset_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return memo_path, dataset_path


# ==============================================================================
# PYTEST UNIT TESTS
# ==============================================================================

def test_memo_text_generation():
    """Verify narrative memorandum contains all mandatory institutional components."""
    text = generate_memo_text()
    assert len(text) > 2000, f"Memo text too short ({len(text)} chars)"
    assert "MEMORANDUM:" in text
    assert "FAKULTAS:" in text
    assert "Sekolah Teknik Elektro dan Informatika" in text
    assert "Fakultas Teknologi Industri" in text
    assert "BAB I" in text
    assert "BAB II" in text
    assert "BAB III" in text
    assert "BAB IV" in text
    assert "BAB V" in text
    assert "BAB VI" in text
    assert "Senat Akademik ITB" in text
    assert "Prof. Dr. Ir. Rinaldi Munir" in text
    assert "Kampus Ganesha" in text
    assert "Kampus Jatinangor" in text
    assert "Labtek V" in text
    assert "Lab-1" in text
    assert "GPU Workstations" in text
    assert "DIFF_TIME" in text
    assert "SAME_ROOM" in text
    assert "PRECEDENCE" in text


def test_memo_text_slicing():
    """Verify TextSlicer partitions memorandum into recognized administrative chunks."""
    text = generate_memo_text()
    passed, diags, chunks = validate_memo_text_slicing(text)
    assert passed, f"TextSlicer validation failed: {diags}"
    assert len(chunks) >= 8, f"Expected >= 8 chunks, got {len(chunks)}"


def test_canonical_json_validation():
    """Verify canonical JSON payload conforms 100% to schema and strict semantics."""
    payload = generate_canonical_json()
    assert len(payload.get("courses", [])) == 28
    assert len(payload.get("distributionConstraints", [])) == 16
    passed, errors = validate_canonical_json(payload)
    assert passed, f"Canonical JSON validation errors:\n" + "\n".join(errors)


def test_dry_run_ingestion_cli():
    """Verify ai-gateway/ingest.py dry-run pass on generated memorandum."""
    memo_path, dataset_path = write_artifacts()
    success, output = run_dry_run_ingest(memo_path)
    assert success, f"Ingestion dry-run failed for {memo_path}:\n{output}"


# ==============================================================================
# CLI RUNNER & AUDIT REPORT
# ==============================================================================

def main() -> int:
    """Main execution function generating both files and validating them."""
    print("================================================================================")
    print(" UniTime AI Ingestion Gateway - M3 Part B Generator & Validator")
    print("================================================================================")
    print(f"Target Directory: {_CURRENT_DIR}")

    # Step 1: Write artifacts
    print("\n[Step 1/4] Generating raw narrative text and canonical JSON artifacts...")
    memo_path, dataset_path = write_artifacts(_CURRENT_DIR)
    print(f"  ✔ Created Memorandum Text:  {memo_path.name} ({memo_path.stat().st_size:,} bytes)")
    print(f"  ✔ Created Canonical Dataset: {dataset_path.name} ({dataset_path.stat().st_size:,} bytes)")

    # Step 2: Validate JSON against Draft 2020-12 and Validator
    print("\n[Step 2/4] Validating canonical JSON against Draft 2020-12 schema & domain rules...")
    with open(dataset_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    is_json_valid, json_errors = validate_canonical_json(payload)
    if is_json_valid:
        print("  ✔ Canonical JSON Schema Validation: PASSED (0 errors, 0 warnings)")
        print(f"    - Courses Total: {len(payload.get('courses', []))}")
        print(f"    - Distribution Constraints: {len(payload.get('distributionConstraints', []))}")
    else:
        print("  ✖ Canonical JSON Schema Validation: FAILED")
        for err in json_errors:
            print(f"    ! {err}")
        return 1

    # Step 3: Validate Text Slicing
    print("\n[Step 3/4] Validating memorandum text structure with TextSlicer...")
    memo_content = memo_path.read_text(encoding="utf-8")
    is_slice_valid, slice_diags, chunks = validate_memo_text_slicing(memo_content)
    if is_slice_valid:
        print(f"  ✔ TextSlicer Semantic Partitioning: PASSED ({len(chunks)} chunks produced)")
        for c in chunks[:5]:
            print(f"    - Chunk {c.chunk_index:02d}: [{c.metadata.get('boundary_type')}] '{c.title}' ({c.char_count} chars)")
        if len(chunks) > 5:
            print(f"    - ... and {len(chunks) - 5} more chunks")
    else:
        print("  ✖ TextSlicer Semantic Partitioning: FAILED")
        for d in slice_diags:
            print(f"    ! {d}")
        return 1

    # Step 4: Test dry-run ingestion
    print("\n[Step 4/4] Executing AI Gateway dry-run ingestion test on memo_dekan_jadwal.txt...")
    dry_run_success, dry_run_output = run_dry_run_ingest(memo_path)
    if dry_run_success:
        print("  ✔ AI Gateway Dry-Run Ingestion Pass: PASSED (Exit code 0)")
    else:
        print("  ✖ AI Gateway Dry-Run Ingestion Pass: FAILED")
        print(dry_run_output)
        return 1

    print("\n================================================================================")
    print(" ✔ Milestone M3 Part B synthesis and verification COMPLETED SUCCESSFULLY!")
    print("================================================================================\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
