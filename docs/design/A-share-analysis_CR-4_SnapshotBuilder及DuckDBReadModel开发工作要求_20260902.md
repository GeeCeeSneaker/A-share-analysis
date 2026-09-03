# A-share-analysis：CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild 开发工作要求

> **Stage**：CR-4  
> **Status**：START / ACTIVE  
> **Issued By**：Reviewer / Design Audit  
> **Issue Date**：2026-09-02 21:05 +08:00  
> **Reviewer Start Baseline**：CR-3.6 closure commit `ff3808b7a5036246ea11e37173aa31d863beb2d9`  
> **Reviewed Code Baseline before closure**：`5970f082c0d5b50364b6d4ddf804559cd6ba8f33`  
> **Frozen Upstream**：CR-2 all chain + CR-3 / 3.1 / 3.2 / 3.3 / 3.4 / 3.5 / 3.6  
> **ADR-023**：ACCEPTED  
> **Required New ADR**：ADR-024 Snapshot / ReadModel Contract（PROPOSED until Reviewer closure）  
> **Production P0-M-1B**：BLOCKED independently

---

# 0. 阶段目标

CR-4 的目标是为已经冻结的 Canonical Runtime 建立一个**确定性、可重建、可查询、适合下游 Feature / State 使用的数据读取层**，但本阶段**不计算 Feature，不计算 State**。

目标数据流：

```text
Raw
  ↓
Provider-Normalized
  ↓
Canonical SUCCESS          ← CR-3 已 CLOSED / FREEZE
  ↓
SnapshotBuilder            ← CR-4-A
  ↓
Immutable Snapshot Artifacts
  ↓
DuckDB ReadModel Rebuild   ← CR-4-B
  ↓
Stable query contract
  ↓
Feature / State            ← future stage, NOT CR-4
```

本阶段必须解决两个问题：

1. **如何把一个已经验证过的 Canonical SUCCESS run 变成一个稳定、按 domain 可直接消费的 Snapshot；**
2. **如何仅依赖 Snapshot 重建 DuckDB ReadModel，使下游不需要理解 Canonical manifest / parquet 的内部组织。**

CR-4 的价值是“稳定消费边界”，不是“再做一遍 Canonical”。

---

# 1. 总体不可违反的架构边界

## 1.1 SnapshotBuilder 唯一允许的上游

SnapshotBuilder **只能消费已经存在的、完整验证通过的 Canonical run**。

禁止：

```text
Provider SDK
Raw direct read
Provider-Normalized direct read
meta_provider_normalization_run direct source selection
重新执行 source priority
重新执行 identity guessing
重新计算 limit rule / corporate-action semantics
重新决定 PIT availability
fallback / best effort
```

SnapshotBuilder 的工作必须是：

```text
Verified Canonical selected truth
  -> deterministic projection / partition / key validation / typing
  -> Snapshot
```

不能是：

```text
Provider/CR-2 data
  -> second Canonical implementation
```

## 1.2 DuckDB ReadModel 唯一允许的上游

DuckDB ReadModel Rebuild **只能消费 CR-4 Snapshot**。

禁止 ReadModel builder：

```text
直接读 Raw
直接读 CR-2
直接读 Provider
绕过 Snapshot 直接拼 Canonical + 其它来源
自行补数据
自行做 fallback
自行做 Feature / State 计算
```

ReadModel 是 Snapshot 的**可丢弃、可重建查询缓存 / query projection**，不是新的 evidence truth。

## 1.3 CR-3 全链冻结

CR-4 不得为了实现便利修改以下 CR-3 frozen semantics：

```text
AvailabilityPolicy
SourcePolicy
identity bridge
canonical natural keys
conflict semantics
verification state
historical continuity
Canonical run identity
Canonical artifact seals
status/finding semantics
```

如果 CR-4 暴露出一个真实 Canonical regression，必须单独提出 Reviewer REOPEN 证据；不得在 CR-4 commit 中“顺手调整”。

---

# 2. CR-4-A：Canonical Read Boundary / SnapshotBuilder

## P0-A01：必须建立公开、只读、单一 Canonical Consumption Verifier

CR-4 不允许复制 CR-3 内部 verifier 逻辑。

当前 CR-3 已有：

```text
historical identity seal
canonical artifact closure
findings/status truth
sealed CR-2 input verification
historical continuity
```

CR-4 需要一个正式的、只读的 Canonical consumption boundary，例如：

```python
verify_canonical_run_for_consumption(
    canonical_run_id: str,
) -> VerifiedCanonicalRun
```

命名可调整，但必须满足：

### 对指定 canonical_run_id 至少验证

```text
ledger row exists
manifest deterministic URI
manifest bytes == ledger manifest_hash
manifest explicit correctness fields == ledger
full derived canonical run identity physical recompute
canonical_run_id UUID5 cross-bind
artifact exact set
selected / decisions / findings physical closure
selected / decision semantic seals
findings DB == parquet == finding_set_hash
status / error from findings truth
sealed CR-2 inputs still exist in authoritative CR-2 ledger
sealed CR-2 identity == current authoritative ledger identity
sealed CR-2 physical / raw-anchor verification healthy where the canonical SUCCESS requires healthy input
```

