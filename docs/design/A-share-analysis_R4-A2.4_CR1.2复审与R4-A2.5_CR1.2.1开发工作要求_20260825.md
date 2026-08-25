# A-share-analysis：R4-A2.4 / CR-1.2 复审结论与 R4-A2.5 / CR-1.2.1 开发工作要求

> **Review Date**：2026-08-25 09:10 +08:00  
> **Reviewed Code HEAD**：`c7aa5112c9719c9aec30a39e4cee85c2f4a13708`  
> **Previous Reviewer Requirement Commit**：`bb5ad633a34711bd9e053c7dc6deff8dee7a93d8`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2.4 Correctness Deepening、CR-1.2 Raw Exchange Closure、ADR-012、Trading Rule Review Workflow、CA Event SoR、DEVLOG / Development Management  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.5 Formal Replay / Rule-SoR Closure + CR-1.2.1 Raw Commit Hardening**  
> **CR-2**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**  

---

# 0. 裁决摘要

本轮相对 `d021936` 的实现质量有明显提升，多数上一轮 P0 已经真正进入运行时，而不是只存在于测试或文档：

```text
hidden calendar prerequisite
→ 已显式化并持久化

single-table raw evidence
→ 已从裸 parquet 锚定升级为 meta-anchored exchange evidence

request lineage
→ 已保存完整 request_params + hash + ingest_run_id

Trading Rule
→ 已增加 run binding + review gate 框架

Corporate Action
→ 已加入独立 dividend event exchange
```

因此本轮不要求回退 CR-1.2 / R4-A2.4 的主体设计。

但复核发现，当前还没有达到 Formal Exact Replay 的不变量：

```text
Every formal semantic consumer must use the run-bound semantic SoR.

Every versioned semantic SoR must have an unambiguous ACTIVE selector
and immutable historical binding.

Every human-reviewed artifact reference must be path-confined and
provenance-validated.
```

当前至少存在 4 项 P0 / blocking correctness 问题，另有 Raw commit recovery、文档与 CI 闭包问题，故不能 VERIFIED。

---

# 1. 本轮已通过、允许保留的实现

以下内容原则上通过，不要求回退。

## 1.1 CR-1.2：Kline prerequisite 显式化

当前正式 Spike path 已实现：

```text
get_calendar_exchange()
→ ProbeExecutor
→ RawWriter
→ trading_days
→ query_kline_exchange(..., trading_days=...)
→ RawWriter
```

`provider.query_kline_exchange()` 在显式提供 `trading_days` 时不再内部发起隐藏 calendar SDK 调用。

B3 / B5 / B6 / B7 的 kline 路径也已经开始统一采用这一模式。

保留该设计。

## 1.2 CR-1.2：Raw Evidence 改为 meta-anchor

当前 `RawWriteResult` 已显式拆分：

```text
payload_artifacts[]
meta_artifact
```

且成功 exchange 的 `evidence_uri/evidence_hash` 指向 `.meta.json`。

`verify_evidence_closure()` 能继续从 meta 复验 payload table hash；Golden bundle 也递归复验 meta → payload。

这是正确方向，保留。

## 1.3 完整 request params / traceability

当前 RawEnvelope / Raw meta 已开始保存：

```text
full request_params
request_params_hash
ingested_at
ingest_run_id
```

Provider wrapper 也已把完整 `code_list` 写入 request params，而不是只写 count / first-N 摘要。

保留。

## 1.4 Trading Rule 基础 binding / review gate

当前已存在：

```text
SpikeRun.trading_rule_file
SpikeRun.trading_rule_version
SpikeRun.trading_rule_hash
SpikeRun.trading_rule_review_status
```

以及：

```text
load_bound_rule_book()
trading_rule_review_gate()
new_run(PRODUCTION) review gate
compute_verdict(PRODUCTION) review recheck
resume_run() bound hash/version check
```

`compute_config_hash()` 也已递归覆盖 `configs/**`。

这些基础能力保留。

## 1.5 CA Event SoR 基础

Golden CA domain 已增加：

```text
calendar
status
dividend event
adj factor
kline
```

并明确：

