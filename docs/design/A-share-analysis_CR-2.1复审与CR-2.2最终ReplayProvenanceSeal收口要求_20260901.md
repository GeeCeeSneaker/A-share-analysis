# A-share-analysis：CR-2.1 复审与 CR-2.2 最终 Replay / Provenance Seal 收口要求

> **Review Date**：2026-09-01 08:49 +08:00  
> **Reviewed Repository HEAD**：`70bb10172a203762193fe60093e9df5153efa6dc`  
> **Primary CR-2.1 Implementation**：`2bd0c31fa47c18b520c192265ce306f44a217fc3`  
> **Reviewer Baseline / Requirements**：`730657f42df6d62e4cdb432d90ea17e3dc7d4598`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-2.1 已正确部分**：**大部分 PASS / FREEZE**  
> **Next Batch**：**CR-2.2 Final Surface Provenance + Historical Exact Replay + Full Seal Consumption**  
> **CR-3**：**BLOCKED_BY_CR-2.2**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-2.1 对上一轮四个 blocker 做了实质修复，不是表面改名。以下内容本轮正式 **PASS / FREEZE**，CR-2.2 不得推倒重写：

```text
PASS / FREEZE  stock daily_bar 与 index_daily 已有独立 production wrapper
PASS / FREEZE  Raw meta 已持久化 normalization_surface 字段
PASS / FREEZE  registry key 已升级为 provider + surface + dataset + endpoint
PASS / FREEZE  legacy ambiguous raw 无 surface 时 fail closed
PASS / FREEZE  index_daily 已真实接入 map_index_daily_row / IndexDailyDTO
PASS / FREEZE  optional provider surfaces 显式 NOT_APPLICABLE
PASS / FREEZE  公开 DATASET_NORMALIZATION_REGISTRY 已撤销
PASS / FREEZE  production registry 采用 private tuple + private index
PASS / FREEZE  NormalizationRunner API 无 mapper/spec/registry/surface/code_commit 注入参数
PASS / FREEZE  SUCCESS / PARTIAL / BLOCKED 开始共用 replay verification 框架
PASS / FREEZE  output parquet -> manifest LAST 的文件侧可恢复协议
PASS / FREEZE  run ledger + quarantine exact set 单 DuckDB transaction
PASS / FREEZE  DB failure rollback + exact retry recovery
PASS / FREEZE  quarantine_set_hash 已持久化
PASS / FREEZE  manifest correctness bytes 去除 wall-clock
PASS / FREEZE  migration 015；旧 migration 未改写
PASS / FREEZE  既有 Raw-only / no-sentinel / no-silent-drop / row locator / provider-faithful 语义
PASS / FREEZE  current HEAD full CI 三腿 green
```

但 Reviewer 继续向 correctness identity 深挖后发现 **3 个 P0**。其中第 2 项存在明确的两次调用可复现 false-accept 路径，因此不能把 CR-2 交给 CR-3 消费。

正式状态：

```text
CR-2      DONE / REOPENED
CR-2.1    DONE / REOPENED（大量机制 PASS / FREEZE）
CR-2.2    START / ACTIVE NEXT
CR-3      BLOCKED_BY_CR-2.2
```

不重开 R4-B2/B1/A3/A2/CR-1 冻结链。

---

# 1. 已通过并冻结的 CR-2.1 修复

## 1.1 Stock / Index 双路由机制 —— PASS / FREEZE

当前 provider facade 已增加：

```text
query_kline_exchange
  -> require_capability=daily_bar
  -> normalization_surface=daily_bar

query_index_kline_exchange
  -> require_capability=index_daily
  -> normalization_surface=index_daily
```

两者共享：

```text
endpoint = MarketData.query_kline
provider_dataset = daily_bar
```

但 registry 通过四元 typed key 精确区分，并分别进入：

```text
daily_bar   -> map_daily_bar_row -> DailyBarDTO
index_daily -> map_index_daily_row -> IndexDailyDTO
```

legacy raw 若缺 `normalization_surface` 且 `(dataset, endpoint)` 多义，`PAYLOAD_SURFACE_AMBIGUOUS` BLOCKED，不按代码前缀/请求参数猜测。本方向冻结。

