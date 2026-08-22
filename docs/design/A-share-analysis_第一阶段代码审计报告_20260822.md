# A-share-analysis 第一阶段代码审计报告

> 仓库：`GeeCeeSneaker/A-share-analysis`  
> 审计分支：`main`  
> 审计 HEAD：`93ae53283e5697f53d052589f7f56a204d187909`  
> 初始阶段提交：`bb2779bfda8b8ec591f93d45fde9363c2022170b`  
> 基线：`A股市场态势数据基座（日频模块）V1.3.2 Frozen Baseline`  
> 审计日期：2026-08-22  
> 审计性质：代码静态审计 + 架构契约一致性审计

---

# 0. 审计结论

第一阶段代码整体质量较好，现有架构**不需要推翻**。以下方向已经基本正确并值得继续：

- DuckDB 进程级独占 Owner；
- UUIDv5 Security ID；
- `data_snapshot_id / feature_artifact_set_id / publish_id` 三层身份；
- Manifest Hash 跨根目录确定性；
- Migration checksum + transactional rollback；
- Mock E2E / Failure Injection；
- AmazingData Adapter 分层；
- Runtime Identity / Provider Doctor；
- Windows 3.14 / Windows 3.12 / Linux 3.14 CI；
- Source Policy / Capability 的治理框架。

但是直接审计代码后发现 **6 个 P0 级问题**。这些问题不会要求重构项目，但在真实历史数据进入 P0a 前必须关闭，否则会破坏 Exact Replay、PIT 或 Provider Spike 结论。

当前建议状态：

```text
P0-M0:
    PASS_WITH_AUDIT_BLOCKERS

AmazingData Adapter:
    CANDIDATE / PRE-P0a

P0-M-1B:
    可继续准备
    但正式账号 Spike 前必须关闭 Provider Reliability 相关 P0

Real P0a:
    BLOCKED，直到本文 6 个 P0 全部关闭
```

---

# 1. P0-01：不可变文件契约实际没有成立

## 现状

`storage/atomic_files.py` 最终使用：

```python
os.replace(temp_path, final_path)
```

如果 `final_path` 已存在，会直接替换旧文件。

同时测试中明确存在：

```python
write_file_atomic(final, b"v1")
write_file_atomic(final, b"v2")
assert final.read_bytes() == b"v2"
```

而 `mock_e2e.py` 的正式路径又使用固定文件名，例如：

```text
canonical/daily_bar/year=2026/month=08/part-0001.parquet
features/security/layer=base/family=skeleton/version=0.0.1/year=2026/month=08/part-0001.parquet
```

## 风险

这会造成：

```text
Snapshot A
→ part-0001.parquet → hash A

Snapshot B / Provider Revision
→ 同一个 part-0001.parquet 被覆盖 → hash B

旧 Snapshot A 仍指向旧 URI
但物理 bytes 已经变成 B
```

Feature Patch 也一样：

```text
Artifact A
Artifact B
```

无法物理共存。

这直接破坏：

```text
Exact Snapshot Replay
Exact Publish Replay
旧实验复现
Patch Replay
```

## 必须修改

### Atomic Writer 默认禁止覆盖

新增：

```python
class ImmutableFileExistsError(AtomicCommitError):
    ...
```

默认：

```python
if final_path.exists():
    raise ImmutableFileExistsError(...)
```

如果希望支持幂等：

```text
allow_existing_identical=True
```

仅在：

```text
existing SHA256 == expected SHA256
```

时允许 no-op。

不同内容必须 BLOCK。

### 文件名必须带输出身份

Canonical：

```text
part-<snapshot-component-id>.parquet
```

Feature：

```text
part-<feature_artifact_set_id>-0001.parquet
```

或使用 content-hash/component UUID。

核心规则：

> 已经被 Snapshot / Artifact 引用的 `file_uri` 永远不能改变 bytes。

## 必测

```text
test_published_file_cannot_be_overwritten
test_existing_file_different_hash_blocks
test_two_snapshots_same_partition_coexist
test_two_artifacts_same_family_version_partition_coexist
test_old_publish_hash_still_matches_after_patch
```

---

# 2. P0-02：Publish 没有校验完整 lineage

## 现状

`publish_snapshot()` 当前只检查：

