# A-share-analysis 第三轮整体审查与下一阶段开发要求

> 仓库：`GeeCeeSneaker/A-share-analysis`  
> 审查分支：`main`  
> 当前 HEAD：`704d77e46afe65c1d3e4e9fcdd8a8b31d102c022`  
> 当前最新代码提交：`6359d205278982c2f8a9309e7b70e66b9a4bcdc7`  
> 上轮审计基线：`99cca13cddd9f52f9d64c155495d652a339aa540`  
> 本轮代码批次：`65c0d89`（R2A）→ `e6187e3`（R2B/R2C）→ `6359d20`（R2C）  
> 文档批次：`3bb6752` → `2048110` → `704d77e`  
> Frozen Baseline：V1.3.2  
> 审查日期：2026-08-22  
> 性质：第三轮静态代码审计 + DEVLOG 治理审查 + 下一阶段开发任务裁决

---

# 0. 审查结论

本轮更新质量较第二轮有明显提升。

上一轮提出的核心结构性问题，大部分已经落到真实代码，而不是只停留在整改说明中：

```text
Spike Framework 已迁入 src/ashare_state/spike/
Spike 真实调用统一经过 AmazingDataProvider(SPIKE)
Publish 增加 meta_artifact_validation
Run / Artifact / Snapshot Policy Lineage 明显加强
Provider Governance Error 与券商 Permission Error 分离
Provider Symbol / Market / Calendar 语义严格化
Doctor 增加 Login 后实际 DLL Re-probe
FileCommitCoordinator 处理进程内 TOCTOU
Migration 强制连续序号
CI 增加 scripts compileall + Spike dry-run
DEVLOG 建立单一滚动开发日志
```

因此，本轮**不建议重构、不建议修改 V1.3.2 Frozen Baseline、不建议更换技术栈**。

但直接审查当前代码后，仍不建议把：

```text
P0-M-1B Production Capability Spike
```

标记为正式可运行。

当前 Spike 的“结构”已经正确，但在以下几个位置还存在会影响正式结论的逻辑漏洞：

```text
Run Lifecycle
Verdict Aggregation
Production Account Identity
Semantic Validators
Golden Truth
Evidence Closure
Capability Approval Evidence
Publish Recovery Lineage
```

其中部分问题会使正式 Spike 无法生成 verdict，另一些更危险——可能产生错误 GO / NO_GO。

建议当前项目状态调整为：

```text
P0-M0 Engineering Foundation        PASS
Round-1 Audit Remediation           CLOSED
Round-2 Structural Remediation      PASS_WITH_R3_FINDINGS
R3 Formal-Spike Correctness         REQUIRED
Trial L1 Smoke                      READY_AFTER_SMALL_PATCH
Production P0-M-1B                  BLOCKED_BY_R3
Canonical Runtime                   READY_TO_DEVELOP
Real P0a                            BLOCKED_BY_SPIKE + CANONICAL_RUNTIME
```

---

# 1. DEVLOG.md 评估

`docs/DEVLOG.md` 采用单一滚动日志、顶部倒序追加、专题报告独立成文，这个方向是正确的。

建议正式固定：

> `docs/DEVLOG.md` = 项目唯一滚动开发日志。

以后不再为每次普通提交持续新增日报文件；只有以下节点另写专题报告：

```text
M0 Exit
Provider Spike
P0a Exit
P0b Exit
Historical Backfill Exit
重大 Incident / Recovery
重大 Architecture Decision
```

---

# 2. DEVLOG 建议增加 Implementation / Review 双状态

当前日志容易出现：

```text
R2A 全关
R2B/R2C 全关
```

但这里实际表示的是：

```text
开发人员认为已完成实现
```

而不是：

```text
外部复核已经确认关闭
```

建议固定区分：

```text
Implementation Status:
    DONE / IN_PROGRESS / BLOCKED

Review Status:
    PENDING_REVIEW / VERIFIED / REOPENED
```

这样以后：

```text
代码写完
≠
审计关闭
```

不会再混为一个状态。

---

# 3. DEVLOG 推荐模板

```markdown
## YYYY-MM-DD HH:mm · <标题>

**Scope**
- 本提交目标

**Implementation**
- 代码实现

**Schema / Contract Changes**
- Migration
- API
- Persisted semantics
- State-machine changes

**Verification**
- pytest:
- ruff:
- mypy:
- CI:
- manual/live:

**Known Open Issues**
- NONE / issue IDs

**Implementation Status**
- DONE

**Review Status**
- PENDING_REVIEW

**Next**
- ...
```

不建议要求每个 commit 在自身 DEVLOG 条目里记录自己的最终 SHA。

原因是 commit 创建前无法知道最终 SHA，amend 后 SHA 也会变化。Git 本身已经能通过 blame/log 把 DEVLOG 修改与 commit 精确关联。

---

# 4. 建议增加 DEVLOG CI Gate

既然已经确定“后续每次提交代码都同步更新日志”，建议把它变成机器约束。

规则：

```text
如果某一个 commit 修改：
    src/
    migrations/
    configs/
    scripts/

则同一个 commit 必须修改：
    docs/DEVLOG.md
```

注意：

> 应按“每个 commit”检查，而不是只检查整个 PR 最终是否改过一次 DEVLOG。

可在 CI 中对：

```text
git rev-list <base>..<head>
```

逐 commit 执行：

```text
git diff-tree --name-only
```

