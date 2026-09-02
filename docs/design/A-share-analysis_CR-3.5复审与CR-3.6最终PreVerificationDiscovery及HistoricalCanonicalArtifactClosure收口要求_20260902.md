# A-share-analysis：CR-3.5 复审与 CR-3.6 最终 Pre-Verification Discovery / Historical Canonical Artifact Closure 收口要求

> **Review Date**：2026-09-02 17:36 +08:00  
> **Reviewed Repository HEAD**：`3c6087e13de4af26143aa72a2a8bbeade052ecdb`  
> **Primary CR-3.5 Implementation**：`48982290056cf88e6daafbecb7d8b8a766da6e28`  
> **Reviewer Baseline / Requirements**：`275fc9348efaa1ecb0a7129108d933b90f54bbb2`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-3.5 Derived Run / Status Seal**：**PASS / FREEZE**  
> **Next Batch**：**CR-3.6 Final Selection-Free Historical Discovery + Historical Canonical Artifact Closure**  
> **ADR-023**：**PROPOSED / NOT ACCEPTED**  
> **CR-4**：**BLOCKED_BY_CR-3.6**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-3.5 对上一轮两个 P0 做了实质修复，其中 **Derived Canonical Run / Status Seal 物理闭环已经成立**。以下机制本轮正式 **PASS / FREEZE**，CR-3.6 不得推倒重写：

```text
PASS / FREEZE  status 不再作为 historical SQL pre-filter
PASS / FREEZE  stored canonical_context_hash 不再作为 historical SQL selection key
PASS / FREEZE  CanonicalInputSnapshot live build 使用共享 derived formulas
PASS / FREEZE  requested_domains_hash 从 requested domain list 物理重算
PASS / FREEZE  input_seal_hash / input_set_hash / verification_state_hash 物理重算
PASS / FREEZE  identity_master_input_set_hash 从 sealed master entries 物理重算
PASS / FREEZE  identity_dataset_hash 使用该 run 自己封存的 bridge policy identity 重算
PASS / FREEZE  canonical_context_hash 从 request-world primitives + sealed bridge policy 重算
PASS / FREEZE  base_identity_hash 物理重算
PASS / FREEZE  idempotency_key = H(base + verification state) 物理重算
PASS / FREEZE  canonical_run_id = UUID5(namespace, idempotency_key) cross-bind
PASS / FREEZE  status = function(exact sealed findings blocking truth)
PASS / FREEZE  error_message = function(exact sealed findings truth)
PASS / FREEZE  findings DB == parquet == finding_set_hash semantic seal
PASS / FREEZE  first consume / replay materialization evidence symmetry（CR-3.4）
PASS / FREEZE  historical input list / CR-2 continuity 主体（CR-3.3/3.4）
PASS / FREEZE  genuine historical BLOCKED 可在 full seal 验证后允许 recovery
PASS / FREEZE  old bridge-policy world 在 full derived identity 验证后可正确跳过
PASS / FREEZE  no new migration；018/019/020/021 untouched
PASS / FREEZE  implementation 1151/0；implementation run 33601822767 success
PASS / FREEZE  docs HEAD 3c6087e CI run 33602594114 三腿 success
```

当前 HEAD GitHub Actions run `33602594114`：Windows 3.12 / Windows 3.14 / Ubuntu 3.14 全 success，Ruff / Format / Mypy / Pytest / Spike / SDK-absent / governance gates 均通过。

但继续按 CR-3.3～CR-3.5 已经确立的 invariant：

> **prior SUCCESS 一旦存在，不能通过损坏/漂移历史证据后让系统“看不见它”，也不能在历史 Canonical 自身 correctness artifact 已损坏时静默 mint replacement/new world。**

本轮仍发现 **2 个 P0 correctness blockers**：

