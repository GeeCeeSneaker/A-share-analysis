# A-share-analysis 外部审计 REV-01—REV-08 管理裁决与整改路线

> Date: 2026-09-05  
> External review: PR #11 / `docs/design/PROJECT_REVIEW_HANDOFF_20260905.md`  
> External review head: `df2d9b78cc9ad5768540405a5bb6aea063f8677b`  
> External review CI: GitHub Actions run `33951064678` / run 296 SUCCESS  
> Audit merge: `0f692a92c68b71066c1f48273e3d69cee3dc6398`  
> Manager disposition review: PR #11 review `5120242178`  
> Status: AUDIT_ACCEPTED / REMEDIATION_REPRIORITIZED / IMPLEMENTATION_NOT_YET_DONE

## 1. 管理结论

外部审计材料整体 **ACCEPT / KEEP**。审计对事实、合成输入、条件性风险和未验证事项做了较好区分，没有把潜在风险描述成已发生事故，也没有把文档/CI 证据冒充真实生产验证。

但原建议优先级不能直接照搬。当前项目正处于 AmazingData 正式账号 T1 controlled online bootstrap 之前，因此凡是会影响“真实凭证进入进程后，identity candidate 是否诚实、安全”的问题必须前置关闭；恢复、历史研究、无人值守、规模和跨版本重放问题则放在真正进入对应阶段前关闭。

本裁决不重开 CR-5 / CR-6 已冻结的业务语义，不改变 `2020-01-01` 历史边界，不批准 Provider capability，也不允许用审计整改替代正式 T1/T2/T3/B1-B7/Data Sufficiency 流程。

## 2. REV 事项重新分级

| ID | 管理裁决 | 新优先级 / Gate | 处理原则 |
|---|---|---|---|
| REV-01 | ACCEPT | **P0 / T1 PRE-BLOCKER** | runtime verdict 与 candidate 状态必须一致；权限代码必须解析出真实数字 code |
| REV-02 | ACCEPT + SPLIT | **REV-02A P0 / T1 PRE-BLOCKER**；REV-02B P1 | 先关闭对外输出/异常原文泄露；临时捕获介质按威胁模型另行治理 |
| REV-03 | ACCEPT | **P1 / RECOVERY-BLOCKER** | T1/T2/T3 不受阻；任何 orphan 删除、恢复清理、全量回填前必须关闭 |
| REV-04 | ACCEPT / PRIORITY UP | **P1 / IMMEDIATE GOVERNANCE FIX** | 将三矩阵“人工要求全绿”与 Actions 阻断配置统一 |
| REV-05 | ACCEPT | **P1 / HISTORICAL-RESEARCH-READINESS BLOCKER** | 保留 observed-at-ingest 真值；另设版本化研究可用性假设，不伪造历史已知 |
| REV-06 | ACCEPT | **P1 / UNATTENDED-RUNTIME BLOCKER** | 受控人工 T1 不阻断；无人值守和 2020+ 大回填前必须具备 hard deadline / kill / reap |
| REV-07 | ACCEPT AS MEASUREMENT RISK | P2 now → **P1 before full 2020+ backfill** | 先量化 RSS/耗时/读取量/重跑成本，再决定 streaming/partition/cache |
| REV-08 | ACCEPT WITH PRESERVATION | P2 now → **P1 before long-lived cross-version replay** | fingerprint 继续 fail closed；补 provenance / historical replay，不允许删 hash 检查 |

## 3. AUDIT-H1 — T1 前置信任边界收口（立即启动）

### 3.1 Scope

只处理：

- REV-01 runtime/entitlement honesty；
- REV-02A safe-output boundary；
- REV-04 CI gate honesty；
- 相应 tests / DEVLOG / DEVELOPMENT_MANAGEMENT / runbook truth sync。

明确不处理：orphan recovery、historical research availability、hard timeout subprocess、全量性能重构、Feature/State fingerprint 算法本身。

### 3.2 REV-01 设计要求

#### Online T1

`IDENTITY_CANDIDATE` 必须同时满足：

```text
sdk_state == SDK_INSTALLED
runtime_verdict == RUNTIME_ACTUAL_LOAD_VERIFIED
AUTHENTICATED == YES
QUERY_READY == YES
profile_parsed == true
profile_is_freezable == true
entitlement_codes contains >= 1 numeric code
production_identity_status == NOT_FROZEN
```

任何 `RUNTIME_PACKAGE_VERIFIED`、`RUNTIME_PATH_AMBIGUOUS`、`NOT_VERIFIED` 都不得产生 online `IDENTITY_CANDIDATE`。

#### Offline preflight

必须区分强弱证据：

- `RUNTIME_ACTUAL_LOAD_VERIFIED`：可以报告 `OFFLINE_RUNTIME_VERIFIED`；
- `RUNTIME_PACKAGE_VERIFIED`：只能报告 package-level preflight，例如 `OFFLINE_PACKAGE_VERIFIED`，不得冒充 actual runtime load；
- ambiguous / unverified：`NOT_TESTABLE_RUNTIME` 或等价 fail-closed 状态。