如果代码变更但无 `docs/DEVLOG.md`，CI BLOCK。

---

# 5. R3-P0-01：Production / Trial Spike Run 当前不会 CLOSED

这是本轮最直接的 Formal Spike P0。

`run_dry_run()` 的生命周期已经完整：

```text
RUNNING
→ probes
→ CLOSED
→ save_run()
```

但 Production / Trial CLI 当前流程是：

```text
new_run()
→ probes
→ catalog.flush()
→ print run_id
→ return
```

没有把 Run 更新成：

```text
CLOSED
```

也没有：

```text
store.save_run(closed_run)
```

与此同时 `compute_verdict()` 的前置条件是：

```text
RunKind.PRODUCTION
AND
status == CLOSED
```

所以按当前实现：

```powershell
python scripts/spike/spike_runner.py --production --phase all
```

即使 B2-B7 全部执行完成，随后：

```powershell
python scripts/spike/spike_runner.py --verdict --run-id <id>
```

仍会因为 Run 还是 `RUNNING` 而被拒绝。

## 必须修

建立统一：

```text
RunStatus:
    RUNNING
    CLOSED
    FAILED
    ABORTED
```

以及：

```text
close_run()
fail_run()
abort_run()
```

Formal Run 无论成功或异常都必须持久化 Terminal State。

---

# 6. R3-P0-02：逐阶段运行与“单 Run Verdict”目前不兼容

CLI 允许：

```text
--production --phase b2
--production --phase b3
...
```

但每次调用都会：

```text
new_run()
```

因此实际是：

```text
B2 → Run A
B3 → Run B
B4 → Run C
...
```

而 Verdict 又只允许：

```text
ONE CLOSED PRODUCTION RUN
```

所以新 Run-scoped Contract 与旧“逐阶段命令”逻辑冲突。

## 推荐方案

Formal Production Spike 默认必须一次：

```text
--production --phase all
```

内部执行：

```text
B2
→ Gate
→ B3
→ Gate
→ B4
→ Gate
→ B5
→ B6
→ B7
→ CLOSE
```

如果确实需要断点恢复，则实现：

```text
--run-id <existing-run>
--resume
```

Resume 必须验证：

```text
same account_profile_id
same code_commit
same environment_lock_hash
same config_hash
same SDK/runtime
status == RUNNING
```

不满足则拒绝续跑。

---

# 7. R3-P0-03：Provider Exception 还没有真正转成 Spike Case 状态

`CaseResult` 已定义：

```text
NOT_TESTABLE_PERMISSION
NOT_TESTABLE_ACCOUNT
NOT_TESTABLE_TIME
MISSING
```

这是正确方向。

但 Probe 当前基本直接：

```python
payload = target.xxx(...)
```

一旦 Provider 抛出：

```text
ProviderPermissionError
ProviderRateLimitError
ProviderAuthError
ProviderSchemaError
ProviderSdkInternalError
```

通常会：

```text
异常向上冒出
CLI 中断
Catalog 未完整 flush
Run 留在 RUNNING
```

而不是转成结构化 Case。

## 建议新增 ProbeExecutor

统一处理：

```text
ProviderPermissionError
→ NOT_TESTABLE_PERMISSION

ProviderRateLimitError
→ NOT_TESTABLE_ACCOUNT / RATE_LIMIT

ProviderAuthError
→ Run FAILED_ACCOUNT

ProviderSchemaError
→ VALIDATED_FAIL / BLOCK

ProviderSdkInternalError
→ SPIKE_INCOMPLETE + BLOCK
```

并保证失败调用对应的 Provider RawEnvelope 也进入 Evidence。

---

# 8. R3-P0-04：Verdict Aggregation 存在 False PASS

这是当前代码中最危险的逻辑问题之一。

## 8.1 DIFF_EXPLAINED 被无条件算 PASS

模型已经正确规定：

```text
DIFF_EXPLAINED
只有 equivalent_pass=True
才能满足 Core Gate
```

但 `coverage()` 当前只看压缩后的：

```text
case_stats
```

并直接把：

```text
DIFF_EXPLAINED
```

加入 `pass_count`。

它看不到：

```text
equivalent_pass
```

因此：

```text
DIFF_EXPLAINED
equivalent_pass=False
```

仍可能被判为能力 PASS。

## 8.2 PASS + FAIL 会被判 PASS

当前逻辑：

```text
fail_count > 0 AND pass_count == 0
→ FAILED

否则只要有 pass
→ PASS
```

所以：

```text
PASS = 1
FAIL = 1
```

最终会变成：

```text
PASS
```

Core Gate 不能接受这个规则。

## 必须改

Verdict 不再从：

```text
stats()
```

推 Gate。

直接遍历：

```text
SpikeCase
```

规则：

```text
required case type 缺失
→ SPIKE_INCOMPLETE

任一 blocking VALIDATED_FAIL
→ FAILED

DIFF_EXPLAINED + equivalent_pass=False
→ 不满足 Gate

VALIDATED_PASS / equivalent DIFF 数量 < min_valid_cases
→ SPIKE_INCOMPLETE

全部 required cases 满足
→ PASS
```

---

# 9. R3-P0-05：min_valid_cases 定义了但没有执行

`SpikeCapabilityDefinition` 已经有：

```text
min_valid_cases
```

但当前 `coverage()` 没使用它。

这意味着：

```text
1 个随机 ST 样本通过
```

和：

```text
50 个 Golden ST 样本通过
```

