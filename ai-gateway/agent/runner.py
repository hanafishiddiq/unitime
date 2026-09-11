"""UniTime AI Ingestion Gateway - Interactive Agent CLI Runner.

Provides a rich terminal UI runner for the LangGraph StateGraph pipeline,
streaming node executions, gracefully handling human-in-the-loop interrupts,
presenting ambiguity questions, capturing user feedback, and generating final summaries.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .graph import build_ingest_graph
from .state import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_WAITING_FOR_HUMAN,
    create_initial_state,
)

logger = logging.getLogger(__name__)
console = Console()


def _display_banner(
    document_path: Path,
    provider: str,
    submit: bool,
    interactive: bool,
) -> None:
    """Print visually structured greeting panel for agent execution."""
    mode_desc = "LIVE SUBMISSION" if submit else "DRY-RUN (Validation & Audit)"
    inter_desc = "ENABLED (Interactive CLI)" if interactive else "DISABLED (Auto-Resolve)"

    content = (
        f"[bold cyan]Input Document:[/bold cyan] {document_path.name}\n"
        f"[bold cyan]LLM Provider:[/bold cyan] [bold yellow]{provider.upper()}[/bold yellow]\n"
        f"[bold cyan]Execution Mode:[/bold cyan] [bold green]{mode_desc}[/bold green]\n"
        f"[bold cyan]Human-in-the-Loop:[/bold cyan] [bold magenta]{inter_desc}[/bold magenta]\n"
        f"[bold cyan]Engine:[/bold cyan] [bold white]LangGraph StateGraph Workflow[/bold white]"
    )
    console.print(
        Panel(
            content,
            title="[bold white on blue] UniTime Smart Ingestion Agent [/bold white on blue]",
            border_style="blue",
        )
    )
    console.print()


def _display_node_progress(node_name: str, node_output: Dict[str, Any]) -> None:
    """Log formatted progress updates for individual node completions."""
    if node_name == "slice":
        slices = node_output.get("slices", [])
        console.print(
            f"[bold blue]⚡ [Phase 1/5] Slicing:[/bold blue] Produced [bold green]{len(slices)}[/bold green] document chunk(s)."
        )
    elif node_name == "extract_chunk":
        idx = node_output.get("current_slice_index", 1)
        partials = node_output.get("partial_payloads", [])
        console.print(
            f"[bold blue]🔍 [Phase 2/5] Extraction:[/bold blue] Extracted slice chunk [bold cyan]{idx}[/bold cyan] ({len(partials)} payload(s) aggregated so far)."
        )
    elif node_name == "merge":
        unified = node_output.get("unified_payload") or {}
        courses = unified.get("courses", [])
        console.print(
            f"[bold blue]🔗 [Phase 3/5] Consolidation:[/bold blue] Unified into [bold green]{len(courses)}[/bold green] course offering(s)."
        )
    elif node_name == "reason_validate":
        val_res = node_output.get("validation_result") or {}
        is_valid = val_res.get("is_valid", False)
        ambiguities = node_output.get("ambiguities", [])
        val_badge = "[bold green]VALID[/bold green]" if is_valid else "[bold red]INVALID[/bold red]"
        console.print(
            f"[bold blue]🧠 [Phase 4/5] ReAct Reasoning:[/bold blue] Schema Status: {val_badge} | Ambiguities: [bold yellow]{len(ambiguities)}[/bold yellow]."
        )
    elif node_name == "human_interrupt":
        console.print("[bold yellow]⏸️  Workflow interrupted for human disambiguation.[/bold yellow]")
    elif node_name == "apply_feedback":
        console.print("[bold green]✔ Human feedback applied and persisted to agent memory.[/bold green]")
    elif node_name == "submit":
        ingest_res = node_output.get("ingest_result") or {}
        st = ingest_res.get("status", "UNKNOWN")
        console.print(
            f"[bold blue]🚀 [Phase 5/5] UniTime Submission:[/bold blue] Status: [bold green]{st}[/bold green]."
        )
    elif node_name == "admin_reporter":
        console.print("[bold green]📄 Executive Markdown audit report written.[/bold green]")


def _handle_human_interrupt(
    interrupt_payload: Any,
    interactive: bool = True,
) -> Dict[str, str]:
    """Present ambiguities to the user and prompt for resolution response."""
    ambiguities: List[Dict[str, Any]] = []

    if isinstance(interrupt_payload, dict):
        ambiguities = interrupt_payload.get("ambiguities", [])
    elif isinstance(interrupt_payload, list):
        ambiguities = interrupt_payload

    console.print()
    console.print(
        Panel(
            f"[bold red]Human Intervention Required[/bold red]\n"
            f"The agent detected [bold yellow]{len(ambiguities)}[/bold yellow] ambiguity/conflict(s) "
            "that require human disambiguation before finalizing the schedule.",
            title="[bold white on red] ⚠️ AMBIGUITY REVIEW [/bold white on red]",
            border_style="red",
        )
    )

    table = Table(title="Pending Ambiguities & Conflicts", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Type", style="cyan", width=18)
    table.add_column("Question / Conflict Details", style="white")
    table.add_column("Suggested Options", style="yellow")

    all_options: List[str] = []

    for i, amb in enumerate(ambiguities, 1):
        if isinstance(amb, dict):
            amb_type = amb.get("type", "general")
            q = amb.get("question", "Unspecified issue.")
            opts = amb.get("options", ["Approve", "Reject"])
            if opts:
                all_options.extend(opts)
            opts_str = " | ".join(opts) if opts else "Freeform answer"
            table.add_row(str(i), amb_type, q, opts_str)
        else:
            table.add_row(str(i), "general", str(amb), "Approve | Reject")

    console.print(table)
    console.print()

    responses = {}

    # Non-interactive mode: Automatically select default
    if not interactive:
        for amb in ambiguities:
            amb_id = amb.get("id") if isinstance(amb, dict) else "unknown"
            opts = amb.get("options", []) if isinstance(amb, dict) else []
            default_choice = opts[0] if opts else "Approved automatically"
            console.print(
                f"[bold yellow]Non-interactive mode active: Auto-selected default resolution for {amb_id}:[/bold yellow] [bold green]'{default_choice}'[/bold green]"
            )
            responses[amb_id] = default_choice
        return responses

    # Interactive mode: Prompt user per ambiguity
    for i, amb in enumerate(ambiguities, 1):
        if not isinstance(amb, dict):
            continue
        amb_id = amb.get("id", str(i))
        console.print(f"\n[bold cyan]Resolving #{i}: {amb_id}[/bold cyan]")
        opts = amb.get("options", [])

        if opts:
            console.print("[dim]Select an option number, type an option name, or enter custom instructions:[/dim]")
            for idx, opt in enumerate(opts, 1):
                console.print(f"  [bold yellow]{idx}[/bold yellow]. {opt}")

            user_input = Prompt.ask(
                f"\n[bold green]Your Choice / Decision for {amb_id}[/bold green]",
                default="1",
            )

            if user_input.isdigit():
                opt_idx = int(user_input) - 1
                if 0 <= opt_idx < len(opts):
                    responses[amb_id] = opts[opt_idx]
                else:
                    responses[amb_id] = user_input.strip()
            else:
                responses[amb_id] = user_input.strip()
        else:
            user_input = Prompt.ask(
                f"[bold green]Your Resolution Decision for {amb_id}[/bold green]",
                default="Approved",
            )
            responses[amb_id] = user_input.strip()

    return responses


def _display_final_summary(final_state: Dict[str, Any]) -> None:
    """Display final execution summary table."""
    status = final_state.get("status", "unknown")
    unified = final_state.get("unified_payload") or {}
    courses = unified.get("courses", []) if isinstance(unified, dict) else []

    total_classes = 0
    for c in courses:
        if isinstance(c, dict):
            for cfg in c.get("configurations", []):
                if isinstance(cfg, dict):
                    for sp in cfg.get("subparts", []):
                        if isinstance(sp, dict):
                            total_classes += len(sp.get("classes", []))

    val_res = final_state.get("validation_result") or {}
    val_passed = bool(val_res.get("is_valid", False)) if isinstance(val_res, dict) else False

    ingest_res = final_state.get("ingest_result") or {}
    ingest_status = ingest_res.get("status", "NOT_SUBMITTED") if isinstance(ingest_res, dict) else "N/A"

    audit_logs = final_state.get("audit_logs", [])
    report_path_str = "See reports/ directory"
    for log in reversed(audit_logs):
        if isinstance(log, dict) and "Executive audit report generated at" in log.get("message", ""):
            report_path_str = log["message"].split("at '", 1)[-1].rstrip("'")
            break

    summary_table = Table(title="Ingestion Execution Outcome", show_header=True, header_style="bold green")
    summary_table.add_column("Pipeline Phase", style="cyan")
    summary_table.add_column("Status / Metric", style="bold white")

    status_style = "bold green" if status == STATUS_COMPLETED else "bold red"
    summary_table.add_row("Overall Agent Status", f"[{status_style}]{status.upper()}[/{status_style}]")
    summary_table.add_row("Total Courses Extracted", str(len(courses)))
    summary_table.add_row("Total Classes Generated", str(total_classes))
    summary_table.add_row("Schema Validation", "[bold green]PASSED[/bold green]" if val_passed else "[bold red]FAILED[/bold red]")
    summary_table.add_row("UniTime Persistence", f"[bold cyan]{ingest_status}[/bold cyan]")
    summary_table.add_row("Audit Report Path", f"[dim]{report_path_str}[/dim]")

    console.print()
    console.print(summary_table)
    console.print()


def run_agent_pipeline(
    document_path: Union[Path, str],
    document_type: str = "auto",
    provider: str = "mock",
    model: Optional[str] = None,
    dry_run: bool = False,
    submit: bool = False,
    interactive: bool = True,
    unitime_url: Optional[str] = None,
    reports_dir: Optional[Union[Path, str]] = None,
    memory_db_path: Optional[Union[Path, str]] = None,
    render_images: bool = False,
    strict: bool = False,
    checkpointer: Optional[Any] = None,
    thread_id: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Execute the full LangGraph ingestion workflow with rich UI and human-in-the-loop support.

    Args:
        document_path: Path to the input curriculum document.
        document_type: Classification format ('auto', 'pdf', 'excel', 'text').
        provider: LLM extraction provider ('mock', 'gemini', 'openai', 'anthropic').
        model: Optional LLM model identifier.
        dry_run: If True, executes validation and reporting without live submission.
        submit: If True and dry_run is False, persists data to UniTime REST API.
        interactive: If True, prompts user for ambiguity resolution via stdin.
        unitime_url: Custom UniTime Smart Ingest endpoint URL.
        reports_dir: Custom directory for storing executive markdown audit reports.
        memory_db_path: Custom SQLite database path for agent memory.
        render_images: If True, renders PDF pages as images for multimodal vision.
        strict: Enforce strict semantic validation.
        checkpointer: LangGraph checkpointer instance (defaults to MemorySaver).
        thread_id: Unique thread conversation identifier for checkpointer.
        verbose: Enable detailed logging output.

    Returns:
        Final state dictionary (IngestAgentState).
    """
    doc_file = Path(document_path).resolve()
    if not doc_file.exists():
        raise FileNotFoundError(f"Target document not found: {doc_file}")

    active_provider = (provider or os.getenv("DEFAULT_LLM_PROVIDER", "mock")).lower()
    should_submit = submit and not dry_run

    _display_banner(doc_file, active_provider, should_submit, interactive)

    # Initialize agent memory context
    memory_context: Dict[str, Any] = {
        "provider": active_provider,
        "model": model,
        "dry_run": not should_submit,
        "submit": should_submit,
        "unitime_url": unitime_url or os.getenv("UNITIME_API_URL"),
        "reports_dir": str(reports_dir) if reports_dir else None,
        "memory_db_path": str(memory_db_path) if memory_db_path else None,
        "render_images": render_images,
        "strict": strict,
    }

    initial_state = create_initial_state(
        document_path=str(doc_file),
        document_type=document_type,
        memory_context=memory_context,
    )

    active_checkpointer = checkpointer if checkpointer is not None else MemorySaver()
    graph = build_ingest_graph(checkpointer=active_checkpointer)

    session_thread_id = thread_id or f"ingest_{uuid.uuid4().hex[:8]}"
    config: Dict[str, Any] = {"configurable": {"thread_id": session_thread_id}}

    current_input: Any = initial_state

    # Workflow loop supporting multiple interrupts if needed
    while True:
        interrupted = False
        interrupt_payload: Any = None

        for event in graph.stream(current_input, config=config):
            if isinstance(event, dict):
                for node_name, node_output in event.items():
                    if node_name == "__interrupt__":
                        interrupted = True
                        if isinstance(node_output, (list, tuple)) and len(node_output) > 0:
                            interrupt_payload = getattr(node_output[0], "value", node_output[0])
                        else:
                            interrupt_payload = node_output
                    else:
                        _display_node_progress(node_name, node_output)

        graph_state = graph.get_state(config)

        # Check if workflow reached natural completion
        if not graph_state.next:
            break

        # Check if paused on task interrupts
        if graph_state.tasks:
            for task in graph_state.tasks:
                if task.interrupts:
                    interrupted = True
                    interrupt_payload = task.interrupts[0].value
                    break

        if interrupted:
            user_response = _handle_human_interrupt(interrupt_payload, interactive=interactive)
            # Resume graph execution using LangGraph Command(resume=...)
            current_input = Command(resume=user_response)
        else:
            break

    final_state = graph.get_state(config).values
    _display_final_summary(final_state)

    return final_state