```text
adj-only => EVENT_SOURCE_MISSING
wrong EX_DATE => EVENT_DATE_MISMATCH
```

保留该架构。

---

# 2. P0-01：Formal limit semantic consumers 仍会读取 current/default Trading Rule

## 2.1 问题

虽然 `ProbeContext.rule_book` 已经能够加载 run-bound Trading Rule，Golden Router 的 limit / BJ validator 也显式接收该 book，但 **并非所有正式语义消费者都使用它**。

当前：

```python
validators.validate_limit_rule(rows)
```

内部仍直接：

```python
resolve_limit_regime(...)
```

没有传 `book=`。

因此 `resolve_limit_regime()` 会回退：

```text
default_rule_book()
→ current working tree configs/trading_rules
```

至少以下正式 probe 仍受影响：

```text
B3 historical_st_suspend / limit_price_and_no_limit_days
B5 BSE limit_price_and_no_limit_days
```

这意味着：

```text
Run bound rule vN
→ B3/B5 cases produced
→ current rule file later advances to vN+1
→ replay/re-execution of semantic validation
→ B3/B5 may use vN+1
```

因此“SpikeRun 已绑定 Trading Rule”目前只对 Golden Router 完整成立，**还不是系统级 Exact Replay**。

## 2.2 风险

这可以造成：

```text
historical case result drift
false PASS / false FAIL
same raw evidence + same run identity => different semantic result
```

属于 P0。

## 2.3 强制修复

推荐：

```python
validate_limit_rule(
    rows,
    *,
    require_any_limit=True,
    book: TradingRuleBook,
)
```

正式运行时禁止 `book=None`。

至少：

```text
B3 -> validate_limit_rule(..., book=ctx.rule_book)
B5 -> validate_limit_rule(..., book=ctx.rule_book)
Golden -> already bound
```

如需要保留单元测试 / standalone convenience，可提供显式：

```text
validate_limit_rule_unbound_for_test(...)
```

或测试显式传 `TradingRuleBook.load()`。

不要让 Formal path 通过默认参数静默读取 current rules。

## 2.4 Required Tests

```text
[ ] B3 formal limit validation receives run-bound book
[ ] B5 BSE validation receives run-bound book
[ ] bound vN + current vN+1 => B3 result unchanged
[ ] bound vN + current vN+1 => B5 result unchanged
[ ] bound rule tampered => semantic execution/resume/verdict BLOCK
[ ] static/AST guard: formal runtime cannot call resolve_*rule without explicit book
[ ] no current/default rule read on formal semantic path
```

---

# 3. P0-02：Trading Rule version selection / review workflow 没有真正形成可运行的 append-only SoR

## 3.1 当前 loader 语义

`TradingRuleBook.load(directory)` 当前会加载目录中的：

```text
*.yaml
*.yml
```

并合并所有文件。

它还要求这些文件的：

```text
version
source_version
review_status
```

一致。

## 3.2 当前 review.py 语义

`review.py` 明确：

```text
COMPILED source file 保留
REVIEWED 生成一个新的 output yaml
```

文档示例：

```text
configs/trading_rules/a_share_limit_v1.yaml
configs/trading_rules/a_share_limit_v1_reviewed.yaml
```

## 3.3 二者冲突

如果按当前推荐流程执行人工 review，则默认目录同时出现：

```text
COMPILED file
REVIEWED file
```

之后：

```text
TradingRuleBook.load(configs/trading_rules)
```

会把二者同时加载。

结果可能出现：

```text
review_status conflict
version metadata conflict
duplicate rule_id
```

即：**当前 review workflow 本身会破坏 default loader 的可用性。**

现有测试没有覆盖这个真实生命周期：测试目录通常只放 REVIEWED 文件，或者直接 `TradingRuleBook.load(out_file)`，没有测试 COMPILED + REVIEWED 历史版本共存。

## 3.4 另外一个 binding 缺陷

`TradingRuleBook` 已经支持：

```text
dataset_files = tuple(...)
combined content_hash
```

但 `new_run()` 当前只绑定：

```python
rule_name = rule_book.dataset_files[0]
trading_rule_file = rule_name
trading_rule_hash = sha256(first file)
```

