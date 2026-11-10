# Code Defender — Merge Readiness Repairs

**Review date**: 2026-11-10。  
**Scope**: 发布树相对 HEAD `8ab8e44` 的 `api/main.py`、根 `package-lock.json` 与新 `tests/unit/test_root_schema.py`，以及本目录 validation 已落盘证据。独立复核，未读本轮 critic 稿、未运行测试/模型、未修改业务或依赖。本次只新增此报告。

## Decision

**无新增 Critical/High 代码阻断，最小 CI 修复可以保留。** 生产 Python 仅一处路由装饰器参数，依赖变化是既有允许版本范围内的锁文件更新；没有放宽断言、关闭审计或扩展业务功能。本地 CI 对等检查已通过，仍不能据此声称远端 CI 已绿，或性能修复及默认资格已经完成。

## Code Assessment

| Change | Independent verification |
|---|---|
| Root OpenAPI | `api/main.py:462` 仅增加 include_in_schema=False，与已有 SPA catch-all 的 `:451` 一致。路由依然注册，缺 dist 时继续调用原 api_info；没有删除 GET /、更改认证或修改业务 REST 路由。 |
| Root regression | `tests/unit/test_root_schema.py:5–24` 用 tmp_path/WEB_DIST_DIR 构造有、无 index 两种应用，均断言根路径不进入 OpenAPI、/api 仍在；实际 GET / 在有构建时返回 HTML，无构建时返回与 /api 相同的 JSON。使用既有 client fixture 的密封替换，未依赖机器真实 dist。测试重点与一行修复相称，无需重构应用工厂。 |
| Lock updates | 根锁将 dompurify 3.4.12→3.4.17、nanoid 3.3.16→3.3.20、source-map-js 1.2.1→1.2.2、postcss 8.5.25→8.5.32，并统一 Vue/@vue 至 3.5.45。原 web/node_modules 的 Vue 副本移动到根 node_modules，编译器必要依赖随之调整，属于 workspace 正常解析/去重。 |
| Scope | 根 package.json 与 web/package.json 声明未改；锁文件内两个 workspace 的声明亦不变，lockfileVersion 仍为 3。没有抬高声明下限、加入独立依赖或改动 workflow 审计阈值。 |

现有 OpenAPI 合同测试与新根入口用例共同验证已复现差异。新测试没有逐项比较两个 schema 的每个字段，但在本次只有一个路由参数变化的范围内，缺根项、保留 /api 及实际响应的回归足够；不要求为了形式一致增加测试矩阵。

## Evidence Snapshot

| Evidence | Observed result | Interpretation |
|---|---|---|
| `validation/schema-red.log` | **1 failed / 1 passed，4.52 s** | 无 dist 的新用例准确复现根路径意外进入 OpenAPI；有 dist 控制通过。 |
| `validation/schema-green.log` | **31 passed，2.79 s** | 修复后定向测试通过。 |
| `validation/audit-green.json` | 生产依赖漏洞各级均 **0** | 对应当前 prod 审计范围；不是所有 dev 依赖也零问题。 |
| `validation/frontend.log` | build 完成；Playwright **21 passed / 1 skipped，14.9 s** | 真实前端构建和既有浏览器用例运行，保留 skip，不称 22 项全通过。 |
| `validation/backend-matrix.log:30` | unit/perf **1061 passed / 4 deselected / 3 warnings，41.40 s** | 排除需要真实服务的标记，与记录的 CI 对等命令一致。 |
| `validation/backend-matrix.log:47` | E2E **123 passed / 2 skipped / 3 warnings，26.27 s** | 进程内 E2E 通过；不把未执行项计为通过。 |
| `validation/backend-matrix.log:195` | 总 branch coverage **72%**，现有门槛 60% | 日志为 coverage run 两阶段累计后的结果；本修复未降低门槛。 |

`frontend.log:8` 的 npm ci 输出仍报告 **13 vulnerabilities（10 moderate、3 high）**，与单独生产审计的 0 应区分。当前交付可称“生产 audit 通过”，不能称“所有依赖零漏洞”。这不是本次新增阻断，不扩为全面开发依赖升级任务。

## Final Boundary

这份报告确认代码与已落盘本地验证证据相符，没有再次运行检查。根路径从缺 dist 的 schema 隐藏是外部元数据修正，CHANGELOG 的影响/迁移说明仍按既定任务交付；实际 GET / 行为未变。用户要求的完整完成还包含 bounded 策略质量修复与最终 CI/main 合并，这些不能被本报告替代，也不能因本地 1184 项通过就宣称远端检查或真实模型已通过。
