# A-share-analysis 第四轮代码审计与下一阶段开发要求

> 仓库：`GeeCeeSneaker/A-share-analysis`  
> 审查分支：`main`  
> 审查 HEAD：`b9dd49b34cd7173df17b870d051881e0a148f33a`  
> 上轮审查基线：`704d77e46afe65c1d3e4e9fcdd8a8b31d102c022`  
> 本轮代码提交：`44ee765` → `e6a2a01` → `b9dd49b`  
> Frozen Baseline：V1.3.2  
> 审查日期：2026-08-22  
> 审查性质：第三轮整改复核 + Formal Spike Gate 攻击性审计 + 下一阶段工作裁决

---

# 0. 执行结论

本轮整改有效，R3 之后代码成熟度明显上升。已经确认有效的方向包括：Run 生命周期终态化、Production 单 Run、Verdict 从压缩 stats 转向 SpikeCase、DIFF_EXPLAINED 等价语义、min_valid_cases、Raw Evidence hash 复验、Production provenance、删除无 Run Publish、Artifact Validation append-only、Publish 绑定 validation id、Golden Case 模型化、Capability Approval 从 SpikeRun 自证、DEVLOG 唯一滚动日志。

因此，本轮不建议重构架构，也不建议修改 V1.3.2 Frozen Baseline。

但不能同意开发日志中的：

```text
R3 Formal-Spike Correctness = COMPLETE
R3 P0 count = 0
```

当前更准确的状态应为：

```text
R3 Implementation Status = DONE
R3 Review Status         = REOPENED
```

原因是 Formal Spike 的 Truth、Gate、Approval 三个闭环仍存在会导致“永远无法 GO”或“错误 PASS / 错误 APPROVED”的漏洞。

建议项目状态：

```text
P0-M0                              PASS
Round-1 / Round-2 Architecture     CLOSED
R3 Structural Remediation          SUBSTANTIALLY PASS
R4 Formal Spike Truth/Gate         REQUIRED
Trial L1 Smoke                     READY_AFTER_SMALL_PATCH
Canonical Runtime CR-1             READY_TO_START
Production P0-M-1B                 BLOCKED_BY_R4 + OFFICIAL ACCOUNT
Real P0a                            BLOCKED_BY P0a_ELIGIBLE + Canonical Runtime
```

---

# 1. R4-P0-01：Golden Truth 仍不具备 Formal Gate 条件

Core Gate 最低数量要求：

```text
50 ST transition
20 delisted
30 limit regime
20 corporate action
```

但 `src/ashare_state/spike/golden_truth.py` 当前只有 7 个内置种子案例，而 `probe_b4_golden()` 实际只读取 `BUILTIN_GOLDEN_CASES`，并没有实现文档描述的“正式 run 前动态补齐 → Freeze → Attach Expected Truth → Source Hash Verify”。

因此按当前代码，即使 Provider 完全正确，也无法达到正式 Gate 的最低数量。当前 `FRAMEWORK READY` 仍然偏早。

Formal Golden 数据应从 Python 常量升级为版本化证据集，例如：

```text
data/golden/provider/amazingdata/
    golden_cases_v1.jsonl
    truth_manifest.json
```

每条至少包含：

```text
golden_case_id
case_type
provider_symbol
trade_date
expected_fields
truth_source
source_ref
source_hash
truth_version
reviewed_by
reviewed_at
```

正式数量：

```text
ST                 >= 50
Delisted           >= 20
Limit Regime       >= 30
Corporate Action   >= 20
BJ Mapping         另设专门案例
```

---

# 2. R4-P0-02：Golden source_hash 目前没有成为 Gate

`GoldenCase` 已经有 `source_ref/source_hash`，但当前内置案例的 `source_hash` 为空，`validate_golden_cases()`、`probe_b4_golden()` 和 `compute_verdict()` 都没有要求 source_hash 存在，也没有重新校验 Truth Evidence 的 SHA-256。

更关键的是，当前 Golden SpikeCase 的 `evidence_ref/evidence_hash` 指向 Provider 返回的 status payload，而不是外部 Truth Evidence。

Formal 链路必须变成：

```text
External Truth Artifact
→ Hash Seal
→ Expected Value
→ Provider Observation
→ Compare
→ Case Result
```

而不是：

```text
代码常量 expected
→ Provider value
→ Compare
```

Formal Run 创建时应记录：

