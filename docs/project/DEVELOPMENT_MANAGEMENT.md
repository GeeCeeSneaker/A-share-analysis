# A-share-analysis 开发管理总册（Development Management）

> **仓库固定路径（MUST NOT RENAME）**：`docs/project/DEVELOPMENT_MANAGEMENT.md`  
> **文档性质**：长期持续维护的项目级“当前设计 + 当前状态 + 开发计划 + 变更控制”总册  
> **项目**：A股市场态势数据基座（日频模块）  
> **Frozen Baseline**：V1.3.2  
> **Current Code Baseline**：本批提交（R4-A2.6 Formal Truth/Manifest Closure + CR-1.2.2 Probe Exchange Enforcement）；上一批 implementation SHA `13d02a191f11c22b836da42ae9ae5707f9e355f1` / 复审基线 HEAD `cdd360879c3a6361f4c952bde39174d3d46dfbcb`（本批提交后以其 commit SHA 为新基线）  
> **Document Revision**：DM-CR-20260825-004 / 005 / 006 / 007  
> **Last Review**：2026-08-25（R4-A2.5/CR-1.2.1 复审：REOPENED——4 项 P0 + 3 项 P1 + 治理修正，本批 R4-A2.6/CR-1.2.2 修复）  
> **Last Reviewer**：Design / Audit Review  
> **CI Status**：**VERIFIED GREEN**（Reviewer 2026-08-25 确认 run 36/HEAD cdd3608 与 run 35/13d02a1 均 success）；后续提交以 Actions 实际结果为准  
> **状态**：ACTIVE / LIVING DOCUMENT  
> **时间标准**：本文档所有人读时间使用 `YYYY-MM-DD HH:mm +08:00`（Asia/Shanghai）或仅日期；trade_date / market session / human timestamp 必须明确区分。

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

> **当前状态（2026-08-25，R4-A2.6 批次统一）**：Golden Truth 结构治理
> 全部就绪（immutable versions v1/v2/v3 + ACTIVE 指针 + semantic hash +
> distinct-event gate + bound formal gates + domain router + typed CA
> event truth）。**当前 ACTIVE = v3 COMPILED 候选**（123 cases；结构化事件
> ST_TRANSITION=10<50、DELIST symbols=10<20 不足），**不是正式 Reviewed
> Truth**——PRODUCTION run 在人工 review 补齐真实事件前被创建门拒绝。
> 人工执行项与最新细节见 §31；历史沿革见 DEVLOG（管理总册只保留当前真相）。

Production Verdict 必须等 Review Gate PASS。

---

# 31. Golden Truth 当前待修

> 2026-08-25 状态（R4-A2.4/CR-1.2 复审 §10.4 改写；原文过时陈述已清除）：

结构侧全部闭环（多轮审计吸收）：

```text
[x] Manifest stats 从 cases 复算（篡改即拦截）
[x] case_semantic_hash / source_artifact_hash 分离
[x] case_type 进入 semantic hash
[x] event_id / event_class
[x] distinct-event coverage（PRODUCTION run 创建门拒绝）
[x] append-only Golden Version（v1/v2/v3 + ACTIVE 指针）
[x] domain-specific Golden Probe Router（R4-A2.3/CR-1.2，evidence bundle 同源）
[x] bound formal gates（verdict 只用 run-bound dataset，ACTIVE 推进/篡改不泄漏）
```

剩余为**人工执行**（结构已就绪，不可再由开发者代办）：

```text
[ ] 人工 review 123 v3 cases（scripts/golden/review.py）
[ ] 补齐 ≥50 distinct ST_TRANSITION 结构化事件（当前 10）
[ ] 补齐 ≥20 distinct DELIST symbols（当前 10）
[ ] 封存外部工件 source_artifact_hash → 产出 REVIEWED 版本
```

Domain Router（已实现，R4-A2.4/CR-1.2 证据同源 + bundle 闭合）：

```text
ST          → history_stock_status
Limit       → status + hist master(listing_date) + PIT calendar + run-bound rule book
Delisted    → historical security master / stock basic
Corp Action → calendar + status + dividend + right_issue + adj + kline T-1/T/T+1
BJ Mapping  → hist master（code continuity）+ exact-date status ±30%
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
| R4-A1 Golden Dataset / Per-Type Gate / Catalog Seal | DONE | absorbed | PASS（由 A1.1 闭环） |
| R4-A1.1 Truth Integrity | DONE | absorbed | PASS（由 R4-A2 批次闭环） |
| R4-A2.1/A2.2 Semantic/PIT Validators + Review Workflow | DONE | absorbed | PASS（由 R4-A2.3 闭环） |
| R4-A2.3 Correctness Closure | DONE | absorbed into R4-A2.6 | 结构保留；最终 VERIFIED 随 R4-A2.6 门（不预写 PASS） |
| CR-1 ProviderExchange + RawWriter | DONE | absorbed into CR-1.2.2 | 结构保留；最终 VERIFIED 随本批门 |
| CR-1.1 Explicit Exchange Runtime | DONE | absorbed into CR-1.2.2 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.4 Correctness Deepening | DONE | absorbed into R4-A2.6 | 结构保留；最终 VERIFIED 随本批门 |
| CR-1.2 Complete Exchange + Raw Closure | DONE | absorbed into CR-1.2.2 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.5 Rule-SoR Closure + CR-1.2.1 Raw Hardening | DONE | REOPENED | 由 R4-A2.6/CR-1.2.2 修复（本批） |
| R4-A2.6 Formal Truth/Manifest Closure + CR-1.2.2 Probe Exchange Enforcement | DONE | PENDING_REVIEW | 最高优先（已完成，待复核） |
| R4-A3 SDK/Lifecycle/Early Stop | PLANNED | PENDING | Next |
| R4-B1 Capability Endpoint Proof | PLANNED | PENDING | Next |
| R4-B2 Publish Validation Exactness | PLANNED | PENDING | Next |
| R4-CI | PLANNED | PENDING | Next |
| CR-2 Provider-Normalized + Quarantine | PLANNED | PENDING | CR-1.1 后 |
| CR-3 Availability + Canonicalizer | PLANNED | PENDING | CR-2 后 |
| CR-4 Snapshot + Read Model Rebuild | PLANNED | PENDING | CR-3 后 |
| Mock 20×60d Vertical Slice | BLOCKED | PENDING | CR-2..4 后 |
| Production P0-M-1B | BLOCKED | PENDING | 正式账号 + R4 + Golden 人工 Review |
| Real P0a | BLOCKED | PENDING | Provider + Canonical Runtime |
| Trend BASE | BLOCKED | PENDING | Real Vertical Slice 后 |

---

# 41. 当前最高优先级

## R4-A2.6 + CR-1.2.2（本批，DONE / PENDING_REVIEW）

```text
CR-1.2.2 Probe Exchange Enforcement（P0-01，DM-CR-20260825-004）：
  B5/B6 code-list 前置改走 ProbeExecutor.call（成功/失败都持久化 +
    失败→结构化 case；B6 前连成功都不持久化）
  B6 依赖前置失败→stock_basic 不发射
  AST 双守卫：probes 的 ctx.target.*_exchange 调用必须在 lambda 内
    （executor 边界）；golden_router 的必须在 collector.persist(...) 内
    （approved boundary 显式化，不靠开发者记忆）
  Spy 计数闭合：B2-B7 每 probe 真实 exchange 调用数 == 持久化 meta 数
