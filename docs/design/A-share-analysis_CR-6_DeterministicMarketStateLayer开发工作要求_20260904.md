# A-share-analysis：CR-6 Deterministic Market State Layer 开发工作要求

> **Date**：2026-09-04  
> **Reviewer Decision**：CR-5 已获最终关闭批准；本合同随 clean replacement PR #3 合入 `main` 后正式 START  
> **Upstream**：CR-4 VERIFIED/CLOSED/FREEZE；CR-5 VERIFIED/CLOSED/FREEZE；ADR-024 / ADR-025 ACCEPTED  
> **CR-6 Status**：**START AFTER PR #3 MERGE**  
> **Production P0-M-1B**：继续独立 BLOCKED  
> **New ADR Required**：ADR-026 — Deterministic Market State Interpretation Contract（初始 PROPOSED）

---

# 0. 目标与研究边界

CR-6 是当前流水线第一次允许进行**状态解释**的层，但它仍然不是预测层和策略层。

冻结研究宪法：

```text
Raw / Observation
      ↓
Canonical Fact
      ↓
Feature
      ↓
State / Regime
      ↓
Strategy Research
```

CR-6 必须回答：

> **“当前 Verified Feature world 呈现什么样的可解释市场结构？”**

而不得回答：

> “明天涨不涨？”  
> “应该买还是卖？”  
> “这个状态未来收益最好吗？”

V1.3.2 已明确：

```text
MA20_BREADTH = 0.72      是 Feature
趋势广度扩张             是 State
因此未来上涨概率更高       是独立 Research / Experiment 结论
```

同时冻结基线明确：

- 连续值优先；
- 不以“总情绪分数”为核心产物；
- 不把所有维度强行合成一个分数；
- State 与 Strategy 必须解耦；
- 参数不能从回测结果里倒推。

因此 CR-6 V1 采用**窄而诚实的描述性 State Set**，只消费 CR-5 已经真实拥有、已经验证的 market Feature。不得因为总体设计文档以后规划了 Trend/Breadth/Volatility/Stress/Rotation，就在当前事实层尚未提供这些输入时提前伪造完整 Phase-1 State。

---

# 1. 正式数据流

```text
Verified Feature SUCCESS
          ↓
verify_feature_run_for_consumption(feature_run_id)
          ↓
Static State Registry / Compiled State Execution Plan
          ↓
Deterministic State Engine
          ↓
Immutable Market State Artifact
          ↓
State Findings
          ↓
State Manifest / Ledger
          ↓
verify_state_run_for_consumption(state_run_id)
          ↓
Future Research / State Extension
```

**唯一正式上游：Verified Feature Run。**

State package 不得从 Raw / Provider-Normalized / Canonical / Snapshot / DuckDB ReadModel 重新获取事实，也不得自己重新实现 Feature 公式。

---

# 2. CR-6 硬边界

## 2.1 允许

- 显式消费一个 `feature_run_id`；
- 读取 public Feature verifier 返回的已验证 market feature rows；
- 对已冻结 Feature 值执行 versioned deterministic interpretation；
- 输出多维、可解释、非预测 State；
- 输出 deterministic findings / UNKNOWN；
- 保存 evidence projection、PIT、lineage、identity 和 replay seals。

## 2.2 禁止

CR-6 V1 禁止：

```text
Provider SDK
Raw / Provider-Normalized direct read
Canonical direct read
Snapshot direct read
DuckDB ReadModel direct read
Feature formula re-computation outside public Feature verifier
latest / best feature run selection
multi-feature-run fusion
hidden fallback
forward fill / backfill
adjusted-price inference
strict trading-session inference
ALL_A_SHARES universe claim
industry / theme / rotation inference
limit-up / ST / board inference
future return label
probability prediction
bull / bear predictive label
sentiment total score
weighted composite score
rank / signal / position / portfolio
strategy / backtest / execution model
parameter optimization from historical performance
machine-learned state classifier
production account / trading
```

如果未来需要这些能力，必须等待对应 Feature facts / Research contract，而不是在 State 层绕开缺失事实。

---

# 3. 新 ADR-026 必须回答的问题

ADR-026 至少回答：

1. 为什么 CR-6 只消费 Verified Feature Run，而不直接读 ReadModel/Snapshot？
2. 为什么 State 是“解释”，不是“预测”或“策略信号”？
3. 为什么 V1 不输出总情绪分数？
4. 为什么 V1 只使用当前 CR-5 已存在的 market Feature？
5. State Registry 如何成为 rule / dependency / threshold 的唯一真相？
6. 为什么 V1 阈值只采用数学上直接可解释的 **sign / majority / exact dominance**，不从回测选择 0.63、0.72 等样本最优值？
7. State row 的 evidence projection 如何与 Feature row exact cross-bind？
8. State `available_at` / lineage 如何保持 PIT？
9. UNKNOWN / insufficient evidence 如何表达，为什么不能 silent fallback？
10. State artifact 与 ledger 如何 deterministic / immutable / recoverable？
11. public State verifier 如何从 Verified Feature Run replay expected State？
12. 为什么 industry/theme/rotation、adjusted-price、strict-session、Stress/RAD 等当前仍 BLOCKED？
13. Alternatives / tradeoffs：
   - one global sentiment score；
   - arbitrary hand-tuned thresholds；
   - data-driven clustering；
   - direct Feature query without state artifact；
   - multi-feature-run fusion；
   - predictive regime label。