在 Gate 中没有区别。

正式 Spike 前必须把：

```text
min_valid_cases
```

变成真实 Gate。

---

# 10. R3-P0-06：Symbol Mapping Validator 有确定性 Bug

当前代码：

```python
code, _, suffix = text.partition(".")
```

对：

```text
600000.SH
```

得到：

```text
suffix = "SH"
```

但允许集合是：

```python
{".SH", ".SZ", ".BJ"}
```

所以正常：

```text
600000.SH
000001.SZ
830799.BJ
```

都会被判：

```text
unknown suffix
```

这会直接导致：

```text
symbol_mapping_unambiguous = FAIL
```

进而造成错误 `NO_GO`。

## 修复建议

不要再维护第二套 suffix parser。

直接复用：

```text
normalize_provider_symbol()
```

或抽象统一：

```text
ProviderSymbolParser
```

另外不要把：

```text
相同 bare code 出现在不同交易所
```

天然当成错误。

真正要验证的是：

```text
(provider_symbol, effective_date)
最多映射到 1 个 security_id
```

而不是 bare numeric code 全球唯一。

---

# 11. R3-P0-07：Daily Bar Units Validator 当前存在自证循环

Probe 当前定义：

```python
DOCUMENTED_UNITS = {
    "volume": "shares",
    "amount": "CNY"
}
```

然后又把同一份常量同时作为：

```text
actual
expected
```

传给 Validator。

这不是验证。

此外 Validator 读取：

```text
CLOSE
VOLUME
AMOUNT
```

但当前 Kline 结构使用：

```text
CLOSE_PRICE
VOLUME
AMOUNT
```

所以数值一致性检查可能得到：

```text
checked = 0
```

而仍返回：

```text
VALIDATED_PASS
```

即：

> 没有一条价格/成交额/成交量一致性证据，也可能通过 daily_bar_units。

## 修复

单位 Evidence 必须来自：

```text
Provider Field Map / SDK Manual / Live Golden Cross-check
```

actual 与 expected 必须是独立来源。

并要求：

```text
checked_n >= threshold
```

`checked_n == 0` 必须：

```text
NOT_VALIDATED / FAIL
```

不能 PASS。

---

# 12. R3-P0-08：ST / Suspension Validator 只验证值域，没有验证事实

当前主要检查：

```text
IS_ST_SEC ∈ {0,1}
IS_SUSP_SEC ∈ {0,1}
```

因此随机抽 5 只正常股票：

```text
全部 0
```

也会：

```text
VALIDATED_PASS
```

但 Core Requirement 是：

```text
历史 ST / Suspension 事实正确
```

正式 Validator 必须覆盖：

```text
已知 ST 加帽日
已知 ST 脱帽日
已知停牌日
已知复牌日
```

并与 Golden Truth 对比。

---

# 13. R3-P0-09：Limit Validator 没有真正验证涨跌停制度

当前主要做：

```text
有 up/down 时
检查 close 是否位于区间
```

但 Status Payload 通常不一定有：

```text
CLOSE
```

所以实际检查可能没执行。

同时还没有正式校验：

```text
pre_close × limit rate
价格最小变动单位 rounding
ST 5%
主板 10%
创业板 / 科创板 20%
北交所 30%
IPO / 特殊无涨跌幅限制日
```

甚至：

```text
所有 limit 字段都缺失
```

也可能因为没有 violation 而 PASS。

这必须在正式 Spike 前收紧。

---

# 14. R3-P0-10：Adj Factor Continuity 还没有真正验证连续性

当前主要验证：

```text
EX_FACTOR >= 0
日期顺序
```

没有真正执行：

```text
Corporate Action
+
raw price
+
factor
+
adjusted price / return
```

之间的连续性校验。

单个合法正 Factor 就可能通过。

这不足以支持：

```text
adj_factor_corporate_action_continuity
```

这个 Core Capability。

---

# 15. R3-P0-11：SDK Permission / Cache / Freshness 当前含占位数据

B5 当前构造：

```python
record = {
    "account_profile_id": ...,
    "permission_codes": account_profile_id,
    "cache_behavior": "documented_local_path_is_local",
    ...
}
```

这里：

```text
permission_codes
```

实际上填的是：

```text
account_profile_id
```

Validator 主要检查字段是否非空。

因此可能：

```text
真实 PermissionCode 没验证
Cache freshness 没测
EOD available timing 没测
```

却返回：

```text
VALIDATED_PASS
```

这个属于 Formal Spike P0。

---

# 16. R3-P0-12：B4 目前不是完整 Golden Truth Pipeline

B4 当前实际是：

```text
取少量 Provider Status
→ Freeze code/date
→ OBSERVED
```

还没有：

```text
Official / Exchange Truth
Expected Fields
Source Reference
Source Hash
Compare
Tolerance
Reason Code
Final Verdict
```

也没有落实：

```text
50 ST
20 delisted
30 limit regime
20 corporate action
```

的逐案例验证。

因此当前 B4 更准确的名称是：

```text
Golden Candidate Discovery Skeleton
```

而不是 Golden Validation。

---

# 17. R3-P0-13：Golden 目前没有真正进入 Core Gate

Core Gate 要求的是：

```text
historical_st_suspend
limit_price_and_no_limit_days
adj_factor_corporate_action_continuity
```

但 B4 当前生成：

```text
golden_status_frozen_sample
```

并不是这些 Capability 的 required case type。

