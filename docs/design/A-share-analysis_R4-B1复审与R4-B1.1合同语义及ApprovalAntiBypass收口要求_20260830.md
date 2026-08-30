# A-share-analysis：R4-B1 复审与 R4-B1.1 Endpoint Contract Semantics / Approval Anti-Bypass 收口要求

> **Review Date**：2026-08-30 13:02 +08:00  
> **Reviewed Repository HEAD**：`5d63295c5f9702ee3b7af927289643a653787361`  
> **Primary R4-B1 Implementation**：`b432159d3b7d5b8e1b693c7704202ea0c73f6d5b`  
> **Previous Reviewer Requirement**：`0502ac9847aba60cefe2ef0e5ac947a5fbf08aac`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **R4-A3 / A3.1 / A3.2**：**CLOSED / VERIFIED / FREEZE（不重开）**  
> **R4-A2.x / CR-1.x**：**CLOSED / VERIFIED / FREEZE（不重开）**  
> **Next Batch**：**R4-B1.1 Endpoint Contract Semantics + Approval Anti-Bypass + Persisted Identity Cross-Binding Closure**  
> **R4-B2**：**BLOCKED until R4-B1.1 VERIFIED**  
> **CR-2**：**sequenced after R4-B2**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

R4-B1 已完成大量正确的机制性建设，本轮不应推倒重做。

以下项目给 **PASS / FREEZE**：

```text
PASS  EndpointRequirement typed contract primitive
PASS  REQUIRED / ALTERNATIVE_GROUP 显式 mode primitive
PASS  ENDPOINT_PROBE_SPECS keyed by requirement_id
PASS  formal ENDPOINT gate 对 envelope.endpoint + provider_dataset 做 exact-match
PASS  unrelated stand-in exchange -> blocking FAIL
PASS  endpoint ProviderError.exchange 仍走 RawWriter persisted evidence
PASS  endpoint persistence failure保持 A3.2 atomic fail-closed
PASS  per-requirement endpoint proof case
PASS  hash-anchored capability gate REPORT artifact
PASS  approve_from_spike_run 已开始消费 endpoint requirement artifact
PASS  provider/target 新增 BJ mapping / equity structure / industry base info exact exchange surface
PASS  R4-A3.x persistence early-stop / positive production identity 无回归
PASS  current HEAD CI full matrix green
```

但 R4-B1 Exit Gate 尚不能通过。当前存在 **3 个 P0 blocker + 1 个 P1 governance correction**：

```text
P0-01  Endpoint Requirement Contract 的“业务必要性语义”存在错误/未闭合：
       security_master 把 current snapshot 与 historical rebuild 错当 official alternatives；
       ADR-020 对 adj_factor 两端点“各自 REQUIRED”的表述与代码合同直接矛盾；
       registry 中其它多 endpoint capability 也没有逐项显式说明为何纳入/排除 proof contract。

P0-02  Capability approval 仍存在 caller-self-declare 绕过路径：
       approve_and_persist_capability() / approve_capability() 不消费 formal endpoint proof，
       可以直接用 CapabilityEvidence 把 capability 置为 APPROVED。

P0-03  approval 的 exact identity cross-binding 不完整：
       REPORT re-check 未核验 provider_dataset / actual_dataset exactness，
       未要求 endpoint proof case evidence_ref/hash == REPORT entry evidence_uri/hash，
       也未从 persisted Raw meta 反向重验 request_id / endpoint / provider_dataset。

P1-01  ADR-020 在 Reviewer 复审前写为 ACCEPTED 且把“Design / Audit Review”列为 Decider，
       同时含有与代码不一致的 endpoint requirement 结论，需要 amendment/correction，保留历史。
```

因此：

```text
R4-B1 = DONE / REOPENED
R4-B1.1 = ACTIVE NEXT
R4-B2 = BLOCKED
```

本轮不要启动 R4-B2。

---

# 1. 已通过并冻结：Exact Endpoint Proof Engine

## 1.1 typed primitive —— PASS / FREEZE

保留：

```text
EndpointRequirement
EndpointRequirementMode.REQUIRED
EndpointRequirementMode.ALTERNATIVE_GROUP
ProofRole
requirement_id
endpoint
provider_dataset
group_id
```

