# 闭环追踪矩阵 — retrieval-benchmark-expansion

> design v2.1 已通过独立 critic/defender 编码入口门禁。实现、永久测试和 commit 完成前不得标
> `closed`。

## 1. Tracking Matrix

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design 修订 | 实现证据 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-RBE-004..007/020 | accepted | v2.1 §2/§3/§8/§9 | `ActiveChannelPolicy`、禁用腿隔离、双关闭终止与 filter-preserving fallback | pending | disabled fallback/planner/MMR call-count；BM25-only zero dense forward | `tests/unit/test_retrieval_benchmark_channels.py`；`tests/e2e/test_retrieval_workflow_e2e.py` | verified-awaiting-commit |
| F-02 | Critical | REQ-RBE-016/017/021 | accepted | v2.1 §4.2/§9 | matrix minimal env、dotenv 禁用、本地组件 preflight 与 zero-network child | pending | hostile env + repository `.env` canary；API fallback 不可触发 | `tests/unit/test_benchmark_matrix_runner.py`；`tests/e2e/test_benchmark_matrix_child_e2e.py` | verified-awaiting-commit |
| F-03 | Critical | REQ-RBE-008/010/011/014 | accepted | v2.1 §5.4/§9 | graded qrels bundle、stable doc id、独立 public evaluator 与 depth gate | pending | known graded run；public depth>=100；production 不冒充 official | `tests/unit/test_public_ir_metrics.py`；`tests/unit/test_prepare_ir_benchmark.py` | verified-awaiting-commit |
| F-04 | High | REQ-RBE-007/021/022 | accepted | v2.1 §2.2/§2.3/§9 | 完整 cache identity 与 immutable `RetrievalExecutionInfo` | pending | canonical identity cache miss；并发/同步/异步 execution status | `tests/unit/test_retrieval_benchmark_channels.py` | verified-awaiting-commit |
| F-05 | High | REQ-RBE-002/003/016/022 | accepted | v2.1 §4.1/§4.2/§7/§9 | balanced rotation、effective config attestation、position report | pending | 每个位置覆盖；requested==effective；latency position trap | `tests/unit/test_benchmark_matrix_runner.py`；`tests/unit/test_benchmark_performance_metrics.py` | verified-awaiting-commit |
| F-06 | High | REQ-RBE-019/023 | accepted | v2.1 §6.1/§8/§9 | `WorkloadLimits`、单次/总 timeout、进程组回收、输出预算 | pending | corpus/disk/output bound；timeout/parent interrupt cleanup | `tests/unit/test_benchmark_matrix_runner.py` | verified-awaiting-commit |
| F-07 | High | REQ-RBE-013/015/021/023 | accepted | v2.1 §4.4/§5.3/§9 | generation bundle、atomic pointer/summary、file+parent fsync | pending | publish fault、旧 generation 保留、checkpoint fsync | `tests/unit/test_prepare_ir_benchmark.py`；`tests/unit/test_benchmark_matrix_runner.py` | verified-awaiting-commit |
| F-08 | High | REQ-RBE-008/009/020 | accepted | v2.1 §3/§6.2/§9 | active-policy index snapshot、分阶段资源指标、dataset Pareto | pending | BM25-only 不计 dense；partial store 拒绝；missing resource 非零 | `tests/unit/test_benchmark_performance_metrics.py`；`tests/unit/test_benchmark_matrix_runner.py` | verified-awaiting-commit |
| F-09 | High | REQ-RBE-020 | accepted | v2.1 §9；tasks T1..T3 | 单元 fault injection、documents route 写读一致性、真实 child | pending | targeted matrix + CI-equivalent unit/perf/E2E | `tests/unit/test_retrieval_benchmark_channels.py`；`tests/e2e/test_retrieval_workflow_e2e.py`；`tests/e2e/test_benchmark_matrix_child_e2e.py` | verified-awaiting-commit |
| F-10 | High | REQ-RBE-010/012..015/022 | accepted | v2.1 §5.2/§5.3/§7/§9 | hash selection、hash-suffixed slug、conversion summary 与 unavailable 分类 | pending | shuffled iterator byte-identical；slug collision；conversion unavailable | `tests/unit/test_prepare_ir_benchmark.py` | verified-awaiting-commit |

## 2. Gate

- 编码入口门禁：通过。critic 的 3 Critical + 7 High 均由 defender 接受并在 design v2.1 实质关闭。
- 实现与验证门禁：通过。F-01..F-10 均有实现证据、定向验证和永久回归路径。
- commit/合并门禁：待完成。当前工作树尚未创建功能 commit；补入 commit id 后，Critical/High
  才可按模板转 `closed`。

## 3. Traceability

```text
REQ-RBE-* -> design v2.1 -> tasks T* -> critic F-01..F-10 -> implementation -> tests -> commit
```
