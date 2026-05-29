from __future__ import annotations

import re
from typing import List

from agent.eval.types import EvalCase, EvalScore


class EvalScorer:
    def score(
        self,
        case: EvalCase,
        actual_answer: str,
        actual_intent: str,
        actual_sources: int,
    ) -> EvalScore:
        section_cov = self._section_coverage(case.expected_sections, actual_answer)
        keyword_cov = self._keyword_coverage(case.expected_keywords, actual_answer)
        intent_ok = self._intent_check(case.expected_intent, actual_intent)
        source_ok = self._source_check(case.expected_min_sources, actual_sources)

        overall = (
            section_cov * 0.3
            + keyword_cov * 0.3
            + float(intent_ok) * 0.2
            + float(source_ok) * 0.2
        )

        return EvalScore(
            section_coverage=section_cov,
            keyword_coverage=keyword_cov,
            intent_accuracy=intent_ok,
            source_count_ok=source_ok,
            overall_score=overall,
            details={
                "expected_sections": case.expected_sections,
                "expected_keywords": case.expected_keywords,
                "actual_intent": actual_intent,
                "actual_sources": actual_sources,
            },
        )

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
