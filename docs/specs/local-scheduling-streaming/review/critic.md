# Critic Report — Local Scheduling and Streaming

**Review target**: `docs/specs/local-scheduling-streaming/design.md` v1, requirements/tasks, and existing model/graph/API/output-check code at the qualified baseline.
**Review mode**: Full critic + STRIDE (only the output-release/PII and queue boundaries changed here).
**Review date**: 2026-11-11
**Independence**: 本评审未读取 defender 报告，未运行真实模型，未修改业务代码。

## Summary

- Critical: 0
- High: 2
- Medium: 0
- Low: 0
- Decision: **先作最小 v2 修订，再进入编码。** 两项问题均是现有代码可直接触发的接线缺口，不要求增加模型调用、语义证明或扩大实验矩阵。修订后的实现仍须以已计划的红绿测试及真实质量/收益对照裁决。

## Findings

### F-01 — PARTIAL and completion metadata currently disappear at the graph boundary

- **id**: F-01
- **severity**: High — `critic.md` §2 High(a)：失败边界未闭合；同时涉及 `agent/AGENTS.md` §2 跨节点状态契约与生成热路径，适用热路径最低 High。并非否定增量发布算法。
- **label**: issue (blocking, must-fix)
- **location**: `docs/specs/local-scheduling-streaming/design.md:20-25`; `agent/skills/base.py:121-126`; `agent/harness/orchestrator.py:533-539`; `api/routers/chat.py:1074-1103,1273-1295,1345-1396`。
- **symptom**: 模型已产生一个合格段落，随后以 length/格式错误/检查失败结束。按 v1 返回 `SkillResult(PARTIAL, metadata={generation_complete: false})`，但 `to_state_update()`只输出 messages/state_updates，status/metadata只进 trace，Graph updates 中不可见。Thinking router 仍保存正文并构造普通 done/评测 metadata。Fast router 同样只取内层 done.sources，丢掉新增终态。因此仅设置 PARTIAL 或 Fast done 字段不足以兑现“不能当正常成功样本”。
- **impact**: 用户得到部分答案但 API/评测可能仍视作完成，UI缺少可靠未完成标识。对应 `core/AGENTS.md` §3 generate降级与根规范“跨节点机器数据走shared_state”；token正文一致本身不能补回丢失的完成状态。
- **root_cause**: v1同时要求跨Graph传播生成终态、又声明“不新增shared_state键”，没有给出可穿过现有 `SkillResult.to_state_update()` 的合规载体。
- **recommendation**: 将 `design.md:20-25` 改为：receipt/检查器仍仅存SkillContext；公共生成终态新增generate唯一生产、API消费的命名空间整键（例如 `generation_outcome`，定义 `status/generation_complete/reason` 与正常/空/失败/部分路径的覆盖写语义），在 `agent/AGENTS.md` 登记所有权并在请求入口清除旧值。Fast通过FastModeResult/内层done显式携带同一语义，router合并到对外metadata；不把新机器状态塞入messages。若采用等价载体，须明确为何符合shared_state契约及sync/async对称性。
- **verification**: `tests/e2e/`使用真实Graph+router+guardrail、mock模型：第一段成功、第二段length/异常，断言Thinking与Fast外层done均为incomplete、评测metadata不计正常完成、token拼接=done.full_response=保存正文。随后同一会话正常生成必须恢复complete，证明没有继承旧状态；非流式入口也能识别未完成。沿用计划中的用例，无需新增真实模型实验组。
- **status**: open

### F-02 — Queue rejection is swallowed by existing control-call retries and fallbacks

