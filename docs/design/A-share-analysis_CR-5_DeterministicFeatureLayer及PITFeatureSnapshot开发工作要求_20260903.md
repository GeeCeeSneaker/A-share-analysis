# A-share-analysis：CR-5 Deterministic Feature Layer + PIT Feature Snapshot 开发工作要求

> **Stage**：CR-5  
> **Status**：START / ACTIVE **after PR #1 merge**  
> **Issued By**：Reviewer / Design Audit  
> **Issue Date**：2026-09-03 17:15 +08:00  
> **Upstream Reviewer Baseline**：CR-4.4 closure reviewer document commit（本批）  
> **Required Starting Code**：PR #1 `codex/cr-4.4-closure-20260903 -> main` merged  
> **Frozen Upstream**：CR-2 all chain + CR-3 all chain + CR-4 / 4.1 / 4.2 / 4.3 / 4.4  
> **ADR-023 / ADR-024**：ACCEPTED after merge  
> **Required New ADR**：ADR-025 Feature Layer / PIT / Window / Missingness Contract（PROPOSED until Reviewer closure）  
> **Production P0-M-1B**：BLOCKED independently

---

# 0. 阶段定位

CR-5 的目标是第一次在已经冻结的 **market fact world** 上进行可计算的研究特征派生，但仍然不进入 State、策略、打分、回测、组合或交易。

正式数据流：

```text
Raw Evidence
    ↓
Provider-Normalized
    ↓
Canonical Runtime
    ↓
Immutable Snapshot
    ↓
Verified DuckDB ReadModel       ← CR-4 CLOSED / FREEZE
    ↓
CR-5 Deterministic Feature Engine
    ↓
Immutable PIT Feature Snapshot
    ↓
Public Feature Consumption Verifier
    ↓
CR-6 State Layer                ← future, NOT CR-5
```

本阶段必须回答：

1. 一个 Feature run **究竟消费哪个 snapshot world**；
2. 每个特征公式、窗口、缺失值、分母、可用时间如何冻结；
3. 如何证明 Feature artifact 不只是自己 seal 自洽，而确实是 Verified ReadModel 的确定性派生；
4. 如何保留 PIT / lineage，使后续 State 和研究不会把后验数据当成当时已知；
5. 如何把“可支持的基础特征”和“语义尚未验证的特征”明确分开，而不是先算了再解释。

---

# 1. 不可违反的上游边界

## P0-01：FeatureBuilder 只能消费 Verified ReadModel

正式入口建议：

```python
FeatureBuilder.build(
    snapshot_id: str,
    feature_set_id: str,
) -> FeatureBuildResult
```

FeatureBuilder 必须：

```text
DuckDBReadModel.open_read_only(snapshot_id)
```

通过 CR-4 frozen verified-open 获得输入。

禁止 CR-5：

```text
Provider SDK
Raw direct read
CR-2 direct read
Canonical parquet direct read
Snapshot parquet direct read as an alternate source
绕过 verified-open 直接 duckdb.connect(path)
latest / best snapshot selection
隐式 rebuild ReadModel
fallback 到其它 snapshot
多 snapshot fusion
```

若指定 snapshot 的 ReadModel 尚未构建或验证失败：

```text
FAIL CLOSED
```

由更高层 orchestration 显式先 rebuild，再把相同 `snapshot_id` 传给 FeatureBuilder；FeatureBuilder 自己不做隐藏副作用。

---

# 2. Feature Set 必须静态、版本化、不可由调用者注入公式

## P0-02：Feature Registry

必须建立静态版本化 registry，例如：

```text
src/ashare_state/features/registry.py
```

至少定义：

```text
feature_set_id
feature_set_version
feature_registry_version
feature_registry_hash
feature_name
output_dtype
required_inputs
window_basis
window_length / lag
formula_rule_id
denominator_policy
missingness_policy
availability_rule
eligibility
```

调用者只允许传：

