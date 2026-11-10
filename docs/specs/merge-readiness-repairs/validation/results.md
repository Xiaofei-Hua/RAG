# Validation

2026-11-10，在`8ab8e44`基础应用本阶段相同改动验证；归档原始日志见test-evidence.tar.gz。独立CI分支只含此修复，不携带其他历史实验。

| Command | Result |
| --- | --- |
| `uv run --frozen --no-sync python -m pytest tests/unit/test_root_schema.py -q` | red: 1 failed, 1 passed |
| 根schema与WSL接口契约定向测试 | green: 31 passed |
| `npm ci` / `npm run build` | passed |
| `npm audit --omit=dev --audit-level=high` | 生产漏洞5→0；未宣称dev依赖清零 |
| `npm run test:e2e` | 21 passed, 1 skipped |
| CI unit+perf（既定marker filter） | 1061 passed, 4 deselected |
| CI in-process E2E | 123 passed, 2 skipped |
| `uv run --frozen --no-sync coverage report --fail-under=60` | 72%, passed |

npm使用仓库固定Node20.20.2；package.json无改动，未提高版本下限。OpenAPI不再把UI根路径作为REST接口；GET /原有JSON/HTML行为保持，API信息继续通过/api获取。