也就是说：

```text
loader 可以表示 multi-file rule dataset
run binding 却只绑定第一个 file
```

两种数据模型不一致。

如果未来 rules 拆成：

```text
main.yaml
chinext.yaml
star.yaml
bse.yaml
```

run 只 seal 第一个文件，Exact Replay 会失效。

## 3.5 强制设计

Trading Rule SoR 应采用明确的“版本 + ACTIVE selector + immutable binding”。

推荐方案（与 Golden 模型一致）：

```text
configs/trading_rules/
    rule_manifest.json          # ACTIVE pointer / selector
    versions/
        v20260824-compiled/
            rules.yaml
            manifest.json
        v20260825-reviewed/
            rules.yaml
            manifest.json
    evidence/
        sha256/...
```

ACTIVE manifest 至少包含：

```text
rule_version
review_status
dataset_files[]
dataset_hash
source_version
review_provenance
```

Run binding 至少：

```text
trading_rule_version
trading_rule_dataset_files[]
trading_rule_dataset_hash
trading_rule_manifest_hash
```

规则：

```text
NEW run
    → resolve ACTIVE selector
    → gate
    → bind immutable version

RUNNING / RESUME / VERDICT / REPLAY
    → only load bound version
    → never read ACTIVE/current selector
```

如团队决定 P0 只允许“单文件 rule dataset”，也可以，但必须：

```text
manifest 显式选择 active_file
loader 只加载 active_file
run bind exact selected file
history files 可以共存但不能自动 merge
```

**禁止继续使用“目录里第一个 YAML 就是 run binding”作为隐式规则。**

## 3.6 Required Tests

```text
[ ] COMPILED + REVIEWED versions can coexist without loader conflict
[ ] ACTIVE points reviewed => new run selects reviewed only
[ ] old compiled version remains immutable/readable
[ ] ACTIVE advances vN -> vN+1; historical vN run unchanged
[ ] multi-file dataset: changing any component breaks bound dataset hash
[ ] run binding covers ALL dataset_files, not first file only
[ ] ACTIVE manifest tamper blocks new run
[ ] bound manifest/file tamper blocks resume/verdict
```

---

# 4. P0-03：Trading Rule Review Gate 的 evidence path/provenance 仍可绕过

## 4.1 当前 gate

当前 `trading_rule_review_gate()` 已检查：

```text
review_status == REVIEWED
required provenance fields non-empty
artifact kind allowlist
source artifact exists
artifact bytes hash matches
```

这是进步。

但与 Golden Review Gate 相比，仍缺几个关键不可绕过约束。

## 4.2 Path confinement 缺失

当前 artifact resolve 主要是：

```python
candidate = root / source_artifact_ref
candidate.is_file()
```

没有执行：

```text
resolve()
relative_to(allowed_evidence_root)
```

因此手工构造 REVIEWED YAML 时理论上可以：

```text
source_artifact_ref: ../../some-existing-file
```

只要 hash 对得上，就可能通过 gate。

Formal Review Evidence 不应允许逃出受控 evidence store。

## 4.3 Provenance field validation 不完整

目前主要检查 non-empty，但还应验证：

```text
source_artifact_hash = exactly 64 lower-hex
reviewed_at = valid ISO timestamp
source_retrieved_at = valid ISO timestamp
source_artifact_ref = relative path only
absolute path = forbidden
.. traversal = forbidden
```

## 4.4 强制修复

建立明确 evidence root，例如：

```text
configs/trading_rules/evidence/
```

或统一外部 evidence store。

Gate 必须：

```text
allowed_root = evidence_root.resolve()
artifact = (allowed_root / ref).resolve()
artifact.relative_to(allowed_root)  # must succeed
```

并完整 schema-validate review provenance。

review.py 也必须生成满足相同约束的 ref。

## 4.5 Required Tests

```text
[ ] ../ traversal rejected
[ ] absolute artifact path rejected
[ ] artifact outside allowed root rejected
[ ] malformed/non-64-hex hash rejected
[ ] invalid reviewed_at rejected
[ ] invalid source_retrieved_at rejected
[ ] missing artifact rejected
[ ] tampered artifact rejected
[ ] valid content-addressed artifact passes
```

