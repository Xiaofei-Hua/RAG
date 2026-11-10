# Design v2

## Evidence and Research
此前原始流已确认：同四题18个judge HTTP；关闭后0个，但零值题仍有13,569字符重复正文，另一轮只有48,112字符delta.reasoning而无正文。旧实验采用temperature=0，不能用工厂字段4096推断引擎实际按4096停止。
Qwen官方模型卡建议按模式设置采样，并提醒presence penalty可缓解重复但过高会混语言；Ollama的OpenAI兼容只支持部分字段，云API的thinking_budget不能直接当成本地Ollama能力。参考：
- https://huggingface.co/Qwen/Qwen3.5-9B
- https://docs.ollama.com/api/openai-compatibility
- https://docs.ollama.com/capabilities/thinking
- https://github.com/ollama/ollama/issues/17561
- https://github.com/ggml-org/llama.cpp/blob/master/common/reasoning-budget.cpp
已有官方采样单变量实验未解决语言/0单位推导，故本次不只改温度；以明确的检索作答任务替代无约束隐式长思考。先验证一次生成机制，不能继续叠加judge或专用题型补写。

## Strategy
新增一个整体策略LOCAL_RAG_POLICY=legacy|bounded，初始默认legacy；本地loopback:11434/v1且精确qwen3.5:9b、general profile才适用，其他provider维持既有调用。最终合格后将bounded设为该部署推荐/默认，legacy一键回滚。不是继续扩展大量组合开关。
有界RAG最终生成使用reasoning_effort=none、兼容max_tokens=2048、temperature=0.7、top_p=0.8。当前0.24原生runner只消费temperature/topK/topP/minP/seed/grammar，不消费presence_penalty，故不发送或声称该参数能抗重复；上述为官方非思考建议的受支持子集；judge离线temperature=0不变。控制调用显式no-think和256输出上限，保留原结构化协议。读取实际wire和原始响应确认生效。禁止在失败后偷偷退回无限长思考或重新生成；传输失败沿现有安全降级，取消继续传播。
同一生成提示通过DomainProfile提供：跟随问题语言；先给直接结论，再说明依据和必要条件；允许基于已给事实的可复核算术/单位换算，保留工况与版本；零值与缺测区分；逐项引用提供来源；不输出自我检查/指令分析或重复结论。不加依赖、不用已知题名/答案作业务分支。
有界策略不进行在线逐句语义模型核验，明确None/degraded；原有来源/结构/PII检查仍执行。深度检索/工具仍运行，所以不把产品深度模式等同于无上限隐藏思考。快速与深度最终生成共用同一策略/提示，避免修了一个入口漏另一个。

## State and Publication
不增加跨节点状态键；沿用grounding_faithfulness=None和confidence_degraded。最终数据必须经过现有输出检查后才能交付；发现旧main的流式路径提前发布草稿时，按最小范围缓冲到本次输出检查完成再发布，不先泄露草稿。无持久化迁移。已收到部分输出而失败时，不重启同一个模型请求拼成答案。

## Verification and Budget
先做最多8次开发机制试验（冻结4个已暴露问题，各2轮），不用冻结留出调提示。重点是零单位比较、不同工况比较、周期起算、英文缺值；核对全文事实/结论/条件/引用，重复或空答案失败。如果机制失败，依据实际输出定位实现或提示问题，不把失败策略默认启用，也不能将仅配置修复冒称整体完成。
策略稳定后以真实API对比快速/深度各两轮开发问题，再运行独立冻结4题两种模式一次；只有必要且与变更相称的对照，已有180s失败可作历史诊断但不能伪造新成功基线。新配置在同机预热下有效正文P95目标≤30s，无180s超时，生成最多1次、语义judge0次；无新实质事实/条件/来源错误。独立评审全文，不用空keywords评分。不要求格式逐字一样或每个内部judge分数更高。
单元先红：实际模型请求参数/入口一致、None≠0、开启/回滚、无二次生成。进程内JSON/SSE通过真实技能和输出护栏，不发布原始PII草稿；prompt golden在tests/fixtures。最终后端矩阵与CI；若前端依赖变化跑Playwright。main合并前确保默认选择对应实际合格配置。

## Risks and Rollback
隐式思考关闭可能影响复杂推理，因此留出包含多条件/多步问题；本任务是给定资料RAG，不能把有限验证推广为所有数学/代码任务。2048总输出可能截断长问题；length/空输出明确失败，不作为完整回答。新策略失败保留legacy，禁止测试失败后静默改裁决。local策略变更属于配置公共接口，CHANGELOG说明作用范围和回滚。第3/4步基于新单请求耗时和混合负载重新决定，不把本次修复等同于它们自动启用。

