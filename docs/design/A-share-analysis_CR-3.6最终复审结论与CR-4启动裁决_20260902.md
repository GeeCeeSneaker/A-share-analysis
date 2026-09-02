# A-share-analysis：CR-3.6 最终复审结论与 CR-4 启动裁决

> **Review Date**：2026-09-02 21:05 +08:00  
> **Reviewed Repository HEAD**：`5970f082c0d5b50364b6d4ddf804559cd6ba8f33`  
> **Primary CR-3.6 Implementation**：`1ebe96b9d28617939c2782795395ef23eee597e0`  
> **Reviewer Baseline / Requirements**：`dd31ca62ebda3c0e2c634a43d867659ac725b6ca`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**VERIFIED / CLOSED / FREEZE**  
> **ADR-023**：**ACCEPTED**  
> **Next Stage**：**CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild — START / ACTIVE**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 最终裁决

本轮对 CR-3.6 的两个 P0 进行最终复核后，**未发现新的、在既定 correctness / tamper / replay threat model 内足以继续阻塞 CR-3 的 P0 blocker**。

因此正式裁决：

```text
CR-3                                  VERIFIED / CLOSED / FREEZE
CR-3.1                                VERIFIED / CLOSED / FREEZE
CR-3.2                                VERIFIED / CLOSED / FREEZE
CR-3.3                                VERIFIED / CLOSED / FREEZE
CR-3.4                                VERIFIED / CLOSED / FREEZE
CR-3.5                                VERIFIED / CLOSED / FREEZE
CR-3.6                                VERIFIED / CLOSED / FREEZE
ADR-023                               ACCEPTED
CR-4                                  START / ACTIVE
Production P0-M-1B                    BLOCKED independently
```

CR-3 全链从此进入 **FREEZE**：除非未来出现可复现 regression / correctness defect，否则不得为 CR-4、Feature、State 或性能便利重新打开 Canonical 语义、Provider 选择、PIT、identity、reconciliation、continuity、artifact seal 等已冻结规则。

---

# 1. CR-3.6 P0-01：Selection-Free Historical Discovery — VERIFIED / FREEZE

## 1.1 复核结论

当前 `_check_historical_continuity()` 已取消所有 verifier 前的 correctness-field 排他筛选：

```text
Phase A
SELECT full canonical ledger
ORDER BY canonical_run_id
(no WHERE correctness filter)
(no Python as_of/status/context pre-filter)

Phase B
_verify_historical_identity_seal(...)
  - deterministic manifest URI
  - manifest bytes == ledger manifest_hash
  - manifest correctness declarations == ledger
  - input seal physical recompute
  - derived context/base/idempotency/run-id physical recompute

Phase C
ONLY AFTER identity verification:
  - different request world -> skip safely
  - same request world -> artifact + finding/status verification
  - genuine BLOCKED -> recovery may proceed
  - SUCCESS -> upstream CR-2 continuity required
```

这满足 CR-3.6 的核心原则：

> **No correctness-bearing field may exclude a historical Canonical row before that row's identity seal is verified.**

历史行 identity 无法证明时采用 GLOBAL DAMAGED / fail-closed，而不是猜测该行“可能属于别的世界”后跳过；这是当前阶段正确的安全取舍。

## 1.2 对抗测试确认

新增 `TestSelectionFreeDiscovery` 覆盖：

- `requested_domains_hash` ledger-only drift；
- `canonical_contract_version` drift；
- availability policy version/hash drift；
- source policy version/hash drift；
- tolerance policy version/hash drift；
- `code_fingerprint` drift；
- `as_of` drift；
- primitive ledger + manifest pair rebind 试图伪造 different world；
- verified genuine different-world positive control。

上述路径均与 Reviewer 要求一致。

**裁决：PASS / FREEZE。**

---

# 2. CR-3.6 P0-02：Historical Canonical Artifact Closure — VERIFIED / FREEZE

## 2.1 复核结论

当前已抽取共享只读：

```text
_verify_canonical_artifacts(record, manifest)
```

并由两条路径共同消费：

```text
Exact Replay
  -> _verify_closure
  -> _verify_canonical_artifacts

Historical Continuity / Superset
  -> same-world historical row
  -> _verify_canonical_artifacts
```

共享 verifier 对 Canonical 自身 artifact 进行：

```text
artifact exact set = selected / decisions / findings
+ deterministic URI
+ physical content hash
+ row count
+ schema hash
+ selected_semantic_hash physical recompute
+ decision_set_hash physical recompute
```

findings 的 DB ↔ parquet ↔ finding_set_hash 以及 findings truth -> status/error semantic recompute 继续由共享 `_verify_findings_truth()` 负责。

因此一个 prior SUCCESS 即使 upstream CR-2 仍健康，只要它自己的 `selected.parquet` / `decisions.parquet` 已损坏，也不能通过“新增一个 CR-2 superset、产生新 run-id”的方式绕过历史证据损坏。

## 2.2 对抗测试确认

新增 `TestHistoricalArtifactClosure` 覆盖：

- selected bytes tamper；
- selected deletion；
- decisions bytes tamper；
- selected row-count rebind；
- selected schema-hash rebind；
- selected semantic seal ledger+manifest rebind；
- decisions semantic seal ledger+manifest rebind；
- untouched SUCCESS + legitimate CR-2 superset positive control；
- exact replay artifact tamper 继续由冻结回归矩阵覆盖。

**裁决：PASS / FREEZE。**

---

# 3. CR-3 全链最终冻结清单

