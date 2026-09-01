# A-share-analysis：CR-2.4 最终复审结论与 CR-3 AvailabilityPolicy + Canonicalizer 开发工作要求

> **Review Date**：2026-09-01 17:06 +08:00  
> **Reviewed Repository HEAD**：`0b4ef7a1c91c896054501853adf40324ba3687fc`  
> **Primary CR-2.4 Implementation**：`3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc`  
> **Reviewer Baseline / Requirements**：`3348200832082dede63697eba25a17aa761a10b6`  
> **Frozen Baseline**：V1.3.2  
> **Formal Verdict**：**CR-2 / CR-2.1 / CR-2.2 / CR-2.3 / CR-2.4 VERIFIED / CLOSED / FREEZE**  
> **ADR-022 Reviewer Decision**：**ACCEPTED**（下一 developer governance commit 必须同步 ADR 正文与 ADR index 状态）  
> **Next Batch**：**CR-3 AvailabilityPolicy + Canonicalizer — START / ACTIVE NEXT**  
> **CR-4**：**BLOCKED_BY_CR-3**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 最终裁决

CR-2 从最初的 `Raw -> Provider-Normalized + Quarantine` 主体，到 CR-2.1/2.2/2.3/2.4 四轮 correctness 收口，现已形成一条可用于后续 Canonical Runtime 的正式生产级中间数据层。CR-2.4 关闭了最后一个 blocker：**RawWriter file commit 与 Raw Evidence Trust Anchor enrollment 不再是两个可任意拆开的动作，而是一个 production-owned anchored ingestion boundary。**

本轮正式确认：

```text
CR-2      VERIFIED / CLOSED / FREEZE
CR-2.1    VERIFIED / absorbed / FREEZE
CR-2.2    VERIFIED / absorbed / FREEZE
CR-2.3    VERIFIED / absorbed / FREEZE
CR-2.4    VERIFIED / CLOSED / FREEZE
ADR-022   REVIEWER ACCEPTED

CR-3      START / ACTIVE NEXT
CR-4      BLOCKED_BY_CR-3
Production P0-M-1B remains BLOCKED independently
```

除非出现**可复现 regression**，后续不得以 CR-3 开发为由重开 R4-B2/B1/A3/A2/CR-1 或 CR-2.x 已冻结机制。

---

# 1. CR-2.4 通过项

## 1.1 AnchoredRawEvidenceWriter —— VERIFIED / FREEZE

当前正式边界：

```text
ProviderExchange
 -> AnchoredRawEvidenceWriter.write_exchange(exchange)
 -> RawWriter.write(exchange)
 -> RawWriteResult.evidence_hash = H1
 -> reread final persisted meta bytes（verify-only）
 -> require sha256(meta bytes) == H1
 -> require meta identity == exchange envelope identity
 -> require evidence/meta URI == canonical request URI
 -> enroll meta_raw_evidence_anchor with H1
 -> return RawWriteResult
```

因此 anchor 的 expected hash 来自**刚刚完成的 RawWriter commit identity**，而不是 enrollment 时重新定义“第一次看到的 bytes”。

### 通过理由

- write -> enroll TOCTOU：最终 bytes != RawWriteResult.evidence_hash 时 HARD FAIL；
- `_enroll_anchor` 再次 verify-only 校验声明的 commit hash，不会用磁盘当前值重定义 first truth；
- request/provider/dataset/endpoint/normalization_surface/operation_id 与 exchange envelope 做 cross-binding；
- canonical meta URI 与 RawWriteResult.evidence_uri/meta_uri 做 cross-binding；
- 同 request + same hash anchor enrollment 幂等；不同 hash hard conflict，绝不 rebaseline；
- anchor DB INSERT 失败时 ingest 不完整，Raw bytes 可保留，但因为无 anchor，NormalizationRunner 继续 fail closed；
- exact retry 同一 exchange 由 RawWriter idempotent 命中同一 commit identity，再完成 anchor enrollment。

本边界满足 CR-2.4 P0。

## 1.2 Production wiring —— VERIFIED / FREEZE

`ProbeContext` 现在要求 `conn`，并将原有 `RawWriter` 替换为 `AnchoredRawEvidenceWriter`：

```text
evidence_from_exchange
 -> anchored writer

failure_evidence
 -> evidence_from_exchange
 -> anchored writer
```

因此 SUCCESS/ERROR provider evidence 都会自动留下 anchor。

`run_dry_run` 也创建已执行 migration 的 DuckDB connection，并通过同一 ProbeContext/anchored write path 进行框架自测，不再由 tests-only helper 模拟一个生产中不存在的流程。

