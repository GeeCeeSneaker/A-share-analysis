# 第二轮审计整改跟踪（2026-08-22）

> 审计报告：`docs/design/A-share-analysis_第二轮代码审计与下一阶段开发要求_20260822.md`
> 审计 HEAD：`99cca13`（整改前）
> 整改提交：`65c0d89`（R2A）/ `e6187e3`（R2B+R2C主体）/ `6359d20`（R2C完成）
> **状态**：R2A / R2B / R2C 全部落地；238 tests 全绿；门禁干净；CI 三矩阵验证中

## 项目状态更新（按审计 §0）

```text
P0-M0 Engineering Foundation        PASS
Round-1 Audit Remediation           SUBSTANTIALLY CLOSED（维持）
Round-2 Residual Hardening          CLOSED（本轮 R2A/R2B/R2C）
P0-M-1A Trial L1 Smoke              READY（脚本硬化完成，待交易时段实测）
P0-M-1B Production Capability Spike FRAMEWORK READY（待正式账号）
Real P0a                            BLOCKED（唯一剩余门：R2-P1-12
                                    Canonical Runtime + GO_CORE）
```

## R2 发现项整改映射

| ID | 问题 | 落点 | 状态 |
|---|---|---|---|
| R2-P0-01 | spike_runner 导入断链 | 框架重写到 `src/ashare_state/spike/`（mypy/pytest 覆盖）；scripts/ 只留 thin CLI；CI 加 compileall + dry-run gate；`test_spike_runner_imports` 防回归 | ✅ `65c0d89` |
| R2-P0-02 | Spike 绕过 Production Adapter | `SpikeTarget` 单一访问路径：真实走 `AmazingDataSession → Provider(SPIKE)`；FakeTarget 仅限物理隔离的 dry-run；provider 补 `get_hist_code_list`/`query_kline`（文档化 surface）；探针零直接 SDK import | ✅ `65c0d89` |
| R2-P0-03 | 调用成功=PASS | `CaseResult` 八态状态机；validator 实现退市包含性/单位一致性/ST停牌域/涨跌停包络/复权连续性/历史深度/符号映射/SDK行为八类语义校验；`core_gate_satisfied()` 只认 VALIDATED_PASS（DIFF_EXPLAINED 需 validator 显式等价裁决） | ✅ `65c0d89` |
| R2-P0-04 | 无 Run Scope | `SpikeRun`（run_kind/provider/account profile/版本/commit/lock hashes）；`data/spike/{dry-run,trial,production}/<run-id>/` 物理隔离；verdict 只聚合一个 CLOSED PRODUCTION run；evidence 无损（repr 禁止→抛错）+ 不可变（UUID 名/覆盖阻断）+ content_hash；case_id 语义编码 + run 内唯一 | ✅ `65c0d89` |
| R2-P0-05 | Fallback Gate 可绕 | migration 008 `meta_artifact_validation`；publish 强制 validation record 且 `identity_fallback_count==0`/`blocking_dq_count==0`；**删除 caller 参数** `fallback_security_ids`；`record_artifact_validation()` 唯一写入口 | ✅ `e6187e3` |
| R2-P0-06 | 血缘未闭合 | publish 七项校验：artifact.calc_run==run（RECOVERY run 明确豁免语义）/code_commit/env_lock/config_hash 三元组/run-snapshot 双 policy 版本；PRODUCTION publish 强制 pipeline_run_id（manual 需显式 allow_manual_publish） | ✅ `e6187e3` |
| R2-P1-01 | Approval 可绕 Evidence | `approve_and_persist_capability()` 唯一入口：先验证后写、单事务（UPDATE 仅治理列，metadata 永不擦除）、失败 ROLLBACK + 缓存回滚；`load_approvals` 恢复完整 provenance 且 DB CANDIDATE 主动降级缓存 APPROVED | ✅ `e6187e3` |
| R2-P1-02 | Governance 误记 Permission | `ProviderGovernanceError`/`ProviderCapabilityNotApprovedError`；PRODUCTION 拒 CANDIDATE 抛治理错误 | ✅ `e6187e3` |
| R2-P1-03 | 查询失败归因过宽 | 仅 VERIFIED 签名（NoneType 下标）判 Permission；`查询失败` → SdkInternal + `classification_rule_id=QUERY_FAIL_UNCLASSIFIED`/`confidence=LOW` | ✅ `6359d20` |
| R2-P1-04 | Doctor 未确认实际 DLL | 两级 verdict：`RUNTIME_PACKAGE_VERIFIED`（wheel 级）≠ `RUNTIME_ACTUAL_LOAD_VERIFIED`；login+最小查询后重新枚举模块 | ✅ `6359d20` |
| R2-P1-05 | Market/Symbol/Calendar | `ProviderSymbolNormalizer` 单一规则（600000→600000.SH）；MARKET_CODE 必填；daily bar 同规则归一；严格日历（一个坏日期隔离整个 payload） | ✅ `e6187e3` |
| R2-P1-06 | L1 时区/状态/lifecycle | Asia/Shanghai 判定；NOT_TESTABLE_TIME/PERMISSION/ACCOUNT/FAIL_NO_EVENTS 四态分离；event_time 解析为 aware datetime；lifecycle（register/run/unregister/stop）先实测记录再下结论 | ✅ `6359d20` |
| R2-P1-07 | TOCTOU | `FileCommitCoordinator` 进程级串行（reentrant）；并发同目标竞速测试：恰好一个提交、另一者 blocked | ✅ `6359d20` |
| R2-P1-08 | 8-hex 路径碰撞 | mock 路径 tag 全量 32-hex | ✅ `e6187e3` |
| R2-P1-09 | 迁移序列连续 | `MigrationSequenceGapError`：repo 必须 001..N 连续，fresh DB 也阻断 | ✅ `e6187e3` |
| R2-P1-10 | STAGING 语义残留 | `versioning.py` service 规则：snapshot/artifact 元数据只允许 validated 插入（ADR-009）；009 迁移 universe_activation 台账 | ✅ `e6187e3` |
| R2-P1-11 | 版本不可变激活 | feature set DRAFT→ACTIVE 成员不可变；universe rule_hash 激活台账；SourcePolicy 沿用 Round-1 状态机 | ✅ `e6187e3` |
| R2-P1-12 | Canonical PIT Runtime | **审计 §23 定位为 Real P0a Entry Gate**（RawWriter/Canonicalizer/AvailabilityPolicyEngine/QuarantineStore 等）——按 §27 列入下一阶段并行开发线，未在本轮 | ⏭ 下一阶段 |

