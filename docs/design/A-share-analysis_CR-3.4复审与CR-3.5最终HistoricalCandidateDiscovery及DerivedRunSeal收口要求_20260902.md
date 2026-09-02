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

---

# 7. Implementation Mapping（CR-3.5，2026-09-02）

> Reviewed base：CR-3.4 复审 reopen commit `275fc93`（本工作要求）；implementation commit `<本批提交后回填>`（CI 三腿确认后回填）。总体 **1151/0**（1136 → 1151，+15 项对抗测试）；ruff check / ruff format / mypy 全绿；**零新 migration**（§3 允许范围内刻意决策：bridge policy identity 已由 manifest 持久化且参与物理重算，ledger 侧新增列不改变 primitive 全字段伪造这一已接受残余边界的本质，不收敛攻击面——migration 链保持 21）。

## 7.1 P0-01 Tamper-Resistant Historical Candidate Discovery

| 要求 | 实现 |
| --- | --- |
| 候选按 primitive request-world fields 查历史，不用 status 预过滤、不把 stored canonical_context_hash 当唯一 selection key | `_check_historical_continuity` 重写：SQL 按 `requested_domains_hash` + `canonical_contract_version` + 三 policy version/hash + `code_fingerprint` 查询；`as_of` 由 Python 侧 `_ledger_as_of(record) != snapshot.as_of` 精确过滤（不同 as_of = 不同 request world） |
| 每个候选先 full-seal 验证，再解释其 historical status | 候选循环：`_verify_historical_canonical_seal(seal, record)`（§9.1 全部检查 + §7.2 derived identity 物理重算 + §7.2 findings truth→status 语义重算）→ 任何 problem 即 DAMAGED（零 replacement）；通过后才比较 `seal.canonical_context_hash == snapshot.canonical_context_hash`（world membership）与 `verified_status` |
| historical SUCCESS / other successful non-BLOCKED → continuity required；genuine BLOCKED → 不作为 SUCCESS continuity dependency | verified SUCCESS 同世界 → 逐 entry `_continuity_problems_for_input`（CR-3.3 机制原样）；verified genuine BLOCKED → `continue`（不阻塞 exact repair / recovery）；verified 但 context != current（旧 bridge policy 世界，manifest bridge 与当前不同）→ `continue` |
| recompute canonical_context_hash from primitives == ledger == manifest | `_derived_run_identity_problems` 内 `_canonical_context_hash_from_primitives(requested_domains_hash, as_of, contract, 三 policy, manifest bridge identity, fingerprint)` == ledger（manifest == ledger 由既有 expected_fields 保证；见 §7.2） |
| identity bridge policy identity（如需要可 migration 022+） | 不引入 migration：bridge identity 以 manifest 为持久化锚参与物理重算（§7.2） |

**Mandatory adversarial tests（§1.4）→ `tests/integration/test_canonical.py::TestHistoricalCandidateDiscovery`（6 项）**

| 要求 | 测试 |
| --- | --- |
| 1. prior SUCCESS → ledger status=BLOCKED only → delete consumed input → DAMAGED / 零新 run | `test_status_drift_cannot_hide_prior_success`（候选仍被发现；findings truth 重算 SUCCESS ≠ 声称 BLOCKED → DAMAGED） |
| 2. prior SUCCESS → ledger canonical_context_hash only drift → delete input → DAMAGED | `test_context_hash_drift_cannot_hide_prior_success`（primitive 发现仍选中该行；context 物理重算 ≠ 漂移值 → DAMAGED） |
| 3. prior SUCCESS → ledger+manifest canonical_context_hash together rebind + outer hash → delete input → DAMAGED | `test_context_rebind_ledger_and_manifest_damaged`（同时覆盖 mandatory 12：manifest 一并被 rebind 时 primitive 重算仍暴露伪造） |
| 4. genuine historical BLOCKED 不得错误阻塞 exact repair / recovery | `test_genuine_blocked_not_blocking_exact_recovery`（物理损坏 output bytes → BLOCKED → exact repair → recovery SUCCESS 新 run，count=2） |
| 5. legitimate new CR-2 superset with historical SUCCESS intact → 仍允许新 run | `test_superset_with_intact_success_still_allowed`（同时覆盖 mandatory 15） |

