# Results

本文评估冻结的最终候选；Stage 1只提交纯函数机制，Stage 2接入Fast/Thinking后才提供显式试用。

## Release Decision
修复以默认关闭方式交付。核心步骤/条件/记录/用途：开发流程1/8→8/8，新留出候选12/12完整；但新留出严格整题仅6/12，存在被改路径真实配对退步，不能默认启用，也不能声称第4步全面验收通过。第3步fair调度保持默认；LOCAL_RAG_SEGMENTED仍false，true仅供明确接受下述限制的试用。
中文留出六答都带入绿色墙钟与18本年鉴；视觉首节未按问题先交代交接完成才可阅览（后段存在）。英文六答完整，但有无害重复。新留出未用于继续改提示或重测择优。严格要求的动作/条件/用途没有降低，ID合法不当质量通过。

## Mechanism and Cost
瓶颈是自由概括丢动作和触发关系，以及已测极低相关异语背景干扰选择。新机制同次选择/排列条款，保留原文、真实来源及指代上下文，完整stop后统一检查发布。流程temperature=0，其他生成仍.7；2048/top_p.8/none不变。没有新增模型核验、翻译、重生成或reranker前向。
两模式来源同步到实际送入模型的证据；缺分/高相关异语不删除，回原完整生成。普通/比较/改写继续GroundedAnswer。首个正文事件等于完整答案，以下收益没有把未检查前缀或占位提示算作首段。

## Real-model Comparison
RTX5070Ti 16GB，Qwen3.5:9b Q4_K_M，Ollama0.24.0-format-backport，context4096/parallel1；模型约8.65GB显存，整卡约9.50GB。真实上传、BGE-M3检索、reranker、Fast/Graph、输出检查、HTTP SSE全链路，缓存关闭；运行时记录随证据归档。
开发六题×两模式×两轮，每侧24答。流程8答；普通16答的实际最终请求逐字段相同，双方严格15/16，候选整批23/24、基线16/24。普通比较有一条通过→失败，另一条改善；保留原路径随机波动，不用总分抵消，不宣称全系统无退步。
候选冻结后，由独立评审者创建中英各一新流程（三轮×两模式），每侧12答。全体严格基线1/12、候选6/12；中文R3 Fast基线通过而候选因无关信息失败，明确拒绝默认资格。原始题目/完整答案/请求与逐答critic/defender报告均归档。

| Scope / mode | N per side | First complete body P50, baseline → candidate | P95, baseline → candidate |
|---|---:|---:|---:|
| Development procedures / Fast | 4 | 7.927s → 4.096s | 9.541s → 4.307s |
| Development procedures / Thinking | 4 | 12.895s → 7.469s | 15.158s → 8.653s |
| New holdout / Fast | 6 | 11.257s → 4.049s | 18.295s → 4.717s |
| New holdout / Thinking | 6 | 15.261s → 7.119s | 15.622s → 8.690s |

留出最终生成的输出token由13,172降至3,504，节约约73%；用户正文由所选原文组成，未用少答步骤换取该收益。调用成本两侧相同：Fast每答1次最终生成，Thinking每答3次原控制+1次最终生成；开发每侧60次，留出每侧30次。没有超时/非stop/无效来源；全部正文一次发布，done与正文一致。无效结束/检查失败另由确定性回归验证，不能因本批无失败而删掉降级契约。
小样本、分批运行，不外推普遍尾延迟改善；开发普通Fast P95由4.022s到7.236s，未改路径仍有波动。温度0重复输出是稳定性/两入口验证，不是独立随机样本或统计显著性证明。

## Validation
- 核心接线红17失败→绿49通过；资格/范围修正红→绿；实际背景去除红5失败→绿69通过，均为固定失败输出/请求契约测试。
- 最终 `uv run --frozen --no-sync python -m coverage run --branch -m pytest tests/unit/ tests/e2e/ tests/perf/ -q`：1313 passed、6 skipped；3个既有warning。`coverage report --fail-under=60`：75%。
- Golden diff：新增流程原文、选择schema/prompt与预期全文；旧非流程API fixture改为原完整schema，保留JSON/SSE、PII、来源、终态和历史一致性验证。
- 本轮无前端代码变化；GitHub必需test/e2e-ui/check通过后合并，实际提交与交付见review/tracking.md。

## Evidence and Reproduction
`validation/evidence.tar.gz`保存所有v1–v6失败/成功、原始JSONL、协议、逐答评审、历史设计、红绿/全矩阵日志及测试适配器；不含运行数据库或凭据。`validation/final-development-metrics.json`、`holdout-metrics.json`为原始记录计算的汇总。解压后按归档路径阅读，不把早期逐段首发指标与本次完整首见混用。
实验适配器在归档tests/integration中，复跑前恢复到tests/integration，使用隔离存储/同一限定模型服务：`uv run --frozen --no-sync python tests/integration/run_bounded_api_probe.py --protocol <protocol.json> --output <new-dir> --policy bounded --scheduler fair --segmented false|true --rounds 3 --modes fast,thinking --timeout 45`。默认false；本次不继续针对已暴露留出调提示。后续需要证明相关性选择及首节顺序的改进能泛化，再另冻新题评估默认资格。
