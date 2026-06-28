# Review Tracking — routing-and-grading-defense

> critic/defender 闭环矩阵。Critical/High 必须 4 列全填才能 `closed`（AGENTS.md §12）。回归测试永久固化防回归。

| ID | Severity | Verdict | Fix Commit / Design 修订 | Regression Test | Status |
|----|----------|---------|--------------------------|-----------------|--------|
| F-01 | Critical | accepted | design v2 §Layer⑤（判据 has_context→max_rerank_prob） | `test_generate_skill_ab_shunt.py::failtrack-1` | closed-in-design-v2 |
| F-02 | Critical | accepted | design v2 §Layer⑤（触发与 is_rewrite_limit_reached 解耦） | `test_generate_skill_ab_shunt.py::failtrack-1` | closed-in-design-v2 |
| F-03 | High | accepted | design v2 §Layer④（min-max→sigmoid+min-max 双筛） | `test_retrieve_skill_rerank_threshold.py`（全弱批 case） | closed-in-design-v2 |
| F-04 | High | accepted | design v2 §shared_state 键所有权（单键增量写 + chat.py 显式读） | `failtrack-5`（intent_confidence 防覆盖） | closed-in-design-v2 |
| F-05 | High | accepted | design v2 §不变量（签名扩展至 intent prompt）；T9 | `test_prompt_signature.py` | pending-impl |
| F-06 | High | defended-with-alternative | design v2 §Layer②（0.5 标占位 + 回归护栏 + 数据收集） | golden hard rag_query cases | closed-with-alternative |
| F-07 | Medium | accepted | design v2 §Layer⑤（流式 done payload 走 _build_metadata）；T15a | characterization metadata 键集测试 | pending-impl |
| F-08 | Medium | accepted | design v2 §Layer⑤（min_relevance_threshold 复活为绝对门槛）；REQ-RG-013a | failtrack-2/3 | closed-in-design-v2 |
| F-09 | High | accepted | design v2 §chat.py 接管哨兵（流循环显式累积 shared_state）；T15 | 流式 E2E SSE route 一致性 | pending-impl |
| F-10 | Low | accepted | design v2 §不变量（双轨重叠注释） | — | closed-in-design |
| F-11 | Medium | acknowledged-out-of-scope | design v2 §不变量（已知限制文档化） | — | out-of-scope → issue-rg-fastpath-confidence |
| F-12 | Medium | accepted | design v2 §测试矩阵（按失效轨迹 failtrack-1..5） | failtrack cases | closed-in-design-v2 |
| F-13 | High | accepted | design v2 §不变量（yaml 同步 + 防漂移断言）；REQ-RG-017；T16 | test_domain_profile 遍历 yaml 断言 | pending-impl |
| F-14 | Low | accepted | design v2 §不变量（_get_float）；REQ-RG-018；T5 | — | closed-in-design |

## 合并门禁状态

- **Critical (F-01/F-02)**：closed-in-design-v2（design.md §REVISED Layer⑤）。编码前 failtrack-1 必须先红验证。
- **High**：F-03/F-04/F-08/F-12 closed-in-design-v2；F-05/F-09/F-13 pending-impl（修订已写入 design，待编码落地）；F-06 closed-with-alternative。
- **v2 须重新过 critic**，重点验证 failtrack-1 用例在 v2 设计下确实能红（即 v1 判据被移除）。

## 待编码后补填

- 各 pending-impl 项在编码完成后填入 commit sha + test name，状态改 `closed`。
- failtrack-1 实现 + 测试通过后，本表 F-01/F-02 状态改 `verified-by-test-failtrack-1`。
