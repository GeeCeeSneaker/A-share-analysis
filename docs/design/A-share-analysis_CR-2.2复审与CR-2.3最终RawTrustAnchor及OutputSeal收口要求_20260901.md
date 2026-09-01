# A-share-analysis：CR-2.2 复审与 CR-2.3 最终 Raw Trust Anchor / Provider-Owned Operation Spec / Output Seal 收口要求

> **Review Date**：2026-09-01 10:45 +08:00  
> **Reviewed Repository HEAD**：`a4a23cd3f758a6cdc450b4256f1d66172ba3524c`  
> **Primary CR-2.2 Implementation**：`a06ea2202cb4f7a5ea0a91c09e666867267a8575`  
> **Reviewer Baseline / Requirements**：`b779994714a55200f437045e31aa0cc5d36350e3`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-2.2 已正确部分**：**大部分 PASS / FREEZE**  
> **Next Batch**：**CR-2.3 Final Raw Evidence Trust Anchor + Provider-Owned Operation Spec + Output-Set / Semantic Seal**  
> **CR-3**：**BLOCKED_BY_CR-2.3**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-2.2 对上一轮 3 个问题继续做了实质修复。以下机制本轮正式 **PASS / FREEZE**，CR-2.3 不得推倒重写：

```text
PASS / FREEZE  stock daily_bar / index_daily 双 wrapper + typed 四元 registry
PASS / FREEZE  call_exchange 已移除 normalization_surface 直接 override 参数
PASS / FREEZE  normalization_surface 当前由 require_capability 派生
PASS / FREEZE  conflict run 新运行时逻辑不会直接成为下一次 baseline
PASS / FREEZE  exact replay 不再依赖 latest run，而按 deterministic run_id 查全历史
PASS / FREEZE  mapper A -> B -> A / contract rollback 的历史 exact replay 方向正确
PASS / FREEZE  full 64-hex MAPPER_CODE_FINGERPRINT 已进入 correctness key
PASS / FREEZE  NormalizationRunSeal typed ledger/manifest/current provenance 框架
PASS / FREEZE  SUCCESS/PARTIAL 必须有 manifest
PASS / FREEZE  quarantine_set_hash 的 DB exact-set 重算
PASS / FREEZE  physical parquet content hash / row_count / schema_hash replay-time 重算
PASS / FREEZE  file-side output -> manifest LAST 可恢复协议
PASS / FREEZE  run ledger + quarantine 单 DuckDB transaction
PASS / FREEZE  migration 016 为 additive migration，014/015 未改
PASS / FREEZE  current HEAD full CI 三腿 green
PASS / FREEZE  CR-2/2.1 no-sentinel / no-silent-drop / row locator / provider-faithful 语义
```

但继续从“谁是 trust root”而不是“已有 hash 是否能对上”审查后，仍发现 **3 个 P0 correctness blockers**：

1. `normalization_surface` 虽不再直接是参数，但公开 production callable `call_exchange(... require_capability=...)` 仍允许普通 caller 自行选择 capability；surface 又等于 `require_capability`。因此 caller 仍可构造 `endpoint/dataset/fn` 与 capability 不一致的 exchange，只是把自报入口从 `normalization_surface` 换成了 `require_capability`。
2. CR-2 第一次消费某条 Raw evidence 时，没有一个**Raw 文件系统之外的 authoritative expected meta hash**。Runner 只是现场 hash 当前 `.meta.json` 并以此作为初始 baseline；而 `verify_meta_closure()` 只验证 meta 声明的 payload 文件/hash/combined hash，不验证 meta 自己是否仍是 RawWriter 当时落盘的原字节。因此在该 request **尚未有 normalization run** 时，单独修改 meta 中 `normalization_surface / endpoint / request params / account 等非 payload-hash 字段` 可以逃过 closure，成为第一次 normalization 的“初始真相”。migration 016 的 legacy rows 默认 `evidence_conflict=FALSE` 也无法安全识别 015-era 已经发生过的 laundering history。
3. `NormalizationRunSeal` 目前封住了主要 ledger/manifest 字段以及每个 manifest 已列出的 output 文件，但**没有封住 expected output exact set / normalized semantic identity**。例如 `security_status_history` 按 registry 必须同时产生 `security_status + limit_price + corporate_action`；如果从 manifest 删除一个 output，再重算 manifest hash 并更新 ledger hash，当前 verifier 只遍历并验证 manifest 中“剩下的 outputs”，不会发现必需输出缺失。类似地，physical parquet 的值若整体换成同 schema/row_count 的另一份数据，并同步更新 manifest content_hash + ledger manifest_hash，当前没有 ledger-bound semantic hash 来证明 normalized values 仍是原运行结果。

因此正式状态：

```text
CR-2      DONE / REOPENED
CR-2.1    DONE / REOPENED（已通过部分 FREEZE）
CR-2.2    DONE / REOPENED（exact replay / full fingerprint / schema verify FREEZE）
CR-2.3    START / ACTIVE NEXT
CR-3      BLOCKED_BY_CR-2.3
```