## §33 Contract Tests 覆盖

| 组 | 要求 | 文件 |
|---|---|---|
| Spike | 9 项全落地 | `test_spike_framework.py`（18 tests） |
| Publish | 8 项全落地 | `test_publish_validation_gate.py`（10）+ `test_publish_lineage.py` 更新 |
| Capability | 5 项全落地 | `test_capability_governance.py`（9） |
| Mapper | 4 项全落地 | `test_mapper_strict_semantics.py`（12）+ 旧测试更新 |
| Runtime | 2 项落地 | doctor 两级 verdict + login 后 reprobe（`6359d20`；doctor 单测在 provider_reliability 中扩展） |
| Storage | 3 项全落地 | `test_commit_coordinator.py`（3）+ `test_migrations.py` repo-gap |

## §34 CI 更新

`ci.yml` 新增：`compileall scripts` + `spike_runner --dry-run` 两道 gate（所有三矩阵）。

## 下一步（按审计 §36 顺序）

1. **R2-P1-12 Canonical Runtime**（Real P0a Entry Gate）：RawWriter → ProviderNormalizedWriter → Canonicalizer → AvailabilityPolicyEngine → QuarantineStore → SnapshotBuilder → Artifact Validator（审计 §27 可并行开发清单）
2. **Trial L1 Smoke**：交易时段跑 `l1_subscription_test.py` 阶梯 1→5→20（100 只仅用于订阅上限行为）
3. **正式账号 P0-M-1B**：`spike_runner --production` B2→B7 + Early Stop 纪律 + 单 run verdict
4. **GO_CORE → P0a**：Canonical Vertical Slice → Trend BASE → Stage A-D 放量
