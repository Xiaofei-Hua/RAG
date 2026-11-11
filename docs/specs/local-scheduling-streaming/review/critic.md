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


## F-04 Implementation Closure — 2026-11-11

已复核`core/retrieval/query_transform.py`：`_llm_invoke`、`_allm_invoke`、`condense_query`均先传播ModelBusyError，普通Exception仍保留原有弱策略。`tests/unit/test_local_model_queue.py::test_query_transform_busy_propagates_without_fallback`覆盖sync/async/condense三种入口。

- 红证据：`validation/cleanup-red-v2.log`中三项均因未抛专用busy失败。
- 绿证据：`validation/step3-backend-v2.log`为1238 passed、6 skipped，另有5项CI环境代理相关失败；`validation/step3-ci-env-corrected.log`记录修正环境后的定向16 passed。不得把前一份日志改写成单次全绿。
- **F-04 status**: verified-by-test-test_query_transform_busy_propagates_without_fallback，后端相关回归通过；修复commit/最终矩阵说明由tracking归档。
- **Step 3 result**: 本critic已提出的实现High均已修复，无剩余已确认阻断。此处不提前替真实调度收益验收下结论。

## v3 Schema Admission and Full Answer Review — 2026-11-11

**Review target**: `design.md`新增v3（44–47行），`data/eval/local-stream-mechanism-v1/results.jsonl`全部16条回答，以及对应`model-http.jsonl`中的4组实际输入证据。未运行模型、未读其他reviewer报告。本节以v3作为本轮schema决策，先前v2的evidence→answer描述应在维护文档中更新为当前方案。

### Evidence Recheck

每个variant均为4题×2轮=8个样本；16次均各调用模型1次。全部8次原始首段发出时间P50：buffered 3.429313s，segmented 2.975852s，下降13.223%（按展示精度记13.2%）；未达到初始30%观察值。这是**原始首段发出时间**统计，其中分段有2/8首段未通过内容完整性复核，不能称为“8/8有效已检首段均取得的收益”。保留全部分母，不通过筛掉失败样本来美化时延。

| Round / Case | Buffered full answer | Segmented first release | Segmented full answer |
|-------------|----------------------|-------------------------|-----------------------|
| R1 / ih2_06 | 540/600分钟、8/5W及不能比较同负载均正确 | 记录比较、负载差异、不能外推均齐全 | 核心正确；后段重复限制，无新冲突 |
| R1 / dev_zero | 已测量的0值、0ms=0s、10分钟基准均正确 | 回答相同及零不等于缺测，核心齐全 | 核心正确；“但单位不同”略绕，未造成实质结论改变 |
| R1 / dev_calibration | Q2、正常连续使用、120日历日、首次启用确认及换探头后校准起算齐全 | 同上，首批完整 | 完整且未扩大资料范围 |
| R1 / dev_missing | 价格未提供；自交付起18个月保修 | 两个问题均完整回答 | 未编造价格或混淆42mm显示宽度 |
| R2 / ih2_06 | 记录比较与同负载未知均齐全 | **未通过**：只给记录条件下的比较，用户明确询问的“能否判断同负载优劣”被推迟到第二段 | 全篇补齐后正确；全篇正确不能替首段通过 |
| R2 / dev_zero | 记录零值与已测量结论正确 | 核心回答完整 | 核心结论正确；尾段把推论“记录的零值不等于缺测”写成证据明确引语，并扩成“没有产生可检测的偏差”，超出原文的记录措辞，详见下文 |
| R2 / dev_calibration | 正常连续使用条件虽在后段，但一次整体发布的全文具备 | **未通过**：漏“正常连续使用”限定 | **未通过**：全篇仍遗漏该限定；更换后先校准的动作也不如R1明确，不得以包含120和起算日期判为合格 |
| R2 / dev_missing | 价格未知与保修起算正确 | 两个问题均完整回答 | 完整，无实质退步 |

当前分段按本次内容检查为6/8首批核心完整；明确的全篇实质遗漏为R2校准。R2零值尾段并未改变“有测量且记录为零”的核心结论，但原输入只有“本次测量已完成”“该数值是本次测试的记录结果”，没有那条直接引语，也没有说明检测分辨率。后续全文复核应继续检查引用表述，优先保持“记录的偏差为零”，不要把推论包装成逐字来源。这里不因此新增模型判分或另一套实验。

全部8个segmented记录的token拼接、done.full_response及answer相同；这仅证明发布文本一致，不证明语义完整。全部outcome=complete描述的是流格式完成，也不能替代上述独立质量结果。

### v3 Design Decision

**结论：可进入红绿编码；新增Critical/High设计阻断为0。**