```text
snapshot exists + DATA_VALIDATED
artifact exists + FEATURE_VALIDATED
universes 非空
```

但没有验证：

```text
artifact.data_snapshot_id == publish.data_snapshot_id
artifact.feature_set_version == publish.feature_set_version
feature_set 存在并 ACTIVE
pipeline_run 存在
pipeline_run.status == FEATURE_VALIDATED
pipeline_run 与 artifact/run 的关系正确
universe_id/version 确实存在
```

因此理论上可以发布：

```text
Snapshot A
+
Artifact B（实际由 Snapshot B 计算）
+
FeatureSet C
```

只要三者各自状态看起来合法。

## 风险

三层 ID 虽然存在，但可以被错误拼接，最终破坏：

```text
lineage
reproducibility
publish audit
exact replay
```

## 必须修改

Publish 前做完整 invariant：

```text
artifact.status == FEATURE_VALIDATED
artifact.data_snapshot_id == data_snapshot_id
artifact.feature_set_version == feature_set_version

feature_set exists
feature_set.status == ACTIVE

snapshot.status == DATA_VALIDATED

pipeline_run exists（传入时）
pipeline_run.status == FEATURE_VALIDATED

每个 universe_id/universe_version 存在 dim_universe
```

## 必测

```text
test_publish_rejects_artifact_snapshot_mismatch
test_publish_rejects_feature_set_mismatch
test_publish_rejects_unknown_feature_set
test_publish_rejects_inactive_feature_set
test_publish_rejects_unknown_pipeline_run
test_publish_rejects_non_feature_validated_pipeline
test_publish_rejects_unknown_universe_version
```

---

# 3. P0-03：Provider Timeout / Retry 语义当前不可靠

## 现状

`run_with_budget()` 的核心流程是：

```python
deadline = ...
return fn()
```

`fn()` 是同步 SDK 调用。

如果 SDK 自己阻塞 4 分钟：

```text
Python 60 秒 deadline
```

并不能在 60 秒时中断调用。

也就是说当前：

```text
query_timeout_seconds = 60
```

不是 hard timeout。

更重要的是，默认 retry 规则几乎是：

```text
所有 Exception 都 retry
```

而 SDK 异常分类是在 `run_with_budget()` 之后才进行。

因此：

```text
SDK TypeError
↓
其实是 Permission
↓
先自动重试
↓
budget/retry 耗尽
↓
ProviderTimeoutError
```

原本权限问题可能最终被记录成超时。

这会污染正式账号 P0-M-1B 的结论。

## 必须修改

推荐顺序：

```text
SDK call
↓
立刻 classify 原始 exception
↓
Typed ProviderError
↓
Retry Policy 根据错误类别决定是否 retry
```

允许 retry：

```text
ProviderNetworkError
可恢复 ProviderTimeoutError
明确允许的 ProviderRateLimitError
少数已验证可恢复 ProviderSdkInternalError
```

禁止 retry：

```text
ProviderAuthError
ProviderPermissionError
ProviderSchemaError
参数错误
代码 TypeError
```

## 真正 Timeout

如果 SDK 同步调用不可取消：

- 当前功能明确叫 `RetryBudget`，不要宣称 hard timeout；
- 正式 Backfill 前做 subprocess worker 超时实验；
- 若 SDK 确实会长期卡死，再决定是否引入 Provider Subprocess Isolation。

## 必测

```text
permission error -> 1 次调用，不 retry
auth error       -> 1 次调用，不 retry
network error    -> 按 policy retry
rate limit       -> 按 policy retry
generic TypeError -> 不得变成 Timeout
blocking callable > budget -> 明确记录真实行为
```

---

# 4. P0-04：Mapper 会把坏数据静默变成合法值

## 现状

`mapper.py` 大量使用：

```python
... or date(1970, 1, 1)
... or 0.0
... or 0
```

例如：

```text
缺失 trade_date → 1970-01-01
缺失 adj_factor → 0.0
缺失 OHLC → 0.0
```

测试里也把：

```text
缺列 -> 1970-01-01
```

当成了正确行为。

另外使用：

```python
a or b
```

选择字段，会混淆：

```text
合法 0
与
missing
```

## 风险

对于本项目，以下领域都不能接受伪造 sentinel：

