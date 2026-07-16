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
import json
import math
import os
import statistics
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


def _ingest_corpus(corpus_by_id: dict[str, dict[str, Any]]) -> tuple[int, Any | None]:
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
        return 0, None
    manager = get_milvus_manager()
    try:
        manager.add_documents(docs)
        bm25 = get_bm25_retriever()
        bm25.clear()
        bm25.add_documents(docs)
        bump_retrieval_cache_version()
        log.info(f"Ingested {len(docs)} benchmark corpus chunks into Milvus + BM25")
        return len(docs), manager
    except Exception:
        manager.close()
        raise


def _owned_hybrid_retriever():
    from core.retrieval.hybrid_retriever import HybridRetriever

    return HybridRetriever()


def _close_embedding_registry() -> None:
    from documents.embedding_registry import reset_embedding_registry

    reset_embedding_registry()


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
    retriever=None,
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
    if retriever is None:
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


def _latency_summary(latencies_ms: list[float]) -> dict[str, float | None]:
    if not latencies_ms:
        return {"cold_ms": None, "warm_p50_ms": None, "warm_p95_ms": None}
    warm = sorted(latencies_ms[1:])
    if not warm:
        return {"cold_ms": latencies_ms[0], "warm_p50_ms": None, "warm_p95_ms": None}
    p95_index = max(0, min(len(warm) - 1, int(len(warm) * 0.95 + 0.999999) - 1))
    return {
        "cold_ms": latencies_ms[0],
        "warm_p50_ms": statistics.median(warm),
        "warm_p95_ms": warm[p95_index],
    }


def _quality_summary(run_metrics: list[dict[str, float]]) -> dict[str, float]:
    def values(key: str) -> list[float]:
        return [float(metrics[key]) for metrics in run_metrics]

    hit_rates = values("hit_rate")
    precisions = values("avg_context_precision")
    recalls = values("avg_context_recall")
    overlaps = values("avg_answer_overlap")
    return {
        "median_hit_rate": statistics.median(hit_rates),
        "worst_hit_rate": min(hit_rates),
        "median_context_precision": statistics.median(precisions),
        "worst_context_precision": min(precisions),
        "median_context_recall": statistics.median(recalls),
        "worst_context_recall": min(recalls),
        "median_answer_overlap_advisory": statistics.median(overlaps),
        "worst_answer_overlap_advisory": min(overlaps),
    }


