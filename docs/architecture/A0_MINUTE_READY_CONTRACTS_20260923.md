# A0：分钟就绪数据契约（Issue #79）

状态：**实现前冻结草案，等待 PM/Owner 审阅**

本文件只冻结跨 `1d`/`1m` 共用的最小语义，不冻结尚未有证据支持的 provider 数值类型、bucket 数量、Parquet 文件大小或物理键表示。现有 daily 实现与本文件不一致的地方必须在分钟数据落地前完成迁移或明确版本化，不能静默兼容两种含义。

## C1. 时间、交易日与 PIT

| 项目 | 契约 | 当前状态 |
|---|---|---|
| bar interval | `bar_start` 为 UTC instant，区间为 `[bar_start, bar_end)`；`1m` 的 `bar_end = bar_start + 1 minute`。禁止用闭区间或本地字符串比较替代。 | 分钟字段尚未进入生产 schema；待实现 |
| trade date | `trade_date` 是交易所本地交易日，用于分区、PIT 与 identity bridge；它不是由 provider `retrieved_at` 推导。 | daily canonical 已有 `trade_date`；分钟需补齐边界测试 |
| market availability | `market_available_at` 表示事实在市场/事件语义上可被观察的时间；必须与 provider 请求完成时间分离。 | 当前 daily 合同使用 `available_at`/received-at 派生路径；分钟命名与语义待迁移 |
| provider provenance | `retrieved_at`/`ingested_at` 只表示提供方响应或本次摄取时间，不能作为事实发生时间。 | 现有 lineage 字段存在；需避免在分钟行重复写批次常量 |
| session state | 交易日历/会话定义必须明确开盘前集合竞价、午间休市、收盘后和非交易时段。 | provider 的分钟会话形状尚未完成 shape/语义探针，暂不硬编码具体补零规则 |
| absent bar | 未返回的分钟不能自动生成价格为 0 的伪 bar。缺失、停牌、午间休市和不适用必须由日历/状态/质量结果分别表达。 | 规则冻结；生产字段/sidecar 待实现 |
| zero value | 合法的 0/0.0 是真实数值，不能用 truthiness 当作缺失。 | 现有 mapper 已遵守 `first_present` 约束；分钟回归需复用 |

PIT 规则：只有 `market_available_at <= as_of` 的事实可以进入该 PIT 视图；`retrieved_at` 晚于 `as_of` 的响应不能借助当前 snapshot 反推历史事实。日历和 identity 版本也必须绑定到 manifest。

## C2. 数值精度与单位

现有 `DailyBarDTO` 将 `open/high/low/close/pre_close` 表示为 `float`，`volume/amount` 也以 provider 数值保存，但代码明确标注 volume（手/股）和 amount（元/千元）单位尚未由独立证据冻结。分钟数据不得沿用这些 Python 类型作为单位证明。

落地前必须完成一次 provider shape probe，至少记录：字段原始类型、精度/小数位、单位证据、缺失/空值形态、最大最小范围以及同一响应内是否混合类型。未完成前：

- 不选择 `float`、`Decimal`、scaled integer 或其他最终物理类型；
- 不同时保留两个含义不同但同名的数值字段；
- 不因转换方便而把合法 0、空值和缺失折叠；
- 合成基准中的 `float64/int64` 只用于比较内存和扫描成本，不能作为 provider 数值结论。

## C3. 逻辑分区、修订与物理布局

逻辑数据集分开治理，但使用同一 manifest/query-facade 体系：

- `security_bar_1d`：逻辑键约为 `(security_id, trade_date)`；
- `security_bar_1m`：逻辑键约为 `(security_id, bar_start)`；
- 逻辑分区建议使用 `dataset/frequency/calendar-month`，例如 `security_bar_1m/2024-01`，最终 URI 由实现 ADR 冻结。

每个逻辑分区必须有：

- `logical_partition_id`：稳定标识数据集、频率和月分区；
- `data_revision`：只有逻辑行内容、逻辑键或其语义 contract 改变时递增；
- `logical_content_hash`：生产边界按确定性列顺序和键顺序计算的一份有界逻辑内容 seal；
- `layout_revision` 与 `artifact_set_hash`：只描述 Parquet 分片/排序/压缩等物理变化，可因 compaction 改变而不改变 `data_revision`。

因此，compaction 不得迫使下游重建研究语义；下游绑定的是逻辑 revision/content hash，并通过 manifest 解析当前 artifact set。

## C4. Lineage 与完整性边界

事实行只保留随行变化或识别单行所必需的字段：identity、时间、OHLC、前收、成交量/额以及经过定义的质量/状态字段。provider、run、raw request/evidence、mapper、policy、contract、PIT、seal 等如果在一个分区/批次内恒定，应放在 partition manifest，并由 manifest 与逻辑 hash 绑定。

生产边界执行重量级检查：schema、类型/单位、键唯一性、时间窗口、PIT、row count、logical content hash、raw/mapper/policy 绑定及不可变 closed-month 约束。普通 open/read 只消费小型 manifest/seal 和引用 artifact 的存在性/绑定关系；全历史语义重算只能由显式、离线、有界 deep audit 触发。

不得把当前 daily 行中的所有 `source_*` 字段机械复制到每条分钟行。`source_row_ordinal`/`source_row_identity_hash` 这类确实随行变化的证据字段，需要在实现时逐字段证明后再决定保留位置。

## C5. 身份表示

治理 identity 永远是稳定 UUID 语义；Parquet 物理键可以是当前 UUID 字符串、固定 16-byte UUID 或 `INT64 + 小型 identity mapping`。物理选择必须以 A1 结果和 mapping 的 PIT/不可变契约共同决定，不能因为本次合成基准的单一查询最快就直接改写治理 identity。

## C6. Post-holdout

当前 Development、Validation、Holdout 窗口保持不可变。`trade_date >= 2026-07-01` 的数据默认标为 `POST_HOLDOUT` / `FORWARD_MONITORING`，在新的 split-policy version 经审阅前不得静默并入既有研究 split。这个状态属于数据集/manifest 元数据，不是价格事实列。

## C7. 迁移纪律

Issue #76 的 retained 78-month canonical evidence 只能在新契约通过审阅并完成 bounded vertical slice 后迁移；迁移必须 `provider_calls=0`，不得重新请求或丢弃既有 raw/canonical 证据。A0 文档通过不等于授权历史迁移，也不等于允许恢复旧 M1/M2/M3。

## 待审阅问题

1. provider shape probe 的单位/精度证据是否足够冻结数值物理类型；
2. minute session 的 auction/lunch/close 和 missing/suspension sidecar 具体字段；
3. manifest 字段的最终 schema 与 `available_at`/`retrieved_at` 的命名迁移；
4. A1 的 layout/key 选择以及 row-group touch 观测缺口；
5. 上述审阅通过后，才进入一个 bounded `daily_bar` vertical refactor。

