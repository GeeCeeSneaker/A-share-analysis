# A-share-analysis PR #18 二轮复审与 GT-H2.2 语义证据对齐要求

> Date: 2026-09-06  
> Authoritative pre-review main: `5685c9cec329b79507f4f38b03a7f193200463d2`  
> PR: #18 `feat: build GT-H2 clean golden candidate`  
> Reviewed head: `6e3fb24924cac848fefe4a9f9f13b8fa292890ce`  
> Reviewer review: `5124979268`  
> Final-head CI: run 331 / `34024915825` — Windows 3.14 / Windows 3.12 / Ubuntu 3.14 SUCCESS  
> PR test merge: `e292b8550c7388f5e2f68fd2a37d04211160a82c` = merge reviewed head into `main@5685c9ce`  
> Status: **GT-H2.1 CLOSED / KEEP; GT-H2.2 SEMANTIC-EVIDENCE ALIGNMENT OPEN; DO NOT MERGE**

## 1. 二轮阶段裁决

GT-H2.1 首轮三项要求已得到实质整改，应保留：

1. 128/128 packet 不再以交易所首页、公告门户根页面、通用规则目录作为 `fact_proved=true` 的 case-level locator；新增 `CASE_SPECIFIC_OFFICIAL_ARTIFACT` scope 和 portal-only denylist；
2. ST sample 已从 SSE 4 / SZSE 46 调整为 SSE 12 / SZSE 38，board 为 MAIN 32 / CHINEXT 15 / STAR 3，并实际包含 STAR ADD 与 STAR REMOVE；
3. 5 个 right-issue case 均已回到 2020-01-01+，旧 `002202.SZ / 2019-03-29` 被移除，`000750.SZ` 改用 contemporaneous 2020 官方公告；
4. candidate 继续保持 `COMPILED 128/128`，未运行 Human review seal、Formal Production B1-B7 或后续 capability/backfill；
5. run 331 三个 required platform jobs 全绿，而且 GitHub test-merge 明确把 PR head 与当前 Reviewer main 基线合并后验证，不存在“旧 base 单独绿灯”问题。

因此 **GT-H2.1 P0-01 / P1-02 / P1-03 CLOSED / KEEP**。

但二轮复审发现：来源 URL 变得“具体”以后，仍可能出现 **specific official artifact 与 Golden expected truth 语义不一致**。这比 locator 形态问题更关键，必须在进入 Human Review 前关闭。

## 2. GT-H2.2 P0-01：STAR 20% Golden case 错绑 ST 5% 规则

当前 `scripts/golden/gt_h2_prepare.py::_source_context()` 对 limit case 使用字符串包含判断：

```python
if "ST" in event_id:
    ...
```

而正常科创板 20% case 的 event id 为：

```text
REGIME-STAR-20
```

`"ST" in "REGIME-STAR-20"` 为真，因此以下 case：

```text
GT-LIMIT-STAR20-688036
GT-LIMIT-STAR20-688012
GT-LIMIT-STAR20-688599
```

虽然 `expected_fields.PRICE_HIGH_LMT_RATE = 0.2`，却被绑定为：

```text
SSE Risk-Warning Board Trading Measures
5% price-limit clause
```

这是确定性的 **false evidence binding**：

```text
official URL is specific
        !=
artifact proves the expected Golden fact
```

`fact_proved=true` 不能只表示 URL 看起来像具体官方文档，而必须表示该 artifact 的内容确实支持该 case 的 expected truth。

### 必须修复

不要增加通用 URL/网页分类系统。采用最小、确定性方案：

1. limit regime source selection 使用 exact event-id / explicit semantic mapping；
2. `REGIME-STAR-20` 显式映射到适用于 STAR 20% regime 的官方具体规则；
3. `REGIME-ST-5` 才映射到 risk-warning 5% 规则；
4. 禁止再用 `"ST" in event_id` 这种 substring 作为业务语义分类；
5. `NO_LIMIT_STAR_FIRST5`、ChiNext pre/post、BSE 30%、main-board 10% 等已有正确分支继续保持。

### 必须新增回归

至少证明：

```text
REGIME-STAR-20    -> STAR 20% official rule
REGIME-ST-5       -> risk-warning 5% official rule
STAR              != substring-classified-as-ST
```

并增加一个小型 semantic assertion，确保关键 rule-driven cases 的 source claim 与 expected regime 一致。目标是防止具体 URL 绑定到错误规则，不要求做网页内容 NLP。

修复后重新生成：

```text
review_packet_index.jsonl
official_fact_registry.json
rebuild_plan_v4.json
golden_cases_v4.jsonl
truth_manifest_v4.json
truth_manifest.json
GT_H2_CORPUS_REPORT.md
```

所有 semantic hash / dataset hash / manifest binding 必须随真实数据变化自然更新，不得手工改 hash。

