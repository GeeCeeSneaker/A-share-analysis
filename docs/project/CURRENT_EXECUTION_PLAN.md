# Current Execution Plan

> 本文件是项目**当前执行控制面**。开发人员用它确认：当前主线做到哪里、唯一 P0 是什么、允许做什么、做到什么算完成、完成后由谁决定下一步。
>
> 历史决策继续保留在 `docs/project/DEVELOPMENT_MANAGEMENT.md`、`docs/DEVLOG.md`、Issues 和 PR reviews 中；日常接任务优先读取本文件与当前 Issue。

## 1. 项目管理责任

- **项目 Owner**：决定总体方向、数据源是否可信、例外授权和最终业务取舍。
- **项目经理 / 审计负责人**：读取最新 `main`、Issue、PR、CI 与开发证据；选择唯一主线；对 exact head 给出 `PASS / REMEDIATE / STOP(BLOCKED)`；每次审阅后更新本文件和对应 Issue 的下一任务、验收、依赖与禁止项。
- **开发执行者（Codex / Agent / 本地开发人员）**：只执行当前授权任务，不自行扩大范围；完成后提交 branch/PR、测试、CI 与证据，等待下一次调度。

审阅结束不能只写“等待下一步”。PASS 必须产生下一任务；REMEDIATE 必须产生可执行整改；BLOCKED 必须写清解除阻断所需最小证据。

## 2. 仓库与数据源治理原则

### 2.1 仓库操作

- 本地 clone / worktree 是代码内容操作的首选路径；GitHub Connector/API 主要用于 Issue、PR、review、Actions/CI 等控制面操作或回退。
- 远端写入、review 接受或 merge 前必须核对 exact base/head SHA。
- 本地 Git 与 Connector/API 不一致时先停止写入并完成同步解释。

### 2.2 数据源信任模型

- **数据源是否可信由 Owner 判定，不要求代码证明。**
- 当前 AmazingData 是 Owner 指定的可信数据源。
- 代码负责验证的是我们自己的工程正确性：调用方法和参数、请求范围、返回格式/schema、缺失/部分数据、PIT/available-at、适配、持久化、重放与物化完整性。
- 不要求 AmazingData 提供签名、证书或第三方 attestation 才能成为当前数据源。
- 不预先建设多源仲裁框架。只有未来 Owner 指定多个可信源，且它们对同一事实实际出现不一致时，才单独研究冲突处理规则。

## 3. 当前主线状态

**阶段**：Phase 0 / CR-7 historical research data foundation

PR #58 已通过项目经理 exact-head 审阅并合并：

- reviewed head：`3712c7fed165eb3e83625b023b68a47aefdf0332`
- merge commit：`31515992021e34517de0b764dd1ebb7f9e7ef35b`
- Issue #55：已完成并关闭

当前主线已经具备：

- verified historical projection / typed coverage basis；
- `TEST_FIXTURE_ONLY` 与 `AUTHORITATIVE_UPSTREAM` 隔离；
- Owner-approved AmazingData typed acquisition receipt；
- exact calendar / historical code-list / daily-bar request identity binding；
- AnchoredRawEvidenceWriter + immutable capture catalog；
- raw evidence / catalog replay verification；
- sidecar、materializer、ordinary reader fail-closed gates；
- fixture / arbitrary caller bytes 无法直接铸造 authoritative evidence；
- 78 个逻辑月份 inventory、staging、atomic publication、idempotent replay / conflict rejection。

**尚未完成**：真实 2020-01 至 2026-06 的 78 月 authoritative historical materialization。

当前阻断不再是“数据源是否可信”，而是我们尚未证明**真实 A 股月度完整性的工程判定规则**。PR #58 中的实现为了安全采用保守规则：月度历史代码表中的每只证券都必须在该月每个交易日存在 daily bar。该规则在真实市场上可能把停牌、月中上市/退市等合法无 bar 情况误判为数据缺失，因此在 broad backfill 前必须用 AmazingData 自身语义验证并修正。

