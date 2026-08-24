# A-share-analysis：R4-A2.2 / CR-1 复审结论与 R4-A2.3 / CR-1.1 开发工作要求

> **Review Date**：2026-08-24 13:13 +08:00  
> **Reviewed HEAD**：`2f4a7ae0e5af0861046b23885d0a6fc498c3326f`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2 / R4-A2.2、CR-1、`docs/project/DEVELOPMENT_MANAGEMENT.md`、`docs/DEVLOG.md`  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.3 Correctness Closure + CR-1.1 Runtime Closure**  
> **Production P0-M-1B**：**BLOCKED**  

---

# 0. Reviewer 工作闭环规则（新增强制治理要求）

自本次评审起，项目的 Reviewer 工作必须形成仓库内闭环：

```text
读取最新 Git HEAD
→ 完成代码 / 测试 / 文档复审
→ 形成 VERIFIED / REOPENED 裁决
→ 同一评审轮次直接把评审意见与下一步开发要求写入仓库
→ 后续协作者仅凭仓库即可取得最新要求并继续工作
```

强制要求：

1. Reviewer 完成评审后，不得只在聊天、临时消息或外部笔记中保留结论；
2. 每次评审必须在仓库归档一份“评审结论 + 问题清单 + 下一步开发要求”；
3. 涉及 C1/C2/C3 或项目状态变化时，开发批次必须同步更新：
   - `docs/DEVLOG.md`
   - `docs/project/DEVELOPMENT_MANAGEMENT.md`
4. Reviewer 不再等待 Project Owner 二次确认是否上传评审结果；评审完成即自动归档；
5. 如果 Reviewer 发现当前管理文档与代码状态不一致，必须在评审文件中明确指出，并把修正文档列为下一批 DoD；
6. 后续协作者开始开发前，应先读取：
   - `docs/project/DEVELOPMENT_MANAGEMENT.md`
   - `docs/DEVLOG.md`
   - `docs/design/` 中日期最新的开发工作要求

本条属于项目 Governance Contract，后续应并入 `docs/project/DEVELOPMENT_MANAGEMENT.md` 的工作流程 / Reviewer 职责章节。

---

# 1. 本轮复审摘要

相对上一轮 HEAD `172abb6`，当前 `main` 前进到 `2f4a7ae`。本次提交集中实现了：

- review_gate 全量遍历；
- Run-bound Golden 基础 resolver；
- Candidate Augmentation；
- Production new_run 的 quantity + event + review fail-fast；
- Golden evidence content-addressing / provenance / path confinement / create-only version；
- Domain Router；
- B3 fabricated ST truth 删除；
- PIT TradingRule + Decimal ROUND_HALF_UP；
- 固定 History fixtures；
- BSE 独立 evidence；
- ProviderExchange；
- RawWriter；
- request_id lineage 相关 contract tests。

这些工作使项目明显前进，但复审发现运行时链路仍有若干“结构已存在、正确性未闭环”的问题，因此 **R4-A2.2 与 CR-1 均不能 VERIFIED**。

本轮裁决：

```text
R4-A2.1 Review Workflow / Candidate / 基础 Bound Resolver
    = SUBSTANTIALLY PASS

R4-A2.2 Domain Router / PIT / CA context
    = REOPENED

CR-1 ProviderExchange + RawWriter
    = REOPENED

Documentation / Governance Synchronization
    = REOPENED
```

下一批禁止扩展到 CR-2 或大规模新功能，优先把当前链路收口。

---

# 2. 已通过、允许保留的实现

以下成果原则上不回退，后续以修正和收口为主：

## 2.1 review_gate 全量校验

已修复“第一条成功后提前 break”的问题：

```text
for every REVIEWED case
    resolve artifact
    SHA256 verify
    collect all errors
```

必须保留 first-valid-second-tampered / later-missing 回归测试。

## 2.2 Candidate Augmentation

当前 candidate 生命周期方向正确：

```text
add-case
→ validate
→ build-version
→ Human Review
```

职责边界继续保持：

```text
Candidate workflow：创建 / 修正 COMPILED candidate
Review workflow：核验证据、COMPILED → REVIEWED
```

Review workflow 不得代替 Candidate workflow 创建 truth event。

## 2.3 Golden Evidence Closure 基础设施

允许保留：

- artifact 真 bytes SHA256；
- content-addressed `evidence/sha256/...`；
- REVIEWED provenance load-time validation；
- artifact path confinement；
- versioned dataset / manifest create-only；
- batch stage-all-then-commit。

