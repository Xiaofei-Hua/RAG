# Code Defender — Bounded Local RAG

**Review date**: 2026-11-10。  
**Scope**: RAG-bounded 相对 a345114 的业务 diff，新增 policy/generation 模块、直接单元/进程内 E2E、Ollama patch 与部署指南。独立审阅，未读另一实现评审；未运行模型/测试、修改业务或服务。此代码审阅完成时尚未读取新留出结果，质量资格另报告。

## Decision

**未发现新增 Critical/High 可触发代码问题。允许继续既定最终回归和质量资格核验。** 实现保持一次最终生成，不追加语义 judge；编号渲染、预算与检查后发布的实际接线符合已审设计。此结论不等于最终模型质量、全量矩阵或远端 CI 已全部通过。

`models/local_rag_policy.py:9` 仍默认 legacy，auto 已实现但尚未默认启用；`utils/env_utils.py:79` 的默认模型已在工作树改为 qwen3.5:9b，显式 LLM_MODEL 仍优先。不得把“policy 默认未变”扩大为“所有默认模型字段均未改”。默认切换与交付仍按最终质量裁决。

## Implementation Assessment

| Boundary | Evidence | Assessment |
|---|---|---|
| 一次 JSON 生成与有效正文 | `core/local_rag_generation.py:27–85` | 在丢失 AIMessage 元数据前拒收 length/content_filter/空内容；严格解析完整 JSON，basis 非空、conclusion 必填，各段空白和无效 ID 整答失败；sync/async 各只调用一次，不做修补生成。 |
| 编号与真实 kept-set | `local_rag_generation.py:35–46,61–75`；`core/fast_mode.py:238–254`；`generate/skill.py:226–236` | 每请求生成 1..N enum，使用保留证据的平行来源列表，不把去重来源卡位置当证据编号。严格整数拒收 bool/0/越界，合法段由程序添加文件名并结论先呈现。 |
| 实际输出预算 | `local_rag_generation.py:59–74`；`models/local_rag_policy.py:36–40` | 生成绑定兼容 max_tokens 及 SDK 字段同为 2048，none/T0.7/p0.8；控制为 none、256。未使用该版本原生 runner 不消费的 presence_penalty。 |
| 控制结构保留 | intent/agent/grade/rewrite 的 chain/bound_model | 在 with_structured_output / bind_tools 时传入预算，不把结构化链降为丢 tools/response_format 的普通 binding；缓存按控制策略重新构造。普通聊天不硬改生成预算。 |
| 禁止失败后再生 | `models/llm_models.py:127–136`；`generate/skill.py:225,315–326,590,657–670` | 合格策略工厂 max_retries=0；Generate 仅一轮，绕开旧直接 SDK 与 LangChain 再生兜底；失败给安全终态、清生成状态。Fast 三入口捕获本次失败给安全文案，不重启请求。取消异常未转换成新请求。 |
| Fast 三入口输出边界 | `core/fast_mode.py:237–255,348–371,436–462`；`local_rag_generation.py:88–101` | sync、async、stream 均调用共用 finalize，来源/结构/PII 沿既有输出管理器；BLOCK/ESCALATE 或检查异常不返回未检查原答案。stream 完成检查后才发正文。 |
| Thinking 发布顺序 | `generate/skill.py:605–609`；`agent/harness/orchestrator.py:538–539`；`api/routers/chat.py:1273–1288` | bounded 不再通过 custom writer 发布未检查草稿；实际 after-hook 修改消息后才产生 node update/API 正文。不是用模拟 harness 人为调整顺序。 |
| 输出检查异常 | `agent/guardrails/manager.py:130–146` | bounded 的检查异常与 BLOCK/ESCALATE 直接替换为安全终态，避免 lifecycle 吞异常后继续交付含 PII 的原文。legacy 既有路径没有借本修复扩写。 |
| None 与在线成本 | GroundingGuardrail 两入口；`output_guardrails.py:123–132`；`api/routers/chat.py:515–521` | generation/output 共用策略，bounded 均不运行在线语义核验；faithfulness=None、degraded=true，保留检索置信度但不伪造 grounding 通过。 |
| auto 选择与回滚 | `models/local_rag_policy.py:8–57` | exact model/profile/http-loopback:11434/v1 才查版本；精确 backport 版本启用，未知/异常/其他版本回 legacy。显式 legacy 不访问版本服务；origin /api/version、1 秒、trust_env=False、客户端关闭、结果缓存。 |
| 英文招呼边界 | `core/intent/classifier.py:134–144` | ASCII 关键词 re.escape 后整体词边界匹配；中文包含判断和 RAG 先行顺序不变，未加入具体题名或排除词列表，which/this/within 回到原分类。 |

