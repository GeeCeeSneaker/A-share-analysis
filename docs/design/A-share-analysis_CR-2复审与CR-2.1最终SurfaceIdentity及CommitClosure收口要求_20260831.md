# A-share-analysis：CR-2 复审与 CR-2.1 最终 Surface Identity / Registry Boundary / Replay / Commit Closure 收口要求

> **Review Date**：2026-08-31 17:42 +08:00  
> **Reviewed Repository HEAD**：`ab20871e9eb207563d0fdeb6228a08416153e2c9`  
> **Primary CR-2 Implementation（GitHub canonical SHA）**：`15cdae25fd7d11e3be0da3683e821629e4226291`  
> **Reviewer Baseline / Requirements**：`a41c9f253dc58c012d787453ba4078bc518474af`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-2.0 core framework**：**大部分 PASS / FREEZE**  
> **Next Batch**：**CR-2.1 Final Normalization Surface Identity + Immutable Registry + Full-State Replay + Atomic Commit Closure**  
> **CR-3**：**BLOCKED_BY_CR-2.1**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-2 本批不是空壳实现。Reviewer 已确认以下主框架是真实落地的，并在 CR-2.1 中 **FREEZE，不得推倒重写**：

```text
PASS / FREEZE  normalization 正式入口只消费 persisted Raw evidence
PASS / FREEZE  verify_meta_closure + RawWriter.read(verify=True) 复用
PASS / FREEZE  provider failure 与 MappingValidationError 分离
PASS / FREEZE  required field invalid 不用 sentinel 伪装
PASS / FREEZE  ROW quarantine 有 raw request/table/row ordinal locator
PASS / FREEZE  WHOLE_PAYLOAD calendar quarantine 语义
PASS / FREEZE  row disposition 记账机制（mapped source rows + quarantined source rows）
PASS / FREEZE  Provider-Normalized 主输出落 immutable parquet + manifest
PASS / FREEZE  logical-URI confinement
PASS / FREEZE  provider-faithful mapper 方向（不提前做 CR-3 canonical）
PASS / FREEZE  SUCCESS / PARTIAL / BLOCKED 状态类型框架
PASS / FREEZE  migration 014 from-zero 链存在；旧 migration 不改
PASS / FREEZE  full CI current HEAD 绿
```

但本轮发现 4 个 P0 correctness blockers，均可由当前代码结构直接推出/复现：

1. `daily_bar` 与 `index_daily` 的 Raw surface identity 冲突，现有 `(provider_dataset, endpoint)` 两元路由无法区分；`index_daily` 已有 mapper/DTO 却未进入 registry，可能被错误路由成股票日线。
2. 所谓 static registry 实际是公开导出的可变 `dict`，普通调用方可替换 mapper spec，NormalizationRunner 会执行被注入的 mapper。
3. idempotency 只在 supported happy path 的既有 run 上早返回；BLOCKED/failed/unsupported 等终态重跑会再次 INSERT 同一确定性 PK；而 SUCCESS 早返回又不重验 manifest/parquet/quarantine 完整性。idempotency key 也未绑定一个不可由 caller 自报的真实 mapper code identity。
4. normalized files / manifest / run ledger / quarantine rows 之间没有可恢复的统一 commit protocol；文件先落最终路径，DB run + quarantine 又逐语句提交，存在 orphan files、半提交 quarantine，以及重试 manifest bytes conflict。Quarantine 集合也没有被 run manifest/hash 精确封存。

因此：

```text
CR-2      DONE / REOPENED
CR-2.1    START / ACTIVE NEXT
CR-3      BLOCKED_BY_CR-2.1
```

除上述 P0/P1 外，不重开 R4-B2/B1/A3/A2/CR-1 冻结链。

---

# 1. 已正确实现并冻结的 CR-2 基础

## 1.1 Raw evidence sole input —— PASS / FREEZE

`NormalizationRunner` 从 raw `.meta.json` 开始，先做 closure verification，再调用现有 `RawWriter.read(verify=True)`；runner package 不重新调用 SDK/provider。失败 exchange 以 `SOURCE_EXCHANGE_FAILED` 记录 BLOCKED run，不伪装成 mapping quarantine。

本方向符合 CR2-P0-01，冻结。

## 1.2 No sentinel / Quarantine locator —— PASS / FREEZE

现有 mapper 对 REQUIRED 字段 missing/unparsable 抛 `MappingValidationError`；runner 将坏行持久化到 quarantine，记录：

