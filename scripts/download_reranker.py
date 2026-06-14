#!/usr/bin/env python3
"""Download or validate the configured cross-encoder reranker."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.retrieval.reranker import get_reranker


def main() -> int:
    reranker = get_reranker()
    loaded = reranker.load()
    print(reranker.status())
    return 0 if loaded else 1


if __name__ == "__main__":
    raise SystemExit(main())