1. **Historical candidate discovery 虽不再依赖 status/context，但仍在 full-seal verification 之前依赖其它可漂移 correctness-bearing fields（requested_domains_hash / contract / policy identities / code_fingerprint / as_of）做 SQL/Python filtering；只漂移其中一个字段即可把 prior SUCCESS 从 verifier 前隐藏。**
2. **Historical Canonical seal 在非 exact-replay 的 continuity/superset 路径尚未验证 prior SUCCESS 的 selected / decisions artifact closure；旧 Canonical 产物损坏后仍可能放行新 superset run。**

正式状态：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4      VERIFIED / CLOSED / FREEZE
CR-3                                 DONE / REOPENED
CR-3.1                               DONE / REOPENED（已吸收）
CR-3.2                               DONE / REOPENED（已吸收）
CR-3.3                               DONE / REOPENED（已吸收）
CR-3.4                               DONE / REOPENED（已吸收，原定 3 P0 PASS/FREEZE）
CR-3.5                               DONE / REOPENED（derived seal PASS/FREEZE）
CR-3.6                               START / ACTIVE NEXT
ADR-023                              PROPOSED
CR-4                                 BLOCKED_BY_CR-3.6
Production P0-M-1B                   BLOCKED independently
```

---

# 1. P0-01：Candidate Discovery 仍然在 verifier 之前信任可漂移 correctness fields

## 1.1 当前实现已经修对的部分

CR-3.5 已删除上一轮两个最直接的 pre-filter：

```text
status != 'BLOCKED'
canonical_context_hash = current_context
```

并改为按所谓 primitive request-world fields 查询：

```sql
SELECT ...
FROM meta_canonicalization_run
WHERE requested_domains_hash = ?
  AND canonical_contract_version = ?
  AND availability_policy_version = ?
  AND availability_policy_hash = ?
  AND source_policy_version = ?
  AND source_policy_hash = ?
  AND tolerance_policy_version = ?
  AND tolerance_policy_hash = ?
  AND code_fingerprint = ?
ORDER BY canonical_run_id
```

随后 Python 还会在 full seal verification **之前**：

```python
if _ledger_as_of(record) != snapshot.as_of:
    continue
```

这比 CR-3.4 强很多，但仍没有达到“tamper-resistant discovery”。

## 1.2 根因

CR-3.5 的 derived verifier 已经明确证明：

```text
requested_domains_hash
policy hashes / versions
code_fingerprint
as_of
contract
```

都是 Canonical run identity 的 correctness-bearing primitive/inputs，最终必须参与：

```text
context / base / idempotency / run-id physical recompute
```

既然这些字段的 integrity 是在 **full seal verifier 内部**才被确认，那么它们就不能在 verifier **之前**拥有“把某条历史记录排除在候选集之外”的权力。

当前实现只是把 pre-verification trust 从：

```text
status / canonical_context_hash
```

移动到了：

```text
requested_domains_hash / contract / policy identities / code_fingerprint / as_of
```

但 invariant 没变。

> **任何只有在 verifier 内才被证明可信的 correctness field，都不得作为“是否进入 verifier”的排他条件。**

## 1.3 可复现绕过 A：requested_domains_hash only drift

起始：

```text
C1 = historical SUCCESS
C1 requested domains = [daily_bar]
C1 consumed CR-2 A
```

攻击/损坏：

```sql
UPDATE meta_canonicalization_run
SET requested_domains_hash = '<fake hash>'
WHERE canonical_run_id = C1;

DELETE FROM meta_provider_normalization_run
WHERE normalization_run_id = A;
```

随后执行同一：

```text
as_of
requested domains = [daily_bar]
policy/code world
```

当前 `_check_historical_continuity()`：

```text
SQL WHERE requested_domains_hash = current_hash
→ C1 不被 SELECT
→ CanonicalRunSeal / _derived_run_identity_problems 根本没有机会发现 drift
→ current snapshot 已因 A 删除而形成不同 input world/run-id
→ exact replay lookup 也不会命中 C1
→ replacement BLOCKED / 甚至残余输入下的新 SUCCESS 有机会被 mint
```

这与上一轮 `canonical_context_hash` drift 的绕过完全同构。

## 1.4 可复现绕过 B：任一 policy / code selector drift

以下任一字段只改 ledger 一处：

```text
canonical_contract_version
availability_policy_version
availability_policy_hash
source_policy_version
source_policy_hash
tolerance_policy_version
tolerance_policy_hash
code_fingerprint
```

再删除/损坏 prior SUCCESS consumed CR-2 input，即可让该 historical SUCCESS 在 SQL 阶段被排除。

这里不需要伪造完整 primitive world，只需 **单字段 drift**。

## 1.5 可复现绕过 C：as_of only drift

即使 SQL 能选中 row，当前仍在 verifier 之前执行：

```python
if _ledger_as_of(record) != snapshot.as_of:
    continue
