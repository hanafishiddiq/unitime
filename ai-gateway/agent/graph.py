"""UniTime AI Ingestion Gateway - LangGraph StateGraph Architecture.

Orchestrates the multi-phase curriculum ingestion lifecycle:
  START -> slice -> extract_chunk (loop) -> merge -> reason_validate
     -> [if ambiguities] -> human_interrupt -> apply_feedback -> (loop back to reason_validate)
     -> [if clean] -> submit -> admin_reporter -> END
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

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
from .state import STATUS_ERROR, IngestAgentState

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Conditional Edge Routers
# -----------------------------------------------------------------------------


def has_more_slices(state: IngestAgentState) -> str:
    """Evaluate whether document slices remain to be extracted.

    Returns:
        'extract_chunk' if more slices need processing; 'merge' once all slices are extracted.
    """
    if state.get("status") == STATUS_ERROR:
        logger.warning("has_more_slices: STATUS_ERROR encountered, proceeding to merge/reporting.")
        return "merge"

    slices = state.get("slices", [])
    idx = state.get("current_slice_index", 0)

    if idx < len(slices):
        return "extract_chunk"
    return "merge"


def check_ambiguities(state: IngestAgentState) -> str:
    """Evaluate whether unresolved ambiguities or conflicts require human review.

    Returns:
        'human_interrupt' if conflicts exist; 'submit' if payload is clean and ready.
    """
    if state.get("status") == STATUS_ERROR:
        logger.warning("check_ambiguities: Pipeline error encountered, routing directly to admin reporter.")
        return "admin_reporter"

    ambiguities = state.get("ambiguities", [])
    if ambiguities and len(ambiguities) > 0:
        logger.info(
            "check_ambiguities: Routing to human_interrupt for %d open ambiguities.",
            len(ambiguities),
        )
        return "human_interrupt"

    logger.info("check_ambiguities: Zero ambiguities pending, proceeding to UniTime submit.")
    return "submit"


# -----------------------------------------------------------------------------
# StateGraph Builder
# -----------------------------------------------------------------------------


def build_ingest_graph(
    checkpointer: Optional[Any] = None,
) -> CompiledStateGraph:
    """Construct and compile the UniTime Ingest StateGraph with checkpointer.

    Args:
        checkpointer: LangGraph checkpointer instance. Defaults to MemorySaver.

    Returns:
        CompiledStateGraph ready for synchronous or streaming execution.
    """
    builder = StateGraph(IngestAgentState)

    # 1. Register Graph Nodes
    builder.add_node("slice", slice_node)
    builder.add_node("extract_chunk", extract_chunk_node)
    builder.add_node("merge", merge_node)
    builder.add_node("reason_validate", reason_validate_node)
    builder.add_node("human_interrupt", human_interrupt_node)
    builder.add_node("apply_feedback", apply_feedback_node)
    builder.add_node("submit", submit_node)
    builder.add_node("admin_reporter", admin_reporter_node)

    # 2. Linear & Conditional Flow Edges
    builder.add_edge(START, "slice")
    builder.add_edge("slice", "extract_chunk")

    # Slices extraction loop
    builder.add_conditional_edges(
        "extract_chunk",
        has_more_slices,
        {
            "extract_chunk": "extract_chunk",
            "merge": "merge",
        },
    )

    builder.add_edge("merge", "reason_validate")

    # Ambiguity check: route to human interrupt or proceed to UniTime submission
    builder.add_conditional_edges(
        "reason_validate",
        check_ambiguities,
        {
            "human_interrupt": "human_interrupt",
            "submit": "submit",
            "admin_reporter": "admin_reporter",
        },
    )

    # Cyclic human-in-the-loop loop: interrupt -> feedback -> re-validation
    builder.add_edge("human_interrupt", "apply_feedback")
    builder.add_edge("apply_feedback", "reason_validate")

    # Terminal pipeline segment
    builder.add_edge("submit", "admin_reporter")
    builder.add_edge("admin_reporter", END)

    # 3. Compile Graph with Checkpointer
    active_checkpointer = checkpointer if checkpointer is not None else MemorySaver()
    compiled = builder.compile(checkpointer=active_checkpointer)

    return compiled
