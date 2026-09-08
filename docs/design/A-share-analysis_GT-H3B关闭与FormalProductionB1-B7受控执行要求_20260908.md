# A-share-analysis · GT-H3B 关闭与 Formal Production B1-B7 受控执行要求

日期：2026-09-08

## 1. 权威基线

本文件取代此前所有“GT-H3B 尚未封印 / Formal Production 仍由 Golden Human Review 阻塞”的阶段性指令。

已核验并关闭：

- PR #25：`chore: execute GT-H3B reviewed Golden seal`
- PR final head：`deb3cb1229d2628c92822e347e87602372c107c5`
- final test-merge：`6429e406fd3423cf201f06221b8f29f2db524cdf`
- final CI：run `34224351991`，Windows 3.12 / Windows 3.14 / Ubuntu 3.14 全部 SUCCESS；Ubuntu full pytest `1618 passed`
- controlled-execution final-head idempotent run：`34224352009` SUCCESS / no durable changes
- Reviewer final review：`5141932394`
- merge commit：`d5d98c2b1485a9a378f0c2dd9090b14f7b6168b1`

GT-H3B reviewed Golden 基线：

- ACTIVE truth version：`v7-reviewed-20260908`
- dataset：`golden_cases_v7.jsonl`
- dataset SHA256：`a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e`
- case count：125
- review summary：`REVIEWED 125/125`
- reviewer marker：`project-owner`
- counts：LIMIT 30 / CORPORATE ACTION 25 / ST TRANSITION 50 / DELIST 20
- ST：38 ADD / 12 REMOVE
- Golden gates：review / quantity / event coverage / production formal 均为空
- 5 个复合 case 已绑定 RULE → APPLICABILITY deterministic evidence bundles
- v1-v6 versioned Golden files 保持 immutable

结论：**GT-H3B VERIFIED / CLOSED。Golden Truth 不再阻塞 Formal Production。**

## 2. 当前唯一授权动作

从本基线起，授权 **一次 controlled Formal Production B1-B7 attempt**。

该授权不是 Provider GO，也不是 Data Sufficiency approval；只是允许在已经封印的 reviewed v7 Golden 上执行正式 Provider 验证。

禁止把 CI `--dry-run`、SDK-absent 测试或模拟输出解释为 Formal Production。

## 3. Formal Production 执行前条件

运行端在开始前必须逐项确认：

1. 工作树来源至少包含 `main@d5d98c2b1485a9a378f0c2dd9090b14f7b6168b1`，且不存在未审阅的 Golden 真值改动。
2. ACTIVE 必须仍为 `v7-reviewed-20260908`，dataset SHA256 必须精确为 `a51013f8...983e`，并且四类 Golden gate 仍为空。
3. Production identity 必须与已冻结身份 `UNKNOWN_24e2ff401792` 精确匹配；不得使用其他账号静默替代。
4. 实际 Provider SDK/runtime/network/auth/query readiness 必须重新记录本次运行时事实；不得直接继承历史 T1/T3 结论充当本次 run evidence。
5. `as_of_date` 不得由人工硬编码猜测。必须通过项目 / Provider 交易日历解析“运行时最近一个已经完整结束的 A 股交易日”，并把解析依据写入 evidence。
6. 不得把账号、Token、密码、endpoint secret、Cookie、原始 profile 或敏感 SDK 输出提交 Git。

## 4. 唯一标准执行路径

在第 3 节全部满足后：

```bash
uv run python scripts/spike/spike_runner.py --production --date <latest-complete-trading-day>
```

要求：

- B1-B7 必须作为一个完整 formal run 执行，不允许只挑“容易通过”的 phase。
- Golden、规则表、expected fields、capability 判定规则不得在运行过程中或看到结果后为了制造 GO 而修改。
- 任意 blocking VALIDATED_FAIL 必须按事实保留；`CLOSED` 不等于 `GO`。
- account/auth/framework fatal 应进入 `FAILED`，不得伪装成 ordinary capability NO_GO。
- 不允许为了改善结果重复启动多个独立正式 run 后只保留最好的一次。

