# Defender Review — Local Scheduling and Streaming

**Review date:** 2026-11-11  
**Scope:** `requirements.md`、`design.md` v1、`tasks.md` 与基线 `44d2748` 的相关实现。  
**Independence:** 本报告独立核对设计和代码，未读取本轮 critic 报告；下列 `D-*` 是独立发现，并非对未知 critic 结论的背书。未调用真实模型，未冻结或消费新留出题。

## Verdict

方向合理。现有合格基线已经实现一次最终生成、零在线 judge；本次应验证短控制调用等待、取消背压和已检查首段的实际收益，不重开既有模型选型，也不要求所有延迟和吞吐指标同时更优。

设计具备可实现路径，但 v2 需明确两处 High 接线契约：忙碌终态不得被旧控制步骤重试吞掉；生成状态必须穿过 Graph 到达 JSON/SSE、保存和评测消费者。它们是本次新增行为的直接依赖，不是独立防御性扩建。另建议删除 SDK 当前不需要的可继承重入令牌。没有发现需要新增模型调用、跨进程调度或通用一致性框架的理由。

## Decision Table

| ID | Severity | Decision | Evidence and reasoning | Required design revision |
|---|---|---|---|---|
| D-01 | High | accepted | `core/intent/classifier.py:172`、`:221` 捕获任意异常后重试；`agent/skills/grade/skill.py:230`、`:254` 重试后默认 relevant；`agent/skills/rewrite/skill.py:133`、`:209` 重试或保留原问题继续。调度器本身不重试不足以保证请求及时忙碌终止。 | Step 3 写明 busy/timeout 的请求级终态传播，禁止后续实际模型调用；补真实 Graph/API 的拒绝接线测试。 |
| D-02 | High | accepted | `agent/skills/base.py:121` 的 `to_state_update()` 不输出 `status`/`metadata`；`api/routers/chat.py:1281` 当前只读 confidence/refused，`:1347` 保存普通 AIMessage。只写 PARTIAL 会在节点边界丢失不完整状态。 | Step 4 明确终态载体和 JSON/SSE/保存/评测消费路径；Fast 返回同义状态；取消不进入成功保存。 |
| D-03 | Medium | accepted | 锁定 `langchain-openai==1.1.13`（`uv.lock:2187`）的 `_generate`/`_agenerate` 直接调 SDK，四入口各持槽不需要重入绕过。可继承 contextvar 令牌会随消费任务创建的子任务传播。 | 删除 v1 Step 3 的可继承重入令牌；保留请求统计 contextvar；以混合同步/异步和流关闭测试证明单槽。 |
| D-04 | Medium | accepted | v1 `design.md:17` 保留 2048 总输出预算，但仅把 evidence 描述为“简短”。首段要等 evidence 完成，证据冗长会抵消首段收益或耗尽回答预算。 | 在 prompt 明确 evidence 只摘与答案直接相关的最少事实/必要换算；机制实验记录 evidence 长度、有效首段时间及截断，不增设泛化门禁。 |

`accepted` 在此表示需要写入设计并实现验证；不等于代码问题已 closed。High 在追踪表中完成设计修订后方可进入实现阶段，代码闭环另附红绿和回归证据。

## D-01 — Busy State Must Survive Existing Fallbacks

- **Fact:** v1 `design.md:13` 承诺调度器“不自动重试”，但基线的分类、grade、rewrite 自身有宽异常重试；分类失败还会产生 `confidence=0.0` 并继续 RAG（`classifier.py:181`、`:232`）。
- **Trigger:** 请求进入已满队列，或控制调用在 30 秒后等待超时。若只抛普通异常，外层重试重新入队；grade 重试耗尽还可能继续生成。用户得到多轮等待或普通答案，队列拒绝不能成为明确可重试终态。
- **Impact:** 直接违背 REQ-302 的背压和不可用语义；同时使拒绝/实际调用分母、等待上限失真。
- **Cost and scope:** 中低成本，本次新调度异常的必要接线。无需改写全部历史失败策略。
- **Recommendation:** 区分调度拒绝与普通模型错误，给本次请求保留明确 busy/timeout 原因；一旦发生，该请求不再产生实际模型调用。可以用现有请求级载体和窄分支实现，不要求新增跨节点消息或新的调度服务。API 输出明确 `retryable` 与未完成状态，质量/置信度不可用保持 `None/degraded`。
- **Verification:** 在真实 router + Graph 的 mock 网络测试中让控制调用被拒绝，断言不会继续实际模型请求、状态到达 JSON/SSE，且请求结束释放全部等待项。仅 scheduler 单元测试不足以覆盖本问题。
- **Status:** accepted; design revision pending.

## D-02 — Partial Is an End-to-End Result Contract

- **Fact:** `SkillResult.status` 和 `metadata` 当前用于 trace，但 `to_state_update()` 仅返回 messages/state_updates。API 会重建 metadata；Fast 流入口 `api/routers/chat.py:1074` 也只累计 token/来源。后续若检查器改写最终内容，Thinking `chat.py:1294` 能静默替换已发正文；前端 `web/src/stores/chat.ts:280` 用 done 覆盖正文、`:298` 用错误替换正文。
- **Trigger:** 第一完整段已检查并发布，第二段随后 length、半 JSON、检查失败或模型流异常。生成节点返回 PARTIAL，但路由若沿旧逻辑保存并捕获 inference，界面和评测仍可能视为成功。
- **Impact:** REQ-402 的核心行为失败；已显示正文可被撤换，或者部分答案伪装为最终答案。
- **Cost and scope:** 中等成本，直接属于分段发布的结果契约。无需新增持久化数据库或广泛历史迁移。
- **Recommendation:** 明确最终响应状态由哪里生成、跨 Graph 如何携带、API 如何读取。可沿既有最终 `AIMessage.additional_kwargs` 的 confidence/refused 返回通道携带 `generation_complete`、终态和可重试标记，它是最终响应元数据，不是把检索证据或调度对象塞进 messages。FastModeResult/done 使用同义字段；保存时保留已检查正文和不完整信息，评测保存状态以排除正常成功口径。若不使用该载体，应在设计中选定等价明确路径。
- **Append-only requirement:** 已发布文本是不可改写前缀。后段失败只追加固定不完整提示，done 和已保存正文采用该值。路由和前端不通过最终替换来“修正”已发 token。取消传播到模型流并停止成功保存；可中断的异步调用关闭后释放槽，同步调用未实际结束时不能提前宣称释放 GPU 工作。
- **Verification:** 真实 Graph + 当前 GuardrailManager 配置的进程内 E2E，第一段发布后分别注入 length、检查异常、ESCALATE、取消，检查不可撤换的正文、终态及保存行为；Playwright 检查已显示正文保留和未完成提示。
- **Status:** accepted; design revision pending.