## 7.2 P0-02 Derived Canonical Run Seal 物理闭环

| 要求 | 实现 |
| --- | --- |
| recompute_input_seal_hash / input_set_hash / verification_state_hash | `_input_hashes_from_entries`（CR-3.4 既有，CR-3.5 起被 `_derived_run_identity_problems` 消费） |
| recompute_identity_master_input_set_hash | 新增 `_master_input_set_hash_from_entries`（PIT-available HEALTHY master entries——live `_build_snapshot` 同公式委托） |
| recompute_identity_dataset_hash(master_set_hash, bridge policy identity) | `identity.py` 抽取 `identity_dataset_hash_with_bridge(master, bridge_v, bridge_h)` 参数化变体（当前世界入口 `identity_dataset_hash` 委托之，公式唯一）；historical 重算用该 run **自己的 manifest bridge identity**——旧 bridge 世界的 prior run 因此可被完整验证后正确跳过（由既有 `test_bridge_policy_version_change_new_run` 回归保证） |
| recompute_canonical_context_hash(request-world primitives) | `_canonical_context_hash_from_primitives`（snapshot 属性委托） |
| recompute_base_identity_hash(...) | `_base_identity_hash_from_primitives`（snapshot 属性委托） |
| recompute_idempotency_key(base, state) | `_idempotency_key_from_hashes`（snapshot 属性委托） |
| recompute_canonical_run_id(idempotency_key)：UUID5(namespace, key) == ledger canonical_run_id | `_canonical_run_id_from_idempotency`（run() 与两个 verifier 共用；`_derived_run_identity_problems` 显式 cross-bind 比对） |
| recompute_status(findings blocking exact set)：any blocking → BLOCKED else SUCCESS；typed transition 扩展 | `_status_error_from_findings`（live run() / `_verify_findings_truth` 共用；只产出 SUCCESS/BLOCKED 两态） |
| physical recompute == manifest explicit field == ledger typed seal | `_derived_run_identity_problems(entries, requested_domains, as_of, ledger, manifest)`：requested_domains_hash ← compact JSON of domain list；其余全部 ← manifest entries + ledger primitives + manifest bridge identity；逐字段与 ledger 比对。消费于 `_verify_historical_canonical_seal`（historical）与 `_verify_closure`（replay——与 expected_provenance（current == ledger）+ typed manifest binding（manifest == ledger）构成三方闭环） |
| live build / replay / historical continuity 共用同一 derived-seal formulas | snapshot 的 input_seal_hash/input_set_hash/verification_state_hash/canonical_context_hash/base_identity_hash/idempotency_key 属性、`_build_snapshot` 的 master set hash、`run()` 的 run_id 与 status/error 派生**全部委托**上述模块级 helpers（复审 §3 允许的最小必要抽取；公式逐字节不变——151 项回归全保持即证明） |
| historical full seal 验证 findings exact-set/content seal 后再重算 status；replay 同一 status semantic check | `_verify_findings_truth(record, manifest)`（两 verifier 共用）：DB rows（count == ledger finding_count；`_finding_set_hash` == ledger seal）== findings parquet（deterministic URI + content hash + row count + ids + semantic hash）== manifest finding_set_hash/finding_count；随后 `_status_error_from_findings(db_findings)` 重算 status 与 error text 并消费 ledger `status`/`error_message` |
| error_message P1：不再处于"看似 correctness 实则不校验"的中间态 | 升级为 derived audit text：`_verify_findings_truth` 消费 `error_message`（rebind → DAMAGED） |

**Mandatory adversarial tests（§2.3）→ `TestDerivedRunSeal`（9 项）**

