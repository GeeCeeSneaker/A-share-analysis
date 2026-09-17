# Issue #76：78 个月权威历史构建执行记录

> 状态：**STOP(BLOCKED) at 2023-02 / 37 of 78 capture PASS / no publication**

## 当前执行检查点（2026-09-17，Owner 批准的静态事件整改后）

- 本次从既有 anchored raw evidence 做 retained replay。状态文件确认 `37/78` 个月 capture PASS；其中原始 `2020-03` 至 `2022-12` 是此前已完成的 fresh-provider capture，本次只是重放，不应重复计为新的在线采集。
- `2023-01` 已按 Owner 批准的最小范围接入一条官方停牌事实：`300114.SZ`，区间为半开区间 `[2023-01-12, 2023-02-02)`。该事实只作用于当前仍 `UNRESOLVED` 的目标 pair，不覆盖 provider 已给出的状态，不把零成交推断为停牌，也不引入 carry-forward 或第二 provider。
- `2023-01` retained replay 结果：monthly universe `4911`、交易日 `16`、required/returned bar pairs `78,403/78,403`、returned rows `78,403`；missing `0`、extra `0`、structural error `0`、`UNRESOLVED=0`。分类为 `NOT_APPLICABLE_SESSION=67`、`POSITIVE_TRADE_COUNT_ACTIVE=7`、`SUSPENSION_NON_TRADING=106`。事件实际闭合原先的 9 个 `300114.SZ` pair，evaluation/catalog 已保存事件 ID、区间和来源 URL，retained replay 会重新校验该对象。
- 官方原文来源：[CNINFO 2023-001（2023-01-12 起停牌）](https://static.cninfo.com.cn/finalpage/2023-01-12/1215580484.PDF)、[CNINFO 2023-007（2023-02-02 起复牌）](https://static.cninfo.com.cn/finalpage/2023-02-02/1215749576.PDF)、[深交所停复牌表（记录 300114.SZ 的 2023-01-12 停牌）](https://docs.static.szse.cn/www/certificate/secondb/GEMmsb/W020230202562529948780.html)。前两份公告证明区间起止，第三份是起始日的交易所交叉核验。
- 随后 runner 在 `2023-02` provider 请求前停止：当前 Codex 执行进程缺少四个安全环境变量。没有发起该月 provider 请求，`2023-02` 不是数据结论；账号、口令、地址和端口均未进入日志、文件或 GitHub。

### 当前可执行下一步

1. 在启动 runner 的同一个本地 PowerShell 进程中安全注入四个变量，然后使用 `--resume --retry-blocked`；不要把值放进参数、脚本、截图、日志或聊天。
2. 从 `2023-02` 继续逐月执行；每个月仍须通过 exact-session、状态、生命周期、bar 集合和 replay 校验，遇到新语义/结构/权限 blocker 必须停下并记录，不能跳过月份。
3. 78 个月 capture 全部通过后，才可继续 receipt、authoritative coverage、materialization、ordinary-reader、幂等和 changed-content conflict 验收；当前仍无 publication。

## 上一个执行检查点（2026-09-17，静态事件整改前的历史快照）

- 本地 runner 在安全变量可见的同一进程中已通过登录并恢复执行。`2020-01`、`2020-02` 为 retained replay，`2020-03` 至 `2022-12` 为 fresh provider；共 `36/78` 个月 capture PASS。当前尚未对这些月份做完整 finalize/receipt/publication 链路，因此“capture PASS”不等于整月最终验收 PASS。
- `2023-01` 使用 fresh provider：monthly universe `4911`、交易日 `16`、required/returned bar pairs `78,403/78,403`、returned rows `78,403`；missing `0`、extra `0`、structural error `0`。completeness 为 `FAIL_CLOSED`，因为 `UNRESOLVED=9`。

### 2023-01 未决 pair 与原始证据

9 个未决 pair 均为 `300114.SZ`：

| 交易日 | fallback snapshot request_id | rows | `num_trades` | 当前结论 |
|---|---|---:|---:|---|
| 2023-01-12 | `dbe180c6-7698-4326-8e43-04ae96c4d960` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-13 | `59ea6494-d606-41be-a8c9-c96d8c4525ef` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-16 | `0b2b19b3-0553-4a34-9b08-887a887acc87` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-17 | `d9665403-2b6a-44e0-b582-712bf047bba4` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-18 | `5c741edd-7a02-413b-88a7-d283a79718b5` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-19 | `f7e7ec77-fdf0-478c-a03f-d85f8daf0a9b` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-20 | `dae30f98-9da8-4978-9e27-9b1b7dae032c` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-30 | `89b006f1-e20e-4f4c-80f1-e0a636ac3659` | 331 | 全部 0 | UNRESOLVED |
| 2023-01-31 | `bac0a57a-8cb9-4756-a7df-9c7fa741b454` | 331 | 全部 0 | UNRESOLVED |

对应的可复核事实：

- 当月 hist code list request `2d0f3cbe-99e4-4585-8c26-4cfcb3c69a0f` 有 `4911` 个代码并包含 `300114.SZ`。
- 当月 `stock_basic` request `14545323-755d-4369-ad68-6a83a140f351` 返回 `4910` 行；`300114.SZ` 不在 `MARKET_CODE` 中，因而本次没有把 LISTDATE/DELISTDATE 事实用于排除这些 pair。
- 当月 history-status request `beb1ade5-f2de-431f-9bf8-70e98e4428eb` 的 provider status 为 `OK`、总行数 `78,493`；其 `300114_SZ.parquet` 是 `0×0` 空 schema，不是一个可解释的停牌状态记录。
- 9 个 fallback snapshot 均是 exact-session 请求，均返回 `331` 行；原始快照的 `num_trades` 全为 `0`，且当前执行合同只把正交易次数作为 active fallback。零活动、空 status 和未返回状态不能被等同为停牌，也不能从相邻日期 carry-forward。

本次 `2023-01` 的分类计数为：`NOT_APPLICABLE_SESSION=67`、`POSITIVE_TRADE_COUNT_ACTIVE=7`、`SUSPENSION_NON_TRADING=97`、`UNRESOLVED=9`、`UNEXPLAINED_MISSING=0`、`EXTRA_RETURNED=0`、`PROVIDER_API_SHAPE_OR_REQUEST_MISMATCH=0`。daily bar request `717d823d-1695-4b99-b090-1b575958a3bf` 的 required/returned pair set 相等，故这不是 bar 缺失或数量不一致问题。

## PM/Owner 在本次整改前需要决定的最小下一步（历史快照）

1. 提供 `300114.SZ` 在上述 9 个 exact-session 的 provider-owned 非交易/停牌状态事实，且能绑定到现有 raw capture 和 retained replay；或
2. 明确批准一个最小 zero-activity 语义/API 扩展，写明允许使用的 provider 字段、零值/空值含义、适用范围、持久化与 replay 校验；同时决定当月 stock_basic 不含历史代码时的身份/生命周期事实来源。

在上述决定前，工程侧不应修改 `0` 交易次数的含义、不应把空 status 判成停牌、不应添加第二来源、不应跳过 `2023-01`，也不应继续后续月份。决定落实后只重跑该月，确认 `UNRESOLVED=0` 后再继续。

## 执行范围与验收状态（本次重跑后）

- 已完成的是 `37/78` 个月 capture；`2023-01` 已通过官方静态事件 retained replay，当前 blocker 已移动到 `2023-02` 的本地安全凭据可见性边界，未进入该月 provider 请求。
- 本地 QA：本次新增事件边界与 retained replay 回归已通过；完整 QA 数字以本次提交前最后一次运行结果为准，远端 CI 以新 commit 的 checks 为准。
- 78 个月的 receipt、authoritative coverage、bounded materialization、ordinary-reader、idempotency 和 changed-content conflict 尚未全部形成结论；因此不能称项目已完成，也没有 publication。
- 原始 payload、ledger、物化文件、账号/身份、网络地址、SDK/runtime 和凭证均未进入 GitHub；本文件只保留脱敏计数、request id、hash/规则引用、官方来源 URL 和阻断事实。
- 范围外的 Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1、baseline、策略和多源 reconciliation 仍未执行。

## 先前检查点（历史留存，已被后续执行替代）

## 已完成

- 基线：`main@ad2ad528d3ffec1269772084f0860c8224e632d2`；范围：2020-01 至 2026-06，共 78 个日历月。
- PM 已批准最小生命周期修复：复用已验证 security-master 的 `stock_basic.DELISTDATE`；仅当交易日 `session >= DELISTDATE` 时分类为 `NOT_APPLICABLE_SESSION`。不把前一日停牌 carry-forward，不用第二数据源，不跳过未决 pair。
- month-completeness/applicability 规则已升级到 v4；`DELISTDATE` 由 verified normalized security-master 进入 identity view，并只在实际排除 pair 时写入 evaluation 和 retained replay。既有 `LISTDATE`、PIT、raw closure 与 finalize 约束保持不变。

| 月份 | capture 结果 | required/returned | unresolved | 实际使用的生命周期事实 |
|---|---|---:|---:|---|
| 2020-01 | PASS（retained replay，未 finalize） | 59,930 / 59,930 | 0 | 既有 5 条 LISTDATE 事实 |
| 2020-02 | PASS（retained replay，未 finalize） | 75,463 / 75,463 | 0 | `600240.SH -> 2020-02-05` 的 DELISTDATE |

2020-02 的分类为 `NOT_APPLICABLE_SESSION=238`、`SUSPENSION_NON_TRADING=79`、
`POSITIVE_TRADE_COUNT_ACTIVE=20`、`UNRESOLVED=0`、`missing=0`、`extra=0`、
`structural=0`。原先 `600240.SH / 2020-02-05` 的缺状态 pair 因已验证 DELISTDATE 正好落在该交易日，按获批规则闭合；它不是把 02-03/02-04 状态外推成 02-05 停牌。

## 上一个检查点的阻断（历史快照）

执行器按 fail-fast 顺序到达 2020-03，但当前 Codex 执行进程看不到安全环境变量
`TGW_USERNAME`、`TGW_PASSWORD`、`TGW_SERVER_VIP`、`TGW_SERVER_PORT`，所以在 provider 登录前停止。
这是本地执行环境阻断，不是 2020-03 的 provider 数据结论；变量值没有写入聊天、本地跟踪文件或 GitHub。

项目管理者下一步只需在本机安全配置这四个变量，然后使用现有保留状态恢复执行。恢复后仍须逐月
capture PASS；出现新的 API、schema、语义、PIT 或身份 blocker 时立即停止并记录 exact month/pair，
不得跳过、carry-forward 或推断。

## 上一个检查点的本地 QA 与边界（历史快照）

- focused：`67 passed`。
- full offline pytest：`1874 passed, 3 skipped`。
- `ruff check src tests`、`ruff format --check src tests`、`mypy src/ashare_state`：通过。
- 2020-03 至 2026-06 的 76 个月未运行；尚未形成 78 个月的 receipt、authoritative coverage、
  materialization、ordinary-reader、idempotency 或 changed-content conflict 完成结论。
- 原始 payload、ledger、物化文件、账号/身份、网络地址、SDK/runtime 和凭证均未进入 GitHub；
  本记录只保留脱敏计数、规则版本和阻断原因。
- 范围外的 Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1、baseline、策略与多源
  reconciliation 均未执行。

对应机器记录见同目录 [`cr7_issue76_history_build_20260916.json`](cr7_issue76_history_build_20260916.json)。

