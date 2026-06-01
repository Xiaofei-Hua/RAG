"""
Retrieval Router — 知识库向量/关键词检索

提供三种检索策略，全部不调用 LLM，仅做知识库匹配：
- 混合检索 (dense + BM25 + RRF fusion)
- 纯向量检索 (dense only)
- 纯关键词检索 (BM25 sparse only)
"""

from __future__ import annotations

import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.log_utils import log

router = APIRouter()


# =============================================================================
# Request / Response Models
# =============================================================================

class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1, description="检索查询文本")
    top_k: int = Field(5, ge=1, le=50, description="返回结果数量")


class RetrievedDocument(BaseModel):
    content: str
    source: str = ""
    title: str = ""
    score: float = 0.0


class RetrievalResponse(BaseModel):
    query: str
    results: List[RetrievedDocument]
    total: int
    retrieval_time_ms: float


# =============================================================================
# Helpers
# =============================================================================

def _build_response(query: str, results, elapsed_ms: float) -> RetrievalResponse:
    docs = []
    for r in results:
        if hasattr(r, "page_content"):
            content = r.page_content
            meta = getattr(r, "metadata", {})
            score = meta.get("score", 0.0)
            source = meta.get("source", "")
            title = meta.get("title", "")
        elif hasattr(r, "text"):
            content = r.text
            score = getattr(r, "score", 0.0)
            meta = getattr(r, "metadata", {})
            source = meta.get("source", "")
            title = meta.get("title", "")
        elif hasattr(r, "document"):
            doc = r.document
            content = doc.page_content
            score = r.score
            source = doc.metadata.get("source", "")
            title = doc.metadata.get("title", "")
        else:
            continue
        docs.append(RetrievedDocument(
            content=content, source=source, title=title, score=score,
        ))
    return RetrievalResponse(
        query=query, results=docs, total=len(docs), retrieval_time_ms=elapsed_ms,
    )


# =============================================================================
# Endpoints
# =============================================================================

@router.post("", response_model=RetrievalResponse)
async def hybrid_retrieve(req: RetrievalRequest):
    """
    混合检索 — dense 向量 + BM25 关键词，RRF 融合排序。

    适用场景：通用检索，兼顾语义匹配和关键词精确匹配。
    """
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    retriever = get_hybrid_retriever()
    start = time.perf_counter()
    try:
        results = retriever.retrieve(req.query, top_k=req.top_k)
    except Exception as e:
        log.error(f"Hybrid retrieval failed: {e}")
        raise HTTPException(500, f"检索失败: {e}")
    elapsed = (time.perf_counter() - start) * 1000
    return _build_response(req.query, results, elapsed)


@router.post("/dense", response_model=RetrievalResponse)
async def dense_retrieve(req: RetrievalRequest):
    """
    纯向量检索 — 仅 dense embedding 相似度搜索，不经过 BM25。

    适用场景：语义匹配优先，如「意思相近但关键词不同」的查询。
    """
    from documents.milvus_db import get_milvus_manager

    manager = get_milvus_manager()
    start = time.perf_counter()
    try:
        results = manager.search(query=req.query, top_k=req.top_k)
    except Exception as e:
        log.error(f"Dense retrieval failed: {e}")
        raise HTTPException(500, f"向量检索失败: {e}")
    elapsed = (time.perf_counter() - start) * 1000
    return _build_response(req.query, results, elapsed)


@router.post("/sparse", response_model=RetrievalResponse)
async def sparse_retrieve(req: RetrievalRequest):
    """
    纯 BM25 关键词检索 — 仅词频匹配，不使用向量。

    适用场景：精确关键词匹配，如 ATA 编号、零件型号、故障代码。
    """
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    # HybridRetriever 的 lazy init 会自动从 Milvus 同步文档到 BM25
    retriever = get_hybrid_retriever()
    bm25 = retriever.sparse_retriever
    start = time.perf_counter()
    try:
        results = bm25.retrieve(req.query, top_k=req.top_k)
    except Exception as e:
        log.error(f"Sparse retrieval failed: {e}")
        raise HTTPException(500, f"BM25 检索失败: {e}")
    elapsed = (time.perf_counter() - start) * 1000
    return _build_response(req.query, results, elapsed)
