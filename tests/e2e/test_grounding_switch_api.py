"""Exercise the chat API with the real generation and output-check stages."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage


@pytest.fixture(autouse=True)
def close_inference_sampler():
    yield
    import agent.eval.inference_store as sampler

    with sampler._store_lock:
        if sampler._store is not None:
            sampler._store.close()
            sampler._store = None


@pytest.mark.parametrize("streaming", [False, True])
def test_disabled_grounding_chat_api(
    client, monkeypatch, fake_harness, fake_session_memory, streaming
):
    from agent.guardrails.manager import GuardrailManager
    from agent.skills.base import SkillContext
    from agent.skills.generate.skill import GenerateSkill
    from core.intent.classifier import IntentResult, IntentType
    from core.retrieval.evidence import documents_to_evidence

    monkeypatch.setenv("GROUNDING_CHECK_ENABLED", "false")
    getter = Mock(side_effect=AssertionError("disabled NLI was called"))
    monkeypatch.setattr("agent.eval.judge.get_judge", getter)
    monkeypatch.setattr("agent.guardrails.grounding_guardrail._guardrail", None)
    monkeypatch.setattr("langgraph.config.get_stream_writer", lambda: lambda event: None)
    monkeypatch.setattr(
        "core.intent.classifier.get_intent_classifier",
        lambda: SimpleNamespace(
            aclassify=AsyncMock(
                return_value=IntentResult(intent=IntentType.RAG_QUERY, confidence=0.99)
            )
        ),
    )
    documents = [
        Document(page_content="超时应为 30 秒。", metadata={"source": "limits.md", "score": 0.9})
    ]
    calls, generated = [], []

    async def chunks(_values):
        calls.append("generate")
        yield "超时应为 30 秒。\n依据来源：《limits.md》。邮箱user@example.com。"

    async def invoke(query, **kwargs):
        skill = GenerateSkill(llm=SimpleNamespace())
        skill._chain = SimpleNamespace(astream=chunks)
        context = SkillContext(
            messages=[HumanMessage(content=query)],
            shared_state={
                "retrieval_evidence": documents_to_evidence(documents),
                "max_rerank_prob": 0.9,
                "intent_confidence": 0.99,
            },
        )
        result = await skill.aexecute(context)
        context.shared_state.update(result.state_updates["shared_state"])
        GuardrailManager().create_after_hook()("generate", context, result)
        generated.append(result)
        return {"messages": result.messages, "shared_state": context.shared_state}

    async def stream(query, **kwargs):
        result = await invoke(query, **kwargs)
        yield "custom", {"type": "token", "content": result["messages"][-1].content}
        yield "updates", {"generate": result}

    monkeypatch.setattr(fake_harness, "ainvoke", invoke)
    monkeypatch.setattr(fake_harness, "astream", stream)
    response = client.post(
        "/api/chat/stream" if streaming else "/api/chat",
        json={
            "message": "知识库规定的超时应为多少秒？",
            "mode": "thinking",
            "session_id": "grounding-switch",
        },
    )
    assert response.status_code == 200, response.text
    if streaming:
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        body = next(event for event in events if event["type"] == "done")["full_response"]
    else:
        body = response.json()["response"]
    assert "30" in body and "limits.md" in body
    assert "user@example.com" not in body
    assert calls == ["generate"]
    getter.assert_not_called()
    assert generated[0].metadata["grounding_faithfulness"] is None
    assert generated[0].metadata["confidence_degraded"] is True
    history = asyncio.run(fake_session_memory.get_messages("grounding-switch"))
    assert all("user@example.com" not in message.content for message in history)
