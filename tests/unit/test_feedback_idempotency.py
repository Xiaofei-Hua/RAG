"""Feedback idempotency across independent SQLite connections."""

from __future__ import annotations

import concurrent.futures
import threading

from agent.feedback.collector import FeedbackCollector
from agent.feedback.types import FeedbackEntry, FeedbackType


def test_record_once_is_atomic_across_collectors(tmp_path):
    path = str(tmp_path / "feedback.db")
    first = FeedbackCollector(path)
    second = FeedbackCollector(path)
    barrier = threading.Barrier(2)

    def record(collector: FeedbackCollector, entry_id: str):
        barrier.wait(timeout=5)
        return collector.record_once(
            FeedbackEntry(
                id=entry_id,
                session_id=" session-1 ",
                message_id=" message-1 ",
                feedback_type=FeedbackType.THUMBS_DOWN,
            )
        )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda args: record(*args),
                    [(first, "feedback-a"), (second, "feedback-b")],
                )
            )
        assert sum(created for _, created in results) == 1
        assert len({entry_id for entry_id, _ in results}) == 1
        assert len(first.get_feedback("session-1")) == 1
    finally:
        first.close()
        second.close()


def test_record_once_preserves_legacy_append_without_message_id(tmp_path):
    collector = FeedbackCollector(str(tmp_path / "feedback.db"))
    try:
        first = collector.record_once(FeedbackEntry(session_id="session-1"))
        second = collector.record_once(FeedbackEntry(session_id="session-1"))
        assert first[1] is True
        assert second[1] is True
        assert first[0] != second[0]
        assert len(collector.get_feedback("session-1")) == 2
    finally:
        collector.close()
