from __future__ import annotations

import json
import os
import sqlite3
from typing import Dict, List, Optional

from agent.feedback.types import FeedbackEntry, FeedbackType
from utils.log_utils import log


class FeedbackCollector:
    def __init__(self, db_path: str = "./data/agent_memory.db"):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                message_id TEXT,
                feedback_type TEXT,
                content TEXT,
                original_answer TEXT,
                corrected_answer TEXT,
                timestamp REAL
            )
        """)
        self._conn.commit()

    def record(self, entry: FeedbackEntry) -> str:
        self._conn.execute(
            "INSERT INTO feedback (id, session_id, message_id, feedback_type, content, original_answer, corrected_answer, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.session_id,
                entry.message_id,
                entry.feedback_type.value,
                entry.content,
                entry.original_answer,
                entry.corrected_answer,
                entry.timestamp,
            ),
        )
        self._conn.commit()
        log.debug(f"FeedbackCollector: recorded feedback {entry.id}")
        return entry.id

    def get_feedback(self, session_id: str) -> List[FeedbackEntry]:
        rows = self._conn.execute(
            "SELECT * FROM feedback WHERE session_id = ? ORDER BY timestamp DESC",
            (session_id,),
        ).fetchall()
        return [self._row_to_entry(row) for row in rows]

    def get_stats(self) -> Dict:
        total = self._conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        by_type = {}
        for row in self._conn.execute(
            "SELECT feedback_type, COUNT(*) as cnt FROM feedback GROUP BY feedback_type"
        ).fetchall():
            by_type[row["feedback_type"]] = row["cnt"]
        positive = by_type.get(FeedbackType.THUMBS_UP.value, 0)
        positive_rate = positive / total if total > 0 else 0.0
        return {"total": total, "by_type": by_type, "positive_rate": positive_rate}

    def _row_to_entry(self, row) -> FeedbackEntry:
        return FeedbackEntry(
            id=row["id"],
            session_id=row["session_id"],
            message_id=row["message_id"] or "",
            feedback_type=FeedbackType(row["feedback_type"]),
            content=row["content"] or "",
            original_answer=row["original_answer"] or "",
            corrected_answer=row["corrected_answer"] or "",
            timestamp=row["timestamp"],
        )


_feedback_collector: Optional[FeedbackCollector] = None


def get_feedback_collector() -> FeedbackCollector:
    global _feedback_collector
    if _feedback_collector is None:
        _feedback_collector = FeedbackCollector()
    return _feedback_collector
