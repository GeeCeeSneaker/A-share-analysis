# A-share-analysis 外部项目评审报告

日期：2026-09-26

评审方式：Codex 独立代码与文档审阅、离线测试、合成输入复现、官方资料核对。未实施第二模型盲审。

代码基线：[main@76e8581701098da9896309cd976f62207a3b0510][baseline]。本报告的行号与结论均针对该提交。

交付范围：报告、离线复现脚本、验证摘要；不修改生产逻辑、冻结规则或历史证据。

## 1. 评审结论

**建议继续沿用现有数据架构，但暂不把“审计链完整、CI 通过”视为“已经具备可靠的历史策略研究和日常生产运行能力”。** 这是评审判断，不是项目的生产批准或投资结论。

项目的实际定位是量化研究数据基座，并非完整交易系统。因此，没有下单、撮合和策略优化模块不是当前缺陷。Canonical 单一持久事实层、逻辑 Snapshot、DuckDB 外部 Parquet 查询、稳定证券身份，以及未知状态不填成负面事实，方向合理；目前没有证据支持更换数据库或引入分布式平台。

最需要优先解决的是三个落差：

1. **数据有完整血缘，不保证业务数值有效。** 合成的零价格行能通过研究资格判断，并进入日收益和市场平均收益计算。
2. **数据在采集时点可追溯，不保证历史决策时点可得。** 当前时间契约主要证明观察/采集时间；下游不能直接据此宣称历史无前视。
3. **底层存储已简化，消费端仍存在全量工作。** 窄查询仍可能读取整个研究 split，历史 reader 在加载时还会遍历验证全部 artifact。

已有 #97（多日价格口径）、#98（日增量生产化）应保持最高实施优先级；本报告增加的数值边界、迁移可搬迁性和研究读路径问题可以作为窄修复处理。不要再建立一套评审状态机或数据治理框架。

## 2. 证据等级、范围与限制

本报告使用四种标记：

- **已确认**：能在基线代码定位，且适用时已经离线复现。
- **条件风险**：实现事实成立，但影响取决于下游用途或部署方式。
- **建议**：评审者提出的取舍，尚未作为项目合同生效。
- **未验证**：本次未取得足够证据，不作肯定或否定结论。

覆盖了 Provider/normalization、Canonical、Snapshot/ReadModel、Feature/State、research reader、迁移与打包，以及现有路线图、开放 Issue/PR 和 CI。采用关键路径审阅，不声称逐行审计全部代码。

本次未连接 AmazingData 生产账户、未安装专有 SDK、未取得被 gitignore 的真实 78 个月数据，亦未运行 Formal B1–B7、实盘或策略回测。因此：

- 仓库中“历史构建完成”的记录是项目已有证据陈述，本次没有独立复核其全部原始事实。
- 没有证据表明真实数据已出现本报告的零价格污染，也没有证明其完全不存在。
- PR #96 只用于了解在途工作状态，不属于本次 main 代码审阅基线；本报告不对该 PR 作批准或否决。
- 合成反例用于验证软件行为，不是市场行情、实测收益或 Provider 故障记录。

### 实际执行的验证

| 检查 | 结果 | 能证明什么 |
|---|---|---|
| `uv sync --frozen` | 成功；Windows、CPython 3.14.7 | 锁定依赖可安装；不证明生产 SDK 兼容 |
| `ruff check .` | 通过 | 当前静态规则通过 |
| `ruff format --check .` | 249 个文件无需调整 | 当前格式门禁通过 |
| `mypy` | 112 个源文件通过 | 当前类型检查通过 |
| 完整离线 pytest | **1,939 passed，9 skipped，0 failed，0 errors**；退出码 0 | 现有离线断言成立；跳过项不是已验证 |
| 测试收集复核 | 1,948 项 | 与执行进度标记总数一致 |
| 基线远端 CI | Windows / Ubuntu Python 3.14 均成功，[运行记录][baseline-ci] | 基线跨平台 CI 成功，不代表跨平台搬迁同一个数据库已验证 |
| 本次额外复现 | 换行、零价格、窄查询、重试预算、wheel；另含时间语义与收益算例 | 见附带脚本和结果摘要 |

测试计数由 pytest 进度日志与 collect-only 输出核对；没有把新增诊断当成原测试套件的通过项。正式交付的脚本也已单独执行。

