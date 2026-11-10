# Release Defender — Bounded Local RAG

**Review date**: 2026-11-10。独立阅读最终源码、`bounded-local-rag-default-final` 两槽、`bounded-local-rag-mixed-final` 八槽完整正文/实际请求和最终后端日志。未运行模型/测试、未改业务或服务。本报告补充既有 code/final-quality 报告，不覆盖历史失败。

## Release Decision

**维持精确已验证组合的 auto 默认资格，无新增 Critical/High 阻断。** `models/local_rag_policy.py:9` 已默认 auto；同函数仍要求精确 qwen3.5:9b/general、本地11434/v1与实际版本0.24.0-format-backport，未知组合回legacy。宿主版本证据沿用 `validation/host-runtime.json`，不重复改动已存在的服务override。

默认验证 runner 明确移除了 LOCAL_RAG_POLICY（`run_bounded_api_probe.py:32–33`），两槽 metadata 实际为 bounded，证明未显式开启该策略也能选中合格路径。runner仍明确配置模型与端点，因此这是“策略变量未设”的验证，不宣称任意零配置部署已验证。

## Final Answer and Wire Review

| Batch | Core result | Evidence |
|---|---|---|
| default-final：电池题Fast/Thinking | 2/2通过 | 明确芦序记录续航长于赤砚；600分钟=10小时、9小时=540分钟换算正确；5W/8W归属及不能外推同负载结论完整，两方引用匹配。 |
| mixed-final：两题×两模式×两轮 | 8/8核心义务通过 | 四条电池回答均有明确比较与不同负载限制；四条零值回答均在10分钟记录范围内判断0ms=0s、不是缺测，未新增“存在测量误差”或泛化为设备绝对精准。正文引用对应相关资料。 |

API2-D01 Medium仍保留：混合r1 Thinking又出现“资料中明确说明记录的零值是数值，不等于缺测”这类把通用解释归为资料直接说明的表述。该结论受已完成测量/记录零值支持，不是新数值错误；但旧引述归属瑕疵并未被证明修好，不将其关闭或声称所有原文引述精确。

两批实际HTTP分别5/20次，共10次最终JSON生成（2048/2048）、15次控制（256/256），均reasoning_effort=none；原始响应未返回隐藏reasoning字符，未见在线judge或补写生成。生成全部stop，控制另有工具调用终态。全部SSE token拼接、done和保存正文一致，grounding=None/degraded。混合样本model_start/end为None，不能用串行计数切片臆造各并发请求的物理调用分配；上述为批次实际总数。

Fast来源卡仍带一个无关候选，正文没有引用它；来源卡数量不能当gold支持数。本轮10条核心答案通过不覆盖原Fast四个不足答：它们仍是未回答，既有legacy对照证明覆盖未退步，继续如实披露。

## Performance and Steps 3/4

| Mode | Serial default first body | Mixed first-body range | Mixed P50 |
|---|---|---|---|
| Fast | 3.628s（1槽） | 4.166–4.783s（4槽） | 4.385s |
| Thinking | 5.878s（1槽） | 8.382–9.168s（4槽） | 8.966s |

混合是每次Fast/Thinking各1并发、2题2轮，共8槽，整批35.939秒；0超时、0缺正文。相对串行与既有同题结果可见混合时延上升，但没有引擎queue/prefill/decode独立分解，不能把全部差值归为队列或外推高并发容量。

**第3步可进入最小调度实验，当前不默认部署新scheduler。** 混合干扰提供了实验理由，尚无新调度方案的实际收益或公平性证据；本次交付保留现行调度，不追加本报告之外的新矩阵或门禁。

**第4步继续暂缓。** 当前一次JSON先依据/条件后结论，需完整解析、有效ID/结束原因及输出检查后交付；提前发布会改变这项契约。现有短答案已较快，本轮未证明分段提前交付的收益，不能仅凭愿望增加流式补丁或绕过条件/输出检查。

## Final Local Verification

`validation/final-backend-matrix.log` 已核实：unit/perf **1091 passed、4 deselected、3 warnings**（43.84s）；进程内E2E **131 passed、2 skipped、3 warnings**（27.52s）；合计1222 passed，合并coverage **74%**，通过既定60%门槛。这更新了前报告“完整矩阵待完成”的快照，但不把本地通过冒称远端GitHub检查已完成。

有限实验规模、原留出失败、已暴露题复测与独立新题的区别继续保留。后续仅按既定CI/合并发布流程收尾，不再调整生成提示来覆盖历史问题。