Offline 结果永远不是 T1 identity evidence。

#### Permission codes

不得继续以 `bool(permission_codes)` 作为 entitlement evidence。

要求建立确定性解析：

- 接受数字 code，以当前公开分隔符 `| , ; whitespace` 分割；
- 解析后至少存在 1 个非空十进制 code；
- empty / whitespace-only / separators-only / mixed invalid character 全拒绝；
- safe projection 可以输出规范化的 scrubbed code 表达，但不得把“存在 permission code”升级成具体数据能力批准。

### 3.3 REV-02A 设计要求

建立统一 **Safe Diagnostic Projection** 边界，覆盖 bootstrap / provider-doctor / doctor report / lifecycle error / stdout / stderr / output file。

最低要求：

1. `scrub_dict` 升级为递归 value scrubber，至少支持 dict / list / tuple 嵌套；
2. credential-bearing login/session error 不得把 raw `str(exc)` 写入 lifecycle reason、doctor `auth_error` 或 CLI 输出；使用稳定 typed error class/code + allowlisted safe context；
3. `provider-doctor` stdout 与 `--output` 必须经过同一安全投影，不得直接 dump raw doctor report；
4. synthetic sentinel adversarial tests 覆盖：
   - nested dict/list；
   - exception text；
   - native fd1/fd2；
   - Python stderr；
   - lifecycle reason；
   - report stdout；
   - report file；
5. 不使用真实账号/Token/endpoint 作为测试样本。

### 3.4 REV-02B 临时介质裁决

当前 `TemporaryFile` 会在受控本地机器上暂存 SDK 原始 fd 输出；这与“秘密不得进入 Git / 持久项目证据”的治理边界不同。

本轮不要求为了消除本地 ephemeral capture 立即重写 fd 捕获架构，但必须：

- 修正文档中任何“raw text 从不落盘/从不持久化”过强表述；
- 明确 TemporaryFile 仅为本机临时捕获、自动关闭清理、不得进入 repository/evidence；
- 在 REV-06 subprocess hard-deadline 方案中一并评估 pipe/memory IPC 与 native fd backpressure，避免为“纯内存”引入死锁。

### 3.5 REV-04 CI 裁决

本项目此前所有 Reviewer merge gate 实际均要求：

```text
Windows 3.14 SUCCESS
Windows 3.12 SUCCESS
Ubuntu 3.14 SUCCESS
```

因此 Actions 配置必须与管理事实一致：**三腿均作为 required job，不允许 `continue-on-error` 将兼容性腿失败汇总为 workflow SUCCESS。**

公共 CI 边界保持不变：

- 不安装 AmazingData proprietary SDK；
- 不持有正式账号凭证；
- CI green 只证明 repository-verifiable checks，不证明真实 Provider 可用。

状态报告必须分三层：

1. Repository CI；
2. controlled local SDK/runtime evidence；
3. formal account / Production evidence。

### 3.6 AUDIT-H1 Exit Gate

```text
[ ] ambiguous/unverified runtime never yields VERIFIED / IDENTITY_CANDIDATE
[ ] online candidate requires RUNTIME_ACTUAL_LOAD_VERIFIED
[ ] offline package-only and actual-load statuses are distinct
[ ] permission empty/whitespace/separator-only/mixed-invalid rejected
[ ] >=1 numeric permission code required for entitlement evidence
[ ] nested dict/list/tuple synthetic secret scrub PASS
[ ] raw exception sentinel absent from lifecycle/doctor/CLI/stdout/stderr/file
[ ] provider-doctor stdout and --output share safe projection
[ ] Windows 3.14 required CI PASS
[ ] Windows 3.12 required CI PASS
[ ] Ubuntu 3.14 required CI PASS
[ ] Ruff / format / mypy / full pytest / Spike / SDK-absent / governance gates PASS
[ ] production_account.yaml remains empty
[ ] no live T1 / T2 / T3 / B1-B7 executed during remediation
```

AUDIT-H1 未合并前，**暂停正式账号凭证 online bootstrap**。

## 4. AUDIT-R1 — Recovery safety（REV-03）

目标：任何恢复/清理动作都不能因为“未登记在旧两张表”误删合法新层产物。

要求：

- 建立统一 `ArtifactReferenceIndex`（命名可调整），聚合当前所有受支持 component tables + valid manifests；
- URI/path root 规范单一化；
- unknown schema/version、损坏 manifest、in-progress artifact、无法确认归属路径一律 PROTECTED；
- `find_orphan_files` 的语义改为 candidate detection，不直接等价 `deletable`；
- 清理链必须 `scan -> classify -> dry-run -> quarantine/grace period -> explicit delete -> audit record`；
- normalization / snapshot / feature / state 合法产物与真实 synthetic orphan 都有回归；
- `publish_recovery.md` 替换占位命令并完成一次本地演练。

