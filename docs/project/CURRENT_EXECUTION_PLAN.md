# Current Execution Plan

> 本文件只维护**当前正在做什么、为什么、下一步是什么、什么会阻塞**。  
> 项目实施路线、优先级和长期考虑见 [`IMPLEMENTATION_ROADMAP_20260925.md`](IMPLEMENTATION_ROADMAP_20260925.md)。  
> 历史状态、SHA、CI run 和旧 scheduler 指令以 Git / Issue / PR 为准，不在这里重复维护。

## 当前阶段目标

尽快形成一个可持续使用的 SH/SZ 研究数据系统：

- 日线可更新到最近完成交易日；
- `security_status` / `limit_price` 的已知事实可复现，历史上游缺口显式标记为 unresolved/partial coverage，不被解释成负面状态；
- 多日 momentum / MA 等研究特征口径正确；
- 正式 accepted run 由 tracked production code 执行；
- 常规 fetch/refetch/retry/probe 在已批准任务内自主执行，不等待逐次审批。

在这一阶段完成前，不启动策略回测、BSE 扩展、行业/指数全面建设、分钟级或 Formal B1-B7 Production。

## 当前并行 P0

### P0-A — Issue #95 / PR #96：SH/SZ status + limit 历史闭环

状态：**78/78 capture reconciled / Canonical one-time build remains**。

已确认：

- 78/78 月度 capture 与 coverage receipt 已完成；
- 16 月 `COMPLETE`，62 月 `PARTIAL_UPSTREAM_COVERAGE`；
- 每个 domain：7,461,248 expected、7,459,685 returned、1,563 missing；
- structural error / duplicate / unexplained extra = 0；
- missing pair 保持 unresolved，不生成默认或负面事实；
- status keyed-table 语义已经收敛到 production mapper/normalization，production 不反向依赖 spike；
- 当前 exact-head Windows/Ubuntu Python 3.14 CI 已通过。

当前唯一 blocker：一轮全历史 Canonical build 的 Python 内存占用较高。上一次在约 9.91 GiB 时人工停止，但现有硬门槛 16 GiB **并未触发**。

当前动作：

1. 完全复用已经保留的 78 个月 normalized evidence；Canonical 尝试不得重新调用 Provider。
2. 先用**现有代码**完成一次 Canonical-only 尝试，在 16 GiB 硬门槛内继续运行；不得因为 RSS 上升但未到门槛而提前停止。
3. 记录 bounded RSS checkpoint：Canonical 前、snapshot/input materialization 后、selection 后、artifact write 后、verify 后、exact replay 后。
4. 若直接完成：立即 exact replay/verification，进入独立 PASS 审查；不要优化一个已经安全完成的一次性路径。
5. 只有实际触发 16 GiB 门槛时才整改内存。整改只针对已确认的全量 Python copies：normalized `to_dicts()`/frozen tuples、`candidates`/`available`/`selected_rows`、schema alignment、semantic-hash 全量排序、`selected_file_rows`。复用 Parquet/Polars/DuckDB，保持持久 Canonical contract/seal 不变，不新建框架。

仍严格阻塞的错误：unkeyed/invalid row、duplicate、identity conflict、out-of-window、unexplained extra、schema/semantic conflict、evidence binding 无法复现。

### P0-B — Issue #97：修正多日研究特征口径

状态：**ACTIVE / implementation must start now; no implementation PR yet**。

第一实现 PR：

- 用每日 `close / pre_close` 构造 PIT-safe linked return/price chain；
- `return_lag_obs_5/20/60` 改为链式日收益乘积；
- `ma_close_obs_5/20/60` 与 `close_to_ma_obs_*` 使用同一 linked-price series；
- `pre_close` 缺失/非法时断链并输出 NULL/finding；
- feature semantic version/hash 必须变化；
- fixtures 覆盖普通序列、现金分红/reference-price step、送转/拆分类 step、缺失 `pre_close`；
- 重验 `pct_above_ma20_observed` 与 `pct_positive_mom20_observed`；
- 至少一个 retained real-data corporate-action 对照；
- Windows/Ubuntu Python 3.14 CI。

IPO 无涨跌幅期和长停牌保护若需要额外 governed input，不得阻塞第一 PR；明确 blocker 后在 #97 内做窄 follow-up。禁止策略回测和 FeatureEngine 大重写。

### P0-C — Issue #98：生产化 runner + 日增量

状态：**ACTIVE / PR A must start now; no implementation PR yet**。

PR A 从 current `main` 独立开发，不依赖 #96：

1. tracked `src/ashare_state/...` production update runner；
2. `ashare update --through <date>` + 小型 plan/dry-run；
3. calendar → identity/universe delta → missing daily bar → Canonical append → logical Snapshot/read refresh；
4. accepted manifest 绑定 commit SHA + clean/dirty state，dirty 只能诊断不能 publish；
5. 同日期重跑幂等并避免无意义 Provider 调用；
6. 用 2026-06 accepted boundary 后前 5 个交易日证明连续更新；
7. 在同一 bounded slice 完成 volume/amount VWAP unit check（至少 60/00/30/688 分组）；
8. 无当前消费者时删除一次性 GT-H3B workflow。

PR B 在 #96 contract merge 后把 status/limit 接入同一 runner；历史/实时上游 coverage 缺口继续保持 partial/unresolved，不转默认值。

## 并行资源原则

#95 的一次性 Canonical 完成性验证不得继续占住 #97/#98。三条 P0 必须独立 branch/PR 推进：

- #95：只处理 Canonical 完成/真实资源边界；
- #97：研究特征正确性；
- #98：日常运行能力。

它们不要求串行等待，也不得互相修改对方 retained run。

## 当前调度规则

已批准 Issue 范围内，开发人员可自主执行 Provider fetch/refetch、retry/replay、bounded targeted probe、一致性验证、缺失 local evidence 重采和定位 blocker 的 fresh isolated run，无需新的 PM/Owner 批准。

仍需重新授权：SH/SZ 扩到 BSE、日期扩到批准范围之外、新业务域/新外部源、破坏性修改 accepted sealed history、research split/core research-contract change、capability promotion、Formal B1-B7/Production、明显超出当前 Issue 的大型架构重建。

## 数据质量边界

**Unknown stays unknown.** 上游没有返回事实时，允许已知事实进入 Canonical，但缺失位置必须保持 unresolved/NULL 并保留 coverage evidence。不得把缺失解释成 `not suspended`、`not ST`、`no price limit` 或其他负面事实。

## 紧随 P0 的 P1

1. raw evidence 最小异地/异盘备份 + receipt/hash 巡检；
2. Provider completeness/partial-coverage 固化到日常 ingestion；
3. adapter / legacy / spike 路径净删除；
4. 根据研究收益决定 `adj_factor`、指数基准、外部抽检和 warmup 历史。

## 暂缓

当前不抢占 P0：2019 或更早 warmup、provider `adj_factor` 全历史、指数/行业全面建设、BSE、外部多源抽检体系、策略回测、分钟级真实 Provider 接入、Formal B1-B7 Production。

## 下一次调度检查重点

1. #96 的 Canonical-only 尝试是否直接在 16 GiB 内完成；若触发门槛，内存整改是否只处理已确认的全量 copies；
2. #96 是否完成 exact replay 并进入 PASS review；
3. #97 是否已经出现 chained-return/linked-price 代码 PR；
4. #98 是否已经出现 tracked runner / `ashare update --through` PR A；
5. 是否存在新的无必要审批、重复文档或等待链；发现即删除。