## Supported Design Decisions

1. **One generation with evidence first:** 现有 `GroundedAnswer` 在 `core/local_rag_generation.py:20` 先生成 basis/conditions/conclusion，并在 `:37` 重排结论。改为内部 evidence → answer 数组能保留必要事实整理，同时让模型在首个 answer 对象中直接形成完整结论。首段必须回答问题，包含会改变结论的条件；证据摘录和拒答均不计有效首段。该方向需要真实质量验证，不能由 schema 合法推断语义合格。
2. **Use the actual output checker:** `GuardrailManager.__init__` 接受自定义配置（`agent/guardrails/manager.py:25`），当前 Fast 的 `finalize_answer` 会新建默认 manager（`core/local_rag_generation.py:104`）。Thinking 通过 before-hook 向当前 SkillContext 注入实际检查器可复用真实配置。`orchestrator.py:473`/`:496` 和 `:508`/`:538` 对同一 context 调用前后钩子，request-local receipt 方案可行；无检查器时回到完整缓冲符合安全降级。Fast 应明确复用其实际配置的检查组件。
3. **Check cumulative paragraphs before emission:** 当前安全提示可能修改输出（`output_guardrails.py:20`），PII 在完整文本上检测（`:261`）。对累计已检查正文加候选段检查、只放行追加后缀，能复用现有行为而不新增在线 judge。平台免责声明可保留在首段后面；不值得为排版而撤换已交付文本。检查异常、BLOCK/ESCALATE 后不暴露候选段是必要边界。
4. **Single shared slot:** 本机引擎已为 parallel=1，应用队列的价值是等待次序、公平性、背压和取消，不是增加 GPU 算力。活动生成不可抢占，短调用优先仅影响下一次授予。以实际 max_tokens 分类、两次短调用后放行生成、年龄提升和全部请求分母可以解释收益与代价。SDK 流必须显式关闭后再释放租约，不能只依靠外层 generator 最终被回收。
5. **Independent rollout:** 调度和分段各保留开关，并分别消融和组合复核，可避免把 schema 变化收益误记为调度收益。有限样本的 P95 是观察值；若吞吐未改善，可据取消/等待上限的实测收益单独决策，不能宣称推理加速。无需追加哈希校验、签名维护或普遍一致性对账工作。

## Honest Limits and Next Review

- 当前只审设计和接入事实，不声称实现已正确或真实收益已达标。
- 自由文本结论完整性、条件覆盖和后段不矛盾不能由 JSON 语法、合法引用 ID 或静态检查证明；按设计分别独立阅读首段和全文，保留全部失败记录。
- 新留出题暂未冻结。待实现和 prompt 稳定后独立冻结至少两道未暴露的多条件问题，先固定问题/参考判断再运行；若据失败调参，该题须转开发集，不能继续冒称留出。
- 共享槽范围是单进程、已合格本地 endpoint。同步活跃网络调用通常不能被另一线程强制取消；其超时/实际关闭前须继续占槽。部署说明应如实写明，不扩大为跨 worker 调度工程。
- 本轮没有须转单的范围外发现；不建立基于假设风险的 backlog。


## Design v2 Admission — 2026-11-11

独立复核 `design.md` v2 第 37–42 行后，D-01 至 D-04 的设计修订已经落实，准入实现和红绿验证。未读取本轮 critic 报告，未调用真实模型，也未提前冻结新题。此结论仅关闭设计阻断，不能替代代码、公共接口和真实质量验收。

| ID | Design disposition | Verified closure | Remaining implementation evidence |
|---|---|---|---|
| D-01 | accepted; design resolved | `design.md:39` 为 ModelBusyError 指定类型化 queue_full/queue_timeout，四个控制步骤及 timed wrapper 均不重试、不落到 0 分 fallback；API、Fast、Harness 各执行边界明确转换终态。Harness 独有 model_queue_outcome 且每请求清空，取消独立传播。 | 饱和控制步骤的真实 Graph/API mock 网络红绿，确认终态传播、无后续实际模型调用及等待项释放。 |
| D-02 | accepted; design resolved | `design.md:38` 采用 Generate 独有 generation_outcome 整键，所有终态覆盖写；Graph 通信严格走 shared_state，最终 AIMessage 字段只用于保存。Fast、JSON/SSE、历史及 capture 明确读取同义状态，保留 v2 `:19`–`:21` 的只追加协议。该载体比 v1 报告的可选消息返回通道更直接遵循仓库状态契约。 | 首段后失败及取消的 E2E、持久化/重开历史状态、前端保留正文与未完成提示；不得只凭 SkillStatus 测试通过。 |
| D-03 | accepted; design resolved | `design.md:12`、`:40` 删除可继承重入令牌，四个 SDK 入口独立持槽至关闭，仅请求统计使用 contextvar。 | 混合 sync/async、流 close/异常和取消授予竞争的单槽验证。 |
| D-04 | accepted; design resolved | `design.md:41` 明确最少决定事实、必要换算及限定，并记录 evidence 长度、实际生成 token 和截断；不以缩短首段为由漏掉条件。 | 两轮机制对照与稳定后独立新留出，分别审首段和全文。 |

本轮没有剩余 Critical/High 设计阻断；保持开关初始关闭，是否默认启用由后续实测收益和语义质量决定。tracking 中可标记设计已解决，代码闭环仍待修复 commit、验证和回归证据。


## Step 3 Implementation Review — 2026-11-11

**Scope:** 当前工作树的 `models/local_model_queue.py`、`models/scheduled_chat_model.py`、typed busy 传播、Harness/API/Fast 接线及新增 unit/E2E。独立阅读实现和红绿日志，未读取本轮 critic 结果、未修改业务/测试代码、未运行真实模型，也未冻结留出题。下列测试数量来自已归档日志复核，不冒称 reviewer 重新执行过完整矩阵。

### Verdict

D-01 和 D-03 的当前实现可以有限准入后续分段开发与真实调度实验。复核中发现的最终 Generate 吞 busy 信号已由精确回归复现并修复；当前没有剩余 High 实现阻断。本结论不等于调度性能收益通过，亦不等于 D-02 分段、保存/历史和界面契约已经实现。默认保持 off，完整矩阵和真实对照仍是交付前工作。

