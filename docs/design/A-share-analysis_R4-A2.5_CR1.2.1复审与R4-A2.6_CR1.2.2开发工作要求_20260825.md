# A-share-analysis：R4-A2.5 / CR-1.2.1 复审结论与 R4-A2.6 / CR-1.2.2 开发工作要求

> **Review Date**：2026-08-25 12:04 +08:00  
> **Reviewed Repository HEAD**：`cdd360879c3a6361f4c952bde39174d3d46dfbcb`  
> **Primary Implementation Commit**：`f3694bdfc4ca159968ce66038fbbd0c32a6b6743`  
> **CI Fix Commit**：`13d02a191f11c22b836da42ae9ae5707f9e355f1`  
> **Previous Reviewer Requirement Commit**：`947fcec3ce55a9cd1886fae9a113ba3771ab1c65`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2.5 Formal Replay / Rule-SoR Closure、CR-1.2.1 Raw Commit Hardening、ADR-013、CA Event Taxonomy、DEVLOG / Development Management、CI  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.6 Formal Truth / Manifest Closure + CR-1.2.2 Probe Exchange Enforcement**  
> **CR-2**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. 裁决摘要

本轮质量继续明显提升，而且上一轮绝大多数整改已经真正落到 runtime：

```text
Formal limit consumers
→ 已显式传入 run-bound TradingRuleBook

Trading Rule
→ 已形成 rule_manifest.json + immutable versions + run binding

Review Gate
→ 已有 evidence-root path confinement / hash / timestamp schema

Corporate Action
→ 已增加 dividend + right_issue 两独立事件流

B5/B6 payload shape
→ 已修复 scalar-list / polars 行提取

Raw Commit
→ 已增加 orphan detection / same-byte recovery / quarantine

CI
→ 当前 main Actions 已正向确认 GREEN
```

因此，本轮 **不回退 ADR-013 主体设计，也不重新打开已经关闭的 hidden-calendar / meta-anchor / full-request lineage 问题**。

但 Reviewer 复核发现，Formal Runtime 仍有两个直接违反基础不变量的 P0，同时 Rule Manifest 自身还有两个 provenance / confinement P0：

```text
Every real provider exchange on a formal probe path must be persisted,
including failures.

Every formal Golden semantic claim must be encoded in the actual bound
Golden truth, not only in synthetic tests.

Every ACTIVE semantic-SoR file reference must be path-confined.

Manifest governance metadata and dataset bytes must describe one coherent
version identity.
```

当前尚未全部满足，因此 **R4-A2.5 / CR-1.2.1 不能 VERIFIED**。

---

# 1. 已通过、允许保留的实现

以下内容本轮通过，后续禁止回退。

## 1.1 Formal Rule Book 显式注入

保留：

```text
validate_limit_rule(..., book=<required>)
book=None => structured FAIL
B3 -> ctx.rule_book
B5 -> ctx.rule_book
Golden limit/BJ -> ctx.rule_book
ACTIVE advance adversarial replay test
bound rule tamper fail-closed
```

本轮已证明 B3/B5/Golden limit 语义不再通过默认 working-tree rule book 静默漂移。

## 1.2 Trading Rule Version Model 基础

保留：

```text
configs/trading_rules/
  rule_manifest.json
  versions/<v>/rules.yaml
  evidence/
```

以及：

```text
load_active_rules()
load_bound_rule_book()
dataset_files[]
dataset_hash
immutable coexisting versions
```

后续是补强 selector / dataset coherence，不回到目录 glob 合并。

## 1.3 Rule Review Gate 基础

保留：

```text
COMPILED -> REVIEWED
source artifact bytes hash
64 lower-hex
ISO-8601 timestamp
artifact kind allowlist
evidence-root path confinement
```

## 1.4 Raw Commit Recovery

本轮 orphan recovery 主体方向通过：

```text
meta-last closure anchor
same-byte orphan retry => recover
conflicting orphan => quarantine + BLOCK
list_orphan_payloads()
fault-injection tests
```

