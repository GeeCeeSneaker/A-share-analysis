# A-share-analysis：CR-5 首批复审与 CR-5.1 Registry Honest Execution / Feature Seal 收口要求

> **Review Date**：2026-09-03 19:22 +08:00  
> **Upstream Reviewer Baseline**：`ace29a5f588adf7590b15e5e133909e3c50d578e`  
> **CR-4 merge main**：`a9c5cee8e3daa6f76dfde961bffc61c139dd6d3a`  
> **Reviewed Branch**：`codex/cr-5-feature-layer-20260903`  
> **Reviewed Branch HEAD**：`193b4c3d21d6736e80fed32539d4c5a49b19446f`  
> **Primary CR-5 Implementation**：`057d3465b1012f5216dd1142f0779784835ed419`  
> **Final Product Head before CI-doc sync**：`eaebce48ad373d7302f208f2f7fe7ddd53bf6cfb`  
> **PR**：#2，OPEN / MERGEABLE / NOT MERGED  
> **Latest CI**：run `33746604036`，Windows 3.12 / Windows 3.14 / Ubuntu 3.14 全 success，每腿 1270 tests  
> **Verdict**：**CR-5 主体机制 PASS；CR-5 DONE / REOPENED；CR-5.1 START / ACTIVE；ADR-025 保持 PROPOSED；PR #2 暂不合并；CR-6 BLOCKED_BY_CR-5.1**

---

# 0. Reviewer 总结

CR-4.4 已随 PR #1 正式合入 `main`，因此：

```text
CR-4 / 4.1 / 4.2 / 4.3 / 4.4    VERIFIED / CLOSED / FREEZE
ADR-024                            ACCEPTED
```

本轮 CR-5 从合并后的 `main=a9c5cee8...` 启动，流程正确；没有在旧 CR-4 基线上偷跑。

CR-5 首批主体架构方向正确，可以保留：

```text
explicit snapshot_id + feature_set_id
        ↓
DuckDBReadModel.open_read_only(snapshot_id)
        ↓
explicit ORDER BY rm_daily_bar
        ↓
static versioned Feature Registry
        ↓
Python deterministic Feature Engine
        ↓
security_daily_features
market_daily_features
feature_findings
        ↓
immutable manifest-last publication
        ↓
meta_feature_build migration 023
        ↓
verify_feature_run_for_consumption
        ↓
Verified ReadModel deterministic replay
```

以下机制本轮判定 **PASS / KEEP**：

- Feature value 正式输入只来自 verified-open ReadModel；
- 不自动 rebuild ReadModel；
- no latest/best/fallback/multi-snapshot；
- `market-state-base-v1` 静态 Registry；
- UNADJUSTED_CANONICAL 命名诚实；
- OBSERVED_SECURITY_BARS 5/20/60；
- raw-return / gap / intraday / amplitude 主公式；
- ordered `math.fsum` / population variance；
- observed-universe breadth；
- null + typed finding 主框架；
- `feature_available_at` / `input_lineage_hash` 主框架；
- UUID5 feature identity；
- immutable recoverable artifact publisher 主框架；
- exact-byte artifact parse；
- Builder / verifier 共用 `compute_feature_set()`；
- verifier 从 Verified ReadModel 重放并 exact compare artifact rows；
- migration 023 from-zero / upgrade / idempotent / tamper framework；
- no State / score / strategy / backtest / trading expansion；
- CI run 33746604036 三平台全绿。

但 Reviewer 发现新的 correctness closure gap。**本轮不得关闭 CR-5，不得 ACCEPT ADR-025，不得 merge PR #2，不得启动 CR-6。**

---

# 1. P0-01：Feature Registry 声明没有被 runtime “诚实执行”

## 1.1 当前问题

Registry 已封存：

```text
feature_name
required_inputs
window_basis
window_length
lag
formula_rule_id
denominator_policy
missingness_policy
availability_rule
eligibility
```

但当前 `compute_feature_set()` 实际只验证：

```text
feature_set.feature_set_id == market-state-base-v1
```

随后 engine 自己硬编码：

