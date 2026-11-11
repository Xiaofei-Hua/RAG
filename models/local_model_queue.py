"""Bound local model work across synchronous and asynchronous callers."""

import asyncio
import threading
import time
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

BUSY_ANSWER = "模型当前繁忙，请稍后重试。"


class ModelBusyError(RuntimeError):
    """Terminate admission without retrying model work."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason

    def outcome(self):
        return {
            "status": "busy",
            "generation_complete": False,
            "reason": self.reason,
            "retryable": True,
        }


@dataclass(eq=False)
class Ticket:
    short: bool
    wake: object
    queued_at: float
    granted_at: float | None = None


@dataclass
class CallStats:
    queue_ms: float = 0.0
    service_ms: float = 0.0
    calls: int = 0
    lock: object = field(default_factory=threading.Lock, repr=False)

    def add(self, queue_ms, service_ms):
        with self.lock:
            self.queue_ms += queue_ms
            self.service_ms += service_ms
            self.calls += 1

    def metadata(self):
        with self.lock:
            return {
                "model_queue_time_ms": round(self.queue_ms, 3),
                "model_service_time_ms": round(self.service_ms, 3),
                "scheduled_model_calls": self.calls,
            }


_call_stats = ContextVar("local_model_call_stats", default=None)


def request_model_metrics():
    stats = _call_stats.get()
    return stats.metadata() if stats is not None and stats.calls else {}


class ModelMetricsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = _call_stats.set(CallStats())
        try:
            return await self.app(scope, receive, send)
        finally:
            _call_stats.reset(token)


class LocalModelQueue:
    def __init__(self, max_waiting=8, wait_timeout=30.0, clock=time.monotonic):
        self.max_waiting = max_waiting
        self.wait_timeout = wait_timeout
        self.clock = clock
        self._lock = threading.Lock()
        self._waiting = deque()
        self._active = None
        self._short_streak = 0

    @property
    def pending(self):
        with self._lock:
            return len(self._waiting)

    @property
    def active_count(self):
        with self._lock:
            return int(self._active is not None)

    def submit(self, short, wake):
        ticket = Ticket(short, wake, self.clock())
        with self._lock:
            if self._active is None:
                self._active = ticket
                ticket.granted_at = self.clock()
            else:
                if len(self._waiting) >= self.max_waiting:
                    raise ModelBusyError("queue_full")
                self._waiting.append(ticket)
        if ticket.granted_at is not None:
            wake()
        return ticket

    def release(self, ticket):
        next_ticket = None
        with self._lock:
            if self._active is ticket:
                self._active = None
                if self._waiting:
                    oldest = self._waiting[0]
                    short = next((t for t in self._waiting if t.short), None)
                    generation = next((t for t in self._waiting if not t.short), None)
                    if self.clock() - oldest.queued_at >= 2.0:
                        next_ticket = oldest
                    elif short is not None and (self._short_streak < 2 or generation is None):
                        next_ticket = short
                    else:
                        next_ticket = generation or oldest
                    self._waiting.remove(next_ticket)
                    self._active = next_ticket
                    next_ticket.granted_at = self.clock()
                    self._short_streak = self._short_streak + 1 if next_ticket.short else 0
                else:
                    self._short_streak = 0
            elif ticket in self._waiting:
                self._waiting.remove(ticket)
        if next_ticket is not None:
            next_ticket.wake()

    def _record(self, ticket, started):
        stats = _call_stats.get()
        if stats is not None:
            stats.add((started - ticket.queued_at) * 1000, (self.clock() - started) * 1000)

    @contextmanager
    def lease(self, short=False):
        ready = threading.Event()
        ticket = self.submit(short, ready.set)
        started = None
        try:
            if ticket.granted_at is None and not ready.wait(self.wait_timeout):
                raise ModelBusyError("queue_timeout")
            started = self.clock()
            yield ticket
        finally:
            if started is not None:
                self._record(ticket, started)
            self.release(ticket)

    @asynccontextmanager
    async def alease(self, short=False):
        loop = asyncio.get_running_loop()
        ready = loop.create_future()

        def resolve():
            if not ready.done():
                ready.set_result(None)

        def wake():
            try:
                loop.call_soon_threadsafe(resolve)
            except RuntimeError:
                self.release(ticket)

        ticket = self.submit(short, wake)
        started = None
        try:
            if ticket.granted_at is None:
                await asyncio.wait_for(ready, self.wait_timeout)
            started = self.clock()
            yield ticket
        except asyncio.TimeoutError as exc:
            if started is None:
                raise ModelBusyError("queue_timeout") from exc
            raise
        finally:
            if started is not None:
                self._record(ticket, started)
            self.release(ticket)


_model_queue = LocalModelQueue()