不重开 R4-B2/B1/A3/A2/CR-1 已冻结机制，除非 CR-2.3 引入可复现 regression。

---

# 1. 本轮已经通过并冻结的 CR-2.2 能力

## 1.1 全历史 exact replay —— PASS / FREEZE

当前 replay 已不再使用 `ORDER BY started_at DESC LIMIT 1` 决定 correctness identity，而是：

```text
exact idempotency_key
 -> uuid5(_RUN_NAMESPACE, key)
 -> exact normalization_run_id PK lookup
 -> existing closure verify
 -> idempotent replay
```

因此 historical A -> B -> A rollback 不会被最新 B 阴影，方向正确，冻结。

## 1.2 conflict run 不再直接洗白当前 hash —— PASS / FREEZE（仅限 016 之后的新运行时）

当前 runner 通过 `evidence_conflict=TRUE` 标记“当前 hash 与既有 trusted baseline 不一致”的 incident BLOCK，并在 baseline 查询中排除 conflict rows。

因此在**016 之后由新代码首次观察到的** H1 -> H2 tamper：

```text
H1 trusted
H2 conflict -> evidence_conflict=TRUE
second H2 -> exact conflict replay / still BLOCK
```

不会再出现上一版“第二次 H2 因最新 run 也是 H2 而被洗白”的直接路径。本机制保留，但 CR-2.3 必须把 baseline trust root 从 normalization history 提升到 Raw ingestion-time anchor，解决 first-consume / legacy upgrade 问题。

## 1.3 Full mapper fingerprint + typed manifest seal + schema recheck —— PASS / FREEZE

`_supported_key/_blocked_key` 已把完整 64 hex `MAPPER_CODE_FINGERPRINT` 混入 correctness hash；显示用短 hash 不再承担 correctness。

Replay 当前会：

```text
ledger contract == CURRENT contract
ledger mapper_code_hash == CURRENT full mapper fingerprint
manifest major semantic fields == ledger seal
quarantine DB exact set recompute == ledger/manifest seal
parquet bytes hash == manifest
parquet row_count == manifest
physical parquet schema hash == manifest
```

以上机制继续冻结。CR-2.3 只补 missing expected-output / semantic-value seal，不重写现有 typed seal。

## 1.4 CI —— PASS

- CR-2.2 implementation `a06ea2202cb4f7a5ea0a91c09e666867267a8575`：run `33460094366` success。
- current reviewed HEAD `a4a23cd3f758a6cdc450b4256f1d66172ba3524c`：run `33460750772` success。
- Ubuntu Python 3.14：success。
- Windows Python 3.12：success。
- Windows Python 3.14：success。
- Ruff lint / format / Mypy / Pytest / Spike framework gates：success。

本轮 REOPEN 仍是 correctness/trust-root blocker，不是 CI blocker。

---

# 2. P0-01：Surface provenance 仍通过 public `require_capability` 间接 caller-declared

## 2.1 当前代码事实

CR-2.2 已删除：

```text
call_exchange(... normalization_surface=...)
```

但 public method 仍为：

```python
call_exchange(endpoint, dataset, fn, *, params=None, require_capability=None)
```

且：

```python
surface_identity = str(require_capability or "")
```

因此普通 caller 仍可语义上执行：

```text
endpoint = MarketData.query_kline
dataset = daily_bar
fn = stock-kline callable
require_capability = index_daily

=> persisted normalization_surface = index_daily
```

只要 index_daily capability gate 本身允许，该 exchange 的 surface provenance 就来自 caller 选择，而不是 provider-owned operation declaration。

这与 B1/B2 的冻结原则相同：**caller-declared correctness identity 不能因为换了字段名字就变成 system-derived**。

## 2.2 CR-2.3 Required Closure

推荐建立 private typed **ProviderOperationSpec**（命名可调整）：

```text
ProviderOperationSpec
  operation_id
  capability
  endpoint
  provider_dataset
  normalization_surface
```

并采用：

```text
public typed wrapper
  -> private operation spec constant
  -> private _execute_exchange(spec, fn, params)
  -> endpoint/dataset/capability/surface 全部从 spec 派生
```

要求：

- ordinary production caller 不再能自由组合 endpoint / dataset / capability / surface；
- generic exchange execution boundary 若保留必须 private/internal，不作为正常 production callable；
- stock query_kline wrapper 和 index query_kline wrapper 使用不同 static operation spec；
- structural guard 精确检查 operation registry ↔ endpoint requirement / normalization registry；
- caller API 不接受 capability/surface/endpoint/dataset 的任意 correctness组合。

不要求防 Python 解释器级 monkeypatch private state；标准与 B2 scanner static registry 一致。

### 必测

