# Runtime Compatibility — Independent Critic

Date: 2026-11-10。只读既有回移patch、构建记录、源码与当前部署脚本，并联网核对官方v0.24.0源码/PR。未启动服务、GPU、模型、测试或构建。

## Conclusion

**本轮资格必须限定到0.24.0-format-backport，不能推广为官方未修补0.24的默认资格。** 这是已复现、直接影响本次JSON schema/来源enum的运行时前提，不是新增防御平台。后验拒收仍安全，但官方旧路径可能无约束地产生无效编号/结构，不能假定具有当前交付可用性。

官方[固定v0.24.0 routes.go](https://github.com/ollama/ollama/blob/v0.24.0/server/routes.go)在chat路径仅为gemma4+think=false设置forceImmediate。Qwen3.5虽接受format字段，初始currentFormat仍被清空；无思考时又没有“思考→正文”转换触发后续格式约束。因此问题不是“0.24完全没有JSON schema实现”，而是本次模型/模式的路由没有启用它。[上游PR #15901](https://github.com/ollama/ollama/pull/15901)正是把该特判扩展到支持思考的builtin parser，并覆盖Qwen3.5。

本地既有`ollama-structured-output-runtime/validation/native-format-backport.patch`只改该条件；当前源码`server/routes.go:2498–2508`保留format交给Completion，再经`llm/server.go:1583–1597`转grammar。没有为此替换native后端、模型或采样器。历史原0.24带schema仍有坏JSON的记录保留；偶然输出合法JSON不能证明旧版已施加enum。

已有可复现材料在RAG-readiness：`data/eval/readiness-recovery-20261025/runtime-ollama024-backport/{build-configuration,build-result}.json`记录固定v0.24.0源码、Go1.26.0、上游回归及成功构建命令；链接版本设为`0.24.0-format-backport`，沿用同版`/usr/local/lib/ollama`与cuda_v13库。这些应成为正式交付资料，不能只依赖该机现成二进制。

## F-BLR-RUNTIME-01 — 默认部署缺少实际已验证引擎前提

issue (blocking for default deployment, must-fix)

- **id**: F-BLR-RUNTIME-01
- **severity**: High，critic §2的实际热路径部署边界未闭合；不声称官方旧版所有回答必然失败。
- **location**: `deploy_wsl.sh:7,127–137,281,403–409,565–594`、`deploy_ollama.sh:5,23–27`；本地schema与单次输出策略的运行时契约。
- **symptom**: 新机按现脚本使用官方0.24可通过CLI版本、tags、普通OK生成及GPU检查；这些均不能证明Qwen3.5无思考schema生效。若再把bounded作为该部署默认，就把自定义引擎验证结果用于未修补服务。
- **impact**: 来源enum约束失效、生成后拒收/不完整交付风险回到已观察路径；性能/质量默认结论不成立。现有后验检查不得移除。
- **root_cause**: 部署仅锁CLI版本和普通生成，未携带实际服务的格式回移前提；当前本机独立ExecStart补丁未由新机部署入口复现。
- **recommendation**: 将既有单点patch、固定源/工具链与同版库的构建安装步骤入库，产物独立安装为`/usr/local/bin/ollama-rag-format-backport`并保留原官方二进制。bounded部署显式选择该服务产物，并核实际`/api/version`为回移版本；未满足则明确拒绝启用bounded，legacy继续原官方路径。不要用CLI版本字符串或普通OK探针替代服务前提，也无需把版本检查放进每次热请求。
- **verification**: 沿用现有回移红绿/构建证据和本轮真实API；部署定向测试证明bounded拒绝未修补服务、接受已指定回移版本，而legacy仍兼容官方0.24。无需新GPU矩阵或整体升级到0.31/0.40。
- **status**: open（默认部署前闭合；不阻止当前已验证回移引擎上的开发/API/留出工作）。

模板仍列qwen3:14b是另一个已由主线程负责的配置接线问题，本报告不另扩模型迁移范围。最终默认声明应同时写清9B/general、回移引擎和已验证策略；删除新增服务drop-in并回到legacy即可使用原官方二进制回滚。

## Design Repair Confirmation

已独立读取design:48–51：留出通过后才默认auto，精确local9B/general再以实际`/api/version=0.24.0-format-backport`选择bounded；未知/其他版本/不可达走legacy，显式legacy回滚。按端点缓存、timeout1s、trust_env=False且配置/引擎变化后重启刷新，足以闭合本次适用前提，无新增设计阻断。该GET是控制面一次读取，不是模型调用；缓存首次等待成本如实保留，不假称零网络成本。无需增加热路径版本轮询或通用能力探测。

F-BLR-RUNTIME-01设计修订已认可；暂保留open仅表示最小实现、补丁/重建说明及部署定向验证尚待归档，不能提前声称已验证部署。可继续当前回移引擎的既定验证与实现工作。
