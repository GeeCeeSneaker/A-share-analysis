# A-share-analysis：R4-A2.11 / CR-1.2.7 复审结论与 R4-A3 开发工作要求

> **Review Date**：2026-08-26 23:57 +08:00  
> **Reviewed Repository HEAD**：`ab0cde7db4673224518540e1974c4e918bdbbf33`  
> **Primary Implementation Commit**：`38da90e5b5f3d698cc909cf7c258c163081bb9af`  
> **CI/Lint Fix Commit**：`6eac92dceaf57014f07d93bd5e6eabcea1dcbc79`  
> **Previous Reviewer Requirement Commit**：`1706f265226e66980da5a820a6189cb908914b9b`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**VERIFIED**  
> **R4-A2.x / CR-1.x Audit Chain**：**CLOSED / VERIFIED**  
> **Next Active Batch**：**R4-A3 SDK / Lifecycle / Early-Stop Closure**  
> **R4-B1 / R4-B2**：**UNBLOCKED / SEQUENCED AFTER R4-A3**  
> **CR-2 Provider-Normalized + Quarantine**：**UNBLOCKED TECHNICALLY / SEQUENCED AFTER R4-B2**  
> **Production P0-M-1B**：**BLOCKED（人工 Review + 正式账号条件未满足）**

---

# 0. Reviewer 最终裁决

本轮对 R4-A2.11 / CR-1.2.7 的复核结论为 **VERIFIED**。

上一轮唯一 remaining P0——Review Parent-Identity Serialization——已经按首选 Option A 做到结构性闭环：

```text
acquire .review.lock
  ↓
load_active_rules / ACTIVE parent selection
  ↓
lineage + input==ACTIVE + COMPILED
  ↓
version confinement + target non-existence
  ↓
ACTIVE exact snapshot + hash
  ↓
reviewed_bytes transform
  ↓
sandbox parse
  ↓
staged gate
  ↓
publish immutable version
  ↓
ACTIVE manifest commit
  ↓
post-commit verification
  ↓
release .review.lock
```

因此此前可复现的 stale-parent race：

```text
A 与 B 都先在锁外基于 v1 完成 Phase 1
A 提交 v2
B 再拿锁，用 stale v1 snapshot 提交 v3
```

在当前正式控制流中已经不再成立。

Reviewer 同时确认此前已冻结的合同均无回归：

```text
ACTIVE input exact snapshot
REVIEWED persisted byte identity = reviewed_bytes
manifest.dataset_hash source = reviewed_bytes only
final reread = verification-only
pre-commit cleanup + deterministic retry
--version lexical-first output confinement
Golden artifact platform-independent confinement
CA collector.call atomic persistence boundary
Raw evidence identity / meta-payload closure / orphan recovery
Bound Rule lexical-first confinement + exact replay
Rule manifest metadata coherence
```

因此不再继续制造 R4-A2.12 / CR-1.2.8 一类同主题整改批次。

---

# 1. R4-A2.11 / CR-1.2.7 验证结果

## 1.1 Lock-before-parent-selection —— PASS

当前 `scripts/rules/review.py` 在 formal path 中：

```text
CLI parse
rules/artifact basic existence check
→ O_CREAT|O_EXCL acquire .review.lock
→ _review_workflow_locked(...)
→ load_active_rules(...)
```

`load_active_rules()`、ACTIVE selector 读取、parent identity、snapshot 和后续 commit 全在同一锁范围内。

这满足上一轮 Exit Gate 的核心不变量：

> **ACTIVE parent identity must be established while the review writer is serialized.**

锁仍是 advisory/process-scoped lock，不是跨机器 OS-level CAS；崩溃后的 stale lock 需要人工清理。该限制已经在 ADR-018 amendment 中诚实记录，不构成本批 blocker。

## 1.2 Stale-parent adversarial —— PASS

新增测试覆盖：

```text
A: v1 -> v2 reviewed commit
B: --from-version v1, target v3
→ B 在锁内看到 ACTIVE 已为 v2
→ BLOCK
→ no v3
→ no new manifest advance
→ lock release
```

默认不传 `--from-version` 时，B 指向旧 v1 的 `--rules` 也会在锁内被 `input == ACTIVE dataset` gate 拒绝。

