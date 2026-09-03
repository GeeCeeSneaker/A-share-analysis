# A-share-analysis 开发管理总册（Development Management）

> **仓库固定路径（MUST NOT RENAME）**：`docs/project/DEVELOPMENT_MANAGEMENT.md`  
> **文档性质**：长期持续维护的项目级“当前设计 + 当前状态 + 开发计划 + 变更控制”总册  
> **项目**：A股市场态势数据基座（日频模块）  
> **Frozen Baseline**：V1.3.2  
> **Reviewed Repository HEAD**：`ab0cde7db4673224518540e1974c4e918bdbbf33`（R4-A2.11/CR-1.2.7 复审基线，run 53 全三腿 success；**VERIFIED**）  
> **Primary Implementation（R4-A2.11）**：`38da90e5b5f3d698cc909cf7c258c163081bb9af`  
> **CI/Lint Fix（R4-A2.11）**：`6eac92dceaf57014f07d93bd5e6eabcea1dcbc79`  
> **Current Code Baseline**：CR-4 首批 implementation `2db6d8d6cc1fef047175b1f23c80016f003eee63` + 两个 assertion-only CI fix `397ea7c`（superset winner 断言）/ `0c328c3de95c636df053a52bb5b4814fde2d14cb`（spike evidence glob 平台序）——基于 CR-3 全链 closure reviewer 基线 `ff3808b7a5036246ea11e37173aa31d863beb2d9`（CR-3.6 最终复审 VERIFIED/CLOSED/FREEZE + CR-4 启动裁决 commit，2026-09-02 21:24 +08:00；CR-3.6 implementation `1ebe96b9d28617939c2782795395ef23eee597e0` run 33623939024 三腿 success）；CR-3.5 implementation `48982290056cf88e6daafbecb7d8b8a766da6e28`（run 33601822767 三腿 success）；CR-3.4 implementation `fce2ca43a35b95d61dc390647fdc46d844d9b1a5`（run 33591527697 三腿 success）；CR-3.3 implementation `f8b80b3212ff299f52ee3fb0308c248fd16c17df`（run 33581493160 三腿 success）；CR-3.2 implementation `df409ede0ddb25ce5cee12a46fa66fe7a3ea093f`（run 33521594830 三腿 success）；CR-3.1 implementation `75744aaa89487aae09474b3569519a73f0efba24`（run 33508307611 三腿 success）；CR-3 implementation `ae5b76c998196f936ae6430408d2a016a35aec0d`（run 33498314119 三腿 success）；CR-2.4 implementation `3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc`（run 33482144065 三腿 success）；CR-2.3 implementation `480dc7549bb512e9c187213e5010fab424248774`（run 33472357951 三腿 success）；CR-2.2 implementation `a06ea2202cb4f7a5ea0a91c09e666867267a8575`（run 33460094366 三腿 success）；CR-2.1 implementation `2bd0c31fa47c18b520c192265ce306f44a217fc3`（run 33398654940 三腿 success）；CR-2 implementation canonical SHA `15cdae25fd7d11e3be0da3683e821629e4226291`（run 33378006770 三腿 success；**SHA Correction 见下方 2026-08-31 P1-01 更正行**）；R4-B2.3 implementation `7362dfc93ab5ea6eb7ebc63c8fddb4508d7942aa` + CI fix `85a9260eb0cc07ea81c7844f661388e113575aa6`（run 33365674254 三腿 success）  
> **Document Revision**：DM-CR-20260830-054..060 / DM-CR-20260831-061 / 062 / 063 / 064 / DM-20260901-065 / 066 / 067 / 068 / 069 / 070 / DM-20260902-071 / 072 / 073 / 074 / DM-20260903-075  
> **Last Review**：2026-09-02 21:24 +08:00（CR-3.6 最终复审：**VERIFIED / CLOSED / FREEZE——CR-3 全链关闭**（CR-3 / CR-3.1 / CR-3.2 / CR-3.3 / CR-3.4 / CR-3.5 / CR-3.6 全部 VERIFIED / CLOSED / FREEZE，28 项 mandatory 全 PASS，Exit Gate 21 项全过；ADR-023 → ACCEPTED；CR-4 SnapshotBuilder + DuckDB ReadModel 正式 START）；Reviewer closure commit `ff3808b7a5036246ea11e37173aa31d863beb2d9`；CR-4 首批 PENDING_REVIEW）  
> **Last Reviewer**：Design / Audit Review  
> **CI Status**：**FULL MATRIX GREEN——run 33715493176（CR-4 首批 final `0c328c3`）三腿 success**（2026-09-03 API positive confirmation：Windows 3.14 + Windows 3.12 + Ubuntu 3.14 各腿 Ruff lint / Ruff format / Mypy / Pytest（1235/0）/ Spike gates / SDK-absent / DEVLOG gate / Management-doc gate 全 success）；CR-4 首批 implementation `2db6d8d` 首跑 run `33707982975` 暴露 2 处**仅测试断言**的跨环境脆弱性（superset winner 跨 ingest 环境合法漂移 / spike evidence 未排序 glob 的平台序差异——NTFS 字典序 vs ext4 目录序命中 `.meta.json`），两个 assertion-only fix（`397ea7c`、`0c328c3`）后三腿全绿——**2 次修复轮次，零产品代码改动**；CR-3.6 implementation run `33623939024`（`1ebe96b`）三腿 success（2026-09-02 API positive confirmation：Windows 3.14 + Windows 3.12 + Ubuntu 3.14 各腿 Ruff lint / Ruff format / Mypy / Pytest（1179/0）/ Spike gates / SDK-absent / DEVLOG gate / Management-doc gate 全 success；一次通过零修复轮次）；CR-3.5 implementation run `33601822767`（`4898229`）三腿 success（2026-09-02 API positive confirmation；1151/0；一次通过零修复轮次）；CR-3.4 implementation run `33591527697`（`fce2ca4`）三腿 success（2026-09-02 API positive confirmation；1136/0；一次通过零修复轮次）；CR-3.3 implementation run `33581493160`（`f8b80b3`）三腿 success（2026-09-02 API positive confirmation；1116/0；一次通过零修复轮次）；CR-3.2 implementation run `33521594830`（`df409ed`）三腿 success（2026-09-01 API positive confirmation；1096/0；一次通过零修复轮次）；CR-3.1 implementation run `33508307611`（`75744aa`）三腿 success（1066/0）；CR-3 implementation run `33498314119`（`ae5b76c`）三腿 success（1025/0）；CR-2.4 implementation run `33482144065`（`3bc5c53`）三腿 success（985/0）；CR-2.3 implementation run `33472357951`（`480dc75`）三腿 success（975/0）；CR-2.2 implementation run `33460094366`（`a06ea22`）三腿 success（955/0）；CR-2.1 implementation run `33398654940`（`2bd0c31`）三腿 success（938/0）；CR-2 implementation run `33378006770`（canonical SHA `15cdae25fd7d11e3be0da3683e821629e4226291`）三腿 success（907/0）；R4-B2.3 run `33365674254`（`7362dfc`+`85a9260`，Reviewer closure 基线）三腿 success  
> **Phase Status（2026-09-03，CR-4 首批交付同步）**：  
> R4-A2.x / CR-1.x → **CLOSED / VERIFIED / FREEZE（不重开）**；R4-A3 / A3.1 / A3.2 → **CLOSED / VERIFIED / FREEZE（不重开）**；R4-B1 / B1.1 / B1.2 → **CLOSED / VERIFIED / FREEZE（不重开）**；R4-B2 / B2.1 / B2.2 / B2.3 → **CLOSED / VERIFIED / FREEZE（不重开；ADR-021 ACCEPTED）**；CR-2 / CR-2.1 / CR-2.2 / CR-2.3 / CR-2.4 → **VERIFIED / CLOSED / FREEZE（不重开；ADR-022 ACCEPTED）**；CR-3 / CR-3.1 / CR-3.2 / CR-3.3 / CR-3.4 / CR-3.5 / CR-3.6 → **VERIFIED / CLOSED / FREEZE（不重开；ADR-023 ACCEPTED——2026-09-02 21:24 复审裁决）**；CR-4 → **IN_PROGRESS（首批 DONE / PENDING_REVIEW：CR-4.1 canonical 公共消费验证器 + CR-4.2 SnapshotBuilder（migration 022）+ CR-4.3 DuckDB ReadModel；ADR-024 PROPOSED；含 CR-3 latent 缺陷（multi-domain semantic seal）显式申报修复——提请复审一并裁决）**；Production P0-M-1B → BLOCKED independently（production_account.yaml 仍为空 + 人工 Golden/Rule Review + 正式账号条件）  
> **SHA Correction（2026-08-31 17:42，Reviewer CR-2 复审 P1-01）**：CR-2 批次头部与 Implementation Mapping 曾记录 implementation SHA `15cdae2e4f1a9df3b7844480979a2f1cb2b2f464`——该 SHA 非真实 implementation commit；以 GitHub commit object 为准：`15cdae25fd7d11e3be0da3683e821629e4226291`（run 33378006770 关联 commit）。历史条目原文保留，CR-2 工作要求文档已追加 §12 更正。  
> **Governance Count Correction（Reviewer，2026-08-30）**：ADR-020 Amendment C.3 所写"SDK_METHOD_CLASSIFICATIONS 表（19 条）"经 Reviewer 逐项计数实为 **18 条**（治理文档数字错误，非 runtime 缺项——结构守卫 exact-set 本身通过）；已随 R4-B1.2 amendment D.3 更正，历史保留。**Count Correction（2026-08-31，CR-2 复审 P1-02）**：ADR-022 §2.2 曾写"9 SUPPORTED / 5 BLOCKED_PENDING_MAPPER"——该批实际 10/4，且 14 条未覆盖 index_daily 等 capability surface；CR-2.1 后 registry 为 **18 条（11 SUPPORTED / 4 BLOCKED_PENDING_MAPPER / 3 NOT_APPLICABLE，runtime exact-set 统计）**，已随 ADR-022 Amendment A §6.1 更正，历史保留。  
> **SHA Correction（2026-08-27，P1 治理）**：上批头部记录的 R4-A3 implementation SHA `de9bf1ab6c5a75e4d57b8b84e5b16b20ed1ba2fe` 有误，以 GitHub commit object 为准：`de9bf1ab6f499b20916f8277dba45c21880fd908`（与 run 55 关联 commit）；同批 SHA 记录 commit = `b5284bdc83631454c1d46add9e3478f86d81386e`。历史条目原文保留。  
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
| R4-A3 / R4-A3.1 / R4-A3.2 SDK Lifecycle / Gates / Early-Stop 链 | DONE | **CLOSED / VERIFIED / FREEZE** | 全链闭环（Reviewer 2026-08-28 裁决，不重开） |
| R4-B1 / B1.1 / B1.2 Capability Endpoint Proof 链 | DONE | **CLOSED / VERIFIED / FREEZE** | 全链闭环（Reviewer 2026-08-30 裁决，不重开） |
| R4-B2 / B2.1 / B2.2 / B2.3 Publish Validation Exactness 链 | DONE | **CLOSED / VERIFIED / FREEZE** | 全链闭环（Reviewer 2026-08-31 裁决；ADR-021 ACCEPTED） |
| CR-2 Provider-Normalized + Quarantine | DONE | **VERIFIED / CLOSED / FREEZE** | 2026-09-01 17:06 最终复审；ADR-022 ACCEPTED |
| CR-2.1 Surface Identity + Registry Boundary + Replay + Commit Closure | DONE | **VERIFIED / absorbed / FREEZE** | 同上（并入 CR-2 closure） |
| CR-2.2 Replay Provenance Seal | DONE | **VERIFIED / absorbed / FREEZE** | 同上 |
| CR-2.3 Raw Trust Anchor + Operation Spec + Output Seal | DONE | **VERIFIED / absorbed / FREEZE** | 同上 |
| CR-2.4 Anchored Raw Ingestion Boundary | DONE | **VERIFIED / CLOSED / FREEZE** | 同上 |
| CR-3 AvailabilityPolicy + Canonicalizer | DONE | **REOPENED** | 主体架构 PASS / FREEZE（2026-09-01 19:06 复审）；8 P0 由 CR-3.1 收口 |
| CR-3.1 Canonical Input Snapshot + Replay Seal | DONE | **REOPENED（已吸收）** | 19 项机制 PASS / FREEZE（2026-09-01 21:08 复审）；5 P0 由 CR-3.2 收口 |
| CR-3.2 Transactional Snapshot + Full Seal | DONE | **REOPENED（已吸收）** | 16 项机制 PASS / FREEZE（2026-09-02 06:56 复审）；2 P0 + 3 P1 由 CR-3.3 收口 |
| CR-3.3 Historical Input Continuity + Verification Evidence | DONE | **REOPENED（已吸收）** | 18 项机制 PASS / FREEZE（2026-09-02 10:22 复审）；3 P0 由 CR-3.4 收口 |
| CR-3.4 Historical Canonical Seal Trust + Verification Replay Symmetry + Manifest Identity Binding | DONE | **REOPENED（已吸收，原定 3 P0 PASS/FREEZE）** | 14 项机制 PASS / FREEZE（2026-09-02 13:17 复审）；2 新 P0 由 CR-3.5 收口 |
| CR-3.5 Historical Candidate Discovery + Derived Run/Status Seal | DONE | **REOPENED** | derived run/status seal PASS / FREEZE——21 项机制（2026-09-02 17:36 复审）；2 新 P0 由 CR-3.6 收口 |
| CR-3.6 Selection-Free Historical Discovery + Historical Artifact Closure | DONE | **VERIFIED / CLOSED / FREEZE** | 2026-09-02 21:24 复审最终裁决（28 mandatory 全 PASS）；CR-3 全链关闭 |
| CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild | IN_PROGRESS | **CR-4.4 ACTIVE / PENDING_REVIEW** | **当前最高优先级**（CR-4.1/4.2/4.3 首批已实现；CR-4.4 收口确定性回放、可恢复 immutable、key binding、physical schema hash、ReadModel verified-open；ADR-024 Amendment A PROPOSED） |
| R4-CI | PLANNED | PENDING | Next |
| CR-3 Availability + Canonicalizer | PLANNED | PENDING | CR-2 后 |
| CR-4 Snapshot + Read Model Rebuild | PLANNED | PENDING | CR-3 后 |
| Mock 20×60d Vertical Slice | BLOCKED | PENDING | CR-2..4 后 |
| Production P0-M-1B | BLOCKED | PENDING | 正式账号 + R4 + Golden 人工 Review |
| Real P0a | BLOCKED | PENDING | Provider + Canonical Runtime |
| Trend BASE | BLOCKED | PENDING | Real Vertical Slice 后 |

---

# 41. 当前最高优先级

## CR-4 SnapshotBuilder + DuckDB ReadModel（IN_PROGRESS——CR-4.4 ACTIVE / PENDING_REVIEW）

CR-3 全链 VERIFIED / CLOSED / FREEZE（2026-09-02 21:24 复审裁决，ADR-023 ACCEPTED）后正式启动。
首批（DM-20260903-075，工作要求
`docs/design/A-share-analysis_CR-4_SnapshotBuilder及DuckDBReadModel开发工作要求_20260902.md`
+ `A-share-analysis_CR-3.6最终复审结论与CR-4启动裁决_20260902.md`）：

CR-4.4（2026-09-03 复审 reopen）当前只处理以下 correctness closure：SnapshotBuilder 与
`verify_snapshot` 共用确定性 canonical projection replay；immutable artifact 采用 identical
no-op / missing-write / different-byte conflict 并在写入前整体 preflight；registry 加入显式
KeyBinding 与 stable sort；Canonical/Snapshot verifier 使用已校验的同一 Parquet bytes，Snapshot
schema_hash 从 physical schema 重算；ReadModel 增加双 fingerprint、canonical_as_of/full
domain_meta seal，并在 `open_read_only` 返回句柄前完成 verified-open。migration 022 不改；
CR-5、Feature/State、provider/fallback/production 仍不在范围内。

```text
CR-4.1 Canonical 公共消费验证器（canonical/verifier.py）：
  verify_canonical_run_for_consumption = 下游读取 canonical truth 的唯一支持入口；
  内部复用 CR-3 唯一实现（identity seal / artifact closure / findings truth /
  sealed-input 权威+物理验证——_sealed_input_authority_problems 共享提取）；
  BLOCKED 显式拒绝；不要求 current discovery presence（合法 superset 不追溯
  破坏已 mint SUCCESS 的消费）
CR-4.2 SnapshotBuilder（snapshot/ 包）：
  版本化 schema registry（列集/dtype/nullability/key arity/key projection
  单一事实源；market=payload、factor_type=key projection）；确定性 identity
  （canonical run-level seals + contract + builder code fingerprint ->
  UUID5）；immutable artifacts（artifact 集==请求 domain 集、manifest LAST、
  _write_immutable 拒绝覆盖）；migration 022 meta_snapshot_build（dup-check
  事务 / exact retry 幂等 replay / crash 残留 fail closed）；verify_snapshot
  （deterministic URI + identity UUID5 cross-bind + canonical provenance
  cross-bind 重跑消费验证器 + artifact 物理/语义 seal 重算）
CR-4.3 DuckDB ReadModel（readmodel/ 包）：
  rebuild = verify_snapshot -> temp 库 -> registry 精确类型建表 +
  read_parquet(hive_partitioning=false) -> temp 上 logical seal（表集/行数/
  key 唯一/表内容重算 semantic hash（TIMESTAMPTZ 归一化 UTC）/schema 精确/
  meta 表）-> Path.replace 原子替换；失败 temp 删除旧目标字节不变
边界（AST guard）：snapshot/readmodel 禁 import providers/normalization/
  raw_writer；禁 pandas/talib/numpy/scipy/sklearn
CR-3 latent 缺陷显式申报（提请复审一并裁决，未悄悄修复）：
  CR-3 selected/decision semantic seal 曾对未对齐 rows 计算而 parquet 写
  对齐后 rows——多 domain exact replay 必误报 DAMAGED（单 domain 无差异故
  六轮复审未暴露）；最小修复=seal 对 aligned rows 计算（单 domain 行为逐
  字节不变）+ TestMultiDomainReplayRegression 回归钉
Adversarial Tests（+56：总体 1235/0；mandatory 1-50 全对应）
```

### CR-3.6 Selection-Free Historical Discovery + Historical Canonical Artifact Closure（前批，VERIFIED / CLOSED / FREEZE）

2026-09-02 17:36 复审 REOPENED 后收口；2026-09-02 21:24 最终复审 **VERIFIED /
CLOSED / FREEZE（不重开）**——CR-3 全链关闭。历史细节见 §61 DM-20260902-074
与 ADR-023 Amendment F。

### CR-3.5 Historical Candidate Discovery + Derived Canonical Run/Status Seal（前批，VERIFIED / 已吸收）

CR-3.4 复审（2026-09-02 13:17 +08:00）REOPENED 后收口；2026-09-02 17:36
CR-3.5 复审：**REOPENED**（Derived Run / Status Seal 全部 PASS / FREEZE——
21 项机制；2 新 P0 由 CR-3.6 收口，见上）。历史细节见 §61 DM-20260902-073
与 ADR-023 Amendment E（其中"primitive request-world fields 查询"的候选
选择已被 Amendment F §11.1 修订——primitive 字段的 integrity 只在 verifier
内部才被确认，任何 correctness field 都不得作为进入 verifier 前的排他条件）：

```text
P0-01 Tamper-Resistant Historical Candidate Discovery：
  旧缺陷：continuity 候选 SQL = WHERE canonical_context_hash = ? AND
    status != 'BLOCKED'——derived 字段预过滤；ledger status 改 'BLOCKED'
    （路径 A）或 canonical_context_hash 漂移假值（路径 B）都让 prior
    SUCCESS 在进入 seal verifier 前被隐藏
  收口：候选发现按 primitive request-world fields（requested_domains_hash
    + as_of（Python 侧精确比较）+ contract + 三 policy version/hash +
    code_fingerprint），不用 status 预过滤、不把 stored context 当
    selection key；每个候选先过 full historical seal（§9.1 全部 + derived
    identity 物理重算 + findings truth→status 语义重算），之后才解释已
    验证的 world/status（SUCCESS 同世界 -> continuity 依赖；genuine
    BLOCKED -> 非依赖不阻塞 recovery；旧 bridge policy 世界 -> 跳过）
  路径 A 由 findings→status 语义重算拦截；路径 B / ledger+manifest 同步
    rebind 由 primitive 物理重算拦截
P0-02 Derived Canonical Run Seal 物理闭环：
  旧缺陷：derived 字段（context/master set/dataset hash/base/idempotency/
    run id/status）只验 ledger == manifest + 三 input hash 重算——
    ledger+manifest 同步 rebind 无法检测（status 可被洗成 genuine
    BLOCKED 或反向洗成 SUCCESS）
  收口：模块级单一派生公式集（live build / replay / historical
    continuity 三方共用）：_requested_domains_hash_from_list /
    _input_hashes_from_entries / _master_input_set_hash_from_entries /
    identity_dataset_hash_with_bridge（identity.py 参数化——用该 run
    自己的 manifest bridge identity 重算，公式唯一）/
    _canonical_context_hash_from_primitives / _base_identity_hash_
    from_primitives / _idempotency_key_from_hashes /
    _canonical_run_id_from_idempotency（UUID5 cross-bind）/
    _status_error_from_findings
  _derived_run_identity_problems() 全部重算与 ledger 逐字段比对，消费于
    _verify_historical_canonical_seal + _verify_closure（三方闭环）；
    snapshot 属性 / _build_snapshot / run() 状态派生全部委托同一
    helpers（最小必要抽取，公式逐字节不变）
status semantic seal：_verify_findings_truth（replay + historical 共用）
  ——findings 三方（DB == parquet == seal）后从 blocking truth 重算
  status 与 error text 并消费 ledger/manifest 字段；error_message 升级
  为 derived audit text（P1 收口）
无新 migration（bridge identity 已由 manifest 持久化且参与物理重算；
  migration 链保持 21）
Adversarial Tests（+15：canonical 166 = 151 回归 + 15 新增；总体 1151/0）：
  audit §1.4/§2.3 mandatory 15 项全对应 + run-id cross-bind positive
```

### CR-3.4 Historical Canonical Seal Trust + Verification Replay Symmetry + Manifest Correctness Identity Binding（前批，DONE / REOPENED）

CR-3.3 复审（2026-09-02 10:22 +08:00）REOPENED 后收口；2026-09-02 13:17
CR-3.4 复审：**REOPENED**（原定 3 P0 PASS / FREEZE——14 项机制；2 新 P0 由
CR-3.5 收口，见上）。历史细节见 §61 DM-20260902-072 与 ADR-023 Amendment D
（其中"continuity 完整验证"的表述已被 Amendment E §10.1 修订——CR-3.4 只
强化了"已被选中的 prior run 怎么验"，候选选择本身仍依赖 derived 字段）：