## 3. 优先级总表

P1 表示应在对应研究使用或运行场景上线前解决；P2 表示可在相邻工作中修正。这里不把每个工程欠缺都升级为 P0。

| 编号 | 优先级 | 事项 | 证据性质 | 与现有工作关系 |
|---|---|---|---|---|
| N1 | P1 | 零 OHLC 行被标记为 VERIFIED，并产生 −100% 收益 | 已确认、合成复现 | 本次新增；可并入 #97 的有效输入边界 |
| N2 | P1 | 迁移 checksum 受 LF/CRLF 影响 | 已确认、合成复现 | 本次新增；恢复与换机前修复 |
| N3 | P1 | 窄研究查询仍读取/验证大范围数据 | 已确认；实际大样本成本未测 | 架构简化在消费端尚未完成 |
| N4 | P2 | 重试休眠越过预算后仍发起新请求 | 已确认、假时钟复现 | 本次新增；适合 #98 附近窄修复 |
| N5 | P2 | wheel 不包含 migrations，脱离源码布局初始化失败 | 已确认；部署方式相关 | 若仅支持源码 checkout，需明确写出边界 |
| C1 | P1 | 采集时点 PIT 与历史决策时点 PIT 容易混用 | 条件风险、接口行为已复现 | 研究消费前明确合同 |
| C2 | P1 | #97 的参考价收益链不能自动等同持仓总回报 | 数学反例、官方语义支持 | 对已知 #97 的补充意见 |
| C3 | P2 | 新 clone 就显示 6 个换行差异，与 clean-run 目标冲突 | 已确认；部分已有记录 | 已知债务的新影响，不冒充全新发现 |

## 4. 本次确认的问题及最小改进

### N1：零价格不是可用于收益计算的有效价格

**已确认。** [研究资格判断][eligibility]只拒绝负数，允许 `open=high=low=close=0`；OHLC 排序关系也全部成立。给定合法身份、有效研究日期、`volume=amount=0`、`pre_close=10`，返回：

```text
research_eligibility = RESEARCH_ENABLED
data_quality_state = VERIFIED
raw_return_1 = -1.0
valid_raw_return_count = 1
mean_raw_return_observed = -1.0
```

[Feature 数值公式][formulas]只要求分母正且有限；[市场聚合][feature-aggregation]把该 −100% 值计入有效样本。这里分别验证了真实的资格函数和 FeatureEngine；不是声称所有实际发布链路都已出现该数据。

**影响。** 一旦上游以全零 OHLC 表示停牌、无报价或占位数据，就可能被解释为真实价格归零，污染收益、市场宽度和状态判断。当前未验证 AmazingData 是否实际返回此类行。

**建议。** 在日价格的主要语义边界明确：可研究价格必须为正；无报价/占位行保留来源与原因，输出 NULL 或禁用相关价格特征。不要删除 Raw，也不要简单把所有 `volume=0` 的记录都当成坏数据；无成交但有效参考价格要按已验证语义处理。Feature 入口应消费同一个有效性结论，避免多个层各写一套校验。

**验收。** 零 OHLC、正 OHLC/零量、负价、非有限值、正常行情各有边界样例；零价格不得进入有效收益分母或有效收益样本；一次针对 retained 历史的聚合巡检只报告计数与代表键，不向仓库上传行情。

### N2：同一迁移的换行变化会导致数据库被误判为篡改

**已确认。** [`_file_sha256()`][migration-hash]直接 hash `read_bytes()`；[`.gitattributes`][attributes]固定了 JSON/YAML 等文件的 LF，但未固定 SQL。本次 checkout 的 24 个 migration 都是 `i/lf w/crlf attr/`。

复现：把仓库 `001_identity_calendar.sql` 分别保存为 LF 和 CRLF，先用 LF 初始化临时数据库，再以 CRLF 文件调用迁移。SQL 文本经通用换行读取后完全相同，但抛出 `MigrationTamperedError`。

**影响。** 两个 Windows 工作区采用不同 Git 换行配置，或恢复数据库到另一 checkout，就可能启动失败。当前 CI 在各平台分别从零创建数据库，覆盖不到同一数据库跨换行环境再打开的情形。

