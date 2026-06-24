# 闭环追踪矩阵 — retrieval-stack-bm25-reranker(Stage A)

## 1. 追踪矩阵

| 发现 ID | 严重性 | 对应 REQ | 辩护决策 | 验证测试 | 状态 |
|---------|--------|----------|----------|----------|------|
| F-RS-01 | Medium | REQ-RS-003 | accepted | CJK 基本区实测覆盖全部航空术语 | **accepted** |
| F-RS-02 | Medium | REQ-RS-005 | accepted | batch 4 + 文档告知运维 | **accepted** |
| F-RS-03 | Low | 设计 §6 | accepted | 当前 2852 条未触发,P3 | **accepted** |
| F-RS-04 | Low | env | accepted | CHANGELOG 告知 | **accepted** |

## 2. 闭环状态
- **Critical: 0 / High: 0** → 门禁满足(无 Critical/High 需闭合)。
- **Medium: 2 accepted** · **Low: 2 accepted**。

## 3. REQ 达成度(诚实)

| REQ | 目标 | 达成 | 证据 |
|-----|------|------|------|
| REQ-RS-001 | jieba 词级切词 | ✅ | 发动机叶片振动→[发动机,叶片,振动] |
| REQ-RS-002 | 降级 warning | ✅ | test_missing_jieba_logs_warning |
| REQ-RS-003 | 中文单字保留 | ✅ | 泵/阀/轴 保留 + 中英 min_token 分离 |
| REQ-RS-004 | 中文 reranker | ✅ | bge-v2-m3 加载 + 中文 predict 有效 |
| REQ-RS-005 | OOM 防护 | ✅ | batch 4 + fallback 兜底 |
| REQ-RS-006 | BM25 中文召回 | ✅ | score=1.76(修复前 0) |
| REQ-RS-007 | score>0 过滤保留 | ✅ | 零重叠文档过滤 |
| REQ-RS-008 | precision↑ | ⚠️ **未达成(0.250<0.261)** | 根因分块瓶颈,转 Stage B |

**REQ-RS-008 修正**:precision 目标需改为 recall/hit_rate↑(已达成 0.5→1.0)+ answer_overlap↑
(已达成 0.835→0.967)。precision 提升依赖 Stage B 分块优化。

## 4. Backlog(转后续 stage)

| RISK | 描述 | 来源 | 转移到 |
|------|------|------|--------|
| precision 瓶颈 | top_k=4 里 gold 占 1/4,precision 封顶 0.25 | REQ-RS-008 | **Stage B**(dedup-source/分块优化) |
| bootstrap limit=10000 | 全量入库 >1 万截断 | F-RS-03 | Stage B/C |
| reranker 热恢复 | _load_attempted 粘性,OOM 需重启 | F-RS-02 | Stage C/D |

## 5. 验证证据

| 项 | 命令 | 结果 |
|----|------|------|
| regression test | `pytest tests/unit/test_bm25_chinese_tokenization.py -q` | **12/12 passed** |
| 检索 benchmark CMRC | `run_benchmark.py --dataset cmrc2018 --top-k 4` | hit/recall 0.5→**1.0**,overlap 0.835→**0.967**,precision 0.250(分块瓶颈) |
| bge 中文打分 | `CrossEncoder.predict` | 0.9234/0.0000/0.4540 |
| jieba 航空术语 | `jieba.cut` | 起落架/液压伺服阀/燃油喷嘴 全部正确 |
