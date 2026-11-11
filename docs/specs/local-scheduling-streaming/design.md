# Design v2

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
