# CR-7 历史物化实现切片（权威证据边界与三个月预检）

日期：2026-09-13
基线：`main@2e9bdc36544c5320072969a2888180b6dfec2c7a`
对应合同：[`cr7_historical_materialization_contract_20260913.json`](cr7_historical_materialization_contract_20260913.json)
状态：`HISTORICAL IMPLEMENTATION RECORD / THREE-MONTH PREFLIGHT FAIL-CLOSED / DRAFT PR / INDEPENDENT DELTA REVIEW REQUIRED`

## 1. 本切片做了什么

本切片实现合同要求的物化边界，并完成三个固定月份的真实源观察预检；不代表
2020-01-01～2026-06-30 的真实历史已经物化或覆盖完整：

- `ResearchPanelBuilder.prepare_verified_projection()` 从现有 R1 路径提取只读的
  ReadModel/snapshot/canonical/identity/PIT 校验，返回内存投影；不会写 R1 artifact、manifest、
  `_SUCCESS` 或 committed pointer。`build_from_readmodel()` 仍保留原有 R1 发布行为。
- `research.historical` 只接受 `VerifiedResearchProjection`，拒绝未验证 caller identity，
  不导入 Provider、AmazingData、正式账号或网络调用。
- `CoverageBasisDescriptor` 严格验证 15 个合同字段、版本化 completeness method、源 snapshot、
  daily-bar 域、月度范围、source-selection fingerprint，以及不含自身 hash 引用的精确 canonical
  UTF-8 artifact bytes/hash。`AUTHORITATIVE_UPSTREAM` 不再接受任意 statement/inventory bytes、
  count 或 timestamp；新增 typed `AmazingDataAcquisitionReceipt`，仅由审阅过的 AmazingData
  三步 acquisition path 在完整请求、响应形状/范围校验和 `AnchoredRawEvidenceWriter` 留存成功后生成。receipt 绑定
  固定 method/operation、月份、Universe 选择、calendar、返回范围、schema/content/evidence hash、
  source snapshot 和 PIT/available-at；`AuthoritativeCoverageEvidence` 的直接 bridge 只消费这类
  receipt。夹具方法明确标记为 `TEST_FIXTURE_ONLY`，
  不具备普通历史 reader 的发布权限；普通 reader 只接受显式 `AUTHORITATIVE_UPSTREAM` 证据等级，
  并要求提供 raw capture root 重放 catalog 与 RawWriter closure。
- writer/runtime lock 只包含 dependency-lock content hash、Python runtime、Parquet writer engine、
  writer configuration version；materialization identity 按合同固定 23 个字段，并将 basis-set hash
  与 writer-lock hash 纳入 idempotency key。主机名、绝对路径、文件 mtime、墙上时间和凭证不进入身份。
- `OfflineHistoricalMaterializer` 在临时/夹具根目录规划 Development 48、Validation A 24、Holdout 6，
  共 78 个逻辑月；每月显式记录 `research_enabled`、`disabled`、`experimental` 三条 route，BSE
  不得进入 enabled route，window/split/primary-key/route 混淆直接 fail closed。
- 分区 Parquet、basis evidence、inventory 和 manifest 先写 `.staging/<materialization_id>`，完成
  字节/schema/row-count/semantic/primary-key/inventory 校验并写 `_SUCCESS.json` 后，才进行同卷目录
  原子 rename。失败时不出现可读 committed materialization；相同 identity 只允许经完整复核的
  idempotent replay，identity 相同但 bytes/inventory 改变则冲突，不使用 last-write-wins。
- `HistoricalMaterializationReader` 是独立的历史合同 reader：必须存在合法 committed `_SUCCESS.json`、
  78 月 inventory、每个月 `research_enabled` 的显式覆盖状态、basis evidence 和完整 hash 校验；
  `PARTIAL`/`UNRESOLVED` 以及 `TEST_FIXTURE_ONLY` 证据自动读取一律阻断，不改变现有 R1 reader。
- 历史上曾有一个固定范围的三个月 source preflight；按 Issue #66，该一次性 SPIKE 已删除，
  不再作为当前 production/acquisition 入口。原始交换仍只允许留在本地 ignored raw 目录，
  脱敏观察结果不能冒充完整 acquisition receipt。

