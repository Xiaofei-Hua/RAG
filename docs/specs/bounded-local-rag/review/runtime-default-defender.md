# Runtime Default Defender — Bounded Local RAG

**Review date**: 2026-11-10。  
**Scope**: `design.md:48–51` 的 Qualified Runtime and Default Selection，以及现有 `models/local_rag_policy.py:7–37`。独立设计审阅，未读另一评审或冻结留出，未运行模型/测试，未改业务代码或服务。本报告不把尚未执行的部署步骤写成已验证事实。

## Decision

**无 Critical/High 设计阻断，允许按此最小方案实现。** 留出与完整回归通过后才改变默认并切换本机运行时；当前代码 `models/local_rag_policy.py:8` 仍默认 legacy。开发 API v7 的 16 槽通过核心回答义务，不等于留出、自动选择接线和实际服务切换已经完成。

真实生成依赖可应用 JSON schema 的运行时，不能只默认发送 schema 后假设官方旧引擎会执行它。精确版本限定是已发现兼容问题的必要部署前提；不要求新增模型能力探测、逐请求生成试探或其他引擎验证矩阵。

## Independent Assessment

| Item | Decision | Evidence and reasoning |
|---|---|---|
| 同版 format 回移 | Accept | `design.md:49` 与上游修复一致：仅把 gemma4 特例扩为具备 thinking 支持的 parser，并在 think=false 时立即应用 format。保留 0.24 后端和同版 GPU 库，避免同时引入新推理后端。 |
| 默认 auto 的适用范围 | Accept | `design.md:50` 要求 exact qwen3.5:9b、general、本地已有限定端点以及服务返回精确 backport 版本；其他版本与未知状态回 legacy，不把较新的官方版本自动视为已测通过。现有模型/profile/端点边界见 `models/local_rag_policy.py:20–27`。 |
| 版本读取与成本 | Accept | 仅在本地模型/profile/端点已匹配且策略为 auto 时需要版本读取；超时、连接失败、非预期响应均按未知回 legacy。1 秒 timeout、禁用代理和进程缓存符合一次配置选择的成本范围，不增加生成/评分调用。 |
| 缓存后的升级/恢复 | Accept | `design.md:50` 明确配置或引擎变化后重启应用刷新。首次读取失败后保持 legacy 到重启是可接受的保守选择；不增加轮询/自动重试机制。 |
| 显式选择与回滚 | Accept | 显式 legacy 不依赖版本服务且恢复原路径；显式 bounded 仍是操作员实验选择，不能将该绕过自动资格判定的路径宣传为已通过默认验证。 |
| 独立二进制与服务变更 | Accept | `design.md:51` 保留官方二进制，以专用 override 指向已验证 binary；原端口/模型存储不变，回滚只移除本次 override。备份服务配置且在留出/回归后执行，范围与实际部署需要相称。 |
| 默认模型迁移 | Accept | 9B 默认与本次测量对象一致；明确已有 LLM_MODEL 不覆写。配置示例、部署说明与 CHANGELOG 应表达相同作用范围，不能把其他 provider/profile 的策略改为 bounded。 |

## Runtime Evidence

已独立核对 [上游 PR #15901 的实际 diff](https://github.com/ollama/ollama/pull/15901/files)：生产条件由 parser 名称特例改为 `builtinParser != nil && builtinParser.HasThinkingSupport()`，同时保留请求显式关闭 thinking 的条件。该修复针对没有 thinking-to-content 转换时格式约束迟迟不生效的问题；不是新的模型提示或额外生成。上游还有相应 parser 测试，不能把整个 PR 说成只有一行，但本项目所需生产回移确实是一行条件替换。

固定源码 [v0.24.0/go.mod](https://raw.githubusercontent.com/ollama/ollama/v0.24.0/go.mod) 声明 Go 1.26.0，与拟定重建工具链一致。此处核对的是修复来源和构建前提，没有独立重建 binary，也没有验证尚未入库的 patch/部署指南。最终应使用同源同版产物并给它独立版本标记；不能仅手改官方 binary 的版本字符串冒充修复。

## Necessary Implementation Checks

实现复核仅需覆盖本次变化直接涉及的选择：auto 匹配已验证版本进入 bounded；官方/其他/未知版本及版本接口失败回 legacy；显式 legacy 不探测；非目标模型/profile/端点不探测；调用预算、输出检查和 None/degraded 仍沿已有策略。复用现有单元和进程内 E2E，不因此追加真实模型矩阵。

版本请求应使用已匹配端点的 origin 下 `/api/version`，不是 `/v1/api/version`；连接关闭/异常按已有 HTTP 客户端习惯处理，不把版本服务异常抛入回答热路径。版本判定只是选择已测组合，不能代替内容质量验证、来源/PII检查，也不能产生 grounding=1 或把 None 当 0。

## Honest Limits

- 当前批准的是设计；自动选择代码、patch/指南、真实服务 override 尚未由本报告核实完成，仍需按既有实现/发布流程落地。
- `lru_cache` 在完成首个读取后复用结果；并发首次未命中可能有重复调用，不能宣称严格 single-flight。此处有限的版本 GET 不值得另建并发协调框架，报告写“缓存版本读取”即可。
- 缓存不会实时跟踪外部服务被替换。设计已经明确升级、回滚或恢复后重启应用刷新；版本字符串是操作层兼容标识，不是安全认证。无真实攻击或完整性事件依据，不新增签名/哈希门禁。
- 官方旧版本的 legacy 路径仍可能保留历史性能限制；这是未验证组合维持原行为，不是把失败算作 0 分或宣称所有运行时均获得本次收益。
- 本轮不读取留出；本机切换与默认 auto 的发布资格继续依赖已经约定的冻结验证和完整回归，不提前改判。
