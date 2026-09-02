# ADR-023: AvailabilityPolicy + Canonical Source Selection

- **Status**: PROPOSED（2026-09-01，CR-3 批次交付 + CR-3.1 Amendment A 收口 + 2026-09-01 CR-3.2 Amendment B 收口 + 2026-09-02 CR-3.3 Amendment C 收口 + 2026-09-02 CR-3.4 Amendment D 收口；Reviewer 复审裁决待定——本 ADR 在复审前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-09-01（CR-3）/ 2026-09-01（Amendment A，CR-3.1）/ 2026-09-01（Amendment B，CR-3.2）/ 2026-09-02（Amendment C，CR-3.3）/ 2026-09-02（Amendment D，CR-3.4）
- **Work Requirement**: `docs/design/A-share-analysis_CR-2.4最终复审结论与CR-3_AvailabilityPolicy_Canonicalizer开发工作要求_20260901.md` + `docs/design/A-share-analysis_CR-3复审与CR-3.1最终CanonicalInputSnapshot及ReplaySeal收口要求_20260901.md` + `docs/design/A-share-analysis_CR-3.1复审与CR-3.2最终TransactionalSnapshot及PolicyExecution收口要求_20260901.md` + `docs/design/A-share-analysis_CR-3.2复审与CR-3.3最终HistoricalInputContinuity及VerificationEvidence收口要求_20260902.md` + `docs/design/A-share-analysis_CR-3.3复审与CR-3.4最终ContinuitySeal及VerificationReplay收口要求_20260902.md`
- **Related**: [ADR-022](ADR-022_provider_normalization_quarantine.md)（ACCEPTED——CR-2 全链 VERIFIED/CLOSED/FREEZE，本 ADR 的上游输入契约）；[ADR-002]（确定性 security identity，identity bridge 的解析内核）

## 1. Context

CR-2（含 2.1-2.4 收口）关闭后，系统拥有一条可信的 Provider-Normalized
中间数据层（anchored ingestion → provider-faithful normalization →
immutable artifacts + exact replay）。CR-3 解决下一个语义层次的问题：

> 同一条市场事实，如果来自不同供应商、不同时间、不同质量，系统在
> "当时那个时间点"（as_of）到底应该信哪一条。

## 2. Decision

### 2.1 Formal Boundary（工作要求 §4/§5）

```text
CR-2 eligible Provider-Normalized runs（仅 SUCCESS；PARTIAL 仅当 domain
  SourcePolicy 显式允许——v1 无任何 domain 允许）
  -> read-only closure verification（verify_normalized_run，CR-2 三方
     seal 全量复验后才可消费）
  -> governed identity bridge（security_master -> security_id）
  -> typed availability derivation + as_of filter（BEFORE selection）
  -> source selection / EXACT reconciliation（静态版本化 SourcePolicy）
  -> immutable canonical artifacts + canonicalization ledger
```

Canonicalizer 的 API 是 `run(as_of, domains=...)`——as_of 是 PIT 查询点
（运行参数），domains 选择构建哪些受治理 domain；**不存在任何
correctness-policy 参数**（provider priority / tolerance / fallback /
partial 全部在静态版本化 registry 中，结构测试断言）。

### 2.2 CR3-P0-01/02：唯一输入 + eligibility 机器定义

- 输入只能是 CR-2 verified Provider-Normalized：消费前对每个候选 run 调
  `verify_normalized_run`（manifest bytes / output content+schema+row_count
  / quarantine exact set / typed seal vs current provenance 的只读全量
  复验）——任何 problem → CLOSURE_VERIFICATION_FAILED blocking finding；
- SUCCESS → eligible；PARTIAL → 默认 NOT eligible（v1 全部 domain
  partial_run_allowed=False，行级消费不发生）；BLOCKED → NEVER。

### 2.3 CR3-P0-03/04：AvailabilityPolicy 机器先行

```text
candidate -> derive available_at -> filter available_at <= as_of
          -> ONLY THEN source selection / reconciliation
```

- `available_at` 的唯一 production basis 是 **OBSERVED_AT_INGEST**：raw
  envelope 的 `received_at`（provider 应答时刻，CR-2 bound evidence 内）
  ——晚于任何真实 publish 时刻，因此对 PIT 保守（绝不让未来知识"过早
  可用"）；
- typed basis 分类（SOURCE_PUBLISHED_AT / OBSERVED_AT_INGEST /
  DOMAIN_RULE_DERIVED / NOT_VERIFIABLE）中后两类不注册（无版本化
  Trading Rule 事实前不推导；NOT_VERIFIABLE 永不进入 PIT truth）；
- 禁止且测试断言：trade_date 00:00 / 1970-01-01 / 固定收盘时间作为
  available_at；先选 source 再查可用性；
