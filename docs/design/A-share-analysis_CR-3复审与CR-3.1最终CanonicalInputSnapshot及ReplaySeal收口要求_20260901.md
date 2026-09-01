# A-share-analysis：CR-3 复审与 CR-3.1 最终 Canonical Input Snapshot / PIT Trust / Replay Seal 收口要求

> **Review Date**：2026-09-01 19:06 +08:00  
> **Reviewed Repository HEAD**：`e1c6bb2236a1b0eac06ee214b7cf64cf4fe13f79`  
> **Primary CR-3 Implementation**：`ae5b76c998196f936ae6430408d2a016a35aec0d`  
> **Reviewer Baseline / Requirements**：`cfa59403556bc81ba592c11d2e48788562e8b3cf`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-3 已正确部分**：**主体架构 PASS / FREEZE**  
> **Next Batch**：**CR-3.1 Final Canonical Input Snapshot + Anchored Availability Evidence + Full Replay Seal + Recoverable Commit**  
> **ADR-023**：**PROPOSED / NOT ACCEPTED**  
> **CR-4**：**BLOCKED_BY_CR-3.1**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-3 已经完成 Provider-Normalized -> Canonical 的主体运行框架，方向正确，且 current HEAD CI 三腿 green。本轮正式确认并冻结以下机制，CR-3.1 不得推倒重写：

```text
PASS / FREEZE  CanonicalRunner 是唯一正式 canonical boundary；无 SDK/provider 调用
PASS / FREEZE  Formal input 只从 CR-2 normalization ledger/artifact 发现，不接受 caller DataFrame/list
PASS / FREEZE  typed AvailabilityPolicy registry；v1 采用 OBSERVED_AT_INGEST
PASS / FREEZE  availability filter 在 source selection / reconciliation 之前执行
PASS / FREEZE  禁止 trade_date 00:00 / 1970 / 固定 close time 伪造 available_at 的设计方向
PASS / FREEZE  static versioned SourcePolicy；caller 无 priority/tolerance/fallback/partial 注入参数
PASS / FREEZE  exact conflict handling：equal -> EQUIVALENT_MERGED；unequal -> SOURCE_CONFLICT BLOCK
PASS / FREEZE  duplicate canonical key -> blocking finding；无 last-write-wins / silent dedupe
PASS / FREEZE  IdentityBridge 不用代码前缀猜交易所；bare code 只允许 unique-market match
PASS / FREEZE  PIT relist identity 方向（latest list_date <= trade_date）
PASS / FREEZE  5 个 CANONICAL_SUPPORTED domain 主体映射
PASS / FREEZE  security_master / ca_projection AUXILIARY_ONLY 边界
PASS / FREEZE  corporate_action projection 不冒充 DIRECT_EVENT
PASS / FREEZE  canonical 包无硬编码涨跌停制度百分比
PASS / FREEZE  CR-3 未越界实现 SnapshotBuilder / DuckDB ReadModel（CR-4 边界保持）
PASS / FREEZE  migration 018 additive canonical ledger / finding schema
PASS / FREEZE  CR-2.4 RawWriter anti-bypass P1 guard 已加固
PASS / FREEZE  current HEAD CI Windows 3.12 / Windows 3.14 / Ubuntu 3.14 green
```

但从“同一份 Canonical truth 是否由一个**唯一、稳定、可复验的 as-of 输入世界**产生”继续审查后，发现若干 P0 correctness blockers。它们不是 SourcePolicy/AvailabilityPolicy 设计推翻，而是 **run identity / authoritative input snapshot / raw PIT evidence / replay seal / retry closure** 未完全收口。

