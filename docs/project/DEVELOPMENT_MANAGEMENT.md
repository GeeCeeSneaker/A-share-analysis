# A-share-analysis 开发管理总册（Development Management）

> **仓库固定路径（MUST NOT RENAME）**：`docs/project/DEVELOPMENT_MANAGEMENT.md`  
> **文档性质**：长期持续维护的项目级“当前设计 + 当前状态 + 开发计划 + 变更控制”总册  
> **项目**：A股市场态势数据基座（日频模块）  
> **Frozen Baseline**：V1.3.2  
> **初始化依据仓库 HEAD**：`bb694c5`（按工作要求 §10 以最新 HEAD 同步，R4-A1.1 已落地）  
> **初始化日期**：2026-08-22  
> **状态**：ACTIVE / LIVING DOCUMENT

---

# 0. 文档定位

本文件不是新的 Frozen Baseline，也不是 `docs/DEVLOG.md` 的替代品。

它长期承担以下职责：

1. 统一描述系统当前按什么方案开发；
2. 统一描述当前开发进度、里程碑、Entry/Exit Gate、阻塞项；
3. 统一记录已批准的设计调整、数据语义调整、工程契约调整及原因；
4. 把 Frozen Baseline、ADR、Provider Verification、DEVLOG、Risk Register、审计报告、测试和代码提交串成一个可追踪体系；
5. 作为后续开发工作要求的管理入口：凡工作要求涉及设计、Schema、数据语义、Provider、PIT、版本血缘、Publish/Replay、Feature 公式或里程碑调整，开发人员必须在同一逻辑提交中更新本文件。

本文件必须保持“当前真相”属性；历史通过 Git、DEVLOG、ADR 和本文 Change Log 保留。

---

# 1. 文档权威性与优先级

发生冲突时按以下顺序解释：

```text
1. 明确批准的新 Frozen Baseline
2. 当前 Frozen Baseline V1.3.2
3. 已 APPROVED 的 ADR（不得与 Frozen Baseline 冲突）
4. 本文件的当前实施约束与状态
5. Provider Verification / Spike / Exit Report
6. docs/DEVLOG.md
7. Audit / Work Requirement / Working Notes
```

规则：

- V1.3.2 不得通过普通 Patch 静默改变核心语义；
- ADR 只能补充或替代实现级决策；
- 审计建议只有在实现、测试并纳入本文件/ADR/代码后，才成为当前实施契约。

---

# 2. 角色与责任

## Project Owner

负责：

- 业务目标和优先级；
- 是否接受重大设计变化；
- 是否允许 Frozen Baseline 升版；
- 正式数据账号、供应商和外部资源的最终确认。

## Development Executor

负责：

- 按工作要求实现；
- 每次代码提交同步 `docs/DEVLOG.md`；
- 设计/契约变化时同步本文件；
- Migration、测试、文档、代码保持一致；
- 不以“文档写完成”替代真实测试和运行证据。

## Design / Audit Reviewer

负责：

- 审查 PIT 正确性、数据语义、可复现性、Gate 可绕过性；
- 下达后续工作要求；
- 复核后将 `Review Status` 标记为 `VERIFIED` 或 `REOPENED`。

---

# 3. 强制维护规则

## 3.1 每次代码提交

修改以下任一路径时，必须同步更新 `docs/DEVLOG.md`：

```text
src/
migrations/
configs/
scripts/
data/golden/
.gitattributes
.github/workflows/
```

## 3.2 设计/契约变化

出现以下任一变化时，同一逻辑提交必须同步更新：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

触发范围包括：

```text
Architecture / Layering
Provider endpoint / capability / runtime
Security Identity / Universe / Trading Rule
Schema / Migration / Canonical Fact Contract
PIT / available_at / Availability Policy
Source Policy / Reconciliation
Raw / Canonical / Snapshot / Artifact / Publish / Replay lineage
Feature 定义、公式、输入、窗口、返回约定
State / Regime 数学定义
Golden Truth / Spike Gate / Capability Approval
CI / reproducibility / immutable storage contract
Concurrency ownership
Security / secrets
Milestone Entry / Exit Gate
```

## 3.3 普通 Bugfix

如果不改变外部语义、Schema、数据定义、Gate、版本与血缘，仅需更新 DEVLOG，不强制改本文件。

