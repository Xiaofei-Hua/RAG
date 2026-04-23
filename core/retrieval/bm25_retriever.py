"""
BM25 Retriever for Enterprise RAG Platform

Implements sparse retrieval using BM25 algorithm for keyword matching.
Provides lexical search capability complementary to dense vector search.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document

from utils.log_utils import log

__all__ = ["BM25Retriever"]


@dataclass
class BM25Config:
    """Configuration for BM25 retriever."""
    k1: float = 1.5      # Term frequency saturation
    b: float = 0.75      # Document length normalization
    top_k: int = 5       # Number of results
    min_token_length: int = 1


class BM25Retriever:
    """
    BM25 sparse retriever for keyword-based search.

    BM25 Formula:
        score(D, Q) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))

    Features:
    - In-memory index for fast retrieval
    - Chinese text segmentation (jieba)
    - Document persistence support
    """

    def __init__(self, config: Optional[BM25Config] = None):
        """
        Initialize BM25 retriever.

        Args:
            config: BM25 configuration
        """
        self.config = config or BM25Config()
        self._documents: List[Document] = []
        self._doc_tokens: List[List[str]] = []
        self._doc_lengths: List[int] = []
        self._avgdl: float = 0.0
        self._idf: Dict[str, float] = {}
        self._doc_freq: Dict[str, int] = {}
        self._index_built = False

        log.debug("BM25Retriever initialized")

    def add_documents(self, documents: List[Document]):
        """
        Add documents to the BM25 index.

        Args:
            documents: Documents to index
        """
        for doc in documents:
            self._documents.append(doc)
            tokens = self._tokenize(doc.page_content)
            self._doc_tokens.append(tokens)
            self._doc_lengths.append(len(tokens))

        self._build_index()
        log.info(f"Added {len(documents)} documents to BM25 index")

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into terms."""
        if not text:
            return []
        text = self._normalize_text(text)

        # Try to use jieba for Chinese text
        try:
            import jieba
            tokens = list(jieba.cut(text))
        except ImportError:
            # Fallback for Chinese + English mixed text
            tokens = re.findall(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+", text.lower())

        # Filter short tokens
        min_len = self.config.min_token_length
        clean_tokens = []
        for t in tokens:
            token = t.strip().lower()
            if not token or len(token) < min_len:
                continue
            clean_tokens.append(token)
        return clean_tokens

    def _normalize_text(self, text: str) -> str:
        """Normalize query/document text for robust matching."""
        normalized = text.lower()
        # Unify common ATA forms: ATA32 / ATA-32 / ata 32 -> ata32
        normalized = re.sub(r"\bata[\s\-_:]*([0-9]{2})\b", r"ata\1", normalized)
        # Normalize repeated whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _build_index(self):
        """Build BM25 index from documents."""
        if not self._documents:
            return

        # Calculate average document length
        self._avgdl = sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 1

        # Build document frequency
        self._doc_freq = {}
        for tokens in self._doc_tokens:
            seen = set()
            for token in tokens:
                if token not in seen:
                    self._doc_freq[token] = self._doc_freq.get(token, 0) + 1
                    seen.add(token)

        # Calculate IDF for all terms
        n_docs = len(self._documents)
        self._idf = {}
        for term, df in self._doc_freq.items():
            # IDF formula with smoothing
            self._idf[term] = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)

        self._index_built = True
        log.debug(f"BM25 index built: {n_docs} docs, {len(self._idf)} terms")

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> List["RetrievalResult"]:
        """
        Retrieve documents using BM25 scoring.

        Args:
            query: Search query
            top_k: Number of results

        Returns:
            List of retrieval results
        """
        from core.retrieval.hybrid_retriever import RetrievalResult

        if not self._index_built or not self._documents:
            log.warning("BM25 index not built or empty")
            return []

        top_k = top_k or self.config.top_k
        query_tokens = self._tokenize(query)

        if not query_tokens:
            return []

        # Calculate BM25 scores for each document
        scores = []
        for doc_idx, doc_tokens in enumerate(self._doc_tokens):
            score = self._bm25_score(query_tokens, doc_tokens, doc_idx)
            if score > 0:
                scores.append((doc_idx, score))

        # Sort by score and get top-k
        scores.sort(key=lambda x: x[1], reverse=True)
        top_results = scores[:top_k]

        # Create retrieval results
        results = []
        for rank, (doc_idx, score) in enumerate(top_results, 1):
            results.append(RetrievalResult(
                document=self._documents[doc_idx],
                score=score,
                source="sparse",
                rank=rank,
            ))

        log.debug(f"BM25 retrieved {len(results)} results for query")
        return results

    def _bm25_score(
        self,
        query_tokens: List[str],
        doc_tokens: List[str],
        doc_idx: int,
    ) -> float:
        """Calculate BM25 score for a document."""
        score = 0.0
        doc_len = self._doc_lengths[doc_idx]
        doc_counter = Counter(doc_tokens)

        k1 = self.config.k1
        b = self.config.b
        avgdl = self._avgdl

        for term in query_tokens:
            if term not in self._idf:
                continue

            tf = doc_counter.get(term, 0)
            idf = self._idf[term]

            # BM25 formula
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc_len / avgdl)

            if denominator > 0:
                score += idf * (numerator / denominator)

        return score

    def clear(self):
        """Clear the index."""
        self._documents.clear()
        self._doc_tokens.clear()
        self._doc_lengths.clear()
        self._idf.clear()
        self._doc_freq.clear()
        self._avgdl = 0.0
        self._index_built = False
        log.debug("BM25 index cleared")

    def remove_by_source(self, source: str):
        """Remove documents matching a source filename and rebuild index."""
        if not self._documents or not source:
            return
        indices_to_remove = [
            i for i, doc in enumerate(self._documents)
            if doc.metadata.get("source") == source
        ]
        if not indices_to_remove:
            return
        for idx in sorted(indices_to_remove, reverse=True):
            del self._documents[idx]
            del self._doc_tokens[idx]
            del self._doc_lengths[idx]
        self._build_index()
        log.info(f"BM25 removed {len(indices_to_remove)} docs for source={source}")

    @property
    def stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            "document_count": len(self._documents),
            "term_count": len(self._idf),
            "avg_doc_length": self._avgdl,
            "index_built": self._index_built,
        }


# Module-level instance
_bm25_retriever: Optional[BM25Retriever] = None


def get_bm25_retriever() -> BM25Retriever:
    """Get or create BM25 retriever instance."""
    global _bm25_retriever
    if _bm25_retriever is None:
        _bm25_retriever = BM25Retriever()
    return _bm25_retriever
