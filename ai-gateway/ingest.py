#!/usr/bin/env python3
"""UniTime AI Ingestion Gateway - Command Line Interface (CLI).

Orchestrates the complete end-to-end extraction pipeline:
  Input Detection -> Slicer -> Extractor (Page/Chunk) -> Merger -> Validator -> UniTime Submission
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# Add gateway root to sys.path
GATEWAY_DIR = Path(__file__).resolve().parent
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))

from core.client import (
    UniTimeClient,
    UniTimeConnectionError,
    UniTimeResponseError,
)
from core.extractor import (
    BaseExtractor,
    ExtractionError,
    get_extractor,
)
from core.merger import Merger
from core.slicer import DocumentSlicer, SliceChunk
from core.validator import ValidationResult, Validator

# Load environment variables
load_dotenv(GATEWAY_DIR / ".env")

console = Console()
logger = logging.getLogger("ai-gateway")


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging level."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="unitime-ai-ingest",
        description="UniTime AI Ingestion Gateway: Extract, Validate, and Ingest Timetabling Data.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to input document (PDF, Excel .xlsx, CSV, TXT memo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Execute extraction, merging, and validation without submitting to UniTime.",
    )
    parser.add_argument(
        "-s",
        "--submit",
        action="store_true",
        help="Submit the validated payload to the UniTime Smart Ingest API.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Path to save the resulting validated JSON payload.",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("DEFAULT_LLM_PROVIDER", "mock"),
        choices=["mock", "gemini", "openai", "anthropic", "custom", "openrouter", "ollama", "vllm", "proxy"],
        help="LLM extraction provider.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL") or os.getenv("LLM_ENDPOINT"),
        help="Custom LLM API base URL / endpoint (for OpenRouter, Ollama, vLLM, or custom proxies).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Convenience alias to force using the deterministic mock extractor.",
    )
    parser.add_argument(
        "--model",
        help="Optional LLM model override (e.g. gpt-4o, gemini-1.5-pro, claude-3-5-sonnet).",
    )
    parser.add_argument(
        "--unitime-url",
        default=os.getenv("UNITIME_API_URL", "http://localhost:8080/unitime/api/smart-ingest"),
        help="Target UniTime Smart Ingest endpoint URL.",
    )
    parser.add_argument(
        "--render-images",
        action="store_true",
        help="Render PDF pages as images for multimodal vision extraction instead of text extraction.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Enforce strict semantic validation (treat warnings as errors).",
    )
    parser.add_argument(
        "-a",
        "--agent",
        action="store_true",
        help="Execute ingestion via the LangGraph StateGraph autonomous agent.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        default=True,
        help="Enable interactive human-in-the-loop prompt resolution during agent execution.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_false",
        dest="interactive",
        help="Disable interactive CLI prompts; auto-resolve ambiguities with defaults.",
    )
    parser.add_argument(
        "--reports-dir",
        help="Optional directory to save agent executive Markdown audit reports.",
    )
    parser.add_argument(
        "--memory-db",
        help="Optional SQLite database path for persistent agent memory.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed debug output.",
    )

    return parser.parse_args()


def display_banner(provider: str, input_path: Path, submit: bool) -> None:
    """Print visually structured greeting panel."""
    mode_desc = "SUBMISSION MODE (Live Ingest)" if submit else "DRY-RUN MODE (Validation Only)"
    content = (
        f"[bold cyan]Input Document:[/bold cyan] {input_path.name}\n"
        f"[bold cyan]Extraction Provider:[/bold cyan] [bold yellow]{provider.upper()}[/bold yellow]\n"
        f"[bold cyan]Execution Mode:[/bold cyan] [bold green]{mode_desc}[/bold green]"
    )
    console.print(
        Panel(
            content,
            title="[bold white on blue] UniTime AI Ingestion Gateway [/bold white on blue]",
            border_style="blue",
        )
    )


def extract_chunks(
    chunks: List[SliceChunk], extractor: BaseExtractor
) -> List[Dict[str, Any]]:
    """Iterate through document chunks and extract partial payloads with progress tracking."""
    partial_payloads: List[Dict[str, Any]] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Extracting document chunks...", total=len(chunks))

        for chunk in chunks:
            progress.update(
                task,
                description=f"[cyan]Processing chunk {chunk.chunk_id}/{chunk.total_chunks} ({chunk.chunk_type})...",
            )
            context = {
                "sourceDocumentName": chunk.source_filename,
                "chunk_id": chunk.chunk_id,
                "total_chunks": chunk.total_chunks,
                **chunk.metadata,
            }

            try:
                if chunk.chunk_type == "image" and chunk.image_bytes:
                    res = extractor.extract_image(
                        chunk.image_bytes,
                        mime_type=chunk.mime_type or "image/png",
                        context=context,
                    )
                else:
                    text = chunk.text_content or ""
                    res = extractor.extract_text(text, context=context)

                if res and res.payload:
                    partial_payloads.append(res.payload)
            except ExtractionError as exc:
                logger.error("Failed to extract chunk %s: %s", chunk.chunk_id, exc)
                console.print(f"[red]Error extracting chunk {chunk.chunk_id}: {exc}[/red]")
            finally:
                progress.advance(task)

    return partial_payloads


def display_validation_report(result: ValidationResult) -> None:
    """Print structured table of validation errors and warnings."""
    if result.is_valid:
        console.print("[bold green]✔ Schema and Semantic Validation PASSED![/bold green]\n")
    else:
        console.print(
            f"[bold red]✘ Validation FAILED with {len(result.errors)} error(s):[/bold red]"
        )
        error_table = Table(show_header=True, header_style="bold red")
        error_table.add_column("Location / Path", style="dim", width=40)
        error_table.add_column("Rule / Validator", style="cyan", width=20)
        error_table.add_column("Message", style="white")

        for err in result.errors:
            error_table.add_row(err.path or "[root]", err.validator, err.message)
        console.print(error_table)
        console.print()

    if result.warnings:
        console.print(
            f"[bold yellow]⚠ {len(result.warnings)} Semantic Warning(s):[/bold yellow]"
        )
        warn_table = Table(show_header=True, header_style="bold yellow")
        warn_table.add_column("Warning Details", style="yellow")
        for warn in result.warnings:
            warn_table.add_row(warn)
        console.print(warn_table)
        console.print()


def display_payload_summary(payload: Dict[str, Any]) -> None:
    """Print high-level metrics for the aggregated payload."""
    session = payload.get("academicSession", {})
    dept = payload.get("department", {})
    sa = payload.get("subjectArea", {})
    courses = payload.get("courses", [])
    constraints = payload.get("distributionConstraints", [])

    total_classes = 0
    total_configs = 0
    for c in courses:
        for cfg in c.get("configurations", []):
            total_configs += 1
            for sp in cfg.get("subparts", []):
                total_classes += len(sp.get("classes", []))

    summary_table = Table(title="Aggregated Payload Metrics", show_header=True, header_style="bold magenta")
    summary_table.add_column("Attribute", style="cyan")
    summary_table.add_column("Value", style="bold white")

    summary_table.add_row("Academic Session", f"{session.get('term', '')} {session.get('year', '')} ({session.get('campus', '')})")
    summary_table.add_row("Department", f"{dept.get('name', '')} ({dept.get('code', '')})")
    summary_table.add_row("Subject Area", f"{sa.get('title', '')} ({sa.get('abbreviation', '')})")
    summary_table.add_row("Total Courses", str(len(courses)))
    summary_table.add_row("Total Configurations", str(total_configs))
    summary_table.add_row("Total Class Sections", str(total_classes))
    summary_table.add_row("Distribution Constraints", str(len(constraints)))

    console.print(summary_table)
    console.print()


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_arguments()
    setup_logging(args.verbose)

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        console.print(f"[bold red]Error: Input file not found:[/bold red] {input_path}")
        return 1

    provider = "mock" if args.mock else args.provider
    should_submit = args.submit and not args.dry_run

    display_banner(provider, input_path, should_submit)

    # Autonomous Agent Execution via LangGraph
    if args.agent:
        from agent.runner import run_agent_pipeline

        try:
            final_state = run_agent_pipeline(
                document_path=input_path,
                provider=provider,
                model=args.model,
                dry_run=args.dry_run or not args.submit,
                submit=should_submit,
                interactive=args.interactive,
                unitime_url=args.unitime_url,
                reports_dir=args.reports_dir,
                memory_db_path=args.memory_db,
                render_images=args.render_images,
                strict=args.strict,
                verbose=args.verbose,
            )

            # Save output JSON if requested
            if args.output and final_state.get("unified_payload"):
                out_path = Path(args.output).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(final_state["unified_payload"], indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                console.print(f"[bold green]Saved validated payload to:[/bold green] {out_path}\n")

            if final_state.get("status") == "error":
                return 1
            return 0
        except Exception as exc:
            console.print(f"[bold red]Agent pipeline execution failed:[/bold red] {exc}")
            if args.verbose:
                logger.exception("Agent execution exception")
            return 1

    # 1. Slice Document
    console.print(f"[bold blue]Step 1: Slicing document...[/bold blue]")
    slicer = DocumentSlicer(render_pdf_as_images=args.render_images)
    try:
        chunks = slicer.slice_file(input_path)
    except Exception as exc:
        console.print(f"[bold red]Failed to slice document:[/bold red] {exc}")
        return 1

    console.print(f"Generated [bold green]{len(chunks)}[/bold green] chunk(s) from {input_path.name}.\n")

    # 2. Extract Chunks via LLM / Mock
    console.print(f"[bold blue]Step 2: Extracting data with provider '{provider}'...[/bold blue]")
    try:
        extractor = get_extractor(provider=provider, model=args.model, base_url=args.base_url)
    except Exception as exc:
        console.print(f"[bold red]Failed to initialize extractor:[/bold red] {exc}")
        return 1

    partial_payloads = extract_chunks(chunks, extractor)
    if not partial_payloads:
        console.print("[bold red]No valid payloads extracted from input chunks.[/bold red]")
        return 1

    # 3. Merge & Aggregate
    console.print(f"[bold blue]Step 3: Merging {len(partial_payloads)} partial payload(s)...[/bold blue]")
    merger = Merger()
    merged_payload = merger.merge(partial_payloads)
    # Ensure source document name is preserved
    merged_payload.setdefault("ingestControl", {})["sourceDocumentName"] = input_path.name
    display_payload_summary(merged_payload)

    # 4. Validate Schema & Semantics
    console.print(f"[bold blue]Step 4: Validating against UniTime schema...[/bold blue]")
    validator = Validator(strict_semantics=args.strict)
    val_result = validator.validate(merged_payload)
    display_validation_report(val_result)

    if not val_result.is_valid:
        console.print("[bold red]Validation failed. Aborting ingestion pipeline.[/bold red]")
        return 1

    # Save output JSON if requested
    if args.output:
        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(merged_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"[bold green]Saved validated payload to:[/bold green] {out_path}\n")

    # 5. Submit to UniTime API
    if should_submit:
        console.print(f"[bold blue]Step 5: Submitting payload to UniTime at {args.unitime_url}...[/bold blue]")
        client = UniTimeClient(base_url=args.unitime_url)

        try:
            # Check endpoint health/readiness first
            console.print("Checking UniTime API connectivity...")
            client.health_check()
            console.print("[green]UniTime API endpoint is reachable and responsive.[/green]")
        except UniTimeConnectionError as conn_err:
            console.print(f"[bold red]Failed to connect to UniTime:[/bold red] {conn_err}")
            return 2
        except Exception as exc:
            logger.warning("Health check warning: %s", exc)

        try:
            response = client.submit_ingest(merged_payload)
            console.print(Panel(response.summary_text(), title="UniTime Response Report", border_style="green" if response.is_success else "red"))

            if not response.is_success:
                console.print("[bold red]Ingestion completed with errors or rejected by UniTime.[/bold red]")
                return 2

            console.print("[bold green]✔ Ingestion successfully committed into UniTime![/bold green]")
        except Exception as exc:
            console.print(f"[bold red]Ingestion submission failed:[/bold red] {exc}")
            return 2
    else:
        console.print("[bold yellow]Dry-run finished. (Use --submit to commit data to UniTime)[/bold yellow]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
