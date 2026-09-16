# Current Execution Plan

> 本文件是项目**当前执行控制面**。开发人员用它确认：当前主线做到哪里、唯一 P0 是什么、允许做什么、做到什么算完成、完成后由谁决定下一步。
>
> 历史决策继续保留在 `docs/project/DEVELOPMENT_MANAGEMENT.md`、`docs/DEVLOG.md`、Issues 和 PR reviews 中；日常接任务优先读取本文件与当前 Issue。

## 0. 2026-09-15 当前调度覆盖

当前 clean `main` 为 `9423c1799ec970ea3d5076e1af5b3a5ab145ed8d`（PR #70 已合并）。当前唯一活动
P0 仍为 Issue #59：先完成完整 `2024-01` 的真实 source-input
Canonical → Snapshot → ReadModel → projection，再进入既有 acquisition → receipt replay →
coverage basis → bounded atomic materialization → ordinary-reader proof。

本文件后面的 Issue #66 文字是历史执行记录；如与本节或 Issue #59 当前 body 冲突，以本节和 Issue #59
为准。当前不授权 Stage B（`2020-01` / `2026-01`）、78 月回补、Formal/Production、BSE/index、
CR-5/R2、Golden/H1、baseline 或策略工作。

2026-09-15 的早期前置检查记录在
[`cr7_authoritative_2024_01_closure_20260915.md`](../provider_verification/cr7_authoritative_2024_01_closure_20260915.md)，
合并后的真实 source-input 继续执行记录在
[`cr7_authoritative_2024_01_source_input_20260915.md`](../provider_verification/cr7_authoritative_2024_01_source_input_20260915.md)。
本次最新适配与完整复核记录在
[`cr7_cr2_provider_native_shape_adapter_20260915.md`](../provider_verification/cr7_cr2_provider_native_shape_adapter_20260915.md)
及对应 JSON。结论为：三个观察到的 CR-2 shape/identity 入口均已 `SUCCESS`，完整真实输入的
`stock_basic` 返回 `5,105/5,106`；唯一缺失 `300114.SZ` 的单例请求为 `OK + 0 rows`，所以
最终代码版本重放的 Canonical run `958b02f2-e8c2-5815-be82-aa96ac6bf652` 以 `IDENTITY_MISSING (22)`
`STOP(BLOCKED)`。这不是账号、网络或适配器阻断，不能删除成员或填造 PIT identity；完整
verified source snapshot、receipt、coverage 和 materializer 仍未构造。

PR #70 已通过独立审阅并合并。合并后的单证券调查记录在
[`cr7_issue59_300114_identity_probe_20260915.md`](../provider_verification/cr7_issue59_300114_identity_probe_20260915.md)
及对应 JSON：`InfoData.get_stock_basic` 和底层 `DownloadInfoData.download_stock_basic` 对
`300114.SZ` 均为 `OK + 0 rows`，未找到 provider-owned identity/date evidence。当前不修改代码；
随后项目经理 review `5217204028` / Issue comment `5690045901` 修正了调查假设：不能因当前代码
空结果就认定历史 universe 错误，下一步应在同一 provider 内调查当前代码 `302132.SZ` 与历史
`300114.SZ` 的连续性。最新记录在
[`cr7_issue59_300114_302132_continuity_probe_20260915.md`](../provider_verification/cr7_issue59_300114_302132_continuity_probe_20260915.md)
及对应 JSON：`302132.SZ` 的两条既有 `stock_basic` 入口均 `OK + 1 row`，明确返回
`MARKET_CODE=302132.SZ`、`LISTDATE=20100827`、`IS_LISTED=1`，但没有返回或暴露绑定
`300114.SZ` 的 old/new relation、稳定跨代码 identity 或有效区间。因此当前仍为
`STOP(BLOCKED)`；不得静默改动 5,106-member universe、凭数字相似性加 alias 或继续下游链。
只有取得同一 provider 的 PIT 可用连续性证据后，才可提出最小映射并重跑既有链路；Stage B、
78 月及其他未授权工作继续禁止。

