"""
Shared fixtures and app wiring for end-to-end tests.

These fixtures let the full FastAPI app run in-process WITHOUT a real Ollama
LLM or Milvus, by replacing the module-level singleton getters that the
routers import internally.

Design notes:
  - The app has NO create_app() factory and most routers import singletons
    inline (not via Depends). So we patch the *source* modules'
    ``get_*`` getters via monkeypatch, plus FastAPI's dependency_overrides for
    ``get_session_memory`` (the one true Depends seam).
  - All on-disk artefacts (inference DB, candidates, eval runs, session DB)
    are redirected to a per-test tmp directory so tests are hermetic.
  - A FakeLLM, FakeRetriever, and a lightweight fake harness stand in for the
    expensive real components.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Tmp data dir: redirect ALL on-disk state so tests never touch real data/
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect every on-disk path the eval/store subsystem uses."""
    data = tmp_path / "data"
    (data / "eval" / "runs").mkdir(parents=True)
    (data / "eval" / "candidates").mkdir(parents=True)
    root = str(data)

    # Patch paths used by the eval / store modules.
    monkeypatch.setattr(
        "agent.eval.inference_store.DEFAULT_DB_PATH",
        os.path.join(root, "inferences.db"),
    )
    monkeypatch.setattr(
        "agent.eval.history.RUNS_DIR",
        __import__("pathlib").Path(os.path.join(root, "eval", "runs")),
    )
    monkeypatch.setattr(
        "agent.eval.history.HISTORY_PATH",
        __import__("pathlib").Path(os.path.join(root, "eval", "runs", "history.jsonl")),
    )
    monkeypatch.setattr(
        "agent.eval.candidates.CANDIDATES_DIR",
        __import__("pathlib").Path(os.path.join(root, "eval", "candidates")),
    )
    monkeypatch.setattr(
        "agent.eval.flywheel.RETRIEVAL_MISSES_DB",
        os.path.join(root, "eval", "retrieval_misses.db"),
    )
    # Reset the inference store singleton so it picks up the new path.
    import agent.eval.inference_store as is_mod

    if is_mod._store is not None:
        is_mod._store.close()
    is_mod._store = None
    return root


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------

class FakeAIMessage:
    """Minimal stand-in for langchain AIMessage."""

    def __init__(self, content: str):
        self.content = content
        self.type = "ai"
        self.additional_kwargs = {}
        self.tool_calls = []


class FakeLLM:
    """
    A deterministic fake chat model. Returns a canned answer (optionally
    derived from the prompt). Implements both sync invoke and async ainvoke,
    plus with_structured_output for the intent classifier.
    """

    def __init__(self, answer: str = "【诊断结论】这是测试诊断。仅供参考，注意安全风险。"):
        self._answer = answer

    def invoke(self, messages, **kwargs):
        return FakeAIMessage(self._answer)

    async def ainvoke(self, messages, **kwargs):
        return FakeAIMessage(self._answer)

    def with_structured_output(self, schema, **kwargs):
        # Intent classifier path: return a default rag_query intent result.
        outer = self

        class _Structured:
            def invoke(self_, messages, **kw):
                return outer._structured_result()

            async def ainvoke(self_, messages, **kw):
                return outer._structured_result()

        return _Structured()

    def _structured_result(self):
        # Build an IntentResult-like object.
        try:
            from core.intent.classifier import IntentResult, IntentType

            return IntentResult(
                intent=IntentType.RAG_QUERY,
                confidence=0.9,
                reasoning="fake classifier",
            )
        except Exception:
            return None


@pytest.fixture
def fake_llm():
    return FakeLLM()


# ---------------------------------------------------------------------------
# Fake retriever
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_retriever():
    """A hybrid retriever that returns two canned docs with scores."""
    from langchain_core.documents import Document

    class _FakeRetriever:
        def retrieve(self, query, top_k=None, filter_expr=None):
            return [
                Document(
                    page_content="发动机振动偏高时应进行频谱分析，1倍频主导通常指示不平衡。",
                    metadata={"source": "engine_manual", "title": "振动诊断", "score": 0.92},
                ),
                Document(
                    page_content="检查支承刚度与紧固件，必要时进行现场动平衡。",
                    metadata={"source": "engine_manual", "title": "振动排查", "score": 0.80},
                )
            ][: (top_k or 4)]

        async def aretrieve(self, query, top_k=None, filter_expr=None):
            return self.retrieve(query, top_k=top_k, filter_expr=filter_expr)

    return _FakeRetriever()