## 2.4 Run-bound Golden 基础 resolver

`SpikeRun` 持久化：

```text
golden_truth_version
golden_dataset_file
golden_dataset_hash
```

`load_bound(dataset_file, truth_version, dataset_hash)` 直读 immutable dataset 的方向正确，必须保留。

## 2.5 B3 / B4 语义职责分离

B3 不再构造现场 `expected_is_st=False`，这一点通过：

```text
B3 = structural observation
B4 = reviewed semantic truth comparison
```

不得回退。

## 2.6 History 固定 fixtures / BSE 专项

以下 fixture 可以继续作为基础：

```text
600519.SH
000001.SZ
835185.BJ
300104.SZ
```

并继续保留 BSE/BJ 独立 evidence，不允许用“当前 code list 恰好包含 BJ”替代。

---

# 3. P0-01：CR-1 没有形成真正的显式 ProviderExchange Runtime 链

## 3.1 问题

虽然 `AmazingDataProvider.call_exchange()` 已返回 `ProviderExchange`，但业务 wrapper 立刻取 `.payload`；SpikeTarget 仍只暴露 payload API。

更关键的是：

```text
ProbeContext.evidence()
```

仍从：

```text
provider.last_envelopes
```

中按 endpoint 反查最后一个 envelope/request_id。

失败路径同样从 `last_envelopes` 反查 failed envelope。

这仍然是隐式共享状态，只是名字不叫 `last_exchange`。

因此当前实现不能满足：

```text
1 real SDK exchange
= 1 ProviderExchange
= 1 request_id
= 1 RawEnvelope
= <=1 payload
= 1 immutable raw evidence record
```

## 3.2 强制修复

### A. SpikeTarget / RealTarget 提供 Exchange API

正式/Spike 路径必须能显式取得 `ProviderExchange`。

建议至少形成：

```python
exchange = target.call_exchange(...)
```

或者为各业务方法提供显式：

```text
get_xxx_exchange(...)
```

业务便利 API 可以继续返回 payload，但 **审计 / Spike / Raw ingestion 路径必须消费 Exchange**。

### B. 删除运行时 last_envelopes 反查

运行路径禁止：

```text
provider.last_envelopes[-1]
按 endpoint 搜索 last_envelopes
通过共享 list 推断本次调用 request_id
```

`last_envelopes` 如保留，仅允许 debugging/diagnostic，不得参与 correctness 或 lineage。

### C. RawWriter 直接消费 ProviderExchange

目标接口建议：

```python
RawWriter.write(exchange, provider=..., dataset=...)
```

而不是让调用者分别传：

```text
request_id
payload
envelope
```

RawWriter 内部必须断言：

```text
exchange.request_id == exchange.envelope.request_id
```

并以 envelope 自带的 provider/provider_dataset 为首选，不允许外部传入值与 envelope 静默冲突。

### D. 失败 Exchange 必须是一等对象

当前失败时 provider 记录 envelope 后直接 raise，调用方只能去共享 list 反查。

必须改为显式可审计模式，例如：

```text
ProviderCallError carries ProviderExchange(error-envelope, payload=None)
```

或者等价结构。

要求：调用失败时也能不依赖全局/共享状态取得此次 exchange 的：

```text
request_id
envelope
attempt_count
error_class
requested_at
received_at
```

## 3.3 Acceptance Tests

至少新增：

```text
test_spike_success_consumes_explicit_exchange

test_spike_failure_consumes_explicit_failed_exchange

test_no_runtime_last_envelopes_lookup

test_same_endpoint_concurrent_or_adjacent_calls_do_not_cross_bind_request_id

test_hidden_calendar_and_kline_create_two_distinct_exchanges
```

最后一项必须证明两个 exchange 均落真实 Raw evidence，而不是仅存在 provider 内存 list 中。

---

# 4. P0-02：RawWriter 尚未真正接入 Spike / Raw Runtime

## 4.1 问题

当前 RawWriter contract test 主要是：

```text
人工构造 / 调用 ProviderExchange
→ 人工调用 RawWriter.write_success()
```

但 Spike 实际 runtime 仍使用：

```text
RunStore.write_evidence()
```

写 JSON evidence。

所以 CR-1 目前是“新模块存在”，还不是“系统 Raw path 已迁移”。

## 4.2 强制修复

Spike 的真实 provider evidence path 应切换为：

