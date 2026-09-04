# Frontend Contract Hardening Tasks

- **Feature**: `frontend-contract-hardening`
- **Design**: [design.md](design.md)

## 1. Spec and Review

- [x] **T-FCH-001** 完成 requirements/design/tasks 三段式。[REQ-FCH-001—REQ-FCH-008]
- [x] **T-FCH-002** 独立 critic/defender 并行评审，归档 review 三件套并关闭 Critical/High；v2 覆盖 public projection、attempt ownership、atomic exchange、history completeness 与可执行 perf gate。[REQ-FCH-001—REQ-FCH-008]

## 2. Red Tests

- [x] **T-FCH-101** 先写增量 think 过滤、grammar/lifecycle/buffer、同步与流式零公开正文 unit/golden 回归。[REQ-FCH-001—REQ-FCH-002]
- [x] **T-FCH-102** 先写 include_sources 全路径、Redis Lua/SQLite atomic physical-idempotent exchange（含 ambiguous reply 同 ID 重放）、跨 shard merge/dedupe、history availability/completeness/persistence 三态与重复 feedback E2E。[REQ-FCH-003—REQ-FCH-006]
- [x] **T-FCH-103** 先写公开 metadata/log/capture/降级缓存正文 allowlist，以及 Redis 单 Lua command、SQLite lock 下 event-loop heartbeat、deadline→null、迟交/重试物理幂等等可执行 perf 契约测试。[REQ-FCH-001, REQ-FCH-005, REQ-FCH-007]

## 3. Implementation

- [x] **T-FCH-201** 实现 attempt-local `IncrementalThinkFilter`/whole-text sanitizer，并接入所有模型输出边界。[REQ-FCH-001, REQ-FCH-007]
- [x] **T-FCH-202** 实现空公开正文 error 终态与 include_sources 投影。[REQ-FCH-002—REQ-FCH-003]
- [x] **T-FCH-203** 实现带稳定 ID 的原子/物理幂等 `save_exchange`、SQLite `to_thread`/busy timeout、deadline unknown、双读 merge/dedupe、history completeness/503 与 persistence metadata。[REQ-FCH-004—REQ-FCH-005]
- [x] **T-FCH-204** 实现反馈原子幂等和副作用 single-fire。[REQ-FCH-006]
- [x] **T-FCH-205** 实现 public metadata projection、固定安全 degraded/cached body、诊断日志最小化和 capture sanitization。[REQ-FCH-001, REQ-FCH-007]
- [x] **T-FCH-206** PHM 接入 contract v2 与 persistence/completeness 三态，延迟登记本地会话并展示失败/unknown 恢复提示。[REQ-FCH-002, REQ-FCH-004—REQ-FCH-005]
- [x] **T-FCH-207** 更新 backend/browser fakes、`docs/API.md` 与 `CHANGELOG.md` breaking 迁移说明，保持 capability 默认关闭。[REQ-FCH-005, REQ-FCH-007—REQ-FCH-008]

## 4. Verification

- [x] **T-FCH-301** 运行定向 unit + in-process E2E + perf contract，记录红→绿证据。[REQ-FCH-008]
- [x] **T-FCH-302** 在固定的 fake uvicorn → Vite `/document` proxy → Chromium 拓扑下运行真实联调，并对 backend 全矩阵与 PHM Playwright 各连续运行两轮全绿，记录同一 git 状态。[REQ-FCH-008]
- [x] **T-FCH-303** 更新 tracking/CHANGELOG/验证命令，确认未覆盖工作树中既有部署改动。[REQ-FCH-007—REQ-FCH-008]

## 5. Verification Evidence

### Red → Green

- 增量 reasoning 过滤：`/tmp/fch-think-red.log` → `/tmp/fch-think-green.log`。
- public response/source/metadata 与 chat 分支：`/tmp/fch-api-red.log` →
  `/tmp/fch-api-green-attempt3.log`（12 passed）。
- 原子会话、反馈幂等与持久化三态：`/tmp/fch-storage-feedback-red.log` →
  `/tmp/fch-storage-feedback-green-1.log`；session retention 与 stream capture 另有各自 red/green 日志。
- 热路径 deadline、单命令与 event-loop 隔离：`/tmp/fch-hotpath-red.log` →
  `/tmp/fch-hotpath-green.log`（26 passed）；`/tmp/fch-perf-green-attempt1.log`（2 passed）。
- 降级置信度不可用曾被错误序列化为 `0.0`：`/tmp/fch-degraded-intent-red.log` 复现，
  `/tmp/fch-degraded-intent-green.log` 通过并固定 `null` 契约。

### Final Gates

- 实现 commit：`2c6f089`；定向后端回归 128 passed，contract matrix 46 passed。
- RAG 全矩阵连续两轮：均为 1210 passed / 6 skipped / 3 个既有第三方弃用告警；日志
  `/tmp/fch-backend-full-final-round1.log`、`/tmp/fch-backend-full-final-round2.log`。
- PHM 固定实现 `8a5b80e` 连续两轮：`vue-tsc` exit 0、12 files / 51 unit tests、build exit 0、
  Playwright 27/27；日志 `/tmp/phm-final-{typecheck,unit,build,playwright}-round{1,2}.log`。
- 真实 fake uvicorn → Vite `/document` → Chromium 联调连续两轮 1/1；日志
  `/tmp/phm-live-final-round1.log`、`/tmp/phm-live-final-round2.log`，临时 spec 已删除。
- `git diff --check` 通过；实现文件未覆盖工作树中既有 FlagEmbedding、deployment、retrieval 改动。
