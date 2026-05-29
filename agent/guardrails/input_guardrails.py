from __future__ import annotations

import re
from typing import Optional

from agent.guardrails.prompts import INJECTION_PATTERNS
from agent.guardrails.types import GuardrailAction, GuardrailConfig, GuardrailResult
from utils.log_utils import log

# ---------------------------------------------------------------------------
# PHM / aviation topic keywords (Chinese + English)
# ---------------------------------------------------------------------------
_TOPIC_KEYWORDS: set[str] = {
    # English
    "fault", "engine", "hydraulic", "avionics", "vibration",
    "ATA", "maintenance", "troubleshoot", "diagnosis", "diagnostic",
    "sensor", "bearing", "turbine", "compressor", "blade",
    "oil", "fuel", "bleed", "landing gear", "apu",
    # Chinese
    "故障", "发动机", "液压", "航电", "振动",
    "维修", "排故", "诊断", "传感器", "轴承",
    "涡轮", "压气机", "叶片", "滑油", "燃油",
    "起落架", "辅助动力装置",
}


class InputGuardrail:
    """Validates incoming user messages before they reach the agent."""

    def __init__(self, config: Optional[GuardrailConfig] = None):
        self._config = config or GuardrailConfig()

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_length(self, message: str) -> GuardrailResult:
        """BLOCK messages that exceed the configured length limit."""
        if len(message) > self._config.max_input_length:
            log.warning(
                f"InputGuardrail: message length {len(message)} exceeds "
                f"limit {self._config.max_input_length}"
            )
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason=f"输入长度({len(message)})超过限制({self._config.max_input_length})",
                confidence=1.0,
            )
        return GuardrailResult(action=GuardrailAction.ALLOW)

    def _check_injection(self, message: str) -> GuardrailResult:
        """BLOCK messages matching known prompt-injection patterns."""
        if not self._config.enable_injection_detection:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        for pattern in INJECTION_PATTERNS:
            match = pattern.search(message)
            if match:
                log.warning(f"InputGuardrail: injection pattern detected: {match.group()!r}")
                return GuardrailResult(
                    action=GuardrailAction.BLOCK,
                    reason=f"检测到潜在注入攻击: {match.group()!r}",
                    confidence=0.9,
                    metadata={"pattern": pattern.pattern},
                )
        return GuardrailResult(action=GuardrailAction.ALLOW)

    def _check_topic(self, message: str) -> GuardrailResult:
        """
        Validate that the message is at least loosely related to the
        PHM / aviation domain.  Ambiguous messages are ALLOWed; only
        clearly manipulative off-topic prompts are BLOCKed.
        """
        if not self._config.enable_topic_check:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        lower = message.lower()

        # Check for topic overlap
        keyword_hits = sum(1 for kw in _TOPIC_KEYWORDS if kw.lower() in lower)

        if keyword_hits > 0:
            return GuardrailResult(action=GuardrailAction.ALLOW)

        # If the message also triggered injection patterns earlier it will
        # already be BLOCKed.  Here we only block clearly off-topic messages
        # that are also short and look like an attempt to redirect the system.
        # Ambiguous / casual questions are allowed through.
        manipulation_markers = {"hack", "exploit", "bypass", "绕过", "破解"}
        if any(m in lower for m in manipulation_markers):
            log.warning(f"InputGuardrail: off-topic with manipulation marker detected")
            return GuardrailResult(
                action=GuardrailAction.BLOCK,
                reason="话题超出系统范围且含有操控意图",
                confidence=0.7,
            )

        # Default: allow -- the safety / injection checks are the hard gate.
        return GuardrailResult(action=GuardrailAction.ALLOW)

    # ------------------------------------------------------------------
    # Orchestrator
    # ------------------------------------------------------------------

    def validate(self, message: str) -> GuardrailResult:
        """Run all input checks in sequence; return the most restrictive result."""
        checks = [
            self._check_length(message),
            self._check_injection(message),
            self._check_topic(message),
        ]

        # If any check returns BLOCK, surface that immediately.
        for result in checks:
            if result.action == GuardrailAction.BLOCK:
                log.info(f"InputGuardrail: blocked input - {result.reason}")
                return result

        return GuardrailResult(action=GuardrailAction.ALLOW)