按最新 scheduler checkpoint `5691108824`，上一轮已确认的历史 DEVLOG 扫描器阻断已按最小治理
方案处理：从 PR #71 删除整个 `tests/integration/test_devlog_gate.py`，不替换为其他历史扫描器、
diff 扫描器、hook、policy engine 或 SHA allowlist。提交
`669137f7629f1b68e5a6401052cfd601c5b8530b` 的 exact-head CI `35049654822` 已在 Ubuntu 3.14、
Windows 3.14、Windows 3.12 三平台成功（每平台 `1848 passed, 6 skipped`，AmazingData SDK
absence 通过；GT-H3B `35049654866` 按范围跳过）。此前 `aa4a635...` 删除新增 grandfather
的失败结果仍作为历史证据保留，详见
[`cr7_issue59_pr71_devlog_cleanup_gate_blocker_20260915.md`](../provider_verification/cr7_issue59_pr71_devlog_cleanup_gate_blocker_20260915.md)
及对应 JSON。治理整改已通过 CI，但 PR #71 仍需独立审阅/合并；在该 PR 合并前，不启动身份
事件实现，也不重跑 2024-01 下游权威链。Stage B、78 月及其他未授权工作继续禁止。

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

PR #68 已通过项目经理 exact-head 审阅并合并：

- PR #68 exact head：`0da6ebb0b48dbcf3c725e90aac8ef7c83017e0ba`
- merge commit / 当前 clean main：`a7671ab34d301cb0aca2f351a31bbc865c100498`
- Issue #55、Issue #66：已完成并关闭；当前唯一开放 P0 为 Issue #59

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

`2024-01` 的单月工程判定规则已在历史 exact head `aeaf10acf3d3512ee63cfc03bcfa4f170002a8d3`
完成版本化实现并通过 bounded Stage A：22 个交易日、5,106 个证券、112,075 个 required
日×证券对全部闭合，unresolved/missing/extra/structural error 均为 0。Stage A PASS 不等于
authoritative receipt 或 78 月物化授权。

### 3.1 历史执行记录：Issue #66（已关闭）

Issue #66 当时的基线是 clean `main@ad25f7f8580ad745f3a4a652ae7d85553e8c51fd`。目标是
在重新推进 Stage B 之前，删除 CR-7 热路径中只为防御“同进程恶意调用者”而存在的包装和重复校验，
同时保留工程上真正有用的边界：请求 scope、schema/partial/missing fail-closed、语义完整性、
原始文件 hash/replay、PIT，以及物化的 atomic/idempotent 行为。

当时实现分支 `feat/issue66-minimalism-20260914` 已完成本地整改并取得新 exact head；整改对应 scheduler 对旧 exact head
`12adbb3e5310f6f75d775afd569a745a7533f9cc` 的 `REMEDIATE / KEEP DRAFT / DO NOT MERGE`
意见（PR #67 review `5205558820`，Issue #66 comment `5674829261`）。四项整改为：

- RawWriter 对 2024-01 已确认的“大量正常 DataFrame + 零行零列空 DataFrame + 显式
  `None`”状态响应维持 request 级 O(1) 物理文件数；成员 inventory 保留每个成员的原始列形态，
  空表恢复为 `(0, 0)`，`None` 不与空表混淆；
- packed 读取只做一次有界 `partition_by` 分组扫描，再按 inventory 重建成员；基准同时记录读取/重建
  耗时，不把写入收益冒充完整下游收益；
- 删除运行时 `AuthoritativeSourceSelection` / `selection_fingerprint` 固定策略包装，保留
  receipt 的直接 provider、source method、scope、PIT 和 completeness 字段；历史设计/审阅归档中
  的旧文字不属于当前运行时契约；