正式状态：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4   VERIFIED / CLOSED / FREEZE
CR-3                              DONE / REOPENED（主体 PASS / FREEZE）
CR-3.1                            START / ACTIVE NEXT
ADR-023                           PROPOSED / REVIEWER NOT ACCEPTED
CR-4                              BLOCKED_BY_CR-3.1
Production P0-M-1B                BLOCKED independently
```

不重开 CR-2.x / R4-B2/B1/A3/A2/CR-1，除非 CR-3.1 引入可复现 regression。

---

# 1. P0-01：requested domain set 没有进入 canonical run identity

## 1.1 当前代码事实

`CanonicalRunner.run(as_of, domains=...)` 允许 caller 选择受治理 domain，但当前：

```text
_run_identity(as_of, fingerprint)
 -> _input_set_hash()
 -> _identity_dataset_hash()
 -> as_of / contract / policies / fingerprint
```

**没有 requested domains。**

同时 `_input_set_hash()` 使用的是全部 `supported_domains() + security_master` 的全局成功 run 集合，而不是本次 requested set。

因此同一 DB / 同一 `as_of`：

```text
run(as_of=T, domains=(daily_bar,))
 -> run_id = R

run(as_of=T, domains=(trade_calendar,))
 -> 仍可能 run_id = R
 -> prior 命中
 -> 直接 replay 第一份 daily_bar canonical run
```

这会让 caller 请求 A domain，却得到 B domain 的历史 artifact，是直接 correctness blocker。

## 1.2 CR-3.1 Required Closure

- 定义 canonical **RequestedDomainSet**：去重、排序后的 exact set；
- RequestedDomainSet 的 canonical hash / canonical JSON 必须进入 run identity；
- manifest + ledger 显式绑定 requested domain exact set/hash；
- 同一 set 不同 caller 顺序应视为同一 semantic identity（例如 `(daily_bar, limit_price)` 与反序相同）；
- 不同 set 即使相同 as_of/inputs/policies 也必须是不同 run id；
- replay 返回的 `domains` 必须来自 ledger/manifest seal，不能丢失。

### 必测

```text
same as_of + daily_bar only != same as_of + trade_calendar only
same as_of + {daily_bar,limit_price} order A/B -> same run
replay domains exact == sealed requested domains
manifest requested_domains rebind -> DAMAGED
ledger requested_domains/hash tamper -> DAMAGED
```

migration 019+ 建议增加 `requested_domains_json` / `requested_domains_hash`（命名可调整），不要修改 018。

---

# 2. P0-02：全部候选在 as_of 之后时，当前可 false SUCCESS

## 2.1 当前代码事实

当前流程正确地执行：

```text
candidate.available_at > as_of
 -> EXCLUDED_FUTURE decision
 -> 不参与 source selection
```

但 `REQUIRED_DOMAIN_MISSING` 的判断是：

```python
if not eligible.get(domain):
    REQUIRED_DOMAIN_MISSING
```

它判断的是“有没有 eligible CR-2 run”，**不是“as_of 时点有没有可用 candidate”**。

因此：

```text
有 daily_bar SUCCESS normalization run
received_at = 2026-09-01 10:00
as_of       = 2026-09-01 09:00

eligible run exists        = YES
available candidates       = ZERO
selected rows              = ZERO
REQUIRED_DOMAIN_MISSING    = NO
blocking findings          = ZERO
=> status 可能 SUCCESS
```

这违反 CR3-P0-03/P0-08：future-only 数据不能让 historical canonical world 看起来“成功但空”。

## 2.2 Required Closure

对每个 requested domain，AvailabilityPolicy filter 后必须机器判断 **availability completeness**：

```text
no eligible verified CR-2 run
 -> REQUIRED_DOMAIN_MISSING

eligible runs exist but zero PIT-available candidates
 -> REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF（推荐新 class）
   或 REQUIRED_DOMAIN_MISSING + reason=NO_CANDIDATE_AVAILABLE_AT_ASOF
 -> blocking
