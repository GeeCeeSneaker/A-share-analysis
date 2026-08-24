# A-share-analysis：R4-A2.3 / CR-1.1 复审结论与 R4-A2.4 / CR-1.2 开发工作要求

> **Review Date**：2026-08-24 19:22 +08:00  
> **Reviewed HEAD**：`d021936efb5a79615eb07f61f9d029f6710800f5`  
> **Previous Reviewer Baseline**：`b7a845633d32b9a905345c5eaa4e447b2be2d786`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2.3 Correctness Closure、CR-1.1 Runtime Closure、ADR-010、ADR-011、DEVLOG、Development Management  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.4 Evidence / Rule Provenance Closure + CR-1.2 Exchange Completeness**  
> **CR-2**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**  

---

# 0. 本轮裁决摘要

本轮不是推倒重做。相对上一轮 `2f4a7ae`，当前 `d021936` 已把多数结构性缺口实质修正：

- Provider / Target 增加显式 `*_exchange` API；
- `ProviderError.exchange` 使失败 exchange 成为一等对象；
- probes/router/runner 已删除 `last_envelopes` 反查正确性路径；
- `RawWriter.write(exchange)` 成为显式写入入口；
- DataFrame / dict-of-DataFrames / Arrow / dict-of-rows 等载荷已建立明确序列化模型；
- Golden Router 已建立 evidence bundle，并从持久化 exchange 的 payload 构造 DomainData；
- Bound Golden formal gates 已显式接受 bound cases/manifest；
- limit status 已按 `(SECURITY_CODE, TRADE_DATE)` 精确匹配；
- first-N 已改为 PIT trading-session index；
- Trading Rule 制度事实已从 `trading_rule.py` 主体迁到版本化 YAML；
- CA 已真正使用交易日历与 T-1/T/T+1 Kline 做连续性验证；
- ADR-010 / ADR-011 已对两项 C2 变化给出正式决策记录。

因此本轮的主要问题已经从“模块存在但未接入”收敛为：

```text
Every real exchange must be persisted
Every persisted exchange must close payload + envelope + exact request lineage
Every semantic SoR must be run-bound / reviewed / hash-sealed
Every formal verdict must be reproducible from those bindings alone
```

当前仍有以下 P0，故 **R4-A2.3 / CR-1.1 不能 VERIFIED**。

---

# 1. 已通过、允许保留的实现

以下部分原则上保留，不要求回退：

## 1.1 Explicit Exchange 基础接口

保留：

```text
ProviderExchange
ProviderError.exchange
Target *_exchange API
ProbeExecutor 对非 ProviderExchange fail-loud
last_envelopes diagnostic-only
```

当前 `last_envelopes` 不再被 probes / golden_router / runner 反查，这一点通过。

## 1.2 RawWriter 载荷形状模型

保留：

```text
list[dict]
scalar list
DataFrame
pyarrow.Table
dict[str, list[dict]]
dict[str, DataFrame]
```

以及 dict-of-tables 方案 A：每个 logical table 独立 Parquet、meta 列出每表 hash/schema/row_count。

不允许回退到：

```text
first dict value
repr(payload)
string fallback
```

## 1.3 Bound Golden Gates

当前：

```text
quantity_gate(cases, manifest)
event_coverage_gate(cases, manifest)
review_gate(cases, manifest)
production_formal_gate(cases, manifest)
```

以及 verdict 对 run-bound Golden 的使用方向正确，保留 ACTIVE advance/tamper 对抗测试。

## 1.4 PIT Rule Resolver 基础

保留：

- versioned rule dataset；
- fail-closed `RuleUnresolvedError`；
- trading-session first-N；
- Decimal `ROUND_HALF_UP`；
- exact trade-date status selection；
- listing_date 缺失即 fail closed。

## 1.5 Golden Router Bundle 基础

`collector.persist(exchange) → DomainData from exact payload → validator → bundle` 的主结构通过。

