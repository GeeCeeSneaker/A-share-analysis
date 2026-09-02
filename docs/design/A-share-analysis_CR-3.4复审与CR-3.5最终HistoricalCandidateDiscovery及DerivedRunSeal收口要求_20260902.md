# A-share-analysis：CR-3.4 复审与 CR-3.5 最终 Historical Candidate Discovery / Derived Canonical Run Seal 收口要求

> **Review Date**：2026-09-02 13:17 +08:00  
> **Reviewed Repository HEAD**：`8585b08dc079207e8306bf3be38cf3de3de2f7a4`  
> **Primary CR-3.4 Implementation**：`fce2ca43a35b95d61dc390647fdc46d844d9b1a5`  
> **Reviewer Baseline / Requirements**：`33d09013c8f2eddaa96d8dcc80cdf676612eaf21`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-3.4 原定 3 个 P0**：**PASS / FREEZE（主体成立）**  
> **Next Batch**：**CR-3.5 Final Historical Candidate Discovery + Derived Canonical Run/Status Seal Closure**  
> **ADR-023**：**PROPOSED / NOT ACCEPTED**  
> **CR-4**：**BLOCKED_BY_CR-3.5**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-3.4 对上一轮 3 个 P0 做了实质修复。以下机制本轮正式 **PASS / FREEZE**，CR-3.5 不得推倒重写：

```text
PASS / FREEZE  CanonicalRunSeal typed historical canonical seal
PASS / FREEZE  continuity 在信任 prior input_normalized_runs 前先验证 historical manifest URI/hash
PASS / FREEZE  historical manifest input entries 物理重算 input_seal_hash
PASS / FREEZE  historical manifest input entries 物理重算 input_set_hash
PASS / FREEZE  historical manifest input entries 物理重算 verification_state_hash
PASS / FREEZE  _INPUT_IDENTITY_FIELDS 作为 live/historical input_set_hash 单一字段真相
PASS / FREEZE  first consume / replay 共用 _collect_input_verification_evidence
PASS / FREEZE  materialization-only failure 可 sealed + exact replay
PASS / FREEZE  materialization cause change -> new BLOCKED evidence run
PASS / FREEZE  materialization exact repair -> recovery SUCCESS，旧 BLOCKED append-only
PASS / FREEZE  manifest canonical_context_hash / base_identity_hash / verification_state_hash replay full-consume
PASS / FREEZE  CR-3.3 historical input continuity / finding truthfulness 主体无 regression
PASS / FREEZE  no new migration；018/019/020/021 untouched
PASS / FREEZE  implementation 1136 tests baseline；CI run 33591527697 success
```

CR-3.4 implementation `fce2ca43...` 的 GitHub Actions run `33591527697` 已确认 success。原 CR-3.4 需求的三项修复方向均成立。

但是继续审查“Historical Canonical Seal 在**被选中之前**是否已经不可绕过”以及“Canonical run 的 derived identity/status 是否真的由物理证据重算”后，发现 **2 个新的 P0 correctness blockers**：

1. **historical continuity candidate discovery 仍在 seal verification 之前依赖可漂移的 `canonical_context_hash` 与 `status` 字段，历史 SUCCESS 可以在进入 verifier 之前被隐藏；**
2. **CanonicalRunSeal 目前主要做 ledger == manifest + 三个 input hash 重算，但没有把 context/base/idempotency/run-id/identity-master/status 等 derived truth 全部从 primitive seal / findings 物理推导回来；尤其 status 可被 ledger+manifest 同时重绑。**

正式状态：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4      VERIFIED / CLOSED / FREEZE
CR-3                                 DONE / REOPENED
CR-3.1                               DONE / REOPENED（已吸收）
CR-3.2                               DONE / REOPENED（已吸收）
CR-3.3                               DONE / REOPENED（已吸收）
CR-3.4                               DONE / REOPENED（原定 3 P0 PASS/FREEZE）
CR-3.5                               START / ACTIVE NEXT
ADR-023                              PROPOSED
CR-4                                 BLOCKED_BY_CR-3.5
Production P0-M-1B                   BLOCKED independently
```

---

# 1. P0-01：Historical candidate discovery 在 seal verification 前仍依赖可漂移字段

## 1.1 当前实现

当前 `_check_historical_continuity(snapshot)` 的 discovery SQL：

```sql
SELECT ...
FROM meta_canonicalization_run
WHERE canonical_context_hash = ?
  AND status != 'BLOCKED'
