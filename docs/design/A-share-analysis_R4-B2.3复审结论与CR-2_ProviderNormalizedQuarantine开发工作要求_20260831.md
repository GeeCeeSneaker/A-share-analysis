# A-share-analysis：R4-B2.3 复审结论与 CR-2 Provider-Normalized + Quarantine 开发工作要求

> **Review Date**：2026-08-31 16:22 +08:00  
> **Reviewed Repository HEAD**：`6c5088bde046719c0b6df2b18d807079e62ee780`  
> **Primary R4-B2.3 Implementation**：`7362dfc93ab5ea6eb7ebc63c8fddb4508d7942aa`  
> **CI Fix**：`85a9260eb0cc07ea81c7844f661388e113575aa6`  
> **Reviewer Baseline / Requirements**：`4a7c26bfd93321e40b19cf22aada67fab36f2571`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**VERIFIED / CLOSED / FREEZE**  
> **R4-B2 / B2.1 / B2.2 / B2.3**：**CLOSED / VERIFIED / FREEZE**  
> **ADR-021**：下一开发治理提交同步为 **ACCEPTED**  
> **Next Batch**：**CR-2 Provider-Normalized + Quarantine**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

R4-B2.3 已关闭 R4-B2 链最后一个 correctness blocker：DQ governed scanner 的 completion proof 不再只绑定 component manifest，而是绑定 checker 实际读取的完整 authoritative input；该 input seal 从 scanner proof 贯穿 validation report，并在 publish transaction 内对 CURRENT input 再次重算比较。

本轮没有发现新的可复现 false-PASS blocker。因此直接执行：

```text
R4-B2      VERIFIED / CLOSED / FREEZE
R4-B2.1    VERIFIED / absorbed / FREEZE
R4-B2.2    VERIFIED / absorbed / FREEZE
R4-B2.3    VERIFIED / CLOSED / FREEZE

CR-2       START / ACTIVE NEXT
CR-3       BLOCKED_BY_CR-2
CR-4       sequenced after CR-3
Production P0-M-1B remains BLOCKED independently
```

本轮不再新增 B2.4，不重开 R4-B1/A3/A2/CR-1 冻结链。

---

# 1. R4-B2.3 Exit Gate 复核

## 1.1 Checker-specific authoritative input seal —— VERIFIED / FREEZE

`ArtifactDQCheckerSpec` 已把：

```text
resolve_input
fingerprint
evaluate
```

放进同一个 production-owned checker spec。scanner 对每个 checker：

```text
resolve SAME input state
→ fingerprint(state)
→ evaluate(state)
```

因此不再存在：

```text
fingerprint 看 A
checker 实际看 B
```

的语义漂移。

### IDENTITY_FALLBACK

fingerprint 覆盖：

```text
artifact components 中实际出现的 security_id 集
+ 每个 security_id 当前 dim_security.identity_key_version
+ 未注册时显式 __MISSING__
+ checker identity/version
```

因此 identity key version 改为 fallback、security 删除/新增、security 集变化都会使旧 proof stale。

### BLOCKING_DQ

fingerprint 覆盖：

```text
CURRENT artifact.data_snapshot_id
+ 五个 canonical fact table 对该 snapshot 的
  (table_name, normalized quality_flags, row_count)
+ checker identity/version
```

NULL/empty 与 evaluator 采用同一规范化规则；没有对无关列做整表 hash。

本项满足 Reviewer R4-B2.3 §4.1/4.2/4.3，冻结。

## 1.2 Scan transaction closure —— VERIFIED / FREEZE

`run_required_artifact_dq_scan()` 当前顺序为：

```text
BEGIN TRANSACTION
  _resolve_scan_context(CURRENT artifact snapshot + components)
  compute CURRENT component manifest
  resolve checker input
  compute authoritative_input_hash
  evaluate SAME input
  persist findings
  INSERT completion proof LAST
COMMIT
```

任何进入 completion correctness identity 的 DB read 不再发生在 BEGIN 之前。checker 异常仍整事务 rollback，不留下 completion proof。

本项满足 Reviewer §5，冻结。

## 1.3 Scanner → Validation → Publish 三层 freshness chain —— VERIFIED / FREEZE

