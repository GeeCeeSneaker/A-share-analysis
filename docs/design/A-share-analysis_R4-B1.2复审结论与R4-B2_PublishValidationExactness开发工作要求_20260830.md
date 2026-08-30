# A-share-analysis：R4-B1.2 复审结论与 R4-B2 Publish Validation Exactness 开发工作要求

> **Review Date**：2026-08-30 18:01 +08:00  
> **Reviewed Repository HEAD**：`aacd107efb4856a726035eb816d58616dee32cdc`  
> **Primary R4-B1.2 Implementation**：`261f5967cbd639ce9dd6fe3c8fa2c1abe5f649b4`  
> **R4-B1.2 CI Fix**：`135298fd670e85a4e0b8b53e10c9117981220137`（tests-only import fix）  
> **Previous Reviewer Requirements**：`6a0a54b05fe7f63b5190b1df7c315bca43394963` + governance correction `dd33d74a9907ab4e4b9d5ad8b1584872a1fb3463`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**VERIFIED**  
> **R4-B1 / R4-B1.1 / R4-B1.2**：**VERIFIED / CLOSED / FREEZE**  
> **R4-A3.x**：**CLOSED / VERIFIED / FREEZE**  
> **R4-A2.x / CR-1.x**：**CLOSED / VERIFIED / FREEZE**  
> **Next Batch**：**R4-B2 Publish Validation Exactness**  
> **CR-2**：**BLOCKED / sequenced after R4-B2**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

R4-B1.2 的两个最终 blocker 已全部闭合，本轮不再创建 R4-B1.3。

```text
VERIFIED  Approval Anti-Bypass：生产 src 不再存在绕过 formal-run 验证即可写 APPROVED 的 callable helper / verified object
VERIFIED  APPROVED transaction 已 inline 到 approve_from_spike_run 完整验证链之后
VERIFIED  tests-only persistence mechanics 已迁出 src，生产代码不 import tests
VERIFIED  industry_taxonomy:InfoData.get_industry_constituent = REQUIRED_ENDPOINT_PROOF
VERIFIED  industry base_info PASS + constituent DENIED -> ENDPOINT FAIL -> BUSINESS fired == 0
VERIFIED  constituent success/failure exchange 走 exact endpoint + RawWriter persisted evidence
VERIFIED  canonical-deliverable required-surface guard 已覆盖 multi-endpoint capability
VERIFIED  B1.1 四层 identity cross-binding 保持无回归
VERIFIED  security_master historical endpoint / sdk_methods classification 保持无回归
VERIFIED  current HEAD full CI matrix green
```

因此正式状态：

```text
R4-B1   -> VERIFIED / CLOSED
R4-B1.1 -> VERIFIED / absorbed into B1 closure
R4-B1.2 -> VERIFIED / CLOSED
R4-B2   -> START / ACTIVE NEXT
```

除真实可复现 regression，不再回头重审 B1 exact endpoint proof / approval boundary。

---

# 1. R4-B1.2 Verification Detail

## 1.1 Approval Anti-Bypass —— VERIFIED / FREEZE

生产模块 `src/ashare_state/providers/amazingdata/capability.py` 已删除 R4-B1.1 中仍可显式 import 的绕过面：

```text
_approve_capability_in_memory_testonly
_approve_and_persist_capability_testonly
VerifiedCapabilityApproval
_persist_verified_capability
```

生产侧唯一写 `APPROVED` 的控制流是：

```text
approve_from_spike_run(...)
  -> load CLOSED PRODUCTION run
  -> provenance_complete
  -> exact frozen production account identity
  -> capability verdict PASS
  -> formal runtime gate proof
  -> endpoint requirement exact identity cross-binding
  -> golden refs validated
  -> build evidence FROM run facts
  -> validate evidence
  -> SAME FUNCTION inline DB transaction writes APPROVED
  -> commit
  -> cache rebuild from DB
```

这里的关键点不是函数名是否带 `_`，而是**写入点与验证链处在同一控制流中，没有独立 callable persistence boundary 可以接收 caller-built evidence / caller-built verified object**。

测试所需 transaction/cache mechanics 已移到 `tests/integration/_capability_test_persistence.py`；AST guard 同时验证 production `src` 不 import tests。

本项 CLOSED / FREEZE。

