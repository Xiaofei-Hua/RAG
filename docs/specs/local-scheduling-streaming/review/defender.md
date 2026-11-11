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