---

# 5. P0-04：Corporate Action 仍没有验证 event TYPE；Right Issue 语义未闭环

## 5.1 上一轮要求

上一轮 Required Test Matrix 明确要求：

```text
wrong event date/type FAIL
```

当前已经实现：

```text
wrong event date => FAIL
```

但 event type 尚未成为 validator contract。

## 5.2 当前问题

CA validator 目前主要：

```text
filter SECURITY_CODE
check EX_DATE == T
```

并没有比较：

```text
event_type
```

Golden test helper 也只给：

```text
IS_WD_SEC = True
```

没有 expected CA event type。

与此同时 capability registry 明确声明：

```text
corporate_action:
    InfoData.get_dividend
    InfoData.get_right_issue
```

而当前 RealTarget / Router 实际只接入：

```text
get_dividend_exchange
```

所以同一天发生其它事件时可能：

```text
wrong type but same EX_DATE
→ still considered event source satisfied
```

并且 Right Issue Golden 无法由当前 event endpoint 完整证明。

## 5.3 强制修复

定义最小 CA event taxonomy，例如：

```text
DIVIDEND
RIGHT_ISSUE
SPLIT / SHARE_CHANGE（如 Provider contract 确认需要）
```

Golden CA case 至少增加 / 使用：

```text
expected_event_type
```

Provider-normalized 前的 Spike validator 也可先做 provider-specific mapping：

```text
provider event record
→ normalized event type
```

验证 key 至少：

```text
provider_symbol
EX_DATE
event_type
```

如 approved provider manual 中 right issue 是独立 endpoint：

```text
get_right_issue_exchange()
```

应加入 Target / Router，并让对应 Golden case 的 bundle 绑定实际 endpoint。

Dividend 不能替代 Right Issue 证明。

## 5.4 Required Tests

```text
[ ] correct date + correct type PASS
[ ] correct date + wrong type FAIL
[ ] wrong date + correct type FAIL
[ ] right-issue case requires right-issue evidence
[ ] dividend event cannot satisfy right-issue golden
[ ] event bundle references exact endpoint used by validator
```

---

# 6. P0-05：B5/B6 scalar-list symbol extraction 仍有语义错误风险

## 6.1 当前问题

B3/B7 已新增 `_flat_values()` 来处理：

```text
list[str]
```

这是正确的。

但 B5 / B6 仍存在：

```python
[str(s) for s in _rows_of(symbols_exchange.payload)]
```

对于：

```python
["600519.SH", "000001.SZ"]
```

`_rows_of()` 会得到：

```python
[{"value": "600519.SH"}, {"value": "000001.SZ"}]
```

随后 `str(s)` 变成：

```text
"{'value': '600519.SH'}"
```

而不是实际 symbol。

受影响至少：

```text
B5 symbol_mapping_unambiguous
B6 free-float sample symbols
```

这可能造成 core symbol-mapping validator 输入错误，属于正式 correctness 问题。

## 6.2 强制修复

所有 scalar-list provider payload 必须统一：

```text
_flat_values()
```

或更好地在 Provider/Target boundary 定义明确 code-list payload contract。

不得在不同 probe 各自猜 shape。

## 6.3 Required Tests

```text
[ ] B5 validate_symbol_mapping receives exact ["600519.SH", ...]
[ ] B6 get_stock_basic_exchange receives exact symbols, not stringified dicts
[ ] scalar list / one-column frame shapes normalize consistently
[ ] malformed code-list shape fail loud, no silent coercion
```

---

# 7. P1：Raw multi-file commit 当前是“meta-last closure-safe”，不是 crash-atomic / recoverable

## 7.1 已有改进

当前 `_commit_files()`：

```text
stage all payload bytes
→ os.replace final payload 1
→ os.replace final payload 2
→ ...
→ write meta LAST
```

这个设计能保证：

```text
partial payload set without meta
不会被误认为完整 evidence
```

这是正确的 closure safety。

## 7.2 仍有问题

如果进程在：

```text
payload 1 已移动到 final
payload 2 尚未移动
meta 尚未写
```

