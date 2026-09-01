# A-share-analysis：CR-3.1 复审与 CR-3.2 最终 Snapshot Transaction / Verified Read Boundary 收口要求

> **Review Date**：2026-09-01 21:01 +08:00  
> **Reviewed Repository HEAD**：`bd3bcad6aa3e55580cfd03943c4c52f3a31efd0a`  
> **Primary CR-3.1 Implementation**：`75744aaa89487aae09474b3569519a73f0efba24`  
> **Reviewer Baseline / Requirements**：`f7204473f1baefc8505f3bd2fb9a57fa40659510`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**CR-3.1 REOPENED**  
> **CR-3 / CR-3.1 已正确部分**：**PASS / FREEZE**  
> **Next Batch**：**CR-3.2 Final Snapshot Transaction + Verified Read Boundary + Policy Enforcement + URI/Manifest Seal Closure**  
> **ADR-023**：**PROPOSED / NOT ACCEPTED**  
> **CR-4**：**BLOCKED_BY_CR-3.2**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-3.1 已经正确关闭上一轮绝大多数 correctness blocker，尤其 requested-domain identity、future-only PIT completeness、anchored availability evidence、identity policy binding、full semantic replay seal 与 recoverable commit 都已具备正式实现与对抗测试。本轮不推倒 CR-3 主体，也不重开 CR-2.x。

正式确认并冻结：

```text
PASS / FREEZE  RequestedDomainSet：去重/排序 exact set 进入 run identity
PASS / FREEZE  不同 requested domain set -> 不同 canonical run
PASS / FREEZE  replay 返回 sealed requested domains
PASS / FREEZE  future-only candidate -> REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF BLOCK
PASS / FREEZE  PIT filter 仍严格先于 source selection
PASS / FREEZE  CanonicalInputSnapshot 后续单一派生：run identity / candidates / manifest / ledger 不再重复 broad query
PASS / FREEZE  Raw received_at：current meta hash == normalization sealed hash == Raw Anchor hash 后才可使用
PASS / FREEZE  raw availability identity cross-binding（provider/dataset/request/endpoint/surface/operation）
PASS / FREEZE  identity_dataset_hash 统一绑定 master input set + bridge policy version/hash
PASS / FREEZE  SourcePolicy hash 改为 asdict + canonical JSON，全部 dataclass 字段进入 hash
PASS / FREEZE  identity_missing_max 按 domain policy 执行
PASS / FREEZE  limit_price identity reconstruction 路径已补齐
PASS / FREEZE  selected / decisions / findings semantic replay seals
PASS / FREEZE  artifact schema / row_count / content hash replay 重验
PASS / FREEZE  findings parquet <-> DB finding exact-set cross-binding
PASS / FREEZE  CR-2 source closure + anchored availability 在 replay 时重验
PASS / FREEZE  findings correctness artifact 移除 wall-clock；DB failure 可 exact retry
PASS / FREEZE  migration 019 additive，不修改 018
PASS / FREEZE  P1：identity finding domain / naive datetime / domain count correction
PASS / FREEZE  current HEAD CI 三平台 green
```

但 CR-3.1 对“snapshot”的实现只解决了 **snapshot 构造完成以后不再 broad re-query**，没有满足上一轮明确要求的 **“BEGIN / snapshot boundary 在任何 authoritative broad read 之前”**；同时 CR-2 physical artifacts 仍存在“先 closure verify、后重新裸读”的 first-run TOCTOU。另有 SourcePolicy runtime enforcement 与 URI/provenance full-seal 两个小而关键的边界未闭合。

正式状态：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4   VERIFIED / CLOSED / FREEZE
CR-3                              DONE / REOPENED（主体 FREEZE）
CR-3.1                            DONE / REOPENED（多数 P0 已关闭）
CR-3.2                            START / ACTIVE NEXT
ADR-023                           PROPOSED / REVIEWER NOT ACCEPTED
CR-4                              BLOCKED_BY_CR-3.2
Production P0-M-1B                BLOCKED independently
```

除本文件列出的 CR-3.2 边界外，不得扩张 CR-3，不得重写已经通过的 AvailabilityPolicy / SourcePolicy / IdentityBridge / selection / reconciliation 主架构。

---

# 1. P0-01：CanonicalInputSnapshot 构造本身没有 transaction snapshot

## 1.1 当前实现进步

当前 `run()` 已改为：

```text
requested domain set
 -> _build_snapshot()
 -> snapshot.run_identity()
 -> candidate build
 -> artifact
 -> ledger
