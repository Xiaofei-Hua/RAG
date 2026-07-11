"""Per-document relevance scoring with multi-signal fusion (F3).

The original GradeSkill grades the whole context blob as a binary yes/no — coarse
and can't rank individual documents. This module adds per-document continuous
scoring that fuses:

- **LLM relevance grade** (per-document binary → 1.0/0.0, via structured output).
- **Reranker score** (continuous, from the cross-encoder's metadata when present).
- **Embedding similarity** (cosine, fallback when reranker is unavailable).

The fused score ∈ [0, 1] drives filtering (drop below threshold) + re-ranking
(more relevant docs first). The binary routing gate (generate vs rewrite) stays
in GradeSkill — this is a complementary precision layer.

Degrades gracefully: if LLM grading fails, falls back to rerank-score-only; if
that's absent, returns docs unchanged (never blocks the pipeline).
"""

from __future__ import annotations

import asyncio

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

from utils.log_utils import log

__all__ = ["score_documents", "ascore_documents"]

# Weight allocation for multi-signal fusion (sum = 1.0).
# Reranker is the strongest signal (cross-encoder); LLM grade catches semantic
# relevance the reranker misses; embedding sim is a weak fallback.
W_RERANK = 0.5
W_LLM_GRADE = 0.4
W_EMBED_SIM = 0.1

# Default filter threshold: documents below this fused score are dropped.
DEFAULT_MIN_SCORE = 0.3

_PER_DOC_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是一个文档相关性评估器。判断以下单个文档片段是否与用户问题相关。"
            '只返回 JSON: {"relevant": true} 或 {"relevant": false}。不要添加解释。',
        ),
        ("human", "用户问题: {question}\n\n文档片段: {doc_text}\n\n判断:"),
    ]
)


def _llm_grade_document(llm, question: str, doc_text: str) -> float:
    """Grade a single document via LLM → 1.0 (relevant) or 0.0 (not). Best-effort."""
    try:
        structured = llm.with_structured_output(dict, method="json_mode")
        chain = _PER_DOC_PROMPT | structured
        result = chain.invoke({"question": question[:300], "doc_text": doc_text[:500]})
        val = result.get("relevant", False)
        return 1.0 if val in (True, "true", "yes", 1) else 0.0
    except Exception:  # noqa: BLE001 — best-effort
        return 0.5  # neutral when LLM fails


async def _allm_grade_document(llm, question: str, doc_text: str) -> float:
    """Async single-document LLM grade."""
    try:
        structured = llm.with_structured_output(dict, method="json_mode")
        chain = _PER_DOC_PROMPT | structured
        result = await chain.ainvoke({"question": question[:300], "doc_text": doc_text[:500]})
        val = result.get("relevant", False)
        return 1.0 if val in (True, "true", "yes", 1) else 0.0
    except Exception:  # noqa: BLE001
        return 0.5


def _get_rerank_score(doc: Document) -> float | None:
    """Extract the reranker score from doc metadata (0-1 normalised)."""
    for key in ("rerank_score", "rerank_prob", "relevance_score"):
        val = doc.metadata.get(key)
        if val is not None:
            try:
                return max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                continue
    return None


def _fused_score(llm_grade: float, rerank_score: float | None, embed_sim: float | None) -> float:
    """Fuse signals into a single [0, 1] score. Missing signals redistribute weight."""
    signals: list[tuple[float, float]] = [(llm_grade, W_LLM_GRADE)]
    if rerank_score is not None:
        signals.append((rerank_score, W_RERANK))
    if embed_sim is not None:
        signals.append((embed_sim, W_EMBED_SIM))
    total_w = sum(w for _, w in signals)
    return sum(s * w for s, w in signals) / total_w if total_w > 0 else 0.0


def score_documents(
    question: str,
    documents: list[Document],
    llm,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Document]:
    """Score + filter documents by fused relevance (sync).

    Each document gets a continuous fused score (LLM grade + rerank + embed sim).
    Documents below ``min_score`` are dropped; survivors are re-ranked by score.
    Degrades to rerank-only (if LLM fails) or unchanged (if all signals absent).
    """
    if not documents:
        return documents
    scored: list[tuple[float, Document]] = []
    for doc in documents:
        rerank = _get_rerank_score(doc)
        embed_sim = doc.metadata.get("embedding_similarity")
        try:
            llm_grade = _llm_grade_document(llm, question, doc.page_content)
        except Exception:  # noqa: BLE001
            llm_grade = 0.5
        fused = _fused_score(llm_grade, rerank, embed_sim)
        if fused >= min_score:
            doc.metadata["grade_score"] = round(fused, 4)
            scored.append((fused, doc))
    if not scored:
        log.debug("per-doc scoring: all docs below threshold, keeping top-1")
        # Keep at least the best doc to avoid starving generation.
        best = max(documents, key=lambda d: _get_rerank_score(d) or 0.0)
        best.metadata["grade_score"] = 0.0
        return [best]
    scored.sort(key=lambda x: x[0], reverse=True)
    log.debug(f"per-doc scoring: {len(scored)}/{len(documents)} docs passed threshold {min_score}")
    return [doc for _, doc in scored]


async def ascore_documents(
    question: str,
    documents: list[Document],
    llm,
    min_score: float = DEFAULT_MIN_SCORE,
) -> list[Document]:
    """Score + filter documents by fused relevance (async, concurrent grading)."""
    if not documents:
        return documents

    async def _score_one(doc: Document) -> tuple[float, Document]:
        rerank = _get_rerank_score(doc)
        embed_sim = doc.metadata.get("embedding_similarity")
        llm_grade = await _allm_grade_document(llm, question, doc.page_content)
        fused = _fused_score(llm_grade, rerank, embed_sim)
        return fused, doc

    results = await asyncio.gather(*[_score_one(d) for d in documents], return_exceptions=True)
    scored: list[tuple[float, Document]] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        fused, doc = r
        if fused >= min_score:
            doc.metadata["grade_score"] = round(fused, 4)
            scored.append((fused, doc))
    if not scored and documents:
        best = max(documents, key=lambda d: _get_rerank_score(d) or 0.0)
        best.metadata["grade_score"] = 0.0
        return [best]
    scored.sort(key=lambda x: x[0], reverse=True)
    log.debug(f"per-doc scoring (async): {len(scored)}/{len(documents)} passed")
    return [doc for _, doc in scored]
