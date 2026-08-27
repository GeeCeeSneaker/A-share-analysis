# ADR-019: SDK Runtime Lifecycle State Machine + Runtime Gate Separation（R4-A3）

- 状态：ACCEPTED
- 日期：2026-08-26
- 依据：R4-A2.11/CR-1.2.7 复审（VERIFIED，审计链 CLOSED）→ R4-A3 开发工作要求（A3-01..05，audit 20260826）
- 关系：无前驱 amendment——新 runtime 契约；与 ADR-018 的 review 工作流互补
- 登记变更：DM-CR-20260826-030 / 031 / 032 / 033（管理总册 §61）

## 1. 为什么（A3-01）

Provider runtime 的流程位置此前只能从异常字符串推断（"login fail" → 认为没登录；
TypeError → 认为权限拒绝）。审计要求：SDK unavailable / load failed / login
failed / auth rejected / session ready / subscribe / callback / unsubscribe /
logout 必须是**显式状态机**，terminal 状态 early-stop，terminal 后不得再有
business call，cleanup 幂等。

## 2. 怎么改

### 2.1 `ashare_state.providers.lifecycle.SdkLifecycle`

```text
INIT -> SDK_UNAVAILABLE | LOAD_FAILED | LOGIN_FAILED | AUTH_REJECTED | SESSION_READY
SESSION_READY/UNSUBSCRIBED -> SUBSCRIBE_STARTED -> CALLBACK_ACTIVE -> UNSUBSCRIBED
任意状态 -> LOGGED_OUT（仅经 close()，幂等；对失败态关闭是合法清理）
```

- 非法跳转 raise（编程错误显式暴露）；每次迁移记录
  `LifecycleTransition(from, to, reason, evidence_ref, at)`；
- `require_ready(action)`：terminal / 非 session-alive →
  `ProviderLifecycleTerminalError`（ProviderError 子类，context 携带
  state/reason/evidence/refused_action/early_stop）——在 endpoint 函数
  **调用之前**抛出。

### 2.2 集成（真实控制流，非文档）

- `AmazingDataSession`：load_sdk 失败 → SDK_UNAVAILABLE / LOAD_FAILED；
  login `ProviderAuthError` → AUTH_REJECTED；其他 login 失败 → LOGIN_FAILED；
  成功 → SESSION_READY（reason/evidence=account_profile_id）；`logout()` →
  `lifecycle.close()`（幂等，失败态关闭合法）。
- `AmazingDataProvider.call_exchange`：**第一道**是 lifecycle 门
  （`require_ready(endpoint)`）——terminal 后 capability gate 与 SDK 函数
  都不会执行，也不产生 exchange/evidence。

### 2.3 Runtime Gates（A3-02，`ashare_state.providers.runtime_gates`）

六类 gate 显式分离，绝不折叠为单一 "provider unavailable"：

```text
AUTH_ACCOUNT        会话状态 + 账号 profile 可证性（纯本地，0 调用）
PERMISSION          broker 侧 entitlement（真实 probe exchange）
ENDPOINT_AVAILABLE  端点可达（真实 probe exchange——缓存不可替代）
CACHE_METADATA      必需本地元数据有效性（纯本地，0 调用）
FRESHNESS_ASOF      data as-of vs required as-of（纯比较，0 调用）
BUSINESS_DATA       业务取数（真实 exchange）
```

每个 `GateResult`：explicit status（PASS/FAIL/**NOT_TESTABLE**/SKIPPED_BLOCKED）
+ blocking reason + traceable evidence_ref + `provider_calls_fired` 计数。

`RuntimeGatePipeline`（A3-03 early stop）：顺序评估；首个 blocking
（FAIL 或 NOT_TESTABLE——**不可证即阻断**）之后，后续 gate 标记
SKIPPED_BLOCKED 且其 `evaluate()` **从不执行**——证明靠计数器，不靠最终
异常。非掩盖性由顺序 + early stop 编码：PERMISSION 先于 CACHE（缓存健康
不能掩盖权限失败）；ENDPOINT 必须真实 probe（缓存命中不是 endpoint proof）；
FRESHNESS FAIL 阻断 BUSINESS（陈旧数据不得降级为 "有数据即 PASS"）。

