# A-share-analysis：CR-6 Deterministic Observed Market State Layer 开发工作要求

> **Issue Date**：2026-09-04 07:26 +08:00  
> **Reviewer Handoff Upstream**：CR-5 final closure Reviewer branch  
> **CR-5 Technical HEAD**：`88bb33760ec43d33abb80871bef6f3c3be880435`（PR #3，APPROVED_TO_MERGE）  
> **Entry Condition**：PR #3 must be merged to `main` before CR-6 product code  
> **Status**：**CR-6 START / ACTIVE after PR #3 merge**  
> **Required ADR**：**ADR-026 Deterministic Observed Market State Contract — PROPOSED**  
> **Production**：P0-M-1B remains independently BLOCKED

---

# 0. 目标与边界

CR-6 是 `Raw → Canonical → Snapshot/ReadModel → Feature → State` 日频数据链的第一版 **State consumption boundary**。

它不是交易策略层，也不是预测层。

CR-6 要回答的是：

> 对一个明确的、已经通过 `verify_feature_run_for_consumption(feature_run_id)` 验证的 Feature world，怎样用完全透明、固定、非拟合的规则，把每个 trade_date 的 market features 解释成可复现的“Observed Market State”。

V1 State 必须满足：

```text
描述性（descriptive）
非预测（non-predictive）
非策略（non-strategy）
非回测优化（non-fitted）
显式 Feature world identity
PIT / no-lookahead
Registry-driven
可重放
可审计
不可静默 fallback
```

---

# 1. 数据流

正式 V1 数据流：

```text
Verified Feature SUCCESS
        ↓
verify_feature_run_for_consumption(feature_run_id)
        ↓
State Registry / Execution Plan
        ↓
Deterministic State Engine
        ↓
Immutable Observed State Snapshot
        ↓
verify_state_run_for_consumption(state_run_id)
        ↓
Future research / monitoring / strategy consumers
```

State Layer **不得**绕过 Feature verifier 去读取：

```text
Raw
Provider-Normalized
Canonical
Snapshot parquet
DuckDB ReadModel
Provider SDK
```

StateBuilder 的正式值输入只允许来自公共 Feature consumption verifier 返回的 VerifiedFeatureRun。

---

# 2. CR-6 V1 的核心设计原则

## P0-01 Explicit `feature_run_id`

推荐 API：

```python
StateBuilder.build(
    feature_run_id: str,
    state_set_id: str,
) -> StateBuildResult
```

禁止：

```text
build_latest()
build_best_available()
automatic latest Feature lookup
fallback to previous Feature run
multi-Feature-run fusion
```

一个 State run 必须精确对应一个 Feature run。

---

## P0-02 One State Run == One Feature World

V1 不允许把：

```text
Feature run F1 的 2025 数据
+
Feature run F2 的 2026 数据
```

混进同一个 State artifact。

State run 的历史世界必须由一个 `feature_run_id` 完整确定。

State output 日期集合只能来自该 VerifiedFeatureRun 的 `market_daily_features` 日期集合。

---

## P0-03 State Registry 必须是唯一规则真相

建议：

```text
STATE_SET_ID = observed-market-state-v1
STATE_REGISTRY_VERSION = state-registry-v1
STATE_CONTRACT_VERSION = state-v1
```

State Registry 至少声明：

- required feature_set_id；
- required feature_contract_version；
- required market input fields；
- dimension rule ids；
- comparison threshold / comparison semantics；
- overall state rule id；
- missingness rule；
- availability rule；
- output enum exact set；
- blocked semantics exact set。

不得由 caller 注入：

```text
threshold
weight
lookback
hysteresis
smoothing
min-duration
score cutoff
bull/bear cutoff
```

任何 State rule 变化都必须：

```text
new Registry version/hash
new state identity
ADR-026 amendment
focused fixtures
```

**禁止从回测结果里调阈值。**

---

# 3. V1 State 输入范围

CR-6 V1 只消费 Verified Feature run 的：

```text
market_daily_features
```