- **praise (non-blocking)**: 将conditions放到answer之前，并由程序把answer[0]+全部已验证conditions一次检查后发布，直接针对本轮“条件在后段出现”的已复现机制，保留单JSON、一次模型调用和独立回滚。相比只调整自然语言要求，更明确规定了已提取条件的发布时间。
- 条件数组必须完整闭合且通过原有结构/引用检查，再等首个answer对象完整；不得先发布结论、随后用另一token补条件。首批正文使用原有累计PII/来源检查，sync/non-stream与stream使用同一合成规则。已有chunk/半对象/非法ID/PII/partial红绿用例覆盖这一新顺序即可，不扩大测试矩阵。
- 该机制保证**已提取的conditions随首批一起交付**，不保证模型没有遗漏条件。R2校准的遗漏是否改善，仍按原定两轮对照与未暴露新题验证；不能因为conditions字段存在便计为语义通过。
- 条件前置可能增加首段等待并减少后续解释空间；维持已有输出预算，在同一机制实验中记录实际首批时间、完整率和全文质量即可。没有理由为了达到30%添加模型调用、丢条件或要求每个时延分位都优于baseline。
- 默认false合理。v3是否启用只在既定质量与实测收益完成后决定；v1本身有已确认内容失败，当前13.2%原始时间改善不足以支持启用v1。


## v3 Mechanism Results and Core Code Review — 2026-11-11

**Evidence**: `data/eval/local-stream-mechanism-v2/{results,model-http}.jsonl`（v3 schema的两轮试验，共16答）；逐条读取首块、所有后续块、完整baseline，以及HTTP捕获里的实际输入corpus。代码复核为本轮`core/segmented_generation.py`、`core/local_rag_generation.py`、Generate/Fast接线、GuardrailManager receipt与SkillContext。未运行真实模型，未读取其他reviewer意见。

### Full Answer Assessment

| Round / Case | Buffered full answer | Segmented first block / full answer |
|-------------|----------------------|------------------------------------|
| R1 / ih2_06 | 5W/10h与8W/9h记录比较、同负载未知均正确 | 首块已同时给比较、差异负载和不可外推；全篇同首块，关键条件完整 |
| R1 / dev_zero | 10分钟基准、0ms=0s、已测量而非缺测正确 | 同样完整；conditions重复单位/零值说明，增加文字但无实质错误 |
| R1 / dev_calibration | Q2、正常连续使用、120日历日、首次启用确认及更换后校准起算齐全 | 正常使用限定已恢复；两个起算点正确。更换后“该次校准”的指代稍紧，不构成改变起算点；未列出出厂/收货/入库排除项，但已明确正向起算定义，不因此判作漏条件 |
| R1 / dev_missing | 价格未提供、交付日起18个月保修正确 | 完整，没有把42mm显示宽度当作价格 |
| R2 / ih2_06 | 两个问题均明确回答且依据正确 | 首块包含各负载、没有其他负载数据、没有同负载对比数据；第二块才出现“无法判断”的直述句。首块表达较间接，但已呈现不可外推的关键未知信息，**不与v1缺少该限制等同**；全篇结论正确 |
| R2 / dev_zero | 记录零值、测量完成、单位换算正确 | 首块完整；未再出现v1的虚构直接引语或额外检测分辨率推断 |
| R2 / dev_calibration | 正常条件、120日历日、两个起算点和更换后先校准正确 | 首块全部具备；正常条件重复一次，未改变含义 |
| R2 / dev_missing | 价格未知、保修期限与起算正确 | 首块及全文完整，无新增事实 |

本轮8/8分段回答的核心事实与适用条件可接受，未发现相对于相应buffered或输入corpus的**明确实质退步**。R2比较首块“未提供同负载对比数据”已表达决定结论的未知项，不以是否出现某个固定短语机械判失败；仍建议在全文质量记录中保留它的表达不够直接。样本只覆盖4道已暴露开发题，不能替代尚未冻结的新题结论。

8个segmented样本的token拼接、done.full_response与保存到results的answer完全相同，均为一次模型调用，无格式截断。此事实与内容评审分开记录。

### Performance Assessment

- 全部8槽首块P50：buffered **3.262651s** → segmented **3.620234s**，慢 **10.96%**。
- 全部8槽总完成P50：buffered **3.262652s** → segmented **3.660661s**，慢 **12.20%**。
- 7/8分段答案只发布一个token块，只有R2比较还有一个后续块；本批没有实现有意义的提前交付收益。两轮每答仍各调用1次模型。
- 原始模型输出中的evidence文本为每答57–105字符（不含JSON/引用开销）；另有0–115字符conditions与89–142字符answer。大量相同事实被复述在多个字段，首块又必须等待conditions结束，因此增加了交付前的工作。
- **结论：本轮v3质量改善成立，但没有启用性能依据，默认应保持false。** 不把“支持分段”本身记为加速，也不把未通过的v1速度与v3质量拼接成一个通过结论。