```text
ProviderExchange
→ RawWriter
→ Raw Parquet + meta.json
→ RawWriteResult
→ SpikeCase.evidence_ref / evidence_hash
```

禁止：

```text
Provider call
→ payload
→ RunStore.write_evidence(JSON)
```

作为正式 provider raw 证据链。

Dry-run/Fake 是否继续使用 RunStore JSON 可单独决定，但 Formal Trial/Production provider path 必须走统一 RawWriter。

## 4.3 Failure evidence

失败 exchange：

```text
payload artifact = none
meta artifact = mandatory
```

SpikeCase 必须能引用 failure meta evidence，并在 evidence closure 时复验 hash。

---

# 5. P0-03：RawWriter 的 DataFrame / dict-of-DataFrames 序列化存在真实数据风险

## 5.1 问题

当前 `_rows_of()` 逻辑对真实 SDK 常见 payload shape 不安全。

典型风险：

```text
list(DataFrame)
```

得到的是列名而不是 records。

`dict[str, DataFrame]` 也可能被误转换。

因此目前“lossless Parquet”只在 `list[dict]` fixture 上得到证明。

## 5.2 强制实现

RawWriter 必须明确支持至少：

```text
list[dict]
dict[str, list[dict]]
pandas.DataFrame
dict[str, pandas.DataFrame]
pyarrow.Table（如运行中可能出现）
```

对于 dict-of-frames，需要定义稳定模型。可选：

### 方案 A

每个 logical table 独立 Parquet：

```text
<request_id>/<table_name>.parquet
```

meta 记录 table list + each hash/schema/rows。

### 方案 B

如果 provider contract 能保证只存在一个有效 frame，则在 adapter boundary 明确 normalize 成单表 ProviderExchange。

不允许“取 dict 第一个 value”作为静默规则。

## 5.3 Required Tests

```text
DataFrame round-trip dtype / value test
dict-of-DataFrames multi-table round-trip
empty DataFrame
nullable int / decimal / datetime / string
Chinese column/value
NaN / None behavior
```

读取 Parquet 后逐字段比较，而不是只断言 `num_rows`。

---

# 6. P0-04：Golden Domain Router 的验证数据与 evidence 不是同一次 Provider Exchange

## 6.1 问题

当前 `route_all()`：

```text
直接 ctx.target.get_xxx()
→ 得到实际验证数据
```

之后 B4 再做：

```text
executor.call(... lambda: None)
```

生成 domain evidence。

这意味着：

```text
Validator 实际使用的数据
!=
SpikeCase 最终绑定的 evidence
```

甚至 endpoint 也可能不一致。

这是严重 provenance 问题，会破坏：

```text
Immutable Evidence
Exact Replay
request_id lineage
failure classification
```

## 6.2 强制修复

每个 Domain fetch 必须显式返回：

```text
DomainData
+ one or more ProviderExchange / RawWriteResult
```

正确流程：

```text
ProviderExchange(s)
→ RawWriter
→ DomainData from exact payload(s)
→ Validator
→ SpikeCase references exact Raw evidence
```

彻底删除为凑 evidence 而存在的：

```text
lambda: None
```

伪调用。

## 6.3 Multi-endpoint domain lineage

例如 Delisted：

```text
get_hist_code_list
get_stock_basic
```

Corporate Action：

```text
corporate-action source endpoint
adj_factor
kline
status（如需要）
```

一个 GoldenCase 可以绑定一个 evidence bundle / evidence refs 列表；不得伪装成单一 status endpoint。

如果现有 `SpikeCase` 只能单 evidence_ref，需要在 R4-A2.3 做最小兼容设计：

```text
evidence_bundle manifest
```

SpikeCase 指向 bundle；bundle 再列出所有 raw refs + hashes + request_ids。

如该变化改变正式 evidence model，按 C2 处理并新增 ADR。

---

# 7. P0-05：Run-bound Golden 在 Production Verdict 阶段仍存在 ACTIVE 泄漏

## 7.1 问题

`load_bound()` 本身正确，但：

```text
production_formal_gate(bound_manifest)
```

内部仍调用：

```text
self.review_gate()
```

而 `review_gate()` 使用 `self.load()`，即 ACTIVE dataset。

所以历史 Production Run 在 ACTIVE Golden 推进后，最终 verdict 仍会受到 ACTIVE 的 artifact 状态影响。

这不满足 Exact Replay。

## 7.2 强制修复

所有 Formal Golden Gate 必须变为 bound-aware：