## 1.2 Industry Endpoint Necessary Surface —— VERIFIED / FREEZE

`industry_taxonomy` 当前 canonical deliverable 为：

```text
bridge_industry_member
```

因此必要 endpoint surface 已修正为：

```text
InfoData.get_industry_base_info       REQUIRED
InfoData.get_industry_constituent     REQUIRED
InfoData.get_industry_weight          OPTIONAL_NON_APPROVAL_SURFACE
InfoData.get_industry_daily           OPTIONAL_NON_APPROVAL_SURFACE
```

`get_industry_constituent_exchange` 已进入 provider / target / exact formal probe boundary。

关键对抗事实：

```text
base_info PASS
constituent DENIED
-> ENDPOINT_AVAILABLE FAIL
-> failure exchange persisted
-> constituent proof case VALIDATED_FAIL
-> BUSINESS_DATA fired == 0
-> capability approval impossible
```

新增 canonical-deliverable guard 还把 multi-endpoint capability 的 REQUIRED surface 明确 pin 成可审计设计事实，避免以后重新出现“全部 sdk_methods 都有分类，但真正必要 endpoint 被错误分成 optional”的形式合规问题。

本项 CLOSED / FREEZE。

## 1.3 CI —— VERIFIED

Reviewer 正向核验：

- implementation + tests-only CI fix HEAD `135298fd670e85a4e0b8b53e10c9117981220137`：GitHub Actions run `33302154703` = **success**；
- current reviewed HEAD `aacd107efb4856a726035eb816d58616dee32cdc`：GitHub Actions run `33302355795` = **success**；
- 两个 run 均为：
  - Ubuntu / Python 3.14 success
  - Windows / Python 3.12 success
  - Windows / Python 3.14 success
  - Ruff lint success
  - Ruff format check success
  - Mypy success
  - Pytest success
  - Spike framework gates success
  - Windows 3.14 governance gates success

主实现 `261f596...` 首轮 CI 曾因 tests helper 的 Python import path 产生 collection ImportError，随后 `135298f...` 仅在 tests 范围修正导入；当前实现链与 current HEAD 均全矩阵 green，未通过删测试/弱化 gate 方式修复。

---

# 2. R4-B2 为什么现在必须做

B1 解决的是：

```text
"这个 capability 的必要 provider endpoint 是否被真实、精确、持久化地证明可用？"
```

B2 必须解决的是：

```text
"什么证据足以把一个 feature artifact set 判定为真正可发布，
并保证 publish 消费的是 exact validated artifact，而不是 caller 自报 PASS？"
```

当前 `pipeline/publish.py` 仍有一个与 B1 早期 approval bypass 同构的结构问题：

```python
record_artifact_validation(
    feature_artifact_set_id=...,
    validation_version=...,
    identity_fallback_count=0,
    blocking_dq_count=0,
    ...
)
```

函数直接把 caller 提交的两个计数写进 append-only validation ledger；它**没有自己执行 artifact validation**。

随后 `publish_snapshot()` 取该 artifact set 的 latest validation record，只要：

```text
identity_fallback_count == 0
blocking_dq_count == 0
```

就可通过 publish validation gate。

所以目前仍存在：

```text
caller self-declare "0 fallback / 0 blocking DQ"
-> validation ledger PASS-shaped record
-> publish eligible
```

`meta_artifact_validation` append-only + publish 绑定 exact `artifact_validation_id` 是已有正确基础，应 FREEZE；B2 不是推倒 ledger，而是让 ledger 中的 PASS **只能由真实 validator 对 exact artifact identity 计算产生**。

---

# 3. R4-B2-01：Formal Artifact Validation Execution Boundary（P0）

必须建立唯一正式 artifact validation 边界，例如：

```text
validate_artifact_for_publish(...)
  -> resolve artifact metadata
  -> resolve exact component manifest
  -> verify artifact/component bytes + metadata identity
  -> execute typed required checks
  -> derive findings/counts FROM checks
  -> persist validation proof
  -> return artifact_validation_id
```

名称可调整，但契约必须满足：