bounded 链按当次 profile 构造，不复用 legacy 生成链；控制链按策略键更新。应用/运行时配置变化按部署文档重启，不能宣称当前单例工厂支持无需重启的任意 provider/model 热切换。

## Tests and Red-to-Green Evidence

- 已读 `tests/unit/test_bounded_local_rag.py`：真实 ChatOpenAI HTTP 序列化参数、无效/重复来源编号、严格解析、一次调用、旧策略保留、None/degraded 与两份 golden。长输出的 SDK LengthFinishReasonError 和应用自身 RuntimeError 都是拒收，均要求只调用一次。
- 已读 `tests/e2e/test_bounded_local_rag_api.py:25–109`：真实 IntentClassifier、AgentHarness/默认技能与 after-hook，模拟 HTTP 模型和检索。Fast/Thinking × JSON/SSE × 检查正常/抛错，验证无原始 PII、token 拼接等于 done、历史无 PII、一次最终生成、judge 不运行。它证明真实编排发布顺序，不证明真实模型内容正确。
- 已读 `test_local_rag_policy.py` 的精确/官方/其他/不可达版本与缓存、legacy 回滚，和 `test_greeting_intent_boundary.py` 的三个普通长词与真实招呼兼容。mock 版本接口不调用运行中服务。
- 最新可核实定向快照：`validation/default-routing-green.log` **39 passed in 3.27s**。未以消息口述替代日志；本轮不重复执行。
- 保留失败时序：初始 `red.log` 7 failed/1 passed；结构化红 7 failed/8 passed，其名为 structured-green.log 的中间快照实际仍有 1 failed/14 passed；API 校正 fixture 后红 8 failed；编号/双预算红 3 failed/14 passed；比较 golden 红 1 failed；默认/路由红 8 failed/4 passed。后续 39 项通过才覆盖当前修改，不能把中间文件名当作通过证据。
- 完整矩阵与最终 Ruff/format 仍由主流程完成。本次阅读时 classifier import 顺序及若干新增排版尚需既定格式整理；不据此新增模型试验或额外交付门禁。

## Runtime Patch and Deployment

`deploy/patches/ollama-0.24.0-thinking-format.patch:7–8` 与已核实上游 #15901 的生产修复一致：think=false 时从 gemma4 特例扩为支持 thinking 的 parser，立即应用 format；没有换推理后端或 GPU 库。

`docs/deployment/BOUNDED_LOCAL_RAG.md:13–24` 使用固定 v0.24.0 源码、Go 1.26.0、独立版本标记与 binary，保留官方同版 GPU 库；`27–41` 描述专用 override、服务端 /api/version 核对与应用重启/回滚。版本标签是部署兼容标识，不是安全认证，不扩为签名/哈希框架。

本机已存在专用 override 是主流程提供的运行事实；本评审未操作或重启服务。后续仅核对实际服务版本，不因指南包含安装步骤而重复覆盖/重启现有已配置服务。留出/回归资格仍须与这个实际运行时对应，不能把官方 0.24.0 直接称为相同合格引擎。

## Honest Limits

- 编号合法不等于语义支持；引用程序渲染解决出处标识，完整事实/条件仍由真实结果独立评审。
- 原检索 weak/empty/conflict 终态保留，不能计为业务答案成功；本实现没有放宽检索阈值或给拒答补写。
- 普通聊天和 agent 直接回答等既有非最终 RAG 生成路径不因此全部获得本次 JSON/输出策略。不能宣称任意模型、所有入口都变成有界证据作答。
- 缓存版本在重启前不跟踪外部替换，首次并发未命中也不承诺严格 single-flight；既有部署契约已说明，有限成本无需新机制。
- 当前独立代码 finding 数为 0 Critical / 0 High；最终推广结论等模型质量、同题差异归因、完整回归及 CI，不用代码评审许可冒充交付完成。