```text
PIT
复权
涨跌停
退市
收益
Universe
```

`1970-01-01` / `0.0` 会把 Schema Drift 或 Provider Missing 伪装成正常值。

## 必须修改

### Critical Required

例如：

```text
security_code
trade_date
关键 OHLC
adj-factor key
```

缺失/解析失败：

```text
ProviderSchemaError / MappingValidationError / Quarantine
```

### Optional

允许：

```text
None
```

由：

```text
quality_flags
null_policy
```

处理。

字段 fallback helper 应使用：

```python
def first_present(row, *names):
    for name in names:
        value = _col(row, name)
        if value is not None:
            return value
    return None
```

禁止用 `or` 判断字段是否存在。

## 必测

```text
test_missing_trade_date_quarantines
test_invalid_date_not_1970
test_missing_adj_factor_quarantines
test_zero_is_not_missing
test_missing_ohlc_not_silently_zero
```

---

# 5. P0-05：Canonical PIT 公共治理列不完整

## 现状

`005_canonical_facts.sql` 已包含：

```text
selected_provider
source_policy_version
source_revision
reconciliation_status
available_at
quality_flags
ingested_at
```

但 Frozen Baseline 的公共治理语义还要求能回答：

```text
provider_dataset
observation_type
availability_kind
data_version
schema_version
selection_reason
```

当前没有这些列。

尤其：

```text
availability_kind
```

缺失后无法区分：

```text
OBSERVED
CONSERVATIVE_ASSUMED
```

而 `available_at` 目前还是 nullable。

## 风险

正式历史回补时无法完整证明：

```text
这条事实当时是否真的可得
还是基于保守 PIT 假设
```

## 必须修改

不要改已经应用的 `005`。

新增：

```text
006_canonical_governance_hardening.sql
```

至少补：

```text
provider_dataset
observation_type
availability_kind
data_version
schema_version
selection_reason
```

规则：

```text
真实可得时刻未知
→ 按 Conservative Availability Policy 计算 available_at
→ availability_kind = CONSERVATIVE_ASSUMED
```

不能：

```text
available_at = NULL
然后继续当正常历史事实使用
```

---

# 6. P0-06：IDENTITY_FALLBACK Publish Block 只存在于对象方法，没有进入实际发布 Gate

## 现状

`ResolvedIdentity.assert_publishable()` 本身是正确的。

但实际：

```text
publish_snapshot()
```

不会检查：

```text
当前 Artifact / Universe 是否包含 fallback security_id
```

当前测试也只证明：

```text
直接调用 identity.assert_publishable()
会报错
```

而没有证明：

```text
整个 Publish Pipeline 绝对无法发布 fallback identity
```

## 风险

只要某条业务链忘记调用 `assert_publishable()`：

```text
IDENTITY_FALLBACK
```

就可能进入正式 PUBLISHED。

## 必须修改

建立统一：

```text
Publish Validation Gate
```

至少包含：

```text
NO_IDENTITY_FALLBACK
NO_DUPLICATE_PROVIDER_SYMBOL_MAPPING
NO_PRE_LIST_ROWS
NO_POST_DELIST_ROWS
SNAPSHOT_ARTIFACT_LINEAGE_VALID
```

必须由 `publish_snapshot()` 或其不可绕过的上层 service 强制执行。

## 必测

构造真实 fallback identity 进入待发布资产，要求：

```text
publish -> BLOCK
```

---

# 7. P1-01：Orphan Detector 根路径错位

当前：

```python
find_orphan_files(conn, features_root)
rel = path.relative_to(features_root).as_posix()
```

测试传入：

```text
features_root = data_root / "features"
```

但数据库登记的 `file_uri` 是：

```text
features/security/...
```

因此正常文件计算出的 rel 是：

```text
security/...
```

与注册 URI 不同。

结果：

> 正常已注册文件也可能被误判成 orphan。

当前只 report，暂未删文件，所以尚未形成损坏。

## 修改

函数改收：

```text
data_root
```

统一：

```python
rel = path.relative_to(data_root).as_posix()
```

## 必测

```text
registered feature file NOT orphan
registered canonical file NOT orphan
true orphan IS orphan
```

---

# 8. P1-02：Capability Gate 当前是 no-op

`AmazingDataProvider._call()`：