- **id**: F-02
- **severity**: High — `critic.md` §2 High(a)：常见入口的过载失效路径未闭合；生成/路由热路径适用最低High。问题是新调度拒绝语义与现有异常处理不兼容，范围限于新busy/timeout信号。
- **label**: issue (blocking, must-fix)
- **location**: `docs/specs/local-scheduling-streaming/design.md:13-14`; `core/intent/classifier.py:158-188,207-239`; `agent/skills/agent/skill.py:167-202,261-269`; `agent/skills/grade/skill.py:217-259`。
- **symptom**: 占满1个活动槽和8个等待项后，发送不会命中关键词捷径的Thinking请求。首个classifier调用被调度拒绝，但现有 `except Exception` 会重试3次；最终返回fallback意图及confidence=0.0，router可能继续后续模型调用。同步Agent和启用的grade模型路径也有自己的retry/fallback。调度器本身“不重试”无法阻止这些调用方再次入队，也无法保证给用户明确busy终态。
- **impact**: 过载时请求分母/等待上限失真，多次无效入队加剧拥塞；队列拒绝被伪装成低置信度正常路由或通用成功正文，破坏REQ-302及“不可用不计0/不绕过降级重调”约定。无需复现任何模型错误即可触发。
- **root_cause**: v1没有区分主动背压与可重试的模型故障，也未指定busy/timeout跨现有retry/技能归一化层的处理方式。
- **recommendation**: 在 `design.md:13-14` 明确内部typed busy/queue-timeout信号；涉及本地调度调用的现有retry分支先识别此信号并终止当前请求，不重试、不改走另一模型调用。API/技能边界将其归一成已定义的可重试安全busy终态，完成状态为false、缺失质量信号保持None/degraded；不要把内部异常直接泄露给用户，也不要让classifier制造0.0作为本次拒绝的评分。覆盖 `get_llm` 和 `create_custom_llm` 两个本地工厂，同一endpoint使用同一队列。
- **verification**: 以Event控制1活动+8等待，走真实Thinking路由触发饱和及排队超时，断言该请求仅尝试一次调度、没有网络调用/后续模型回退、外层返回可重试busy/incomplete且不产生0分可用信号；清空队列后下一请求正常完成。同步调用方增加同样的typed rejection定向断言。沿用原计划队列/取消E2E即可。
- **status**: open

## Positive Findings

- **praise (non-blocking)**: 同一模型共享sync/async/stream槽、单应用worker限制、原子处理grant/cancel、短调用公平及老化规则，直接针对16GB单GPU的真实排队问题；没有把应用等待搬家包装成GPU吞吐提升。
- **praise (non-blocking)**: evidence先提取必要事实、answer首段携带结论全部限定，比旧末尾conclusion顺序更可能减少有效首段等待；仅以完整对象及真实分隔符发布，不修复半JSON，维持单次生成预算。
- **praise (non-blocking)**: 累计正文经现有检查、禁止改写已发布前缀、PII异常/BLOCK/ESCALATE终止、receipt只在同请求使用，已覆盖本次真正涉及的信息释放边界。
- **praise (non-blocking)**: 两轮小规模机制/API对照、独立新多条件留出、失败保留及独立回滚，足以裁决本次有限改动；不要求静态检查证明自然语言所有限制完整。

## Review Checklist

| Area | Result |
|------|--------|
| 单GPU资源与调度公平 | 方向成立；执行中验证实际queue/service时间，零收益时如实报告 |
| sync/async/stream对称 | 设计覆盖；两个本地模型工厂都必须使用同一队列 |
| SDK重入 | 设计者补充已检查锁定SDK，`_generate/_agenerate`不调用self流入口；接受v2删除可继承contextvar重入令牌，四入口各持槽，避免不必要机制 |
| 取消/流关闭 | 原子撤销或释放已授予槽已定义；测试须等待实际流关闭再断言下个调用进入 |
| 首段语义/引用 | 不以结构合法冒充事实支持；保持原定独立首段与全文审阅和留出 |
| 输出PII/检查失败 | 有缓解；完整段检测、前缀不可改写、失败不泄露原文 |
| 跨节点与同步终态 | F-01待修订 |
| 过载降级/不可用≠0 | F-02待修订 |
| 测试/回滚/收益 | 已有计划足够；红绿、E2E、Playwright、真实有限对照按原范围完成 |

## STRIDE

