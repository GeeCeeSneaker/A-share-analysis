# A-share-analysis 外审吸收与架构优化实施方案

> 状态：**PM DECISION / REMEDIATE / TARGET ARCHITECTURE ACCEPTED, IMPLEMENTATION PHASED**  
> 日期：2026-09-23  
> 基线：PR #77 external-review head `edf539f7fdccd948cda24b5da7d017033af1ce90`  
> 适用范围：A-share-analysis 日线数据基座、后续 1 分钟数据、量化研究消费层  
> 原则：最小化、PIT 正确、单一事实面、列式/批处理、日增量、分钟级不换架构

---

## 1. PM 结论

外审没有推翻当前重审方向，反而强化了核心判断：

1. `Parquet + DuckDB` 不是当前资源问题的根因；
2. 原 `Canonical -> physical Snapshot -> physical ReadModel -> full Python projection` 的重复事实副本和 eager Python object 化必须退出主架构；
3. Canonical 应成为唯一权威市场事实面；
4. Snapshot 应逻辑化为 exact partition/version manifest；
5. ReadModel 应成为 DuckDB analytical/query facade，而不是第四份历史数据；
6. Research/Feature 只在增加稳定研究语义时物化；
7. 1d 与 1m 必须共用同一治理、identity、PIT、manifest、query 和 incremental model；
8. 分钟级物理布局必须由 synthetic benchmark 决定，而不是先拍 bucket/file/row-group 参数；
9. 数据平台正常资源复杂度必须与 total history 解耦。

因此总体 disposition：**REMEDIATE，不再优化旧复制架构；进入“契约冻结 -> synthetic benchmark -> daily 最小重构 -> Issue #76 迁移收口 -> minute enablement”的新路线。**

---

## 2. 外审建议的裁决

### 2.1 立即接受

| 外审建议 | PM 裁决 |
|---|---|
| Canonical 单一权威事实面 | ACCEPT |
| Snapshot 逻辑 manifest，不复制事实 | ACCEPT |
| DuckDB external scan/query facade | ACCEPT |
| 删除 full-history `fetchall/list[dict]/projected list` 热路径 | ACCEPT |
| producer boundary 重验证，ordinary read 轻量消费 seal | ACCEPT |
| deep audit 显式、批量、有界、非 hot path | ACCEPT |
| lineage 大量上移 partition/batch manifest | ACCEPT |
| logical data identity 与 physical artifact identity 分离 | ACCEPT，升级为核心 contract |
| fingerprint 只绑定 output-affecting semantics | ACCEPT |
| daily steady state 只处理 new day / open month | ACCEPT |
| synthetic minute benchmark 前置 | ACCEPT |
| future feature/factor 需要 version + source snapshot + warmup | ACCEPT |
| holdout 之后增量数据不能隐式流入 Development | ACCEPT，立即补 contract |

### 2.2 接受目标，但不直接照抄实现

#### A. `security_id -> INT64 surrogate`

外审建议在 1m fact 中使用 INT64 surrogate。目标（降低 2B rows 上 UUID/string 的存储和 join 成本）成立，但**现在不直接引入 surrogate mapping 层**。

先 benchmark 三种表示：

1. 当前 stable UUID string；
2. UUID / fixed 16-byte binary；
3. INT64 surrogate + small identity dimension。

只有 3 相比 2 有显著 storage/query 收益，且 mapping complexity 可控，才采用 surrogate。治理层 stable `security_id` 仍保持 UUID，不改变业务身份模型。

#### B. `Normalized 全部 transient`

不做 blanket deletion。

新规则：**Normalized 不是必须长期存在的“完整事实层”，是否持久化按 dataset 决定。**

- 大体量 bar 类：默认 transient/rebuildable；Raw 可 replay、Canonical 已 sealed 后不保留完整第二份事实副本；
- 小型且承担身份/PIT/诊断职责的 dimension（如 security master）：可以 durable；
- 是否保留必须有具体消费者，不能因为“分层完整”而保留。

#### C. minute `16/32 bucket`、固定 file size/row-group

全部降级为 benchmark candidate，不进入 contract 常量。

先比较：