## 3.4 禁止静默调整

禁止“先改代码，后补设计文档”。C1/C2/C3 变化必须与代码、测试、本文件和 ADR（如需要）形成同一逻辑批次。

---

# 4. Change Control 分级

## C0 — Implementation Only

例：重构、性能优化、bugfix，外部契约不变。

要求：

```text
DEVLOG + Tests
```

## C1 — Contract Clarification

例：加强 Validator、增加不可绕过 Gate、明确已有字段含义。

要求：

```text
DEVLOG
DEVELOPMENT_MANAGEMENT
Contract Tests
```

## C2 — Design Change

例：改变数据流、SoR、Schema、Feature 公式、PIT、Publish/Replay、Provider 职责。

要求：

```text
DEVLOG
DEVELOPMENT_MANAGEMENT
ADR
Migration / Compatibility Plan（如适用）
Contract Tests
Review = PENDING_REVIEW
```

## C3 — Frozen Baseline Change

任何改变 V1.3.2 核心含义的变化。

要求：

```text
Project Owner 明确批准
新 Baseline Version
Impact Analysis
ADR
Migration / Backfill Plan
Regression Plan
DEVELOPMENT_MANAGEMENT
```

不得在普通 Patch 中完成。

---

# 5. Change Record 标准

C1/C2/C3 变化必须在文末追加：

```text
Change ID:
Type:
Date:
Status:
Trigger:
Old Contract:
New Contract:
Reason:
Affected Modules:
Affected Data:
Compatibility:
Migration / Backfill:
Tests:
ADR:
Commit:
Reviewer:
```

Change ID：

```text
DM-CR-YYYYMMDD-NNN
```

---

# 6. 项目目标

构建：

> Point-in-Time 正确、可复现、可审计、Provider-neutral、可扩展的 A 股市场态势数据基座。

系统首先回答：

```text
市场当前处于什么状态？
```

而不是直接回答：

```text
市场下一步会涨还是跌？
```

市场描述与预测、策略、执行分离。

---

# 7. 核心设计原则

```text
Raw → Canonical → Feature → State
Continuous first; labels derived
Description ≠ prediction
State labels mathematical
允许不确定性/冲突，不强制单一评分
Composite weights 必须在 incremental validity 后
所有 baseline 只使用 t-1 及更早信息
available_at / ingested_at / provider / version 可追踪
Exact Replay 必须成立
Provider semantic label 不作为核心市场事实
ST / Suspended / Corporate Action / Limit Rule 必须 PIT
所有价格限制使用实际法律规则，不硬编码 ±10/20
```

---

# 8. 系统分层

```text
L0  PIT Security Universe / Industry Membership / Trading Rules
L1  Fact / Raw Observations
L2  Canonical Provider-independent Data
L3  Feature
L4  State
L5  Regime
L6  Historical Conditional Return / Risk

Strategy / Portfolio / Execution
    与数据基座分离
```

Realtime 与日频尽量共享定义，不能形成两套相互矛盾的市场语义。

---

# 9. Provider-neutral 总体架构

```text
AmazingData / TGW
Tushare
QMT
        ↓
Provider Adapter / Normalization
        ↓
Raw Immutable Evidence
        ↓
Provider-Normalized
        ↓
Source Policy / Reconciliation
        ↓
Canonical Selected
        ↓
Snapshot
        ↓
Feature Artifact
        ↓
Publish
        ↓
State / Regime / Analysis
```

当前原则：

- AmazingData：市场事实、历史/实时 L1、Security/Status、Daily/Kline、Limit、Adjustment/CA、Snapshot；
- Tushare：free_share、明确 SW/CITIC taxonomy、主题 membership、专项交叉验证；
- QMT：Realtime、Trading、Realtime cross-check。

任何 Provider 角色变化都属于 C1/C2，必须更新本文件。

---

# 10. Observation Type

Provider/Canonical 数据必须区分：

```text
DIRECT_OBSERVATION
DERIVED_FACT
PROVIDER_DERIVED
SEMANTIC_LABEL
```

不得把 Provider 算法标签伪装成直接市场事实。

---

# 11. Security Identity

正式 Security ID：