```text
for length in (5, 20, 60)
for lag in (5, 20, 60)
raw formula names
amount window 20
vol window 20
market formula behavior
```

因此存在直接矛盾世界：

```text
Registry：ma_close_obs_20.window_length = 17
Registry hash / Feature identity：已经变化
Feature Engine：仍然算 20 observed bars
Verifier：调用同一个旧 engine，也算 20
结果：Registry 声明 17，但 runtime 与 verifier 一致地接受 20-bar truth
```

`formula_rule_id / denominator_policy / availability_rule / eligibility` 也存在同类风险。

这违反 CR-5 P0-02：

> Feature Registry 必须是公式、窗口、缺失值与可用性规则的唯一受治理声明，而不能只是参与 hash 的说明文档。

## 1.2 Required closure

优先方案：**Registry-driven execution plan**。

建议建立：

```text
compile_feature_execution_plan(feature_set)
```

其中：

- engine 不再从 feature name 自己猜 window；
- `window_length / lag` 从 FeatureSpec 读取；
- `formula_rule_id` 通过静态、typed、exact-set dispatch registry 映射到实现；
- 每个 SUPPORTED spec 必须恰好有一个执行实现；
- engine 不得执行 Registry 未声明的额外 feature；
- Registry 声明但 engine 不认识的 rule / window / denominator / availability 必须 fail closed before artifact write；
- blocked semantics 必须是 typed classification，不只是自由文本 tuple。

如果开发选择继续保留硬编码执行矩阵，则必须建立共享 `_assert_feature_registry_honestly_executed()`，机械逐字段验证所有 declared execution semantics 与 runtime implementation 完全相同；不允许只检查 feature names/version/hash。

## 1.3 Mandatory adversarial tests

至少新增：

1. `ma_close_obs_20.window_length: 20 -> 17`，engine 未同步时 fail closed，zero artifact / zero ledger。
2. `return_lag_obs_20.lag: 20 -> 17` fail closed。
3. `formula_rule_id` 改成未实现值 fail closed。
4. `denominator_policy` 改成未实现值 fail closed。
5. `missingness_policy` 改成未实现值 fail closed。
6. `availability_rule` 改成未实现值 fail closed。
7. `window_basis` 改成 `MARKET_SESSIONS` fail closed，绝不能仍执行 observed-bars。
8. SUPPORTED feature 无 handler fail closed。
9. runtime 多出 Registry 未声明 feature fail closed。
10. blocked semantic 不得通过改名进入 SUPPORTED path。

---

# 2. P0-02：Feature manifest / ledger 仍有未被 physical/derived recompute 消费的 correctness 字段

## 2.1 Manifest semantic declarations 可成对重绑

Builder 写入：

```text
price_basis
window_basis
universe_rule_id
```

但当前 Feature verifier 的 `manifest_fields` 没有把它们与当前 Feature Registry / execution plan 交叉绑定。

直接攻击：

```text
price_basis = UNADJUSTED_CANONICAL
      ↓ 修改为
price_basis = ADJUSTED

只重新计算 manifest_hash 并同步 ledger.manifest_hash
feature_run_id / artifacts / formulas 不变
```

当前 verifier 可继续通过，因为该字段既不参与 manifest field cross-bind，也不从 Registry recompute。

同理 `window_basis`、manifest `universe_rule_id`。

Required：

```text
manifest.price_basis      == current feature_set.price_basis
manifest.window_basis     == derived execution-plan window basis
manifest.universe_rule_id == current feature_set.universe_rule_id
```

如果未来存在多 window-basis feature，manifest 不应只存一个模糊全局字符串；应封存 feature registry hash 或明确 per-feature execution contract，避免误导。

## 2.2 Top-level row counts 没有从物理/replay结果重算

当前：

```text
security_row_count
market_row_count
finding_count
```

只做 ledger ↔ manifest 对比。

但 verifier 已经拥有：

```text
actual_rows[security_daily_features]
actual_rows[market_daily_features]
actual_rows[feature_findings]
computed replay rows
```

所以必须 physical recompute：

