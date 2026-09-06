# A-share-analysis PR #18 三轮复审与 GT-H2.2.1 BJ 外部证据诚实性收口要求

> Date: 2026-09-06  
> Authoritative baseline before this review: `main@24a3b3468565d3ca4f627d43b27e896fca13bb4d`  
> PR: #18 `feat: build GT-H2 clean golden candidate`  
> Reviewed head: `fb1949e4c64b0ed196477873cc9f75c0098c5b18`  
> Reviewer review: `5125169271`  
> Final-head CI: run 335 / `34028088458` — Windows 3.14 / Windows 3.12 / Ubuntu 3.14 SUCCESS  
> Tested merge tree: `d7255e41b01284c4e27cb51d7158ed130be8c3a8` = `main@24a3b346` + `PR head@fb1949e`  
> Status: **GT-H2.2 P0-01 CLOSED; BJ claim narrowing PASS/KEEP; GT-H2.2.1 P0-03 OPEN; DO NOT MERGE**

## 1. 本轮已关闭内容

### 1.1 STAR / ST 规则来源错配已关闭

此前 `"ST" in event_id` 会把 `REGIME-STAR-20` 错分到 ST 5% 分支。当前实现已经改为 exact `event_id` 选择，并增加 fail-closed expected-rate assertion：

- `REGIME-STAR-20` -> STAR 20% official rule；
- `REGIME-ST-5` -> SSE/SZSE 5% risk-warning rule；
- 未知 regime -> fail closed；
- STAR 不再可能进入 ST 分支；
- packet 已重新生成并验证 5 个 STAR20 rows 均为 20% 语义。

该项正式：**VERIFIED / CLOSED / KEEP**。

### 1.2 BJ claim narrowing 方向正确

当前 3 个 BJ rows 已不再把 `CODE_CONTINUITY` / `SEGMENT_VALID` 作为 executable expected_fields，而改为：

```text
PRICE_HIGH_LMT_RATE = 0.3
PRICE_LOW_LMT_RATE  = 0.3
```

`truth_source` 也改为“historical master presence + exact-date status + run-bound BSE rule/price”这一类与 `_validate_bj_mapping()` 更接近的描述。

方向正确，应保留；但外部 artifact 尚未同步，因此该项只能判定 **PASS / KEEP, NOT CLOSED**。

## 2. GT-H2.2.1 P0-03：BJ 外部 artifact 与新 Golden truth 仍不一致

当前 v4 的典型状态：

### `GT-BJ-835185-2022`

Golden assertion：

```text
expected_fields = 30% / 30%
truth_source     = historical master + exact-date status + BSE 30% rule/price
```

但 `source_ref` 仍是：

```text
BSE official new/old code mapping table (835185 -> 920185)
```

该 artifact 是映射上下文，不是证明当前 expected 30% rate 或 2022-06-01 exact-date master presence 的 artifact。

### `GT-BJ-920-SEGMENT`

Golden assertion：

```text
expected_fields = 30% / 30%
truth_source     = historical master + exact-date status + BSE 30% rule/price
```

但 `source_ref` 仍是：

```text
BSE 920 code-segment launch announcement
```

它证明号段/迁移背景，不等于证明 2024-07-01 的 exact provider-master presence 与 30% rate truth。

当前 packet checklist 甚至明确要求：

```text
do not infer a stronger mapping guarantee from the contextual official document
```

这反过来证明当前 artifact 被当成“context”，而不是当前 Golden assertion 的直接证据。

## 3. 冻结原则

Golden Truth 必须继续满足：

```text
Golden truth claim
== expected semantic assertion
== Human-review external artifact
== Formal validator executable proof
```

Provider 自身返回结果不能反过来充当 Golden Truth 的独立外部真值来源。

Human Review 的任务是核对独立官方事实，并把真实 artifact bytes/hash 绑定进不可变 evidence；不能在审核阶段重新解释“这个 artifact 实际不证明 expected truth，但 Provider 输出证明了，所以仍 REVIEWED”。

## 4. 首选收口方案：删除 3 个 BJ mapping Golden rows

这是当前最低复杂度、最高诚实度方案，也是 Reviewer 默认要求。

原因：

