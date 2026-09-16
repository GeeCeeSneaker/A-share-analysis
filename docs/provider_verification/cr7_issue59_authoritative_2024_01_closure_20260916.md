# Issue #59 · 2024-01 authoritative acquisition and materialization closure

状态：`AUTHORITATIVE_CLOSURE_VERIFIED_LOCALLY / REVIEW_PENDING`

## 范围与执行方式

- Issue：[#59](https://github.com/GeeCeeSneaker/A-share-analysis/issues/59)
- 调度依据：Issue comment `5691600928`
- 代码基线：PR #71 merge `c360354bee8698c8a2db61a607d0bb3dcefd0ddb`
- 执行分支：`investigate/issue59-identity-event-20260916`
- 唯一采集范围：`validation_a:2024-01`
- 市场数据源：Owner-approved AmazingData
- 代码调用门控：`ProviderUseMode.SPIKE`

本次使用正式账号通过进程环境变量完成真实 SDK 采集，但 `SPIKE` 是代码层能力门控，不能
解释为 Formal B1-B7、Production capability 或全库生产资格已经批准。凭证、账号 profile、
私有 endpoint、SDK/runtime、原始响应和 DuckDB 均没有进入 Git。

## 采集与 completeness

| 检查项 | 脱敏结果 |
|---|---|
| 月度证券 universe | 5,106 |
| 交易日 | 22 |
| 返回证券数 | 5,106 |
| 返回日期范围 | `2024-01-02` – `2024-01-31` |
| required pair / returned pair | 112,075 / 112,075 |
| 返回日线行数 | 112,075 |
| missing / extra / unresolved | 0 / 0 / 0 |
| structural errors | 空 |
| completeness | `PASS`，规则 `amazingdata-month-completeness-rule-v2` |
| 分类 | `SUSPENSION_NON_TRADING=132`; `NOT_APPLICABLE_SESSION=125`; `POSITIVE_TRADE_COUNT_ACTIVE=22` |
| 语义请求 | 22 个逐交易日历史证券集请求 |
| positive-trade fallback | 22 个请求、22 个正交易对 |

receipt：

- `receipt_id`：`amazingdata-history-receipt-dac6ef03211d95487cc7fcce68a4ed7d`
- `receipt_hash`：`2860764047844a61d8ab47e4949f98c93f74780a6a47cce3e9bd08d120db37e2`
- `source_snapshot_id`：`2cd0957a-2237-5127-afba-6127376a7ed0`
- `source_snapshot_manifest_hash`：`3cf5405cfa7a751427fd33c18bc9fa8cec5c66a7923a7779dc48f3b848823c1f`
- 月度证券集合 hash：`f9b15023b79cd261c599a5de52e5d00e62cdf82c4b9fddffcde601450a7e8fde`
- 交易日集合 hash：`f7a391589c4ab102ce6b570c4001a92590eae94a3794e0f40f8554e6da903452`
- required/returned pair 集合 hash：`14517c57e0a369b8b700a1a6c5f5fe9ed069f540b3d6ce28d79c44d8a12a2651`
- 保留 capture：本地忽略目录 `data/spike/identity_event_chain_20260916/authoritative_capture_20260916/`
- capture catalog：`source_capture/amazingdata/amazingdata-history-receipt-dac6ef03211d95487cc7fcce68a4ed7d.json`
- capture catalog hash：`dac6ef03211d95487cc7fcce68a4ed7d97eebed897ccb492ae4a2ed8d5101782`
- completeness statement：`amazingdata-complete-dac6ef03211d95487cc7fcce68a4ed7d`

采集路径内部已再次调用 `verify_retained_capture()`；receipt、capture catalog、每个已保留
exchange 和 completeness evaluation 均通过重放校验。

## coverage 与 bounded materialization

receipt 已直接桥接为 `AUTHORITATIVE_UPSTREAM` coverage evidence/basis，没有通过任意 caller
bytes 或手工 completeness 标签铸造权威状态：

- evidence id：`amazingdata-evidence-validation_a:2024-01-amazingdata-history-receipt-dac6ef03211d95487cc7fcce68a4ed7d`
- coverage basis id：`amazingdata-basis-validation_a:2024-01-amazingdata-history-receipt-dac6ef03211d95487cc7fcce68a4ed7d`
- evidence hash：`390aed67d005385acfb83ce0cdb7773073a38536c12c4ccfbacbfc7cbda90112`
- basis artifact hash：`9ff7f821cc561db7fa78040fcc370c35a9f7ae3e12fff7decdbdc28ce0af7b61`

`OfflineHistoricalMaterializer` 仅发布目标分区 `validation_a:2024-01`：

- materialization id：`rhm-04c8912e344ac251c6a5f6e9ebda5977423a41eb17ecb1c5347c23068fb6753b`
- idempotency key：`04c8912e344ac251c6a5f6e9ebda5977423a41eb17ecb1c5347c23068fb6753b`
- manifest：`research_security_daily/contract=cr7-history-materialization-v1/materialization=rhm-04c8912e344ac251c6a5f6e9ebda5977423a41eb17ecb1c5347c23068fb6753b/manifest.json`
- manifest hash：`17cddb4c8586ed1921dcabd0a8db8764dc74e02590fc5c2f6ebb005ba681d2c7`
- artifact content hash：`2a313442e6cbb3f3f934e71c61aa7d71891047fdc5013d2243d1b10d267a237a`
- partition inventory hash：`216abe2c67612347373dff8b17ae32e5562c727e6613f6cb2ee6917b187600a9`
- ordinary reader 读回：112,075 行
- 相同输入重放：`idempotent_replay=true`
- 修改一行内容后重放：`MaterializationConflictError`，已 fail closed

## 审阅边界与下一步

本报告证明的是当前实现、真实有界采集、保留证据闭环和单月物化的工程结果；它不自动批准
Production、B1-B7、Stage B 或 78 个月回补。原始证据不上传 Git，独立审阅如需检查原始
payload，应在受控本地环境按上述 capture/hash 复核，不能通过上传凭证或 raw 绕过治理。

当前需要：审阅本分支代码、测试、脱敏报告和 exact-head CI；独立 PM 给出 `PASS`、
`REMEDIATE` 或 `STOP(BLOCKED)` 后，项目管理者再决定是否考虑 Stage B。当前不自行批准、
不自行合并，也不启动任何未授权阶段。
