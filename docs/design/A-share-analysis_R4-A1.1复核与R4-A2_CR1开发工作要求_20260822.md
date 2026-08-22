# A-share-analysis R4-A1.1 复核结论与下一阶段开发工作要求

> 仓库：`GeeCeeSneaker/A-share-analysis`  
> 审查分支：`main`  
> 审查 HEAD：`8d7d4aa3f5647991edc938016d3b063ea76e5be6`  
> 当前最新代码基线：`bb694c5304ee63bd0c6beb9d36ae5c21a7db8b59`  
> R4-A1.1 主实现：`b3a3d273468896824dd6d133e1db0b84f0a4a2e6`  
> Development Management 初始化：`f1023941aa06b09ee55f77f1585bbcf46baf1d7f`  
> Development Management SHA 回填：`8d7d4aa3f5647991edc938016d3b063ea76e5be6`  
> Frozen Baseline：V1.3.2  
> 日期：2026-08-22  
> 性质：Focused Acceptance Review + R4-A2 / CR-1 开发任务书

---

# 0. 本轮裁决

本轮同时复核：

```text
R4-A1.1 Truth Integrity Hotfix
DEVLOG Governance
DEVELOPMENT_MANAGEMENT 初始化与同步
```

总体结论：

```text
Development Management Governance
    PASS_WITH_MINOR_FIXES

R4-A1.1 Structure / Integrity
    SUBSTANTIALLY PASS

R4-A1.1 Formal Truth Closure
    REOPENED

Production P0-M-1B
    BLOCKED

CR-1
    READY TO START IN PARALLEL
```

不需要改 Frozen Baseline，不需要重新设计 Spike Framework。

下一步进入：

```text
Track A:
R4-A2 Golden Review + Domain Router + Semantic/PIT Validators

Track B:
CR-1 ProviderExchange + RawWriter
```

两条线并行。

---

# 1. Development Management 文档复核

仓库路径：

```text
docs/project/DEVELOPMENT_MANAGEMENT.md
```

正确。

当前文档已经正确建立：

```text
权威级别
C0/C1/C2/C3 Change Control
DEVLOG / Management Doc 分工
设计变更同提交规则
当前系统架构
PIT / Storage / Provider / Publish / Feature 契约
Workstream 状态
Entry Gate
Risk / Technical Debt
Change Log
Definition of Done
```

本治理体系正式接受。

因此：

```text
DM-CR-20260822-001
Review:
    VERIFIED
```

可在下一提交中更新。

---

# 2. Management Doc 需要修的 4 个小问题

## 2.1 §41 存在重复 R4-A2 段落

当前 `§41 当前最高优先级` 连续出现两次：

```text
## R4-A2
```

第一段比第二段多：

```text
Domain-specific Golden Router
```

下一次更新时合并为一个 R4-A2，不保留重复段落。

---

## 2.2 Change Log 缺 R4-A1.1 契约记录

当前 Change Log 只有：

```text
DM-CR-20260822-001
建立 Development Management
```

但管理总册已经吸收了 R4-A1.1 的：

```text
Golden hash model
event coverage
append-only version
production run gate
```

这些属于 C1 Contract Clarification。

由于 R4-A1.1 代码先于管理总册建立，可补一条：

```text
DM-CR-20260822-002
Adopt R4-A1.1 Golden Truth Integrity Contract
```

标明：

```text
Implementation Commit:
b3a3d273468896824dd6d133e1db0b84f0a4a2e6

Review:
REOPENED
```

原因是 Formal Source Evidence 仍未闭环。

---

## 2.3 DEVLOG 顶部治理说明已落后于实际 CI

DEVLOG 文件顶部目前仍描述：

```text
CI gate:
src/migrations/configs/scripts
```

但实际 `.github/workflows/ci.yml` 已扩展：

```text
data/golden/**
.gitattributes
.github/workflows/**
```

DEVLOG 顶部维护规则必须同步实际 CI。

---

## 2.4 DEVLOG 时间统一为 Asia/Shanghai