后续是扩大“完整 exchange 集”和“meta/request lineage closure”，不是回到旧的 pseudo-evidence 设计。

---

# 2. P0-01：仍存在真实 SDK Exchange 被创建但未进入 RawWriter

## 2.1 Hidden calendar exchange 仍被丢弃

当前 `AmazingDataProvider.query_kline_exchange()` 内部调用 `_market()`；`_market()` 再调用：

```python
calendar = self.get_calendar()
```

`get_calendar()` 会创建一个真实 `ProviderExchange`，但 `_market()` 只取 payload，calendar exchange 本身不会返回给 Spike，也不会进入 RawWriter。

因此真实路径仍可能是：

```text
SDK get_calendar
→ ProviderExchange created
→ exchange discarded
→ only diagnostic last_envelopes remains

SDK query_kline
→ ProviderExchange returned
→ RawWriter persists only kline
```

这违反 CR-1/CR-1.1 的核心不变量：

```text
Every real SDK exchange must become immutable raw evidence.
```

### 当前测试不足

现有 `test_hidden_calendar_call_has_own_exchange` 仅证明：

```text
calendar SDK call happened
calendar envelope exists in provider.last_envelopes
```

它没有证明：

```text
calendar exchange → RawWriter
kline exchange    → RawWriter
=> two immutable raw artifacts
```

Implementation Mapping 中引用的 `test_hidden_calendar_and_kline_persist_separate_raw_artifacts` 与实际测试文件不一致，必须修正。

## 2.2 Probe 仍有 payload-only provider calls

至少以下路径仍绕开 RawWriter：

```text
probe_b3_core_facts:
    ctx.target.get_code_list(...)

probe_b7_capacity:
    ctx.target.get_code_list(...)
    ctx.target.get_calendar()
```

这些在 RealTarget 上都会触发真实 provider exchange，但 exchange 被 payload convenience wrapper 丢弃。

## 2.3 强制修复

正式 Spike/audit runtime 必须满足：

```text
No real provider call may be made through payload-only target methods.
```

推荐方案：

### 方案 A（优先）— Audit path 显式展开 prerequisites

把 Kline 的 calendar prerequisite 在 Spike/Target audit path 显式化：

```text
calendar_exchange = get_calendar_exchange()
→ persist
→ trading_days

kline_exchange = query_kline_exchange_with_calendar(..., trading_days)
→ persist
```

正式 audit path 中 `query_kline_exchange` 不得再内部发起不可见 calendar exchange。

业务 convenience API 可以保留内部 convenience behavior，但不得被 Spike / formal evidence path 使用。

### 方案 B — ProviderExchangeBundle / ProviderCallResult

如必须保留内部 prerequisite，则高层返回：

```text
prerequisite_exchanges[]
primary_exchange
```

并由 RawWriter/ProbeExecutor 全量持久化。

不接受：

```text
继续依赖 last_envelopes 找 hidden exchange
```

## 2.4 Required Tests

```text
hidden calendar + kline => exactly two persisted exchange evidences
calendar failure => failure meta persisted; kline must not fabricate success
B3 symbol-list fetch is persisted
B7 symbol-list + calendar fetches are persisted
AST/static test: formal probes cannot call payload-only target provider methods
```

---

# 3. P0-02：Success Raw Evidence 只闭合 payload，没有闭合 envelope/meta

## 3.1 当前问题

成功 single-table exchange 会写：

```text
<request_id>.parquet
<request_id>.meta.json
```

但 `RawWriteResult.evidence_uri/evidence_hash` 对单表成功只指向 Parquet。

`ProbeContext.evidence_from_exchange()` 只把该 payload ref/hash 交给 case；Golden bundle 也只列：

```text
request_id
endpoint
evidence_ref
content_hash
```

因此：

```text
Parquet intact
meta.json deleted/tampered
```

现有 `verify_evidence_closure()` 仍可能通过。

这意味着 request_id、endpoint、request_params_hash、requested_at、received_at、account profile、attempt_count、error/status 等 envelope 事实并没有形成 verdict-level immutable closure。

