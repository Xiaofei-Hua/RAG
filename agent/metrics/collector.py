"""
Metrics Collector

Central collector for token usage, costs, quality signals, and timing.
Tracks both per-run and cumulative statistics.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from agent.metrics.types import (
    CostRecord,
    QualitySignal,
    RunMetrics,
    TokenUsage,
)
from utils.log_utils import log

__all__ = ["MetricsCollector", "get_metrics_collector"]


class MetricsCollector:
    """
    Collects and aggregates metrics across skill executions.

    Tracks:
    - Per-skill token usage and costs
    - Quality signals from skill results
    - Per-skill execution durations
    - Cumulative statistics across all runs
    """

    def __init__(self) -> None:
        # Per-run counters
        self._run_tokens: int = 0
        self._run_cost: float = 0.0
        self._run_quality_signals: List[QualitySignal] = []
        self._run_skill_durations: Dict[str, float] = {}

        # Cumulative counters
        self._total_runs: int = 0
        self._cumulative_tokens: int = 0
        self._cumulative_cost: float = 0.0
        self._cumulative_durations: Dict[str, List[float]] = {}

        # Full history
        self._cost_records: List[CostRecord] = []

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_token_usage(self, skill_name: str, usage: TokenUsage) -> None:
        """
        Record token usage for a skill. Accumulates into run totals.

        Args:
            skill_name: Name of the skill that consumed tokens.
            usage: TokenUsage with prompt/completion/total counts.
        """
        self._run_tokens += usage.total_tokens
        log.debug(
            f"Metrics: {skill_name} used {usage.total_tokens} tokens "
            f"(prompt={usage.prompt_tokens}, completion={usage.completion_tokens})"
        )

    def record_cost(self, record: CostRecord) -> None:
        """
        Store a cost record. Accumulates into run totals.

        Args:
            record: CostRecord with skill name, token usage, and cost.
        """
        self._run_cost += record.estimated_cost_usd
        self._cost_records.append(record)
        log.debug(
            f"Metrics: {record.skill_name} cost ${record.estimated_cost_usd:.6f}"
        )

    def record_quality(self, signal: QualitySignal) -> None:
        """
        Append a quality signal to the current run.

        Args:
            signal: QualitySignal with skill name, type, and value.
        """
        self._run_quality_signals.append(signal)
        log.debug(
            f"Metrics: {signal.skill_name} quality signal "
            f"{signal.signal_type}={signal.value}"
        )

    def record_duration(self, skill_name: str, duration_ms: float) -> None:
        """
        Store per-skill execution timing for the current run.

        Args:
            skill_name: Name of the skill.
            duration_ms: Execution duration in milliseconds.
        """
        self._run_skill_durations[skill_name] = duration_ms
        log.debug(f"Metrics: {skill_name} took {duration_ms:.1f}ms")

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def get_run_metrics(self) -> RunMetrics:
        """
        Aggregate current run data into a RunMetrics snapshot.

        Returns:
            RunMetrics with totals for the current run.
        """
        return RunMetrics(
            total_tokens=self._run_tokens,
            total_cost_usd=self._run_cost,
            quality_signals=list(self._run_quality_signals),
            skill_durations=dict(self._run_skill_durations),
        )

    def reset_run(self) -> None:
        """
        Clear per-run counters and fold into cumulative stats.
        """
        # Fold run data into cumulative counters
        self._total_runs += 1
        self._cumulative_tokens += self._run_tokens
        self._cumulative_cost += self._run_cost

        for skill_name, duration in self._run_skill_durations.items():
            if skill_name not in self._cumulative_durations:
                self._cumulative_durations[skill_name] = []
            self._cumulative_durations[skill_name].append(duration)

        # Reset per-run state
        self._run_tokens = 0
        self._run_cost = 0.0
        self._run_quality_signals.clear()
        self._run_skill_durations.clear()

    def get_cumulative_stats(self) -> Dict:
        """
        Return totals across all completed runs.

        Returns:
            Dict with total_runs, total_tokens, total_cost_usd,
            avg_latency_per_skill, and total_cost_records.
        """
        avg_latencies: Dict[str, float] = {}
        for skill_name, durations in self._cumulative_durations.items():
            if durations:
                avg_latencies[skill_name] = sum(durations) / len(durations)

        return {
            "total_runs": self._total_runs,
            "total_tokens": self._cumulative_tokens,
            "total_cost_usd": self._cumulative_cost,
            "avg_latency_per_skill": avg_latencies,
            "total_cost_records": len(self._cost_records),
        }


# ----------------------------------------------------------------------
# Module-level singleton
# ----------------------------------------------------------------------

_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """
    Get or create the global MetricsCollector singleton.

    Returns:
        The shared MetricsCollector instance.
    """
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