```text
raw_request_id
raw_table_name
raw_row_ordinal
source_key (best effort)
error class/message/context
mapper identity / contract
```

`trade_calendar` 一个非法日期触发 whole-payload quarantine + zero normalized output。以上语义保留。

## 1.3 Provider-faithful boundary —— PASS / FREEZE

DailyBar provider unit/literal、industry taxonomy `GALAXY_UNVERIFIED`、status 三投影均仍保持 Provider-Normalized 层语义，没有提前做 AvailabilityPolicy / SourcePolicy / Canonical selection。CR-2.1 不得借修复之名启动 CR-3。

## 1.4 CI —— PASS

- CR-2 implementation run `33378006770`：**success**；GitHub head SHA = `15cdae25fd7d11e3be0da3683e821629e4226291`。
- current reviewed HEAD `ab20871e9eb207563d0fdeb6228a08416153e2c9` run `33378447083`：**success**。
- Ubuntu Python 3.14 / Windows Python 3.12 / Windows Python 3.14：均 success。
- Ruff lint / format / Mypy / Pytest / Spike gates：均 success。

所以本轮 REOPEN 不是 CI blocker，而是 contract correctness 缺口尚未进入现有 907-test green matrix。

---

# 2. P0-01：Normalization Surface Identity 不充分，`index_daily` 与 `daily_bar` 冲突

## 2.1 当前冲突

B1 冻结 endpoint contract 已明确：

```text
daily_bar
  -> MarketData.query_kline
  -> provider_dataset = daily_bar

index_daily
  -> MarketData.query_kline
  -> provider_dataset = daily_bar
```

即两种**不同业务 surface**共享同一个 provider endpoint + provider dataset。

但 CR-2 registry 当前 key 仅为：

```text
(provider_dataset, endpoint)
```

因此：

```text
("daily_bar", "MarketData.query_kline")
```

只能有一个 registry entry。现在它绑定的是：

```text
map_daily_bar_row -> DailyBarDTO
```

而仓库已有：

```text
map_index_daily_row -> IndexDailyDTO
IndexDailyDTO.return_type = UNVERIFIED
```

却没有任何 CR-2 registry route。

这不是“index_daily 诚实 BLOCKED”，而是存在**误路由为 daily_bar**的可能。

## 2.2 为什么现有 structural guard 没发现

当前测试只 AST 扫描 `provider.py` 中 `_call_or_exchange(endpoint, dataset, ...)`，要求 registry exact 覆盖这些二元 pair。

但：

- `provider.py` 只有一个 `query_kline_exchange` wrapper，且固定 `require_capability="daily_bar"`；
- B1 的 `index_daily` capability requirement 存在于 `endpoint_requirements.py`，不是一个独立 `(dataset, endpoint)` pair；
- 因此“provider facade 14 pair exact coverage”并不等价于“所有 capability/mapper surface exact coverage”。

Reviewer 原 CR2-P0-02 明确要求 `index_daily` 必须显式 routing；本项未满足。

## 2.3 CR-2.1 必须修复

需要一个**持久化、system-derived 的 normalization surface identity**，不能靠 request 参数猜。

推荐 Option A：

```text
RawEnvelope / raw meta
  + normalization_surface (或 capability / business_surface)

provider wrapper
  -> system-derived surface identity
  -> RawWriter persists exact surface identity

Normalization registry key
  -> (provider, normalization_surface, provider_dataset, endpoint)
     或等价不可歧义 typed key
```

对 query_kline 至少建立两个显式 production wrapper/surface：

```text
stock daily_bar     -> DailyBarDTO mapper
index daily_bar     -> IndexDailyDTO mapper
```

若底层 SDK endpoint/dataset 相同，也必须由上层明确业务 surface 区分。

**禁止**：

```text
if code looks like index then guess index_daily
if request_params contains XXX then猜
靠 symbol 前缀/长度/列表内容推断业务 surface
```

legacy raw evidence 若缺少足以客观区分的 surface identity，而该 endpoint 存在歧义，应 `PAYLOAD_SURFACE_AMBIGUOUS / BLOCKED`，不得猜测。

## 2.4 Coverage guard 必须升级

结构守卫不能只看 `provider.py` 二元 pair。至少 cross-check：

