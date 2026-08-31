# A-share-analysis：R4-B2.2 复审与 R4-B2.3 最终 DQ Authoritative Input Seal 收口要求

> **Review Date**：2026-08-31 13:37 +08:00  
> **Reviewed Repository HEAD**：`1fc6d2329a6f185c320e0805068586d394cba20e`  
> **Primary R4-B2.2 Implementation**：`281a39b6cbf421ed509711f02338c39fb74cf8ea`  
> **Reviewer Baseline / Requirements**：`625f4a2b9214d3c33ad5c6fcfd7b2552866f9b22`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED（仅剩 1 个 P0：authoritative scan-input freshness seal）**  
> **R4-B2.2 scanner ownership / execution boundary**：**PASS / FREEZE**  
> **Next Batch**：**R4-B2.3 Final DQ Authoritative Input Seal + Scan Transaction Closure**  
> **CR-2**：**BLOCKED_BY_R4-B2.3**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

R4-B2.2 已经真正关闭了上一轮的“caller self-declare scan executed”问题。本轮确认以下部分 **VERIFIED / FREEZE**，不得继续机械重构：

```text
VERIFIED / FREEZE  production caller-facing record_artifact_check_execution removed
VERIFIED / FREEZE  run_required_artifact_dq_scan public signature only accepts
                   conn / data_root / feature_artifact_set_id
VERIFIED / FREEZE  scanned component manifest is scanner-internal, not caller parameter
VERIFIED / FREEZE  DQ scan contract version is system-derived
VERIFIED / FREEZE  checker producer identity is system-derived from static checker registry
VERIFIED / FREEZE  ARTIFACT_DQ_CHECKERS is production-owned static registry, not caller parameter
VERIFIED / FREEZE  IDENTITY_FALLBACK evaluator performs real authoritative-input read
VERIFIED / FREEZE  BLOCKING_DQ evaluator performs real authoritative-input read
VERIFIED / FREEZE  actual findings are persisted before completion proof
VERIFIED / FREEZE  evaluator failure rolls back and leaves no completion proof
VERIFIED / FREEZE  validator requires current contract + exact checker producer + component manifest
VERIFIED / FREEZE  genuine zero scan happy path exists
VERIFIED / FREEZE  stale component manifest / stale scan contract / fake producer fail closed
VERIFIED / FREEZE  R4-B2.1 full seal / publish transaction / URI confinement / manifest-name semantics intact
VERIFIED / FREEZE  implementation CI + current HEAD CI full matrix green
```

但是 Reviewer 在检查“真实 scan 的 authoritative input 到底是什么”时发现一个新的、可复现的 correctness gap：

> completion proof 现在只 seal `scanned_component_manifest_hash`，但两个真实 checker 实际读取的 authoritative input **不只 components**。

当前真实输入为：

```text
IDENTITY_FALLBACK_ZERO
  components -> security_id set
  + dim_security.identity_key_version

BLOCKING_DQ_ZERO
  artifact.data_snapshot_id
  + fact_daily_bar / fact_security_status_daily / fact_limit_price /
    fact_adj_factor / fact_corporate_action 的 quality_flags
```

因此当前 completion row 只能证明：

```text
“scanner 曾在某 component manifest 下跑完”
```

还不能证明：

```text
“scanner 当时读取的 identity registry / snapshot DQ input
  与 validation / publish 当前看到的 authoritative input 仍是同一份”
```

这会造成 **stale governed proof → false PASS**。

因此：

```text
R4-B2     -> DONE / REOPENED
R4-B2.1   -> DONE / REOPENED（已通过项全部 FREEZE）
R4-B2.2   -> DONE / REOPENED（scanner boundary PASS/FREEZE；input seal 未闭合）
R4-B2.3   -> START / ACTIVE NEXT
CR-2      -> BLOCKED
```

这是发现了新的可复现 correctness gap，不是机械增加 review 轮次。除本 P0 外，不重开 B2.2 scanner ownership，也不重开 B2.1/B1/A3/A2/CR-1 冻结项。

---

# 1. R4-B2.2 已正确关闭的原 P0 —— PASS / FREEZE

