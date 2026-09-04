# Frontend Contract Hardening Design

- **Feature**: `frontend-contract-hardening`
- **Requirements**: [requirements.md](requirements.md)
- **Status**: v2 addressing independent review gates

## 1. Architecture and Data Flow

```text
LLM generation attempt
  -> IncrementalThinkFilter (attempt-local)
  -> public token chunks
  -> non-empty terminal guard
  -> atomic history exchange + public metadata/source projection
  -> SSE done / ChatResponse

history GET -> Redis + SQLite dual read -> stable merge/dedupe
            -> SessionReadResult(available, complete, degraded, backend)
feedback POST -> to_thread(SQLite BEGIN IMMEDIATE + existing lookup)
              -> created? side effects : no-op
```

过滤器是每次**生成尝试**创建的局部对象，禁止放入 LLM/harness 单例。直接 general、Fast、RAG generate 与 fallback general 分别拥有独立实例。同步与流式都调用同一解析器；旧正则不再承担安全边界。

## 2. State Contracts

### 2.1 Incremental filter

- Grammar 大小写不敏感：opening 为 `<think>` 或 `<think` + whitespace + attributes + `>`；closing 为 `</think` + optional whitespace + `>`。opening 可嵌套并以 depth 计数。
- 一旦识别 `<think` 后的合法 delimiter 即进入隐藏态，不等待完整 `>`；未闭合、嵌套未归零、超出 256 字符的 tag 均在 `finish()` 时 fail closed 丢弃。
- `push(chunk) -> str` 只保留可能构成标签的最短尾缀；隐藏态不累计 reasoning 正文，总缓冲上限 256 字符。
- `finish() -> str` 只允许释放一次公开尾缀；重复调用返回空，finish 后 push 视为调用错误且不得发射原文。
- `sanitize_model_text(text)` 用新实例执行 `push()+finish()`，作为同步、snapshot 与配置固定回答的同源入口。

### 2.2 Generation ownership and unique emit points

| Path | Filter owner | Authoritative public text |
|---|---|---|
| sync general / RAG / Fast | 路由或 Fast helper 的单次生成 | `sanitize_model_text` 结果 |
| stream general | 该次 `llm.astream` | filter 输出 token 的累积 |
| stream Fast | `fast_generate_stream` | helper 的 filtered token + `done.full_response` |
| stream RAG | `GenerateSkill` 当前模型调用 | public custom token 与 sanitized final snapshot 进行前缀一致性裁决 |
| stream fallback general | 新建 filter，绝不复用 RAG attempt | fallback filter 输出 token 的累积 |

路由不得以未过滤 snapshot 覆盖已经发送的 token；Fast 外层透传 error，并以 helper 的 `done.full_response` 为最终权威值。每个 attempt 恰好调用一次 finish。RAG arbitration 规则：

- 未产生 public custom token 时，采用并发射非空 sanitized final snapshot（覆盖 reasoning-only custom）。
- snapshot 与 public accumulator 相等时不补发；snapshot 以前者为前缀时只补发安全 suffix。
- 其他不一致（包括 snapshot 短于或改写已发正文）产生 SSE error，不发 done、不保存、不 capture，禁止静默截断或覆盖。
- generation attempt 在已发 public token 后异常时不得自动 retry；尚未发 public token 才可用全新 filter 重试。

### 2.3 Empty generation

Fast/general/fallback/RAG 的公开文本 `.strip()` 为空时，SSE 输出 `{type:error,message:"模型未返回可展示内容，请重试"}` 并 return，同步接口返回 HTTP 502 同一安全文案。两者均不保存 exchange、不 capture。已有 empty-corpus/refusal 固定提示经同源 sanitizer 后仍是合法非空回答。

### 2.4 Session persistence and availability

`SessionReadResult(messages, available, complete, degraded, backend)` 是显式返回值。公开 history response 同时带 `contract_version=2`。Redis 与 SQLite 不是主从镜像，而是 primary + failover shards，因此读取规则为：

- Redis 与 SQLite 都配置时始终双读；二者成功后按 `_message_id` 合并去重，`complete=true, backend=combined`，即使任一方为空。
- 仅一方成功时返回其内容，`available=true, complete=false, degraded=true`；这同样覆盖“Redis 空但 SQLite 读失败”，不得声称真空。
- 二者都失败时 `available=false`，history 路由返回 503。
- 缺少 Redis 包或显式注入 SQLite-only store 时，SQLite 是唯一配置源，成功读取可返回 `complete=true, backend=fallback`。

新 exchange 生成 UUID，并把稳定 `_exchange_id` 与 `:user`/`:assistant` `_message_id` 写入两条消息。合并以 `_message_id` 为首选；遗留消息用 type/content/timestamp 的稳定 fingerprint。排序依次使用 `_timestamp`、`_exchange_id`、role order（user 在 assistant 前）与 `_message_id`，裁剪只在合并去重后执行。

