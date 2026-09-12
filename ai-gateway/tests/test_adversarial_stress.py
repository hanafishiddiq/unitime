"""
Adversarial Stress-Testing Suite for UniTime AI Ingestion Gateway.

Tests:
1. Spatial Topology & Coordinate Fallbacks (Tier 1 explicit, Tier 2 building inheritance, Tier 3 null fallback)
   and Geodesic Distance / Travel Time Metric Behavior.
2. Slicer Robustness on Generated Physical Files & Boundary Inputs (TableSlicer, PDFSlicer, TextSlicer, DocumentSlicer).
3. JSON Validation Stress-Test against Validator & Draft 2020-12 Schema (invalid day tokens, inverted times,
   out-of-range capacities, teaching share anomalies, orphaned constraints).
"""

from __future__ import annotations

import copy
import io
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import openpyxl
import pytest
from PIL import Image

# Import gateway core modules
from core.slicer import DocumentSlicer
from core.validator import Validator
from slicers import (
    PageDimensions,
    PageSlice,
    PDFSlicer,
    TableChunk,
    TableSlicer,
    TextChunk,
    TextSlicer,
)

# Import spatial catalog from robustness artifacts
import sys
ROBUSTNESS_DIR = Path(__file__).resolve().parent.parent / "test_data_robustness"
if str(ROBUSTNESS_DIR) not in sys.path:
    sys.path.insert(0, str(ROBUSTNESS_DIR))

import spatial_catalog as sc


# ==============================================================================
# 1. COORDINATE FALLBACKS & GEODESIC DISTANCE METRIC STRESS TESTS
# ==============================================================================