```text
P0-01 Historical Canonical Run Seal Trust：
  旧缺陷：continuity guard 信任 prior manifest.input_normalized_runs 前只验
    manifest 存在 + 外层 bytes hash == ledger.manifest_hash——rebind（改
    input list 去 A + rehash + 只更新 ledger.manifest_hash + DELETE CR-2
    A）可把已消费输入"洗出"continuity evidence
  收口：typed CanonicalRunSeal（from_ledger）+ _verify_historical_
    canonical_seal() 在信任历史 input list 前完整验证：
    1. deterministic manifest URI + manifest bytes == ledger.manifest_hash
    2. manifest 显式 correctness 字段（canonical_run_id / contract /
       as_of / idempotency_key / status / requested domains json+hash /
       input_set_hash / input_seal_hash / identity_dataset_hash /
       identity_master_input_set_hash / canonical_context_hash /
       base_identity_hash / verification_state_hash / 三 policy
       version+hash / code_fingerprint）== ledger seal
    3. 物理重算 _input_hashes_from_entries()（与 CanonicalInputSnapshot
       同公式）：input_seal_hash（全 seal entries）/ input_set_hash
       （identity subset——_INPUT_IDENTITY_FIELDS 模块级单一事实源，
       identity_dict 同源）/ verification_state_hash（run_id +
       verification + verification_problem_hash）必须 == ledger
  prior manifest/ledger 自身 DAMAGED -> HARD DAMAGED：不用该 input list
    做 continuity 判断，零 replacement
P0-02 Verification Evidence Replay Symmetry：
  旧缺陷：replay 对 INVALID sealed input 硬编码 materialization_problems
    =[]——但 first consume 允许 closure+anchor 健康后在 _materialize_
    outputs 才失败（TOCTOU path），first-run seal 可含非空 materialization
    evidence，replay 无法对称重建 exact evidence hash
  收口：first consume 与 replay 共用同一 collector _collect_input_
    verification_evidence(run identity, role, as_of, keep_rows)：
    closure problems -> anchored-evidence problems ->（closure+anchor
    健康时）exact-byte materialization verify -> derived verification
    enum -> canonical problem evidence -> problem hash
  first-run（keep_rows=True）额外保留物化行；replay（keep_rows=False）
    丢弃行但运行同一验证序列/语义
  exact physical failure repeat -> idempotent replay 同一 BLOCKED run；
    cause 变化 -> 新 exact evidence identity；exact repair -> recovery
    run（历史 BLOCKED 保留）
P0-03 Manifest Correctness Identity 全消费：
  canonical_context_hash / base_identity_hash / verification_state_hash
    进入 _verify_closure 的 typed manifest binding（manifest == ledger ==
    current recompute 三方闭环）；continuity 历史 seal 同样消费
无新 migration（复审 §4 优先不新增 schema；三收口全部为 canonicalizer
  runtime 侧；migration 链保持 21）
新公开类型：CanonicalRunSeal / InputVerificationEvidence
Adversarial Tests（+20：canonical 151 = 131 回归 + 20 新增；总体 1136/0）：
  audit §1.3/§2.3/§3 mandatory 13 项全对应 + positive controls
```

### CR-3.3 Historical Input Continuity + Verification Evidence Exactness + Finding Truthfulness（前批，DONE / REOPENED）

CR-3.2 复审（2026-09-02 06:56 +08:00）REOPENED 后收口；2026-09-02 10:22
CR-3.3 复审：**REOPENED**（18 项机制 PASS / FREEZE；3 P0 由 CR-3.4 收口，
见上）。历史细节见 §61 DM-20260902-071 与 ADR-023 Amendment C（其中
replay 分支 materialization_problems 恒空的表述已被 Amendment D §9.2
修订）：

```text
P0-01 Historical Input Continuity Guard（migration 021
  canonical_context_hash）：
  context = requested domain set + as_of + contract + 三 policy
    identities + identity bridge policy identity + canonical code
    fingerprint（刻意不含 current CR-2 input set / verification state）
  guard：查同 context 全部历史非 BLOCKED run，对每个 prior 的 sealed
    input set 逐 run 检查：
    1. run_id 仍在当前 authoritative CR-2 ledger（disappearance ->
       DAMAGED）
    2. ledger identity（status + 全部 seal 字段）== prior sealed
       identity（drift -> DAMAGED）
    3. physical + anchored verification 仍健康（degradation -> DAMAGED）
    4. 健康的 prior input 必在 current snapshot discovery（同 context
       => 同 surface plan；缺失即不可解释 drift）
  合法新增：全部 prior inputs 完整 + current set 是 superset -> 正常
    新 run；exact restoration -> 历史 SUCCESS exact replay
P0-02 Verification Evidence Exactness：
  InputRunSeal 新增 verification_problem_hash（canonical sorted
    problem evidence：run_id + verification class + closure problems +
    anchored-evidence problems + materialization problems）
  base identity 不含 problem hash（identity_dict 排除）；verification
    state / manifest input seal / input_seal_hash 均含
  同一 INVALID class + 不同 cause -> 新 state -> 新 BLOCKED evidence
    run（prior BLOCKED 保留 append-only；finding detail 反映真实当前
    cause）；exact same failure -> idempotent replay；INVALID ->
    HEALTHY -> recovery run
  replay sealed-input 验证分流：HEALTHY sealed input 要求仍健康；
    INVALID sealed input 要求当前 problem evidence == sealed problem
    hash（exact failure 才 replay）
P1-01 finding scope 真实：source-scope findings 用 reserved scope
  input:<normalization_surface>（绝不用 "source"），detail seal
  affected_domains exact set（shared surface 如 security_status_history
  同时封 security_status + limit_price）
P1-02 finding precedence：no discovered -> MISSING；discovered but
  damaged -> 仅 closure/evidence finding（不误报 UNAVAILABLE——损坏不是
  不可用）；healthy but all future -> UNAVAILABLE（真语义保留）
P1-03 治理计数更正：CR-3.2 说明 "19 fields" 实际 20；CR-3.3 后 21
  （+verification_problem_hash；identity_dict 17 字段）；测试机械断言
  exact set，不再手写
Migration 021：canonical_context_hash 列（未改 018/019/020；21 链
  from-zero + 020->021 upgrade + idempotent + tamper probe 022）
Adversarial Tests（+20：canonical 131 = 111 回归 + 20 新增；总体
  1116/0）：audit §1.4/§2.3 mandatory 15 项 + P1 三项全对应
```

### CR-3.2 Transactional Snapshot + Identity Master PIT + Honest Policy Execution + Full Seal + Verification-State Transition（前批，DONE / REOPENED）

CR-3.1 复审（2026-09-01 21:08 +08:00）REOPENED 后收口；2026-09-02 06:56
CR-3.2 复审：**REOPENED**（16 项机制 PASS / FREEZE；2 P0 + 3 P1 由
CR-3.3 收口，见上）。历史细节见 §61 DM-20260901-070 与 ADR-023
Amendment B（其中 degraded-SUCCESS guard 以 base identity 查询、
verification state 只封枚举两处表述已被 Amendment C §8.1-§8.2 修订）：

```text
P0-01 Transactional Materialized Snapshot：
  BEGIN TRANSACTION（MVCC boundary——第一个 authoritative broad SELECT
    之前）-> surface 去重发现（P1-02：同一 surface 一次查询 union
    datasets）-> 逐 run closure+anchor verify -> 物化 exact sealed bytes
    （读 bytes -> hash==manifest -> parse 同一份 -> 深冻结行）-> COMMIT
  candidate builder 只消费 materialized rows——绝不重查当前 ledger path /
    重读当前文件（snapshot 后 UPDATE/替换只影响下次 invocation/replay）
  深不可变（P1-01）：InputRunSeal / SnapshotRun / MaterializedOutput /
    CanonicalFinding frozen dataclasses + tuple-frozen rows
  race 测试：第二 connection 在 broad reads 之间真实 commit（file-backed
    DuckDB MVCC）——非"snapshot 返回后再插入"
P0-02 Identity Master PIT：
  security_master 与 market source 同规则：anchor-verified
    received_at <= as_of 才进 IdentityBridge；future master 是 discovery
    evidence（input seal pit_available=false）绝不解析历史 rows
  typed findings：IDENTITY_DATASET_MISSING / UNAVAILABLE_AT_ASOF /
    IDENTITY_EVIDENCE_INVALID；first-run/replay 对称（都验 master
    anchor）；relist 保持 early truth
P0-03 Honest Policy Execution：
  explicit supported-value guard：required_evidence_class /
    reconciliation / tolerance id+version / conflict_action / fallback /
    partial 全部只允许 v1 实现值——声明不支持值 fail closed（run 之前）
P0-04 Full Seal 全消费：
  input entry 升级 typed full CR-2 seal（InputRunSeal：contract version /
    mapper identity+code hash / manifest uri+hash / output_set+semantic
    hash / status / raw identity / verification / received_at /
    pit_available）；input_seal_hash 三方（snapshot==manifest==ledger）
  manifest 显式 provenance 全消费：identity_master_input_set_hash /
    bridge policy version+hash / required_evidence_classes（==current）
  manifest_uri 本身 deterministic verify（expected base + /manifest.json）
  replay sealed-input 验证 seal-based（用 seal 字段直接验 files——不依赖
    current DB row）
P0-05 Verification-State Transition：
  run identity = base identity（input world，不含 state）+
    verification_state_hash（每 discovered run 的 verification outcome）
  migration 020 四列（base_identity_hash / verification_state_hash /
    input_seal_hash / identity_master_input_set_hash）
  state 相同 -> exact replay；BLOCKED(可恢复)+修复 -> 新 deterministic
    run（绝不 replay stale BLOCKED；历史证据保留）；SUCCESS+退化 ->
    DAMAGED 拒绝（不 mint replacement；exact repair 后恢复历史 replay）
  input_set_hash 只含 identity 字段（state 字段进 state hash / manifest
    evidence，绝不进 base identity）
P1：深不可变 snapshot；shared surface discovery 去重；domains=[] 显式
  reject（None = all supported）
Migration 020：四列（未改 018/019；20 链 from-zero + 019->020 upgrade +
  idempotent + tamper probe 021）
Adversarial Tests（+30：canonical 111 = 81 回归 + 30 新增；总体 1096/0）：
  audit §7 矩阵 32 项全对应（01-06 race/materialize/immutability /
  07-12 master PIT / 13-17 policy guard / 18-23 full seal rebind /
  24-27 state transition / 28-32 migration+CI+regression）
```

### CR-3.1 Canonical Input Snapshot + Anchored Availability Evidence + Full Replay Seal + Recoverable Commit（前批，DONE / REOPENED）

CR-3 复审（2026-09-01 19:06 +08:00）REOPENED 后收口；2026-09-01 21:08
CR-3.1 复审：**REOPENED**（19 项机制 PASS / FREEZE，5 P0 由 CR-3.2 收口，
见上）。历史细节见 §61 DM-20260901-069 与 ADR-023 Amendment A（其中
snapshot 构造方式 / master 验证 / policy 消费 / manifest 字段消费 / run
identity 五处表述已被 Amendment B §7.1-§7.5 修订）：

```text
P0-01 RequestedDomainSet 进 run identity：
  请求域去重排序 exact set；canonical JSON hash 进 identity；migration 019
  ledger 列 requested_domains_json/hash + manifest 显式绑定；replay 返回
  domains 来自 ledger seal；不同 set 必不同 run / 同 set 不同顺序同 run
P0-02 Availability completeness：
  无 eligible verified run -> REQUIRED_DOMAIN_MISSING；有 eligible run 但零
  PIT-available 候选 -> REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF（均 blocking；
  "合法空集"仅 policy 显式声明，v1 无）；future-only 永不 false SUCCESS
P0-03 CanonicalInputSnapshot（一次 authoritative 解析）：
  typed immutable dataclass：requested set + discovered CR-2 source/master
  run exact set（含验证失败 run——blocking prefinding 诚实记录）+ policy
  identities + code fingerprint；run identity / candidates / manifest /
  ledger 全部从 snapshot 派生，不再重复 broad query；mid-run 插入只能被
  下一次 invocation 看到（新 identity）
P0-04 AnchoredAvailabilityEvidence：
  读 received_at 前证明 current raw meta exact-byte SHA-256 ==
  normalization run sealed raw_evidence_hash == anchor.evidence_hash +
  cross-bind provider/dataset/request/uri/endpoint/surface/operation_id
  （anchor==run==meta 三方）；失败 -> AVAILABILITY_EVIDENCE_INVALID
  blocking；replay 对每个 sealed source run 重新执行
P0-05 Identity binding 统一：
  identity_dataset_hash = hash(master_input_set_hash, bridge_policy_version,
  bridge_policy_hash) 进 identity/manifest/ledger 三处同值；bridge policy
  变更 -> 新 run；replay 比对三方
P0-06 Policy hash 全字段：
  source_policy_hash = asdict + sorted canonical JSON 全语义字段（fallback/
  identity_missing_max/required_evidence_class/tolerance_version 均覆盖）；
  runtime 诚实消费（声明 fallback/partial 无支持 -> 显式 raise；
  identity_missing_max per-domain 计数 vs 阈值；required_evidence_classes
  进 manifest）
P0-07 Full replay seal：
  CURRENT snapshot identities == ledger == manifest == replay-time physical
  recompute（selected_semantic_hash / decision_set_hash / finding_set_hash /
  artifact exact set / deterministic URI / schema recompute / row_count /
  findings parquet<->DB exact-set cross-bind）+ re-verify 每个 sealed CR-2
  source run closure + anchored evidence；migration 019 两 semantic seal 列
P0-08 Recoverable commit：
  findings.parquet 无 wall-clock（finding id = uuid5；created_at 仅 DB
  transaction-time audit metadata，排除出 semantic hash）；DB 失败 ->
  exact retry 文件 byte-identical no-op -> ledger 补提交
P1：identity finding 真实 domain（per-domain 计数）；domain matrix 计数
  更正 12 -> 13（5/2/6，runtime exact-set 统计）；naive datetime 拒绝 +
  naive string 固定 UTC 规则（跨平台 deterministic）
Migration 019：requested_domains_json/hash + selected_semantic_hash +
  decision_set_hash 四列（未改 018；19 链 from-zero + 018->019 upgrade +
  idempotent + tamper probe 020）
Adversarial Tests（+41：canonical 81 = 40 回归 + 41 新增；总体 1066/0）：
  audit §10 矩阵 34 项全对应（snapshot race 经 _build_snapshot
  monkeypatch 注入——production 无 hook）
```

### CR-3 AvailabilityPolicy + Canonicalizer（前批，DONE / REOPENED）

CR-2.4 最终复审（2026-09-01 17:06 +08:00）VERIFIED 后交付；2026-09-01
19:06 CR-3 复审：**REOPENED**（主体架构 PASS / FREEZE，18 项冻结清单；
8 P0 由 CR-3.1 收口，见上）。历史细节见 §61 DM-20260901-068 与
ADR-023 §2（其中 requested-domain-identity / input-set 口径 / received_at
读取 / identity hash 口径 / policy hash 覆盖 / replay seal 消费 / findings
determinism 七处表述已被 Amendment A §6.1-§6.8 修订）：

```text
P0-01/02 唯一输入 + eligibility 机器定义：
  CanonicalRunner.run(as_of, domains=...)——唯一正式 canonical 边界
  输入 = CR-2 verified Provider-Normalized（SUCCESS only；PARTIAL 默认
    NOT eligible——v1 全部 domain partial_run_allowed=False；BLOCKED
    NEVER）
  消费前逐 run 调 verify_normalized_run（normalization/runner.py 公开
    只读 closure verifier：manifest bytes / output content+schema+
    row_count / quarantine exact set / typed seal vs current provenance）
    ——任何 problem -> CLOSURE_VERIFICATION_FAILED blocking finding
P0-03/04 AvailabilityPolicy 机器先行：
  candidate -> derive available_at -> filter <= as_of -> ONLY THEN
    selection（顺序机器强制，EXCLUDED_FUTURE decision 留证）
  available_at 唯一 basis = OBSERVED_AT_INGEST（raw envelope
    received_at，晚于真实 publish -> PIT 保守）；SOURCE_PUBLISHED_AT/
    DOMAIN_RULE_DERIVED 未注册（无已验证 publish ts / 无版本化 Trading
    Rule 事实）；NOT_VERIFIABLE 永不进入 PIT truth
  typed basis 四分类 + policy 版本 availability-v1 + hash 进 run identity
P0-05/06 Identity fail closed + typed natural keys：
  IdentityBridge：CR-2 verified security_master runs（三 dataset 全集）
    -> ADR-002 resolve_security_identity（EXCHANGE:STOCK:SYMBOL:F<date>）
  exchange 归属只来自 provider market 后缀；裸码唯一市场匹配（三变体
    恰一存在；两存在 = ambiguous fail closed——绝不前缀猜）
  PIT relist：list_date <= trade_date 最新；missing/ambiguous ->
    IDENTITY_MISSING blocking finding（identity_missing_max=0）+ 行排除
    ——裸 symbol 绝不作为 canonical key fallback
  natural keys 静态 typed（calendar: market+trade_date；bars/status/
    limit: security_id+trade_date；adj_factor: security_id+ex_date+
    factor_type）
  Domain eligibility matrix 12 项全显式：5 CANONICAL_SUPPORTED /
    2 AUXILIARY_ONLY（security_master=identity dataset；ca_projection=
    STATUS_FLAG_PROJECTION tier——direct CA mapper BLOCKED 期间绝不伪造
    direct truth）/ 5 BLOCKED_PENDING_SEMANTICS（index_daily 无已验证
    市场归属等）；非 SUPPORTED domain 调用即 raise（无 silent skip /
    无绕过 CR-2 直读 Raw）
P0-07..09 SourcePolicy 版本化静态 + No Silent Fallback：
  CanonicalSourcePolicy registry（source-policy-v1）：priority /
    fallback 空 / partial False / SINGLE_SOURCE_EXACT / exact-v1 /
    conflict BLOCK；caller 零注入面（签名结构测试）
  不可用首选 -> REQUIRED_DOMAIN_MISSING blocking（无静默 fallback）
  同 key 多候选 EXACT 比较：等值 -> EQUIVALENT_MERGED decision +
    deterministic winner（(priority, manifest hash, ordinal)——iteration
    order 永不影响）；不等值 -> SOURCE_CONFLICT blocking；同 output
    重复 key -> DUPLICATE_CANONICAL_KEY blocking（绝不 silent dedupe /
    last-write-wins）
P0-10 精确 lineage：canonical row 绑定 12+ 字段（run_id/output_name/
  row ordinal + row identity hash/raw request/evidence hash/mapper
  identity/policy versions/availability basis...）
P0-12 无硬编码制度事实：AST guard 扫 canonical 包（无 ST=5%/科创板=20%/
  北交所=30%/规则变化日期字面量）
P0-13..15 Immutable artifacts + deterministic identity + 状态机：
  canonical/contract=<V>/as_of=<T>/run=<id>/ 下 selected/decisions/
  findings.parquet + manifest.json LAST（无墙钟；immutable 同 bytes
  no-op）；manifest 封 input run exact set + 三 policy identity +
  canonicalizer code fingerprint（五模块源码 SHA-256 行尾归一）+
  每 artifact seal + selected_semantic_hash + finding_set_hash
  run identity = uuid5(sha256(input_set + identity_hash + as_of +
    contract + 三 policy identity + fingerprint))——policy/代码/输入任一
    变化 -> 新 run（历史保留）；prior 同 identity 先三方 seal closure
    复验再 idempotent replay（篡改 -> fail closed）
  migration 018 ledger（meta_canonicalization_run +
    meta_canonical_reconciliation_finding）单事务 + finding 行数断言
  状态机 SUCCESS/BLOCKED（PARTIAL 仅 policy 允许——v1 无）
P1 guard 加固（CR-2.4 复审 §2，本批完成）：
  _scan_unanchored_writes 升级——RawWriter write 调用点经 alias 赋值
    （rw = RawWriter(...); rw.write(...)）与直接构造调用（RawWriter
    (...).write(...)）双形态跟踪；构造点白名单 = raw_writer.py /
    raw_anchor.py + normalization/runner.py（read-only verified
    reader，无 write 豁免）；negative fixtures + production 全树零违规
Adversarial Tests（36 项，tests/integration/test_canonical.py）：
  audit §8 矩阵 30 类全对应 + P1 guard 4 项；总体 1025/0
```

### CR-2.4 Anchored Raw Ingestion Boundary（前批，VERIFIED / CLOSED / FREEZE）

CR-2.3 复审（2026-09-01 14:26 +08:00）REOPENED 后 wiring 收口；2026-09-01
17:06 CR-2.4 最终复审：**VERIFIED / CLOSED / FREEZE**（CR-2 全链关闭；
ADR-022 ACCEPTED）。历史细节见 §61 DM-20260901-067 与 ADR-022 Amendment D
（工作要求
`docs/design/A-share-analysis_CR-2.3复审与CR-2.4最终AnchoredIngestionBoundary收口要求_20260901.md`）：

```text
AnchoredRawEvidenceWriter（audit §3.1）——唯一 production-owned 写入边界：
  write_exchange(exchange) -> RawWriteResult
    1. RawWriter.write(exchange)            # 文件侧 commit（meta 最后落盘）
    2. reread persisted meta bytes——VERIFY-ONLY：
       require sha256(reread) == RawWriteResult.evidence_hash
       （write->enroll 之间换字节（TOCTOU）-> 整体 HARD FAIL，H2 永不 enroll）
    3. identity cross-binding：meta 的 request_id/provider/provider_dataset/
       endpoint/normalization_surface/operation_id == exchange envelope
       （伪造 meta 身份 -> BLOCK）+ uri cross-binding
    4. enroll immutable anchor（keyed to COMMIT identity）
    5. return——ingest 至此才算完成（任何失败 = evidence 不 ready）
全部 production evidence 写入接线（audit §3.2）：
  ProbeContext 新增必需 conn 参数；raw_writer -> AnchoredRawEvidenceWriter
    （evidence_from_exchange / failure_evidence -> write_exchange——
    SUCCESS 与 ERROR exchange 均自动 anchor）
  run_dry_run 打开 in-memory migrated DB——框架自检走与 production
    完全相同的 anchored 写路径
  结构守卫（AST）：src/ 中 RawWriter write/write_success/write_failure
    调用点只允许 raw_writer.py（定义）与 raw_anchor.py（boundary 内部）；
    reader（RawWriter.read）不受限（normalization 只读消费）
Enrollment 可恢复但不可 rebaseline（audit §3.3）：
  anchor INSERT 注入失败 -> write_exchange 抛出 -> 本次 ingest 失败；
    raw bytes（H1）在盘无 anchor -> Normalization RAW_ANCHOR_MISSING
  exact retry 同一 exchange：RawWriter idempotent（same bytes ignoring
    ingested_at -> no-op -> evidence_hash = 首 commit 的 H1）-> enrollment
    成功 -> 一个 immutable anchor、单一 evidence identity
  已有 anchor H1：same H1 idempotent / H2 hard conflict；永不 rebaseline
API 收口（audit §3.4）：
  公开 record_raw_evidence_anchor（"看现场 bytes 建首次 anchor"）撤销；
    enrollment 私有化 _enroll_anchor——evidence_hash 为必填调用方声明
    commit identity，函数内 verify-only 比对磁盘（不自行定义真值）
  公开面：AnchoredRawEvidenceWriter / persist_exchange_with_anchor /
    lookup_raw_evidence_anchor / RawEvidenceAnchor / RawAnchorError
  tests 制造 legacy/unanchored 或 governed-reingest 夹具用私有
    primitive（tests-only，B2 static registry 同口径）
无 schema 变更（复用 migration 017 anchor 表）
Adversarial Tests（+10：normalization 114 = 104 回归 + 10 新增）：
  audit §4 17 项矩阵全对应（ProbeContext SUCCESS/ERROR anchor 2 /
  结构守卫 1 / TOCTOU 1 / enrollment 失败恢复 1 / same-H1 idempotent 1 /
  H2 hard conflict 1 / anchored->runner SUCCESS 1 / identity
  cross-binding 1 / API 收口 1 + 回归 8 项全保持）；总体 985/0
```

### CR-2.3 Raw Trust Anchor + Provider-Owned Operation Spec + Output Seal（前批，DONE / REOPENED）

CR-2.2 复审（2026-09-01 10:45 +08:00）REOPENED 后收口；2026-09-01 14:26
CR-2.3 复审：**REOPENED**（operation spec / anchor schema+runner
verification / output-set+semantic seal PASS / FREEZE；仅 enrollment
boundary 由 CR-2.4 收口，见上）。历史细节见 §61 DM-20260901-066 与
ADR-022 Amendment C（其中公开 recorder、测试 helper 手工 anchor 等表述
已被 Amendment D §9.4 修订）：

