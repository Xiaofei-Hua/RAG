"""Preserve procedural evidence through one complete, checked selection."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

GOLDEN = Path(__file__).parents[1] / "fixtures/local_segmented_procedure.json"


def fixture_input():
    from core.retrieval.evidence import render_untrusted_evidence

    case = json.loads(GOLDEN.read_text())
    evidence = [
        {"source": name, "content": text, "title": ""}
        for name, text in zip(case["sources"], case["contexts"])
    ]
    return case, {
        "question": case["question"],
        "sources": case["sources"],
        "evidence": evidence,
        "context": render_untrusted_evidence(evidence),
    }


@pytest.mark.parametrize("asynchronous", [False, True])
def test_complete_selection_preserves_steps_and_request_contract(
    bounded_local_model, monkeypatch, asynchronous
):
    from core.local_rag_generation import generation_chain

    case, inputs = fixture_input()
    model, calls, output = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    output["text"] = json.dumps(case["response"])
    chain = generation_chain(model)
    answer = asyncio.run(chain.ainvoke(inputs)) if asynchronous else chain.invoke(inputs)
    assert answer == case["expected_answer"]
    assert "Packaging cartons" not in answer and "92 boxes" not in answer
    assert len(calls) == 1
    request = calls[0]
    assert request["messages"][0]["content"] == case["system_prompt"]
    assert request["max_tokens"] == 2048 and request["reasoning_effort"] == "none"
    assert request["temperature"] == 0 and request["top_p"] == 0.8
    schema = request["response_format"]["json_schema"]["schema"]
    assert schema["$defs"]["ProcedureParagraph"]["properties"]["clause_ids"]["items"][
        "enum"
    ] == list(range(1, case["expected_unit_count"] + 1))


def test_annotation_preserves_event_context_sources_and_history():
    from core.procedure_generation import prepare_procedure

    case, inputs = fixture_input()
    inputs["context"] += "\nConversation: keep the current version."
    prepared = prepare_procedure(inputs)
    assert len(prepared["units"]) == case["expected_unit_count"]
    assert prepared["context"].endswith("Conversation: keep the current version.")
    replacement = next(u for u in prepared["units"] if "Begin a fresh" in u["text"])
    assert "After replacing" in replacement["text"]
    inputs["evidence"][1]["source"] = inputs["sources"][0]
    inputs["sources"] = inputs["sources"][:1]
    from core.retrieval.evidence import render_untrusted_evidence

    inputs["context"] = render_untrusted_evidence(inputs["evidence"])
    assert {u["source_id"] for u in prepare_procedure(inputs)["units"]} == {1}


@pytest.mark.parametrize(
    "reason", ["cross_language", "missing_mapping", "missing_evidence", "history_only"]
)
def test_unsupported_procedure_uses_one_buffered_call(bounded_local_model, monkeypatch, reason):
    from core.local_rag_generation import generation_chain

    _, inputs = fixture_input()
    if reason == "cross_language":
        inputs["question"] = "请按操作步骤用中文说明。"
    elif reason == "missing_mapping":
        inputs["sources"] = ["other.txt"]
    elif reason == "missing_evidence":
        inputs.pop("evidence")
    else:
        inputs["context"] = "Conversation with no matching evidence block."
    model, calls, _ = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    generation_chain(model).invoke(inputs)
    assert len(calls) == 1
    assert "basis" in calls[0]["response_format"]["json_schema"]["schema"]["properties"]


@pytest.mark.parametrize("failure", [None, "length", "invalid_id", "check_failed"])
def test_procedure_publication_is_complete_checked_and_single_call(
    bounded_local_model, monkeypatch, failure
):
    from agent.guardrails.types import GuardrailAction
    from core.local_rag_generation import UNAVAILABLE_ANSWER
    from core.segmented_generation import stream_answer

    case, inputs = fixture_input()
    model, calls, output = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    if failure == "invalid_id":
        case["response"]["answer"][-1]["clause_ids"] = [0]
    output.update(
        text=json.dumps(case["response"]), finish="length" if failure == "length" else "stop"
    )
    checked = []

    def checker(text, *args, **kwargs):
        checked.append(text)
        if failure == "check_failed":
            raise RuntimeError("check unavailable")
        assert text == case["expected_answer"]
        return SimpleNamespace(action=GuardrailAction.ALLOW, sanitized_content=text)

    async def run():
        return [e async for e in stream_answer(model, inputs, checker, case["contexts"])]

    events = asyncio.run(run())
    assert len(calls) == 1
    assert [e["type"] for e in events] == ["token", "done"]
    assert events[0]["content"] == events[1]["full_response"]
    assert events[1]["generation_outcome"]["generation_complete"] == (failure is None)
    assert len(checked) == (0 if failure in {"length", "invalid_id"} else 1)
    if failure:
        assert events[0]["content"] == UNAVAILABLE_ANSWER
    else:
        assert events[0]["content"] == case["expected_answer"]


@pytest.mark.parametrize(
    "question",
    [
        "如何理解这个结果？",
        "How do cache replicas remain consistent?",
        "How can these results be interpreted?",
    ],
)
def test_explanations_keep_the_existing_generation_route(
    bounded_local_model, monkeypatch, question
):
    from core.local_rag_generation import generation_chain

    _, inputs = fixture_input()
    inputs["question"] = question
    model, calls, output = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    generation_chain(model).invoke(inputs)
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert "basis" in schema["properties"] and "ProcedureParagraph" not in schema["$defs"]


@pytest.mark.parametrize(
    "content",
    [
        "Le contrôle doit être effectué avant utilisation.",
        "检查资料：Before operation, check the reference sheet and keep failed records.",
    ],
)
def test_other_or_mixed_language_uses_buffered_generation(
    bounded_local_model, monkeypatch, content
):
    from core.local_rag_generation import generation_chain
    from core.retrieval.evidence import render_untrusted_evidence

    _, inputs = fixture_input()
    inputs["question"] = (
        "请按操作步骤说明。" if "检查资料" in content else "Give a step-by-step procedure."
    )
    inputs["evidence"] = [{"source": inputs["sources"][0], "content": content, "title": ""}]
    inputs["context"] = render_untrusted_evidence(inputs["evidence"])
    model, calls, _ = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    generation_chain(model).invoke(inputs)
    assert len(calls) == 1
    assert "basis" in calls[0]["response_format"]["json_schema"]["schema"]["properties"]


def test_chinese_procedure_keeps_event_boundaries():
    from core.procedure_generation import prepare_procedure
    from core.retrieval.evidence import render_untrusted_evidence

    evidence = [
        {
            "source": "流程.txt",
            "title": "",
            "content": "先检查样张。该次合格后开始计数。失败时停止操作。",
        }
    ]
    result = prepare_procedure(
        {
            "question": "请给操作步骤。",
            "sources": ["流程.txt"],
            "evidence": evidence,
            "context": render_untrusted_evidence(evidence),
        }
    )
    assert result["units"][0]["text"] == "先检查样张。 该次合格后开始计数。"
    assert result["units"][1]["text"] == "失败时停止操作。"


@pytest.mark.parametrize(
    "foreign_score,known,strong,admit",
    [
        (0.001, True, True, True),
        (0.5, True, True, False),
        (None, True, True, False),
        (0.001, False, True, False),
        (0.001, True, False, False),
    ],
)
def test_only_measured_weak_foreign_evidence_is_removed(foreign_score, known, strong, admit):
    from core.procedure_generation import prepare_procedure
    from core.retrieval.evidence import render_untrusted_evidence

    case, inputs = fixture_input()

    def metadata(score):
        return {"rerank_score": score, "rerank_applied": True, "rerank_output_space": "probability"}

    inputs["evidence"][0]["metadata"] = metadata(0.98 if strong else 0.7)
    foreign = {
        "source": "other.txt",
        "content": "另一台机器的库存记录。",
        "title": "",
        "metadata": metadata(foreign_score),
    }
    if not known:
        foreign["metadata"].pop("rerank_output_space")
    inputs["evidence"].append(foreign)
    inputs["sources"].append("other.txt")
    inputs["context"] = render_untrusted_evidence(inputs["evidence"])
    result = prepare_procedure(inputs)
    assert (result is not None) == admit
    if admit:
        assert len(result["units"]) == case["expected_unit_count"]
        assert "另一台机器的库存记录。" not in result["context"]
        assert {u["source_id"] for u in result["units"]} == {1, 2}


def test_reranker_marks_actual_probability_without_changing_scores():
    from langchain_core.documents import Document

    from core.retrieval.reranker import Reranker

    sigmoid = type("Sigmoid", (), {"__module__": "torch.nn.modules.activation"})
    model = SimpleNamespace(activation_fn=sigmoid(), predict=lambda *args, **kwargs: [0.98, 0.001])
    reranker = Reranker()
    reranker._model = model
    docs = [Document(page_content="relevant"), Document(page_content="unrelated")]
    result = reranker.rerank("query", docs)
    assert [d.metadata["rerank_score"] for d in result] == [0.98, 0.001]
    assert all(d.metadata["rerank_output_space"] == "probability" for d in result)
    assert all(
        "rerank_prob" not in d.metadata and "rerank_probability" not in d.metadata for d in result
    )
    model.activation_fn = None
    assert all("rerank_output_space" not in d.metadata for d in reranker.rerank("query", docs))


@pytest.mark.parametrize("flag", [None, "false"])
def test_procedure_default_and_opt_out_keep_original_generation(
    bounded_local_model, monkeypatch, flag
):
    from core.local_rag_generation import generation_chain

    _, inputs = fixture_input()
    if flag is None:
        monkeypatch.delenv("LOCAL_RAG_SEGMENTED", raising=False)
    else:
        monkeypatch.setenv("LOCAL_RAG_SEGMENTED", flag)
    model, calls, _ = bounded_local_model
    generation_chain(model).invoke(inputs)
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert "basis" in schema["properties"] and "ProcedureParagraph" not in schema["$defs"]
    assert calls[0]["temperature"] == 0.7
    assert inputs["context"] in calls[0]["messages"][-1]["content"]
