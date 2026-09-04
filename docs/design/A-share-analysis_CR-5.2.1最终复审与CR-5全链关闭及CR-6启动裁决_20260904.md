# A-share-analysis：CR-5.2.1 最终复审、CR-5 全链关闭与 CR-6 启动裁决

> **Review Date**：2026-09-04 07:28 +08:00  
> **Upstream Reviewer Baseline**：`ffe47adda01e5e1fe8bc6302733d4cbf4d527c94`  
> **Clean Replacement Branch**：`codex/cr-5-feature-layer-20260904`  
> **Atomic CR-5 Replacement Commit**：`3e7a0c27c5c7ee058c05721fca2e7b837cc8bb8e`  
> **Reviewed Replacement HEAD**：`88bb33760ec43d33abb80871bef6f3c3be880435`  
> **Replacement PR**：#3 OPEN / MERGEABLE / NOT MERGED  
> **Old PR**：#2 DO NOT MERGE；保留审计历史，replacement closure 后关闭  
> **CI Evidence**：run `33814571568`（atomic code commit）SUCCESS；run `33816176159`（latest replacement head）SUCCESS  
> **Verdict**：**CR-5.2.1 VERIFIED / CLOSED / FREEZE；CR-5.2 VERIFIED / CLOSED / FREEZE；CR-5 VERIFIED / CLOSED / FREEZE；ADR-025 ACCEPTED；PR #3 APPROVED_TO_MERGE；CR-6 START after PR #3 merge；Production P0-M-1B remains independently BLOCKED**

---

# 0. Reviewer 最终结论

CR-5 的最后一个阻塞项已经关闭。

上一轮 CR-5.2 的 bounded selected-input lineage 技术实现本身已通过 Reviewer 复审，但旧开发历史中存在一个不能由后补文档修复的 per-commit DEVLOG 治理违规：

```text
0fe989767d40bc31d0c538c0e07d509f9d1983ff
changes code without updating docs/DEVLOG.md
```

Reviewer 明确拒绝：

- 扩展一次性 grandfather exception；
- 降级 per-commit DEVLOG 规则；
- force-push 改写旧 PR #2 历史。

开发执行人随后建立 clean replacement branch，并将最终 CR-5 tree 原子化重放到：

```text
3e7a0c27c5c7ee058c05721fca2e7b837cc8bb8e
```

该 commit 的 tree SHA：

```text
ca7a76ef3e198911f5b03c4213b2930ed3ba3fc3
```

与旧 CR-5.2 最终已审技术 tree `8281e258a7595f8e5fbbd8d0f7e023a494f0b821` **完全相同**。

因此此次 clean replacement 没有重新设计 Feature 算法，也没有改变已经通过的 CR-5.1 / CR-5.2 correctness truth；它只把同一个最终 tree 重新落成治理合规的原子提交。

正式裁决：

```text
CR-4 all chain                         VERIFIED / CLOSED / FREEZE
CR-5.1 correctness                     VERIFIED / CLOSED / FREEZE
CR-5.2 bounded lineage                 VERIFIED / CLOSED / FREEZE
CR-5.2.1 governance gate               VERIFIED / CLOSED / FREEZE
CR-5                                   VERIFIED / CLOSED / FREEZE
ADR-025                                ACCEPTED
PR #3                                  APPROVED_TO_MERGE
PR #2                                  DO NOT MERGE / close as superseded history
CR-6 Deterministic Market State Layer  START after PR #3 merge
Production P0-M-1B                     BLOCKED independently
```

CR-5 以后仅因**可复现 regression**重新打开，不再以“继续优化 Feature”或“补更多指标”为由扩展已冻结的 CR-5 V1 合同。

---

# 1. CR-5.2.1 Governance Closure — VERIFIED

## 1.1 clean replacement 的 tree 等价性

Reviewer 核对：

```text
old reviewed final tree  @ 8281e258...
new atomic replacement   @ 3e7a0c27...
```

两者 tree SHA 均为：

```text
ca7a76ef3e198911f5b03c4213b2930ed3ba3fc3
```

这给出比“人工逐文件看起来相同”更强的证据：**最终 Git tree 逐对象等价**。

因此：

- Feature Registry 不变；
- Feature formulas 不变；
- Feature builder/verifier 不变；
- CR-5.1 对抗测试不变；
- CR-5.2 bounded-lineage 实现不变；
- migration 023 不变；
- ADR-025 Amendment A/B 内容不变；
- CR-6 没有偷跑。

## 1.2 atomic code commit 自身通过治理 gate

关键区别是，本轮不是“最后一个 docs commit 绿，所以假装历史 code commit 合规”。

atomic replacement code commit：

```text
3e7a0c27c5c7ee058c05721fca2e7b837cc8bb8e
```

自身关联 CI run：

```text
33814571568
```

结果 SUCCESS。

Windows Python 3.14 leg 中：

```text
Ruff lint                SUCCESS
Ruff format              SUCCESS
Mypy                     SUCCESS
Full pytest              SUCCESS
Spike gates              SUCCESS
AmazingData SDK absent   SUCCESS
DEVLOG per-commit gate   SUCCESS
Management-doc gate      SUCCESS
```

