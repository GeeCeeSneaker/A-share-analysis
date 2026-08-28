# A-share-analysis：R4-A3.2 复审结论与 R4-B1 Capability Endpoint Proof 开发工作要求

> **Review Date**：2026-08-28 21:22 +08:00  
> **Reviewed Repository HEAD**：`5d50b16d94227aa895d82a265566f2a910d22bfd`  
> **Primary R4-A3.2 Implementation**：`cf76469865e963dcb39980297b0248d178d0012f`  
> **Previous Reviewer Requirement**：`44393a218edf57426b4dfb94f5a85b6f6b6c7d13`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**VERIFIED**  
> **R4-A3 / R4-A3.1 / R4-A3.2**：**CLOSED / VERIFIED**  
> **R4-A2.x / CR-1.x**：**CLOSED / VERIFIED（继续冻结）**  
> **Next Active Batch**：**R4-B1 Capability Endpoint Proof**  
> **R4-B2**：**BLOCKED until R4-B1 VERIFIED**  
> **CR-2**：**sequenced after R4-B2**  
> **Production P0-M-1B**：**BLOCKED（独立人工/正式账号 Gate 未满足）**

---

# 0. Reviewer 最终裁决

R4-A3.2 已关闭 R4-A3.1 复审剩余的两个 runtime blocker，且没有引入新的 correctness regression。

正式裁决：

```text
R4-A3           VERIFIED / CLOSED
R4-A3.1         VERIFIED / absorbed
R4-A3.2         VERIFIED / CLOSED
R4-A2.x/CR-1.x  CLOSED / VERIFIED / FREEZE
R4-B1           START / ACTIVE NEXT
R4-B2           BLOCKED_BY_R4-B1
CR-2            sequenced after R4-B2
P0-M-1B         BLOCKED independently
```

本轮**不创建 R4-A3.3**。

---

# 1. R4-A3.2 两项 blocker 复审

## 1.1 P0-01 Persistence Failure Structural Early-Stop —— VERIFIED / FREEZE

上一轮缺陷是：RawWriter persistence failure 只在 pipeline 完成后的 post-processing 阶段把 PASS 改写成 FAIL，导致报告看似 early-stop，但 ENDPOINT/BUSINESS provider call 可能已经发生。

当前实现已经把：

```text
provider exchange fire
-> RawWriter persist
-> persisted identity bind
-> gate verdict
```

合并到**同一次 gate evaluation**中。

核心结构：

```text
_PersistedPermissionGate.evaluate()
_PersistedEndpointGate.evaluate()
_PersistedBusinessGate.evaluate()
        ↓
original gate evaluate
        ↓
_finalize_persisted()
        ↓
persistence failure -> immediate GateStatus.FAIL
        ↓
RuntimeGatePipeline sees blocking FAIL
        ↓
downstream SKIPPED_BLOCKED
```

Reviewer 核验点全部满足：

```text
[PASS] PERMISSION persist fail -> ENDPOINT fired == 0
[PASS] PERMISSION persist fail -> BUSINESS fired == 0
[PASS] ENDPOINT persist fail -> BUSINESS fired == 0
[PASS] downstream provider_calls_fired == 0
[PASS] downstream zero Raw evidence
[PASS] request_id alone never becomes formal evidence PASS
[PASS] business persist failure cannot produce all_passed
[PASS] execute() no longer silently post-hoc rewrite PASS -> FAIL
[PASS] unreachable PASS-without-binding state fails loudly via FormalGateProofError
```

这项以后作为正式 formal-gate contract 冻结。

## 1.2 P1-01 Trial L1 Real Script Wiring —— VERIFIED / FREEZE

上一轮真实脚本错误是：

```python
lifecycle = SdkLifecycle()
lifecycle: dict[str, object] = {}
```

导致 `SubscriptionController` 实际收到 dict。

当前脚本已经明确拆分：

```text
sdk_lifecycle  = correctness SoR (SdkLifecycle)
lifecycle_diag = diagnostic VIEW (dict)
```

并提取：

```text
execute_subscription_flow(sdk, stage, duration_seconds, ...)
```

由脚本级 integration test 注入 fake SDK，真实执行：

```text
SESSION_READY
-> SUBSCRIBE_STARTED
-> CALLBACK_ACTIVE
-> UNSUBSCRIBED
-> close/logout -> LOGGED_OUT
```

Reviewer 核验点：