### SnapshotBuilder 只接受

```text
status == SUCCESS
```

`BLOCKED` 必须显式拒绝，不能生成“部分 Snapshot”。

### Important distinction

该 consumption verifier 不应要求“当前 Canonical discovery input set 与历史 run 完全相同”。

例如：

```text
C1 historical SUCCESS consumed A
后来新增 CR-2 B
```

只要 C1 自身 sealed inputs / artifacts 仍完整，C1 应仍可被 SnapshotBuilder 显式消费。

因此不得简单把需要 CURRENT snapshot equality 的 exact replay verifier 当成 Snapshot consumption verifier。

### 禁止

- SnapshotBuilder 调 private `_verify_*` 并自己拼装第二套规则；
- 只检查 `status='SUCCESS'`；
- 只检查 manifest_hash；
- 只检查 selected.parquet 存在。

---

## P0-A02：SnapshotBuilder API 必须显式绑定一个 Canonical run

V1 推荐正式 API：

```python
SnapshotBuilder.build(canonical_run_id: str) -> SnapshotBuildResult
```

不要提供：

```python
build_latest()
build(as_of)  # internally choose latest SUCCESS
build_best_available()
```

原因：CR-4 不能重新引入“latest / best / implicit source choice”。

如果未来需要 orchestration 自动先生成 Canonical 再 Snapshot，应由更高层 workflow 显式传递 `canonical_run_id`，而不是 SnapshotBuilder 自己选。

---

## P0-A03：一个 Snapshot V1 只能来自一个 Canonical run

CR-4 V1 禁止把多个 Canonical runs 拼成一个 Snapshot：

```text
C_daily_bar + C_adj_factor + C_calendar -> one snapshot   ❌ V1 forbidden
```

原因：多个 run 可能属于不同：

```text
as_of
policy world
code fingerprint
verification state
input world
```

多 run fusion 是独立 correctness 问题，不能在第一版 ReadModel 阶段隐式引入。

因此：

```text
1 Snapshot == exactly 1 verified Canonical SUCCESS run
```

Snapshot domain set必须等于该 Canonical run 的 `requested_domains`。

---

## P0-A04：Deterministic Snapshot Identity

必须定义：

```text
SNAPSHOT_CONTRACT_VERSION = "snapshot-v1"   # example
```

Snapshot identity 必须系统派生，不允许 random UUID。

至少进入 identity 的 primitive：

```text
canonical_run_id
canonical manifest hash
canonical requested_domains_hash
canonical selected_semantic_hash
canonical as_of
snapshot contract version
snapshot builder code fingerprint
```

推荐：

```text
snapshot_base_hash = sha256(canonical JSON of primitives)
snapshot_id = UUID5(SNAPSHOT_NAMESPACE, snapshot_base_hash)
```

或等价确定性方案。

要求：

```text
same verified Canonical + same builder contract/code -> same snapshot_id
builder code/contract change -> new snapshot_id
Canonical run change -> new snapshot_id
```

Snapshot identity 不得由 wall-clock / insertion order / temp path 决定。

---

## P0-A05：Snapshot 必须按 Canonical domain 形成独立、稳定 artifact

当前 Canonical V1 支持 domain：

```text
trade_calendar
daily_bar
security_status
limit_price
adj_factor
```

Snapshot 只为该 Canonical run 实际 requested domains 生成 artifact。

推荐布局：

```text
snapshot/
  contract=snapshot-v1/
  as_of=YYYYMMDDTHHMMSSZ/
  snapshot=<snapshot_id>/
    trade_calendar.parquet
    daily_bar.parquet
    security_status.parquet
    limit_price.parquet
    adj_factor.parquet
    manifest.json
```

未 requested 的 domain **不得生成伪空表冒充 requested**。

requested 但合法零行的 domain：允许形成**带确定 schema 的零行 artifact**，不得因 pandas/polars 空表推断导致 schema 漂移。

---

## P0-A06：Snapshot 不能改变 Canonical business truth

Snapshot 可以做：

```text
按 canonical_domain 分表
稳定排序
严格 dtype projection
canonical key typed decode（仅按冻结 Canonical key contract）
字段顺序规范化
lineage 字段保留
```

Snapshot 不可以做：

```text
复权价格计算
收益率计算
技术指标
涨跌停规则推导
ST 规则推导
交易日补全
缺失值填充
forward fill
backfill
价格修正
source merge
identity guessing
```

这些属于 Feature / State 或新的 Canonical semantics，不是 CR-4。

---

## P0-A07：Canonical key round-trip integrity

每个 Snapshot domain 必须验证 Canonical natural key 唯一性。

至少：

```text
trade_calendar      canonical_key unique; market + trade_date consistent

daily_bar           canonical_key unique; security_id + trade_date consistent
security_status     canonical_key unique; security_id + trade_date consistent
limit_price         canonical_key unique; security_id + trade_date consistent
adj_factor          canonical_key unique
```

对于 Canonical row 中没有单独暴露全部 key component 的 domain（当前尤其 `adj_factor` 的 `factor_type`），SnapshotBuilder 可以按**冻结的 Canonical key schema**从 `canonical_key` 严格 typed-decode 出 key component，但必须：