### F-05 — Segmented non-streaming accepts a non-stop finish

- **id**: F-05
- **severity**: High — `critic.md` §2 High(a)，新分段生成热路径的完成状态与sync/async同义契约未闭合。
- **label**: issue (blocking, must-fix)
- **location**: `core/local_rag_generation.py:27-32,43-53`; 对照`core/segmented_generation.py:98-103`。
- **symptom**: 给两入口同一个完整且合法的segmented JSON，但finish_reason为None或tool_calls：纯函数探针两次均得到`nonstream_accepted=true`、`stream_complete=false`。JSON/非流式路径能将没有stop完成信号的生成记为完整，流式却正确拒绝。
- **impact**: 违反design明确的“完整schema且finish=stop”，并令相同生成结果因入口不同得到不同成功终态。
- **root_cause**: 新segmented非流式渲染复用了legacy complete_content，仅拒绝length/content_filter，没有执行本功能约定的正向stop要求。
- **recommendation**: 只在segmented分支补finish_reason==stop检查，legacy保持原语义；使用同一生成失败安全终态，不新增调用或输出修复。
- **verification**: 在现有segmented单元回归参数化None/tool_calls拒绝及stop接受；保持现有length回归。探针仅构造AIMessage并调用render_answer/ParagraphParser，不连接模型。
- **status**: open（已告知实现者并获确认进行窄修复，最终红绿证据由tracking补齐）

### Parser and Receipt Scope

- 完整conditions先解析验证，再与answer[0]合成一个首块；没有发现先泄露结论、后补条件的程序路径。半对象没有真实分隔符时不发布，非法引用及检查失败保留此前已检查正文并标不完整。
- CheckedParagraphs使用已检查前缀构造累计候选，检查后要求旧前缀保持不变；未检查的evidence不发布，PII检测在完整首块/后段上进行。
- before-hook把当前检查器放入新SkillContext；只有stream_answer返回的同一次最终正文被记入checked_output，after-hook仅在内容相等时跳过重复改写。from_agent_state不反序列化这两个字段，to_agent_state也不导出；未发现本次范围内的具体receipt绕过。
- 本审查未另立假设性的duplicate-key、配置漂移或跨进程防御工作项；现有27项API/unit通过由实现者报告，发布仍需既定完整矩阵与实际结果。

## v4 Coding Admission — 2026-11-11

已独立读取`design.md` v4（49–52行）：删去**模型输出**的evidence数组，保留完整kept输入证据、conditions→answer、首块原子合成、引用枚举与既有输出检查，维持单调用及预算。

**Decision: 可按v4进入红绿编码，新增Critical/High设计阻断为0。** F-05按已确认的窄修复同步处理，不需再展开设计循环。

- 该消融直接减少本轮实测的冗余输出工作，不删检索证据，不取消条件或现有输出检查，也不引入另一模型调用。
- 明确计算准备可能变弱是合理的成本说明；下一次仍用相同4题两轮对照判断数值/换算、条件与首块/全篇质量，质量保持后再按原计划冻结未暴露新题，无需新增机制或更大的实验矩阵。
- conditions完整闭合及首个answer完整后才检查/发布的规则保持；sync/non-stream同一渲染与stop完成判定，已有golden随schema做对应修订。
- v4尚无收益结果；继续默认false，保留v1/v3历史失败和退步数据。不能预先把删去evidence等同已取得速度或质量收益。


## v4 Full Answer Review and v5 Admission — 2026-11-11

**Reviewed**: `data/eval/local-stream-mechanism-v3/{results,model-http}.jsonl`全部16答及实际输入corpus；`design.md` v5（54–59行，含rewrite_count补充）。未调用真实模型，未读取其他reviewer报告。

### v4 Quality Recheck

