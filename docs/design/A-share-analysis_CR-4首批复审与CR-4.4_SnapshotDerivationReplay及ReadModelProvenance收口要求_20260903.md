# A-share-analysis：CR-4 首批复审与 CR-4.4 Snapshot Derivation / Replay / ReadModel Provenance 收口要求

> **Review Date**：2026-09-03 13:03 +08:00  
> **Reviewer Baseline**：`7d67926f8ecefde7d82116bf587655cde41236b3`  
> **Reviewed HEAD**：`738e116875cb1a9ee3c0eb4ad66bb37c521b0bfa`  
> **Primary Implementation**：`2db6d8d6cc1fef047175b1f23c80016f003eee63`  
> **Test-only Fixes**：`397ea7c0ffc8860b29b874dadbbd86792c8c503c` / `0c328c3de95c636df053a52bb5b4814fde2d14cb`  
> **CI Run**：`33715493176` — Windows 3.12 / Windows 3.14 / Ubuntu 3.14 SUCCESS  
> **Verdict**：**CR-4 DONE / REOPENED；CR-4.1～4.3 主体方向 PASS，但不得 FREEZE；CR-4.4 START / ACTIVE**  
> **ADR-024**：PROPOSED / NOT ACCEPTED  
> **CR-5 Feature**：BLOCKED_BY_CR-4.4  
> **Production P0-M-1B**：BLOCKED independently

---

# 0. Reviewer 裁决摘要

CR-4 首批已经把正确的主骨架建立起来：

```text
Verified Canonical SUCCESS
        ↓
public canonical consumption verifier
        ↓
1 Canonical run -> 1 deterministic Snapshot
        ↓
domain-partitioned immutable Parquet + manifest + ledger
        ↓
verify_snapshot
        ↓
DuckDB temp rebuild
        ↓
logical seal
        ↓
atomic publish
```

以下机制本轮 **PASS / 保留**：

1. `verify_canonical_run_for_consumption()` 作为正式下游 Canonical 读取边界；
2. SnapshotBuilder 显式 `build(canonical_run_id)`，无 latest / best；
3. one Snapshot == exactly one Canonical run；
4. deterministic snapshot identity；
5. versioned Snapshot schema registry；
6. requested domain exact-set artifacts + typed zero-row artifact；
7. PIT `available_at <= as_of` defense-in-depth；
8. Snapshot manifest LAST-write；
9. migration 022 `meta_snapshot_build`；
10. ReadModel 只消费 `verify_snapshot()`；
11. snapshot-specific DuckDB；
12. temp DB -> logical seal -> atomic replace；
13. table exact set / schema / rowcount / semantic hash / key uniqueness；
14. timezone explicitness；
15. CR-4 AST boundary：无 Provider/Raw/CR-2 direct source selection、无 Feature/State；
16. CI 三平台通过。

但是，Reviewer 复核发现 **5 个 correctness blocker**。这些不是功能偏好，而是 CR-4 原始 P0 contract 尚未真正闭环，因此 CR-4 本轮不能 CLOSED。

---

# 1. CR-3 latent semantic-seal defect 裁决：最小修复 ACCEPTED / RE-FREEZE

开发人员申报：CR-3 `_write_artifacts()` 过去在 multi-domain run 中，对 **unaligned rows** 计算 `selected_semantic_hash / decision_set_hash`，而 Parquet 实际写入的是 `_align_schema()` 后的 rows；因此 replay 从 Parquet 重算时会误报 DAMAGED。

Reviewer 复核后裁决：

```text
该缺陷真实存在；
修复方向正确；
属于 frozen CR-3 的可复现 correctness regression；
允许最小 hotfix；
不构成 CR-3 语义重新设计。
```

当前改为：

```text
aligned_selected = _align_schema(selected_rows)
aligned_decisions = _align_schema(decisions)
selected_semantic_hash <- aligned_selected
decision_set_hash      <- aligned_decisions
Parquet                 <- same aligned rows
```

并增加 multi-domain exact replay regression pin。

**裁决：该 CR-3 hotfix ACCEPTED；CR-3 继续维持 VERIFIED / CLOSED / FREEZE。**