```text
UUIDv5(
    normalized_exchange
    + asset_type
    + initial_symbol
    + first_list_date
)
```

原则：

- Provider suffix 不定义实体身份；
- Temporary fallback 仅允许 Spike/Staging/Quarantine；
- Publish Path 禁止 Fallback Identity；
- 正式 Publish 后不得 re-key；
- Provider Symbol Mapping 必须 effective-date aware。

---

# 12. Universe

核心可交易 Universe：

```text
CORE_TRADABLE_V1
=
listed
+ valid bar
+ not suspended
```

不得把 20/60 日历史不足写进 Universe。

Feature 自己通过：

```text
valid_mask
valid_n
```

表达窗口不足。

Universe 必须 PIT，包括 list/delist、ST、suspension、board、trading rule。

---

# 13. Trading Rules

必须使用实际历史制度：

```text
Main Board
ST / *ST
ChiNext
STAR
BSE
IPO / first-N-day no-limit
special resumption
tick size
rounding
```

历史规则必须有：

```text
effective_from
effective_to
```

价格计算使用明确 Decimal rounding，不使用语言默认 round 代替交易所规则。

---

# 14. Point-in-Time / Availability

任何 Canonical Fact 在 Validated Snapshot 前必须有：

```text
available_at
availability_kind
availability_policy_version
ingested_at
```

首批：

```text
OBSERVED
CONSERVATIVE_ASSUMED
```

历史回补不得伪称知道历史 provider 的真实可用时间。

无法给出安全 available_at 的记录：

```text
QUARANTINE / NOT_VALIDATED
```

不得 Publish。

---

# 15. Storage / System of Record

当前原则：

```text
Raw Immutable File = Provider Evidence
Canonical Parquet  = Canonical System of Record
DuckDB fact_*      = Rebuildable Read Model
```

Provider SDK 自带 HDF5/缓存只是 ingestion cache，不是系统 SoR。

任何 Read Model 必须能从 Snapshot Manifest + Canonical Parquet 重建。

---

# 16. Immutable File Contract

```text
Final Path 不存在
→ commit

已存在且 hash 相同
→ idempotent

已存在且 bytes/hash 不同
→ BLOCK
```

Phase 0 当前：

```text
Single DB/File Commit Owner Process
```

Worker 可并发下载/计算，但不应跨进程直接争抢 Final Commit。

---

# 17. Raw Evidence / ProviderExchange

目标统一审计单元：

```text
ProviderExchange {
    RawEnvelope
    Payload
}
```

一个 Exchange 的 `request_id` 必须贯穿：

```text
Provider
→ Spike
→ RawWriter
→ Provider-Normalized
→ Canonical lineage
```

失败 Exchange 也保存 RawEnvelope。

Raw Evidence 必须：

```text
immutable
secret-scrubbed
hash-sealed
lossless
```

禁止以 `repr()` 截断替代原始数据。

---

# 18. Canonical Core Fact Domains

Real P0a 第一批只做：

```text
daily_bar
security_status
limit_price
adj_factor
corporate_action
```

每条 Canonical Fact 至少具有：

```text
security_id
trade_date / effective time
selected_provider
provider_dataset
observation_type
availability_kind
available_at
availability_policy_version
source_policy_version
source_revision
data_version
schema_version
selection_reason
reconciliation_status
quality_flags
ingested_at
```

---

# 19. Source Policy

状态：

```text
CANDIDATE
APPROVED
RETIRED
```

原则：

```text
同一 Domain 不允许重叠 APPROVED policy
APPROVED version 后不可原地修改
新语义 = 新 Version
```

正式 Source Policy DB 不可变写路径仍属于 P0b 前待完成项。

---

# 20. Snapshot

Snapshot 必须绑定：

```text
data_snapshot_id
source_policy_version
availability_policy_version
components
logical_uri
content_hash
manifest_hash
```

不允许 glob 推断输入；metadata 只在 Validated 后创建。

---

# 21. Feature Artifact

Feature 结果必须绑定：

```text
feature_artifact_set_id
data_snapshot_id
feature_set_version
calc_run_id
code_commit
environment_lock_hash
config_hash
components
feature manifest
```

不得允许“只知道 Snapshot ID 就猜 Feature”。

---

# 22. Publish

Publish 必须绑定：

