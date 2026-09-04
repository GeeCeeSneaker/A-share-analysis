# A-share-analysis：CR-5.1 复审与 CR-5.2 Bounded Lineage Complexity 收口要求

> **Review Date**：2026-09-03 21:42 +08:00  
> **Upstream Reviewer Baseline**：`aa24751b18437e24b48aaf5bfc3b9ae3382e90fd`  
> **Reviewed Branch**：`codex/cr-5-feature-layer-20260903`  
> **Reviewed Branch HEAD**：`a92c71b4c65af0723d611318247d522b3207d6c9`  
> **Primary CR-5.1 Implementation**：`9f7cc9aee3f3f3021af603aefdebf19258558847`  
> **CR-5.1 Code/Test Head**：`06106c27652e14f13d360fd3e153ececb39a4434`  
> **Latest Reviewed CI-green Branch HEAD**：`a92c71b4c65af0723d611318247d522b3207d6c9`  
> **CI**：run `33758109611`（code/test head）SUCCESS；run `33759993886`（latest branch head）SUCCESS；Windows 3.12 / Windows 3.14 / Ubuntu 3.14 全绿  
> **PR**：#2 OPEN / MERGEABLE / NOT MERGED  
> **Verdict**：**CR-5.1 correctness VERIFIED / CLOSED / FREEZE；CR-5 继续 DONE / REOPENED，仅剩 P1 bounded-lineage complexity；CR-5.2 START / ACTIVE；ADR-025 保持 PROPOSED；PR #2 暂不合并；CR-6 继续 BLOCKED**

---

# 0. Reviewer 总结

CR-5.1 已把上一轮 Reviewer 提出的 correctness closure gap 实质关闭。当前不再存在足以继续重开 CR-5.1 correctness 的 P0 blocker。

正式裁决：

```text
CR-4 all chain                         VERIFIED / CLOSED / FREEZE
CR-5 first-batch architecture          PASS / KEEP
CR-5.1 Registry Honest Execution       VERIFIED / CLOSED / FREEZE
CR-5.1 Feature Seal Closure            VERIFIED / CLOSED / FREEZE
CR-5.1 Numeric/Finding Closure         VERIFIED / CLOSED / FREEZE
CR-5.1 Mandatory Matrix Mapping        VERIFIED / CLOSED / FREEZE
CR-5                                    DONE / REOPENED (one P1 only)
CR-5.2 Bounded Lineage Complexity       START / ACTIVE
ADR-025                                 PROPOSED until CR-5 final closure
PR #2                                   DO NOT MERGE yet
CR-6                                    BLOCKED_BY_CR-5.2
Production P0-M-1B                      BLOCKED independently
```

CR-5.2 不允许重新设计 Feature 公式、Feature Registry 名称、价格口径、窗口语义、market breadth 语义或 artifact contract；它只处理上一轮 Reviewer 已明确要求“CR-5 最终 FREEZE 前必须处理或显式延期”的 **P1-02 asymptotic complexity**。

---

# 1. CR-5.1 已验证关闭项

## 1.1 Registry Honest Execution — VERIFIED / FREEZE

当前 `compile_feature_execution_plan(feature_set)` 已成为正式 V1 execution contract compiler。

它机械验证：

```text
FeatureSet type
feature_set_id/version
feature_registry_version
price_basis
universe_rule_id
exact feature names + exact order
typed blocked semantics exact set
每个 FeatureSpec 全字段 equality
formula_rule_id -> typed exact handler
exact handler coverage / no duplicate / no extra feature
```

因此以下 world 均 fail closed before artifact publication：

```text
ma_close_obs_20 window 20 -> 17
return_lag_obs_20 lag 20 -> 17
unknown formula_rule_id
unknown denominator_policy
unknown missingness_policy
unknown availability_rule
OBSERVED_SECURITY_BARS -> MARKET_SESSIONS
SUPPORTED declaration without V1 handler
extra / renamed feature
untyped / rebound blocked semantics
```