不直接对 `security_daily_features` 做新的 cross-sectional 聚合。

理由：

- cross-sectional aggregation 已属于 Feature truth；
- State Layer 应解释 Feature，不应重新发明 Feature；
- 避免 Feature 与 State 两层出现重复 denominator / missingness / aggregation 实现。

V1 需要的 market fields：

```text
trade_date
feature_available_at
input_lineage_hash
universe_rule_id
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

State Registry 必须要求 upstream：

```text
feature_set_id == market-state-base-v1
price_basis == UNADJUSTED_CANONICAL
window_basis == OBSERVED_SECURITY_BARS
universe_rule_id == OBSERVED_DAILY_BAR_UNIVERSE
```

不得把 observed universe 改称“全 A 股”。

---

# 4. V1 State Dimensions

CR-6 V1 不使用拟合阈值、不使用权重、不使用历史分位数。

只使用有直接业务含义的 sign / majority 关系。

## 4.1 Breadth Direction State

输入：

```text
advancer_count
decliner_count
valid_raw_return_count
```

规则：

```text
valid_raw_return_count <= 0
    -> INSUFFICIENT

advancer_count > decliner_count
    -> POSITIVE

advancer_count < decliner_count
    -> NEGATIVE

advancer_count == decliner_count
    -> BALANCED
```

注意：这里不把 `advancer_ratio < 0.5` 错称“下跌股票占多数”，因为 unchanged 可能较多。比较 advancer 与 decliner count 才是诚实的 directional breadth。

建议输出：

```text
breadth_direction_state
```

exact enum：

```text
POSITIVE
NEGATIVE
BALANCED
INSUFFICIENT
```

---

## 4.2 MA20 Trend Breadth State

输入：

```text
valid_ma20_count
pct_above_ma20_observed
```

规则：

```text
valid_ma20_count <= 0 or ratio is NULL
    -> INSUFFICIENT

pct_above_ma20_observed > 0.5
    -> POSITIVE

pct_above_ma20_observed < 0.5
    -> NEGATIVE

pct_above_ma20_observed == 0.5
    -> BALANCED
```

这里 `0.5` 是“可比较证券中严格多数在 MA20 上方”的数学 majority boundary，不允许优化。

建议输出：

```text
trend_breadth_state
```

---

## 4.3 MOM20 Momentum Breadth State

输入：

```text
valid_mom20_count
pct_positive_mom20_observed
```

规则同 majority：

```text
valid_mom20_count <= 0 or ratio is NULL
    -> INSUFFICIENT

ratio > 0.5 -> POSITIVE
ratio < 0.5 -> NEGATIVE
ratio = 0.5 -> BALANCED
```

建议输出：

```text
momentum_breadth_state
```

---

## 4.4 Return Distribution State（辅助维度）

输入：

```text
mean_raw_return_observed
median_raw_return_observed
```

V1 仅做 sign consensus：

```text
either NULL
    -> INSUFFICIENT

mean > 0 and median > 0
    -> POSITIVE

mean < 0 and median < 0
    -> NEGATIVE

mean == 0 and median == 0
    -> FLAT

otherwise
    -> MIXED
```

建议 enum：

```text
POSITIVE
NEGATIVE
FLAT
MIXED
INSUFFICIENT
```

该维度**不进入 V1 overall state**，只作为解释性辅助状态。理由：单日 raw return distribution 噪声较高，V1 不应通过任意权重把它混入主状态。

---

# 5. V1 Overall Observed Market State

核心三维：

```text
breadth_direction_state
trend_breadth_state
momentum_breadth_state
```

V1 overall rule 使用最保守的 **unanimous directional consensus**，不使用加权分数。

规则：

```text
任一核心维度 == INSUFFICIENT
    -> INSUFFICIENT

三个核心维度全部 POSITIVE
    -> UP_CONSENSUS

三个核心维度全部 NEGATIVE
    -> DOWN_CONSENSUS

其它组合
    -> MIXED
