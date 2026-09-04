"""In-process contracts consumed by the PHM knowledge center."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import AIMessage


def _events(response) -> list[dict]:
    events = []
    for line in response.read().decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def _done(events: list[dict]) -> dict:
    return next(event for event in events if event.get("type") == "done")


def test_sync_rag_and_fast_honor_include_sources_false(client):
    for mode in ("thinking", "fast"):
        response = client.post(
            "/api/chat",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": f"sources-{mode}",
                "mode": mode,
                "include_sources": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["sources"] == []
        assert body["metadata"]["source_count"] > 0


def test_stream_rag_and_fast_honor_include_sources_false(client, monkeypatch):
    async def fast_stream(*args, **kwargs):
        yield {"type": "token", "content": "快速回答"}
        yield {
            "type": "done",
            "full_response": "快速回答",
            "sources": [{"content": "证据", "source": "doc", "title": "文档"}],
        }

    import core.fast_mode as fast_mode

    monkeypatch.setattr(fast_mode, "fast_generate_stream", fast_stream)
    for mode in ("thinking", "fast"):
        with client.stream(
            "POST",
            "/api/chat/stream",
            json={
                "message": "git 合并冲突如何解决？",
                "session_id": f"stream-sources-{mode}",
                "mode": mode,
                "include_sources": False,
            },
        ) as response:
            done = _done(_events(response))
        assert done["sources"] == []
        assert done["metadata"]["source_count"] > 0


def test_public_metadata_is_v2_allowlist_and_persistence_is_observable(client):
    response = client.post(
        "/api/chat",
        json={"message": "git 合并冲突如何解决？", "session_id": "metadata-v2"},
    )
    assert response.status_code == 200
    metadata = response.json()["metadata"]
    assert metadata["contract_version"] == 2
    assert metadata["history_persisted"] is True
    assert "reasoning" not in metadata
    assert "intent_reasoning" not in metadata
    assert "error" not in metadata
    history = client.get("/api/chat/history/metadata-v2").json()
    assert [message["role"] for message in history["messages"]] == ["user", "assistant"]


def test_sync_empty_public_generation_is_502_and_is_not_persisted(
    client, fake_llm, fake_session_memory
):
    fake_llm._answer = "<think>SECRET"
    response = client.post(
        "/api/chat",
        json={"message": "今天心情不错", "session_id": "empty-sync"},
    )
    assert response.status_code == 502
    assert "SECRET" not in response.text
    assert fake_session_memory._store.get("empty-sync", []) == []


def test_stream_general_filters_cross_chunk_reasoning(client, monkeypatch):
    class StreamLLM:
        async def astream(self, messages):
            for content in ("公开<thi", "nk>SECRET</think>", "回答"):
                yield AIMessage(content=content)

    import models.llm_models as llm_models

    monkeypatch.setattr(llm_models, "get_llm", lambda: StreamLLM())
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "今天心情不错", "session_id": "stream-filter"},
    ) as response:
        events = _events(response)
    public = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert public == "公开回答"
    assert _done(events)["full_response"] == public
    assert "SECRET" not in json.dumps(events, ensure_ascii=False)


def test_stream_empty_public_generation_emits_error_without_done(client, monkeypatch):
    class StreamLLM:
        async def astream(self, messages):
            yield AIMessage(content="<think>SECRET")

    import models.llm_models as llm_models

    monkeypatch.setattr(llm_models, "get_llm", lambda: StreamLLM())
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "今天心情不错", "session_id": "stream-empty"},
    ) as response:
        events = _events(response)
    assert [event["type"] for event in events].count("error") == 1
    assert not any(event["type"] == "done" for event in events)
    assert "SECRET" not in json.dumps(events, ensure_ascii=False)


def test_rag_public_prefix_is_reconciled_with_final_snapshot(client, fake_harness, monkeypatch):
    async def stream(*args, **kwargs):
        yield ("custom", {"type": "token", "content": "<think>SECRET</think>答"})
        yield (
            "updates",
            {"generate": {"messages": [AIMessage(content="答案")]}, "shared_state": {}},
        )

    monkeypatch.setattr(fake_harness, "astream", stream)
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "git 合并冲突如何解决？", "session_id": "rag-prefix"},
    ) as response:
        events = _events(response)
    public = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert public == "答案"
    assert _done(events)["full_response"] == "答案"
    assert "SECRET" not in json.dumps(events, ensure_ascii=False)


def test_rag_custom_snapshot_conflict_is_error_not_silent_success(
    client, fake_harness, monkeypatch
):
    async def stream(*args, **kwargs):
        yield ("custom", {"type": "token", "content": "旧答案"})
        yield (
            "updates",
            {"generate": {"messages": [AIMessage(content="新答案")]}, "shared_state": {}},
        )

    monkeypatch.setattr(fake_harness, "astream", stream)
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"message": "git 合并冲突如何解决？", "session_id": "rag-conflict"},
    ) as response:
        events = _events(response)
    assert any(event["type"] == "error" for event in events)
    assert not any(event["type"] == "done" for event in events)


def test_history_distinguishes_complete_incomplete_and_unavailable(
    client, fake_session_memory, monkeypatch
):
    response = client.get("/api/chat/history/real-empty")
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == 2
    assert body["complete"] is True
    assert body["degraded"] is False

    async def incomplete(*args, **kwargs):
        return SimpleNamespace(
            messages=[], available=True, complete=False, degraded=True, backend="fallback"
        )

    monkeypatch.setattr(fake_session_memory, "read_messages", incomplete)
    response = client.get("/api/chat/history/incomplete")
    assert response.status_code == 200
    assert response.json()["complete"] is False
    assert response.json()["degraded"] is True

    async def unavailable(*args, **kwargs):
        return SimpleNamespace(
            messages=[], available=False, complete=False, degraded=True, backend="unavailable"
        )

    monkeypatch.setattr(fake_session_memory, "read_messages", unavailable)
    response = client.get("/api/chat/history/unavailable")
    assert response.status_code == 503


def test_history_persistence_false_and_unknown_are_not_reported_as_success(
    client, fake_session_memory, monkeypatch
):
    for persisted in (False, None):
        async def save_exchange(*args, **kwargs):
            return SimpleNamespace(
                persisted=persisted,
                backend="fake",
                degraded=True,
                exchange_id="exchange",
            )

        monkeypatch.setattr(fake_session_memory, "save_exchange", save_exchange)
        response = client.post(
            "/api/chat",
            json={"message": "你是谁", "session_id": f"persist-{persisted}"},
        )
        assert response.status_code == 200
        assert response.json()["metadata"]["history_persisted"] is persisted


def test_duplicate_feedback_returns_original_id_and_runs_side_effect_once(
    client, monkeypatch
):
    calls = []

    def on_negative_feedback(**kwargs):
        calls.append(kwargs)

    import agent.eval.flywheel as flywheel

    monkeypatch.setattr(flywheel, "on_negative_feedback", on_negative_feedback)
    payload = {
        "session_id": "feedback-session",
        "message_id": "feedback-message",
        "feedback_type": "THUMBS_DOWN",
    }
    first = client.post("/api/feedback", json=payload)
    second = client.post("/api/feedback", json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(calls) == 1
    listed = client.get("/api/feedback/feedback-session").json()["feedback"]
    assert len(listed) == 1


def test_circuit_breaker_degraded_response_never_echoes_exception(client, fake_harness, monkeypatch):
    from core.fallback.circuit_breaker import CircuitBreakerError

    async def boom(*args, **kwargs):
        raise CircuitBreakerError("SECRET db://user:password@host <think>hidden</think>")

    monkeypatch.setattr(fake_harness, "ainvoke", boom)
    response = client.post(
        "/api/chat",
        json={"message": "git 合并冲突如何解决？", "session_id": "safe-degraded"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["route"] == "degraded"
    assert body["metadata"]["degradation_code"] == "circuit_breaker_open"
    assert body["metadata"]["contract_version"] == 2
    assert body["metadata"]["intent_confidence"] is None
    assert "SECRET" not in response.text
    assert "password" not in response.text
    assert "reasoning" not in body["metadata"]
    assert "error" not in body["metadata"]


def test_every_successful_stream_route_captures_only_public_answer(
    client, fake_harness, monkeypatch
):
    captures = []

    def capture(**kwargs):
        captures.append(kwargs)

    import agent.eval.capture as capture_module

    monkeypatch.setattr(capture_module, "maybe_capture_inference", capture)

    class StreamLLM:
        async def astream(self, messages):
            yield AIMessage(content="<think>SECRET</think>公开回答")

    import models.llm_models as llm_models

    monkeypatch.setattr(llm_models, "get_llm", lambda: StreamLLM())

    async def fast_stream(*args, **kwargs):
        yield {"type": "token", "content": "<think>SECRET</think>快速回答"}
        yield {"type": "done", "full_response": "快速回答", "sources": []}

    import core.fast_mode as fast_mode

    monkeypatch.setattr(fast_mode, "fast_generate_stream", fast_stream)

    requests = [
        {"message": "你是谁", "mode": "thinking"},
        {"message": "今天天气不错", "mode": "thinking"},
        {"message": "快速检查", "mode": "fast"},
        {"message": "git 合并冲突如何解决？", "mode": "thinking"},
    ]
    for index, body in enumerate(requests):
        body["session_id"] = f"capture-{index}"
        with client.stream("POST", "/api/chat/stream", json=body) as response:
            assert any(event["type"] == "done" for event in _events(response))

    from core.fallback.circuit_breaker import CircuitBreakerError

    async def boom(*args, **kwargs):
        raise CircuitBreakerError("SECRET")
        yield None

    monkeypatch.setattr(fake_harness, "astream", boom)
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "message": "git 合并冲突再次检查",
            "session_id": "capture-degraded",
            "mode": "thinking",
        },
    ) as response:
        assert any(event["type"] == "done" for event in _events(response))

    assert [item["route"] for item in captures] == [
        "general_chat",
        "general_chat",
        "fast",
        "rag",
        "degraded",
    ]
    assert all(item["reasoning"] == "" for item in captures)
    assert "SECRET" not in json.dumps(captures, ensure_ascii=False, default=str)
