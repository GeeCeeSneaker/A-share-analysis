# A-share-analysis：CR-3.1 复审与 CR-3.2 最终 Transactional Snapshot / PIT Identity / Policy Execution / Replay Health Seal 收口要求

> **Review Date**：2026-09-01 21:08 +08:00  
> **Reviewed Repository HEAD**：`bd3bcad6aa3e55580cfd03943c4c52f3a31efd0a`  
> **Primary CR-3.1 Implementation**：`75744aaa89487aae09474b3569519a73f0efba24`  
> **Reviewer Baseline / Requirements**：`f7204473f1baefc8505f3bd2fb9a57fa40659510`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-3.1 已正确部分**：**大部分 PASS / FREEZE**  
> **Next Batch**：**CR-3.2 Final Transactional Canonical Snapshot + PIT Identity Master + Honest Policy Execution + Replay Health/Full Seal Closure**  
> **ADR-023**：**PROPOSED / NOT ACCEPTED**  
> **CR-4**：**BLOCKED_BY_CR-3.2**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-3.1 对上一轮 8 个 P0 做了实质修复。以下机制本轮正式 **PASS / FREEZE**，CR-3.2 不得推倒重写：

```text
PASS / FREEZE  RequestedDomainSet 去重/排序并进入 canonical run identity
PASS / FREEZE  requested domain exact set/hash 持久化到 ledger + manifest
PASS / FREEZE  future-only market source 不再 false SUCCESS
PASS / FREEZE  REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF typed blocking finding
PASS / FREEZE  source raw received_at 读取前做 current bytes == CR-2 sealed hash == raw anchor hash
PASS / FREEZE  source raw provider/dataset/request/endpoint/surface/operation_id cross-binding 方向
PASS / FREEZE  identity_dataset_hash 统一为 master set + bridge policy version/hash
PASS / FREEZE  source_policy_hash 改为全 dataclass canonical serialization
PASS / FREEZE  selected / decisions / findings 三类 deterministic artifacts
PASS / FREEZE  selected_semantic_hash / decision_set_hash / finding_set_hash
PASS / FREEZE  artifact exact-set、deterministic URI（selected/decisions/findings）、content/schema/row_count 重验主体
PASS / FREEZE  findings parquet <-> DB exact-set cross-binding
PASS / FREEZE  replay 重验 sealed CR-2 source + anchored raw evidence 的主体机制
PASS / FREEZE  findings correctness bytes 去 wall-clock；DB failure exact retry 可恢复
PASS / FREEZE  identity finding 按真实 domain 记录
PASS / FREEZE  naive datetime fail closed / naive string fixed-UTC contract
PASS / FREEZE  migration 019 additive；018 未改写
PASS / FREEZE  current HEAD full CI Windows 3.12 / Windows 3.14 / Ubuntu 3.14 green
```

但是继续按“同一次 canonical run 是否真的只代表一个唯一 as-of 世界”向下审查后，发现 **5 个 P0 correctness blockers**。其中 P0-01 / P0-02 会直接破坏 PIT/authoritative-snapshot 语义，P0-03 会造成 policy 声明与真实执行不一致，P0-04/P0-05 会造成 replay seal/状态转换不完整。

正式状态：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4   VERIFIED / CLOSED / FREEZE
CR-3                              DONE / REOPENED
CR-3.1                            DONE / REOPENED（大量机制 PASS / FREEZE）
CR-3.2                            START / ACTIVE NEXT
ADR-023                           PROPOSED
CR-4                              BLOCKED_BY_CR-3.2
Production P0-M-1B                BLOCKED independently
```

不重开 CR-2.x / R4-B2/B1/A3/A2/CR-1，除非 CR-3.2 引入可复现 regression。

---

# 1. P0-01：`CanonicalInputSnapshot` 还没有真正的 DB snapshot boundary，且验证后重新读取“当前 DB / 当前文件”

## 1.1 当前事实

CR-3.1 新增了 `CanonicalInputSnapshot`，方向正确；但 `_build_snapshot()` 在任何 authoritative broad read 前没有 `BEGIN TRANSACTION` / MVCC snapshot boundary，也没有等价的一条 SQL 一次性冻结所有权威 DB 输入。

当前顺序仍可能是：

```text
query domain A SUCCESS runs
 -> verify A
query domain B SUCCESS runs
 -> verify B
query security_master SUCCESS runs
 -> verify master
```

若另一个 connection 在 A/B/master 查询之间插入新 normalization run，则同一个 `CanonicalInputSnapshot` 仍可能混入两个时间点的 DB 世界。

现有 race test 的 injection 发生在：

```text
snapshot = original(_build_snapshot(...))
INSERT new normalization run
return snapshot
```

它只能证明“snapshot 构建完成后插入不会污染”，没有证明“snapshot 构建过程中插入不会污染”。这没有满足上一轮明确要求：

```text
BEGIN / snapshot boundary 在任何 authoritative broad read 之前
```

## 1.2 验证后又重开 TOCTOU

`_read_output_rows(run_id, output_name)` 会：

```text
重新 SELECT current normalized_manifest_uri FROM meta_provider_normalization_run
 -> current manifest path
 -> current parquet
