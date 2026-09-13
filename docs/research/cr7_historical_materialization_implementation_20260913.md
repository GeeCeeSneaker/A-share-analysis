# CR-7 历史物化实现切片（仅离线夹具）

日期：2026-09-13
基线：`main@6d94a196089901b92a5b7a085922a1f7c4ffaaa2`
对应合同：[`cr7_historical_materialization_contract_20260913.json`](cr7_historical_materialization_contract_20260913.json)
状态：`LOCAL IMPLEMENTATION / OFFLINE FIXTURE ONLY / DRAFT PR / INDEPENDENT REVIEW REQUIRED`

## 1. 本切片做了什么

本切片实现合同要求的离线边界，不代表 2020-01-01～2026-06-30 的真实历史已经物化或覆盖完整：

- `ResearchPanelBuilder.prepare_verified_projection()` 从现有 R1 路径提取只读的
  ReadModel/snapshot/canonical/identity/PIT 校验，返回内存投影；不会写 R1 artifact、manifest、
  `_SUCCESS` 或 committed pointer。`build_from_readmodel()` 仍保留原有 R1 发布行为。
- `research.historical` 只接受 `VerifiedResearchProjection`，拒绝未验证 caller identity，
  不导入 Provider、AmazingData、正式账号或网络调用。
- `CoverageBasisDescriptor` 严格验证 15 个合同字段、版本化 completeness method、源 snapshot、
  daily-bar 域、月度范围、source-selection fingerprint，以及不含自身 hash 引用的精确 canonical
  UTF-8 artifact bytes/hash。当前只注册离线夹具方法；没有权威上游 completeness evidence 时，
  缺少 basis 的 enabled 月份只能得到 `UNRESOLVED_NOT_FOR_RESEARCH`，不能由 caller label、row count、
  月份连续性或已验证字节提升为 OBSERVED。
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
  78 月 inventory、basis evidence 和完整 hash 校验；`PARTIAL`/`UNRESOLVED` 自动读取一律阻断，
  不改变现有 R1 reader。

## 2. 当前明确没有完成的事项

以下事项不属于本 PR，也没有被本实现暗中完成：

- Provider/AmazingData 调用、真实 2020～2026H1 历史回填、universe sweep、Production 或 Formal/B1-B7；
- 真实上游 completeness evidence、BSE mapping/index 激活、CR-5/R2 feature export；
- Golden/H1/global baseline、策略和任何凭证/raw Provider payload 上传。

因此，夹具 helper `build_fixture_coverage_basis_descriptor()` 的 COMPLETE 只表示该离线夹具的
封存范围，不是市场覆盖真值，也不能作为未来生产历史运行的授权。

## 3. 重点审阅位置

| 审阅问题 | 对照位置 |
| --- | --- |
| R1 非发布投影是否零写入 | `src/ashare_state/research/panel.py` 的 `prepare_verified_projection()`；`tests/integration/test_r1_research_panel_integration.py` |
| basis 是否绑定精确 bytes/hash 和版本化 method | `src/ashare_state/research/historical.py` 的 `CoverageBasisDescriptor`、`verify_coverage_basis()` |
| 23 字段 identity 和 writer lock | `build_materialization_identity()`、`build_writer_runtime_lock_identity()` |
| 78 月和三 route inventory | `expected_partition_keys()`、`OfflineHistoricalMaterializer.plan()` |
| staging、marker、replay、冲突、failure invisibility | `OfflineHistoricalMaterializer.materialize()`、`HistoricalMaterializationReader` |
| 对抗场景 | `tests/unit/test_cr7_historical_materialization.py` |

## 4. 本地验证与下一道门

已执行最终门禁：全量 `pytest` 为 `1790 collected, 1787 passed, 3 skipped`；3 个 skip 均为既有
Windows symlink 权限限制。Ruff check/format、`mypy src`、`compileall`、`uv pip check`、合同 JSON
parse 和 `git diff --check` 均通过。PR #53 初始实现 head `9423625bbcbb386300765809276058995ff2e849`
对应 GitHub Actions CI #572，Ubuntu 3.14、Windows 3.12、Windows 3.14 均为 `success`，GT-H3B #110
按策略 `skipped`。PR 仍保持 Draft，当前待独立 Reviewer 对 exact head 复核；在新的 scheduler 决策前，
不得把本切片扩大成真实历史物化或生产执行。

账号、密码、IP、端口、Token、Cookie、专有 SDK/runtime 和 Provider 原始 payload 不得进入 GitHub。