```python
if cap.status is not APPROVED:
    pass
```

所以：

```text
CANDIDATE
```

并不阻止生产调用。

建议增加：

```text
ProviderUseMode.SPIKE
ProviderUseMode.PRODUCTION
```

规则：

```text
SPIKE:
    CANDIDATE allowed

PRODUCTION:
    only APPROVED
```

Spike 必须显式 opt-in。

---

# 9. P1-03：Capability Approval 只存在内存，无 Evidence Bundle

`approve_capability()` 当前只需要：

```text
verified_at
account_profile_id
```

即可改为 APPROVED。

问题：

- 没有 Spike Report / Golden / Provider Verification / Dry-run；
- 没有持久化到 `meta_provider_capability`；
- 进程重启后全回 CANDIDATE。

建议：

```text
meta_provider_capability
```

成为权威状态。

批准必须绑定：

```text
spike_report_ref
golden_case_refs
provider_verification_ref
adapter_version
account_profile_id
verified_at
approved_by
```

---

# 10. P1-04：失败 Provider Call 没有 RawEnvelope

`provider.py` 注释称：

```text
regardless of outcome
```

但实际异常时直接 raise，后面的 envelope 创建代码不会执行。

建议 RawEnvelope 增加：

```text
status
error_class
error_code
duration_ms
attempt_count
capability_status
```

成功/失败都生成 envelope。

---

# 11. P1-05：Migration 删除 / 改名 / 非法命名未检测

当前会检查：

```text
当前仍存在的已应用 migration 的 hash
```

但不会检测：

```text
已应用文件被删除
已应用文件被改名
非法命名 *.sql 被静默忽略
```

建议启动校验：

```text
ledger applied ids
必须是 repo migration sequence 的完整前缀
filename exact match
hash exact match
```

并且 migrations 目录中任何 `.sql` 不符合命名规则：

```text
BLOCK
```

而不是忽略。

---

# 12. P1-06：Logical URI 仍可存在别名

目前仍可能接受：

```text
a//b.parquet
a/./b.parquet
a/b.parquet/
```

字符串不同，但可能映射到同一个物理路径。

建议：

```python
normalized = PurePosixPath(uri).as_posix()
if normalized != uri:
    raise NonCanonicalLogicalUriError(...)
```

---

# 13. P1-07：account_profile_id 可能跨账号碰撞

当前只 hash：

```text
PermissionCode
SubscribeLimitNum
TotalWeekFlow
```

两个不同账户权限相同：

```text
account_profile_id 相同
```

建议：

```text
provider
environment label
host
hash(username)
entitlement hash
```

或显式配置：

```text
TGW_ACCOUNT_PROFILE=TRIAL_SIMULATION
TGW_ACCOUNT_PROFILE=PRODUCTION_MAIN
```

用户名只存 hash，不存明文。

---

# 14. P1-08：登录 Profile 解析失败仍会 login_ok=True

如果 SDK 登录未抛异常，但 logon JSON 无法解析：

```text
profile = {"NOTE": ...}
```

最终仍进入：

```text
login_ok=True
```

建议拆分：

```text
auth_ok
profile_parsed
entitlement_verified
```

生产 Source Policy Approval：

```text
PROFILE_UNKNOWN / entitlement_verified=False
→ BLOCK
```

---

# 15. P1-09：Provider Error 分类过于激进

当前：

```text
TypeError + NoneType / unhashable
→ ProviderPermissionError
```

以及：

```text
"查询失败" + 有 permission_codes
→ ProviderPermissionError
```

可能误把：

```text
SDK bug
参数错误
接口签名漂移
服务故障
```

当作权限不足。

尤其 `unhashable list` 已经有迹象更像接口签名问题。

建议：

```text
只有 endpoint ↔ entitlement 明确映射
或已验证的服务错误模式
才归为 Permission
```

其他未知错误：

```text
ProviderSdkInternalError
```

---

# 16. P1-10：ProviderUnavailableError 重复定义

当前至少存在两套：

```text
providers/base.py::ProviderUnavailableError
providers/amazingdata/errors.py::ProviderUnavailableError
```

是不同 Python class。

建议统一：

```text
providers/errors.py
```

公共定义：

```text
ProviderError
ProviderUnavailableError
ProviderNetworkError
...
```

