# Tracking

两位独立设计评审均无Critical/High；最小ASCII词边界方案获准后实现。最终bounded代码、全文与release评审涵盖本修复。

| Issue | Fix commit | Verification | Permanent regression | Status |
| --- | --- | --- | --- | --- |
| 英文which/this/within被hi误分类 | 84345dd | 原留出Thinking45s超时→回归约5.8s完整回答；新两英文题rag_query且完整作答 | tests/unit/test_greeting_intent_boundary.py；2eeb2a4中的实际IntentClassifier JSON/SSE E2E | closed |

红8fail/4pass→定向39pass；最终完整矩阵1222pass、coverage74%。招呼及中文快捷路径保留，无新增专用模型调用；纠正后的RAG会执行原有控制链，不能把错误聊天捷径当正确基线。