```text
len(actual security rows) == manifest == ledger security_row_count
len(actual market rows)   == manifest == ledger market_row_count
len(actual findings)      == manifest == ledger finding_count
```

必须加入成对 rebind tests。

## 2.3 Upstream primitive cross-bind 完整化

同时补：

```text
manifest.snapshot_as_of == verified_snapshot.as_of
ledger.snapshot_as_of   == verified_snapshot.as_of
```

当前 identity 虽包含 snapshot_as_of，但 public verifier 应明确消费 upstream truth，不依赖“正常 Builder 不会写错”。

SUCCESS run 还应要求：

```text
ledger.error_message is NULL
```

避免错误状态元数据漂移。

## 2.4 Mandatory tests

11. price_basis only rebind + outer manifest hash -> verifier refuses。
12. window_basis only rebind -> refuses。
13. universe_rule_id manifest only rebind -> refuses。
14. security_row_count ledger+manifest pair rebind -> refuses by physical count。
15. market_row_count pair rebind -> refuses。
16. finding_count pair rebind -> refuses。
17. snapshot_as_of forged feature world -> refuses against verified Snapshot。
18. SUCCESS + non-null error_message -> refuses。

---

# 3. P0-03：Rolling denominator / market breadth missingness semantics 仍有 fail-closed 与 finding truth gap

CR-5 合同明确：

```text
denominator None or <= 0
-> value NULL
-> UNSAFE_DENOMINATOR
```

当前 raw same-row ratio 已做到，但 rolling path 尚未统一。

## 3.1 return_lag_obs_N

当前 prior close <= 0 时 `formulas.lag_return()` 返回 None，engine 将其归为：

```text
NON_FINITE_RESULT
```

应改为：

```text
UNSAFE_DENOMINATOR
```

并明确 detail：prior observed close <= 0。

## 3.2 close_to_ma_obs_N

当前 MA <= 0 时同样会被归成 `NON_FINITE_RESULT`。

应改为 `UNSAFE_DENOMINATOR`。

建议把 ratio-with-reason 提取为共享 typed helper，same-row / lag / close-to-ma / amount 全部使用同一 denominator truth，避免四套判断漂移。

## 3.3 pct_above_ma20_observed

当前 market path 以：

```text
ma_close_obs_20 is not None
```

选入 denominator，然后直接执行：

```text
close_to_ma_obs_20 > 0
```

但存在：

```text
MA 有数值
close_to_ma 因 denominator 不安全而 NULL
```

此时可能出现 `None > 0` 运行时异常，违反“普通数值无效 -> null + typed finding，不让整个 run 崩溃”的 contract。

CR-5.1 必须在 ADR-025 Amendment A 明确：

```text
valid_ma20_count
```

究竟表示：

A. `ma_close_obs_20` 本身 non-null；还是
B. 能实际参与 `above-MA` 比较的 `close_to_ma_obs_20` non-null。

Reviewer 推荐 B，因为 `pct_above_ma20_observed` 的 denominator 必须等于**实际可比较证券数**；若采用 B，应同步 formula_rule_id/registry wording/tests，但 output column 名可保持 V1 contract。

## 3.4 Mandatory tests

19. lag prior close = 0 -> null + UNSAFE_DENOMINATOR，不崩。
20. lag prior close < 0 -> 同上。
21. MA denominator = 0 -> close_to_ma null + UNSAFE_DENOMINATOR。
22. MA denominator < 0 -> 同上。
23. market day 含 close_to_ma null -> pct_above 不崩，denominator 按 ADR 决议精确计数。
24. zero valid breadth denominator -> ratio null，不是 0。
25. NaN/+Inf/-Inf 输入不得进入 artifact，finding class 精确。

---

# 4. P1-01：OPTIONAL_INPUT_MISSING finding 当前使用“全历史累计缺失数”，不是实际 active selection 范围

`amount_to_mean_obs_20` 与 `vol_raw_return_obs_20` 的 value 使用：

```text
last 20 valid values
```

这是正确的。

但当前 finding 计数：

```text
(index + 1) - len(all valid rows since history start)
```

