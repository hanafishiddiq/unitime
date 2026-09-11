"""UniTime AI Ingestion Gateway - Agent Subsystem.

Provides LangGraph-compatible state definitions, SQLite persistent memory,
ReAct agent tools, workflow nodes, compiled StateGraph, executive reporting,
and interactive CLI runner for curriculum ingestion.
"""

from __future__ import annotations

from .graph import build_ingest_graph, check_ambiguities, has_more_slices
from .memory import AgentMemory
from .nodes import (
    admin_reporter_node,
    apply_feedback_node,
    extract_chunk_node,
    human_interrupt_node,
    merge_node,
    reason_validate_node,
    slice_node,
    submit_node,
)
from .reporter import write_admin_report
from .runner import run_agent_pipeline
from .state import (
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_PROCESSING,
    STATUS_WAITING_FOR_HUMAN,
    AgentStatus,
    IngestAgentState,
    create_initial_state,
)
from .tools import (
    ALL_TOOLS,
    check_time_conflict,
    generate_admin_summary,
    inspect_room_capacity,
    record_learned_resolution,
    resolve_instructor_identity,
)

__all__ = [
    # State
    "IngestAgentState",
    "create_initial_state",
    "AgentStatus",
    "STATUS_PROCESSING",
    "STATUS_WAITING_FOR_HUMAN",
    "STATUS_COMPLETED",
    "STATUS_ERROR",
    # Persistent Memory
    "AgentMemory",
    # Tools
    "inspect_room_capacity",
    "resolve_instructor_identity",
    "record_learned_resolution",
    "check_time_conflict",
    "generate_admin_summary",
    "ALL_TOOLS",
    # Workflow Nodes
    "slice_node",
    "extract_chunk_node",
    "merge_node",
    "reason_validate_node",
    "human_interrupt_node",
    "apply_feedback_node",
    "submit_node",
    "admin_reporter_node",
    # StateGraph
    "build_ingest_graph",
    "has_more_slices",
    "check_ambiguities",
    # Reporting & Runner
    "write_admin_report",
    "run_agent_pipeline",
]