同时验证：

```text
fresh current-ACTIVE review -> can proceed
same target-version race -> immutable collision, no overwrite
held lock -> second reviewer fails before load_active_rules
success/failure -> lock both released
```

这正面关闭了上一轮指出的 control-flow blind spot。

## 1.3 三重 structural proof —— PASS

本批不是仅依赖 happy-path 测试：

```text
Runtime probe:
  load_active_rules executes while .review.lock exists

AST structural guard:
  O_EXCL lock acquisition precedes first load_active_rules in formal path

Behavior adversarial:
  stale parent cannot overwrite an already advanced ACTIVE selector
```

三种证明共同锁定该 contract，接受。

---

# 2. 上一轮冻结项回归裁决

## 2.1 REVIEWED exact bytes —— PASS / FREEZE

正式 REVIEWED dataset identity 继续由：

```python
reviewed_bytes = reviewed_text.encode("utf-8")
```

定义，formal dataset write 路径继续使用 `write_bytes()`；不得回退到平台相关的 `write_text()`。

## 2.2 Manifest seal identity —— PASS / FREEZE

继续保持：

```text
expected_dataset_hash = hash(final_rel + reviewed_bytes)
filesystem readback = verify only
```

禁止未来重新改成：

```text
read whatever bytes happen to be on final path
→ hash those bytes
→ bless into ACTIVE manifest
```

## 2.3 Publish rollback —— PASS / FREEZE

ACTIVE manifest 原子替换前为 uncommitted：失败必须清理本次 published version / evidence / staging / tmp manifest，并允许 deterministic retry。

manifest commit 后若 coherence verification 失败，继续使用显式 `REVIEW_COMMIT_INCONSISTENT` hard-failure 语义，不得伪装成普通可重试失败。

## 2.4 Upstream evidence / replay contracts —— PASS / FREEZE

以下继续冻结：

```text
ProviderExchange explicit runtime boundary
RawWriter persisted identity
request_id / evidence_ref / evidence_hash coherence
provider-native Raw + semantic adapter separation
CA per-call atomic persistence
Bound Rule exact files/hash/version replay
lexical-first confinement
no silent fallback
```

---

# 3. CI Truth

本轮检查到的真实 CI 时间线：

```text
run 51 -> FAIL
  原因：新增 lineage test 的 3 个 Ruff lint 错误
  本地检查输出截断只保留 trailer，造成误判

6eac92dceaf57014f07d93bd5e6eabcea1dcbc79
  -> 修复 2 × SIM102 + 1 × C416

run 52 -> FULL MATRIX GREEN

current HEAD ab0cde7db4673224518540e1974c4e918bdbbf33
run 53 -> FULL MATRIX GREEN
```

run 53 job-level truth：

```text
Windows / Python 3.14 -> SUCCESS
  Ruff lint       SUCCESS
  Ruff format     SUCCESS
  Mypy            SUCCESS
  Pytest          SUCCESS
  Spike gates     SUCCESS
  DEVLOG gate     SUCCESS
  Management gate SUCCESS

Windows / Python 3.12 -> SUCCESS
  Ruff / format / Mypy / Pytest / Spike gates SUCCESS

Ubuntu / Python 3.14 -> SUCCESS
  Ruff / format / Mypy / Pytest / Spike gates SUCCESS
```

因此当前 CI = **FULL MATRIX GREEN**。

run 51 的历史失败不得删除；它证明本地验证展示层曾掩盖退出状态。后续本地验证必须以 exit code 为准，不得通过截断输出判断 pass/fail。

---

# 4. Governance Reviewer Correction

当前 `docs/project/DEVELOPMENT_MANAGEMENT.md` 的本批 `Current Code Baseline` 两个完整 SHA 写错，必须以 GitHub commit object 为准。

错误记录：

```text
38da90e583a83dd0e83991987df7f29ddbc7189c6
6eac92dc1bfb7a3aa70619dc34695930e88a51af
```

正确记录：

```text
Primary implementation:
38da90e5b5f3d698cc909cf7c258c163081bb9af

Lint fix:
6eac92dceaf57014f07d93bd5e6eabcea1dcbc79

Reviewed current HEAD:
ab0cde7db4673224518540e1974c4e918bdbbf33
```

