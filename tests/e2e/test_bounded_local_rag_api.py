"""Exercise actual graph generation and publication through the chat API."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document

from core.fast_mode import fast_generate_async as real_fast_generate_async


@pytest.fixture(autouse=True)
def close_inference_store():
    yield
    import agent.eval.inference_store as sampler

    with sampler._store_lock:
        if sampler._store is not None:
            sampler._store.close()
            sampler._store = None


@pytest.mark.parametrize("mode", ["fast", "thinking"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("check_fails", [False, True])
def test_bounded_api_checks_before_publishing(
    client,
    monkeypatch,
    fake_session_memory,
    bounded_local_model,
    mode,
    streaming,
    check_fails,
):
    from agent.guardrails.manager import GuardrailManager
    from agent.harness import AgentHarness, HarnessConfig
    from core import fast_mode
    from core.intent.classifier import IntentClassifier

    model, calls, output = bounded_local_model
    value = json.loads(output["text"])
    value["conclusion"]["text"] = "周期120日，联系人电话13800138000。"
    output["text"] = json.dumps(value, ensure_ascii=False)
    documents = [
        Document(
            page_content="正常连续使用周期120日。",
            metadata={"source": "维护记录.txt", "rerank_prob": 0.9},
        )
    ]
    diagnostics = {"state": "accept"}
    retrieval = SimpleNamespace(documents=documents, should_generate=True, diagnostics=diagnostics)
    monkeypatch.setattr(
        "core.retrieval.workflow.get_retrieval_workflow",
        lambda: SimpleNamespace(
            aretrieve=AsyncMock(return_value=retrieval), retrieve=lambda *a, **k: retrieval
        ),
    )
    monkeypatch.setattr("models.llm_models.get_llm", lambda *a, **k: model)
    monkeypatch.setattr(fast_mode, "fast_generate_async", real_fast_generate_async)
    monkeypatch.setattr(
        "core.intent.classifier.get_intent_classifier", lambda: IntentClassifier(llm=model)
    )
    getter = Mock(side_effect=AssertionError("online judge called"))
    monkeypatch.setattr("agent.eval.judge.get_judge", getter)
    harness = AgentHarness(llm=model, config=HarnessConfig(use_memory=False))
    harness.register_defaults()
    from core.retrieval.workflow import get_retrieval_workflow

    harness.registry.get("retrieve")._workflow = get_retrieval_workflow()
    manager = GuardrailManager()
    harness.lifecycle.on_after_skill(manager.create_after_hook())
    monkeypatch.setattr("agent.harness.get_agent_harness", lambda *a, **k: harness)
    if check_fails:
        monkeypatch.setattr(
            GuardrailManager, "check_output", Mock(side_effect=RuntimeError("broken"))
        )
    response = client.post(
        "/api/chat/stream" if streaming else "/api/chat",
        json={
            "message": "Which calibration interval applies to this device?",
            "mode": mode,
            "session_id": "bounded-api",
        },
    )
    assert response.status_code == 200, response.text
    if streaming:
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        done = next(event for event in events if event["type"] == "done")
        body, metadata = done["full_response"], done["metadata"]
        tokens = "".join(event["content"] for event in events if event["type"] == "token")
        assert tokens == body
    else:
        body, metadata = response.json()["response"], response.json()["metadata"]
    assert "13800138000" not in body
    if check_fails:
        assert "输出检查" in body
    else:
        assert "120" in body and "维护记录.txt" in body
    assert metadata["grounding_faithfulness"] is None
    assert metadata["confidence_degraded"] is True
    assert sum(c.get("response_format", {}).get("type") == "json_schema" for c in calls) == 1
    getter.assert_not_called()
    history = asyncio.run(fake_session_memory.get_messages("bounded-api"))
    assert all("13800138000" not in message.content for message in history)
    harness.close()