```text
P0-01 Provider-Owned Operation Spec（audit §2）：
  新 operations.py：ProviderOperationSpec（operation_id/capability/endpoint/
    provider_dataset/normalization_surface）私有 STATIC 常量 15 个——每个
    facade wrapper 绑定一个
  call_exchange / _call_or_exchange 撤销：generic executor 私有化为
    _execute_exchange(spec, fn, params)——endpoint/dataset/capability/
    surface/operation_id 全部由 spec 派生（普通 caller 无法组合
    daily fn + index capability；公开方法签名无任何 free-form
    correctness selector——结构测试断言）
  query_kline_exchange -> DAILY_BAR_KLINE / query_index_kline_exchange ->
    INDEX_DAILY_KLINE（AST 绑定断言）
  RawEnvelope / raw meta 新增 operation_id（anchor 交叉绑定）
  结构守卫：15 spec 与 SDK_METHOD_CLASSIFICATIONS + normalization
    registry 双向 exact 核对（3 NOT_APPLICABLE 无 spec）
P0-02 Raw Evidence Trust Anchor（audit §3）：
  migration 017 meta_raw_evidence_anchor（(provider, dataset,
    request_id) PK + evidence_uri/evidence_hash/endpoint/operation_id/
    normalization_surface/payload_kind/ingest_run_id/created_at）
  governed ingestion flow（raw_anchor.py::record_raw_evidence_anchor）：
    RawWriter commit meta LAST -> reread persisted bytes -> sha256 ->
    anchor（同 bytes 幂等；异 bytes RawAnchorError hard fail——anchor
    永不 re-baseline）
  NormalizationRunner 在任何 meta 解析/路由/映射之前查 anchor：
    缺失（legacy pre-017）-> RAW_ANCHOR_MISSING BLOCKED（fail closed；
    governed repair = re-ingest；绝不 auto-grandfather——015-era
    H1+H2 laundering history 升级后 H2 永不被信任）
    current hash != anchor -> RAW_ANCHOR_MISMATCH INCIDENT HARD BLOCK
    （evidence_conflict=TRUE 仅诊断；信任根是 anchor——重复运行永续
    BLOCK；修复回原 bytes -> 原 run exact replay）
  evidence_conflict（016）降级为诊断属性；旧 baseline DISTINCT-hash
    查询删除
P0-03 Expected Output Exact Set + Semantic Value Seal（audit §4）：
  migration 017 ledger 两列 normalized_output_set_hash /
    normalized_semantic_hash
  output_set_hash = hash(sorted(output_name, canonical uri, content_hash,
    schema_hash, row_count)) 三方消费：ledger == manifest ==
    replay-time 物理重算
  semantic_hash（全输出表 sorted canonical JSON）三方消费：ledger ==
    manifest == replay-time 从物理 parquet records 重算
  expected exact set：manifest output_name set == CURRENT registry
    spec.output_names（no missing / no extra / no duplicate——删除
    required output + 重绑双 hash 仍 DAMAGED）
  URI deterministic binding：每 output uri == ledger 身份重算的
    base_path + output_name（重绑到另一合法 logical path 仍 DAMAGED）
  物化语义升级：materialized set 恰好等于 spec.output_names（空表
    物化为空 parquet——零产出证据；empty-payload SUCCESS 测试覆盖）
  NormalizationRunSeal 扩展 raw_evidence_uri / raw_payload_kind /
    normalized_output_set_hash / normalized_semantic_hash；manifest 新增
    raw_payload_kind / output_set_hash；pre-CR-2.3 行缺 seal 不作
    healthy replay
Migration 017：anchor 表 + 两 seal 列（未改 014/015/016；17 链
  from-zero + 001..016->017 upgrade + idempotent + tamper probe 018）
Adversarial Tests（+20：normalization 104 = 84 回归 + 20 新增）：
  audit §6 A（operation provenance 3）/ B（raw trust anchor 6）/
  C（output + semantic seal 10）/ D（regression——既有 84 项全保持）矩阵
  全对应；总体 975/0
```

### CR-2.2 Replay Provenance Seal（前批，DONE / REOPENED）

CR-2.1 复审（2026-09-01 10:15 +08:00）裁决 **CR-2.1 REOPENED** 后收口；
2026-09-01 10:45 CR-2.2 复审：**REOPENED**（exact replay / full
fingerprint / schema verify FREEZE，3 P0 trust-root 由 CR-2.3 收口，见上）。
历史细节见 §61 DM-20260901-065 与 ADR-022 Amendment B（其中
require_capability 派生 surface、run-history baseline、外层文件 hash seal
三处表述已被 Amendment C §8.1-§8.3 修订）：

```text
P0-01 Surface 真正 system-derived（audit §2）：
  撤销 call_exchange 的 normalization_surface caller-override 可选参数
    （与 B1/B2 "caller-declared identity is not system-derived" 同裁）
  surface_identity = str(require_capability or "")——capability 契约派生；
    query_kline_exchange（capability=daily_bar）与
    query_index_kline_exchange（capability=index_daily）仅靠 capability 区分
  结构测试：签名无该参数 + provider.py 全部 _call_or_exchange 调用点
    无该 kwarg + 派生表达式断言；registry 18 条映射不变（surface 值
    本就等于 capability 名，零数据迁移）
P0-02 Raw Evidence Binding 冲突不可洗白 + 全历史 exact replay（audit §3）：
  baseline = 该 request 全部非 conflict run 的 DISTINCT raw_evidence_hash；
    current hash 不在 baseline（且 baseline 非空）-> INCIDENT HARD BLOCK
    （evidence_conflict=TRUE，migration 016；不改变 baseline）
  第二次/第三次运行同样 BLOCK（conflict BLOCK 记录不成为新 baseline）；
    conflict run 自身按 exact key 幂等 replay（一 ledger 行）
  surface 篡改（meta surface 字段改 index_daily）-> bytes 变 -> conflict
    BLOCK 永续，永不产出 index_daily SUCCESS
  修复回原始 bytes -> 原 run 照常 exact replay
  exact replay lookup：run_id = uuid5(namespace, idempotency_key) 直接查询
    ledger（不再 latest-run 比较）——mapper A->B->A / contract A->B->A
    rollback replay 历史 A run（无 duplicate-PK、无 B 阴影）；全部 blocked
    分支（含 multi-table / accounting violation）统一 exact lookup
P0-03 Full Seal 消费（audit §4）：
  _supported_key/_blocked_key 混入完整 MAPPER_CODE_FINGERPRINT（64 hex）
    ——显示串可缩 16 hex，correctness hash input 不缩短；前 16 位相同
    的 fingerprint 产生不同 run identity
  typed NormalizationRunSeal dataclass：from_ledger() / 
    current_provenance_problems()（ledger == 当前 contract + 当前 full fp，
    defense in depth）/ manifest_binding_problems()（manifest 全语义字段
    == ledger seal + quarantine 三方绑定 manifest == ledger == DB recompute）
  manifest policy typed 化：SUCCESS/PARTIAL manifest REQUIRED（ledger status
    翻转伪造不出 manifest-free healthy replay）；BLOCKED 携带即验证
  schema_hash 重算：replay 从物理 parquet 重算 sha256(str(frame.schema))
    与 manifest 比对——rebind（换 parquet + 更新 content_hash）仍被拦截
  Rebind tamper 矩阵 10 项：manifest surface/status/counts/
    quarantine_set_hash/mapper_code_hash 篡改 + 重算外层 hash + UPDATE
    ledger hash -> DAMAGED；ledger status/quarantine seal/mapper_code_hash
    篡改 -> DAMAGED；output schema 换绑 -> DAMAGED
Migration 016：meta_provider_normalization_run + evidence_conflict BOOLEAN
  DEFAULT FALSE（未改 014/015；16 链 from-zero + upgrade（001..015 先应用
  再补 016 仅应用尾部）+ idempotent + tamper 测试）
Adversarial Tests（+17：normalization 84 = 67 回归 + 17 新增）：
  audit §2.4（签名/AST/低层不可 override）+ §3.5（H1->H2 三次 BLOCK /
  surface swap 永不 SUCCESS / 修复回 H1 replay / mapper rollback /
  contract rollback）+ §4.6（first16 collision + rebind 矩阵 10 项）全对应
```

### CR-2.1 Surface Identity + Registry Boundary + Replay + Commit Closure（前批，DONE / REOPENED）

CR-2 复审（2026-08-31 17:42 +08:00）裁决 **CR-2 REOPENED** 后收口；2026-09-01 10:15 CR-2.1 复审：**REOPENED**（收口方向保留，3 P0 由 CR-2.2 收口，见上）。历史细节见 §61 DM-CR-20260831-064 与 ADR-022 Amendment A（其中 call_exchange 可选 surface 参数、latest-run hash equality、16-hex 截断 fingerprint 等 3 处表述已被 Amendment B §7.1-§7.3 修订）：

```text
P0-01 Surface Identity（audit §2）：
  registry key 升级为 typed 四元组 (provider, normalization_surface,
    provider_dataset, endpoint)；
  normalization_surface = SYSTEM-DERIVED 持久化身份：provider facade
    call_exchange 派生（默认 capability 身份）-> RawWriter 写入 raw meta
    （向后兼容字段）；禁止 request 参数 / symbol 前缀猜测
  query_kline_exchange (surface=daily_bar -> DailyBarDTO) 与
    query_index_kline_exchange (surface=index_daily -> IndexDailyDTO)
    两个显式 production wrapper——同 endpoint+dataset 的两个业务 surface
    永不误路由（测试断言 schema 互斥）
  legacy 歧义 raw（缺 surface 字段且 pair 多义）-> PAYLOAD_SURFACE_AMBIGUOUS
    BLOCKED（不猜）；非歧义 pair 仍可路由（向后兼容）
  新错误类 PAYLOAD_SURFACE_AMBIGUOUS（分类表六类）
  Coverage guard 升级：provider facade AST surfaces 与
    SDK_METHOD_CLASSIFICATIONS 交叉核对 == registry exact set（18 条）；
    optional 未消费 surface（get_index_daily / get_industry_weight /
    get_industry_daily）显式 NOT_APPLICABLE，不从 structural truth 消失
P0-02 Immutable Registry（audit §3）：
  撤销公开可变 DATASET_NORMALIZATION_REGISTRY；module-private 不可变
    tuple + private exact index；公开面只有只读 lookup_spec / specs_for /
    registry_specs（不可变 snapshot）
  NormalizationRunner 构造器与 run() 签名无 spec/mapper/registry/surface
    参数（结构测试断言）；tests-only 注入仅经 monkeypatch 私有 state
    （B2 scanner static registry 同一裁决口径）
P0-03 One Exact Replay Policy（audit §4）：
  SUCCESS / PARTIAL / BLOCKED 全终态统一：same exact input identity ->
    重验既有 run closure（manifest bytes / outputs / quarantine exact
    set）-> intact = idempotent return；damaged/tampered = fail closed
    （repair required，绝不 false healthy replay）
  mapper code identity 进入 run identity：MAPPER_CODE_FINGERPRINT =
    SHA-256 over governed mapper + DTO module sources（行尾归一跨 OS
    确定性，import 时 system-derived）——mapper 实现变更 -> 新 run
    identity（历史保留）；撤销 caller 自报 code_commit 参数
  CR-2 legacy ledger 行缺 quarantine_set_hash seal -> 永不 healthy replay
  contract 版本 bump cr2.1-v1
P0-04 Atomic + Recoverable Commit Closure（audit §5）：
  写入协议：输出 parquet 先落（ROW scope 全输出物化——空 parquet 即零产出
    证据；WHOLE_PAYLOAD 坏则零输出）-> manifest 最后落盘（correctness
    bytes 无墙钟无 caller provenance，exact retry 字节不变）-> BEGIN
    TRANSACTION（dup 检查 + run INSERT + 全部 quarantine INSERT + 行数
    断言）COMMIT（失败整体 ROLLBACK）
  DB 失败后 exact retry：确定性文件 anchor 幂等 no-op -> ledger
    reconciliation（无 orphan manifest / 半提交 quarantine）
  artifact 路径加 run=<run_id> 段（新 run 新路径，不覆盖历史）
  quarantine exact-set seal：quarantine_set_hash = canonical hash over
    sorted semantic records，同时绑定 manifest 与 ledger；UPDATE/DELETE/
    缺行由 replay 复验发现
  状态机细化：mapped==0 且有 quarantine -> BLOCKED（PARTIAL = 有好行保留）
Migration 015：meta_provider_normalization_run + normalization_surface /
  mapper_code_hash / quarantine_set_hash 三列（ADD COLUMN IF NOT EXISTS；
  未改 014；from-zero 15 链 + upgrade（001..014 先应用再补 015 仅应用尾部）
  + idempotent 测试）
Adversarial Tests（67 项全量 = CR-2 37 项回归 + CR-2.1 新增 30 项）：
  audit §7 清单 19 项全对应（surface 双路由 / legacy 歧义 fail closed /
  覆盖守卫交叉核对 / 无公开可变 registry / 三终态幂等 / 输出-manifest-
  quarantine 篡改删除 fail closed / 注入 DB 失败恢复 / 多输出写失败 /
  mapper code identity 变更 / 双环境同 manifest identity / happy path
  回归 / migration from-zero+upgrade / CI 矩阵 / 冻结回归）
```

### CR-2 Provider-Normalized + Quarantine（前批，DONE / REOPENED）

R4-B2.3 复审（2026-08-31 16:22 +08:00）裁决 **R4-B2 / B2.1 / B2.2 / B2.3
全链 VERIFIED / CLOSED / FREEZE**（ADR-021 → ACCEPTED）；CR-2 批次落地
CR2-P0-01..10（新 ADR-022；工作要求
`docs/design/A-share-analysis_R4-B2.3复审结论与CR-2_ProviderNormalizedQuarantine开发工作要求_20260831.md`）。2026-08-31 17:42 CR-2 复审：core framework FREEZE，4 P0 由 CR-2.1 收口（见上）。历史细节见 §61 DM-CR-20260831-063 与 ADR-022 §1-§5（其中二元 key / 9-5 分类等表述已被 ADR-022 Amendment A §6.1-§6.4 修订）。

### R4-B2 / B2.1 / B2.2 / B2.3（前批，CLOSED / VERIFIED / FREEZE）

全链闭环（Reviewer 2026-08-31 16:22 裁决：除真实可复现 regression 不再
重审；ADR-021 → ACCEPTED）。历史细节见各批 Change Log 与 ADR-021（含
Amendments B / E / F / G）。

## Golden / Trading Rule 人工 Review（结构就绪，等人工执行）

```text
scripts/golden/review.py 逐条核验 123 v3 cases + 补齐 distinct events
scripts/rules/review.py 对已验证 ACTIVE 规则版本执行人工复核（exact-byte
  + serialized-parent seal workflow，已 VERIFIED）
```

## R4-B1（R4-A3.1 VERIFIED 后启动；R4-B2 -> R4-B1 后；CR-2 -> R4-B2 后）

```text
Capability Approval 不接受 caller self-declare；绑定 provider/dataset/
  endpoint/account profile/runtime；persisted exchange evidence；
  permission/endpoint proof 与 business-quality proof 分离
（R4-B1/B2 正式开发要求在 R4-A3.1 VERIFIED 后细化；gate 边界
  FORMAL_GATE_PROBE_KINDS 已为 endpoint/permission proof 提供消费面）
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

**CR-2 交付状态（2026-08-31，DM-CR-20260831-063 / ADR-022；2026-08-31 17:42 复审 REOPENED，CR-2.1 收口 DM-CR-20260831-064；2026-09-01 10:15 CR-2.1 复审 REOPENED，CR-2.2 收口 DM-20260901-065；2026-09-01 10:45 CR-2.2 复审 REOPENED，CR-2.3 收口 DM-20260901-066；2026-09-01 14:26 CR-2.3 复审 REOPENED，CR-2.4 收口 DM-20260901-067；**2026-09-01 17:06 CR-2.4 最终复审：CR-2 / CR-2.1 / CR-2.2 / CR-2.3 / CR-2.4 全链 VERIFIED / CLOSED / FREEZE，ADR-022 REVIEWER ACCEPTED**）**：typed dataset normalization registry + NormalizationRunner（raw evidence 唯一输入 / verified reader / closure 校验 / SOURCE_EXCHANGE_FAILED 分离）+ first-class immutable 持久化输出（parquet + manifest + ledger）+ no-silent-drop 记账不变式（runtime 机器强制）+ first-class quarantine（append-only / row locator / scrubbed context）+ deterministic replay + provider-faithful DTO（不预支 canonical 语义）+ SUCCESS/PARTIAL/BLOCKED 状态机。CR-2.1 收口后：typed surface 四元 key（system-derived normalization_surface 持久化身份 + index/daily 双 wrapper + legacy 歧义 fail closed）/ private 不可变 registry（无公开可变对象，runner API 无注入面）/ 全终态统一 exact replay（重验 closure 后幂等；篡改即 fail closed；system-derived mapper code fingerprint 进入 run identity）/ atomic + recoverable commit closure（manifest 无墙钟最后落盘 + 单事务 ledger/quarantine + quarantine exact-set seal + 注入失败恢复测试）。67 项对抗测试（含结构守卫 + 覆盖交叉核对）；migration 014 + 015；详见 §41 / ADR-022（含 Amendment A）。CR-2.2 收口后：surface 严格 capability 契约派生（无 caller-override 参数）/ raw evidence binding 冲突不可洗白（evidence_conflict 标记 + INCIDENT HARD BLOCK 永续）/ 全历史 exact run_id replay（mapper/contract rollback 无 duplicate-PK）/ full mapper hash 进入 identity + typed NormalizationRunSeal 全语义字段三方绑定 + schema_hash 重算（rebind tamper 矩阵 10 项全拦截）。84 项对抗测试；migration 014 + 015 + 016；详见 §41 / ADR-022（含 Amendment A + B）。CR-2.3 收口后：provider-owned operation spec（私有静态常量 + 私有 executor + 公开面无 generic callable）/ ingestion-time raw evidence anchor（meta 精确字节 hash 外部权威登记；legacy 无 anchor fail closed；mismatch 永续 BLOCK；evidence_conflict 降级诊断）/ expected output exact-set + semantic value seal（三方绑定 ledger == manifest == 物理重算；expected set == 当前 spec.output_names；URI deterministic 重算；空表物化）。104 项对抗测试；migration 014 + 015 + 016 + 017；详见 §41 / ADR-022（含 Amendment A + B + C）。CR-2.4 wiring 收口后：AnchoredRawEvidenceWriter 唯一 production 写入边界（commit-identity 绑定 enrollment + TOCTOU verify-only reread + envelope identity cross-binding）/ ProbeContext + run_dry_run 全接线（SUCCESS/ERROR 均自动 anchor）/ enrollment API 私有化收口（verify-only，不接受现场 hash 定义真值）/ 结构守卫封死 unanchored 写入。114 项对抗测试；详见 §41 / ADR-022（含 Amendment A + B + C + D）。

**CR-3 交付状态（2026-09-01，DM-20260901-068 / ADR-023；六轮复审 REOPEN 收口：CR-3.1 DM-20260901-069 / CR-3.2 DM-20260901-070 / CR-3.3 DM-20260902-071 / CR-3.4 DM-20260902-072 / CR-3.5 DM-20260902-073 / CR-3.6 DM-20260902-074；**2026-09-02 21:24 最终复审全链 VERIFIED / CLOSED / FREEZE，ADR-023 ACCEPTED**）**：CanonicalRunner（CR-2 verified 唯一输入 + 只读 closure verifier / SUCCESS-only eligibility）/ IdentityBridge（security_master 三 dataset 全集 → ADR-002 身份；裸码唯一市场匹配；PIT relist；missing/ambiguous fail closed）/ AvailabilityPolicy（OBSERVED_AT_INGEST + as_of 先行过滤）/ SourcePolicy 静态版本化（SINGLE_SOURCE_EXACT；EXACT reconciliation）/ Domain eligibility matrix 13 项显式（5/2/6）/ immutable canonical artifacts + deterministic run identity / migration 018。CR-3.1 收口后：RequestedDomainSet identity（019）/ availability completeness / CanonicalInputSnapshot / anchored availability evidence / identity binding 统一 / policy hash 全字段 / full replay seal / recoverable commit。CR-3.2 收口后：transactional materialized snapshot / identity master PIT / honest policy execution / typed full CR-2 input seal / verification-state transition。CR-3.3 收口后：historical input continuity guard（canonical_context_hash 021——ledger disappearance/status/seal drift 全部 DAMAGED 拒绝，superset 合法新增、exact restore 恢复历史 replay、master 同规则）/ verification evidence exactness（verification_problem_hash 进 state/seal/input_seal_hash——同 class 不同 cause 新 BLOCKED run、exact failure 幂等、INVALID sealed input replay 比对当前 problem evidence）/ finding truthfulness（reserved scope input:\<surface\> + affected_domains；damaged 不误报 UNAVAILABLE）/ seal count correction（21/17，测试机械断言）。**CR-3.4 收口后**：historical canonical run seal trust（typed CanonicalRunSeal + `_verify_historical_canonical_seal`——历史 manifest input list 在被 continuity 信任前先过 deterministic URI + bytes hash + 全部显式 correctness 字段 == ledger + input_seal/input_set/verification_state 三 hash 物理重算；manifest+ledger outer-hash rebind 无法洗出已消费输入；prior 自身 DAMAGED → HARD DAMAGED 零 replacement）/ verification evidence replay symmetry（first consume 与 replay 共用 `_collect_input_verification_evidence` collector——materialization-only failure 的 exact evidence hash 首跑与重放对称重建，keep_rows 是唯一差异）/ manifest correctness identity 全消费（canonical_context_hash + base_identity_hash + verification_state_hash 进 typed manifest binding，manifest == ledger == current 三方闭环）。151 项对抗测试；migration 018 + 019 + 020 + 021（CR-3.4 零新 migration）；总体 1136/0。**CR-3.5 收口后**：tamper-resistant historical candidate discovery（候选发现按 primitive request-world fields——requested_domains_hash + as_of + contract + 三 policy identities + code_fingerprint，不用 status 预过滤、不把 stored canonical_context_hash 当 selection key；候选先过 full historical seal 再解释已验证的 world/status——genuine BLOCKED 非依赖不阻塞 recovery、旧 bridge policy 世界跳过）/ derived canonical run seal 物理闭环（模块级单一派生公式集三方共用：requested_domains_hash / 三 input hash / master set / dataset hash（用该 run 自己的 manifest bridge identity 重算）/ context / base / idempotency / run id UUID5 cross-bind；`_derived_run_identity_problems` 全部重算与 ledger 逐字段比对，消费于 historical seal verifier + replay closure verifier；live build 全部委托同一 helpers）/ status semantic seal（`_verify_findings_truth`：findings 三方 DB==parquet==seal 后从 blocking truth 重算 status 与 error text 并消费 ledger/manifest 字段；error_message 升级为 derived audit text——P1 收口）。166 项对抗测试；migration 018 + 019 + 020 + 021（CR-3.5 零新 migration）；总体 1151/0。**CR-3.6 收口后**：selection-free / pre-verification-trust-free historical discovery（Phase A broad 全表扫描无 WHERE 无 Python 预过滤——"No correctness-bearing field may exclude a historical canonical row before its identity seal is verified"；Phase B `_verify_historical_identity_seal` 先验身份（findings truth 刻意移出，只在同 world 后运行）；Phase C 验证后才解释 world/status——different world 安全 skip / same world → artifact closure + findings truth → CR-2 依赖 / genuine BLOCKED 非依赖；identity seal 任何 problem → GLOBAL / HISTORICAL CANONICAL LEDGER DAMAGED fail closed 零 mint；ledger+manifest 对 rebind 由 derived identity/run-id cross-bind 在 world 分类前拦截）/ shared historical canonical artifact closure verifier（`_verify_canonical_artifacts`：counts==ledger + exact set + deterministic URIs + 物理 content_hash/row_count/schema_hash + selected/decision 语义 seals，exact replay 与 historical continuity 共用；genuine BLOCKED 亦须证据内部完好）。194 项对抗测试；migration 018 + 019 + 020 + 021（CR-3.6 零新 migration）；总体 1179/0；详见 §41 / ADR-023（含 Amendment A + B + C + D + E + F）。

**CR-4 首批交付状态（2026-09-03，DM-20260903-075 / ADR-024 PROPOSED）**：Canonical 公共消费验证器（`canonical/verifier.py`——verified SUCCESS 唯一消费入口，BLOCKED 显式拒绝，sealed CR-2 权威+物理验证不要求 current discovery presence）/ SnapshotBuilder（`snapshot/` 包——版本化 schema registry（market=payload、factor_type=key projection）；确定性 identity（canonical run-level seals + contract + builder fingerprint → UUID5）；immutable domain-partitioned artifacts + manifest LAST；migration 022 `meta_snapshot_build`（exact retry 幂等 replay + crash 残留 fail closed）；`verify_snapshot`（identity UUID5 cross-bind + canonical provenance cross-bind 重跑消费验证器 + artifact 物理/语义/聚合 seal 重算））/ DuckDB ReadModel（`readmodel/` 包——temp 库构建 + registry 精确类型建表 + `read_parquet(hive_partitioning=false)` + **temp 上 logical seal**（表集/行数/key 唯一/表内容重算 semantic hash（UTC 归一化）/schema 精确/meta 表）+ `Path.replace` 原子替换；失败零残留）/ 边界 AST guard（禁 providers/normalization/raw_writer/特征库）/ **CR-3 latent 缺陷显式申报修复**（multi-domain semantic seal 对齐缺陷——提请复审裁决）。44+11+1 新增测试；migration 018-022；总体 1235/0；详见 §41 / ADR-024。

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

CR-4.4 additional closure：

```text
canonical selected rows → shared registry projection replay
→ exact expected artifact rows (including zero-row domains)
→ physical bytes/schema/semantic/aggregate verification
→ verified Snapshot → verified-open ReadModel
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