因此即使 B4 永远只是：

```text
OBSERVED
```

B3 的弱 Validator 仍可能让 Core Capability 通过。

正式 P0-M-1B 前必须把 Golden 结果与 Core Gate 绑定。

---

# 18. R3-P0-14：`--production` 只是 CLI 标签，不验证账号真是 Production

当前：

```text
--production
```

直接决定：

```text
RunKind.PRODUCTION
```

没有进一步确认登录账号确实是正式账号。

因此理论上：

```text
仿真账号
+
--production
```

也可以生成：

```text
RunKind.PRODUCTION
```

而 Verdict Eligibility 目前主要检查：

```text
run_kind
status
```

这不够。

## Production Run 必须验证

```text
auth_ok == True
profile_parsed == True
entitlement_verified == True
account_profile_id != UNKNOWN
account_profile_id 不得为 TRIAL_SIMULATION
account_profile_id 与预期 Production Profile 匹配
```

可以增加：

```text
TGW_ENVIRONMENT=TRIAL | PRODUCTION
TGW_ACCOUNT_ALIAS=PRODUCTION_MAIN
```

但配置标签只能辅助。

最终权威仍是登录后生成的：

```text
account_profile_id
```

---

# 19. R3-P0-15：Formal Spike Provenance 不完整

`SpikeRun` 已定义：

```text
code_commit
environment_lock_hash
config_hash
sdk_version
runtime_version
account_profile_id
```

但 Production CLI 当前只填：

```text
code_commit
sdk_version
runtime_version
account_profile_id
```

下面两项仍为空：

```text
environment_lock_hash
config_hash
```

同时：

```text
current_code_commit()
```

只获取 short SHA，并允许：

```text
unknown
```

## Formal Production Run 建议强制

```text
full 40-char Git SHA
working tree clean
uv.lock hash
config hash
Python executable/version
Provider adapter version
SDK version
runtime version
account_profile_id
```

任何关键 Provenance：

```text
unknown / empty
```

正式 Verdict 必须：

```text
SPIKE_INCOMPLETE
```

而不能 GO。

---

# 20. R3-P0-16：Verdict 还没有验证 Evidence Hash

每个 Case 已经保存：

```text
evidence_ref
evidence_hash
```

这个设计正确。

但 `compute_verdict()` 没有重新执行：

```text
SHA256(evidence_ref) == evidence_hash
```

同时 `CaseCatalog.load()` 没有重新：

```text
case.validate()
run-id match
duplicate-id check
```

所以如果：

```text
Catalog JSONL 被改
Case Result 被改
Raw Evidence 被改
```

当前 Verdict 不一定发现。

## Formal Verdict 前增加 Evidence Closure

必须依次验证：

```text
Run Manifest valid
Run status CLOSED
Run provenance complete
Catalog belongs to run
Case IDs unique
case.validate()
Evidence file exists
Evidence hash matches
Catalog hash matches
```

Closure PASS 后才允许：

```text
GO_CORE / GO_DEGRADED / NO_GO
```

---

# 21. R3-P0-17：Capability Approval 仍然只验证“引用字符串非空”

当前 Capability Evidence 主要包含：

```text
spike_report_ref
provider_verification_ref
golden_case_refs
dry_run_ref
approved_by
approved_at
account_profile_id
```

审批服务主要验证这些字段：

```text
非空
```

但没有自己读取并确认：

```text
Production SpikeRun 是否存在
Run 是否 CLOSED
Capability 是否 PASS
Account Profile 是否一致
Golden Case 是否存在
Golden Case 是否真的 VALIDATED_PASS
Evidence Hash 是否正确
```

因此理论上人为构造：

```text
golden_case_refs=("abc",)
spike_report_ref="x"
```

仍可满足结构校验。

## 正确方向

正式 Capability Approval 不应接受：

```text
“我告诉你它通过了”
```

而应该接受：

```text
spike_run_id
capability_id
approved_by
```

Governance Service 自己查询：

```text
Run
Verdict
Cases
Evidence Closure
Account Profile
Golden Truth
```

确认通过后再批准。

---

# 22. R3-P0-18：Publish 仍保留无 Run 的 Manual Escape Hatch

Publish 已经大幅加强，正常路径要求：

```text
pipeline_run_id
```

但是：

```python
allow_manual_publish=True
```

仍允许：

```text
pipeline_run_id=None
```

直接 Publish。

测试也明确允许这个行为。

但代码注释又写：

```text
manual recovery should record a RECOVERY run
```

二者矛盾。

## 建议

删除：

```text
allow_manual_publish
```

统一规则：

> 任何 Publish 都必须有 Pipeline Run。

恢复：

```text
run_type = RECOVERY
```

重新发布：

```text
run_type = REPUBLISH / RECOVERY
```

也必须生成真实 Run。

---

# 23. P1-01：Artifact Validation 目前不是 Append-only

`meta_artifact_validation` 当前：

```text
PRIMARY KEY(feature_artifact_set_id)
```

写入：

```text
INSERT OR REPLACE
```

这意味着：

```text
Artifact A
Validation V1 PASS
Publish P1

后来 Validation V2 FAIL
```

V2 可以覆盖 V1。

旧 Publish 无法精确回答：

```text
当时是通过哪个 validator / validation hash 批准的
```

## 建议 Migration 010

改成：

```text
artifact_validation_id
feature_artifact_set_id
validation_version
validator_code_commit
validation_hash
...
PRIMARY KEY(artifact_validation_id)
```

