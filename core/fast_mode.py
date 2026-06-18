"""
Fast Mode Pipeline for Enterprise RAG Platform

Skips the full LangGraph pipeline and directly retrieves + generates.
Uses exactly 1 retrieval call + 1 LLM call for minimal latency.

Thinking mode (current graph): Intent → Agent → Retrieve → Grade → Generate  (4+ LLM calls)
Fast mode (this module):       Retrieve → Generate                               (1 LLM call)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from core.prompts.aircraft_prompts import GENERATE_SYSTEM_PROMPT, GENERATE_HUMAN_PROMPT
from utils.log_utils import log
from utils.think_tag_utils import strip_think_tags, build_fast_mode_prompt

__all__ = [
    "FastModeResult",
    "fast_generate",
    "fast_generate_async",
    "fast_generate_stream",
]

# Module-level chain cache
_chain = None


@dataclass
class FastModeResult:
    answer: str
    sources: List[Dict[str, Any]]
    retrieval_count: int
    retrieval_time_ms: float
    generation_time_ms: float


def _format_context(documents) -> str:
    """Format retrieved documents into context string.

    Delegates to the shared :mod:`core.retrieval.formatting` layer (the single
    source of truth for the evidence-line format). The Chinese fallback labels
    (未知来源/未知标题) are preserved via ``defaults`` so existing prompts are
    unaffected.
    """
    from core.retrieval.formatting import format_documents

    context, _ = format_documents(
        documents, defaults={"source": "未知来源", "title": "未知标题"}
    )
    return context


def _docs_to_sources(documents) -> List[Dict[str, Any]]:
    """Convert retrieved Documents to source dicts for API response."""
    sources = []
    for doc in documents:
        meta = getattr(doc, "metadata", None) or {}
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        sources.append({
            "content": content[:500],
            "source": meta.get("source"),
            "title": meta.get("title"),
            "score": meta.get("score", 0.0),
            "retrieval_score": meta.get("retrieval_score"),
            "rerank_score": meta.get("rerank_score"),
            "rerank_applied": bool(meta.get("rerank_applied", False)),
        })
    return sources


# Fast mode prompt — appends /no_think to suppress Qwen3 reasoning
_FAST_HUMAN_PROMPT = GENERATE_HUMAN_PROMPT.rstrip() + "\n\n/no_think"


def _get_chain(llm: BaseChatModel):
    """Build the generate chain (cached across calls)."""
    global _chain
    if _chain is None:
        prompt = ChatPromptTemplate.from_messages([
            ("system", GENERATE_SYSTEM_PROMPT),
            ("human", _FAST_HUMAN_PROMPT),
        ])
        _chain = prompt | llm | StrOutputParser()
    return _chain


# Cache for the streaming prompt chain (no StrOutputParser — we iterate chunks directly)
_stream_prompt = ChatPromptTemplate.from_messages([
    ("system", GENERATE_SYSTEM_PROMPT),
    ("human", _FAST_HUMAN_PROMPT),
])


def fast_generate(query: str, top_k: int = 3) -> FastModeResult:
    """
    Fast mode: direct retrieve + generate (synchronous).
    Uses /no_think to suppress Qwen3 reasoning for lower latency.

    Args:
        query: User question
        top_k: Number of documents to retrieve

    Returns:
        FastModeResult with answer, sources, and timing info
    """
    # --- Retrieve ---
    t0 = time.perf_counter()
    from core.retrieval.hybrid_retriever import get_hybrid_retriever
    retriever = get_hybrid_retriever()
    documents = retriever.retrieve(query, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    log.info(f"Fast mode retrieval: {len(documents)} docs, {retrieval_ms:.0f}ms")

    if not documents:
        return FastModeResult(
            answer="当前知识库中暂无相关文档。请先通过文档管理页面上传排故手册、维修手册等资料，然后再进行提问。",
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
        )

    # --- Generate ---
    context = _format_context(documents)
    if len(context) > 2500:
        context = context[:2500] + "\n...[内容已截断]"

    from models.llm_models import get_llm
    llm = get_llm()
    chain = _get_chain(llm)

    t1 = time.perf_counter()
    answer = chain.invoke({"question": query, "context": context})
    answer = strip_think_tags(answer)
    gen_ms = (time.perf_counter() - t1) * 1000

    log.info(f"Fast mode generation: {len(answer)} chars, {gen_ms:.0f}ms")

    return FastModeResult(
        answer=answer,
        sources=_docs_to_sources(documents),
        retrieval_count=len(documents),
        retrieval_time_ms=retrieval_ms,
        generation_time_ms=gen_ms,
    )


async def fast_generate_stream(query: str, top_k: int = 3) -> AsyncIterator[Dict[str, Any]]:
    """
    Fast mode: direct retrieve + streaming generate.

    Yields SSE-style event dicts:
        {"type": "status", ...}
        {"type": "token", "content": ...}
        {"type": "sources", "data": [...]}
        {"type": "done", ...}

    Args:
        query: User question
        top_k: Number of documents to retrieve
    """
    # --- Retrieve ---
    t0 = time.perf_counter()
    from core.retrieval.hybrid_retriever import get_hybrid_retriever
    retriever = get_hybrid_retriever()
    documents = await retriever.aretrieve(query, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t0) * 1000

    log.info(f"Fast mode retrieval: {len(documents)} docs, {retrieval_ms:.0f}ms")

    if not documents:
        yield {"type": "token", "content": "当前知识库中暂无相关文档。请先通过文档管理页面上传排故手册、维修手册等资料，然后再进行提问。"}
        yield {"type": "done", "full_response": "", "sources": [], "processing_time_ms": retrieval_ms}
        return

    context = _format_context(documents)
    if len(context) > 2500:
        context = context[:2500] + "\n...[内容已截断]"

    # --- Stream generate ---
    from models.llm_models import get_llm
    llm = get_llm()
    chain = _stream_prompt | llm

    t1 = time.perf_counter()
    full_response = ""
    async for chunk in chain.astream({"question": query, "context": context}):
        if hasattr(chunk, "content") and chunk.content:
            full_response += chunk.content
            yield {"type": "token", "content": chunk.content}
    gen_ms = (time.perf_counter() - t1) * 1000

    full_response = strip_think_tags(full_response)

    log.info(f"Fast mode stream done: {len(full_response)} chars, {gen_ms:.0f}ms")

    yield {
        "type": "done",
        "full_response": full_response,
        "sources": _docs_to_sources(documents),
        "processing_time_ms": retrieval_ms + gen_ms,
    }


async def fast_generate_async(query: str, top_k: int = 3) -> FastModeResult:
    """Native async fast mode for non-streaming API calls."""
    t0 = time.perf_counter()
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    documents = await get_hybrid_retriever().aretrieve(query, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t0) * 1000
    if not documents:
        return FastModeResult(
            answer="当前知识库中暂无相关文档。请先通过文档管理页面上传排故手册、维修手册等资料，然后再进行提问。",
            sources=[],
            retrieval_count=0,
            retrieval_time_ms=retrieval_ms,
            generation_time_ms=0,
        )

    context = _format_context(documents)
    if len(context) > 2500:
        context = context[:2500] + "\n...[内容已截断]"

    from models.llm_models import get_llm

    t1 = time.perf_counter()
    answer = await _get_chain(get_llm()).ainvoke(
        {"question": query, "context": context}
    )
    answer = strip_think_tags(answer)
    generation_ms = (time.perf_counter() - t1) * 1000
    return FastModeResult(
        answer=answer,
        sources=_docs_to_sources(documents),
        retrieval_count=len(documents),
        retrieval_time_ms=retrieval_ms,
        generation_time_ms=generation_ms,
    )