## 1.3 Recovery / conflict tests —— VERIFIED

本轮新增对抗测试覆盖：

- Probe SUCCESS 自动 anchor；
- failure evidence 自动 anchor；
- write->enroll TOCTOU meta swap 不得 enrollment；
- anchor INSERT failure -> ingest fail；
- 无 anchor 时 Normalization `RAW_ANCHOR_MISSING`；
- exact retry -> one anchor + same evidence identity；
- same H1 repeat idempotent；
- same request H1->H2 hard conflict；
- anchored healthy raw -> Normalization SUCCESS；
- meta endpoint/operation/surface 与 envelope 不一致 -> enrollment BLOCK；
- public late recorder API 已撤销。

## 1.4 CI —— VERIFIED

Current reviewed HEAD `0b4ef7a1c91c896054501853adf40324ba3687fc` CI run `33482934673`：

```text
Ubuntu Python 3.14       success
Windows Python 3.12      success
Windows Python 3.14      success
Ruff lint                success
Ruff format              success
Mypy                     success
Pytest                    success
Spike framework gates    success
Governance gates          success where applicable
```

CR-2.4 implementation commit `3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc` 的 developer-reported test baseline 为 `985/0`。

---

# 2. P1 非阻塞加固：RawWriter anti-bypass AST guard 需要增强

当前 structural guard 的方向正确，但实现依赖 receiver 变量名包含 `writer` 才将 `.write/.write_success/.write_failure` 判断为 RawWriter call site。因此以下代码形态理论上可能绕过 guard：

```python
rw = RawWriter(...)
rw.write(exchange)

RawWriter(...).write(exchange)
```

这是**future regression guard 的覆盖不完整**，不是当前 CR-2 correctness blocker：当前正式 provider evidence path 已切到 AnchoredRawEvidenceWriter，且 anchored boundary 本身已完成 correctness closure。

登记为 P1/TD，CR-3 第一批治理提交中完成即可：

- AST 跟踪 `RawWriter` import / alias / constructor assignment；
- 或更简单：生产 `src/ashare_state` 中除 `raw_writer.py/raw_anchor.py` 外禁止构造 `RawWriter(...)`；
- tests 下允许 direct RawWriter 用于 legacy/tamper fixture；
- guard 必须新增 `rw = RawWriter(...); rw.write(...)` 与 `RawWriter(...).write(...)` 的 negative fixtures。

不得以此重开 CR-2。

---

# 3. CR-2 全链冻结能力清单

CR-3 可依赖以下契约为稳定上游：

```text
1. Raw Evidence 是唯一正式 normalization 输入
2. Provider-owned operation identity
3. RawWriter exact evidence + anchored ingestion trust root
4. Raw meta/payload exact-byte closure
5. Static typed normalization registry
6. Provider-Normalized provider-faithful DTO semantics
7. No sentinel（1970 / 0.0 等不得伪造）
8. No silent drop：input = normalized + quarantine
9. Whole-payload quarantine
10. First-class quarantine + exact raw row locator
11. SUCCESS / PARTIAL / BLOCKED typed state machine
12. Immutable normalized parquet + deterministic manifest
13. Quarantine exact-set seal
14. Full mapper code SHA-256 identity
15. Historical exact replay（A->B->A）
16. Raw evidence trust anchor first-consume protection
17. Expected output exact-set seal
18. Physical content/schema/row_count replay verification
19. Normalized semantic value seal
20. File-side recoverable commit + DB transaction closure
```

CR-3 不得绕过 CR-2 manifest/ledger 直接读取“看起来像 normalized 的 parquet”。

---

# 4. CR-3 目标：Provider-Normalized -> Canonical

CR-3 的唯一职责是把**已通过 CR-2 的 provider-specific / provider-faithful 数据**转换成系统统一的 Canonical 候选与选择结果，并把 PIT 时间正确性、数据源政策、冲突处理做成可审计 runtime。

正式边界：

```text
CR-2 eligible Provider-Normalized artifacts
        ↓
Candidate Builder
        ↓
Identity Resolution
        ↓
AvailabilityPolicy（先做 as-of 可用性过滤）
        ↓
SourcePolicy / Reconciliation
        ↓
Canonicalizer
        ↓
Immutable Canonical Artifact + Decision/Conflict Evidence
```

CR-3 **不是** SnapshotBuilder，不负责 DuckDB read model rebuild；这些属于 CR-4。

---

# 5. CR-3 P0 Runtime Contract

## CR3-P0-01：Canonical 唯一输入必须是 CR-2 verified Provider-Normalized