问题不在 primitive，而在**当前表里的 requirement 语义是否正确、完整、可追溯**。

## 1.2 exact-match execution —— PASS / FREEZE

保留 `_ExactEndpointRequirementsGate` 的核心结构：

```text
requirement
-> exact probe factory
-> ProviderExchange
-> RawWriter persist
-> envelope.endpoint exact-match
-> envelope.provider_dataset exact-match
-> GateStatus PASS/FAIL
```

stand-in endpoint 返回 OK 也必须 FAIL；这一点已经正确。

## 1.3 A3 structural early-stop —— PASS / FREEZE

endpoint gate blocking 后 BUSINESS probe 不得 fire；RawWriter persistence failure 必须在 gate evaluation 内即时 FAIL。当前结构继续冻结。

---

# 2. P0-01：Endpoint Requirement Contract 语义不正确 / 不完整

## 2.1 security_master 的 ALTERNATIVE_GROUP 与项目自己的 core capability 冲突

当前 ADR-020 / contract 声称：

```text
BaseData.get_code_list
BaseData.get_hist_code_list
```

是 `security_master` 的“官方替代”，任一可用即可证明 ENDPOINT_AVAILABLE。

但项目正式 Spike capability 明确是：

```text
security_master_with_delisted
```

核心目标：

```text
master must contain delisted securities (survivorship)
```

现有 B2 正式语义 probe 也明确调用：

```text
BaseData.get_hist_code_list(...)
```

并用它验证 delisted/survivorship。

更关键的是，新测试明确允许：

```text
get_code_list PASS
get_hist_code_list DENIED
-> ENDPOINT_AVAILABLE PASS
-> BUSINESS_DATA 再因 hist fetch 失败而 FAIL
```

这证明当前 endpoint contract 本身是过弱的，靠 BUSINESS gate 在后面兜底。

这违反 B1-03：

```text
PERMISSION != ENDPOINT_AVAILABLE != BUSINESS_DATA
```

**强制修复**：

`security_master_with_delisted` 所需要的 historical listing endpoint 必须在 ENDPOINT contract 本身被正确表达。推荐：

```text
BaseData.get_hist_code_list = REQUIRED
```

`get_code_list` 如果只是 current snapshot / permission / convenience surface，可：

```text
- 不作为 security_master endpoint requirement；或
- 以明确的非批准角色记录（如果后续需要扩展 role model）
```

但不得继续让 `get_code_list` 单独使 `security_master` 的 ENDPOINT gate PASS。

新增对抗测试：

```text
get_code_list PASS + get_hist_code_list DENIED
-> ENDPOINT_AVAILABLE FAIL
-> BUSINESS probe fired == 0
-> capability approval impossible
```

## 2.2 ADR-020 与 adj_factor contract 直接矛盾

ADR-020 明确写：

```text
get_adj_factor 与 get_backward_factor 是不同数据流
不得编组
各自 REQUIRED
```

但当前 `ENDPOINT_REQUIREMENTS` 只有：

```text
adj_factor:BaseData.get_adj_factor
```

没有：

```text
BaseData.get_backward_factor
```

必须二选一并把当前真相说清楚：

### Option A（若两者确实都是 capability 必要 surface）

```text
两者都 REQUIRED
+ exact probe
+ persisted proof
+ approval consumption
```

### Option B（若 backward_factor 不是当前 capability approval 的必要条件）

```text
从 ADR-020 的“各自 REQUIRED”撤回
明确说明 sdk_methods 中它只是 optional/documented/business alternative
并建立 typed classification，避免以后再次由 reviewer 猜测
```

不得保持“ADR REQUIRED / runtime contract 不要求”的双重真相。

## 2.3 所有 registry sdk_methods 必须显式 reconcile，不允许“合同只覆盖 capability 名称”

当前结构守卫只证明：

```text
contract capability keys == registry capability keys
```

它没有证明 registry 中每个 `sdk_methods` 的语义已经被明确处理。

至少需要逐项 reconcile：

