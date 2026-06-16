# 航空排故智能问答系统

面向航空地面健康管理（PHM）与维修排故场景的本地 RAG 智能问答平台。
系统能够导入维修手册、排故文档等知识资料，通过混合检索与大语言模型生成
带依据的故障诊断、可能原因、排查步骤和安全提示。

项目默认使用本地 Ollama 与 Qwen3 模型，知识库和会话数据均可在本机运行，
适合内网、离线环境和需要保护技术资料的场景。

## 核心能力

- **双问答模式**：Thinking 模式执行完整 LangGraph 流程，Fast 模式直接检索并生成
- **混合检索**：Dense 向量检索 + BM25 关键词检索 + RRF 融合
- **知识库管理**：支持上传、查询、删除、去重和重建文档索引
- **结构化诊断**：输出诊断结论、可能原因、排查步骤、安全风险和依据来源
- **推理过程捕获**：支持读取 Qwen3 的 reasoning 内容
- **会话与反馈**：保存对话历史，收集点赞、点踩、纠正和标记反馈
- **可靠性能力**：包含 tracing、指标、熔断、降级和输入输出 guardrails
- **生产部署**：FastAPI 可直接托管前端静态文件，并支持 `/rag` 等反代前缀

## 技术栈

| 层级 | 技术 |
|------|------|
| Agent 编排 | LangGraph、Harness + Skills + MCP |
| 后端 API | FastAPI、Uvicorn |
| LLM | Qwen3:14b、Ollama OpenAI 兼容接口 |
| Embedding | BGE-small-zh-v1.5 |
| 检索 | Milvus Lite、BM25、RRF |
| 会话存储 | Redis，可自动降级到 SQLite |
| 前端 | Vue 3、Vite、TypeScript、Pinia |

## 工作流程

Thinking 模式执行完整诊断流程：

```text
用户问题
  -> 意图识别
  -> Agent 判断是否调用检索工具
  -> Dense + BM25 混合检索
  -> 文档相关性评分
  -> 必要时重写问题并重新检索
  -> 生成结构化诊断回答
```

Fast 模式跳过多轮判断，直接执行检索和生成，适合需要更低延迟的查询。

## 快速开始（Quick Start）

### 1. 环境要求

- Linux、WSL2 或 macOS
- Python 3.10+
- Node.js 20+
- [Ollama](https://ollama.com/)
- 建议至少 16 GB 内存；运行 `qwen3:14b` 建议使用独立显卡

Redis 为可选组件。Redis 不可用时，系统会自动使用 SQLite 保存会话。

### 2. 准备 Ollama 模型

如果 Ollama 尚未作为系统服务运行，请在单独的终端启动：

```bash
ollama serve
```

然后下载默认模型：

```bash
ollama pull qwen3:14b
```

可以通过 `ollama list` 确认模型已经就绪。

### 3. 配置项目

```bash
git clone <repository-url>
cd RAG
cp .env.example .env
```

如果已经进入本项目目录，直接执行 `cp .env.example .env` 即可。

默认 `.env` 配置：

```dotenv
# LLM
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=qwen3:14b
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096

# Embedding
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_MODEL_PATH=models/local_models/bge-small-zh-v1.5
EMBEDDING_DIMENSION=512
EMBEDDING_DEVICE=cpu
```

完整配置与说明见 `.env.example`。

### 4. 一键启动开发环境

```bash
chmod +x run.sh stop.sh
./run.sh
```

首次启动会自动创建 Python 虚拟环境、安装依赖、下载 Embedding 模型并安装前端依赖。

启动完成后访问：

| 服务 | 地址 |
|------|------|
| Web 前端 | http://localhost:3000 |
| 后端 API | http://localhost:8000/api |
| Swagger 文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |

查看日志或停止服务：

```bash
tail -f logs/backend.log
tail -f logs/frontend.log
./stop.sh
```

### 5. 导入首份知识库文档

可以在前端的“文档管理”页面上传文档，也可以调用 API：

```bash
curl -X POST http://localhost:8000/api/documents/upload \
  -F "file=@md/phm_test_knowledge_base.md"
```

支持上传 `.md`、`.txt` 和 `.pdf`。PDF 会按页面解析：优先使用 `pypdfium2`
抽取文字层，并用 `pypdf` 逐页兜底；明确保留列分隔的表格会转成 Markdown
表格 chunk 入库；带图片页面会记录图片对象元数据。纯扫描图片 PDF 或图片内文字
需要启用 OCR 后才能进入检索索引。

OCR 默认为关闭，适合在安装本地 OCR 引擎后按需打开：

```dotenv
PDF_OCR_ENABLED=true
PDF_OCR_ENGINE=paddleocr
PDF_OCR_LANG=ch
PDF_OCR_DPI=220
```

本项目已支持 PaddleOCR，本地依赖为 `paddlepaddle` + `paddleocr`。首次 OCR 会
下载 PaddleOCR 官方模型到 `~/.paddlex/official_models/`；CPU 环境默认禁用
PaddleX MKLDNN 路径以避免部分主机上的 oneDNN/PIR 推理错误。

上传完成并建立索引后，即可在前端询问：

```text
液压系统压力低应该如何排查？
```

也可以直接调用问答 API：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"液压系统压力低应该如何排查？","mode":"thinking"}'
```

## 手动启动

需要分别控制后端和前端时，可以使用以下方式。

安装后端与测试依赖：

```bash
uv sync --extra dev
```

启动后端：

```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