```text
caller cannot call public generic exchange with daily fn + index capability
public API signatures contain no free-form capability/surface correctness selector
stock wrapper -> daily_bar operation spec only
index wrapper -> index_daily operation spec only
operation spec / normalization registry structural exact set guard
```

---

# 3. P0-02：第一次 normalization 前 Raw meta 本身没有 authoritative external hash anchor

## 3.1 当前 `verify_meta_closure()` 实际证明什么

当前 closure 检查：

```text
every table file exists
payload bytes hash == meta.tables[].content_hash
combined payload content_hash recomputes
```

它**不可能单靠 meta 自己证明 meta 字节仍是 RawWriter 当时写出的原字节**。

例如只修改：

```text
normalization_surface: daily_bar -> index_daily
endpoint
request_params
account_profile_id
capability_status
```

只要不破坏 table hash/combined payload hash，payload+meta closure 仍可成立。

当前 runner 在 first consume 时：

```text
raw_evidence_hash = sha256(CURRENT meta bytes)
baseline_hashes = normalization run history
if no prior run -> baseline empty
=> CURRENT meta hash becomes first accepted binding
```

这不是 ingestion-time evidence anchor verification。

## 3.2 migration 016 legacy upgrade 也不安全

migration 016：

```sql
evidence_conflict BOOLEAN DEFAULT FALSE
```

对所有 014/015 legacy run 默认 FALSE。

但 015-era 代码本身存在 Reviewer 已证明的 laundering path，因此一个真实旧库可能已有：

```text
H1 SUCCESS/PARTIAL
H2 RAW_EVIDENCE_INVALID BLOCKED（由 tamper conflict 产生）
```

升级 016 后二者都 `evidence_conflict=FALSE`，baseline 会变成 `{H1, H2}`，H2 已被 grandfather 为 trusted hash。

不能用“legacy rows 默认都是可信”作为 correctness 证明。

## 3.3 CR-2.3 Required Closure：Raw Evidence Trust Anchor

CR-2 normalization 应消费一个**Raw 文件系统之外、在 RawWriter 成功落盘时就生成的 authoritative evidence anchor**。

推荐增加 additive migration（017+）+ raw-evidence ledger，例如：

```text
meta_raw_evidence_anchor
  provider
  provider_dataset
  request_id
  evidence_uri
  evidence_hash          # persisted meta exact-byte SHA256
  endpoint / operation_id / normalization_surface（可作为交叉绑定）
  ingest_run_id
  created_at
  immutable identity / uniqueness
```

正式流程：

```text
ProviderOperationSpec
 -> ProviderExchange
 -> RawWriter commit meta LAST
 -> reread persisted meta bytes
 -> compute evidence_hash
 -> persist Raw Evidence Anchor in governed ingestion control flow
 -> CR-2 NormalizationRunner
 -> lookup exact expected evidence_hash from anchor ledger
 -> CURRENT meta bytes hash must equal expected
 -> only then verify payload closure + route mapper
```

关键原则：

- `NormalizationRunner` 不能把“自己第一次看到的 meta hash”当 trust root；
- expected raw evidence hash 不能由 normalization caller 参数提供；
- conflict normalization rows只做 audit，不再承担 raw trust baseline；
- legacy raw 无 authoritative anchor 时 fail closed / re-ingest / governed rebuild，不得猜；
- 若允许 legacy rebuild，只能对**客观可证明唯一**的历史 evidence identity 建 anchor；多 hash / conflict history 必须人工/重新取数处理，不能 migration 静默任选。

### 对 migration 016 的处理

不要求回改 016。新增 017+ 把 `evidence_conflict` 降为诊断/audit 属性；CR-2 correctness trust root 改为 raw evidence anchor ledger。

### 必测

```text
1. first normalization 前只改 meta.normalization_surface，payload 不动 -> BLOCK
2. first normalization 前只改 endpoint/request_params 等非 payload-hash字段 -> BLOCK
3. raw meta bytes hash != authoritative raw anchor -> BLOCK before routing
4. 015-era DB：H1 + historical H2 conflict BLOCK -> upgrade 017 后 H2 绝不能 trusted
5. legacy request with >1 distinct historical raw hash -> no auto anchor / fail closed
6. legacy request with no anchor -> fail closed（或按明确 governed re-ingest path）
7. exact healthy anchor + intact meta/payload -> normalize success
8. anchor itself duplicate/conflicting identity -> hard fail
```

---

# 4. P0-03：Full Seal 仍未封住 expected output exact set + normalized semantic values

## 4.1 Missing Output Set Seal

`_verify_manifest_outputs()` 当前：

```text
for output in manifest["outputs"]:
   verify listed file exists
   verify content hash
   verify row count
   verify schema hash
```

但没有：

```text
actual manifest output_names exact set == current spec.output_names
```

因此 multi-output surface：

```text
security_status_history
 expected:
   security_status
   limit_price
   corporate_action
```

若攻击/损坏操作：

