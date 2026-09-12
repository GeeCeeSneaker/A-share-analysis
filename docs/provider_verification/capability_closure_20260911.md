# AmazingData 能力闭环矩阵（2026-09-12，独立审阅整改后）

## 结论边界

本文件记录的是 Issue #39 授权的六项**定向、非 Production**能力预检，不是 Formal B1-B7 结果，也不是 Provider capability approval。预检没有创建 `SpikeRun`，没有写入 catalog/verdict，没有改 Golden、H1 规则、2020 基线或既有封存证据。

独立审阅发现，原实现把两类“观察到的相关性”越界成了生产归一化规则：状态双缺失行被丢弃，`DIV_PROGRESS` 为 `1/2/12` 且缺 `DATE_EX` 的股利行被丢弃。仓库没有新增权威 SDK/Provider 契约来证明这两类行一定是非观测或非事件，因此本次选择失败关闭：两类形状均保留为未决，不能静默丢弃。

- 原始脱敏在线收据绑定代码提交：`258489bc29359a1212cd33528ac5764ceb97e110`
- 本次语义整改代码提交：`de411142bd3a80a998418ce2c48ae8e134993012`
- 脱敏在线收据：[capability_closure_20260911.json](capability_closure_20260911.json)，44,794 bytes，SHA-256 `bd2294ec4836446bb819a66b91f0def2392be463834d5da2fa61df1f8f71eb51`。该 JSON 是整改前的冻结观察证据；其中旧的 `FRAMEWORK_REMEDIATION_REQUIRED` 不是当前运行时授权，也未被改写。
- 运行环境：AmazingData `1.1.9`、tgw runtime `V4.3.0.260626-rc2.0-YHZQ`；BJ mapping 预检需要本地 `tables==3.11.1`，相关 wheel 仅存于被忽略的 `vendor/`。
- 原始 Provider 返回仅保存在本地忽略目录 `data/spike/capability-closure-20260911/raw/`；GitHub 只提交下表所需的字段、数量、schema/hash 和分类。

## 六项闭环