| Item | Disposition | Evidence | Limit |
|---|---|---|---|
| D-01 control retries | accepted; implemented | classifier、agent、grade、rewrite 及 BaseSkill timed wrapper 的 ModelBusyError 分支先于普通异常；拒绝直接上行到入口。`tests/unit/test_local_model_queue.py:138` 分别覆盖 sync/async classifier 只尝试一次；`tests/e2e/test_local_model_admission.py:10` 覆盖真实模型包装 + intent 的 JSON/SSE 饱和，网络调用数为零、confidence 为 None。 | 不是把所有模型错误都改为终态；旧通用降级不因本次设计扩展。 |
| D-01 final generation | accepted; reproduced and fixed | 初审时 `GenerateSkill` 两个宽异常分支仍吞 ModelBusyError；`validation/generation-busy-red.log:215` 为 2 failed，原因是公共结果缺 generation_complete。现 `agent/skills/generate/skill.py:317`、`:660` 前的专门分支将信号上行。真实 Graph + router + mock 网络回归在 `tests/e2e/test_local_model_admission.py:78` 拒绝最终长调用，确认只有一次拒绝、无 JSON schema 最终网络调用。 | 同步分支已按同样窄异常结构核对；此次公共 JSON/SSE 回归执行的是异步 Graph。 |
| D-01 public outcome | accepted; implemented for Step 3 | Harness 四执行边界转换 busy，`_busy_state` 写独有 model_queue_outcome，`_build_request_shared_state` 清旧值；API `_build_metadata` 读取 outcome 并把不可用置信度设为 None/degraded。Fast sync/async/stream 对 busy 单独返回同义结果。 | 最终保存/历史携带完整 generation_outcome 仍属下一阶段，当前不能宣称 D-02 全部关闭。 |
| D-03 shared admission | accepted; implemented | `local_model_queue.py:96`/`:110` 的同一线程锁管理 active 与等待项；sync Event 和 async Future 共享该队列。没有可继承的 lease token；`scheduled_chat_model.py:24`–`:44` 在四 SDK 入口持槽。取消或超时的 finally 撤销等待项或释放已授予槽。 | 这是单进程模型调用队列，不能替代跨进程调度；同步活跃网络调用在实际返回/关闭前仍占槽。 |
| D-03 fairness and cleanup | accepted; scoped evidence | 单元测试覆盖两次短调用后放行生成、2 秒年龄提升、队列上限、超时、取消与 grant 竞争、混合 sync/async。`test_public_stream_close_releases_transport_before_slot` 使用真实 httpx AsyncByteStream，断言 transport 关闭时槽仍持有、public astream 关闭后槽归零。 | 该测试是网络边界 mock，不证明真实 Ollama 收到取消后何时停止 GPU 工作；后者留给已计划的取消实验。 |

`validation/admission-green-v2.log:2` 归档结果为 **26 passed in 2.49s**。红绿证据直接验证本次实际失效行为，成本与改动规模相称。未因“LangChain 可能延迟关闭”的假设另建 SDK 层替换工程；以精确流关闭回归判断当前代码即可。

### Measurement Follow-up Within Existing Scope

当前 `CallStats` 只累计成功获得槽的调用 queue_ms/service_ms/calls（`local_model_queue.py:35`、`:136`），尚未提供 v2 所述每次 call_class，也没有记录未获得槽而超时的等待耗时。请求统计对象经 contextvar 隔离，并通过共享对象覆盖同一请求的子任务，这个结构合理；但现有公共结果只能说明请求累计等待，不能单靠它证明“短控制等待减少”。

这是 Medium 的实验可解释性限制，不是新增独立门禁。真实对照前，在既有探针或调用记录补足短/长分类以及 timeout 等待耗时即可；保留请求累计字段，不要求新遥测平台。对拒绝请求不应用缺字段冒充 0ms。实际 GPU 吞吐、排队公平、取消效果继续分别报告，不用单元通过数替代性能成果。

### Remaining Stage Boundaries

- D-02 的检查器/receipt、只追加段落、完整/不完整状态保存、历史和 UI 尚待 Step 4；本次不把这些未完成工作误报为 Step 3 缺陷或完成。
- 调度开关仍 off，尚无真实两轮/混合/取消收益的独立结论。即便公平调度不提高 GPU 吞吐，也可依据明确测得的背压和取消收益决定是否启用。
- 新留出继续等待 prompt 和生成实现稳定；未提前消费题目。


## Design v3 Admission and Mechanism v1 Review — 2026-11-11

**Scope:** `design.md:44`–`:47`、`data/eval/local-stream-mechanism-v1/results.jsonl` 全部 16 条完整正文及首个 token 事件、原开发协议 `docs/specs/bounded-local-rag/validation/development.json` 的问题/来源/整题要求。未读取本轮 critic 报告、未调用模型、未冻结留出题。

### Verdict

**准入 v3 编码与红绿验证，默认继续 false。** 单次 JSON 改为 evidence → conditions → answer，并把已验证 conditions 与 answer[0] 合成一个不可拆开的首次发布内容，是针对已复现问题的合适小改动。它复用 baseline 的条件字段，不增加模型调用，也不引入语义判断服务。当前 v1 不具备默认启用的质量依据；v3 是否有效须以新一轮完整答案和首块评审确认。

### Full-answer Findings

| Case and round | First delivered body | Whole answer | Evidence |
|---|---|---|---|
| ih2_06 R1 | 通过：已有记录比较、8 W/5 W、不能判断相同负载均在首次发布内容。 | 通过；后段重复限制，不改变结论。措辞“表现更好”宜理解为给定记录运行时长，不应扩大为综合性能。 | results.jsonl:2；protocol:14、:25–:28 |
| ih2_06 R2 | 不通过：首次内容只给记录比较，未回答问题的“能否判断相同负载优劣”。 | 通过：第二段才给出不能外推的限制。 | results.jsonl:9 |
| dev_zero R1 | 通过：保留 10 分钟、两个零结果、零不等于缺测；“但单位不同”措辞较弱，但未给出错误数值结论。 | 同首块，无后段新限制。 | results.jsonl:4；protocol:43–:52 |
| dev_zero R2 | 通过：0 毫秒与 0 秒换算一致，且不是缺测。 | 结论正确；末段存在来源归属措辞瑕疵：称两份证据明确指出“记录的零值不等于缺测”，实际 corpus 仅写测量已完成和本次记录结果。该判断可从资料推得，但不能伪装成来源原句。 | results.jsonl:11；protocol:6–:7 |
| dev_calibration R1 | 通过：正常连续使用、120 日历日、首次确认起算、更换后先校准及重新起算齐全。 | 同首块，通过。 | results.jsonl:6；protocol:8、:61–:69 |
| dev_calibration R2 | 不通过：漏掉正常连续使用限定。 | 不通过：全文也未补上该限定。 | results.jsonl:13 |
| dev_missing R1/R2 | 通过：价格未提供，18 个月从交付起算，英文回答并引用来源。 | 通过；无虚构价格、无把 42 mm 当价格。 | results.jsonl:8、:15；protocol:9、:78–:86 |