```

它没有直接消费 snapshot 中已经验证过的 exact manifest/output bytes。

因此可以出现：

```text
snapshot 验证 run A / manifest M1
 -> DB row 的 normalized_manifest_uri 被 UPDATE 到 M2
 -> candidate builder 重新查 current DB
 -> 实际读取 M2
```

或者：

```text
verify_normalized_run() 验证 parquet bytes P1
 -> 文件在 verify 后、read 前被替换 P2
 -> _read_output_rows() 直接读取 P2
```

这会形成“run identity / input seal = S1，但实际 consumed rows = S2”的经典 TOCTOU。

## 1.3 `frozen=True` 不是深层 immutable

当前 snapshot 内部仍包含：

```text
dict[str, tuple[dict, ...]]
tuple[dict, ...]
```

且 `findings = list(snapshot.prefindings)` 只是浅拷贝，后续 `_write_artifacts()` 会给同一 finding dict 增加 finding_id / canonical_run_id。也就是说 snapshot 内容在创建后实际仍可被修改。

## 1.4 CR-3.2 Required Closure

必须建立真正的 **Transactional / Materialized Canonical Input Snapshot**：

推荐方案：

```text
BEGIN read transaction / MVCC snapshot
  -> 一次性发现 requested source runs + identity master runs + raw anchors
  -> 对 exact runs 做 closure/anchor verify
  -> 对实际要消费的 normalized output 读取 EXACT SEALED BYTES
     （一次 read bytes -> hash/schema/row_count verify -> parse those same bytes）
  -> 物化成 typed immutable snapshot records / rows
COMMIT read snapshot

后续：
run identity / bridge / candidates / selection / manifest / ledger
全部只消费 materialized snapshot，不再 broad query，不再 current-uri requery
```

也可保持一个 transaction 到 canonical ledger commit，但必须证明 DB snapshot + file-read identity 同一世界；禁止 nested transaction 破坏语义。

至少要求：

- snapshot boundary 在第一个 authoritative broad query 前；
- same underlying surface 不因多个 requested domain 被不同时间重复发现；
- source/master run 使用 frozen typed record，不用 mutable dict truth；
- output rows 从已经验证的 exact bytes 派生；
- candidate builder 不重新查询 current normalization ledger path；
- manifest/ledger/input_set_hash 都只来自同一个 snapshot；
- 文件在 snapshot 后被修改只影响下一 invocation/replay verify，不污染当前已物化 run。

---

# 2. P0-02：Identity Master 仍可泄露 future knowledge，且 first-run / replay anchor 规则不对称

## 2.1 当前 PIT look-ahead

普通 market source 已经执行：

```text
anchored received_at
 -> available_at <= as_of
 -> only then selection
```

但是 `security_master` identity runs 当前：

```text
all SUCCESS master runs
 -> verify_normalized_run only
 -> read all master rows
 -> IdentityBridge
```

没有：

```text
_verify_anchored_availability(master run)
master received_at <= as_of
```

`IdentityBridge` 只执行：

```text
latest list_date <= trade_date
```

所以：

```text
行情在 T0 已知
某 security_master/relist identity 在 T1 才被系统观察到
T0 < as_of < T1
```

当前 canonical 仍可能使用 T1 的 master record 改写 T0 时点的 security_id / relist identity，属于 PIT future leakage。

## 2.2 first-run 与 replay 规则自相矛盾

第一次 `_build_snapshot()`：

```text
source run          -> verify_normalized_run + verify raw anchor
identity master run -> verify_normalized_run ONLY
```

但 replay `_verify_closure()` 对 manifest 中所有 `input_normalized_runs`（包括 `identity_master`）统一调用 `_verify_run_intact()`，其中包含 raw anchor verification。

因此存在：

```text
master normalization run 完整
但 master raw anchor 被删除