因此很早以前、早已不在当前 last-20-valid selection span 内的一个 null/invalid row，会在以后每一天继续被报告为“本次 feature 跳过的输入”。

这使 finding detail 不再描述实际当前 computation。

Required：

- finding 只统计为了取得当前 last 20 valid members 而实际跨过的 invalid/null rows；
- 早于当前 oldest selected member 的缺失行不得继续污染当前 finding；
- `input_lineage_hash` 与 finding 所描述的 active input span 应可解释地对应。

Mandatory：

26. 一个 100 bars 前的 null amount，在最近 20 valid span 外，不应继续产生当前 OPTIONAL_INPUT_MISSING。
27. 最近 20-valid selection 中间的 null 应产生 exact skipped count。
28. vol 同样两项。

---

# 5. P1-02：首批实现存在明显 O(n²) 路径，需在进入 CR-6 前收敛

当前每个 security row 的 `amount_to_mean_obs_20` 会重新扫描：

```text
security_rows[: index + 1]
```

因此单证券 N bars 为 O(N²)。全 A 股多年历史会放大到不可接受规模。

Feature verifier 又会完整 deterministic replay，因此这个成本至少发生在 build 与每次 verify/consume 两侧。

同时 `_validate_rows()` 用 list 做 duplicate membership，也会退化为 O(total_rows²)。

不要求牺牲 deterministic correctness，但要求改为 deterministic O(N) / O(N log N) 数据结构：

- amount：维护 ordered last-20-valid deque / ring；
- raw-return：已有 incremental list，可收敛 last-valid window；
- duplicate：使用 set + previous-order key；
- finding skipped-span metadata 可随 active window 状态维护。

至少增加一个非 flaky 的规模回归或结构测试，证明不再有 history-prefix rescan。

该项 P1，不单独阻止 correctness 修复提交，但 **CR-5 最终 FREEZE 前必须处理或由 Reviewer 明确延期**。

---

# 6. P0-04：66 项 Mandatory Matrix 尚未真正闭环

本轮从 CR-4 的 1256 tests 增长到 1270，净增 14 项。

CI 全绿是好信号，但不能替代原工作要求 §16 的 66 项 mandatory semantics。

当前已有代表性覆盖：

- healthy build + public verify；
- exact retry；
- unknown feature set；
- missing ReadModel；
- missing daily_bar；
- bytes tamper；
- business value + outer seals rebound；
- forbidden imports；
- registry basic identity；
- one ordered formula fixture；
- zero denominator；
- observation gap；
- future-row target leakage；
- input order determinism。

但至少以下原 mandatory 尚无明确 focused pin：

```text
unknown/damaged Snapshot
foreign/tampered ReadModel input
no latest/best API guard
two snapshots -> distinct feature identity/artifacts
registry formula/window change identity + honest execution
builder fingerprint identity
wall-clock/artifact byte determinism
raw/gap/intraday/amplitude individual exact fixtures
MA 5/20/60 boundaries
lag 5/20/60 boundaries
full missing/null/nonfinite matrix
finding exact-set determinism
varying available_at max-used-input
lineage member mutation
late-ingested historical fact knowledge time
market aggregate lineage/available_at
zero market denominator
pct_above denominator exactness
blocked adjusted/session/all-A semantics
manifest LAST ordering
schema/rowcount/semantic rebind
lineage + ALL seals rebound
ledger commit failure recovery
partial residue recovery
conflicting residue refusal
exact hash-bytes parse pin
```

CR-5.1 不要求机械地制造“66 个独立 test functions”；允许 parametrization，但必须在原 CR-5 工作要求追加 **Mandatory Test Mapping**：每个 1..66 都指向具体 test name / parameter case / CI evidence。

Exit Gate 不能用“1270 全绿”替代“66 项都被验证”。

---

# 7. CR-5.1 Allowed Scope

允许：

```text
features/registry.py
features/formulas.py
features/engine.py
features/builder.py
features/verifier.py
features/models.py（仅必要 identity/finding helper）
tests/integration/test_features.py
ADR-025 Amendment A
CR-5 work requirement Implementation / Mandatory Mapping
DEVLOG append-only
DEVELOPMENT_MANAGEMENT sync
```