- policy 版本（availability-v1）+ hash 进入 canonical run identity。

### 2.4 CR3-P0-05/06：Identity fail closed + typed natural keys

- Provider symbol → security_id 走 **IdentityBridge**：从 CR-2 verified
  security_master runs（code_list / hist_code_list / stock_basic 三
  dataset 全集）构建，经 ADR-002 `resolve_security_identity`（uuidv5 over
  `EXCHANGE:STOCK:SYMBOL:F<list_date>`）解析；
- exchange 归属只来自 provider symbol 的 market 后缀（CR-2 mapper 已验证
  语义），**裸码只允许唯一市场匹配**（三个后缀变体中恰一个存在；两个
  存在 = ambiguous fail closed——绝不用代码前缀猜交易所）；
- PIT relist：取 list_date <= trade_date 的最新 identity；无 → missing；
- missing/ambiguous → IDENTITY_MISSING finding（identity_missing_max=0
  → blocking）+ 行排除——**裸 provider symbol 永不作为 canonical key
  fallback**；
- natural keys 按 domain 静态定义（calendar: market+trade_date；bars/
  status/limit: security_id+trade_date；adj_factor:
  security_id+ex_date+factor_type）；
- **Domain eligibility matrix**（12 domain 全显式分类）：5
  CANONICAL_SUPPORTED（trade_calendar / daily_bar / security_status /
  limit_price / adj_factor）；2 AUXILIARY_ONLY（security_master=identity
  dataset、ca_projection=STATUS_FLAG_PROJECTION evidence tier，P0-11：
  direct dividend/right-issue mapper 仍 BLOCKED_PENDING_MAPPER 期间绝不
  伪造 direct corporate_action truth）；5 BLOCKED_PENDING_SEMANTICS
  （corporate_action direct / index_daily（INDEX_CODE 无已验证市场归属）/
  industry_member（effective interval 语义未验证）/ equity_structure（B6
  pending）/ bj_code_mapping + industry_taxonomy_definition）。API 对
  非 SUPPORTED domain 直接 raise（无 silent skip；无绕过 CR-2 从 Raw
  直读的路径）。

### 2.5 CR3-P0-07..09：SourcePolicy 版本化静态 + No Silent Fallback

- `CanonicalSourcePolicy` 静态 registry（source-policy-v1）：priority /
  fallback（空）/ partial（False）/ reconciliation=SINGLE_SOURCE_EXACT /
  tolerance=exact-v1 / identity_missing_max=0 / conflict_action=BLOCK；
- caller 无任何注入面（签名结构测试）；
- 不可用首选 → REQUIRED_DOMAIN_MISSING blocking finding（无静默
  fallback；若未来允许 fallback 则是显式 FALLBACK_SELECTED decision +
  policy 版本变更）；
- 同 key 多候选：**EXACT** 比较——等值 → EQUIVALENT_MERGED decision +
  deterministic winner（(priority index, manifest hash, ordinal) 排序，
  provider/run iteration order 永不影响结果）；不等值 → blocking
  SOURCE_CONFLICT finding；同一 output 内重复 key → blocking
  DUPLICATE_CANONICAL_KEY finding（绝不 silent dedupe /
  last-write-wins / keep-first）。

### 2.6 CR3-P0-10：精确 lineage

每条 canonical row 绑定：canonical_domain / canonical_key /
selected_provider / source_normalization_run_id / source_output_name /
source_row_ordinal（CR-2 deterministic sorted parquet 物理行号）+
source_row_identity_hash（行 canonical JSON sha256）/ source_raw_request_id
/ source_raw_evidence_hash / source_mapper_identity /
availability_basis + policy_version / source_policy_version /
canonical_contract_version。

### 2.7 CR3-P0-12：无硬编码制度事实

Limit-price 制度事实（ST=5% / 科创板=20% / 北交所=30% / 规则变化日期）
不得出现在 Python——AST guard 扫描 canonical 包（测试断言）。CR-3 只
选择 provider-normalized limit price 值，不做制度推导。

### 2.8 CR3-P0-13..15：Immutable artifacts + deterministic identity + 状态机

- 布局：`canonical/contract=<V>/as_of=<T>/run=<run_id>/` 下
  selected.parquet + decisions.parquet + findings.parquet +
  manifest.json（**LAST**；无墙钟 correctness 字段；immutable——同 bytes
  no-op / 异 bytes conflict）；
- manifest 封住：input normalized run exact set（run_id:manifest_hash）+
  input_set_hash / identity_dataset_hash（bridge dataset + policy）/
  availability+source+tolerance policy version+hash / canonicalizer code
  fingerprint（canonical 包五模块源码 SHA-256，行尾归一）/ 每 artifact
  uri+content+schema+row_count / selected_semantic_hash /
  finding_set_hash / status；
