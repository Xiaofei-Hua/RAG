# Design

ASCII chat_keywords从任意substring改为正则单词边界匹配，关键词先re.escape；中文保持旧包含匹配，RAG关键词优先次序不变。who are you等短语保留整体边界。无新状态键/接口/依赖/辅助LLM调用；不改生成提示及证据策略。回滚该条件恢复旧逻辑。
先固定Which/this/within不是招呼、Hi!/Hello独立词仍匹配的单元红绿；进程内API保留真实IntentClassifier并捕获实际RAG/生成调用。原未见留出保留失败记录，只复测为回归；另用独立新两题检验英文路由与最终质量。无新安全边界，原降级不变；目标消除误路由及该45s超时。独立critic/defender后编码。
