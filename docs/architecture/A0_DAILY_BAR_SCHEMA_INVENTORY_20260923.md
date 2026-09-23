# A0：daily_bar 字段盘点与分钟迁移分类

状态：**代码盘点完成；最终迁移位置等待 A0/vertical-slice 审阅**

盘点依据：

- canonical domain spec：`src/ashare_state/canonical/eligibility.py`；
- provider DTO/mapper：`src/ashare_state/providers/amazingdata/dto.py`、`mapper.py`；
- canonical row construction：`src/ashare_state/canonical/canonicalizer.py`；
- 本地 retained canonical selected Parquet 的只读 schema 观察；没有重新请求 provider。

## 1. 当前 daily 输入与逻辑事实

| 当前字段/来源 | 当前用途 | 分类 | `1m` 处理要求 |
|---|---|---|---|
| `provider_symbol` / provider code | provider 响应身份，随后经 identity bridge 得到 `security_id` | 输入身份，不是最终事实键 | 保留在 raw/mapper evidence；canonical fact 使用 governed `security_id` |
| `kline_type` | DTO 中的日线类型（默认 `DAY`） | daily 输入控制字段 | 不复制进分钟 fact；频率由 dataset manifest/contract 标识 |
| `kline_time` | provider `yyyymmdd` 编码，映射为 `trade_date` | daily 时间输入 | 分钟改为明确的 `bar_start`/`bar_end` UTC instant，并保留 `trade_date` |
| `security_id` | canonical identity | row-varying、必要 | 保留；治理语义仍为稳定 UUID，即使物理列改用 surrogate |
| `trade_date` | daily logical key/PIT/分区 | row-varying、必要 | 保留为交易所本地交易日，不从 `retrieved_at` 推导 |
| `open/high/low/close` | daily bar payload | row-varying、必要 | 保留为分钟 payload；provider 数值单位/精度需先冻结 |
| `pre_close` | daily bar payload，可空 | row-varying、必要（可空） | 保留；明确缺失与合法零值，不做 truthiness 合并 |
| `volume` | provider 成交量 | row-varying、必要（单位未冻结） | 保留候选；shape/unit probe 后再冻结 dtype/unit |
| `amount` | provider 成交额 | row-varying、必要（单位未冻结） | 保留候选；shape/unit probe 后再冻结 dtype/unit |

当前 daily canonical key 是 `(security_id, trade_date)`，domain spec 的 payload 是上述 7 个市场数据字段。分钟 key 应升级为 `(security_id, bar_start)`，不能以 `trade_date` 单独去重。

## 2. 当前 canonical/selected lineage 字段

下面的分类不是直接删除清单，而是“每个字段必须证明是否分区恒定”的迁移清单。

| 当前字段 | 初步分类 | 处理建议 |
|---|---|---|
| `canonical_domain` | partition/batch 常量候选 | 放入 manifest；fact schema 只在确有 query/validation consumer 时保留 |
| `canonical_contract_version` | partition/batch 常量候选 | manifest contract binding；不在每条分钟行重复 |
| `selected_provider` | partition/batch 常量候选 | manifest；若一个分区存在多 provider 版本，必须先分批并分别封印 |
| `source_normalization_run_id` | batch 常量候选 | manifest；绑定 canonical logical revision |
| `source_output_name` | batch 常量候选 | manifest；不能假设一个混合分区只有一个 output |
| `source_raw_request_id` | 常量候选，需验证 | 若同一 partition/batch 恒定则 manifest，否则保留最小 row-level binding |
| `source_raw_evidence_hash` | 常量候选，需验证 | 同上；不能因为分钟规模大就丢失 raw closure |
| `source_mapper_identity` | policy/mapper 常量候选 | manifest；必须参与 producer seal，不能逐分钟重复 |
| `source_policy_version` | policy 常量候选 | manifest；下游通过 manifest binding 读取 |
| `availability_policy_version` | policy 常量候选 | manifest；与 `market_available_at` 的实际语义一起版本化 |
| `available_at` | 可能随批次/行变化 | 先区分 market availability 与 provider retrieval；未证明恒定前不得移出 fact/quality 表 |
| `ingested_at` | run/batch 常量候选 | 先确认是否每个响应批次独立；若恒定则 manifest，否则保留最小 provenance |
| `source_row_ordinal` | row-varying evidence | 仅在 raw audit/重放确实消费时保留；否则转入 bounded evidence index |
| `source_row_identity_hash` | row-varying evidence | 仅在单行 raw identity 绑定需要时保留；不等同于 logical content hash |
| `canonical_key` | 可由逻辑键确定的冗余字段候选 | `(security_id, trade_date)`/`(security_id, bar_start)` 可按 contract 重建；删前需更新 seal/hash 规则和查询 consumer |
| `canonical_run_id` / `snapshot_id` | hand-off/manifest 元数据 | 不属于事实 payload；Snapshot 只保留 manifest，不复制全量 fact |

## 3. 与分钟规模不兼容的重复物

以下形态在 daily 小规模时尚可读，但在分钟规模会放大为每行重复字符串/哈希：

- provider/run/raw/mapper/policy/contract 的长字符串和 hash；
- JSON 化的 `canonical_key`（若逻辑键列已单独存在）；
- Snapshot/ReadModel 中再次复制的全量 fact payload；
- 为了普通 read 而预先物化的全历史 Python `list[dict]`。

它们不是“全部删除”，而是必须移到 manifest、evidence index 或按需的 research-derived dataset；只有新增研究语义的物化才允许成为物理副本。

## 4. 目前不能安全冻结的字段

1. `volume`/`amount` 的 provider unit、scale 和最终 dtype；
2. `available_at` 与 `retrieved_at` 的分钟级来源/命名；
3. auction、午间休市、收盘和停牌的具体 availability/quality 表达；
4. raw lineage 是否对一个逻辑月份恒定；
5. `canonical_key` 等冗余字段是否还有外部 consumer；
6. physical key、bucket 数、row-group/file target size。

这些未决项已经写入 A0 契约，不应通过默认值、跨源补齐或静默 dtype 转换解决。

## 5. 验收边界

本盘点完成了“当前字段是什么、候选应去哪”的审计输入，但没有改写生产 schema，也没有迁移 Issue #76 retained evidence。只有 A0 review、A1 选型和 bounded `daily_bar` vertical slice 均通过后，才允许按 `provider_calls=0` 迁移已封存历史。

