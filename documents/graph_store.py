"""
Knowledge-graph store for GraphRAG (LightRAG-inspired) retrieval leg.

Stores entities, relations and entity→chunk back-references extracted from
documents at ingestion time. The :class:`GraphRetriever` (see
``core/retrieval/graph_retriever.py``) consumes this store as the third RRF
leg of the hybrid retriever.

Design (see ``docs/specs/graphrag/design.md`` v2):

- SQLite-backed, thread-safe (``RLock``), module-level ``DEFAULT_DB_PATH`` so
  ``tests/conftest.py`` can redirect it to ``tmp_path`` (AGENTS.md §6/§10
  persistence contract).
- Three tables (``entities`` / ``relations`` / ``entity_chunks``) plus a
  ``graph_meta`` key/value table for the embedding fingerprint (F-09).
- ``upsert`` is transactional (F-10): remove-by-source + insert run inside one
  SQLite context so a mid-batch failure rolls back.
- ``entity_id`` is a normalised hash so the same entity surfaced across chunks
  merges (mention_count accumulates). ``file_hash`` defaults to '' so the
  idempotency key degrades to ``source`` when the uploader omits it (F-07).
- ``entity_chunks`` stores the **original chunk text fragment** (a trusted
  source), not the LLM-generated description, and carries ``parent_id`` so a
  graph hit can be expanded by ``expand_to_parents`` (F-06) and filtered by
  ``source`` (F-01).

The store is intentionally storage-only: extraction (Qwen3) and retrieval
(numpy ANN + 1-hop) live in their own modules so this layer stays dependency
free apart from sqlite3 + the logger.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

__all__ = [
    "Entity",
    "Relation",
    "GraphStore",
    "make_entity_id",
    "make_relation_id",
    "get_graph_store",
    "reset_graph_store",
]

# Module-level path so tests/conftest.py can redirect it to tmp_path
# (AGENTS.md §6/§10 persistence contract).
DEFAULT_DB_PATH = "./data/graph_store.db"

# F-03: cap LLM-generated descriptions so an injected payload cannot smuggle a
# long instruction into the store. The retrieval context returns original chunk
# text, not this description, so this is defence-in-depth.
MAX_DESCRIPTION_LEN = 100

# Strip control characters / newlines from descriptions (F-03): a multi-line
# injection attempt collapses to a single line, neutralising prompt-structure
# attacks in stored metadata.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _normalize_name(name: str) -> str:
    """Case/whitespace/fullwidth normalisation for entity identity.

    Two surface forms of the same concept (``"ATA 29"`` / ``"ata29"`` /
    ``"ＡＴＡ　２９"``) collapse to one ``entity_id`` so mentions accumulate.
    """
    if not name:
        return ""
    # Fullwidth ASCII (U+FF01-FF5E) → ASCII, then NFKC-style whitespace trim.
    return name.strip().casefold().replace("　", " ").replace("\t", " ").replace("  ", " ")


def make_entity_id(name: str, entity_type: str) -> str:
    """Stable, normalised id for an (name, type) pair."""
    raw = f"{_normalize_name(name)}::{_normalize_name(entity_type)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def make_relation_id(src: str, relation_type: str, tgt: str) -> str:
    """Stable id for a directed (src, rel, tgt) relation."""
    raw = f"{src}::{_normalize_name(relation_type)}::{tgt}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _sanitize_description(desc: str | None) -> str:
    """F-03 defence-in-depth: clamp length + strip control chars."""
    if not desc:
        return ""
    cleaned = _CTRL_RE.sub(" ", desc).strip()
    if len(cleaned) > MAX_DESCRIPTION_LEN:
        cleaned = cleaned[:MAX_DESCRIPTION_LEN]
    return cleaned


@dataclass
class Entity:
    """An extracted named concept with a domain type."""

    name: str
    type: str
    description: str = ""
    embedding: list[float] | None = None
    source: str = ""
    parent_id: str = ""  # parent_id of the chunk that surfaced this entity (F-06)
    chunk_text: str = ""  # original chunk fragment backing this mention

    @property
    def id(self) -> str:
        return make_entity_id(self.name, self.type)


@dataclass
class Relation:
    """A directed edge ``src --relation_type--> tgt`` between two entities."""

    src: str  # entity id
    tgt: str  # entity id
    relation_type: str
    description: str = ""
    source: str = ""
    weight: float = 1.0

    @property
    def id(self) -> str:
        return make_relation_id(self.src, self.relation_type, self.tgt)


@dataclass
class GraphRow:
    """A flat row returned by :meth:`GraphStore.load_all` for matrix rebuild."""

    entity_id: str
    name: str
    type: str
    source: str
    parent_id: str
    chunk_text: str
    embedding: list[float] = field(default_factory=list)


class GraphStore:
    """Thread-safe SQLite store of entities / relations / entity-chunk refs."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id            TEXT NOT NULL,
                    name          TEXT NOT NULL,
                    type          TEXT NOT NULL,
                    description   TEXT,
                    embedding     BLOB,
                    source        TEXT NOT NULL,
                    file_hash     TEXT NOT NULL DEFAULT '',
                    created_at    REAL,
                    mention_count INTEGER DEFAULT 1,
                    PRIMARY KEY (id, source)
                );
                CREATE INDEX IF NOT EXISTS idx_entities_source ON entities(source);
                CREATE INDEX IF NOT EXISTS idx_entities_name_type ON entities(name, type);

                CREATE TABLE IF NOT EXISTS relations (
                    id            TEXT PRIMARY KEY,
                    src_entity    TEXT NOT NULL,
                    tgt_entity    TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    description   TEXT,
                    source        TEXT NOT NULL,
                    weight        REAL DEFAULT 1.0
                );
                CREATE INDEX IF NOT EXISTS idx_relations_src ON relations(src_entity);
                CREATE INDEX IF NOT EXISTS idx_relations_tgt ON relations(tgt_entity);
                CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source);

                CREATE TABLE IF NOT EXISTS entity_chunks (
                    entity_id  TEXT NOT NULL,
                    chunk_text TEXT NOT NULL,
                    parent_id  TEXT,
                    source     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ec_entity ON entity_chunks(entity_id);
                CREATE INDEX IF NOT EXISTS idx_ec_source ON entity_chunks(source);

                CREATE TABLE IF NOT EXISTS graph_meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def upsert(
        self,
        entities: list[Entity],
        relations: list[Relation],
        source: str,
        file_hash: str = "",
        embedding_model: str = "",
        embedding_dim: int = 0,
    ) -> int:
        """Transactionally replace a source's graph data (F-10 idempotency).

        Removes every entity/relation/chunk row for ``source`` first, then
        inserts the new batch inside a single SQLite transaction so a mid-batch
        failure rolls back and the old data survives.

        Returns the number of entities written.
        """
        import struct

        if not entities and not relations:
            return 0

        now = time.time()
        # F-07: file_hash degrades to '' so the idempotency key stays on source.
        fh = file_hash or ""
        rows_written = 0

        with self._lock:
            # The `with self._conn:` context is an explicit transaction: it
            # commits on clean exit, rolls back on exception (F-10).
            with self._conn:
                self._remove_source_rows(source)

                for ent in entities:
                    eid = ent.id
                    blob = None
                    if ent.embedding:
                        # Pack float32 little-endian — matches numpy float32
                        # reinterpretation on little-endian hosts (x86/ARM LE).
                        blob = struct.pack(f"<{len(ent.embedding)}f", *ent.embedding)
                    desc = _sanitize_description(ent.description)
                    self._conn.execute(
                        """
                        INSERT INTO entities
                            (id, name, type, description, embedding, source,
                             file_hash, created_at, mention_count)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (eid, ent.name, ent.type, desc, blob, source or ent.source, fh, now, 1),
                    )
                    rows_written += 1
                    if ent.chunk_text:
                        self._conn.execute(
                            """
                            INSERT INTO entity_chunks (entity_id, chunk_text, parent_id, source)
                            VALUES (?, ?, ?, ?)
                            """,
                            (eid, ent.chunk_text, ent.parent_id or "", source or ent.source),
                        )

                for rel in relations:
                    rid = rel.id
                    self._conn.execute(
                        """
                        INSERT INTO relations
                            (id, src_entity, tgt_entity, relation_type,
                             description, source, weight)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rid,
                            rel.src,
                            rel.tgt,
                            rel.relation_type,
                            _sanitize_description(rel.description),
                            source or rel.source,
                            float(rel.weight),
                        ),
                    )

                # F-09: record the embedding fingerprint so a later model swap
                # is detectable instead of silently corrupting cosine scores.
                if embedding_model:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO graph_meta (key, value) VALUES (?, ?)",
                        ("embedding_model", embedding_model),
                    )
                if embedding_dim:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO graph_meta (key, value) VALUES (?, ?)",
                        ("embedding_dim", str(int(embedding_dim))),
                    )
                self._conn.execute(
                    "INSERT OR REPLACE INTO graph_meta (key, value) VALUES (?, ?)",
                    ("built_at", str(now)),
                )
        return rows_written

    def remove_by_source(self, source: str) -> int:
        """Delete every row tied to ``source`` across all three tables.

        Returns the number of removed entities (for observability).
        """
        if not source:
            return 0
        with self._lock:
            with self._conn:
                removed = self._remove_source_rows(source)
        return removed

    def _remove_source_rows(self, source: str) -> int:
        """Remove rows for a source (caller holds lock + transaction)."""
        cur = self._conn.execute("DELETE FROM entities WHERE source = ?", (source,))
        removed = cur.rowcount or 0
        self._conn.execute("DELETE FROM relations WHERE source = ?", (source,))
        self._conn.execute("DELETE FROM entity_chunks WHERE source = ?", (source,))
        return removed

    # ------------------------------------------------------------------
    # Read path (matrix rebuild + 1-hop adjacency)
    # ------------------------------------------------------------------

    def load_all(self) -> list[GraphRow]:
        """Load every entity with its backing chunk for matrix rebuild.

        Used by :class:`GraphRetriever` on cold start (F-05) and after writes.
        Embeddings are unpacked to ``list[float]``; empty vectors are skipped.
        """
        import struct

        rows: list[GraphRow] = []
        with self._lock:
            cur = self._conn.execute(
                """
                SELECT e.id AS eid, e.name, e.type, e.source, e.embedding,
                       ec.chunk_text, ec.parent_id
                FROM entities e
                LEFT JOIN entity_chunks ec
                  ON ec.entity_id = e.id AND ec.source = e.source
                ORDER BY e.id
                """
            )
            for r in cur.fetchall():
                blob = r["embedding"]
                vec: list[float] = []
                if blob:
                    n = len(blob) // 4
                    try:
                        vec = list(struct.unpack(f"<{n}f", blob))
                    except struct.error:
                        continue
                rows.append(
                    GraphRow(
                        entity_id=r["eid"],
                        name=r["name"],
                        type=r["type"],
                        source=r["source"],
                        parent_id=r["parent_id"] or "",
                        chunk_text=r["chunk_text"] or "",
                        embedding=vec,
                    )
                )
        return rows

    def neighbors(self, entity_ids: list[str]) -> list[tuple[str, str, float]]:
        """1-hop adjacency: ``(neighbor_id, relation_type, weight)`` per seed.

        Used by the high-level retrieval leg (F-08). Returns de-duplicated
        neighbours across both edge directions. Neighbour ids are entity_ids
        (cross-source by design — graph traversal connects concepts across
        manuals); the caller resolves each to its source-scoped chunks.
        """
        if not entity_ids:
            return []
        placeholders = ",".join("?" for _ in entity_ids)
        out: dict[str, tuple[str, float]] = {}
        with self._lock:
            cur = self._conn.execute(
                f"""
                SELECT tgt_entity AS nb, relation_type, weight
                FROM relations WHERE src_entity IN ({placeholders})
                UNION ALL
                SELECT src_entity AS nb, relation_type, weight
                FROM relations WHERE tgt_entity IN ({placeholders})
                """,
                (*entity_ids, *entity_ids),
            )
            for r in cur.fetchall():
                nb = r["nb"]
                w = float(r["weight"]) if r["weight"] is not None else 1.0
                if nb not in out or w > out[nb][1]:
                    out[nb] = (r["relation_type"], w)
        return [(nb, rt, w) for nb, (rt, w) in out.items()]

    def chunks_for_entity(self, entity_id: str) -> list[tuple[str, str, str]]:
        """All ``(source, chunk_text, parent_id)`` rows for an entity id.

        A concept surfaced across manuals yields one row per source so the
        high-level leg can fan out and let F-01 filtering pick the allowed
        source(s) at the Document level.
        """
        out: list[tuple[str, str, str]] = []
        with self._lock:
            cur = self._conn.execute(
                "SELECT source, chunk_text, parent_id FROM entity_chunks WHERE entity_id = ?",
                (entity_id,),
            )
            for r in cur.fetchall():
                out.append((r["source"], r["chunk_text"] or "", r["parent_id"] or ""))
        return out

    def chunk_text_for(self, keys: list[tuple[str, str]]) -> dict[tuple[str, str], tuple[str, str]]:
        """Fetch ``(chunk_text, parent_id)`` per (entity_id, source) pair.

        Keyed by the (entity_id, source) tuple because the same concept surfaced
        in two manuals is two entity rows (PK is id+source) with two distinct
        backing chunks — a source-scoped lookup keeps F-01 filtering precise.
        """
        if not keys:
            return {}
        out: dict[tuple[str, str], tuple[str, str]] = {}
        with self._lock:
            for eid, source in keys:
                row = self._conn.execute(
                    """
                    SELECT chunk_text, parent_id FROM entity_chunks
                    WHERE entity_id = ? AND source = ?
                    """,
                    (eid, source),
                ).fetchone()
                if row:
                    out[(eid, source)] = (row["chunk_text"] or "", row["parent_id"] or "")
        return out

    def meta(self, key: str, default: str = "") -> str:
        """Read a ``graph_meta`` value (F-09 fingerprint)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM graph_meta WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
        return row["c"] if row else 0

    def close(self) -> None:
        with self._lock:
            conn = getattr(self, "_conn", None)
            if conn is None:
                return
            self._conn = None
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors parent_store / bm25_retriever)
# ---------------------------------------------------------------------------

_store: GraphStore | None = None
_store_lock = threading.Lock()


def get_graph_store() -> GraphStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = GraphStore()
    return _store


def reset_graph_store() -> None:
    """Close and clear the shared singleton (mainly for tests)."""
    global _store
    if _store is not None:
        _store.close()
    _store = None
