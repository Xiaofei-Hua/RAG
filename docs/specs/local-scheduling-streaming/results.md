# Results — Local Scheduling and Checked Publication

## Decision
2026-11-11：第3步在已合格本地bounded运行时默认`LOCAL_LLM_SCHEDULER=fair`；第4步已实现，但`LOCAL_RAG_SEGMENTED=false`。分段在开发集有收益，新留出长流程有实质遗漏，不能默认启用。两个开关可独立回滚，无新增在线模型核验或生成重试。独立[critic](review/critic.md)与[defender](review/defender.md)同意此决策；工程发现闭环见[tracking](review/tracking.md)。

第3步解决的是无法约束的并发等待、取消和过载重试，不声称大幅提高GPU吞吐。第4步的结构/引用/PII检查只保证发布契约，不能证明语义完整。检索弱证据拒答、协议完整、答案质量分别计数。

## Runtime and Method
RTX 5070 Ti 16GB，qwen3.5:9b Q4_K_M（模型digest 6488c96fa5fa），Ollama 0.24.0-format-backport，context4096/parallel1/max_loaded1，BGE-M3及reranker；输入证据、2048最终预算、none/.7/.8采样保持一致。服务使用独立网络命名空间，主服务和用户数据未改动。资格边界见[部署说明](../../deployment/BOUNDED_LOCAL_RAG.md)。
开发4题含异负载续航比较、零值等值、校准起算和未知价格。每模式每题两轮；新留出由独立defender于2026-11-11T05:30:44Z冻结，包含多条件流量比较和英文多步骤扫描器维护。冻结后没有按留出答案调prompt/分流词。所有问题、完整答案、实际HTTP请求、失败和日志保存在[归档](validation/evidence.tar.gz)；清单见[INDEX](validation/INDEX.md)。

首段时间为真实API请求至首个已检查正文token，不计status/reasoning/拒答。分位数为小样本描述值，不是置信区间或服务SLA。调度统计是应用内累计等待/服务与逻辑SDK调用；HTTP捕获单独统计实际调用，均不是GPU kernel时间。未启用调度时缺失等待值不当作0。

## Step 3 — Mixed Load and Capacity
同一原bounded prompt，2 Fast+2 Thinking并发、2题、2轮，各16槽位，40次实际HTTP（24控制+16生成）。两边协议完成16/16，critic整题语义各14/16：off两答比较未明确谁更长，fair两答校准遗漏正常连续使用限定；提示/参数未改，不能据此归因队列影响语义，也不能称质量16/16。

| Metric | off | fair |
|---|---:|---:|
| Batch elapsed | 73.895s | 72.686s |
| First body P50 / P95 | 11.753 / 18.832s | 12.044 / 18.182s |
| Fast P50 / P95 | 7.452 / 9.398s | 7.377 / 9.662s |
| Thinking P50 / P95 | 16.222 / 18.900s | 16.459 / 18.771s |
| Application HTTP inflight peak | 4 | 1 |

总时长下降1.64%，未达到原20%观察目标；各模式尾延迟变化小，没有稳定吞吐提升依据。fair请求累计排队P50/P95为6.801/12.445s。
容量实测：一个模型流占用时，10个等待请求中8个排队、2个queue_full；取消8个均清除。单独等待请求30.030s返回queue_timeout，没有绕过队列增加调用。释放后短请求0.131s完成。该容量测试主动持有流，用于验证队列上限，不是引擎速度测量。
真实生成取消：收到非空正文“整理”后取消，应用槽0.000543s释放，后续短请求0.154s完成，活动/等待均归零。这是应用释放测量，不声称GPU kernel同步停机。上述有界等待/取消证据支持默认fair，单应用worker限制保留。

## Step 4 — Ablations and Final API Comparison
每项机制试验4题×2轮，每侧8答、每答1生成；以下所有失败均保留。

| Trial | First-body P50, baseline → candidate | Quality finding | Decision |
|---|---|---|---|
| evidence→answer | 3.429→2.976s | 首段6/8；比较限制晚到、校准工况遗漏 | 拒绝默认 |
| evidence→conditions→answer | 3.263→3.620s | 候选8/8，但更慢，7/8仅一块 | 拒绝默认 |
| conditions→answer, all questions | 3.364→1.794s | 候选7/8；比较只列数值无赢家 | 拒绝默认 |
| adaptive final v5 | 见下表 | 比较/改写保留原完整生成，其他题分段 | 进入冻结留出 |

最终开发API对照两种模式×4题×2轮，每侧16答，双方独立评审首段/全篇16/16；实际HTTP均40次。候选8答原schema、8答精简schema，未增加调用。

| Metric | Buffered | Adaptive opt-in |
|---|---:|---:|
| Overall first body P50 / P95 | 4.200 / 6.017s | 3.793 / 6.288s |
| Fast first body P50 / P95 | 3.206 / 3.702s | 2.771 / 3.969s |
| Thinking first body P50 / P95 | 5.598 / 6.066s | 5.447 / 6.437s |
| Whole response P50 | 4.259s | 3.947s |
| Batch elapsed | 69.237s | 64.287s |

