"""
OpenTelemetry Tracing for Enterprise RAG Platform

Provides distributed tracing for observability and debugging.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, TypeVar

from utils.log_utils import log

__all__ = [
    "TracingConfig",
    "RAGTracer",
    "trace_context",
    "get_tracer",
    "traced",
]

T = TypeVar("T")


@dataclass
class TracingConfig:
    """Configuration for OpenTelemetry tracing."""
    service_name: str = "rag-platform"
    environment: str = "development"
    enable_tracing: bool = True
    sample_rate: float = 1.0  # 100% sampling for development
    export_endpoint: Optional[str] = None  # OTLP endpoint


class SpanContext:
    """Context for a single trace span."""

    def __init__(self, name: str, trace_id: Optional[str] = None):
        self.name = name
        self.trace_id = trace_id or self._generate_trace_id()
        self.span_id = self._generate_span_id()
        self.start_time = time.perf_counter()
        self.end_time: Optional[float] = None
        self.attributes: Dict[str, Any] = {}
        self.events: list = []
        self.status = "OK"

    def _generate_trace_id(self) -> str:
        import uuid
        return uuid.uuid4().hex[:16]

    def _generate_span_id(self) -> str:
        import random
        return format(random.getrandbits(64), '016x')

    def set_attribute(self, key: str, value: Any):
        """Set span attribute."""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict] = None):
        """Add event to span."""
        self.events.append({
            "name": name,
            "timestamp": time.perf_counter(),
            "attributes": attributes or {},
        })

    def set_status(self, status: str, description: str = ""):
        """Set span status."""
        self.status = status

    def finish(self):
        """Mark span as finished."""
        self.end_time = time.perf_counter()

    @property
    def duration_ms(self) -> float:
        """Get span duration in milliseconds."""
        if self.end_time is None:
            return 0
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class RAGTracer:
    """
    Lightweight tracer for RAG operations.

    Provides tracing without external dependencies for development.
    Can be upgraded to full OpenTelemetry for production.
    """

    _instance: Optional["RAGTracer"] = None

    def __init__(self, config: Optional[TracingConfig] = None):
        """
        Initialize the tracer.

        Args:
            config: Tracing configuration
        """
        self.config = config or TracingConfig()
        self._current_span: Optional[SpanContext] = None
        self._span_stack: list = []

        log.debug(f"RAGTracer initialized: service={self.config.service_name}")

    @classmethod
    def get_instance(cls) -> "RAGTracer":
        """Get singleton tracer instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_span(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> SpanContext:
        """
        Start a new span.

        Args:
            name: Span name
            attributes: Initial attributes

        Returns:
            SpanContext for the new span
        """
        # Get trace_id from parent span if exists
        trace_id = None
        if self._span_stack:
            trace_id = self._span_stack[-1].trace_id

        span = SpanContext(name, trace_id)

        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)

        self._span_stack.append(span)
        self._current_span = span

        log.debug(f"Started span: {name} (trace={span.trace_id[:8]}...)")
        return span

    def end_span(self, span: SpanContext):
        """
        End a span.

        Args:
            span: Span to end
        """
        span.finish()

        if self._span_stack and self._span_stack[-1] is span:
            self._span_stack.pop()
            self._current_span = self._span_stack[-1] if self._span_stack else None

        log.debug(
            f"Ended span: {span.name} "
            f"(duration={span.duration_ms:.1f}ms, status={span.status})"
        )

    @contextmanager
    def trace(
        self,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """
        Context manager for tracing a block of code.

        Args:
            name: Span name
            attributes: Initial attributes

        Yields:
            SpanContext
        """
        span = self.start_span(name, attributes)
        try:
            yield span
        except Exception as e:
            span.set_status("ERROR", str(e))
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            raise
        finally:
            self.end_span(span)

    def get_current_span(self) -> Optional[SpanContext]:
        """Get current active span."""
        return self._current_span

    def add_event(self, name: str, attributes: Optional[Dict] = None):
        """Add event to current span."""
        if self._current_span:
            self._current_span.add_event(name, attributes)


# Module-level convenience functions
def get_tracer() -> RAGTracer:
    """Get the tracer instance."""
    return RAGTracer.get_instance()


@contextmanager
def trace_context(name: str, **attributes):
    """
    Context manager for tracing.

    Usage:
        with trace_context("retrieval", query="..."):
            # retrieval code
    """
    tracer = get_tracer()
    with tracer.trace(name, attributes) as span:
        yield span


def traced(name: Optional[str] = None):
    """
    Decorator for tracing functions.

    Usage:
        @traced("retrieval")
        async def retrieve(query: str):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            tracer = get_tracer()
            with tracer.trace(span_name):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            tracer = get_tracer()
            with tracer.trace(span_name):
                return func(*args, **kwargs)

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# Convenience spans for RAG operations
def trace_intent_classification(query: str):
    """Create span for intent classification."""
    return get_tracer().trace(
        "intent_classification",
        {"query.length": len(query)}
    )


def trace_retrieval(query: str, top_k: int = 5):
    """Create span for retrieval."""
    return get_tracer().trace(
        "retrieval",
        {"query.length": len(query), "top_k": top_k}
    )


def trace_llm_call(model: str, prompt_length: int):
    """Create span for LLM call."""
    return get_tracer().trace(
        "llm_call",
        {"model": model, "prompt_length": prompt_length}
    )