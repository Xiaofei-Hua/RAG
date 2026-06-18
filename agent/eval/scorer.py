"""
Scorer for evaluation cases.

Combines legacy rule-based signals (section / keyword / intent / source
coverage) with trustworthy LLM-as-judge metrics. When the judge is
unavailable or produces no signal, the scorer degrades gracefully to
rule-based-only scoring so the eval run never hard-fails.
"""

from __future__ import annotations

import re
from typing import List, Optional

from agent.eval.judge import LLMJudge, TrustworthyMetrics
from agent.eval.types import EvalCase, EvalScore


class EvalScorer:
    """Score an (answer, contexts) pair against a case."""

    # Weights for the composite overall score.
    # Trustworthy metrics dominate when present; rule-based signals act as a
    # baseline floor so cases without a golden reference still produce a score.
    W_RULE = 0.3
    W_FAITH = 0.4
    W_REL = 0.15
    W_CONTEXT = 0.15

    def __init__(self, judge: Optional[LLMJudge] = None, use_judge: bool = True):
        self._judge = judge
        self._use_judge = use_judge

    @property
    def judge(self) -> Optional[LLMJudge]:
        if not self._use_judge:
            return None
        if self._judge is None:
            try:
                self._judge = LLMJudge()
            except Exception:  # noqa: BLE001 - judge must be optional
                self._judge = None
        return self._judge

    def score(
        self,
        case: EvalCase,
        actual_answer: str,
        actual_intent: str,
        actual_sources: int,
        retrieved_contexts: Optional[List[str]] = None,
    ) -> EvalScore:
        """
        Compute the full EvalScore for a case.

        Args:
            case: the golden case
            actual_answer: generated answer text
            actual_intent: detected intent label
            actual_sources: number of retrieved sources
            retrieved_contexts: list of retrieved context strings (for judge)
        """
        # --- rule-based signals (always computed) ---
        section_cov = self._section_coverage(case.expected_sections, actual_answer)
        keyword_cov = self._keyword_coverage(case.expected_keywords, actual_answer)
        intent_ok = self._intent_check(case.expected_intent, actual_intent)
        source_ok = self._source_check(case.expected_min_sources, actual_sources)

        score = EvalScore(
            section_coverage=section_cov,
            keyword_coverage=keyword_cov,
            intent_accuracy=intent_ok,
            source_count_ok=source_ok,
        )

        rule_component = (
            section_cov * 0.3
            + keyword_cov * 0.3
            + float(intent_ok) * 0.2
            + float(source_ok) * 0.2
        )

        # --- trustworthy metrics (best-effort) ---
        judge = self.judge
        if judge is not None and judge.available:
            contexts = retrieved_contexts or []
            metrics = judge.evaluate(
                question=case.query,
                answer=actual_answer,
                contexts=contexts,
                reference_answer=case.reference_answer,
            )
            score.faithfulness = metrics.faithfulness
            score.answer_relevancy = metrics.answer_relevancy
            score.hallucination_score = metrics.hallucination_score
            score.context_precision = metrics.context_precision
            score.context_recall = metrics.context_recall
            score.judge_used = metrics.judge_used
            score.details["judge_rationale"] = metrics.rationale

        # --- composite overall score ---
        score.overall_score = self._composite(rule_component, score)
        score.details.update(
            {
                "expected_sections": case.expected_sections,
                "expected_keywords": case.expected_keywords,
                "actual_intent": actual_intent,
                "actual_sources": actual_sources,
            }
        )
        return score

    def _composite(self, rule_component: float, score: EvalScore) -> float:
        """
        Blend rule-based and trustworthy signals into an overall score.

        When faithful/relevancy are available they dominate; otherwise the
        rule component carries the score so the run still produces a number.
        Hallucination pulls the score DOWN (it is a defect signal).
        """
        if score.judge_used and score.faithfulness is not None:
            faith = score.faithfulness
            rel = score.answer_relevancy if score.answer_relevancy is not None else rule_component
            # Context precision/recall averaged when present.
            context_terms = [t for t in (score.context_precision, score.context_recall) if t is not None]
            context = sum(context_terms) / len(context_terms) if context_terms else rule_component
            blended = (
                rule_component * self.W_RULE
                + faith * self.W_FAITH
                + rel * self.W_REL
                + context * self.W_CONTEXT
            )
            # Penalize hallucination.
            if score.hallucination_score is not None:
                blended *= (1.0 - 0.5 * score.hallucination_score)
            return max(0.0, min(1.0, blended))
        return max(0.0, min(1.0, rule_component))

    # -- rule-based helpers (legacy, preserved) ----------------------------

    def _section_coverage(self, expected: List[str], actual: str) -> float:
        if not expected:
            return 1.0
        found = 0
        for section in expected:
            if re.search(rf"【{re.escape(section)}】", actual):
                found += 1
            elif section in actual:
                found += 1
        return found / len(expected)

    def _keyword_coverage(self, expected: List[str], actual: str) -> float:
        if not expected:
            return 1.0
        found = sum(1 for kw in expected if kw in actual)
        return found / len(expected)

    def _intent_check(self, expected: str, actual: str) -> bool:
        return expected == actual

    def _source_check(self, expected_min: int, actual: int) -> bool:
        return actual >= expected_min