1. production publish-validation path 不接受 caller 直接提交 `identity_fallback_count` / `blocking_dq_count` 作为真相；
2. 两个 count 必须是 validator 输出的派生值，而不是函数输入；
3. 不允许 production caller 自行构造一个 "ValidatedArtifact" / "PASS result" 再交给 persistence helper 绕过 validator；
4. 测试 fixture 可在 tests 中直接准备 ledger rows，但 production src 不得保留“无需真实 validation 即可记录 PASS”的 callable；
5. `record_artifact_validation()` 若继续存在于 production API，必须变成 validator 内部 persistence primitive，不能继续作为 caller-facing PASS writer。

推荐结构：

```text
ArtifactValidationContract
        ↓
ArtifactValidator
        ↓
ArtifactValidationReport (derived, not caller asserted)
        ↓
private/internal ledger persist in SAME governed control flow
```

不要重复 B1.1 的错误：下划线命名或普通 dataclass 不是不可伪造边界。

---

# 4. R4-B2-02：Typed Publish Validation Contract（P0）

当前 publish gate 只有两个 aggregate count，无法证明“required checks 是否全部执行”。

必须建立 typed check contract，至少区分：

```text
ARTIFACT_MANIFEST_INTEGRITY
COMPONENT_EXISTENCE
COMPONENT_CONTENT_HASH
COMPONENT_SCHEMA_HASH
COMPONENT_ROW_COUNT
FEATURE_FAMILY_COVERAGE
FEATURE_SET_VERSION_MATCH
DATA_SNAPSHOT_BINDING
IDENTITY_FALLBACK_ZERO
BLOCKING_DQ_ZERO
```

可根据现有数据结构合并/拆分，但必须满足：

- 每个 required check 有稳定 `check_id`；
- status 至少为 `PASS | FAIL | NOT_TESTABLE`（不可证明 = blocking）；
- missing required check = FAIL_CLOSED；
- unknown check 不能替代 required check；
- aggregate counts 只能是报告摘要，不能是 publish eligibility 的唯一事实；
- publish eligibility = **required check set 完整且全部 PASS**。

新增/修改 feature artifact schema 或 validation contract 时，缺少对应 validator coverage 必须测试失败，而不是默认 PASS。

---

# 5. R4-B2-03：Validation 必须绑定 Exact Artifact Identity（P0）

现有 ledger 绑定：

```text
artifact_validation_id
feature_artifact_set_id
validation_version
validator_code_commit
counts
validated_at
detail
```

但 Publish Validation Exactness 需要进一步回答：

> 这次 PASS 验证的究竟是不是现在要 publish 的那组 artifact components / bytes？

B2 validation proof 至少必须 seal：

```text
feature_artifact_set_id
artifact_manifest_hash
component_manifest_hash（由 component identity 排序稳定计算）
validation_contract_version/hash
validator_code_commit
required-check result set hash
```

component manifest 至少应覆盖：

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

是否通过新增 ledger columns、独立 validation-report artifact、或 validation manifest 表实现，可由开发方设计；但 publish 必须可以**机器重验**：

```text
validation sealed artifact identity
== current artifact registry identity
```

任何以下情况必须 BLOCK：

```text
artifact_manifest_hash changed
component added/removed
component file_uri changed
component content_hash changed
schema_hash changed
row_count changed
feature family/version changed
validation proof artifact missing/tampered
```

不能只因为 `feature_artifact_set_id` 字符串相同就继承旧 PASS。

Legacy validation rows（迁移 008/010 历史记录）若没有新的 exact seal，不得自动视为 B2-valid PASS；需要重新验证后才能用于新 publish。

---

# 6. R4-B2-04：Persisted Validation Evidence / Tamper Closure（P0）

参考 B1 的成功模式，validation report 必须有不可歧义的 persisted evidence identity。

推荐：

```text
validation/<artifact_validation_id>.json
```

包含：

```text
artifact_validation_id
feature_artifact_set_id
artifact_manifest_hash
component_manifest_hash
validation_contract_version/hash
validator_code_commit
checks[]
summary counts
validated_at
```

ledger 记录必须绑定该 report 的：

```text
report_uri
report_hash
```

publish 前重新读取并验证：

```text
sha256(report bytes) == ledger report_hash
report.artifact_validation_id == ledger id
report.feature_artifact_set_id == target artifact
report artifact/component seal == current artifact identity
required checks complete + PASS
```

report missing / tampered / wrong artifact id / wrong manifest / check set incomplete → FAIL_CLOSED。

