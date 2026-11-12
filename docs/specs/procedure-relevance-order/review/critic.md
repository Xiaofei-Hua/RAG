# Critic Review — Procedure Relevance and Order

**Date**: 2026-11-12
**Mode**: 完整独立critic；生成热路径，无新增安全边界。
**Implementation**: `915f421fe3208740391ddcd0b979234c57090f1a`；默认与回滚回归 `eeac9860d9a63e8f7a538c95916f725b659d35e3`。初版及历次八字段发现、失败实验保留在[验证归档](../validation/README.md)，不以最终结论覆盖历史事实。

## Decision

**按用户明确确认的最终标准，批准v19默认启用。** 当前未解决Critical: 0；未裁决阻塞High: 0；High已接受替代: 1（F-16）。GitHub必要检查与合并状态仍由主线程最终确认，本报告不提前宣称CI完成。

[用户验收决定](../validation/acceptance-decision.md)明确允许整体质量改善、关键事实无退步时的首节位置瑕疵。该决定是在用户获知v19真实18答内容完整、六答许可第二节后作出；不是预注册严格通过。原严格 **12/18** 继续保留，位置限制没有被修复。事实、条件、步骤、记录用途、未知或引用的实质退步仍然阻塞，丢记录的v20及其他未通过候选均未进入生产。

## Evidence and Outcome

- v19十个已暴露题两模式两轮40答开发通过；冻结后独立三新题两模式三轮18答，内容完整性、相关性、已问未知、未问未知排除与引用各18/18。首节12/18，广播六答许可后置。见[机制审读](../validation/README.md)及[新留出逐答审读](../validation/README.md)。重复采样不计为18个独立新题。
- 两侧各45 HTTP=18最终生成+27控制，未加模型调用。API完整首见P50/P95为13.050/15.158→9.927/10.142秒，最终输出均值968.33→709tokens；不以速度抵消内容错误，不将串行小样本声明为普遍性能保证。
- 三项开关均unset的真实默认六答保持冻结v19的请求、selection及实际正文：关键内容6/6，严格首节4/6，广播两答为同一已接受限制；15 HTTP=6最终生成+9控制，全部stop/complete，SSE/done/存盘一致。见[默认独立核验](../validation/README.md)及[默认统计](../validation/default-v19-critic-statistics.json)。
- 红绿、永久golden与API回归已完成：v19红2→绿72；默认红1失败/false1通过→绿92。最终矩阵1336passed、6skipped、3既有warnings、branch coverage75%。详见[results](../results.md)与[归档索引](../validation/README.md)，不重复运行已通过检查。

## Historical Finding Groups

详细状态、实际commit、验证与永久回归的四向映射见[tracking](tracking.md)。这里保留行为组对应，不把每个弃用变体重复创建为新生产缺陷。

| Findings | Final disposition and permanent contract |
|---|---|
| F-03/10/14及F-16已修的句中指代子项 | 完整原文键、已选规范条件前置、句首才回连；`test_completed_prerequisite_moves_only_selected_step_to_lead`、`test_sentence_internal_reference_keeps_permission_separate`。不外推为所有自然许可顺序已修。 |
| F-04/06/08，及F-07/12/17的遗漏/无关项部分 | 完整条款分类保留动作、条件、记录用途及所问未知，排除未问事实；`test_complete_selection_preserves_steps_and_request_contract`、`test_real_clause_classifications_exclude_unasked_facts`及真实三份golden。40开发/18新留出/6默认实际正文提供语义验证。 |
| F-05/11/13的英文退步 | 最终中文资格隔离此候选影响，英文保留原证据及原完整生成；`test_english_procedure_keeps_original_evidence_and_generation`。不声称英文原答案的全部质量问题已修。 |
| F-09的实验输出截断 | 弃用自由长数组，固定完整键分类；真实最终输出stop，永久`test_procedure_publication_is_complete_checked_and_single_call`覆盖length、缺键、错键/角色及检查失败降级。 |
| F-15的实验资格误判 | 全部路由预检后才生成；`test_procedure_route_requires_explicit_noncomparison_request`固化明确流程/非比较边界。本轮r1修订发生在模型输出前，r2正常预检。 |
| F-16剩余自然许可后置 | **High / defended-with-alternative，未fixed/closed。** 用户知情接受，全文正确完整、候选仅限合格中文、显式false可回滚。历史Critical及严格失败保持归档。 |

修复行为关联`915f421`，默认/false行为关联`eeac986`；不可将这两个SHA填成广播位置限制的修复证明。F-01/02原实验定义问题已在模型输出前补齐，历史设计记录保留。

## Invariants and Accepted Limitation

完整stop后一次输出检查发布；非法结构/非stop/输出检查失败仍不可用且confidence=None，不追加调用；同步异步与API/SSE/保存路径已有回归。无新shared_state键、持久化或安全边界，不可信资料与PII检查保持。None不当0、仅真实reranker概率参与弱异语资料判断；未扩大英文/比较/改写/非流程或其他模型的路由。显式false仍回原完整生成。

F-16按当前范围不再是关键事实目标未闭合，因此由历史Critical调整为High并接受替代；保留High遵守生成热路径风险下限，不重新建立用户未要求的位置零退步门禁。用户得到完整正确的许可，只是广播示例的许可仍位于第二节；文档与最终说明必须如实保留。未来改进可继续，但不是本次默认交付的隐藏前置条件。

**praise (non-blocking)**: 最终v19提高了内容覆盖与相关性，保留未知和引用，并减少实测等待；已失败方案、严格位置限制与用户取舍均公开留存，没有用结构合法或检查数量冒充实际质量。
