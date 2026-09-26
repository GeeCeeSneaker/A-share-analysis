# A-share-analysis 实施路线与优先级

> 生效日期：2026-09-25  
> 最近路线修订：2026-09-26  
> 文档性质：项目级实施路线。用于统一开发、评审和调度判断。  
> 当前执行状态请同时查看 `docs/project/CURRENT_EXECUTION_PLAN.md` 与对应 GitHub Issue。

## 1. 当前阶段目标

项目当前不以“通过更多 gate”为主要产出指标，而以形成**研究口径正确、可以持续日更、普通研究读取足够低摩擦**的 SH/SZ 数据系统为目标。

近期目标：

> **稳定获得截至最近完成交易日的 SH/SZ 日线、可确认的交易状态和涨跌停事实；Provider 无法提供的历史状态明确保持未知；多日研究特征具有明确且不误导的收益/时间语义；正式 runner 可重复执行；普通研究读取不为窄查询整批物化全历史。**

达到这一目标前，不扩大到策略回测、BSE、行业/指数全面建设、分钟级真实 Provider 接入或 Formal B1-B7 Production。

## 2. 项目原则

### 2.1 正确性优先，但只在真实风险处 fail-closed

继续保留 PIT 边界、存活者偏差控制、Canonical 单一事实面、逻辑 Snapshot、身份稳定性、缺失分类、不可猜测补值等已有有效设计。

fail-closed 用于结构错误、语义冲突、不可复现证据和不可逆发布，不用于制造流程等待，也不要求上游提供其事实上不存在的数据。

### 2.2 Unknown stays unknown

Provider 返回空不代表 `false / 0 / 正常 / 无涨跌停`。历史 status/limit 缺口保留为 unresolved/NULL，并携带 coverage evidence。

已返回且通过 identity/date/key/schema 验证的事实可以保存和消费；未知字段不能阻塞与其无关的 daily-bar-only 研究。

### 2.3 区分“数据谱系正确”和“研究数值/语义正确”

CI、hash、manifest、replay 能证明工件来源和执行一致性，但不能单独证明研究公式、价格有效性和时间语义适合研究目的。

因此研究层必须同时明确：

- 原始值是否合法；
- 收益/价格链代表什么，不代表什么；
- 数据何时被系统观察到，与历史交易时点是否可知是两件事；
- 普通研究读取是否与数据规模成合理关系。

### 2.4 任务范围需要授权，任务内部执行自主

Issue 范围一旦批准，开发人员可自主进行 Provider fetch/refetch/retry/replay、targeted probe、对照查询、一致性验证和缺失本地证据重采，不逐次申请。

仅以下变化需重新项目级授权：市场/日期/业务域扩张、新外部数据源、破坏 accepted sealed history、核心 research contract/split 变化、capability promotion、Formal B1-B7/Production、明显超出当前 Issue 的大型架构重建。

### 2.5 最小化同样适用于流程和平台

- 当前控制面保持短小；历史状态留给 Git/Issue/PR。
- spike 不得成为 production dependency。
- 不因单个问题预建 DAG、catalog、缓存服务、temporal database、第二持久化平面或安装器。
- 先证明真实消费者和真实瓶颈，再增加抽象。

## 3. 2026-09-26 外部审计吸收结论

外部审计 PR #99 的可复现实验被接受为**代码路径行为证据**，不被扩大解释为“真实 retained history 已被污染”。审计不改变现有总体架构方向，但改变当前工作优先级。

核心吸收：

1. **研究正确性优先于继续增加治理门禁。** 零价格、收益命名和 PIT 术语必须先清楚。
2. **运行可恢复性优先于包装/部署扩张。** retry budget、migration EOL、fresh-clone cleanliness 应在正式 runner 建设时一并收口。
3. **读取路径是下一阶段真实性能边界。** 已简化存储平面不等于窄查询自然高效，需分区/谓词下推和代表性 workload benchmark。
4. **#95 的历史 Canonical 内存问题是独立收尾/扩展性问题。** 它不能继续串行阻塞研究正确性和日增量系统建设。

## 4. 当前优先级

### P0-A：研究数值与语义正确性 — Issue #97 / PR #100

这是当前最高业务正确性优先级。

#### 4.1 Reference-price linked return / linked price

- 使用有效正值 `close / pre_close` 构造逐日 reference-price factor。
- `return_lag_obs_5/20/60` 使用连续日 factor 链，而不是跨公司行动断点直接 `current_close / prior_close`。
- `ma_close_obs_*` / `close_to_ma_obs_*` 使用同一 deterministic linked-price series。
- 缺失、非有限或非正 `pre_close/close` 断链并产生 NULL/finding；不得 forward-fill。
- feature semantic version/hash 必须变化。