```text
security_master:
  get_code_list
  get_hist_code_list
  get_stock_basic

adj_factor:
  get_adj_factor
  get_backward_factor

industry_taxonomy:
  get_industry_base_info
  get_industry_constituent
  get_industry_weight
  get_industry_daily

index_daily:
  get_index_daily
  query_kline
```

不是要求机械地把所有 method 都标 REQUIRED；要求**每个 method 有显式分类与理由**，例如：

```text
REQUIRED_ENDPOINT_PROOF
ALTERNATIVE_GROUP_MEMBER
OPTIONAL / NON_APPROVAL_SURFACE
BUSINESS_SEMANTIC_ONLY
DEPRECATED / NOT_USED
```

名称可调整，但不能再出现：

```text
registry 声明了多个 method
-> contract 静默漏掉其中若干
-> 仅靠开发者注释解释
```

建议让结构测试验证：

```text
set(registry.sdk_methods)
== set(all explicitly classified method identities for that capability)
```

这样新增/删除 SDK method 时必须同步 contract decision。

---

# 3. P0-02：Capability Approval 仍可绕过 formal endpoint proof

## 3.1 当前 bypass

B1 将 exact endpoint artifact re-check 放进：

```text
approve_from_spike_run()
  -> _require_formal_gate_proof(...)
```

这是正确方向。

但仓库仍存在公开路径：

```text
approve_and_persist_capability(conn, name, CapabilityEvidence)
approve_capability(name, CapabilityEvidence)
```

它们只调用：

```text
_validate_evidence()
```

`_validate_evidence()` 只验证：

```text
字段非空
capability 非 RETIRED
positive frozen production account identity
```

并不验证：

```text
closed formal production run
formal gate proof
exact endpoint requirements
REPORT artifact
Raw evidence identity
```

随后即可写 DB `status='APPROVED'` 或直接把内存 registry 置 APPROVED。

因此“caller self-declare CapabilityEvidence”仍然可以绕开 B1 exact endpoint proof。

这与 B1 的核心目标冲突：

> Capability Approval 不能接受 caller self-declare；必须由 formal production run 的 persisted evidence 推导。

## 3.2 强制修复

生产可达的 APPROVED transition 必须只有一个不可绕过来源。

推荐结构：

```text
approve_from_spike_run(...)
  -> verify production run
  -> verify evidence closure
  -> verify capability verdict
  -> verify exact endpoint proof + Raw identity
  -> build VerifiedCapabilityApproval / sealed internal proof object
  -> private persistence function
```

然后：

```text
_persist_verified_capability(...)
```

只接受内部 verified object，而不是 caller 构造的 `CapabilityEvidence`。

现有：

```text
approve_and_persist_capability
approve_capability
```

如果仅为测试需要：

```text
- 改为 private/test helper；或
- 明确限制到 test-only code path；或
- 让它们也必须消费不可伪造的 verified proof object
```

禁止继续存在“传几个字符串即可 APPROVED”的 production-reachable API。

Required tests：

```text
[ ] direct approve_and_persist_capability + fabricated CapabilityEvidence -> cannot APPROVE
[ ] direct approve_capability + fabricated CapabilityEvidence -> cannot make production gate see APPROVED
[ ] only approve_from_spike_run / verified proof transition can persist APPROVED
[ ] failed endpoint requirement -> no alternate public approval function can bypass
[ ] DB and in-memory cache remain authoritative/consistent after rejected bypass
```

不要削弱既有 positive production identity；它只是必要条件，不是 endpoint proof 的替代品。

---

# 4. P0-03：Approval 未把 contract / case / REPORT / Raw meta 完整 cross-bind

## 4.1 当前已做部分

当前 `_require_formal_gate_proof()` 已：

```text
- re-hash gates/{cap}.json against REPORT case hash
- check expected_endpoint == contract endpoint
- PASS entry actual_endpoint == contract endpoint
- require evidence_uri/hash nonempty
```

这些保留。

## 4.2 当前缺口

当前 approval re-check **没有**验证：

```text
entry.provider_dataset == contract.provider_dataset
entry.actual_dataset == contract.provider_dataset
```

也没有要求：

```text
endpoint proof case.evidence_ref  == REPORT entry.evidence_uri
endpoint proof case.evidence_hash == REPORT entry.evidence_hash
```

更没有打开 persisted Raw meta，反向验证：

