"""
Query transformation strategies to lift retrieval recall on multi-hop / abstract
queries that a single rewrite cannot reach.

Two strategies (both LLM-driven, local Qwen3):
  - HyDE (Hypothetical Document Embeddings): generate a hypothetical answer to
    the query, then embed THAT answer to retrieve — closer to the answer's
    distribution than the question's.
  - Multi-Query: generate N reformulations of the query, retrieve for each,
    then fuse the result lists with RRF.

Both are optional and degrade to the original query on any failure (LLM down,
parse error) so retrieval never hard-fails on their account.

These are NOT wired into the default retrieve path (which already has a
rewrite loop); they are exposed for the retrieve skill to use when enabled via
``shared_state["query_transform"]`` = ``"hyde"`` | ``"multi_query"``.
"""

from __future__ import annotations

import re

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = ["hyde", "multi_query_retrieve"]


# ---------------------------------------------------------------------------
# Shared LLM helper
# ---------------------------------------------------------------------------


def _llm_invoke(prompt: str) -> str | None:
    """Best-effort single LLM call. Returns None on any failure."""
    try:
        from langchain_core.messages import HumanMessage

        from models.llm_models import create_custom_llm

        llm = create_custom_llm(temperature=0.0)
        resp = llm.invoke([HumanMessage(content=prompt)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        return (text or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.debug(f"query-transform LLM call failed: {e}")
        return None


async def _allm_invoke(prompt: str) -> str | None:
    try:
        from langchain_core.messages import HumanMessage

        from models.llm_models import create_custom_llm

        llm = create_custom_llm(temperature=0.0)
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        return (text or "").strip() or None
    except Exception as e:  # noqa: BLE001
        log.debug(f"query-transform async LLM call failed: {e}")
        return None


# ---------------------------------------------------------------------------
# HyDE
# ---------------------------------------------------------------------------


def _hyde_prompt_template() -> str:
    """HyDE prompt template from the active domain profile (call-time read)."""
    from core.prompts.domain_profile import get_active_profile

    # The profile's hyde prompt uses {question}; map to the {query} arg here.
    return get_active_profile().prompts.get("hyde", "").replace("{question}", "{query}") or (
        "请针对下面的用户问题，写一段 100-150 字的假设性回答段落，"
        "用于检索。只输出段落本身。\n\n问题：{query}\n\n假设性回答："
    )


def hyde(query: str) -> str:
    """
    Generate a hypothetical document for the query (sync).

    Returns the hypothetical text to embed, or falls back to the original
    query when the LLM is unavailable.
    """
    text = _llm_invoke(_hyde_prompt_template().format(query=query[:300]))
    if not text:
        log.debug("HyDE: LLM unavailable, using original query")
        return query
    return text


async def ahyde(query: str) -> str:
    """Async HyDE."""
    text = await _allm_invoke(_hyde_prompt_template().format(query=query[:300]))
    return text or query


# ---------------------------------------------------------------------------
# Multi-Query
# ---------------------------------------------------------------------------


def _multi_query_prompt_template() -> str:
    """Multi-query prompt template from the active domain profile (call-time)."""
    from core.prompts.domain_profile import get_active_profile

    return get_active_profile().prompts.get("multi_query", "") or (
        "针对下面的用户问题，生成 {n} 个不同角度的、等价的检索查询，"
        "用于从知识库召回更多相关内容。每行一个，不要编号，不要解释。\n\n"
        "问题：{query}\n\n生成的{n}个查询："
    )


_Q_LINE_RE = re.compile(r"[^\n]{4,}")


def _parse_queries(raw: str, n: int) -> list[str]:
    """Extract up to n clean query lines from the LLM response."""
    lines = [line.strip().lstrip("0123456789.-、）)）:： ") for line in raw.splitlines()]
    lines = [line for line in lines if _Q_LINE_RE.fullmatch(line)]
    return lines[:n]


def multi_query_expand(query: str, n: int = 3) -> list[str]:
    """Generate N reformulations of the query (sync). Returns [original, ...]."""
    raw = _llm_invoke(_multi_query_prompt_template().format(query=query[:300], n=n))
    if not raw:
        return [query]
    extra = _parse_queries(raw, n)
    # De-dup, keep original first.
    out = [query]
    for q in extra:
        if q and q not in out:
            out.append(q)
    return out[: n + 1]


async def amulti_query_expand(query: str, n: int = 3) -> list[str]:
    """Async variant of multi_query_expand."""
    raw = await _allm_invoke(_multi_query_prompt_template().format(query=query[:300], n=n))
    if not raw:
        return [query]
    extra = _parse_queries(raw, n)
    out = [query]
    for q in extra:
        if q and q not in out:
            out.append(q)
    return out[: n + 1]


def _rrf_fuse(document_lists: list[list[Document]], k: int = 60) -> list[Document]:
    """Lightweight RRF over several retrieved lists (reuse score metadata)."""
    import hashlib

    scores: dict = {}
    for docs in document_lists:
        for rank, doc in enumerate(docs, 1):
            did = hashlib.md5(doc.page_content[:500].encode()).hexdigest()[:12]
            s = 1.0 / (k + rank)
            if did in scores:
                scores[did][0] += s
            else:
                scores[did] = [s, doc]
    ordered = sorted(scores.values(), key=lambda x: x[0], reverse=True)
    return [doc for _, doc in ordered]


def multi_query_retrieve(
    query: str,
    retriever,
    n: int = 3,
    top_k: int = 4,
    filter_expr: str | None = None,
) -> list[Document]:
    """
    Expand the query, retrieve for each, RRF-fuse, return top_k.

    ``retriever`` must expose ``retrieve(query, top_k, filter_expr)``.
    Falls back to a single retrieval when expansion fails.
    """
    queries = multi_query_expand(query, n=n)
    if len(queries) == 1:
        return retriever.retrieve(query, top_k=top_k, filter_expr=filter_expr)
    lists = []
    for q in queries:
        try:
            lists.append(retriever.retrieve(q, top_k=top_k, filter_expr=filter_expr))
        except Exception as e:  # noqa: BLE001
            log.debug(f"multi-query retrieve failed for '{q[:30]}': {e}")
    if not lists:
        return retriever.retrieve(query, top_k=top_k, filter_expr=filter_expr)
    fused = _rrf_fuse(lists)
    return fused[:top_k]


async def amulti_query_retrieve(
    query: str,
    retriever,
    n: int = 3,
    top_k: int = 4,
    filter_expr: str | None = None,
) -> list[Document]:
    """Async variant of multi_query_retrieve."""
    queries = await amulti_query_expand(query, n=n)
    if len(queries) == 1:
        return await retriever.aretrieve(query, top_k=top_k, filter_expr=filter_expr)
    import asyncio

    tasks = [retriever.aretrieve(q, top_k=top_k, filter_expr=filter_expr) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    lists = [r for r in results if isinstance(r, list)]
    if not lists:
        return await retriever.aretrieve(query, top_k=top_k, filter_expr=filter_expr)
    fused = _rrf_fuse(lists)
    return fused[:top_k]
