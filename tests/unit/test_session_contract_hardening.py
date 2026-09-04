"""Session persistence truthfulness and atomicity regressions."""

from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage


class _RedisShard:
    def __init__(self, rows=None, *, fail_read: bool = False):
        self.rows = list(rows or [])
        self.fail_read = fail_read
        self.eval_calls = []

    async def lrange(self, key, start, end):
        if self.fail_read:
            raise ConnectionError("redis unavailable SECRET")
        return self.rows[start : end + 1]

    async def eval(self, script, key_count, *args):
        self.eval_calls.append((script, key_count, args))
        return 1


def _message_json(kind: str, content: str, message_id: str, timestamp: float) -> str:
    return json.dumps(
        {
            "type": kind,
            "content": content,
            "additional_kwargs": {
                "_timestamp": timestamp,
                "_exchange_id": "exchange-1",
                "_message_id": message_id,
            },
        }
    )


def test_sqlite_exchange_is_atomic_and_physically_idempotent(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, _SQLiteStore

    async def exercise():
        store = _SQLiteStore(str(tmp_path / "sessions.db"))
        memory = RedisSessionMemory(redis_client=store, sqlite_store=store)
        first = await memory.save_exchange(
            "session-1",
            HumanMessage(content="问题"),
            AIMessage(content="回答"),
            exchange_id="exchange-1",
        )
        replay = await memory.save_exchange(
            "session-1",
            HumanMessage(content="问题"),
            AIMessage(content="回答"),
            exchange_id="exchange-1",
        )
        read = await memory.read_messages("session-1")
        await memory.close()
        return first, replay, read

    first, replay, read = asyncio.run(exercise())
    assert first.persisted is True
    assert replay.persisted is True
    assert [message.content for message in read.messages] == ["回答", "问题"]
    assert len(read.messages) == 2
    assert read.complete is True


def test_session_dual_read_merges_duplicate_exchange_and_orders_roles(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, _SQLiteStore

    assistant = _message_json("AIMessage", "回答", "exchange-1:assistant", 10.0)
    human = _message_json("HumanMessage", "问题", "exchange-1:user", 10.0)
    redis = _RedisShard([assistant, human])

    async def exercise():
        sqlite = _SQLiteStore(str(tmp_path / "sessions.db"))
        await sqlite.save_exchange("rag:session:session-1", human, assistant)
        memory = RedisSessionMemory(redis_client=redis, sqlite_store=sqlite)
        result = await memory.read_messages("session-1")
        await memory.close()
        return result

    result = asyncio.run(exercise())
    assert result.available is True
    assert result.complete is True
    assert result.degraded is False
    assert result.backend == "combined"
    assert [message.content for message in reversed(result.messages)] == ["问题", "回答"]


def test_session_single_readable_shard_is_incomplete_not_empty(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, _SQLiteStore

    async def exercise():
        sqlite = _SQLiteStore(str(tmp_path / "sessions.db"))
        memory = RedisSessionMemory(
            redis_client=_RedisShard(fail_read=True),
            sqlite_store=sqlite,
        )
        result = await memory.read_messages("session-1")
        await memory.close()
        return result

    result = asyncio.run(exercise())
    assert result.messages == []
    assert result.available is True
    assert result.complete is False
    assert result.degraded is True
    assert result.backend == "fallback"


def test_redis_exchange_uses_one_replay_safe_lua_command(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, _SQLiteStore

    redis = _RedisShard()

    async def exercise():
        sqlite = _SQLiteStore(str(tmp_path / "sessions.db"))
        memory = RedisSessionMemory(redis_client=redis, sqlite_store=sqlite)
        result = await memory.save_exchange(
            "session-1",
            HumanMessage(content="问题"),
            AIMessage(content="回答"),
            exchange_id="exchange-1",
        )
        await memory.close()
        return result

    result = asyncio.run(exercise())
    assert result.persisted is True
    assert len(redis.eval_calls) == 1
    script, key_count, args = redis.eval_calls[0]
    assert key_count == 2
    assert all(command in script for command in ("LRANGE", "LPUSH", "LTRIM"))
    assert "exchange-1:user" in args
    assert "exchange-1:assistant" in args


def test_odd_retention_limit_never_keeps_half_an_exchange(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, SessionConfig, _SQLiteStore

    async def exercise():
        store = _SQLiteStore(str(tmp_path / "sessions.db"))
        memory = RedisSessionMemory(
            config=SessionConfig(max_messages=3),
            redis_client=store,
            sqlite_store=store,
        )
        for index in range(2):
            await memory.save_exchange(
                "session-1",
                HumanMessage(content=f"问题{index}"),
                AIMessage(content=f"回答{index}"),
                exchange_id=f"exchange-{index}",
            )
        result = await memory.read_messages("session-1")
        await memory.close()
        return result

    result = asyncio.run(exercise())
    assert [message.content for message in reversed(result.messages)] == ["问题1", "回答1"]


def test_corrupt_history_row_marks_read_incomplete(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, _SQLiteStore

    async def exercise():
        store = _SQLiteStore(str(tmp_path / "sessions.db"))
        await store.lpush("rag:session:session-1", "not-json")
        memory = RedisSessionMemory(redis_client=store, sqlite_store=store)
        result = await memory.read_messages("session-1")
        await memory.close()
        return result

    result = asyncio.run(exercise())
    assert result.available is True
    assert result.messages == []
    assert result.complete is False
    assert result.degraded is True