本项是 governance traceability correction，不影响本轮 runtime VERIFIED。

本轮状态应同步为：

```text
R4-A2.10 / CR-1.2.6 -> DONE / VERIFIED (absorbed)
R4-A2.11 / CR-1.2.7 -> DONE / VERIFIED
R4-A2.x / CR-1.x    -> CLOSED / VERIFIED
RISK-004             -> CLOSED for its current review-lineage definition
R4-A3                 -> READY / ACTIVE NEXT
R4-B1                 -> READY_AFTER_R4-A3
R4-B2                 -> READY_AFTER_R4-B1
CR-2                  -> UNBLOCKED, sequenced after R4-B2
Production P0-M-1B    -> BLOCKED
```

由于 Reviewer connector 不适合安全重写超长 `DEVELOPMENT_MANAGEMENT.md` 全文件，本 Reviewer commit 作为裁决与 SHA correction 证据；下一逻辑开发提交必须把上述状态同步进总册和 DEVLOG，且不得改写历史记录。

---

# 5. R4-A2.x / CR-1.x 审计链关闭条件复核

上一轮 Exit Gate 逐项裁决：

```text
[x] single-writer serialization covers parent selection through commit
[x] stale parent cannot commit after ACTIVE advanced
[x] ACTIVE parent identity established while serialized
[x] exact ACTIVE snapshot intact
[x] reviewed_bytes exact persisted identity intact
[x] manifest identity derived only from reviewed_bytes
[x] final reread verification-only
[x] pre-commit cleanup / deterministic retry intact
[x] output confinement intact
[x] CA / Raw / Bound Rule closures intact
[x] full CI matrix green
[x] docs/runtime lock-scope overclaim corrected by ADR-018 amendment
```

**Reviewer Verdict：VERIFIED。**

连续 R4-A2.x / CR-1.x correctness audit 到此关闭。

---

# 6. 下一阶段排序原则

虽然 Exit Gate 通过后 **R4-A3 与 CR-2 都已技术解锁**，但不要同时启动两个大工作面。

保持现有架构顺序：

```text
R4-A3 SDK / Lifecycle / Early Stop
        ↓
R4-B1 Capability Endpoint Proof
        ↓
R4-B2 Publish Validation Exactness
        ↓
R4-CI final contract consolidation（如 B1/B2 引入 gate 变化）
        ↓
CR-2 Provider-Normalized + Quarantine
        ↓
CR-3 AvailabilityPolicy + Canonicalizer
        ↓
CR-4 Snapshot + Read Model Rebuild
```

理由：R4-A3/B1/B2 仍属于 Provider/Spike formal truth 与 capability approval 基础设施；先把 Provider Runtime 的正式 gate 做完，再让 CR-2 消费 Raw evidence，可以减少后续 Canonical 层因 Provider 合同变化而返工。

---

# 7. Next Active Batch：R4-A3 SDK / Lifecycle / Early-Stop Closure

## 7.1 目标

把当前“ProviderExchange/Raw correctness 已成立”推进到“Provider runtime lifecycle / permission / freshness 能 fail-closed 地形成正式 capability evidence”。

本批不做 Canonical mapping，不启动 Feature/State。

## 7.2 强制工作项

### A3-01 SDK Lifecycle State Machine

必须把：

```text
SDK unavailable
load failed
login failed
auth rejected
session ready
subscribe started
callback active
unsubscribe
logout / close
```

表达成明确 lifecycle state / terminal state，不允许通过异常字符串猜测流程状态。

要求：

```text
terminal auth failure -> early stop
terminal SDK load failure -> early stop
no later provider business call after terminal failure
cleanup/unsubscribe/logout must be idempotent where applicable
```

### A3-02 Permission / Cache / Freshness 分 Gate

禁止把不同性质的失败折叠成一个“provider unavailable”。至少独立：

```text
AUTH / ACCOUNT
PERMISSION
ENDPOINT_AVAILABLE
CACHE / LOCAL_METADATA
FRESHNESS / ASOF
BUSINESS_DATA
```

每个 gate 必须：

