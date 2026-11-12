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
    assert "蓝色圆点" not in answer and "领取单模板" not in answer
    assert len(calls) == 1
    request = calls[0]
    assert request["messages"][0]["content"] == case["system_prompt"]
    assert request["max_tokens"] == 2048 and request["reasoning_effort"] == "none"
    assert request["temperature"] == 0 and request["top_p"] == 0.8
    schema = request["response_format"]["json_schema"]["schema"]
    clauses = schema["properties"]["clauses"]
    assert clauses["required"] == list(case["response"]["clauses"])
    assert set(clauses["properties"]) == set(clauses["required"])
    assert clauses["additionalProperties"] is False
    for slot in clauses["properties"].values():
        assert slot["type"] == "string"
        assert slot["enum"] == [
            "main_rule",
            "scope",
            "step",
            "record",
            "limit",
            "omit",
        ]
    assert "交付许可条件" not in answer


def test_annotation_preserves_event_context_sources_and_history():
    from core.procedure_generation import prepare_procedure

    case, inputs = fixture_input()
    inputs["context"] += "\nConversation: keep the current version."
    prepared = prepare_procedure(inputs)
    assert len(prepared["units"]) == case["expected_unit_count"]
    assert prepared["context"].endswith("Conversation: keep the current version.")
    replacement = next(u for u in prepared["units"] if "补齐后重新确认" in u["text"])
    assert "附件数量与清单不符时暂停交付" in replacement["text"]
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
        inputs["question"] = "Explain the step-by-step procedure in English."
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


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "length",
        "missing_clause",
        "extra_clause",
        "invalid_role",
        "no_lead",
        "altered_clause",
        "check_failed",
    ],
)
def test_procedure_publication_is_complete_checked_and_single_call(
    bounded_local_model, monkeypatch, failure
):
    from agent.guardrails.types import GuardrailAction
    from core.local_rag_generation import UNAVAILABLE_ANSWER
    from core.segmented_generation import stream_answer

    case, inputs = fixture_input()
    model, calls, output = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    clauses = case["response"]["clauses"]
    first, *_, last = clauses
    if failure == "missing_clause":
        clauses.pop(last)
    elif failure == "extra_clause":
        clauses["99:额外条款"] = "omit"
    elif failure == "invalid_role":
        clauses[first] = "unknown"
    elif failure == "no_lead":
        case["response"]["clauses"] = {k: "omit" for k in clauses}
    elif failure == "altered_clause":
        clauses[first.split(":", 1)[0] + ":错配的原文"] = clauses.pop(first)
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
    assert len(checked) == (
        0
        if failure
        in {
            "length",
            "missing_clause",
            "extra_clause",
            "invalid_role",
            "no_lead",
            "altered_clause",
        }
        else 1
    )
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
        "content": "This is the inventory record for another machine.",
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
        assert "inventory record" not in result["context"]
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
def test_procedure_default_and_opt_out_keep_request_contract(
    bounded_local_model, monkeypatch, flag
):
    from core.local_rag_generation import generation_chain

    case, inputs = fixture_input()
    if flag is None:
        monkeypatch.delenv("LOCAL_RAG_SEGMENTED", raising=False)
    else:
        monkeypatch.setenv("LOCAL_RAG_SEGMENTED", flag)
    model, calls, output = bounded_local_model
    if flag is None:
        output["text"] = json.dumps(case["response"])
    answer = generation_chain(model).invoke(inputs)
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    if flag is None:
        assert answer == case["expected_answer"]
        assert "clauses" in schema["properties"]
        assert calls[0]["temperature"] == 0
    else:
        assert "basis" in schema["properties"] and "ProcedureParagraph" not in schema["$defs"]
        assert calls[0]["temperature"] == 0.7
        assert inputs["context"] in calls[0]["messages"][-1]["content"]


@pytest.mark.parametrize("language", ["zh", "en"])
def test_constraint_placement_preserves_roles_and_mixed_boundaries(language):
    from langchain_core.messages import AIMessage

    from core.procedure_generation import render_procedure

    texts = (
        [
            "仅限馆内使用。",
            "双方签名后才能开始阅览。",
            "必须保留签名记录。",
            "检查失败须停机；户外规则未说明。",
            "库存须在月底盘点。",
        ]
        if language == "zh"
        else [
            "Indoor use only.",
            "Operation is allowed only after both signatures.",
            "Records must retain both signatures.",
            "If a check fails, stop until corrected; no outdoor rule is supplied.",
            "Inventory must be counted monthly.",
        ]
    )
    procedure = {
        "language": language,
        "units": [{"id": i, "source_id": 1, "text": t} for i, t in enumerate(texts, 1)],
    }
    message = AIMessage(
        content=json.dumps(
            {
                "clauses": {
                    f"{i}:{texts[i - 1]}": role
                    for i, role in enumerate(["scope", "step", "record", "limit", "omit"], 1)
                }
            }
        ),
        response_metadata={"finish_reason": "stop"},
    )
    answer = render_procedure(message, ["rules.txt"], procedure)
    lead = answer.split("\n\n**")[0]
    assert texts[0] in lead and texts[1] in lead
    assert texts[2] not in lead and texts[3] not in lead
    assert texts[4] not in answer and answer.count(texts[1]) == 1
    boundary = "条件与边界" if language == "zh" else "Conditions and boundaries"
    assert f"**{boundary}**\n\n{texts[3]}[rules.txt]" in answer
    message.content = json.dumps(
        {
            "clauses": {
                f"{i}:{texts[i - 1]}": role
                for i, role in enumerate(["step", "step", "record", "limit", "omit"], 1)
            }
        }
    )
    assert render_procedure(message, ["rules.txt"], procedure) == answer


