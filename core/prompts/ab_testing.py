"""
Prompt A/B testing framework (P3.2).

Splits traffic between two or more prompt variants for the same profile, logs
which variant produced each answer, and computes quality metrics per variant
from the eval flywheel's inference store. This enables data-driven prompt
selection without guesswork.

Variant assignment is deterministic per session (hash of session_id) so a user
sees consistent variant within a session.

Configured via env:
  - ``PROMPT_AB_VARIANTS`` = JSON like {"phm_diagnosis_v1": ["v1", "v2"]}
  - ``PROMPT_AB_RATIO`` = traffic split (default 0.5)

Variant prompts are loaded from ``core/prompts/variants/<profile>_<variant>.py``.
"""

from __future__ import annotations

import hashlib
import json
import os

from utils.log_utils import log

__all__ = ["assign_variant", "record_variant", "variant_stats"]


def _parse_variants() -> dict[str, list[str]]:
    """Parse PROMPT_AB_VARIANTS env into {profile: [variant_ids]}."""
    raw = os.getenv("PROMPT_AB_VARIANTS", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {k: list(v) for k, v in data.items() if isinstance(v, list)}
    except json.JSONDecodeError:
        log.warning(f"Invalid PROMPT_AB_VARIANTS JSON: {raw!r}")
    return {}


def _ratio() -> float:
    try:
        return float(os.getenv("PROMPT_AB_RATIO", "0.5"))
    except (TypeError, ValueError):
        return 0.5


def assign_variant(profile: str, session_id: str) -> str:
    """
    Deterministically assign an A/B variant for a session.

    Returns the variant id (e.g. "v1", "v2"). When no variants are configured
    for the profile, returns "default".
    """
    variants = _parse_variants().get(profile)
    if not variants or len(variants) < 2:
        return "default"

    # Deterministic hash-based assignment.
    h = int(hashlib.sha1(f"{profile}:{session_id}".encode()).hexdigest(), 16)
    ratio = _ratio()
    # variant[0] gets `ratio` of traffic, the rest split evenly.
    bucket = (h % 1000) / 1000.0
    if bucket < ratio:
        return variants[0]
    return variants[
        min(int((bucket - ratio) / ((1 - ratio) / (len(variants) - 1))) + 1, len(variants) - 1)
    ]


# In-memory log of variant assignments (small; for stats + testability).
_assignment_log: list[dict] = []


def record_variant(profile: str, session_id: str, variant: str, trace_id: str = "") -> None:
    """Record which variant was used for an answer (for later quality analysis)."""
    _assignment_log.append(
        {
            "profile": profile,
            "session_id": session_id,
            "variant": variant,
            "trace_id": trace_id,
        }
    )
    if len(_assignment_log) > 10000:
        del _assignment_log[:5000]  # cap memory


def variant_stats(profile: str | None = None) -> dict[str, dict[str, int]]:
    """
    Aggregate variant assignment counts.

    Returns {variant: {"count": N}} optionally filtered by profile.
    """
    counts: dict[str, dict[str, int]] = {}
    for rec in _assignment_log:
        if profile and rec["profile"] != profile:
            continue
        v = rec["variant"]
        counts.setdefault(v, {"count": 0})
        counts[v]["count"] += 1
    return counts


def reset_assignment_log() -> None:
    """Clear the log (tests)."""
    _assignment_log.clear()
