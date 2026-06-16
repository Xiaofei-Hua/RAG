# 航空排故智能问答系统（RAG）技术报告

> 测试环境：WSL2 Ubuntu / NVIDIA RTX 5070 Ti 16GB / Ollama 0.24.0
> 测试日期：2026-05-27

---

## 1. 系统概述

本项目是一个面向航空地面健康管理（PHM）领域的企业级 RAG 平台，基于检索增强生成技术，为机务人员提供故障诊断、排故引导、知识库问答和维护决策支持。系统采用前后端分离架构：

- **后端**：FastAPI + LangGraph + Milvus Lite
- **前端**：Vue 3 + Vite + TypeScript
- **LLM**：Qwen3-14B（本地 Ollama 部署，Q4_K_M 量化）
- **Embedding**：BGE-small-zh-v1.5（本地部署）

---

## 2. 大语言模型：Qwen3-14B

### 2.1 模型规格

| 参数 | 数值 |
|------|------|
| 模型家族 | Qwen3（阿里通义千问第三代） |
| 总参数量 | **14.8B**（148 亿） |
| 非嵌入层参数量 | 12.6B |
| 架构类型 | Decoder-only Transformer（Dense） |
| 层数 | **40** |
| 注意力头（GQA） | Q: 40 heads / KV: 8 heads |
| 原生上下文长度 | **32,768 tokens**（32K） |
| 扩展上下文长度（YaRN） | **131,072 tokens**（128K） |
| 量化格式 | **GGUF Q4_K_M** |
| 模型文件大小 | **9.3 GB** |
| 显存占用 | **~12 GB**（RTX 5070 Ti 16GB，含 KV Cache） |
| 最大输出长度 | 32,768 tokens |
| 多语言支持 | 100+ 语言和方言 |
| 工具调用能力 | 支持（Agent/Function Calling） |
| Ollama 模型 ID | `qwen3:14b` |

### 2.2 双模式推理机制

Qwen3 的核心特性是**在同一模型权重内无缝切换思考模式与非思考模式**：

#### 思考模式（Thinking Mode）

- 默认启用，模型会生成 `<think...>` 包裹的推理链后再输出最终回答
- 适用于复杂逻辑推理、数学计算、编程、深度分析
- **推荐采样参数**：Temperature=0.6, TopP=0.95, TopK=20（禁止贪心解码）
- 开关方式：`enable_thinking=True` 或用户输入 `/think`

#### 非思考模式（Non-Thinking Mode）

- 快速响应模式，跳过推理链直接输出答案
- 适用于简单对话、格式化输出、高频调用场景
- **推荐采样参数**：Temperature=0.7, TopP=0.8, TopK=20
- 开关方式：`enable_thinking=False` 或用户输入 `/no_think`

> **本项目集成方案**：
> - **Thinking 模式（RAG 深度诊断）**：保留 Qwen3 默认 thinking 行为，通过 OpenAI SDK 直接调用 Ollama 捕获 `reasoning` 字段，推理过程（约 800-1600 字符）随响应返回给前端，供用户查看模型的推理逻辑
> - **Fast 模式（快速问答）**：在 Prompt 末尾追加 `/no_think` 关闭推理，跳过 thinking token 生成，降低延迟
> - Temperature=0.0, MaxTokens=4096，`strip_think_tags()` 兜底过滤泄漏的 `<think...>` 标签

### 2.3 本项目 LLM 配置

```dotenv
# .env
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
LLM_MODEL=qwen3:14b
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=60
LLM_MAX_RETRIES=1
```

模型配置统一从环境变量读取，进程环境变量优先于项目根目录 `.env`。
Embedding 模型 ID、本地路径、向量维度、设备和批大小同样可通过
`EMBEDDING_*` 环境变量配置。

### 2.4 推理性能实测

测试硬件：NVIDIA RTX 5070 Ti 16GB（GPU 占用约 12GB，14B Q4_K_M 量化）

#### 基础 LLM 调用

| 测试场景 | 输入长度 | 输出长度 | 首 Token 延迟 (TTFT) | 总延迟 |
|----------|----------|----------|---------------------|--------|
| 短提示（"你好"） | ~5 tokens | 15 chars | — | **5,449 ms** |
| RAG 问答（含上下文） | ~200 tokens | 755 chars | — | **6,420 ms** |
| 流式生成 | ~20 tokens | 171 chars | **4,003 ms** | 4,661 ms |

