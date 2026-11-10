# Critic Review — Greeting Intent Boundary

Date: 2026-11-10。独立读取三段式、`core/intent/classifier.py`、general关键词、已完成留出8槽/实际HTTP及既有红日志；未读取另一评审或新两题，未运行模型/测试，未改业务。

**结论：0 findings，允许编码此最小修复。** 不需要扩展意图策略、中文关键词、生成提示、检索算法或新增辅助模型调用。

praise (non-blocking)：修复直接针对已复现的ASCII词内误匹配。`classifier.py:123–139`先匹配RAG关键词，再对chat_keywords任意substring匹配；general的RAG词表为空，chat含hi。最后Thinking题的which包含hi，实际intent事件为general_chat/0.9；唯一HTTP只含通用聊天提示和原问题，没有资料、reasoning_effort或有效Ollama max_tokens，45s未完成。因此不能把该槽误归为有界RAG答案质量失败或完整45s TTFT。

ASCII关键词使用re.escape及完整单词边界，中文继续原包含匹配、RAG优先序保持，能切断which/this/within误中hi；未命中继续原LLM分类，不要强制赋成RAG。Hi!/Hello等独立词仍保留快捷行为；多词关键词按整体边界处理即可。

`bounded-local-rag/validation/default-routing-red.log`已分别复现Which/this/within三个错误GENERAL_CHAT断言；同日志另5个默认选择失败属于另一个工作项，不能把8个失败全归此bug。按现有单元红绿及真实IntentClassifier的JSON/SSE/图调用覆盖完成即可。修复会恢复正常intent/agent/grade/generate开销；“无新增辅助调用”不代表该误路由题的物理调用仍为原来的1次。

## Completed Holdout Context

| Mode / case | 当前实际结果 |
|---|---|
| Fast / unit_conditions | 安全拒答，0生成，不计成功；不在没有同题legacy对照时判新增退步。 |
| Fast / explicit_missing | 同上。 |
| Fast / version_conditions | PASS：R3.1明确不支持；R3.4仅升级不足，管理员与FAT32同时必需，来源正确。 |
| Fast / threshold_condition | PASS：257L已超过240L，不能等到28日；先到者规则、适用清水/6–32°C范围、英文与引用完整。无需逐字复写用户已给17日/22°C才能作出正确适用判断。 |
| Thinking / unit_conditions | PASS：2.3L/min=138L/h>126L/h，70/110kPa归属正确，不能外推同压，双源完整。 |
| Thinking / explicit_missing | PASS：储存温度未指定，工作12–38°C含端点，英文与来源正确。 |
| Thinking / version_conditions | PASS：版本和两个同时必要条件完整，引用正确。 |
| Thinking / threshold_condition | 未完成：错误闲聊快捷路由，45s客户端超时，合格TTFT=None，不计答案成功。 |

合计5份完整实质回答、2个0生成安全拒答、1个未完成；4个独立问题各两模式，不是8个独立问题。Fast拒答的约1s是安全提示到达，不能记作有效答案性能。保持所有原失败/缺失，legacy同题用于判断原有检索覆盖，不能要求本次生成/路由修复让所有检索指标全面更优。

同题修复复测属于暴露后的回归，不再称新盲测；既定新两题用于独立验证即可，不据本次审阅追加更大矩阵。默认auto的运行时前提与部署闭环继续由bounded-local-rag单独追踪。