| Round / Case | Buffered full answer | Segmented first block and full answer |
|-------------|----------------------|--------------------------------------|
| R1 / ih2_06 | 芦序600分钟大于赤砚540分钟，并明确不同负载不可外推 | **已知不完整**：列出8W/9h、5W/10h并答出不能判断同负载优劣，但没有直接回答谁在记录中更长；全文仅此块，未在后续补足 |
| R1 / dev_zero | 0ms=0s、已测量而非缺测，正确 | 明确换算并回答偏差相同、零是测量结果，完整 |
| R1 / dev_calibration | 正常连续使用、Q2、120日历日、两个起算点及换探头先校准，正确 | 首块全部具备，还明确不从出厂/收货/入库起算；无实质遗漏 |
| R1 / dev_missing | 价格未知、自交付起18个月保修，正确 | 两问完整，无虚构价格或单位混淆 |
| R2 / ih2_06 | 记录时长比较及同负载未知，正确 | 明确10h>9h且仅属各自负载记录，不能外推同负载优劣，完整 |
| R2 / dev_zero | 零值与测量完成，正确 | 明确0s=0ms及相同偏差，零不等于缺测，完整 |
| R2 / dev_calibration | 正常条件、120日历日、首次启用确认及更换校准起算，正确 | 首块全部具备，两个周期未混淆，完整 |
| R2 / dev_missing | 价格未知、保修期限与起点，正确 | 完整且简洁，没有额外未经支持的事实 |

除设计已记录的R1比较回答不够完整外，未发现额外实质问题；v4分段为7/8核心回答完整。所有引用均指向实际输入来源。8个分段回答均只有一个token块，token拼接=done.full_response=results.answer；每答仍仅一次模型调用。

### v4 Measured Tradeoff

全部8槽原始首块P50为3.364225s→1.794193s，下降**46.668%**；总完成P50为3.364226s→1.831219s，下降**45.568%**。该收益主要对应更少的生成工作与更短的最终回答，不能描述成大量后文在首块之后继续输出。由于包含1个未完整回答的比较样本，既不能宣称v4全部质量通过，也不能把46.7%直接当作v5分流后的最终收益。

### v5 Decision

**可进入红绿编码，无剩余Critical/High设计准入阻断。** 采取有限适用范围，比继续要求同一精简schema对所有题型稳定更符合已有证据。

- 比较/等值/差值/倍数命中本地中英文规则时，保留已合格bounded完整生成；其它问题采用conditions→answer。选路发生在本次生成之前，不试错后重生，因此不增加模型调用。
- Thinking现有Generate读取最后一条HumanMessage，而Rewrite会追加改写问题。已提出并复核design第59行的补充：`rewrite_count>0`一律保守使用完整生成，避免原比较词被改写掉后走入精简路径。sync generation_chain与async Generate传相同已有参数，**不新增状态键或分类模型**；该接线问题已在设计内闭合。
- 同一helper需要在每次请求拿到question/rewrite_count后作决定，实际schema回归应覆盖中文比较、英文比较、等值/倍数及改写丢词；不把选择结果缓存在共享模型或无问题参数的chain中。沿用设计中的两类定向红绿即可，无需扩展实验矩阵。
- 本地词匹配是有限规则覆盖，不是完整自然语言语义分类：保守地多送完整路径只降低加速覆盖，漏匹配则仍可能暴露精简路径的质量边界。最终既定新留出同时核对实际选路与全文答案，不要求规则穷尽所有表达。
- 这4道开发题里，明确比较与等值题均应保留完整路径，校准及缺失价格题可用精简路径；最终需报告实际分流数量、全部题目分母、整体/模式分位数及质量。不能把比较题从质量分母删除，也不能声称比较题加速。
- 默认false保持到原定最终组合验证完成；v1/v3/v4原记录保留。未要求继续优化所有题型，也未提出新机制。

### F-05 Update

已复核`core/local_rag_generation.py:47-48`仅在segmented分支严格检查finish_reason==stop，legacy未改；`test_nonstream_requires_same_stop_contract`包含None/tool_calls/length/content_filter回归。`validation/v4-unit-e2e.log`记录23 passed，F-05代码缺口已修复，状态更新为verified-by-test-test_nonstream_requires_same_stop_contract。该日志仍带测试进程结束时的SQLite ResourceWarning，不应在最终报告中称其输出完全无警告；既定最终矩阵负责如实归档其处理情况。


## Final v5 API and Step 3 Mixed Queue Review — 2026-11-11

**Scope**: 独立逐条读取`data/eval/local-adaptive-api-{baseline,candidate}/results.jsonl`全部32答，以及`data/eval/local-queue-{off,fair}-v1/results.jsonl`全部32答的首块、全文和实际来源；核对各组`model-http.jsonl`的真实schema、生成完成原因和调用数量。没有运行模型、读取defender报告或改动冻结的prompt/词表；本节不包含尚待执行的holdout-v5。

### v5 API Quality and Actual Routing

baseline与candidate均启用fair调度，差异为分段开关false/true；每组两模式×两轮×4题共16槽，未删除比较题或失败槽。