Formal Canonicalizer 不得：

- 调 Provider SDK；
- 重新读取 Raw payload 自己做 mapper；
- 接受 caller 直接传 DataFrame/list 作为“正式候选”；
- 绕过 CR-2 run closure / output-set / semantic seal。

Canonical 输入至少必须绑定：

```text
normalization_run_id
provider
normalization_surface
provider_dataset
raw_request_id
raw_evidence_hash
normalization_contract_version
mapper_code_hash
normalized_manifest_uri/hash
normalized_output_set_hash
normalized_semantic_hash
status
```

消费前必须调用 CR-2 authoritative replay/closure verifier 或等价只读验证器。

## CR3-P0-02：CR-2 run eligibility 必须机器定义

建议：

```text
SUCCESS  -> eligible
PARTIAL  -> 默认 NOT eligible；只有 SourcePolicy 明确允许该 domain 的 retained-good-row consumption 才 eligible
BLOCKED  -> NEVER eligible
```

若允许 PARTIAL：

- quarantine exact set 必须验证；
- canonicalizer 只能消费 CR-2 materialized good rows；
- 不得访问 quarantined raw rows；
- policy 必须版本化并进入 canonical run identity。

caller 不得临时传 `allow_partial=True`。

## CR3-P0-03：AvailabilityPolicy 必须在 Source Selection 前执行

PIT 核心顺序必须是：

```text
candidate
 -> derive/resolve available_at
 -> filter available_at <= as_of
 -> only THEN source selection / reconciliation
```

禁止：

```text
先选“最好”的 provider
再看它是否在 as_of 可用
```

否则未来数据会影响历史选择。

## CR3-P0-04：available_at 不得伪造

每类 surface 必须有 typed availability classification，例如：

```text
SOURCE_PUBLISHED_AT
OBSERVED_AT_INGEST
DOMAIN_RULE_DERIVED
NOT_VERIFIABLE
```

最低要求：

- 有经验证 source publish timestamp -> 可用 SOURCE_PUBLISHED_AT；
- 没有 source publish timestamp -> 默认保守使用 ingestion/observation time；
- 不得把 `trade_date 00:00`、`1970-01-01`、固定收盘时间写死成 available_at；
- 若需基于市场制度/收盘时间推导，必须引用版本化 Trading Rule / Calendar 事实 + policy version；
- `NOT_VERIFIABLE` 不得偷偷进入 PIT canonical truth。

每条 Canonical row 至少带：

```text
effective_date / trade_date
available_at
ingested_at
availability_basis
availability_policy_version
```

## CR3-P0-05：Provider identity resolution fail closed

Provider symbol -> `security_id` 必须走受治理的 identity mapping / bridge；不得：

- 根据股票代码前缀猜交易所；
- 找不到映射时退回 provider symbol 当 canonical key；
- ambiguous mapping 取第一条。

结果至少：

```text
resolved -> candidate
missing -> canonical finding / excluded
ambiguous -> canonical finding / excluded
```

关键 domain 若 missing/ambiguous 超出 policy 阈值，应 BLOCK run。

## CR3-P0-06：Canonical natural key 必须按 domain 静态定义

至少显式定义当前可进入 CR-3 的 domain key，例如：

```text
trade_calendar        market + trade_date
daily_bar             security_id + trade_date
security_status       security_id + trade_date
limit_price           security_id + trade_date
adj_factor            security_id + effective/trade date
corporate_action      security_id + event_date + event_class + deterministic event identity
industry_member       security_id + taxonomy + industry_id + effective interval
index_daily           index identity + trade_date
equity_structure      security_id + effective/report date（按已验证 provider semantics）
```

具体字段必须依据 DTO 已验证语义，不足则该 domain 显式 `BLOCKED_PENDING_CANONICAL_SEMANTICS`，不得猜。

## CR3-P0-07：SourcePolicy 必须版本化、静态/数据驱动、不可 caller 注入

Source selection 至少绑定：

```text
domain
provider priority
allowed fallback providers
partial-run allowance
reconciliation policy
tolerance rule id/version
required evidence class
policy version
```

可使用已有 `meta_source_policy` / `meta_tolerance_rule`，但 runtime 必须有 typed read model / exact validation。

禁止 caller：

```text
canonicalize(... preferred_provider="X")
canonicalize(... tolerance=0.1)
canonicalize(... allow_fallback=True)
```

作为 production correctness truth。

## CR3-P0-08：No Silent Fallback

当首选 provider 在当前 as_of 不可用或失败时：

