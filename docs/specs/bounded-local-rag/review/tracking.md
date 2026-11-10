# Tracking

设计初审并行独立完成后才实现。最终代码、全文质量、默认入口及混合负载再独立评审；Critical 0，High全部闭合。原失败与Medium引述措辞不删改。

| ID | Severity | Fix commit / resolution | Verification | Permanent regression | Status |
| --- | --- | --- | --- | --- | --- |
| F-BLR-01 | Medium | cfdab43：移除原生0.24不消费的presence_penalty | 源码/实际wire，只声明受支持采样字段 | test_fast_wire_has_real_budget_and_no_hidden_thinking | closed |
| BL-D01 | High | 2eeb2a4：Fast统一finalize、Thinking after-hook后交付，失败不泄露草稿 | API红8fail→绿；最终131 E2E通过，真实SSE token=done | test_fast_checks_before_any_delivery；tests/e2e/test_bounded_local_rag_api.py（JSON/SSE、两模式、护栏异常） | closed |
| BL-D02 | High | 2eeb2a4：生成/输出共享策略，跳过在线judge且保留None/degraded | 实际API请求逐条分类0judge；元数据None，未当0或1 | test_bounded_skips_online_judge_without_faking_a_score；真实Graph E2E | closed |
| F-BLR-RUNTIME-01 | High | cfdab43：补丁/重建说明/实际版本资格，非合格环境回legacy | 上游format回归红绿归档；宿主version收据；默认真实API2/2 | test_auto_requires_the_qualified_server_and_caches_it（含不可达/未验证版本） | closed |
| API2-D01 | Medium | 保留：零值概括曾被说成原文引述；独立评审认定核心事实/条件/来源无退步 | final-quality及release双方全文审阅，历史回答保留 | 继续披露；不据此声称逐字引文完美 | accepted, nonblocking |

## Verification Receipts
完整本地矩阵1091 unit/perf +131 E2E通过，2skip/4deselected，coverage74%。代码两位评审均无新增Critical/High。16开发答案通过；最终回归/新留出8合格、4与legacy相同的不足答，不计成功；默认2槽、混合8槽合格。
修复提交为独立可合并stage，每阶段非机械改动≤800行，复杂业务逻辑≤500行；最终默认选择与证据单独提交。最终GitHub检查及main合并记录见release。
