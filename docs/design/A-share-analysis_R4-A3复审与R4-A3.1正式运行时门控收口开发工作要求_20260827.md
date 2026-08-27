# A-share-analysis：R4-A3 复审结论与 R4-A3.1 正式运行时门控收口开发工作要求

> **Review Date**：2026-08-27 10:40 +08:00  
> **Reviewed Repository HEAD**：`b5284bdc83631454c1d46add9e3478f86d81386e`  
> **Primary Implementation Commit**：`de9bf1ab6f499b20916f8277dba45c21880fd908`  
> **Previous Reviewer Requirement Commit**：`154198cfbad85015716f1e7acc952c1c202a2057`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **R4-A2.x / CR-1.x Audit Chain**：**CLOSED / VERIFIED（保持冻结，不重开）**  
> **Next Batch**：**R4-A3.1 Formal Runtime-Gate Wiring / Persisted Evidence / Production Account Positive Identity Closure**  
> **R4-B1**：**BLOCKED until R4-A3.1 VERIFIED**  
> **R4-B2**：**BLOCKED**  
> **CR-2**：**TECHNICALLY UNBLOCKED BY CR-1, BUT SEQUENCED / BLOCKED BY CURRENT ROADMAP until R4-B2**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. Reviewer 裁决摘要

R4-A3 本批已经完成了相当重要的基础结构，尤其是 SDK lifecycle 与 terminal early-stop 的核心机制：

```text
PASS  explicit SdkLifecycle state machine
PASS  SDK unavailable/load fail/login fail/auth reject -> explicit terminal state
PASS  session success -> SESSION_READY
PASS  provider.call_exchange lifecycle gate executes before capability gate / endpoint fn
PASS  terminal lifecycle -> endpoint fn zero calls / zero exchange
PASS  generic RuntimeGatePipeline sequential early-stop semantics
PASS  permission/cache/freshness gate concepts are separated in the component model
PASS  current HEAD CI full matrix green
```

这些部分保留 **PASS / FREEZE**；下一批不要重写成另一套状态机。

但 R4-A3 Exit Gate 要求的不是“新增一个可测试的 gate library”，而是：

> **Provider runtime lifecycle / permission / endpoint / cache / freshness 必须真正进入 formal capability evidence control flow，并沿 ProviderExchange → RawWriter → persisted evidence 闭合。**

当前 HEAD 尚未满足这一点。

本轮存在 3 个 P0 correctness / governance blocker，以及 1 个 P1 lifecycle integration 缺口：

```text
P0-01 RuntimeGatePipeline 未接入 formal Spike / Provider execution path
P0-02 Runtime gate evidence 只记录 request_id，没有 RawWriter persisted evidence identity
P0-03 Production account boundary 使用 blacklist（not Trial == Production），不是 positive identity / frozen production profile
P1-01 subscription lifecycle states 未接入现有真实 L1 subscription control flow
```

因此 **R4-B1 不得启动**。

---

# 1. 已通过并冻结的实现

## 1.1 SDK lifecycle core —— PASS / FREEZE

保留当前 `ashare_state.providers.lifecycle.SdkLifecycle`：

```text
INIT
  -> SDK_UNAVAILABLE
  -> LOAD_FAILED
  -> LOGIN_FAILED
  -> AUTH_REJECTED
  -> SESSION_READY

SESSION_READY / UNSUBSCRIBED
  -> SUBSCRIBE_STARTED
  -> CALLBACK_ACTIVE
  -> UNSUBSCRIBED

any state -> LOGGED_OUT via close()
```

继续保留：

```text
illegal transition -> explicit error
transition history -> from/to/reason/evidence/at
terminal state -> require_ready() typed failure
close() -> idempotent cleanup
```

## 1.2 Session / provider terminal early-stop —— PASS / FREEZE

当前正式 provider facade 已把：

```python
self.session.lifecycle.require_ready(endpoint)
```

放在 `call_exchange()` 第一层，先于 capability gate 与 endpoint fn。

这已经满足：

```text
SDK/load/auth terminal failure
-> no later provider business fn
-> no exchange/envelope for refused call
```

