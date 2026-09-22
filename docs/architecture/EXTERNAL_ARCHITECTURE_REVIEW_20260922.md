# A-share-analysis 数据基座技术架构外部审阅材料

> 状态：**FOR EXTERNAL REVIEW / 架构重审中 / 非最终冻结设计**  
> 日期：2026-09-22  
> 审阅对象：A-share-analysis 数据基座及其面向量化研究的长期数据架构  
> 当前开发分支：PR #77 / issue76/history-build-20260916  
> 当前控制事项：Issue #76  
> 目的：邀请外部数据工程、量化研究基础设施、列式存储、DuckDB/Parquet、证券数据治理专家，对本项目的功能目标、数据模型、技术选型、资源模型、分钟级扩展能力和复杂度控制进行独立审阅，并提出可执行的优化建议。

---

## 1. 外审希望回答的核心问题

本次外审不是要求专家仅检查某段代码，而是希望对系统的长期技术路线进行挑战性审阅。

请重点判断：

1. 当前拟采用的 **Parquet + DuckDB + Manifest/Ledger** 单机列式架构，是否能够在不更换核心架构的情况下，从当前日线扩展到全市场 1 分钟级历史和日增量数据。
2. 是否存在我们仍然没有发现的重复数据层、重复验证、重复物化或不必要的工程复杂度。
3. 当前提出的“Canonical 为唯一权威事实层、Snapshot 逻辑化、ReadModel 查询化”的方向是否正确；是否存在数据一致性、PIT、审计或研究效率方面的缺口。
4. 分钟级数据的物理分区、文件大小、排序、security bucket、开放月碎片与月末 compaction 方案应该如何设计。
5. 在典型量化研究访问模式下，DuckDB 外部扫描 Parquet 是否足够；什么规模和负载才真正需要 ClickHouse、Iceberg/Delta、Spark/Ray、对象存储或其他组件。
6. 当前资源预算是否合理，尤其是 RAM、NVMe、CPU、I/O 预算，以及初始历史回填与长期日增量的复杂度是否真正与总历史长度解耦。
7. 当前 lineage、hash、fingerprint、replay、PIT 和完整性验证机制中，哪些必须保留，哪些应进一步上移到 partition/manifest 层或删除。
8. 当前架构是否能高效支持后续因子研究、事件研究、横截面研究、时间序列研究、回测、策略组合研究和模拟/实盘结果监测。
9. 是否存在当前阶段就必须解决、否则未来迁移成本会很高的问题。

---

## 2. 系统定位

A-share-analysis 的定位不是交易终端，也不是实时撮合或下单系统，而是：

> **A 股量化研究和后续策略运行所依赖的可复现、可追溯、PIT 正确、资源可控的市场数据基座。**

系统首先解决“研究输入是否可靠、是否可重放、是否按正确时间视角使用”这一问题，然后向上提供稳定、高性能的数据消费接口。

项目生态预期为：

- **A-share-analysis**：数据获取、标准化、身份、PIT、Canonical 数据、研究数据接口和历史数据基座；
- **Quantitative-Strategy-Research**：策略研究、回测、策略比较、参数与组合研究；
- 已存在的具体策略研究（如 Strong-Trend Alpha）后续并入统一策略研究体系；
- 第一阶段不做真实交易执行；
- 后续需要支持模拟盘/实盘策略运行结果监测和评估，但数据平台不能因此变成交易执行系统。

研究原则是：先有可解释、过硬的交易逻辑，再做参数优化；数据平台不能通过事后调参或数据泄漏制造“漂亮结果”。

---

## 3. 当前功能需求目标

### 3.1 数据获取

当前 Owner 指定 AmazingData 为可信市场/历史数据源。

系统负责：

- 按明确日期、市场、证券范围调用 Provider；
- 保存必要的 Raw evidence；
- 记录 retrieval time、available-at / PIT 等时间语义；
- 对 partial、missing、schema drift、错误 scope 等情况 fail closed；
- 支持 retained evidence replay，避免为了复现重复访问 Provider；
- Provider trust 本身由 Owner 决定，代码不承担“证明 Provider 可信”的职责。

未来如果出现第二个 Owner-approved 数据源并发生真实冲突，再针对具体冲突设计 reconciliation，不提前构建通用多源仲裁系统。

### 3.2 证券身份

核心原则：

- 稳定实体使用 security_id；
- 默认业务代码采用最新有效代码；
- 历史代码仅用于 PIT / provider-history resolution；
- 同一上市实体发生纯代码变更时保持同一个 security_id；
- 历史查询可解析当时有效代码；
- 普通当前展示使用最新有效代码。

已实际验证案例：

- 300114.SZ → 302132.SZ，生效日 2025-02-17；
- 2024 历史数据仍可使用 300114.SZ 做 provider/PIT 解析；
- 当前展示和普通非 as-of 查询使用 302132.SZ；
- 两者绑定同一个 security_id。

真正的新主体、被吸收后不存在连续上市主体等情况不能强行合并，需要显式 predecessor/successor 关系。

### 3.3 日线市场数据

当前主要事实域为 A 股日线：

- trade calendar；
- security master；
- 上市/退市边界；
- 停牌状态；
- OHLCV / amount；
- available_at / PIT；
- completeness；
- data-quality / research eligibility。

