# A-share-analysis：R4-B1.1 复审与 R4-B1.2 最终 Approval Boundary / Industry Endpoint 收口要求

> **Review Date**：2026-08-30 15:42 +08:00  
> **Reviewed Repository HEAD**：`c2e572d1073c48ae93a4bc57373830ba92306054`  
> **Primary R4-B1.1 Implementation**：`6f323f38d72c3a8d7ed83430904d19316bcf93a3`  
> **Previous Reviewer Requirement**：`51f71feb55c3e55938fbf40154dc24c91b95aa5b`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **R4-A3.x / R4-A2.x / CR-1.x**：**CLOSED / VERIFIED / FREEZE（不重开）**  
> **Next Batch**：**R4-B1.2 Final Approval Boundary + Industry Endpoint Semantics Closure**  
> **R4-B2**：**BLOCKED until R4-B1.2 VERIFIED**  
> **CR-2**：sequenced after R4-B2  
> **Production P0-M-1B**：BLOCKED independently

---

# 0. Reviewer 裁决摘要

R4-B1.1 已正确关闭上一轮 3 个 P0 中的大部分内容，本轮**不推倒重做**。

## PASS / FREEZE

```text
PASS  security_master historical endpoint = REQUIRED
PASS  snapshot-only cannot satisfy security_master endpoint proof
PASS  sdk_methods 全量 typed classification primitive
PASS  registry sdk_methods == classification exact-set structural guard
PASS  REQUIRED classification <-> ENDPOINT_REQUIREMENTS 双向一致
PASS  adj_factor ADR/code double-truth 已按 Option B 修正
PASS  exact endpoint/dataset match engine
PASS  stand-in endpoint -> blocking FAIL
PASS  A3 structural early-stop remains true
PASS  case <-> REPORT evidence URI/hash equality
PASS  REPORT expected/actual endpoint + dataset re-check
PASS  REPORT entry <-> persisted Raw meta byte-hash re-check
PASS  Raw meta request_id / endpoint / provider_dataset reverse verification
PASS  current HEAD full CI matrix green
PASS  ADR-020 amendment preserves/retracts prior overclaims
```

但 R4-B1 Exit Gate 仍有 **2 个 P0 blocker**：

```text
P0-01  Approval Anti-Bypass 仍是 Python 命名约定，不是结构性边界。
P0-02  industry_taxonomy contract 与 canonical deliverable bridge_industry_member 不一致：
       只 REQUIRED base_info，却把 constituent 标成 optional。
```

因此：

```text
R4-B1   = DONE / REOPENED
R4-B1.1 = DONE / REOPENED（大部分 PASS / FREEZE）
R4-B1.2 = ACTIVE NEXT
R4-B2   = BLOCKED
```

本轮不要启动 R4-B2。

---

# 1. 已通过：Persisted Identity Cross-Binding —— VERIFIED / FREEZE

当前 `_require_formal_gate_proof()` 已形成四层精确绑定：

```text
Endpoint Requirement Contract
        ↕ exact endpoint / provider_dataset
REPORT endpoint_requirements[]
        ↕ evidence_uri / evidence_hash
Endpoint Proof Case
        ↕ persisted bytes hash
RawWriter .meta.json
        ↕ request_id / endpoint / provider_dataset
Contract / REPORT
```

Reviewer 核验：

```text
[PASS] expected_endpoint == contract endpoint
[PASS] provider_dataset == contract dataset
[PASS] actual_endpoint == contract endpoint
[PASS] actual_dataset == contract dataset
[PASS] proof case evidence_ref == REPORT evidence_uri
[PASS] proof case evidence_hash == REPORT evidence_hash
[PASS] persisted .meta.json exists
[PASS] sha256(meta bytes) == REPORT evidence_hash
[PASS] meta.request_id == REPORT request_id
[PASS] meta.endpoint == contract endpoint
[PASS] meta.provider_dataset == contract dataset
```

同时正式 `ProbeContext.evidence_from_exchange()` 的 evidence anchor 仍是 RawWriter `.meta.json`，其 evidence_hash 为持久化 meta bytes 的 SHA-256；因此上述 cross-binding 与正式运行时 evidence contract 一致。

此项冻结。除出现可复现 regression，不再重开。

---

# 2. P0-01：Approval Anti-Bypass 仍未结构性关闭

## 2.1 当前实现的进步

R4-B1.1 已删除旧公共名称：

```text
approve_capability
approve_and_persist_capability
```

并让正式 happy path 变成：

```text
approve_from_spike_run
  -> closed PRODUCTION run
  -> production identity
  -> verdict
  -> formal gate proof
  -> exact endpoint cross-binding
  -> VerifiedCapabilityApproval
  -> _persist_verified_capability
```

