# Development

## Prerequisites

开发工具链必须与仓库契约一致：Python ≥3.10、uv 0.11.8、Node 20.20.2、npm 10.8.2、
`curl` 与 util-linux 的 `setsid`。本地模型模式还需要已安装并运行的 Ollama；工具安装由操作系统
包管理或受信发行物完成，仓库脚本不会执行远程安装器。

```bash
uv --version
node --version
npm --version
curl --fail http://127.0.0.1:11434/api/tags
```

## First Start

```bash
cp .env.example .env
chmod 600 .env
./deploy_ollama.sh --model qwen3.5:9b
./run.sh --profile local
```

`run.sh` 使用 frozen lock、`npm ci`、loopback 监听和有界 readiness 检查；进程身份记录在
`.pids/*.meta`，停止时会同时核对 PID、PGID、启动时钟、命令和工作目录，避免误杀复用 PID。

不安装本地模型栈、改走 API embedding 时：

```bash
./run.sh --profile api-only
```

需要事先在 `.env` 配好对应 API endpoint/key。已完成依赖同步时可加 `--skip-sync`；只调后端时
可加 `--no-frontend`。开发模式拒绝非 loopback CORS origin，不应作为公网部署方式。

## Verification and Stop

```bash
curl --fail http://127.0.0.1:8000/live
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:3000/
./stop.sh
```

后端和前端日志分别为 `logs/backend.log`、`logs/frontend.log`。若元数据身份不匹配，`stop.sh`
会拒绝发送信号；先人工核验 `/proc/<pid>`，不要按端口批量杀进程。

## Local RAG Scheduling and Publication

本地9B/general合格运行时的单槽调度、流程条款选择、忙碌/未完成终态与独立回滚见[Bounded Local RAG](BOUNDED_LOCAL_RAG.md)。16GB机器使用单应用worker、Ollama parallel=1、context4096；修改配置后重启。调度默认fair，流程优化默认false；比较/非流程保持完整生成，流程也在全文检查后发布。步骤覆盖已改善，但新留出存在无关内容，完整质量尚未合格；见[质量与耗时结果](../specs/segmented-procedure-coverage/results.md)。