| Case | Baseline, four answers | Candidate, four answers | Actual candidate schema |
|------|-----------------------|-------------------------|-------------------------|
| ih2_06 | 均明确芦序600分钟/10小时长于赤砚540分钟/9小时，且不能外推同负载优劣 | 同样完整；5W/8W对应正确，没有把记录比较写成同负载优劣 | basis→conditions→conclusion，4/4 |
| dev_zero | 均回答0ms=0s、两者偏差相同，零值来自已完成测量而非缺测 | 同样完整，无未支持的非零偏差或缺测推断 | basis→conditions→conclusion，4/4 |
| dev_calibration | 均保留Q2、正常连续使用、120日历日、首次投入使用确认起算及换探头先校准后重算 | 首块均包含这些条件，且明确排除出厂/收货/入库起算；没有省略正常使用限定 | conditions→answer，4/4 |
| dev_missing | 均说明价格未提供、保修18个月且从交付起算 | 同样完整，没有将42mm显示宽度当作价格 | conditions→answer，4/4 |

**本组结论**：baseline 16/16、candidate 16/16核心问题与关键限定完整；未发现candidate相对对应baseline或输入证据的实质质量退步。引用均指向本次实际输入来源，没有新增错误来源或不受来源支持的关键事实。少量措辞重复或语病不改变结论，不作为新阻断。

实际调用而非仅配置显示：baseline 16次最终生成均为完整schema；candidate为8次完整、8次精简，覆盖率8/16。Fast每请求1次模型调用，Thinking每请求3次控制+1次最终生成；两组各40次调用（24 control +16 generation），未增加生成重试或在线judge。每次最终生成都是合法完整JSON且finish=stop。

这32答均只发出一个token块，首块即全文；因此不能据此宣称在这些短答案上观察到了多段持续交付。每答token拼接=done.full_response=results.answer，HTTP200、generation_complete=true、status=complete、refused=false各16/16。首块包括完整回答中的后续说明段，不能把“第一自然段”误作本实验的首个发布块。

### Step 3 Mixed Queue Quality and Denominators

off/fair两组均关闭分段，最终生成均为basis→conditions→conclusion；每组为2 Fast+2 Thinking同时请求×2题×2轮，共16槽。已按round/mode/case/slot核对，未用完成顺序冒充配对顺序。

| Group | HTTP / generation complete | Comparison fully answers both questions | Calibration includes all key conditions | Overall semantic completeness |
|-------|----------------------------|-----------------------------------------|-----------------------------------------|-------------------------------|
| off | 16/16 | 6/8 | 8/8 | 14/16 |
| fair | 16/16 | 8/8 | 6/8 | 14/16 |

必须保留的四个不完整样本：

| Evidence row | Concrete omission | Assessment |
|--------------|-------------------|------------|
| off `results.jsonl:4`, R1/thinking/ih2_06/slot=3 | 首块及全文列540与600分钟，说明不能判断同负载优劣，但未直接答出按记录谁更长 | 与v4既定评审标准相同，算比较任务不完整；数值、引用和不可外推限定本身正确 |
| off `results.jsonl:10`, R2/fast/ih2_06/slot=0 | 列芦序10小时、赤砚9小时及不能判断同负载，全文未明确谁在记录中更长 | 同样算任务不完整，不因读者可自行比较而改判通过 |
| fair `results.jsonl:5`, R1/fast/dev_calibration/slot=0 | 全文漏“正常连续使用”适用条件 | HTTP捕获index=13的输入包含该条件，输出conditions=[]且basis/conclusion也没有该限定；不是渲染时丢字 |
| fair `results.jsonl:14`, R2/fast/dev_calibration/slot=2 | 同样全文漏“正常连续使用” | HTTP捕获index=34亦为有该输入、conditions=[]且全文省略；周期和两个起算点其余正确 |

其它28个混合请求的首块和全文核心事实、结论、适用条件与引用可接受。所有32答均一个token块，token拼接=done.full_response=results.answer；off/fair各40次模型调用（24 control +16 generation），全部最终生成finish=stop。没有HTTP失败、busy、截断、空回答或未完成槽，**技术完成分母16/16不能替代语义通过14/16**；全部16槽仍保留在延迟和完成率统计中。

调度对照未观察到总体语义完整率下降，但错误分布发生变化：fair比较完整，两个Fast校准回答漏条件。不能据这小批非逐token确定的生成样本，把条件遗漏因果归到队列实现，也不能宣称队列提高质量或答案质量完全不变。这两例暴露的是完整bounded生成也不能保证自由文本条件提取完备；保留原文与分母，并在最终结果中如实陈述即可，不据此新建通用语义检测、二次修复或扩展实验矩阵。

### Decision