时 crash，重试时：

```text
existing_any = True
meta missing
=> conflict
```

当前没有：

```text
orphan recovery
quarantine
resume transaction
```

所以这还不能称为真正的 multi-file atomic commit。

当前测试所谓“failed mid-way”实际是在 normalize 阶段就失败，没有做 `os.replace` 后故障注入。

## 7.3 要求

本项可作为 CR-1.2.1 P1 hardening，不阻塞本轮核心 Rule SoR P0 修复，但必须在 CR-2 消费 Raw 前关闭。

二选一：

### 方案 A — 明确改名 + recovery protocol

契约改为：

```text
meta-last closure-safe commit
```

并实现：

```text
orphan payload detection
same-request deterministic retry cleanup/resume
quarantine if bytes conflict
```

### 方案 B — directory-level transaction

如文件系统与布局允许：

```text
transaction dir
→ complete set + meta
→ atomic directory rename/publish
```

## 7.4 Tests

```text
[ ] inject failure after first final payload promotion
[ ] retry same request recovers deterministically
[ ] no false idempotence on partial transaction
[ ] conflicting orphan bytes => quarantine/BLOCK
[ ] meta never points to incomplete payload set
```

---

# 8. Governance / Documentation 仍未闭环

上一轮要求明确把 docs consistency 作为 Exit Gate，但当前仍有不一致。

## 8.1 Current Code Baseline 仍不是 exact SHA

管理总册顶部仍写：

```text
Current Code Baseline: 本批提交 (...)
```

必须改为：

```text
c7aa5112...   # reviewer 当前复核基线
```

下一批完成后再更新为实际 correction HEAD。

## 8.2 §30 / §31 仍是旧状态

当前 §30/31 仍写：

```text
2026-08-22 R4-A1.1 后
v2 COMPILED Candidate
R4-A1.1 Review=PENDING_REVIEW
domain router 待修
BJ Mapping -> BJ mapping endpoint
```

而 §40/41 已写 R4-A2.3 / CR-1.1 absorbed。

管理总册内部存在明显“旧当前真相”与“新当前真相”冲突。

必须改写 §30/31 为当前状态，而不是保留历史口径。历史应留 Git/DEVLOG。

## 8.3 §40 提前把未复核批次写成 absorbed PASS

当前 §40 将：

```text
R4-A2.3 => absorbed / PASS by A2.4
CR-1.1 => absorbed / PASS by CR-1.2
```

但本次 Reviewer 对 A2.4 / CR-1.2 仍裁决 REOPENED。

因此不能用“由下一批闭环”来提前等价 VERIFIED。

## 8.4 RISK-004 提前 CLOSED

上一轮工作要求明确：

```text
RISK-004 REOPENED until this review closes
```

当前总册却已写：

```text
RISK-004 Status: CLOSED
```

应改：

```text
OPEN / REOPENED
```

直到 Reviewer 对 CR-1.2 / rule-consumer closure 正式 VERIFIED。

## 8.5 CR-2 不得提前 READY

当前 §41 有：

```text
后续 CR（CR-1.2 已就绪）
```

本次裁决为 REOPENED，因此：

```text
CR-2 = BLOCKED
```

直到本文件 Exit Gate 通过。

---

# 9. CI：仍没有 Positive Confirmation

上一轮 Exit Gate 明确：

```text
CI status is positively confirmed, not merely “triggered”
```

本次 Reviewer 查询 `c7aa5112...` 时：

```text
associated workflow runs: none visible
combined statuses: none visible
```

这不等价于 CI FAIL，但也不能作为 CI PASS。

因此当前状态必须写：

```text
Local: developer reports 461 passed / ruff / mypy clean
CI: NOT POSITIVELY CONFIRMED
```

在 Review VERIFIED 前至少要能看到并确认要求的 GitHub Actions checks 成功，或明确修复 CI trigger/config 使其产生可验证结果。

---

# 10. 下一批正式范围

## R4-A2.5 — Formal Replay / Rule-SoR Closure

目标：

```text
Every formal semantic result
= function(
    run-bound raw evidence,
    run-bound Golden Truth,
    run-bound Trading Rules,
    run-bound code/env/config
  )
```