该部分只留 P1 hardening，不作为本轮主 P0。

## 1.5 CI

Reviewer 已通过 GitHub Actions API 正向确认当前 `main`：

```text
run 36 / HEAD cdd3608... => completed / success
run 35 / 13d02a1...     => completed / success
```

所以本轮 **CI = VERIFIED GREEN**，不再以“待确认”作为阻塞原因。

---

# 2. P0-01：B5 / B6 仍存在绕过 ProbeExecutor 的真实 Exchange 路径

## 2.1 当前代码

B5 当前仍直接执行：

```python
symbols_exchange = ctx.target.get_code_list_exchange("EXTRA_STOCK_A")
symbols_all = [str(s) for s in _flat_values(symbols_exchange.payload)]
sym_meta = ctx.evidence_from_exchange(symbols_exchange)
```

这条路径成功时最终会手工持久化，但 **失败时不会经过 ProbeExecutor 的统一异常处理**：

```text
get_code_list_exchange()
→ ProviderError(exchange=<failure exchange>)
→ exception escapes before symbols_exchange assignment
→ failure exchange not persisted by this path
→ no structured SpikeCase from ProbeExecutor
```

B6 更严重：

```python
symbols_exchange = ctx.target.get_code_list_exchange("EXTRA_STOCK_A")
symbols = [str(s) for s in _flat_values(symbols_exchange.payload)][:3]
```

当前 B6 既没有通过 `ProbeExecutor.call()`，也没有紧随其后 `ctx.evidence_from_exchange(symbols_exchange)`。

所以成功路径本身就可能形成：

```text
real ProviderExchange created
→ payload consumed
→ exchange not persisted
```

这直接违反 CR-1 / CR-1.2 的核心不变量：

```text
Every real provider exchange on the formal Spike path is immutable evidence.
```

## 2.2 为什么现有静态测试没有挡住

当前静态测试主要禁止：

```text
get_code_list()
get_calendar()
query_kline()
```

这类 payload-only method。

但：

```text
ctx.target.get_code_list_exchange()
```

虽然返回显式 Exchange，如果调用点绕过统一持久化 / failure handling，一样会丢 evidence。

所以“只允许 *_exchange”不是充分条件。

真正契约应是：

```text
formal provider call
→ approved exchange execution boundary
→ success/failure both persisted
→ structured outcome
```

## 2.3 强制修复

B5 / B6 code-list prerequisite 必须改成：

```python
payload, meta = executor.call(
    "BaseData.get_code_list",
    lambda: ctx.target.get_code_list_exchange("EXTRA_STOCK_A"),
    ...
)
```

或者引入一个等价的统一 helper，但该 helper 必须具备与 `ProbeExecutor.call()` 相同的：

```text
ProviderExchange type assertion
success RawWriter persistence
failure exchange persistence
ProviderError -> structured case
no last_envelopes lookup
```

不得继续保留“调用者自己记得成功后手工 persist”的 correctness contract。

## 2.4 Required Tests

```text
[ ] B5 code_list success => exactly one corresponding raw meta
[ ] B5 code_list permission failure => failure meta persisted
[ ] B5 code_list permission failure => structured NOT_TESTABLE case, no unhandled escape
[ ] B6 code_list success => raw meta persisted
[ ] B6 code_list permission failure => failure meta persisted + structured case
[ ] instrumented Fake/Spy: formal B2-B7 real-call count == persisted exchange count
[ ] static guard catches direct formal ctx.target.*_exchange calls that bypass approved execution boundary
```

静态守卫不要求误伤 Golden `_DomainCollector` 这类已经“调用即 persist”的专用边界，但必须把允许边界做成显式 allowlist，而不是靠开发者记忆。

---

# 3. P0-02：CA Event Type 只存在于新测试，尚未进入实际 Golden v3 Truth

## 3.1 当前 validator 行为