**本轮未识别新增Critical/High实现阻断，可继续既定冻结留出和最终交付验证；本节不是提前批准默认启用。** v5实际分流及开发题质量通过。Step 3对照的2/16与2/16语义不完整须在最终实验说明中披露，不能写“全部回答质量通过”。最终默认值仍依照已计划的留出与实际收益裁决，不更改冻结prompt/词表，不删失败样本。


## Frozen v5 Holdout Review and Default Recommendation — 2026-11-11

**Evidence**: 已独立阅读`validation/holdout-v5.json`协议、`data/eval/local-adaptive-holdout-{baseline,candidate}/results.jsonl`全部16槽及`model-http.jsonl`实际请求/响应。12个生成答的每个发布块和全文均已审阅，另4个弱检索终态单独核对。输入包含完整原始规则与notes，未将协议的manual_required或答案推导当模型输入。本评审未运行模型、改prompt/词表或阅读其他reviewer的结论。上一节混合off/fair全部32答的审阅已完成，无待补抽样。

### Accounting and Routing

| Item | Baseline | Candidate |
|------|----------|-----------|
| All request slots | 8 | 8 |
| Completed generation / all slots | 6/8 | 6/8 |
| Fast flow weak-retrieval terminal | 2/8 | 2/8 |
| Model calls | 18 = 12 control + 6 generation | 18 = 12 control + 6 generation |
| Actual final schema | 6 complete | 2 complete + 4 compact |
| Delivered body blocks | 全8槽各1块 | 7槽各1块，R1 Thinking scanner为2块 |

两个Fast flow槽在两组中都没有进入生成（model_start=model_end），返回相同安全资料不足正文，metadata为status=unavailable、generation_complete=false、reason=retrieval_terminal、confidence=None、confidence_degraded=true、retryable=true。HTTP均200不能算成功回答；失败/未完成分母仍为2/8，不能删除这两槽再报告100%完成。已有检索终态的存在也意味着本留出没有验证Fast对新比较题的生成质量，不能把Thinking的通过扩称到两模式均通过。该限制两组相同，未显示分流造成新增拒答。

实际精简覆盖为全部槽4/8，或已进入生成的4/6；这两个口径须同时说清。每次最终生成都是合法完整JSON且finish=stop；两组所有槽token拼接=done.full_response=results.answer。比较题仍为完整schema，scanner为精简schema，没有额外生成、重试或在线judge。完成状态只证明生成协议结束，不能代替下述语义评审。

### Complete Answers and First Deliveries

- **Thinking flow，两轮两组共4答**：数值换算、记录比较与不同工况不可外推均正确。baseline统一到0.25L/s与0.23L/s，符合协议明确允许的等价单位；不能因为没有逐字写15L/min与13.8L/min而判失败。candidate给出15L/min与13.8L/min，明确苔弦更大；两组均保留液体甲/27°C与液体乙/17°C及同工况未知。每答首块即全文，未发现实质退步。

| Scanner pair | Baseline | Candidate first block and full answer |
|--------------|----------|--------------------------------------|
| R1 Fast | 操作范围、初始起算、37有效小时/排除待机、失败停机、更换后通过才重置、未知室外规则/费用均明确；但没有给出指定参考页、序列号、日期/结果/失败记录等请求中的具体准备记录步骤 | 范围、首次起算、时长、失败处理与未知费用/环境保留。**更换后的周期重置未明确**：fresh 37-hour interval只写在失败后重检通过的条件句内；后续更换段仅要求重新检查，没有说明成功更换检查后即重置。全文仅此块。准备记录步骤同样缺失 |
| R1 Thinking | 关键规则和具体准备/记录步骤较齐全，初次/周期检查目的解释较简略 | 两块合读给出实际准备、序列号、日期/结果、保留失败记录及追踪目的，关键规则可接受。首块“a fresh 37-hour interval begins only after a check passes”是概括表达，结合首次通过后投用与更换后重新检查已表达起算条件；第二块把首次起算写得更具体，不据缺少固定“not delivery”字样判首块失败 |
| R2 Fast | 明确更换后检查通过才开始新的37小时周期；其余关键条件正确。仍未充分展开准备/记录walkthrough | 与R1 Fast相同，新的周期只在失败重检语境出现，更换后的成功检查重置规则没有明确给出；其余关键条件正确。没有后续解释块补足，也未展开实际准备/记录步骤 |
| R2 Thinking | 有指定参考页准备、设备序列号、日期/通过失败记录、保留失败记录，以及旧头结果不适用于新头的理由；核心规则正确 | 核心规则、两个起算点、失败处理和未知边界齐全；但全文缩成一个规则段，**没有提供所要求的实际walkthrough**：漏指定参考页准备，记录只提序列号/日期/结果，未展开失败记录保留与追踪用途，也省略更换为何需新检查的说明。相对baseline是请求中操作说明内容的减少，而非单纯改写措辞 |

