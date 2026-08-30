# A-share-analysis：R4-B2 复审与 R4-B2.1 最终 Validation Seal / Transaction 收口要求

> **Review Date**：2026-08-30 19:13 +08:00  
> **Reviewed Repository HEAD**：`892f465272622395eba030cc9847d68c5b07e539`  
> **Primary R4-B2 Implementation**：`11b1b5bedce7ecc07ba865227c9d3ea820818f66`  
> **Reviewer Baseline / Requirements**：`1f5eb3a2cffa20515564b03ea3aad20feaacfb4c`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **R4-B2 Mechanism Foundation**：**PASS / FREEZE（见 §1）**  
> **Next Batch**：**R4-B2.1 Final Validation Truth + Seal Consumption + Transaction Closure**  
> **CR-2**：**BLOCKED_BY_R4-B2.1**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

R4-B2 已完成大量正确的机制性建设，但尚未达到 VERIFIED。问题不是 CI / lint / test failure，而是有四处 publish correctness contract 仍没有结构性闭合。

本轮冻结为 PASS 的建设：

```text
PASS/FREEZE  old record_artifact_validation caller-count writer removed
PASS/FREEZE  meta_artifact_validation INSERT inline in validate_artifact_for_publish
PASS/FREEZE  production validation function signature no caller counts/result/checks/report
PASS/FREEZE  typed ArtifactValidationCheckId + PASS/FAIL/NOT_TESTABLE
PASS/FREEZE  component existence/content/schema/row_count physical verification
PASS/FREEZE  FEATURE_FAMILY_COVERAGE / feature-set / snapshot binding checks
PASS/FREEZE  component_manifest_hash exact component-registry seal
PASS/FREEZE  validation report persisted as immutable validation/<id>.json
PASS/FREEZE  report_uri/report_hash binding and report-byte re-hash
PASS/FREEZE  legacy pre-B2 validation rows fail closed
PASS/FREEZE  deterministic latest validation head; caller cannot choose historical PASS id
PASS/FREEZE  publish-time physical component bytes re-hashed
PASS/FREEZE  atomic republish rollback / exact artifact_validation_id binding retained
PASS/FREEZE  migration 011 added without rewriting old migrations
PASS/FREEZE  ADR-021 remains PROPOSED / management remains PENDING_REVIEW
PASS/FREEZE  full required CI matrix green
```

但以下四个 P0 blocker 必须一次性收口：

```text
P0-01  IDENTITY_FALLBACK_ZERO / BLOCKING_DQ_ZERO 仍可“未执行即 PASS”
P0-02  validation seal 写了但 publish 未完整消费 contract/check/provenance seal
P0-03  Option A TOCTOU 只把 _b2_recheck 放进事务，完整 publish-critical reads 仍在事务外
P0-04  新物理文件验证绕过 frozen logical-URI confinement helper，可读 data_root 外路径
```

另有 P1：`ARTIFACT_MANIFEST_INTEGRITY` 当前只证明“manifest_hash 非空 + 有 components”，并没有真正验证 manifest integrity；check 名称/语义与实际证据不一致。

因此：

```text
R4-B2   -> DONE / REOPENED
R4-B2.1 -> START / ACTIVE NEXT
CR-2    -> BLOCKED
```

本轮不启动 CR-2，不重开 R4-B1/A3/A2/CR-1 冻结链。

---

# 1. 已通过并冻结的 R4-B2 机制

## 1.1 Formal Validation Boundary —— PASS / FREEZE

`validate_artifact_for_publish()` 已成为 production pipeline 中唯一写 `meta_artifact_validation` 的 callable；旧 `record_artifact_validation()` 消失，函数签名不接受：

```text
identity_fallback_count
blocking_dq_count
result
checks
report
```

ledger INSERT 与验证控制流在同一函数内，B1.1/B1.2 已证明过的“不要靠下划线/private dataclass 伪装不可绕过”原则被正确复用。

