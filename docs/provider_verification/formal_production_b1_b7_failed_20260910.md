# Formal Production B1-B7 · 2026-09-10 失败证据与整改记录

> 记录类型：真实正式运行的脱敏失败证据；不是 Provider verdict，也不是 GO/NO-GO 结论。

## 1. 结论先行

Issue #39 只授权了一次、且明确冻结为 `--production --date 20260908`；本次真实
Production attempt 实际使用了 `--date 20260909`，因此是**偏离调度授权 as-of 的真实
运行**，不能描述为按授权命令执行。由于它确实创建了 `SpikeRun`，一次性 attempt
额度按已消耗处理。该 run 以 `FAILED` 结束，`failure_reason=FRAMEWORK_ERROR`；失败
发生在 B7 首个全市场、单日 K 线 exchange 的 raw evidence 持久化边界，B7 没有产出
phase result；因此没有运行 `--verdict`，也没有把该 run 改写为 `CLOSED`。

失败不是账号未登录或网络不可达的推断：本次在线 preflight 已确认
`NETWORK_REACHABLE=REACHABLE`、`AUTHENTICATED=YES`、`QUERY_READY=YES`。这也不代表
Provider 数据能力已经通过；B2-B6 的真实结果仍需由 Reviewer 按 run-bound evidence
复核。

## 2. 运行身份与前置事实

| 项目 | 本次实际值 |
|---|---|
| source HEAD | `3082491b5af2affdba92b1992407452f6c8ccb2c` |
| clean checkout | 运行前 `git status --porcelain` 为空；从该 HEAD 建立独立 worktree |
| run id | `c3dc1f43-7678-461d-8824-e7b44186e0ac` |
| run kind | `PRODUCTION` |
| governing authorization | Issue #39；只允许 `--production --date 20260908` 一次 |
| actual command | `uv run python scripts/spike/spike_runner.py --production --date 20260909` |
| authorization conformance | `DEVIATED_AS_OF_DATE`；真实 run 已创建，旧授权不得重跑 |
| started | `2026-09-10T09:37:43.756184+00:00` |
| ended | `2026-09-10T10:39:59.913074+00:00` |
| as-of date | `20260909` |
| calendar resolution | 通过本次在线 `RealTarget.get_calendar_exchange -> AmazingDataProvider.get_calendar_exchange -> BaseData.get_calendar` 读取；解析时刻为 `2026-09-10T17:36:57.682883+08:00`；当日为交易日，按“严格取前一完整交易日”解析为 `20260909` |
| account profile | `UNKNOWN_24e2ff401792`（仅伪匿名 ID） |
| SDK / TGW | `AmazingData 1.1.9` / `tgw 1.0.9.2` |
| runtime | `V4.3.0.260626-rc2.0-YHZQ` |
| environment lock hash | `03f61918aed5caec38359e96ed0804b556551a53ebbad07eabb6a02e4533c3bd` |
| production config hash | `a65d07584f7ed93c6d5ec23cf4d3ca5f1427b89bef3a17b0487b5b61c00c2c14` |
| Golden | `v7-reviewed-20260908`，125 cases，dataset hash `a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e` |
| trading rules | `v20260910-h1r4-reviewed`，`REVIEWED`，dataset version `2026-09-10.2`，manifest-style hash `b8b77ef83f5741c12a2effef988f793c0827f737ea471494814c1b0b6d7f9aed` |

密码、真实 endpoint、Token、Cookie、原始 profile、专有 SDK/runtime 文件和 Provider
原始数据均未写入 GitHub。

## 3. B1-B7 紧凑结果矩阵

| 阶段 | 本次运行输出 | 证据解释 |
|---|---|---|
| B1 | capabilities：`trade_calendar=PASS`、`security_master=PASS`、`daily_bar=PASS`、`index_daily=PASS`；`code_mapping_bj`、`security_status_history`、`adj_factor`、`corporate_action`、`equity_structure`、`industry_taxonomy` 为 `BLOCKED_BY_ENDPOINT_AVAILABLE` | 真实 gate 结果，不能等同于全部能力通过 |
| B2 | `rows=5442`，`VALIDATED_FAIL` | 已执行并记录真实校验失败 |
| B3 | `daily_bar=VALIDATED_FAIL`；`st_suspend/limit/adj=NOT_TESTABLE` | 依赖能力未满足，未强行补判 |
| B4 | `golden_cases=125`；`MISSING=105`、`VALIDATED_FAIL=20` | 未把缺失或失败改写成通过 |
| B5 | `calendar_rows=8723`、`symbols=5562`、`bse_evidence_rows=0`；代码当次输出 `earliest=99991231` | 这是待整改的数据/输出问题，尚未被解释为有效历史覆盖 |
| B6 | `OBSERVED` | 只记录观察结果，不升级为能力通过 |
| B7 | 未产出 phase result；在首个全市场单日 K 线 exchange 的 raw 写入处触发 `RawWriterError` | 失败边界明确，未进行静默重试或另起 run |

