# Critic 报告 — frontend-contract-hardening

**评审对象**: `docs/specs/frontend-contract-hardening/design.md` (v1)
**评审模式**: 完整 critic + STRIDE（生成/会话热路径与信息泄露）
**评审日期**: 2026-09-04

## 摘要

- Critical: 4 条
- High: 4 条
- Medium: 0 条
- Low: 0 条
- 初审结论: 必须修订出 v2；下列问题均已进入 v2 设计，待代码与永久测试闭环。

## Findings

### F-01 — PHM 会丢弃持久化真值并提前登记假会话

- **id**: F-01
- **severity**: Critical；目标“不可恢复不得伪装成功”在 v1 下仍可复现，符合严重性表 §2(a)。
- **location**: `src/utils/knowledge-normalize.ts` metadata allowlist、`src/stores/knowledge-agent.ts` session event；会话热路径不变量。
- **symptom**: backend 返回 `history_persisted=false` 时字段被丢弃，且仅收到 session event 就写 localStorage；空生成或保存失败仍出现可恢复会话入口。
- **impact**: 用户重载后打开会话得到空历史，丢失已显示回答。
- **root_cause**: v1 只设计后端生产字段，未设计前端消费与 session 登记时机。
- **recommendation**: PHM allowlist 接入字段；session event 只更新内存，合法 done 且 persistence 不为 false 后再登记；false 显示复制提示。
- **verification**: Playwright 断言 session→error 不登记，done+false 不登记且显示 warning，done+true 登记。
- **status**: accepted-by-defender；v2 §2.7。

### F-02 — 两次独立保存不能表示原子 exchange

- **id**: F-02
- **severity**: Critical；可能新增半条对话且错误报告成功，违反会话热路径降级不变量。
- **location**: `core/memory/redis_memory.py:92`、`api/routers/chat.py` 分散的两次 `save_message`。
- **symptom**: 两次写之间 backend 切换或单次失败时 user/assistant 分裂到不同存储，简单布尔合取无法证明同一 exchange 完整。
- **impact**: 历史出现孤立问题/回答，用户上下文错误且无法可靠恢复。
- **root_cause**: v1 沿用 message 粒度接口表达 exchange 粒度承诺。
- **recommendation**: 生产实现单 backend transaction 的 `save_exchange`；失败时整对在 fallback 事务重试，所有 chat 分支只用该 helper。
- **verification**: Redis pipeline 操作数、SQLite transaction rollback、失败切换后成对写入的永久测试。
- **status**: accepted-by-defender；v2 §2.4。

### F-03 — 非镜像 SQLite 空结果仍会伪装完整空会话

- **id**: F-03
- **severity**: Critical；Redis 既有历史在故障时仍会显示为空，目标 BUG 未闭合。
- **location**: `core/memory/redis_memory.py:131-158`、history response contract；会话降级矩阵。
- **symptom**: Redis 读失败、健康但未镜像的 SQLite 返回空数组时，调用方无法区分“无历史”和“历史不完整”。
- **impact**: 用户误以为会话内容被删除，或在缺失上下文上继续诊断。
- **root_cause**: v1 只有 available/degraded，未定义 completeness 与公开消费。
- **recommendation**: `SessionReadResult` 增加 complete/backend；fallback 读取明确 `complete=false`，双失败 503，PHM 显示不完整提示。
- **verification**: 真空 200/complete、Redis 失败+SQLite 空 200/incomplete、双失败 503 三态测试。
- **status**: accepted-by-defender；v2 §2.4/§2.7。

### F-04 — 非流式正则无法 fail closed

- **id**: F-04
- **severity**: Critical；未闭合/嵌套 reasoning 可进入 response、history 与 capture，属于直接信息泄露。
- **location**: `utils/think_tag_utils.py:12-22`、`api/routers/chat.py` 同步路径；安全基线信息泄露。
- **symptom**: 模型返回 `<think>secret` 或嵌套标签时，旧 regex 不移除并向外返回。
- **impact**: 内部推理、提示片段或敏感数据泄露。
- **root_cause**: v1 把状态机限定为流式，非流式继续依赖只匹配完整成对标签的 regex。
- **recommendation**: `sanitize_model_text` 与流式共享同一 parser，所有公开/持久化/capture 边界只接受其输出。
- **verification**: 同步 general/RAG/Fast/fallback 的未闭合与嵌套 secret 参数化回归。
- **status**: accepted-by-defender；v2 §2.1-§2.3。

### F-05 — 过滤器所有权和 fallback 生命周期不明确

- **id**: F-05
- **severity**: High；常规路径可工作，但 RAG custom/snapshot/rewrite/fallback 边界未闭合，符合 §2(a)。
- **location**: `api/routers/chat.py` 多个 token 发射点、`agent/skills/generate/skill.py` generate stream。
- **symptom**: request-local filter 若停在隐藏态后进入 fallback，会吞掉 fallback 正文；snapshot 还可能覆盖已发 token。
- **impact**: 泄露 reasoning、重复/缺失 token 或空回答。
- **root_cause**: v1 未指定逻辑生成 attempt、唯一发射出口与 reset/finish 时机。
- **recommendation**: 每个 attempt 独立实例，逐路径定义 authoritative text；fallback 新建实例；finish 恰好一次。
- **verification**: RAG 未闭合 reasoning→fallback、custom/snapshot 不一致与多次 generation 的回归测试。
- **status**: accepted-by-defender；v2 §2.2。

