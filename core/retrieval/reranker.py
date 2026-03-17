"""
Reranker for Enterprise RAG Platform

Provides document reranking to improve retrieval quality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = ["Reranker"]


@dataclass
class RerankerConfig:
    """Configuration for reranker."""
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 5
    batch_size: int = 8


class Reranker:
    """
    Document reranker using cross-encoder models.

    Reranks retrieved documents based on query-document relevance.
    Can use local models or API-based reranking services.
    """

    def __init__(self, config: Optional[RerankerConfig] = None):
        """
        Initialize reranker.

        Args:
            config: Reranker configuration
        """
        self.config = config or RerankerConfig()
        self._model = None

        log.debug(f"Reranker initialized: model={self.config.model_name}")

    def _load_model(self):
        """Lazy load the cross-encoder model."""
        if self._model is not None:
            return

        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.config.model_name)
            log.info(f"Reranker model loaded: {self.config.model_name}")
        except ImportError:
            log.warning("sentence-transformers not installed, reranking disabled")
        except Exception as e:
            log.warning(f"Failed to load reranker model: {e}")

    def rerank(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Document]:
        """
        Rerank documents by relevance to query.

        Args:
            query: Search query
            documents: Documents to rerank
            top_k: Number of documents to return

        Returns:
            Reranked documents
        """
        if not documents:
            return []

        top_k = top_k or self.config.top_k

        # If no model available, return original order
        self._load_model()
        if self._model is None:
            return documents[:top_k]

        try:
            # Create query-document pairs
            pairs = [(query, doc.page_content) for doc in documents]

            # Score pairs
            scores = self._model.predict(pairs)

            # Sort by score
            scored_docs = list(zip(documents, scores))
            scored_docs.sort(key=lambda x: x[1], reverse=True)

            # Return top-k
            reranked = [doc for doc, score in scored_docs[:top_k]]

            log.debug(f"Reranked {len(documents)} documents -> {len(reranked)}")
            return reranked

        except Exception as e:
            log.warning(f"Reranking failed: {e}")
            return documents[:top_k]

    async def arerank(
        self,
        query: str,
        documents: List[Document],
        top_k: Optional[int] = None,
    ) -> List[Document]:
        """Async reranking."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.rerank,
            query,
            documents,
            top_k
        )


# Module-level instance
_reranker: Optional[Reranker] = None


def get_reranker() -> Reranker:
    """Get or create reranker instance."""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker