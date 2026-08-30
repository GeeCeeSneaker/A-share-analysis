# ADR-020: Endpoint Requirement Contract（显式端点身份合同）

- **Status**: ACCEPTED（2026-08-28，R4-B1 批次）
- **Deciders**: Design / Audit Review（audit 20260828）+ 开发方
- **Date**: 2026-08-28
- **Work Requirement**: `docs/design/A-share-analysis_R4-A3.2复审结论与R4-B1开发工作要求_20260828.md`
- **Related**: [ADR-019](ADR-019_sdk_lifecycle_runtime_gates.md)（Runtime Gates——本 ADR 是其 ENDPOINT gate 的身份维度收口）

## 1. Context（audit 20260828 §2）

R4-A3.x 之后，formal ENDPOINT_AVAILABLE gate 的 probe 是一个
capability-chosen 调用——**没有任何机制强制这个 probe 真的调用该
capability 声明的官方 endpoint**：

- `industry_taxonomy` / `equity_structure` 的 endpoint probe 实际调用
  `get_stock_basic`（entitlement stand-in）；
- `daily_bar` / `index_daily` 的 endpoint probe 实际调用 calendar；
- `code_mapping_bj` 的 endpoint probe 实际调用 generic stock code-list。

一个 PASS 只证明"provider 能应答某请求"，不证明"该 capability 的官方
endpoint 可用"。若 `get_industry_base_info` 被拒而 `get_stock_basic` 可用，
gate 仍然 PASS——**fail-open**。同时 capability registry 的 `sdk_methods`
tuple 是文档性事实，被散落的 if/else 解释（capability A 用方法 1 的
probe，capability B 用方法 3 的 probe），没有单一审计入口；approval 只靠
case-id 名称（`GATE-{cap}-ENDPOINT`）推断 proof 存在，不验证 actual
endpoint 与声明一致——篡改/错位检测为零。

## 2. Decision

### 2.1 Typed contract（B1-01）

新模块 `ashare_state.providers.amazingdata.endpoint_requirements`：

```
EndpointRequirement(
    requirement_id   # 全局唯一："capability:Class.method"
    capability       # 所属 capability（registry key）
    endpoint         # SDK endpoint 身份（必须出现在 envelope.endpoint）
    provider_dataset # provider 侧 dataset 标签（必须出现在 envelope）
    mode             # REQUIRED | ALTERNATIVE_GROUP
    group_id         # ALTERNATIVE_GROUP 时必填（组内 >= 2 成员）
    proof_role       # ENDPOINT_PROOF | BUSINESS_PROOF（后者为 B2-B7 预留）
)
```

`ENDPOINT_REQUIREMENTS` 表覆盖全部 10 个注册 capability（13 条声明，
`validate_endpoint_requirements()` 结构自检：id 唯一 / endpoint 为
Class.method / REQUIRED 无 group / 组 >= 2 成员）。registry 与 contract 的
覆盖一致性由结构守卫测试强制（`registered requirements == formal endpoint
proof plan coverage`——新增 capability 漏纳入即测试失败）。

**ALTERNATIVE_GROUP 语义**（官方替代）：`security_master` 的
listing_surface 组——`BaseData.get_code_list`（当前快照）与
`BaseData.get_hist_code_list`（历史重建）互为官方替代，任一可用即满足
该 capability 的 endpoint proof。**不满足组语义的端点对（如
get_adj_factor 与 get_backward_factor——前/后复权因子是不同数据流）
不得编组**，各自 REQUIRED。

### 2.2 Exact endpoint probe（B1-02）

`spike/formal_gates.py` 的 ENDPOINT_AVAILABLE gate 重构为
`_ExactEndpointRequirementsGate`：**每个 requirement 一个 exact probe**，
probe factory 来自静态表 `ENDPOINT_PROBE_SPECS`（keyed by
requirement_id）——**gate 无法被塞入 caller 选择的 stand-in endpoint**
（`CapabilityProbePlan.endpoint_requirements` 直接从 contract 派生，无
caller 入口）。

每次 probe evaluation 原子（fire + persist + verdict，沿 R4-A3.2 P0-01）：

- exchange 的 `envelope.endpoint` **与** `envelope.provider_dataset` 必须
  精确匹配 requirement 声明——**mismatch = blocking FAIL**（stand-in
  永不 PASS；失败 exchange 的 endpoint 同样校验）；
- persist 失败 = FAIL（request_id 单独存在不构成 formal evidence PASS）；
- ProviderError（一等失败 exchange）= FAIL。

