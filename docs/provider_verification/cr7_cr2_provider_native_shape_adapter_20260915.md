# CR-7 CR-2 provider-native shape 适配与完整 2024-01 复核（2026-09-15）

状态：`CR-2 ADAPTER VERIFIED / FULL 2024-01 CANONICAL BLOCKED / NO RECEIPT / NO MATERIALIZATION`

本记录承接 Issue #59 在 PR #69 合并后的调度授权（Issue comment `5681562056`）。授权范围只
包括三个已经实际观察到的 provider shape：`hist_code_list` scalar symbol、`stock_basic`
identity + `LISTDATE`、`daily_bar` member-key map。没有引入通用 adapter framework，也没有
进入 Stage B、78 月回补、Formal B1-B7 或 Production verdict。

## 本次代码结果

- `RawWriter` 对非默认 pandas index 保留原始 index；默认合成 `RangeIndex` 不添加伪列。实际
  AmazingData 批量 `stock_basic` 的重复零 index 会被保留为 raw evidence，但不会覆盖已验证的
  provider identity。
- `stock_basic` 的真实 `MARKET_CODE` 字面字段实际携带完整后缀符号（例如 `NNNNNN.SZ`），
  已作为严格、字面、版本化的 identity carrier 处理；`LISTDATE` 映射为 `list_date`，不补查询日
  或首个交易日。若同时有代码/index，必须一致；合成或无效 index 不能冒充身份。
- `hist_code_list` 仅对 `{"value": "NNNNNN.SH|SZ|BJ"}` 做 scalar membership 适配；裸码、未知
  后缀、非六位数字和冲突市场全部 fail closed，且不生成 `list_date`。
- `daily_bar` 仅对精确的
  `amazingdata / daily_bar / MarketData.query_kline / daily_bar` member-map 路径逐 member 展开；
  所有成员都处理，`None`/空表不生成成交行，成员 key 和行内身份不一致时逐行 quarantine，禁止
  take-first、请求顺序回填和代码前缀推断。

## 真实完整 2024-01 source-input 结果

本地受控进程使用 `ProviderUseMode.SPIKE`，范围为 SH 日历、2024-01 月度历史证券表、5,106
个证券和 22 个交易日；凭证、SDK、私有 endpoint、raw payload、DuckDB 均留在被忽略的
`data/spike/`，未进入 Git。

| 输入 | 真实结果 | CR-2 结果 |
|---|---:|---|
| `trade_calendar` | raw 8,726 行 | `SUCCESS`，8,726/8,726 |
| `hist_code_list` | raw 5,106 行 | `SUCCESS`，5,106/5,106；scalar 适配生效 |
| `stock_basic` | provider 返回 5,105 行 | `SUCCESS`，5,105/5,105；每行由 `MARKET_CODE` 后缀符号携带身份并保留 `LISTDATE` |
| `daily_bar` | `packed_multi_table`，raw 112,075 行 | `SUCCESS`，112,075/112,075；5,106 × 22 全部映射 |

在最终代码版本上对同一批真实 raw 做了隔离重放；结果仍为：

Canonical 真实完整输入运行结果：

- final replay run `958b02f2-e8c2-5815-be82-aa96ac6bf652`：`BLOCKED`；selected `112,053`；唯一阻断为
  `IDENTITY_MISSING`，计数 22。
- 本地集合差异显示历史证券表比 `stock_basic` 多一个 provider symbol：`300114.SZ`。
  对该单一缺失成员做的诊断请求返回 `OK` 但 0 行 DataFrame；这确认是提供方没有返回可用
  `stock_basic` 身份/上市日期，而不是批量行序绑定或网络/账号故障。
- 因而不能用历史 membership、请求参数、代码前缀、查询日或首个交易日伪造该证券的 PIT
  identity。完整 2024-01 source snapshot 尚未成立，不能把 112,053 条选中事实当作 112,075
  条完整事实继续下游。

## 下游边界验证与停止点

为验证适配没有破坏既有下游，另用同一真实 raw 中的一个证券/一个交易日建立了隔离的本地
QA 账本：Canonical `SUCCESS`（1 row）→ Snapshot `SUCCESS` → ReadModel 验证通过 →
`prepare_verified_projection()` 返回 1 row。这只是边界连通性证据，不是完整 2024-01 权威验收。

完整输入运行已在 Canonical 停止，因此以下严格未执行：

- 完整 2024-01 的 Snapshot、ReadModel、projection；
- `AmazingDataHistoryAcquisition.acquire_month()`、receipt、retained replay、coverage basis；
- bounded materialization、ordinary reader、idempotency/conflict proof；
- Stage B（`2020-01`/`2026-01`）、78 月回补、Formal B1-B7、Production、BSE/index、CR-5/R2、
  Golden/H1、baseline 和策略工作。

## 验证与下一步

- focused CR-2/provider normalization tests：通过；覆盖 scalar 合法/非法值、member map 全量
  成员、`None`/空表、成员冲突、默认/非默认 index、`MARKET_CODE` identity carrier 和日期映射。
- 全仓 `uv run pytest -q`：退出码 0；format、ruff、mypy、compileall、dependency、JSON、diff
  和 tracked-file secret scan 均通过。
- 当前最小外部解除条件：Owner/项目经理需要决定 `300114.SZ` 在 2024-01 既定 5,106 universe
  中是否应有另一份同一可信 provider 的可用 `stock_basic`/PIT 上市日期证据，或正式修订该月
  universe contract。开发代码不能自行删除该成员或填造身份。
- 条件满足后只重跑完整 2024-01 既有链，并从 Canonical `SUCCESS` 后继续 Issue #59 规定的
  Snapshot → ReadModel → projection → acquisition → coverage → materialization 顺序。
