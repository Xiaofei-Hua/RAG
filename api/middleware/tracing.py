"""
Tracing Middleware for Enterprise RAG Platform

Adds distributed tracing to all requests.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from utils.log_utils import log


class TracingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request tracing.

    Adds trace ID to all requests for distributed tracing.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or use existing trace ID
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4())[:16])

        # Store in request state
        request.state.trace_id = trace_id

        # Start timing
        start_time = time.perf_counter()

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = (time.perf_counter() - start_time) * 1000

        # Add trace headers
        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Response-Time-Ms"] = f"{duration:.1f}"

        # Log request
        log.info(
            f"[{trace_id}] {request.method} {request.url.path} "
            f"- {response.status_code} ({duration:.1f}ms)"
        )

        return response