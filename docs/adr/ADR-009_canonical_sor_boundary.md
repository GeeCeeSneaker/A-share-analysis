# ADR-009: Canonical System of Record 边界（审计 P1-17）

- 状态：ACCEPTED
- 日期：2026-08-22
- 依据：第一阶段代码审计报告 §23（P1-17）
- 影响范围：存储链路、P0a Canonicalizer、读模型

## 决策

```text
Canonical Immutable Parquet = System of Record（唯一真相源）
DuckDB                      = Metadata + View / Index / Governance / Read Model（派生读模型）
```

## 规则

1. `meta_data_snapshot_component` / `meta_feature_artifact_component` 登记的
   不可变 Parquet 文件是 Canonical 事实的唯一权威形态（content_hash 可验证）；
2. `fact_*` DuckDB 表是**读模型**：由 Canonical Parquet 派生加载，用于快速
   查询与治理查询；它可以随时从 Parquet 重建；
3. **禁止**出现"Canonical Parquet + DuckDB mutable fact"两份都自称真相的
   状态：fact 表的行集身份（rowset identity）不进入 `data_manifest_hash`，
   因此它不参与 Exact Replay 承诺——Exact Replay 永远以 Parquet + manifest
   为准；
4. 任何 fact 表与 Parquet 的不一致视为读模型过期，处理方式是重建读模型，
   而非"修正" Parquet。

## 若未来需要 DuckDB 作为 SoR

必须开新 ADR，且 `data_manifest_hash` 必须把 DuckDB rowset identity 纳入
计算（当前架构明确不走这条路——审计同款建议）。

---

# 附：STAGING 生命周期决策（审计 P1-15，方案 B）

**决策**：STAGING 只存在于 run/filesystem 层，**不**进入元数据表状态机：
`meta_data_snapshot` / `meta_feature_artifact_set` 只在完成后 INSERT
`DATA_VALIDATED` / `FEATURE_VALIDATED` 行（hash NOT NULL 由此天然自洽）。

理由：真实 STAGING 阶段未知最终 manifest hash，方案 A（nullable hash +
validated 时 service invariant）需要额外的状态机复杂度；方案 B 用
"metadata 只在完成时写入"达成同样的不变量，且与 8 步原子提交顺序
（文件落盘 → 登记 component → 事务切指针）天然一致。

含义：状态枚举中的 STAGING 仅保留给 `meta_ingest_run`（原始抓取阶段，
那里没有 manifest hash 语义）。
