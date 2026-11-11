"""Generate one bounded answer and apply the existing local output checks."""

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, ConfigDict, Field

from models.local_rag_policy import bounded_local_rag
from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags

UNAVAILABLE_ANSWER = "本次回答未能完整生成，请缩小问题范围后重试。"


class CitedParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1)
    source_ids: list[int] = Field(min_length=1)


class GroundedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    basis: list[CitedParagraph] = Field(min_length=1)
    conditions: list[CitedParagraph]
    conclusion: CitedParagraph


def complete_content(message) -> str:
    metadata = getattr(message, "response_metadata", {}) or {}
    text = strip_think_tags(str(getattr(message, "content", "") or "")).strip()
    if metadata.get("finish_reason") in {"length", "content_filter"} or not text:
        raise RuntimeError("incomplete local RAG generation")
    return text


def render_paragraph(paragraph, sources):
    text = strip_think_tags(paragraph.text).strip()
    if not text or any(i < 1 or i > len(sources) for i in paragraph.source_ids):
        raise ValueError("invalid cited paragraph")
    names = dict.fromkeys(sources[i - 1] or f"证据{i}" for i in paragraph.source_ids)
    return text + "".join(f"[{name}]" for name in names)


def render_answer(message, sources: list[str], segmented=False) -> str:
    if segmented:
        from core.segmented_generation import SegmentedAnswer

        if (getattr(message, "response_metadata", {}) or {}).get("finish_reason") != "stop":
            raise ValueError("incomplete_generation")
        answer = SegmentedAnswer.model_validate_json(complete_content(message))
        lead = render_paragraph(answer.answer[0], sources)
        conditions = " ".join(render_paragraph(p, sources) for p in answer.conditions)
        return "\n\n".join(
            [
                lead + (" " + conditions if conditions else ""),
                *(render_paragraph(p, sources) for p in answer.answer[1:]),
            ]
        )
    else:
        answer = GroundedAnswer.model_validate_json(complete_content(message))
        paragraphs = [answer.conclusion, *answer.basis, *answer.conditions]
    return "\n\n".join(render_paragraph(paragraph, sources) for paragraph in paragraphs)


def build_generation_request(model, sources, segmented=False):
    from core.prompts.domain_profile import get_active_profile
    from core.segmented_generation import SegmentedAnswer

    if not sources:
        raise ValueError("missing evidence sources")
    profile = get_active_profile()
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                profile.prompts[
                    "segmented_generate_system" if segmented else "bounded_generate_system"
                ],
            ),
            ("human", profile.prompts["generate_human"]),
        ]
    )
    body = dict(getattr(model, "extra_body", None) or {})
    body["max_tokens"] = 2048
    schema = (SegmentedAnswer if segmented else GroundedAnswer).model_json_schema()
    schema["$defs"]["CitedParagraph"]["properties"]["source_ids"]["items"]["enum"] = list(
        range(1, len(sources) + 1)
    )
    configured = model.bind(
        reasoning_effort="none",
        temperature=0.7,
        top_p=0.8,
        max_tokens=2048,
        extra_body=body,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "rag_answer", "strict": True, "schema": schema},
        },
    )
    return prompt | configured


def generation_chain(model):
    from core.segmented_generation import segmented_enabled

    def generate(inputs, config):
        segmented = segmented_enabled(model, inputs["question"], inputs.get("rewrite_count", 0))
        sources = inputs["sources"]
        message = build_generation_request(model, sources, segmented).invoke(inputs, config)
        return render_answer(message, sources, segmented)

    async def agenerate(inputs, config):
        segmented = segmented_enabled(model, inputs["question"], inputs.get("rewrite_count", 0))
        sources = inputs["sources"]
        message = await build_generation_request(model, sources, segmented).ainvoke(inputs, config)
        return render_answer(message, sources, segmented)

    return RunnableLambda(generate, afunc=agenerate)


def finalize_answer(answer: str, sources, contexts, outcome=None) -> str:
    from agent.guardrails.manager import GuardrailManager
    from agent.guardrails.types import GuardrailAction

    if not bounded_local_rag():
        return answer
    try:
        result = GuardrailManager().check_output(answer, sources, contexts=contexts)
        if result.action in {GuardrailAction.BLOCK, GuardrailAction.ESCALATE}:
            if outcome is not None:
                outcome.update(
                    generation_complete=False,
                    status="unavailable",
                    reason="output_check_rejected",
                    retryable=True,
                )
            return "现有资料不足以支持完整回答，请核对原始资料后重试。"
        return result.sanitized_content or answer
    except Exception as exc:
        if outcome is not None:
            outcome.update(
                generation_complete=False,
                status="unavailable",
                reason="output_check_failed",
                retryable=True,
            )
        log.warning(f"Bounded output check failed: {type(exc).__name__}")
        return "本次回答未能完成输出检查，请重试。"
