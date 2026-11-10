# Real Quality Defender — Grounding Disable Hot Path

**Review date**: 2026-11-10。
**Scope**: 独立读取冻结开发协议、三组已完成的实际 API 正文/来源/metadata，以及首轮 A/B 的原始 generate 流。未读取本轮 critic 稿件，未运行模型或测试，未修改实现。本报告是 Agent 逐题语义审阅，不是外部真人盲测，也不是关键词或 judge 分数验收。

## Decision

**停止关闭 grounding 的策略资格评估，保留默认 `GROUNDING_CHECK_ENABLED=true`；不运行冻结留出。** 首轮 B 的零值题实际发布了无据断言、长篇重复和缺少必需条件的正文，不能因有来源或前几段答对就判整题通过。第二轮 B 同题又在生成阶段耗尽预算。主 Agent 已终止后续控制器/runtime，`stop-decision.json` 记录 `qualification_stopped` 和留出未运行；第二轮 A 已启动但未完成，原始数据保留。

已有完整结果是 **A + B + B 共 12 条**，不是合格完成的 AB/BA 对照；12 也不能冒充包含未完成 r2A 的全部尝试数。两轮 B 的 8 条中，6 条主要事实、比较/条件和引用语义完整，1 条正文实质不合格，1 条未完成。英文题还需单列下述固定中文提示边界，不能把这 6 条简写成“全文所有维度无条件通过”。A 四条均未交付业务答案，质量不可评估，不能当 0 分或正确基线。

这不撤销最小开关 bug 修复的代码评审许可。PR4 可作为**默认不变的配置修复**独立交付；本实验不支持默认关闭、质量不退步承诺或推广。默认 true 也不代表当前 A 的可用性已合格。

## Evidence Boundary

- 协议：集成树 `/home/outsiderzz/Projects/RAG-readiness/docs/specs/grounding-disable-hotpath/validation/development-v1.json`，题目/原文/必需事实在第 5–94 行，停止与计时规则在第 224–229 行；`all_manual_required_must_pass=true`，禁止单数字或关键词评分。
- 下文 `r1-A`、`r1-B`、`r2-B` 分别指 `/home/outsiderzz/Projects/RAG-readiness/data/eval/grounding-disable-hotpath-20261110/development/r1-A-c1/thinking-c1/`、`r1-B-c1/thinking-c1/`、`r2-B-c1/thinking-c1/`。
- 已读各目录 `result.json` 的四条完整正文与全部来源内容，并从 `model-http-responses.jsonl` 解析 SSE `choices[].delta.content`；没有把隐藏 reasoning 当成用户正文。原始文本重复段逐一归类，未只取开头或截断摘要。
- 模型为 `qwen3.5:9b`，同一冻结配置仅切换 grounding。停止凭据为实验根目录 `stop-decision.json`；本报告未启动或消费留出。

## Question-by-Question Assessment

| Case | r1-A published result | r1-B / r2-B actual answer assessment |
|---|---|---|
| `ih2_06` | 预算终态，无正文/来源可评质量 | 两轮 B 都给赤砚 9 小时、芦序 600 分钟=10 小时并明确芦序记录更长；保留 8 W / 5 W，明确不能比较相同负载优劣，没有比例外推。两份来源与事实对应，中文完整。主要质量通过。正文在 r1-B/r2-B `result.json:50`。 |
| `dev_zero` | 预算终态；内部生成不等于已交付正确答案 | 首轮失败，详见下节；两份来源确实是对应计时器测试，编号可对应来源，但这不能支持新增误差断言。第二轮仅预算消息、无来源，未知而非正确拒答。正文分别在 `result.json:248`。 |
| `dev_calibration` | 预算终态 | 两轮 B 均保留“正常连续使用”“建议”“120 个日历日”；首次从完成投入使用确认起算，排除出厂/收货/入库；更换后先校准，再从校准完成日起算。单一来源支持全部事实，没有把建议改成强制。主要质量通过；r1-B `result.json:446`、r2-B `:406`。 |
| `dev_missing` | 预算终态 | 两轮 B 的英文业务回答都明确未提供价格，没有把 42 mm 当价格；18 个月保修从 delivery 起算，未改为 manufacture/sale，并明确引用产品资料。主要事实、缺失信息边界和业务回答语言通过；r1-B `result.json:628`、r2-B `:588`。但完整 API 正文末尾含两段中文提示，不能称全文纯英文，见下节。 |

A 的四条预算消息位于 `r1-A/result.json:50/:232/:414/:608`，sources 为空，confidence=None，validation=block/degraded。它们不是对资料不足的语义拒答。B 的非预算答复均显式提示尚未完成依据核验，grounding.raw_score=None、coverage=None、degraded=true；这与来源匹配及较高检索置信度是不同信号，不能据此宣称已经语义验证。

## Material Failure and Attribution