```text
snapshot_id
feature_set_id
```

不得传：

```text
window=17
ma_period=23
vol_period=37
fillna=0
tolerance=...
adjustment_formula=...
```

参数不是优化旋钮，而是 **Feature Contract 的组成部分**。修改窗口或公式必须：

```text
registry version/hash change
+ ADR-025 Amendment
+ new feature identity
+ tests
```

V1 正式 feature set 建议冻结为：

```text
market-state-base-v1
```

不允许从结果表现反推参数后悄悄修改平台基础特征。

---

# 3. V1 Feature Eligibility Matrix

CR-5 必须像 Canonical domain matrix 一样明确分类，至少：

```text
SUPPORTED
BLOCKED_PENDING_SEMANTICS
NOT_APPLICABLE
```

## 3.1 SUPPORTED — same-row raw-price features

基于 `rm_daily_bar`，所有分母必须 non-null 且 `> 0`；否则输出 null + typed finding，不得 sentinel。

```text
raw_return_1
  = close / pre_close - 1

gap_open_raw
  = open / pre_close - 1

intraday_return_raw
  = close / open - 1

amplitude_preclose_raw
  = (high - low) / pre_close
```

这些特征必须明确标记：

```text
PRICE_BASIS = UNADJUSTED_CANONICAL
```

不得命名成 adjusted return 或 total return。

## 3.2 SUPPORTED — observed-bar rolling features

V1 **不假装自己已经有每只证券严格的交易所 session window**。

当前 Snapshot 事实层尚没有独立冻结的：

```text
security_id -> market/session calendar association
```

因此 V1 rolling semantics 固定为：

```text
window_basis = OBSERVED_SECURITY_BARS
```

按：

```text
ORDER BY security_id, trade_date, canonical_key
```

对每只证券的实际观察 bar 序列计算。

推荐 V1 固定窗口：

```text
5 / 20 / 60 observed bars
```

特征：

```text
ma_close_obs_5
ma_close_obs_20
ma_close_obs_60

close_to_ma_obs_5
close_to_ma_obs_20
close_to_ma_obs_60
  = close / ma_close_obs_N - 1

return_lag_obs_5
return_lag_obs_20
return_lag_obs_60
  = close_t / close_(N prior observed bars) - 1
  # requires current + N prior observations

amount_to_mean_obs_20
  = amount_t / mean(last 20 observed non-null amount incl. t)

vol_raw_return_obs_20
  = population stddev of exact ordered 20 valid raw_return_1 values
```

Mean / variance 必须使用**确定顺序算法**。V1 correctness 优先，推荐：

```text
math.fsum ordered values
```

以及明确的 population variance：

```text
mean = fsum(x) / N
variance = fsum((x - mean)^2) / N
vol = sqrt(variance)
```

禁止依赖未声明的并行聚合顺序导致 semantic hash 跨平台漂移。

## 3.3 SUPPORTED — observed-universe market breadth

V1 可以形成 `market_daily_features`，但 denominator 必须诚实命名为：

```text
OBSERVED_DAILY_BAR_UNIVERSE
```

而不是：

```text
ALL_A_SHARES
ALL_LISTED_SECURITIES
```

因为当前 CR-4 ReadModel 没有独立冻结的全上市证券 universe table。

V1 推荐：

```text
observed_security_count
valid_raw_return_count
advancer_count
decliner_count
unchanged_count
advancer_ratio_observed
mean_raw_return_observed
median_raw_return_observed
valid_ma20_count
pct_above_ma20_observed
valid_mom20_count
pct_positive_mom20_observed
total_amount_observed
```

其中：

```text
advancer       raw_return_1 > 0
decliner       raw_return_1 < 0
unchanged      raw_return_1 == 0
ratio denominator = valid_raw_return_count
```

无有效 denominator 时输出 null + finding，绝不输出 0 伪装事实。

## 3.4 BLOCKED_PENDING_SEMANTICS