**建议。** 固定 migration 的字节表示，并处理已经登记 CRLF hash 的存量 ledger。不能只新增 `*.sql text eol=lf` 后就宣布完成，也不能盲目重写旧 checksum；应提供一次有范围的兼容判断/迁移，证明差异仅为允许的换行变化，真实 SQL 修改继续阻断。

**验收。** 同一临时数据库在 LF/CRLF checkout 下重开成功，或给出明确可执行的兼容流程；修改一个真实 SQL token 必须仍被拒绝；24 个 migration 的 Git 属性在新 clone 中一致。

### N3：窄查询的过滤发生得太晚，底层优化收益没有贯穿研究端

**已确认。** [R1 reader][r1-reader]在日期/证券/列筛选前执行整个 artifact 的 `read_bytes()`、`pl.read_parquet()` 和 `frame.to_dicts()` 语义 hash。小样本中，请求 1 行 1 列，底层仍读取 2 行 24 列，且 Parquet 读取没有投影参数。这是执行顺序复现，不是全市场性能基准。

问题并不局限于旧 R1：[HistoricalMaterializationReader.from_manifest()][historical-reader]逐个读入并复核 artifact；其 `load_security_daily()` 又读完目标 split 的全部月文件，再按日期和证券过滤。已有月分区没有被用来先裁剪请求范围。[FeatureBuilder][feature-builder]仍对 ReadModel `fetchall()` 后生成 Python 字典列表。

**影响。** 研究者查询一个月、一只证券时，内存和 I/O 仍随更大数据集增长；重复查询重复支付全量 hash 成本。不能由此断言当前机器必然 OOM，本次未取得真实数据来测峰值。

**建议。** 沿用项目已经采纳的边界：发布/显式审计做深校验，普通读消费不可变分区与 manifest 的验证结果。先按分区日期选文件，再用 DuckDB SQL 或 Polars `scan_parquet().filter().select()` 做谓词/列下推；需要大输出时提供 batch/lazy 形式。保留明确的深度审计入口，不把删除所有完整性检查当优化。[Polars 官方说明][polars-doc]支持在读取阶段进行下推。

**验收。** 同一份合成多月数据，请求单月时不访问无关月份的事实文件；单证券投影不先转全表为 Python 字典；小样本结果/顺序与原实现一致。为“单证券一年、全市场一个月、全市场一年”各记录一次耗时、峰值 RSS、打开的文件数，并明确冷/热缓存；先测量再选择优化规模。

### N4：重试预算在 sleep 之后没有再次检查

**已确认。** [`run_with_budget()`][retry-code]在捕获异常后检查 deadline，再执行完整 backoff；下一轮直接调用 `fn()`。假时钟实验配置 0.05 秒预算、1 秒退避、第一次网络错误，第二次调用仍在 `t=1.0` 发出并成功返回。

**影响。** 即使 SDK 每次都及时返回错误，系统也会在已耗尽重试预算后再请求一次。这与原生 SDK 无法硬中断是两个问题。模块开头已诚实说明“重试预算不是硬超时”，应保留该说明。

**建议。** 退避不超过剩余预算，并在发起下一次重试前重新检查 deadline；预算耗尽时保留最终错误类别和尝试次数。不因此增加进程调度框架，也不宣称修复后可以取消阻塞中的原生 SDK 调用。

**验收。** 用假时钟证明最后一个允许时点之后没有新调用；正常成功、不可重试错误、预算耗尽三类行为保持清楚。

### N5：源码 checkout 可运行，但构建的 wheel 不能独立初始化

**已确认，部署方式相关。** [wheel 配置][packaging]只打包 `src/ashare_state`；[CLI][cli-code]按 `Path(__file__).parents[2] / "migrations"` 查找文件。本次 `uv build --wheel` 成功，但 wheel 中 SQL 文件数为 0。在独立临时目录载入该 wheel 的包、复用锁定依赖执行 `init_db()`，退出码为 1，错误是 `MigrationError: migrations directory not found`。

**影响。** `uv sync` 的 editable checkout 路径掩盖了包资源缺失。README 当前主推源码运行，因此不把它描述成所有受支持启动方式都失败。

**建议。** 选择一个清晰边界：若发布 wheel 是近期目标，把 migrations 作为包资源并使用 `importlib.resources`；若只支持完整 checkout，则明确限制并让 self-test 检出缺少 migrations，而不是输出 0 后继续成功。暂不需要新安装器。