#### RAG 系统端到端对比（Fast vs Thinking）

| 查询 | 模式 | 总耗时 | 回答长度 | 推理过程 | 路由 |
|------|------|--------|---------|---------|------|
| 发动机振动偏高 | Fast（/no_think） | **10,941 ms** | 1,249 chars | 无 | fast |
| 发动机振动偏高 | Thinking | **14,750 ms** | 1,076 chars | **837 chars** | rag |
| 液压系统压力低 | Fast（/no_think） | **11,225 ms** | 1,012 chars | 无 | fast |
| 液压系统压力低 | Thinking | **17,503 ms** | 910 chars | **1,632 chars** | rag |
| 起落架收放超时 | Fast（/no_think） | **9,277 ms** | 944 chars | 无 | fast |
| 起落架收放超时 | Thinking | **9,915 ms** | 917 chars | **926 chars** | rag |

**性能分析**：
- Fast 模式（/no_think）比 Thinking 模式平均快 **15-40%**，省去了推理 token 生成开销
- Thinking 模式额外产生 800-1,600 字符的推理过程，可帮助用户理解模型的分析逻辑
- TTFT 约 4-5.5 秒，主要耗时在 GPU 加载和 KV Cache 初始化
- GPU 显存占用 12GB/16GB（75%），14B 参数模型充分利用 GPU 资源

---

## 3. RAG 系统架构

### 3.1 整体架构图

```
用户请求
   │
   ▼
┌──────────────────────────────────────────────────┐
│  FastAPI API 层 (:8000)                           │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌───────┐  │
│  │  Chat   │ │ Documents│ │Session │ │ Admin │  │
│  │ Router  │ │  Router  │ │ Router │ │Router │  │
│  └────┬────┘ └────┬─────┘ └───┬────┘ └───┬───┘  │
│       │           │           │          │       │
│  ┌────▼────────────▼───────────▼──────────▼───┐  │
│  │        Middleware (Tracing / Error)         │  │
│  └─────────────────┬──────────────────────────┘  │
└────────────────────┼─────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   ┌─────────┐ ┌──────────┐ ┌────────────┐
   │ Thinking│ │   Fast   │ │  General   │
   │  Mode   │ │   Mode   │ │    Chat    │
   └────┬────┘ └────┬─────┘ └─────┬──────┘
        │           │             │
        ▼           ▼             ▼
   ┌────────────────────────────────────────┐
   │           LangGraph Pipeline           │
   │  Agent → Retrieve → Grade → Generate  │
   │         (或直接 Retrieve → Generate)    │
   └────────────────┬───────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   ┌─────────┐ ┌─────────┐ ┌──────────┐
   │ Milvus  │ │  BM25   │ │  Redis   │
   │  Lite   │ │ Retriever│ │ Memory   │
   │(Dense)  │ │(Sparse) │ │(Session) │
   └─────────┘ └─────────┘ └──────────┘
        │           │
        ▼           ▼
   ┌──────────────────────────┐
   │  RRF 融合 → 重排序 → TopK │
   └──────────────────────────┘
```

### 3.2 双流水线设计

系统提供两种推理模式，满足不同延迟和深度需求：

| 维度 | Thinking 模式 | Fast 模式 |
|------|-------------|-----------|
| 流水线 | 意图→Agent→检索→评分→重写→生成 | 检索→生成 |
| LLM 调用次数 | 4-6 次 | 1 次 |
| Qwen3 Thinking | **开启**（捕获推理过程） | **关闭**（/no_think） |
| 推理过程 | 返回 800-1,600 字符推理内容 | 无推理内容 |
| 典型延迟 | 10-18 秒 | 9-11 秒 |
| 适用场景 | 复杂故障诊断、深度分析 | 高频查询、快速响应 |
| 检索质量 | 带查询重写，更高 | 直接检索 |
| Reasoning 传递 | `metadata.reasoning` 返回前端 | 无 |

---

## 4. 检索系统

### 4.1 Embedding 模型

| 参数 | 数值 |
|------|------|
| 模型 | BAAI/bge-small-zh-v1.5 |
| 向量维度 | **512** |
| 运行设备 | CPU |
| 批处理大小 | 8 |
| 归一化 | True |
| 模型大小 | ~91 MB |

### 4.2 向量数据库（Milvus Lite）