以下不允许在 CR-5 V1 偷偷实现：

```text
adjusted OHLC
adjusted return / total return
复权因子公式推断
corporate-action neutralized return
严格 N market-session window per security
“全市场上市股票” denominator
board / ST / tick-size 推断出的涨跌停 hit
near-limit tolerance classification
industry breadth
index-relative alpha / beta
cross-sectional z-score based on an ungoverned universe
strategy signal / score / rank
```

### Adjusted feature 特别裁决

虽然 Canonical 已有：

```text
adj_factor
backward_factor
factor_type
```

**存在事实字段 ≠ 已验证了下游复权公式。**

在正式证据/Spike/ADR 明确：

```text
factor orientation
base date
forward/backward semantics
corporate action coverage
provider historical revision behavior
```

之前，不得凭字段名猜复权公式。

---

# 4. Missingness / Validity Contract

## P0-03：禁止 silent fill / silent drop

禁止：

```text
fillna(0)
-999 / 999999 sentinel
forward fill price
backfill
把停牌日复制前值
窗口不足时缩短 N
跳过异常行但不记录
```

每个 feature value 可以是 null，但 null 的原因必须可以审计。

建议形成独立 deterministic artifact：

```text
feature_findings.parquet
```

最小字段：

```text
scope                  # security_daily / market_daily
security_id            # nullable for market scope
trade_date
feature_name
finding_class
detail_json
```

建议 finding class：

```text
INSUFFICIENT_HISTORY
INPUT_NULL
UNSAFE_DENOMINATOR
NON_FINITE_RESULT
OPTIONAL_INPUT_MISSING
UNSUPPORTED_SEMANTICS
```

Structural contract violation（错误 schema、foreign snapshot、registry 不支持、duplicate key）必须直接 fail closed；普通历史不足属于可解释 row-level finding，不应让整个 Feature run 失败。

---

# 5. PIT / Temporal Lineage

## P0-04：Feature 不能只保留 trade_date，必须保留 knowledge time

这是 CR-5 最重要的研究正确性原则之一。

一个历史 `trade_date=T` 的事实，可能是在更晚时间才被当前系统观察/摄取。CR-5 不得把：

```text
trade_date
```

误当成：

```text
known_at
```

V1 每个 security feature row 至少保留：

```text
security_id
trade_date
source_snapshot_id
source_canonical_run_id
feature_run_id
feature_set_id
feature_contract_version
feature_available_at
input_lineage_hash
```

### feature_available_at

对该 row 所有实际用于产生非-null feature 的输入，取：

```text
max(input.available_at)
```

作为保守的 row-level：

```text
feature_available_at
```

要求：

```text
feature_available_at <= snapshot.as_of
```

若某些简单 feature 本来可以更早可用，但同 row 的 60-bar feature 需要更晚输入，使用最大值是保守但正确的 V1 选择；以后如需 feature-level available_at，可另立 contract，不得在 V1 隐式混用。

### input_lineage_hash

必须从实际参与计算的 ordered upstream row identities 派生，例如 canonical JSON over：

```text
(domain,
 canonical_key,
 source_row_identity_hash,
 available_at)
```

再 SHA-256。

rolling feature 的 lineage 必须包含整个实际 window，而不只是当前行。

market aggregate 的 lineage 必须从参与该日 aggregate 的 security feature lineage 集合确定性派生。

### Historical target leakage guard

计算目标日 `T` 的 rolling feature 时：

```text
只能使用 trade_date <= T 的 security observations
```

不得因为 Snapshot as_of 更晚，就让 `T+1`、`T+20` 的价格进入 T 的 rolling window。

同时不得宣称：

```text
feature for T was known on T
```

真正知识时点由 `feature_available_at` 表示。

---

# 6. Deterministic Feature Identity

## P0-05：1 Feature run == 1 Snapshot world + 1 Feature Contract

建议：

```text
FEATURE_CONTRACT_VERSION = "feature-v1"
```