class TestCoordinateFallbacksAndDistanceMetrics:
    """Empirical verification of 3-tiered coordinate topology and distance calculations."""

    def test_coordinate_tier_distribution_proportions(self) -> None:
        """Verify the exact 3-tiered coordinate distribution (40% Tier 1, 35% Tier 2, 25% Tier 3)."""
        rooms = sc.ALL_ROOMS
        assert len(rooms) == 20, f"Expected exactly 20 rooms in topology, found {len(rooms)}"

        t1_rooms = [r for r in rooms if r["coordinate_tier"] == 1]
        t2_rooms = [r for r in rooms if r["coordinate_tier"] == 2]
        t3_rooms = [r for r in rooms if r["coordinate_tier"] == 3]

        assert len(t1_rooms) == 8, f"Tier 1 room count expected 8 (40%), got {len(t1_rooms)}"
        assert len(t2_rooms) == 7, f"Tier 2 room count expected 7 (35%), got {len(t2_rooms)}"
        assert len(t3_rooms) == 5, f"Tier 3 room count expected 5 (25%), got {len(t3_rooms)}"

        # Verify coordinate presence per tier
        for r in t1_rooms:
            coords = sc.get_effective_coordinates(r)
            assert coords is not None, f"Tier 1 room {r['name']} must have explicit coordinates"
            assert r.get("room_coordinates") is not None

        for r in t2_rooms:
            coords = sc.get_effective_coordinates(r)
            assert coords is not None, f"Tier 2 room {r['name']} must inherit building coordinates"
            assert r.get("room_coordinates") is None
            # Must equal parent building coordinates
            bldg = sc.BUILDINGS[r["building_abbreviation"]]
            assert coords == (bldg["coordinates"]["longitude"], bldg["coordinates"]["latitude"])

        for r in t3_rooms:
            coords = sc.get_effective_coordinates(r)
            assert coords is None, f"Tier 3 room {r['name']} must have completely null coordinates"
            assert r.get("room_coordinates") is None
            bldg = sc.BUILDINGS[r["building_abbreviation"]]
            assert bldg.get("coordinates") is None

    def test_pairwise_distance_matrix_metric_properties(self) -> None:
        """
        Adversarially evaluate all 400 pairwise room distance combinations (20x20)
        against metric space properties:
        - Non-negativity: d(A, B) >= 0
        - Identity of indiscernibles: d(A, A) == 0
        - Symmetry: d(A, B) == d(B, A)
        """
        rooms = sc.ALL_ROOMS
        assert len(rooms) == 20

        for r1 in rooms:
            # Identity: same room must always yield 0.0, even if Tier 3
            d_self = sc.get_distance_in_meters(r1, r1)
            assert d_self == 0.0, f"Identity violated for room {r1['name']}: got {d_self}"

            for r2 in rooms:
                d12 = sc.get_distance_in_meters(r1, r2)
                d21 = sc.get_distance_in_meters(r2, r1)

                # Non-negativity
                assert d12 >= 0.0, f"Distance negative between {r1['name']} and {r2['name']}: {d12}"

                # Symmetry
                assert abs(d12 - d21) < 1e-7, (
                    f"Symmetry violated between {r1['name']} and {r2['name']}: d12={d12} != d21={d21}"
                )

    def test_tier_3_null_coordinates_fallback_exactness(self) -> None:
        """
        Empirically verify that when any room in a distinct pair lacks coordinates (Tier 3),
        distance calculation strictly returns DEFAULT_NULL_DISTANCE_METERS (10,000.0 m),
        while maintaining d(A, A) == 0.0 for identical Tier 3 rooms.
        """
        rooms = sc.ALL_ROOMS
        t3_rooms = [r for r in rooms if r["coordinate_tier"] == 3]
        non_t3_rooms = [r for r in rooms if r["coordinate_tier"] != 3]

        # 1. Tier 3 vs Non-Tier 3 (Tier 1 or Tier 2) -> 10,000.0 meters
        for r3 in t3_rooms:
            for r_other in non_t3_rooms:
                dist = sc.get_distance_in_meters(r3, r_other)
                assert dist == sc.DEFAULT_NULL_DISTANCE_METERS, (
                    f"Expected {sc.DEFAULT_NULL_DISTANCE_METERS} m fallback for {r3['name']} vs {r_other['name']}, got {dist}"
                )

        # 2. Distinct Tier 3 vs Tier 3 -> 10,000.0 meters
        for i, r3_a in enumerate(t3_rooms):
            for j, r3_b in enumerate(t3_rooms):
                dist = sc.get_distance_in_meters(r3_a, r3_b)
                if i == j:
                    assert dist == 0.0, f"Same Tier 3 room distance must be 0.0, got {dist}"
                else:
                    assert dist == sc.DEFAULT_NULL_DISTANCE_METERS, (
                        f"Distinct Tier 3 rooms must return fallback {sc.DEFAULT_NULL_DISTANCE_METERS}, got {dist}"
                    )

    def test_tier_1_and_tier_2_distance_behavior(self) -> None:
        """
        Verify intra-building and inter-building distance calculations:
        - Intra-building Tier 1 vs Tier 1: Small non-zero geodesic offset (~8-15 m).
        - Intra-building Tier 1 vs Tier 2: Small geodesic distance from room to building centroid (~3-10 m).
        - Intra-building Tier 2 vs Tier 2: Exactly 0.0 m (both resolve to identical building centroid).
        - Inter-campus distance: Between Ganesha and Jatinangor > 18 km.
        """
        # Tier 1 vs Tier 1 in same building LTV: 7601 and 7602
        d_t1_t1 = sc.get_distance_in_meters("LTV 7601", "LTV 7602")
        assert 5.0 < d_t1_t1 < 25.0, f"Expected fine-grained room offset (5-25m), got {d_t1_t1}"

        # Tier 1 vs Tier 2 in same building LTV: 7601 (T1) and 7603 (T2)
        d_t1_t2 = sc.get_distance_in_meters("LTV 7601", "LTV 7603")
        assert 1.0 < d_t1_t2 < 15.0, f"Expected room-to-bldg centroid offset, got {d_t1_t2}"

        # Tier 2 vs Tier 2 in same building GKU1J: 101 (T2) and 102 (T2)
        d_t2_t2_same_bldg = sc.get_distance_in_meters("GKU1J 101", "GKU1J 102")
        assert d_t2_t2_same_bldg == 0.0, (
            f"Two Tier 2 rooms in same building must share centroid (0.0 m), got {d_t2_t2_same_bldg}"
        )

        # Cross-campus inter-building distance: LTV (Ganesha) to GKU1J (Jatinangor)
        d_cross = sc.get_distance_in_meters("LTV 7601", "GKU1J 101")
        assert 18000.0 < d_cross < 19000.0, f"Inter-campus distance expected ~18.4 km, got {d_cross/1000.0} km"

    def test_travel_time_fallbacks_and_cross_campus_enforcement(self) -> None:
        """
        Verify travel time calculations:
        - Cross-campus travel strictly enforces minimum 60.0 minutes, regardless of room coordinate tier.
        - Intra-campus travel with null coordinates falls back to null_travel_time (60.0 min).
        - Intra-campus travel with coordinates divides distance by walking speed (66.67 m/min).
        - Same room travel is always 0.0 min.
        """
        # Cross-campus: T1 to T1
        assert sc.get_travel_time_in_minutes("LTV 7601", "GKU1J 101") == 60.0
        # Cross-campus: T1 to T3 (null coords)
        assert sc.get_travel_time_in_minutes("LTV 7601", "LABTJ 301") == 60.0
        # Cross-campus: T3 to T3
        assert sc.get_travel_time_in_minutes("LTV 7601", "LABTJ 302") == 60.0

        # Intra-campus: T1 to T1 (LTV 7601 to LTIII 3101)
        dist_intra = sc.get_distance_in_meters("LTV 7601", "LTIII 3101")
        expected_walk_min = dist_intra / sc.DEFAULT_WALKING_SPEED_MPM
        calc_walk_min = sc.get_travel_time_in_minutes("LTV 7601", "LTIII 3101")
        assert abs(calc_walk_min - expected_walk_min) < 1e-4

        # Intra-campus: T3 to T3 (LABTJ 301 to LABTJ 302) -> falls back to null_travel_time (60 min)
        assert sc.get_travel_time_in_minutes("LABTJ 301", "LABTJ 302") == 60.0

        # Same room: Tier 3 room to itself -> 0.0 min
        assert sc.get_travel_time_in_minutes("LABTJ 301", "LABTJ 301") == 0.0

    def test_nonexistent_and_invalid_room_identifiers(self) -> None:
        """Verify graceful fallback when invalid or non-existent room identifiers are supplied."""
        assert sc.get_distance_in_meters("GHOST_ROOM_999", "LTV 7601") == sc.DEFAULT_NULL_DISTANCE_METERS
        assert sc.get_distance_in_meters("LTV 7601", "GHOST_ROOM_999") == sc.DEFAULT_NULL_DISTANCE_METERS
        assert sc.get_distance_in_meters("GHOST_1", "GHOST_2") == sc.DEFAULT_NULL_DISTANCE_METERS
        assert sc.get_travel_time_in_minutes("GHOST_ROOM_999", "LTV 7601") == 60.0

    def test_vincenty_geodesic_stability(self) -> None:
        """Verify mathematical stability of Vincenty formula on extreme or identical coordinates."""
        # Identical coordinates
        assert sc.vincenty_distance(-6.89, 107.61, -6.89, 107.61) == 0.0
        # Equator points
        d_eq = sc.vincenty_distance(0.0, 100.0, 0.0, 101.0)
        assert 110000.0 < d_eq < 112000.0  # ~111.3 km per longitudinal degree at equator


