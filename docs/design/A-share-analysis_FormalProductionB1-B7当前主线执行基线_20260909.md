# A-share-analysis · Formal Production B1-B7 当前主线执行基线

日期：2026-09-09（Asia/Shanghai）

## 1. 目的与优先级

本文件将 GT-H3B 关闭后的 Formal Production 要求收敛为当前唯一可执行工作指令。

它不推翻以下既有事实与规则：

- `docs/design/A-share-analysis_GT-H3B关闭与FormalProductionB1-B7受控执行要求_20260908.md` 中关于单次 controlled attempt、B1-B7 全量执行、resume、verdict、evidence PR、CLOSED != GO 等规则继续有效；
- `docs/provider_verification/gt_h3b_local_formal_preflight_20260908.md` 作为历史预检事实记录继续保留；
- GT-H3B reviewed Golden v7 保持 ACTIVE / REVIEWED 125/125，不重新打开 Golden Human Review。

本文件只收紧“从哪个源码状态启动正式运行”以及“运行端现在具体要做什么”。若旧文档中的 source checkout / main SHA 表述与本文件冲突，以本文件为准。

## 2. 当前起始基线

本文件创建前已独立审阅并合并：

- PR #27：真实 sealed v7 corpus 离线强验证集成测试；merge commit `f28f6484e42f739b47ec72da74707a08c1c7e0b0`；
- PR #28：Formal Production 本地预检阻塞事实记录；merge commit `631a4c64e0c9286c41333141f593ae57e92a24aa`。

因此本轮执行准备的起始 parent baseline 为：

`main@631a4c64e0c9286c41333141f593ae57e92a24aa`

注意：本管理文件落入 main 后 main SHA 会自然前进。正式运行不得机械硬编码上述 parent SHA；运行端必须使用**执行时最新、已经审阅进入 main 的 clean checkout**，并把实际执行 HEAD SHA 写入 run-bound evidence。

## 3. 当前唯一主任务

停止继续扩展非必要 Golden / receipt / verifier hardening。

当前唯一主任务是：

> 在具备 AmazingData SDK/runtime 与正式账号环境的 Windows operator 上，准备一个执行时 current main 的完整、干净、可核验 checkout，并启动唯一一次受控 Formal Production B1-B7。

本任务不是“再做一次预检文档”，也不是 CI dry-run；目标是产生真实 `RunKind.PRODUCTION` run ID、完整 B1-B7 run-bound evidence 和同一 run 的最终 verdict（若 lifecycle 为 CLOSED）。

## 4. Clean checkout 强制要求

正式运行目录必须同时满足：

1. `git rev-parse HEAD` 等于执行时已审阅进入 `main` 的最新 commit；
2. `git status --porcelain` 为空；
3. 不允许从旧的 `work/audit_h1_c939b747` 脏副本直接运行；旧副本只作为历史/本地 SDK 介质来源，不作为正式 source tree；
4. checkout 必须完整包含 reviewed v7 Golden、evidence store、5 个 composite bundles、GT-H3B receipt、当前 `spike_runner.py`、Provider/Golden/capability 代码及相关配置；
5. 不得手工复制少量新文件到旧源码目录伪造“当前 main”；必须是可由 Git commit identity 证明的完整 tree；
6. 若执行前 main 又合并了会影响 Provider runner、Golden contract、capability 判定、production config 或 evidence semantics 的变更，必须重新以新的 current main 建 clean checkout；不得继续用旧 checkout。

可以在新的独立目录/`git worktree`/受治理 clone 中准备；不得为了 clean 而覆盖现有脏工作区中的用户文件。

## 5. SDK 与身份环境

允许复用此前已经验证过的本地 AmazingData SDK 安装介质，但必须在新的 clean checkout 对本次运行重新记录 runtime 事实。

本次正式 preflight 至少确认：

- AmazingData `1.1.9` 与 TGW `1.0.9.2` 实际可加载；
- runtime fingerprint 与已审定身份候选兼容；
- production profile pseudonymous ID 必须仍为 `UNKNOWN_24e2ff401792`，不得静默换账号；
- NETWORK_REACHABLE / AUTHENTICATED / QUERY_READY 必须由本次在线运行重新建立，不能用历史 T1/T3 结论代替；
- 任何密码、Token、Cookie、真实 endpoint、原始 profile、敏感 SDK 输出不得进入 Git。