```text
decode -> validate type/arity -> re-encode
re-encoded canonical key == original canonical_key
```

禁止通过 symbol/code/provider 字段反推 key。

如果决定在 Snapshot V1 显式增加 `factor_type` key projection，必须在 ADR-024 和 snapshot schema registry 中写清楚：它是 **Canonical key projection**，不是 provider semantics inference。

---

## P0-A08：PIT / lineage preservation

所有 Snapshot row 必须保留或可无损追溯至少：

```text
canonical_domain
canonical_key
trade_date / canonical date field
available_at
ingested_at
availability_basis
availability_policy_version
selected_provider
source_normalization_run_id
source_output_name
source_row_ordinal
source_row_identity_hash
source_raw_request_id
source_raw_evidence_hash
source_mapper_identity
source_policy_version
canonical_contract_version
canonical_run_id       # Snapshot can add as projection lineage
snapshot_id            # Snapshot can add as projection lineage
```

SnapshotBuilder 必须 defense-in-depth 断言：

```text
row.available_at <= canonical_run.as_of
```

不得通用地假设：

```text
trade_date <= as_of.date
```

因为 calendar / 已知未来计划类数据可能在 as_of 时已经合法可知；PIT 判断以 `available_at` 为准。

---

## P0-A09：Snapshot schema registry 必须显式版本化

不要依赖“当前 Parquet 自动推断出来的 schema”。

需要建立 versioned schema registry，例如：

```text
src/ashare_state/snapshot/schema.py
```

每个 domain 必须有：

```text
required columns
nullable / non-nullable
logical dtype
natural/key projection
stable sort key
```

SnapshotBuilder 遇到：

```text
missing required field
unexpected key arity
null required identity
wrong type
key mismatch
duplicate key
```

必须 fail closed。

不允许 silent cast 把错误值转字符串“先存进去”。

---

## P0-A10：Snapshot artifact / manifest full seal

每个 domain artifact manifest entry 至少：

```text
uri
content_hash
schema_hash
row_count
semantic_hash
```

Snapshot manifest 至少封存：

```text
snapshot_id
snapshot_contract_version
snapshot_builder_code_fingerprint
canonical_run_id
canonical_manifest_uri/hash
canonical_as_of
requested_domains/json/hash
canonical_selected_semantic_hash
domain artifact exact set
per-domain artifact seals
snapshot_semantic_hash
status
```

`manifest.json` 必须 LAST write。

所有 correctness bytes 不得写 wall-clock。

wall-clock 只可进入 ledger audit columns，不得进入 snapshot identity / artifact bytes。

---

## P0-A11：Immutable + Recoverable Write

Snapshot artifacts 采用与 CR-3 类似原则：

```text
new path -> write
same deterministic path + identical bytes -> idempotent no-op
same deterministic path + different bytes -> DAMAGED / conflict
```

若文件写完后 ledger commit 失败：

```text
exact retry
-> same snapshot_id
-> same artifact bytes
-> no-op file verification
-> ledger commit recovery
```

不得：

```text
overwrite old snapshot
rm -rf then rebuild same id
random suffix hide conflict
```

---

## P0-A12：Snapshot ledger / migration

CR-4 预计需要持久化 Snapshot build ledger。

允许新增 **migration 022+**，但不得修改 018-021。

建议最小表：

```text
meta_snapshot_build
```

至少字段：

```text
snapshot_id PK
canonical_run_id
canonical_manifest_uri
canonical_manifest_hash
canonical_as_of
requested_domains_json
requested_domains_hash
snapshot_contract_version
builder_code_fingerprint
manifest_uri
manifest_hash
artifact_set_hash
snapshot_semantic_hash
row_count_total
status
error_message
started_at
completed_at
```

字段最终以 implementation design 为准，但 correctness identity / replay 需要的字段不能只存在 manifest 而无 ledger cross-bind。

如果 migration 022 引入，必须：

```text
from-zero migration test
021 -> 022 upgrade test
idempotent migrate test
tamper probe / checksum gate
```

---

# 3. CR-4-B：DuckDB ReadModel Rebuild

## P0-B01：ReadModel 是 Derived Cache，不是 Evidence Truth

必须在 ADR-024 明确：

```text
Snapshot Parquet + Snapshot Manifest = CR-4 correctness artifact
DuckDB ReadModel = rebuildable derived query projection
```

不要把 DuckDB 文件字节 hash 当核心 evidence seal，因为 DuckDB file physical bytes 可能受内部 metadata / storage layout 影响。

ReadModel correctness 应以**logical rebuild exactness**验证：

```text
table exact set
schema exactness
row count
primary/key uniqueness
semantic hash per table
source snapshot_id
```

---

## P0-B02：ReadModel API 显式绑定 snapshot_id

推荐：

```python
DuckDBReadModel.rebuild(snapshot_id: str) -> ReadModelBuildResult
```

以及只读打开：

```python
DuckDBReadModel.open(snapshot_id: str)
```

禁止：

```text
open_latest()
rebuild_latest_success()
implicit latest snapshot selection
```

需要“当前生产 snapshot alias”的概念，后续另立 publish/promotion stage；CR-4 不实现。

---