各 Provider 只继承扩展。

---

# 17. P1-11：sdk_loader / doctor 有异常与 ABI Path 规则不一致

`probe_identity(require_sdk=True)` 某些缺 SDK 路径可能抛：

```text
原始 ImportError / PackageNotFoundError
```

而 Doctor 期望：

```text
ProviderUnavailableError
```

另外 loader 与 doctor 推导 ABI 目录的字符串规则不同。

建议：

- SDK 缺失统一转换为 `ProviderUnavailableError`；
- ABI path resolver 只保留一份；
- Doctor 调用 loader 的 resolved runtime path，不自行拼路径。

---

# 18. P1-12：stdout fd capture 非线程安全

当前使用：

```text
os.dup2(fd 1)
```

这是整个进程级 stdout 重定向。

虽然支持嵌套调用，但没有全局 threading lock。

如果两个 Provider Thread 同时进入：

```text
可能 stdout 串包
恢复顺序错误
Token capture 泄漏
```

建议：

```python
_GLOBAL_SDK_STDOUT_LOCK = threading.RLock()
```

SDK capture 区域强制串行。

---

# 19. P1-13：Logging 对 printf-style secret 存在潜在格式错误

例如：

```python
logger.info("password=%s", password)
```

Filter 可能把 msg 改成：

```text
password=***MASKED***
```

但 `record.args` 仍有一个参数。

Formatter 可能报：

```text
not all arguments converted
```

当前测试没有覆盖。

建议优先：

```text
structured logging
```

并补：

```text
printf-style secret logging test
```

---

# 20. P1-14：配置密码建议改成 SecretStr

当前：

```python
tgw_password: str
```

建议：

```python
from pydantic import SecretStr
tgw_password: SecretStr
```

调用 SDK 时才：

```python
settings.tgw_password.get_secret_value()
```

避免误打印整个 Settings 时暴露密码。

---

# 21. P1-15：STAGING 生命周期与 NOT NULL Manifest Hash 冲突

目前：

```text
meta_data_snapshot.status 可 STAGING
但 data_manifest_hash NOT NULL

meta_feature_artifact_set.status 可 STAGING
但 artifact_manifest_hash NOT NULL
```

真实 STAGING 阶段往往还不知道最终 hash。

当前 Mock E2E 直接 INSERT：

```text
DATA_VALIDATED
FEATURE_VALIDATED
```

所以并没有真正测试 staging lifecycle。

二选一：

### 方案 A

真正落 STAGING：

```text
hash nullable
validated 时强制 not-null service invariant
```

### 方案 B

STAGING 只存在于 run/filesystem：

```text
metadata 表只在完成后 INSERT validated
```

则不要假装数据库状态机有完整 STAGING 生命周期。

P0a 前必须定一种。

---

# 22. P1-16：meta_pipeline_run 没有锁 source_policy_version

Frozen Baseline 要求 Backfill 启动时锁：

```text
source_policy_version
```

当前表中没有。

建议新 migration 增加：

```text
source_policy_version
availability_policy_version
```

至少 source policy version 必须持久化到 Pipeline Run。

---

# 23. P1-17：Canonical System of Record 边界需明确

当前 Frozen 存储链：

```text
Immutable Canonical Parquet
→ meta_data_snapshot_component
```

同时 `005_canonical_facts.sql` 又创建了实体 DuckDB fact 表。

下一阶段必须明确：

## 推荐

```text
Canonical Immutable Parquet = System of Record
DuckDB = Metadata + View / Index / Governance / Read Model
```

不要出现：

```text
Canonical Parquet
+
DuckDB mutable fact
```

两份都自称真相。

如果 DuckDB physical fact table 也要成为 SoR：

> `data_manifest_hash` 就必须把 DuckDB rowset identity 也纳入计算。

当前架构不建议走这条路。

---

# 24. P1-18：版本库中应进一步减少运营敏感信息

审计发现 Provider Verification 文档中包含：

```text
完整仿真账号编号
本机 SDK 安装路径
```

其他工作材料也曾出现实际服务端地址。

即使仓库目前是 private，也建议版本库只保留：

```text
masked account id
account_profile_id
provider endpoint alias
runtime path pattern
```

真实账号、服务器地址、Token、SDK 本地绝对路径尽量放：