## DM-20260903-076 — CR-4.4 Snapshot 回放、不可变写入与 ReadModel provenance 收口

**Type**：C4 correctness closure（CR-4 首批复审 reopen；ADR-024 Amendment A PROPOSED）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：2026-09-03 CR-4 首批复审要求收口 P0-01 deterministic canonical projection、P0-02 recoverable immutable write、P0-03 explicit key binding、P0-04 physical schema hash / same-byte materialization、P0-05 ReadModel provenance + verified-open。  
**Scope**：仅上述五项与 focused tests、ADR-024 Amendment A、DEVLOG、工作要求 §13.7；migration 022 不改；CR-5、Feature/State、provider/fallback/production 不在范围内。

**Implementation**
- Snapshot schema registry 新增 `KeyBinding` 与 `stable_sort_key`；新增共享 `project_verified_canonical_snapshot`，Builder/verifier 完全共用。
- Snapshot verifier 对每个物理 artifact 的 expected canonical projection 做 exact row/semantic 比对；业务值或 lineage 连同 manifest/ledger seals rebound 仍 DAMAGED。
- immutable writer 支持 identical no-op、missing write、different-byte conflict；全计划 preflight，manifest LAST；ledger commit crash 与 partial residue 可 exact retry。
- Canonical/Snapshot verifier 从已 hash-verify 的同一 bytes 解析 Parquet；Snapshot schema_hash physical recompute；公共 canonical verifier 复用已物化 selected rows。
- ReadModel meta 增加 snapshot/readmodel builder fingerprints；logical seal 检查 canonical_as_of、完整 domain_meta snapshot binding；`open_read_only` / `verify_readmodel` 执行 verified-open。

**Schema / Contract**：migration 022 unchanged；derived ReadModel schema change is per-build and does not add project migration 023。  
**Affected Modules**：`src/ashare_state/snapshot/schema.py`、`snapshot/builder.py`、`snapshot/verifier.py`、`snapshot/__init__.py`、`src/ashare_state/canonical/canonicalizer.py`、`canonical/verifier.py`、`src/ashare_state/readmodel/duckdb_model.py`、`readmodel/__init__.py`、focused integration tests、ADR-024、DEVLOG、CR-4 work requirement §13.7。  
**Tests**：在既有 CR-4 首批回归基础上增加 CR-4.4 对抗测试；具体数量以 PR CI 正向结果为准。  
**Verification**：PR CI pending；不把实现完成误报为审计 VERIFIED。  
**Commit**：`__INITIAL_COMMIT_SHA__`（待 GitHub commit object 创建后回填）  
**Reviewer**：PENDING_REVIEW

## DM-20260903-075 — CR-4 首批：Canonical 公共消费验证器 + SnapshotBuilder + DuckDB ReadModel

**Type**：C4（CR-4 启动首批；含 CR-3 closure 治理同步与 CR-3 latent 缺陷显式申报修复）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3 全链最终复审（2026-09-02 21:24 +08:00，Reviewer closure commit `ff3808b7a5036246ea11e37173aa31d863beb2d9`，文档 `docs/design/A-share-analysis_CR-3.6最终复审结论与CR-4启动裁决_20260902.md`）裁决 **CR-3 / CR-3.1 / CR-3.2 / CR-3.3 / CR-3.4 / CR-3.5 / CR-3.6 全链 VERIFIED / CLOSED / FREEZE；ADR-023 → ACCEPTED；CR-4 SnapshotBuilder + DuckDB ReadModel START**；CR-4 工作要求 `docs/design/A-share-analysis_CR-4_SnapshotBuilder及DuckDBReadModel开发工作要求_20260902.md`（audit 20260902；P0-A01..A03 / P0-A04..A12 / P0-B01..B09；mandatory 测试 1-50；§5 十问须 ADR 回答；§12 流式红线含"CR-3 frozen 缺陷须显式申报，不得悄悄修复或绕过"）。  
**Governance Sync（裁决要求的第一动作，本 commit 内完成）**：ADR-023 status → ACCEPTED（六轮 Amendment 裁决并入）；ADR-000 索引同步；CR-3.6 工作要求追加 Reviewer Closure 裁决章节；DM 头部基线切换至 reviewer closure commit `ff3808b`；CR-3 全链 → VERIFIED / CLOSED / FREEZE。  
**New Contract**（ADR-024 PROPOSED，§5 十问十答）：（1）**CR-4.1 Canonical 公共消费验证器**（`src/ashare_state/canonical/verifier.py`）：`verify_canonical_run_for_consumption` 是下游读取 canonical truth 的唯一支持入口——ledger row → typed identity seal（deterministic URI + bytes hash + manifest==ledger + 全 derived identity 物理重算）→ 共享 artifact closure verifier → findings truth + status 语义重算 → **verified SUCCESS 才可消费**（BLOCKED 显式拒绝）→ 每 sealed CR-2 input 权威 ledger identity + 物理/anchor 健康（`_sealed_input_authority_problems` 共享提取，**不要求 current discovery presence**——合法 superset 增长不追溯破坏已 mint SUCCESS 的消费）→ selected rows 从 hash 验证过的 parquet 物化。VerifiedCanonicalRun frozen dataclass。（2）**CR-4.2 SnapshotBuilder**（`src/ashare_state/snapshot/`）：版本化 schema registry（DomainSnapshotSchema/ColumnSpec/DType——列集/logical dtype/nullability/key arity/key projection 单一事实源；trade_calendar.market=payload 字段、adj_factor.factor_type=key projection（canonical key 第 3 段 typed decode））；确定性 identity（snapshot_base_hash = canonical run-level seals（run_id/manifest_hash/requested_domains_hash/selected_semantic_hash/as_of）+ snapshot_contract_version + builder code fingerprint 的 canonical JSON SHA-256 → snapshot_id = UUID5(SNAPSHOT_NAMESPACE, ...)——从 run-level seals 而非投影行派生：可先算后写、manifest 原语可重算）；artifact 布局 `snapshot/contract=snapshot-v1/as_of=<fmt>/snapshot=<id>/<domain>.parquet + manifest.json(LAST)`（artifact 集 == 请求 domain 集精确）；严格投影（canonical_key JSON round-trip 验证 + PIT 契约断言 available_at <= as_of + typed 转换 fail closed + canonical_key 稳定排序 + key 唯一）；`_write_immutable` 拒绝覆盖；migration **022** `meta_snapshot_build`（一事务 dup-check + INSERT；exact retry → verify_snapshot 全物理验证后幂等 replay；目录存在 ledger 无行 → 显式 fail closed crash 残留）；`verify_snapshot`（deterministic URI + bytes hash + manifest==ledger + identity UUID5 cross-bind + builder fingerprint 一致 + **canonical provenance cross-bind**（重跑消费验证器 + manifest canonical 字段 == VERIFIED ledger truth——canonical 在 snapshot 之后损坏同样 fail closed）+ artifact exact set == requested domains + 物理 content/schema/row_count/semantic seal 重算 + row PIT/投影 sanity + artifact_set_hash/snapshot_semantic_hash/row_count_total 聚合重算）。（3）**CR-4.3 DuckDB ReadModel**（`src/ashare_state/readmodel/`）：`DuckDBReadModel.rebuild` = verify_snapshot → temp 库（`.readmodel.building.duckdb`）→ 建表（registry 精确 DuckDB 类型映射 + `PRIMARY KEY (canonical_key)` + NOT NULL identity 列）→ INSERT（`read_parquet(hive_partitioning=false)`——修复路径 `contract=/as_of=/snapshot=` 段被误读为分区列）→ **temp 库上 logical seal**（表集精确 == `{rm_<domain>} ∪ {rm_snapshot_meta, rm_domain_meta}` / 行数 == snapshot seal / key 唯一 / **从表内容重算 semantic hash == snapshot 域 seal**（TIMESTAMPTZ fetch 归一化回 UTC）/ `information_schema` 列类型精确比对（TIMESTAMP WITH TIME ZONE 显式时区语义）/ rm_snapshot_meta + rm_domain_meta 内容）→ `Path.replace` 原子替换确定性目标 `readmodel/contract=readmodel-v1/snapshot=<id>/readmodel.duckdb`；失败 temp 删除旧目标字节不变（无部分/损坏模型可见）；`open_read_only` 消费入口。（4）**边界 AST guard**：snapshot/ 与 readmodel/ 禁止 import providers/normalization/raw_writer；禁止 pandas/talib/numpy/scipy/sklearn（无特征计算）；`SnapshotBuilder.build` 签名只接受 canonical_run_id。  
**CR-3 Latent 缺陷显式申报（§12 红线合规——提请 Reviewer 在 CR-4 复审中一并裁决，未悄悄修复）**：CR-3 `_write_artifacts` 的 selected/decision semantic seal 曾对**未对齐 rows**计算，而 parquet 写 `_align_schema` 对齐后的 rows——**多 domain 混合时 exact replay 的 recompute 必然误报 DAMAGED**（fail-closed 方向 false positive；单 domain key 集合一致故 1179 项既有回归全绿、六轮复审未暴露；CR-4 多 domain 消费首次触发）。最小修复：seal 改为对 aligned rows 计算（单 domain 行为逐字节不变——194 项既有 canonical 回归全保持即证明）；新增 `TestMultiDomainReplayRegression::test_multi_domain_exact_replay_idempotent` 回归钉。申报位置：ADR-024 Consequences / 本条目 / DEVLOG / CR-4 工作要求 Implementation Mapping §7.5。  
**Schema**：migration **022** `meta_snapshot_build`（链 21 → 22；含 idx canonical_run_id）  
**Affected Modules**：`src/ashare_state/canonical/verifier.py`（新）、`src/ashare_state/canonical/canonicalizer.py`（`_sealed_input_authority_problems` 共享提取 + semantic seal aligned 修复）、`src/ashare_state/snapshot/`（schema/models/builder/verifier，新包）、`src/ashare_state/readmodel/`（schema/duckdb_model，新包）、`migrations/022_snapshot_build.sql`、`tests/integration/test_snapshot.py`（新，44）、`tests/integration/test_readmodel.py`（新，11）、`tests/integration/test_canonical.py`（+1 回归）、`tests/integration/test_migrations.py`（22 链 + 021→022 升级 + probe 023）、`tests/integration/conftest.py`（conn/env_root 共享）、`docs/adr/ADR-024`（新）、ADR-023/ADR-000（ACCEPTED 同步）  
**Tests**：1235/0（1179 → 1235，+56；mandatory 1-50 全对应）  
**Verification**：Local 1235/0；ruff check / ruff format / mypy 全绿（78 源文件）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33715493176（final `0c328c3de95c636df053a52bb5b4814fde2d14cb`）三腿 success**（2026-09-03 API positive confirmation；implementation `2db6d8d` 首跑 run 33707982975 暴露 2 处仅测试断言的跨环境脆弱性，2 次 assertion-only 修复轮次后全绿——零产品代码改动）  
**Commit**：`2db6d8d6cc1fef047175b1f23c80016f003eee63`（CR-4 首批 implementation）+ `397ea7c`（fix：superset winner 跨环境断言）+ `0c328c3de95c636df053a52bb5b4814fde2d14cb`（fix：spike evidence glob 平台序断言）  
**Reviewer**：PENDING_REVIEW

## DM-20260902-074 — CR-3.6 Selection-Free Historical Discovery + Historical Canonical Artifact Closure

**Type**：C3 correctness closure（ADR-023 Amendment F；CR-3.5 复审 2 新 P0 全收口；零新 migration）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3.5 复审（2026-09-02 17:36 +08:00，Reviewed HEAD `3c6087e13de4af26143aa72a2a8bbeade052ecdb`，Primary implementation `48982290056cf88e6daafbecb7d8b8a766da6e28`，裁决 **REOPENED**——**Derived Run / Status Seal 全部 PASS / FREEZE**（21 项机制：status 不再作 historical SQL pre-filter / stored context 不再作 selection key / live build 共享 derived formulas / requested_domains_hash·三 input hash·master set·dataset hash（run 自己的 bridge identity）·context·base·idempotency·run-id UUID5 cross-bind·status·error_message 全物理重算 / findings DB==parquet==seal / materialization symmetry / genuine BLOCKED recovery / old bridge world skip / no new migration）；P0-01：historical candidate discovery 虽不再依赖 status/context，仍在 full-seal verification 之前依赖其它可漂移 correctness-bearing fields（requested_domains_hash / contract / policy identities / code_fingerprint / as_of）做 SQL/Python filtering——只漂移其中一个字段即可把 prior SUCCESS 从 verifier 前隐藏；P0-02：historical Canonical seal 在非 exact-replay 的 continuity/superset 路径尚未验证 prior SUCCESS 的 selected / decisions artifact closure——旧 Canonical 产物损坏后仍可能放行新 superset run；工作要求 `docs/design/A-share-analysis_CR-3.5复审与CR-3.6最终PreVerificationDiscovery及HistoricalCanonicalArtifactClosure收口要求_20260902.md`，reopen commit `dd31ca6`）。  
**New Contract**（ADR-023 Amendment F §11.1-§11.2）：（1）**P0-01 Selection-Free / Pre-Verification-Trust-Free Discovery**：原则 "No correctness-bearing field may exclude a historical canonical row before its identity seal is verified"。Phase A broad discovery（`SELECT 全部 ledger row ORDER BY canonical_run_id`——无 WHERE、无 Python 预过滤）；Phase B 每行先过 historical identity seal（`_verify_historical_identity_seal`：deterministic manifest URI / bytes hash / manifest 显式 correctness 字段 == ledger / requested domains hash + 三 input hash + master set + dataset hash（run 自己的 bridge identity）+ context + base + idempotency + run-id 全物理重算；findings truth 刻意移出——只在 same-world 分类后运行）；Phase C 验证后才解释 world/status（verified different request world → safely skip / verified same world → shared artifact verifier → findings/status truth →（SUCCESS）CR-2 dependency continuity / verified genuine BLOCKED → 非依赖 recovery allowed）。identity seal 任何 problem → **GLOBAL / HISTORICAL CANONICAL LEDGER DAMAGED**（不能安全证明与当前 world 无关，fail closed 零 mint）。ledger+manifest 单字段对 rebind（伪造 different world）由 derived identity / run-id cross-bind 在 world 分类之前拦截，不可能借 forged world 提前 skip。（2）**P0-02 Shared Historical Canonical Artifact Verifier**：`_verify_canonical_artifacts(record, manifest)`（自 `_verify_closure` artifact 段抽取的共享只读 helper）：manifest selected_count/decision_count == ledger + artifact exact set（selected/decisions/findings）+ deterministic artifact URIs + physical content_hash/row_count/schema_hash 逐 artifact + selected/decision semantic seals（recompute == ledger == manifest）。消费点：exact replay（`_verify_closure`）与 historical continuity（same-world 每行——genuine BLOCKED 亦须 recorded evidence 内部完好才可被分类为 genuine）。findings artifact 三方 truth 与 status recompute 保留在共享 `_verify_findings_truth`。  
**Schema**：零新 migration（复审 §3.1 允许"仅当引入真正有独立完整性锚的 history index"；未验证的普通 ledger 索引字段会换回旧漏洞；migration 链保持 21）  
**Affected Modules**：`src/ashare_state/canonical/canonicalizer.py`（selection-free 发现重写 + identity seal 拆分 + `_verify_canonical_artifacts` 抽取与两路消费）、`tests/integration/test_canonical.py`（194 项 = 166 回归 + 28 新增）、`docs/adr/ADR-023`（Amendment F）、`docs/adr/ADR-000`（索引）  
**Tests**：1179/0（1151 → 1179，+28：TestSelectionFreeDiscovery 20 / TestHistoricalArtifactClosure 8；复审 §1.3/§2.4 mandatory 14 项全对应）  
**Verification**：Local 1179/0；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33623939024（implementation `1ebe96b9d28617939c2782795395ef23eee597e0`）三腿 success**（2026-09-02 API positive confirmation，一次通过零修复轮次）  
**Commit**：`1ebe96b9d28617939c2782795395ef23eee597e0`（CR-3.6 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260902-073 — CR-3.5 Historical Candidate Discovery + Derived Canonical Run/Status Seal

**Type**：C3 correctness closure（ADR-023 Amendment E；CR-3.4 复审 2 新 P0 + P1 全收口；零新 migration）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3.4 复审（2026-09-02 13:17 +08:00，Reviewed HEAD `8585b08dc079207e8306bf3be38cf3de3de2f7a4`，Primary implementation `fce2ca43a35b95d61dc390647fdc46d844d9b1a5`，裁决 **REOPENED**——原定 3 P0 PASS / FREEZE（14 项机制：CanonicalRunSeal typed historical seal / continuity 先验历史 manifest URI+hash / 三 input hash 物理重算 / `_INPUT_IDENTITY_FIELDS` 单一字段真相 / first consume + replay 共用 evidence collector / materialization symmetry 全链 / manifest 三 correctness identity replay full-consume / no new migration）；P0-01：historical continuity candidate discovery 仍在 seal verification 之前依赖可漂移的 `canonical_context_hash` 与 `status` 字段——路径 A（ledger status 改 'BLOCKED'）与路径 B（context hash 漂移假值）都让历史 SUCCESS 在进入 verifier 前被隐藏，随后 DELETE 其消费的 CR-2 输入即可 mint 新 truth；P0-02：CanonicalRunSeal 未把 context/base/idempotency/run-id/identity-master/status 等 derived truth 从 primitive seal / findings 物理推导回来——尤其 status 可被 ledger+manifest 同时重绑（SUCCESS→BLOCKED 洗成 genuine BLOCKED 隐藏 continuity 依赖；BLOCKED→SUCCESS 反向）；P1：error_message 处于"看似 correctness 实则不校验"的中间态；工作要求 `docs/design/A-share-analysis_CR-3.4复审与CR-3.5最终HistoricalCandidateDiscovery及DerivedRunSeal收口要求_20260902.md`，reopen commit `275fc93`）。  
**New Contract**（ADR-023 Amendment E §10.1-§10.2）：（1）**P0-01 Tamper-Resistant Historical Candidate Discovery**：候选发现按 primitive request-world fields（`requested_domains_hash` + `as_of`（Python 侧 `_ledger_as_of` 精确比较）+ `canonical_contract_version` + 三 policy version/hash + `code_fingerprint`），不用 `status` 预过滤、不把 stored `canonical_context_hash` 当 selection key；每个候选先过 full historical seal（§9.1 全部检查 + derived identity 物理重算 + findings truth→status 语义重算），之后才解释已验证的 world/status：verified SUCCESS 且 ledger context == current → continuity 依赖；verified genuine BLOCKED → 非依赖（不阻塞 exact repair/recovery）；verified 但 context != current（旧 bridge policy 世界）→ 跳过。（2）**P0-02 Derived Canonical Run Seal 物理闭环**：模块级单一派生公式集（live build / replay / historical continuity 三方共用）：`_requested_domains_hash_from_list`（sha256 compact JSON of domain list）/ `_input_hashes_from_entries`（CR-3.4 既有三 hash）/ `_master_input_set_hash_from_entries`（PIT-healthy master entries，live 同公式）/ `identity_dataset_hash_with_bridge`（`identity.py` 参数化抽取——用该 run 自己的 manifest bridge identity 重算，当前世界入口委托之，公式唯一）/ `_canonical_context_hash_from_primitives` / `_base_identity_hash_from_primitives` / `_idempotency_key_from_hashes` / `_canonical_run_id_from_idempotency`（UUID5(namespace, key) cross-bind）/ `_status_error_from_findings`（findings blocking truth → (status, error)）；`_derived_run_identity_problems(entries, requested_domains, as_of, ledger, manifest)` 把全部重算与 ledger 逐字段比对，消费于 `_verify_historical_canonical_seal`（continuity）+ `_verify_closure`（replay，与 expected_provenance/current + typed manifest binding 构成三方闭环）；live build（snapshot 属性 / `_build_snapshot` / `run()` 状态派生）全部委托同一 helpers（复审 §3 允许的最小必要抽取，公式逐字节不变）。（3）**status semantic seal**：`_verify_findings_truth(record, manifest)`（replay + historical 共用）——findings 三方（DB rows == findings parquet == finding_set_hash seal；parquet 按 deterministic URI + content hash + row count 验证）后从 blocking truth 重算 status 与 error text 并**消费** ledger/manifest 的 status/error_message 字段；未来新增 status 必须由明确 typed transition 规则扩展。  
**Schema**：零新 migration（复审 §3 允许"仅确需持久化额外 primitive request-world field 时"——bridge policy identity 已由 manifest 持久化且参与物理重算，ledger 侧新增列不改变 primitive 漂移这一已接受残余边界的本质；migration 链保持 21）  
**Affected Modules**：`src/ashare_state/canonical/canonicalizer.py`（候选发现重写 + derived seal helpers + `_verify_findings_truth` + 三方消费点 + live 委托）、`src/ashare_state/canonical/identity.py`（`identity_dataset_hash_with_bridge` 参数化抽取）、`tests/integration/test_canonical.py`（166 项 = 151 回归 + 15 新增）、`docs/adr/ADR-023`（Amendment E）、`docs/adr/ADR-000`（索引）  
**Tests**：1151/0（1136 → 1151，+15：TestHistoricalCandidateDiscovery 6 / TestDerivedRunSeal 9；复审 §1.4/§2.3 mandatory 15 项全对应 + run-id cross-bind positive control）  
**Verification**：Local 1151/0；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33601822767（implementation `48982290056cf88e6daafbecb7d8b8a766da6e28`）三腿 success**（2026-09-02 API positive confirmation，一次通过零修复轮次）  
**Commit**：`48982290056cf88e6daafbecb7d8b8a766da6e28`（CR-3.5 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260902-072 — CR-3.4 Historical Canonical Seal Trust + Verification Replay Symmetry + Manifest Correctness Identity Binding

