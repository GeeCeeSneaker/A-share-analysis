# A-share-analysis 开发管理总册（Development Management）

> **仓库固定路径（MUST NOT RENAME）**：`docs/project/DEVELOPMENT_MANAGEMENT.md`  
> **文档性质**：长期持续维护的项目级“当前设计 + 当前状态 + 开发计划 + 变更控制”总册  
> **项目**：A股市场态势数据基座（日频模块）  
> **Frozen Baseline**：V1.3.2  
> **Reviewed Repository HEAD**：`ab0cde7db4673224518540e1974c4e918bdbbf33`（R4-A2.11/CR-1.2.7 复审基线，run 53 全三腿 success；**VERIFIED**）  
> **Primary Implementation（R4-A2.11）**：`38da90e5b5f3d698cc909cf7c258c163081bb9af`  
> **CI/Lint Fix（R4-A2.11）**：`6eac92dceaf57014f07d93bd5e6eabcea1dcbc79`  
> **Current Code Baseline**：本批 implementation commit（R4-A3 SDK / Lifecycle / Early-Stop Closure；SHA 于提交后由同批 docs commit 记录）  
> **Document Revision**：DM-CR-20260826-030 / 031 / 032 / 033  
> **Last Review**：2026-08-26 23:57 +08:00（R4-A2.11/CR-1.2.7 复审：**VERIFIED——R4-A2.x / CR-1.x 审计链 CLOSED**；R4-A3 为下一活跃批次）  
> **Last Reviewer**：Design / Audit Review  
> **CI Status**：**FULL MATRIX GREEN**——run 52/53（`6eac92d` / `ab0cde7`）三腿 success（Reviewer job-level 正向确认）；本批提交后以 Actions 实际结果为准  
> **Phase Status（Reviewer 裁决同步，2026-08-26）**：  
> R4-A2.10 / CR-1.2.6 → DONE / VERIFIED (absorbed)；R4-A2.11 / CR-1.2.7 → DONE / VERIFIED；R4-A2.x / CR-1.x → **CLOSED / VERIFIED**；RISK-004 → **CLOSED for its current review-lineage definition**；R4-A3 → READY / ACTIVE NEXT；R4-B1 → READY_AFTER_R4-A3；R4-B2 → READY_AFTER_R4-B1；CR-2 → UNBLOCKED, sequenced after R4-B2；Production P0-M-1B → BLOCKED（人工 Review + 正式账号条件未满足）  
> **SHA Correction（Reviewer，2026-08-26）**：上批记录的 `38da90e583a83dd0e83991987df7f29ddbc7189c6` / `6eac92dc1bfb7a3aa70619dc34695930e88a51af` 有误，以 GitHub commit object 为准：`38da90e5b5f3d698cc909cf7c258c163081bb9af` / `6eac92dceaf57014f07d93bd5e6eabcea1dcbc79`（本头部即为修正记录；历史条目原文保留）  
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
| R4-A2.3 Correctness Closure | DONE | absorbed into R4-A2.7 | 结构保留；最终 VERIFIED 随 R4-A2.7 门（不预写 PASS） |
| CR-1 ProviderExchange + RawWriter | DONE | absorbed into CR-1.2.3 | 结构保留；最终 VERIFIED 随本批门 |
| CR-1.1 Explicit Exchange Runtime | DONE | absorbed into CR-1.2.3 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.4 Correctness Deepening | DONE | absorbed into R4-A2.7 | 结构保留；最终 VERIFIED 随本批门 |
| CR-1.2 Complete Exchange + Raw Closure | DONE | absorbed into CR-1.2.3 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.5 Rule-SoR Closure + CR-1.2.1 Raw Hardening | DONE | absorbed into R4-A2.7 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.6 Formal Truth/Manifest Closure + CR-1.2.2 Probe Exchange Enforcement | DONE | absorbed into R4-A2.8 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.7 Final Integrity + CR-1.2.3 Evidence Identity Closure | DONE | absorbed into R4-A2.9 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.8 Final Exchange-Boundary + CR-1.2.4 Pre-Access Integrity | DONE | absorbed into R4-A2.10 | 结构保留；最终 VERIFIED 随本批门 |
| R4-A2.9 Review-Seal Exactness + CR-1.2.5 Output Confinement | DONE | VERIFIED (absorbed) | PASS |
| R4-A2.10 Review Publish Byte-Identity + CR-1.2.6 Review Publish Integrity | DONE | VERIFIED (absorbed) | PASS |
| R4-A2.11 Final Single-Writer Lineage Closure + CR-1.2.7 Review Parent-Identity Serialization | DONE | **VERIFIED** | **R4-A2.x / CR-1.x 审计链 CLOSED（2026-08-26）** |
| R4-A3 SDK / Lifecycle / Early-Stop Closure | DONE | PENDING_REVIEW | 最高优先（已完成，待复核；VERIFIED 后进入 R4-B1） |
| R4-B1 Capability Endpoint Proof | PLANNED | READY_AFTER_R4-A3 | — |
| R4-B2 Publish Validation Exactness | PLANNED | READY_AFTER_R4-B1 | — |
| CR-2 Provider-Normalized + Quarantine | PLANNED | UNBLOCKED / after R4-B2 | — |
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

## R4-A3 SDK / Lifecycle / Early-Stop Closure（本批，DONE / PENDING_REVIEW）

