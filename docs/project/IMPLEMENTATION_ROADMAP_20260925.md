# A-share-analysis 实施路线与优先级

> 生效日期：2026-09-25  
> 最近路线修订：2026-09-26  
> 文档性质：项目级实施路线。用于统一开发、评审和调度判断。  
> 当前执行状态请同时查看 `docs/project/CURRENT_EXECUTION_PLAN.md` 与对应 GitHub Issue。

## 1. 当前阶段目标

项目下一阶段不再以“通过更多 gate”为主要产出指标，而以形成可持续使用的研究数据系统为目标。

近期目标是：

> **让研究端稳定获得截至最近交易日的 SH/SZ 日线、可确认的交易状态和涨跌停事实；对 Provider 无法提供的历史状态明确标记为未知；同时保证多日研究特征不会因除权除息、新股无涨跌幅期或长停牌产生系统性错误。**

达到这个目标之前，不扩大到策略回测、BSE、行业/指数全面建设、分钟级数据或 Formal Production。

## 2. 已确认的项目原则

### 2.1 正确性优先，但只在真实风险处 fail-closed

继续保留 PIT、存活者偏差控制、Canonical 单一事实面、逻辑 Snapshot、身份稳定性、缺失分类、不可猜测补值等已经证明有价值的设计。

fail-closed 用于结构错误、语义冲突和不可逆发布，不用于要求上游数据源必须提供它事实上没有的数据。

### 2.2 Unknown stays unknown，不让未知拖死已知事实

Provider 返回空并不代表 `false/0/正常/无涨跌停`。历史 status/limit 缺口必须保留为 unresolved/NULL，并有 coverage evidence。

但只要已返回行本身通过 identity/date/key/schema 验证，就可以作为 truthful Canonical fact 保存。研究层继续使用现有 `RESEARCH_DISABLED_UNRESOLVED`、`DataQualityState.UNRESOLVED` 和 partial/unresolved coverage 语义隔离未知字段。

### 2.3 任务范围需要授权，任务范围内的只读数据调用不逐次授权

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

### 2.4 优先解决实际问题，不为历史工件本身停工

旧 retained artifact 丢失或难以恢复时，如果重新拉取是更简单、更快且可验证的方式，应直接重新拉取。不要为了恢复旧路径而建立新的 recovery framework。

### 2.5 最小化同样适用于流程

- 当前执行控制面保持一页级别；
- 历史状态留在 Issue / PR / Git 历史，不重复复制 SHA、CI 编号和旧 scheduler 指令；
- 一次性 spike 不得反向成为 production dependency；
- 不为一个真实使用场景预建通用框架；
- 每增加一个审批点，都必须能说明它具体防止什么不可逆或高代价失败，否则取消。

## 3. 当前优先级

### P0-A：完成 SH/SZ `security_status + limit_price` 历史闭环 — Issue #95 / PR #96

**目标**：完成 2020-01..2026-06 的月度历史，把 Provider 能确认的 status/limit 事实完整保存，并把上游历史 coverage 缺口显式建模，形成后续日增量可复用的正式契约。

已确认：

- status keyed-table identity/date/key fail-closed 路径已跑通；
- production normalization 已收敛到正式 AmazingData mapper，不再反向依赖 spike；
- 62 个已对账月份累计有 1,563 个 unresolved pair/domain；
- 单证券/单日重拉仍可成功返回 0 行；
- 至少两个缺口日存在同日 daily bar；
- 因此这不是普通 batch、normalization 或 retry 问题，而是上游历史 coverage/applicability 不完整。

路线决定：

1. 不再等待 Provider 对历史漏行给出书面解释，也不再要求同一 endpoint 把历史 gap 补到 0。
2. 每月明确 `COMPLETE` 或 `PARTIAL_UPSTREAM_COVERAGE`（优先复用现有等价模型）。
3. 对所有实际返回且结构正确的 status/limit 行正常 Normalize/Canonicalize。
4. missing pair 不生成任何值；不得解释成 not suspended、not ST、no price limit 或其他负面状态。
5. 每月保存 expected/returned/missing 计数、missing-key-set hash 和证据绑定。
6. 复用已经验证的历史 capture，完成剩余月份，不为已确认的 coverage gap 做大规模重复重拉。
7. downstream 对 missing status/limit 保持 unresolved/NULL；依赖这些字段的研究输出排除或显式标记，daily-bar-only 研究不受阻塞。

**#95 PASS**：78/78 月完成 capture/reconciliation；所有返回行结构正确、可 replay；complete/partial coverage 明确；known facts Canonicalized；missing facts 未被猜测；Windows/Ubuntu Python 3.14 exact-head CI 通过。零 upstream missing **不再是** PASS 条件。

### P0-B：修正多日研究特征口径 — Issue #97

**原因**：现有 `return_lag_obs_*`、`ma_close_obs_*`、`close_to_ma_obs_*` 基于未复权 raw `close`，在分红、送转、除权参考价变化时会制造假的多日跌幅/趋势变化，并污染市场态势聚合。

第一实现切片：

- 使用每日 `close / pre_close` 链式累计计算多日收益；
- 从同一 PIT-safe 链构造 research-only linked price，用于均线和 close-to-MA；
- `pre_close` 缺失/非法时断链并输出 NULL/finding，不 forward-fill、不跨 gap；
- 一日 `raw_return_1` 等已正确口径保持不变；
- feature semantic version/hash 明确变化；
- fixtures 覆盖普通序列、现金分红/reference-price step、送转/拆分类 step、缺失 `pre_close`；
- 重验 CR-6 中依赖 MA20/mom20 breadth 的状态。

无涨跌幅 IPO session 和长停牌保护仍属于 #97，但如果现有 feature engine 没有足够 governed input，不得阻塞第一 PR；先明确 disable/blocker，再做窄 follow-up。