## 3.2 强制契约

成功 exchange 的 immutable evidence 单元必须至少闭合：

```text
payload artifact(s)
AND
meta/envelope artifact
```

推荐将 RawWriteResult 明确拆为：

```text
payload_artifacts[]:
    uri
    content_hash
    schema_hash
    row_count

meta_artifact:
    uri
    content_hash
```

Evidence Bundle 对每个 exchange 至少记录：

```text
request_id
endpoint
provider_dataset
payload_artifacts[]
meta_ref
meta_hash
```

`verify_evidence_closure()` 必须同时验证所有 payload artifacts 与 meta artifact。

## 3.3 Metadata completeness

当前 RawEnvelope 没有持久化完整 `request_params` 字段，而 RawWriter `_meta_bytes()` 尝试读取 `envelope.request_params` 时实际通常得到空值；同时多个 endpoint 传给 `call_exchange(params=...)` 的只是 summary（例如 `codes=len(code_list)` 或仅前三个 code）。

这不足以 Exact Replay。

必须建立：

```text
request_params_hash = hash(full canonical request params)
```

且应能重建原请求。二选一：

### 方案 A

meta 直接持久化 scrubbed full request params。

### 方案 B

大型参数单独写 content-addressed request manifest：

```text
request_params_ref
request_params_hash
```

meta 持久化 ref/hash + 摘要。

无论哪种：

```text
same endpoint/date/count but different actual symbols
```

必须产生不同 request_params_hash。

## 3.4 Traceability 字段

按项目 Raw/Availability 原则与管理总册 CR-1 contract，补齐并测试：

```text
ingested_at
meta_ingest_run / ingest_run_id（或等价 run binding）
schema hash at artifact level
source revision（若 provider 提供）
```

若决定改变字段名/结构，按 ADR-010 amendment 处理。

## 3.5 Required Tests

```text
success parquet intact + meta deleted => evidence closure BLOCK
success parquet intact + meta tampered => BLOCK
multi-table one parquet tampered => BLOCK
same request payload same but meta different => conflict BLOCK
two code lists same length => request_params_hash differs
meta/request manifest reconstructs exact original code list
secret fields remain scrubbed
request_id/meta/payload/bundle all cross-check
```

---

# 4. P0-03：Trading Rule SoR 没有 run-bound provenance，Exact Replay 仍可漂移

## 4.1 `config_hash` 没有覆盖嵌套规则目录

当前 `compute_config_hash()` 只遍历：

```python
config_dir.glob("*.yaml")
```

新 SoR 位于：

```text
configs/trading_rules/a_share_limit_v1.yaml
```

因此修改 Trading Rule YAML **不会改变 config_hash**。

这是直接的 provenance 漏洞。

## 4.2 SpikeRun 没有绑定 Trading Rule 版本/hash

当前 SpikeRun 只显式绑定 Golden：

```text
golden_truth_version
golden_dataset_file
golden_dataset_hash
```

没有：

```text
trading_rule_file
trading_rule_version
trading_rule_hash
source_version
review_status
```

`default_rule_book()` 读取当前工作树规则文件，而不是 run-bound immutable rule artifact。

因此：

```text
run created under rule vN
repo/ACTIVE rule moves to vN+1
historical verdict/replay
```

仍可能解析 vN+1。

## 4.3 强制修复

Trading Rules 既然已由 ADR-011 升格为正式 SoR，就必须建立和 Golden 同级别的 binding：

```text
TradingRuleBinding:
    dataset_file / rule_file
    version
    content_hash
    source_version
    review_status
```

正式 run 创建时绑定；RUNNING / RESUME / VERDICT / REPLAY 只读取 bound rule dataset。

同时：

```text
compute_config_hash
```

必须递归、确定性覆盖 `configs/**`，或明确把 trading-rule hash 从 config_hash 独立出来。不得继续遗漏嵌套配置。

## 4.4 Required Tests