- **run identity** = uuid5(sha256(input_set + identity_hash + as_of +
  contract + 三 policy identity + code fingerprint))——任一 policy/代码/
  输入变化 → 新 run（历史保留）；prior 同 identity run 先 closure 复验
  （manifest bytes / artifacts / findings DB exact set 三方 seal）再
  idempotent replay，篡改/缺失 → fail closed；
- ledger（migration 018 `meta_canonicalization_run` +
  `meta_canonical_reconciliation_finding`）单事务提交（dup 检查 + finding
  行数断言）；
- 状态机：SUCCESS（零 blocking finding）/ BLOCKED（identity /
  availability / source conflict / required domain / closure 任一
  blocking failure）；PARTIAL 仅由 policy 允许（v1 无）——caller 不能
  决定。

## 3. Consequences

- CR-3 依赖且只依赖 CR-2 的 20 条冻结契约（工作要求 §3 清单）；
  不绕过 manifest/ledger 直读 "看起来像 normalized 的 parquet"；
- 逐行 decision 存 decisions.parquet（审计），DB 只存 run-level seal 与
  findings（不把大批 canonical rows 塞进 metadata DB）；
- 第二个 provider 到来时是 **policy 版本变更**（新 run identity，历史
  保留），不是 caller 参数；
- CR-3 不是 SnapshotBuilder（DuckDB read model rebuild 属 CR-4）。

## 4. Testing

36 项对抗测试（tests/integration/test_canonical.py）覆盖工作要求 §8
矩阵 30 类 + P1 guard 加固 4 项（alias / constructor-call /
reader-module 白名单 / production 全树零违规）；总体 1025/0。

## 5. DM 登记

管理总册 §61：DM-20260901-068（CR-3 AvailabilityPolicy + Canonicalizer
runtime + migration 018 + ADR-022 ACCEPTED 同步 + CR-2.4 P1 guard 加固）+
DM-20260901-069（CR-3.1 Amendment A：Canonical Input Snapshot / Anchored
Availability Evidence / Full Replay Seal / Recoverable Commit）+
DM-20260901-070（CR-3.2 Amendment B：Transactional Materialized Snapshot /
Identity Master PIT / Honest Policy Execution / Full Seal /
Verification-State Transition）+ DM-20260902-071（CR-3.3 Amendment C：
Historical Input Continuity / Verification Evidence Exactness / finding
truthfulness / seal count correction）。相关：§42 Canonical Runtime
Roadmap、§44 CR-2 acceptance（上游冻结）。

---

# 6. Amendment A：CR-3.1 Canonical Input Snapshot + Replay Seal（2026-09-01，audit "CR-3复审与CR-3.1最终CanonicalInputSnapshot及ReplaySeal收口要求"）

CR-3 复审（2026-09-01 19:06 +08:00，Reviewed HEAD `e1c6bb2236a1b0eac06ee214b7cf64cf4fe13f79`，
Primary implementation `ae5b76c998196f936ae6430408d2a016a35aec0d`）裁决
**CR-3 REOPENED**：主体架构 PASS / FREEZE（18 项冻结清单见复审 §0），
但 run identity / authoritative input snapshot / raw PIT evidence /
replay seal / retry closure 未完全收口。**本 amendment 修订 §2 中被复审
推翻的表述；原文保留在上文，以本节为准。**

## 6.1 P0-01 RequestedDomainSet 进 run identity（修订 §2.1）

`run(as_of, domains=...)` 的 domains 原先不进 identity——同一 as_of 请求
daily_bar 会直接 replay trade_calendar 历史运行。CR-3.1 起：请求域经去重
排序成 exact set，其 canonical JSON hash 进入 run identity；migration 019
ledger 列 `requested_domains_json` / `requested_domains_hash`；manifest
显式绑定；replay 返回的 domains 来自 ledger seal；不同 set 必不同 run id，
同 set 不同顺序同 run。

## 6.2 P0-02 Availability completeness（修订 §2.3）

原先 REQUIRED_DOMAIN_MISSING 只判"有无 eligible CR-2 run"——future-only
候选全被 as_of 排除时 run 可能 false SUCCESS。CR-3.1 起机器区分：无
eligible verified run → `REQUIRED_DOMAIN_MISSING`；有 eligible run 但零
PIT-available 候选 → `REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF`（均 blocking；
"合法空集合"只能由 domain policy 显式版本化声明，v1 无此例）。

## 6.3 P0-03 CanonicalInputSnapshot（修订 §2.1/§2.8）

