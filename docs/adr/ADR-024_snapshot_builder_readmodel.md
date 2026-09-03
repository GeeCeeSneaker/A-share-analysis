# ADR-024: SnapshotBuilder + DuckDB ReadModel（CR-4 快照与读模型层）

## Status

- **Status**: PROPOSED（2026-09-03，CR-4 首批交付；Reviewer 复审裁决待定——本 ADR 在复审通过前不自称 ACCEPTED）
- **Deciders**: 开发方（设计实现）；Design / Audit Review（裁决 pending）
- **Date**: 2026-09-03
- **Work Requirement**: `docs/design/A-share-analysis_CR-4_SnapshotBuilder及DuckDBReadModel开发工作要求_20260902.md`（audit 20260902，含 CR-3 全链 closure 裁决 ff3808b7a5036246ea11e37173aa31d863beb2d9 与 CR-4 启动裁决）

## Context

CR-3 已交付 Verified Canonical Truth（ADR-023 ACCEPTED）。CR-4 在其上建立下游消费层：
domain-partitioned point-in-time snapshot（SnapshotBuilder）与 DuckDB 查询模型（ReadModel
Rebuild）。本 ADR 回答工作要求 §5 的十个设计问题。

## Decisions（工作要求 §5 十问十答）

### 1. Snapshot 输入是什么？SnapshotBuilder 是否直接读 Canonical parquet？

**输入 = CR-4.1 公共消费验证器 `verify_canonical_run_for_consumption`（`src/ashare_state/canonical/verifier.py`）的 VerifiedCanonicalRun**。Builder 绝不直接读 canonical parquet 文件、绝不重新实现 canonical 校验。验证器内部复用 CR-3 的唯一实现（typed identity seal / 共享 artifact closure verifier / findings truth / sealed-input 权威+物理验证——`CanonicalRunner` 的方法），无第二套较弱副本。与 exact replay 的刻意区别：消费不要求 sealed CR-2 inputs 仍在 current discovery 中（合法 superset 增长不得追溯破坏已 mint 的 SUCCESS 消费），但要求 ledger 存在 + identity 相等 + 物理/anchor 健康。

### 2. Snapshot identity 怎么计算？（确定性推导 + 变化条件）

`snapshot_base_hash = sha256(canonical JSON of {canonical_run_id, canonical manifest_hash, canonical requested_domains_hash, canonical selected_semantic_hash, canonical as_of, snapshot_contract_version, snapshot_builder_code_fingerprint})`；`snapshot_id = UUID5(SNAPSHOT_NAMESPACE, base_hash)`。identity 从 canonical **run-level seals**（非投影行）派生——可先算后写、manifest 原语可重算。变化条件：canonical run 不同（输入/世界/派生 seal 变）→ 新 snapshot；snapshot 合同版本或 builder 代码指纹变 → 新 snapshot；同一 verified canonical run 重建 → 同一 snapshot id（幂等）。

### 3. artifact 磁盘布局？

`snapshot/contract=snapshot-v1/as_of=<YYYYMMDDTHHMMSSZ>/snapshot=<snapshot_id>/<domain>.parquet + manifest.json(LAST)`，root 同 canonical artifacts 树（`normalized_root`）。artifact 集 == 请求 domain 集（精确）；manifest 最后写入（P0-A11）。

### 4. snapshot identity 是否包含 builder code fingerprint？代码变化会怎样？

包含（`snapshot_builder_code_fingerprint()`：snapshot/schema.py + canonical/verifier.py + snapshot/builder.py 源码 SHA-256，行尾归一）。代码变化 → 新 fingerprint → 新 snapshot id（历史保留，append-only）；`verify_snapshot` 拒绝验证"由不同 builder 代码版本构建"的 snapshot（当前代码无法证明其构建规则）。

### 5. per-domain artifact schema 从哪个单一事实源来？

版本化 schema registry（`snapshot/schema.py`：`DomainSnapshotSchema`/`ColumnSpec`/`DType`）。每个 supported domain 声明精确列集 + logical dtype + nullability + key arity + key projection 索引。Builder 投影 / snapshot verifier 物理验证 / DuckDB ReadModel 建表与 schema seal **三方消费同一 registry**，无第二套 schema。

### 6. typed key projection 怎么处理？（trade_calendar.market / adj_factor.factor_type）

canonical_key 严格 JSON 数组 round-trip 验证（decode → arity → 全 str → re-encode 一致）。**market 是 canonical payload 字段**（trade_calendar 行自带）；**factor_type 是 key projection**（canonical key 第 3 段 decode，ColumnSpec.key_index=2）——不是 canonical payload 字段，snapshot 表以显式 key projection 列携带。

### 7. lineage 字段保留？