## 1.1 Completion proof 已经是实际 scanner 的内部产物

`run_required_artifact_dq_scan()` 当前结构已经满足上一轮最核心要求：

```text
static checker registry
-> production evaluator
-> actual authoritative read
-> derive findings
-> persist findings
-> INSERT completion proof LAST
```

旧 `record_artifact_check_execution()` 已从 production API 消失；caller 无法通过合法 production callable 提交：

```text
scanned_component_manifest_hash
scan_contract_version
producer
count/result/status
completed_at
```

这一项 CLOSED / FREEZE。

## 1.2 两个 DQ checker 不再是 no-op

当前 checker 的实际输入与判断逻辑已经存在：

### IDENTITY_FALLBACK

读取 artifact component parquet 中的 distinct `security_id`，再读取：

```text
dim_security.security_id
dim_security.identity_key_version
```

`SECURITY_IDENTITY_V1_FALLBACK` 或 security_id 无法在 `dim_security` 证明 → finding。

### BLOCKING_DQ

读取 artifact 当前绑定 snapshot 的：

```text
fact_daily_bar
fact_security_status_daily
fact_limit_price
fact_adj_factor
fact_corporate_action
```

的 `quality_flags`，命中 blocking flag → finding。

这满足上一轮“真实 scan 必须能说明 authoritative input”的要求，本轮不要求改 checker 业务定义，除非为 input-fingerprint 所必需。

## 1.3 Validator 已正确消费 current scan contract / checker provenance

validator 已要求：

```text
proof.scan_contract_version == CURRENT DQ_SCAN_CONTRACT_VERSION
proof.producer == static registry system-derived producer
proof.scanned_component_manifest_hash == current component manifest
```

旧/未知 contract、fake producer、stale components → `NOT_TESTABLE`。

这一部分 PASS / FREEZE。

---

# 2. 唯一剩余 P0：Completion Proof 未绑定完整 Authoritative Scan Input

## 2.1 组件 manifest 不是两个 checker 的完整输入

当前 execution-completion schema（migration 012）包含：

```text
feature_artifact_set_id
check_id
scan_contract_version
producer
scanned_component_manifest_hash
completed_at
```

其中 `scanned_component_manifest_hash` 只 seal artifact component registry identity。

但：

```text
IDENTITY_FALLBACK evaluator
```

还读取可独立变化的：

```text
dim_security.identity_key_version
```

而：

```text
BLOCKING_DQ evaluator
```

还读取：

```text
artifact.data_snapshot_id
snapshot-bound canonical fact quality_flags
```

这些输入都没有进入 completion proof，也没有进入 validation report / publish final recheck 的 current-input equality check。

所以：

```text
component manifest unchanged
```

并不等于：

```text
checker authoritative input unchanged
```

这是本轮 P0。

## 2.2 可复现错误路径 A：identity registry 在 scan 后变化

当前代码允许：

```text
1. governed scan genuinely runs
2. IDENTITY_FALLBACK finds zero
3. completion proof written, component manifest = H
4. AFTER scan: dim_security 某已参与 artifact 的 security_id
   identity_key_version 改成 SECURITY_IDENTITY_V1_FALLBACK
5. components 未变，manifest 仍 = H
6. validate_artifact_for_publish()
   -> proof contract matches
   -> producer matches
   -> component manifest matches
   -> persisted IDENTITY_FALLBACK findings 仍为 0
   -> check 可继续 PASS
```

但当前 authoritative input 已经包含 fallback identity。

即：

```text
stale governed proof
-> false PASS
```

## 2.3 可复现错误路径 B：blocking DQ fact 在 scan 后变化

当前代码允许：

```text
1. governed scan genuinely runs
2. BLOCKING_DQ finds zero
3. completion proof written, component manifest = H
4. AFTER scan: 同一 data_snapshot_id 的 canonical fact table
   新增/变更 quality_flags = STALE_WINDOW（或其它 blocking flag）
5. feature components 未变，manifest 仍 = H
6. validator 继续只比较 H + contract + producer
7. old meta_artifact_dq_finding 仍为 0
8. BLOCKING_DQ_ZERO 可继续 PASS
```

