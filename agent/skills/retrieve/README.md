# Retrieve Skill

混合检索（dense + BM25 + RRF）获取相关文档。

## 输入
- 用户查询（从 HumanMessage 或 tool_call 提取）

## 输出
- ToolMessage：包含检索到的文档

## 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| top_k | 4 | 返回文档数 |
| use_hybrid | true | 启用混合检索 |
| max_context_length | 2500 | 最大上下文长度 |
| return_as_tool_message | true | 以 ToolMessage 格式返回 |
