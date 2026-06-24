# core/AGENTS.md — 基础设施专属规范

> 本文件补充根 `AGENTS.md`，仅当工作目录在 `core/` 子树下时由 Agent 加载。
> 全局纪律见根 `AGENTS.md`，此处聚焦检索栈、降级矩阵、熔断器、内存与会话。

## 1. 目录职责

```
core/
├── retrieval/        # hybrid/bm25/reranker/mmr/cache/time_decay/query_transform
├── fallback/         # circuit_breaker / retry / degradation
├── memory/           # 会话记忆（Redis 可选 / SQLite 自动降级）
├── prompts/          # aircraft_prompts.py 是 Prompt 单一事实来源
├── intent/           # 意图分类
├── tracing/          # OpenTelemetry
├── context/          # token_budget
├── concurrency/      # 并发原语
└── workflow/         # 编排辅助
```

## 2. 检索栈

- **Dense（Milvus Lite）+ BM25（`core/retrieval/bm25_retriever.py`，单例）+ RRF** 融合。
- 可选 **Cross-encoder reranker**、**MMR**、**time-decay**、**结果缓存**、**query_transform**（HyDE/multi_query）。
- BM25 单例引导：仅在为空时重跑；`add_documents` / `remove_by_source` 必须触发缓存失效（index-version 命名空间自增），防止单例陈旧。

## 3. Graceful Degradation 矩阵（强制不变量）

每个热路径组件都必须：尝试好路径 → 失败时 `log` 并降级为更弱但安全的策略 → **绝不向外抛**。
「不可用」**永远不得**报告为 0 分（会污染置信度与回归门禁）。

| 组件 | 失败形态 | 降级 | 位置 |
|------|----------|------|------|
| 混合检索 | dense/sparse 腿抛错 | `gather(return_exceptions=True)`，失败腿返回空，继续用存活腿；整体失败 → dense-only；dense 失败 → `[]` | `core/retrieval/hybrid_retriever.py` |
| Cross-encoder reranker | 未启用/抛错 | 保持 RRF 顺序 `documents[:top_k]`，`rerank_applied=false` | 同上 |
| MMR | 向量不可用 | 原样返回 | 同上 |
| time-decay | 抛错 | 原样返回 | 同上 |
| 检索结果缓存 | 读/写抛错 | 跳过缓存，落到实时检索 | 同上 |
| 在线 grounding | 任何失败 | 返回 `degraded=True`，**永不抛** | `agent/guardrails/grounding_guardrail.py` |
| LLM judge | 连续 N 次失败 | 熔断 → `available=False` → 指标变 `None` → 规则评分兜底 | `agent/eval/judge.py` |
| 复合置信度 | grounding 为 `None` | 把 grounding 权重重分配给 retrieval，标记 `degraded=True` | `agent/skills/generate/skill.py` `_compute_confidence` |
| generate LLM 调用 | OpenAI SDK 抛错 | 重试退避 → LangChain 兜底 → 固定错误文案 | 同上 |
| MCP 组装 | 抛错 | AgentSkill 回退到独立 retriever 工具 | `agent/harness/orchestrator.py` `_build_mcp_client` |
| 会话存储 | Redis 不可达 | 自动降级到 SQLite | `core/memory` |

**违规修复**：若某热路径组件缺失降级分支，新增组件时必须补上；测试必须有「不可用≠0 分」+「降级路径」断言（根 AGENTS.md §7）。

## 4. 熔断器（按依赖分别调参，不要合并）

| 依赖 | 阈值 | 恢复 | 位置 |
|------|------|------|------|
| LLM | 3 次失败 | 60s | `core/fallback/circuit_breaker.py` |
| retriever | 5 次失败 | 30s | 同上 |
| judge 内部 `_FailureTracker` | 5 次失败 | — | `agent/eval/judge.py` |

## 5. Prompt 单一来源

- `core/prompts/aircraft_prompts.py` 是事实来源；技能级 `prompts.py` 仅 re-export。
- `api/main.py` 启动时记录 prompt sha1 签名用于行为可追溯。
- 改 prompt 后必须重算 sha1 并更新签名表（影响 golden/snapshot test）。
