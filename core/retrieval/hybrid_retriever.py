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
    dense_top_k: int = 10

    # Sparse retrieval (BM25)
    sparse_weight: float = 0.5
    sparse_top_k: int = 10

    # RRF parameters
    rrf_k: int = 60  # RRF constant

    # Final results
    final_top_k: int = 5

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

    def retrieve(self, query: str, top_k: Optional[int] = None) -> List[Document]:
        """
        Perform hybrid retrieval synchronously.

        Args:
            query: Search query
            top_k: Number of results (default from config)

        Returns:
            List of retrieved documents
        """
        top_k = top_k or self.config.final_top_k
        start_time = time.perf_counter()

        try:
            # Perform retrievals
            if self.config.enable_parallel:
                dense_results, sparse_results = self._parallel_retrieve(query)
            else:
                dense_results = self._dense_retrieve(query)
                sparse_results = self._sparse_retrieve(query)

            # Fuse results
            fused_results = self._rrf_fusion(dense_results, sparse_results)

            # Convert to documents
            documents = [
                r.document for r in fused_results[:top_k]
            ]

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

    async def aretrieve(self, query: str, top_k: Optional[int] = None) -> List[Document]:
        """
        Perform hybrid retrieval asynchronously.

        Args:
            query: Search query
            top_k: Number of results

        Returns:
            List of retrieved documents
        """
        top_k = top_k or self.config.final_top_k
        start_time = time.perf_counter()

        try:
            # Parallel async retrieval
            dense_task = asyncio.create_task(
                self._adense_retrieve(query)
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

            # Convert to documents
            documents = [r.document for r in fused_results[:top_k]]

            elapsed = (time.perf_counter() - start_time) * 1000
            log.info(
                f"Async hybrid retrieval: "
                f"final={len(documents)}, elapsed={elapsed:.1f}ms"
            )

            return documents

        except Exception as e:
            log.error(f"Async hybrid retrieval failed: {e}")
            return []

    def _dense_retrieve(self, query: str) -> List[RetrievalResult]:
        """Perform dense (vector) retrieval."""
        try:
            results = self.dense_manager.search(
                query=query,
                top_k=self.config.dense_top_k,
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

    async def _adense_retrieve(self, query: str) -> List[RetrievalResult]:
        """Async dense retrieval."""
        return await asyncio.get_running_loop().run_in_executor(None, self._dense_retrieve, query)

    async def _asparse_retrieve(self, query: str) -> List[RetrievalResult]:
        """Async sparse retrieval."""
        return await asyncio.get_running_loop().run_in_executor(None, self._sparse_retrieve, query)

    # Shared thread pool for parallel retrieval
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def _parallel_retrieve(
        self, query: str
    ) -> Tuple[List[RetrievalResult], List[RetrievalResult]]:
        """Perform parallel retrieval using threads."""
        dense_future = self._executor.submit(self._dense_retrieve, query)
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