当前历史建设目标为：

- 2020-01 至 2026-06；
- 共 78 个自然月；
- 全月独立完整性判断；
- 可重放、可增量、可恢复；
- 不允许跳过阻塞月份后宣称全量完成。

### 3.4 分钟级数据

系统必须从当前架构开始就为全市场 1 分钟 bar 做准备。

目标不是建设第二套“分钟平台”，而是：

- 1d 和 1m 共用同一套 Raw、身份、PIT、manifest、query、research governance；
- 物理事实数据分开；
- 后续 5m / 15m / 30m / 60m 默认从 1m 派生；
- 只有实际重复 workload 证明有必要时才新增物化频率。

初始预期不是低延迟实时流系统，而是以交易日结束后的可靠日增量为主。未来如需盘中实时研究，应作为额外需求重新评估。

### 3.5 量化研究消费

研究层需要高效支持至少两类访问：

**横截面：**

- 某日/某分钟全市场；
- 某时间区间内的大范围 universe；
- 因子截面、排序、分组、中性化等。

**时间序列：**

- 单证券多年日线/分钟线；
- 一个股票池的多年历史；
- rolling window、事件前后窗口、波动/成交等。

消费接口要求：

- 支持 date/time range；
- 支持 security_id 集合过滤；
- 支持 column projection；
- 优先使用 DuckDB SQL / Arrow / Polars Lazy/Batch；
- 禁止大历史先 fetchall 到 Python 再处理。

### 3.6 Research dataset

研究数据集可以增加业务语义，例如：

- research split；
- research eligibility；
- exclusion reason；
- data quality；
- current-code-first identity presentation；
- feature / factor output。

只有“增加稳定、可复用研究语义”的数据才值得形成新的物理派生数据集。

Snapshot、ReadModel 或普通 verifier 不应该因为方便而复制全部事实数据。

### 3.7 Research split / 防泄漏

当前日线研究窗口：

- Development：2020-01-01 ～ 2023-12-31；
- Validation A：2024-01-01 ～ 2025-12-31；
- Holdout：2026-01-01 ～ 2026-06-30。

Holdout 不应被普通 Development 研究入口隐式混入。

所有 feature、身份、可用性、公司行动信息均需满足 PIT 语义，禁止 future knowledge 污染历史研究。

### 3.8 增量运行

历史 backfill 完成以后，正常运行节奏必须是：

- 每个交易日只采集新增交易日；
- provider/network work 应接近 O(new day)；
- downstream 工作量应接近 O(new day)，最坏 O(current open month)；
- closed months 不重新投影、不重写；
- outage 后从最新 verified boundary 做小范围 catch-up；
- 历史 correction 只影响相应逻辑分区及真正依赖它的 downstream 数据。

### 3.9 可靠性

必须保留：

- partial/missing fail closed；
- schema validation；
- PIT；
- deterministic identity；
- immutable closed history；
- atomic publication；
- idempotent replay；
- changed-content conflict；
- retained evidence；
- crash/resume；
- secrets 不进入 GitHub；
- 原始 Provider 数据按需要保存在本地 evidence store。

---

## 4. 明确不希望建设的东西

在没有实测需求以前，不希望引入：

- Spark；
- Ray；
- Hadoop；
- Kafka；
- Redis/cache service；
- ClickHouse 集群；
- 独立分布式 scheduler；
- 通用 event sourcing 平台；
- 通用 corporate-action engine；
- speculative multi-source reconciliation；
- 为内部可信调用者设计的 anti-forgery object machinery；
- 过多 adapter / receipt / sidecar / wrapper 链。

项目原则是：

> smallest design satisfying business purpose, correctness and basic operational safety。

每一个长期机制都应该能明确回答：

- 它防止了哪个真实失败？
- 为什么已有 boundary / manifest / convention 不能解决？

---

## 5. 当前实现已经暴露出的架构问题

历史代码形成过以下链路：

~~~text
Raw
  ↓
Normalized
  ↓
Canonical
  ↓ physical copy
Snapshot
  ↓ physical copy
DuckDB ReadModel
  ↓ full Python projection
ResearchProjection
  ↓
Historical Materialization
~~~

这条路径在日线 2020-2026H1 构建中暴露出严重的内存放大。

实际观察过的峰值包括：

- 约 46.7 GiB：Snapshot/ReadModel 路径存在多套全量 Python row representation；
- 约 46.5 GiB：ResearchPanelBuilder.prepare_verified_projection 同时保留 source rows 和 projected rows；
- 约 38.5 GiB：ReadModel 全量逻辑验证仍在进行；
- 第一轮 bounded hash 优化后仍约 22.268 GiB；
- 后续 sealed snapshot handoff 消除了部分重复路径，但旧 snapshot fingerprint 与当前代码不兼容，新的真实 RSS 尚未完成有效测量。

这些数字可以由当前实现解释，但**不被认为是业务规模天然要求**。

主要放大来源：

1. Parquet → DataFrame → list[dict] / tuple；
2. 再生成另一套 projected list；
3. 为 semantic hash 再生成字符串表示并排序；
4. Snapshot 再写完整事实副本；
5. DuckDB 再复制完整事实；
6. Research 再全量 fetchall；
7. Historical materializer 再分组/复制/序列化。