在另一个终端启动前端开发服务器：

```bash
cd web
npm ci
npm run dev
```

Vite 开发服务器会将 `/api` 请求代理到 `http://127.0.0.1:8000`。

## Ubuntu 一键部署

`deploy.sh` 可以安装 Ubuntu/Debian 所需组件、下载模型、构建前端静态文件并生成
`.env`：

```bash
sudo ./deploy.sh
```

常用选项：

```bash
sudo ./deploy.sh --skip-ollama
sudo ./deploy.sh --skip-redis
sudo ./deploy.sh --skip-model
sudo ./deploy.sh --skip-embedding
sudo ./deploy.sh --build-offline-bundle
```

`deploy.sh` 会预热运行所需的本地资产：Ollama LLM 模型、Embedding 模型、
Reranker 模型、PaddleOCR 模型、Python 依赖和前端 `web/dist` 构建产物。
其中 Reranker 会保存到 `models/local_models/reranker/...`，避免离线环境依赖
用户级 Hugging Face cache。

部署脚本完成后，使用 `./run.sh` 启动开发模式，或按下一节使用 FastAPI
托管生产静态文件。

### 构建离线部署包

在一台有网络的同架构机器上完成预热并打包：

```bash
sudo ./deploy.sh --build-offline-bundle
```

生成物位于 `offline_bundle/rag_offline_bundle_<timestamp>.tar.gz`。包内包含：

- 项目代码与 `web/dist` 前端静态构建产物
- `wheelhouse/` Python 离线安装包和 `requirements.lock.txt`
- `models/local_models/` 下的 Embedding、Reranker、Ollama 模型目录快照
- `paddleocr/official_models/` PaddleOCR 模型缓存
- `install_offline.sh` 离线安装脚本和 `env.offline`

在断网目标机上解压并安装：

```bash
tar -xzf rag_offline_bundle_<timestamp>.tar.gz
cd rag_offline_bundle_<timestamp>
./install_offline.sh /opt/rag-platform
```

目标机仍需预先具备基础系统能力：`python3`、可用的 `ollama` 可执行文件，以及可选的
Redis。离线脚本不访问网络，会从包内 wheelhouse 安装 Python 依赖，并把 PaddleOCR
模型缓存恢复到当前用户的 `~/.paddlex/official_models`。启动 Ollama 时请设置：

```bash
export OLLAMA_MODELS=/opt/rag-platform/models/local_models/ollama
ollama serve
```

## 生产静态部署

生产环境不需要运行 Vite 开发服务器。先构建前端：

```bash
cd web
npm ci
npm run build
cd ..
```

然后只启动 FastAPI：

```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

构建输出位于 `web/dist/`。FastAPI 会托管前端资源，并为 Vue Router 提供
SPA fallback。此时前端与 API 均通过 `http://localhost:8000` 访问。

### 使用 `/rag` 反代前缀

构建时设置前端公共路径：