注意：CR-4.4 P0-04 还会要求把 artifact verifier 的“hash bytes 与 parse bytes”统一成同一份 exact bytes；这是新的 exact-byte verification hotfix，不允许顺带改 CR-3 其它语义。

---

# 2. P0-01：Snapshot 缺少 Canonical → Snapshot 的派生真值闭环

## 2.1 当前问题

当前 `verify_snapshot()` 做了：

```text
snapshot ledger / manifest cross-bind
snapshot UUID5 identity recompute
canonical run re-verification
artifact URI/hash/schema/rowcount/semantic self-consistency
PIT / projection-id sanity
```

但它 **没有重新从 VerifiedCanonicalRun.selected_rows 计算 expected Snapshot rows**，也没有证明：

> Snapshot domain artifacts 的业务值，确实等于当前 snapshot contract 对该 Canonical selected truth 的确定性投影。

因此存在直接 bypass：

1. 已有 healthy Canonical C + Snapshot S；
2. 修改 S 的 `daily_bar.close`（保持 key/schema/PIT 合法）；
3. 重新写 Parquet；
4. 重算该 domain 的 `content_hash / semantic_hash`；
5. 重算 `artifact_set_hash / snapshot_semantic_hash`；
6. 更新 snapshot manifest + outer manifest hash；
7. 同步更新 `meta_snapshot_build.manifest_hash / artifact_set_hash / snapshot_semantic_hash`；
8. Snapshot identity 不变，因为 snapshot_id 只绑定 Canonical run-level primitives + builder fingerprint；
9. 当前 verifier 会看到“Snapshot 自身全部 seal 自洽 + Canonical C 仍健康”，从而可能通过。

这违反：

```text
P0-A06 Snapshot cannot change Canonical business truth
P0-A10 full Snapshot artifact/manifest seal
Exit Gate: Snapshot verifier full replay closure
```

## 2.2 Required closure

抽取一个 **builder + verifier 共用** 的确定性 projection helper，例如：

```text
project_verified_canonical_snapshot(
    verified_canonical,
    snapshot_id,
) -> {domain: exact projected rows}
```

它必须是 SnapshotBuilder 构建和 `verify_snapshot()` replay 的唯一 projection 实现：

```text
VerifiedCanonicalRun.selected_rows
  -> domain grouping
  -> canonical-key cross-field validation
  -> strict typed projection
  -> PIT check
  -> key uniqueness
  -> canonical_key stable sort
```

`verify_snapshot()` 在完成 canonical consumption verification 后，必须重新生成 expected rows，并至少验证：

```text
actual domain row exact set / semantic hash == expected projection
actual requested-domain row counts == expected projection counts
```

推荐进一步直接比较 canonicalized exact rows；不能只比较 manifest 自己声明的 seal。

## 2.3 Mandatory tests

1. Snapshot business value tamper + 完整重算 artifact seals + manifest + ledger outer seals -> **DAMAGED**。
2. Snapshot lineage value tamper + 完整 rebind -> **DAMAGED**。
3. untouched Snapshot replay -> PASS。
4. legitimate zero-row requested domain -> PASS。

---

# 3. P0-02：P0-A11 Immutable + Recoverable Write 实现与合同相反

## 3.1 当前问题

CR-4 原始要求明确：

```text
new path -> write
same deterministic path + identical bytes -> idempotent no-op
same deterministic path + different bytes -> conflict / DAMAGED

files written + ledger commit failure
-> exact retry
-> same snapshot_id
-> verify same bytes
-> no-op existing files
-> ledger commit recovery
```

当前实现：

```text
if target_dir.exists() and ledger row missing:
    raise SnapshotBuilderError("unexplainable residue")
```

且 `_write_immutable()` 对任何 existing path 一律拒绝。

当前测试 `test_crash_residue_directory_fails_closed` 甚至把**与 Mandatory 15 相反的行为**写成了通过条件。

因此 P0-A11 / Mandatory 15 尚未完成。

## 3.2 Required closure

构建过程应先确定所有 deterministic expected bytes，再使用 shared immutable-recoverable writer：

```text
path missing
  -> write exact bytes

path exists
  -> read existing bytes
  -> identical -> no-op / recovered residue
  -> different -> conflict / DAMAGED
```