`get_messages()` 为聊天热路径保留 list 兼容，并在不可用时降级为 `[]`。history response 增量增加 `complete/degraded/backend`，PHM normalizer 与抽屉展示不完整提示。

生产新增 `save_exchange(session_id, user, assistant) -> SaveExchangeResult`：两条消息先序列化一次。Redis 使用一个 Lua command 同时维护 message list 与同长度的 message-ID list：脚本在最多 50 个 ID 中检查 pair，二者已存在则 no-op、只存在一个则返回 inconsistent、均不存在才 LPUSH+LTRIM 完整 pair；因此 ambiguous reply 后以相同 ID 重放仍物理幂等且原子。session registry 是可由 message list 重建的派生索引，在 pair commit 后 best-effort 更新，不参与 `persisted` 真值。Redis command 异常时，同一 ID/时间戳的完整 pair 在 SQLite 的一个 `BEGIN IMMEDIATE` 事务中重试。每个 backend 内不会出现半个 exchange；双份成功由读取去重吸收。SQLite 增量增加 nullable `_message_id` 列及 partial UNIQUE index，遗留行无需迁移，重试相同 pair 是物理 no-op。

Redis client 配置 connect/read timeout。SQLite read/save/registry/clear 均以 `asyncio.to_thread` 调用同步 helper，连接配置 `busy_timeout=250ms`。API 用 `asyncio.shield` 保留 worker task：1 秒内完成返回 true/false；超时返回 `persisted=null`，注册只消费结果/异常且不把未决状态误报失败。后台迟交由物理 message ID 幂等和双读去重吸收。identity/Fast/general/RAG/takeover/degraded 所有非空返回分支只调用 `save_exchange`。测试 fake 同步增加该方法；`save_message` 仅为其他调用方保留兼容，不作为 chat 路由 fallback。

### 2.5 Feedback idempotency

新增 `FeedbackCollector.record_once(entry) -> (id, created)`。trim 后 session/message 均非空时，在 `BEGIN IMMEDIATE` 事务内按 `timestamp ASC, id ASC` 查首条；存在则返回原 ID，否则插入，异常显式 rollback。用非唯一复合索引加速查询，避免遗留重复数据导致迁移失败。API 通过 `asyncio.to_thread` 调用，避免阻塞 event loop。只有 `created=true` 执行 correction memory 与 flywheel；副作用是 commit 后 at-most-once/best-effort。原 `record()` 与空 message ID 的追加语义保留兼容。

### 2.6 Public projection and sources

内部 `sources` 始终保留给 grounding/capture；只在 HTTP/SSE response assembly 时应用 `request.include_sources`。`source_count` 仍表示实际检索证据数，`sources=[]` 表示调用方选择不接收正文。非流式 Fast 路径保留既有、非敏感的 `retrieval_time_ms`/`generation_time_ms`；前端只消费总 `processing_time_ms`，不依赖这两个可选字段。

`_build_public_metadata()` 固定输出 `contract_version=2`，只允许 route/profile/IDs、confidence、source count、structured answer、section labels、force/refused、history persistence/degradation code，以及非流式 Fast 的可选阶段耗时；禁止 `reasoning`、`intent_reasoning` 和原始异常。capture 只接收 sanitized answer，reasoning 固定为空；普通日志只记录 session 前缀、输入长度、trace 和异常类型。

Circuit-breaker 与 cached degraded response 不接收/拼接 `str(exception)`；正文必须经 `sanitize_model_text`，空结果回退为固定安全服务文案，旧内存缓存内容同样经过该出口。同步/SSE degraded 均使用稳定 `degradation_code`，不把异常详情写入 metadata/body/capture/log。

### 2.7 PHM session truthfulness

`session` SSE 只更新当前内存中的 session ID，不写 localStorage。只有收到合法 done、`contract_version=2` 且 `history_persisted=true` 才登记本地会话；false 显示“未保存”，null/缺字段/旧 contract 显示“持久化状态未知”，均建议复制且不登记。history 只有 v2 且 `complete=true` 才标记完整；字段缺失按 unknown/incomplete 显示 warning。空生成/error 永不登记本地会话。

## 3. Failure and Degradation Matrix