```text
nested configs/trading_rules change => config_hash changes
run bound rule vN; current rule advances vN+1 => historical result unchanged
bound rule file tampered/deleted => verdict BLOCK
current rule tampered while bound vN healthy => historical verdict unaffected
rule hash/version mismatch => resume/verdict BLOCK
```

---

# 5. P0-04：Trading Rule 的 Human Review Gate 目前只有文档，没有代码 Gate

## 5.1 当前状态

当前 YAML：

```text
review_status: COMPILED
reviewed_by: ""
```

管理总册已经把：

```text
Trading Rule 数据层 REVIEWED
```

列为 P0-M-1B Entry Gate。

但 `new_run(PRODUCTION)` 目前只执行 Golden quantity/event/review gates，没有 trading-rule review gate；resolver 也不会因规则数据仍为 COMPILED 而阻止 Production formal run。

## 5.2 强制实现

建立 Trading Rule Review Workflow / Gate，至少包括：

```text
COMPILED → REVIEWED
reviewed_by
reviewed_at
source_artifact_ref
source_artifact_hash
source_artifact_kind
source_retrieved_at
rule dataset content hash
```

制度事实的 `source_ref` 不能只是自由文本“某交易所规则”；Formal REVIEWED 必须能 resolve 到封存 artifact bytes 并 hash verify。

Production 创建前：

```text
TradingRuleReviewGate == PASS
```

Verdict/replay 时：

```text
reverify bound rule dataset + bound source artifacts
```

规则仍 COMPILED 时：

```text
PRODUCTION run creation MUST BLOCK
```

Trial/Dry-run 可以使用 COMPILED，但必须在 provenance 中明确。

---

# 6. P0-05：Corporate Action 仍缺“事件事实源”，adj-factor 不能替代 event record

## 6.1 上一轮 contract

工作要求明确要求 CA 至少包含：

```text
Event official/provider record
Adj factor around event
Kline T-1/T/T+1
PIT trading calendar
```

管理总册当前也仍写：

```text
Corporate Action
→ dividend/right issue + adj factor + price context
```

## 6.2 当前实现

当前 CA bundle 是：

```text
calendar
history_stock_status
adj_factor
kline
```

validator 以：

```text
adj row EX_DATE == T
```

作为 event-date proof。

这证明了“adjustment factor 在 T 发生变化”，但没有独立证明：

```text
dividend
rights issue
split / bonus issue
other corporate-action event type
```

也不能证明 Golden `truth_source` 对应的具体事件语义。

## 6.3 强制修复

CA domain 必须加入独立事件事实源：

```text
provider corporate-action/dividend/right-issue endpoint
OR
reviewed external official event artifact / versioned event dataset
```

要求：

```text
Event record exact date/type
+ Adj factor
+ Trading calendar
+ Kline T-1/T/T+1
(+ Status when suspension semantics needed)
```

如果 AmazingData SDK 确实没有可用 corporate-action event endpoint，不得静默把 adj factor 重新定义为 event source；必须：

1. 写 spike/provider capability 结论；
2. 选择正式替代 SoR；
3. 如改变 V1.3.2 中 CA source contract，提交相应 ADR / Change Record，必要时走 Baseline change approval；
4. Golden event truth 与 source artifact 绑定。

## 6.4 Required Tests

```text
adj factor exists but no event record => Core Golden CA cannot PASS
event record wrong date/type => FAIL
event + adj + T-1/T/T+1 all consistent => PASS
suspension path => explicit NOT_TESTABLE_TIME
evidence bundle includes event source + adj + calendar + kline (+status)
```

---

# 7. P0-06：Institutional Rule Facts 仍有 Python hard-code 漏网

虽然 `trading_rule.py` 主体已经数据驱动，但 `golden_router._validate_bj_mapping()` 仍直接写：

```python
if float(rule.up_rate) != 0.30 or float(rule.down_rate) != 0.30:
```

并以“BSE +/-30%”作为 validator 内置事实。