以下能力自本裁决起视为 Canonical Runtime V1 已完成的 correctness contract：

```text
1. Provider-Normalized -> Canonical 唯一正式边界
2. 仅消费 CR-2 ledger / sealed artifacts；无 SDK / Provider 直连
3. typed AvailabilityPolicy；availability before source selection
4. RequestedDomainSet 进入 identity；None / empty 语义明确
5. static SourcePolicy；无 caller correctness knobs
6. exact source conflict；无 silent fallback / last-write-wins
7. PIT market data
8. PIT identity master
9. raw received_at exact bytes + raw anchor cross-bind
10. IdentityBridge；无 code-prefix exchange guessing
11. Transactional Canonical Input Snapshot
12. exact-byte materialization inside DB snapshot
13. deeply immutable typed snapshot records
14. honest policy execution / unsupported values fail closed
15. deterministic selected / decisions / findings
16. selected / decision / finding semantic seals
17. artifact exact set + deterministic URI + physical closure
18. findings parquet ↔ DB exact-set cross-bind
19. manifest correctness fields full consume
20. input full typed seal
21. verification_problem_hash exact cause identity
22. first consume / replay verification evidence symmetry
23. BLOCKED -> repair recovery；旧 evidence append-only
24. prior SUCCESS degradation -> DAMAGED / zero replacement
25. historical CR-2 input continuity
26. historical Canonical full identity seal
27. derived context/base/idempotency/run-id physical recompute
28. status/error = exact sealed findings truth function
29. selection-free historical discovery
30. different-world classification only after identity verification
31. historical selected/decisions artifact closure
32. genuine BLOCKED may recover only after its recorded evidence is internally intact
```

任何 CR-4 实现不得复制、弱化或旁路这些规则。

---

# 4. Verification / CI

CR-3.6 implementation：`1ebe96b9d28617939c2782795395ef23eee597e0`。

验证结果：

```text
1179 tests passed / 0 failed
1151 -> 1179 (+28 adversarial)
CR-3..CR-3.5 frozen regression matrix: 166 tests retained green
no new migration; chain remains through 021
```

GitHub Actions implementation run：`33623939024`，已确认：

```text
Windows py3.12   SUCCESS
Windows py3.14   SUCCESS
Ubuntu  py3.14   SUCCESS
Ruff lint        SUCCESS
Ruff format      SUCCESS
Mypy             SUCCESS
Pytest           SUCCESS
Spike gates      SUCCESS
SDK absent       SUCCESS
Governance gates SUCCESS where applicable
```

Docs backfill HEAD：`5970f082c0d5b50364b6d4ddf804559cd6ba8f33`。

---

# 5. ADR-023 最终裁决

**ADR-023 AvailabilityPolicy + Canonical Source Selection：ACCEPTED。**

接受范围包括 Amendment A / B / C / D / E / F 形成的最终语义；历史过程中被后续 Amendment 修正的旧表述，以最后 Amendment 和 Reviewer closure 为准。

CR-4 第一笔开发提交必须同步：

```text
ADR-000 index: ADR-023 -> ACCEPTED / VERIFIED 2026-09-02
ADR-023 header/status -> ACCEPTED
DEVLOG: append CR-3 full-chain closure entry
DEVELOPMENT_MANAGEMENT:
  - Current Code Baseline -> CR-3.6 closure reviewer baseline
  - CR-3..3.6 -> VERIFIED/CLOSED/FREEZE
  - ADR-023 -> ACCEPTED
  - CR-4 -> START/ACTIVE
CR-3.6 work requirement Implementation Mapping:
  - Reviewer verdict -> VERIFIED / CLOSED / FREEZE
```

历史 DEVLOG 仍 append-only，不得回写覆盖旧结论。

---

# 6. CR-4 正式启动

CR-4 名称：

> **SnapshotBuilder + DuckDB ReadModel Rebuild**

CR-4 的独立开发工作要求见同日 Reviewer 文档：

`docs/design/A-share-analysis_CR-4_SnapshotBuilder及DuckDBReadModel开发工作要求_20260902.md`

CR-4 的核心定位不是继续修改 Canonical，而是：

```text
Verified Canonical SUCCESS
        ↓
Deterministic Snapshot
        ↓
Rebuildable DuckDB ReadModel
        ↓
future Feature / State consumers
```

CR-4 不得进入 Feature / State 计算，也不得启动 production account / live trading 相关工作。

---

# 7. Owner View

```text
A股市场态势数据基座
│
├─ Raw Evidence                              ✅ CLOSED / FREEZE
├─ Provider Capability                       ✅ CLOSED / FREEZE
├─ Publish Safety                            ✅ CLOSED / FREEZE
├─ Provider Normalization + Quarantine       ✅ CR-2 CLOSED / FREEZE
├─ Canonical Runtime                         ✅ CR-3 全链 CLOSED / FREEZE
│   ├─ PIT / identity / policy               ✅
│   ├─ transactional exact-byte snapshot     ✅
│   ├─ replay / repair / continuity          ✅
│   ├─ derived run/status seals              ✅
│   ├─ selection-free historical discovery   ✅
│   └─ historical artifact closure           ✅
│
├─ SnapshotBuilder + DuckDB ReadModel        🔧 CR-4 START
├─ Feature                                   ⏸ NOT STARTED
├─ State                                     ⏸ NOT STARTED
└─ Production                                ⛔ P0-M-1B independently blocked
```

**Reviewer final decision：CR-3 正式结束。后续工程注意力转入 CR-4，不再继续在 Canonical 层无边界扩张。**