- `PositiveTradeFallback.request_params_by_pair` 保持 `Mapping` 运行时语义，构造后冻结为只读映射，
  不再把 tuple 伪装成 Mapping。

上述整改之外，原 Issue #66 最小化实现保持不变：

- 大型同构 provider map（至少 128 个成员）按 request 级单个 Parquet 打包，meta 记录成员及
  `None`/空表信息；小型或异构 map 保持原有布局；
- raw boundary 通过 `VerifiedRawEvidence` 完成一次物理闭环，normalization/重放读取复用该句柄；
- receipt 直接使用 `VerifiedResearchProjection`，正向交易 fallback 使用窄 `PositiveTradeFallback`，
  删除不可直接构造的 capture/snapshot 包装；
- authoritative coverage 由一个直接 bridge 生成，移除 `AuthoritativeCoverageBasisAdapter`；
- retained operation 的三套重复校验合并为 `_verify_retained_operation()`；
- canonical owner 与下游消费边界拆开：owner 负责一次完整 canonical closure，下游通过
  `read_canonical_run_manifest()` / `load_canonical_projection()` 消费已绑定的 manifest、版本、
  schema、row-count 和 sealed semantic hash；Snapshot/Feature/R1 不再递归重跑整条 CR-3 链；
- ReadModel、Feature、R1 复用一次 `open_read_only_with_snapshot()` 的 snapshot hand-off；保留
  ReadModel 写入后的 semantic recompute 作为独立的 DuckDB copy-integrity 检查，Feature 保留
  精确公式重放作为自身业务不变量；
- publish 的重量级报告/组件/DQ 文件校验移至 DB 事务前，事务内只重绑验证头、组件注册、manifest
  identity 和小型 DQ proof，并保留过期/漂移 fail-closed；
- `MonthCompletenessEvaluation` 收敛为单一 rule version、输入身份、最终 required/returned
  seal、阻塞计数、结构错误和分类汇总，去掉中间 applicability/suspension subset hashes 与
  评价内重复子版本字段；
- 删除已被规范 Stage-A 结果取代的一次性 Spike 脚本、脚本测试和历史诊断文件，CI 保留质量检查与
  AmazingData SDK 隔离检查，去掉历史扫描/Spike framework ceremony。

本轮只允许完成上述最小化、回归验证和交接文档；不运行 Stage B、78 月回补、Formal/Production、
BSE/index、CR-5/R2、Golden/H1、baseline 或策略工作。原始 provider 数据、凭证、私有 endpoint、
专有 SDK/runtime 仍只在本地受控目录存在。

Issue #66 的整改验收是：精确 rebase 到 `main@ad25f7f`、完成 P0-1 至 P0-4 的边界回归、
代码净删除和可复核 before/after 记录，确认 `2024-01` 既有 Stage-A 结果不被破坏，然后保持
Draft PR 等 scheduler 独立复审。本轮基准为 5,002 个逻辑成员：legacy 5,001 个 Parquet、
packed 1 个 Parquet；物理字节 `7,174,641 -> 84,344`，持久化 `45,911.01 -> 3,609.53 ms`，
closure `44,985.21 -> 53.97 ms`，读取/重建 `14,919.95 -> 3,032.02 ms`。本轮没有真实
provider payload，因而 snapshot/readmodel/publish 的端到端吞吐、峰值内存和真实文件收益仍未
测量，已列为后续授权任务。本地收集 1,839 项，`uv run pytest -q` 退出码为 0（1,835 passed、
4 个既有环境条件 skip）；Ruff、format、mypy、compileall、`uv pip check` 和 diff check 均通过。
实现 exact head `40ca7733f2edb2643ec1cf491fdd617fdce7e583` 的 required CI #617（run
`34935462639`）三个矩阵均 success，受控 GT-H3B #135 skipped；仍由 scheduler 决定是否恢复 Issue #59 的最小
`2024-01` authoritative acquisition/materializer proof；不得由开发者自行进入 Stage B。