---

# 4. Public API 与输入世界

## P0-S01：Explicit Feature Run API

推荐：

```python
StateBuilder.build(
    feature_run_id: str,
    state_set_id: str,
) -> StateBuildResult
```

禁止：

```python
build_latest()
build_best()
build_current()
feature_run_id=None
```

一个 State Run 只对应一个 Feature Run。

## P0-S02：Public Feature Verifier Only

Builder 必须调用：

```python
verify_feature_run_for_consumption(feature_run_id)
```

并只使用 `VerifiedFeatureRun` 提供的已验证 rows / provenance。

StateBuilder 不允许：

- 自己查 `meta_feature_build` 后绕过 verifier；
- 自己打开 feature parquet；
- 自己打开 DuckDB ReadModel；
- 复制一套较弱 Feature verifier；
- 在 feature verifier 失败时使用 cached / best-effort state。

Feature status 不是 SUCCESS 或任何 upstream verification 失败：

```text
NO STATE ARTIFACT
```

---

# 5. Static State Registry

建议：

```text
src/ashare_state/state/registry.py
```

V1：

```text
STATE_SET_ID = "market-state-descriptive-v1"
STATE_REGISTRY_VERSION = "state-registry-v1"
STATE_CONTRACT_VERSION = "state-v1"
```

每个 `StateSpec` 至少声明：

```text
state_name
output_enum
required_feature_inputs
rule_id
threshold_policy
missingness_policy
availability_rule
interpretation
non_predictive_statement
eligibility
```

State Registry 是唯一 rule/dependency/threshold 真相。

Caller 不得传：

```text
bull_threshold
breadth_threshold
weight
score_weight
confidence_weight
```

## P0-S03：Honest State Execution Compiler

实现：

```python
compile_state_execution_plan(state_set)
```

必须机械验证：

- exact state_set id/version/registry version；
- exact state names/order；
- 每个 StateSpec 全字段；
- required_feature_inputs exact；
- rule_id -> one typed handler；
- threshold_policy exact；
- missingness / availability exact；
- no unsupported state；
- no duplicate / extra / hidden state；
- every SUPPORTED declaration has exactly one runtime handler。

禁止出现 CR-5 首批曾经发生过的：

```text
Registry 声明一套 rule
engine 实际硬编码另一套 rule
Builder 和 Verifier 又共同接受
```

---

# 6. CR-6 V1 允许的 State 维度

CR-6 V1 不追求“完整市场状态”。只构建当前 CR-5 market features 能直接支撑的**四个描述性维度**。

所有阈值均是直接语义边界：

```text
0      = 收益方向 sign boundary
0.5    = 占比 majority boundary
A > D  = 上涨数与下跌数 exact dominance
```

不得通过后续收益优化阈值。

---

## 6.1 `return_center_state`

输入：

```text
mean_raw_return_observed
median_raw_return_observed
```

规则：

```text
if either input is NULL:
    UNKNOWN
elif mean > 0 and median > 0:
    POSITIVE_CENTER
elif mean < 0 and median < 0:
    NEGATIVE_CENTER
else:
    MIXED_CENTER
```

解释：横截面收益中心整体偏正、偏负或均值/中位数不一致。

禁止把 `POSITIVE_CENTER` 解释为“后市看涨”。

---

## 6.2 `daily_participation_state`

输入：

```text
valid_raw_return_count
advancer_count
decliner_count
unchanged_count
```

必须先验证：

```text
advancer_count + decliner_count + unchanged_count
== valid_raw_return_count
```

规则：

```text
if valid_raw_return_count <= 0:
    UNKNOWN
elif advancer_count > decliner_count:
    ADVANCE_DOMINANT
elif decliner_count > advancer_count:
    DECLINE_DOMINANT
else:
    BALANCED
```

这里不使用 `advancer_ratio < 0.5 => decline`，因为大量 unchanged 时该推理不成立。

`advancer_ratio_observed` 可以作为 evidence cross-check：

```text
advancer_ratio_observed
== advancer_count / valid_raw_return_count
```

在 Feature verifier 已保证的前提下 State 可以再次做 defensive assertion；不重新定义 Feature。

---

## 6.3 `trend_participation_state`

输入：

```text
valid_ma20_count
pct_above_ma20_observed
valid_mom20_count
pct_positive_mom20_observed
```

规则：

```text
if either ratio is NULL
   or valid_ma20_count <= 0
   or valid_mom20_count <= 0:
    UNKNOWN
elif pct_above_ma20_observed > 0.5
     and pct_positive_mom20_observed > 0.5:
    BROAD_POSITIVE
elif pct_above_ma20_observed < 0.5
     and pct_positive_mom20_observed < 0.5:
    BROAD_NEGATIVE
else:
    MIXED
```

注意：

- 这里的 `20` 是 CR-5 的 **OBSERVED_SECURITY_BARS**，不是严格交易日；
- denominator 是 **OBSERVED_DAILY_BAR_UNIVERSE 中实际可比较证券集合**；
- `BROAD_POSITIVE` 是“当前观察样本内多数处于正向 20-observation 结构”，不是全 A 股、不是预测。

---

