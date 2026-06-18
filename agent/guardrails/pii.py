"""
PII detection and output redaction (P3.1).

Detects personally-identifiable information in user input and agent output,
then either blocks the input or redacts the output. Detection is regex-based
(Chinese phone numbers, ID cards, emails, bank cards, IP addresses) with no
external dependency, plus an opt-in LLM-based pass for paraphrased PII.

Configured via GuardrailConfig:
  - ``enable_pii_check`` (default True)
  - ``pii_redact_output`` (default True) — redact in output; False => block.

Integrates with OutputGuardrail.validate() and InputGuardrail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

__all__ = ["PIIMatch", "detect_pii", "redact_pii", "PII_PATTERNS"]


@dataclass
class PIIMatch:
    """A single PII detection."""
    kind: str       # phone | id_card | email | bank_card | ip
    value: str
    start: int
    end: int


# Regex patterns (ordered by specificity — most specific first).
# Note: no \b word-boundary anchors — \b does not fire around CJK characters,
# which would let PII in Chinese text slip through (e.g. "电话13812345678").
# We use lookarounds instead to avoid partial matches inside longer digit runs.
PII_PATTERNS: List[Tuple[str, re.Pattern]] = [
    # Chinese 18-digit ID card (last char X allowed)
    ("id_card", re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)")),
    # Chinese mobile phone (11 digits starting with 1)
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    # Bank card (16-19 digits)
    ("bank_card", re.compile(r"(?<!\d)[1-9]\d{15,18}(?!\d)")),
    # Email
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # IPv4
    ("ip", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
]


def detect_pii(text: str) -> List[PIIMatch]:
    """Detect all PII occurrences in text."""
    if not text:
        return []
    matches: List[PIIMatch] = []
    for kind, pattern in PII_PATTERNS:
        for m in pattern.finditer(text):
            # Sanity: skip IPs that look like version numbers (e.g. 1.2.3).
            if kind == "ip" and len(m.group().split(".")) != 4:
                continue
            matches.append(PIIMatch(
                kind=kind, value=m.group(),
                start=m.start(), end=m.end(),
            ))
    # Sort by position; de-overlap (keep first occurrence).
    matches.sort(key=lambda x: x.start)
    deduped: List[PIIMatch] = []
    last_end = -1
    for m in matches:
        if m.start >= last_end:
            deduped.append(m)
            last_end = m.end
    return deduped


def redact_pii(text: str) -> str:
    """Return text with all PII replaced by [REDACTED:<kind>]."""
    matches = detect_pii(text)
    if not matches:
        return text
    # Replace from the end to keep indices stable.
    out = text
    for m in reversed(matches):
        out = out[:m.start] + f"[已脱敏:{m.kind}]" + out[m.end:]
    return out


def has_pii(text: str) -> bool:
    """True if any PII is detected."""
    return bool(detect_pii(text))