```

因此：

```text
prior SUCCESS C1
→ ledger as_of only drift
→ delete/damage consumed CR-2 input
→ current invocation
→ C1 在 full seal 前被 Python continue
```

同样绕过 Historical Canonical Seal。

## 1.6 Required Closure：Selection-Free / Pre-Verification-Trust-Free Discovery

CR-3.6 必须把原则收紧为：

> **No correctness-bearing field may exclude a historical canonical row before its identity seal is verified.**

推荐最简单、最可靠的 v1 方案：

### Phase A — Broad discovery

```sql
SELECT full ledger row
FROM meta_canonicalization_run
ORDER BY canonical_run_id
```

**不按** status/context/domains/as_of/contract/policy/code/hash 等 correctness fields 做排他过滤。

Canonical ledger 目前规模远小于业务数据表，CR-3 correctness 优先于 premature optimization。

如果后续需要性能优化，可在 CR-4+ 另做 **有独立完整性锚的 history index**；CR-3.6 不得用一个未验证的普通 ledger index field 换回旧漏洞。

### Phase B — Historical identity seal first

对每一 historical canonical row：

```text
deterministic manifest URI
manifest bytes == ledger manifest_hash
manifest explicit identity fields == ledger
requested domains hash physical recompute
input/master/dataset/context/base/state/idempotency/run-id physical recompute
```

**先建立可信的 derived request world。**

### Phase C — world/status interpretation after verification

只有 identity seal verified 后：

```text
verified different request world
 -> skip

verified same world + genuine BLOCKED
 -> not SUCCESS continuity dependency; recovery allowed

verified same world + SUCCESS
 -> verify full historical Canonical closure
 -> verify every sealed CR-2 dependency continuity
```

### 对无法建立可信 request-world 的 historical row

如果某 historical row 的 identity seal 已损坏到无法证明其属于哪个 world：

```text
GLOBAL / HISTORICAL CANONICAL LEDGER DAMAGED
fail closed
no new canonical run minted
```

原因很简单：系统不能安全证明“这条损坏记录与当前 world 无关”，因此不能靠猜测跳过。

### Mandatory adversarial tests — Discovery

1. prior SUCCESS -> ledger `requested_domains_hash` only drift -> delete consumed input -> MUST DAMAGED / zero new run。
2. parameterized：prior SUCCESS -> each of contract / availability policy version/hash / source policy version/hash / tolerance version/hash / code_fingerprint only drift -> delete consumed input -> MUST DAMAGED。
3. prior SUCCESS -> ledger `as_of` only drift -> delete consumed input -> MUST DAMAGED。
4. prior SUCCESS -> ledger + manifest one primitive field together rebind + outer manifest_hash -> delete consumed input -> MUST DAMAGED via run-id/derived identity cross-bind；不能因为 forged world 看似不同而提前 skip。
5. verified genuine different-world historical run remains skippable（positive control）。
6. genuine historical BLOCKED remains non-dependency and exact recovery works（positive control）。
7. untouched historical SUCCESS + legitimate new CR-2 superset remains allowed（positive control）。

---

# 2. P0-02：Historical CanonicalRunSeal 在 continuity path 尚未验证 selected / decisions artifact closure

## 2.1 当前 exact replay 路径是正确的

`_verify_closure(record, snapshot)` 已经验证：

```text
artifact exact set = selected / decisions / findings
artifact deterministic URI
content_hash
row_count
schema_hash
selected_semantic_hash
decision_set_hash
findings DB/parquet/seal
sealed CR-2 inputs
```

因此 **exact same run-id replay** 遇到 selected/decisions 文件损坏时，会正确 DAMAGED。

这一机制继续 PASS / FREEZE。

## 2.2 Historical continuity / superset path 的 gap

但 `_check_historical_continuity()` 进入 `_verify_historical_canonical_seal()` 时，当前 historical seal 主要验证：

```text
manifest URI/hash
manifest/ledger correctness identity
input hashes
master/dataset/context/base/state/idempotency/run-id
findings parquet/DB/status truth
```

随后直接进入 CR-2 input continuity。

它 **没有** 在 prior SUCCESS 被当作可信 historical dependency 前验证：

```text
selected.parquet physical content/schema/row_count
selected_semantic_hash