```

后续不再调用旧版 `_input_set_hash()` / `_identity_dataset_hash()` 做 moving broad query，这一方向正确并冻结。

## 1.2 当前仍未满足上一轮明确契约

上一轮 CR-3.1 §3.2 明确要求：

```text
1. BEGIN / snapshot boundary 在任何 authoritative broad read 之前；
2. broad source/master run query 只用于构造 snapshot；
3. 后续全部从 snapshot 派生。
```

当前 `_build_snapshot()` 仍是多次独立 SELECT：

```text
query domain A SUCCESS runs
 -> verify A
query domain B SUCCESS runs
 -> verify B
...
query security_master SUCCESS runs
 -> read master
```

没有 `BEGIN TRANSACTION` / DuckDB MVCC snapshot boundary。

因此若另一个 writer 在 `_build_snapshot()` 内部查询之间提交新的 normalization SUCCESS run，当前 snapshot 仍可能是多个数据库时刻拼接出的集合。

现有 `test_mid_run_source_insertion_current_run_exact` 的注入点是：

```text
original _build_snapshot() 已经完整返回 S1
 -> 再插入 S2
 -> return S1
```

它只证明“snapshot 完成以后 S2 不会泄漏”，没有证明“snapshot 构造过程中各 broad reads 来自同一个 DB snapshot”。

## 1.3 CR-3.2 Required Closure

必须在**第一个 authoritative broad SELECT 之前**建立数据库 snapshot boundary。

推荐两种实现之一：

### 方案 A：短 read transaction 构造 snapshot

```text
BEGIN TRANSACTION
 -> resolve requested domain source run exact rows
 -> resolve security_master run exact rows
 -> resolve ledger-side identities needed by snapshot
 -> build immutable typed DB snapshot
COMMIT read transaction
```

之后不得 broad query 当前 SUCCESS run 全集。

### 方案 B：保持同一 transaction 到 canonical ledger commit

若 DuckDB 单写者模型与当前 runtime 允许，可以在同一 transaction snapshot 上继续工作并最终提交 ledger；但不得引入长事务导致 CR-2 writer 被无必要阻塞。优先方案 A + verified physical read snapshot（见 P0-02）。

### 必测：真实 transaction race

不能只 monkeypatch “snapshot 返回以后”插入。至少增加一个 file-backed DuckDB 双 connection / 可重复的 transaction test：

```text
conn A BEGIN
conn A query first source subset
conn B insert + COMMIT new normalization run S2
conn A query remaining source/master subsets
=> conn A snapshot 仍只能看到 BEGIN 时的 S1 world

next invocation / next transaction
=> sees S2 -> new canonical identity
```

还需覆盖：

```text
source domain query A 后插入 source B
source query 后插入 security_master
同一 normalization run 同时 feed security_status + limit_price 时 snapshot exact
```

---

# 2. P0-02：CR-2 input 仍存在“先验证、后重新裸读”的 first-run TOCTOU

## 2.1 当前代码事实

`_build_snapshot()` 对 source run：

```text
verify_normalized_run(run_id)
_verify_anchored_availability(run)
 -> 认为 run verified
 -> snapshot 保存 run_row metadata + received_at
```

但真正构建候选时 `_build_candidates()` 调 `_read_output_rows()`，后者再次：

```text
SELECT normalized_manifest_uri FROM ledger
read manifest path
read parquet path
pl.read_parquet(...)
```

这些是 snapshot 之后的重新读取，并没有把**这次实际读取的 manifest/parquet bytes** 与 snapshot 中刚刚验证过的 CR-2 seal 再绑定。

security_master 也存在类似 verify -> later read 的微小窗口。

因此存在 first-run TOCTOU：

```text
CR-2 closure verify PASS on bytes H1
 -> snapshot metadata resolved
 -> H1 manifest/parquet 被替换为 H2
 -> _read_output_rows() 读取 H2
 -> canonical output 基于 H2
 -> current first invocation 可能返回 SUCCESS