## 4. Issue #59 当前执行记录与历史证据

**Issue #59 — `P0: prove bounded 2024-01 authoritative acquisition/materialization before Stage B`**

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

Stage B 的历史脱敏结果已按 Issue #66 从当前树清理，仍可从 Git 历史与 Issue #59 交接记录追溯；
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

此前的 SPIKE 复现脚本已按 Issue #66 删除；原始交换只在本地 ignored raw 目录保留，当前树
不再提供可被误认为生产入口的历史诊断命令。

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

### 4.6 Corrected exact-head Stage A 结果（2026-09-14）

整改提交 `d0710a28c7b6aa7376c4612c0b445d2c0fe7e41a` 的 exact-head CI #599 已通过：Ubuntu
3.14、Windows 3.12、Windows 3.14 全部成功，受控执行保持 skipped。随后在干净工作树以该
提交运行了唯一获准的 `2024-01` Stage A；脱敏报告中的 `code_head` 与该执行提交一致。

本次 22 个精确日 `get_hist_code_list` 请求均为 `[D,D]` 闭区间（另有 1 个正常的整月请求），
因此本次观察可以用于审阅修正后的请求绑定，但业务语义仍未通过：22 个交易日、5,106 个
月度证券、1 个状态 schema mismatch、22 个 `UNRESOLVED` pair、22 个尚未证明为必需的返回
pair，`missing_required_pair_count=0`，总体 `FAIL_CLOSED`。没有生成 authoritative receipt，
没有进入 materializer。

规范脱敏报告为
[`cr7_month_completeness_stage_a_20260914.json`](../provider_verification/cr7_month_completeness_stage_a_20260914.json)，
整改前报告已按 Issue #66 从当前树清理，作为历史诊断不再被当前验收消费；两者不能混作同一
语义版本的证据。

当前返回门是独立 delta review：审阅人需核对 `d0710a2...`、CI #599、规范 Stage A 报告的
`code_head` 和 `[D,D]` 请求结论。除非新的 Stage A 达到 `PASS` 并得到调度确认，不得运行
Stage B、78 月回补、Formal/Production 或其他明确禁止的工作。

### 4.7 状态重复日整改（2026-09-14）

最新 delta review 发现 `_status_rows()` 只按 `(TRADE_DATE, IS_SUSP_SEC)` 元组去重；同一证券同一
交易日若同时返回 `IS_SUSP_SEC=0` 与 `1`，两个元组并不相同，后行会覆盖前行并制造顺序依赖的
状态事实。已按最小范围整改：重复的规范化 `TRADE_DATE`（相同 flag 或冲突 flag）均写入
`STATUS_DUPLICATE_DATE`，并丢弃该证券的全部状态行，使其只能以 `FAIL_CLOSED` 进入结果，不会
把任一重复行提升为 active/suspended 权威事实；新增冲突与相同 flag 两种对抗回归。

本轮实现已提交为 `99cf9c61d60108b35bf200486222ab55926ce389`；focused/full QA 通过，GitHub
Actions CI #601 三平台 required jobs 全部成功，受控执行 #125 为 skipped。随后从该干净提交头
仅重跑 `2024-01` Stage A，规范报告已更新为
[`cr7_month_completeness_stage_a_20260914.json`](../provider_verification/cr7_month_completeness_stage_a_20260914.json)，
`code_head` 与实际执行头一致；上一版报告已按 Issue #66 从当前树清理，历史提交和 Issue 记录
仍可追溯。

本次真实评估仍为 `FAIL_CLOSED`：22 个交易日、5,106 个证券、1 个 `STATUS_SCHEMA_MISMATCH`、
22 个 `UNRESOLVED`、22 个未证明为必需的返回 pair，`missing_required_pair_count=0`；没有
authoritative receipt，也没有进入 materializer。不得运行 Stage B、78 月回补、Formal/Production、
BSE/index、CR-5/R2、Golden/H1、baseline 或策略工作；不能用推断修平当前状态缺口。

