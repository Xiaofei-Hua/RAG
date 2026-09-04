# Defender 报告 — frontend-contract-hardening

**评审对象**: `review/critic.md` 与 v1 设计
**评审日期**: 2026-09-04

## 裁决表

| 发现 ID | 严重性 | 决策 | 理由 | design.md 修订条目 |
|---|---|---|---|---|
| F-01 | Critical | accepted | PHM allowlist 无字段且 session event 立即写 localStorage，场景可达 | v2 §2.7 |
| F-02 | Critical | accepted | message 粒度保存无法证明 exchange 原子性 | v2 §2.4 |
| F-03 | Critical | accepted | SQLite 非 Redis 镜像，健康空不代表完整空 | v2 §2.4/§3 |
| F-04 | Critical | accepted | regex 只移除完整闭合标签 | v2 §2.1-§2.3 |
| F-05 | High | accepted | 多 attempt/多发射点确实可触发状态串扰 | v2 §2.2 |
| F-06 | High | accepted | grammar/buffer/lifecycle 是安全边界必要契约 | v2 §2.1/§5 |
| F-07 | High | accepted | 所有 response assembly 都需固定矩阵 | v2 §2.6/§6 |
| F-08 | High | accepted | 无 socket timeout、同步 SQLite 会阻塞 event loop | v2 §2.4-§2.5/§5 |

## Critical / High 五步裁决

F-01—F-08 的事实均由对应源文件复核成立，且触发场景分别是 session→error、跨 backend 写、Redis 故障、未闭合标签、RAG takeover、边界 grammar、不同响应分支和半连接存储。影响均达到 High 以上，修复成本低到中等，全部属于 REQ-FCH-001—008 范围，故不作护短式拒绝。v2 已采用 critic 建议；反馈去重的唯一约束建议以 `BEGIN IMMEDIATE` + 稳定首条查询 + 跨 connection 测试替代，避免遗留重复数据迁移失败。

## 范围外问题清单

| 发现 | 转单 issue ID | 说明 |
|---|---|---|
| 身份/租户授权 | `RAG-KA-BL-001`, `RAG-KA-BL-004` | 正确实现需要明确身份来源和租户数据模型；本工作包维持 mutation 默认关闭及 local-only/认证网关发布门禁。 |

## 诚实承认的有限边界

- feedback 副作用是 commit 后 at-most-once/best-effort；进程在 commit 后、触发前崩溃可能造成零次，但不会因重试重复执行。
- Redis 故障后的 SQLite 不是历史镜像，因此只能诚实返回 `complete=false`，本工作包不承诺补齐故障前 Redis 历史。
- 浏览器联调证明应用层 SSE 与 Vite proxy，不声称控制 TCP byte 分包；分块安全由 unit 覆盖。

## v2 最终复核

复核接受 F-09—F-16，并确认替代措施已写入 v2：双读去重、SQLite worker/未决三态、完整早退矩阵、strict v2 contract、固定安全 degraded body、RAG snapshot 裁决及 Redis Lua 物理幂等。最终残余 Critical 0、High 0，批准进入红测。身份/租户仍按既有 backlog 与发布门禁处理。
