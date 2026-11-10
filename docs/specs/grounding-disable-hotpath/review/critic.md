# Critic — Grounding Disable Hot Path

**评审对象**：requirements.md / design.md v1 / tasks.md；发布树 `/home/outsiderzz/Projects/RAG-grounding-switch`，并核对集成树对应入口。  
**评审模式**：完整 critic，热路径降级与置信度边界。  
**评审日期**：2026-11-10。

## Decision

Critical 0 / High 0 / Medium 0 / Low 0。**可进入最小实现。** 未发现可触发的设计阻断；未阅读 defender 报告，未运行模型或测试。

## Findings

无新增 finding。

`praise (non-blocking)`：把既有总开关放到在线 GroundingGuardrail 入口，而非仅在 GenerateSkill 跳过一次调用，可同时覆盖同步、异步、模块wrapper及Output直接调用；默认true和离线LLMJudge保持原行为。

## Evidence and Invariants

- 发布树 `agent/skills/generate/skill.py:319–352` 的两个 helper 直接调用在线核验，未读配置；`agent/guardrails/output_guardrails.py:123` 只控制自己的语义分支。现有失效路径与设计描述一致。
- `grounding_guardrail.py:87、161` 两公共入口在取 `self.judge` 前返回 `GroundingResult(None, degraded=True, reason="disabled")`，即可切断昂贵调用；构造器72行仅保存judge，module wrapper不会提前初始化它。集成树 `_prepare:176` 为两入口共同前置，判断应在 `_online_claims` 之前。
- `types.py:8–12` 的既有布尔规则可直接复用；仅把59行改为field factory，解决新实例在模块导入后读到旧默认的问题，无需改变其他环境字段。
- 明确配置层次：factory保留 `GuardrailConfig(enable_grounding_check=...)` 的显式字段赋值；环境false仍是在线NLI总开关，显式Output配置true不能越过它。既有实例不是动态配置订阅，本设计也不承诺修改环境后同步重载全部实例。
- Generate旧有 `None` 路径在982–1019行将grounding权重转给retrieval并标记degraded；分数可能与启用核验时不同，不能宣传为核验通过或可信度必然降低。设计保留此公式，符合不可用不当0/1。
- Output关闭语义分支后走既有来源规则；结构/安全检查及255行PII路径独立。设计没有取消这些检查或增加新状态键，也没有把集成树 `grounding_assessment` / 检查后发布功能冒称已回移。
- 提前返回不创建异步任务，不新增取消捕获；默认true仍落原sync/async代码。旧main其他并发/流式问题不是本次阻断项。

## Verification Boundary

设计已覆盖必要红绿：禁用值与两个入口/wrapper在取judge前短路；未设/true仍调用；import后新实例及显式字段；真实GenerateSkill单次生成、NLI零调用、None/confidence_degraded；API JSON/SSE与来源/PII保留。实现时按这些直接行为验证即可，不增加无关矩阵。

真实24槽验证用于评价关闭核验的成本/质量取舍；A的超时不伪造TTFT，B失败也不抹掉默认不变的开关bug修复价值。此设计批准不等于已验证性能收益或允许默认关闭。