另一个已暴露问题是：

- snapshot builder fingerprint 曾包含 canonical verifier 模块源码；
- verifier 的性能实现变化导致旧 snapshot 被认定为不同 builder version；
- 数据语义未变化，却要求重建历史 snapshot。

这说明当前 fingerprint 绑定粒度过细。

因此当前已明确：

> 不再以“把旧架构压到 16 GiB 以下”作为目标，而是消除不必要的物理复制和全历史工作。

---

## 6. 当前拟确定的目标架构

### 6.1 总体数据流

目标架构：

~~~text
Provider
   ↓
Raw Evidence
   ↓
Normalization
   ↓
Canonical Columnar Fact Partitions
   ↓
Logical Snapshot Manifest
   ↓
DuckDB Query Facade
   ↓
Research / Feature / Strategy Consumers
~~~

其中：

- Raw 有自己的必要 retained evidence；
- Canonical 是唯一权威市场事实数据面；
- Snapshot 不保存第二份事实；
- ReadModel 不保存第三份事实；
- Research/Feature 只有在增加稳定业务语义时才允许派生物化。

### 6.2 Raw

职责：

- 保存精确 request scope；
- 保存可复放 Provider evidence；
- hash/size/schema/shape；
- retrieval timestamp；
- 对 provider SDK 输出做可靠落盘。

Raw 不面向策略研究查询。

分钟级 Raw 可能成为显著存储来源，因此需要专家审查：

- retention 是否永久；
- 是否应该保留原始每-request bytes，还是在 verified normalization 后归档/压缩；
- 是否需要冷热分层；
- 是否存在许可证/数据使用约束。

### 6.3 Normalized

职责：

- Provider-native shape → 稳定内部 typed schema；
- 不加入研究语义；
- 保留必要 source binding；
- 为 Canonical 提供稳定输入。

需要审查 Normalized 与 Canonical 是否有进一步合并空间，避免成为长期完整数据副本。

### 6.4 Canonical

Canonical 应成为权威列式事实层。

拟采用数据集：

- security_bar_1d；
- security_bar_1m；
- security_master；
- trade_calendar；
- status / lifecycle / necessary dimensions。

Canonical fact 应尽量保持“窄”。

尤其在分钟级，不应在每个 bar 上重复保存几十个分区级 lineage 字符串和 hash。

建议把 partition-constant 信息提升至 manifest，例如：

- provider；
- source run；
- raw evidence hash；
- mapper；
- contract version；
- source policy；
- acquisition receipt；
- PIT boundary；
- schema hash；
- content hash；
- row count。

行级只保留真正逐行变化或必要定位的信息。

### 6.5 Snapshot

Snapshot 应是逻辑 point-in-time view，而不是事实副本。

概念结构：

~~~text
snapshot_id
as_of
identity_version
canonical_contract
datasets:
  security_bar_1d:
    partitions [...]
  security_bar_1m:
    partitions [...]
dimensions:
  security_master: exact version
  calendar: exact version
~~~

每个 partition reference 至少包含：

- logical partition；
- artifact URI；
- content hash；
- schema version/hash；
- row count；
- min/max time；
- data version；
- necessary semantic seal。

创建一个 Snapshot 应主要是 metadata 操作，而不是再复制数亿/数十亿行。

### 6.6 ReadModel

ReadModel 的目标定义调整为：

> DuckDB analytical/query facade over exact Parquet files named by a verified Snapshot。

事实数据不再 INSERT 成另一份完整 DuckDB 文件。

DuckDB 负责：

- read_parquet；
- view；
- projection pushdown；
- predicate pushdown；
- partition pruning；
- join；
- aggregation；
- sorting；
- spill-to-disk。

小维表可以加载进 DuckDB，例如 security identity/calendar。

需要专家确认：

- 使用 persistent DuckDB catalog view 还是每 research session 建立轻量 temporary views；
- metadata DB 与 analytical query process 如何隔离；
- Windows/Linux 对 external Parquet scan 和多 reader 行为的影响。

### 6.7 Research

Research 层通过稳定逻辑接口读取 Snapshot/Canonical，而不是认识具体文件布局。

例如逻辑上：

~~~text
bars_1d
bars_1m
security_master
trading_calendar
~~~

API 或 SQL 必须支持：

- range；
- universe/security filter；
- selected columns；
- lazy/batch；
- Arrow/Polars interop。

禁止：

~~~text
all history → fetchall → Python list[dict] → second list → research
~~~

### 6.8 Feature / Factor

Feature 是合理的派生物化，但需要满足：

- 声明 source partition/version；
- 声明 feature contract；
- 声明 warmup window；
- 按时间 partition；
- incremental；
- 只 invalidates 必要时间范围。

例如新增一个交易日，不应默认重算六年历史。

---

## 7. 日线与分钟线统一设计

### 7.1 数据量级

按约 5,000 只证券估算：

**日线：**

- 约 5,000 bars / trading day；
- 约 1.25M rows / year；
- 6.5 年约 8M rows。

**1 分钟：**

- 约 240 regular-session bars / security / day；
- 约 1.2M rows / trading day；
- 约 300M rows / year；
- 6.5 年约 1.9B rows。

实际数量受上市日期、停牌、交易日、auction/bar definition、BSE coverage 等影响。

