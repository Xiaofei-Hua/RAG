"""
Embedding model version registry.

Binds each Milvus collection to the embedding model + dimension that produced
its vectors, so a silent model swap (which would put query vectors in a
different space from stored vectors) is detected instead of silently
corroding retrieval quality.

Storage: SQLite at ``./data/embedding_registry.db``. The fingerprint is a
short hash of ``(model_name, dimension)``. On collection creation we record
the fingerprint; on search we compare the current embedding config against the
recorded one and emit a prominent warning when they diverge.

This is deliberately advisory (warn, never block) so a config change during
operations does not hard-stop retrieval — but it makes the drift visible.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading

from utils.log_utils import log

__all__ = [
    "fingerprint",
    "EmbeddingRegistry",
    "get_registry",
    "check_collection_compatible",
    "DEFAULT_DB_PATH",
]

# Module-level path attribute (AGENTS.md §6/§10 persistence contract) so
# tests/conftest.py and tests/e2e_ui/_fakes.py can redirect it to tmp_path.
DEFAULT_DB_PATH = os.getenv("EMBEDDING_REGISTRY_DB", "./data/embedding_registry.db")


def fingerprint(model_name: str, dimension: int) -> str:
    """Stable short fingerprint for an embedding model + dimension pair."""
    raw = f"{model_name}|{int(dimension)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class EmbeddingRegistry:
    """Thread-safe SQLite registry of embedding fingerprints per collection."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_registry (
                collection    TEXT PRIMARY KEY,
                fingerprint   TEXT,
                model         TEXT,
                dimension     INTEGER,
                created_at    REAL,
                updated_at    REAL
            )
            """
        )
        self._conn.commit()

    def register(
        self,
        collection: str,
        model_name: str,
        dimension: int,
    ) -> str:
        """Record (or update) the embedding fingerprint for a collection."""
        fp = fingerprint(model_name, dimension)
        import time

        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO embedding_registry
                    (collection, fingerprint, model, dimension, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(collection) DO UPDATE SET
                    fingerprint = excluded.fingerprint,
                    model = excluded.model,
                    dimension = excluded.dimension,
                    updated_at = excluded.updated_at
                """,
                (collection, fp, model_name, int(dimension), now, now),
            )
            self._conn.commit()
        log.info(f"EmbeddingRegistry: {collection} -> {model_name} dim={dimension} (fp={fp})")
        return fp

    def get(self, collection: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM embedding_registry WHERE collection = ?",
                (collection,),
            ).fetchone()
        return dict(row) if row else None

    def is_compatible(
        self,
        collection: str,
        model_name: str,
        dimension: int,
    ) -> bool:
        """True when the current embedding config matches the recorded one."""
        record = self.get(collection)
        if record is None:
            # No record yet — treat as compatible (first use).
            return True
        return record["fingerprint"] == fingerprint(model_name, dimension)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_registry: EmbeddingRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> EmbeddingRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = EmbeddingRegistry()
    return _registry


def check_collection_compatible(
    collection: str,
    model_name: str,
    dimension: int,
) -> bool:
    """
    Check + warn helper used by the retriever.

    Returns True if compatible (or no record). Emits a WARNING when the
    embedding model changed since the collection was created — the most common
    cause of silent retrieval-quality collapse.
    """
    try:
        reg = get_registry()
        if reg.is_compatible(collection, model_name, dimension):
            return True
        record = reg.get(collection) or {}
        log.warning(
            f"Embedding model mismatch for '{collection}': "
            f"current={model_name}/{dimension} vs "
            f"recorded={record.get('model')}/{record.get('dimension')}. "
            f"Stored vectors are in a different space — re-index this collection."
        )
        return False
    except Exception as e:  # noqa: BLE001 - never block retrieval on registry
        log.debug(f"embedding compatibility check failed: {e}")
        return True