P0-A08：**全部 canonical selected-row lineage 字段逐字保留**（available_at/ingested_at/availability_basis/availability_policy_version/selected_provider/source_normalization_run_id/source_output_name/source_row_ordinal/source_row_identity_hash/source_raw_request_id/source_raw_evidence_hash/source_mapper_identity/source_policy_version/canonical_contract_version/canonical_key/security_id/canonical_domain/payload）。snapshot 只**新增两个投影**：canonical_run_id / snapshot_id（列名即语义，永不冒充 canonical truth）。PIT 契约断言 available_at <= as_of（fail closed）。

### 8. migration 022 是什么？

`meta_snapshot_build`（snapshot 构建账本）：snapshot_id PK / canonical_run_id / canonical_manifest_uri+hash / canonical_as_of / requested_domains_json+hash / snapshot_contract_version / builder_code_fingerprint / manifest_uri+hash / artifact_set_hash / snapshot_semantic_hash / row_count_total / status / error_message / started_at / completed_at。**history append-only：重复 snapshot_id → fail；exact retry → 幂等 replay（ledger 存在 + 全物理 verify）**；目录存在但 ledger 无行 → 显式 fail closed（crash 残留，人工检查）。canonical_as_of 与 canonical ledger 列同名同型（TIMESTAMPTZ，UTC instant 语义）。

### 9. ReadModel rebuild 如何原子发布？

temp 文件构建（`readmodel/contract=readmodel-v1/snapshot=<id>/.readmodel.building.duckdb`）→ 建表（registry 精确类型 + PK(canonical_key)）+ INSERT（`read_parquet(hive_partitioning=false)`——**防路径 `contract=/as_of=/snapshot=` 段被误读为分区列**）→ **在 temp 库上验证 logical seal**（表集精确 / 行数 / key 唯一 / 从表内容重算 semantic hash == snapshot seal / schema 精确（TIMESTAMP WITH TIME ZONE 显式时区）/ meta 表）→ `Path.replace` 原子替换确定性目标。失败：temp 删除、旧目标字节不变（无部分/损坏模型可见）。**semantic hash 计算前把 DuckDB fetch 的 TIMESTAMPTZ 归一化回 UTC**（session 时区否则漂移字符串序列化）。

### 10. 表结构固定如何保证？（stale table / schema drift）

每次 rebuild 是全新 temp 库（不继承旧表）→ snapshot B 不会有 snapshot A 的表。表集 seal：`{rm_<domain> for requested} ∪ {rm_snapshot_meta, rm_domain_meta}` 精确比对；列级 `information_schema` 与 registry 的 DuckDB 类型映射精确比对；logical semantic hash 从表内容重算 == snapshot 域 seal（列值/行数/顺序的完整逻辑等值证明）。

## Implementation Structure

```text
src/ashare_state/canonical/verifier.py    CR-4.1 公共消费边界（唯一 canonical 读取入口）
src/ashare_state/snapshot/schema.py       版本化 schema registry（单一事实源）
src/ashare_state/snapshot/models.py       identity 派生 + 结果模型
src/ashare_state/snapshot/builder.py      SnapshotBuilder + migration 022 ledger 事务
src/ashare_state/snapshot/verifier.py     verify_snapshot（identity/artifact/cross-bind 重算）
src/ashare_state/readmodel/schema.py      DuckDB 类型映射（READMODEL_CONTRACT_VERSION）
src/ashare_state/readmodel/duckdb_model.py DuckDBReadModel（temp→seal→原子替换）
migrations/022_snapshot_build.sql         meta_snapshot_build
```

## Consequences

- 下游（feature 计算/发布）只能从 verified snapshot/readmodel 读——canonical truth 的单一消费路径成立。
- CR-4 层边界（AST guard 测试）：snapshot/ 与 readmodel/ 禁止 import providers / normalization / raw_writer；禁止 pandas/talib/numpy/scipy/sklearn（无特征计算）。
- **CR-4 实现期间发现并显式申报的 CR-3 latent 缺陷**（提请 Reviewer 在 CR-4 复审中一并裁决，非悄悄修复）：CR-3 `_write_artifacts` 的 selected/decision semantic seal 曾对**未对齐 rows**计算，而 parquet 写入 `_align_schema` 对齐后的 rows——多 domain 混合时 exact replay 的 recompute 必然误报 DAMAGED（fail-closed 方向的 false positive；单 domain key 集合一致故 1179 项既有回归全绿、从未暴露）。最小修复：seal 改为对 aligned rows 计算（单 domain 行为逐字节不变）；新增 `TestMultiDomainReplayRegression` 回归。

## Testing

1235/0（1179 → 1235，+56：`test_snapshot.py` 44（consumption verifier 10 / builder 21 / schema projection 3 / boundary 10（含 parametrize））/ `test_readmodel.py` 11 / `test_canonical.py` 多 domain replay 回归 1；migration 测试更新至 22 链）。mandatory 1-50 全对应（见 CR-4 工作要求 Implementation Mapping）。
