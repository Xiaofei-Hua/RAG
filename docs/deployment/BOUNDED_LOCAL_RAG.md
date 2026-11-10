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