## v2 Wiring Clarifications
- 本地总策略判定由生成和Output共用，bounded时即使既有GROUNDING_CHECK_ENABLED默认true也不执行在线NLI；离线judge仍原路径。公开元数据明确None/degraded，不把None传给Output后又触发重新核验。legacy回滚恢复既有GROUNDING配置语义。
- 旧main Fast三入口此前没有输出检查；bounded为它们添加共用一次finalize（来源、结构、PII与降级标记），完成后才返回/产生SSE token。Thinking技能不提前writer草稿；经已有after-hook检查后的node最终消息才供API发布。真实LangGraph事件回归验证，不能只有harness适配器。
- 在StrOutputParser丢弃元数据前检查AIMessage/chunk的finish_reason；length或空内容作为明确失败降级，不能发布截断成功或再调一次生成。bounded同步分支绕开旧SDK length再生与LangChain fallback，外层生成重试次数也为0，客户端transport retries=0。用户取消不转换成新请求。
- 本地ChatOpenAI在最终payload序列化将max_completion_tokens映射回Ollama支持的max_tokens，防bind后再次改名；结构化control先保留tools/response_format再绑用途。测试捕获实际HTTP请求，不能只检查配置对象。
- 策略/模型/profile纳入复用边界，避免缓存旧legacy链后开启bounded仍沿旧路径。仅测试过的9B/general默认可改变；其他模型/自定义profile继续既有策略。

## v3 Single-pass Evidence-first Output
开发v1已完成8次，仅4次完整通过，失败为比较首句错误、引用及适用条件遗漏；不是继续扩大模型预算。保留原始失败记录。一次JSON生成按basis（事实/换算依据）→conditions（适用条件/限制）→conclusion（明确结论）输出，各段为text/source_ids；conclusion必填，basis至少一项，conditions允许空列表但不得省略影响结论的原始条件。前端正文由程序将conclusion放首段，然后依据和条件；不展示JSON。
source_ids是实际kept evidence的1-based编号，由调用者传入平行来源列表，不从模型文件名、去重后的来源卡或不可信正文猜测。生成前验证来源表；生成后严格解析整个结构，非空文本、至少一个有效ID，不能给无效ID补全部来源或静默删段。length、空输出、非法JSON/ID一次安全降级，不重生。JSON结构正确不代表语义正确，仍按完整结论、事实、条件进行独立实测审阅。
提示明确数量比较先统一单位，单位写法不同不代表物理量不同；先列事实与换算有助于同一次生成作出一致结论。该规则不包含具体题名/数值答案。先重复原4题2轮机制验证，通过后进行真实API多轮与既定留出。
控制调用的256预算仅绑定intent/agent/grade/rewrite用途，普通聊天保留原预算；最终RAG固定2048。全局客户端仅在本地策略生效时关闭传输重试。未通过验证前仍默认legacy。

## v3 API Contract Correction
真实API开发两轮16槽中两个英文回答正文正确但source_ids=0，被本地验证拒收；记录为失败，不改判。JSON schema中的source_ids按当前kept-set枚举1..N，避免模型用0-based编号；保持后验校验，不把0猜成1，不增加补写。max_tokens同时在LangChain bind和兼容extra_body设置，令旧/新字段同为2048（control为256），消除仅兼容字段正确而遗留字段4096的歧义。首次API准备阶段遇到旧main/历史runner目录和上传字段差异均在生成前失败，不计模型槽次。

同轮r1 Fast电池题只并列10h/9h、未明确谁更长，也判失败，故首轮API开发为13/16，不是14/16。提示补充数量比较必须给明确关系，不能仅用basis数值清单代替conclusion；允许必要数字和条件。两独立评审确认该通用修复无设计阻断，原失败保留。

## Qualified Runtime and Default Selection
实际合格引擎为0.24.0-format-backport；官方0.24.0在qwen3.5无思考时丢弃format，不能默认启用此策略。官方修复来源：https://github.com/ollama/ollama/pull/15901 ，回移仅改forceImmediate条件，保留0.24原生后端/同版GPU库。入库该patch及固定版本重建、选择独立二进制、实际/api/version检查和回滚步骤。
完成真实留出后，LOCAL_RAG_POLICY默认由legacy改auto：只有精确local9B/general及/api/version=0.24.0-format-backport选择bounded；其他/未知/不可达runtime仍legacy。每个服务端点进程内缓存版本读取（timeout1s、禁用代理），不是模型调用；配置或引擎升级后重启应用刷新。显式legacy回滚，bounded保留为已知运行时的显式实验选择。默认不把未验证0.31/new engine或其他模型一起放行。
默认模型迁移qwen3:14b→qwen3.5:9b，并同步配置示例/部署文档；已有明确LLM_MODEL不覆写。系统Ollama原二进制保留；本机切换已验证独立binary前备份服务配置，端口与模型存储保持原值，回滚仅移除本次专用override并重启模型服务。此项在留出和完整回归通过后执行。
