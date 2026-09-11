# Formal B1-B7 只读 replay 诊断记录（2026-09-11）

> 状态：**REPLAY_DIAGNOSTIC v3 / ORIGINAL RUN PRESERVED / FOLLOW-UP REVIEW REQUIRED / NO FORMAL AUTHORIZATION**

## 目的与边界

本记录执行的是 [Issue #39](https://github.com/GeeCeeSneaker/A-share-analysis/issues/39) 最新调度意见要求的只读 replay：使用本地可用的旧 Formal 封存证据，按当前主线代码在内存中重走适配器、validator 和 Golden router 边界，形成诊断结果。它不是第三次 Formal，不是 Provider capability approval，也不是对旧 verdict 的改写。

- 旧封存 run：`dad1e1b8-0c34-4031-8e94-cc87a03dbbf4`，状态 `CLOSED`，旧 verdict `SPIKE_INCOMPLETE`。
- 旧 sealed catalog：178 条，SHA-256 `bad92a04ae6008cc094d72a213f670f0ccdf9ab5befc285b29e46d0a7a9dee53`；旧 run 文件未修改。
- replay 代码绑定：`0c8dc076b11d02251a7ee2f572d78a1dbc634dc1`（基于 `main@b7c9b1b2986e5cbd5415ef44826acbc7d008cfc5` 的分支提交）。
- Golden 绑定：`v7-reviewed-20260908`、125 条、SHA-256 `a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e`。
- 交易规则绑定：`v20260910-h1r4-reviewed`、`REVIEWED`、dataset SHA-256 `b8b77ef83f5741c12a2effef988f793c0827f737ea471494814c1b0b6d7f9aed`。

复现入口为 [`formal_readonly_replay.py`](../../scripts/spike/formal_readonly_replay.py)，脱敏产物为 [`formal_readonly_replay_20260911.json`](formal_readonly_replay_20260911.json)。v3 产物只保留 hash、行数、结果分类、reason code、脱敏子归因和证据逻辑路径，不上传 raw payload、账号或凭证。

## B1-B7 与 Golden 结果

“旧记录”是旧 Formal catalog 中已经封存的结果；“replay”是本次离线重走的结果。两者不应混读为同一个 Formal verdict。

| 阶段 | 能力/案例组 | 旧记录 | replay 结果 | 诊断分类与原因 |
| --- | --- | --- | --- | --- |
| B1 | `formal_runtime_gate`（40 条） | 36 PASS、2 FAIL、2 permission-not-testable | `NOT_RUN_OFFLINE` | 未重跑 SDK/runtime/account gate；`SDK_RUNTIME_ACCOUNT_GATE_NOT_REEXECUTED` |
| B2 | `security_master_with_delisted` | 1 FAIL | `MISSING` | 5,442 行均为 value-only historical-code membership；所需 `IS_LISTED`/`DELISTING_DATE` 语义字段未出现；`DELISTED_SEMANTIC_FIELD_MISSING` |
| B3 | `daily_bar_units` | 1 FAIL | `VALIDATED_PASS` | 1,200 行进入 keyed/canonical view，1,155 行检查且全部单位一致；观察为 volume shares、amount CNY |
| B3 | `historical_st_suspend` | 1 OBSERVED | `VALIDATED_FAIL` | status-specific boundary 先保留 5 张状态表身份；1 行/1 表仍缺 `TRADE_DATE`（声明 11,332 行）；`PROVIDER_STATUS_SHAPE` |
| B3 | `limit_price_and_no_limit_days.sample` | 1 FAIL | `VALIDATED_FAIL` | 同一状态 payload 的 1 行/1 表仍缺/无效 `TRADE_DATE`，先于限价算术；`PROVIDER_STATUS_SHAPE` |
| B3 | `limit_price_and_no_limit_days.BSE` | 1 MISSING | `MISSING` | BSE status 声明为空（0 行、1 表），Provider 语义仍未确定；`PROVIDER_EMPTY_STATUS_UNRESOLVED` |
| B3 | `adj_factor_corporate_action_continuity` | 1 OBSERVED | `OBSERVED` | 只有复权行，没有价格上下文；仅结构观察，连续性继续 deferred |
| B4 | `golden_st_transition`（50 条） | 50 FAIL | 50 FAIL | status-specific boundary 先保留 47 张状态表身份；6 行/6 表仍缺/无效 `TRADE_DATE`（声明 118,878 行）；`PROVIDER_STATUS_SHAPE` |
| B4 | `golden_delisted`（20 条） | 20 FAIL | 20 FAIL | 当前合并 validator 已到达，但 Provider 语义值与期望不符；`DELISTED_SEMANTIC_MISMATCH` |
| B4 | `golden_limit_regime`（30 条） | 30 FAIL | 30 FAIL | 22 张状态表中 2 行/2 表仍出现 `TRADE_DATE` 缺失/无效（声明 51,465 行）；`PROVIDER_STATUS_SHAPE` |
| B4 | `golden_corporate_action`（25 条） | 25 FAIL | 25 FAIL | 脱敏 schema 归因：dividend 55 行中 25 行缺 `DATE_EX`，right_issue 18 行中 1 行缺 `EX_DIVIDEND_DATE`；`PROVIDER_SCHEMA` |
| B5 | `sdk_permission_cache_freshness` | 1 PASS | `NOT_RUN_OFFLINE` | 日历可读，但账户权限/缓存行为不能由离线 raw 复现；`ACCOUNT_PERMISSION_IDENTITY_NOT_REEXECUTED` |
| B5 | `history_start_2020` | 1 FAIL | 3/3 明确夹具 PASS；核心投影 `UNRESOLVED` | 首个适用交易日覆盖通过；`300104.SZ` 保持 deferred，不放宽全局 2020 baseline |
| B5 | `symbol_mapping_unambiguous` | 1 PASS | standalone `VALIDATED_PASS`；核心投影 `MISSING` | 5,562 个 scalar mapping 值通过 parser 检查，但核心合同还要求 `golden_bj_mapping`；该类型本次无回放证据 |
| B6 | `free_float_equivalence`、`sw_taxonomy` | 各 1 OBSERVED | `OBSERVED_ONLY` | 仅结构行；optional semantic check 未离线重跑；`OPTIONAL_SEMANTIC_CHECK_NOT_REEXECUTED` |
| B6 | `benchmark_index_availability` | 1 OBSERVED | `OBSERVED_ONLY` | 240 行结构可读；指数语义检查未离线重跑；`INDEX_SEMANTIC_CHECK_NOT_REEXECUTED` |
| B7 | `capacity_backfill` | 1 OBSERVED | `NOT_RUN_OFFLINE` | 仅检查不可变 raw metadata，没有 backfill loop/timing；`CAPACITY_TIMING_METRICS_NOT_IN_RAW_PAYLOAD` |

## CORE_CAPABILITY 合同投影

v3 延续从仓库现有 [`CORE_CAPABILITIES`](../../src/ashare_state/spike/capabilities.py) 派生的 `core_capability_projection`。它是诊断投影，不是 verdict；每个能力按合同要求的全部 `required_case_types` 聚合，明确列出 `replayed_case_types`、`absent_case_types`、逐类型 minimum/有效计数、结果计数和 reason code。B3 的单一结构案例与 B4 Golden 组不会再被当成互相独立的核心能力结论；存在 deferred fixture 时，`history_start_2020` 不得投影为 PASS。

| 核心能力 | 所需案例类型覆盖 | replay 投影 | 关键边界 |
| --- | --- | --- | --- |
| `security_master_with_delisted` | 2/2 | `REPLAY_CORE_FAILED` | B2 缺退市语义字段，Golden 退市语义 mismatch |
| `daily_bar_units` | 1/1 | `REPLAY_CORE_PASS` | 仅表示当前封存字节的诊断重走结果 |
| `historical_st_suspend` | 2/2 | `REPLAY_CORE_FAILED` | status identity shape 仍阻断 |
| `limit_price_and_no_limit_days` | 2/2 | `REPLAY_CORE_FAILED` | sample/BSE 与 Golden limit 均纳入同一合同 |
| `adj_factor_corporate_action_continuity` | 2/2 | `REPLAY_CORE_FAILED` | adj 仅结构观察，Golden CA schema 阻断 |
| `history_start_2020` | 1/1 | `REPLAY_CORE_UNRESOLVED` | 3 个明确 fixture 的当前代码 replay 通过，但 `300104.SZ` deferred；原因 `HISTORICAL_DELISTED_FIXTURE_DEFERRED` |
| `symbol_mapping_unambiguous` | 1/2 | `REPLAY_CORE_MISSING` | `golden_bj_mapping` 缺失，不能用 standalone parser PASS 替代 |
| `sdk_permission_cache_freshness` | 1/1 | `REPLAY_CORE_UNRESOLVED` | 离线未重跑账户权限/缓存行为 |

## 本轮审阅阻断的处理

- 所有 `history_stock_status` 回放路径改用 replay 内部的 status-specific keyed flatten boundary：合格外层 symbol 会被传播并与行内身份校验冲突；非合格外层 key 不参与推断，行内 `MARKET_CODE`/日期交由 `canonical_status_view()` 判定。无合格 key 的空/null member 单独记为 structural unresolved，不伪造 status row。当前封存字节的剩余异常已收敛为 core 1 行/1 表、Golden ST 6 行/6 表、Golden limit 2 行/2 表的日期缺失/无效。
- `core_capability_projection` 直接读取冻结合同定义；`symbol_mapping_unambiguous` 明确保持 `MISSING`，直到 `golden_bj_mapping` 有独立证据；`history_start_2020` 因 `300104.SZ` deferred 明确保持 `UNRESOLVED`。该投影不会写入或重算旧 verdict。
- `golden_corporate_action` 的 `PROVIDER_SCHEMA` 现在给出文档化字段名和受影响行数；不输出任何 raw 值。

## 只读性与证据闭包

本次 v3 产物 [`formal_readonly_replay_20260911.json`](formal_readonly_replay_20260911.json) 的 SHA-256 为 `6e42506b9a6b2886c70fa8eed07edded3ad06b8835ebd082523870fbca035dae`，大小 51,421 bytes。

- 读取并验证 23 个 meta 文档，materialize 22 个 payload，发出 27 个脱敏证据 anchor。
- 封存 evidence tree 前后均为 27,988 个文件、370,227,555 bytes，inventory SHA-256 均为 `49318037cb609c6cf764e1863c0025f1ad6980ff2ac9593092544f0943f8113a`。
- `provider_calls=0`、`provider_sdk_target_constructed=false`、`spike_run_created=false`、`raw_writer_write_calls=0`、`catalog_write_calls=0`、`verdict_write_calls=0`。
- 旧 `spike_run.json`、`verdict.json`、sealed catalog、Golden 和交易规则均只读；原始 payload 仍留在本地封存目录，不进入 Git。

## 后续门槛

1. 由独立 Reviewer 在最新提交 `0c8dc076b11d02251a7ee2f572d78a1dbc634dc1` 上复核 status-specific 键边界、CORE_CAPABILITY 聚合、脱敏子归因、绑定 hash 和只读控制；当前 PR 仍保持 Draft，CI 及 follow-up review 尚未完成。
2. B2 退市语义、status canonical shape、BSE 空响应、公司行为 dividend contract 仍需获得新的可复核证明；不得以 replay 的 PASS 或结构观察替代这些证明。
3. `300104.SZ` 在纳入通用历史覆盖前必须绑定 applicability/tradability 事实；不得为它削弱全局 2020 起始日基线。
4. 若要形成新的 Formal 结论，必须由调度者针对合并后的 clean main 另行一次性授权；在此之前禁止 Production、`--resume`、`--verdict`、backfill、策略扩展或生产化。