```

exact enum：

```text
UP_CONSENSUS
DOWN_CONSENSUS
MIXED
INSUFFICIENT
```

## 5.1 为什么 V1 不直接叫 bull / bear

`UP_CONSENSUS` / `DOWN_CONSENSUS` 描述的是：

> observed breadth、MA20 breadth、MOM20 breadth 三个冻结维度在当日方向上是否一致。

它不宣称：

```text
未来上涨概率更高
未来收益为正
牛市 / 熊市的宏观定义
交易信号
仓位建议
```

未来若研究需要 bull/bear/regime taxonomy，应另起 State Registry version + ADR amendment，并提供非后验的业务定义和验证，而不是把策略研究标签偷塞进基础平台。

---

# 6. State output schema

建议：

```text
src/ashare_state/state/schema.py
```

V1 `observed_market_state` row 至少：

```text
trade_date
source_feature_run_id
source_snapshot_id
source_canonical_run_id
state_run_id
state_set_id
state_contract_version
state_available_at
input_lineage_hash
price_basis
window_basis
universe_rule_id

input_observed_security_count
input_valid_raw_return_count
input_advancer_count
input_decliner_count
input_unchanged_count
input_advancer_ratio_observed
input_valid_ma20_count
input_pct_above_ma20_observed
input_valid_mom20_count
input_pct_positive_mom20_observed
input_mean_raw_return_observed
input_median_raw_return_observed