因此分钟级不能使用全历史 Python object materialization。

### 7.2 时间语义需要提前固定

分钟级需要外审重点检查：

- bar_time 表示开始时间还是结束时间；
- China Standard Time / UTC 的存储和 API 表示；
- 09:15–09:25 集合竞价如何表示；
- 09:30 第一根 bar 的边界；
- 午休；
- 收盘集合竞价；
- 停牌证券是否产生 0-volume bar；
- provider 返回缺失 minute 与“没有交易”的区别；
- available_at 是 bar close、provider publication time 还是 retrieval time；
- future knowledge / late correction 的 PIT 处理。

这些语义一旦做错，后面所有分钟因子都会受到影响。

### 7.3 物理分区

当前建议：

**开放月份：**

- 每个交易日写一个或少量 bounded fragment；
- 只追加新日；
- 不重写 closed month；
- fragment 可按 size/bucket 控制。

**月末：**

- 对当月做一次 compaction；
- 生成少量大 Parquet；
- manifest 原子切换到 compacted version；
- 原 fragments 可归档/删除，具体 retention 待审查。

不建议永久 one-file-per-security-per-day，也不建议一个月只形成一个极大的不可 pruning 文件。

### 7.4 security bucket

可能方案：

- month partition；
- month 内按 stable hash(security_id) 分 bucket；
- bucket 内按 bar_time / security_id 排序，或反向排序策略；
- 利用 Parquet row-group min/max statistics。

目标同时支持：

- 某时间点全市场；
- 某 universe 多日；
- 单证券多年；
- 某股票池多年。

bucket 数不能凭感觉固定，应该以 benchmark 选择。

请专家特别评估：

- month + security hash bucket 是否优于 date partition；
- 是否应该按 exchange/security_id range；
- row group 大小；
- target Parquet file size；
- sorting key；
- bloom filter 是否有实际收益。

### 7.5 Compaction

Compaction 必须：

- bounded memory；
- atomic manifest publish；
- logical row truth 不变；
- content/hash/version 可验证；
- crash 不产生半发布；
- closed partition immutable。

需要审查 plain Parquet + manifest 是否足够，还是从分钟级 correction/compaction 复杂度看应引入 Iceberg/Delta 类 table format。

当前倾向是暂不引入，除非外审或 benchmark 表明确显示自建 manifest 会承担过多 table-management 复杂度。

---

## 8. Lineage 与数据治理

### 8.1 当前问题

当前日线 schema 有不少 lineage 字段逐行保存，例如：

- source raw request；
- evidence hash；
- mapper；
- source policy；
- contract；
- run id；
- snapshot id。

日线规模尚能承受，但 1.9B minute rows 时可能造成显著：

- storage amplification；
- dictionary/page overhead；
- memory；
- hashing；
- scan cost。

### 8.2 当前建议

把 lineage 分为：

**Row-varying：**

真正随 bar 变化、且必须逐行定位的字段。

**Partition-constant / batch-constant：**

提升到 manifest。

Row 可以通过：

~~~text
dataset version + partition identity + row key
~~~

回溯到完整 lineage。

请专家评估：

- 哪些 lineage 必须逐 row；
- 是否保留 source_row_identity_hash；
- security_id 是否应使用 UUID string、DuckDB UUID、16-byte binary 或内部 surrogate key；
- 对 research/debug 可用性的影响。

---

## 9. 验证与审计模型

### 9.1 当前原则

工程原则已经明确：

> One concern, one primary enforcement layer。

一个 invariant 不应在每个 downstream 层重新证明一次。

### 9.2 建议模型

**Partition producer boundary：**

负责重验证：

- schema；
- key uniqueness；
- PIT；
- completeness；
- content；
- semantic rule；
- deterministic output；
- atomic publication。

**Ordinary consumer：**

验证：

- manifest identity；
- contract/version；
- partition set；
- necessary hash/size/schema metadata；
- dataset availability。

普通 reader 不应每次打开都：

- 扫全历史；
- 全量 semantic sort；
- deep verify upstream Raw。

**Deep Audit：**

保留显式入口：

- batch/stream；
- 可扫描全历史；
- exact semantic recompute；
- 定期或版本迁移时执行；
- 不作为 ordinary query hot path。

请专家审查：

- ordinary read 是否应每次重新 SHA-256 大文件；
- 是否更适合 write-time hash + periodic scrub；
- local filesystem bit-rot/corruption 的实际威胁模型；
- Parquet footer/page checksum 是否值得启用；
- 怎样在可靠性与每次 O(total history) 校验之间取平衡。

---

## 10. Fingerprint / Versioning

当前已暴露反例：

- verifier 的 streaming/performance 改动；
- 因源码 hash 被纳入 snapshot builder fingerprint；
- 导致未改变数据语义的 snapshot 失效。

当前建议：

**进入 durable identity 的只有：**

- output schema contract；
- selection semantics；
- PIT semantics；
- identity semantics；
- price basis；
- materialization semantics；
- 会真正改变产出 bytes/rows/meaning 的 builder contract。

**不进入数据身份的：**

- logging；
- batching；
- verifier implementation；
- memory algorithm；
- temporary-file strategy；
- monitoring；
- performance optimization。