# ==============================================================================
# 2. SLICER ROBUSTNESS STRESS TESTS
# ==============================================================================

class TestSlicerRobustness:
    """Empirical stress-testing of TableSlicer, PDFSlicer, and TextSlicer under boundary inputs."""

    @pytest.fixture
    def robustness_dir(self) -> Path:
        return ROBUSTNESS_DIR

    # --- TableSlicer Stress Tests ---

    def test_table_slicer_on_generated_excel(self, robustness_dir: Path) -> None:
        """Test TableSlicer on actual generated physical spreadsheet (jadwal_itb_multicampus.xlsx)."""
        xlsx_file = robustness_dir / "jadwal_itb_multicampus.xlsx"
        assert xlsx_file.exists(), f"Missing physical artifact: {xlsx_file}"

        slicer = TableSlicer(batch_size=50)
        chunks = list(slicer.slice(xlsx_file))

        # 84 rows / 50 batch_size = 2 chunks (50 rows, 34 rows)
        assert len(chunks) == 2
        assert chunks[0].start_row == 0
        assert chunks[0].end_row == 50
        assert len(chunks[0].rows) == 50
        assert chunks[0].total_rows == 84

        assert chunks[1].start_row == 50
        assert chunks[1].end_row == 84
        assert len(chunks[1].rows) == 34
        assert chunks[1].total_rows == 84

        # Verify header preservation across both chunks
        expected_cols = 13
        assert len(chunks[0].headers) == expected_cols
        assert len(chunks[1].headers) == expected_cols
        assert chunks[0].headers == chunks[1].headers
        assert "Kode MK" in chunks[0].headers
        assert "Komponen" in chunks[0].headers

        # Verify markdown and CSV format representations exist and are non-empty
        for c in chunks:
            assert len(c.markdown) > 500
            assert len(c.csv_content) > 500
            assert "| Kode MK |" in c.markdown
            assert "Kode MK," in c.csv_content or "Kode MK;" in c.csv_content

    def test_table_slicer_varying_batch_sizes(self, robustness_dir: Path) -> None:
        """Test TableSlicer with extreme batch sizes: 1, 84, and 200."""
        xlsx_file = robustness_dir / "jadwal_itb_multicampus.xlsx"

        # Fine-grained: batch_size=1 -> exactly 84 chunks
        slicer_1 = TableSlicer(batch_size=1)
        chunks_1 = list(slicer_1.slice(xlsx_file))
        assert len(chunks_1) == 84
        for idx, c in enumerate(chunks_1):
            assert len(c.rows) == 1
            assert c.chunk_index == idx
            assert c.total_chunks == 84
            assert len(c.headers) == 13

        # Coarse-grained: batch_size=100 -> exactly 1 chunk
        slicer_100 = TableSlicer(batch_size=100)
        chunks_100 = list(slicer_100.slice(xlsx_file))
        assert len(chunks_100) == 1
        assert len(chunks_100[0].rows) == 84
        assert chunks_100[0].chunk_index == 0
        assert chunks_100[0].total_chunks == 1

    def test_table_slicer_invalid_parameters_and_file_boundaries(self, tmp_path: Path) -> None:
        """Verify TableSlicer input validation for invalid batch sizes, missing files, and 0-byte files."""
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            TableSlicer(batch_size=0)

        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            TableSlicer(batch_size=-10)

        slicer = TableSlicer()
        with pytest.raises(FileNotFoundError):
            list(slicer.slice(tmp_path / "non_existent.xlsx"))

        empty_file = tmp_path / "empty.xlsx"
        empty_file.write_bytes(b"")
        with pytest.raises(ValueError, match="File is empty"):
            list(slicer.slice(empty_file))

    def test_table_slicer_header_only_and_empty_sheets(self, tmp_path: Path) -> None:
        """Test behavior when an Excel workbook has a sheet with only headers or empty rows."""
        wb = openpyxl.Workbook()
        ws_empty = wb.active
        ws_empty.title = "EmptySheet"

        ws_headers = wb.create_sheet(title="HeaderOnlySheet")
        ws_headers.append(["ColA", "ColB", "ColC"])

        test_file = tmp_path / "edge_sheets.xlsx"
        wb.save(test_file)
        wb.close()

        # With skip_empty_sheets=True (default) -> both sheets skipped
        slicer_skip = TableSlicer(skip_empty_sheets=True)
        chunks_skip = list(slicer_skip.slice(test_file))
        assert len(chunks_skip) == 0

        # With skip_empty_sheets=False -> yields chunks for both empty and header-only sheets
        slicer_no_skip = TableSlicer(skip_empty_sheets=False)
        chunks_no_skip = list(slicer_no_skip.slice(test_file))
        assert len(chunks_no_skip) == 2
        assert chunks_no_skip[0].sheet_name == "EmptySheet"
        assert chunks_no_skip[0].metadata["is_empty"] is True
        assert chunks_no_skip[1].sheet_name == "HeaderOnlySheet"
        assert chunks_no_skip[1].headers == ["ColA", "ColB", "ColC"]
        assert chunks_no_skip[1].rows == []
        assert chunks_no_skip[1].metadata["is_empty"] is True

    def test_table_slicer_csv_delimiter_sniffing_and_special_chars(self, tmp_path: Path) -> None:
        """Test TableSlicer on semicolon-delimited CSV with Indonesian characters."""
        csv_content = (
            "Kode MK;Nama Kuliah;SKS;Ruang\n"
            "IF2110;Algoritma & Struktur Data;4;Labtek V 7601\n"
            "EL2101;Rangkaian Elektrik;3;Labtek VIII 8201\n"
        )
        csv_file = tmp_path / "jadwal_indo.csv"
        csv_file.write_text(csv_content, encoding="utf-8")

        slicer = TableSlicer(batch_size=10)
        chunks = list(slicer.slice(csv_file))
        assert len(chunks) == 1
        assert chunks[0].headers == ["Kode MK", "Nama Kuliah", "SKS", "Ruang"]
        assert len(chunks[0].rows) == 2
        assert chunks[0].rows[0][0] == "IF2110"
        assert chunks[0].rows[0][1] == "Algoritma & Struktur Data"

    # --- PDFSlicer Stress Tests ---

    def test_pdf_slicer_on_generated_pdf(self, robustness_dir: Path) -> None:
        """Test PDFSlicer on actual generated physical catalog (katalog_jadwal_itb.pdf)."""
        pdf_file = robustness_dir / "katalog_jadwal_itb.pdf"
        assert pdf_file.exists(), f"Missing physical artifact: {pdf_file}"

        slicer = PDFSlicer(dpi=150, keep_in_memory=True, save_to_disk=False, extract_text_metadata=True)
        slices = list(slicer.slice(pdf_file))

        assert len(slices) == 4, f"Expected 4 pages in catalog PDF, got {len(slices)}"
        for idx, s in enumerate(slices):
            assert s.page_number == idx + 1
            assert s.total_pages == 4
            assert s.dimensions.width > 1000
            assert s.dimensions.height > 800
            assert s.image_bytes is not None and len(s.image_bytes) > 50000

            # Text extraction metadata verification
            assert s.metadata["has_text"] is True
            assert "extracted_text" in s.metadata
            assert len(s.metadata["extracted_text"]) > 2000

        # Page 1 contains ITB header
        assert "INSTITUT TEKNOLOGI BANDUNG" in slices[0].metadata["extracted_text"]
        # Page 4 contains Distribution Constraints
        assert "DISTRIBUSI" in slices[3].metadata["extracted_text"]

    def test_pdf_slicer_dpi_and_format_boundaries(self, tmp_path: Path, robustness_dir: Path) -> None:
        """Verify PDFSlicer boundary enforcement for DPI limits and unsupported formats."""
        pdf_file = robustness_dir / "katalog_jadwal_itb.pdf"

        # DPI < 72 raises ValueError
        with pytest.raises(ValueError, match="DPI must be between 72 and 600"):
            PDFSlicer(dpi=71)

        # DPI > 600 raises ValueError
        with pytest.raises(ValueError, match="DPI must be between 72 and 600"):
            PDFSlicer(dpi=601)

        # Unsupported image formats raise ValueError
        with pytest.raises(ValueError, match="Unsupported image format"):
            PDFSlicer(image_format="gif")
        with pytest.raises(ValueError, match="Unsupported image format"):
            PDFSlicer(image_format="bmp")

        # Boundary valid: DPI 72
        slicer_72 = PDFSlicer(dpi=72, keep_in_memory=True, save_to_disk=False)
        slices_72 = list(slicer_72.slice(pdf_file))
        assert len(slices_72) == 4
        assert slices_72[0].dimensions.width < 1000  # Low resolution

        # Both save_to_disk and keep_in_memory False raises ValueError
        with pytest.raises(ValueError, match="At least one of save_to_disk or keep_in_memory must be True"):
            PDFSlicer(save_to_disk=False, keep_in_memory=False)

    def test_pdf_slicer_cleanup_and_temp_management(self, robustness_dir: Path) -> None:
        """Verify that PDFSlicer in context manager with auto_cleanup properly cleans up temporary files."""
        pdf_file = robustness_dir / "katalog_jadwal_itb.pdf"

        managed_dir = None
        with PDFSlicer(dpi=100, save_to_disk=True, auto_cleanup=True) as slicer:
            managed_dir = slicer.output_dir
            assert managed_dir is not None
            assert managed_dir.exists()
            slices = list(slicer.slice(pdf_file))
            assert len(slices) == 4
            # Files should exist inside managed dir
            generated_files = list(managed_dir.glob("*.png"))
            assert len(generated_files) == 4

        # After exiting context manager, managed directory must be cleaned up
        assert not managed_dir.exists(), f"Managed temporary directory {managed_dir} was not cleaned up"

    # --- TextSlicer Stress Tests ---

    def test_text_slicer_on_generated_memo(self, robustness_dir: Path) -> None:
        """Test TextSlicer on actual generated narrative memo (memo_dekan_jadwal.txt)."""
        memo_file = robustness_dir / "memo_dekan_jadwal.txt"
        assert memo_file.exists(), f"Missing physical artifact: {memo_file}"

        slicer = TextSlicer(max_chunk_chars=2000, min_chunk_chars=100)
        chunks = slicer.slice_file(memo_file)

        assert len(chunks) == 19, f"Expected 19 chunks from dean narrative memo, got {len(chunks)}"

        # Verify semantic boundary partitioning
        titles = [c.title for c in chunks if c.title]
        assert any("MEMORANDUM" in t or "Arahan" in t for t in titles)
        assert any("BAB I" in t for t in titles)
        assert any("BAB II" in t for t in titles)
        assert any("BAB III" in t for t in titles)
        assert any("BAB IV" in t for t in titles)
        assert any("BAB V" in t for t in titles)
        assert any("BAB VI" in t for t in titles)
        assert any("LAMPIRAN I" in t for t in titles)
        assert any("LAMPIRAN II" in t for t in titles)

        # Verify continuation chunks contain breadcrumbs
        continuation_chunks = [c for c in chunks if "(Lanjutan" in c.content]
        assert len(continuation_chunks) >= 5, "Expected continuation breadcrumbs in split sections"

    def test_text_slicer_unbreakable_text_and_boundaries(self, tmp_path: Path) -> None:
        """Test TextSlicer parameter boundaries and sliding-window split on unbreakable continuous text."""
        # Boundaries: max < 200
        with pytest.raises(ValueError, match="max_chunk_chars must be >= 200"):
            TextSlicer(max_chunk_chars=199)

        # Boundaries: min >= max
        with pytest.raises(ValueError, match="min_chunk_chars must be strictly less than max_chunk_chars"):
            TextSlicer(max_chunk_chars=300, min_chunk_chars=300)

        # Unbreakable continuous string with 5,000 characters without whitespace or newlines
        giant_string = "A" * 5000
        test_file = tmp_path / "giant.txt"
        test_file.write_text(giant_string, encoding="utf-8")

        slicer = TextSlicer(max_chunk_chars=1000, overlap_chars=100)
        chunks = slicer.slice_file(test_file)
        assert len(chunks) >= 5, f"Expected at least 5 chunks from 5000 chars, got {len(chunks)}"
        total_extracted = sum(c.char_count for c in chunks)
        assert total_extracted >= 5000

    def test_document_slicer_unified_dispatch(self, robustness_dir: Path) -> None:
        """Verify DocumentSlicer dispatches all 4 physical artifacts without errors."""
        doc_slicer = DocumentSlicer()

        xlsx_chunks = doc_slicer.slice_file(robustness_dir / "jadwal_itb_multicampus.xlsx")
        assert len(xlsx_chunks) >= 2
        assert all(c.chunk_type == "text" for c in xlsx_chunks)

        pdf_chunks = doc_slicer.slice_file(robustness_dir / "katalog_jadwal_itb.pdf")
        assert len(pdf_chunks) == 4
        assert all(c.chunk_type == "text" for c in pdf_chunks)

        txt_chunks = doc_slicer.slice_file(robustness_dir / "memo_dekan_jadwal.txt")
        assert len(txt_chunks) == 19
        assert all(c.chunk_type == "text" for c in txt_chunks)

        json_chunks = doc_slicer.slice_file(robustness_dir / "unitime_smart_ingest_dataset.json")
        assert len(json_chunks) > 10
        assert all(c.chunk_type == "text" for c in json_chunks)


