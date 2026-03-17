"""
Model Fallback Module

Provides resilience patterns for LLM calls:
- Circuit breaker (prevent cascading failures)
- Retry with exponential backoff
- Graceful degradation strategies
"""

from core.fallback.circuit_breaker import CircuitBreaker, CircuitState, CircuitBreakerError
from core.fallback.retry import RetryPolicy, retry_with_backoff
from core.fallback.degradation import DegradationHandler, FallbackMode

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerError",
    "RetryPolicy",
    "retry_with_backoff",
    "DegradationHandler",
    "FallbackMode",
]