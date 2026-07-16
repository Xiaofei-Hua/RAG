# Web Sanitizer Lock Refresh — Tasks

## Spec and Review

- [x] [REQ-WSR-001..004] 编写 requirements/design/tasks。
- [x] [REQ-WSR-001..007] 独立 critic/defender v1 评审：接受 F-01..F-05，阻塞编码。
- [x] [REQ-WSR-001..007] 修订 v2，最终 gate 为 0 residual Critical/High。

## Red Tests

- [x] [REQ-WSR-001/002/005/006] 新增 lock/Docker/workflow contract unit；红证据：`4 failed`，
  分别命中 3.4.7、nested lock/`npm install`、缺失 path filters、缺失受控 audit。
- [x] [REQ-WSR-004] 新增恶意 assistant HTML Playwright 契约；安全 DOM/执行断言永久固化。
- [x] [REQ-WSR-004] implementation critic 红证据：sanitizer throw 时危险 `<img>` 留在 DOM；
  修复为 escaped plain-text fallback，并增加降级态 Playwright 截图。

## Implementation

- [x] [REQ-WSR-001/002/006] 使用 Node 20.20.2/npm 10.8.2 与受控 registry 定向刷新 lock。
- [x] [REQ-WSR-002] 审计 lock tuple：仅 DOMPurify/@types-trusted-types 布局与目标版本变化；
  其他 package version/resolved/integrity 无漂移；Rollup `libc` 字段移除为 npm 10.8.2 元数据规范化。
- [x] [REQ-WSR-005] Docker web-builder 接入 root workspace lock + npm ci + installed-version gate，
  Docker workflow 对所有 main/PR 变更运行，package-list probe fail closed。
- [x] [REQ-WSR-004] Playwright route 注入恶意 HTML，增加安全契约和过程截图。
- [x] [REQ-WSR-001/003/005] 在 CHANGELOG 记录 sanitizer 与 reproducible web-builder 修复。

## Verification

- [x] [REQ-WSR-003/006] 受控 registry 下 `npm audit --omit=dev`：0 vulnerabilities。
- [x] [REQ-WSR-003] production build 通过；ESLint 0 errors / 14 既有 warnings。
- [x] [REQ-WSR-003/004] Playwright：21 passed；人工检查 sanitizer 正常/异常、source/session 截图通过。
- [x] [REQ-WSR-003/005] cold classic Docker：web-builder 29s、full image 106s、DOMPurify
  3.4.12、478101058 bytes、zero-torch/import/profile files 全通过。
- [x] [REQ-WSR-001/002/006] scoped diff/whitespace/lock provenance/tuple 审计通过。
- [x] 干净候选 torch-less 全矩阵：853 unit+perf、87 E2E、branch coverage 68%；仓库内
  SQLite ResourceWarning 已清理，剩余 warning 仅来自 jieba/milvus-lite 对第三方 `pkg_resources` 的使用。

## Delivery

- [ ] 精确暂存并随当前 main 交付；不纳入并行检索前沿改动。

## Red→Green Evidence

- Red：`tests/unit/test_web_sanitizer_lock_refresh.py` → `4 failed`。
- Green：最终 CI/web/image contract suites → `23 passed`。
- Browser：两条 sanitizer 用例随全套 → `21 passed`；正常路径与强制异常路径均阻断危险 DOM/执行。
