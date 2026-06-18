"""
Request cancellation helpers (P3.4).

The streaming / async chat paths previously ignored client disconnects, leaving
upstream LLM calls running after the client gave up. This module provides a
cancellation-aware wrapper that:
  - detects ``asyncio.CancelledError`` (client disconnect / timeout),
  - cancels the wrapped task cleanly,
  - logs the cancellation for observability.

Used by the chat router to wrap harness.ainvoke / streaming generation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional, TypeVar

from utils.log_utils import log

__all__ = ["cancellable", "CancelledTaskError"]

T = TypeVar("T")


class CancelledTaskError(Exception):
    """Raised when a task is cancelled (client disconnect / timeout)."""


async def cancellable(
    coro: Awaitable[T],
    task_name: str = "task",
    on_cancel: Optional[Callable[[], None]] = None,
) -> T:
    """
    Await ``coro`` but propagate cancellation cleanly.

    On ``asyncio.CancelledError`` (client disconnect), runs ``on_cancel`` (if
    provided) and re-raises so the caller can return a partial / 499 response.
    """
    try:
        return await coro
    except asyncio.CancelledError:
        log.info(f"Task '{task_name}' cancelled (client disconnect)")
        if on_cancel:
            try:
                on_cancel()
            except Exception as e:  # noqa: BLE001
                log.debug(f"on_cancel callback failed: {e}")
        raise