```text
[PASS] controller 接收 sdk_lifecycle 本体
[PASS] verdict 从同一个 sdk_lifecycle 派生
[PASS] register failure 不伪造 SUBSCRIBE_STARTED
[PASS] terminal close 幂等
[PASS] AST guard 防 lifecycle/dict 同名重绑
[PASS] script behavior test 覆盖真实 wiring，而非 controller 复制品
```

Trial L1 仍然只是 connectivity evidence，不提升为 Production truth。

---

# 2. R4-A3 全链冻结项

以下内容随本轮 VERIFIED 一并冻结，后续除非出现可复现 regression，不得机械重开：

```text
SdkLifecycle explicit state machine
terminal lifecycle -> provider endpoint zero call
FormalRuntimeGateExecutor single formal boundary
AUTH/PERMISSION/ENDPOINT/CACHE/FRESHNESS/BUSINESS explicit gates
formal approval anti-bypass (_require_formal_gate_proof)
ProviderExchange -> ProbeContext.evidence_from_exchange -> RawWriter
request_id / evidence_uri / evidence_hash semantic separation
success/failure exchange persisted evidence closure
meta/report tamper -> evidence closure block
positive/frozen production account identity
production_account.yaml empty -> fail closed
RunKind.PRODUCTION != production account identity
SubscriptionController runtime state integration
persistence-failure structural early-stop
R4-A2.x / CR-1.x all previously frozen exact-byte / lineage / Raw evidence contracts
```

---

# 3. CI Reviewer 正向确认

## 3.1 Primary implementation

GitHub Actions run：

```text
33167368684
head_sha = cf76469865e963dcb39980297b0248d178d0012f
conclusion = success
```

Job-level：

```text
Windows / Python 3.12  SUCCESS
Windows / Python 3.14  SUCCESS
Ubuntu  / Python 3.14  SUCCESS
```

三腿均执行并通过：

```text
Ruff lint
Ruff format check
Mypy
Pytest
Spike framework gates
AmazingData SDK absence check
required governance gates
```

## 3.2 Current reviewed HEAD

Current HEAD `5d50b16d...` 的 run `33167643119` 同样 overall success / full matrix green。

因此 CI 不是本轮保留项或 blocker。

---

# 4. Governance 复审

当前管理总册正确保持：

```text
R4-A3       DONE / REOPENED
R4-A3.1     DONE / REOPENED
R4-A3.2     DONE / PENDING_REVIEW
R4-B1       BLOCKED until reviewer verification
```

开发方没有提前自我标记 VERIFIED，符合治理约束。

ADR-019 采用 Amendment 2026-08-28 记录两项 runtime correction，保留了历史缺陷与修正原因，没有改写旧审计事实。

本 Reviewer verdict 提交后，下一逻辑开发提交必须把当前真相同步为：

```text
R4-A3 / A3.1 / A3.2 = CLOSED / VERIFIED
R4-B1 = ACTIVE / NEXT
R4-B2 = BLOCKED_BY_R4-B1
CR-2 = sequenced after R4-B2
P0-M-1B = BLOCKED
```

同步：

```text
docs/DEVLOG.md               append only
docs/project/DEVELOPMENT_MANAGEMENT.md current truth
```

不得删除历史 REOPENED 记录。

---

# 5. 下一阶段：R4-B1 Capability Endpoint Proof

## 5.1 目标

A3 已证明：

> formal capability proof 必须经过正式 Runtime Gate boundary，并具有 persisted evidence。

B1 要证明更具体的一层：

> **ENDPOINT_AVAILABLE 所证明的 endpoint，必须就是 capability contract 声明的真实 provider endpoint；不得用 unrelated/generic endpoint 的成功代替目标 endpoint proof。**

当前 `CAPABILITY_REGISTRY` 已声明每个 capability 的 `sdk_methods`，但现有 formal gate plan 中仍存在 stand-in：

```text
code_mapping_bj       -> generic BJ code-list probe
industry_taxonomy     -> stock_basic stand-in
equity_structure      -> stock_basic stand-in
部分 capability 的 endpoint gate -> calendar/code-list generic entitlement surface
```

这些在 A3 阶段可用于证明 gate mechanism，但在 B1 阶段不能继续被解释为 capability endpoint proof。

---

# 6. B1-01：显式 Endpoint Requirement Contract

`Capability.sdk_methods: tuple[str, ...]` 当前无法明确区分：

```text
全部都必须证明（ALL）
替代 endpoint 任选其一（ANY / OR group）
主 endpoint + fallback
多个 endpoint 分别服务同一 capability 的不同事实
```