下一批不得把 lifecycle check 下移到 endpoint 调用之后。

## 1.3 RuntimeGatePipeline component semantics —— PASS AS COMPONENT

现有 component 已正确表达：

```text
AUTH_ACCOUNT
PERMISSION
ENDPOINT_AVAILABLE
CACHE_METADATA
FRESHNESS_ASOF
BUSINESS_DATA
```

并且：

```text
FAIL / NOT_TESTABLE -> downstream SKIPPED_BLOCKED
downstream evaluate() does not run
provider_calls_fired supports call-count proof
permission before cache
freshness before business
```

这部分作为可复用 primitive 保留。

注意：本项只给 **component-level PASS**，不等于 formal runtime wiring PASS。

## 1.4 CI —— PASS

Reviewer 正向核验 current HEAD `b5284bdc...` Actions run 56：

```text
Windows / Python 3.14 -> SUCCESS
  Ruff lint     SUCCESS
  Ruff format   SUCCESS
  Mypy          SUCCESS
  Pytest        SUCCESS
  Spike gates   SUCCESS

Windows / Python 3.12 -> SUCCESS
Ubuntu  / Python 3.14 -> SUCCESS
workflow overall      -> SUCCESS
```

CI 不是本轮 blocker。

---

# 2. P0-01：RuntimeGatePipeline 未进入 formal control flow

## 2.1 当前结构

本批新增：

```text
src/ashare_state/providers/runtime_gates.py
```

并新增 component/integration tests。

但本批 diff **没有**把该 pipeline 接入现有正式 Spike / Probe runtime：

```text
src/ashare_state/spike/probes.py        未修改
src/ashare_state/spike/runner.py        未修改
src/ashare_state/spike/target.py        未修改
formal ProbeExecutor / golden router    未改为消费 RuntimeGatePipeline
```

现有 `test_runtime_gate_separation.py` 直接构造 `_CountingProbe`，由测试自己创建 `RawEnvelope / ProviderExchange`，然后直接调用：

```text
RuntimeGatePipeline([...]).evaluate()
```

它证明了 library 本身 early-stop 正确，但没有证明真实 formal path 会使用这些 gates。

## 2.2 为什么这是 blocking

R4-A3 的目标是：

```text
Provider runtime formal truth
  -> AUTH
  -> PERMISSION
  -> ENDPOINT
  -> CACHE/METADATA
  -> FRESHNESS
  -> BUSINESS
  -> formal capability evidence
```

如果正式 Spike/probe 路径仍可直接调用既有 probe，不经过 `RuntimeGatePipeline`，则：

```text
gate library = optional helper
formal runtime = 仍可绕过
```

这不满足“gates as code / fail-closed”的项目长期原则。

## 2.3 强制修复

下一批必须建立**一个唯一正式 gate execution boundary**。

推荐结构（名称可调整，语义不可弱化）：

```text
FormalRuntimeGateExecutor / CapabilityProbePlan
  ↓
AUTH_ACCOUNT
  ↓
PERMISSION
  ↓
ENDPOINT_AVAILABLE
  ↓
required CACHE_METADATA
  ↓
FRESHNESS_ASOF
  ↓
BUSINESS_DATA
```

正式 Provider/Spike capability proof 必须通过该 boundary。

至少做到：

```text
[ ] formal capability proof / probe orchestration 明确调用 RuntimeGatePipeline
[ ] 不能由 caller 选择“跳过 permission/freshness 直接 business fetch”
[ ] blocking gate 后真实 target/provider endpoint call count 为 0
[ ] SpikeCase / capability proof 从该 pipeline result 派生
[ ] static/control-flow test 防止 formal path 绕过 gate boundary
```

不要求把所有历史普通业务便利函数都强制套 gate；要求的是 **formal proof / capability approval 所消费的路径唯一且不可绕过**。

---

# 3. P0-02：A3-05 Persisted Evidence Closure 尚未成立

## 3.1 当前实现

`runtime_gates._fire_probe()` 当前：

```text
probe()
-> ProviderExchange
-> inspect exchange.envelope
-> GateResult.evidence_ref = request_id
```

它没有执行：