# ---------------------------------------------------------------------------
# Fake harness
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_harness(fake_llm, fake_retriever):
    """
    A minimal agent harness that returns a canned answer + sources for any
    ainvoke / invoke / astream call. This stands in for the full LangGraph so
    the RAG chat branch runs without building the real graph.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    canned_answer = "【诊断结论】发动机振动偏高，最可能为转子不平衡，仅供参考注意安全风险。"

    def _build_result():
        return {
            "messages": [
                ToolMessage(
                    content="发动机振动偏高时应进行频谱分析，1倍频主导通常指示不平衡。",
                    tool_call_id="c1",
                ),
                AIMessage(
                    content=canned_answer,
                    additional_kwargs={
                        "reasoning": "fake reasoning",
                        "confidence": 0.85,
                    },
                ),
            ],
            "_sources": [
                {
                    "source": "engine_manual",
                    "title": "振动诊断",
                    "content": "发动机振动偏高时应进行频谱分析",
                    "score": 0.92,
                }
            ],
        }

    class _FakeHarness:
        async def astart(self):
            return self

        async def aclose(self):
            pass

        def invoke(self, query, thread_id=None, **kwargs):
            return _build_result()

        async def ainvoke(self, query, thread_id=None, **kwargs):
            return _build_result()

        async def astream(self, query, thread_id=None, **kwargs):
            # Emit a single "done" update.
            yield {"messages": [AIMessage(content=canned_answer)]}

    return _FakeHarness()


# ---------------------------------------------------------------------------
# Fake session memory
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_session_memory():
    """An in-memory session store so chat/sessions endpoints work offline."""
    import time

    class _FakeMemory:
        def __init__(self):
            self._store = {}  # session_id -> list of langchain messages

        async def save_message(self, session_id, message):
            self._store.setdefault(session_id, []).append(message)

        async def get_messages(self, session_id, limit=50):
            from langchain_core.messages import HumanMessage, AIMessage

            msgs = self._store.get(session_id, [])
            # Return as langchain messages with a timestamp in additional_kwargs.
            out = []
            for m in msgs:
                content = getattr(m, "content", str(m))
                cls = HumanMessage if type(m).__name__ == "HumanMessage" else AIMessage
                out.append(cls(
                    content=content,
                    additional_kwargs={"_timestamp": time.time()},
                ))
            return out[-limit:]

        async def get_session_info(self, session_id):
            msgs = self._store.get(session_id, [])
            return {
                "session_id": session_id,
                "message_count": len(msgs),
                "title": "",
                "created_at": None,
                "last_active": None,
                "exists": True,
            }

        async def list_sessions(self, skip=0, limit=20):
            all_sessions = [
                {"session_id": sid, "message_count": len(msgs)}
                for sid, msgs in self._store.items()
            ]
            return all_sessions[skip : skip + limit], len(all_sessions)

        async def clear_session(self, session_id):
            self._store.pop(session_id, None)

        def close(self):
            pass

    return _FakeMemory()


# ---------------------------------------------------------------------------
# App + TestClient with all singletons patched
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_data_dir, fake_llm, fake_retriever, fake_harness, fake_session_memory, monkeypatch):
    """
    Build a TestClient over the real FastAPI app with all expensive
    singletons replaced by fakes. The app's lifespan is bypassed so we never
    build the real LangGraph.
    """
    # Patch source-module getters BEFORE importing the app.
    import agent.harness as harness_mod
    monkeypatch.setattr(harness_mod, "get_agent_harness", lambda *a, **k: fake_harness)

    import core.intent.classifier as intent_mod
    # Make the classifier use the keyword fast-path / our fake LLM.
    monkeypatch.setattr(intent_mod, "get_intent_classifier", lambda *a, **k: _FakeIntentClassifier(fake_llm))

    import core.retrieval.hybrid_retriever as hr_mod
    monkeypatch.setattr(hr_mod, "get_hybrid_retriever", lambda *a, **k: fake_retriever)

    import models.llm_models as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm", lambda *a, **k: fake_llm)
    monkeypatch.setattr(llm_mod, "create_custom_llm", lambda *a, **k: fake_llm)

    # Patch fast_mode to use the fake llm/retriever instead of real ones.
    import core.fast_mode as fast_mod
    async def _fake_fast_generate_async(query, **kwargs):
        from types import SimpleNamespace
        docs = fake_retriever.retrieve(query)
        return SimpleNamespace(
            answer="【诊断结论】快速模式诊断结果。仅供参考注意安全风险。",
            sources=[
                {"source": d.metadata["source"], "title": d.metadata["title"],
                 "content": d.page_content, "score": d.metadata["score"]}
                for d in docs
            ],
            retrieval_count=len(docs),
            retrieval_time_ms=10.0,
            generation_time_ms=20.0,
        )
    monkeypatch.setattr(fast_mod, "fast_generate_async", _fake_fast_generate_async)

    # Force the inference sampler to capture EVERY request in E2E tests.
    # (DEFAULT_SAMPLE_RATE is read at module load so env override is too late;
    # patching should_sample directly is reliable.)
    import agent.eval.sampler as sampler_mod
    monkeypatch.setattr(sampler_mod, "should_sample", lambda *a, **k: True)
    # capture.py imports should_sample by name, so patch it there too.
    import agent.eval.capture as capture_mod
    monkeypatch.setattr(capture_mod, "should_sample", lambda *a, **k: True)

    # Import app and override the session_memory dependency.
    from api.main import app
    from api.routers.chat import get_session_memory as chat_get_session_memory
    from api.routers.sessions import get_session_memory as sess_get_session_memory

    app.dependency_overrides[chat_get_session_memory] = lambda: fake_session_memory
    app.dependency_overrides[sess_get_session_memory] = lambda: fake_session_memory

    # Use TestClient with a no-op lifespan context so the real harness/LLM
    # startup is skipped.
    from fastapi.testclient import TestClient

    # Patch the lifespan startup path: make get_agent_harness().astart a no-op
    # and avoid reranker warmup by disabling it.
    monkeypatch.setattr("utils.env_utils.RERANKER_WARMUP", False)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


class _FakeIntentClassifier:
    """Uses keyword fast-path; falls back to a fake LLM structured output."""

    _RAG_KEYWORDS = frozenset([
        "振动", "液压", "航电", "发动机", "故障", "诊断", "排故", "排查",
        "压力", "温度", "滑油", "振动", "传感器", "电源", "信号",
    ])
    _CHAT_KEYWORDS = frozenset(["你好", "谢谢", "再见", "你是谁", "你能做什么", "hello", "hi"])

    def __init__(self, fake_llm):
        self._llm = fake_llm

    def _keyword(self, query):
        text = query.lower()
        if any(kw in text for kw in self._RAG_KEYWORDS):
            from core.intent.classifier import IntentResult, IntentType
            return IntentResult(
                intent=IntentType.RAG_QUERY, confidence=0.9, reasoning="keyword"
            )
        if any(kw in text for kw in self._CHAT_KEYWORDS):
            from core.intent.classifier import IntentResult, IntentType
            return IntentResult(
                intent=IntentType.GENERAL_CHAT, confidence=0.9, reasoning="keyword"
            )
        return None

    async def aclassify(self, query):
        from core.intent.classifier import IntentResult, IntentType
        res = self._keyword(query)
        if res:
            return res
        return IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake default"
        )

    def classify(self, query):
        res = self._keyword(query)
        if res:
            return res
        from core.intent.classifier import IntentResult, IntentType
        return IntentResult(
            intent=IntentType.GENERAL_CHAT, confidence=0.7, reasoning="fake default"
        )
