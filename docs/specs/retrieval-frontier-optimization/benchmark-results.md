# Retrieval Frontier Optimization — Benchmark Results

## 1. Environment

- Date: 2026-07-16
- Profile: `general`
- Embedding: local BGE-M3, 1024 dimensions, native sparse enabled
- Reranker: local `bge-reranker-v2-m3`
- `top_k=4`, three repetitions per process
- Every dataset × variant × AB/BA position used a fresh process, Milvus DB, collection,
  embedding registry, RAPTOR DB, visual index/assets and cache namespace.
- The runner verified dataset/corpus hashes before and after each run, then verified the isolated
  collection row count and normalized content hash.

The generator model and embedding/reranker weights were not trained or modified. Improvements below come
from request-local query-representation reuse, typed planning, authority-safe ranking, bounded corrective
logic and consistent evidence selection.

## 2. Stage 1 Decision

The static enlarged candidate funnel and contextual index were not promoted. On the initial paired run,
the combined treatment reduced HotpotQA recall from `0.917` to `0.883` and MS MARCO recall from `0.833`
to `0.667`. Funnel-only MS MARCO was also `0.667`. Query-reuse-only reduced latency materially, but its
initial MS MARCO recall was `0.800`, a `0.033` absolute loss against that run's control. These options remain
reversible and default-off:

- `RETRIEVAL_CANDIDATE_FUNNEL_ENABLED=false`
- `CONTEXTUAL_INDEX_ENABLED=false`
- standalone legacy `enable_query_reuse` is not promoted independently

The final Stage 2 workflow reuses the query representation while preserving the compatibility candidate
budgets and cross-encoder ordering; that combination passed the controlled gate below.

## 3. Stage 2 Isolated AB/BA Result

Medians below combine the AB and BA processes for each variant. `forward` is the measured BGE-M3 query
forward count over all three repetitions.

| Dataset | Variant | Recall | MRR | nDCG | Warm P95 ms | Query forwards |
|---|---|---:|---:|---:|---:|---:|
| builtin_general | control | 1.000 | 1.000 | 1.000 | 107.9 | 56 |
| builtin_general | workflow | 1.000 | 1.000 | 1.000 | 70.8 | 24 |
| CMRC2018 | control | 1.000 | 0.911 | 0.934 | 196.9 | 210 |
| CMRC2018 | workflow | 1.000 | 0.961 | 0.971 | 155.4 | 90 |
| HotpotQA | control | 0.917 | 1.000 | 0.915 | 216.9 | 210 |
| HotpotQA | workflow | 0.917 | 1.000 | 0.919 | 165.7 | 90 |
| MS MARCO | control | 0.800 | 0.578 | 0.634 | 164.3 | 210 |
| MS MARCO | workflow | 0.800 | 0.597 | 0.648 | 110.8 | 90 |

Results:

- AB/BA order-independence: passed for every primary quality metric with tolerance `1e-9`.
- Promotion gate: passed on all four datasets; no primary quality loss exceeded `0.02`, and every warm P95
  ratio was below `1.25`.
- Query forwards fell by about 57% on the 30-case datasets and by about 57% on builtin_general.
- `RETRIEVAL_WORKFLOW_ENABLED` is therefore promoted to default-on. Explicit `false` restores the legacy
  retrieval path without deleting data.

Runtime summary: `/tmp/rfo_stage2_isolated_abba_v2_20260716/summary.json`.

## 4. Frontier Specialized Microbenchmarks

Five repetitions used the same deterministic fixture for the disabled/enabled variant. Synthetic token
encoders isolate algorithm correctness and fallback behavior; they are not evidence that a particular real
ColPali/ColBERT checkpoint should be promoted.

| Channel | Disabled quality | Enabled quality | Enabled P95 ms | Decision |
|---|---:|---:|---:|---|
| ColBERT MaxSim | 0.500 MRR | 1.000 MRR | 0.369 | keep off pending real-model long-chunk run |
| RAPTOR | 0.000 coverage | 1.000 coverage | 11.053 | keep off pending domain corpus/global-query run |
| Graph PPR/path | 0.000 MRR | 0.333 MRR | 2.292 | keep off pending extracted-graph multi-hop run |
| ColPali page | 0.000 hit | 1.000 hit | 0.325 | keep off; synthetic encoder and text-only generation |

Runtime result: `/tmp/rfo_frontier_specialized_20260716/results.json`.

## 5. Commands

```bash
uv run --frozen python scripts/run_paired_benchmark.py \
  --dataset data/benchmark/builtin_general.yaml \
  --dataset data/benchmark/benchmark_cmrc2018.yaml \
  --dataset data/benchmark/benchmark_hotpotqa.yaml \
  --dataset data/benchmark/benchmark_msmarco.yaml \
  --output-dir /tmp/rfo-stage2-abba \
  --top-k 4 --repeats 3

uv run --frozen python scripts/run_frontier_benchmark.py \
  --fixture data/benchmark/frontier_specialized.yaml \
  --repeats 5 \
  --work-dir /tmp/rfo-frontier/work \
  --output-json /tmp/rfo-frontier/results.json
```

## 6. Promotion and Rollback

- Default-on: shared adaptive/corrective `RetrievalWorkflow`.
- Default-off: enlarged candidate funnel, contextual indexing, ColBERT, RAPTOR, Graph PPR/path and ColPali.
- Contextual migration creates a new collection only:

```bash
uv run --frozen python scripts/migrate_embedding_collection.py \
  --target-collection rag_knowledge_base_context_v1 \
  --contextual-index \
  --sample-query "reviewed verification query"
```

- ColPali assets are prepared explicitly; runtime never downloads:

```bash
uv run --frozen python scripts/download_colpali.py \
  --output models/local_models/colpali
```

## 7. Verification Matrix

<!-- RAG_LLM_PR -->

| Scope | Command / evidence | Result |
|---|---|---|
| Slice red-green | `/tmp/rfo_*_red.log` and corresponding green logs | selector/workflow/ColBERT/RAPTOR/PPR/visual regressions captured |
| Retrieval/matrix targeted | retrieval channels, workflow, public IR, matrix runner and child E2E | `65 passed` |
| CI unit + perf | coverage-wrapped pytest with live-backend markers excluded | `968 passed, 4 deselected` |
| Process-internal E2E | coverage append with real backend excluded | `92 passed, 2 skipped` |
| Coverage | accumulated branch coverage | `72%` (`fail-under=60`) |
| Static/import checks | Ruff over repository; `python -c "import api.main; print('OK')"`; diff audit | passed; `OK` |
| UI | Playwright | N/A: no UI files changed by this feature |