方向正确。

## 2.2 剩余 bypass

但是 Python 的 `_name` 仅是命名约定，不是访问控制。

当前生产 `src/ashare_state/providers/amazingdata/capability.py` 仍包含：

```text
_approve_and_persist_capability_testonly(conn, name, CapabilityEvidence)
_approve_capability_in_memory_testonly(name, CapabilityEvidence)
VerifiedCapabilityApproval(...)
_persist_verified_capability(conn, verified)
```

问题：

1. `_approve_and_persist_capability_testonly()` 仍直接接受 caller-built `CapabilityEvidence`，并最终写 `APPROVED`；任何调用者都可以显式 import 下划线函数。
2. `VerifiedCapabilityApproval` 是普通可实例化 dataclass，不是不可伪造 token；`__post_init__` 只检查 `verified_from_run` / `endpoint_requirements_proven` 非空。
3. 调用者可自行构造：

```python
VerifiedCapabilityApproval(
    name="daily_bar",
    evidence=fabricated_evidence,
    verified_from_run="fake-run",
    endpoint_requirements_proven=("fake-proof",),
)
```

然后直接调用 `_persist_verified_capability()`。
4. `_persist_verified_capability()` 只重做 `_validate_evidence()`；它**不会重新验证 closed production run / verdict / formal gate REPORT / endpoint proof / Raw meta cross-binding**。

所以当前真实状态仍是：

```text
caller fabricated evidence
-> explicitly import private helper / construct verified dataclass
-> APPROVED
```

测试目前只证明：

```text
旧 public 名字消失
src 自己不调用 test-only helper
APPROVED literal 只出现在有限函数
```

这不能证明 caller 无法绕过。

## 2.3 强制修复

### Preferred Option A：生产模块彻底不存在“无需 formal run 即可写 APPROVED”的 callable

```text
approve_from_spike_run(...)
    -> 完成全部验证
    -> 同一函数内部执行 DB transaction / cache rebuild
```

测试若需要单独验证 transaction/cache mechanics：

```text
放在 tests/ fixture/helper
直接构造 DB 前置状态
```

不得为了测试便利在 `src` 留一个可写生产 APPROVED 的 bypass helper。

`VerifiedCapabilityApproval` 如仅用于在一个函数内部传递数据，可删除；不要把“verified”安全语义寄托在 caller 可构造 dataclass 上。

### Option B：若必须保留 persistence helper

helper 自身必须接收真实 run/store/catalog inputs，并**重新执行或不可绕过地调用** formal-run verification：

```text
closed PRODUCTION
positive frozen production identity
verdict PASS
formal runtime gates
exact endpoint requirement proof
case/REPORT/Raw cross-binding
```

它不得接受一个 caller 自报“我已经 verified”的对象作为唯一授权条件。

## 2.4 必须新增对抗测试

测试必须直接尝试真实绕过，而不是只检查命名：

```text
[ ] import capability._approve_and_persist_capability_testonly -> 应不存在/不能写 APPROVED
[ ] construct VerifiedCapabilityApproval with fake nonempty fields -> 不能写 APPROVED
[ ] direct-call any src persistence helper without a real formal run -> 不能写 APPROVED
[ ] caller-built CapabilityEvidence + frozen production id -> 仍不能写 APPROVED
[ ] only approve_from_spike_run with real closed proof chain can transition DB to APPROVED
```

结构守卫建议：生产 `src` 中不存在任何函数，其参数仅靠 `CapabilityEvidence` / “verified object” 即可到达 `status='APPROVED'` 写入。

---

# 3. P0-02：industry_taxonomy Endpoint Contract 与实际交付物仍不一致

## 3.1 当前合同

Registry：

```text
industry_taxonomy.sdk_methods:
  InfoData.get_industry_base_info
  InfoData.get_industry_constituent
  InfoData.get_industry_weight
  InfoData.get_industry_daily

canonical_domains:
  bridge_industry_member
```

R4-B1.1 classification 当前为：

```text
get_industry_base_info      = REQUIRED_ENDPOINT_PROOF
get_industry_constituent    = OPTIONAL_NON_APPROVAL_SURFACE
get_industry_weight         = OPTIONAL_NON_APPROVAL_SURFACE
get_industry_daily          = OPTIONAL_NON_APPROVAL_SURFACE
```

这仍然过弱。

`bridge_industry_member` 的核心交付物是：

```text
security <-> industry membership
```

仅 `get_industry_base_info` 只能证明 taxonomy definition / identity surface 可用，不能证明 constituent membership surface 可用。

如果：

```text
get_industry_base_info PASS
get_industry_constituent DENIED
```