当前部分 DEVLOG 时间与 Git commit 时间存在明显时区偏差。

从现在起固定：

```text
YYYY-MM-DD HH:mm +08:00
Asia/Shanghai
```

或者只记录：

```text
YYYY-MM-DD
```

不要记录无时区的未来时间。

A 股项目所有：

```text
trade_date
market session
DEVLOG human timestamp
```

必须明确区分。

---

# 3. R4-A1.1 已验证通过的内容

以下实现本轮接受。

## 3.1 Manifest Self-Verification

`GoldenTruthStore.load()` 已从实际 Cases 重新计算：

```text
case_count
counts_by_type
review_summary
```

并与 active manifest exact match。

只改：

```text
review_summary
counts_by_type
```

已经无法绕过 Gate。

裁决：

```text
PASS
```

---

## 3.2 Semantic Hash 已包含 case_type

当前 `case_semantic_hash` 包含：

```text
golden_case_id
case_type
provider_symbol
trade_date
expected_fields
truth_source
source_ref
source_artifact_hash
truth_version
```

修改 `case_type` 后无法保持旧 hash。

裁决：

```text
PASS
```

---

## 3.3 Distinct Event Gate

当前代码已经区分：

```text
event_id
event_class
```

负样本：

```text
NEGATIVE_SAMPLE
```

不会再被算作 ST Transition Event。

当前 v2 真实状态：

```text
ST_CAP = 2 < 50
DELIST = 10 < 20
```

因此正式 Production Run 会被拒绝。

这属于正确的 Fail Closed 行为。

裁决：

```text
PASS
```

---

## 3.4 Golden Version 不再 lexicographic guess

已经采用：

```text
golden_cases_v1.jsonl
golden_cases_v2.jsonl

truth_manifest.json
    ACTIVE pointer
```

运行时不再：

```text
sorted(files)[-1]
```

猜版本。

裁决：

```text
PASS
```

---

## 3.5 CI full-history + DEVLOG governed paths

当前 CI 已：

```yaml
actions/checkout:
    fetch-depth: 0
```

DEVLOG Gate 也已包含：

```text
data/golden
.gitattributes
.github/workflows
```

裁决：

```text
PASS
```

---

# 4. R4-A1.1 剩余 P0：source_artifact_hash 还没有真正绑定 Source Artifact

当前：

```text
source_artifact_hash
```

在 COMPILED Case 中为空。

Review Gate 对 REVIEWED Case 的要求主要是：

```text
source_artifact_hash 非空
```

但代码目前没有：

```text
source_artifact_ref
真实 Evidence Artifact
重新计算 artifact SHA256
```

所以理论上人工可以填写任意：

```text
source_artifact_hash = "abcdef..."
```

重新生成 `case_semantic_hash`，然后标成 REVIEWED。

系统无法证明：

```text
这个 hash 确实来自 source_ref 对应的外部官方证据
```

因此：

> R4-A1.1 的 Integrity Framework 可以通过，但 Formal Truth Closure 不能 VERIFIED。

这项直接并入 R4-A2，不另建大阶段。

---

# 5. R4-A2 第一任务：Golden Review Evidence Closure

## Documentation Update Required

```text
YES
```

Target：

```text
docs/project/DEVELOPMENT_MANAGEMENT.md
```

Change ID：

```text
DM-CR-20260822-003
```

Type：

```text
C1 Contract Clarification
```

至少更新：

```text
§30 Golden Truth
§31 Golden Truth 当前待修
§40 当前项目阶段状态
§41 当前最高优先级
§48 P0-M-1B Entry Gate
§52 Risk Summary
§61 Change Log
```

---

# 6. Golden Review 不允许手工填 Hash

需要实现一个正式 Review Workflow，例如：

```text
python scripts/golden/review.py ...
```

Review Workflow 自己生成：

```text
source_artifact_hash
reviewed_by
reviewed_at
review_status
review_note
```

调用者不得直接提交：

```text
source_artifact_hash
```

作为“相信我”的输入。

---

# 7. Source Evidence Model

Golden Case / Review Record 建议增加：