first canonical -> 仍可能使用 master rows -> SUCCESS
立即 second canonical -> replay 检查 master anchor -> DAMAGED
```

系统不能产生一份“刚创建就无法通过自己的 replay verifier”的 SUCCESS run。

## 2.3 CR-3.2 Required Closure

Identity master 必须有明确 typed PIT policy。Reviewer 要求最低为：

```text
master raw exact bytes + anchor cross-binding valid
received_at <= as_of 才可进入 IdentityBridge
```

未来 master 可留在 `discovered input set` / decision evidence 中，但不能影响当前 as-of 的 identity resolution。

若架构希望把 security_master 定义为“非 PIT、可回溯静态 reference dimension”，必须先用 ADR 明确证明该语义不会产生历史 look-ahead；在当前 Frozen Baseline 的 PIT correctness 目标下，不允许默认这么假设。

建议增加 typed finding：

```text
IDENTITY_DATASET_UNAVAILABLE_AT_ASOF
IDENTITY_EVIDENCE_INVALID
```

或等价分类，关键是不能用未来 identity master 静默解析历史 rows。

---

# 3. P0-03：SourcePolicy 做到了“hash 全字段”，但没有做到“runtime 诚实消费全字段”

## 3.1 当前事实

`source_policy_hash()` 已改为 `dataclasses.asdict + canonical JSON`，这一项 PASS。

但 runtime `_assert_policy_honestly_consumed()` 目前只显式拒绝：

```text
allowed_fallback_providers != empty
partial_run_allowed == true
```

以下字段虽进入 hash，却没有形成等价 runtime contract：

```text
required_evidence_class
reconciliation
conflict_action
tolerance_rule_id
tolerance_rule_version
```

当前实际执行固定为：

```text
verify_normalized_run()
EXACT payload equality
SOURCE_CONFLICT -> blocking=True
```

例如把 policy 的：

```text
required_evidence_class = OTHER_CLASS
```

现有测试只证明 hash/run identity 改变；runtime 仍会继续消费 `PROVIDER_NORMALIZED_VERIFIED` 的 CR-2 run，而不是拒绝自己不支持的 evidence class。

同理，未来把 reconciliation/tolerance/conflict_action 改成 runtime 未实现的值，只改 hash 不改执行，会出现：

```text
policy identity 表示规则 B
实际程序仍执行规则 A
```

## 3.2 Required Closure

在 v1 尚未实现多种行为时，最安全的是 **explicit supported-value guard**：

```text
required_evidence_class == PROVIDER_NORMALIZED_VERIFIED
reconciliation == SINGLE_SOURCE_EXACT
tolerance_rule_id/version == exact-v1 / 1
conflict_action == BLOCK
allowed_fallback_providers == ()
partial_run_allowed == False
```

任何声明超出 runtime capability -> fail closed / governance error，不能只生成新 hash 后继续旧行为。

未来新增行为时，必须：

```text
policy field new value
+ runtime implementation
+ decision/finding semantics
+ tests
+ policy version/hash
```

同一批进入。

---

# 4. P0-04：Canonical full seal 仍有“写入 manifest 但 replay 不消费”的 provenance 字段；上游 CR-2 exact seal 未完整 snapshot 化

## 4.1 manifest 显式字段未 full consume

manifest 当前写入：

```text
identity_master_input_set_hash
identity_bridge_policy_version
identity_bridge_policy_hash
required_evidence_classes
```

但 `_verify_closure()` 的 ledger<->manifest field comparison 没有逐项消费这些字段。

因此攻击/误改路径仍成立：

```text
修改 manifest.identity_bridge_policy_version
或 identity_bridge_policy_hash
或 identity_master_input_set_hash
或 required_evidence_classes
 -> 重算 manifest bytes hash
 -> UPDATE ledger.manifest_hash
 -> 现有 verifier 可不发现 manifest 本身已自相矛盾
```

`identity_dataset_hash` / `source_policy_hash` 的合成值保持正确并不能替代“manifest 显式声明字段必须真实”的 full-field seal。

## 4.2 snapshot input entry 没有封住完整 CR-2 seal

CR3-P0-01 原工作要求明确要求 canonical input 至少绑定：

```text
normalization_contract_version
mapper_code_hash
normalized_manifest_uri/hash
normalized_output_set_hash
normalized_semantic_hash
status
```

当前 `_input_entry()` 只持久化部分 identity（run/provider/surface/dataset/endpoint/raw identity/manifest hash），上述若干 CR-2 frozen seal字段只在 `verify_normalized_run()` 中瞬时检查，没有进入 CanonicalInputSnapshot / canonical manifest exact input seal。

CR-3.2 应直接 snapshot typed `NormalizationRunSeal`（或等价完整字段），而不是自建一个较弱的 subset。

## 4.3 manifest anchor URI 本身也要 deterministic verify

当前 verifier 对 selected/decisions/findings URI 有 deterministic recompute，但 ledger `manifest_uri` 本身没有与 expected base URI `/manifest.json` 比较。manifest anchor 也属于 run exact artifact closure，不允许复制到任意路径后只改 ledger URI/hash。

## 4.4 Required Closure

建立 typed `CanonicalRunSeal` / `CanonicalInputRunSeal`（命名可调整），做到：

```text
CURRENT snapshot
 == ledger typed seal
 == manifest typed seal
 == replay-time physical recompute