B1 必须把这种语义显式化，禁止 reviewer/runner 根据 tuple 顺序猜测。

推荐引入 typed contract，例如：

```text
EndpointRequirement
  requirement_id
  endpoint/method
  provider_dataset
  mode = REQUIRED | ALTERNATIVE_GROUP
  group_id
  proof_role
```

或等价模型。

至少明确：

```text
trade_calendar
security_master
code_mapping_bj
daily_bar
security_status_history
adj_factor
corporate_action
equity_structure
industry_taxonomy
index_daily
```

每个 capability 到底要求哪些真实 endpoint proof。

不得在 Python 中用散落 if/else 隐式解释 registry tuple。

---

# 7. B1-02：Exact Endpoint Probe，不允许 unrelated stand-in

Formal ENDPOINT gate 必须调用与 Requirement 匹配的真实 target/provider exchange surface。

要求：

```text
[ ] target/provider 暴露缺失的 exact exchange methods
[ ] ENDPOINT gate evidence envelope.endpoint 与 requirement endpoint 精确匹配
[ ] provider_dataset 与 endpoint contract 可核验
[ ] endpoint failure 仍产生 first-class failure exchange + RawWriter evidence
[ ] 不允许 stock_basic 成功替代 industry endpoint proof
[ ] 不允许 generic code-list 成功替代 BJ mapping endpoint proof
[ ] 不允许 calendar 成功替代 daily_bar/index_daily endpoint proof
```

若某 endpoint 当前 SDK/account 无法验证：

```text
NOT_TESTABLE / FAIL_CLOSED
```

不得 fallback 到无关 endpoint 并标 PASS。

如果确实存在 provider 官方支持的替代 endpoint：必须在 endpoint contract 中以明确 `ALTERNATIVE_GROUP` 表达，而不是 runtime 静默 fallback。

---

# 8. B1-03：Permission Proof 与 Endpoint Proof 继续分离

必须保持 A3 的非掩盖性：

```text
PERMISSION
!=
ENDPOINT_AVAILABLE
!=
BUSINESS_DATA / semantic quality
```

例如：

```text
BaseData.get_code_list PASS
```

只能证明该 permission/entitlement probe 可用，不能证明：

```text
InfoData.get_industry_base_info
InfoData.get_equity_structure
InfoData.get_bj_code_mapping
```

存在、可调用或具备相应权限。

禁止重新把三者折叠成 “provider available = true”。

---

# 9. B1-04：Capability Approval 必须消费 exact endpoint identity

当前 `_require_formal_gate_proof()` 已要求 gate proof cases 存在且 PASS，但 B1 后仅“有一个 ENDPOINT case PASS”还不够。

approval path 必须能证明：

```text
capability requirement
<-> gate proof case
<-> ProviderExchange.envelope.endpoint
<-> provider_dataset
<-> persisted evidence URI/hash
```

推荐 endpoint proof case/artifact 显式携带：

```text
requirement_id
capability
expected_endpoint
actual_endpoint
provider_dataset
request_id
evidence_uri
evidence_hash
status
```

approval 对 mismatch 必须 fail closed。

不能只靠 case_id 名称推断 endpoint 真相。

---

# 10. B1-05：对抗测试

至少增加：

```text
[ ] exact endpoint PASS -> persisted exchange endpoint 与 requirement 完全一致
[ ] wrong/unrelated endpoint 返回 OK -> capability endpoint proof FAIL
[ ] generic permission endpoint PASS + target endpoint permission denied -> ENDPOINT FAIL
[ ] target endpoint missing/SDK drift -> NOT_TESTABLE/FAIL, no fake PASS
[ ] endpoint ProviderError.exchange -> failure evidence persisted + exact endpoint identity retained
[ ] endpoint evidence meta missing/tampered -> proof BLOCK
[ ] endpoint case actual_endpoint tamper -> approval BLOCK
[ ] alternative endpoint group：仅明确声明的 alternative 可满足，不相关 endpoint 不可满足
[ ] ALL requirements：缺任意 required endpoint -> capability cannot approve
[ ] no production frozen identity -> Production approval 仍 BLOCK（A3 regression）
[ ] endpoint blocker -> dependent business probe zero call/evidence（A3 regression）
[ ] existing 762-test baseline zero regression
```

建议增加结构守卫：

```text
registered capability requirements
== formal endpoint proof plan coverage
```

避免新增 capability 后忘记纳入 B1 proof。