```text
Raw meta request_id        == REPORT entry.request_id
Raw meta endpoint          == contract.endpoint
Raw meta provider_dataset  == contract.provider_dataset
Raw meta identity/hash     == case/report binding
```

因此目前可以构造：

```text
actual_endpoint = 正确 endpoint
actual_dataset  = 错误 dataset
REPORT hash 重新绑定
```

approval 仍可能通过。

也可以把 REPORT entry 的 evidence_uri/hash 改成另一份非空 evidence，只要 re-bind REPORT hash；case 与 artifact 之间没有 identity equality check。

这不满足 B1-04 要求：

```text
capability requirement
<-> proof case
<-> ProviderExchange envelope endpoint/provider_dataset
<-> persisted evidence URI/hash
```

## 4.3 强制修复

对每一个被用于满足 requirement 的 PASS proof，approval 至少重验：

```text
case.case_id == endpoint_requirement_case_id(req)
case.result == PASS
case.evidence_ref == entry.evidence_uri
case.evidence_hash == entry.evidence_hash

entry.requirement_id == req.requirement_id
entry.capability == req.capability
entry.expected_endpoint == req.endpoint
entry.actual_endpoint == req.endpoint
entry.provider_dataset == req.provider_dataset
entry.actual_dataset == req.provider_dataset
entry.status == PASS
entry.request_id nonempty

persisted raw meta at entry.evidence_uri:
  bytes hash == entry.evidence_hash
  request_id == entry.request_id
  endpoint == req.endpoint
  provider_dataset == req.provider_dataset
```

Raw meta 读取应复用已有 run-store/evidence parser，不要新造第二套 lineage 解析。

ALTERNATIVE_GROUP：只需要对真正用于满足 group 的 PASS member 做完整 cross-bind，但失败成员不能伪装成满足者。

Required adversarial tests（均在 REPORT hash 重新绑定后仍要拒绝）：

```text
[ ] actual_dataset tamper -> approval BLOCK
[ ] provider_dataset tamper -> approval BLOCK
[ ] REPORT evidence_uri 换成 permission/business evidence -> BLOCK
[ ] REPORT evidence_hash 换成另一份合法 hash -> BLOCK
[ ] endpoint proof case evidence_ref 与 REPORT entry 不一致 -> BLOCK
[ ] endpoint proof case evidence_hash 与 REPORT entry 不一致 -> BLOCK
[ ] Raw meta endpoint tamper / mismatch -> BLOCK
[ ] Raw meta provider_dataset mismatch -> BLOCK
[ ] Raw meta request_id mismatch -> BLOCK
```

---

# 5. P1-01：ADR-020 governance correction

当前 ADR-020：

```text
Status: ACCEPTED
Deciders: Design / Audit Review + 开发方
```

但这是开发方在本轮 Reviewer 正式复审之前写入的状态，且其中：

```text
security_master official alternative
adj_factor 两 endpoint 各自 REQUIRED
```

至少一项与项目 core capability 冲突，一项与代码合同直接不一致。

下一批不要删除 ADR-020 历史。采用 amendment/correction：

```text
- 记录 R4-B1 reviewer REOPENED
- 修正 endpoint semantic table
- 修正/解释 method classification
- 不再把未经 Reviewer 复核的结论表述为 Reviewer 已决策事实
```

ADR status 按项目既有治理约定处理；关键是不能 overclaim。

---

# 6. CI 裁决

Reviewer 正向确认：

```text
R4-B1 implementation
  commit = b432159d3b7d5b8e1b693c7704202ea0c73f6d5b
  Actions run = 33179092630
  conclusion = success

Current reviewed HEAD
  commit = 5d63295c5f9702ee3b7af927289643a653787361
  Actions run = 33179456562
  conclusion = success
```

current HEAD job-level：

```text
Windows / Python 3.12  SUCCESS
Windows / Python 3.14  SUCCESS
Ubuntu  / Python 3.14  SUCCESS

Ruff lint             SUCCESS
Ruff format           SUCCESS
Mypy                  SUCCESS
Pytest                SUCCESS
Spike framework gates SUCCESS
```

因此 CI 本身不是 blocker。

但现有绿灯包含：