```text
publish_id
data_snapshot_id
feature_artifact_set_id
feature_set_version
pipeline_run_id
artifact_validation_id
```

规则：

```text
任何 Publish 都必须有 Run
Recovery / Republish 也必须建对应 Run
```

Publish 前 Gate：

```text
Snapshot Validated
Artifact Validated
FeatureSet Active + hash self-check
Universe Valid
Identity fallback count = 0
blocking DQ count = 0
Run/Artifact/Snapshot/Policy/Code/Config lineage 一致
```

---

# 23. Exact Replay

通过 `publish_id` 必须能精确找回：

```text
Snapshot
Feature Artifact
Feature Set
Validation
Run
Code Commit
Environment Lock
Config
Source/Availability Policy
```

任何 `latest` 默认解析不得改变已发布历史语义。

---

# 24. Feature / State System

State 维度：

```text
Breadth
Trend
Price–Volume
Volatility
Risk Appetite
Stress
Style
Payoff / Feedback
Structure / Rotation
Tradability / Opportunity Accessibility
```

每个 Feature/State 应有：

```text
Level
Velocity
Acceleration
Duration
Percentile
Confidence
Divergence
```

---

# 25. Trend BASE 首批公式

```text
RET_N = ln(P_t / P_{t-N})
N = 5, 20, 60
```

```text
SER_N =
sum(r)
/
sum(abs(r))
```

首批还包括：

```text
UP_DAY_RATIO
MA_DIST
MA_BREADTH
POS_RET_BREADTH
NEW_HIGH
NEW_LOW
```

Canonical Vertical Slice 通过前，不扩大完整 PV/Vol/Stress/Theme/Style。

---

# 26. Price–Volume 关键约定

后续：

```text
TOR_RATIO20 =
TOR_t / median(TOR_{t-20:t-1})

PV_PRICE_RESPONSE_020
    canonical standardized response

RAD_LIMIT_NORM
    raw Close/PreClose-1
    denominator = actual legal limit
    NO_LIMIT separate

PV_EFF_N =
RET_N / sum(turnover_rate_f)
```

`FLOAT_A_SHARE` 不得未经验证等同 Tushare `free_share`。

---

# 27. Breadth / Vol / Stress 后续范围

Breadth：

```text
ADV / DEC / FLAT
quantiles / IQR / tails
strong/weak standardized response breadth
participation HHI / Effective N
```

Volatility：

```text
close-close 5/20/60
Parkinson
cross-sectional IQR/tail
downside semivol
vol breadth
vol5/vol60
```

Stress：

```text
weak-tail breadth
weak-tail amount share
DD_N
new lows
down-limit pressure
response × turnover downside matrix
```

---

# 28. Feature Audit Framework

Feature/State 上线前：

```text
Reliability
Logic
Distribution
Redundancy
Incremental validity
Out-of-sample
Multiple testing
```

历史条件回报至少：

```text
1 / 3 / 5 / 10 / 20 trading days
```

---

# 29. Provider Capability Governance

Capability Approval 必须系统自证，不接受调用者声明“通过”。

最终应验证：

```text
Closed PRODUCTION SpikeRun
Complete Provenance
Evidence Closure
Golden Truth Binding
Required Case Types
Required Case Counts
Required Provider Endpoints
Account Profile
Blocking Reasons = []
```

Capability 记录必须能说明 provider、dataset、endpoint、频率、历史/实时、PIT grade、account profile、SDK/runtime 和 verified_at。

---

# 30. Golden Truth 治理

正式 Golden Truth 必须：

```text
Versioned
Human Reviewed
Externally Evidenced
Hash Sealed
Event Diverse
```

当前状态（2026-08-22 R4-A1.1 后）：

```text
R4-A1.1 Implementation = DONE
R4-A1.1 Review         = PENDING_REVIEW
```

当前 v2 是：

```text
COMPILED Candidate Dataset（v2-candidate-20260822）
```

不是正式 Reviewed Truth。

v2 相比 v1 的落地（R4-A1.1）：
manifest 统计从 cases 复算、case_semantic_hash/source_artifact_hash 分离、
case_type 进入 semantic hash、event_id/event_class + distinct-event gate、
append-only 版本（v1/v2 + ACTIVE 指针）。
诚实覆盖状态：ST_CAP=2<50、DELIST=10<20 —— PRODUCTION run 在 golden
review 补齐真实事件前被创建门拒绝。