```

如果某 domain 的业务语义允许“合法空集合”，必须由 domain policy **显式版本化声明**，不能由 caller 决定；v1 暂无此例时默认 required domain 零 candidate = BLOCKED。

### 必测

```text
all candidate received_at > as_of -> BLOCKED, zero selected, EXCLUDED_FUTURE retained
one early + one future -> SUCCESS with early only
future-only must never SUCCESS
adding future-only run must not change earlier selected truth except input identity per frozen snapshot semantics
```

---

# 3. P0-03：authoritative canonical input set 没有一次性 snapshot；存在 read-race

## 3.1 当前代码事实

同一次 `run()` 中 broad input discovery 被重复执行：

```text
_run_identity()
 -> _input_set_hash()           # 第一次 broad query
 -> _identity_dataset_hash()

_collect_verified_runs()        # 第二批 broad query
_build_identity_bridge()        # 再查 master runs

_write_artifacts()
 -> _input_set_hash()           # 再次 broad query

_commit_ledger()
 -> _input_set_hash()           # 再次 broad query
 -> _identity_dataset_hash()
```

这些读没有一个 run-scoped authoritative snapshot 对象，也没有从第一次解析出的 exact set 继续派生。

若 canonical 构建过程中另一个流程插入新的 SUCCESS normalization run：

```text
run_id / idempotency_key    可能按 S1 计算
实际 candidates             可能已经包含 S2
manifest input_set_hash     可能记录 S2
ledger input_set_hash       可能又是 S2/S3
```

run identity / consumed inputs / manifest / ledger 可能不再代表同一个世界。

## 3.2 Required Closure：CanonicalInputSnapshot

建立 immutable typed snapshot（命名可调整）：

```text
CanonicalInputSnapshot
  requested_domains exact set/hash
  source runs exact rows（run_id/provider/surface/dataset/manifest hash/status/...）
  identity master run exact set
  CR-2 closure verification result
  authoritative raw availability evidence bindings
  input_set_hash
  identity_dataset_hash / identity_policy identity
  resolved policy identities
```

要求：

1. **BEGIN / snapshot boundary 在任何 authoritative broad read 之前**；
2. 每个 broad source/master run query 只用于构造 snapshot 一次；
3. run identity、candidate builder、manifest、ledger 全部从同一个 snapshot 派生；
4. 后续不得再次用“当前 DB 全集”重算 input_set hash；
5. 构建过程中新增 normalization run 不得偷偷混入当前 run；下一次 canonical invocation 才看到它并产生新 run identity；
6. snapshot 内每个 CR-2 run closure problem 必须 retained 为 blocking evidence，不能静默从 snapshot 消失。

实现可以：

- 保持 DuckDB transaction snapshot 到 ledger commit；或
- 在 BEGIN 后一次性解析全部权威行并生成 typed immutable snapshot，之后只按 exact IDs 查验证内容；

但必须证明“本 run 的 input set”不是多次 broad query 的 moving target。

### 必测

```text
resolve snapshot S1 -> injection insert SUCCESS run S2 -> current run remains exact S1
next invocation sees S2 -> different run id
identity-master run mid-run insertion cannot alter current bridge
manifest/ledger/input identity all exact equal snapshot S1
```

---

# 4. P0-04：Availability 读取 Raw `received_at` 前没有验证当前 Raw meta 仍是 anchored bytes

## 4.1 当前代码事实

CR-3 对 normalized run 调 `verify_normalized_run()`；该 helper 复用 CR-2 `_verify_run_closure()`，验证 normalized manifest/output/quarantine/current mapper provenance。

但 `CanonicalRunner._received_at()` 随后直接：

```python
meta_path = raw_root / raw_evidence_uri
json.loads(meta_path.read_text())["received_at"]
```

当前 `verify_normalized_run()` **不重新验证当前 raw meta bytes == normalization run raw_evidence_hash == meta_raw_evidence_anchor.evidence_hash**。

因此在 normalization 已经成功后，仅修改 Raw meta：

```text
received_at: 2026-09-01 10:00 -> 2026-08-30 10:00
payload / normalized parquet 完全不动
```

CR-2 normalized closure仍可能是 empty problem，CR-3 却会使用被修改后的时间，把未来数据提前变成历史可用。

这是 PIT trust-root blocker。

## 4.2 Required Closure：AnchoredAvailabilityEvidence

CR-3 在读取 `received_at` 前必须证明：

```text
current raw meta exact-byte SHA256
 == normalization run sealed raw_evidence_hash
 == authoritative meta_raw_evidence_anchor.evidence_hash
