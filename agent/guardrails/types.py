from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GuardrailAction(str, Enum):
    """Possible outcomes from a guardrail check."""

    ALLOW = "allow"
    BLOCK = "block"
    SANITIZE = "sanitize"
    ESCALATE = "escalate"


@dataclass
class GuardrailResult:
    """Result returned by every guardrail check."""

    action: GuardrailAction
    reason: str = ""
    sanitized_content: Optional[str] = None
    confidence: float = 1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class GuardrailConfig:
    """Configuration for the guardrail subsystem."""

    max_input_length: int = 2000
    enable_injection_detection: bool = True
    enable_topic_check: bool = True
    enable_safety_check: bool = True
    enable_hallucination_check: bool = True
    enable_structure_check: bool = True