```text
golden_truth_version
golden_manifest_hash
```

Resume 和 Verdict 都必须重新核验。

---

# 3. R4-P0-03：Golden Seed 已存在内部语义冲突风险

无需外部资料，仅从代码内部即可看到：

一个 ST 案例的 `truth_source` 描述为 “ST removal”，但 `expected_fields={"IS_ST_SEC": True}`。这至少在语义上存在明显冲突，不能作为 Formal Golden 直接使用。

STAR 案例中也同时存在“20% limit regime”和“first-day/first-five-days no-limit”的混合表达。Formal Golden 必须做到：

```text
一个 case
一个明确 truth
一个有效日期
一个 source
一个 source hash
一个 reviewer
```

不能靠代码注释解释。

---

# 4. R4-P0-04：Required Case Types 并没有真正全部必需

`SpikeCapabilityDefinition.required_case_types` 已经声明多个必需类型，例如：

```text
historical_st_suspend:
    historical_st_suspend
    golden_st_transition
```

但 `_capability_status_from_cases()` 当前只检查：

```text
relevant cases 非空
+
所有相关 case 的 valid 总数 >= min_valid_cases
```

没有逐个检查“每一个 required_case_type 都达到自己的最低数量”。

理论上可能出现：

```text
golden_st_transition = 0
historical_st_suspend = 50 PASS
→ capability PASS
```

这违背 `Gate Contract == Probe Contract`。

建议把单一：

```text
min_valid_cases: int
```

改成：

```python
required_case_counts = {
    "historical_st_suspend": 1,
    "golden_st_transition": 50,
}
```

类似：

```text
security_master_with_delisted
    security_master_with_delisted >= 1
    golden_delisted >= 20

historical_st_suspend
    historical_st_suspend >= 1
    golden_st_transition >= 50

limit_price_and_no_limit_days
    limit_price_and_no_limit_days >= 1
    golden_limit_regime >= 30

adj_factor_corporate_action_continuity
    adj_factor_corporate_action_continuity >= 1
    golden_corporate_action >= 20
```

---

# 5. R4-P0-05：Adj Factor Continuity 当前无法真正形成 Direct PASS

`validate_adj_continuity()` 已经正确改成：

```text
没有 price_context
→ OBSERVED
```

但 B3 当前调用时没有传 `price_context`，所以 Direct Case 只能是 OBSERVED。

B4 的 `golden_corporate_action` 目前主要比对 `IS_WD_SEC`，它能证明 Provider 能看到除权/除息状态，却不能证明 Adj Factor + Raw Price + Corporate Action 的价格连续性。

必须对 Corporate Action Golden Cases取：

```text
T-1 raw close
T raw/pre-close
T+1
adj factor before/after
corporate action flag
```

并明确计算复权连续性后，Direct Adj Continuity 才允许 `VALIDATED_PASS`。

---

# 6. R4-P0-06：SDK Permission / Cache / Freshness 仍有 False PASS

当前 B5 已改为真实 permission_codes，这是进步，但 `cache_behavior` 仍是固定字符串：

```text
documented_local_path_is_local
```

Validator 主要检查 permission_codes 看起来像数字、cache_behavior 非空，因此仍没有真正验证：

```text
Cache 是否命中
第一次拉取 vs 第二次拉取
缓存是否陈旧
EOD 数据何时可见
freshness / available_at
revision behavior
```

但 Capability 名称却是 `sdk_permission_cache_freshness`，因此仍可能只证明 PermissionCode 就让整个能力 PASS。

建议拆成：

```text
sdk_permission_profile
sdk_cache_behavior
sdk_freshness_behavior
```

三者都 PASS 后才合成能力 PASS。

---

# 7. R4-P0-07：B3 的 ST Golden Fact 仍是现场假设

B3 当前对任意 `symbols[:1]` 构造：

```text
expected_is_st=False
```

这个 False 不是外部 Truth。

随机第一只股票不是 ST 时会产生伪 Golden PASS；如果恰好是 ST，又会 False FAIL。

B3 只应负责字段结构/值域/PIT payload integrity，语义 PASS 交给 B4 Golden Truth；或者 B3 只使用已经封存的 Golden Catalog，不允许现场假设。

---

# 8. R4-P0-08：History Coverage 样本选择不稳定

B5 当前从 `get_code_list()` 取前两只股票，再从 1990 查询到 as-of。