Feature identity 至少进入：

```text
snapshot_id
snapshot manifest hash
snapshot semantic hash
snapshot as_of
readmodel contract version
readmodel builder code fingerprint
feature_set_id
feature_set_version
feature_registry_version
feature_registry_hash
feature contract version
feature builder code fingerprint
```

推荐：

```text
feature_base_hash = sha256(canonical JSON primitives)
feature_run_id = UUID5(FEATURE_NAMESPACE, feature_base_hash)
```

禁止：

```text
random UUID
wall-clock
DB insertion order
host timezone
thread scheduling
latest pointer
```

同一 Verified Snapshot + 同一 Feature Contract/Code 必须得到同一 `feature_run_id`。

---

# 7. Feature Artifact Contract

## P0-06：Immutable PIT Feature Snapshot

V1 推荐 exact artifact set：

```text
feature/
  contract=feature-v1/
  snapshot=<snapshot_id>/
  run=<feature_run_id>/
    security_daily_features.parquet
    market_daily_features.parquet
    feature_findings.parquet
    manifest.json
```

`manifest.json` LAST。

每个 artifact entry：

```text
uri
content_hash
schema_hash
row_count
semantic_hash
```

Manifest 至少封存：

```text
feature_run_id
feature_contract_version
feature_builder_code_fingerprint
feature_set_id/version
feature_registry_version/hash
snapshot_id
snapshot manifest uri/hash
snapshot semantic hash
snapshot as_of
readmodel contract version/fingerprint
artifact exact set
artifact seals
feature semantic aggregate hash
finding_set_hash
row counts
status = SUCCESS
```

所有 correctness artifact bytes **不得含 wall-clock**。

`started_at / completed_at` 只允许进入 ledger audit metadata。

---

# 8. Recoverable Immutable Publication

## P0-07：直接继承 CR-4 Frozen Contract

Feature artifacts 必须复用已经冻结的 publication principle：

```text
missing deterministic path             -> write
existing path + exact same bytes        -> no-op
existing path + different bytes         -> conflict / DAMAGED
preflight complete deterministic plan
artifacts first
manifest LAST
ledger LAST
```

文件已写、ledger commit 失败：exact retry 必须自动恢复。

禁止：

```text
rm -rf old run
random suffix
覆盖旧 artifact
```

---

# 9. Feature Ledger / Migration

## P0-08：预计 migration 023 `meta_feature_build`

允许新增 migration **023**，不得修改 018-022。

建议字段：

```text
feature_run_id PK
snapshot_id
snapshot_manifest_uri
snapshot_manifest_hash
snapshot_semantic_hash
snapshot_as_of
readmodel_contract_version
readmodel_builder_code_fingerprint
feature_set_id
feature_set_version
feature_registry_version
feature_registry_hash
feature_contract_version
feature_builder_code_fingerprint
manifest_uri
manifest_hash
artifact_set_hash
feature_semantic_hash
finding_set_hash
security_row_count
market_row_count
finding_count
status
error_message
started_at
completed_at
```

如果 migration 023 落地，必须完整：

```text
from-zero
022 -> 023 upgrade
idempotent migration
migration checksum/tamper probe
```

---

# 10. Public Feature Consumption Verifier

## P0-09：CR-6 不得信任“feature parquet 存在”

必须提供：

```python
verify_feature_run_for_consumption(feature_run_id: str) -> VerifiedFeatureRun
```

它至少验证：

```text
ledger row exists
manifest deterministic URI/hash
manifest == ledger correctness fields
feature identity physical recompute + UUID5 cross-bind
current feature registry version/hash
current builder fingerprint
upstream Snapshot verifies
upstream ReadModel verified-open succeeds
artifact exact set
physical content/schema/rowcount/semantic seals
feature findings exact set
PIT/lineage invariants
```

并且必须像 CR-4 Snapshot closure 一样证明：

