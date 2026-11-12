# Review Tracking

按[用户知情验收决定](../validation/acceptance-decision.md)验收整体质量与关键事实；严格首节原分数12/18不改。以下合并相同失效行为，完整八字段发现、弃用变体及原评级保存在[工程证据归档](../validation/README.md)，不把每次失败另立生产缺陷。

| Finding / scope | Severity | Requirements | Defender decision | Production / disposition | Verification | Permanent regression | Status |
|---|---|---|---|---|---|---|---|
| F-01/02 实验判据与因素边界 | Medium | 704/705 | accepted | 915f421设计；用户后续验收决定单列 | 冻结/原判据/失败及新标准均归档 | 无生产改动，协议/结果归档 | closed |
| F-03/10/14；F-07/12的旧首节失效 | Critical/High | 702 | accepted | 915f421完整键/规范前置/句首回连 | v19开发40/40；陶艺许可恢复首节 | test_sentence_internal_reference_keeps_permission_separate；test_completed_prerequisite_moves_only_selected_step_to_lead | closed |
| F-04/06/08；F-07/12/17的内容遗漏/偏题 | Critical/High | 701/703 | accepted | 915f421完整原文键及六类，弃用自由关联/短键 | v19开发40/40；新留出关键内容18/18；默认6/6 | test_complete_selection_preserves_steps_and_request_contract；test_real_clause_classifications_exclude_unasked_facts；真实golden | closed |
| F-05/11/13 英文实验失效路径 | Critical/High | 703/705 | accepted | 915f421统一中文资格，英文回原生成及原证据 | 英文/普通28个最终请求不变；默认未扩大范围 | test_english_procedure_keeps_original_evidence_and_generation；test_only_measured_weak_foreign_evidence_is_removed | closed |
| F-09 弃用数组方案耗尽预算 | High | 703/704 | accepted | 915f421固定完整键对象，2048与非stop降级不变 | v19开发40及新留出18/默认6均单次stop | test_procedure_publication_is_complete_checked_and_single_call[length] | closed |
| F-15 实验准入漏检 | High | 704 | accepted | 915f421路由回归；新留出生成前完整资格预检 | v19 r1→r2仅生成前等义提问修订；真实默认6答同候选请求 | test_procedure_route_requires_explicit_noncomparison_request（6例） | closed |
| F-16 剩余广播许可位置后移（含DH17-01/DH19-01） | High | 702/705 | defended-with-alternative | 915f421修复原陶艺；剩余广播未技术修复。用户明确接受展示限制；eeac986默认/false回滚 | 新留出全文正确18/18、首节12/18；默认内容6/6、首节4/6；README/CHANGELOG明示限制 | 完整内容golden及test_complete_selection_preserves_steps_and_request_contract；test_procedure_default_and_opt_out_keep_request_contract | defended-with-alternative |

当前无未处置Critical，High均closed或上述已落实替代。F-16不是closed/fixed；替代是用户批准的新范围、完整正确正文、公开限制与已验证回滚，绝不是把第二节算首节。英文原路径本身的既有质量问题不宣称已修。
核心修复commit：915f421fe3208740391ddcd0b979234c57090f1a；默认/回滚commit：eeac9860d9a63e8f7a538c95916f725b659d35e3。最终矩阵1336通过/6跳过、branch75%，默认红1失败1通过→绿92；真实默认15HTTP=6最终生成+9原控制。GitHub必要检查与main交付以发布PR实际状态为准，不提前写通过。