```bash
cd web
VITE_BASE_PATH=/rag/ npm run build
cd ..
APP_ROOT_PATH=/rag uv run uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Nginx 配置示例：

```nginx
location /rag/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

该配置会移除 `/rag` 前缀后再转发给 FastAPI。浏览器请求
`/rag/api/chat` 时，FastAPI 实际收到 `/api/chat`。

## 配置说明

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `OPENAI_BASE_URL` | `http://localhost:11434/v1` | LLM OpenAI 兼容接口 |
| `OPENAI_API_KEY` | `ollama` | LLM API Key |
| `LLM_MODEL` | `qwen3:14b` | 问答模型名称 |
| `LLM_TEMPERATURE` | `0.0` | LLM 采样温度 |
| `LLM_MAX_TOKENS` | `4096` | 单次回答最大生成 token |
| `LLM_TIMEOUT` | `60` | 单次 LLM 请求超时秒数 |
| `LLM_MAX_RETRIES` | `1` | LLM 客户端重试次数 |
| `EMBEDDING_MODEL` | `BAAI/bge-small-zh-v1.5` | Hugging Face Embedding 模型 ID |
| `EMBEDDING_MODEL_PATH` | `models/local_models/bge-small-zh-v1.5` | Embedding 本地缓存路径 |
| `EMBEDDING_DIMENSION` | `512` | Embedding 输出向量维度 |
| `EMBEDDING_DEVICE` | `cpu` | Embedding 运行设备，例如 `cpu`、`cuda` |
| `EMBEDDING_NORMALIZE` | `true` | 是否归一化 Embedding 向量 |
| `EMBEDDING_BATCH_SIZE` | `8` | Embedding 编码批大小 |
| `RERANKER_ENABLED` | `false` | 是否在 RRF 融合后启用 Cross-Encoder 重排序 |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 可选重排序模型 |
| `RERANKER_MODEL_PATH` | `models/local_models/reranker/ms-marco-MiniLM-L-6-v2` | 可选本地模型目录，配置且存在时优先于模型 ID |
| `RERANKER_DEVICE` | `cpu` | Reranker 运行设备，例如 `cpu`、`cuda` |
| `RERANKER_WARMUP` | `false` | 是否在服务启动时加载 Reranker |
| `RERANKER_CANDIDATE_TOP_K` | `10` | Dense 与 BM25 各自送入 RRF 的候选数 |
| `RERANKER_TOP_K` | `5` | 调用方未指定 `top_k` 时的最终默认结果数 |
| `RERANKER_BATCH_SIZE` | `8` | 重排序批大小 |
| `OTEL_ENABLED` | `false` | 是否启用 OpenTelemetry tracing |
| `OTEL_SERVICE_NAME` | `rag-platform` | Trace 中的服务名 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | 空 | OTLP/HTTP trace 接收地址 |
| `OTEL_SAMPLE_RATE` | `1.0` | Trace 采样率，范围 0～1 |
| `OTEL_CONSOLE_EXPORTER` | `false` | 是否将 Span 输出到控制台 |
| `MILVUS_DB_URI` | `./milvus_data.db` | Milvus Lite 数据库路径 |
| `COLLECTION_NAME` | `t_collection01` | Milvus collection 名称 |
| `PDF_EXTRACT_TABLES` | `true` | 是否将明确列分隔的 PDF 表格转为 Markdown chunk |
| `PDF_OCR_ENABLED` | `false` | 是否对扫描页/图片页启用 OCR |
| `PDF_OCR_ENGINE` | `paddleocr` | OCR 引擎，目前支持 `paddleocr`、`tesseract` |
| `PDF_OCR_LANG` | `ch` | OCR 语言配置 |
| `PDF_OCR_DPI` | `220` | PDF 页面渲染为 OCR 图片时的 DPI |
| `PDF_OCR_MIN_TEXT_CHARS` | `20` | 页面文字少于该阈值时才尝试 OCR |
| `PDF_ASSET_DIR` | `data/document_assets` | OCR 页面图片与后续图片资产目录 |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | `0` | PaddleOCR CPU 兼容性开关，默认禁用 MKLDNN |
| `APP_ROOT_PATH` | 空 | FastAPI 对外反代路径前缀 |
| `VITE_BASE_PATH` | `/` | 前端构建时的公共路径 |
| `WEB_DIST_DIR` | `web/dist` | FastAPI 托管的前端构建目录 |