> **Feature rows 是 Verified ReadModel + frozen Feature Registry 的确定性 replay，而不是一组自洽但被重绑的任意数值。**

因此应抽取单一共享：

```text
compute_feature_set(...)
```

Builder 与 verifier 共用。

`verify_feature_run_for_consumption()` 重新计算 expected feature rows / findings，并与 artifact exact compare。

---

# 11. V1 Schema 建议

## 11.1 `security_daily_features`

至少：

```text
security_id
trade_date
source_snapshot_id
source_canonical_run_id
feature_run_id
feature_set_id
feature_contract_version
feature_available_at
input_lineage_hash

raw_return_1
gap_open_raw
intraday_return_raw
amplitude_preclose_raw

ma_close_obs_5
ma_close_obs_20
ma_close_obs_60
close_to_ma_obs_5
close_to_ma_obs_20
close_to_ma_obs_60
return_lag_obs_5
return_lag_obs_20
return_lag_obs_60
amount_to_mean_obs_20
vol_raw_return_obs_20
```

所有 business feature 列 nullable；identity / provenance 列 non-null。

必须按：

```text
security_id, trade_date
```

唯一且稳定排序。

## 11.2 `market_daily_features`

至少：

```text
trade_date
source_snapshot_id
feature_run_id
feature_set_id
feature_available_at
input_lineage_hash
universe_rule_id = OBSERVED_DAILY_BAR_UNIVERSE

observed_security_count
valid_raw_return_count
advancer_count
decliner_count
unchanged_count
advancer_ratio_observed
mean_raw_return_observed
median_raw_return_observed
valid_ma20_count
pct_above_ma20_observed
valid_mom20_count
pct_positive_mom20_observed
total_amount_observed
```

按 `trade_date` 唯一。

---

# 12. Formula / Numeric Safety

## P0-10：无 silent numeric corruption

必须统一：

```text
NaN / +Inf / -Inf 不得进入 correctness artifact
```

任何计算结果非 finite：

```text
value = null
+ NON_FINITE_RESULT finding
```

分母：

```text
None or <= 0
```

则：

```text
value = null
+ UNSAFE_DENOMINATOR finding
```

窗口：

```text
不足固定 N -> null + INSUFFICIENT_HISTORY
```

不得缩短窗口完成计算。

禁止在 correctness 层做“展示友好 rounding”；展示层以后可单独格式化，Feature truth 保留 float64 计算结果。

---

# 13. Deterministic Query / Calculation Boundary

## P0-11

从 DuckDB 读取必须显式 `ORDER BY`，不得依赖自然行序。

Feature calculation code 不允许把算法语义藏在 SQL planner 未冻结的聚合顺序中。

第一版建议：

```text
DuckDB = verified typed row retrieval
Python ordered deterministic engine = formula truth
```

后续若为性能改成 DuckDB/Polars rolling/parallel aggregation，必须先证明：

```text
logical semantic exact equivalence
```

并增加跨平台 deterministic regression；不能只以“更快”为理由替换 correctness implementation。

---

# 14. Required Implementation Layout

建议：

```text
src/ashare_state/features/
  __init__.py
  registry.py
  formulas.py
  engine.py
  models.py
  builder.py
  verifier.py
```

禁止 Feature package import：

```text
providers
normalization
raw_writer
canonicalizer source-selection internals
strategy
backtest
portfolio
trading
```

允许依赖：

```text
readmodel public verified-open boundary
snapshot public verification metadata
frozen utility canonical serialization/hash helpers
```

如果复用 CR-4 private helper 会造成 Feature 直接绑定内部实现，应抽取正式公共只读 helper，而不是大量 `# noqa: SLF001` 扩散到新层。

---

# 15. ADR-025 必须回答的问题

ADR-025 至少回答：

