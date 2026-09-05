# A-share-analysis T3 关闭与 Formal Production B1-B7 执行要求

> Date: 2026-09-05  
> T1 evidence PR: #13 / merge `df78ad984de3817bb55b480372eef0a8f786dc99`  
> T1 retrospective Reviewer review: `5121721955`  
> T2 Owner confirmation: PR #13 Owner-authored confirmation for `UNKNOWN_24e2ff401792`  
> T3 PR: #14  
> Reviewed T3 head: `3e9999ceab8084b1e438f9494277f9d2586529ea`  
> T3 Reviewer review: `5121723165`  
> T3 CI: GitHub Actions `33971997542` / run 307 SUCCESS  
> T3 merge: `16ab22b0a2e6046ef4d162e424cbe4286e793857`  
> Status: **T1 VERIFIED / T2 CONFIRMED / T3 VERIFIED+CLOSED / FORMAL PRODUCTION B1-B7 AUTHORIZED**

## 1. 当前权威状态

生产身份治理链已经闭合：

```text
T1 controlled online bootstrap     VERIFIED
T2 human identity confirmation     CONFIRMED
T3 production identity freeze      VERIFIED / MERGED
Formal Production B1-B7            AUTHORIZED / NOT YET REVIEWED
Data Sufficiency Matrix            BLOCKED BY FORMAL RUN REVIEW
Provider capability decision       BLOCKED
2020+ backfill                      BLOCKED
```

当前冻结配置必须保持：

```yaml
production_account_profile_id: "UNKNOWN_24e2ff401792"
confirmed_at: "2026-09-05T22:19:58+08:00"
confirmed_by: "project-owner"
```

该配置只解决“正式运行必须绑定哪一个已确认账号身份”。它不等于 Provider capability approval，也不证明任何数据集完整性。

## 2. PR #13 流程偏差记录

PR #13 的 T1 evidence 内容经事后独立复核为有效，但它在正式 Reviewer closure review 记录前已经被合并。这是 **governance sequencing deviation**，不是 T1 证据失效。

从本阶段开始恢复强制顺序：

```text
developer evidence PR
    -> final required CI
    -> Reviewer independent closure
    -> only then merge
```

不得因为仓库 Owner/开发者/Reviewer 使用同一个 GitHub 写入账号，就省略项目管理层的独立审阅步骤。无法使用 GitHub APPROVE/REQUEST_CHANGES 自审时，继续使用 COMMENT review 明确项目裁决。

## 3. Formal Production B1-B7 的唯一允许执行模型

### 3.1 环境与源码基线

使用受控 Windows 正式 SDK 环境：

- clean checkout of current `main`；
- 必须包含 T3 merge `16ab22b0a2e6046ef4d162e424cbe4286e793857` 或其后的 Reviewer-only documentation head；
- Python / AmazingData / TGW runtime 绑定到执行记录；
- 凭证仍只通过本地进程环境或 gitignored `.env` 注入；
- 禁止将 username/password/Token/真实 host/port/raw profile/raw SDK stdout/stderr/专有 SDK 文件上传 GitHub。

正式 run 开始前，代码必须能从 `configs/production_account.yaml` 读取 exact frozen identity，并在运行时 fail closed 地验证实际账号 identity 与其精确一致。任何 mismatch 都不是新的 candidate，而是正式运行阻断。

### 3.2 as-of date

`--date` 必须选择一个已经完整结束的交易日。不要在管理文档中硬编码猜测日期；使用项目受治理的交易日历/Provider 事实确认目标日期已经完成交易后再执行。

### 3.3 单一 governed Production run

唯一正式入口：

```powershell
uv run python scripts/spike/spike_runner.py --production --date <latest-complete-trading-day>
```

要求：

1. 一个 `RunKind.PRODUCTION` run 完整执行 `B1,B2,B3,B4,B5,B6,B7`；
2. 不接受 caller-selected `--phase bN`；
3. 不得把 Trial、dry-run、T1 bootstrap、provider-doctor、旧 smoke 或多个 Production run 拼接成一个正式 verdict；
4. 所有正式 case/evidence/verdict 必须绑定同一个 `run_id`、同一个 frozen profile、同一个 source SHA、同一个 `as_of_date`；
5. 任何为了“补一个失败 phase”而新开局部 run 的结果不得替代原正式 run。

### 3.4 Resume 纪律

只有硬进程中断导致原 run 仍为 `RUNNING` 时，才允许：

```powershell
uv run python scripts/spike/spike_runner.py --production --resume --run-id <id>
```

Production resume 必须 replay-all B1-B7。省略 `--date` 时使用原 run 固化的 `as_of_date`；显式传入时必须 exact match。

