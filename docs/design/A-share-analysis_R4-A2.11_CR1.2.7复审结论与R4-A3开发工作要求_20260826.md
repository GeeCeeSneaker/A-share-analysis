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
