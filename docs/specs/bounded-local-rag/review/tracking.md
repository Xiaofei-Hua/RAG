# Tracking

独立并行评审已完成；v2闭合设计接线，默认legacy，允许实现和有限开发试验。

| ID | Severity | Resolution | Verification | Status |
| --- | --- | --- | --- | --- |
| F-BLR-01 | Medium | v2移除当前0.24原生不消费的presence_penalty | 原生源码与实际wire | design closed |
| BL-D01 | High | v2 Fast共用finalize、Thinking检查前不发布 | 真实JSON/SSE和PII回归待实现 | design closed; code pending |
| BL-D02 | High | v2生成/输出共用bounded判定，None不重触发judge | 同步/异步及实际调用数待实现 | design closed; code pending |
