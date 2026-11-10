# Critic Review — Merge Readiness Repairs

- Date: 2026-11-10
- Scope: requirements/design/tasks v1，独立设计评审；未读取本轮defender，未运行测试、安装依赖或修改业务文件。
- Decision: **无发现，允许进入既定最小修复。** Critical/High/Medium/Low 均0。当前不宣称CI已经通过或已经合并。

praise (non-blocking)：两项均对应已经复现的交付阻断，未用关闭测试/审计代替修复，也没有把CI修复冒称模型性能成果。

`api/main.py:451`已有SPA入口不进入OpenAPI，而`:462`缺dist时的根JSON入口默认进入schema。给后者同样加`include_in_schema=False`能切断构建产物影响REST清单的根因；`:425–434`的`/api`信息接口和`GET /`实际响应无需改变。`create_app`已有`WEB_DIST_DIR`入口，tmp_path有/无index的两种回归可以直接实现，不需要新app架构。

依赖使用仓库根`package-lock.json`及根npm workspace（`web/package.json`声明范围），因此从根更新并复用既有`npm ci`/构建/生产audit/Playwright即可。只更新已复现问题及必要父依赖，不抬下限、不关审计，符合当前用户AGENTS的最小范围。最终以新锁对应的实际audit及完整相关CI为准；本次只审设计，不从版本号推断已无漏洞。

按既定红→绿、GET响应回归与依赖验证归档，和有界RAG真实质量结果分别报告后完成main合并/push即可；不需要新模型实验或扩大防御性工作。

Update: 已读design:6新增已复现的vue/@vue/server-renderer锁修复，仍在现有声明范围内，与同一生产audit阻断直接相关；无新增发现。
