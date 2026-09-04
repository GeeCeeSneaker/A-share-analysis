# A-share-analysis：项目接管基线审查与任务调度

> Date: 2026-09-05  
> Reviewer takeover baseline: `main@4a5aedafbec2b128b1656d1e152a6938ae0c88c9`  
> Active PR at takeover: PR #9 `P0-M-1B.0 harden positive production identity gates`  
> Operating model: Reviewer负责方案设计、代码审阅、阶段裁决与下一步任务调度；仓库是主要协作与交接载体。

---

## 0. 接管裁决

本项目不重新立项、不推翻既有冻结基线，按现有治理链继续推进。

当前已完成并冻结的核心工程链：

```text
Raw Evidence / Trust Anchor
  -> Provider Normalization + Quarantine
  -> AvailabilityPolicy + Canonical Selection
  -> SnapshotBuilder + DuckDB ReadModel
  -> Deterministic Feature Layer + PIT
  -> Deterministic Market State Layer
```

ADR-022 / 023 / 024 / 025 / 026 已完成 Reviewer VERIFIED / CLOSED / FREEZE。后续任何改动不得借生产数据源接入之名重新解释这些冻结语义；如确需改变，必须走独立 ADR/Amendment 和 C1/C2/C3 设计变更治理。

当前真正的主线不是 CR-7 或策略开发，而是 AmazingData 正式生产身份与数据能力准入。

---

## 1. 当前权威主线

严格保持以下顺序：

```text
P0-M-1B.0 / 0.1
受控 bootstrap + positive identity contract closure
  -> human-confirm scrubbed identity
  -> exact frozen production allowlist

P0-M-1B.1
formal Production B1-B7 on one governed run
  -> formal verdict
  -> Data Sufficiency Matrix
  -> Reviewer capability decision

Provider approval之后
  -> 2020-01-01 -> current 正式回填
  -> 数据平台稳定性/完整性验证
  -> 再进入后续数据域扩展或 CR-7
```

在 AmazingData Provider capability 正式批准前，禁止：

- 将 Trial / bootstrap / local smoke 证据冒充 Production evidence；
- 启动 2020+ 正式回填；
- 以“非试用账号”作为 production 身份的隐式升级条件；
- 开始 CR-7、策略、回测、组合、交易执行等新主线；
- 未经 Data Sufficiency + formal verdict 就批准 provider capability。

---

## 2. PR #9 首轮接管审查结论

状态：**REOPENED / CHANGES REQUIRED / DO NOT MERGE**。

### P0-01：最终 head CI 未闭环

接管时 PR #9 head 为 `d32b516ceb27f0c45a1d1b4286fa4d8c19f5424a`。

其 CI run `33928995279` / run 282 为 FAILURE：

- Ubuntu py3.14：Ruff lint PASS，Ruff format FAIL；
- Windows py3.12：Ruff lint PASS，Ruff format FAIL；
- Windows py3.14：Install uv FAIL。

因此早期 `66ab5ec7` / run 277 的 1449 passed 不能作为当前最终 head 的合并证据。

### P0-02：production identity exact-value / whitespace fail-closed 不一致

当前 `load_frozen_production_identity()` 的实现路径先对 YAML 中 `production_account_profile_id` 执行 `.strip()`，再构造 `FrozenProductionIdentity` 并执行 freezable predicate。

这会把：

```text
" UNKNOWN_abcdef123456"
"UNKNOWN_abcdef123456 "
```

规范化成合法的 `UNKNOWN_abcdef123456` 后再校验。

但 PR #9 新增测试 `test_config_rejects_non_freezable_or_wrong_profile_ids` 明确要求以上带首尾空白的配置被拒绝。这不仅是测试与实现不一致，也是治理语义问题：正式身份配置必须是 exact value，不能通过静默规范化获得 production truth。

同类边界也存在于 bootstrap safe projection：doctor 返回的 profile id 当前先 `.strip()` 再判断 generated/freezable。该路径必须与 frozen config 使用相同的 exact-value discipline。

### PR #9 必须完成的修复

1. 对原始 profile id 直接做 exact generated/freezable 校验；验证前不得 `.strip()` 规范化；
2. 保留并补强 leading/trailing whitespace 的 config adversarial tests；
3. 给 bootstrap 增加 leading/trailing whitespace candidate 对抗测试，必须得到 `NOT_TESTABLE_PROFILE`，不得进入 `IDENTITY_CANDIDATE`；
4. 三平台最终 head 全量 CI 成功；
5. 文档只引用最终 head 对应的 CI run；
6. 本 PR 审核关闭前，`configs/production_account.yaml` 保持为空；不得执行 online bootstrap / B1-B7 / Data Sufficiency / verdict / Provider approval。

以上要求已同步写入 PR #9 Conversation。

---

## 3. 下一阶段任务调度

### T0 — PR #9 contract honesty closure（当前唯一 P0）

Owner/Developer 完成 P0-01 / P0-02 修复与最终 CI；Reviewer 复审代码、测试、最终 workflow evidence。

**Exit Gate**：