```text
provider facade exchange surfaces
+ ENDPOINT_REQUIREMENTS / SDK_METHOD_CLASSIFICATIONS
+ current provider mapper/DTO supported surfaces
+ DATASET_NORMALIZATION_REGISTRY
```

每个 surface 必须显式属于：

```text
SUPPORTED_NORMALIZATION
BLOCKED_PENDING_MAPPER
NOT_APPLICABLE
```

特别要求明确：

```text
index_daily
InfoData.get_index_daily (optional SDK surface)
industry_weight / industry_daily (optional surface)
```

若当前不消费，应 `NOT_APPLICABLE`，而不是从 structural truth 中消失。

---

# 3. P0-02：Static Registry 仍可由 caller 直接注入 mapper

当前：

```python
DATASET_NORMALIZATION_REGISTRY: dict[...] = ...
```

并在 `__all__` 中公开导出。`DatasetNormalizationSpec` 也可直接构造。

现有测试本身演示：

```text
construct evil DatasetNormalizationSpec
-> DATASET_NORMALIZATION_REGISTRY[(daily_bar, query_kline)] = evil spec
-> NormalizationRunner.run()
-> 正式 runner 执行 evil mapper
```

测试用 monkeypatch 可以存在，但**生产正常调用面不应提供一个公开可变 dict 作为 truth**。

## 3.1 Required closure

生产 registry 应改为不可变 / private authoritative declaration，例如：

```text
private tuple/frozen specs
+ private exact index
+ read-only lookup_spec()
```

或等价 `MappingProxyType` + 不导出底层 mutable object。

要求：

- caller API 无法 add/replace/delete production spec；
- caller 无法向 `NormalizationRunner.run()` 传 mapper/spec/registry；
- test-only injection 必须使用 monkeypatch 私有 module state 或 tests-only helper，不成为生产 API；
- structural test 检查没有公开 mutable registry object 被 runner 作为 truth 消费。

不要求把 Python 解释器级 monkeypatch 防到绝对不可能；目标与 B2 scanner static registry 一致：**正常 production callable / exported mutable object 不能成为注入路径**。

---

# 4. P0-03：Deterministic Replay / Idempotency 只覆盖 happy path，且旧输出不重验

## 4.1 BLOCKED/failed surface 重放不是幂等

当前 prior lookup 在前，但 exact idempotent early-return 只发生在：

```text
registry lookup成功且 SUPPORTED
-> compute mapper_identity + idempotency_key
-> prior key match -> return
```

以下路径在此之前就调用 `_blocked_run()`：

```text
SOURCE_EXCHANGE_FAILED
BLOCKED_PENDING_MAPPER
unknown / NOT_APPLICABLE surface
raw closure invalid
```

`_blocked_run()` 又用 deterministic uuid5 产生同一个 `normalization_run_id`，然后直接 INSERT。

所以同一份 blocked evidence 第二次 `run()` 会尝试重复插入同一 primary key，而不是 idempotent no-op。

## 4.2 SUCCESS/PARTIAL early-return 不重验既有输出

supported prior key 命中后，runner 当前直接从 DB 取 run summary 返回；没有在 return 前验证：

```text
normalized_manifest_uri exists
manifest bytes hash == ledger normalized_manifest_hash
manifest run/raw/contract/mapper identity == ledger/current
manifest outputs all exist
output bytes hash/schema/row-count == manifest
quarantine count/set identity intact
```

因此：

```text
run SUCCESS
-> normalized parquet 被删除/篡改
-> rerun same raw
-> 仍返回 idempotent_replay=True
```

这是 false healthy replay。

## 4.3 mapper code identity 也必须进入 exact run identity

原要求是：

```text
raw evidence bytes
+ normalization contract version
+ mapper code identity
```

当前 idempotency key 只使用：

```text
raw_evidence_hash
NORMALIZATION_CONTRACT_VERSION
mapper_identity = dataset/endpoint@mapper_version
```

`NormalizationRunner(code_commit=...)` 的 `code_commit` 是 caller 输入，只被写进 manifest，不参与 idempotency key，也不是 system-derived correctness identity。

CR-2.1 必须选择一种可靠方案：

```text
A. system/build-derived code_commit / build identity
B. governed mapper implementation hash
C. contract hash + mapper implementation identity 的等价机器证明
```

并进入 idempotency / manifest exact identity。不能仅依赖开发者“记得手工 bump mapper_version”。

## 4.4 Required replay contract

SUCCESS / PARTIAL / BLOCKED 全部必须有统一 exact replay policy：

