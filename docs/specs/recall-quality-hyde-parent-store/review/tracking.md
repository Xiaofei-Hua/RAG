# 闭环追踪矩阵 — recall-quality-hyde-parent-store(Stage B)

## 1. 追踪矩阵

| 发现 ID | 严重性 | 辩护决策 | 验证/修复 | 状态 |
|---------|--------|----------|-----------|------|
| F-RB-01 | High | accepted(已修) | 故障码正则扩为字母数字交错码;E1A02/FQ01/HYD3→none;补测试 | **closed** |
| F-RB-02 | Medium | accepted | expand 默认开是目标;generate budget 兜底 | **closed** |
| F-RB-03 | Medium | defended | LRU event loop 单线程下无真并发 | **closed** |
| F-RB-04 | Low | defended | batch→逐 doc 换打标可靠性;slice 非热路径 | **closed** |
| F-RB-05 | Low | accepted | corpus 需重新生成;度量时执行 | **closed** |

## 2. 闭环状态
- **Critical: 0 / High: 1(F-RB-01 closed)**。
- **合并门禁**: ✅ 通过。

## 3. REQ 达成度

| REQ | 目标 | 达成 | 证据 |
|-----|------|------|------|
| REQ-RB-001 | parent_store 写入 | ✅ | md/非 md 切片打 parent_id + store 父段 |
| REQ-RB-002 | expand 条件默认 | ✅ | 带 parent_id 默认 expand |
| REQ-RB-003 | expand 显式控制 | ✅ | shared_state false 关闭 |
| REQ-RB-004 | HyDE 接线 | ✅ | 诊断问句→hyde |
| REQ-RB-005 | multi_query 接线 | ✅ | 短抽象现象→multi_query |
| REQ-RB-006 | 精确锚点不变换 | ✅ | ATA/故障码→none(F-RB-01 修正后含 EICAS 码) |
| REQ-RB-007 | 显式覆盖 | ✅ | shared_state 优先 |
| REQ-RB-008 | 降级安全 | ✅ | LLM 失败→原 query;parent 缺失→child |
| REQ-RB-009 | LRU 缓存 | ✅ | OrderedDict LRU 128 |

## 4. 验证证据
- regression test:63 passed(含 19 新增)。
- 故障码正则:E1A02/FQ01/HYD3→none(实测)。
- small-to-big:语义多样长文本切片 + store 父段 + expand 返回父段(实测)。
- precision 度量:待 corpus 重新生成后重测(记 F-RB-05)。

## 5. Backlog
- precision 可信度量:需重跑 `prepare_benchmark.py` 重新生成 corpus(修了 source 语义)后,
  再跑 `run_benchmark.py --dedup-source`。CMRC precision 预期 small-to-big 提升 gold 密度。