其余 8 条 buffered 全文也已阅读：比较条件、零值与缺测、校准正常使用条件/起算规则、价格未知/保修均有表达。校准 buffered 文本的首个自然段也未写正常使用限定，但它一次交付完整正文，限定同次到达；不能用自然段边界混淆“首次交付内容”边界。buffered 的 dev_zero R1 同样出现把推论说成“资料明确说明”的较强归属措辞，因此不能把来源归属措辞问题全算作分段独有退步；本轮保留原文，不以新增机制扩大处理。

16 条记录均为一次模型调用。v1 segmented 首次交付内容完整性为 **6/8**；R2 比较和校准不能计为有效首段。P50 3.429 → 2.976 秒、下降约 13.2% 是全部槽位的原始首块时延，不能据此声称“合格首段已提速 13.2%”，也不应剔除两条失败后拿 6 条与 baseline 8 条直接比较。

### Why the Revision Is Proportionate

- **结构性解决已知后置问题：** `results.jsonl:9` 的模型确实生成了不可外推限制，只是放在第二段。conditions 在 answer 前完成，程序把全部已提取条件与结论一次发布，就不再依赖模型把这些条件自行搬入第一个 answer.text。每条条件仍保留自己的来源引用，作为完整首次内容一起走当前输出检查。
- **不夸大对遗漏的作用：** `results.jsonl:13` 的正常使用条件根本未出现在全文。单独条件字段可恢复 baseline 已表现有效的抽取任务分工，但程序无法补齐模型没有生成的事实。v3 `design.md:46` 已诚实承认这一限制；编码准入不等于条件完整性得到证明。
- **更小替代方案不足：** 仅强化“首段包含全部条件”prompt 是现有任务分工的重复；固定等待两个 answer 段既不能处理单段遗漏，也不能保证条件不会在第三段。把 evidence 全部公开会混合事实摘录与答案，增加重复；等待整个答案恢复原缓冲行为则丢失本次提前交付的目标。当前三字段修订规模仍小，且不用额外调用。
- **成本必须重测：** 条件在首个答案前生成会增加首块前 token，且可能和结论重复。evidence 只留事实/必要换算，条件专属 conditions，有助于控制这个成本。无需为达到原 30% 观察目标扩大调用预算或截掉条件；质量合格后按实际首块 P50/P95、全篇时长和全部完成槽位判断收益。

### Implementation Admission Conditions

这些是 v3 现有设计的落地边界，不是新增架构门禁：

1. 首次发布单位是 **已完整验证的 evidence/conditions + 首个完整 answer 对象所形成的可见结论和全部条件**。evidence 本身不发布；condition 尚未闭合、引用不合法或首个 answer 未完整时不发布。平台免责声明在该整体检查后追加，不能插在结论与其限定之间。
2. conditions 的各自引用应随对应条件保留；不靠合并引用编号来暗示所有来源支持所有子句。首块必须整体检查后一次输出，不能先 yield 结论、再 yield 条件。
3. 同步/非流式与流式共用相同首块合成规则；后续 answer 只作解释，仍遵守不撤换已交付正文及失败 partial 协议。增加的条件字段仅扩展现有 schema/解析/渲染回归，不另建字符串语义判分。
4. 红绿用例直接固定已复现类型：answer[0] 无限制但 conditions 有限制时首块带齐；conditions/首个 answer 截断或非法引用时尚无首块；同步结果和流式结果采用同一合成。随后重新审两轮已暴露 4 题的首块和全文，保留 v1 失败记录，再考虑独立新留出。

因此，本轮无须再增加编码前 High 设计阻断；v1 的首块质量失败仍是部署阻断，待 v3 实验结果关闭。新题继续等待生成 prompt 稳定后冻结。


## Mechanism v2 Results — v3 Quality Review, 2026-11-11

独立阅读 `data/eval/local-stream-mechanism-v2/results.jsonl` 全部 16 条正文与首次 token 内容，并逐项对照 development corpus/整题要求；另解析 model-http 原始非流式响应与 SSE 内容。没有调用模型或读取历史留出题。按任务最新指示，质量评审后暂缓冻结新题，未创建 holdout-v3.json 或 freeze.md。

### Quality Decision

**v3 本轮未见实质质量退步：8/8 分段答案的首块和全文均可通过开发题语义评审。** 条件重复、句式不够紧凑及“不能外推”是否采用同一句式不单独升级为失败；判断依据是已有数值关系、适用范围和未知边界是否已向用户交付，后段有无新增改变结论的限制。

| Case | R1 segmented | R2 segmented | Buffered full answers |
|---|---|---|---|
| ih2_06 | 540 分钟/600 分钟及各自 8 W/5 W 齐全，首次已明示不能推断同负载优劣，全部引用对应。 | 首块给出 9 小时/10 小时记录比较、各自负载限制、未提供其他/相同负载数据；后段只是明确这些限制的不可判定后果，没有新增限制。因此语义通过，不以缺某句固定措辞再判失败。 | 两轮均正确比较记录并保留不可外推条件。 |
| dev_zero | 首块明确 0 毫秒=0 秒、10 分钟条件和测量已完成；不是缺测。 | 同样齐全，零值和记录单位的条件有重复，但没有错误外推或不同单位就判不同的结论。 | 两轮均正确；没有实质数值/来源退步。 |
| dev_calibration | 首块已给正常连续使用、120 日历日、首次投入使用确认和更换后校准完成日两个起算点。 | 首块同样齐全，且明说更换后先校准再重新起算。v1 的正常使用限定遗漏本轮未复现。 | 两轮全文均保留限定与起算规则。 |
| dev_missing | 英文回答价格未提供、保修 18 个月从交付起算，引用产品资料。 | 同样正确，无虚构价格或误用 42 mm。 | 两轮均正确。 |

对应 segmented 行为 results.jsonl:2、:4、:6、:8、:9、:11、:13、:15；buffered 为其余八行。全部原始模型响应以 stop 结束，16 条请求/16 个答案、每答一次模型调用；不把该结构事实替代上表的语义阅读。

