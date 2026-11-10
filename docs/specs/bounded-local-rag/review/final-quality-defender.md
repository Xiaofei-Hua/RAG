# Final Quality Defender — Bounded Local RAG

**Review date**: 2026-11-10。  
**Method**: 独立 Agent 逐篇语义审阅，结合原始请求/响应、SSE 与实际来源；不是外部真人盲测，也不是关键词分数或在线 judge 通过率。本人先独立冻结 routing-v2 两题，实施方冻结代码并实际执行后才获准阅读本批结果。未修改提示/业务，未运行模型/测试，未读另一评审。

## Qualification Decision

**允许将默认选择切为 auto，且仅精确本地 qwen3.5:9b、general profile、实际服务版本 0.24.0-format-backport 自动启用 bounded。** 其他模型/profile/运行时维持 legacy，显式 legacy 继续回滚。`validation/host-runtime.json` 已记录宿主同一服务版本；已有专用 override 无需再次改动或重启。

依据是：最终开发 v7 的 16 条核心答案通过；原四题修复后回归交付六条正确答案、保留两条 Fast 未回答；两道新英文补充题的 Thinking 答案都完成多条件、推导、缺值义务，Fast 两条仍未回答。四个 Fast 未回答均有同题 legacy 对照，问题、来源正文和不足答文案一致、模型请求为 0，说明本次未降低既有检索交付覆盖。没有理由把修复所有旧检索不足答扩为本次生成策略默认资格的额外门禁。

这是有限作用域的质量不退步许可，不是“所有留出都答对”。最终回归加新留出共 **12 槽：8 条核心答案通过、4 条未回答、0 超时**；Thinking 6/6 交付，Fast 2/6 交付。当前许可仍需既定完整矩阵、最终格式/CI及发布工作完成，不替代这些执行证据。

## Cohorts and Preserved History

| Cohort | Slots | Complete core answers | Nonanswers / failures | Meaning |
|---|---:|---:|---|---|
| API development v6 | 16 | 13 | 1 未明确比较；2 非法 ID 被安全拒收 | 保留旧失败，不因后续修复重写结果。 |
| API development v7 | 16 | 16 | 无不可用；保留 API2-D01 非阻断引述归属瑕疵 | 4 已暴露问题 × 2 模式 × 2 轮，非 16 道独立题。 |
| Original holdout-v1 | 8 | 5 | 2 Fast 不足答；1 Thinking 错路由后 45.002 秒超时 | 首次留出真实失败，不可覆盖。 |
| Original questions regression | 8 | 6 | 2 Fast 不足答，0 超时 | 原题已暴露，仅称回归，不再称全新盲测。 |
| Independent routing-v2 | 4 | 2 | 2 Fast 不足答，0 超时 | 2 新英文题 × 2 模式；Thinking 两条通过。 |
| Original Fast legacy comparison | 2 | 0 | 同样不足答、0 模型 | 定位既有覆盖缺口，不计业务成功。 |
| New Fast legacy comparison | 2 | 0 | 同样不足答、0 模型 | 同样未发生相对新策略覆盖退步。 |

最终配置可读作开发 v7 16 槽 + 回归 8 槽 + 新题 4 槽，共 28 槽中 24 条完成核心回答、4 条未回答；必须同时保留上述分组与历史，不能只报“24/24”而隐藏未回答分母。

## Regression Full-Answer Review

证据：`data/eval/bounded-local-rag-holdout-regression/results.jsonl`。

| Case | Fast | Thinking |
|---|---|---|
| unit_conditions | 未回答，0 模型。 | Pass：岚柯 2.3 L/min=138 L/h，明确大于砺帆 126 L/h；70/110 kPa 分别对应正确，不能据此比较同压优劣；两来源齐全。 |
| explicit_missing | 未回答，0 模型。 | Pass：存储范围未给，运行范围 12–38°C 且含端点；不混用范围或把 24 V 当温度，英文正文与环境表对应。 |
| version_conditions | Pass：R3.1 仅屏幕汇总、不支持逐批 CSV；R3.4 新增但还需管理员与 FAT32 U盘同时满足。 | Pass：同一版本/必要条件关系，无新增必需步骤。 |
| threshold_condition | Pass：257>240，须现在更换；17 日未到 28 日不能覆盖体积上限；22°C 在 6–32°C、清水条件与安装日起算明确。 | Pass：明确体积上限先到、不能等第28日；257/240、17/28 与22°C范围正确。题设已给清水，未逐字复述水质不等于将规则推广到其他水质。 |

Fast 滤芯答案把文件给定范围表述为规则不可外推到其他水质/范围，这与受限规则适用边界一致，不构成另设寿命要求。两种模式都没有将“先到为准”误成必须同时满足两个上限。Thinking 原误路由题现有 rag_query 事件和完整有界答案，原 general_chat/超时问题得到实际回归确认。

## Independent Supplement Full-Answer Review

证据：`validation/holdout-routing-v2.json` 与 `data/eval/bounded-local-rag-holdout-routing-v2/{results,model-http}.jsonl`。

### Operating Modes

