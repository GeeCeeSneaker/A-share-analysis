# A-share-analysis 第二轮代码审计与下一阶段开发要求

> 仓库：`GeeCeeSneaker/A-share-analysis`  
> 审计分支：`main`  
> 审计 HEAD：`99cca13cddd9f52f9d64c155495d652a339aa540`  
> 上轮审计 HEAD：`93ae53283e5697f53d052589f7f56a204d187909`  
> 整改提交：`cf81be3` / `fee655b` / `bfce563` / `0a5c704` / `99cca13`  
> 基线：`A股市场态势数据基座（日频模块）V1.3.2 Frozen Baseline`  
> 日期：2026-08-22  
> 性质：**整改复核 + 第二轮代码审计 + 下一阶段开发任务书**

---

# 0. 最终结论

上一轮整改总体是成功的，而且不是“文档整改”，而是确实落到了代码、Migration 和 Contract Test 中。

已明显改善并建议继续保留的部分：

```text
Immutable File 默认禁止覆盖
Snapshot / Artifact / FeatureSet / Universe Publish 校验
Provider classify-before-retry
ProviderUseMode.SPIKE / PRODUCTION
失败调用 RawEnvelope
Mapper 去除 1970-01-01 / 0.0 sentinel
Canonical PIT 公共治理列
SecretStr
统一 Provider Error Taxonomy
Runtime ABI Resolver
stdout fd capture 全局 RLock
Migration 删除/改名检测
Canonical Parquet SoR ADR
Capability DB 持久化框架
```

因此：

> **现有架构不需要推翻，也不建议修改 V1.3.2 Frozen Baseline。**

但是，当前整改文档写“P0/P1 全部关闭”仍偏乐观。

第二轮直接审计发现的核心问题是：

> Production Adapter / Storage Skeleton 已经比上一轮严谨很多，但接下来真正用于给 `GO_CORE / GO_DEGRADED / NO_GO` 下结论的 `scripts/spike` 仍是一套独立旧链路，而且存在“当前可能跑不起来、调用成功即 PASS、Dry-run 与正式证据串档”的问题。

此外，Publish Gate 和 Capability Governance 还存在几个“看起来有 Gate、实际上仍可绕过”的边界。

建议项目状态调整为：

```text
P0-M0 Engineering Foundation
    PASS

Round-1 Audit Remediation
    SUBSTANTIALLY CLOSED

Round-2 Residual Hardening
    REQUIRED

P0-M-1A Trial L1 Smoke
    NOT READY FOR FORMAL VERDICT

P0-M-1B Production Capability Spike
    NOT READY
    ——先完成 R2A

Real P0a
    BLOCKED
    ——Round-2 P0=0 + GO_CORE + Canonical Runtime Ready 后进入
```

---

# 1. 上轮 6 个 P0 的复核

| 上轮 ID | 第二轮判断 | 说明 |
|---|---|---|
| P0-01 Immutable File | **基本关闭** | 默认覆盖已 BLOCK；仍有并发 TOCTOU P1 |
| P0-02 Publish Lineage | **部分关闭** | Snapshot/Artifact/FSet/Universe 已校验，但 Run/Policy/Artifact 血缘还没闭合 |
| P0-03 Provider Retry/Timeout | **Production Adapter 已关闭；Spike 路径未关闭** | `scripts/spike/adk_client.py` 仍是独立 blanket retry |
| P0-04 Mapper Sentinel | **基本关闭** | 1970/0.0 已去除；Market/Symbol/Calendar 仍需 strict validation |
| P0-05 Canonical PIT Columns | **Schema 层关闭** | Runtime Canonical Writer/Availability Validation 尚未实现 |
| P0-06 Fallback Identity Publish Gate | **部分关闭** | `fallback_security_ids` 仍是可选 caller 参数，可被省略绕过 |

因此整改文档建议不要再写：

```text
all P0/P1 closed
```

更准确的是：

```text
Round-1 findings implemented;
Round-2 residual blockers pending.
```

---

# 2. R2-P0-01：正式 Spike Runner 当前存在导入断链

## 现状

`scripts/spike/spike_runner.py`：

```python
from samples_b1_sdk import run_b1
```

但：

```text
scripts/spike/samples_b1_sdk.py
```

当前只定义：

```python
main()
```

没有：

```python
run_b1()
```

因此当前正式：

