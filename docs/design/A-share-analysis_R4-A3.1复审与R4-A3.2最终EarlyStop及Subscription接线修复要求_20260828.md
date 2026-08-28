# A-share-analysis：R4-A3.1 复审与 R4-A3.2 最终 Early-Stop / Subscription 接线修复要求

> **Review Date**：2026-08-28 18:57 +08:00  
> **Reviewed Repository HEAD**：`d8232d6edde09798fd17149a79d71c56727f2358`  
> **Primary Implementation Commit**：`2c6ecdd1219b9964cc48a4145f99344894dcd1c1`  
> **CI Fix Commit**：`9bfe327dabdf4504e7252b745022b91ef71b88f8`  
> **DEVLOG Grandfathering Commit**：`e7b167c27ec163bc0f9d69f0765f2585d8d430da`  
> **CI Gate Sync Commit**：`af8a28a92b6a609047597ed8b403996a6e405ead`  
> **Documentation Commit**：`d8232d6edde09798fd17149a79d71c56727f2358`  
> **Previous Reviewer Requirement Commit**：`cdc29a341fc73f113ea766f639678b201052ee3f`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **R4-A2.x / CR-1.x**：**CLOSED / VERIFIED（保持冻结）**  
> **Next Batch**：**R4-A3.2 Final Persistence-Early-Stop + Trial-L1 Wiring Fix**  
> **R4-B1**：**BLOCKED until R4-A3.2 VERIFIED**  
> **R4-B2**：**BLOCKED**  
> **CR-2**：**按既定路线 sequenced after R4-B2**  
> **Production P0-M-1B**：**BLOCKED（production_account.yaml 仍为空 + 人工 Golden/Rule Review + 正式账号条件）**

---

# 0. Reviewer 最终裁决摘要

R4-A3.1 已经关闭上一轮绝大多数结构性缺口，本轮不应重写已完成部分。

以下项目给 **PASS / FREEZE**：

```text
PASS  FormalRuntimeGateExecutor 成为 formal capability gate boundary
PASS  approve_from_spike_run 强制消费 formal gate proof cases，anti-bypass 成立
PASS  PERMISSION / ENDPOINT / BUSINESS 正常成功 exchange 经 ProbeContext.evidence_from_exchange -> RawWriter 持久化
PASS  失败 ProviderError.exchange 同样可持久化并进入 gate evidence
PASS  GateResult 显式拆分 request_id / evidence_uri / evidence_hash
PASS  persisted meta / gate-report tamper 纳入 evidence closure
PASS  production identity 从 blacklist 改为 positive exact frozen identity
PASS  production_account.yaml 默认空 -> production truth fail closed
PASS  verify_production_account / _validate_evidence / approve_from_spike_run / AuthAccountGate 均采用 positive identity
PASS  SubscriptionController 本体驱动 SUBSCRIBE_STARTED / CALLBACK_ACTIVE / UNSUBSCRIBED，组件测试完整
PASS  current HEAD CI run 62 full matrix green
PASS  R4-A2.x / CR-1.x frozen regressions 未见重开理由
```

但 R4-A3.1 Exit Gate 仍有两个真实 runtime 缺口：

```text
P0-01  RawWriter persistence failure 目前是 pipeline 跑完后的 post-hoc downgrade；downstream provider calls 已可能发生
P1-01  Trial L1 脚本把 SdkLifecycle 变量立即覆盖为 dict，SubscriptionController 实际收到 dict，真实接线运行即失败
```

因此本轮不得给 R4-A3 VERIFIED，R4-B1 继续 BLOCKED。

为避免无止境拆批，下一批仅做 **R4-A3.2 两项最终修复**；不要再扩展与 A3 无关的新工作面。

---

# 1. 已通过并冻结：Formal gate wiring / anti-bypass

当前 `src/ashare_state/spike/formal_gates.py` 已建立正式 boundary：

