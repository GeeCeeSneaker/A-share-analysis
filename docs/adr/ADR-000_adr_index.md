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
| ADR-010 | Raw Evidence Model（显式 Exchange → RawWriter → Bundle） | ACCEPTED | 2026-08-24 | [ADR-010](ADR-010_raw_evidence_model.md)，R4-A2.3/CR-1.1 P0-01/02/04 落地（DM-CR-20260824-006）；**amended by ADR-012**（meta-anchored 双向闭合，2026-08-24） |
| ADR-011 | 交易制度事实的版本化数据层 | ACCEPTED | 2026-08-24 | [ADR-011](ADR-011_trading_rule_data_sor.md)，R4-A2.3 P0-06/07 落地（DM-CR-20260824-005）；**amended by ADR-012**（run 绑定 + review gate，2026-08-24） |
| ADR-012 | Raw Exchange Closure + Trading Rule Binding（R4-A2.4/CR-1.2） | ACCEPTED | 2026-08-24 | [ADR-012](ADR-012_raw_exchange_closure.md)，amendment to 010/011；DM-CR-20260824-008/009/010/011；**amended by ADR-013**（版本模型 + 事件分类学，2026-08-25） |
| ADR-013 | Trading Rule Version Model + CA Event Taxonomy（R4-A2.5/CR-1.2.1） | ACCEPTED | 2026-08-25 | [ADR-013](ADR-013_rule_version_model.md)，amendment to ADR-012；DM-CR-20260825-001/002/003；**amended by ADR-014**（selector 契约收紧，2026-08-25） |
| ADR-014 | Rule Manifest Selector Contract（confinement + coherence） | ACCEPTED | 2026-08-25 | [ADR-014](ADR-014_rule_manifest_selector.md)，amendment to ADR-013；R4-A2.6 P0-03/04（DM-CR-20260825-006）；**contract 补全 by ADR-015 §5**（pre-access confinement / required coherence，2026-08-25） |
| ADR-015 | Corporate-Action Provider-Shape Validation Adapter | ACCEPTED | 2026-08-25 | [ADR-015](ADR-015_ca_provider_shape_adapter.md)，amendment to ADR-013 §4 + ADR-014 补全；R4-A2.7/CR-1.2.3 P0-01..04（DM-CR-20260825-008/009/010/011）；**amended by ADR-016**（原子边界 / lexical-first / review preflight，2026-08-25） |
| ADR-016 | Atomic Exchange Boundary + Lexical-First Confinement + Review Input Integrity | ACCEPTED | 2026-08-25 | [ADR-016](ADR-016_atomic_boundary_integrity.md)，amendment to ADR-013/015；R4-A2.8/CR-1.2.4 P0-01..03 + P1（DM-CR-20260825-013/014/015/016）；**amended by ADR-017**（exact-byte seal 修正其 §3 overclaim，2026-08-25） |
| ADR-017 | Review Exact-Byte Seal + Output Confinement + Cross-Platform Byte Truth | ACCEPTED | 2026-08-25 | [ADR-017](ADR-017_review_seal_output_confinement.md)，amendment to ADR-016；R4-A2.9/CR-1.2.5 P0-01/02 + P1 + CI 根因修复（DM-CR-20260825-017/018/019/020）；**amended by ADR-018**（输出侧 byte identity 闭合其 §1 未完成环，2026-08-25） |
| ADR-018 | Review Publish Byte-Identity + Manifest Seal from reviewed_bytes | ACCEPTED | 2026-08-25 | [ADR-018](ADR-018_review_publish_byte_identity.md)，amendment to ADR-017；R4-A2.10/CR-1.2.6 P0-01/02 + P1（DM-CR-20260825-022..026）；**§4 amended by R4-A2.11/CR-1.2.7**（lock-before-preflight 修正其覆盖范围 overclaim，DM-CR-20260825-027..029，2026-08-25） |

## 纪律

- INHERITED：决策正文位于冻结设计文档（`docs/design/`），本索引仅登记；
- ACCEPTED：正文在本目录，独立成文；
- 新 ADR 只增不改；推翻旧决策时旧 ADR 标记 SUPERSEDED 并指向新 ADR。