```text
same exact input identity
-> verify existing result closure
-> intact => idempotent return, zero duplicate rows/files
-> damaged/tampered => hard fail closed / repair-required
```

如果 mapper/contract identity变化，则应产生**新的 normalization run identity**，历史 run 保留，不覆盖。

---

# 5. P0-04：文件 / Manifest / Run Ledger / Quarantine 没有 Atomic + Recoverable Commit Closure

## 5.1 当前写入顺序存在半提交

当前成功/partial path：

```text
write output parquet(s) to FINAL paths
write manifest.json to FINAL path
INSERT meta_provider_normalization_run
for quarantine:
    INSERT meta_provider_quarantine one by one
```

没有一个统一 DB transaction，也没有 staging + final anchor recovery protocol。

### Failure A：manifest 已写，run ledger INSERT 失败

下次重试会重新生成 manifest；当前 manifest 包含 wall-clock `completed_at`，所以同一个 deterministic URI 下 bytes 会不同：

```text
existing manifest != retry manifest
-> _write_immutable conflict
```

于是一次 DB 短暂失败可以把 exact run 卡成不可恢复的 orphan manifest。

### Failure B：run row 已写，quarantine INSERT 中途失败

DuckDB 默认逐语句提交；没有 BEGIN/ROLLBACK 包住 run + quarantine set。

可能得到：

```text
meta_provider_normalization_run.quarantined_count = N
但 meta_provider_quarantine 实际只有 K < N
```

此时 ledger summary 与 evidence 不一致。

### Failure C：multi-output artifact 写一半

history_stock_status 有 3 个输出。若第二/第三个输出写失败，前面的 final-path parquet 已存在但没有完整 anchor。需要明确 recovery，而不能把 orphan file 当正常输出。

## 5.2 Quarantine 还没有 exact immutable set seal

migration 014 的 quarantine 是普通 DB 行；run manifest 只记录 `quarantined_count`，没有：

```text
quarantine artifact/set hash
exact quarantine record set identity
```

因此后续 UPDATE/DELETE/缺行无法由 run manifest 自身发现。

原 CR2-P0-03 要求 run manifest/ledger 至少绑定 quarantine artifact uri/hash/count；P0-05 要求 quarantine immutable/append-only。本项目前未完整满足。

## 5.3 Required closure

推荐采用与 RawWriter 已验证模式一致的思想，但允许实现形式调整：

```text
1. derive exact deterministic run identity
2. build normalized outputs + deterministic quarantine-set evidence in staging
3. build deterministic correctness manifest
   - correctness bytes 不含 wall-clock completed_at，或把时间移出 correctness hash
4. atomically move data artifacts
5. write final manifest anchor LAST（file side）
6. BEGIN DB TRANSACTION
     verify no conflicting run
     INSERT/UPSERT exact run ledger
     INSERT full quarantine set
     assert quarantine_count == exact persisted set count
   COMMIT
7. on DB failure -> rollback DB；file-side exact anchor 可由 retry/recovery 识别并完成 ledger reconciliation
```

也可采用 PENDING→FINAL 状态机，但必须给出 crash/retry semantics，满足：

```text
任何时点失败
-> 不会留下一个“看起来 SUCCESS/PARTIAL 但 evidence 不完整”的 run
-> retry exact input 能确定性恢复或明确 hard conflict
```

Quarantine 可以继续以 DB 可查询行存在，但必须额外形成 machine-verifiable exact set seal，例如：

```text
quarantine_set_hash = canonical hash(sorted quarantine semantic records)
```

并由 run manifest/ledger 绑定。也可以写 immutable `quarantine.json/parquet` artifact + hash；二选一或等价实现。

---

# 6. P1 治理真相更正

## P1-01 Implementation SHA 记录错误

GitHub canonical CR-2 implementation commit 是：

```text
15cdae25fd7d11e3be0da3683e821629e4226291
```

但 `DEVELOPMENT_MANAGEMENT.md` 和 Implementation Mapping 当前记录：

```text
15cdae2e4f1a9df3b7844480979a2f1cb2b2f464
```

该 SHA 不是真实 implementation commit。下一批按“历史不改写、追加 correction”原则更正；不要篡改历史 DEVLOG 原文。

## P1-02 ADR-022 surface count 文案错误

ADR-022 写：

```text
9 SUPPORTED / 5 BLOCKED_PENDING_MAPPER
```