---

# 11. B1-06：不要越界到 B2 / CR-2

本批只完成：

```text
Capability Endpoint Proof exactness
```

不提前启动：

```text
R4-B2 Publish Validation Exactness
CR-2 Provider-Normalized + Quarantine
Feature / State
```

允许为 B1 增加必要的 target/provider exchange adapter，但不要借机大规模重构 canonical 层。

---

# 12. B1 Governance

建议登记：

```text
DM-CR-20260828-046 Capability Endpoint Requirement Contract
DM-CR-20260828-047 Exact Endpoint Evidence Binding / Anti-Stand-In
DM-CR-20260828-048 Capability Approval Endpoint-Identity Enforcement
```

若 Endpoint Requirement Contract 改变长期 capability registry 语义，应新建 ADR（推荐 ADR-020）；不要把这一长期合同继续塞进 ADR-019 lifecycle/gate amendment。

必须记录四问：

```text
1. 为什么 generic permission endpoint 不能证明 capability-specific endpoint？
2. 如何表达 ALL / ANY / alternative endpoint 语义，避免 tuple 猜测？
3. 如何把 capability requirement 与 persisted ProviderExchange endpoint identity 绑定？
4. 为什么 endpoint proof 与后续 business-quality/publish validation 必须分阶段？
```

并记录替代方案、拒绝理由、成本收益。

---

# 13. R4-B1 Exit Gate

只有全部满足，Reviewer 才能给 R4-B1 VERIFIED：

```text
[ ] all registered capabilities have explicit endpoint requirements
[ ] requirement ALL/alternative semantics are explicit, not inferred
[ ] formal endpoint probes call exact provider methods
[ ] unrelated/generic stand-in cannot satisfy endpoint proof
[ ] endpoint/provider_dataset identities are bound to persisted evidence
[ ] success/failure exact endpoint exchanges both use RawWriter chain
[ ] capability approval consumes exact endpoint proof identity
[ ] wrong/missing/tampered endpoint proof fails closed
[ ] A3 persistence early-stop remains structurally true
[ ] positive production account identity remains frozen/fail-closed
[ ] R4-A2.x/CR-1.x frozen contracts remain intact
[ ] full required CI matrix green
[ ] DEVLOG / management / ADR accurately match runtime
```

满足后：

```text
R4-B1 -> VERIFIED
R4-B2 Publish Validation Exactness -> START
```

Production P0-M-1B 仍不会因此自动放行。

---

# 14. Reviewer Handoff

下一轮 Reviewer 重点：

```text
A. Endpoint Requirement Contract 是否消除 sdk_methods tuple 歧义
B. formal endpoint probe 是否为 exact endpoint，而非 stand-in
C. endpoint identity 是否进入 persisted proof + approval
D. wrong/missing/tampered endpoint 是否 fail closed
E. A3/A2/CR-1 frozen regression + full CI
```

除发现可复现 regression，不再回头重审 R4-A3 的已冻结主题。


---

# 10. Implementation Mapping（开发方填写，2026-08-28）

## B1-01 — Explicit Endpoint Requirement Contract

| Requirement（§2.2/§2.3） | Implementation | Tests |
|---|---|---|
| typed contract（requirement_id / endpoint / provider_dataset / mode / group_id / proof_role） | `src/ashare_state/providers/amazingdata/endpoint_requirements.py`：`EndpointRequirement` frozen dataclass + `EndpointRequirementMode`（REQUIRED / ALTERNATIVE_GROUP）+ `ProofRole`（ENDPOINT_PROOF / BUSINESS_PROOF——后者为 B2-B7 语义证明预留） | TestEndpointRequirementContract（6） |
| 覆盖全部 10 个注册 capability | `ENDPOINT_REQUIREMENTS` 表：13 条声明（security_master 双成员组；corporate_action 双 REQUIRED dividend+right_issue；其余单 REQUIRED） | test_contract_covers_every_registered_capability |
| contract 结构自检 | `validate_endpoint_requirements()`：id 唯一 / endpoint 为 Class.method / provider_dataset 非空 / REQUIRED 无 group / ALTERNATIVE_GROUP 有 group 且组 ≥2 成员 | test_contract_is_structurally_valid + mode/group 断言 |
| 唯一事实源（禁止散落 if/else） | gate（`GATE_PLAN_SPECS` 的 `endpoint_requirements` 从 `endpoint_requirements_for` 派生）、probe（`ENDPOINT_PROBE_SPECS` keyed by requirement_id）、approval（`_require_formal_gate_proof`）、守卫测试四处消费同一 contract | 结构守卫测试 + 代码审查点 |
| 显式 ALTERNATIVE_GROUP | security_master `listing_surface`：`BaseData.get_code_list`（当前快照）+ `BaseData.get_hist_code_list`（历史重建）——官方替代，任一可用即满足 | test_alternative_group_* |

