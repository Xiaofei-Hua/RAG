# Defender — Greeting Intent Boundary

**Review date**: 2026-11-10。  
**Scope**: 本功能 requirements/design/tasks，`core/intent/classifier.py`、general profile，以及已完成 `bounded-local-rag-holdout-v1` 八槽原始结果与十五条模型请求。独立审阅，未读另一评审；未修改业务代码或运行模型/测试。另按授权冻结两题补充留出，不在本报告暴露新题内容。

## Decision

**设计无 Critical/High 阻断，允许最小实现。** 已复现的问题是 ASCII 闲聊关键词在普通单词内部命中，修复该条件即可；保留中文包含匹配、RAG 关键词优先级和既有 LLM 分类路径。不因这次复现重写意图策略或把普通聊天统一改为无思考。

原留出整体为 **5 条核心回答合格、2 条 Fast 未回答、1 条 Thinking 错路由后超时**，不是 8/8 成功。原题复测只算已暴露回归；新的独立补充留出另行验证。当前结果不提前授予默认推广资格，但也不能把尚待 legacy 对照归因的两条检索不足答，直接认定为有界生成导致的质量退步。

## Decision Table

| ID | Severity | Decision | Evidence | Design |
|---|---|---|---|---|
| GIB-D01 | High（已复现缺陷；拟定设计已覆盖） | accepted | `classifier.py:133` 使用任意子串；真实第八槽出现 general_chat/0.9，第十五次模型请求没有资料且走无 none 的普通聊天，45.002 秒无正文。 | `design.md:3–4` ASCII 边界匹配及实际分类 API 回归 |

## Five-Step Assessment — GIB-D01

1. **事实核验**：`data/profiles/general.yaml:42` 包含 hi；`classifier.py:125–139` 将 query 小写后直接判断关键词是否位于文本任意位置。真实问题的 which 包含 hi，满足该条件。此处不需要猜测 LLM 分类失败。
2. **可触发性**：`classifier.py:198–201` 的异步入口在命中时提前返回，跳过正常结构化分类。结果第八行 intent 事件明确 general_chat，随后唯一模型请求为普通聊天 system+user、无检索证据、max_completion_tokens=4096、未设置 reasoning_effort；与错误路径一致。同步 classify 原本直接走模型，不能据此宣称同步也发生了同一快捷误匹配。
3. **成本与影响**：常见英语词可稳定使信息问题跳过检索且本次超时，影响实质交付；一处匹配条件及直接回归即可修复，成本低，必须接受。
4. **范围**：只修 ASCII chat_keywords 的词边界，关键词先转义，短语边界保持整体处理。中文规则和 RAG 优先级不变；无新状态、模型用途或额外调用。正常 LLM 分类是原有兜底，不应把恢复它计为新补写流程。
5. **等价替代**：没有必要加入题型规则、硬编码 which/this 排除表、强制 RAG 或新分类器。按实际关键词的词边界统一匹配更小且覆盖已复现原因。返回不确定后继续原路径，不将未判断当作低质量 0 分。

目标是排除长词中的误命中，不保证带真实独立招呼词的复杂混合请求全部重新分类；那是既有语义，不在本次无证据扩展。原有大小写处理及 Hi!/Hello、中文快捷行为用既定定向测试保留即可。

## Original Holdout Full-Answer Assessment

| Slot | Mode / case | Result and support |
|---|---|---|
| 1 | Fast / unit_conditions | 未回答。资料不足文案，模型调用 0；来源卡已有两泵原始记录，但没有给出要求的换算和比较。不能算正确业务答案。 |
| 2 | Fast / explicit_missing | 未回答。资料不足文案，模型调用 0；来源卡已有所需环境表，不能以安全拒答代替已知运行范围与未知存储范围的分别回答。 |
| 3 | Fast / version_conditions | Pass。R3.1 不支持、R3.4 需管理员与 FAT32 同时满足、仅升级不足，引用准确。结论/条件有重复但无指令循环或事实矛盾。 |
| 4 | Fast / threshold_condition | Pass。257 L 超过 240 L，须立即更换而不能等第 28 日；保留从安装起 28 日及先到为准、水质和 6–32°C 范围。对题设 22°C 的适用正确，未逐字重述 22/day17 不构成实质遗漏，正文英文。 |
| 5 | Thinking / unit_conditions | Pass。2.3 L/min→138 L/h，明确 138>126；两泵分别 70/110 kPa，不能外推同压优劣，两来源准确。 |
| 6 | Thinking / explicit_missing | Pass。存储范围未给，运行 12–38°C 且含端点，未将 24 V 混入温度，英文及引用准确。 |
| 7 | Thinking / version_conditions | Pass。两版本能力与必要条件完整，没有把两个条件改成任选或添加新条件。 |
| 8 | Thinking / threshold_condition | 无回答，45.002 秒超时，valid TTFT=None；错路由是已确认原因，不能给空答案质量通过。 |

五条生成正文没有发现新实质事实/条件/来源错误。英文业务正文附固定中文 AI 提示，不能称整个 payload 纯英文；Fast 来源卡里的无关候选不能按总数称为正确 gold。编号/来源出现本身不是语义通过的依据。

## Attribution and Timing Limits

两条 Fast 原始 first_body_s 约 0.990/0.979 秒实际是信息不足通知；有效业务正文时间应为 None，并保留该通知耗时。五条完整业务正文时间为 3.719、3.978、7.432、4.455、6.513 秒；不能把仅成功分布或快速拒答拿来掩盖八槽中的三条未完成。

Fast 在生成前已返回弱证据终态，当前证据说明它们不是新 JSON 生成失败，却还不能单凭“检索没改”证明相对 legacy 完全相同。接受同题、同资料、同检索配置的 legacy 对照：若同样不足答，可把它们记录为现有覆盖缺口与整体未完成，不要求把检索算法重做作为本次生成默认资格的新门禁；若 legacy 可答，则需按差异重新裁决。不能只将拒答标为安全便称全部留出成功。

原 holdout-v1.json 从旧开关实验复用了 corpus/cases/manual；其 configuration 仍含 A/B、temperature=0 等旧配置描述。此次实际 bounded 生成 wire 为 none、2048/2048，控制为 none、256/256，合计五次有界最终生成、九次控制、一次误路由普通聊天。最终报告须区分冻结题材/义务与实际执行配置，不把旧配置段当作这轮真实 wire。

## New Frozen Supplement

已写 `bounded-local-rag/validation/holdout-routing-v2.json`：两道全新英文题、两份资料，兼容 corpus/cases/manual_required/manual_derivation；普通 which/this 不含独立招呼意图，涵盖多条件适用、可复核推导与缺失信息。计划两模式各一次，共四槽；不强制 RAG，不把评审义务或参考推导传入模型。

实施方在代码冻结并运行完成后才读取题目与参考内容；本报告与消息不暴露新题名、数值或答案。复用已批准的质量和耗时标准，不以新题更容易或关键词得分替代完整回答审阅。原留出失败继续保留，本补充不得改写历史为首次全部成功。