```powershell
uv run python scripts/spike/spike_runner.py --dry-run
```

存在直接 ImportError 的风险。

## 为什么测试没抓到

当前 CI：

```text
ruff
format
mypy
pytest
SDK absence check
```

但没有运行：

```text
scripts/spike/spike_runner.py --dry-run
```

而 pytest 默认只收集 `tests/`。

所以：

```text
179 tests green
```

不能证明：

```text
Spike CLI 可以运行
```

## 必须修改

新增：

```text
run_b1(...)
```

或统一重构 B1 接口。

CI 增加：

```powershell
uv run python scripts/spike/spike_runner.py --dry-run
```

并增加：

```text
test_spike_runner_imports
test_spike_dry_run_all_phases
```

---

# 3. R2-P0-02：正式 Spike 绕过了已经修好的 Production Adapter

这是本轮最重要的架构问题。

当前正确的生产调用链已经是：

```text
AmazingDataSession
        ↓
AmazingDataProvider
        ↓
ProviderUseMode
        ↓
Capability Gate
        ↓
stdout isolation
        ↓
classify_sdk_error
        ↓
class-aware retry
        ↓
RawEnvelope
```

但是 `scripts/spike` 仍然自己维护：

```text
scripts/spike/adk_client.py
```

它重新实现：

```text
直接 import SDK
getattr(module, method)
blanket retry
自建 JSON archive
```

因此上一轮已经修好的：

```text
classify-before-retry
ProviderUseMode
共享 Error Taxonomy
Failed RawEnvelope
stdout capture
Account Profile
Runtime Identity
```

没有真正进入 Formal Spike。

## 另外一个实际问题

已确认的 AmazingData Python SDK 使用模式是：

```text
AmazingData.login(...)
BaseData()
InfoData()
MarketData()
SubscribeData()
```

而当前 Spike 仍大量使用占位调用：

```text
get_security_list
get_share_structure
get_industry_list
get_index_daily_list
```

这与正式 Adapter 已经确认的 API surface 并不一致。

## 裁决

不要继续维护两套 SDK Client。

`adk_client.py` 应废弃或只保留 Evidence Helper。

正式 Spike 必须走：

```text
AmazingDataSession
        ↓
AmazingDataProvider(
    use_mode=ProviderUseMode.SPIKE
)
```

Spike 的差异只允许是：

```text
允许 CANDIDATE capability
更详细 evidence
更保守 throttle
Golden validators
```

而不是重新实现 SDK 访问层。

---

# 4. R2-P0-03：“调用成功 = PASS”不能用于 GO_CORE

当前 B2/B3/B4/B5 的大量逻辑仍是：

```text
SDK call 没抛异常
        ↓
case result = PASS
```

这不能支持核心能力结论。

例如：

```text
Security Master 返回 N 行
≠ 已证明含历史退市

query_kline 返回数据
≠ volume/amount 单位正确

history_stock_status 返回数据
≠ ST/停牌语义正确

history_stock_status 返回数据
≠ 涨跌停/无涨跌幅限制日正确

get_adj_factor 返回数据
≠ Corporate Action 连续性正确
```

## Golden B4 当前也没有真正实现

目前只是：

```text
调用 history_stock_status
→ candidate rows=N
→ live run PASS
```

并没有真正执行：

```text
50 个 ST 加/脱帽
20 个退市
30 个涨跌停规则切换/无涨跌幅限制
20 个 Corporate Action

自动选样
冻结样本
确定 expected truth
逐案例 comparison
差异归因
```

## B6/B7 同样存在风险

例如：

```text
actual = TO_BE_ASSESSED
result = DIFF_EXPLAINED
```

后续 Aggregator 又把：

```text
DIFF_EXPLAINED
```

视为 PASS。

这会形成“尚未评估却通过”的假结论。

## 必须修改 Case 状态

建议：

```text
OBSERVED
VALIDATED_PASS
VALIDATED_FAIL
DIFF_EXPLAINED
NOT_TESTABLE_PERMISSION
NOT_TESTABLE_ACCOUNT
NOT_TESTABLE_TIME
MISSING
```

只有：

```text
VALIDATED_PASS
```

可以满足 Core Gate。

`DIFF_EXPLAINED` 只能表示：

```text
差异已解释
```

是否等价于 PASS 必须由具体 Validator / Tolerance Rule 决定。

---

# 5. R2-P0-04：Spike Verdict 没有 Run Scope