`compute_feature_set()` 在任何输入行计算前编译该 plan，并从 `FeatureSpec.window_length / lag / required_inputs` 消费 execution declaration。

**Reviewer verdict：PASS / FREEZE。**

---

## 1.2 Feature semantic seal / physical recompute — VERIFIED / FREEZE

Public Feature verifier 现在明确消费：

```text
manifest.price_basis      == current Feature Registry
manifest.window_basis     == compiled execution plan
manifest.universe_rule_id == current Feature Registry
ledger.snapshot_as_of     == Verified Snapshot.as_of
manifest.snapshot_as_of   == Verified Snapshot.as_of
SUCCESS -> ledger.error_message IS NULL
```

并从物理 artifact 重算：

```text
security_row_count
market_row_count
finding_count
```

形成：

```text
physical rows == manifest == ledger
```

同时保留原有：

```text
exact bytes -> content hash
physical schema -> schema_hash
physical row count -> artifact row_count
physical rows -> semantic_hash
physical artifact exact set -> artifact_set_hash
security + market rows -> feature_semantic_hash
finding rows -> finding_set_hash
Verified ReadModel deterministic replay -> exact row compare
```

因此 semantic declaration、top-level count、business value、lineage value 均不能通过同步重绑 outer seals 绕过 replay。

**Reviewer verdict：PASS / FREEZE。**

---

## 1.3 Numeric denominator / market breadth truth — VERIFIED / FREEZE

当前 ratio path 已统一：

```text
null denominator        -> NULL + UNSAFE_DENOMINATOR
non-positive denominator-> NULL + UNSAFE_DENOMINATOR
non-finite denominator  -> NULL + NON_FINITE_RESULT
non-finite numerator    -> NULL + NON_FINITE_RESULT
```

`return_lag_obs_N` 与 `close_to_ma_obs_N` 不再把 non-positive denominator 误报为普通 `NON_FINITE_RESULT`。

ADR-025 Amendment A 已把：

```text
valid_ma20_count
```

冻结为：

```text
COUNT(non-null close_to_ma_obs_20)
```

即“实际可以参加 above-MA 比较的证券数”。`pct_above_ma20_observed` 使用同一 comparable set，不再存在 `None > 0` 路径。

**Reviewer verdict：PASS / FREEZE。**

---

## 1.4 Active missingness semantics — VERIFIED / FREEZE

`amount_to_mean_obs_20` 与 `vol_raw_return_obs_20` 已不再用 lifetime historical missing count。

当前 finding 通过 incremental valid history + invalid-prefix count 计算：

```text
oldest selected valid member
        ↓
active selection span
        ↓
current row
```

只报告该 active span 内为了取得 last-N-valid members 实际跨过的 invalid/null observations；早于 oldest selected member 的旧缺失不再持续污染以后 finding。

这部分 finding correctness 已有 old-gap / active-gap 对抗测试。

**Reviewer verdict：PASS / FREEZE。**

---

## 1.5 Original Mandatory Matrix 1..66 — VERIFIED AS MAPPED

CR-5 原工作要求已新增 §16.10，将原始 1..66 分别映射到：

```text
focused test
parameter case
frozen upstream regression
static guard
CI matrix evidence
```

Reviewer 接受这种 mapping 方式；不要求制造 66 个独立函数。

CI evidence：

- code/test head `06106c27652e14f13d360fd3e153ececb39a4434`：run `33758109611` SUCCESS；
- latest reviewed branch head `a92c71b4c65af0723d611318247d522b3207d6c9`：run `33759993886` SUCCESS；
- Windows 3.12 / Windows 3.14 / Ubuntu 3.14 全 success；
- Ruff lint / Ruff format / mypy / full pytest / Spike framework / AmazingData SDK-absent 全 success；
- Windows 3.14 governance gates success。

**Reviewer verdict：PASS / FREEZE。**

---

# 2. 唯一未关闭项：P1 Bounded Lineage Complexity