禁止任何正式语义 validator 隐式读取：

```text
current/default rules
latest/ACTIVE after run binding
unversioned external artifact
```

## CR-1.2.1 — Raw Commit Hardening

目标：

```text
Raw exchange closure
+ crash/retry semantics
```

不扩大 CR-2 主体。

---

# 11. 推荐实施顺序

## Batch A — All-consumer Rule Binding

```text
1. inventory every resolve_trading_rule / resolve_limit_regime consumer
2. formal validators require explicit TradingRuleBook
3. B3/B5 pass ctx.rule_book
4. static guard current/default rule usage
5. adversarial vN/vN+1 replay tests
```

## Batch B — Trading Rule Version/ACTIVE Model

```text
1. define immutable rule version layout
2. define explicit ACTIVE manifest / selector
3. bind all dataset_files + combined hash
4. review creates NEW immutable reviewed version
5. ACTIVE advance independent from historical runs
```

## Batch C — Rule Review Evidence Hardening

```text
1. evidence root + path confinement
2. hash format validation
3. timestamp validation
4. content-addressed artifact recommended
5. traversal/absolute-path adversarial tests
```

## Batch D — CA Event-Type Closure + Code List Shape Fix

```text
1. normalized CA event type
2. expected event type in Golden case
3. dividend vs right issue exact proof
4. B5/B6 scalar list normalization
```

## Batch E — Raw Commit Recovery

```text
1. fault injection after partial final promotion
2. define cleanup/resume/quarantine
3. document real atomicity semantics
```

## Batch F — Governance / CI Closure

```text
DEVLOG correction
DEVELOPMENT_MANAGEMENT current-state cleanup
RISK-004 REOPENED
exact SHA baseline
CR-2 BLOCKED
CI positive confirmation
```

---

# 12. Required Test Matrix

## Rule binding / replay

```text
[ ] B3 uses bound rule book
[ ] B5 uses bound rule book
[ ] no formal resolve_*rule without explicit book
[ ] current rule advance does not change bound B3 result
[ ] current rule advance does not change bound B5 result
[ ] bound rule tamper blocks
```

## Rule dataset lifecycle

```text
[ ] COMPILED and REVIEWED versions coexist
[ ] explicit ACTIVE selector chooses one version
[ ] new run binds selected immutable version
[ ] historical run unaffected by ACTIVE advance
[ ] all dataset files participate in bound hash
[ ] multi-file tamper of any component blocks
```

## Rule review provenance

```text
[ ] ../ traversal rejected
[ ] absolute path rejected
[ ] malformed hash rejected
[ ] invalid timestamp rejected
[ ] missing artifact rejected
[ ] tampered artifact rejected
[ ] valid reviewed artifact passes
```

## CA

```text
[ ] date+type exact match PASS
[ ] wrong event type FAIL
[ ] wrong event date FAIL
[ ] right issue uses right issue evidence
[ ] dividend cannot substitute right issue
```

## Symbol payload shape

```text
[ ] B5 gets real symbols
[ ] B6 gets real symbols
[ ] scalar-list normalization single source
```

## Raw recovery

```text
[ ] fault after first payload finalization
[ ] retry recovers/quarantines deterministically
[ ] meta cannot anchor partial payload set
```

## Governance / CI

```text
[ ] Current Code Baseline exact SHA
[ ] §30/31/40/41 consistent
[ ] RISK-004 REOPENED until Reviewer closes
[ ] DEVLOG correction appended, history preserved
[ ] CR-2 remains BLOCKED
[ ] CI checks positively confirmed
```

---

# 13. Exit Gate

R4-A2.5 / CR-1.2.1 只有以下全部满足，Reviewer 才可以把 Formal Replay / CR-1.2 closure 判 VERIFIED：