## 1.2 Immutable registry boundary —— PASS / FREEZE

公开 mutable dict 已撤销。当前 production declaration：

```text
_REGISTRY_SPECS private tuple
_REGISTRY_INDEX private exact index
lookup_spec / specs_for / registry_specs read-only consumption
```

Runner constructor/run signature没有 mapper/spec/registry/surface/code_commit。测试只能 monkeypatch private module state，不构成普通 production callable 注入面。符合上一轮 P0-02，冻结。

## 1.3 Recoverable commit closure —— PASS / FREEZE

文件侧：

```text
output artifact(s)
-> manifest anchor LAST
```

manifest correctness bytes不含 wall-clock，所以 DB 短暂失败后 exact retry 可生成 byte-identical manifest。

数据库侧：

```text
BEGIN
 -> duplicate guard
 -> run ledger INSERT
 -> full quarantine set INSERT
 -> persisted quarantine count assertion
COMMIT
```

失败 rollback。测试覆盖 run INSERT failure、quarantine INSERT failure、多输出中途失败及 retry recovery。该机制方向正确，冻结。

## 1.4 CI —— PASS

Current HEAD `70bb10172a203762193fe60093e9df5153efa6dc`：GitHub Actions run `33399858212` **success**。

- Ubuntu Python 3.14：success
- Windows Python 3.14：success
- Windows Python 3.12：success
- Ruff lint / format：success
- Mypy：success
- Pytest：success
- Spike framework gates：success

本轮 REOPEN 仍是 correctness contract，不是 CI blocker。

---

# 2. P0-01：`normalization_surface` 仍有正常 production callable 的 caller override 路径

## 2.1 当前代码

`AmazingDataProvider.call_exchange(...)` 当前公开参数仍包含：

```python
normalization_surface: str | None = None
```

并使用：

```python
surface_identity = str(normalization_surface or require_capability or "")
```

这意味着 surface 虽然在正常 wrapper 中传的是常量，但**低层 production callable 仍允许 caller 自行声明 surface**。

例如语义上可以形成：

```text
require_capability = daily_bar
endpoint = MarketData.query_kline
dataset = daily_bar
normalization_surface = index_daily
```

Raw meta 随后会把 `index_daily` 当成正式 persisted surface。

而 `map_index_daily_row()` 接受 `INDEX_CODE` **或 `SECURITY_CODE`** 作为 index_code，因此普通股票 daily-bar row 若被错误标成 `index_daily`，并不保证 mapper 会因 shape 自动失败；它可能成功生成 IndexDailyDTO。

所以当前 surface identity 的**路由机制**正确，但 provenance 仍不是严格 system-derived。

## 2.2 Required closure

推荐直接收口为：

```text
call_exchange 不接受 caller normalization_surface
surface identity = provider-owned wrapper/capability contract 派生
```

最简单且符合当前语义的实现：

```text
surface_identity = require_capability
```

对 ambiguous query_kline：

```text
query_kline_exchange       -> require_capability=daily_bar
query_index_kline_exchange -> require_capability=index_daily
```

已经足够区分，不需要额外 public override 参数。

若未来存在 `surface != capability` 的合法场景，应建立 production-owned static mapping，而不是恢复 caller string override。

必须增加结构测试：

```text
AmazingDataProvider.call_exchange signature 不含 normalization_surface override
stock/index wrapper 只能通过 provider-owned capability/surface mapping 产生不同 surface
低层 caller 无法用 daily_bar capability 写出 index_daily surface
```

本要求不是防御 Python interpreter 级 monkeypatch，而是与 B1/B2 一致：**普通 production callable 不能让 caller 自报 correctness identity**。

---

# 3. P0-02：`latest run` 被当作 raw-evidence 基线，存在“篡改 BLOCK 一次后第二次被洗白”的 false accept

## 3.1 当前 prior lookup

`NormalizationRunner.run()` 开头查询：

```sql
SELECT normalization_run_id, raw_evidence_hash, idempotency_key
FROM meta_provider_normalization_run
WHERE provider=? AND provider_dataset=? AND raw_request_id=?
ORDER BY started_at DESC
LIMIT 1
```

