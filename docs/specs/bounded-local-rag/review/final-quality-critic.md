# Final Quality Critic — Bounded Local RAG

**Date**: 2026-11-10  
**Review**: 独立逐题审阅完整最终正文、原资料/manual_required、实际生成/控制请求和原始响应；未读取当前 defender、未运行模型或测试。仅以已完成结果裁决。

## Decision

**支持本次限定默认资格**：`LOCAL_RAG_POLICY=auto` 仅在精确本地 `qwen3.5:9b / general / 0.24.0-format-backport` 生效；其他运行时/模型/profile走legacy，显式legacy可回滚。实际本机版本收据 `validation/host-runtime.json` 与合格运行时一致。此处是质量裁决，最终矩阵及提交闭环由主线程完成。

没有发现当前候选新增实质事实、条件、比较、引用或语言错误。四个 Fast 检索覆盖缺口依然存在，均不能计为成功答案；逐题 legacy 对照证明它们并非本策略造成，不能因此声称 Fast 已全面覆盖，也无需把已有检索问题变成此次默认选择的新门槛。小规模混合负载只提供后续调度诊断，不是本次新增资格条件。

## Full-answer Decisions

原4题首次运行仍保持 **5个正确回答 + 2个Fast弱检索拒答 + 1个Thinking误路由超时**，不追溯改成通过。ASCII招呼边界修复后，原4题仅作为回归；新2道英文题是另外冻结、执行后才供本评审读取的有限留出。

| Case | Fast | Thinking | Full obligation evidence |
|---|---|---|---|
| holdout_unit_conditions | weak，无答案 | PASS | 岚柯2.3 L/min=138 L/h > 砺帆126 L/h；70/110 kPa归属正确；不外推同压优劣，两来源齐。 |
| holdout_explicit_missing | weak，无答案 | PASS | 储存温度未说明；运行12–38°C inclusive；未把24 V或运行范围当储存范围，英文引用齐。 |
| holdout_version_conditions | PASS | PASS | R3.1仅屏幕汇总、不支持CSV；R3.4新增但需管理员且FAT32 U盘，升级本身不足，中文引用齐。 |
| holdout_threshold_condition | PASS | PASS | 257>240 L，不能等到第28日；17<28不推翻先到限原则，22°C属于6–32°C；正确应用用户已说明的清洁自来水情境，无需每段重复全部条件。 |
| routing_holdout_operating_modes | weak，无答案 | PASS | 14 V/31°C/无风扇允许标准模式；逐项指出高频模式电压、温度、风扇三项均不满足且须同时满足；储存范围未知，英文且来源正确。 |
| routing_holdout_capacity_export | weak，无答案 | PASS | 4×4=16而64−49=15，明确空间不足；16>15是等价完整比较，无需强制另抄65>64。导出不释放容量，先验证成功再独立手工清空，恢复64槽；Wi-Fi未知，英文引用齐。 |

本次回归8槽为6个合格答案/2个拒答；新留出4槽为2个合格答案/2个拒答。不可把6个不同问题的模式复测当12个独立问题，或宣称12/12回答成功。固定中文平台免责声明不改变英文模型正文判定；来源卡显示截短不等于模型证据截断，新两题实际生成请求均含完整原资料。

前一阶段 `bounded-local-rag-api-dev-v7` 四个开发题×两模式×两轮仍为16/16实质回答通过，旧13/16和更早机制失败保持原判。开发r2 Fast零值题曾把提示中的概括句写作资料引句，已在 `api-development-v2-critic.md` 单列引用措辞局限；本题零值/测量结论和真实来源不因此改成错误，也不宣称逐字引文完美。

## Actual Calls and Publication

- 原4题回归的18个物理HTTP = 6生成 + 4意图 + 4工具规划 + 4相关性；新2题8个HTTP = 2生成 + 2意图 + 2工具规划 + 2相关性。每个可答Fast一次生成；每个Thinking一次上述4阶段，未出现rewrite、补写或语义judge。四个弱检索Fast请求各0模型调用。
- 所有生成实际 `max_tokens=max_completion_tokens=2048`、`reasoning_effort=none`、temperature0.7/top_p0.8，控制两个预算字段均256。实际生成schema枚举与当前证据表一致，全部返回编号有效；生成/结构化控制finish=stop，工具调用finish=tool_calls，无length或隐藏reasoning正文。
- 新两题控制均真实输出rag_query（0.95），实际rag_retrieve查询保留目标对象和义务、grade=yes；生成收到完整资料与原问题，没有把manual/预期答案作为模型输入。生成后的引用和输出检查保留，公开grounding=None且confidence_degraded=true；不能描述为已通过在线语义核验。
- 完整API结果中SSE正文在最终检查后整体交付，字段记录的first_body_s因此可作为本次合格答案的交付时刻。拒答虽然也有首token时间，其**有效回答TTFT为None**；不能用于缩短成功答案分位数。

## Latency and Baseline Limits

线性分位数 `(N−1)q`，只列合格答案，同时保留全槽分母：

| Stage / mode | Valid answers / slots | P50 first body (s) | P95 first body (s) |
|---|---:|---:|---:|
| 开发v7 Fast | 8/8 | 3.188 | 3.931 |
| 开发v7 Thinking | 8/8 | 5.669 | 6.009 |
| 原4题回归 Fast | 2/4 | 4.005 | 4.626 |
| 原4题回归 Thinking | 4/4 | 5.753 | 7.390 |
| 新2题 Fast | 0/2 | None | None |
| 新2题 Thinking | 2/2 | 8.634 | 9.195 |

新两题Thinking完整请求结束为9.358/8.121s，首已检正文为9.257/8.011s，不能混用两个口径。有效答案均低于30s目标；此样本规模只支持有限本地RAG范围，不外推任意数学/代码或并发性能。

`bounded-local-rag-retrieval-terminal-baseline` 与 `bounded-local-rag-routing-terminal-baseline` 的四个legacy Fast请求，同对应候选逐题问题、返回来源和安全拒答正文一致，调用计数全0。保留覆盖不足，不把安全拒答改判成功。

`bounded-local-rag-paired-legacy-v1` 两个暴露难题×两轮×两模式的8槽：只有r1 Fast电池完整答出正确10h>9h、负载条件及引用；首正文token22.150s、最终24.640s。其余7槽在30s观察预算截尾、答案/有效TTFT=None；不声称它们最终必定180s失败，不计算全组成功P50/P95或提速百分比。HTTP计数显示8次开始，而raw归档仅2条（其中零值流无完整stop）；不能把8次开始称8个完整模型响应。当前收益证据是有界完整交付和调用数量，不能用截尾值伪造速度分母。

## Evidence Paths

- `data/eval/bounded-local-rag-api-dev-v7/{results,model-http}.jsonl`
- `data/eval/bounded-local-rag-holdout-regression/{results,model-http}.jsonl`
- `data/eval/bounded-local-rag-holdout-routing-v2/{results,model-http}.jsonl`
- `data/eval/bounded-local-rag-{retrieval-terminal-baseline,routing-terminal-baseline,paired-legacy-v1}/`
- 冻结问题/完整资料：`validation/development.json`、`validation/holdout-v1.json`、`validation/holdout-routing-v2.json`。旧holdout-v1保留最初开关实验的配置描述，本次bounded实际入口/参数以已批准bounded设计、运行结果和wire为准；未执行或宣称旧A/B日程。