CA validator 当前只有在：

```python
expected_type = case.expected_fields.get("event_type")
```

非空时才执行事件类型匹配。

如果 `event_type` 为空，则 exact-date 任意 corporate-action event 都可以继续进入后续验证。

## 3.2 实际 Golden v3 仍是 untyped

当前真实：

```text
data/golden/provider/amazingdata/golden_cases_v3.jsonl
```

中的 Corporate Action case 仍类似：

```json
{
  "case_type": "golden_corporate_action",
  "event_class": "DIVIDEND_EX_DATE",
  "expected_fields": {
    "IS_WD_SEC": true
  }
}
```

也就是说：

```text
truth already says event_class = DIVIDEND_EX_DATE
but validator ignores that taxonomy
because expected_fields.event_type is absent
```

新测试甚至明确保留：

```text
untyped case accepts any event type
```

因此开发日志中“`expected_fields[event_type]` 已声明、v3 数据无需重封”的表述与实际数据不一致。

## 3.3 强制契约

Formal Golden CA 不得存在“untyped accepts any”的旁路。

推荐优先方案：直接使用已经进入 Golden semantic identity 的 `event_class` 作为类型事实来源：

```text
DIVIDEND_EX_DATE    -> DIVIDEND
RIGHT_ISSUE_EX_DATE -> RIGHT_ISSUE
```

规则：

```text
formal golden_corporate_action
=> event type MUST resolve exactly once

expected_fields.event_type present
=> must agree with event_class-derived type

unknown / missing / conflicting type
=> FAIL CLOSED
```

这样不需要静默修改历史 v3 bytes，也不会破坏已有 case semantic hash。

如果开发团队坚持 `expected_fields.event_type` 才是唯一 SoR，则必须：

```text
create NEW Golden candidate version
recompute case_semantic_hash
normal review/version workflow
never edit v3 in place
```

二选一，但不能继续保留“真实 v3 untyped、synthetic test typed”的状态。

## 3.4 Required Tests

```text
[ ] load ACTUAL golden_cases_v3.jsonl CA cases and resolve every event type
[ ] actual DIVIDEND_EX_DATE case + same-date RIGHT_ISSUE-only provider evidence => EVENT_TYPE_MISMATCH
[ ] actual RIGHT_ISSUE case + DIVIDEND-only evidence => EVENT_TYPE_MISMATCH
[ ] unknown CA event_class => fail closed
[ ] event_class and expected_fields.event_type disagree => fail closed
[ ] formal CA case cannot pass with event type unresolved
```

删除 / 反转当前：

```text
test_untyped_case_accepts_any_event_type
```

Formal path 不得允许该语义。

---

# 4. P0-03：ACTIVE Rule Manifest 的 dataset_files[] 未做 path confinement

## 4.1 当前不一致

当前系统已经有 `_confined()`，并正确用于：

```text
review source artifact ref
bound rule dataset replay
```

但是 `load_rule_manifest()` 对 `dataset_files[]` 当前仅做：

```python
(root / rel).is_file()
```

`load_active_rules()` 的 dataset hash 也直接读取：

```python
(root / rel).read_bytes()
```

因此 ACTIVE manifest 理论上可以声明：

```text
../../outside.yaml
```

只要文件存在且 manifest hash 匹配，NEW run 的 ACTIVE selector 就可能读取 rules root 之外的数据。

这和 review artifact 已建立的 confinement 纪律不一致，也破坏：

```text
configs/trading_rules/versions/* = Trading Rule SoR boundary
```

## 4.2 强制修复

`load_rule_manifest()` 必须在任何 existence/read/hash 操作前，对每个 `dataset_files[]` 做 confinement。

最低要求：

```text
relative path only
no absolute path
no .. escape
no symlink escape
must remain under configs/trading_rules
```

更推荐进一步约束：

```text
dataset_files[] must be under versions/<rule_version>/
```

这样 manifest selector id 与版本目录形成结构性一致。