但当前 registry 实际 14 条是：

```text
10 SUPPORTED
4 BLOCKED_PENDING_MAPPER
```

而更深层问题是该 14 条本身未覆盖 index_daily 等 capability surface（P0-01）。CR-2.1 修完 surface identity 后重新以 runtime exact-set 统计，ADR 不要再手工写错数字。

---

# 7. CR-2.1 必须新增的对抗测试

至少补齐：

```text
1. same MarketData.query_kline + provider_dataset=daily_bar:
   stock daily surface -> DailyBarDTO
   index daily surface -> IndexDailyDTO
   两者绝不碰撞/误路由

2. ambiguous legacy raw lacking surface identity
   -> fail closed, no guess-by-code/request-param

3. structural guard cross-check provider facade + endpoint requirements /
   SDK classifications + mapper/DTO surfaces + normalization registry

4. ordinary caller cannot mutate exported production registry and inject mapper

5. same BLOCKED_PENDING_MAPPER raw rerun -> idempotent, one run row
6. same SOURCE_EXCHANGE_FAILED raw rerun -> idempotent, one run row
7. same PARTIAL raw rerun -> idempotent, one run row / same quarantine set

8. SUCCESS output parquet tamper/delete -> rerun does NOT return healthy idempotent
9. manifest tamper/delete -> rerun blocks
10. quarantine set missing/tampered -> rerun blocks

11. injected ledger INSERT failure after file-side commit -> exact retry recovers
12. injected quarantine INSERT failure -> DB transaction rolls back; retry recovers
13. multi-output write failure -> no valid final anchor claiming complete run

14. mapper code identity changes with same raw+contract
    -> new run identity / no stale reuse

15. two clean environments at different wall-clock times:
    same raw + same contract + same mapper code identity
    -> same semantic/correctness manifest identity

16. current happy paths remain:
    no sentinel / row locator / calendar whole quarantine /
    provider-faithful / no silent drop / URI confinement

17. from-zero + upgrade migration green（如新增 schema 用 migration 015+，不得改 014）
18. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green
19. all R4-B2/B1/A3/A2/CR-1 frozen regressions green
```

---

# 8. CR-2.1 Scope Boundary

允许：

```text
RawEnvelope/meta 增加向后兼容的 system-derived normalization surface identity
AmazingData explicit business-surface wrapper（用于消除 query_kline 歧义）
normalization registry / runner
normalized/quarantine manifest/seal
migration 015+
CR-2 tests / ADR-022 amendment / governance sync
```

不允许：

```text
AvailabilityPolicy
SourcePolicy reconciliation
cross-provider Canonical selection
SnapshotBuilder
Feature / State
```

CR-2.1 仍是 Raw -> Provider-Normalized + Quarantine correctness closure。

---

# 9. CR-2.1 Exit Gate

只有以下全部通过，才允许 CR-2 CLOSED -> CR-3 START：

```text
[ ] ambiguous provider endpoint/dataset surfaces have exact persisted business-surface identity
[ ] index_daily and daily_bar exact routing both correct
[ ] legacy ambiguous raw fails closed
[ ] all capability/mapper/provider surfaces explicitly classified
[ ] production normalization registry is immutable from ordinary caller API
[ ] no caller mapper/spec injection path
[ ] SUCCESS/PARTIAL/BLOCKED all use one exact replay policy
[ ] existing run is re-verified before idempotent reuse
[ ] normalized manifest/output tamper or missing files fail closed
[ ] quarantine exact set is hash/seal bound and count-consistent
[ ] mapper code identity is system-derived and in exact run identity
[ ] file-side artifacts + manifest + DB run/quarantine have recoverable commit semantics
[ ] DB partial persistence cannot create false SUCCESS/PARTIAL
[ ] exact retry after injected failures recovers deterministically
[ ] existing no-sentinel / no-silent-drop / locator / provider-faithful semantics preserved
[ ] no CR-3 semantics leaked in
[ ] migration from-zero/upgrade green
[ ] full CI matrix green
[ ] governance SHA/count/status truth corrected
```

完成后：

```text
CR-2 / CR-2.1 -> VERIFIED / CLOSED / FREEZE
ADR-022 -> ACCEPTED
CR-3 AvailabilityPolicy + Canonicalizer -> START
```

---

# 10. Governance 同步

