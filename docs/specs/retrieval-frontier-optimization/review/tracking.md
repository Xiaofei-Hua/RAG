# 闭环追踪矩阵 — retrieval-frontier-optimization

> Critical/High 已在 design v2 接受或给出已落地的设计替代；代码、验证测试和回归固化完成前不得标
> `closed`。本表随每个 stage 更新。

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design.md 修订版本 | 实现证据 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-RFO-024/030 | accepted | v2 §3.5 | `core/retrieval/filter_scope.py`；各检索通道 capability 与 filter-preserving fallback | 未创建（用户未要求 commit） | `test_filter_scope_capabilities_are_typed_and_fail_closed`、`test_sync_fallback_never_drops_filter`、跨入口 invalid-filter E2E | `tests/unit/test_retrieval_frontier_filters.py`；`tests/e2e/test_retrieval_workflow_e2e.py` | verified-awaiting-commit |
| F-02 | High | REQ-RFO-012/015/023/030 | accepted | v2 §4.1/§4.4 | `core/retrieval/workflow.py`；Fast/Thinking/MCP 统一终态；retrieve skill 独占 diagnostics 整键 | 未创建（用户未要求 commit） | `test_retrieve_skill_is_unique_diagnostics_owner`、`test_fast_and_mcp_consume_same_workflow_terminal`、入口一致性 E2E | `tests/unit/test_retrieval_frontier_workflow.py`；`tests/e2e/test_retrieval_workflow_e2e.py` | verified-awaiting-commit |
| F-03 | High | REQ-RFO-004/005/021/030 | defended-with-alternative | v2 §3.2/§6 | `core/retrieval/query_representation.py`；单次原子前向、安全 legacy 降级、模型 fingerprint cache identity | 未创建（用户未要求 commit） | `test_query_representation_uses_one_forward_for_all_heads`、`test_query_representation_atomic_failure_uses_none_not_zero`、`test_embedding_cache_identity_includes_model_fingerprint` | `tests/unit/test_retrieval_frontier_representation.py` | verified-awaiting-commit |
| F-04 | High | REQ-RFO-019/022/024/030 | accepted | v2 §5.4 | `core/retrieval/visual_retriever.py`；全页 hash 资产、staging 原子发布、更新/删除/孤儿清理、OCR 降级 | 未创建（用户未要求 commit） | `test_visual_index_uses_all_pages_and_hash_addressed_assets`、`test_visual_update_collision_delete_and_orphan_cleanup_are_atomic`、`test_visual_oom_degrades_to_ocr_without_zero_visual_score` | `tests/unit/test_retrieval_frontier_visual.py` | verified-awaiting-commit |
| F-05 | Critical | REQ-RFO-017/022/024/030 | accepted | v2 §5.2 | `core/retrieval/raptor_store.py`；building/ready generation、source hash、原子发布、stale/delete 隔离 | 未创建（用户未要求 commit） | `test_raptor_building_generation_is_invisible_until_atomic_publish`、`test_raptor_failed_publish_keeps_prior_ready_generation`、`test_raptor_stale_filter_delete_and_concurrent_reads_are_source_safe` | `tests/unit/test_retrieval_frontier_raptor.py` | verified-awaiting-commit |
| F-06 | High | REQ-RFO-026/028/029 | accepted | v2 §8.1 | `scripts/run_paired_benchmark.py`；dataset×variant×order 独立进程/存储/cache，语料快照与 AB/BA 校验 | 未创建（用户未要求 commit） | `test_paired_benchmark_specs_isolate_dataset_variant_and_order`、`test_paired_benchmark_detects_ab_ba_quality_drift`、`test_corpus_snapshot_matches_ingestion_id_deduplication` | `tests/unit/test_retrieval_frontier_benchmark.py` | verified-awaiting-commit |

## 2. Gate

- 编码入口门禁：通过。所有 Critical/High 已由独立 defender 接受或给出 design v2 替代方案。
- 实现与验证门禁：通过。F-01..F-06 均有实现证据、定向验证与 CI 永久回归路径。
- commit 门禁：未通过。当前工作树尚未创建本功能 commit，因此 Critical/High 均如实保持
  `verified-awaiting-commit`，不得标 `closed`。
- 若用户授权 commit，补入 commit id 后重新核对四列，Critical 可转 `closed`；High 可转
  `closed`，F-03 也可保留 `defended-with-alternative` 并附已验证替代。

## 3. 四向追溯

```text
REQ-RFO-* -> design v2 section -> tasks.md task -> critic F-* -> implementation/test
```
