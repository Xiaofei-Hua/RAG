"""
Embedding + query-result cache (P3.6).

Caches:
  1. Query embeddings (BGE vectors) keyed on the query text — repeated queries
     skip the (CPU-bound) embedding call.
  2. Full hybrid-retrieval results keyed on (query, filter_expr, top_k) —
     repeated identical queries return cached docs instantly.

Uses an LRU cache (thread-safe). Cache size is configurable via env
``RETRIEVAL_CACHE_SIZE`` (default 512). Hit ratio is logged for observability.

This wraps the embedding model and the hybrid retriever transparently —
existing callers get caching for free.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from typing import Any, List, Optional

from utils.log_utils import log

__all__ = ["LRUCache", "cached_embedding_function", "cache_key", "get_retrieval_cache"]


def _max_size() -> int:
    try:
        return max(16, int(os.getenv("RETRIEVAL_CACHE_SIZE", "512")))
    except (TypeError, ValueError):
        return 512


class LRUCache:
    """Thread-safe bounded LRU cache."""

    def __init__(self, maxsize: int = 512):
        self._maxsize = maxsize
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._data),
                "maxsize": self._maxsize,
                "hits": self.hits,
                "misses": self.misses,
                "hit_ratio": self.hits / total if total else 0.0,
            }

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0


# Singleton caches.
_embedding_cache = LRUCache(maxsize=_max_size())
_retrieval_cache = LRUCache(maxsize=_max_size())


def get_retrieval_cache() -> LRUCache:
    return _retrieval_cache


def cache_key(*parts: Any) -> str:
    """Build a stable cache key from arbitrary parts."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class CachedEmbeddingFunction:
    """
    Wraps an embedding model to cache query embeddings.

    Only query embedding (``embed_query``) is cached — document embedding
    (``embed_documents``) is write-path and not cached (each doc embeds once
    during indexing).
    """

    def __init__(self, base):
        self._base = base

    def embed_query(self, text: str):
        key = cache_key(text)
        cached = _embedding_cache.get(key)
        if cached is not None:
            return cached
        vec = self._base.embed_query(text)
        _embedding_cache.put(key, vec)
        return vec

    def embed_documents(self, texts: List[str]):
        return self._base.embed_documents(texts)

    @property
    def base(self):
        return self._base


def cached_embedding_function(base):
    """Wrap an embedding model with query caching."""
    return CachedEmbeddingFunction(base)
