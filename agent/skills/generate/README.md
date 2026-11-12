# Generate Skill

基于实际kept evidence生成带正文引用的答案。合格本地9B/general使用一次有界生成，不在线反复调用模型核验；legacy继续保留原reasoning/grounding路径。

## Inputs
用户问题、shared_state.retrieval_evidence、来源/相关性信号和rewrite_count。原ToolMessage兼容路径仍保留。

## Outputs
AIMessage为最终用户正文；generation_evidence为实际使用的证据集合；generation_outcome整键描述complete/incomplete/unavailable。失败/拒答清旧状态，缺失核验信号保持None/degraded。

## Publication
LOCAL_RAG_SEGMENTED默认true；仅合格中文明确流程、非比较且rewrite_count=0时，同次对完整原文条款直接选择类别，再按规则/范围、步骤、记录/用途及条件/边界组成原文，完整stop并一次检查后发布。内部分类不展示、不作事实证明；英文等其他问题保持原basis→conditions→conclusion及原证据。实际kept来源与上下文同步，原retrieval_evidence保留。非法槽位/字段、length或检查失败为不可用且confidence=None，不追加生成；显式false回滚。

SkillContext中的当前输出检查器/receipt不序列化。队列busy直接传播到Harness，不进入生成重试。同步非流式与流式都要求有效JSON、真实来源及正常stop结束。预算2048、top_p=.8、reasoning_effort=none；流程选择temperature=0，其他生成=.7。新留出相关性未合格，默认关闭，见[实验结果](../../../docs/specs/segmented-procedure-coverage/results.md)。

## Validation
[设计、独立评审与实测](../../../docs/specs/local-scheduling-streaming/)，[配置与回滚](../../../docs/deployment/BOUNDED_LOCAL_RAG.md)。legacy配置定义以config.py为准，不能把legacy重试次数当作bounded调用次数。