**Type**：C3 correctness closure（ADR-023 Amendment D；CR-3.3 复审 3 P0 全收口；零新 migration）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3.3 复审（2026-09-02 10:22 +08:00，Reviewed HEAD `b5fdc27b9f2fd9c262c7dc6dae9aa665b9494bc1`，Primary implementation `f8b80b3212ff299f52ee3fb0308c248fd16c17df`，裁决 **REOPENED**——18 项机制 PASS / FREEZE（canonical_context_hash 方向 / continuity guard 按 context 查历史 / 全部 CR-2 ledger drift 检测 / superset 合法 / exact restore replay / verification_problem_hash 进 seal+state / finding truthfulness / 治理计数）；P0-01：continuity guard 信任可被 rebind 的历史 Canonical input list——改历史 manifest input list（去 A）+ rehash + 只更新 ledger.manifest_hash + DELETE CR-2 A → A 被"洗出"continuity evidence，可 mint 新 SUCCESS truth；P0-02：materialization-only failure 的 first-run/replay verification evidence 不对称——replay 硬编码 `materialization_problems=[]`，first-run seal 可含非空 materialization evidence（TOCTOU path），exact evidence hash 无法对称重建，产生自相矛盾；P0-03：manifest 的 canonical_context_hash + base_identity_hash + verification_state_hash 三 correctness identity 字段写入但 replay 不消费——display-only seal，edit manifest + rehash + update ledger.manifest_hash 可造自相矛盾 manifest；工作要求 `docs/design/A-share-analysis_CR-3.3复审与CR-3.4最终ContinuitySeal及VerificationReplay收口要求_20260902.md`，reopen commit `33d0901`）。  
**New Contract**（ADR-023 Amendment D §9.1-§9.3）：（1）**P0-01 Historical Canonical Run Seal Trust**：typed `CanonicalRunSeal`（frozen dataclass，`from_ledger`）+ `_verify_historical_canonical_seal()`——continuity 在使用历史 manifest input list 前先验证完整历史 seal：deterministic manifest URI（expected base + /manifest.json）+ manifest bytes == ledger.manifest_hash；manifest 显式 correctness 字段（canonical_run_id / contract / as_of / idempotency_key / status / requested domains json+hash / input_set_hash / input_seal_hash / identity_dataset_hash / identity_master_input_set_hash / canonical_context_hash / base_identity_hash / verification_state_hash / 三 policy version+hash / code_fingerprint）== ledger seal；**物理重算** `_input_hashes_from_entries()`（与 CanonicalInputSnapshot 同公式）：historical input_seal_hash（全 seal entries canonical JSON）/ input_set_hash（identity subset——`_INPUT_IDENTITY_FIELDS` 模块级单一事实源，`InputRunSeal.identity_dict` 同源）/ verification_state_hash（run_id + verification + verification_problem_hash per entry）三者必须 == ledger（列表删除/改写/重排/改 seal 字段均无法重算出 sealed hashes）。prior canonical manifest/ledger 自身 DAMAGED → HARD DAMAGED：不用该 input list 做 continuity 判断，零 replacement。（2）**P0-02 Verification Evidence Replay Symmetry**：first consume（`_snapshot_run`）与 replay（`_verify_sealed_input` INVALID 分支）**共用同一 collector** `_collect_input_verification_evidence(run identity, role, as_of, keep_rows)`：closure problems → anchored-evidence problems →（closure+anchor 健康时）exact-byte materialization verify → derived verification enum → canonical problem evidence → problem hash；first-run（keep_rows=True）额外保留物化行，replay（keep_rows=False）丢弃行但运行同一验证序列/语义；materialization-only failure 被 replay 精确重建（exact repeat → idempotent replay 同一 BLOCKED run；cause 变化 → 新 exact evidence identity；exact repair → recovery run，历史 BLOCKED 保留）；typed `InputVerificationEvidence` frozen dataclass 封装 collector 输出。（3）**P0-03 Manifest Correctness Identity 全消费**：canonical_context_hash / base_identity_hash / verification_state_hash 进入 `_verify_closure` 的 typed manifest binding（manifest == ledger == current recompute 三方闭环——expected_provenance 证 ledger==current，manifest binding 证 manifest==ledger）；continuity 历史 seal expected_fields 同样消费三字段。  
**Schema**：零新 migration（复审 §4 优先不新增 schema——三收口全部为 canonicalizer runtime 侧，020/021 已有全部所需列；migration 链保持 21）  
**Affected Modules**：`src/ashare_state/canonical/canonicalizer.py`（historical seal verify + shared evidence collector + manifest identity binding + `_INPUT_IDENTITY_FIELDS` 提取）、`src/ashare_state/canonical/__init__.py`（导出 CanonicalRunSeal / InputVerificationEvidence）、`tests/integration/test_canonical.py`（151 项 = 131 回归 + 20 新增）、`docs/adr/ADR-023`（Amendment D）、`docs/adr/ADR-000`（索引）  
**Tests**：1136/0（1116 → 1136，+20：TestHistoricalCanonicalSealTrust 9 / TestMaterializationEvidenceSymmetry 4 / TestManifestCorrectnessIdentityBinding 7；复审 §1.3/§2.3/§3 mandatory 13 项全对应 + positive controls）  
**Verification**：Local 1136/0；ruff check / ruff format / mypy 全绿；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33591527697（implementation `fce2ca43a35b95d61dc390647fdc46d844d9b1a5`）三腿 success**（2026-09-02 API positive confirmation，一次通过零修复轮次）  
**Commit**：`fce2ca43a35b95d61dc390647fdc46d844d9b1a5`（CR-3.4 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260902-071 — CR-3.3 Historical Input Continuity + Verification Evidence Exactness + Finding Truthfulness

**Type**：C3 correctness closure（ADR-023 Amendment C；CR-3.2 复审 2 P0 + 3 P1 全收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3.2 复审（2026-09-02 06:56 +08:00，Reviewed HEAD `9ffdf35f577e48ec4de1432057d954da07f78db0`，Primary implementation `df409ede0ddb25ce5cee12a46fa66fe7a3ea093f`，裁决 **REOPENED**——16 项机制 PASS / FREEZE；P0-01：CR-2 ledger 输入消失 / status 或 seal identity 漂移改变 current base identity 绕过 prior SUCCESS degradation guard（可能 mint 新 BLOCKED 甚至新 SUCCESS truth）；P0-02：verification_state_hash 只封 verification 枚举不封具体 problem evidence——同错误大类内 cause 变化（anchor missing → anchor hash mismatch）replay stale BLOCKED finding；P1-01：source-scope finding canonical_domain="source" 非真实 domain；P1-02：damaged source 追加误导性 UNAVAILABLE_AT_ASOF；P1-03：治理文档 InputRunSeal "19 fields" 实际 20；工作要求 `docs/design/A-share-analysis_CR-3.2复审与CR-3.3最终HistoricalInputContinuity及VerificationEvidence收口要求_20260902.md`，reopen commit `9ec2fca`）。  
**New Contract**（ADR-023 Amendment C §8.1-§8.3）：（1）**P0-01 Historical Input Continuity Guard**：migration 021 `canonical_context_hash`（requested domain set + as_of + contract + 三 policy identities + identity bridge policy identity + canonical code fingerprint——刻意不含 current CR-2 input set / verification state）；`_check_historical_continuity`：查同 context 全部历史非 BLOCKED run，对每个 prior 的 sealed input set 逐 run 检查（ledger 存在性 / ledger identity == prior sealed identity（status + 全部 seal 字段）/ physical + anchored verification 仍健康 / 健康的 prior input 必在 current snapshot discovery）；disappearance / drift / degradation → DAMAGED（不 mint 任何 replacement）；合法新增（prior inputs 全部完整 + current superset）→ 正常新 run；exact restoration → 历史 SUCCESS exact replay；identity master 同规则。（2）**P0-02 Verification Evidence Exactness**：`InputRunSeal.verification_problem_hash`（canonical sorted problem evidence：run_id + verification class + closure problems + anchored-evidence problems + materialization problems）；base identity 不含（identity_dict 排除）；verification state（run_id + class + problem hash）/ manifest input seal / input_seal_hash 均含；同 INVALID class + 不同 cause → 新 BLOCKED evidence run（prior BLOCKED 保留 append-only，finding detail 反映真实当前 cause）；exact same failure → idempotent replay；INVALID → HEALTHY → recovery run；replay sealed-input 验证分流（HEALTHY 要求仍健康；INVALID 要求当前 problem evidence == sealed problem hash）。（3）**P1-01**：source-scope findings 用 reserved scope `input:<normalization_surface>` + detail seal `affected_domains` exact set（shared surface 双域）。（4）**P1-02**：finding precedence 三分支（no discovered → MISSING；discovered but damaged → 仅 closure/evidence finding；healthy but all future → UNAVAILABLE）。（5）**P1-03**：seal count correction 19→20→21（identity_dict 17）；测试机械断言 exact set。  
**Schema**：migration 021（canonical_context_hash 列；未改 018/019/020；21 链 from-zero + 020→021 upgrade + idempotent + tamper probe 022）  
**Affected Modules**：`src/ashare_state/canonical/canonicalizer.py`（continuity guard + problem hash + finding scope/precedence + replay 分流）、`migrations/021_canonical_context_hash.sql`、`tests/integration/test_canonical.py`（131 项 = 111 回归 + 20 新增）、`tests/integration/test_migrations.py`（21 链）、`docs/adr/ADR-023`（Amendment C）、`docs/adr/ADR-000`（索引）  
**Tests**：1116/0（1096 → 1116，+20：TestHistoricalInputContinuity 11 / TestVerificationEvidenceState 4 / TestFindingTruthfulness 4 / TestSealFieldCountCorrection 1）  
**Verification**：Local 1116/0；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33581493160（implementation `f8b80b3212ff299f52ee3fb0308c248fd16c17df`）三腿 success**（2026-09-02 API positive confirmation，一次通过零修复轮次）  
**Commit**：`f8b80b3212ff299f52ee3fb0308c248fd16c17df`（CR-3.3 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260901-070 — CR-3.2 Transactional Snapshot + Identity Master PIT + Honest Policy Execution + Full Seal + Verification-State Transition

**Type**：C3 correctness closure（ADR-023 Amendment B；CR-3.1 复审 5 P0 + 3 P1 全收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3.1 复审（2026-09-01 21:08 +08:00，Reviewed HEAD `bd3bcad6aa3e55580cfd03943c4c52f3a31efd0a`，Primary implementation `75744aaa89487aae09474b3569519a73f0efba24`，裁决 **REOPENED**——19 项机制 PASS / FREEZE；P0：snapshot 无真实 DB transaction boundary（多次独立 SELECT，race 下混入多时刻世界）+ 验证后 `_read_output_rows` 重读当前 DB/path（TOCTOU：identity seal=S1 但 consumed rows=S2）+ frozen 非深层 immutable / identity master 无 PIT 过滤与 anchor 验证（future leakage + first/replay 不对称——刚创建的 SUCCESS 无法通过自己的 replay verifier）/ policy hash 全字段但 runtime 未诚实消费（required_evidence_class 等六字段声明与执行脱节）/ manifest 显式 provenance 字段（identity_master_input_set_hash / bridge policy version+hash / required_evidence_classes）写入但 replay 不消费 + input entry 未封完整 CR-2 seal（contract version / mapper code hash / output set / semantic hash / status 缺失）+ manifest_uri 未 deterministic verify / verification state 不参与 replay 状态转换（上游修复后永久 replay 旧 BLOCKED；SUCCESS 退化需 fail closed）；P1：deep immutability / shared surface 去重 / domains=[] truthiness；工作要求 `docs/design/A-share-analysis_CR-3.1复审与CR-3.2最终TransactionalSnapshot及PolicyExecution收口要求_20260901.md`，reopen commit `a3f181a`）。  
**New Contract**（ADR-023 Amendment B §7.1-§7.5）：（1）**P0-01 Transactional Materialized Snapshot**：`_build_snapshot` 用 `BEGIN TRANSACTION`（MVCC boundary——第一个 authoritative broad SELECT 之前）包裹全部发现；surface 去重（`_surface_plan`：同一 surface union datasets 一次查询，多 domain 共享不重复发现）；逐 run closure+anchor verify 后**物化 exact sealed bytes**（`_materialize_outputs`：读 bytes → hash == manifest content_hash → parse 同一份 bytes → 深冻结行为 tuple of sorted item-tuples）；candidate builder 只消费 `SnapshotRun.outputs`（绝不重查当前 ledger path / 重读当前文件）；深不可变 typed records（`InputRunSeal` / `SnapshotRun` / `MaterializedOutput` / `CanonicalFinding` frozen dataclasses）；race 测试用第二 connection 在 broad reads 之间真实 commit（file-backed DuckDB MVCC）。（2）**P0-02 Identity Master PIT**：master 与 source 同规则——`_verify_anchored_availability` + `received_at <= as_of` 才进 IdentityBridge（`available_master_rows`）；future master 留 discovery evidence（input seal `pit_available=false`）；typed findings `IDENTITY_DATASET_MISSING` / `IDENTITY_DATASET_UNAVAILABLE_AT_ASOF` / `IDENTITY_EVIDENCE_INVALID`；first/replay 对称；`identity_master_input_set_hash` = available masters set。（3）**P0-03 Honest Policy Execution**：`_assert_policy_honestly_executed` 扩展为 supported-value guard（required_evidence_class==PROVIDER_NORMALIZED_VERIFIED / reconciliation==SINGLE_SOURCE_EXACT / tolerance exact-v1@1 / conflict_action==BLOCK / fallback 空 / partial False——任何不支持值在 canonical run 之前 raise）。（4）**P0-04 Full Seal**：`InputRunSeal` typed full CR-2 seal（19 字段含 contract version / mapper identity+code hash / manifest uri+hash / output_set+semantic hash / status / raw identity / verification / received_at / pit_available）；`input_seal_hash` 三方（snapshot == manifest == ledger）；manifest 显式 provenance 全消费（identity_master_input_set_hash / bridge policy version+hash / required_evidence_classes == current policy）；manifest_uri deterministic verify；replay sealed-input 验证 seal-based（`_verify_sealed_input`：用 seal 字段直接验 files——manifest bytes / outputs content+schema+row_count / CR-2 manifest 自身 seal字段 == typed seal / raw meta + anchor——不依赖 current DB row）。（5）**P0-05 Verification-State Transition**：run identity = base identity（`base_identity_hash`：requested set + identity seal entries + identity hash + as_of + contract + policies + fingerprint——**不含 state**）+ `verification_state_hash`（每 discovered run verification outcome）；degraded-SUCCESS guard（同 base 存在非 BLOCKED 历史 + 当前 state damaged → DAMAGED raise，不 mint replacement）；BLOCKED 可恢复 + exact repair → state hash 变 → 新 deterministic run id（recovery run；历史 BLOCKED 证据 append-only 保留）；`input_set_hash` 只含 identity 字段（`InputRunSeal.identity_dict()`——state 字段绝不进 base identity）。（6）**P1**：深不可变；surface 去重；`domains=[]` 显式 reject。  
**Schema**：migration 020（base_identity_hash / verification_state_hash / input_seal_hash / identity_master_input_set_hash 四列；未改 018/019；20 链 from-zero + 019→020 upgrade + idempotent + tamper probe 021）  
**Affected Modules**：`src/ashare_state/canonical/canonicalizer.py`（transactional snapshot + materialization + typed records + state transition + full seal 重构）、`migrations/020_canonical_full_seal.sql`、`tests/integration/test_canonical.py`（111 项 = 81 回归 + 30 新增）、`tests/integration/test_migrations.py`（20 链）、`docs/adr/ADR-023`（Amendment B）、`docs/adr/ADR-000`（索引）  
**Tests**：1096/0（1066 → 1096，+30：TestTransactionalSnapshot 6 / TestIdentityMasterPIT 6 / TestHonestPolicyExecution 8 / TestFullSealConsumption 7 / TestVerificationStateTransition 3）  
**Verification**：Local 1096/0；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33521594830（implementation `df409ede0ddb25ce5cee12a46fa66fe7a3ea093f`）三腿 success**（2026-09-01 API positive confirmation，一次通过零修复轮次）  
**Commit**：`df409ede0ddb25ce5cee12a46fa66fe7a3ea093f`（CR-3.2 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260901-069 — CR-3.1 Canonical Input Snapshot + Anchored Availability Evidence + Full Replay Seal + Recoverable Commit

**Type**：C3 correctness closure（ADR-023 Amendment A；CR-3 复审 8 P0 + 3 P1 全收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-3 复审（2026-09-01 19:06 +08:00，Reviewed HEAD `e1c6bb2236a1b0eac06ee214b7cf64cf4fe13f79`，Primary implementation `ae5b76c998196f936ae6430408d2a016a35aec0d`，裁决 **REOPENED**——主体架构 PASS / FREEZE（18 项冻结清单）；P0：requested domain set 未进 identity / future-only 可 false SUCCESS / 无 authoritative snapshot（read-race）/ received_at 未验 anchor（PIT trust-root）/ identity policy hash 口径不一致 / policy hash 漏字段 / replay full seal 未消费 / findings wall-clock 不可恢复；P1：identity finding 域错标 / domain 计数 12→13 / naive datetime；工作要求 `docs/design/A-share-analysis_CR-3复审与CR-3.1最终CanonicalInputSnapshot及ReplaySeal收口要求_20260901.md`，reopen commit `f720447`）。  
**New Contract**（ADR-023 Amendment A §6.1-§6.8 + P1）：（1）**P0-01 RequestedDomainSet identity**：请求域去重排序 exact set + canonical hash 进 run identity；migration 019 `requested_domains_json/hash`；manifest 显式绑定；replay domains 来自 ledger seal；不同 set 不同 run / 同 set 异序同 run / 重复域去重。（2）**P0-02 availability completeness**：无 eligible verified run → `REQUIRED_DOMAIN_MISSING`；有 eligible 但零 PIT-available → `REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF`（均 blocking）；EXCLUDED_FUTURE decisions 留证；future-only 永不 SUCCESS；新增 future run 不改早期 selected 真值（仅 input identity 变化）。（3）**P0-03 CanonicalInputSnapshot**：typed immutable dataclass 一次性解析（requested set + discovered source/master run exact set + closure/anchor 验证结果 + policy identities + fingerprint）；run identity/candidates/manifest/ledger 全部派生自 snapshot（无重复 broad query）；**discovered set 含验证失败 run**（blocking prefinding 诚实记录；post-success tamper 表现为 DAMAGED replay 而非新 identity）；mid-run 插入仅下一次 invocation 可见；测试经 `_build_snapshot` monkeypatch 注入 race（production 无 hook）。（4）**P0-04 AnchoredAvailabilityEvidence**：读 received_at 前证明 raw meta exact-byte SHA-256 == run sealed raw_evidence_hash == anchor.evidence_hash + cross-bind provider/dataset/request/uri/endpoint/surface/operation_id（三方）；失败 → `AVAILABILITY_EVIDENCE_INVALID` blocking；replay 对 sealed source runs 重验。（5）**P0-05 identity binding 统一**：`identity_dataset_hash = hash(master_input_set_hash, bridge_policy_version, bridge_policy_hash)` 唯一口径进 identity/manifest/ledger；bridge policy 变更新 run；三方比对。（6）**P0-06 policy hash 全字段**：asdict + sorted canonical JSON；runtime 诚实消费（fallback/partial 声明无支持 → raise；identity_missing_max per-domain vs 阈值；required_evidence_classes 进 manifest）。（7）**P0-07 full replay seal**：CURRENT snapshot == ledger == manifest == physical recompute（selected_semantic_hash/decision_set_hash/finding_set_hash/artifact exact set/deterministic URI/schema recompute/row_count/findings parquet↔DB exact-set）+ CR-2 source closure + anchor re-verify；rebind 矩阵全拦截。（8）**P0-08 recoverable commit**：findings.parquet 无 wall-clock（uuid5 id；created_at 仅 DB audit metadata 排除出 semantic hash）；DB 注入失败 → exact retry byte-identical no-op → ledger 补提交（BLOCKED-with-findings 热路径测试）。（9）**P1**：identity finding 真实 domain；matrix 计数更正 13（5/2/6，ADR-023 §2.4 原文 12/5 追加更正保留历史）；naive datetime 拒绝 + naive string 固定 UTC 规则。  
**Schema**：migration 019（requested_domains_json/hash + selected_semantic_hash + decision_set_hash 四列；未改 018；19 链 from-zero + 018→019 upgrade + idempotent + tamper probe 020）  
**Affected Modules**：`src/ashare_state/canonical/canonicalizer.py`（CanonicalInputSnapshot + anchored evidence + full seal + recoverable commit 重构）、`identity.py`（identity_bridge_policy_version/hash + identity_dataset_hash 统一口径 + master_input_set_hash 构造）、`source_policy.py`（全字段 canonical hash + tolerance canonical JSON）、`migrations/019_canonical_replay_seal.sql`、`tests/integration/test_canonical.py`（81 项 = 40 回归 + 41 新增）、`tests/integration/test_migrations.py`（19 链）、`docs/adr/ADR-023`（Amendment A + §2.4 计数更正）、`docs/adr/ADR-000`（索引）  
**Tests**：1066/0（1025 → 1066，+41：TestRequestedDomainIdentity 6 / TestAvailabilityCompleteness 3 / TestInputSnapshot 3 / TestAnchoredAvailabilityEvidence 6 / TestIdentityPolicyBinding 4 / TestPolicyHashCompleteness 6 / TestFullReplaySeal 7 / TestRecoverableCommit 2 / TestP1Corrections 4）  
**Verification**：Local 1066/0；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33508307611（implementation `75744aaa89487aae09474b3569519a73f0efba24`）三腿 success**（2026-09-01 API positive confirmation，一次通过零修复轮次）  
**Commit**：`75744aaa89487aae09474b3569519a73f0efba24`（CR-3.1 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260901-068 — CR-3 AvailabilityPolicy + Canonicalizer Runtime（含 ADR-022 ACCEPTED 治理同步 + CR-2.4 P1 guard 加固）