**Verdict**：全部 REQUIRED PASS + 每个 ALTERNATIVE_GROUP >= 1 成员 PASS
→ PASS；否则 FAIL（blocking，冻结 pipeline early-stop，下游 probe
fired == 0）。无法验证的 endpoint **不 fallback 到无关 endpoint**——
fail closed。

**新 exchange surface**：provider/target 新增三个 exact 方法
（`get_bj_code_mapping_exchange` / `get_equity_structure_exchange` /
`get_industry_base_info_exchange`），FakeTarget/RealTarget/SpikeTarget
Protocol 三处同步——R4-A3.1 时代的 stand-in 注释与 `_probe_stock_basic`
mapping 全部移除。

### 2.3 Proof case / artifact 身份（B1-04）

- **每个 requirement 一个 proof case**（`endpoint_requirement_case_id(req)`
  = `GATE-{capability}-{Class.method}`）：expected/actual 携带
  expected_endpoint / actual_endpoint / request_id / evidence_uri /
  evidence_hash；evidence_ref/hash 绑 RawWriter 持久化 meta（成功与失败
  exchange 都是证据）。SKIPPED（pipeline early-stop）不落 case——
  approval 自然拒绝（无 fabrication）。
- **REPORT artifact（`{run}/gates/{cap}.json`）携带结构化身份**：
  `endpoint_requirements[]` 每条含 requirement_id / capability /
  expected_endpoint / actual_endpoint / provider_dataset / actual_dataset /
  mode / group_id / status / request_id / evidence_uri / evidence_hash。
  artifact 由 REPORT case 的 evidence_hash（sha256）锚定。

**approval 消费（`_require_formal_gate_proof` 重写）**：

1. PERMISSION / BUSINESS / REPORT case 存在、类型正确、PASS、evidence
   绑定非空（R4-A3.1 语义保留）；
2. 每个 REQUIRED requirement 有对应 proof case 且 PASS 且 evidence
   绑定非空；每个 ALTERNATIVE_GROUP >= 1 成员 PASS；
3. **artifact 重验（防篡改）**：重算 artifact sha256 == REPORT case
   evidence_hash；逐条 entry 与 contract 比对——expected_endpoint ==
   contract endpoint；PASS 条目的 actual_endpoint == contract endpoint
   （stand-in = 拒绝）；evidence_uri/hash 非空。任何 mismatch →
   CapabilityGovernanceError（fail closed）。

**身份从 hash 锚定的 artifact 读，不从 case-id 名称推断**——B1-04 的
核心要求。

## 3. Alternative Considered（四问，audit §7.4）

**Q1：为什么 typed contract 而非继续解释 registry 的 sdk_methods？**
registry tuple 是文档性事实（capability 大致涉及哪些方法），没有
mode/group 语义、没有 probe 绑定、没有结构自检——每次消费都要靠散落
if/else 重新解释"这个 capability 用哪个方法做 proof"。typed contract 把
这些决策一次性显式化为可审计数据结构：一处声明、gate/approval/守卫
三处消费同一事实源，结构错误在装载期即被 `validate_endpoint_requirements`
抓住。

**Q2：为什么不扩展现有 FORMAL_GATE_PROOF_SUFFIXES 加更多 case 后缀？**
后缀方案仍然以 case-id 名称承载语义——approval 只能"推断"proof 覆盖了
哪些端点，无法验证 actual endpoint 与声明一致（B1-04 明确禁止）。
per-requirement case + hash 锚定 artifact 才能让 approval **重验身份**
而不是数 case 个数。

**Q3：为什么 ALTERNATIVE_GROUP 而非全部 REQUIRED？**
get_code_list（当前快照）与 get_hist_code_list（历史重建）在业务上
是同一上市证券清单的两个官方来源——任一可用即 capability 可交付。
若强行全部 REQUIRED，provider 下线快照端点时会误报 capability 不可用
（fail-too-closed 同样是失真）。组语义必须显式声明（组内成员是**官方
替代**），且组内 >= 2 成员由结构自检强制——防止"组"退化成单个端点的
别名。

**Q4：为什么 mismatch 在 gate evaluation 内即时 FAIL 而非记 warning？**
gate 的职责就是回答"该 capability 的官方 endpoint 是否可用"。一个
endpoint 不匹配的 PASS 比没有数据更糟——下游会基于错误前提继续
（B2-B7 语义校验会浪费一个 run 的额度，approval 会基于假身份放行）。
fail closed 是 Runtime Gates 契约（ADR-019）的一贯原则：不可证即阻断。

## 4. Consequences