原先同一次 run 内 broad input discovery 被重复执行（identity /
candidates / manifest / ledger 各自查当前 DB 全集）——read-race 下四者
可能代表不同世界。CR-3.1 起：`CanonicalInputSnapshot`（typed immutable
dataclass）在一切之前**一次性**解析——requested domain set + discovered
CR-2 source/master run exact set + closure/anchor 验证结果 + policy
identities + code fingerprint；run identity、candidates、manifest、ledger
全部从 snapshot 派生，不再重复 broad query。**Discovered set 包含验证
失败的 run**（其 blocking prefinding 是诚实记录）——这使 post-success
tamper 表现为 DAMAGED replay 而非悄悄 mint 新 identity。mid-run 插入的
新 run 只能被下一次 invocation 看到（新 identity）。

## 6.4 P0-04 AnchoredAvailabilityEvidence（修订 §2.3）

原先 `_received_at()` 直接读 raw meta——normalize 后仅改 received_at 可
把未来数据提前变历史可用（CR-2 closure 不覆盖 raw meta bytes）。CR-3.1
起：读 received_at 前必须证明 current raw meta exact-byte SHA-256 ==
normalization run sealed `raw_evidence_hash` == `meta_raw_evidence_anchor.
evidence_hash`，并 cross-bind provider/dataset/request/uri/endpoint/
surface/operation_id（anchor == run == meta 三方）。失败 →
`AVAILABILITY_EVIDENCE_INVALID` blocking finding。replay 对每个 sealed
source run 重新执行此验证。

## 6.5 P0-05 Identity binding 统一（修订 §2.4）

原先 `_run_identity`/ledger 用裸 master set hash、manifest 用
`sha256(policy_version|set)`——两口径且 policy version 缺失。CR-3.1 起
唯一口径：`identity_dataset_hash = hash(master_input_set_hash,
identity_bridge_policy_version, identity_bridge_policy_hash)` 进入 run
identity / manifest / ledger 三处同值；bridge policy 变更 → 新 run；
replay 比对 ledger == manifest == current。

## 6.6 P0-06 Policy hash 全字段（修订 §2.5）

`source_policy_hash()` 原先手写字段串（漏 allowed_fallback_providers /
identity_missing_max / required_evidence_class / tolerance_rule_version）。
CR-3.1 起：`dataclasses.asdict` + sorted canonical JSON 全字段覆盖；runtime
诚实消费——声明 fallback/partial 而 runtime 无支持时**显式 raise**；
`identity_missing_max` 按 per-domain 计数 vs 阈值判定 blocking（非硬编码
>0）；`required_evidence_class` 进 manifest binding
（`required_evidence_classes` map）。

## 6.7 P0-07 Full replay seal（修订 §2.8）

原先 verifier 只验 manifest bytes/counts/DB findings——manifest 已写入的
correctness 字段未被三方消费，selected/decisions/findings 可 rebind。CR-3.1
起 replay 必须：CURRENT snapshot identities == ledger == manifest ==
replay-time physical recompute（selected_semantic_hash / decision_set_hash /
finding_set_hash / artifact exact set / deterministic URI / schema recompute /
row_count / findings parquet ↔ DB exact-set cross-bind），并 re-verify 每个
sealed CR-2 source run closure + anchored availability evidence。migration
019 ledger 增 `selected_semantic_hash` / `decision_set_hash`。

## 6.8 P0-08 Recoverable commit（修订 §2.8）

原先 findings.parquet 含 `created_at = now()`——DB 失败后 exact retry 因
bytes 不同而 conflict 不可恢复。CR-3.1 起：deterministic correctness
artifact 不含任何 wall-clock（finding id = uuid5；created_at 仅作为
transaction-time audit metadata 存 DB 且排除出 semantic hash）；DB 失败
→ exact retry 文件 byte-identical no-op → ledger 补提交。

## 6.9 P1 更正

- identity finding 按真实 domain 记录（per-domain 计数 + 真实 scope，不
  再统一写 daily_bar）；
- **domain matrix 计数更正**：§2.4 原文写"12 domain / 5 blocked"——实际
  为 **13 domain（5 CANONICAL_SUPPORTED / 2 AUXILIARY_ONLY / 6
  BLOCKED_PENDING_SEMANTICS）**，runtime exact-set 统计（测试断言 13）；
- timezone：naive datetime 拒绝（其解释依赖 host 时区）；naive string 按
  文档化固定 UTC 规则解析（跨平台 deterministic，测试覆盖）。

## 6.10 Scope 边界

CR-3.1 不新增业务 domain、不做 CR-4（SnapshotBuilder / DuckDB ReadModel）、
不扩功能面——只封死四个正确性身份（requested set / input snapshot /
PIT evidence / replay seal）。migration 019（未改 018）；CR-2.x 冻结语义
零触碰。