| 参数 | 数值 |
|------|------|
| 存储后端 | SQLite（本地文件 `milvus_data.db`） |
| Collection | `t_collection01` |
| 索引类型 | AUTOINDEX |
| 度量类型 | IP（内积） |
| 最大文本长度 | 4,000 字符 |
| 最大元数据长度 | 500 字符 |
| 批处理大小 | 20 |
| 一致性级别 | Bounded |

### 4.3 混合检索策略

系统采用 **Dense + Sparse（BM25）双路召回 + RRF 融合**策略：

| 参数 | Dense 路径 | Sparse 路径 |
|------|-----------|-------------|
| 模型 | BGE-small-zh-v1.5 | BM25 |
| 权重 | 0.5 | 0.5 |
| Top-K | 5 | 5 |
| RRF 常数 k | 60 | 60 |
| 最终 Top-K | 3 | 3 |

**BM25 参数**：k1=1.5, b=0.75

**重排序器**：cross-encoder/ms-marco-MiniLM-L-6-v2（可选，Top-5）

### 4.4 检索性能实测

| 查询 | 检索耗时 | 文档数 | Dense 命中 | Sparse 命中 |
|------|---------|--------|-----------|------------|
| 发动机振动偏高（冷启动） | 2,397 ms | 3 | 5 | 0 |
| 液压系统压力低（热启动） | 19 ms | 3 | 5 | 0 |
| 起落架收放超时（热启动） | 14 ms | 3 | 5 | 0 |

> 冷启动包含模型加载和索引构建耗时，热启动检索仅需 14-20 ms。

### 4.5 文档分块策略

#### PDF 结构化解析与 OCR

PDF 上传按页面级 ingestion pipeline 处理：

1. 优先使用 `pypdfium2` 抽取文字层；单页失败或文字不足时使用 `pypdf` 逐页兜底。
2. 明确保留列分隔符（`|`、Tab、多空格）的表格转换为 Markdown 表格 chunk，metadata 标记 `content_type=table` 与 `table_id`。
3. 带图片对象的页面记录 `pdf_image_count`、`pdf_has_images` 等 metadata，便于来源审计和后续多模态扩展。
4. 当 `PDF_OCR_ENABLED=true` 时，图片页/扫描页会由 `pypdfium2` 渲染为页面图片，并调用 PaddleOCR 生成 `content_type=ocr_text` chunk。

当前 OCR 引擎为 PaddleOCR（`paddlepaddle` + `paddleocr`）。首次运行会下载官方模型到
`~/.paddlex/official_models/`。在 CPU 环境中，项目默认设置
`PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0`，以规避 PaddlePaddle 3.x 在部分主机上
触发 oneDNN/PIR `ConvertPirAttribute2RuntimeAttribute` 推理错误。

OCR 结果适合进入 RAG 检索，但不是强一致结构化抽取；故障码中的 `0/O`、`1/I` 等字符
可能出现混淆，关键业务字段仍建议在上游 PDF 生成阶段保留文字层或经过人工校验。

| 参数 | 数值 |
|------|------|
| 语义分块阈值 | 1,200 tokens |
| 字符回退阈值 | 5,000 chars |
| 回退分块大小 | 900 tokens |
| 分块重叠 | 120 tokens |
| 小文档保留阈值 | < 3,840 chars 不分块 |
| 分块方式 | 语义分块（优先）→ RecursiveCharacterTextSplitter（回退） |

---

## 5. LangGraph 工作流

### 5.1 Thinking 模式完整流水线

```
START
  │
  ▼
┌──────────┐  意图分类（LLM/关键词）
│  Agent   │──────────────────────┐
│  Node    │  判断是否需要检索      │
└────┬─────┘                      │
     │ tools_condition             │
     ├─ 需要检索 ──→ Retrieve      │ END（直接回答）
     │              (ToolNode)     │
     │                 │           │
     │                 ▼           │
     │           Grade Documents   │
     │           (LLM 评分)        │
     │                 │           │
     │          ┌──────┴──────┐    │
     │          │             │    │
     │     相关 ▼          不相关▼  │
     │    ┌─────────┐   ┌────────┐ │
     │    │ Generate │   │ Rewrite│ │
     │    │  Node    │   │  Node  │ │
     │    └────┬────┘   └───┬────┘ │
     │         │            │      │
     │         ▼            │      │
     │        END    回到 Agent ────┘
     │               (最多重写3次)
```

### 5.2 各节点配置