1. 为什么 Feature 绑定 explicit `snapshot_id`，没有 latest/best？
2. 为什么输入边界是 Verified ReadModel，而不是直接读 Snapshot Parquet？
3. Feature Registry 为什么是静态版本化 contract，而不是 caller parameters？
4. V1 为什么 rolling window 明确叫 `OBSERVED_SECURITY_BARS`？
5. `trade_date` 与 `feature_available_at` 有什么区别，如何避免后验知识泄漏？
6. 为什么 V1 raw-price feature 明确是 UNADJUSTED？
7. 为什么 adjusted return 在 factor formula 证据完成前 BLOCKED？
8. 为什么市场 breadth denominator 是 `OBSERVED_DAILY_BAR_UNIVERSE`，不能称“全 A 股”？
9. Missingness / denominator / non-finite 如何处理，为什么禁止 sentinel/fill？
10. Feature identity 包含哪些 primitives？
11. Feature artifact 为什么是 correctness truth；是否需要 Feature ReadModel？V1 为什么可以不做？
12. deterministic ordered numeric algorithm 如何保证跨平台 replay？
13. FeatureBuilder / verifier 如何共享一套计算实现避免强弱两套公式？
14. alternatives：
   - dynamic user-defined formula；
   - pandas/SQL ad-hoc feature；
   - direct Snapshot query；
   - adjusted price immediately；
   - multi-snapshot feature fusion；
   并说明拒绝/延后的原因。

---

# 16. Mandatory Test Matrix

## 16.1 Input boundary / world identity

1. healthy verified ReadModel -> Feature build succeeds。
2. unknown snapshot -> refuse。
3. Snapshot damaged -> refuse before feature artifact write。
4. ReadModel foreign/tampered -> refuse。
5. ReadModel missing -> refuse; FeatureBuilder must not auto-rebuild。
6. no latest/best API/static guard。
7. no Raw/CR-2/Provider/Canonical direct-source access AST guard。
8. two different snapshots -> different feature_run_id and independent artifacts。

## 16.2 Registry / identity

9. unknown feature_set_id -> refuse。
10. registry hash enters feature identity。
11. formula/window registry change -> different identity。
12. builder code fingerprint change -> different identity。
13. same Snapshot + same contract/code -> same feature_run_id。
14. wall-clock / insertion order cannot change identity/artifact bytes。

## 16.3 Formula correctness

15. raw_return_1 exact fixture。
16. gap_open_raw exact fixture。
17. intraday_return_raw exact fixture。
18. amplitude exact fixture。
19. MA5/20/60 exact ordered fixtures。
20. lag-return 5/20/60 exact boundary fixtures（N prior observations semantics）。
21. amount mean ratio exact fixture。
22. vol_obs20 exact deterministic fixture。
23. target T cannot use trade_date > T row。
24. security rows always sorted / key unique。
25. observation gap is not forward-filled。

## 16.4 Missingness / numerical safety

26. insufficient N history -> null + exact finding。
27. null input -> null + finding。
28. zero/non-positive denominator -> null + finding。
29. non-finite result never persists。
30. no sentinel values/static guard。
31. no forward/backfill/static guard。
32. findings exact-set hash deterministic。

## 16.5 PIT / lineage

33. feature_available_at = max actual used input available_at。
34. feature_available_at <= snapshot.as_of。
35. rolling input_lineage_hash changes if any member identity changes。
36. simple feature lineage contains the actual current source row。
37. later-ingested historical fact does not get mislabeled as known on trade_date。
38. market aggregate available_at / lineage derived from actual participating security rows。

## 16.6 Market breadth

39. observed denominator exact fixture。
40. adv/decline/unchanged counts exact。
41. zero valid denominator -> null, not 0。
42. pct_above_ma20 denominator = valid_ma20_count only。
43. deterministic mean/median across input ordering。
44. universe_rule_id is explicit and constant。

## 16.7 Blocked semantics

45. adjusted-return feature request/classification cannot execute formula。
46. session-window feature cannot silently use observed-bar implementation under session name。
47. “all A-share” denominator cannot be emitted under V1 registry。
48. no strategy/score/rank/backtest imports or outputs。