```text
explicit status
explicit blocking reason
traceable evidence
no silent fallback
```

权限失败不能被缓存数据成功掩盖；缓存命中不能替代正式 endpoint proof；freshness 不足不得降级为“有数据即 PASS”。

### A3-03 Early Stop Control Flow

一旦 formal prerequisite 失败：

```text
later dependent endpoint MUST NOT fire
```

至少对以下链路增加 fault-injection：

```text
SDK load fail -> no login / endpoint call
login/auth terminal fail -> no capability calls
permission fail -> no dependent business fetch
required metadata/cache invalid -> no dependent probe
freshness gate fail -> no business-truth PASS
```

必须通过 provider call-count / exchange-count / evidence-count 证明，而不是只看最终异常。

### A3-04 Runtime Truth / Trial Boundary

继续保持：

```text
CI/Fake = structure truth only
Trial account = L1 connectivity only
Production account = formal permission / endpoint / business truth
```

任何 Trial/Fake 成功都不得把 capability 标为 PRODUCTION APPROVED。

### A3-05 Evidence Closure

所有 runtime gate 仍必须遵守现有正式证据链：

```text
Provider call
→ ProviderExchange
→ RawWriter
→ persisted meta/payload evidence
→ SpikeCase / Gate result
```

禁止为了 lifecycle 便利重新引入 payload-only provider calls、`last_envelopes` correctness consumer 或 synthetic success exchange。

## 7.3 Required Tests

至少覆盖：

```text
[ ] SDK absent -> terminal state + no later call
[ ] SDK load exception -> terminal state + cleanup
[ ] login/auth reject -> early stop
[ ] permission denied -> explicit PERMISSION fail, no silent fallback
[ ] cache hit + permission fail -> permission still FAIL
[ ] stale data -> freshness FAIL, not business PASS
[ ] required endpoint failure -> dependent endpoints do not fire
[ ] unsubscribe/close retry is safe/idempotent
[ ] Fake/Trial cannot produce PRODUCTION approval
[ ] every real/fake provider call in formal path returns ProviderExchange
[ ] success/failure evidence remains RawWriter-anchored
[ ] previous R4-A2.x/CR-1.x regression suite remains green
```

## 7.4 Governance

建议 Change IDs：

```text
DM-CR-20260826-030  SDK Lifecycle State Machine
DM-CR-20260826-031  Permission / Cache / Freshness Gate Separation
DM-CR-20260826-032  Runtime Early-Stop Enforcement
DM-CR-20260826-033  R4-A2.x / CR-1.x VERIFIED Governance Closure
```

如 lifecycle state / capability status 改变外部契约，则 C1/C2 按规则同步：

```text
Code + Tests + DEVLOG + DEVELOPMENT_MANAGEMENT
+ ADR（如改变长期 runtime/capability design）
```

四问必须记录：

```text
为什么要改
怎么改
考虑哪些替代方案 / 为什么拒绝
成本与收益
```

---

# 8. R4-A3 Exit Gate

只有同时满足：

```text
[ ] lifecycle states explicit and testable
[ ] auth/load terminal failures early-stop
[ ] permission/cache/freshness/business gates separated
[ ] no dependent provider call after blocking prerequisite
[ ] no silent fallback
[ ] no payload-only formal provider path regression
[ ] ProviderExchange / Raw evidence chain remains exact
[ ] Fake/Trial cannot grant PRODUCTION capability truth
[ ] CI required matrix green
[ ] docs match runtime
```

才允许进入 R4-B1。

---

# 9. R4-B1 / R4-B2 预留边界（本批不要提前实现）

## R4-B1 Capability Endpoint Proof

下一批重点：

```text
Capability Approval 不接受 caller self-declare
必须绑定 provider / dataset / endpoint / account profile / runtime
必须有 persisted exchange evidence
permission / endpoint proof 与 business-quality proof 分离
```

## R4-B2 Publish Validation Exactness

后续重点：

```text
explicit artifact_validation_id
publish/verdict 必须绑定 exact validated artifact identity
Migration 011（若现有 roadmap 保持）
publish/replay 不能受 ACTIVE pointer 漂移影响
artifact missing/tampered -> fail closed
```

