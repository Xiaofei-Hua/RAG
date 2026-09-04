# Frontend Contract Hardening Requirements

- **Feature**: `frontend-contract-hardening`
- **Status**: confirmed remediation scope
- **Date**: 2026-09-04

## 1. Surface and Essential Need

表面需求是复核 PHM 前端与 RAG 后端的文档、检索、SSE、历史和反馈契约；本质需求是让浏览器只接收到可公开、可恢复、可验证的结果，并避免“空成功”、推理泄露、重复写入和伪造持久化成功。

## 2. Scope

本阶段修改 RAG 的流式公开文本过滤、空生成终态、`include_sources`、会话读写可用性和反馈幂等。既有文档/反馈/history 身份与租户授权仍由部署网关门禁负责，所有前端 mutation capability 继续默认关闭；多租户鉴权模型不在本阶段擅自设计。

## 3. Requirements

### REQ-FCH-001 — Public model-output boundary

**WHEN** 任意一次模型生成以任意 chunk 边界输出 reasoning 标签，**THE SYSTEM SHALL** 在发送 SSE token、构造同步响应、保存 assistant history、构造 `done.full_response` 或写 eval capture 之前，以同一个 fail-closed 规则移除 reasoning 区段；跨 chunk、未闭合、嵌套或超长标签中的正文不得短暂暴露给客户端。

### REQ-FCH-002 — Non-empty terminal answer

**IF** 过滤后的生成结果没有非空公开正文，**THE SYSTEM SHALL** 在流式路径以明确、可重试的 SSE `error` 终止，在同步路径返回 HTTP 502；两条路径均不得发送空成功、保存空 exchange、写 eval capture 或让 PHM 记住一个不可恢复的本地会话。

### REQ-FCH-003 — Source preference contract

**WHEN** `ChatRequest.include_sources=false`，**THE SYSTEM SHALL** 在同步和流式 Thinking/Fast 响应中返回空 `sources`；内部检索、评估和日志可继续使用真实 evidence，但不得通过公开 sources 字段泄露。

### REQ-FCH-004 — Observable history read availability

**WHEN** session history 可分布在 Redis 与 SQLite fallback，**THE SYSTEM SHALL** 双读、按稳定 message/exchange ID 合并去重；只有所有配置的数据源均成功读取时才返回 `complete=true`。**IF** 至少一个源可读但另一源失败，须返回可用内容及 `complete=false/degraded=true`；**IF** 所有源均失败，history 路由须返回 HTTP 503。基础设施故障或不完整降级不得伪装成真实空会话，聊天热路径仍须安全继续。

### REQ-FCH-005 — Observable history persistence

**WHEN** 聊天回答已生成，**THE SYSTEM SHALL** 为 user/assistant 分配同一稳定 exchange ID，并在每次 backend 尝试中以一个原子、物理幂等操作保存完整 exchange；Redis 结果不确定时允许把同一 exchange 整体写入 SQLite，读取时必须去重，禁止把两条消息拆到不同 backend。公开 `history_persisted` 为三态：成功 `true`、明确失败 `false`、deadline 后后台结果未决 `null`。回答始终继续交付；PHM 只有在 v2 contract 明确返回 true 时才持久记住新会话，false/null/缺字段分别提示失败或未知并建议复制回答。

### REQ-FCH-006 — Idempotent feedback

**WHEN** 同一非空 `(session_id, message_id)` 的反馈因双击、重试或并发被重复提交，**THE SYSTEM SHALL** 原子返回首条记录 ID，不新增反馈记录，也不重复触发 correction memory 或 negative-feedback flywheel。缺少 `message_id` 的遗留请求保持既有追加语义。

### REQ-FCH-007 — Degradation and privacy

**IF** 文本过滤、会话存储或反馈附属飞轮失败，**THE SYSTEM SHALL** 记录仅含错误类别与 trace 的诊断并采用更弱但安全的结果；不可用不得编码为 0 分，原始 reasoning、用户问题和原始异常不得进入客户端或普通日志。公开 metadata 必须经过 allowlist projection，禁止下发 `reasoning`、`intent_reasoning` 或原始 `error`；缓存或降级正文也必须经过同一 sanitizer，且不得插入 `str(exception)`。

### REQ-FCH-008 — Verification

**WHEN** 本功能交付，**THE SYSTEM SHALL** 提供 unit、进程内 E2E 和 PHM Playwright 联调证据；最终代码状态的后端契约矩阵与前端 Playwright 必须各连续两次无失败。

## 4. Acceptance Criteria

- 跨 chunk `<thi` + `nk>SECRET</think>` 在 token、done、history、capture 中均不可见。
- LLM 零公开 chunk 只产生可重试 error，不产生空 done。
- `include_sources=false` 在同步/流式、Thinking/Fast 均为空；true 保持兼容。
- 双存储故障的 history 是 503，真实空 history 仍是 200 空数组。
- Redis 降级到非镜像 SQLite 时 history 是 200 且 `complete=false`，PHM 显示“历史可能不完整”。
- 每个 backend 尝试只会原子、幂等保存完整 exchange；不确定重试产生的副本以 exchange/message ID 去重；false/null/unknown 均不让 PHM 登记已确认可恢复会话。
- 同一消息的并发反馈只落一条且附属副作用只执行一次。
- 普通日志和公开 metadata 不包含用户问题、raw reasoning 或原始异常文本。