R4-A2.6 Golden CA Typed Truth（P0-02，DM-CR-20260825-005）：
  event_class（已入语义 hash）成为类型事实源：
    DIVIDEND_EX_DATE→DIVIDEND / RIGHT_ISSUE_EX_DATE→RIGHT_ISSUE
  expected_fields.event_type 与 event_class 冲突→fail closed；
    unknown/untyped→fail closed（旧 untyped-accepts-any 测试反转）
  validator v5；真实 v3 全部 20 个 CA cases 解析为 DIVIDEND 并参与校验
    （actual-truth regression，非 synthetic-only）
R4-A2.6 Rule Manifest Confinement + Coherence（P0-03/04，DM-CR-20260825-006）：
  dataset_files[] confinement 于任何 fs 访问前（相对/无 ../无绝对/
    symlink resolve 仍须在 root 内；且必须在 versions/<rule_version>/ 下
    ——selector 与版本目录结构一致；ACTIVE 与 bound 共用同一 helper）
  manifest↔dataset 治理字段强制一致（review_status/source_version/
    review_provenance（语义等价，空值键豁免，datetime 规范化）/
    dataset_version）；真实 manifest 的 source_version 不一致已修正
  SpikeRun 绑定分离 selector version（manifest.rule_version）与 dataset
    content version（yaml.version）+ source_version；load_bound 双版本复验
P1（DM-CR-20260825-006/007 内）：
  provenance_complete() 纳入 rule binding（selector+files+hash+status）
  review.py：manifest 原子切换（tmp+os.replace）+ --from-version 血缘
    检查 + 非 ACTIVE 输入拒绝 + 切换后 coherence 自验证
  raw partial-orphan 集语义：present-成员字节一致的 same retry→恢复
    （补缺成员+meta）；orphan 集含未声明成员→整集隔离；quarantined
    bytes 不算 active orphan；恢复后 closure 干净
```

## Golden / Trading Rule 人工 Review（结构就绪，等人工执行）

```text
scripts/golden/review.py 逐条核验 123 v3 cases + 补齐 distinct events
scripts/rules/review.py 对 ACTIVE 规则版本执行人工复核（--from-version
  血缘检查；产出 REVIEWED 版本并原子切换 ACTIVE）
```

## R4-A3 / B1 / B2（CR-2 前；CR-2 仍 BLOCKED 直到 R4-A2.6/CR-1.2.2 VERIFIED）

```text
permission/cache/freshness 分 Gate
Early Stop
Auth terminal-state
Approval endpoint proof
explicit artifact_validation_id
Migration 011
```

## 后续 CR

```text
CR-2 Provider-Normalized + Quarantine（消费 raw evidence → provider-normalized）
CR-3 AvailabilityPolicy + Canonicalizer
CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild
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

# 43. CR-1 / CR-1.1 Acceptance

CR-1 输入：

```text
ProviderExchange
```

CR-1 输出：

```text
Raw immutable payload
RawEnvelope
logical_uri
content_hash
schema_hash
row_count
meta_ingest_run
```

CR-1 要求：

```text
success exchange → payload persisted
failed exchange → envelope persisted
request_id 不变
secret scrub
immutable
same-hash retry idempotent
different bytes same URI block
```

CR-1.1（Runtime Closure，R4-A2.3 §3-§5 补充）要求：

```text
target.*_exchange 显式 API（RealTarget + FakeTarget，dry-run 同管线）
运行时无 last_envelopes 反查（diagnostic-only，AST 静态测试）
ProbeExecutor.call(fn)：fn 必须返回 ProviderExchange（否则 TypeError）
失败 exchange 一等对象：ProviderError.exchange（error envelope + payload=None）
    ；治理拒绝 synthetic_failure_exchange（诚实记录，不冒充 SDK exchange）
RawWriter.write(exchange) 统一入口：
    exchange.request_id == envelope.request_id 断言
    provider/dataset envelope-first（外部冲突 BLOCK）
载荷形状支持：list[dict] / dict[str,list[dict]] / DataFrame(polars|pandas)
    / dict[str,DataFrame] / pyarrow.Table / 标量列表
dict-of-tables 方案 A：每逻辑表独立 Parquet + meta 列出全部
    (name,file,content_hash,schema_hash,row_count)；禁止静默取首值
Spike 证据链唯一正式路径：
    exchange → RawWriter → Parquet+meta → RawWriteResult(evidence_uri/hash)
    → SpikeCase.evidence_ref/evidence_hash（evidence_type=RAW_PARQUET）
RunStore.write_evidence(JSON) 保留为兼容 API，不再是正式 provider 证据链
逐字段 round-trip 测试（值/类型/nullable/中文/NaN-None 语义）
```

CR-1.2（Complete Exchange + Raw Meta/Request Closure，R4-A2.4 §2-§3）要求：

```text
隐藏日历前置显式（Option A）：
    calendar exchange 先持久化 → 窗口 trading_days 显式传入
    RealTarget.query_kline_exchange(trading_days=...)（无隐藏内部取数）
    日历失败 → 失败 meta 落盘 + kline 不发射（不伪造成功）
B3/B7 code_list/calendar 前置 = 持久化 exchange（参数落盘：
    code_list/trading_days）
RawWriteResult 拆分：payload_artifacts[]（uri/content_hash/schema_hash/
    row_count）+ meta_artifact；evidence 恒为 exchange .meta.json
    （双向闭合：payload 篡改/删除 → BLOCK；meta 删除 → BLOCK）
meta 持久化完整脱敏 request_params + params_hash（等长不同 symbols
    hash 不同）+ ingested_at + ingest_run_id
多文件提交 staging 原子化（全部 payload 先落 staging → os.replace 逐个
    → meta 最后）；表名净化冲突 BLOCK；read(verify=True) 读前复验
AST 静态测试：probes.py / golden_router.py 禁止调用 payload-only
    target 方法（get_code_list / get_calendar / query_kline 等业务面）
```

CR-1.2.1（Raw Commit Hardening，R4-A2.5 §7）要求：

