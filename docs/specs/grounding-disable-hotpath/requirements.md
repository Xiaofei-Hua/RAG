# Requirements

## Problem
关闭GROUNDING_CHECK_ENABLED只影响OutputGuardrail，GenerateSkill仍调用check_grounding/acheck_grounding，导致用户仍为每句模型核验等待。目标是让已有配置真正控制整个在线核验路径；不给未知结果打0/1，不改生成提示或用新窄题型规则替代通用回答。

## EARS
- REQ-001: WHEN GROUNDING_CHECK_ENABLED=false，THE SYSTEM SHALL 在同步/异步在线核验取得judge或调用模型之前返回不可用结果（faithfulness=None,degraded=True,reason=disabled）。
- REQ-002: WHILE 配置未设或为true，THE SYSTEM SHALL 保留原语义核验行为；配置解析与GuardrailConfig使用同一布尔规则。
- REQ-003: WHEN 语义核验关闭，THE SYSTEM SHALL 保留现有来源、结构、安全提示和PII检查，回答置信度不得把未核验误记为完全支持。
- REQ-004: WHEN 修复交付，THE SYSTEM SHALL 提供单元/进程内API红绿及真实9B多轮对照、独立留出验证；默认值继续true，未经质量验证不默认关闭语义核验。
- REQ-005: WHEN 推送GitHub，THE SYSTEM SHALL 基于origin/main交付独立小分支，并将同一修复适配到当前集成工作树，保留主工作树已有未提交内容。
