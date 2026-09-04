# Frontend Contract Hardening Review Tracking

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design 修订 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-FCH-002/005 | accepted | v2 §2.7 | `2c6f089`, PHM `8a5b80e` | contract-v2 PHM unit + Playwright | persisted false/null/blocked-storage cases | closed |
| F-02 | Critical | REQ-FCH-005 | accepted | v2 §2.4 | `2c6f089` | atomic exchange unit/E2E | Redis Lua + SQLite rollback/idempotency | closed |
| F-03 | Critical | REQ-FCH-004 | accepted | v2 §2.4/§3 | `2c6f089`, PHM `8a5b80e` | history completeness E2E + Playwright | empty/partial/double-failure states | closed |
| F-04 | Critical | REQ-FCH-001/002/007 | accepted | v2 §2.1-§2.3 | `2c6f089` | public-answer sanitizer unit/E2E | unclosed/nested/sync/stream cases | closed |
| F-05 | High | REQ-FCH-001/002 | accepted | v2 §2.2 | `2c6f089` | stream fallback/attempt E2E | custom/snapshot/fallback lifecycle | closed |
| F-06 | High | REQ-FCH-001/007 | accepted | v2 §2.1/§5 | `2c6f089` | sanitizer grammar unit + hotpath perf | case/nesting/tag/buffer bounds | closed |
| F-07 | High | REQ-FCH-003 | accepted | v2 §2.6/§6 | `2c6f089` | include_sources route matrix | sync/SSE × general/RAG/Fast | closed |
| F-08 | High | REQ-FCH-005-007 | accepted | v2 §2.4-§2.5/§5 | `2c6f089` | 26 hotpath + 2 perf tests | deadline/one-command/to_thread contracts | closed |
| F-09 | High | REQ-FCH-004/005 | accepted | v2 §2.4 | `2c6f089` | session merge/dedupe unit/E2E | split-shard stable-ID regression | closed |
| F-10 | High | REQ-FCH-004/005/007 | accepted | v2 §2.4/§5 | `2c6f089` | lock/heartbeat/deadline tests | SQLite worker + unknown timeout | closed |
| F-11 | High | REQ-FCH-001-005 | accepted | v2 §6 | `2c6f089` | chat early-return E2E matrix | identity/degraded/takeover regressions | closed |
| F-12 | Critical | REQ-FCH-002/005 | accepted | v2 §2.6-§2.7 | `2c6f089`, PHM `8a5b80e` | missing-v2/persistence unit + Playwright | unknown never becomes persisted | closed |
| F-13 | Critical | REQ-FCH-001/007 | accepted | v2 §2.6 | `2c6f089` | degraded/cache sanitizer E2E | no exception/reasoning disclosure | closed |
| F-14 | High | REQ-FCH-005 | accepted | v2 §2.4/§3 | `2c6f089` | retention/deadline unit + perf | late completion is null + replay-safe | closed |
| F-15 | High | REQ-FCH-001/002 | accepted | v2 §2.2 | `2c6f089` | custom/snapshot conflict E2E | prefix arbitration + error terminal | closed |
| F-16 | High | REQ-FCH-005 | accepted | v2 §2.4/§5 | `2c6f089` | Redis command/idempotency unit + perf | bounded-ID single Lua regression | closed |

Critical/High 只有在实现 commit、验证结果和永久回归测试三列全部填入后才能改为 `closed`。

## 2. Design Gate

v1 被阻塞；v2 已吸收全部复核 Critical/High。实现 `2c6f089` 与 PHM `8a5b80e` 已填写代码、验证和永久回归三列，16 项全部关闭。后端与 PHM 最终矩阵各连续两轮全绿；身份/租户项仍以既有 backlog + 发布门禁记录，不在本工作包虚构身份模型。