decisions.parquet physical content/schema/row_count
decision_set_hash

artifact exact set / deterministic URI（selected / decisions 部分）
```

因此 historical SUCCESS 的 Canonical correctness artifact 可以在 non-replay path 被损坏而未阻塞新 run。

## 2.3 可复现绕过

```text
C1 = SUCCESS under world W, consumed CR-2 A
selected.parquet / decisions.parquet currently intact
```

随后：

```text
1. tamper or delete C1 selected.parquet
2. keep C1 manifest / ledger / findings intact
3. add a legitimate new healthy CR-2 input B
4. invoke same request world W
```

当前：

```text
current snapshot = A + B
→ new base/run-id（不是 exact replay）
→ historical continuity discovers C1
→ historical identity/status seal passes
→ A still intact
→ selected.parquet damage is not checked by historical seal
→ C2 may be minted
```

这违反已经冻结的 CR-3.2/CR-3.x invariant：

> **prior SUCCESS 被 physical correctness damage 降级后，不得通过新 input world / replacement run 绕过；必须先修复历史证据。**

## 2.4 Required Closure：Shared Historical Canonical Artifact Verifier

不要再维护第三套较弱 artifact verifier。

建议从现有 `_verify_closure()` 抽取共享只读 helper，例如：

```text
_verify_canonical_artifacts(record, manifest)
 -> artifact exact set
 -> deterministic URIs
 -> physical hash/schema/row_count
 -> selected semantic seal
 -> decision semantic seal
 -> findings artifact semantic rows / seal
```

然后：

```text
exact replay
 -> current provenance checks
 -> shared canonical artifact verifier
 -> current sealed-input verifier

historical continuity candidate
 -> historical identity seal
 -> same-world classification
 -> shared canonical artifact verifier
 -> findings/status semantic truth
 -> historical CR-2 dependency continuity
```

规则：

```text
same-world historical SUCCESS:
  any canonical artifact damage -> DAMAGED -> no new run

same-world genuine BLOCKED:
  historical evidence must remain internally intact before it can be classified as genuine BLOCKED

different-world verified run:
  may skip after identity world has been safely established