ORDER BY canonical_run_id
```

之后才：

```text
CanonicalRunSeal.from_ledger(record)
 -> _verify_historical_canonical_seal(seal)
 -> trust manifest.input_normalized_runs
```

因此 CR-3.4 强化的是“**已经被选中的 prior run 怎么验**”，但 prior run 是否有资格进入 verifier，仍由两个未先验证的字段决定：

```text
canonical_context_hash
status
```

## 1.2 直接绕过路径 A：status drift

```text
C1 historical SUCCESS consumed CR-2 A

1. UPDATE meta_canonicalization_run
   SET status = 'BLOCKED'
   WHERE canonical_run_id = C1

2. DELETE / damage CR-2 A

3. invoke the same requested domains + as_of + policy/code world
```

当前 SQL 在 historical seal verification 前就执行：

```text
status != BLOCKED
```

所以 C1 完全不会进入 `CanonicalRunSeal` verifier。

这与 CR-3.3/3.4 的核心 invariant 冲突：

> prior SUCCESS 一旦存在，它的 sealed dependency continuity 必须永远可被发现；不能靠修改一个 canonical ledger status 字段把这段历史从 guard 的候选集中隐藏。

## 1.3 直接绕过路径 B：canonical_context_hash drift

```text
C1 historical SUCCESS under request world W

1. UPDATE meta_canonicalization_run
   SET canonical_context_hash = H_fake
   WHERE canonical_run_id = C1

2. DELETE / damage one CR-2 input consumed by C1

3. invoke W again
```

当前 continuity 只查：

```text
canonical_context_hash = snapshot.canonical_context_hash
```

C1 同样在进入 historical seal verifier 前消失。

因此仅仅“manifest.context == ledger.context”不够；如果 ledger context 本身就是 candidate selection key，那么它必须先由更原子的 request-world fields 被重新推导，或者 candidate discovery 根本不能只依赖这个派生字段。

## 1.4 Required Closure

必须建立 **tamper-resistant historical candidate discovery**。核心规则：

> **先找到所有可能属于同一 request world 的历史 canonical rows，再验证 derived context/status；不能先用 derived context/status 把需要验证的历史行过滤掉。**

推荐方案（字段名可调整）：

```text
HistoricalRequestWorldKey primitives:
- requested_domains_json/hash
- as_of
- canonical_contract_version
- availability_policy_version/hash
- source_policy_version/hash
- tolerance_policy_version/hash
- canonical code_fingerprint
- identity bridge policy identity（如需要可 migration 022+ 显式持久化；不得修改 018..021）
```

Continuity candidate discovery 应按 primitive request-world fields 查历史，不用 `status` 预过滤，不把 stored `canonical_context_hash` 当唯一 selection key。

随后对每个候选：

```text
recompute canonical_context_hash from primitives
== ledger canonical_context_hash
== manifest canonical_context_hash
```

再验证 full CanonicalRunSeal，最后才根据**已验证、已物理推导**的 historical status 决定：

```text
historical SUCCESS / other successful non-BLOCKED -> continuity required
historical genuine BLOCKED -> 不作为 SUCCESS continuity dependency
```

### Mandatory adversarial tests

1. prior SUCCESS -> ledger `status=BLOCKED` only -> delete consumed CR-2 input -> same request world MUST DAMAGED，zero replacement。
2. prior SUCCESS -> ledger `canonical_context_hash` only drift -> delete consumed CR-2 input -> MUST DAMAGED。
3. prior SUCCESS -> ledger+manifest `canonical_context_hash` together rebind + outer manifest_hash -> delete consumed input -> MUST DAMAGED。
4. genuine historical BLOCKED（seal/status semantics valid）不得错误阻塞其后 exact repair / recovery（positive control）。
5. legitimate new CR-2 superset with historical SUCCESS fully intact remains allowed（positive control）。

---

# 2. P0-02：CanonicalRunSeal 还没有完成 derived run identity / status 的物理闭环

## 2.1 当前已完成

CR-3.4 已能从 historical manifest input entries 重算：

```text
input_seal_hash
input_set_hash
verification_state_hash
```

并检查 manifest explicit fields == ledger。

这解决了“删 input entry + 只更新 outer manifest_hash”的上一轮攻击。

## 2.2 仍未物理推导的 correctness truth

当前 `CanonicalRunSeal` 对以下字段主要是：

```text
ledger value == manifest value
```

但还没有全部从更原子的 seal truth 重算：

```text
canonical_context_hash
identity_master_input_set_hash
identity_dataset_hash
base_identity_hash
idempotency_key
canonical_run_id
status
```

其中前五类是 canonical run identity 的派生值；`status` 是 findings 的派生业务真值。

### status 是当前最直接的 correctness gap

当前 run 生成时：

```text
blocking findings exist -> BLOCKED
otherwise -> SUCCESS
```

但 replay / historical full seal 目前主要检查：

```text
manifest.status == ledger.status
```

没有把 status 从 sealed findings 的 `blocking` 集合物理重算。

因此存在：

```text
historical SUCCESS
 -> UPDATE ledger.status = BLOCKED
 -> UPDATE manifest.status = BLOCKED
 -> rehash manifest + UPDATE ledger.manifest_hash