不要让 `details_json` / free-text detail 继续承担 correctness identity。

---

# 7. R4-B2-05：Publish Gate Final Recheck / TOCTOU Closure（P0）

当前 `publish_snapshot()` 的大量 precondition read 和 latest validation selection 在 `BEGIN TRANSACTION` **之前**完成；之后才开启 publish write transaction。

B2 必须消除：

```text
precheck PASS
-> state / validation / component identity changes
-> publish transaction still commits old conclusion
```

至少应实现下列之一（推荐 A）：

### Option A — transaction 内完成 publish-critical read + final recheck

```text
BEGIN TRANSACTION
  -> resolve snapshot/artifact/run/feature-set/universe
  -> resolve current validation head
  -> verify validation proof + exact artifact seal
  -> final required-check PASS
  -> supersede old publish
  -> insert new publish bound to exact artifact_validation_id
  -> update run
  -> uniqueness guard
COMMIT
```

### Option B — precomputed immutable PublishApprovalSeal + transaction 内 exact compare

只有当 seal 本身不可伪造、并且 transaction 内重验 current state identity == seal 时才可接受。

不得仅在 transaction 外检查一遍然后信任局部变量。

同时维持已有原子 republish 契约：任何最终 gate/write 失败都 rollback，旧 PUBLISHED 继续可见。

---

# 8. R4-B2-06：Latest Validation Policy 必须机器明确（P1）

现有 append-only ledger + publish 绑定 exact `artifact_validation_id` 是 PASS / FREEZE。

B2 要明确 current-head policy：

```text
old PASS
-> later FAIL / NOT_TESTABLE
-> 不得选择旧 PASS 发布
```

如果 revalidation 后重新 PASS：

```text
old PASS
-> FAIL
-> newer PASS on SAME exact artifact identity + current validation contract
-> 可使用 newest PASS
```

不要让 caller 自行传入一个历史 PASS validation id 规避更新后的失败结果。

排序/选择规则必须 deterministic；validation timestamp 必须由系统生成，不能由 caller 自报。

---

# 9. R4-B2 Adversarial Tests（必须）

至少覆盖：

```text
1. caller 直接提交 fallback=0,dq=0 -> 无 production PASS write 路径
2. required validator check 未执行 -> validation NOT eligible
3. one required check NOT_TESTABLE -> publish BLOCK
4. component missing after validation -> publish BLOCK
5. component content_hash tamper -> publish BLOCK
6. component schema_hash tamper -> publish BLOCK
7. component row_count tamper -> publish BLOCK
8. artifact_manifest_hash mismatch -> publish BLOCK
9. validation report bytes tamper -> publish BLOCK
10. report artifact id swapped to another feature_artifact_set -> publish BLOCK
11. old PASS + newer FAIL -> old PASS cannot publish
12. legacy validation row without B2 seal -> publish BLOCK / requires revalidation
13. validation PASS then component registry changes before publish -> final recheck BLOCK
14. failure during final publish gate -> old PUBLISHED remains visible (rollback)
15. exact valid report + unchanged artifact -> publish PASS and snapshot binds exact artifact_validation_id
```

还应增加 structural/AST guard：

```text
production src 中不存在一个 callable 可以接受 caller-supplied counts/result
并在不执行 formal artifact validation 的情况下制造 publish-eligible validation record
```

---

# 10. B2 Existing Contracts to FREEZE

不得破坏：

```text
append-only meta_artifact_validation history
meta_publish_snapshot binds artifact_validation_id
at most one PUBLISHED per trade_date
atomic republish rollback
snapshot <-> artifact exact lineage
artifact <-> pipeline run exact lineage (RECOVERY exception按现有契约)
run <-> snapshot source/availability policy lineage
ACTIVE feature-set immutable definition self-check
universe registration checks
exact replay readers resolve metadata, never glob directories
R4-B1 exact endpoint proof + approval boundary
R4-A3 runtime early-stop / positive production identity
R4-A2.x / CR-1.x frozen evidence contracts
```

如 schema migration 必需，必须 migration-from-zero + upgrade-path 测试，不得修改旧 migration 文件伪造历史。

---

# 11. B2 Scope Boundary

本批只完成：

```text
Publish Validation Exactness
```

不得提前启动：