## 6.4 `market_structure_state`

这是一个**解释性组合枚举**，不是加权总分。

输入仅为前三个已解释 state dimension。

规则：

```text
if any required dimension == UNKNOWN:
    UNKNOWN

elif return_center_state == POSITIVE_CENTER
     and daily_participation_state == ADVANCE_DOMINANT
     and trend_participation_state == BROAD_POSITIVE:
    BROAD_ADVANCE

elif return_center_state == NEGATIVE_CENTER
     and daily_participation_state == DECLINE_DOMINANT
     and trend_participation_state == BROAD_NEGATIVE:
    BROAD_DECLINE

elif return_center_state == POSITIVE_CENTER:
    POSITIVE_MIXED_PARTICIPATION

elif return_center_state == NEGATIVE_CENTER:
    NEGATIVE_MIXED_PARTICIPATION

else:
    MIXED
```

解释边界：

- `BROAD_ADVANCE` / `BROAD_DECLINE` 是当日多维 evidence 同向确认；
- `POSITIVE_MIXED_PARTICIPATION` / `NEGATIVE_MIXED_PARTICIPATION` 表示收益中心与参与结构没有形成全维同向；
- `MIXED` 表示收益中心本身不一致或中性；
- 不宣称“主升”“熊市”“冰点”“高潮”“退潮”“反转机会”。

尤其禁止当前 V1 输出：

```text
SINGLE_MAINLINE
FAST_ROTATION
HIGH_DIVERGENCE
RISK_ON / RISK_OFF
BULL / BEAR
ICE_POINT / CLIMAX
```

因为当前 Feature contract 尚无足够 industry/theme/rotation/dispersion/stress facts 支撑这些状态。

---

# 7. State Findings / UNKNOWN 语义

## P0-S04：不丢日期

对于 Verified Feature artifact 中的每个 market feature row，State 必须输出 exactly one market state row。

证据不足时：

```text
state = UNKNOWN
```

而不是删除日期、forward-fill 前一天状态或自动使用较弱指标替代。

## P0-S05：Typed State Findings

建议 finding classes：

```text
STATE_INPUT_NULL
STATE_INPUT_EMPTY_DENOMINATOR
STATE_INPUT_INVARIANT_VIOLATION
STATE_RULE_UNAVAILABLE
```

正常“维度混合”不是 finding；`MIXED` 是合法 state。

Finding 必须 deterministic，包含：

```text
trade_date
state_name
finding_class
detail_json
```

不含 wall-clock correctness metadata。

---

# 8. Evidence Projection 与解释能力

## P0-S06：State artifact 必须携带所用证据，不做黑盒 label

`market_daily_state` 建议至少包含：

```text
trade_date
source_feature_run_id
source_snapshot_id
source_canonical_run_id
state_run_id
state_set_id
state_contract_version
state_available_at
source_feature_input_lineage_hash
input_lineage_hash
universe_rule_id

evidence_observed_security_count
evidence_valid_raw_return_count
evidence_advancer_count
evidence_decliner_count
evidence_unchanged_count
evidence_advancer_ratio_observed
evidence_mean_raw_return_observed
evidence_median_raw_return_observed
evidence_valid_ma20_count
evidence_pct_above_ma20_observed
evidence_valid_mom20_count
evidence_pct_positive_mom20_observed

return_center_state
daily_participation_state
trend_participation_state
market_structure_state
```

这些 `evidence_*` 字段只是 Verified Feature values 的 exact projection，不成为新的 Feature 事实所有者。

Verifier 必须证明：

```text
state evidence value
== exact source Feature market row value
```

这样查询者看到 `BROAD_ADVANCE` 时，可以同时看到它依据的实际连续值，而不是只有一个黑盒字符串。

---

# 9. PIT 与 State Lineage

## P0-S07：State Available Time

V1 四个 State 都只消费同一个 market feature row，因此：

```text
state_available_at
= source market feature row.feature_available_at
```

如果未来 State rule 消费多行/多 Feature row，则必须改为：

```text
max(actual consumed feature inputs available_at)
```

禁止使用 trade_date 代替 knowledge time。

## P0-S08：State Input Lineage

保留：

```text
source_feature_input_lineage_hash
```

即 CR-5 market feature row 原有 lineage。

另计算：

```text
state.input_lineage_hash
```

至少绑定：

```text
source_feature_run_id
trade_date
source_feature_input_lineage_hash
source feature_available_at
exact evidence feature names + typed values
state registry version/hash
state rule ids
```

原因：Feature upstream lineage 相同但 feature value 被非法修改时，State evidence lineage 也必须变化；public State verifier还会通过 upstream Feature replay独立阻断此类篡改。

---

# 10. Deterministic State Identity

## P0-S09：State Run Identity

建议 primitives：

```text
feature_run_id
feature_manifest_hash
feature_semantic_hash
feature_set_id
feature_registry_hash
state_set_id
state_set_version
state_registry_version
state_registry_hash
state_contract_version
state_builder_code_fingerprint
```

建议：

```text
state_base_hash = SHA256(canonical_json(primitives))
state_run_id    = UUID5(STATE_NAMESPACE, state_base_hash)
```

禁止：

```text
random UUID
wall-clock
database insertion order
host timezone
thread scheduling
```

同一 Verified Feature + 同一 State contract/code => 同一 state_run_id。