R4-B1/B2 的正式开发要求在 A3 VERIFIED 后再细化，避免并行扩大修改面。

---

# 10. Production P0-M-1B 继续 BLOCKED

R4-A2.x / CR-1.x VERIFIED **不等于**生产 Provider Truth 已完成。

Production P0-M-1B 仍需：

```text
Golden Truth 人工 Review
  - review 123 v3 cases
  - ST_TRANSITION distinct events >= 50
  - DELIST distinct symbols >= 20
  - external official artifacts sealed

Trading Rule 人工 Review
  - 使用本轮 VERIFIED 的 exact-byte + serialized-parent workflow

Production Account Profile
  - 正式账号
  - production_account_profile_id frozen

Provider Doctor
  - RUNTIME_ACTUAL_LOAD_VERIFIED

Formal endpoint / permission / entry gates
```

Trial / Fake / CI 成功不得替代上述条件。

---

# 11. 禁止事项

R4-A3 本批禁止：

```text
提前做 CR-2 Provider-Normalized mapping
提前做 CR-3/CR-4
Feature / State 扩展
把 Trial/Fake 当 Production truth
为减少失败而弱化 permission/freshness gate
重新引入 payload-only provider calls
重新打开已经 VERIFIED 的 R4-A2.x/CR-1.x 主体，除非出现可复现 regression
```

---

# 12. Reviewer Handoff

下一轮 Reviewer 只应重点检查：

```text
1. lifecycle state 是否真实进入 control flow，而非仅枚举/文档
2. auth/load/permission terminal failure 是否阻断后续 provider call
3. permission/cache/freshness 是否真正分离且无互相掩盖
4. formal evidence 是否继续 ProviderExchange -> RawWriter
5. Fake/Trial 是否被硬限制为非 Production truth
6. CI job-level truth
7. R4-A2.x/CR-1.x regression 是否保持
8. governance 是否同步 VERIFIED closure + 正确 SHA
```

如果 R4-A3 通过，再进入 R4-B1；不要再回到 R4-A2.x 进行无止境局部审计。

---

# 13. Implementation Mapping（Developer 回填，2026-08-26）

> 本批：R4-A3 SDK / Lifecycle / Early-Stop Closure（Batch A→F 全部完成；**未启动 CR-2 / R4-B1 / R4-B2 / Feature / State**——遵守 §11 禁止项）。
> 测试基线：**716 passed / 0 failed**（658 → 716，+58）；CI 等价四检查（ruff check + format --check + mypy + pytest，**以退出码严格验证**）本地全绿；dry-run 冒烟 35 exchanges + 5 bundles 双向闭合零问题（lifecycle 门不影响 dry-run 正常路径）；既有 R4-A2.x/CR-1.x regression 全部保持（658 项零回归）。
> Change IDs：DM-CR-20260826-030/031/032/033；**ADR-019**（含审计四问完整记录）。
> CI：本批提交后以 Actions 实际结果为准（上批 run 52/53 已三腿 success）。

## A3-01（SDK Lifecycle State Machine，§7.2）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 显式 lifecycle state / terminal state（9 态） | `providers/lifecycle.py::SdkLifecycleState`（INIT/SDK_UNAVAILABLE/LOAD_FAILED/LOGIN_FAILED/AUTH_REJECTED/SESSION_READY/SUBSCRIBE_STARTED/CALLBACK_ACTIVE/UNSUBSCRIBED/LOGGED_OUT + 合法迁移表） | lifecycle::TestStateMachine（15） |
| 不允许异常字符串猜测流程状态 | session.login 按错误**类型**落显式状态（ProviderUnavailableError→SDK_UNAVAILABLE；其他 load 异常→LOAD_FAILED；ProviderAuthError→AUTH_REJECTED；其他 login ProviderError→LOGIN_FAILED）；状态迁移记录 reason/evidence | early_stop::TestSdkLoadFailure ×2 + TestLoginTerminalFailure ×2 + TestLifecycleDrivesSession ×3 |
| terminal auth/load failure → early stop | `require_ready` → `ProviderLifecycleTerminalError`（context: state/reason/evidence/refused_action/early_stop）；`call_exchange` **第一道门** | lifecycle::TestRequireReady（7） |
| terminal 后无 business call | lifecycle 门在 capability gate 与 fn() 之前；零 exchange/零 envelope | early_stop::TestNoBusinessCallAfterTerminal（参数化 5 terminal 态：fired==0 + last_envelopes==[]） |
| cleanup/unsubscribe/logout 幂等 | `close()`（任意状态→LOGGED_OUT；已 closed 为 no-op）；失败态关闭=合法清理 | lifecycle::test_close_is_idempotent + test_close_from_failed_state_is_legal_cleanup + early_stop::test_real_session_logout_is_idempotent |