当前：

```text
CaseCatalog.load_existing()
```

会把统一 JSONL 中历史案例全部加载。

Verdict 对所有历史数据一起聚合。

当前 Case 没有：

```text
spike_run_id
run_kind
account_profile_id
sdk_version
runtime_version
code_commit
config_hash
dry_run
```

因此存在三个严重问题。

## 5.1 Dry-run Fake Evidence 混入正式结论

Dry-run 也会写案例。

如果与正式运行共用 Catalog：

```text
FAKE evidence
```

可以进入真实 Verdict。

## 5.2 Trial / Production 串档

未来：

```text
TRIAL_SIMULATION
PRODUCTION_MAIN
```

如果写在同一个 JSONL：

无法证明最终结论基于哪个账号 Profile。

## 5.3 旧 FAIL 永久污染新 Run

如果：

```text
旧 SDK / 旧参数 FAIL
```

后来修好重新运行 PASS：

旧 FAIL 仍会被统计。

## 必须引入 SpikeRun

至少：

```text
spike_run_id
run_kind = DRY_RUN | TRIAL | PRODUCTION
provider
account_profile_id
sdk_version
runtime_version
code_commit
environment_lock_hash
config_hash
started_at
ended_at
status
```

每个 Case 必须绑定：

```text
spike_run_id
```

Verdict 必须：

```text
--run-id <spike_run_id>
```

只聚合：

```text
一个封闭的 Production Run
```

Dry-run 永远不能作为 Capability Approval Evidence。

---

# 6. Spike Raw Evidence 还没有真正做到 Immutable / Lossless

当前 raw 文件名使用：

```text
second timestamp
+
client-local sequence
+
method
```

不同 Client 实例：

```text
sequence 从 0 重新开始
```

存在同秒/同方法覆盖风险。

另一个问题：

```python
_to_jsonable()
```

无法 JSON 序列化时：

```python
return repr(obj)
```

DataFrame 的 `repr()` 可能截断。

因此当前文档中的：

```text
Raw response verbatim archived
```

并不严格成立。

同时 `RequestReceipt.content_hash` 虽然定义了，但当前没有真正填写。

## 修改

建议：

```text
data/spike/<run-kind>/<spike_run_id>/raw/
    <request_id>.parquet
    或
    <request_id>.json
```

request_id：

```text
UUID
```

Evidence metadata：

```text
request_id
request_params_hash
provider_dataset
endpoint
requested_at
received_at
account_profile_id
sdk_version
runtime_version
schema_hash
content_hash
row_count
status
error_class
```

不能覆盖旧 Evidence。

---

# 7. Spike Case ID 当前存在重复风险

B3 对：

```text
historical_st_suspend
limit_price_and_no_limit_days
```

两次都调用：

```text
get_history_stock_status
```

当前 Case ID 又按：

```text
B3-<method>-<date>
```

构造。

所以两个不同语义 Case 可以得到相同 case_id。

## 必须定义唯一键

至少：

```text
(spike_run_id, case_id)
```

Case ID 应编码语义：

```text
B3-ST-600000.SH-20260814
B3-LIMIT-600000.SH-20260814
```

CaseCatalog 必须主动拒绝重复 ID。

---

# 8. Core Gate 与 Probe 输出没有闭合

Core Gate 当前要求：

```text
security_master_with_delisted
daily_bar_units
historical_st_suspend
limit_price_and_no_limit_days
adj_factor_corporate_action_continuity
history_start_2018_plus_warmup
symbol_mapping_unambiguous
sdk_permission_cache_freshness
```

但现有 Probe 并没有完整产生：

```text
history_start_2018_plus_warmup
symbol_mapping_unambiguous
sdk_permission_cache_freshness
```

B5 当前实际生成的是：

```text
units_coverage_freshness
```

这说明：

```text
Gate Contract
≠
Probe Contract
```

## 建议

建立：

```text
SpikeCapabilityDefinition
```

每个 capability 固定：

```text
capability_id
required_case_types
min_valid_cases
validator_id
blocking_rule
```

Verdict 前先检查：

```text
required_case_types coverage == 100%
```

缺失不是：

```text
NO_GO
```

而是：

```text
SPIKE_INCOMPLETE
```

`NO_GO` 只用于：

> 已充分验证，核心能力确实失败。

---

# 9. B7 Capacity/Backfill 当前缺失