### 4.8 单一状态 schema blocker 的最小诊断（2026-09-14）

PR #61 已合并为 `main@559f59169e00d91d52c43cad77f0cf1ea2d56665`，且该提交已核实为当前
工作分支基线。按最新调度，本轮只处理 2024-01 原始状态批次中唯一的
`STATUS_SCHEMA_MISMATCH` 成员，不扩大到其他月份或其他成员。

历史上曾用固定脚本完成单一 schema blocker 诊断；该脚本和报告已按 Issue #66 从当前树清理，
仅通过历史提交/Issue 记录追溯，不作为当前生产入口。

精确头 `d5a7577709f76d2caf2ad5b427aaa8ad8cb2d4a8` 的 GitHub Actions CI #604 三个平台均为
`success`。随后 bounded probe 于 `2026-09-14T11:24:08.134017+00:00` 完成：保留批次中目标成员与
singleton 响应均为零行零列，SDK callback 为 2 次 `kDataEmpty` + `data=None`，raw writer 保留
形态，未发现适配器列丢失。脱敏报告已按 Issue #66 从当前树清理，历史结果仍可由 Git 提交
记录追溯。

脚本锁定的语义边界仍有效：`kDataEmpty` 或空 DataFrame 只能表示“本次没有返回状态数据”，不能被
转换为 `IS_SUSP_SEC=0`，也不能被转换为“无状态变化”。本次没有观察到正向 AmazingData 语义规则，
因此唯一合法结论是 `STOP(BLOCKED)`；当前 Stage A 保持 fail-closed，等待 Owner 决定是否取得正式
状态语义契约、替代接口或其他经授权的数据源。在此之前不重跑 Stage A 语义编码，不启动 Stage B。

### 4.9 同源正向交易事实 fallback 探针（2026-09-14）

PR #62 已由独立调度合并为 `main@548e336353495e5c168ccde3bd85a4e8031fbe63`。当前继续按
Issue #59 的唯一下一任务，只在 Owner 批准的 AmazingData 内寻找能够证明“该证券当日实际发生交易”
的正向事实；不增加其他 Provider，不做多源仲裁。

已确认的 SDK 合同候选：本地安装的 `AmazingData==1.1.9` 公共 `MarketData.query_snapshot` 文档声明
历史 Level-1 快照及 `date -> code -> DataFrame` 返回形态；`tgw==1.0.9.2` 的公开
`MDSnapshotL1` 暴露 `num_trades`、`total_volume_trade`、`total_value_trade`，AmazingData 的 typed
`Snapshot` 暴露 `num_trades`、`volume`、`amount`。当前没有找到独立的供应商字段说明原文，因此报告会把
这组“公开字段名 + typed annotation”明确标为合同候选，不虚构单位或额外语义。

历史上曾实现固定边界的正向交易事实探针；脚本和一次性报告已按 Issue #66 从当前树清理，
当前保留的正向交易语义只存在于生产采集与完整性 evaluator 的窄实现中。

exact committed head `dfb0e4875f17fe7dd3bbbfdf5bc608e642833782` 已完成固定单成员
`2024-01` 探针；脱敏报告已按 Issue #66 从当前树清理，历史提交和 Issue 记录仍可追溯。
保留日历确认的 22 个适用日中，22/22 返回 DataFrame，且 22/22 至少有一个有限且严格大于零的
交易活动候选字段；返回帧合计 96,781 行，22 个分日 raw exchange 只保存在本地 ignored raw/anchor。
探针结论为 `PROVIDER_SEMANTIC_RESOLVED`，但这是“公开 SDK 字段合同候选 + 单成员单月实测”的证据，
不是供应商 capability approval，也不是普适历史完整性证明。由于没有独立供应商字段说明原文，仍需
独立审阅人裁决合同等级；`fallback_rule_encoded=false`，未修改 `month_completeness.py`，未创建
authoritative receipt/materializer。PR #63 的 exact-head CI #607 已在 Ubuntu 3.14、Windows 3.12、
Windows 3.14 全部成功，GT-H3B #129 按策略 skipped。下一道门是 exact head、报告、请求边界和候选
语义的独立审阅。