## A3-02（Permission / Cache / Freshness 分 Gate，§7.2）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 六类 gate 独立 | `providers/runtime_gates.py::GateKind`（AUTH_ACCOUNT/PERMISSION/ENDPOINT_AVAILABLE/CACHE_METADATA/FRESHNESS_ASOF/BUSINESS_DATA）+ 各 Gate 类 | separation::TestGateResults（9） |
| explicit status / blocking reason / traceable evidence / no silent fallback | GateResult（status: PASS/FAIL/**NOT_TESTABLE**/SKIPPED_BLOCKED + reason + evidence_ref + provider_calls_fired）；probe 走 ProviderExchange（evidence_ref=request_id） | separation::test_every_gate_result_carries_reason_and_evidence |
| 权限失败不被缓存掩盖 | pipeline 顺序 PERMISSION → CACHE_METADATA + early stop | separation::test_cache_hit_cannot_mask_permission_failure（cache_ok=True 仍 blocked_by PERMISSION） |
| 缓存命中不替代 endpoint proof | EndpointAvailableGate 真实 probe exchange | separation（EndpointAvailableGate 语义 + probe 计数==1） |
| freshness 不足不降级为有数据即 PASS | FreshnessAsOfGate：stale→FAIL；unknown as-of→NOT_TESTABLE（阻断） | separation::test_freshness_stale_fails + test_freshness_unknown_as_of_not_testable + test_freshness_fail_blocks_business_pass（business probe==0） |

## A3-03（Early Stop Control Flow，§7.2）

| 链路 | 测试（计数证明） |
|---|---|
| SDK load fail → no login / endpoint call | early_stop::test_sdk_absent_no_login_no_endpoint_call（SDK_UNAVAILABLE；后续 call_exchange 拒绝）+ test_sdk_load_exception_is_load_failed |
| login/auth terminal fail → no capability calls | early_stop::test_auth_rejected_no_capability_calls（sdk.calls==["login"]，零 BaseData/InfoData）+ test_network_login_failure_is_login_failed |
| permission fail → no dependent business fetch | separation::test_permission_fail_blocks_dependent_business_fetch（permission.fired==1、endpoint==0、business==0、total==1） |
| required metadata/cache invalid → no dependent probe | separation::test_cache_metadata_fail_blocks_dependent_probe（business==0） |
| freshness gate fail → no business-truth PASS | separation::test_freshness_fail_blocks_business_pass（business probe==0） |
| call-count / exchange-count / evidence-count 证明 | GateResult.provider_calls_fired + report.total_provider_calls_fired + probe.fired + last_envelopes==[]（非最终异常） |

## A3-04（Runtime Truth / Trial Boundary，§7.2）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| Trial/Fake 不得把 capability 标为 PRODUCTION APPROVED | `capability._validate_evidence` + `approve_from_spike_run` 双入口拒绝 TRIAL_*/FAKE*/UNKNOWN/空 account_profile_id | boundary::TestApprovalRefusesTrialAccounts（参数化 5 类 + 生产账号对照） |
| run kind PRODUCTION 本身不是 production truth | spike-run 路径独立拒绝（防御纵深：创建门被绕过时） | boundary::test_production_run_with_trial_account_refused（monkeypatch 创建门后 APPROVAL 仍拒） |

## A3-05（Evidence Closure，§7.2）