```

显式覆盖：

- requested domains JSON/hash；
- exact full CR-2 upstream seal per input run；
- identity master input set hash；
- bridge policy version/hash；
- identity_dataset_hash；
- availability/source/tolerance policy version/hash；
- required_evidence_classes exact map/hash；
- code fingerprint；
- status/counts；
- selected/decision/finding semantic seals；
- artifact exact set + deterministic manifest/artifact URI + content/schema/row_count；
- idempotency key。

若新增 ledger 字段，用 migration 020+；不得修改 018/019。

---

# 5. P0-05：Input verification/eligibility state 会改变 canonical outcome，但不参与 replay 状态转换，修复后可能永久 replay 旧 BLOCKED

## 5.1 当前问题

`CanonicalInputSnapshot` 虽然保存 `prefindings`，但 run identity 只包含：

```text
requested set
input entries
identity hash
as_of
policies
code fingerprint
```

并不包含“这些 input 当前验证是 healthy / closure-failed / anchor-missing / anchor-mismatch”等 deterministic verification state。

可以出现：

```text
source run identity = S1
raw anchor 临时缺失
 -> canonical run R = BLOCKED（AVAILABILITY_EVIDENCE_INVALID）

随后通过 governed exact repair 恢复同一个 anchor
source run identity 仍是 S1
 -> current snapshot 已 healthy
 -> run_id 仍是 R
 -> prior 命中
 -> verifier 只检查旧 BLOCKED artifacts 自洽 + 当前 source 已 intact
 -> 可能直接 replay 旧 BLOCKED
```

即：上游真实修复后，Canonical 仍可能永久被旧失败结果锁死。

反方向又必须继续保持上一轮的安全目标：

```text
历史 SUCCESS
 -> upstream 后来损坏
 -> 不能通过“verification state change”偷偷 mint 一个新的 healthy run
 -> 必须 fail closed / DAMAGED
```

所以不能简单把 health bit 塞进 run id 后就结束。

## 5.2 Required Closure

CR-3.2 必须定义明确的 **base identity + verification/eligibility state transition** 语义（实现方式可选）：

- 当前 health state 与历史 run 相同 -> 正常 exact replay；
- 历史 SUCCESS + 当前 input 退化/damaged -> DAMAGED / replay refused，不能 mint healthy replacement；
- 历史 BLOCKED 仅因可恢复 closure/anchor 问题 + 当前已 exact repair -> 不得 replay stale BLOCKED；应进入新的 deterministic recovery run/identity，或明确的 supersession mechanism；
- repair 不得覆盖/删除历史 BLOCKED evidence；
- 所有 transition 都必须可审计、可测试、无 caller override。

建议定义 typed：

```text
CanonicalInputVerificationSeal
canonical_base_identity
verification_state_hash
```

但 Reviewer 不强制具体命名。

---

# 6. P1 / 结构性加固（本批建议一起完成）

## P1-01 Deep immutable snapshot

`@dataclass(frozen=True)` 不能包 mutable nested dict 作为 authoritative truth。建议 source/master/input entries 改 typed frozen records，payload rows 使用 immutable/canonical representation，避免 shallow-copy 后被 artifact writer修改。

## P1-02 Shared surface discovery 去重

`security_status` / `limit_price` 等可共享同一个 normalization surface。Snapshot discovery 应按 source surface/run exact set 一次解析，再投影给多个 domain；避免同一 underlying run 因 domain 循环重复 broad query/重复 entry。

## P1-03 `domains=[]` API 语义显式

当前 `domains=[]` 因 falsy 会等价 `None` -> 构建全部 supported domains。建议明确：

```text
None = all supported
empty collection = reject 或 exact empty（按产品决定）
```

不要由 Python truthiness 隐式决定。

---

# 7. CR-3.2 Mandatory Adversarial Test Matrix

除 CR-3.1 41 项新增测试、CR-3 原 40 项和所有 CR-2/R4 frozen regressions外，至少增加：

```text
01 DB snapshot boundary：domain A query 后、domain B query 前由第二 connection INSERT S2
   -> current run 仍严格 S1
02 master query 前 INSERT new master run -> current snapshot 不可见
03 next invocation 才看到 S2 -> new identity
04 snapshot verify M1 后 UPDATE normalization ledger manifest_uri=M2
   -> current run 不得消费 M2
05 verify output P1 后、candidate read 前 replace file P2
   -> current run只能消费已验证 P1，或 hard block；不得消费未经验证 P2
06 snapshot nested record mutation attempt不可改变 authoritative truth

07 future-only security_master received_at > as_of -> 不得进入 IdentityBridge
08 early master + future relist master -> historical selected security_id 保持 early truth
09 all identity master future-only -> identity-required domain BLOCKED
10 master raw anchor missing before FIRST canonical -> first run BLOCK，不得 SUCCESS
11 master raw meta/anchor mismatch before FIRST canonical -> BLOCK
12 first run成功后立即 replay，在无外部变化时必须同样通过（first/replay verifier parity）