## 4.3 Required Tests

```text
[ ] manifest dataset_files = ../../outside.yaml => BLOCK before bytes read
[ ] absolute dataset path => BLOCK
[ ] symlink escape outside rule root => BLOCK
[ ] dataset file outside versions/<rule_version>/ => BLOCK (if adopting strict layout)
[ ] valid version-local multi-file dataset => PASS
```

同一 confinement helper 应同时被 ACTIVE load 和 bound load 复用，避免两套规则漂移。

---

# 5. P0-04：Rule Manifest 与 Dataset Governance Metadata 尚未形成单一一致事实

## 5.1 当前已经出现真实不一致

当前 `rule_manifest.json`：

```text
source_version = "2026-08-24.1"
```

而 ACTIVE `rules.yaml`：

```text
source_version = "SSE/SZSE/BSE public trading rules, consolidated 2026-08"
```

系统目前没有检查这两个值是否一致。

此外，manifest 与 dataset 同时维护：

```text
review_status
source_version
review_provenance
version identity
```

但 `load_active_rules()` 当前主要只校验：

```text
dataset_hash
dataset_version == book.version
```

未完整校验治理字段一致性。

## 5.2 直接风险

例如：

```text
manifest.review_status = REVIEWED
rules.yaml.review_status = COMPILED
```

Production Review Gate 会因为 `book.review_status` 而挡住，这一点安全；但 TRIAL run 当前会把：

```text
run.trading_rule_review_status = manifest.review_status
```

记录成 REVIEWED，形成 provenance 谎报。

反向：

```text
manifest = COMPILED
rules.yaml = REVIEWED
```

Review Gate 可能按 dataset bytes PASS，但 Run 记录仍写 COMPILED。

这不是 Exact Replay bytes 问题，而是 **Formal Provenance Truth 一致性问题**。

## 5.3 Version Identity 也需要拆清

当前：

```text
manifest.rule_version = v20260824-compiled
rules.yaml.version    = 2026-08-24.1
```

但 Run 的：

```text
trading_rule_version
```

实际保存的是 `rule_book.version`（即 YAML content version），而不是 manifest selector/version id。

文件路径虽然仍能帮助 replay，但版本血缘字段语义不清晰。

## 5.4 强制修复

必须明确单一契约。推荐：

```text
trading_rule_version          = manifest.rule_version
trading_rule_dataset_version  = rules.yaml.version
trading_rule_dataset_files[]
trading_rule_dataset_hash
trading_rule_review_status
trading_rule_source_version
```

ACTIVE load 时强制：

```text
manifest.review_status == dataset.review_status
manifest.source_version == dataset.source_version
manifest.review_provenance == dataset.review_provenance
manifest.dataset_version == dataset.version
```

如果决定某些治理字段只应存在于 manifest，则删除 dataset 中重复 SoR，并在 ADR-013 amendment 中明确。

不接受“两个地方都写，但不比较”。

## 5.5 Required Tests

```text
[ ] manifest REVIEWED vs dataset COMPILED => BLOCK new_run
[ ] manifest COMPILED vs dataset REVIEWED => BLOCK
[ ] source_version mismatch => BLOCK
[ ] review_provenance mismatch => BLOCK
[ ] dataset_version mismatch => BLOCK
[ ] run json binds selector version AND dataset content version explicitly
[ ] ACTIVE vN -> vN+1 after run creation => historical replay still uses exact bound vN identity
```

---

# 6. P1-01：SpikeRun.provenance_complete() 应纳入 Rule Binding

ADR-013 后 Trading Rule 已是 formal semantic SoR，但当前 `provenance_complete()` 仍主要要求：

```text
code / env / config / sdk / runtime / account
+ Production Golden binding
```

Trading Rule 缺失目前由 `compute_verdict()` 额外 block，因此 final verdict 暂未形成 false GO。

但 provenance API 自身已经落后于系统 contract。

建议把 Production formal provenance 明确扩展为：