如果 Provider 排序前两只是近年上市股票，会错误得出 Provider 历史覆盖不足。

History Coverage 应使用固定 Golden Securities：

```text
长期上市 SH
长期上市 SZ
历史退市证券
BSE/BJ 历史案例
```

并明确记录：

```text
expected listing period
required history start
provider earliest
```

不能依赖 API 返回顺序。

---

# 9. R4-P0-09：B2 Historical Security Master 只验证 SH/SZ

B2 调用的是：

```text
EXTRA_STOCK_A_SH_SZ
```

从代码语义上只覆盖上海、深圳，但 Frozen Universe 明确包含 BSE。

Formal Security Master Gate 必须证明：

```text
SH
SZ
BJ
delisted
listing/delisting lifecycle
```

如果 SDK 没有统一枚举，应分市场调用并合并 Evidence。

同时建立：

```text
BSE historical security case
BJ code mapping case
```

---

# 10. R4-P0-10：Symbol Mapping 还没有验证 BJ 历史映射

当前 suffix parser 已修好，但现在验证的是“当前 full provider symbol 可解析且唯一”，没有证明：

```text
北交所旧代码 / 新代码
effective-date mapping
(provider_symbol, effective_date) -> security_id
```

而 Capability Description 仍写 “incl. BJ old/new codes”。

应增加独立 `golden_bj_mapping`，至少验证旧/新代码、有效日期和同日无一对多歧义。

---

# 11. R4-P0-11：Limit Validator 仍不够 PIT

当前 `board_of()` 是静态规则：

```text
MAIN 10%
ST MAIN 5%
ChiNext 20%
STAR 20%
BSE 30%
```

没有真正纳入：

```text
trade_date
listing_date
trading-rule effective date
IPO first N days
历史 ChiNext 规则切换
特殊 no-limit day
```

这会对历史样本产生 False FAIL。

另外 `expected_limit_price()` 注释写 half-up，实现却使用 Python `round()`；Python round 是 bankers rounding，不应被当作严格的 `ROUND_HALF_UP`。

Spike Rule Validator 应使用版本化交易规则：

```text
exchange
board
effective_from
effective_to
st_flag
listing_age_rule
up_rate
down_rate
tick
rounding_mode
no_limit_rule
```

计算使用 `Decimal + ROUND_HALF_UP`。

---

# 12. R4-P0-12：Case Catalog 没有真正 Seal

当前 Evidence Closure 已能发现 Raw Evidence 文件篡改、cross-run case 和重复 case，这是明显进步。

但 `spike_case_catalog.jsonl` 本身没有封存 Hash。

Run CLOSED 后仍可编辑：

```text
VALIDATED_FAIL → VALIDATED_PASS
expected_value
validator_id
equivalent_pass
```

只要 evidence_ref/evidence_hash 仍指向原 Raw 文件，当前 Closure 不一定发现，因为 Verdict 不会重新执行全部 Validator，而是信任 Catalog 里的 CaseResult。

必须在 Close Run 时计算：

```text
case_catalog_hash
golden_manifest_hash
```

写入 SpikeRun。Formal Verdict 重新计算并 exact match；不匹配则 `SPIKE_INCOMPLETE`。

Closed Run Catalog 应视为 Immutable Artifact。

---

# 13. R4-P0-13：Production Account Gate 仍依赖试用账号启发式

`AccountProfile.from_scrubbed()` 当前用：

```text
TotalWeekFlow == 10
```

推断 `TRIAL_SIMULATION`，否则标为 `ACCOUNT`。

这是针对当前试用账号的启发式，不是正式 Account Type Contract；并且 Session 创建 Profile 时没有传入明确的 TRIAL/PRODUCTION environment，profile hash 的 environment 可能仍是 UNKNOWN。

正式 Gate 应改成：

```text
configured_account_environment = PRODUCTION
+
login profile fingerprint
+
expected production account profile
```

正式账号首次开通后人工确认 Profile 并 Freeze `production_account_profile_id`。之后 `--production` 必须匹配该 Profile，不能仅靠流量数字猜账号类型。

---

# 14. R4-P0-14：Capability Approval 自证仍没有完全闭环

`approve_from_spike_run()` 是正确方向，但仍有四个问题。

第一，它检查某个 capability 的 `capability_status == PASS`，但没有明确拒绝 `verdict.blocking_reasons`。因此如果 run 存在 Evidence Closure blocking reason，而该能力状态仍是 PASS，仍有继续审批的风险。