async def _run(args: argparse.Namespace) -> int:
    cases = load_dataset(args.dataset)
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        log.error(f"No cases loaded from {args.dataset}")
        return 2

    ingest_manager = None
    retriever = None
    dense_manager = None
    try:
        corpus_by_id = _load_corpus(args.dataset)
        if corpus_by_id:
            _, ingest_manager = _ingest_corpus(corpus_by_id)
        else:
            log.warning("No corpus — retrieving against whatever is already indexed")
        text_index = _build_text_index(corpus_by_id)
        retriever = _owned_hybrid_retriever()

        print(f"\n{'=' * 64}")
        repeats = max(1, int(getattr(args, "repeats", 1)))
        print(
            f"Benchmark: {args.dataset}  "
            f"({len(cases)} cases, top_k={args.top_k}, repeats={repeats})"
        )
        print(f"{'=' * 64}")

        run_metrics = []
        all_latencies_ms = []
        total_started = time.perf_counter()
        for repeat_index in range(repeats):
            from core.retrieval.cache import get_retrieval_cache

            get_retrieval_cache().clear()
            rows = []
            latencies_ms = []
            print(f"\nRUN {repeat_index + 1}/{repeats}")
            for case in cases:
                query_started = time.perf_counter()
                retrieved = await _retrieve(
                    case.query,
                    top_k=args.top_k,
                    text_index=text_index,
                    corpus_by_id=corpus_by_id,
                    dedup_source=args.dedup_source,
                    retriever=retriever,
                )
                query_latency_ms = (time.perf_counter() - query_started) * 1000
                latencies_ms.append(query_latency_ms)
                retrieved_ids = [item["chunk_id"] for item in retrieved]
                precision, recall = _ctx_metrics(case.expected_context_ids, retrieved_ids)
                top_text = retrieved[0]["text"] if retrieved else ""
                answer_overlap = _answer_overlap(case.reference_answer, top_text)
                hit = bool(set(case.expected_context_ids) & set(retrieved_ids))
                rows.append(
                    {
                        "id": case.id,
                        "query": case.query[:40],
                        "ctx_precision": precision,
                        "ctx_recall": recall,
                        "answer_overlap": answer_overlap,
                        "retrieved_hit": hit,
                        "n_retrieved": len(retrieved),
                        "latency_ms": query_latency_ms,
                    }
                )
                flag = "✓" if hit else "✗"
                print(
                    f"  {flag} {case.id:<14} "
                    f"P={precision if precision is not None else 'n/a':<5} "
                    f"R={recall if recall is not None else 'n/a':<5} "
                    f"ans_ov={answer_overlap:.2f} latency={query_latency_ms:.1f}ms "
                    f"| {case.query[:30]}"
                )

            precisions = [x["ctx_precision"] for x in rows if x["ctx_precision"] is not None]
            recalls = [x["ctx_recall"] for x in rows if x["ctx_recall"] is not None]
            overlaps = [x["answer_overlap"] for x in rows]
            hits = sum(1 for x in rows if x["retrieved_hit"])
            metrics = {
                "hit_rate": hits / len(rows) if rows else 0.0,
                "avg_context_precision": (sum(precisions) / len(precisions) if precisions else 0.0),
                "avg_context_recall": sum(recalls) / len(recalls) if recalls else 0.0,
                "avg_answer_overlap": sum(overlaps) / len(overlaps) if overlaps else 0.0,
            }
            run_metrics.append(metrics)
            all_latencies_ms.extend(latencies_ms)
            print(
                f"  run aggregate: hit={metrics['hit_rate']:.1%}, "
                f"precision={metrics['avg_context_precision']:.3f}, "
                f"recall={metrics['avg_context_recall']:.3f}, "
                f"answer_overlap={metrics['avg_answer_overlap']:.3f} (advisory)"
            )

        elapsed = time.perf_counter() - total_started
        quality = _quality_summary(run_metrics)
        latency = _latency_summary(all_latencies_ms)

        print(f"\n{'-' * 64}")
        print(f"AGGREGATE ({len(cases)} cases x {repeats} runs, {elapsed:.1f}s)")
        print(
            "  hit rate median/worst                    : "
            f"{quality['median_hit_rate']:.1%}/{quality['worst_hit_rate']:.1%}"
        )
        print(
            "  context precision median/worst           : "
            f"{quality['median_context_precision']:.3f}/"
            f"{quality['worst_context_precision']:.3f}"
        )
        print(
            "  context recall median/worst              : "
            f"{quality['median_context_recall']:.3f}/{quality['worst_context_recall']:.3f}"
        )
        print(
            "  answer overlap median/worst (advisory)   : "
            f"{quality['median_answer_overlap_advisory']:.3f}/"
            f"{quality['worst_answer_overlap_advisory']:.3f}"
        )
        print(
            f"  latency cold/warm P50/P95 (ms)          : "
            f"{latency['cold_ms']!s}/{latency['warm_p50_ms']!s}/{latency['warm_p95_ms']!s}"
        )

        # --- regression gate: persist + compare against a stored baseline ---
        exit_code = 0
        metrics = {
            "hit_rate": quality["worst_hit_rate"],
            "avg_context_precision": quality["worst_context_precision"],
            "avg_context_recall": quality["worst_context_recall"],
            "avg_answer_overlap": quality["median_answer_overlap_advisory"],
            "n_cases": len(cases),
            "top_k": args.top_k,
            "dedup_source": args.dedup_source,
            "repeats": repeats,
            **quality,
            **latency,
        }
        if args.fail_on_regression:
            exit_code = _regression_gate(args.dataset, metrics)
        if args.update_baseline:
            _save_baseline(args.dataset, metrics)
            print("  (baseline updated)")
        print(f"{'-' * 64}\n")
        return exit_code
    finally:
        if retriever is not None:
            dense_manager = getattr(retriever, "_dense_manager", None)
            try:
                retriever.close()
            except Exception as exc:
                log.debug(f"Benchmark retriever close skipped: {exc}")
        if dense_manager is not None:
            try:
                dense_manager.close()
            except Exception as exc:
                log.debug(f"Benchmark dense manager close skipped: {exc}")
        if ingest_manager is not None:
            try:
                ingest_manager.close()
            except Exception as exc:
                log.debug(f"Benchmark ingest manager close skipped: {exc}")
        try:
            _close_embedding_registry()
        except Exception as exc:
            log.debug(f"Benchmark registry close skipped: {exc}")