```text
CapabilityProbePlan
  -> AUTH_ACCOUNT
  -> PERMISSION
  -> ENDPOINT_AVAILABLE
  -> CACHE_METADATA
  -> FRESHNESS_ASOF
  -> BUSINESS_DATA
```

`probe_b1_formal_gates()` 覆盖注册 capability；`approve_from_spike_run()` 通过 `_require_formal_gate_proof()` 要求 PERMISSION / ENDPOINT / BUSINESS / REPORT 四类 proof case 均存在且 PASS。

这一点已经满足上一轮“gate library 不得只是 optional helper”的要求，继续冻结。

说明：本轮不把 `b1 -> b2..b7` 是否做 run-global short-circuit 扩展成新 blocker。A3.1 的核心合同是 formal capability proof / approval 不可绕过 gate boundary；B1 对 capability-specific endpoint proof 的进一步细化留在 R4-B1，不在本批重新扩大范围。

---

# 2. P0-01：Persistence failure 不是即时 blocking，真实 downstream call 可继续

## 2.1 当前控制流

`_PersistedProbe.__call__()` 当前：

```text
provider probe()
  -> ProviderExchange success
  -> _persist(exchange)
       -> ctx.evidence_from_exchange(exchange)
       -> 若 RawWriter/persistence 异常：
            persist_error = "..."
            return
  -> 仍 return ProviderExchange
```

因此 `RuntimeGatePipeline` 看到的是：

```text
PERMISSION exchange status = OK
-> PermissionGate returns PASS
-> pipeline 继续 ENDPOINT_AVAILABLE
-> CACHE_METADATA
-> FRESHNESS_ASOF
-> BUSINESS_DATA
```

只有整个 pipeline 完成以后，`FormalRuntimeGateExecutor.execute()` 的 post-processing 才发现：

```text
result.status == PASS
AND probe.binding is None
```

然后把该 result 改写为 FAIL / blocked_by。

这会形成一个“报告看起来 early-stopped，但真实调用已经发生”的假象。

## 2.2 为什么这是 P0

上一轮 Exit Gate 明确要求：

```text
blocking prerequisite -> dependent provider call count == 0
blocking prerequisite -> dependent Raw evidence count == 0
request_id exists but Raw evidence did not persist -> NOT formal evidence PASS
```

如果 PERMISSION 的 exchange 成功，但 RawWriter 落盘失败，则 formal prerequisite 已经失败；系统必须在 **pipeline 继续执行 ENDPOINT/BUSINESS 之前** 把它变成 blocking FAIL。

当前是：

```text
persistence fail
-> pipeline still treats gate as PASS
-> downstream calls fire
-> after-the-fact rewrite report to FAIL
```

不满足 structural fail-closed。

## 2.3 Required Fix

不要只在 pipeline 结束后 post-process。

推荐把“call + persist + GateResult”做成 pipeline 内部的一次原子 gate evaluation，例如：

```text
PersistedPermissionGate.evaluate()
  -> provider exchange
  -> RawWriter persist
  -> persist success: PASS + exact binding
  -> persist failure: FAIL immediately

RuntimeGatePipeline sees FAIL
  -> ENDPOINT / CACHE / FRESHNESS / BUSINESS = SKIPPED_BLOCKED
  -> downstream provider call count == 0
```

实现形式可以是：

```text
Option A（推荐）
formal_gates.py 内新增 persisted GateCheck helper/subclass，直接返回已绑定 GateResult

Option B
调整 probe/gate contract，使 persistence error 在 _fire_probe 阶段被显式映射为 GateStatus.FAIL，且不能把原 success exchange 再解释为 PASS
```

禁止：

```text
先完整跑完 pipeline -> 再把 PASS 改 FAIL
```

## 2.4 Mandatory adversarial tests

至少新增：

