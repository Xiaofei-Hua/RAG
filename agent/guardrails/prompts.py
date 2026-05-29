from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Safety disclaimer appended to PHM/aviation answers
# ---------------------------------------------------------------------------
SAFETY_DISCLAIMER = (
    "\n\n---\n"
    "⚠️ 本回答由AI系统生成，仅供参考，不能替代专业维修人员的判断。"
    "实际维修操作请以制造商技术手册为准。"
)

# ---------------------------------------------------------------------------
# Compiled regex patterns for prompt-injection detection
# ---------------------------------------------------------------------------
INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions|rules|prompts)", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"\bDAN\b"),
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"```\s*(system|assistant|user)\s*:", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+a", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+(are|were)\s+)?a", re.IGNORECASE),
    re.compile(r"override\s+(your|the)\s+(instructions|rules|guidelines)", re.IGNORECASE),
    re.compile(r"reveal\s+(your|the)\s+(system|hidden|internal)\s+(prompt|instructions|rules)", re.IGNORECASE),
]