语义必须明确：该链是 **reference-price linked return/price**，用于消除原始价格 reference step 对趋势特征的机械污染；它不是 `TOTAL_RETURN`、不是现金分红持有收益、不是 portfolio NAV/PnL，也不得用这些名称对外暴露。

#### 4.2 Research OHLC 数值有效性

在唯一 research-eligibility 边界收口：

- OHLC 必须 finite 且严格 `> 0`；
- `volume == 0` 本身允许；
- 负值、非有限值和零价格不得进入 `RESEARCH_ENABLED / VERIFIED`。

不得再建第二套 price validator。

#### 4.3 PIT 术语边界

R1 第一阶段定义为**retrospective observed-at-ingest research panel**：snapshot 可以证明系统在构建/观察时拥有这些数据，不自动证明某个 2020 trade-date 的研究者在 2020 当天已经知道后来获取的事实。

- manifest/reader/docs 要明确这个边界；
- 不伪造 historical decision-time `available_at`；
- 不在 #97 建 temporal-version database；
- 将来若具体策略需要严格 decision-time PIT，再以真实历史版本数据单独建设。

#### 4.4 #97 第一批验收

至少覆盖普通序列、分红/reference-price step、送转/拆分类 step、缺失/非法 `pre_close`、零 OHLC、正 OHLC+零 volume，并重验依赖 MA20/mom20 的市场 breadth。

在 #97 完成前，旧口径 R1/CR-6 输出不得直接进入策略回测。

### P0-B：生产化 runner + 日增量与可恢复性 — Issue #98

目标：让项目从历史构建工具成为日常可运行的数据产品。

#### PR A：daily-bar vertical

1. tracked production runner 进入 `src/ashare_state/...`。
2. 提供 `ashare update --through <date>` 与小型 plan/dry-run。
3. calendar → identity/universe delta → missing daily bar → Canonical append → logical Snapshot/read refresh。
4. 同日期重跑幂等，避免无意义 Provider 调用。
5. accepted manifest 绑定 tracked commit + clean/dirty state；dirty 只诊断不 publish。
6. 从 2026-06 accepted boundary 后连续至少 5 个交易日证明更新与重跑。
7. bounded VWAP 检查冻结 SH/SZ volume/amount 单位。

#### 外审合入的运行收口

- **Retry budget**：sleep 不得超过剩余预算；下一次 Provider call 之前再次检查 deadline。
- **Migration EOL**：明确 migration SQL line-ending policy；兼容同一 SQL 文本 CRLF/LF 的既有 ledger，真实内容/token 变化仍 fail-closed；不盲改历史 checksum。
- **Fresh clone cleanliness**：普通 repository text 通过 `.gitattributes` 保证 Windows fresh clone 不因 EOL 变 dirty；只有 byte identity 属于契约的 sealed evidence 保持 byte-exact。
- **Distribution boundary**：当前正式支持 source-checkout operation。若运行布局缺 migrations，startup/self-test 明确报 unsupported layout。没有真实 wheel 消费者前，不建设 migration-resource packaging 或 installer。

#### PR B：status/limit

#96 contract 合入后接入同一 runner。complete/partial upstream coverage 都保存 truthful facts，missing 继续 unresolved/NULL，结构错误继续 fail-closed。

不得增加 scheduler service、DAG framework、distributed queue、新 catalog 或第二套持久化平面。

### P0-C：历史 status/limit Canonical 收尾与扩展性 — Issue #95 / PR #96

#95 不再处于整个项目的关键路径，但必须完成历史事实收尾。

已确认：

- 78/78 capture/coverage reconciliation 完成；
- 16 月 COMPLETE、62 月 PARTIAL_UPSTREAM_COVERAGE；
- 每个 domain 7,461,248 expected / 7,459,685 returned / 1,563 missing；
- structural/duplicate/unexplained-extra = 0；
- 真实 Canonical-only 尝试已触发 16 GiB RSS 硬边界，Provider calls=0。

当前路径：

1. 若执行主机确有安全余量，可做**一次** higher-resource Canonical-only finalization：至少 32 GiB 物理内存、启动前约 28 GiB 可用、约 24 GiB isolated hard stop；仍然零 Provider call。
2. 无安全主机或触发 24 GiB 后，不继续抬内存上限，直接做窄 disk-backed/columnar selection 修复。
3. 修复只删除已确认的全历史 Python copies/materialization/list-sort 压力，复用 Parquet/Polars/DuckDB；Canonical durable artifacts、hash/seal/replay contract 不变。
4. 不重写 Canonical，不引入第二存储平面。

