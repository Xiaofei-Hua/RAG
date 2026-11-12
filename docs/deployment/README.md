# Deployment Guide

本文档集是部署与运维的事实入口。功能规格和历史设计位于 `docs/specs/*`，不作为操作手册；
实际命令、端口、健康状态和安全边界以本目录、锁文件与部署资产为准。

## Deployment Matrix

| 场景 | LLM | Embedding / Reranker | 入口 | 适用文档 |
|---|---|---|---|---|
| 本地开发 | Ollama 或兼容 API | 默认本地 BGE-M3 / 本地 reranker | `run.sh` | [Development](development.md) |
| Windows + WSL 本地生产 | WSL 内 Ollama `qwen3.5:9b` | WSL 内本地 BGE-M3 / reranker / GPU | `deploy_wsl.sh` + systemd + localhost | [WSL Complete Guide](WSL_DEPLOYMENT.md) |
| 裸机生产 | 本机 Ollama | 本地模型，支持 GPU | systemd + Nginx | [Bare Metal](bare-metal.md) |
| API-only 容器 | DashScope/OpenAI 兼容服务 | DashScope embedding，无 torch/reranker | Docker + Nginx | [API-only Docker](api-only-docker.md) |
| 气隙部署 | 目标机已有 Python/Ollama/系统库 | 在线机预打包 uv cache 与模型 | 离线安装器 | [Offline](offline.md) |

所有生产方案都必须满足：

- `DEPLOYMENT_ENV=production`；
- `ADMIN_API_KEY` 非空，`ALLOWED_ORIGINS` 是明确 HTTP(S) origin，禁止 `*`；常规生产至少一个
  non-loopback origin，WSL 本机方案则必须显式 `LOCAL_ONLY_DEPLOYMENT=true` 且全部为 loopback；
- 应用仅监听 loopback 或容器内部端口，公网入口由 TLS 反向代理提供；
- `.env`、`deploy/secrets/` 与真实 `deploy/env/*.env` 不进入 Git、镜像或离线包；
- `/live` 只表示进程存活，`/health` 的 `healthy|degraded` 才是就绪/降级状态。

部署完成后的备份、升级、回滚、监控和故障分类见 [Operations](operations.md)。
Windows 11 单机使用优先阅读一篇式 [WSL Complete Guide](WSL_DEPLOYMENT.md)，其中同时包含前置安装、
脚本、全部 HTTP/MCP 接口、运维和排障，不需要在多篇文档之间拼步骤。

## Local RAG Scheduling and Publication

本地9B/general运行时的调度、中文流程分类、忙碌/未完成终态与回滚见[Bounded Local RAG](BOUNDED_LOCAL_RAG.md)。16GB机器使用单应用worker、Ollama parallel=1、context4096；调度默认fair，中文流程优化默认true，英文/比较/改写/非流程保持原完整生成。流程在全文检查后发布，最终生成仍一次；已有显式false继续生效。配置修改后重启，真实质量/耗时及样本限制见[实验结果](../specs/procedure-relevance-order/results.md)。
