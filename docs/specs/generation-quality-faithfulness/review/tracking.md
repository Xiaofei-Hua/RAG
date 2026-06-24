# 闭环追踪矩阵 — generation-quality-faithfulness(Stage C)

## 1. 追踪矩阵

| 发现 ID | 严重性 | 辩护决策 | 状态 |
|---------|--------|----------|------|
| F-RC-01 | Medium | accepted(agent nudge 放行权衡) | accepted |
| F-RC-02 | Medium | accepted(grade 默认 no 增 rewrite,保守正确) | accepted |
| F-RC-03 | Medium | accepted(thinking 重生成延迟,少数场景) | accepted |
| F-RC-04 | Low | accepted(短答案/无 template 边界) | accepted |
| F-RC-05 | Low | accepted(threshold 成死配置,记 fallback) | accepted |

## 2. 闭环状态
- **Critical: 0 / High: 0**。Medium/Low 全 accepted。门禁通过。

## 3. REQ 达成度

| REQ | 目标 | 达成 |
|-----|------|------|
| REQ-RC-001 | grade 默认 no | ✅ |
| REQ-RC-002 | grade prompt JSON 示例 | ✅ |
| REQ-RC-003 | _parse_relevance 按 key | ✅ |
| REQ-RC-004 | agent 空 tool_call 兜底 | ✅ |
| REQ-RC-005 | thinking max_tokens 6144 | ✅ |
| REQ-RC-006 | finish_reason 截断检测 | ✅ |
| REQ-RC-007 | 结构校验末段 | ✅ |
| REQ-RC-008 | refusal 无分数拒绝 | ✅ |
| REQ-RC-009 | refusal 量纲(改为交给 grade,撤回归一化) | ✅(设计修正) |

## 4. 关键:refusal 设计自纠偏
实现者同步评审发现"绝对阈值 0.3 对 RRF ~0.01 恒拒绝"→ 尝试归一化 → 实测破坏全低分拒绝 →
撤回 → 改"有分数交给 grade"(分层正确)。诚实记录,非后台 critic 发现。

## 5. 验证证据
- regression:47 passed(grade/agent/thinking/refusal + 既有回归)。
- refusal RRF:str+score=0.0082→不拒绝(交给 grade);str 无 score→拒绝。
- grade:空 dict→not_relevant;{"score":"not relevant"}→False。
