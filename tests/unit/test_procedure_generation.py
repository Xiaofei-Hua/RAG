"""Test source clauses and measured evidence eligibility before routing integration."""

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
