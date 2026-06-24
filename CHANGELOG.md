# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
starting from 0.1.0.

## [Unreleased]

### Added — recall quality + precision (small-to-big) (`recall-quality-hyde-parent-store`, stage B)

- Wired `parent_store` small-to-big retrieval (was dead code: read side ready,
  write side never connected). `markdown_parser._chunk_documents` and
  `documents._split_documents` now tag every chunk with a `parent_id` and store
  the parent section text, so `expand_to_parents` swaps small-chunk hits for
  full-section context at retrieval time — improves both precision (small chunk
  hits the gold id) and generation quality (parent gives full context).
- `_maybe_expand_parents` now defaults ON when chunks carry `parent_id`
  (callers can still opt out via `shared_state["expand_parents"]=False`); old
  indexes without parent_id are a no-op.
- Wired HyDE / multi_query query transforms (were implemented but never
  triggered — `shared_state["query_transform"]` had no producer).
  `RetrieveSkill._decide_transform` picks a transform by heuristic: ATA/fault
  code -> none (precise anchor); diagnostic question -> hyde; short abstract
  symptom -> multi_query. Explicit `shared_state["query_transform"]` overrides.
- Added an LRU cache for query-transform LLM calls so the rewrite loop doesn't
  re-transform the same query.

### Fixed — benchmark source granularity (`recall-quality-hyde-parent-store`, stage B)

- `scripts/prepare_benchmark.py` set `source` to the dataset name ("cmrc2018"),
  so `--dedup-source` collapsed every article into one chunk — a metric artifact,
  not a recall gain. Now uses document-level `source` (`cmrc2018_wiki_{i}`) so
  dedup-source collapses only sibling chunks of the same article. Precision
  numbers measured before this fix were not meaningful.

### Fixed — Chinese retrieval stack (`retrieval-stack-bm25-reranker`, stage A)

- Restored the BM25 sparse retrieval leg for Chinese: `jieba` was never declared
  as a dependency, so `bm25_retriever._tokenize` silently fell back to a regex
  that collapsed whole Chinese sentences into a single token — Chinese queries
  shared zero terms with documents (BM25 score always 0, sparse leg empty,
  hybrid retrieval degraded to dense-only). Declaring `jieba` makes the
  already-written jieba path run; the regex fallback now `log.warning`s instead
  of degrading silently. (REQ-RS-001/002/006)
- `BM25Config.min_token_length` split into `min_token_length_zh=1` /
  `min_token_length_en=2` (script-aware): high-value aviation单字 (泵/阀/轴)
  survive while English single letters are dropped. (REQ-RS-003)
- Measured: CMRC2018 hit_rate 0.5→1.0, recall 0.5→1.0, answer_overlap
  0.835→0.967. (context_precision unchanged at 0.25 — a chunking bottleneck,
  not a ranking problem; deferred to stage B.)

### [breaking] — multilingual reranker (`retrieval-stack-bm25-reranker`, stage A)

- Switched the reranker from the English-only `cross-encoder/ms-marco-MiniLM-L-6-v2`
  to the multilingual `BAAI/bge-reranker-v2-m3`. The English model emitted noise
  logits on Chinese and reordered RRF output worse than chance. `.env` keys
  changed: `RERANKER_MODEL`, `RERANKER_MODEL_PATH`, `RERANKER_BATCH_SIZE` 8→4
  (CPU OOM defence, bge is ~568MB vs ms-marco 90MB). Air-gapped deployments must
  bundle the new model. (REQ-RS-004/005)

### Added — domain-adaptive agent (`domain-adaptive-profile`)

- New `core/prompts/domain_profile.py` `DomainProfile` layer + loader. The agent
  is no longer hardcoded to aviation PHM: prompts, routing keywords, output
  structure, identity text, refusal/empty messages, and the safety disclaimer
  are all sourced from the active domain profile (`data/profiles/<name>.yaml`),
  selected by the `DOMAIN_PROFILE` env var (default `aviation_phm`, preserving
  existing behaviour). (REQ-D-001..007)
- New domain profile `data/profiles/general.yaml` — a domain-agnostic profile
  (neutral prompts, no forced output sections, no domain keyword fast-path) so
  the same codebase serves any knowledge base. Switch with `DOMAIN_PROFILE=general`.