## B1-02 — Exact Endpoint Probe

| Requirement（§2.3） | Implementation | Tests |
|---|---|---|
| ENDPOINT gate 调用与 Requirement 匹配的真实 exchange | `_ExactEndpointRequirementsGate`：每 requirement 一个 exact probe（factory 来自 `ENDPOINT_PROBE_SPECS`，keyed by requirement_id——plan 从 contract 派生，caller 无入口塞 stand-in） | test_every_capability_proves_its_exact_endpoint（10 capability 全 PASS，case 的 expected_value 含声明的 endpoint） |
| envelope.endpoint 与 requirement endpoint 精确匹配 | probe evaluation 原子（fire+persist+verdict）：`envelope.endpoint` **与** `envelope.provider_dataset` 精确匹配；mismatch = blocking FAIL（失败 exchange 的 endpoint 同样校验） | test_stand_in_endpoint_is_a_blocking_fail（industry 由 stock_basic 应答 → FAIL + case VALIDATED_FAIL + mismatch 记录 + business fired==0） |
| 不允许 stand-in（stock_basic ≠ industry_taxonomy；generic code-list ≠ BJ mapping；calendar ≠ daily_bar/index_daily） | 三个新 exact exchange：`get_bj_code_mapping_exchange` / `get_equity_structure_exchange` / `get_industry_base_info_exchange`（provider + Protocol + RealTarget + FakeTarget 四处同步）；R4-A3.1 的 stand-in probe 映射全部移除；daily_bar/index_daily 的 requirement 是 `MarketData.query_kline`（endpoint gate 不再用 calendar probe） | 同上 + FakeTarget fake exchange endpoint 身份精确 |
| 无法验证的 endpoint → NOT_TESTABLE/FAIL_CLOSED，不 fallback | denied exact endpoint（endpoint 身份正确、调用被拒）→ requirement FAIL，无 fallback 到无关 endpoint；失败 exchange 持久化绑定 | test_denied_exact_endpoint_is_fail_not_fallback |
| REQUIRED 全 PASS + 组 ≥1 成员 → PASS；否则 FAIL | verdict 汇总逻辑（REQUIRED 逐条；组 any）；FAIL = blocking（pipeline early-stop，下游 probe fired==0） | test_alternative_group_all_members_denied_is_fail（组全 denied → FAIL + 两组员各 fired==1） |
| registry 的 sdk_methods 不被散落解释 | registry tuple 保留为文档性事实；proof 语义全部由 typed contract 承载（一处声明三处消费） | 结构守卫 |

## B1-03 — Permission/Endpoint/Business 分离保持

| Requirement | Implementation | Tests |
|---|---|---|
| permission / endpoint / business gate 语义互不掩盖 | permission probe 保持共享 entitlement surface（get_code_list EXTRA_STOCK_A）；business fetch 语义不动；endpoint outcomes 独立于 business verdict | test_permission_denial_leaves_endpoint_probes_unfired（permission denied → endpoint probes fired==0 + 无 case fabrication）；test_alternative_group_single_member_pass_is_pass（endpoint gate PASS 的同时 business 独立 FAIL——分离证明） |

## B1-04 — Approval 消费 exact endpoint identity