上一轮 Reviewer 明确写明：

> P1-02 不单独阻止 correctness 修复提交，但 **CR-5 最终 FREEZE 前必须处理或由 Reviewer 明确延期**。

本轮不做延期。原因是 Feature verifier 是未来 CR-6 每次消费的正式可信边界，任何 build / verify 都会完整 deterministic replay；如果 row-level lineage 在稀疏数据上退化成 history-sized scan，这个成本会进入日常消费路径，而不是偶发离线工具。

## 2.1 当前进步

CR-5.1 已完成两项正确优化：

```text
旧：每 row 重新 security_rows[: index + 1] 搜 last valid amount
新：incremental valid_amount_rows + invalid prefix

旧：verifier duplicate membership 使用 list
新：security key membership 使用 set
```

所以旧的显式 prefix-valid-value rescan 已删除。

## 2.2 仍存在的最坏情况

当前 amount / volatility lineage 使用：

```text
_add_input_span(input_rows, security_rows, start=active_start, end=index)
```

它会把 active span 中 **每一条 observation** 再加入本 row 的 `input_rows`。

当数据稀疏时，active_start 可能长期不前移。

### Case A：尚未凑齐 N 个 valid member

```text
len(valid_amount_rows) < 20
-> amount_start = 0

len(valid_raw_rows) < 20
-> volatility_start = 0
```

若前 M 条中只有少量 valid member，则每个 target row 都会 materialize：

```text
[0..1]
[0..2]
[0..3]
...
[0..M]
```

累计 observation visits：

```text
1 + 2 + ... + M = O(M²)
```

### Case B：已有 20 个 valid member，随后长时间 invalid

oldest selected valid member 固定，而 index 持续增长：

```text
active span = [fixed_oldest_valid .. current]
```

同样会出现随 invalid streak 长度增长的二次累计。

这不是理论上无法出现的输入：停牌、异常字段、provider 缺失或 unsafe denominator 都可能形成连续 invalid observations。

现有 `test_incremental_windows_do_not_rescan_history_prefix` 只证明源码中不存在旧字面量：

```text
security_rows[: index + 1]
```

以及 security duplicate 使用 set；它没有证明 **row lineage membership 被固定窗口上界约束**，因此不能作为 O(N)/O(N log N) 的完整证据。

## 2.3 次要同类问题

Feature verifier 当前 market-date uniqueness 仍使用：

```text
market_dates: list
if trade_date in market_dates
```

这是 O(D²) membership。D 只是交易日数量，现实影响小于 security lineage，但在本次 complexity closure 中一并改成：

```text
seen_market_dates: set
previous_market_date
```

避免留下同类明显路径。

---

# 3. CR-5.2 Required Design

CR-5.2 的目标不是“更快一点”，而是建立**与 V1 固定窗口语义一致的 bounded lineage contract**。

## P1-01：Numeric truth 不变

必须保持 byte/logical semantics：

```text
raw_return / gap / intraday / amplitude      unchanged
MA 5/20/60                                   unchanged
close_to_ma 5/20/60                          unchanged
lag return 5/20/60                           unchanged
amount last-20-valid                          unchanged
volatility last-20-valid raw returns          unchanged
active missingness skipped count              unchanged
market breadth                               unchanged
PIT no-lookahead                              unchanged
```

如果 output truth 因本轮优化变化，除 `input_lineage_hash / feature_available_at` 被 Reviewer-approved lineage rule 明确改变外，视为 regression。

## P1-02：row lineage 只绑定“实际被 Feature truth 消费的有界输入”

Reviewer 推荐 V1 明确：

```text
input_lineage_hash
```

绑定：

1. current observation；
2. MA 实际固定 observed-bar window（最大 60 rows）；
3. lag 实际 fixed lag dependency（当前 + prior / 或现有 fixed <=61 dependency set）；
4. amount 实际 selected last-N-valid amount rows（最多 20）；
5. volatility 实际 selected last-N-valid raw-return rows（最多 20）；
6. 其它 V1 公式真实 selected input rows。

