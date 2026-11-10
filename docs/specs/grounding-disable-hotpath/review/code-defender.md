# Code Defender — Grounding Disable Hot Path

**Review date**: 2026-11-10。  
**Scope**: 发布树实际 diff、集成树对应适配、`test_grounding_switch.py`、`test_grounding_switch_api.py`、disabled golden 与已落盘红绿日志。未读取本轮 code critic 意见，未运行测试或模型。

## Decision

**当前生产实现无新增 Critical/High 阻断，符合已批准的最小设计。** 发布树生产 diff 只有两个文件、10 行新增/1 行删除：GroundingGuardrail 导入既有布尔解析器并在 sync/async 两入口提前返回；GuardrailConfig 的一个字段改为 default_factory。集成树只在共用 `_prepare` 增加同一判断。没有改 prompt、生成预算、默认值、输出护栏或离线 judge。

两树最终测试矩阵现已通过，并覆盖修订后的 fixture；原失败时序保留如下。代码与测试通过不构成默认关闭许可，真实 24 QA 的质量/性能结论仍待既定测量。

## Implementation Verification

| Boundary | Independent code assessment |
|---|---|
| 禁用早于昂贵操作 | 发布树 `agent/guardrails/grounding_guardrail.py:99–100` / `:181–182` 在空资料、judge 获取和声明拆分前调用 `_env_bool(..., True)`；false 返回 `GroundingResult(None, degraded=True, reason="disabled")`。不会触发旧无 hard claims 的 1.0 分支。 |
| wrapper 与当前适配 | wrapper 的对象构造不取得 judge；公共入口已覆盖。集成树 `_prepare` 的前置判断在 `_online_claims` 之前，sync/async 都复用它，无需在 Generate 和 Output 各加一套跳过逻辑。 |
| 解析与默认 | 沿用 `types.py:8–12` 的 strip/lower true 集合；缺环境默认 true。未改其他字段或解析规则。 |
| 实例字段与全局优先级 | factory 每次创建默认实例时读环境；显式 true/false 仍直接作为字段值。GroundingGuardrail 独立执行全局 env 判断，因此显式 Output config=true 不能触发被全局禁用的 NLI。现有实例不是环境订阅器。 |
| 不可用语义 | 禁用结果 available=false、faithfulness=None、degraded=true，reason=disabled；旧 Generate 的 None 降级和当前的 assessment 均复用。没有写入支持分数 0/1，也没有新增结果 schema。 |
| 保留既有保护 | Output 的来源 fallback、安全/结构/PII 代码均未改。关闭只切断语义核验，不把来源格式匹配称为语义支持，不改变已有最终发布机制。 |
| 取消与状态 | 新分支同步返回结果，无新增异步任务、异常捕获或请求级可变成员；默认 true 仍进入原实现。没有新 shared_state 键或持久化。 |

## Test Review and Honest Coverage

- `tests/unit/test_grounding_switch.py:21–41` 覆盖 false/0/off/no/含空格大写与四种入口。judge getter 即使被既有降级捕获，末尾 assert_not_called 仍能发现实际触碰；不是仅断言没有向外抛错。disabled golden 明确 available=false、faithfulness=null、degraded=true、reason=disabled。
- `:44–63` 在默认及 true/1/yes/on 下使用实际 GroundingGuardrail，断言 entail 一次且 faithfulness=1.0，验证本修复没有默认关闭核验。`:66–72` 区分 import 后新实例与显式字段覆盖。
- `:75–122` 调用实际 GenerateSkill sync/async，以固定模型响应验证一次生成、零 judge、None/confidence_degraded；再走真实 GuardrailManager after-hook 检查 PII，并单独验证虚构来源仍 escalate。测试没有替换 grounding helper 来制造零调用。
- API 测试用 client fixture 请求 JSON/SSE，替换的是 harness 编排、模型与检索材料；真实 GenerateSkill 和输出 after-hook 仍执行，能验证返回正文包含预期事实和来源名、PII 脱敏、一次生成及零 judge。None/降级断言读取测试中真实生成结果的 metadata，**不能表述为旧 main API 已公开返回完整 grounding 收据**。
- SSE stub 在 after-hook 之后才主动发出 token/update。因此该用例**不验证旧 main 的原生流式发布先后顺序**，也不证明真实 LangGraph 编排的所有事件路径。它的覆盖与测试 docstring“真实 generation/output stages”一致；集成树已有 mandatory 发布门禁沿用原回归，不在本次回移。
- API 的来源断言位于正文，不能夸大为检验完整来源卡 schema；本次生产 diff 未改该 schema。测试仅用固定响应验证控制与安全行为，真实模型内容质量仍待既定 A/B。

## Evidence Read and Fixture Correction

| Evidence snapshot | Observed result | Meaning |
|---|---|---|
| 发布树 `validation/red-unit.log` | 23 failed / 10 passed | 禁用入口、import 后默认配置和 Generate 路径在修复前失败；启用控制仍通过。 |
| 发布树 `validation/red-e2e.log` | 2 failed | JSON/SSE 经真实生成路径仍触碰 judge。合计 25 个预期失败。 |
| 两树早期 `validation/green-targeted.log` | 发布树 62 passed（2.15 s）；集成树 62 passed（2.65 s） | 证明开关修复初期定向 green；发布树退出时另有 unclosed database ResourceWarning，不把它说成无 warning。 |
| 首次读取发布树 `validation/backend-matrix.log` | 1 failed / 1181 passed / 6 skipped / 3 warnings / 2 errors | 两个新 API teardown 报错；另有 WSL 文档/OpenAPI 表对应测试失败。该快照不能报全量通过。 |

首次全量的 teardown 直接导入 `reset_inference_store`，但发布树 `agent/eval/inference_store.py` 仅有 get/close，没有集成树新增的 reset helper。独立核对时，主 Agent 已将当前 fixture 修为在既有 `_store_lock` 内 close 并清空 `_store`；两树当前 fixture 一致，此修正适配旧接口，**不需扩大生产代码回移 reset helper**。

当前 fixture 修改晚于上述定向 green 日志，因此那两份 62 passed 仅作为初期快照保留。后续最终日志已独立读取，补齐最终 fixture 和完整矩阵证据；本 defender 未重跑或扩大业务范围。

| Final evidence | Observed result | Scope |
|---|---|---|
| 发布树 `validation/backend-matrix-final.log` | **1182 passed / 6 skipped / 3 warnings，58.73 s** | 修复提交 `de1a474`；旧全量失败不再作为当前结果。 |
| 集成树 `validation/backend-matrix.log` | **2768 passed / 6 skipped / 3 warnings，154.65 s** | 适配提交 `24d0a97`，沿用当前集成接口与既有回归。 |
| 集成树 `validation/e2e-final.log` | **2 passed，2.40 s** | fixture 调整后的 JSON/SSE 用例通过。 |

最终两份矩阵日志均显示既有 Swig / jieba 相关 warning；不能报告为零 warning。没有把早期 ResourceWarning 或 teardown ImportError 从历史记录中删除。

## Final Disposition

没有当前仍需改动的生产代码 finding。测试清理适配与两树完整矩阵的最终 green 已核对，代码评审和测试证据现已闭合；旧失败继续保留。默认 true、来源/PII 与未核验语义保持。真实 A/B 的延迟、可用性和逐题质量仍待独立结果审阅，不由代码评审或 mock 测试代替。