- L0：month，无 security bucket，time-first sort；
- L1：month + 16 stable security buckets，time-first sort；
- L2：month + 16 stable security buckets，security-first sort。

只有实测显示 file size/query pruning 不足，才追加 32 bucket 方案。避免组合爆炸。

#### D. numeric type

外审建议 price Float64、volume Int64、amount Int64(分)。**不直接冻结，先以 AmazingData 实际字段语义与 retained evidence 验证是否 lossless。**

原则先冻结：

- Canonical numeric interpretation 必须唯一；
- volume 若源语义为整数则 Int64；
- amount 只有在可无损映射固定 scale 时才使用 scaled Int64，否则选择明确 Decimal/Float contract；
- unadjusted Canonical 不因 research 复权改写。

### 2.3 当前不采用 / 后置

- Iceberg / Delta：不引入；出现多 writer、object-store/multi-node、频繁 correction/time-travel、manifest transaction complexity 明显上升时再评估；
- ClickHouse：不引入；高并发低延迟 serving、盘中实时 ingest 或 DuckDB 实测不足时再评估；
- Spark/Ray：不引入；单机 bounded pipeline 实测无法完成才评估；
- Linux/PVE/WSL 强制迁移：不作为当前 P0；minute benchmark 同时比较可用运行环境后再决定；若使用 WSL，数据不得落 `/mnt/c`；
- Bloom filter / 多级 cache / generic streaming framework：没有实测需求前不做。

---

## 3. 最终目标数据架构

~~~text
AmazingData
    |
    v
Raw Evidence  --------------------------+
    |                                   |
    | typed normalization               | replay/audit
    v                                   |
Canonical Fact Partitions <-------------+
    |
    +-- partition manifest
    |
    v
Logical Snapshot Manifest
    |
    v
DuckDB Query Facade (external Parquet scan)
    |
    +--> Arrow / DuckDB Relation / Polars Lazy
    |
    +--> Research / Feature materialization (only when valuable)
~~~

### 3.1 Raw

保留外部输入事实、scope、retrieval、raw hash、replay 能力。

分钟级 Raw 的长期 retention 先采用：

- hot / current evidence 保留本地；
- closed/verified evidence 可压缩冷归档；
- 不因存储优化删除尚不能由 sealed Canonical + policy 重建/审计的唯一事实；
- actual compression ratio 在 minute probe 后再定容量策略。

### 3.2 Normalization

作为 transformation boundary，而不是默认第二套 data lake。

### 3.3 Canonical

唯一 durable market fact plane。

至少包括：

- `security_bar_1d`；
- `security_bar_1m`（后续）；
- security master / identity dimension；
- trade calendar；
- suspension/lifecycle/corporate-action 必要 dimensions。

Canonical 始终保存 unadjusted market truth；adjusted series 属于 Research/Feature。

### 3.4 Snapshot

Snapshot = exact logical data version。

不保存事实 row，只引用：

- logical partition id；
- data revision；
- logical content hash；
- physical artifact set / layout revision；
- artifact URI/content hash/schema/row count/time bounds；
- identity/calendar/corporate-action dimension versions；
- as-of / PIT contract。

创建 snapshot 应是 metadata operation。

### 3.5 ReadModel

保留 ReadModel 作为 API/逻辑概念，但不再作为完整历史事实副本。

DuckDB 根据 Snapshot manifest 建 view/relation，直接扫描 exact Parquet artifact set。

small dimensions 可物理装入 session/local DuckDB；fact history 不重复 INSERT。

### 3.6 Research / Feature

只暴露 columnar/lazy interface：

- DuckDB Relation；
- Arrow batch/table；
- Polars LazyFrame。

禁止生产路径使用全历史 row iterator / `fetchall -> list[dict]`。

Feature dataset 最少声明：

- factor/feature version；
- source snapshot/version；
- source partitions；
- warmup/lookback；
- output partitions；
- invalidation scope。

不构建通用 dependency DAG；partition-level dependency metadata 足够。

---

## 4. 必须先冻结的最小 Contracts（A0）

A0 是当前唯一允许先行的架构任务。它是“小合同”，不是新框架。

### C1. Bar Time Semantics v1

