"""
Tracing Module for Enterprise RAG Platform

Provides distributed tracing using OpenTelemetry:
- Request tracing across services
- Performance metrics collection
- Error tracking
- Integration with observability platforms
"""

from core.tracing.opentelemetry import (
    TracingConfig,
    RAGTracer,
    trace_context,
    get_tracer,
    traced,
)

__all__ = [
    "TracingConfig",
    "RAGTracer",
    "trace_context",
    "get_tracer",
    "traced",
]