# web/AGENTS.md — 前端专属规范

> 本文件补充根 `AGENTS.md`，仅当工作目录在 `web/` 子树下时由 Agent 加载。
> 技术栈：Vue 3 + Vite + TypeScript + Pinia。

## 1. 目录与产物

```
web/
├── src/                # Vue SPA 源码（components / stores / api / views）
├── dist/               # 构建产物（Playwright E2E 与生产静态部署依赖）
├── package.json
├── playwright.config.ts
└── vite.config.ts
```

- **`web/dist` 契约**：Playwright E2E 与生产静态部署都依赖 `web/dist`。改前端后必须 `npm run build` 重新生成。
- 依赖锁文件 `package-lock.json`，禁止 `@latest` 写法。

## 2. 命令（绝对路径、可独立执行）

```bash
# 安装依赖
cd web && npm ci

# 开发
cd web && npm run dev

# 构建（生成 dist/，E2E/部署前置）
cd web && npm run build

# Playwright E2E（需 web/dist + 后端运行）
cd web && npm run build && cd ..
npx playwright test --config=web/playwright.config.ts
```

## 3. 前端测试纪律（根 AGENTS.md §7 的前端部分）

- 涉及前端的改动必须给齐 **Playwright E2E**，证明功能在 UI 层完整：chat / SSE 流式 / 文档上传 / 会话 / 反馈。
- **截图断言验证功能正确性**：E2E 在关键交互节点（页面加载、消息渲染、上传完成、流式增量）用
  Playwright 截图（`page.screenshot()`）或 `toHaveScreenshot()` 断言页面呈现是否符合预期——
  纯 DOM 选择器断言无法覆盖视觉/布局/异步渲染问题，截图是端到端验证「功能是否真正正确」的必要手段。
  截图基线存入 `tests/e2e_ui/` 对应快照目录；UI 有意变更时先更新基线并在 PR 单列 screenshot diff。
- Playwright 脚本放 `tests/e2e_ui/`（不是 `web/` 内），CI 以独立 job 运行（`.github/workflows/e2e-ui.yml`）。
- 前端 E2E 不在默认 `pytest testpaths` 内（需 Node + 构建产物），由 `e2e-ui.yml` 单独驱动。

## 4. 约定

- 组件命名 PascalCase，组合式 API（`<script setup lang="ts">`）。
- 状态管理用 Pinia store；跨组件共享状态禁止用全局变量。
- HTTP 调用统一走 `src/api/` 封装；SSE 流式处理集中在 chat 模块。
- 代码无 emoji（与后端约定一致）。
- 遇到后端 API 变更，同步更新 `src/api/` 类型定义与对应 E2E 用例。