这一结构保持冻结；R4-B2.1 不要重新引入独立 PASS persistence helper / caller-build ValidatedArtifact。

## 1.2 Typed Checks / Physical Component Validation —— PASS / FREEZE

以下机制正确：

- typed required-check IDs；
- FAIL / NOT_TESTABLE blocking；
- physical file existence；
- file SHA-256 vs registered content_hash；
- parquet schema re-read + schema_hash；
- parquet row_count re-read；
- feature family coverage；
- feature-set / DATA_VALIDATED snapshot existence binding。

B2.1 只修 correctness gap，不重写这些机制。

## 1.3 Component Seal + Persisted Report —— PASS / FREEZE

`component_manifest_hash` 覆盖：

```text
file_uri
content_hash
schema_hash
row_count
feature_family
feature_family_version
layer
partition_key
```

report 有 immutable file identity；ledger 绑定 report URI/hash；publish 会重新读 report bytes、重算 sha256，并重新计算 CURRENT component manifest，同时重验物理 bytes。

这部分机制正确，继续冻结。

## 1.4 Latest Head / Legacy / Atomic Republish —— PASS / FREEZE

- latest validation：`validated_at DESC, artifact_validation_id DESC`；
- caller 无 API 传历史 validation id；
- legacy row 无 B2 report seal → BLOCK；
- publish 绑定 exact `artifact_validation_id`；
- final gate/write 异常 rollback，旧 PUBLISHED 保留。

继续冻结。

---

# 2. P0-01：DQ Required Checks 仍存在“未执行即 PASS”

## 2.1 当前问题

当前 formal validator 对两项 required checks 的实现是：

```text
IDENTITY_FALLBACK_ZERO
BLOCKING_DQ_ZERO
```

从 `meta_artifact_dq_finding` 做：

```sql
SELECT count(*) ... finding_class = 'IDENTITY_FALLBACK'
SELECT count(*) ... finding_class = 'BLOCKING_DQ'
```

然后：

```text
count == 0 -> PASS
```

但 `meta_artifact_dq_finding` 只记录“坏事实”，没有正向证明：

```text
对应 DQ scan / identity-fallback scan 确实执行过
且扫描范围 == 当前 exact artifact/components
且 scan contract/version == 当前 required check contract
```

所以当前存在：

```text
feature pipeline 根本没跑 identity-fallback / blocking-DQ scan
-> finding table 对该 artifact 自然为空
-> SELECT count(*) = 0
-> formal validator 把两项 required checks 标 PASS
-> publish eligible
```

这正是 B2-02 要消除的“两个 aggregate count 无法区分：检查过且为零 vs 根本没检查”。

ADR-021 当前将该问题列为 CR-3 residual risk，但这不能作为 R4-B2 VERIFIED 的前提：B2 required-check contract 自己已经把这两项声明为 REQUIRED，因此“是否执行”必须在 B2 fail-closed。

## 2.2 R4-B2.1 要求

不要求在 B2.1 扩展全部 CR-3 DQ 业务语义，但必须有 **positive execution proof**。

允许等价设计，推荐原则：

```text
DQ required check
-> governed check runner / upstream persisted check proof
-> exact artifact/component identity binding
-> check_id + contract/version + producer identity
-> completed status
-> derived finding_count
-> persisted proof identity
-> formal artifact validator consumes it
```

关键规则：

1. **absence of bad findings != proof of zero findings**；
2. 没有对应 check execution/completion proof → `NOT_TESTABLE`，不得 PASS；
3. execution proof 必须绑定 current `feature_artifact_set_id` + exact component/artifact identity；
4. stale scan（artifact/component identity 已变化）不得继承；
5. check runner / producer 不得提供 caller-facing `count=0/result=PASS` persistence API；
6. 如果当前 production feature pipeline 尚没有能力产生这种正向 proof，formal validator 必须 fail closed 为 NOT_TESTABLE；mock/tests 可以通过 tests-side controlled producer 建立 proof，但 production 不得默认 PASS；
7. `identity_fallback_count` / `blocking_dq_count` 最终仍可作为 summary，但 eligibility 真相是 typed check execution proof + result。

