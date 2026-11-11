# Generate Skill

基于实际kept evidence生成带正文引用的答案。合格本地9B/general使用一次有界生成，不在线反复调用模型核验；legacy继续保留原reasoning/grounding路径。

## Inputs
用户问题、shared_state.retrieval_evidence、来源/相关性信号和rewrite_count。原ToolMessage兼容路径仍保留。

## Outputs
AIMessage为最终用户正文；generation_evidence为实际使用的证据集合；generation_outcome整键描述complete/incomplete/unavailable。失败/拒答清旧状态，缺失核验信号保持None/degraded。

## Publication
LOCAL_RAG_SEGMENTED开启且问题非比较、rewrite_count=0时，conditions完整数组与第一个answer共同检查后一次发布首段，其余解释逐段累计检查；检查不得改写已发前缀。未完成输出保留已检查部分并返回PARTIAL/明确终态。比较和改写保留basis→conditions→conclusion完整生成；启发式分流不承诺识别所有隐含比较。

SkillContext中的当前输出检查器/receipt不序列化。队列busy直接传播到Harness，不进入生成重试。同步非流式与流式都要求有效JSON、真实来源及正常stop结束。预算2048、temperature0.7/top_p0.8、reasoning_effort=none。

## Validation
[设计、独立评审与实测](../../../docs/specs/local-scheduling-streaming/)，[配置与回滚](../../../docs/deployment/BOUNDED_LOCAL_RAG.md)。legacy配置定义以config.py为准，不能把legacy重试次数当作bounded调用次数。
