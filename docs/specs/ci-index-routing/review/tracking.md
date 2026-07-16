# Tracking — CI Index Routing

## 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护者决策 | design 修订 | 修复 commit | 验证测试 | 回归测试固化 | 状态 |
|---|---|---|---|---|---|---|---|---|
| F-01 | Critical | REQ-CIR-001/002/005 | accepted | v2 §1/§3/§4/§6 | pending | local dual-host canary passed; remote pending | `tests/unit/test_ci_dependency_routing.py` | open |
| F-02 | Critical | REQ-CIR-003/006/007 | accepted | v2 §2/§5/§6 | pending | exports exclude local stack; Docker zero-torch/size/import passed | `tests/unit/test_ci_dependency_routing.py` + Docker workflow | open |
| F-03 | High | REQ-CIR-004/005/007 | accepted | v2 §4/§6 | pending | hash/wiring/local timing passed; remote pending | `tests/unit/test_ci_dependency_routing.py` | open |
| N-01 | High | REQ-CIR-001/005 | accepted | v2.1 §3/§5/§6 | pending | absolute target + decoy passed; Docker gate now uses explicit `/app/venv` | `tests/unit/test_ci_dependency_routing.py` | open |
| N-02 | High | REQ-CIR-005/011 | accepted | v2.1 §3/§7 | pending | hostile/target dual server passed | `tests/unit/test_ci_dependency_routing.py` | open |
| N-03 | High | REQ-CIR-004/005 | accepted | v2.1 §4/§6 | pending | pending same-SHA cold runs | workflow dispatch evidence | open |
| N-04 | High | REQ-CIR-009 | accepted | v2.1 §4 | pending | every setup-uv + Docker pinned 0.11.8 | `tests/unit/test_ci_dependency_routing.py` | open |
| N-05 | High | REQ-CIR-006 | accepted | v2.1 §2 | pending | non-root package version/source/hash audit passed | lock audit + `tests/unit/test_ci_dependency_routing.py` | open |
| N-06 | High | REQ-CIR-010 | defended-with-alternative | v2.1 §2/§3 | pending | hashed ci-build + undeclared backend zero-request + cold install passed | `tests/unit/test_ci_dependency_routing.py` | open |
| N-07 | High | REQ-CIR-004 | accepted | v2.1 §4/§5 | pending | 1200s gate simulation passed; local cold full build 106s; remote pending | `tests/unit/test_ci_dependency_routing.py` | open |
| N-08 | High | REQ-CIR-005 | accepted | v2.2 §6 | pending | pending runner class/image metadata | remote dispatch evidence | open |
| CI-IMP-H-01 | High | REQ-CIR-007 | accepted | v2.3 §4/§6 | pending | Docker workflow has no incomplete positive path filter | `test_web_sanitizer_lock_refresh.py::test_docker_workflow_runs_for_all_changes_and_checks_the_target_venv` | open |
| CI-IMP-H-02 | High | REQ-CIR-007 | accepted | v2.3 §5 | pending | package-list probe and grep status are separated; remote image gate pending | `test_ci_dependency_routing.py::test_workflow_docker_and_installer_contracts` | open |
| CI-IMP-H-03 | High | REQ-CIR-012 | accepted | v2.3 §4 | pending | cold dispatch defaults to hosted-only | `test_ci_dependency_routing.py::test_workflow_docker_and_installer_contracts` | open |
| CI-IMP-M-02 | Medium | REQ-CIR-005 | accepted | v2.3 §6 | pending | independent runtime artifact tamper rejected; target package unavailable | `test_ci_dependency_routing.py::test_installer_rejects_tampered_runtime_hash` | open |

## 合并门禁

- F-01/F-02/F-03 与 N-01..N-08 均须填入修复 commit、验证/永久回归测试及适用的 remote
  evidence 后才可 closed；N-06 必须实际预装 hashed allowlist 并关闭 build isolation。
- 当前全部阻塞合并与最终交付。

## Evidence Before Fix

| Workflow | Run | 结果 | 失效阶段 |
|---|---|---|---|
| Unit & E2E | 29470496495 | cancelled after >30m | dependency install |
| Playwright UI E2E | 29470496606 | cancelled after >30m | backend dependency install |
| API-Only Docker | 29470496462 | cancelled after >30m | dependency image layer |
| Lockfile Consistency | 29470496494 | success | no dependency install |
