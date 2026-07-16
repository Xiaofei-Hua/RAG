# CI Index Routing — Tasks

## Spec and Review

- [x] [REQ-CIR-001..011] 编写 v1、完成 critic/defender 并接受 F-01/F-02/F-03。
- [x] [REQ-CIR-001..011] 修订 v2，完成并行复核；接受 N-01..N-07。
- [x] [REQ-CIR-001..011] 修订 v2.1：显式 venv、hostile env、cold cache、uv pin、无漂移重锁、
  build constraints 与 Docker full-build gate。
- [x] [REQ-CIR-005/010] 修订 v2.2：build allowlist 预装 + no-build-isolation；性能样本改为同
  runner class/image version，不要求同一 hosted VM。
- [x] [REQ-CIR-001..011] 并行完成 v2.2 最终 critic/defender；0 residual Critical/High，编码门禁通过。
- [x] [REQ-CIR-005/007/012] implementation critic 红证据：Docker trigger/package probe、hosted
  dispatch 与 runtime hash 契约缺口；修订 v2.3 并补永久回归。

## Red Tests

- [x] [REQ-CIR-003/005/006] actual frozen export closure/hash/source tests；红证据：`ci-build` 未定义，
  当前 dev/API-only 仍由 base FlagEmbedding 泄漏 torch/CUDA。
- [x] [REQ-CIR-001/002/004/009/011] workflow/Docker/installer contract tests；红证据：test job 无
  timeout，installer/version pin/no-sync/cold/full-build gate 均缺失。
- [x] [REQ-CIR-001/005/010/011] handcrafted wheel/sdist/simple-index tests：absolute target + decoy、
  hostile second server、bad runtime/build hash、undeclared build dependency zero-request、timeout。
- [x] [REQ-CIR-007/012] Docker all-change trigger、probe fail-closed、cold dispatch 不请求 self-hosted。

## Implementation

- [x] [REQ-CIR-003/006/010] 以 frozen uv manifest sequence 移动 FlagEmbedding、添加 `ci-build`，
  单次 offline lock；自动审计 package version/source/hash 无漂移。
- [x] [REQ-CIR-001..005/009..011] 实现 `scripts/sync_locked_deps.sh`：profile/build export、URL/closure
  guard、explicit target、env scrub、hashed build preinstall、no-build-isolation runtime、TERM/KILL。
- [x] [REQ-CIR-001/004/005/007/009] 更新 Unit/E2E 与 Playwright workflows：pin、script、
  `--frozen --no-sync`、cold-cache dispatch、job/sync timeout。
- [x] [REQ-CIR-002/004/005/007/009] 更新 Docker workflow/Dockerfile：pin、国内默认 ARG、CI official
  index、cold no-cache、600/1200/1800 秒 gates、runtime no-sync。
- [x] [REQ-CIR-008] 更新 CHANGELOG migration。

## Local Verification

- [x] 定向 tests 红→绿；`bash -n` installer。
- [x] `uv lock --check` 与 lock semantic diff audit。
- [x] 干净候选 + torch-less venv：unit+perf 853 passed / 4 deselected；E2E 87 passed /
  2 skipped；branch coverage 68%（gate 60%）。
- [x] web build + Playwright：21 passed；人工查看关键截图。
- [x] classic Docker cold build：106s；dependency sync 40s；478101058 bytes；zero-torch/import/profile 通过。
- [x] Ruff、format、import、禁用注释审计、scoped `git diff --check` 最终复跑。

## Remote Verification and Delivery

- [ ] commit/push `main`，监控 Lockfile、Unit/E2E、Playwright、Docker 首轮 warm checks。
- [ ] 同一 SHA/workflow/runner label+arch+image version/Python/uv 对 Unit/E2E、Playwright、Docker
  各运行 3 次 `cold-cache=true`；记录 image metadata、dependency/full-build median/max；若 image
  version 变化则分组或重采样。
- [ ] 回填 review/tracking 的 commit、测试、run URL/attempt/cache/秒数并关闭所有 Critical/High；
  push 最终文档并确认最终 required checks。

## Evidence Before Fix

- failed：Unit/E2E `29470496495`、Playwright `29470496606`、Docker `29470496462`，均依赖阶段
  >30 分钟后取消；Lockfile `29470496494` success。
- override reproduction：`UV_DEFAULT_INDEX` + `uv sync --frozen -vv` 仍请求阿里云。
- closure reproduction：dev/API-only 均含 FlagEmbedding、torch 2.12.1+cu132 与 CUDA。
- v2 review reproduction：`UV_PROJECT_ENVIRONMENT` 不影响 `uv pip` target；`UV_INDEX` 在
  `--no-config --default-index` 下仍优先；普通 remove/add 夹带 ir-datasets/sentencepiece 升级。
- red run：`uv run --frozen python -m pytest tests/unit/test_ci_dependency_routing.py -q` →
  `12 failed, 3 passed`（2026-07-16；实现前）。
