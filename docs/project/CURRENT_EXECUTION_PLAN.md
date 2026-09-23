## 0.14. 2026-09-23 P0 #79 A0/A1 exact confirmation checkpoint

> 状态：**A0/A1 窄整改与 exact-runner 确认重跑已完成；资源门禁 PASS；物理选型仍待 PM/Owner 冻结；不进入 daily_bar 重构、Issue #76 历史迁移或 provider reacquisition**

PM 对 exact head `1f31989ee656e8957c92811dc6cab74044bb9305` 的 A0/A1 审阅要求已落实。当前绑定证据不把合成基准 PASS 写成架构冻结或 Issue #79 全部 PASS。

已完成：

- A0 将 `market_as_of` 与 `source_vintage_as_of` 分离：普通历史研究不要求 `retrieved_at <= market_as_of`；严格源版本才要求 `retrieved_at <= source_vintage_as_of` 的保留证据；不使用含义混杂的持久化通用 `as_of`。
- A1 runner 在 W4-W8 同时运行 `open_fragments` 与 `closed_compacted`。L1/L2 的 W5/W6 在 `read_parquet` 前按稳定 bucket manifest 选择候选文件；W4 读取完整相关集合；`files_available` 与 `all_files_available` 分开记录；DuckDB 未暴露可靠 row-group touch count 时保持 `null`。
- 同一格式化 exact runner 的第一次完整运行仅因 `uuid_string/L1` 的一次性 short/long 耗时比 `1.4325` 触发 FAIL；无内存、闭月重写或 full fact-copy 失败。按有界确认规则仅重跑一次，以下确认结果为当前唯一绑定结果，不再继续重试。

确认结果：

- 9 组配置（L0/L1/L2 × UUID string/fixed16/INT64），每组 21,600,000 行，`provider_calls=0`；
- `resource_gate_status=PASS`，整体状态仍为 `REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION`；
- 最大 daily-ingest RSS 0.2776 GiB、month-compaction RSS 0.2828 GiB、查询 RSS 0.3200 GiB、short/long 最大比值 1.1580、closed-month rewrite=0、Snapshot/ReadModel full fact copy=0；
- W5 单证券的 L1/L2 candidate byte set 在 open 与 closed artifact 上约比 L0 小 10–12 倍；W6 的 100/500-security 范围跨越全部 16 个 bucket，不宣称 bucket 减少。

绑定产物：

- A0：`docs/architecture/A0_MINUTE_READY_CONTRACTS_20260923.md`；
- A1：`docs/architecture/A1_MINUTE_LAYOUT_BENCHMARK_DECISION_20260923.md`；
- 结果：`docs/architecture/benchmarks/a1_minute_layout_benchmark_20260923.json` 与同名 `.md`；
- runner Git head：`f940ec782a816e6b63d6a13c462af5441e8256c0`；
- runner blob SHA：`f91f891ac2dca782603753685c4106308626d15f`；
- runner source SHA-256：`ad535f18c5de11b154a7291ad2cb4ac0c3384f15acaf2d35c6cfe644384f86d8`；
- benchmark JSON SHA-256：`CD094B2C6509B34405A317BC0CF0D725603BDAB0D323827458CEBFF3DDBD783A`；
- benchmark Markdown SHA-256：`81B8EB85CE5B151B328929DE4BB474BDD402EFBFE25D58E695912057B6D30E6A`。

当前仍是临时选型建议：L1 + fixed16 UUID physical key；L0 + fixed16 是较简单备选；现有证据不足以冻结 INT64 mapping，也不授权 32 bucket、provider、daily_bar vertical refactor 或 Issue #76 迁移。下一步由 PM/Owner 审阅并冻结布局/键表示；冻结后 scheduler 才能授权一个 bounded `daily_bar` Canonical → logical Snapshot → DuckDB facade vertical slice。

# Current Execution Plan

> 本文件是项目**当前执行控制面**。开发人员用它确认：当前主线做到哪里、唯一 P0 是什么、允许做什么、做到什么算完成、完成后由谁决定下一步。
>
> 历史决策继续保留在 `docs/project/DEVELOPMENT_MANAGEMENT.md`、`docs/DEVLOG.md`、Issues 和 PR reviews 中；日常接任务优先读取本文件与当前 Issue。

## 0.11. 2026-09-22 M1 authorized gate attempt — retained artifact provenance blocked (未重新测量)

> 状态：**M1 仍 STOP(BLOCKED) 且未完成有效 RSS 测量；不进入 M2/M3**

PM 在审阅 exact head `1e656022a3702ed5ae4f51a42e1959257b8badce` 时确认 M1.1 代码整改通过，并授权只执行一次真实的 78 个月 retained ReadModel 校验；要求 15 GiB 外部硬停止、峰值 <16 GiB 才能接受，若超限不得重试。

本次只读门禁已按授权执行一次，但在进入内存密集阶段前被持久化 provenance 封印拒绝：

- `consume_snapshot_seal` 发现保留 snapshot 的 `snapshot_builder_code_fingerprint` 与当前代码不一致，按现有 fail-closed 合同停止；没有绕过版本封印，也没有改写快照/ReadModel。
- 进程约 4.1 秒退出，工作集约 0.005 GiB；该数值不是有效 RSS 门禁结果，因为尚未进入 ReadModel 语义校验。
- execution state 未变化，临时 `.readmodel-verify` 目录已清理，provider calls 为 0；没有启动 provider capture、全链重跑、M2、M3 或物化发布。

