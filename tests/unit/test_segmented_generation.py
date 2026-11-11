"""Only complete, checked answer paragraphs may be released."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessageChunk

GOLDEN = Path(__file__).parents[1] / "fixtures/local_segmented_answer.json"


@pytest.mark.parametrize("width", [1, 7, 31, 4096])
def test_incremental_objects_require_real_delimiters(width):
    from core.segmented_generation import ParagraphParser

    text = GOLDEN.read_text()
    parser = ParagraphParser(["A.txt", "B.txt"])
    rendered = []
    for offset in range(0, len(text), width):
        rendered.extend(parser.feed(text[offset : offset + width]))
    parser.finish("stop")
    assert len(rendered) == 2
    assert "相同" in rendered[0] and "温度不同" in rendered[0]
    assert rendered[0].endswith("[A.txt][B.txt]")


def test_half_object_or_missing_delimiter_never_releases():
    from core.segmented_generation import ParagraphParser

    text = GOLDEN.read_text()
    first_end = text.index("},{", text.index('"answer"')) + 1
    parser = ParagraphParser(["A.txt", "B.txt"])
    assert parser.feed(text[:first_end]) == []
    assert len(parser.feed(",")) == 1
    with pytest.raises(ValueError):
        parser.finish("length")


@pytest.mark.parametrize("replacement", [0, 3, "1"])
def test_invalid_source_stops_publication(replacement):
    from core.segmented_generation import ParagraphParser

    value = json.loads(GOLDEN.read_text())
    value["answer"][0]["source_ids"] = [replacement]
    with pytest.raises(ValueError):
        ParagraphParser(["A.txt", "B.txt"]).feed(json.dumps(value))


def test_lead_precedes_finish_and_failure_keeps_only_checked_prefix(monkeypatch):
    from agent.guardrails.types import GuardrailAction
    from core import segmented_generation as segmented

    async def run():
        text = GOLDEN.read_text()
        end = text.index("},{", text.index('"answer"')) + 2
        blocked, proceed = asyncio.Event(), asyncio.Event()
        closed = []

        class Model:
            async def astream(self, *a, **kw):
                try:
                    yield AIMessageChunk(content=text[:end])
                    blocked.set()
                    await proceed.wait()
                    yield AIMessageChunk(content='{"text":"未完成电话13800138000')
                    yield AIMessageChunk(content="", response_metadata={"finish_reason": "length"})
                finally:
                    closed.append(True)

        monkeypatch.setattr(segmented, "request_model", lambda *a, **k: Model())

        def checker(text, *a, **k):
            return SimpleNamespace(action=GuardrailAction.ALLOW, sanitized_content=text)

        stream = segmented.stream_answer(
            None,
            {"sources": ["A.txt", "B.txt"], "context": "事实", "question": "比较"},
            checker,
            [],
        )
        first = await anext(stream)
        assert first["type"] == "token" and "相同" in first["content"]
        assert not blocked.is_set()
        proceed.set()
        rest = [event async for event in stream]
        done = rest[-1]
        assert done["generation_outcome"]["generation_complete"] is False
        assert done["full_response"].startswith(first["content"])
        assert "13800138000" not in done["full_response"]
        assert (
            first["content"] + "".join(e["content"] for e in rest if e["type"] == "token")
            == done["full_response"]
        )
        assert closed == [True]

    asyncio.run(run())


def test_checker_cannot_rewrite_an_already_published_prefix():
    from agent.guardrails.types import GuardrailAction
    from core.segmented_generation import CheckedParagraphs

    calls = []

    def checker(text, *a, **kw):
        calls.append(text)
        return SimpleNamespace(
            action=GuardrailAction.SANITIZE, sanitized_content=text if len(calls) == 1 else "改写"
        )

    publisher = CheckedParagraphs(checker, ["A.txt"], [])
    assert publisher.append("首段[A.txt]") == "首段[A.txt]"
    with pytest.raises(ValueError):
        publisher.append("后段[A.txt]")
    assert publisher.text == "首段[A.txt]"


def test_actual_sdk_stream_matches_complete_json(bounded_local_model):
    from core.segmented_generation import request_model

    model, calls, output = bounded_local_model
    output["text"] = GOLDEN.read_text()

    async def run():
        return [
            chunk
            async for chunk in request_model(model, ["A.txt", "B.txt"]).astream(
                {"question": "Compare", "context": "facts"}
            )
        ]

    chunks = asyncio.run(run())
    assert "".join(chunk.content for chunk in chunks) == output["text"]
    assert any(chunk.response_metadata.get("finish_reason") == "stop" for chunk in chunks)


@pytest.mark.parametrize("finish", [None, "tool_calls", "length", "content_filter"])
def test_nonstream_requires_same_stop_contract(finish):
    from langchain_core.messages import AIMessage

    from core.local_rag_generation import render_answer

    with pytest.raises((ValueError, RuntimeError)):
        render_answer(
            AIMessage(content=GOLDEN.read_text(), response_metadata={"finish_reason": finish}),
            ["A.txt", "B.txt"],
            segmented=True,
        )


@pytest.mark.parametrize(
    "question,rewrites",
    [
        ("哪个续航更长？", 0),
        ("偏差是否相同？", 0),
        ("Compare the recorded times", 0),
        ("How many times larger is A?", 0),
        ("更新后的独立提问", 1),
    ],
)
def test_comparisons_and_rewrites_keep_qualified_generation(
    monkeypatch, bounded_local_model, question, rewrites
):
    from core.local_rag_generation import generation_chain

    monkeypatch.setenv("LOCAL_RAG_SEGMENTED", "true")
    model, calls, output = bounded_local_model
    answer = generation_chain(model).invoke(
        {
            "question": question,
            "context": "正常连续使用120日",
            "sources": ["A.txt"],
            "rewrite_count": rewrites,
        }
    )
    assert "120" in answer
    props = calls[0]["response_format"]["json_schema"]["schema"]["properties"]
    assert "basis" in props and "conclusion" in props