### Latency Decision

| Metric | Buffered, n=8 | Segmented, n=8 | Interpretation |
|---|---:|---:|---|
| First delivered body P50 | 3.262651 s | 3.620234 s | 慢 10.96%，本轮无首块收益。 |
| First delivered body P95, linear interpolation | 3.954702 s | 4.478973 s | 小样本尾延迟也未改善。 |
| Full answer P50 | 3.262652 s | 3.660661 s | 全篇完成更慢。 |
| One answer block | 8/8 buffered once | 7/8 segmented | 当前短题通常没有后文可提前释放，不能把功能支持分段当作已取得提速。 |

质量改善和性能失败分别保留；不把 v3 宣称为部署通过，也不因质量已通过就默认启用。模型原始 SSE 没有 completion_tokens usage，因此当前可量化的是实际输出 evidence 的文本字符数 **57–105**，不能将字符数或 SSE chunk 数冒充 token 数。

## Design v4 Admission — 2026-11-11

独立核对 `design.md:49`–`:52` 后，**准入最小 v4 编码，默认继续 false，无新增 High 设计阻断。** 输入 kept evidence 完整保留；输出仅 conditions → answer；conditions 完整验证后与首个答案原子合成；引用枚举、输出检查、finish/partial/取消语义、一次模型调用与总预算不变。删除重复输出字段的范围清楚，适合作为下一次最小消融。

- **Reasoning:** 当前模型已经看到全部输入事实，额外输出内部事实摘要不是不可替代的运行时验证。删除该摘要可以减少首块前的生成工作，而保留 v3 处理条件后置的结构。必要数字和换算仍需在答案/解释中清楚表达，不得为省输出将答非所问或缺事实视为成功。
- **Quality risk:** 没有显式事实准备可能使单位换算、零值与缺测、条件抽取退步；这是本轮要验证的算法取舍。设计已安排同 4 题两轮，复用现有完整语义标准即可，不新增在线 judge、额外调用或语义证明机制。
- **Concrete wording gap, non-blocking:** `design.md:50`、`:52` 的“真实瓶颈”/“已测得生成 token 开销”应表述为已观察到重复输出与时延、待消融验证其贡献。SSE 未返回精确 token 数，且 conditions 重复等开销也存在；目前不能归因到唯一瓶颈。此修正文案即可，不需另建测量系统。
- **Implementation focus:** schema、prompt、增量解析以及同步渲染同时去掉输出 evidence；保持 conditions 数组和 answer 非空/引用/完成边界原有测试。下一次两轮继续用全部 8 个槽位分别报告首块质量与时延，保留 v1/v3 原始失败。质量和实现稳定后再冻结新留出。

本轮没有创建或运行任何留出题，也没有修改业务代码。


## Mechanism v3 Results and Design v5 Admission — 2026-11-11

独立审阅 `data/eval/local-stream-mechanism-v3/results.jsonl` 全部 16 答、首次交付内容和 development corpus；未读取旧留出或本轮 critic 报告，未运行模型。

### v4 Quality Findings

| Case | Segmented R1 | Segmented R2 | Buffered R1/R2 |
|---|---|---|---|
| ih2_06 | 不通过整题：9 小时、600 分钟=10 小时及不同负载限制均正确，但没有直接回答记录中哪个更长；只列可供用户自行比较的数值。 | 通过：明确 10 小时大于9小时，并保留不同负载/不能判断同负载优劣。 | 两轮通过。 |
| dev_zero | 通过：10分钟、0毫秒=0秒、零是完成测量结果而非缺测。 | 通过，无新限制或错误外推。 | 两轮通过。 |
| dev_calibration | 通过：正常连续使用、120日历日、两个正确起算点、更换后先校准齐全。 | 通过，首次交付已齐全。 | 两轮全文通过。 |
| dev_missing | 通过：英文、价格未知、18个月从交付起算、来源正确。 | 通过。 | 两轮通过。 |

segmented 7/8 通过，已知比较 R1 之外未发现新实质问题。原始首块 P50 约3.364→1.794秒不能当作全部题型质量合格的46.7%收益；8条分段答案本轮均仅一个 answer 块，改善主要表现为精简输出的更早完整交付，不能声称本样本验证了长文多次提前发布。

### v5 Design Decision

**准入 v5 有限分流实现及最终组合验证。** 比较/等值/差值/倍数保留已合格 bounded 完整生成，其余问题使用 conditions→answer，是质量优先且成本适当的终版适用范围。它不要求再次模型分类、不先暴露比较草稿、不对失败再生成，也没有把比较题从整体评价分母删掉。

本地词匹配是保守启发式，不是完整语义识别器：多选会减少加速覆盖，未匹配的隐含比较仍可能存在。文档和验收应诚实描述此边界，以通用中英文变体和实际所选 schema 覆盖各入口；不承诺识别任意比较表达。当前无须为此扩展到新分类模型。各Fast/Thinking与sync/async/stream入口必须共用同一选择函数；生成前选择一次，不能失败后尝试第二条模型路径。

等值题当前两轮虽通过，和比较一并保留原路径是保守覆盖取舍，不是宣称已复现其全部失败。现有开发集上的比较/等值占一半，因此整体收益必须以实际覆盖数和全题分位数计算；不能把非比较子集收益推广到全部题型。默认保持false，组合 API 两模式两轮及新留出通过前不报告部署完成。

### Independent Holdout Freeze

设计范围认可后已冻结 `validation/holdout-v5.json` 与 `validation/freeze-v5.md`：1道新中文换算/工况比较、1道新英文非比较多条件流程和长说明。全部名称、数据和来源为本轮新拟，未读取旧留出，未调用模型。题面与整题人工要求在运行前写定，生成输入仅 query/corpus 正常资料证据；离线要求不得进入模型上下文。冻结后不得据题面或输出调prompt/路由；如用于修订，相关题须转开发集并另冻新题。

这次冻结不是声称 v5 已通过新题或性能门禁。后续须保留所有槽位及失败原文，分别审首块/全文，并报告实际分流覆盖和整体收益。


## v5 Development API Review — 2026-11-11

**Reviewed evidence:** `data/eval/local-adaptive-api-baseline/{results,model-http,batch}.jsonl/json` 与 `local-adaptive-api-candidate` 对应文件。独立逐条阅读两模式×两轮×4题，共 **32 答** 的首次 token 内容和全文，并按 development corpus/整题要求判断；实际 schema 来自各结果 model_start/model_end 区间内的模型 HTTP 请求，不从开关名称推断。未读取本轮 critic 报告，未运行模型，也未改冻结题或 prompt。

