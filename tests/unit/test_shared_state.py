#!/usr/bin/env python3
"""
Unit tests for the cross-node shared_state fix (Stage 1).

These verify that:
  - AgentState carries a merged ``shared_state`` field.
  - SkillContext <-> AgentState round-trips preserve shared_state.
  - The lifecycle before-hook increment mechanism collects and merges
    shared_state increments, and the orchestrator's _merge_state_update
    combines them with a skill's own output (skill wins on conflict).
  - The memory-enrichment hook returns a shared_state increment.
  - GenerateSkill publishes retrieved_contexts/sources/grounding_faithfulness
    into shared_state (activating the output guardrail's NLI path).
  - RetrieveSkill publishes retrieval_relevance (activating composite
    confidence cross-node).

Run: pytest tests/unit/test_shared_state.py -v
"""

from __future__ import annotations

import sys

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

sys.path.insert(0, ".")


# ===========================================================================
# AgentState + merge reducer
# ===========================================================================

class TestMergeReducer:
    def test_later_write_wins_per_key(self):
        from agent.context.state import merge_shared_state

        merged = merge_shared_state({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert merged == {"a": 1, "b": 3, "c": 4}

    def test_none_sides_default_to_empty(self):
        from agent.context.state import merge_shared_state

        assert merge_shared_state(None, {"x": 1}) == {"x": 1}
        assert merge_shared_state({"x": 1}, None) == {"x": 1}
        assert merge_shared_state(None, None) == {}

    def test_does_not_mutate_inputs(self):
        from agent.context.state import merge_shared_state

        left = {"a": 1}
        right = {"b": 2}
        merge_shared_state(left, right)
        assert left == {"a": 1}
        assert right == {"b": 2}

    def test_list_valued_key_is_whole_key_overwrite_not_concatenation(self):
        """F03 contract pin: the reducer is a shallow merge. When two producers
        write the same key holding a list, the later write REPLACES the whole
        list — it does NOT concatenate. This is the documented foot-gun
        (AGENTS.md §4.1); new producers must use a fresh key or accept overwrite
        semantics. Pinning it prevents an accidental switch to deep-merge."""
        from agent.context.state import merge_shared_state

        left = {"retrieved_contexts": ["doc_a", "doc_b"]}
        right = {"retrieved_contexts": ["doc_c"]}
        merged = merge_shared_state(left, right)
        # Later write wins wholesale; "doc_a"/"doc_b" are GONE, not appended.
        assert merged == {"retrieved_contexts": ["doc_c"]}

    def test_initial_state_has_shared_state(self):
        from agent.context.state import StateManager

        state = StateManager.create_initial_state("hi")
        assert "shared_state" in state
        assert state["shared_state"] == {}


# ===========================================================================
# SkillContext round-trip
# ===========================================================================

class TestSkillContextRoundTrip:
    def test_to_from_agent_state_preserves_shared_state(self):
        from agent.skills.base import SkillContext

        ctx = SkillContext(
            messages=[],
            shared_state={"relevance_scores": [0.9], "sources": ["a"]},
        )
        state = ctx.to_agent_state()
        assert state["shared_state"] == {"relevance_scores": [0.9], "sources": ["a"]}

        ctx2 = SkillContext.from_agent_state(state)
        assert ctx2.shared_state == {"relevance_scores": [0.9], "sources": ["a"]}

    def test_from_agent_state_defaults_empty_when_missing(self):
        from agent.skills.base import SkillContext

        # Old-style checkpoint without shared_state field.
        ctx = SkillContext.from_agent_state({"messages": [], "rewrite_count": 0})
        assert ctx.shared_state == {}

    def test_from_agent_state_handles_none(self):
        from agent.skills.base import SkillContext

        ctx = SkillContext.from_agent_state(
            {"messages": [], "shared_state": None}
        )
        assert ctx.shared_state == {}

    def test_from_agent_state_returns_independent_copy(self):
        from agent.skills.base import SkillContext

        state = {"messages": [], "shared_state": {"a": 1}}
        ctx = SkillContext.from_agent_state(state)
        ctx.shared_state["a"] = 99
        # Mutating the context must not leak back into the source dict.
        assert state["shared_state"]["a"] == 1


# ===========================================================================
# SkillResult state_updates propagation
# ===========================================================================

class TestSkillResultStateUpdate:
    def test_state_updates_with_shared_state_propagates(self):
        from agent.skills.base import SkillResult

        result = SkillResult(
            state_updates={"shared_state": {"sources": ["x"]}}
        )
        update = result.to_state_update()
        assert update["shared_state"] == {"sources": ["x"]}

    def test_state_updates_without_shared_state(self):
        from agent.skills.base import SkillResult

        result = SkillResult(state_updates={"rewrite_count": 1})
        update = result.to_state_update()
        assert "shared_state" not in update
        assert update["rewrite_count"] == 1


# ===========================================================================
# Lifecycle before-hook increment mechanism
# ===========================================================================

class TestBeforeHookIncrements:
    def test_hook_returning_dict_is_collected(self):
        from agent.harness.lifecycle import LifecycleManager
        from agent.skills.base import SkillContext

        lm = LifecycleManager()

        def hook(skill_name, context):
            return {"shared_state": {"relevant_memories": ["m1"]}}

        lm.on_before_skill(hook, name="mem", priority=80)
        ctx = SkillContext(messages=[], shared_state={})
        increments = lm.fire_before_skill("agent", ctx)
        assert increments == {"shared_state": {"relevant_memories": ["m1"]}}

    def test_multiple_hook_increments_merged(self):
        from agent.harness.lifecycle import LifecycleManager
        from agent.skills.base import SkillContext

        lm = LifecycleManager()
        lm.on_before_skill(
            lambda name, ctx: {"shared_state": {"a": 1}}, name="h1", priority=80
        )
        lm.on_before_skill(
            lambda name, ctx: {"shared_state": {"b": 2}}, name="h2", priority=90
        )
        ctx = SkillContext(messages=[], shared_state={})
        increments = lm.fire_before_skill("agent", ctx)
        assert increments["shared_state"] == {"a": 1, "b": 2}

    def test_hook_returning_none_is_noop(self):
        from agent.harness.lifecycle import LifecycleManager
        from agent.skills.base import SkillContext

        lm = LifecycleManager()
        lm.on_before_skill(lambda name, ctx: None, name="noop", priority=80)
        ctx = SkillContext(messages=[], shared_state={})
        increments = lm.fire_before_skill("agent", ctx)
        assert increments == {}

    def test_non_shared_increments_pass_through(self):
        from agent.harness.lifecycle import LifecycleManager
        from agent.skills.base import SkillContext

        lm = LifecycleManager()
        lm.on_before_skill(
            lambda name, ctx: {"intent_confidence": 0.7}, name="h", priority=80
        )
        ctx = SkillContext(messages=[], shared_state={})
        increments = lm.fire_before_skill("agent", ctx)
        assert increments == {"intent_confidence": 0.7}

    def test_failing_hook_does_not_break_others(self):
        from agent.harness.lifecycle import LifecycleManager
        from agent.skills.base import SkillContext

        lm = LifecycleManager()

        def boom(name, ctx):
            raise RuntimeError("fail")

        def ok(name, ctx):
            return {"shared_state": {"good": True}}

        lm.on_before_skill(boom, name="boom", priority=50)
        lm.on_before_skill(ok, name="ok", priority=80)
        ctx = SkillContext(messages=[], shared_state={})
        increments = lm.fire_before_skill("agent", ctx)
        # The failing hook is skipped; the good one still contributes.
        assert increments == {"shared_state": {"good": True}}


# ===========================================================================
# Orchestrator _merge_state_update
# ===========================================================================

class TestMergeStateUpdate:
    def test_hook_and_skill_shared_state_combine(self):
        from agent.harness.orchestrator import AgentHarness
        from agent.skills.base import SkillResult

        harness = AgentHarness()
        result = SkillResult(
            state_updates={"shared_state": {"retrieved_contexts": ["c1"]}}
        )
        before_inc = {"shared_state": {"relevant_memories": ["m1"]}}
        update = harness._merge_state_update(result, before_inc)
        assert update["shared_state"] == {
            "retrieved_contexts": ["c1"],
            "relevant_memories": ["m1"],
        }

    def test_skill_wins_on_key_conflict(self):
        from agent.harness.orchestrator import AgentHarness
        from agent.skills.base import SkillResult

        harness = AgentHarness()
        result = SkillResult(
            state_updates={"shared_state": {"k": "skill"}}
        )
        before_inc = {"shared_state": {"k": "hook", "other": 1}}
        update = harness._merge_state_update(result, before_inc)
        assert update["shared_state"]["k"] == "skill"
        assert update["shared_state"]["other"] == 1

    def test_no_increments_returns_plain_update(self):
        from agent.harness.orchestrator import AgentHarness
        from agent.skills.base import SkillResult

        harness = AgentHarness()
        result = SkillResult(state_updates={"rewrite_count": 1})
        update = harness._merge_state_update(result, {})
        assert update == {"rewrite_count": 1}


# ===========================================================================
# Memory enrichment hook returns increment
# ===========================================================================

class TestMemoryEnrichmentHook:
    def test_hook_returns_shared_state_increment(self, monkeypatch):
        from agent.memory.lifecycle import create_memory_enrichment_hook

        class _FakeMem:
            def __init__(self, mid, content, mtype):
                self.id = mid
                self.content = content
                self.memory_type = type("T", (), {"value": mtype})()

        class _FakeStore:
            def retrieve(self, query):
                return [_FakeMem("m1", "振动限值 4.0", "correction")]

        monkeypatch.setattr(
            "agent.memory.lifecycle.get_memory_store", lambda: _FakeStore()
        )

        hook = create_memory_enrichment_hook()
        from agent.skills.base import SkillContext

        ctx = SkillContext(
            messages=[HumanMessage(content="振动限值是多少？")], shared_state={}
        )
        increment = hook("agent", ctx)
        assert increment is not None
        assert "shared_state" in increment
        assert increment["shared_state"]["relevant_memories"][0]["content"] == "振动限值 4.0"
        # Also mutates the live context for the current node.
        assert ctx.shared_state["relevant_memories"][0]["content"] == "振动限值 4.0"

    def test_hook_returns_none_for_non_agent_skill(self):
        from agent.memory.lifecycle import create_memory_enrichment_hook
        from agent.skills.base import SkillContext

        hook = create_memory_enrichment_hook()
        ctx = SkillContext(messages=[HumanMessage(content="q")], shared_state={})
        assert hook("retrieve", ctx) is None


# ===========================================================================
# GenerateSkill publishes grounding contexts/sources
# ===========================================================================

class TestGenerateSkillPublishesSharedState:
    def test_extract_sources_list_from_tool_message(self):
        from agent.skills.generate.skill import GenerateSkill

        messages = [
            HumanMessage(content="q"),
            ToolMessage(
                content=[
                    {"text": "片段1", "source": "manual_a.pdf", "score": 0.9},
                    {"text": "片段2", "source": "manual_b.pdf", "score": 0.8},
                    {"text": "片段3", "source": "manual_a.pdf", "score": 0.7},
                ],
                tool_call_id="c1",
            ),
        ]
        sources = GenerateSkill._extract_sources_list(messages)
        # De-duplicated, order preserved.
        assert sources == ["manual_a.pdf", "manual_b.pdf"]

    def test_contexts_list_flattens_chunks(self):
        from agent.skills.generate.skill import GenerateSkill

        messages = [
            HumanMessage(content="q"),
            ToolMessage(
                content=[
                    {"text": "片段1", "score": 0.9},
                    {"text": "", "score": 0.1},  # empty -> skipped
                    {"text": "片段3", "score": 0.7},
                ],
                tool_call_id="c1",
            ),
        ]
        contexts = GenerateSkill._contexts_list(messages)
        assert contexts == ["片段1", "片段3"]


# ===========================================================================
# RetrieveSkill publishes retrieval_relevance
# ===========================================================================

class TestRetrieveSkillPublishesRelevance:
    def test_mean_relevance_from_documents(self):
        from agent.skills.retrieve.skill import RetrieveSkill
        from langchain_core.documents import Document

        docs = [
            Document(page_content="a", metadata={"score": 0.8}),
            Document(page_content="b", metadata={"score": 0.6}),
            Document(page_content="c", metadata={"source": "x"}),  # no score
        ]
        assert RetrieveSkill._mean_relevance(docs) == pytest.approx(0.7)

    def test_mean_relevance_none_when_no_scores(self):
        from agent.skills.retrieve.skill import RetrieveSkill
        from langchain_core.documents import Document

        docs = [Document(page_content="a", metadata={})]
        assert RetrieveSkill._mean_relevance(docs) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