```text
quantity_gate(cases, manifest)
event_coverage_gate(cases, manifest)
review_gate(cases, manifest)
production_formal_gate(cases, manifest)
```

或者同等实现。

规则：

```text
NEW run creation
    可使用 ACTIVE 选择并 gate

RUNNING / RESUME / CLOSE / VERDICT / REPLAY
    只能使用 run-bound dataset
    禁止读取 ACTIVE
```

Review artifact 的 ref/hash 复验必须针对 bound cases 自身。

## 7.3 必测反向场景

```text
1. run bound vN
2. ACTIVE advance to vN+1
3. vN+1 artifact tampered
4. vN intact
=> historical run verdict unchanged

反向：
1. vN bound artifact tampered/deleted
2. ACTIVE vN+1 perfectly healthy
=> historical run verdict MUST BLOCK
```

还必须测试：

```text
ACTIVE truth_version 与 bound 不同
ACTIVE review_summary 与 bound 不同
ACTIVE event coverage 与 bound 不同
```

均不得改变 bound run 的 formal result。

---

# 8. P0-06：PIT Trading Rule 违反 Frozen Baseline 的“禁止硬编码制度事实”

## 8.1 问题

当前 `trading_rule.py` 在 Python 分支中直接编码：

```text
Main 10%
ST 5%
ChiNext 10% / 20%
STAR 20%
BSE 30%
IPO 44% / 36%
effective dates
```

虽然代码具有 effective_from/to 字段，但事实本身仍硬编码在代码。

Frozen Baseline / Development Management 的原则是：

```text
不得硬编码 ±10/20 等制度规则
历史制度必须 PIT + versioned + traceable
```

## 8.2 强制设计

规则事实迁移到版本化数据层，例如：

```text
configs/trading_rules/*.yaml
```

或：

```text
data/reference/trading_rules/<version>.jsonl
```

至少字段：

```text
rule_id
exchange
board
security_pattern / eligibility condition
effective_from
effective_to
st_state
listing_age_rule
up_rate
down_rate
tick_size
rounding_mode
source_ref
source_version
review_status
```

Python 代码只负责：

```text
load
validate
PIT match
conflict detection
resolve
Decimal calculation
```

不得继续作为制度事实 SoR。

## 8.3 规则冲突必须 fail closed

出现：

```text
0 matching rule
>1 equally-valid rules
unknown board
missing source version
```

禁止 silent fallback 到 MAIN 10%。

必须：

```text
RULE_UNRESOLVED / validation failure
```

---

# 9. P0-07：首 N 日无涨跌幅限制不能用“日历天 * 2”近似

## 9.1 问题

当前 `_in_first_days()` 用：

```text
listing_date + days * 2 calendar days
```

近似前 N 个交易日。

春节、国庆、停牌、特殊日历下会错误。

## 9.2 修复

必须通过 PIT Trading Calendar 计算：

```text
listing trading session index
current trading session index
```

以交易日序号判断 first-N sessions。

### Required Tests

至少覆盖：

```text
listing before Spring Festival
listing before National Day
weekend crossing
5th trading day
6th trading day
missing calendar row
```

missing calendar 不得 fallback 为 calendar-day approximation。

---

# 10. P0-08：Limit Validator 没有精确按 case.trade_date 取状态

## 10.1 问题

当前 limit validation 从跨多年 status rows 中：

```text
next(row where SECURITY_CODE == bare)
```

只按证券代码取第一条，没有 exact `trade_date` filter。

这可能拿到完全不同日期的：

```text
IS_ST_SEC
HIGH_LIMITED
LOW_LIMITED
```

从而产生 false PASS / false FAIL。

## 10.2 修复

必须通过至少：

```text
provider_symbol
trade_date
```

精确匹配。

若 provider date 字段格式不同，先在 adapter/provider-normalized 层明确 normalize。

0 行 / 多行都 fail closed。

listing_date 也必须来自同一 PIT context，不允许默认 None 导致规则悄然退化。

---

# 11. P0-09：Corporate Action T-1/T/T+1 目前只是注释，不是验证

## 11.1 问题

当前实现抓取大范围 kline / adj，但 validator 实际只判断：

```text
status result
adj row exists or not
```

没有证明：

```text
T-1
T
T+1
```

三个真实交易日上下文，也没有完成 price / adjustment continuity。

同时管理要求写的是：

```text
Corporate Action
→ dividend/right issue + adj factor + price context
```

目前 corporate-action 事件源 endpoint 并未真正进入证据组合。

## 11.2 修复要求

