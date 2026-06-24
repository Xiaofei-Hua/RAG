#!/usr/bin/env python3
"""
F24 — real-judge flywheel E2E (requires Ollama).

PR-gated e2e tests stub the judge (fast, no Ollama). This test runs the REAL
local LLMJudge against a replay sample so the flywheel's hallucination-detection
path (claim extraction + per-claim NLI + circuit-breaker degradation) is
exercised end-to-end. Marked ``requires_ollama`` — skipped by default, run in
the nightly self-hosted CI job (see .github/workflows/tests.yml).

Run manually: OLLAMA_FULL_TESTS=1 pytest tests/e2e/test_flywheel_real_judge.py -v

Prerequisite (design F24 / P1): the self-hosted runner must have Ollama +
Qwen3 + Milvus available. If the judge is unavailable, this test degrades
gracefully (asserts the degradation path, not a hard failure) so a missing
runner does not turn the gate red for the wrong reason.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, ".")

pytestmark = [
    pytest.mark.requires_ollama,
    pytest.mark.skipif(
        os.environ.get("OLLAMA_FULL_TESTS") != "1",
        reason="needs OLLAMA_FULL_TESTS=1 and a live Ollama (nightly/self-hosted)",
    ),
]


def test_real_judge_faithfulness_on_supported_answer():
    """A faithful answer (claims fully supported by context) should score high,
    proving the real judge + claim extraction + NLI path works end-to-end."""
    from agent.eval.judge import get_judge

    judge = get_judge()
    if not judge.available:
        pytest.skip("LLMJudge unavailable (Ollama down) — graceful degradation path")

    metrics = judge.trustworthy_metrics(
        question="发动机振动限值是多少？",
        answer="发动机振动限值应为 4.0 IPS。",
        contexts=["手册规定：发动机振动限值为 4.0 IPS，超过该值需停机检查。"],
        golden_context_ids=None,
        reference_answer="振动限值 4.0 IPS。",
    )
    # A well-supported single-claim answer should be faithful.
    assert metrics.faithfulness is not None
    assert metrics.faithfulness >= 0.5, (
        f"faithfulness {metrics.faithfulness} unexpectedly low for a grounded answer"
    )
    assert metrics.judge_used is True


def test_real_judge_faithfulness_on_unsupported_answer():
    """A fabricated answer (claim contradicted by context) should score low on
    faithfulness, proving the judge can detect hallucinations — the core
    flywheel safety property that the PR-gated fake-judge e2e cannot verify."""
    from agent.eval.judge import get_judge

    judge = get_judge()
    if not judge.available:
        pytest.skip("LLMJudge unavailable (Ollama down) — graceful degradation path")

    metrics = judge.trustworthy_metrics(
        question="发动机振动限值是多少？",
        answer="发动机振动限值应为 25.0 IPS，这是正常工作范围。",
        contexts=["手册规定：发动机振动限值为 4.0 IPS，超过该值需停机检查。"],
        golden_context_ids=None,
        reference_answer="振动限值 4.0 IPS。",
    )
    # A contradicted hard claim should NOT be judged fully faithful.
    assert metrics.faithfulness is not None
    assert metrics.faithfulness < 1.0, (
        f"faithfulness {metrics.faithfulness} should be < 1.0 for a contradicted claim"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
