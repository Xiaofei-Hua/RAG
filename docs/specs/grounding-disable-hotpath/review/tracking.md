# Tracking

设计阶段critic/defender独立并行评审，无Critical/High，先完成设计后编码。代码评审发现的测试清理兼容问题已修复；真实模型策略资格失败与代码bugfix分开裁决。

| ID | Severity | Resolution | Commit / Alternative | Verification | Regression | Status |
| --- | --- | --- | --- | --- | --- | --- |
| F-GDH-C01 | Medium | 测试清理不再引用旧main不存在的reset函数，关闭并清空已有采样器 | de1a474；发布验证归档1a4507c | 发布1182通过，当前集成2768通过；清理适配后API两例再过 | tests/e2e/test_grounding_switch_api.py | closed |
| RQ-D01 | High | 候选发布共有生成错误，且第二轮同题生成超时；不继续默认关闭资格 | de1a474保留默认true；按设计停止，holdout不运行，详见results.md | 实际12终态与1部分尝试；两份独立real-quality评审，B为6合格/1错误/1不可用 | test_grounding_switch.py保留未设/true启用路径；原失败原文保存于real-model-evidence.tar.gz | defended-with-alternative |

| Requirement | Evidence | Status |
| --- | --- | --- |
| REQ-001/002 | 单元sync/async/wrapper红→绿、配置读取时机、golden不可用语义 | fulfilled |
| REQ-003 | 真实GenerateSkill与输出护栏的JSON/SSE测试，来源与PII检查保留 | fulfilled |
| REQ-004 | 两工作树矩阵通过；真实A+B+B多轮发现质量失败并停止 | partial：不宣称AB/BA或留出合格，默认保持true |
| REQ-005 | 聚焦origin/main的fix/grounding-disable-hotpath，PR #4；同修复集成当前工作树 | pushed；当前集成树已适配 |

GitHub已有后端首页表契约及UI依赖审计失败在validation/tests.md单列，不以本地通过替代远端状态，也不增加无关实现来掩盖。