性能优化不是前置条件。如果 Polars 改写能减少代码并保持逐值一致，可以完成；否则先修语义。

**在 #97 完成前，不允许把旧口径 R1/CR-6 输出直接用于策略回测。**

### P0-C：生产化 runner + 日增量能力 — Issue #98

**目标**：把项目从“一次历史构建”变成可日常运行的数据系统。

分两步：

**PR A：先生产化已经稳定的 daily-bar vertical**

1. 持久化运行编排进入 `src/ashare_state/...`。
2. 提供 `ashare update --through <date>`。
3. 最小链路：calendar → identity/universe delta → missing daily bar → Canonical append → logical Snapshot/read refresh。
4. 同一日期重跑幂等，不做无意义 Provider 工作。
5. accepted run manifest 记录 tracked commit SHA 和 clean/dirty state；dirty run 只诊断、不 publish。
6. 用 2026-06 accepted boundary 后的前 5 个交易日证明连续更新和幂等重跑。
7. 同一 bounded slice 完成 volume/amount VWAP unit check（至少 60/00/30/688 分组）。

**PR B：#96 contract 合入后接 status/limit**

- 接入同一个 tracked runner，不建第二套路径；
- complete/partial upstream coverage 都能保存 truthful facts；
- missing status/limit 保持 unresolved/NULL；
- 结构错误仍然 fail-closed。

随后执行 `ashare update --through 2026-09-25` 追平数据边界，并完成新的 5-session operational cycle。

该 Issue 还需完成：最小 raw archive + second backup root + integrity verify，以及删除无当前消费者的一次性 `gt-h3b-controlled-execution.yml`。这些不应阻塞 PR A 的第一版 tracked vertical。

不要增加 scheduler service、DAG framework、distributed queue、新 catalog 或第二套持久化平面。

## 4. 紧随 P0 的可靠性工作

### P1-A：raw 证据备份与巡检

- 每月/批次完成后，将碎 raw + receipt 打包为少量不可变 archive；
- 一个可配置 second backup root；
- 一个 `receipt -> archive exists + hash match` 巡检命令；
- 只对新 accepted run 强制，不先做旧历史大迁移；
- 不建对象存储/catalog/备份服务框架。

### P1-B：Provider completeness / partial coverage 成为普通 ingestion 不变量

Provider 返回 OK 不能等同于完整，也不能因为不完整就丢弃其余真实事实。

所有后续 endpoint 采用：

- explicit expected denominator 或 exact requested-key set；
- 保守分批；
- 请求成员与返回 table/member 逐一核对；
- 缺失保持 unresolved，不自动当成 negative fact；
- coverage 状态进入 manifest/receipt；
- 必要时 targeted refetch 自主执行。

### P1-C：收敛 adapter / legacy 路径

- production mapper/normalization 成为唯一生产语义路径；
- Golden/diagnostic 尽可能调用正式生产路径；
- spike 只保留真正一次性或诊断用途；
- 删除已经完成使命的旧 spike 和兼容层；
- 以净删除/依赖方向变简单为目标，不建 replacement framework。

## 5. 暂缓项及原因

以下事项有价值，但当前不能抢占 P0：

- **2019 或更早 warmup**：先把 2020+ 数据质量、特征口径和日增量做正确，再按真实研究需求回补。
- **Provider `adj_factor`**：后续用于与 PIT linked-return 链交叉校验，不等待它修当前多日特征。
- **指数 / 行业**：等 SH/SZ 核心数据可持续更新后再补。
- **BSE**：先完成通用 identity/code mapping 能力再开启。
- **外部抽检源**：以后作为小规模 DQ signal，不进入 Canonical，不建多源仲裁框架。
- **Formal B1-B7 / Production**：仍不自动授权，当前重点是正确、稳定、日常可用的数据产品。

## 6. 近期实施顺序

### 现在并行推进

- #95/#96：按 complete/partial coverage 契约完成剩余月份、Canonicalization、replay、CI；
- #97：提交 chained-return/linked-price 第一 PR；
- #98：提交 tracked daily-bar runner + `ashare update --through` PR A。

三条线互不要求串行等待，但不能互相修改对方 retained run。

### 第一批完成后

1. #95 形成 78/78 status + limit known-fact history + explicit partial coverage；
2. #97 在真实公司行动样本上通过新特征语义验证；
3. #98 用历史边界向 2026-09-25 增量追平；
4. 连续 5 个交易日自动运行；
5. 然后再决定 adj_factor、指数、外部抽检和 warmup。

## 7. 阶段验收指标

未来阶段性评审优先看能力，而不是 gate 数量：

- 日线数据能更新到最近已完成交易日；
- SH/SZ status + limit 的 known facts 可复现，upstream missing 有明确 partial coverage 且不会被解释成负面状态；
- 研究端可以只在 status/limit 已知时消费对应状态字段；
- 多日 momentum / MA 不受公司行动 raw-price discontinuity 污染；
- update 可幂等重跑，失败可定位；
- Provider OK 不会绕过 completeness/coverage 检查；
- accepted run 可由 tracked code + retained evidence 重放；
- raw 证据有独立副本并可巡检；
- 控制面文档保持简短，没有同一决策在多份文档重复维护。

## 8. 文档与调度约定

- 本文维护“实施路线、优先级和为什么”；
- `CURRENT_EXECUTION_PLAN.md` 只维护当前进行中的工作、阻塞和最近下一步；
- Issue 维护具体任务 acceptance 与实时进展；
- PR 维护具体代码/证据 review；
- 历史 SHA、CI run、旧 scheduler 指令不再回填到本文。

路线变化时，应先更新本文对应优先级/理由，再调整当前执行计划，确保参与项目的人员从仓库即可了解最新方向。