当前阶段编号：

```text
B6 free-float
B7 taxonomy/index
```

但冻结后的正式 Spike 顺序应保持：

```text
B2 Identity / Security Master
B3 Core Market Facts
B4 Corporate Action / Adjustment
B5 Unit / PIT / Cache / Freshness
B6 Replacement Assessment
    free-float
    industry
    benchmark
B7 Capacity / Backfill
```

B7 必须实际跑：

```text
ALL_A × 1 month
```

至少输出：

```text
symbol_count
row_count
bytes_received
request_count
retry_count
wall_clock
throughput
cache_behavior
failure_rate
peak_rss
```

---

# 10. R2-P0-05：Fallback Identity Gate 仍可绕过

当前：

```python
publish_snapshot(
    ...,
    fallback_security_ids=None
)
```

如果调用者不传：

```text
NO_IDENTITY_FALLBACK
```

就没有被真正验证。

这仍然属于：

```text
caller assertion
```

而不是：

```text
system invariant
```

## 正确实现

建议新增：

```text
meta_artifact_validation
```

至少：

```text
feature_artifact_set_id
validation_version
identity_fallback_count
blocking_dq_count
validated_at
validator_code_commit
validation_hash
```

Publish 强制：

```text
validation record exists
identity_fallback_count == 0
blocking_dq_count == 0
```

没有 Validation Record：

```text
BLOCK
```

然后删掉或弱化：

```text
fallback_security_ids
```

这个 caller 参数。

---

# 11. R2-P0-06：Run ↔ Artifact ↔ Snapshot ↔ Policy 血缘仍不完整

当前 Publish 已检查：

```text
pipeline_run.status == FEATURE_VALIDATED
```

但还没有验证：

```text
artifact.calc_run_id == pipeline_run_id

pipeline_run.source_policy_version
==
snapshot.source_policy_version

pipeline_run.availability_policy_version
==
snapshot.availability_policy_version

artifact.code_commit
==
pipeline_run.code_commit

artifact.environment_lock_hash
==
pipeline_run.environment_lock_hash

artifact.config_hash
==
pipeline_run.config_hash
```

Migration 006 已经增加：

```text
source_policy_version
availability_policy_version
```

现在应该真正把它们进入 Publish Gate。

## pipeline_run_id 也不应在 Production Publish 中可选

正式 P0a 建议：

```text
PRODUCTION publish
→ pipeline_run_id REQUIRED
```

如果将来需要：

```text
manual recovery
republish
```

也创建一个明确：

```text
run_type = RECOVERY / REPUBLISH
```

而不是：

```text
pipeline_run_id = None
```

---

# 12. R2-P1-01：Capability Approval 仍可绕 Evidence

当前治理方向正确：

```text
meta_provider_capability = authoritative
```

但实现仍有几个边界。

## 12.1 persist_approval 可单独调用

完整 Evidence 校验发生在：

```text
approve_capability()
```

但：

```text
persist_approval()
```

可以被调用者直接调用。

因此理论上：

```text
broken evidence
→ 直接写 APPROVED
```

## 12.2 先改内存，后持久化

如果：

```text
approve_capability()
→ memory APPROVED

persist_approval()
→ DB failure
```

会出现：

```text
Memory = APPROVED
DB = CANDIDATE
```

与“DB authoritative”矛盾。

## 12.3 INSERT OR REPLACE 有 Metadata 擦除风险

原 `meta_provider_capability` 还有：

```text
asset_class
frequency
history_supported
realtime_supported
point_in_time_grade
permission_note
transport
adapter_version
```

使用：

```sql
INSERT OR REPLACE
```

可能把已有列替换成 NULL。

## 12.4 load_approvals 没恢复完整 provenance

当前只读：

```text
capability
status
```

不会完整恢复：

```text
verified_at
account_profile_id
```

也需要确保：

```text
DB CANDIDATE
```

能够主动覆盖旧进程 Cache 的 APPROVED。

## 修改

统一为：

```text
approve_and_persist_capability()
```

一笔事务：

```text
validate evidence
→ UPSERT governance fields
→ COMMIT
→ reload registry from DB
```

禁止对外暴露两个可独立执行的审批步骤。

---

# 13. R2-P1-02：Governance Error 不应使用 ProviderPermissionError

当前：

```text
PRODUCTION 使用 CANDIDATE capability
```

