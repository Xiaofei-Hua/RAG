import asyncio
import json

import pytest
from langchain_core.documents import Document
from openai import LengthFinishReasonError


@pytest.fixture
def local_model(bounded_local_model):
    return bounded_local_model


def test_fast_wire_has_real_budget_and_no_hidden_thinking(local_model):
    from core.fast_mode import _get_chain

    model, calls, _ = local_model
    answer = _get_chain(model).invoke(
        {
            "question": "多久校准？",
            "context": "[证据1] 来源=维护记录.txt\n120日",
            "sources": ["维护记录.txt"],
        }
    )
    assert "120" in answer
    assert len(calls) == 1
    assert calls[0].get("reasoning_effort") == "none"
    assert calls[0].get("max_tokens") == 2048
    assert calls[0].get("max_completion_tokens") == 2048
    assert calls[0]["temperature"] == 0.7
    assert calls[0]["top_p"] == 0.8


@pytest.mark.parametrize("text,finish", [("未完的答案", "length"), ("", "stop")])
def test_incomplete_generation_is_not_accepted_or_repeated(local_model, text, finish):
    from core.fast_mode import _get_chain

    model, calls, output = local_model
    output.update(text=text, finish=finish)
    with pytest.raises((RuntimeError, LengthFinishReasonError)):
        _get_chain(model).invoke(
            {"question": "周期？", "context": "120日", "sources": ["维护记录.txt"]}
        )
    assert len(calls) == 1


@pytest.mark.parametrize("entry", ["sync", "async", "stream"])
def test_fast_checks_before_any_delivery(local_model, monkeypatch, entry):
    from core import fast_mode
    from models import llm_models

    model, calls, output = local_model
    value = json.loads(output["text"])
    value["conclusion"]["text"] = "联系人电话13800138000，周期120日。"
    output["text"] = json.dumps(value, ensure_ascii=False)
    documents = [Document(page_content="周期120日", metadata={"source": "维护记录.txt"})]
    monkeypatch.setattr(llm_models, "get_llm", lambda: model)
    monkeypatch.setattr(fast_mode, "_retrieve_sync", lambda *a, **k: (documents, None))

    async def retrieve(*a, **k):
        return documents, None

    monkeypatch.setattr(fast_mode, "_retrieve_async", retrieve)
    if entry == "sync":
        answer = fast_mode.fast_generate("周期？").answer
    elif entry == "async":
        answer = asyncio.run(fast_mode.fast_generate_async("周期？")).answer
    else:

        async def collect():
            return [event async for event in fast_mode.fast_generate_stream("周期？")]

        events = asyncio.run(collect())
        tokens = "".join(e.get("content", "") for e in events if e["type"] == "token")
        answer = events[-1]["full_response"]
        assert tokens == answer
    assert "13800138000" not in answer
    assert "120" in answer
    assert len(calls) == 1


def test_bounded_skips_online_judge_without_faking_a_score(local_model, monkeypatch):
    import agent.eval.judge as judge
    from agent.guardrails.grounding_guardrail import check_grounding

    calls = []

    def unexpected():
        calls.append(True)
        raise AssertionError("online judge must not run")

    monkeypatch.setattr(judge, "get_judge", unexpected)
    result = check_grounding("建议每120个日历日校准一次。", ["建议每120个日历日校准一次。"])
    assert not calls
    assert result.faithfulness is None
    assert result.degraded


def test_legacy_keeps_its_original_model_policy(local_model, monkeypatch):
    from core.fast_mode import _get_chain

    monkeypatch.setenv("LOCAL_RAG_POLICY", "legacy")
    model, calls, _ = local_model
    _get_chain(model).invoke(
        {"question": "周期？", "context": "120日", "sources": ["维护记录.txt"]}
    )
    assert calls[0].get("reasoning_effort") is None
    assert calls[0]["temperature"] == 0


@pytest.mark.parametrize("source_ids", [[], [0], [2], [True]])
def test_invalid_citations_fail_the_whole_answer_without_retry(local_model, source_ids):
    from core.local_rag_generation import generation_chain

    model, calls, output = local_model
    value = json.loads(output["text"])
    value["basis"][0]["source_ids"] = source_ids
    output["text"] = json.dumps(value, ensure_ascii=False)
    with pytest.raises(ValueError):
        generation_chain(model).invoke(
            {"question": "周期？", "context": "120日", "sources": ["维护记录.txt"]}
        )
    assert len(calls) == 1


def test_citations_use_kept_evidence_indices_and_render_conclusion_first(local_model):
    from core.local_rag_generation import generation_chain

    model, calls, output = local_model
    value = {
        "basis": [{"text": "乙记录360分钟，甲记录5小时。", "source_ids": [3, 1]}],
        "conditions": [{"text": "两者测试负载不同。", "source_ids": [1, 3]}],
        "conclusion": {
            "text": "按记录乙的时间较长，不能据此断定同负载续航。",
            "source_ids": [3, 1],
        },
    }
    output["text"] = json.dumps(value, ensure_ascii=False)
    actual = generation_chain(model).invoke(
        {"question": "比较", "context": "资料", "sources": ["甲.txt", "甲.txt", "乙.txt"]}
    )
    from pathlib import Path

    expected = Path(__file__).parents[1] / "fixtures" / "bounded_answer.txt"
    assert actual == expected.read_text().rstrip()
    assert calls[0]["response_format"]["type"] == "json_schema"
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert schema["$defs"]["CitedParagraph"]["properties"]["source_ids"]["items"]["enum"] == [
        1,
        2,
        3,
    ]


@pytest.mark.parametrize("text", ["not JSON", '{"basis": [], "conditions": []}'])
def test_malformed_output_is_not_repaired_by_a_second_call(local_model, text):
    from core.local_rag_generation import generation_chain

    model, calls, output = local_model
    output["text"] = text
    with pytest.raises(ValueError):
        generation_chain(model).invoke(
            {"question": "周期？", "context": "120日", "sources": ["维护记录.txt"]}
        )
    assert len(calls) == 1


def test_bounded_prompt_golden(local_model):
    from pathlib import Path

    from core.local_rag_generation import generation_chain

    model, calls, _ = local_model
    generation_chain(model).invoke(
        {"question": "比较两份记录", "context": "资料", "sources": ["维护记录.txt"]}
    )
    expected = Path(__file__).parents[1] / "fixtures" / "bounded_generation_prompt.txt"
    assert calls[0]["messages"][0]["content"] == expected.read_text()
