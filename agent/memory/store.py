from __future__ import annotations

import json
import os
import sqlite3
from typing import Dict, List, Optional

from agent.memory.types import MemoryEntry, MemoryQuery, MemoryType
from utils.log_utils import log


class MemoryStore:
    def __init__(self, db_path: str = "./data/agent_memory.db"):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_table()

    def _init_table(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_memory (
                id TEXT PRIMARY KEY,
                memory_type TEXT,
                content TEXT,
                metadata_json TEXT,
                created_at REAL,
                access_count INT DEFAULT 0,
                relevance_score REAL DEFAULT 1.0
            )
        """)
        self._conn.commit()

    def store(self, entry: MemoryEntry) -> str:
        self._conn.execute(
            "INSERT INTO agent_memory (id, memory_type, content, metadata_json, created_at, access_count, relevance_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.memory_type.value,
                entry.content,
                json.dumps(entry.metadata),
                entry.created_at,
                entry.access_count,
                entry.relevance_score,
            ),
        )
        self._conn.commit()
        log.debug(f"MemoryStore: stored memory {entry.id}")
        return entry.id

    def retrieve(self, query: MemoryQuery) -> List[MemoryEntry]:
        sql = "SELECT * FROM agent_memory WHERE content LIKE ?"
        params: list = [f"%{query.query}%"]

        if query.min_relevance > 0:
            sql += " AND relevance_score >= ?"
            params.append(query.min_relevance)

        if query.memory_types:
            placeholders = ",".join("?" for _ in query.memory_types)
            sql += f" AND memory_type IN ({placeholders})"
            params.extend(mt.value for mt in query.memory_types)

        sql += " ORDER BY relevance_score DESC, access_count DESC LIMIT ?"
        params.append(query.limit)

        rows = self._conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            entry = self._row_to_entry(row)
            self._conn.execute(
                "UPDATE agent_memory SET access_count = access_count + 1 WHERE id = ?",
                (entry.id,),
            )
            results.append(entry)
        self._conn.commit()
        return results

    def update(self, id: str, updates: Dict) -> bool:
        if not updates:
            return False
        set_clauses = []
        values = []
        for key, val in updates.items():
            if key == "metadata":
                set_clauses.append("metadata_json = ?")
                values.append(json.dumps(val))
            elif key == "memory_type":
                set_clauses.append("memory_type = ?")
                values.append(val.value if isinstance(val, MemoryType) else val)
            else:
                set_clauses.append(f"{key} = ?")
                values.append(val)
        values.append(id)
        cursor = self._conn.execute(
            f"UPDATE agent_memory SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def delete(self, id: str) -> bool:
        cursor = self._conn.execute("DELETE FROM agent_memory WHERE id = ?", (id,))
        self._conn.commit()
        return cursor.rowcount > 0

    def get_by_id(self, id: str) -> Optional[MemoryEntry]:
        row = self._conn.execute("SELECT * FROM agent_memory WHERE id = ?", (id,)).fetchone()
        return self._row_to_entry(row) if row else None

    def _row_to_entry(self, row) -> MemoryEntry:
        return MemoryEntry(
            id=row["id"],
            memory_type=MemoryType(row["memory_type"]),
            content=row["content"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=row["created_at"],
            access_count=row["access_count"],
            relevance_score=row["relevance_score"],
        )


_memory_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store