```text
RawWriter.write(exchange)
```

也没有得到/绑定：

```text
meta_artifact URI
payload_artifacts[]
content_hash
schema_hash
persisted evidence hash
```

当前新增测试只验证：

```text
evidence_ref.startswith("req-ok-")
evidence_ref.startswith("req-fail-")
```

这只是 request identity，不是 immutable persisted evidence identity。

## 3.2 与既有正式证据合同冲突

上一轮 R4-A3 A3-05 明确要求：

```text
Provider call
-> ProviderExchange
-> RawWriter
-> persisted meta/payload evidence
-> SpikeCase / Gate result
```

不能把：

```text
ProviderExchange exists
```

等同于：

```text
formal evidence persisted
```

现有 R4-A2.x / CR-1.x 已经花多轮审计把 provider evidence 的 SoR 固定为 RawWriter persisted identity；R4-A3 不能在新 gate 层重新退化为 request-id-only evidence。

## 3.3 强制修复

推荐复用已有 `ProbeExecutor.call` / RawWriter 边界，而不是在 `runtime_gates.py` 自己复制一套 writer。

正式 probe gate 应得到类似：

```text
PersistedExchangeView / RawWriteResult
  exchange
  evidence_uri (meta anchor)
  evidence_hash
  payload_artifacts[]
```

然后 `GateResult` 至少需要能追溯：

```text
provider exchange request_id
persisted evidence URI
persisted evidence hash
```

可通过新增字段或稳定 typed evidence object 实现；不要把多个意义继续塞进一个模糊 `evidence_ref`。

必须增加对抗测试：

```text
[ ] permission PASS -> exchange persisted -> GateResult binds exact meta URI/hash
[ ] permission FAIL -> failure exchange persisted -> GateResult binds exact failure meta URI/hash
[ ] endpoint PASS/FAIL 同样闭合
[ ] business PASS/FAIL 同样闭合
[ ] persisted meta missing/tampered -> formal proof BLOCK
[ ] request_id 存在但 Raw evidence 未落盘 -> 不得视为 formal evidence PASS
[ ] blocking gate 后 downstream zero provider call AND zero Raw evidence
```

---

# 4. P0-03：Production Account Boundary 是 blacklist，不是 positive identity

## 4.1 当前实现

`AccountProfile.from_scrubbed()` 当前按启发式：

```python
kind = "TRIAL_SIMULATION" if TotalWeekFlow == 10 else "ACCOUNT"
```

所以任何“不像已知 Trial 特征”的 profile 都会得到：

```text
ACCOUNT_<hash>
```

随后 capability approval 的两个入口仅拒绝：

```text
TRIAL_*
FAKE*
UNKNOWN
empty
```

测试甚至明确把：

```text
ACCOUNT_abc123
```

当成 production account 对照并允许 APPROVED。

## 4.2 为什么这是 fail-open

项目当前治理真相仍是：

```text
正式账号尚未开通/确认
正式 P0-M-1B 前必须：
  正式账号 Profile 人工确认
  freeze production_account_profile_id
```

因此在正式账号还没有被 positive-confirm / frozen 之前：

```text
not known trial != production
```

“只黑名单拒绝 Trial/Fake/Unknown”会让一个未知普通账号、教育账号、非正式账号、供应商其他套餐，只要 profile 不恰好符合 `TotalWeekFlow == 10`，就进入 `ACCOUNT_*` 并具备 capability APPROVED 资格。

这与：

```text
CI/Fake = structure truth only
Trial = connectivity only
Production account = formal truth only
```

冲突。

## 4.3 强制修复：positive production identity

不要继续扩展 Trial 黑名单。

需要一个显式 positive contract，例如：

```text
AccountKind = UNKNOWN | TRIAL | PRODUCTION
```

或：

```text
frozen production_account_profile_id / allowlisted profile identity
```

正式 approval 必须要求：

```text
account_profile_id == explicitly configured/frozen production identity
AND profile parsed
AND entitlement verified
AND formal account kind == PRODUCTION
```

在当前“正式账号未确认”状态下，正确行为应是：