BENCHMARK_RUNS_DIR = Path("data/eval/runs")
BENCHMARK_BASELINES_DIR = Path("data/benchmark/baselines")
BASELINE_SCHEMA_VERSION = 1
QUALITY_SEMANTICS_VERSION = 1
_GATE_METRIC_KEYS = ("hit_rate", "avg_context_precision", "avg_context_recall")
_BASELINE_METRIC_KEYS = (
    *_GATE_METRIC_KEYS,
    "avg_answer_overlap",
    "median_hit_rate",
    "worst_hit_rate",
    "median_context_precision",
    "worst_context_precision",
    "median_context_recall",
    "worst_context_recall",
    "median_answer_overlap_advisory",
    "worst_answer_overlap_advisory",
    "cold_ms",
    "warm_p50_ms",
    "warm_p95_ms",
)


def _baseline_path(dataset: str) -> Path:
    stem = Path(dataset).stem
    return BENCHMARK_BASELINES_DIR / f"{stem}_baseline.json"


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _baseline_config(dataset: str, metrics: dict[str, Any]) -> dict[str, Any]:
    from utils.env_utils import resolve_embedding_settings

    dataset_path = Path(dataset)
    corpus_path = dataset_path.with_name(dataset_path.stem + "_corpus.yaml")
    settings = resolve_embedding_settings()
    return {
        "dataset": dataset_path.stem,
        "dataset_sha256": _file_sha256(dataset_path),
        "corpus_sha256": _file_sha256(corpus_path),
        "n_cases": metrics.get("n_cases"),
        "top_k": metrics.get("top_k"),
        "dedup_source": metrics.get("dedup_source"),
        "repeats": metrics.get("repeats"),
        "embedding": {
            "provider": settings.provider,
            "model": settings.model,
            "dimension": settings.dimension,
            "sparse_enabled": settings.sparse_enabled,
        },
    }


