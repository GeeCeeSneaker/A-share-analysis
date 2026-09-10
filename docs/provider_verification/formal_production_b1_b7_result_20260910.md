# Formal Production B1-B7 · 完整运行结果与同 run verdict

日期：2026-09-10（Asia/Shanghai）
记录类型：真实正式运行的脱敏结果记录；不是独立 Provider approval。

## 1. 结论先行

本次唯一受控 Formal Production run 已完整执行 B1-B7，生命周期为 SPIKE CLOSED；随后仅对同一 run 执行一次 verdict，结果为 SPIKE_INCOMPLETE。

CLOSED 只表示 B1-B7 产生了终态记录，不表示 GO。verdict 明确列出 6 项 core FAILED、1 项 core MISSING，且 P0a/P0b 与历史回填资格均不可用。不得把本次结果表述为 Provider 通过、生产可用或允许回填。

## 2. 运行身份与授权一致性

| 项目 | 已确认值 |
|---|---|
| governing authorization | Issue #39，最新授权评论 5619810170 |
| exact command | uv run python scripts/spike/spike_runner.py --production --date 20260909 |
| run id | dad1e1b8-0c34-4031-8e94-cc87a03dbbf4 |
| run kind | PRODUCTION |
| source HEAD | fba18153a986cc1283a8c082e5d5629902d774cf |
| clean checkout | 运行前后均为空工作树 |
| as-of date | 20260909 |
| started / ended | 2026-09-10T22:03:02.372698+08:00 → 2026-09-10T23:09:53.298994+08:00 |
| terminal lifecycle | CLOSED |
| account profile | UNKNOWN_24e2ff401792（伪名） |
| SDK / runtime | AmazingData 1.1.9 / V4.3.0.260626-rc2.0-YHZQ |
| Golden | v7-reviewed-20260908，125 cases，SHA-256 a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e |
| trading rules | v20260910-h1r4-reviewed，REVIEWED，dataset 2026-09-10.2，SHA-256 b8b77ef83f5741c12a2effef988f793c0827f737ea471494814c1b0b6d7f9aed |

这次授权明确冻结为 20260909，实际命令与日期完全一致；没有复用旧失败 run，没有执行 resume，没有创建第二个 Production run。

## 3. B1-B7 实际结果

| 阶段 | 实际结果 | 供 Reviewer 对照的摘要 |
|---|---|---|
| B1 | 8 项 capability gate PASS；code_mapping_bj、industry_taxonomy 被 ENDPOINT_AVAILABLE 阻断 | gate 文件 10 个；API readiness 不能替代后续语义验证 |
| B2 | VALIDATED_FAIL | security master 返回 5,442 行；未据此推断退市连续性成立 |
| B3 | daily_bar=VALIDATED_FAIL；st_suspend=OBSERVED；limit=VALIDATED_FAIL；adj=OBSERVED | 观察态不升级为通过 |
| B4 | 125/125 VALIDATED_FAIL | Golden 版本与 hash 未修改，失败结果原样保留 |
| B5 | 已执行，但历史能力不成立 | calendar 8,723 行、5,562 symbols、BSE evidence 0；earliest=99991231 是观察到的输出，不接受为历史覆盖声明 |
| B6 | OBSERVED | 3 个 optional 观察案例；未升级为能力通过 |
| B7 | phase result 完整 | 5 个交易日、5,562 symbols、6,662,216 rows、1,031,721,881 bytes、5 requests、0 retries、0 failures、1,106.462 秒 |

B7 未再次出现前一 run 的 RawWriter DataFrame | None framework failure，因此本次确实闭合了完整 run；这不改变 B2-B5 的失败，也不构成 Provider approval。

## 4. 同 run verdict

verdict 文件：data/spike/production/dad1e1b8-0c34-4031-8e94-cc87a03dbbf4/verdict.json。执行命令：

uv run python scripts/spike/spike_runner.py --verdict --run-id dad1e1b8-0c34-4031-8e94-cc87a03dbbf4

结果：

- verdict：SPIKE_INCOMPLETE；
- core FAILED：security_master_with_delisted、daily_bar_units、historical_st_suspend、limit_price_and_no_limit_days、adj_factor_corporate_action_continuity、history_start_2020；
- core MISSING：symbol_mapping_unambiguous；
- optional SPIKE_INCOMPLETE：free_float_equivalence、sw_taxonomy、benchmark_index_availability、capacity_backfill；
- sdk_permission_cache_freshness=PASS；
- p0a_eligible=false、p0b_eligible=false、historical_backfill_eligible=NO。

## 5. Case catalog 与证据边界

本次 catalog 共 178 条，全部绑定 run id dad1e1b8-0c34-4031-8e94-cc87a03dbbf4：

| 分类 | 数量 |
|---|---:|
| Golden | 125 |
| runtime gate | 40 |
| 其他 B2-B7 / optional | 13 |
| 合计 | 178 |

结果计数为：VALIDATED_PASS=38、VALIDATED_FAIL=131、OBSERVED=6、MISSING=1、NOT_TESTABLE_PERMISSION=2。JSONL 的 SHA-256 是 bad92a04ae6008cc094d72a213f670f0ccdf9ab5befc285b29e46d0a7a9dee53，与 spike_run.json.case_catalog_hash 一致。

原始 Provider 文件仍只保存在本地 run 目录：27,974 个文件、369,934,607 bytes；路径+字节数清单摘要为 86baae3fd3cd448ceeb05cae5a13e3f4b08afdc37d6015b320fa3f889f9bca77。本 PR 不上传这些 raw 文件、原始 payload、账号、密码、真实 endpoint、Token、Cookie 或专有 SDK/runtime。

脱敏 receipt 及 spike_run.json、verdict.json、10 个 gate JSON、两份 catalog 的 SHA-256/字节数清单见 [formal_production_b1_b7_result_receipt_20260910.json](formal_production_b1_b7_result_receipt_20260910.json)。

## 6. 供独立 Reviewer 的下一道门

本 PR 只提交运行结果和审计锚点，不提交修复性 Provider 结论。Reviewer 应基于同一 run 的本地证据逐项复核：

1. B2 的退市覆盖为何为 VALIDATED_FAIL，以及 hist_code_list 的实际语义能否满足项目定义；
2. B3 daily-bar 单位、限价与 no-limit、历史 ST suspend、复权连续性的失败/观察边界；
3. B4 125 条 Golden 全部失败的逐案原因，确认没有因数据缺失而被误判成通过；
4. B5 99991231 sentinel、2020 起始覆盖与 BSE evidence=0 的关系；
5. B7 五日全市场 evidence 的完整性、run-bound lineage 和 RawWriter nullable-shape 修复后的 read-back；
6. verdict 的 fail-closed 逻辑与 CLOSED != GO 口径。

在独立 Reviewer 接受本结果前，不启动 backfill、策略扩展、生产化或新的 Formal Production run；如需修复能力，必须先形成新的整改方案与授权，不得用修改期望值或重写历史 evidence 规避本次失败。

## 7. 变更与验证声明

- 本次运行没有修改 Golden、trading rules、capability expectations 或 provider configuration；
- 没有从旧失败 run 拼接 phase/case/verdict；
- 没有启动 backfill 或策略扩展；
- 旧失败 run c3dc1f43-7678-461d-8824-e7b44186e0ac 的记录保持不可变历史；
- 本文件和 receipt 是唯一新增的治理安全结果材料，raw evidence 保留在本地供受控复核。