| # | 要审的问题 | 已确认的事实（以收据和代码为准） | 判断/分类 | 进入 Formal 前仍需处理 |
|---|---|---|---|---|
| 1 | 状态历史日期异常 | `InfoData.get_history_stock_status`，8 个指定证券、1990-01-01—2099-12-31，共 20,638 行；8 行同时缺 `TRADE_DATE` 和 `MARKET_CODE`，但保留限价/状态字段。 | 原生 shape 已确认；这些行是否是非观测/汇总行仍 `STILL_UNRESOLVED`。当前运行时不再丢弃该形状，`canonical_status_view()` 对缺失身份的行失败关闭。 | 需要权威 Provider/SDK 契约或一手材料证明该形状可安全排除；在此之前双缺失、单侧缺失和未知形状都必须显式失败。 |
| 2 | 退市语义 | `InfoData.get_stock_basic` 对 4 个请求证券返回 3 行，并提供 `IS_LISTED`、`LISTDATE`、`DELISTDATE`；`hist_code_list` 是独立的 scalar code-list 连续性证据。 | 字段存在：`PROVIDER_CONFIRMED`；`IS_LISTED`/退市日期是否能直接证明 Golden 的历史 PIT 语义：`STILL_UNRESOLVED`。 | 需要把 stock-basic 状态、历史 code-list 连续性和 Golden 的 `IS_LISTED` 期望逐一对齐；不得把 code-list membership 当作退市状态。 |
| 3 | BJ mapping / endpoint | 补齐本地 PyTables 运行依赖后，`InfoData.get_bj_code_mapping` 原生端点返回 248 行，schema 含 `OLD_CODE`、`NEW_CODE`、`LISTING_DATE`；实际 SDK 签名不接受 `code_list`，facade 已改为完整表请求并保留客户端过滤声明。 | 端点可调用：`PROVIDER_CONFIRMED`；这不等于 `golden_bj_mapping` 已补齐，也不等于 mapping 语义 gate PASS。 | `golden_bj_mapping` 仍缺独立 Golden/事实材料；需由项目管理者另行决定是否建设，不能用本次 248 行接口可用性替代。 |
| 4 | BSE 历史状态 | 对 `835185.BJ` 精确请求 2022-01-01—2022-12-31，`InfoData.get_history_stock_status` 返回带该表名的空结果，0 行、0 列。 | 原生空响应：`PROVIDER_CONFIRMED`；空响应代表历史未覆盖、不可交易还是请求/适配问题：`STILL_UNRESOLVED`。 | 需用最窄的独立日期/上市事实或 Provider contract 判定空响应语义；在此之前不能宣称 BSE 历史状态能力通过。 |
| 5 | 公司行为日期字段 | Dividend：123 行，`DATE_EX` 缺失 50 行；缺失集中在观察到的 `DIV_PROGRESS` 1/2/12，进度 3 的 73 行均有日期。Right issue：6 行，`EX_DIVIDEND_DATE` 缺失 0 行。 | Dividend：`STILL_UNRESOLVED`；相关性不能定义进度语义，当前 `_ca_provider_view()` 对任何缺 `DATE_EX` 的股利行失败关闭。Right issue：`STILL_UNRESOLVED`，因为封存材料曾有 1 行缺失但本次未复现。 | 需要权威 Provider/SDK 契约确认进度码与 `DATE_EX` 的适用关系，并补足右配股历史缺失行的可复核解释；不能把“返回事件行”提升为连续性 PASS。 |
| 6 | `300104.SZ` 历史 fixture | `BaseData.get_hist_code_list` 在 2020-01-01—2020-07-20 返回 3,907 个 scalar code，包含 `300104.SZ`；目标日线窗口 7 个交易日返回 0 行/空表，而同窗口 `600519.SH` 控制请求返回 7 行，说明日线 period/adapter 本身已生效。 | Provider 返回差异：`PROVIDER_CONFIRMED`；目标证券能否作为该历史交易性 fixture：`STILL_UNRESOLVED`，当前不可用；提出 `600519.SH` 为替换候选但未替换。 | 需绑定 `300104.SZ` 的独立上市/适用性/可交易事实，或由 Reviewer 接受明确的替代 fixture；不得为它放宽全局 2020-01-01 基线。 |

## 代码和测试对照

- SDK 契约修正：`src/ashare_state/providers/amazingdata/provider.py`
- 状态/公司行为窄适配：`src/ashare_state/spike/row_adapter.py`、`src/ashare_state/spike/golden_router.py`
- 定向预检脚本：`scripts/spike/capability_closure_probe.py`
- 回归测试：`tests/integration/test_cr1_provider_exchange.py`、`tests/integration/test_ca_provider_shape.py`、`tests/unit/test_spike_row_adapter.py`

本地全量 `pytest`、Ruff check/format、mypy、py_compile、`uv pip check` 和 `git diff --check` 均通过。整改精确 head `5680d9365794872be4e8767b7aa379be7e534406` 的 GitHub Actions CI `#547` 三个平台均成功，GT-H3B `#95` 按策略 skipped。当前整改未重新调用 Provider 或重跑在线预检；下一道门是独立 delta review。PR #45 继续保持 Draft，在 Review/merge 前不创建第三次 Formal Production run。

## 独立审阅整改对照

| 审阅阻断 | 处理 | 当前可声称的结论 |
|---|---|---|
| 状态行同时缺身份和 `TRADE_DATE` 时被静默丢弃 | 删除生产 skip；`canonical_status_view()` 统一按缺失交换所限定身份失败 | 只能确认原生返回形状，不能确认其为汇总/非观测行 |
| `DIV_PROGRESS=1/2/12` 且缺 `DATE_EX` 时被静默丢弃 | 删除进度码过滤；`_ca_provider_view()` 对所有缺 `DATE_EX` 的股利行失败 | 只能确认缺失与进度码的观察相关性，不能确认非事件语义 |

本次没有找到或新增可授权上述归一化的权威契约，所以没有保留更窄的猜测性过滤。回归测试分别锁定两类形状的 fail-closed 行为；原始收据和本地 ignored raw 不变。
