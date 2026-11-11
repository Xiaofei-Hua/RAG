"""Release complete, checked paragraphs from one constrained generation."""

import json
import os
import re
from contextlib import aclosing

from pydantic import BaseModel, ConfigDict, Field

from core.local_rag_generation import UNAVAILABLE_ANSWER, CitedParagraph, render_paragraph
from models.local_model_queue import ModelBusyError
from models.local_rag_policy import bounded_local_rag

INCOMPLETE_NOTICE = "\n\n本次回答尚未完整生成，以上仅为已完成部分，请重试。"


class SegmentedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    conditions: list[CitedParagraph]
    answer: list[CitedParagraph] = Field(min_length=1)


_COMPARISON = re.compile(
    r"比较|对比|相比|相同|一样|差异|区别|哪个|哪种|哪一|优劣|更长|更短|更大|更小|"
    r"更高|更低|多于|少于|大于|小于|相差|倍|等于|一致|"
    r"\b(?:compar\w*|same|equal\w*|differ\w*|versus|vs|better|worse|longer|shorter|"
    r"larger|smaller|greater|less|higher|lower|ratio|times)\b",
    re.IGNORECASE,
)


def segmented_enabled(model=None, question="", rewrite_count=0):
    return (
        os.getenv("LOCAL_RAG_SEGMENTED", "false").lower() == "true"
        and bounded_local_rag(model)
        and rewrite_count == 0
        and not _COMPARISON.search(question)
    )


def generation_outcome(complete=True, reason=None, partial=False):
    return {
        "status": "complete" if complete else "incomplete" if partial else "unavailable",
        "generation_complete": complete,
        "reason": reason,
        "retryable": not complete,
    }


class ParagraphParser:
    def __init__(self, sources):
        self.sources = sources
        self.buffer = ""
        self.position = None
        self.conditions = []
        self.closed = False
        self.count = 0
        self.decoder = json.JSONDecoder()

    def feed(self, text):
        self.buffer += text
        if len(self.buffer.encode("utf-8")) > 32768:
            raise ValueError("generation_buffer_limit")
        if self.position is None:
            start = re.match(r'\s*\{\s*"conditions"\s*:\s*', self.buffer)
            if not start:
                return []
            try:
                conditions, end = self.decoder.raw_decode(self.buffer, start.end())
            except json.JSONDecodeError:
                return []
            if not isinstance(conditions, list):
                raise ValueError("invalid_conditions")
            self.conditions = [
                render_paragraph(CitedParagraph.model_validate(item), self.sources)
                for item in conditions
            ]
            answer = re.match(r'\s*,\s*"answer"\s*:\s*\[', self.buffer[end:])
            if not answer:
                return []
            self.position = end + answer.end()
        paragraphs = []
        while not self.closed:
            pos = self.position
            while pos < len(self.buffer) and self.buffer[pos].isspace():
                pos += 1
            try:
                value, end = self.decoder.raw_decode(self.buffer, pos)
            except json.JSONDecodeError:
                break
            while end < len(self.buffer) and self.buffer[end].isspace():
                end += 1
            if end == len(self.buffer):
                break
            if self.buffer[end] not in ",]":
                raise ValueError("invalid_paragraph_delimiter")
            paragraph = CitedParagraph.model_validate(value)
            rendered = render_paragraph(paragraph, self.sources)
            if self.count == 0 and self.conditions:
                rendered += " " + " ".join(self.conditions)
            paragraphs.append(rendered)
            self.count += 1
            self.closed = self.buffer[end] == "]"
            self.position = end + 1
        return paragraphs

    def finish(self, finish_reason):
        if finish_reason != "stop":
            raise ValueError("incomplete_generation")
        answer = SegmentedAnswer.model_validate_json(self.buffer)
        if not self.closed or self.count != len(answer.answer):
            raise ValueError("incomplete_answer")


class CheckedParagraphs:
    def __init__(self, checker, sources, contexts):
        self.checker, self.sources, self.contexts = checker, sources, contexts
        self.text = ""

    def append(self, paragraph):
        from agent.guardrails.types import GuardrailAction

        candidate = self.text + ("\n\n" if self.text else "") + paragraph
        result = self.checker(candidate, self.sources, contexts=self.contexts)
        if result.action in {GuardrailAction.BLOCK, GuardrailAction.ESCALATE}:
            raise ValueError("output_check_rejected")
        checked = result.sanitized_content if result.sanitized_content is not None else candidate
        if not checked.startswith(self.text) or not checked.strip():
            raise ValueError("published_prefix_changed")
        suffix = checked[len(self.text) :]
        self.text = checked
        return suffix


def request_model(model, sources):
    from core.local_rag_generation import build_generation_request

    return build_generation_request(model, sources, segmented=True)


async def stream_answer(model, inputs, checker, contexts):
    sources = inputs["sources"]
    parser = ParagraphParser(sources)
    publisher = CheckedParagraphs(checker, sources, contexts)
    finish_reason = None
    try:
        async with aclosing(request_model(model, sources).astream(inputs)) as stream:
            async for chunk in stream:
                metadata = getattr(chunk, "response_metadata", {}) or {}
                finish_reason = metadata.get("finish_reason", finish_reason)
                for paragraph in parser.feed(str(getattr(chunk, "content", "") or "")):
                    suffix = publisher.append(paragraph)
                    if suffix:
                        yield {"type": "token", "content": suffix}
        parser.finish(finish_reason)
        outcome = generation_outcome()
    except ModelBusyError:
        raise
    except Exception as exc:
        # 只保留已检查前缀，固定失败提示不含模型原文。
        suffix = INCOMPLETE_NOTICE if publisher.text else UNAVAILABLE_ANSWER
        outcome = generation_outcome(False, type(exc).__name__, partial=bool(publisher.text))
        publisher.text += suffix
        yield {"type": "token", "content": suffix}
    yield {"type": "done", "full_response": publisher.text, "generation_outcome": outcome}