```text
gitignored evidence / local runbook
```

另外 `.gitignore` 建议增加：

```text
vendor/
*.whl
```

避免商业 SDK wheel 被误提交。

---

# 25. P2 优化项

以下不阻塞 P0a：

- 状态 VARCHAR 增加 CHECK；
- 关键 lineage 增加 service invariant / 必要 FK；
- `RawEnvelope.params_hash` 使用完整 SHA-256，不截断到 16 hex；
- Provider 增加 `duration_ms / attempt_count / bytes / cache_hit / freshness_lag`；
- 清理文档旧数字：部分 M0 资料还写 84 tests / 001-004，而当前已到 128 tests / migration 005。

---

# 26. 当前测试体系的最大问题

128 tests 全绿值得肯定，但当前至少有一类测试是在验证错误契约：

```text
test_overwrite_is_atomic_replace
```

它验证的是：

```text
同 URI 可以换 bytes
```

而 Frozen Baseline 要的是：

```text
Published Immutable URI 永远不能换 bytes
```

所以后续测试重点不是继续增加数量，而是加入“不可绕过的反向 Contract Test”。

---

# 27. 必须新增的 Contract Tests

## Immutable

```text
test_published_file_cannot_be_overwritten
test_existing_file_different_hash_blocks
test_same_partition_two_snapshots_coexist
test_same_partition_two_artifacts_coexist
test_old_publish_exact_replay_after_patch
```

## Publish lineage

```text
test_publish_rejects_artifact_snapshot_mismatch
test_publish_rejects_feature_set_mismatch
test_publish_rejects_unknown_feature_set
test_publish_rejects_non_active_feature_set
test_publish_rejects_unknown_pipeline
test_publish_rejects_pipeline_not_feature_validated
test_publish_rejects_unknown_universe
test_publish_rejects_identity_fallback
```

## Provider

```text
test_permission_not_retried
test_auth_not_retried
test_network_retry_policy
test_rate_limit_retry_policy
test_generic_typeerror_not_timeout
test_failed_call_has_raw_envelope
```

## Mapper

```text
test_missing_trade_date_quarantines
test_invalid_date_not_1970
test_zero_is_not_missing
test_missing_adj_factor_quarantines
test_missing_ohlc_not_zero
```

## Recovery

```text
test_registered_feature_file_not_orphan
test_registered_canonical_file_not_orphan
```

## Migration

```text
test_deleted_applied_migration_blocks
test_renamed_applied_migration_blocks
test_invalid_sql_filename_blocks
```

## Security / logging

```text
test_printf_style_secret_logging
test_parallel_stdout_capture_serialized
test_settings_repr_does_not_expose_password
```

---

# 28. 推荐整改 Commit 顺序

## Patch A — M0 Integrity Hardening

优先修改：

```text
atomic_files.py
paths.py
publish.py
migrations.py
mock_e2e.py
failure injection / replay tests
identity publish validation
orphan detector
```

目标：

```text
真正 Immutable
真正 Exact Replay
真正 Publish Lineage Gate
```

---

## Patch B — Provider Reliability Hardening

修改：

```text
timeout.py
errors.py
provider.py
session.py
capability.py
sdk_loader.py
doctor.py
stdout_capture.py
logging_setup.py
config.py
```

目标：

```text
正式账号 Spike 不误重试
不误分类
失败调用可审计
CANDIDATE 不会被生产路径误用
```

---

## Patch C — Canonical PIT Hardening

新增 migration：

```text
006_canonical_governance_hardening.sql
```

不要改已应用 `005`。

补齐：

```text
provider_dataset
observation_type
availability_kind
data_version
schema_version
selection_reason
```

同时把 Canonical SoR 契约写死。

---

# 29. 正式账号 P0-M-1B 启动前条件

至少：

```text
[ ] P0-03 Provider Retry/Timeout 修复
[ ] P0-04 Mapper Sentinel 修复
[ ] SPIKE / PRODUCTION Capability Mode 分开
[ ] Failed Provider Call 可审计
[ ] account_profile_id 唯一规则修复
[ ] Provider Doctor runtime identity 稳定
```

然后按：

```text
B2 Security Master
B3 Daily / Status / Limit
B4 Corporate Action / Adj
B5 Units / Freshness / Cache
B6 free-float / Industry / Benchmark
B7 Capacity
```