每个 Corporate Action Golden Case 最少形成：

```text
Event official/provider record
Adj factor around event
Kline T-1 / T / T+1
PIT trading calendar
```

验证包括：

```text
exact event date
factor transition location
raw price discontinuity
adjusted continuity（按项目定义）
missing session / suspension semantics
```

若 T 或相邻日停牌，validator 应给出明确 NOT_TESTABLE/DIFF_EXPLAINED 规则，不得随意 PASS。

---

# 12. P1：BSE/BJ Evidence 需要从“有专项调用”升级为“独立语义证明”

当前 B5 对 `835185.BJ` 的专项 status 调用方向正确，但后续应明确：

```text
BSE board mapping
PIT rule
historical security identity
limit regime
```

分别由何种 evidence 证明。

不能仅以“status endpoint 返回了 rows”判定 BSE correctness。

此项可随 R4-A2.3 完成，不单独阻塞第一批修复提交。

---

# 13. Documentation / Governance 当前不一致

当前 `docs/project/DEVELOPMENT_MANAGEMENT.md` / `docs/DEVLOG.md` 中存在以下冲突：

1. Change Log 声称 CR-1 已实现“无 last_exchange 模式”，而 runtime 仍反查 `last_envelopes`；
2. DEVLOG 声称 Spike request_id 已“不再重新生成”，而实际代码仍有 uuid fallback；
3. 管理总册状态表仍把部分已经实现的 R4-A2/CR-1 写成 PLANNED/READY，同时 Change Log 又写 DONE；
4. Risk / Technical Debt 中仍有已变更但未同步的描述；
5. 当前审计裁决为 REOPENED，管理文件必须如实反映，而不能继续写“全部完成”等同于通过复核。

## 强制修复

R4-A2.3 / CR-1.1 开发批次必须同一逻辑 change set 更新：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

至少修改：

```text
Current Code Baseline
Last Review
§40 当前阶段状态
§41 当前最高优先级
§43 CR-1 Acceptance
§48 P0-M-1B Entry Gate
§52 Risk Summary
§53 Technical Debt
§56 Reviewer Workflow
§61 Change Log
§62 Next Maintenance Checkpoint
```

并把本文件 §0 的 Reviewer 自动归档规则并入管理总册。

建议 Change IDs：

```text
DM-CR-20260824-005 — R4-A2.3 Correctness Closure
DM-CR-20260824-006 — CR-1.1 Explicit Exchange Runtime Closure
DM-CR-20260824-007 — Reviewer Auto-Archive Governance
```

如 evidence bundle 改造构成 C2，则另开正式 ADR，不得把 C2 偷降成 C1。

---

# 14. 本批明确禁止事项

在本批 P0 关闭前，禁止：

```text
[ ] 启动 CR-2 Provider-Normalized / Quarantine 主体开发
[ ] 启动 CR-3 Canonicalizer
[ ] 启动 CR-4 Snapshot Builder
[ ] 执行正式 P0-M-1B
[ ] 用试用账号结果作为数据质量 / 历史语义 / Capacity 正式证据
[ ] 为赶进度保留 silent fallback
[ ] 继续新增 Feature/State 功能
```

可以并行的工作仅限：

```text
Golden 人工候选事件整理 / source evidence 准备
试用账号 L1 connectivity（明确标 TRIAL / NOT FORMAL EVIDENCE）
测试 fixture 完善
文档修正
```

---

# 15. R4-A2.3 / CR-1.1 推荐实施顺序

## Batch A — Explicit Exchange Runtime

```text
1. Error/Exchange API 设计
2. SpikeTarget explicit exchange path
3. RawWriter consumes ProviderExchange
4. success/failure raw persistence
5. remove last_envelopes correctness dependency
6. DataFrame / dict-of-DataFrames round-trip
```

## Batch B — Golden Evidence Binding

```text
1. Domain fetch uses explicit exchanges
2. RawWriter persist domain exchanges
3. DomainData constructed from exact payloads
4. evidence bundle（如需要）
5. remove lambda:None evidence
6. failure classification + case linkage
```

## Batch C — Bound Formal Gates

```text
1. gate APIs become bound-aware
2. verdict no ACTIVE reads
3. ACTIVE advance/tamper adversarial tests
```

## Batch D — Trading Rule Correctness

```text
1. rule data/config SoR
2. rule schema validator
3. PIT resolver
4. trading-calendar first-N
5. exact trade-date status match
6. Decimal ROUND_HALF_UP retain
```