```text
orphan payload（字节在盘、meta 锚缺失，中断提交残留）：
    same-request retry 且字节一致 -> 提交恢复（补落 meta，idempotent）
    retry 字节不同 -> orphan 移入 .quarantine/（可取证、永不冒充有效
    证据）且写入 BLOCK；partial orphan（多表落一半）同隔离
list_orphan_payloads(raw_root) 巡检接口（健康存储返回空）
_commit_files payload 落位对"已存在且字节一致"跳过（恢复语义）
fault-injection 测试：meta 写失败 -> 无锚无残留、retry 恢复；
    payload move 失败 -> 无 meta 锚（meta 最后落盘语义保持）
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
[ ] Domain-specific Golden Router（evidence bundle 同源验证）
[ ] Bound-aware Formal Gates（verdict 只用 run-bound dataset）
[ ] Trading Rule 数据层 REVIEWED（configs/trading_rules，ADR-011/012）
[ ] Trading Rule Run Binding（verdict 复验 bound file+hash+version）
[ ] Runtime Evidence 链（exchange → RawWriter → RAW_PARQUET，CR-1.1）
[ ] Raw Exchange Closure（meta-anchored 双向闭合 + request 可重建，CR-1.2）
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
Status: OPEN（结构已闭环：integrity gates + review workflow + evidence
        closure + bound gates；剩余人工执行：123 cases 人工 Review +
        补齐 distinct events（当前 ST_TRANSITION=10<50、DELIST symbols=10<20）
        + 外部工件封存）
Impact: False GO / False NO_GO
Mitigation: R4-A1.1/R4-A2.3 已落地（gates as code，fail-closed）；
           人工 review 完成前 P0-M-1B Entry Gate 永远 BLOCKED
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
Status: REOPENED（R4-A2.5/CR-1.2.1 复审维持 REOPENED：B5/B6 仍有绕过
        executor 的 exchange 路径 + CA 类型未入真实 truth + manifest
        无 confinement/一致性——即 R4-A2.6/CR-1.2.2 的四项 P0）
        → 本批 R4-A2.6/CR-1.2.2 修复后结构完整（executor 边界 AST 守卫
        + Spy 计数闭合 + typed truth + manifest confinement/coherence）；
        保持 REOPENED 直到 Reviewer 验证本批（不预写关闭）
Mitigation: PENDING_REVIEW（R4-A2.6/CR-1.2.2）
```

## RISK-005 Trading Rule 数据层未人工 Review

```text
Status: OPEN（结构完全闭环：immutable versions + ACTIVE manifest + run
        绑定（文件清单+联合 hash）+ review gate（path confinement + schema）
        + review 工具链；剩余人工执行：scripts/rules/review.py 对
        v20260824-compiled 产出 REVIEWED 版本并切换 ACTIVE）
Impact: 制度事实当前 ACTIVE=COMPILED；COMPILED 被代码层硬阻断
        （PRODUCTION new_run/verdict 拒绝）
Mitigation: P0-M-1B 前人工执行；fail-closed 语义 + st_state 严格解析
        已在代码层（RULE_UNRESOLVED 永不静默退化）
```

---

# 53. Technical Debt

