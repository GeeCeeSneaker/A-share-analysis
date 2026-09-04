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
| ADR-018 | Review Publish Byte-Identity + Manifest Seal from reviewed_bytes | ACCEPTED | 2026-08-25 | [ADR-018](ADR-018_review_publish_byte_identity.md)，amendment to ADR-017；R4-A2.10/CR-1.2.6 P0-01/02 + P1（DM-CR-20260825-022..026）；**§4 amended by R4-A2.11/CR-1.2.7**（lock-before-preflight 修正其覆盖范围 overclaim，DM-CR-20260825-027..029，2026-08-25）；**VERIFIED 2026-08-26**（R4-A2.x/CR-1.x 审计链 CLOSED） |
| ADR-019 | SDK Runtime Lifecycle State Machine + Runtime Gate Separation | ACCEPTED | 2026-08-26 | [ADR-019](ADR-019_sdk_lifecycle_runtime_gates.md)，R4-A3 A3-01..04（DM-CR-20260826-030/031/032/033）；amendments 2026-08-27/28（A/B）；**VERIFIED 2026-08-28**（R4-A3.x 链 CLOSED） |
| ADR-020 | Endpoint Requirement Contract（显式端点身份合同） | ACCEPTED | 2026-08-28 | [ADR-020](ADR-020_endpoint_requirement_contract.md)，R4-B1（DM-CR-20260828-046/047/048）；amendments 20260830 C/D（语义修正 / anti-bypass / cross-binding）；**VERIFIED 2026-08-30**（R4-B1.x 链 CLOSED） |
| ADR-021 | Publish Validation Exactness（发布验证精确性） | ACCEPTED | 2026-08-30 | [ADR-021](ADR-021_publish_validation_exactness.md)，R4-B2 B2-01..06（DM-CR-20260830-054/055/056）；amendments B2.1/B2.2/B2.3（DM-CR-20260830-057..060 / DM-CR-20260831-061/062）；**VERIFIED 2026-08-31**（R4-B2.x 链 CLOSED） |
| ADR-022 | Provider Normalization and Quarantine（提供方归一化与隔离） | **ACCEPTED** | 2026-08-31 | [ADR-022](ADR-022_provider_normalization_quarantine.md)，CR-2（DM-CR-20260831-063）+ CR-2.1 Amendment A（DM-CR-20260831-064）+ CR-2.2 Amendment B（DM-20260901-065）+ CR-2.3 Amendment C（DM-20260901-066）+ CR-2.4 Amendment D（DM-20260901-067：anchored raw ingestion boundary）；**Reviewer ACCEPTED / VERIFIED 2026-09-01**（"CR-2.4最终复审结论与CR-3开发工作要求_20260901"，Reviewed HEAD `0b4ef7a`）——CR-2 全链 VERIFIED / CLOSED / FREEZE |
| ADR-023 | AvailabilityPolicy + Canonical Source Selection（时间可用性策略与 Canonical 源选择） | **ACCEPTED / VERIFIED** | 2026-09-02 | [ADR-023](ADR-023_availability_policy_canonical_selection.md)，CR-3（DM-20260901-068）+ CR-3.1 Amendment A（DM-20260901-069）+ CR-3.2 Amendment B（DM-20260901-070）+ CR-3.3 Amendment C（DM-20260902-071）+ CR-3.4 Amendment D（DM-20260902-072）+ CR-3.5 Amendment E（DM-20260902-073）+ CR-3.6 Amendment F（DM-20260902-074）；2026-09-02 21:24 复审裁决 VERIFIED / CLOSED / FREEZE——CR-3 全链关闭 |
| ADR-024 | SnapshotBuilder + DuckDB ReadModel（CR-4 快照与读模型层） | ACCEPTED / VERIFIED | 2026-09-03 | [ADR-024](ADR-024_snapshot_builder_readmodel.md)，CR-4（DM-20260903-075/076/077）：CR-4 全链 VERIFIED / CLOSED / FREEZE；PR #1 已于 `a9c5cee8e3daa6f76dfde961bffc61c139dd6d3a` 合并，CR-4.4 final review accepted |

| ADR-025 | Deterministic Feature Layer / PIT / Window / Missingness Contract（CR-5） | ACCEPTED / VERIFIED | 2026-09-03 | [ADR-025](ADR-025_feature_layer_pit_missingness.md)，CR-5 / CR-5.1 / CR-5.2 / CR-5.2.1 VERIFIED / CLOSED / FREEZE；PR #3 merged at 075ad80e5254998a0662a0f9c1cadc107a217fdb |

| ADR-026 | Deterministic Market State Interpretation Contract（CR-6） | PROPOSED / PENDING_REVIEW | 2026-09-04 | [ADR-026](ADR-026_deterministic_market_state_interpretation.md)，CR-6.0–6.4 evidence synchronized；Reviewer pending；PR #6 remains open | 

## 纪律

- INHERITED：决策正文位于冻结设计文档（`docs/design/`），本索引仅登记；
- ACCEPTED：正文在本目录，独立成文；
- 新 ADR 只增不改；推翻旧决策时旧 ADR 标记 SUPERSEDED 并指向新 ADR。