```text
从 manifest 删除 corporate_action entry
重新写 manifest
UPDATE ledger.normalized_manifest_hash
```

当前 verifier 会验证剩下两份并可能 replay healthy；必需输出缺失没有结构性判定。

## 4.2 Missing Ledger-Bound Semantic Seal

Manifest 当前已有 `semantic_hash`，但 ledger 没有独立绑定该 semantic identity，replay 也没有从 physical parquet 重算 semantic records hash 并三方比较。

因此 coordinated rebind：

```text
替换 parquet values（保持 schema + row_count）
更新 manifest.content_hash
更新 manifest.semantic_hash
更新 ledger.normalized_manifest_hash
```

仅靠当前 typed fields / schema / row count不能证明 normalized values仍是原 run 的结果。

## 4.3 Required Closure

推荐 migration 017+ 在 normalization run ledger 增加至少：

```text
normalized_output_set_hash
normalized_semantic_hash
```

其中：

```text
normalized_output_set_hash = hash(sorted(
  output_name,
  canonical logical uri,
  content_hash,
  schema_hash,
  row_count
))
```

并三方消费：

```text
ledger output_set_hash
== manifest output_set_hash / recomputed manifest output set
== replay-time physical output recompute
```

同时：

```text
ledger normalized_semantic_hash
== manifest semantic_hash
== replay-time from physical parquet records recompute
```

以及 exact expected set：

```text
manifest output_name set == current typed registry spec.output_names
no duplicate output_name
no missing required output
no undeclared extra output
```

URI 也应按 deterministic expected base path + output_name 重算，而不是只接受 manifest 任意 logical URI。

`NormalizationRunSeal` 建议增加：

```text
raw_evidence_uri
raw_payload_kind
normalized_output_set_hash
normalized_semantic_hash
```

并把 manifest ↔ ledger ↔ physical current verification 做成 typed reusable contract。

### 必测

```text
1. multi-output manifest 删除 1 个 required output + rehash ledger -> DAMAGED
2. manifest 增加 unknown output -> DAMAGED
3. duplicate output_name -> DAMAGED
4. output URI 重绑到另一合法 logical path -> DAMAGED
5. parquet values 替换、schema/row_count不变 + update content_hash + rebind manifest hash -> DAMAGED
6. manifest semantic_hash + ledger manifest hash一起重绑，但 ledger semantic seal未改 -> DAMAGED
7. ledger semantic seal篡改 -> current physical recompute mismatch
8. normal happy replay output-set + semantic three-way exact match -> PASS
```

---

# 5. CR-2.3 不允许重开的冻结机制

除非出现真实 regression，CR-2.3 不得重新设计：

```text
RawWriter exact-byte / payload closure既有机制
Provider-Normalized DTO provider-faithful semantics
no sentinel
row locator
no silent drop accounting
whole-payload calendar quarantine
private immutable normalization registry
stock/index typed routing
full-history deterministic run-id replay
full 64-hex mapper fingerprint key
quarantine_set_hash exact-set
schema hash physical recompute
output -> manifest LAST recoverable file protocol
ledger + quarantine single transaction
logical URI confinement
R4-B2/B1/A3/A2/CR-1 frozen contracts
```

CR-2.3 是**信任根 + exact output seal**收口，不是再造 normalization framework。

---

# 6. 必须增加的对抗测试矩阵

至少覆盖：

```text
A. Provider-owned operation provenance
1. public production API cannot freely choose require_capability/surface for generic exchange
2. stock/index wrappers bind distinct private static operation specs
3. operation spec cross-checks endpoint/dataset/capability/normalization registry exact identity

B. Raw trust anchor
4. first normalization before any prior run: meta surface tamper -> BLOCK
5. first normalization: meta endpoint/params/account metadata tamper -> BLOCK
6. current meta hash != ingestion-time raw anchor -> BLOCK before mapper
7. 015 legacy H1 + H2 conflict history upgrade -> H2 not trusted
8. ambiguous legacy raw anchor cannot auto-grandfather
9. missing anchor fail closed/re-ingest
10. healthy anchor exact match success

C. Output + semantic seal
11. required output removed + manifest rehash + ledger manifest hash update -> BLOCK
12. undeclared output added -> BLOCK
13. duplicate output name -> BLOCK
14. output URI rebind -> BLOCK
15. same schema/row-count but changed values + rebind content/manifest hashes -> BLOCK
16. semantic ledger seal tamper -> BLOCK
17. normal exact replay remains PASS

D. Regression
18. SUCCESS/PARTIAL/BLOCKED historical exact replay remains green
19. conflict H2 repeated stays BLOCKED
20. mapper A->B->A replay remains green
21. DB failure recovery remains green
22. no-sentinel / no-silent-drop / locator / calendar / provider-faithful all green
23. migration from-zero + 016->017 upgrade + idempotency/tamper green
24. Ubuntu 3.14 / Windows 3.12 / Windows 3.14 full CI green
```