```text
TD-001 历史 audit/work_report 较多
    不影响运行；不删除 Git 历史

TD-002 Spike/Canonical 尚未共享 ProviderExchange
    CR-1.1/CR-1.2 已闭环 Spike 侧；Canonical 侧在 CR-2 消费 raw evidence

TD-003 CI Governance full-history checkout 待完善
    R4-CI

TD-004 RawWriter 旧入口 write_success/write_failure 保留为兼容包装
    CR-2 接入后可移除（统一走 write(exchange)）

TD-005 golden v3 候选 distinct events 不足（ST 10<50 / DELIST symbols 10<20）
    人工 review 批次中以 candidate.py add-case 补齐

TD-006 FakeTarget dividend 事件数据与 golden CA cases 的日期对齐有限
    dry-run 中部分 CA case 诚实 FAIL（事件源缺失）；正式验证以真实
    provider dividend/right issue records 为准（P0-M-1B）

TD-007 CI ruff format 门在 b7a84563..c7aa511 期间缺本地等价检查
    本批起本地提交前必须跑 ruff format --check（连同 lint/mypy/pytest
    的 CI 等价四检查）
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
Developer 在工作要求文档内更新各问题的 implementation mapping
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

## Reviewer Auto-Archive 规则（R4-A2.3 §0 并入管理总册）

历史工作要求文档（`docs/design/*工作要求*` / `*审计*` / `*复审*`）不做手工归档移动；其生命周期由本总册与 DEVLOG 承载：

1. 每份工作要求处理完毕（本批全部 P0 关闭或明确转 P1/DEFERRED）后，Developer 必须在该文档内追加 **implementation mapping** 章节（问题编号 → 代码/测试/ADR 定位），随后该文档即视为**已关闭归档**；
2. 复核裁决（VERIFIED/REOPENED）直接记录于 DEVLOG 对应条目与本总册 §61 Change Log，不再为旧工作要求文档新开复审文件；
3. 若同一主题需要新一轮整改，Reviewer 下达**新的**工作要求文档（新文件名带日期与批次号），不修改已关闭文档正文；
4. 单一真相入口永远是本总册（当前状态）+ DEVLOG（时间线）+ ADR（长期决策），历史工作要求文档只作为输入证据保留。

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

## DM-CR-20260825-007 — R4-A2.5 Review Correction & Governance Sync

**Type**：C1（治理修正）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.5/CR-1.2.1 复审 §9——DEVLOG 自相矛盾（CONFIRMED GREEN vs "待 Actions 确认"）；"v3 无需重封"的 CA 声明与实际数据（v3 untyped）不符；Current Code Baseline 非 exact SHA；§30 保留过时 current-state；§40 提前写 upstream PASS。  
**Correction**：DEVLOG R4-A2.5 条目两处就地修正（保留历史，标注复审修正）；总册头部基线改为 exact SHA 引用（上批 implementation 13d02a1 + 复审 HEAD cdd3608；本批提交后以其 SHA 为新基线）；§30 重写为当前真相统一（2026-08-25）；§40 全部 upstream 行改为 "absorbed into R4-A2.6/CR-1.2.2——最终 VERIFIED 随本批门"（不预写 PASS）；RISK-004 保持 REOPENED 直到 Reviewer 验证本批；CI = VERIFIED GREEN（Reviewer 确认 run 35/36）。  
**Affected Modules**：Documentation / Governance（DEVLOG、总册 §30/§40/§61）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-006 — Rule Manifest Confinement & Metadata Coherence

**Type**：C2 amendment to ADR-013（manifest selector 契约收紧）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.6 P0-03/P0-04——ACTIVE manifest 的 dataset_files[] 无 confinement（../ 与绝对路径可逃出 rules root）；manifest 与 dataset 治理字段（review_status/source_version/review_provenance/dataset_version）真实不一致（source_version 实锤）且不比较；run 的 trading_rule_version 语义混淆（selector id vs yaml content version）。  
**Old Contract**：`load_rule_manifest` 仅检查 `(root/rel).is_file()`；`load_active_rules` 只校验 dataset_hash + dataset_version；SpikeRun.trading_rule_version = yaml content version。  
**New Contract**：`_confined_dataset_file`（相对/无 `..`/无绝对/symlink resolve 后仍须在 root 内 + 必须位于 `versions/<rule_version>/` 下）在任何 fs 访问前执行——ACTIVE（load_rule_manifest）与 bound（load_bound_rule_book）共用同一 helper；`load_active_rules` 强制 manifest↔dataset 四字段一致（review_provenance 语义等价比较：空值键豁免、datetime 规范化）；真实 rule_manifest.json 的 source_version 修正为与 yaml 一致；SpikeRun 绑定 `trading_rule_version`（selector）+ `trading_rule_dataset_version`（content）+ `trading_rule_source_version`，load_bound 双版本复验（旧 run json 兼容读取）；P1：`provenance_complete()` 纳入 rule binding；review.py manifest 原子切换（tmp+os.replace）+ `--from-version` 血缘检查 + 非 ACTIVE 输入拒绝 + 切换后 coherence 自验证。  
**Affected Modules**：spike/trading_rule.py、spike/model.py、spike/run_store.py、spike/runner.py、spike/probes.py、scripts/rules/review.py、configs/trading_rules/rule_manifest.json  
**Tests**：tests/integration/test_rule_manifest_closure.py（16：traversal/绝对/symlink/version-dir×2/一致性×5/双版本绑定/provenance×3/review 脚本×3）+ binding 适配  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-005 — Golden CA Event-Type Truth Closure

**Type**：C1/C2 implementation-semantic closure（不创建新 Golden 版本——event_class 已在语义 hash 内，无 v3 bytes 变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.6 P0-02——CA 事件类型校验只对 synthetic 测试生效（expected_fields.event_type）；真实 golden v3 的 20 个 CA cases 均 untyped（event_class=DIVIDEND_EX_DATE 被 validator 忽略），"untyped accepts any" 旁路在 formal path 保留。  
**Old Contract**：`expected_type = case.expected_fields.get("event_type")`——空则跳过类型校验（任意事件类型可过精确日期后进入后续验证）。  
**New Contract**：`_resolve_expected_event_type(case)`——event_class（语义 hash 成员）为 PRIMARY 类型事实源（DIVIDEND_EX_DATE→DIVIDEND / RIGHT_ISSUE_EX_DATE→RIGHT_ISSUE）；expected_fields.event_type 存在时必须与 event_class 派生一致（冲突→fail closed）；unknown/missing event_class→`EVENT_TYPE_UNRESOLVED` fail closed；类型比对为**强制**（validator v5）；删除并反转旧 "untyped accepts any" 测试；actual-truth regression：load 真实 golden_cases_v3.jsonl 全部 20 个 CA cases（每个解析为 DIVIDEND 并跑 typed validator 端到端；right-issue-only 证据对真实 DIVIDEND case 产生 EVENT_TYPE_MISMATCH）。  
**Affected Modules**：spike/golden_router.py、tests/integration/test_ca_event_type.py（重写）  
**Compatibility**：v3 bytes 与语义 hash 零变更（event_class 早已入 hash）；带 event_type 的合成 case 必须与 event_class 一致。  
**Tests**：test_ca_event_type.py（16：解析×6 + typed 验证×7 + 真实 v3×3）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-004 — Formal Probe Exchange Enforcement

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-1.2.2 P0-01（R4-A2.5/CR-1.2.1 复审 §2）——B5/B6 的 code-list 前置绕过 ProbeExecutor 直接调用 `ctx.target.get_code_list_exchange`：B5 失败路径的 failure exchange 不持久化（异常在手工 persist 前逃逸）；B6 连成功路径都不持久化。违反"formal path 每个 exchange 都是 immutable evidence"不变量。  
**Old Contract**：调用者自行取得 exchange、成功后手工 `evidence_from_exchange`（"记得持久化"的 correctness contract）。  
**New Contract**：B5/B6 code-list 前置改走 `executor.call(...)`（成功/失败都持久化 + 失败→结构化 case + ProviderError 不逃逸）；B6 依赖前置失败→stock_basic 不发射；**AST 双静态守卫**：probes.py 的 `ctx.target.*_exchange` 调用必须位于 lambda 内（executor 边界）、golden_router.py 的必须位于 `collector.persist(...)` 参数内（approved boundary 显式化——不靠开发者记忆，也不误伤 `_DomainCollector` 这类调用即持久化的专用边界）；**Spy 计数闭合测试**：B2-B7 每个 probe 的真实 exchange 调用数 == 持久化 raw meta 数（含 B4 golden 路由）。  
**Affected Modules**：spike/probes.py（B5/B6）  
**Tests**：tests/integration/test_probe_exchange_enforcement.py（12：B5/B6 成功恰好一个 meta ×2 + B5/B6 失败持久化+结构化 ×2 + B6 依赖不发射 + Spy 计数 ×6 + AST 守卫 ×2）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-003 — CA Event Taxonomy + B5/B6 Payload Shapes + CI 根因修复

**Type**：C1（CA 证据组合扩展）+ C2（CI 门新增 format check 执行修正）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.4/CR-1.2 复审 P0-04/P0-05（CA 事件类型不可替代；B5/B6 标量载荷静默垃圾）+ §10 治理（CI 全红根因：ruff format --check 门自 b7a84563 起未过，开发者本地只跑 ruff check）。  
**Old Contract**：CA 事件源仅 dividend 流（任何事件记录可证明任何类型期望）；B5/B6 的 code_list 消费把 row dict 强转为字符串（`"{'value': '600519.SH'}"` 垃圾但静默"通过"）；`_rows_of` 对 polars frame 走 `list(to_dict())` 返回列名列表（静默垃圾行）。  
**New Contract**（ADR-013 §4-§5）：事件分类学 DIVIDEND/RIGHT_ISSUE 两独立流（provider `get_right_issue_exchange`；CA 域 fetch 六 exchange 全入 bundle）；golden case 以 `expected_fields["event_type"]` 声明期望类型（语义 hash 兼容载体）；校验 (symbol, EX_DATE, type) 精确三元组，DIVIDEND 永不替代 RIGHT_ISSUE（`EVENT_TYPE_MISMATCH`）；provider 字面量归一化（分红/配股等）；`event_type` 为验证器元键（status 字段比对前剥离）；`_flat_values` 标量列表展开 + 多列 fail loud；`_rows_of` polars 优先 `.rows()`。CI：本地等价四检查（ruff check + format --check + mypy + pytest）入提交前流程；8 个红提交的根因记录于头部 CI Status。  
**Affected Modules**：providers/amazingdata/provider.py、spike/{target,golden_router,probes}.py、scripts/rules/review.py、configs/trading_rules/**（版本模型迁移：v20260824-compiled + manifest）  
**Tests**：test_ca_event_type.py（8）、test_b5_b6_payload_shapes.py（9）、test_raw_commit_recovery.py（8）、test_rule_binding_adversarial.py（4）+ 适配  
**ADR**：[ADR-013](../adr/ADR-013_rule_version_model.md) §4-§6  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-002 — Trading Rule Version Model + Review Gate Hardening

**Type**：C2 amendment to ADR-012 §2  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.5 P0-02/P0-03（规则数据集缺版本模型：目录 glob 合并在 COMPILED/REVIEWED 共存时歧义；绑定只记录第一个文件；gate 的 ref 无 confinement/hash/timestamp schema）。  
**Old Contract**：`TradingRuleBook.load(dir)` glob 合并目录全部 yaml；SpikeRun 绑定单 file+hash；gate 的 artifact ref 任意相对路径（可指向 evidence 外）、hash 无 schema、时间戳无校验；review.py原地改写。  
**New Contract**（ADR-013 §1-§2）：`rule_manifest.json`（ACTIVE 选择器）+ `versions/<v>/rules.yaml`（不可变共存）+ `evidence/`；`load_active_rules` 复算 dataset_hash（ACTIVE 篡改→new_run 阻断）；SpikeRun 绑定 `trading_rule_dataset_files[] + dataset_hash`（联合 hash 算法=manifest；篡改任一文件阻断 replay；旧 run json 兼容读取）；`load_bound_rule_book` 逐文件 confinement+hash+version 校验；目录 glob 合并语义废除；gate：ref 相对 evidence root + path confinement（绝对/`..` 拒绝于 fs 访问前）+ hash 64 lower-hex + reviewed_at/source_retrieved_at ISO-8601 + artifact bytes 复验；review.py 重写（新 immutable 版本 + ACTIVE 切换 + evidence 内容寻址 + 副本自验证 + 重复 review 拒绝）。  
**Affected Modules**：spike/trading_rule.py、spike/{model,run_store,runner,probes}.py、scripts/rules/review.py、configs/trading_rules/**（迁移至版本布局）  
**Compatibility**：旧 SpikeRun json 的 trading_rule_file/hash 映射为单文件 dataset_files（兼容读取）；单文件 `TradingRuleBook.load(file)` 保留。  
**Tests**：test_trading_rule_binding.py 重写（24：版本共存/ACTIVE 推进/篡改阻断×4/绑定持久化/gate 加固×5/review 脚本端到端/st_state×4/book 必填×2）+ test_trading_rule_data.py 适配  
**ADR**：[ADR-013](../adr/ADR-013_rule_version_model.md) §1-§2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-001 — Formal Rule-SoR Closure（全消费者 run-bound book）

**Type**：C1（验证器契约强化）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.5 P0-01（validate_limit_rule 仍可用 module fallback：trial/prod 的 B3/B5 消费工作树当前规则，违反 Exact Replay）。  
**Old Contract**：`validate_limit_rule(rows, book=None)`——book 可选，None 时 resolve 链 fallback `default_rule_book()`（工作树当前状态）。  
**New Contract**（ADR-013 §3）：`book` 为**必填 keyword**（无默认值；显式 None→结构化 VALIDATED_FAIL，消息含 "book=None refused"）；B3/B5（probes）传 `ctx.rule_book`；`route_all` 把 run-bound book 传入 limit/BJ 验证器；AST 守卫测试：probes/golden_router 的 validate_limit_rule 调用必带 book= 且非 None 字面量、resolve_* 必带 book=；对抗测试：ACTIVE v1(10%)→v2(20%) 推进后同 run 重放 B5 limit cases 恒等（bound 仍 10%）；bound 文件篡改→`ctx.rule_book` 访问即阻断。  
**Affected Modules**：spike/validators.py、spike/probes.py、spike/golden_router.py、tests/unit/test_spike_validators_v2.py（显式 book）  
**Compatibility**：无（validate_limit_rule 签名收紧为破坏性变更——调用方全部同批更新；测试显式加载 ACTIVE book）。  
**Tests**：test_rule_binding_adversarial.py（4）+ TestLimitRule 适配 + 502 全量回归  
**ADR**：[ADR-013](../adr/ADR-013_rule_version_model.md) §3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-011 — R4-A2.3/CR-1.1 Review Correction & Governance Sync

**Type**：C1（治理修正）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.3/CR-1.1 复审 §10——上批 DEVLOG/管理总册宣称与 runtime 有出入（BJ mapping endpoint 表述 / CI 状态 / Last Review 时间基线）。  
**Correction**：本批 DEVLOG 与总册如实记录：BJ 证明为 hist master + exact-date regime（无 mapping endpoint 依赖）；CI 以推送后 Actions 实际结果为准（本地与 CI 区分口径 §49 不变）；Last Review 指向最新复审文档。上批 R4-A2.3/CR-1.1 条目状态由 PENDING_REVIEW 归档为 absorbed（由 R4-A2.4/CR-1.2 批次闭环）。  
**Affected Modules**：Documentation / Governance（DEVLOG、总册 §40/§41/§61）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-010 — Corporate Action Event SoR Closure

**Type**：C1（实现 closure；Frozen Baseline CA SoR 语义未变——corporate_action 数据集本含事件记录）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.4 P0-05——CA 证据组合缺少事件事实源，adj 流单独不是充分 SoR。  
**Old Contract**：CA 域 fetch = calendar + status + adj + kline；adj-only 也能 PASS。  
**New Contract**：CA 域 fetch = calendar + status + **dividend（事件事实源）** + adj + kline（五 exchange 全入 bundle）；`_validate_corp_action_context`：无事件记录→`VALIDATED_FAIL(EVENT_SOURCE_MISSING)`（"adj-factor movement alone is not a sufficient event SoR"）；事件存在但 EX_DATE≠T→`EVENT_DATE_MISMATCH`；event+adj+kline 一致→PASS；事件日停牌→`NOT_TESTABLE_TIME(SUSPENSION_AT_EVENT)`；FakeTarget `get_dividend_exchange`（事件端点进 dry-run 覆盖）。  
**Affected Modules**：spike/golden_router.py、spike/target.py（FakeTarget + SpikeTarget Protocol）  
**Tests**：tests/integration/test_ca_event_sor.py（6 个：一致 PASS+bundle lineage / adj-only FAIL / 日期错配 FAIL / 停牌 NOT_TESTABLE / bundle 闭合）  
**ADR**：ADR-012 §3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-009 — Trading Rule Run Binding + Formal Review Gate

**Type**：C2 amendment to ADR-011  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.4 P0-03/P0-04——规则数据集缺 run 绑定与审阅闭环；compute_config_hash 平铺 glob 看不见嵌套规则文件。  
**Old Contract**：SpikeRun 无规则绑定；validators 用工作树当前规则（working-tree advance 泄漏进历史 run）；COMPILED 规则可进 PRODUCTION；`compute_config_hash` 只扫 `configs/*.yaml`；st_state truthiness 解析。  
**New Contract**：SpikeRun 绑定 `trading_rule_file/version/hash/review_status`（TRIAL/PRODUCTION 创建时）；`compute_config_hash` 递归 `configs/**`（相对路径规范化）；RUNNING/RESUME/VERDICT/REPLAY 只用 `load_bound_rule_book`（bytes hash + version 复验，mismatch→`RuleUnresolvedError`）；`ProbeContext.rule_book`（run-bound）传入 limit/BJ 验证器；Review Gate（COMPILED→REVIEWED：provenance 六字段完整 + artifact kind allowlist + artifact bytes hash 复验）在 `new_run(PRODUCTION)`（fail-fast）与 `compute_verdict(PRODUCTION)`（复核）执行；`scripts/rules/review.py`（工具自算 SHA-256 写入 REVIEWED 副本 + 副本自验证 + 重复 review 拒绝）；`_parse_st_state` 严格解析（truthiness 禁止，"false" 字符串不再反转为 True）。  
**Affected Modules**：spike/model.py、spike/run_store.py、spike/runner.py、spike/probes.py、spike/trading_rule.py、scripts/rules/review.py（新）  
**Compatibility**：SpikeRun 新字段默认空（旧 run json 兼容读取）；REVIEWED 副本与 COMPILED 原件并存（单文件约定由运维落位）。  
**Tests**：tests/integration/test_trading_rule_binding.py（14 个：config 递归 / 绑定持久化 / working-tree 篡改阻断 / version mismatch / COMPILED 阻断 PRODUCTION / REVIEWED 通过 / artifact 篡改阻断 / provenance 缺失阻断 / kind 非法 / review 脚本端到端 / st_state 严格解析×4）  
**ADR**：[ADR-012](../adr/ADR-012_raw_exchange_closure.md) §2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-008 — CR-1.2 Complete Exchange + Raw Meta/Request Closure

**Type**：C2 amendment to ADR-010  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.3/CR-1.1 复审 REOPENED（CR-1.1 四 P0：日历前置隐藏 / RawWriteResult 语义不完整 / request 不可重建 / evidence 锚定不闭合）。  
**Old Contract**：query_kline 内部隐藏 get_calendar；单表 evidence 绑裸 parquet（meta 删除不破坏闭合）；meta 只有 request_params_hash（请求不可重建）；多表提交无 staging 原子性；表名冲突静默覆盖；read 无验证。  
**New Contract**：见 §43 CR-1.2 要求块（隐藏日历前置显式化 Option A / payload+meta 双向闭合 / 完整 params + ingested_at + ingest_run_id / staging 原子提交 meta 最后 / 表名冲突 BLOCK / read(verify=True) / AST 禁止 payload-only 调用面）。  
**Affected Modules**：storage/raw_writer.py（verify_meta_closure + staging + ArtifactRef）、spike/runner.py（递归双向闭合）、spike/probes.py（evidence meta 带 payload_artifacts + ingest run 注入）、spike/golden_router.py（bundle entry 带 payload/meta 引用）、spike/target.py（FakeTarget 真实 params + trading_days；RealTarget.query_kline_exchange(trading_days)）  
**Compatibility**：证据锚定变更为 meta.json——旧 run 的 parquet 证据按 legacy 路径闭合（meta 必须在）；RawWriteResult 字段只增不减。  
**Tests**：tests/unit/test_raw_closure.py（13 个：tamper/deletion 双向 / 多表 tamper / combined hash / 完整 params + 等长异 symbols / 脱敏 / ingest 绑定 / staging 无残留 / 冲突零落盘 / 失败无 meta 锚 / read verify×2）+ tests/integration/test_cr12_exchange_completeness.py（7 个：两 exchange 恰好 / 日历失败 kline 不发射 / B3/B7 前置 / AST×2 / rule_book 绑定）  
**ADR**：[ADR-012](../adr/ADR-012_raw_exchange_closure.md) §1  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-007 — Reviewer Auto-Archive 规则并入管理总册

**Type**：C1（治理流程）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.3 工作要求 §0（Reviewer 闭环规则）要求并入管理总册。  
**Old Contract**：工作要求文档生命周期未定义；历史复审文档逐份独立成文。  
**New Contract**：§56 新增"Reviewer Auto-Archive 规则"——工作要求处理完毕后 Developer 在文档内追加 implementation mapping 即视为关闭归档；复核裁决记录于 DEVLOG 与 §61；新整改下达新工作要求文档，不修改已关闭正文。  
**Affected Modules**：Documentation / Governance（§56）  
**Tests**：DM CI guard（管理总册结构守卫）继续覆盖  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-006 — Raw Evidence Model（CR-1.1 Explicit Exchange Runtime）

**Type**：C2（正式 evidence model 变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.2 复审裁决 REOPENED——CR-1 的 ProviderExchange/RawWriter 存在 4 项 P0（运行时链不完整 / RawWriter 未接入 / 序列化风险 / router 证据不同源）。  
**Old Contract**：探针消费 payload 便捷方法；失败 envelope 依赖 `provider.last_envelopes` 反查（共享状态）；正式 provider 证据链 = `payload → RunStore.write_evidence(JSON)`；B4 路由 `lambda: None` 伪调用 + 单条 domain envelope；dict payload 静默取第一个 value。  
**New Contract**（ADR-010）：
- 运行时证据链唯一正式路径：`target.*_exchange() → RawWriter.write(exchange) → Parquet + .meta.json → RawWriteResult → SpikeCase.evidence_ref/evidence_hash`（evidence_type=RAW_PARQUET）；
- 失败 exchange 一等对象：`ProviderError.exchange`（`call_exchange` 附加）；治理拒绝 `synthetic_failure_exchange`；`last_envelopes` 降级 diagnostic-only（AST 静态测试强制 probes/golden_router/runner 不得访问）；
- `ProbeExecutor.call(fn)` 的 fn 必须返回 ProviderExchange（TypeError fail loud）；
- 载荷形状全支持 + dict-of-tables 方案 A（每逻辑表独立 Parquet；meta 记录全部 hash/schema/rows）；混合/未知形状抛 RawWriterError；逐字段 round-trip 测试（含中文/NaN/None/nullable）；
- Golden Router 证据同源：每 domain 全部 exchange 先持久化、DomainData 来自精确 payload、case 绑定 **evidence bundle**（`raw/bundles/*.json` 列出全部 request_id/ref/hash）；`verify_evidence_closure` 对 bundle 递归复验；domain fetch 失败按错误类结构化全部 case；
- RawWriter `write(exchange)`：request_id 一致性断言 + envelope-first provider/dataset（外部冲突 BLOCK）；旧入口保留为兼容包装。  
**Affected Modules**：providers/exchange.py、providers/errors.py、providers/amazingdata/provider.py、storage/raw_writer.py、spike/target.py、spike/probes.py、spike/golden_router.py、spike/runner.py  
**Compatibility**：`RunStore.write_evidence`（JSON）保留（测试/旧数据兼容），不再是正式证据链；SpikeCase.evidence_type RAW_JSON→RAW_PARQUET；旧 raw 目录布局不变（同 request_id 同字节幂等）。  
**Tests**：418 passing（新增 test_cr11_explicit_exchange 10 + test_raw_writer_shapes 22 + test_golden_router_evidence 13；CR-1/spike/golden gates 既有测试适配）  
**ADR**：[ADR-010](../adr/ADR-010_raw_evidence_model.md)  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260824-005 — R4-A2.3 Correctness Closure（bound gates / rule data / exact-date / CA context）

**Type**：C2（Trading Rules 契约变更）+ C1（gates 语义强化）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.2 复审裁决 REOPENED——5 项 P0（run-bound ACTIVE 泄漏 / 制度事实硬编码 / 首 N 日日历天近似 / limit 未精确按日匹配 / CA T-1/T/T+1 只是注释）+ P1（BJ 独立语义证明）。  
**Old Contract**：`production_formal_gate(bound_manifest)` 内部仍调 `review_gate()`（读 ACTIVE）；`verify_binding` 用 ACTIVE 对比（违反 bound-run 契约）；`trading_rule.py`/`validators.py` 硬编码 ±10/20/30% 等制度费率；首 N 日无判定（CHINEXT first-5 规则直接 None）；`_validate_limit_pit` 取首个 symbol 匹配行（非精确日期）；`_validate_corp_action_context` 只做字段比较（无 T-1/T/T+1 价格上下文）；`_validate_bj_mapping` 依赖不存在的 mapping endpoint。  
**New Contract**：
- **Bound-aware gates**：`quantity_gate/event_coverage_gate/review_gate/production_formal_gate` 全部接受 `(cases, manifest)`；VERDICT 只用 run-bound 数据集；`verify_binding`（ACTIVE 对比语义）删除；ACTIVE advance/tamper 双向对抗测试证明不泄漏；
- **Trading Rule 数据层**（ADR-011）：制度事实迁入 `configs/trading_rules/a_share_limit_v1.yaml`（version/review_status + rules[]）；Python 只 load/validate/PIT 匹配/冲突检测/resolve/Decimal 计算；fail-closed（0 匹配 / >1 equally-valid / 缺 listing_date+calendar / 未知板别 → `RuleUnresolvedError`，永不静默退化 MAIN 10%）；Python 源码出现费率字面量即测试失败；
- **首 N 日 = session 序号**：`first_n_sessions` 用 PIT 交易日历 index（上市日=第 1 个 session）；日历缺行 fail-closed；测试覆盖春节/国庆/跨周末/第 5-6 日；
- **Limit 精确匹配**：`(SECURITY_CODE, TRADE_DATE)` 精确匹配（0 行/多行 fail closed）；listing_date 必须来自同一 PIT hist master（缺失即 FAIL，不允许 None 退化）；限价 Decimal ROUND_HALF_UP 与 provider 高低限价一致性校验；
- **CA T-1/T/T+1 真验证**：exact event date（adj EX_DATE==T）/ factor transition at T / raw discontinuity（factor≠1 时 raw_ret≠adj_ret）/ adjusted continuity（|adj_ret|≤35%）/ 停牌→`NOT_TESTABLE_TIME(SUSPENSION_AT_EVENT)`（绝不静默 PASS）；
- **BJ 语义证明**：hist master 存在性（code continuity）+ exact-date status ±30% regime（数据驱动 rule），不再依赖 mapping endpoint。  
**Affected Modules**：spike/golden_store.py、spike/golden_router.py、spike/trading_rule.py、spike/validators.py、spike/runner.py、configs/trading_rules/（新）  
**Affected Data**：configs/trading_rules/a_share_limit_v1.yaml（COMPILED，待人工 review）  
**Compatibility**：`resolve_trading_rule` 返回值从 `TradingRule | None` 改为 raise `RuleUnresolvedError`（fail-closed）；`validate_limit_rule` 升级 v3（数据驱动）；`BOARD_LIMIT_RATES/board_of/expected_limit_price` 删除（无外部引用）。  
**Tests**：418 passing（新增 test_trading_rule_data 21 + test_bound_formal_gates 8 + router/CA/BJ 场景 13）  
**ADR**：[ADR-011](../adr/ADR-011_trading_rule_data_sor.md)  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260822-004 — CR-1 ProviderExchange / RawWriter Runtime Contract

**Type**：C1（新增运行时契约）  
**Status**：DONE（Implementation）/ PENDING_REVIEW  
**Trigger**：R4-A2 Batch-1 复核裁决 CR-1 READY / SHOULD START NOW。  
**Old Contract**：provider `get_xxx` 直接返回 payload；envelope 藏在 `last_envelopes`（thread-local 式）；无 Raw 层持久化；query_kline 内部 get_calendar 无独立审计。  
**New Contract**：
- `ProviderExchange`（1 SDK exchange = 1 request_id = 1 RawEnvelope = ≤1 payload）；`call_exchange()` 显式返回 exchange；业务 wrapper 取 `.payload`；**无 last_exchange/consume 模式**
- hidden SDK call（`query_kline → get_calendar`）独立 exchange（calendar 不埋进 kline envelope）
- `RawWriter`：成功 exchange → Parquet 工件 + .meta.json（envelope）；失败 exchange → envelope-only 失败证据（请求审计永不丢失）；same hash 幂等 / different bytes BLOCK；跨平台逻辑 URI；secret 脱敏；**无 repr() 序列化**
- Spike `ProbeContext.evidence` 复用 exchange 的 request_id（不再重新生成）  
**Affected Modules**：providers/exchange.py（新）、providers/amazingdata/provider.py、storage/raw_writer.py（新）、spike/probes.py  
**Tests**：348 passing（新增 test_cr1_provider_exchange：request_id 保持 / 失败 envelope / 幂等 / 冲突 BLOCK / secret 脱敏 / 跨平台 URI / 无 repr / hidden calendar 独立 exchange / spike request_id lineage）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260822-003 — R4-A2 Golden Review / Domain Router / PIT Validator Contract（第一批）

**Part 2（本批）**：R4-A2 Batch-1 复核四项 P0 全部修复——
- **P0-01** review_gate 全 case 校验（删除 early break；完整错误收集；first-valid-second-tampered 测试）
- **P0-02** Run-bound Golden resolver：`load_bound(dataset_file, truth_version, dataset_hash)` 直读 immutable dataset；resume/verdict/B4 全部走 bound（ACTIVE 仅决定 NEW run 默认版本）；ACTIVE 推进后历史 run 仍可 Exact Replay（测试）
- **P0-03** Candidate Augmentation Workflow（`scripts/golden/candidate.py`：add-case/validate/build-version）；review 只核验不创建事件；生命周期文档更新
- **P0-04** PRODUCTION new_run 执行完整 formal gate（quantity + events + review）fail-fast（不再烧完正式账号流量才在 verdict 发现 golden 未 review）
- P1-01 batch kind 统一 allowlist；P1-02 REVIEWED provenance load 时完整校验；P1-03 artifact ref path confinement；P1-04 版本文件 create-only（不同 bytes BLOCK）；P1-05 batch stage-all-then-commit（无孤儿 evidence）；P1-06 evidence 真正 content-addressed（sha256/ 路径，方案 A）
- **R4-A2.2**：Domain Router（golden_router.py：ST→status / Delisted→hist_code_list+stock_basic / Limit→status+PIT rule / CA→status+adj+kline / BJ→mapping）；B3 现场 ST truth 删除（B3 结构性、B4 语义性彻底分离）；PIT TradingRule（版本化 effective_from/to + Decimal ROUND_HALF_UP）；History 固定 fixtures（600519/000001/835185/300104，不再 get_code_list()[:2]）；BSE 独立 core evidence
- 事件 identity 结构化：ST=(symbol, effective_date, subtype)、DELIST=(symbol, effective_date)——自由字符串 event_id 无法凑数（60 fake-id 合并为 1 的测试）
**Status 更新**：Implementation DONE（R4-A2.1 + R4-A2.2 全部落地）/ Review PENDING_REVIEW  
**Tests**：348 passing（本批 +13：bound resolver 4 + candidate workflow 4 + router/trading_rule 相关 + CR-1 13 项）

**Type**：C1 Contract Clarification  
**Status**：IN_PROGRESS（第一批已落地：Evidence Closure + Review Workflow + 事件语义 + hash 更名；Router/PIT/BSE/BJ 进行中）  
**Trigger**：R4-A1.1 复核 REOPENED Formal Truth Closure——source_artifact_hash 未真正绑定 Source Artifact。  
**Old Contract**：REVIEWED 只检查 source_artifact_hash 非空（可手工填任意值）；event gate 只有 ST_CAP 单类；SpikeRun 字段名 golden_manifest_hash 存的是 dataset_hash。  
**New Contract**：
- **Review Workflow 是唯一 COMPILED→REVIEWED 路径**（`scripts/golden/review.py`）：reviewer 提供外部证据工件文件，workflow 自己读取 bytes 计算 SHA256 并复制入 evidence store（内容寻址）；**无 --hash 参数**（手工 hash 永远无法输入）
- **Formal Review Gate**（review_gate）：每个 REVIEWED case 的 source_artifact_ref 必须 resolve 到 evidence 工件且 SHA256 与封存值一致，否则 REVIEW_INCOMPLETE
- **Provenance 分离**：compiled_by/compiled_at 与 reviewed_by/reviewed_at 独立；COMPILED case 带 reviewer 字段即 load 失败
- **事件语义**（§9/§10）：ST_TRANSITION + subtype（ST_ADD/ST_REMOVE/STAR_ST_ADD/STAR_ST_REMOVE），gate 要求 ≥50 distinct 且 ADD>0 且 REMOVE>0；DELIST 要求 distinct event ≥20 **AND** distinct symbol ≥20
- **字段更名**（§11 方案 A）：SpikeRun.golden_manifest_hash → golden_dataset_hash（load 兼容旧 key）
- 数据集 v3 candidate（compiled/reviewed 分离 + ST_TRANSITION 语义；诚实覆盖：ST_TRANSITION=2<50 无 REMOVE subtype、DELIST=10<20）  
**Reason**：让"封存的 hash"从 Claim 变成可机器复验的 External Evidence。  
**Affected Modules**：spike/golden_store、spike/validators、spike/model、spike/run_store、spike/runner、providers/amazingdata/capability、scripts/golden  
**Affected Data**：data/golden/provider/amazingdata/（v3 ACTIVE；evidence/ 由 review workflow 产生）  
**Compatibility**：GoldenCase 字段扩展；golden_dataset_hash 更名（legacy json key 兼容读取）。  
**Migration / Backfill**：golden_cases_v3.jsonl。  
**Tests**：313 passing（新增 test_golden_review_workflow：artifact 字节封存/无 hash 参数/重复 review 拒绝/缺失 artifact 拒绝/封存后篡改检测/ghost ref 检测/ST_REMOVE subtype gate/symbol 双门/更名兼容）。  
**ADR**：Not Required（契约澄清）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260822-002 — Adopt R4-A1.1 Golden Truth Integrity Contract

**Type**：C1 Contract Clarification  
**Status**：REOPENED（Formal Source Evidence 未闭环；source_artifact_hash 尚未绑定真实工件——R4-A2 第一任务）  
**Trigger**：R4-A1 复核 REOPENED，四项 P0（manifest 自验证 / hash 拆分 / event 覆盖 / 版本选择）。  
**Old Contract**：source_hash 单哈希；manifest 统计可被单点篡改；loader 按字典序猜版本。  
**New Contract**：manifest 统计从 cases 复算（篡改即拦截）；case_semantic_hash（含 case_type）与 source_artifact_hash 分离；event_id/event_class + distinct-event gate（PRODUCTION run 创建即拒绝，fail-closed）；append-only v1/v2 + ACTIVE 指针。  
**Reason**：Golden 从 "Versioned Claim Set" 推进到 "Versioned + Reviewed + Externally-Evidenced Truth Set" 的结构前提。  
**Affected Modules**：spike/golden_store、spike/runner、spike/validators、scripts/golden  
**Affected Data**：data/golden/provider/amazingdata/（v2 candidate，123 cases，全部 COMPILED）  
**Compatibility**：GoldenCase 字段扩展（source_hash→case_semantic_hash + 新字段）；load API 不变。  
**Migration / Backfill**：golden_cases_v2.jsonl 由 compile_v2 生成。  
**Tests**：302 passing（含 §22 关键测试：manifest 双类篡改 / entry 改+重封 / case_type 改 / REVIEWED 无 artifact / 负样本不算事件 / 诱饵 loader / append-only）。  
**ADR**：Not Required（契约澄清，不改架构）  
**Implementation Commit**：`b3a3d27`  
**Reviewer**：Design/Audit Review（2026-08-22：Structure SUBSTANTIALLY PASS；Formal Truth Closure REOPENED）

## DM-CR-20260822-001 — 建立 Development Management 总册

**Type**：C1 / Governance  
**Status**：VERIFIED（2026-08-22 R4-A1.1 复核：Development Management Governance PASS_WITH_MINOR_FIXES，§2 四小项已在本批修正）  
**Trigger**：项目进入多轮审计、Formal Spike 与 Canonical Runtime 并行阶段，需要统一长期管理入口。  
**Old Contract**：设计、进度、审计、风险、日志分散在多个文档。  
**New Contract**：建立 `docs/project/DEVELOPMENT_MANAGEMENT.md`，统一维护当前设计摘要、状态、Gate、Roadmap、变更控制和文档索引。  
**Reason**：降低语义漂移，避免“代码改变而当前方案不同步”。  
**Affected Modules**：Documentation / Governance  
**Affected Data**：None  
**Compatibility**：不改变运行时代码。  
**Migration / Backfill**：None  
**Tests**：management-doc governance test（DM CI guard，本批落地）。  
**ADR**：Not Required  
**Commit**：`f102394`（初始化）+ `8d7d4aa`（SHA 回填）+ 本批（§2 修正）  
**Reviewer**：Design/Audit Review（VERIFIED 2026-08-22）

---

# 62. 下一次维护检查点

R4-A2.6 + CR-1.2.2 已更新（2026-08-25，见 DM-CR-20260825-004/005/006/007）：

```text
§30 §40 §41 §52 §61 §62 + 头部（基线 exact SHA / CI VERIFIED GREEN）(done 2026-08-25)
```

下一批（R4-A3 / CR-2，须待本批 VERIFIED）落地时至少更新：

```text
§17                 (CR-2 Provider-Normalized 契约)
§40 §42 §44         (roadmap / acceptance)
§48                 (如新增 entry gate 条目)
§52 §53 §61         (风险 / TD / Change Log)
```

Golden / Trading Rule 人工 Review 执行时至少更新：

```text
§40 §48 §52 §61     (RISK-001/005 状态 + REVIEWED 版本落位)
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
