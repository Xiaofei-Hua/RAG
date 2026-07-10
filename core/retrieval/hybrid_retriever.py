"""
Hybrid Retriever for Enterprise RAG Platform

Combines dense (vector) and sparse (BM25) retrieval with RRF fusion.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from dataclasses import dataclass

from langchain_core.documents import Document

from core.retrieval.bm25_retriever import BM25Retriever
from documents.milvus_db import MilvusManager
from utils.env_utils import (
    GRAPH_RAG_ENABLED,
    GRAPH_RAG_TOP_K,
    GRAPH_RAG_WEIGHT,
    RERANKER_CANDIDATE_TOP_K,
    RERANKER_ENABLED,
    RERANKER_TOP_K,
)
from utils.log_utils import log

__all__ = [
    "HybridRetriever",
    "HybridRetrieverConfig",
]


def _retrieval_cache_enabled() -> bool:
    """Env-gated retrieval-result cache (default on)."""
    import os

    return os.getenv("RETRIEVAL_CACHE_ENABLED", "true").lower() in ("1", "true", "yes", "on")


@dataclass
class HybridRetrieverConfig:
    """Configuration for hybrid retriever."""

    # Dense retrieval
    dense_weight: float = 0.5
    dense_top_k: int = RERANKER_CANDIDATE_TOP_K if RERANKER_ENABLED else 5

    # Sparse retrieval (BM25)
    sparse_weight: float = 0.5
    sparse_top_k: int = RERANKER_CANDIDATE_TOP_K if RERANKER_ENABLED else 5

    # RRF parameters
    rrf_k: int = 60  # RRF constant

    # Final results. Without a reranker, RRF+MMR output is the final ranking —
    # 3 is too aggressive a cut (loses relevant-but-lower-ranked evidence);
    # 5 matches the reranker-off candidate pool above.
    final_top_k: int = RERANKER_TOP_K if RERANKER_ENABLED else 5
    enable_reranker: bool = RERANKER_ENABLED

    # MMR de-redundancy (applied after RRF, optionally after reranker).
    # When enabled, near-duplicate chunks are removed in favour of diverse,
    # still-relevant evidence.
    enable_mmr: bool = True
    mmr_lambda: float = 0.7  # 1.0 = pure relevance, 0.0 = pure diversity

    # Performance
    enable_parallel: bool = True

    # GraphRAG leg (docs/specs/graphrag). Default OFF (REQ-GR-008): when False
    # the graph leg is never invoked and RRF normalisation excludes graph_weight,
    # so behaviour is byte-for-byte identical to the pre-graph implementation.
    enable_graph: bool = GRAPH_RAG_ENABLED
    graph_weight: float = GRAPH_RAG_WEIGHT
    graph_top_k: int = GRAPH_RAG_TOP_K


@dataclass
class RetrievalResult:
    """Single retrieval result."""

    document: Document
    score: float
    source: str  # "dense", "sparse", or "hybrid"
    rank: int = 0


class HybridRetriever:
    """
    Hybrid retriever combining dense and sparse retrieval.

    Uses Reciprocal Rank Fusion (RRF) to combine results from
    multiple retrievers for improved recall and precision.

    RRF Formula:
        RRF(d) = Σ 1/(k + rank(d)) for each retriever ranking

    Features:
    - Parallel retrieval for performance
    - Configurable weights for dense/sparse
    - RRF fusion algorithm
    - Optional reranking
    """

    def __init__(
        self,
        dense_manager: MilvusManager | None = None,
        sparse_retriever: BM25Retriever | None = None,
        config: HybridRetrieverConfig | None = None,
    ):
        """
        Initialize hybrid retriever.

        Args:
            dense_manager: Milvus manager for dense retrieval
            sparse_retriever: BM25 retriever for sparse retrieval
            config: Retrieval configuration
        """
        self.config = config or HybridRetrieverConfig()
        self._dense_manager = dense_manager
        self._sparse_retriever = sparse_retriever
        self._initialized = False
        # Per-instance executor for the parallel dense/sparse sync legs. The
        # legacy class-level ThreadPoolExecutor(max_workers=2) was a process-wide
        # serialization point (2 workers shared across every request); it is now
        # instance-scoped with a configurable worker count, and shut down in
        # close() (wired into api.main lifespan shutdown). The async path uses
        # run_in_executor(None, ...) (default pool) and is intentionally left
        # unchanged — it is not bottlenecked.
        import os

        try:
            workers = max(2, int(os.getenv("RETRIEVAL_PARALLEL_WORKERS", "4")))
        except (TypeError, ValueError):
            workers = 4
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=workers)

        log.debug(
            f"HybridRetriever created: "
            f"dense_weight={self.config.dense_weight}, "
            f"sparse_weight={self.config.sparse_weight}, "
            f"parallel_workers={workers}"
        )

    def close(self) -> None:
        """Release the parallel-retrieval thread pool. Idempotent."""
        ex = getattr(self, "_executor", None)
        if ex is not None:
            try:
                ex.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass

    @property
    def dense_manager(self) -> MilvusManager:
        """Get dense retriever (lazy initialization)."""
        if self._dense_manager is None:
            from documents.milvus_db import get_milvus_manager

            self._dense_manager = get_milvus_manager()
        return self._dense_manager

    @property
    def sparse_retriever(self) -> BM25Retriever:
        """Get the shared BM25 singleton (auto-synced from Milvus on cold start).

        Returns the process-wide ``get_bm25_retriever()`` singleton — the same
        instance the documents router writes to on add/remove. This closes the
        historical divergence where the hybrid retriever built its own
        ``BM25Retriever()`` instance that never saw runtime document mutations.
        """
        if self._sparse_retriever is None:
            from core.retrieval.bm25_retriever import get_bm25_retriever

            self._sparse_retriever = get_bm25_retriever()
        self._ensure_sparse_indexed()
        return self._sparse_retriever

    def _ensure_sparse_indexed(self) -> None:
        """Bootstrap the shared BM25 singleton from Milvus on cold start only.

        The singleton is incrementally maintained by the documents write path
        (add/remove call ``add_documents``/``remove_by_source`` on it directly),
        so once it has an index we never re-bootstrap — its own
        ``_index_built``/``_documents`` flags are authoritative. This only runs
        on a cold process (or after an explicit ``clear()``) to hydrate BM25
        from the durable Milvus store.
        """
        if self._sparse_retriever._index_built and self._sparse_retriever._documents:
            return  # Singleton already holds an index maintained by the write path.
        try:
            results = self.dense_manager.query(
                filter_expr="id > 0",
                output_fields=["text", "source", "title"],
                limit=10000,
            )
            if results:
                docs = [
                    Document(
                        page_content=r.get("text", ""),
                        metadata={
                            "source": r.get("source", ""),
                            "title": r.get("title", ""),
                        },
                    )
                    for r in results
                    if r.get("text")
                ]
                if docs:
                    self._sparse_retriever.add_documents(docs)
                    log.info(f"BM25 index loaded from Milvus: {len(docs)} docs")
        except Exception as e:
            log.debug(f"BM25 Milvus sync skipped (collection may not exist): {e}")

    # ------------------------------------------------------------------
    # Cache helpers (F19 — single source of truth for version folding +
    # deepcopy placement, so the sync and async retrieve paths cannot drift)
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key_for(query: str, filter_expr: str | None, top_k: int) -> str:
        """Build the versioned retrieval cache key (single source)."""
        from core.retrieval.cache import cache_key, get_retrieval_cache_version

        return cache_key(
            "hybrid",
            query,
            filter_expr or "",
            top_k,
            get_retrieval_cache_version(),
        )

    @staticmethod
    def _cache_get(key: str) -> list[Document] | None:
        """Read-through cache helper. Returns None on any failure (degrade to
        live retrieval — never break the path over caching)."""
        if not _retrieval_cache_enabled():
            return None
        try:
            from core.retrieval.cache import get_retrieval_cache

            return get_retrieval_cache().get(key)
        except Exception as e:  # noqa: BLE001
            log.debug(f"retrieval cache read skipped: {e}")
            return None

    @staticmethod
    def _cache_put(key: str, documents: list[Document]) -> None:
        """Write cache helper. Deep-copies so downstream mutations to the
        returned Document objects do not corrupt the cached entry."""
        if not _retrieval_cache_enabled():
            return
        try:
            import copy

            from core.retrieval.cache import get_retrieval_cache

            get_retrieval_cache().put(key, copy.deepcopy(documents))
        except Exception as e:  # noqa: BLE001
            log.debug(f"retrieval cache write skipped: {e}")

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_expr: str | None = None,
    ) -> list[Document]:
        """
        Perform hybrid retrieval synchronously.

        Args:
            query: Search query
            top_k: Number of results (default from config)
            filter_expr: optional Milvus boolean expression to pre-filter
                dense candidates (e.g. ``source == "engine_manual"``).

        Returns:
            List of retrieved documents
        """
        top_k = top_k or self.config.final_top_k
        start_time = time.perf_counter()

        # Result cache: identical (query, filter, top_k) returns instantly.
        # The cache is best-effort; on any failure we fall through to live
        # retrieval (never break the path over caching).
        # Result cache: identical (query, filter, top_k, version) returns
        # instantly. Version-folding + read are centralised in _cache_get /
        # _cache_key_for so sync and async cannot drift.
        cache_key_str = self._cache_key_for(query, filter_expr, top_k)
        cached = self._cache_get(cache_key_str)
        if cached is not None:
            log.debug(f"Hybrid retrieval cache HIT (key={cache_key_str[:8]})")
            return cached

        try:
            # Perform retrievals
            if self.config.enable_parallel:
                dense_results, sparse_results, graph_results = self._parallel_retrieve(
                    query, filter_expr
                )
            else:
                dense_results = self._dense_retrieve(query, filter_expr)
                sparse_results = self._sparse_retrieve(query)
                graph_results = self._graph_retrieve(query, filter_expr)

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results, graph_results)

            # Pipeline order: RRF → time_decay → rerank → MMR. time_decay MUST
            # run before rerank so the decayed `score` feeds the reranker's
            # blend signal; running it after rerank left decay with no ranking
            # effect whenever the reranker was on (its `rerank_score` then
            # dominated MMR). See time_decay.py docstring (B6).
            documents = [r.document for r in fused_results]
            documents = self._time_decay(documents)
            documents = self._rerank(query, documents, top_k)
            documents = self._mmr(query, documents, top_k)

            elapsed = (time.perf_counter() - start_time) * 1000
            graph_count = len(graph_results) if isinstance(graph_results, list) else 0
            log.info(
                f"Hybrid retrieval completed: "
                f"dense={len(dense_results)}, sparse={len(sparse_results)}, "
                f"graph={graph_count}, final={len(documents)}, "
                f"elapsed={elapsed:.1f}ms"
            )

            # Persist into the result cache (deep-copy + version folded in the
            # shared _cache_put helper so sync/async cannot drift).
            self._cache_put(cache_key_str, documents)

            return documents

        except Exception as e:
            log.error(f"Hybrid retrieval failed: {e}")
            # Fallback to dense only
            try:
                results = self._dense_retrieve(query)
                return [r.document for r in results[:top_k]]
            except Exception:
                return []

    async def aretrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_expr: str | None = None,
    ) -> list[Document]:
        """
        Perform hybrid retrieval asynchronously.

        Args:
            query: Search query
            top_k: Number of results
            filter_expr: optional Milvus boolean expression to pre-filter.

        Returns:
            List of retrieved documents
        """
        top_k = top_k or self.config.final_top_k
        start_time = time.perf_counter()

        # Result cache (parity with the sync path via the shared helpers).
        cache_key_str = self._cache_key_for(query, filter_expr, top_k)
        cached = self._cache_get(cache_key_str)
        if cached is not None:
            log.debug(f"Async hybrid retrieval cache HIT (key={cache_key_str[:8]})")
            return cached

        try:
            # Parallel async retrieval
            dense_task = asyncio.create_task(self._adense_retrieve(query, filter_expr))
            sparse_task = asyncio.create_task(self._asparse_retrieve(query))
            tasks = [dense_task, sparse_task]
            if self.config.enable_graph:
                graph_task = asyncio.create_task(self._agraph_retrieve(query, filter_expr))
                tasks.append(graph_task)

            gathered = await asyncio.gather(*tasks, return_exceptions=True)
            dense_results = gathered[0]
            sparse_results = gathered[1]
            graph_results = gathered[2] if len(gathered) > 2 else []

            # Handle exceptions
            if isinstance(dense_results, Exception):
                log.warning(f"Dense retrieval failed: {dense_results}")
                dense_results = []
            if isinstance(sparse_results, Exception):
                log.warning(f"Sparse retrieval failed: {sparse_results}")
                sparse_results = []
            if isinstance(graph_results, Exception):
                log.warning(f"Graph retrieval failed: {graph_results}")
                graph_results = []

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results, graph_results)

            # Pipeline order mirrors the sync path: RRF → time_decay → rerank →
            # MMR (B6 — decay before rerank so the decayed score feeds rerank).
            documents = [r.document for r in fused_results]
            documents = self._time_decay(documents)
            documents = await self._arerank(query, documents, top_k)
            documents = await self._ammr(query, documents, top_k)

            elapsed = (time.perf_counter() - start_time) * 1000
            graph_count = len(graph_results) if isinstance(graph_results, list) else 0
            log.info(
                f"Async hybrid retrieval: final={len(documents)}, "
                f"graph={graph_count}, elapsed={elapsed:.1f}ms"
            )

            # Persist into the result cache via the shared helper (deep-copy +
            # version folded in one place).
            self._cache_put(cache_key_str, documents)

            return documents

        except Exception as e:
            log.error(f"Async hybrid retrieval failed: {e}")
            return []

    def _dense_retrieve(self, query: str, filter_expr: str | None = None) -> list[RetrievalResult]:
        """Perform dense (vector) retrieval, optionally pre-filtered."""
        try:
            results = self.dense_manager.search(
                query=query,
                top_k=self.config.dense_top_k,
                filter_expr=filter_expr,
            )

            return [
                RetrievalResult(
                    document=r.to_document(),
                    score=r.score,
                    source="dense",
                    rank=i + 1,
                )
                for i, r in enumerate(results)
            ]
        except Exception as e:
            log.warning(f"Dense retrieval failed: {e}")
            return []

    def _sparse_retrieve(self, query: str) -> list[RetrievalResult]:
        """Perform sparse (BM25) retrieval."""
        try:
            return self.sparse_retriever.retrieve(query, self.config.sparse_top_k)
        except Exception as e:
            log.warning(f"Sparse retrieval failed: {e}")
            return []

    async def _adense_retrieve(
        self, query: str, filter_expr: str | None = None
    ) -> list[RetrievalResult]:
        """Async dense retrieval."""
        return await asyncio.get_running_loop().run_in_executor(
            None, self._dense_retrieve, query, filter_expr
        )

    async def _asparse_retrieve(self, query: str) -> list[RetrievalResult]:
        """Async sparse retrieval."""
        return await asyncio.get_running_loop().run_in_executor(None, self._sparse_retrieve, query)

    def _graph_retrieve(self, query: str, filter_expr: str | None = None) -> list[RetrievalResult]:
        """GraphRAG leg (third RRF leg). Gated by ``enable_graph``.

        Degrades to ``[]`` on any failure (REQ-GR-003) — never raises, so the
        surrounding RRF path falls back to dense+sparse transparently.
        """
        if not self.config.enable_graph:
            return []
        try:
            from core.retrieval.graph_retriever import get_graph_retriever

            return get_graph_retriever().retrieve(
                query,
                top_k=self.config.graph_top_k,
                filter_expr=filter_expr,
            )
        except Exception as e:  # noqa: BLE001 — degrade to empty
            log.warning(f"Graph retrieval failed, degraded to empty: {e}")
            return []

    async def _agraph_retrieve(
        self, query: str, filter_expr: str | None = None
    ) -> list[RetrievalResult]:
        """Async graph leg."""
        return await asyncio.get_running_loop().run_in_executor(
            None, self._graph_retrieve, query, filter_expr
        )

    def _rerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """Optionally apply a cross-encoder after RRF fusion."""
        if not self.config.enable_reranker:
            return documents[:top_k]

        from core.retrieval.reranker import get_reranker

        return get_reranker().rerank(query, documents, top_k=top_k)

    async def _arerank(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """Async counterpart of the optional cross-encoder stage."""
        if not self.config.enable_reranker:
            return documents[:top_k]

        from core.retrieval.reranker import get_reranker

        return await get_reranker().arerank(query, documents, top_k=top_k)

    def _time_decay(self, documents: list[Document]) -> list[Document]:
        """Apply gentle time-decay scoring (P3.7). No-op without timestamps."""
        if not documents:
            return documents
        try:
            from core.retrieval.time_decay import apply_time_decay

            return apply_time_decay(documents)
        except Exception as e:  # noqa: BLE001
            log.debug(f"time-decay skipped: {e}")
            return documents

    def _mmr(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """
        Optional MMR de-redundancy stage.

        Runs after RRF (and reranker if enabled). When MMR embeddings are
        unavailable it silently returns the input unchanged so retrieval never
        fails on this account.
        """
        if not self.config.enable_mmr or len(documents) <= 1:
            return documents[:top_k]

        from core.retrieval.mmr import mmr_rerank

        try:
            return mmr_rerank(query, documents, top_k=top_k, lambda_=self.config.mmr_lambda)
        except Exception as e:  # noqa: BLE001
            log.debug(f"MMR skipped: {e}")
            return documents[:top_k]

    async def _ammr(
        self,
        query: str,
        documents: list[Document],
        top_k: int,
    ) -> list[Document]:
        """Async counterpart of the MMR stage (offloads to executor)."""
        if not self.config.enable_mmr or len(documents) <= 1:
            return documents[:top_k]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._mmr, query, documents, top_k)

    def _parallel_retrieve(
        self, query: str, filter_expr: str | None = None
    ) -> tuple[list[RetrievalResult], list[RetrievalResult]]:
        """Perform parallel retrieval using threads.

        Returns ``(dense, sparse, graph)``; the graph leg runs only when
        ``enable_graph`` is on and degrades to ``[]`` on any failure.
        """
        dense_future = self._executor.submit(self._dense_retrieve, query, filter_expr)
        sparse_future = self._executor.submit(self._sparse_retrieve, query)
        dense_results = dense_future.result()
        sparse_results = sparse_future.result()
        graph_results: list[RetrievalResult] = []
        if self.config.enable_graph:
            graph_future = self._executor.submit(self._graph_retrieve, query, filter_expr)
            try:
                graph_results = graph_future.result()
            except Exception as e:  # noqa: BLE001 — graph leg degrades to empty
                log.warning(f"Graph retrieval leg failed, degraded to empty: {e}")
                graph_results = []
        return dense_results, sparse_results, graph_results

    def _rrf_fusion(
        self,
        dense_results: list[RetrievalResult],
        sparse_results: list[RetrievalResult],
        graph_results: list[RetrievalResult] | None = None,
    ) -> list[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF) to combine retrieval results.

        RRF(d) = Σ w_i / (k + rank_i(d))

        The GraphRAG leg (``graph_results``) joins as a third retriever when
        ``enable_graph`` is on and the leg produced hits. F-04 gate: when graph
        is off (or empty), ``graph_weight`` is excluded from the normalisation
        denominator so dense/sparse weights stay byte-for-byte identical to the
        pre-graph implementation (REQ-GR-008 zero-change default).

        Args:
            dense_results: Results from dense retrieval
            sparse_results: Results from sparse retrieval
            graph_results: Results from the graph leg (optional)

        Returns:
            Fused and ranked results
        """
        # F-04 weight normalisation. The graph weight participates only when
        # the leg is both enabled AND non-empty; otherwise the denominator is
        # dense+sparse so the existing two-leg scores are unchanged.
        use_graph = bool(graph_results) and self.config.enable_graph
        if use_graph:
            total = self.config.dense_weight + self.config.sparse_weight + self.config.graph_weight
        else:
            total = self.config.dense_weight + self.config.sparse_weight
        dense_w = self.config.dense_weight / total
        sparse_w = self.config.sparse_weight / total
        graph_w = self.config.graph_weight / total if use_graph else 0.0

        # Build document ID to result mapping
        doc_scores: dict[str, tuple[float, RetrievalResult]] = {}

        def _fold(results: list[RetrievalResult], weight: float) -> None:
            if not weight:
                return
            for result in results:
                doc_id = self._get_doc_id(result.document)
                rrf_score = weight / (self.config.rrf_k + max(result.rank, 1))
                if doc_id in doc_scores:
                    existing_score, existing_result = doc_scores[doc_id]
                    doc_scores[doc_id] = (existing_score + rrf_score, existing_result)
                else:
                    doc_scores[doc_id] = (rrf_score, result)

        _fold(dense_results, dense_w)
        _fold(sparse_results, sparse_w)
        if use_graph:
            _fold(graph_results or [], graph_w)

        # Sort by combined score
        sorted_results = sorted(doc_scores.values(), key=lambda x: x[0], reverse=True)

        # Create final results with updated scores
        fused_results = []
        for rank, (score, result) in enumerate(sorted_results, 1):
            result.score = score
            result.source = "hybrid"
            result.rank = rank
            metadata = dict(result.document.metadata)
            metadata["retrieval_score"] = float(score)
            metadata["score"] = float(score)
            metadata["retrieval_source"] = "hybrid"
            result.document = Document(
                page_content=result.document.page_content,
                metadata=metadata,
            )
            fused_results.append(result)

        log.debug(f"RRF fusion: {len(fused_results)} results")
        return fused_results

    def _get_doc_id(self, document: Document) -> str:
        """Generate unique ID for document deduplication.

        Hashes the full ``page_content`` (not just a prefix) so that two chunks
        sharing a long boilerplate header — common in aviation manuals — are not
        collapsed into one RRF entry and silently dropped from fusion.
        """
        import hashlib

        content = document.page_content
        return hashlib.md5(content.encode()).hexdigest()[:16]


# Module-level instance
_hybrid_retriever: HybridRetriever | None = None


def get_hybrid_retriever(config: HybridRetrieverConfig | None = None) -> HybridRetriever:
    """Get or create hybrid retriever instance."""
    global _hybrid_retriever
    if _hybrid_retriever is None or config is not None:
        _hybrid_retriever = HybridRetriever(config=config)
    return _hybrid_retriever