```text
A3-01 SDK Lifecycle State Machine（DM-CR-20260826-030，ADR-019 §2.1/2.2）：
  ashare_state.providers.lifecycle.SdkLifecycle：
    INIT -> SDK_UNAVAILABLE | LOAD_FAILED | LOGIN_FAILED | AUTH_REJECTED
          | SESSION_READY
    SESSION_READY/UNSUBSCRIBED -> SUBSCRIBE_STARTED -> CALLBACK_ACTIVE
          -> UNSUBSCRIBED（可重订阅）
    任意状态 -> LOGGED_OUT（仅经 close()，幂等；失败态关闭=合法清理）
  非法跳转 raise；迁移历史（from/to/reason/evidence/at）可审计
  require_ready(action)：terminal/非 session-alive -> 
    ProviderLifecycleTerminalError（ProviderError 子类，context 携带
    state/reason/evidence/refused_action/early_stop）——endpoint 函数
    调用之前抛出
  集成（真实控制流）：session.login 全失败类 -> 显式 terminal 态；
    logout -> close() 幂等；provider.call_exchange 第一道 lifecycle 门
    （terminal 后 capability gate 与 SDK 函数均不执行、零 exchange）
A3-02 Permission / Cache / Freshness 分 Gate（DM-CR-20260826-031，
    ADR-019 §2.3）：
  runtime_gates 六类显式分离（AUTH_ACCOUNT / PERMISSION /
    ENDPOINT_AVAILABLE / CACHE_METADATA / FRESHNESS_ASOF / BUSINESS_DATA）
  GateResult：explicit status（PASS/FAIL/NOT_TESTABLE/SKIPPED_BLOCKED）
    + blocking reason + traceable evidence_ref + provider_calls_fired 计数
  非掩盖性：PERMISSION 先于 CACHE（缓存健康不掩盖权限失败）；
    ENDPOINT 真实 probe（缓存不可替代 endpoint proof）；FRESHNESS FAIL
    阻断 BUSINESS（陈旧不得降级为有数据即 PASS）
A3-03 Early Stop Control Flow（并入 030/031）：
  RuntimeGatePipeline 顺序评估；首个 blocking（FAIL 或 NOT_TESTABLE——
    不可证即阻断）后，后续 gate SKIPPED_BLOCKED 且 evaluate 从不执行
  fault-injection 以 call-count / exchange-count / evidence-count 证明
    （permission fail -> business probe 计数 == 0）
A3-04 Runtime Truth / Trial Boundary（DM-CR-20260826-032）：
  capability approval 双入口（_validate_evidence + approve_from_spike_run）
    拒绝 TRIAL_*/FAKE*/UNKNOWN/空 account_profile_id——run kind PRODUCTION
    本身不构成 production truth
A3-05 Evidence Closure：
  gates 的 probe 走 ProviderExchange 显式边界（成功/失败 exchange 都
    可携带 evidence）；lifecycle 门在 exchange 创建之前（refused call
    不产生半截 evidence）；既有 ProviderExchange -> RawWriter 链零回归
```

## Golden / Trading Rule 人工 Review（结构就绪，等人工执行）

```text
scripts/golden/review.py 逐条核验 123 v3 cases + 补齐 distinct events
scripts/rules/review.py 对已验证 ACTIVE 规则版本执行人工复核（exact-byte
  + serialized-parent seal workflow，已 VERIFIED）
```

## R4-B1（R4-A3 VERIFIED 后启动；R4-B2 -> R4-B1 后；CR-2 -> R4-B2 后）

```text
Capability Approval 不接受 caller self-declare；绑定 provider/dataset/
  endpoint/account profile/runtime；persisted exchange evidence；
  permission/endpoint proof 与 business-quality proof 分离
（R4-B1/B2 正式开发要求在 A3 VERIFIED 后细化）
```

## 后续 CR

