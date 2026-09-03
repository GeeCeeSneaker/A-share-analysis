# A-share-analysis：CR-4.4 最终复审、CR-4 全链关闭与 CR-5 启动裁决

> **Review Date**：2026-09-03 17:15 +08:00  
> **Reviewer Baseline**：`a47b73c5ee3df429264b61fd62fa774b066cb62d`  
> **Reviewed Branch**：`codex/cr-4.4-closure-20260903`  
> **Reviewed Branch HEAD**：`b040ce2733b25408a9697f8af523f6a4b524bea2`  
> **Primary CR-4.4 Implementation**：`cad56f39fc4f8d50b2eefdae45045dd5a86237a5`  
> **Final Product / CI-green HEAD**：`3e19aa5690ebd1f90818a0ee7b52de44423b7dc9`  
> **PR**：#1 `codex/cr-4.4-closure-20260903 -> main`，OPEN / MERGEABLE  
> **Latest Branch CI**：run `33734170963` — SUCCESS  
> **Verdict**：**CR-4.4 VERIFIED / CLOSED / FREEZE；CR-4 全链 VERIFIED / CLOSED / FREEZE；PR #1 APPROVED_TO_MERGE**  
> **ADR-024**：**ACCEPTED（随 PR #1 合并生效）**  
> **Next Stage**：**CR-5 Deterministic Feature Layer + PIT Feature Snapshot — START / ACTIVE after merge**  
> **Production P0-M-1B**：BLOCKED independently

---

# 0. Reviewer 最终裁决

CR-4.4 对上一轮 Reviewer 提出的 5 个 correctness blocker 已完成针对性收口。复核代码、对抗测试、CI 与治理记录后，**未发现新的、足以继续阻塞 CR-4 的 P0 correctness blocker**。

正式裁决：

```text
CR-4.1 Canonical Consumption Boundary      VERIFIED / CLOSED / FREEZE
CR-4.2 SnapshotBuilder                     VERIFIED / CLOSED / FREEZE
CR-4.3 DuckDB ReadModel                    VERIFIED / CLOSED / FREEZE
CR-4.4 Correctness Closure                 VERIFIED / CLOSED / FREEZE
CR-4                                       VERIFIED / CLOSED / FREEZE
ADR-024                                    ACCEPTED
PR #1                                      APPROVED_TO_MERGE
CR-5                                       START / ACTIVE AFTER MERGE
Production P0-M-1B                         BLOCKED independently
```

由于本次实现尚位于 PR #1 分支而非 `main`，上述 **CR-4 FREEZE / ADR-024 ACCEPTED 以 PR #1 合入 main 为生效点**。不得在未合并 Reviewer-approved CR-4.4 代码的旧 `main` 上启动 CR-5 产品代码。

---

# 1. P0-01 Canonical -> Snapshot Deterministic Derivation — VERIFIED / FREEZE

当前已经形成单一共享投影：

```text
project_verified_canonical_snapshot(...)
```

Builder 与 `verify_snapshot()` 同时使用该函数，统一执行：

```text
VerifiedCanonicalRun.selected_rows
        ↓
requested-domain membership
        ↓
strict typed projection
        ↓
PIT available_at <= as_of
        ↓
explicit key binding
        ↓
canonical-key uniqueness
        ↓
stable deterministic ordering
        ↓
expected Snapshot rows
```

`verify_snapshot()` 不再只证明 Snapshot 自身 seal 自洽，而是把物理 artifact rows 与上述 **Canonical replay expected rows** 做 exact semantic comparison。

因此即便攻击者同时重绑：

```text
artifact bytes
content_hash
semantic_hash
artifact_set_hash
snapshot_semantic_hash
manifest_hash
snapshot ledger outer seals
```

只要业务值或 lineage 不再等于 Verified Canonical truth，就会被拒绝。

**裁决：PASS / FREEZE。**

---

# 2. P0-02 Recoverable Immutable Snapshot Publication — VERIFIED / FREEZE

当前 deterministic path 写入语义已修正为：