```text
golden binding present
AND
trading-rule selector version present
AND
dataset files/hash present
AND
review status present
```

这样 Capability Approval、未来 Replay/Publish 复用该 API 时不会得到“provenance_complete=True 但 semantic SoR 未绑定”的矛盾结果。

---

# 7. P1-02：Rule Review ACTIVE 切换建议做 crash-safe / lineage-safe

当前 `scripts/rules/review.py` 已正确创建新 immutable version，但 ACTIVE manifest 最后通过普通 `write_text()` 切换。

建议补强：

```text
write temp manifest
fsync / atomic replace
```

至少保证 crash 只产生：

```text
old valid ACTIVE
or
new valid ACTIVE
```

而不是半截 manifest。

同时建议 review 工具明确校验被 review 的 `--rules`：

```text
must correspond to current ACTIVE COMPILED version
```

或者要求显式：

```text
--from-version <expected-current-active>
```

避免操作者拿一个任意旧/外部 compiled yaml 生成新 REVIEWED 并直接切 ACTIVE，而没有显式 lineage transition。

---

# 8. P1-03：Raw Orphan Recovery 保留，但补全集合级 fault tests

当前 RawWriter recovery 主体通过。

下一批只补边角：

```text
[ ] multi-table partial orphan: existing t1 + missing t2 + same retry => complete + meta
[ ] multi-table orphan has unexpected extra table => quarantine / BLOCK
[ ] quarantine 后 list_orphan_payloads 不把 quarantined bytes 当 active orphan
[ ] recovery 后 verify_meta_closure == []
```

不要求重构 RawWriter 主模型。

---

# 9. Governance / 文档同步仍未闭环

## 9.1 Current Code Baseline 仍不是 exact SHA

`DEVELOPMENT_MANAGEMENT.md` 顶部仍写：

```text
Current Code Baseline: 本批提交
```

本轮已经存在明确提交，不能继续使用模糊描述。

建议区分：

```text
Current Implementation Baseline = 13d02a191f11c22b836da42ae9ae5707f9e355f1
Current Repository HEAD          = cdd360879c3a6361f4c952bde39174d3d46dfbcb
```

若后续整改代码产生新 SHA，则下一批完成时更新为那个 exact implementation SHA。

## 9.2 §30 / §31 仍互相矛盾

§30 仍保留：

```text
2026-08-22 R4-A1.1
current v2 candidate
R4-A1.1 Review=PENDING_REVIEW
```

而 §31 已更新到：

```text
2026-08-25
v1/v2/v3
bound router/gates complete
remaining human review
```

§30 作为“当前治理”章节不能继续保存旧 current-state copy。

历史应留给 DEVLOG / Git；管理总册只能保留当前真相。

## 9.3 §40 仍提前把 upstream 写成 PASS

当前 §40 已写：

```text
R4-A2.3  REOPENED -> absorbed  PASS（由 R4-A2.5 复审闭环）
CR-1.1   REOPENED -> absorbed  PASS（由 CR-1.2/1.2.1 闭环）
```

但本轮 Reviewer 实际裁决仍是 REOPENED。

不能在 Reviewer 验证前预写“由本批复审闭环”。

正确状态应表达：

```text
absorbed into R4-A2.6 / CR-1.2.2
not independently VERIFIED yet
```

直到后续 Reviewer 真正给出 VERIFIED。

## 9.4 DEVLOG 自相矛盾

同一最新条目已经写：

```text
GitHub Actions: CONFIRMED GREEN
```

但 Known Open Issues 仍写：

```text
CI 提交后待 Actions 确认
```

必须修正。

同时删除 / 更正：

```text
v3 数据无需重封
```

这种当前没有实际数据支撑的 CA type 声明。

---

# 10. 下一批实施顺序

## Batch A — Probe Exchange Enforcement