```

同时 cross-bind：

```text
provider / provider_dataset / raw_request_id / evidence_uri
```

可以增加下游只读 helper（推荐，不改变 CR-2 运行语义）：

```text
verify_normalized_run_for_canonical(...)
或
verify_raw_availability_evidence(...)
```

该 helper：

- 先验证 current meta bytes hash；
- lookup exact RawEvidenceAnchor；
- anchor missing/mismatch -> blocking；
- 仅在 hash exact 后 parse `received_at`；
- 不从 caller 接 expected hash；
- 不补建 anchor；
- 不重新 mapper。

### 必测

```text
normalization SUCCESS 后、第一次 canonical 前只改 raw received_at -> BLOCK
只改 raw endpoint/account/request params -> BLOCK
raw anchor row missing -> BLOCK
raw anchor hash mismatch -> BLOCK
canonical SUCCESS 后再改 raw received_at -> exact replay refused
intact anchored raw -> available_at == original received_at
```

---

# 5. P0-05：IdentityBridge policy identity 未正确进入 run identity；ledger/manifest 的 identity_dataset_hash 口径不一致

## 5.1 当前代码事实

`IdentityBridge.dataset_hash`：

```text
sha256(IDENTITY_BRIDGE_POLICY_VERSION | master_dataset_hash)
```

manifest 写的是：

```text
identity_dataset_hash = bridge.dataset_hash
```

但 `_run_identity()` 与 ledger `_commit_ledger()` 使用：

```text
_identity_dataset_hash()
 = sha256(master run_id:manifest_hash set)