@pytest.mark.parametrize(
    "question,eligible",
    [
        ("请说明物件如何领回。", False),
        ("请按办理流程说明物件如何领回。", True),
        ("Explain how a result is confirmed.", False),
        ("Explain the step-by-step procedure for confirming a result.", True),
        ("请说明交接流程，卡片房号不一致时如何处理。", False),
        ("请说明交接流程，卡片房号有误时如何处理。", True),
    ],
)
def test_procedure_route_requires_explicit_noncomparison_request(
    bounded_local_model, monkeypatch, question, eligible
):
    from core.segmented_generation import segmented_enabled

    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    model, calls, _ = bounded_local_model
    assert segmented_enabled(model, question, rewrite_count=0) is eligible
    assert calls == []


def test_english_procedure_keeps_original_evidence_and_generation(bounded_local_model, monkeypatch):
    from core.local_rag_generation import generation_chain
    from core.procedure_generation import select_procedure_evidence
    from core.retrieval.evidence import render_untrusted_evidence

    evidence = [
        {
            "source": "rules.txt",
            "content": "This procedure requires a signed receipt before use.",
            "metadata": {
                "rerank_score": 0.98,
                "rerank_applied": True,
                "rerank_output_space": "probability",
            },
        },
        {
            "source": "other.txt",
            "content": "另一份资料的操作记录。",
            "metadata": {
                "rerank_score": 0.001,
                "rerank_applied": True,
                "rerank_output_space": "probability",
            },
        },
    ]
    question = "Explain the step-by-step procedure for using this item."
    assert select_procedure_evidence(evidence, question) is evidence
    context = render_untrusted_evidence(evidence)
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    model, calls, _ = bounded_local_model
    generation_chain(model).invoke(
        {
            "question": question,
            "sources": ["rules.txt", "other.txt"],
            "evidence": evidence,
            "context": context,
        }
    )
    assert len(calls) == 1 and calls[0]["temperature"] == 0.7
    assert "basis" in calls[0]["response_format"]["json_schema"]["schema"]["properties"]
    assert context in calls[0]["messages"][-1]["content"]


@pytest.mark.parametrize("index", [0, 1])
def test_real_clause_classifications_exclude_unasked_facts(index):
    from langchain_core.messages import AIMessage

    from core.procedure_generation import render_procedure

    cases = json.loads((GOLDEN.parent / "procedure_relevance_regressions.json").read_text())
    case = cases[index]
    message = AIMessage(
        content=json.dumps(case["response"], ensure_ascii=False),
        response_metadata={"finish_reason": "stop"},
    )
    answer = render_procedure(message, case["sources"], {"units": case["units"], "language": "zh"})
    assert answer == case["expected_answer"]
    assert all(word not in answer for word in case["excluded"])
    message.content = json.dumps(
        {"clauses": dict(reversed(list(case["response"]["clauses"].items())))}
    )
    assert (
        render_procedure(message, case["sources"], {"units": case["units"], "language": "zh"})
        == answer
    )


@pytest.mark.parametrize("role", ["step", "record", "limit", "omit"])
def test_completed_prerequisite_moves_only_selected_step_to_lead(role):
    from langchain_core.messages import AIMessage

    from core.procedure_generation import render_procedure

    texts = ["适用于室内活动。", "核对与登记完成才启动。", "先查看刚才提交的人才申请表。"]
    units = [{"id": i, "source_id": 1, "text": text} for i, text in enumerate(texts, 1)]
    message = AIMessage(
        content=json.dumps(
            {
                "clauses": {
                    f"{u['id']}:{u['text']}": r for u, r in zip(units, ["scope", role, "step"])
                }
            }
        ),
        response_metadata={"finish_reason": "stop"},
    )
    answer = render_procedure(message, ["流程.txt"], {"units": units, "language": "zh"})
    lead = answer.split("\n\n**")[0]
    assert (texts[1] in lead) == (role == "step")
    assert (texts[1] in answer) == (role != "omit")
    assert texts[2] in answer and texts[2] not in lead


@pytest.mark.parametrize("asynchronous", [False, True])
def test_sentence_internal_reference_keeps_permission_separate(
    bounded_local_model, monkeypatch, asynchronous
):
    from core.local_rag_generation import generation_chain
    from core.procedure_generation import prepare_procedure
    from core.retrieval.evidence import render_untrusted_evidence

    case = json.loads((GOLDEN.parent / "procedure_relevance_regressions.json").read_text())[2]
    evidence = [
        {"source": name, "content": text, "title": ""}
        for name, text in zip(case["sources"], case["contexts"])
    ]
    inputs = {
        "question": case["question"],
        "sources": case["sources"],
        "evidence": evidence,
        "context": render_untrusted_evidence(evidence),
    }
    assert prepare_procedure(inputs)["units"] == case["units"]
    model, calls, output = bounded_local_model
    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    output["text"] = json.dumps(case["response"])
    chain = generation_chain(model)
    answer = asyncio.run(chain.ainvoke(inputs)) if asynchronous else chain.invoke(inputs)
    assert answer == case["expected_answer"]
    assert case["units"][3]["text"] in answer.split("\n\n**")[0]
    assert all(word not in answer for word in case["excluded"])
    assert len(calls) == 1
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["clauses"]["required"] == list(case["response"]["clauses"])