**Type**：C3 正式批次（ADR-023 PROPOSED；CR-3 runtime 全量交付）+ 治理真相同步（Reviewer 最终裁决）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-2.4 最终复审（2026-09-01 17:06 +08:00，Reviewed HEAD `0b4ef7a1c91c896054501853adf40324ba3687fc`，裁决 **CR-2 / CR-2.1 / CR-2.2 / CR-2.3 / CR-2.4 全链 VERIFIED / CLOSED / FREEZE；ADR-022 REVIEWER ACCEPTED；CR-3 START / ACTIVE NEXT；CR-4 BLOCKED_BY_CR-3**；P1 非阻塞：RawWriter AST guard alias-tracking 加强于 CR-3 首批完成；工作要求 `docs/design/A-share-analysis_CR-2.4最终复审结论与CR-3_AvailabilityPolicy_Canonicalizer开发工作要求_20260901.md`，closure commit `cfa5940`）。  
**Governance Sync（工作要求 §10，本批完成）**：ADR-022 Status → **ACCEPTED**（正文头部 + Reviewer 裁决引文）；ADR-000 index ADR-022 → ACCEPTED + VERIFIED 2026-09-01；ADR-023 新建（PROPOSED）；DEVLOG 追加 Reviewer closure + 本批条目；总册头部 / §40 / §41 / §44 / §61 同步；CR-2.4 P1 AST guard 技术债登记并**本批闭环**。  
**New Contract**（ADR-023 §2）：（1）**P0-01/02 唯一输入 + eligibility**：`CanonicalRunner.run(as_of, domains=...)` 唯一正式边界；输入仅 CR-2 verified Provider-Normalized（SUCCESS only；PARTIAL 默认 NOT eligible——v1 全部 domain partial_run_allowed=False；BLOCKED NEVER）；消费前逐 run `verify_normalized_run`（normalization/runner.py 新公开只读 closure verifier：manifest bytes / output content+schema+row_count / quarantine exact set / typed seal vs current provenance）——problem → CLOSURE_VERIFICATION_FAILED blocking。（2）**P0-03/04 AvailabilityPolicy**：available_at 唯一 basis = OBSERVED_AT_INGEST（raw envelope received_at——PIT 保守）；typed 四分类中仅 OBSERVED_AT_INGEST 注册；as_of 过滤在 selection 之前（EXCLUDED_FUTURE decision 留证）；policy 版本 availability-v1 + hash 进 run identity。（3）**P0-05/06 Identity fail closed**：IdentityBridge 从 CR-2 verified security_master（code_list/hist_code_list/stock_basic 三 dataset 全集）经 ADR-002 resolve_security_identity 构建；exchange 归属仅来自 provider market 后缀；裸码唯一市场匹配（歧义 fail closed）；PIT relist（list_date <= trade_date 最新）；missing/ambiguous → IDENTITY_MISSING blocking（identity_missing_max=0）+ 行排除；natural keys 静态 typed；Domain eligibility matrix 12 项显式（5 CANONICAL_SUPPORTED / 2 AUXILIARY_ONLY：security_master identity dataset + ca_projection STATUS_FLAG_PROJECTION tier / 5 BLOCKED_PENDING_SEMANTICS：corporate_action direct、index_daily、industry_member、equity_structure、bj_code_mapping、industry_taxonomy_definition）；非 SUPPORTED domain 调用即 raise。（4）**P0-07..09 SourcePolicy 静态版本化**：CanonicalSourcePolicy registry（source-policy-v1；priority/fallback 空/partial False/SINGLE_SOURCE_EXACT/exact-v1/conflict BLOCK/identity_missing_max 0）；caller 零注入面；不可用首选 → REQUIRED_DOMAIN_MISSING blocking；同 key EXACT 比较——等值 EQUIVALENT_MERGED decision + deterministic winner（(priority, manifest hash, ordinal)），不等值 SOURCE_CONFLICT blocking，同 output 重复 key DUPLICATE_CANONICAL_KEY blocking（无 last-write-wins / keep-first / silent dedupe）。（5）**P0-10 lineage**：canonical row 绑定 12+ 字段（source run/output/row ordinal + row identity hash/raw request/evidence hash/mapper identity/policy versions/availability basis）。（6）**P0-12 无硬编码制度事实**：AST guard。（7）**P0-13..15 artifacts + identity + 状态机**：canonical/contract/as_of/run 布局（selected/decisions/findings parquet + manifest LAST 无墙钟 immutable）；manifest 封 input run exact set + input_set_hash + identity_dataset_hash（bridge dataset + policy）+ 三 policy version/hash + canonicalizer code fingerprint（五模块源码 SHA-256 行尾归一）+ artifact seals + selected_semantic_hash + finding_set_hash；run identity = uuid5(sha256(input_set + identity_hash + as_of + contract + 三 policy identity + fingerprint))——历史 exact replay（三方 seal closure 复验；篡改 fail closed）；migration 018 ledger 单事务（dup 检查 + finding 行数断言）；SUCCESS/BLOCKED 状态机（PARTIAL 仅 policy 允许）。（8）**P1 guard 加固**：`_scan_unanchored_writes` 升级——alias 赋值（`rw = RawWriter(...); rw.write(...)`）与直接构造调用（`RawWriter(...).write(...)`）双形态跟踪；构造白名单 = raw_writer.py / raw_anchor.py + normalization/runner.py（read-only reader 无 write 豁免）；negative fixtures + production 全树零违规。  
**Schema**：migration 018（meta_canonicalization_run 24 列 + meta_canonical_reconciliation_finding 10 列；未改旧文件；18 链 from-zero + 001..017→018 upgrade + idempotent + tamper probe 019）  
**Affected Modules**：`src/ashare_state/canonical/`（新包 5 模块：canonicalizer.py / eligibility.py / availability.py / source_policy.py / identity.py）、`src/ashare_state/normalization/runner.py`（公开只读 verify_normalized_run）、`migrations/018_canonicalization.sql`、`tests/integration/test_canonical.py`（36 项）、`tests/integration/test_migrations.py`（18 链）、`docs/adr/ADR-022`（ACCEPTED）、`docs/adr/ADR-023`（新建 PROPOSED）、`docs/adr/ADR-000`（索引）  
**Tests**：1025/0（985 → 1025，+40：TestBoundaryStructure 4 / TestClosureVerification 2 / TestAvailability 4 / TestIdentityResolution 3 / TestSelection 7 / TestRunIdentity 5 / TestDomainMatrix 6 / TestLedgerAndArtifacts 3 + TestRawWriterGuardHardening 4——36 canonical + 4 guard 重构计入）  
**Verification**：Local 1025/0；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33498314119（implementation `ae5b76c998196f936ae6430408d2a016a35aec0d`）三腿 success**（2026-09-01 API positive confirmation，一次通过零修复轮次）  
**Commit**：`ae5b76c998196f936ae6430408d2a016a35aec0d`（CR-3 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260901-067 — CR-2.4 Anchored Raw Ingestion Boundary

**Type**：C2 correctness wiring（ADR-022 Amendment D；CR-2.3 复审唯一剩余 P0 收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-2.3 复审（2026-09-01 14:26 +08:00，Reviewed HEAD `81d6b8d53a97cdcc7ee1cdfbd627d4dac2913e4d`，裁决 **REOPENED（仅剩 Anchored Ingestion Boundary wiring / enrollment correctness）**——operation spec / anchor schema+runner verification / output-set+semantic seal PASS / FREEZE；P0：正式 Raw evidence 写入链（ProbeContext.evidence_from_exchange）未接线 anchor（测试靠 helper 手工模拟 governed flow）/ recorder 只 hash "调用时看到的 meta" 未绑定 RawWriter 刚返回的 exact evidence hash（write→anchor TOCTOU / late-enrollment blessing 窗口）/ enrollment 是普通可调用 primitive 未收口；工作要求 `docs/design/A-share-analysis_CR-2.3复审与CR-2.4最终AnchoredIngestionBoundary收口要求_20260901.md`，reopen commit `3348200`）。  
**New Contract**（ADR-022 Amendment D §9.1-§9.4）：（1）**AnchoredRawEvidenceWriter**（`raw_anchor.py`）：唯一 production-owned 写入边界 `write_exchange(exchange)`——RawWriter.write（文件 commit，meta LAST）→ reread persisted meta bytes（VERIFY-ONLY：require sha256(reread) == RawWriteResult.evidence_hash；TOCTOU 换字节 → 整体 HARD FAIL，H2 永不 enroll）→ identity cross-binding（meta 的 request_id/provider/provider_dataset/endpoint/normalization_surface/operation_id == exchange envelope + uri cross-binding）→ enroll immutable anchor（keyed to COMMIT identity）；任何失败 = evidence 不 ready。（2）**全部 production evidence 写入接线**：`ProbeContext.__init__` 新增必需 `conn` 参数，`raw_writer` → `AnchoredRawEvidenceWriter`（SUCCESS 与 ERROR exchange 均自动 anchor）；`run_dry_run` 打开 in-memory migrated DB（repo migrations 全链）——框架自检走与 production 完全相同的 anchored 写路径；结构守卫（AST）：src/ 中 RawWriter write/write_success/write_failure 调用点只允许 raw_writer.py（定义）与 raw_anchor.py（boundary 内部），reader 不受限。（3）**Enrollment 可恢复不可 rebaseline**：anchor INSERT 注入失败 → ingest 失败（raw bytes H1 在盘无 anchor → Normalization RAW_ANCHOR_MISSING）；exact retry：RawWriter idempotent（same bytes ignoring ingested_at → no-op → evidence_hash = 首 commit H1）→ enrollment 成功 → 一个 immutable anchor、单一 evidence identity；已有 anchor H1：same H1 idempotent / H2 hard conflict。（4）**API 收口**：公开 `record_raw_evidence_anchor` 撤销，私有化 `_enroll_anchor`（evidence_hash 为必填调用方声明 commit identity，函数内 verify-only 比对磁盘）；公开面仅 AnchoredRawEvidenceWriter / persist_exchange_with_anchor / lookup_raw_evidence_anchor / RawEvidenceAnchor / RawAnchorError；tests 用私有 primitive 制造夹具（B2 static registry 同口径）。  
**Schema**：无（复用 migration 017 anchor 表）  
**Affected Modules**：`src/ashare_state/storage/raw_anchor.py`（AnchoredRawEvidenceWriter + 私有 _enroll_anchor + 公开 recorder 撤销）、`src/ashare_state/spike/probes.py`（ProbeContext conn 参数 + anchored writer 接线）、`src/ashare_state/spike/runner.py`（run_dry_run in-memory DB + migrations）、`tests/integration/_anchored_ctx.py`（新共享 helper）、11 个 spike 测试文件 + test_formal_gate_wiring + test_endpoint_requirement_proof + test_cr11（ProbeContext conn 接线）、`tests/integration/test_provider_normalization.py`（114 项：私有 enrollment 夹具迁移 + 10 新增）、`docs/adr/ADR-022`（Amendment D）  
**Tests**：985/0（975 → 985，+10：TestAnchoredIngestionBoundary 10 项）  
**Verification**：Local 985/0；ruff check / ruff format / mypy 全绿（63 文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33482144065（implementation `3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc`）三腿 success**（2026-09-01 API positive confirmation，一次通过零修复轮次）  
**Commit**：`3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc`（CR-2.4 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260901-066 — CR-2.3 Raw Trust Anchor + Provider-Owned Operation Spec + Output Seal

**Type**：C2 correctness closure（ADR-022 Amendment C；CR-2.2 复审 3 P0 全收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-2.2 复审（2026-09-01 10:45 +08:00，Reviewed HEAD `a4a23cd3f758a6cdc450b4256f1d66172ba3524c`，裁决 **REOPENED**——exact replay / full fingerprint / schema verify 等 FREEZE，3 P0：surface provenance 仍经 public `require_capability` 间接 caller-declared / 首次消费的 raw meta 无文件系统之外 authoritative anchor（首消费 meta-only 篡改可成"初始真相"；016 legacy 无法安全识别 015-era laundering）/ seal 未封住 expected output exact set 与 normalized semantic values（删 output 重绑双 hash 可过；同 schema/row_count 换值重绑可过）；工作要求 `docs/design/A-share-analysis_CR-2.2复审与CR-2.3最终RawTrustAnchor及OutputSeal收口要求_20260901.md`，reopen commit `323bbb5`）。  
**New Contract**（ADR-022 Amendment C §8.1-§8.3）：（1）**P0-01 Provider-Owned Operation Spec**：新 `operations.py`——`ProviderOperationSpec`（operation_id/capability/endpoint/provider_dataset/normalization_surface）私有静态常量 15 个（每 facade wrapper 一个）；`call_exchange`/`_call_or_exchange` 撤销，generic executor 私有化为 `_execute_exchange(spec, fn, params)`（endpoint/dataset/capability/surface/operation_id 全由 spec 派生）；`query_kline_exchange`→`DAILY_BAR_KLINE`、`query_index_kline_exchange`→`INDEX_DAILY_KLINE`（AST 绑定断言）；RawEnvelope/raw meta 新增 `operation_id`；结构守卫：15 spec 与 `SDK_METHOD_CLASSIFICATIONS` + normalization registry 双向 exact 核对；公开方法签名无任何 free-form correctness selector（endpoint/dataset/require_capability/capability/normalization_surface/spec）。（2）**P0-02 Raw Evidence Trust Anchor**：migration 017 `meta_raw_evidence_anchor`（PK (provider, dataset, request_id) + evidence_uri/evidence_hash/endpoint/operation_id/normalization_surface/payload_kind/ingest_run_id/created_at）；`raw_anchor.py::record_raw_evidence_anchor`（governed ingestion flow：RawWriter commit meta LAST → reread bytes → sha256 → anchor；同 bytes 幂等 / 异 bytes `RawAnchorError` hard fail——anchor 永不 re-baseline）+ `lookup_raw_evidence_anchor`；Runner 在任何 meta 解析/路由/映射之前查 anchor——缺失（legacy pre-017）→ `RAW_ANCHOR_MISSING` BLOCKED（fail closed；governed repair = re-ingest；绝不 auto-grandfather——015-era H1+H2 history 升级后 H2 永不被信任，且失败运行不自动建 anchor）/ current hash ≠ anchor → `RAW_ANCHOR_MISMATCH` INCIDENT HARD BLOCK（`evidence_conflict=TRUE` 仅诊断——016 列降级为诊断属性；信任根是 anchor：重复运行永续 BLOCK、修复回原 bytes → 原 run exact replay）；旧 baseline DISTINCT-hash 查询删除。（3）**P0-03 Expected Output Exact Set + Semantic Value Seal**：migration 017 ledger 两列 `normalized_output_set_hash` / `normalized_semantic_hash`；output_set_hash = hash(sorted(output_name, canonical uri, content_hash, schema_hash, row_count)) 三方消费（ledger == manifest == replay-time 物理重算）；semantic_hash（全输出表 sorted canonical JSON）三方消费（ledger == manifest == replay-time 从物理 parquet records 重算）；expected exact set（manifest output_name set == CURRENT registry spec.output_names，no missing/extra/duplicate）；URI deterministic binding（每 output uri == ledger 身份重算 base_path + output_name）；物化语义升级（materialized set 恰好等于 spec.output_names——空表物化为空 parquet 零产出证据，empty-payload SUCCESS 测试）；`NormalizationRunSeal` 扩展 raw_evidence_uri/raw_payload_kind/normalized_output_set_hash/normalized_semantic_hash；manifest 新增 raw_payload_kind/output_set_hash；pre-CR-2.3 行缺 seal 不作 healthy replay。  
**Schema**：migration 017（anchor 表 + 两 seal 列；未改 014/015/016；17 链 from-zero + 001..016→017 upgrade + idempotent + tamper probe 018）  
**Affected Modules**：`src/ashare_state/providers/amazingdata/operations.py`（新）、`provider.py`（spec 化 executor + 15 wrapper 重构 + RawEnvelope.operation_id）、`src/ashare_state/storage/raw_anchor.py`（新）、`raw_writer.py`（meta 持久化 operation_id）、`src/ashare_state/normalization/runner.py`（anchor 验证 + exact-set/semantic seal + seal 扩展）、`registry.py`（RAW_ANCHOR_MISSING/MISMATCH 错误类）、`migrations/017_raw_trust_anchor_and_output_seal.sql`、`tests/integration/test_provider_normalization.py`（104 项）、`tests/integration/test_migrations.py`（17 链）、`tests/integration/test_cr1_provider_exchange.py` / `test_runtime_early_stop.py` / `tests/unit/test_provider_reliability.py`（call_exchange → 私有 _execute_exchange + 测试 spec）、`docs/adr/ADR-022`（Amendment C）  
**Tests**：975/0（955 → 975，+20：TestOperationSpecProvenance 3 / TestRawTrustAnchor 6 / TestOutputExactSetSeal 6 / TestSemanticValueSeal 4 / 公开签名守卫重构 1）  
**Verification**：Local 975/0；ruff check / ruff format / mypy 全绿（63 文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33472357951（implementation `480dc7549bb512e9c187213e5010fab424248774`）三腿 success**（2026-09-01 API positive confirmation，一次通过零修复轮次）  
**Commit**：`480dc7549bb512e9c187213e5010fab424248774`（CR-2.3 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-20260901-065 — CR-2.2 Replay Provenance Seal

**Type**：C2 correctness closure（ADR-022 Amendment B；CR-2.1 复审 3 P0 全收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-2.1 复审（2026-09-01 10:15 +08:00，Reviewed HEAD `70bb1018e8445a3b9d2b5897f3f0b4a4260cb0a`，裁决 **REOPENED**——收口方向保留，3 P0：surface provenance caller-override 参数 / raw hash conflict 可被 BLOCK 记录洗白 + latest-run replay 遮蔽历史 exact match / seal 只验外层文件 hash 不比对全量字段与 current fingerprint；工作要求 `docs/design/A-share-analysis_CR-2.1复审与CR-2.2最终ReplayProvenanceSeal收口要求_20260901.md`）。  
**New Contract**（ADR-022 Amendment B §7.1-§7.3）：（1）**P0-01 Surface 真正 system-derived**：撤销 `call_exchange` 的 `normalization_surface` caller-override 参数；`surface_identity = str(require_capability or "")`（capability 契约派生）；`query_kline_exchange`（capability=daily_bar）与 `query_index_kline_exchange`（capability=index_daily）仅靠 capability 区分；registry 18 条映射不变（surface 值等于 capability 名，零数据迁移）；结构测试断言签名无该参数 + provider.py 全部 `_call_or_exchange` 调用点无该 kwarg + 派生表达式。（2）**P0-02 Raw Evidence Binding 冲突不可洗白 + 全历史 exact replay**：baseline = 该 request 全部非 conflict run 的 DISTINCT `raw_evidence_hash`（`evidence_conflict=TRUE` 的 run 排除，migration 016 新列）；current hash 不在 baseline（且非空）→ INCIDENT HARD BLOCK（conflict run 记录、不改变 baseline；第二/三次运行同样 BLOCK；conflict run 自身按 exact key 幂等 replay）；surface 篡改（meta surface 字段改 index_daily）→ bytes 变 → conflict BLOCK 永续；修复回原始 bytes → 原 run exact replay；exact replay lookup 改为 `run_id = uuid5(namespace, idempotency_key)` 直接查询（不再 latest-run ORDER BY 比较）——mapper A→B→A / contract A→B→A rollback replay 历史 A run（无 duplicate-PK、无 B 阴影）；全部 blocked 分支（含 multi-table / accounting violation）统一 exact lookup。（3）**P0-03 Full Seal 消费**：`_supported_key`/`_blocked_key` 混入完整 `MAPPER_CODE_FINGERPRINT`（64 hex，显示串仍 16 hex）——前 16 位相同的 fingerprint 产生不同 run identity；typed `NormalizationRunSeal` dataclass（`from_ledger()` / `current_provenance_problems()`：ledger == 当前 contract + 当前 full fingerprint，defense in depth / `manifest_binding_problems()`：manifest 全语义字段 == ledger seal + quarantine 三方绑定 manifest == ledger == DB recompute）；manifest policy typed 化（SUCCESS/PARTIAL manifest REQUIRED——ledger status 翻转伪造不出 manifest-free healthy replay；BLOCKED 携带即验证）；schema_hash 重算（replay 从物理 parquet 重算 `sha256(str(frame.schema))` 与 manifest 比对——rebind 换 parquet + 更新 content_hash 仍被拦截）；rebind tamper 矩阵 10 项全落地（manifest surface/status/counts/quarantine_set_hash/mapper_code_hash 篡改 + 重算外层 hash + UPDATE ledger hash → DAMAGED；ledger status/quarantine seal/mapper_code_hash 篡改 → DAMAGED；output schema 换绑 → DAMAGED）。  
**Schema**：migration 016（meta_provider_normalization_run + `evidence_conflict BOOLEAN DEFAULT FALSE`；未改 014/015；16 链 from-zero + upgrade（001..015 先应用再补 016 仅应用尾部）+ idempotent + tamper 测试）  
**Affected Modules**：`src/ashare_state/providers/amazingdata/provider.py`（撤销 surface override 参数 + capability 派生）、`src/ashare_state/normalization/runner.py`（baseline conflict check + exact run_id lookup + typed seal + schema_hash recompute + evidence_conflict 传递）、`src/ashare_state/normalization/__init__.py`（导出 NormalizationRunSeal）、`migrations/016_replay_provenance_seal.sql`、`tests/integration/test_provider_normalization.py`（84 项 = 67 回归 + 17 新增）、`tests/integration/test_migrations.py`（16 链 + upgrade + probe 017）、`docs/adr/ADR-022`（Amendment B）  
**Tests**：955/0（938 → 955，+17：TestRawEvidenceBindingPermanence 5 项 / TestFullMapperIdentity 1 项 / TestFullSealConsumption 10 项 / 结构签名测试 1 项）  
**Verification**：Local 955/0（938 → 955，+17）；ruff check / ruff format / mypy 全绿（61 文件零错）；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33460094366（implementation `a06ea2202cb4f7a5ea0a91c09e666867267a8575`）三腿 success**（2026-09-01 API positive confirmation，一次通过零修复轮次）  
**Commit**：`a06ea2202cb4f7a5ea0a91c09e666867267a8575`（CR-2.2 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260831-064 — CR-2.1 Surface Identity + Registry Boundary + Full-State Replay + Atomic Commit Closure

**Type**：C2 correctness closure（ADR-022 Amendment A；CR-2 复审 4 P0 全收口）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-2 复审（2026-08-31 17:42 +08:00，Reviewed HEAD `ab20871e9eb207563d0fdeb6228a08416153e2c9`，裁决 **REOPENED**——core framework FREEZE，4 P0：surface identity 冲突 / 公开可变 registry / happy-path-only 幂等 / 无原子提交协议；工作要求 `docs/design/A-share-analysis_CR-2复审与CR-2.1最终SurfaceIdentity及CommitClosure收口要求_20260831.md`）。  
**New Contract**（ADR-022 Amendment A）：（1）**P0-01 Surface Identity**：registry key 升级 typed 四元组 `(provider, normalization_surface, provider_dataset, endpoint)`；`normalization_surface` 为 system-derived 持久化身份（provider facade `call_exchange` 派生默认 capability 身份 → RawWriter 写入 raw meta 向后兼容字段；禁止 request 参数/symbol 前缀猜测）；`query_kline_exchange`（daily_bar → DailyBarDTO）与 `query_index_kline_exchange`（index_daily → IndexDailyDTO）双显式 wrapper；legacy 歧义 raw → `PAYLOAD_SURFACE_AMBIGUOUS` BLOCKED（新错误类，分类表六类）；coverage guard 升级为 facade AST + `SDK_METHOD_CLASSIFICATIONS` 交叉核对 == registry exact set（18 条：11 SUPPORTED / 4 BLOCKED_PENDING_MAPPER / 3 NOT_APPLICABLE——optional 未消费 surface 显式 NOT_APPLICABLE 不消失）。（2）**P0-02 Immutable Registry**：撤销公开可变 `DATASET_NORMALIZATION_REGISTRY`；module-private 不可变 tuple + private exact index；公开面仅只读 `lookup_spec` / `specs_for` / `registry_specs`；runner 构造器与 `run()` 签名无 spec/mapper/registry/surface 参数（结构测试断言）；tests-only 注入仅经 monkeypatch 私有 state。（3）**P0-03 One Exact Replay Policy**：SUCCESS/PARTIAL/BLOCKED 全终态统一——same exact input identity（evidence hash + contract `cr2.1-v1` + system-derived mapper identity）→ 重验既有 run closure（manifest bytes == ledger hash / outputs bytes+row_count == manifest / quarantine exact set seal == ledger）→ intact = idempotent return，damaged/tampered = fail closed（repair required）；`MAPPER_CODE_FINGERPRINT` = SHA-256 over governed mapper + DTO module sources（行尾归一）进入 run identity——mapper 实现变更产生新 run（历史保留）；撤销 caller 自报 `code_commit`；CR-2 legacy 行缺 seal 永不 healthy replay。（4）**P0-04 Atomic + Recoverable Commit Closure**：输出 parquet 先落（ROW scope 全输出物化，空 parquet = 零产出证据）→ manifest 最后落盘（correctness bytes 无墙钟无 caller provenance，exact retry 字节不变）→ 单 DuckDB 事务（dup 检查 + run INSERT + 全部 quarantine INSERT + 行数断言）COMMIT/ROLLBACK；DB 失败 exact retry 确定性恢复；artifact 路径加 `run=<run_id>` 段；`quarantine_set_hash`（canonical hash over sorted semantic records）双锚定 manifest+ledger；状态机细化（mapped==0 有 quarantine → BLOCKED）。  
**Schema**：migration 015（meta_provider_normalization_run + `normalization_surface` / `mapper_code_hash` / `quarantine_set_hash` 三列，ADD COLUMN IF NOT EXISTS；未改 014；from-zero 15 链 + upgrade（001..014 → 015 仅尾部）+ idempotent 测试）  
**Affected Modules**：`src/ashare_state/normalization/`（registry.py 重构 typed key + 私有化；runner.py 重写 replay/commit 协议）、`src/ashare_state/providers/amazingdata/provider.py`（RawEnvelope.normalization_surface 字段 + call_exchange 派生 + query_index_kline_exchange）、`src/ashare_state/storage/raw_writer.py`（meta 持久化 surface 字段）、`migrations/015_normalization_surface_closure.sql`、`tests/integration/test_provider_normalization.py`（67 项）、`tests/integration/test_migrations.py`（15 链 + upgrade）、`docs/adr/ADR-022`（Amendment A + P1-02 count 更正）、CR-2 工作要求文档（§12 SHA correction P1-01）  
**Tests**：67 项 normalization 对抗测试（CR-2 37 项回归 + CR-2.1 新增 30 项，audit §7 清单 19 项全对应）+ migrations 11 项（15 链 from-zero/upgrade/idempotent/tamper）  
**Governance**：P1-01 SHA 更正（CR-2 implementation canonical = `15cdae25fd7d11e3be0da3683e821629e4226291`，原记录 `15cdae2e4f1...` 为笔误——历史原文保留，工作要求文档追加 §12 更正）；P1-02 count 更正（ADR-022 §2.2 "9/5" → runtime exact-set 18 条 11/4/3，经 Amendment A §6.1）  
**Verification**：Local 938/0（907 → 938，+31：normalization 37 → 67（+30）+ migrations 10 → 11（+1 upgrade））；ruff check / ruff format / mypy 全绿；CI 同款 `uv run pytest` 复验；GitHub Actions **run 33398654940（implementation `2bd0c31fa47c18b520c192265ce306f44a217fc3`）三腿 success**（2026-08-31 API positive confirmation，一次通过零修复轮次）  
**Commit**：`2bd0c31fa47c18b520c192265ce306f44a217fc3`（CR-2.1 implementation；SHA 由 docs 回填 commit 补记）  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260831-063 — Provider-Normalized + Quarantine Runtime (CR-2)