```text
test_alternative_group_single_member_pass_is_pass
```

它把当前错误的 security_master endpoint semantics 固化成测试预期；所以下一批修正 contract 后，该测试应被改写，而不是为了维持 779/0 保留错误语义。

---

# 7. R4-B1.1 实施顺序

```text
Batch A — Endpoint Semantic Reconciliation
  reconcile every registry sdk_method
  fix security_master historical requirement
  resolve adj_factor ADR/code contradiction
  classify industry/index/security-master extra methods explicitly

Batch B — Approval Anti-Bypass
  one production-reachable APPROVED transition
  caller CapabilityEvidence cannot self-declare approval
  verified internal proof object / private persistence boundary

Batch C — Persisted Identity Cross-Binding
  contract <-> case <-> REPORT <-> Raw meta exact equality
  endpoint + dataset + request_id + URI/hash all reverified

Batch D — Adversarial Regression
  security-master hist denied
  direct approval bypass
  dataset/evidence/raw-meta tamper
  A3/A2/CR-1 regressions

Batch E — Governance
  DEVLOG append
  DEVELOPMENT_MANAGEMENT current truth
  ADR-020 amendment/correction
  exact SHA + job-level CI truth
```

---

# 8. R4-B1.1 Exit Gate

只有全部满足才能给 R4-B1 VERIFIED：

```text
[ ] every registry sdk_method has an explicit endpoint-proof classification/reconciliation
[ ] security_master cannot endpoint-PASS when historical/delisted required endpoint is denied
[ ] ADR-020 and runtime contract agree on adj_factor / all multi-method capabilities
[ ] exact endpoint stand-in mismatch remains fail-closed
[ ] endpoint provider_dataset exactness remains fail-closed
[ ] only verified formal-run path can create production APPROVED capability state
[ ] direct caller-supplied CapabilityEvidence cannot bypass formal endpoint proof
[ ] proof case <-> REPORT entry evidence URI/hash exact-match
[ ] REPORT entry <-> Raw meta request_id/endpoint/provider_dataset exact-match
[ ] tampered dataset/evidence binding/raw meta fails closed
[ ] A3 persistence structural early-stop remains true
[ ] positive production identity remains fail-closed
[ ] R4-A2.x / CR-1.x frozen contracts remain intact
[ ] full required CI matrix green
[ ] DEVLOG / management / ADR match actual runtime truth
```

通过后：

```text
R4-B1 / B1.1 -> VERIFIED / CLOSED
R4-B2 Publish Validation Exactness -> START
```

Production P0-M-1B 仍独立 BLOCKED。

---

# 9. Governance 当前状态要求

下一逻辑开发提交同步：

```text
R4-A2.x / CR-1.x = CLOSED / VERIFIED / FREEZE
R4-A3.x = CLOSED / VERIFIED / FREEZE
R4-B1 = DONE / REOPENED
R4-B1.1 = ACTIVE NEXT
R4-B2 = BLOCKED_BY_R4-B1.1
CR-2 = sequenced after R4-B2
P0-M-1B = BLOCKED
```

同步：

```text
docs/DEVLOG.md               append-only
docs/project/DEVELOPMENT_MANAGEMENT.md current truth
docs/adr/ADR-020_endpoint_requirement_contract.md amendment/correction
```

不得删除 R4-B1 本轮实现与 CI 绿灯历史；REOPENED 是 contract correctness 复审结论，不是否认已经通过的 mechanism work。

---

# 10. Reviewer Handoff

下一轮只重点检查：

```text
A. capability endpoint semantic contract 是否正确且 registry methods 全量 reconcile
B. production APPROVED transition 是否不可由 caller self-declare 绕过
C. contract/case/REPORT/Raw meta 是否 exact cross-bind
D. dataset/evidence/raw-meta tamper 是否 fail closed
E. A3/A2/CR-1 regression + full CI
```

不要启动 R4-B2，不要扩展 CR-2 / canonical / feature / state。

---

# 11. Implementation Mapping（开发方填写，2026-08-30）

## P0-01 — Endpoint Requirement Contract 语义修正（§2）

