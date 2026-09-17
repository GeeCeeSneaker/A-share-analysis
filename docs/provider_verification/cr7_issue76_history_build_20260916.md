# Issue #76：78 个月权威历史构建执行记录

> 状态：**STOP(BLOCKED) at 2020-02 / 1 of 78 capture closures / no publication**

## 结论

- 基线：`main@ad2ad528d3ffec1269772084f0860c8224e632d2`；范围是 2020-01 至 2026-06，共 78 个日历月。
- 真实 AmazingData 路径已启动。2020-01 使用已 hash-anchored 的留存捕获复放并通过 capture completeness：required/returned `59,930/59,930`，missing/extra/unresolved/structural `0/0/0/0`。
- 2020-02 使用新鲜 provider 捕获，日线返回 `75,463` 个 pair，required/returned `75,463/75,463`，missing/extra 均为 0；但有 1 个状态事实未决，评价为 `FAIL_CLOSED`，按 fail-fast 停止。
- 2020-03 至 2026-06 的 76 个月未运行。未生成 receipt、authoritative coverage、materialization、ordinary-reader、幂等或 changed-content conflict 结论；因此本 Issue 不是 PASS。

## 唯一阻断

| 项目 | 已确认事实 |
|---|---|
| pair | `600240.SH / 2020-02-05` |
| 当月宇宙 | 3,789 个证券；精确日代码表明确包含 `600240.SH` |
| PIT LISTDATE | `2000-06-28`；不是上市前配对 |
| status 返回 | 两次同范围请求均只给该证券 `2020-02-03`、`2020-02-04`，且 `IS_SUSP_SEC=1`；`2020-02-05` 无状态行 |
| daily bar 返回 | 该响应中 `600240.SH` 的 symbol table 不存在 |
| 规则结果 | `UNRESOLVED=1`、`missing=0`、`extra=0`、结构错误 `0`；不能把前两日暂停外推到 02-05 |

这不是“日线缺失已被证明为停牌”：当前合同要求先有逐日 status 事实，缺状态不能被历史状态、无 bar、代码前缀或请求顺序补成 suspension。必须由 Owner/项目管理者提供该日 provider-owned status 事实，或批准最小、明确记录的语义/API 合同变化；在此之前不跳过 2020-02，也不进入后续月份。

## 可复核证据

- `history_stock_status` 两次请求：`35d649b1-2b7b-47ba-8715-52a25a7f8d93`（content hash `55973d3c…f8cb`）和 `8628d292-e4dc-4ae6-96d3-748b3c3d723f`（`9c235b4f…1eee`）；均为 3,789 个证券、月范围、响应 75,522 行。
- 2020-02-05 exact-day `hist_code_list`：`09011e96-30ca-489f-af3f-26ca1bd6ef5f`，content hash `c93791d9…ae96`，3,769 行，包含目标证券。
- 月度 `daily_bar`：`56ca2084-48ac-456a-845c-f89d4fa12747`，content hash `2749690d…7c29`，75,463 行；目标 symbol table 为 absent。
- 逐月状态、完整性字段、未运行月份、请求范围和上述证据的完整 JSON 见本目录同名 `.json` 文件。原始 payload 与本地 ledger 未上传，仅保存在忽略目录。

## 运行器说明

首次尝试暴露了本地一次性运行器的三个编排问题：精确日列表缓存、合并 LISTDATE 在 retained replay 时未按月裁剪、以及阻断记录器参数冲突。三项均在最终真实结果前修复并做离线复放验证；没有修改生产代码，也没有把这些 harness 问题冒充为数据源结果。

## 下一步要求

1. 项目管理者/Owner 为 `600240.SH / 2020-02-05` 提供明确 provider-owned 状态事实，或在 Issue #76 上批准最小语义/API 合同调整。
2. 获批后从已保留的 2020-02 evidence 恢复该月，重新通过 completeness，再按原顺序继续 2020-03；不得用 carry-forward 或第二数据源静默填充。
3. 在 78/78 月全部 capture PASS、receipt/coverage/materialization/reader/replay/conflict 和 exact-head CI 全部通过前，不得宣称历史库完成。

本记录未包含凭证、账号/身份、网络地址、SDK/runtime、原始响应、数据库或物化文件；范围外的 Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1、策略与多源 reconciliation 均未执行。