并在：

```text
meta_publish_snapshot
```

增加：

```text
artifact_validation_id
```

Publish 精确绑定当时使用的 Validation。

---

# 24. P1-02：Universe Activation 仍可被重新激活覆盖

当前：

```text
activate_universe()
```

使用：

```sql
INSERT OR REPLACE
```

如果有人绕过 helper：

```text
UPDATE dim_universe.rule_json
→ activate_universe()
```

旧 rule_hash 可能被新 hash 覆盖。

## 修复

Activation 已存在时：

```text
same hash
→ idempotent no-op

different hash
→ VersioningError
```

不能 `REPLACE`。

---

# 25. P1-03：Feature Set Immutable 仍依赖调用纪律

当前：

```text
assert_feature_set_members_mutable()
```

只是 blessed helper。

直接 SQL：

```text
INSERT/DELETE meta_feature_set_member
```

仍可绕过。

不一定需要 DB Trigger。

更简单的强 Gate：

## Activate 时

```text
重新计算 definition_hash
```

## Publish 时

```text
重新计算 ACTIVE FeatureSet members hash
```

如果：

```text
current hash != registered definition_hash
```

直接 BLOCK。

这样即使有人绕过 helper 修改数据库，Publish 也不能放行。

---

# 26. P1-04：Source Policy Version Immutability 还没有真正落 DB

`source_policy.py` 当前主要是：

```text
状态转换纯函数
```

还没有完整实现：

```text
DB approve
DB retire
APPROVED version entries immutable
```

这个问题主要影响：

```text
P0b
Historical Backfill
```

不需要阻塞当前 Canonical Runtime Skeleton。

但在 Source Policy 第一次正式 APPROVED 前必须关闭。

---

# 27. P1-05：Capability Approval Rollback 仍有 Cache 边界

当前流程仍然先：

```text
approve_capability()
→ Memory APPROVED
```

再：

```text
BEGIN
→ DB write
```

如果 DB 写入失败且 DB 原来根本没有该 capability row：

```text
load_approvals()
```

查询不到该行，未必能把刚才的内存 APPROVED 恢复成 CANDIDATE。

## 最简单修复

不要在 DB Transaction 前修改 Cache。

改成：

```text
validate_evidence_without_mutation
→ BEGIN
→ DB write
→ COMMIT
→ rebuild cache from DB
```

把 mutating `approve_capability()` 私有化或改成纯 validation helper。

---

# 28. P1-06：query_kline 内部隐藏了未审计的 Calendar SDK Call

当前：

```text
query_kline()
→ _market()
→ self._base().get_calendar()
→ MarketData(...)
→ query_kline()
```

其中：

```text
get_calendar()
```

没有经过：

```text
self._call()
```

因此这次 SDK Exchange：

```text
没有独立 RawEnvelope
没有独立 Capability Gate
没有独立 error classification context
```

出现错误时会被外层：

```text
daily_bar
```

调用包装。

## 修复

显式使用：

```text
self.get_calendar()
```

或内部建立：

```text
_get_calendar_for_marketdata()
```

但也必须经过 Provider Boundary。

保持规则：

> Every Provider Exchange gets its own envelope.

---

# 29. P1-07：Spike Evidence 尚未真正复用 Provider RawEnvelope

Spike 调用 Provider 后，又自己生成：

```text
新的 UUID
新的 evidence metadata
```

没有直接绑定 Provider 中已经存在的：

```text
RawEnvelope.request_id
attempt_count
duration_ms
capability_status
error_class
request_params_hash
```

这也是 B7 当前难以获得真实：

```text
request_count
retry_count
```

的根本原因。

## 推荐方向

让 Provider 调用返回或可消费：

```text
ProviderExchange {
    envelope
    payload
}
```

或者：

```text
consume_last_exchange()
```

Spike Evidence 与未来 RawWriter 使用同一个：

```text
request_id
```

从而实现：

```text
Spike
Canonical Runtime
Production Ingestion
```

共享完全一致的审计单元。

---

# 30. P1-08：B7 还不是 ALL_A × 1 Month Capacity

当前 Capacity Probe 实际是：

```text
全代码
×
sample_date 单日
```

不是：

```text
ALL_A × 1 month
```

并且：

```text
request_count = 1
retry_count = 0
cache_behavior = first-pull
failure_rate = 0
peak_rss = None
```

多数仍属于结构字段，不是实测数据。

正式账号 Capacity Gate 至少：

```text
ALL_A
×
20 个左右交易日
```

记录真实：

```text
rows
bytes
request_count
retry_count
elapsed
rows/sec
MB/sec
first pull / second pull cache
peak RSS
errors
```

---

# 31. P1-09：B2 end_date 写死 20260822

B2 目前：

```text
get_hist_code_list(..., 19900101, 20260822)
```

以后运行会变成固定历史截止。

改成统一：

```text
run.as_of_date
```

或 CLI：

```text
--as-of-date
```

所有 Probe 都引用同一个 Run As-of。

不要在业务函数内写死当前日期。

---

# 32. P1-10：L1 Script 建议小修后正式实测

这一版已经修正确：

```text
Asia/Shanghai
aware event_time
not-testable 状态拆分
subscription lifecycle 记录
```

但还有四点：

## 32.1 Evidence 仍会覆盖

输出：

```text
l1_subscription_1.json
l1_subscription_5.json
```