下一步不是降低封印要求，而是由 PM/Owner 决定：从已有 sealed canonical evidence 生成与当前代码兼容的 retained snapshot/ReadModel，或提供一份已兼容的保留产物。该重建属于独立操作，不在本次 M1-only 授权内；在兼容产物就绪前，不得再次测量、不得启动 M2/M3，也不得把本次 0.005 GiB 写成 M1 PASS。


## 0.10. 2026-09-22 M1.1 sealed snapshot hand-off (未重新测量)

> 状态：**M1.1 代码整改已提交；M1 真实 78 个月 RSS 门禁仍 STOP(BLOCKED)；不进入 M2/M3**

PM 审阅指出，上一轮虽已把 ReadModel 逻辑 hash 改为有界算法，但 `ReadModel rebuild/open` 仍递归调用 `verify_snapshot`，会再次读取并重投影 canonical selected 数据。已按该要求补齐最小下游消费边界：

- 新增 `consume_snapshot_seal`：校验 snapshot ledger/manifest 身份、canonical manifest seal 交叉绑定、快照 artifact 的流式 content hash、Parquet schema、metadata row count、semantic seal 格式及 artifact/snapshot/总行数聚合 seal；不调用 `load_canonical_projection`、`open_canonical_projection_source` 或 `project_canonical_snapshot`。
- ReadModel rebuild/open 改为消费该 sealed hand-off；完整 `verify_snapshot` 深审计路径保留给显式审计和 Snapshot 自身回归，不被删除或放宽。
- 新增回归：sealed hand-off 禁止整表 `read_parquet`/canonical projection；snapshot artifact 篡改和 canonical manifest/ledger 漂移仍 fail-closed；ReadModel rebuild/open 均走 sealed hand-off。
- 本地离线 QA：Snapshot/ReadModel 集成测试、Ruff、mypy 通过；未访问 provider、未使用正式账号、未启动新的 78 个月真实 RSS 测量。
- CI #716 的 Ubuntu 3.14、Windows 3.14、Windows 3.12 required jobs 全部 success；GT-H3B 按范围 skipped。

这仍是代码级整改，不能证明峰值 RSS 已低于 PM 的 <16 GiB 门禁。下一步仍须 PM/Owner 明确批准一次新的、带 15 GiB RSS 硬上限的 M1 测量；只有满足预算才允许 M2/M3，否则立即 STOP 并记录峰值。

## 0.9. 2026-09-22 M1 高内存边界整改（未重新测量）

> 状态：**代码整改已提交；M1 真实 78 个月 RSS 门禁仍 STOP(BLOCKED)；不进入 M2/M3**

针对 0.8 暴露的剩余分配边界，已完成不触碰真实历史窗口的最小代码整改：

- canonical selected.parquet 新增批量、哈希已验证的行源；seal-only Snapshot/ReadModel 路径不再把 selected.parquet 全量 read_bytes/to_dicts。
- seal-only snapshot 校验改为 Arrow 批量读取物理 Parquet，并对 canonical projection 使用受控 JSONL 外部排序块；保留原有 hash、schema、行数、PIT、key、逐行语义和 duplicate-key fail-closed 约束。
- 保留 retain_domain_rows=True 的旧内存交接语义，避免改变需要完整行 hand-off 的调用方；新增回归确认 seal-only 不调用整表 read_parquet。
- 代码提交：canonical 批量源 1339f3e83304324d0815cbe0856fbf5a2213b394；snapshot 有界校验 f3c4de311cf3da5bf7968dc9e05306b0ec27630f；回归 fc03bd1a1b32bb4bebe2c0f196a4b40cbccbfe92；最终 EOF 格式修复分别为 eac3b7eafdcfd5227312c543b1ed9f84f6c241d8、c612ab66c49005a00dd8e3f5475c6ea7f8d414a0、44c346b40ff7551cbfac7974063f139d9ff94fa3。CI #711 的 Ubuntu 3.14、Windows 3.14、Windows 3.12 required jobs 全部 success。
- 离线验证：Ruff、mypy、Snapshot/ReadModel 集成测试及全量 pytest 均通过；未访问 provider、未使用正式账号、未启动 78 个月真实测量。

这只能证明代码回归通过，不能证明实际 RSS 已低于 16 GiB。下一步仍须由 PM/Owner 决定是否在同一安全环境执行一次新的、带 15 GiB RSS 硬上限的 M1 测量；测量满足预算后才允许 M2/M3，否则继续 STOP 并记录新的峰值边界。

## 0.8. 2026-09-22 M1 RSS 门禁失败（最新）

> 状态：**STOP(BLOCKED)；M1 未通过；按内存安全要求不进入 M2/M3**

按 0.7 计划，对既有 78 个月 snapshot/readmodel 只读执行了一次 M1 独立测量，外层设置 15 GiB RSS 硬上限。外部进程观测到校验子进程约 22.268 GiB working set，已经超过 PM 的 <16 GiB 初始预算；进程随即停止，没有第二次或 unchanged-code 重试。

测量后确认 execution_state.json 未变化，临时 .readmodel-verify 目录已清理；没有有意写入、删除或覆盖 ledger、raw、normalized、snapshot/readmodel 或 materialization 产物。M1 的小型 fixture、精确 hash 和 seal-only 回归仍通过，但不足以证明真实 78 个月路径有界。