## P0-B03：ReadModel rebuild 前必须完整验证 Snapshot

必须建立共享：

```python
verify_snapshot(snapshot_id) -> VerifiedSnapshot
```

验证至少：

```text
snapshot ledger row
manifest deterministic URI/hash
snapshot identity physical recompute
artifact exact set
per-domain URI/content/schema/row_count/semantic hash
requested domain set exactness
canonical provenance cross-bind
```

ReadModel 不允许“文件存在就加载”。

---

## P0-B04：ReadModel table exact set

V1 table set 与 requested Snapshot domains 一一对应。

推荐 table names：

```text
rm_trade_calendar
rm_daily_bar
rm_security_status
rm_limit_price
rm_adj_factor
```

另允许固定 metadata tables：

```text
rm_snapshot_meta
rm_domain_meta
```

未 requested domain 不得残留上一个 rebuild 的旧 table。

必须测试：

```text
snapshot A has daily_bar + calendar
snapshot B only daily_bar
rebuild B
-> calendar old table must not survive
```

---

## P0-B05：Transactional / Atomic Rebuild

不得在当前可读 DuckDB 文件上逐表 destructive update，使 reader 看见 half-rebuilt world。

推荐：

```text
build temp DB
-> create all tables
-> validate full logical seal
-> close/fsync as appropriate
-> atomic replace/publish to deterministic snapshot-specific path
```

或者使用等价的 transactionally safe design。

要求：

```text
rebuild failure -> old complete read model remains intact
new incomplete DB never becomes readable target
```

注意：CR-4 V1 是 snapshot-specific immutable/rebuildable DB，不是“全局 latest”数据库。

---

## P0-B06：Logical semantic exactness

每张 ReadModel table 必须从对应 Snapshot artifact 重算 semantic hash，并与 Snapshot semantic seal一致。

至少验证：

```text
row_count(readmodel) == row_count(snapshot artifact)
semantic_hash(readmodel rows) == snapshot domain semantic_hash
schema == readmodel contract schema
key uniqueness preserved
```

不得因为 DuckDB 自动 cast / decimal coercion / timezone conversion 改变 logical truth。

时间字段必须显式定义 timezone 语义；不能依赖 host local timezone。

---

## P0-B07：查询层不得隐式修改数据

ReadModel 可以提供方便查询的 VIEW / index / sort/order strategy，但不得：

```text
填充空值
计算复权价
计算 return
计算 moving average
计算 market state
补交易日
跨 domain forward-fill
```

可以提供纯关系型 convenience view，例如：

```text
按 security_id + trade_date 连接的 VIEW
```

但 **CR-4 V1 建议先不做 cross-domain convenience join**，避免在 ReadModel 阶段引入时间对齐/缺失策略。

优先把每个 frozen domain 的读取契约做好。

---

## P0-B08：ReadModel provenance

`rm_snapshot_meta` 至少暴露：

```text
snapshot_id
snapshot_contract_version
canonical_run_id
canonical_as_of
requested_domains
readmodel_contract_version
builder/rebuild code fingerprint
```

每个 domain table / meta 必须能够追溯到唯一 snapshot_id。

下游 Feature stage 以后必须通过这个 metadata 知道自己消费的是哪一个 snapshot world。

---

# 4. Snapshot V1 domain contract 基线

Snapshot 必须基于 CR-3 frozen supported domain matrix，不新增 domain。

## 4.1 trade_calendar

Canonical key：

```text
market + trade_date
```

Snapshot required business fields至少：

```text
market
trade_date
canonical_key
lineage / PIT fields
```

不在 CR-4 补开市/休市推理。

## 4.2 daily_bar

Key：

```text
security_id + trade_date
```

Business values：

```text
open
high
low
close
pre_close
volume
amount
```

Snapshot 不做复权。

## 4.3 security_status

Key：

```text
security_id + trade_date
```

Business values：

```text
pre_close
high_limited
low_limited
price_high_lmt_rate
price_low_lmt_rate
is_st_sec
is_susp_sec
is_wd_sec
is_xr_sec
```

Snapshot 不重新解释制度规则。

## 4.4 limit_price

Key：

```text
security_id + trade_date
```

Values：

```text
pre_close
up_limit
down_limit
up_limit_rate
down_limit_rate
```

Snapshot 不根据 code / board / ST 状态重新计算涨跌停。

## 4.5 adj_factor

Canonical natural key：

```text
security_id + canonical date + factor_type
```

Current Canonical selected row 必须以 `canonical_key` 作为最终 key truth。

若 Snapshot 暴露：

```text
factor_type
```

只能从 Canonical key strict decode，不得从 provider dataset 名称猜测。

Values：

```text
adj_factor
backward_factor
```

CR-4 不计算 adjusted OHLC。

---

# 5. ADR-024 必须回答的问题

CR-4 第一批实现必须新增：

```text
ADR-024 Snapshot and DuckDB ReadModel Contract
status = PROPOSED
```

至少回答：