重复运行会覆盖旧证据。

改成：

```text
data/spike/trial-l1/<run-id>/
```

并不可变保存。

## 32.2 register Error 仍容易全归 Permission

注册失败也可能是：

```text
SDK signature drift
Network
Internal
Permission
```

应复用 Provider Typed Error。

## 32.3 Sample 目前主要取 SH

正式 20 只应恢复：

```text
SH / SZ / BJ
高流动性 / 低流动性
```

覆盖。

## 32.4 PASS 分两个维度

建议报告：

```text
event_stream_verdict
lifecycle_verdict
```

即使收到事件，如果：

```text
unregister / stop
```

失败，也不应整体简单 PASS。

---

# 33. P1-11：FileCommitCoordinator 只解决进程内竞争

当前 RLock 只在当前进程有效。

Phase 0 可以接受，因为当前设计依赖：

```text
Single DuckDB Owner Process
```

但 Canonical Runtime 必须明确：

> 所有 Immutable Final Commit 必须由唯一 Owner 进程执行。

如果未来 Provider 下载使用多个 worker process：

```text
Worker
→ staging

Owner
→ validate
→ hash
→ final commit
→ metadata transaction
```

Worker 不得直接 Commit 到 Final Path。

---

# 34. P1-12：Spike Report 文档已经过期

当前 `docs/spike_report_p0m1.md` 仍保留旧用法：

```text
data/spike/results/
data/spike/raw/
--phase verdict
逐阶段独立执行
```

但新框架已经变成：

```text
data/spike/{dry-run,trial,production}/<run-id>/
--verdict --run-id
Run-scoped Evidence
```

正式账号到位前必须同步更新 Spike Report / Runbook。

---

# 35. P1-13：Provider Verdict 与 Milestone Eligibility 应彻底分离

旧 Spike Report 的语义是：

```text
GO_DEGRADED
=
Core 通过
但 free-float / SW / dual-source 缺失

P0a 可以进入
P0b / M2 部分阻塞
```

但最近工作计划有时又写：

```text
GO_CORE → P0a
```

容易产生里程碑语义漂移。

## 建议 Verdict 同时输出

```json
{
  "provider_verdict": "GO_DEGRADED",
  "p0a_eligible": true,
  "p0b_eligible": false,
  "historical_backfill_eligible": "PARTIAL"
}
```

这样：

```text
Provider 能力评价
```

与：

```text
项目阶段能否启动
```

完全分离。

---

# 36. 当前推荐项目状态

```text
Engineering Foundation
    PASS

Storage / Identity / Migration Skeleton
    PASS

Round-1 Audit
    CLOSED

Round-2 Structural Remediation
    PASS_WITH_R3_FINDINGS

Formal Spike Infrastructure
    BLOCKED
    until R3 Formal-Spike P0 closed

Trial L1
    READY_AFTER_SMALL_PATCH

Canonical Runtime
    READY_TO_DEVELOP

Production P0-M-1B
    WAIT_R3 + OFFICIAL ACCOUNT

Real P0a
    WAIT CANONICAL_RUNTIME + P0A_ELIGIBLE
```

---

# 37. 下一步第一批：R3-0 Formal Spike Correctness

这批优先于正式账号 Spike。

可以与 Canonical Runtime Skeleton 并行，但必须在正式 P0-M-1B 前关闭。

## R3-0A — Run Lifecycle

实现：

```text
RunStatus Enum
close_run()
fail_run()
abort_run()
resume_run()
```

Formal Run 一定有 Terminal State。

---

## R3-0B — Verdict Engine

直接从：

```text
SpikeCase
```

计算。

强制：

```text
core_gate_satisfied()
equivalent_pass
min_valid_cases
fail dominates pass
required case coverage
evidence closure
```

---

## R3-0C — Production Account Gate

Production Run：

```text
profile complete
entitlement verified
non-trial
expected account profile matched
```

否则拒绝创建 Production Run。

---

## R3-0D — Semantic Validators

至少重写/加强：

```text
symbol mapping
daily bar units
ST/suspension
limit rules
adj factor continuity
sdk permission/cache/freshness
```

---

## R3-0E — Golden Truth

建立：

```text
GoldenCase {
    golden_case_id
    security_id / provider_symbol
    trade_date
    truth_source
    expected_fields
    source_ref
    source_hash
}
```

Provider 值与 Golden Truth 做逐案例 comparison。

---

## R3-0F — Evidence Closure

Verdict 前：

```text
run manifest
case catalog
raw evidence
hash
provenance
```

全部重新校验。

---

# 38. 下一步第二批：R3-1 Governance Exactness

完成：

```text
删除 allow_manual_publish 无 Run 路径
Recovery 也必须 pipeline_run
Artifact Validation Append-only
Publish bind artifact_validation_id
Capability Approval 从真实 SpikeRun 自证
Capability rollback cache 修复
Universe reactivation changed hash BLOCK
FeatureSet activation/publish definition hash self-check
```

Source Policy DB 不可变写路径可以在 P0b 前完成，但接口和状态机现在先定死。

---

# 39. 下一步第三批：Canonical Runtime

这是现在最重要的“新功能开发主线”。

当前工程已经有：

```text
Provider
Storage primitives
Publish
Mock E2E
Spike
```

但还没有正式：

```text
RawWriter
ProviderNormalizedWriter
Canonicalizer
AvailabilityPolicyEngine
QuarantineStore
SnapshotBuilder
Canonical ReadModel Rebuilder
```