### Scanner proof

`meta_artifact_check_execution` 通过 migration 013 增加并持久化：

```text
authoritative_input_hash
scanned_data_snapshot_id
```

同时保留：

```text
execution_id
check_id
scan_contract_version
producer
scanned_component_manifest_hash
completed_at
```

### Validation

`validate_artifact_for_publish()` 对每个 DQ required check 重算 CURRENT input fingerprint，并要求：

```text
proof contract == CURRENT DQ scan contract
proof producer == system-derived current checker identity
proof component manifest == CURRENT component manifest
proof authoritative_input_hash == CURRENT checker input hash
```

legacy/NULL/stale seal 均 `NOT_TESTABLE`，不能 grandfather。

validation report 持久化 `dq_execution_seals`，记录其实际消费的 execution id / contract / producer / input seal / component manifest / scanned snapshot。

### Publish final recheck

`_b2_recheck()` 在 publish transaction 内：

```text
验证完整 validation report / artifact / component seal
重验 physical component bytes
重算 CURRENT checker authoritative-input fingerprints
compare CURRENT fingerprints == report.dq_execution_seals
```

validation 后 `dim_security` 或 snapshot fact `quality_flags` 再变化时，publish 以 `ARTIFACT_DQ_INPUT_STALE` fail closed；输入无法客观重算时以 `ARTIFACT_DQ_INPUT_UNRESOLVABLE` fail closed。

因此上一轮三条 stale-proof false-PASS 路径均已关闭。

## 1.4 对抗测试 —— VERIFIED

新增/更新测试覆盖至少：

```text
scanner BEGIN-first ordering
scan 后 identity 改 FALLBACK -> old proof stale
scan 后 security unregistered -> old proof stale
scan 后 blocking fact 出现 -> old proof stale
artifact snapshot rebind -> old BLOCKING_DQ proof stale
validation 后 identity input 改变 -> publish BLOCK
validation 后 blocking DQ input 改变 -> publish BLOCK
input seal garbage / NULL -> fail closed
rescan 后真实 finding -> validation FAIL
unchanged genuine-zero -> validation PASS + publish success
validation report binds consumed DQ execution seals
legacy report without dq_execution_seals -> publish BLOCK
```

既有 B2.2 governed scanner、B2.1 full seal/transaction/URI、B1/A3/A2/CR-1 冻结测试保持绿。

## 1.5 CI —— VERIFIED

- implementation/fix run `33365674254`：success；
- current reviewed HEAD run `33366574574`：success；
- Windows Python 3.12：success；
- Windows Python 3.14：success；
- Ubuntu Python 3.14：success；
- Ruff lint / format / Mypy / Pytest / Spike framework gates：success；
- current suite：870 tests / 0 failed（开发记录与 CI 一致）。

开发过程中曾误提交 `.fix_tests.py` 导致 `ruff check .` 失败，随后由 `85a9260...` 删除并恢复全矩阵绿。该事件不构成 correctness blocker，但后续开发要求：临时迁移/改写脚本不得进入正式提交；本地 pre-push 检查应与 CI 一样覆盖 repo root，避免重复发生。

---

# 2. R4-B2 全链最终冻结范围

以下内容自本 Reviewer commit 起视为 CLOSED / FREEZE；后续只有可复现 regression 才允许重开：

```text
Formal artifact validation boundary
caller cannot self-declare validation counts/PASS
Typed required-check completeness
Persisted immutable validation report
Validation contract / checks / provenance / version full seal consumption
Exact artifact + component manifest seal
Physical bytes publish-time recheck
Latest validation-head policy
Legacy validation fail closed
Full transaction-internal publish preconditions
Logical-URI confinement
Governed DQ scanner boundary
Static production checker registry
System-derived scan contract / checker producer
Completion proof after real scan + findings persistence
Scanner failure -> no completion proof
Checker-specific authoritative-input fingerprint
Scanner transaction BEGIN-first identity resolution
Scanner proof -> validation report -> publish current-input freshness chain
Atomic republish rollback / exact artifact_validation_id binding
```

---

# 3. CR-2 目标：Raw Evidence → Provider-Normalized + Quarantine

现有管理总册 §44 的 CR-2 acceptance 是：