```text
PR #9 final head
+ exact profile identity contract
+ whitespace adversarial tests
+ Ubuntu 3.14 SUCCESS
+ Windows 3.12 SUCCESS
+ Windows 3.14 SUCCESS
+ configs/production_account.yaml still empty
=> Reviewer may close/merge PR #9
```

### T1 — Controlled live bootstrap + human identity confirmation

仅在 T0 合并后，在受控 Windows + 官方 AmazingData SDK 环境执行 online bootstrap。只允许脱敏输出进入审查；credentials / Token / host / port / raw profile / raw SDK stdout/stderr 不得进入 Git。

若产出 `IDENTITY_CANDIDATE`，由 Owner/Reviewer 人工确认 scrubbed account_profile_id 是否属于项目正式账号。

### T2 — Separate identity-freeze governance commit

人工确认通过后，用独立治理提交写入：

```yaml
production_account_profile_id: "<exact scrubbed generated id>"
confirmed_at: "<timezone-aware ISO-8601>"
confirmed_by: "<safe human/operator marker>"
```

同批更新 `docs/DEVLOG.md` 与 `docs/project/DEVELOPMENT_MANAGEMENT.md`，并保留 focused production identity gates。

### T3 — Formal Production B1-B7

identity freeze 合并且 CI 全绿后，运行一条受治理的 Production run，B1-B7 全部绑定到该 run；禁止 Trial/bootstrap 证据替代，禁止 caller-selected partial Production phase。

### T4 — Formal verdict + Data Sufficiency Matrix

基于同一 Production run：

- formal verdict；
- Core 8 + Optional 4；
- 2020+ history coverage；
- index constituent/weight；
- industry weight/daily；
- equity/free-float；
- margin；
- financial PIT；
- capability gap / blocker / workaround 分级。

Reviewer 才在此阶段给出 AmazingData capability GO / CONDITIONAL GO / NO-GO。

### T5 — 2020+ backfill and platform acceptance

仅 Provider approval 后执行 2020-01-01 -> current；不得拉取或为 Feature warmup 回填 2020 年以前数据。回填完成后再做完整性、可重放、PIT、稳定性和性能验收。

---

## 4. 当前 P1 治理债务

这些问题真实存在，但不得抢占 T0–T4 主线。

### P1-DOC-01 README 明显漂移

README 仍描述 Phase 0 初始骨架、migrations 001-004、早期目录结构；当前主线已有 migrations 001-024、Canonical/Snapshot/Feature/State 等完整层次。

要求：在生产身份/Provider verdict 主线稳定后，重写 README 为“当前事实入口”，明确 frozen baseline、当前 architecture layers、正式运行边界与 authoritative docs。

### P1-DOC-02 Risk Register 漂移

`docs/risk_register.md` 仍保留早期“自动化测试 84 项”等信息，未反映当前 1400+ tests、production identity freeze、single-provider production qualification 等新风险。

要求：后续按 append-only/status-change discipline 补充：

- Production identity misclassification / secret leakage；
- AmazingData formal capability/data sufficiency risk；
- public repo governance / credentials isolation；
- README/management truth drift；
- Windows SDK/runtime reproducibility。

---

## 5. Reviewer 后续固定工作流

每次用户通知“仓库已更新”后，Reviewer 默认执行：

1. 锁定 `main` 和 active PR 最新 SHA；
2. 比较上次审阅基线到当前增量；
3. 检查代码、测试、CI、DEVLOG、DEVELOPMENT_MANAGEMENT、ADR/Amendment 一致性；
4. 优先找 correctness / evidence / replay / PIT / identity / approval anti-bypass 问题，而不是只看格式；
5. 对发现的问题分 P0/P1/P2，并明确 exit gate；
6. 审查结论与下一步工作要求写回仓库（PR Conversation 或 design handoff document）；
7. 未达到 exit gate 不进入下一阶段；
8. 达到 exit gate 时明确 CLOSE / MERGE / FREEZE / START NEXT STAGE 裁决。

---

## 6. 长期技术原则

继续沿用并强化：

```text
Provider-neutral
PIT correctness
Raw -> Canonical -> Feature -> State
available_at / ingested_at traceability
Immutable Evidence
Exact Replay
Fail Closed
No Silent Fallback
No Hard-coded Trading Rule Truth
No Trial-to-Production Upgrade
No Capability Approval Without Run-bound Evidence
2020-01-01 History Boundary
```

策略研究、回测和未来模拟盘/实盘运行可以消费本平台，但不得反过来用策略结果“倒推”修改数据层事实。数据基座首先要成为可审计、可重放、可证明的数据事实系统。

---

## 7. 当前 Reviewer 状态

```text
Project takeover                 ACTIVE
Main baseline                    4a5aedaf
CR-5 / ADR-025                   VERIFIED / CLOSED / FREEZE
CR-6 / ADR-026                   VERIFIED / CLOSED / FREEZE
PR #8                            MERGED / CLOSED
PR #9                            REOPENED / CHANGES REQUIRED
AmazingData production identity  NOT FROZEN
Formal Production B1-B7          NOT EXECUTED
Data Sufficiency Matrix          NOT EXECUTED
Provider capability approval     BLOCKED
Next action                      PR #9 P0-01/P0-02 closure
```
