# Design v1

## Evidence and Hypothesis
当前本机实测正文37–38秒生成，此后核验仍用123–128秒；并发/批量/换核验器未解决正确性，见本地readiness历史grounding-structural-headings/legacy-outline-results.md和bounded-grounding-pass/validation/results-v1.md。这些历史实验不随本小PR复制入GitHub。
现有配置本已允许关闭语义核验，但只有OutputGuardrail读取它，GenerateSkill直接调用的GroundingGuardrail未读取。修复这条不一致，消除关闭配置时的全部online judge调用，比继续增加提示/专用模板更直接。它不保证答案语义正确，也不把未核验当核验通过。

## Implementation
在agent/guardrails/types.py将enable_grounding_check改为field(default_factory=...)，仍使用已有_env_bool规则及默认true，使新建配置读取当前环境，防模块导入时冻结旧环境。实例内显式GuardrailConfig(enable_grounding_check=...)语义不变。
GroundingGuardrail的同步check/异步acheck在judge获取、声明提取、空资料判断之前共享相同的环境开关判断；false返回GroundingResult(None,degraded=True,reason="disabled")。当前集成版本两入口已有共用_prepare，可在_prepare入口做同一判断；GitHub main旧版在两个公共入口做对称判断。没有新增模型、状态键、依赖、持久化、prompt或env语义。
关闭的结果继续经过GenerateSkill的None置信度降级逻辑。当前集成版本已有grounding_assessment及强制输出发布门禁，保持原生None/unknown语义。GitHub旧版本仅返回其已有None/confidence_degraded语义，不能宣传新收据或检查后流式发布等未回移功能。
OutputGuardrail仍由原配置控制语义分支，来源/结构/安全/PII开关不变。本PR不把设置GROUNDING_CHECK_ENABLED=false解释为关闭所有护栏，也不修无关的旧main流式发布架构。关闭语义核验是明确可选策略，默认仍true。离线eval/judge.entail不受影响，仍可供评估。

## Validation
1. 单元红：false/0/off/no及sync/async/模块wrapper均不允许触碰judge；现状实际触碰即可失败。新配置实例在import后能读取环境，显式实例覆盖仍有效。true/未设保持调用并返回真实结果；禁用永不返回0/1。
2. 单元绿：same skill sync/async生成仍调用一次，核验0次；confidence_degraded=true；输出PII仍脱敏，错误来源仍标记。不开启该配置时既有grounding测试保持通过。
3. 进程内E2E：client fixture，真实GenerateSkill与输出检查，mock模型/检索单例，/api/chat和/api/chat/stream两入口；检查完成状态、来源、None/降级、无NLI调用，不能由仅调用helper代替API验证。集成分支检查后发布沿用既有回归；旧main不宣称新增发布契约。
4. 真模型：当前集成版本相同qwen3.5:9b/Q4_K_M/全GPU/4096和已合格CONTROL配置，A=GROUNDING_CHECK_ENABLED=true，B=false；所有其他flag与prompt不变。冻结4开发题，两轮AB/BA，再冻结4独立留出一轮。总24个Thinking QA上限；Fast仅做不受影响的回归，不额外重复未改路径的大矩阵。将实际call、有效正文TTFT、完成时间、事实/比较结论/条件/引用/语言/未知字段单列。judge分数不同不是回退判据。
5. 只有有效配对计算延迟比；A超时有效TTFT=None，B正确交付作为恢复可用性，不用180秒伪造成功基线。B新实质错误则停止资格，修复代码仍可作为默认不变的配置bug修复交付，配置不默认启用。试验结果不把有限样本推广成通用质量保证。

## Review and Delivery
独立critic/defender并行，先修必要问题再编码；本次只修实际失效的开关与配置读取，不扩展为规则引擎或新安全平台。修改规模目标业务<40行；测试与三段文档、结果、评审总体PR<800行。
远端main比当前集成落后169提交。为避免把大量历史实验混入PR，发布工作树RAG-grounding-switch从origin/main建立fix/grounding-disable-hotpath；同一修复在RAG-readiness按其现有接口适配并验证，主RAG未提交更改保持原样。不force push，不直接改main。

## Rollback / Safety
回滚代码或设GROUNDING_CHECK_ENABLED=true，默认就是true。无数据迁移或依赖变更。被禁用的是可选语义核验，已有来源/PII/权限边界不变。若配置解析/检查失败，保留现有热路径None降级，不吞取消；新路径不引入异步任务。该修复不承诺解决全部生成错误、第3/4步也不据此自动启用。

## Clarification

全局env=false优先于显式Output config=true；field factory保留显式字段值，但不允许越过在线核验总开关。既有配置实例不随环境自动重载。