breadth_direction_state
trend_breadth_state
momentum_breadth_state
return_distribution_state
observed_market_state
```

### 为什么保留 `input_*`

State artifact 应该能独立解释：

> 为什么当天被判为这个状态。

`input_*` 必须是 Verified Feature row 的 exact copy，不允许 State 层重新计算 Feature 数值。

Verifier 必须 exact compare copy fields。

---

# 7. State PIT / Lineage

## P0-07 State availability

V1 State 每个 trade_date 只消费对应的一条 `market_daily_features` row，因此：

```text
state_available_at
=
source market feature row.feature_available_at
```

不得使用：

```text
trade_date midnight
build wall-clock
next day confirmation time
future state knowledge
```

并要求：

```text
state_available_at <= upstream snapshot_as_of
```

## P0-08 State lineage

建议 `input_lineage_hash` 绑定：

```text
source_feature_run_id
trade_date
source market feature row.input_lineage_hash
source feature_available_at
source market row semantic payload hash
state registry rule identity
```

可以实现为 typed deterministic members + canonical JSON hash。

至少必须保证：

- upstream market input value 改变 -> state lineage / replay 变化；
- upstream market feature lineage 改变 -> state lineage 变化；
- unrelated future feature row 变化不改变历史 state row；
- no wall-clock。

---

# 8. No hidden temporal state in V1

CR-6 V1 **禁止**：

```text
hysteresis
minimum holding days
state smoothing
EMA state
3-day confirmation
future confirmation
previous-state-dependent transition
regime duration rule
look-ahead transition labeling
```

理由：这些都会把 current-state truth 变成 path-dependent temporal model，需要独立 State model contract。

V1 每个 trade_date 必须仅由该 trade_date 的 Verified market feature row + static Registry rule决定。

如果未来需要 transition/hysteresis，另建 CR-6.x / ADR-026 Amendment，不得静默修改 V1。

---

# 9. Deterministic State Identity

建议：

```text
STATE_CONTRACT_VERSION = state-v1
STATE_SET_ID = observed-market-state-v1
STATE_REGISTRY_VERSION = state-registry-v1
```

identity primitives 至少：

```text
feature_run_id
feature manifest hash
feature semantic hash
feature finding set hash
feature_set_id / version / registry hash
state_set_id / version
state_registry_version / state_registry_hash
state_contract_version
state_builder_code_fingerprint
```

推荐：

```text
state_base_hash = sha256(canonical_json(primitives))
state_run_id = UUID5(STATE_NAMESPACE, state_base_hash)
```

禁止：

```text
random UUID
wall-clock
host timezone
DB insertion order
thread scheduling
latest alias
```

同一个 Verified Feature world + 相同 Registry/code 必须得到相同 state_run_id。

Registry / code / Feature run 改变必须得到新 identity。

---

# 10. State artifacts

V1 exact artifact set：

```text
observed_market_state.parquet
state_findings.parquet
manifest.json
```

建议路径：

```text
state/contract=state-v1/feature=<feature_run_id>/run=<state_run_id>/
```

## 10.1 Findings

State findings 只允许描述 State rule 无法产生完整状态的原因，例如：

```text
INSUFFICIENT_BREADTH_INPUT
INSUFFICIENT_TREND_INPUT
INSUFFICIENT_MOMENTUM_INPUT
INSUFFICIENT_RETURN_DISTRIBUTION_INPUT
```

不要把 Feature finding 原样复制进 State findings。

Feature finding 已经有独立 artifact / seal；State 只记录“State rule 因 upstream 已验证的缺失值而无法判定该维度”。

State findings deterministic exact set。

---

# 11. Immutable / recoverable publication

完全继承 CR-4/CR-5 publication contract：

```text
missing path + expected bytes -> write
same path + same bytes        -> no-op
same path + different bytes   -> hard conflict / DAMAGED
artifacts first
manifest last among correctness files
ledger last
```

文件写完、ledger commit 失败：

```text
exact retry
-> same state_run_id
-> identical existing bytes accepted
-> missing expected bytes repaired
-> ledger recovered
```

禁止：

```text
rm -rf same run id
random suffix
silent overwrite
new random id to hide conflict
```

---

# 12. State ledger / migration

建议 migration：

```text
024_state_build.sql
```

migration 023 冻结，不修改。

建议 `meta_state_build` 至少字段：

```text
state_run_id
feature_run_id
feature_manifest_uri
feature_manifest_hash
feature_semantic_hash
feature_finding_set_hash
state_set_id
state_set_version
state_registry_version
state_registry_hash
state_contract_version
state_builder_code_fingerprint
manifest_uri
manifest_hash
artifact_set_hash
state_semantic_hash
finding_set_hash
state_row_count
finding_count
status
error_message
started_at
completed_at
```

correctness identity 不使用 audit timestamps。

Migration tests：

```text
from-zero
023 -> 024
idempotent migrate
checksum/tamper guard
```

---

# 13. Public State verifier

必须提供：

```python
verify_state_run_for_consumption(
    state_run_id: str,
) -> VerifiedStateRun
```

Verifier 必须重新证明：

1. ledger row exists；
2. status == SUCCESS；
3. error_message is NULL；
4. deterministic manifest URI；
5. manifest bytes == ledger manifest_hash；
6. manifest correctness fields == ledger；
7. current State Registry exact identity；
8. full state identity primitives physical recompute；
9. UUID5 run-id cross-bind；
10. public Feature verifier still accepts source `feature_run_id`；
11. upstream Feature manifest/semantic/finding provenance unchanged；
12. artifact exact set；
13. exact bytes -> content hash；
14. physical schema -> schema_hash；
15. physical row counts；
16. physical semantic hashes；
17. state findings exact seal；
18. State rows stable order + unique trade_date；
19. copied `input_*` values exact equal Verified Feature market row；
20. PIT `state_available_at` exact equal source market feature availability；
21. replay current State Registry/engine from VerifiedFeatureRun；
22. actual State artifact rows == deterministic replay rows exact。

Builder 与 verifier 必须共享同一个 State execution implementation，不允许两套公式。

---

# 14. Suggested modules

```text
src/ashare_state/state/
    __init__.py
    registry.py
    models.py
    schema.py
    engine.py
    builder.py
    verifier.py

migrations/
    024_state_build.sql

tests/integration/
    test_state.py