13 required_evidence_class unsupported -> fail closed before canonical run
14 reconciliation unsupported -> fail closed
15 tolerance_rule_id/version unsupported -> fail closed
16 conflict_action unsupported -> fail closed
17 supported v1 policy values -> behavior unchanged

18 manifest identity_master_input_set_hash rebind + manifest/ledger outer rehash -> DAMAGED
19 manifest bridge policy version/hash rebind -> DAMAGED
20 manifest required_evidence_classes rebind -> DAMAGED
21 canonical manifest_uri rebind -> DAMAGED
22 upstream input entry full CR-2 seal field rebind -> DAMAGED / snapshot mismatch
23 full typed input seal exact equality across snapshot/manifest/replay

24 source anchor missing -> first canonical BLOCKED；governed exact repair -> next invocation不得 replay stale BLOCKED
25 source closure temporarily damaged -> BLOCKED；exact repair -> next invocation不得 replay stale BLOCKED
26 prior SUCCESS -> source/anchor damage -> DAMAGED，不能 mint replacement healthy run
27 repair/recovery preserves historical BLOCKED evidence（no overwrite/delete）

28 migration 020 from-zero（若 schema 变更）
29 migration 019->020 upgrade（若 schema 变更）
30 Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green
31 Ruff / format / Mypy / Spike / governance gates green
32 all CR-3.1 / CR-3 / CR-2.x / R4 frozen regressions green
```

测试 race 必须使用能真正发生在 `_build_snapshot()` 内部 broad reads 之间的 injection；“原 `_build_snapshot()` 已完整返回后再 insert”的测试不能替代 item 01/02。

---

# 8. CR-3.2 Scope Boundary

允许：

```text
CanonicalRunner / CanonicalInputSnapshot
read-only CR-2 verified-output helper（若用于 exact bytes materialization）
identity master PIT policy
SourcePolicy execution guard
canonical replay/full seal
migration 020+
ADR-023 Amendment B
governance / tests
```

不允许：

```text
SnapshotBuilder
DuckDB ReadModel rebuild
Feature / State
新增尚未验证 semantics 的 canonical domain
绕过 CR-2 frozen verifier 重做 mapper
```

CR-3.2 仍是 Canonical Runtime correctness closure，不是 CR-4。

---

# 9. CR-3.2 Exit Gate

全部通过才允许：

```text
CR-3 / CR-3.1 / CR-3.2 -> VERIFIED / CLOSED / FREEZE
ADR-023 -> ACCEPTED
CR-4 SnapshotBuilder + ReadModel -> START
```

Exit Gate：

```text
[ ] real DB snapshot boundary before first authoritative broad read
[ ] actual consumed normalized rows materialized from exact verified bytes
[ ] no post-snapshot current-ledger/current-path reread changes consumed truth
[ ] snapshot is deeply immutable or equivalently protected
[ ] identity master anchored evidence verified on first consume and replay
[ ] identity master obeys PIT as_of availability policy
[ ] future master cannot change historical identity truth
[ ] policy declaration and runtime behavior exact match / unsupported values fail closed
[ ] full manifest provenance fields are consumed, not display-only
[ ] upstream CR-2 full seal is snapshotted/bound
[ ] deterministic manifest URI is verified
[ ] current verification/eligibility state cannot replay stale BLOCKED after repair
[ ] prior SUCCESS degradation remains DAMAGED fail closed
[ ] recoverable repair preserves immutable history
[ ] CR-3.1 passed mechanisms remain frozen
[ ] no CR-4 logic leak
[ ] migration / CI / governance green
```

---

# 10. Governance / ADR / 管理总册要求

下一 developer commit 必须同步：

- `docs/DEVLOG.md`：append CR-3.2 correction，不改写历史；
- `docs/project/DEVELOPMENT_MANAGEMENT.md`：CR-3.1 REOPENED / CR-3.2 ACTIVE / CR-4 BLOCKED；
- ADR-023 保持 PROPOSED，并追加 **Amendment B**：
  - transactional/materialized snapshot；
  - identity-master PIT policy；
  - honest policy execution；
  - full manifest/input seal；
  - verification-state recovery semantics；
- ADR index 保持 ADR-023 PROPOSED；
- 风险/TD/change log 按总册现有规则同步。

状态必须写为：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4   CLOSED / VERIFIED / FREEZE
CR-3                              DONE / REOPENED
CR-3.1                            DONE / REOPENED（大部分机制 FREEZE）
CR-3.2                            ACTIVE / NEXT
ADR-023                           PROPOSED
CR-4                              BLOCKED_BY_CR-3.2
Production P0-M-1B                BLOCKED independently
```

---

# 11. 面向项目 Owner 的中文工程进度

## 11.1 本阶段一句话

