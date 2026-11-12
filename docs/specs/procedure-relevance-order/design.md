# Design

## Problem and Research
只修复合格中文流程的无关内容与首节许可后置。真实失败有两个原因：数字/截断标识及自写问题关联会选错事项；任意位置的指代匹配把准备、许可、异常并成一个难以分类的大条款。提高混合条款优先级未解决后者，不继续堆提示词。
从[Kyosuke Nishida](https://www.knishida.info/publications/)的[QFE](https://aclanthology.org/P19-1225/)借鉴问题驱动抽取，从[Nicola De Cao](https://nicola-decao.github.io/)的[GENRE](https://arxiv.org/abs/2010.00904)及[SEAL](https://arxiv.org/abs/2204.10628)借鉴可读标识。从[LlamaIndex Sentence Window](https://developers.llamaindex.ai/python/examples/node_postprocessor/metadatareplacementdemo/)借鉴细粒度单元与周边上下文分开处理；这里只改分句，不改索引或增加检索。研究任务不同，不以论文代替本地9B实测；失败实验和完整修订保存在[验证归档](validation/README.md)。

## Algorithm and Hypotheses
H1：一次JSON对“编号:完整原文”直接选择main_rule/scope/step/record/limit/omit，比数字/短前缀加自写关联更易对应真实事项。完整键集合必须匹配实际条款，不根据返回顺序或近似正文配对；分类仍可能错，schema合法不是语义证明。实验支持组合，不单独归因某一字段。
H2：程序负责展示顺序，降低模型同时概括、选取、排序的负担。main_rule/scope进入首节；只把已选step的通用明确规范及“完成才”条件前置，不恢复omit，不移动record/limit，不推导许可。不用单个“才”或实体/动作词表。各组保持来源原序，每条完整原文只出现一次并附真实引用。
H3：只用_REFERENCE.match回连句首指代；句中“该/其”等不自动吞并前句，独立许可可独立分类。句首“该次…”仍与前句合并。原句、来源及相邻上下文全部保留于同一次请求，不拆分分号条件；这不是完整指代解析器，需实际验证条件/用途完整性。

## Architecture and State
core/procedure_generation.py拥有ProcedureAnswer、动态schema、条款分组与渲染；_clause_key为共同标识来源。general.yaml是prompt唯一来源，使用已验证v17完整键原提示，拒绝v18优先级提示；core/local_rag_generation.py复用原最终生成请求。参数none/temperature0/top_p.8/2048、context4096，完整生成控制保留.7。
select与prepare共同限定中文目标；仍限已验证本地loopback9B/general、明确流程、非比较、rewrite_count=0、合格同语种资料。英文原context不预删，其它问题回原完整生成。仅既有真实reranker概率可排除极弱异语资料，缺失None不当0。
完整stop→组合原文→既有引用/PII检查一次→整体发布。Fast同步/异步/JSON/SSE和Thinking共用入口，首个正文为完整已检查回答。无新增shared_state键、REST字段、依赖或持久化；generation_evidence对应实际生成来源，不改原retrieval_evidence。

## Failure and Security
缺多键、错正文键、非法类别、无首节、非stop及引用/输出检查失败沿用不可用、confidence=None，不追加模型调用。取消/排队不变。资料仍是不可信引用，忽略其中指令，PII检查后才发布。无新增安全边界或假设性防御工作。

## Budget and Validation
分类/渲染O(条款字符总数)，完整原文回显有成本，但不增加LLM、embedding、reranker或judge调用，也不扩大2048预算。v19开发40答最大879输出tokens；相对v17平均多15.30tokens、最终生成P50多0.207秒，成本可接受，不声称这一步更快或任意长输入保证。
验收为所问事实/分支/记录用途完整、实际首节主要规则与范围、排除无关事实、已问与未问未知及真实引用；首节长度、无害标题变化不判失败，不要求每题每个分位数全面更优。按用户2026-11-12明确决定，默认门槛采用整体质量改善、关键事实无退步，允许少量首节位置瑕疵；首节指标继续单列，不改写原失败结果。v19十个暴露题两模式两轮40/40通过，旧失败留出只算开发；API首见与直接生成计时分别报告。
永久golden覆盖真实完整键分类、未问装饰/费用排除、完成条件、句内指代独立许可；单元+进程内E2E覆盖句首回连、英文原路、None降级、单调用、JSON/SSE/保存/PII。v19红2失败→绿72，20请求与生产分组/context/schema一致、40答零模型回放。未改前端；最终后端矩阵/coverage及GitHub必要UI检查执行。
冻结v19后独立作者新建3题/6资料，先做segmented_enabled/select/prepare完整资格预检，再真实API false/true各18答（两模式各三轮）。模型输出前固定问题/资料/rubric；失败保留并转开发，不反复改题冒充新留出。重复采样不当独立新题，评分只离线，既有未改英文/普通请求对照不反复调用。

## Rollout and Migration
用户在知晓新留出关键内容18/18、首节12/18后，确认允许少量首节位置瑕疵；因此选择已冻结生产v19进入默认启用验证，不采用丢记录的v20或无收益的v21。默认已改true；默认/显式false回归通过，三项配置均未显式设置的真实默认6答验证通过关键内容，完整矩阵通过。显式false仍优先，修改或移除后重启方可启用；fair调度不受影响。
[breaking] 默认启用仅覆盖上述合格中文流程；旧显式试用的英文流程回原完整生成，未扩大模型/远程API/比较/改写资格。README/API/部署示例同步范围、限制、结果和回滚。最终独立critic/defender/tracking闭环及GitHub检查后合并main；不部署到另一个含用户未提交改动的工作区。

## Explicit Acceptance Boundary
[用户验收决定](validation/acceptance-decision.md)变更的是默认门槛，不是事实结果：广播六答的待播许可仍在第二节，全文许可正确完整，记录为展示限制；不得写成全部首节修复。事实/步骤/条件/记录用途/已问未知/引用的实质退步及无关内容回流仍阻塞，v20因此继续否决。v19新留出发生在原冻结后，代码保持一致；这项用户在知情后的决策不冒充预注册的严格通过。未实施方案与完整历史保存在验证归档。
