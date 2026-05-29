from __future__ import annotations

import re
from typing import List, Optional

from agent.guardrails.prompts import SAFETY_DISCLAIMER
from agent.guardrails.types import GuardrailAction, GuardrailConfig, GuardrailResult
from utils.log_utils import log


class OutputGuardrail:
    """Validates and post-processes agent responses before they reach the user."""

    def __init__(self, config: Optional[GuardrailConfig] = None):
        self._config = config or GuardrailConfig()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_safety_disclaimer(self, answer: str) -> GuardrailResult:
        """Ensure the answer carries a safety disclaimer when appropriate."""
        if not self._config.enable_safety_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # If the answer already mentions risk or a safety note, it is fine.
        if "风险" in answer or "安全提示" in answer or "仅供参考" in answer:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Append the disclaimer via SANITIZE.
        return GuardrailResult(
            action=GuardrailAction.SANITIZE,
            reason="缺少安全免责声明",
            sanitized_content=answer + SAFETY_DISCLAIMER,
            confidence=1.0,
        )

    def _check_structure(self, answer: str) -> GuardrailResult:
        """
        Check that substantive answers (> 50 chars) follow the expected
        PHM structured format (diagnosis conclusion / troubleshooting steps).
        """
        if not self._config.enable_structure_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        if len(answer) <= 50:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        has_conclusion = "诊断结论" in answer or "排查步骤" in answer or "分析结论" in answer

        if has_conclusion:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Short / unstructured answer -- append a quality note.
        quality_note = (
            "\n\n> 💡 提示: 本回答未包含结构化诊断结论，如需详细排查步骤请进一步描述故障现象。"
        )
        return GuardrailResult(
            action=GuardrailAction.SANITIZE,
            reason="回答缺少结构化诊断内容",
            sanitized_content=answer + quality_note,
            confidence=0.8,
        )

    def _check_hallucination(
        self, answer: str, sources: Optional[List[str]] = None
    ) -> GuardrailResult:
        """
        Compare cited sources in the answer against the actual retrieval
        sources.  If the answer cites something not grounded in the sources,
        flag it for escalation.
        """
        if not self._config.enable_hallucination_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # If no sources provided, we cannot verify -- allow through.
        if not sources:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Extract the "依据来源" / "参考" / "引用" section from the answer.
        source_section = ""
        for marker in ("依据来源", "参考来源", "参考资料", "引用"):
            idx = answer.find(marker)
            if idx != -1:
                source_section = answer[idx:]
                break

        if not source_section:
            # No source section at all -- not a hallucination concern.
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # Check whether any source mentioned in the answer is NOT in the
        # actual sources list.  We do a loose substring check.
        mismatched = []
        # Extract potential source references (e.g. document names / IDs).
        # Simple heuristic: look for quoted strings or bracketed references.
        cited_refs = re.findall(r"[《\[](.*?)[》\]]", source_section)
        if not cited_refs:
            cited_refs = re.findall(r"来源[：:]\s*(.+?)(?:\n|$)", source_section)

        for cited in cited_refs:
            cited_lower = cited.strip().lower()
            if not any(cited_lower in src.lower() or src.lower() in cited_lower for src in sources):
                mismatched.append(cited)

        if mismatched:
            log.warning(f"OutputGuardrail: potential hallucination - mismatched sources: {mismatched}")
            return GuardrailResult(
                action=GuardrailAction.ESCALATE,
                reason=f"回答引用了不存在的来源: {mismatched}",
                confidence=0.7,
                metadata={"mismatched_sources": mismatched},
            )

        return GuardrailResult(action=GuardrailAction.ALLOW)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def validate(
        self, answer: str, sources: Optional[List[str]] = None
    ) -> GuardrailResult:
        """Run all output checks in sequence; return the most restrictive result."""
        # Priority order: BLOCK > ESCALATE > SANITIZE > ALLOW
        worst = GuardrailResult(action=GuardrailAction.ALLOW)

        # 1. Hallucination check (can produce ESCALATE)
        result = self._check_hallucination(answer, sources)
        if result.action == GuardrailAction.ESCALATE:
            worst = result
        elif result.action.value > worst.action.value:
            worst = result

        # 2. Safety disclaimer (can produce SANITIZE)
        result = self._check_safety_disclaimer(answer)
        if result.action == GuardrailAction.SANITIZE and worst.action == GuardrailAction.ALLOW:
            worst = result
            answer = result.sanitized_content or answer  # use sanitized for subsequent checks

        # 3. Structure check (can produce SANITIZE -- use potentially sanitized content)
        result = self._check_structure(answer)
        if result.action == GuardrailAction.SANITIZE and worst.action == GuardrailAction.ALLOW:
            worst = result

        if worst.action != GuardrailAction.ALLOW:
            log.info(f"OutputGuardrail: {worst.action.value} - {worst.reason}")

        return worst