```text
Raw
→ Provider Mapper
→ Provider-Normalized
```

且：

```text
Mapping Validation 失败进入 Quarantine
不得 silent drop
不得使用 1970-01-01 / 0.0 等 sentinel 伪装合法值
```

现有基础已经具备：

- CR-1 提供 exact persisted `ProviderExchange -> RawWriter -> Raw immutable evidence`；
- `RawWriter` 的 `.meta.json` 是 evidence anchor，声明 exact payload table hash/schema/row_count；
- AmazingData `dto.py` 已明确 Provider-Normalized DTO 是 provider-faithful 层，不得偷换成 Canonical 语义；
- `mapper.py` 已对 required field 执行严格解析，`MappingValidationError` 明确写着“row quarantined by caller”；
- 但“caller 实际如何从 Raw evidence deterministic 地执行 mapper、如何持久化 normalized 结果、如何落 Quarantine、如何保证没有 silent drop”尚未形成正式 runtime。

CR-2 就是关闭这一缺口。

---

# 4. CR-2 非目标 / 边界

CR-2 **不做**：

```text
Source Policy / provider reconciliation
AvailabilityPolicy / available_at selection
跨 provider Canonical fact 合并
Canonical chosen source
SnapshotBuilder
DuckDB read-model rebuild
Feature / State
```

这些属于 CR-3 / CR-4。

CR-2 输出仍然必须是：

```text
provider-specific, provider-faithful, typed normalized facts
```

不得因为系统后续希望得到某个 Canonical 语义，就在 Provider Mapper 中提前“脑补”或改写 provider 事实。

---

# 5. CR-2 P0 Runtime Contract

## CR2-P0-01 Raw evidence 是唯一正式输入

正式 normalization runtime 必须从 **已持久化 Raw evidence** 读取，不能重新调 SDK/provider：

```text
ProviderExchange
  -> RawWriter
  -> exact raw meta anchor + payload bytes
  -> CR-2 NormalizationRunner
```

NormalizationRunner 必须先验证 raw evidence closure：

```text
meta evidence hash valid
payload file exists
payload content hash matches meta declaration
schema/row-count declaration可读取
```

应直接复用 `RawWriter.read(verify=True)` 或等价现有 verified reader，不得另写一套弱化 hash 规则。

失败 ProviderExchange（只有 failure meta、无业务 payload）不得被假装成 mapping failure；应明确记录 normalization `SOURCE_EXCHANGE_FAILED / NOT_NORMALIZABLE` 状态，并保留原 Raw failure evidence，不进入 Provider-Normalized 主输出。

## CR2-P0-02 Typed Dataset Normalization Registry

建立 production-owned、static typed registry：

```text
provider_dataset
expected raw payload/table shape
mapper / projector
output DTO/domain type
normalization contract version
quarantine scope: ROW | WHOLE_PAYLOAD
```

不得让 caller 注入任意 mapper/evaluator 作为 production truth。

所有当前 capability / mapper surface 必须 **显式分类**：

```text
SUPPORTED_NORMALIZATION
BLOCKED_PENDING_MAPPER
NOT_APPLICABLE
```

不允许某个 provider dataset 因为“暂时没 mapper”而 silent skip 后让 run 看起来 SUCCESS。

至少对当前已有 mapper/DTO surfaces 建立 exact routing，包括：

```text
trade_calendar
security_master
provider symbol / BJ mapping相关 identity surface（按现有设计路由）
daily_bar
security_status_history -> SecurityStatus + LimitPrice + CA flags/projections
adj_factor
industry member
equity_structure
index_daily
```

若 corporate-action direct endpoint 等当前 mapper 仍未具备足够已验证字段语义，则必须明确 `BLOCKED_PENDING_MAPPER`，不得伪造完成。

## CR2-P0-03 Provider-Normalized persistence 必须是 first-class immutable output

不能只在内存返回 DTO list。

推荐结构：

```text
normalized/provider=<P>/dataset=<D>/raw_request=<request_id>/contract=<version>/...
```

或等价 provider-neutral logical URI。

每次 normalization 必须有持久化 manifest/ledger，至少绑定：