---

# 7. CR-2.3 Exit Gate

只有全部满足，Reviewer 才允许 CR-2 CLOSED -> CR-3 START：

```text
[ ] generic production exchange boundary no caller-selectable capability/surface correctness identity
[ ] provider operation identity private/static and wrapper-owned
[ ] stock/index operation identity exact and structurally guarded
[ ] ingestion-time Raw meta exact-byte hash has external authoritative anchor
[ ] normalization verifies expected Raw evidence hash before routing/mapping
[ ] first-consume meta-only tamper fail closed
[ ] legacy 015 conflict history cannot be grandfathered as trusted anchor
[ ] full-history exact replay remains intact
[ ] full mapper fingerprint correctness key remains intact
[ ] manifest expected output names exact-set == registry spec
[ ] output logical URI deterministic exact binding
[ ] ledger/manifest/physical output-set hash three-way bound
[ ] ledger/manifest/physical normalized semantic hash three-way bound
[ ] quarantine exact-set seal remains intact
[ ] physical content/schema/row-count recheck remains intact
[ ] recoverable file + DB commit semantics remain intact
[ ] no CR-3 Availability/SourcePolicy/Canonical semantics leak in
[ ] migrations from-zero/upgrade/idempotency/tamper green
[ ] full CI green
[ ] ADR-022 / DEVLOG / DEVELOPMENT_MANAGEMENT synced current truth
```

完成后必须一次性：

```text
CR-2 / CR-2.1 / CR-2.2 / CR-2.3 -> VERIFIED / CLOSED / FREEZE
ADR-022 -> ACCEPTED
CR-3 AvailabilityPolicy + Canonicalizer -> START
```

**通过 CR-2.3 后不再继续扩张 CR-2 scope。** 后续只有可复现 regression 才重开。

---

# 8. Governance 要求

下一开发批次同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
docs/adr/ADR-022_provider_normalization_quarantine.md
```

ADR-022 继续 `PROPOSED`，待 Reviewer CR-2.3 closure 后改 `ACCEPTED`。

状态：

```text
R4-B2.x          CLOSED / VERIFIED / FREEZE
CR-2             DONE / REOPENED
CR-2.1           DONE / REOPENED（部分机制 FREEZE）
CR-2.2           DONE / REOPENED（exact replay/full fingerprint/schema verify FREEZE）
CR-2.3           ACTIVE / NEXT
CR-3             BLOCKED_BY_CR-2.3
Production P0-M-1B BLOCKED independently
```

本 focused reviewer document 在下一 developer governance sync 前是当前权威复审/下步工作要求。

---

# 9. 面向项目 Owner 的中文工程进度

## 9.1 当前阶段一句话

Raw -> Provider-Normalized 这层已经从“能转换”发展到“能隔离坏数据、能恢复失败、能历史精确重放”。现在剩下的是最后的**信任根**：系统必须证明“第一次看到的 Raw meta 就是取数时那份原始 meta”，并证明“一个标准化运行应产生的所有输出一份不少、里面的实际数据值没有被整体替换”。这两件事解决后，CR-2 才真正能作为 CR-3 的可信输入。

## 9.2 本阶段功能实现情况

```text
Raw -> Provider-Normalized                已实现
坏数据 Quarantine                         已实现
坏行精确定位                              已实现
禁止 1970/0.0 sentinel                   已实现
no-silent-drop 记账                       已实现
股票/指数 typed routing                   已实现
immutable normalization registry          已实现
SUCCESS/PARTIAL/BLOCKED 重放框架          已实现
全历史 exact replay                       已实现
mapper full SHA-256 correctness identity   已实现
quarantine exact-set seal                  已实现
parquet content/row/schema replay 验证      已实现
文件/DB故障恢复                            已实现

provider operation 彻底不可 caller 自报    待 CR-2.3
Raw meta ingestion-time external hash anchor 待 CR-2.3
legacy conflict upgrade 安全处理            待 CR-2.3
required output exact-set seal              待 CR-2.3
normalized semantic-value ledger seal        待 CR-2.3

