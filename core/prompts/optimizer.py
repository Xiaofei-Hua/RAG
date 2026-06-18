"""
Lightweight prompt optimization advisor (P3.3).

Analyses evaluation history to identify systematic prompt weaknesses and
suggest concrete improvements — without a heavyweight dependency like DSPy.

How it works: it reads recent eval runs, groups low-scoring cases by failure
mode (missing sections, missing keywords, low faithfulness, refusal), and
produces actionable suggestions (e.g. "8/15 cases missing 【排查步骤】 — add an
explicit instruction to always include troubleshooting steps").

This is advisory (suggests, doesn't auto-apply) so prompts change deliberately.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.log_utils import log

__all__ = ["PromptSuggestion", "analyse_prompt_weaknesses"]


class PromptSuggestion:
    """One actionable prompt-improvement suggestion."""

    def __init__(self, severity: str, category: str, message: str, evidence: str = ""):
        self.severity = severity  # high | medium | low
        self.category = category  # missing_section | missing_keyword | hallucination | refusal
        self.message = message
        self.evidence = evidence

    def to_dict(self) -> Dict[str, str]:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "evidence": self.evidence,
        }


def _load_recent_runs(runs_dir: str = "data/eval/runs", limit: int = 3) -> List[Dict]:
    """Load the N most recent eval-run detail JSONs."""
    p = Path(runs_dir)
    if not p.exists():
        return []
    files = sorted(p.glob("*.json"), reverse=True)[:limit]
    runs = []
    for f in files:
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return runs


def analyse_prompt_weaknesses(
    runs_dir: str = "data/eval/runs",
    score_threshold: float = 0.6,
    limit: int = 3,
) -> List[PromptSuggestion]:
    """
    Analyse recent eval runs and return prompt-improvement suggestions.

    Args:
        runs_dir: directory containing run detail JSONs.
        score_threshold: cases scoring below this are "weak".
        limit: number of recent runs to analyse.

    Returns a list of PromptSuggestion (highest severity first).
    """
    runs = _load_recent_runs(runs_dir, limit=limit)
    if not runs:
        return []

    weak_cases: List[Dict] = []
    for run in runs:
        for r in run.get("results", []):
            score = r.get("score", {})
            if score.get("overall_score", 1.0) < score_threshold:
                weak_cases.append(r)

    if not weak_cases:
        return [PromptSuggestion(
            severity="low", category="none",
            message="No systematic weaknesses detected in recent runs.",
        )]

    suggestions: List[PromptSuggestion] = []

    # 1. Missing sections analysis.
    section_fail = Counter()
    for c in weak_cases:
        expected = c.get("score", {}).get("details", {}).get("expected_sections", [])
        if expected and c["score"].get("section_coverage", 1.0) < 1.0:
            for s in expected:
                # Heuristic: if coverage < 1, at least one section missing.
                section_fail[s] += 1
    for section, count in section_fail.most_common(3):
        if count >= max(2, len(weak_cases) * 0.2):
            suggestions.append(PromptSuggestion(
                severity="high", category="missing_section",
                message=f"在 prompt 中显式要求始终包含【{section}】部分",
                evidence=f"{count}/{len(weak_cases)} 个低分用例缺失该部分",
            ))

    # 2. Hallucination analysis.
    halluc_cases = [
        c for c in weak_cases
        if c.get("score", {}).get("hallucination_score") is not None
        and c["score"]["hallucination_score"] > 0.3
    ]
    if len(halluc_cases) >= 2:
        suggestions.append(PromptSuggestion(
            severity="high", category="hallucination",
            message="加强 anti-hallucination 约束：要求只基于检索内容作答，无依据时不编造",
            evidence=f"{len(halluc_cases)}/{len(weak_cases)} 个低分用例存在幻觉",
        ))

    # 3. Low faithfulness trend.
    faith_vals = [
        c["score"]["faithfulness"] for c in weak_cases
        if c.get("score", {}).get("faithfulness") is not None
    ]
    if faith_vals and sum(faith_vals) / len(faith_vals) < 0.5:
        suggestions.append(PromptSuggestion(
            severity="medium", category="faithfulness",
            message="强调答案的每个声明必须可溯源到检索片段",
            evidence=f"平均 faithfulness={sum(faith_vals)/len(faith_vals):.2f}",
        ))

    # 4. Refusal rate.
    refusals = [c for c in weak_cases if c.get("error") and "refus" in str(c["error"]).lower()]
    if len(refusals) >= len(weak_cases) * 0.3:
        suggestions.append(PromptSuggestion(
            severity="medium", category="refusal",
            message="拒答率偏高，检查检索召回是否不足或 min_relevance 阈值是否过严",
            evidence=f"{len(refusals)}/{len(weak_cases)} 个用例被拒绝",
        ))

    severity_order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: severity_order.get(s.severity, 3))
    return suggestions