```text
source_artifact_ref
source_artifact_hash
source_artifact_kind
source_retrieved_at

compiled_by
compiled_at

reviewed_by
reviewed_at
review_note
review_status
```

不要继续让：

```text
COMPILED Case
```

使用：

```text
reviewed_by = ai-compile-v2
reviewed_at = compile time
```

编译和人工 Review 是两个不同 provenance。

---

# 8. Source Artifact 的最小要求

正式 REVIEWED Case：

```text
source_ref
```

只作为来源定位信息，不够。

必须存在一个可验证的 Evidence Artifact：

```text
source_artifact_ref
```

Review Workflow：

```text
读取 artifact bytes
→ SHA256
→ 写 source_artifact_hash
```

Formal Review Gate：

```text
resolve source_artifact_ref
→ bytes exist
→ SHA256 == source_artifact_hash
```

否则：

```text
REVIEW_INCOMPLETE
```

不得进入 Production Truth。

Evidence Artifact 可以：

```text
Git repository
受控 evidence store
或另一个稳定文件存储
```

但 Formal 环境必须可 resolve 和 hash verify。

不要只保存无法验证的字符串 Hash。

---

# 9. ST Event Gate 语义再校正

Frozen Requirement 是：

```text
50 ST/*ST events
```

当前 Gate 只计算：

```text
ST_CAP
```

下一版应改为：

```text
ST_TRANSITION
```

并增加 subtype：

```text
ST_ADD
ST_REMOVE
STAR_ST_ADD
STAR_ST_REMOVE
```

负样本：

```text
NEGATIVE_SAMPLE
```

只用于 False-positive 检查，不计入 50 Event Gate。

建议至少同时满足：

```text
distinct ST events >= 50
ST_ADD > 0
ST_REMOVE > 0
```

避免 50 个案例全部来自同一种状态变化。

---

# 10. Delisted Gate 要同时验证 distinct security

当前：

```text
distinct event_id >= 20
```

还不够。

因为 event_id 是 Dataset 自己定义的字符串。

正式 Gate：

```text
distinct DELIST event_id >= 20
AND
distinct provider_symbol >= 20
```

避免同一退市证券通过人为拆 event id 凑数量。

---

# 11. Golden Hash 字段命名修正

当前 SpikeRun：

```text
golden_manifest_hash
```

实际绑定的是：

```text
GoldenManifest.dataset_hash
```

这个名字容易误导。

正式 Production Run 前二选一：

### 方案 A（推荐）

改成：

```text
golden_dataset_hash
```

另外如需 Manifest Seal：

```text
golden_manifest_hash
```

单独计算。

### 方案 B

真正让 `golden_manifest_hash` 保存 manifest bytes hash。

不得继续：

```text
字段叫 manifest_hash
实际存 dataset_hash
```

---

# 12. Golden Dataset Event Diversity

Formal Golden 不应该只满足：

```text
row count
```

还要满足：

```text
distinct event
distinct security
board / exchange
historical regime
positive / negative
```

建议 Truth Manifest 输出：

```text
case_count
counts_by_type
counts_by_event_class
distinct_events_by_type
distinct_securities_by_type
exchange_coverage
board_coverage
review_summary
```

这些全部由 Cases 重新计算，不信任手填。

---

# 13. R4-A2 第二任务：Domain-specific Golden Probe Router

当前 Formal Golden 不能继续：

```text
所有 Golden Case
→ get_history_stock_status()
```

必须按 domain 路由。

---

## ST

```text
get_history_stock_status
```

验证：

```text
ST add/remove
suspension/resumption
```

---

## Delisted

使用：

```text
get_hist_code_list
get_stock_basic
```

验证：

```text
list_date
delist_date
historical existence
delisting lifecycle
```

不要用“退市几年后的 status row 是否存在”判断 Security Master。

---

## Limit

使用：

```text
get_history_stock_status
+
PIT Trading Rule
```

验证：

```text
rate
limit price
no-limit
tick
rounding
```

---

## Corporate Action

必须组合：

