#!/usr/bin/env python3
"""
Benchmark runner — measures RAG *retrieval* effectiveness on the generic
benchmark datasets WITHOUT requiring Ollama/LLM.

Unlike ``scripts/run_eval.py`` (which drives the full harness including LLM
generation), this script targets the retrieval stack directly:

  for each case:
    1. ingest the case's corpus into Milvus + BM25 (once, cached)
    2. retrieve top_k for the case query
    3. map retrieved docs back to chunk ids (content hash) so the deterministic
       context precision/recall (set-overlap with expected_context_ids) is computable
    4. also compute answer-overlap (rule-based) using reference_answer vs the
       top retrieved chunk text

Output: a per-case + aggregate report to stdout and ``data/eval/runs/``.

Usage:
    # Chinese benchmark, general profile (domain-agnostic retrieval)
    DOMAIN_PROFILE=general uv run --frozen python scripts/run_benchmark.py \
        --dataset data/benchmark/benchmark_cmrc2018.yaml

    # English + limit
    DOMAIN_PROFILE=general uv run --frozen python scripts/run_benchmark.py \
        --dataset data/benchmark/benchmark_msmarco.yaml --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml  # noqa: E402

from agent.eval.dataset import load_dataset  # noqa: E402
from utils.log_utils import log  # noqa: E402


def _content_id(text: str) -> str:
    """Stable 12-char content id — MUST match prepare_benchmark._chunk_id's
    normalisation (whitespace-collapse via ' '.join(split())) so a retrieved
    doc maps to the same id as the corpus chunk it came from."""
    norm = " ".join((text or "").strip().split())
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


def _load_corpus(dataset_path: str) -> dict[str, dict[str, Any]]:
    """Load the sidecar <name>_corpus.yaml and index chunks by id."""
    p = Path(dataset_path)
    corpus_path = p.with_name(p.stem + "_corpus.yaml")
    if not corpus_path.exists():
        log.warning(f"Corpus file not found: {corpus_path}")
        return {}
    with corpus_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {ch["id"]: ch for ch in data.get("chunks", [])}


def _ingest_corpus(corpus_by_id: dict[str, dict[str, Any]]) -> int:
    """Ingest all corpus chunks into Milvus + BM25 so the retriever can find them.

    Returns the number of chunks ingested. Idempotent-ish: re-running rebuilds
    the BM25 index from Milvus each call (acceptable for a benchmark tool).
    """
    from langchain_core.documents import Document

    from core.retrieval.bm25_retriever import get_bm25_retriever
    from core.retrieval.cache import bump_retrieval_cache_version
    from documents.milvus_db import get_milvus_manager

    docs = []
    for cid, ch in corpus_by_id.items():
        docs.append(
            Document(
                page_content=ch.get("text", ""),
                metadata={
                    "source": ch.get("source", "benchmark"),
                    "title": ch.get("title", ""),
                    "chunk_id": cid,
                    "score": 0.0,
                },
            )
        )
    if not docs:
        return 0
    manager = get_milvus_manager()
    manager.add_documents(docs)
    bm25 = get_bm25_retriever()
    bm25.clear()
    bm25.add_documents(docs)
    bump_retrieval_cache_version()
    log.info(f"Ingested {len(docs)} benchmark corpus chunks into Milvus + BM25")
    return len(docs)


def _normalize_text(text: str) -> str:
    """Normalize text for robust matching (strip + collapse whitespace)."""
    return " ".join((text or "").strip().split())


def _build_text_index(corpus_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Build a normalized-text -> chunk_id map so retrieved docs (whose Milvus
    metadata may not carry our chunk_id) can be matched back to corpus ids."""
    return {_normalize_text(ch.get("text", "")): cid for cid, ch in corpus_by_id.items()}