1. 为什么 Snapshot V1 = exactly one Canonical run；为什么不做 multi-run fusion？
2. 为什么 Snapshot artifact 是 correctness truth，而 DuckDB 是 rebuildable cache？
3. Snapshot identity 由哪些 primitive 构成？为什么不含 wall-clock？
4. 为什么 CR-4 API 显式要求 canonical_run_id / snapshot_id，而没有 latest/best？
5. canonical key 如何 round-trip；`adj_factor.factor_type` 如需 projection 如何定义？
6. empty requested domain 的 schema 如何稳定？
7. DuckDB rebuild 如何做到 atomic / no half-world？
8. DuckDB physical-byte determinism 为什么不是 contract；logical semantic exactness 如何证明？
9. 未来 Feature / State 应依赖哪个接口，不应依赖哪些内部路径？
10. alternatives：
   - direct query Canonical parquet；
   - one global mutable DuckDB；
   - multi-run snapshot fusion；
   - views over parquet vs copied tables；
   并说明取舍。

---

# 6. Required implementation layout（建议，不强制文件名）

推荐：

```text
src/ashare_state/
  snapshot/
    __init__.py
    schema.py
    builder.py
    verifier.py
    models.py
  readmodel/
    __init__.py
    schema.py
    duckdb_model.py
    verifier.py
    models.py
```

Canonical 公共消费 verifier 可放：

```text
src/ashare_state/canonical/verifier.py
```

但不能复制 canonicalizer 内已有公式；应抽取复用或形成唯一实现。

---

# 7. CR-4 Mandatory Test Matrix

## 7.1 Canonical consumption boundary

1. SUCCESS intact -> consumable。
2. BLOCKED -> SnapshotBuilder refuses。
3. canonical manifest missing -> refuse。
4. canonical selected bytes tampered -> refuse。
5. canonical decisions tampered -> refuse。
6. findings DB/parquet drift -> refuse。
7. canonical run-id/derived identity drift -> refuse。
8. sealed CR-2 input ledger row disappeared -> refuse。
9. sealed CR-2 physical evidence damaged -> refuse。
10. historical SUCCESS remains consumable after unrelated/new CR-2 superset appears（positive）。

## 7.2 Snapshot identity / replay

11. same Canonical + same code -> same snapshot_id。
12. domain input ordering does not change snapshot_id/bytes。
13. builder code fingerprint change -> new snapshot identity。
14. exact rebuild -> byte-identical Parquet + manifest。
15. file write success + ledger failure -> exact retry recovers。
16. same deterministic path different bytes -> refuse overwrite。
17. Snapshot manifest missing/tampered -> verifier refuses。
18. Snapshot ledger manifest_hash rebind only -> refuse。
19. Snapshot artifact content tamper -> refuse。
20. Snapshot artifact row_count/schema/semantic rebind -> refuse。

## 7.3 Domain schema / key

21. duplicate canonical_key -> fail closed。
22. daily_bar security_id/key mismatch -> fail closed。
23. limit_price key mismatch -> fail closed。
24. trade_calendar market/key mismatch -> fail closed。
25. adj_factor canonical key wrong arity -> fail closed。
26. adj_factor factor_type projection round-trip mismatch -> fail closed（若 projection implemented）。
27. required non-null identity missing -> fail closed。
28. requested zero-row domain -> deterministic typed empty artifact。
29. `available_at > canonical as_of` -> fail closed。
30. future `trade_date` but valid `available_at <= as_of` 不得被通用规则错误删除（positive）。

## 7.4 DuckDB rebuild

31. verified Snapshot -> rebuild success。
32. damaged Snapshot -> zero DB publish。
33. table exact set equals requested domains + fixed meta tables。
34. stale table from previous/different rebuild cannot survive。
35. all table schemas exact。
36. row counts exact。
37. semantic hashes equal Snapshot domain hashes。
38. timezone values round-trip exact。
39. rebuild failure mid-table -> no half-built target published。
40. exact second rebuild -> same logical hashes / schemas / row counts。
41. no direct Raw / CR-2 / Provider access production AST/static guard。
42. no Feature/State calculation helpers imported into CR-4 production code。

## 7.5 Migration / CI

若新增 migration 022+：

43. from-zero。
44. previous latest -> new migration upgrade。
45. idempotent migration。
46. tamper/checksum probe。

Full CI：

47. Windows py3.12。
48. Windows py3.14。
49. Ubuntu py3.14。
50. Ruff / format / mypy / full pytest / existing gates all green。

---

# 8. CR-4 Exit Gate

CR-4 只有在以下全部成立后才能 Reviewer closure：

```text
[ ] formal public Canonical consumption verifier exists and is single-source
[ ] SnapshotBuilder accepts explicit canonical_run_id only
[ ] BLOCKED Canonical cannot produce Snapshot
[ ] one Snapshot == one Canonical run
[ ] deterministic snapshot identity
[ ] versioned Snapshot schema registry
[ ] supported requested domain exact-set artifacts
[ ] canonical key round-trip / uniqueness enforcement
[ ] PIT available_at invariant preserved
[ ] no Feature / State / fill / fallback semantics
[ ] full Snapshot artifact + manifest seal
[ ] immutable / exact retry recoverability
[ ] Snapshot verifier full replay closure
[ ] DuckDB consumes Snapshot only
[ ] explicit snapshot_id API; no latest/best
[ ] table exact set / stale-table prevention
[ ] atomic/no-half-world rebuild
[ ] logical semantic exactness across Snapshot -> DuckDB
[ ] metadata provenance complete
[ ] migration tests green if schema changes
[ ] frozen CR-3 regression matrix remains green
[ ] full three-leg CI green
[ ] ADR-024 complete
[ ] DEVLOG + DEVELOPMENT_MANAGEMENT synchronized
```