- **正向**：stand-in 结构性不可能（probe spec 表 keyed by
  requirement_id；plan 从 contract 派生；mismatch 即时 FAIL）；
  approval 的身份重验防篡改（hash 锚定 + contract 比对）；
  capability registry 与 proof plan 的覆盖一致性被守卫测试强制。
- **代价**：新增 capability 必须同时声明 requirements + probe specs
  （漏做即测试红——这是特性不是缺陷）；corporate_action 现在有两个
  REQUIRED proof（dividend + right_issue，各一次真实 probe call）；
  FakeTarget 需为新端点提供 fake exchange（dry-run 全链路一致）。
- **真实环境注记**：`InfoData.get_bj_code_mapping` /
  `get_equity_structure` / `get_industry_base_info` 是 SDK 手册端点
  （registry 已声明），真实可用性由 Trial/Production Spike 阶段的
  B1 阶段验证——本 ADR 固定的是**身份合同**（调用与校验结构），
  不预支可用性结论。
- **B1-06 边界**：不扩展 B2 publish 链 / golden 审计 / CR-2；不动
  permission/business gate 语义（B1-03 分离保持）。

## 5. DM 登记

管理总册 §61 Change Log：DM-CR-20260828-046（contract + gate）/
DM-CR-20260828-047（provider/target exact surface）/
DM-CR-20260828-048（approval 消费 + 对抗测试）。

---

## Amendment 2026-08-30（R4-B1.1，audit 20260830）——correction：合同语义 / Approval Anti-Bypass / Cross-Binding

> **Status 修正说明**：本 ADR 原文写作时（2026-08-28）Status 被记为
> ACCEPTED 且 Deciders 列入 Design / Audit Review——那是开发方在 Reviewer
> 正式复审**之前**预写的状态，属 overclaim。Reviewer 于 2026-08-30 复审
> 裁决 R4-B1 **REOPENED**（3 P0 + 1 P1）。本 amendment 保留原文历史、
> 记录 REOPEN 事实并修正与运行时真相不一致的结论；修正后的契约以本节
> 与代码（endpoint_requirements.py）为准。

### C.1 P0-01 修正：security_master 的"官方替代"编组是错的（撤回）

原文 §2.1/§3 声称 `get_code_list`（当前快照）与 `get_hist_code_list`
（历史重建）是 security_master 的 official alternatives（任一可用即满足
endpoint proof）。**该结论与项目自己的 core capability 冲突**：

- 正式 spike capability 是 `security_master_with_delisted`——master 必须
  含 delisted securities（survivorship）；
- B2 正式语义 probe 调用 `get_hist_code_list` 并用它验证 delisted；
- R4-B1 的测试甚至固化了"snapshot PASS + hist DENIED → ENDPOINT PASS"
  的错误预期（靠 BUSINESS gate 兜底——违反 B1-03 分离）。

**修正**：`BaseData.get_hist_code_list` = REQUIRED（survivorship 的必要
条件）；`get_code_list` 从 requirements 中移除，分类
OPTIONAL_NON_APPROVAL_SURFACE（快照便利面/permission surface）。快照单独
可用**永不**满足 endpoint proof。测试改写：hist denied → ENDPOINT FAIL
→ BUSINESS fired==0 → approval impossible。

### C.2 P0-01 修正：adj_factor 双真相（Option B 撤回"各自 REQUIRED"）

原文 §3 Q3 声称 get_adj_factor 与 get_backward_factor "不同数据流、
不得编组、各自 REQUIRED"，但运行时 contract 只声明了 get_adj_factor——
ADR 与代码矛盾。**修正（Option B）**：backward-adjustment factor 是当前
管线不消费的数据流；capability approval 只要求 forward-adjustment
endpoint（REQUIRED）；`get_backward_factor` 显式分类
OPTIONAL_NON_APPROVAL_SURFACE 并记录理由。不再存在双重真相。

### C.3 P0-01 新增：SDK_METHOD_CLASSIFICATIONS（全量 method reconcile）

原文只覆盖"contract 的 capability 集合 == registry 的 capability 集合"，
registry 中每个 sdk_method 的语义仍靠注释解释。**新增**
`SdkMethodProofClass` 五分类（REQUIRED_ENDPOINT_PROOF /
ALTERNATIVE_GROUP_MEMBER / OPTIONAL_NON_APPROVAL_SURFACE /
BUSINESS_SEMANTIC_ONLY / DEPRECATED_NOT_USED）+
`SDK_METHOD_CLASSIFICATIONS` 表（19 条，含 reason 字段）：**每个 registry
sdk_method 恰有一条分类**，结构守卫验证
`set(registry.sdk_methods) == set(classified)` 且 REQUIRED 分类与
requirements 双向一致——新增/删除 SDK method 必须同步 contract decision。