## 16.8 Artifact / replay / recovery

49. exact artifact set + manifest LAST。
50. content tamper -> verify_feature_run refuses。
51. schema/rowcount/semantic seal rebind -> refuse。
52. business value + ALL Feature seals rebound -> deterministic replay still refuses。
53. lineage value + ALL seals rebound -> deterministic replay still refuses。
54. ledger commit failure -> exact retry recovery。
55. partial identical residue -> recovery。
56. conflicting residue -> refuse。
57. feature verifier parses exact hash-verified bytes。
58. historical healthy feature exact replay idempotent。

## 16.9 Migration / CI

59. migration 023 from-zero。
60. 022 -> 023 upgrade。
61. idempotent migration。
62. migration tamper/checksum probe。
63. Windows py3.12 green。
64. Windows py3.14 green。
65. Ubuntu py3.14 green。
66. Ruff / format / mypy / full pytest / Spike / SDK / governance gates green。

---

# 17. CR-5 Exit Gate

Reviewer closure 前必须全部成立：

```text
[ ] PR #1 / CR-4.4 merged; upstream CR-4 frozen
[ ] ADR-025 complete and reviewed
[ ] public verified ReadModel is the only Feature input boundary
[ ] explicit snapshot_id + feature_set_id only
[ ] static versioned Feature Registry
[ ] SUPPORTED / BLOCKED semantics matrix complete
[ ] raw vs adjusted price basis named honestly
[ ] observed-bar window semantics explicit
[ ] observed-universe breadth denominator explicit
[ ] deterministic formulas pinned by fixtures
[ ] no silent fill / sentinel / shortened windows
[ ] feature_available_at lineage correct
[ ] input_lineage_hash deterministic
[ ] no target-date lookahead
[ ] deterministic Feature identity
[ ] immutable exact-retry recoverable artifacts
[ ] Feature ledger / migration complete if introduced
[ ] public Feature consumption verifier exists
[ ] verifier replays formulas from Verified ReadModel
[ ] all physical + semantic seals consumed
[ ] no State / strategy / score / backtest semantics
[ ] frozen CR-2/3/4 regressions green
[ ] three-platform CI green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR index synchronized
[ ] Reviewer sees no new P0 correctness blocker
```

通过后：

```text
CR-5 -> VERIFIED / CLOSED / FREEZE
ADR-025 -> ACCEPTED
CR-6 Market State Layer -> START
```

---

# 18. 明确禁止范围

CR-5 不允许：

```text
market regime / state classification
bull/bear labels
stock score
alpha signal
entry/exit signal
strategy rules
backtest
parameter optimization from PnL
portfolio construction
simulated trading
live trading
production account
new Provider
new Canonical domain
silent adjusted-price semantics
industry/index semantics guessing
```

CR-5 的职责是：

> **构造可被未来 State 层信任的“特征事实层”，而不是提前做策略判断。**

---

# 19. Owner View

```text
Trusted Market Facts
        ✅ Raw / Normalized / Canonical / Snapshot / ReadModel frozen
                      │
                      ▼
CR-5 Feature Layer
        🔧 把事实转换为确定性、PIT 可追溯的基础特征
        🔧 每个公式/窗口/缺失值规则都有版本和证据
        🔧 不因历史回测结果修改平台基础参数
                      │
                      ▼
PIT Feature Snapshot
        🔧 可重放、可校验、不可静默改写
                      │
                      ▼
CR-6 State Layer
        ⏸ 下一阶段才回答“市场处于什么状态”
```

完成 CR-5 后，未来 State / Research 代码应该只需要知道：

```text
feature_run_id
```

即可获得一个**来源唯一、时间世界明确、公式冻结、缺失原因可审计、可确定性重建**的市场特征世界，而不再接触 Provider、Raw、Canonical 内部选择或临时 DataFrame 计算脚本。
