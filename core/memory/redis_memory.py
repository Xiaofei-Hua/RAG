"""
Redis Session Memory for Enterprise RAG Platform

Provides persistent session storage with:
- Sliding window message retention
- Automatic session expiration
- Memory-efficient serialization
- Connection pooling for low-resource servers
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage

from utils.log_utils import log

__all__ = [
    "RedisSessionMemory",
    "SessionConfig",
]


@dataclass
class SessionConfig:
    """Configuration for session memory."""
    redis_url: str = "redis://localhost:6379/0"
    session_ttl: int = 3600  # 1 hour default
    max_messages: int = 50   # Max messages per session
    key_prefix: str = "rag:session:"
    connection_pool_size: int = 5


class RedisSessionMemory:
    """
    Redis-based session memory manager.

    Features:
    - Persistent storage across restarts
    - Automatic expiration
    - Sliding window message retention
    - Memory-efficient JSON serialization
    """

    def __init__(
        self,
        config: Optional[SessionConfig] = None,
        redis_client: Optional[Any] = None,
    ):
        """
        Initialize Redis session memory.

        Args:
            config: Session configuration
            redis_client: Optional pre-configured Redis client
        """
        self.config = config or SessionConfig()
        self._redis = redis_client
        self._connected = False

        log.debug(f"RedisSessionMemory created: ttl={self.config.session_ttl}s")

    @property
    def redis(self):
        """Get Redis client (lazy initialization)."""
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    self.config.redis_url,
                    max_connections=self.config.connection_pool_size,
                    decode_responses=True,
                )
                self._connected = True
                log.info(f"Redis connected: {self.config.redis_url}")
            except ImportError:
                log.warning("redis package not installed, using SQLite fallback")
                self._redis = _SQLiteStore()
            except Exception as e:
                log.error(f"Redis connection failed: {e}, using SQLite fallback")
                self._redis = _SQLiteStore()
        return self._redis

    def _session_key(self, session_id: str) -> str:
        """Generate Redis key for session."""
        return f"{self.config.key_prefix}{session_id}"

    async def save_message(
        self,
        session_id: str,
        message: BaseMessage,
    ) -> bool:
        """
        Save a message to session history.

        Args:
            session_id: Session identifier
            message: Message to save

        Returns:
            True if saved successfully
        """
        try:
            key = self._session_key(session_id)

            # Serialize message
            msg_data = self._serialize_message(message)
            msg_json = json.dumps(msg_data, ensure_ascii=False)

            # Try to save, fallback to in-memory on connection error
            try:
                await self.redis.lpush(key, msg_json)
                await self.redis.ltrim(key, 0, self.config.max_messages - 1)
                await self.redis.expire(key, self.config.session_ttl)
            except Exception as conn_err:
                # Connection failed, switch to in-memory fallback
                if not isinstance(self._redis, _SQLiteStore):
                    log.warning(f"Redis operation failed, switching to SQLite: {conn_err}")
                    self._redis = _SQLiteStore()
                    self._connected = False
                    # Retry with in-memory store
                    await self.redis.lpush(key, msg_json)
                    await self.redis.ltrim(key, 0, self.config.max_messages - 1)
                    await self.redis.expire(key, self.config.session_ttl)
                else:
                    raise conn_err

            log.debug(f"Message saved to session {session_id[:8]}...")
            return True

        except Exception as e:
            log.error(f"Failed to save message: {e}")
            return False

    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[BaseMessage]:
        """
        Get messages from session history.

        Args:
            session_id: Session identifier
            limit: Maximum messages to return (default from config)

        Returns:
            List of messages (newest first)
        """
        limit = limit or self.config.max_messages

        try:
            key = self._session_key(session_id)

            # Get messages from Redis
            msg_jsons = await self.redis.lrange(key, 0, limit - 1)

            # Deserialize messages
            messages = []
            for msg_json in msg_jsons:
                try:
                    msg_data = json.loads(msg_json)
                    message = self._deserialize_message(msg_data)
                    if message:
                        messages.append(message)
                except Exception as e:
                    log.warning(f"Failed to deserialize message: {e}")

            log.debug(f"Retrieved {len(messages)} messages from session {session_id[:8]}...")
            return messages

        except Exception as e:
            log.error(f"Failed to get messages: {e}")
            return []

    async def clear_session(self, session_id: str) -> bool:
        """Clear all messages for a session."""
        try:
            key = self._session_key(session_id)
            await self.redis.delete(key)
            log.info(f"Session cleared: {session_id[:8]}...")
            return True
        except Exception as e:
            log.error(f"Failed to clear session: {e}")
            return False

    async def session_exists(self, session_id: str) -> bool:
        """Check if session exists."""
        try:
            key = self._session_key(session_id)
            exists = await self.redis.exists(key)
            return exists > 0
        except Exception:
            return False

    async def get_session_info(self, session_id: str) -> Dict[str, Any]:
        """Get session metadata."""
        try:
            key = self._session_key(session_id)
            length = await self.redis.llen(key)
            ttl = await self.redis.ttl(key)

            return {
                "session_id": session_id,
                "message_count": length,
                "ttl_seconds": ttl,
                "exists": length > 0,
            }
        except Exception as e:
            return {"session_id": session_id, "error": str(e)}

    async def extend_session(self, session_id: str) -> bool:
        """Extend session TTL."""
        try:
            key = self._session_key(session_id)
            await self.redis.expire(key, self.config.session_ttl)
            return True
        except Exception:
            return False

    def _serialize_message(self, message: BaseMessage) -> Dict[str, Any]:
        """Serialize a message to JSON-compatible dict."""
        msg_type = type(message).__name__
        return {
            "type": msg_type,
            "content": message.content,
            "additional_kwargs": getattr(message, "additional_kwargs", {}),
        }

    def _deserialize_message(self, data: Dict[str, Any]) -> Optional[BaseMessage]:
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

    async def close(self):
        """Close Redis connection."""
        if self._redis is not None and hasattr(self._redis, "close"):
            await self._redis.close()
            log.debug("Redis connection closed")


class _SQLiteStore:
    """
    SQLite-based persistent fallback when Redis is unavailable.

    Data survives restarts, unlike the old in-memory store.
    Implements the same async interface that RedisSessionMemory expects.
    """

    def __init__(self, db_path: str = "./data/sessions.db"):
        import sqlite3
        import os

        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "  key TEXT NOT NULL,"
            "  idx INTEGER NOT NULL,"
            "  value TEXT NOT NULL,"
            "  PRIMARY KEY (key, idx)"
            ")"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ttls ("
            "  key TEXT PRIMARY KEY,"
            "  expires_at REAL NOT NULL"
            ")"
        )
        self._conn.commit()
        log.info(f"SQLite session store initialized: {db_path}")

    def _cleanup_expired(self, key: str) -> bool:
        """Remove key if expired. Returns True if key was expired."""
        with self._lock:
            row = self._conn.execute(
                "SELECT expires_at FROM ttls WHERE key = ?", (key,)
            ).fetchone()
            if row and row[0] < time.time():
                self._conn.execute("DELETE FROM sessions WHERE key = ?", (key,))
                self._conn.execute("DELETE FROM ttls WHERE key = ?", (key,))
                self._conn.commit()
                return True
            return False

    async def lpush(self, key: str, value: str):
        with self._lock:
            self._cleanup_expired(key)
            self._conn.execute(
                "UPDATE sessions SET idx = idx + 1 WHERE key = ?", (key,)
            )
            self._conn.execute(
                "INSERT INTO sessions (key, idx, value) VALUES (?, 0, ?)",
                (key, value),
            )
            self._conn.commit()

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        with self._lock:
            if self._cleanup_expired(key):
                return []
            rows = self._conn.execute(
                "SELECT value FROM sessions WHERE key = ? ORDER BY idx LIMIT ? OFFSET ?",
                (key, end - start + 1, start),
            ).fetchall()
            return [r[0] for r in rows]

    async def ltrim(self, key: str, start: int, end: int):
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

    async def llen(self, key: str) -> int:
        with self._lock:
            if self._cleanup_expired(key):
                return 0
            row = self._conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else 0

    async def delete(self, key: str):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE key = ?", (key,))
            self._conn.execute("DELETE FROM ttls WHERE key = ?", (key,))
            self._conn.commit()

    async def exists(self, key: str) -> int:
        with self._lock:
            if self._cleanup_expired(key):
                return 0
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
            return 1 if row else 0

    async def expire(self, key: str, seconds: int):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO ttls (key, expires_at) VALUES (?, ?)",
                (key, time.time() + seconds),
            )
            self._conn.commit()

    async def ttl(self, key: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT expires_at FROM ttls WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return -1
            remaining = row[0] - time.time()
            return max(0, int(remaining))

    async def close(self):
        if self._conn:
            self._conn.close()


# Module-level instance (lazy loaded)
_memory_instance: Optional[RedisSessionMemory] = None


def get_session_memory(config: Optional[SessionConfig] = None) -> RedisSessionMemory:
    """Get or create session memory instance."""
    global _memory_instance

    if _memory_instance is None or config is not None:
        _memory_instance = RedisSessionMemory(config=config)
        log.debug("Created new RedisSessionMemory instance")

    return _memory_instance