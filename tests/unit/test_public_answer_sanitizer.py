"""Permanent regressions for public answer sanitizing and stream safety."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage


def _filter_chunks(chunks: list[str]) -> tuple[str, object]:
    from utils.think_tag_utils import IncrementalThinkFilter

    parser = IncrementalThinkFilter()
    output = "".join(parser.push(chunk) for chunk in chunks)
    output += parser.finish()
    return output, parser


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["普通回答"], "普通回答"),
        (["前缀<think>SECRET</think>后缀"], "前缀后缀"),
        (["前缀<thi", "nk>SECRET</thi", "nk   >后缀"], "前缀后缀"),
        (["A<THINK mode='deep'>x<think>y</think>z</THINK >B"], "AB"),
        (["公开<think>SECRET"], "公开"),
        (["公开<think data='", "x" * 300], "公开"),
        (["<thinkology>是普通文本</thinkology>"], "<thinkology>是普通文本</thinkology>"),
        (["普通文本<thi"], "普通文本<thi"),
    ],
)
def test_incremental_think_filter_is_fail_closed(chunks, expected):
    output, _ = _filter_chunks(chunks)
    assert output == expected
    assert "SECRET" not in output


def test_incremental_filter_matches_for_every_chunk_boundary():
    raw = "公开A<think reason='x'>SECRET</think   >公开B"
    for split in range(len(raw) + 1):
        output, _ = _filter_chunks([raw[:split], raw[split:]])
        assert output == "公开A公开B", split


def test_incremental_filter_has_bounded_buffer_and_one_finish():
    from utils.think_tag_utils import IncrementalThinkFilter

    parser = IncrementalThinkFilter(max_tag_chars=256)
    assert parser.push("公开<think " + "x" * 10_000) == "公开"
    assert parser.buffered_chars <= 256
    assert parser.finish() == ""
    assert parser.finish() == ""
    with pytest.raises(RuntimeError):
        parser.push("不得继续")


def test_whole_text_sanitizer_reuses_fail_closed_parser():
    from utils.think_tag_utils import sanitize_model_text

    assert sanitize_model_text("  <think>SECRET</think> 可展示答案  ") == "可展示答案"
    assert sanitize_model_text("<think>SECRET") == ""


def test_fast_stream_filters_reasoning_before_emitting_tokens(monkeypatch):
    import core.fast_mode as fast_mode

    monkeypatch.setenv("RETRIEVAL_WORKFLOW_ENABLED", "false")

    class Retriever:
        async def aretrieve(self, *args, **kwargs):
            return [Document(page_content="公开证据", metadata={"source": "doc"})]

    class Chain:
        async def astream(self, _values):
            for text in ("公开<thi", "nk>SECRET</think>", "回答"):
                yield type("Chunk", (), {"content": text})()

    class Prompt:
        def __or__(self, _llm):
            return Chain()

    monkeypatch.setattr(
        "core.retrieval.hybrid_retriever.get_hybrid_retriever", lambda: Retriever()
    )
    monkeypatch.setattr("models.llm_models.get_llm", lambda: object())
    monkeypatch.setattr(fast_mode, "_stream_prompt", Prompt())

    async def collect():
        return [event async for event in fast_mode.fast_generate_stream("问题")]

    events = asyncio.run(collect())
    public = "".join(event.get("content", "") for event in events if event["type"] == "token")
    assert public == "公开回答"
    assert events[-1]["type"] == "done"
    assert events[-1]["full_response"] == public
    assert "SECRET" not in str(events)


def test_generate_skill_filters_reasoning_before_stream_writer(monkeypatch):
    from agent.skills.base import SkillContext
    from agent.skills.generate.skill import GenerateSkill
    from core.retrieval.evidence import documents_to_evidence

    class Chain:
        async def astream(self, _values):
            for text in ("公开<thi", "nk>SECRET</think>", "回答"):
                yield text

    async def no_faith(*_args):
        return None

    emitted = []
    skill = GenerateSkill()
    monkeypatch.setattr(skill, "_chain", Chain())
    monkeypatch.setattr(skill, "_agrounding_faithfulness", no_faith)
    monkeypatch.setattr("langgraph.config.get_stream_writer", lambda: emitted.append)
    context = SkillContext(
        messages=[HumanMessage(content="问题")],
        shared_state={
            "retrieval_evidence": documents_to_evidence(
                [Document(page_content="公开证据", metadata={"grade_score": 0.9})]
            )
        },
    )

    result = asyncio.run(skill.aexecute(context))
    public = "".join(event["content"] for event in emitted if event["type"] == "token")
    assert public == "公开回答"
    assert result.messages[-1].content == public
    assert "SECRET" not in str(emitted)


def test_degraded_response_does_not_echo_internal_error():
    from core.fallback.degradation import DegradationHandler

    answer = DegradationHandler().generate_degraded_response(
        "问题", "SECRET db://user:password@host"
    )
    assert "SECRET" not in answer.content
    assert "password" not in answer.content
