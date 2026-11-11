# Review Tracking

## Design Gate
独立critic/defender并行完成v1与v2；v2无剩余Critical/High设计阻断后开始编码。

| ID | Severity | Status | Fix | Verification | Regression |
|---|---|---|---|---|---|
| F-01 / D-02 | High | design-resolved | 分段生成终态经shared_state、API、历史与capture传递 | 待Step4 | 待Step4 |
| F-02 / D-01 | High | implemented | typed busy终止控制调用和Graph；双outcome清旧值 | admission-red.log → admission-green-v2.log | test_local_model_admission.py |
| F-03 | High | implemented | 最终Generate同步/异步传播busy | generation-busy-red.log → admission-green-v2.log | test_actual_graph_generation_busy_is_terminal |
| F-04 | High | implemented | condense及底层同步/异步助手传播busy | cleanup-red-v2.log → step3-backend-v2.log | test_query_transform_busy_propagates_without_fallback |
| D-03 | Medium | closed | 四个SDK入口共享单槽，无可继承重入许可 | 队列/取消/网络流关闭定向测试通过 | test_local_model_queue.py |
| D-04 | Medium | pending-experiment | 简短evidence与首段全部条件 | 待真实模型 | 待留出 |

## Step 3 Backend
全量 unit/e2e/perf 的业务与队列测试通过；第二次全量为1238 passed、6 skipped、5个测试环境失败。5个失败均因继承代理导致隔离命名空间内的localhost测试索引无法访问。清除代理后定向重跑依赖安装文件16 passed，合计全部1243项通过、6项跳过；没有修改依赖安装业务逻辑。首次全量的Fast测试替身缺新字段已对齐两个维护中的fake。日志见validation/，真实性能和最终整体验收另行记录，不以单元测试声称加速。