第二，`capability_case_refs` 仍由调用者自由提供，并未强制属于该 capability 的 required case types / golden types / required counts。

第三，`dry_run_ref` 当前写成：

```text
verdict:<provider verdict>
```

这不是真正的 Framework Dry Run，更不是 Source Policy Dry Run，只是满足“字段非空”。

第四，Registry Capability → Spike Capability 映射可能过度批准。例如 `corporate_action` Registry 声明 `InfoData.get_dividend/get_right_issue`，但当前映射到 `adj_factor_corporate_action_continuity`，并没有证明这两个 endpoint 都实际调用成功。`trade_calendar` 又映射到一个并不存在的同名 Spike Capability。

原则应固定为：

> Provider Capability Approval 必须证明其声明的 endpoint/dataset，而不是找到一个“相近的 Spike 结论”。

建议接口改成：

```text
approve_from_spike_run(
    name,
    spike_run_id,
    approved_by
)
```

删除 `capability_case_refs`，由系统根据 Capability Definition 自动推导 required cases 和 required endpoints，并强制 `blocking_reasons == []`。

---

# 15. R4-P1-01：ProviderAuthError Failure Reason 会被覆盖

ProbeExecutor 遇到 ProviderAuthError 时会先：

```text
fail_run(... FAILED_ACCOUNT)
raise
```

但 SpikeRun 是 frozen object，CLI 外层持有的 local `run` 仍是原 RUNNING 对象，于是外层 exception handler 又可能：

```text
fail_run(... FRAMEWORK_ERROR)
```

最终将 FAILED_ACCOUNT 覆盖为 FRAMEWORK_ERROR。

应让 `fail_run()` 返回的新 Run 回写上下文，或外层 exception 重新从 Store load run 再决定是否 fail。

---

# 16. R4-P1-02：文档写了 Early Stop，但代码没有实现

Spike Report 写 B2/B3/B4 blocking fail 应 Early Stop，但 `_run_phases()` 当前只是按顺序执行全部 phase，没有阶段 Gate。

正式账号流量昂贵时没有必要在已确定 Blocking Fail 后继续 B3-B7。

每阶段应执行：

```text
phase_gate()
→ CONTINUE
→ STOP_NO_GO
→ STOP_INCOMPLETE
```

Early Stop 必须成为代码，不是 Runbook 文案。

---

# 17. R4-P1-03：部分 Provider Call 仍绕过 ProbeExecutor

多个 Probe 中仍有直接：

```text
ctx.target.get_code_list(...)
ctx.target.get_calendar(...)
```

这些调用失败时不会统一生成 structured failure case / ProbeExecutor evidence，可能直接成为 FRAMEWORK_ERROR。

Formal Spike 中每一次 Provider Exchange 都应走统一 Executor / ProviderExchange。这项正好与 CR-1 一次解决。

---

# 18. R4-P1-04：B7 仍不是正式 Capacity Benchmark

B7 从 1 日升级到 5 日是进步，但仍不是 20 个左右交易日 / 1 个月。

同时当前 request_count 取 Provider 创建以来所有 `query_kline` envelopes，可能混入 B3/B5/B6；retry_count 更是对全部 envelopes 求和。所谓 `first / cached-or-first` 只是按循环顺序打标签，没有执行同一个请求的 first pull / second pull。

正式 B7 应：

```text
记录 B7 开始时 envelope cursor
只统计 B7 request ids
ALL_A × >=20 trading days
相同请求 first pull
相同请求 second pull
```

并记录 rows/bytes/request/retry/wall time/provider duration/RSS/failure/cache behavior。

---

# 19. R4-P1-05：Migration 010 丢失旧 Validation Metadata

010 迁移旧表时把 `validator_code_commit` 写成 NULL，也没有独立保留旧 `validation_hash/details_json`。

新表只剩一个 `detail`，而 `record_artifact_validation()` 又使用：

```text
details_json or validation_hash
```

二选一写入。

建议在正式 P0a 前用 migration 011 固定为独立字段：

```text
artifact_validation_id
feature_artifact_set_id
validation_version
validator_code_commit
validation_hash
details_json
identity_fallback_count
blocking_dq_count
validated_at
```

---

# 20. R4-P1-06：Publish Reader 未暴露 artifact_validation_id