```text
missing path                       -> write expected bytes
existing file + identical bytes   -> immutable no-op
existing file + different bytes   -> HARD CONFLICT
non-file at deterministic path    -> HARD CONFLICT
```

构建流程：

```text
build all deterministic bytes in memory
        ↓
preflight ALL artifact + manifest paths
        ↓
write missing domain artifacts
        ↓
manifest LAST
        ↓
ledger transaction LAST
```

已覆盖：

- ledger commit failure 后完整 residue exact retry recovery；
- partial identical residue recovery；
- conflicting residue refuse；
- existing committed snapshot full verify idempotent replay。

这同时满足 **immutable** 与 **recoverable**，不再需要人工删除 crash residue 才能恢复。

**裁决：PASS / FREEZE。**

---

# 3. P0-03 Explicit Natural-Key Binding — VERIFIED / FREEZE

Snapshot schema registry 已把 key shape 提升为 typed binding contract：

```text
trade_calendar
  key[0] == market
  key[1] == trade_date

daily_bar / security_status / limit_price
  key[0] == security_id
  key[1] == trade_date

adj_factor
  key[0] == security_id
  key[1] == trade_date
  key[2] -> factor_type typed key projection
```

因此“JSON 形状正确，但 row identity 与 key 内容不一致”已经 fail closed。

禁止 CR-5 重新从 symbol/code/provider 字段推断这些身份；Feature 层必须消费 Snapshot / ReadModel 中已经冻结的 typed identity。

**裁决：PASS / FREEZE。**

---

# 4. P0-04 Same-Byte Verification + Physical Schema Seal — VERIFIED / FREEZE

Canonical shared artifact verifier 与 Snapshot verifier 均已采用：

```text
bytes = path.read_bytes()
sha256(bytes) == sealed content_hash
parse SAME bytes
```

不再出现：

```text
hash path read A
then parser rereads path B
```

公共 Canonical consumption boundary 也直接复用 shared artifact verifier 从 exact verified bytes materialize 的 `selected_rows`，不再 post-verification reread path。

Snapshot verifier 同时：

```text
physical frame schema
        ↓
actual_schema_hash recompute
        ↓
compare manifest schema_hash
        ↓
aggregate artifact_set_hash uses physical recompute
```

因此 `schema_hash` 已从 declaration 变成真正被消费的 correctness seal。

**裁决：PASS / FREEZE。**

---

# 5. P0-05 ReadModel Provenance + Verified Open — VERIFIED / FREEZE

`rm_snapshot_meta` 已包含并验证：

```text
snapshot_id
snapshot_contract_version
canonical_run_id
canonical_as_of
requested_domains
readmodel_contract_version
snapshot_builder_code_fingerprint
readmodel_builder_code_fingerprint
```

`rm_domain_meta` 对每一行强制：

```text
snapshot_id == target snapshot_id
domain belongs exact requested set
artifact URI / rowcount / semantic hash == verified Snapshot
```

正式打开路径现在为：

```text
open_read_only(snapshot_id)
        ↓
verify_snapshot(snapshot_id)
        ↓
open SAME target DB read-only
        ↓
_validate_logical_seal(on that handle)
        ↓
only then return handle
```

显式 `verify_readmodel(snapshot_id)` 同样使用该 verified-open 路径。

因此以下情况均在 handle 暴露前拒绝：

- foreign Snapshot DB copied into another snapshot path；
- `rm_snapshot_meta` drift；
- `rm_domain_meta` foreign snapshot binding；
- table business value tamper；
- schema / rowcount / key uniqueness / semantic drift；
- upstream Snapshot / Canonical provenance degradation。

ReadModel 仍保持 **rebuildable cache**，不是 evidence truth；发生损坏时正确动作是从 Verified Snapshot rebuild，不是信任或修补现有 DB。

**裁决：PASS / FREEZE。**

---

# 6. CR-3 Exact-Byte Hotfix 复核

CR-4.4 为满足 same-byte requirement，对 CR-3 shared verifier 做了最小 correctness hotfix：

- Canonical artifact parse 使用已经 hash-verified 的 bytes；
- sealed CR-2 output verification 同样 parse verified bytes；
- public consumption verifier 复用 verified selected rows。