这直接违反：

```text
validation truth must describe CURRENT authoritative input
```

## 2.4 可复现错误路径 C：artifact 重绑 snapshot，但 components 不变

`run_required_artifact_dq_scan()` 当前在 `BEGIN TRANSACTION` **之前**先读取：

```text
artifact.data_snapshot_id
components
scanned_component_manifest_hash
```

然后才 `BEGIN TRANSACTION` 并运行 checker。

Phase 0 的 DB ownership 只保证 **跨进程独占**；同一 process 可以存在多个同模式 connection。因此另一个同进程 connection 理论上可在 pre-read 与 `BEGIN` 之间改变 registry。

更直接的无并发版本：

```text
scan 在 snapshot S1 下完成，component manifest = H
-> 后续 artifact.data_snapshot_id 改为 S2
-> S1/S2 使用同一 feature components，H 不变
-> old proof 仍满足 component-manifest comparison
-> validator DATA_SNAPSHOT_BINDING 只检查 CURRENT S2 是 DATA_VALIDATED
-> proof 本身没有字段证明 BLOCKING_DQ 当时扫的是 S1 还是 S2
```

因此 `scanned_component_manifest_hash` 无法替代 `scanned data-snapshot / checker input identity`。

---

# 3. R4-B2.3 必须解决的核心：Checker-Specific Authoritative Input Fingerprint

不要重写 scanner architecture；在现有 static registry + governed boundary 上增加 **input seal**。

推荐结构：

```text
ArtifactDQCheckerSpec
  check_id
  checker_version
  evaluator
  input_fingerprint   # production-owned / checker-specific

BEGIN TRANSACTION
  resolve CURRENT artifact + data_snapshot + components
  compute current component manifest

  for each static checker:
    compute authoritative_input_hash from the SAME current inputs
    execute evaluator against those inputs
    persist findings
    write completion proof LAST:
      component_manifest_hash
      data_snapshot_id (when applicable / recommended explicit)
      authoritative_input_hash
      scan contract / checker producer
COMMIT
```

然后：

```text
validate_artifact_for_publish
  -> recompute CURRENT checker authoritative-input fingerprint
  -> compatible proof requires:
       current contract
       current producer/checker
       current component manifest
       current authoritative_input_hash
  -> mismatch => NOT_TESTABLE / rescan required
```

并且 validation report / publish final recheck 必须确保 DQ input seal 没有在 validation 后再次变旧：

```text
scanner proof input seal
  -> validation report seal
  -> publish transaction current-input recheck
```

不能只在 validator 时比较一次，否则：

```text
validation PASS
-> DQ authoritative input changes
-> publish still trusts old validation report
```

仍存在 stale PASS。

---

# 4. Authoritative Input Fingerprint 最低要求

实现形式可调整，但必须可机器重算、稳定、provider/machine independent、不能由 caller 提交。

## 4.1 IDENTITY_FALLBACK checker

推荐 fingerprint 至少覆盖：

```text
current component manifest hash
+ exact security_id set read from components
+ for every security_id:
    current dim_security.identity_key_version
    OR explicit MISSING marker
```

可用 sorted canonical JSON → SHA-256。

这样：

```text
identity_key_version change
security registration removed/added
artifact security_id set change
```

都会使 old proof stale。

## 4.2 BLOCKING_DQ checker

fingerprint 至少覆盖：

```text
current artifact.data_snapshot_id
+ checker actually读取的 quality_flags input state
```

推荐不要对无关列做昂贵全表 hash；只需要 seal **影响 evaluator 结果的输入**。

例如对每个事实表、目标 snapshot 做稳定聚合：

```text
(table_name, quality_flags, row_count)
ORDER BY table_name, quality_flags
```

把 NULL/empty 语义按 evaluator 当前规则规范化，再 canonical JSON → SHA-256。

如果项目已有一个**被机器强制不可变、且能够证明与这些 canonical fact quality_flags 完全同源的 snapshot/fact seal**，也可以复用；但必须给出代码级 equality chain，不能仅因为 `data_snapshot_id` 字符串相同就假设 fact rows 不会变化。

