# Current Execution Plan

> 本文件只维护**当前正在做什么、为什么、下一步是什么、什么会阻塞**。  
> 项目实施路线、优先级和长期考虑见 [`IMPLEMENTATION_ROADMAP_20260925.md`](IMPLEMENTATION_ROADMAP_20260925.md)。  
> 历史状态、SHA、CI run 和旧 scheduler 指令以 Git / Issue / PR 为准，不在这里重复维护。

## 当前阶段目标

尽快形成一个可持续使用的 SH/SZ 研究数据系统：

- 日线可以更新到最近完成交易日；
- `security_status` / `limit_price` 的已知事实可复现，历史上游缺口显式标记为 unresolved/partial coverage，不被解释成负面状态；
- 多日 momentum / MA 等研究特征口径正确；
- 正式 accepted run 由 tracked production code 执行；
- 常规 fetch/refetch/retry/probe 在已批准任务内自主执行，不等待逐次审批。

在这一阶段完成前，不启动策略回测、BSE 扩展、行业/指数全面建设、分钟级或 Formal B1-B7 Production。

## 当前并行 P0

### P0-A — Issue #95 / PR #96：SH/SZ status + limit 历史闭环

状态：**ACTIVE / upstream partial coverage confirmed; truthful-row publication path being completed**。

已确认：

- 62 个已对账月份累计有 1,563 个 unresolved pair/domain；
- 单证券/单日重拉仍可返回成功但 0 行；
- 至少两个抽样缺口日存在同日 daily bar；
- 因此缺口不是普通 batch、normalization 或 retry 问题，而是上游历史 coverage/applicability 不完整；
- PR #96 已把 status keyed-table 语义收敛到 production mapper/normalization，production 不再反向依赖 spike。

当前动作：

1. 不再等待 Provider 对历史漏行给出书面解释，也不再为同一 1,563 个 gap 做无差别重拉。
2. 每月输出 `COMPLETE` 或 `PARTIAL_UPSTREAM_COVERAGE`（可复用现有等价模型，不新建框架）。
3. 对 partial 月 Canonicalize **实际返回且结构正确**的 status/limit 行；missing pair 不生成任何默认/负面事实。
4. 保留 expected/returned/missing 计数、missing-key-set hash 与安全证据绑定。
5. 复用已验证的 62 个月，完成剩余月份采集与对账。
6. downstream/status enrichment 对缺失 status/limit 保持 NULL/UNRESOLVED；依赖这些字段的研究输出排除或显式标记，daily-bar-only 研究不被阻塞。
7. PR #96 完成 78/78 对账、Canonical exact replay 和 Windows/Ubuntu Python 3.14 exact-head CI 后进入独立 PASS 审查。

仍然严格阻塞的错误：unkeyed/invalid row、duplicate、identity conflict、out-of-window、unexplained extra、schema/semantic conflict。

### P0-B — Issue #97：修正多日研究特征口径

状态：**OPEN / implementation requested now**。

第一实现切片：

- 用每日 `close / pre_close` 构造 PIT-safe linked return/price chain；
- `return_lag_obs_5/20/60` 改为链式日收益乘积；
- `ma_close_obs_5/20/60` 与 `close_to_ma_obs_*` 使用同一 linked-price series；
- `pre_close` 缺失/非法时断链并输出 NULL/finding；
- feature semantic version/hash 必须变化；
- fixtures 至少覆盖普通序列、现金分红/reference-price step、送转/拆分类 step、缺失 `pre_close`；
- 重验 `pct_above_ma20_observed` 与 `pct_positive_mom20_observed`。

IPO 无涨跌幅期和长停牌保护属于 #97，但若现有 feature engine 没有足够 governed input，不得阻塞第一 PR；可先明确 disable/blocker，再做窄 follow-up。

### P0-C — Issue #98：生产化 runner + 日增量

状态：**OPEN / first implementation split requested**。

PR A 先做稳定 daily-bar vertical，不依赖未合并的 #96：

1. tracked `src/ashare_state/...` production update runner；
2. `ashare update --through <date>`；
3. calendar → identity/universe delta → missing daily bar → Canonical append → logical Snapshot/read refresh；
4. accepted manifest 绑定 commit SHA + clean/dirty state；dirty run 只能诊断，不能 publish；
5. 用 2026-06 accepted boundary 后的前 5 个交易日证明连续更新与幂等重跑；
6. 在同一 bounded slice 完成 volume/amount VWAP unit check（至少 60/00/30/688 分组）。

PR B 在 #96 contract merge 后，把 status/limit 接入同一 runner；历史/实时上游 coverage 缺口保持 partial/unresolved，不转成默认值。

随后执行 `ashare update --through 2026-09-25` 追平数据边界，再证明新的 5-session operational cycle。

## 当前调度规则

### 开发人员可自主执行

在已经批准的 Issue 范围内，可自主：Provider fetch/refetch、retry/replay、bounded targeted probe、单证券/单日/邻近日对照、一致性验证、缺失 local evidence 重采、定位 blocker 的 fresh isolated run。

这些动作不需要新的 PM/Owner 批准。

### 仍需重新授权

- SH/SZ 扩到 BSE；
- 日期扩到已批准范围之外；
- 新业务数据域 / 新外部数据源；
- destructive mutation / deletion of accepted sealed history；
- research split / core research-contract change；
- capability promotion；
- Formal B1-B7 / Production；
- 明显超出当前 Issue 的大型架构重建。

## 数据质量边界

**Unknown stays unknown.** 上游没有返回事实时，允许已知事实进入 Canonical，但缺失位置必须保持 unresolved/NULL，并保留 coverage evidence。不得把缺失解释成 `not suspended`、`not ST`、`no price limit` 或其他负面事实。

以下结构错误仍阻止对应 capture/accepted run：unkeyed row、duplicate natural key、identity conflict、out-of-window row、unexplained extra、schema/semantic conflict、无法复现的 evidence binding。

## 紧随 P0 的 P1

1. raw evidence 最小异地/异盘备份 + receipt/hash 巡检；
2. Provider completeness/partial-coverage 规则固化到日常 ingestion；
3. adapter / legacy / spike 路径净删除与依赖方向收敛；
4. 根据研究收益决定 `adj_factor` 交叉校验、指数基准、外部抽检和 warmup 历史。

## 暂缓

当前不抢占 P0：2019 或更早 warmup、provider `adj_factor` 全历史、指数/行业全面建设、BSE、外部多源抽检体系、策略回测、分钟级真实 Provider 接入、Formal B1-B7 Production。

## 下一次调度检查重点

1. #96 是否完成 78/78 complete/partial coverage 对账、Canonical exact replay 和 exact-head CI；
2. #97 是否出现第一版 chained-return/linked-price PR 与 corporate-action fixtures；
3. #98 是否出现 tracked runner / `ashare update --through` PR A，并完成首个 5-session slice；
4. partial status/limit coverage 是否在 downstream 被严格保留为 unresolved，而不是静默负面值；
5. 是否又出现重复审批或历史文档堆叠；无具体风险的控制应删除。