# Final Critic Review — Segmented Procedure Coverage

**Date**: 2026-11-11
**Mode**: 完整 critic，生成热路径；未读取 defender 报告，未运行模型或修改业务代码。
**Scope**: 默认关闭的条款选择机制及 Fast/Thinking 接线；步骤、条件、记录与用途覆盖，不宣称全部流程质量或默认启用资格已合格。

## Decision

- Critical: 0 within the accepted disabled delivery scope.
- High: 1，`defended-with-alternative`：保持默认 false 隔离未合格选择行为；问题未修复。
- **允许按下述两阶段合并默认关闭的能力；禁止改默认 true。** 最终提交仍需对应阶段测试/CI 和 tracking 提交号，不以本评审代替。

**praise (non-blocking)**：开发流程严格完整质量 8/8；新留出核心步骤/条件/记录/用途覆盖 12/12，完整交付显著更快，且仍每答一次最终生成。原文组合保留了具体字段和事件条件，真实来源、历史及完整检查后发布契约成立。

新留出严格完整质量仅 **6/12**（基线 1/12）：六条中文都加入墙钟颜色和年鉴数量，视觉首节未给交接完成才阅览的主要规则。R3 Fast 中文是基线合格→候选失败，足以拒绝默认资格，不能用总分或速度抵消。

## Finding

### F-13 — 新留出中文选择无关条款且首节缺主要放行规则

**issue (blocking for default enablement; alternative accepted for disabled delivery)**

- **id**: F-13；与历史 F-10 的无关选择属于同类残留，不冒称旧问题已普遍解决。
- **severity**: High。critic §2 的生成热路径边界/输出正确性未闭合；六次实际 opt-in 答案失败。当前批准范围明确为默认关闭，核心覆盖已改善，因此本 finding 阻断默认启用而不把实验保留本身认定为新增默认失效。
- **location**: `validation/procedure-api-holdout-candidate/results.jsonl:1`、`:3`、`:5`、`:7`、`:9`、`:11`；`core/procedure_generation.py:147` 原样发布所选条款；REQ-601/604。
- **symptom**: 中文首节选择 `[1,8,16,17]`，把墙钟绿色、18 本年鉴当作适用规则正文；交接签名后才阅览的条款 6 在后段，未出现在要求的视觉首节。完整动作和用途本身齐全。
- **impact**: 严格留出只有 6/12，且出现被改机制的真实配对下降。真实引用、正常 stop 和更快交付都不能证明相关性或首节组织合格。
- **root_cause**: 单次条款选择仍会选择同语种不相关事实并排错首节；直接原文渲染保真，不能纠正语义选择错误。
- **recommendation**: 保持 `core/segmented_generation.py` 默认 false 与 `.env.example` 的 false；文档明确 opt-in 限制及留出失败。按已确认范围停止用本留出调 prompt/阈值/采样，不把失败改判通过。未来若继续改行为，须另立最小设计并重冻留出。
- **verification**: 已核对六个真实请求/最终答案和全部首次正文事件；false 的开发及留出基线实际仍为 GroundedAnswer/0.7，一次最终生成。代码默认与示例均为 false；修复提交号及各阶段测试证据由 tracking 回填。隔离验证不等于语义缺陷修复。
- **status**: defended-with-alternative — 父任务已明确接受 false 隔离的交付范围；默认资格仍不通过，问题保持已知未修复。

## Qualification Interpretation

开发普通题严格分数为两侧各 15/16，候选整批 23/24，保留一条配对下降；16 条普通题实际最终 request 完全不变。这是未改 GroundedAnswer/0.7 路径的既有波动证据，不应通过反复抽样或扩大本次 prompt 修改来追求逐答相同。

质量门槛针对被改路径的实质退步。本次留出的中文问题确实由 ProcedureAnswer 的选择造成，不能援引上述普通题解释豁免。默认 false 是明确的替代交付决定，而不是宣称质量门槛通过。

F-07/F-08/F-09 的资格修复及 F-12 的开发复现关闭条件已有独立代码/API 证据；其 commit/永久回归关联交由 tracking 完成。历史失败不删除、不翻案。

## Two Independently Mergeable Stages

1. **Pure mechanism and unit contract**：新增 `procedure_generation.py`、general procedure prompt、局部 reranker marker、golden，以及只覆盖 annotation/source/history、中文事件、measured foreign 资格、marker 的中间版本单元文件。暂不包含 generation_chain、segmented_enabled 或 Fast/Generate 入口改动。纯函数依赖均已在主干存在；新 prompt 尚无生产消费者，marker 不改 predict、旧分值或旧消费者。这一范围可独立合并，现有行为不变。
2. **Integration and delivery documentation**：加入完整请求/渲染/发布契约、资格路由、Fast/Generate 实际证据预选、完整单元/API 场景和 breaking/运维文档。非流程、comparison、rewrite、不合格证据回原完整生成；默认及示例继续 false。披露覆盖收益、严格留出 6/12 以及无关内容/首节限制。

用独立临时 worktree 验证阶段 1 的实际中间提交及 unit/e2e/perf，阶段 2 验证最终树；冻结最终工作树无需为切分实验行为而变化。不能只把最终测试文件整体放入阶段 1，因为其中 generation_chain/完整发布测试依赖阶段 2。两阶段都应按实际提交通过矩阵并回填 tracking 后合并。

已独立核对最终后端矩阵 `validation/final-backend.log`：**1313 passed / 6 skipped / 3 warnings**，65.38 秒；3 项 warning 与此前矩阵相同（jieba/pkg_resources、两项 SWIG 类型警告）。`validation/final-coverage.log` 总覆盖率 **75%**。本次预选后定向检查为 69 passed。最终工作树的矩阵已完成；阶段 1 实际中间提交的独立 worktree 矩阵仍待执行，两个阶段的提交号与 CI 仍须回填。

## Evidence Archive

详细证据以 `validation/evidence.tar.gz` 归档交付。以下列出报告在本 spec 中的原相对路径，报告本体按原路径完整保留为归档成员，不依赖 GitHub 上单独存在这些文件：

- `review/critic-v1-history.md`：最初设计评审；`review/mechanism-v*-critic.md` 保留各机制完整过程与失败。
- `review/final-code-critic.md`、`review/noise-removal-code-critic.md`：最终代码和预选接线评审。
- `review/api-noise-removed-critic.md`：开发集全部 24 配对、来源/调用/延迟。
- `review/api-holdout-critic.md`：新留出全部 12 配对、具体缺失/无关内容、视觉首节与完整发布分别评分、默认判定。

## Delivery Verification Addendum

主Agent补记（不改变独立语义评审结论）：Stage 1实际29a6ae1独立矩阵1282 passed/6 skipped、coverage74%；Stage 2补默认关闭/显式false回归后1315 passed/6 skipped、coverage75%，日志为归档中的stage1-backend.log、final-policy-matrix.log及相应coverage。运行时代码冻结未变，新增测试仅证明不启用时保留原路径。
