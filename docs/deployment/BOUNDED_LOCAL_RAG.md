# Bounded Local RAG

## Scope
默认问答模型为`qwen3.5:9b`。本机16GB显卡的合格组合为Q4_K_M、4096 context、原生Ollama 0.24.0同源构建加格式修复、BGE-M3及reranker。没有因关闭隐式思考而省略结论/条件/正文引用；最终作答一次，意图/工具/相关性控制为短调用，不在线逐句调用模型核验。来源编号与结构检查不能代替语义事实核验，grounding保持None、confidence_degraded=true。

`LOCAL_RAG_POLICY=auto`只对本地loopback:11434/v1、精确9B/general profile及实际`/api/version=0.24.0-format-backport`启用有界策略。其他版本/模型/profile维持legacy。服务身份按端点在进程内缓存，版本读取失败保持legacy直到应用重启；不会以模型请求探测。`legacy`明确回滚；`bounded`用于已验证运行时的显式试验，不能据此声称其他版本通过。

## Runtime Fix
官方0.24.0对Qwen3.5的think=false会清空format；修复来自[上游#15901](https://github.com/ollama/ollama/pull/15901)。本仓库的[补丁](../../deploy/patches/ollama-0.24.0-thinking-format.patch)仅回移该条件，不切换到新版推理后端。上游项目采用MIT许可。完整构建/红绿日志见性能规格中的归档。

在已有官方0.24.0 GPU库的Linux/WSL部署中，用固定Go1.26.0及C/C++工具构建独立程序。以下命令从RAG仓库根执行，source/release目录需为新建的专用构建目录；不覆盖官方ollama二进制。

```bash
RAG_REPO="$PWD"
BUILD_DIR="$HOME/.local/src/ollama-rag-0.24.0"
git clone --branch v0.24.0 --depth 1 https://github.com/ollama/ollama.git "$BUILD_DIR"
cd "$BUILD_DIR"
git apply "$RAG_REPO/deploy/patches/ollama-0.24.0-thinking-format.patch"
go version  # 本次合格构建使用go1.26.0；CGO需要C/C++编译器
CGO_ENABLED=1 go build -ldflags '-X github.com/ollama/ollama/version.Version=0.24.0-format-backport' -o ollama-rag-format-backport .
sudo install -m 0755 ollama-rag-format-backport /usr/local/bin/ollama-rag-format-backport
```

保持官方0.24.0的`/usr/local/lib/ollama`与CUDA库，不混入0.31库。构建原生GPU库的完整方法见[对应版本构建指南](https://github.com/ollama/ollama/blob/v0.24.0/docs/development.md)。程序路径相对于库目录符合官方Linux布局，native runner由同一程序启动。

## Service Selection
为现有ollama.service添加专用drop-in（先保存现有service/drop-in列表，已有同名文件先备份），保留现有端口、模型目录和用户，不替换原unit：

```ini
# /etc/systemd/system/ollama.service.d/20-rag-format-backport.conf
[Service]
ExecStart=
ExecStart=/usr/local/bin/ollama-rag-format-backport serve
```

用`systemctl daemon-reload`与`systemctl restart ollama`应用。重启会中断当前模型请求，应在空闲时执行。`curl --noproxy '*' http://127.0.0.1:11434/api/version`必须返回`0.24.0-format-backport`，不能用CLI版本代替正在服务的版本。应用配置设置`LLM_MODEL=qwen3.5:9b`和`LOCAL_RAG_POLICY=auto`，然后重启应用。

建议保持`OLLAMA_CONTEXT_LENGTH=4096`、`OLLAMA_NUM_PARALLEL=1`、`OLLAMA_MAX_LOADED_MODELS=1`；加大并发前按实际显存与排队测量，不默认多模型驻留或CPU溢出。16GB不是扩大隐藏思考和逐句judge预算的依据。

## Rollback
设置`LOCAL_RAG_POLICY=legacy`并重启应用即可恢复原策略。若回滚引擎，仅恢复/移除本次专用drop-in、daemon-reload并重启ollama；官方二进制和模型权重未覆盖。再次切换模型/服务版本后也重启应用，刷新身份缓存。

本方案的实验问题规模有限；保留原始失败与拒答，结果报告区分回答质量、覆盖率、超时和有效首段时间。不宣称所有通用推理任务或其他引擎版本均已验证。

## Scheduling and Publication

本地已合格的Qwen3.5:9b/general运行时使用有界RAG：最终作答最多一次模型调用，意图/工具/相关性控制每次256 tokens，最终生成2048 tokens；两种产品模式都关闭模型隐藏思考，深度模式的区别是检索编排。线上不逐句重复调用模型核验，缺失grounding分数为`None/degraded`，来源、结构、PII检查保留。

`LOCAL_LLM_SCHEDULER=fair`开启单进程共享模型槽：1个运行、最多8个等待、等待上限30秒；短控制调用有界优先并防止长生成饥饿。队列满/超时立即返回可重试忙碌终态，不继续模型重试。16GB部署使用一个应用worker、Ollama parallel=1；这不提供跨进程全局调度。

`LOCAL_RAG_SEGMENTED=true`启用按题分流：非比较且未改写的问题生成conditions→answer，结论与完整条件先经同一输出检查后一起展示，再展示检查过的解释段；比较/等值/差值/倍数或已改写问题保留合格完整生成。词匹配是保守启发式，不保证识别所有隐含比较。生成失败保留已检查正文并标记`generation_complete=false`，服务端保存的未完成回答在历史中保留标记；主动停止只保留当前页面已显示正文，不保存为成功答案。第3步已通过容量/取消验收，默认fair；第4步留出长流程存在步骤/起算遗漏，默认false，仅显式试用；设置off/false并重启可独立回滚。

完整收益、样本分母与适用限制见[本轮实验](../specs/local-scheduling-streaming/results.md)。
