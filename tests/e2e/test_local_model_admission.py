"""Admission failure is terminal at public boundaries."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.parametrize("streaming", [False, True])
def test_full_queue_stops_intent_without_model_call(
    client, monkeypatch, bounded_local_model, streaming
):
    from core.intent.classifier import IntentClassifier
    from models import local_model_queue
    from models.scheduled_chat_model import ScheduledChatOpenAI

    original, calls, _ = bounded_local_model
    model = ScheduledChatOpenAI(
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        max_retries=0,
        http_client=original.http_client,
        http_async_client=original.http_async_client,
    )
    queue = local_model_queue.LocalModelQueue(max_waiting=0)
    ticket = queue.submit(False, lambda: None)
    monkeypatch.setattr(local_model_queue, "_model_queue", queue)
    monkeypatch.setenv("LOCAL_LLM_SCHEDULER", "fair")
    monkeypatch.setattr(
        "core.intent.classifier.get_intent_classifier", lambda: IntentClassifier(llm=model)
    )
    response = client.post(
        "/api/chat/stream" if streaming else "/api/chat",
        json={"message": "Which calibration interval applies to this device?", "mode": "thinking"},
    )
    queue.release(ticket)
    assert response.status_code == 200
    if streaming:
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        result = next(event for event in events if event["type"] == "done")
        assert (
            "".join(e["content"] for e in events if e["type"] == "token") == result["full_response"]
        )
    else:
        result = response.json()
    meta = result["metadata"]
    assert meta["generation_complete"] is False
    assert meta["reason"] == "queue_full" and meta["retryable"] is True
    assert meta["confidence"] is None and meta["confidence_degraded"] is True
    assert calls == []


@pytest.mark.parametrize("entry", ["invoke", "ainvoke", "stream", "astream"])
def test_graph_busy_replaces_previous_success(monkeypatch, entry):
    from agent.harness import AgentHarness, HarnessConfig
    from agent.harness.orchestrator import _build_request_shared_state
    from models.local_model_queue import ModelBusyError

    harness = AgentHarness(config=HarnessConfig(use_memory=False))
    graph = Mock()
    graph.invoke.side_effect = ModelBusyError("queue_timeout")
    graph.ainvoke = AsyncMock(side_effect=ModelBusyError("queue_timeout"))
    graph.stream.side_effect = ModelBusyError("queue_timeout")

    async def failed(*args, **kwargs):
        raise ModelBusyError("queue_timeout")
        yield

    graph.astream = failed
    monkeypatch.setattr(type(harness), "graph", property(lambda self: graph))
    monkeypatch.setattr(harness, "astart", AsyncMock())
    old = {
        "generation_outcome": {"generation_complete": True},
        "model_queue_outcome": {"status": "old"},
    }
    state = _build_request_shared_state(old)
    assert state["generation_outcome"] is None and state["model_queue_outcome"] is None

    async def run():
        if entry == "astream":
            return [event async for event in harness.astream("校准周期", shared_state=old)][-1]
        return await harness.ainvoke("校准周期", mode="thinking", shared_state=old)

    if entry in {"ainvoke", "astream"}:
        result = asyncio.run(run())
    elif entry == "stream":
        result = list(harness.stream("校准周期", shared_state=old))[-1]
    else:
        result = harness.invoke("校准周期", mode="thinking", shared_state=old)
    assert result["shared_state"]["generation_outcome"] is None
    assert result["shared_state"]["model_queue_outcome"]["reason"] == "queue_timeout"
    assert "繁忙" in result["messages"][-1].content
    harness.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_actual_graph_generation_busy_is_terminal(
    client, monkeypatch, bounded_local_model, streaming
):
    from types import SimpleNamespace

    from langchain_core.documents import Document

    from agent.guardrails.manager import GuardrailManager
    from agent.harness import AgentHarness, HarnessConfig
    from core.intent.classifier import IntentClassifier
    from models import local_model_queue
    from models.scheduled_chat_model import ScheduledChatOpenAI

    original, calls, _ = bounded_local_model
    model = ScheduledChatOpenAI(
        model="qwen3.5:9b",
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        max_retries=0,
        http_client=original.http_client,
        http_async_client=original.http_async_client,
    )
    queue = local_model_queue.LocalModelQueue()
    submit = queue.submit
    rejected = []

    def admit(short, wake):
        if not short:
            rejected.append(True)
            raise local_model_queue.ModelBusyError("queue_full")
        return submit(short, wake)

    monkeypatch.setattr(queue, "submit", admit)
    monkeypatch.setattr(local_model_queue, "_model_queue", queue)
    monkeypatch.setenv("LOCAL_LLM_SCHEDULER", "fair")
    docs = [
        Document(
            page_content="正常连续使用周期120日。",
            metadata={"source": "维护记录.txt", "rerank_prob": 0.9},
        )
    ]
    result = SimpleNamespace(documents=docs, should_generate=True, diagnostics={"state": "accept"})
    workflow = SimpleNamespace(
        aretrieve=AsyncMock(return_value=result), retrieve=lambda *a, **k: result
    )
    monkeypatch.setattr("core.retrieval.workflow.get_retrieval_workflow", lambda: workflow)
    monkeypatch.setattr("models.llm_models.get_llm", lambda *a, **k: model)
    monkeypatch.setattr(
        "core.intent.classifier.get_intent_classifier", lambda: IntentClassifier(llm=model)
    )
    harness = AgentHarness(llm=model, config=HarnessConfig(use_memory=False))
    harness.register_defaults()
    harness.registry.get("retrieve")._workflow = workflow
    harness.lifecycle.on_after_skill(GuardrailManager().create_after_hook())
    monkeypatch.setattr("agent.harness.get_agent_harness", lambda *a, **k: harness)
    response = client.post(
        "/api/chat/stream" if streaming else "/api/chat",
        json={"message": "Which calibration interval applies to this device?", "mode": "thinking"},
    )
    if streaming:
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        data = next(event for event in events if event["type"] == "done")
    else:
        data = response.json()
    assert data["metadata"]["generation_complete"] is False
    assert data["metadata"]["reason"] == "queue_full"
    assert rejected == [True]
    assert calls and all(
        call.get("response_format", {}).get("type") != "json_schema" for call in calls
    )
    harness.close()
