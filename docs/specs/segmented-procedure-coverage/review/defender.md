# Defender Review — Segmented Procedure Coverage

**Date**: 2026-11-11
**Object**: 最终设计、代码、真实开发对照与冻结新留出；独立评审，未读取 critic 报告。
**Decision**: **允许默认关闭的实现分阶段合并，不允许默认启用。** 未发现新的代码级 Critical/High 阻断；完整语义质量未合格，不能称第 4 步已全面通过。最终提交及各阶段 CI 结果由 tracking 补齐。

## Evidence and Limits

- 开发流程严格 1/8→8/8；非流程两侧各 15/16，实际 16 个生成请求逐字段一致，保留一条配对下降。候选开发整批为 23/24，不能报告 24/24。
- 新留出两题×两模式×三轮：全部动作/条件/记录步骤 5/12→12/12；所问用途 4/12→12/12；严格整题 **1/12→6/12**。候选中文六答都选入墙钟/年鉴，首节又未给开始阅览的主要规则；其中 R3 Fast 是真实 Pass→Fail。英文六答完整，重复本身不判失败。12 个候选只有两个不同正文，不能当 12 个独立题目。
- 每侧均 12 次最终生成、18 次 Thinking 控制调用，调用未增加。完整正文首次发布 P50 12.9245→5.4527 秒，P95 17.7125→8.4083 秒；生成 completion tokens 13,172→3,504。收益限于这批输入，不替代质量门槛。
- 最终后端矩阵 `validation/final-backend.log` 为 1313 passed / 6 skipped / 3 既有 warning；`validation/final-coverage.log` 总覆盖率 75%。本 reviewer 核对落盘结果，没有重新调用模型或重复跑全量。

历史详细报告和原始记录随 `validation/evidence.tar.gz` 归档；相关成员包括本 spec 的 `review/holdout-v1-defender.md`、`review/api-noise-removed-defender.md`、`review/noise-removal-code-defender.md`、`review/final-code-defender.md`、`review/initial-design-defender.md`，以及 `validation/procedure-api-holdout-{baseline,candidate}/{results.jsonl,model-http.jsonl}`。这些是归档成员路径，不是单独提交文件的链接。

## Decisions

| ID | Severity | Decision | Evidence and implemented alternative | Design |
|---|---|---|---|---|
| H-D01 | High | defended-with-alternative | 留出候选第 1/3/5/7/9/11 行选入无关墙钟/年鉴，第 9 行由基线合格转失败。默认继续 false，显式试用文档明示质量边界；未声称语义修复。 | Rollout and Compatibility |
| H-D02 | Medium | defended-with-alternative | 同六答主要阅览规则在第三节才出现，书面首节不满足 v2；实际已完整 stop 后整体发布，无提前发布不完整前缀。以默认关闭隔离。 | Strategy and Eligibility；Rollout and Compatibility |

### H-D01 Decision Tree

1. **Fact**：逐条全文与冻结判据核对，两个装饰事实确在答案中，且有真实依据；有依据不能证明相关。
2. **Trigger**：显式 true 的真实 Fast/Thinking 各三轮均触发；无需假想异常。false 不进入条款选择，见 `core/segmented_generation.py:36`。
3. **Cost and impact**：完整答案对用户问题的相关性真实退步，阻止默认启用；再据本留出改提示将污染验收，本轮不继续调试。
4. **Scope**：属于本机制选择质量边界，应保留为未修问题，不转嫁成检索缺句，也不扩建额外语义模型平台。
5. **Alternative**：`design.md:23`、`.env.example:186` 与 `README.md:70` 已明确 false 及显式启用限制；满足本轮默认关闭交付目标。该替代不保证手工 true 的质量，也不允许把 finding 标为已修复。

## Code Admission

一次调用内选择原条款及顺序、按真实来源映射构成正文，适合修复已复现的自由摘要漏步；`core/procedure_generation.py:147` 先验证 stop 和 ID，`core/segmented_generation.py:155` 等完整生成并经过现有检查后发布。结构有效只证明协议完成。

跨语言/缺映射/资格不明先回原完整生成；低相关异语仅在已测概率和强同语种依据同时满足时排除，缺分不作 0，原全局 rerank 数值/消费者不变。Fast 三入口及 Generate 共用预选结果，实际 context/kept/sources 一致；原检索证据与历史保留。非流程、比较、rewrite 维持完整 GroundedAnswer；temperature 0 仅作用于合格流程选择，普通生成仍 .7。检查失败走不可用及 confidence=None，未加模型核验或生成重试。

准予两个独立阶段：先纯条款机制/概率标记及纯函数契约，再 API 接线/完整发布与文档。两个阶段均保持默认 false，分别完成适用测试和 CI；最终 tracking 用实际提交补闭环。本报告不是未经检查即合并授权，也不新增原任务之外的质量平台或防御门禁。

## Delivery Verification Addendum

主Agent补记（不改变独立语义评审结论）：Stage 1实际29a6ae1独立矩阵1282 passed/6 skipped、coverage74%；Stage 2补默认关闭/显式false回归后1315 passed/6 skipped、coverage75%，日志为归档中的stage1-backend.log、final-policy-matrix.log及相应coverage。运行时代码冻结未变，新增测试仅证明不启用时保留原路径。