**验收。** 用构建产物在源码目录之外执行初始化和幂等迁移；或文档/自检明确拒绝不支持的安装布局。

## 5. 容易被忽略的研究语义

### C1：把“当年发生”与“系统何时知道”分开

**已确认的事实。** [availability policy][availability-code]对所有支持域使用 `OBSERVED_AT_INGEST`，`available_at = received_at`。[R1 projection][r1-projection]检查的是 `available_at <= source_snapshot_as_of`，不是 `available_at <= 历史策略决策时刻`；默认 reader 只有 split/date 过滤，没有 decision-time 参数。

合成面板中，2020-01-02 的行、2026-07-01 才观察到的数据，在 2026-09-01 snapshot 下可从 Development 读出。这符合当前“回顾式数据面板”的实现，但不构成“2020 年已经知道该值”的证明；测试入口显式使用 `allow_test_fixture=True`，没有绕过生产来源门禁。

**条件风险。** 下游如果只按 `trade_date` 回测，并把这个面板称为严格历史 PIT，可能混入后续修订和事后恢复的状态。反过来，机械套用 `available_at <= 2020年决策时间` 又会把后来回采的数据全部排掉。不能靠伪造当天 15:00 的可用时间解决这一矛盾。

**建议。** 在现有研究 manifest/接口说明中明确本数据集属于“后来观察的历史数据”还是“有原始 vintage 证明的历史时点数据”。严格 PIT 消费必须按决策时间选可用版本；无法证明的历史日线可用于明确披露假设的回顾研究，但不能同名冒充严格 PIT。若未来用交易规则推导 EOD 可用时间，必须同时说明这是一项假设，并保留供应商后修订的限制。增加最小的用途/时间语义说明即可，不必建立新的时间数据库。

**验收。** 未来才观察到的修订在严格 PIT 查询中不可见；回顾模式明确返回其真实观察时间与限制；不得回写现有证据的 `available_at`。

### C2：支持 #97 修复，但明确 linked price 的经济含义

**已知缺陷。** #97 已准确指出：原始 close 比值和原始 close MA 会把除权除息台阶当成多日价格变化。这个问题不能因为当前字段叫 `UNADJUSTED_CANONICAL` 就忽略；面向趋势/动量消费者时仍需要明确修复或禁用。

**本次补充。** 用 `close / pre_close` 链接日变化可以修复这类台阶，但“参考价收益链”不自动等于真实持仓总回报，也不等于现金分红、配股、税费和再投资全部正确记账。[上交所规则发布页及其第 4.3 节附件][sse-rule]区分前收盘价和除权除息参考价；[MSCI 的总回报方法说明][msci-doc]另外处理现金分配。

一个纯算术反例，忽略税费且不做额外再投资：

| 输入/结果 | 数值 |
|---|---:|
| 前一日真实收盘价 | 10.00 |
| 每股现金分红 | 1.00 |
| 除息参考价 | 9.00 |
| 当日收盘价 | 9.90 |
| `close / pre_close - 1` | 10% |
| 原持有人价格加现金的回报 `(9.9 + 1) / 10 - 1` | 9% |

**建议。** #97 继续推进，不等待完整 adj_factor 历史；先证明 Provider 的 `pre_close` 在所用板块/公司行动样本中确为预期参考价，并把派生序列命名和文档解释为参考价链接序列。不要把它直接用于资本回测净值或贴上 `TOTAL_RETURN` 标签。现金分红、送转、配股分别验证，状态 flag 不能替代完整权益事件账。

### 样本、交易条件与验证划分的后续边界

项目已经显式使用 `OBSERVED_DAILY_BAR_UNIVERSE`，这是优点。仍需在下游保留以下区别：

- 没有 bar 不等于退市或不在历史股票池；有 bar 不等于可成交。停牌、涨跌停和状态缺失不能由 bar 是否存在推断。
- #95 允许部分上游事实进入 Canonical 后，状态相关研究应只在字段已知时消费；不能把未知状态转为 `false`，也不应无理由禁用同一证券已验证的 OHLCV。R1 当前没有状态字段，此项是后续连接合同的要求，不是已经观察到的误连接。
- Development/Validation/Holdout 的显式划分已实现，但不负责所有标签泄漏。未来研究项目要按真实预测周期处理跨边界标签和 embargo，特征预处理只在训练窗口拟合；这是下游职责，当前不应塞进数据采集层。
- 初期没有足够 warmup 就保留 NULL；不以为了“满窗”而向前填充或偷用未来观测。指数、行业和容量评估等按真实研究需求补齐。