这些可以进入 audit metadata / software build metadata，但不应使未改变的历史事实重新 materialize。

请专家评估 semantic fingerprint 的最小必要集合。

---

## 11. 增量和纠错

### 11.1 Daily steady state

目标：

~~~text
new trading day
 → provider
 → raw
 → normalized
 → current canonical open partition
 → snapshot manifest update
 → research/current feature partition
~~~

历史 closed month 不动。

### 11.2 Outage catch-up

如果漏了 3 个交易日：

- 获取精确 missing range；
- bounded batch；
- 不 replay 既有 closed history；
- 从 latest verified boundary 继续。

### 11.3 Late correction

需要明确：

- provider 修订昨日/历史数据；
- affected partition 新 version；
- snapshot 指向新 version；
- dependent research/features 只重算受影响窗口；
- 历史旧版本是否保留；
- 如何区分 correction 与 duplicate replay。

这是分钟级后可能变得更重要的问题。

---

## 12. 研究性能目标

不建议现在承诺未经 benchmark 的严格 SLA，但应建立 workload 基线。

建议至少验证：

### 12.1 日线

- 全市场 6.5 年；
- 某股票池多年；
- 某日横截面；
- Development/Holdout partition filter。

### 12.2 分钟线

**W1：一个全市场交易日**

约 1M+ bars。

**W2：一个开放月份**

约 20M–30M bars。

**W3：单证券 5 年分钟线**

约 300k bars 数量级。

**W4：100 只证券 3 年**

约 18M bars。

**W5：全市场一年分钟线**

约 300M bars。

测试：

- selected columns；
- date/time range；
- security list；
- groupby/resample；
- rolling；
- cross-section；
- join identity/calendar；
- feature materialization。

必须观察：

- scanned bytes；
- elapsed time；
- peak RSS；
- temp/spill；
- files touched；
- CPU utilization。

---

## 13. 资源评估

以下为架构规划范围，不是已验证 SLA。

### 13.1 行数

| 数据 | 估算 |
|---|---:|
| 日线 / day | ~5k rows |
| 日线 / year | ~1.2–1.3M rows |
| 日线 / 6.5 years | ~8M rows |
| 1m / day | ~1.0–1.3M rows |
| 1m / year | ~250–320M rows |
| 1m / 6.5 years | ~1.6–2.1B rows |

### 13.2 磁盘

实际必须用真实 schema/provider payload benchmark。

对“窄 Canonical 1m fact”先使用非常粗的规划区间：

- compressed Parquet：约 30–120 bytes / row；
- 2B rows：约 60–240 GB canonical fact。

如果每行继续带大量 UUID/string lineage，可能显著高于该范围。

整个平台还包括：

- Raw evidence；
- Normalized；
- Canonical；
- manifest/metadata；
- research materialization；
- feature data；
- temp/spill；
- old corrected partition versions。

因此对 6–10 年分钟级研究环境：

**最低合理规划：**

- 2 TB NVMe。

**更舒适：**

- 4 TB NVMe。

如果长期保留大量 Raw、多个 research/feature materialization 和 correction history，可能需要更高容量或冷热分层。

### 13.3 RAM

新架构目标不是“历史越长 RAM 越大”。

建议规划：

**日线数据平台：**

- 16 GB 应能运行；
- 32 GB 足够舒适。

**1m 数据平台 + 研究：**

- 32 GB 应能完成 ingestion、compaction 和大部分查询；
- 64 GB 是推荐研究工作站容量，给 DuckDB、Polars、OS cache、并发研究和复杂 rolling 留余量；
- 系统不应把 64 GB 视为可以常态占满的预算。

目标：

- daily ingest：数百 MB ～ 低个位 GB；
- open-month compaction：低个位 GB ～ 数 GB；
- deep audit：bounded，目标不随 total months 线性增加；
- 单个普通查询：由 query workload 决定，允许 DuckDB spill。

当前 22–47 GB 的日线峰值被视为架构缺陷，不是资源预算依据。

### 13.4 CPU

建议：

- 8 cores：可运行；
- 12–16 modern cores：适合作为本地研究/数据工作站；
- 更多核心对 Parquet scan、compression、DuckDB aggregation 有收益，但不是 correctness requirement。

GPU 对核心数据平台无必要。

### 13.5 I/O

分钟级真正敏感的是 NVMe throughput/latency。

建议专家重点评估：

- 单 NVMe 是否足够；
- temp/spill 与 durable data 是否值得分盘；
- compaction 和大研究查询同时发生时的 I/O contention；
- Windows NTFS vs WSL2/Linux filesystem；
- 是否需要为持续研究使用 Linux/PVE VM 作为正式数据节点。

---

## 14. Plain Parquet + DuckDB 的选择理由

当前选择它们不是因为“简单所以不管性能”，而是因为当前 workload 特征：

- research-first；
- read-heavy；
- historical；
- append/partition oriented；
- columnar；
- time/universe filters；
- single-node；
- 不要求毫秒级在线 serving；
- 不要求高并发 OLTP；
- 不要求分布式 ingest。

Parquet 优势：

- immutable；
- columnar；
- compressed；
- language-neutral；
- object/file-store friendly；
- metadata/statistics；
- 非专有格式。

DuckDB 优势：