---

# 9. 明确禁止范围

CR-4 不允许：

```text
Feature engineering
technical indicators
returns
rolling windows
market regime/state
stock scoring
strategy/backtest logic
portfolio construction
production account
simulated/live trading
provider expansion
new canonical domain
corporate_action semantic unblocking
index identity guessing
industry taxonomy semantics
business fallback
```

这些全部属于后续阶段或独立 research project。

---

# 10. Governance / 交付要求

开发提交必须同步：

```text
ADR-024
ADR-000 index
DEVLOG append-only entry
DEVELOPMENT_MANAGEMENT
本工作要求 Implementation Mapping
```

第一笔 CR-4 开发提交必须先把上一阶段 Reviewer closure 同步进治理文档：

```text
CR-3..3.6 -> VERIFIED / CLOSED / FREEZE
ADR-023 -> ACCEPTED
CR-4 -> START / ACTIVE
Reviewer baseline -> ff3808b7a5036246ea11e37173aa31d863beb2d9
```

重要设计变化必须在 ADR-024 Amendment 中记录理由、替代方案和成本，不允许只在代码注释中改变 contract。

大体积 DuckDB / Parquet 测试输出不得提交仓库；提交：

```text
小型 deterministic fixtures
测试代码
结论/摘要
hash / rowcount / schema evidence
```

不要提交完整大数据产物。

---

# 11. Reviewer 期望的第一批实现顺序

建议严格按以下顺序，避免一次铺太大：

```text
CR-4.0
  governance sync + ADR-024 + contracts/models

CR-4.1
  Canonical public consumption verifier
  + mandatory 1-10

CR-4.2
  SnapshotBuilder identity/schema/artifacts/ledger/replay
  + mandatory 11-30

CR-4.3
  DuckDB ReadModel rebuild/verification/atomic publish
  + mandatory 31-42

CR-4.4
  migration/CI/governance final closure batch if needed
```

可以在一个 implementation commit 中完成，但 Reviewer 将按上述逻辑层次审查；不要通过相互依赖的巨大函数把四层混在一起。

---

# 12. Owner View

```text
Canonical Runtime
   ✅ correctness / PIT / continuity / artifact closure 已冻结
            │
            ▼
CR-4 SnapshotBuilder
   🔧 把一个 Verified Canonical SUCCESS
      变成稳定、按 domain、严格 schema 的 Snapshot
            │
            ▼
CR-4 DuckDB ReadModel
   🔧 从 Snapshot 原样重建查询数据库
      数据库坏了可以重建，Snapshot 才是 correctness artifact
            │
            ▼
Future Feature / State
   ⏸ 下一阶段再进入指标、状态、特征计算
```

**本阶段判断标准：CR-4 做完以后，下游研究代码应该能够稳定地“按 snapshot_id 打开一个完整 A 股市场事实世界”，而不需要知道 Provider、CR-2、Canonical source selection、manifest 内部细节，也不会无意中读取到另一个时间世界的数据。**

---

# 13. Implementation Mapping（CR-4 首批，2026-09-03）

> Reviewed base：CR-3 全链 closure reviewer 基线 `ff3808b7a5036246ea11e37173aa31d863beb2d9`（CR-4 启动裁决）；implementation commit `<本批提交后回填>`（CI 三腿确认后回填）。总体 **1235/0**（1179 → 1235，+56 项对抗测试）；ruff check / ruff format / mypy 全绿（78 源文件）；migration **022**（链 21 → 22）。治理同步（§12 裁决要求的第一动作，同 commit 完成）：ADR-023 → ACCEPTED、ADR-000 索引、CR-3.6 工作要求 Reviewer Closure 章节、DM 基线 `ff3808b`、CR-3 全链 VERIFIED/CLOSED/FREEZE。

## 13.1 §5 十问实现对照（ADR-024 PROPOSED 全文见 `docs/adr/ADR-024_snapshot_builder_readmodel.md`）