```text
dividend / right issue
adj_factor
history status
Kline price context
```

不能只检查：

```text
IS_WD_SEC
```

---

## BJ Mapping

使用：

```text
BJ mapping endpoint
historical security master
effective-date mapping
```

不得让：

```text
CODE_CONTINUITY
SEGMENT_VALID
```

去 status endpoint 中找字段。

---

# 14. R4-A2 第三任务：Adj Continuity

当前：

```text
validate_adj_continuity()
```

在没有：

```text
price_context
```

时正确返回 OBSERVED。

下一步 B3/B4 必须提供：

```text
T-1
T
T+1
raw close/preclose
adj factor before/after
corporate action
```

再做连续性验证。

`adj_factor_corporate_action_continuity` 只有真实 price context validator PASS 才能进入 Core PASS。

---

# 15. R4-A2 第四任务：删除 B3 现场 ST 假设

不得：

```text
symbols[:1]
expected_is_st = False
```

B3 只做：

```text
schema
value-domain
payload integrity
```

语义 Truth：

```text
必须来自 Reviewed Golden
```

---

# 16. R4-A2 第五任务：History Coverage 固定样本

不要取：

```text
get_code_list() 前 2 只
```

固定 Coverage Fixtures：

```text
长期上市 SH
长期上市 SZ
BSE
历史退市证券
```

记录：

```text
expected_list_date
provider_earliest
required_earliest
```

不能把“股票上市晚”误判成“Provider 历史短”。

---

# 17. R4-A2 第六任务：PIT Trading Rule

建立版本化规则，而不是静态：

```text
board -> rate
```

至少：

```text
exchange
board
effective_from
effective_to
st_flag
listing_age_rule
up_rate
down_rate
tick_size
rounding_mode
no_limit_rule
```

测试：

```text
Main 10%
ST Main 5%
ChiNext reform before/after
STAR
STAR first-5 no-limit
BSE 30%
IPO / no-limit
```

计算：

```text
Decimal
ROUND_HALF_UP
```

禁止 Python float `round()` 作为交易所正式 rounding。

---

# 18. R4-A2 第七任务：BSE / BJ

必须增加独立 Core Evidence：

```text
BSE historical Security Master
BSE daily bar
BSE 30% rule

BJ old/new code
effective-date mapping
unique security identity
```

BSE 不能只依赖“code list 里可能顺便出现”。

---

# 19. Track B：CR-1 ProviderExchange + RawWriter

## Documentation Update Required

```text
YES
```

Target：

```text
docs/project/DEVELOPMENT_MANAGEMENT.md
```

Change ID：

```text
DM-CR-20260822-004
```

Type：

```text
C1
```

原因：

```text
§17 已经冻结 ProviderExchange 目标；
本任务是将已批准 Contract 实现为运行时代码，
不改变 SoR / Frozen Baseline。
```

至少更新：

```text
§17
§40
§42
§43
§52
§61
```

---

# 20. ProviderExchange Contract

建议：

```python
ProviderExchange[T]:
    envelope: RawEnvelope
    payload: T | None
```

要求：

```text
一个 provider exchange
=
一个 request_id
=
一个 RawEnvelope
=
最多一个 payload
```

这个 request_id 贯穿：

```text
Provider
→ Spike
→ RawWriter
→ Normalized
→ Canonical lineage
```

---

# 21. 不要使用 last_exchange / thread-local hack

不要实现：

```text
provider.last_exchange
consume_last_exchange()
```

作为正式 Contract。

原因：

```text
未来并发后存在错误绑定风险
```

推荐让内部 Provider Call 显式返回：

```text
ProviderExchange
```

如现有业务 API 仍希望返回 Payload，可建立清晰 wrapper：

```text
call_exchange()
→ ProviderExchange

get_daily_bar()
→ call_exchange().payload
```

Spike/RawWriter 使用：

```text
call_exchange
```

不得重新查询 Provider。

---

# 22. 每一次真实 SDK Exchange 都必须有 Envelope

例如当前：

```text
query_kline
→ 内部 get_calendar
→ query_kline
```