系统启动时会加载项目根目录的 `.env`。由 Shell、Docker 或 Kubernetes
传入的环境变量优先级高于 `.env`，因此无需修改文件即可覆盖配置。

### 更换 LLM

项目支持任意 OpenAI 兼容接口。以切换到另一个 Ollama 模型为例：

```bash
ollama pull qwen3:8b
```

修改 `.env`：

```dotenv
LLM_MODEL=qwen3:8b
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=2048
```

重启后端后生效。也可以只对单次启动覆盖：

```bash
LLM_MODEL=qwen3:8b uv run uvicorn api.main:app --port 8000
```

### 更换 Embedding 模型

Embedding 配置包含三个必须匹配的字段：

```dotenv
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_MODEL_PATH=models/local_models/bge-large-zh-v1.5
EMBEDDING_DIMENSION=1024
```

- `EMBEDDING_MODEL` 是下载来源或 Hugging Face 模型 ID。
- `EMBEDDING_MODEL_PATH` 是本地缓存路径。路径内存在已保存模型时优先加载本地模型。
- `EMBEDDING_DIMENSION` 必须与模型实际输出维度一致。

更换 Embedding 模型或维度后，旧向量与新模型不兼容，必须重建 collection
并重新导入知识库文档：

```bash
uv run python documents/milvus_db.py --action create --drop
```

然后重新启动服务并上传文档。使用 `./run.sh` 或 `deploy.sh` 时，脚本会按照
当前 `.env` 自动下载配置的 Embedding 模型到本地路径。

### 启用两阶段重排序

混合检索默认执行 Dense + BM25 召回和 RRF 融合。需要进一步提高最终排序精度时，
可以启用 Cross-Encoder 对融合候选文档进行第二阶段重排序：

```dotenv
RERANKER_ENABLED=true
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_MODEL_PATH=models/local_models/reranker/ms-marco-MiniLM-L-6-v2
RERANKER_DEVICE=cpu
RERANKER_WARMUP=false
RERANKER_CANDIDATE_TOP_K=10
RERANKER_TOP_K=5
RERANKER_BATCH_SIZE=8
```

`deploy.sh` 和 `scripts/download_reranker.py` 会把模型保存到
`RERANKER_MODEL_PATH`，便于离线运行。若该路径为空且只使用 Hugging Face 模型 ID，
首次加载会自动下载到：

```text
~/.cache/huggingface/hub/models--<organization>--<model-name>/
```

推荐保留项目内路径，便于离线打包。需要提前下载并验证模型时运行：

```bash
uv run python scripts/download_reranker.py
```

配置 `RERANKER_WARMUP=true` 后，服务启动时会加载模型，
避免首个检索请求承担模型加载耗时。

默认 `cross-encoder/ms-marco-MiniLM-L-6-v2` 体积较小，但主要面向英文检索。
中文 PHM 场景建议评估中文或多语言 Reranker，例如 `BAAI/bge-reranker-base`，
再根据显存、延迟和检索效果决定是否切换。

Cross-Encoder 会增加检索延迟和内存占用，因此默认关闭。启用后，检索 API
会返回：

- `retrieval_score`：RRF 融合后的召回分数
- `rerank_score`：Cross-Encoder 相关性分数
- `rerank_applied`：本次是否成功应用重排

模型加载失败时系统会保留 RRF 顺序并标记 `rerank_applied=false`，不会中断检索。
运行状态可通过 `/api/admin/health` 查看：`cold` 表示尚未下载，`ready` 表示已缓存但
尚未加载，`healthy` 表示已加载，`degraded` 表示加载失败。

### OpenTelemetry 可观测性

系统支持 FastAPI HTTP Span 与 Agent Skill Span，可通过 OTLP/HTTP 导出到
Jaeger、Grafana Tempo 或 OpenTelemetry Collector。以本地 Jaeger 为例：

```bash
docker run --rm --name rag-jaeger \
  -p 16686:16686 -p 4318:4318 \
  jaegertracing/all-in-one:latest
```