| # | 问题 | 实现 |
| --- | --- | --- |
| 1 | Snapshot 输入 | CR-4.1 公共消费验证器 `verify_canonical_run_for_consumption`（`canonical/verifier.py`）——Builder 绝不直接读 canonical parquet、绝不重实现 canonical 校验；内部复用 CR-3 唯一实现（identity seal / artifact closure / findings truth / sealed-input 权威+物理验证） |
| 2 | identity 计算 | `snapshot_base_hash` = canonical run-level seals（run_id/manifest_hash/requested_domains_hash/selected_semantic_hash/as_of）+ snapshot contract + builder code fingerprint 的 canonical JSON SHA-256；`snapshot_id = UUID5(SNAPSHOT_NAMESPACE, ...)` |
| 3 | 磁盘布局 | `snapshot/contract=snapshot-v1/as_of=<YYYYMMDDTHHMMSSZ>/snapshot=<id>/<domain>.parquet + manifest.json(LAST)`；artifact 集 == 请求 domain 集 |
| 4 | fingerprint | `snapshot_builder_code_fingerprint()`（snapshot/schema.py + canonical/verifier.py + snapshot/builder.py 源码 SHA-256 行尾归一）进 identity；verify 拒绝不同 builder 版本构建的 snapshot |
| 5 | schema 单一事实源 | `snapshot/schema.py` 版本化 registry（列集/DType/nullability/key_arity/key projection）——builder 投影 / snapshot verifier / readmodel 建表三方共用 |
| 6 | typed key projection | canonical_key JSON 数组严格 round-trip；**market = canonical payload 字段**（trade_calendar 行自带）；**factor_type = key projection**（key 第 3 段 decode，ColumnSpec.key_index=2） |
| 7 | lineage | 全部 canonical selected-row lineage 字段逐字保留 + 仅新增 canonical_run_id / snapshot_id 两个投影；PIT 断言 available_at <= as_of fail closed |
| 8 | migration 022 | `meta_snapshot_build`（18 列 + idx canonical_run_id）；canonical_as_of 与 canonical ledger 同名同型（TIMESTAMPTZ UTC instant）；重复 snapshot_id fail、exact retry 幂等 replay、crash 残留 fail closed |
| 9 | ReadModel 原子发布 | temp 库构建 → temp 上 logical seal → `Path.replace` 原子替换确定性目标；失败 temp 删除旧目标字节不变 |
| 10 | 表结构固定 | 每次 rebuild 全新 temp 库（无 stale 表结构可能）+ 表集精确比对 + information_schema 列类型精确比对（TIMESTAMP WITH TIME ZONE）+ 表内容重算 semantic hash == 域 seal |

## 13.2 Mandatory 测试映射（1-50）

**Mandatory 1-10（消费验证器）→ `tests/integration/test_snapshot.py::TestCanonicalConsumptionVerifier`**：1 `test_consume_verified_success_green` / 2 `test_consume_unknown_run_rejected` / 3 `test_consume_blocked_run_rejected` / 4 `test_consume_after_superset_growth_green`（C1 consumed A + 新增 B 后 C1 仍可消费）/ 5 `test_consume_rejects_input_ledger_drift` + `test_consume_rejects_input_disappearance` / 6 `test_consume_rejects_status_rebind`（typed seal 先拦截，语义重算同判） / 7 `test_consume_rejects_canonical_manifest_rebind` / 8+9 `test_consume_rejects_selected_artifact_tamper` + `test_consume_rejects_input_physical_damage` / 10 `test_builder_rejects_unverifiable_canonical_input`（零文件零 ledger 行）。

**Mandatory 11-30（SnapshotBuilder）→ `TestSnapshotBuilder` + `TestSnapshotSchemaProjection`**：11 `test_build_success_writes_artifacts_and_ledger` / 12 `test_exact_retry_idempotent_replay` + `test_crash_residue_directory_fails_closed` / 13 `test_conflicting_duplicate_ledger_row_fails` / 14 `test_snapshot_id_deterministic_across_environments` + `test_artifacts_deterministic_bytes`（**同环境语义**：抹掉 snapshot 层重建 → 同 id 同 bytes；跨环境 byte 相等被刻意不主张——raw evidence meta 含 ingest wall-clock，跨独立 ingest 的 canonical run id 必不同，identity determinism 的主张对象是同一 verified canonical truth）/ 15 `test_different_canonical_run_different_snapshot` / 16 `test_identity_from_canonical_seals_not_rows`（manifest 的 canonical 字段 == canonical ledger + fingerprint == 当前代码）/ 17 `test_artifact_set_equals_requested_domains` / 18 `test_domain_partitioned_rows`（schema == registry）/ 19 `test_rows_sorted_by_canonical_key` / 20 schema registry unit（`test_key_roundtrip_validation` / `test_pit_contract_enforced` / `test_typed_projection_fail_closed`——wrong type / None non-nullable / nullable None 合法）/ 21 `test_lineage_preserved_verbatim`（含 typed 时间投影的 instant 精确比较）/ 22 `test_verify_snapshot_green` / 23 `test_verify_snapshot_unknown_id_rejected` / 24 `test_verify_snapshot_manifest_bytes_tamper` + `test_verify_snapshot_manifest_field_rebind` / 25 `test_verify_snapshot_domain_artifact_tamper` + `test_verify_snapshot_domain_artifact_missing` / 26 `test_verify_snapshot_identity_rebind` + `test_verify_snapshot_uri_rebind` / 27 `test_verify_snapshot_builder_fingerprint_mismatch` / 28 `test_verify_snapshot_canonical_drift_fails` + `test_verify_snapshot_canonical_input_disappearance`（build 后 canonical 损坏 → cross-bind fail closed）/ 29 `test_verify_snapshot_requested_domain_drift` / 30 `test_builder_immutable_no_overwrite`。

