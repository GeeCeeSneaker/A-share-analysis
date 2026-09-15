# CR-7 2024-01 最小真实 source-input 链路（2026-09-15）

状态：`STOP(BLOCKED)`。本记录是 Issue #59 在 PR #68 合并后的继续执行结果，
只检查最小真实输入，不代表 Formal B1-B7、Production verdict 或 authoritative
receipt。

## 范围和安全边界

- 实际开发基线：`a7671ab34d301cb0aca2f351a31bbc865c100498`，即 PR #68 合并后的
  clean `main`。
- 只请求 2024-01 的最小真实样本：完整历史代码表用于选择一个真实证券，再请求该证券
  的 `stock_basic` 和 2024-01-02 单日线；同时请求 SH 日历用于显式交易日参数。
- 使用已有 `AmazingDataProvider`、`AnchoredRawEvidenceWriter`、`NormalizationRunner`、
  `CanonicalRunner`；没有新增 bootstrap 框架，没有改写原始返回值。
- 本次在线调用使用现有 Provider facade 的显式 `ProviderUseMode.SPIKE`，用于诊断原生
  shape 到既有标准化边界的可达性；没有运行 Formal B1-B7 或 Production 流程。
- 原始 payload、完整 request params、账号凭证、私有 endpoint、SDK/runtime 和本地
  DuckDB 仅保存在被 `.gitignore` 排除的 `data/spike/source_input_shape_probe_20260915/`；
  本记录只保存脱敏身份、计数、哈希、ID 和结论。

## 已确认的真实结果

脱敏账号画像 `UNKNOWN_24e2ff401792` 的本地 bootstrap 已确认网络可达、认证成功、查询
就绪；这不是本次阻断原因。

| 交换 | 真实请求范围 | RawWriter | NormalizationRunner | 关键证据 |
|---|---|---:|---|---|
| `trade_calendar` | `SH`；返回 8,726 日 | 1 parquet + 1 meta，`rows=8,726` | `SUCCESS`，8,726/8,726，0 quarantine | raw content `afc2d62522e009097858fcbc1bb71564e375b7ebfe689f706a486fec603917b3`；evidence `408fb8d1ef24a6288d60914f7c525972c776ba22b5476e26c14a9e3e35bdc097`；manifest `51982065c6aaa3b98badc4da0c3c3d093cfd57a495ab4e55ceb245de8f7b0b66` |
| `hist_code_list` | `EXTRA_STOCK_A_SH_SZ`；20240101–20240131 | 1 parquet + 1 meta，`rows=5,106` | `BLOCKED / MAPPING_VALIDATION_FAILED`，0 normalized，5,106 quarantined | 当前 mapper 对每个 scalar `value` 都报告 `SECURITY_CODE/code` 缺失；raw content `1b447a21d71094b40e99aca090af12d01b3b0216ead5f0474ee6f565f1e2c83`；evidence `b8ba5a8fbd0d8d571b5ade21f4c0704591934ebf4111ae3749127728c5f61897` |
| `stock_basic` | 由上述真实代码表选 1 个证券 | 1 parquet + 1 meta，`rows=1` | `BLOCKED / MAPPING_VALIDATION_FAILED`，0 normalized，1 quarantined | SDK DataFrame 列不含 `SECURITY_CODE`，当前 mapper 报同一必填字段缺失；raw content `12460957f70b720c0bef923c8509c0a3c923b0d78135c9ef459fe659ffbdd01e`；evidence `1252cad58d2110c5cb3269799f2d1629105145e86ed3a2e9ae51776b426b494b` |
| `daily_bar` | 20240102 单交易日、1 个证券、`DAY`、显式 `trading_days=[20240102]` | 1 parquet + 1 meta，`multi_table_frames`，`rows=1` | `BLOCKED / PAYLOAD_SHAPE_UNSUPPORTED` | provider 返回 `dict[provider_symbol, DataFrame]`；当前 daily-bar registry 没有 exact `source_table`，因此按设计拒绝取第一张表；raw content `95cad8071aac0d6eb7d540015e38425a768ac8a10d937d201523e007b02747c7`；evidence `dc80c7829c636c55c5b497b3c0a018e3890a55ad3729229a4386de46d46127c1` |