因此本轮不启动 M2 projection/materialization，也不启动 M3 materialization-only/resume。后续必须先隔离并消除剩余高内存分配边界，再由 PM/Owner 决定是否重新测量；完整脱敏事实见 [M1 RSS 阻断补充](ISSUE76_MATERIALIZATION_MEMORY_BLOCKER_20260922.md)。

## 0.7. 2026-09-22 M1 有界 Snapshot/ReadModel 校验实现检查点

> 状态：**M1 代码已提交；小型回归与静态 QA 通过；78 个月 RSS 门禁尚未运行；M2/M3 未开始**

已按 PM 的 M1 要求提交以下最小整改：

- Snapshot verifier 新增 seal-only 模式，ReadModel rebuild/open 使用 `retain_domain_rows=False`，仍执行逐行 projection/PIT/key/seal 校验，但不再把所有物理行留在 `VerifiedSnapshot.domain_rows`；build row count 改从已验证 ledger seal 读取。
- ReadModel 逻辑语义 hash 保持既有 `_rows_semantic_hash` 字节契约，改为 `fetchmany` 分批、临时 sorted chunks、受控 fan-in merge 和增量 JSON-array hash；禁止大表 `fetchall`。校验连接设置显式 4GB DuckDB memory limit 和临时目录，临时 chunk 在成功/失败路径清理。
- 新增回归覆盖：多批次 exact hash（时区时间、空值、浮点、非 ASCII）、禁止 `fetchall`、seal-only hand-off 和原有 Snapshot 行保留模式。
- 提交：Snapshot `f4c876701bd3a12e4c0241f65ca97e8785eae7b7`；ReadModel `e2b3c4033368d9a79969b4f7ae17fb8e754dc1f1`；测试 `ce2fd134cc5dd5024825b92f89a3b3f5f051ae6b`、`fe7870f11ddc8fa27f2fb4d7141ccece09699a9e`。
- 本地目标回归、Snapshot/ReadModel 集成测试、Ruff、mypy 和 diff 检查均通过；尚未声称实际 78 个月峰值低于 16GB，也未启动 M2/M3 或最终验收。

下一步严格为：先对既有 78 个月 ReadModel 做一次带硬 RSS 上限的 M1 独立测量；若仍超过预算，立即 STOP 并补充阻断报告，不继续重复尝试。只有测量满足预算，才进入 M2。

## 0.6. 2026-09-22 78 月物化内存阻断（最新）

> 状态：**STOP(BLOCKED)；无最终 PASS；按内存安全要求暂停继续重跑**