| 要求 | 落实 |
|---|---|
| gate 结果走 ProviderExchange → RawWriter | gates 的 ProbeCaller 契约 = 返回 ProviderExchange / 抛携带 .exchange 的 ProviderError（CR-1.1 一等失败）；PermissionGate/EndpointAvailableGate/BusinessDataGate 的 evidence_ref 即 exchange.request_id |
| 不重新引入 payload-only / last_envelopes / synthetic success | lifecycle 门在 exchange 创建之前（refused call 零半截 evidence）；全量 716 含既有 AST 守卫与 Spy 计数闭合测试零回归 |

## §7.3 Required Tests 对照

```text
[x] SDK absent -> terminal state + no later call（SDK_UNAVAILABLE + 后续拒绝）
[x] SDK load exception -> terminal state + cleanup（LOAD_FAILED + close 合法）
[x] login/auth reject -> early stop（AUTH_REJECTED；sdk.calls 只有 login）
[x] permission denied -> explicit PERMISSION fail, no silent fallback（FAIL + failure exchange evidence）
[x] cache hit + permission fail -> permission still FAIL（cache_ok=True 仍 blocked_by PERMISSION）
[x] stale data -> freshness FAIL, not business PASS（business probe==0）
[x] required endpoint failure -> dependent endpoints do not fire（business==0）
[x] unsubscribe/close retry is safe/idempotent（close 幂等 ×3 测试）
[x] Fake/Trial cannot produce PRODUCTION approval（双入口 ×6）
[x] every real/fake provider call in formal path returns ProviderExchange（gates ProbeCaller 契约 + 既有 CR-1 契约测试零回归）
[x] success/failure evidence remains RawWriter-anchored（evidence_ref=request_id + 既有 raw 链零回归）
[x] previous R4-A2.x/CR-1.x regression suite remains green（658 项零回归 → 716 全过）
```

## §7.4 Governance（DM-CR-20260826-033）

| 要求 | 落实 |
|---|---|
| Phase Status 同步（§4 裁决） | 总册头部 Phase Status 块 + §40（R4-A2.9/A2.10 → VERIFIED (absorbed)；R4-A2.11 → VERIFIED；R4-A2.x/CR-1.x → CLOSED；R4-A3 → PENDING_REVIEW；R4-B1/B2/CR-2 排序；P0-M-1B → BLOCKED） |
| SHA Correction | 总册头部 SHA Correction 段（正确 SHA：`38da90e5b5f3d698cc909cf7c258c163081bb9af` / `6eac92dceaf57014f07d93bd5e6eabcea1dcbc79`；历史条目原文保留不改写） |
| RISK-004 CLOSED for its current review-lineage definition | §52（含新消费面重新开项注记） |
| DEVLOG / ADR | DEVLOG 顶部新条目（历史保留）；ADR-018 索引标注 VERIFIED；ADR-019 新增（四问完整记录） |
| 四问记录 | ADR-019 §3（备选与拒绝理由表）+ §4（成本收益）：显式状态机 vs 异常字符串映射 / gate 分离 vs 折叠布尔 / NOT_TESTABLE 阻断 vs 放行 / 缓存 entitlement vs 真实 probe / OS 锁 vs 单进程状态机 |

## §8 Exit Gate 自检

```text
[x] lifecycle states explicit and testable（状态机 + 迁移表 + 15 单元测试）
[x] auth/load terminal failures early-stop（require_ready + call_exchange 第一道门）
[x] permission/cache/freshness/business gates separated（六类 GateKind + 非掩盖性测试）
[x] no dependent provider call after blocking prerequisite（pipeline early stop + 计数证明）
[x] no silent fallback（NOT_TESTABLE 阻断；stale FAIL；权限失败显式 FAIL）
[x] no payload-only formal provider path regression（既有 AST 守卫零回归）
[x] ProviderExchange / Raw evidence chain remains exact（probe 走显式边界；raw 链零回归）
[x] Fake/Trial cannot grant PRODUCTION capability truth（双入口拒绝 + 防御纵深）
[~] CI required matrix green —— 本地四检查退出码全绿；本批提交后以 Actions 实际结果为准（不预写）
[x] docs match runtime（ADR-019 + 总册 + DEVLOG 同批更新）
```

已知开放项（如实声明）：Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；Production P0-M-1B 保持 BLOCKED（§10 条件）；R4-B1/B2 待 A3 VERIFIED 后细化正式开发要求。