Domain-specific Golden Probe Router 按审计 §7 并入 R4-A2。

Production Verdict 必须等 Review Gate PASS。

---

# 31. Golden Truth 当前待修

R4-A1.1 已完成（Implementation DONE / Review PENDING_REVIEW）：

```text
[x] Manifest stats 从 cases 复算（篡改即拦截）
[x] case_semantic_hash / source_artifact_hash 分离
[x] case_type 进入 semantic hash
[x] event_id / event_class
[x] distinct-event coverage（PRODUCTION run 创建门拒绝）
[x] append-only Golden Version（v1/v2 + ACTIVE 指针）
[ ] domain-specific Golden Probe Router（并入 R4-A2，审计 §7）
```

Golden Review Workflow（R4-A1.1 后仍开放）：
人工 review 逐条核验 → 补齐 ≥50 distinct ST_CAP / ≥20 distinct DELIST
真实事件 → 封存外部工件 source_artifact_hash → REVIEWED → 版本 v3。

Domain Router：

```text
ST
→ history_stock_status

Limit
→ status + PIT trading rule

Delisted
→ historical security master / stock basic

Corporate Action
→ dividend/right issue + adj factor + price context

BJ Mapping
→ BJ mapping + historical effective-date mapping
```

---

# 32. Provider Account / Environment

当前仍处于正式账号开通前准备阶段。

试用/仿真账号只用于基础 L1 Snapshot 连接与有限订阅测试，不用于证明历史核心事实，也不用于推导正式平台 Capacity。

正式 P0-M-1B 前必须：

```text
正式账号 Profile 人工确认
freeze production_account_profile_id
Provider Doctor = RUNTIME_ACTUAL_LOAD_VERIFIED
完整权限/endpoint 验证
```

---

# 33. Trial L1

建议：

```text
1 → 5 → 20 symbols
```

验证：

```text
login
subscribe lifecycle
callback
provider_event_time
received_at
bid/ask
cumulative volume/amount
trading phase
unsubscribe
reconnect
```

100 symbol 只用于订阅上限行为。

---

# 34. 技术栈与 SDK 原则

```text
Python
uv
DuckDB
Parquet
Windows / Linux
```

AmazingData/TGW：

```text
External Commercial Provider Runtime
```

要求：

```text
Core uv.lock 不写商业 wheel 机器绝对路径
Local setup script 安装 SDK
Adapter lazy import
CI 使用 Fixture/Fake Provider
Secrets 不进入 Git
wheel 不进入 Git
```

---

# 35. DuckDB 并发

Phase 0：

```text
一个进程拥有读写 DB
```

不要假设多个外部进程可同时无约束访问同一文件。

多进程/零停机属于未来单独 ADR。

---

# 36. CI / Quality Gate

最小 Gate：

```text
ruff
format
mypy
pytest
python -m compileall scripts
Spike dry-run
Migration continuity
DEVLOG change gate
```

GitHub Actions 应使用完整历史：

```text
actions/checkout fetch-depth: 0
```

以保证 Git lineage/DEVLOG Gate 生效。

---

# 37. Test Taxonomy

```text
Unit
Contract
Integration
Fixture Vertical Slice
Live Trial
Production Spike
Historical Replay
```

Dry-run/Fake 不能代替 Formal Provider Truth。

---

# 38. Migration 规则

```text
001..N 连续
已执行 Migration 不修改
已执行 Migration 不删除/改名
Runner 记录 content hash
Schema 修复只能新增 Migration
```

---

# 39. Secrets / Security

Git 禁止：

```text
用户名
密码
Token
Secret
商业 SDK wheel
生产私密配置
```

Evidence/Log/Exception 必须 scrub secret。

---

# 40. 当前项目阶段状态