Publish 已存 `artifact_validation_id`，但 `latest_published()` 与 `resolve_publish()` 没返回它。

Exact Replay Helper 还不能完整回答“这个 Publish 当时由哪个 Validation 批准”。

Reader 应返回同一 ID，并增加：

```text
resolve_artifact_validation_for_publish()
```

---

# 21. R4-P1-07：Publish 不应隐式选择“最新 Validation”

当前 Publish 自动：

```text
ORDER BY validated_at DESC
LIMIT 1
```

选择最新 Validation。

更精确的设计是：

```text
Artifact Validator
→ artifact_validation_id
Pipeline
→ 显式传给 Publish
Publish
→ 校验该 validation 属于该 artifact 且 blocking=0
```

不要靠“此刻最新”隐式决定版本。

---

# 22. R4-P1-08：DEVLOG CI Gate 在 shallow checkout 下可能失效

CI 使用：

```yaml
uses: actions/checkout@v4
```

但没有 `fetch-depth: 0`，后续却使用：

```text
git rev-list
git merge-base --is-ancestor e6a2a01 ...
```

默认浅克隆下可能没有祖先历史；merge-base 失败后当前脚本会直接 continue，最终表面输出 OK，实际没有检查。

测试中又使用 `git rev-list main`，PR detached checkout 下也不够稳。

建议：

```yaml
uses: actions/checkout@v4
with:
  fetch-depth: 0
```

测试统一以 HEAD / event base 为基准，不假设 local main 一定存在。

---

# 23. R4-P1-09：L1 Session 判断没有处理交易所休市日

L1 当前只判断 weekday + HHMM。法定节假日如果是周一到周五，会被认为 IN_SESSION，然后无事件可能被记为 FAIL_NO_EVENTS。

应先用已验证交易日历判断 is_trade_day，再判断时段；在交易日历能力尚未 APPROVED 时，应返回 NOT_TESTABLE_CALENDAR，而不是直接 FAIL。

---

# 24. R4-P1-10：L1 异常仍存在 Permission 兜底过宽

L1 仍有若干 `except Exception → NOT_TESTABLE_PERMISSION`，可能把 SDK surface drift、register signature、network/internal error 都记成权限问题。

L1 也应复用 Provider Error Taxonomy，至少区分：

```text
PERMISSION
NETWORK
AUTH
SDK_INTERNAL
SCHEMA
ACCOUNT_LIMIT
```

---

# 25. Source Policy DB 不可变按原计划放到 P0b 前

这一项开发日志已明确保留为 Open Issue。本轮同意它不阻塞 CR-1 / Mock Canonical Runtime，但必须在第一个 APPROVED Source Policy 出现前完成。

---

# 26. 对“286 tests”的审计口径

仓库 DEVLOG/commit message 记录：

```text
286 passed
ruff/format/mypy clean
```

本次 GitHub Connector 没有返回当前 HEAD 的 commit status / workflow run，因此本审计把它视为开发方记录，而不是独立确认“当前 HEAD GitHub Actions 三矩阵已经绿”。

以后 DEVLOG 建议分开：

```text
Local:
    pytest
    ruff
    mypy

GitHub Actions:
    Windows 3.14
    Windows 3.12
    Linux 3.14
    workflow run / commit
```

---

# 27. 本轮状态裁决

建议下一次 DEVLOG 写：

```text
R3 Implementation Status:
    DONE

R3 Review Status:
    REOPENED

R4 Blocking Findings:
    Golden Truth Closure
    Required Case-Type Gate
    Adj Continuity
    SDK Freshness
    BSE/BJ Coverage
    Catalog Seal
    Production Account Identity
    Capability Approval Closure
```

R4-P0 全部关闭后再将 Review Status 改为 VERIFIED。

不需要再做一次“大范围全架构审查”，只做 Focused Acceptance Review。

---

# 28. 下一阶段总顺序

```text
R4-A Formal Spike Truth/Gate Closeout
        ↓
R4-B Capability Approval / Publish Exactness
        ↓
CR-1 ProviderExchange + RawWriter
        ↓
CR-2 Provider-Normalized + Quarantine
        ↓
CR-3 Availability + Canonicalizer
        ↓
CR-4 Snapshot + DuckDB Read Model Rebuild
        ↓
CR-A Mock 20×60d Vertical Slice
        ↓
Official Account P0-M-1B
        ↓
CR-B AmazingData 20×60d
        ↓
Real P0a
        ↓
Trend BASE
```

