from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional

from agent.feedback.types import EscalationLevel, EscalationRecord
from utils.log_utils import log

# Module-level path so tests/conftest.py can redirect it to tmp_path
# (AGENTS.md §6/§10 persistence contract). Shared with MemoryStore/FeedbackCollector.
DEFAULT_DB_PATH = "./data/agent_memory.db"


class EscalationManager:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS escalations (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                level TEXT,
                reason TEXT,
                answer TEXT,
                resolved INT DEFAULT 0,
                timestamp REAL
            )
        """)
        self._conn.commit()

    def assess_confidence(self, metadata: Dict) -> EscalationLevel:
        has_reasoning = metadata.get("has_reasoning", True)
        answer_length = metadata.get("answer_length", 200)
        has_sources = metadata.get("has_sources", True)
        hallucination_flag = metadata.get("hallucination_flag", False)

        if hallucination_flag:
            return EscalationLevel.CRITICAL
        if not has_sources:
            return EscalationLevel.HIGH
        if not has_reasoning and answer_length < 100:
            return EscalationLevel.MEDIUM
        return EscalationLevel.NONE

    def create_escalation(
        self,
        level: EscalationLevel,
        session_id: str,
        answer: str = "",
        context: Dict = None,
    ) -> EscalationRecord:
        import uuid
        import json

        record = EscalationRecord(
            id=str(uuid.uuid4()),
            session_id=session_id,
            level=level,
            reason=f"Auto-escalation: {level.value}",
            answer=answer,
            context_snapshot=context or {},
        )
        self._conn.execute(
            "INSERT INTO escalations (id, session_id, level, reason, answer, resolved, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.session_id,
                record.level.value,
                record.reason,
                record.answer,
                0,
                record.timestamp,
            ),
        )
        self._conn.commit()
        log.warning(f"EscalationManager: created {level.value} escalation {record.id}")
        return record

    def get_pending(self) -> List[EscalationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM escalations WHERE resolved = 0 ORDER BY timestamp DESC"
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def resolve(self, id: str, resolution: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE escalations SET resolved = 1 WHERE id = ?", (id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def _row_to_record(self, row) -> EscalationRecord:
        return EscalationRecord(
            id=row["id"],
            session_id=row["session_id"],
            level=EscalationLevel(row["level"]),
            reason=row["reason"],
            answer=row["answer"] or "",
            resolved=bool(row["resolved"]),
            timestamp=row["timestamp"],
        )

    def close(self) -> None:
        """Close the underlying SQLite connection. Idempotent."""
        conn = getattr(self, "_conn", None)
        if conn is None:
            return
        self._conn = None
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


_escalation_manager: Optional[EscalationManager] = None


def get_escalation_manager() -> EscalationManager:
    global _escalation_manager
    if _escalation_manager is None:
        _escalation_manager = EscalationManager()
    return _escalation_manager


def reset_escalation_manager() -> None:
    """Close and clear the shared singleton (mainly for tests)."""
    global _escalation_manager
    if _escalation_manager is not None:
        _escalation_manager.close()
    _escalation_manager = None