CR-3.1 已经把“请求哪些数据、future-only 数据不能进入历史、原始 received_at 要验 anchor、Canonical 文件要做 semantic seal、失败后可重试”等大块补齐；现在剩下的是最后一层**同一次 Canonical 构建必须真的只看到一个输入世界，并且身份数据本身也不能使用未来知识，policy 写什么程序就必须执行什么，修复后的输入也不能被旧 BLOCKED 永久锁死。**

## 11.2 当前工程阶段图

```text
A股市场态势数据基座
│
├─ ① 原始数据证据层
│    ✅ CR-1 / R4-A2.x CLOSED / VERIFIED
│
├─ ② Provider 运行能力验证
│    ✅ R4-A3 / R4-B1 CLOSED / VERIFIED
│
├─ ③ 发布前数据安全
│    ✅ R4-B2.x CLOSED / VERIFIED
│
├─ ④ Raw -> Provider-Normalized + Quarantine
│    ✅ CR-2 / 2.1 / 2.2 / 2.3 / 2.4 CLOSED / VERIFIED
│
├─ ⑤ Provider-Normalized -> Canonical
│    🟡 CR-3 主体已完成
│    🟡 CR-3.1 大部分 correctness 已完成
│    🔧 CR-3.2 最终收口
│       ├─ 真正 DB snapshot，不混入半途新数据
│       ├─ 实际消费已验证的 exact bytes，不重新找 current path
│       ├─ security_master 也遵守 as-of，不能未来身份回填历史
│       ├─ policy 声明与程序执行完全一致
│       ├─ manifest/input full seal 全字段真正消费
│       └─ 上游修复后不 replay 旧 BLOCKED，历史 SUCCESS 退化仍 hard fail
│
├─ ⑥ Snapshot / ReadModel
│    ⏸ CR-4 等待 CR-3.2
│
└─ ⑦ 正式生产闭环
     ⛔ 正式账号 + Golden/Trading Rule 人工复核仍独立阻塞
```

## 11.3 关键指标（工程闭环口径，不是精确工时）

```text
Raw 可追溯 / 防篡改 / replay          ██████████  已闭环
Provider 接入/权限/精确接口            ██████████  已闭环
发布前安全/DQ                          ██████████  已闭环
Raw -> Provider-Normalized             ██████████  已闭环
Quarantine / no-sentinel / no-drop     ██████████  已闭环

Canonical requested-domain identity    ██████████  已闭环
Canonical source availability PIT      █████████░  source 已闭环，identity-master 待补
Canonical input snapshot consistency   ███████░░░  有 typed snapshot，但 DB/file TOCTOU 待收口
Canonical policy execution             ████████░░  hash 已完整，行为 guard 待收口
Canonical replay/full seal             █████████░  主体完成，显式字段/health transition 待补
Canonical DB-failure recovery          ██████████  已闭环

Snapshot / ReadModel                   ░░░░░░░░░░  尚未开始
正式生产可用                           ░░░░░░░░░░  后续 runtime + 正式账号/人工复核待完成
```

**老板视角**：CR-3.1 已经非常接近完成，当前不是“大功能没做”，而是还差几条会决定历史回测是否真的没有未来函数、同一次运行是否真的代表一个输入世界的底层正确性边界。把 CR-3.2 这批收口后，才适合把 Canonical 层冻结并进入 CR-4 Snapshot/ReadModel。

---

# 12. Implementation Mapping（开发方填写，2026-09-01）

> 本 Mapping 以本文件（21:08 完整版，含 P0-05 状态转换与 §7 32 项矩阵）为权威依据——其覆盖同日 21:01 版《SnapshotTransaction及VerifiedReadBoundary收口要求》的全部内容。

## §1 P0-01 Transactional Materialized Snapshot

| Requirement | Implementation | Tests |
|---|---|---|
| BEGIN 在第一个 broad SELECT 前 | `_build_snapshot`：`BEGIN TRANSACTION` 包裹全部 surface 发现与物化，`COMMIT` 收尾 | `TestTransactionalSnapshot::test_concurrent_insert_between_broad_reads_invisible`（第二 connection 在 domain 查询后、master 查询前真实 commit——file-backed DuckDB MVCC——current run 严格 S1） |
| same surface 不重复发现 | `_surface_plan`：per-surface union datasets 一次查询 | `test_concurrent_master_insert_between_broad_reads_invisible`（daily_bar 查询返回后注入 master run——snapshot 不可见） |
| mid-run 插入只影响下次 invocation | — | `test_next_invocation_sees_committed_insert`（新 identity 诚实发现） |
| 验证后不重读当前 DB path | `_materialize_outputs`：读 bytes → hash==manifest → parse 同一份；candidate builder 消费 `SnapshotRun.outputs` | `test_post_snapshot_ledger_uri_update_not_consumed`（snapshot 后 UPDATE manifest_uri=evil——current run 仍消费 M1 物化行） |
| verify 后文件替换不被消费 | — | `test_post_verify_file_replacement_not_consumed`（verify P1 后换 P2——close 值仍是物化 P1 的 10.5/20.5 非 777.0） |
| 深层 immutable | typed frozen dataclasses + tuple-frozen rows | `test_snapshot_deep_immutability`（frozen 赋值 raise；run() 结果不受 mutation attempt 影响） |