### Semantic Decision

baseline **16/16**、candidate **16/16** 首次交付内容和全文通过本开发集语义评审，没有发现新增实质质量退步。判定依据如下，不是以数字或关键词命中替代全题阅读：

| Case | Slots reviewed per variant | Required meaning verified |
|---|---:|---|
| ih2_06 | Fast R1/R2、Thinking R1/R2 | 统一单位后给出芦序记录续航长于赤砚，保留各自5 W/8 W条件，并明确不能判断同负载优劣。candidate 四答均给直接排序结论，没有重现 v4 R1 只列数值的遗漏。 |
| dev_zero | Fast R1/R2、Thinking R1/R2 | 0毫秒与0秒表示相同偏差，保留10分钟条件，明确已完成测量的零结果不是缺测，两来源相符。 |
| dev_calibration | Fast R1/R2、Thinking R1/R2 | 正常连续使用、120日历日、首次完成投入使用确认起算、更换后先校准再从校准完成起算均齐全。candidate 的精简首次交付已包含全部这些限定。 |
| dev_missing | Fast R1/R2、Thinking R1/R2 | 英文答复价格未提供、保修18个月从交付起算，没有编造价格或将42mm当价格，来源正确。 |

每份 results.jsonl 的行1/5/9/13为比较，2/6/10/14为零值，3/7/11/15为校准，4/8/12/16为未知价格。全部32答的首个 token 内容等于该答全文，因此没有隐蔽地把后续才补足条件的答案算作有效首块；同时也不能以此样本声称真实长文的多次提前交付已被证明。

### Actual Routing and Calls

- baseline 16次最终生成全部使用 `basis,conditions,conclusion`，HTTP非流式完整返回。
- candidate 比较与等值共 **8/16** 次仍为上述完整schema；校准与未知价格共 **8/16** 次使用 `conditions,answer` 且 `stream=true`。两个模式、两个轮次的实际分流一致，精简覆盖率为本样本的50%。
- 两组分别为 **40次实际调用=24次控制+16次最终生成**。Fast每答1次；Thinking每答3次控制+1次最终生成。未新增最终生成或事后修复调用，也未发现额外judge调用。不能把“一次最终生成”简写成Thinking端到端只有一次模型调用。
- 两组均16个complete终态，全部尝试槽位均进入评价；没有以拒答/不完整样本替换有效答案分母。本次结果不改写先前实验中的Fast覆盖缺口。

### Observed Benefit and Cost

以下P95均采用线性插值；每模式仅8槽、整体16槽，是小样本观察而非稳定尾延迟保证。

| First-delivery metric | Baseline | Candidate | Reading |
|---|---:|---:|---|
| Overall P50 | 4.200480s | 3.793346s | 降约9.69%。 |
| Overall P95 | 6.016896s | 6.287500s | 增约4.50%，未全面改善。 |
| Fast P50 | 3.206433s | 2.770599s | 改善。 |
| Fast P95 | 3.701953s | 3.969288s | 本轮变慢，须如实保留。 |
| Thinking P50 | 5.597863s | 5.447053s | 小幅改善。 |
| Thinking P95 | 6.066351s | 6.437001s | 本轮变慢，须如实保留。 |
| Compact-eligible subset P50, n=8 | 3.944917s | 3.137496s | 降约20.47%，仅适用于该子集。 |
| Retained comparison subset P50, n=8 | 4.647112s | 5.138279s | 同完整策略的观测波动/成本仍计入整体，不宣称比较也加速。 |

全篇P50为4.259299→3.947074s；顺序批次耗时69.236750→64.287116s，下降约7.15%。这些是最终组合在开发集上的实测，不把机制 v4 的原始46.7%推广为API整体收益。无需为了让所有指标更优而继续扩大模型调用或把已保留路径排除；新留出及最终检查仍待完成。

## Step 3 Mixed-run Measurement Review — 2026-11-11

对 `local-queue-off-v1` 和 `local-queue-fair-v1` 核对批次、结果状态、模型调用和时间记录；此处是调度计量审阅，不冒称另外逐句验收了这32份混合正文。

| Metric | Off | Fair | Reading |
|---|---:|---:|---|
| Slots / complete | 16 / 16 | 16 / 16 | 本轮没有busy、abort或cancel样本。 |
| Actual model calls | 40 | 40 | 均24控制+16最终生成。 |
| Batch elapsed | 73.895343s | 72.685778s | 仅下降约1.64%，不能宣称显著推理加速。 |
| First-delivery overall P50 | 11.753264s | 12.043920s | 略变慢。 |
| First-delivery overall P95 | 18.831631s | 18.181623s | 略改善。 |
| Observed HTTP requests in flight, peak | 4 | 1 | fair实际把模型网络准入串行化，与单槽设计一致。 |
| Request cumulative application queue P50/P95 | 未记录 | 6.801490s / 12.444544s | 这是应用等待可见化，off缺字段不能当0ms；也不是GPU计算吞吐。 |

Fast首块P95为9.397562→9.661825s，Thinking为18.900210→18.771091s；不存在“所有模式都更快”的证据。现有模型HTTP日志已提供call_class，补足了先前评审指出的实验分类可解释性。

有界等待和取消属于该设计的部署价值，但本次混合样本没有触发拒绝或取消，不能单独据此宣称已测得真实取消节省。相关结论应引用专门的饱和/超时/取消回归或实测，而不是把排队从引擎搬到应用记为额外吞吐。当前没有因这些小幅速度取舍提出新增架构门禁；按既定范围如实汇报即可。


## v5 Frozen Holdout Review — 2026-11-11

**Evidence and independence:** 按运行前冻结的 `validation/holdout-v5.json`，逐条审阅 `data/eval/local-adaptive-holdout-baseline/results.jsonl` 与 candidate 对应文件全部 **16 个槽位**的首次交付及全文，并核对两组 model-http 的真实 schema/调用区间。未读取本轮 critic 报告，未运行模型，未修改题目、prompt 或比较词表。下列行号均指各自 results.jsonl。

### Whole-question Decision

**新留出没有给出默认开启分段的质量依据；保持 `LOCAL_RAG_SEGMENTED=false`。** 两组分别只有6个执行完成的生成和2个弱检索终态；`generation_complete=true` 是协议完成，不能据此声称6/6整题成功。比较的有效生成均正确；长流程存在两组共有的遗漏，candidate 另有可见的配对内容损失。开发集16/16通过仍然成立，但不能替代新题结论。