```text
production identity unavailable
-> NOT_TESTABLE / BLOCKED
-> no capability APPROVED
```

而不是把 `ACCOUNT_*` 自动当作 production。

必须同步修改：

```text
verify_production_account()
_validate_evidence()
approve_from_spike_run()
formal runtime AuthAccountGate / production proof input
```

Required adversarial tests：

```text
[ ] arbitrary ACCOUNT_x is NOT sufficient for production approval
[ ] unknown non-trial profile does not auto-upgrade to PRODUCTION
[ ] trial heuristic miss cannot grant production truth
[ ] frozen production id exact-match -> only then eligible
[ ] mismatched account id -> BLOCK
[ ] no frozen production id configured -> formal approval BLOCK / NOT_TESTABLE
[ ] run_kind=PRODUCTION never substitutes for production account identity
```

不要把真实账号 secret 写入 Git。freeze 的应是 scrubbed/stable profile identity 或安全配置引用，不是 username/token/password。

---

# 5. P1-01：Subscription lifecycle states 尚未进入真实 L1 control flow

## 5.1 当前情况

`SdkLifecycle` 已定义：

```text
SUBSCRIBE_STARTED
CALLBACK_ACTIVE
UNSUBSCRIBED
```

但现有真实 Trial L1 脚本：

```text
scripts/spike/l1_subscription_test.py
```

仍然直接：

```text
import AmazingData
ad.login
SubscribeData.register
run/start
callback
unregister
stop
ad.logout
```

并用自己的：

```python
lifecycle: dict[str, object] = {}
```

记录 register/run/unregister/stop 状态，没有驱动新 `SdkLifecycle.transition()`。

因此目前：

```text
login/load/logout states -> real control flow integrated
subscription/callback/unsubscribe states -> state-machine model only
```

## 5.2 下一批要求

不要求把 Trial L1 误升级为 Production proof；它仍只能是 connectivity evidence。

但要让 lifecycle 合同与真实控制流一致，至少建立一个 subscription wrapper / controller：

```text
SESSION_READY
-> register success -> SUBSCRIBE_STARTED
-> first valid callback / callback activation -> CALLBACK_ACTIVE
-> unregister/stop complete -> UNSUBSCRIBED
-> logout -> LOGGED_OUT
```

并保持：

```text
unregister/stop retry safe
callback after UNSUBSCRIBED does not silently reactivate state
registration failure does not fake SUBSCRIBE_STARTED
```

现有脚本应消费该 controller，而不是维护第二套 lifecycle dict 作为 correctness SoR。

---

# 6. P1 Governance：SHA truth / 状态重复

管理总册头部当前再次记录了错误完整 SHA：

```text
记录值：de9bf1ab6c5a75e4d57b8b84e5b16b20ed1ba2fe
真实值：de9bf1ab6f499b20916f8277dba45c21880fd908
```

Reviewer 以 GitHub commit object 为准。

同时 §40 存在重复 workstream 行：

```text
R4-A3 已有 DONE / PENDING_REVIEW
后面又有 R4-A3 PLANNED / PENDING
R4-B1 / R4-B2 / CR-2 也出现重复旧行
```

下一批必须清理“当前真相”区域的重复状态，但**不删除历史 DEVLOG / Git history**。

本轮治理状态应为：

```text
R4-A2.x / CR-1.x = CLOSED / VERIFIED
R4-A3 = DONE / REOPENED
R4-A3.1 = REQUIRED / ACTIVE NEXT
R4-B1 = BLOCKED_BY_R4-A3.1
R4-B2 = BLOCKED
CR-2 = sequenced after R4-B2
Production P0-M-1B = BLOCKED
```

ADR-019 当前关于 Runtime Gates / Trial Production boundary 的表述存在 overclaim；下一批采用 amendment（可继续 ADR-019 amendment，若 production account positive-identity 形成长期新 contract，也可新 ADR）。历史原文保留。

---

# 7. R4-A3.1 推荐实施顺序