不要把该修复扩大成 CR-3 全量 DQ 体系；这里只闭合“REQUIRED check 确实执行过”的证据链。

## 2.3 Mandatory tests

```text
no DQ execution proof + no bad findings -> NOT_TESTABLE -> publish BLOCK
valid exact scan proof + zero findings -> PASS
scan proof for different artifact -> BLOCK
scan proof bound to old component manifest -> BLOCK after component change
missing one of two required DQ execution proofs -> BLOCK
caller tries to persist zero-count/PASS proof directly -> no production bypass path
```

---

# 3. P0-02：Exact Validation Seal 未被 publish 完整消费

## 3.1 当前问题

R4-B2 ledger/report 已写入：

```text
validation_version
validator_code_commit
validation_contract_hash
artifact_manifest_hash
component_manifest_hash
required_checks_hash
report_uri
report_hash
```

但 `_b2_recheck()` 当前 SELECT / recheck 只消费：

```text
artifact_validation_id
identity_fallback_count
blocking_dq_count
report_uri
report_hash
artifact_manifest_hash
component_manifest_hash
```

没有机器重验：

```text
ledger.validation_contract_hash
report.validation_contract_hash
current validation_contract_hash()

ledger.required_checks_hash
report.required_checks_hash
recomputed hash(report checks)

ledger.validator_code_commit
report.validator_code_commit

ledger.validation_version
report.validation_version / current supported contract version
```

因此 ADR-021 所写“contract changed -> old seal invalid”目前并不成立。

一个尤其明确的例子：required check IDs 不变、但 check semantics / contract version/hash 改变时，旧 report 仍包含当前 required IDs 且全 PASS，`_b2_recheck()` 不比较 current contract hash，就可能继续发布旧 validation。

同样，`required_checks_hash` 虽写入 ledger/report，但 publish 不消费它；这是“写了 seal 字段”而不是“seal 成为 correctness input”。

## 3.2 R4-B2.1 要求

`_b2_recheck()` 必须把完整 seal 作为不可拆分 identity 读取并交叉验证：

```text
ledger <-> report <-> current contract
```

至少：

```text
ledger.validation_contract_hash == report.validation_contract_hash
ledger.validation_contract_hash == validation_contract_hash() CURRENT

ledger.required_checks_hash == report.required_checks_hash
report.required_checks_hash == recompute(report typed check-id/status set)

ledger.validator_code_commit == report.validator_code_commit
validator_code_commit non-empty

ledger.validation_version == report.validation_version
validation_version == CURRENT supported validation contract version
(or explicit typed compatibility policy; no silent grandfather)
```

推荐把 `validation_version` 从 caller optional input 改为 system-derived current version；若必须允许显式版本参数，则只能等于当前 supported version，不能成为 caller 自报 provenance。

还应拒绝 duplicate required check IDs，避免 dict collapse 让两个同 ID 条目覆盖彼此。

## 3.3 Mandatory adversarial tests

所有 tamper 测试都应在“重新绑定 report_hash”后仍 BLOCK：

```text
report validation_contract_hash stale -> BLOCK
ledger/report validation_contract_hash mismatch -> BLOCK
current contract hash changed while IDs unchanged -> old validation BLOCK
report required_checks_hash tamper -> BLOCK
ledger/report required_checks_hash mismatch -> BLOCK
check status changed but required_checks_hash 未同步 -> BLOCK
validator_code_commit mismatch -> BLOCK
validation_version mismatch / legacy unsupported version -> BLOCK
duplicate required check_id -> BLOCK
```

---

# 4. P0-03：Option A TOCTOU Closure 只完成局部

## 4.1 当前问题

Reviewer R4-B2-05 明确要求 Option A：