| Requirement | Implementation | Tests |
|---|---|---|
| security_master 历史端点必须 REQUIRED（survivorship core） | `ENDPOINT_REQUIREMENTS`：`security_master:BaseData.get_hist_code_list` = REQUIRED（唯一 requirement）；`get_code_list` 移出 requirements（分类 OPTIONAL_NON_APPROVAL_SURFACE）；`ENDPOINT_PROBE_SPECS` 同步移除 get_code_list 条目 | test_security_master_hist_endpoint_is_required |
| get_code_list 不得单独使 endpoint gate PASS | 快照不再有 requirement probe——snapshot PASS + hist DENIED → ENDPOINT FAIL → early-stop → BUSINESS fired==0 → approval impossible | test_hist_denied_snapshot_available_is_endpoint_fail + test_snapshot_alone_can_never_satisfy_the_proof（含 REPORT 记录诚实 FAIL） |
| adj_factor 双真相二选一 | **Option B**：撤回 ADR-020 "各自 REQUIRED"；`get_backward_factor` 分类 OPTIONAL_NON_APPROVAL_SURFACE（reason 记录"当前管线不消费的后复权数据流，R4-B1.1 Option B 解决 ADR overclaim"）；approval 只要求 get_adj_factor | test_adj_factor_backward_factor_is_option_b（分类 + runtime contract 一致） |
| 全部 registry sdk_methods 显式 reconcile | `SDK_METHOD_CLASSIFICATIONS` 表（19 条，`SdkMethodClassification`：capability / endpoint / classification / reason）：security_master 三方法、adj_factor 两方法、industry_taxonomy 四方法、index_daily 两方法全部显式分类（五分类 enum：REQUIRED_ENDPOINT_PROOF / ALTERNATIVE_GROUP_MEMBER / OPTIONAL_NON_APPROVAL_SURFACE / BUSINESS_SEMANTIC_ONLY / DEPRECATED_NOT_USED） | test_every_registry_sdk_method_is_explicitly_classified（`set(registry.sdk_methods) == set(classified)`，漏项即红） |
| 分类与 requirements 双向一致 | `validate_endpoint_requirements()` 扩展：分类表内部一致（无重复、reason 非空）+ REQUIRED 分类 ↔ REQUIRED requirements 集合相等 + ALTERNATIVE_GROUP 分类 ↔ 组成员集合相等 | test_contract_is_structurally_valid（含新检查） |
| 修正后改写错误语义测试 | `test_alternative_group_single_member_pass_is_pass`（Reviewer §6 点名）改写为两个 hist-denied 语义测试 | 同上两测试 |

## P0-02 — Approval Anti-Bypass（§3）

| Requirement | Implementation | Tests |
|---|---|---|
| 唯一生产 APPROVED transition | `approve_from_spike_run`（closed run → provenance → verdict → formal gate proof → endpoint cross-binding）→ `VerifiedCapabilityApproval`（内部 sealed proof object：name / evidence / verified_from_run / endpoint_requirements_proven；`__post_init__` 拒绝空证明）→ `_persist_verified_capability`（private 持久化边界，只接受 verified object；保留 R3-P1-05 validate-before-mutate / 单事务 / cache-rebuild / R2-P1-01 UPDATE-only-governance-fields） | test_only_the_verified_path_persists_approved |
| caller CapabilityEvidence 不能 self-declare | 旧 public 函数**移除**：`approve_and_persist_capability` / `approve_capability` 从模块命名空间消失；测试改用显式 test-only helper（`_approve_and_persist_capability_testonly` / `_approve_capability_in_memory_testonly`，docstring 声明非生产路径） | test_old_public_approval_paths_no_longer_exist + test_fabricated_evidence_cannot_self_declare_production_approval |
| test-only helper 不得被生产代码引用 | AST 守卫：src/ 全模块扫描，任何对两个 test-only helper 名字的引用即 AssertionError | test_production_code_never_calls_the_testonly_helpers |
| APPROVED 写入只在 governed 边界 | AST 守卫：capability.py 中 "APPROVED" 字面量 / CapabilityStatus.APPROVED 构造只允许出现在 `_persist_verified_capability` / `_approve_capability_in_memory_testonly`（+load_approvals 的 DB→cache 重建） | test_approved_writes_only_in_governed_boundaries |
| failed endpoint requirement 无旁路 + DB/cache 一致 | 篡改为 FAIL 的 run → approve_from_spike_run 拒绝 → load_approvals 后仍 CANDIDATE，DB 无 APPROVED 行 | test_failed_endpoint_requirement_has_no_bypass |
| positive production identity 不削弱 | test-only helper 保留 `_validate_evidence` 全部拒绝路径（frozen identity exact-match 等）；生产链在 approve_from_spike_run 内独立验证 | 既有 test_trial_production_boundary.py 全过（迁移至 helper） |