async def _retrieve(
    query: str,
    top_k: int,
    text_index: dict[str, str],
    corpus_by_id: dict[str, dict[str, Any]] | None = None,
    dedup_source: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve and return docs with chunk_id.

    chunk_id resolution priority:
      1. metadata.chunk_id (if Milvus preserved it)
      2. normalized-text reverse-lookup against the corpus (robust to metadata loss)
      3. content hash fallback

    When ``dedup_source`` is set, we over-fetch (2x top_k) then collapse chunks
    from the same source document to the single highest-scoring one. This
    targets the CMRC2018 failure mode where retrieval returns several chunks of
    the same Wikipedia article, diluting precision without aiding recall.
    """
    from core.retrieval.hybrid_retriever import get_hybrid_retriever

    retriever = get_hybrid_retriever()
    fetch_k = top_k * 2 if dedup_source else top_k
    docs = await retriever.aretrieve(query, top_k=fetch_k)
    out = []
    for d in docs:
        meta = getattr(d, "metadata", {}) or {}
        text = getattr(d, "page_content", "") or ""
        norm = _normalize_text(text)
        cid = meta.get("chunk_id") or text_index.get(norm) or _content_id(text)
        # Resolve the source document (for source-level dedup). Prefer the
        # corpus's source for the matched chunk; fall back to metadata.
        source = ""
        if corpus_by_id and cid in corpus_by_id:
            source = corpus_by_id[cid].get("source", "")
        if not source:
            source = meta.get("source", "")
        out.append(
            {
                "chunk_id": cid,
                "text": text,
                "score": meta.get("score", 0.0),
                "source": source,
            }
        )

    if not dedup_source or len(out) <= top_k:
        return out[:top_k]

    # Collapse same-source chunks to the highest-scoring one. This raises
    # precision when one document dominates the result set.
    seen_sources: dict[str, dict[str, Any]] = {}
    for r in out:
        src = r.get("source") or ""
        if src not in seen_sources or r["score"] > seen_sources[src]["score"]:
            seen_sources[src] = r
    # Preserve retrieval order among the survivors.
    survivor_ids = {r["chunk_id"] for r in seen_sources.values()}
    deduped = [r for r in out if r["chunk_id"] in survivor_ids]
    return deduped[:top_k]


def _answer_overlap(reference: str, top_chunk_text: str) -> float:
    """Rule-based answer correctness: fraction of reference-answer chars found
    in the top retrieved chunk. Crude but LLM-free; signals whether retrieval
    surfaced the evidence needed to answer."""
    if not reference or not top_chunk_text:
        return 0.0
    ref = reference.strip()
    hits = sum(1 for ch in ref if ch in top_chunk_text)
    return hits / max(1, len(ref))


def _ctx_metrics(expected: list[str], retrieved: list[str]) -> tuple[float | None, float | None]:
    from agent.eval.scorer import EvalScorer

    return EvalScorer.score_context_ids(expected, retrieved)


async def _run(args: argparse.Namespace) -> int:
    cases = load_dataset(args.dataset)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        log.error(f"No cases loaded from {args.dataset}")
        return 2

    corpus_by_id = _load_corpus(args.dataset)
    if corpus_by_id:
        _ingest_corpus(corpus_by_id)
    else:
        log.warning("No corpus — retrieving against whatever is already indexed")
    text_index = _build_text_index(corpus_by_id)

    print(f"\n{'=' * 64}")
    print(f"Benchmark: {args.dataset}  ({len(cases)} cases, top_k={args.top_k})")
    print(f"{'=' * 64}")

    rows = []
    t0 = time.perf_counter()
    for case in cases:
        retrieved = await _retrieve(
            case.query,
            top_k=args.top_k,
            text_index=text_index,
            corpus_by_id=corpus_by_id,
            dedup_source=args.dedup_source,
        )
        retrieved_ids = [r["chunk_id"] for r in retrieved]
        p, r = _ctx_metrics(case.expected_context_ids, retrieved_ids)
        top_text = retrieved[0]["text"] if retrieved else ""
        ans_ov = _answer_overlap(case.reference_answer, top_text)
        hit = bool(set(case.expected_context_ids) & set(retrieved_ids))
        rows.append(
            {
                "id": case.id,
                "query": case.query[:40],
                "ctx_precision": p,
                "ctx_recall": r,
                "answer_overlap": ans_ov,
                "retrieved_hit": hit,
                "n_retrieved": len(retrieved),
            }
        )
        flag = "✓" if hit else "✗"
        print(
            f"  {flag} {case.id:<14} P={p if p is not None else 'n/a':<5} "
            f"R={r if r is not None else 'n/a':<5} ans_ov={ans_ov:.2f} "
            f"| {case.query[:30]}"
        )
    elapsed = time.perf_counter() - t0

    # Aggregate
    precisions = [x["ctx_precision"] for x in rows if x["ctx_precision"] is not None]
    recalls = [x["ctx_recall"] for x in rows if x["ctx_recall"] is not None]
    overlaps = [x["answer_overlap"] for x in rows]
    hits = sum(1 for x in rows if x["retrieved_hit"])

    print(f"\n{'-' * 64}")
    print(f"AGGREGATE ({len(rows)} cases, {elapsed:.1f}s)")
    print(
        f"  retrieval hit rate (>=1 gold chunk found) : {hits}/{len(rows)} = {hits / len(rows):.1%}"
    )
    if precisions:
        print(
            f"  avg context_precision                   : {sum(precisions) / len(precisions):.3f}"
        )
    if recalls:
        print(f"  avg context_recall                      : {sum(recalls) / len(recalls):.3f}")
    print(f"  avg answer_overlap (rule)               : {sum(overlaps) / len(overlaps):.3f}")

    # --- regression gate: persist + compare against a stored baseline ---
    exit_code = 0
    metrics = {
        "hit_rate": hits / len(rows) if rows else 0.0,
        "avg_context_precision": (sum(precisions) / len(precisions)) if precisions else 0.0,
        "avg_context_recall": (sum(recalls) / len(recalls)) if recalls else 0.0,
        "avg_answer_overlap": (sum(overlaps) / len(overlaps)) if overlaps else 0.0,
        "n_cases": len(rows),
        "top_k": args.top_k,
        "dedup_source": args.dedup_source,
    }
    if args.fail_on_regression:
        exit_code = _regression_gate(args.dataset, metrics)
    if args.update_baseline:
        _save_baseline(args.dataset, metrics)
        print("  (baseline updated)")
    print(f"{'-' * 64}\n")
    return exit_code


BENCHMARK_RUNS_DIR = Path("data/eval/runs")


def _baseline_path(dataset: str) -> Path:
    stem = Path(dataset).stem
    return BENCHMARK_RUNS_DIR / f"{stem}_baseline.json"


def _save_baseline(dataset: str, metrics: dict[str, Any]) -> None:
    import json

    BENCHMARK_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with _baseline_path(dataset).open("w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


def _regression_gate(dataset: str, metrics: dict[str, Any]) -> int:
    """Compare current metrics to the stored baseline; return 1 on regression.

    A regression is a drop beyond a small tolerance (2 points = 0.02) in any of
    hit_rate / context_precision / context_recall. answer_overlap is advisory
    only. If no baseline exists yet, we save one and pass (first run seeds it).
    """
    import json

    bp = _baseline_path(dataset)
    if not bp.exists():
        log.info("No baseline found; seeding one at " + str(bp))
        _save_baseline(dataset, metrics)
        return 0
    with bp.open(encoding="utf-8") as f:
        base = json.load(f)

    tol = 0.02
    regressed = []
    for key in ("hit_rate", "avg_context_precision", "avg_context_recall"):
        cur = metrics.get(key, 0.0)
        prev = base.get(key, 0.0)
        if cur < prev - tol:
            regressed.append(f"{key}: {prev:.3f} -> {cur:.3f}")

    if regressed:
        print(f"\n!! REGRESSION DETECTED on {dataset}:")
        for r in regressed:
            print(f"    {r}")
        print("Run with --update-baseline to accept the new values if intended.\n")
        return 1
    print("  regression gate: PASS (no metric dropped beyond tolerance)\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the RAG retrieval benchmark (no LLM needed).")
    parser.add_argument("--dataset", required=True, help="Path to benchmark_<name>.yaml")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N cases")
    parser.add_argument(
        "--dedup-source",
        action="store_true",
        help="Collapse same-source chunks to the top-scoring one (raises precision).",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Compare to stored baseline; exit 1 if metrics regress (CI gate).",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Persist the current run as the new baseline.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