这仍使 Python validator 成为部分制度事实 SoR。

当前静态测试只扫描 `trading_rule.py`，覆盖面不足。

## 修复

BJ validator 应使用：

```text
Golden expected_fields
+ resolved rule record/version
+ provider observed limit prices
```

来比较，不在 Python 写制度费率字面量。

静态测试范围至少覆盖：

```text
src/ashare_state/spike/**/*.py
```

并用结构化规则避免误报普通数学常数。

---

# 8. P0-07：文档当前真相仍存在矛盾 / 过度宣称

## 8.1 Current Code Baseline 不精确

管理总册顶部仍写：

```text
Current Code Baseline：本批提交
```

必须写本轮实际 reviewed code SHA：

```text
d021936efb5a79615eb07f61f9d029f6710800f5
```

Reviewer 后续仅提交文档时，应明确区分：

```text
Reviewed Code Baseline
Reviewer Documentation Commit
```

不要用模糊“本批提交”。

## 8.2 §30 / §31 仍是旧状态

§30/§31 仍描述：

```text
R4-A1.1 PENDING_REVIEW
v2 candidate
Domain Router 待做
```

而 §40/§41 已写 R4-A2.3 DONE/PENDING_REVIEW。

作为“当前真相”总册，这是内部冲突。

## 8.3 Risk 状态过早关闭

§52：

```text
RISK-004 ProviderExchange 未统一 = CLOSED
```

但本轮仍存在 hidden/payload-only exchanges，因此必须 REOPEN。

## 8.4 DEVLOG 过度宣称

顶部开发条目声称：

```text
所有正式 provider evidence 都走 exchange→RawWriter
hidden calendar+kline 两 artifact 测试已覆盖
Python 无制度费率字面量
P0-01..09 全修
```

与实际 runtime 不一致。

不要修改/删除历史条目；应在顶部**追加 Reviewer Correction** 明确纠正。

---

# 9. P1 Robustness / Hygiene

以下不单独阻塞第一修复提交，但应随 CR-1.2 一并处理：

## P1-01 RawWriter multi-file atomicity

成功 multi-table 当前逐个写 Parquet，最后写 meta。中途异常可能留下 partial artifact set。

建议：

```text
stage all bytes
validate conflicts
atomic commit all
```

或用 request-scoped staging + final rename。

## P1-02 table-name sanitization collision

`_safe_table_name()` 可能让不同 logical names 映射到同一文件名。必须 detect collision and BLOCK。

## P1-03 read-time integrity

`RawWriter.read()` 最好复验 meta + table hashes，或明确只有 `VerifiedRawReader` 可进入 replay/canonical path。

## P1-04 TradingRule st_state parser

配置 loader 对非 null 字符串使用 `bool(st_raw)`；字符串 `"false"` 会得到 True。当前 YAML 使用布尔类型，但 schema 应 fail closed，不接受歧义字符串。

## P1-05 CI 状态

本轮 GitHub combined status / commit workflow lookup没有返回已确认的 checks。Local 418 PASS 不能替代 CI。

开发下一批需明确区分：

```text
Local Validation
GitHub CI Validation
```

---

# 10. 下一批架构边界

下一批命名：

```text
R4-A2.4 Evidence / Rule Provenance Closure
+
CR-1.2 Exchange Completeness
```

本批目标不是增加功能，而是完成两个 closure：

## Closure A — Every Exchange is Evidence

```text
Every REAL provider call
→ explicit ProviderExchange
→ persisted Raw payload/meta
→ exact request lineage
→ evidence closure
```

## Closure B — Every Semantic SoR is Bound

```text
Golden Truth
Trading Rules
Corporate Action Truth
```

均必须：

```text
versioned
reviewed where formal
source-evidenced
hash-sealed
run-bound
replayable
```

---

# 11. 推荐实施顺序

## Batch A — Exchange Completeness

```text
1. inventory every RealTarget/provider call path
2. eliminate audit-path payload-only calls
3. make Kline calendar prerequisite explicit
4. persist prerequisite + primary exchanges
5. static/runtime tests proving no unpersisted real exchange
```

