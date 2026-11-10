# Code Critic — Bounded Local RAG

**Date**: 2026-11-10  
**Scope**: 相对 `a345114` 的业务改动、两个新增策略/生成模块、单元及真实图 API 回归、native patch 与部署说明。独立只读审阅；未运行测试/模型，未读取并行 defender。

## Decision

新增 Critical/High/Medium/Low：**0/0/0/0**。当前实现可进入最终质量与交付收口；代码审阅不代替真实质量裁决或尚未完成的最终矩阵。当前默认仍 `legacy`，不把显式试验等同默认资格。

## Evidence

- `models/local_rag_policy.py:8–30` 同时限制精确 `qwen3.5:9b`、general、HTTP loopback:11434/v1。`auto` 额外要求实际服务版本 `0.24.0-format-backport`；其他/未知版本走 legacy。版本 GET 使用 1 s timeout、禁代理、端点缓存，不是模型调用；服务变更后重启应用的缓存边界已写入部署说明。
- `core/local_rag_generation.py:27–85` 一次模型生成，生成前按实际保留证据的平行列表给出 `1..N` enum，后验仍严格拒绝空/非法 ID、非法 JSON、length 和空内容，不猜测编号或补发生成。正文引用由真实来源表渲染；这证明来源定位，不冒充语义核验。2048 同时绑定 SDK 字段和兼容 `max_tokens`；控制用途为256，保留 tools/结构化输出。默认工厂在本策略下 transport retries=0。
- `core/fast_mode.py:236–260,346–373,437–458` 三入口都在 finalize 后返回/发布；`agent/skills/generate/skill.py:225–243,590–612` 不进入旧 SDK 再生/fallback，且不向 writer 泄露未经检查草稿。既有 after-hook 后的最终节点消息供 API 发布。
- `agent/guardrails/manager.py:130–150` 对实际复现的检查异常清除正文，BLOCK/ESCALATE 同样替换安全消息；PII SANITIZE 保留。语义 judge 在 bounded 下不调用，公开 `grounding_faithfulness=None / confidence_degraded=true`，未把未核验写成0或通过。
- `tests/e2e/test_bounded_local_rag_api.py` 使用真实 IntentClassifier、AgentHarness/图/技能/护栏，仅替换外部模型传输与检索。Fast/Thinking × JSON/SSE × 检查正常/抛错覆盖调用数、清理后 token/done、历史内容和 judge 零调用；不再用假 intent 掩盖 Which 的旧误路由。
- `core/intent/classifier.py` 的 ASCII 招呼词改为完整词边界，中文包含匹配和 RAG 优先次序保留。没有为新题硬编码主体/数值或新增分类调用。控制链 `getattr(..., {})` 保留已有注入 legacy chain；开启策略仍按实际 kwargs 重建。
- `deploy/patches/ollama-0.24.0-thinking-format.patch` 仅回移官方修复的 forceImmediate 条件。`docs/deployment/BOUNDED_LOCAL_RAG.md` 明确固定0.24同源/Go1.26、同版GPU库、独立 binary、实际服务版本检查和专用 drop-in 回滚。官方未修补0.24不会由 auto 放行；既有显式 LLM_MODEL 不被默认9B迁移覆写。

## Verification Boundary

已读 `validation/default-routing-green.log`：39 passed；此前 `backend-matrix.log` 仍为1078 passed / 1 failed / 4 deselected，失败为注入的 legacy grade chain 被错误重建。现有四处默认 `{}` 修正与定向通过对应，**不将旧矩阵改写为全绿**；最终矩阵由主线程归档。schema/引用渲染与 prompt 有固定 golden；真实生成/API既有失败保留，另见相应质量报告。

既有 `F-BLR-RUNTIME-01` 的实现缺口由版本选择、可复现补丁/部署说明及 `test_auto_requires_the_qualified_server_and_caches_it` 相关定向测试覆盖：本次记 **verified-by-test，待修复 commit/最终 tracking 填齐**，不提前标 closed。未发现需要新增实验矩阵的代码阻断。
