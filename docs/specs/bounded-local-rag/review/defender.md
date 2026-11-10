# Defender Review — Bounded Local RAG

**Review date**: 2026-11-10。  
**Review scope**: requirements/design/tasks v1、发布树实际生成/控制/输出/流式入口、当前安装的模型客户端代码。按 defender 五步决策树独立预审，未读本轮 critic 稿；未读冻结留出、未运行模型/测试、未修改业务代码。用户当前 AGENTS 的性能主线与最新授权优先于发布树旧版说明。

## Decision

**Current decision (v2)**: 已核对 design v2 第 14–15、30–35 行；BL-D01/02 的设计接线已明确，无剩余 Critical/High 设计阻断，允许进入红→绿实现和既定开发机制试验。默认仍为 legacy，尚无真实质量/默认推广许可。以下 v1 独立初审保留历史，最终复核见文末。

**一次 no-think 检索作答、实效输出预算与零在线 judge 的方向可行，值得按当前有限实验验证。** 它直接针对已观测的长思考、重复正文和逐句核验成本；继续叠加同模型 judge 或事后补写不能解决该瓶颈。显式单位推导、比较结论、工况/计时条件、缺值边界及语言要求都是通用任务约束，没有把题目答案编码进业务逻辑。

v1 仍须把两个既有入口差异写成具体接线决定，见 BL-D01/02；这两点只需最小共用 finalizer/策略判定，不要求新发布框架、全局调度或更多实验。修订落实后可以编码，默认暂为 legacy；最终默认与合并须以真实完整验证结果为据。用户已授权修复后合并 main，不能再次用“仅配置修复可交付”替代这次完整目标。

## Decision Table

| ID | Severity | Decision | Evidence and minimum correction | Design revision |
|---|---|---|---|---|
| BL-D01 | High | accepted，v2 设计已落实 | Fast 三入口当前不执行输出护栏；Thinking 提前发 token。明确各入口共享检查后最终正文，并覆盖真实事件顺序。 | v2 第 32 行 |
| BL-D02 | High | accepted，v2 设计已落实 | cached_faith=None 会让 Output 再调用 judge。Generate/Output 必须共用 bounded 适用判定，保留 None/degraded 和来源/PII。 | v2 第 31 行 |

## BL-D01 — Final Output Boundary

- **Location**: `core/fast_mode.py:233/:326/:394`；`agent/skills/generate/skill.py:577–588`；`agent/harness/orchestrator.py:538`；`api/routers/chat.py:1068–1077/:1218–1226/:1267–1289`；design v1 第 17、20、25 行。
- **Symptom / impact**: Fast sync/async 直接返回模型文本，stream 直接发送片段，没有现成 OutputGuardrail 可“保留”；Thinking 在生成结束和 after-hook 之前已发送 custom token，API 直接转发。仅在最后改写结果不能撤回已发布的 PII/草稿，Fast 也不会因此获得来源/结构检查。
- **Root cause**: v1 的“复用现有输出检查”没有区分有 after-hook 的 Thinking 与没有该步骤的 Fast。
- **Recommendation**: 一个小型输出完成函数复用现有 GuardrailManager/OutputGuardrail；Fast 三入口都调用它，再交付 answer/done。Thinking 的 custom 生成片段仅内部缓冲，after-hook 后最终消息才作为正文来源；API 不得拼接旧草稿和检查结果。现有状态事件可继续。沿用 kept evidence/source 集合，无需新共享状态键或回移整套 readiness 框架。
- **Verification**: 用实际生成与 after-hook 的事件顺序跑 JSON/SSE；模型先产出含测试 PII 的片段，最终检查后响应、SSE token/done、保存的回答一致且已脱敏。Fast 同样经过真实输出检查；不能仅让 mock harness 先清理再吐 token 来证明旧主流程已修。
- **Status**: 设计修订待落实；不是新代码已复现失败的虚报。

