# Intent Skill

分类用户意图（rag_query, general_chat, doc_upload, system_cmd）。

## 输入
- 用户消息

## 输出
- next_action: 路由决策

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_retries | 2 | 最大重试次数 |
| retry_delay | 0.5 | 重试间隔(秒) |
| fallback_intent | rag_query | 分类失败时的回退意图 |