多方法 capability 的最终分类（可审计理由见代码表）：security_master 三
方法（hist REQUIRED；code_list/stock_basic 非 approval surface）；
adj_factor（forward REQUIRED；backward Option B）；industry_taxonomy
（base_info REQUIRED；constituent/weight/daily 非 approval surface）；
index_daily（query_kline REQUIRED；get_index_daily 非 approval surface）。

### C.4 P0-02 新增：Approval Anti-Bypass（唯一生产 APPROVED transition）

R4-B1 把 exact endpoint 重验放进 `approve_from_spike_run`，但
`approve_and_persist_capability()` / `approve_capability()` 仍是 public——
caller self-declare CapabilityEvidence 即可 APPROVED（绕过全部 formal
endpoint proof）。**修正**：

- 新增内部 sealed proof object `VerifiedCapabilityApproval`（name /
  evidence / verified_from_run / endpoint_requirements_proven；
  空证明禁止构造）——只在 `approve_from_spike_run` 全验证链通过后构造；
- DB 写 APPROVED 的唯一边界 = private `_persist_verified_capability
  (conn, verified)`（只接受 verified object，保留 R3-P1-05
  validate-before-mutate / 单事务 / cache-rebuild 语义）；
- 旧 public 函数移除：`approve_and_persist_capability` / `approve_capability`
  消失；测试改用显式命名的 test-only helper
  （`_approve_and_persist_capability_testonly` /
  `_approve_capability_in_memory_testonly`，docstring 声明边界）；
- AST 守卫 ×2：src/ 全模块禁止引用 test-only helper；capability.py 中
  APPROVED 字面量只允许出现在 governed 边界（_persist_verified_capability
  / testonly helper / load_approvals）。

### C.5 P0-03 新增：Persisted Identity Cross-Binding（四层精确绑定）

R4-B1 的 REPORT re-check 未核验 provider_dataset/actual_dataset、未要求
proof case 与 REPORT entry 的 evidence URI/hash 相等、未从 Raw meta 反向
重验。**修正**（`_require_formal_gate_proof` 重写，返回 proven requirement
ids 供 verified object 消费）——对每个满足 requirement 的 PASS 证明：

```text
contract        <-> REPORT entry（endpoint + provider_dataset + capability）
proof case      <-> REPORT entry（evidence_ref == evidence_uri；
                    evidence_hash == evidence_hash）
REPORT entry    <-> persisted Raw meta（sha256(bytes) == entry.evidence_hash）
Raw meta        <-> contract（endpoint + provider_dataset）与 entry
                    （request_id）精确相等
```

任何单点篡改（actual_dataset / provider_dataset / evidence_uri 换成
permission 证据 / evidence_hash 换另一份合法 hash / case 与 entry 不一致 /
raw meta endpoint/dataset/request_id tamper）→ fail closed。9 项对抗测试
全部在"REPORT hash 重新绑定后仍拒绝"的条件下验证。

### C.6 治理状态同步

- R4-B1 原始实现（`b432159`）的机制性工作（exact-match engine /
  persisted proof / hash-anchored artifact）保留 FREEZE；本 amendment 只
  修正 contract 语义与 approval 边界；
- DM 登记：管理总册 §61 DM-CR-20260830-049（语义修正 + classification）/
  050（anti-bypass）/ 051（cross-binding + 对抗测试）；
- 原 §2.1 的 listing_surface 编组、§3 Q3 的"各自 REQUIRED"表述按上文
  C.1/C.2 修正，原文保留供审计追溯。

---

## Amendment 2026-08-30（R4-B1.2，audit 20260830 15:42）——Final Approval Boundary / Industry Endpoint Closure

> **关联 Reviewer Verdict**：`docs/design/A-share-analysis_R4-B1.1复审与R4-B1.2最终ApprovalBoundary及IndustryEndpoint收口要求_20260830.md`（REVIEWED HEAD `c2e572d1073c48ae93a4bc57373830ba92306054`）。
> 复审裁决：R4-B1.1 大部分 PASS / FREEZE（四层 cross-binding VERIFIED 冻结、security_master 撤回编组正确、classification 守卫正确）；**2 个 P0 blocker** 由本 amendment 修正。

### D.1 P0-01 修正：Approval Anti-Bypass 结构性关闭（Option A）

Amendment C.4 的"verified object + private boundary"仍是 Python 命名约定而非访问控制：`_approve_and_persist_capability_testonly()` 可被显式 import；`VerifiedCapabilityApproval` 是普通可实例化 dataclass（`__post_init__` 只查非空），caller 可伪造后直调 `_persist_verified_capability()`——后者只重做 `_validate_evidence`，不重验 formal run。