```

未来 replay 会发现源被破坏并 DAMAGED，但**第一次调用已经可能把未验证 H2 当成 Canonical truth 返回给上层**，不能接受。

## 2.2 CR-3.2 Required Closure：Verified Physical Read Snapshot

CanonicalInputSnapshot 不应只冻结 DB ledger rows；还必须冻结“本次真正消费的数据 bytes/semantic rows”。

建议建立 read-only helper（命名可调整）：

```text
VerifiedNormalizedInput
  run seal / run identity
  manifest exact bytes/hash
  selected output_name
  output exact uri
  output content_hash/schema_hash/row_count
  exact parsed rows OR immutable in-memory frame/records
  anchored received_at binding
```

正确顺序必须是：

```text
resolve exact CR-2 run
 -> lexical-first resolve CR-2 manifest/output logical URI
 -> read exact bytes ONCE
 -> hash/schema/row_count/semantic vs CR-2 seal
 -> parse those SAME verified bytes
 -> freeze rows in CanonicalInputSnapshot
 -> candidate builder ONLY consumes snapshot rows
```

禁止：

```text
verify path now
later reopen current path and trust whatever bytes are there
```

identity master 同样必须从 exact verified bytes/rows进入 snapshot。

可再加一次 commit 前 verify-only source closure 作为 defense-in-depth；但 correctness 核心是**candidate 使用的就是已 hash-verified 的那一份 bytes**，不能依赖“读之前/读之后某时刻文件碰巧正确”。

### 必测

至少：

```text
verify H1 -> before candidate build swap output to H2 -> current run must never consume H2
verify H1 -> swap manifest uri/content binding -> current run BLOCK
verify H1 -> swap security_master output -> identity bridge must not consume H2
snapshot freezes H1 rows -> later file tamper cannot change current in-memory candidate values
persistent tamper before final closure -> run cannot be healthy
```

---

# 3. P0-03：SourcePolicy 仍有“进入 hash 但 runtime 不真正执行”的字段

## 3.1 已通过部分

`source_policy_hash()` 已改为 `dataclasses.asdict + canonical JSON`，所有字段进入 hash；`priority_providers`、`identity_missing_max` 已被实际使用；fallback / partial 若声明非当前支持值会 fail loudly。这些冻结。

## 3.2 剩余问题

当前 `_assert_policy_honestly_consumed()` 只显式拒绝：

```text
allowed_fallback_providers != empty
partial_run_allowed == True
```

但当前 v1 还有 correctness 字段：

```text
reconciliation = SINGLE_SOURCE_EXACT
tolerance_rule_id = exact-v1
tolerance_rule_version = 1
conflict_action = BLOCK
required_evidence_class = PROVIDER_NORMALIZED_VERIFIED
```

实际 runtime 的行为仍是硬编码：

- `_payload_equal()` 永远 exact；
- SOURCE_CONFLICT finding 永远 `blocking=True`；
- `required_evidence_class` 主要写入 manifest，没有作为 eligibility runtime assertion；
- `reconciliation` 不参与 dispatch/assertion。

因此若未来只把 policy 改成：

```text
conflict_action = ALLOW
reconciliation = TOLERANT
required_evidence_class = OTHER_CLASS
```

run identity/hash 确实会变化，但 runtime 仍继续执行旧的 EXACT/BLOCK/CR-2-verified 行为。此时 policy 只是“被记录”，没有成为真正 machine truth。

## 3.3 CR-3.2 Required Closure

当前 v1 不需要提前实现复杂 fallback/tolerance；只要把支持范围 machine-enforced：

```text
reconciliation must == SINGLE_SOURCE_EXACT
conflict_action must == BLOCK
tolerance_rule_id/version must == exact-v1 / 1
required_evidence_class must == PROVIDER_NORMALIZED_VERIFIED
allowed_fallback_providers must == ()
partial_run_allowed must == False
```

不支持值 -> CanonicalRunnerError / policy unsupported，**不得用旧算法继续跑**。

未来需要 tolerance/fallback 时：

```text
new policy value
+ corresponding runtime dispatcher/implementation
+ version change
+ adversarial tests
```

一起进入，不允许只改 policy dataclass。

所有 canonical row / manifest provenance 应使用 snapshot 已冻结的 policy identity，不要在 snapshot 后重新调用 live module globals 作为 correctness truth。

### 必测

```text
conflict_action=ALLOW without implementation -> hard fail
reconciliation!=SINGLE_SOURCE_EXACT -> hard fail
tolerance id/version unsupported -> hard fail
required_evidence_class!=PROVIDER_NORMALIZED_VERIFIED -> hard fail
current v1 exact policy -> existing CR-3 selection regression green
```

---

# 4. P0-04：Canonical replay 的 URI confinement 与剩余 manifest provenance seal 未闭合

## 4.1 URI lexical-first 问题

当前 `_verify_closure()`：

```text
manifest_path = normalized_root / ledger.manifest_uri
 -> 先访问