修改 `.env` 并重启后端：

```dotenv
OTEL_ENABLED=true
OTEL_SERVICE_NAME=rag-platform
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
OTEL_SAMPLE_RATE=1.0
```

随后访问 `http://localhost:16686`，可以查看 HTTP 请求及
`agent.skill.agent`、`agent.skill.retrieve`、`agent.skill.grade`、
`agent.skill.generate` 等 Span。生产环境建议降低采样率。

当前生效配置可通过以下接口查看：

```bash
curl http://localhost:8000/api/admin/config
```

## 常用 API

| 功能 | 方法与路径 |
|------|------------|
| 非流式问答 | `POST /api/chat` |
| SSE 流式问答 | `POST /api/chat/stream` |
| 上传知识文档 | `POST /api/documents/upload` |
| 文档列表 | `GET /api/documents` |
| 混合检索 | `POST /api/retrieval` |
| 会话列表 | `GET /api/sessions` |
| 提交反馈 | `POST /api/feedback` |
| 系统配置 | `GET /api/admin/config` |
| 详细健康检查 | `GET /api/admin/health` |

完整请求和响应格式见 [API 文档](docs/API.md)。

## 测试

安装开发依赖并运行 pytest 单元测试：

```bash
uv sync --extra dev
uv run pytest
```

启动后端后，可以运行独立 API 和全链路测试：

```bash
uv run python tests/api/test_health.py
uv run python tests/api/test_chat.py
uv run python tests/api/test_documents.py
uv run python tests/api/test_sessions.py
uv run python tests/api/test_retrieval.py
uv run python tests/api/test_feedback.py
uv run python tests/integration/test_system.py
```

验证前端生产构建：

```bash
cd web
npm run build
```

### 并发压测

启动后端并导入知识库后，可以使用内置异步压测脚本测试 SSE 接口：

```bash
uv run python scripts/load_test.py \
  --mode fast \
  --requests 20 \
  --concurrency 4
```

脚本输出成功率、吞吐量、端到端 P50/P95/P99 延迟和首 Token 延迟（TTFT）。
Thinking 模式可通过 `--mode thinking` 测试。

更多测试说明见 [tests/README.md](tests/README.md)。

## 项目结构

```text
agent/
├── harness/       LangGraph 编排、计划、生命周期与可观测性
├── skills/        Agent、检索、评分、重写、生成和意图技能
├── context/       Agent 共享状态与会话上下文
├── mcp/           MCP 服务端、客户端与检索工具
├── feedback/      用户反馈与升级处理
├── guardrails/    输入输出安全检查
└── memory/        长期记忆提取与存储

api/               FastAPI 应用、路由与中间件
core/              检索、意图、会话、降级和 tracing
documents/         文档解析、注册与 Milvus 管理
models/            LLM 与 Embedding 配置
web/               Vue 3 前端
tests/             单元、API 与全链路测试
docs/              API 文档与技术报告
```

## 数据与运行时文件

以下内容会在本地运行时生成，并已通过 `.gitignore` 排除：

- `data/`：会话、反馈、文档注册等 SQLite 数据
- `milvus_data.db*`：Milvus Lite 数据库与锁文件
- `models/local_models/`：本地 Embedding 模型
- `web/dist/`：前端生产构建产物
- `logs/`、`.pids/`：运行日志与进程文件

## 常见问题

### Ollama 连接失败

确认 Ollama 正在运行，模型已经下载：

```bash
curl http://localhost:11434/api/tags
ollama list
```

### 首次启动较慢

首次运行需要下载约 91 MB 的 Embedding 模型，并加载 Milvus 与模型权重。
后续启动和检索速度会明显提升。

### Redis 不可用

Redis 是可选组件。连接失败时，系统会自动降级到 `data/sessions.db`。

### 修改了反代前缀但前端资源仍然 404

`VITE_BASE_PATH` 是构建时变量。修改后必须重新执行 `npm run build`。

## 更多文档

- [API 接口文档](docs/API.md)
- [系统技术报告](docs/technical_report.md)
- [Agent Skills 说明](agent/skills/README.md)
- [测试说明](tests/README.md)