## 3. GT-H2.2 P1-02：BJ mapping truth claim 与 Formal validator 实际语义未完全对齐

当前三个 `golden_bj_mapping` case 在 packet 中使用：

```text
CODE_CONTINUITY = true
SEGMENT_VALID   = true
```

并分别引用：

- BSE 2021 opening/trading rule；
- 835185 -> 920185 new/old code mapping table；
- 920 code-segment launch announcement。

但是当前 `_validate_bj_mapping()` 的可执行 Formal 语义实际是：

```text
1. 当前 case 的 bare code 存在于 Provider historical security master；
2. 当前 trade_date 存在 exact status row；
3. run-bound BSE rule 可解析；
4. Provider observed limit price/rate 与该 BSE rule 一致。
```

它并不读取 `expected_fields.CODE_CONTINUITY` 或 `SEGMENT_VALID`，也没有直接验证：

```text
835185 -> 920185
```

这一旧/新代码关系。

这会造成 Truth packet 声称的事实强于 Formal runtime 真正验证的事实。

### 推荐的低复杂度收口

优先选择 **truth honesty alignment**，不要立即引入复杂 mapping 状态机：

- 如果 B7 V1 本意只是验证“BJ code 能在历史 master/status 中正确出现 + BSE rule 语义正确”，则改写 case 的 `truth_source`、`expected_fields`、packet checklist，使其准确描述这一可执行语义；删除不会被 validator 消费、容易造成虚假保证的 stronger mapping fields。
- 如果项目明确要求 B7 V1 必须证明 `old_code -> new_code` 或 920 segment relation，则增加一个小而显式、可由现有 Provider data 独立执行的 mapping check，并用 adversarial test 锁定；不要仅依靠 source prose 声称已验证。

Reviewer 默认偏向第一种低复杂度方案，除非现有设计文档已经明确把 old/new code relation 定义为 B7 Formal 必测合同。

无论采用哪种方案，必须满足：

```text
Golden source claim
== Human review checklist
== expected semantic assertion
== Formal validator actually executed proof
```

## 4. `allow_rekey` 合同保留但继续收紧边界

本轮为修正 legacy dividend 错误 ex-date 引入：

```text
REPLACE + allow_rekey=true
```

该方向可保留，因为 exact official ex-date 改变时 `golden_case_id` 必须同步变化。

保持以下约束：

- 默认 REPLACE 不允许 identity change；
- 只有 plan 显式 `allow_rekey=true` 才允许；
- new id 不得与其他 source/output case 冲突；
- source old id 仍必须恰好被一个 operation 消费；
- rekey 结果仍必须 COMPILED、重新计算 semantic hash；
- 不允许用 rekey 绕过 DROP/ADD 审计语义或伪造 REVIEWED provenance。

当前实现方向可 KEEP，不要求另起复杂版本迁移机制。

## 5. GT-H2.2 re-review exit criteria

下一次 Reviewer 复审前必须满足：

```text
[ ] GT-H2.1 exact locator 修复全部保留
[ ] SSE/STAR ST rebalance 全部保留
[ ] five right-issue cases remain 2020+
[ ] candidate remains COMPILED N/N
[ ] REGIME-STAR-20 no longer selects ST 5% source
[ ] STAR20 source artifact explicitly supports 20% regime
[ ] ST5 source artifact explicitly supports 5% risk-warning regime
[ ] no substring-based ST/STAR business classification remains in source selection
[ ] semantic regression covers STAR-vs-ST collision
[ ] BJ packet truth and Formal validator executable semantics are aligned
[ ] review packet still covers ACTIVE exactly once
[ ] GoldenTruthStore.load / review_readiness / quantity / event_coverage pass
[ ] production_formal_gate has only human-review blocker
[ ] final-head Windows 3.14 / Windows 3.12 / Ubuntu 3.14 all SUCCESS
[ ] no Human review seal
[ ] no Production B1-B7 / Data Sufficiency / Provider verdict / backfill
```

## 6. 下一阶段继续冻结

GT-H2.2 未经 Reviewer closure 前继续禁止：

```text
review.py final N/N seal
GT-H3 reviewed version publication
Formal Production B1-B7 retry
Data Sufficiency Matrix
Provider GO / CONDITIONAL GO / NO-GO
2020+ backfill
strategy / backtest / trading
```

### 当前状态

```text
GT-H1 / H1.1 / H1.2          CLOSED
GT-H2 mechanics              PASS / KEEP
GT-H2.1 source-quality       CLOSED / KEEP
GT-H2.2 semantic alignment   CURRENT TASK
Human Review / GT-H3         BLOCKED
Formal B1-B7                  BLOCKED
Provider capability verdict  BLOCKED
2020+ backfill                BLOCKED
```