```text
BEGIN TRANSACTION
  -> resolve snapshot/artifact/run/feature-set/universe
  -> resolve current validation head
  -> verify exact validation seal
  -> final required-check PASS
  -> publish writes
COMMIT
```

当前实现仍是：

```text
transaction OUTSIDE:
  snapshot status/policies
  artifact status + snapshot/version/run/provenance
  feature-set status/definition hash
  run status/provenance/policies
  universe existence

BEGIN TRANSACTION
  _b2_recheck(validation/artifact-component proof)
  publish writes
COMMIT
```

因此它只关闭了 validation/component 那部分窗口，没有实现 Reviewer 已批准的 Option A 全量 authoritative re-read。

ADR-021 §2.4 一方面写“全部 precondition read 仍在事务外”，另一方面又声称“TOCTOU closed”；这两句不能同时成立。

DuckDB 单写者模型可以降低并发发生概率，但不能把一个 transaction 外读取的状态自动变成 transaction 内 authoritative fact；而且既然本批已经明确选择 Option A，就应让代码与 ADR 一致。

## 4.2 R4-B2.1 要求

允许保留 transaction 外的 **advisory / fail-fast precheck**，但 publish correctness 不能依赖它们。

事务内必须重新读取并使用当前值验证：

```text
snapshot exists + DATA_VALIDATED + source/availability policy
artifact exists + FEATURE_VALIDATED + snapshot/version/calc_run/provenance
feature set exists + ACTIVE + CURRENT member definition hash
pipeline run exists + FEATURE_VALIDATED + recovery semantics + provenance/policy
all universes still exist
latest validation head
full validation seal/report/physical bytes
```

所有写入使用事务内 authoritative values，不得沿用 transaction 外 stale tuples 作为 correctness input。

结构上可提取：

```text
_resolve_publish_preconditions(conn, ...)
```

但必须在 `BEGIN TRANSACTION` 后调用；transaction 外若再调用一次只能用于友好错误，不可替代最终调用。

## 4.3 Mandatory tests

```text
state changes after advisory precheck / before authoritative txn check -> BLOCK
snapshot demoted before txn authoritative read -> BLOCK
artifact demoted / rebound before txn authoritative read -> BLOCK
feature-set definition changed before txn authoritative read -> BLOCK
run status/provenance changed before txn authoritative read -> BLOCK
universe removed before txn authoritative read -> BLOCK
structural guard proves authoritative publish-precondition resolver runs after BEGIN
final failure still rollback and preserve old PUBLISHED
```

不要通过增加 production test-hook 来制造 race；可使用 connection proxy / extracted resolver / structural ordering guard 等测试方式。

---

# 5. P0-04：B2 新物理文件读取绕过 Frozen Logical-URI Confinement

## 5.1 当前问题

Frozen P0-4 contract 已有唯一 helper：

```text
validate_logical_uri(uri)
physical_from_logical_uri(data_root, uri)
```

规则包括：

```text
relative to data_root
POSIX '/' only
no scheme
no leading slash
no drive letters
no backslash
no '..'
no alias form (a//b, a/./b, a/b/)
```

但 R4-B2 新增代码在 validation 和 publish final recheck 中直接做：

```python
path = data_root / uri
comp_path = Path(data_root) / component["file_uri"]
```

没有走 frozen confinement helper。

因此如果 component registry 在 formal validation 前包含：

```text
../outside.parquet
/absolute/outside.parquet
C:/outside.parquet
...
```

validator 可能解析/读取 data_root 外的文件，而不是在 URI 层 fail closed。随后 component manifest 会把这个非法 URI 本身 seal 下来，publish 又用同样的直接 Path join 复验，形成“非法路径被一致地验证”而不是“非法路径被拒绝”。

这是 R4-B2 新物理读取路径对 Frozen P0-4 的回归风险，必须在 B2 closure 前修复。

## 5.2 R4-B2.1 要求

validation 与 publish final recheck 解析任何 registry `file_uri` 时，统一使用 existing frozen helper：