PASS：完整 Canonical build、consumer verification、exact idempotent replay、exact-head CI，并记录 peak RSS/stage checkpoints。

### P1-A：研究读取分区/谓词下推与 workload benchmark — Issue #101

目标：解决“存储已简化，但普通窄查询仍可能整批读取/物化”的问题。

- publication/deep-audit 可以做完整 artifact/hash verification；
- ordinary research read 信任已验证且不可变的 manifest，先选相关 partition/file，再 materialize；
- 用现有 DuckDB/Polars lazy/external scan 下推 date/security_id filter；
- 去掉普通读路径中可避免的 whole-dataset `read_bytes -> read_parquet -> to_dicts` 和 DB `fetchall -> Python dict list`；
- 不建 cache server、index service、catalog、第二 research dataset 或新 query framework。

基准至少：

- one security / one year；
- all market / one month；
- all market / one year。

记录 elapsed、peak RSS、opened partitions/files、cold run 和 immediate hot repeat。基线测量前不拍脑袋制定统一 latency SLA。

## 5. 紧随主线的可靠性工作

### P1-B：raw evidence 最小备份与巡检

每月/批次完成后压成少量不可变 archive + checksum；一个 configurable second backup root；一个 receipt→archive existence/hash verify command。只对新 accepted run 强制，不为旧历史先做迁移，不建对象存储/catalog 服务。

### P1-C：Provider completeness / partial coverage

Provider OK 不等于完整。后续 ingestion 使用 explicit denominator/requested-key set、请求成员与返回成员逐一核对、coverage 状态入 receipt/manifest、缺失保持 unresolved、targeted refetch 可自主执行。

### P1-D：adapter / legacy / spike 净删除

production mapper/normalization 为唯一生产语义路径；diagnostic 尽量调用 production；spike 只保留一次性用途；优先净删除而不是造 replacement framework。

## 6. 明确暂缓

当前不抢占主线：

- strict historical decision-time temporal database；
- total-return / cash-inclusive corporate-action accounting model；
- wheel/installer/migration-resource packaging；
- 2019 或更早 warmup；
- Provider `adj_factor` 全历史；
- 指数/行业全面建设；
- BSE；
- 外部多源仲裁体系；
- 策略回测；
- 分钟级真实 Provider；
- Formal B1-B7 Production。

这些不是永久取消，而是等真实消费者/研究需求证明价值后再排。

## 7. 近期实施顺序

### 立即并行

1. **#97 / PR #100**：完成 reference-price chain、OHLC >0、PIT/return semantic boundary，exact-head CI 后优先审阅。
2. **#98**：立即形成 PR A；daily-bar tracked runner 与 N2/N4/C3 运行收口同时推进，不等 #95。
3. **#95 / PR #96**：独立完成历史 Canonical finalization/scalability，不占住 #97/#98。
4. **#101**：可并行建立 read-path baseline，但不得拖慢前两条 P0。
5. **PR #99**：作为外部审计记录独立保存/合并；实施代码不塞回审计 PR。

### 第一批完成后

- #97 新语义成为默认 research feature contract；
- #98 从历史边界追平到最新完成交易日并证明连续 5-session operation；
- #95 完成历史 known-fact Canonical/replay；
- #101 给出真实 retained-data 读取基线和最小 pushdown 改善；
- 再按真实研究收益决定 warmup、adj_factor、index/industry 等后续项。

## 8. 阶段验收指标

未来评审优先看能力，而不是 gate 数：

- research OHLC 不接受 0/负/非有限价格，零成交量本身不误判；
- multi-day return/MA 不被 raw-price corporate-action step 机械污染，且公开语义不会冒充 total/holding return；
- R1 明确 retrospective observed-at-ingest 与 strict decision-time PIT 的区别；
- 日线更新到最近完成交易日，update 可幂等重跑；
- fresh Windows clone 不因普通文本 EOL 误报 dirty；retry budget 不越界发起下一次调用；
- status/limit known facts 可复现，upstream missing 明确 partial/unresolved；
- #95 historical Canonical 能完成并 exact replay；
- 普通窄研究查询证明 partition/filter pushdown，避免无必要的全历史物化；
- accepted run 可由 tracked code + retained evidence 重放；
- 控制面保持短小，无重复审批/重复文档层。

## 9. 文档与调度约定

- 本文维护“实施路线、优先级和为什么”；
- `CURRENT_EXECUTION_PLAN.md` 只维护当前工作、真正 blocker 和最近动作；
- Issue 维护具体 acceptance/实时进展；
- PR 维护代码/证据 review；
- 外审/设计文档保留事实和建议，不直接成为新的审批层；
- 路线实质变化时先更新本文，再调整当前执行计划。