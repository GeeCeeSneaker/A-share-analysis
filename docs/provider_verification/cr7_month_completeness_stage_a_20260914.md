# CR-7 `2024-01` Stage A 脱敏结果

**执行状态**：`PASS`

**执行时间**：2026-09-14 15:18:51 UTC  
**执行代码头**：`aeaf10acf3d3512ee63cfc03bcfa4f170002a8d3`  
**基线**：`main@738474acb47b0e2e90bead53d12b481a5af4a55f`  
**报告**：[`cr7_month_completeness_stage_a_20260914.json`](cr7_month_completeness_stage_a_20260914.json)

## 结果摘要

| 项目 | 结果 |
|---|---:|
| 交易日数 | 22 |
| 月度证券数 | 5,106 |
| 必需日×证券对 | 112,075 |
| 返回日×证券对 | 112,075 |
| fallback eligible / queried / positive | 22 / 22 / 22 |
| `POSITIVE_TRADE_COUNT_ACTIVE` | 22 |
| `SUSPENSION_NON_TRADING` | 132 |
| `NOT_APPLICABLE_SESSION` | 125 |
| `UNRESOLVED` | 0 |
| `EXTRA_RETURNED` | 0 |
| 结构错误 | 0 |

本次只验证 `2024-01`。对历史状态响应中明确为零行、零列的成员，逐个发出单证券、单交易日 `[D,D]`
的 `MarketData.query_snapshot` 请求；只有返回帧的 `code`、`trade_time` 与请求身份一致，且
`num_trades` 为有限严格正值时，才归类为 active。结果中 22 个候选全部满足该条件，因此月度完整性
评价达到 `PASS`。

## 边界与证据

- 月度规则版本：`amazingdata-month-completeness-rule-v2`。
- 正交易数 fallback 版本：`amazingdata-positive-trade-count-fallback-v1`。
- 报告 schema：`cr7.month_completeness_semantics.v2`。
- Provider 使用模式为 `SPIKE`；未创建 formal run，未启动 Stage B。
- authoritative receipt 未签发，materializer 未进入；本报告是有界诊断证据，不是 78 月历史物化授权。
- 原始响应和本地 anchors 只保存在本地 ignored 路径；仓库仅提交脱敏计数、身份绑定和 hash。
- `volume`、`amount`、价格、盘口、行存在本身、零值、缺字段或请求失败均未被当作 active 依据。

## 审阅要点

审阅人应核对报告中的 `code_head`、规则/fallback 版本、22 个交易日 hash、required/returned pair hash
以及 `unresolved/missing/extra/structural` 均为零。该 PASS 只覆盖当前单月和当前已批准的同源 fallback；
Stage B、78 月物化、Formal/Production、BSE/index、CR-5/R2、Golden/H1、baseline 和策略工作仍需
单独授权。