```

**不包含 `IDENTITY_BRIDGE_POLICY_VERSION`。**

所以：

- 改 relist / bare-symbol / identity bridge policy version，可能不产生新 run identity；
- ledger `identity_dataset_hash` 与 manifest `identity_dataset_hash` 实际不是同一语义口径；
- replay 当前又不比较该字段，因此差异被隐藏。

## 5.2 Required Closure

定义唯一 identity binding：

```text
identity_master_input_set_hash
identity_bridge_policy_version
identity_bridge_policy_hash（建议）
identity_dataset_hash = canonical hash(above)
```

要求：

- run identity 使用同一个 `identity_dataset_hash`；
- manifest/ledger exact same value；
- IdentityBridge 实例从 snapshot 的 exact master rows构建；
- identity policy change -> new run；
- current/replay verifier比较 ledger == manifest == current policy identity。

### 必测

```text
IDENTITY_BRIDGE_POLICY_VERSION bump -> new run
ledger identity hash == manifest identity hash == runtime snapshot hash
manifest identity hash rebind -> DAMAGED
ledger identity hash tamper -> DAMAGED
```

---

# 6. P0-06：SourcePolicy hash 未覆盖全部 correctness 字段

当前 `source_policy_hash()` 只覆盖部分字段：domain / priority / reconciliation / tolerance_rule_id / partial / conflict_action。

但 dataclass 还有会影响 correctness 的：

```text
allowed_fallback_providers
identity_missing_max
required_evidence_class
tolerance_rule_version（虽另有 tolerance hash，但 source policy本身也应语义完整）
```

其中 `allowed_fallback_providers` / `identity_missing_max` 的变化若忘记 bump version，当前 source hash 不会变化。

CR-3.1 必须使 policy hash 对**全部语义字段 exact canonical serialization**（建议 `dataclasses.asdict` + sorted canonical JSON）计算；不要手写漏字段字符串。

同时 runtime 必须诚实消费当前 v1 fields：

- `identity_missing_max` 不应只靠硬编码 `> 0`；
- fallback 若 v1 禁止则明确走 empty allowed set；未来打开必须由 policy + decision class 控制；
- required evidence class 进入 eligibility/manifest binding。

### 必测

```text
only allowed_fallback_providers change -> policy hash/run identity changes
only identity_missing_max change -> policy hash/run identity changes
required_evidence_class change -> policy hash/run identity changes
policy field rebind in manifest/ledger -> DAMAGED
```

---

# 7. P0-07：Canonical replay full seal 未真正消费全部 correctness evidence

## 7.1 当前 verifier 的覆盖范围

当前 `_verify_closure()` 主要验证：

```text
manifest bytes == ledger manifest_hash
manifest run_id / contract / idempotency / status
manifest finding_count == ledger
selected/decisions/findings file bytes == manifest content_hash
artifact row_count
DB finding count + finding_set_hash == ledger
```

但 manifest 已经写入的下列 correctness 字段没有被 full three-way consume：

```text
requested_domains（且尚未入 identity）
input_normalized_runs exact set
input_set_hash
identity_dataset_hash
availability/source/tolerance policy versions/hashes
code_fingerprint
selected_count / decision_count
artifact schema_hash
selected_semantic_hash
finding_set_hash manifest binding
```

同时：

- selected.parquet 的实际 values 没有 replay-time semantic recompute；
- decisions.parquet 没有 semantic seal；
- findings.parquet 没有与 DB finding exact set做 semantic cross-binding；
- schema_hash 记录了但 replay 不重算；
- replay 在返回 prior run 前不 reverify sealed CR-2 source runs + anchored availability evidence。

因此存在 rebind 类路径：

```text
替换 selected.parquet 为同 row_count 的不同值
 -> 更新 manifest artifact content_hash
 -> 更新 ledger manifest_hash
 -> current replay 可能 healthy
```

类似地 decisions/findings audit artifact 可以被替换并 rebind。

## 7.2 Required Closure：CanonicalRunSeal

参考已冻结 CR-2 `NormalizationRunSeal`，建立 typed canonical full seal（命名可调整），至少绑定：

```text
canonical_run_id
requested_domain_set/hash
as_of
contract
input snapshot exact set/hash
identity dataset + identity policy identity
availability/source/tolerance policy version/hash
code fingerprint
status
selected/decision/finding counts
selected semantic hash
decision semantic hash
finding semantic/exact-set hash
artifact exact set（selected/decisions/findings）
artifact uri/content/schema/row_count
idempotency key
```

Replay 必须：

```text
CURRENT requested/input/policy/code identity
      == ledger seal
      == manifest seal
      == replay-time physical recompute
```

并 reverify：

- sealed CR-2 normalized run closures；
- raw availability evidence anchor/hash；
- expected artifact exact set + deterministic URI；
- physical schema/hash/row_count；
- selected semantic values；
- decisions semantic values；
- findings parquet semantic set == DB finding semantic set == ledger/manifest seal。

任何层不一致 -> DAMAGED / replay refused。

### 必测 adversarial rebind matrix

```text
selected values swap same schema+rowcount + manifest/ledger rehash -> BLOCK
selected schema swap + content rebind -> BLOCK
decisions values rewrite + manifest/ledger rehash -> BLOCK
findings parquet rewrite but DB unchanged -> BLOCK
manifest input set/hash rebind -> BLOCK
manifest availability/source/tolerance/identity/code fields rebind -> BLOCK
ledger policy/input/code fields tamper -> BLOCK
artifact missing/extra/duplicate/URI rebind -> BLOCK
CR-2 source artifact tamper after canonical -> replay BLOCK
raw received_at tamper after canonical -> replay BLOCK
```

migration 019+ 应增加缺失的 ledger-side semantic/artifact seals；不修改 018。

---

# 8. P0-08：BLOCKED run 的 findings artifact 含 wall-clock `created_at`，DB failure 后 exact retry 不可恢复

当前 `_write_artifacts()` 在写 findings.parquet 前：

```python
finding["created_at"] = datetime.now(UTC).isoformat()
```

文件先落，DB ledger/findings 后提交。

若：

```text
selected/decisions/findings/manifest 文件成功
 -> DB INSERT/COMMIT 失败并 rollback
 -> exact retry same run id