## 6. 已知事项的复核：不重复建任务

| 已有工作 | 本次判断 | 建议补充的验收点 |
|---|---|---|
| [#97 多日特征][issue97] | 原始价格台阶问题仍在 main；应优先修复 | 加 N1 有效价格边界、C2 参考价/总回报区别；重新验证 CR-6 消费结果 |
| [#98 生产 runner / 日增量][issue98] | CLI 尚无 update；DTO 的 volume/amount 仍写 TBD。已被项目识别 | 保持一个 tracked runner；每日增量、同日幂等、补缺、最终成功边界；单位检查按板块分组并处理零量分母 |
| [#95 / #96 状态与涨跌停历史][issue95] | 最新项目计划记录 78 月均有 partial coverage；不能把它改写为无缺口历史 | 复用 retained evidence；已知事实与 unresolved 键均可追溯；只阻断结构/身份/语义错误。真实全量本次未复核 |
| 备份与恢复 | 当前路线图已含 raw archive、第二备份根及 hash 巡检 | 增加一次在临时干净目录的实际恢复读取；明确 ledger/manifest/规则/环境锁也如何保留。重新拉取不保证拿回同一 vintage |
| [#82 Formal 兼容检查][issue82] | 应保持原有边界 | 报告不构成 Formal 或 Production 批准，也不要求为了报告重跑生产数据 |

### C3：clean checkout 与 clean-run 要求需要对齐

**已确认。** 新 clone、尚未编辑文件时 `git status` 已显示 6 个修改，`git diff --ignore-cr-at-eol` 为空；原因是索引存储 CRLF、属性要求 LF。5 个旧 Golden 文档在[历史工作流][legacy-workflow]中已有专门处理，另有 `docs/architecture/benchmarks/a1_minute_layout_benchmark_20260923.json`。

**条件风险。** 若 #98 用全仓 `git status` 判断可发布代码必须 clean，会让新 checkout 无法满足条件；若不断加“忽略这几个文件”的分支，则会积累不可维护的例外。

**建议。** 对普通文本做受控规范化；对必须保留原字节的封存证据，采用一致的 byte-exact 属性并复核已有 hash。两类不要混着批量 renormalize。本次报告没有改动这 6 个文件，也不会把它们的换行差异带进提交。

## 7. 可删减的复杂度与维护改进

这些是建议，不是新增上线前置审批。

1. **把简化延伸到研究端和非 daily 域。** daily ReadModel 已跳过全量事实扫描，但[非 daily 域仍逐表计数/语义 hash][readmodel-validation]；一旦 #95 大历史接入，需实测普通 open 的工作量。先修 N3 的真实读路径，不先增加新缓存服务。
2. **把源码 fingerprint 当构建 provenance，兼容性按合同判断。** 当前 ReadModel 仍要求 builder 源码 fingerprint 与当前代码相同，注释修改也可能要求重建。ReadModel 可重建，因此风险低于已封存 Canonical 被误拒绝；但应评估“兼容代码升级后仍可读”是否值得作为一个小用例，避免重演之前的可用性问题。
3. **清理一次性执行面。** 现有 tracked Python 源码 112 个文件、49,782 行，其中 `src/ashare_state/spike/` 19 个文件、10,851 行；tests 为 113 个文件、43,797 行，scripts 为 21 个文件、15,393 行。行数不是质量评分，只说明维护面已经很大。每个迁入 production 的职责同时删掉无消费者的旧 spike/测试，避免长期保留双路径。
4. **补面向用户的入口说明。** README 仍写 migration `001–004`，实际已到 `024`；应链接 CURRENT_EXECUTION_PLAN，说明今天能执行什么、哪些 reader 是推荐入口、哪些数据只能回顾使用。保留冻结设计原文，更新入口页即可。
5. **补五类有价值的测试，而非再加内部防伪测试。** N1 数值有效性、N2 数据库换工作区、N3 查询实际访问范围、N4 截止时间、N5 构建产物启动。它们检验外部可观察行为，能弥补“原公式自证”的局限。

## 8. 建议实施顺序与退出条件

| 批次 | 最小交付 | 可观察的退出条件 |
|---|---|---|
| A：研究正确性 | 继续 #97；合入 N1；明确 C1/C2 | 公司行动与零价格样例通过；旧语义版本不会被当成新版本；历史 PIT 限制可见 |
| B：运行与可恢复 | 继续 #98；处理 N2/N4/C3；若要分发再处理 N5 | 幂等日增量；预算后不再发请求；干净 checkout；临时恢复目录能读取同一已封存版本 |
| C：研究可用性 | N3 的分区裁剪/下推；小规模真实 workload 测量 | 单月查询不扫无关月；峰值 RSS 和 I/O 可解释；既有结果一致 |
| D：有消费者再扩展 | 指数/行业、R2、策略研究、分钟数据 | 每项扩展有明确消费场景和验收样例，不增加第二套持久事实层 |

不要让备份体系、全市场分钟级重构或新的审批流程阻塞 #97/#98 的首个可用版本。修复顺序按实际影响调整，而非按报告章节顺序机械执行。

## 9. 复现方式与证据文件

- [离线诊断脚本](reproduce_external_review_20260926.py)：只创建临时数据库/合成 Parquet，不调用网络或 Provider；使用显式 test-only 面板入口。
- [实际验证摘要](external_review_20260926_evidence.json)：基线、测试结果和诊断输出，未包含账户、绝对本机路径、行情或 SDK。

在本报告基线及锁定依赖环境中，PowerShell 可执行：

```powershell
uv sync --frozen
uv build --wheel --out-dir "$env:TEMP/ashare-review-wheel"
uv run python docs/reviews/reproduce_external_review_20260926.py `
  --wheel "$env:TEMP/ashare-review-wheel/ashare_state-0.1.0-py3-none-any.whl"
```

脚本的输出是诊断观察，并不把缺陷保留为未来必须满足的断言。wheel 检查从构建产物加载代码、复用当前锁定依赖，是包资源检查，不宣称做过全新生产机器安装。正式修复时应把对应验收样例放到正常测试中，诊断脚本可随问题关闭归档，避免成为另一套生产路径。

[baseline]: https://github.com/GeeCeeSneaker/A-share-analysis/commit/76e8581701098da9896309cd976f62207a3b0510
[baseline-ci]: https://github.com/GeeCeeSneaker/A-share-analysis/actions/runs/36220340201
[eligibility]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/research/eligibility.py#L49-L115
[formulas]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/features/formulas.py#L26-L37
[feature-aggregation]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/features/engine.py#L863-L885
[migration-hash]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/storage/migrations.py#L84-L85
[attributes]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/.gitattributes
[r1-reader]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/research/reader.py#L78-L183
[historical-reader]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/research/historical.py#L3957-L4045
[feature-builder]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/features/builder.py#L197-L202
[retry-code]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/providers/amazingdata/timeout.py#L108-L164
[packaging]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/pyproject.toml#L42-L46
[cli-code]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/cli.py#L23-L38
[availability-code]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/canonical/availability.py#L65-L112
[r1-projection]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/research/panel.py#L820-L838
[legacy-workflow]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/.github/workflows/gt-h3b-controlled-execution.yml#L66-L82
[readmodel-validation]: https://github.com/GeeCeeSneaker/A-share-analysis/blob/76e8581701098da9896309cd976f62207a3b0510/src/ashare_state/readmodel/duckdb_model.py#L537-L597
[issue97]: https://github.com/GeeCeeSneaker/A-share-analysis/issues/97
[issue98]: https://github.com/GeeCeeSneaker/A-share-analysis/issues/98
[issue95]: https://github.com/GeeCeeSneaker/A-share-analysis/issues/95
[issue82]: https://github.com/GeeCeeSneaker/A-share-analysis/issues/82
[polars-doc]: https://docs.pola.rs/user-guide/lazy/using/
[sse-rule]: https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml
[msci-doc]: https://www.msci.com/indexes/documents/methodology/0_MSCI_Index_Calculation_Methodology_20250826.pdf