CR-3 Canonical Runtime                     尚未启动
```

## 9.3 中文工程进程图

```text
A股市场态势数据基座
│
├─ ① 原始数据证据层
│    ✅ 原始数据落盘、payload hash、meta anchor、精确重放机制已完成
│    🔧 CR-2.3 追加：把 meta 的 exact-byte hash 在文件系统之外正式登记
│       目的：第一次下游消费前也能发现 meta 自身被修改
│
├─ ② 数据供应商能力验证
│    ✅ 账号 / 权限 / 精确 endpoint / approval 防绕过已完成
│
├─ ③ 发布安全检查
│    ✅ 文件 / DQ / 输入新鲜度 / 发布最终复验 / rollback 已完成
│
├─ ④ Raw -> Provider 标准化 + 坏数据隔离
│    🟡 已接近最终闭环
│    │
│    ├─ ✅ 正常数据标准化
│    ├─ ✅ 坏数据隔离并定位原始行
│    ├─ ✅ 股票/指数不再共用错误 mapper
│    ├─ ✅ mapper registry 不可普通调用方替换
│    ├─ ✅ SUCCESS/PARTIAL/BLOCKED 可历史 exact replay
│    ├─ ✅ mapper 完整 SHA-256 进入 run identity
│    ├─ ✅ DB/文件失败可恢复
│    ├─ ✅ quarantine 集合可校验
│    ├─ ✅ parquet 内容/行数/schema 可重验
│    │
│    └─ 🔧 CR-2.3 最后收口
│         ├─ provider 操作身份彻底由系统 wrapper 决定
│         ├─ Raw meta 第一次消费也有外部 hash 锚点
│         ├─ 旧库曾经发生的冲突不能被升级自动洗白
│         ├─ 多输出一份都不能少、一份都不能多
│         └─ 标准化后的实际数据值有独立 semantic seal
│
├─ ⑤ 多供应商统一 Canonical
│    ⏸ CR-3 等待 CR-2.3
│
├─ ⑥ Snapshot / ReadModel
│    ⏸ CR-4 等待 CR-3
│
└─ ⑦ 正式生产闭环
     ⛔ 仍需后续 runtime + 正式账号 + Golden/Trading Rule 人工复核
```

## 9.4 主要能力闭环程度（工程口径，不等于工时）

```text
原始 payload 完整性 / 重放          ██████████ 100%
Provider 能力 / 审批安全            ██████████ 100%
Publish 发布安全                    ██████████ 100%
坏数据发现 / 定位 / 隔离            █████████░ 约95%
Raw -> Provider-Normalized          █████████░ 约95%
历史 exact replay                   ██████████ 接近闭环
标准化故障恢复                      ██████████ 接近闭环

Raw meta 自身第一次消费防篡改        ██████░░░░ 约60%（缺外部 anchor）
Provider operation provenance        ████████░░ 约80%（仍有 public capability selector）
Normalized 输出完整集合证明          ███████░░░ 约70%
Normalized 实际值 semantic seal      ██████░░░░ 约60%

