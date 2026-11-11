# Grade Skill

评估检索文档与用户问题的相关性。

## 输入
- 用户问题（从 HumanMessage 提取）
- 检索到的文档（从 ToolMessage 提取）

## 输出
- next_action: "generate"（相关）或 "rewrite"（不相关）

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 1.0 | 重试间隔(秒) |

## Bounded Local Controls

合格本地9B/general控制调用限制为256 tokens并关闭隐藏思考；队列满/超时通过ModelBusyError终止本次请求，不参与表中的普通故障重试/默认评分。Rewrite的历史指代消解同样必须传播busy。相关性评估是检索控制，不是生成后逐句事实核验。配置与回滚见[本地生成指南](../../../docs/deployment/BOUNDED_LOCAL_RAG.md)。
