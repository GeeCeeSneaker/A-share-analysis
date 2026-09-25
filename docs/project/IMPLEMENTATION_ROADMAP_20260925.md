# A-share-analysis 实施路线与优先级

> 生效日期：2026-09-25  
> 文档性质：项目级实施路线。用于统一开发、评审和调度判断。  
> 当前执行状态请同时查看 `docs/project/CURRENT_EXECUTION_PLAN.md` 与对应 GitHub Issue。

## 1. 当前阶段目标

项目下一阶段不再以“通过更多 gate”为主要产出指标，而以形成可持续使用的研究数据系统为目标。

近期目标是：

> **让研究端稳定获得截至最近交易日的 SH/SZ 日线、可交易状态和涨跌停数据，并保证多日研究特征不会因除权除息、新股无涨跌幅期或长停牌产生系统性错误。**

达到这个目标之前，不扩大到策略回测、BSE、行业/指数全面建设、分钟级数据或 Formal Production。

## 2. 已确认的项目原则

### 2.1 正确性优先，但只在真实风险处 fail-closed

继续保留 PIT、存活者偏差控制、Canonical 单一事实面、逻辑 Snapshot、身份稳定性、缺失分类、不可猜测补值等已经证明有价值的设计。

fail-closed 用于数据正确性和不可逆发布，不用于制造流程等待。

### 2.2 任务范围需要授权，任务范围内的只读数据调用不逐次授权

一个 Issue 的业务范围一旦批准，开发人员可以自主进行合理的 Provider fetch/refetch/retry/replay、targeted probe、对照查询和一致性验证，不需要每次重新申请。

只有以下变化需要新的项目级授权：

- 扩大市场范围，例如 SH/SZ -> BSE；
- 扩大时间范围到当前任务之外；
- 引入新的业务数据域或新的外部数据源；
- 破坏性覆盖/删除已经验收的 sealed history；
- 修改研究切分、核心研究契约或正式发布语义；
- capability promotion；
- Formal B1-B7 / Production；
- 明显超出当前任务自然范围的大规模架构重建。

### 2.3 优先解决实际问题，不为历史工件本身停工

旧 retained artifact 丢失或难以恢复时，如果重新拉取是更简单、更快且可验证的方式，应直接重新拉取。不要为了恢复旧路径而建立新的 recovery framework。

### 2.4 最小化同样适用于流程

- 当前执行控制面保持一页级别；
- 历史状态留在 Issue / PR / Git 历史，不重复复制 SHA、CI 编号和旧 scheduler 指令；
- 一次性 spike 不得反向成为 production dependency；
- 不为已经有一个真实使用场景的问题预建通用框架；
- 每增加一个审批点，都必须能说明它具体防止什么不可逆或高代价失败，否则取消。

## 3. 当前优先级

### P0-A：完成 SH/SZ `security_status + limit_price` 历史闭环 — Issue #95 / PR #96

**目标**：完成 2020-01..2026-06 的月度历史，并形成后续日增量可复用的正式契约。

当前状态：

- 月度请求、身份/date/key fail-closed 路径已跑通；
- 已完成多个连续月份的真实采集；
- 连续多月均存在少量 unresolved pair；最新检查时已连续覆盖到 48 个月，具体实时数量以 Issue #95 为准；
- Canonical publication 仍被正确阻断；
- 这已经更像统一的 applicability / endpoint coverage / denominator mismatch，而不是随机网络失败。

**当前最优动作不是继续盲跑剩余月份，而是先解释共性 gap。**

执行要求：

1. 保留现有 run，不接受任何 unresolved month。
2. 从早期、中期、近期月份各抽取小样本 missing pairs。
3. 对 missing pair 自主做单证券/单日/邻近日 status 查询，以及必要的 identity、listing、session、daily-bar 对照。
4. 判断 gap 是否属于：
   - 非适用 session；
   - endpoint 不返回某类状态；
   - identity/listing 边界问题；
   - denominator 过宽；
   - Provider 静默不完整；
   - 其他可复现规则。