日线与分钟统一使用“事件时间”和“可用时间”两类时间，不混淆 provenance retrieval time。

分钟 canonical 语义目标：

- regular 1m bar 表示半开区间 `[bar_start, bar_end)`；
- row key 使用 `security_id + bar_start`；
- 存储一个无歧义 UTC instant，同时保留/可派生 China local `trade_date`；
- auction / lunch / close 的 provider 行为必须通过 AmazingData 小样本实测后写入 contract；
- missing bar、zero-volume bar、suspension 三者严格区分；
- 不制造假 0-volume bar 来填洞。

**重要修正：不要把 `retrieved_at` 直接等同于研究 PIT 的 `available_at`。**

应至少区分：

- `event_time` / bar interval；
- `market_available_at`（该 bar 在市场语义上可知的最早时间，规则必须显式）；
- `retrieved_at`（本项目实际从 provider 获取的时间，属于 provenance）。

否则历史 API 在 2026 年重新取得 2020 数据会错误地使 2020 bar “直到 2026 才可用”。现有 daily PIT 规则迁移时必须特别抽检这一点。

### C2. Numeric Semantics v1

先通过 retained daily evidence + 一个 minute provider shape probe 确认：

- source price precision；
- volume unit/整数性；
- amount unit/scale；
- null/zero semantics；
- auction/partial-minute 数值规则。

再冻结物理 dtype。

### C3. Partition / Revision v1

区分四个概念：

1. **logical_partition_id**：dataset + logical month；
2. **data_revision**：logical rows 真正变化才改变；
3. **logical_content_hash**：对确定排序的 canonical row stream 在 producer boundary 一次计算；
4. **layout_revision / artifact_set_hash**：compaction、file split/merge 等 physical layout 改变。

因此：

- physical compaction 可以改变 file/content hashes；
- logical rows 未变时 `logical_content_hash` 和 `data_revision` 不变；
- Research/Feature 不应仅因 compaction 被 invalidated。

### C4. Integrity v1

Producer boundary：

- schema；
- key uniqueness；
- PIT；
- completeness；
- deterministic logical ordering；
- artifact content hash；
- logical content hash；
- atomic manifest publication。

Ordinary read：

- validate manifest/version/schema/partition selection；
- 不每次重新 SHA 全量大文件；
- 不每次重算 global semantic sort。

Deep audit / scrub：

- explicit command；
- bounded batch；
- 可全量扫描；
- 独立于 ordinary research open。

### C5. Lineage Placement v1

Fact row 只保留真正 row-varying 且查询/诊断需要的字段。

Partition/batch constant 上移 manifest：provider、request/run、raw evidence、mapper、contract、policy、PIT basis、schema/artifact seals 等。

`source_row_identity_hash` 不默认进入 1m fact；如果唯一 row key + partition manifest 已能精确 replay，就删除。

### C6. Identity Key Representation

不改变 stable UUID `security_id` 的治理语义。

physical representation 由 A1 benchmark 在 fixed UUID/binary UUID/INT64 surrogate 中选择。

### C7. Research Split v2

现有 Development / Validation A / Holdout 边界保持 immutable。

新增：

- `POST_HOLDOUT` / `FORWARD_MONITORING`：`2026-07-01` 之后新增数据默认进入此区；
- 不自动滚动 Development/Holdout；
- 新研究周期必须 mint 新 split-policy version，经明确审阅后才改变训练/验证窗口。

这样 2026-07 以后日增量不会形成隐式 look-ahead / holdout 污染。

### C8. Correction / Compaction v1

不允许改写已 committed closed artifact bytes。

- duplicate replay：logical + physical content 相同 -> no-op；
- open-month correction：新 fragment/partition version + manifest switch；
- closed historical revision：新 `data_revision`，旧版本保留到 retention policy 清理；
- layout-only compaction：只改变 `layout_revision`，logical identity 不变。

---

## 5. Synthetic Minute Architecture Benchmark（A1，前置）

目的不是做 performance framework，而是用一次可复现实验决定物理布局。

### 5.1 数据规模

至少：

- 1 个 full-market 1m trading day：~1M–1.3M rows；
- 1 个完整 open-month shape：~20M–30M rows；
- 可通过复用统计分布生成第二个 closed-month，用于验证“历史长度不影响 daily append”。