### 2.4 Trial/Fake 边界（A3-04）

capability approval 双入口拒绝非生产账号：`_validate_evidence` 与
`approve_from_spike_run` 均拒绝 `TRIAL_*` / `FAKE*` / `UNKNOWN` / 空
account_profile_id——run kind 为 PRODUCTION 本身不构成 production truth。

## 3. 备选方案与拒绝理由

| 备选 | 拒绝理由 |
|---|---|
| 异常字符串映射"状态"（现状） | 审计明令禁止；分类置信度低且不可测 |
| lifecycle 交给调用方自觉维护 | "记得检查"型契约（历轮审计已多次拒绝同类） |
| gates 折叠为一个 provider-unavailable 布尔 | 审计 A3-02 明令禁止；不同性质失败的修复路径与证据完全不同 |
| NOT_TESTABLE 视为非阻断 | 违反 fail-closed：不可证 = 不能放行 business truth |
| 权限失败用缓存 entitlement 放行 | 缓存命中掩盖权限失败（审计 §7.2 明示反例） |
| 用 OS 进程锁/信号量做 early stop | 跨平台语义不一致；单进程状态机 + typed error 足够且可测 |

## 4. 成本与收益

- 成本：provider/session 构造需携带 lifecycle（测试 fake 同步更新）；
  call_exchange 每次多一次状态检查（纯内存，可忽略）。
- 收益：流程位置显式可测；terminal 后零 business call 由**构造**保证
  （fault-injection 以 call/exchange/evidence 计数证明）；gate 分离使
  permission/freshness 失败的证据与修复路径各自可审计；R4-B1 的
  capability endpoint proof 可直接复用 ENDPOINT_AVAILABLE/PERMISSION gate。

## 5. 测试

- `tests/unit/test_sdk_lifecycle.py`（15）：状态机全迁移 / terminal 集 /
  幂等 close / 非法跳转 / require_ready 全拒绝语义 / history 审计。
- `tests/integration/test_runtime_early_stop.py`（11）：SDK absent /
  load 异常 / auth 拒绝 / network 失败 的 call-count 证明；terminal 后
  endpoint 函数零调用 + 零 envelope；INIT 拒绝；READY 对照组；真实
  session login/logout 驱动 lifecycle。
- `tests/integration/test_runtime_gate_separation.py`（15）：各 gate
  语义 / pipeline 全过 / permission-fail 阻断（probe 计数==1, business==0）/
  缓存不掩盖权限 / freshness 阻断 business / cache-metadata 阻断 /
  endpoint 失败阻断 / NOT_TESTABLE auth 全阻断 / 结果可审计性。
- `tests/integration/test_trial_production_boundary.py`（7）：TRIAL/FAKE/
  UNKNOWN/空账号在两个 approval 入口拒绝；生产账号对照；spike-run 路径
  防御纵深（monkeypatch 创建门后仍拒）。

---

## Amendment 2026-08-27（R4-A3.1，audit 20260827）

R4-A3 复审 REOPEN（三点）：gate 组件未接入 formal execution path；gate
evidence 仅 request_id，缺 RawWriter persisted identity；trial 边界为
blacklist（fail-open）。本 amendment 记录接线后的最终契约。

### A.1 唯一正式 gate 执行边界（P0-01）

`ashare_state.spike.formal_gates.FormalRuntimeGateExecutor`：唯一正式
gate 执行边界。正式 capability proof（B1 阶段，每个注册 capability 一个
`CapabilityProbePlan`）经它组装**冻结顺序**的 RuntimeGatePipeline：

```text
AUTH_ACCOUNT -> PERMISSION -> ENDPOINT_AVAILABLE
            -> CACHE_METADATA -> FRESHNESS_ASOF -> BUSINESS_DATA
```