```

### Mandatory adversarial tests — Artifact Closure

8. prior SUCCESS -> tamper selected.parquet bytes -> add healthy CR-2 superset -> MUST DAMAGED / zero new run。
9. prior SUCCESS -> delete selected.parquet -> superset -> MUST DAMAGED。
10. prior SUCCESS -> tamper decisions.parquet -> superset -> MUST DAMAGED。
11. prior SUCCESS -> selected schema/row-count/semantic seal mismatch -> superset -> MUST DAMAGED。
12. prior SUCCESS -> decisions semantic seal mismatch -> superset -> MUST DAMAGED。
13. untouched prior SUCCESS + superset -> still allowed（positive control）。
14. exact replay artifact-tamper tests remain green（regression）。

---

# 3. CR-3.6 Scope

## 3.1 Allowed

```text
selection-free historical canonical discovery
historical identity-seal-first classification
shared canonical artifact closure verifier
historical SUCCESS selected/decisions artifact verification
focused CR-3.6 adversarial tests
ADR-023 Amendment F
DEVLOG append-only correction/entry
DEVELOPMENT_MANAGEMENT DM entry / status sync
migration 022+ ONLY if an actually anchored history index is introduced
```

## 3.2 Forbidden

```text
SnapshotBuilder
DuckDB ReadModel rebuild
Feature / State
new provider integration
new canonical domains
new source-selection behavior
fallback / reconciliation expansion
production account work
rewriting frozen migrations 018-021
```

CR-3.5 已 PASS 的 derived identity / status formulas 不得重写，除非 CR-3.6 regression 明确证明必须修正。

---

# 4. CR-3.6 Exit Gate

必须全部满足：

```text
[ ] historical candidate discovery 不使用任何未验证 correctness field 做排他 pre-filter
[ ] requested_domains_hash only drift 不能隐藏 prior SUCCESS
[ ] contract / policy / code selector only drift 不能隐藏 prior SUCCESS
[ ] as_of only drift 不能在 verifier 前隐藏 prior SUCCESS
[ ] ledger+manifest primitive rebind 不能通过 forged different-world 逃逸 run-id seal
[ ] different-world verified historical run 可安全跳过
[ ] genuine BLOCKED 仍允许 exact recovery
[ ] same-world SUCCESS selected artifact damage -> DAMAGED / no replacement
[ ] same-world SUCCESS decisions artifact damage -> DAMAGED / no replacement
[ ] historical artifact exact set / URI / hash / schema / rowcount / semantic seals 全消费
[ ] historical findings/status truth仍保持 CR-3.5 semantics
[ ] exact replay full closure regression 全绿
[ ] CR-3.4 materialization evidence symmetry 全绿
[ ] CR-3.3 input continuity / verification cause exactness 全绿
[ ] CR-3.2 transactional snapshot / master PIT / honest policy 全绿
[ ] CR-2.x / R4 frozen regressions 全绿
[ ] no CR-4 semantics leak
[ ] migration 018-021 untouched；若 022+ 则 from-zero/upgrade/idempotent/tamper 全过
[ ] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 CI 全绿
[ ] Ruff / format / Mypy / Spike / SDK-absent / governance gates 全绿
[ ] ADR-023 Amendment F + DEVLOG + DEVELOPMENT_MANAGEMENT 完整同步
[ ] Reviewer 复审无新的 P0 correctness blocker
```

只有全部通过，才允许：

```text
CR-3 / CR-3.1 / CR-3.2 / CR-3.3 / CR-3.4 / CR-3.5 / CR-3.6
 -> VERIFIED / CLOSED / FREEZE

ADR-023
 -> ACCEPTED

CR-4 SnapshotBuilder + DuckDB ReadModel
 -> START
```

---

# 5. Reviewer Owner View

CR-3.5 已经把“历史记录一旦进入检查，身份和 SUCCESS/BLOCKED 真值不能伪造”做到了较高完整度。

CR-3.6 剩下的是两个更底层的收口：

```text
第一：不能让一条需要检查的历史记录
     通过修改任何一个查询字段
     在进入检查前就消失。

第二：不能只证明历史 SUCCESS 的 metadata / findings / upstream input 没问题，
     却允许它自己的 selected / decisions 产物已经损坏。
