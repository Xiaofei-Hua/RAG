# Code Critic — Grounding Disable Hot Path

**日期**：2026-11-10。独立只读复核发布树与集成树diff、测试及现有日志；未运行模型或测试，未阅读defender结论。

## Decision

生产实现无新增实质阻断，与已审最小设计一致。发现一项仅涉及新E2E清理的Medium问题，已在工作树修正，发布树修后复验尚待归档；不把旧62项绿记录冒充当前全部矩阵已绿。默认仍true，真实24槽实验尚未作为结果计入。

## Findings

### F-GDH-C01 — 新E2E清理调用旧发布树不存在的reset函数

`issue (blocking)` — 仅测试适配，非生产热路径。

- **id**: F-GDH-C01
- **severity**: Medium；按critic §2为实现适配问题，具体影响限于测试teardown，不适用热路径最低High约束。
- **location**: `tests/e2e/test_grounding_switch_api.py:13–21`；测试隔离/资源回收纪律。
- **symptom**: 首轮发布树矩阵的两项新API测试正文断言完成后，teardown导入 `reset_inference_store` 触发ImportError。
- **impact**: 本次新增测试不能完整通过，资源清理未完成；不能据旧定向日志宣称发布矩阵通过。产品开关功能未因此失效。
- **root_cause**: 清理fixture沿用了集成树具有、origin/main发布树没有的reset接口。
- **recommendation**: 仅按旧接口在测试内取得 `_store_lock`，关闭已存在的 `_store` 并置None；不回移新生产reset API。当前两树已如此修改。
- **verification**: 保留首轮 `validation/backend-matrix.log` 的两项错误，执行当前JSON/SSE回归并确认无teardown错误；该两项永久保留。新版完整矩阵也可覆盖此验证，不需另扩矩阵。
- **status**: open（代码修正已只读确认；待发布树修后测试证据及fix commit）。

## Production and Test Assessment

- 发布树 `grounding_guardrail.py:99、181` 在空资料判断及 `self.judge` 之前用原 `_env_bool` 返回None/degraded/disabled；集成树 `_prepare:177` 是同步异步共同前置。模块wrapper仅构造廉价对象，禁用不触碰judge，已有缓存judge也不会进入其调用路径。
- `types.py:59` factory仅延迟本字段环境读取，解析默认true及显式字段赋值保留；没有新增配置、状态、prompt、模型请求或改变离线judge。
- 单元测试直接观察 `get_judge` 零调用及禁用golden，覆盖false/0/off/no/空白大小写与四入口；开启/未设确实调用stub judge并得到支持结果，未用假返回值绕过被修入口。
- 生成测试运行实际GenerateSkill同步/异步代码，生成provider被stub，检查一次生成、None/confidence_degraded及实际Output来源/PII逻辑。未核验不被假造为0/1；保留原置信度权重重分配，不能保证分数下降。
- API测试使用真实HTTP router、GenerateSkill和Output hook，intent、检索材料及harness衔接被替换。它验证JSON/SSE终态、PII与历史、一次生成/零NLI；**不等于完整LangGraph路由/检索/检查点测试，也不证明旧main原生流式全程先检查后发布**。当前测试描述没有冒称这些边界。
- 没有修改来源/结构/安全/PII分支或旧发布机制，也没有把集成新收据回移到发布树。关闭后较弱的语义保障是原显式配置的结果，不是默认改变。

## Evidence Read

- 发布树红：单元23 failed/10 passed，API 2 failed；原定向绿62 passed/2.15s（另有进程退出ResourceWarning，保留）。
- 集成树原定向62 passed/2.65s；完整矩阵2768 passed、6 skipped、3 warnings/154.65s。
- 发布树首轮完整矩阵1181 passed、6 skipped、3 warnings、1 failed、2 errors/65.81s。两error对应F-GDH-C01；另一项WSL文档/OpenAPI失败为额外GET `/`，主线程正在补足原web/dist构建前提，未要求本bugfix修改生产路由或旧文档。
- 本报告记录当时日志，不预判后续验证成功；修后结果可在此追加关闭证据。
