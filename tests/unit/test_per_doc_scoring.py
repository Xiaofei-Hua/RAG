#!/usr/bin/env python3
"""
F3 per-document continuous scoring + multi-signal fusion — regression guards.

The original GradeSkill grades the whole context blob as binary yes/no (coarse).
F3 adds per-document continuous scoring fusing LLM grade + reranker score +
embedding similarity, for finer-grained filtering and re-ranking.

Run: pytest tests/unit/test_per_doc_scoring.py -v
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

sys.path.insert(0, ".")


class TestFusedScore:
    def test_all_signals_present(self):
        from agent.skills.grade.per_doc_scoring import _fused_score

        # llm=1.0 (w=0.4), rerank=0.8 (w=0.5), embed=0.6 (w=0.1)
        # = (1.0*0.4 + 0.8*0.5 + 0.6*0.1) / 1.0 = 0.86
        score = _fused_score(1.0, 0.8, 0.6)
        assert abs(score - 0.86) < 1e-6

    def test_rerank_absent_redistributes_weight(self):
        from agent.skills.grade.per_doc_scoring import _fused_score

        # Only llm (w=0.4) + embed (w=0.1): total_w=0.5
        # = (1.0*0.4 + 0.6*0.1) / 0.5 = 0.92
        score = _fused_score(1.0, None, 0.6)
        assert abs(score - 0.92) < 1e-6

    def test_all_absent_returns_zero(self):
        from agent.skills.grade.per_doc_scoring import _fused_score

        # Only llm signal with neutral 0.5
        score = _fused_score(0.5, None, None)
        assert abs(score - 0.5) < 1e-6


class TestGetRerankScore:
    def test_extracts_rerank_score(self):
        from agent.skills.grade.per_doc_scoring import _get_rerank_score

        doc = Document(page_content="x", metadata={"rerank_score": 0.85})
        assert _get_rerank_score(doc) == 0.85

    def test_extracts_rerank_prob(self):
        from agent.skills.grade.per_doc_scoring import _get_rerank_score

        doc = Document(page_content="x", metadata={"rerank_prob": 0.7})
        assert _get_rerank_score(doc) == 0.7

    def test_clamps_to_0_1(self):
        from agent.skills.grade.per_doc_scoring import _get_rerank_score

        doc = Document(page_content="x", metadata={"rerank_score": 1.5})
        assert _get_rerank_score(doc) == 1.0

    def test_absent_returns_none(self):
        from agent.skills.grade.per_doc_scoring import _get_rerank_score

        doc = Document(page_content="x", metadata={})
        assert _get_rerank_score(doc) is None


class TestScoreDocuments:
    def test_filters_below_threshold(self):
        """Documents below min_score are dropped (rerank drives filter when LLM=0)."""
        from agent.skills.grade.per_doc_scoring import score_documents

        docs = [
            Document(page_content="relevant doc", metadata={"rerank_score": 0.9}),
            Document(page_content="irrelevant doc", metadata={"rerank_score": 0.1}),
        ]
        # LLM grades the relevant doc as relevant (1.0) and irrelevant as not (0.0).
        # Fused: relevant = (1.0*0.4+0.9*0.5)/0.9 = 0.944; irrelevant = (0.0*0.4+0.1*0.5)/0.9 = 0.056
        with patch(
            "agent.skills.grade.per_doc_scoring._llm_grade_document", side_effect=[1.0, 0.0]
        ):
            result = score_documents("query", docs, MagicMock(), min_score=0.5)
        assert len(result) == 1
        assert result[0].page_content == "relevant doc"

    def test_reranks_by_score(self):
        """Survivors are re-ranked by fused score descending."""
        from agent.skills.grade.per_doc_scoring import score_documents

        docs = [
            Document(page_content="medium", metadata={"rerank_score": 0.6}),
            Document(page_content="high", metadata={"rerank_score": 0.95}),
            Document(page_content="low", metadata={"rerank_score": 0.5}),
        ]
        with patch("agent.skills.grade.per_doc_scoring._llm_grade_document", return_value=1.0):
            result = score_documents("q", docs, MagicMock(), min_score=0.4)
        assert [d.page_content for d in result] == ["high", "medium", "low"]

    def test_keeps_best_when_all_below_threshold(self):
        """When all docs score below threshold, keep at least the best (don't starve)."""
        from agent.skills.grade.per_doc_scoring import score_documents

        docs = [
            Document(page_content="a", metadata={"rerank_score": 0.05}),
            Document(page_content="b", metadata={"rerank_score": 0.02}),
        ]
        with patch("agent.skills.grade.per_doc_scoring._llm_grade_document", return_value=0.0):
            result = score_documents("q", docs, MagicMock(), min_score=0.8)
        assert len(result) == 1  # kept best

    def test_empty_input_returns_empty(self):
        from agent.skills.grade.per_doc_scoring import score_documents

        assert score_documents("q", [], MagicMock()) == []

    def test_grade_score_metadata_attached(self):
        """Surviving docs get a grade_score metadata field."""
        from agent.skills.grade.per_doc_scoring import score_documents

        docs = [Document(page_content="x", metadata={"rerank_score": 0.9})]
        with patch("agent.skills.grade.per_doc_scoring._llm_grade_document", return_value=1.0):
            result = score_documents("q", docs, MagicMock(), min_score=0.5)
        assert "grade_score" in result[0].metadata


class TestRetrievePerDocScoringGate:
    def test_disabled_by_default_returns_unchanged(self):
        """PER_DOC_SCORING_ENABLED=false (default) → docs unchanged, no LLM call."""
        from agent.skills.retrieve.skill import RetrieveSkill

        hr = RetrieveSkill()
        docs = [Document(page_content="x")]
        context = MagicMock()
        with patch("agent.skills.retrieve.skill._per_doc_scoring_enabled", return_value=False):
            result = hr._maybe_score_per_doc("q", docs, context)
        assert result is docs  # unchanged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