下一开发批次必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
ADR-022 amendment / status remains PROPOSED until Reviewer closure
```

状态写为：

```text
R4-B2.x          CLOSED / VERIFIED / FREEZE
CR-2             DONE / REOPENED
CR-2.1           ACTIVE / NEXT
CR-3             BLOCKED_BY_CR-2.1
Production P0-M-1B BLOCKED independently
```

本 Reviewer 不重写巨大 living document；本 focused reviewer document 是当前权威复审/下一步要求，下一开发提交负责把 current truth 合并回管理总册。

---

# 11. 面向项目 Owner 的中文工程进度

## 11.1 当前阶段一句话

系统现在已经能把大部分 Raw 原始数据转换为标准化 Provider 数据，并把坏行隔离出来；但在进入“统一 Canonical 数据层”之前，还要解决 4 个可靠性问题：**同接口不同业务不能走错 mapper、mapper 规则不能被普通调用方改写、所有成功/失败重跑都必须真正幂等、文件/数据库/隔离记录必须作为一整套结果原子提交并可恢复。**

## 11.2 功能实现情况

```text
Raw 原始证据可靠保存                 已完成
Provider 接口能力验证                已完成
发布前完整性 / DQ 检查               已完成
Raw -> Provider-Normalized 主流程     已实现主体
坏数据自动隔离                       已实现主体
坏行精确定位到 Raw 原始行            已实现
非法关键字段禁止 sentinel            已实现
输入行不允许 silent drop              已实现主体
Provider 单位/字面语义保持            已实现

不同业务 surface 精确路由            未完全完成（index_daily 冲突）
Normalization mapper 防外部注入       未完成
所有终态 deterministic replay         未完成
重放前 normalized 完整性复验          未完成
Quarantine exact set immutable seal    未完成
文件 + DB + quarantine 原子提交/恢复   未完成

CR-3 Canonical Runtime                 尚未启动（正确保持阻塞）
```

## 11.3 当前工程阶段图

```text
A股市场态势数据基座
│
├─ ① 原始数据证据层
│    ✅ 已完成：取到什么就保存什么，可验 hash、可重放
│
├─ ② 数据供应商能力验证
│    ✅ 已完成：账号/权限/精确接口/审批防绕过
│
├─ ③ 发布安全检查
│    ✅ 已完成：文件、数据质量、输入新鲜度、发布原子回滚
│
├─ ④ 原始数据标准化 + 坏数据隔离
│    🟡 主体已实现，CR-2 本轮复审 REOPENED
│    │
│    ├─ ✅ Raw -> Provider-Normalized
│    ├─ ✅ 坏行 -> Quarantine
│    ├─ ✅ 坏行可定位原始 request/table/row
│    ├─ ✅ 不用 1970/0.0 伪造坏数据
│    ├─ ✅ 正常/隔离 source-row 记账
│    │
│    └─ 🔧 CR-2.1 当前要收口
│         ├─ 不同业务不能误走同一个 mapper
│         ├─ mapper registry 不能被普通调用方替换
│         ├─ 成功/部分成功/失败都能安全重跑
│         └─ 文件、manifest、DB、隔离记录必须整体一致
│
├─ ⑤ 系统统一标准数据 Canonical
│    ⏸ CR-3 等待 CR-2.1
│
├─ ⑥ Snapshot / Read Model
│    ⏸ CR-4 等待 CR-3
│
└─ ⑦ 正式生产闭环
     ⛔ 正式账号 + Golden/Trading Rule 人工复核仍未满足
```

## 11.4 主要指标完成度（工程口径，不等同精确工时百分比）

```text
原始证据可追溯性             ██████████  已闭环
原始证据防篡改/重放           ██████████  已闭环
Provider 能力/审批安全         ██████████  已闭环
发布前数据安全                 ██████████  已闭环
坏数据发现与定位               ████████░░  主体完成，隔离 set seal 待补
Raw->Normalized 转换           ████████░░  主体完成，surface routing 待补
不静默丢 source row            █████████░  主体已机器检查
Normalization 幂等/可恢复      █████░░░░░  happy path 有，所有终态/故障恢复待补
跨 Provider Canonical 统一      ░░░░░░░░░░  尚未开始
Snapshot / ReadModel            ░░░░░░░░░░  尚未开始
正式生产可用                    ░░░░░░░░░░  仍受后续 runtime + 正式账号/人工复核阻塞
```

这里的条形图表示**该能力的工程闭环程度**，不是用代码行数计算的项目总百分比。