## Batch E — Corporate Action Context

```text
1. event source
2. trading-day context
3. T-1/T/T+1 kline
4. adj continuity
5. suspension/missing semantics
```

## Batch F — Documentation Closure

```text
DEVLOG
DEVELOPMENT_MANAGEMENT
ADR if C2
Review work requirement implementation mapping
```

---

# 16. Required Test Matrix

开发者不得只报“tests passed”，必须在 DEVLOG 中列出本批新增测试类别和数量。

最低新增测试矩阵：

## Exchange / Raw

```text
success explicit exchange
failure explicit exchange
same endpoint two consecutive exchanges
hidden calendar + kline two exchange/raw artifacts
request_id exact lineage
no last_envelopes runtime lookup
same hash idempotence
different bytes block
DataFrame roundtrip
dict-of-frames roundtrip
secret scrub
cross-platform URI
```

## Bound Golden

```text
ACTIVE advance does not affect historical run
ACTIVE artifact tamper does not affect bound healthy run
BOUND artifact tamper blocks even if ACTIVE healthy
BOUND event coverage independent of ACTIVE
BOUND review summary independent of ACTIVE
```

## Trading Rule

```text
rule data effective_from/to
rule overlap blocks
rule missing blocks
ST/main/ChiNext/STAR/BSE selected from rule data
Spring Festival first-5-day case
National Day first-5-day case
5th vs 6th trading session
ROUND_HALF_UP edge decimals
exact trade_date status selection
```

## Corporate Action

```text
T-1/T/T+1 exact sessions
adj factor changes at expected event
price context missing => not PASS
suspension case semantics
evidence bundle binds all exchanges
```

---

# 17. Exit Gate

R4-A2.3 / CR-1.1 只有同时满足以下条件，才允许 Reviewer 重新判 VERIFIED：

```text
[ ] Runtime correctness 不依赖 last_envelopes
[ ] Spike provider path 显式消费 ProviderExchange
[ ] Success and failure exchanges 都进入 RawWriter
[ ] Real SDK payload shapes lossless round-trip
[ ] Golden validators 与其 evidence 来自同一批真实 exchanges
[ ] 无 lambda:None 伪 evidence
[ ] Production historical verdict 对 ACTIVE 完全独立
[ ] Bound artifact failure 能独立阻断
[ ] Trading rules 不以 Python hard-code 作为 SoR
[ ] first-N 规则使用 trading calendar
[ ] limit status exact trade_date match
[ ] CA T-1/T/T+1 真正验证
[ ] No silent fallback
[ ] DEVLOG 与 DEVELOPMENT_MANAGEMENT 同步
[ ] Reviewer auto-archive rule 已写入管理总册
[ ] ruff / format / mypy / pytest / dry-run 全绿
```

即便全部 Local tests PASS，只要上述任一 runtime contract 未闭环，Review 仍为 REOPENED。

---

# 18. 下一轮 Reviewer 检查重点

下次开发者报告仓库更新后，Reviewer 优先检查：

```text
1. grep / search last_envelopes 的 runtime consumer
2. ProviderExchange error path
3. RawWriter real DataFrame path
4. Golden Router exact evidence lineage
5. production_formal_gate 是否还调用 ACTIVE load()
6. trading rules 是否已数据化
7. first-N 是否真正基于 trading calendar
8. limit row 是否按 symbol + trade_date 唯一选择
9. CA T-1/T/T+1 是否真正参与 validator
10. DEVLOG / DEVELOPMENT_MANAGEMENT / Change IDs 是否一致
```

不接受仅凭提交说明或“348/xxx tests passing”判定关闭。

---

# 19. 当前正式状态

```text
Reviewed HEAD: 2f4a7ae0e5af0861046b23885d0a6fc498c3326f
Review Verdict: REOPENED

R4-A2.1:
    Implementation = DONE
    Review = PARTIAL PASS / retained

R4-A2.2:
    Implementation = IN_PROGRESS (correctness closure required)
    Review = REOPENED

CR-1:
    Implementation = IN_PROGRESS (runtime integration incomplete)
    Review = REOPENED

Next:
    R4-A2.3 + CR-1.1

CR-2:
    BLOCKED

Production P0-M-1B:
    BLOCKED
```

本文件为下一批开发的直接任务输入。开发者完成后必须更新本文件对应问题的 implementation mapping，并同步 DEVLOG / DEVELOPMENT_MANAGEMENT，然后再提交 Reviewer 复审。