migration 023 当前不需要修改。除非出现真实持久化字段缺口，不得为了本轮修复随意改 schema；若必须新 schema，使用 migration 024，不要重写已经提交并验证的 023。

禁止：

```text
CR-6 State
bull/bear/regime
score/rank/signal
strategy/backtest
adjusted-return formula
session-window claim
all-A-share denominator
industry/index feature
new Provider / Canonical domain
production enablement
```

CR-2 / CR-3 / CR-4 保持 CLOSED / FREEZE。

---

# 8. CR-5.1 Exit Gate

全部满足才允许 Reviewer 关闭 CR-5：

```text
[ ] Registry execution is honest: no declared field can drift from runtime behavior silently
[ ] formula_rule_id/window/lag/denominator/missingness/availability/eligibility all consumed or fail closed
[ ] blocked semantics classification typed and mechanically guarded
[ ] manifest price_basis/window_basis/universe_rule_id consumed against Registry/execution truth
[ ] security/market/finding top-level counts physically recomputed
[ ] snapshot_as_of explicitly cross-bound to Verified Snapshot
[ ] SUCCESS error_message semantics sealed
[ ] all denominator<=0 paths -> NULL + UNSAFE_DENOMINATOR
[ ] pct_above_ma20 denominator semantics explicit and null-safe
[ ] OPTIONAL_INPUT_MISSING detail reflects active computation span, not all-history noise
[ ] feature_available_at / lineage varying-time adversarial tests green
[ ] business + lineage + semantic-field all-seal rebound tests green
[ ] ledger-failure / partial-residue / conflict recovery tests green
[ ] original CR-5 mandatory 1..66 mapping complete
[ ] migration 023 tests remain green; 001..022 untouched
[ ] CR-2/3/4 frozen regressions green
[ ] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 green
[ ] Ruff / format / mypy / full pytest / Spike / SDK / governance gates green
[ ] ADR-025 Amendment A + DEVLOG + DEVELOPMENT_MANAGEMENT + CR-5 work requirement mapping synced
[ ] Reviewer sees no new P0 correctness blocker
```

若全部通过：

```text
CR-5 / CR-5.1          VERIFIED / CLOSED / FREEZE
ADR-025                  ACCEPTED
PR #2                    APPROVED_TO_MERGE
CR-6 Market State Layer  START AFTER MERGE
```

---

# 9. 当前正式状态

```text
CR-2 all chain                     VERIFIED / CLOSED / FREEZE
CR-3 / 3.1..3.6                    VERIFIED / CLOSED / FREEZE
CR-4 / 4.1..4.4                    VERIFIED / CLOSED / FREEZE
ADR-023 / ADR-024                  ACCEPTED

CR-5                               DONE / REOPENED
  主体 architecture               PASS / KEEP
  Registry honesty                P0 OPEN
  Feature seal closure            P0 OPEN
  numeric/finding semantics        P0/P1 OPEN
  mandatory matrix                P0 AUDIT GATE OPEN
CR-5.1                             START / ACTIVE NEXT
ADR-025                            PROPOSED / NOT ACCEPTED
PR #2                              OPEN / DO NOT MERGE YET
CR-6                               BLOCKED_BY_CR-5.1
Production P0-M-1B                 BLOCKED independently
```

---

# 10. Owner View

CR-5 已经把“事实 -> 特征”的主干跑通，方向没有问题；现在剩下的不是重新设计 Feature 层，而是把**公式声明与实际执行、manifest 语义、missingness finding、完整验证矩阵**做最后一层交叉绑定。

这一步非常值得在 CR-6 State 之前收干净：一旦 State 层开始用这些 Feature，Registry 如果只是“写着 20 日、实际却可能算另一套窗口”，或者 Feature manifest 能被改成 `ADJUSTED` 仍通过验证，那么后续所有状态研究都会建立在不可审计的语义上。

因此 CR-5.1 是 focused closure，不扩业务范围；修完以后再进入 Market State。