因此旧 `0fe989...` 的历史治理缺陷没有被 grandfather 或后补遮蔽，而是通过新的治理合规原子历史真正消除。

## 1.3 latest replacement HEAD 同样全绿

latest reviewed replacement HEAD：

```text
88bb33760ec43d33abb80871bef6f3c3be880435
```

对应 CI run：

```text
33816176159
```

同样 SUCCESS。

Windows 3.12 / Windows 3.14 / Ubuntu 3.14 三腿全部成功；Windows 3.14 governance gates success。

**Reviewer verdict：CR-5.2.1 VERIFIED / CLOSED / FREEZE。**

---

# 2. CR-5 技术冻结清单

以下机制自本裁决起属于 CR-5 frozen contract，除可复现 regression 外不得随意改变。

## 2.1 输入世界

- `FeatureBuilder.build(snapshot_id, feature_set_id)` 只接受显式 ID；
- Feature value 只来自 `DuckDBReadModel.open_read_only(snapshot_id)`；
- public Snapshot verifier 只提供已验证 provenance；
- 不允许 latest / best / fallback / multi-snapshot fusion；
- 不允许 Feature builder 隐式 rebuild ReadModel；
- 不允许 Provider / Raw / CR-2 / Canonical source-selection 进入 Feature package。

## 2.2 Registry honest execution

- static versioned Feature Registry；
- `compile_feature_execution_plan()` 对 FeatureSet metadata、exact names/order、每个 FeatureSpec 全字段、blocked semantics 与 formula handler 做机械 exact bind；
- caller 不能注入 window / formula / fill / adjustment / tolerance；
- Registry 声明变化但 engine 无支持时，必须在 artifact publication 前 fail closed。

## 2.3 V1 Feature truth

Frozen V1 只声明：

```text
PRICE_BASIS   = UNADJUSTED_CANONICAL
WINDOW_BASIS  = OBSERVED_SECURITY_BARS
UNIVERSE      = OBSERVED_DAILY_BAR_UNIVERSE
```

证券基础特征：

```text
raw_return_1
gap_open_raw
intraday_return_raw
amplitude_preclose_raw
ma_close_obs_5 / 20 / 60
close_to_ma_obs_5 / 20 / 60
return_lag_obs_5 / 20 / 60
amount_to_mean_obs_20
vol_raw_return_obs_20
```

市场特征：

```text
observed_security_count
valid_raw_return_count
advancer_count / decliner_count / unchanged_count
advancer_ratio_observed
mean_raw_return_observed
median_raw_return_observed
valid_ma20_count
pct_above_ma20_observed
valid_mom20_count
pct_positive_mom20_observed
total_amount_observed
```

明确仍 BLOCKED：

```text
adjusted OHLC / adjusted return / total return
strict per-security market-session windows
ALL_A_SHARES denominator
board/ST/tick-size limit inference
industry breadth / theme breadth / rotation
index-relative alpha/beta
score / rank / signal / strategy / backtest
```

## 2.4 PIT / missingness / numeric safety

- `feature_available_at = max(actual selected input available_at)`；
- later observation 不得改变 earlier target row；
- no fill / ffill / bfill / sentinel / silent drop；
- unsafe denominator -> NULL + typed finding；
- NaN / +/-Inf 不进入 correctness artifact；
- findings deterministic exact-set replay；
- `valid_ma20_count` = 实际 non-null `close_to_ma_obs_20` 可比较证券数。

## 2.5 Bounded selected-input lineage

- current row、fixed MA/lag dependency、selected-valid amount/volatility members 进入 lineage；
- invalid gap rows若仅作为 skipped members 之间的 observation，不重复进入每个 target row lineage；finding 负责记录 deterministic skip truth；
- `FeatureExecutionPlan.max_security_lineage_members` 从 Registry/execution plan 推导；当前 V1 conservative bound = 101；
- engine runtime enforce 该 bound；
- 10k sparse amount/raw-return adversarial tests 证明 explicit member count 不随历史长度无限增长；
- market-date uniqueness 使用 set + previous-order guard。

## 2.6 Artifact / replay / publication

- deterministic UUID5 feature identity；
- correctness identity 不含 wall-clock；
- exact artifact set：security / market / findings + manifest；
- manifest last，ledger last；
- deterministic immutable path；
- missing residue 可 exact retry；identical bytes no-op；different bytes hard conflict；
- exact bytes are the bytes parsed；
- content/schema/rowcount/semantic seals physical recompute；
- semantic fields与当前 Registry/plan cross-bind；
- physical counts == manifest == ledger；
- public Feature verifier重新 verified-open ReadModel，调用同一 `compute_feature_set()` replay，并 exact compare physical artifact rows；
- migration 023 frozen。

## 2.7 Test / CI contract

