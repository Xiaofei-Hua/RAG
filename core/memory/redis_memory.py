"""
Redis Session Memory for Enterprise RAG Platform

Provides persistent session storage with:
- Sliding window message retention
- Memory-efficient serialization
- Connection pooling for low-resource servers
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from utils.log_utils import log

__all__ = [
    "RedisSessionMemory",
    "SessionConfig",
    "SessionReadResult",
    "SaveExchangeResult",
    "DEFAULT_SESSION_DB_PATH",
]

# Module-level path attribute (AGENTS.md §6/§10 persistence contract) for the
# SQLite fallback store, so tests/conftest.py and tests/e2e_ui/_fakes.py can
# redirect it to tmp_path. (The in-process client fixture overrides
# get_session_memory via dependency_overrides, so this path is only hit by the
# real uvicorn process when Redis is unavailable.)
DEFAULT_SESSION_DB_PATH = os.getenv("SESSIONS_DB", "./data/sessions.db")


@dataclass
class SessionConfig:
    """Configuration for session memory."""

    redis_url: str = "redis://localhost:6379/0"
    max_messages: int = 50  # Max messages per session
    key_prefix: str = "rag:session:"
    connection_pool_size: int = 5
    socket_timeout_seconds: float = 0.75
    operation_timeout_seconds: float = 1.0


@dataclass(frozen=True)
class SessionReadResult:
    """Observable result for a history read across configured shards."""

    messages: list[BaseMessage]
    available: bool
    complete: bool
    degraded: bool
    backend: str


@dataclass(frozen=True)
class SaveExchangeResult:
    """Persistence truth for one atomic user/assistant exchange."""

    persisted: bool | None
    backend: str
    degraded: bool
    exchange_id: str


_REDIS_SAVE_EXCHANGE_LUA = """
local ids = redis.call('LRANGE', KEYS[2], 0, -1)
local user_seen = false
local assistant_seen = false
for _, value in ipairs(ids) do
    if value == ARGV[3] then user_seen = true end
    if value == ARGV[4] then assistant_seen = true end
end
if user_seen and assistant_seen then return 0 end
if user_seen or assistant_seen then
    return redis.error_reply('inconsistent exchange')