```

若没有 status semantic recompute，这个原 SUCCESS 可以被“洗成 genuine BLOCKED”。结合 P0-01 的 status prefilter，会直接隐藏 continuity dependency。

反向也成立：

```text
historical BLOCKED (blocking findings exist)
 -> ledger+manifest status = SUCCESS
```

如果 replay 只做字段相等而不从 findings truth 重算，就可能把一个有 blocking finding 的历史 run 当成 SUCCESS。

## 2.3 Required Closure：Derived Canonical Run Seal

建立单一 canonical derivation helpers（名称不限），live build / replay / historical continuity 共用：

```text
recompute_input_seal_hash(entries)
recompute_input_set_hash(entries)
recompute_verification_state_hash(entries)
recompute_identity_master_input_set_hash(entries)
recompute_identity_dataset_hash(master_set_hash, bridge policy identity)
recompute_canonical_context_hash(request-world primitives)
recompute_base_identity_hash(...)
recompute_idempotency_key(base_identity_hash, verification_state_hash)
recompute_canonical_run_id(idempotency_key)
recompute_status(findings blocking exact set)
```

要求：

```text
physical recompute
== manifest explicit field
== ledger typed seal
```

`canonical_run_id` 若数据库主键本身无法安全更新，至少必须验证：

```text
UUID5(namespace, recomputed idempotency_key) == ledger canonical_run_id
```

### identity master derived seal

`identity_master_input_set_hash` 当前 live 公式由 PIT-available HEALTHY master seals 派生。historical verifier 应从 manifest input entries 按同一公式重算，而不是只信 ledger/manifest 相等。

随后：

```text
identity_dataset_hash
= identity_dataset_hash(recomputed master set + bridge policy identity)
```

同样三方验证。

### status semantic seal

至少：

```text
any sealed finding.blocking == true -> expected status BLOCKED
otherwise -> expected status SUCCESS
```

如果未来新增 status，必须由明确 typed transition 规则扩展，不允许自由字符串。

historical full seal 应验证 findings 的 exact-set/content seal 后再重算 status；replay verifier 也必须执行相同 status semantic check。

`error_message` 建议同步做 P1：要么定义为非 correctness audit text；要么建立 deterministic derived/error seal。当前不要让它处于“看起来像 correctness、实际上不校验”的中间状态。

### Mandatory adversarial tests

6. rebind ledger+manifest `status SUCCESS -> BLOCKED` + outer hash，findings 无 blocking -> DAMAGED。
7. rebind ledger+manifest `status BLOCKED -> SUCCESS` + outer hash，findings 有 blocking -> DAMAGED。
8. rebind ledger+manifest `identity_master_input_set_hash` together while input entries unchanged -> DAMAGED by physical recompute。
9. rebind ledger+manifest `identity_dataset_hash` together -> DAMAGED。
10. rebind ledger+manifest `base_identity_hash` together -> DAMAGED by physical recompute。
11. rebind ledger+manifest `idempotency_key` together -> DAMAGED；recomputed run id must not match。
12. stored `canonical_context_hash` drift detected by primitive recompute even when manifest is rebound too。
13. untouched SUCCESS exact replay remains idempotent。
14. untouched BLOCKED exact failure replay remains idempotent。
15. legitimate superset world still produces new run。

---

# 3. CR-3.5 Allowed Scope

允许：

- `src/ashare_state/canonical/canonicalizer.py`
- canonical run seal / identity derivation helpers
- historical candidate discovery query
- findings->status semantic verification
- tests
- ADR-023 Amendment E
- DEVLOG / DEVELOPMENT_MANAGEMENT sync
- migration 022+ **仅在确需持久化额外 primitive request-world field 时**

禁止：

- SnapshotBuilder
- DuckDB ReadModel
- Feature / State
- 新 provider
- fallback / new reconciliation policy
- 新 canonical domain semantics
- 重写 CR-2.x frozen semantics
- production account / Trading Rule 扩展

CR-3.4 已 PASS 的机制禁止重构式重写，除非为了复用 derived-seal helper 做最小必要抽取。

---

# 4. CR-3.5 Exit Gate

全部满足才允许：

```text
CR-3 / CR-3.1 / CR-3.2 / CR-3.3 / CR-3.4 / CR-3.5
-> VERIFIED / CLOSED / FREEZE