- plan 必须定义全部六类 gate——caller 无法选择性跳过
  permission/freshness 直接 business fetch；
- blocking gate 后：downstream probe `fired == 0` 且零新 raw evidence
  （计数器 + raw 目录双证明）；
- gate proof 落 4 个 `formal_runtime_gate` case / capability：
  `GATE-{cap}-PERMISSION/ENDPOINT/BUSINESS`（绑定持久化 meta）+
  `GATE-{cap}-REPORT`（绑定六 gate 完整报告 artifact
  `{run}/gates/{cap}.json`）；
- `approve_from_spike_run` 调用 `_require_formal_gate_proof`：四 case
  缺一或非 PASS → 拒绝（early stop 因此天然阻断 approval）；AST
  静态守卫防绕过（approval 必须含该调用；executor 必须构造 pipeline；
  probe_b1 必须经 executor）。

### A.2 persisted evidence 闭合（P0-02）

`GateResult` 拆分证据语义：`request_id`（请求身份）/ `evidence_uri`
（RawWriter .meta.json 锚）/ `evidence_hash`——`has_persisted_evidence`
要求 URI+hash 同时存在；request_id 单独存在**不构成** formal evidence
PASS。probe exchange（成功与失败）经 `ProbeContext.evidence_from_exchange`
持久化后绑定；持久化失败（exchange 已 fire 但字节未落盘）将 PASS 降级
FAIL 并置 blocked_by（fail closed）。gate proof case 与 report artifact
纳入统一 evidence closure（篡改即阻断 verdict）。

### A.3 positive production identity（P0-03）

`ashare_state.providers.amazingdata.production_identity`：blacklist 改
allowlist。`configs/production_account.yaml` 冻结**scrubbed stable profile
id**（非凭证；空 = 未确认 = fail closed——当前仓库真值）。
`AccountProfile.kind` 为解析事实（TRIAL heuristics / UNKNOWN；非 trial
≠ production，旧 `ACCOUNT_` 前缀废除，改为 `UNKNOWN_<digest>`）。
`verify_production_account` / `_validate_evidence` / `approve_from_spike_run` /
`AuthAccountGate(require_production_identity=True)` 四处同步：仅 exact
match 放行；无 frozen identity 即 NOT_TESTABLE/BLOCKED；
RunKind.PRODUCTION 永不替代账号身份。

### A.4 subscription lifecycle 接线（P1-01）

`ashare_state.providers.amazingdata.subscription.SubscriptionController`：
L1 脚本 register/run/unregister/stop 经真实状态机驱动
（SESSION_READY → SUBSCRIBE_STARTED → CALLBACK_ACTIVE → UNSUBSCRIBED →
LOGGED_OUT）。register 失败不 fake SUBSCRIBE_STARTED；unregister/stop
retry-safe；UNSUBSCRIBED 后回调计数为 late callback，永不 reactivation；
诊断 dict 是 VIEW，状态机是 SoR。

### A.5 新增测试

- `tests/integration/test_formal_gate_wiring.py`（14）：executor 全过
  （六 gate 顺序 + 绑定 hash 读盘验证）/ permission 失败零下游调用零新
  evidence（失败 exchange 仍持久化绑定）/ probe_b1 全 capability /
  report artifact + REPORT case hash 闭合 / dry-run b1 阶段 / 持久化失败
  降级 FAIL / meta 与 report 篡改阻断 closure / 4 个 AST 静态防绕过守卫。
- `tests/unit/test_subscription_controller.py`（14）：register 失败不
  迁移 / 首回调激活（幂等）/ late callback 不 reactivation / retry-safe
  unregister / stop 完成 / run 失败记录不崩溃 / diagnostic 视图非 SoR。
- `test_trial_production_boundary.py` 重写（15）：旧 fail-open 断言
  （任意 `ACCOUNT_abc123` 可 approve）废除，改为 exact frozen match +
  mismatch 拒绝 + 无 frozen fail-closed + RunKind 不替代身份。

DM 登记见管理总册 §61 Change Log（DM-CR-20260827-040..043）。