```text
normalization_run_id
provider
provider_dataset
raw request_id
raw evidence_uri
raw evidence_hash
raw payload artifact identity
table name（如 multi-table）
normalization_contract_version
mapper/checker code identity or code_commit
normalized artifact uri/hash/schema_hash/row_count
quarantine artifact uri/hash/count
input_count
normalized_count
quarantined_count
status
started_at / completed_at
```

逻辑 URI 继续遵守 frozen logical-URI confinement；normalized 文件 immutable / content-hash verifiable。

## CR2-P0-04 No Silent Drop Accounting Invariant

对于 ROW-level mapper：

```text
input_row_count
== normalized_row_count + quarantined_row_count
```

必须由 runtime 机器强制。

任何：

```text
mapper exception swallowed
filter 后不记录原因
unknown row silently continue
```

都视为 contract violation。

对于 WHOLE_PAYLOAD mapper，例如现有 `map_trade_calendar()` 明确要求“一条日期无法解析则整个 calendar payload quarantine”，应满足：

```text
any invalid element
→ zero normalized output for this payload
→ one WHOLE_PAYLOAD quarantine evidence
→ run status BLOCKED/PARTIAL according to typed policy
```

不得只过滤坏日期后继续产生“看似完整”的交易日历。

## CR2-P0-05 Quarantine 必须是 first-class evidence，不是日志

`MappingValidationError` 不能只 print/log。

Quarantine 至少持久化：

```text
quarantine_id
normalization_run_id
provider / provider_dataset
raw request_id
raw evidence_uri / hash
raw table name
row locator / source row ordinal（ROW scope）
quarantine_scope
error_class
error_message
scrubbed structured error context
mapper / normalization contract version
created_at
```

并保留足以**从 Raw evidence 精确定位原始坏记录**的信息。

禁止把敏感 credentials/token 写入 quarantine；沿用现有 secret-scrub contract。

Quarantine 记录必须 immutable/append-only；修 mapper 后重新处理产生新的 normalization run，不删除历史 quarantine 来伪装“从未失败过”。

## CR2-P0-06 Deterministic source-row locator

Row quarantine 必须能回答：

```text
这个坏 DTO 来自哪一个 raw request？
哪一个 raw logical table？
哪一行 / 哪个稳定 source key？
```

推荐至少：

```text
raw_request_id + raw_table_name + raw_row_ordinal
```

如果 provider payload 有稳定自然键，可额外记录，但不得只存自然键而丢失 raw row locator。

multi-table Raw payload 不得“取第一个 table”；严格按 RawWriter meta 中声明的 table identity 路由。

## CR2-P0-07 Deterministic replay / idempotency

同一：

```text
raw evidence bytes
+ normalization contract version
+ mapper code identity
```

重复执行必须得到同样的：

```text
normalized semantic records
quarantine decision
normalized manifest hash（忽略明确非语义时间字段后的 canonical identity）
```

不得因 DataFrame row ordering、dict ordering、Windows/Linux path separator、timezone-local formatting 导致语义输出变化。

同一个 exact run 重放不得重复插入一组不可区分的 normalized/quarantine records；需要明确 idempotency key / conflict semantics。

## CR2-P0-08 Mapping error 与 Provider error 分离

错误分类至少分开：

```text
RAW_EVIDENCE_INVALID      # raw closure/hash 不成立
SOURCE_EXCHANGE_FAILED    # provider exchange 本身失败
PAYLOAD_SHAPE_UNSUPPORTED # raw success 但 payload/table shape 未支持
MAPPING_VALIDATION_FAILED # required field missing/unparsable等，可 quarantine
NORMALIZATION_INTERNAL_ERROR
```

不要把 ProviderPermissionError / NetworkError 与 MappingValidationError 混成一种 quarantine 原因。

## CR2-P0-09 Provider-Normalized 不得提前 Canonicalize

必须保持现有 `dto.py` 契约：

```text
provider literal / provider units / provider field semantics
```

例如当前仍为：

```text
DailyBarDTO.volume / amount = provider unit（未验证时不能擅自换算）
IndustryMemberDTO.taxonomy_owner = UNVERIFIED/GALAXY_UNVERIFIED until verified
IndexDailyDTO.return_type = UNVERIFIED until verified
EquityStructureDTO provider field meaning stays provider-faithful
```

