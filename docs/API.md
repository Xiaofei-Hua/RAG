# RAG 智能问答平台 — 接口文档

> Base URL: `http://{host}:8000`
>
> 本文档供外部系统集成使用，涵盖所有 HTTP 接口、请求/响应格式及 SSE 流式协议。

---

## 目录

- [1. 通用约定](#1-通用约定)
- [2. 智能问答](#2-智能问答)
  - [2.1 发送消息（非流式）](#21-发送消息非流式)
  - [2.2 发送消息（SSE 流式）](#22-发送消息sse-流式)
  - [2.3 获取对话历史](#23-获取对话历史)
  - [2.4 清除会话](#24-清除会话)
  - [2.5 查询 Prompt 状态](#25-查询-prompt-状态)
- [3. 文档管理](#3-文档管理)
  - [3.1 上传文档](#31-上传文档)
  - [3.2 文档列表](#32-文档列表)
  - [3.3 文档详情](#33-文档详情)
  - [3.4 删除文档](#34-删除文档)
  - [3.5 重建索引](#35-重建索引)
- [4. 会话管理](#4-会话管理)
  - [4.1 创建会话](#41-创建会话)
  - [4.2 会话列表](#42-会话列表)
  - [4.3 会话详情](#43-会话详情)
  - [4.4 删除会话](#44-删除会话)
  - [4.5 延长会话有效期](#45-延长会话有效期)
- [5. 系统监控](#5-系统监控)
  - [5.1 基础健康检查](#51-基础健康检查)
  - [5.2 详细健康检查](#52-详细健康检查)
  - [5.3 系统指标](#53-系统指标)
  - [5.4 熔断器状态](#54-熔断器状态)
  - [5.5 重置熔断器](#55-重置熔断器)
  - [5.6 降级状态](#56-降级状态)
  - [5.7 设置降级模式](#57-设置降级模式)
  - [5.8 系统配置](#58-系统配置)

---

## 1. 通用约定

### 响应头

| Header | 说明 |
|--------|------|
| `X-Trace-ID` | 请求追踪 ID，全链路唯一 |
| `X-Response-Time-Ms` | 服务端处理耗时（毫秒） |

### 错误响应格式

所有接口在出错时返回统一格式：

```json
{
  "detail": "错误描述信息"
}
```

HTTP 状态码：`4xx` 客户端错误，`5xx` 服务端错误。

---

## 2. 智能问答

### 2.1 发送消息（非流式）

```
POST /api/chat
```

发送用户消息，同步返回完整回答。

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `message` | string | 是 | — | 用户消息，最少 1 字符 |
| `session_id` | string | 否 | `null` | 会话 ID，用于多轮对话。不传则新建会话 |
| `stream` | boolean | 否 | `false` | 是否启用流式输出（本接口始终为 false） |
| `include_sources` | boolean | 否 | `true` | 是否在响应中包含来源文档 |
| `mode` | string | 否 | `"thinking"` | 回答模式：`"thinking"` 或 `"fast"` |

**`mode` 说明：**

| 值 | 说明 | LLM 调用次数 | 适用场景 |
|----|------|--------------|----------|
| `thinking` | 深度思考模式，经过意图分析 → Agent → 检索 → 文档评估 → 生成完整流程 | 4+ | 需要高精度诊断的场景 |
| `fast` | 快速模式，直接检索知识库 + 生成回答，跳过意图分类与文档评估 | 1 | 需要快速响应的场景 |

#### 响应体

```json
{
  "response": "航空发动机振动异常的诊断结论...",
  "session_id": "session_abc123",
  "intent": "rag_query",
  "sources": [
    {
      "content": "相关文档片段...",
      "source": "engine_manual.md",
      "title": "发动机维修手册",
      "score": 0.87
    }
  ],
  "processing_time_ms": 3520.5,
  "metadata": {
    "intent_confidence": 0.95,
    "intent_reasoning": "故障诊断类技术问题",
    "source_count": 3,
    "diagnosis": {
      "conclusion": "发动机振动值超标...",
      "possible_causes": ["轴承磨损", "叶片不平衡"],
      "troubleshooting_steps": ["检查振动传感器", "进行动平衡测试"],
      "safety_risks": "振动持续超标可能导致...",
      "evidence_sources": ["来源: engine_manual.md"],
      "info_gaps": "缺少历史振动趋势数据"
    },
    "route": "rag",
    "prompt_profile": "phm_diagnosis_v1",
    "force_rag": false
  }
}
```

#### 响应字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `response` | string | AI 回答内容 |
| `session_id` | string | 会话 ID（首次请求会自动生成） |
| `intent` | string | 检测到的意图：`rag_query` / `general_chat` / `degraded` |
| `sources` | SourceDocument[] | 参考来源文档列表 |
| `processing_time_ms` | float | 总处理耗时（毫秒） |
| `metadata.route` | string | 路由类型：`rag` / `general_chat` / `fast` |
| `metadata.prompt_profile` | string | Prompt 配置标识 |
| `metadata.diagnosis` | PHMDiagnosis \| null | PHM 结构化诊断数据（仅 RAG 模式） |

**`metadata.route` 取值说明：**

| 值 | 说明 |
|----|------|
| `rag` | 深度思考模式，经过完整 RAG 流程 |
| `general_chat` | 通用闲聊，直接 LLM 回答 |
| `fast` | 快速检索模式，直接检索 + 生成 |
| `degraded` | 降级模式，服务异常时的兜底回答 |

---

### 2.2 发送消息（SSE 流式）

```
POST /api/chat/stream
```

发送用户消息，通过 Server-Sent Events (SSE) 流式返回回答。请求体与非流式接口完全相同。

#### 请求体

与 [2.1 发送消息（非流式）](#21-发送消息非流式) 相同。

#### 响应

`Content-Type: text/event-stream`

每个事件格式为：

```
data: {JSON}\n\n
```

#### SSE 事件类型

##### session — 会话信息（首个事件）

```json
{
  "type": "session",
  "session_id": "session_abc123"
}
```

##### intent — 意图分类结果

```json
{
  "type": "intent",
  "intent": "rag_query",
  "confidence": 0.95,
  "route": "rag",
  "force_rag": false
}
```

快速模式下：`"intent": "rag_query", "confidence": 1.0, "route": "fast"`

##### status — 处理状态提示

```json
{
  "type": "status",
  "message": "正在检索知识库..."
}
```

| message 取值 | 说明 |
|-------------|------|
| `正在分析意图...` | 意图分类中（仅 thinking 模式） |
| `正在检索知识库...` | 向量检索中 |
| `正在评估文档相关性...` | 文档评估中（仅 thinking 模式） |
| `正在优化查询...` | 查询改写中（仅 thinking 模式） |
| `正在生成回答...` | LLM 生成中 |
| `检测为PHM技术问题，已切换知识库诊断模式...` | 意图覆盖提示 |

##### node — 当前执行节点

```json
{
  "type": "node",
  "name": "agent"
}
```

| name 取值 | 说明 |
|-----------|------|
| `agent` | Agent 节点（仅 thinking 模式） |
| `retrieve` | 检索节点 |
| `grade` | 文档评估节点（仅 thinking 模式） |
| `rewrite` | 查询改写节点（仅 thinking 模式） |
| `generate` | 生成节点（仅 thinking 模式） |
| `fast_generate` | 快速生成节点（仅 fast 模式） |

##### token — 流式内容片段

```json
{
  "type": "token",
  "content": "根据"
}
```

`content` 为增量文本片段，前端应追加显示。每个 token 事件只包含一小段文字。

##### done — 完成信号

```json
{
  "type": "done",
  "full_response": "完整回答内容...",
  "sources": [
    {
      "content": "文档片段...",
      "source": "manual.md",
      "title": "维修手册",
      "score": 0.85
    }
  ],
  "processing_time_ms": 3520.5,
  "metadata": {
    "intent_confidence": 0.95,
    "intent_reasoning": "...",
    "source_count": 3,
    "diagnosis": null,
    "route": "rag",
    "prompt_profile": "phm_diagnosis_v1",
    "force_rag": false
  }
}
```

> 收到 `done` 事件后流结束。`full_response` 为完整回答，可用其替换之前累积的 token。

##### error — 错误

```json
{
  "type": "error",
  "message": "错误描述"
}
```

#### SSE 集成示例

**Python (httpx)：**

```python
import httpx
import json

def chat_stream(message: str, session_id: str = None, mode: str = "thinking"):
    url = "http://localhost:8000/api/chat/stream"
    payload = {"message": message, "mode": mode}
    if session_id:
        payload["session_id"] = session_id

    with httpx.stream("POST", url, json=payload, timeout=120) as resp:
        for line in resp.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                if event["type"] == "token":
                    print(event["content"], end="", flush=True)
                elif event["type"] == "done":
                    return event

result = chat_stream("发动机振动异常如何排查？")
```

**JavaScript (fetch)：**

```javascript
async function chatStream(message, sessionId = null, mode = 'thinking') {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      session_id: sessionId,
      stream: true,
      mode,
    }),
  });

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));
        if (event.type === 'token') {
          // 追加显示 event.content
        } else if (event.type === 'done') {
          // 完成，event.full_response 为完整回答
        }
      }
    }
  }
}
```

---

### 2.3 获取对话历史

```
GET /api/chat/history/{session_id}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 会话 ID |

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `limit` | integer | 20 | 返回消息数量上限 |

#### 响应体

```json
{
  "session_id": "session_abc123",
  "messages": [
    { "role": "user", "content": "发动机振动异常如何排查？" },
    { "role": "assistant", "content": "根据知识库检索结果..." }
  ],
  "total_messages": 4
}
```

---

### 2.4 清除会话

```
DELETE /api/chat/session/{session_id}
```

#### 响应体

```json
{
  "status": "success",
  "message": "Session session_abc123 cleared"
}
```

---

### 2.5 查询 Prompt 状态

```
GET /api/chat/prompt-status
```

用于集成方验证当前加载的 Prompt 配置版本。

#### 响应体

```json
{
  "loaded": true,
  "prompt_profile": "phm_diagnosis_v1",
  "generate_prompt_signature": "0df94211b3ee",
  "generate_prompt_preview": "你是地面健康管理（PHM）平台中的航空故障诊断助手..."
}
```

---

## 3. 文档管理

### 3.1 上传文档

```
POST /api/documents/upload
```

上传文档到知识库，后台自动进行分块、向量化并存入 Milvus。

#### 请求

`Content-Type: multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 文档文件，支持 `.md`、`.txt`、`.pdf` |

#### 响应体

```json
{
  "id": "988f849c",
  "filename": "engine_manual.md",
  "status": "processing",
  "message": "Document uploaded and processing started"
}
```

| status 值 | 说明 |
|-----------|------|
| `processing` | 已接收，后台处理中 |
| `duplicate` | 文件已存在（HTTP 409） |

---

### 3.2 文档列表

```
GET /api/documents
```

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` | integer | 0 | 跳过条数 |
| `limit` | integer | 20 | 返回条数 |

#### 响应体

```json
{
  "documents": [
    {
      "id": "988f849c",
      "filename": "engine_manual.md",
      "status": "completed",
      "chunks": 12,
      "created_at": 1713696000.0,
      "size_bytes": 15360,
      "file_hash": "6a06a695c5d26b41..."
    }
  ],
  "total": 5
}
```

---

### 3.3 文档详情

```
GET /api/documents/{doc_id}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 文档 ID |

#### 响应体

与 [3.2 文档列表](#32-文档列表) 中单个文档对象格式相同。

---

### 3.4 删除文档

```
DELETE /api/documents/{doc_id}
```

从文档注册表、Milvus 向量库和 BM25 索引中同步删除。

#### 响应体

```json
{
  "status": "success",
  "message": "Document 988f849c deleted"
}
```

---

### 3.5 重建索引

```
POST /api/documents/reindex
```

重新扫描 `md/` 目录下所有 Markdown 文件并重建向量索引。后台异步执行。

#### 响应体

```json
{
  "status": "success",
  "message": "Reindexing started in background"
}
```

---

## 4. 会话管理

### 4.1 创建会话

```
POST /api/sessions
```

#### 响应体

```json
{
  "session_id": "session_abc123",
  "message": "Session created successfully"
}
```

---

### 4.2 会话列表

```
GET /api/sessions
```

#### 查询参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` | integer | 0 | 跳过条数 |
| `limit` | integer | 20 | 返回条数 |

#### 响应体

```json
{
  "sessions": [
    {
      "session_id": "session_abc123",
      "message_count": 6,
      "ttl_seconds": 3600,
      "created_at": 1713696000.0,
      "last_active": 1713699600.0
    }
  ],
  "total": 3
}
```

---

### 4.3 会话详情

```
GET /api/sessions/{session_id}
```

#### 响应体

与 [4.2 会话列表](#42-会话列表) 中单个会话对象格式相同。

---

### 4.4 删除会话

```
DELETE /api/sessions/{session_id}
```

#### 响应体

```json
{
  "status": "success",
  "message": "Session session_abc123 deleted"
}
```

---

### 4.5 延长会话有效期

```
POST /api/sessions/{session_id}/extend
```

#### 响应体

```json
{
  "status": "success",
  "message": "Session session_abc123 extended"
}
```

---

## 5. 系统监控

### 5.1 基础健康检查

```
GET /health
```

#### 响应体

```json
{
  "status": "healthy",
  "timestamp": 1713696000.0,
  "circuits": {
    "llm": "closed",
    "retriever": "closed"
  }
}
```

---

### 5.2 详细健康检查

```
GET /api/admin/health
```

包含各子服务的详细状态。

#### 响应体

```json
{
  "status": "healthy",
  "services": {
    "llm": {
      "status": "healthy",
      "circuit": "closed",
      "stats": {
        "success_count": 42,
        "failure_count": 0,
        "failure_rate": 0.0,
        "last_failure_time": 0.0
      }
    },
    "retriever": {
      "status": "healthy",
      "circuit": "closed",
      "stats": { "..." : "..." }
    },
    "milvus": {
      "status": "healthy",
      "details": { "..." : "..." }
    }
  }
}
```

---

### 5.3 系统指标

```
GET /api/admin/metrics
```

#### 响应体

```json
{
  "timestamp": 1713696000.0,
  "memory": {
    "rss_mb": 256.5,
    "vms_mb": 512.0
  },
  "gc": {
    "gen_0": { "collections": 120, "collected": 850, "uncollectable": 0 }
  },
  "python": { "version": "3.13.0" }
}
```

---

### 5.4 熔断器状态

```
GET /api/admin/circuit-breakers
```

#### 响应体

```json
{
  "llm": {
    "success_count": 42,
    "failure_count": 0,
    "failure_rate": 0.0,
    "last_failure_time": 0.0
  },
  "retriever": { "..." : "..." }
}
```

---

### 5.5 重置熔断器

```
POST /api/admin/circuit-breakers/{name}/reset
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | string | 熔断器名称：`llm` 或 `retriever` |

#### 响应体

```json
{
  "status": "success",
  "message": "LLM circuit breaker reset"
}
```

---

### 5.6 降级状态

```
GET /api/admin/degradation
```

#### 响应体

```json
{
  "mode": "normal",
  "fallback_mode": "static_response",
  "metrics": { "..." : "..." }
}
```

---

### 5.7 设置降级模式

```
POST /api/admin/degradation/mode/{mode}
```

#### 路径参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `mode` | string | 降级模式：`normal` / `degraded` / `fallback` |

#### 响应体

```json
{
  "status": "success",
  "mode": "normal"
}
```

---

### 5.8 系统配置

```
GET /api/admin/config
```

#### 响应体

```json
{
  "milvus": {
    "uri": "./milvus_data.db",
    "collection": "t_collection01"
  },
  "session": {
    "ttl": 3600,
    "max_messages": 50
  }
}
```

---

## 附录 A：数据结构

### ChatRequest

```typescript
interface ChatRequest {
  message: string              // 必填，用户消息
  session_id?: string          // 可选，会话 ID
  stream?: boolean             // 默认 false
  include_sources?: boolean    // 默认 true
  mode?: "thinking" | "fast"   // 默认 "thinking"
}
```

### ChatResponse

```typescript
interface ChatResponse {
  response: string
  session_id: string
  intent: string               // "rag_query" | "general_chat" | "degraded"
  sources: SourceDocument[]
  processing_time_ms: number
  metadata: {
    intent_confidence: number
    intent_reasoning: string
    source_count: number
    diagnosis: PHMDiagnosis | null
    route: "rag" | "general_chat" | "fast" | "degraded"
    prompt_profile: string
    force_rag: boolean
  }
}
```

### SourceDocument

```typescript
interface SourceDocument {
  content: string
  source?: string
  title?: string
  score: number
}
```

### PHMDiagnosis

```typescript
interface PHMDiagnosis {
  conclusion: string
  possible_causes: string[]
  troubleshooting_steps: string[]
  safety_risks: string
  evidence_sources: string[]
  info_gaps: string
}
```

### DocumentInfo

```typescript
interface DocumentInfo {
  id: string
  filename: string
  status: string               // "processing" | "completed" | "failed"
  chunks: number
  created_at: number           // Unix 时间戳
  size_bytes: number
  file_hash: string
}
```

### SessionInfo

```typescript
interface SessionInfo {
  session_id: string
  message_count: number
  ttl_seconds: number
  created_at: number
  last_active: number
}
```

---

## 附录 B：快速模式 vs 深度模式流程对比

```
深度思考模式 (mode="thinking"):
  用户消息 → 意图分类(LLM) → Agent决策(LLM) → 向量检索 → 文档评估(LLM) → 生成回答(LLM)
             ──────────────────────────────────────────────────────────────────────────────
             约 4+ 次 LLM 调用，耗时 15~30 秒，精度高

快速模式 (mode="fast"):
  用户消息 → 向量检索 → 生成回答(LLM)
             ──────────────────────────
             仅 1 次 LLM 调用，耗时 3~8 秒，速度快
```