manifest 仍然 LAST。

若 prior crash 只写了一部分 artifacts：

```text
existing identical subset -> keep
missing expected artifacts -> continue exact write
conflicting existing artifact -> refuse
```

ledger commit retry成功后，形成正常 SUCCESS row。

不得 `rm -rf`、覆盖、随机 suffix。

## 3.3 Mandatory tests

5. Inject ledger commit failure **after all files written** -> first call fails, zero ledger；second exact retry -> same snapshot_id / same bytes / ledger SUCCESS。
6. Partial identical residue -> retry completes missing files + ledger SUCCESS。
7. Existing same path different bytes -> refuse, zero ledger overwrite。
8. Exact normal replay with ledger row -> remains idempotent。

原 `test_crash_residue_directory_fails_closed` 必须修正；不能继续把与规范相反的行为标记成 Mandatory coverage。

---

# 4. P0-03：Canonical key 只做 JSON round-trip，没有做 row ↔ key cross-field consistency

## 4.1 当前问题

当前 `validate_canonical_key()` 只检查：

```text
JSON array
arity
non-empty string components
canonical JSON re-encode
```

但 `project_selected_row()` 没有验证：

```text
trade_calendar:
  key[0] == row.market
  key[1] == row.trade_date

daily_bar / security_status / limit_price:
  key[0] == row.security_id
  key[1] == row.trade_date

adj_factor:
  key[0] == row.security_id
  key[1] == row.trade_date (canonical ex_date projection)
  key[2] == projected factor_type
```

因此当前可接受“canonical_key 格式完全正确，但 row identity/business key columns 指向另一个实体/日期”的 row。

这正是原要求 Mandatory 22/23/24 的目的，当前测试矩阵未覆盖该攻击。

## 4.2 Required closure

Snapshot schema registry 应显式保存 key projection contract，而不仅是 `key_arity`。

推荐：

```text
DomainSnapshotSchema:
  key_components / key_bindings
  stable_sort_key
```

并形成 shared validation：

```text
decode canonical key
-> typed/arity round-trip
-> compare key components against row columns / declared key projections
-> mismatch => fail closed
```

不得从 provider symbol / dataset 猜 key。

## 4.3 Mandatory tests

9. daily_bar security_id/key mismatch -> fail。
10. daily_bar trade_date/key mismatch -> fail。
11. limit_price security_id/key mismatch -> fail。
12. trade_calendar market/key mismatch -> fail。
13. trade_calendar trade_date/key mismatch -> fail。
14. adj_factor security_id/date mismatch -> fail。
15. adj_factor factor_type projection positive + wrong arity negative 均保持。

---

# 5. P0-04：Physical seal 未全部 physical recompute；exact-byte verification 存在 reread gap

## 5.1 Snapshot schema_hash 未被消费

当前 `verify_snapshot()`：

```text
frame.schema == registry schema   # 有检查
```

但没有：

```text
sha256(str(frame.schema)) == manifest.artifacts[domain].schema_hash
```

随后 `recomputed_seals` 又直接复制 manifest 中的 `schema_hash` 来重算 `artifact_set_hash`。

因此攻击者可以修改 manifest `schema_hash`，同步重算 artifact_set / outer manifest / ledger fields，而 physical schema bytes 本身不变；当前 verifier 不会证明 sealed `schema_hash` 等于 physical schema hash。

这违反 P0-A10 / Mandatory 20。

### Required

```text
actual_schema_hash = sha256(str(frame.schema))
actual_schema_hash == artifact entry schema_hash
recomputed artifact_set uses actual_schema_hash
```

Mandatory：artifact `schema_hash` ledger/manifest coherent rebind -> DAMAGED。

## 5.2 Hash bytes 与 parse bytes 必须是同一份 exact bytes

当前 Canonical artifact verifier 与 Snapshot verifier 均存在模式：

```text
data = path.read_bytes()
verify sha256(data)
frame = pl.read_parquet(path)   # 再次从 path 读取
```

public Canonical consumption verifier 在 artifact verifier 返回后还再次：

```text
pl.read_parquet(selected_path)
```