R4-A/R4-B 是短收口；Canonical Runtime 不应因此停工。

---

# 29. R4-A Formal Spike Gate Closure

建议一次集中提交完成：

1. Golden Dataset v1：补齐 50/20/30/20，独立文件保存，不再硬编码大量 Python 常量。
2. 每条 Golden 必须有 `source_ref/source_hash/reviewer/reviewed_at`。
3. Formal Run 保存 `golden_truth_version/golden_manifest_hash`。
4. Required Case Gate 改成 per-type count。
5. Case Catalog Close 时生成 `case_catalog_hash`。
6. 修复 Adj Continuity 的 price context。
7. B3 不再制造 `expected_is_st=False`。
8. History Coverage 使用固定 long-listed samples。
9. B2 增加 BSE；新增 BJ historical mapping。
10. Limit Rule PIT 化并改用 Decimal ROUND_HALF_UP。
11. SDK behavior 拆 permission/cache/freshness。
12. Phase Gate 实现 Early Stop。

---

# 30. R4-B Governance Closure

Capability Approval 应：

```text
只输入 name / spike_run_id / approved_by
```

系统自动验证：

```text
PRODUCTION + CLOSED
provenance
catalog/golden seal
evidence closure
blocking_reasons empty
required case types/counts
required endpoint exchanges
account profile
```

Provider Capability 增加 `required_provider_endpoints`，例如：

```text
daily_bar
    MarketData.query_kline

trade_calendar
    BaseData.get_calendar

corporate_action
    InfoData.get_dividend
    InfoData.get_right_issue
```

未调用过 endpoint，不允许 APPROVE。

---

# 31. Publish Exactness 收口

Migration 011 独立保存 validation_hash/details_json。

`publish_snapshot()` 增加显式：

```text
artifact_validation_id
```

禁止隐式选 latest。

`latest_published()/resolve_publish()` 返回 validation id，并提供 validation reader。

---

# 32. CR-1：现在可以立即开始

R4 Spike 收口与 CR-1 可以并行。

CR-1 第一目标是统一审计单元：

```text
ProviderExchange:
    envelope
    payload
```

一个 Provider Exchange 从：

```text
Provider
→ Spike
→ RawWriter
→ Canonical
```

保持同一个 request_id。

同时关闭已知的：

```text
query_kline 内部 calendar call 无独立 envelope
Spike 重新生成 evidence request id
```

---

# 33. RawWriter Acceptance

输入：

```text
ProviderExchange
```

输出：

```text
Raw immutable file
content_hash
schema_hash
row_count
logical_uri
meta_ingest_run
```

要求：

```text
success exchange → payload persisted
failed exchange  → envelope persisted
request_id 不变
secret scrub
immutable
same-hash retry idempotent
different bytes same URI block
```

---

# 34. CR-2：Provider Normalized + Quarantine

流程：

```text
Raw
→ AmazingData Mapper
→ DTO
→ Provider-Normalized Parquet
```

任何 MappingValidationError 必须进入 Quarantine，不得 silent drop / sentinel / 1970 / 0.0。

---

# 35. CR-3：Availability + Canonicalizer

第一批仅五个事实域：

```text
daily_bar
security_status
limit_price
adj_factor
corporate_action
```

每条必须具有：

```text
provider_dataset
observation_type
availability_kind
available_at
source_policy_version
source_revision
data_version
schema_version
selection_reason
```

---

# 36. CR-4：Snapshot + DuckDB Read Model Rebuild

保持：

```text
Canonical Parquet = SoR
DuckDB fact_*     = rebuildable read model
```

Acceptance：

```text
删除 DuckDB fact_* read model
→ 只凭 Snapshot Manifest 重建
→ key/row/hash/aggregate 一致
```

---

# 37. Mock Vertical Slice

不要直接全市场。

第一验收：

```text
20 securities × 60 trading days
```

完整走：

```text
Fixture Provider
→ ProviderExchange
→ Raw
→ Normalized
→ Canonical
→ Snapshot
→ DuckDB Rebuild
→ Skeleton Artifact
→ Artifact Validation
→ Publish
→ Exact Replay
```

---

# 38. Trial L1

下一个实际交易日可以并行执行：

```text
1 → 5 → 20
```

但运行前补：

```text
交易日历判断
typed error
evidence hash
duplicate metrics
```