Thinking 结论逐项说明标准模式可用：14 V 在 12–18 V、31°C 在 5–35°C，风扇可选。高速模式不可用的三项原因全部列出：供电低于16 V、温度高于30°C、没有所需风扇，并说明三个条件必须同时满足。不存在把“满足一项即可”或“修复一个条件即可”偷换为通过的问题。

存储温度未指定，明确不能从运行范围推出存储范围；没有全盘拒绝可回答部分。正文英文，所有段落使用本次实际来源 Arvessa_S4_operating_modes.txt；该文件全部原文包含上述规则。结论中的“zero conditions are met”就是三个高速条件都不满足，语法略生硬但事实无误。**核心义务 Pass。**

### Capacity and Export

Thinking 正确算出计划4×4=16条、已有49条而64容量只余15格，明确16>15所以不能全存。该量化与“总65超64、差1”数学等价，不要求重复每一种列式。明确 USB 导出不删除本地记录，须完成并验证成功导出后另行手动清空，清空后64格足以容纳计划记录；没有建议未验证就删除或自动覆盖旧记录。

Wi-Fi 支持明确未指定，未把资料未说明说成硬件禁止；回答了其余可确定部分，引用 Elvoria_inspection_logger_retention_note.txt。重复列出规则和结论属于有限组织重复，没有元提示循环、自相矛盾或新无据事实。**核心义务 Pass。**

两题 Fast 都是信息不足文案，没有进入生成，不能因无幻觉而计为成功。这轮四槽不是四条合格答案。

## Fast Coverage Attribution

`bounded-local-rag-retrieval-terminal-baseline/results.jsonl` 的原两题，与原题 bounded 的 query、资料不足文案和来源相同，各模型起止计数均0。

`bounded-local-rag-routing-terminal-baseline/results.jsonl` 的新两题，与 routing-v2 Fast 的 query、资料不足文案及来源正文逐项相同，各模型起止计数均0。legacy通知时间约0.900/1.422秒，bounded约0.943/1.432秒；这不是有效业务首段加速或减速结论。

因此，四条问题的不足发生于本次最终生成之前，且已实际证明 legacy 同样未交付。可以接受保留这一既有覆盖边界并启用已改进的生成策略；不能声称检索覆盖被修复，或用safe refusal、metadata.refused=false、source_count替代完整回答判定。

## Timing and Model Cost

| Cohort / mode | Valid answers / attempts | Valid first-body time | Other outcomes |
|---|---:|---|---|
| Development v7 Fast | 8 / 8 | P50 3.188s；P95 3.936s | 无超时。 |
| Development v7 Thinking | 8 / 8 | P50 5.669s；P95 6.074s | 无超时。 |
| Original regression Fast | 2 / 4 | 3.316、4.695s | 两个不足答的有效 TTFT=None。 |
| Original regression Thinking | 4 / 4 | 4.538–7.669s | 原错路由已恢复，0超时。 |
| New supplement Fast | 0 / 2 | None | 两个不足答，通知约0.943/1.432s。 |
| New supplement Thinking | 2 / 2 | **9.257、8.011s** | 总耗时为9.358、8.121s，不能混作首正文。 |

所有已交付有界业务答案均低于既定30秒目标；样本很小，开发P95采用nearest-rank，不外推生产尾延迟。未回答不纳入有效正文分布，但必须同时报告上述分母。

另核对同问题 legacy 开发对照 `bounded-local-rag-paired-legacy-v1`：8 槽仅1条交付（Fast电池，首正文22.150s/总24.640s），该答案的明确比较和工况限制正确；另外7槽30秒观察窗口无正文、有效TTFT=None。bounded相应8槽全部交付且核心质量正确。不能将7个未完成当0分或30秒成功延迟计算总体加速百分比，也不能把这批30秒观察窗写成旧180秒实验。

v7/原题回归/新题的实际请求分别40/18/8次，其中最终JSON生成16/6/2次，其余为控制；各成功请求最多一次最终生成，在线语义judge0。生成两预算字段均2048，控制均256，reasoning_effort均none；已读取原始响应未见隐藏reasoning文本。三组 SSE token 拼接、done和保存正文逐槽一致。None/degraded继续表明没有在线语义评分，不表示已获得机器验证的忠实度1.0。

## Finite Qualifications

- 开发 v7 的 API2-D01 仍为 Medium 非阻断：将提示中的零值通用解释误标成资料引语，结论本身受资料支持。未修成逐字引文，不写“所有引述完美”。新留出未出现同类实质内容问题。
- 英文业务正文仍带固定中文AI提示，来源卡摘要会截断；本次依据完整原文和实际模型context审阅，不把卡片500字符摘要当全部证据。
- 原 holdout-v1 的题材/义务沿用冻结内容，但旧 configuration 段不能冒称这轮实际 bounded wire；真实请求字段以各批 model-http 为准。
- 版本、模型/profile和本机已测资源组合范围外不自动推广；这不是所有数学、代码或任意长文的性能/质量保证。
- 本报告授予上述精确作用域的质量许可；完整矩阵、格式与远端CI仍按既定流程收尾。保持原失败、拒答与统计分组，不再为获得更漂亮分数修改提示或消费更多题目。