然后只把**最新一条 run**的 `raw_evidence_hash` 与当前 raw meta bytes hash 比较。

若不同：

```text
当前执行 -> RAW_EVIDENCE_INVALID BLOCKED
```

但这个 BLOCKED run 本身又被写入 `meta_provider_normalization_run`，并绑定**新的 current raw hash**。

## 3.2 可复现 false-accept 路径

假设已有正常成功 run：

```text
raw request R
meta hash = H1
surface = daily_bar
-> SUCCESS run A
```

外部随后改 raw meta，但保持 payload table hash 声明仍正确，例如只把：

```text
normalization_surface: daily_bar -> index_daily
```

此时 meta bytes hash = H2，payload closure 仍可能自洽。

### 第一次再运行

```text
latest run = A / H1
current raw = H2
H1 != H2
-> RAW_EVIDENCE_INVALID BLOCKED run B
```

B 被写入 ledger，绑定 H2。

### 第二次再运行

```text
latest run = B / H2
current raw = H2
-> hash conflict check 不再触发
-> parse modified meta(surface=index_daily)
-> verify_meta_closure 仍可能 PASS
-> route index_daily
-> map_index_daily_row
-> 可产生 SUCCESS
```

也就是说：

```text
篡改 raw evidence
-> 第一次被发现
-> 发现记录本身成为新的“最新基线”
-> 第二次反而可能接受篡改后的 evidence
```

这是明确 correctness blocker。

## 3.3 同一 latest-only 逻辑还破坏历史 exact replay

另一个正常工程场景：

```text
mapper code A -> run A
mapper code B -> run B
代码 rollback 到 mapper code A
```

此时 exact run A 明明已经存在，但 latest run 是 B。

当前：

```text
latest key B != current key A
-> 不 replay A
-> 按 deterministic run id A 再执行
-> _commit_ledger 发现 run A 已存在
-> duplicate execution error
```

因此“同一 exact input identity 能找到历史对应 run 并安全 replay”尚未成立。

## 3.4 Required closure

必须把两种概念分开：

### A. Raw request immutable evidence binding

同一 `(provider, provider_dataset, raw_request_id)` 一旦已有可信 normalization lineage，其 raw evidence hash 不得因新增一个 BLOCKED run 就改变基线。

可以选择：

```text
Option A（推荐）
查询该 request 的历史 distinct raw_evidence_hash：
  current hash 与既有可信 raw binding 不一致 -> INCIDENT HARD BLOCK
  不把冲突 hash 写成下一次可接受的新 baseline

Option B
增加独立 immutable raw-request binding / incident surface
```

关键不变量：

```text
raw hash conflict 的 BLOCK 记录不能成为下一次新的 evidence truth
```

### B. Exact replay lookup

在计算出 current exact idempotency key 后，应：

```text
lookup exact idempotency_key / deterministic run_id across full history
-> found -> verify exact closure -> replay
-> not found -> new run
```

不能使用“latest run key 是否相同”替代 exact historical lookup。

必须支持：

```text
A -> B -> A rollback
current A 能找到历史 run A 并 replay
```

## 3.5 Mandatory tests

至少新增：

```text
1. SUCCESS H1 -> raw meta 改为 H2（payload closure 仍自洽）
   -> 第一次 BLOCK
   -> 第二次仍 BLOCK
   -> 第三次仍 BLOCK；永不把 H2 洗成可信 baseline

2. 特别测试：daily_bar meta surface 被改成 index_daily
   -> repeated run 永远不能产出 IndexDaily SUCCESS

3. H1 SUCCESS -> H2 conflict BLOCK -> raw 修复回 H1
   -> 能找到并 replay 原 H1 exact run

4. mapper A -> mapper B -> rollback A
   -> replay 历史 A，不 duplicate-PK error

5. contract A -> contract B -> rollback A（可通过 monkeypatch contract identity 测）
   -> exact historical replay 语义一致
```

---

# 4. P0-03：Replay seal 写得比实际消费得多；full mapper hash 未进入 exact identity

## 4.1 mapper full code hash 被截断后才进入 idempotency identity

