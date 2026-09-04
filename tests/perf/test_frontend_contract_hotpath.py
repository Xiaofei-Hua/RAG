"""Executable hot-path contracts for the public frontend protocol."""

from __future__ import annotations

import asyncio
import threading

from langchain_core.messages import AIMessage, HumanMessage


def test_reasoning_filter_retains_constant_boundary_state():
    from utils.think_tag_utils import IncrementalThinkFilter

    parser = IncrementalThinkFilter(max_tag_chars=256)
    output = parser.push("公开<think data='" + "x" * 1_000_000)

    assert output == "公开"
    assert parser.buffered_chars <= 256
    assert parser.finish() == ""


def test_sqlite_save_keeps_loop_responsive_and_deadline_unknown_is_replay_safe(tmp_path):
    from core.memory.redis_memory import RedisSessionMemory, SessionConfig, _SQLiteStore

    async def exercise():
        store = _SQLiteStore(str(tmp_path / "sessions.db"))
        entered = threading.Event()
        release = threading.Event()
        completed = threading.Event()
        original = store._save_exchange_sync

        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test release deadline")
            try:
                return original(*args, **kwargs)
            finally:
                completed.set()

        store._save_exchange_sync = blocked
        memory = RedisSessionMemory(
            config=SessionConfig(operation_timeout_seconds=0.01),
            redis_client=store,
            sqlite_store=store,
        )
        pending = asyncio.create_task(
            memory.save_exchange(
                "session-1",
                HumanMessage(content="问题"),
                AIMessage(content="回答"),
                exchange_id="stable-exchange",
            )
        )
        assert await asyncio.to_thread(entered.wait, 5)

        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=1)

        result = await pending
        assert result.persisted is None
        release.set()
        assert await asyncio.to_thread(completed.wait, 5)

        replay = await memory.save_exchange(
            "session-1",
            HumanMessage(content="问题"),
            AIMessage(content="回答"),
            exchange_id="stable-exchange",
        )
        read = await memory.read_messages("session-1")
        await memory.close()
        return replay, read

    replay, read = asyncio.run(exercise())
    assert replay.persisted is True
    assert len(read.messages) == 2
    assert {message.content for message in read.messages} == {"问题", "回答"}