```text
[ ] all formal Trading Rule consumers use run-bound book
[ ] no formal semantic validator falls back to current/default rule SoR
[ ] Trading Rule has explicit immutable version + ACTIVE selector model
[ ] run binding covers complete rule dataset, not first file only
[ ] COMPILED / REVIEWED historical versions can coexist
[ ] rule review evidence is path-confined + hash/timestamp schema validated
[ ] CA validator verifies event date AND event type
[ ] Right Issue cannot be proven by Dividend evidence
[ ] B5/B6 code-list scalar payloads are interpreted correctly
[ ] Raw partial-commit crash semantics are documented and tested
[ ] no silent fallback
[ ] Development Management / DEVLOG match runtime and reviewer verdict
[ ] RISK-004 remains open until verified
[ ] CR-2 remains blocked until this gate closes
[ ] pytest / ruff / format / mypy / dry-run pass
[ ] GitHub Actions status is positively confirmed
```

---

# 14. 本批禁止事项

在本文件 Exit Gate 关闭前：

```text
[ ] 不启动 CR-2 Provider-Normalized / Quarantine 主体开发
[ ] 不启动 CR-3 / CR-4
[ ] 不扩大 Feature / State
[ ] 不执行正式 P0-M-1B
[ ] 不将 trial/dry-run 作为 formal provider truth
[ ] 不把 Local tests 代替 CI / runtime contract review
```

允许并行：

```text
Golden candidate/source artifact 准备
Trading Rule 官方 evidence 人工整理
formal provider account 准备
Trial L1 connectivity
```

---

# 15. Change Control 建议

建议新增：

```text
DM-CR-20260825-012 — Trading Rule All-Consumer Binding + Dataset Selector
DM-CR-20260825-013 — Trading Rule Review Evidence Hardening
DM-CR-20260825-014 — Corporate Action Event-Type / Right-Issue Closure
DM-CR-20260825-015 — CR-1.2.1 Raw Commit Recovery + Governance Correction
```

建议分类：

```text
012: C2 amendment to ADR-011/ADR-012
013: C1/C2（取决于 evidence store 是否改变 SoR layout）
014: C1；若改变 Frozen CA source contract 则升级 C3
015: C1；若改变 Raw publish/commit model 则 C2 amendment to ADR-012
```

同一逻辑 batch 必须：

```text
Code
Tests
DEVLOG
DEVELOPMENT_MANAGEMENT
ADR amendment（如 C2）
Implementation Mapping
```

每项重要改动继续保留 Notes 四要素：

```text
为什么改
怎么改
考虑过哪些方案、为什么没选
代价与收益
```

---

# 16. Reviewer 下次复检重点

下一次仓库更新后按以下顺序复检：

```text
1. validators.validate_limit_rule 是否强制接受 bound book
2. B3/B5 是否显式传 ctx.rule_book
3. grep resolve_limit_regime / resolve_trading_rule 的无 book Formal 调用
4. Trading Rule ACTIVE selector / immutable version layout
5. new_run 是否还取 dataset_files[0]
6. review.py 产生的新版本能否与历史 COMPILED 共存
7. trading_rule_review_gate path confinement / timestamp / hash schema
8. CA wrong-type / right-issue test
9. B5/B6 code-list payload normalization
10. partial os.replace crash recovery test
11. §30/31/40/41/52/53/61/62 与 runtime 是否一致
12. exact Current Code Baseline SHA
13. GitHub Actions run/check 是否真实可见且成功
```

---

# 17. 当前正式状态

```text
Reviewed Code HEAD:
    c7aa5112c9719c9aec30a39e4cee85c2f4a13708

R4-A2.4:
    Implementation = DONE
    Review = REOPENED

CR-1.2:
    Implementation = DONE
    Review = REOPENED

Next:
    R4-A2.5 Formal Replay / Rule-SoR Closure
    CR-1.2.1 Raw Commit Hardening

CR-2:
    BLOCKED

Golden Human Review:
    BLOCKED / pending human work

Trading Rule Human Review:
    BLOCKED / workflow itself must first become version-selector-safe

Production P0-M-1B:
    BLOCKED

CI:
    NOT POSITIVELY CONFIRMED for c7aa5112...
```

本文件是下一开发批次的直接任务输入。开发完成后，请在本文件末尾追加 Implementation Mapping，并同步 DEVLOG / DEVELOPMENT_MANAGEMENT，再提交 Reviewer 复检。