| Workstream | Implementation | Review | 当前结论 |
|---|---|---|---|
| P0-M0 Engineering Foundation | DONE | VERIFIED | PASS |
| Round-1/2 Architecture Hardening | DONE | VERIFIED/absorbed | PASS |
| R3 Formal Spike Structure | DONE | absorbed by R4 | STRUCTURE PASS |
| R4-A1 Golden Dataset / Per-Type Gate / Catalog Seal | DONE | REOPENED | 由 A1.1 修复 |
| R4-A1.1 Truth Integrity | DONE | PENDING_REVIEW | 最高优先（已完成，待复核） |
| R4-A2 Semantic/PIT Validators | PLANNED | PENDING | Next |
| R4-A3 SDK/Lifecycle/Early Stop | PLANNED | PENDING | Next |
| R4-B1 Capability Endpoint Proof | PLANNED | PENDING | Next |
| R4-B2 Publish Validation Exactness | PLANNED | PENDING | Next |
| R4-CI | PLANNED | PENDING | Next |
| CR-1 ProviderExchange + RawWriter | READY | PENDING | 可并行 |
| CR-2 Provider-Normalized + Quarantine | PLANNED | PENDING | CR-1 后 |
| CR-3 Availability + Canonicalizer | PLANNED | PENDING | CR-2 后 |
| CR-4 Snapshot + Read Model Rebuild | PLANNED | PENDING | CR-3 后 |
| Mock 20×60d Vertical Slice | BLOCKED | PENDING | CR-1..4 后 |
| Production P0-M-1B | BLOCKED | PENDING | 正式账号 + R4 |
| Real P0a | BLOCKED | PENDING | Provider + Canonical Runtime |
| Trend BASE | BLOCKED | PENDING | Real Vertical Slice 后 |

---

# 41. 当前最高优先级

## R4-A2（R4-A1.1 已完成后接续）

```text
Adj T-1/T/T+1 price context
删除 B3 现场 expected_is_st=False
History Coverage 固定样本
PIT Limit Rule
Decimal ROUND_HALF_UP
BSE Security Master
BJ effective-date mapping
Domain-specific Golden Router（自 R4-A1.1 并入）
```

## R4-A2

```text
Adj T-1/T/T+1 price context
删除 B3 现场 expected_is_st=False
History Coverage 固定样本
PIT Limit Rule
Decimal ROUND_HALF_UP
BSE Security Master
BJ effective-date mapping
```

## R4-A3 / B1 / B2

```text
permission/cache/freshness 分 Gate
Early Stop
Auth terminal-state
Approval endpoint proof
explicit artifact_validation_id
Migration 011
```

## CR-1

可立即并行：

```text
ProviderExchange
RawWriter
```

---

# 42. Canonical Runtime Roadmap

```text
CR-1 ProviderExchange + RawWriter
        ↓
CR-2 Provider-Normalized + Quarantine
        ↓
CR-3 AvailabilityPolicy + Canonicalizer
        ↓
CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild
        ↓
CR-A Fixture 20 securities × 60 trading days
        ↓
P0-M-1B Production Provider Verification
        ↓
CR-B AmazingData 20 × 60
        ↓
Real P0a
        ↓
Trend BASE
```

---

# 43. CR-1 Acceptance

输入：

```text
ProviderExchange
```

输出：

```text
Raw immutable payload
RawEnvelope
logical_uri
content_hash
schema_hash
row_count
meta_ingest_run
```

要求：

```text
success exchange → payload persisted
failed exchange → envelope persisted
request_id 不变
secret scrub
immutable
same-hash retry idempotent
different bytes same URI block
```

---

# 44. CR-2 Acceptance

```text
Raw
→ Provider Mapper
→ Provider-Normalized
```

Mapping Validation 失败进入 Quarantine，不得 silent drop / 1970 / 0.0 sentinel。

---

# 45. CR-3 Acceptance

首批：

```text
daily_bar
security_status
limit_price
adj_factor
corporate_action
```

所有 Publishable Canonical Row 必须完整满足 PIT/Governance fields。

---

# 46. CR-4 Acceptance

```text
Canonical Parquet
→ Snapshot Manifest
→ DuckDB rebuild
```

Acceptance：

```text
清空 DuckDB read model
→ 只凭 Snapshot + Parquet 重建
→ key / row / aggregate 一致
```

---

# 47. Mock Vertical Slice

范围：

```text
20 securities × 60 trading days
```

完整链：

```text
Fixture Provider
→ ProviderExchange
→ Raw
→ Provider-Normalized
→ Canonical
→ Snapshot
→ DuckDB Rebuild
→ Skeleton Artifact
→ Artifact Validation
→ Publish
→ Exact Replay
```

