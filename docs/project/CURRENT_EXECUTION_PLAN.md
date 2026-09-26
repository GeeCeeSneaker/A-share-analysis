# Current Execution Plan

> 本文件只维护**当前正在做什么、为什么、下一步是什么、什么会阻塞**。  
> 项目长期路线和优先级理由见 [`IMPLEMENTATION_ROADMAP_20260925.md`](IMPLEMENTATION_ROADMAP_20260925.md)。  
> 历史 SHA、CI、旧 scheduler 指令留在 Git/Issue/PR，不在这里重复堆叠。

## 当前阶段目标

把 SH/SZ 数据平台推进到三个同时成立的状态：

1. **研究口径正确**：价格、收益和 PIT 术语不误导下游；
2. **日常可运行**：tracked runner 可幂等更新到最近完成交易日；
3. **普通研究可用**：窄读取不无条件整批物化全历史。

外部审计 PR #99 已作为 advisory engineering evidence 吸收。其 synthetic reproductions 证明代码路径行为，不自动证明 retained real history 已发生同样污染。

## 当前主线优先级

### P0-A — Issue #97 / PR #100：研究数值与语义正确性

状态：**ACTIVE / draft implementation exists / highest correctness priority**。

当前必须完成：

- `close/pre_close` 构造 reference-price linked chain；
- 5/20/60 日 return、MA、close-to-MA 使用同一链；
- invalid/nonpositive `pre_close/close` 断链 -> NULL/finding；
- research OHLC 必须 finite 且 `>0`，`volume==0` 本身允许；
- feature semantic identity bump；
- 分红/reference-step、送转/拆分、缺失 pre_close、zero-OHLC、zero-volume fixtures；
- 明确该链**不是 total return / cash-inclusive holding return / NAV**；
- R1 明确是 retrospective observed-at-ingest panel，不声称 historical decision-time knowability；
- 重验依赖 MA20/mom20 的 breadth；
- exact-head Windows/Ubuntu Python 3.14 CI。

不等待 adj_factor，不建 temporal database，不做 FeatureEngine 大重写，不启动策略回测。

### P0-B — Issue #98：tracked runner + 日增量与运行可恢复性

状态：**ACTIVE / implementation PR A must start now**。

PR A：

1. tracked `src/ashare_state/...` production runner；
2. `ashare update --through <date>` + 小型 plan/dry-run；
3. calendar → identity/universe delta → missing daily bar → Canonical append → logical Snapshot/read refresh；
4. 同日期重跑幂等、避免无意义 Provider call；
5. accepted manifest 绑定 clean tracked commit；
6. 从 2026-06 accepted boundary 后连续至少 5 个交易日证明运行；
7. bounded VWAP 检查冻结 volume/amount 单位。

外审一并收口：

- retry sleep 受 remaining budget 限制，下一次 Provider call 前再检查 deadline；
- migration SQL 明确 EOL policy，同文本 CRLF/LF 既有 ledger 不误报 tamper；
- 普通 repo text 用 `.gitattributes` 保证 fresh Windows clone 不因 EOL 假 dirty；
- 当前只支持 source-checkout operation，缺 migrations 的运行布局明确报 unsupported；无真实 wheel consumer 前不做 installer/package-resource 工程。

PR B 在 #96 contract 合入后把 status/limit 接入同一 runner。不得增加 DAG/scheduler/catalog/第二持久化平面。

### P0-C — Issue #95 / PR #96：历史 status/limit Canonical 收尾

状态：**78/78 capture reconciled / real 16 GiB Canonical memory boundary confirmed / isolated finalization lane**。

已完成：

- 16 COMPLETE + 62 PARTIAL_UPSTREAM_COVERAGE；
- 每 domain 7,461,248 expected / 7,459,685 returned / 1,563 missing；
- structural / duplicate / unexplained extra = 0；
- partial missing 保持 unresolved；
- Canonical-only attempt 已真实触发 16 GiB 硬边界，Provider calls=0。

当前只做二选一：

1. 有安全资源主机（>=32 GiB physical、启动前约 28 GiB available）时，允许一次 Canonical-only finalization，约 24 GiB isolated hard stop；或
2. 无安全余量/触发 24 GiB 时，直接做窄 disk-backed/columnar selection 修复，删除全历史 Python object/list/sort copies，同时保持现有 Canonical artifacts/hash/seal/replay contract。

不再重复 16 GiB 尝试，不重采 Provider，不重写 Canonical。#95 不阻塞 #97/#98。

### P1 — Issue #101：研究读取分区/谓词下推

状态：**OPEN / may benchmark in parallel, does not block P0-A/B**。

目标：publication/deep-audit 继续完整验证；ordinary read 先按 manifest 选 partition/file，再 materialize，并使用 DuckDB/Polars pushdown。

基准：

- one security / one year；
- all market / one month；
- all market / one year；
- 每项记录 elapsed、peak RSS、files/partitions opened、cold/hot repeat。

不建 cache server/index service/catalog/第二 research dataset。

## 外部审计 PR #99

状态：**advisory record accepted / implementation routed elsewhere**。

- 审计 PR 只保留报告、evidence、reproducer；
- 不把 production fix 混进 PR #99；
- synthetic evidence 不扩大为真实 retained-history contamination 结论；
- normal checks 通过后可作为审计记录合并。

## 当前授权边界

已批准 Issue 范围内，开发可自主执行 Provider fetch/refetch/retry/replay、bounded targeted probe、一致性验证和缺失本地证据重采，不需逐次授权。

仍需项目级授权：市场/日期/业务域扩张、新外部数据源、破坏 accepted sealed history、核心 research contract/split 改变、capability promotion、Formal Production、明显大型架构重建。

## 当前禁止的等待链

- #97 不等 #95；
- #98 PR A 不等 #95/#96；
- #101 benchmark 不得拖慢 #97/#98；
- PR #99 不成为新的 gate；
- wheel packaging、strict decision-time PIT、total-return accounting、index/industry/BSE/minute 不抢当前主线。

## 下一次调度检查重点

1. PR #100 是否吸收 OHLC>0、PIT wording、reference-return naming，并 exact-head CI 通过；
2. #98 是否已经出现 tracked runner PR A，并落实 retry/EOL/fresh-clone 三个窄修复；
3. #96 是完成一次安全 higher-resource finalization，还是已进入 narrow disk-backed selection 修复；
4. #101 是否给出真实 retained/representative read baseline，而不是只给 synthetic microbench；
5. PR #99 是否保持纯审计记录并完成正常合并；
6. 是否新增了无具体风险收益的审批、治理层或框架；发现即删除/合并。