**Mandatory 31-42（ReadModel）→ `tests/integration/test_readmodel.py::TestDuckDBReadModel`**：31 `test_rebuild_success` / 32+33 `test_logical_seal_row_counts_and_semantics`（表内容重算 semantic == 域 seal）/ 34 `test_no_stale_table_between_snapshots` / 35+36 `test_schema_exactness_with_explicit_timezone`（TIMESTAMP WITH TIME ZONE + UTC instant 精确 round-trip）/ 37 `test_key_uniqueness` / 38 `test_meta_tables_content` / 39 `test_rebuild_unknown_snapshot_fails_clean`（零 temp 残留）/ 40 `test_exact_second_rebuild_idempotent` / 41 `test_rebuild_atomic_failure_leaves_target_intact`（注入 logical seal 失败 → 旧目标字节不变 + temp 清理 + 模型仍可用）/ 42 `test_open_read_only_unknown_snapshot`。

**Mandatory 43-46（migration/CI）**：43 from-zero 22 链 + `meta_snapshot_build` ∈ EXPECTED_TABLES（`test_all_tables_created` / `test_idempotent_rerun` 更新至 22）/ 44 upgrade 021→022 只应用新尾 + 18 列全验证（`test_upgrade_from_prior_chain_applies_only_new_tail`）/ 45 idempotent rerun / 46 tamper probe 023（`test_tamper_check_runs_before_any_new_migration`）。47-50 CI 三腿 + Ruff/format/Mypy/governance gates——推送后 API 正向确认（回填）。

**边界（§8）→ `TestBoundaryStructure`**：snapshot/ 与 readmodel/ AST guard（禁 providers/normalization/raw_writer；禁 pandas/talib/numpy/scipy/sklearn）；`SnapshotBuilder.build` 签名只接受 canonical_run_id。

## 13.3 实现中发现并修复的工程问题（均以测试钉死）

- DuckDB TIMESTAMPTZ fetch 返回本地时区（Windows GMT+8 session timezone）——`verify_snapshot` 的 as_of 与 readmodel logical seal 的行值统一 `astimezone(UTC)` 归一化（UTC instant 才是 deterministic anchor / semantic truth）
- `read_parquet` 自动 hive_partitioning 把 artifact 路径的 `contract=/as_of=/snapshot=` 段误读为分区列（+3 列 Binder 错误）——`read_parquet(..., hive_partitioning=false)`
- adj_factor 的 factor_type 不在 canonical payload_fields（只进 canonical key）——schema registry 以 key projection 列（key_index=2）携带
- polars dict-rows + 显式 schema 会把 extra keys 也带为列——snapshot 投影先经 registry 严格过滤再构造 frame（列集 == registry 精确）

## 13.4 CR-3 Latent 缺陷显式申报（§12 流式红线合规）

**发现**：CR-3 `_write_artifacts` 的 selected/decision semantic seal 曾对**未对齐 rows**计算，而 parquet 写入 `_align_schema` 对齐后的 rows——多 domain 混合时（不同 domain 行的 key 集合不同）exact replay 从 parquet 重算的 semantic hash 必然与 ledger seal 失配 → 误报 DAMAGED（fail-closed 方向 false positive）。单 domain 时 key 集合一致故对齐是无操作——1179 项既有回归全绿、六轮复审均未暴露；CR-4 多 domain 消费首次触发。

**处理路径（未悄悄修复）**：最小修复（seal 改为对 aligned rows 计算——单 domain 行为逐字节不变，194 项既有 canonical 回归全保持即证明）+ `TestMultiDomainReplayRegression::test_multi_domain_exact_replay_idempotent`（4 domain SUCCESS 幂等 replay）回归钉 + ADR-024 Consequences / DM-20260903-075 / DEVLOG 申报 + **提请 Reviewer 在 CR-4 复审中一并裁决该 CR-3 frozen 机制的修正**。

## 13.5 Exit Gate 自检（§12）

```text
[x] consumption verifier 是唯一 canonical 读取入口（BLOCKED 拒绝 + superset 语义正确）  -> canonical/verifier.py + mandatory 1-10
[x] snapshot identity 确定性 + run-level seals 派生 + fingerprint 参与                     -> mandatory 14-16
[x] artifact 集精确 == 请求域；domain 分区；schema registry 强制                            -> mandatory 17-20
[x] lineage 全保留 + 仅两个 snapshot 投影 + PIT 断言                                       -> mandatory 21
[x] immutable artifacts + manifest LAST + exact retry 幂等 + crash 残留 fail closed        -> mandatory 11-13/30
[x] verify_snapshot 全物理重算 + canonical provenance cross-bind（build 后损坏也拦截）      -> mandatory 22-29
[x] readmodel temp→logical seal→原子替换；失败零残留；表集/schema/时区/唯一性/semantic 全验   -> mandatory 31-42
[x] migration 022 from-zero/upgrade/idempotent/tamper probe                                -> mandatory 43-46
[x] 边界 AST guard（providers/normalization/raw/特征库全禁）                                -> TestBoundaryStructure
[x] CR-3 冻结机制零"悄悄修改"——唯一触碰为显式申报的 latent 缺陷修复（回归钉 + 提请裁决）     -> §13.4
[x] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff/format/Mypy/governance gates          -> 推送后 API 正向确认（回填本节）
[ ] Reviewer 复审裁决（含 CR-3 latent 缺陷修复的追认）                                      -> PENDING_REVIEW
```