---

# 48. 正式 P0-M-1B Entry Gate

必须全部满足：

```text
[ ] R4 Formal Spike P0 = 0
[ ] Golden Reviewed Version
[ ] External Source Artifact Hash
[ ] Distinct-event Gate
[ ] Golden Manifest / Catalog Seal
[ ] Domain-specific Golden Router
[ ] Production Account Profile Freeze
[ ] Provider Doctor actual runtime verified
[ ] clean working tree
[ ] full Git SHA
[ ] uv.lock hash
[ ] config hash
[ ] Capability endpoint proof
```

---

# 49. Formal Flow

```text
Provider Doctor
→ Production Account Gate
→ ONE Production SpikeRun
→ B2 + Phase Gate
→ B3 + Phase Gate
→ B4 Golden + Phase Gate
→ B5
→ B6
→ B7
→ Seal
→ Close
→ Evidence Closure
→ Verdict
→ Human Review
→ Capability Approval
```

`NOT_TESTABLE / framework incomplete`：

```text
SPIKE_INCOMPLETE
```

只有充分验证后核心失败才是：

```text
NO_GO
```

---

# 50. Milestone Eligibility

Provider Verdict 与 Milestone 分离：

```text
provider_verdict:
    GO_CORE
    GO_DEGRADED
    NO_GO
    SPIKE_INCOMPLETE

milestone:
    p0a_eligible
    p0b_eligible
    historical_backfill_eligible
```

---

# 51. Performance 放量

```text
Stage A  20 securities × 60d
Stage B  100 securities × 2y
Stage C  ALL_A × 1 month
Stage D  Full Historical Backfill
```

每级必须过：

```text
DQ
Exact Replay
Coverage
Performance
```

---

# 52. 风险摘要

详细风险继续维护 `docs/risk_register.md`。

## RISK-001 Formal Golden Truth 未闭环

```text
Status: OPEN
Impact: False GO / False NO_GO
Mitigation: R4-A1.1 已落地（integrity gates as code）；
           剩余：Golden Router（R4-A2）+ 人工 Review Workflow
           补齐 distinct events 并封存外部工件
```

## RISK-002 正式 Provider 账号未验证

```text
Status: OPEN / EXTERNAL
Impact: 历史权限/吞吐/Endpoint 无正式证据
Mitigation: P0-M-1B
```

## RISK-003 Source Policy Production Immutability

```text
Status: OPEN
Deadline: 首个 APPROVED Source Policy 前
```

## RISK-004 ProviderExchange 未统一

```text
Status: OPEN
Mitigation: CR-1
```

---

# 53. Technical Debt

```text
TD-001 历史 audit/work_report 较多
    不影响运行；不删除 Git 历史

TD-002 Spike/Canonical 尚未共享 ProviderExchange
    CR-1

TD-003 CI Governance full-history checkout 待完善
    R4-CI
```

---

# 54. ADR 触发规则

必须新增 ADR：

```text
改变 SoR
改变 DB ownership/concurrency
改变 Security ID
改变 Publish/Replay lineage
改变 Provider primary/fallback
改变 Canonical Fact model
改变 Feature formula semantics
改变 State/Regime mathematics
改变 Frozen Baseline
```

普通 bugfix、测试补充、实现级重构通常不需要 ADR。

---

# 55. 文档体系索引

```text
docs/design/A股市场态势数据基座_日频模块_V1.3.2_开发方案.md
    Frozen Baseline

docs/project/DEVELOPMENT_MANAGEMENT.md
    当前项目管理总册

docs/DEVLOG.md
    单一滚动开发日志

docs/adr/
    Architecture Decision Records

docs/provider_verification/
    Provider Verification

docs/spike_report_p0m1.md
    Provider Spike

docs/m0_exit_report.md
    M0 Exit

docs/risk_register.md
    Risk Register

docs/runbook/
    Runbooks

docs/design/*审计*
    历史审计/工作要求
```

---

# 56. 工作流程

