# Current Execution Plan

> 本文件只维护**当前正在做什么、为什么、下一步是什么、什么会阻塞**。  
> 项目实施路线、优先级和长期考虑见 [`IMPLEMENTATION_ROADMAP_20260925.md`](IMPLEMENTATION_ROADMAP_20260925.md)。  
> 历史状态、SHA、CI run 和旧 scheduler 指令以 Git / Issue / PR 为准，不在这里重复维护。

## 当前阶段目标

尽快形成一个可持续使用的 SH/SZ 研究数据系统：

- 日线、`security_status`、`limit_price` 可更新到最近完成交易日；
- 多日 momentum / MA 等研究特征口径正确；
- Provider 返回 OK 不能绕过完整性校验；
- 正式 accepted run 由 tracked production code 执行；
- 常规 fetch/refetch/retry/probe 在已批准任务内自主执行，不等待逐次审批。

在这一阶段完成前，不启动策略回测、BSE 扩展、行业/指数全面建设、分钟级或 Formal B1-B7 Production。

## 当前并行 P0

### P0-A — Issue #95 / PR #96：SH/SZ status + limit 历史闭环

状态：**ACTIVE / publication blocked by recurring unresolved pairs**。

已确认：

- 2020-01..2026-06 月度采集范围已批准；
- 允许任务范围内自主 reacquire / retry / targeted probe；
- 多个月真实采集已完成，但 45 个连续月份都残留少量 unresolved pair；
- Canonical publication 正确保持 blocked；
- 当前迹象更像 applicability / endpoint coverage / denominator mismatch，而不是随机传输失败。

当前动作：

1. 暂停无差别继续跑剩余月份；保留现有未接受 run。
2. 从早期、中期、近期月份各选小样本 missing pair。
3. 自主执行单证券/单日/邻近日 status 查询及必要的 identity/listing/session/daily-bar 对照。
4. 给 gap 建立证据支持的最小分类；不按“Provider 没返回就从 denominator 删除”。
5. 找到规则后先重跑至少 3 个 sentinel 月。
6. sentinel 月 unresolved applicable pair=0 后，再恢复剩余历史采集。

PR #96 合并前必须同时满足：

- production normalization 不依赖 `ashare_state.spike.*`；
- status keyed-table identity/date 校验收敛到正式 mapper/normalization；
- spike 可以调用 production code，production 不反向 import spike；
- 不新建第三套 adapter/framework。

### P0-B — Issue #97：修正多日研究特征口径

状态：**OPEN / may run in parallel with #95**。

当前缺陷：5/20/60 日收益、均线和 close-to-MA 使用未复权 raw `close`，会在分红、送转等 reference-price 变化时产生错误的多日趋势信号。

当前动作：

- 用每日 `close / pre_close` 链式累计构造 PIT-safe 多日收益；
- 用同一链生成 research-only linked price 供 MA/close-to-MA 使用；
- `pre_close` 缺失/非法时断链并输出 NULL/finding；
- 保持已正确的一日 raw-return / gap / intraday / amplitude 语义；
- 同一修改路径解决无涨跌幅 IPO session 的市场聚合污染和长停牌导致的无限跨期窗口；
- 重新验证 CR-6 中依赖 momentum/MA breadth 的状态。

性能重写不是前置条件。能用更少代码安全替换为 Polars 则做，否则先完成语义修复。

### P0-C — Issue #98：生产化 runner + 日增量

状态：**OPEN / start in parallel**。

当前动作：

1. 将持续运行需要的 orchestration 收敛到 `src/ashare_state/...`。
2. 实现 `ashare update --through <date>`。
3. 最小 EOD 链路：calendar → identity/universe delta → missing daily bar → status/limit → completeness → Canonical open-month append → logical Snapshot/read surface。
4. accepted run manifest 绑定 tracked commit 和 clean/dirty state。
5. 同日期重跑幂等；缺失/可疑 evidence 可自动 refetch，不需要逐次授权。
6. 完成连续至少 5 个交易日无人工代码修改的更新演示。
7. 用 bounded VWAP 检验冻结 SH/SZ volume/amount 单位。
8. 删除无当前消费者的一次性 `gt-h3b-controlled-execution.yml`。

不要增加 scheduler service、DAG framework、distributed queue、新 catalog 或第二持久化平面。

## 当前调度规则

### 开发人员可自主执行

在已经批准的 Issue 范围内，可自主：

- Provider fetch / refetch；
- retry / replay；
- bounded targeted probe；
- 单证券/单日/邻近日对照；
- 一致性验证；
- 缺失 local evidence 的重新获取；
- 为定位 blocker 进行小范围 fresh isolated run。

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

## 当前发布门禁

执行自由度提高，不代表降低数据质量要求。

以下任一情况存在时，对应数据不得进入 accepted Canonical history：

- unresolved applicable missing pair；
- unkeyed row；
- duplicate natural key；
- identity conflict；
- out-of-window row；
- unexplained extra；
- schema/semantic conflict；
- endpoint completeness 未证明。

允许继续自主查询和重采来解决这些问题，但不允许通过猜测、补值或删除 denominator 来获得 PASS。

## 紧随 P0 的 P1

P0 主线完成后按以下顺序推进：

1. raw evidence 最小异地/异盘备份 + receipt/hash 巡检；
2. Provider completeness 规则固化到所有日常 ingestion；
3. adapter / legacy / spike 路径净删除与依赖方向收敛；
4. 根据研究收益决定 `adj_factor` 交叉校验、指数基准、外部抽检和 warmup 历史。

## 暂缓

当前不抢占 P0 的工作：

- 2019 或更早 warmup；
- provider `adj_factor` 全历史；
- 指数 / 行业全面建设；
- BSE；
- 外部多源抽检体系；
- 策略回测；
- 分钟级真实 Provider 接入；
- Formal B1-B7 Production。

## 下一次调度检查重点

1. #95 是否已完成 missing-pair root-cause 小样本归因，是否出现可复现规则；
2. PR #96 是否去除了 production → spike 依赖；
3. #97 是否给出 corporate-action regression fixture 和 corrected chained-return 结果；
4. #98 是否已经形成 tracked runner / `ashare update --through` 最小骨架；
5. 是否有任何新审批或文档层只是重复 Git/Issue 已有信息；如无具体风险，应删除而不是继续扩治理。
