# 审计整改跟踪（2026-08-22 审计 → 整改映射）

> 审计报告：`docs/design/A-share-analysis_第一阶段代码审计报告_20260822.md`
> 整改顺序按审计 §28：Patch A（M0 Integrity）→ Patch B（Provider Reliability）→ Patch C（Canonical PIT）→ Contract Tests

## P0 关闭状态

| ID | 问题 | 状态 | 修复位置 |
|---|---|---|---|
| P0-01 | Atomic Writer 可覆盖旧文件（破坏 Exact Replay） | CLOSED | atomic_files.py：`ImmutableFileExistsError` 默认禁止覆盖；`allow_existing_identical` 仅同哈希幂等；文件名带输出身份 |
| P0-02 | Publish 未验证完整 lineage | CLOSED | publish.py：snapshot/artifact/feature_set/pipeline_run/universe 七项 invariant 全校验 |
| P0-03 | Timeout 非硬超时 + 权限错误被重试伪装成超时 | CLOSED | timeout.py：先分类后重试，PERMISSION/AUTH/SCHEMA 禁止重试 |
| P0-04 | Mapper 用 1970/0.0 哨兵隐藏缺失 | CLOSED | mapper.py：关键字段缺失/解析失败 → `MappingValidationError`；`first_present` 替代 `or` |
| P0-05 | Canonical PIT 治理列不完整 | CLOSED | 006_canonical_governance_hardening.sql（不改 005） |
| P0-06 | IDENTITY_FALLBACK 未进 Publish Gate | CLOSED | publish.py：publish validation gate 强制 NO_IDENTITY_FALLBACK |

## P1 关闭状态

| ID | 状态 | 说明 |
|---|---|---|
| P1-01 orphan 根路径错位 | CLOSED | find_orphan_files 改收 data_root |
| P1-02 Capability Gate no-op | CLOSED | ProviderUseMode.SPIKE/PRODUCTION；PRODUCTION 仅 APPROVED |
| P1-03 Capability Approval 不持久化 | CLOSED | 持久化到 meta_provider_capability + evidence bundle |
| P1-04 失败 Call 无 Envelope | CLOSED | RawEnvelope 增加 status/error_class/duration/attempt，成功失败都记录 |
| P1-05 Migration 删除/改名未检测 | CLOSED | ledger 必须是 repo 序列完整前缀 + filename 精确匹配 + 非法命名 BLOCK |
| P1-06 Logical URI alias | CLOSED | normalize 后不一致即 `NonCanonicalLogicalUriError` |
| P1-07 account_profile_id 碰撞 | CLOSED | 加入 provider/env/host/username-hash |
| P1-08 profile 解析失败仍 login_ok | CLOSED | 拆分 auth_ok/profile_parsed/entitlement_verified |
| P1-09 Error 分类过激 | CLOSED | 未知错误默认 ProviderSdkInternalError；permission 映射仅限已验证模式 |
| P1-10 异常基类重复 | CLOSED | 统一 providers/errors.py，amazingdata 继承扩展 |
| P1-11 loader/doctor 不一致 | CLOSED | ABI resolver 单一实现；缺 SDK 统一 ProviderUnavailableError |
| P1-12 stdout capture 非线程安全 | CLOSED | 全局 RLock 串行化 |
| P1-13 printf-style masking | CLOSED | filter 处理后清 args；补测试 |
| P1-14 Password SecretStr | CLOSED | pydantic SecretStr |
| P1-15 STAGING/hash 冲突 | CLOSED | 方案 B：metadata 表只在完成时 INSERT validated（文档化决策） |
| P1-16 pipeline_run 未锁 policy 版本 | CLOSED | 006 加 source_policy_version/availability_policy_version |
| P1-17 SoR 边界 | CLOSED | 文档化：Parquet=SoR，DuckDB=元数据+读模型（ADR-009） |
| P1-18 敏感信息 | CLOSED | 账号掩码、地址别名化、.gitignore 加 vendor/ 与 *.whl |