**Type**：C2 数据层新契约（新 ADR）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：CR-2（audit 20260831 §3-§6）——"caller 实际如何从 Raw evidence deterministic 地执行 mapper、如何持久化 normalized 结果、如何落 Quarantine、如何保证没有 silent drop"尚未形成正式 runtime。  
**New Contract**（ADR-022）：新包 `ashare_state.normalization`——（1）**registry**：STATIC production-owned typed registry，keyed by (provider_dataset, endpoint) exact routing，14 个 provider surface 全显式分类（9 SUPPORTED / 5 BLOCKED_PENDING_MAPPER——dividend / right_issue / bj_code_mapping / industry_base_info mapper 未具备足够已验证字段语义，fail closed）；结构守卫测试 AST 抽取 provider surface 要求 exact 覆盖。（2）**runner**：`NormalizationRunner.run(provider, provider_dataset, request_id)` 唯一正式归一化边界——raw evidence 唯一输入（verify_meta_closure + RawWriter.read(verify=True) 复用；无 provider/SDK 访问）；失败 exchange = SOURCE_EXCHANGE_FAILED BLOCKED（≠ mapping quarantine）；multi-table 严格 table 路由（不取第一个 table）。（3）**持久化**：normalized/provider=<P>/dataset=<D>/raw_request=<rid>/contract=cr2-v1/ 下 parquet（canonical 全列排序）+ manifest.json（绑定 raw evidence / contract / mapper identity / 输出表身份 / semantic_hash / counts / status）+ ledger 表 meta_provider_normalization_run；URI 经 frozen logical-URI confinement（组件校验 + physical_from_logical_uri）；artifact 不可变。（4）**记账不变式**：input == mapped + quarantined 由 runtime 机器强制（违反 → NORMALIZATION_INTERNAL_ERROR BLOCKED）；mapper 非 MappingValidationError 异常记为 internal-error quarantine（带 locator）并 BLOCKED——不被吞掉。（5）**quarantine**：meta_provider_quarantine（append-only）——raw request/table/row ordinal 精确定位 + scrubbed structured context（credential 递归 REDACT）+ scope/error_class/mapper identity/contract。（6）**determinism**：run_id = uuid5(sha256(evidence hash + contract + mapper identity))；idempotent replay 返回既有 run（零重复行）；semantic_hash 行序无关（reversed 输入测试）；同 request 不同 evidence bytes → RAW_EVIDENCE_INVALID BLOCK。（7）**provider-faithful**：既有 mappers 原样注册——provider literals/units/未验证标记通过；history_stock_status → 三输出（镜像 + limit-price + CA-flag projection，event_type=STATUS_FLAG_PROJECTION）。（8）**状态机**：SUCCESS/PARTIAL/BLOCKED；PARTIAL 由 registry 逐 surface 声明。  
**Schema**：migration 014（meta_provider_normalization_run 22 列 + meta_provider_quarantine 17 列；from-zero 14 链 + idempotent + tamper 守卫；未改旧文件）  
**Tests**：tests/integration/test_provider_normalization.py（37：raw 唯一输入 / meta+bytes tamper BLOCK / missing-field / unparsable-date / unparsable-numeric quarantine 无 sentinel / legal zero 不当 missing / 记账不变式 / whole-payload calendar / multi-table 路由 / BLOCKED_PENDING_MAPPER / row locator / secret 不泄漏 / internal exception 记录 / idempotent + deterministic + conflicting evidence / URI confinement + evil request id / provider-faithful（units/literals/GALAXY_UNVERIFIED）/ 三输出路由 / 状态机三态 / 结构守卫 ×3）  
**ADR**：[ADR-022](../adr/ADR-022_provider_normalization_quarantine.md)（新；PROPOSED 待复审）；[ADR-021](../adr/ADR-021_publish_validation_exactness.md) status → ACCEPTED（B2 链 CLOSED 同步）  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260831-062 — Final DQ Authoritative Input Seal + Scan Transaction Closure

**Type**：C1 validation 契约收口（input freshness seal）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2.3 P0（audit 20260831 §2/§3/§5）——completion proof 只 seal `scanned_component_manifest_hash`，未覆盖 checker 实际读取的完整 authoritative input：IDENTITY_FALLBACK 还读 `dim_security.identity_key_version`（scan 后改为 FALLBACK → components 未变 manifest 匹配 findings 0 → false PASS）；BLOCKING_DQ 还读 snapshot + 五 fact 表 quality_flags（scan 后加 blocking flag → 同上）；artifact 重绑 snapshot 而 components 不变 → proof 无字段证明当时扫的 snapshot；且 scanner 的 artifact/components 读取在 BEGIN TRANSACTION 之前（audit §5 顺序缺陷）。  
**New Contract**（ADR-021 Amendment G）：（1）**单一 production-owned spec 封装**（§4.3 防漂移）——`ArtifactDQCheckerSpec` 增加 `resolve_input`（解析 authoritative input state）+ `evaluate`（对同一 state 判定）；`fingerprint(input_state)` = canonical JSON（含 check_id + checker_version + state）→ SHA-256——fingerprint 与 evaluation 天然同源；（2）input state 定义（§4.1/4.2）：IDENTITY_FALLBACK = components distinct security_id + 每个的当前 identity_key_version（未注册 → `__MISSING__`）；BLOCKING_DQ = 当前 data_snapshot_id + 每 fact 表 (table_name, quality_flags, row_count) 稳定聚合（NULL/empty 规范化）——只 seal 影响 evaluator 结果的输入；（3）migration 013：`authoritative_input_hash` + `scanned_data_snapshot_id` 两列；DQ_SCAN_CONTRACT_VERSION → dq-scan-b2.3-v1；validation contract → b2-exact-v3；（4）**三层 seal 消费链**（§3）：scanner proof → validation report（dq_execution_seals 绑定 execution_id/contract/producer/input seal/manifest/snapshot）→ publish transaction current-input recheck（重算 CURRENT fingerprints 比对——validation 后 input 变化 → DQ_INPUT_STALE BLOCK；不可解析 → DQ_INPUT_UNRESOLVABLE BLOCK）；物理 bytes 终验先行（missing/tampered 报具体错误）；（5）**Scan Transaction Closure**（§5）：BEGIN TRANSACTION FIRST——authoritative reads 全部移入事务内（`_resolve_scan_context`）；AST ordering 守卫（首个 execute 即 BEGIN 且先于 context 解析）；（6）validator：input seal 缺失（legacy）/ stale → NOT_TESTABLE。  
**Tests**：TestR4B23AuthoritativeInputSeal（12：AST ordering / identity 改 FALLBACK / 删注册 / fact 加 STALE_WINDOW / snapshot 重绑——四类 scan 后 input 变化 stale-proof BLOCK / validation 后 input 变化 ×2 → publish recheck BLOCK / seal tamper+NULL → fail closed / rescan 后真实 finding FAIL / genuine zero unchanged PASS+publish / report seal 与 ledger 一致 / 缺 seals 的 report 拒绝）+ 既有 B2.2/B2.1 测试适配零回归（67→69 局部；全量 870/0）  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) Amendment G  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260831-061 — Final Governed DQ Scan Execution Boundary

**Type**：C1 validation 契约结构性收口（execution truth）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2.2 P0（audit 20260831 §2）——R4-B2.1 的 `record_artifact_check_execution` 不执行任何 scan：caller 读 registry + 公开 `compute_component_manifest_hash` 即可对两个 check 各伪造一行 completion（contract/producer 任意非空串），不写 finding，validate 即 PASS——"caller self-declare scan executed"，与 B1（self-declare APPROVED）/ B2（self-declare 0 counts）同构；mock happy path 正在使用声明路径；proof 的 scan_contract_version / producer 无 current-contract / checker-identity 校验（"fake-v0" + "attacker" 也能成为 PASS 前置）。  
**New Contract**（ADR-021 Amendment F）：新模块 `pipeline/artifact_dq_scan.py`——`run_required_artifact_dq_scan(conn, *, data_root, feature_artifact_set_id)` 为唯一 governed DQ scan execution boundary（签名只有三项，AST 守卫断言无 identity/result/count/completion 参数）：STATIC production registry（ARTIFACT_DQ_CHECKERS：check_id / finding_class / checker_version / evaluator，不可注入）→ 内部 resolve CURRENT components + compute manifest → 逐 check 执行 evaluator（authoritative input）→ persist findings（append-only，按 detail 去重）→ INSERT completion proof LAST（contract = CURRENT "dq-scan-b2.2-v1"；producer = registry 派生 checker 身份——全部 system-derived）→ 单事务 COMMIT（evaluator raise → ROLLBACK → 零 completion row → NOT_TESTABLE）。旧 `record_artifact_check_execution` 从生产命名空间删除（production INSERT 唯一出现在 scan boundary，AST 守卫）。validator 三重校验：proof 缺失 / contract != CURRENT / producer != system-derived checker identity / manifest != current → NOT_TESTABLE。**Authoritative inputs**（§4.5）：IDENTITY_FALLBACK = feature parquet security_id（distinct）× dim_security.identity_key_version（FALLBACK 版本或未注册均 finding——fail closed；mock_e2e 补 dim_security 注册）；BLOCKING_DQ = snapshot 五个 fact 表 quality_flags（blocking 集 = QualityFlag 减 IDENTITY_FALLBACK）。validation contract version → b2-exact-v2（count_source 语义更新，旧 seal 由 current-contract recheck 失效）。真实检测测试（无伪造语义）：fallback 身份 UPDATE → 真实发现 → FAIL；STALE_WINDOW fact 行 → 真实发现 → FAIL。  
**Tests**：test_publish_validation_exactness.py::TestR4B22GovernedScanBoundary（10）+ TestR4B21DQExecutionProof 适配（6 项 B2.1 语义在新结构下零回归）+ confinement 测试适配（attacker re-seal 场景——scanner 自身拒开恶意 URI，validation 层仍 fail closed）  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) Amendment F  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-060 — Publish Validation Logical-URI Confinement + Manifest Check Rename

**Type**：C1 correctness closure（frozen P0-4 回归修复 + check 语义诚实化）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2.1 P0-04 + P1-01（audit 20260830 §5/§6）——R4-B2 新物理文件读取（validator 组件重验 / publish bytes 终验 / report 读取）直接 `data_root / uri`，绕过 frozen `physical_from_logical_uri` helper：escaped/absolute/drive/backslash/alias URI 可读 data_root 外文件且被"一致地验证"；ARTIFACT_MANIFEST_INTEGRITY 只证明"manifest_hash 非空 + 有 components"，名称与证据不一致。  
**New Contract**（ADR-021 Amendment E.5/E.6）：（1）validation 与 publish final recheck 解析任何 registry `file_uri` 及 report_uri 统一经 `physical_from_logical_uri(data_root, uri)`（frozen P0-4 helper；URI 层 fail closed 先于任何 data_root 外读取；保持 exact string identity，不 normalize 接受 alias）；恶意 URI → validation required check FAIL（confinement 词记录）→ publish BLOCK。（2）check rename：`ARTIFACT_MANIFEST_INTEGRITY` → `ARTIFACT_MANIFEST_PRESENT_AND_SEALED`（Option B——证明注册上游 seal 存在；exact component integrity 由 component manifest seal + COMPONENT_* checks 证明；当前 schema 无法无损重建 registration formula，不 overclaim）。  
**Tests**：TestR4B21LogicalURIConfinement（7：../outside / /absolute / C:/drive / backslash / a//b / a/./b 六类恶意 URI（data_root 外 perfect sentinel bytes 一致仍被拒）+ canonical unchanged PASS）；既有 happy 断言经 REQUIRED_VALIDATION_CHECKS 枚举自动覆盖 rename  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) Amendment E.5/E.6  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-059 — Full Transaction-Internal Publish Preconditions

**Type**：C1 publish 契约收口（Option A 完成）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2.1 P0-03（audit 20260830 §4）——R4-B2 只把 `_b2_recheck` 放进事务，完整 lineage reads（snapshot / artifact / feature-set / run / universe）仍在事务外：ADR "TOCTOU closed" 与 "precondition read 仍在事务外"不能同时成立；事务外读取的状态不是 transaction 内 authoritative fact。  
**New Contract**（ADR-021 Amendment E.4）：`publish_snapshot` 重构——全部 authoritative reads 在 `BEGIN TRANSACTION` 之后执行（新 helper `_resolve_publish_preconditions`（完整 lineage gate 语义零变更）事务内调用；`_b2_recheck` 同）；写入只消费事务内值；事务外无任何 correctness read。AST ordering 守卫（测试）：publish_snapshot 体内 BEGIN TRANSACTION 先于 precondition resolver / seal recheck / 首个 conn.execute。状态变化场景（snapshot demoted / artifact demoted/rebound / feature-set member 改动 / run 状态变化 / universe 删除）全部 BLOCK；失败 rollback 保留旧 PUBLISHED（原子 republish 契约 FREEZE 零回归）。  
**Tests**：TestR4B21TransactionInternalPreconditions（8：AST ordering 守卫 + 七个状态变化场景 BLOCK）；test_failure_injection scenario D 零回归  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) Amendment E.4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-058 — Full Validation Seal Consumption / Current Contract Recheck

**Type**：C1 publish 契约收口（seal 成为 correctness input）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2.1 P0-02（audit 20260830 §3）——R4-B2 写入了完整 seal 字段（contract hash / checks hash / validator commit / validation version）但 `_b2_recheck` 只消费 id/counts/report_uri/report_hash/双 manifest——"写了 seal"而非"seal 成为 correctness input"；ADR "contract hash changes invalidate prior seals" 不成立（check IDs 不变 + 语义变化时旧 report 仍全 PASS 可发布）。  
**New Contract**（ADR-021 Amendment E.3）：`_b2_recheck` 完整 seal 三方交叉验证：`validation_contract_hash` ledger == report == `validation_contract_hash()` CURRENT（语义性 contract 演进使旧 seal 失效）；`required_checks_hash` ledger == report == report checks 数组重算 hash（status 改动未重封即暴露）+ duplicate check_id 拒绝（防 dict collapse）；`validator_code_commit` ledger == report 且非空；`validation_version` ledger == report == 当前 supported 版本。`validate_artifact_for_publish` 移除 caller `validation_version` 参数（system-derived——不允许自报 provenance；无 silent grandfather）。  
**Tests**：TestR4B21FullSealConsumption（9：report contract hash stale / ledger-report mismatch / current contract monkeypatch 变化（IDs 不变）/ report checks hash tamper / ledger mismatch / status 改动未重封 / validator commit mismatch / version mismatch / duplicate check id——全部在 re-bind report hash 后仍 BLOCK）  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) Amendment E.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-057 — DQ Required-Check Positive Execution Proof

**Type**：C1 validation 契约收口（消除"未执行即 PASS"）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2.1 P0-01（audit 20260830 §2）——IDENTITY_FALLBACK_ZERO / BLOCKING_DQ_ZERO 仅凭 finding 表 count==0 即 PASS：feature pipeline 根本没跑扫描时表自然为空——"检查过且为零"与"根本没检查"不可区分（B2-02 本要消除的正是这个）。ADR-021 把它列为 CR-3 residual risk 不能作为 VERIFIED 前提（B2 自己已声明这两项 REQUIRED）。  
**New Contract**（ADR-021 Amendment E.2）：新表 `meta_artifact_check_execution`（migration 012）：governed scan 的正向执行证明——check_id / feature_artifact_set_id / scan_contract_version / producer / **scanned_component_manifest_hash**（exact 扫描输入身份）/ completed_at；**不含 count 不含 result**（`record_artifact_check_execution` 签名无 result 参数 + production 唯一 INSERT 边界 AST 守卫——caller 无法 declare count=0/PASS）。validator 语义：无 proof → NOT_TESTABLE（absence of bad findings != proof of zero findings）；stale proof（scanned manifest != current）→ NOT_TESTABLE（rescan required）；匹配 proof + 派生 count==0 → PASS（detail 记录 scan executed + producer + contract）。findings 仍走 append-only 事实表；counts 仍是派生值。残余边界如实记录：proof 证明"扫描执行过且绑定 exact 输入"，不证明"扫描者诚实上报全部 findings"（feature pipeline DQ 治理链 / CR-3 域）。  
**Tests**：TestR4B21DQExecutionProof（6：no proof + no findings → NOT_TESTABLE BLOCK / valid proof zero findings PASS / foreign artifact proof 不转移 / stale proof after component change BLOCK / 缺一项 proof BLOCK / API 无 result 参数 + 唯一 INSERT 边界）；mock_e2e 在 validate 前记录 proofs（production mock 链示范）  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) Amendment E.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-056 — Publish Final Recheck / TOCTOU Closure + Latest-Head Policy

**Type**：C1 publish 契约收口  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2 B2-05/B2-06（audit 20260830 §7/§8）——publish_snapshot 的 precondition read 与 latest validation selection 在 BEGIN TRANSACTION 之前完成，之后才开写事务（TOCTOU：precheck 与 commit 之间状态变化不被发现，publish 可能 commit 基于旧读数的结论）；latest-head 选择规则未机器明确（old PASS + newer FAIL 时不得选旧 PASS）。  
**New Contract**（ADR-021 §2.4/2.5）：publish_snapshot 新增 required 参数 `data_root`；publish-critical 重验移入事务内（`_b2_recheck`，Reviewer 推荐 Option A）：（1）deterministic latest-head（validated_at DESC, artifact_validation_id DESC；validated_at 由 validator 系统时钟写入）；（2）legacy 无 seal 行 BLOCK；（3）report bytes sha256 == ledger report_hash + id/artifact-set 身份比对；（4）current registered artifact_manifest_hash == seal 且 registry 重算 component_manifest_hash == seal；（5）required check 集完整且全 PASS；（6）counts==0；（7）物理字节终验（每组件文件存在 + sha256 == 注册 content_hash——validate 后文件被替换即使 registry 未变也 BLOCK）。任何失败 → ROLLBACK → 旧 PUBLISHED 保留（原子 republish 契约 FREEZE）；supersede/insert/universe/run/uniqueness 逻辑零改动。caller 无 API 传历史 validation id。  
**Tests**：test_publish_validation_exactness.py（newer FAIL 压 old PASS / legacy row BLOCK / registry+bytes tamper ×4 / report tamper/missing/换绑 / PK 注入 rollback / happy 绑定 exact id）；test_failure_injection.py（scenario D rollback 迁移 data_root 后零回归）  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) §2.4/2.5  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-055 — Exact Artifact Validation Seal / Persisted Report

**Type**：C1 validation 契约扩展  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2 B2-03/B2-04（audit 20260830 §5/§6）——ledger 只绑 feature_artifact_set_id 字符串，不绑 artifact/component 的 exact identity（bytes/schema/row/manifest）；validation 无 persisted evidence identity；publish 无法机器重验"这次 PASS 验证的就是现在要发布的字节"。  
**New Contract**（ADR-021 §2.3）：migration 011 ledger 新增 6 列（artifact_manifest_hash / component_manifest_hash / validation_contract_hash / report_uri / report_hash / required_checks_hash）；component_manifest_hash 采用 B2 全字段公式（file_uri/content/schema hash/row_count/family/version/layer/partition 排序 canonical JSON hash——component 任何增删改都改变它）；validation_contract_hash() 是 check contract 身份（版本 + required check 集 + seal 字段 + count 源）；report 物理落盘 `data_root/validation/<artifact_validation_id>.json`（write_file_atomic，immutable bytes，含全部 seal + checks[] + derived summary counts）；ledger.detail 只是摘要，correctness identity 全在 report。publish 重验 = report bytes hash + ledger 身份 + current registry 双 hash + required checks（见 DM-CR-20260830-056）。  
**Tests**：happy report 全 check PASS 断言；report tamper/missing/换绑三场景 BLOCK  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) §2.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-054 — Formal Artifact Validation Execution Boundary + Typed Checks

**Type**：C1 新正式路径契约（结构性 anti-bypass）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B2 B2-01/B2-02（audit 20260830 §2/§3/§4）——record_artifact_validation 直接把 caller 提交的两个计数写进 append-only ledger 而不执行任何 artifact validation（caller self-declare "0/0" → PASS-shaped record → publish eligible，与 B1 早期 approval bypass 同构）；publish gate 只有 aggregate counts，无法证明 required checks 全部执行。  
**New Contract**（ADR-021 §2.1/2.2）：（1）新模块 `pipeline/artifact_validation.py`——`validate_artifact_for_publish(conn, *, data_root, feature_artifact_set_id, validator_code_commit)` 为唯一正式 validation 执行边界（resolve registry → 物理字节重验 → typed checks → 派生 counts → seal → 持久化 report → inline INSERT；沿 B1.2 Option A 模式，无独立 persistence callable）；（2）旧 `record_artifact_validation` 从生产命名空间删除，meta_artifact_validation 的 INSERT 全仓库唯一出现在边界函数内（AST 守卫；签名无 count/result/checks/report 参数）；（3）新表 `meta_artifact_dq_finding`（migration 011，append-only 坏事实，finding_class 白名单）——counts 由 `SELECT count(*)` 派生，`record_artifact_dq_finding` 只能追加坏事实（结构上不可能制造 PASS）；（4）`ArtifactValidationCheckId` 十类 required check（PASS/FAIL/NOT_TESTABLE，NOT_TESTABLE=blocking；物理字节级 content/schema/row 重验；FEATURE_FAMILY_COVERAGE= components distinct (family,version) == member (id,version) 集合——mock_e2e component feature_family 对齐 member id，物理 bytes 不变）。既有测试迁移：record_artifact_validation 三处调用改 DQ facts + formal validator；断言更新为 check-level 阻断。  
**Tests**：test_publish_validation_exactness.py::TestNoCallerDeclaredPass（3：count-writer 消失 / AST 守卫 / raw SQL 伪造无 seal 行 BLOCK）+ TestTypedRequiredChecks（4：happy 全 PASS / missing check / NOT_TESTABLE / unknown check 替代）；test_publish_validation_gate.py + test_publish_lineage.py 迁移后全过（25/0）；test_migrations.py 11-migration 适配  
**ADR**：[ADR-021](../adr/ADR-021_publish_validation_exactness.md) §2.1/2.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-053 — Industry Constituent REQUIRED Endpoint Proof