- 对 Parquet 直接查询；
- pushdown；
- vectorized execution；
- spill；
- SQL；
- Arrow/Polars integration；
- 低运维复杂度。

### 14.1 需要外审挑战的替代选项

**Iceberg / Delta：**

可能在 versioning、compaction、partition evolution、snapshot isolation 上降低自研 manifest 复杂度。

问题：

- 是否对单机项目过重？
- Python/DuckDB 生态成熟度是否足够？
- 会不会重新引入大量 table-format ceremony？

**ClickHouse：**

可能在大量分钟数据、高并发、交互查询时有优势。

问题：

- 单人/小团队研究是否值得运维常驻服务？
- backtest/feature workload 是否真正优于 local Parquet + DuckDB？
- 什么时候是迁移阈值？

**Polars Lazy：**

适合作为 research/dataframe API，但不应形成第二个存储系统。

**Arrow Dataset：**

可作为批处理/interop 层。

请专家给出“何时该升级”的明确触发条件，而不是笼统推荐更重技术。

---

## 15. 数值类型需要重新审查

当前 OHLCV 多使用 Float64。

分钟级规模扩大后，需要专家评估：

- price 是否应存 scaled integer / decimal；
- amount 精度；
- volume integer vs float；
- corporate action adjustment 后的 numeric contract；
- Float64 的跨引擎 deterministic/hash 问题；
- Parquet compression 和计算效率。

不希望为了理论纯粹性增加复杂度，但如果类型选错会导致未来数据迁移，应现在纠正。

---

## 16. Price basis / Corporate actions

当前 Research daily price basis 是：

- UNADJUSTED_CANONICAL。

这有利于保持源数据事实，但量化研究后续必然会涉及：

- adjusted price；
- returns；
- split/dividend；
- rights issue；
- merger；
- delisting；
- code change。

当前倾向：

- Canonical 保留未调整市场事实；
- adjustment factor / corporate action 作为独立 PIT dimension；
- adjusted series 在 research/feature 层按 contract 派生；
- 不覆盖原始 Canonical price。

请专家审查：

- 是否适合分钟级；
- adjustment factor 粒度和 PIT；
- adjusted minute bars 是否应物化；
- 如何避免 survivor/lookahead bias。

---

## 17. Completeness 在分钟级的可扩展性

日线目前会检查 expected security-session pairs。

分钟级如果简单展开：

~~~text
security × session × minute
~~~

可能产生非常大的 expected-pair 结构。

需要避免在 Python 中构造数十亿 pair set。

请专家审查可扩展方案，例如：

- per security/day aggregate count；
- provider trading calendar + bar-range completeness；
- compact bitmap；
- SQL anti-join；
- partition-local vectorized validation；
- exception-only evidence。

要求：

- 不能把缺 bar 自动等价为停牌；
- 不能用附近日期猜；
- 必须处理 listing/delisting/suspension；
- 但不应为了审计构造巨型 Python set。

---

## 18. Metadata / Catalog

Plain manifest 方案仍需要一个小型 catalog：

- dataset；
- partition key；
- current version；
- artifact URI；
- schema；
- content hash；
- row count；
- time bounds；
- source lineage；
- state。

需要外审确认：

- DuckDB metadata tables 是否足够；
- SQLite 是否更合适做 control metadata；
- 是否需要 append-only manifest log；
- 如何避免 metadata DB 自己成为强耦合单点；
- 如何备份/重建 catalog。

事实数据应可从 artifacts + manifests 恢复 catalog，尽量不产生不可恢复 hidden state。

---

## 19. 并发模型

当前旧架构强调 DuckDB 进程级独占。

未来 research 场景可能出现：

- 一个数据更新任务；
- 多个本地 strategy/agent research readers；
- notebook / batch jobs 并发读取。

目标：

- 单 writer 控制 manifest/catalog；
- closed Parquet immutable，可多 reader；
- research process 可以各自建立 DuckDB read-only query context；
- 不要求所有 research reader 共享一个长期可写 DuckDB database。

需要专家审查：

- 最简单可靠的 concurrent reader/writer 模型；
- Windows file locking；
- WSL/Linux 是否应作为正式运行环境；
- manifest atomic switch 与 reader snapshot consistency。

---

## 20. 文件生命周期和备份

需要明确：

- Raw retention；
- normalized intermediate retention；
- canonical current + old versions；
- open-month fragments；
- compacted partition；
- research outputs；
- feature outputs；
- DuckDB temp；
- audit temp chunks。

备份重点应是：

- Raw evidence（如要求长期重放）；
- Canonical；
- manifests/catalog；
- identity/corporate-action dimension；
- contracts/code revision references。

Derived ReadModel cache 不应成为必须备份的数据。

请专家评估：

- 本地 NVMe + backup disk；
- NAS/object storage；
- checksum scrub；
- snapshot backup；
- disaster recovery。

---

## 21. 当前项目状态

当前 Issue #76 的历史工作已经证明：

- 78 个月 Provider/Raw evidence 已经取得并保留；
- 一些具体 provider/lifecycle/identity edge case 已闭合；
- 已存在本地 78 partition materialization；
- 但最终 reader/idempotency/conflict gate 没有完成；
- 内存问题暴露后，项目主动停止继续强化旧架构；
- PR #77 保持 Draft；
- 当前重心已经从“让旧链路勉强 PASS”切换为“先纠正数据平面架构”。