---

# 7. Amendment B：CR-3.2 Transactional Snapshot + Identity Master PIT + Honest Policy Execution + Full Seal + Verification-State Transition（2026-09-01，audit "CR-3.1复审与CR-3.2最终TransactionalSnapshot及PolicyExecution收口要求"）

CR-3.1 复审（2026-09-01 21:08 +08:00，Reviewed HEAD `bd3bcad6aa3e55580cfd03943c4c52f3a31efd0a`，Primary implementation `75744aaa89487aae09474b3569519a73f0efba24`）裁决
**REOPENED**：19 项机制 PASS / FREEZE（requested-domain identity /
future-only completeness / anchored availability / identity binding /
全字段 policy hash / 三 semantic seal / recoverable commit / P1 三项），
5 个 P0 集中在 "同一次 canonical run 是否真的只代表一个唯一 as-of
世界"。**本 amendment 修订 §2/§6 中被复审推翻的表述；原文保留在上文，
以本节为准。**

## 7.1 P0-01 Transactional Materialized Snapshot（修订 §6.3）

§6.3 的 snapshot 只解决了 "构造完成后不再 broad re-query"。CR-3.2 起：

```text
BEGIN TRANSACTION（MVCC snapshot boundary——在第一个 authoritative
  broad SELECT 之前）
  -> surface 去重发现（P1-02：同一 surface 只查询一次，union datasets）
  -> 逐 run：closure verify + anchored availability verify
  -> 物化 exact sealed bytes：读 bytes -> hash == manifest content_hash
     -> parse 同一份 bytes -> 深冻结行（tuple of sorted item-tuples）
COMMIT
```

- candidate builder 只消费 materialized rows（**绝不重新查询当前
  normalization ledger path / 重读当前文件**）——snapshot 后的 ledger
  UPDATE 或文件替换只影响下一次 invocation / replay verify；
- 深不可变（P1-01）：typed frozen records（`InputRunSeal` /
  `SnapshotRun` / `MaterializedOutput` / `CanonicalFinding` frozen
  dataclasses；行 tuple-frozen；无 shallow-copy 后被 writer 修改）；
- race 测试用第二 connection 在 broad reads 之间真实 commit（file-backed
  DuckDB MVCC）——非 "snapshot 返回后再插入"。

## 7.2 P0-02 Identity Master PIT（修订 §2.4/§6.4）

security_master 与 market source 同规则：anchor-verified
`received_at <= as_of` 才可进 IdentityBridge；future master 是
discovery evidence（sealed in input set，`pit_available=false`）但绝不
解析历史 rows。typed findings：`IDENTITY_DATASET_MISSING` /
`IDENTITY_DATASET_UNAVAILABLE_AT_ASOF` / `IDENTITY_EVIDENCE_INVALID`。
first-run 与 replay 对称（都验 master anchor）。relist 用例保持 early
truth。

## 7.3 P0-03 Honest Policy Execution（修订 §6.6）

§6.6 只显式拒绝 fallback/partial。CR-3.2 起 **explicit supported-value
guard**：`required_evidence_class == PROVIDER_NORMALIZED_VERIFIED` /
`reconciliation == SINGLE_SOURCE_EXACT` / `tolerance_rule_id ==
exact-v1` / `tolerance_rule_version == 1` / `conflict_action == BLOCK` /
fallback 空 / partial False——任何声明超出 v1 runtime 能力 fail closed
（在 canonical run 之前）。未来新增行为必须字段值 + runtime 实现 +
decision/finding 语义 + 测试 + policy 版本同一批进入。

## 7.4 P0-04 Full Seal 全消费（修订 §6.7）

- input entry 升级为 **typed full CR-2 seal**（`InputRunSeal`：
  contract_version / mapper_identity / mapper_code_hash /
  manifest_uri+hash / output_set_hash / semantic_hash / status / raw
  identity / verification / received_at / pit_available）——
  `input_seal_hash` 三方（snapshot == manifest == ledger）；
- manifest 显式 provenance 字段全部被 replay 消费：
  `identity_master_input_set_hash` / `identity_bridge_policy_version` /
  `identity_bridge_policy_hash` / `required_evidence_classes`（== current
  policy）；
- **manifest_uri 本身 deterministic verify**（expected base +
  `/manifest.json`）；
- replay 的 sealed-input 验证改为 seal-based（直接用 seal 字段验证
  files：manifest bytes / outputs content+schema+row_count / CR-2 manifest
  自身 seal 字段 == typed seal / raw meta + anchor）——不依赖 current
  DB row。

## 7.5 P0-05 Verification-State Transition（新增）