**修正（Reviewer Preferred Option A）**：生产模块**彻底不存在**"无需 formal run 即可写 APPROVED"的 callable——

- `_approve_capability_in_memory_testonly` / `_approve_and_persist_capability_testonly` / `VerifiedCapabilityApproval` / `_persist_verified_capability` 全部从 `capability.py` 删除；
- 持久化事务（validate-before-mutate / 单事务 / cache-rebuild / UPDATE-only-governance-fields）**inline 进 `approve_from_spike_run` 尾部**——caller 到达写入点必已通过完整验证链（closed PRODUCTION run / frozen identity / verdict / formal gate proof / 四层 cross-binding / golden refs）；
- 测试所需的 transaction/cache mechanics 移入 `tests/integration/_capability_test_persistence.py`（tests/ 内，生产 src 不 import test 模块——AST 守卫）；
- 对抗测试改为**真实绕过尝试**（伪造 verified object → 类不存在；caller-built evidence + frozen id → 无 importable 路由；AST 守卫：capability.py 中唯一引用 APPROVED 状态的函数是 `approve_from_spike_run` 且其签名无 evidence/verified 参数；src 不 import tests.*）。

### D.2 P0-02 修正：industry_taxonomy constituent 端点 REQUIRED

Amendment C.3 把 `get_industry_constituent` 分类为 OPTIONAL_NON_APPROVAL_SURFACE——**过弱**：capability 名为 `industry_taxonomy`、canonical domain 为 `bridge_industry_member`，其核心交付物是 security ↔ industry **membership**；仅 `get_industry_base_info` 只证明 taxonomy definition/identity surface。base_info PASS + constituent DENIED 时 ENDPOINT gate 仍 PASS 并允许 APPROVED，但系统无法可靠构建 `bridge_industry_member`——与 security_master 问题同构（证明代表性 endpoint ≠ 证明必要交付面）。

**修正**：

- `industry_taxonomy:InfoData.get_industry_constituent` = **REQUIRED_ENDPOINT_PROOF**（requirements 表 + classification 同步；reason 绑定 bridge_industry_member 交付语义）；
- `get_industry_weight` / `get_industry_daily` 维持 OPTIONAL_NON_APPROVAL_SURFACE，但 reason 显式指向**当前消费边界**（"bridge_industry_member 的 membership 构建不消费 weights/daily；若未来 canonical/feature consumer 需要，重新评估"）；
- provider/target 新增 exact exchange surface `get_industry_constituent_exchange`（provider + Protocol + RealTarget + FakeTarget 四处同步）；
- 新增对抗测试：base_info PASS + constituent DENIED → ENDPOINT FAIL → early-stop → BUSINESS fired==0 → 失败 exchange 持久化绑定 → proof case VALIDATED_FAIL → approval impossible；
- **canonical-deliverable 结构守卫**（新测试）：multi-endpoint capability 的 REQUIRED requirements 集合 == canonical 交付面必要端点集合（security_master={hist}；adj_factor={forward}；corporate_action={dividend,right_issue}；industry_taxonomy={base_info,constituent}；index_daily={query_kline}）——防止"全部 sdk_methods 已分类但必要 method 被分 optional"的形式合规、语义失真再次发生。

### D.3 P1 更正：分类表计数（治理文档数字错误）

Amendment C.3 写"SDK_METHOD_CLASSIFICATIONS 表（19 条）"——Reviewer 逐项计数实际为 **18 条**（trade_calendar 1 + security_master 3 + code_mapping_bj 1 + daily_bar 1 + security_status_history 1 + adj_factor 2 + corporate_action 2 + equity_structure 1 + industry_taxonomy 4 + index_daily 2）。结构守卫 `set(registry.sdk_methods) == set(classified)` 本身通过，故为**治理文档数字错误，非 runtime 缺项**。本 amendment 更正为 18 条；R4-B1.2 将 constituent 从 OPTIONAL 改为 REQUIRED **不改变条目数**（修改既有条目的 classification，非新增），当前表仍为 18 条。

### D.4 治理状态同步

- R4-B1.1 的四层 cross-binding / security_master 撤回编组 / classification 结构守卫等 PASS 项 FREEZE（除非可复现 regression 不再重审）；
- DM 登记：管理总册 §61 DM-CR-20260830-052（Option A anti-bypass）/ DM-CR-20260830-053（industry constituent REQUIRED）；
- ADR-020 Amendment C.4 的"verified object"设计按 D.1 修正（原文保留供审计追溯——该设计被证明依赖命名约定而非结构边界）。