```python
physical_from_logical_uri(data_root, file_uri)
```

并保持 exact string identity；不得自行 normalize 后接受 alias。

若 component URI invalid：

```text
validation required check -> FAIL / NOT_TESTABLE（fail closed）
publish final recheck -> BLOCK
```

同时对 report_uri 可继续使用系统生成的 `validation/<uuid>.json`，但读取时也建议走同一 logical-URI helper，形成统一 confinement。

## 5.3 Mandatory tests

至少：

```text
../outside.parquet -> BLOCK before filesystem read outside root
/absolute/path -> BLOCK
C:/windows-drive/path -> BLOCK cross-platform
backslash path -> BLOCK
alias a//b / a/./b -> BLOCK
valid canonical POSIX relative URI -> unchanged PASS
```

测试应证明 outside sentinel 文件即使存在且 hash 完全匹配，也不能被 validator/publish 当作合法 component。

---

# 6. P1-01：ARTIFACT_MANIFEST_INTEGRITY check 当前名称/证据不一致

当前实现：

```text
if artifact_manifest_hash and components:
    ARTIFACT_MANIFEST_INTEGRITY = PASS
```

这证明的是：

```text
registered artifact_manifest_hash 非空
且 artifact 有 component rows
```

它没有重新计算注册时 artifact manifest formula，也没有证明该 hash 与 component registry coherent。

B2.1 需要二选一：

### Option A
真正重算 registration-time artifact manifest identity，并与 `meta_feature_artifact_set.artifact_manifest_hash` 比较；需要的 identity metadata 必须来自可审计 registry，不能猜字段。

### Option B
如果当前 feature component schema 无法无损重建旧 registration formula，则不要 overclaim：把 typed check 改成与证据相符的语义，例如：

```text
ARTIFACT_MANIFEST_PRESENT_AND_SEALED
```

同时明确：component registry/bytes 的实际 exact integrity 由 `component_manifest_hash + COMPONENT_*` checks 证明；`artifact_manifest_hash` 是上游注册身份 seal，不在 B2 假装重算。

无论选哪种，ADR-021 / report detail / tests 必须与运行时真相一致。

---

# 7. CI / Governance Review

Reviewer 正向核验：

- R4-B2 implementation `11b1b5bedce7ecc07ba865227c9d3ea820818f66`：run `33307917769` = success；
- current reviewed HEAD `892f465272622395eba030cc9847d68c5b07e539`：run `33308120230` = success；
- current HEAD job-level：Ubuntu Python 3.14 / Windows Python 3.12 / Windows Python 3.14 均 success；Ruff lint / format / Mypy / Pytest / Spike framework gates success；Windows 3.14 governance gates success。

因此本轮 REOPENED 与 CI 无关。

治理方面当前正确保持：

```text
R4-B2 DONE / PENDING_REVIEW
CR-2 BLOCKED_BY_R4-B2
ADR-021 PROPOSED
```

开发方没有提前自称 VERIFIED / ACCEPTED，本项 PASS。

R4-B2.1 必须以 amendment 修正 ADR-021 当前以下 overclaim：

```text
“contract hash changes invalidate prior seals” —— 当前 publish 尚未验证 current contract hash
“TOCTOU closed” —— 当前只 validation/component final recheck 在 txn 内，完整 lineage reads 仍在 txn 外
“required checks cannot be unexecuted” —— DQ zero checks 当前仍以 bad-fact absence 直接 PASS
```

历史原文保留；新增 amendment，不重写历史事实。

---

# 8. R4-B2.1 Scope / Exit Gate

本批只做 R4-B2 correctness closure，不启动 CR-2 主实现。

## 8.1 必须完成