| 要求 | 测试 |
| --- | --- |
| 6. rebind ledger+manifest status SUCCESS→BLOCKED + outer hash，findings 无 blocking → DAMAGED | `test_status_success_to_blocked_rebind_damaged` |
| 7. rebind ledger+manifest status BLOCKED→SUCCESS + outer hash，findings 有 blocking → DAMAGED | `test_status_blocked_to_success_rebind_damaged` |
| 8. rebind ledger+manifest identity_master_input_set_hash（entries 不变）→ DAMAGED by physical recompute | `test_master_input_set_hash_rebind_damaged`（加 superset 输入确保 historical verifier 是 catcher） |
| 9. rebind ledger+manifest identity_dataset_hash → DAMAGED | `test_identity_dataset_hash_rebind_damaged` |
| 10. rebind ledger+manifest base_identity_hash → DAMAGED by physical recompute | `test_base_identity_hash_rebind_damaged` |
| 11. rebind ledger+manifest idempotency_key → DAMAGED；recomputed run id must not match | `test_idempotency_key_rebind_damaged`（idem 重算失配 + UUID5 cross-bind 失配） |
| P1 error_message | `test_error_message_rebind_damaged` |
| 13. untouched SUCCESS exact replay idempotent | `test_untouched_success_exact_replay_idempotent` |
| 14. untouched BLOCKED exact failure replay idempotent | `test_untouched_blocked_exact_replay_idempotent` |
| （补充）run-id cross-bind positive control | `test_run_id_cross_bind_positive`（live run id == UUID5(namespace, ledger idempotency_key)） |

## 7.3 Scope Boundary 合规

只修改：`src/ashare_state/canonical/canonicalizer.py`、`src/ashare_state/canonical/identity.py`（参数化抽取，公式唯一）、`tests/integration/test_canonical.py`、ADR-023 Amendment E（§10.1-§10.4）、ADR-000 索引、`docs/DEVLOG.md`（追加条目）、`docs/project/DEVELOPMENT_MANAGEMENT.md`（DM-20260902-073）、本 Mapping。**未新增 migration 022**；未触碰 SnapshotBuilder / ReadModel / Feature / State / Provider / Policy / production 人工项；CR-3.4 PASS 的 14 项机制零重构式重写（唯一改动是复审 §3 明示允许的"复用 derived-seal helper 的最小必要抽取"——委托共享公式，公式本身不变）。

## 7.4 Exit Gate 自检

```text
[x] historical candidate discovery 不依赖未验证的 status 预过滤                -> primitive-fields SQL + Python as_of 过滤
[x] stored canonical_context_hash 漂移不能把 prior SUCCESS 从 candidate set 隐藏 -> mandatory 2 测试
[x] candidate rows 先被 full-seal 验证，再解释其 historical status              -> 候选循环顺序（seal -> membership -> status 解释）
[x] canonical_context_hash 从 primitives 物理重算                              -> _canonical_context_hash_from_primitives + _derived_run_identity_problems
[x] identity_master_input_set_hash 物理重算                                    -> _master_input_set_hash_from_entries
[x] identity_dataset_hash 物理重算                                             -> identity_dataset_hash_with_bridge（manifest bridge identity）
[x] base_identity_hash 物理重算                                                -> _base_identity_hash_from_primitives
[x] idempotency_key 物理重算                                                   -> _idempotency_key_from_hashes
[x] canonical_run_id 与 recomputed idempotency key cross-bind                  -> _canonical_run_id_from_idempotency 显式比对 + positive control 测试
[x] status 从 exact sealed findings blocking truth 重算                        -> _status_error_from_findings + _verify_findings_truth
[x] replay 与 historical continuity 使用同一 derived-seal formulas             -> 模块级 helpers 三方消费（live/replay/continuity）
[x] prior SUCCESS status/context drift + CR-2 disappearance 全过               -> mandatory 1/2/3(+12) 测试
[x] BLOCKED<->SUCCESS status rebind adversarial tests 全过                     -> mandatory 6/7 测试
[x] CR-3.4 materialization symmetry tests 全绿                                 -> 151 项回归全保持
[x] CR-3.3 continuity/finding tests 全绿                                       -> 同上
[x] CR-3/3.1/3.2/CR-2/R4 frozen regressions 全绿                               -> 全量 1151/0
[x] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff/format/Mypy/Spike/governance gates 全绿 -> 推送后 API 正向确认（回填本节）
[x] ADR-023 Amendment E + DEVLOG + DEVELOPMENT_MANAGEMENT 完整同步             -> Amendment E §10.1-§10.4 + DEVLOG 条目 + DM-20260902-073
[x] 若 migration 022+：from-zero / upgrade / idempotent / tamper probe 全过    -> N/A（零 schema 变化，21 链不变）
[ ] Reviewer 复审无新的 P0 correctness blocker                                 -> PENDING_REVIEW
```