当前：

```python
MAPPER_CODE_FINGERPRINT = full SHA-256
```

但：

```python
mapper_identity_for(spec)
  -> ...#{MAPPER_CODE_FINGERPRINT[:16]}
```

而 `_supported_key()` 只 hash：

```text
raw_evidence_hash
NORMALIZATION_CONTRACT_VERSION
mapper_identity
```

因此 exact run identity 实际只消费 mapper SHA-256 的前 **16 hex chars（64 bit）**。

ledger/manifest 虽然另外保存 full `mapper_code_hash`，但 replay 当前没有把 full hash 与 current fingerprint 做强制比较。

对于 correctness identity，本项目之前已经明确采用 full SHA-256，不应重新引入截断 identity。

Required：

```text
idempotency key 直接包含 full MAPPER_CODE_FINGERPRINT
```

显示字符串可缩短，但 correctness hash input 不得缩短。

必须测试：

```text
两个 mapper fingerprint 前16位完全相同、后48位不同
-> 必须产生不同 exact run identity
```

## 4.2 manifest / ledger / current cross-binding 不完整

`_verify_manifest_outputs()` 当前只交叉比对：

```text
normalization_run_id
raw_request_id
raw_evidence_hash
normalization_contract_version
mapper_identity
quarantined_count
```

但 manifest 实际还写入且 correctness path 后续可能消费：

```text
provider
normalization_surface
provider_dataset
endpoint
mapper_code_hash
quarantine_set_hash
input_count
normalized_count
status
```

这些目前没有完整 ledger <-> manifest <-> current contract cross-check。

### 特别重要：quarantine_set_hash

当前 `_verify_quarantine_set()`：

```text
persisted quarantine DB exact set
-> recompute hash
-> compare ledger.quarantine_set_hash
```

但没有进一步检查：

```text
manifest.quarantine_set_hash == ledger.quarantine_set_hash
```

所以“quarantine seal 双锚定 manifest + ledger”目前是**写入了两个位置，但 replay 未完整消费二者绑定**。

这与之前 B2 的“seal written but not consumed”属于同类问题。

## 4.3 SUCCESS/PARTIAL manifest-required invariant 未在 replay 入口强制

`_verify_run_closure()` 当前逻辑：

```text
always verify quarantine set
if normalized_manifest_uri is not None:
    verify manifest outputs
```

因此如果 ledger 状态/字段被破坏成：

```text
status = SUCCESS
normalized_manifest_uri = NULL
```

manifest verification 会被直接跳过；随后 replay result 使用 ledger.status 返回。

至少必须机器强制：

```text
SUCCESS / PARTIAL -> manifest_uri/hash REQUIRED
```

BLOCKED 是否允许无 manifest，应按 typed cause/scope policy 明确；例如：

```text
source exchange failed / unsupported surface -> no normalized manifest 合法
row-scope mapping BLOCKED 且写了 empty-output evidence -> manifest 必须保持并重验
```

## 4.4 Output schema seal 未重算

manifest 为每个 output 写了：

```text
content_hash
schema_hash
row_count
```

replay 当前重验：

```text
content_hash
row_count
```

但没有重新计算 physical parquet schema hash 与 manifest `schema_hash` 比较。

CR-2 原工作要求明确把 schema hash 放进 persisted artifact identity；replay closure 应实际消费。

## 4.5 Required full replay seal

建议抽象一个 typed `NormalizationRunSeal` / verifier，至少机器验证：

```text
CURRENT contract version
CURRENT full mapper code fingerprint
CURRENT exact surface spec

== ledger
== manifest
```

交叉绑定至少：

```text
provider
normalization_surface
provider_dataset
endpoint
raw_request_id
raw_evidence_uri/hash
normalization_contract_version
mapper_identity
FULL mapper_code_hash
status
input_count
normalized_count
quarantined_count
quarantine_set_hash
```

并验证：

```text
manifest bytes hash == ledger manifest hash
quarantine DB exact-set hash == ledger == manifest
output exact declared files exist
content_hash recompute
schema_hash recompute
row_count recompute
```

manifest-required policy按 run status/cause fail closed。

