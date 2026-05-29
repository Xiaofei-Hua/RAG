"""
Planner

Determines the execution plan for an agent run:
- Thinking mode: full graph (intent -> agent -> retrieve -> grade -> generate/rewrite)
- Fast mode: direct (retrieve -> generate) skipping agent, grade, rewrite

The planner considers:
1. User's explicit mode preference (if provided)
2. Intent classification result
3. Session history / configuration
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.log_utils import log

__all__ = [
    "ExecutionPlan",
    "PlanType",
    "Planner",
]


class PlanType:
    """Execution plan types."""
    THINKING = "thinking"
    FAST = "fast"
    DIRECT = "direct"  # General chat, no retrieval needed


@dataclass
class ExecutionPlan:
    """
    Describes how the agent should execute a query.

    Attributes:
        plan_type: One of 'thinking', 'fast', 'direct'
        skills: Ordered list of skill names to execute
        mode: Human-readable description
    """
    plan_type: str
    skills: List[str]
    mode: str = ""

    # Pre-built plans for common paths
    @classmethod
    def thinking_plan(cls) -> ExecutionPlan:
        """Full thinking mode: agent -> retrieve -> grade -> generate/rewrite."""
        return cls(
            plan_type=PlanType.THINKING,
            skills=["agent", "retrieve", "grade", "generate", "rewrite"],
            mode="thinking",
        )

    @classmethod
    def fast_plan(cls) -> ExecutionPlan:
        """Fast mode: retrieve -> generate (no agent/grade/rewrite)."""
        return cls(
            plan_type=PlanType.FAST,
            skills=["retrieve", "generate"],
            mode="fast",
        )

    @classmethod
    def direct_plan(cls) -> ExecutionPlan:
        """Direct response (no retrieval, just LLM)."""
        return cls(
            plan_type=PlanType.DIRECT,
            skills=["agent"],
            mode="direct",
        )


class Planner:
    """
    Determines the execution plan for a query.

    Decision logic:
    1. If mode is explicitly "fast" -> fast plan
    2. If intent is general_chat -> direct plan
    3. Otherwise -> thinking plan (default)

    The planner is used by the orchestrator before building/executing
    the graph to decide which path to take.
    """

    def __init__(
        self,
        default_mode: str = "thinking",
        enable_fast_mode: bool = True,
    ):
        self._default_mode = default_mode
        self._enable_fast_mode = enable_fast_mode

    def plan(
        self,
        query: str = "",
        intent: Optional[str] = None,
        mode: Optional[str] = None,
        **kwargs,
    ) -> ExecutionPlan:
        """
        Determine the execution plan.

        Args:
            query: User's query (for future heuristics)
            intent: Intent classification result (e.g., 'rag_query', 'general_chat')
            mode: Explicit mode override ('thinking', 'fast', 'direct')

        Returns:
            ExecutionPlan describing the skill chain
        """
        # Explicit mode override
        if mode == "fast" and self._enable_fast_mode:
            log.info("Planner: fast mode (explicit)")
            return ExecutionPlan.fast_plan()

        if mode == "direct":
            log.info("Planner: direct mode (explicit)")
            return ExecutionPlan.direct_plan()

        # Intent-based routing
        if intent is not None:
            if intent == "general_chat":
                log.info("Planner: direct mode (general_chat intent)")
                return ExecutionPlan.direct_plan()

            if intent == "rag_query" and self._enable_fast_mode:
                # Check if the query suggests fast mode
                # (short, factual queries can use fast mode)
                # For now, use thinking mode as default for rag_query
                pass

        # Default to thinking mode
        if self._default_mode == "fast" and self._enable_fast_mode:
            log.info("Planner: fast mode (default)")
            return ExecutionPlan.fast_plan()

        log.info("Planner: thinking mode (default)")
        return ExecutionPlan.thinking_plan()

    def plan_from_context(
        self,
        context: Optional[Any] = None,
        **kwargs,
    ) -> ExecutionPlan:
        """
        Plan from a SkillContext or similar object.

        Extracts mode and intent metadata from context if available.
        """
        mode = kwargs.get("mode")

        intent = None
        if context is not None:
            # Try to get intent from context shared_state
            if hasattr(context, "shared_state"):
                intent = context.shared_state.get("intent")
            # Try to get mode from context
            if hasattr(context, "mode") and mode is None:
                mode = context.mode

        return self.plan(
            query=kwargs.get("query", ""),
            intent=intent,
            mode=mode,
        )
