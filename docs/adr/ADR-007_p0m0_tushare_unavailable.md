# ADR-007: P0 阶段 Tushare 不可用的单源运行风险

- 状态：ACCEPTED
- 日期：2026-08-21
- 决策人：开发侧提出，设计者裁决（GO WITH CHANGES 第 3 节）
- 影响范围：P0-M-1 Spike 范围、P0b 里程碑、Source Policy、风险登记册

## 背景与问题

Frozen Baseline V1.3.2 的 Phase 0 假设 AmazingData + Tushare 双 Provider：

1. `daily_basic`（`turnover_rate_f` / `free_share` / `circ_mv`）由 Tushare 提供；
2. 申万行业 taxonomy 与历史成员由 Tushare 提供；
3. 跨源 Reconciliation / Source Policy 需要 Tushare 作为第二候选源；
4. No-Go 预案 `FUSED_TS_SECURITY_CONTEXT_V1`（stock_basic + namechange + suspend_d + stk_limit）完全依赖 Tushare。

当前现实：**Tushare 积分不足（daily_basic 需 2000 分），未注册可用状态；仅 AmazingData 可用。**

## 决策

1. **不修改 Frozen Baseline**：V1.3.2 保持多源设计。当前单源是临时运行条件，不是架构变更。
2. **Spike 范围扩大**：P0-M-1 在 7.1A 清单外追加验证原属 Tushare 的能力（free-float 语义、行业 taxonomy、Benchmark 指数、EOD 可得时刻），并按四级结论评估：
   `EXACT_EQUIVALENT / DERIVABLE_EQUIVALENT / ALTERNATIVE_SEMANTICS / MISSING`。
3. **语义纪律（不可违反）**：
   - `FLOAT_A_SHARE` 等字段不得默认等同于 `free_share`；语义不同则注册为独立字段，**不修改 `PV_TURNOVER_F` 的数学定义**；
   - 银河行业体系（若非申万）注册独立 `taxonomy_id = GALAXY_xxx`，**不得冒充 SW，不得据此宣称 SW L1 Phase 0 DoD 完成**；
   - 单源自洽校验的 reconciliation 状态固定为 `NOT_RUN_NO_SECONDARY`，**禁止伪造 PASS**。
4. **里程碑语义**：`P0a` 等 Spike 核心事实 GO；`P0b` 与 SW/free-float 相关的 P0-M2 部分**允许显式 BLOCKED，不允许伪装完成**。
5. **No-Go 处置**：若 AmazingData 核心事实 No-Go 且 Tushare 仍不可用 → **P0a BLOCKED**，上报设计者重新裁决（补 Tushare 积分 / 新 Provider 单独 Spike）。**AKShare 不因免费可用而自动成为生产 fallback。**

## 后果

- 正面：不阻塞工程骨架（P0-M0）与数据源验证（Spike）双轨推进；能力验证与语义替代严格分离。
- 负面：P0b 与部分 P0-M2 大概率 BLOCKED 直到第二源可用；无真实跨源对账期间数据质量依赖单源自洽 + 人工 Golden。
- 缓解：风险登记册持续跟踪；Tushare 积分补足后按 `meta_source_policy` CANDIDATE→APPROVED 治理流程接入，无需改架构。

## 恢复条件

Tushare 积分补足（≥2000，覆盖 daily_basic/申万/指数）后：
1. 在 `configs/providers.yaml` 将 tushare.status 从 `disabled_pending_credits` 改为启用；
2. 补做 Tushare 侧 Provider Verification（含 7.13 节接入验收 10 项）；
3. Source Policy 按治理流程（Dry-run → APPROVED）恢复双源。