**invalid rows 仅因为“位于 selected valid members 之间”而被 finding 计数，不需要逐条重复 materialize 进每一个后续 row 的 lineage。**

理由：

- 它们没有进入 numeric value；
- finding 已确定性记录 skipped count；
- 若某 invalid observation 未来变为 valid，上游 Snapshot/ReadModel world 会变化，selection set、feature value/lineage 和 Feature run identity 会重新计算；
- 若它仍然 invalid，仅其无关 identity 变化不应迫使当前 numeric feature 声称“消费了”该 row。

如果开发选择保留“active invalid row identities 必须全部进入 lineage”的语义，则必须使用 deterministic compact range seal / tree / equivalent structure，以 O(1) 或 O(log N) 更新与消费，禁止逐 target row materialize history-sized span。

## P1-03：bounded member count

对当前 V1 fixed contract，单个 security feature row 的 explicit upstream member count 必须存在与历史长度无关的上界。

开发应在 code 中形成可测试的 derived bound，例如：

```text
max fixed observed dependency
+ amount selected valid count
+ volatility selected valid count
+ current row
```

不要把 Reviewer 文档中的示意常数硬编码为不可演化 magic number；应从 execution plan / Registry 固定窗口推导。

## P1-04：feature_available_at 同步 truthful

row-level：

```text
feature_available_at = max(实际进入 row lineage 的 selected upstream available_at)
```

不得因为一个没有参与任何 numeric truth、仅位于 active gap 中的旧 invalid row 拥有更晚 `available_at`，而永久抬高后续 feature knowledge time。

这比当前“materialize entire active span”更贴近 CR-5 原始 PIT contract：**max actual used input available_at**。

Finding 本身仍由 deterministic replay 证明，不需要通过扩大 row lineage 来代替 finding seal。

## P1-05：market verifier uniqueness O(N)

改为：

```text
seen_market_dates: set
previous_market_date
```

同时保持 exact stable-order guard。

---

# 4. Mandatory CR-5.2 Tests

至少新增以下 focused tests；可 parametrization。

1. **10k sparse amount history**：少于 20 valid 或长 invalid streak；instrument / capture 每 row lineage member count，证明 max member count 不随 history length 增长。
2. **10k sparse raw-return history**：同上验证 volatility lineage bounded。
3. 不能使用 wall-clock threshold 作为唯一证据；CI 机器抖动会造成 flaky。优先验证 operation/member bound。
4. amount numeric result 与 CR-5.1 fixture exact unchanged。
5. volatility numeric result exact unchanged。
6. active OPTIONAL_INPUT_MISSING skipped count exact unchanged。
7. old gap outside active span finding 不回归。
8. invalid gap row identity 改变但仍 invalid：若采用 Reviewer 推荐 selected-input lineage，当前 target 的 numeric truth与 lineage 不应被无关 identity 改写。
9. invalid gap row从 invalid -> valid：selection / feature truth / lineage 必须按新 Verified world 改变。
10. invalid gap row available_at 变晚但仍未被 numeric truth消费：采用 selected-input lineage 时，不得抬高 target feature_available_at。
11. selected valid row identity 改变 -> target input_lineage_hash 必须改变。
12. selected valid row available_at 改变 -> target feature_available_at 必须按 max selected input 改变。
13. market duplicate date uses set + previous-order guard；duplicate still fails closed。
14. structural guard：不存在 per-target history-sized `start..index` lineage materialization path。
15. 1312+ frozen regression matrix全绿。
16. Windows py3.12 / Windows py3.14 / Ubuntu py3.14 + Ruff / format / mypy / full pytest / Spike / SDK / governance gates green。

### 推荐的非 flaky 证明方式

允许测试对共享 lineage accumulator / serializer 做 monkeypatch/counter：

```text
count members consumed per target row
```

并断言：

```text
max_members <= derived_v1_bound
```