CR-2 不得为了“方便 CR-3”把这些未知项静默改成系统 Canonical truth。

## CR2-P0-10 Success/Partial/Blocked 状态必须有机器定义

Normalization run status 建议至少：

```text
SUCCESS      all required inputs normalized, quarantine_count == 0
PARTIAL      row-level quarantine exists but policy permits retained good rows
BLOCKED      whole-payload quarantine / unsupported required surface /
             raw evidence invalid / source exchange failed / internal failure
```

每个 provider_dataset 的 `PARTIAL` 是否允许必须由 typed registry 明确，不能 caller 临时决定。

CR-3 只能消费 CR-2 明确允许的 normalized artifacts；不得自己绕过 quarantine 去读 raw 坏行。

---

# 6. 推荐 Schema / Artifact 设计

可调整命名，但建议最少增加两个 metadata surface：

```text
meta_provider_normalization_run
meta_provider_quarantine
```

Provider-Normalized 主记录建议继续使用 immutable Parquet artifact + manifest，而不是把所有 provider rows 全塞 metadata table。

示意：

```text
Raw .meta.json + payload parquet
        |
        v
NormalizationRun
  ├─ normalized artifact(s) + manifest
  └─ quarantine artifact / quarantine ledger
```

`meta_provider_normalization_run` 是 lineage/summary，不替代 normalized bytes。

若新增 migration：

```text
新增下一编号 migration
不得修改 001..013 历史 migration
from-zero + upgrade + idempotency + tamper/sequence tests 必须同步
```

CR-2 涉及正式数据层契约，至少按 C2 处理并新增 ADR（建议 ADR-022 Provider Normalization and Quarantine）。

---

# 7. 必须增加的对抗 / Contract Tests

至少覆盖：

```text
1. normalization 只能消费 persisted Raw evidence；测试中禁止 provider SDK call
2. raw meta hash tamper -> normalization BLOCK
3. raw payload bytes tamper -> normalization BLOCK
4. required field missing -> MappingValidationError -> quarantine，绝不 sentinel
5. unparsable required date -> quarantine；无 1970-01-01
6. unparsable required numeric -> quarantine；无 0.0 sentinel
7. legal zero/0.0 不得被 first_present 当 missing
8. row-wise：input == normalized + quarantine，任何 silent drop 使测试 FAIL
9. trade_calendar 一个非法日期 -> whole payload quarantine，零 normalized calendar
10. multi-table raw payload exact table routing；不得 take-first-table
11. unsupported required dataset -> BLOCKED_PENDING_MAPPER / run BLOCK，不 silent skip
12. mapper exception detail 可追溯到 raw request/table/row locator
13. quarantine 不泄露 password/token/secret/credential
14. rerun same raw+contract -> deterministic/idempotent
15. same request but raw evidence bytes conflict -> BLOCK
16. normalized artifact URI obeys logical-URI confinement（../, absolute, drive, alias 拒绝）
17. source exchange failure != mapping quarantine
18. provider-normalized DTO 保留 provider units/literals，不偷做 canonical assumptions
19. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 all green
20. R4-B2/B1/A3/A2/CR-1 frozen regression green
```

---

# 8. CR-2 Exit Gate

只有以下全部成立，Reviewer 才允许进入 CR-3：

```text
[ ] Raw evidence is the sole normalization input
[ ] exact Raw evidence closure verified before mapping
[ ] static typed dataset normalization registry exists
[ ] all current capability/mapper surfaces explicitly classified
[ ] Provider-Normalized output is immutable persisted artifact, not memory-only
[ ] normalized output binds exact raw evidence uri/hash/request/table
[ ] row-level no-silent-drop accounting invariant enforced
[ ] whole-payload quarantine semantics enforced where required
[ ] MappingValidationError produces first-class quarantine evidence
[ ] quarantine has exact raw row locator + structured scrubbed error context
[ ] no sentinel substitution for required invalid fields
[ ] failed provider exchange separated from mapping quarantine
[ ] unsupported required payload/dataset fail closed
[ ] deterministic replay + idempotency proven
[ ] provider-specific semantics/units remain provider-faithful
[ ] no CR-3 Availability/SourcePolicy/Canonical selection leaked into CR-2
[ ] logical-URI / immutable artifact contracts preserved
[ ] migrations from-zero / upgrade / idempotency green if schema changes
[ ] full CI matrix green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR current truth synced
[ ] ADR-021 status synced ACCEPTED after B2 closure
```