## 4.6 Mandatory tamper tests

这些测试应**重新绑定 manifest_hash**后再验证，以证明不是只有外层文件 hash 在工作：

```text
6. manifest normalization_surface 改错 + 重新写 ledger manifest_hash -> replay BLOCK
7. manifest status 改 PASS/其他 + rebind -> BLOCK
8. ledger status 从 BLOCKED 改 SUCCESS，仍无 manifest -> BLOCK
9. manifest input_count/normalized_count 改错 + rebind -> BLOCK
10. manifest quarantine_set_hash 改错 + rebind -> BLOCK
11. ledger quarantine_set_hash 与 manifest 不一致 -> BLOCK
12. ledger full mapper_code_hash 与 current / manifest 不一致 -> BLOCK
13. manifest full mapper_code_hash 与 current 不一致 + rebind -> BLOCK
14. physical parquet schema / manifest schema_hash 不一致 -> BLOCK
15. same first16 mapper hash, different remaining bits -> new run identity
```

---

# 5. CR-2.2 Scope Boundary

CR-2.2 只允许修复：

```text
provider normalization_surface provenance boundary
raw-request evidence-hash conflict permanence / incident behavior
historical exact replay lookup
full mapper identity
normalization replay seal consumption
related migration/tests/ADR-022 amendment/governance sync
```

不得启动：

```text
AvailabilityPolicy
SourcePolicy reconciliation
cross-provider Canonical selection
SnapshotBuilder
Feature / State
```

不重做已经 PASS/FREEZE 的 CR-2.1 registry、commit protocol、quarantine locator/no-sentinel/provider-faithful 机制。

---

# 6. CR-2.2 Exit Gate

只有以下全部成立，才允许 CR-2 CLOSED -> CR-3 START：

```text
[ ] normalization_surface cannot be overridden by ordinary production caller
[ ] surface is derived from provider-owned capability/business-surface contract
[ ] stock/index exact routing remains green
[ ] legacy ambiguous raw remains fail closed
[ ] raw evidence hash conflict can never become the next accepted baseline
[ ] repeated runs over conflicting/tampered raw remain blocked
[ ] repaired original raw can replay the original exact historical run
[ ] exact replay lookup searches by exact idempotency identity, not latest-run equality
[ ] mapper A -> B -> A rollback replays historical A
[ ] full mapper SHA-256 enters correctness/idempotency identity
[ ] ledger / manifest / current surface+contract+mapper full seal cross-bound
[ ] quarantine_set_hash recomputes DB exact set and matches BOTH ledger and manifest
[ ] SUCCESS/PARTIAL manifest-required invariant enforced
[ ] output content/schema/row-count all physically reverified
[ ] rebind-style adversarial tamper tests block
[ ] CR-2.1 atomic/recovery + immutable registry tests remain green
[ ] existing no-sentinel/no-silent-drop/locator/provider-faithful tests remain green
[ ] migrations from-zero/upgrade green if schema changes
[ ] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green
[ ] ADR-022 remains PROPOSED until Reviewer closure
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT current truth synced
```

完成后：

```text
CR-2 / CR-2.1 / CR-2.2 -> VERIFIED / CLOSED / FREEZE
ADR-022 -> ACCEPTED
CR-3 AvailabilityPolicy + Canonicalizer -> START
```

---

# 7. 治理同步要求