Registry/code/feature world 改变 => 新 state identity。

---

# 11. State Artifact Contract

## P0-S10：Exact V1 Artifact Set

建议：

```text
state/contract=state-v1/
  feature_run=<feature_run_id>/
  run=<state_run_id>/
    market_daily_state.parquet
    state_findings.parquet
    manifest.json
```

一个 State Run 不允许生成 security signal、portfolio 或 strategy artifact。

## P0-S11：Versioned Typed Schema

建议：

```text
src/ashare_state/state/schema.py
```

显式定义：

- columns/order；
- dtype；
- nullability；
- state enum values；
- key：`trade_date` unique；
- stable sort：trade_date；
- findings schema。

禁止 silent cast。

## P0-S12：Full Seals

每个 artifact：

```text
uri
content_hash
schema_hash
row_count
semantic_hash
```

Manifest 至少：

```text
state_run_id
state_base_hash
state contract version
state builder fingerprint
state set id/version
state registry version/hash
feature_run_id
feature manifest uri/hash
feature semantic hash
feature set id/registry hash
artifact exact set/seals
state_semantic_hash
finding_set_hash
state_row_count
finding_count
status
error_message
```

Manifest LAST。

Correctness bytes 不含 wall-clock；started/completed timestamp 只进 ledger audit fields。

---

# 12. Immutable / Recoverable Publication

## P0-S13

复用已经冻结的正确模式：

```text
path missing           -> write exact bytes
path exists same bytes -> idempotent no-op
path exists diff bytes -> hard conflict / DAMAGED
```

顺序：

```text
state artifacts
   ↓
manifest LAST
   ↓
ledger transaction LAST
```

文件写完 + ledger failure：

```text
exact retry
-> verify same deterministic bytes
-> no overwrite
-> recover ledger commit
```

partial identical residue 可补齐缺失文件；任何 conflicting residue fail closed。

禁止 rm-rf 后用同一个 state_run_id 重建，也禁止随机 suffix 回避冲突。

---

# 13. State Ledger / Migration

## P0-S14

若需要 ledger，新增：

```text
migration 024+
```

**migration 023 及以前全部 frozen，不得重写。**

建议：

```text
meta_state_build
```

至少：