```

Required new ADR：

```text
docs/adr/ADR-026_observed_market_state_contract.md
```

---

# 15. ADR-026 必须回答的问题

1. 为什么 State 只能消费 Verified Feature run？
2. 为什么 V1 one State run = one Feature run？
3. 为什么 V1 只消费 market_daily_features，不重新做 security cross-sectional Feature？
4. 为什么 breadth direction 使用 advancer_count vs decliner_count，而不是错误把 advancer_ratio<0.5 称为 decliner majority？
5. 为什么 MA20 / MOM20 使用数学 majority boundary 0.5？
6. 为什么 overall state 使用 unanimous consensus，而不是 score/weight？
7. 为什么不直接使用 bull/bear 命名？
8. 为什么 V1 禁止 hysteresis / smoothing / future confirmation？
9. state_available_at 与 state lineage 如何定义？
10. 为什么 State input values 要 exact copy 以保证解释性？
11. State identity primitives 和 no-wall-clock 原则？
12. State artifact 与 findings 的 seal/replay？
13. 为什么 migration 024 additive，023 冻结？
14. Future richer regime taxonomy 如何 version，而不是回测调参？
15. Alternatives / tradeoffs：weighted score、z-score、historical percentile、HMM/clustering、bull/bear labels、direct Feature artifact read、multi-run fusion。

---

# 16. Mandatory CR-6 Test Matrix

至少覆盖以下 **60 项语义 / gate**；允许 parametrization，但必须建立 1..60 mapping。

## A. Input boundary / identity 1–10

1. healthy Verified Feature SUCCESS accepted；
2. unknown feature_run rejected；
3. damaged Feature artifact rejected；
4. rebound Feature seals rejected upstream；
5. builder API requires explicit feature_run_id + state_set_id；
6. no latest/best/fallback API static guard；
7. one Feature run only / no fusion；
8. wrong feature_set_id rejected；
9. wrong feature_contract_version rejected；
10. wrong universe/price/window semantics rejected。

## B. Registry honest execution 11–18

11. Registry static/versioned；
12. unknown state_set rejected；
13. rule id drift fails closed；
14. majority threshold 0.5 -> changed declaration fails closed unless supported new version；
15. missingness rule drift fails closed；
16. output enum drift fails closed；
17. extra unimplemented State dimension fails closed；
18. blocked semantics typed / exact set。

## C. Breadth / trend / momentum exact boundaries 19–31

19. advancers > decliners -> breadth POSITIVE；
20. advancers < decliners -> NEGATIVE；
21. equal -> BALANCED；
22. no valid raw return -> INSUFFICIENT + finding；
23. MA20 ratio >0.5 -> POSITIVE；
24. MA20 ratio <0.5 -> NEGATIVE；
25. MA20 ratio ==0.5 -> BALANCED；
26. MA20 denominator zero/null -> INSUFFICIENT；
27. MOM20 ratio >0.5 -> POSITIVE；
28. MOM20 ratio <0.5 -> NEGATIVE；
29. MOM20 ratio ==0.5 -> BALANCED；
30. MOM20 denominator zero/null -> INSUFFICIENT；
31. no NaN/Inf in copied state evidence。

## D. Return + overall state 32–39

32. mean/median positive -> return POSITIVE；
33. mean/median negative -> NEGATIVE；
34. both zero -> FLAT；
35. opposite signs -> MIXED；
36. null -> INSUFFICIENT；
37. three core POSITIVE -> UP_CONSENSUS；
38. three core NEGATIVE -> DOWN_CONSENSUS；
39. any other valid combination -> MIXED；any core insufficient -> overall INSUFFICIENT。

## E. PIT / lineage / determinism 40–48

40. state_available_at exact source market feature_available_at；
41. available_at > upstream as_of rejected；
42. future Feature row cannot alter earlier State row；
43. input order does not change truth；
44. upstream market input value mutation changes replay/state；
45. upstream market lineage mutation changes State lineage；
46. unrelated future row mutation does not change historical lineage；
47. same Feature/Registry/code => same state_run_id；
48. Registry/code/Feature identity change => different state_run_id。

## F. Artifacts / verifier / recovery 49–56

49. exact artifact set；
50. content tamper rejected；
51. schema rebind rejected；
52. business value + all outer seals rebind rejected by replay；
53. copied input_* mismatch rejected；
54. ledger failure exact retry recovery；
55. partial identical residue recovery；
56. conflicting residue refusal。

## G. Migration / scope / CI 57–60

57. migration 024 from-zero / 023→024 / idempotency / tamper；
58. static import guard: no Provider/Raw/CR2/Canonical/Snapshot/ReadModel direct consumption；
59. no strategy/backtest/score/rank/position/forecast/hysteresis code；
60. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff / format / mypy / full pytest / Spike / SDK / governance gates all green。

---

# 17. CR-6 Exit Gate

CR-6 只有以下全部成立才允许关闭：

```text
[ ] PR #3 merged before CR-6 product code ancestry
[ ] ADR-025 governance sync ACCEPTED
[ ] ADR-026 complete / PROPOSED for review
[ ] public Feature verifier is sole value boundary
[ ] explicit feature_run_id/state_set_id only
[ ] one state run = one Feature run
[ ] State Registry exact/honest execution
[ ] only market_daily_features consumed in V1
[ ] breadth exact count-comparison semantics
[ ] MA20 majority exact semantics
[ ] MOM20 majority exact semantics
[ ] return sign-consensus exact semantics
[ ] overall unanimous-consensus exact semantics
[ ] no bull/bear predictive claim
[ ] no smoothing/hysteresis/future confirmation
[ ] no fitted thresholds / weights / backtest tuning
[ ] state_available_at PIT exact
[ ] State lineage deterministic
[ ] copied evidence exact to Feature
[ ] deterministic State identity
[ ] immutable/recoverable artifact publication
[ ] public State verifier exact replay
[ ] state findings exact seal
[ ] migration 024 additive; 023 untouched
[ ] Mandatory 1..60 mapping complete
[ ] frozen CR-5 regression matrix green
[ ] three-platform CI full green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR-000 synchronized
```

---

# 18. 明确禁止范围

CR-6 V1 禁止：

```text
predictive expected return
probability of rise/fall
bull/bear claims with hidden fitted meaning
weighted composite score
cross-sectional rank
security score
trading signal
entry/exit
position sizing
portfolio construction
backtest optimization
machine-learning classifier
HMM / clustering
future-labeled supervised state
historical percentile threshold
z-score threshold without governed Feature support
hysteresis / smoothing / confirmation days
adjusted-price inference
strict session-window reinterpretation
ALL_A_SHARES universe claim
industry/index state without Feature evidence
Provider / production / trading enablement
```

如果未来需要这些能力，必须作为新的 Research / Strategy / State Registry version 独立评审。

---

# 19. 推荐开发顺序

```text
CR-6.0
  merge ancestry check
  governance sync
  ADR-026
  State Registry / models / schema

CR-6.1
  deterministic State engine
  exact rule fixtures / PIT tests

CR-6.2
  identity / artifacts / ledger / migration 024
  recoverable publication

CR-6.3
  public State verifier
  replay / anti-rebind tests

CR-6.4
  mandatory mapping
  full regression / CI / governance closure
```

开发可以合并实现 commit，但 Reviewer 按以上逻辑层审查。

---

# 20. Owner View

CR-6 V1 的重点不是“预测市场”，而是把已经可信的 Feature 变成**一种可以客观解释、每天稳定重算、永远知道依据是什么的市场状态记录**。

例如：

```text
breadth       POSITIVE
trend breadth POSITIVE
momentum      POSITIVE
--------------------------------
observed state UP_CONSENSUS
```

这里的含义只是：

> 在当前 observed universe 与冻结的 raw-price / observed-bar 语义下，当日上涨/下跌广度、MA20 广度、MOM20 广度三个维度方向一致。

它不是：

> “系统预测明天上涨”或“应该买入”。

这种边界必须在平台阶段保持干净，未来量化策略研究才能把“事实状态”和“策略解释”分开评估，避免从回测结果倒推底层数据定义或 State 阈值。