- New E2E coverage tests (`tests/e2e/test_e2e_coverage.py`) and domain-profile
  unit + switch tests (`tests/unit/test_domain_profile.py`,
  `tests/e2e/test_e2e_domain_switch.py`).

### Changed — bugfix-batch-2

- `astream` / `ainvoke_fast` now reset the per-run trace contextvar and emit the
  run summary, matching the other invocation entrypoints (was leaving the
  contextvar pointing at a finished collector). (B1)
- RAG streaming loop guards against non-dict stream events so a list-shaped
  payload no longer aborts generation mid-stream. (B2)
- RAG streaming `done` event now carries `confidence` / `confidence_level` /
  `refused`, matching the non-streaming response. (B4)
- `fast_generate_stream` empty-corpus `done.full_response` now carries the
  empty-corpus message (was an empty string). (B5)
- Document upload temp path is now the module-level `UPLOAD_TMP_DIR` attribute
  (was hardcoded `/tmp`), redirectable by the test fixture. (B6)
- Orphaned `processing` registry rows are recovered to `failed` before blocking
  re-upload, so a dead background worker no longer wedges documents. (B7)
- Degraded-response metadata now includes `route="degraded"` (parity with the
  eval capture and other routes). (B8)

### [security] — checkpoint serde compatibility (`checkpoint-serde-compat`)

- Closed CVE-2025-64439 (langgraph-checkpoint `JsonPlusSerializer` json-mode
  deserialisation RCE, CVSS 7.4), CVE-2025-67644 (checkpointer SQL injection),
  and CVE-2026-27794 (cache-layer RCE) by aligning `langgraph-checkpoint-sqlite`
  2.0.10 → 3.1.0 (which restricts json-mode deserialisation to an allow-list and
  uses `dumps_typed`/`json.dumps`). `langgraph-checkpoint` stays on 4.1.x.
  (REQ-CS-004)
- Forced strict msgpack deserialisation (`_enable_strict_msgpack_deserialization`
  in the orchestrator) so the msgpack path is no longer permissive by default —
  closes the remaining unregistered-type RCE surface. (F-CS-06)
- Pinned `aiosqlite<1.0` (it was a transitive dependency with no upper bound);
  the async saver relies on aiosqlite's private `_thread` attribute for liveness
  checks, which a 1.0 refactor could remove. (F-CS-06)

### Fixed — checkpoint serde compatibility (`checkpoint-serde-compat`)

- Resolved an `AttributeError: 'JsonPlusSerializer' object has no attribute
  'dumps'` that made every thinking-mode `invoke()`/`ainvoke()` (and thus the
  whole end-to-end eval, 15/15 cases) fail: `langgraph-checkpoint-sqlite 2.0.10`
  called the removed `.dumps()`/`.loads()` API. The two prior monkeypatches
  (import-time `_patch_jsonplus_serde_compat` + the `astart()` `is_alive`/dumps
  shim) are removed now that 3.x uses `dumps_typed`/`loads_typed` + `json`.
  (REQ-CS-001/002/007)
- `HarnessConfig.checkpoint_path` now resolves via `field(default_factory=...)`
  backed by a module-level `DEFAULT_CHECKPOINT_PATH`, so `tests/conftest.py
  tmp_data_dir` can redirect it (was a hardcoded dataclass default that ignored
  monkeypatch — AGENTS.md §10 persistence contract).
- `langgraph-checkpoint-sqlite 3.x` brings a new transitive dependency
  `sqlite-vec` (native C extension); offline/air-gapped deployments must bundle
  this wheel. (F-CS-04)

### [breaking] — checkpoint serde compatibility (`checkpoint-serde-compat`)

- Session checkpoints (`data/checkpoints.db`) are **not readable across the
  2.x↔3.x boundary**: the new `writes.idx`/delta semantics differ. After
  upgrading, **existing sessions cannot resume their context** (users must start
  a new session — a functional downgrade, not data corruption). Back up
  `data/checkpoints.db` before switching and delete it on first run with 3.x.
  (F-CS-05/07)

### [breaking] — domain-adaptive agent (`domain-adaptive-profile`)

