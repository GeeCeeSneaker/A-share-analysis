# A-share-analysis：CR-5.2 复审与 CR-5.2.1 Governance Gate 收口要求

> **Review Date**：2026-09-04 06:24 +08:00  
> **Clean Upstream Reviewer Baseline**：`67d37f8e51b086e0585ba12b53e529e49d70a427`  
> **Reviewed Development Branch**：`codex/cr-5-feature-layer-20260903`  
> **Reviewed Development HEAD**：`8281e258a7595f8e5fbbd8d0f7e023a494f0b821`  
> **Primary CR-5.2 Implementation**：`0fe989767d40bc31d0c538c0e07d509f9d1983ff`  
> **Primary CR-5.2 Final Tree**：`8281e258a7595f8e5fbbd8d0f7e023a494f0b821`  
> **Latest CI**：run `33767742448`（run 175）— Windows 3.12 / Ubuntu 3.14 product gates success；Windows 3.14 product gates success but DEVLOG per-commit governance gate failure  
> **PR #2**：OPEN / MERGEABLE / NOT MERGED  
> **Verdict**：**CR-5.2 technical implementation PASS；CR-5.2 final closure HOLD solely on governance history；CR-5.2.1 Governance Gate Closure START / ACTIVE；ADR-025 remains PROPOSED；PR #2 DO NOT MERGE；CR-6 remains BLOCKED**

---

# 0. Reviewer 总结

本轮没有发现新的 Feature correctness 或 bounded-lineage 算法 blocker。

CR-5.2 已完成上一轮要求的技术收口：

```text
selected-input lineage                     PASS
history-independent member bound           PASS
Registry-derived bound                     PASS
10k sparse amount proof                     PASS
10k sparse raw-return proof                 PASS
selected/unselected identity semantics      PASS
selected/unselected available_at semantics  PASS
market-date set/order guard                 PASS
no migration 023 change                     PASS
no CR-6 / State scope creep                 PASS
```

但最新 CI run `33767742448` 不能判定为 full green。唯一失败项是 Windows 3.14 的 DEVLOG per-commit gate：

```text
commit 0fe989767d40bc31d0c538c0e07d509f9d1983ff
changes code without updating docs/DEVLOG.md
```

后续 `56dae955...` 虽补写 DEVLOG，但当前治理规则是 **per-commit**，后补不能修复祖先 commit。

因此：

```text
CR-5.1 correctness                  VERIFIED / CLOSED / FREEZE
CR-5.2 technical semantics          PASS / KEEP
CR-5.2 final exit                   HOLD — governance only
CR-5.2.1 Governance Gate Closure    START / ACTIVE
CR-5                               DONE / REOPENED (governance only)
ADR-025                             PROPOSED
PR #2                               DO NOT MERGE
CR-6                                BLOCKED_BY_CR-5.2.1
Production P0-M-1B                 BLOCKED independently
```

本轮**禁止再次修改 Feature 算法**，除非 clean rebuild CI 暴露可复现 regression。

---

# 1. CR-5.2 技术实现复审 — PASS

## 1.1 selected-input lineage 正确落地

原来的：

```text
active_start .. current
```

逐 target row materialization 已删除。

amount / volatility 现在只把真实 selected valid members 加入 lineage；current row、MA fixed window、lag fixed dependency 仍按既有语义进入。Invalid gap rows 只因位于 selected members 之间而被 finding 计数，不再重复进入每一个后续 row lineage。

这与上一轮 Reviewer 推荐语义一致。

## 1.2 Registry-derived member bound 正确

`FeatureExecutionPlan.max_security_lineage_members` 从 execution plan 推导：

```text
current row
+ max(fixed observed/lag dependency)
+ selected amount valid window
+ selected volatility valid window
```

当前 V1 得到 conservative bound 101，并在 engine 对每个 security feature row 运行时 enforce。

没有把 Reviewer 文档示意常数直接硬编码为不可演化 magic number。

## 1.3 10k sparse adversarial proof 接受

新增 10k sparse amount / raw-return tests 通过 monkeypatch 捕获每个 target row 的实际 lineage member count，并断言：

```text
max(lineage_members_per_target)
<= compile_feature_execution_plan(...).max_security_lineage_members
```

这是上一轮明确允许的非 wall-clock 结构证明。