Five steps：①上述调用点直接证实现状，v1 方向正确但接线假设不完整；②正常 Fast 成功生成及 Thinking 流式生成均可触发，不是假设异常；③影响直接涉及本次保留的 PII/来源边界，修复成本为中等以下；④属于 REQ-001/003；⑤共用完成函数与仅发布最终消息是足够的最小修复，无需额外发布阶段或第二模型。接受修订。

## BL-D02 — None Does Not Disable the Online Judge

- **Location**: `agent/guardrails/output_guardrails.py:123–139`、`manager.py:124–130`、`grounding_guardrail.py:99–100/:181–182`；design v1 第 17、20 行。
- **Symptom / impact**: Output 仅在 cached_faith 非 None 时复用；bounded 生成若只写 None，且默认全局 grounding=true、有 contexts，输出阶段会重新进入 check_grounding。零 judge 和延迟收益因此不成立；改写全局环境来躲开它又会影响 legacy 或其他 provider。
- **Root cause**: 缺失结果与有意关闭语义评分均使用 None，不能只靠该值决定是否发起模型调用。
- **Recommendation**: 定义一个无请求可变全局状态的 bounded 适用判定，让 Generate/Output 两处使用同一结果，或在两者共同的在线 GroundingGuardrail 边界按同一部署策略跳过。不得禁用整个 hallucination/source check；返回未核验的 None/degraded，保留来源、结构、PII。优先复用配置判定/现有 metadata，不为此引入新 shared_state 键。
- **Verification**: 全局 GROUNDING_CHECK_ENABLED 保持 true，bounded 的真实 Generate + Output 路径仍零 judge；legacy、未匹配 provider/model 继续旧语义。API/最终正文必须有明确未核验表示，综合 confidence 不能被称为语义支持分数。来源错误及 PII 清理仍有效。
- **Status**: 设计修订待落实。

Five steps：①None 分支的再次调用直接可读；②正常有证据请求必然到达该分支；③这是本次核心性能目标，不能把再次逐句 judge 当安全补偿；④属于 REQ-002/003；⑤共享判定就是等价且更小的实现，不必新增 skip 开关矩阵或伪造 0/1 分。接受修订。

## Implementation Clarifications Within the Approved Scope

- **Wire budget**: 当前安装的 `langchain_openai/chat_models/base.py:3151–3167` 将普通 max_tokens 改名为 max_completion_tokens；仅在模型字段上写 2048/256 不能证明本地引擎收到兼容上限。可复用 extra_body 的最终 HTTP 合并传 max_tokens；结构化 Intent/Grade 先组装 structured Runnable、Agent 先 bind_tools，再施加用途参数，实际捕获 HTTP 中的字段和值。禁止全局修改共享模型导致工具/通用聊天也被误绑定。sync SDK 与 LangChain 各入口使用相同预算契约。
- **One generation**: `generate/skill.py:221/:574` 有外层重试，`:695–715` 有 length 再生，`:739–742` 有 SDK→LangChain fallback。bounded 必须避开这些再次生成路径，已收到部分正文后失败只交付安全终态，取消仍传播。Fast/Thinking 现有 StrOutputParser 会丢掉 finish_reason；先保留模型响应/流结束 metadata，再判断 length/空输出，不能把截断正文装成成功。对这些已知路径做参数/调用数和 length 回归，已包含在 v1 的验证范围。
- **Default scope**: requirements 第 5 行为本地 Qwen3.5:9b，design 第 14 行却写整个 Qwen3.5 家族。自动默认应收窄到真实验证的 endpoint、9B 模型标识与 prompt/profile 组合；其他模型、provider、未验证 profile 继续 legacy。无需在线探测服务或新模型注册系统。回滚是否需重启要与现有缓存一致并写清。
- **Prompt and source contract**: 通过 DomainProfile 添加/选择 bounded 通用提示，legacy 原文保持可回滚；保留检索材料的可信边界，允许基于材料的明确算术，不允许按负载擅自外推。若采用来源名引用即可复用现有匹配规则；如使用证据编号，必须按实际 kept-set 定义映射，不能把去重后的来源卡索引冒充文档编号。无必要扩大成全局引用解析器。
- **Language and degraded delivery**: 不仅检查生成的英文主体，还检查应用追加提示；可以保持已明确披露的固定中文通知边界，或提供与问题语言一致的简短未核验文案，但不能在报告里删除通知后声称全文纯英文。错误终态、拒答、None 信号与正确缺值回答分别记录。