- `metadata.prompt_profile` values are now derived from the active domain
  profile's `profile_label` (`<label>_diagnosis_v1` etc.). Under the default
  `aviation_phm` profile the label is `phm`, so existing values
  (`phm_diagnosis_v1`, `phm_fast_v1`, `phm_general_v1`, `phm_identity_v1`) are
  unchanged. Switching to a different profile changes these labels. **Migration:**
  none required for the default profile; consumers that hard-match `phm_*`
  should match the `profile_label` instead.
- New env var `DOMAIN_PROFILE` (default `aviation_phm`).

### Changed — bugfix-batch-1 (post adversarial review)

Architecture & contracts:
- Skills are directory-only (`agent/skills/<name>/skill.py`); the legacy flat
  `*_skill.py` shims have been removed. (F15)
- `api.main` exposes an `create_app()` factory; the module-level `app` is now
  factory-built. (F16)
- `LLMJudge` exposes public `entail`/`aentail`; the grounding guardrail no
  longer reaches into the underscore-private methods. (F17)
- Hybrid retriever cache helpers (`_cache_key_for`/`_cache_get`/`_cache_put`)
  centralise version folding + deepcopy so the sync/async retrieve paths cannot
  drift. (F19)

Correctness:
- BM25 read path now consumes the shared `get_bm25_retriever()` singleton (it
  previously built a private instance that never saw document mutations), and
  document add/remove bumps a retrieval-cache version so stale results are not
  served. (F01)
- `_get_doc_id` hashes the full page content (was first 500 chars), so chunks
  sharing a long header are no longer collapsed in RRF. (F18)
- `grade` conditional-edge path logs an error if state is produced on either
  loss channel (before-hook increment or skill `state_updates`), instead of
  silently dropping it. (F02)
- Removed a duplicate `from utils.log_utils import log` in `agent/context/state.py`. (F04)

Security:
- Admin auth compares the key via `hmac.compare_digest` (no length oracle), and
  `api.main` lifespan refuses to start in a production-unsafe config (no
  `ADMIN_API_KEY` + default CORS + not under `PYTEST_RUN`). (F05)
- `ExternalAPIToolsServer.http_get` disables redirects and verifies the
  post-connect peer IP against the resolved public set, closing the SSRF
  TOCTOU + redirect-follow window. (F06)
- Chinese prompt-injection patterns added to `INJECTION_PATTERNS`. (F07)
- PII detection tiers: human PII (incl. passport) detected by default; aircraft
  operational IDs (tail number, MSN) are NOT PII by default (gated behind
  `PII_DETECT_OPERATIONAL_IDS`); an opt-in `PII_LLM_PASS` reuses the judge
  circuit breaker and degrades to regex-only when unavailable. (F08)
- Calculator switched from `eval()` to an AST whitelist; `abs`/`pow`/`min`/
  `max`/`round` now work and injection attempts are rejected. (F09)
- PII redaction composes with ESCALATE (a hallucinated answer containing PII
  stays ESCALATE *and* is redacted on the served message), instead of
  pre-empting the escalation. (F10)

Concurrency / performance:
- Hybrid retriever's parallel executor is instance-scoped with configurable
  `RETRIEVAL_PARALLEL_WORKERS` (default 4) and shut down in `close()` (wired
  into lifespan shutdown). (F11)
- Sync `invoke()`/`stream()` serialised by a process lock so the shared sync
  SQLite checkpointer is not written concurrently across threads. (F12)
- Retrieval cache deepcopy cost benchmarked (`tests/perf/`). (F13)
- Per-run trace isolation on the singleton harness guarded by a concurrent
  test. (F14)

Dependencies / release:
- `paddlepaddle`/`paddleocr` moved to an optional `[ocr]` extra; `deploy.sh`
  installs it so the offline bundle retains OCR. (F20)
- LangChain/LangGraph pinned with compatible upper bounds. (F21)
- `.gitattributes` routes new model files (`.safetensors`/`.bin`/...) through
  Git LFS; the existing tracked `model.safetensors` is NOT migrated (would
  rewrite history). (F22)
- `CHANGELOG.md`, ruff config, and pre-commit hook added. (F23)

### Testing
- New unit/perf/e2e tests covering every finding above.
- `requires_ollama`/`requires_backend` markers registered; live-Ollama skill
  tests are skipped by default.
- `testpaths` extended to include `tests/perf`.