```text
[ ] DQ required checks 有 positive execution proof；absence 不再等于 zero PASS
[ ] no execution proof -> NOT_TESTABLE / publish BLOCK
[ ] validation_contract_hash ledger/report/current 三方 exact match
[ ] required_checks_hash ledger/report/recomputed exact match
[ ] validator_code_commit / validation_version ledger-report identity complete
[ ] stale semantic contract seal blocks old validation even when check IDs unchanged
[ ] all authoritative snapshot/artifact/feature-set/run/universe reads transaction-internal
[ ] validation latest-head + report/seal + physical bytes final recheck remains transaction-internal
[ ] frozen logical URI confinement used by validation/publish physical component resolution
[ ] escaped/absolute/drive/backslash/alias file_uri fail closed
[ ] ARTIFACT_MANIFEST typed check claim与实际可证明事实一致
[ ] latest-head / legacy / atomic republish frozen mechanisms无回归
[ ] R4-B1/A3/A2/CR-1 frozen contracts无回归
[ ] migration-from-zero + upgrade path green if schema changes
[ ] full Windows 3.12 / Windows 3.14 / Ubuntu 3.14 CI green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR-021 amendment 与 runtime 真相一致
```

## 8.2 状态推进

全部满足后：

```text
R4-B2 / R4-B2.1 -> VERIFIED / CLOSED / FREEZE
CR-2 Provider-Normalized + Quarantine -> START / ACTIVE NEXT
```

若本批按上述四个 P0 + 一个 P1 完整收口，**不要再机械创建 R4-B2.2**；直接提交 Reviewer 复审。

Production P0-M-1B 仍独立 BLOCKED，不因 B2 closure 自动放行。

---

# 9. Governance Change IDs 建议

下一批建议登记：

```text
DM-CR-20260830-057 DQ Required-Check Positive Execution Proof
DM-CR-20260830-058 Full Validation Seal Consumption / Current Contract Recheck
DM-CR-20260830-059 Full Transaction-Internal Publish Preconditions
DM-CR-20260830-060 Publish Validation Logical-URI Confinement
```

若 P1 manifest check 语义调整属于 contract rename / semantic correction，一并写入 ADR-021 Amendment R4-B2.1；无需另建 ADR。

---

# 10. Implementation Mapping（开发方填写，2026-08-30）

## P0-01 — DQ Required-Check Positive Execution Proof（§2）

| Requirement（§2.2/§2.3） | Implementation | Tests |
|---|---|---|
| positive execution proof：governed check runner 持久化 proof | 新表 `meta_artifact_check_execution`（migration 012）+ `record_artifact_check_execution`（check_id / artifact set / scan_contract_version / producer / **scanned_component_manifest_hash** / completed_at / detail） | test_valid_exact_proof_with_zero_findings_passes |
| absence of bad findings != proof of zero findings | validator 语义：无 proof → **NOT_TESTABLE**（"no positive execution proof... absence of bad findings is not proof of zero findings"） | test_no_execution_proof_is_not_testable_and_blocks（删 proofs → 两 check NOT_TESTABLE → publish BLOCK） |
| proof 绑定 current feature_artifact_set_id + exact identity | proof 按 (artifact set, check_id) 查询且 `scanned_component_manifest_hash == compute_component_manifest_hash(current components)` 才有效 | test_proof_for_different_artifact_does_not_transfer / test_stale_proof_blocks_after_component_change |
| stale scan 不得继承 | stale → NOT_TESTABLE（"stale scan... artifact changed after the scan; rescan required"） | 同上 stale 测试 |
| 不得提供 caller-facing count=0/result=PASS persistence API | `record_artifact_check_execution` 签名无 count/result/status/pass 参数（AST 断言）；production 唯一 INSERT 边界（AST 扫描 pipeline 包）；findings 仍走 append-only 事实表 | test_execution_proof_api_carries_no_result_params |
| production feature pipeline 无能力时 fail closed NOT_TESTABLE | validator 消费侧强制（无匹配 proof 即 NOT_TESTABLE）；mock_e2e 在 validate 前记录 proofs（mock 链示范）；tests 用 tests-side producer 建立证明 | 上述全部 |
| counts 只是 summary | report.summary 携带派生计数；eligibility = proof + typed check 状态 | happy report 断言 |

