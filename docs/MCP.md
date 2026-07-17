# RAG MCP 工具契约

本文档描述仓库内的 MCP（Model Context Protocol）检索工具。当前实现是**进程内 MCP**：
`MCPClient` 直接注册并调用 `MCPRetrievalServer`，没有独立网络监听端口，也不是 HTTP API。
HTTP 集成请使用 [API.md](API.md)。

## 1. Server and lifecycle

- Server name：`rag-retrieval-server`
- 实现：`agent/mcp/retrieval_server.py`
- 客户端：`agent/mcp/client.py`
- Thinking 的 `RetrieveSkill` 可通过 MCP 调用 `rag_retrieve`；调用失败时回退到同一个
  共享 `RetrievalWorkflow`，不会让聊天热路径向外抛异常。
- `MCPClient.call_tool()` 成功时返回工具的实际结果；直接调用
  `InProcessMCPServer.call_tool()` 时，外层是 `MCPToolResult(success, result, error)`。

## 2. Tools

| Tool | 输入 | 输出 | 说明 |
|---|---|---|---|
| `rag_retrieve` | `query`、可选 `top_k`/`filter_expr`/`transform` | 默认 `{documents, diagnostics}`；legacy 为文档数组 | 共享自适应/纠正工作流 |
| `rag_search_dense` | `query`、可选 `top_k` | 文档数组 | Milvus dense-only，绕过高层 workflow |
| `rag_search_sparse` | `query`、可选 `top_k` | 文档数组 | 共享 BM25 索引的 sparse-only 检索 |

`top_k` 默认值为 `4`。`query` 为唯一必填字段。

### 2.1 `rag_retrieve` input

```json
{
  "query": "git 合并冲突如何解决",
  "top_k": 4,
  "filter_expr": "source == \"git_guide.md\"",
  "transform": "multi_query"
}
```

- `filter_expr` 会进入 typed `FilterScope`。非法表达式返回 filtered-empty；无法执行该过滤的
  通道会被排除，系统绝不会删除过滤条件后重试。
- `transform` 是 legacy 兼容字段。默认 workflow 开启时由 planner 自行决定 query transform；
  只有 `RETRIEVAL_WORKFLOW_ENABLED=false` 时才直接采用调用方的 `hyde` / `multi_query`。

### 2.2 Default output (`RETRIEVAL_WORKFLOW_ENABLED=true`)

```json
{
  "documents": [
    {
      "index": 1,
      "content": "相关证据片段",
      "source": "git_guide.md",
      "title": "合并冲突排查",
      "score": 0.87,
      "parent_id": "section-12"
    }
  ],
  "diagnostics": {
    "plan": {
      "query_type": "procedure",
      "budgets": {
        "candidate_k": 10,
        "rerank_k": 4,
        "selection_k": 4,
        "final_k": 4,
        "retry_budget": 1
      }
    },
    "state": "accept",
    "should_generate": true,
    "retry_action": null,
    "degraded": false,
    "document_count": 1,
    "channel_counts": {},
    "optional_channel_status": {},
    "primary_channel_status": {},
    "retrieval_identity": "...",
    "retrieval_cache_hit": false,
    "uncovered_facets": [],
    "filter_kind": "source_set",
    "filter_fingerprint": "...",
    "elapsed_ms": 42.1
  }
}
```

`diagnostics` 只包含脱敏后的计划、状态、计数、能力和单向 fingerprint；不会包含 query vector、
文档正文副本、原始 filter、绝对资产路径或模型密钥。字段可随 schema 演进增加，调用方应忽略
未知字段。

终态语义：

| `state` | `should_generate` | 含义 |
|---|---:|---|
| `accept` | `true` | 证据足够，可进入生成 |
| `weak` | `false` | 相关性、评分或 facet 覆盖不足 |
| `conflict` | `false` | 同一文档族存在无法自动消解的结构化版本冲突 |
| `empty` | `false` | 无可用证据、filter 非法或没有健康通道 |

### 2.3 Legacy output (`RETRIEVAL_WORKFLOW_ENABLED=false`)

```json
[
  {
    "index": 1,
    "content": "相关证据片段",
    "source": "git_guide.md",
    "title": "合并冲突排查",
    "score": 0.87,
    "parent_id": "section-12"
  }
]
```

这是旧的 list-only 契约。外部调用方迁移时应优先识别默认对象形态，并在需要支持回滚时兼容数组：

```python
raw = await client.call_tool("rag_retrieve", arguments)
documents = raw.get("documents", []) if isinstance(raw, dict) else raw
diagnostics = raw.get("diagnostics") if isinstance(raw, dict) else None
```

## 3. Dense and sparse outputs

`rag_search_dense` 与 `rag_search_sparse` 始终返回文档数组，元素字段与上面的 `documents[]`
相同。它们是显式低层检索工具，不执行 planner、corrective state 或终止判定。

## 4. Feature flags and degradation

- `RETRIEVAL_WORKFLOW_ENABLED=true`：默认对象契约与共享终态语义。
- `COLBERT_RERANK_ENABLED=false`、`RAPTOR_ENABLED=false`、`GRAPH_PPR_ENABLED=false`、
  `COLPALI_ENABLED=false`：可选通道默认关闭。
- 可选模型缺失、OOM 或索引不可用时，通道不贡献结果并记录 unavailable/degraded；不会把
  “不可用”伪造成 0 分。
- `RETRIEVAL_WORKFLOW_ENABLED=false`：只回滚检索编排和返回形态，不删除 Milvus、RAPTOR
  或视觉索引。

完整架构、benchmark 与 promotion 依据见：

- [Retrieval frontier design](specs/retrieval-frontier-optimization/design.md)
- [Retrieval frontier benchmark](specs/retrieval-frontier-optimization/benchmark-results.md)
- [Retrieval baseline matrix](specs/retrieval-benchmark-expansion/benchmark-results.md)