1. `REQUIRED_GOLDEN_COUNTS` 当前只强制：
   - ST >= 50
   - DELIST >= 20
   - LIMIT >= 30
   - CORPORATE_ACTION >= 20
2. `golden_bj_mapping` **不是 Formal quantity gate**；
3. 当前已有正式 `golden_limit_regime` BSE 30% cases，可以覆盖 executable BSE rate truth；
4. 为了保留 3 条不构成 hard gate 的“mapping”记录而扩展 mapping validator / multi-artifact review model，会增加当前阶段不必要复杂度；
5. 真正 BJ old/new code / 920 migration capability 可以在后续 Provider capability / Data Sufficiency 阶段单独设计并验证。

因此 GT-H2.2.1 默认执行：

```text
DROP GT-BJ-835185-CONTINUITY
DROP GT-BJ-835185-2022
DROP GT-BJ-920-SEGMENT
```

然后重新生成：

- `golden_cases_v4.jsonl`
- `truth_manifest_v4.json`
- `truth_manifest.json`
- `rebuild_plan_v4.json`
- `review_packet_index.jsonl`
- `GT_H2_CORPUS_REPORT.md`
- semantic hashes / dataset hash
- related tests / DEVLOG / DEVELOPMENT_MANAGEMENT

预计 case_count 从 128 -> **125**。不要为了维持 128 数字补 filler case；数量不是目标。

删除后必须重新证明：

```text
review_readiness_gate == []
quantity_gate         == []
event_coverage_gate   == []
production_formal_gate only reports human-review blocker
review_summary        == COMPILED 125/125
```

## 5. 可选方案：真正实现 BJ mapping validator

只有项目明确决定“BJ mapping 必须现在进入 Formal Golden”时才采用。

该方案必须同时做到：

1. Golden expected_fields 明确编码真实 mapping / segment assertion；
2. Provider observation 真正执行并证明该 assertion；
3. case-level official artifact 证明同一个 assertion；
4. validator 不再只检查 historical master presence + 30% regime；
5. 若一个 Golden fact 必须由多个独立 official artifacts 才能证明，不得伪装成 one-artifact proof：
   - 要么拆成多个独立 case；
   - 要么显式升级 review-artifact model 支持多 artifact closure。

本阶段不推荐该方案，因为它不是当前 Formal hard gate，且会扩大 GT-H2 复杂度。

## 6. 必须新增/更新的回归

首选 DROP 路径：

```text
[ ] ACTIVE v4 无 golden_bj_mapping rows
[ ] packet 无 BJ mapping rows
[ ] 不存在“expected 30% 但 artifact 只证明 mapping/segment”的 case
[ ] counts/gates 重新计算正确
[ ] Formal non-review gates zero problems
[ ] only blocker = REVIEWED 0/125
[ ] v1-v3 immutable files unchanged
```

若采用真正 mapping validator 路径，则必须额外增加 source/expected/provider-result/validator 全链一致性 adversarial tests。

## 7. 继续冻结的边界

GT-H2.2.1 完成前：

- 不运行 `review.py` final seal；
- 不进入 GT-H3；
- 不运行 Production B1-B7；
- 不作 Data Sufficiency / Provider capability decision；
- 不做 2020+ backfill；
- 不运行策略 / 回测 / 交易；
- 不为了制造 GO 修改 Golden truth 或 Provider rule truth。

## 8. 下一次 Reviewer 复审标准

下一轮只审 GT-H2.2.1 增量：

1. 首选 3 个 BJ mapping rows 已 DROP，或有充分理由实现了真实 mapping validator；
2. Golden truth / expected_fields / source artifact / Formal validator 完全一致；
3. v4 与 packet 全量重新生成且 hashes 一致；
4. `COMPILED N/N`，没有伪造 REVIEWED；
5. final head 三平台 CI 全绿；
6. CI 实际测试 merge tree 必须包含本 Reviewer main baseline；
7. 无 Production、Human seal、Provider approval 或 backfill 越级。

满足后可给出：

```text
GT-H2.2.1 VERIFIED
GT-H2 CLOSED
MERGE AUTHORIZED
```

合并后再进入独立 Human Review / GT-H3 artifact-binding 与原子全量 seal 阶段。