```text
1. B5 code-list 改走 ProbeExecutor
2. B6 code-list 改走 ProbeExecutor
3. inventory probes.py 所有 ctx.target.*_exchange 调用
4. 建立 approved execution-boundary static guard
5. success/failure exchange-count tests
```

## Batch B — Golden CA Typed Truth

```text
1. formal event type 从 actual Golden semantic truth 解析
2. event_class -> canonical type mapping
3. expected_fields.event_type 与 event_class 一致性 gate
4. unknown/untyped formal CA fail closed
5. actual golden v3 regression tests
```

## Batch C — Rule Manifest Confinement

```text
1. dataset_files[] confinement BEFORE fs access
2. versions/<rule_version>/ layout consistency
3. absolute / traversal / symlink tests
```

## Batch D — Rule Metadata Coherence

```text
1. 决定 manifest vs dataset governance SoR
2. enforce duplicated metadata equality OR remove duplication
3. separate selector rule_version vs dataset content version
4. SpikeRun provenance fields update
5. bound replay tests
```

## Batch E — P1 Hardening

```text
provenance_complete includes rules
review manifest atomic switch
review from-version lineage check
raw partial-orphan set tests
```

## Batch F — Governance Closure

```text
DEVLOG reviewer correction
DEVELOPMENT_MANAGEMENT exact SHA
§30/31 current-state unification
§40 no premature PASS
RISK-004 remains REOPENED until Reviewer verifies
CI = CONFIRMED GREEN
```

---

# 11. Required Acceptance Matrix

## Probe Exchange

```text
[ ] B5 code_list success persisted exactly once
[ ] B5 code_list failure persisted exactly once
[ ] B5 failure => structured case, no crash leakage
[ ] B6 code_list success persisted exactly once
[ ] B6 code_list failure persisted exactly once
[ ] B6 failure => structured case
[ ] formal real-call count == persisted exchange count
[ ] no formal provider call outside approved exchange execution boundary
```

## Golden CA

```text
[ ] every actual bound Golden CA case resolves a canonical event type
[ ] actual v3 DIVIDEND case cannot pass on RIGHT_ISSUE-only evidence
[ ] actual RIGHT_ISSUE case cannot pass on DIVIDEND-only evidence
[ ] missing/unknown formal event type fails closed
[ ] event_class / expected_fields.event_type conflict fails closed
[ ] type + date + symbol exact match remains required
```

## Rule Manifest

```text
[ ] dataset_files traversal blocked
[ ] absolute path blocked
[ ] symlink escape blocked
[ ] version-dir mismatch blocked
[ ] manifest/dataset review_status mismatch blocked
[ ] source_version mismatch blocked
[ ] review_provenance mismatch blocked or duplication removed by contract
[ ] selector version + dataset version independently bound on Run
[ ] ACTIVE advance cannot alter historical replay
```

## Raw / P1

```text
[ ] partial multi-table orphan same retry recovers
[ ] unexpected orphan member quarantines/blocks
[ ] quarantine excluded from active orphan scan
[ ] recovered exchange passes full evidence closure
```

## Governance

```text
[ ] Current Code Baseline exact SHA
[ ] §30/31 current truth consistent
[ ] §40 no premature absorbed PASS
[ ] RISK-004 remains REOPENED until this Reviewer gate passes
[ ] DEVLOG CI wording internally consistent
[ ] DEVLOG CA-type claims match actual Golden bytes
[ ] Local and CI status remain separately reported
```

---

# 12. Exit Gate

只有全部满足，Reviewer 才可将 R4-A2.x / CR-1.x 基础层判定 VERIFIED：