### 4.10 版本化正交易数 fallback 与 Stage A 结果（2026-09-14）

以 clean `main@738474acb47b0e2e90bead53d12b481a5af4a55f` 为基线，本轮按 Issue #59
最新 checkpoint 把已审阅的同源正向事实收敛为工程规则，并在 exact committed head
`aeaf10acf3d3512ee63cfc03bcfa4f170002a8d3` 完成唯一获准的 `2024-01` Stage A。实现提交的
exact-head CI #610 在 Ubuntu 3.14、Windows 3.12、Windows 3.14 全部 `success`；GT-H3B #131
按策略 `skipped`。

- 月度完整性规则升级为 `amazingdata-month-completeness-rule-v2`；fallback 单独版本为
  `amazingdata-positive-trade-count-fallback-v1`。只有状态响应中明确表现为零行、零列的
  DataFrame 成员才有资格进入 fallback；普通空列表、部分列、非空 malformed schema 均不
  得绕过状态结构门。
- 对每个 exact-day applicability pair 发出单证券、单交易日 `[D,D]` 的
  `MarketData.query_snapshot` 请求，固定 `09:30:00.000`–`15:00:00.000`。只有帧内
  `code`/`trade_time` 与请求完全一致且 `num_trades` 存在有限严格正值，才能分类为
  `POSITIVE_TRADE_COUNT_ACTIVE` 并加入 required-bar 集合。
- 行存在、价格/盘口、`volume`/`amount`、零值、缺失/空快照、缺字段或请求失败不产生
  正向事实；这些情况仍为 unresolved 或结构性 FAIL_CLOSED，绝不推断暂停或不适用。
- acquisition receipt 升级为 v3，capture catalog、snapshot operation、完整请求哈希、
  raw evidence closure、SDK/runtime envelope 和 fallback 版本均进入可重放链；旧评价/旧
  receipt 版本不能按新规则回放。快照只作为语义证据留存，不开放 canonical normalization。
- 已补齐正向、零值、缺失、空表、错误日期/证券、部分 schema、调用方伪造、篡改回放和
  旧版本拒绝的离线回归；普通 snapshot normalization 仍保持 `BLOCKED_PENDING_MAPPER`。

**Stage A 脱敏结果**：22 个交易日、5,106 个月度证券、112,075 个 required 日×证券对全部闭合；
22 个 fallback eligible pair 全部完成精确 `[D,D]` snapshot 查询并以 `num_trades > 0` 归类为
`POSITIVE_TRADE_COUNT_ACTIVE`。评价分类为 active 22、suspension/non-trading 132、
not-applicable 125、unresolved 0、extra 0、structural error 0，报告和月份状态均为 `PASS`。
报告见 [`cr7_month_completeness_stage_a_20260914.json`](../provider_verification/cr7_month_completeness_stage_a_20260914.json)，
人工可读摘要见 [`cr7_month_completeness_stage_a_20260914.md`](../provider_verification/cr7_month_completeness_stage_a_20260914.md)。
旧的未闭合报告已按 Issue #66 从当前树清理，不再作为当前验收输入。

该报告仍是 `SPIKE` 诊断：未创建 authoritative receipt，materializer 未进入，未运行 Stage B 或
78 月物化。下一道门是 scheduler 独立 delta review；在得到后续明确授权前，不运行 Stage B、
78 月物化、Formal/Production 或其他禁止范围。

## 5. 历史记录：Issue #66 明确禁止

Issue #66 **不授权**：

