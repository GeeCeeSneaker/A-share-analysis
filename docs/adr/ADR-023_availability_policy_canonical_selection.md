# ADR-023: AvailabilityPolicy + Canonical Source Selection

- **Status**: PROPOSED（2026-09-01，CR-3 批次交付 + CR-3.1 Amendment A 收口；Reviewer 复审裁决待定——本 ADR 在复审前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-09-01（CR-3）/ 2026-09-01（Amendment A，CR-3.1）
- **Work Requirement**: `docs/design/A-share-analysis_CR-2.4最终复审结论与CR-3_AvailabilityPolicy_Canonicalizer开发工作要求_20260901.md` + `docs/design/A-share-analysis_CR-3复审与CR-3.1最终CanonicalInputSnapshot及ReplaySeal收口要求_20260901.md`
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
Availability Evidence / Full Replay Seal / Recoverable Commit）。相关：§42
Canonical Runtime Roadmap、§44 CR-2 acceptance（上游冻结）。

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