```text
Reviewer 下达 Work Requirement
        ↓
标记是否触发 DEVELOPMENT_MANAGEMENT 更新
        ↓
Developer 实现
        ↓
同 Commit 更新 DEVLOG
        ↓
C1/C2/C3 同 Commit 更新 DEVELOPMENT_MANAGEMENT
        ↓
ADR / Migration（如需要）
        ↓
Tests / CI
        ↓
Implementation = DONE
Review = PENDING_REVIEW
        ↓
Reviewer Recheck
        ↓
VERIFIED / REOPENED
```

---

# 57. 后续 Work Requirement 的文档条款

凡工作要求引起 C1/C2/C3，工作要求中必须写：

```text
Documentation Update Required: YES

Target:
docs/project/DEVELOPMENT_MANAGEMENT.md

Required Sections:
<章节>

Change ID:
DM-CR-...

Same-commit rule:
Code + Tests + DEVLOG + DEVELOPMENT_MANAGEMENT
must be in the same logical change set.
```

---

# 58. Definition of Done

Implementation DONE：

```text
[ ] Code
[ ] Tests
[ ] Migration if required
[ ] DEVLOG
[ ] DEVELOPMENT_MANAGEMENT if C1/C2/C3
[ ] ADR if required
[ ] No secret/wheel leakage
[ ] Static gates
[ ] Evidence/Replay requirements
[ ] Known issues recorded
```

Review VERIFIED 还要求：

```text
[ ] Code-level recheck
[ ] Gate cannot be bypassed
[ ] Docs match runtime
[ ] No false PASS / false GO path
```

---

# 59. 状态枚举

Implementation：

```text
PLANNED
READY
IN_PROGRESS
DONE
BLOCKED
DEFERRED
```

Review：

```text
PENDING_REVIEW
VERIFIED
REOPENED
NOT_REQUIRED
```

Runtime/Gate：

```text
PASS
FAIL
BLOCKED
SPIKE_INCOMPLETE
NOT_TESTABLE
```

禁止“基本完成/差不多通过/应该没问题”等模糊状态。

---

# 60. 版本与更新时间

永远维护同一路径：

```text
docs/project/DEVELOPMENT_MANAGEMENT.md
```

每次 C1/C2/C3：

1. 更新受影响设计章节；
2. 更新“当前项目阶段状态”；
3. Change Log 顶部追加；
4. DEVLOG 同步；
5. Git 保存过去版本。

---

# 61. Change Log

> 新条目倒序追加，不删除历史。

## DM-CR-20260822-001 — 建立 Development Management 总册

**Type**：C1 / Governance  
**Status**：PENDING_REVIEW  
**Trigger**：项目进入多轮审计、Formal Spike 与 Canonical Runtime 并行阶段，需要统一长期管理入口。  
**Old Contract**：设计、进度、审计、风险、日志分散在多个文档。  
**New Contract**：建立 `docs/project/DEVELOPMENT_MANAGEMENT.md`，统一维护当前设计摘要、状态、Gate、Roadmap、变更控制和文档索引。  
**Reason**：降低语义漂移，避免“代码改变而当前方案不同步”。  
**Affected Modules**：Documentation / Governance  
**Affected Data**：None  
**Compatibility**：不改变运行时代码。  
**Migration / Backfill**：None  
**Tests**：建议加入 management-doc governance test。  
**ADR**：Not Required  
**Commit**：待上传仓库后填写  
**Reviewer**：PENDING_REVIEW

---

# 62. 下一次维护检查点

完成 R4-A1.1 后至少更新（**本次初始化已按最新 HEAD 同步完成**）：

```text
§30 §31 §40 §41 §52   (done 2026-08-22, 见 DM-CR-20260822-001)
§48                    (R4-A2 Golden Router 落地时更新)
§61                    (Change Log 持续追加)
```

完成 CR-1 后至少更新：

```text
§17
§40
§42
§43
§52
§61
```

---

# 63. 项目管理原则总结

```text
Frozen Baseline 不静默漂移
Design Change 必须有 Change Record
Code / Tests / DEVLOG / Management Doc 同步
Data Definition 先于 Feature Expansion
PIT 正确性先于“有数据”
Exact Replay 先于“跑得快”
Formal Truth 先于 GO/NO-GO
Canonical Runtime 先于大规模 Feature
```

本文件长期持续维护，不另起 `DEVELOPMENT_MANAGEMENT_v2/v3.md`。
Git 历史负责保存过去版本。
