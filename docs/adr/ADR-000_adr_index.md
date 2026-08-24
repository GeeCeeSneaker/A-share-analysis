# ADR 索引

ADR（Architecture Decision Record）记录对系统有长期影响的决策。编号一经分配不再复用。

| 编号 | 标题 | 状态 | 日期 | 备注 |
|---|---|---|---|---|
| ADR-001 | Why Parquet + DuckDB | INHERITED | 2026-08-21 | 冻结基线 §0.5/5/39.13，正文见设计文档 |
| ADR-002 | Security ID strategy（UUIDv5 固定命名空间） | ACCEPTED | 2026-08-21 | 冻结基线 §6.2 + 设计裁决 §6；namespace 字面量 `b2e7b5e4-28f5-5384-8508-bcc20755d552` 固化于 `src/ashare_state/identity/security_id.py`，**发布后永不可变** |
| ADR-003 | Theme PIT semantics | PLANNED | - | Phase 1 前细化，冻结基线 §6.20 |
| ADR-004 | Feature version policy | INHERITED | 2026-08-21 | 冻结基线 §28，语义版本规则 |
| ADR-005 | EOD total vs regular amount | INHERITED | 2026-08-21 | 冻结基线 §6.6/8.5，Phase 0 默认 total_* |
| ADR-006 | Table format（Iceberg/Delta）评估触发器 | PLANNED | - | 首次需要多写者/自动 GC/对象存储高频时间旅行时触发，冻结基线 §5.8 |
| ADR-007 | P0 阶段 Tushare 不可用的单源运行风险 | ACCEPTED | 2026-08-21 | [ADR-007](ADR-007_p0m0_tushare_unavailable.md) |
| ADR-008 | DuckDB 进程级独占所有权模型 | ACCEPTED | 2026-08-21 | [ADR-008](ADR-008_duckdb_process_model.md)，设计裁决 P0-1 的落地 |
| ADR-009 | Canonical SoR 边界 | ACCEPTED | 2026-08-22 | [ADR-009](ADR-009_canonical_sor_boundary.md) |
| ADR-010 | Raw Evidence Model（显式 Exchange → RawWriter → Bundle） | ACCEPTED | 2026-08-24 | [ADR-010](ADR-010_raw_evidence_model.md)，R4-A2.3/CR-1.1 P0-01/02/04 落地（DM-CR-20260824-006） |
| ADR-011 | 交易制度事实的版本化数据层 | ACCEPTED | 2026-08-24 | [ADR-011](ADR-011_trading_rule_data_sor.md)，R4-A2.3 P0-06/07 落地（DM-CR-20260824-005） |

## 纪律

- INHERITED：决策正文位于冻结设计文档（`docs/design/`），本索引仅登记；
- ACCEPTED：正文在本目录，独立成文；
- 新 ADR 只增不改；推翻旧决策时旧 ADR 标记 SUPERSEDED 并指向新 ADR。
