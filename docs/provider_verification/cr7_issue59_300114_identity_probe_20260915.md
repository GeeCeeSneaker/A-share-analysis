# Issue #59 `300114.SZ` provider identity evidence probe（2026-09-15）

状态：`STOP(BLOCKED) / NO PROVIDER-OWNED IDENTITY-DATE EVIDENCE`

本记录承接 Issue #59 scheduler checkpoint `5689306424`，基于合并后的
`main@9423c1799ec970ea3d5076e1af5b3a5ab145ed8d`。授权范围严格限制为：只在 Owner
批准的 AmazingData 中调查单一证券 `300114.SZ` 的 provider-owned security identity 和
可用于 PIT security-master contract 的 listing/effective date。

## 调查范围与入口

已安装的 AmazingData 包版本为 `1.1.9`。本次只发送了带有
`["300114.SZ"]` 的单证券请求，没有查询其他证券、其他数据源或 Stage B/78 月数据。

| 入口 | 是否调用 | 原因/结果 |
|---|---:|---|
| `AmazingDataProvider.get_stock_basic_exchange` → `InfoData.get_stock_basic(code_list)` | 是 | 现有 typed provider facade，允许精确 `code_list` |
| `DownloadInfoData.download_stock_basic(code_list)` | 是 | 已安装 SDK 的底层单代码入口，精确传入同一 symbol |
| `BaseData.get_code_info(security_type)` | 否 | 签名只接受 `security_type`，调用会变成无界 universe 查询，不符合本次单证券授权 |
| `BaseData.get_code_list(security_type)` | 否 | 仅为按 security type 的 membership surface，不能提供单证券 PIT 日期 |
| `BaseData.get_hist_code_list(security_type, start_date, end_date)` | 否 | 是日期窗口 membership surface；历史 membership 本身不能充当 identity/date evidence |

对 SDK bytecode 的只读检查确认：`DownloadInfoData.download_stock_basic` 遍历调用方
提供的 `code_list`，为每个 code 构造 `StockBasicSpi(code)`，并把该 code 原样作为
provider `market_code` 参数提交；没有发现可从 bars、查询日期或请求顺序推导上市日期的
语义。因此该底层入口与现有 typed facade 的 provider 语义一致。

## 实际结果

| 调查入口 | 状态 | 返回形状 | 行数 | 身份字段 | 日期字段 |
|---|---|---|---:|---|---|
| `InfoData.get_stock_basic`（经 `AmazingDataProvider`） | `OK` | `pandas.DataFrame`，`RangeIndex` | 0 | `MARKET_CODE`（无行值） | `LISTDATE`、`DELISTDATE`（无行值） |
| `DownloadInfoData.download_stock_basic` | `OK` | `pandas.DataFrame`，`RangeIndex` | 0 | `MARKET_CODE`（无行值） | `LISTDATE`、`DELISTDATE`（无行值） |

两次返回的列均为：

`MARKET_CODE, SECURITY_NAME, COMP_NAME, PINYIN, COMP_NAME_ENG, LISTDATE, DELISTDATE, LISTPLATE_NAME, COMP_SNAME_ENG, IS_LISTED`

typed facade 的 raw anchor 为：request `215b50ef-b582-4176-899b-c4a95adb0777`、
payload hash `57eb2d33b8c45b7c573b08833a84eee80c150dfe22fa959a29a13cdc0e68799a`、
evidence hash `35903afd3a8f98bf5b70b19a9c8b0e239c91baff91543cea13c9e40d45cbdc8b`。
底层入口的本地忽略 raw artifact 为
`data/spike/identity_probe_300114_20260915/raw/direct_download_stock_basic.parquet`，
大小 `5,830` bytes，SHA-256
`4edda6c2ca2cec85333bede47c4c9e56aba43d58312a12cf3d8957d8d476c37c`。

## 判定与停止点

上述两个已有、同一可信 provider 的单证券身份入口均为 `OK + 0 rows`。因此当前没有
provider-owned identity/date record，不能将其作为 PIT security-master 事实，也不能：

- 从 `daily_bar`、查询日期、首个观察交易日、代码前缀、请求顺序或 hist membership 推导 `LISTDATE`；
- 删除 `300114.SZ` 以把 5,106-member universe 静默改成 5,105；
- 添加另一数据源、multi-source reconciliation 或通用 identity discovery framework；
- 在没有 Canonical `SUCCESS` 的情况下继续 Snapshot、ReadModel、projection、receipt、coverage 或 materialization。

本次没有修改运行时代码。最小解除条件是 Owner/项目经理提供同一 AmazingData provider 的
权威 identity/date 记录，或正式修订 2024-01 universe contract。条件满足后，才按 Issue #59
既定顺序重跑完整 source-input → Canonical → Snapshot → ReadModel → projection，并在
Canonical 成功后继续 acquisition/receipt/replay/coverage/materialization 链。

账号、密码、IP、端口、完整 raw payload、SDK/runtime 文件和 DuckDB 均未进入 Git；完整
raw 仅保存在本地被忽略的 `data/spike/`。