- 2020-01 至 2026-06 的 78 月 broad backfill / materialization；
- 第三次 Formal B1-B7；
- Production `--resume` / `--verdict`；
- BSE mapping 或 index 激活；
- CR-5/R2 feature export；
- Golden/H1/global baseline 修改；
- 策略实现或参数优化；
- 外部 source-trust 证明机制；
- 没有真实多源冲突时建设 multi-source arbitration。

**例外授权**：本轮只允许 Issue #66 的最小化实现、合成测量和回归；不得以历史 Issue #59
的代表月授权文字推导新的在线取数授权。

## 6. 历史记录：Issue #66 验收标准

开发 PR 进入最终审阅前必须同时满足：

- exact base/head SHA 可复核；
- focused tests 通过；
- 全量 repository QA 通过；
- exact-head CI 绿色；
- 生产代码和测试代码相对基线有净删除，且没有新增安全/溯源框架；
- fixture/caller 仍不能绕过现有 AmazingData acquisition 与 raw boundary；
- 大型同构 map 的文件数、持久化与重放校验测量已记录，成员/null/空表可无损读取；
- raw closure 在边界处只执行一次，后续只消费绑定句柄并执行自身语义检查；
- canonical、snapshot、ReadModel、Feature/R1 的消费边界各自只验证所拥有的 seal/不变量，
  不递归重跑下游未拥有的整条 CR-3 链；
- publish 的重量级物理校验在事务前完成，事务内重新绑定小型 seal 并保持原子发布、过期和漂移
  fail-closed；
- completeness evaluation 不持久化中间 applicability/suspension/not-applicable 集合 hashes，
  且只保留一个评价 rule version；
- receipt、coverage bridge、retained replay 不再依赖已删除的 adapter/capture/snapshot ceremony；
- 合法 suspension/applicability gap 不被误判为数据损坏；
- unexplained missing/extra row、malformed shape、scope/request drift、PIT violation 仍 fail closed；
- 当前 `2024-01` Stage A 规范结果保持可追溯；
- 本轮不执行 Stage B 或 78 月回补；
- exact base/head、focused/full QA 和 exact-head CI 可复核。

## 7. 审阅后的调度

### PASS

如果 Issue #66 最小化通过独立审阅：scheduler 才能恢复 Issue #59 的最小
`2024-01` authoritative acquisition/materializer proof；这仍不等于 78 月物化授权。

### REMEDIATE

若问题属于最小化后的 completeness / request / format / PIT 或物化实现，发最小整改任务；
不得用 heuristic 掩盖缺口，也不得自行换数据源。

### STOP / BLOCKED

若 AmazingData 当前接口无法给出解释某类缺 bar 所需的语义事实，记录具体 blocker 并停止相应范围；是否增加其他数据源由 Owner 决定。

## 8. 后续路线（非当前授权）

1. PR #68 bounded materializer/reader 整改的独立审阅；
2. Issue #59 最小 `2024-01` authoritative acquisition/materializer proof；
3. controlled 78-month authoritative historical materialization；
4. 全量 coverage / artifact lineage / replay / corruption E2E；
5. 数据基座 Freeze Gate；
6. CR-5/R2 与研究特征层；
7. `Quantitative-Strategy-Research` 等策略项目正式消费本数据基座。

策略研究不得反向改变数据口径；参数优化不得补偿数据或交易逻辑缺陷。

---

**Last scheduler update**：2026-09-15

**Current task**：Issue #59（PR #68 已合并；最小真实 2024-01 source-input 在 CR-2 shape
normalization 边界阻断）

**Required ancestor**：当前 clean `main@a7671ab34d301cb0aca2f351a31bbc865c100498`。下一步只
处理 [`cr7_authoritative_2024_01_source_input_20260915.md`](../provider_verification/cr7_authoritative_2024_01_source_input_20260915.md)
列出的最小 provider-native shape/identity 适配；适配前不手填 snapshot，不进入 acquisition、
materialization、Stage B 或 78 月回补。
