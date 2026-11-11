# Design

## Problem and Research
基线 main f7984fe 的真实请求已含准备、记录和失败处置，却在自由概括时丢失步骤、目的或把换件起算推广到普通复查。先后提示强化、先选依据再改写、显式负选择均实测失败；完整历史与原始失败保留在 validation/evidence.tar.gz，不以新版判据重判旧失败。
从[Lei Wang主页](https://demoleiwang.github.io/HomePage/)追踪[Plan-and-Solve](https://aclanthology.org/2023.acl-long.147/)与[实现](https://github.com/AGI-Edgerunners/Plan-and-Solve-Prompting)，从[Attribute First, then Generate](https://aclanthology.org/2024.acl-long.182/)及[实现](https://github.com/lovodkin93/attribute-first-then-generate)借鉴阶段组织与细粒度归因。只迁移选择/排序的思想，同次调用完成，不移植多次生成；论文不直接证明本地9B效果。[CrossEncoder接口](https://www.sbert.net/docs/package_reference/cross_encoder/model.html)及本机实际Sigmoid解释了原分数量纲；条款阈值实测不能区分必需信息与包装句，故未采用。

## Strategy and Eligibility
假设：将最终任务改为选择、排列资料条款，直接用所选原文组成答案，减少自由改写漏步及生成token。仅 general、合格本地Qwen3.5:9b bounded、未改写、非比较且明确要求步骤/流程/how to/sequence 时适用；bare如何/How do解释题不进入。中文或英文资料必须满足保守同语种资格，跨语/混合/不确定在调用前回原完整GroundedAnswer。
已实测极低相关异语背景会让Fast漏选记录用途。因此只有同语种至少一份已测概率≥.9、全部异语都已测≤.01时，才从实际生成证据中移除异语候选。概率必须来自实际Sigmoid的rerank_score与rerank_output_space=probability声明；None/未知量纲不作0，不改全局评分及既有消费者。存在高分/缺分异语时原集合整体保留并回完整生成，不部分筛掉可能依据；同语种干扰仍由模型选择。
按句子/换行编号，在同来源内将显式指代句并回前句，保留触发事件。该规则不等于通用指代消解。模型一次生成title+clause_ids，conditions固定空数组；程序按真实来源映射合成阶段正文，不追加未选原文或第二份摘要。标题、排序和选择仍可能出错，ID合法不代表语义完整。
流程选择temperature=0，其余生成=.7；均保持top_p=.8、reasoning_effort=none、2048预算。等同一次JSON正常stop并完成全文后，经过既有引用/PII/output checker一次，整体发布；不提前暴露不完整操作前缀，不增加核验、翻译、重生成或模型前向。完整首见是本次性能指标。

## Architecture and State
Fast三个入口在prepare_evidence前预选，context/kept_documents/sources来自同一集合；Generate在既有_prepare_generation_evidence所有者边界处理，并整键写generation_evidence/retrieved_contexts/sources。原retrieval_evidence和diagnostics不变，无新shared_state键、REST字段、持久化。来源映射用结构化证据，不解析正文伪标题；历史只替换原完整资料块，其余保留。
core/procedure_generation.py负责资格/条款/渲染；local_rag_generation负责单次schema/请求；segmented_generation复用完整生成链和输出检查。Prompt由general profile单源派生。比较、rewrite和非流程仍原完整schema；取消、单槽队列、busy透传保持。无效ID/非stop/检查失败返回固定不可用、confidence=None，不泄露未检查原文、不补调用。资料仍是不可信内容，原文也经过PII检查；安全边界未扩大。

## Validation and Decision
旧公开留出退为开发题。机制实验保留全部失败：v1 0/6、v2 1/6、v3 0/6；原文选择v4 6/6，负选择v5 0/12，温度0的v6 12/12（.7对照6/12）；重复输出不冒称独立随机样本。最终开发六题×两模式×两轮，false完整生成对照true有限流程；新独立中英各一题×两模式×三轮，候选冻结后才建题，不能用留出调提示。每答离线审查全部动作、条件、顺序、目的、未知边界、引用与无关内容；原始HTTP及API记录可重查。
质量门槛是被改有限流程无新增实质退步、复现修复、调用不增，且完整首见中位数有收益；不要求所有分位数全面更优。开发流程1/8→8/8，普通题两侧各15/16、候选整批23/24，有一条配对下降。16个非流程实际请求逐字段与基线相同，保留此原路径波动，不为追求逐答随机全胜修改无关prompt，也不称全系统无退步。独立新留出仍决定有限默认资格；出现流程退步不得用总分抵消。
确定性矩阵包括sync/async单调用、原文与来源golden、事件指代、未知/高分异语回退、同源多chunk、完整stop/无效ID/输出检查失败、PII、Fast/Thinking JSON/SSE/done/history一致。测试只进tests。定向红绿后跑完整unit/e2e/perf与coverage；无前端改动，沿用UI回归与CI检查。具体命令、实测与样本局限见results.md；实验规模有界。

## Rollout and Compatibility
[breaking] LOCAL_RAG_SEGMENTED=true的语义收窄为合格流程的完整条款选择，旧非流程逐段生成不再随该开关开启。false仍完整生成回滚；新留出核心覆盖12/12、严格6/12且有真实配对退步，故默认继续false；相关性/视觉首节顺序未修复，以关闭隔离，不能声称默认资格通过。LOCAL_LLM_SCHEDULER=fair独立保留；普通API/其他模型不扩展范围，单应用worker/Ollama parallel=1/context4096。
提交按独立可合并阶段控制规模：先新增条款机制及纯函数契约（尚未接入默认路径），再接入两模式、API回归及更新操作文档。每阶段独立测试并通过GitHub检查；最终评审tracking用实际修复提交闭环。回滚false并重启应用即可，旧显式false配置仍保留用户选择。