不需要先造 2B rows。

### 5.2 只比较三个候选布局

- **L0**：month / no bucket / time-first sort；
- **L1**：month + 16 stable security bucket / time-first sort；
- **L2**：month + 16 stable security bucket / security-first sort。

32 buckets 只在 L1/L2 实测 file/query 明显不足时追加。

### 5.3 key representation 同场比较

- UUID string；
- fixed/native UUID；
- INT64 surrogate。

测 storage、join、filter、complexity。

### 5.4 Workloads

- W1：单日 ingest；
- W2：连续 5 日 append / outage catch-up；
- W3：open month -> month-close compaction；
- W4：单分钟全市场横截面；
- W5：单证券多年 equivalent scan；
- W6：100/500 security universe range；
- W7：resample / rolling / groupby；
- W8：identity dimension join；
- W9：compaction 同时执行 W6，观察 I/O contention。

### 5.5 记录指标

- peak RSS；
- elapsed；
- CPU；
- bytes read/written；
- spill；
- file count；
- files/row-groups touched；
- compression bytes/row。

### 5.6 资源 Gate

这些是架构 gate，不是最终跨硬件 SLA：

- daily ingest peak RSS：目标 `<2 GiB`；
- month compaction peak RSS：目标 `<4 GiB`，不得随 total history 增长；
- 6 months vs 6 years equivalent daily append：peak RSS / touched closed files 应基本不变；
- closed months rewritten：`0`；
- Snapshot/ReadModel full fact copies：`0`。

query elapsed 记录为 baseline，不在未确定硬件/布局前设置过强绝对 SLA。

---

## 6. Daily 最小重构（B）

只有 A0 contracts + A1 benchmark 完成后，才进入 product refactor。

### B1. Canonical partitioned truth

以 `daily_bar` 为第一条迁移域：

- monthly logical partition；
- closed immutable；
- partition manifest；
- logical content identity；
- 不要求长期完整 Normalized duplicate。

### B2. Logical Snapshot

替换 physical Snapshot data copy。

### B3. DuckDB query facade

替换 full physical ReadModel copy。

### B4. Lazy Research boundary

替换 `fetchall/list[dict]/full projected list`。

### B5. Delete old duplicate paths

本任务是 simplification，验收要求 **生产代码 + 测试代码净简化**。

至少删除/退役：

- full fact Snapshot payload path；
- full-history ReadModel rebuild copy path；
- whole-history research Python projection；
- ordinary-read recursive deep audit；
- verifier implementation source 进入 durable data identity 的逻辑。

不保留“两套都能跑”的长期兼容层。

---

## 7. Issue #76 78 月迁移收口（C）

Issue #76 已有 retained evidence 是资产，不重新获取 provider。

**provider_calls = 0**。

### C1. 先抽检语义

选择至少：

- 2020-01；
- 2024-01；
- 2026-01；
- 含 300114/302132 transition 的月份；
- 含 suspension/list/delist edge case 的月份。

确认旧 retained evidence 的 PIT/available/retrieval 语义可以映射到 C1–C8 新 contract，不能“只换 manifest 外壳”。

### C2. 迁移

从 retained Raw/verified facts 生成 78 个 authoritative daily logical partitions，logical Snapshot 和 DuckDB query facade。

### C3. Final acceptance

- 78/78 partition completeness；
- zero unresolved；
- no duplicate/missing month；
- exact logical content proof；
- ordinary reader/query proof；
- idempotent replay/resume；
- changed logical content conflict/revision behavior；
- closed-month immutability；
- daily append complexity independent of total history；
- no full Snapshot/ReadModel fact copy；
- exact-head QA/CI green。

旧 `<16 GiB M1` 不再作为架构目标；新 daily path 应远低于该数量级。

---

## 8. Minute Enablement（D）

只有 daily simplified path 与 synthetic benchmark 均 PASS 才开始真实 1m。

顺序：

1. AmazingData minute shape/time/numeric bounded probe；
2. 1 个真实 trading day；
3. 5-day catch-up；
4. 1 open month；
5. month-close compaction；
6. correction/revision exercise；
7. 扩大历史 backfill。