```text
state_run_id
feature_run_id
feature_manifest_uri/hash
feature_semantic_hash
feature_set_id
feature_registry_hash
state_set_id/version
state_registry_version/hash
state_contract_version
state_builder_code_fingerprint
manifest_uri/hash
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

Migration 必须：

- from-zero；
- 023 -> 024 upgrade；
- idempotent migrate；
- checksum/tamper gates；
- 不改变 frozen historical migrations。

---

# 14. Public State Consumption Verifier

## P0-S15

正式 API：

```python
verify_state_run_for_consumption(state_run_id) -> VerifiedStateRun
```

必须验证：

1. state ledger row exists；
2. status == SUCCESS；
3. SUCCESS -> error_message NULL；
4. deterministic manifest URI；
5. manifest bytes == ledger manifest hash；
6. manifest correctness fields == ledger；
7. current State Registry exact bind；
8. builder fingerprint exact bind；
9. state identity primitives physical recompute；
10. UUID5 state_run_id cross-bind；
11. public Feature verifier重新验证 source feature run；
12. feature manifest/hash/semantic provenance exact bind；
13. artifact exact set；
14. exact bytes content hash；
15. exact bytes parse；
16. physical schema_hash；
17. physical rowcount；
18. semantic_hash；
19. state row key/order/enum/nullability；
20. every evidence_* exact equals Verified Feature row；
21. State Registry deterministic replay；
22. expected state rows == physical state rows exact；
23. expected findings == physical findings exact；
24. physical counts == manifest == ledger；
25. aggregate state/finding hashes physical recompute。

Builder 和 verifier 必须共用一个：

```text
compute_state_set(...)
```

或 equivalent deterministic execution function。

不得出现 Builder/Verifier 两套互相漂移的 rule implementation。

---

# 15. No Predictive Leakage / No Strategy Contamination

## P0-S16

State Engine 禁止 import：

```text
experiments
forward_labels
backtest
strategy
portfolio
execution
trading
```

State rule 不能访问：

```text
T+1 / T+3 / T+5 / future return
MFE / MAE
future volatility
strategy pnl
```

必须有静态 AST/import guard。

State Registry 的任何 threshold/rule 变更理由不得写：

```text
because backtest return improved
because Sharpe improved
because win rate improved
```

未来 State quality 与 Strategy value 研究属于独立 Experiment 阶段。

---

# 16. CR-6 Mandatory Test Matrix

不要求机械制造 60 个独立 test functions，允许 parametrization；但必须在工作要求中建立逐项 mapping。

## Group A — Input Boundary / World Identity（1–10）

1. intact Feature SUCCESS passes StateBuilder。
2. unknown feature_run_id refused。
3. non-SUCCESS Feature refused。
4. damaged Feature manifest refused。
5. damaged Feature artifact refused。
6. damaged Feature finding truth refused。
7. foreign/tampered upstream ReadModel causing Feature verifier failure -> zero State publish。
8. explicit feature_run_id API signature guard。
9. no latest/best/current helper guard。
10. two distinct feature_run_id -> distinct state identity / path。

## Group B — State Registry Honest Execution（11–20）

11. unknown state_set_id refused。
12. state rule id drift refused before artifact write。
13. required feature list drift refused。
14. threshold policy drift refused。
15. missingness policy drift refused。
16. availability rule drift refused。
17. output enum drift refused。
18. extra state declaration refused。
19. SUPPORTED state without handler refused。
20. caller cannot inject thresholds/weights。

## Group C — Exact Rule Semantics（21–34）

21. mean>0 + median>0 -> POSITIVE_CENTER。
22. mean<0 + median<0 -> NEGATIVE_CENTER。
23. opposite signs / zero boundary -> MIXED_CENTER。
24. null return-center evidence -> UNKNOWN + finding。
25. advancers>decliners -> ADVANCE_DOMINANT。
26. decliners>advancers -> DECLINE_DOMINANT。
27. equal -> BALANCED。
28. count invariant mismatch -> fail closed or exact typed invariant finding per ADR decision；不得静默继续。
29. both trend ratios >0.5 -> BROAD_POSITIVE。
30. both <0.5 -> BROAD_NEGATIVE。
31. equality 0.5 / split directions -> MIXED。
32. null / zero-valid denominator -> UNKNOWN。
33. all positive components -> BROAD_ADVANCE；all negative -> BROAD_DECLINE。
34. positive/negative center without full participation confirmation -> corresponding MIXED_PARTICIPATION；center mixed -> MIXED。

## Group D — Evidence / PIT / Lineage（35–44）

35. state row count == Feature market row count。
36. no date drop when evidence unavailable。
37. evidence_* exact copies source Feature values。
38. evidence tamper + rebound outer seals refused by replay。
39. source Feature lineage mutation in a new verified world changes State input lineage。
40. evidence feature value change in a new verified world changes State input lineage/state where applicable。
41. state_available_at == source feature_available_at。
42. future Feature row cannot change earlier State row。
43. input order does not change State semantic hash。
44. host timezone does not change State identity/bytes。

## Group E — Identity / Artifact / Recovery（45–56）

45. deterministic state_run_id same world same code。
46. State Registry hash change changes state identity。
47. State builder fingerprint change changes state identity。
48. artifact byte determinism exact retry。
49. manifest LAST structural/failure test。
50. ledger commit failure exact retry recovery。
51. partial identical residue recovery。
52. conflicting residue refusal。
53. artifact content tamper refused。
54. schema/rowcount/semantic pair-rebind refused by physical recompute。
55. state business value + all outer seals rebound refused by Feature replay。
56. finding value + all outer seals rebound refused。

## Group F — Migration / CI / Scope Guard（57–64）

57. migration from zero。
58. 023 -> 024 upgrade。
59. repeated migrate idempotent。
60. migration checksum/tamper gate。
61. no Provider/Raw/Canonical/Snapshot/ReadModel direct import/use in State package。
62. no Feature formula implementation duplicated in State package。
63. no Strategy/Experiment/ForwardLabel/Backtest imports；no future columns。
64. full frozen 1320+ regression + Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff / format / mypy / full pytest / Spike / SDK / governance gates。

---

# 17. Recommended Module Layout

```text
src/ashare_state/state/
  __init__.py
  registry.py
  models.py
  schema.py
  engine.py
  builder.py
  verifier.py
```

测试：

```text
tests/integration/test_state.py
```

Migration：

```text
migrations/024_state_build.sql
```

如最终不需要 migration，可不强行新增；但 state ledger 若要持久化，必须走正式 migration。

---

# 18. Recommended Implementation Sequencing

## CR-6.0 — Governance + ADR + Contract Skeleton

第一笔 CR-6 commit：

- 同步 CR-5 final closure governance；
- ADR-025 -> ACCEPTED；
- ADR-000 sync；
- DEVLOG append-only；
- DEVELOPMENT_MANAGEMENT -> CR-6 START；
- 新建 ADR-026 PROPOSED；
- State registry/models/schema skeleton；
- 不先写大量 state engine 逻辑。

## CR-6.1 — Registry + Engine Rule Truth

完成：

- State Registry；
- compile execution plan；
- four V1 dimensions；
- typed findings；
- tests 11–44。

## CR-6.2 — Identity / Artifact / Ledger / Replay

完成：

- deterministic state identity；
- Builder；
- artifacts；
- migration 024 if used；
- immutable/recoverable write；
- public verifier；
- tests 1–10 + 45–60。

## CR-6.3 — Full Closure

完成：

- static scope guards；
- full 1320+ upstream regression；
- three-leg CI；
- ADR-026 implementation mapping；
- DEVLOG/Management sync；
- Reviewer final closure。

开发人员可以在一个提交完成多层，但 Reviewer 按上述逻辑层审查。

---

# 19. CR-6 Exit Gate

全部成立才允许 CR-6 CLOSED/FREEZE：

```text
[ ] PR #3 merged; CR-5 mainline closure effective
[ ] ADR-025 governance synchronized as ACCEPTED
[ ] ADR-026 complete and reviewable
[ ] State consumes public Verified Feature only
[ ] explicit feature_run_id + state_set_id API only
[ ] one State Run = one Feature Run
[ ] no latest/best/fallback/fusion
[ ] static State Registry is execution truth
[ ] exact V1 state rules frozen
[ ] no arbitrary backtest-selected threshold/weight
[ ] no total sentiment score
[ ] no predictive / strategy semantics
[ ] every Feature market date -> exactly one State row
[ ] UNKNOWN/finding semantics deterministic
[ ] evidence projection exact-bound to Feature row
[ ] state_available_at PIT correct
[ ] state lineage deterministic and truthful
[ ] deterministic state identity
[ ] versioned typed schema / enum
[ ] exact artifact set and full physical seals
[ ] immutable/recoverable publication
[ ] public State verifier full replay
[ ] all-seal business-value rebind refused
[ ] migration gates green if migration used
[ ] no direct Raw/Canonical/Snapshot/ReadModel access
[ ] no Feature formula duplication
[ ] no future labels / Experiment / Strategy imports
[ ] full frozen upstream regression green
[ ] Mandatory 1..64 mapping complete
[ ] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR sync
```

---

# 20. 明确延期到未来的数据语义

当前 CR-6 不得为了“状态看起来更完整”自行补这些能力：

```text
完整 Trend State
Volatility Regime
Stress State
RAD / limit-normalized stress
Industry / Theme leadership
Rotation speed
single-mainline / multi-mainline
risk appetite
style regime
adjusted-return trend
strict trading-session trend
ALL_A total-market breadth
```

原因不是这些概念不重要，而是**当前 frozen CR-5 V1 还没有足够的 Verified Feature facts 支撑它们**。

正确解锁方式：

```text
先新增 / 验证对应 Feature contract
        ↓