## 4.3 Fingerprint 必须与 evaluator 使用同一语义

禁止：

```text
fingerprint 看 A
checker 实际看 B
```

最好把 checker-specific input resolution / fingerprint / evaluation 封装在同一 production-owned spec/implementation 中，防止两套逻辑逐渐漂移。

---

# 5. Scan Transaction 顺序必须按原要求真正闭合

当前 scanner：

```text
read artifact snapshot
read components
compute scanned_manifest
BEGIN TRANSACTION
run evaluators
write proofs
```

下一批必须改成：

```text
BEGIN TRANSACTION
  read CURRENT artifact snapshot
  read CURRENT components
  compute input identities/fingerprints
  run evaluator
  persist findings
  write proof LAST
COMMIT
```

可以在事务外做纯参数格式 fail-fast，但任何会进入 completion correctness identity 的 DB read 都必须发生在 governed transaction 内。

建议增加类似 publish B2.1 的 AST/order guard：

```text
run_required_artifact_dq_scan() 中
first conn.execute == BEGIN TRANSACTION
BEGIN precedes artifact/component authoritative reads
```

（如 DuckDB API 具体实现需要其它形式，可等价实现，但不得信任事务前读取的 snapshot/components 作为 proof identity。）

---

# 6. Persisted Schema / Contract 建议

如果沿现有 migration 012 表扩展，使用新的 migration，例如 013；不得修改旧 migration。

建议新增（名称可调整）：

```text
meta_artifact_check_execution.authoritative_input_hash
meta_artifact_check_execution.scanned_data_snapshot_id   # 推荐显式记录，便于审计
```

如果不同 checker 的输入类型不同，`authoritative_input_hash` 可作为统一 checker-specific seal。

同时 validation report 应纳入：

```text
DQ check_id
execution_id (recommended)
scan_contract_version
producer/checker identity
authoritative_input_hash
scanned component manifest
scanned data_snapshot_id when applicable
```

validation contract hash/version 应因新增 correctness seal 正式演进；legacy completion/validation 缺少 input seal时 fail closed / rescan+revalidate，不得 grandfather。

---

# 7. 必须增加的对抗测试

至少新增以下测试：

```text
1. scanner BEGIN precedes authoritative artifact/snapshot/component DB reads

2. genuine zero IDENTITY_FALLBACK scan
   -> scan 后把参与 artifact 的 security_id 改成 FALLBACK
   -> old completion proof is stale
   -> validation NOT_TESTABLE / rescan required
   -> publish BLOCK

3. genuine zero IDENTITY_FALLBACK scan
   -> scan 后删除参与 artifact 的 dim_security row
   -> old proof stale / BLOCK

4. genuine zero BLOCKING_DQ scan
   -> scan 后对 SAME data_snapshot_id 插入 STALE_WINDOW quality flag
   -> old proof stale
   -> validation/publish BLOCK

5. scan on snapshot S1
   -> artifact rebind to DATA_VALIDATED S2 while feature components unchanged
   -> old BLOCKING_DQ proof cannot transfer
   -> NOT_TESTABLE / rescan required

6. validation PASS
   -> AFTER validation, mutate identity-registry checker input
   -> publish transaction final recheck BLOCK

7. validation PASS
   -> AFTER validation, mutate blocking-DQ quality_flags input
   -> publish transaction final recheck BLOCK

8. authoritative_input_hash tamper / missing / stale
   -> fail closed

9. old execution row without new input seal
   -> NOT_TESTABLE / rescan required

10. rescan after authoritative input change
    -> new fingerprint generated internally
    -> real finding persists -> validation FAIL

11. genuine zero inputs unchanged from scan through publish
    -> validation + publish PASS

12. existing R4-B2.2 scanner ownership / actual-finding / failure tests remain green

13. existing R4-B2.1 full-seal / transaction / URI tests remain green

14. full CI matrix green
```

---

# 8. 继续冻结的现有合同

本批只增加 DQ authoritative-input freshness seal；不得借机重写：