跨 Provider Canonical               ░░░░░░░░░░ 0%
Snapshot / ReadModel                 ░░░░░░░░░░ 0%
正式生产可用                         ░░░░░░░░░░ 尚未进入
```

当前最重要的工程判断：**CR-2 已经不再缺“数据怎么转换”的主体能力，缺的是“第一次输入和最终输出究竟能不能被当成不可替换的可信事实”。CR-2.3 只解决这个 trust-root / exact-output 闭环，通过后就应停止继续扩张 CR-2，正式转入 CR-3。**

---

# 10. Implementation Mapping（开发方填写，2026-09-01）

## §2 P0-01 Provider-Owned Operation Spec

| Requirement | Implementation | Tests |
|---|---|---|
| 撤销 caller 自由组合入口 | `call_exchange` / `_call_or_exchange` 删除；generic executor 私有化为 `_execute_exchange(spec, fn, params)` | `TestRegistryStructuralGuard::test_no_public_generic_exchange_boundary`（公开方法签名无 endpoint/dataset/require_capability/capability/normalization_surface/spec；`hasattr(call_exchange)` 为 False） |
| private typed ProviderOperationSpec | `operations.py`：frozen dataclass + 15 私有静态常量 + 私有 `_OPERATION_SPECS` dict + 只读 `lookup_operation_spec` | `TestOperationSpecProvenance::test_specs_are_immutable_and_private_registry` |
| wrapper -> 私有 spec 常量 -> 私有 executor | 15 个 wrapper 全部改为 `self._execute_exchange(<CONST>, fn, params=...)`；kline 双 wrapper 绑定 `DAILY_BAR_KLINE` / `INDEX_DAILY_KLINE` | `test_provider_facade_kline_wrappers_declare_distinct_surfaces`（AST 断言绑定 + 双 spec capability/surface 互斥且共享 endpoint/dataset）+ `test_executor_signature_is_spec_typed_private`（签名仅 `(self, spec, fn, params)`） |
| operation registry ↔ 双契约结构守卫 | spec (capability, endpoint) ∈ SDK_METHOD_CLASSIFICATIONS；spec (surface, dataset, endpoint) ∈ registry 且非 NOT_APPLICABLE；双向 exact | `test_operation_specs_cross_checked_with_both_contracts`（15 spec；seen == non-NA registry keys） |
| meta 持久化 operation 身份 | RawEnvelope.operation_id + raw meta `operation_id` 字段（RawWriter） | `TestRawTrustAnchor::test_anchor_cross_binds_operation_identity`（anchor 行交叉绑定 endpoint/surface） |

## §3 P0-02 Raw Evidence Trust Anchor

| Requirement | Implementation | Tests |
|---|---|---|
| anchor ledger（017+） | migration 017 `meta_raw_evidence_anchor`（PK + evidence_uri/hash + endpoint/operation_id/surface/payload_kind/ingest_run_id/created_at） | `test_migrations.py` 17 链 + anchor 列断言 |
| RawWriter 落盘后 reread + 登记 | `raw_anchor.py::record_raw_evidence_anchor`（governed ingestion flow 组件：reread persisted meta bytes → sha256 → insert） | `test_anchor_recording_is_idempotent_and_conflict_hard_fails`（同 bytes 幂等一行；异 bytes `RawAnchorError`——永不 re-baseline） |
| runner 查 expected hash 于路由前 | `runner.py::run()` 头部 `lookup_raw_evidence_anchor`——任何 meta 解析/路由/映射之前 | `test_first_consume_surface_tamper_blocks_before_routing`（无 prior run；仅改 surface 字段 → BLOCK；无输出；ledger 仅 1 行 incident） |
| 首消费 meta-only 篡改 fail closed | anchor mismatch（surface/endpoint/params/account 任一改动都改变 meta bytes） | `test_first_consume_endpoint_params_account_tamper_blocks`（endpoint/account 逐项篡改 → MISMATCH；恢复原 bytes → SUCCESS） |
| current hash != anchor -> BLOCK before mapper | `RAW_ANCHOR_MISMATCH` blocked run（evidence_conflict=TRUE 诊断） | `test_raw_meta_hash_tamper_blocks`（CR-2 回归更新）+ 上述两项 |
| 015-era H1+H2 冲突史升级不洗白 | 无 anchor → `RAW_ANCHOR_MISSING` 永续 fail closed；migration 不 auto-anchor；失败运行不建 anchor | `test_legacy_history_upgrade_never_trusts_conflict_hash`（fabricated legacy H1/H2 runs → BLOCKED；无 anchor 自动创建；H2 无 SUCCESS 行） |
| 多 hash legacy 不 auto-grandfather | 同上（任何无 anchor 情况 fail closed） | 同上（>1 distinct hash 场景含于 fabricated history） |
| legacy 无 anchor fail closed / re-ingest | `RAW_ANCHOR_MISSING` + governed re-ingest 路径（record anchor 后解锁） | `test_missing_anchor_fails_closed_then_governed_reingest_succeeds` |
| healthy anchor exact match success | 全部既有 happy-path 测试经 `_persist_raw(conn=conn)` 记录 anchor | `test_anchor_cross_binds_operation_identity` + 84 项回归 |
| anchor duplicate/conflict -> hard fail | `RawAnchorError` | `test_anchor_recording_is_idempotent_and_conflict_hard_fails` |
| 016 evidence_conflict 降级 | mismatch 运行仍标记 TRUE 但仅诊断；信任根 = anchor；旧 baseline 查询删除 | `test_blocked_conflict_run_replays_idempotently`（CR-2.2 回归：conflict run 幂等 + 标记计数） |

## §4 P0-03 Output-Set / Semantic Seal

| Requirement | Implementation | Tests |
|---|---|---|
| normalized_output_set_hash / normalized_semantic_hash（017+） | migration 017 两列 + `_output_set_hash()` canonical hash | `test_happy_path_exact_set_and_seals`（ledger == manifest 双 seal；replay healthy） |
| 三方 output-set 消费 | replay 物理重算（content/schema/row_count from files + expected URI）== ledger == manifest | `test_ledger_output_set_seal_tamper_blocks` / `test_manifest_output_set_hash_rebind_blocks` |
| 三方 semantic 消费 | replay 从物理 parquet records 重算 `_canonical_semantic_hash` == ledger == manifest | `test_values_swapped_same_schema_rowcount_rebind_blocks`（§4.6-15：同 schema/row_count 换值 + rebind content/manifest hash → DAMAGED） |
| manifest expected set == 当前 spec.output_names | `_verify_manifest_outputs` registry lookup + missing/extra/duplicate 检查 | `test_required_output_removed_rebind_blocks`（§4.6-11）/ `test_undeclared_output_added_blocks`（§4.6-12）/ `test_duplicate_output_name_blocks`（§4.6-13） |
| output URI deterministic 重算 | expected_base 由 ledger 身份重算；uri ≠ base+name → rebind 检测 | `test_output_uri_rebind_blocks`（§4.6-14：移到另一合法 logical path） |
| semantic ledger seal 篡改 | ledger.normalized_semantic_hash 编辑 → 三方断裂 | `test_ledger_semantic_seal_tamper_blocks` / `test_manifest_semantic_hash_rebind_blocks`（§4.6-16） |
| manifest 携带 raw_payload_kind | manifest 新增字段 + seal 比对 | `manifest_binding_problems`（raw_evidence_uri/raw_payload_kind 全语义比对——rebind 矩阵回归） |
| 正常 exact replay PASS | — | `test_happy_path_exact_set_and_seals`（replay=True）+ 84 项回归 |
| 空表物化（零产出证据） | materialized set 恒等于 spec.output_names（空表 = 空 parquet） | `test_empty_payload_success_materializes_all_declared_outputs`（SUCCESS + 0 行 + 全输出物化 + replay healthy） |

## §5 冻结机制不重开

RawWriter exact-byte/payload closure / DTO provider-faithful / no-sentinel / row locator / no-silent-drop / calendar whole quarantine / private immutable registry / typed routing / full-history replay / full fingerprint key / quarantine exact-set / schema recompute / file-DB commit / logical URI confinement / R4 冻结契约——全部经 84 项回归保持（§6-D 矩阵 18-23）。

## §6 对抗测试矩阵对照（24 项）

```text
[✓] A1 public API 无法自由选择 require_capability/surface（签名守卫 + executor 私有）
[✓] A2 stock/index wrapper 绑定不同私有静态 spec（AST 断言）
[✓] A3 operation spec 与 endpoint requirement / normalization registry 双向 exact 核对
[✓] B4 首次消费前 meta surface 篡改 -> BLOCK（路由前）
[✓] B5 首次消费前 endpoint/params/account 篡改 -> BLOCK
[✓] B6 current meta hash != anchor -> BLOCK before mapper
[✓] B7 015 legacy H1+H2 冲突史升级 -> H2 不被信任
[✓] B8 多 hash legacy 不 auto-grandfather（失败运行不建 anchor）
[✓] B9 无 anchor fail closed / re-ingest 解锁
[✓] B10 healthy anchor exact match success
[✓] C11 required output 删除 + manifest rehash + ledger hash 更新 -> DAMAGED
[✓] C12 未声明 output 加入 -> DAMAGED
[✓] C13 duplicate output_name -> DAMAGED
[✓] C14 output URI 重绑 -> DAMAGED
[✓] C15 同 schema/row_count 换值 + rebind content/manifest hash -> DAMAGED
[✓] C16 semantic ledger seal 篡改 -> DAMAGED
[✓] C17 正常 exact replay PASS
[✓] D18 SUCCESS/PARTIAL/BLOCKED 历史 exact replay 回归全绿
[✓] D19 conflict H2 重复运行保持 BLOCKED（anchor 语义）
[✓] D20 mapper A->B->A replay 回归全绿
[✓] D21 DB 失败恢复回归全绿
[✓] D22 no-sentinel / no-silent-drop / locator / calendar / provider-faithful 回归全绿
[✓] D23 migration from-zero + 016->017 upgrade + idempotency/tamper 全绿
[ ]  D24 Ubuntu 3.14 / Windows 3.12 / 3.14 full CI green（本批推送后 API 正向确认，SHA 回填）
```

## §7 Exit Gate 对照（20 项）

```text
[✓] generic production exchange boundary no caller-selectable capability/surface correctness identity
[✓] provider operation identity private/static and wrapper-owned
[✓] stock/index operation identity exact and structurally guarded
[✓] ingestion-time Raw meta exact-byte hash has external authoritative anchor
[✓] normalization verifies expected Raw evidence hash before routing/mapping
[✓] first-consume meta-only tamper fail closed
[✓] legacy 015 conflict history cannot be grandfathered as trusted anchor
[✓] full-history exact replay remains intact
[✓] full mapper fingerprint correctness key remains intact
[✓] manifest expected output names exact-set == registry spec
[✓] output logical URI deterministic exact binding
[✓] ledger/manifest/physical output-set hash three-way bound
[✓] ledger/manifest/physical normalized semantic hash three-way bound
[✓] quarantine exact-set seal remains intact
[✓] physical content/schema/row-count recheck remains intact
[✓] recoverable file + DB commit semantics remain intact
[✓] no CR-3 Availability/SourcePolicy/Canonical semantics leak in
[✓] migrations from-zero/upgrade/idempotency/tamper green（17 链）
[ ]  full CI green（本批推送后 API 正向确认，SHA 回填）
[✓] ADR-022 / DEVLOG / DEVELOPMENT_MANAGEMENT synced current truth（Amendment C + DM-20260901-066 + DEVLOG 条目）
```

## Verification Summary

- Local: **975 / 0**（955 → 975，+20；normalization 104 = 84 回归 + 20 新增；migrations 11 含 17 链）；ruff check / ruff format / mypy 全绿（63 文件零错）；CI 同款命令 `uv run pytest` 复验 975/0
- ADR-022 Amendment C（status 仍 PROPOSED）；migration 017（未改 014/015/016）；contract 版本未 bump（`cr2.1-v1`——trust-root/seal 收口而非 registry 语义变更，full fingerprint 混入已使 key 空间区分新旧实现）
- Implementation SHA + CI run：推送后回填（本节与 DEVLOG/总册头部同步更新）