def _baseline_payload(dataset: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "quality_semantics_version": QUALITY_SEMANTICS_VERSION,
        "config": _baseline_config(dataset, metrics),
        "metrics": {key: metrics.get(key) for key in _BASELINE_METRIC_KEYS},
    }


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _valid_sha256(value: Any, *, optional: bool = False) -> bool:
    if optional and value is None:
        return True
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def _baseline_validation_error(
    payload: Any,
    current_config: dict[str, Any],
) -> str | None:
    if not isinstance(payload, dict):
        return "baseline root must be an object"
    if payload.get("schema_version") != BASELINE_SCHEMA_VERSION:
        return "schema_version mismatch"
    if payload.get("quality_semantics_version") != QUALITY_SEMANTICS_VERSION:
        return "quality_semantics_version mismatch"

    config = payload.get("config")
    if not isinstance(config, dict):
        return "config must be an object"
    if not isinstance(config.get("dataset"), str) or not config["dataset"]:
        return "config.dataset must be a non-empty string"
    if not _valid_sha256(config.get("dataset_sha256")):
        return "config.dataset_sha256 must be a SHA-256 digest"
    if not _valid_sha256(config.get("corpus_sha256"), optional=True):
        return "config.corpus_sha256 must be a SHA-256 digest or null"
    for key in ("n_cases", "top_k", "repeats"):
        value = config.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return f"config.{key} must be a positive integer"
    if not isinstance(config.get("dedup_source"), bool):
        return "config.dedup_source must be boolean"
    embedding = config.get("embedding")
    if not isinstance(embedding, dict):
        return "config.embedding must be an object"
    if embedding.get("provider") not in {"local", "api"}:
        return "config.embedding.provider is invalid"
    if not isinstance(embedding.get("model"), str) or not embedding["model"]:
        return "config.embedding.model must be a non-empty string"
    dimension = embedding.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension <= 0:
        return "config.embedding.dimension must be a positive integer"
    if not isinstance(embedding.get("sparse_enabled"), bool):
        return "config.embedding.sparse_enabled must be boolean"
    if config != current_config:
        return "baseline config does not match the current benchmark"

    stored_metrics = payload.get("metrics")
    if not isinstance(stored_metrics, dict):
        return "metrics must be an object"
    for key in _GATE_METRIC_KEYS:
        value = stored_metrics.get(key)
        if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
            return f"metrics.{key} must be finite and within [0, 1]"
    for key in (
        "avg_answer_overlap",
        "median_hit_rate",
        "worst_hit_rate",
        "median_context_precision",
        "worst_context_precision",
        "median_context_recall",
        "worst_context_recall",
        "median_answer_overlap_advisory",
        "worst_answer_overlap_advisory",
    ):
        value = stored_metrics.get(key)
        if value is not None and (not _finite_number(value) or not 0.0 <= float(value) <= 1.0):
            return f"metrics.{key} must be finite and within [0, 1]"
    for key in ("cold_ms", "warm_p50_ms", "warm_p95_ms"):
        value = stored_metrics.get(key)
        if value is not None and (not _finite_number(value) or float(value) < 0.0):
            return f"metrics.{key} must be finite and non-negative"
    return None


def _save_baseline(dataset: str, metrics: dict[str, Any]) -> None:
    path = _baseline_path(dataset)
    payload = _baseline_payload(dataset, metrics)
    error = _baseline_validation_error(payload, payload["config"])
    if error:
        raise ValueError(f"refusing to write invalid benchmark baseline: {error}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _regression_gate(dataset: str, metrics: dict[str, Any]) -> int:
    """Compare current metrics to the stored baseline; return 1 on regression.

    A regression is a drop beyond a small tolerance (2 points = 0.02) in any of
    hit_rate / context_precision / context_recall. answer_overlap is advisory.
    Missing, malformed, or configuration-mismatched baselines fail closed.
    """
    bp = _baseline_path(dataset)
    if not bp.exists():
        print(f"\n!! BASELINE MISSING: {bp}")
        print("Run with --update-baseline after an explicitly reviewed benchmark run.\n")
        return 1
    try:
        with bp.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        current_config = _baseline_config(dataset, metrics)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"\n!! BASELINE INVALID: {exc}\n")
        return 1
    error = _baseline_validation_error(payload, current_config)
    if error:
        print(f"\n!! BASELINE INVALID: {error}\n")
        return 1
    base = payload["metrics"]

    for key in _GATE_METRIC_KEYS:
        value = metrics.get(key)
        if not _finite_number(value) or not 0.0 <= float(value) <= 1.0:
            print(f"\n!! CURRENT METRIC INVALID: {key}={value!r}\n")
            return 1

    tol = 0.02
    regressed = []
    for key in _GATE_METRIC_KEYS:
        cur = float(metrics[key])
        prev = float(base[key])
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
        "--repeats",
        type=int,
        default=3,
        choices=range(1, 101),
        metavar="1..100",
        help="Repeat retrieval to report median/worst quality (default: 3).",
    )
    parser.add_argument(
        "--dedup-source",
        action="store_true",
        help="Collapse same-source chunks to the top-scoring one (raises precision).",
    )
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Compare to stored baseline; exit 1 if metrics regress (CI gate).",
    )
    baseline_group.add_argument(
        "--update-baseline",
        action="store_true",
        help="Persist the current run as the new baseline.",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