下一开发提交必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
ADR-022 Amendment B（或等价 amendment）
本 Reviewer 文档 Implementation Mapping
```

状态：

```text
R4-B2.x               CLOSED / VERIFIED / FREEZE
CR-2                   DONE / REOPENED
CR-2.1                 DONE / REOPENED（大量机制 FREEZE）
CR-2.2                 ACTIVE / NEXT
CR-3                   BLOCKED_BY_CR-2.2
Production P0-M-1B     BLOCKED independently
```

不得将 ADR-022 自行改成 ACCEPTED；只有 Reviewer 确认 CR-2.2 Exit Gate 全过后同步 ACCEPTED。

---

# 8. 面向项目 Owner 的中文工程进度

## 8.1 一句话状态

CR-2.1 已经把“股票/指数走错 mapper、规则表可随便替换、数据库半提交”等大问题基本解决；现在剩下的是更底层的**可信重放**问题：系统必须保证“一次发现 Raw 被改过，不能因为记录了一次 BLOCK 就把被改后的版本洗成新基线”，并且重用历史结果前必须把业务身份、mapper 完整版本、状态、数量、隔离集合和输出 schema 全部重新核实。

## 8.2 当前功能完成度

```text
Raw 原始数据可靠保存                    ✅ 已闭环
Provider 接口/权限/审批验证              ✅ 已闭环
发布前数据安全检查                      ✅ 已闭环
Raw -> Provider-Normalized 主流程        ✅ 主体完成
坏数据自动隔离                          ✅ 主体完成
坏行精确定位                            ✅ 已完成
禁止关键字段 sentinel                   ✅ 已完成
输入行 no-silent-drop                    ✅ 已完成
Provider-faithful                        ✅ 已完成
股票/指数双 mapper 路由                  ✅ 已完成机制
公开 mutable registry 注入面             ✅ 已关闭
文件 + DB + quarantine 可恢复提交         ✅ 已完成机制

surface provenance 普通 caller 不可伪造   🔧 待最后收口
Raw tamper 不可被 BLOCK 记录洗白          🔧 待最后收口
历史 exact run 任意版本可正确找到/replay  🔧 待最后收口
full mapper hash exact identity           🔧 待最后收口
manifest/ledger/current 全量 seal 消费     🔧 待最后收口

CR-3 Canonical Runtime                    ⏸ 等 CR-2.2
```

## 8.3 当前工程阶段图

```text
A股市场态势数据基座
│
├─ ① 原始数据证据层
│    ✅ 已完成 / 冻结
│
├─ ② 数据供应商能力验证
│    ✅ 已完成 / 冻结
│
├─ ③ 发布安全检查
│    ✅ 已完成 / 冻结
│
├─ ④ 原始数据标准化 + 坏数据隔离
│    🟡 已完成绝大部分，仍需 CR-2.2 最终可信重放收口
│    │
│    ├─ ✅ Raw -> Provider-Normalized
│    ├─ ✅ 坏行 -> Quarantine
│    ├─ ✅ 坏行可定位原始 request/table/row
│    ├─ ✅ 股票 / 指数同接口不同 mapper 已区分
│    ├─ ✅ registry 普通调用面不可替换 mapper
│    ├─ ✅ 文件 + DB + quarantine 故障可恢复
│    │
│    └─ 🔧 CR-2.2
│         ├─ surface 必须真正 system-derived，不能 caller override
│         ├─ Raw 一旦发生 hash 冲突不能被“下一次”洗白
│         ├─ 历史 exact run 按 identity 查找，不只看 latest
│         └─ manifest / ledger / mapper / quarantine / schema 全 seal 重验
│
├─ ⑤ 系统统一标准数据 Canonical
│    ⏸ CR-3 等待 CR-2.2
│
├─ ⑥ Snapshot / Read Model
│    ⏸ CR-4 等待 CR-3
│
└─ ⑦ 正式生产闭环
     ⛔ 正式账号 + Golden / Trading Rule 人工复核仍未满足
```

## 8.4 关键指标工程闭环度

```text
原始证据可追溯性                 ██████████ 100%
原始证据防篡改/基础重放           ██████████ 100%
Provider 能力/审批安全             ██████████ 100%
发布前数据安全                     ██████████ 100%
坏数据发现与精确定位               █████████░ 约95%
Raw -> Provider 标准化             █████████░ 约90%
股票/指数业务路由正确性            █████████░ 约90%（路由完成，provenance 待封口）
标准化提交故障恢复                 █████████░ 约90%
标准化 exact replay 可信度          ███████░░░ 约70%（latest-baseline / seal consumption 待补）
跨 Provider Canonical 统一          ░░░░░░░░░░ 0%（尚未启动）
Snapshot / ReadModel                ░░░░░░░░░░ 0%（尚未启动）
正式生产可用                        ░░░░░░░░░░ 尚未进入
```

条形图表示能力的工程闭环程度，不等同精确工时/代码量百分比。
