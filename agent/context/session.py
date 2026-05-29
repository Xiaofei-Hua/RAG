"""
Session Context

Encapsulates session-level metadata for an agent run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

__all__ = ["SessionContext"]


@dataclass
class SessionContext:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    mode: str = "thinking"
    user_id: Optional[str] = None
    prompt_profile: str = "phm_diagnosis_v1"