```

artifact：

```text
if manifest artifact uri != deterministic expected:
    append problem
path = normalized_root / manifest artifact uri
 -> 仍继续访问这个 uri
```

因此“检测到 uri 不正确”发生在**路径访问之前没有 fail/validate**；`../`、Windows drive/backslash、alias path 等不应进入任何 filesystem access。

项目已有冻结的统一逻辑 URI primitive：

```text
validate_logical_uri
physical_from_logical_uri
```

Canonical 必须复用，不得重新发明路径规则。

同时 ledger `manifest_uri` 必须先 exact 比较 system-derived expected manifest URI，再 lexical-first resolve；artifact URI 必须先 exact expected + `validate_logical_uri`，再访问 physical file。

### 必测

```text
ledger manifest_uri = ../../outside.json -> BLOCK before access
artifact uri = ../outside.parquet -> BLOCK before access
Windows drive / backslash -> BLOCK
alias a//b / a/./b -> BLOCK
valid deterministic URI -> PASS Win/Linux
```

## 4.2 剩余 manifest correctness 字段“写了但 replay 未比较”

CR-3.1 已把核心 hash / semantic seals补上，但 manifest 还包含：

```text
identity_master_input_set_hash
identity_bridge_policy_version
identity_bridge_policy_hash
required_evidence_classes
```

当前 `_verify_closure()` 没有逐项比较这些字段与 current snapshot / current policy derived truth。

虽然 `identity_dataset_hash` / `source_policy_hash` 间接包含大部分语义，这些显式字段仍是 manifest 的 correctness/audit provenance；允许 rebind 后与真实 policy 不一致，会形成“healthy replay 但审计 manifest 撒谎”。

CR-3.2 要求：凡 manifest 声明为 correctness provenance 的字段，要么：

1. 在 replay 中 exact compare current derived truth；或
2. 从 manifest 删除并只保留一个 authoritative sealed representation。

不要保留“写入但没人校验”的 correctness 字段。

### 必测

```text
manifest identity_master_input_set_hash rebind + manifest/ledger rehash -> DAMAGED
identity_bridge_policy_version/hash rebind -> DAMAGED
required_evidence_classes rebind -> DAMAGED
```

---

# 5. CR-3.1 已通过项：不得在 CR-3.2 重开

以下本轮正式接受为正确方向/实现，CR-3.2 只做边界收口：

## 5.1 Requested domain identity —— PASS / FREEZE

- deduped + sorted domain set；
- domain hash 进入 run identity；
- ledger/manifest seal；
- replay domains 来自 ledger；
- order independence / duplicate dedupe。

## 5.2 Availability completeness —— PASS / FREEZE

- no run -> REQUIRED_DOMAIN_MISSING；
- run exists but zero PIT-available candidate -> REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF；
- EXCLUDED_FUTURE decision retained；
- early + future -> early only。

## 5.3 Anchored availability evidence —— PASS / FREEZE

- raw meta current hash == normalized sealed raw_evidence_hash；
- current hash == Raw Anchor evidence_hash；
- provider/dataset/request/endpoint/surface/operation identity cross-binding；
- received_at tamper before first canonical -> BLOCK；
- post-success tamper -> replay DAMAGED。

## 5.4 Identity binding —— PASS / FREEZE

- master_input_set_hash + bridge policy version/hash -> one identity_dataset_hash；
- run identity/manifest/ledger 使用同一语义；
- limit_price identity path 已补齐；
- per-domain identity missing threshold/finding。

## 5.5 Canonical semantic replay —— PASS / FREEZE

- selected semantic hash；
- decisions semantic hash；
- finding DB/parquet exact-set seal；
- schema/content/rowcount；
- artifact exact set与 deterministic uri设计（仅补 lexical-first access order）；
- sealed CR-2 source replay revalidation。

## 5.6 Recoverable commit —— PASS / FREEZE

- correctness artifacts 无 retry-time wall clock；
- finding_id uuid5 deterministic；
- DB `created_at` 仅审计 metadata；
- DB failure rollback + exact retry file no-op + ledger commit。

---

# 6. CR-3.2 Mandatory Tests

在现有 1066 tests 基础上至少新增：

1. DuckDB transaction snapshot：source query 中途另一 connection commit S2，current snapshot仍是 S1；
2. master query 中途另一 connection commit master S2，current identity bridge仍是 begin-snapshot；
3. verified CR-2 output H1 在 verify 与 candidate read 之间替换 H2 -> H2 不可被消费；
4. verified CR-2 manifest 在 verify 与 read 之间重绑 -> BLOCK；
5. security_master verify/read TOCTOU -> BLOCK / frozen H1；
6. unsupported reconciliation -> hard fail；
7. unsupported conflict_action -> hard fail；
8. unsupported tolerance id/version -> hard fail；
9. unsupported required_evidence_class -> hard fail；
10. manifest URI `..` traversal -> pre-access BLOCK；
11. artifact URI `..` traversal -> pre-access BLOCK；
12. Windows drive/backslash/alias logical URI -> pre-access BLOCK；
13. manifest identity_master_input_set_hash rebind -> DAMAGED；
14. manifest identity bridge policy version/hash rebind -> DAMAGED；
15. manifest required_evidence_classes rebind -> DAMAGED；
16. all existing CR-3.1 requested-domain / future-only / anchored PIT / semantic replay / retry tests green；
17. all CR-2/B2/B1/A3/A2/CR-1 frozen regressions green；
18. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 CI all green。

---

# 7. CR-3.2 Exit Gate

全部满足才允许：

```text
CR-3 / CR-3.1 / CR-3.2 VERIFIED / CLOSED / FREEZE
ADR-023 ACCEPTED
CR-4 SnapshotBuilder + DuckDB ReadModel START
```

Exit Gate：

- BEGIN / MVCC snapshot 在任何 authoritative broad read 之前；
- snapshot 内所有 source/master ledger row 来自同一 DB snapshot；
- candidate/master rows 来自与 CR-2 seal 同一次 exact verified bytes；
- snapshot 后无 moving broad query / unverified physical re-read；
- current v1 SourcePolicy semantic fields全部 machine-enforced；
- unsupported policy value fail loudly；
- canonical manifest / artifact logical URI lexical-first confinement；
- remaining manifest correctness provenance全部 full-seal consume 或删除冗余；
- CR-3.1 已通过机制无 regression；
- migration chain green；
- full CI three legs green；
- governance同步。

通过后 Reviewer 不再继续制造 CR-3.x；除非发现新的**可复现 correctness regression**，应正式进入 CR-4。

---

# 8. Governance 要求

下一 developer commit 必须：

- `docs/DEVLOG.md` append-only；
- `docs/project/DEVELOPMENT_MANAGEMENT.md` 同步：CR-3.1 REOPENED -> CR-3.2 ACTIVE；
- ADR-023 保持 PROPOSED，新增 CR-3.2 Amendment，不得自称 ACCEPTED；
- migration 若需要新字段用 020+，不得修改 018/019；若仅 runtime closure 不需 schema，不要为了编号而造 migration；
- 本文件末尾追加 implementation mapping + exact SHA + CI run；
- CR-4 继续 BLOCKED_BY_CR-3.2；
- Production P0-M-1B 独立 BLOCKED，不得混淆为 CR-3 blocker。

---

# 9. Owner View

CR-3.1 已经把“请求什么数据、历史时点是否真的可用、时间证据有没有被改、结果文件有没有被替换、数据库失败能不能恢复”这些大问题基本补齐。

CR-3.2 只剩最后一个信任边界：

```text
不是“我刚才检查过这批数据”就算 snapshot，
而是要证明：

① 这些数据库记录来自同一个数据库时刻；
② 我真正拿来计算的文件 bytes，就是刚才验过 hash 的那一份；
③ policy 写的规则和 runtime 真正执行的规则一致；
④ manifest 里的每个 correctness 声明都能重新证明；
⑤ 任何文件路径在访问前就必须先通过逻辑 URI confinement。
```

这轮通过后，Provider-Normalized -> Canonical 的可信闭环才完整，随后应直接进入 CR-4 SnapshotBuilder + DuckDB ReadModel。