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
