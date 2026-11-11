# Agent Skill

决定是否调用检索工具或直接回复。

## 输入
- 用户消息列表
- 绑定的检索工具

## 输出
- AIMessage：包含 tool_calls（触发检索）或直接回复内容

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 1.0 | 重试间隔(秒) |
| message_window | 10 | 发送给 LLM 的最近消息数 |

## Bounded Local Controls

合格本地9B/general控制调用限制为256 tokens并关闭隐藏思考；队列满/超时通过ModelBusyError终止本次请求，不参与表中的普通故障重试/默认评分。Rewrite的历史指代消解同样必须传播busy。相关性评估是检索控制，不是生成后逐句事实核验。配置与回滚见[本地生成指南](../../../docs/deployment/BOUNDED_LOCAL_RAG.md)。