```text
[ ] zero unpersisted real provider exchanges on formal B2-B7 path
[ ] success AND failure exchanges all close into immutable evidence
[ ] no direct formal provider-call bypass outside approved executor/collector boundary
[ ] every formal Golden CA case has exact typed event truth
[ ] wrong corporate-action type cannot PASS any actual bound Golden case
[ ] ACTIVE rule manifest file refs are path-confined
[ ] Rule manifest and dataset governance metadata are coherent
[ ] Run binds unambiguous selector version + dataset identity
[ ] formal provenance API includes all semantic SoR bindings
[ ] Raw orphan recovery remains closure-safe
[ ] no silent fallback
[ ] no current/ACTIVE dependency leaks into historical formal semantics
[ ] management docs match runtime
[ ] required regression/adversarial tests pass
[ ] GitHub Actions remains positively GREEN
```

---

# 13. 本批禁止事项

R4-A2.6 / CR-1.2.2 VERIFIED 前：

```text
[ ] 不启动 CR-2 Provider-Normalized + Quarantine 主体
[ ] 不启动 CR-3 / CR-4
[ ] 不扩大 Feature / State 开发
[ ] 不执行正式 P0-M-1B
[ ] 不把人工 Golden/Rule Review 当作修复代码 P0 的替代品
[ ] 不以 synthetic typed CA test 代替 actual Golden truth 检查
```

允许并行：

```text
Golden candidate/source artifact 准备
Trading Rule 官方 source artifact 准备
正式账号外部准备
R4-A3/B1/B2 的设计分析（不得越过当前 Gate 形成正式 dependent implementation）
```

---

# 14. Change Control 建议

建议登记：

```text
DM-CR-20260825-004 — Formal Probe Exchange Enforcement
DM-CR-20260825-005 — Golden CA Event-Type Truth Closure
DM-CR-20260825-006 — Rule Manifest Confinement & Metadata Coherence
DM-CR-20260825-007 — R4-A2.5 Review Correction & Governance Sync
```

分类建议：

- 004：C1 correctness closure；
- 005：若仅把现有 `event_class` 映射为 canonical type，属于 C1/C2 implementation-semantic closure；若创建新的 Golden version，则按现有 Golden governance 执行，不修改旧 v3；
- 006：ADR-013 amendment，建议 C2；如果改变 Rule Version model 的核心 SoR 语义，再新增 ADR-014；
- 007：C1 governance correction。

所有重要改动 Notes / Change Record 继续必须回答：

```text
为什么改
怎么改
考虑过哪些方案、为什么没选
代价与收益
```

---

# 15. Reviewer 下一轮复检重点

下一次仓库更新后优先检查：

```text
1. B5/B6 是否还有 direct target exchange bypass
2. failure exchange 是否真实写入 RawWriter
3. formal provider call count 是否与 raw meta count 闭合
4. actual golden_cases_v3 CA event type 是否真正参与 validator
5. untyped formal CA 是否已经 fail closed
6. rule_manifest dataset_files 是否 path-confined
7. symlink/traversal 是否可逃出 rules root
8. manifest.review_status/source_version/provenance 是否与 dataset 一致
9. Run 是否区分 selector version 和 dataset content version
10. provenance_complete 是否包含 rule binding
11. review ACTIVE flip 是否 crash-safe
12. §30/31/40、DEVLOG、RISK-004 是否与当前裁决一致
13. latest GitHub Actions 是否持续 success
```

---

# 16. 当前正式状态

```text
Reviewed Repository HEAD:
    cdd360879c3a6361f4c952bde39174d3d46dfbcb

R4-A2.5:
    Implementation = DONE
    Review         = REOPENED

CR-1.2.1:
    Implementation = DONE
    Review         = REOPENED

CI:
    VERIFIED GREEN

Next:
    R4-A2.6 Formal Truth / Manifest Closure
    CR-1.2.2 Probe Exchange Enforcement

CR-2:
    BLOCKED

Golden Human Review:
    OPEN / HUMAN ACTION REQUIRED

Trading Rule Human Review:
    OPEN / HUMAN ACTION REQUIRED

Production P0-M-1B:
    BLOCKED
```

Reviewer 结论：**本轮非常接近基础层收口，但尚未达到 VERIFIED。下一批必须保持“小范围 correctness closure”，禁止借机扩展 CR-2。**