candidate R1/R2 Fast的具体定位为`results.jsonl:2,6`，HTTP捕获index=1,10。完整输入明确包含“After replacing the scanning head ... Begin a fresh 37-operating-hour interval only when that check passes”，候选输出未在更换步骤交代该起算关系；对应baseline直接写出了这一关系。其余语句不足以清楚区分“更换检查一次通过”与“检查失败后重检通过”两种起算情形，不能按条件完整通过。

candidate R2 Thinking定位为`results.jsonl:8`、HTTP index=18。它确实保留了操作规则，不能误报为数值或安全停机错误；问题是用户另行要求的practical walkthrough和解释被明显压缩。反过来，baseline Fast的同类说明不足以及baseline Thinking对部分目的解释的简略也应保留，不能把baseline当完美金标。协议的全题要求没有在所有样本满足，因此两组均不能宣称“6/6完整满足所有要求”。

所有candidate关键引用均来自实际提供的相关文件；未发现新增数值错误、虚构价格、室外操作规则或错误停止条件。正常同义表达、概括句及重复不算失败。本次拒绝默认启用的依据是已请求的内容和起算关系减少，不是要求自由文本形式化或逐字匹配。

### Benefit and Decision

保留全部8槽的首块P50为7.483s→4.872s；仅6个完成生成槽为8.638s→5.670s。候选有真实速度收益，但含上述不完整说明，不能把速度下降作为质量已通过的证据。4个精简样本只有1个发出第二块，大部分收益仍是减少生成内容，并非所有长说明都实现了完整首段后持续交付。

**Step 4建议：保持默认false、允许显式启用，以当前证据完成交付，不继续用这批留出调prompt/词表。** 开发题的质量通过不能覆盖本次新操作说明上的退步。无需新增通用语义检测、额外模型调用、二次修复或扩大实验；现有实现、单调用收益、适用边界与历史失败可以完整归档。若未来再针对这些问题修改策略，这批题即转为开发题，不能再次宣称独立留出。

**Step 3建议：质量方面不新增阻断，最终默认启用可独立于Step 4裁决。** 已审混合off/fair均14/16语义完整、16/16技术完成，未见总体语义完整率下降，但不能宣称所有回答质量不变。是否默认fair还需结合当前执行中的真实容量、取消清理和性能结果；本节不提前把尚未收到的探针结果写为通过。


## Final Implementation Review and Step 3 Default — 2026-11-11

**Scope**: 当前工作树的`core/fast_mode.py`、`core/local_rag_generation.py`、`core/segmented_generation.py`、Generate、GuardrailManager、SkillContext、chat API/history、`web/src/stores/chat.ts`与`ChatView.vue`；同时复核已实现的queue/SDK包装、容量及live-cancel探针与结果。仅报告可触发的Critical/High实现缺陷；未改业务代码、未运行真实模型。

**Findings: 新增Critical 0，High 0。** 本结论针对已读代码和现有证据，不将Step 4留出质量边界改写为通过。

### Admission and Cancellation Evidence

- `data/eval/local-queue-capacity-v2/results.json`：真实SDK流占用活动槽后，10个新调用产生8个等待和2个queue_full；取消8个等待后pending=0，未增加网络模型调用。随后等待超时为30.030430s，reason=queue_timeout，仍只有原先1个模型调用。关闭活动流释放耗时0.000687s，后续OK调用0.130689s；最终实际2 calls、active=0、pending=0。
- 该容量探针是在真实响应首chunk后**主动保留流及lease**，用于验证应用准入和超时。它不证明GPU连续计算了30秒，也不应报告为30秒GPU饱和试验。v1探针同步问题及失败日志保留，最终依据为v2。
- `data/eval/local-live-cancel-v1/results.json`：真实生成收到首个非空内容“整理”后，调用公开SDK流的aclose，直到槽释放为0.000543s；紧接的OK请求0.153754s。总2 calls、active=0、pending=0，未出现取消后占槽不退或额外调用。
- 真实探针覆盖SDK流关闭；先前确定性回归覆盖等待取消/授予竞争、sync/async共享槽、传输关闭顺序与typed busy公共边界。它们与UI AbortController/取消异常传播的代码审查共同构成本轮证据，不能声称真实探针本身跑过浏览器断网全过程。

### Code Assessment