## Batch B — Raw Exchange Closure

```text
1. payload artifact refs/hashes
2. meta ref/hash
3. full canonical request params / request manifest
4. request_params_hash over full real params
5. ingested_at + ingest_run binding
6. closure verifies payload + meta + params
7. multi-file atomicity/collision handling
```

## Batch C — Trading Rule Binding

```text
1. recursive config hash or dedicated rule hash
2. version/hash/file/source binding on SpikeRun
3. bound rule resolver
4. ACTIVE/current rule independence tests
5. review workflow + source artifact hash closure
6. Production rule Review Gate
```

## Batch D — CA Event SoR

```text
1. identify real provider/official event source
2. bind event type/date/source
3. include event exchange/artifact in bundle
4. verify event + adj + calendar + kline + status semantics
```

## Batch E — Rule Literal Cleanup

```text
1. remove BJ 0.30 literal from validator
2. project-wide institutional-fact static guard
3. compare Golden expected vs resolved rule vs provider observed
```

## Batch F — Governance Closure

```text
DEVLOG reviewer correction
DEVELOPMENT_MANAGEMENT current-state cleanup
RISK-004 reopen until verified
new Change Records
ADR-010/011 amendments if contract changes
work requirement implementation mapping
CI confirmation
```

---

# 12. Required Test Matrix

## Exchange completeness

```text
[ ] B3 code-list exchange persisted
[ ] B7 code-list exchange persisted
[ ] B7 calendar exchange persisted
[ ] query_kline calendar prerequisite + kline = two persisted raw exchanges
[ ] hidden prerequisite failure produces failure meta and no fabricated primary success
[ ] no formal probe calls payload-only target provider APIs
[ ] every real SDK call count equals persisted exchange count in instrumented fake/spy target
```

## Raw closure

```text
[ ] successful single-table payload + meta both closure-verified
[ ] successful multi-table every table + meta closure-verified
[ ] failure meta closure-verified
[ ] payload intact / meta tampered => BLOCK
[ ] meta intact / payload tampered => BLOCK
[ ] same request id + same payload + changed metadata => BLOCK
[ ] full request params hash differs for equal-size different code lists
[ ] exact request params reconstructable
[ ] secrets scrubbed
[ ] ingested_at/run binding present
```

## Trading Rule provenance

```text
[ ] nested trading-rule config affects config/provenance hash
[ ] run binds rule file/version/hash
[ ] current rule advance does not alter historical verdict
[ ] bound rule tamper/delete blocks
[ ] current rule tamper does not affect healthy bound historical run
[ ] COMPILED rule dataset blocks Production new_run
[ ] REVIEWED rule source artifact missing/tampered blocks
[ ] human review provenance completeness validated
```

## Corporate Action

```text
[ ] independent event source present in bundle
[ ] adj-only evidence cannot PASS
[ ] wrong event date/type FAIL
[ ] event + adj + T-1/T/T+1 consistent PASS
[ ] suspension semantics explicit
```

## Governance

```text
[ ] management Current Code Baseline uses exact SHA
[ ] §30/31/40/41 consistent
[ ] RISK-004 REOPENED until this review closes
[ ] DEVLOG correction appended; history preserved
[ ] implementation mapping references actual test names
[ ] Local / CI status reported separately
```

---

# 13. Exit Gate

只有以下全部满足，Reviewer 才可将 R4-A2.4 / CR-1.2 判 VERIFIED：

