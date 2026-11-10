# Requirements

## Problem
真实未见留出在Thinking中因which包含hi被误判闲聊，绕过检索/有界生成并45s超时。只修已复现的ASCII词内误匹配，不扩展意图策略。

- REQ-001: WHEN ASCII闲聊关键词只出现在较长单词内部，THE SYSTEM SHALL 继续原有意图分类而非直接路由闲聊。
- REQ-002: WHEN 输入包含独立闲聊关键词或中文关键词，THE SYSTEM SHALL 保持现有快捷分类行为。
- REQ-003: WHEN 通过实际API回答原失败题，THE SYSTEM SHALL 进入RAG、保留结论/引用且无额外修补调用；新留出独立验证。