run identity = **base identity**（input world：requested set + identity
seal entries + identity hash + as_of + contract + policies +
fingerprint）+ **verification_state_hash**（每 discovered run 的
verification outcome canonical hash）。migration 020 四列
（base_identity_hash / verification_state_hash / input_seal_hash /
identity_master_input_set_hash）：

```text
state 相同             -> exact replay（含 BLOCKED 的同状态重放）
BLOCKED(可恢复) + 修复  -> 新 deterministic run id（recovery run）——
                          绝不 replay stale BLOCKED；历史证据保留
SUCCESS + 退化          -> DAMAGED 拒绝（不 mint 任何 replacement）；
                          exact repair 后恢复历史 replay
```

`input_set_hash` 只含 identity 字段（verification/received_at/
pit_available 是 runtime state，进 state hash / manifest evidence，
绝不进 base identity）。

## 7.6 P1

- P1-01 深不可变 snapshot（7.1）；
- P1-02 shared surface discovery 去重（7.1）；
- P1-03 `domains=[]` 显式 reject（None = all supported）。

## 7.7 CR-3.2 对抗测试（+30 项）

`tests/integration/test_canonical.py`（111 项 = CR-3/3.1 81 项回归 +
30 新增：TransactionalSnapshot 6（含真实 MVCC race×2 + ledger URI
update + file replace + deep immutability + next-invocation）/
IdentityMasterPIT 6 / HonestPolicyExecution 8（5 unsupported-value
parametrize + supported 回归 + empty domains）/ FullSealConsumption 7 /
VerificationStateTransition 3（repair recovery ×2 + degradation
refusal + evidence preservation））。总体 1096/0。

## 7.8 Scope 边界

CR-3.2 仍是 Canonical Runtime correctness closure：不建
SnapshotBuilder / DuckDB ReadModel（CR-4）、不新增 canonical domain、
不绕过 CR-2 frozen verifier。migration 020（未改 018/019）；CR-3.1
FREEZE 的 19 项机制零重写（81 项回归全保持）。

---

# 8. Amendment C：CR-3.3 Historical Input Continuity + Verification Evidence Exactness（2026-09-02，audit "CR-3.2复审与CR-3.3最终HistoricalInputContinuity及VerificationEvidence收口要求"）

CR-3.2 复审（2026-09-02 06:56 +08:00，Reviewed HEAD `9ffdf35f577e48ec4de1432057d954da07f78db0`，Primary implementation `df409ede0ddb25ce5cee12a46fa66fe7a3ea093f`）裁决
**REOPENED**：16 项机制 PASS / FREEZE（transactional snapshot / master
PIT / honest policy / full seal 主体 / state transition 主体），但 2 个
P0 + 3 个 P1。**本 amendment 修订 §7 中被复审推翻的表述；原文保留在
上文，以本节为准。**

## 8.1 P0-01 Historical Input Continuity Guard（修订 §7.5）

§7.5 的 degraded-SUCCESS guard 以 `base_identity_hash` 查历史——但
consumed CR-2 run 的 ledger 行 DELETE / status drift / seal 字段 drift
都会改变 current base identity，使 guard 查不到历史 SUCCESS，可能 mint
新的 BLOCKED 甚至新 SUCCESS truth。CR-3.3 起（migration 021
`canonical_context_hash`）：

```text
canonical_context_hash = requested domain set + as_of + contract +
  availability/source/tolerance policy identities + identity bridge
  policy identity + canonical code fingerprint
（刻意不含 current CR-2 input set / verification state）

guard：查同 context 的全部历史非 BLOCKED run，对每个 prior 的
  sealed input set 逐 run 检查：
    1. run_id 仍在当前 authoritative CR-2 ledger 中存在（disappearance
       -> DAMAGED）
    2. ledger identity（status + 全部 seal 字段）== prior sealed
       identity（drift -> DAMAGED）
    3. physical + anchored verification 仍健康（degradation -> DAMAGED）
    4. 健康的 prior input 必然出现在 current snapshot discovery 中
       （同 context => 同 surface plan；缺失即不可解释 drift）
合法新增：全部 prior inputs 完整保留 + current set 是 superset
  -> 正常新 run（新 identity）
exact restoration -> 历史 SUCCESS exact replay
```

## 8.2 P0-02 Verification Evidence Exactness（修订 §7.5）

`verification_state_hash` 只封枚举——同错误大类内 cause 变化（anchor
missing → anchor hash mismatch）会 replay stale BLOCKED finding。CR-3.3
起 `InputRunSeal` 新增 `verification_problem_hash`（canonical sorted
problem evidence：run_id + verification class + closure problems +
anchored-evidence problems + materialization problems）：

