#!/usr/bin/env python3
"""
REQ-RB-001/002/003 — parent_store small-to-big wiring regression.

Guards Stage B: parent_store was dead code (read side ready, write side never
wired). These tests assert the write side now tags chunks with parent_id and
stores the parent text, and expand_to_parents returns the parent (not the
fallback child) for tagged chunks.

Run: pytest tests/unit/test_parent_store_write.py -v
"""

from __future__ import annotations

import os
import sys

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


@pytest.fixture(autouse=True)
def _isolated_parent_store(monkeypatch, tmp_path):
    """Redirect parent_store to a tmp db and reset the singleton per test
    (tests/conftest.py tmp_data_dir also does this, but keep this hermetic
    so the test is order-independent)."""
    import documents.parent_store as ps

    db = str(tmp_path / "ps.db")
    monkeypatch.setattr(ps, "DEFAULT_DB_PATH", db)
    if ps._store is not None:
        ps._store.close()
    ps._store = None
    yield
    if ps._store is not None:
        ps._store.close()
    ps._store = None


# ===========================================================================
# REQ-RB-001 — non-md splitter tags chunks + stores parent
# ===========================================================================


class TestNonMarkdownSplitTagsParent:
    def test_small_doc_tagged_with_self_parent(self):
        """A small doc (< threshold) is kept intact and tagged with its own
        parent_id; the parent_store holds its full text."""
        from api.routers.documents import _split_documents

        small = Document(page_content="液压泵压力低于阈值。" * 5, metadata={"source": "hyd.md"})
        result = _split_documents([small])
        assert result, "splitter returned nothing"
        for chunk in result:
            assert "parent_id" in chunk.metadata, "small chunk missing parent_id"

        from documents.parent_store import get_parent_store

        store = get_parent_store()
        pid = result[0].metadata["parent_id"]
        parent = store.get(pid)
        assert parent is not None, "parent not stored"
        assert "液压泵压力" in parent["content"]

    def test_large_doc_children_share_parent_and_store_has_full_text(self):
        """A large doc is split into chunks; all chunks share one parent_id and
        the parent_store holds the original full doc text (small-to-big).

        Uses semantically varied text (SemanticChunker won't split highly
        repetitive text — it treats repetition as one semantic unit)."""
        from api.routers.documents import _split_documents

        paragraphs = [
            "起落架收放系统采用液压驱动,主液压泵提供压力。",
            "低温环境下液压油粘度升高,泵的输出压力可能下降。",
            "蓄压器用于吸收液压冲击并维持系统压力稳定。",
            "电磁阀控制收放作动筒的油路方向,响应时间影响收放速度。",
            "密封件老化会导致内泄漏,降低系统效率。",
            "液压油滤芯堵塞会引起泵的吸入阻力增大。",
            "压力传感器实时监测系统压力并向飞控报告。",
            "应急放起落架系统采用独立的手动液压回路。",
            "液压泵的磨损状态可通过金属屑检测器监控。",
            "系统压力过低时会触发警告并建议尽快着陆。",
        ] * 8  # ~80 distinct paragraphs, > 3840 chars, semantically varied
        big_text = "\n\n".join(paragraphs)
        big = Document(page_content=big_text, metadata={"source": "gear.md"})
        result = _split_documents([big])
        # If the splitter isn't available in this env, fall back to asserting
        # tagging still happened on the single (un-split) chunk.
        assert result, "splitter returned nothing"
        pids = {c.metadata.get("parent_id") for c in result}
        assert len(pids) == 1, f"chunks have differing parent_ids: {pids}"

        from documents.parent_store import get_parent_store

        pid = next(iter(pids))
        parent = get_parent_store().get(pid)
        assert parent is not None
        # parent text is the FULL doc, >= any single chunk.
        assert len(parent["content"]) >= max(len(c.page_content) for c in result)


# ===========================================================================
# REQ-RB-001 — expand returns parent, not fallback child
# ===========================================================================