离线 `SDK_INSTALLED` / `RUNTIME_ACTUAL_LOAD_VERIFIED` 仅是 preflight，不等于 Formal Production。

## 6. as_of_date 解析

禁止人工猜一个日期直接运行。

运行端必须先通过项目/Provider 交易日历确定“运行时最近一个已经完整结束的 A 股交易日”，并把：

- resolved date；
- 交易日历来源/调用；
- 解析时刻；
- 如遇节假日/周末的回退依据

写入 run-bound evidence。

## 7. 唯一正式执行命令

第 4-6 节全部通过后，只启动一次：

```bash
uv run python scripts/spike/spike_runner.py --production --date <provider-derived-date>
```

执行约束：

- B1-B7 必须属于同一个 production run；
- 不允许只跑部分 phase 后另起正式 run；
- 不允许看到结果后修改 Golden、expected fields、规则表、capability 判定条件来制造 GO；
- 不允许启动多个独立正式 run 后只保留最好结果；
- account/auth/framework fatal 按 FAILED 保存；
- blocking VALIDATED_FAIL 按事实保存，允许最终出现合法 `CLOSED + NO_GO`。

## 8. Resume 与 verdict

只有真实硬中断、且原 run lifecycle 仍为 `RUNNING`，才允许：

```bash
uv run python scripts/spike/spike_runner.py --production --resume --run-id <run-id>
```

必须继续同一个 run identity 和完整 B1-B7 lineage。

如果且仅如果同一正式 run 合法进入 `CLOSED`，执行：

```bash
uv run python scripts/spike/spike_runner.py --verdict --run-id <run-id>
```

不得对 FAILED run 伪造 CLOSED verdict，也不得用另一个 run 的结果拼接 verdict。

## 9. 正式 evidence PR 最低内容

正式运行结束后创建独立 evidence PR。至少包含脱敏的：

- actual source main/HEAD SHA；
- clean-worktree assertion；
- reviewed Golden `v7-reviewed-20260908` + dataset SHA256 `a51013f8fbfb2e9addceb4b75c2213d35a30c3b65459928164b77597aecb983e`；
- production run ID；
- resolved `as_of_date` 及交易日历依据；
- runtime / SDK fingerprint；
- pseudonymous profile `UNKNOWN_24e2ff401792`；
- B1-B7 compact matrix；
- lifecycle status；
- blocking / non-blocking failure ledger；
- run-bound artifact/evidence refs；
- verdict command/result（仅 CLOSED）；
- 明确声明没有修改 Golden/规则制造结果、没有启动 backfill。

正式 Provider 结论只由独立 Reviewer 基于这份 run-bound evidence 给出。

## 10. 验收与阶段出口

本轮完成标准不是“SDK 能加载”，而是以下之一：

### A. 合法 CLOSED

- B1-B7 完整；
- lifecycle = CLOSED；
- verdict 对同一 run_id 生成；
- evidence PR 可独立复核。

之后 Reviewer 给出 GO / CONDITIONAL GO / NO-GO，并决定是否进入 Data Sufficiency Matrix。

### B. 合法 FAILED

- fatal 原因与 run-bound failure evidence 完整保留；
- 不另起第二个正式 run 掩盖失败；
- Reviewer 先裁决是否需要整改以及是否授权新的正式 attempt。

### C. 执行前 fail-closed

若 clean checkout、identity、runtime、network/auth/query readiness 或交易日历解析未满足，则不得创建正式 run；记录 preflight blocker，但不记为 Provider NO-GO，也不消耗正式 attempt。

## 11. 当前阶段状态

- GT-H3B：CLOSED；
- reviewed Golden v7：ACTIVE / REVIEWED 125/125；
- real-corpus offline verifier：三平台集成回归已建立；
- Formal Production B1-B7：AUTHORIZED FOR ONE CONTROLLED ATTEMPT / NOT YET EXECUTED；
- Provider verdict：PENDING；
- Data Sufficiency Matrix：BLOCKED pending accepted Formal Production evidence；
- 2020+ backfill：BLOCKED。

从本文件起，除非出现新的真实 preflight blocker，不再以继续增加治理文档或 Golden hardening 代替 Formal Production 执行。