截至失败边界，run-scoped case catalog 已 best-effort flush；按本地 JSONL/CSV 实际
重算共 172 条记录（125 条 Golden、36 条 runtime gate、11 条其他 B2-B6 记录），
catalog 未封印，`case_catalog_hash` 为空。它不能替代完整的 B7 evidence closure。

## 4. 根因与整改

### 已确认根因

AmazingData 的 `MarketData.query_kline` 对全市场请求返回
`dict[security_code, DataFrame | None]`：有当日行的证券对应 DataFrame，没有当日行的
证券对应 `None`。旧 `RawWriter` 只接受“字典值全部为 DataFrame”或“全部为
`list[dict]`”，于是把合法的可选空成员误报为 unsupported payload shape，并抛出：

```text
RawWriterError: unsupported payload shape: dict values must ALL be DataFrames or ALL be list[dict]
(got value types: ['DataFrame', 'NoneType']); silently taking one dict value is forbidden
```

这里的“禁止取第一个值”保护本身仍然正确；错误在于没有把 Provider 已定义的
`DataFrame | None` 映射形状纳入有损失语义的持久化合同。

### 当前分支已完成的修复

- `RawWriter` 现在对 `dict[str, DataFrame | None]` 和 `dict[str, list[dict] | None]`
  进行显式分类；实际表继续各自写入 Parquet。
- `None` 成员不生成虚假数据行、不被丢弃，代码名写入 raw meta 的 `null_tables`，
  `RawWriter.read()` 还原为 `None`。
- 任意其他混合类型仍然 fail loud；没有恢复“静默取一个字典值”。
- 新增 DataFrame/None 形状的 field-level 回归测试；RawWriter shape、B7 exchange
  completeness、probe exchange enforcement 和 Spike framework 测试均通过。

这项修复只修复 evidence writer 对已确认 Provider 返回形状的兼容性，不改变 Golden
期望值、交易规则、能力判定或 Provider 返回数据，也不把本次 FAILED run 重新计算为
成功。

## 5. Run-bound evidence 引用

原始 run artifact 仅保留在执行 worktree 的本地 `data/spike/production/`，不提交到
GitHub：

```text
production/c3dc1f43-7678-461d-8824-e7b44186e0ac/spike_run.json
production/c3dc1f43-7678-461d-8824-e7b44186e0ac/gates/*.json
production/c3dc1f43-7678-461d-8824-e7b44186e0ac/cases/spike_case_catalog.jsonl
production/c3dc1f43-7678-461d-8824-e7b44186e0ac/raw/provider=amazingdata/dataset=*/
```

`spike_run.json` 是 lifecycle/failure identity 的来源；gate JSON 是 B1 capability
链的来源；case catalog 是截至失败边界的 best-effort case 记录；raw meta/Parquet
是已成功写入 exchange 的本地证据。失败的那个 B7 exchange 没有获得 meta anchor，
这正是本次框架问题的一部分，不能伪称已闭合。

为使独立 Reviewer 不必访问执行 worktree，本次新增了脱敏、可提交的 durable receipt：
[`formal_production_b1_b7_receipt_20260910.json`](formal_production_b1_b7_receipt_20260910.json)。
它只保存 lifecycle/dataset identity、B1-B6 摘要、B7 缺失声明以及 `spike_run.json`、
10 个 gate JSON 和两种 case catalog 导出的字节数与 SHA-256；不包含 Provider 原始
数据、账号凭据或专有运行时文件。receipt 中的 catalog 计数以实际文件为准，覆盖早先
记录中的错误 `166` 计数。

## 6. 禁止动作与下一步出口

本次 run 已是 `FAILED`，不是 `RUNNING`，所以：

1. 不执行 `--resume`；resume 只适用于真实硬中断且原 run 仍为 `RUNNING`。
2. 不执行 `--verdict`；verdict 只适用于同一 run 合法进入 `CLOSED`。
3. 不再启动第二次 Formal Production 来覆盖本次失败；本次授权已经消耗。
4. 先由独立 Reviewer 审阅本记录和修复 diff；合并修复后，若仍需 Formal Provider
   结论，必须由项目管理者提供新的、明确的一次性正式运行授权，并从新的 clean
   main 重新做 preflight、as-of 解析和全量 B1-B7。

本记录的状态是：`FORMAL ATTEMPT FAILED / EVIDENCE RETAINED / VERDICT NOT RUN /
WRITER FIX IN REVIEW / NEW ATTEMPT AUTHORIZATION REQUIRED`。
