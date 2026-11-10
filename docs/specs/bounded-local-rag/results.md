# Results — 2026-11-10

## Outcome
完成已验证本地RAG单次作答策略，默认模型qwen3.5:9b；默认auto仅本地11434/v1、general及实际0.24.0-format-backport启用，未知版本/其他模型仍legacy。两位独立Agent分别审阅全文并允许限定默认资格；不是外部真人盲测。语义核验不在线重复调用模型，grounding=None/degraded；来源、结构和PII检查保留，检查结束才发布正文。

## Root Causes and Changes
旧调用兼容层未实际传递max_tokens、隐藏思考没有受预期预算限制；逐句NLI增加模型调用；官方Ollama0.24在Qwen3.5关闭思考时清空format；英文which/this/within误命中hi招呼，进入无预算普通聊天。仅关闭思考的提示仍会遗漏比较关系、来源或工况。
修复实际请求字段，控制输出256、最终生成2048，禁用自动重生。一次JSON生成先依据/条件再结论，程序将明确结论置首并据kept证据编号附来源。回移已合并上游格式修复，精确版本资格控制默认，修复ASCII招呼词边界。普通聊天保持原思考/生成预算。没有增加补写或judge调用。

## Runtime
RTX5070Ti 16GB；Qwen3.5:9b Q4_K_M（9.7B），模型digest为6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7，驻留显存8649499264字节；context4096、并行1。原生0.24同源后端与同版GPU库，加一处format backport；不是stock0.24。真实BGE-M3/reranker/Milvus、HTTP SSE、LangGraph和输出检查，缓存关闭、每批独立存储。宿主现有服务已是同一backport，不需要再重启或覆盖服务。

## Quality and Timing
分位数采用线性插值(N−1)q；只计算完整合格答案首段时间，拒答/超时有效TTFT=None，同时保留全槽分母。首段为通过输出检查的业务正文，不是进度提示或隐藏思考。

| Cohort | Complete answers / slots | Effective first-body timing | Other outcomes |
| --- | --- | --- | --- |
| 机制v1 | 4/8 | 不作为上线依据 | 比较、引用/条件失败保留 |
| API开发v6 | 13/16 | 不作为上线依据 | 1无明确比较、2非法来源ID |
| API开发v7 Fast | 8/8 | P50 3.188s / P95 3.931s | 4题×2轮 |
| API开发v7 Thinking | 8/8 | P50 5.669s / P95 6.009s | 同4题×2轮 |
| 首次独立原留出 | 5/8 | 不追溯改判 | 2 Fast不足答、1误路由45s超时 |
| 修复后原题回归 | 6/8 | Fast 3.316–4.695s；Thinking 4.538–7.669s | 2 Fast不足答，0超时 |
| 另行冻结的新2题 | 2/4 | Thinking 8.011/9.257s | 2 Fast不足答，0超时 |
| 默认auto冒烟 | 2/2 | Fast 3.628s / Thinking 5.878s | 未设置LOCAL_RAG_POLICY |
| 两请求混合负载 | 8/8 | Fast P95 4.750s / Thinking P95 9.167s | 2题×2轮×2模式，0超时 |

回归与新题合计8条完整答案、4次不足答；4次Fast不足答逐题legacy对照同问题/来源/文案、各0模型调用，是既有检索覆盖限制，不计成功，也未被本策略恶化。开发16条+回归/新题12槽不能说28/28答对。开发及混合零值题有把通用解释说成原文引述的措辞瑕疵，核心零值事实/条件/引用对象正确；保留Medium非阻断，不宣称逐字引述完美。

新同机legacy对照两道暴露难题×两模式×两轮共8槽：1条完整正确（首段22.150s/总24.640s），7条在30s观察窗无正文，不能用截尾值当成功延迟算提速比例。旧180s多judge实验仅作历史诊断；没有重跑大规模失败组合。当前相同8槽全部完整交付，首段约2–6s。
实际开发v7/回归/新题分别40/18/8物理模型请求，最终生成16/6/2，其余为意图、工具规划、相关性；默认冒烟5次，混合20次。可答Fast=1次，Thinking通常4次，最终生成各1次，在线语义judge=0；没有把深度模式虚报为全流程只调一次模型。所有已完成请求预算和none在真实wire验证。legacy8次开始只有2条raw可归档，其余取消前未完整返回，不能称8个完整响应。

## Step 3 and Step 4
第3步已具备稳定单请求、真实混合负载、固定预算和零judge基线，可开展有界调度/背压对照。相同两题顺序调用首段P95 Fast3.883s、Thinking6.046s；并发各1后4.750s、9.167s，表明存在共享资源干扰。但未分离精确引擎queue时间，不能将全部增幅归因排队或宣称达到原queue≥20%门槛；应用排队也可能只是移动等待位置。当前8请求35.939s均完成，不默认增加未经收益验证的调度层。
第4步继续暂缓：当前JSON结论在内部末尾，只有整份依据/条件完整后才能安全前置；提前输出片段可能被后续条件推翻。短回答2–9s尚无已验证的独立完整段落提前收益，不能仅为更早token暴露未检查内容。本次修复已经直接缩短有效正文等待，无需靠未验证的分段发布证明效果。两步决策见独立release评审。

## Verification
红绿日志涵盖实际wire预算、缺失引用/非法ID、比较结论golden、未完成/length不得重试、Fast三入口与真实Graph JSON/SSE先检查后交付、PII异常不泄露、None不伪装成0、which误路由、版本资格及默认模型。旧失败完整留档。

```bash
uv run --frozen --no-sync coverage run --branch -m pytest tests/unit/ tests/perf/ -q -m "not requires_ollama and not requires_backend"
# 1091 passed, 4 deselected
uv run --frozen --no-sync coverage run --branch --append -m pytest tests/e2e/ -q -m "not requires_backend"
# 131 passed, 2 skipped
uv run --frozen --no-sync coverage report --fail-under=60
# 74%
```

前端行为未改；CI修复阶段已通过生产npm audit(0)、构建、Playwright21 passed/1 skipped与远端Docker。开发依赖审计仍有13项，不声称全依赖无漏洞。最终远端CI与main交付写入release记录。

## Reproduction and Evidence
validation/evidence.tar.gz保留测试红绿、真实协议/完整输出/实际请求、临时probe源码和早期独立评审。只含本次合成资料及选定诊断文件，不打包模型、数据库或用户内容。解包到仓库后，使用同版已合格引擎与local-models环境，运行归档的tests/integration/run_bounded_api_probe.py；例如：

```bash
uv run --frozen --no-sync python tests/integration/run_bounded_api_probe.py --protocol docs/specs/bounded-local-rag/validation/development.json --output /tmp/rag-reproduction-new --rounds 2 --policy default
```

输出目录必须新建且隔离；历史留出协议中的旧A/B配置不是本轮wire参数，当前脚本参数与model-http为实际依据。混合负载只报告全批请求数，不能把同时变化的全局计数当每请求计数。
