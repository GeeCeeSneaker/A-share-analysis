# A-share-analysis PR #16 二轮复审与 GT-H1.2 原子全量审核收口要求

> Date: 2026-09-06  
> Authoritative main before this document: `bd088a257b0ffd1189e089b3a0bf8def32cd113c`  
> PR #16 reviewed head: `f725b189b6d8b429ab08102847b86576c8bb4e7c`  
> Reviewer review: `5123839198`  
> CI: GitHub Actions `34005167481` / run 317 SUCCESS  
> Status: **GT-H1.1 P0-01/P0-02 VERIFIED / GT-H1.2 REOPENED / CHANGES REQUIRED / DO NOT MERGE**

## 1. 二轮复审裁决

PR #16 对首轮两个 P0 的修复方向和实现均保留：

1. structural identity 不再作为 Golden row 唯一键；`golden_case_id` 唯一即可，同一真实 ST/DELIST 事件可以有多个不同 `trade_date` 的 observation cases；Formal/manifest 只按 structural identity 去重计数。
2. `review.py` 在 evidence staging 之前执行 dataset-wide readiness gate：要求 clean v4+、manifest schema v2、零 invalid structural cases、全部 COMPILED、无 review provenance。旧 v1-v3 和结构不完整候选继续 fail closed。
3. run 317 的 Windows 3.14、Windows 3.12、Ubuntu 3.14 三个 required CI legs 全部成功。

以上两个首轮 P0 视为 **VERIFIED / KEEP**。

但二轮复审发现新的生命周期 P0：当前 review readiness 与 partial review publication 组合后会造成不可恢复的 mixed ACTIVE 状态，因此 PR #16 暂不允许合并。

## 2. GT-P0-03 — partial review publication lifecycle deadlock

当前入口规则要求：

```text
review entry:
all ACTIVE cases == COMPILED
```

但 CLI 仍允许：

```text
--case <one-case>
```

以及只覆盖部分 case 的 `--manifest`。

因此存在确定性死锁：

```text
clean v4 candidate (N COMPILED)
    ↓
review 1/N or K/N
    ↓
publish reviewed ACTIVE
    ↓
ACTIVE = K REVIEWED + (N-K) COMPILED
    ↓
next review readiness
    ↓
REFUSED: every case must remain COMPILED
    ↓
full human review can never complete
```

不得通过放宽 readiness gate、允许 mixed ACTIVE 继续增量 review 来解决，因为这会重新引入 candidate/review lineage 混合，并使“发现候选事实错误后应该回到哪个 clean candidate”重新变得模糊。

## 3. 管理裁决：采用原子全量 review publication

为保持架构简单、可审计，不增加 partial-review 状态机。

Human review 可以长期、分批准备 review packet，但 **ACTIVE publication 只能一次性完整 seal 当前 clean candidate**。

正式合同：

```text
clean candidate
    ↓
review packets may be prepared incrementally outside ACTIVE
    ↓
one publishing batch
    ↓
case IDs == ACTIVE case IDs exactly
    ↓
all artifacts/kinds/provenance validated in memory
    ↓
all output rows == REVIEWED
    ↓
commit evidence
    ↓
create reviewed immutable dataset + manifest
    ↓
ACTIVE moves last
```

## 4. GT-H1.2 唯一允许的代码范围

### 4.1 complete-coverage gate

在读取/复制 durable evidence 或创建新版本前，review publisher 必须验证：

```text
submitted_case_ids == active_case_ids
```

并且：

- 每个 ACTIVE `golden_case_id` 恰好出现一次；
- 不得缺失；
- 不得重复；
- 不得出现 foreign case；
- dataset N>1 时，`--case` 单条 publish 必须拒绝；
- dataset N==1 时，可允许单 case 作为完整覆盖的退化情形。

### 4.2 atomic review output gate

所有 review entry 在内存中 apply 后、任何 durable publication 前必须再次断言：

```text
review_summary == {REVIEWED: N}
all cases have complete review provenance
all artifact source bytes were actually read
all artifact digests are derived from those bytes
all semantic hashes self-validate
manifest statistics are recomputed from the final cases
```

不得发布 `REVIEWED K/N` 的 ACTIVE dataset。

### 4.3 zero-side-effect rejection

以下拒绝必须证明：

```text
ACTIVE pointer unchanged
no new immutable dataset version
no new manifest version
no new evidence artifact
```

适用：

- single-case against N>1;
- partial batch;
- duplicate case in batch;
- foreign case in batch;
- legacy v1-v3 ACTIVE;
- schema<2;
- invalid structural case;
- malformed artifact/kind/provenance input。

### 4.4 保留现有正确边界

不得回退：

- explicit `event_effective_date`；
- no `trade_date` fallback；
- structural deduplicated counting；
- repeated observation cases allowed；
- v1-v3 immutable/loadable but Formal fail-closed；
- schema-v2 manifest self-verification；
- content-addressed evidence；
- create-only version files；
- ACTIVE pointer last；
- Human Review 与 candidate compilation 职责分离。

## 5. Required adversarial tests

至少新增/修改测试证明：

1. clean candidate N>1 + `--case` -> refused / zero side effects；
2. batch N-1 -> refused / zero side effects；
3. duplicate ID batch -> refused / zero side effects；
4. foreign ID batch -> refused / zero side effects；
5. exact N/N batch -> success；
6. success 后 `review_summary == {"REVIEWED": N}`；
7. 每一个 REVIEWED case 的 artifact ref/hash 都可解析并 exact verify；
8. tampered/missing artifact 继续使 formal review gate fail closed；
9. old v3/incomplete-v4 refusal 保持 zero side effects；
10. repeated structural observation cases仍允许且只计一个 structural event；
11. old run-bound Golden replay 不受影响。

当前 `test_review_twice_rejected` 不应继续作为正常 lifecycle 的正向设计。它现在证明的是死锁。应改成“partial first publish itself is refused”。

## 6. Scope prohibition

GT-H1.2 PR 修复期间继续禁止：

- 添加真实 GT-H2 Golden corpus facts；
- 执行真实 Human full review；
- 执行 Formal Production B1-B7；
- Data Sufficiency；
- Provider capability approval；
- 2020+ backfill；
- strategy/backtest/trading work。

## 7. Exit gate

PR #16 只有同时满足以下条件才可再次提交 Reviewer closure：

```text
GT-P0-01 structural row/event semantics        VERIFIED
GT-P0-02 clean-candidate review readiness      VERIFIED
GT-P0-03 atomic complete review publication    VERIFIED
full/partial/duplicate/foreign rejection       zero side effects
full N/N reviewed batch                        success + REVIEWED N/N
three required CI legs                         SUCCESS
no Golden facts / no Production execution      VERIFIED
```

通过后才允许合并 PR #16。合并后下一阶段是 **GT-H2 clean Golden corpus construction**；GT-H2 完成并经 Reviewer 审查后，才进入实际 Human Review / GT-H3 seal。