end
redis.call('LPUSH', KEYS[1], ARGV[1], ARGV[2])
redis.call('LTRIM', KEYS[1], 0, tonumber(ARGV[5]) - 1)
redis.call('LPUSH', KEYS[2], ARGV[3], ARGV[4])
redis.call('LTRIM', KEYS[2], 0, tonumber(ARGV[5]) - 1)
return 1
"""


class RedisSessionMemory:
    """
    Redis-based session memory manager.

    Features:
    - Persistent storage across restarts
    - Sliding window message retention
    - Memory-efficient JSON serialization
    """

    def __init__(
        self,
        config: SessionConfig | None = None,
        redis_client: Any | None = None,
        sqlite_store: _SQLiteStore | None = None,
    ):
        self.config = config or SessionConfig()
        self._redis = redis_client
        self._redis_initialized = redis_client is not None
        self._redis_configured = not isinstance(redis_client, _SQLiteStore)
        self._sqlite = sqlite_store or (
            redis_client if isinstance(redis_client, _SQLiteStore) else _SQLiteStore()
        )
        self._connected = False

    @property
    def redis(self):
        """Get Redis client (lazy initialization)."""
        if not self._redis_initialized:
            self._redis_initialized = True
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(
                    self.config.redis_url,
                    max_connections=self.config.connection_pool_size,
                    decode_responses=True,
                    socket_connect_timeout=self.config.socket_timeout_seconds,
                    socket_timeout=self.config.socket_timeout_seconds,
                    retry_on_timeout=False,
                )
                self._connected = True
                log.info("Redis session backend configured")
            except ImportError:
                log.warning("redis package not installed, using SQLite fallback")
                self._redis_configured = False
                self._redis = None
            except Exception as exc:
                log.error("Redis client setup failed: {}", type(exc).__name__)
                self._redis = None
        return self._redis if self._redis is not None else self._sqlite

    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for session."""
        return f"{self.config.key_prefix}{session_id}"

    def _message_ids_key(self, session_id: str) -> str:
        return f"{self._session_key(session_id)}:message_ids"

    async def save_exchange(
        self,
        session_id: str,
        user_message: BaseMessage,
        assistant_message: BaseMessage,
        *,
        exchange_id: str | None = None,
    ) -> SaveExchangeResult:
        """Atomically persist a complete exchange, with replay-safe IDs."""
        exchange_id = exchange_id or str(uuid.uuid4())
        timestamp = time.time()
        user_id = f"{exchange_id}:user"
        assistant_id = f"{exchange_id}:assistant"
        user_json = json.dumps(
            self._serialize_message(
                user_message,
                timestamp=timestamp,
                exchange_id=exchange_id,
                message_id=user_id,
            ),
            ensure_ascii=False,
        )
        assistant_json = json.dumps(
            self._serialize_message(
                assistant_message,
                timestamp=timestamp,
                exchange_id=exchange_id,
                message_id=assistant_id,
            ),
            ensure_ascii=False,
        )
        title = user_message.content[:50].replace("\n", " ").strip()
        # History is retained in complete user/assistant pairs.  An odd
        # configured message limit would otherwise keep half of the oldest
        # exchange after LTRIM/DELETE.
        retained_messages = max(2, self.config.max_messages // 2 * 2)
        redis_failed = False

        if self._redis_configured:
            redis = self.redis
            if redis is not self._sqlite:
                try:
                    await asyncio.wait_for(
                        redis.eval(
                            _REDIS_SAVE_EXCHANGE_LUA,
                            2,
                            self._session_key(session_id),
                            self._message_ids_key(session_id),
                            user_json,
                            assistant_json,
                            user_id,
                            assistant_id,
                            str(retained_messages),
                        ),
                        timeout=self.config.operation_timeout_seconds,
                    )
                    self._connected = True
                    await self._register_redis_session(session_id, title)
                    return SaveExchangeResult(True, "primary", False, exchange_id)
                except Exception as exc:
                    redis_failed = True
                    self._connected = False
                    log.warning("Redis exchange failed: {}", type(exc).__name__)

        task = asyncio.create_task(
            self._sqlite.save_exchange(
                self._session_key(session_id),
                user_json,
                assistant_json,
                max_messages=retained_messages,
                session_id=session_id,
                title=title,
            )
        )
        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=self.config.operation_timeout_seconds
            )
            return SaveExchangeResult(True, "fallback", redis_failed, exchange_id)
        except TimeoutError:
            task.add_done_callback(self._consume_background_result)
            log.warning("SQLite exchange result is pending after deadline")
            return SaveExchangeResult(None, "fallback", True, exchange_id)
        except Exception as exc:
            log.error("SQLite exchange failed: {}", type(exc).__name__)
            return SaveExchangeResult(False, "fallback", True, exchange_id)

    @staticmethod
    def _consume_background_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except Exception as exc:
            log.error("Deferred SQLite exchange failed: {}", type(exc).__name__)

    async def _register_redis_session(self, session_id: str, title: str) -> None:
        """Best-effort derived registry update; message persistence is authoritative."""
        redis = self._redis
        if redis is None:
            return
        try:
            if hasattr(redis, "zadd"):
                await redis.zadd(f"{self.config.key_prefix}registry", {session_id: time.time()})
            if title and hasattr(redis, "hset"):
                await redis.hset(f"{self.config.key_prefix}titles", session_id, title)
        except Exception as exc:
            log.debug("Redis session registry update skipped: {}", type(exc).__name__)

    async def save_message(
        self,
        session_id: str,
        message: BaseMessage,
    ) -> bool:
        """Save a message to session history."""
        try:
            key = self._session_key(session_id)

            msg_data = self._serialize_message(message)
            msg_json = json.dumps(msg_data, ensure_ascii=False)

            # Derive a short title from the first HumanMessage
            title = ""
            if isinstance(message, HumanMessage):
                title = message.content[:50].replace("\n", " ").strip()

            try:
                backend = self.redis
                await backend.lpush(key, msg_json)
                await backend.ltrim(key, 0, self.config.max_messages - 1)
                if backend is self._sqlite:
                    await self._sqlite.register_session(session_id, title)
                else:
                    await self._register_redis_session(session_id, title)
            except Exception as conn_err:
                log.warning("Primary message save failed: {}", type(conn_err).__name__)
                await self._sqlite.lpush(key, msg_json)
                await self._sqlite.ltrim(key, 0, self.config.max_messages - 1)
                await self._sqlite.register_session(session_id, title)

            log.debug(f"Message saved to session {session_id[:8]}...")
            return True

        except Exception as exc:
            log.error("Failed to save message: {}", type(exc).__name__)
            return False

    async def read_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> SessionReadResult:
        """Read and merge all configured shards without disguising partial data."""
        limit = limit or self.config.max_messages
        key = self._session_key(session_id)
        shards: list[tuple[str, Any]] = [("fallback", self._sqlite)]
        if self._redis_configured:
            redis = self.redis
            if redis is not self._sqlite:
                shards.insert(0, ("primary", redis))

        async def read(name: str, backend: Any):
            try:
                rows = await asyncio.wait_for(
                    backend.lrange(key, 0, self.config.max_messages - 1),
                    timeout=self.config.operation_timeout_seconds,
                )
                return name, list(rows), None
            except Exception as exc:
                log.warning("Session shard read failed ({}): {}", name, type(exc).__name__)
                return name, [], exc

        results = await asyncio.gather(*(read(name, backend) for name, backend in shards))
        successes = [(name, rows) for name, rows, error in results if error is None]
        if not successes:
            return SessionReadResult([], False, False, True, "unavailable")

        messages: list[BaseMessage] = []
        seen: set[str] = set()
        decode_failed = False
        for _, rows in successes:
            for raw in rows:
                try:
                    data = json.loads(raw)
                    identity = self._message_identity(data)
                    if identity in seen:
                        continue
                    message = self._deserialize_message(data)
                    if message is not None:
                        seen.add(identity)
                        messages.append(message)
                except Exception as exc:
                    decode_failed = True
                    log.warning("Session message decode skipped: {}", type(exc).__name__)

        messages.sort(key=self._message_sort_key, reverse=True)
        complete = len(successes) == len(shards) and not decode_failed
        backend = "combined" if len(successes) > 1 else successes[0][0]
        return SessionReadResult(messages[:limit], True, complete, not complete, backend)

    async def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[BaseMessage]:
        """Get messages from session history (newest first)."""
        result = await self.read_messages(session_id, limit=limit)
        return result.messages

    async def register_session(self, session_id: str, title: str = ""):
        """Register or update a session in the session registry."""
        try:
            await self._sqlite.register_session(session_id, title)
            if self._redis_configured and self.redis is not self._sqlite:
                await self._register_redis_session(session_id, title)
        except Exception as exc:
            log.error("Failed to register session: {}", type(exc).__name__)

    async def list_sessions(self, skip: int = 0, limit: int = 20):
        """List all tracked sessions."""
        try:
            return await self._sqlite.list_sessions(skip, limit)
        except Exception as exc:
            log.error("Failed to list sessions: {}", type(exc).__name__)
            return [], 0

    async def clear_session(self, session_id: str) -> bool:
        """Clear all messages for a session and unregister it."""
        try:
            key = self._session_key(session_id)
            await self._sqlite.delete(key)
            await self._sqlite.unregister_session(session_id)
            if self._redis_configured and self.redis is not self._sqlite:
                try:
                    await self.redis.delete(key, self._message_ids_key(session_id))
                    if hasattr(self.redis, "zrem"):
                        await self.redis.zrem(f"{self.config.key_prefix}registry", session_id)
                    if hasattr(self.redis, "hdel"):
                        await self.redis.hdel(f"{self.config.key_prefix}titles", session_id)
                except Exception as exc:
                    log.warning("Primary session clear incomplete: {}", type(exc).__name__)
            log.info(f"Session cleared: {session_id[:8]}...")
            return True
        except Exception as exc:
            log.error("Failed to clear session: {}", type(exc).__name__)
            return False

    async def session_exists(self, session_id: str) -> bool:
        """Check if session exists."""
        try:
            result = await self.read_messages(session_id, limit=1)
            return bool(result.messages)
        except Exception:
            return False

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Get session metadata."""
        try:
            result = await self.read_messages(session_id)

            return {
                "session_id": session_id,
                "message_count": len(result.messages),
                "exists": bool(result.messages),
                "complete": result.complete,
                "degraded": result.degraded,
            }
        except Exception as exc:
            return {"session_id": session_id, "error": type(exc).__name__}

    def _serialize_message(
        self,
        message: BaseMessage,
        *,
        timestamp: float | None = None,
        exchange_id: str | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        """Serialize a message to JSON-compatible dict."""
        msg_type = type(message).__name__
        kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
        kwargs["_timestamp"] = time.time() if timestamp is None else timestamp
        if exchange_id:
            kwargs["_exchange_id"] = exchange_id
        if message_id:
            kwargs["_message_id"] = message_id
        return {
            "type": msg_type,
            "content": message.content,
            "additional_kwargs": kwargs,
        }

    def _deserialize_message(self, data: dict[str, Any]) -> BaseMessage | None:
        """Deserialize a message from dict."""
        msg_type = data.get("type", "HumanMessage")
        content = data.get("content", "")
        kwargs = data.get("additional_kwargs", {})

        message_classes = {
            "HumanMessage": HumanMessage,
            "AIMessage": AIMessage,
            "SystemMessage": SystemMessage,
        }

        msg_class = message_classes.get(msg_type, HumanMessage)
        return msg_class(content=content, additional_kwargs=kwargs)

    @staticmethod
    def _message_identity(data: dict[str, Any]) -> str:
        kwargs = data.get("additional_kwargs") or {}
        message_id = kwargs.get("_message_id")
        if message_id:
            return f"id:{message_id}"
        payload = json.dumps(
            {
                "type": data.get("type"),
                "content": data.get("content"),
                "timestamp": kwargs.get("_timestamp"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"legacy:{hashlib.sha256(payload.encode()).hexdigest()}"

    @staticmethod
    def _message_sort_key(message: BaseMessage) -> tuple:
        kwargs = getattr(message, "additional_kwargs", {}) or {}
        role_order = 1 if isinstance(message, AIMessage) else 0
        return (
            float(kwargs.get("_timestamp") or 0.0),
            str(kwargs.get("_exchange_id") or ""),
            role_order,
            str(kwargs.get("_message_id") or ""),
        )

    async def close(self):
        """Close Redis connection."""
        if self._redis is not None and self._redis is not self._sqlite and hasattr(
            self._redis, "close"
        ):
            result = self._redis.close()
            if inspect.isawaitable(result):
                await result
        await self._sqlite.close()
        log.debug("Session backends closed")


class _SQLiteStore:
    """
    SQLite-based persistent fallback when Redis is unavailable.

    Data survives restarts. No TTL — sessions persist until manually deleted.
    """

    def __init__(self, db_path: str | None = None):
        import sqlite3

        db_path = db_path or DEFAULT_SESSION_DB_PATH
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=0.25)
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA busy_timeout=250")
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception as exc:
            log.debug("SQLite session WAL unavailable: {}", type(exc).__name__)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  key TEXT NOT NULL,"
            "  idx INTEGER NOT NULL,"
            "  value TEXT NOT NULL,"
            "  message_id TEXT,"
            "  PRIMARY KEY (key, idx)"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS session_meta ("
            "  session_id TEXT PRIMARY KEY,"
            "  created_at REAL NOT NULL,"
            "  last_active REAL NOT NULL,"
            "  title TEXT NOT NULL DEFAULT ''"
            ")"
        )
        session_cols = [r[1] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()]
        if "message_id" not in session_cols:
            self._conn.execute("ALTER TABLE sessions ADD COLUMN message_id TEXT")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_message_id "
            "ON sessions (key, message_id) WHERE message_id IS NOT NULL"
        )
        # Migrate: add title column if missing
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(session_meta)").fetchall()]
        if "title" not in cols:
            self._conn.execute("ALTER TABLE session_meta ADD COLUMN title TEXT NOT NULL DEFAULT ''")
        self._conn.commit()
        log.info(f"SQLite session store initialized: {db_path}")

    @staticmethod
    def _json_message_id(value: str) -> str | None:
        try:
            data = json.loads(value)
            message_id = (data.get("additional_kwargs") or {}).get("_message_id")
            return str(message_id) if message_id else None
        except Exception:
            return None

    async def lpush(self, key: str, value: str):
        await asyncio.to_thread(self._lpush_sync, key, value)

    def _lpush_sync(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE sessions SET idx = idx + 1 WHERE key = ?", (key,))
            self._conn.execute(
                "INSERT INTO sessions (key, idx, value, message_id) VALUES (?, 0, ?, ?)",
                (key, value, self._json_message_id(value)),
            )
            self._conn.commit()

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        return await asyncio.to_thread(self._lrange_sync, key, start, end)

    def _lrange_sync(self, key: str, start: int, end: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT value FROM sessions WHERE key = ? ORDER BY idx LIMIT ? OFFSET ?",
                (key, end - start + 1, start),
            ).fetchall()
            return [r[0] for r in rows]

    async def ltrim(self, key: str, start: int, end: int):
        await asyncio.to_thread(self._ltrim_sync, key, start, end)

    def _ltrim_sync(self, key: str, start: int, end: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM sessions WHERE key = ? AND idx NOT IN "
                "(SELECT idx FROM sessions WHERE key = ? ORDER BY idx LIMIT ? OFFSET ?)",
                (key, key, end - start + 1, start),
            )
            rows = self._conn.execute(
                "SELECT rowid FROM sessions WHERE key = ? ORDER BY idx",
                (key,),
            ).fetchall()
            for new_idx, (rowid,) in enumerate(rows):
                self._conn.execute(
                    "UPDATE sessions SET idx = ? WHERE rowid = ?",
                    (new_idx, rowid),
                )
            self._conn.commit()

    async def save_exchange(
        self,
        key: str,
        user_json: str,
        assistant_json: str,
        *,
        max_messages: int = 50,
        session_id: str | None = None,
        title: str = "",
    ) -> None:
        await asyncio.to_thread(
            self._save_exchange_sync,
            key,
            user_json,
            assistant_json,
            max_messages,
            session_id,
            title,
        )

    def _save_exchange_sync(
        self,
        key: str,
        user_json: str,
        assistant_json: str,
        max_messages: int,
        session_id: str | None,
        title: str,
    ) -> None:
        user_id = self._json_message_id(user_json)
        assistant_id = self._json_message_id(assistant_json)
        if not user_id or not assistant_id:
            raise ValueError("exchange messages require stable IDs")

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                rows = self._conn.execute(
                    "SELECT message_id FROM sessions WHERE key = ? AND message_id IN (?, ?)",
                    (key, user_id, assistant_id),
                ).fetchall()
                found = {row[0] for row in rows}
                if found == {user_id, assistant_id}:
                    self._conn.commit()
                    return
                if found:
                    raise RuntimeError("inconsistent exchange")

                self._conn.execute("UPDATE sessions SET idx = idx + 2 WHERE key = ?", (key,))
                self._conn.execute(
                    "INSERT INTO sessions (key, idx, value, message_id) VALUES (?, 1, ?, ?)",
                    (key, user_json, user_id),
                )
                self._conn.execute(
                    "INSERT INTO sessions (key, idx, value, message_id) VALUES (?, 0, ?, ?)",
                    (key, assistant_json, assistant_id),
                )
                self._conn.execute(
                    "DELETE FROM sessions WHERE key = ? AND idx >= ?", (key, max_messages)
                )
                if session_id:
                    now = time.time()
                    self._conn.execute(
                        "INSERT INTO session_meta "
                        "(session_id, created_at, last_active, title) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(session_id) DO UPDATE SET "
                        "last_active=excluded.last_active, "
                        "title=CASE WHEN session_meta.title='' THEN excluded.title "
                        "ELSE session_meta.title END",
                        (session_id, now, now, title),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    async def llen(self, key: str) -> int:
        return await asyncio.to_thread(self._llen_sync, key)

    def _llen_sync(self, key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else 0

    async def delete(self, key: str):
        await asyncio.to_thread(self._delete_sync, key)

    def _delete_sync(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE key = ?", (key,))
            self._conn.commit()

    async def exists(self, key: str) -> int:
        return await asyncio.to_thread(self._exists_sync, key)

    def _exists_sync(self, key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
            return 1 if row else 0

    async def register_session(self, session_id: str, title: str = ""):
        await asyncio.to_thread(self._register_session_sync, session_id, title)

    def _register_session_sync(self, session_id: str, title: str = "") -> None:
        now = time.time()
        with self._lock:
            existing = self._conn.execute(
                "SELECT title FROM session_meta WHERE session_id = ?", (session_id,)
            ).fetchone()
            if existing:
                if title and not existing[0]:
                    self._conn.execute(
                        "UPDATE session_meta SET last_active = ?, title = ? WHERE session_id = ?",
                        (now, title, session_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE session_meta SET last_active = ? WHERE session_id = ?",
                        (now, session_id),
                    )
            else:
                self._conn.execute(
                    "INSERT INTO session_meta (session_id, created_at, last_active, title) VALUES (?, ?, ?, ?)",
                    (session_id, now, now, title),
                )
            self._conn.commit()

    async def list_sessions(self, skip: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list_sessions_sync, skip, limit)

    def _list_sessions_sync(self, skip: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, created_at, last_active, title FROM session_meta "
                "ORDER BY last_active DESC LIMIT ? OFFSET ?",
                (limit, skip),
            ).fetchall()
            total = self._conn.execute("SELECT COUNT(*) FROM session_meta").fetchone()[0]

        results = []
        for session_id, created_at, last_active, title in rows:
            key = f"rag:session:{session_id}"
            with self._lock:
                msg_count = self._conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE key = ?", (key,)
                ).fetchone()[0]

            results.append(
                {
                    "session_id": session_id,
                    "message_count": msg_count,
                    "created_at": created_at,
                    "last_active": last_active,
                    "title": title,
                }
            )
        return results, total

    async def unregister_session(self, session_id: str):
        await asyncio.to_thread(self._unregister_session_sync, session_id)

    def _unregister_session_sync(self, session_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM session_meta WHERE session_id = ?", (session_id,))
            self._conn.commit()

    async def close(self):
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None


# Module-level instance (lazy loaded)
_memory_instance: RedisSessionMemory | None = None


def get_session_memory(config: SessionConfig | None = None) -> RedisSessionMemory:
    """Get or create session memory instance."""
    global _memory_instance

    if _memory_instance is None or config is not None:
        _memory_instance = RedisSessionMemory(config=config)
        log.debug("Created new RedisSessionMemory instance")

    return _memory_instance