普通 Python failure 应按现有语义进入 `FAILED`；operator interrupt 进入 `ABORTED`。不要通过 resume 或新 run 把真实 fatal failure 静默升级为成功。

## 4. CLOSED、FAIL 与 verdict 的语义

必须继续保持现有冻结语义：

- B2/B3/B4 等 blocking semantic check 可以得到 `VALIDATED_FAIL`；
- 如果全部 B1-B7 已执行完，run 可以进入 `CLOSED`；
- `CLOSED` 只表示执行完整，不表示业务 GO；
- formal verdict 必须对 blocking failure 给出 `NO_GO` / fail-closed 结果；
- auth/account/framework fatal failure 才进入 `FAILED`。

因此不要为了追求“所有 case 都 PASS”而改变事实、重写 Golden、调参数或过滤失败证据。

run `CLOSED` 后，只能对同一个 run 计算正式 verdict：

```powershell
uv run python scripts/spike/spike_runner.py --verdict --run-id <id>
```

## 5. Formal run evidence package

完成一次正式 run 后，开发人员只提交一个 focused evidence PR，供 Reviewer 审阅。

### 必须记录

- source/main SHA；
- T3 frozen identity 的 scrubbed ID；
- controlled platform / Python / SDK / runtime version；
- `run_id`；
- `RunKind.PRODUCTION`；
- `as_of_date`；
- run started/completed timestamps；
- run terminal status；
- B1-B7 每 phase/case 的最终稳定状态和计数；
- run-scoped manifest/catalog/verdict 的安全相对引用与 hash（如现有合同提供）；
- formal verdict；
- 明确列出 blocking FAIL、optional missing、not-testable 或 denied capability；
- 明确声明所有 evidence 来自同一个 governed Production run。

### 禁止提交

- credentials / Token；
- real endpoint / host / port；
- raw SDK stdout/stderr；
- raw account profile；
- 未经安全投影的 SDK exception；
- 本地 `.env`；
- 专有 SDK 二进制；
- 仅为了证明结果而上传的大体量 raw provider payload。

如现有 run-scoped raw evidence 本身含受治理的数据内容，保留在本地/既有数据目录和元数据 hash 边界，不因为本次审核而复制进公开 Git 仓库。

## 6. Reviewer Exit Gate — Formal Production B1-B7

只有同时满足以下条件，Reviewer 才会接受本阶段 evidence：

- [ ] frozen identity exact-match 验证没有被绕过；
- [ ] one and only one governed Production run 作为正式结论来源；
- [ ] B1-B7 全部实际执行；
- [ ] 无 Trial/bootstrap/doctor/旧 smoke 证据替代；
- [ ] run lifecycle 与 CLOSED/FAILED/ABORTED 语义诚实；
- [ ] formal verdict 与 same `run_id` 绑定；
- [ ] blocking FAIL 保留并正确导致 NO_GO/fail-closed；
- [ ] evidence package 无秘密泄漏；
- [ ] `configs/production_account.yaml` 未被再次改写；
- [ ] evidence PR final head 的 Windows 3.14 / Windows 3.12 / Ubuntu 3.14 required CI 全部 SUCCESS；
- [ ] Reviewer 已提交正式 closure review，开发人员才允许 merge。

## 7. 本阶段明确不授权的工作

Formal B1-B7 之前/期间不要同时启动：

- Data Sufficiency Matrix 最终裁决；
- AmazingData capability `APPROVED`；
- 2020-01-01 -> current backfill；
- strategy/backtest/trading；
- 为追求 GO 而改 Golden / capability rule / CR-5 / CR-6 frozen semantics；
- REV-03/05/06/07/08 的大范围重构，除非 formal run 暴露一个具体 blocker，且先记录事实再单独分派。

## 8. Formal run 之后的顺序

Reviewer 接受 B1-B7 evidence 后，下一阶段才是：

```text
Formal B1-B7 evidence review
    -> Data Sufficiency Matrix (Core 8 + Optional 4, 2020+ readiness)
    -> Reviewer capability verdict: GO / CONDITIONAL GO / NO-GO
    -> close required audit gates before scale-up
       REV-03 recovery safety
       REV-05 historical/PIT research semantics
       REV-06 hard deadline before unattended/backfill
       REV-07 measured capacity before full-scale backfill
       REV-08 provenance/replay at its long-lived compatibility gate
    -> only after Provider approval + required gates: 2020+ backfill
```

## 9. Next developer task

**Execute exactly one controlled formal Production B1-B7 run under this contract, calculate the verdict for that same run if it reaches CLOSED, prepare the minimal safe evidence PR, and stop for Reviewer review.**

Do not merge that evidence PR before Reviewer closure.