完成后：

```text
CR-2 -> VERIFIED / CLOSED
CR-3 AvailabilityPolicy + Canonicalizer -> START
```

---

# 9. 治理同步要求

下一开发提交必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
ADR-021 status -> ACCEPTED
new ADR for CR-2 contract（建议 ADR-022）
```

管理总册状态更新为：

```text
R4-B2 / B2.1 / B2.2 / B2.3  CLOSED / VERIFIED / FREEZE
CR-2                            ACTIVE / NEXT
CR-3                            BLOCKED_BY_CR-2
CR-4                            sequenced after CR-3
Production P0-M-1B              BLOCKED independently
```

并按总册既有要求更新 §17、§40、§42、§44、风险/技术债、Change Log。

本 Reviewer 不要求本轮直接重写巨大 living document；本 focused reviewer document 是当前权威复审/下步工作要求，下一开发批次负责把 current truth 合并回治理总册。

---

# 10. 工程进度（面向项目 Owner）

```text
A股数据基座
│
├─ ① Raw / Evidence 基础设施
│    ✅ CR-1 + R4-A2.x 已完成并冻结
│
├─ ② Provider 正式运行时能力证明
│    ✅ R4-A3 + R4-B1 已完成并冻结
│
├─ ③ Publish Validation Exactness
│    ✅ R4-B2   Formal validation boundary
│    ✅ B2.1    Seal / transaction / URI closure
│    ✅ B2.2    Governed DQ scanner
│    ✅ B2.3    Authoritative-input freshness seal
│    └─ 本轮正式 CLOSED / VERIFIED
│
├─ ④ Provider-Normalized + Quarantine
│    🔧 CR-2 现在启动
│    ├─ Raw evidence -> typed provider DTO
│    ├─ 坏数据 -> 可追溯 Quarantine
│    └─ 目标：不丢行、不造 sentinel、可精确重放
│
├─ ⑤ Canonical Runtime
│    ⏸ CR-3 AvailabilityPolicy + Canonicalizer（等 CR-2）
│    ⏸ CR-4 SnapshotBuilder + ReadModel（等 CR-3）
│
└─ ⑥ 正式生产数据闭环
     ⛔ P0-M-1B 仍受正式账号 / 人工 Golden & Rule Review 阻塞