```text
CR-2 Provider-Normalized + Quarantine（after R4-B2）
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
Status: CLOSED for its current review-lineage definition（Reviewer
        2026-08-26 VERIFIED 裁决：R4-A2.11/CR-1.2.7 lock-before-preflight
        三重证明 + stale-parent 对抗通过；R4-A2.x / CR-1.x 审计链 CLOSED。
        连续 11 个批次的 exchange/evidence/review-lineage correctness
        修复全部 VERIFIED，冻结项无回归）
Note: 未来若 CR-2+ 引入新的 provider-normalized 消费面，按新工作要求
      重新开项（不得在旧条目上复活）
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

## DM-CR-20260826-033 — R4-A2.x / CR-1.x VERIFIED Governance Closure

**Type**：C1（治理闭环）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.11/CR-1.2.7 复审（2026-08-26 23:57 +08:00）裁决 **VERIFIED——R4-A2.x / CR-1.x 审计链 CLOSED**；Reviewer 要求下一逻辑开发提交同步状态至总册与 DEVLOG（不得改写历史），并修正两个误记 SHA（以 GitHub commit object 为准：Primary `38da90e5b5f3d698cc909cf7c258c163081bb9af`；Lint fix `6eac92dceaf57014f07d93bd5e6eabcea1dcbc79`；Reviewed HEAD `ab0cde7db4673224518540e1974c4e918bdbbf33`）。  
**Closure**：总册头部（Reviewed HEAD / Primary / Lint fix 正确 SHA + Phase Status 块 + SHA Correction 记录）；§40（R4-A2.9/A2.10 → VERIFIED (absorbed)；R4-A2.11 → VERIFIED；审计链 CLOSED；R4-A3 → PENDING_REVIEW；R4-B1/B2/CR-2 排序落位）；§41 重写为 R4-A3 批次；§52 RISK-004 → CLOSED for its current review-lineage definition（含"新消费面重新开项"注记）；ADR-018 索引标注 VERIFIED；DEVLOG 顶部新条目。  
**Affected Modules**：Documentation / Governance（DEVLOG、总册、ADR-000）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260826-032 — Runtime Trial/Production Truth Boundary

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3 A3-04——Trial/Fake 成功不得把 capability 标为 PRODUCTION APPROVED；run kind PRODUCTION 本身不构成 production truth。  
**New Contract**（ADR-019 §2.4）：capability approval **双入口**拒绝非生产账号——`_validate_evidence`（所有 approve 路径共用）与 `approve_from_spike_run`（spike 派生路径）均拒绝 `TRIAL_*` / `FAKE*` / `UNKNOWN` / 空 account_profile_id；既有 `new_run(PRODUCTION)` 的 `verify_production_account` 创建门保持（防御纵深：创建门被绕过/篡改时 approval 路径仍拒）。  
**Tests**：test_trial_production_boundary.py（7：参数化 5 类非法账号双语义拒绝 + 生产账号对照 + spike-run 路径防御纵深——monkeypatch 创建门后 APPROVAL 仍拒；模块属性访问纪律 + registry snapshot/restore 防泄漏）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) §2.4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260826-031 — Permission / Cache / Freshness Gate Separation

**Type**：C1 新 runtime 契约  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3 A3-02/A3-03——不同性质失败不得折叠为单一 "provider unavailable"；权限失败不能被缓存掩盖；缓存命中不能替代 endpoint proof；freshness 不足不得降级为"有数据即 PASS"；early-stop 须以计数证明。  
**New Contract**（ADR-019 §2.3）：`ashare_state.providers.runtime_gates`——六类 GateKind 显式分离（AUTH_ACCOUNT/PERMISSION/ENDPOINT_AVAILABLE/CACHE_METADATA/FRESHNESS_ASOF/BUSINESS_DATA）；GateResult（status: PASS/FAIL/**NOT_TESTABLE**/SKIPPED_BLOCKED + reason + evidence_ref + provider_calls_fired）；`RuntimeGatePipeline` 顺序评估 + early stop（首个 blocking=FAIL 或 NOT_TESTABLE 后，后续 gate 的 evaluate **从不执行**）。非掩盖性由顺序+early-stop 编码：PERMISSION 先于 CACHE；ENDPOINT 用真实 probe exchange；FRESHNESS FAIL 阻断 BUSINESS。gate 的 probe 走 ProviderExchange 显式边界（成功/失败 exchange 携带 evidence——A3-05）。  
**Tests**：test_runtime_gate_separation.py（15：各 gate 语义 ×9 / pipeline 全过 / permission-fail 阻断（probe 计数==1、business==0、total==1）/ 缓存健康不掩盖权限 / freshness 阻断 business / cache-metadata 阻断 / endpoint 失败阻断 / NOT_TESTABLE auth 全阻断零调用 / 每结果可审计）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) §2.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260826-030 — SDK Lifecycle State Machine + Early-Stop Enforcement

**Type**：C1 新 runtime 契约（session/provider 控制流变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3 A3-01——SDK unavailable/load failed/login failed/auth rejected/session ready/subscribe/callback/unsubscribe/logout 必须是显式 lifecycle state/terminal state；不允许异常字符串猜测流程状态；terminal 后无 business call；cleanup 幂等。  
**New Contract**（ADR-019 §1/§2.1/§2.2）：`ashare_state.providers.lifecycle.SdkLifecycle`（显式状态 + 合法迁移表 + 迁移历史 + 幂等 close（失败态关闭=合法清理）+ `require_ready` → `ProviderLifecycleTerminalError`（ProviderError 子类，context 含 state/reason/evidence/refused_action/early_stop））。集成：`AmazingDataSession.login` 全失败类落显式 terminal 态（SDK_UNAVAILABLE/LOAD_FAILED/AUTH_REJECTED/LOGIN_FAILED）、成功落 SESSION_READY（evidence=account_profile_id）；`logout` → close()；`AmazingDataProvider.call_exchange` **第一道 lifecycle 门**（terminal 后 capability gate 与 SDK 函数均不执行、零 exchange/零 evidence）。测试 fake session 同步携带 lifecycle（SESSION_READY）。  
**Compatibility**：ProviderError 层新增一个子类；既有调用方（捕获 ProviderError）不受影响。  
**Tests**：test_sdk_lifecycle.py（15）+ test_runtime_early_stop.py（11：SDK absent/load 异常/auth 拒绝/network 失败的 call-count 证明；terminal 后 endpoint 函数零调用+零 envelope（参数化 5 态）；INIT 拒绝；READY 对照；真实 session login/logout/close 驱动）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) §1-§2.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-029 — R4-A2.10 Reviewer Governance Correction

**Type**：C1（治理修正）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.10/CR-1.2.6 复审 §5——治理文档须记录 Reviewed HEAD `846fd458cc2c740f423699dabdbe0f4d48bf9c24`（run 49 三腿 success）与 Primary Implementation `8d29c16d2476a48e105b091a9ec63b2b39c3d77e`；R4-A2.10 = Implementation DONE / Review REOPENED（P0 byte-identity 主体 = PASS / frozen；publish cleanup = PASS / frozen；DM-CR-20260825-025 single-writer = REOPENED，原因 = lock acquired AFTER parent-dependent Phase 1）；ADR-018 §4 overclaim 需 amendment 不删历史；RISK-004/CR-2/R4-A3/P0-M-1B 保持。  
**Correction**：总册头部更新（Reviewed HEAD + Reviewer Correction 段：lock 覆盖范围 overclaim）；§40 R4-A2.10 → REOPENED（PASS/FREEZE 项与 REOPENED 项分列）；ADR-018 §4 amendment（修正记录 + 索引标注）。  
**Affected Modules**：Documentation / Governance（DEVLOG、总册 §40/§41/§52/§61、ADR-018/ADR-000）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-028 — Single-Writer Lock Scope / Stale-Parent Regression

**Type**：C1 correctness closure（含测试矩阵）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.11 P0-01 测试要求——现有测试只覆盖锁文件存在性（fail fast / 成功释放 / 失败释放），存在 control-flow blind spot：未覆盖"两个 reviewer 在任一获锁前都对同一 parent 完成 Phase 1"的 stale-preflight race。  
**New Contract**（ADR-018 §4 amendment）：三重证明矩阵——①runtime counter：`load_active_rules`（parent selection）执行时 `.review.lock` 必已存在（`lock_exists_at_preflight is True`）；②AST 结构守卫：锁获取（O_EXCL open，含 BitOr 嵌套 flag 匹配）行号先于首个 `load_active_rules`；③stale-parent 对抗：A 提交 v2 后 B 的 v1-based 提交（`--from-version v1`）BLOCK（lineage moved；零新 version/零新 evidence/零 manifest 推进/锁释放）；无 `--from-version` 时 stale `--rules` 输入被 input==ACTIVE 拒绝；B 从 current ACTIVE（新 COMPILED 候选）重启正常；同版本 race 撞 immutable collision（首版字节逐字节不动）；并发锁 fail fast 先于任何 ACTIVE 读取（`load_active_rules` 调用数 == 0）；成功/失败后锁释放保持。  
**Affected Modules**：tests/integration/test_review_lineage_serialization.py（8 个）  
**ADR**：[ADR-018](../adr/ADR-018_review_publish_byte_identity.md) §4 amendment  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-027 — Review Parent-Identity Serialization Closure

**Type**：C1 correctness closure（控制流重排）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.11 P0-01——`.review.lock` 获取位于 Phase 1（snapshot/sandbox）之后：两个 reviewer 可基于同一旧 parent 完成 Phase 1，随后依次获锁提交，第二个用 stale parent snapshot 覆盖第一个的 ACTIVE advance。"Phase 2/3 串行" != "review parent lineage 串行"。  
**Old Contract**：`main()` 完成全部 ACTIVE-dependent 读取（load_active_rules / lineage / COMPILED / version 检查 / snapshot / reviewed_bytes / sandbox）后才获取锁；锁只包 `_review_locked_workflow`（Phase 2/3）。  
**New Contract**（ADR-018 §4 amendment，Option A）：**lock-before-preflight**——`main()` 仅做 CLI parse + 参数 lexical 检查 + rules_path/artifact 存在性检查后即获取锁；整个 workflow（ACTIVE integrity + parent identity → snapshot → transform → sandbox → staged gate → publish → manifest commit → post-commit verification）在 `_review_workflow_locked` 内于锁内执行；finally 释放保持。**四问**：①原 placement 只串行化提交不串行化 parent 选择（stale-preflight race 实测可复现）；②parent identity 在锁内建立（preflight 本身持锁）；③选 Option A 而非 Option B（recheck）——A 使 ADR-018 原广告语义成立且单一代码路径，B 需双份 parent 验证 + ADR 改写为 optimistic snapshot 语义；④成本 = 持锁时间稍长（preflight 纳入，竞争时快速失败），收益 = stale-parent 覆盖在构造上不可能。  
**Affected Modules**：scripts/rules/review.py（main 拆分：Phase 0 锁获取 + `_review_workflow_locked` 全流程）  
**Tests**：test_review_lineage_serialization.py（8）+ 全量 658 保持（既有 byte-identity/cleanup/confinement 测试零回归）  
**ADR**：[ADR-018](../adr/ADR-018_review_publish_byte_identity.md) §4 amendment  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-026 — R4-A2.9 Reviewer Governance Correction

**Type**：C1（治理修正）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.9/CR-1.2.5 复审 §7——治理文档须记录 exact SHA（Reviewed HEAD `8a6f4149e0f7090850b77c3b2e6a804b8ef45595` / Primary Implementation `793dfc1220e3d1b8669483c008a8596150b0dcd6` / Cross-Platform CI Fix `b429220663897060b7940c727d0e09ec902192de`）；R4-A2.9 → REOPENED（输入侧冻结 + 输出侧未闭合）；RISK-004 保持；ADR-017 需 amendment 不删历史；CI = run 46 全三腿 success（不得再写"optional Ubuntu 仍失败"）。  
**Correction**：总册头部改为 exact SHA 三元组（Reviewer doc commit 不再被误写成 implementation baseline）；§40 R4-A2.9 → REOPENED；RISK-004 理由更新；ADR-018 为 ADR-017 §1 未完成环的修正记录（索引标注 amended by）。  
**Affected Modules**：Documentation / Governance（DEVLOG、总册 §40/§41/§52/§61、ADR-018/ADR-000）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-025 — Review Single-Writer / Commit-Lineage Policy

**Type**：C1（运维契约）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.10 P1-02——`--from-version` 只在 Phase 1 验证 lineage；长流程中另一 reviewer 推进 ACTIVE 时 Phase 3 仍可能覆盖新 selector；不得继续把 `--from-version` 描述成完整并发 CAS。  
**New Contract**（ADR-018 §4，Option A）：`rules_root/.review.lock`（`O_CREAT|O_EXCL`）覆盖 preflight → snapshot → staged gate → manifest commit 全程；并发 reviewer fail fast（错误信息指明 stale lock 手动清理路径）；finally 释放（成功/失败均释放）。**诚实记录**：advisory + 进程级锁，非 OS-level CAS；check 与 replace 之间仍非原子 CAS，正式并发写由 single-writer 运维契约兜底；`--from-version` 语义降级为 lineage 提示。  
**Tests**：test_review_publish_integrity.py::TestSingleWriterLock ×3（并发 fail fast + 零 mutation + 外来锁不被删除 / 成功后释放 / 失败后释放）  
**ADR**：[ADR-018](../adr/ADR-018_review_publish_byte_identity.md) §4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-024 — Review Publish Failure Cleanup / Retry Semantics

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.10 P1-01——publish 的 except 只清 staging_dir：rename 成功后 manifest 写失败会留下 finalized versions/<new>/（immutable collision 使 same-version retry 永久失败）+ 孤儿 evidence + ACTIVE 仍旧。  
**New Contract**（ADR-018 §3）：**commit boundary = ACTIVE manifest 原子替换成功**。`published_version` / `created_evidence` / `manifest_committed` 状态跟踪驱动 `_cleanup_uncommitted`：提交前任何失败（含注入的 tmp manifest write 失败 / manifest replace 失败 / read-back mismatch / gate 失败 / 异常）→ 移除新 published version_dir + 本次创建 evidence + staging + tmp manifest → ACTIVE 保持旧 selector → 同版本重试可行；提交后验证失败 → 显式 `REVIEW_COMMIT_INCONSISTENT` 硬失败（exit 3——ACTIVE 已指向新版本，人工介入，绝不伪装成可重试失败）。  
**Tests**：TestPreCommitFailureCleanup ×2（write/replace 注入 → 完整清理 + 同版本重试成功）+ TestPublishWindowTamper::test_tampered_retry_is_deterministic  
**ADR**：[ADR-018](../adr/ADR-018_review_publish_byte_identity.md) §3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-023 — Manifest Seal Identity / Publish TOCTOU Closure

**Type**：C1 correctness closure（manifest identity 语义变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.10 P0-02——旧 Phase 3 在 rename 后**重新 read final rules.yaml** 并用该 read 计算 manifest.dataset_hash：gate 验证 R → rename → final 被替换为 T → reread T → manifest 封存 hash(T) → ACTIVE 指向 T 且 coherence 通过——"gate 验证了 R，manifest 祝福了 T"（输入侧 double-read TOCTOU 的输出侧镜像）。  
**Old Contract**：`published_bytes = read_bytes(final); manifest.dataset_hash = hash(published_bytes)`。  
**New Contract**（ADR-018 §2）：manifest identity 唯一来源 = gate-validated **in-memory reviewed_bytes**（`expected_dataset_hash = _hash_snapshot([(final_rel, reviewed_bytes)])`）；publish 后 read-back 为 **VERIFICATION ONLY**（`actual != reviewed_bytes` → BLOCK + rollback：移除已 publish 的 version_dir 与本次 evidence，ACTIVE 不推进）。篡改字节在构造上不可能进入 manifest。  
**Tests**：TestPublishWindowTamper::test_post_rename_tamper_fails_closed_and_rolls_back（monkeypatch Path.replace 在 rename 后注入 tamper → fail closed + 回滚 + ACTIVE 保持 v1-compiled + dataset_files 不变）+ test_manifest_hash_derives_from_reviewed_bytes（独立重算）  
**ADR**：[ADR-018](../adr/ADR-018_review_publish_byte_identity.md) §2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-022 — Persisted REVIEWED Exact-Byte Identity

**Type**：C1 correctness closure（输出路径字节语义变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.10 P0-01——REVIEWED 经 `Path.write_text()` 落盘：Windows 文本模式换行翻译可把内存 LF 写成 CRLF（persisted bytes != exact transformed bytes）；既有等价测试用 `read_text().splitlines()` 被 universal-newline 归一化蒙蔽。  
**Old Contract**：`staged_yaml.write_text(reviewed_text)`（sandbox 同）。  
**New Contract**（ADR-018 §1）：`reviewed_bytes = reviewed_text.encode("utf-8")` 单一不可变内存对象；sandbox 解析 / staged rules.yaml / 全部正式 dataset 写入 **write_bytes ONLY**；不变量链 ACTIVE snapshot → reviewed_bytes → write_bytes → staged → atomic rename → final 全程字节同一；**AST 静态守卫**（review.py 禁止任何 `write_text` 调用——文本模式在构造上被排除）。  
**Tests**：TestPersistedByteIdentity ×4（final bytes LF-only 且 == 独立重建的 reviewed_bytes（yaml datetime isoformat 还原）/ manifest hash 独立重算一致 / 生成版本 load_active_rules + load_bound_rule_book 重放（跨平台字节真相）/ AST 禁 write_text）——CI 两 OS matrix 均执行（测试对象是**工具生成的**数据集，非仓库已提交 yaml）  
**ADR**：[ADR-018](../adr/ADR-018_review_publish_byte_identity.md) §1  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-020 — R4-A2.8 Reviewer Governance Correction

**Type**：C1（治理修正）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.8/CR-1.2.4 复审 §6——治理文档须记录 Reviewed baseline `ada0eac2d973730605f7af65f57e72a22e1483c1` / 三个原始 P0 主体冻结 / REOPENED / CI job-level truth / RISK-004 保持；ADR-016 §3 的"exact ACTIVE bytes"表述为 overclaim（double-read gap），需 amendment 不删历史。  
**Correction**：总册头部更新（Reviewed baseline + Reviewer Correction 段：seal double-read TOCTOU / version 输出无 confinement / CI 全矩阵非绿）；§40 R4-A2.8/CR-1.2.4 → REOPENED（主体冻结 + 由本批修复）；RISK-004 理由更新；ADR-017 为 ADR-016 §3 的修正记录（索引标注 amended by）。  
**Affected Modules**：Documentation / Governance（DEVLOG、总册 §40/§41/§52/§61、ADR-017/ADR-000）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-019 — Cross-Platform CI Truth / Byte-Exact Fix

**Type**：C1 correctness fix（真实跨平台 bug）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.9 §5——Reviewer 下钻 run 42 job matrix：optional Ubuntu 3.14 的 Pytest step 实际 FAILED（~20 测试同错 `ACTIVE dataset hash mismatch: declared 7dc5f627... recomputed dd2219d2...`），overall SUCCESS 仅因 `continue-on-error: ${{ !matrix.required }}`；不得表述"全矩阵绿"。  
**Root Cause（API 日志查证）**：**根因 1**——`.gitattributes` 覆盖 `data/golden/**`/`*.json`/`*.jsonl` 但**漏 `*.yaml`**：Windows autocrlf checkout 重写 LF→CRLF（本地 hash 与 manifest 一致故 Windows CI 过），Ubuntu checkout 保持 LF（重算 hash 失配）；golden 未挂因已有 LF 规则。**根因 2（run 44 查证）**——golden review gate 的 artifact confinement 平台依赖：Linux 上 `evidence_dir / "C:/evil.txt"` 是**相对**拼接（resolved 检查不见逃逸，仅报"不存在"），Windows 上盘符使其绝对（被检出）；`test_absolute_artifact_ref_rejected` 因此在 Ubuntu 失败。均属**真实跨平台 correctness bug**（非环境依赖）。  
**Fix**：根因 1——`.gitattributes` 补 `*.yaml`/`*.yml text eol=lf` + `configs/trading_rules/evidence/** -text`（内容寻址 artifact 禁 eol 归一化）；工作树 yaml 规范化 LF（`git diff` 与 blob 字节零差异）；`rule_manifest.json` dataset_hash 以 LF 字节重算（`dd2219d2...` 与 Ubuntu 重算值完全一致——两平台自此同字节）。根因 2——`golden_store._verify_artifact` 先做**平台无关 lexical 检查**（前导 `/`、盘符前缀、`..` 穿越——与其他 confinement 同一"lexical first, resolved second"设计语言）再 resolved 比较。回归测试 ×5（yaml 无 CRLF / .gitattributes 规则 / 工作树 == git blob / 盘符 ref 双平台拒 / POSIX 绝对 ref 双平台拒）。  
**Policy（§5.2）**：未削弱 required gate、未 skip 测试、未删除 Ubuntu leg；`continue-on-error` 策略不变；CI 真相以 job-level 记录于总册头部；本批提交后以 Actions 实际结果为准（重点观察 Ubuntu leg 转绿）。  
**Affected Modules**：.gitattributes、configs/trading_rules/{rule_manifest.json, versions/v20260824-compiled/rules.yaml}、spike/golden_store.py  
**Tests**：test_review_failure_cleanup.py::TestCrossPlatformRuleBytes ×3 + test_golden_review_workflow.py 平台无关 ×2  
**ADR**：[ADR-017](../adr/ADR-017_review_seal_output_confinement.md) §4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-018 — Trading Rule Review Output-Version Confinement

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.9 P0-02——`--version` 未验证即拼路径：`../escape`/`foo\/bar`/绝对路径/盘符样式可在 versions root 外创建目录；且 evidence 拷贝等 mutation 先于 version 冲突检查。  
**Old Contract**：`version_dir = rules_root / "versions" / args.version` 直接 mkdir/write。  
**New Contract**（ADR-017 §2）：`_validate_version_id`——Step A lexical（单一组件语法 `^[A-Za-z0-9][A-Za-z0-9._-]*$`，显式拒 `.`/`..`；分隔符/盘符/绝对路径在语法层不可能）；Step B resolved confinement（`versions_root/<id>` resolve 后必须位于 versions/ 内）；Step C 顺序（version 语法+confinence+不存在性等**全部确定性校验**先于任何输出 mutation——既有版本冲突先于 evidence 拷贝）。**测试**：12 类非法 id → 拒绝 + **before/after 文件树快照零差异**（覆盖 versions/ 内创建与越界逃逸）；合法 id 输出仅在 versions/<id>/ 且恰为 rules.yaml。  
**Affected Modules**：scripts/rules/review.py  
**Tests**：test_review_version_confinement.py（17：参数化 12 + 合法 1 + 冲突 1 + eol 豁免 1 + blob 一致性 1 + tree snapshot 内含）  
**ADR**：[ADR-017](../adr/ADR-017_review_seal_output_confinement.md) §2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-017 — Trading Rule Review Exact-Byte Seal + Staged Output

**Type**：C1 correctness closure（review 工作流 seal 语义变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.9 P0-01——旧实现两次独立读取 ACTIVE 文件（Read A 生成 REVIEWED 副本、Read B `_dataset_files_hash` 验证）：swap→capture→restore→verify→seal-tampered 的 TOCTOU 使"hash 验证的字节 ≠ 被封存的字节"。  
**Old Contract**：capture 与 verify 分离（ADR-016 §3 的"已验证 ACTIVE bytes"表述为 overclaim）。  
**New Contract**（ADR-017 §1/§3）：**一次性 snapshot**——`active_bytes = read_bytes()` 单次读取；`_hash_snapshot([(rel, active_bytes)])` 用 manifest 同一算法对**内存字节**计算（与 manifest hash 相等即证明 snapshot 就是 ACTIVE 字节）；`_build_reviewed_text(active_bytes, ...)` 从同一 snapshot 构造副本；此后**无任何 ACTIVE 文件第二次读取**；输出 `sealed from ACTIVE snapshot sha256=<hash>` 供复核。**Staged 输出**（P1 并入）：Phase 1 纯校验/snapshot（含 REVIEWED 副本临时沙箱解析——零 rule-store mutation）→ Phase 2 staged（evidence 内容寻址 + `versions/.staging-<id>/` 运行完整 gate；gate 失败显式移除 staging+本次 evidence——`return` 在 try 内不触发 except 的坑已修）→ Phase 3 publish（staging 原子改名 `versions/<id>/`；ACTIVE manifest 最后原子替换；publish 后 manifest 的 dataset_hash 从 published bytes 计算）。**测试**：exact-byte 7（健康流报告 snapshot sha / REVIEWED 内容从 exact snapshot 逐行推导 / preflight 后篡改读取 BLOCK 零输出 / 无第二次读取可替换 seal 身份 / 控制组 / ACTIVE 文件读取数 == preflight+1 / 篡改零输出）+ cleanup 4（gate 失败无 finalized version+无 evidence / 不推进 ACTIVE / preflight 失败无 temp / 失败后重试确定性）。  
**Affected Modules**：scripts/rules/review.py  
**Tests**：test_review_seal_exactness.py（7）+ test_review_failure_cleanup.py（7 中 4 项属本条）  
**ADR**：[ADR-017](../adr/ADR-017_review_seal_output_confinement.md) §1/§3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-016 — R4-A2.7 Reviewer Governance Correction + P1 Hardening

**Type**：C1（治理修正 + P1 加固）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.7/CR-1.2.3 复审 §6——治理文档须记录 Reviewed Code Baseline `47b47437b0828262e4f9f11c57862af2558a4d34` / REOPENED / CI run 40 SUCCESS / RISK-004 保持 REOPENED；P1-01（endpoint 身份交叉校验）与 P1-02（空 frame schema）建议本批清掉。  
**Correction & P1**：总册头部更新（Reviewed baseline + Reviewer Correction 段：CA control-flow / lexical-first 顺序 / review integrity 未关闭）；§40 R4-A2.7/CR-1.2.3 → REOPENED；`CA_STREAM_ENDPOINTS` 固定映射（dividend↔get_dividend / right_issue↔get_right_issue；跨流重标 → `CAProviderShapeError`）；`_payload_columns` + `_ca_provider_view(payload_columns=)`：0 行+必需列=合法空事件流、0 行+缺列=`PROVIDER_SCHEMA`。  
**Affected Modules**：spike/golden_router.py、Documentation / Governance  
**Tests**：test_ca_atomic_boundary.py::TestEmptyFrameSchema ×3 + TestEndpointIdentityCrossCheck ×2  
**ADR**：[ADR-016](../adr/ADR-016_atomic_boundary_integrity.md) §4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-015 — Trading Rule Review Input Integrity Gate

**Type**：C1/C2（review 工作流契约变更）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.8 P0-03——review.py 只验证 selector 可解析（`load_rule_manifest`），被篡改/不一致的 COMPILED ACTIVE 可被"洗成"新的合法 REVIEWED 版本（human review ≠ re-seal an integrity-broken candidate）。  
**Old Contract**：preflight = manifest 可读 + --from-version / 单文件 / --rules==ACTIVE 路径比较；REVIEWED 副本从 --rules 路径二次读取。  
**New Contract**（ADR-016 §3）：preflight 不可绕过执行 `load_active_rules`（ACTIVE dataset hash 复算 + manifest↔dataset 四字段 coherence——与 runtime 同一 gate）；增加 review_status==COMPILED 校验（REVIEWED ACTIVE 拒绝再 review）；REVIEWED 副本从**已验证 ACTIVE bytes** 产生（canonical 路径读取 + 读取后复验 hash，无 TOCTOU）；preflight 失败 → **零输出**（无 evidence 拷贝、无 versions/<new>/、无 temp/final manifest 变更）；§4.4：source_version/dataset_version REQUIRED 下沉 `load_rule_manifest` schema 校验（review/selector 工具与 runtime 共享单一 manifest API 契约）。  
**Affected Modules**：scripts/rules/review.py、spike/trading_rule.py（manifest schema）  
**Tests**：test_review_input_integrity.py（9：篡改 bytes/篡改 manifest hash/缺 source_version/空 dataset_version/coherence mismatch ×3/健康流成功/REVIEWED 拒绝——全部含零输出断言）  
**ADR**：[ADR-016](../adr/ADR-016_atomic_boundary_integrity.md) §3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-014 — Bound Rule Lexical-First Pre-Access Confinement

**Type**：C1 correctness closure（ADR-014/015 契约补全）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.8 P0-02——`_confined()` 先 `Path.resolve()` 再 containment 比较：非法 `../..` ref 在 lexical 拒绝前已触发 filesystem resolution（"confinement before ANY fs access" 仍为 overclaim）。  
**Old Contract**：`_confined(root, rel)`（resolve-first）+ `_confined_dataset_file`（内含 lexical）并列调用，顺序不透明。  
**New Contract**（ADR-016 §2）：`_lexically_confined_dataset_file`（Step A：非空/相对/无盘符/无 `..`/versions/<rule_version>/ 结构——**零 fs 访问**）；`_confined_dataset_file` 成为**唯一入口**（Step A → Step B resolved symlink escape）；bound loop 删除前置 `_confined`（双 helper 并列废除）；evidence ref 的 `_confined` 增加 lexical `..` 前置拒绝。**测试**：`Path.resolve` spy——traversal（外部文件存在）/绝对/盘符/异版本目录的拒绝全程 **candidate 未被 resolve**；合法路径才触发 resolve；symlink escape 仍在 Step B 拦截；正常 bound replay 保持通过。  
**Affected Modules**：spike/trading_rule.py  
**Tests**：test_lexical_first_confinement.py（9：拒绝前零 resolve ×4 / 合法 resolve / symlink / 正常通过 / helper 单元 ×2）  
**ADR**：[ADR-016](../adr/ADR-016_atomic_boundary_integrity.md) §2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-013 — Golden Domain Atomic Exchange Persistence

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.8 P0-01——CA 域 assign-then-persist（`x = target.X(); ...; collector.persist(x)`）重新打开"真实 exchange 已创建但未持久化"窗口：第二个 provider call 失败时第一个 success exchange 永久丢证据（real calls=2 / persisted=1）；AST 守卫已退化为 name-presence 检查。  
**Old Contract**：调用者取得 exchange 引用后另行 persist（"记得稍后持久化"）；AST 守卫接受 assign-then-persist（变量名某处出现 persist 即可）。  
**New Contract**（ADR-016 §1）：`_DomainCollector.call(fn) -> PersistedExchangeView`（frozen dataclass：payload/request_id/endpoint/evidence_meta）——**call+persist 是一个边界操作**（exchange 在边界返回前已持久化；lineage 从 view 读取）；**全部域 fetch**（ST_STATUS/DELISTED_MASTER/LIMIT_PIT_RULE/CORP_ACTION_CONTEXT/BJ_MAPPING）统一走原子边界；AST 守卫升级**控制流安全**（exchange 调用必须位于 `collector.call(lambda: ...)` 的 lambda 内；负向测试证明旧 assign-then-persist 源码被拒）。  
**Affected Modules**：spike/golden_router.py、tests/integration/test_probe_exchange_enforcement.py（守卫收紧）  
**Tests**：test_ca_atomic_boundary.py（7：dividend 成功+right_issue 失败→两者都持久化+call 数==persisted 数 / persist 失败→后续 provider call 不发射 / dividend 失败→right_issue 不发射 / full success lineage / 空 frame ×3 / endpoint 交叉 ×2）；既有 router/CA/enforcement 测试适配  
**ADR**：[ADR-016](../adr/ADR-016_atomic_boundary_integrity.md) §1  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-012 — R4-A2.6 Review Correction & Governance Sync + Review Tool Hardening

**Type**：C1（治理修正 + 工具加固）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.6/CR-1.2.2 复审 §8——总册 Baseline 缺 exact SHA（2e85f447...）；CI 状态未更新至 run 38；ADR-014/§41 声明"任何 fs 访问前 confinement"而 runtime 不完全满足（overclaim）；P1-01/02（review.py 单文件静默限制 / durability wording）。  
**Correction**：总册头部 exact SHA（上批 implementation 2e85f447 + run 38 success）+ Reviewer Correction 段（ADR-014 overclaim 记录，以 ADR-015 §5 为准）；§40 R4-A2.6/CR-1.2.2 → REOPENED（由本批修复）；RISK-004 保持 REOPENED；review.py：multi-file ACTIVE 显式 fail loud（Option A，禁止未来 silent review only first file）+ wording 更正（atomic replacement / reader-safe——非 power-loss durable，无 fsync）。  
**Affected Modules**：scripts/rules/review.py、Documentation / Governance  
**Tests**：binding::TestReviewScriptHardening（保持）+ 单文件拒绝逻辑（multi-file manifest 场景）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-011 — Corporate-Action Provider-Shape Validation Adapter

**Type**：C1/C2 implementation-semantic closure（Raw SoR 不变；validation 边界新增 adapter 契约）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.7 P0-04——CA validator/FakeTarget 消费 canonical-like 字段（SECURITY_CODE/EX_DATE/EVENT_TYPE），而 AmazingData 官方文档（3.5.7.1/3.5.7.2）真实字段为 MARKET_CODE/DATE_EX 与 MARKET_CODE/EX_DIVIDEND_DATE；EVENT_TYPE 被伪造成 payload 列。真实账号上 CA formal Golden 无法按真实数据验证。  
**Old Contract**：validator 直接 `r.get("SECURITY_CODE"/"EX_DATE"/"EVENT_TYPE")`；FakeTarget 合成同名字段（canonical 旁路）。  
**New Contract**（ADR-015）：`CA_PROVIDER_FIELD_CONTRACT` 显式文档契约；`_ca_provider_view` ephemeral 归一化（MARKET_CODE→security_code；DATE_EX/EX_DIVIDEND_DATE→ex_date；event_type=**端点身份**派生，payload 伪造 EVENT_TYPE 列被忽略）；view 携带 source_endpoint/raw_request_id lineage；缺文档字段→`CAProviderShapeError`→route_all 结构化 `VALIDATED_FAIL(PROVIDER_SCHEMA)`（fail loud）；FakeTarget 改 provider 原生字段（dry-run 与 real 同一 adapter）；raw evidence 保持 provider 原生字段名（parquet 列名断言）；validator v6（消费小写语义字段）。**方案取舍**（审计 §13 四问）：不改 raw（Raw SoR 不可变）、不在 validator 内散落别名探测（first-alias-wins 禁止）、不启动 CR-2（不稳定契约不传播）——ephemeral adapter 是最小且集中的契约点。  
**Affected Modules**：spike/golden_router.py、spike/target.py  
**Tests**：test_ca_provider_shape.py（13：view 归一化×3/伪造 EVENT_TYPE 忽略/缺字段×3/未知流/FakeTarget provider 字段/raw parquet 原生列名/端到端 PASS/反向 endpoint/结构化 PROVIDER_SCHEMA/真实 v3 case）+ test_ca_event_type/sor 适配  
**ADR**：[ADR-015](../adr/ADR-015_ca_provider_shape_adapter.md) §1-§4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-010 — Required Rule Metadata Coherence

**Type**：C2 amendment to ADR-014 §2  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.7 P0-03——coherence 对 source_version/dataset_version 仍是"填了才比较"可选语义：manifest 空字段可放行（dataset 真实 lineage 被走私；new_run 会绑定空 source_version 形成 formal lineage 缺失）。  
**Old Contract**：`if manifest.dataset_version and ...` / `if manifest.source_version and ...`（条件比较）；provenance_complete 不要求 dataset_version/source_version；bound replay 只复验 selector+hash+content-version。  
**New Contract**（ADR-015 §5.3）：两字段 **必填非空 + 无条件精确比较**（missing/empty/mismatch 全 BLOCK）；`provenance_complete()` 对 PRODUCTION 要求 dataset_version + source_version 非空；`load_bound_rule_book` 增 source_version/review_status 复验参数（runner 的 verdict/resume + probes.rule_book 三处调用全传完整身份——bound 与 loaded 不一致即 BLOCK）。  
**Affected Modules**：spike/trading_rule.py、spike/model.py、spike/runner.py、spike/probes.py  
**Tests**：test_rule_required_coherence.py（12：required×4 + mismatch×2 + coherent PASS + provenance×3 + bound disagree×2 + 完整一致加载）  
**ADR**：[ADR-015](../adr/ADR-015_ca_provider_shape_adapter.md) §5.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-009 — Raw Evidence Identity / Idempotency Closure

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.7 P0-02——完整幂等成功重试返回 sha256(新 meta_bytes)（含新 ingested_at），而磁盘保留旧 meta → returned evidence_hash != sha256(persisted file)；SpikeCase 绑定二次返回值后 verify_evidence_closure 必然失败。违反 "RawWriteResult must describe the persisted evidence"。  
**Old Contract**：`meta_hash = sha256(meta_bytes)`（in-memory serialization）。  
**New Contract**（ADR-015 §5.2）：所有 success return path 以**磁盘实际 bytes** 计算 evidence_hash/meta_artifact（`meta_path.read_bytes()`）；fresh commit 断言 persisted == intended；幂等重试返回 existing persisted hash（**不覆盖旧 meta**——immutable semantics 保留首次成功落盘 bytes）。**方案取舍**：不为 hash 一致而重写旧 meta（会破坏 immutable 语义与首次审计痕迹）。  
**Affected Modules**：storage/raw_writer.py  
**Tests**：test_raw_identity.py（6：幂等返回磁盘 hash/单表/多表 closure/失败幂等/orphan 恢复/fresh 断言）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260825-008 — Bound Rule Pre-Access Confinement Closure

**Type**：C1 correctness closure（ADR-014 契约补全）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A2.7 P0-01——`load_bound_rule_book` 曾以 `(root / dataset_files[0]).is_file()` 探测 root（**fs probe 先于 confinement**）：篡改绑定 `../../outside.yaml` 在被拒绝前已对 root 外路径发生一次存在性探测。ADR-014 声明的 "confinement before ANY filesystem access" 仅 ACTIVE 路径成立（overclaim）。  
**Old Contract**：root = 第一个使 dataset_files[0] 存在的候选；随后逐文件 confinement。  
**New Contract**（ADR-015 §5.1）：root 由参数**确定性**解析（rules_root / repo_root / default dir——不触碰 dataset_files）；全文件 confinement（lexical + resolved + versions/<rule_version>/ 结构）先行；**之后**才存在性/read/hash/load。FsSpy（patch Path.is_file/read_bytes/open）测试证明：traversal（外部文件真实存在）/绝对路径/异版本目录的拒绝全程**零越界 fs 访问**。  
**Affected Modules**：spike/trading_rule.py  
**Tests**：test_bound_pre_access.py（4：traversal 零探测/绝对零探测/异版本目录零探测/合法 multi-file PASS）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

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

R4-A3 已更新（2026-08-26，见 DM-CR-20260826-030/031/032/033）：

```text
§40 §41 §52 §61 §62 + 头部（VERIFIED closure 同步 / SHA correction / Phase Status）(done 2026-08-26)
```

R4-B1 落地时至少更新：

```text
§41 §44             (B1 契约与 acceptance)
§48 §52 §61         (entry gate / 风险 / Change Log)
ADR（若 capability approval 契约演进）
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