```text
base identity        不含 problem hash（identity_dict 排除）
verification state   含 problem hash（run_id + class + problem hash）
manifest input seal  持久化 problem hash（as_dict 含）
input_seal_hash      含 problem hash
同一 INVALID class + 不同 cause -> 新 state -> 新 BLOCKED evidence run
  （prior BLOCKED 保留 append-only；finding detail 反映真实当前 cause）
exact same failure   -> idempotent replay 同一 BLOCKED run
INVALID -> HEALTHY   -> recovery run
prior SUCCESS + 任何退化 -> P0-01 continuity guard HARD DAMAGED
```

replay 的 sealed-input 验证分流：HEALTHY sealed input 要求仍健康
（物理 + anchor）；INVALID sealed input（BLOCKED run 记录的失败）要求
**当前 problem evidence == sealed problem hash**（exact failure 才
replay）。

## 8.3 P1（audit §3-§5）

- **P1-01 finding scope 真实**：source-scope findings 用 reserved scope
  `input:<normalization_surface>`（绝不用无业务语义的 "source"），detail
  seal `affected_domains` exact set（受该 surface 影响的全部 requested
  domains——shared surface 如 security_status_history 同时封
  security_status 与 limit_price）；
- **P1-02 finding precedence**：no discovered → REQUIRED_DOMAIN_MISSING；
  discovered but damaged → 仅 closure/evidence finding（**不再误报
  UNAVAILABLE_AT_ASOF**——损坏不是不可用）；healthy but all future →
  UNAVAILABLE（真语义保留）；
- **P1-03 治理计数更正**：CR-3.2 说明称 InputRunSeal "19 fields"——实际
  为 **20**；CR-3.3 后为 **21**（+verification_problem_hash）；
  identity_dict 为 17 字段。治理文档按代码 exact set 记录（测试机械
  断言），不再手写数字。

## 8.4 CR-3.3 对抗测试（+20 项）

`tests/integration/test_canonical.py`（131 项 = CR-3/3.1/3.2 111 项回归
+ 20 新增：HistoricalInputContinuity 11（delete/status/uri/hash/seal
drift ×5 + two-sources delete-one + exact restore replay + superset
allowed + future-only addition + master disappearance/status drift）/
VerificationEvidenceState 4（cause change 新 run ×2 + exact failure
idempotent + recovery 保留历史）/ FindingTruthfulness 4（reserved scope +
affected domains + shared surface 双域 + damaged 不误报 + healthy future
仍报）/ SealFieldCountCorrection 1）。总体 1116/0。

## 8.5 Scope 边界

CR-3.3 仍是 CR-3 correctness closure：不建 SnapshotBuilder / ReadModel
（CR-4）、不新增 domain、不改 CR-2 frozen contract。migration 021（未改
018/019/020）；CR-3.2 FREEZE 的 16 项机制零重写（111 项回归全保持）。

---

# 9. Amendment D：CR-3.4 Historical Canonical Seal Trust + Verification Replay Symmetry + Manifest Correctness Identity Binding（2026-09-02，audit "CR-3.3复审与CR-3.4最终ContinuitySeal及VerificationReplay收口要求"）

CR-3.3 复审（2026-09-02 10:22 +08:00，Reviewed HEAD `b5fdc27b9f2fd9c262c7dc6dae9aa665b9494bc1`，Primary implementation `f8b80b3212ff299f52ee3fb0308c248fd16c17df`）裁决
**REOPENED**：18 项机制 PASS / FREEZE（canonical_context_hash 方向 /
continuity guard 按 context 查历史 / 全部 CR-2 ledger drift 检测 /
superset 合法 / exact restore replay / verification_problem_hash 进
seal+state / finding truthfulness / 治理计数），但 3 个 P0 correctness
blockers。**本 amendment 修订 §8 中被复审推翻的表述；原文保留在上文，
以本节为准。**无新 migration（022 未引入——三收口均为 runtime 侧）。

## 9.1 P0-01 Historical Canonical Run Seal Trust（修订 §8.1）

§8.1 的 continuity guard 在信任 prior `manifest.input_normalized_runs`
之前只验证 manifest 文件存在 + 外层 bytes hash == ledger.manifest_hash
+ JSON 可读——rebind 路径成立：改写历史 manifest input list（去掉 A）+
rehash + 只更新 ledger.manifest_hash（input_seal_hash / input_set_hash /
verification_state_hash 保持）+ DELETE CR-2 A → A 被"洗出"continuity
evidence。CR-3.4 起引入 **typed `CanonicalRunSeal`** +
`_verify_historical_canonical_seal()`：continuity 在使用历史 manifest
input list 前先验证完整历史 seal——