抛：

```text
ProviderPermissionError
```

这会把：

```text
内部治理未批准
```

和：

```text
银河账号权限不足
```

混在一起。

建议新增：

```text
ProviderGovernanceError
ProviderCapabilityNotApprovedError
```

Provider Entitlement 统计只统计真正：

```text
ProviderPermissionError
```

---

# 14. R2-P1-03：“查询失败”错误归因仍过宽

当前仍存在：

```text
"查询失败"
+
account_context 中存在 permission_codes
→ ProviderPermissionError
```

正式账号当然也会有 PermissionCode。

因此：

```text
参数错误
服务异常
SDK drift
服务器内部失败
```

仍可能被误判为权限问题。

## 修改

只有：

```text
explicit endpoint entitlement map
+
verified denial signature
```

才允许归：

```text
ProviderPermissionError
```

建议 Evidence 增加：

```text
classification_rule_id
classification_confidence
```

未知错误继续：

```text
ProviderSdkInternalError
```

---

# 15. R2-P1-04：Provider Doctor 只验证了“包路径”，还没有稳定验证“实际加载 DLL”

当前 Doctor：

```text
先 enumerate DLL
→ 后 login/query
```

但：

```text
login/query 后没有重新 enumerate
```

如果 `tgw.dll` 是首次真实 SDK 调用后才加载：

最终可能：

```text
TGW_LOADED_DLL_PATH = None
```

但 Verdict 已依据 wheel 预期路径给：

```text
RUNTIME_IDENTITY_VERIFIED
```

建议拆成：

```text
RUNTIME_PACKAGE_VERIFIED
RUNTIME_ACTUAL_LOAD_VERIFIED
```

并在：

```text
login
minimal query
```

后重新：

```text
EnumProcessModulesEx
```

确认实际 DLL path。

---

# 16. R2-P1-05：Mapper 仍需三处 Strict Semantic 修正

## Security Master Market 必须 Required

当前 MARKET_CODE 仍允许：

```text
""
```

Identity / Provider Symbol 不能接受未知 Market。

未知/缺失：

```text
MappingValidationError
```

## Daily Bar Provider Symbol 要统一

Security Master 可能：

```text
600000.SH
```

Daily Bar 当前可能：

```text
600000
```

必须建立单一：

```text
ProviderSymbolNormalizer
```

所有 DTO 统一：

```text
600000.SH
000001.SZ
830799.BJ
```

## Trade Calendar 不得静默丢弃坏日期

当前：

```text
unparsable date
→ filter 掉
```

Calendar 是：

```text
rolling
PIT
available_at
prev/next trade date
```

基础。

一个坏日期就应该：

```text
quarantine whole response / ProviderSchemaError
```

---

# 17. R2-P1-06：L1 Realtime Smoke Script 还不能直接拿来判权限

## 17.1 明确用 Asia/Shanghai

当前：

```python
datetime.now()
```

依赖开发机本地时区。

必须：

```python
ZoneInfo("Asia/Shanghai")
```

## 17.2 状态原因要区分

非交易时间无事件，不应写：

```text
NOT_TESTABLE_PERMISSION
```

应该：

```text
NOT_TESTABLE_TIME
NOT_TESTABLE_MARKET_CLOSED
NOT_TESTABLE_PERMISSION
FAIL_NO_EVENTS
```

## 17.3 Subscription Lifecycle 先实机确认

当前：

```text
register
→ sleep
```

没有明确：

```text
run/start event loop
```

在当前 AmazingData 1.1.9 wheel 上正式确认：

```text
register
run/start
unregister
stop
callback signature
```

之前：

```text
FAIL_NO_EVENTS
```

不能解释成账号无权限。

## 17.4 Event Time 不能字符串排序

必须解析成：

```text
event_time_utc
```

或：

```text
Asia/Shanghai aware datetime
```

再判断：

```text
latency
out-of-order
```

---

# 18. R2-P1-07：Immutable Writer 还有并发 TOCTOU

当前：

```text
exists?
→ write temp
→ os.replace
```

两个并发 Writer：

```text
A exists=False
B exists=False
A replace
B replace
```

理论上 B 仍可覆盖 A。

Phase 0 单 Writer 让当前风险有限。

但将来：

```text
Raw Provider Workers
```

不一定都在 DuckDB Owner 内。

## 建议

短期：

```text
FileCommitCoordinator
```

