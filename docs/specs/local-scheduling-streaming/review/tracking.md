# Review Tracking

## Design and Implementation Gate
独立critic/defender并行完成v1/v2设计审查，阻断在编码前落实到v2；后续每次schema修订独立审查。最终代码与真实全文/首段审查均无剩余Critical/High实现阻断。质量失败通过保持分段默认关闭处理，不等同于质量合格。

| ID | Severity | Requirements | Decision | Fix commit | Verification | Permanent regression | Status |
|---|---|---|---|---|---|---|---|
| F-01 / D-02 | High | REQ-402 | accepted | a40d4a0 | segment-api-red→segment-api-green-v3；ui-final | tests/e2e/test_segmented_api.py；tests/e2e_ui/segmented.spec.ts | closed |
| F-02 / D-01 | High | REQ-302 | accepted | 32da0f0 / 30e4fe5 | admission-red→admission-green-v2 | tests/e2e/test_local_model_admission.py | closed |
| F-03 | High | REQ-302 | accepted | 32da0f0 / 30e4fe5 | generation-busy-red→admission-green-v2 | test_actual_graph_generation_busy_is_terminal | closed |
| F-04 | High | REQ-302 | accepted | 32da0f0 | cleanup-red-v2→step3-ci-env-corrected；final-backend | test_query_transform_busy_propagates_without_fallback | closed |
| F-05 | High | REQ-402 | accepted | 16ab3e2 | stop-contract-red→segment-green；final-backend | tests/unit/test_segmented_generation.py非流式finish参数化 | closed |
| D-03 | Medium | REQ-301 | accepted | 32da0f0 | SDK流关闭/取消单测；live-cancel-v1 | tests/unit/test_local_model_queue.py | closed |
| D-04 | Medium | REQ-403 | defended-with-alternative | 16ab3e2 / a71a885 | 三次机制消融、两轮API、新留出全文审查 | 默认false与比较/改写保留路径单测 | defended-with-alternative |

## Final Evidence
1274 passed、6 skipped、3 warnings，coverage74%；UI去重24 passed、1 skipped；ruff23文件通过。final-backend.log与ui-final.log归档。实际默认2/2、显式组合4/4完成；两轮API开发各16/16语义通过，留出长流程有配对步骤遗漏，因此只默认启用fair，分段false。所有实验原文和失败记录保留，详见[results](../results.md)。

## Merge Gate
修复commit与永久回归已齐备，独立critic/defender最终矩阵复核完成。分阶段PR仍需GitHub必需检查test/e2e-ui/check通过后才可合并；远端交付状态以实际合并记录为准。