```

**当前最关键含义**：系统已经能可靠回答“这批 feature artifact 是否真的经过当前数据输入的检查、是否仍可发布”；下一步开始补齐此前缺失的中间数据层——把已经保存好的 provider Raw 证据稳定转换为 Provider-Normalized 数据，并把任何无法可靠解释的坏记录隔离出来，而不是让它们悄悄进入 Canonical 主数据。

---

# 11. Implementation Mapping（开发方填写，2026-08-31）

## §5 P0 Runtime Contract

| Requirement | Implementation | Tests |
|---|---|---|
| **P0-01** Raw evidence 唯一正式输入；复用 verified reader；失败 exchange ≠ mapping failure | `NormalizationRunner.run(provider, provider_dataset, request_id)`：定位 `.meta.json` → `verify_meta_closure`（复用）→ `RawWriter.read(verify=True)`（复用）→ mapper；全程无 provider/SDK 访问；ERROR meta → `SOURCE_EXCHANGE_FAILED` BLOCKED run（保留 failure evidence、零 quarantine 行） | test_normalizes_persisted_raw_evidence / test_missing_raw_meta_is_caller_misuse / test_source_exchange_failure_is_not_a_mapping_quarantine / test_runner_has_no_provider_calls |
| **P0-02** Typed dataset registry；caller 不可注入；全 surface 显式分类；unsupported fail closed | `registry.py`：STATIC `DATASET_NORMALIZATION_REGISTRY` keyed by (dataset, endpoint)；14 surface 全分类（9 SUPPORTED / 5 BLOCKED_PENDING_MAPPER：dividend / right_issue / bj_code_mapping / industry_base_info）；结构守卫 AST 抽取 provider surface exact 覆盖 | test_every_provider_surface_is_explicitly_classified / test_supported_specs_have_mappers / test_unsupported_surface_blocks_no_silent_skip / test_unknown_surface_blocks |
| **P0-03** First-class immutable 持久化输出 + manifest 绑定 raw request/evidence/table + 逻辑 URI confinement | `normalized/provider=<P>/dataset=<D>/raw_request=<rid>/contract=cr2-v1/`：parquet per output（canonical 全列排序）+ manifest.json（全绑定）+ ledger `meta_provider_normalization_run`（migration 014，22 列）；组件校验 + `physical_from_logical_uri`；artifact 不可变（同 bytes no-op / 异 bytes conflict） | test_normalizes_persisted_raw_evidence（manifest 断言）/ test_normalized_artifact_uris_are_canonical / test_evil_request_id_fails_closed ×6 |
| **P0-04** No silent drop（ROW 记账 + WHOLE_PAYLOAD 语义） | runtime 机器强制 `input == mapped + quarantined`（违反 → NORMALIZATION_INTERNAL_ERROR BLOCKED）；mapper 非 MappingValidationError 异常记为 internal-error quarantine + BLOCKED（不吞掉）；calendar 一个非法日期 → 零 normalized + 一条 whole-payload quarantine + BLOCKED | test_row_accounting_invariant_machine_enforced / test_mapper_internal_exception_is_recorded_not_swallowed / test_one_invalid_calendar_date_quarantines_whole_payload / test_valid_calendar_normalizes |
| **P0-05** Quarantine first-class evidence（全字段 + scrub + immutable） | `meta_provider_quarantine`（migration 014，17 列，append-only）：quarantine_id / run 绑定 / provider+dataset / raw request / evidence uri+hash / table / ordinal / source_key / scope / error_class / message / scrubbed context（credential 递归 REDACT）/ mapper identity / contract | test_quarantine_locates_exact_raw_row / test_quarantine_never_leaks_secrets（注入 password/token → REDACTED） |
| **P0-06** Deterministic source-row locator；multi-table 严格路由 | quarantine 记录 `raw_request_id + raw_table_name + raw_row_ordinal`（source_key 为 best-effort 自然键不替代 locator）；multi-table payload 无 spec.source_table 路由 → PAYLOAD_SHAPE_UNSUPPORTED BLOCK（不取第一个 table） | test_quarantine_locates_exact_raw_row / test_multi_table_payload_requires_exact_table_routing |
| **P0-07** Deterministic replay / idempotency；同 request 冲突 bytes BLOCK | run_id = uuid5(sha256(evidence hash + contract + mapper identity))；idempotent replay 返回既有 run（零重复行）；semantic_hash 行序无关；同 request 不同 evidence bytes → RAW_EVIDENCE_INVALID BLOCK | test_rerun_is_idempotent / test_deterministic_semantic_output（reversed 输入）/ test_conflicting_raw_evidence_bytes_block |
| **P0-08** 错误分类分离 | `NormalizationErrorClass` 五类（RAW_EVIDENCE_INVALID / SOURCE_EXCHANGE_FAILED / PAYLOAD_SHAPE_UNSUPPORTED / MAPPING_VALIDATION_FAILED / NORMALIZATION_INTERNAL_ERROR） | 各 BLOCK 测试的 error_class 断言 |
| **P0-09** 不提前 canonicalize | 注册 mapper 即既有 provider-faithful mappers：provider literals / units / GALAXY_UNVERIFIED 原样通过；status 三输出 event_type=STATUS_FLAG_PROJECTION 诚实标注 | test_daily_bar_preserves_provider_units_and_literals / test_industry_member_keeps_unverified_marker |
| **P0-10** SUCCESS/PARTIAL/BLOCKED 机器定义；PARTIAL 由 registry 声明 | 状态机如 §5；PARTIAL 逐 spec.allow_partial；internal error → BLOCKED | TestStatusMachine 三态 + test_row_quarantine_partial_when_allowed |

## §7 必须增加的对抗测试（20 项映射）

1. normalization 只消费 persisted Raw evidence；禁止 SDK call ✓（test_runner_has_no_provider_calls + test_missing_raw_meta）
2. raw meta hash tamper → BLOCK ✓
3. raw payload bytes tamper → BLOCK ✓
4. required field missing → quarantine 绝不 sentinel ✓（+ normalized artifact 断言无坏行）
5. unparsable required date → quarantine 无 1970-01-01 ✓
6. unparsable required numeric → quarantine 无 0.0 ✓
7. legal zero/0.0 不当 missing ✓（first_present 语义）
8. row-wise input == normalized + quarantine ✓（4 行混合场景）
9. trade_calendar 一个非法日期 → whole payload quarantine 零输出 ✓
10. multi-table exact routing 不 take-first ✓
11. unsupported required dataset → BLOCKED_PENDING_MAPPER run BLOCK ✓
12. mapper exception 可追溯 locator ✓（ordinal 0/1 断言）
13. quarantine 不泄露 password/token/secret ✓（注入验证）
14. rerun same raw+contract → deterministic/idempotent ✓（零重复 ledger 行）
15. same request conflicting raw bytes → BLOCK ✓
16. normalized URI logical-URI confinement ✓（canonical 断言 + evil request id ×6）
17. source exchange failure ≠ mapping quarantine ✓（零 quarantine 行断言）
18. provider-normalized DTO 保留 provider units/literals ✓
19. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 all green——推送后正向确认（见下）
20. R4-B2/B1/A3/A2/CR-1 frozen regression green ✓（全量 907/0）

## §6 Schema / Artifact 设计

- migration 014：`meta_provider_normalization_run`（22 列）+ `meta_provider_quarantine`（17 列）；from-zero 14 链 + idempotent + tamper 守卫测试同步；未改 001..013
- normalized 主记录 = immutable Parquet artifact + manifest（metadata table 仅 lineage/summary——工作要求 §6 原样采纳）
- C2 处理 + 新 ADR：**ADR-022**（含五问 + 被拒替代方案 + 残余边界如实记录）

## §8 Exit Gate 对照

```text
[✓] Raw evidence is the sole normalization input
[✓] exact Raw evidence closure verified before mapping
[✓] static typed dataset normalization registry exists
[✓] all current capability/mapper surfaces explicitly classified（14 surface AST 守卫）
[✓] Provider-Normalized output is immutable persisted artifact, not memory-only
[✓] normalized output binds exact raw evidence uri/hash/request/table
[✓] row-level no-silent-drop accounting invariant enforced
[✓] whole-payload quarantine semantics enforced where required
[✓] MappingValidationError produces first-class quarantine evidence
[✓] quarantine has exact raw row locator + structured scrubbed error context
[✓] no sentinel substitution for required invalid fields
[✓] failed provider exchange separated from mapping quarantine
[✓] unsupported required payload/dataset fail closed
[✓] deterministic replay + idempotency proven
[✓] provider-specific semantics/units remain provider-faithful
[✓] no CR-3 Availability/SourcePolicy/Canonical selection leaked into CR-2
[✓] logical-URI / immutable artifact contracts preserved
[✓] migrations from-zero / upgrade / idempotency green（14 链）
[ ] full CI matrix green（推送后正向确认回填）
[✓] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR current truth synced
[✓] ADR-021 status synced ACCEPTED after B2 closure
```

## §9 治理同步

- DEVLOG append-only 新条目（2026-08-31 CR-2：why / how / 关键决策 / SHA+CI 推送后回填）
- DEVELOPMENT_MANAGEMENT：头部（B2 链 CLOSED + CR-2 ACTIVE + CR-3 BLOCKED_BY_CR-2）+ §40/§41/§44/§61（DM-CR-20260831-063）
- ADR-021 status → **ACCEPTED**（B2 closure 同步）；ADR-000 索引更新（ADR-021 ACCEPTED + ADR-022 PROPOSED）
- 新 **ADR-022**（Provider Normalization and Quarantine）

## Verification Summary

- Local: **907 / 0**（870 → 907，+37）；ruff check / ruff format --check / mypy 全绿；CI 同款命令 `uv run pytest` 复验 907/0
- 未启动 CR-3 / CR-4 / Feature / State（§4 边界遵守）；Exit Gate 全过 → CR-3 START
