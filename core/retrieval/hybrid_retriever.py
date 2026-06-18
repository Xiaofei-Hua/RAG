"""
Hybrid Retriever for Enterprise RAG Platform

Combines dense (vector) and sparse (BM25) retrieval with RRF fusion.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from documents.milvus_db import MilvusManager, MilvusConfig
from core.retrieval.bm25_retriever import BM25Retriever
from utils.env_utils import (
    RERANKER_CANDIDATE_TOP_K,
    RERANKER_ENABLED,
    RERANKER_TOP_K,
)
from utils.log_utils import log

__all__ = [
    "HybridRetriever",
    "HybridRetrieverConfig",
]


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

    # Final results
    final_top_k: int = RERANKER_TOP_K if RERANKER_ENABLED else 3
    enable_reranker: bool = RERANKER_ENABLED

    # MMR de-redundancy (applied after RRF, optionally after reranker).
    # When enabled, near-duplicate chunks are removed in favour of diverse,
    # still-relevant evidence.
    enable_mmr: bool = True
    mmr_lambda: float = 0.7  # 1.0 = pure relevance, 0.0 = pure diversity

    # Performance
    enable_parallel: bool = True


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
        dense_manager: Optional[MilvusManager] = None,
        sparse_retriever: Optional[BM25Retriever] = None,
        config: Optional[HybridRetrieverConfig] = None,
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

        log.debug(
            f"HybridRetriever created: "
            f"dense_weight={self.config.dense_weight}, "
            f"sparse_weight={self.config.sparse_weight}"
        )

    @property
    def dense_manager(self) -> MilvusManager:
        """Get dense retriever (lazy initialization)."""
        if self._dense_manager is None:
            from documents.milvus_db import get_milvus_manager
            self._dense_manager = get_milvus_manager()
        return self._dense_manager

    @property
    def sparse_retriever(self) -> BM25Retriever:
        """Get sparse retriever (lazy initialization, auto-synced from Milvus)."""
        if self._sparse_retriever is None:
            self._sparse_retriever = BM25Retriever()
        self._ensure_sparse_indexed()
        return self._sparse_retriever

    def _ensure_sparse_indexed(self) -> None:
        """Load documents from Milvus into BM25 if the index is empty."""
        if self._sparse_retriever._index_built and self._sparse_retriever._documents:
            return  # Already indexed
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

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_expr: Optional[str] = None,
    ) -> List[Document]:
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

        try:
            # Perform retrievals
            if self.config.enable_parallel:
                dense_results, sparse_results = self._parallel_retrieve(query, filter_expr)
            else:
                dense_results = self._dense_retrieve(query, filter_expr)
                sparse_results = self._sparse_retrieve(query)

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results)

            documents = [r.document for r in fused_results]
            documents = self._rerank(query, documents, top_k)
            documents = self._time_decay(documents)
            documents = self._mmr(query, documents, top_k)

            elapsed = (time.perf_counter() - start_time) * 1000
            log.info(
                f"Hybrid retrieval completed: "
                f"dense={len(dense_results)}, sparse={len(sparse_results)}, "
                f"final={len(documents)}, elapsed={elapsed:.1f}ms"
            )

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
        top_k: Optional[int] = None,
        filter_expr: Optional[str] = None,
    ) -> List[Document]:
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

        try:
            # Parallel async retrieval
            dense_task = asyncio.create_task(
                self._adense_retrieve(query, filter_expr)
            )
            sparse_task = asyncio.create_task(
                self._asparse_retrieve(query)
            )

            dense_results, sparse_results = await asyncio.gather(
                dense_task, sparse_task, return_exceptions=True
            )

            # Handle exceptions
            if isinstance(dense_results, Exception):
                log.warning(f"Dense retrieval failed: {dense_results}")
                dense_results = []
            if isinstance(sparse_results, Exception):
                log.warning(f"Sparse retrieval failed: {sparse_results}")
                sparse_results = []

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results)

            documents = [r.document for r in fused_results]
            documents = await self._arerank(query, documents, top_k)
            documents = self._time_decay(documents)
            documents = await self._ammr(query, documents, top_k)

            elapsed = (time.perf_counter() - start_time) * 1000
            log.info(
                f"Async hybrid retrieval: "
                f"final={len(documents)}, elapsed={elapsed:.1f}ms"
            )

            return documents

        except Exception as e:
            log.error(f"Async hybrid retrieval failed: {e}")
            return []

    def _dense_retrieve(
        self, query: str, filter_expr: Optional[str] = None
    ) -> List[RetrievalResult]:
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

    def _sparse_retrieve(self, query: str) -> List[RetrievalResult]:
        """Perform sparse (BM25) retrieval."""
        try:
            return self.sparse_retriever.retrieve(query, self.config.sparse_top_k)
        except Exception as e:
            log.warning(f"Sparse retrieval failed: {e}")
            return []

    async def _adense_retrieve(
        self, query: str, filter_expr: Optional[str] = None
    ) -> List[RetrievalResult]:
        """Async dense retrieval."""
        return await asyncio.get_running_loop().run_in_executor(
            None, self._dense_retrieve, query, filter_expr
        )

    async def _asparse_retrieve(self, query: str) -> List[RetrievalResult]:
        """Async sparse retrieval."""
        return await asyncio.get_running_loop().run_in_executor(None, self._sparse_retrieve, query)

    def _rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
    ) -> List[Document]:
        """Optionally apply a cross-encoder after RRF fusion."""
        if not self.config.enable_reranker:
            return documents[:top_k]

        from core.retrieval.reranker import get_reranker

        return get_reranker().rerank(query, documents, top_k=top_k)

    async def _arerank(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
    ) -> List[Document]:
        """Async counterpart of the optional cross-encoder stage."""
        if not self.config.enable_reranker:
            return documents[:top_k]

        from core.retrieval.reranker import get_reranker

        return await get_reranker().arerank(query, documents, top_k=top_k)

    def _time_decay(self, documents: List[Document]) -> List[Document]:
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
        documents: List[Document],
        top_k: int,
    ) -> List[Document]:
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
            return mmr_rerank(
                query, documents, top_k=top_k, lambda_=self.config.mmr_lambda
            )
        except Exception as e:  # noqa: BLE001
            log.debug(f"MMR skipped: {e}")
            return documents[:top_k]

    async def _ammr(
        self,
        query: str,
        documents: List[Document],
        top_k: int,
    ) -> List[Document]:
        """Async counterpart of the MMR stage (offloads to executor)."""
        if not self.config.enable_mmr or len(documents) <= 1:
            return documents[:top_k]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._mmr, query, documents, top_k)

    # Shared thread pool for parallel retrieval
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def _parallel_retrieve(
        self, query: str, filter_expr: Optional[str] = None
    ) -> Tuple[List[RetrievalResult], List[RetrievalResult]]:
        """Perform parallel retrieval using threads."""
        dense_future = self._executor.submit(self._dense_retrieve, query, filter_expr)
        sparse_future = self._executor.submit(self._sparse_retrieve, query)
        return dense_future.result(), sparse_future.result()

    def _rrf_fusion(
        self,
        dense_results: List[RetrievalResult],
        sparse_results: List[RetrievalResult],
    ) -> List[RetrievalResult]:
        """
        Reciprocal Rank Fusion (RRF) to combine retrieval results.

        RRF(d) = Σ w_i / (k + rank_i(d))

        Args:
            dense_results: Results from dense retrieval
            sparse_results: Results from sparse retrieval

        Returns:
            Fused and ranked results
        """
        # Build document ID to result mapping
        doc_scores: Dict[str, Tuple[float, RetrievalResult]] = {}

        # Process dense results
        for result in dense_results:
            doc_id = self._get_doc_id(result.document)
            rrf_score = self.config.dense_weight / (self.config.rrf_k + result.rank)

            if doc_id in doc_scores:
                existing_score, existing_result = doc_scores[doc_id]
                doc_scores[doc_id] = (existing_score + rrf_score, existing_result)
            else:
                doc_scores[doc_id] = (rrf_score, result)

        # Process sparse results
        for result in sparse_results:
            doc_id = self._get_doc_id(result.document)
            rrf_score = self.config.sparse_weight / (self.config.rrf_k + result.rank)

            if doc_id in doc_scores:
                existing_score, existing_result = doc_scores[doc_id]
                doc_scores[doc_id] = (existing_score + rrf_score, existing_result)
            else:
                doc_scores[doc_id] = (rrf_score, result)

        # Sort by combined score
        sorted_results = sorted(
            doc_scores.values(),
            key=lambda x: x[0],
            reverse=True
        )

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
        """Generate unique ID for document deduplication."""
        # Use content hash as ID
        import hashlib
        content = document.page_content[:500]  # Use first 500 chars
        return hashlib.md5(content.encode()).hexdigest()[:16]


# Module-level instance
_hybrid_retriever: Optional[HybridRetriever] = None


def get_hybrid_retriever(config: Optional[HybridRetrieverConfig] = None) -> HybridRetriever:
    """Get or create hybrid retriever instance."""
    global _hybrid_retriever
    if _hybrid_retriever is None or config is not None:
        _hybrid_retriever = HybridRetriever(config=config)
    return _hybrid_retriever