```text
1. deterministic manifest URI（expected base + /manifest.json）+
   manifest bytes == ledger.manifest_hash
2. manifest 显式 correctness 字段 == ledger seal（canonical_run_id /
   contract / as_of / idempotency_key / status / requested domains
   json+hash / input_set_hash / input_seal_hash / identity_dataset_hash /
   identity_master_input_set_hash / canonical_context_hash /
   base_identity_hash / verification_state_hash / 三 policy
   version+hash / code_fingerprint）
3. 物理重算（`_input_hashes_from_entries`，与
   CanonicalInputSnapshot 同公式）：
   historical_input_seal_hash       = hash(canonical JSON of 全 seal entries)
   historical_input_set_hash        = hash(canonical JSON of identity
                                       subset——`_INPUT_IDENTITY_FIELDS`
                                       单一事实源，identity_dict 同源）
   historical_verification_state_hash = hash(run_id + verification +
                                       verification_problem_hash per entry)
   三者必须 == ledger（列表被删除/改写/重排/改 seal 字段均无法重算出
   sealed hashes）
```

prior canonical manifest / ledger 自身 DAMAGED → **HARD DAMAGED**：不再
用该 manifest 的 input list 做 continuity 判断，不 mint 任何 replacement。

## 9.2 P0-02 Verification Evidence Replay Symmetry（修订 §8.2）

§8.2 的 replay 分支对 INVALID sealed input 重算 evidence 时硬编码
`materialization_problems=[]`——但 first consume 允许 closure+anchor
健康后在 `_materialize_outputs` 才失败（TOCTOU protection path），因此
first-run seal 可含非空 materialization evidence，replay 永远构造空
列表 → exact evidence hash 无法对称重建（DEVLOG 中"INVALID 短路物化故
恒空"的 rationale 错误——INVALID 是 first-run 物化失败的结果而非前提）。
CR-3.4 起 **first consume 与 replay 共用同一 collector**
`_collect_input_verification_evidence(run identity, role, as_of,
keep_rows)`：

```text
closure problems -> anchored-evidence problems ->（closure+anchor 健康
时）exact-byte materialization verify -> derived verification enum ->
canonical problem evidence -> problem hash
```

first-run（keep_rows=True）额外保留物化行；replay（keep_rows=False）
丢弃行但运行**同一验证序列/语义**。materialization-only failure 可被
replay verifier 精确重建：exact physical failure repeat → idempotent
replay 同一 BLOCKED run（不再自相矛盾）；cause 变化 → 新 exact
evidence identity（新 run）；exact repair → recovery run，历史 BLOCKED
保留。

## 9.3 P0-03 Manifest Correctness Identity 全消费（修订 §7.4）

manifest 显式写入 canonical_context_hash / base_identity_hash /
verification_state_hash，但 §7.4 的 manifest<->ledger 逐字段比较未含
三者（expected_provenance 只证 ledger == current，不证 manifest ==
ledger）——edit manifest 三字段 + rehash + update ledger.manifest_hash
可造出自相矛盾但 verifier 通过的 manifest。CR-3.4 起三字段进入
`_verify_closure` 的 typed manifest binding（manifest == ledger ==
current recompute 三方闭环）；continuity 使用历史 manifest 前同样消费
（§9.1 expected_fields 已含）。

## 9.4 CR-3.4 对抗测试（+20 项）

`tests/integration/test_canonical.py`（151 项 = CR-3/3.1/3.2/3.3 131 项
回归 + 20 新增：HistoricalCanonicalSealTrust 9（input list rebind +
CR-2 DELETE → DAMAGED / entry seal 字段 rebind / input_seal_hash 字段
rebind / input_set+state+base+context 四字段 parametrize rebind / prior
manifest 缺失 HARD DAMAGED / 健康历史 manifest + superset positive
control）/ MaterializationEvidenceSymmetry 4（TOCTOU 第二演员 racy
closure monkeypatch：first-run BLOCKED + evidence hash 精确断言 / exact
failure 幂等 replay / exact repair recovery 保留历史 / cause A→B 新
evidence run）/ ManifestCorrectnessIdentityBinding 7（三方绑定
positive control + SUCCESS replay rebind ×3 parametrize + BLOCKED
replay rebind ×3 parametrize））。总体 1136/0。

## 9.5 Scope 边界

CR-3.4 是 CR-3 关闭前最后一层"历史审计证据本身也不能被重新绑定"的
收口：不建 SnapshotBuilder / ReadModel（CR-4）、不新增 domain、不改
CR-2 frozen contract、**无新 migration**（优先不新增 schema——三收口
全部为 canonicalizer runtime 侧）。CR-3.3 FREEZE 的 18 项机制零重写
（131 项回归全保持）。
