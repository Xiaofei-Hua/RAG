# Design v1

## Fix
根路径是前端/框架入口，已有SPA路由include_in_schema=False；将缺dist时的根JSON fallback也设为include_in_schema=False，使REST清单不依赖构建产物。GET /实际响应不变；OpenAPI在无dist配置下不再列UI根路径，CHANGELOG列明这一元数据修正及迁移。
新增测试在tmp_path下分别构造有/无index的app，断言OpenAPI一致、GET /原有响应正常。先运行现有缺dist失败与新测试红，再一行修复。
前端只用npm update更新已复现dompurify/nanoid/source-map-js、vue/@vue/server-renderer及其必要父依赖到现有package.json允许的版本，保留semver下限与审计阈值。先保留npm audit红证据，更新锁文件，npm ci/build/audit与完整Playwright。锁文件机械变更与业务逻辑分别说明。

## Review / Rollback
两位独立Agent并行评审。无shared_state/数据库变化；不移除PII、安全/来源检查。回滚本提交恢复原锁与根schema表示，不停用CI。性能修复需独立完成质量门槛后才合并，不能用修CI替代性能成果。