因此本次外审的意见可以影响当前架构，不存在“设计已经不能动”的前提。

---

## 22. 建议的迁移策略

希望避免 Big Bang rewrite。

建议分阶段：

### A. 冻结旧的全量复制扩展

不继续建设：

- physical Snapshot full copy；
- physical full-history ReadModel copy；
- full-history Python projection。

### B. 把 Canonical 事实数据改为长期 partitioned columnar truth

先以 daily_bar 验证。

### C. Snapshot logical manifest

让 Snapshot 引用 exact Canonical partitions。

### D. DuckDB external query facade

验证同一 research semantic 能通过 external Parquet 获得。

### E. bounded Research materialization

按 month/current month。

### F. 迁移 Issue #76 retained evidence

provider_calls=0，从已有 sealed evidence 生成新 Canonical partitions / logical snapshot。

### G. minute synthetic architecture benchmark

在投入真实分钟数据前跑一组 realistic synthetic benchmark。

外审专家如认为顺序应调整，请明确指出。

---

## 23. 分钟级架构锁定前的验收测试

至少需要：

1. **Full-market day ingest**  
   ~1M bars，batch 内存有界。

2. **Open-month append**  
   多个交易日连续追加，不重写 closed months。

3. **Month-close compaction**  
   bounded memory，atomic manifest switch。

4. **Cross-sectional query**  
   某分钟/某时段全市场，验证 pruning。

5. **Security history**  
   小证券集合多年，验证不扫描不必要 bucket。

6. **Large range query**  
   全市场较长周期，观察 DuckDB scan/spill。

7. **Correction**  
   修正一个历史 day/partition，只有 dependent outputs invalidated。

8. **Crash simulation**  
   compaction/build 途中失败，无半发布。

9. **PIT**  
   future identity/action 不污染旧时间。

10. **No duplicate fact plane**  
    Snapshot/ReadModel 不产生完整 OHLCV copy。

---

## 24. 建议资源验收指标

### 24.1 Memory complexity

验收重点不是固定绝对数字，而是：

> 6 个月和 6 年历史执行同一个 daily append，其 peak RAM 应接近相同。

> 处理一个月时，peak RAM 不应因历史已有月份数量线性增长。

### 24.2 I/O

必须能说明：

- adding one day reads/writes 哪些文件；
- month close reads/writes 哪些文件；
- ordinary query scans 哪些 files/bytes。

### 24.3 Storage amplification

需要统计：

~~~text
raw bytes
normalized bytes
canonical bytes
research bytes
feature bytes
total bytes / canonical bytes
~~~

外审希望专家建议合理 amplification target。

### 24.4 File count

避免：

- millions of tiny files；
- one gigantic file preventing pruning。

---

## 25. 潜在问题清单

希望专家重点检查以下风险。

### P1. Snapshot 逻辑化以后，是否削弱审计

我们认为 manifest + exact partition hashes 足够，但需要独立确认。

### P2. Plain Parquet manifest 是否会逐渐变成自研 Iceberg

如果 correction、compaction、version、snapshot isolation 越做越复杂，是否应尽早采用成熟 table format？

### P3. security hash bucket 对横截面查询是否不利

需要 balance security history 与 full-market cross-section。

### P4. 月分区是否适合 1m

一个月 ~20M–30M rows。是否应该 day/month hybrid？

### P5. Parquet file / row-group size

需要实测确定，不能拍脑袋。

### P6. Row lineage 太重

需要决定哪些字段移到 manifest。

### P7. Semantic hash 成本

是否真正需要每个 fact partition 自己再维护排序后的 semantic hash？还是 deterministic parquet/content hash + schema/key validation 足够？

### P8. Full-file SHA-256 read cost

不能每次 ordinary read 都重新 hash 数百 GB。

### P9. Metadata catalog consistency

如何保证 manifest、catalog、files 三者 crash-safe。

### P10. Late data / corrections

尤其分钟数据 provider 可能修订。

### P11. Corporate actions

adjustment/PIT/identity 必须避免 research leakage。

### P12. Python API

如何防止未来开发人员重新写出 fetchall/list[dict] 大数据路径。

### P13. Windows

正式数据节点是否继续 Windows，还是 WSL/Linux 更适合 DuckDB/Parquet/NVMe。

### P14. Concurrent research

多个 agent/notebook 同时访问时的锁和 I/O。

### P15. Strategy feature explosion

Factor/feature materialization 很容易比原始分钟数据大很多，需要 lifecycle/retention 规则。

### P16. Minute completeness

不能构建巨型 expected-pair Python set。

### P17. Data precision

Float64 / integer / decimal 要现在确认。

### P18. Backfill throughput

即使内存 bounded，2B rows 首次回填可能受 provider、compression、hash、I/O 限制，需要估算完成时间。

### P19. Query performance

单机 DuckDB 对 full-market multi-year minute feature query 是否满足研究体验，需要 benchmark，不应仅靠理论。

### P20. Scale-out trigger

必须提前定义什么时候单机方案“不够”，避免既过早分布式，也避免明显超负荷后才迁移。

---

## 26. 希望外部专家给出的具体结论