首轮零值题的最终正文为 **13,627 字符、322 个空行分隔段**，包含 52 个“最终回答”段及大量反复解释检索指令的元提示。开头正确列出 0 毫秒 / 0 秒及已完成测量，但后文有肯定句 **“'0' 存在测量误差”**。两份原文只记录本次已完成测试的零偏差，完全没有这条误差判断。正文还遗漏冻结必需的 **10 分钟基准条件**，末尾停在未完成的纠错列表。来源真实和前文部分正确均不能抵消后文无据断言。

“数值相同但单位不同”不等于明确声称 0 ms≠0 s，不能把它夸大成已发生的数值换算错误；但回答没有清楚完成物理偏差相等的说明。停止判断已有无据内容、条件遗漏和严重重复为充分依据，不依赖该措辞争议。首轮原始流的 finish_reason 为 stop，不能无证据称为 token cap 截断。

**归因修正**：`r1-A/model-http-responses.jsonl:12` 与 `r1-B/model-http-responses.jsonl:8` 中此题的原始 generate 正文逐字符相同，均为 **13,569 字符**，均含同一无据句和同一条件遗漏。A 的比较题原始生成也有较长元提示重复。因此不能宣称开关制造了新的生成缺陷，也不能宣称 A 的 NLI 已正确判出了该错；A 实际只是耗尽预算后未发布。B 的新增交付结果确实把既有不合格生成呈现给用户，这足以使关闭策略不满足质量资格。

英文题的两条最终正文均在英文业务答复后附上“声明尚未完成依据核验”及 AI 免责声明的中文文本。它们是现有应用提示，不能归因于模型没有按英文回答，也未改变价格/保修事实；但冻结的语言维度要求必须如实披露：**英文主要回答成立，完整 payload 并非全英文**。没有为了形成通过数而删除这些提示或改写冻结要求。

## Timing and Cost Interpretation

| Case | r1-A effective answer TTFT | r1-B body arrival | r2-B body arrival |
|---|---|---|---|
| `ih2_06` | None | 29.270 s，主要语义完整 | 29.372 s，主要语义完整 |
| `dev_zero` | None | 131.288 s，正文质量失败 | None；180.049 s 后预算终态 |
| `dev_calibration` | None | 34.400 s，主要语义完整 | 29.071 s，主要语义完整 |
| `dev_missing` | None | 39.228 s，事实完整，中文应用提示另列 | 39.178 s，同一语言边界 |

A 的原始 ttft_ms 约 180,010 ms 仅表示预算消息到达，不能用 180 秒作成功基线计算“降低百分之多少”。B 零值题的 131.288 秒是实际错误正文到达时间，也超过预设 90 秒恢复交付门槛；不能纳入合格答案的延迟分布。r2-B 的零值题 generate timed_out/completion_unknown=1，同样不产生有效答案 TTFT。没有形成有效 A/B 成功配对，因此不能宣布达到 30% 配对中位数目标。

三份 HTTP 日志分别记录 **34 / 16 / 16 次模型物理尝试**，其中 judge 为 **18 / 0 / 0**；B 每组均为 intent、agent、grade、generate 各 4 次。该证据支持关闭路径确实去除了在线 judge 尝试，不能直接换算 token 或 GPU 成本，也不能等同每次调用都成功。A 部分 judge 请求失败/超时；各请求计时可能重叠，不能把时长简单相加当墙钟。所有原始 `quality_pass` 都为 null，汇总的 quality_pass_rate_all=0 不应被解释成语义实测 0 分，更不能将空关键词视为通过。

## Five-Step Disposition

| Finding | Severity | Decision | Evidence / implemented alternative |
|---|---|---|---|
| RQ-D01：关闭策略已发布实质不合格正文，资格未通过 | High | `defended-with-alternative` | `r1-B/result.json:248`；停止资格、留出未运行、默认 true。设计第 18 行已规定该分支，`stop-decision.json` 记录执行结果。该标签接受受限交付，并非声称生成质量已修好。 |

1. **事实**：完整正文和两份来源证明无据句、遗漏及重复；原始 A/B 流又反证“由开关新制造生成错误”的过度归因。
2. **触发**：真实首轮 B 已发布该正文，第二轮同题未完成；不是假设异常。A 没有正确交付，不能用不可评基线替 B 免责。
3. **成本与影响**：该题直接违背本次核心质量门槛；继续跑满不能修复已发生的错误。重写 prompt 或扩大推理机制不是这次开关修复的必要成本。
4. **范围**：资格停止、默认选择和如实汇报在本任务内；本轮不追加生成优化、阈值放宽或新试验。24 QA 是上限，不是必须消耗的配额。
5. **替代**：按原设计保留默认 true、停止资格与冻结留出，只交付已有开关语义修复。已完成和未完成原始尝试保留，不冒称完整 AB/BA、不授予默认关闭许可；这是本次范围内可接受的替代。

`stop_on_new_material_error` 应按**新增实际交付中的实质错误**执行，不能误写成已证明新生成回退的因果结论；即使只按生成错误是否新增作狭义解释，整题必需条件和 90 秒门槛也已经失败，仍没有继续资格的依据。现有停止决策正确；无需为凑满轮数恢复运行。本报告没有认定生成问题已 closed，也没有把修复开关的功能正确性与关闭后的内容质量混为一谈。