```text
[ ] PERMISSION provider exchange succeeds, RawWriter persist fails
    -> PERMISSION = FAIL
    -> ENDPOINT probe fired == 0
    -> BUSINESS probe fired == 0
    -> downstream Raw evidence count == 0

[ ] ENDPOINT provider exchange succeeds, its persist fails
    -> ENDPOINT = FAIL
    -> BUSINESS probe fired == 0

[ ] BUSINESS persist fails
    -> BUSINESS = FAIL
    -> report cannot all_passed

[ ] request_id may exist, but URI/hash absent -> never PASS

[ ] existing provider-denial early-stop test stays green
[ ] success/failure persisted-evidence binding tests stay green
```

最好让测试直接断言 `_BoundReport.probes[kind].fired`，不能只断言最终 `blocked_by`。

---

# 3. P1-01：Trial L1 script 的 SdkLifecycle 被 dict 覆盖

## 3.1 当前实际代码

`scripts/spike/l1_subscription_test.py` 当前先做：

```python
lifecycle = SdkLifecycle()
lifecycle.transition(SdkLifecycleState.SESSION_READY, ...)
```

随后紧接着：

```python
events: list[dict] = []
lifecycle: dict[str, object] = {}
```

第二行把真正的 `SdkLifecycle` 对象覆盖成普通 dict。

后续：

```python
controller = SubscriptionController(lifecycle, sub)
controller.register(...)
```

因此真实运行时：

```text
SDK register 成功
-> SubscriptionController.register
-> self.lifecycle.transition(...)
-> dict 没有 transition
-> AttributeError
```

并且后面：

```python
state = lifecycle.state
lifecycle.close(...)
```

同样都不再指向状态机；finally 中 close 的异常还被 suppress，容易让错误更隐蔽。

所以“controller 单元测试 PASS”不能证明“真实 L1 脚本 wiring PASS”。

## 3.2 Required Fix

必须把 correctness SoR 与 diagnostic view 使用不同变量，最低要求：

```text
sdk_lifecycle: SdkLifecycle
lifecycle_diag: dict[str, object]
```

并确保：

```text
SubscriptionController(sdk_lifecycle, sub)
state = sdk_lifecycle.state
sdk_lifecycle.close(...)
report["lifecycle"] = lifecycle_diag
report["lifecycle_state_machine"] = controller.diagnostic()
```

不要再复用 `lifecycle` 一个名字承载两种不同类型。

## 3.3 Mandatory script-level regression

现有 `test_subscription_controller.py` 只证明 controller 本体。

下一批必须增加至少一个**消费真实脚本控制流**的测试，不能只测 controller：

```text
[ ] fake SDK login success
[ ] fake SubscribeData.register success
[ ] callback
[ ] unregister / stop
[ ] script/core flow reaches SUBSCRIBE_STARTED -> CALLBACK_ACTIVE -> UNSUBSCRIBED
[ ] no AttributeError / type shadowing
[ ] lifecycle_verdict derives from SAME SdkLifecycle object
[ ] logout/close terminal handling remains safe
```

推荐把脚本内部 SDK-dependent 主流程提取为可注入 fake 的小函数后做 behavioral test；若暂时不重构，至少要有 AST/static guard 防止 `SdkLifecycle` 变量随后被 dict 重绑定，但 behavioral test 仍应优先。

Trial L1 继续只能是 connectivity evidence，不得借此升级 production truth。

---

# 4. Positive Production Identity —— PASS / FREEZE

本批已把旧逻辑：

```text
not Trial -> ACCOUNT_* -> approval eligible
```

改成：

```text
parsed known trial -> TRIAL_SIMULATION_*
other parsed profile -> UNKNOWN_*
production truth -> exact match configs/production_account.yaml frozen id
```

当前 `production_account_profile_id` 为空，因此正式生产身份不可证，系统正确 fail closed。

继续冻结：

```text
verify_production_account exact-match
_validate_evidence exact-match
approve_from_spike_run exact-match
AuthAccountGate production exact-match / missing frozen id -> NOT_TESTABLE
RunKind.PRODUCTION != production identity
secrets must never enter Git
```