### F-06 — 标签 grammar 与有界行为欠定义

- **id**: F-06
- **severity**: High；边界输入可能绕过安全过滤，且热路径缺必要回归测试。
- **location**: v1 design §2.1；生成安全边界。
- **symptom**: 大小写、属性、嵌套、超长标签、close whitespace、相似普通文本没有确定行为。
- **impact**: 绕过、误吞正文或无界缓冲导致内存放大。
- **root_cause**: 仅用示例描述状态机，没有形式化输入契约。
- **recommendation**: 明确 case-insensitive grammar、nested depth、256 上限、未闭合 fail closed 与 finish 生命周期。
- **verification**: 每类 grammar 和逐字 chunk property/golden 用例，断言 buffer 上限。
- **status**: accepted-by-defender；v2 §2.1。

### F-07 — `include_sources` 测试矩阵不完整

- **id**: F-07
- **severity**: High；公开 DTO 在常见返回分支仍可能忽略用户偏好，缺必要回归矩阵。
- **location**: `api/routers/chat.py` 同步/SSE 与 Thinking/Fast 分支。
- **symptom**: 只修某个 response assembly 时，其他分支仍返回 sources；或错误把内部 grounding 清空。
- **impact**: 调用方收到未请求的文档正文，或 RAG 生成质量下降。
- **root_cause**: v1 未逐返回点定义 projection 与内部 evidence 分离。
- **recommendation**: HTTP/SSE × general/RAG/Fast/takeover 参数化；仅公开 sources 置空，source_count 与内部 capture 保持真实。
- **verification**: true/false 全矩阵断言公开 sources 和内部 evidence/capture。
- **status**: accepted-by-defender；v2 §2.6。

### F-08 — 性能与事件循环预算不可执行

- **id**: F-08
- **severity**: High；会话热路径在半连接 Redis 或同步 SQLite 下可无限/长时间阻塞，且无 perf gate。
- **location**: `core/memory/redis_memory.py:67-85`、`api/routers/feedback.py:55`、v1 design §5。
- **symptom**: Redis 无 connect/read timeout；同步反馈事务直接运行在 async route；“p95 <30ms”无可复现实验条件。
- **impact**: chat done/反馈请求挂起并阻塞并发请求。
- **root_cause**: v1 只有愿望式时延目标，没有 deadline、单 round trip 或线程隔离设计。
- **recommendation**: Redis socket timeout + exchange 1s deadline；单 pipeline/transaction；feedback `to_thread`；用确定性操作/线程契约测试。
- **verification**: 阻塞 fake 在 deadline 内降级、单 transaction、event-loop thread 不执行 SQLite 的测试。
- **status**: accepted-by-defender；v2 §2.4-§2.5/§5。

## STRIDE 摘要

| 类别 | 结论 |
|---|---|
| Spoofing / Elevation | 身份/租户风险既有且超出本工作包；沿用 `RAG-KA-BL-001/004` 与 local-only/认证网关发布门禁。 |
| Tampering | 严格 DTO 与 atomic exchange/feedback transaction 降低不一致写入。 |
| Repudiation | 保留 trace/message ID；日志不保留用户正文。 |
| Information Disclosure | F-04/F-05 为阻塞项；v2 统一 sanitizer 与 public projection。 |
| DoS | F-06/F-08 为阻塞项；v2 设 buffer 与存储 deadline。 |

## 公平性确认

`praise (non-blocking)`：v1 已正确坚持 `include_sources=false` 只影响公开 projection、保留 `source_count` 真值，并保留 `get_messages`/`record` 兼容入口；v2 延续这些边界。

## v2 复核增补

复核另发现并在编码前关闭：

- **F-09 (High)**：跨 backend 历史会分裂；改为双读、稳定 ID merge/dedupe，并定义单 shard 失败为 incomplete。
- **F-10 (High)**：同步 sqlite3 无法被 async deadline 约束；改为 `to_thread`、busy timeout 与未决三态。
- **F-11 (High)**：identity/degraded/custom/snapshot/takeover 早退矩阵缺失；已补进 E2E 表。
- **F-12 (Critical)**：缺少 `history_persisted` 被当成 true；改为 `contract_version=2` + true/false/null/unknown，缺字段不登记。
- **F-13 (Critical)**：degraded/cache 正文仍可能含 `str(exception)`；改为固定安全正文 + 同源 sanitizer。
- **F-14 (High)**：worker timeout 后可能迟交却报告 false；改为 null/unknown，并以物理 message ID 幂等吸收迟交/重试。
- **F-15 (High)**：一旦有 custom 就忽略 snapshot 会丢正文；改为 public-token 前缀裁决，冲突明确 error。
- **F-16 (High)**：Redis transaction 不等于重放幂等；改为单 Lua command 同时检查 bounded ID list 并写完整 pair。

上述每项的 symptom/impact 均对应原 finding 的同类会话热路径或信息泄露边界；recommendation、verification 已分别固化到 design §2.2/§2.4/§2.6/§2.7 与 test matrix。最终独立复核结论：Critical 0、High 0，可进入红测。