当前 ENDPOINT contract 仍可 PASS，并允许 `industry_taxonomy` capability 最终 APPROVED；但系统无法可靠构建 `bridge_industry_member`。

这与上一轮 security_master 的问题同构：

```text
证明一个“代表性 endpoint” != 证明 capability 的必要交付面
```

## 3.2 强制修复

推荐：

```text
InfoData.get_industry_base_info   = REQUIRED_ENDPOINT_PROOF
InfoData.get_industry_constituent = REQUIRED_ENDPOINT_PROOF
```

`get_industry_weight` / `get_industry_daily` 是否 REQUIRED 应依据当前 canonical/feature consumer 决定；若当前不参与 `bridge_industry_member` 构建，可保持 OPTIONAL，但理由必须明确指向当前消费边界。

如果开发方认为 constituent 不应成为 approval requirement，则必须提供一个**不同且自洽的 capability definition**，解释为什么名为 `industry_taxonomy`、canonical domain 为 `bridge_industry_member` 的 capability 在 constituent endpoint 不可用时仍可以 APPROVED。不能只用“base_info 是 classification identity source”作为充分理由。

## 3.3 必须新增测试

```text
base_info PASS + constituent DENIED
-> ENDPOINT_AVAILABLE FAIL
-> BUSINESS probe fired == 0
-> constituent failure exchange persisted
-> constituent proof case VALIDATED_FAIL
-> capability approval impossible
```

并增加结构守卫：

```text
canonical deliverable required surfaces
<-> REQUIRED endpoint requirements
```

至少对 multi-endpoint capability 用显式测试固定当前设计决定，避免以后再次出现“所有 sdk_methods 都分类了，但必要 method 被分类成 optional”的形式合规、语义失真。

---

# 4. CI / Governance

Reviewer 正向确认 current HEAD `c2e572d1073c48ae93a4bc57373830ba92306054`：

```text
GitHub Actions run 33295951987 = SUCCESS
Windows / Python 3.12 = SUCCESS
Windows / Python 3.14 = SUCCESS
Ubuntu  / Python 3.14 = SUCCESS
Ruff lint              = SUCCESS
Ruff format            = SUCCESS
Mypy                   = SUCCESS
Pytest                 = SUCCESS
Spike framework gates  = SUCCESS
```

因此 CI 不是 blocker；剩余问题是 contract/security boundary correctness。

ADR-020 Amendment 2026-08-30 对原 ACCEPTED/Decider overclaim、security_master grouping、adj_factor double truth 已作历史保留式 correction，治理方式正确；但本 Reviewer verdict 后不得把 R4-B1/B1.1 标 VERIFIED。

下一逻辑开发提交同步：

```text
R4-B1   = DONE / REOPENED
R4-B1.1 = DONE / REOPENED (cross-binding + security_master reconciliation PASS/FREEZE)
R4-B1.2 = ACTIVE
R4-B2   = BLOCKED_BY_R4-B1.2
```

同步：

```text
docs/DEVLOG.md append-only
docs/project/DEVELOPMENT_MANAGEMENT.md current truth
ADR-020 amendment/correction（industry requirement / approval boundary）
```

---

# 5. R4-B1.2 Exit Gate

只有全部满足才给 R4-B1 全链 VERIFIED：

```text
[ ] security_master historical REQUIRED remains frozen
[ ] registry sdk_methods classification exact-set remains green
[ ] industry constituent required-surface semantics correctly closed
[ ] base_info PASS + constituent DENIED -> ENDPOINT FAIL + business zero call
[ ] src contains no test-only APPROVED-writing bypass helper
[ ] caller cannot fabricate VerifiedCapabilityApproval and persist APPROVED
[ ] no production persistence helper trusts a caller-declared "verified" object
[ ] only real formal-run verification path can reach APPROVED
[ ] four-layer exact cross-binding remains intact
[ ] A3 persistence early-stop / positive production identity remain intact
[ ] R4-A2.x / CR-1.x frozen contracts remain intact
[ ] full CI matrix green
[ ] DEVLOG / management / ADR current truth matches runtime
```

满足后：

```text
R4-B1 / B1.1 / B1.2 = VERIFIED / CLOSED
R4-B2 Publish Validation Exactness = START
```

Production P0-M-1B 仍独立 BLOCKED。

---

# 6. Reviewer Handoff

下一轮只检查两项：

```text
A. industry_taxonomy 必要 endpoint 语义是否与 bridge_industry_member 交付一致
B. caller-self-declare APPROVED 是否从生产 src 中真正结构性消失
```

Cross-binding engine、security_master historical requirement、A3/A2/CR-1 frozen contracts除非出现可复现 regression，不再重审。