5. 只接受证据支持的最小规则；不按“缺了就删”修 denominator。
6. 用至少 3 个 sentinel 月重跑验证；只有 unresolved applicable pairs=0 后才恢复剩余 78 个月执行。
7. Canonical 仍要求：missing/extra/duplicate/identity conflict/out-of-window/structural error 全部为 0。

**PR #96 合并前额外要求**：production normalization 不得依赖 `ashare_state.spike.*`。把 status keyed-table identity/date 校验收敛到正式 mapper/normalization 边界；spike 可以调用 production code，production 不得反向 import spike。不要建立第三套 adapter。

### P0-B：修正多日研究特征口径 — Issue #97

**原因**：现有 `return_lag_obs_*`、`ma_close_obs_*`、`close_to_ma_obs_*` 基于未复权 raw `close`，在分红、送转、除权参考价变化时会制造假的多日跌幅/趋势变化，并污染市场态势聚合。

实施方向：

- 使用每日 `close / pre_close` 链式累计计算多日收益；
- 从同一 PIT-safe 链构造 research-only linked price，用于均线和 close-to-MA；
- `pre_close` 缺失/非法时断链并输出 NULL/finding，不 forward-fill、不跨 gap；
- 一日 `raw_return_1` 等已正确口径保持不变；
- 同一修改路径内解决：无涨跌幅 IPO session 对市场聚合的污染、长停牌后 observed-bar window 跨越过长日历间隔；
- CR-6 中消费 momentum/MA breadth 的状态重新验证。

性能优化不是该任务的前置条件。如果 Polars 改写能同时减少代码并保持逐值一致，可以完成；否则先修语义，性能另排。

**在 #95 + #97 完成前，不允许把当前 R1 直接用于策略回测。**

### P0-C：生产化 runner + 日增量能力 — Issue #98

**目标**：把项目从“一次历史构建”变成可日常运行的数据系统。

最小交付：

1. 持久化运行编排进入 `src/ashare_state/...`，正式 accepted run 不依赖 ignored/local `runner.py` 或长期 spike 脚本。
2. 提供：

   ```text
   ashare update --through <date>
   ```

3. EOD 最小链路：
   - calendar / target sessions；
   - identity / universe delta；
   - missing daily-bar；
   - status + limit；
   - completeness / reconciliation；
   - open-month Canonical append；
   - accepted 后刷新 logical Snapshot / external read surface。
4. 命令幂等；同一日期重跑不做无意义 Provider 工作。
5. accepted run manifest 至少记录 tracked commit SHA 和 clean/dirty state；正式发布只接受 clean tracked code。
6. 连续至少 5 个交易日无需改代码、无需逐日审批即可更新成功。

该任务同时完成两个小型债务：

- 用 bounded VWAP (`amount / volume`) 与 `[low, high]` / 100x 关系冻结 SH/SZ 成交量和成交额单位；按 60/00/30/688 至少分组验证；
- 删除已经无当前用途的一次性 `gt-h3b-controlled-execution.yml` workflow，历史证据留在 Git。

不要在 #98 中增加 scheduler service、DAG framework、distributed queue、新 catalog 或第二套持久化平面。

## 4. 紧随 P0 的可靠性工作

### P1-A：raw 证据备份与巡检

Issue #90 已经证明仅有 Git receipt/hash 而没有原始文件副本是不够的。

采用最小方案：

- 每月/批次完成后，将大量碎 raw + receipt 打包为少量不可变 archive；
- 保留一个可配置 second backup root（异盘、NAS 或其他独立存储位置）；
- 提供一个 `receipt -> archive exists + hash match` 巡检命令；
- 只对新 accepted run 强制，不为旧历史先做一次大迁移；
- 不建对象存储/catalog/备份服务框架。

### P1-B：Provider completeness 成为所有 ingestion 的普通不变量