```text
CR-2 Provider-Normalized + Quarantine 主实现
CR-3 AvailabilityPolicy + Canonicalizer
CR-4 Snapshot + Read Model Rebuild
Feature / State 大规模扩展
```

允许为了 B2 validation exactness 增加：

```text
validation contract / report
validation ledger schema extension
artifact/component integrity reader
publish final-recheck executor
必要 migration + tests
```

但不要借机重写 canonical/provider architecture。

---

# 12. Governance Requirements

本批至少登记：

```text
DM-CR-20260830-054 Formal Artifact Validation Execution Boundary
DM-CR-20260830-055 Exact Artifact Validation Seal / Persisted Report
DM-CR-20260830-056 Publish Final Recheck / TOCTOU Closure
```

若 artifact validation / publish approval 成为长期合同，建议新建 **ADR-021 Publish Validation Exactness**，不要继续扩充 ADR-020（ADR-020 是 endpoint requirement contract）。

ADR 必须回答：

```text
1. 为什么 caller-supplied zero counts 不是系统 validation truth？
2. validation 如何绑定 exact artifact/component bytes identity？
3. 为什么 required check coverage 不能只靠 aggregate counts？
4. publish-critical checks 为什么必须在 transaction 内 final recheck？
5. legacy validation records 如何处理，为什么不能自动 grandfather 为 PASS？
```

记录替代方案、拒绝理由、成本收益。

必须同步：

```text
docs/DEVLOG.md（append only）
docs/project/DEVELOPMENT_MANAGEMENT.md current truth
ADR-021（若创建）/ ADR index
本工作要求 Implementation Mapping
exact implementation SHA
exact job-level CI truth
```

Reviewer 本提交是 closure / next-work 文档；下一开发提交应把 management current truth 从：

```text
R4-B1.2 DONE / PENDING_REVIEW
R4-B2 BLOCKED
```

同步为：

```text
R4-B1 / B1.1 / B1.2 CLOSED / VERIFIED / FREEZE
R4-B2 ACTIVE / IN_PROGRESS（实现完成后 DONE / PENDING_REVIEW）
CR-2 BLOCKED_BY_R4-B2
Production P0-M-1B BLOCKED independently
```

---

# 13. R4-B2 Exit Gate

只有全部满足，Reviewer 才给 R4-B2 VERIFIED：

```text
[ ] production validation PASS cannot be caller self-declared via counts/result object
[ ] one formal artifact-validation execution boundary exists
[ ] identity_fallback_count / blocking_dq_count are validator-derived, not caller inputs
[ ] required validation checks are typed and completeness-enforced
[ ] missing/NOT_TESTABLE required check blocks publish
[ ] validation binds exact feature_artifact_set_id + artifact manifest/component identity
[ ] validation report persisted and hash-bound
[ ] publish re-verifies report bytes + ledger identity + current artifact identity
[ ] changed/missing/tampered component invalidates prior PASS
[ ] legacy validation rows without exact B2 seal cannot publish without revalidation
[ ] current-head validation policy prevents choosing stale old PASS after newer FAIL
[ ] publish-critical final checks occur inside transaction / equivalent exact final seal comparison
[ ] failed final gate rolls back and preserves previous PUBLISHED
[ ] valid unchanged artifact publishes and binds exact artifact_validation_id
[ ] B1/A3/A2/CR-1 frozen contracts have zero regression
[ ] full required CI matrix green
[ ] DEVLOG / management / ADR exact runtime/SHA truth
```

满足后：

```text
R4-B2 -> VERIFIED / CLOSED
CR-2 Provider-Normalized + Quarantine -> START
```

Production P0-M-1B 仍不会因 B2 VERIFIED 自动放行。

---

# 14. Reviewer Handoff

下一轮 Reviewer 只需重点追踪：

```text
A. validation PASS 是否由 validator 对 actual artifact 计算，而非 caller assertion
B. typed required-check set 是否完整、fail closed
C. validation seal 是否精确绑定 artifact/component identity + persisted report hash
D. publish transaction 是否做 final exact recheck，消除 precheck TOCTOU
E. old PASS/new FAIL/legacy row/tamper adversarial tests
F. frozen regressions + full CI
```

除发现真实 regression，不再重开 R4-B1.x 已 VERIFIED 项。