若内部 Calendar 也是真实 SDK call：

```text
Calendar
```

必须有自己的：

```text
request_id
RawEnvelope
```

不能隐藏在 DailyBar Envelope 里。

---

# 23. RawWriter Contract

输入：

```text
ProviderExchange
```

成功：

```text
Envelope + Payload
→ immutable raw artifact
```

失败：

```text
Envelope
→ failure evidence
```

不得因为没有 Payload 丢失请求记录。

---

# 24. Raw Artifact 最小字段

必须可追踪：

```text
provider
provider_dataset
endpoint
request_id
request_params_hash

requested_at
received_at
duration_ms
attempt_count

account_profile_id
sdk_version
runtime_version

row_count
schema_hash
content_hash
raw_file_uri

status
error_class
error_code
```

---

# 25. Raw 格式

结构化表数据：

```text
Parquet 优先
```

小型 metadata / object：

```text
JSON
```

要求：

```text
lossless
deterministic schema metadata
immutable
```

不得：

```text
repr()
```

代替原始数据。

---

# 26. Raw 路径

建议逻辑路径：

```text
raw/
provider=amazingdata/
dataset=<dataset>/
date=<YYYY-MM-DD>/
<request_id>.parquet
```

Envelope：

```text
<request_id>.meta.json
```

实际命名可调整，但必须：

```text
request_id unique
logical URI canonical
cross-platform stable
```

---

# 27. RawWriter 幂等

同一个 request_id：

```text
same content hash
→ idempotent no-op

different content
→ BLOCK
```

不能覆盖。

---

# 28. Ingest Run

如现有 Schema 无完整运行记录，新增：

```text
meta_ingest_run
```

至少：

```text
ingest_run_id
provider
account_profile_id
code_commit
environment_lock_hash
config_hash
started_at
ended_at
status
```

如果已有同等结构，不重复造表。

Schema 变化必须新增 Migration，不修改旧 migration。

---

# 29. CR-1 Contract Tests

至少：

```text
test_provider_exchange_preserves_request_id
test_spike_uses_provider_exchange_request_id
test_raw_writer_success_persists_payload_and_envelope
test_raw_writer_failure_persists_envelope
test_raw_writer_same_hash_idempotent
test_raw_writer_different_bytes_same_request_blocks
test_query_kline_calendar_has_own_exchange
test_raw_evidence_contains_no_secret
test_raw_logical_uri_cross_platform
test_no_repr_payload_fallback
```

---

# 30. Management Doc 本次必须同步的内容

本批次包含 C1 Contract 调整/落实。

因此：

```text
Documentation Update Required: YES
```

必须同时更新：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

---

# 31. Management Change Records

下一逻辑批次至少新增：

## DM-CR-20260822-002

```text
Adopt R4-A1.1 Golden Truth Integrity Contract
```

记录已落地的：

```text
manifest self verification
semantic/source hash split
event coverage
append-only version
```

Review：

```text
REOPENED
```

直到 Formal Source Evidence Closure 完成。

---

## DM-CR-20260822-003

```text
R4-A2 Golden Review / Domain Router / PIT Validator Contract
```

Implementation 完成后：

```text
DONE
PENDING_REVIEW
```

---

## DM-CR-20260822-004

```text
CR-1 ProviderExchange / RawWriter Runtime Contract
```

Implementation 完成后：

```text
DONE
PENDING_REVIEW
```

---

# 32. Management Doc 当前修订要求

本次同时：

```text
DM-CR-20260822-001 Review
PENDING_REVIEW → VERIFIED
```

因为 Development Management 初始化治理本身本轮通过。

同时：

```text
删除 §41 重复 R4-A2
更新 §40 状态表
更新 §41 优先级
更新 §52 风险
更新 §61 Change Log
```

---

# 33. 建议增加 Current Baseline Metadata

在文档头部增加：

```text
Current Code Baseline:
<latest code SHA>

Document Revision:
<latest docs SHA>

Last Review:
YYYY-MM-DD HH:mm +08:00

Last Reviewer:
Design / Audit Review
```