Feature Registry 新版本
        ↓
Feature artifact / verifier closure
        ↓
再增加 State Registry 新版本
```

禁止 State 层自己跨层补数据。

---

# 21. Owner View

CR-6 V1 完成后，系统应能够对每个 market date 输出类似：

```text
trade_date: 2026-08-20

Evidence:
  mean_return_observed          +0.0041
  median_return_observed        +0.0027
  advancers                     3120
  decliners                     1710
  pct_above_ma20_observed       0.64
  pct_positive_mom20_observed   0.59

State:
  return_center_state           POSITIVE_CENTER
  daily_participation_state     ADVANCE_DOMINANT
  trend_participation_state     BROAD_POSITIVE
  market_structure_state        BROAD_ADVANCE
```

它表达的是：

> **“在这个明确的 Verified Feature knowledge world 中，市场收益中心、当日参与面和 20-observation 参与结构同时偏正。”**

它不表达：

> “明天会上涨。”  
> “应该加仓。”  
> “这是牛市。”

这种分层是后续策略研究能够长期可信的前提。


---

# 22. CR-6.4 Final Adversarial / Contract-Honesty Addendum

> **Reviewer state**：CR-6.0–6.3 PASS / KEEP；CR-6 remains **DONE / REOPENED**；CR-6.4 remains **START / ACTIVE** pending human review. PR #6 must remain open and must not be merged automatically.
>
> **Implementation head**：`e47514a8afc864c9f197e18f95ea56fe81424a2d`; current main `2dc63e803af908baa3424d576b17d8b07751e05f` was merged normally into the branch by two-parent merge commit `bdb112213dc64325ccc3931a1c0617ae448ef93d`. No history rewrite was used.
>
> **CI evidence**：GitHub Actions run `33836243605` (run 213) passed on Ubuntu 3.14, Windows 3.12, and Windows 3.14. Each leg reported `1401 passed`; Ruff lint/format, mypy, Spike, and SDK-absent checks passed. The applicable Windows 3.14 DEVLOG and Management gates passed.

This addendum is an evidence mapping for the frozen Group A–F matrix above. It does not add State dimensions or predictive/strategy scope. Items 2–7 are the State builder's zero-publication propagation matrix for the named upstream failure classes; the full upstream Feature adversarial suite remains covered by the complete CI regression.

The persisted finding contract is deliberately narrower than the fatal error contract: only `STATE_INPUT_NULL` and `STATE_INPUT_EMPTY_DENOMINATOR` may be written to `state_findings`. `STATE_INPUT_INVARIANT_VIOLATION` and `STATE_RULE_UNAVAILABLE` are typed fatal error codes; they are raised before State artifact publication, cannot be published as findings, and an injected fatal finding class is rejected by the public verifier.

| ID | Frozen requirement | Concrete implementation evidence |
|---:|---|---|
| 1 | intact Feature SUCCESS | `tests/integration/test_state_persistence.py::test_builder_publishes_and_public_verifier_replays` |
| 2 | unknown feature_run_id | `tests/integration/test_state_persistence.py::test_feature_verifier_failure_matrix_publishes_nothing` — parameter `unknown feature_run_id` |
| 3 | non-SUCCESS Feature | `tests/integration/test_state_persistence.py::test_feature_verifier_failure_matrix_publishes_nothing` — parameter `non-SUCCESS Feature` |
| 4 | damaged Feature manifest | `tests/integration/test_state_persistence.py::test_feature_verifier_failure_matrix_publishes_nothing` — parameter `damaged Feature manifest` |
| 5 | damaged Feature artifact | `tests/integration/test_state_persistence.py::test_feature_verifier_failure_matrix_publishes_nothing` — parameter `damaged Feature artifact` |
| 6 | damaged Feature finding | `tests/integration/test_state_persistence.py::test_feature_verifier_failure_matrix_publishes_nothing` — parameter `damaged Feature finding` |
| 7 | foreign/tampered upstream ReadModel | `tests/integration/test_state_persistence.py::test_feature_verifier_failure_matrix_publishes_nothing` — parameter `foreign ReadModel` |
| 8 | explicit feature_run_id API | `tests/integration/test_state.py::test_state_builder_requires_explicit_world_arguments` |
| 9 | no latest/best/current helper | `tests/integration/test_state.py::test_state_builder_has_no_implicit_world_helpers` |
| 10 | distinct feature worlds mint distinct State identity/path | `tests/integration/test_state_persistence.py::test_two_feature_runs_have_distinct_state_identity_and_path` |
| 11 | unknown state_set_id | `tests/integration/test_state.py::test_unknown_state_set_refused` |
| 12 | rule_id drift | `tests/integration/test_state.py::test_registry_field_drift_refused` — mutation `rule_id=FOREIGN_RULE` |
| 13 | required feature list drift | `tests/integration/test_state.py::test_registry_field_drift_refused` — mutation `required_feature_inputs=(foreign_feature,)` |
| 14 | threshold policy drift | `tests/integration/test_state.py::test_registry_field_drift_refused` — mutation `threshold_policy=BACKTEST_OPTIMIZED` |
| 15 | missingness policy drift | `tests/integration/test_state.py::test_registry_field_drift_refused` — mutation `missingness_policy=SILENT_DROP` |
| 16 | availability rule drift | `tests/integration/test_state.py::test_registry_field_drift_refused` — mutation `availability_rule=TRADE_DATE` |
| 17 | output enum drift | `tests/integration/test_state.py::test_registry_field_drift_refused` — mutation `output_enum=(BULL, BEAR)` |
| 18 | extra state declaration | `tests/integration/test_state.py::test_extra_state_declaration_refused` |
| 19 | SUPPORTED declaration without handler | `tests/integration/test_state.py::test_supported_declaration_without_handler_refused` |
| 20 | caller cannot inject threshold/weight | `tests/integration/test_state.py::test_caller_cannot_inject_thresholds_or_weights` |
| 21 | positive center sign rule | `tests/integration/test_state.py::test_return_center_exact_sign_semantics` — parameter `(0.01, 0.001, POSITIVE_CENTER)` |
| 22 | negative center sign rule | `tests/integration/test_state.py::test_return_center_exact_sign_semantics` — parameter `(-0.01, -0.001, NEGATIVE_CENTER)` |
| 23 | opposite signs and zero boundary | `tests/integration/test_state.py::test_return_center_exact_sign_semantics` — parameters `(0.01,-0.001)`, `(0,0.001)`, `(0,0)` -> `MIXED_CENTER` |
| 24 | null return-center evidence | `tests/integration/test_state.py::test_return_center_null_is_unknown_with_finding` |
| 25 | advancers dominate | `tests/integration/test_state.py::test_daily_participation_exact_dominance` — parameter `(6,3,ADVANCE_DOMINANT)` |
| 26 | decliners dominate | `tests/integration/test_state.py::test_daily_participation_exact_dominance` — parameter `(3,6,DECLINE_DOMINANT)` |
| 27 | equal participation | `tests/integration/test_state.py::test_daily_participation_exact_dominance` — parameter `(4,4,BALANCED)` |
| 28 | count invariant fatal and zero publication | `tests/integration/test_state.py::test_daily_participation_count_invariant_fails_closed` plus `tests/integration/test_state_persistence.py::test_state_invariant_failure_is_typed_and_publishes_nothing` — exact `STATE_INPUT_INVARIANT_VIOLATION`, zero artifacts and zero ledger rows |
| 29 | both trend ratios above majority | `tests/integration/test_state.py::test_trend_participation_majority_semantics` — parameter `(0.7,0.8,BROAD_POSITIVE)` |
| 30 | both trend ratios below majority | `tests/integration/test_state.py::test_trend_participation_majority_semantics` — parameter `(0.3,0.2,BROAD_NEGATIVE)` |
| 31 | trend equality/split | `tests/integration/test_state.py::test_trend_participation_majority_semantics` — parameters `(0.5,0.5)` and `(0.7,0.3)` -> `MIXED` |
| 32 | trend null/zero denominator | `tests/integration/test_state.py::test_trend_null_and_empty_denominator_are_unknown` |
| 33 | all-positive/all-negative composition | `tests/integration/test_state.py::test_market_structure_exact_composition` — parameter cases `{}` -> `BROAD_ADVANCE` and negative inputs -> `BROAD_DECLINE` |
| 34 | mixed participation/center composition | `tests/integration/test_state.py::test_market_structure_exact_composition` — positive/negative mixed participation and mixed center cases; `test_market_structure_unknown_when_dimension_unknown` |
| 35 | one State row per Feature market date | `tests/integration/test_state.py::test_every_feature_market_date_produces_one_state_row` |
| 36 | no date drop for unavailable evidence | `tests/integration/test_state.py::test_return_center_null_is_unknown_with_finding` and `test_daily_participation_zero_valid_is_unknown_with_finding` — row retained as `UNKNOWN` |
| 37 | exact evidence projection | `tests/integration/test_state.py::test_evidence_projection_is_exact` |
| 38 | evidence rebind plus outer-seal rebind rejected | `tests/integration/test_state_persistence.py::test_evidence_rebind_is_rejected_by_independent_feature_replay` |
| 39 | source lineage mutation changes State lineage | `tests/integration/test_state.py::test_source_lineage_and_evidence_lineage_are_separate` — changed `input_lineage_hash` case |
| 40 | evidence value mutation changes State lineage | `tests/integration/test_state.py::test_source_lineage_and_evidence_lineage_are_separate` — changed `mean_raw_return_observed` case |
| 41 | PIT available_at | `tests/integration/test_state.py::test_state_available_at_is_feature_available_at` |
| 42 | future row cannot change prior State row | `tests/integration/test_state.py::test_future_feature_row_does_not_change_prior_state_row` |
| 43 | input-order determinism | `tests/integration/test_state.py::test_input_order_does_not_change_semantic_hash` |
| 44 | host-timezone determinism | `tests/integration/test_state_persistence.py::test_wall_clock_timezone_does_not_change_identity_or_bytes` |
| 45 | same world/code deterministic state_run_id | `tests/integration/test_state.py::test_state_identity_is_deterministic_for_same_world` |
| 46 | State Registry hash mints new identity | `tests/integration/test_state.py::test_registry_and_builder_identity_fingerprints_mint_new_state_run` — parameter `state_registry_hash` |
| 47 | Builder fingerprint mints new identity | `tests/integration/test_state.py::test_registry_and_builder_identity_fingerprints_mint_new_state_run` — parameter `state_builder_code_fingerprint` |
| 48 | exact retry artifact bytes | `tests/integration/test_state_persistence.py::test_artifact_bytes_are_deterministic_on_exact_retry` |
| 49 | manifest last and failure has no SUCCESS ledger | `tests/integration/test_state_persistence.py::test_manifest_is_last_and_failure_has_no_success_ledger` |
| 50 | ledger failure exact retry recovery | `tests/integration/test_state_persistence.py::test_ledger_commit_failure_exact_retry_recovers` |
| 51 | partial identical residue recovery | `tests/integration/test_state_persistence.py::test_partial_identical_residue_recovers` |
| 52 | conflicting residue refusal | `tests/integration/test_state_persistence.py::test_conflicting_residue_refuses_without_new_identity` |
| 53 | tampered State artifact refusal | `tests/integration/test_state_persistence.py::test_tampered_state_artifact_is_rejected` |
| 54 | schema/row-count/semantic physical recompute | `tests/integration/test_state_persistence.py::test_physical_recompute_rejects_state_pair_rebind` — parameters `schema`, `row_count`, `semantic` |
| 55 | business State rebind plus all seals | `tests/integration/test_state_persistence.py::test_business_state_rebind_is_rejected_by_independent_replay` |
| 56 | finding rebind plus all seals | `tests/integration/test_state_persistence.py::test_finding_rebind_is_rejected_by_deterministic_replay` |
| 57 | migration from zero | `tests/integration/test_migrations.py::TestFromZeroInit::test_all_tables_created` |
| 58 | 023 -> 024 upgrade | `tests/integration/test_migrations.py::TestLedgerIntegrity::test_upgrade_from_prior_chain_applies_only_new_tail` |
| 59 | migration idempotency | `tests/integration/test_migrations.py::TestFromZeroInit::test_idempotent_rerun` |
| 60 | migration checksum/tamper gate | `tests/integration/test_migrations.py::TestTamperDetection::test_modified_applied_migration_blocks` |
| 61 | State import boundary | `tests/integration/test_state_scope.py::test_state_import_boundary_is_explicit` |
| 62 | no duplicated Feature implementation | `tests/integration/test_state_scope.py::test_state_does_not_duplicate_feature_implementation` |
| 63 | no research/predictive identifiers and no future columns | `tests/integration/test_state_scope.py::test_state_contains_no_research_or_predictive_identifiers` plus `test_state_columns_are_the_frozen_non_future_contract` |
| 64 | three-platform full CI and gates | GitHub Actions run `33836243605` (run 213), implementation head `e47514a8afc864c9f197e18f95ea56fe81424a2d`: Ubuntu 3.14, Windows 3.12, Windows 3.14 each `1401 passed`; Ruff lint/format, mypy, Spike, SDK-absent passed; Windows 3.14 DEVLOG/Management gates passed |

The mapping is concrete at the test and parameter/case level. Parameterized rows are not counted as undocumented test functions: every listed case is executed by the repository's pytest matrix. Group F-64 records the post-merge implementation-head verification; docs synchronization must retain the same three-platform gate and remain green before reviewer closure.


> **Documentation synchronization evidence**：The documentation synchronization commit `f293e696e3fe8b751a56b51a2d4b4b8b3892c318` was independently verified by GitHub Actions run `33837386772` (run 214): Ubuntu 3.14, Windows 3.12, and Windows 3.14 each completed successfully with 1401 tests passed; Ruff lint/format, mypy, Spike, SDK-absent, and the applicable Windows 3.14 DEVLOG/Management gates passed. This is audit evidence for the synchronized documentation head; it does not change the pending human-review status. The State contract remains pending human review; this evidence does not authorize PR merge or CR-6 CLOSED/FREEZE.