## 1.4 PIT / identity 行为符合 selected-input contract

Focused tests 已覆盖：

- invalid gap identity 改变且仍 invalid -> target selected lineage 不变；
- invalid gap 从 invalid 变 valid -> selection / feature value / lineage 改变；
- unrelated invalid gap available_at 变晚 -> target feature_available_at 不被抬高；
- selected valid identity 改变 -> lineage 改变；
- selected valid available_at 改变 -> feature_available_at 按 selected max 改变。

这与 Amendment B 的 selected-input PIT 定义一致。

## 1.5 verifier 明显 O(D²) membership 已关闭

market date uniqueness 已改为：

```text
seen_market_dates: set
previous_market_date
```

同时保留 duplicate + deterministic order fail-closed。

## 1.6 frozen truth 未扩展

本轮未改：

```text
Feature names / formulas
5/20/60 windows
raw price basis
observed-bar window basis
observed-universe breadth
artifact schema
migration 023
CR-2 / CR-3 / CR-4
State / score / signal / strategy / production
```

Reviewer 对 CR-5.2 技术实现结论：**PASS / KEEP；不再要求算法修正。**

---

# 2. 唯一 blocker：DEVLOG per-commit governance gate

run `33767742448` 的产品门禁实际状态：

```text
Ruff lint                    PASS
Ruff format                  PASS
Mypy                         PASS
Full pytest                  PASS — 1320 passed
Spike framework              PASS
AmazingData SDK-absent       PASS
Windows 3.12                 PASS
Ubuntu 3.14                  PASS
Windows 3.14 product checks  PASS
DEVLOG per-commit gate       FAIL
```

失败对象不是最新 docs commit，而是历史 implementation commit `0fe989767...` 本身未同时更新 `docs/DEVLOG.md`。

现有 workflow 的治理注释已经明确原有 grandfather 是一次性 disclosed exception，并写有 `do NOT extend`。Reviewer 不批准为本次 CR-5.2 再扩展 grandfather 列表，也不批准把 per-commit 规则降级为“同一 push 后补即可”。

同时遵守项目 no-force-push / preserve-history 纪律，不允许 force rewrite 当前 PR #2 分支来隐藏这个事实。

---

# 3. Required Repair：clean replacement branch / PR，不改历史、不放宽 gate

## P0-G01 保留旧 PR #2 作为审计历史

旧分支：

```text
codex/cr-5-feature-layer-20260903
```

和 PR #2 不 force-push、不修改历史语义。

在 replacement PR full green 前：

```text
PR #2 MUST NOT MERGE
```

完成 replacement 后可以关闭 PR #2，并在说明中引用本 Reviewer 裁决和 replacement PR；不要删除旧 branch 直到 CR-5 最终 closure 完成。

## P0-G02 从 clean Reviewer branch HEAD 建 replacement development branch

以本 Reviewer 分支：

```text
review/cr-5.2-governance-closure-20260904
```

的 HEAD 为唯一 clean handoff point。

该 Reviewer branch 自 `67d37f8e...` 分叉，因此不包含违规 commit `0fe989767...`。

建议：

```bash
git fetch origin
git switch -c codex/cr-5.2-clean-closure-20260904 \
  origin/review/cr-5.2-governance-closure-20260904
```

## P0-G03 精确重放 CR-5.2 final tree，不重新设计

目标不是重新实现，而是把旧开发分支：

```text
67d37f8e51b086e0585ba12b53e529e49d70a427
..
8281e258a7595f8e5fbbd8d0f7e023a494f0b821
```

的**最终有效差异**重放到 clean branch。

推荐使用 final-tree diff / squash，而不是逐个 cherry-pick 旧 6 个 commits；逐个 cherry-pick 会重新引入 `0fe989...` 的 per-commit governance 形态。

示意：

```bash
git diff 67d37f8e51b086e0585ba12b53e529e49d70a427 \
         8281e258a7595f8e5fbbd8d0f7e023a494f0b821 \
  | git apply --index
```

或者等价的 deterministic squash-final-tree 方法。

在提交前必须确认 staged tree 只包含本轮已复审的 9 个路径类别：