规定所有 Immutable Commit 单 Writer。

并增加跨进程 Contract Test。

暂时不用引入分布式锁。

---

# 19. R2-P1-08：输出路径只使用 UUID 前 8 hex

当前 mock path tag：

```text
uuid[:8]
```

只有 32 bit。

长期会有无意义碰撞。

发生后虽然 Immutable Writer 会 BLOCK，不会污染数据，但会造成随机生产失败。

直接改成：

```text
full UUID
```

或至少：

```text
32 hex
```

---

# 20. R2-P1-09：Migration Repo 序列还应强制连续

当前已经能检测：

```text
已应用 migration 删除/改名
```

很好。

但新 Repo 如果是：

```text
001
003
004
```

目前仍缺：

```text
repo ids == 001..N
```

的强制检查。

建议缺号直接：

```text
MigrationSequenceGapError
```

---

# 21. R2-P1-10：ADR-009 与旧 Schema 的 STAGING 语义仍有残留

ADR 已决定：

```text
Snapshot / Artifact metadata
只在完成后 INSERT validated
```

但历史 Migration 003 仍保留：

```text
DEFAULT STAGING
```

不能直接改历史 Migration，这一点正确。

下一步要做的是：

```text
service-level rule:
禁止 Snapshot/Artifact metadata 新插入 STAGING
```

必要时新增后续 Migration 做注释/约束补强。

同时更新：

```text
SnapshotStatus
ArtifactSetStatus
```

的说明，避免开发人员误用。

---

# 22. R2-P1-11：FeatureSet / Universe / SourcePolicy Version 还没有不可变激活机制

现在都有：

```text
version
```

但同一个 version 仍可以：

```text
UPDATE rule
INSERT/DELETE member
```

这会造成：

```text
同一个 version
不同时间含义不同
```

P0a/P0b 前必须形成：

```text
DRAFT
→ compute definition hash
→ ACTIVE/APPROVED
→ immutable
```

修改只能：

```text
new version
```

## Feature Set

ACTIVE 后：

```text
member immutable
definition_hash publish 前可重算验证
```

## Universe

Universe Version：

```text
rule_hash
activation
immutable
```

## Source Policy

APPROVED 后：

```text
entries immutable
```

---

# 23. Canonical PIT 当前只完成 Schema，Runtime Contract 是下一阶段必做

Migration 006 的整改是正确的。

但目前还没有完整实现：

```text
RawWriter
RawEnvelope Persistence
ProviderNormalizedWriter
Canonicalizer
CanonicalValidationService
AvailabilityPolicyEngine
QuarantineStore
SnapshotBuilder
```

所以：

```text
available_at must be non-null
availability_kind must be valid
selection_reason must exist
```

当前还主要是设计纪律，不是不可绕过的运行时约束。

这不是 M0 回归问题。

但它是：

> **Real P0a Entry Gate。**

---

# 24. 下一阶段 R2A：Spike Framework Rewrite

优先级最高。

现在不要先扩 Trend/PV。

## 24.1 正式 Spike 统一走 Production Adapter

```text
Spike Runner
→ AmazingDataSession
→ AmazingDataProvider(SPIKE)
```

删除独立：

```text
SDK import
login
retry
error mapping
```

重复实现。

## 24.2 SpikeRun

新增：

```text
spike_run_id
run_kind
provider
account_profile_id
sdk_version
runtime_version
code_commit
environment_lock_hash
config_hash
started_at
ended_at
status
```

## 24.3 Case

增加：

```text
spike_run_id
validator_id
validator_version
evidence_hash
```

## 24.4 Dry-run 完全隔离

```text
data/spike/dry-run/<run-id>/
data/spike/trial/<run-id>/
data/spike/production/<run-id>/
```

正式 Verdict：

```text
只接受 PRODUCTION
```

## 24.5 实现真正 Validators

包括：

```text
Security Master / Delisted
Daily OHLCV Unit
ST / Suspension
Limit Rule / No-limit
Corporate Action / Adj
History Coverage
Symbol Mapping
PIT / Cache / Freshness
```

## 24.6 Golden

真正执行：

```text
Discover
Freeze
Expected Truth
Compare
Reason Code
Verdict
```

## 24.7 B7 Capacity

增加：

```text
ALL_A × 1 month
```

性能/限流/缓存测试。

---

# 25. 下一阶段 R2B：Publish + Governance Hardening