**Type**：C1 contract 语义修正（必要交付面）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1.2 P0-02（audit 20260830 §3）——industry_taxonomy 的 canonical deliverable 是 bridge_industry_member（security ↔ industry MEMBERSHIP），但 R4-B1.1 把 constituent 标为 OPTIONAL_NON_APPROVAL_SURFACE：base_info PASS + constituent DENIED 时 ENDPOINT gate 仍 PASS 并可 APPROVED，而 bridge_industry_member 无法可靠构建（证明代表性 endpoint ≠ 证明必要交付面，与 security_master 问题同构）。  
**New Contract**（ADR-020 Amendment D.2）：`industry_taxonomy:InfoData.get_industry_constituent` = REQUIRED_ENDPOINT_PROOF（requirements 表 + classification 同步，reason 绑定 bridge_industry_member 交付语义）；`get_industry_weight` / `get_industry_daily` 维持 OPTIONAL 但 reason 显式指向当前消费边界（membership 构建不消费；consumer 变化时重新评估）；provider/target 新增 exact exchange surface `get_industry_constituent_exchange`（provider + Protocol + RealTarget + FakeTarget 四处同步）+ probe factory。**canonical-deliverable 结构守卫**（新测试）：multi-endpoint capability 的 REQUIRED requirements 集合 == canonical 交付面必要端点集合（security_master={hist}；adj_factor={forward}；corporate_action={dividend,right_issue}；industry_taxonomy={base_info,constituent}；index_daily={query_kline}）。  
**Tests**：test_endpoint_requirement_proof.py::TestIndustryConstituentRequiredSurface（3：base_info PASS + constituent DENIED → ENDPOINT FAIL + BUSINESS fired==0 + 失败 exchange 持久化 + VALIDATED_FAIL case；b1 BLOCKED + REPORT 诚实失败；canonical-deliverable surfaces == REQUIRED requirements）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) Amendment D.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-052 — Structural Approval Anti-Bypass（Option A）

**Type**：C1 approval 边界结构性重构  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1.2 P0-01（audit 20260830 §2）——R4-B1.1 的 anti-bypass 是 Python 命名约定非访问控制：`_approve_and_persist_capability_testonly()` 可被显式 import；`VerifiedCapabilityApproval` 是普通可实例化 dataclass（`__post_init__` 只查非空），caller 伪造后直调 `_persist_verified_capability()`——后者只重做 `_validate_evidence`，不重验 closed production run / verdict / formal gate REPORT / endpoint proof / Raw meta cross-binding。  
**New Contract**（ADR-020 Amendment D.1，Reviewer Preferred Option A）：生产模块彻底不存在"无需 formal run 即可写 APPROVED"的 callable——（1）`_approve_capability_in_memory_testonly` / `_approve_and_persist_capability_testonly` / `VerifiedCapabilityApproval` / `_persist_verified_capability` 全部从 capability.py 删除；（2）持久化事务（R3-P1-05 validate-before-mutate / 单事务 / cache-rebuild / R2-P1-01 UPDATE-only-governance-fields）inline 进 `approve_from_spike_run` 尾部——caller 到达写入点必已通过完整验证链；（3）测试所需 transaction/cache mechanics 移入 `tests/integration/_capability_test_persistence.py`（tests/ 内；生产 src 不 import test 模块）；（4）对抗测试改为真实绕过尝试（7 项）：伪造 verified object → 类不存在；caller-built evidence + frozen id → 无 importable 路由；AST 守卫（capability.py 中唯一引用 APPROVED 状态的函数是 approve_from_spike_run 且签名无 evidence/verified 参数；src/ 全模块不 import tests.*）。  
**Tests**：test_approval_anti_bypass.py::TestApprovalAntiBypass 重写（7）；test_capability_governance.py / test_trial_production_boundary.py 迁移至 tests/ helper（approve_and_persist_testonly / approve_in_memory_testonly）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) Amendment D.1  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-051 — Persisted Identity Cross-Binding

**Type**：C1 approval 契约收口（四层精确绑定）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1.1 P0-03（audit 20260830 §4）——REPORT re-check 未核验 provider_dataset/actual_dataset exactness，未要求 endpoint proof case 的 evidence_ref/hash == REPORT entry 的 evidence_uri/hash（case 与 artifact 之间无 identity equality），未从 persisted Raw meta 反向重验 request_id/endpoint/provider_dataset——篡改 REPORT entry 后 re-bind hash 即可通过。  
**New Contract**（ADR-020 Amendment C.5）：`_require_formal_gate_proof` 重写并返回 proven requirement ids（供 VerifiedCapabilityApproval 消费）——对每个满足 requirement 的 PASS 证明：contract ↔ REPORT entry（endpoint + provider_dataset + capability 三字段）；proof case ↔ REPORT entry（evidence_ref == evidence_uri 且 evidence_hash == evidence_hash——case 与 artifact 对"什么证据证明了该端点"必须一致）；REPORT entry ↔ persisted Raw meta（sha256(bytes) == entry.evidence_hash）；Raw meta ↔ contract/entry（endpoint + provider_dataset + request_id 精确相等）。approval 新增 spike_root 参数；run_dir/spike_root 缺失即拒绝（fail closed）。9 项对抗测试全部在 REPORT hash re-bind 后仍拒绝：actual_dataset tamper / provider_dataset tamper / evidence_uri 换 permission 证据 / evidence_hash 换另一份合法 hash / case evidence_ref 与 entry 不一致 / case evidence_hash 与 entry 不一致 / raw meta endpoint tamper / raw meta provider_dataset mismatch / raw meta request_id mismatch。  
**Tests**：tests/integration/test_approval_anti_bypass.py::TestCrossBindingTamper（9）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) Amendment C.5  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-050 — Approval Anti-Bypass（唯一生产 APPROVED transition）

**Type**：C1 approval 边界重构  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1.1 P0-02（audit 20260830 §3）——approve_and_persist_capability() / approve_capability() 是 public 路径且只做 _validate_evidence（字段非空 + RETIRED 拒绝 + positive frozen identity），不消费 formal endpoint proof——caller self-declare CapabilityEvidence 即可 APPROVED。  
**New Contract**（ADR-020 Amendment C.4）：新增内部 sealed proof object `VerifiedCapabilityApproval`（name / evidence / verified_from_run / endpoint_requirements_proven；空证明禁止构造）——只在 approve_from_spike_run 全验证链通过后构造；DB 写 APPROVED 的唯一边界 = private `_persist_verified_capability(conn, verified)`（只接受 verified object；保留 R3-P1-05 validate-before-mutate / 单事务 / cache-rebuild 语义与 R2-P1-01 UPDATE-only-governance-fields）。旧 public 函数移除：approve_and_persist_capability / approve_capability 从模块命名空间消失；测试改用显式 test-only helper（_approve_and_persist_capability_testonly / _approve_capability_in_memory_testonly，docstring 声明非生产路径）。AST 守卫 ×2：src/ 全模块禁止引用 test-only helper；capability.py 中 APPROVED 字面量只允许出现在 governed 边界（_persist_verified_capability / testonly helper / load_approvals）。fabricated CapabilityEvidence 无任何 public 路径可达 APPROVED；failed endpoint requirement 的 run 拒绝后 DB 与内存 cache 一致（CANDIDATE）。  
**Tests**：tests/integration/test_approval_anti_bypass.py::TestApprovalAntiBypass（6）；test_capability_governance.py / test_trial_production_boundary.py 迁移至 test-only helper  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) Amendment C.4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260830-049 — Endpoint Contract Semantic Reconciliation

**Type**：C1 contract 语义修正（撤回错误编组 + 全量 method reconcile）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1.1 P0-01（audit 20260830 §2）——security_master 把 current snapshot 与 historical rebuild 错当 official alternatives（与 security_master_with_delisted 的 survivorship core 冲突：snapshot PASS + hist DENIED 时 ENDPOINT gate 仍 PASS，靠 BUSINESS gate 兜底违反 B1-03）；ADR-020 声称 adj_factor 两端点"各自 REQUIRED"与代码 contract（只有 get_adj_factor）直接矛盾；registry 其它多 endpoint capability（industry_taxonomy 四方法 / index_daily 两方法 / security_master 三方法）未逐项显式说明为何纳入/排除 proof contract。  
**New Contract**（ADR-020 Amendment C.1/C.2/C.3）：（1）security_master：BaseData.get_hist_code_list = REQUIRED（survivorship 必要条件）；get_code_list 移出 requirements（OPTIONAL_NON_APPROVAL_SURFACE）——快照单独可用永不满足 endpoint proof；ENDPOINT_PROBE_SPECS 同步移除 get_code_list 条目。（2）adj_factor Option B：撤回 ADR "各自 REQUIRED"；get_backward_factor 显式分类 OPTIONAL_NON_APPROVAL_SURFACE（当前管线不消费的后复权数据流）。（3）新增 SdkMethodProofClass 五分类 + SDK_METHOD_CLASSIFICATIONS 表（19 条，每条含 auditable reason）：每个 registry sdk_method 恰一条分类；validate_endpoint_requirements() 扩展（分类表内部一致 + REQUIRED 分类 ↔ requirements 双向一致 + ALTERNATIVE_GROUP 分类 ↔ 组成员一致）；结构测试验证 set(registry.sdk_methods) == set(classified)。固化错误语义的 test_alternative_group_single_member_pass_is_pass 按 Reviewer §6 改写为 hist-denied 两测试（ENDPOINT FAIL + BUSINESS fired==0 + approval impossible + REPORT 记录诚实失败）。  
**Tests**：test_endpoint_requirement_proof.py（contract 类 4 项新增：hist REQUIRED / 全量 classified / Option B / 组结构；exact-proof 类 2 项改写）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) Amendment C.1-C.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260828-048 — Approval Consumes Exact Endpoint Identity

**Type**：C1 approval 契约重写  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1 B1-04（audit 20260828 §2.4）——approval 靠 case-id 命名推断 proof（`GATE-{cap}-ENDPOINT` 存在即认为端点已证明），不验证 actual endpoint 与声明一致；篡改/错位检测为零。  
**New Contract**（ADR-020 §2.3）：`_require_formal_gate_proof` 重写——（1）PERMISSION/BUSINESS/REPORT case 语义保留；（2）每个 REQUIRED requirement 必须有 PASS proof case（`endpoint_requirement_case_id`）且 evidence_ref/hash 非空；每个 ALTERNATIVE_GROUP 至少一个成员 PASS；（3）**REPORT artifact 重验**：重算 `{run}/gates/{cap}.json` 的 sha256 == REPORT case evidence_hash；逐条 entry 与 contract 比对（expected_endpoint == contract endpoint；PASS 条目 actual_endpoint == contract endpoint——stand-in 即拒绝；evidence_uri/hash 非空）——任何 mismatch → CapabilityGovernanceError（fail closed）。身份从 hash 锚定 artifact 读，不从 case-id 名称推断。`approve_from_spike_run` 传入 run_dir 以执行 artifact 重验。  
**Tests**：test_endpoint_requirement_proof.py::TestApprovalConsumesExactEndpointIdentity（3：bind 后篡改 artifact 字节 → hash mismatch 拒绝；actual_endpoint 改为 calendar + re-bind hash → stand-in 拒绝；删除 REQUIRED requirement case → 拒绝）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) §2.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260828-047 — Provider/Target Exact Exchange Surface

**Type**：C1 provider surface 扩展  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1 B1-02（audit 20260828 §2.2）——industry_taxonomy / equity_structure / code_mapping_bj 的官方 endpoint（get_industry_base_info / get_equity_structure / get_bj_code_mapping）不在 exchange surface 上，R4-A3.1 时代用 stand-in probe（stock_basic / generic code-list）。  
**New Contract**（ADR-020 §2.2）：`AmazingDataProvider` 新增三个 explicit-exchange 方法——`get_bj_code_mapping_exchange`（endpoint=InfoData.get_bj_code_mapping / dataset=code_mapping_bj / require_capability=code_mapping_bj）、`get_equity_structure_exchange`（InfoData.get_equity_structure / equity_structure）、`get_industry_base_info_exchange`（InfoData.get_industry_base_info / industry_taxonomy）；`SpikeTarget` Protocol / `RealTarget`（delegate）/ `FakeTarget`（fake exchange，endpoint 身份精确）四处同步；各带 payload convenience 方法。  
**Tests**：FakeTarget exact endpoint 经 test_endpoint_requirement_proof.py::test_every_capability_proves_its_exact_endpoint 全量覆盖（10 capability 全 PASS）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md) §2.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260828-046 — Endpoint Requirement Contract + Exact Gate

**Type**：C1 新契约（typed contract + gate 重构）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-B1 B1-01/B1-02/B1-05（audit 20260828 §2.2/§2.3/§2.5）——capability→endpoint 映射无单一审计事实源（散落 if/else 解释 registry tuple）；ENDPOINT gate probe 是 capability-chosen 调用（stand-in 可 PASS，fail-open）。  
**New Contract**（ADR-020 §2.1/§2.2）：新模块 `providers/amazingdata/endpoint_requirements.py`——`EndpointRequirement` typed dataclass（requirement_id/capability/endpoint/provider_dataset/mode/group_id/proof_role）+ `ENDPOINT_REQUIREMENTS` 表（10 capability / 13 条：security_master 为 ALTERNATIVE_GROUP listing_surface 双成员，corporate_action 为双 REQUIRED dividend+right_issue，其余单 REQUIRED）+ `validate_endpoint_requirements()` 结构自检。`spike/formal_gates.py`：`CapabilityProbePlan.endpoint_requirements` 从 contract 派生（caller 无入口）；`ENDPOINT_PROBE_SPECS` 静态表 keyed by requirement_id；`_ExactEndpointRequirementsGate` 替代单 probe endpoint gate——每 requirement 一次原子 evaluation（fire+persist+verdict），envelope endpoint+dataset 精确匹配（mismatch = blocking FAIL，stand-in 永不 PASS；失败 exchange 的 endpoint 同样校验），REQUIRED 全 PASS + 组 ≥1 成员 PASS → PASS，否则 FAIL（early-stop，无 fallback）；每 requirement 一个 proof case（成功/失败都落，SKIPPED 不落）；REPORT artifact 携带 `endpoint_requirements[]` 结构化身份。  
**Tests**：test_endpoint_requirement_proof.py（17：contract 结构 6 + exact proof 5 + approval 身份 3 + 结构守卫 2 + 全 capability 精确证明 1）；test_formal_gate_wiring.py 适配（per-requirement outcomes/probes 断言）  
**ADR**：[ADR-020](../adr/ADR-020_endpoint_requirement_contract.md)  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260828-045 — Trial-L1 Script SdkLifecycle Wiring Fix

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3.2 P1-01（audit 20260828 §3）——`scripts/spike/l1_subscription_test.py` 将 `lifecycle = SdkLifecycle()` 随后同名重绑为 `lifecycle: dict[str, object] = {}`：SubscriptionController 实际收到 dict（无 `transition`，真实运行即 AttributeError）；`state = lifecycle.state` 与 `lifecycle.close()` 失效；finally 中 close 异常被 suppress 使错误更隐蔽。controller 组件测试 PASS 不能证明真实脚本 wiring PASS。  
**New Contract**（ADR-019 Amendment B.2）：correctness SoR 与 diagnostic view 分离命名——`sdk_lifecycle: SdkLifecycle`（SoR：注入 SubscriptionController、verdict 从它派生、finally 中幂等 `close()`）+ `lifecycle_diag: dict`（VIEW：`report["lifecycle"]`）；SDK-dependent 主流程提取为 `execute_subscription_flow(sdk, stage, duration_seconds, *, sleep, monotonic)`——可注入 fake SDK **行为级**测试真实脚本控制流；main() 只保留 login/env/session-gate/flush 与 terminal close。  
**Tests**：tests/integration/test_l1_subscription_script.py（5：端到端状态机路径 SESSION_READY→SUBSCRIBE_STARTED→CALLBACK_ACTIVE→UNSUBSCRIBED + verdict 同源 + register 失败不 fake 状态 + terminal close 幂等 + AST guard ×2 防 dict 遮蔽回归）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) Amendment B.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260828-044 — Persistence-Failure Structural Early-Stop

**Type**：C1 correctness closure（假 early-stop 修复）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3.2 P0-01（audit 20260828 §2）——R4-A3.1 的 `_PersistedProbe` 在持久化失败时只记录 `persist_error` 并照常返回成功 exchange：pipeline 视 PERMISSION 为 PASS 并继续评估 ENDPOINT/CACHE/FRESHNESS/BUSINESS（**真实 downstream provider calls 已发生**），pipeline 跑完后 execute() post-processing 才把 PASS 改写 FAIL——报告呈现 early stopped 但结构上从未 early stop，违反 Exit Gate 的 fail-closed 结构要求。  
**New Contract**（ADR-019 Amendment B.1，Option A）：fire + persist + verdict 合并为 pipeline 内部的一次**原子 gate evaluation**——`_PersistedPermissionGate` / `_PersistedEndpointGate` / `_PersistedBusinessGate`（`spike/formal_gates.py`）evaluate() 后经 `_finalize_persisted`：persist 成功 → 绑定三段证据身份；persist 失败且 exchange 成功 → **当场降级 blocking FAIL**（request_id 可携带但 URI/hash 为空）；已 FAIL 结果保留具体原因并附加持久化失败信息。冻结 pipeline 看到 FAIL → early stop → 下游 probe 从不 fire（`probes[kind].fired == 0` + raw 目录零新 evidence 双证明）。execute() post-hoc 降级逻辑**删除**，替代为防御性 `FormalGateProofError`（PASS 无绑定抵达该处 = 原子 gate 契约失效 → fail loudly，绝不静默改写报告）。**禁止先完整跑完 pipeline 再把 PASS 改 FAIL。**  
**Tests**：test_formal_gate_wiring.py 对抗集（PERMISSION persist 失败 → ENDPOINT/BUSINESS fired==0 + SKIPPED_BLOCKED + 零 raw evidence；ENDPOINT persist 失败 → BUSINESS fired==0；BUSINESS persist 失败 → all_passed 拒绝；request_id 存在但 URI/hash 缺失永不 PASS——断言直接落在 `_BoundReport.probes[kind].fired`）；既有 provider-denial early-stop 与 success/failure binding 测试零回归  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) Amendment B.1  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260827-043 — Subscription Lifecycle SoR Integration

**Type**：C1 correctness closure  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3.1 P1-01（audit 20260827 §5.2）——subscription lifecycle states 已交付但真实 Trial L1 脚本仍用私有 dict 作为第二 lifecycle SoR。  
**New Contract**（ADR-019 Amendment A.4）：`ashare_state.providers.amazingdata.subscription.SubscriptionController`——register/run/unregister/stop 驱动真实 `SdkLifecycle`（SESSION_READY → SUBSCRIBE_STARTED → CALLBACK_ACTIVE → UNSUBSCRIBED → LOGGED_OUT）；register 失败不 fake SUBSCRIBE_STARTED；unregister/stop retry-safe；UNSUBSCRIBED 后回调计数 late_callbacks 永不 reactivation；诊断 dict 是 VIEW，状态机是 SoR；`scripts/spike/l1_subscription_test.py` 消费 controller（report 增加 lifecycle_state_machine 视图，verdict 由状态机派生）。  
**Tests**：test_subscription_controller.py（14）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) Amendment A.4  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260827-042 — Positive Production Account Identity（blacklist → allowlist）

**Type**：C1 correctness closure（fail-open 修复）  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3.1 P0-03（audit 20260827 §4.3/§7）——"not Trial == Production" 为 fail-open：任意 unknown/educational/other-vendor-tier 账号被盖 `ACCOUNT_*` 即获得 approval 资格。  
**New Contract**（ADR-019 Amendment A.3）：`configs/production_account.yaml` 冻结 scrubbed stable profile id（非凭证；空 = 未确认 = fail closed——当前仓库真值）；`AccountProfile.kind` 为解析事实（TRIAL / UNKNOWN；非 trial ≠ production；`ACCOUNT_` 前缀废除 → `UNKNOWN_<digest>`）；四处同步 exact-match 放行：`verify_production_account`（production run 创建门）、`_validate_evidence`、`approve_from_spike_run`、`AuthAccountGate(require_production_identity=True)`（formal boundary 的 production proof input）；无 frozen identity → NOT_TESTABLE / BLOCKED；RunKind.PRODUCTION 永不替代账号身份。旧 fail-open 断言（任意 `ACCOUNT_abc123` 可 approve）废除并重写为 exact-match 对抗集。  
**Tests**：test_trial_production_boundary.py 重写（15：exact match 放行 / mismatch 拒绝 / 无 frozen fail-closed / RunKind 不替代身份 / production_account_status 三态）+ test_amazingdata_provider.py（kind 断言）+ 各 production-run 测试 fixture 化 frozen identity  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) Amendment A.3  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260827-041 — Persisted Gate Evidence Identity

**Type**：C1 evidence 契约  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3.1 P0-02（audit 20260827 §4.2）——gate evidence 只有 request_id：一个 request id 只是请求身份，不是持久化证据身份；probe 失败无第一类失败 exchange 落盘。  
**New Contract**（ADR-019 Amendment A.2）：`GateResult` 证据语义显式拆分 `request_id` / `evidence_uri`（RawWriter .meta.json 锚）/ `evidence_hash`，`has_persisted_evidence` 要求 URI+hash 同时存在；probe exchange（成功与失败）经 `ProbeContext.evidence_from_exchange` 统一持久化后绑定（无 private writer）；持久化失败（exchange 已 fire 但字节未落盘）→ PASS 降级 FAIL 并置 blocked_by（fail closed）；gate proof case 与 gates/{cap}.json report artifact 纳入统一 evidence closure（篡改即阻断 verdict）。  
**Tests**：test_formal_gate_wiring.py（绑定 hash 读盘验证 / 失败 exchange 持久化绑定 / 持久化失败降级 / meta 与 report 篡改阻断 closure）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) Amendment A.2  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

## DM-CR-20260827-040 — Formal Runtime-Gate Execution Boundary Wiring

**Type**：C1 新正式路径契约  
**Status**：DONE / PENDING_REVIEW  
**Trigger**：R4-A3.1 P0-01（audit 20260827 §4.1）——RuntimeGatePipeline 仅为可复用组件，formal Spike/Provider execution path 未消费：组件测试证明的是库，不是正式路径。  
**New Contract**（ADR-019 Amendment A.1）：`ashare_state.spike.formal_gates.FormalRuntimeGateExecutor` 为**唯一** formal gate execution boundary；`CapabilityProbePlan` 六 gate 全量必填（caller 无法选择性跳过 permission/freshness）；冻结顺序 pipeline；`probe_b1_formal_gates` 为全部 formal run（含 dry-run）的强制第一阶段（run_dry_run + scripts/spike/spike_runner.py PHASES）；blocking gate 后 downstream probe fired == 0 且零新 raw evidence；每 capability 落 4 个 `formal_runtime_gate` case（PERMISSION/ENDPOINT/BUSINESS 绑持久化 meta + REPORT 绑六 gate 报告 artifact）；`approve_from_spike_run` → `_require_formal_gate_proof`（四 case 缺一或非 VALIDATED_PASS 即拒绝——early stop 天然阻断 approval）；AST 静态守卫 ×4 防绕过。  
**Tests**：test_formal_gate_wiring.py（14）+ test_capability_approval_from_spike.py（bypass 拒绝）+ test_spike_framework.py（b1 phase 断言）  
**ADR**：[ADR-019](../adr/ADR-019_sdk_lifecycle_runtime_gates.md) Amendment A.1  
**Commit**：本批  
**Reviewer**：PENDING_REVIEW

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