## §2 P0-02 Identity Master PIT

| Requirement | Implementation | Tests |
|---|---|---|
| master anchored evidence + received_at <= as_of | `_snapshot_run` 对 identity_master 同样执行 `_verify_anchored_availability` + `pit_available` 判定；`available_master_rows` 才进 bridge | `TestIdentityMasterPIT::test_future_master_never_resolves_historical_rows` |
| future master 不改历史 identity truth | future master 留 discovery evidence（`pit_available=false`） | `test_early_master_plus_future_relist_keeps_early_truth`（early master 唯一 available；relist 是 sealed evidence） |
| all-future master -> BLOCKED | `IDENTITY_DATASET_UNAVAILABLE_AT_ASOF` blocking | `test_all_masters_future_only_blocks` |
| master anchor missing/mismatch before FIRST -> BLOCK | `IDENTITY_EVIDENCE_INVALID` blocking | `test_master_anchor_missing_first_run_blocks` / `test_master_meta_mismatch_first_run_blocks` |
| first/replay verifier parity | replay 对全部 sealed input（含 master）执行 `_verify_sealed_input`（含 anchor） | `test_first_run_replay_parity`（成功后立即 replay 通过同一 verifier） |

## §3 P0-03 Honest Policy Execution

| Requirement | Implementation | Tests |
|---|---|---|
| required_evidence_class unsupported -> fail closed | `_assert_policy_honestly_executed` supported-value guard（run 之前） | `TestHonestPolicyExecution`（5 项 parametrize：evidence_class/reconciliation/tolerance_id/tolerance_version/conflict_action） |
| fallback/partial unsupported -> fail closed | 同上（继承 CR-3.1 行为） | `TestPolicyHashCompleteness::test_fallback_providers_change_new_run`（raise）+ CR-3.1 回归 |
| supported v1 values 行为不变 | — | `test_supported_v1_values_behavior_unchanged` |
| domains=[] 显式语义 | `run()`：None=all；empty reject | `test_empty_domains_rejected` |

## §4 P0-04 Full Seal

| Requirement | Implementation | Tests |
|---|---|---|
| input entry 封完整 CR-2 seal | `InputRunSeal` 19 字段（contract version / mapper identity+code hash / manifest uri+hash / output_set+semantic hash / status / raw identity / verification / received_at / pit_available） | `TestFullSealConsumption::test_typed_input_seal_three_way_equality`（snapshot == manifest == ledger + 全字段存在断言） |
| manifest 显式 provenance 全消费 | `_verify_closure`：identity_master_input_set_hash / bridge policy version+hash / required_evidence_classes（==current policy）逐项比对 | `test_identity_master_input_set_hash_rebind_blocks` / `test_bridge_policy_version_rebind_blocks` / `test_bridge_policy_hash_rebind_blocks` / `test_required_evidence_classes_rebind_blocks` |
| manifest_uri deterministic verify | expected base + `/manifest.json` 比对 | `test_manifest_uri_rebind_blocks` |
| input entry seal 字段 rebind -> DAMAGED | typed seal vs current snapshot 比对 | `test_input_entry_seal_field_rebind_blocks`（mapper_code_hash rebind + 外层 rehash） |
| CR-2 exact seal snapshot 化 | `input_seal_hash` 三方 + `_verify_sealed_input`（CR-2 manifest 自身 seal 字段 == typed seal） | 同上 + replay 回归 |

## §5 P0-05 Verification-State Transition

| Requirement | Implementation | Tests |
|---|---|---|
| state 相同 -> exact replay | run id = uuid5(base + state hash) | 既有 replay 回归全保持 |
| 历史 BLOCKED(可恢复) + repair -> 新 recovery run | state hash 变 -> 新 run id；历史证据保留 | `TestVerificationStateTransition::test_anchor_missing_then_repair_mints_recovery_run`（BLOCKED → repair → 新 SUCCESS run + BLOCKED 行/finding 保留）/ `test_closure_damage_then_repair_mints_recovery_run` |
| 历史 SUCCESS + 退化 -> DAMAGED 拒绝 | degraded-SUCCESS guard（同 base 非 BLOCKED 历史 + 当前 damaged → raise） | `test_prior_success_degradation_refused`（DAMAGED；无新 run minted；exact repair 后恢复历史 replay） |
| repair 不覆盖历史 BLOCKED evidence | append-only（无 UPDATE/DELETE 路径） | `test_repair_preserves_block_evidence`（2 ledger 行 + BLOCKED finding 保留） |
| state 不污染 base identity | `InputRunSeal.identity_dict()`（state 字段排除出 input_set_hash/base） | `test_prior_success_degradation_refused`（退化后 base 仍同 -> guard 命中） |