该修改没有改变：

```text
PIT semantics
SourcePolicy
IdentityBridge
conflict semantics
run identity
findings/status truth
historical continuity
```

属于对 CR-3 已冻结 Exact Byte 原则的实现补强，而非重新设计 Canonical。

**CR-3 保持 VERIFIED / CLOSED / FREEZE。**

---

# 7. Tests / CI

CR-4 首批：`1235 passed`。

CR-4.4 final：

```text
1256 passed / 0 failed
```

最新分支 HEAD `b040ce2733b25408a9697f8af523f6a4b524bea2` 的 PR CI run：

```text
33734170963
```

确认：

```text
Windows Python 3.12     SUCCESS
Windows Python 3.14     SUCCESS
Ubuntu  Python 3.14     SUCCESS
Ruff lint               SUCCESS
Ruff format             SUCCESS
Mypy                    SUCCESS
Full Pytest             SUCCESS
Spike gates             SUCCESS
AmazingData SDK absent  SUCCESS
DEVLOG gate             SUCCESS where applicable
Management-doc gate     SUCCESS where applicable
```

此前 code-final run `33732904158` 也三腿成功；最后 docs/governance branch HEAD 又独立跑绿，因此不存在“代码 HEAD green、最后文档 HEAD 未验证”的悬空状态。

---

# 8. CR-4 Frozen Contract

自 PR #1 合并起，以下 CR-4 V1 contract 进入 FREEZE：

```text
1. public Canonical consumption verifier is the only downstream Canonical truth boundary
2. explicit canonical_run_id only; no latest/best
3. 1 Snapshot == exactly 1 verified Canonical SUCCESS run
4. deterministic Snapshot identity
5. static versioned Snapshot schema registry
6. explicit canonical natural-key cross-binding
7. deterministic Canonical -> Snapshot replay projection
8. domain exact-set Parquet artifacts including typed zero-row domains
9. PIT lineage preservation
10. full physical artifact/content/schema/rowcount/semantic seals
11. exact-byte parse after hash verify
12. manifest LAST
13. immutable + exact-retry recoverable publication
14. migration 022 meta_snapshot_build
15. Snapshot verification re-verifies Canonical provenance
16. ReadModel consumes Verified Snapshot only
17. snapshot-specific DuckDB; no global latest database
18. ReadModel exact table set
19. schema / rowcount / key / semantic logical seal
20. explicit timezone semantics
21. complete ReadModel provenance fingerprints
22. temp build -> logical seal -> atomic replace
23. verified-open before read handle escapes
24. no Provider / Raw / CR-2 source selection in CR-4
25. no Feature / State calculations in CR-4
```

任何 CR-5 代码不得为了指标开发便利修改或旁路上述规则。真实 regression 必须单独提交证据后由 Reviewer 明确 REOPEN。

---

# 9. Merge / Governance Handoff

PR #1 已经通过 Reviewer correctness review，正式：

```text
APPROVED_TO_MERGE
```

合并到 `main` 时/后，下一笔治理同步必须把：

```text
ADR-024 status -> ACCEPTED
ADR-000 index -> ADR-024 ACCEPTED
DEVLOG append-only -> CR-4.4 Reviewer closure
DEVELOPMENT_MANAGEMENT ->
  CR-4 / 4.1 / 4.2 / 4.3 / 4.4 VERIFIED / CLOSED / FREEZE
  CR-5 START / ACTIVE
  Production P0-M-1B remains BLOCKED
```

不得改写历史 DEVLOG 条目，只追加 closure。

---

# 10. 下一阶段

CR-5 正式名称：

> **Deterministic Feature Layer + PIT Feature Snapshot**

详细开发合同见同批 Reviewer 文档：

`docs/design/A-share-analysis_CR-5_DeterministicFeatureLayer及PITFeatureSnapshot开发工作要求_20260903.md`

CR-5 的核心目标是：

> 在不破坏 Snapshot world identity、PIT lineage、missingness truth 和可重建性的前提下，把冻结的市场事实转换成可供未来 State 层消费的确定性基础特征；不进入策略、打分、回测或实盘。
