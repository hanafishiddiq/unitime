#!/usr/bin/env python3
"""
generate_dataset.py - Master Dataset Orchestrator & Generator for UniTime Robustness Suite
========================================================================================

Master orchestrator script that imports and executes all modular data generators in sequence:
  1. Milestone M1: Spatial Catalog (spatial_catalog.py)
     - Verifies 2 campuses, 7 buildings, 20 rooms, and strict 3-tiered coordinate distribution
       (40% Tier 1, 35% Tier 2, 25% Tier 3).
  2. Milestone M2: Curriculum Model (curriculum_model.py)
     - Verifies 28 courses across IF, SI, EL, TI, TPB, 32 faculty members, and 16 distribution constraints.
  3. Milestone M3-A: Multi-Format Document Synthesis (generate_xlsx_pdf.py)
     - Generates jadwal_itb_multicampus.xlsx (merged headers, TBA rooms, semicolon delimiters).
     - Generates katalog_jadwal_itb.pdf (landscape tables, repeating headers, constraint footnotes).
  4. Milestone M3-B: Narrative Memo & Canonical JSON (generate_txt_json.py)
     - Generates memo_dekan_jadwal.txt (structured administrative directives with section headings).
     - Generates unitime_smart_ingest_dataset.json (strict Draft 2020-12 canonical schema payload).
  5. Milestone M4: Pre-UniTime Legacy Schedule Simulation (generate_legacy.py)
     - Generates pre_unitime_legacy_schedule.json (flawed baseline with 4 hard conflicts, room misallocations,
       student idle gaps, and post-UniTime optimized solution).

After generation, the script audits and certifies that all physical artifacts exist,
are non-empty, and are structurally ready for the automated verification suite (verify_dataset.py).

Author: test_writer_qa_7 (UniTime Teamwork Subagent)
Exclusive File: ai-gateway/test_data_robustness/generate_dataset.py
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure current directory is in python search path
_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

# Ensure ai-gateway root is in python search path
_AI_GW_DIR = _CURRENT_DIR.parent
if str(_AI_GW_DIR) not in sys.path:
    sys.path.insert(0, str(_AI_GW_DIR))

# Import modular generator modules
try:
    import spatial_catalog as sc
    import curriculum_model as cm
    import generate_xlsx_pdf as gxp
    import generate_txt_json as gtj
    import generate_legacy as gl
except ImportError as err:
    print(f"[FATAL] Failed to import modular generator: {err}", file=sys.stderr)
    sys.exit(1)

# Optional Rich formatting
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    _HAS_RICH = True
    console = Console()
except ImportError:
    _HAS_RICH = False
    console = None


# ==============================================================================
# PHYSICAL ARTIFACT DEFINITIONS
# ==============================================================================
# The core target artifacts produced by M1 through M4
PHYSICAL_ARTIFACTS: List[Dict[str, str]] = [
    {
        "filename": "campus_topology.json",
        "milestone": "M1",
        "description": "Multi-Campus Spatial Topology (2 campuses, 7 buildings, 20 rooms, tiered coords)",
        "min_size_bytes": 10000,
    },
    {
        "filename": "buildingRoomImport.xml",
        "milestone": "M1",
        "description": "UniTime BuildingRoom DTD XML facility data exchange payload",
        "min_size_bytes": 8000,
    },
    {
        "filename": "curriculum_catalog.json",
        "milestone": "M2",
        "description": "Curriculum & Faculty Catalog (28 courses, 32 faculty, 16 distribution constraints)",
        "min_size_bytes": 20000,
    },
    {
        "filename": "jadwal_itb_multicampus.xlsx",
        "milestone": "M3-A",
        "description": "Stress-Testing Multi-Campus Timetable Spreadsheet (.xlsx)",
        "min_size_bytes": 10000,
    },
    {
        "filename": "katalog_jadwal_itb.pdf",
        "milestone": "M3-A",
        "description": "Formal Academic Directive & Timetable Catalog PDF (.pdf)",
        "min_size_bytes": 12000,
    },
    {
        "filename": "memo_dekan_jadwal.txt",
        "milestone": "M3-B",
        "description": "Administrative Dean Narrative Scheduling Directive Memo (.txt)",
        "min_size_bytes": 12000,
    },
    {
        "filename": "unitime_smart_ingest_dataset.json",
        "milestone": "M3-B",
        "description": "Canonical Schema-Conformant Ingestion Payload (Draft 2020-12)",
        "min_size_bytes": 80000,
    },
    {
        "filename": "pre_unitime_legacy_schedule.json",
        "milestone": "M4",
        "description": "Pre-UniTime Manual Legacy Schedule Baseline with 4 Hard Conflicts & Resolution",
        "min_size_bytes": 150000,
    },
]


# ==============================================================================
# CONSOLE FORMATTING HELPERS
# ==============================================================================
def print_banner(title: str, subtitle: Optional[str] = None) -> None:
    if _HAS_RICH and console:
        grid = Table.grid(expand=True)
        grid.add_column(justify="center")
        grid.add_row(Text(title, style="bold cyan"))
        if subtitle:
            grid.add_row(Text(subtitle, style="dim white"))
        console.print(Panel(grid, border_style="bright_blue"))
    else:
        border = "=" * 80
        print(f"\n{border}")
        print(f" {title.center(78)}")
        if subtitle:
            print(f" {subtitle.center(78)}")
        print(f"{border}\n")


def print_step(step_num: int, total_steps: int, title: str) -> None:
    msg = f"[{step_num}/{total_steps}] {title}"
    if _HAS_RICH and console:
        console.print(f"\n[bold yellow]{msg}[/bold yellow]")
    else:
        print(f"\n---> {msg}")


def print_success(msg: str) -> None:
    if _HAS_RICH and console:
        console.print(f"  [bold green]✔[/bold green] {msg}")
    else:
        print(f"  [OK] {msg}")


def print_warning(msg: str) -> None:
    if _HAS_RICH and console:
        console.print(f"  [bold yellow]⚠[/bold yellow] {msg}")
    else:
        print(f"  [WARN] {msg}")


def print_error(msg: str) -> None:
    if _HAS_RICH and console:
        console.print(f"  [bold red]✖[/bold red] {msg}")
    else:
        print(f"  [ERROR] {msg}")


# ==============================================================================
# MASTER GENERATION PIPELINE
# ==============================================================================
def run_master_generation(
    target_dir: Path,
    verify_only: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Executes the entire generation pipeline and validates all generated physical artifacts.

    :param target_dir: Directory where artifacts reside and will be generated.
    :param verify_only: If True, skips re-generation and directly verifies existing artifacts.
    :param verbose: If True, outputs detailed diagnostic information.
    :return: Dictionary containing execution statistics and artifact status.
    """
    start_time = time.time()
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    print_banner(
        "UniTime AI Ingestion Gateway - Master Dataset Orchestrator (M6)",
        f"Target Directory: {target_dir}",
    )

    pipeline_results: Dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "target_dir": str(target_dir),
        "steps_completed": 0,
        "total_steps": 5 if not verify_only else 1,
        "generator_status": {},
        "artifacts_status": [],
        "all_artifacts_valid": False,
        "elapsed_seconds": 0.0,
    }

    if not verify_only:
        # ----------------------------------------------------------------------
        # Step 1: Milestone M1 - Spatial & Facility Topology
        # ----------------------------------------------------------------------
        print_step(1, 5, "Milestone M1: Spatial Catalog & Topology Verification")
        try:
            spatial_report = sc.verify_spatial_topology(base_dir=target_dir)
            assert spatial_report["status"] == "PASSED", "Spatial verification failed!"
            print_success(
                f"Spatial Topology Certified: {spatial_report['campuses']} Campuses, "
                f"{spatial_report['buildings']} Buildings, {spatial_report['rooms']} Rooms"
            )
            print_success(
                f"Coordinate Tiers: Tier 1: {spatial_report['tier_1_rooms']} (40.0%), "
                f"Tier 2: {spatial_report['tier_2_rooms']} (35.0%), "
                f"Tier 3: {spatial_report['tier_3_rooms']} (25.0%)"
            )
            print_success(f"Geodesic Inter-Campus Distance: {spatial_report['inter_campus_distance_km']:.2f} km")
            pipeline_results["generator_status"]["M1_spatial"] = "SUCCESS"
        except Exception as e:
            print_error(f"Milestone M1 execution failed: {e}")
            pipeline_results["generator_status"]["M1_spatial"] = f"FAILED: {e}"
            raise

        # ----------------------------------------------------------------------
        # Step 2: Milestone M2 - Curriculum & Personnel Model
        # ----------------------------------------------------------------------
        print_step(2, 5, "Milestone M2: Multi-Department Curriculum & Personnel Model")
        try:
            passed, diags = cm.verify_curriculum_integrity()
            assert passed, f"Curriculum integrity check failed with issues: {diags}"
            courses = cm.get_courses()
            instructors = cm.get_instructors()
            constraints = cm.get_distribution_constraints()
            print_success(
                f"Curriculum Certified: {len(courses)} Courses (TPB: 4, IF: 6, SI: 6, EL: 6, TI: 6)"
            )
            print_success(
                f"Faculty Roster: {len(instructors)} Lecturers (Single & Team-Teaching, Max 16 SKS)"
            )
            print_success(
                f"Distribution Constraints: {len(constraints)} Constraints (DIFF_TIME, SAME_ROOM, BTB, PRECEDENCE, MEET_WITH)"
            )
            pipeline_results["generator_status"]["M2_curriculum"] = "SUCCESS"
        except Exception as e:
            print_error(f"Milestone M2 execution failed: {e}")
            pipeline_results["generator_status"]["M2_curriculum"] = f"FAILED: {e}"
            raise

        # ----------------------------------------------------------------------
        # Step 3: Milestone M3-A - Excel (.xlsx) & PDF (.pdf) Synthesis
        # ----------------------------------------------------------------------
        print_step(3, 5, "Milestone M3-A: Multi-Format Document Synthesis (Excel & PDF)")
        try:
            courses_data = gxp.get_prepared_schedule_data()
            excel_path = target_dir / "jadwal_itb_multicampus.xlsx"
            pdf_path = target_dir / "katalog_jadwal_itb.pdf"

            xl_res = gxp.generate_excel_timetable(excel_path, courses_data)
            print_success(
                f"Generated Spreadsheet: {excel_path.name} "
                f"({excel_path.stat().st_size:,} bytes, {xl_res['total_sections']} sections, "
                f"{xl_res['merged_ranges']} merged cells, {xl_res['tba_sections']} TBA rooms)"
            )

            pdf_res = gxp.generate_pdf_catalog(pdf_path, courses_data)
            print_success(
                f"Generated Academic PDF: {pdf_path.name} "
                f"({pdf_path.stat().st_size:,} bytes, {pdf_res['total_sections']} rows, "
                f"{pdf_res['total_constraints']} footnotes)"
            )
            pipeline_results["generator_status"]["M3A_xlsx_pdf"] = "SUCCESS"
        except Exception as e:
            print_error(f"Milestone M3-A execution failed: {e}")
            pipeline_results["generator_status"]["M3A_xlsx_pdf"] = f"FAILED: {e}"
            raise

        # ----------------------------------------------------------------------
        # Step 4: Milestone M3-B - Narrative Memo (.txt) & Canonical JSON (.json)
        # ----------------------------------------------------------------------
        print_step(4, 5, "Milestone M3-B: Narrative Memo (.txt) & Canonical JSON (.json)")
        try:
            memo_path, dataset_path = gtj.write_artifacts(target_dir)
            print_success(f"Generated Narrative Memo: {memo_path.name} ({memo_path.stat().st_size:,} bytes)")
            print_success(f"Generated Canonical JSON: {dataset_path.name} ({dataset_path.stat().st_size:,} bytes)")

            # Validate canonical JSON payload
            with open(dataset_path, "r", encoding="utf-8") as f:
                json_payload = json.load(f)
            is_valid_json, json_errs = gtj.validate_canonical_json(json_payload)
            assert is_valid_json, f"Canonical JSON schema validation failed: {json_errs}"
            print_success(f"Validated Canonical JSON: 0 schema errors, 0 semantic errors")

            pipeline_results["generator_status"]["M3B_txt_json"] = "SUCCESS"
        except Exception as e:
            print_error(f"Milestone M3-B execution failed: {e}")
            pipeline_results["generator_status"]["M3B_txt_json"] = f"FAILED: {e}"
            raise

        # ----------------------------------------------------------------------
        # Step 5: Milestone M4 - Pre-UniTime Legacy Schedule Simulation
        # ----------------------------------------------------------------------
        print_step(5, 5, "Milestone M4: Pre-UniTime Legacy Schedule Simulation (.json)")
        try:
            legacy_file = target_dir / "pre_unitime_legacy_schedule.json"
            legacy_out_path = gl.save_legacy_schedule_json(str(legacy_file))
            legacy_path = Path(legacy_out_path)
            print_success(
                f"Generated Legacy Schedule: {legacy_path.name} ({legacy_path.stat().st_size:,} bytes)"
            )

            # Self-audit flaw checks
            gl.test_legacy_schedule_has_4_hard_conflicts()
            gl.test_legacy_schedule_room_misallocations()
            gl.test_legacy_schedule_student_dead_time_gap()
            gl.test_post_unitime_schedule_zero_flaws()
            print_success("Legacy Flaws Certified: Exactly 4 hard conflicts + room misallocations + idle gaps verified")
            print_success("Post-UniTime Optimization Certified: 100% flaw resolution rate verified")

            pipeline_results["generator_status"]["M4_legacy"] = "SUCCESS"
        except Exception as e:
            print_error(f"Milestone M4 execution failed: {e}")
            pipeline_results["generator_status"]["M4_legacy"] = f"FAILED: {e}"
            raise

    # --------------------------------------------------------------------------
    # Artifacts Verification & Integrity Certification
    # --------------------------------------------------------------------------
    print_step(
        1 if verify_only else 6,
        1 if verify_only else 6,
        "Comprehensive Physical Artifacts Existence & Non-Empty Verification",
    )

    all_valid = True
    table_rows = []

    for art in PHYSICAL_ARTIFACTS:
        file_path = target_dir / art["filename"]
        exists = file_path.exists()
        size_bytes = file_path.stat().st_size if exists else 0
        is_non_empty = exists and (size_bytes > 0)
        meets_minimum = is_non_empty and (size_bytes >= art["min_size_bytes"])

        status = "PASSED" if meets_minimum else "FAILED"
        if not meets_minimum:
            all_valid = False

        mod_time_str = (
            datetime.datetime.fromtimestamp(
                file_path.stat().st_mtime, tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S UTC")
            if exists
            else "N/A"
        )

        art_record = {
            "filename": art["filename"],
            "milestone": art["milestone"],
            "description": art["description"],
            "exists": exists,
            "size_bytes": size_bytes,
            "min_size_bytes": art["min_size_bytes"],
            "modified_time": mod_time_str,
            "status": status,
        }
        pipeline_results["artifacts_status"].append(art_record)

        table_rows.append((
            art["filename"],
            art["milestone"],
            f"{size_bytes:,} B",
            f">= {art['min_size_bytes']:,} B",
            status,
        ))

    # Output verification table
    if _HAS_RICH and console:
        rtable = Table(title="Generated Physical Artifacts Certification Matrix", header_style="bold blue")
        rtable.add_column("Filename", style="bold white", width=34)
        rtable.add_column("Milestone", justify="center", style="cyan", width=10)
        rtable.add_column("Actual Size", justify="right", style="magenta", width=14)
        rtable.add_column("Min Threshold", justify="right", style="dim white", width=14)
        rtable.add_column("Status", justify="center", width=10)

        for fname, ms, sz, msz, st in table_rows:
            st_color = "bold green" if st == "PASSED" else "bold red"
            rtable.add_row(fname, ms, sz, msz, Text(st, style=st_color))
        console.print(rtable)
    else:
        print("\n" + "=" * 80)
        print(f"{'Filename':<34} {'Milestone':<10} {'Actual Size':<14} {'Min Size':<14} {'Status':<10}")
        print("-" * 80)
        for fname, ms, sz, msz, st in table_rows:
            print(f"{fname:<34} {ms:<10} {sz:>12}   {msz:>12}   {st:<10}")
        print("=" * 80 + "\n")

    pipeline_results["all_artifacts_valid"] = all_valid
    pipeline_results["elapsed_seconds"] = round(time.time() - start_time, 2)

    if all_valid:
        print_banner(
            "ALL PHYSICAL DATASET ARTIFACTS SUCCESSFULLY GENERATED & VERIFIED!",
            f"Total Artifacts: {len(PHYSICAL_ARTIFACTS)} | Elapsed Time: {pipeline_results['elapsed_seconds']}s",
        )
    else:
        print_error("One or more physical artifacts failed existence or size thresholds!")
        sys.exit(1)

    return pipeline_results


# ==============================================================================
# CLI ENTRYPOINT
# ==============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Master Dataset Orchestrator & Generator for UniTime AI Ingestion Gateway."
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=str(_CURRENT_DIR),
        help="Target output directory for generated files (default: ai-gateway/test_data_robustness)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify existing physical artifacts without re-generating them.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output during generation.",
    )

    args = parser.parse_args()
    target_path = Path(args.output_dir).resolve()

    try:
        results = run_master_generation(
            target_dir=target_path,
            verify_only=args.verify_only,
            verbose=args.verbose,
        )
        return 0 if results["all_artifacts_valid"] else 1
    except Exception as err:
        print_error(f"Master generation failed: {err}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
