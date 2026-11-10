"""The global grounding switch must stop generation-time judge work."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from agent.guardrails.grounding_guardrail import GroundingGuardrail
from agent.guardrails.types import GuardrailConfig

ANSWER = "超时应为 30 秒。"
CONTEXTS = ["文档写明超时 30 秒。"]
GOLDEN = json.loads((Path(__file__).parents[1] / "fixtures/grounding_disabled.json").read_text())


@pytest.mark.parametrize("flag", ["false", "0", "off", "no", " FALSE "])
@pytest.mark.parametrize("entry", ["sync", "async", "wrapper", "async_wrapper"])
def test_disabled_never_acquires_judge(monkeypatch, flag, entry):
    import agent.guardrails.grounding_guardrail as module

    monkeypatch.setenv("GROUNDING_CHECK_ENABLED", flag)
    getter = Mock(side_effect=AssertionError("disabled grounding acquired a judge"))
    monkeypatch.setattr("agent.eval.judge.get_judge", getter)
    monkeypatch.setattr(module, "_guardrail", None)
    guard = GroundingGuardrail()
    call = {
        "sync": guard.check,
        "async": guard.acheck,
        "wrapper": module.check_grounding,
        "async_wrapper": module.acheck_grounding,
    }[entry]
    result = call(ANSWER, CONTEXTS)
    if entry in {"async", "async_wrapper"}:
        result = asyncio.run(result)
    getter.assert_not_called()
    assert {key: getattr(result, key) for key in GOLDEN} == GOLDEN


@pytest.mark.parametrize("flag", [None, "true", "1", "yes", "on"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_enabled_preserves_semantic_check(monkeypatch, flag, asynchronous):
    if flag is None:
        monkeypatch.delenv("GROUNDING_CHECK_ENABLED", raising=False)
    else:
        monkeypatch.setenv("GROUNDING_CHECK_ENABLED", flag)
    entail = Mock(return_value=SimpleNamespace(supported=True))

    async def aentail(*args):
        return entail(*args)

    guard = GroundingGuardrail(SimpleNamespace(available=True, entail=entail, aentail=aentail))
    result = (
        asyncio.run(guard.acheck(ANSWER, CONTEXTS))
        if asynchronous
        else guard.check(ANSWER, CONTEXTS)
    )
    entail.assert_called_once()
    assert result.faithfulness == 1.0


def test_new_config_reads_environment_after_import(monkeypatch):
    monkeypatch.setenv("GROUNDING_CHECK_ENABLED", "false")
    assert GuardrailConfig().enable_grounding_check is False
    assert GuardrailConfig(enable_grounding_check=True).enable_grounding_check is True
    monkeypatch.setenv("GROUNDING_CHECK_ENABLED", "true")
    assert GuardrailConfig().enable_grounding_check is True
    assert GuardrailConfig(enable_grounding_check=False).enable_grounding_check is False


@pytest.mark.parametrize("asynchronous", [False, True])
def test_generation_preserves_none_and_output_checks(monkeypatch, asynchronous):
    from agent.guardrails.manager import GuardrailManager
    from agent.skills.base import SkillContext
    from agent.skills.generate.skill import GenerateSkill
    from core.retrieval.evidence import documents_to_evidence

    monkeypatch.setenv("GROUNDING_CHECK_ENABLED", "false")
    getter = Mock(side_effect=AssertionError("no judge allowed"))
    monkeypatch.setattr("agent.eval.judge.get_judge", getter)
    monkeypatch.setattr("agent.guardrails.grounding_guardrail._guardrail", None)
    monkeypatch.setattr("langgraph.config.get_stream_writer", lambda: lambda event: None)
    answer = ANSWER + "\n依据来源：《limits.md》。联系人：user@example.com。"
    skill = GenerateSkill(llm=SimpleNamespace())
    generation = Mock(return_value=(answer, ""))
    skill._invoke_with_reasoning = generation

    async def chunks(_values):
        generation()
        yield answer

    skill._chain = SimpleNamespace(astream=chunks)
    evidence = documents_to_evidence(
        [Document(page_content=CONTEXTS[0], metadata={"source": "limits.md", "score": 0.9})]
    )
    context = SkillContext(
        messages=[HumanMessage(content="超时应为多少秒？")],
        shared_state={
            "retrieval_evidence": evidence,
            "max_rerank_prob": 0.9,
            "intent_confidence": 0.9,
        },
    )
    result = asyncio.run(skill.aexecute(context)) if asynchronous else skill.execute(context)
    assert result.messages, result
    generation.assert_called_once()
    getter.assert_not_called()
    assert result.metadata["grounding_faithfulness"] is None
    assert result.metadata["confidence_degraded"] is True
    context.shared_state.update(result.state_updates["shared_state"])
    manager = GuardrailManager()
    manager.create_after_hook()("generate", context, result)
    assert "user@example.com" not in result.messages[-1].content
    bad_source = manager.check_output(
        "依据来源：《invented.md》。", ["limits.md"], contexts=CONTEXTS
    )
    assert bad_source.action.value == "escalate"
    getter.assert_not_called()