- 78 个月 capture/replay 与规范化链路已完成，且已有一份本地 78 分区物化目录；但最新运行没有完成 changed-content conflict gate、最终 reader/幂等/冲突闭环，因此不能把现有目录写成最终发布或验收 PASS。
- 旧版 snapshot verifier 在本机约 46.7 GB 内存处出现高峰；完成流式逐行比对等优化后，`ResearchPanelBuilder.prepare_verified_projection` 仍约 46.5 GB；进一步缩窄到既有 readmodel/物化输入的尝试仍约 38.5 GB，均在进入最终物化验收前安全停止。
- 已完成的安全/代码整改仍有效：Windows 原生 SDK stdout/stderr 句柄捕获已补齐，CI #690 required jobs 全部成功；snapshot verifier 内存优化提交 `1d55bea8120d336e40840071084b4c11de409dbf`，CI #694 全部成功。
- 当前主要问题不是凭据或 provider 认证：ReadModel 逻辑校验仍以 `fetchall`、全量 dict/list 和全量语义排序为主；verified projection 同时保留 source rows 与 projected rows；仓库没有受控的 materialization-only/resume 入口，导致恢复过程再次触发高峰。
- 下一次允许推进前，必须先完成并独立验证：有界内存的精确 ReadModel 语义校验、有界 projection/materialization、可审计的 materialization-only/resume 命令、内存回归/峰值门禁，以及明确区分既有本地目录、幂等重放、冲突阻断和最终 PASS 的状态契约。
- 本轮已按要求停止本地重试；凭据、会话 token、raw payload 和本地执行状态未写入 GitHub。完整脱敏交接见 [Issue #76 物化内存阻断报告](ISSUE76_MATERIALIZATION_MEMORY_BLOCKER_20260922.md)。

## 0.5. 2026-09-21 78 月重跑物化修复与 SDK 日志边界

> 状态：**78/78 capture 已通过；首次物化因 runner 常量错误 STOP(BLOCKED)；修复后的 retained replay/物化重跑进行中；无 publication**

- 首次完整重跑的 78 个月份均为 `PASS`，但 `MATERIALIZATION` 的变更内容冲突回归使用了
  `"ENABLED"`，与契约值 `RESEARCH_ENABLED` 不一致，触发 `StopIteration`。已将本机 ignored
  runner 改为使用 `ResearchEligibility.ENABLED.value`；不能把月度 capture PASS 写成最终交付 PASS。
- 重跑只消费已有本地 retained raw/normalized 证据，不重新请求 78 个月；必须等最终
  `MATERIALIZATION -> COMPLETE / PASS`、reader、幂等 replay 和 changed-content conflict 全部通过后，
  才能写最终 summary。
- 终端曾观察到 SDK 的 `logon json` 会话 token。共享 fd 捕获不足以覆盖 Windows 原生
  `GetStdHandle`/`WriteFile` 路径；已在 `stdout_capture.py` 增加 Windows 标准句柄重定向，补充
  原生句柄回归测试。focused tests、Ruff、mypy 本地通过；CI 待回报。凭据、token、raw payload 和
  本地状态仍不得进入 GitHub；GitHub Actions CI #690 的 Ubuntu 3.14、Windows 3.12、Windows 3.14 required jobs 已全部 success。
- 已暴露会话 token 不作为证据继续使用；本轮结束后必须登出/重新登录使其失效。

## 0.4. 2026-09-21 provider 查询失败有界重试整改

> 状态：**代码已补齐并通过离线 QA；在线 2025-09 重跑待执行，仍 STOP(BLOCKED)**

针对 2025-09 的 InfoData.get_stock_basic 通用“查询失败”，已完成有界、延迟、端点准入的重试实现，详见 [重试整改报告](../provider_verification/cr7_issue76_provider_retry_20260920.md)：

- 通用 QUERY_FAIL_UNCLASSIFIED 默认仍不可重试；只有历史运行实际触发的 InfoData.get_stock_basic 端点在本次 Issue 的 runner 配置中显式放行。
- 最多 2 次重试，等待约 30 秒、60 秒，带 ±25% jitter，单次等待封顶 120 秒；不做立即重试或无限重试。
- 认证、权限、schema、普通未知 SDK 错误不因本整改改变分类或获得重试资格；重试耗尽仍 STOP(BLOCKED)。
- provider envelope 的 attempt_count 和预算耗尽上下文保留重试事实，便于在线结果审阅。
- 本地 ignored runner 已同步该配置，但 data/spike 不属于 Git 源码；仓库提交的是共享 retry policy、回归测试和运行要求，不包含凭据、原始 payload 或本地状态。
- 离线验证：provider focused 64 passed；tests/unit 505 passed、1 skipped；Ruff 与 mypy 通过。重试耗尽仍保留 ProviderSdkInternalError，并附带尝试次数；尚未声称 2025-09 在线恢复或 78/78 完成。
- exact-head CI #684 的 Windows 3.14、Windows 3.12、Ubuntu 3.14 三个 required jobs 已全部 success；GT-H3B #194 按策略 skipped。

下一步：在同一安全 PowerShell 进程执行 --resume --retry-blocked；若 3 次仍为同一通用失败，保持 STOP(BLOCKED)，按原计划做受控分块/新增证券窄探针，不扩大重试次数或端点 allowlist。receipt、coverage、materialization、publication 及 B1-B7/Production 仍未授权。

## 0.3. 2026-09-20 当前调度覆盖 — Issue #76 2025-09 provider 查询阻断

> 状态：**STOP(BLOCKED) at 2025-09 / 68 of 78 capture PASS / no publication**

最新正式运行结果已写入 [Issue #76 执行记录](../provider_verification/cr7_issue76_history_build_20260916.md) 及对应 JSON：

- broker-enabled 本地运行环境与最新代码已正常加载；2025-02 retained replay、2025-03 至 2025-08 均已通过，累计 68/78 个月。
- 2025-09 的 hist_code_list 返回 5,161 个证券；随后 InfoData.get_stock_basic 返回未归因的通用“查询失败”，runner 按 fail-closed 写入 ProviderSdkInternalError 并停止。该错误当前不证明是账号、权限、参数上限或服务瞬时故障。
- 不得跳过 2025-09、删减新增证券、伪造 stock_basic 成功或提前进入 receipt/coverage/materialization/publication。
- 下一步是重新登录后对同一输入做一次明确重试；若重复，再做受控分块/新增证券窄探针，区分 provider 瞬时故障与请求/证券触发条件。只有 78/78 capture PASS 后才能进入下游 gates。

## 0.2. 2026-09-18 当前调度覆盖 — Issue #76 2023-02 capture 诊断

> 状态：**STOP(BLOCKED) at 2023-02 / raw capture obtained / offline replay fixed the cross-month orchestration defect / no publication**

用户已在本机同一安全进程完成 TGW 变量注入，`2023-02` 实际发生 `44` 次 provider calls。原始请求均为 `OK`：calendar `27cd797f-43d7-460d-ac8f-1390178427d0`、hist code list `f0db8a97-700a-49db-b464-996719a3c83f`、stock basic `e0979f16-5c56-4fc9-bd66-1b934e30e771`、history status `5f13940b-d241-4320-91d7-aa30a9d3bd01`、daily bar `f6192d4d-74c3-4896-a0a1-cfd3b8ff623f`。凭证及网络身份仍未写入文件或 GitHub。

- 原始 `2023-02` completeness：`4,926` securities、`20` sessions、required/returned `98,194/98,194`；missing/extra/structural `0/0/0`，但 `UNRESOLVED=1`。分类：`NOT_APPLICABLE_SESSION=153`、`POSITIVE_TRADE_COUNT_ACTIVE=19`、`SUSPENSION_NON_TRADING=172`、`UNRESOLVED=1`。
- 唯一未决 pair 为 `300114.SZ / 2023-02-01`。status 返回 `0×0` 空表，daily bar 恰缺该日；这不是账号失败，也不能用 `num_trades=0` 推断停牌。
- 根因是 runner 编排只在 `month == 2023-01` 传递已批准的 `[2023-01-12, 2023-02-02)` 事件，漏掉跨月的 `2023-02-01`。本地未跟踪 runner 已修为按事件半开区间与月份相交传递；使用同一批已落盘 raw 的 retained replay 已验证 `2023-02 PASS`、required/returned `98,194/98,194`、`UNRESOLVED=0`、`SUSPENSION_NON_TRADING=173`。这不是生产语义放宽，也没有重新请求 provider。
- 当前执行状态文件仍保留原始 `STOP(BLOCKED)`，因为尚未用修正后的 runner 正式恢复整条链。下一次正式恢复会先 replay `2023-02`，然后从 `2023-03` 发起在线请求；receipt、coverage、materialization、ordinary-reader、幂等、冲突和 78/78 验收都仍未完成。

详细脱敏记录见 [`cr7_issue76_history_build_20260916.md`](../provider_verification/cr7_issue76_history_build_20260916.md) 与对应 JSON。保持 PR #77 Draft；不得把本次 `2023-02` 离线 replay 写成 78 个月完成。

## 0.1. 2026-09-17 历史调度检查点 — Issue #76 78 个月历史构建

> 状态：**STOP(BLOCKED) at 2023-02 / 37 of 78 capture PASS / no publication**

Issue #76 授权从 `main@ad2ad528d3ffec1269772084f0860c8224e632d2` 构建 2020-01 至 2026-06 的 78 个月历史。PR #77 的 PM review 已批准最小 `DELISTDATE` 适用性修复：复用已验证 normalized security-master 的 `stock_basic.DELISTDATE`，仅当 `session >= DELISTDATE` 时判为 `NOT_APPLICABLE_SESSION`；不 carry-forward 停牌、不换源、不跳过 pair。现有 typed AmazingData → raw anchor → completeness → Canonical → Snapshot → ReadModel → verified projection → bounded materializer 路径保持不变。

- 生产代码已升级 month-completeness/applicability 到 v5；`DELISTDATE` 进入 identity view，并仅保留实际用于排除 pair 的事实；同时仅保留 Owner 批准的 `300114.SZ` 官方停牌事件 `[2023-01-12, 2023-02-02)`。该事件只闭合其 exact-session 未决 pair，不改变零成交含义，不做 carry-forward，不引入通用事件框架或第二 provider。`LISTDATE`、PIT、raw closure 和 finalized capture 的既有 fail-closed 约束保持不变。
- `2020-01`：hash-anchored retained replay capture PASS，required/returned `59,930/59,930`，missing/extra/unresolved/structural `0/0/0/0`。
- `2020-02`：使用已保留同范围 raw exchanges retained replay capture PASS，required/returned `75,463/75,463`，missing/extra/unresolved/structural `0/0/0/0`；`NOT_APPLICABLE_SESSION=238`，实际使用的 post-delisting 事实为 `600240.SH -> 2020-02-05`。
- `2020-03` 至 `2022-12`：此前共 34 个月 fresh-provider capture PASS；本次使用保留 raw 做 retained replay，没有把 replay 误报为新的在线采集。与前两个月合计 `36/78`。
- `2023-01`：retained replay 已通过。`4911` 个证券、`16` 个交易日，required/returned `78,403/78,403`，missing/extra/structural `0/0/0`，`UNRESOLVED=0`；分类为 `NOT_APPLICABLE_SESSION=67`、`POSITIVE_TRADE_COUNT_ACTIVE=7`、`SUSPENSION_NON_TRADING=106`。Owner 批准的官方事件实际闭合 9 个 `300114.SZ` pair，来源为 [CNINFO 2023-001](https://static.cninfo.com.cn/finalpage/2023-01-12/1215580484.PDF)、[CNINFO 2023-007](https://static.cninfo.com.cn/finalpage/2023-02-02/1215749576.PDF) 和 [深交所停复牌表](https://docs.static.szse.cn/www/certificate/secondb/GEMmsb/W020230202562529948780.html)。
- `2023-02`：历史检查点；当时 runner 在 provider 请求前因当前执行进程缺少安全环境变量停止。该检查点已被上方 0.2 的实际 provider capture 与离线 replay 诊断取代。
- 本次新增静态事件、半开区间边界和 retained replay 回归已通过；本地 focused pytest 为 `72 passed`、full offline pytest 为 `1879 passed, 3 skipped`，Ruff、format、mypy、compile、依赖和敏感值扫描均通过。exact-head CI run `656`（commit `ab133200ce7ff7247c356fd2cc603bbb34647858`）的 Ubuntu 3.14、Windows 3.14、Windows 3.12 三个必需作业均 `success`，GT-H3B run `166` 按范围 `skipped`。这只证明仓库门禁通过；由于 capture 阶段尚未闭合 78 个月，当前尚未产生完整 receipt、authoritative coverage、materialization、ordinary-reader、idempotency 或 changed-content conflict 结论。

详细脱敏执行记录见 [`cr7_issue76_history_build_20260916.md`](../provider_verification/cr7_issue76_history_build_20260916.md) 及对应 JSON。上述内容是历史检查点；当前下一步以 0.2 为准：使用修正 runner 先 replay `2023-02`，再从 `2023-03` 恢复在线请求。不得把认证信息写入仓库，也不应扩大为零成交启发式。

### 本地安全配置说明（不进入 Git）

环境变量只对设置它的进程及其子进程可见。已经启动的 Codex 进程不会因为另一个独立 PowerShell 窗口后来设置了变量而自动获得它们；因此应在**启动 runner 的同一个 PowerShell 窗口**中注入变量，或由同一进程的安全凭据管理器注入。下面的示例只展示变量名和流程，不包含任何真实账号、地址或口令：

```powershell
$env:TGW_USERNAME = Read-Host 'TGW username'
$secure = Read-Host 'TGW password' -AsSecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $env:TGW_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    $secure.Dispose()
}
$env:TGW_SERVER_VIP = Read-Host 'approved TGW server VIP'
$env:TGW_SERVER_PORT = Read-Host 'TGW server port'

try {
    Set-Location '<local-repository-root>'
    uv run --locked --offline python data/spike/issue76_history_build_20260916/runner.py --resume --retry-blocked
}
finally {
    Remove-Item Env:TGW_USERNAME, Env:TGW_PASSWORD, Env:TGW_SERVER_VIP, Env:TGW_SERVER_PORT -ErrorAction SilentlyContinue
}
```

不要在命令行参数、脚本文件、日志、截图或 GitHub 中填写/回显口令；不要把变量设置在与 runner 无父子关系的另一个终端后，期待当前 Codex 进程同步获得。执行结束后应确认变量已清除，再把 runner 的脱敏结果更新到本 PR。

Issue #76 完成前保持范围排除：Formal B1-B7/Production、BSE/index、CR-5/R2、Golden/H1/global baseline、strategy/portfolio、speculative reconciliation。

## 0. 2026-09-16 当前调度覆盖 — Issue #73 remediation

当前基线为 PR #74 合并后的 `main@22c42a72e222d9b6f6519095fb641a4adb190e12`。本轮严格限定为
Issue #73 授权的 `2020-01` Development 与 `2026-01` Holdout；两代表月的技术验收已 PASS，
现提交 Draft PR #75 供 PM 审阅。此结论不扩大到其他月份或后续阶段。

- **2020-01：PASS。** 五个缺口均由已有、已验证的 AmazingData `stock_basic.LISTDATE` 证明为
  上市前配对，并分类为 `NOT_APPLICABLE_SESSION`（不是停牌）。缺失/格式错误 LISTDATE 不会
  自动解除未决。required/returned `59,930/59,930`，unresolved `0`；receipt、retained replay、
  coverage、Development 单分区 materialization、ordinary reader（59,930 行）、幂等重放和
  changed-content conflict 全部通过。
- **2026-01：PASS。** 两阶段 capture/finalize 与 projection 分区/cardinality mismatch 防护通过；
  required/returned `103,454/103,454`，unresolved `0`；receipt、retained replay、coverage、Holdout
  单分区 materialization、ordinary reader（103,454 行）、幂等重放和 changed-content conflict
  全部通过。`retrieved_at_utc <= pit_as_of` 保持不变。
- 两月变更后复放使用既有 hash-anchored provider exchanges，未发起新的 SDK/provider/network 请求；
  两月分别以当前代码重算 completeness、重新签发 receipt，并走完 coverage/materialization/reader
  断言。不能将此离线证据误述为新的供应商在线重取。

脱敏时间、五项 LISTDATE、classification、材料化 ID 与验证明细见
[remediation 报告](../provider_verification/cr7_issue73_stage_b_remediation_20260916.md)及对应
[JSON](../provider_verification/cr7_issue73_stage_b_remediation_20260916.json)。本地 QA 已通过：
聚焦测试 `61 passed`、全量离线 pytest `1868 passed, 3 skipped`、Ruff/格式检查通过、mypy
108 个源文件无问题；exact-head CI 状态以 GitHub 检查为准，不缓存动态值。

下一步由 PM 审阅双月证据、LISTDATE 适用规则及 finalize scope/cardinality guard，再决定是否接受
本轮。不得据此启动 78 月回补、其他月份、Formal B1-B7/Production、BSE/index、CR-5/R2、
Golden/H1、baseline 或策略工作；这些仍需独立授权。

## 0H. 2026-09-16 PR #74 合并前的 Stage B blocker baseline（历史记录）

以下内容记录 PR #74 合并前的历史阻断快照，仅作历史留存；当前状态以本节 0 的 remediation
更新及 Issue #73 最新指示为准。

当时执行基线为 `main@f8a750b96f6d6fca4bc1996ba592a4d5dcfa4b48`。Issue #73 仅授权
Stage B 的 `2020-01` Development 与 `2026-01` Holdout 两个代表月；本轮未执行其他月份、
78 月回补或 Production/B1-B7 工作。

两个隔离月均已完成源输入、Canonical → Snapshot → ReadModel → verified projection 与权威
提供方采集，但都在物化前按现有规则 `STOP(BLOCKED)`：2020-01 completeness 为
59,930/59,930 返回但有 5 个 unresolved security-session pairs；2026-01 completeness
103,454/103,454 通过，但最新提供方响应晚于 verified projection 的 PIT 时间 381.534241 秒，
现有 receipt validator 因 `retrieved_at_utc > pit_as_of` 拒绝签发。两月均没有 receipt、coverage
basis 或 materialization PASS；没有删减 universe、放宽 completeness/PIT 校验或复用旧 Stage B raw。

详细脱敏计数、ID、hash、阻断证据及 PM/Owner 最小决策要求见
[`cr7_issue73_stage_b_execution_20260916.md`](../provider_verification/cr7_issue73_stage_b_execution_20260916.md)
和对应 JSON。全量离线测试在本次仅文档变更前、同一代码 head 上通过 `1857 passed, 3 skipped`；
当前 exact-head CI 状态以 Draft PR checks 为准，本文件不缓存动态 CI 状态。独立 PM 审阅仍待完成；
审阅前不启动 78 月回补或任何 Issue #73 明确禁止的工作。

## 0A. Issue #59 closure evidence (historical snapshot, 2026-09-16)

PR #71 已通过独立 PM 审阅并合并：exact head 为
`8325ec4a85117213f514764444058e4664d5af16`，merge commit 为
`c360354bee8698c8a2db61a607d0bb3dcefd0ddb`。本轮从该 clean `main` 建立
`investigate/issue59-identity-event-20260916`，没有在历史分支上继续堆叠改动。

Issue #59 的最小 current-code-first identity fix 已在本地实现，范围严格限于 Owner
批准的静态事件 `300114.SZ -> 302132.SZ`：旧码有效区间为
`[2010-08-27, 2025-02-17)`，新码从 `2025-02-17` 起开放；两者共用 ADR-002
初始种子派生的一个稳定 `security_id`。现有 bridge 版本为 `identity-bridge-v2`；
普通 current lookup 返回 `302132.SZ`，显式 PIT 查询在 2024 年仍解析
`300114.SZ`。R1 保留既有裸码 `symbol` 列契约，但普通展示取 open/current 记录，
不会把 2024 历史旧码泄漏为当前业务代码；PIT resolver 仍保留历史语义。

本地离线行为测试已经通过，包括 identity bridge、Canonical 身份策略、R1 current/PIT
展示和完整 `test_canonical.py`。随后在复制的 retained 2024-01 raw 上建立全新本地
DuckDB ledger（保留原有 raw anchor，不改原始目录），用当前 mapper 重建四个 CR-2
SUCCESS 运行并完成：

`Canonical -> Snapshot -> ReadModel -> ResearchPanelBuilder.prepare_verified_projection()`

实际结果为：22 个交易日、5,106 个历史证券、112,075 条日×证券行全部保留；Canonical
`SUCCESS / selected=112075 / findings=0`，Snapshot、ReadModel、verified projection
均为 `SUCCESS`，projection 行数为 112,075，current identity lookup 为 `302132.SZ`。
此前旧 ledger 的 `mapper_code_hash` 属于旧代码版本，按现行 fail-closed 规则不能直接重用；
这不是放宽校验或删除历史，而是对同一已锚定 raw 在隔离 ledger 中做可复现重放。

随后已按 Issue #59 授权范围，用进程环境变量注入的正式账号完成一次真实但严格有界的
2024-01 `AmazingDataHistoryAcquisition.acquire_month()`。代码 use mode 明确为 `SPIKE`；
这表示本次运行允许调用尚未完成 Production 治理批准的候选能力，不等于 Formal B1-B7 或
Production 已批准，也没有改变能力注册表状态。凭证没有写入文件或日志。

真实 authoritative closure 结果：5,106 个证券、22 个交易日、112,075 条返回行；required
pair 与 returned pair 均为 112,075，missing/extra/unresolved 均为 0，structural errors 为
空，completeness `PASS`。分类为 `SUSPENSION_NON_TRADING=132`、
`NOT_APPLICABLE_SESSION=125`、`POSITIVE_TRADE_COUNT_ACTIVE=22`。receipt 已签发并对保留
capture 二次 `verify_retained_capture()` 通过；详细脱敏 ID、哈希和分类见
[`cr7_issue59_authoritative_2024_01_closure_20260916.md`](../provider_verification/cr7_issue59_authoritative_2024_01_closure_20260916.md)
及对应 JSON。

receipt 已桥接为 authoritative coverage basis；单分区
`validation_a:2024-01` bounded materialization 成功，ordinary reader 读回 112,075 行，
相同输入的第二次物化返回 `idempotent_replay=true`，修改一行内容的重放被
`MaterializationConflictError` 阻断。原始捕获、DuckDB、物化 Parquet 和 SDK/runtime 仍只
在本地忽略目录，未提交 Git；此闭环等待独立 PM 审阅，不能把本地 artifact 当成已合并主线。

在 Issue #59 closeout 时，Stage B（`2020-01` / `2026-01`）、78 月回补、Formal/Production、
BSE/index、CR-5/R2、Golden/H1、baseline 和策略工作尚未授权。随后 Issue #73 仅为上述两个
代表月授予了受限 Stage B 授权；当前结果与后续决策以本文件第 0 节和 Issue #73 为准。

## 0B. 2026-09-15 历史调度快照

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

**Last scheduler update**：2026-09-23

**Current task**：Issue #79（A0/A1 窄整改已完成，等待 PM/Owner 冻结物理布局与键表示；不进入 daily_bar vertical slice、Issue #76 历史迁移或 provider reacquisition）。

**Required decision**：审阅 corrected A0/A1 证据并决定是否冻结 L1 + fixed16 UUID（或其他有充分证据的方案）；只有冻结后，scheduler 才能授权一个 bounded `daily_bar` Canonical → logical Snapshot → DuckDB facade vertical slice。Issue #76 仍保持历史证据不变、provider_calls=0 的迁移禁令。：2026-09-16

**Current task**：Issue #76（78 个月权威历史构建已通过 2020-02 `DELISTDATE` 适用性修复，
当前在 2020-03 本地认证环境边界停止）

**Required ancestor**：Issue #76 基线为 `main@ad2ad528d3ffec1269772084f0860c8224e632d2`；
在本机安全配置认证环境变量后，从已保留证据恢复并继续 2020-03，不得把环境阻断误写成
provider 数据结论，也不得跳过月份或将当前进度写成 78/78。


## 2026-09-23 authoritative active gate — Issue #76 PIT decision

**This section supersedes the preceding end-of-file “Current task” / “Required decision” blocks** that described #79 as awaiting a physical-layout freeze or Issue #76 as waiting for 2020-03 credentials. Those are historical checkpoints and are not the current operating instructions.

- Issue #79 passed; Issue #80 passed and closed; PR #81 was integrated into this Issue #76 branch at 50e5e2dd8c8a1722cd70fbf6a8b2233494a647e7. CI #744 / run 35852805033 passed the three required jobs. The latest audit-doc commit cb55629595cb25431907b05c14d69ae812fe254d also passed exact-head CI #745 / run 35857453802 on Ubuntu 3.14, Windows 3.12, and Windows 3.14. GT-H3B controlled execution was skipped by scope.
- Two existing retained roots are reconciled read-only: 342,735 paths/files and 6,591,572,317 bytes in each; no relative-path, case-only, or file-size differences; the targeted state, summary, runner, ledger, and active source-manifest hashes match. This is an inventory/control-metadata reconciliation, not a claim that every retained payload was fully byte-hashed.
- Actual retained state/summary, manifests, and receipts establish 78/78 capture/replay PASS for 2020-01 through 2026-06 (7,442,987 daily-bar rows). The old 68/78 PR description is stale for capture/replay. Six representative offline months passed selected receipt-closure and PIT/identity/lifecycle checks with provider_calls=0; see docs/project/ISSUE76_MATERIALIZATION_MEMORY_BLOCKER_20260922.md.
- The representative audit's PIT result is **not PASS**: retained historical bars are a later backfill, have no row-level market_available_at, and legacy available_at means received_at/ingestion provenance. Do not derive historical availability from retrieval time or infer it from close prices.
- **Immediate blocker before migration:** Owner/PM must record the C1 daily-bar rule: (a) a versioned trade-date/session-close event-eligibility convention explicitly distinguished from actual provider publication time; or (b) date-level eligibility with no row-level market_available_at assertion; or (c) a requirement for exact historical as-known values plus an acceptable vintage source. The retained archive alone cannot prove exact values physically known in 2020.
- **Separate downstream gate:** the overall retained execution remains STOP(BLOCKED) at TARGETED_MATERIALIZATION_PREP_MEMORY_GUARD. A prior 78-partition publication exists, but final idempotent replay and changed-content conflict acceptance are not complete. Do not equate capture/replay PASS or the prior publication with Issue #76 completion.
- No provider calls, reacquisition, migration, or retained-file mutation occurred in this audit. Keep PR #77 Draft. Do not start the 78-partition migration until the C1 decision is recorded. After that decision, continue only with month-bounded migration from the retained evidence, followed by logical Snapshot/DuckDB facade, ordinary-reader, idempotent replay, and changed-content conflict gates.

## 2026-09-23 authoritative active gate — Issue #76 identity blocker

**This section supersedes the earlier end-of-file C1-pending and credential-waiting checkpoints.** The PM/Owner approved the frozen DAILY_BAR_EVENT_ELIGIBILITY_V1 rule in Issue #76 comment #5795151285. The implementation keeps session-close event eligibility distinct from the retained source-vintage clock and adds no synthetic row-level market_available_at field.

- Local regression QA passed for the C1 daily-bar event contract, Canonical, Snapshot, ReadModel, and R1 research-panel tests; Ruff checks for the affected implementation/tests passed. This is local QA, not a claim that the 78-month acceptance gates or exact-head CI have passed.
- GitHub exact-head CI run 35892568571 (#747) on the preceding commit passed Ruff lint but failed `ruff format --check` on eight files, so its Mypy/pytest steps were skipped. The follow-up formatted the reported files plus two additional files caught by the full local check; local `ruff check .`, `ruff format --check .` (245 files), and `mypy src/ashare_state` (111 files) now pass. The post-type-fix Canonical/Snapshot/ReadModel pytest set also exited 0. CI on this follow-up commit is pending.
- The sequential, month-bounded, offline Canonical migration passed 32/78 months (2020-01 through 2022-08), with 2,758,510 selected rows and provider_calls=0 in that migration process. It stopped fail-fast at 2022-09; no later month was run.
- Retained 2022-09 capture/coverage is PASS: 100,844 daily-bar rows, 4,828 symbols and 21 sessions. Canonical run c608860c-59b3-5c0f-9428-b4a6a177cc8c is BLOCKED at 66,000 selected/decision rows by one IDENTITY_MISSING finding for 34,844 pairs. Offline reproduction with the production IdentityBridge finds 1,669 affected symbols; each has a hist_code_list row with null list_date and no stock_basic row in the retained monthly inputs. The identity policy correctly fails closed.
- Exact code/session evidence and hash-anchored input lineage are recorded in docs/project/ISSUE76_IDENTITY_BLOCKER_2022-09_20260923.md and ISSUE76_2022-09_IDENTITY_MISSING_PAIRS.csv. The CSV is only a derived symbol/session mask; raw provider payloads and database files are not committed.
- Required next action: Owner/PM must provide or authorize authoritative listing-date facts for the exact affected symbols, name a specific authoritative identity source and its bounded use, or formally confirm that retained evidence is insufficient under the current identity contract. Do not guess, borrow identity from other months, reacquire provider data, or resume migration before this decision.
- The earlier materialization-memory guard describes a separate prior execution path; this current migration stopped on identity before archive Snapshot publication and did not pass or re-test that downstream gate. Peak RSS for the failed invocation was not persisted, so no peak value is claimed.
- Issue #76 remains incomplete: 46 months remain; the one logical archive Snapshot, DuckDB external facade, full ordinary-reader inventory, exact idempotent replay, changed-content conflict rejection, and final acceptance/CI gates are not complete. Keep PR #77 Draft.