| Boundary | Review conclusion |
|----------|-------------------|
| Shared model admission | sync/async及四SDK入口使用同一thread-safe队列，无可继承重入凭据；槽在内部SDK流关闭之后释放。busy不进入控制/改写/生成重试，既有F-03/F-04修复仍在 |
| First checked paragraph | conditions完整解析、引用验证后才与answer[0]原子合成；半对象/未闭合分隔符不发布。每个累计候选经过现有检查，拒绝改写已发布前缀；异常只追加固定未完成文案 |
| Completion and sync parity | 精简非流式必须finish=stop，流式也检查stop和完整schema。F-05修复只在新分支；比较或rewrite_count>0统一保留完整生成，无二次模型修复 |
| Checker receipt | 检查器/checked_output只存在于本次新SkillContext；不从state载入、不导出到state。before-hook注入当前检查器，after-hook只跳过完全相同已检查正文；未发现可触发的检查绕过 |
| Graph/API/history | Generate整键写generation_outcome，入口清旧值；Fast提供同义状态。API显式传播metadata、保存最终AIMessage并在历史读取；输出检查失败改为未完成，公共confidence=None。general fallback清掉原生成失败状态，避免成功通用回答继承旧失败 |
| Partial/cancel UI | done中的未完成状态与历史metadata可见；流结束无done、SSE错误、AbortError均保留现有正文。停止操作abort请求；取消异常不进入生成成功保存路径。这里“保留正文”指当前显示内容，不宣称用户取消后的未保存文本在重开历史仍存在 |

`adaptive-green.log`已实读44 passed，`fallback-state-green.log`为10 passed；`stop-contract-red.log`是None/tool_calls两项真实失败、原length/content_filter两项通过，修复后保留四参数回归。`full-ui.log`已记录23 passed、1 skipped。旧`full-backend-v2.log`的1个fallback失败不能抹掉或称该次全绿；实现者修复后的定向绿和最终全矩阵分别归档。此评审不代替尚待最终确认的完整后端/coverage命令退出状态，也不新增额外验证门禁。

### Step 3 Default Decision

**建议在现有本地bounded/qwen3.5:9b匹配范围内将LOCAL_LLM_SCHEDULER默认设为fair，保留off回滚；LOCAL_RAG_SEGMENTED默认保持false。** 有界等待、满载明确拒绝、超时不调用模型、取消释放及同步异步统一准入均有直接证据，适合16GB单GPU部署。

收益必须准确描述为准入和背压控制，不是模型算力提升。混合对照保留各16槽，完成时延整体P50为11.809s→12.072s，P95为18.946s→18.298s；Fast P50 7.453s→7.378s、P95 9.398s→9.662s，Thinking P50 16.330s→16.635s、P95 19.018s→18.886s。小样本中分位数有升有降，批次总耗时73.895s→72.686s，不支持稳定吞吐提高或每种请求均加速的宣传。

质量分母仍采用上一节结论：off/fair各14/16语义完整、16/16技术完成，具体遗漏原文保留。队列默认建议不依赖Step 4默认开启，也不依赖把这些遗漏改判通过。完整矩阵完成后可以按已授权范围交付当前两步，无需继续优化或追加新的模型实验。


## Final Matrix Closure — 2026-11-11

已按收尾范围独立核验完成日志及最后两组运行记录，没有新增实验或扩大代码审查范围。

- `validation/final-backend.log`明确记录**1274 passed, 6 skipped, 3 warnings**，耗时63.78s；同份日志coverage TOTAL为**74%**。本次完整矩阵已通过，替代上一节“最终后端退出结果待确认”的状态；旧失败记录仍保留。
- `validation/full-ui.log`为**23 passed, 1 skipped**，其中已包含分段partial和stop两项。随后`validation/ui-final.log`为分段3项全部通过，新增的是history保留未完成提示；因此合计唯一通过用例是**24 passed、1 skipped**，不是23+3重复计数。
- `data/eval/local-final-default/results.jsonl`默认配置Fast/Thinking各1槽，**2/2 HTTP200且generation_complete=true、status=complete**，共5次模型调用。
- `data/eval/local-final-combined/results.jsonl`为fair+segmented显式启用的混合收尾验证，Fast/Thinking×比较/校准共4槽，**4/4 HTTP200且generation_complete=true、status=complete**，共10次模型调用。该小批完成结果不改判此前独立留出的长说明质量边界，也不将显式组合开关当作新的默认设置。

**Final recommendation unchanged: scheduler默认fair，segmented默认false。** 既定矩阵已收口，当前评审无未解决的Critical/High实现阻断，可按已授权范围打包交付。分段仍保留为可选功能，已有收益、质量遗漏和失败分母按前文如实保留。