这意味着“通过 hash 的 bytes”和“真正物化给下游的 rows”不是结构上同一份 bytes，存在 TOCTOU / post-verification reread gap。

对于本项目已经冻结的 exact-byte 原则，这是不允许的。

### Required

共享 verifier 应：

```text
data = path.read_bytes()
sha256(data) verify
frame = pl.read_parquet(BytesIO(data))
rows = frame.to_dicts()
```

并将 verified/materialized rows 从同一 helper 返回给 downstream；public consumption verifier 不得在 verifier 之后重新按 path 读取 selected artifact。

Snapshot verifier 同理：hash 后必须解析同一 `data` bytes。

若需调整 CR-3 `_verify_canonical_artifacts`，只允许 exact-byte materialization hotfix + focused regression，不得改 frozen semantics。

## 5.3 Mandatory tests

16. Snapshot manifest schema_hash coherent rebind -> DAMAGED。
17. Canonical public consumption verified rows 必须来自 hash-verified exact bytes（可通过 monkeypatch/path swap regression 证明无 post-verify reread）。
18. Snapshot verifier domain rows同样来自 exact verified bytes。
19. Existing CR-3 artifact tamper/replay regressions全绿。

---

# 6. P0-05：ReadModel provenance / consumption boundary 尚不完整

## 6.1 rm_snapshot_meta 缺少 required code provenance

原 P0-B08 要求 `rm_snapshot_meta` 至少暴露：

```text
snapshot_id
snapshot_contract_version
canonical_run_id
canonical_as_of
requested_domains
readmodel_contract_version
builder/rebuild code fingerprint
```

当前表没有 snapshot builder / readmodel rebuild code fingerprint。

必须新增至少：

```text
snapshot_builder_code_fingerprint
readmodel_builder_code_fingerprint
```

定义 `readmodel_builder_code_fingerprint()`，覆盖真正影响 ReadModel logical construction 的 governed source（至少 readmodel schema + rebuild implementation；具体集合在 ADR-024 Amendment A 写清）。

## 6.2 logical seal 未完整消费 provenance columns

当前 `_validate_logical_seal()` 没有验证：

```text
rm_snapshot_meta.canonical_as_of
rm_domain_meta 每行 snapshot_id == verified.snapshot_id
```

这些都必须纳入 exact provenance validation。

## 6.3 open_read_only 当前只信文件路径存在

当前 `open_read_only(snapshot_id)`：

```text
if target exists:
    duckdb.connect(..., read_only=True)
```

若把另一个 snapshot 的、结构完全合法的 DuckDB 文件复制到该 deterministic target path，当前 open API 会直接把错误 world 交给下游。

这与本阶段 Owner View 的目标冲突：

> 下游应能按 snapshot_id 打开一个完整且被证明属于该 snapshot world 的查询模型。

### Required closure

建立 shared `verify_readmodel(snapshot_id)` 或让 `open_read_only()` 在返回连接前执行 read-only logical seal：

```text
verify_snapshot(snapshot_id)
open target read-only
verify exact table set/schema/rowcount/semantic/meta provenance
only then return/open handle
```

ReadModel 是 cache，所以目标损坏时可提示 rebuild；但不能静默读错。

如果担心每次 full semantic verify 成本，V1 correctness 优先；性能优化以后另做有完整性锚的 verified-open strategy，不能先信路径。

## 6.4 Mandatory tests

20. rm_snapshot_meta code fingerprints 存在且 exact。
21. canonical_as_of meta drift -> verify/open refuse。
22. rm_domain_meta foreign snapshot_id -> verify/open refuse。
23. 将 Snapshot B 的 valid DuckDB bytes 替换到 Snapshot A target path -> `open_read_only(A)` refuse。
24. target DuckDB logical row tamper -> verify/open refuse。
25. untouched model verified open -> PASS。
26. rebuild failure仍保持旧 verified target intact。

---

# 7. CR-4.4 Scope

只允许：

```text
P0-01 shared Canonical->Snapshot deterministic projection replay
P0-02 recoverable immutable snapshot write
P0-03 key cross-field binding
P0-04 exact physical schema seal + exact-byte materialization
P0-05 ReadModel provenance + verified open
focused tests
ADR-024 Amendment A
DEVLOG append-only
DEVELOPMENT_MANAGEMENT sync
CR-4 work requirement Implementation Mapping sync
```