| Slot / line | Baseline first delivery and whole answer | Candidate first delivery and whole answer | Decision |
|---|---|---|---|
| Flow R1 Fast / 1 | 弱检索，未作记录比较；unavailable/retrieval_terminal，confidence=None。 | 同样弱检索，无模型调用。 | 两组都只是安全终态，不能计为答案成功或把不可用记0分。 |
| Procedure R1 Fast / 2 | 工况、首次起算、37活动小时/排除待机、换头通过后重计、失败停机、未知信息齐全；全文未给准备指定参考纸、serial/date/result记录和保留失败记录这些实操步骤。 | 首块即全文，主要工况/首次起算/失败规则正确，但同样遗漏上述实操；fresh37小时只接在失败后复检段，换头首次检查通过后的重新起算关系不够明确。 | 整题不通过；不能把精简后的规则摘要当作完整流程。 |
| Flow R1 Thinking / 3 | 明确苔弦0.25L/s高于霜榆0.23L/s，保留甲/27°C与乙/17°C及无同工况对照。 | 明确15L/min高于13.8L/min，条件和不可外推齐全。 | 两组通过。冻结标准允许等价单位，不能事后因baseline没有按分钟书写而判错。 |
| Procedure R1 Thinking / 4 | 首次即全文，操作/记录动作及核心条件齐全；首次/周期检查目的没有充分展开，不能宣称所有说明点都已覆盖。 | 唯一两块输出：首块已有工况、37活动小时、通过检查才起算、失败停机及未知边界；后块给参考纸、serial/date/result、失败记录和追溯，明确首次通过而非交付起算。换头需新检测的目的说明较简。 | 没有发现后块新增会逆转首块的限制；实操覆盖较好，解释覆盖仍应如实描述，不因固定措辞缺席单独升级问题。 |
| Flow R2 Fast / 5 | 与R1一样弱检索终态。 | 与R1一样弱检索终态。 | 仍计尝试槽位，不计答案成功。 |
| Procedure R2 Fast / 6 | 核心条件包括换头后通过才重新起算；实操记录步骤仍遗漏，部分目的说明不足。 | 首块即全文；同R1 Fast，缺实操记录步骤，重新起算只明确连接失败后的复检，没有清楚连接换头检查。 | 整题不通过；不以37、pass等词出现代替事件关系判断。 |
| Flow R2 Thinking / 7 | 明确0.25L/s高于0.23L/s，工况/未知边界齐全。 | 明确15L/min高于13.8L/min，工况/未知边界齐全。 | 两组通过，无虚构同工况结论。 |
| Procedure R2 Thinking / 8 | 首次即全文，指定参考纸、serial/date/result及保留失败记录均有；目的解释不全。 | 首次即全文，核心条件完整并写serial/date/result，但漏准备指定参考纸和**保留失败检查记录**，也未充分展开周期检查/追溯目的。 | 明确存在配对内容损失：baseline同槽有的失败记录保存要求在candidate消失，不能由合法JSON、引用或完整终态抵消。 |

冻结流程要求逐项核对的结果是：R7/干燥室内/16–28°C、首次检查通过起算、37活动小时且排除待机、失败停止直至纠正并复检通过、室外/潮湿场景无已给规则、费用未知均有实质覆盖。Fast candidate 的换头重新起算关系和多份答案的实操/目的覆盖仍不足。因此不将“核心条件大体正确”缩写为“首块与全篇全部合格”。R1 Thinking candidate 后文只是细化首次起算和操作过程，不据其没在首块逐字写“not delivery”另造门禁。

引用方面，各比较数值与工况均归于正确来源，流程答复也使用了规则和检查说明两份来源，没有凭空价格或室外许可。baseline Fast R2有一段把“建立安装工作参考”的说明只引到 operating_rules，实际说明在 check_notes；全文首段引用两者，属于归属精度瑕疵。合法来源ID不能证明每个子句都获该来源支持，也不能补回未写出的步骤。重复条件及中文平台免责声明不单独导致英文正文不合格。

### Actual Routing, Calls and Timing

- 两组各8槽、各18次实际调用，均为 **12次控制+6次最终生成**，没有第二次最终修复或在线judge。两次Fast比较各自无模型调用。
- baseline的6次最终生成全部使用`basis,conditions,conclusion`。candidate的2次Thinking比较仍使用此完整schema，4次流程生成实际使用`conditions,answer`和流式请求；精简覆盖是全部尝试的4/8、实际生成的4/6。不是遇到失败后再回退调用。
- candidate仅R1 Thinking流程有两块；其余5个实际生成首次即全文。该唯一长文样本说明机制能够提前交付检查后的正文，不能据此声称一般长文已经充分验证。
- 顺序批次52.105354→35.429021秒；6个实际生成的**原始**首块P50为8.637716→5.669807秒。这些包括流程不完整答案，不能作为“合格答案提速”的验收数值；两条弱检索仍保留在每组8槽的总分母。
- 连同开发集整体P50下降9.69%、P95上升4.50%的取舍，本次可以确认部分精简输出更早到达，不能确认完整流程质量不退步或普遍尾延迟改善。

本轮以关闭默认开关收敛，不据留出调prompt/词表，不扩大到新分类器、二次生成或在线语义判分。若后续用此流程题推动修订，须将它转开发题，再另冻新题；本次原始失败记录保持不变。

## Step 4 Implementation Review — 2026-11-11

**Scope:** 独立读取当前`core/segmented_generation.py`、`core/local_rag_generation.py`、Generate/Fast、GuardrailManager/SkillContext、API保存与历史、前端停止和partial处理及对应unit/E2E/Playwright代码。未读取critic本轮结果、未运行模型或测试；测试结果只引用已归档日志。实现可作为**默认关闭的有限分段能力**交付，未发现需另扩机制的Critical/High实现阻断；质量开关决定与协议实现正确性分开。