四个真实交换均通过 `AnchoredRawEvidenceWriter` 完成锚定，raw 目录共 4 个 parquet 和 4
个 meta；但只有日历形成健康 CR-2 normalized run。原始 payload 未上传。

## Canonical 边界结果

在同一个本地 probe 数据库上调用既有
`CanonicalRunner.run(as_of=..., domains=("daily_bar",))`，没有注入任何候选行，结果为：

| 字段 | 结果 |
|---|---|
| `canonical_run_id` | `4cd59195-2547-5b2e-a172-6f649892a3d2` |
| 状态 | `BLOCKED` |
| selected / decisions / findings | `0 / 0 / 2` |
| manifest hash | `72cd70f3109d6767392c797a8526ea29331ab35d83162b1e35206e93f402f7ca` |
| blocking findings | `IDENTITY_DATASET_MISSING; REQUIRED_DOMAIN_MISSING` |

因此没有合法的 `SUCCESS` canonical run，`SnapshotBuilder.build()`、
`DuckDBReadModel.rebuild()` 和 `ResearchPanelBuilder.prepare_verified_projection()` 均未
执行。也没有调用 `AmazingDataHistoryAcquisition.acquire_month()`、签发 receipt、构建
coverage basis、物化或普通 reader。

## 最小、具体的阻断

这不是账号、网络或 RawWriter 锚定失败，而是“真实 provider 原生 shape → 现有 CR-2
normalization → Canonical”边界尚未闭合：

1. 历史代码表是 `list[str]`，现有 security-master row mapper 只接受带
   `SECURITY_CODE`/`code` 和 `MARKET_CODE`/`market` 的行；当前无法把 scalar membership
   安全地变成带 PIT `list_date` 的 identity row。
2. `stock_basic` 返回的真实 DataFrame 没有显式证券代码列；不能靠请求顺序或单行巧合把
   请求代码回填为 provider 事实，也不能把 `LISTDATE` 字段未经契约确认强行改名为
   `LISTING_DATE`。
3. 日线是保留逻辑 member key 的多表映射，当前标准化 registry 没有能消费任意 provider
   member key 的 exact route；取第一张表会违反 CR-2 的 shape/范围契约。

## 解除条件（不是本次自行扩大范围）

项目经理需要先批准或实现上述既有数据边界的最小、版本化适配，并补充对应回归和 exact-head
CI。适配必须同时满足：

- RawWriter 继续逐字节保留 provider 原生 payload，不在 raw 层伪造列；
- identity 适配必须有 provider-owned 的证券代码、市场归属和可用的 PIT 上市日期证据，
  不能用请求顺序、代码前缀或当前快照替代历史事实；
- daily-bar 适配必须保留每个逻辑 member 的代码绑定并逐 member 映射，禁止 take-first、
  静默丢弃、裸码市场猜测或把 `None`/空表伪造成成交行；
- mapper / registry / code fingerprint、normalized seal 和 canonical identity 的变化
  必须由代码与测试共同记录；不得手填 snapshot ID、manifest hash、ReadModel 或
  `VerifiedResearchProjection`。

在该最小适配未被项目管理者接受并通过验证前，继续保持 `STOP(BLOCKED)`。适配完成后只重跑
这一个最小 2024-01 source-input 链；只有得到可重开的 verified projection，才按 Issue #59
顺序进入完整 2024-01 acquisition / retained replay / coverage basis / bounded
materialization / ordinary-reader / idempotency proof。

Stage B（`2020-01`、`2026-01`）、78 月回补、Formal B1-B7、Production verdict、BSE/index、
CR-5/R2、Golden/H1、baseline 和策略工作仍未授权。