Stage 100 只验证订阅上限行为，不用于推断平台 Capacity。

---

# 39. 正式账号到位前 Entry Checklist

正式 P0-M-1B 前必须：

```text
[ ] R4-P0 全关闭
[ ] Golden v1 数量完整
[ ] 每个 Golden source_hash 完整
[ ] Golden Manifest hash 固定
[ ] Case Catalog Seal 实现
[ ] Production Account Profile 人工确认并 Freeze
[ ] Provider Doctor = RUNTIME_ACTUAL_LOAD_VERIFIED
[ ] Working tree clean
[ ] full Git SHA
[ ] uv.lock hash
[ ] config hash
[ ] Capability Approval endpoint proof 实现
```

然后：

```text
Doctor
→ Production Account Gate
→ One Production Run
→ B2 + Gate
→ B3 + Gate
→ B4 + Gate
→ B5
→ B6
→ B7
→ Seal Catalog
→ Close
→ Evidence Closure
→ Verdict
→ Human Review
→ Capability Approval
```

---

# 40. 新增 Contract Tests

必须补：

```text
test_required_case_type_missing_blocks_even_if_total_count_met
test_each_required_case_type_has_own_minimum
test_golden_source_hash_required_for_production
test_golden_manifest_hash_mismatch_blocks_resume
test_catalog_result_tamper_blocks_verdict
test_adj_direct_case_requires_price_context
test_b3_does_not_invent_non_st_truth
test_history_coverage_uses_fixed_long_listed_symbols
test_bse_security_master_required
test_bj_mapping_effective_date
test_chinext_pre_reform_limit_rule
test_chinext_post_reform_limit_rule
test_round_half_up_tick
test_permission_only_does_not_pass_cache_freshness
test_cache_requires_two_identical_pulls
test_freshness_observation_required
test_approval_blocks_when_verdict_has_blocking_reason
test_approval_derives_case_refs_itself
test_approval_requires_endpoint_exchange
test_corporate_action_not_approved_without_dividend_right_issue_calls
test_trade_calendar_has_real_spike_capability
test_auth_failure_reason_remains_failed_account
test_blocking_b2_early_stops_b3_to_b7
```

CI 修正：

```yaml
actions/checkout:
  fetch-depth: 0
```

---

# 41. 推荐 Commit 顺序

```text
Commit R4-A1
Golden Dataset v1 + per-case-type gate + catalog/golden seal

Commit R4-A2
Adj/Limit/ST/History/BSE/BJ semantic fixes

Commit R4-A3
SDK permission/cache/freshness + Early Stop + auth failure state

Commit R4-B1
Capability Approval endpoint-proof + closure gate

Commit R4-B2
Migration 011 + explicit artifact_validation_id publish/read

Commit R4-CI
DEVLOG gate shallow-clone fix + L1 calendar/typed errors

Commit CR-1
ProviderExchange + RawWriter

Commit CR-2
ProviderNormalized + Quarantine

Commit CR-3
Availability + Canonicalizer

Commit CR-4
Snapshot + Read Model Rebuild

Commit CR-A
20×60d Mock Vertical Slice
```

每个代码 Commit 同步 DEVLOG，状态：

```text
Implementation Status = DONE
Review Status = PENDING_REVIEW
```

---

# 42. 当前不要做

暂时不要：

```text
全量历史回补
完整 Feature 家族
State/Regime
复杂 API/UI
多进程 Writer
Iceberg/Delta
ClickHouse/Redis
```

当前真正瓶颈已经不是架构，而是：

```text
Formal Truth
+
Canonical Runtime
```

---

# 43. 最终评价

R3 整改已经把项目从“有框架”推进到“接近真实运行”。

但当前应定义为：

```text
Formal-Spike Structure         = PASS
Formal-Spike Truth Closure     = NOT PASS
Formal-Spike Approval Closure  = NOT PASS
```

完成本报告 R4-P0 后，不建议再进行新的大范围架构审查，只需一次 Focused Acceptance Review，确认：

```text
Golden Manifest
Per-type Gate
Catalog Seal
Production Account Identity
Adj/Freshness/BSE/BJ
Approval Endpoint Proof
```

全部通过。

随后正式把工程重点转到：

```text
Canonical Runtime
→ Mock 20×60
→ Official Provider 20×60
→ Real P0a
→ Trend BASE
```
