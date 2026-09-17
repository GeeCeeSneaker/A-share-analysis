# Issue #76：78 个月权威历史构建执行记录

> 状态：**STOP(BLOCKED) at 2020-03 / 2 of 78 capture PASS / no publication**

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

## 当前阻断

执行器按 fail-fast 顺序到达 2020-03，但当前 Codex 执行进程看不到安全环境变量
`TGW_USERNAME`、`TGW_PASSWORD`、`TGW_SERVER_VIP`、`TGW_SERVER_PORT`，所以在 provider 登录前停止。
这是本地执行环境阻断，不是 2020-03 的 provider 数据结论；变量值没有写入聊天、本地跟踪文件或 GitHub。

项目管理者下一步只需在本机安全配置这四个变量，然后使用现有保留状态恢复执行。恢复后仍须逐月
capture PASS；出现新的 API、schema、语义、PIT 或身份 blocker 时立即停止并记录 exact month/pair，
不得跳过、carry-forward 或推断。

## 本地 QA 与边界

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