```

这两条关闭后，Historical Canonical Continuity 才真正满足：

```text
先找到
→ 再证明身份
→ 再证明状态
→ 再证明 Canonical 产物
→ 再证明上游输入
→ 最后才允许产生新的 Canonical world
```

这仍然是 CR-3 correctness closure，不是 CR-4 功能扩展。

---

# 6. Governance Handoff Requirement

本 Reviewer commit 仅新增 focused review/work-requirement 文档，避免在复审提交中大范围重写 DEVLOG / DEVELOPMENT_MANAGEMENT。

**CR-3.6 developer implementation commit 必须同步：**

1. `docs/DEVLOG.md` append-only CR-3.6 implementation entry；
2. `docs/project/DEVELOPMENT_MANAGEMENT.md` 更新 current baseline / CR-3.6 ACTIVE / CR-4 BLOCKED_BY_CR-3.6 / CI；
3. `docs/adr/ADR-023_availability_policy_canonical_selection.md` Amendment F；
4. `docs/adr/ADR-000_adr_index.md` 同步 ADR-023 amendment 状态；
5. 本文档追加 Implementation Mapping + implementation SHA + CI run id。

不得改写历史 DEVLOG 条目来“修正”本轮结论；一律 append correction / new entry。

---

# 7. Implementation Mapping（CR-3.6，2026-09-02）

> Reviewed base：CR-3.5 复审 reopen commit `dd31ca6`（本工作要求）；implementation commit `1ebe96b9d28617939c2782795395ef23eee597e0`（GitHub Actions **run 33623939024 三腿 success**，2026-09-02 API positive confirmation：Windows 3.14 + Windows 3.12 + Ubuntu 3.14 各腿 Ruff lint / Ruff format / Mypy / Pytest（1179/0）/ Spike gates / SDK-absent / DEVLOG gate / Management-doc gate 全 success，一次通过零修复轮次）。总体 **1179/0**（1151 → 1179，+28 项对抗测试）；ruff check / ruff format / mypy 全绿；**零新 migration**（§3.1 允许范围内刻意决策：未引入未验证的 history index——普通 ledger 索引字段会把"查询字段可漂移"的漏洞换一个位置；migration 链保持 21）。

## 7.1 P0-01 Selection-Free / Pre-Verification-Trust-Free Discovery

| 要求 | 实现 |
| --- | --- |
| Phase A broad discovery（不按任何 correctness field 排他过滤） | `_check_historical_continuity` 重写：`SELECT {全列} FROM meta_canonicalization_run ORDER BY canonical_run_id`——无 WHERE、无 Python 预过滤（CR-3.5 的 primitive-fields SQL WHERE 与 as_of Python filter 全部删除） |
| Phase B historical identity seal first | `_verify_historical_canonical_seal` 拆分为 `_verify_historical_identity_seal(seal, record) -> (manifest, problems)`：deterministic manifest URI / bytes hash / manifest 显式 correctness 字段 == ledger / requested domains json+hash / 三 input hash / `_derived_run_identity_problems` 全物理重算——**findings truth 刻意移出**（不同 world 行的 findings/status 与本 world 无关，复审 §2.4 分层流程） |
| Phase C world/status interpretation after verification | 验证后：`seal.canonical_context_hash != snapshot.canonical_context_hash` → safely skip；same world → `_verify_canonical_artifacts` + `_verify_findings_truth` → verified BLOCKED → 非依赖（recovery allowed）；verified SUCCESS → `_continuity_problems_for_input` CR-2 依赖检查 |
| 无法建立可信 request-world 的行 → GLOBAL DAMAGED fail closed | identity seal 任何 problem 或 manifest is None → `historical canonical ledger row ... is DAMAGED (GLOBAL)` raise，零 mint |
| ledger+manifest primitive 对 rebind 不能借 forged different-world 逃逸 | derived identity / run-id cross-bind 在 identity seal 内（world 分类**之前**）运行——`_derived_run_identity_problems` 的 recompute 用 ledger（被 rebind 的）primitives 重算 context/base/idempotency/run-id，与 ledger 原存值必然失配 |

**Mandatory adversarial tests（§1.3）→ `tests/integration/test_canonical.py::TestSelectionFreeDiscovery`（20 项）**

| 要求 | 测试 |
| --- | --- |
| 1. requested_domains_hash only drift → delete input → DAMAGED | `test_requested_domains_hash_drift_cannot_hide_prior_success`（manifest field ≠ ledger → identity seal 拦截） |
| 2. contract / 三 policy version+hash / code_fingerprint only drift → DAMAGED | `test_primitive_selector_drift_cannot_hide_prior_success`（8 字段 parametrize） |
| 3. as_of only drift → verifier 前不可隐藏 | `test_as_of_drift_cannot_hide_prior_success`（deterministic URI anchor 从漂移 as_of 重建 → 与存储 URI 失配 → DAMAGED） |
| 4. ledger+manifest 单 primitive 字段对 rebind + outer hash → DAMAGED via run-id/derived cross-bind，不得提前 skip | `test_primitive_pair_rebind_cannot_forge_different_world`（9 字段 parametrize：requested_domains_hash + 8 选择器；identity seal 内 recompute 先于 world 分类） |
| 5. verified genuine different-world run 可安全跳过 | `test_verified_different_world_run_skippable`（prior SUCCESS at AS_OF_LATE + superset → AS_OF_EARLY world 新 SUCCESS run，count==2） |
| 6. genuine BLOCKED 非依赖 + exact recovery | 既有回归 `TestHistoricalCandidateDiscovery::test_genuine_blocked_not_blocking_exact_recovery`（CR-3.5，全绿保持） |
| 7. untouched SUCCESS + superset 仍允许新 run | 既有回归 `test_superset_with_intact_success_still_allowed` + 本批 `TestHistoricalArtifactClosure::test_untouched_superset_positive` |

## 7.2 P0-02 Shared Historical Canonical Artifact Verifier

| 要求 | 实现 |
| --- | --- |
| `_verify_canonical_artifacts(record, manifest)` 共享只读 helper | 自 `_verify_closure` artifact 段抽取：manifest selected_count/decision_count == ledger → artifact exact set（selected/decisions/findings）→ deterministic URIs（`_expected_artifact_uri`）→ physical content_hash / row_count / schema_hash 逐 artifact → selected semantic seal（recompute == ledger == manifest）→ decision semantic seal（同） |
| exact replay 消费 | `_verify_closure`：provenance（current==ledger）→ typed seal（manifest==ledger）→ derived identity recompute → **`_verify_canonical_artifacts`** → `_verify_findings_truth` → sealed inputs（结构不变，artifact 段替换为共享调用） |
| historical continuity 消费（same-world 每行） | `_check_historical_continuity` Phase C：same-world → `_verify_canonical_artifacts` + `_verify_findings_truth` → 任何 problem → DAMAGED 零 replacement |
| same-world genuine BLOCKED 证据内部完好才可分类 | BLOCKED 行同样过 artifact verifier + findings truth（verified_status == "BLOCKED" 判定在其后） |
| findings artifact semantic rows / seal | 保留在共享 `_verify_findings_truth`（DB == parquet == finding_set_hash seal + status/error recompute；CR-3.5 语义原样） |

**Mandatory adversarial tests（§2.4）→ `TestHistoricalArtifactClosure`（8 项）**

| 要求 | 测试 |
| --- | --- |
| 8. selected.parquet bytes tamper + superset → DAMAGED | `test_selected_bytes_tamper_superset_damaged` |
| 9. selected.parquet 删除 + superset → DAMAGED | `test_selected_delete_superset_damaged` |
| 10. decisions.parquet tamper + superset → DAMAGED | `test_decisions_tamper_superset_damaged` |
| 11. selected schema/row-count/semantic seal mismatch + superset → DAMAGED | `test_selected_seal_mismatch_superset_damaged`（row_count/schema_hash parametrize：manifest artifact seal + outer hash rebind）+ `test_selected_semantic_seal_rebind_superset_damaged`（ledger+manifest selected_semantic_hash 对 rebind） |
| 12. decisions semantic seal mismatch + superset → DAMAGED | `test_decisions_semantic_seal_rebind_superset_damaged`（ledger+manifest decision_set_hash 对 rebind） |
| 13. untouched prior SUCCESS + superset 仍允许 | `test_untouched_superset_positive` |
| 14. exact replay artifact-tamper 回归 | 既有 `TestFullSealConsumption::test_selected_values_rebind_blocks / test_selected_schema_rebind_blocks / test_decisions_rebind_blocks`（全绿保持；且 broad discovery 使 continuity 路径亦拦截——双重捕获） |

## 7.3 Scope Boundary 合规

只修改：`src/ashare_state/canonical/canonicalizer.py`（发现重写 + seal 拆分 + artifact verifier 抽取）、`tests/integration/test_canonical.py`（194 = 166 回归 + 28 新增）、ADR-023 Amendment F（§11.1-§11.4）、ADR-000 索引、`docs/DEVLOG.md`（append-only 新条目）、`docs/project/DEVELOPMENT_MANAGEMENT.md`（DM-20260902-074 + 头部/§40/§41/§44/§61）、本 Mapping。**未新增 migration 022**（未引入 history index）；未触碰 SnapshotBuilder / ReadModel / Feature / State / Provider / 新 domain / selection 行为 / fallback / production 项；未改写 018-021；CR-3.5 PASS 的 derived identity / status formulas 零重写（`_verify_historical_canonical_seal` 拆分只是把 findings truth 从 identity 部分移出——两部分公式逐字节不变，166 项回归全保持即证明）。

## 7.4 Exit Gate 自检

```text
[x] historical candidate discovery 不使用任何未验证 correctness field 做排他 pre-filter     -> Phase A 全表扫描（无 WHERE / 无 Python 过滤）
[x] requested_domains_hash only drift 不能隐藏 prior SUCCESS                                -> mandatory 1 测试
[x] contract / policy / code selector only drift 不能隐藏 prior SUCCESS                     -> mandatory 2 测试（8 字段 parametrize）
[x] as_of only drift 不能在 verifier 前隐藏 prior SUCCESS                                   -> mandatory 3 测试（deterministic URI anchor）
[x] ledger+manifest primitive rebind 不能通过 forged different-world 逃逸 run-id seal       -> mandatory 4 测试（9 字段 parametrize；recompute 先于 world 分类）
[x] different-world verified historical run 可安全跳过                                     -> mandatory 5 测试
[x] genuine BLOCKED 仍允许 exact recovery                                                  -> 既有 CR-3.5 回归全绿
[x] same-world SUCCESS selected artifact damage -> DAMAGED / no replacement                -> mandatory 8/9/11 测试
[x] same-world SUCCESS decisions artifact damage -> DAMAGED / no replacement               -> mandatory 10/12 测试
[x] historical artifact exact set / URI / hash / schema / rowcount / semantic seals 全消费  -> _verify_canonical_artifacts（两路共用）
[x] historical findings/status truth仍保持 CR-3.5 semantics                                -> _verify_findings_truth 原样（same-world 分类后运行）
[x] exact replay full closure regression 全绿                                              -> 166 项回归全保持
[x] CR-3.4 materialization evidence symmetry 全绿                                          -> 同上
[x] CR-3.3 input continuity / verification cause exactness 全绿                             -> 同上
[x] CR-3.2 transactional snapshot / master PIT / honest policy 全绿                         -> 同上
[x] CR-2.x / R4 frozen regressions 全绿                                                    -> 全量 1179/0
[x] no CR-4 semantics leak                                                                 -> 无 SnapshotBuilder / ReadModel 触碰
[x] migration 018-021 untouched；若 022+ 则 from-zero/upgrade/idempotent/tamper 全过        -> N/A（零 schema 变化，21 链不变）
[x] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 CI 全绿                                      -> run 33623939024 三腿 success（2026-09-02 API positive confirmation，一次通过零修复轮次）
[x] Ruff / format / Mypy / Spike / SDK-absent / governance gates 全绿                       -> 本地全绿 + CI 同款命令复验
[x] ADR-023 Amendment F + DEVLOG + DEVELOPMENT_MANAGEMENT 完整同步                          -> Amendment F §11.1-§11.4 + DEVLOG append 新条目 + DM-20260902-074
[ ] Reviewer 复审无新的 P0 correctness blocker                                             -> PENDING_REVIEW
```
