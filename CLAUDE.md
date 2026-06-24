# CLAUDE.md

> Claude Code 的入口文件。本仓库的权威工程规范在 `AGENTS.md`（根 + 子目录 `agent/core/web/tests`）。
> Claude Code 自动加载本文件；通过下面的 `@` 引用，根 `AGENTS.md` 内容会一并注入上下文。

@AGENTS.md

---

## Claude Code 专属提示

- **Plan Mode**：用户给新需求时，默认进入 Plan Mode（先复述需求、列歧义、给关键决策推荐项），用户确认后再编码。流程见 `AGENTS.md` §13。
- **子 Agent 委派**：对抗式评审的 critic/defender **必须用独立子 Agent 并行执行**（各自独立上下文窗口），父 Agent 只接收蒸馏后的 findings。大范围调研（>3 文件/跨模块/未知调用链）也委派子 Agent。
- **工具选择**：优先用专用工具（Glob/Grep/Read/Edit/Write）而非 shell 命令做文件操作；Bash 留给真正需要 shell 的场景。
- **编码前自检**：复述需求理解 → 指出歧义与隐含假设 → 针对关键决策逐一询问 → 用户确认前停留在需求/设计阶段。

> 其余所有工程纪律、命令、架构、不变量、安全基线、工作流均以 `AGENTS.md`（+ 子目录 AGENTS.md + `docs/specs/prompts/`）为准，本文件不重复。