## 4. 当前唯一 P0

**Issue #59 — `P0: validate AmazingData month-completeness semantics and bounded full-scope receipts`**

开发起点：先本地 `git fetch`，从包含本文件最新版本的最新 clean `main` 建立 worktree；记录实际 base SHA，并确认 PR #58 merge `31515992021e34517de0b764dd1ebb7f9e7ef35b` 是该 base 的祖先。

### 4.1 Stage A — 2024-01 真实全量诊断

本任务明确授权对 **2024-01** 做一个 bounded、Universe-complete 的真实诊断：

1. 通过 reviewed AmazingData path 获取该月 historical universe、交易日历和 full daily-bar response；
2. 使用最小必要的 AmazingData 语义接口解释缺失 security-date pair，例如历史证券状态 / 停牌状态或精确日期的历史代码适用性；
3. 只提交脱敏后的计数、分类、hash 和结论；raw payload、凭证、私有 endpoint、专有 SDK/runtime 不进入 GitHub；
4. 缺失 pair 至少分成：
   - AmazingData 支持的停牌 / 合法不交易；
   - 证券在该 session 不适用（上市/退市或等价 applicability）；
   - API/请求/shape mismatch；
   - 无法解释的 missing pair。

禁止从“没有 bar”本身反推停牌、未上市或退市。无法由 AmazingData 已有语义解释的情况保持 `UNRESOLVED` 并 fail closed。

### 4.2 完整性规则整改

Stage A 证据出来后，定义 versioned deterministic expected-bar set：

- 每个交易日哪些证券应适用；
- 哪些适用 session 因合法停牌等原因不要求 bar；
- 哪些 security-date pair 必须有 bar；
- extra/missing rows 的判定；
- schema/range/request/PIT 漂移的 fail-closed 行为。

除非 Stage A 真实证据证明它正确，否则不得继续使用 `month_code_list × all trading days` 作为完整性定义。

该规则必须进入 receipt identity / replay contract，保证首次取数与后续重放使用同一版本语义。

### 4.3 Stage B — 2020-01 与 2026-01

只有 Stage A 规则闭合、focused/full QA 通过后，才授权同一 bounded full-scope path 再执行：

- Development：`2020-01`
- Holdout：`2026-01`

三个代表月分别必须得到以下二者之一：

A. 可重现的 `AUTHORITATIVE_UPSTREAM` full-scope receipt，并证明 materializer/reader 能正确消费；或

B. 精确、可审计的 fail-closed semantic/API blocker。

### 4.4 当前执行记录（2026-09-14）

> 本节记录的是整改前探索性观察。后续 exact-head 审阅确认精确日请求窗口错误，且 Stage B
> 当时误通过了非 `PASS` 的 Stage A gate；下列 Stage A/B 结果均不构成当前验收证据，修正状态见 4.5。

Issue #59 的实际开发 base 为 `67f37d7ef7a084d775d14dbd0d474e1604e96d25`，且已确认
PR #58 merge `31515992021e34517de0b764dd1ebb7f9e7ef35b` 是其祖先。Stage A 已通过同一
AmazingData SPIKE 路径取得并在本地 ignored raw 中保留完整的 2024-01 观察：22 个交易日、
5,106 个月度证券、22 个精确日历史代码表、全量历史状态和全量日线，共 26 个成功交换。

Stage A 的版本化规则已经替换旧的 `month_universe × all_sessions` 交叉乘积：精确日代码表
定义 session applicability，`IS_SUSP_SEC=1` 定义合法非交易，只有 `IS_SUSP_SEC=0` 的
适用 pair 进入必需 bar 集合；未知状态不转成“不适用”。离线重放结果为：132 个
`SUSPENSION_NON_TRADING`、115 个 `NOT_APPLICABLE_SESSION`、0 个必需 bar 缺失，说明这些
合法 gap 未被误报为数据损失；但供应商状态响应有 1 个无列成员和共 32 个适用 pair 无状态
覆盖，另有 22 个返回行落在尚未证明必需的 pair 上，因此整体仍为 `FAIL_CLOSED`，不是
authoritative receipt。