Mandatory tests §2.3 六项全对应：no proof+no findings→NOT_TESTABLE BLOCK ✓；valid exact scan proof+zero findings→PASS ✓；proof for different artifact→BLOCK ✓；proof bound old manifest→BLOCK after change ✓；missing one of two→BLOCK ✓；caller persist zero-count/PASS directly→无 production bypass 路径（签名 + 唯一 INSERT 边界）✓

## P0-02 — Full Seal Consumption（§3）

| Requirement（§3.2） | Implementation | Tests |
|---|---|---|
| ledger.validation_contract_hash == report == current | `_b2_recheck` 三方比对（CURRENT 经 `validation_contract_hash()`） | test_report_contract_hash_stale / test_ledger_report_contract_hash_mismatch / test_current_contract_change_blocks_old_validation（monkeypatch current——IDs 不变仍 BLOCK） |
| required_checks_hash 三方 + 重算 | ledger == report == sha256(report checks 的 {check_id,status} canonical JSON) | test_report_required_checks_hash_garbage / test_ledger_checks_hash_mismatch / test_status_changed_without_rehash（status 改动未重封） |
| validator_code_commit 一致且非空 | ledger == report 且非空 | test_validator_commit_mismatch |
| validation_version 一致 + 当前 supported | ledger == report == VALIDATION_CONTRACT_VERSION；**`validate_artifact_for_publish` 移除 caller version 参数（system-derived）** | test_validation_version_mismatch |
| duplicate required check id 拒绝 | report checks 数组 id 集合大小 == 数组长度（先于 dict collapse） | test_duplicate_check_id_blocks（重复条目 + 双 hash 一致 re-seal 仍 BLOCK） |

Mandatory adversarial §3.3 九项全对应（全部 re-bind report hash 后仍 BLOCK）✓

## P0-03 — Full Transaction-Internal Preconditions（§4）

| Requirement（§4.2） | Implementation | Tests |
|---|---|---|
| 事务内重新读取全部 authoritative 状态 | `_resolve_publish_preconditions`（完整 lineage gate 语义零变更：snapshot DATA_VALIDATED + policies / artifact FEATURE_VALIDATED + snapshot/version/calc_run/provenance / feature-set ACTIVE + definition hash 自检 / run FEATURE_VALIDATED + recovery 语义 + provenance/policy / universes）在 BEGIN TRANSACTION 后调用；`_b2_recheck`（head + 完整 seal + 物理 bytes）同；写入只消费事务内值 | test_structural_guard_preconditions_inside_transaction（AST ordering：BEGIN < resolver < recheck < 首个 execute） |
| state changes → BLOCK | 事务内 authoritative re-read 用当前值判定 | snapshot demoted / artifact demoted / artifact rebound / feature-set member 改动（FEATURE_SET_IMMUTABLE）/ run status 变化 / universe 删除 七场景全 BLOCK |
| 最终失败 rollback 保留旧 PUBLISHED | 既有原子 republish 契约零改动（FREEZE） | test_failed_final_gate_preserves_old_published + test_failure_injection scenario D 零回归 |
| 不通过 production test-hook 制造 race | 测试用 AST ordering 守卫 + 状态变化场景（无 test-hook） | 结构性证明 |

## P0-04 — Logical-URI Confinement（§5）