这就是 R2-P1-12 的真正内容。

---

# 40. Canonical Runtime 推荐最小目录

不要过度拆分。

建议：

```text
src/ashare_state/ingest/
    raw_writer.py

src/ashare_state/canonical/
    availability.py
    canonicalizer.py
    validation.py
    quarantine.py
    snapshot.py
```

Provider Mapper 继续留：

```text
providers/amazingdata/mapper.py
```

Source Policy 继续：

```text
storage/source_policy.py
```

---

# 41. RawWriter

输入：

```text
ProviderExchange / RawEnvelope
+
payload
```

输出：

```text
Immutable Raw file
content_hash
schema_hash
row_count
raw_file_uri
meta_ingest_run
```

必须：

```text
成功/失败 exchange 都有 envelope
成功 payload immutable
request_id 与 Provider 一致
Spike 与 Production Ingest 共用审计单元
```

---

# 42. Provider-Normalized Writer

流程：

```text
Raw
→ Mapper
→ DTO
→ Provider-normalized Parquet
```

任何：

```text
MappingValidationError
```

进入：

```text
Quarantine
```

不得：

```text
静默丢行
伪造 sentinel
```

保留：

```text
provider
provider_dataset
provider_symbol
source schema version
received_at
必要 raw source fields
```

---

# 43. AvailabilityPolicyEngine

第一版只实现两类明确语义：

```text
OBSERVED
    真实观测到 provider 可用时间

CONSERVATIVE_ASSUMED
    历史回补使用 versioned conservative rule
```

Canonical Fact 在 Validate 前必须：

```text
available_at != NULL
availability_kind != NULL
availability_policy_version != NULL
```

无法确定：

```text
QUARANTINE
```

不能 Published。

---

# 44. Canonicalizer

当前只做五个核心事实域：

```text
daily_bar
security_status
limit_price
adj_factor
corporate_action
```

暂时不要扩行业/主题/free-float。

每条 Canonical Fact 必须填：

```text
selected_provider
provider_dataset
observation_type
availability_kind
source_policy_version
source_revision
data_version
schema_version
selection_reason
reconciliation_status
available_at
quality_flags
ingested_at
```

---

# 45. Security Identity Resolver

Canonical 写入前：

```text
provider_symbol
→ effective-date bridge
→ security_id
```

要求：

```text
PIT
effective-date aware
pre-list / post-delist block
no ambiguous mapping
```

Fallback：

```text
可以进入 Quarantine / Spike
不得进入 Publishable Artifact
```

---

# 46. Snapshot Builder

输入：

```text
Validated Canonical Files
```

输出：

```text
data_snapshot_id
meta_data_snapshot_component
data_manifest_hash
```

必须：

```text
Validated 后才 Insert Metadata
不 glob
Logical URI
Manifest deterministic
```

---

# 47. DuckDB Read Model Rebuild

ADR 已确定：

```text
Canonical Parquet = System of Record
DuckDB fact_* = rebuildable read model
```

现在要真正实现：

```text
snapshot manifest
→ rebuild DuckDB read model
```

Acceptance：

```text
清空 fact_*
→ 从 Snapshot Parquet 重建
→ row count / key / aggregate 一致
```

---

# 48. Artifact Validator

不要让调用者手填：

```text
identity_fallback_count
blocking_dq_count
```

Validator 自己计算。

第一版至少：

```text
duplicate PK
unknown security
pre-list
post-delist
identity fallback
invalid OHLC
negative volume/amount
invalid status
invalid limit
missing availability
missing canonical governance
```

结果生成：

```text
append-only artifact_validation_id
```

---

# 49. Canonical Runtime Stage CR-A

先做 Mock / Fixture：

```text
20 securities
×
60 trading days
```

完整链：

```text
Provider
→ Raw
→ Provider Normalized
→ Canonical
→ Snapshot
→ DuckDB Rebuild
→ Skeleton Artifact
→ Artifact Validation
→ Publish
→ Exact Replay
```

全部 PASS 后才进入真实数据。

---

# 50. Canonical Runtime Stage CR-B

正式 Provider Core 通过后：

```text
AmazingData
20 securities
×
60 trading days
```

验证：

```text
Raw Evidence
Security Identity
PIT Availability
Canonical Governance
Snapshot
Read Model Rebuild
Exact Replay
```

通过后开始 Trend BASE。

---

# 51. Trial L1 并行安排

先做一个小 Patch：

```text
Run-scoped immutable evidence
Typed SDK errors
SH/SZ/BJ mixed sample
event_stream_verdict
lifecycle_verdict
```

然后交易时段：

```text
1
→ 5
→ 20
```

100：

```text
只用于 subscription entitlement limit behavior
```

不要用试用账号推断平台容量。

---

# 52. 正式账号 P0-M-1B

R3-0 关闭后再跑。

流程：

```text
Provider Doctor
→ RUNTIME_ACTUAL_LOAD_VERIFIED
→ Verify Production Account Profile
→ Open ONE Production SpikeRun
→ B2
→ Core Gate
→ B3
→ Core Gate
→ B4 Golden Truth
→ Core Gate
→ B5
→ B6
→ B7
→ Close Run
→ Evidence Closure
→ Verdict
→ Human Review
→ Capability Approval
```

---

# 53. Early Stop

正式 Run 内：