整体首段中位数改善9.69%，P95慢4.50%；精简覆盖子集8答P50改善20.47%。前一失败机制的46.7%不能作为最终API收益，分段默认关闭也意味着这些不是默认用户加速幅度。

## Frozen Holdout and Default Gate
每侧8槽位、18次HTTP（12控制+6生成）。双方2个Fast流量比较槽位均为weak检索终态，不能计生成成功；Thinking流量比较2答保留原schema、结论与条件正确。
扫描器维护4个候选答中，Fast两轮换头校验通过后重置37 active hours的表述不够明确，基线Fast也已有准备/记录遗漏。明确配对退步在Thinking第2轮：候选遗漏指定参考纸准备及保留失败校验记录，而对应基线保留；第1轮候选覆盖主要步骤且确实提前发布两段。引用编号合法和finish=stop不能修复步骤遗漏。
因此第4步默认false，保留显式试用；本轮不继续在已看过的留出题上调参。6个生成答的原始P50 8.638→5.670s、总时长52.105→35.429s包含质量失败，不能作为合格收益。若未来推进默认开启，先针对长流程证据覆盖做无额外调用的小实验，再重新冻结独立留出；不要求所有延迟指标全面更优，但明确结论、关键条件、步骤与引用不能新增实质退步。
最终实际默认（auto/fair/false）冒烟2/2、5次HTTP；显式fair+分段混合复核4/4、10次HTTP（6控制+2原schema+2精简），不改变留出否决结论。

## Validation
最终完整后端：1274 passed、6 skipped、3已有warning，分支覆盖74%；浏览器全套23 passed/1 skipped，新增history后分段3项重跑全部通过，去重24 passed/1 skipped。构建通过，23个改动Python文件ruff检查/格式通过。

```bash
# 已同步环境；隔离网络且清除代理，避免依赖安装测试继承外网代理
PYTHON_DOTENV_DISABLED=1 EMBEDDING_PROVIDER=api MILVUS_SPARSE_INDEX=false uv run --frozen --no-sync coverage run --branch -m pytest tests/unit/ tests/e2e/ tests/perf/ -q
uv run --frozen --no-sync coverage report --fail-under=60
npm run build
./node_modules/.bin/playwright test --config=web/playwright.config.ts
./node_modules/.bin/playwright test --config=web/playwright.config.ts tests/e2e_ui/segmented.spec.ts
# 真实API复现：探针源文件、开发/留出协议及环境记录均在归档中；输出必须是新的隔离目录
uv run --frozen --no-sync python tests/integration/run_bounded_api_probe.py --protocol docs/specs/bounded-local-rag/validation/development.json --output data/eval/new-baseline --scheduler fair --segmented false --rounds 2
uv run --frozen --no-sync python tests/integration/run_bounded_api_probe.py --protocol docs/specs/local-scheduling-streaming/validation/holdout-v5.json --output data/eval/new-holdout --scheduler fair --segmented true --rounds 2
```

红绿证据：queue-red→queue-green；admission-red/generation-busy-red/cleanup-red-v2→admission-green-v2/step3-ci-env-corrected；segment-red/sdk-stream-red/stop-contract-red/adaptive-red→segment-green/adaptive-green；segment-api-red→segment-api-green-v3；default-admission-red→green；ui-red-v2→ui-green/ui-final。最终完整日志final-backend.log覆盖全部后端修复。
早期full-backend-v1因未安装pytest-cov使用了不支持参数；改用已有coverage。step3五项环境失败来自隔离namespace继承代理，清除代理后同测试16通过；full-backend-v2的fallback fixture缺astream，修复替身后定向10通过并完成最终全量。queue-capacity-v1是探针未等拒绝结果的竞态，修订探针同步后v2通过，未据此改产品队列。保留失败日志，不将环境/fixture失败伪装成产品红绿证据。

## Documentation and Delivery
维护文档已同步：根README/CHANGELOG/AGENTS、agent/core/web/tests契约、agent技能总览及agent/generate/grade/retrieve/rewrite说明、tests README、API/SSE/history、部署总览/本地有界/WSL/裸机/开发/离线/运维/API-only指南、四个环境示例、spec索引和技术报告。不存在的models/core/web README不新造；MCP接口未改，旧spec/14B实验保留历史标识与后续链接。
实现分阶段提交：队列32da0f0，忙碌终态30e4fe5，分段解析16ab3e2，接口/UI a40d4a0，默认资格与维护文档a71a885。PR必须通过test/e2e-ui/check后合并受保护main，不绕过保护。归档仅含本轮合成语料、模型请求/答案、测试日志、探针和UI截图，不含运行数据库或用户配置。

## Procedure Follow-up

2026-11-11步骤遗漏修复与新的独立留出见[后续实验](../segmented-procedure-coverage/results.md)。此处历史失败不改判；第3步fair继续默认，第4步仍false。

## Follow-up

中文相关性与首节的后续修复、当前默认资格及真实对照见[后续结果](../procedure-relevance-order/results.md)。本报告原始失败与历史默认不追溯改写。
