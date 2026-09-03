# A-share-analysis：CR-5 最终关闭裁决与 PR #3 合并批准

> **Review Date**：2026-09-04 07:26 +08:00  
> **Prior Reviewer Baseline**：`ffe47adda01e5e1fe8bc6302733d4cbf4d527c94`  
> **Clean Development Branch**：`codex/cr-5-feature-layer-20260904`  
> **Atomic Governed Implementation**：`3e7a0c27c5c7ee058c05721fca2e7b837cc8bb8e`  
> **Latest Development HEAD**：`88bb33760ec43d33abb80871bef6f3c3be880435`  
> **PR #3**：OPEN / MERGEABLE / APPROVED_TO_MERGE  
> **Replacement For**：PR #2（保留历史，DO NOT MERGE）  
> **Verdict**：**CR-5 / CR-5.1 / CR-5.2 / CR-5.2.1 VERIFIED / CLOSED / FREEZE；ADR-025 ACCEPTED；PR #3 APPROVED_TO_MERGE；CR-6 State START after PR #3 merge**

---

# 0. 最终裁决

CR-5 Deterministic Feature Layer 已满足最终 Exit Gate。

```text
CR-5.1 correctness closure                    VERIFIED / CLOSED / FREEZE
CR-5.2 bounded selected-input lineage          VERIFIED / CLOSED / FREEZE
CR-5.2.1 governance gate closure               VERIFIED / CLOSED / FREEZE
CR-5 full chain                                VERIFIED / CLOSED / FREEZE
ADR-025                                        ACCEPTED
PR #3                                          APPROVED_TO_MERGE
PR #2                                          CLOSE / DO NOT MERGE / KEEP HISTORY
CR-6 Deterministic Market State Layer          START AFTER PR #3 MERGE
Production P0-M-1B                             BLOCKED independently
```

CR-5 后续只有在出现可复现 regression 时允许重新打开。不得因为 CR-6 设计方便而回写、弱化或绕过 CR-5 的 Feature Registry、PIT、lineage、immutable artifact、replay 或 governance contract。

---

# 1. Clean replacement history — VERIFIED

旧 PR #2 的最终技术实现 HEAD：

```text
8281e258a7595f8e5fbbd8d0f7e023a494f0b821
```

其技术实现已在上一轮 Reviewer 中判定 PASS，但祖先 commit：

```text
0fe989767d40bc31d0c538c0e07d509f9d1983ff
```

违反 repository 的 per-commit DEVLOG gate：代码 commit 没有在同一个 commit 同步 `docs/DEVLOG.md`。后续 docs commit 无法修复 immutable ancestor，因此旧 PR #2 不允许合并。

开发按 Reviewer 要求从 `main` 重建 clean replacement history，形成：

```text
3e7a0c27c5c7ee058c05721fca2e7b837cc8bb8e
feat: close CR-5.2 with atomic governed change
```

该 commit 同时包含：

```text
Feature code
Feature tests
migration 023
DEVLOG
DEVELOPMENT_MANAGEMENT
ADR-025 / ADR index / work requirement mapping
```

不存在 force-push，不修改旧 PR #2 历史，也没有扩大 CI grandfather exception。

## 1.1 Exact tree equivalence

Reviewer 已核对 Git commit tree：

```text
old technical HEAD 8281e258... tree = ca7a76ef3e198911f5b03c4213b2930ed3ba3fc3
clean atomic      3e7a0c27... tree = ca7a76ef3e198911f5b03c4213b2930ed3ba3fc3
```

二者 **Git tree SHA 完全相同**。

因此 clean replacement 不是“重新实现一版类似 CR-5”，而是把已审查的最终仓库树以 governance-compliant ancestry 重新提交。不存在因治理修复产生新的 Feature 代码或测试语义漂移。

**Reviewer verdict：PASS / FREEZE。**

---

# 2. CR-5.2 bounded lineage — FINAL VERIFIED

CR-5.2 最终 contract 冻结如下：

## 2.1 Selected-input lineage

security row `input_lineage_hash` 绑定真正进入 V1 Feature truth 的 selected inputs：

- current observation；
- fixed observed-bar windows；
- fixed lag dependencies；
- selected last-N-valid amount rows；
- selected last-N-valid raw-return rows；
- 其它 Registry 声明且实际被 execution plan 消费的 rows。

仅位于 selected members 之间、但没有进入 numeric value 的 invalid rows，由 deterministic findings 记录，不再被逐 target row 重复 materialize 进 lineage。

## 2.2 Registry-derived bound

`FeatureExecutionPlan.max_security_lineage_members` 从 frozen Registry / execution plan 推导，不使用不可演化 magic number。

当前 V1 conservative bound：

```text
1 + max(fixed observed/lag dependency) + amount selected-valid N + volatility selected-valid N
= 101
```

engine 对每个 security feature row 运行时 enforce。

## 2.3 Sparse-history proof

10k sparse amount 与 10k sparse raw-return focused tests 捕获每个 target row 实际 lineage member count，并验证：

```text
max(actual members) <= compiled Registry-derived bound
```

该证明不依赖 wall-clock threshold。

## 2.4 PIT truth

冻结：

```text
feature_available_at = max(actual selected upstream available_at)
```

unselected invalid row 的 identity / available_at 变化不应虚假改变当前 selected lineage 或 knowledge time；若该 row 从 invalid 变为 valid 并进入 selection，则 feature truth / lineage / availability 必须按新 Verified world 改变。

## 2.5 Market uniqueness