## Experimental Assessment

8 次开发机制试验上限与随后有限 API/留出验证和本变更相称；无需增加大量消融组合。原问题已经暴露，适合作为开发回归，不能再称盲测；冻结留出未读取。正式运行前只需把既定矩阵写清：同一最终发布源码中 legacy/bounded 的定义、Fast/Thinking 分组、轮序、失败/取消归属与 P95 计算范围；不是要求增加问题或轮数。

实际请求体、响应 finish_reason/usage、是否有隐藏思考及在线 judge 数共同验证机制，不用工厂参数或字符数冒充生效 token 上限。P95≤30 s 是当前场景目标；单次生成最多 1 次、judge 0 次是机制约束；全文事实/比较/条件/引用和缺值边界必须独立通过。180 s 预算消息仍不是有效 TTFT；失败、length、空答、无依据扩写均不得从质量分母中删去。开发机制失败后定位并修订当前机制，不能继续消费留出或把失败策略默认化。

独立核对的官方资料支持参数化关闭思考和模式化采样，但不证明本机已生效：Qwen3.5 不支持依赖旧软命令切换，建议非思考一般任务使用 temperature=0.7/top_p=0.8，presence_penalty 需权衡重复和混语言；本方案 0.5 是实验选择而非原样官方预设。[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3.5-9B) Ollama 文档列出 max_tokens 与 reasoning_effort，并说明 none 的兼容行为；仍以当前实际引擎响应为准。[Ollama compatibility](https://docs.ollama.com/api/openai-compatibility)

## Remaining Boundary

没有要求全局调度、第二次生成、在线审稿模型、哈希门禁或更多冻结题。策略是否最终默认取决于完整结果；开发成功不等于留出通过，CI 修复也不代替性能成果。本次独立预审只要求上面两个入口事实在设计中闭合，后续实现与结果仍按既有任务验证。

## v2 Final Design Permission

已独立读取 v2 的完整修订，不读取 critic 新稿。两项 High 均已按最小方案接受并写入设计：第 31 行用同一 bounded 判定阻止 Generate/Output 在线 NLI，第 32 行明确 Fast 新增一次共用 finalize、Thinking 只发布 after-hook 后消息并用真实 LangGraph 事件回归。因而“保留 None 却重新 judge”及“Fast 以为已有护栏”的设计缺口闭合；实现验证仍待红绿，不把设计批准写成代码缺陷已经 closed。

第 33–35 行落实 finish_reason/空输出在 parser 前判定、bounded 禁止旧再生/fallback/重试、最终 HTTP token 字段映射和缓存隔离；第 14 行将默认作用范围限定为精确 9B/general。最终序列化映射与此前提出的 extra_body 是等价实现选择，实际 HTTP 回归即可裁决，不要求叠加两个适配器。移除 presence_penalty 是可接受的保守收窄；本 defender 未另行审计本地 runner 源码，也不会把公开 API 接收字段当成实际采样已消费的证明。后续只验证 v2 真实使用的 T=0.7、top_p=0.8 与 no-think/输出预算。

**可以开始实现和原定有限试验，不需新增矩阵或另一次用户确认。** 默认和 main 合并仍以既定完整质量、留出与 CI 结果为准；本次许可不提前消耗留出，不新增发布框架或任务外门禁。
