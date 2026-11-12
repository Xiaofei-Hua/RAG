# Validation Evidence

全部语料为合成资料，不含用户文档、运行数据库或凭据。保存成功、失败与中断，不用结构合法代替语义评审。当前结论见[results](../results.md)，用户对默认门槛的知情调整见[acceptance decision](acceptance-decision.md)；原严格评分未回写。

| Archive | Contents |
|---|---|
| mechanism-evidence.tar.gz | v1–v13机制原始请求/响应、协议、提示与临时脚本 |
| api-history-evidence.tar.gz | v9 API/失败留出及不计验收的早期中断 |
| api-development-evidence.tar.gz | v13完整API两侧44答及模型调用 |
| holdout-v13-failed-evidence.tar.gz | v13冻结、三新题两侧18答；候选15/18，转开发 |
| semantic-key-failed-evidence.tar.gz | v14/v15同14上下文失败实验，均未接线 |
| full-clause-evidence.tar.gz | v16真实14答、v17回放、冻结代码与原提示 |
| api-v17-evidence.tar.gz | v17七中文题两模式两轮、对应基线索引与统计 |
| holdout-v17-failed-evidence.tar.gz | v17新留出12/18首节未过，原结果保留 |
| priority-failed-evidence.tar.gz | v18已完成37答后停止，未接线，无第38完成wire |
| sentence-reference-evidence.tar.gz | v19先导2答、开发40答、冻结代码及分句实验入口 |
| holdout-v19-failed-evidence.tar.gz | v19两侧各18答；原严格首节12/18失败，后用户接受位置限制；内容18/18 |
| position-failed-evidence.tar.gz | v20两答1/2，Fast丢记录，停止52答扩展 |
| opening-flag-failed-evidence.tar.gz | v21两答许可均后置且增加token，未扩展/未接线 |
| default-v19-evidence.tar.gz | 三项配置unset的真实默认6答，内容6/6、首节4/6，15HTTP |
| engineering-evidence.tar.gz | 全设计修订、独立阶段评审、原/新验收、红绿/完整矩阵、环境、分模式统计及验证入口；v22只有提案未运行 |

归档保留仓库相对路径；解压到独立目录查看，不覆盖有本地修改的工作区。需要跨实验复现时合并解压相应数据归档。原始默认决定仅代表当时状态，最终唯一启用机制为v19六类完整键/句首回连；v20/v21未采用。
完整API用归档的tests/integration/run_bounded_api_probe.py，在[已验证模型/引擎](../../../deployment/BOUNDED_LOCAL_RAG.md)与隔离数据库中串行运行false/true，参数`--policy bounded --scheduler fair --rounds 3 --modes fast,thinking --timeout 45`；默认冒烟用三项`default`且rounds1。P95线性插值，多轮不是多道独立题；未改英文/普通控制复用相同原请求，不冒称再测。
机制适配器须配对应冻结版本：v14–v16依赖v13数字键渲染；v19实验脚本在冻结v17上暂换分组；v20/v21读取冻结v19实际请求。不能把临时适配器直接当生产代码或把直接模型时间当API首见。工程档包含完整重现入口与判据。
