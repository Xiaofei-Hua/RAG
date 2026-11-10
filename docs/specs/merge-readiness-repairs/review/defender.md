# Defender Review — Merge Readiness Repairs

**Review date**: 2026-11-10。  
**Review scope**: requirements/design/tasks v1、`api/main.py`、npm workspace 与根锁文件、此前已独立读取的远端 CI 失败归档。未读本轮 critic 稿、未运行测试/模型、未改业务或依赖。

## Decision

**无 Critical/High 设计阻断，允许按最小范围实施。** 两个远端阻断均已实际复现，修复与用户要求的完整 main 合并直接相关，不是额外防御性开发。根路径一行 schema 修正和冻结依赖兼容更新均合理；合并仍须等性能修复的真实质量与 CI 一起完成。

## Independent Assessment

| Item | Evidence | Decision |
|---|---|---|
| 根路径 schema | `api/main.py:451` 的 SPA catch-all 已 include_in_schema=False；`:462` 的缺 dist 根入口未隐藏，同一个 REST schema 因构建文件存在与否变化。 | 将后者同样设为 False 是最小修复，GET / 路由和响应不变。无需改 REST 指南去适配随机产物状态。 |
| 工程回归 | `create_app()` 已通过 WEB_DIST_DIR 选择静态入口，`:437–465` 不需要重构应用工厂。 | tmp_path 有/无 index 各创建 app，核对相同 OpenAPI 和原 GET / 行为，足够覆盖已复现边界；不要依赖开发者机器碰巧已有 dist。 |
| 依赖更新 | 根 `package.json` 声明 web workspace；真实锁是根 `package-lock.json`，不是 web/package-lock.json。当前锁有 dompurify 3.4.12、nanoid 3.3.16、source-map-js 1.2.1、vue/server-renderer 3.5.35。 | 在现有 semver 范围内用包管理器更新根锁，保留声明下限与审计阈值；不手改锁、不跳 audit。 |
| 验证与交付 | npm audit、build、Playwright 是本次更新已覆盖的行为与已失败 CI。 | 红证据保留，更新后运行既有验证与远端 CI；不以本地 green 替代远端结果，也不将 CI 修好称为性能目标已完成。 |

## Necessary Clarification

design 第 6 行列 dompurify/nanoid/source-map-js 及父依赖，但已归档 audit 同时指向 **vue / @vue/server-renderer**。应把这一已复现同族更新明确列入范围；它不是上述三个包的父依赖，遗漏它会留下原 high 项。现有 `web/package.json` 的 vue `^3.4.0` 允许兼容修订，相关 @vue 同版本依赖由 npm 正常解析，无须提高下限或放开检查。这是既有 REQ-002 的清单补全，不新增独立门禁。

## Five-Step Rationale

1. **Fact**: 远端后端失败明确多出 GET /；生产 npm audit 报 4 high / 1 critical。实际代码/锁文件与日志对应，问题不是因本次性能改动才被假设出来。
2. **Reachability**: 干净 clone 没有 web/dist，正常安装冻结 npm 锁就会触发两个既有 CI 阻断。
3. **Cost and impact**: 根 schema 一行修复；依赖属于可回滚机械锁更新。影响直接阻止用户要求的 main 合并，成本相称。
4. **Scope**: 用户已授权修复后合并；当前三段式明确包含两项，不需再次询问，也不需扩为依赖全面升级工程。
5. **Alternative**: 隐藏 UI 根路由的 schema 项、在现有允许范围内更新受影响依赖，是保留运行行为与安全检查的最小方案。复用已有矩阵即可，不接受禁用 audit/断言或忽略远端失败作为替代。

## Honest Limits

此处是设计许可，不宣称已修复 CI 或已通过 Playwright。OpenAPI 在缺 dist 配置下不再列出 UI 根入口属于外部元数据调整，CHANGELOG 需按项目规则说明影响和迁移；实际 GET / 仍可访问。无需修改用户未提交工作、重构前端或新增无关实验。

## Final Clarification Check

已核对更新后的 design 第 6 行明确包含 vue/@vue/server-renderer；已复现 audit 范围的清单补全完成。原设计许可维持：无 Critical/High 阻断，可立即按一行 schema 修复与兼容锁更新实施，不需新矩阵。