实测重取时供应商在第 10 个精确日窗口返回 `ProviderPermissionError`；该次只写了本地
忽略证据且未覆盖既有完整观察。Stage B 已按固定的 `2020-01` Development 与
`2026-01` Holdout 进程隔离执行；两个 worker 均完整跑完（分别 20、24 个成功交换），
没有超时，也没有把一个月份的原始证据或状态带入另一个月份。单月原生 SDK 卡住时由父进程
以固定 900 秒 OS 边界收口；这不是把 SDK 的 `TimeBudget` 宣称为硬超时。

Stage B 的脱敏结果见
[`cr7_month_completeness_stage_b_20260914.json`](../provider_verification/cr7_month_completeness_stage_b_20260914.json)：
两个月均为 `FAIL_CLOSED`，没有产生 authoritative receipt，也没有进入 materializer。
`2020-01` 的 3 个状态成员为不可读/零列表，触发 `STATUS_SCHEMA_MISMATCH`，并留下 36 个
`UNRESOLVED` pair；返回但尚未被状态证明为必需的 16 个 pair 也不作通过依据。`2026-01`
没有结构错误，但仍有 4 个 `UNRESOLVED` pair。两个月的必需 bar 缺失均为 0；这只说明
已判定为必需的集合没有观察到缺 bar，不能覆盖未决状态问题。

因此当前最小下一任务是要求 AmazingData 状态接口/适配层明确并稳定提供：每个返回成员的
可读 schema，以及足以区分“状态未变化”与“状态数据缺失”的完整月内语义。禁止用“无状态
行即未变化”、跨源补齐或额外 heuristic 清除 2020 的 36 个或 2026 的 4 个未决 pair。
整改后只重跑本 Issue 授权的三个代表月并重新核对 receipt/materializer gate；在此之前不做
78 月回补。

本地复现入口固定为（需要本地未跟踪的 `.env`，输出目录均已忽略）：

```text
uv run python scripts/spike/cr7_month_completeness_semantics.py --env-file .env --output data/spike/cr7-month-completeness-semantics-stage-a-20260914/report.json
uv run python scripts/spike/cr7_month_completeness_semantics.py --stage-b --env-file .env --stage-a-report docs/provider_verification/cr7_month_completeness_stage_a_20260914.json --output data/spike/cr7-month-completeness-semantics-stage-b-20260914/report-process-isolated.json
```

第二条命令只接受脚本内固定的两个 Stage B 月份，不接受自由日期、Universe、resume 或
production 参数；worker 输出会保留在本地 ignored raw 目录，提交的 JSON 仅为脱敏摘要。

当前源码及聚焦回归已通过；全量 pytest 已通过（退出码 0，3 个既有 Windows symlink
权限 skip）。本阶段仍保持 `CLOSURE_DESIGN_ONLY_NOT_ACTIVE`，不铸造 authoritative receipt、
不进入 materializer、不做 78 月回补，也不执行 Formal B1-B7、Production、BSE/index、
CR-5/R2、Golden/H1、baseline 或策略工作。

### 4.5 Exact-head 审阅整改（2026-09-14）

项目经理对 PR #61 的 exact head `089e4fa6ef2395bee1997b1e504cf5fb67c79502` 给出
`REMEDIATE / KEEP DRAFT / DO NOT MERGE`。审阅确认 AmazingData 的 `get_hist_code_list`
两端都是闭区间，因此旧实现用 `[D,D+1]` 取得的“精确日”观察可能混入 D+1 才适用的证券，旧
计数不能作为语义验收依据；旧 Stage B 还在 Stage A 为 `FAIL_CLOSED` 时越过了错误的 gate。