本轮针对独立审阅的窄修复保留并强化了三项边界：覆盖状态按完整 78 个月聚合，稀疏来源不能得到
整体 OBSERVED；每个月的 `research_enabled` inventory 即使没有物理 artifact 也记录状态和原因；
覆盖验证使用匹配分区的 descriptor，并用 COMPLETE/PARTIAL 反转输入顺序回归验证确定性。

## 2. 当前明确没有完成的事项

以下事项不属于本 PR，也没有被本实现暗中完成：

- 真实 2020～2026H1 历史回填、universe sweep、Production 或 Formal/B1-B7；
- 真实完整范围 receipt **尚未生成**：三个月预检的三组 Provider sentinel 观察均成功，但该预检
  没有执行完整月份/完整 Universe acquisition，也没有可消费的 verified CR-4 projection，因此结果为
  `FULL_SCOPE_ACQUISITION_RECEIPT_NOT_PRODUCED`，未生成 authoritative sidecar，也未进入 materializer；
- BSE mapping/index 激活、CR-5/R2 feature export；
- Golden/H1/global baseline、策略和任何凭证/raw Provider payload 上传。

因此，夹具 helper `build_fixture_coverage_basis_descriptor()` 的 COMPLETE 只表示该离线夹具的
封存范围，不是市场覆盖真值，也不能作为未来生产历史运行的授权。

## 3. 重点审阅位置

| 审阅问题 | 对照位置 |
| --- | --- |
| R1 非发布投影是否零写入 | `src/ashare_state/research/panel.py` 的 `prepare_verified_projection()`；`tests/integration/test_r1_research_panel_integration.py` |
| basis 是否绑定精确 bytes/hash 和版本化 method | `src/ashare_state/research/historical.py` 的 `CoverageBasisDescriptor`、`verify_coverage_basis()` |
| 权威 sidecar 是否只能由 Owner-approved AmazingData receipt 产生，且可重放 retained capture | `src/ashare_state/research/historical.py` 的 `AmazingDataAcquisitionReceipt` / `AuthoritativeCoverageEvidence`；`src/ashare_state/providers/amazingdata/authoritative_history.py`；`tests/unit/test_cr7_historical_materialization.py` |
| 23 字段 identity 和 writer lock | `build_materialization_identity()`、`build_writer_runtime_lock_identity()` |
| 78 月和三 route inventory | `expected_partition_keys()`、`OfflineHistoricalMaterializer.plan()` |
| staging、marker、replay、冲突、failure invisibility | `OfflineHistoricalMaterializer.materialize()`、`HistoricalMaterializationReader` |
| 三个月真实源预检的固定范围和脱敏收据 | Issue #59 的历史提交/交接记录（已按 Issue #66 从当前树清理） |
| 对抗场景 | `tests/unit/test_cr7_historical_materialization.py` |

## 4. 本地验证与下一道门

三个月真实源预检已按固定范围执行：三个 split 的 calendar、historical code-list 和 daily-bar
sentinel 调用均返回 `OK`，但该 sentinel 预检没有执行完整月份/完整 Universe acquisition，因而没有
生成可消费的 receipt；当前实现把结论保持为 `FAIL_CLOSED_BLOCKED`，阻断码为
`FULL_SCOPE_ACQUISITION_RECEIPT_NOT_PRODUCED`，权威 evidence 为 `NOT_PRODUCED`，materializer 为
`NOT_ENTERED_FAIL_CLOSED`。既有 JSON 收据是整改前的历史记录，已按 Issue #66 从当前树清理；
本地 raw 交换只保留在 ignored 目录，不进入 GitHub。

最终本地门禁和 exact-head GitHub Actions 结果由 PR 交接记录；在新的 scheduler 决策前，不得把本
切片扩大成真实历史物化或生产执行。PR 保持 Draft，等待独立 delta review。

账号、密码、IP、端口、Token、Cookie、专有 SDK/runtime 和 Provider 原始 payload 不得进入 GitHub。
