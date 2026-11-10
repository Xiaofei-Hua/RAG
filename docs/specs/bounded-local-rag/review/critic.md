# Critic Review — Bounded Local RAG

- Date: 2026-11-10
- Scope: requirements/tasks 与 design v2；独立完整 critic，涉及生成/核验降级和检查后发布。未读取本轮 defender 或未运行留出题；未运行模型、测试或修改业务代码。
- Decision: **v2 无未解决阻断，允许进入实现与既定真实验证。** Critical/High 0；原Medium F-BLR-01已在design v2:15纠正。本报告不是质量通过或默认启用许可。

## Assessment

praise (non-blocking)：方案直接切断已观察到的隐式长思考、重复生成及在线多次 judge 成本；保留一次生成的完整任务义务、None/degraded、来源/结构/PII检查，失败不重生。先开发后冻结留出、保留旧失败并按真实正文判断，符合本次完整修复目标。30s P95 是待测目标，不是已取得收益；不能以180s预算消息充当成功基线。

现有实现确有需要本次改动处理的具体入口，设计已明确覆盖，不另立假设门禁：

| Existing path | 实现需落实的既定契约 |
|---|---|
| `agent/skills/generate/skill.py:694–715`、`:739–741`、`:220–303` | bounded 不进入截断后补生成、SDK→LangChain fallback和外层重复生成；同时限制SDK自身重试，失败安全返回。legacy按原范围保留。 |
| 同文件`:577–588`；`core/fast_mode.py:326–339` | 最终生成保留结束原因，length/空输出失败；先缓冲，交给实际输出检查再发布SSE，不能只修改最终JSON。 |
| `core/fast_mode.py:156`、`:394` | 字符串解析器会丢失完成元数据；bounded 不能仅绑定参数后复用该结果作为完整成功。 |
| `agent/guardrails/output_guardrails.py:123–134` | 缓存值None仍会再次请求grounding；统一策略必须覆盖此入口，不能只让Generate跳过judge。 |
| `GenerateSkill._invoke_with_reasoning:668–684` vs async `self.llm` | 策略匹配实际调用端点/模型；按REQ-001目标9B限定已验证默认范围，不将一次9B验证外推全部Qwen3.5或外部provider。 |

上述内容用设计已列的实际请求、JSON/SSE、无第二次生成和None回归即可验证，不要求新增质量矩阵。无跨节点新键、无持久化迁移；本次相关信息泄露风险由检查前不发布草稿解决，其他安全边界保持原状。

## Finding

### F-BLR-01 — Wire presence penalty 不等于当前原生引擎执行的抗重复机制

suggestion (blocking for experiment description, coding may proceed)

- **id**: F-BLR-01
- **severity**: Medium。按critic §2为实验契约/机制说明欠定义；这里仅纠正冷路径设计与结果归因，未发现新生产热路径失效，因此不按热路径缺陷提升。
- **location**: `docs/specs/bounded-local-rag/design.md:5,15`；收益验证须区分请求字段与实际算法。
- **symptom**: 既有native 0.24可接收presence_penalty=0.5，但API收据出现该值不能证明它参与采样。若沿“读取wire确认生效”作归因，会再次把未执行的罚项记为抗重复策略。
- **impact**: 混淆本次机制/成本解释和未来默认的准确配置；不否定no-think、真实输出cap、temperature/top_p或新任务契约的独立可测价值。
- **root_cause**: `openai/openai.go:602–603`接收字段，而本地0.24 `runner/ollamarunner/runner.go:897–904`只传temperature/topK/topP/minP/seed/grammar；`sample/samplers.go:87–99`不消费该罚项。
- **recommendation**: 在design:15省去presence_penalty，或明确仅兼容传递、当前native不生效且不作为抗重复收益依据；冻结实际runtime时沿用这一已知事实。无需为此升级引擎、增加实验或实现通用参数探测。
- **verification**: 本次源码只读已足够证明此项；修订文案/冻结参数后，原有8次机制试验按完整答案判断收益，不能从wire字段或输出偶然不重复推出罚项有效。
- **status**: fixed-in-design-v2（已只读确认移除罚项并明确当前native不消费；待设计提交记录commit，不宣称运行验证）。

## Sources and Limits

已核对[Qwen官方模型卡](https://huggingface.co/Qwen/Qwen3.5-9B)：非思考通用预设含temperature0.7/top_p0.8，罚项支持取决于框架；本方案不是其完整预设。已核对[Ollama兼容说明](https://docs.ollama.com/api/openai-compatibility)与本地0.24源码：`max_tokens`映射`num_predict`，不能以SDK构造参数代替实际HTTP验证。当前仅批准有界实现与既定验证工作，不预判新prompt能解决语言/单位结论，也不以此报告替代最终真实质量、CI或main交付。

## v2 Confirmation

已独立核对design:14–15与:30–35：精确9B/general、统一跳过NLI、Fast finalize、Thinking after-hook后发布、parser前结束状态、禁二次生成及transport retry、最终wire字段与缓存边界均已明确，覆盖上述实际源码入口。无新增发现，不需扩大本轮矩阵或再次等待设计评审。