Gate：**关闭前禁止任何 orphan 自动/人工删除作为正式 runbook 操作；全量 2020+ backfill 前必须关闭。**

## 5. AUDIT-HIST — Historical PIT / research semantics（REV-05）

### 5.1 保留 Canonical 真值

当前 `OBSERVED_AT_INGEST -> received_at` 是保守、诚实的观测语义，继续 KEEP。不得为了方便回测把今天采集的历史记录伪装成当年已知。

### 5.2 新增研究层可用性轴

在后续历史研究设计中区分：

- event/effective time；
- source published time（有可靠来源时）；
- observed/ingested time（真实系统观测）；
- research assumed available time（显式版本化假设）。

Research assumption 必须是独立、版本化、可披露的研究视图/政策，不覆盖 Canonical observed truth。

### 5.3 立即修正文档漂移

- `run_backfill.md` Stage D 从 `2014/2015 -> current` 改为 `2020-01-01 -> current`；
- 删除/弃用“回补后 available_at 使用 CONSERVATIVE_ASSUMED”与当前实现矛盾的陈述；
- `configs/base.yaml` 现有 legacy `CONSERVATIVE_ASSUMED` 配置不得继续被误认为 Canonical runtime truth；明确 deprecated/non-authoritative，后续若用于 research assumption 必须另起 versioned contract。

Gate：历史数据可以作为 raw/provider coverage 被采集，但在研究可用性政策未批准前，**不得宣称 historical PIT research-ready / no-lookahead backtest-ready**。

## 6. AUDIT-RUNTIME / PERF — REV-06 + REV-07

### REV-06

在无人值守、自动恢复和 2020+ 大规模回填前实施 subprocess/equivalent isolation：

- parent hard deadline；
- child kill + reap；
- login/query hang synthetic tests；
- terminal failure ledger；
- no half publication / permanent lock / orphan process；
- total retry budget + idempotency；
- cleanup 不输出 raw sensitive text。

受控、人工监督的一次 T1/T2/T3 不被 REV-06 单独阻断。

### REV-07

禁止“先重构再测”。沿现有 Stage A/B/C 放量建立 benchmark evidence：

- rows / securities / date span；
- bytes read/written；
- peak RSS；
- wall-clock；
- retry/re-run cost；
- artifact counts / sizes；
- target environment identity。

得到证据后再决定 partition pruning / streaming batches / incremental index / verification cache。所有性能优化必须保持 artifact semantics、PIT、hash/replay correctness 不变。

## 7. AUDIT-REPLAY — REV-08

严格 code fingerprint **KEEP / FREEZE**，不得通过忽略 mismatch 解决兼容性。

优先设计旁路 Build Provenance Ledger，避免无必要修改已冻结 Feature/State semantic identity：

- git source commit SHA；
- dependency lock hash（如 `uv.lock`）；
- Python/version/platform；
- builder fingerprint；
- contract/registry versions；
- upstream artifact identities。

定义三种明确结果：

```text
CURRENT_ENV_VERIFIED
HISTORICAL_ENV_REQUIRED
REBUILD_REQUIRED / INCOMPATIBLE
```

旧产物必须能定位到历史源码/依赖环境；当前环境不兼容时 fail closed；必要时受控重建，不删除 fingerprint gate。

## 8. 新的权威执行顺序

```text
PR #11 external audit record            MERGED / PRESERVED
        ↓
AUDIT-H1 (REV-01 + REV-02A + REV-04)    P0/P1 IMMEDIATE
        ↓ merge + all required CI green
T1 controlled online bootstrap
        ↓
T2 human identity confirmation
        ↓
T3 separate production identity freeze
        ↓
Formal Production B1-B7
        ↓
Data Sufficiency Matrix + verdict
        ↓
AmazingData capability decision
        ↓
AUDIT-R1 + AUDIT-HIST + staged PERF gates
        ↓
2020-01-01 -> current full backfill
        ↓
platform acceptance / historical research readiness
```

REV-06 必须在无人值守/大规模运行前关闭；REV-08 在长期 artifact 跨版本生命周期形成前关闭。

## 9. 下一开发任务

立即创建独立整改 PR（建议标题：`fix: close audit T1 trust-boundary blockers`），只实现 **AUDIT-H1**。

禁止同时修改：

- `configs/production_account.yaml`；
- CR-5/CR-6 frozen feature/state semantics；
- migrations 023/024；
- Provider capability approval；
- historical backfill；
- strategy / backtest / portfolio / trading。

开发完成后提交：代码 diff、focused adversarial tests、最终 head 三平台 required CI 证据、DEVLOG/DEVELOPMENT_MANAGEMENT 同步。Reviewer 复审通过后才恢复真实 T1。