| 节点 | 超时 | 重试 | 说明 |
|------|------|------|------|
| Agent Node | 60s | 2次 | 决定是否调用检索工具 |
| Retrieve Node | — | 3次 | 执行混合检索 |
| Grade Node | — | — | LLM 结构化输出判断文档相关性 |
| Rewrite Node | — | — | 优化查询以提升检索质量（最多3轮） |
| Generate Node | 120s | 2次 | 基于上下文生成 PHM 诊断报告 |
| Intent Classifier | 10s | 2次 | 意图分类：rag_query / general_chat |

### 5.3 快速模式性能实测

| 查询 | 检索 | 生成 | 总耗时 | 回答长度 |
|------|------|------|--------|---------|
| 发动机振动偏高 | 2,397 ms | 7,389 ms | 10,206 ms | 719 chars |
| 液压系统压力低 | 19 ms | 7,432 ms | 7,452 ms | 642 chars |
| 起落架收放超时 | 14 ms | 8,453 ms | 8,468 ms | 1,146 chars |

> 性能瓶颈：LLM 生成约占 85-95% 的总耗时（单次推理 6-8.5 秒），检索热启动仅 14-20 ms。

---

## 6. Prompt 工程

### 6.1 生成节点 Prompt

系统 Prompt 采用 PHM 结构化输出模板，要求模型严格按以下格式输出：

```
【诊断结论】...
【可能原因】1. ...
【排查步骤】1. ...
【风险与安全提示】...
【依据来源】1. 来源:... | 标题:... | 证据:...
【信息缺口】...
```

核心规则：
1. 仅使用上下文信息，不编造
2. 优先引用故障代码、ATA 章节、参数阈值、排故步骤
3. 每条依据标注来源
4. 存在安全风险时给出风险提示
5. 信息不足时列出缺失数据

### 6.2 查询重写 Prompt

当文档评分不通过时，Rewrite 节点优化用户查询，补全可检索要素（系统/部件、故障现象、故障代码、ATA 章节、运行工况）。

### 6.3 文档评分 Prompt

二元评分（相关/不相关），基于文档是否包含相关系统/部件、故障现象、故障代码、ATA 章节、排故流程等要素。

---

## 7. 容错与降级机制

### 7.1 断路器（Circuit Breaker）

| 参数 | LLM 服务 | 检索服务 |
|------|---------|---------|
| 失败阈值 | 3 次 | 5 次 |
| 恢复超时 | 60s | 30s |
| 半开最大调用 | 3 次 | 3 次 |
| 成功恢复阈值 | 2 次 | 2 次 |

### 7.2 重试策略

| 参数 | 数值 |
|------|------|
| 最大重试次数 | 3 |
| 基础延迟 | 1.0s |
| 最大延迟 | 60s |
| 指数基数 | 2.0 |
| 抖动 | 启用 |
| 可重试异常 | ConnectionError, TimeoutError |

### 7.3 降级模式

| 模式 | 说明 |
|------|------|
| FULL | 正常运行 |
| CACHED_ONLY | 仅返回缓存响应 |
| SIMPLIFIED | 简化响应 |
| OFFLINE | 最小离线模式 |

降级缓存 TTL：3600 秒（1 小时）

---

## 8. 会话管理

| 参数 | 数值 |
|------|------|
| 主存储 | Redis（`redis://localhost:6379/0`） |
| 备用存储 | SQLite（`./data/sessions.db`） |
| 每会话最大消息数 | 50 |
| 连接池大小 | 5 |
| Key 前缀 | `rag:session:` |

---