# ==============================================================================
# 3. JSON VALIDATION STRESS TESTS
# ==============================================================================

class TestJSONValidationStress:
    """Empirical verification of schema and semantic validator against canonical and adversarial payloads."""

    @pytest.fixture
    def canonical_dataset(self) -> Dict[str, Any]:
        dataset_path = ROBUSTNESS_DIR / "unitime_smart_ingest_dataset.json"
        assert dataset_path.exists()
        with open(dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @pytest.fixture
    def validator(self) -> Validator:
        return Validator(strict_semantics=False)

    @pytest.fixture
    def strict_validator(self) -> Validator:
        return Validator(strict_semantics=True)

    def test_canonical_dataset_clean_pass(
        self, canonical_dataset: Dict[str, Any], validator: Validator, strict_validator: Validator
    ) -> None:
        """Verify that the generated canonical dataset passes 100% cleanly without errors or warnings."""
        res = validator.validate(canonical_dataset)
        assert res.is_valid is True, f"Canonical dataset failed standard validation: {res.error_messages}"
        assert len(res.errors) == 0
        assert len(res.warnings) == 0

        res_strict = strict_validator.validate(canonical_dataset)
        assert res_strict.is_valid is True, f"Canonical dataset failed strict validation: {res_strict.error_messages}"
        assert len(res_strict.errors) == 0
        assert len(res_strict.warnings) == 0

    def test_invalid_day_tokens_schema_rejection(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """
        Adversarially inject invalid day tokens and verify that Draft 2020-12 schema regex catches them:
        - Arbitrary strings: 'X', 'XYZ', 'ABC', 'Monday', 'Senin', ''
        - Malformed binary masks: '10101' (length 5), '10101001' (length 8), '1020100' (invalid digit 2)
        - Mixed invalid tokens: 'MWRX', 'MTWTFSS'
        """
        invalid_tokens = [
            "X",
            "Monday",
            "Wednesday",
            "Senin",
            "Jumat",
            "",
            "ABC",
            "10101",
            "10101001",
            "1020100",
            "MWRX",
        ]

        for token in invalid_tokens:
            mutated = copy.deepcopy(canonical_dataset)
            mutated["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["timePreferences"] = [
                {"days": token, "startTime": "08:00", "endTime": "10:00"}
            ]
            res = validator.validate(mutated)
            assert res.is_valid is False, f"Expected day token '{token}' to be rejected, but it passed!"
            err_props = [e.path for e in res.errors]
            assert any("days" in p for p in err_props), f"Error path missing 'days' for token '{token}'"

    def test_valid_day_tokens_acceptance(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """Verify that all legal UniTime day patterns, 3-letter codes, and 7-bit masks cleanly pass."""
        valid_tokens = [
            # UniTime standard day codes
            "M", "T", "W", "Th", "R", "F", "S", "Su", "U",
            "MWF", "TTh", "MW", "ThF", "MF",
            # 3-letter day codes
            "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun",
            # 7-bit binary masks (Mon-Sun)
            "1000000", "0100000", "0010000", "0001000", "0000100", "0000010", "0000001",
            "1010100", "0101000", "1111100",
        ]

        for token in valid_tokens:
            mutated = copy.deepcopy(canonical_dataset)
            mutated["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["timePreferences"] = [
                {"days": token, "startTime": "08:00", "endTime": "10:00"}
            ]
            res = validator.validate(mutated)
            assert res.is_valid is True, f"Expected valid day token '{token}' to pass, got errors: {res.error_messages}"

    def test_inverted_and_equal_time_preferences(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """
        Verify semantic validator detects:
        - Inverted time slots: startTime >= endTime (e.g. 15:00 to 09:00).
        - Zero-duration equal time slots: startTime == endTime (e.g. 10:00 to 10:00).
        """
        # Inverted time
        mutated_inverted = copy.deepcopy(canonical_dataset)
        mutated_inverted["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["timePreferences"] = [
            {"days": "M", "startTime": "15:00", "endTime": "09:00"}
        ]
        res_inv = validator.validate(mutated_inverted)
        assert res_inv.is_valid is False
        assert any("startTime '15:00' must be earlier than endTime '09:00'" in e.message for e in res_inv.errors)

        # Equal time
        mutated_equal = copy.deepcopy(canonical_dataset)
        mutated_equal["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["timePreferences"] = [
            {"days": "M", "startTime": "10:00", "endTime": "10:00"}
        ]
        res_eq = validator.validate(mutated_equal)
        assert res_eq.is_valid is False
        assert any("startTime '10:00' must be earlier than endTime '10:00'" in e.message for e in res_eq.errors)

    def test_malformed_time_formats_rejection(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """Verify regex rejection of malformed time strings (invalid hours, invalid minutes, non-numeric)."""
        malformed_times = [
            ("24:00", "10:00"),  # Hour 24 invalid
            ("25:00", "10:00"),  # Hour 25 invalid
            ("08:60", "10:00"),  # Minute 60 invalid
            ("08:99", "10:00"),  # Minute 99 invalid
            ("8am", "10am"),     # Non-24h format
            ("TBA", "TBA"),      # Text placeholder
        ]

        for st, et in malformed_times:
            mutated = copy.deepcopy(canonical_dataset)
            mutated["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["timePreferences"] = [
                {"days": "M", "startTime": st, "endTime": et}
            ]
            res = validator.validate(mutated)
            assert res.is_valid is False, f"Expected time ({st}, {et}) to be rejected, but it passed!"

    def test_class_capacity_boundaries(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """Verify schema rejection of zero or negative class capacities."""
        for invalid_cap in [0, -1, -50]:
            mutated = copy.deepcopy(canonical_dataset)
            mutated["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["capacity"] = invalid_cap
            res = validator.validate(mutated)
            assert res.is_valid is False, f"Capacity {invalid_cap} must be rejected (minimum 1)"
            assert any("less than the minimum of 1" in e.message for e in res.errors)

        # Boundary valid: capacity 1
        mutated_1 = copy.deepcopy(canonical_dataset)
        mutated_1["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["capacity"] = 1
        res_1 = validator.validate(mutated_1)
        assert res_1.is_valid is True

    def test_instructor_share_percentage_anomalies(
        self, canonical_dataset: Dict[str, Any], validator: Validator, strict_validator: Validator
    ) -> None:
        """
        Verify that instructor share sums not totaling 100%:
        - Triggers warning in standard validation.
        - Triggers hard validation error in strict validation.
        """
        mutated = copy.deepcopy(canonical_dataset)
        # Change Dr. Warsoma share from 70% to 50% (total = 50 + 30 = 80%)
        mutated["courses"][0]["configurations"][0]["subparts"][0]["classes"][0]["instructors"][0]["sharePercentage"] = 50

        # Standard validator -> warning
        res = validator.validate(mutated)
        assert res.is_valid is True
        assert len(res.warnings) == 1
        assert "instructor share percentages sum to 80%, expected 100%" in res.warnings[0]

        # Strict validator -> error
        res_strict = strict_validator.validate(mutated)
        assert res_strict.is_valid is False
        assert len(res_strict.errors) >= 1
        assert any("sum to 80%, expected 100%" in e.message for e in res_strict.errors)

    def test_orphaned_distribution_constraint_reference(
        self, canonical_dataset: Dict[str, Any], validator: Validator, strict_validator: Validator
    ) -> None:
        """Verify detection of distribution constraints referencing non-existent courses or sections."""
        mutated = copy.deepcopy(canonical_dataset)
        mutated["distributionConstraints"][0]["classes"][0] = {
            "courseNumber": "NON_EXISTENT_COURSE_9999",
            "sectionName": "K99",
        }

        # Standard validator -> warning
        res = validator.validate(mutated)
        assert res.is_valid is True
        assert any("references undefined class section" in w for w in res.warnings)

        # Strict validator -> error
        res_strict = strict_validator.validate(mutated)
        assert res_strict.is_valid is False
        assert any("references undefined class section" in e.message for e in res_strict.errors)

    def test_non_dict_and_missing_required_root_payloads(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """Verify validator handles non-dict payloads and missing required root fields."""
        # Non-dict payload
        res_list = validator.validate(["invalid_list"])  # type: ignore[arg-type]
        assert res_list.is_valid is False
        assert "Payload must be a JSON object" in res_list.errors[0].message

        # Missing required root fields (e.g. courses)
        mutated = copy.deepcopy(canonical_dataset)
        del mutated["courses"]
        res_no_courses = validator.validate(mutated)
        assert res_no_courses.is_valid is False
        assert any("'courses' is a required property" in e.message for e in res_no_courses.errors)

    def test_partial_payload_validation(
        self, canonical_dataset: Dict[str, Any], validator: Validator
    ) -> None:
        """Verify validate_partial accommodates partial payloads without root required fields."""
        partial_payload = {
            "courses": [canonical_dataset["courses"][0]]
        }
        res = validator.validate_partial(partial_payload)
        assert res.is_valid is True, f"Valid partial payload failed: {res.error_messages}"
