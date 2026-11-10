# Requirements

## Problem
用户要求完整修复后合并main。现有远端CI已复现：无web/dist时GET /进入OpenAPI而有dist时不进入；前端锁定的生产依赖有npm audit高/严重问题。必须修复真实阻断，不能通过关闭检查交付。

## EARS
- REQ-001: WHEN 有/无前端构建产物，THE SYSTEM SHALL 提供一致的REST OpenAPI；根路径继续提供原有HTML或API信息fallback。
- REQ-002: WHEN 安装冻结前端依赖，THE SYSTEM SHALL 通过生产npm audit与既有构建/Playwright，不通过扩大版本下限或禁用审计规避。
- REQ-003: WHEN 性能修复全部验证，THE SYSTEM SHALL 合并并push main，不遗留草稿当最终交付。