| Class | Assessment |
|-------|------------|
| Spoofing | 未改变认证/调用者身份边界；receipt不接受用户反序列化输入 |
| Tampering | 已发布正文只能追加；receipt须与本次已检查最终正文相同，拒绝重写旧前缀 |
| Repudiation | queue/service/call class与请求统计已有设计；不新增审计系统 |
| Information Disclosure | 已涉及PII发布边界有明确检查与失败终止；不扩展到无关密钥/上传/检索防御 |
| Denial of Service | 有界队列、等待上限、公平与取消成立；F-02指出现有重试会破坏主动背压 |
| Elevation of Privilege | 未改变Admin、网络监听或其他权限边界 |

## Coding Decision

F-01/F-02纳入最小v2并在tracking分配实现/回归验证后，可开始红绿编码；不要求先运行真实模型，也不把尚未实现的设计修订冒称测试闭环。实际发布/默认开关仍需原计划的质量与收益证据。


## v2 Admission Review — 2026-11-11

**Reviewed**: `design.md` v2, especially lines 25 and 37–42. 未读取defender报告、未运行模型。本节替代上文v1的编码阻断结论；保留原发现作为实现追踪依据。

- **F-01: design resolved.** `generation_outcome`由Generate唯一生产、整键覆盖，Fast使用同义结果，API显式读取并传递到JSON/SSE、最终会话保存与capture；历史接口读取保存状态。跨Graph仍只使用shared_state，检查器/receipt仍只留在SkillContext，边界已闭合。
- **F-02: design resolved.** typed `ModelBusyError`越过现有control/timed retry与0分fallback，分别在API intent、Fast入口及Harness graph边界归一为安全可重试终态；Harness独占`model_queue_outcome`，取消独立传播，边界已闭合。
- **Request reset interpretation**: 按设计者本次明确补充的“generation_outcome清旧值”执行，请求初始化清除两种outcome旧值。既有同会话回归应覆盖“前次complete → 下次在generate之前busy”，证明旧generation_outcome不会遮蔽model_queue_outcome；这是F-01/F-02原定回归的具体断言，不新增机制或真实实验组。
- 删除可继承重入令牌、保持四个实际SDK入口分别持槽，属于合理的最小化实现。

**Decision: 可进入红绿编码。** v2无剩余Critical/High设计阻断。这里仅确认设计闭合，不代表实现/测试/真实质量已通过；F-01/F-02的commit与回归证据继续在tracking中补齐，发布及默认开关仍依原计划的质量和收益结果决定。


## Step 3 Implementation Review — 2026-11-11

**Reviewed**: `models/local_model_queue.py`, `models/scheduled_chat_model.py`, model factories, typed-busy control/Generate propagation, Harness/Fast/API wiring, `tests/unit/test_local_model_queue.py`, `tests/e2e/test_local_model_admission.py`, and the installed LangChain/httpx/httpcore close paths. 本节为独立代码复核；未读取defender报告、未调用真实模型、未修改业务代码。两个独立探针均通过`uv run --frozen --no-sync python -c`执行，模型网络为httpx.MockTransport或纯fake。

### F-03 — Final Generate initially swallowed admission rejection (fixed during review)

- **id**: F-03
- **severity**: High — `critic.md` §2 High(a)；生成热路径的过载边界未闭合。
- **label**: issue (blocking, must-fix), resolved in working tree
- **location**: `agent/skills/generate/skill.py:317-319`与异步生成对应异常分支；`tests/e2e/test_local_model_admission.py:78-125`。
- **symptom**: Thinking控制步骤成功、仅最终生成入队被拒绝时，旧`except Exception`将ModelBusyError转换成普通FAILURE文本，Harness收不到busy，API没有generation_complete=false。
- **impact**: REQ-302的可重试busy终态在真实生成位置失效，普通文案被当作正常完成输出。
- **root_cause**: typed-busy传播只覆盖控制技能，漏掉最终Generate的两处通用异常捕获。
- **recommendation**: 两处先`except ModelBusyError: raise`，沿已存在的Harness公共边界归一。实现者已按此修复；不新增状态通道。
- **verification**: 已读取`validation/generation-busy-red.log`（真实Graph+router+mock网络，JSON/SSE两例失败）及`validation/admission-green-v2.log`（26 passed）；`test_actual_graph_generation_busy_is_terminal`断言生成仅被拒绝一次、不产生最终json_schema模型请求、外部metadata携带busy/incomplete。当前代码两处均已专门传播。
- **status**: verified-by-test-test_actual_graph_generation_busy_is_terminal（commit由tracking后补）