```

retry 会生成新的 finding `created_at`，findings.parquet bytes 不同；immutable path 已存在，于是 conflict，不能恢复。

这违反 file-first / DB-later recoverable closure，尤其所有 BLOCKED run（有 finding）容易中招。

## Required Closure

- wall-clock audit metadata 不得进入 deterministic correctness artifact bytes；
- finding semantic artifact只含 deterministic fields；
- DB `created_at` 可以是 transaction-time audit metadata，但必须排除 finding semantic hash；
- 或采用其他可证明 deterministic 的 timestamp 来源，但不能 retry 时 `now()`；
- file-side artifacts + manifest 在 DB rollback 后 exact retry必须 byte-identical no-op，然后完成 ledger commit。

### 必测

```text
inject DB failure after artifacts on BLOCKED run with findings
 -> ledger/findings DB rollback
 -> files remain
 -> exact retry succeeds
 -> existing files byte-identical no-op
 -> one canonical ledger row / one exact finding set
```

---

# 9. P1 非阻塞但本批应一起修正

## 9.1 Identity finding 的 canonical_domain 当前硬编码 `daily_bar`

当前跨所有 requested domains 统计 `identity_missing_count`，最终 finding 固定：

```text
canonical_domain = daily_bar
```

若 `security_status` / `limit_price` / `adj_factor` 缺 identity，审计 finding 会写错 domain。CR-3.1 改为 per-domain（最好 per-key/aggregate 均可，但必须真实 scope），不要把其他域记成 daily_bar。

## 9.2 Domain matrix 文档计数错误

代码当前是：

```text
5 CANONICAL_SUPPORTED
2 AUXILIARY_ONLY
6 BLOCKED_PENDING_SEMANTICS
= 13 domains
```

ADR-023 / commit 文案写成“12 domain / 5 blocked”，需按历史不改写原则追加更正（不要删旧 DEVLOG）。

## 9.3 timezone-naive datetime API

`run(as_of=datetime)` 对 naive datetime 直接 `.astimezone(UTC)`，其解释依赖运行机本地时区。为跨平台 deterministic：

- 推荐直接拒绝 `tzinfo is None` 的 datetime；
- string 无 offset 也最好明确合同（建议要求 offset-aware，或固定 UTC 规则并测试）。

必须新增 Windows/Linux 时区独立测试。

---

# 10. CR-3.1 Mandatory Test Matrix

除所有 CR-3 / CR-2 frozen regressions外，至少新增：

```text
01 requested daily_bar vs trade_calendar same as_of -> distinct run
02 requested same domain set different order -> same run
03 replay returns exact requested domain set
04 future-only eligible runs -> BLOCKED, never SUCCESS
05 early + future -> early selected / future excluded
06 CanonicalInputSnapshot mid-run source insertion -> current S1 unchanged
07 next invocation after insertion -> new identity S2
08 mid-run identity-master insertion -> current bridge unchanged
09 first canonical before: raw received_at meta-only tamper -> BLOCK
10 raw anchor missing/mismatch -> BLOCK
11 canonical after success: raw received_at tamper -> replay refused
12 identity bridge policy version change -> new run
13 ledger/manifest identity dataset hash exact same
14 source policy allowed_fallback change -> hash/new run
15 identity_missing_max change -> hash/new run
16 selected values rebind -> replay refused
17 selected schema rebind -> replay refused
18 decisions rebind -> replay refused
19 findings parquet vs DB divergence -> replay refused
20 manifest input/policy/code rebind -> replay refused
21 ledger input/policy/code tamper -> replay refused
22 CR-2 normalized source tamper after canonical -> replay refused
23 artifact exact-set / URI rebind -> replay refused
24 BLOCKED file-write success + DB fail -> exact retry recovers
25 identity finding domain truthful (status/limit/factor cannot report daily_bar)
26 naive datetime deterministic fail/reject
27 migration 019 from-zero
28 migration 018 -> 019 upgrade
29 migration idempotent/checksum/tamper sequence
30 current CR-3 tests + all CR-2/B2/B1/A3/A2/CR-1 regressions
31 Windows 3.12 green
32 Windows 3.14 green
33 Ubuntu 3.14 green
34 Ruff / format / Mypy / Spike / governance gates green
```

建议显式加入 monkeypatch/injection hook，只用于测试“snapshot 解析完成后插入新 normalization run”的 race；production API 不暴露该 hook。

---

# 11. CR-3.1 Exit Gate

全部通过才允许：

```text
CR-3 / CR-3.1 VERIFIED / CLOSED / FREEZE
ADR-023 ACCEPTED
CR-4 SnapshotBuilder + ReadModel START
```

Exit Gate：

- RequestedDomainSet exact bind；
- future-only required domain fail closed；
- one authoritative CanonicalInputSnapshot；
- run identity / consumed candidates / manifest / ledger exact same snapshot；
- availability received_at anchored evidence exact verify；
- identity bridge policy enters correctness identity；
- policy hash covers all semantic fields；
- canonical full seal consumed on replay；
- replay re-verifies source CR-2 closure + raw PIT evidence；
- selected/decisions/findings semantic seals；
- artifact schema/exact-set/URI verify；
- DB failure exact retry recoverable；
- truthful identity finding scope；
- timezone deterministic；
- no CR-4 logic leak；
- migration + full CI green；
- governance sync complete。

不得因为 current CI green 或 1025 tests green 跳过以上 adversarial cases；当前缺口正是测试矩阵未覆盖的 correctness corners。

---

# 12. Governance / ADR / 管理总册要求

下一 developer commit 必须同步：

- `docs/DEVLOG.md`：append CR-3.1 correction，不改写历史；
- `docs/project/DEVELOPMENT_MANAGEMENT.md`：CR-3 -> REOPENED / CR-3.1 ACTIVE / CR-4 BLOCKED；
- ADR-023 保持 PROPOSED，并追加 CR-3.1 Amendment A，纠正：
  - requested domain set identity；
  - CanonicalInputSnapshot；
  - anchored availability evidence；
  - identity policy binding；
  - full replay seal；
  - recoverable commit；
- ADR index 同步 ADR-023 PROPOSED / CR-3.1 pending；
- domain count 12 -> 13 的更正以 append/correction 方式登记；
- 风险/TD/change log 按管理总册现有规则同步。

状态必须写成：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4   CLOSED / VERIFIED / FREEZE
CR-3                              DONE / REOPENED
CR-3.1                            ACTIVE / NEXT
ADR-023                           PROPOSED
CR-4                              BLOCKED_BY_CR-3.1
Production P0-M-1B                BLOCKED independently
```

---

# 13. Reviewer Owner-View Summary

CR-3 现在已经能做“从 Provider-Normalized 候选中按 as-of、身份、来源政策生成 Canonical”的主体流程，但还不能把输出称为最终稳定 canonical truth，原因集中在：

```text
本次到底请求哪些 domain
        +
本次到底看到哪一组 CR-2 输入
        +
received_at 是否仍是 ingestion-time 原始真值
        +
以后 replay 时 canonical 文件和上游 lineage 是否还能全部证明没变
```

CR-3.1 不增加新业务 domain、不做 CR-4、不扩功能面；只把这四个“正确性身份”一次封死。