已提交整改 `c00524762827edf4acc34e992366e81e91f31825`：

- acquisition、bounded diagnostic、retained replay 和离线 fake 全部改用
  `start_date == end_date == D`；
- applicability 版本升为 `amazingdata-hist-code-list-exact-session-v2`，因此旧版本的
  两日证据不能被当作新语义重放；
- Stage B 只接受当前 rule/applicability version 且 evaluation `status == PASS` 的 Stage A；
  `FAIL_CLOSED` 会返回 `STAGE_A_GATE_BLOCKED`，不会调用 Provider；
- 增加“证券只在 D+1 出现时，D 不得进入适用集合”的回归，以及精确请求和版本 gate 回归。

下一步必须先取得该提交的三平台 exact-head CI；CI 通过后只从该不可变提交重跑 Stage A
`2024-01`，并把真实运行使用的 code head 写入新的脱敏报告。此前的 Stage B 报告仅保留为
历史诊断、明确标记为非验收证据；不得重跑 Stage B，不得进行 78 月回补。

## 5. 当前明确禁止

Issue #59 **不授权**：

- 2020-01 至 2026-06 的 78 月 broad backfill / materialization；
- 第三次 Formal B1-B7；
- Production `--resume` / `--verdict`；
- BSE mapping 或 index 激活；
- CR-5/R2 feature export；
- Golden/H1/global baseline 修改；
- 策略实现或参数优化；
- 外部 source-trust 证明机制；
- 没有真实多源冲突时建设 multi-source arbitration。

**例外授权**：仅 Issue #59 指定的 `2024-01`、`2020-01`、`2026-01` 可以进行 bounded universe-complete diagnostic；这不构成 78 月 universe sweep 授权。

## 6. Issue #59 验收标准

开发 PR 进入最终审阅前必须同时满足：

- exact base/head SHA 可复核；
- focused tests 通过；
- 全量 repository QA 通过；
- exact-head CI 绿色；
- AmazingData 信任模型未被重新复杂化；
- fixture/caller 仍不能绕过 AmazingData acquisition path；
- 合法 suspension/applicability gap 不被误判为数据损坏；
- unexplained missing/extra row、malformed shape、scope/request drift、PIT violation 仍 fail closed；
- Stage A `2024-01` 有真实 full-scope 脱敏诊断；
- Stage B 只在 Stage A 规则闭合后执行；
- 三个月分别有 authoritative receipt/materializer proof 或具体 fail-closed blocker；
- 没有扩大到 78 月 backfill。

## 7. 审阅后的调度

### PASS

如果三个代表月都稳定产生 authoritative receipts，且 materializer / ordinary reader 的 replay、corruption、identity gates 全部通过：项目经理下一步可授权**受控 78 月 historical materialization**。

### REMEDIATE

若问题属于我们自己的 completeness semantics / adapter / request / format / PIT 实现，发最小整改任务；不得用 heuristic 掩盖缺口，也不得自行换数据源。

### STOP / BLOCKED

若 AmazingData 当前接口无法给出解释某类缺 bar 所需的语义事实，记录具体 blocker 并停止相应范围；是否增加其他数据源由 Owner 决定。

## 8. 后续路线（非当前授权）

1. Issue #59 三个月 completeness closure；
2. controlled 78-month authoritative historical materialization；
3. 全量 coverage / artifact lineage / replay / corruption E2E；
4. 数据基座 Freeze Gate；
5. CR-5/R2 与研究特征层；
6. `Quantitative-Strategy-Research` 等策略项目正式消费本数据基座。

策略研究不得反向改变数据口径；参数优化不得补偿数据或交易逻辑缺陷。

---

**Last scheduler update**：2026-09-14

**Current task**：Issue #59

**Required ancestor**：PR #58 merge `31515992021e34517de0b764dd1ebb7f9e7ef35b`；实际开发 base 必须是包含本文件最新版本的最新 clean `main`，并记录 exact SHA。