| Requirement（§2.4） | Implementation | Tests |
|---|---|---|
| proof case 携带 requirement_id / capability / expected_endpoint / actual_endpoint / provider_dataset / request_id / evidence_uri / evidence_hash / status | 每 requirement 一个 proof case（`endpoint_requirement_case_id`）：expected/actual 字符串携带全部字段；evidence_ref/hash 绑 RawWriter 持久化 meta（成功与失败 exchange 都是证据） | test_every_capability_proves_its_exact_endpoint + stand-in 测试的 case 断言 |
| artifact 携带结构化身份 | REPORT artifact（`gates/{cap}.json`）新增 `endpoint_requirements[]`：requirement_id/capability/expected_endpoint/actual_endpoint/provider_dataset/actual_dataset/mode/group_id/status/reason/request_id/evidence_uri/evidence_hash——由 REPORT case evidence_hash（sha256）锚定 | test_gate_report_artifact_persisted_with_bindings（既有）+ approval 重验测试 |
| approval 对 mismatch fail closed | `_require_formal_gate_proof` 重写：REQUIRED 每 requirement 有 PASS case + evidence 绑定；组 ≥1 成员；**artifact 重验**（重算 sha256 == case hash；逐条与 contract 比对 expected_endpoint / actual_endpoint==endpoint / evidence 绑定非空）→ 任何 mismatch 拒绝 | test_approval_refuses_stand_in_actual_endpoint（actual_endpoint 改 calendar + re-bind hash → 拒绝） |
| 不能只靠 case_id 名称推断 | 身份从 hash 锚定的 REPORT artifact 读，不从 case-id 推断；artifact 不存在/无 entry / hash 不符均拒绝 | test_approval_refuses_tampered_artifact（bind 后改字节 → hash 拒绝）+ artifact missing 分支 |
| 缺 REQUIRED requirement case → 拒绝 | REQUIRED 逐条检查 case 存在 + PASS + 绑定 | test_approval_refuses_missing_required_case（jsonl 删行 → 拒绝） |

## B1-05 — 对抗测试 + 结构守卫

§2.5 验收矩阵逐项：

1. probe 返回不同 endpoint（registry 内 stand-in）→ gate FAIL + case VALIDATED_FAIL ✓（test_stand_in_endpoint_is_a_blocking_fail）
2. daily_bar/index_daily 用 calendar probe → FAIL ✓（requirement=MarketData.query_kline；calendar exchange 的 endpoint/dataset 不匹配 → mismatch FAIL——由 exact-match 机制结构性覆盖）
3. industry probe 返回 stock_basic → FAIL ✓（同 1）
4. code_mapping_bj 用 stock code list endpoint → FAIL ✓（requirement=InfoData.get_bj_code_mapping；generic code-list 的 endpoint/dataset 不匹配 → mismatch FAIL）
5. valid probe PASS（10 capability 全部 exact probe PASS）✓（test_every_capability_proves_its_exact_endpoint）
6. alternative group 全部成员 fail → FAIL ✓（test_alternative_group_all_members_denied_is_fail）
7. endpoint exchange fail（ProviderError）→ FAIL + 失败 exchange 持久化绑定 ✓（test_denied_exact_endpoint_is_fail_not_fallback）
8. permission fail → endpoint probes fired==0 ✓（既有 test_permission_failure_blocks_with_zero_downstream_calls 适配 + 新测试）
9. actual_endpoint tamper → approval BLOCK ✓（test_approval_refuses_stand_in_actual_endpoint）
10. 缺 REQUIRED case → 拒绝 ✓（test_approval_refuses_missing_required_case）
11. artifact hash tamper → 拒绝 ✓（test_approval_refuses_tampered_artifact）
12. 结构守卫：registered requirements == formal endpoint proof plan coverage ✓（TestStructuralGuard：contract 覆盖 == registry caps；probe specs == contract；GATE_PLAN_SPECS requirements == contract——新增 capability 漏纳入即测试红）

## Governance（Batch F）

- **ADR-020**（新 ADR——按 §8 要求独立成文，不塞 ADR-019 amendment）：Context / Decision（typed contract + exact gate + 身份消费）/ 四问（§7.4：typed contract vs 解释 registry tuple / per-requirement case vs 后缀方案 / ALTERNATIVE_GROUP vs 全 REQUIRED / mismatch 即时 FAIL vs warning）/ Consequences（含真实环境注记——SDK 手册端点的可用性由 Spike 阶段验证，本 ADR 固定身份合同）
- DEVELOPMENT_MANAGEMENT.md：头部（R4-A3/A3.1/A3.2 CLOSED / VERIFIED；R4-B1 DONE / PENDING_REVIEW）+ §40/§41 重写 + §61 DM-CR-20260828-046/047/048
- DEVLOG.md 顶部新条目（2026-08-28 R4-B1）
- 本 Implementation Mapping

## Verification Summary

- Local: **779 / 0**（762 → 779，+17）；ruff check / ruff format --check / mypy 全绿（退出码严格验证）
- 既有回归零破坏：persistence early-stop 对抗集（3）、L1 wiring（5）、gate separation（15）、trial boundary（15）、subscription controller（14）、approval from spike（6）、dry-run 全相位
- B1-06 边界遵守：未启动 R4-B2 publish 链 / golden 审计 / CR-2（§9 禁止项）