market-date uniqueness 使用：

```text
seen_market_dates: set
previous_market_date
```

保留 deterministic order fail-closed，消除明显 O(D^2) membership。

**Reviewer verdict：VERIFIED / CLOSED / FREEZE。**

---

# 3. CR-5 correctness contracts — FINAL FREEZE

以下 CR-5 contracts 作为完整冻结链继续有效：

```text
explicit snapshot_id + feature_set_id only
Verified ReadModel only value boundary
one Feature run == one Snapshot world
static versioned Feature Registry
Registry honest execution compiler
UNADJUSTED_CANONICAL price basis
OBSERVED_SECURITY_BARS window basis
OBSERVED_DAILY_BAR_UNIVERSE denominator semantics
raw-price same-row formulas
observed 5/20/60 MA / lag semantics
last-20-valid amount / volatility semantics
no fill / forward-fill / backfill / sentinel / silent drop
finite / denominator safety + typed findings
feature_available_at PIT semantics
bounded selected-input lineage
UUID5 deterministic feature identity
immutable deterministic artifacts
manifest-last / ledger-last recoverable publication
physical content/schema/row-count/semantic seals
Feature semantic / finding exact seals
public Feature consumption verifier
Verified ReadModel deterministic replay + exact row compare
original mandatory matrix 1..66 mapping
migration 023 frozen
no State / signal / strategy / backtest / production semantics inside Feature
```

只允许可复现 regression 触发 CR-5 reopen。

---

# 4. CI / Governance evidence

Clean atomic implementation head：

```text
3e7a0c27c5c7ee058c05721fca2e7b837cc8bb8e
```

GitHub Actions：

```text
run 33814571568 / run 176 — SUCCESS
```

最新 docs-evidence head：

```text
88bb33760ec43d33abb80871bef6f3c3be880435
```

GitHub Actions：

```text
run 33816176159 / run 177 — SUCCESS
```

Reviewer 已核实 run 177：

```text
Windows Python 3.12              SUCCESS
Windows Python 3.14              SUCCESS
Ubuntu Python 3.14               SUCCESS
Ruff lint                        SUCCESS
Ruff format                      SUCCESS
Mypy                             SUCCESS
Full pytest                      SUCCESS
Spike framework gates            SUCCESS
AmazingData SDK absent           SUCCESS
Windows 3.14 DEVLOG gate         SUCCESS
Windows 3.14 Management gate     SUCCESS
```

开发记录显示 clean atomic run 176 三腿均为 `1320 passed`；run 177 再次通过完整 pytest 与全部门禁。

**Reviewer verdict：FULL GREEN。**

---

# 5. PR disposition

## PR #3

```text
feat: close CR-5.2 with atomic governed change
head = 88bb33760ec43d33abb80871bef6f3c3be880435
base = main
mergeable = true
```

**Reviewer decision：APPROVED_TO_MERGE。**

PR #3 合并 `main` 后，CR-5 CLOSED/FREEZE 与 ADR-025 ACCEPTED 作为 mainline governance 正式生效。

## PR #2

旧 PR #2 的技术 tree 已由 PR #3 clean replacement 精确取代；其历史 per-commit DEVLOG failure 必须保留为审计证据。

**Reviewer decision：CLOSE / DO NOT MERGE / KEEP BRANCH UNTIL OWNER CHOOSES CLEANUP。**

不得 force-push PR #2 伪造 green history。

---

# 6. Governance sync required on first CR-6 commit

本 Reviewer 裁决为当前权威状态。由于不为纯状态文字扰动已 full-green PR #3，以下治理字段由 **第一笔 CR-6 code/governance commit** 同批同步：

```text
ADR-025 header/status -> ACCEPTED
ADR-000 index          -> ADR-025 ACCEPTED / VERIFIED 2026-09-04
DEVLOG append          -> CR-5 full closure + PR #3 merge SHA + CR-6 start
DEVELOPMENT_MANAGEMENT -> CR-5 CLOSED/FREEZE; CR-6 START/ACTIVE
```

历史 DEVLOG append-only，不重写旧条目。

---

# 7. CR-6 Entry Gate

CR-6 只有在 PR #3 **实际合入 main** 后才允许产生 State product code。

第一笔 CR-6 commit 必须：

1. 基于包含 PR #3 merge 的 main，或基于本 Reviewer handoff tree 并在 PR #3 merge 后确保 base ancestry 一致；
2. 同步上述 governance；
3. 新建 ADR-026；
4. 不修改 CR-5 frozen formulas / artifacts / migration 023；
5. State 只能消费 `verify_feature_run_for_consumption(feature_run_id)` 的 Verified Feature truth。

正式 CR-6 开发合同见：

`docs/design/A-share-analysis_CR-6_DeterministicObservedMarketStateLayer开发工作要求_20260904.md`

---

# 8. Owner View

```text
Raw / Provider / Canonical             100% CLOSED / FREEZE
Snapshot / DuckDB ReadModel             100% CLOSED / FREEZE
Feature Layer CR-5                      100% VERIFIED / CLOSED / FREEZE
CR-5 governance                         100% CLOSED
PR #3                                   APPROVED_TO_MERGE
State Layer CR-6                        START after merge
Production                              independently BLOCKED
```

前五层已经回答：

> 数据从哪里来、是否可信、是否属于正确历史世界、怎样形成可复现 Feature。

CR-6 开始回答：

> 在**不进入策略和预测**的前提下，如何把这些 Verified Features 解释成稳定、透明、可审计的“当日市场状态”。