Provider 返回 OK 不能等同于完整。

所有后续 endpoint 采用：

- explicit expected denominator 或 exact requested-key set；
- 保守分批；
- 请求成员与返回 table/member 逐一核对；
- 缺失保持 unresolved，不自动当成 negative fact；
- 必要时 targeted refetch 自主执行。

这条原则直接进入 #95 和 #98，不再单独建设新的 governance subsystem。

### P1-C：收敛 adapter / legacy 路径

当前已确认 spike adapter 和 production mapper/normalization 有重复语义。

方向：

- production mapper/normalization 成为唯一生产语义路径；
- Golden/diagnostic 尽可能调用正式生产路径；
- spike 只保留真正一次性或诊断用途；
- 删除证明问题已经解决的旧 spike 和兼容层；
- 以净删除/依赖方向变简单为目标，不新建 replacement framework。

## 5. 暂缓项及原因

以下事项有价值，但当前不能抢占 P0：

### 5.1 2019 或更早 warmup

250 日特征确实会使 2020 大部分窗口不可用，但先把当前 2020+ 数据质量、特征口径和日增量系统做正确。之后再由 Owner 根据研究需要决定是否仅回补 warmup。

### 5.2 Provider `adj_factor`

后续用于与隐含 PIT 调整链交叉校验，而不是等待它来修当前多日特征。

### 5.3 指数 / 行业

等当前 SH/SZ 基础数据可持续更新后，再补沪深300/中证500/1000等基准与行业数据。

### 5.4 BSE

先完成通用代码变更/identity mapping 再开启，避免继续逐事件人工 hard-code。当前 P0 不扩到 BSE。

### 5.5 外部抽检源

可以作为每月少量 DQ signal，但不进入 Canonical，不建设多源仲裁框架。等核心日增量稳定后再决定具体来源。

### 5.6 Formal B1-B7 / Production

仍不自动授权。当前重点是形成正确、稳定、日常可用的数据产品；Formal 另行决策。

## 6. 近期实施顺序

### 现在并行推进

- #95：暂停无差别继续历史月份，先定位系统性 unresolved gap，并修正 #96 production/spike 依赖方向；
- #97：修多日收益/均线/PIT 口径；
- #98：抽取正式 runner，建立 `ashare update --through` 骨架与单位检查。

三条线互不要求串行等待，但不能互相修改对方 retained run。

### 第一批完成后

1. #95 形成 78/78 status + limit accepted history；
2. #97 在真实数据上通过特征语义验证；
3. #98 用历史边界向当前日期增量追平；
4. 连续 5 个交易日自动运行；
5. 然后再决定 adj_factor、指数、外部抽检和 warmup。

## 7. 阶段验收指标

未来阶段性评审优先看以下能力，而不是 gate 数量：

- 日线数据能更新到最近已完成交易日；
- SH/SZ status + limit 在支持窗口内无 unresolved applicable pair；
- 研究端能区分停牌、ST、涨跌停等基本可交易状态；
- 多日 momentum / MA 不受公司行动 raw-price discontinuity 污染；
- IPO 无涨跌幅期和长停牌不会扭曲市场聚合；
- update 可幂等重跑，失败可定位，Provider OK 不会绕过完整性检查；
- accepted run 可由 tracked code + retained evidence 重放；
- raw 证据存在独立副本并可巡检；
- 控制面文档保持简短，没有同一决策在多份文档重复维护。

## 8. 文档与调度约定

- 本文维护“实施路线、优先级和为什么”；
- `CURRENT_EXECUTION_PLAN.md` 只维护当前进行中的工作、阻塞和最近下一步；
- Issue 维护具体任务 acceptance 与实时进展；
- PR 维护具体代码/证据 review；
- 历史 SHA、CI run、旧 scheduler 指令不再回填到本文。

路线变化时，应先更新本文对应优先级/理由，再调整当前执行计划，确保参与项目的人员从仓库即可了解最新方向。