"""Checked paragraphs and incomplete outcomes survive every API boundary."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.documents import Document


@pytest.mark.parametrize("scenario", ["records", "procedure", "procedure_with_noise"])
@pytest.mark.parametrize("mode", ["fast", "thinking"])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("finish", ["stop", "length"])
def test_segmented_api_persists_completion(
    client, fake_session_memory, monkeypatch, bounded_local_model, mode, streaming, finish, scenario
):
    from agent.guardrails.manager import GuardrailManager
    from agent.harness import AgentHarness, HarnessConfig
    from core import fast_mode
    from core.intent.classifier import IntentClassifier

    model, calls, output = bounded_local_model
    is_procedure = scenario.startswith("procedure")
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    output.update(
        text=(Path(__file__).parents[1] / "fixtures/local_segmented_answer.json").read_text(),
        finish=finish,
    )
    procedure = json.loads(
        (Path(__file__).parents[1] / "fixtures/local_segmented_procedure.json").read_text()
    )
    value = procedure["response"] if is_procedure else json.loads(output["text"])
    if not is_procedure:
        value = {
            "basis": value["answer"][1:],
            "conditions": value["conditions"],
            "conclusion": value["answer"][0],
        }
        value["basis"][0]["text"] += "联系人电话13800138000。"
    output["text"] = json.dumps(value, ensure_ascii=False)
    docs = [
        Document(
            page_content=f"{name}温度下记录一秒",
            metadata={"source": name + ".txt", "rerank_prob": 0.9},
        )
        for name in ("A", "B")
    ]
    if is_procedure:
        docs = [
            Document(
                page_content=text.replace(
                    "Velora archival scanner", "Phone 13800138000 Velora archival scanner"
                ),
                metadata={"source": name, "rerank_prob": 0.9},
            )
            for name, text in zip(procedure["sources"], procedure["contexts"])
        ]
    if scenario == "procedure_with_noise":
        for doc in docs:
            doc.metadata.update(
                rerank_applied=True, rerank_score=0.98, rerank_output_space="probability"
            )
        docs.append(
            Document(
                page_content="另一台机器的无关操作记录。",
                metadata={
                    "source": "noise.txt",
                    "rerank_applied": True,
                    "rerank_score": 0.001,
                    "rerank_output_space": "probability",
                },
            )
        )
    result = SimpleNamespace(documents=docs, should_generate=True, diagnostics={"state": "accept"})
    workflow = SimpleNamespace(
        aretrieve=AsyncMock(return_value=result), retrieve=lambda *a, **k: result
    )
    monkeypatch.setattr("core.retrieval.workflow.get_retrieval_workflow", lambda: workflow)
    monkeypatch.setattr("models.llm_models.get_llm", lambda *a, **k: model)
    # 恢复真实Fast入口；client fixture原先注入固定答案。
    monkeypatch.setattr(fast_mode, "fast_generate_async", REAL_FAST)
    monkeypatch.setattr(
        "core.intent.classifier.get_intent_classifier", lambda: IntentClassifier(llm=model)
    )
    harness = AgentHarness(llm=model, config=HarnessConfig(use_memory=False))
    harness.register_defaults()
    harness.registry.get("retrieve")._workflow = workflow
    manager = GuardrailManager()
    harness.lifecycle.on_before_skill(manager.create_before_hook())
    harness.lifecycle.on_after_skill(manager.create_after_hook())
    monkeypatch.setattr("agent.harness.get_agent_harness", lambda *a, **k: harness)
    response = client.post(
        "/api/chat/stream" if streaming else "/api/chat",
        json={
            "message": procedure["question"] if is_procedure else "Explain these records.",
            "mode": mode,
            "session_id": "segment-api",
        },
    )
    assert response.status_code == 200, response.text
    if streaming:
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        data = next(e for e in events if e["type"] == "done")
        body = data["full_response"]
        assert "".join(e["content"] for e in events if e["type"] == "token") == body
    else:
        data = response.json()
        body = data["response"]
    assert data["metadata"]["generation_complete"] == (finish == "stop")
    assert "13800138000" not in body
    if finish == "stop":
        if is_procedure:
            assert "prepare the designated reference sheet" in body.lower()
            assert "keep failed-check records" in body
            assert "old head's result does not qualify" in body
            assert "92 boxes" not in body
            for source in procedure["sources"]:
                assert f"[{source}]" in body
        else:
            assert "相同" in body and "温度不同" in body and "[A.txt][B.txt]" in body
    saved = asyncio.run(fake_session_memory.get_messages("segment-api"))
    answer = next(m for m in saved if m.type == "ai")
    assert answer.content == body
    assert answer.additional_kwargs["generation_outcome"]["generation_complete"] == (
        finish == "stop"
    )
    history = client.get("/api/chat/history/segment-api").json()
    item = next(m for m in history["messages"] if m["role"] == "assistant")
    assert item["metadata"]["generation_complete"] == (finish == "stop")
    assert sum(c.get("response_format", {}).get("type") == "json_schema" for c in calls) == 1
    if is_procedure:
        generation = next(
            c for c in calls if c.get("response_format", {}).get("type") == "json_schema"
        )
        assert generation["messages"][0]["content"] == procedure["system_prompt"]
        if scenario == "procedure_with_noise":
            assert "noise.txt" not in generation["messages"][-1]["content"]
            assert "noise.txt" not in json.dumps(data.get("sources", []))
    if finish != "stop":
        assert data["metadata"].get("confidence") is None
    harness.close()


from core.fast_mode import fast_generate_async as REAL_FAST


@pytest.mark.parametrize("streaming", [False, True])
def test_general_fallback_does_not_save_old_generation_failure(
    client, fake_harness, fake_llm, fake_session_memory, monkeypatch, streaming
):
    from langchain_core.messages import AIMessage

    from api.routers import chat
    from core.intent.classifier import IntentResult, IntentType

    classifier = SimpleNamespace(
        aclassify=AsyncMock(return_value=IntentResult(intent=IntentType.RAG_QUERY, confidence=0.99))
    )
    monkeypatch.setattr("core.intent.classifier.get_intent_classifier", lambda: classifier)

    async def general_stream(*a, **k):
        yield AIMessage(content="通用回答")

    monkeypatch.setattr(fake_llm, "astream", general_stream, raising=False)

    state = {
        "messages": [AIMessage(content="")],
        "shared_state": {
            "fallback_general_chat": True,
            "generation_evidence": [],
            "generation_outcome": {
                "status": "unavailable",
                "generation_complete": False,
                "reason": "no_generation",
                "retryable": True,
            },
        },
    }
    monkeypatch.setattr(fake_harness, "ainvoke", AsyncMock(return_value=state))

    async def stream(*a, **k):
        yield "updates", {"generate": state}

    monkeypatch.setattr(fake_harness, "astream", stream)
    monkeypatch.setattr(
        chat, "_run_general_chat", AsyncMock(return_value=("通用回答", [], None, False, ""))
    )
    response = client.post(
        "/api/chat/stream" if streaming else "/api/chat",
        json={"message": "普通的技术说明", "session_id": "fallback-outcome"},
    )
    assert response.status_code == 200
    messages = asyncio.run(fake_session_memory.get_messages("fallback-outcome"))
    answer = next(m for m in messages if m.type == "ai")
    assert answer.additional_kwargs.get("generation_outcome") is None