| Failure | User-visible result | Internal behavior | Retry |
|---|---|---|---|
| unclosed think block | 不发送 reasoning | 丢弃未闭合区段 | 下一请求 |
| empty public generation | SSE error，无 done | 不保存空 assistant | 用户重试 |
| Redis + SQLite read down | history 503 | 聊天热路径仍以空 history 降级 | 用户稍后重试 |
| 任一 shard 读取失败 | history 200 + incomplete warning | 返回可读 shard，`complete=false` | 自动/稍后重试 |
| atomic exchange 明确失败 | 回答正常，`history_persisted=false` | 不登记假会话 | 复制回答/重试 |
| SQLite worker 超过 deadline | 回答正常，`history_persisted=null` | 后台结果未决，物理幂等 | 复制回答/稍后查历史 |
| circuit/cached degraded 含异常或 think | 固定/过滤后的安全文案 | 原始异常仅归类 | 用户稍后重试 |
| duplicate feedback | 返回原 ID | 不重复 memory/flywheel | 无需 |
| flywheel failure | feedback 仍成功 | debug 记录类别，不记录正文 | 后台修复 |

不变量：不可用不转为 0；热路径存储失败不抛；raw reasoning 不跨边界；`shared_state` 不新增键。

## 4. Security Impact

- 移除流式 reasoning 的瞬时信息泄露窗口。
- 幂等反馈降低重复写入和重复评测放大。
- 本阶段不改变身份/租户边界；部署仍必须以认证网关保护 mutation/history，未验收前 PHM 写 capability 保持关闭。
- 日志只记录错误类型/请求 trace，不记录模型 raw chunk、用户问题、原始异常或 secret。
- Redis 初始化日志只记录 backend 状态，不输出可能含凭据的 URL。

## 5. Performance Budget

- 过滤器单遍处理，内存缓冲硬上限 256；perf test 对固定输入断言线性输出与缓冲上限，不采用脆弱的墙钟阈值。
- exchange 在一个 Redis round trip 或一个 SQLite transaction 内完成，1 秒 deadline 是可执行的失败上限；SSE 在 answer 后保存再发 done，不影响首 token。
- feedback 的 `BEGIN IMMEDIATE` 仅覆盖 lookup+insert，附属副作用在事务外；API 使用 worker thread。

## 6. Test Matrix

| Layer | Cases |
|---|---|
| unit | 普通/大小写/属性/嵌套标签，同/跨 chunk、未闭合/超长/相似正文、finish 生命周期、buffer bound；atomic exchange；record_once 顺序及两个独立 connection 并发 |
| in-process E2E | 同步/流式 × identity/general/RAG/Fast/takeover/circuit-breaker/cached degraded 的空正文、secret 和 persistence；include_sources true/false 全矩阵；RAG reasoning-only custom+snapshot、正文前缀+snapshot、冲突、未闭合 think→takeover；history empty/incomplete/503/merge-dedupe；feedback duplicate side-effect once；公开 metadata/log/capture allowlist |
| perf | filter 线性空间契约、Redis 单 Lua command、feedback 不在 event-loop 线程执行；SQLite 锁竞争时 event-loop heartbeat 继续，deadline 返回 null 且迟交/重试物理幂等 |
| PHM unit/Playwright | v2 `history_persisted` true/false/null/missing、假会话不登记、失败/unknown 提示、history complete/missing 提示；真实 Vite `/document` 到 hermetic uvicorn |

红→绿日志写入 `tasks.md`；测试文件只进入 `tests/`。

真实浏览器拓扑固定为临时数据目录下的 `PYTEST_RUN=1 RAG_E2E_FAKES=1 uvicorn` → PHM Vite `/document` proxy → Chromium。该用例不得 route-mock 被验收的 `/document` 请求；Playwright 验证应用层事件、恢复提示与代理，UTF-8/CRLF/任意 byte 分块由 unit 覆盖。两轮记录相同的 RAG/PHM git 状态。

## 7. Compatibility and Rollback

- `include_sources=true` 默认值、`get_messages()->list` 和 `record()` 保持兼容。
- 安全边界是有意的语义 breaking change：公开 metadata 不再含 raw `reasoning`/`intent_reasoning`/`error`；空模型输出由 200/empty done 改为 HTTP 502/SSE error；history 故障由伪空 200 改为 incomplete 200 或 503；重复 feedback 改为返回首条 ID。
- `docs/API.md` 与 `CHANGELOG.md [Unreleased]` 必须给出迁移说明：先部署 RAG v2，再部署 PHM；客户端只在 `contract_version=2` 且 persistence/complete 明确为 true 时显示确定性已保存/完整，旧或混合版本按 unknown；不读取原始 reasoning。
- 可单独回滚对应 commit；数据库不新增强制 schema 或不可逆迁移。
- 回滚会重新暴露已确认的 reasoning/重复反馈风险，不作为生产应急首选。

身份/租户授权保持在既有 `RAG-KA-BL-001`/`RAG-KA-BL-004` backlog；生产发布前置条件仍是 loopback/local-only 或已验收的 path+method 认证网关。若部署不满足该条件，发布阻塞而不是在本工作包猜测身份模型。