### F-04 — Sync coreference condensation still swallows busy before Rewrite retries

- **id**: F-04
- **severity**: High — `critic.md` §2 High(a)；属于已新增typed-busy传播的真实多轮同步路径，非假设性防御建议。
- **label**: issue (blocking, must-fix)
- **location**: `core/retrieval/query_transform.py:80-101,163-193`; `agent/skills/rewrite/skill.py:101-115`。
- **symptom**: 同步Rewrite携带conversation_history，问题为“那它需要多少天？”。fake `create_custom_llm().invoke`在condense阶段抛ModelBusyError后，`_llm_invoke`吞成None，`condense_query`回退原问题，随后Rewrite仍调用自己的模型。独立探针输出`calls=["condense_busy","rewrite_after_busy"], status="success"`。现有Rewrite行107的专用except收不到内部信号。
- **impact**: 本次请求已经被主动背压拒绝却继续另一模型调用，不满足REQ-302/v2明确的终止语义，队列等待/调用计数也不能反映一次终止请求。
- **root_cause**: typed-busy分支位于调用方，实际helper先经过两个通用异常降级层。
- **recommendation**: 最小修订`_llm_invoke`和`condense_query`，使本次内部ModelBusyError不进入None/原query回退，交给现有Rewrite/Harness处理。仅围绕已复现路径补传播及回归；不据此要求扩大所有可选评分或检索机制。
- **verification**: 在`tests/`固化同一多轮sync Rewrite场景：condense抛queue_full后断言专用信号到达Harness安全终态、rewrite模型调用次数为0；普通模型不可用异常仍保留原有query降级。无需真实模型。
- **status**: open

### Queue and Stream Conclusions

- **praise (non-blocking)**: sync Event与async Future共用同一个受线程锁保护的队列；超时/取消都撤销自己的ticket，grant与cancel竞争后也释放正确槽。未发现两个调用同时获得活动槽的可触发路径。
- **praise (non-blocking)**: 两个model factory都通过ScheduledChatOpenAI；四个SDK入口无可继承重入token。同步流使用closing，异步流直接包实际SDK层并使用aclosing，顺序为关闭传输后释放槽。
- **praise (non-blocking)**: API intent拒绝、Harness四入口、Fast三入口已有明确busy载体；两个outcome键在请求起点清旧值。public response将缺失confidence保持None/degraded。
- **独立取消探针通过**: MockTransport的Body在下一chunk处等待Event，取消消费Task；Body.aclose也等待Event以模拟真实异步关闭。关闭期间Task未结束且slot=1；允许关闭后transport_closed=true、slot=0，未提前放槽。
- **关闭语义限度**: 在已yield chunk之间直接调用public astream.aclose，若Body.aclose需要异步等待，public aclose可以先返回，内部清理仍持slot=1；允许transport关闭后释放。现有无await的Body.aclose回归只覆盖立即关闭。此处未复现永久泄漏或提前放槽，因此不升级为额外阻断、不要求拷贝SDK；不能把现有测试描述为所有异步关闭都在public aclose返回前完成。
- request级聚合queue/service/call计数已接线；逐次call_class、排队拒绝分母、真实混合收益仍按既有实验计划验证，本评审不将单元通过等同吞吐收益。

### Implementation Decision

当前Step 3代码仅有F-04这一项未闭合High；F-03已有红绿回归。F-04修复后可继续原计划Step 4与完整矩阵/真实有限对照。本结论不提前批准默认开启或发布；F-01的分段完成状态/历史持久化属于尚待完成的Step 4，不重复开同义发现。
