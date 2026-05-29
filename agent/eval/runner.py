from __future__ import annotations

import time
from typing import List, Optional

from agent.eval.scorer import EvalScorer
from agent.eval.types import EvalCase, EvalReport, EvalResult
from utils.log_utils import log


class EvalRunner:
    def __init__(self):
        self._scorer = EvalScorer()

    def run_case(self, case: EvalCase) -> EvalResult:
        start = time.perf_counter()
        try:
            from agent.harness.orchestrator import AgentHarness, HarnessConfig

            config = HarnessConfig(session_id=f"eval_{case.id}")
            harness = AgentHarness(config=config)

            result = harness.invoke(case.query)

            actual_answer = ""
            if result and result.messages:
                last_msg = result.messages[-1]
                actual_answer = getattr(last_msg, "content", str(last_msg))

            actual_intent = result.shared_state.get("detected_intent", "") if result else ""
            actual_sources = result.shared_state.get("source_count", 0) if result else 0

            score = self._scorer.score(case, actual_answer, actual_intent, actual_sources)

            elapsed_ms = (time.perf_counter() - start) * 1000
            return EvalResult(
                case_id=case.id,
                score=score,
                actual_answer=actual_answer,
                actual_intent=actual_intent,
                actual_sources=actual_sources,
                execution_time_ms=elapsed_ms,
            )
        except Exception as e:
            log.error(f"EvalRunner: case {case.id} failed: {e}")
            return EvalResult(
                case_id=case.id,
                execution_time_ms=(time.perf_counter() - start) * 1000,
                error=str(e),
            )

    def run_all(self, cases: Optional[List[EvalCase]] = None) -> EvalReport:
        if cases is None:
            from agent.eval.cases import get_default_eval_cases
            cases = get_default_eval_cases()

        results: List[EvalResult] = []
        for case in cases:
            log.info(f"EvalRunner: running case {case.id} - {case.query[:30]}...")
            result = self.run_case(case)
            results.append(result)

        total = len(results)
        passed = sum(1 for r in results if r.score.overall_score >= 0.6 and r.error is None)
        failed = total - passed
        avg_score = (
            sum(r.score.overall_score for r in results) / total if total > 0 else 0.0
        )

        report = EvalReport(
            total_cases=total,
            passed=passed,
            failed=failed,
            average_score=avg_score,
            results=results,
        )

        log.info(
            f"EvalRunner: completed {total} cases, {passed} passed, {failed} failed, avg={avg_score:.2f}"
        )
        return report