禁止：

```text
Feature / State
returns / indicators
multi-run snapshot fusion
latest/best alias
new canonical domain
provider expansion
fallback/fill
production account work
```

migration 018-021 必须继续 untouched；022 如无需 schema 变更不得重写，未来若需要新 persistent project-ledger schema 使用 023+。ReadModel 自身 derived DB schema 变化不需要 project DB migration。

---

# 8. CR-4.4 Exit Gate

全部成立后 Reviewer 才能关闭 CR-4：

```text
[ ] P0-01 Snapshot rows physically derived/cross-bound to Verified Canonical selected truth
[ ] coherent Snapshot business-value rebind cannot pass
[ ] P0-02 file-complete + ledger-failure exact retry recovers
[ ] partial identical residue recoverable; conflicting residue refuses
[ ] P0-03 every domain key components cross-bound to row fields
[ ] P0-04 snapshot schema_hash physically recomputed/consumed
[ ] hash bytes == parsed/materialized bytes on Canonical consumption path
[ ] hash bytes == parsed/materialized bytes on Snapshot verification path
[ ] no post-verification selected.parquet reread
[ ] P0-05 ReadModel metadata provenance complete
[ ] readmodel builder fingerprint exists
[ ] canonical_as_of + rm_domain_meta.snapshot_id consumed
[ ] open_read_only cannot silently open foreign/tampered snapshot model
[ ] public Canonical consumption boundary remains single-source
[ ] one Snapshot == one Canonical run
[ ] Snapshot identity semantics unchanged unless required by proven fix
[ ] PIT / zero-row typed schema / domain exact-set green
[ ] atomic ReadModel rebuild green
[ ] CR-3 multi-domain seal hotfix regression green
[ ] CR-3/CR-2/R4 frozen regression matrices green
[ ] migration chain 022 green; 018-021 untouched
[ ] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 green
[ ] Ruff / format / mypy / pytest / spike / SDK-absent / governance gates green
[ ] ADR-024 Amendment A complete
[ ] DEVLOG + DEVELOPMENT_MANAGEMENT + Implementation Mapping synchronized
[ ] Reviewer sees no new P0 blocker
```

通过后：

```text
CR-4 / CR-4.1 / CR-4.2 / CR-4.3 / CR-4.4
-> VERIFIED / CLOSED / FREEZE

ADR-024
-> ACCEPTED

CR-5 Feature Layer
-> eligible to START (需 Reviewer 先下发正式工作要求)
```

---

# 9. Owner View

当前不是 CR-4 推倒重来，而是“主体完成，最后 correctness closure”。

```text
Canonical Runtime                  ✅ CLOSED / FREEZE
   │
   ├─ CR-3 multi-domain seal hotfix ✅ ACCEPTED / RE-FREEZE
   │
   ▼
Canonical Consumption API          ✅ 主体完成
   │                                  🔧 exact-byte return closure
   ▼
SnapshotBuilder                    ✅ 主体完成
   │                                  🔧 Canonical->Snapshot derivation cross-bind
   │                                  🔧 key row-binding
   │                                  🔧 recoverable exact retry
   │                                  🔧 schema_hash physical consume
   ▼
Snapshot Verifier                 ✅ 主体完成
   │                                  🔧 exact-byte + expected-projection replay
   ▼
DuckDB ReadModel                  ✅ 主体完成
                                      🔧 provenance fingerprints
                                      🔧 verified-open / foreign-model refusal

Feature / State                   ⏸ BLOCKED_BY_CR-4.4
```

工程闭合度（不是代码量/工时）：

```text
Canonical consumption boundary      ~90%
Snapshot deterministic identity     100%
Snapshot schema / partitioning       ~90%
Snapshot derivation correctness      ~75%
Snapshot recoverable write           ~60%
Snapshot physical seal               ~90%
DuckDB rebuild / atomic publish      ~95%
DuckDB provenance / verified open    ~75%
CR-4 overall correctness maturity    ~85%
```

下一开发提交请以本文件作为 Reviewer authoritative handoff，并同步治理文档；不要启动 CR-5。
