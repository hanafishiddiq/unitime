# Original User Request

## 2026-09-12T13:10:50Z

Use a very large team of agents. Build a comprehensive, multi-campus academic test dataset, multi-format ingestion test suite, and legacy scheduling benchmark to rigorously stress-test the robustness of the UniTime AI Ingestion Gateway pipeline and automated timetabling solver. The system models realistic Indonesian Higher Education (SN-Dikti / ITB multi-campus) operations across 4 study programs (Teknik Informatika, Sistem Informasi, Teknik Elektro, Teknik Industri) spanning Kampus Ganesha and Kampus Jatinangor, featuring deliberate real-world edge cases (hierarchical missing coordinates, partial metadata, cross-department resource sharing), an independent QA & semantic auditor ensuring zero logical defects, and a pre-UniTime manual schedule baseline quantitatively compared against the post-UniTime solver solution.

Working directory: /Users/hanafi/Desktop/Rumah/Playground/UniTime Fork/ai-gateway/test_data_robustness
Integrity mode: development

## Requirements

### R1. Multi-Campus Spatial & Facility Topology with Tiered Coordinate Edge Cases
Construct a complete physical infrastructure model across Kampus Ganesha and Kampus Jatinangor encompassing buildings, rooms, capacities, and facilities:
- Room capacities spanning seminar rooms (20 seats), standard classrooms (40-60 seats), computer & hardware laboratories (25-35 workstations), up to large amphitheatres (120-250 seats).
- Room features and equipment flags (GPU Workstations, Projectors, Audio System, SmartBoard).
- Deliberate tiered coordinate edge cases to stress-test UniTime's distance matrix calculations:
  - Exactly ~40% of locations have complete, high-precision Cartesian/GPS (X, Y) coordinates.
  - Exactly ~35% have building-level coordinates only, where rooms have null coordinates and must inherit from their parent building.
  - Exactly ~25% have completely missing/null coordinates for both building and room, requiring graceful fallback by the distance solver.

### R2. Multi-Department Curriculum & Personnel Model
Model the academic structure across 4 distinct study programs (IF: Teknik Informatika, SI: Sistem Informasi, EL: Teknik Elektro, TI: Teknik Industri) across 25-35 courses:
- Common first-year courses (TPB / General Education e.g., Kalkulus, Fisika Dasar, Pengantar Rekayasa) shared across engineering cohorts.
- Core departmental courses with multi-tier subpart structures (e.g., 3 SKS Lecture + 1 SKS Lab, or Lecture + Recitation/Responsi).
- Parallel classes (K01, K02, etc.) and hierarchical parent-child relationships (Lab sections bound to Lecture sections).
- Faculty roster with realistic single and team-teaching allocations (50:50, 70:30 shares), lead lecturer designations, workload SKS caps, and realistic missing optional metadata (some missing emails or institutional IDs).
- Distribution constraints: `DIFF_TIME` (no conflict for shared lecturers), `SAME_ROOM` (specialized labs), `BACK_TO_BACK` (linked lectures/responsies), `PRECEDENCE` (theory preceding lab in the weekly cycle), and `MEET_WITH` (shared common courses).

### R3. Multi-Format Stress-Testing Ingestion Documents
Generate physical raw source documents in all 4 supported gateway formats, populated with the synchronized curriculum data:
- **Excel Spreadsheet (`.xlsx`)**: Formatted with merged multi-row header banners, merged subject cells, missing room numbers on selected sections, and multi-instructor semicolon delimiters.
- **Academic Catalog & Directive PDF (`.pdf`)**: Formal administrative timetable document featuring multi-column layouts, table headers repeating across pages, and distribution constraint footnotes.
- **Narrative Administrative Memo (`.txt`)**: Conversational dean directive containing room preference requests, instructor day-off constraints, and timetable amendment notices.
- **Canonical Schema JSON (`.json`)**: Formatted and strictly conformant to `unitime-smart-ingest-schema.json`.

### R4. Pre-UniTime Legacy Schedule Simulation (Manual Flawed Baseline)
Construct a realistic manual timetable representing what academic administration traditionally created before adopting UniTime:
- Demonstrates real-world human scheduling flaws:
  - 2-3 hidden instructor or room time conflicts (`hard constraint violations`).
  - Severe room under-utilization and misallocation (e.g., 20 students assigned to a 150-seat auditorium while a 50-student class is squeezed into a 45-seat room).
  - Excessive student dead-time gaps (e.g., 4-hour idle gaps between classes).
  - Impractical travel demands (classes scheduled 10 minutes apart across different campuses or distant buildings).

### R5. Post-UniTime Solver Comparison & Executive Evaluation Report
Generate an automated comparative evaluation matrix contrasting the Pre-UniTime legacy proposal against the UniTime optimized timetable:
- Room capacity utilization efficiency (% seat occupancy).
- Conflict elimination rate (100% hard constraints resolved).
- Student schedule compactness (reduction in idle window hours).
- Instructor campus-crossing / travel travel time optimization.
- Executive summary report in Markdown with visual tables and comparative bar charts.

### R6. Independent QA & Semantic Consistency Auditor
Implement an automated validation suite that programmatically cross-checks the entire dataset before finalizing:
- Referential integrity across all files (every room referenced in schedules exists in the facility catalog; every instructor referenced exists in the staff roster).
- Room capacity >= class section capacity for all assigned allocations.
- Pedagogical validity (no lab precedes its theory class in the same week when `PRECEDENCE` is enforced).
- Zero unhandled exceptions when passing files through the AI Gateway parsers and schema validator.

## Verification Resources & Mechanisms

- **Automated Validation Script (`verify_dataset.py`)**: Programmatic test script validating referential integrity, room capacity bounds, distribution constraints, coordinate fallbacks, and schema conformance.
- **AI Gateway Integration Runner**: Running `python ingest.py` on the generated `.xlsx`, `.pdf`, `.txt`, and `.json` files in dry-run mode, verifying that schema validation passes and comprehensive reports are emitted in `reports/`.
- **Legacy vs UniTime Comparative Benchmark**: Automated metrics comparison script computing seat utilization, travel distance, conflict counts, and idle hours.

## Acceptance Criteria

### Spatial & Data Completeness
- [ ] At least 2 campuses, 6 buildings, and 20 rooms are defined with realistic capacities and equipment tags.
- [ ] Tiered coordinate distribution strictly verified: 40% (±5%) complete X/Y, 35% (±5%) building-only X/Y (rooms null), and 25% (±5%) null coordinates.
- [ ] All 4 study programs (IF, SI, EL, TI) are represented with a total of 25 to 35 courses and appropriate SKS/subpart configurations.

### Document & Format Robustness
- [ ] All 4 physical files (`.xlsx`, `.pdf`, `.txt`, `.json`) are generated in the working directory and successfully parsed by gateway slicers without unhandled crashes.
- [ ] The generated canonical JSON validates cleanly against `unitime-smart-ingest-schema.json`.

### Pre vs Post Comparison Integrity
- [ ] Pre-UniTime manual schedule document explicitly marks and quantifies all human-scheduling flaws (at least 2 hidden conflicts, severe room size mismatches, and multi-hour student gaps).
- [ ] Comparative analysis report quantitatively proves UniTime's optimization improvements across utilization, travel, and conflict metrics.

### QA Auditor Gate
- [ ] Automated verification script executes cleanly with zero assertion failures and zero orphaned foreign keys.
- [ ] Comprehensive Markdown executive audit report is produced, certifying the dataset as production-ready for robustness testing.