## 9. API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 同步对话（支持 thinking/fast 模式） |
| POST | `/api/chat/stream` | SSE 流式对话 |
| GET | `/api/chat/history/{session_id}` | 获取历史记录 |
| DELETE | `/api/chat/session/{session_id}` | 清除会话 |
| GET | `/api/chat/prompt-status` | Prompt 状态 |
| POST | `/api/documents/upload` | 上传文档（md/txt/pdf） |
| GET | `/api/documents` | 文档列表 |
| DELETE | `/api/documents/{doc_id}` | 删除文档 |
| POST | `/api/documents/reindex` | 重建索引 |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions` | 创建会话 |
| GET | `/health` | 健康检查 |
| GET | `/metrics` | 系统指标 |

---

## 10. 前端技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4.0 | 前端框架 |
| Vite | 5.0.0 | 构建工具 |
| TypeScript | — | 类型安全 |
| Pinia | 2.1.0 | 状态管理 |
| Vue Router | 4.2.0 | 路由 |
| Axios | 1.6.0 | HTTP 客户端 |
| Marked | 11.0.0 | Markdown 渲染 |
| Highlight.js | 11.9.0 | 代码高亮 |
| DOMPurify | 3.3.2 | XSS 防护 |

---

## 11. 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| LangChain | ≥1.0.0 | LLM 编排框架 |
| LangGraph | ≥1.0.0 | 有状态工作流 |
| langchain-openai | — | OpenAI 兼容接口 |
| langchain-huggingface | — | 本地 Embedding |
| pymilvus | ≥2.5.0 | Milvus Python SDK |
| milvus-lite | ≥2.5.0 | 轻量级向量数据库 |
| sentence-transformers | ≥3.0.0 | Embedding 模型 |
| FastAPI | ≥0.109.0 | Web 框架 |
| uvicorn | ≥0.27.0 | ASGI 服务器 |
| pydantic | ≥2.0.0 | 数据校验 |
| loguru | ≥0.7.0 | 日志 |

---

## 12. 硬件资源占用

| 资源 | 占用 | 总量 | 利用率 |
|------|------|------|--------|
| GPU 显存 | 12 GB | 16 GB | 75% |
| GPU 温度 | 32°C | — | 正常 |
| Embedding 模型 | ~91 MB（内存） | — | CPU 运行 |
| Milvus 数据库 | ~230 KB | — | 本地文件 |
| 模型文件 | 9.3 GB（磁盘） | — | GGUF Q4_K_M |

---

## 13. 优化建议

### 13.1 LLM 性能优化

- **模型已升级**：从 Qwen3-8B（6.5GB 显存）升级至 Qwen3-14B（12GB 显存），参数量提升 80%，充分利用 RTX 5070 Ti 16GB 显存
- **调整采样参数**：当前 Temperature=0.0，官方推荐思考模式用 0.6、非思考模式用 0.7
- **Qwen3 Thinking 已集成**：Thinking 模式已开启推理过程捕获（通过 OpenAI SDK 直接读取 `reasoning` 字段），Fast 模式通过 `/no_think` 关闭推理以降低延迟

### 13.2 检索质量优化

- **升级 Embedding**：bge-small-zh-v1.5（512维）→ bge-large-zh-v1.5（1024维）或 bge-m3（多语言）
- **两阶段重排序已接入**：Dense 与 BM25 扩大候选召回，经 RRF 融合后可选 Cross-Encoder 重排序；接口保留 `retrieval_score`、`rerank_score` 和 `rerank_applied` 便于排障
- **中文 Reranker 选型**：默认 MiniLM 模型轻量但主要面向英文，中文 PHM 场景应评估 `BAAI/bge-reranker-base` 等中文或多语言模型
- **增大上下文窗口**：当前 2,500 字符截断偏小，建议提升至 4,000-6,000 字符
- **优化 BM25**：当前 BM25 召回为 0（中文分词未生效），需引入 jieba 分词

### 13.3 架构优化

- **意图分类去 LLM 化**：当前已实现关键词快捷路由，但仍走 LLM 回退路径，可完全改为规则匹配
- **文档评分去 LLM 化**：用 embedding 相似度替代 LLM 评分，节省一次推理
- **原生异步执行已完成**：Agent Skill 使用 LangGraph `ainvoke/astream`，SQLite checkpoint 使用 `AsyncSqliteSaver`，同步 Milvus 操作通过受控线程边界执行
- **Thinking 模式真正流式输出已完成**：Generate Skill 使用 LangGraph custom stream 将生成文本增量透传至 SSE，并记录首 Token 延迟（TTFT）
- **OpenTelemetry 已接入**：支持 FastAPI HTTP Span、Agent Skill Span 与 OTLP/HTTP 导出，可对接 Jaeger、Tempo 或 OpenTelemetry Collector
- **压测能力已补充**：`scripts/load_test.py` 可统计并发请求成功率、吞吐量、P50/P95/P99 与 TTFT

---

## 参考文献

- [Qwen3 Technical Report (arXiv:2505.09388)](https://arxiv.org/abs/2505.09388)
- [Qwen3-14B Model Card (HuggingFace)](https://huggingface.co/Qwen/Qwen3-14B)
- [Qwen3 Blog: Think Deeper, Act Faster](https://qwenlm.github.io/blog/qwen3/)
- [BGE Embedding Models (BAAI)](https://huggingface.co/BAAI/bge-small-zh-v1.5)
- [Milvus Lite Documentation](https://milvus.io/docs/milvus_lite.md)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