ADR-023 -> ACCEPTED
CR-4 SnapshotBuilder + DuckDB ReadModel -> START
```

Exit Gate：

1. historical candidate discovery 不依赖未经验证的 `status` 预过滤；
2. stored canonical_context_hash 漂移不能把 prior SUCCESS 从 candidate set 隐藏；
3. candidate rows 先被 full-seal 验证，再解释其 historical status；
4. canonical_context_hash 从 primitives 物理重算；
5. identity_master_input_set_hash 物理重算；
6. identity_dataset_hash 物理重算；
7. base_identity_hash 物理重算；
8. idempotency_key 物理重算；
9. canonical_run_id 与 recomputed idempotency key cross-bind；
10. status 从 exact sealed findings blocking truth 重算；
11. replay 与 historical continuity 使用同一 derived-seal formulas；
12. prior SUCCESS status/context drift + CR-2 disappearance adversarial tests 全过；
13. BLOCKED<->SUCCESS status rebind adversarial tests 全过；
14. CR-3.4 materialization symmetry tests 全绿；
15. CR-3.3 continuity/finding tests 全绿；
16. CR-3/3.1/3.2/CR-2/R4 frozen regressions 全绿；
17. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff/format/Mypy/Spike/governance gates 全绿；
18. ADR-023 Amendment E + DEVLOG + DEVELOPMENT_MANAGEMENT 完整同步；
19. 若 migration 022+：from-zero / 021->022 / idempotent / tamper probe 全过；
20. Reviewer 复审无新的 P0 correctness blocker。

---

# 5. Governance / Handoff

本 Reviewer commit 是下一开发批次唯一有效增量要求。下一开发 commit 必须同步：

- `docs/DEVLOG.md`（append-only；不得改写历史 CR-3.4 entry；如需纠正 CR-3.4 “full seal”描述，追加 correction）；
- `docs/project/DEVELOPMENT_MANAGEMENT.md`；
- `docs/adr/ADR-023_availability_policy_canonical_selection.md`（Amendment E）；
- 本文 Implementation Mapping；
- CI run / implementation SHA 回填。

**不得启动 CR-4，直到 Reviewer 明确把 CR-3 全链 CLOSED / FREEZE。**