Production P0-M-1B 仍需真实正式账号开通后由人确认并 freeze scrubbed profile identity。

---

# 5. Persisted Evidence 正常路径 —— PASS / FREEZE

除 P0-01 的“persistence failure timing”外，以下已经成立：

```text
success exchange -> ProbeContext.evidence_from_exchange -> RawWriter
failure ProviderError.exchange -> same RawWriter path
GateResult splits request_id / evidence_uri / evidence_hash
Gate proof cases bind meta anchor URI/hash
meta/report tamper -> evidence closure failure
approval consumes proof cases
```

下一批修 P0-01 时不得退回 request-id-only evidence，也不得另造 private writer。

---

# 6. SubscriptionController component —— PASS / FREEZE

`providers/amazingdata/subscription.py` 本体的状态语义可接受：

```text
register success -> SUBSCRIBE_STARTED
first callback -> CALLBACK_ACTIVE
unregister/stop -> UNSUBSCRIBED
late callback after UNSUBSCRIBED -> counted, no reactivation
unregister retry-safe
step errors explicit
```

本轮只修脚本把正确 controller 接到错误变量的问题，不重写 controller。

---

# 7. CI Truth

Reviewer 正向核验 current HEAD：

```text
HEAD: d8232d6edde09798fd17149a79d71c56727f2358
Actions run: 33043352320 (run 62)
overall: SUCCESS
```

job-level：

```text
Windows / Python 3.12 -> SUCCESS
Windows / Python 3.14 -> SUCCESS
Ubuntu  / Python 3.14 -> SUCCESS

Ruff lint      SUCCESS
Ruff format    SUCCESS
Mypy           SUCCESS
Pytest         SUCCESS
Spike gates    SUCCESS
DEVLOG gate    SUCCESS on required leg
Management gate SUCCESS on required leg
```

因此 CI 当前 = **FULL MATRIX GREEN**。

但 CI 没有发现本轮两个 runtime gap：

```text
- persistence-failure test 没断言 downstream fired count
- subscription tests 只测 controller，不执行真实 L1 script wiring
```

这正是下一批需要补的测试盲点。

---

# 8. Governance

当前治理状态应更新为：

```text
R4-A2.x / CR-1.x = CLOSED / VERIFIED
R4-A3 = DONE / REOPENED
R4-A3.1 = DONE / REOPENED
R4-A3.2 = REQUIRED / ACTIVE NEXT
R4-B1 = BLOCKED_BY_R4-A3.2
R4-B2 = BLOCKED
CR-2 = sequenced after R4-B2
Production P0-M-1B = BLOCKED
```