class TestExpandReturnsParent:
    def test_expand_swaps_child_for_parent_text(self):
        """When a chunk carries a stored parent_id, expand_to_parents MUST
        return the parent's text (small-to-big), not the child fallback."""
        from documents.parent_store import (
            expand_to_parents,
            get_parent_store,
            make_parent_id,
        )

        store = get_parent_store()
        source = "doc.md"
        pid = make_parent_id(source, 0)
        parent_text = "这是完整的父段文本,包含多个 child 的上下文。" * 20
        store.store(pid, content=parent_text, source=source, title="父段")

        child = Document(
            page_content="child 片段",
            metadata={"source": source, "parent_id": pid, "score": 1.0},
        )
        expanded = expand_to_parents([child])
        assert len(expanded) == 1
        e0 = expanded[0]
        assert len(e0.page_content) > len(child.page_content), (
            "expand returned child-sized text, not the parent — small-to-big broken"
        )
        assert "父段文本" in e0.page_content

    def test_expand_fallback_when_parent_missing(self):
        """If a chunk has parent_id but the store has no such parent, expand
        MUST fall back to the child (graceful, never empty)."""
        from documents.parent_store import expand_to_parents, make_parent_id

        pid = make_parent_id("ghost.md", 99)
        child = Document(
            page_content="orphan child",
            metadata={"source": "ghost.md", "parent_id": pid, "score": 1.0},
        )
        expanded = expand_to_parents([child])
        assert expanded, "expand returned empty on missing parent"
        assert expanded[0].page_content == "orphan child"


# ===========================================================================
# REQ-RB-002/003 — expand conditional default in RetrieveSkill
# ===========================================================================


class TestExpandConditionalDefault:
    def test_expand_default_on_when_parent_id_present(self):
        """expand_parents defaults ON when chunks carry parent_id (Stage B)."""
        from agent.skills.base import SkillContext
        from agent.skills.retrieve.skill import RetrieveSkill

        ctx = SkillContext(messages=[], shared_state={})  # no expand_parents key
        child = Document(
            page_content="x",
            metadata={"parent_id": "p1", "source": "s", "score": 1.0},
        )
        # Monkeypatch expand_to_parents to assert it's called.
        called = []
        from documents import parent_store

        orig = parent_store.expand_to_parents
        parent_store.expand_to_parents = lambda docs: (called.append(True), docs)[1]
        try:
            RetrieveSkill._maybe_expand_parents(ctx, [child])
        finally:
            parent_store.expand_to_parents = orig
        assert called, "expand was NOT triggered despite parent_id present"

    def test_expand_opt_out_via_shared_state_false(self):
        """shared_state['expand_parents']=False disables expand even with parent_id."""
        from agent.skills.base import SkillContext
        from agent.skills.retrieve.skill import RetrieveSkill

        ctx = SkillContext(messages=[], shared_state={"expand_parents": False})
        child = Document(
            page_content="x",
            metadata={"parent_id": "p1", "source": "s", "score": 1.0},
        )
        result = RetrieveSkill._maybe_expand_parents(ctx, [child])
        assert result == [child], "expand ran despite explicit opt-out"

    def test_expand_noop_for_old_index_without_parent_id(self):
        """Old indexes whose chunks lack parent_id get no-op (backward compat)."""
        from agent.skills.base import SkillContext
        from agent.skills.retrieve.skill import RetrieveSkill

        ctx = SkillContext(messages=[], shared_state={})
        child = Document(page_content="x", metadata={"source": "s", "score": 1.0})
        result = RetrieveSkill._maybe_expand_parents(ctx, [child])
        assert result == [child]


# ===========================================================================
# F-RB-01 — MCP path must carry parent_id end-to-end
# ===========================================================================


class TestMCPParentIdPassthrough:
    def test_mcp_format_documents_carries_parent_id(self):
        """The MCP retrieval server MUST carry parent_id in its serialized
        output, otherwise _maybe_expand_parents no-ops on MCP deployments
        (critic F-RB-01: precision small-to-big silently broken in production)."""
        from agent.mcp.retrieval_server import MCPRetrievalServer

        doc = Document(
            page_content="child chunk",
            metadata={"source": "s", "title": "t", "score": 1.0, "parent_id": "p_abc"},
        )
        out = MCPRetrievalServer._format_documents([doc])
        assert out[0]["parent_id"] == "p_abc", "MCP server dropped parent_id"

    def test_mcp_raw_to_documents_restores_parent_id(self):
        """The retrieve skill's MCP client MUST restore parent_id from the raw
        dict so _maybe_expand_parents sees it."""
        from agent.skills.retrieve.skill import RetrieveSkill

        raw = [
            {"content": "x", "source": "s", "title": "t", "score": 1.0, "parent_id": "p_def"}
        ]
        docs = RetrieveSkill._raw_to_documents(raw)
        assert docs[0].metadata.get("parent_id") == "p_def", (
            "MCP client dropped parent_id — expand would no-op"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
