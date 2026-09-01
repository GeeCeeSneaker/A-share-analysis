# ADR-023: AvailabilityPolicy + Canonical Source Selection

- **Status**: PROPOSED（2026-09-01，CR-3 批次交付；Reviewer 复审裁决待定——本 ADR 在复审前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-09-01
- **Work Requirement**: `docs/design/A-share-analysis_CR-2.4最终复审结论与CR-3_AvailabilityPolicy_Canonicalizer开发工作要求_20260901.md`
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
runtime + migration 018 + ADR-022 ACCEPTED 同步 + CR-2.4 P1 guard 加固）。
相关：§42 Canonical Runtime Roadmap、§44 CR-2 acceptance（上游冻结）。