```text
B2 blocking FAIL
→ close FAILED_CORE
→ NO_GO

B3 blocking FAIL
→ close FAILED_CORE
→ NO_GO

B4 Golden blocking FAIL
→ close FAILED_CORE
→ NO_GO
```

如果是：

```text
NOT_TESTABLE
framework incomplete
permission unresolved
```

应：

```text
SPIKE_INCOMPLETE
```

不要误记成 `NO_GO`。

---

# 54. P0a Eligibility

建议代码明确输出：

```text
p0a_eligible
p0b_eligible
historical_backfill_eligible
```

只要 Core Facts 全部通过：

```text
p0a_eligible = true
```

即使：

```text
free-float
SW taxonomy
dual-source reconciliation
```

缺失，也只阻塞依赖这些数据的 P0b/M2 功能。

---

# 55. GO 后 Real P0a

第一条真实 Vertical Slice：

```text
AmazingData
→ Raw Immutable
→ Provider Normalized
→ Canonical
    Daily
    Status
    Limit
    Adj
    Corporate Action
→ Security ID
→ ALL_A
→ Trend BASE
→ Aggregate
→ Artifact
→ Validation
→ Publish
→ Exact Replay
```

---

# 56. Trend 仍不要提前扩大

Vertical Slice 通过后第一批 Feature：

```text
RET_005
RET_020
RET_060

SER_005
SER_020
SER_060

UP_DAY_RATIO

MA_DIST
MA_BREADTH

POS_RET_BREADTH
NEW_HIGH
NEW_LOW
```

暂时不要扩大：

```text
PV
Vol
Stress
Style
Theme
Payoff
```

---

# 57. 本轮必须新增 Contract Tests

## Spike Lifecycle

```text
test_production_run_closes
test_failed_run_persists_terminal_state
test_resume_uses_same_run
test_verdict_rejects_running_run
test_trial_account_cannot_create_production_run
test_production_requires_complete_provenance
```

## Verdict

```text
test_diff_explained_without_equivalence_not_pass
test_diff_explained_equivalent_can_pass
test_pass_plus_fail_is_fail
test_min_valid_cases_enforced
test_evidence_hash_mismatch_blocks_verdict
test_catalog_cross_run_case_blocks_verdict
```

## Validators

```text
test_symbol_600000_sh_passes
test_daily_units_requires_independent_evidence
test_daily_units_checked_zero_not_pass
test_all_zero_st_sample_not_semantic_pass
test_limit_missing_all_not_pass
test_known_mainboard_limit_case
test_known_star_limit_case
test_known_st_limit_case
test_known_no_limit_case
test_adj_requires_price_continuity
test_sdk_behavior_uses_real_permission_codes
```

## Publish

```text
test_manual_publish_without_run_is_impossible
test_recovery_publish_requires_recovery_run
test_old_publish_keeps_original_validation_id
```

## Governance

```text
test_approval_requires_closed_production_run
test_approval_requires_case_refs_exist
test_approval_rejects_trial_run
test_failed_insert_without_existing_db_row_restores_candidate_cache
test_universe_reactivation_changed_rule_blocks
test_feature_set_definition_hash_mismatch_blocks_publish
```

## DEVLOG

```text
test_code_commit_requires_devlog_change
```

---

# 58. 推荐 Commit 顺序

```text
Commit R3-0A
Spike lifecycle + resume + production account gate

Commit R3-0B
Verdict engine + evidence closure + provenance gate

Commit R3-0C
Core semantic validators + Golden Truth

Commit R3-1A
Publish no-run bypass + append-only artifact validation

Commit R3-1B
Capability approval evidence binding + version immutability fixes

Commit CR-1
RawWriter + ProviderExchange/RawEnvelope persistence

Commit CR-2
Provider-normalized writer + Quarantine

Commit CR-3
AvailabilityPolicy + Canonicalizer

Commit CR-4
SnapshotBuilder + DuckDB read-model rebuild

Commit CR-5
Artifact Validator + 20×60d Mock Vertical Slice
```

每个代码提交同步：

```text
docs/DEVLOG.md
```

---

# 59. 当前不建议做

暂时不要：

```text
完整 Trend/PV 大开发
Vol/Stress/Theme 扩域
十年全市场历史回补
Tushare Fusion 正式实现
复杂调度系统
Redis / ClickHouse / Iceberg
API/UI
```

现在最高价值工作是把两条链彻底做实：

```text
Formal Provider Verification
Canonical Runtime
```

---

# 60. 最终裁决

项目已经从：

```text
“架构骨架”
```

进入：

```text
“接近真实数据运行”
```

阶段。

第二轮整改后最明显的进步是：

> Spike、Provider、Publish、Governance 已经开始走同一套生产路径，不再是彼此独立的原型。

但现在最需要警惕的是：

```text
238 tests green
≠ Formal Spike 语义一定正确

存在 Validator
≠ 已经真正验证市场事实

存在 CaseResult
≠ Verdict Aggregation 一定不会 False PASS
```

本轮发现的问题都能在当前架构中修复，不需要再次进行大范围架构设计。

建议下一步：

```text
短周期完成 R3-0 + R3-1
同时启动 Canonical Runtime
并行完成 Trial L1
```

达到：

```text
R3 Formal-Spike P0 = 0
+
Canonical Runtime Mock 20×60d Vertical Slice PASS
```

后，项目就真正进入：

> **“正式账号到位即可验证 Provider；Provider 通过即可安全接真实历史数据”的状态。**