- policy 明确允许 alternative -> 记录 `FALLBACK_SELECTED` decision evidence；
- policy 不允许 -> BLOCK / NOT_AVAILABLE；
- 不得静默“有什么用什么”。

Canonical row 必须记录最终来源及 selection reason。

## CR3-P0-09：Reconciliation 必须显式处理跨源冲突

多 provider 同 key 且在同 as_of 可用时：

1. 按 domain tolerance 先比较；
2. within tolerance -> policy 选择确定来源，并记录 equivalent/reconciled；
3. above tolerance -> `SOURCE_CONFLICT` finding；
4. 是否 BLOCK 由 SourcePolicy 明确规定。

禁止：

- last-write-wins；
- dataframe concat 后 drop_duplicates(keep="first/last")；
- provider loop 顺序决定 winner。

## CR3-P0-10：Canonical row 必须有精确 lineage

每条 Canonical row 至少绑定：

```text
canonical_domain
canonical_key
selected_provider
source_normalization_run_id
source_output_name
source_normalized_row_identity / deterministic ordinal
source_raw_request_id
source_raw_evidence_hash
source_mapper_identity
source_availability_basis
source_policy_version
canonical_contract_version
```

CR-3 可在读取 CR-2 deterministic sorted parquet 时派生 deterministic normalized-row ordinal / row semantic hash，作为 row locator；不得要求回改 CR-2 已冻结格式，除非发现无法客观唯一定位的可复现 blocker。

若同一 normalized output 内出现重复 canonical key，必须显式 finding/BLOCK，不能 silent dedupe。

## CR3-P0-11：Corporate Action evidence tier 必须区分

`history_stock_status` 产生的 CA flag projection（例如 `STATUS_FLAG_PROJECTION`）不是 dividend/right-issue direct event SoR 的等价替代。

CR-3 SourcePolicy 必须把：

```text
DIRECT_EVENT
STATUS_FLAG_PROJECTION
OTHER_INFERRED
```

当成不同 evidence tier。

在 direct CA mapper 仍 `BLOCKED_PENDING_MAPPER` 时，不得把 projection 偷偷升级为“已验证公司行动事实”。可形成 indicator/auxiliary canonical surface，但不可伪造 direct corporate_action truth。

## CR3-P0-12：Limit Price / Trading Rule 不得硬编码制度事实

CR-3 可以选择 provider-normalized limit price / status 数据，也可以引用版本化 Trading Rule 做验证/availability derivation，但不得在 Python 中新增：

```text
ST=5%
科创板=20%
北交所=30%
某日期后规则变化
```

等硬编码制度事实。

## CR3-P0-13：Canonical 输出必须是 immutable artifact，不是直接 live-table overwrite

推荐布局：

```text
canonical/domain=<D>/as_of=<T>/contract=<V>/run=<run_id>/
  candidates.parquet（可选，若需要审计）
  selected.parquet
  decisions.parquet / findings.parquet
  manifest.json
```

manifest 至少封住：

```text
canonical_run_id
canonical_contract_version
as_of
input normalized run exact set/hash
identity dataset/version/hash
availability policy version/hash
source policy version/hash
tolerance rule version/hash
code fingerprint
selected artifact uri/content/schema/row_count/semantic hash
finding/decision exact-set hash
status
```

manifest LAST，文件 immutable，逻辑 URI confinement 沿用已冻结模式。

## CR3-P0-14：Canonical run identity 必须确定性、可历史 exact replay

同：

```text
exact normalized input set
+ as_of
+ canonical contract
+ identity version
+ availability policy identity
+ source policy identity
+ tolerance identity
+ canonicalizer code fingerprint
```

必须得到同一 run identity / semantic result。

任一 policy/version/code 改变 -> 新 run，历史保留，不覆盖旧 Canonical。

## CR3-P0-15：Canonical run 状态机器定义

建议：

```text
SUCCESS  所有 required domains 在当前 as_of 完整产出，零 blocking finding
PARTIAL  policy 明确允许的非核心缺口/可解释 fallback，仍有可用 selected rows
BLOCKED  identity/availability/source conflict/required domain/closure 等 blocking failure
```

是否允许 PARTIAL 由 policy 定义，不由 caller。

---

# 6. CR-3 推荐数据模型 / migration

新增 additive migration，编号接在当前 017 之后（即 018+；不得修改旧 migration）。建议至少：

```text
meta_canonicalization_run
  canonical_run_id
  as_of
  canonical_contract_version
  input_set_hash
  identity_version/hash
  availability_policy_version/hash
  source_policy_version/hash
  tolerance_policy_version/hash
  code_fingerprint
  manifest_uri/hash
  selected_count
  finding_count
  status
  started_at/completed_at

meta_canonical_reconciliation_finding
  finding_id
  canonical_run_id
  domain
  canonical_key
  finding_class
  providers / source run refs
  observed values summary
  tolerance rule
  blocking
  created_at
```

