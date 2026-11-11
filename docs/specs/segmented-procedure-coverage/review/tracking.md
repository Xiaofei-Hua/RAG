# Review Tracking

## Disposition
独立critic/defender并行评审覆盖编码前设计、每次机制修订、最终代码、开发及新留出。默认关闭交付获准；默认启用未通过。完整历史报告与逐答记录在validation/evidence.tar.gz内保留，旧失败不改判。

| ID | Severity | Requirement | Fix commit | Verification | Permanent regression | Status |
|---|---|---|---|---|---|---|
| D-01 / F-01,03,05 | High / Critical | REQ-601 | 0e43679 (integration), 29a6ae1 (primitives) | 开发流程8/8、新留出核心步骤/条件/记录/用途12/12 | test_complete_selection_preserves_steps_and_request_contract; test_annotation_preserves_event_context_sources_and_history; test_segmented_api_persists_completion | closed |
| F-02 | Critical | REQ-601/602 | 0e43679 (integration), 29a6ae1 (primitives) | 所有开发/留出首个实际正文事件等于完整全文；不再提前交付局部流程 | test_procedure_publication_is_complete_checked_and_single_call | closed |
| F-04,06 | High | REQ-601/602 | 0e43679 (integration), 29a6ae1 (primitives) | 实际来源映射、引用条款原文与全文检查，开发/留出引用有效 | test_annotation_preserves_event_context_sources_and_history; test_segmented_api_persists_completion | closed |
| F-07,08,11 | High | REQ-602 | 0e43679 (integration), 29a6ae1 (primitives) | 解释/跨语/普通题回原完整；16/16普通实际请求与基线相同 | test_explanations_keep_the_existing_generation_route; test_other_or_mixed_language_uses_buffered_generation | closed |
| F-09,12 | Critical | REQ-601/602 | 0e43679 (integration), 29a6ae1 (primitives) | 两模式开发流程8/8，两个Fast用途复现已恢复，实际来源去噪一致 | test_only_measured_weak_foreign_evidence_is_removed; test_segmented_api_persists_completion[procedure_with_noise] | closed |
| F-10,13 / H-D01,02 | High / Medium | REQ-604 | default false retained | 开发包装误选已恢复；新留出中文相关性/视觉首节失败仍未修复，禁止默认启用 | test_procedure_default_and_opt_out_keep_original_generation | defended-with-alternative — false隔离，非缺陷修复 |

## Delivery
Stage 1新增纯机制与纯函数契约，Stage 2接线及文档，均默认false。Stage 1提交29a6ae1独立矩阵1282 passed/6 skipped、coverage74%；Stage 2最终树（含默认关闭回归）1315 passed/6 skipped、coverage75%。所有Critical已关联0e43679/29a6ae1、真实验证和永久回归；High相关性/首节问题以默认false替代交付，明确未修。合并必须通过GitHub test/e2e-ui/check；最终交付状态以对应PR为准。