### 唯一允许的 resume

只有真实硬中断且原 run 仍处于 `RUNNING` 时，才允许：

```bash
uv run python scripts/spike/spike_runner.py --production --resume --run-id <run-id>
```

resume 必须继续完整 B1-B7，并保持同一 run identity / evidence lineage。

## 5. Formal run 结束后的 verdict

若 run 合法进入 `CLOSED`，随后执行：

```bash
uv run python scripts/spike/spike_runner.py --verdict --run-id <run-id>
```

必须分别记录：

- run lifecycle 状态：RUNNING / CLOSED / FAILED
- Provider verdict：GO / CONDITIONAL GO / NO-GO（按当前代码实际定义为准，不预填结论）
- B1-B7 每阶段结果与 blocking / non-blocking failures
- actual runtime fingerprint
- formal `as_of_date`
- pseudonymous account profile ID
- run-bound artifact / evidence references

再次强调：**CLOSED != GO**。一个 blocking validation failure 可以是合法 `CLOSED + NO_GO`。

## 6. Formal Production evidence PR

正式运行后必须创建独立 evidence PR；不得直接把结果视为已批准。

PR 至少包含：

- source main SHA
- reviewed Golden version + dataset SHA
- formal run ID
- resolved `as_of_date` 及交易日历解析依据
- runtime / SDK fingerprint
- frozen production profile pseudonymous ID（不得写敏感原始身份信息）
- B1-B7 compact result matrix
- run lifecycle status
- verdict command/result（如果 run CLOSED）
- failure ledger / evidence artifact references
- 明确声明：未改 Golden 制造结果、未运行 backfill、未给 Data Sufficiency 最终批准
- final-head/current-main CI 状态（若 PR 包含代码或治理文件变更则必须重新满足仓库 required gates）

独立 Reviewer 必须检查实际 run-bound evidence 后才能给 Provider 结论。

## 7. Formal run 后的下一阶段

只有 Formal Production evidence 被 Reviewer 接受后，才进入：

1. Provider capability verdict 的正式关闭；
2. Data Sufficiency Matrix（Core8 + Optional4）；
3. 2020-01-01 至当前的覆盖率 / gap / workaround 评估；
4. BJ mapping/migration capability 作为此前明确延期项纳入 Data Sufficiency；
5. 按需要关闭 REV-03 / REV-05 / REV-06 / REV-07 / REV-08 后，才允许规模化 2020+ backfill。

Formal Production 通过也不等于立即全量 backfill。

## 8. 非阻断后续 hardening

以下两项已由 Reviewer 记录为非阻断改进，不重新打开 GT-H3B，也不阻塞本次 Formal Production：

1. `GT_H3B_EXECUTION_RECEIPT.json` 中 `source_main_sha` 实际记录的是 GitHub Actions `GITHUB_SHA`（PR merge-ref），不是 main parent；保留历史 receipt 原字节不改，后续 receipt schema 应改名或同时记录 `base_sha / merge_ref_sha / head_sha`。
2. `gt_h3b_execute.py::_verify_existing_seal()` 的幂等路径当前弱于首次 `_verify_reviewed_output()`；未来再次发布新的 reviewed Golden version 前，应让幂等 verifier 同样逐 evidence rehash、复验 composite bundle，并重跑所有 Golden gates。

这两项不得通过重写已经封印的 v7/evidence/receipt 来“修历史”。

## 9. 当前阶段状态

- GT-H3B：**CLOSED**
- reviewed Golden v7：**ACTIVE / REVIEWED 125/125**
- Formal Production B1-B7：**AUTHORIZED FOR ONE CONTROLLED ATTEMPT / NOT YET REVIEWED**
- Provider verdict：**NOT YET CLOSED**
- Data Sufficiency：**BLOCKED pending accepted Formal Production evidence**
- 2020+ full backfill：**BLOCKED**
- strategy / backtest / trading：不属于本阶段