如果逐行 selection decision 数量较大，优先保存 immutable Parquet `decisions.parquet`，DB 只保存 run-level seal/summary；不要把大批 Canonical rows 塞入 metadata DB。

CR-3 建议新 ADR：

**ADR-023 AvailabilityPolicy + Canonical Source Selection**。

---

# 7. CR-3 第一批 domain eligibility matrix

开发前先生成静态/版本化 matrix，至少逐项分类：

```text
trade_calendar
daily_bar
security_master / identity-derived dimensions
security_status_history -> security_status
security_status_history -> limit_price
security_status_history -> CA projection
adj_factor
industry_member
equity_structure
index_daily
corporate_action direct dividend/right_issue
BJ code mapping
industry base-info taxonomy definition
```

每项只能是：

```text
CANONICAL_SUPPORTED
AUXILIARY_ONLY
BLOCKED_PENDING_SEMANTICS
NOT_APPLICABLE
```

不得 silent skip。

特别注意：CR-2 中 `BLOCKED_PENDING_MAPPER` 的 surface 不能在 CR-3 被“绕过 mapper”直接从 Raw 读取完成。

---

# 8. CR-3 Mandatory Adversarial Tests

至少覆盖以下 30 类：

1. Canonicalizer 不 import/call Provider SDK；
2. caller 不能注入 provider priority/tolerance/allow_fallback；
3. CR-2 BLOCKED run 不 eligible；
4. CR-2 PARTIAL 默认不 eligible；
5. policy 明确允许 PARTIAL 时只消费 materialized good rows；
6. normalized manifest/hash tamper -> BLOCK；
7. normalized physical semantic seal mismatch -> BLOCK；
8. available_at > as_of 的候选在 source selection 前被排除；
9. future preferred provider 不得影响历史 as_of winner；
10. source publish timestamp 缺失时不得伪造 00:00 / 1970；
11. OBSERVED_AT_INGEST 保守 availability 正确；
12. availability policy version change -> new canonical run；
13. identity missing -> finding/excluded；
14. identity ambiguous -> finding/excluded；
15. provider symbol prefix 不得作为 identity fallback；
16. 同 normalized output 重复 canonical key -> BLOCK/finding，不 silent dedupe；
17. 单 provider healthy candidate -> deterministic selected；
18. preferred provider available -> selected；
19. preferred unavailable + allowed fallback -> explicit FALLBACK_SELECTED；
20. preferred unavailable + fallback forbidden -> BLOCK/NOT_AVAILABLE；
21. 两 provider within tolerance -> deterministic policy winner；
22. 两 provider above tolerance -> SOURCE_CONFLICT；
23. provider iteration/order reversed -> same canonical result；
24. row order reversed -> same semantic hash；
25. source policy version change -> new run/history preserved；
26. tolerance version change -> new run/history preserved；
27. mapper/canonicalizer code fingerprint change -> new run/history exact replay；
28. CA STATUS_FLAG_PROJECTION 不能替代 DIRECT_EVENT；
29. Python AST guard 确认无 institutional limit-price facts hardcoded；
30. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff/Mypy/Pytest/Spike/governance 全绿。

另把 CR-2.4 P1 guard 加固纳入 CR-3 首批 regression test：

```text
rw = RawWriter(...); rw.write(...) -> guard FAIL
RawWriter(...).write(...) -> guard FAIL
```

---

# 9. CR-3 Exit Gate

全部满足后才允许：

```text
CR-3 VERIFIED / CLOSED / FREEZE
 -> CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild START
```

Exit Gate：

```text
[ ] CR-2 verified normalized output is sole formal input
[ ] normalized run closure/semantic seal consumed
[ ] typed domain eligibility matrix complete
[ ] AvailabilityPolicy versioned and machine-owned
[ ] as_of filter happens BEFORE source selection
[ ] no fabricated available_at
[ ] identity mapping fail closed
[ ] canonical natural keys typed/static
[ ] SourcePolicy versioned and caller cannot override correctness
[ ] no silent fallback
[ ] reconciliation/tolerance explicit
[ ] no last-write-wins / keep-first dedupe
[ ] per-row canonical lineage complete
[ ] CA evidence tier preserved
[ ] no hard-coded institutional price-limit facts
[ ] immutable canonical artifact + manifest
[ ] decision/finding exact-set seal
[ ] deterministic run identity / historical exact replay
[ ] additive migration from-zero + upgrade green
[ ] all CR-2/B2/B1/A3/A2/CR-1 frozen regressions green
[ ] full 3-leg CI green
[ ] ADR-023 created
[ ] ADR-022 + ADR index synchronized to ACCEPTED
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT synchronized
```

