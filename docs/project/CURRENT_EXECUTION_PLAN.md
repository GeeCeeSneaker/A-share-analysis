# Current Execution Plan

本页只保留当前 P0、接下来三项工作和明确阻塞。详细验收标准以 GitHub Issue / PR 为准，长期优先级见 [`IMPLEMENTATION_ROADMAP_20260925.md`](IMPLEMENTATION_ROADMAP_20260925.md)；SHA、CI 历史和临时调度留言留在 GitHub。

## 活跃 P0

- **#97 / PR #100 — 研究价格与收益语义：ACTIVE。** 核心 reference-price linked-chain 实现 PR 已打开；exact-head Windows/Ubuntu CI 待完成。代表性真实日线 corporate-action 对照尚缺；合成测试不冒充真实数据验收。IPO/no-limit 和长停牌规则如缺少受治理输入，继续保持禁用并单独记阻塞。
- **#98 — tracked 日增量 runner：ACTIVE。** PR A 的 runner、`ashare update --through <date>`、幂等性、单位检查和外审提出的 retry/EOL/source-checkout 修复正在本地实现。真实五日 Provider 验收未完成。归档/异地副本巡检、恢复 smoke、README 入口和旧 GT-H3B workflow 清理是核心 PR A 之后的小型 follow-up，不得延迟 PR A。
- **#95 / PR #96 — 历史 status + limit Canonical 收尾：ACTIVE / 独立资源车道。** 78 个月 denominator 已完成，partial 月份仍有未解决键，不能发布为完整事实。Canonical-only 尝试已在 16 GiB 触发真实 RSS 硬门槛且没有生成成功 Canonical 结果；不得重复相同资源尝试。仅在主机至少 32 GiB 物理内存且启动前约 28 GiB 可用时，才可按 issue 指令做一次隔离的更高资源尝试；否则走窄 disk-backed/columnar selection 修复。该项不阻塞 #97/#98。

## 接下来三项

1. **#97：**等 PR #100 exact-head CI 完成并独立审阅；保持真实 corporate-action 对照缺口可见，不以此推迟合成语义修复的审阅。
2. **#98：**从当前 main 收尾并提交 PR A；核心代码可审后再追加归档/恢复 smoke、操作文档和旧 workflow 清理。恢复已接受的 2026-06 日线 Snapshot 与配套证据后，完成之后连续五个交易日、60/00/30/688 VWAP 单位检查、同目标无 Provider 重跑及异地归档校验。
3. **#95：**按上述内存决策执行唯一允许的路径；未核清 missing expected pairs 前不做 Canonical publication。

## 阻塞与决定

- **#98 实时验收：**当前干净 worktree 不含 `data/db/atlas.duckdb`、已接受的 2026-06 日线 Snapshot 或对应 raw/normalized 基线。需要恢复原接受状态及证据；fake-provider 五日测试只验证代码路径，不能替代真实验收，也不能把新抓取数据冒充旧 baseline。
- **#98 PR B：**等 PR #96 的 status/limit contract 合并后再接入；不阻塞 PR A。
- **#95：**按 expected-pair applicability 核清未解决键；不得放宽 denominator、填补缺失值或把缺失解释为负面事实。Canonical 内存决策遵从该 issue 最新 checkpoint。
- **异地备份配置：**将 `ASHARE_EVIDENCE_BACKUP_ROOT` 指向独立网络共享/远端根。代码校验它不与主 `data_root` 重叠并检查归档、收据和校验和；它不能单凭本机路径证明存储介质确实位于另一台机器。
- **P1 #101 — partition-aware read：**可并行基准，但不阻塞 #97/#98；需要用可用 retained/representative data 记录窄读与全市场读的时间、峰值内存和实际打开分区数。

当前不做策略回测、BSE、分钟数据或 Formal B1-B7 / Production。
