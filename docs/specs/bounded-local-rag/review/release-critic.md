# Release Critic — Bounded Local RAG

**Date**: 2026-11-10。独立只读核验；未运行模型/测试，未改业务，未读取本轮 defender。

## Decision

**可进入既定提交、CI与main合并收口**。默认已由legacy改为auto；仍严格限定精确本地9B/general和实际0.24.0-format-backport，其他运行时维持legacy。新增Critical/High阻断0，不提出新门禁或矩阵。已披露的零值概括句引述归属问题（Medium）继续保留，不能宣称逐字引文完美。

`run_bounded_api_probe.py:19–33` 在default模式显式移除LOCAL_RAG_POLICY并禁用dotenv；因此本轮是实际缺省选择验证，不是显式bounded重命名。两个默认请求实际metadata为bounded，wire也符合该策略。

## Results

| Completed group | Full-answer verdict | Evidence |
|---|---|---|
| default-final，电池Fast/Thinking各1 | 2/2实质正确 | 600min=10h，或9h=540min，关系均明确；5/8 W归属正确且不能外推同负载；正文两来源齐。 |
| mixed-final，电池两模式×两轮 | 4/4实质正确 | 明确芦序记录更长，保留负载差异及未给同负载数据；没有错实体或比例外推。 |
| mixed-final，零值两模式×两轮 | 4/4实质正确，1处既有引述措辞局限 | 10分钟基准、0ms=0s、测量已完成而非缺测、两来源均正确。r1 Thinking“资料中明确说明记录的零值是数值，不等于缺测”把正确推论说成原文直接声明；原文实际是“本次测量已完成…该数值是本次测试的记录结果”。延续已披露Medium，未改变数值/结论或引入新实质退步。 |

这是2个暴露题的模式/轮次复测，不是10道独立留出。10槽全部完成，无超时/丢请求/拒答；四个此前Fast覆盖缺口及历史失败仍按 `final-quality-critic.md` 保留，本轮不追溯改判。

默认2槽共5个HTTP（2生成+各1意图/工具规划/grade）；混合8槽共20个（8生成+各4意图/工具规划/grade）。全部生成2048双预算字段、none、temperature0.7/top_p0.8；控制双字段256、none。生成及结构化控制stop、工具tool_calls，隐藏reasoning字符0，无length、judge、补写或重试。各生成实际来源序号有效，conclusion位于JSON末尾；并发收据按实际query/证据归属读取，不用全局计数范围硬配单题。

10槽SSE token拼接=done=results.jsonl中的结果正文；grounding=None、confidence_degraded=true。结构/PII检查仍在交付前，无在线语义核验通过的虚假声明。

## Timing and Steps 3/4

首已检正文时间：默认电池Fast **3.628s**，Thinking **5.878s**。混合Fast4槽 **4.166–4.783s，P50 4.385s/P95 4.750s**；Thinking4槽 **8.382–9.168s，P50 8.966s/P95 9.167s**（线性分位数）。混合批次35.939s完成8槽，未以丢请求改善指标。

**Step 3**：已具备在可用单请求基础上试验调度的前提，但本次没有调度变体。真实HTTP重叠可见，例如混合第2条Fast生成11941.197–11944.914期间，第3条Thinking工具规划11942.107–11945.689；这证明请求重叠及等待增长，不能将整段HTTP时间或单请求差值直接认作引擎队列时间，尤其不能宣布queue占比≥20%。保留有界后续试验价值，尚无调度已收益或应默认开启的证据。

**Step 4**：保持暂缓。当前JSON先basis/conditions、最后conclusion，正式正文须完整解析、有效引用和输出检查后发布；当前没有在线NLI，旧生成与NLI重叠收益不能直接迁移。本轮2–9s级短回答没有实测提前发布收益。若改为先发依据/独立段落，需另行处理完整条件、末尾结论、PII/整答拒绝契约；不能把草稿到达当已核验首段，也不把当前暂缓推广成所有流式架构均无收益。第3/4步均不阻塞本次已合格策略交付。

## Local Matrix and Evidence

已读 `validation/final-backend-matrix.log`：unit/perf **1091 passed / 4 deselected / 3 warnings（43.84s）**；进程内E2E **131 passed / 2 skipped / 3 warnings（27.52s）**；coverage **74%**，超过60%既有阈值。此前失败日志保留；这里是本地最终矩阵，未冒称尚未执行的远程CI成功。

实测根：`data/eval/bounded-local-rag-default-final/`、`data/eval/bounded-local-rag-mixed-final/` 的 `results.jsonl / model-http.jsonl / batch.json`。本报告不修改默认资格的既定边界；余下只需既定提交、远程CI和合并流程。