```text
R4-B2.2 governed scanner API shape / static checker registry
R4-B2.2 actual identity/blocking-DQ evaluator semantics（除 input fingerprint 共用解析所必需）
R4-B2.1 full validation seal consumption
R4-B2.1 publish transaction-internal preconditions
R4-B2.1 logical-URI confinement
R4-B2.1 manifest honest-name semantics
B2 formal validation boundary / no caller counts
append-only validation history / deterministic latest head
atomic republish rollback / exact artifact_validation_id binding
R4-B1 exact endpoint proof / approval anti-bypass
R4-A3 runtime early-stop / positive production identity
R4-A2.x / CR-1.x evidence / replay / lineage contracts
```

Production P0-M-1B 继续独立 BLOCKED。

---

# 9. CI / Governance 当前事实

Reviewer 正向确认：

```text
R4-B2.2 implementation 281a39b6cbf421ed509711f02338c39fb74cf8ea
  CI run 33360372756 = success

current reviewed HEAD 1fc6d2329a6f185c320e0805068586d394cba20e
  CI run 33360745179 = success
  Ubuntu Python 3.14 = success
  Windows Python 3.12 = success
  Windows Python 3.14 = success
  Ruff / format / Mypy / Pytest / Spike gates = success
  Windows 3.14 DEVLOG + management governance gates = success
```

因此本轮 REOPENED 不是 CI blocker，而是 current tests 尚未覆盖“authoritative input 在 genuine scan 后发生变化”的 stale-proof adversarial case。

当前管理总册保持：

```text
R4-B2.2 DONE / PENDING_REVIEW
CR-2 BLOCKED_BY_R4-B2.2
```

没有提前自我 VERIFIED，治理态度正确。

下一开发提交必须 append-only 同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
docs/adr/ADR-021_publish_validation_exactness.md Amendment
本 Reviewer requirement 的 implementation mapping
```

ADR-021 继续保留历史，不删除 Amendment F；新增 correction 说明：

```text
R4-B2.2 closed caller-asserted completion,
but component-only completion seal did not cover all actual checker inputs;
R4-B2.3 closes checker-specific authoritative-input freshness through publish.
```

---

# 10. R4-B2.3 Exit Gate

只有以下全部成立，Reviewer 才直接关闭整个 B2 链：

```text
[ ] R4-B2.2 caller-facing completion writer remains absent
[ ] governed static scanner remains the only production completion writer
[ ] scanner BEGIN precedes authoritative correctness reads
[ ] checker input identity/fingerprint is computed internally, never caller-supplied
[ ] IDENTITY_FALLBACK proof seals current identity-registry state relevant to scanned securities
[ ] BLOCKING_DQ proof seals current snapshot + quality_flags state actually used by evaluator
[ ] completion proof carries machine-verifiable authoritative-input seal
[ ] validator recomputes current input seal and rejects stale/missing/legacy proof
[ ] validation report binds exact DQ execution/input seal
[ ] publish transaction final recheck rejects DQ input changes after validation
[ ] identity change after scan cannot inherit old zero PASS
[ ] blocking quality-flag change after scan cannot inherit old zero PASS
[ ] snapshot rebind with unchanged feature components cannot inherit old DQ proof
[ ] genuine unchanged zero scan still PASSes
[ ] actual finding still FAILs and is persisted before completion
[ ] scanner failure still writes no completion
[ ] B2.1 full seal / transaction / URI / atomic rollback remain intact
[ ] R4-B1/A3/A2/CR-1 frozen contracts show no regression
[ ] migration-from-zero / upgrade path green if schema changes
[ ] full required CI matrix green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR-021 match runtime truth
```

Exit 后直接：

```text
R4-B2 / B2.1 / B2.2 / B2.3 -> VERIFIED / CLOSED / FREEZE
ADR-021 -> ACCEPTED（若 governance 约定允许 Reviewer closure 时接受）
CR-2 Provider-Normalized + Quarantine -> START
Production P0-M-1B -> remains BLOCKED independently
```

本批不得提前启动 CR-2 主实现。