## §7 测试矩阵对照（32 项）

```text
[✓] 01 broad reads 之间第二 connection INSERT S2 -> current run 严格 S1（真实 MVCC）
[✓] 02 master query 前插入 master run -> snapshot 不可见
[✓] 03 next invocation 看到 S2 -> new identity
[✓] 04 snapshot verify M1 后 UPDATE ledger manifest_uri=M2 -> 不消费 M2
[✓] 05 verify P1 后 replace file P2 -> 只消费已物化 P1
[✓] 06 snapshot nested record mutation 不可改变 authoritative truth
[✓] 07 future-only master received_at > as_of -> 不进 IdentityBridge
[✓] 08 early master + future relist -> historical security_id 保持 early truth
[✓] 09 all identity master future-only -> identity-required domain BLOCKED
[✓] 10 master anchor missing before FIRST -> BLOCK（IDENTITY_EVIDENCE_INVALID）
[✓] 11 master raw meta/anchor mismatch before FIRST -> BLOCK
[✓] 12 first run 后立即 replay 无外部变化 -> 通过同一 verifier（parity）
[✓] 13 required_evidence_class unsupported -> run 前 fail closed
[✓] 14 reconciliation unsupported -> fail closed
[✓] 15 tolerance_rule_id/version unsupported -> fail closed
[✓] 16 conflict_action unsupported -> fail closed
[✓] 17 supported v1 policy values -> 行为不变
[✓] 18 manifest identity_master_input_set_hash rebind -> DAMAGED
[✓] 19 manifest bridge policy version/hash rebind -> DAMAGED
[✓] 20 manifest required_evidence_classes rebind -> DAMAGED
[✓] 21 canonical manifest_uri rebind -> DAMAGED
[✓] 22 upstream input entry full CR-2 seal field rebind -> DAMAGED
[✓] 23 full typed input seal 三方 exact equality
[✓] 24 source anchor missing -> BLOCKED；governed repair -> next invocation 不 replay stale BLOCKED（新 recovery run + 证据保留）
[✓] 25 source closure temporarily damaged -> BLOCKED；exact repair -> recovery run
[✓] 26 prior SUCCESS -> damage -> DAMAGED（无 replacement；repair 后恢复历史 replay）
[✓] 27 repair 保留历史 BLOCKED evidence（append-only）
[✓] 28 migration 020 from-zero（20 链）
[✓] 29 migration 019->020 upgrade（含 020 四列断言）
[ ]  30 Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green（推送后 API 正向确认，SHA 回填）
[✓] 31 Ruff / format / Mypy / Spike / governance gates green（本地；CI 待确认）
[✓] 32 all CR-3.1 / CR-3 / CR-2.x / R4 frozen regressions green（81 + 985 全保持；总体 1096/0）
```

## §9 Exit Gate 对照（17 项）

```text
[✓] real DB snapshot boundary before first authoritative broad read（BEGIN TRANSACTION + MVCC race 测试）
[✓] actual consumed normalized rows materialized from exact verified bytes
[✓] no post-snapshot current-ledger/current-path reread changes consumed truth
[✓] snapshot deeply immutable（typed frozen records + tuple-frozen rows）
[✓] identity master anchored evidence verified on first consume and replay（对称）
[✓] identity master obeys PIT as_of availability policy
[✓] future master cannot change historical identity truth
[✓] policy declaration and runtime behavior exact match / unsupported fail closed
[✓] full manifest provenance fields consumed（rebind 矩阵全拦截）
[✓] upstream CR-2 full seal snapshotted/bound（InputRunSeal + input_seal_hash 三方）
[✓] deterministic manifest URI verified
[✓] repair 后不 replay stale BLOCKED（base + state identity）
[✓] prior SUCCESS degradation DAMAGED fail closed
[✓] recoverable repair preserves immutable history
[✓] CR-3.1 passed mechanisms frozen（81 项回归全保持）
[✓] no CR-4 logic leak
[ ]  migration / CI / governance green（migration 20 链本地全绿；CI 待 API 确认，SHA 回填；governance 本批已同步）
```

## Verification Summary

- Local: **1096 / 0**（1066 → 1096，+30：TransactionalSnapshot 6 / IdentityMasterPIT 6 / HonestPolicyExecution 8 / FullSealConsumption 7 / VerificationStateTransition 3）；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款命令 `uv run pytest` 复验 1096/0
- ADR-023 Amendment B（status 仍 PROPOSED）；migration 020（未改 018/019）；CR-3.1 FREEZE 的 19 项机制零重写（81 项回归全保持）
- Implementation SHA + CI run：推送后回填（本节与 DEVLOG/总册头部同步更新）