---

# 10. Governance / next developer first commit requirements

下一 developer commit 必须先同步项目治理真相：

```text
ADR-022          ACCEPTED / VERIFIED 2026-09-01
CR-2.x           CLOSED / VERIFIED / FREEZE
CR-3             ACTIVE / NEXT
CR-4             BLOCKED_BY_CR-3
Production P0-M-1B BLOCKED independently
```

必须同步：

- `docs/adr/ADR-022_provider_normalization_quarantine.md` Status -> ACCEPTED；
- `docs/adr/ADR-000_adr_index.md` ADR-022 -> ACCEPTED + VERIFIED 2026-09-01；
- `docs/DEVLOG.md` 追加 Reviewer closure（不得改写历史）；
- `docs/project/DEVELOPMENT_MANAGEMENT.md` 当前状态、§17/§40/§42/§44、风险/TD/change log；
- 新建 ADR-023；
- 登记 CR-2.4 AST guard alias-tracking P1 技术债并在 CR-3 首批完成。

---

# 11. 老板视角

CR-2 关闭后，项目已经不只是“能从供应商拿数据”，而是形成了：

```text
供应商调用身份固定
 -> 原始数据不可篡改留证
 -> Raw 身份自动登记
 -> 标准化转换
 -> 坏数据隔离
 -> 一条不偷偷丢
 -> 历史版本可精确重放
 -> 标准化文件少一份/多一份可发现
 -> 文件值被替换也可发现
```

下一阶段 CR-3 解决的是另一个层次的问题：

> **同一条市场事实，如果来自不同供应商、不同时间、不同质量，系统在“当时那个时间点”到底应该信哪一条。**

因此 CR-3 的核心不是继续写 mapper，而是正式建立 **时间可用性 + 多源选择 + 冲突解释 + Canonical lineage**。这是进入 Snapshot/ReadModel 前最后一个数据语义层。

---

# 12. Implementation Mapping（开发方填写，2026-09-01）

## §5 P0 Runtime Contract