希望外审不要只给“总体不错/建议优化”类意见，而尽量逐项给出：

1. **推荐保留的架构决策**；
2. **建议修改的架构决策**；
3. **必须现在修改，否则未来迁移成本大的问题**；
4. **可以推迟的问题**；
5. **应删除的复杂度**；
6. **分钟级推荐 partition/file/row-group strategy**；
7. **建议的事实表 schema 和 lineage placement**；
8. **DuckDB + Parquet 能支持到什么规模/并发/workload**；
9. **采用 Iceberg/Delta/ClickHouse 等的具体触发条件**；
10. **建议硬件规格**；
11. **benchmark workload 与验收阈值**；
12. **correctness / PIT / quant research leakage 风险**；
13. **对 feature/factor storage 的建议**；
14. **对 correction/version/compaction 的建议**；
15. **对 Windows vs Linux/WSL/PVE 运行环境的建议**。

---

## 27. 外审中的既定约束与可修改项

### 27.1 目前视为既定的业务约束

除非专家指出严重风险：

- Owner 决定数据源可信性；
- stable security_id；
- current-code-first ordinary identity；
- PIT；
- immutable closed history；
- retained raw/replay；
- fail closed；
- daily incremental steady state；
- research split；
- no lookahead；
- minute-ready；
- no real trading execution in current phase；
- data foundation serves Quantitative-Strategy-Research。

### 27.2 明确可以推翻或修改

欢迎专家直接挑战：

- Snapshot 是否需要独立概念；
- Normalized 是否长期保留；
- Canonical partition layout；
- bucket 方式；
- metadata DB；
- DuckDB view strategy；
- file sizes；
- row group sizes；
- hash strategy；
- lineage fields；
- semantic fingerprint；
- compaction；
- table format；
- research physical materialization；
- numeric types；
- machine/OS layout。

---

## 28. 项目希望坚持的最终特性

无论最终具体实现如何，希望系统长期保持：

**简单：**  
可以由小团队长期维护，不因“审计”而形成庞大 ceremony。

**可靠：**  
错误数据不能静默进入研究。

**PIT 正确：**  
研究结果不能被未来信息污染。

**增量：**  
历史越长，处理今天的数据不应该越慢。

**高效：**  
量化研究不应被数据平台 I/O 和 Python object overhead 拖累。

**可复现：**  
研究结果可以知道用了哪一版数据。

**可扩展：**  
加入 1m 不需要重建平台；加入更多 feature/domain 也复用同一机制。

**可诊断：**  
真实 blocker 能快速定位，不通过大量抽象掩盖问题。

---

## 29. 目前我们的初步结论

当前团队的暂定判断是：

1. **几十 GiB 日线内存占用不合理，也不必要。**
2. 问题主要来自数据被多层物理复制和 Python object 化，而不是 Parquet/DuckDB 本身。
3. 应把 Canonical 作为唯一市场事实数据面。
4. Snapshot 应逻辑化。
5. ReadModel 应查询化。
6. Research/Feature 是唯一可能合理增加物理副本的层，但必须有业务价值且 incremental。
7. 分钟级数据要求 lineage 上移、partition/file 设计和 query pruning 从现在就确定。
8. 在没有 benchmark 证明必要以前，不应该升级成分布式系统。
9. 64 GB RAM 应是舒适研究余量，而不是日线系统正常运行的刚性需求。
10. 未来系统真正的容量压力更可能来自 NVMe、I/O、Raw retention 和 Feature explosion，而不是必须加载全部历史到内存。

**这些结论全部欢迎外部专家推翻。**

---

## 30. 相关项目证据入口

外审如需进一步查看项目细节，可以从以下文件开始：

- README.md
- docs/project/ENGINEERING_PRINCIPLES.md
- docs/project/CURRENT_EXECUTION_PLAN.md
- docs/project/ISSUE76_MATERIALIZATION_MEMORY_BLOCKER_20260922.md
- docs/research/README.md
- docs/research/cr7_historical_materialization_contract_20260913.md
- docs/design/A股市场态势数据基座_日频模块_V1.3.2_开发方案.md
- Issue #76
- PR #77

其中早期 design 文件属于历史/冻结设计依据。**本外审文档及 Issue #76 最新控制面代表当前架构重审方向**；若两者与早期文档冲突，应把冲突本身列为外审问题，而不是自动沿用旧设计。

---

# 外审结论填写建议

专家可以直接在本文件后补充：

## A. Overall Assessment

- ACCEPT / ACCEPT WITH CHANGES / REDESIGN
- 一句话总体判断

## B. Critical Issues

按严重性列 P0 / P1 / P2。

## C. Recommended Target Architecture

如果不同意本文方案，请给出替代数据流和各层职责。

## D. Minute-data Recommendation

给出 partition、file size、sorting、bucket、compaction、query engine 建议。

## E. Resource Recommendation

给出 RAM / CPU / storage / I/O 的建议范围和假设。

## F. Complexity Reduction

指出应删除或合并的层/合同/验证。

## G. Quant Research Efficiency

评估对 factor / backtest / cross-sectional / time-series 的适配。

## H. Migration Plan

建议从当前 PR #77 状态如何低风险迁移。

## I. Go / No-Go Items

哪些问题必须在继续历史物化前解决，哪些可以后置。