| Contract | Implementation evidence | Review conclusion |
|---|---|---|
| 同一生成先条件后答案，首块不可拆 | `core/segmented_generation.py:65`先完整解析并校验conditions，`:97`验证完整对象，`:99`把条件合入answer[0]后才交检查器；`core/local_rag_generation.py:43`非流式采用同样合成。 | 首块不会先放结论、后放条件。结构不能保证模型已抽取全部语义条件，留出失败仍成立。 |
| 原有检查配置与不可改写前缀 | `agent/guardrails/manager.py:68`注入当前实例check_output，`SkillContext:57`仅请求内持有；`CheckedParagraphs:123`检查累计正文，拒绝BLOCK/ESCALATE、空正文或已发布前缀改写。 | Thinking使用实际manager配置；Fast沿用其现有默认manager路径。缺checker时完整缓冲；未新建另一套检查策略或在线judge。 |
| 相同内容的检查回执 | `GenerateSkill:611`记录当前已发布终态正文；manager`:116`仅在该context回执与最终内容相等时跳过重复检查。 | 回执不跨请求/不持久化，避免after-hook再次改写已发布正文。它不宣称答案语义已正确。 |
| 明确结束与后段失败 | `ParagraphParser.finish:108`及非流式renderer`:47`均要求stop；`stream_answer:147`持有并关闭内层流，普通后段失败只追加固定未完成提示，ModelBusy单独上行。 | 半JSON、length、未知结束或检查失败不伪装complete；保留已检查前缀，不将未检查候选泄露。CancelledError不被普通Exception转换为成功结果。 |
| Graph状态及消费者 | `GenerateSkill:610`/`:617`写generation_outcome整键；同步/其余路径先清理并写相应终态。API`:1330`读取shared_state、`:1437`保存最终元数据、`:1009`恢复历史，`:525`令不可用置信度为None/degraded；Fast同义传播并捕获评测元数据。 | 状态通过shared_state通信，AIMessage字段只承担最终持久化。fallback_general_chat显式清旧outcome，未把上一节点未生成状态误带到一般聊天。 |
| UI停止与部分正文 | `web/src/stores/chat.ts:180`传AbortSignal，`:225`/`:301`在异常或无done结束时保留现有正文并标未完成；ChatView有停止按钮和独立提示，历史携带metadata。 | done沿用服务端最终值；本次真实Graph回归要求它与所有token拼接一致。没有为了假设的任意畸形服务端新增通用对账层。 |

`test_segmented_api_persists_completion`使用真实Graph/router和真实GuardrailManager、mock网络，覆盖两模式×JSON/SSE×stop/length，检查PII不会发布、token拼接与保存正文一致、历史状态及一次最终调用。单元回归覆盖增量边界、引用、先交付后失败、检查器改写前缀与非流式严格stop。UI回归覆盖已显示前缀后的停止和partial提示。

日志核对：`stop-contract-red.log`为2failed/2passed，当前`adaptive-green.log`为44passed；早期`segment-api-green*.log`仍保留中间失败，最终不能只凭文件名把它们视为绿。`ui-red-v2.log`2failed到`ui-green.log`2passed；当前`full-ui.log`23passed/1skipped，`coverage.log`报告74%。所见`full-backend-v2.log`仍含FakeLLM缺astream的1failed/1272passed，父任务正在处理完整矩阵；本报告不冒称完整矩阵已绿，合并前仍应按既定流程归档最后结果。上述是现有验证范围，不追加新的防御性门禁。

## Step 3 Capacity, Live Cancellation and Default Decision — 2026-11-11

独立核对`data/eval/local-queue-capacity-v2/results.json`及`local-live-cancel-v1/results.json`，并读取消探针确认是真实模型产生首个字符后关闭流，而非模型开始前撤销等待。

| Evidence | Observation | Meaning and limit |
|---|---|---|
| Capacity | 活跃流占槽期间8个等待项取消、2个queue_full，超时30.030430秒；后续请求前仅1次实际模型调用。 | 有界队列和等待撤销生效，拒绝/超时没有自动追加模型调用。该探针有意保持已取得首块的流，超时是准入等待，不是GPU计算时长。 |
| Live cancel | 首个“整理”字符后关闭，应用槽释放0.000543秒；后续请求0.153754秒返回OK；实际调用共2次，active/pending均0。 | 真实网络流取消后可重新准入。未直接测量GPU内核停止时间，不能把槽释放数值报告成GPU取消耗时或GPU节省量。 |
| Mixed performance | 既有混合批次73.895→72.686秒，仅约1.64%改善；P50略慢、P95略好，实际HTTP并发峰值4→1。 | 支持有界准入/等待/取消价值，不支持明显推理吞吐提升或所有请求更快。 |

**最终建议：已合格本地endpoint、单进程部署默认`LOCAL_LLM_SCHEDULER=fair`；`LOCAL_RAG_SEGMENTED=false`保持不变。** 两个开关独立。fair仍遵守同步活跃调用实际返回/关闭才释放槽的限制，不扩成跨worker调度。分段可显式试用，交付说明必须保留长流程完整性退步和开发集尾延迟代价，不把默认关闭写成“质量验收全面通过”。这既交付了已验证的队列能力和可回滚的分段实现，也避免为了本轮留出继续无界调参；最终合并仍以父任务完成既定测试矩阵、文档与追踪闭环为准。


## Final Matrix Closure — 2026-11-11

按父任务要求仅复核新增完成日志及最终默认/组合运行记录，未新增实验、运行测试或模型，也未改代码、prompt及留出。上一节所述“完整矩阵待收口”现由以下证据更新：

| Validation | Verified result | Scope |
|---|---|---|
| `validation/final-backend.log` | **1274 passed, 6 skipped, 3 warnings**；该最终日志自身coverage为**74%**。 | 原`full-backend-v2.log`的中间失败记录保留；最终矩阵已通过，不再以该旧失败作为待办。 |
| `validation/full-ui.log` + `ui-final.log` | 原全UI **23 passed/1 skipped**；随后3个segmented用例全通过，包括新增历史未完成提示。去重合计**24 passed/1 skipped**。 | 后一次停止/partial两个重跑用例不重复计数；历史显示契约已有浏览器回归。 |
| `data/eval/local-final-default` | **2/2 complete**，Fast/Thinking各一槽；5次HTTP调用=3控制+2最终生成，2次最终均为`basis,conditions,conclusion`。 | 默认关闭分段的完成性烟测，非新独立质量或性能对照。 |
| `data/eval/local-final-combined` | **4/4 complete**，fair+segmented混合执行；10次HTTP调用=6控制+4最终生成，2次原完整schema、2次`conditions,answer`。 | 组合路径完成且分流存在；没有用这4槽覆盖或撤销先前留出质量问题。 |

本轮既定测试矩阵已收口，**默认fair、segmented=false的交付建议保持不变**。独立评审没有新增阻断；原留出中的长流程遗漏、有限样本尾延迟取舍及单进程调度边界继续保留，最终烟测不构成“普遍更优”或“留出全面通过”的新结论。
