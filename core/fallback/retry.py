"""
Retry Policy for Enterprise RAG Platform

Provides retry logic with exponential backoff for transient failures.
"""

from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple, TypeVar, Union

from utils.log_utils import log

__all__ = [
    "RetryPolicy",
    "retry_with_backoff",
]

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """
    Retry policy configuration.

    Attributes:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        exponential_base: Base for exponential backoff
        jitter: Add random jitter to prevent thundering herd
        retryable_exceptions: Exception types that trigger retry
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: Tuple[type, ...] = (
        ConnectionError,
        TimeoutError,
    )

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        import random

        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )

        if self.jitter:
            # Add up to 25% jitter
            delay *= (1 + random.random() * 0.25)

        return delay


def retry_with_backoff(
    policy: Optional[RetryPolicy] = None,
    retryable_exceptions: Optional[Tuple[type, ...]] = None,
):
    """
    Decorator for automatic retry with exponential backoff.

    Args:
        policy: Retry policy configuration
        retryable_exceptions: Exception types to retry on

    Returns:
        Decorated function

    Example:
        >>> @retry_with_backoff(max_retries=3)
        ... async def fetch_data():
        ...     return await some_api_call()
    """
    if policy is None:
        policy = RetryPolicy()

    if retryable_exceptions is not None:
        policy = RetryPolicy(
            max_retries=policy.max_retries,
            base_delay=policy.base_delay,
            max_delay=policy.max_delay,
            exponential_base=policy.exponential_base,
            jitter=policy.jitter,
            retryable_exceptions=retryable_exceptions,
        )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(policy.max_retries + 1):
                try:
                    return await func(*args, **kwargs)

                except policy.retryable_exceptions as e:
                    last_exception = e

                    if attempt < policy.max_retries:
                        delay = policy.calculate_delay(attempt)
                        log.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}): {e}. "
                            f"Retry in {delay:.1f}s..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        log.error(
                            f"{func.__name__} failed after {policy.max_retries + 1} attempts"
                        )

            raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(policy.max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except policy.retryable_exceptions as e:
                    last_exception = e

                    if attempt < policy.max_retries:
                        delay = policy.calculate_delay(attempt)
                        log.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}): {e}. "
                            f"Retry in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        log.error(
                            f"{func.__name__} failed after {policy.max_retries + 1} attempts"
                        )

            raise last_exception

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator