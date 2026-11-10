# Release

## Reviewed Stages

| Stage | PR | Implementation | Scope |
| --- | --- | --- | --- |
| CI repairs | [#5](https://github.com/Xiaofei-Hua/RAG/pull/5) | ce22584 | root schema、兼容生产锁更新 |
| Grounding switch | [#4](https://github.com/Xiaofei-Hua/RAG/pull/4) | a345114 | 既有关闭开关真正跳过judge，默认仍true |
| Runtime / model | [#6](https://github.com/Xiaofei-Hua/RAG/pull/6) | cfdab43 | 精确资格、9B默认、上游引擎格式补丁 |
| Short controls | [#7](https://github.com/Xiaofei-Hua/RAG/pull/7) | 84345dd | 短控制预算、英文招呼边界 |
| Complete answer | [#8](https://github.com/Xiaofei-Hua/RAG/pull/8) | 2eeb2a4 | 一次JSON、明确结论/引用、检查后交付 |
| Qualified default | [#9](https://github.com/Xiaofei-Hua/RAG/pull/9) | b93608f | 真实质量通过后auto、完整证据与局限 |

各阶段分别可合并，非机械改动≤800行，核心复杂逻辑≤500行。按依赖顺序合并main；实际merge commit与最终检查可从上述PR及[main Actions](https://github.com/Xiaofei-Hua/RAG/actions?query=branch%3Amain)核验，不把分支已推送冒称main已交付。

## Exact-head Validation

b93608f最终业务代码本地矩阵1222 passed（1091单元/perf、131 E2E），2 skipped/4 deselected，coverage74%；拆分测试文件后38项再通过。真实质量与耗时见[结果](results.md)、[独立critic](review/release-critic.md)、[独立defender](review/release-defender.md)。

远端实际通过：
- [Stage A backend](https://github.com/Xiaofei-Hua/RAG/actions/runs/42808997251)
- [Stage B backend](https://github.com/Xiaofei-Hua/RAG/actions/runs/42809003088)
- [Stage C backend](https://github.com/Xiaofei-Hua/RAG/actions/runs/42809008127)
- [Final backend](https://github.com/Xiaofei-Hua/RAG/actions/runs/42809013354)
- [Final Playwright](https://github.com/Xiaofei-Hua/RAG/actions/runs/42809019283)
- [Final Docker build / size / non-root health](https://github.com/Xiaofei-Hua/RAG/actions/runs/42809024299)

main要求每阶段同步最新base，必需test/e2e-ui/check通过；合并按既有保护执行，不使用管理员绕过。重跑合并树属于仓库要求，不继续新增模型题库或修改已通过的生成提示。

## Deployment Boundary

宿主Ollama已是合格backport，本次没有覆盖其二进制/重启用户服务。原工作区20项未提交修改逐字保留；发布来源为GitHub main，实际应用部署仍按现有[部署指南](../../deployment/BOUNDED_LOCAL_RAG.md)。已有显式LLM_MODEL或LOCAL_RAG_POLICY继续优先；升级运行应用需使用合并后的代码并重启应用刷新配置缓存。此记录不把Git合并说成已有进程自动热更新。
