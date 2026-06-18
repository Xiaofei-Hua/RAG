"""
Evaluation types for the agent evaluation flywheel.

Extends the legacy rule-based scoring model with trustworthy metrics
(faithfulness / answer relevancy / hallucination / context precision) backed
by a local LLM-as-judge, plus golden-answer support and run-history for
regression comparison.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# =============================================================================
# Dataset types
# =============================================================================

@dataclass
class EvalCase:
    """
    A single evaluation case.

    Rule-based fields (expected_sections / expected_keywords) are retained for
    backward compatibility. Trustworthy metrics additionally rely on:
      - reference_answer: golden answer used by faithfulness / relevancy
      - expected_context_ids: ids of chunks that SHOULD be retrieved (for
        context precision / recall when known)
    """
    id: str = ""
    query: str = ""
    # Rule-based expectations (legacy)
    expected_sections: List[str] = field(default_factory=list)
    expected_keywords: List[str] = field(default_factory=list)
    expected_intent: str = "rag_query"
    expected_min_sources: int = 0
    difficulty: str = "medium"
    # Trustworthy / golden fields
    reference_answer: str = ""
    expected_context_ids: List[str] = field(default_factory=list)
    # Metadata
    tags: List[str] = field(default_factory=list)
    source: str = "seed"          # seed | feedback | correction | curated


@dataclass
class EvalScore:
    """
    Scores for a single case.

    `section_coverage` / `keyword_coverage` are legacy rule-based signals.
    The judge_* fields are populated by the local LLM-as-judge when available.
    """
    # Legacy rule-based
    section_coverage: float = 0.0
    keyword_coverage: float = 0.0
    intent_accuracy: bool = False
    source_count_ok: bool = False
    # Trustworthy metrics (0.0-1.0, or None when not computed)
    faithfulness: Optional[float] = None
    answer_relevancy: Optional[float] = None
    hallucination_score: Optional[float] = None      # 0.0 = no hallucination, 1.0 = fully unsupported
    context_precision: Optional[float] = None
    context_recall: Optional[float] = None
    # Aggregates
    overall_score: float = 0.0
    # Whether the trustworthy metrics were computed via judge (vs degraded to rules)
    judge_used: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of running a single case, including retrieved artifacts."""
    case_id: str = ""
    score: EvalScore = field(default_factory=EvalScore)
    actual_answer: str = ""
    actual_intent: str = ""
    actual_sources: int = 0
    retrieved_contexts: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class EvalReport:
    """Aggregate report for a single eval run (in-memory)."""
    timestamp: float = field(default_factory=time.time)
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    average_score: float = 0.0
    # Per-metric averages (None when not computed)
    avg_faithfulness: Optional[float] = None
    avg_answer_relevancy: Optional[float] = None
    avg_hallucination: Optional[float] = None
    avg_context_precision: Optional[float] = None
    avg_context_recall: Optional[float] = None
    results: List[EvalResult] = field(default_factory=list)


# =============================================================================
# Run-history / regression types
# =============================================================================

@dataclass
class EvalRunSummary:
    """
    Serializable summary of one eval run, persisted to disk for trend /
    regression analysis. Mirrors the aggregate fields of EvalReport plus
    provenance metadata.
    """
    run_id: str = ""
    timestamp: float = field(default_factory=time.time)
    git_commit: str = ""
    tag: str = ""                  # ci | manual | nightly | ...
    dataset: str = ""              # dataset path / name
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    average_score: float = 0.0
    avg_faithfulness: Optional[float] = None
    avg_answer_relevancy: Optional[float] = None
    avg_hallucination: Optional[float] = None
    avg_context_precision: Optional[float] = None
    avg_context_recall: Optional[float] = None
    judge_used: bool = False
    # Filesystem path to the full per-case detail JSON (same run_id)
    detail_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "git_commit": self.git_commit,
            "tag": self.tag,
            "dataset": self.dataset,
            "total_cases": self.total_cases,
            "passed": self.passed,
            "failed": self.failed,
            "average_score": self.average_score,
            "avg_faithfulness": self.avg_faithfulness,
            "avg_answer_relevancy": self.avg_answer_relevancy,
            "avg_hallucination": self.avg_hallucination,
            "avg_context_precision": self.avg_context_precision,
            "avg_context_recall": self.avg_context_recall,
            "judge_used": self.judge_used,
            "detail_path": self.detail_path,
        }


@dataclass
class MetricDelta:
    """Change in a single metric between two runs."""
    metric: str = ""
    baseline: Optional[float] = None
    current: Optional[float] = None
    delta: Optional[float] = None       # current - baseline (positive = improvement for "higher is better")
    regressed: bool = False


@dataclass
class RegressionReport:
    """Difference between a baseline run and the current run."""
    baseline_run_id: str = ""
    current_run_id: str = ""
    deltas: List[MetricDelta] = field(default_factory=list)
    # Metrics where current regressed beyond their threshold
    regressions: List[MetricDelta] = field(default_factory=list)
    passed: bool = True                 # True if no metric regressed beyond threshold
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "baseline_run_id": self.baseline_run_id,
            "current_run_id": self.current_run_id,
            "deltas": [
                {
                    "metric": d.metric,
                    "baseline": d.baseline,
                    "current": d.current,
                    "delta": d.delta,
                    "regressed": d.regressed,
                }
                for d in self.deltas
            ],
            "regressions": [d.metric for d in self.regressions],
            "passed": self.passed,
            "summary": self.summary,
        }