## P0-03 — Persisted Identity Cross-Binding（§4）

| Requirement | Implementation | Tests |
|---|---|---|
| contract ↔ REPORT entry（含 dataset） | `_require_formal_gate_proof` 重写：entry.expected_endpoint / **provider_dataset** / capability == contract 三字段 | test_provider_dataset_tamper_blocks |
| entry.actual_dataset == contract dataset | 显式检查 | test_actual_dataset_tamper_blocks |
| proof case ↔ REPORT entry identity equality | case.evidence_ref == entry.evidence_uri 且 case.evidence_hash == entry.evidence_hash（case 与 artifact 对"什么证据证明了该端点"必须一致） | test_report_evidence_uri_swapped_to_permission_evidence_blocks（entry 指向 permission 证据）+ test_report_evidence_hash_swapped_to_other_legitimate_hash_blocks + test_case_evidence_ref_disagreeing_with_report_blocks（反向：改 case）+ test_case_evidence_hash_disagreeing_with_report_blocks |
| REPORT entry ↔ Raw meta（hash 重验） | sha256(meta bytes) == entry.evidence_hash（entry.evidence_uri 相对 spike_root 解析；approval 新增 spike_root 参数，缺失即拒绝） | 全部 9 项的基础层 |
| Raw meta ↔ contract/entry（endpoint/dataset/request_id） | meta_doc.endpoint == req.endpoint；meta_doc.provider_dataset == req.provider_dataset；meta_doc.request_id == entry.request_id | test_raw_meta_endpoint_tamper_blocks + test_raw_meta_provider_dataset_mismatch_blocks + test_raw_meta_request_id_mismatch_blocks |
| 全部对抗在 REPORT hash re-bind 后仍拒绝 | dataset 两项 tamper 测试均调用 `_rebind_report_case_hash`（攻击者重锚 REPORT case hash）；evidence 置换测试同步改 entry 的 uri/hash/request_id 后 re-bind | 见上各行（re-bind 内建于 helper） |
| 复用既有 parser | meta 读取直接 json.load .meta.json（RawWriter 写盘格式；无第二套 lineage 解析） | 代码审查点 |

## P1-01 — ADR-020 Governance Correction（§5）

- **Amendment 2026-08-30**（追加，原文保留）：Status 修正说明（原 ACCEPTED/Deciders 是 Reviewer 复审前开发方预写的 overclaim，如实记录）；C.1 security_master 编组撤回（含与 core capability 冲突的三点论证）；C.2 adj_factor Option B；C.3 classification 表；C.4 anti-bypass；C.5 cross-binding；C.6 治理状态同步（R4-B1 机制性工作 FREEZE 保留）

## Batch D — Adversarial Regression（§7）

- security-master hist denied：ENDPOINT FAIL + BUSINESS fired==0 + approval impossible（2 项新测试）
- direct approval bypass：6 项（TestApprovalAntiBypass）
- dataset/evidence/raw-meta tamper：9 项（TestCrossBindingTamper）
- A3/A2/CR-1 regression：全量 797/0（persistence early-stop / L1 wiring / gate separation / trial boundary / frozen contracts 零回归）
- 固化错误语义的测试按 §6 改写（不为维持 779/0 保留错误语义）

## Verification Summary

- Local: **797 / 0**（779 → 797，+18：anti-bypass 6 + cross-binding 9 + contract 语义 3；改写 2）；ruff check / ruff format --check / mypy 全绿（退出码严格验证）
- 既有回归零破坏（A3/A2/CR-1 冻结契约）
- 边界遵守：未启动 R4-B2 / CR-2（§10）