这样证明的是算法结构，而不是某台 CI 机器“10k rows 恰好 0.8 秒”。

---

# 5. Governance / ADR

ADR-025 追加 **Amendment B — Bounded Selected-Input Lineage**，至少回答：

1. `input_lineage_hash` 到底绑定 selected inputs，还是整个 active span？
2. 为什么 invalid skipped rows 不需要逐条进入 numeric row lineage？
3. finding truth 如何独立 seal/replay？
4. feature_available_at 为什么取 selected actual inputs 的 max？
5. long sparse histories 如何保证 O(N) / O(N log N)？
6. 若未来新增更长或动态窗口，bounded member count 如何从 Registry/plan 推导？
7. 与 CR-5.1 output numeric truth 的兼容性。

同步：

```text
ADR-025 Amendment B
CR-5 work requirement Implementation Mapping
DEVLOG append-only
DEVELOPMENT_MANAGEMENT
```

ADR-025 在 Reviewer 最终关闭 CR-5 前仍保持：

```text
PROPOSED
```

---

# 6. CR-5.2 Exit Gate

必须全部成立：

```text
[ ] CR-5.1 P0 correctness regressions全部保持 green
[ ] numeric feature values unchanged
[ ] active missingness findings unchanged
[ ] no history-sized per-target lineage materialization
[ ] security row lineage explicit member count has Registry-derived bound
[ ] sparse amount 10k adversarial proof
[ ] sparse raw-return 10k adversarial proof
[ ] selected-input identity mutation changes lineage
[ ] unselected invalid identity mutation does not falsely change selected-input lineage（若采用推荐语义）
[ ] selected-input available_at controls feature_available_at
[ ] unrelated invalid available_at does not falsely lift feature_available_at（若采用推荐语义）
[ ] market date uniqueness uses O(N) set/order guard
[ ] public Feature verifier replay remains exact
[ ] migration 023 untouched
[ ] no CR-6 / State / score / strategy code
[ ] all original 1..66 mapping remains valid
[ ] three-platform CI full green
[ ] ADR-025 Amendment B + governance sync
```

通过后 Reviewer 才执行：

```text
CR-5.2 -> VERIFIED / CLOSED / FREEZE
CR-5   -> VERIFIED / CLOSED / FREEZE
ADR-025 -> ACCEPTED
PR #2 -> APPROVED_TO_MERGE
CR-6 -> START (after merge)
```

---

# 7. 明确禁止范围

CR-5.2 不允许借性能收口扩展：

```text
State / regime / bull-bear
score / rank / signal
strategy / backtest
adjusted OHLC / adjusted return
strict session windows
ALL_A_SHARES denominator
industry/index semantics
new Provider
new Canonical domain
production account / trading
```

也不要为了本轮修改 migration 023。若只是 lineage computation semantics 变化，使用现有 feature-v1 correctness artifact + builder code fingerprint + ADR Amendment 管理；只有真实 persistent schema 变化才允许新增 migration 024，禁止重写 023。

---

# 8. Owner View

```text
CR-5 Feature Layer
│
├─ 输入世界唯一                         ✅
├─ Registry honest execution             ✅
├─ 公式 / window / denominator            ✅
├─ PIT / no look-ahead                    ✅
├─ Feature immutable artifact             ✅
├─ Replay / anti-rebind                   ✅
├─ Mandatory 1..66 mapping                ✅
│
└─ Bounded lineage complexity             🔧 CR-5.2 only remaining item
     ├─ 当前正常数据路径已明显改善
     ├─ 但 sparse / long-invalid worst case 仍可能 O(N²)
     └─ 收口后即可正式 FREEZE CR-5
```

当前阶段不再是 Feature correctness 设计问题，而是**让已经正确的 Feature truth 能够在多年、全市场、稀疏异常数据上稳定重复验证**。这一步完成后再启动 CR-6 State，避免 State 层建立在一个逻辑正确但正式消费路径可能被稀疏历史拖垮的底座上。