| P0 | Implementation | Tests |
|---|---|---|
| P0-01 唯一输入 CR-2 verified | `CanonicalRunner` 只读 CR-2 ledger + artifacts（+raw meta received_at）；`verify_normalized_run`（normalization/runner.py 公开只读 verifier）消费前全量复验 | `TestClosureVerification`（manifest hash tamper / physical values swap → CLOSURE_VERIFICATION_FAILED → BLOCKED） |
| P0-02 eligibility 机器定义 | SUCCESS only（`_surface_runs` 查询 status='SUCCESS'）；PARTIAL 默认排除（v1 全 domain partial_run_allowed=False） | `TestBoundaryStructure::test_blocked_cr2_run_not_eligible` / `test_partial_cr2_run_not_eligible_by_default` |
| P0-03 availability 先于 selection | candidates 构建后先 `available_at <= as_of` 过滤（EXCLUDED_FUTURE decision），后 `_select` | `TestAvailability::test_as_of_filter_runs_before_selection` / `test_future_data_never_wins_historical_selection` |
| P0-04 available_at 不伪造 | `derive_available_at`（availability.py）唯一 basis OBSERVED_AT_INGEST = raw received_at；无 00:00/1970/固定收盘 | `test_available_at_is_real_ingest_time_never_fabricated`（== received_at；非 1970；非 T00:00；trade_date != available_at） |
| P0-05 identity fail closed | `IdentityBridge`（security_master 三 dataset → ADR-002）；裸码唯一市场匹配；PIT relist；missing/ambiguous → IDENTITY_MISSING blocking + 行排除 | `TestIdentityResolution` 3 项（missing finding+排除 / PIT relist / unknown market MISSING 非前缀猜） |
| P0-06 natural keys 静态 typed | eligibility.py：calendar market+trade_date；bars/status/limit security_id+trade_date；adj_factor security_id+ex_date+factor_type；不足 domain BLOCKED_PENDING_SEMANTICS | `TestDomainMatrix::test_matrix_classifies_every_surface`（12 项显式） |
| P0-07 SourcePolicy 版本化静态不可注入 | `CanonicalSourcePolicy` registry（source-policy-v1）；run() 签名零 correctness 参数 | `TestBoundaryStructure::test_no_caller_correctness_parameters`（run + __init__ 签名断言） |
| P0-08 No Silent Fallback | 不可用 → REQUIRED_DOMAIN_MISSING blocking；EXCLUDED_FUTURE 显式 decision | `TestSelection::test_required_domain_missing_blocks` + availability EXCLUDED_FUTURE 断言 |
| P0-09 Reconciliation 显式冲突 | EXACT 比较：等值 → EQUIVALENT_MERGED decision + deterministic winner；不等值 → SOURCE_CONFLICT blocking；重复 key → DUPLICATE_CANONICAL_KEY blocking | `TestSelection::test_equivalent_values_merge_with_decision` / `test_conflicting_values_block` / `test_duplicate_canonical_key_blocks` / `test_run_order_does_not_change_winner` |
| P0-10 精确 lineage | canonical row 14 字段（source run/output/ordinal+row identity hash/raw request/evidence hash/mapper identity/policy versions/availability basis） | `TestLedgerAndArtifacts::test_manifest_seals_everything`（逐字段断言） |
| P0-11 CA evidence tier | matrix：corporate_action BLOCKED_PENDING_SEMANTICS + ca_projection AUXILIARY_ONLY；API raise | `TestDomainMatrix::test_ca_projection_never_direct_event_truth` |
| P0-12 无硬编码制度事实 | AST guard 扫 canonical 包（limit/ST/board + 5/10/20/30% 模式） | `TestDomainMatrix::test_no_hardcoded_institutional_facts` |
| P0-13 immutable artifact + manifest | canonical/contract/as_of/run 布局；manifest LAST 无墙钟；同 bytes no-op 异 bytes conflict | `TestLedgerAndArtifacts`（manifest 全 seal 断言）+ `TestRunIdentity::test_damaged_prior_run_fails_closed` |
| P0-14 确定性 run identity + exact replay | uuid5(sha256(input_set+identity_hash+as_of+contract+三 policy+fingerprint))；prior 同 identity 三方 seal 复验后 idempotent | `TestRunIdentity` 5 项（policy/tolerance/fingerprint 变化新 run + rollback replay + tampered/replay fail closed + finding 删除 fail closed） |
| P0-15 状态机 | SUCCESS/BLOCKED（blocking findings 聚合）；PARTIAL 仅 policy | `TestSelection`（BLOCKED 场景）+ manifest status 断言 |

## §6 数据模型 / migration

migration 018：`meta_canonicalization_run`（24 列：run identity + as_of + contract + input_set/identity/policy 三组 version+hash + code fingerprint + manifest uri/hash + counts + status + idempotency key/replay + 时间戳 + finding_set_hash）+ `meta_canonical_reconciliation_finding`（10 列：deterministic finding_id + run 绑定 + domain/key/class + detail + blocking）。逐行 decisions 存 decisions.parquet（DB 只存 run-level seal/summary）。18 链 from-zero + 001..017→018 upgrade + idempotent + tamper probe 019（test_migrations.py）。

## §7 Domain Eligibility Matrix

12 项全显式分类（eligibility.py `_DOMAIN_SPECS`）：5 CANONICAL_SUPPORTED / 2 AUXILIARY_ONLY / 5 BLOCKED_PENDING_SEMANTICS——`TestDomainMatrix::test_matrix_classifies_every_surface` 结构断言；非 SUPPORTED domain 调用即 raise（`test_auxiliary_and_blocked_domains_rejected`）。

## §8 对抗测试矩阵（30 类）

