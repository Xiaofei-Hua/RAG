#!/usr/bin/env python3
"""
Unit tests for P2 (Agent autonomy) + P3 (Engineering polish) enhancements.

Covers:
  - P2.1/P2.3 MCP tool registry + utility tools
  - P2.2 memory semantic retrieval + injection
  - P2.4/P2.5 model routing + fallback
  - P2.6 self-reflection
  - P2.7 HITL gate + workflow DSL
  - P3.1 PII detection + redaction
  - P3.2 prompt A/B testing
  - P3.3 prompt optimizer
  - P3.4 cancellation
  - P3.6 retrieval cache
  - P3.7 time decay

Run: pytest tests/unit/test_p2p3.py -v
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


# ===========================================================================
# P2.1 / P2.3 — MCP tool registry + utility tools
# ===========================================================================

class TestMCPToolRegistry:
    def test_utility_server_registers_calculator(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        srv = UtilityToolsServer()
        tools = srv.list_tools()
        names = [t["name"] for t in tools]
        assert "calculator" in names
        assert "unit_convert" in names

    def test_calculator_basic(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        assert s.calculate("2 + 3") == "5"
        assert s.calculate("2 * (3 + 4)") == "14"
        assert s.calculate("sqrt(16)") == "4.0"

    def test_calculator_rejects_injection(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        # Disallowed characters => error, not code execution.
        assert "错误" in s.calculate("__import__('os')")

    def test_unit_convert_temperature(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        result = s.convert_unit("100℃", "℉")
        assert "212" in result

    def test_unit_convert_length(self):
        from agent.mcp.tools_registry import UtilityToolsServer

        s = UtilityToolsServer()
        result = s.convert_unit("1 m", "cm")
        assert "100" in result

    def test_register_custom_tool_function(self, monkeypatch):
        import agent.mcp.tools_registry as reg_mod

        monkeypatch.setattr(reg_mod, "_extra_servers", [])
        monkeypatch.setattr(reg_mod, "_registered_defaults", True)

        def my_tool(x: str) -> str:
            return f"echo:{x}"

        reg_mod.register_tool_function("echo", "echo tool", my_tool)
        servers = reg_mod.get_extra_servers()
        tool_names = []
        for srv in servers:
            tool_names.extend(t["name"] for t in srv.list_tools())
        assert "echo" in tool_names


# ===========================================================================
# P2.2 — memory semantic retrieval + injection
# ===========================================================================

class TestMemoryInjection:
    def test_inject_memories_prepends(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        class _Ctx:
            shared_state = {
                "relevant_memories": [
                    {"content": "振动限值应为 4.0 IPS", "type": "correction"},
                ]
            }
        docs = [Document(page_content="检索到的手册内容", metadata={"score": 0.8})]
        out = RetrieveSkill._inject_memories(_Ctx(), docs)
        assert len(out) == 2
        # Memory first.
        assert "振动限值" in out[0].page_content
        assert out[0].metadata.get("is_memory") is True

    def test_inject_memories_noop_without_state(self):
        from agent.skills.retrieve.skill import RetrieveSkill

        docs = [Document(page_content="x")]
        assert RetrieveSkill._inject_memories(
            type("C", (), {"shared_state": None})(), docs
        ) == docs

    def test_memory_store_semantic_fallback_to_like(self, tmp_path, monkeypatch):
        """Semantic retrieve falls back to LIKE when embeddings unavailable."""
        from agent.memory.store import MemoryStore
        from agent.memory.types import MemoryEntry, MemoryQuery

        store = MemoryStore(str(tmp_path / "mem.db"))
        store.store(MemoryEntry(id="m1", content="振动限值 4.0 IPS"))
        # retrieve should work (LIKE fallback if no embeddings).
        results = store.retrieve(MemoryQuery(query="振动"))
        assert len(results) >= 1
        store._conn.close()


# ===========================================================================
# P2.4 / P2.5 — model routing + fallback
# ===========================================================================

class TestModelRouter:
    def test_tier_defaults_to_base(self, monkeypatch):
        import models.model_router as mr

        monkeypatch.delenv("LLM_MODEL_GRADE", raising=False)
        assert mr.get_model_for_tier(mr.ModelTier.GRADE, "qwen3:14b") == "qwen3:14b"

    def test_tier_uses_env(self, monkeypatch):
        import models.model_router as mr

        monkeypatch.setenv("LLM_MODEL_GRADE", "qwen3:4b")
        assert mr.get_model_for_tier(mr.ModelTier.GRADE, "qwen3:14b") == "qwen3:4b"
        # generate tier unaffected.
        assert mr.get_model_for_tier(mr.ModelTier.GENERATE, "qwen3:14b") == "qwen3:14b"

    def test_fallback_llm_tries_secondary(self):
        from models.model_router import FallbackLLM

        class _FakeResp:
            content = "ok"

        class _PrimaryFail:
            def invoke(self, msgs, **kw):
                raise RuntimeError("primary down")

        class _SecondaryOk:
            def invoke(self, msgs, **kw):
                return _FakeResp()

        fb = FallbackLLM(_PrimaryFail(), [_SecondaryOk()])
        assert fb.invoke([]).content == "ok"

    def test_fallback_llm_all_fail_raises(self):
        from models.model_router import FallbackLLM

        class _Fail:
            def invoke(self, msgs, **kw):
                raise RuntimeError("down")

        fb = FallbackLLM(_Fail(), [_Fail()])
        with pytest.raises(RuntimeError):
            fb.invoke([])

    def test_fallback_llm_primary_only_when_no_secondaries(self):
        from models.model_router import FallbackLLM

        class _Ok:
            def invoke(self, msgs, **kw):
                return "result"

        fb = FallbackLLM(_Ok())
        assert fb.invoke([]) == "result"

    def test_no_fallback_when_env_unset(self, monkeypatch):
        import models.model_router as mr

        monkeypatch.delenv("LLM_FALLBACK_BASE_URL", raising=False)
        primary = object()
        assert mr.get_fallback_llm(primary) is primary


# ===========================================================================
# P2.6 — self-reflection
# ===========================================================================

class TestSelfReflection:
    def test_confident_when_reasoning_consistent(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        # Hard claim + clear reasoning => confident.
        r = reflect_on_reasoning(
            "振动限值应为 4.0 IPS。",
            "根据手册第12页，振动限值为4.0 IPS，这是明确的。",
        )
        assert r.confident is True

    def test_not_confident_on_hedged_reasoning(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        r = reflect_on_reasoning(
            "振动限值应为 4.0 IPS。",
            "我猜测可能大概是这个值，不太确定。",
        )
        assert r.confident is False
        assert r.caveat  # caveat provided

    def test_not_confident_on_contradiction(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        r = reflect_on_reasoning(
            "振动限值应为 4.0 IPS。",
            "手册说4.0但另一方面又说不超过5.0，存在矛盾。",
        )
        assert r.confident is False

    def test_no_hard_claims_is_confident(self):
        from agent.skills.generate.self_reflection import reflect_on_reasoning

        r = reflect_on_reasoning(
            "请进一步检查该系统。",
            "不确定具体原因。",
        )
        assert r.confident is True  # soft answer, no caveat needed


# ===========================================================================
# P2.7 — HITL gate + workflow DSL
# ===========================================================================

class TestHITLGate:
    def test_request_and_resolve(self, tmp_path, monkeypatch):
        import core.workflow.hitl as hitl_mod

        gate = hitl_mod.HITLGate(str(tmp_path / "hitl.db"))
        req = gate.request_approval("s1", "execute_remediation", "更换轴承")
        assert req.status == "pending"
        assert not gate.is_approved(req.id)

        assert gate.resolve(req.id, approved=True) is True
        assert gate.is_approved(req.id) is True
        gate.close()

    def test_reject(self, tmp_path):
        from core.workflow.hitl import HITLGate

        gate = HITLGate(str(tmp_path / "hitl.db"))
        req = gate.request_approval("s1", "action")
        gate.resolve(req.id, approved=False)
        assert not gate.is_approved(req.id)
        gate.close()

    def test_list_pending(self, tmp_path):
        from core.workflow.hitl import HITLGate

        gate = HITLGate(str(tmp_path / "hitl.db"))
        gate.request_approval("s1", "a1")
        gate.request_approval("s2", "a2")
        pending = gate.list_pending()
        assert len(pending) == 2
        gate.close()


class TestWorkflowDSL:
    def test_resolve_default_when_no_spec(self, tmp_path, monkeypatch):
        import core.workflow.hitl as hitl_mod

        monkeypatch.setenv("WORKFLOW_DIR", str(tmp_path / "nowf"))
        plan = hitl_mod.resolve_workflow_for_intent(
            "rag_query", default_plan=["agent", "retrieve", "generate"]
        )
        assert plan == ["agent", "retrieve", "generate"]

    def test_load_yaml_workflow(self, tmp_path, monkeypatch):
        import core.workflow.hitl as hitl_mod

        wf_dir = tmp_path / "wf"
        wf_dir.mkdir()
        (wf_dir / "main.yaml").write_text(
            "name: phm\n"
            "plans:\n"
            "  rag_query: [retrieve, grade, generate]\n"
            "  general_chat: [generate]\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("WORKFLOW_DIR", str(wf_dir))
        plan = hitl_mod.resolve_workflow_for_intent("rag_query")
        assert plan == ["retrieve", "grade", "generate"]
        plan2 = hitl_mod.resolve_workflow_for_intent("general_chat")
        assert plan2 == ["generate"]


# ===========================================================================
# P3.1 — PII detection + redaction
# ===========================================================================

class TestPII:
    def test_detect_phone(self):
        from agent.guardrails.pii import detect_pii

        assert [m.kind for m in detect_pii("电话13812345678")] == ["phone"]

    def test_detect_email(self):
        from agent.guardrails.pii import detect_pii

        assert [m.kind for m in detect_pii("联系abc@test.com")] == ["email"]

    def test_detect_id_card(self):
        from agent.guardrails.pii import detect_pii

        matches = [m.kind for m in detect_pii("身份证110101199003071234")]
        assert "id_card" in matches

    def test_no_false_positive(self):
        from agent.guardrails.pii import detect_pii

        assert detect_pii("发动机振动偏高，频谱分析") == []

    def test_redact(self):
        from agent.guardrails.pii import redact_pii

        out = redact_pii("电话13812345678请回拨")
        assert "13812345678" not in out
        assert "已脱敏" in out


class TestOutputGuardrailPII:
    def test_output_redacts_pii(self):
        from agent.guardrails.output_guardrails import OutputGuardrail

        og = OutputGuardrail()
        result = og.validate(
            "联系工程师电话13812345678获取支持。",
            sources=["doc"],
            contexts=["ctx"],
        )
        assert result.action.value == "sanitize"
        assert "13812345678" not in (result.sanitized_content or "")


# ===========================================================================
# P3.2 — prompt A/B testing
# ===========================================================================

class TestABTesting:
    def test_default_when_no_variants(self, monkeypatch):
        import core.prompts.ab_testing as ab

        monkeypatch.delenv("PROMPT_AB_VARIANTS", raising=False)
        assert ab.assign_variant("profile", "session1") == "default"

    def test_deterministic_assignment(self, monkeypatch):
        import core.prompts.ab_testing as ab

        ab.reset_assignment_log()
        monkeypatch.setenv(
            "PROMPT_AB_VARIANTS",
            '{"phm_diagnosis_v1": ["v1", "v2"]}',
        )
        monkeypatch.setenv("PROMPT_AB_RATIO", "0.5")
        # Same session => same variant.
        v1 = ab.assign_variant("phm_diagnosis_v1", "session-x")
        v2 = ab.assign_variant("phm_diagnosis_v1", "session-x")
        assert v1 == v2
        assert v1 in ("v1", "v2")

    def test_record_and_stats(self, monkeypatch):
        import core.prompts.ab_testing as ab

        ab.reset_assignment_log()
        monkeypatch.delenv("PROMPT_AB_VARIANTS", raising=False)
        ab.record_variant("p", "s1", "v1")
        ab.record_variant("p", "s2", "v2")
        stats = ab.variant_stats("p")
        assert stats["v1"]["count"] == 1
        assert stats["v2"]["count"] == 1


# ===========================================================================
# P3.3 — prompt optimizer
# ===========================================================================

class TestPromptOptimizer:
    def test_no_runs_returns_empty(self, tmp_path):
        from core.prompts.optimizer import analyse_prompt_weaknesses

        suggestions = analyse_prompt_weaknesses(runs_dir=str(tmp_path / "noruns"))
        assert suggestions == []

    def test_detects_missing_sections(self, tmp_path):
        from core.prompts.optimizer import analyse_prompt_weaknesses

        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run = {
            "results": [
                {
                    "score": {
                        "overall_score": 0.3,
                        "section_coverage": 0.5,
                        "details": {"expected_sections": ["排查步骤"]},
                    }
                }
                for _ in range(4)
            ]
        }
        import json

        (runs_dir / "run1.json").write_text(json.dumps(run), encoding="utf-8")
        suggestions = analyse_prompt_weaknesses(runs_dir=str(runs_dir))
        cats = [s.category for s in suggestions]
        assert "missing_section" in cats


# ===========================================================================
# P3.4 — cancellation
# ===========================================================================

class TestCancellation:
    def test_propagates_cancel(self):
        from core.concurrency.cancellation import cancellable

        async def _main():
            async def slow():
                await asyncio.sleep(10)
            task = asyncio.create_task(slow())
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancellable(task, task_name="test")

        asyncio.run(_main())

    def test_returns_result_on_success(self):
        from core.concurrency.cancellation import cancellable

        async def _main():
            async def ok():
                return "done"
            result = await cancellable(ok(), task_name="ok")
            assert result == "done"

        asyncio.run(_main())


# ===========================================================================
# P3.6 — retrieval cache
# ===========================================================================

class TestRetrievalCache:
    def test_lru_eviction(self):
        from core.retrieval.cache import LRUCache

        c = LRUCache(maxsize=2)
        c.put("a", 1)
        c.put("b", 2)
        c.put("c", 3)  # evicts 'a'
        assert c.get("a") is None
        assert c.get("b") == 2
        assert c.get("c") == 3

    def test_hit_miss_stats(self):
        from core.retrieval.cache import LRUCache

        c = LRUCache(maxsize=10)
        c.put("k", "v")
        c.get("k")  # hit
        c.get("nope")  # miss
        stats = c.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert 0 < stats["hit_ratio"] < 1

    def test_cached_embedding(self):
        from core.retrieval.cache import LRUCache, CachedEmbeddingFunction

        class _Base:
            def __init__(self):
                self.calls = 0
            def embed_query(self, text):
                self.calls += 1
                return [1.0, 2.0]
            def embed_documents(self, texts):
                return [[1.0] for _ in texts]

        base = _Base()
        cached = CachedEmbeddingFunction(base)
        cached.embed_query("hello")
        cached.embed_query("hello")  # cached, no new call
        assert base.calls == 1


# ===========================================================================
# P3.7 — time decay
# ===========================================================================

class TestTimeDecay:
    def test_fresh_doc_unchanged(self):
        from core.retrieval.time_decay import apply_time_decay

        import time

        now = time.time()
        doc = Document(page_content="fresh", metadata={"score": 1.0, "created_at": now})
        out = apply_time_decay([doc], now=now)
        assert out[0].metadata["score"] == pytest.approx(1.0)

    def test_old_doc_decayed(self):
        from core.retrieval.time_decay import apply_time_decay

        import time

        now = time.time()
        # 360 days old, half-life 180 => factor ~0.25
        old_ts = now - 360 * 86400
        doc = Document(page_content="old", metadata={"score": 1.0, "created_at": old_ts})
        out = apply_time_decay([doc], half_life_days=180, now=now)
        assert out[0].metadata["score"] < 0.5
        assert out[0].metadata["score"] > 0.05  # floored at 0.1

    def test_no_timestamp_passthrough(self):
        from core.retrieval.time_decay import apply_time_decay

        doc = Document(page_content="nots", metadata={"score": 0.8})
        out = apply_time_decay([doc])
        assert out[0].metadata["score"] == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