不先发起数年分钟回填再调 architecture。

---

## 9. Hardware / Runtime Decision

### 当前规划

- 平台本体设计必须能在 32 GB RAM 正常运行；
- 64 GB 为推荐研究工作站容量，不作为 correctness 依赖；
- minute history：2 TB NVMe 最低规划，4 TB 更舒适；
- data 与 temp/spill 分盘有潜在收益，但在 W9 实测后决定；
- GPU 不是数据平台依赖。

### OS

Windows 不因当前架构问题被否定。

在 minute benchmark 阶段，同 workload 对比当前 Windows 与候选 Linux/PVE/WSL 环境的 I/O、spill、crash/recovery；只有实测和长期运维收益足够再迁正式节点。

---

## 10. 技术升级触发条件

### Iceberg/Delta

满足实际需求再评估：

- 多 writer / 多机共享事实面；
- object storage 成为主要数据面；
- correction/time-travel 需求频繁；
- 自有 manifest transaction/compaction 代码开始明显复制成熟 table-format 功能；
- file/partition metadata 管理成为瓶颈。

不采用“代码超过某个 LOC”或“出现第 N 个 bug”作为机械触发器。

### ClickHouse

出现以下 workload 再评估：

- 高频并发交互式 serving；
- 盘中实时流 ingest；
- DuckDB + Parquet 在真实目标 query benchmark 中持续无法满足研究体验。

### Distributed compute

只有单机 columnar pipeline 已做到 bounded、pruned、spill-friendly 后仍不足，才评估 Spark/Ray 等。

---

## 11. 控制面与执行顺序

新的唯一顺序：

~~~text
A0 contract freeze
  -> A1 synthetic minute benchmark
  -> B daily data-plane simplification
  -> C Issue #76 retained 78-month migration/closure
  -> D real minute enablement
  -> E feature/strategy-facing expansion
~~~

任何开发任务如果不直接服务当前阶段，不进入当前 P0。

PR #77 继续作为 Issue #76 历史 evidence / architecture-review branch，保持 Draft；不在这个已经很大的 PR 中无限堆叠完整新架构实现。

建议另开一个明确的架构优化 P0 Issue，先完成 A0/A1；Issue #76 标记为“blocked by architecture gate”，retained evidence 原样保留。A0/A1 PASS 后，再决定 daily refactor 的独立实现 PR 拆分。

---

## 12. 当前第一批可执行任务

### Task A0-1 — contracts

只写 5 份小型 contract / ADR（可以合并成 1–2 个 Markdown，避免文档泛滥）：

- time / available / retrieval semantics；
- numeric semantics；
- logical partition + data/layout revision；
- lineage placement + integrity；
- research split post-holdout policy。

### Task A0-2 — existing-schema inventory

列出当前 daily row 中：

- row-varying；
- partition-constant；
- redundant lineage；
- future minute 不应逐行保存的字段。

### Task A1-1 — one disposable benchmark runner

只生成 synthetic minute Parquet + 执行 L0/L1/L2 + W1–W9，输出一个 JSON + Markdown summary。

不要构建 benchmark framework。

### Task A1-2 — decision record

根据数据选择：

- partition layout；
- sort key；
- bucket count（含 no-bucket）；
- target file/row-group；
- physical security key representation；
- Windows/Linux runtime decision是否需要现在做。

完成后才能授权 B。

---

## 13. PM 最终裁决

外审的最大价值不是提供一组“标准答案”，而是确认我们已经找到真正的系统性问题，并指出少数现在必须冻结的 contract。

下一步不应继续优化旧 M1/M2/M3，也不应立即大规模重写。

**正确动作是先用最小 contracts 固定语义，再用一个 realistic minute benchmark 决定物理布局，然后只重构 daily_bar 一条纵向链路并删除旧重复层。**

如果这一条纵向链在 78 月日线和 synthetic 1m 上都通过，再扩展其他 domain。这样同时满足：

- 资源有界；
- 逻辑复杂度下降；
- 量化研究效率；
- 分钟级不换平台；
- 最小迁移风险；
- 不因专家建议重新引入未经实测的过早优化。