---

# 30. Real P0a 进入条件

除 `GO_CORE` 外，还必须：

```text
[ ] P0-01 Immutable Files CLOSED
[ ] P0-02 Publish Lineage CLOSED
[ ] P0-04 Mapper CLOSED
[ ] P0-05 Canonical PIT Governance CLOSED
[ ] P0-06 Fallback Identity Publish Gate CLOSED
[ ] Canonical SoR Contract 明确
```

才允许真实数据进入：

```text
Provider
→ Raw
→ Provider-normalized
→ Canonical
→ Snapshot
→ Trend
→ Artifact
→ Publish
```

---

# 31. 当前不建议做

暂时不要：

```text
大规模增加 Trend/PV Feature
直接跑十年历史 Backfill
引入 Iceberg/Delta
引入 ClickHouse/Redis
引入分布式任务队列
提前开发复杂 API
```

当前最高价值工作是：

> 把 Immutable、Lineage、Provider Boundary、PIT 四条做到“代码不可绕过”。

---

# 32. 优先级汇总

| ID | 级别 | 问题 | 处理时点 |
|---|---|---|---|
| P0-01 | P0 | Atomic Writer 可覆盖旧文件，破坏 Exact Replay | Real P0a 前 |
| P0-02 | P0 | Publish 未验证完整 lineage | Real P0a 前 |
| P0-03 | P0 | Timeout 非 hard timeout，Retry/分类会污染 Spike | 正式账号 Spike 前 |
| P0-04 | P0 | Mapper 用 1970/0 隐藏缺失 | 正式账号 Spike/Real P0a 前 |
| P0-05 | P0 | Canonical PIT 公共治理列不完整 | Real历史写入前 |
| P0-06 | P0 | IDENTITY_FALLBACK BLOCK 未进入 Publish Gate | Real P0a 前 |
| P1-01 | P1 | Orphan detector 根路径错位 | 立即 |
| P1-02 | P1 | Capability Gate no-op | 正式账号 Spike 前 |
| P1-03 | P1 | Capability Approval 不持久化、无 Evidence | P0a 前 |
| P1-04 | P1 | 失败 Provider Call 无 RawEnvelope | 正式账号 Spike 前 |
| P1-05 | P1 | Migration 删除/改名未检测 | 建议立即 |
| P1-06 | P1 | Logical URI 存在 alias | 建议立即 |
| P1-07 | P1 | account_profile_id 可碰撞 | 正式账号前 |
| P1-08 | P1 | Profile parse失败仍 login_ok | 正式账号前 |
| P1-09 | P1 | Error heuristic 过度归因 Permission | 正式账号 Spike 前 |
| P1-10 | P1 | Provider exception 基类重复 | 建议立即 |
| P1-11 | P1 | loader/doctor 异常和 ABI path 不一致 | 建议立即 |
| P1-12 | P1 | stdout capture 非线程安全 | 并发前 |
| P1-13 | P1 | logging printf-style masking 风险 | 建议修 |
| P1-14 | P1 | Password 不是 SecretStr | 建议修 |
| P1-15 | P1 | STAGING lifecycle / hash NOT NULL 冲突 | P0a 前 |
| P1-16 | P1 | pipeline_run 未锁 source_policy_version | Backfill/P0b 前 |
| P1-17 | P1 | Canonical DuckDB/Parquet SoR 边界不清 | P0a 前 |
| P1-18 | P1 | Repo 内运营敏感信息/SDK wheel 防误提交 | 建议立即 |

---

# 33. 最终判定

本轮审计结论：

```text
不需要重构
不需要改 Frozen Baseline
继续当前架构
但先做 Integrity Hardening
```

第一阶段最大的价值已经实现：

> 框架结构基本正确。

现在要补的是：

> 把原先存在于“设计文档、注释和 Unit Test”中的 invariant，真正变成任何业务代码都无法绕过的强约束。

建议开发顺序：

```text
A. Immutable + Publish Lineage
B. Provider Reliability
C. Mapper + Canonical PIT
D. Contract Tests
E. 正式账号 P0-M-1B
F. GO_CORE
G. Real P0a
```

只有 6 个 P0 全部关闭后，才建议开始真实 P0a。
