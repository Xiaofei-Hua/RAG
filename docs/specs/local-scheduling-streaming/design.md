# Design — Final v5

## Final Decision
2026-11-11最终实现以v5为准：conditions→answer，比较/改写保留完整生成；前面v2及后续v3/v4章节保留设计演进。真实留出发现长流程步骤退步，第4步保持false；第3步以有界等待/取消收益默认fair。完整分母、代价与独立评审见[results](results.md)。

## Evidence and Research
2026-11-10合格基线main44d2748：Fast首段P95 3.931s、Thinking6.009s；双请求混合Thinking9.167s。实际模型流显示Fast长生成排在Thinking工具规划前，规划本身短却等待3.5–4.2s。只有HTTP端到端时长，尚不能精确拆出引擎队列，故新增实际应用等待测量。
官方可借鉴：
- [vLLM scheduler policy](https://docs.vllm.ai/en/latest/configuration/engine_args/)提供FCFS/priority；迁移的是调用优先级和公平规则，不更换本机推理引擎。
- [Ollama FAQ](https://docs.ollama.com/faq)说明并行/排队与显存关系；本机保持parallel1/context4096，避免多模型和更高显存预算。
- [SGLang structured output](https://docs.sglang.io/docs/advanced_features/structured_outputs)与[论文](https://arxiv.org/abs/2312.07104)表明grammar可约束结构；结构有效不代表语义完整，必须独立验证首段和最终答案。使用已有Ollama回移格式支持，不增加模型调用或新推理依赖。

## Step 3 — Bounded Shared Model Queue
LOCAL_LLM_SCHEDULER=off|fair，初始off，质量与资源/混合收益合格后才默认fair（仍仅bounded资格）。一个进程对已合格本地endpoint共享1个活动槽、最多8个等待项，等待上限30s。只约束模型计算，不把检索/输出检查塞进模型槽；显式sync与async共用同一调度器。
ChatOpenAI窄子类包装_generate/_agenerate/_stream/_astream，实际调用持有槽到响应/流关闭；当前锁定SDK已核对，generate与stream四入口不相互调用；各自持槽，不使用可继承的重入令牌。控制按实际max_tokens<=256归短队列，其余为生成队列。空闲即执行，不人为等候凑批；等待时最多连续2个短调用，之后让最早生成前进，等待超过2s者优先按到达顺序，防生成饥饿。不是GPU token级抢占。
Ticket由线程锁保护，async Future以call_soon_threadsafe唤醒，sync Event等待；取消/timeout与grant竞争必须原子撤销或释放已授予槽。所有异常/GeneratorExit/CancelledError走finally释放，不自动重试。不使用忙等或sleep。多worker不是全局单槽，16GB指南要求单应用worker；跨进程调度明确不在本次作用域。
记录每次queue_ms/service_ms/call_class；请求级统计用contextvar及ASGI请求生命周期，不进入messages或共享实例属性，metadata提供排队累计与模型调用数。队列满/超时在既有RAG降级入口呈现忙碌/不完整，不绕过调度回退直调；None/degraded保持。

## Step 4 — One Generation, Checked Paragraphs
LOCAL_RAG_SEGMENTED=false|true，初始false，只有bounded资格且通过真实首段/完整质量才默认开启。既有完整生成回滚仍保留。新单次JSON为evidence（简短来源事实/单位换算，内部不发布）→answer（完整CitedParagraph数组）；answer[0]必须是回答问题的明确结论，并包含所有会改变结论的工况/版本/先决条件、未知项。后段只展开依据和解释，不得补一个会推翻首段的新限制。继续2048/none/.7/.8，枚举实际kept来源编号。证据不是私有思维过程展示，而是简短输入事实提取。
增量解析只接受已完整结束的JSON对象及其真实分隔符，不补括号/修复半JSON。先读完并验证evidence，再逐个校验answer对象；所有文本非空、引用非空且在1..N。最多32KiB生成缓冲。最终仍要求完整schema与finish=stop，格式合法不冒称语义验证成功。
每个拟发布段构成累计正文，经当前GuardrailManager的来源/结构/PII/免责声明检查后只发布追加部分；检查如需修改已发布前缀则停止，不暴露新段。首段完整检查可能追加平台免责声明，之后的解释位于该已检查段后，避免重新排列已经交付的文本。来源/PII检查异常、BLOCK/ESCALATE均终止，不把raw字符串作为检查兜底。
Thinking通过GuardrailManager before-hook把当前输出检查器放在SkillContext非持久化字段中，确保使用同一配置；无该检查器时保持原完整缓冲路径。已检查最终正文在SkillContext留下请求级receipt，after-hook仅对相同已检查正文避免重复改写。Fast复用同一检查组件。receipt不进入messages/shared_state，也不从用户输入反序列化。
流式状态为pending→partial→complete|incomplete|cancelled。无已发布段时失败返回固定安全文案；有已发布段时追加固定“不完整”提示、metadata.generation_complete=false，保留None/degraded，不能当正常成功样本。无重生成，无后续原文泄露；停止/断连传播取消并关闭模型流。GenerateSkill使用PARTIAL状态，Fast done带明确状态，API与UI保留部分正文并显示未完成。token拼接=done.full_response=已保存正文；取消不保存成功回答。
同步/非流式入口复用同一schema/渲染规则并等待完成；不会把增量接口返回值误当完整答案。源正文及检索范围保持现有kept-set。

## Contracts and Failure
新增配置与metadata属公共契约，CHANGELOG标breaking及回滚。SkillContext新增仅请求级非持久化检查器/receipt；新增的终态键按下节声明唯一生产者，均走shared_state浅合并。默认单进程调度不伪称跨worker全局。不改CORS/auth/上传/网络边界；安全影响仅已涉及的PII检查后发布与生成中断。每段检查完整文本，跨chunk隐私片段需完成段后再验证，新增段导致旧前缀需脱敏时拒绝发布新增部分。
可用性失败不计质量0；没有证据仍为原安全终态。后续段落语义矛盾无法靠JSON静态证明，真实独立评审必须分别检查首段/全篇；不能要求自由文本数学保证，也不能用“结构已验证”偷换“事实已核验”。

## Experiments and Acceptance
先做已暴露4题的两轮机制对照，验证新schema首段条件/比较/引用，再做真实API快速/深度两轮。固定新策略后由独立reviewer冻结至少2道未暴露多条件问题；失败保留记录，针对归因修复，不反复消费留出。
调度对照保持prompt/证据/采样/模型一致；2+2模式混合与取消/队列上限分别测量，记录全部请求分母、accepted/completed/aborted/busy、有效首段P50/P95、总完成时间/吞吐、真实模型调用和queue_ms。目标混合P95或吞吐改善20%，模式P95不恶化>5%是观察目标而非要求所有指标全面更优；若无调度吞吐收益，只有实测取消/等待上限收益可单独支持部署，不伪造加速。
分段目标有效已检首段P50较完整输出降低30%，全篇事实/结论/条件/引用无新增实质退步；新题首段本身完整，不用证据摘录或状态提示冒充答案。两步分别消融，组合复核小规模混合，不改变原有Fast覆盖缺口分母。
单元红绿：统一sync/async槽、FIFO/短调用公平、队列满/超时、取消grant竞态、流异常/close释放、请求统计隔离；JSON任意chunk切分/转义/非法ID/PII跨chunk/length/半对象不发布；首段先于模型结束；后续异常partial一致。E2E用真实Graph+router+guardrail、mock模型网络，覆盖JSON/SSE与断连；Playwright验证多段逐步展示/未完成标识/停止，无实际模型依赖。最终完整矩阵、独立代码与全文评审、CI按main保护依次合并。

## Documentation
更新所有维护中的相关README（根、models/core/agent/skills/web/tests）、HTTP API/SSE、部署/配置/架构与性能说明、CHANGELOG和AGENTS中与当前代码不符的事实。旧spec/旧实验作为历史保留，通过新结果链接标记后续，不把旧失败改成通过。文档以实际代码和验证为准，不将旧集成分支未合并功能写成main现状。

## v2 Review Closure
F-01 / D-02：GenerateSkill唯一生产shared_state["generation_outcome"]整键，值为{status:complete|incomplete|unavailable,generation_complete:bool,reason:str|None,retryable:bool}；success、partial和所有清空/拒答/错误终态都覆盖写，避免跨轮旧值。FastModeResult及stream done提供同义字段。API显式读取（包括Fast done，不能只取sources），写入JSON/SSE metadata、保存的AIMessage.additional_kwargs及评测capture；跨节点只走shared_state，保存消息字段只是最终持久化，不充当Graph通信。历史接口读取保存metadata，使未完成状态重开会话仍可见。receipt/检查器继续仅在SkillContext，不持久化。
F-02 / D-01：ModelBusyError明确区分queue_full/queue_timeout。classifier、agent、grade、rewrite以及BaseSkill timed wrapper必须专门向请求入口传播这一内部终止信号，不进入原有retry/0分fallback。API在intent拒绝时返回安全busy JSON或SSE终态（confidence=None，generation_complete=false，retryable=true），不再路由；Fast直接入口转同义安全结果。Harness四入口在graph边界捕获busy并终止该次graph，转换安全状态/stream终态；不得继续调用下一模型。Harness唯一生产model_queue_outcome整键，并在_build_request_shared_state清旧值；API在缺generation_outcome时读取该键。两个命名空间不争用。暂停/取消异常独立传播，不能当busy吞掉；没有“报满后绕过调度直调”路径。
D-03：不使用contextvar重入token，仅请求统计使用contextvar；四个真实SDK入口各自持槽直到关闭。
D-04：evidence只保留决定结论的原始事实、必要单位换算和限制，避免复述全文；机制实验记录evidence字符/实际生成token数和截断，不能为缩短首段丢事实。至少两个新题审首段全部条件与最终答案。
测试分配：队列饱和Thinking HTTP JSON/SSE、捕获实际模型请求数0且confidence None，classifier不重试；Graph生成半途失败公共metadata/历史保存/capture一致；所有新键归属表同步agent/AGENTS.md。以上闭合载体和忙碌终态，不扩大架构/实验。

## v3 — Evidence from the First Mechanism Trial
真实两轮4题对照各8次、每答1次模型调用；buffered首段P50=3.429s，segmented=2.976s（下降13.2%，未达到30%观察目标）。v1一个比较答案将不可外推条件留在第二段，另一个校准答案漏掉正常连续使用限定，不能默认开启。失败原文保留于local-stream-mechanism-v1，独立评审审全篇。
最小修订：单次JSON字段改为evidence→conditions→answer。conditions为所有影响结论的条件/版本/起算/未知/不能外推限制的独立CitedParagraph数组（无则[]）。先校验完整evidence和conditions；首个answer对象完成后，程序将结论与已生成conditions合成同一个首段，一起经过既有检查再发布。后续answer只能解释，不得新增改变结论的条件。这样不靠模型自行把条件搬到array第一个text，仍不增加模型调用或语义判分。同步/非流式使用同一合成规则。evidence只写必要原始事实和换算，条件专属conditions，减少重复。静态结构仍不能证明条件提取完整，真实对照与新题仍检查这一点。
收益按实际报告：30%为初始观察目标，不因未达目标扩大模型调用或降低质量；若首段P50/P95有可测收益、调用数不增且无实质质量退步，可据此判断启用。完成率与延迟分母继续报告全部槽位。

## v4 — Remove Redundant Output Work
v3机制两轮16答：首块条件恢复，critic未见新增数值/起算/版本/全文实质退步；但buffered首块P50=3.263s，segmented=3.620s（慢10.96%），7/8只有一个答案块。已观察到输出evidence复述与时延增加，待消融检验其贡献，再写conditions和answer，短答案没有足够后文可提前释放。不能用“支持分段”冒称加速。
最小v4假设：已有模型输入的kept evidence表完整保留，删除模型输出中的evidence数组，仅生成conditions→answer。conditions仍先完整生成和验证，与answer[0]原子合成首段；实际引用枚举、完整JSON/finish、当前输出检查、部分终态均不变。数字事实及必要换算直接写入结论或必要解释，不额外让模型重复一份内部事实摘要。零额外模型调用、无隐藏思考放宽、无语义检查取消。可能损失显式计算准备的质量，因此只以同4题两轮最小对照验证，若质量保持再冻结新的独立留出，未通过不默认开启。
这是一项针对已观察到重复输出（57–105字符；流式usage未返回token计数）与时延的消融，不改检索范围/证据/控制调用/采样/总预算。v1、v3失败记录完整保留，真实收益按首块质量合格与全部槽位分别计算。

## v5 — Adaptive Release, Preserve the Qualified Comparison Path
v4同题两轮各8次：原始首块P50 3.364s→1.794s，但R1比较只列9h/10h而没有直接断言谁更长，质量未合格，不以46.7%冒称最终收益。已复现9B在省去事实准备后的比较结论稳定性边界。
最终最小策略：比较/等值/差值/倍数问题继续使用已合格的bounded完整生成（basis→conditions→conclusion，输出前统一检查），其他问题使用conditions→answer精简分段。用本地确定性中英文比较词识别，保守多选只影响加速覆盖率，不增加模型调用；不引入分类模型。各Fast sync/async/stream、Thinking sync/async入口按同一函数根据问题选策略。比较题不尝试先发布不完整结论，也不做生成失败后的二次模型修复。输出budget/采样/证据不变。
这是明确的质量优先适用范围，不声称所有题型都更快。既有比较路径已在基线与本轮buffered多轮通过，保留该能力；最终组合仍需两模式两轮API对照与新留出。保持未通过默认false。验证增加比较识别和实际schema回归，质量对比按全题计算，收益同时给出分流覆盖数及整体/各模式分位数。先前v1/v3/v4失败均保留。

v5接线限定：Thinking发生过rewrite（rewrite_count>0）时保守使用bounded完整生成，因为末条HumanMessage可能已被改写掉比较词。无需新增状态或模型；Fast无rewrite。同步generation_chain与异步Generate分段分支统一传入现有rewrite_count，并加丢比较词的回归。