实现：

```text
meta_artifact_validation
fallback 自动 Gate
blocking DQ Gate
Production publish 强制 pipeline_run
Run/Artifact/Snapshot/Policy/Code/Config 全血缘
Capability approve-and-persist transaction
Capability Registry DB 全量重建
ProviderGovernanceError
FeatureSet activation immutability
Universe activation immutability
SourcePolicy version immutability
```

---

# 26. 下一阶段 R2C：Provider Semantic Hardening

实现：

```text
ProviderSymbolNormalizer
Market Required
Strict Trade Calendar
classification_rule_id / confidence
Doctor login 后 actual DLL reprobe
L1 Asia/Shanghai session
L1 event_time parser
Subscription lifecycle live verification
FileCommitCoordinator
```

---

# 27. 正式账号还没到位时可以并行开发

不需要等数据权限。

可以完成：

```text
RawWriter
RawEnvelope persistence
Provider-normalized writer
Canonicalizer interface
Canonical validation
Availability Policy Engine
Quarantine Store
Security Bridge Resolver
Source Policy Selector skeleton
Snapshot Builder
Artifact Validator
Publish Validation
ALL_A Universe with Mock
```

---

# 28. Feature 顺序仍然是 Trend 优先

Canonical Vertical Slice 稳定后再开始：

```text
RET_005 / 020 / 060
SER_005 / 020 / 060
UP_DAY_RATIO
MA_DIST
MA_BREADTH
POS_RET_BREADTH
NEW_HIGH / NEW_LOW
```

当前不要：

```text
完整 PV
FLOAT_A_SHARE → free_share
Galaxy → SW
```

---

# 29. 仿真 L1 的安排

修好 L1 脚本后：

```text
1 stock
→ 5
→ 20
```

先验证：

```text
Subscribe Lifecycle
callback
provider_event_time
received_at
cumulative volume/amount
bid/ask
trading_phase
unsubscribe
reconnect
```

100 只只用于：

```text
subscription limit behavior
```

不要长期占用试用额度。

---

# 30. 正式账号 P0-M-1B

R2A/R2B/R2C 关闭后：

```text
Provider Doctor
    ↓
B2 Identity / Security Master
    ↓
B3 Core Facts
    ↓
B4 Corporate Action / Adjustment
    ↓
B5 Units / PIT / Cache / Freshness
    ↓
B6 Replacement Assessment
    ↓
B7 Capacity
    ↓
Single Production Spike Run Verdict
```

## Early Stop

```text
B2 core FAIL → STOP
B3 core FAIL → STOP
B4 core FAIL → STOP
```

不要浪费正式账号流量继续外围测试。

---

# 31. GO_CORE 后 Real P0a

```text
AmazingData
→ Raw Immutable
→ Provider-normalized
→ Canonical Daily/Status/Limit/Adj/CA
→ Security ID
→ ALL_A
→ Trend BASE
→ Market Aggregate
→ Artifact
→ Publish
→ Exact Replay
```

---

# 32. 放量节奏

```text
Stage A
20 securities × 60d

Stage B
100 securities × 2y

Stage C
ALL_A × 1 month

Stage D
Full Historical Backfill
```

每一级必须通过：

```text
DQ
Exact Replay
Coverage
Performance
```

---

# 33. 必须新增 Contract Tests

## Spike

```text
test_spike_runner_import
test_spike_dry_run_all
test_dry_run_never_counts_for_production_verdict
test_verdict_scoped_to_one_run
test_case_id_unique_within_run
test_unvalidated_observation_never_passes
test_core_case_missing_yields_incomplete
test_trial_and_production_evidence_never_mix
test_b7_capacity_present
```

## Publish

```text
test_publish_requires_artifact_validation_record
test_publish_blocks_fallback_count
test_production_publish_requires_pipeline_run
test_publish_rejects_artifact_calc_run_mismatch
test_publish_rejects_source_policy_mismatch
test_publish_rejects_availability_policy_mismatch
test_publish_rejects_code_commit_mismatch
test_publish_rejects_config_hash_mismatch
```

## Capability

```text
test_persist_cannot_bypass_evidence
test_failed_db_persist_does_not_approve_cache
test_approval_preserves_existing_metadata
test_db_candidate_demotes_cached_approved
test_load_restores_account_profile_and_verified_at
```

## Mapper

