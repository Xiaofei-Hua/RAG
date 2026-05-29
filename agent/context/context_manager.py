"""
Context Manager

Manages shared state across skill executions within a single agent run.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from dataclasses import dataclass, field

from utils.log_utils import log

__all__ = ["ContextManager"]


class ContextManager:
    """
    Manages shared mutable state across skill executions.

    Skills can read/write shared state via context.shared_state,
    which is backed by this manager.
    """

    def __init__(self):
        self._state: Dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._state[key] = value

    def update(self, data: Dict[str, Any]) -> None:
        self._state.update(data)

    def has(self, key: str) -> bool:
        return key in self._state

    def clear(self) -> None:
        self._state.clear()

    def snapshot(self) -> Dict[str, Any]:
        return dict(self._state)

    def restore(self, data: Dict[str, Any]) -> None:
        self._state = dict(data)
