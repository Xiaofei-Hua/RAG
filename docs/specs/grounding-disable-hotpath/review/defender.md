# Defender — Grounding Disable Hot Path

**Review date**: 2026-11-10。  
**Review target**: requirements / design v1 / tasks；发布树 `RAG-grounding-switch` 与集成树 `RAG-readiness` 的实际 grounding、Generate 和输出检查入口。  
**Independence**: 先独立读取规格、相关规范和两树代码，再读取本轮 `review/critic.md`；未以 critic 结论代替核验。未运行模型或测试，仅写本报告。

## Decision

**允许进入最小红→绿实现；Critical 0 / High 0，无剩余设计阻断。** 接受既有全局环境开关的优先级澄清：`GROUNDING_CHECK_ENABLED=false` 禁用全部在线 NLI，显式 Output config=true 不能越过它；field factory 仅保留显式字段赋值，并使新建默认配置读取当前环境。既有实例不承诺动态订阅环境变化。

这是配置缺陷修复许可，不是默认关闭语义核验或性能/质量验收通过。默认 true 保持，真实结果仍需按已定 24 QA 上限记录。无需新增规则、模型、接口或实验轮次。

## Independent Evidence

| Boundary | Source evidence | Assessment |
|---|---|---|
| 失效路径 | 发布树 `agent/skills/generate/skill.py:319–352` 的 sync/async helper 直接调用 check/acheck；`grounding_guardrail.py:98–103`、`:177–182` 没有读取开关。 | 关闭 Output 语义分支不能阻止 Generate 先付出 NLI 调用成本，缺陷成立。 |
| 最小截断位置 | 发布树 constructor `grounding_guardrail.py:72–85` 只保存 judge，实际获取是 lazy；wrapper `:246–259` 只构造 guardrail 后进入公共入口。集成树 `_prepare:176–188` 是两个入口的共用前置。 | 发布树在 check/acheck 第一处分支返回；集成树在 `_prepare` 的声明提取之前返回，即可覆盖相关调用，不必改每个消费者。 |
| 配置读取 | `agent/guardrails/types.py:8–12` 已有 strip/lower 布尔规则；`:59` 当前在模块导入时计算默认值。 | 只把此字段改为 factory，沿用默认 true 和同一解析器；不扩展其他环境字段。 |
| None 与复合置信度 | 发布树 Generate `:1013–1027` 在 faith=None 时转移 grounding 权重并标 degraded；集成树 `_effective_grounding:430–444` 保留 raw_score=None、coverage=None 与 degraded。 | 禁用不得返回 faithfulness=0/1。复合 confidence 仍可能因 retrieval/intent 较高而较高，不能把其数值解释成已核验支持率，也不要求新增置信度上限。 |
| 来源与 PII | 发布树 Output `:170–212` 是语义分支之后的来源 fallback，`:238–283` 的安全/结构/PII 检查独立。集成树 Output `:196–204` 保留 assessment 并追加未核验提示，`:334–365` 保留 PII 与 grounding metadata。 | 关闭 NLI 不关闭全部护栏。regex 只能核对已有来源格式，不能声称它证明事实受证据支持。 |
| 当前发布路径 | 集成树 manager `finalize_output:72–122` 从 degraded assessment 生成原有 answer_validation；旧发布树没有同等接口。 | 按各树现有接口适配，不把集成收据/检查后发布能力冒称为此次回移，不顺带重构旧流式架构。 |

禁用先于空回答/无声明判断，避免旧发布树“无 hard claims 则 1.0”的分支被误用于禁用状态。当前结果中的 total/judged 等零计数只是未进入声明核验的既有结构表示，不能据此宣传已证明没有未知声明；原始分数与 coverage 的不可用语义继续保留。无需为此扩展结果 schema。

## Critic Adjudication

本轮 critic 没有新增 finding，逐项核对其事实与边界后接受“可进入最小实现”的结论；没有需要关闭的 Critical/High finding，也不虚构修复提交或测试结果。

| Critic item | Decision | Reason |
|---|---|---|
| 公共在线入口短路可覆盖 Generate / wrapper / Output 直接调用 | accepted | lazy judge 与两入口的实际调用顺序已独立核对，提前返回在常见路径可达。 |
| factory 保留字段覆盖，全局 env=false 优先 | accepted clarification | design 第 8 行“显式实例语义不变”应按字段值保留理解，不能解释为可越过总开关；主 Agent 已明确接受该层级。 |
| 复用 None 降级、保留来源/PII、默认 true | accepted | 两树现有路径具备必要消费者，不需要新状态或防御框架。 |
| 不把真实 24 QA 设计许可当作验收通过 | accepted | 性能收益和最终正文质量尚待测量；默认不变的配置修复与可选运行策略的资格分开判断。 |

## Five-step Rationale

1. **Fact**: Generate 确实绕过只存在于 Output config 的开关；模块导入时默认求值也确实会冻结旧环境。依据如上，未仅凭评审者权威接受。主 Agent另报告实际类加 stub 的复现：false 仍触发 sync/async 各一次 entail 并得到 1.0；这是主 Agent 的复现证据，本 defender 未重跑。
2. **Reachability**: 正常 Thinking 生成且有检索上下文即可触发；不是恶意输入或假设异常。wrapper 不提前取得 judge，因此公共入口短路足以消除该成本。
3. **Cost versus impact**: 两个前置分支/一个共用前置分支及单字段 factory 能修复已存在的开关契约，规模与问题相称。增加新核验器、专用问答规则或额外生成不是必要替代。
4. **Scope**: 严格限于 REQ-001/002 的开关行为，并验证 REQ-003 的既有降级/输出边界。未改默认、离线 eval/judge.entail、prompt 或不相关配置。
5. **Alternative and decision**: 接受入口修复与全局 env 优先；不接受只在 Generate 跳过一次调用而留下在线直接调用漏口。无其他必须修订的设计项，进入既定红绿与验收即可。

## Verification and Limits

- 既定红绿应覆盖 false/0/off/no、默认/true、同步/异步/wrapper，且禁用时连 lazy judge 获取都不能发生；新默认实例与显式字段覆盖分别验证。关闭后正常生成一次、NLI 零次与 faithfulness=None/degraded 是直接收益契约。
- JSON/SSE E2E 使用真实 GenerateSkill 和输出检查、mock 模型/检索；保留来源与 PII 断言。集成树沿用原发布门禁回归，发布树只验证其已有接口。这已在设计中，不新增矩阵。
- 四开发题 × A/B × 两轮 AB/BA = 16 QA，四独立留出题 × A/B 一轮 = 8 QA，总计 24 QA；这些是问答槽，不能误当物理 LLM 调用总数。A 的逐句 NLI 与 B 的零 NLI 应另行计数。保持同一 9B、预算、CONTROL 配置与 prompt。
- 最终审阅必须同时核对事实、条件、比较结论、引用、语言与未知字段；不能因 B 没有 judge 分数而自动判质量差，也不能因 B 更快而判正确。全部尝试的成功、超时、错误和缺有效正文应保留；只有有效配对计算延迟比，A 超时的有效正文时间为 None，不能填 180 秒作成功基线。
- 质量出现新增实质退步时停止运行策略资格；默认仍 true 的配置修复可以按实际证据交付，不把策略失败隐去，也不自动开启此前暂缓的其他步骤。有限开发/留出样本只支持本次受控配置结论。

**Review closure**: 本次必要边界审查收束。没有新增试验、范围外 backlog 或实现扩张要求；后续按既定规格实施和归档实际验证即可。