| Requirement（§5.2/§5.3） | Implementation | Tests |
|---|---|---|
| validation + publish 物理解析统一走 frozen helper | validator 组件重验 / publish bytes 终验 / report 读取全部经 `physical_from_logical_uri(data_root, uri)`（exact string identity，不 normalize 接受 alias） | TestR4B21LogicalURIConfinement |
| 恶意 URI fail closed（先于 data_root 外读取） | URI 层 validate_logical_uri 抛错 → COMPONENT_EXISTENCE FAIL（confinement 词）→ publish BLOCK | ../outside / /absolute / C:/drive / backslash / a//b / a/./b 六项参数化测试 |
| outside sentinel 即使存在且 hash 完全匹配也被拒 | 测试在 data_root 外放 **bytes 与真实组件一致的 sentinel**——仍被拒（拒绝发生在 URI 层） | 同上（每项测试均创建 perfect sentinel） |
| valid canonical POSIX URI unchanged PASS | frozen helper 语义零变更 | test_valid_canonical_uri_still_passes |
| report_uri 也走同一 helper | `physical_from_logical_uri(data_root, report_uri)`（系统生成 validation/<uuid>.json 天然 canonical；非 canonical report_uri → REPORT_URI_INVALID BLOCK） | 代码审查点 |

## P1-01 — Manifest Check 语义诚实化（§6，Option B）

| Requirement | Implementation | Tests |
|---|---|---|
| check 名称与证据一致 | rename `ARTIFACT_MANIFEST_INTEGRITY` → `ARTIFACT_MANIFEST_PRESENT_AND_SEALED`；detail 明确"exact component integrity is proven by the component manifest seal + COMPONENT_* checks" | happy report 断言（REQUIRED_VALIDATION_CHECKS 枚举自动覆盖 rename）+ detail 语义断言 |

## §7 治理一致性

- **ADR-021 Amendment R4-B2.1**（E.1-E.7）：修正原文三处 overclaim（"contract hash changes invalidate prior seals" / "TOCTOU closed" / "required checks cannot be unexecuted"——原文保留，落地后成立）；P0-01..04 + P1-01 决策记录；残余边界如实记录（execution proof 证明扫描执行 + exact 输入绑定，不证明 producer 诚实上报全部 findings——CR-3 域）
- DEVELOPMENT_MANAGEMENT.md：头部（R4-B2 REOPENED / R4-B2.1 DONE / CR-2 BLOCKED_BY_R4-B2.1）+ §40/§41 重写 + §61 DM-CR-20260830-057/058/059/060
- DEVLOG.md 顶部新条目（2026-08-30 R4-B2.1）
- 未自称 VERIFIED / ACCEPTED；ADR-021 保持 PROPOSED 待复审

## §8.1 Exit Gate 对照

```text
[✓] DQ required checks positive execution proof；absence 不再等于 zero PASS
[✓] no execution proof -> NOT_TESTABLE / publish BLOCK
[✓] validation_contract_hash ledger/report/current 三方 exact match
[✓] required_checks_hash ledger/report/recomputed exact match
[✓] validator_code_commit / validation_version ledger-report identity complete
[✓] stale semantic contract seal blocks old validation（IDs 不变场景测试）
[✓] all authoritative reads transaction-internal（AST ordering 守卫 + 七状态场景）
[✓] latest-head + report/seal + physical bytes final recheck remains transaction-internal
[✓] frozen logical URI confinement used by validation/publish
[✓] escaped/absolute/drive/backslash/alias file_uri fail closed（六类 + perfect sentinel）
[✓] ARTIFACT_MANIFEST typed check 与实际可证明事实一致（Option B rename）
[✓] latest-head / legacy / atomic republish frozen 机制零回归
[✓] R4-B1/A3/A2/CR-1 frozen contracts 零回归（全量 848/0）
[✓] migration-from-zero（12 链）+ upgrade path green
[✓] full Windows 3.12 / Windows 3.14 / Ubuntu 3.14 CI green（run 33310045925 三腿 success，implementation `317ac488c00c6b406311a29f25ff062e312df3a3`，2026-08-30 API positive confirmation，一次通过零修复轮次）
[✓] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR-021 amendment 与 runtime 真相一致
```

## Verification Summary

- Local: **848 / 0**（819 → 848，+29）；ruff check / ruff format --check / mypy 全绿；CI 同款命令 `uv run pytest` 复验 848/0
- §8 scope boundary：未启动 CR-2 主实现；按 §8.2 直接提交复审（不机械创建 R4-B2.2）