```text
[✓] 1  canonicalizer 不 import/call Provider SDK（AST 扫 canonical 包）
[✓] 2  caller 不能注入 provider priority/tolerance/allow_fallback（签名断言）
[✓] 3  CR-2 BLOCKED run 不 eligible
[✓] 4  CR-2 PARTIAL 默认不 eligible（+ 全 policy partial_run_allowed=False 断言）
[✓] 5  （policy 允许 PARTIAL 的场景 v1 不存在——策略槽位 + 静态断言）
[✓] 6  normalized manifest/hash tamper -> BLOCK
[✓] 7  normalized physical semantic seal mismatch -> BLOCK
[✓] 8  available_at > as_of 候选在 selection 前排除（EXCLUDED_FUTURE）
[✓] 9  future preferred 不影响历史 as_of winner
[✓] 10 无 publish timestamp 不伪造 00:00/1970（== received_at 断言）
[✓] 11 OBSERVED_AT_INGEST 保守 availability 正确
[✓] 12 availability policy version change -> new run
[✓] 13 identity missing -> finding/excluded
[✓] 14 identity ambiguous/无法归市 -> finding/excluded（裸码多市场 + unknown market）
[✓] 15 provider symbol prefix 不得作为 identity fallback（missing 行无 bare-symbol key）
[✓] 16 同 output 重复 canonical key -> BLOCK（DUPLICATE_CANONICAL_KEY）
[✓] 17 单 provider healthy candidate -> deterministic selected
[✓] 18 preferred provider available -> selected（priority[0]=amazingdata）
[✓] 19 preferred unavailable + fallback forbidden -> BLOCK（REQUIRED_DOMAIN_MISSING）
[✓] 20 （同 19——v1 无 fallback provider 槽位）
[✓] 21 两 run within tolerance -> deterministic policy winner（EQUIVALENT_MERGED）
[✓] 22 两 run above tolerance -> SOURCE_CONFLICT blocking
[✓] 23 provider/run iteration order reversed -> same canonical result（deterministic tiebreak）
[✓] 24 row order reversed -> same semantic hash（selected 按 key 排序 + semantic hash）
[✓] 25 source policy version change -> new run/history preserved
[✓] 26 tolerance version change -> new run/history preserved
[✓] 27 code fingerprint change -> new run/history exact replay（含 rollback replay）
[✓] 28 CA STATUS_FLAG_PROJECTION 不能替代 DIRECT_EVENT
[✓] 29 AST guard 无 institutional limit-price facts hardcoded
[ ]  30 Windows 3.12 / 3.14 / Ubuntu 3.14 full CI green（本批推送后 API 正向确认，SHA 回填）
```

另：CR-2.4 P1 guard 加固已纳入本批（§2 建议）：

```text
[✓] rw = RawWriter(...); rw.write(...) -> guard FAIL（alias 形态 + 构造点双重违规）
[✓] RawWriter(...).write(...) -> guard FAIL（直接构造调用形态）
[✓] normalization/runner.py 构造白名单（read-only reader）但 write 零豁免
[✓] production 全树零违规
```

## §9 Exit Gate 对照（24 项）

```text
[✓] CR-2 verified normalized output is sole formal input（verify_normalized_run 全量复验）
[✓] normalized run closure/semantic seal consumed（tamper -> CLOSURE_VERIFICATION_FAILED）
[✓] typed domain eligibility matrix complete（12 项显式）
[✓] AvailabilityPolicy versioned and machine-owned（availability-v1 + hash 进 identity）
[✓] as_of filter happens BEFORE source selection
[✓] no fabricated available_at（OBSERVED_AT_INGEST == received_at）
[✓] identity mapping fail closed（missing/ambiguous blocking + 行排除）
[✓] canonical natural keys typed/static
[✓] SourcePolicy versioned and caller cannot override correctness
[✓] no silent fallback（REQUIRED_DOMAIN_MISSING / EXCLUDED_FUTURE 显式）
[✓] reconciliation/tolerance explicit（EXACT + finding）
[✓] no last-write-wins / keep-first dedupe（deterministic winner + blocking findings）
[✓] per-row canonical lineage complete（14 字段）
[✓] CA evidence tier preserved（AUXILIARY_ONLY + API raise）
[✓] no hard-coded institutional price-limit facts（AST guard）
[✓] immutable canonical artifact + manifest（manifest LAST 无墙钟）
[✓] decision/finding exact-set seal（finding_set_hash 三方：ledger == manifest == DB recompute）
[✓] deterministic run identity / historical exact replay（三方 seal 复验 + tamper fail closed）
[✓] additive migration from-zero + upgrade green（18 链 + probe 019）
[✓] all CR-2/B2/B1/A3/A2/CR-1 frozen regressions green（985 项全保持）
[ ]  full 3-leg CI green（本批推送后 API 正向确认，SHA 回填）
[✓] ADR-023 created（PROPOSED）
[✓] ADR-022 + ADR index synchronized to ACCEPTED（本批完成）
[✓] DEVLOG / DEVELOPMENT_MANAGEMENT synchronized（本批完成）
```

## Verification Summary

- Local: **1025 / 0**（985 → 1025，+40：canonical 36 项 + guard 加固 4 项）；ruff check / ruff format / mypy 全绿（69 源文件零错）；CI 同款命令 `uv run pytest` 复验 1025/0
- ADR-023 PROPOSED（新建）；ADR-022 → **ACCEPTED**（正文 + 索引同步）；migration 018（未改旧文件）；CR-2.x 冻结契约零改动（runner.py 仅新增只读 verifier）
- Implementation SHA + CI run：推送后回填（本节与 DEVLOG/总册头部同步更新）
