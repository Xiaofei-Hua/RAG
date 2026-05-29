"""
Lifecycle Hooks

Provides before_skill, after_skill, and on_error hooks that the
orchestrator calls around each skill execution.

Hooks are callables that receive (skill_name, context, result) and
can perform logging, tracing, metrics, or state manipulation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from agent.skills.base import SkillContext, SkillResult
from utils.log_utils import log

__all__ = [
    "LifecycleHook",
    "HookType",
    "LifecycleManager",
]


class HookType:
    """Hook type constants."""
    BEFORE_SKILL = "before_skill"
    AFTER_SKILL = "after_skill"
    ON_ERROR = "on_error"


@dataclass
class LifecycleHook:
    """
    A registered lifecycle hook.

    Attributes:
        name: Human-readable name for the hook
        hook_type: One of 'before_skill', 'after_skill', 'on_error'
        callback: Callable to invoke
        priority: Lower values run first (default 100)
    """
    name: str
    hook_type: str
    callback: Callable
    priority: int = 100


class LifecycleManager:
    """
    Manages lifecycle hooks for the agent harness.

    Supports three hook points:
    - before_skill: Called before a skill executes
    - after_skill: Called after a skill succeeds
    - on_error: Called when a skill fails

    Example:
        >>> lm = LifecycleManager()
        >>> lm.on_before_skill(logging_hook)
        >>> lm.on_after_skill(metrics_hook)
        >>> lm.on_error(error_handler)
    """

    def __init__(self):
        self._hooks: Dict[str, List[LifecycleHook]] = {
            HookType.BEFORE_SKILL: [],
            HookType.AFTER_SKILL: [],
            HookType.ON_ERROR: [],
        }

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on_before_skill(
        self,
        callback: Callable,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """
        Register a hook to run before a skill executes.

        Callback signature: (skill_name: str, context: SkillContext) -> None
        """
        self._hooks[HookType.BEFORE_SKILL].append(
            LifecycleHook(
                name=name or callback.__name__,
                hook_type=HookType.BEFORE_SKILL,
                callback=callback,
                priority=priority,
            )
        )
        self._hooks[HookType.BEFORE_SKILL].sort(key=lambda h: h.priority)

    def on_after_skill(
        self,
        callback: Callable,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """
        Register a hook to run after a skill executes successfully.

        Callback signature:
            (skill_name: str, context: SkillContext, result: SkillResult) -> None
        """
        self._hooks[HookType.AFTER_SKILL].append(
            LifecycleHook(
                name=name or callback.__name__,
                hook_type=HookType.AFTER_SKILL,
                callback=callback,
                priority=priority,
            )
        )
        self._hooks[HookType.AFTER_SKILL].sort(key=lambda h: h.priority)

    def on_error(
        self,
        callback: Callable,
        name: str = "",
        priority: int = 100,
    ) -> None:
        """
        Register a hook to run when a skill fails.

        Callback signature:
            (skill_name: str, context: SkillContext, error: Exception) -> None
        """
        self._hooks[HookType.ON_ERROR].append(
            LifecycleHook(
                name=name or callback.__name__,
                hook_type=HookType.ON_ERROR,
                callback=callback,
                priority=priority,
            )
        )
        self._hooks[HookType.ON_ERROR].sort(key=lambda h: h.priority)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def fire_before_skill(
        self,
        skill_name: str,
        context: SkillContext,
    ) -> None:
        """Fire all before_skill hooks."""
        for hook in self._hooks[HookType.BEFORE_SKILL]:
            try:
                hook.callback(skill_name, context)
            except Exception as e:
                log.warning(f"Before-skill hook '{hook.name}' failed: {e}")

    def fire_after_skill(
        self,
        skill_name: str,
        context: SkillContext,
        result: SkillResult,
    ) -> None:
        """Fire all after_skill hooks."""
        for hook in self._hooks[HookType.AFTER_SKILL]:
            try:
                hook.callback(skill_name, context, result)
            except Exception as e:
                log.warning(f"After-skill hook '{hook.name}' failed: {e}")

    def fire_on_error(
        self,
        skill_name: str,
        context: SkillContext,
        error: Exception,
    ) -> None:
        """Fire all on_error hooks."""
        for hook in self._hooks[HookType.ON_ERROR]:
            try:
                hook.callback(skill_name, context, error)
            except Exception as e:
                log.warning(f"Error hook '{hook.name}' failed: {e}")

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all hooks."""
        for hook_type in self._hooks:
            self._hooks[hook_type].clear()

    def list_hooks(self) -> Dict[str, List[str]]:
        """List all registered hook names by type."""
        return {
            hook_type: [h.name for h in hooks]
            for hook_type, hooks in self._hooks.items()
        }