```text
Batch A — Formal Runtime Gate Wiring
  formal capability probe plan
  RuntimeGatePipeline cannot be bypassed
  real provider/target call-count early stop

Batch B — Persisted Gate Evidence
  reuse ProbeExecutor / RawWriter
  bind request_id + evidence URI + evidence hash
  success/failure both persisted

Batch C — Positive Production Account Identity
  explicit AccountKind / frozen production profile identity
  no blacklist-only approval
  no configured production identity -> fail closed

Batch D — Subscription Lifecycle Integration
  wrapper/controller drives SdkLifecycle states
  trial L1 script consumes it

Batch E — Adversarial Regression
  bypass guard
  missing/tampered persisted evidence
  unknown ACCOUNT_x cannot approve
  downstream zero call/evidence
  existing R4-A2.x/CR-1.x suite zero regressions

Batch F — Governance
  DEVLOG append
  DEVELOPMENT_MANAGEMENT current truth cleanup
  ADR-019 amendment / new ADR if needed
  exact implementation SHA
  exact job-level CI truth
```

---

# 8. Exit Gate：R4-A3.1 → R4-B1

只有同时满足：

```text
[ ] formal capability proof actually executes RuntimeGatePipeline (or equivalent single gate boundary)
[ ] formal path cannot bypass permission / endpoint / freshness prerequisites
[ ] blocking prerequisite -> dependent provider call count == 0
[ ] blocking prerequisite -> dependent Raw evidence count == 0
[ ] every provider gate probe success/failure is persisted through RawWriter
[ ] Gate result binds exact persisted evidence URI/hash, not request_id only
[ ] missing/tampered persisted evidence fails closed
[ ] production truth uses positive/frozen production account identity
[ ] arbitrary ACCOUNT_* cannot approve
[ ] no configured production identity -> approval blocked / not-testable
[ ] RunKind.PRODUCTION cannot substitute for account identity
[ ] subscription lifecycle states drive actual subscription control flow
[ ] Trial L1 remains connectivity-only and cannot enter production approval
[ ] lifecycle terminal early-stop current PASS behavior remains intact
[ ] RuntimeGatePipeline component current PASS behavior remains intact
[ ] R4-A2.x / CR-1.x frozen contracts remain intact
[ ] current required CI matrix full green
[ ] docs/ADR match runtime and exact SHA truth
```

满足后 Reviewer 才能：

```text
R4-A3 / R4-A3.1 -> VERIFIED
R4-B1 Capability Endpoint Proof -> START
```

---

# 9. 禁止事项

本批禁止：

```text
启动 R4-B1 主实现来绕过 A3 integration gap
启动 R4-B2 / CR-2 / Feature / State 大工作面
把 request_id 当 persisted evidence identity
为省事让 gate 自己生成 synthetic success exchange
把 non-trial / ACCOUNT_* 默认解释为 PRODUCTION
把 production account secret 写进 Git
削弱已有 R4-A2.x / CR-1.x frozen contracts
通过跳过测试/放松 CI 掩盖 formal-path wiring failure
```

允许并行：

```text
Golden / Trading Rule 人工 review 准备
正式生产账号开通外部准备
R4-B1 设计分析（不得启动依赖 A3 formal gate 的正式实现）
```

---

# 10. 变更记录四问

下一批 notes / ADR 必须回答：

```text
1. 为什么 component-level gate tests 不能证明 formal runtime gate 已闭合？
2. 如何保证每一个 formal capability proof 都不可绕过 RuntimeGatePipeline？
3. 为什么 GateResult 必须绑定 RawWriter persisted identity，而不是 request_id？
4. 为什么 production identity 必须 positive-confirm / frozen，而不能采用“非 Trial 即 Production”的 blacklist？
```

并记录替代方案与成本收益。

---

# 11. Reviewer Handoff

下一轮 Reviewer 重点只检查 R4-A3.1 四件事：

```text
A. formal gate wiring
B. persisted Raw evidence binding
C. positive production account identity
D. subscription lifecycle integration
```

同时回归：

```text
lifecycle terminal early stop
R4-A2.x / CR-1.x frozen contracts
full CI matrix
```

如果上述全部通过且无新的 correctness regression，则给 R4-A3 **VERIFIED** 并进入 R4-B1；不要再次扩展与本批无关的新工作面。