下一逻辑提交同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
ADR-019 amendment / correction note（只需记录这两个 runtime correction，不删除历史）
```

管理总册的 Current Code Baseline / Reviewer Baseline 应使用**完整 40-char SHA**，不要只记录缩写。

关于 `9bfe327...` 的 DEVLOG grandfathered 例外：本轮接受其作为已披露历史修复，不要求 force-push 重写历史；但该 whitelist 必须保持**单一、精确 commit**，不得扩展成泛化绕过规则。

---

# 9. R4-A3.2 Exit Gate

下一轮只检查以下清单：

```text
[ ] persistence failure is converted to blocking FAIL DURING gate evaluation
[ ] PERMISSION persistence fail -> endpoint/business provider calls == 0
[ ] ENDPOINT persistence fail -> business provider calls == 0
[ ] downstream Raw evidence count == 0 after such block
[ ] no post-hoc "fake early-stop" report
[ ] normal success/failure persisted binding remains exact
[ ] L1 script no longer shadows SdkLifecycle with dict
[ ] SubscriptionController receives the real SdkLifecycle object
[ ] script-level behavioral test covers register/callback/unregister/stop wiring
[ ] positive production identity remains frozen/pass
[ ] lifecycle terminal early-stop remains pass
[ ] R4-A2.x / CR-1.x frozen contracts remain pass
[ ] current full CI matrix green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR match runtime + full SHA truth
```

若全部满足且无新的 correctness regression：

```text
R4-A3 / R4-A3.1 / R4-A3.2 -> VERIFIED / CLOSED
R4-B1 Capability Endpoint Proof -> START / ACTIVE NEXT
```

Production P0-M-1B 仍独立 BLOCKED，不能因代码 VERIFIED 自动放行。

---

# 10. Reviewer Handoff

下一轮 Reviewer **不要再扩展新主题**。只复核：

```text
1. persistence-failure structural early-stop
2. Trial L1 real script wiring
3. regression + CI + governance
```

Formal gate anti-bypass、positive production identity、正常 persisted evidence binding、SubscriptionController component、R4-A2.x/CR-1.x 均冻结，除非出现可复现回归。


---

# 11. Implementation Mapping（开发方填写，2026-08-28）

## P0-01 — Persistence-Failure Structural Early-Stop（§2）

| Requirement（§2.3/§2.4） | Implementation | Tests |
|---|---|---|
| 不做 pipeline 跑完后的 post-process | `execute()` 的 post-hoc 降级逻辑**删除**；替代为防御性 `FormalGateProofError`（PASS 无绑定抵达该处 = 原子 gate 契约失效 → fail loudly，绝不静默改写报告） | 代码审查点：formal_gates.py execute() 无 replace(status=FAIL) 改写路径 |
| Option A：persisted GateCheck helper/subclass 直接返回已绑定 GateResult | `_PersistedPermissionGate` / `_PersistedEndpointGate` / `_PersistedBusinessGate` + `_finalize_persisted`（formal_gates.py）：evaluate() 内 fire + persist + verdict 原子化——persist 成功绑三段身份；persist 失败且 exchange 成功当场降级 blocking FAIL；已 FAIL 结果保留具体原因并附加持久化失败信息 | test_permission_persistence_fail_blocks_immediately |
| PERMISSION persist fail → PERMISSION=FAIL → ENDPOINT/BUSINESS fired == 0 | 即时 FAIL → 冻结 pipeline early stop → 下游 gate SKIPPED_BLOCKED、下游 probe 从不 fire | 同上：`probes[ENDPOINT].fired == 0` + `probes[BUSINESS].fired == 0` + SKIPPED_BLOCKED 断言 + provider_calls_fired == 0 |
| downstream Raw evidence count == 0 | raw 目录零 `.meta.json`（`_raw_files(ctx) == []`） | 同上 |
| ENDPOINT persist fail → BUSINESS fired == 0 | `_SelectiveNoPersistContext.fail_on_factory({1})`（permission 正常持久化、endpoint 失败） | test_endpoint_persistence_fail_blocks_business |
| BUSINESS persist fail → BUSINESS=FAIL，report 不得 all_passed | `_SelectiveNoPersistContext.fail_on_factory({2})`；business fired == 1（上游全过，它确实 fire 了，只是持久化失败）；上游两个 exchange 正常落盘 | test_business_persistence_fail_refuses_all_passed |
| request_id may exist, but URI/hash absent → never PASS | 降级 result 携带 `last_request_id`（请求身份可追溯）但 URI/hash 为空 → `has_persisted_evidence == False`；proof case 为 VALIDATED_FAIL | test_request_id_alone_is_never_formal_evidence_pass |
| 既有 provider-denial early-stop 测试保持绿 | 零改动，全过 | test_permission_failure_blocks_with_zero_downstream_calls |
| 既有 success/failure persisted binding 测试保持绿 | 零改动，全过 | test_all_gates_pass_business_fires_and_evidence_binds |
| 断言 `_BoundReport.probes[kind].fired`（非只断言 blocked_by） | 全部新对抗测试直接断言 probe counters | 见上各行 |

## P1-01 — Trial L1 Script SdkLifecycle Wiring（§3）

| Requirement（§3.2/§3.3） | Implementation | Tests |
|---|---|---|
| SoR 与 diagnostic view 不同变量 | `sdk_lifecycle: SdkLifecycle`（SoR）+ `lifecycle_diag: dict`（VIEW）；一个名字不再承载两种类型 | AST guard：`lifecycle` 不得被 dict 注解/重绑定 |
| SubscriptionController 收到真实 SdkLifecycle | `SubscriptionController(sdk_lifecycle, sub)` | AST guard：构造首参必须是 `sdk_lifecycle` 变量 |
| state = sdk_lifecycle.state；sdk_lifecycle.close(...) | verdict 从 `sdk_lifecycle.state` 派生；finally 中幂等 `close(reason="logout")` | 行为测试断言 transitions 全路径 + close 幂等 |
| script-level behavioral test（推荐提取可注入 fake 的小函数） | `execute_subscription_flow(sdk, stage, duration_seconds, *, sleep, monotonic)`——SDK-dependent 主流程整体提取，main() 只留 login/env/session-gate/flush 与 terminal close | test_l1_subscription_script.py 加载真实脚本模块 + fake SDK（login 前置 / fake register / run() 触发 callback / unregister / stop） |
| register/callback/unregister/stop 走通状态机 | fake SDK run() 模拟一帧行情 → callback fires | test_flow_drives_the_real_state_machine_end_to_end：SESSION_READY→SUBSCRIBE_STARTED→CALLBACK_ACTIVE→UNSUBSCRIBED 全路径 + events_received==1 + status PASS |
| no AttributeError / type shadowing | SoR/view 命名分离 | 行为测试跑通即证明（dict 无 transition 会当场 AttributeError） |
| lifecycle_verdict derives from SAME SdkLifecycle object | `report["lifecycle_state_machine"]["state"]` 与返回的 lifecycle 对象同源 | 同上：两者同为 UNSUBSCRIBED；lifecycle_verdict PASS |
| logout/close terminal handling remains safe | `close()` 幂等（LOGGED_OUT 终态，重复 close 安全） | test_terminal_close_is_safe_after_flow |
| register 失败不 fake 状态 | 提前 return NOT_TESTABLE_PERMISSION + diag 记录 | test_register_failure_is_reported_not_faked：state 仍 SESSION_READY |
| Trial L1 只是 connectivity evidence | 脚本 verdict 语义未变（NOT_TESTABLE_* / FAIL_NO_EVENTS / PASS 均 connectivity 层级） | 既有脚本语义零改动 |

## Governance（§8）

- ADR-019 Amendment 2026-08-28（B.1/B.2：两个 runtime correction 的完整缺陷记录 + 修正理由 + Option A 选择依据；不删除历史）
- DEVELOPMENT_MANAGEMENT.md：头部（完整 40-char SHA：Reviewer 复审 HEAD `d8232d6edde09798fd17149a79d71c56727f2358` + R4-A3.1 各 commit 完整 SHA）+ Phase Status（R4-A3/A3.1 REOPENED 修正随 A3.2；R4-B1 BLOCKED until A3.2 VERIFIED；R4-B2 BLOCKED；CR-2 sequenced after R4-B2）+ §40/§41 重写为 R4-A3.2 + §61 DM-CR-20260828-044/045
- DEVLOG.md 顶部新条目（2026-08-28 R4-A3.2）
- `9bfe327` grandfathered 例外保持单一精确 commit，未扩展（whitelist 冻结）

## Verification Summary

- Local: **762 / 0**（754 → 762，+8）；ruff check / ruff format --check / mypy 全绿（退出码严格验证）
- 既有回归零破坏：provider-denial early-stop、success/failure persisted binding、gate separation（15）、trial boundary（15）、subscription controller（14）、lifecycle 单元（15）
- CI：推送后 API 正向确认（三腿）