```text
test_security_master_missing_market_blocks
test_unknown_market_code_blocks
test_daily_bar_provider_symbol_normalized
test_calendar_bad_date_blocks_whole_payload
```

## Runtime

```text
test_doctor_reprobes_dll_after_login
test_package_verified_is_not_actual_loaded_verified
```

## Storage

```text
test_concurrent_immutable_commit_cannot_replace
test_full_uuid_paths_do_not_collide
test_migration_sequence_gap_blocks
```

---

# 34. CI 新增脚本级 Gate

现有 CI 保留。

新增：

```powershell
uv run python -m compileall scripts
uv run python scripts/spike/spike_runner.py --dry-run
```

最好再把 Spike Framework 的纯逻辑迁到：

```text
src/ashare_state/spike/
```

`scripts/` 只作为 CLI entry point。

这样：

```text
mypy
pytest
coverage
```

才能真正覆盖正式 Spike 逻辑。

---

# 35. 优先级汇总

| ID | 级别 | 问题 | 关闭时点 |
|---|---|---|---|
| R2-P0-01 | P0 | `spike_runner` 导入不存在的 `run_b1` | 立即 |
| R2-P0-02 | P0 | Formal Spike 绕过 Hardened Provider Adapter | 正式 Spike 前 |
| R2-P0-03 | P0 | Call Success 被当 Semantic PASS | 正式 Spike 前 |
| R2-P0-04 | P0 | Dry-run/Trial/历史证据混合，无 Run Scope | 正式 Spike 前 |
| R2-P0-05 | P0 | Fallback Identity Gate 仍可由 caller 省略 | Real P0a 前 |
| R2-P0-06 | P0 | Run/Artifact/Snapshot/Policy 血缘未闭合 | Real P0a 前 |
| R2-P1-01 | P1 | Capability Approval 可绕 Evidence / 非事务 | Approval 前 |
| R2-P1-02 | P1 | Governance Error 被记成 Permission | 正式运维前 |
| R2-P1-03 | P1 | “查询失败”仍可能过度判 Permission | 正式 Spike 前 |
| R2-P1-04 | P1 | Doctor 未在 Login 后确认实际 DLL | 正式账号前 |
| R2-P1-05 | P1 | Market/Symbol/Calendar strict mapping | 正式数据前 |
| R2-P1-06 | P1 | L1 时区/状态/lifecycle/time parser | 仿真结论前 |
| R2-P1-07 | P1 | Immutable Writer TOCTOU | 并发 ingest 前 |
| R2-P1-08 | P1 | 文件 identity tag 仅 8 hex | 近期 |
| R2-P1-09 | P1 | Migration 序列未强制连续 | 近期 |
| R2-P1-10 | P1 | ADR-009 与旧 STAGING 语义残留 | P0a 前 |
| R2-P1-11 | P1 | FeatureSet/Universe/SourcePolicy 未真正 version-immutable | P0a/P0b 前 |
| R2-P1-12 | P1 | Canonical PIT Runtime Writer/Validation 尚未实现 | Real P0a 前 |

---

# 36. 推荐开发顺序

```text
R2A
Spike Framework Rewrite
    ↓
R2B
Publish + Governance Hardening
    ↓
R2C
Provider Semantic / L1 Hardening
    ↓
Trial L1 Smoke
    ↓
Production P0-M-1B
    ↓
GO_CORE
    ↓
P0a Canonical Vertical Slice
    ↓
Trend BASE
    ↓
20×60d
    ↓
100×2y
    ↓
ALL_A×1m
    ↓
Full Historical Backfill
```

---

# 37. 第二轮审计裁决

本轮整改：

```text
方向正确
质量良好
不需要返工重构
```

但当前最需要防止的新风险是：

> 核心库已经越来越严格，而“用来证明核心库可以接正式数据”的 Spike 脚本仍停留在旧原型阶段。

如果现在直接用当前 Spike 跑正式账号，最危险的不是程序报错，而是：

```text
得到一个有 JSON、有 case、有 PASS，
但语义上不足以证明 GO_CORE 的报告。
```

因此下一阶段不要先扩大 Feature。

先完成：

```text
Spike Framework
Publish Validation
Capability Governance
Canonical Runtime Contract
```

四条链统一到同一套生产代码路径。

完成后，项目才真正进入：

> **“可以安全接真实历史数据”的 P0a 阶段。**