```text
src/ashare_state/features/engine.py
src/ashare_state/features/registry.py
src/ashare_state/features/verifier.py
tests/integration/test_features.py
docs/DEVLOG.md
docs/adr/ADR-000_adr_index.md
docs/adr/ADR-025_feature_layer_pit_missingness.md
docs/design/A-share-analysis_CR-5_DeterministicFeatureLayer及PITFeatureSnapshot开发工作要求_20260903.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

以及本 Reviewer 文档本身已经存在于 clean base，不应重复创建。

## P0-G04 clean code commit 必须自身同时满足治理

replacement branch 上承载 CR-5.2 code change 的 commit，必须在**同一个 commit**内包含至少：

```text
Feature code/tests
DEVLOG CR-5.2 implementation entry
DEVELOPMENT_MANAGEMENT CR-5.2 current status
ADR-025 Amendment B / mapping（如 final tree包含）
```

不允许：

```text
code commit A
然后 docs-only commit B 后补 DEVLOG
```

因为这正是本轮失败原因。

如果 clean commit 形成后需要补写“真实 commit SHA / CI run id / replacement PR number”，允许再追加 docs-only evidence commit；但 code commit 自身的 DEVLOG/management 同步必须已经成立。

## P0-G05 replacement PR

从 clean branch 新开 replacement PR，target 仍为 `main`。

PR 描述必须明确：

1. 这是 PR #2 的 governance-clean replacement；
2. Feature final tree 应与旧 reviewed HEAD `8281e258...` 的 CR-5.2 有效 tree 等价；
3. 没有重新设计 Feature semantics；
4. replacement 的原因仅是旧 commit `0fe989...` 违反 per-commit DEVLOG gate；
5. PR #2 保留用于审计，不合并。

---

# 4. Mandatory verification for CR-5.2.1

replacement branch 必须完成：

1. `git diff` / tree evidence：CR-5.2 产品代码、tests、ADR Amendment B 与旧 reviewed final tree 等价；仅允许治理 evidence 中的 branch/commit/CI/PR references 合理变化。
2. CR-5.1 全部 frozen regressions green。
3. 10k sparse amount member-bound proof green。
4. 10k sparse raw-return member-bound proof green。
5. selected/unselected identity + available_at focused tests green。
6. market date set/order guard green。
7. migration 023 untouched。
8. no CR-6/State/score/signal/strategy code。
9. Windows py3.12 SUCCESS。
10. Windows py3.14 SUCCESS。
11. Ubuntu py3.14 SUCCESS。
12. Ruff lint SUCCESS。
13. Ruff format SUCCESS。
14. Mypy SUCCESS。
15. full pytest >= 1320 green（若只有治理 docs 变化，测试数不应下降；若测试收集发生变化必须解释）。
16. Spike framework SUCCESS。
17. AmazingData SDK-absent SUCCESS。
18. **DEVLOG per-commit gate SUCCESS**。
19. **Management-doc gate SUCCESS**。
20. replacement PR OPEN / MERGEABLE / NOT MERGED，等待 Reviewer final closure。

---

# 5. Exit decision after clean replacement

只要 replacement branch/PR 满足上述 20 项，且与旧 reviewed final tree 无实质算法差异，下一轮 Reviewer 应直接执行：

```text
CR-5.2.1  VERIFIED / CLOSED / FREEZE
CR-5.2    VERIFIED / CLOSED / FREEZE
CR-5      VERIFIED / CLOSED / FREEZE
ADR-025   ACCEPTED
clean replacement PR  APPROVED_TO_MERGE
old PR #2             CLOSE / DO NOT MERGE
CR-6       START only after clean PR merged to main
```

不要再创建 CR-5.3；除非 clean rebuild 暴露新的真实 correctness regression。

---

# 6. Owner View

当前 CR-5 的技术成熟度已经达到关闭水平，剩余问题是**提交历史不满足我们自己设定的治理纪律**，不是 Feature 算法缺陷。

```text
CR-5 Feature Layer
│
├─ correctness                         ✅
├─ Registry honesty                    ✅
├─ PIT / lineage semantics             ✅
├─ bounded sparse-history complexity   ✅
├─ 1320 product tests                  ✅
├─ three-platform product checks       ✅
│
└─ per-commit governance history       🔧 one clean-rebuild closure only
```

因此本轮不扩大技术开发范围。完成 clean replacement 并取得 full-green governance CI 后，即可正式关闭 CR-5 并进入 CR-6。