- 原 CR-5 Mandatory Matrix 1..66 已形成 explicit mapping；
- CR-5.1 focused adversarial closure retained；
- CR-5.2 sparse / lineage / PIT / complexity closure retained；
- replacement full suite = 1320 passed / 0 failed；
- Windows py3.12 / py3.14 / Ubuntu py3.14；
- Ruff / format / mypy / full pytest / Spike / SDK-absent / governance gates。

---

# 3. ADR-025 Final Decision

ADR-025 — Deterministic Feature Layer / PIT / Window / Missingness Contract：

```text
ACCEPTED — 2026-09-04
```

接受范围包含：

- 原始 ADR-025 V1 Feature contract；
- Amendment A — Registry Honest Execution / Feature Seal Closure；
- Amendment B — Bounded Selected-Input Lineage。

ADR-025 不解锁任何仍在 CR-5 中明确 BLOCKED 的语义。

后续若要引入 adjusted-price、strict-session window、ALL_A denominator 或其它当前未证实语义，必须使用新 Feature Registry version + ADR Amendment/新 ADR + independent correctness evidence；不能静默改变 `market-state-base-v1`。

---

# 4. PR 裁决

## PR #3

```text
APPROVED_TO_MERGE
```

理由：

- clean history；
- exact final-tree replay；
- atomic code commit 自身 governance compliant；
- latest HEAD CI green；
- no premature self-approval；
- no CR-6 scope creep。

PR #3 merge 到 `main` 是 CR-5 CLOSED/FREEZE 在主线上的正式生效点，也是 CR-6 开发允许开始的生效点。

## PR #2

```text
DO NOT MERGE
SUPERSEDED_BY_PR_3
```

保留其历史用于说明：CR-5 first batch → CR-5.1 → CR-5.2 技术收口以及 per-commit governance failure 的完整过程。

PR #3 merge 后可关闭 PR #2；不要 force-push 改写旧 PR #2 来伪造合规历史。

---

# 5. CR-6 启动原则

CR-6 正式名称：

> **Deterministic Market State Layer — 可解释、非预测、可重放的市场状态解释层**

CR-6 必须继续服从 V1.3.2 研究宪法：

```text
Fact -> Canonical -> Feature -> State -> Strategy Research
```

其中：

- Feature 是数学事实；
- State 才允许做状态解释；
- State 不等于预测；
- State 不等于交易信号；
- State 不等于一个总情绪分数。

冻结基线中明确：

```text
MA20_BREADTH = 0.72        -> Feature
“趋势广度扩张”             -> State
“因此未来上涨概率更高”       -> 必须进入独立 Research/Experiment
```

因此 CR-6 的第一版只允许基于 Verified CR-5 Feature Run 生成**可解释的多维描述性 State facts**，不得根据未来收益、回测结果或策略效果选择阈值/权重。

CR-6 的详细接口、State Registry、允许的 V1 状态维度、artifact/replay、PIT、测试矩阵和明确禁止项，以同分支下一份《CR-6 Deterministic Market State Layer 开发工作要求》为正式执行合同。

---

# 6. Governance Sync Requirement

本 Reviewer 裁决是 CR-5 最终权威结论。

PR #3 merge 后，第一笔 CR-6 developer governance commit 必须同步：

```text
ADR-000:
  ADR-025 -> ACCEPTED / VERIFIED 2026-09-04

ADR-025 header:
  ACCEPTED 2026-09-04

DEVLOG append-only:
  CR-5.2.1 clean replacement closure
  CR-5 full VERIFIED/CLOSED/FREEZE
  PR #3 approval / PR #2 superseded
  CR-6 START

DEVELOPMENT_MANAGEMENT:
  current main baseline = PR #3 merge commit
  CR-5 -> VERIFIED/CLOSED/FREEZE
  CR-5.1 -> FREEZE
  CR-5.2 -> FREEZE
  CR-5.2.1 -> FREEZE
  ADR-025 -> ACCEPTED
  CR-6 -> START/ACTIVE
```

历史 DEVLOG 只能 append，不回写历史条目。

---

# 7. Owner View

```text
Raw / Evidence                         100%  CLOSED/FREEZE
Provider-normalized                    100%  CLOSED/FREEZE
Canonical Runtime                      100%  CLOSED/FREEZE
SnapshotBuilder                        100%  CLOSED/FREEZE
DuckDB ReadModel                       100%  CLOSED/FREEZE
Feature Layer                          100%  VERIFIED/CLOSED/FREEZE
  ├─ Feature correctness               100%
  ├─ PIT / no-lookahead                100%
  ├─ replay / anti-rebind              100%
  ├─ bounded lineage                   100%
  └─ Git governance history            100%

Market State Layer                     START after PR #3 merge
Strategy / Experiment                  BLOCKED_BY_STATE_CONTRACT
Production                             independently BLOCKED
```

CR-5 现在回答的问题已经完整闭合：

> **“可信事实怎样被转换成可信、PIT 正确、可解释来源、可确定性重放的研究特征？”**

CR-6 开始回答：

> **“这些可信特征怎样被解释成多维市场状态，同时不把描述、预测和策略混成一层？”**