不要让：

```text
初始化依据仓库 HEAD
```

成为长期越来越旧的唯一代码定位信息。

---

# 34. Management Doc CI Guard

当前先不要做复杂语义推断。

建议第一版只对确定属于 Contract 的路径强制管理文档：

```text
data/golden/**
migrations/**
docs/adr/**
src/ashare_state/spike/capabilities.py
src/ashare_state/spike/golden_store.py
src/ashare_state/pipeline/publish.py
src/ashare_state/identity/security_id.py
```

这些路径变化：

```text
必须同时修改
docs/project/DEVELOPMENT_MANAGEMENT.md
```

其他普通 src bugfix 仍只强制 DEVLOG。

如果后面误报太多，再调整列表。

---

# 35. R4-A1.1 最终状态

本轮后应记录：

```text
R4-A1.1 Implementation
    DONE

R4-A1.1 Review
    REOPENED

Closed:
    manifest self-verification
    case semantic hash
    per-event gate
    append-only version selection
    full-history CI
    extended DEVLOG gate

Remaining:
    source artifact resolution/hash verification
    review workflow
    ST event-class semantics
    delist distinct security gate
    Domain Router
```

---

# 36. 下一阶段并行计划

```text
TRACK A

R4-A2
├─ Golden Review Evidence Closure
├─ Domain-specific Golden Router
├─ ST / Delist event semantics
├─ Adj continuity
├─ PIT Limit Rule
├─ History Coverage fixtures
└─ BSE / BJ

        ↓

R4-A3
├─ permission profile
├─ cache first/second pull
├─ freshness
├─ phase early stop
└─ auth terminal-state

        ↓

R4-B1
Capability Endpoint Proof

        ↓

R4-B2
Publish Validation Exactness


TRACK B

CR-1
ProviderExchange
    ↓
RawWriter
    ↓
CR-2
Provider-Normalized + Quarantine
```

---

# 37. 工作顺序裁决

优先级：

```text
1. R4-A2
2. CR-1（与 R4-A2 并行）
3. R4-A3
4. R4-B1
5. R4-B2
6. R4-CI
7. CR-2
```

不要等待正式 Provider 账号再写这些代码。

---

# 38. 暂时不要做

当前不要：

```text
Trend 大规模开发
PV / Vol / Stress
全历史 Backfill
Tushare Fusion
复杂调度
API/UI
```

先关闭：

```text
Formal Truth
+
Raw/Canonical Runtime
```

---

# 39. 下一次评审范围

下一次不做全仓“大审计”。

只检查：

## R4-A2

```text
External Source Evidence
Review Workflow
Golden Router
PIT Limit
Adj
History
BSE/BJ
```

## CR-1

```text
ProviderExchange identity
RawWriter immutability
failure envelope
SDK hidden calls
request_id lineage
```

## Management

```text
DM-CR-002/003/004
§40/41/52/61
DEVLOG time standard
```

达到：

```text
R4-A2 Review VERIFIED
CR-1 Review VERIFIED
```

后，直接进入：

```text
R4-A3 / CR-2
```

而不是重新审整个 M0 架构。

---

# 40. 提交纪律

每个实现 Commit：

```text
Code
Tests
DEVLOG
```

R4-A2 / CR-1 都属于管理总册已定义的 C1 Contract Work，因此：

```text
同一逻辑提交必须更新
docs/project/DEVELOPMENT_MANAGEMENT.md
```

开发人员完成后只写：

```text
Implementation Status = DONE
Review Status = PENDING_REVIEW
```

不得自行写：

```text
VERIFIED
```

---

# 41. 完成回报格式

开发完成后提交：

```text
Commit SHA(s):
Track:
Files Changed:
Tests:
GitHub CI:
DEVLOG:
Management Change ID:
Management Sections Updated:
Implementation Status:
Review Status:
Known Open Issues:
```

GitHub CI 必须区分：

```text
Local validation
GitHub Actions validation
```

不能把本地 pytest 结果写成远端 CI 已绿。