```text
[ ] zero unpersisted real provider exchanges on formal Spike path
[ ] no payload-only provider call in formal probes
[ ] Kline prerequisite calendar is explicit and persisted
[ ] success evidence closure verifies payload(s) AND meta
[ ] full real request parameters are reconstructable / hash-verifiable
[ ] request_params_hash represents full actual request, not count/first-N summary
[ ] ingested/run lineage satisfies Raw contract
[ ] Trading Rule dataset is run-bound with file/version/hash
[ ] Trading Rule formal Review Gate is enforced by code
[ ] Trading Rule source artifacts are resolvable + hash-sealed
[ ] institutional rates are not Python validator SoR
[ ] Corporate Action has independent event fact source
[ ] adj-only CA cannot Core PASS
[ ] bound Golden remains independent of ACTIVE
[ ] no silent fallback
[ ] management docs match runtime
[ ] required regression / adversarial tests pass
[ ] CI status is positively confirmed, not merely “triggered”
```

---

# 14. 本批禁止事项

R4-A2.4 / CR-1.2 VERIFIED 前：

```text
[ ] 不启动 CR-2 Provider-Normalized / Quarantine 主体
[ ] 不启动 CR-3 / CR-4
[ ] 不扩大 Feature / State 开发
[ ] 不执行正式 P0-M-1B
[ ] 不用 trial/dry-run 证明正式数据质量
[ ] 不用“Local tests 全绿”替代 runtime contract 复核
```

可以并行：

```text
Golden candidate/source artifact 准备
Trading Rule 官方规则 evidence 准备/人工 review
Corporate Action event-source endpoint spike
Trial L1 connectivity（标记非正式证据）
```

---

# 15. Change Control 建议

建议新增：

```text
DM-CR-20260824-008 — CR-1.2 Complete Exchange + Raw Meta/Request Closure
DM-CR-20260824-009 — Trading Rule Run Binding + Formal Review Gate
DM-CR-20260824-010 — Corporate Action Event SoR Closure
DM-CR-20260824-011 — R4-A2.3/CR-1.1 Review Correction & Governance Sync
```

分类建议：

- 008：C2 amendment to ADR-010；
- 009：C2 amendment to ADR-011；
- 010：若保持 Frozen Baseline 已定义 CA SoR，只是实现 closure，可 C1/C2 视最终 source architecture；若改变 Frozen Baseline 的 CA source 语义则必须升级 C3；
- 011：C1 governance correction。

每项重要改动的 Notes / Change Record 必须明确 4 件事：

```text
为什么改
怎么改
考虑过哪些方案、为什么未选
代价与收益
```

---

# 16. Reviewer 复检重点

下一次仓库更新后优先检查：

```text
1. grep/audit formal probes 是否仍调用 get_xxx payload convenience
2. query_kline 是否还有未返回/未持久化 hidden calendar exchange
3. RawWriteResult / bundle 是否同时绑定 payload + meta
4. RawEnvelope request_params 是否是完整真实请求
5. request_params_hash 是否对 equal-size/different-symbol request 区分
6. SpikeRun 是否绑定 trading-rule file/version/hash
7. verdict/replay 是否读取 current/default rule book
8. Production new_run 是否拒绝 COMPILED trading rules
9. rule review artifact 是否 bytes-resolvable + hash verified
10. CA bundle 是否有独立 event source，而不是只靠 adj EX_DATE
11. Python 是否仍含制度费率事实（尤其 BJ 30%）
12. DEVLOG / §30/31/40/41/43/48/52/53/61/62 是否一致
13. CI checks 是否真实可见并成功
```

---

# 17. 当前正式状态

```text
Reviewed Code HEAD: d021936efb5a79615eb07f61f9d029f6710800f5

R4-A2.3:
    Implementation = DONE
    Review = REOPENED

CR-1.1:
    Implementation = DONE
    Review = REOPENED

Next:
    R4-A2.4 + CR-1.2

CR-2:
    BLOCKED

Golden Human Review:
    OPEN / BLOCKING P0-M-1B

Trading Rule Human Review:
    OPEN / BLOCKING P0-M-1B

Production P0-M-1B:
    BLOCKED

CI for reviewed HEAD:
    NOT CONFIRMED by GitHub status/workflow lookup
```

本文件是下一批开发的直接任务输入。开发者应按 Batch A→F 执行，并在提交复审前回填 implementation mapping。