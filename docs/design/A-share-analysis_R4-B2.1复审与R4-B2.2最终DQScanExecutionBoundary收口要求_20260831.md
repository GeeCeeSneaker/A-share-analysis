# A-share-analysis：R4-B2.1 复审与 R4-B2.2 最终 DQ Scan Execution Boundary 收口要求

> **Review Date**：2026-08-31 08:03 +08:00  
> **Reviewed Repository HEAD**：`b00e40da78f84897ecb2f8d569178e99bcf829ce`  
> **Primary R4-B2.1 Implementation**：`317ac488c00c6b406311a29f25ff062e312df3a3`  
> **Reviewer Baseline / Requirements**：`306124775ed6f16bc796cc7fe51b0474daf6084f`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED（仅剩 1 个 P0）**  
> **R4-B2.1 已通过部分**：**PASS / FREEZE**  
> **Next Batch**：**R4-B2.2 Final Governed DQ Scan Execution Boundary**  
> **CR-2**：**BLOCKED_BY_R4-B2.2**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

R4-B2.1 对上一轮 4 个 P0 + 1 个 P1 中的 **3 个 P0 + 1 个 P1 已正确闭合**，这些部分本轮正式冻结，不得继续重构：

```text
VERIFIED / FREEZE  P0-02 full seal consumption
VERIFIED / FREEZE    ledger.validation_contract_hash == report == CURRENT contract hash
VERIFIED / FREEZE    ledger.required_checks_hash == report == recomputed report checks hash
VERIFIED / FREEZE    duplicate check_id fail closed
VERIFIED / FREEZE    validator_code_commit ledger/report exact-match + non-empty
VERIFIED / FREEZE    validation_version system-derived + ledger/report/current exact-match

VERIFIED / FREEZE  P0-03 full transaction-internal publish preconditions
VERIFIED / FREEZE    BEGIN TRANSACTION precedes authoritative snapshot/artifact/feature-set/run/universe reads
VERIFIED / FREEZE    validation head / seal / physical bytes also re-read inside the same transaction
VERIFIED / FREEZE    atomic rollback / old PUBLISHED preservation intact

VERIFIED / FREEZE  P0-04 frozen logical-URI confinement restored
VERIFIED / FREEZE    component file_uri -> physical_from_logical_uri()
VERIFIED / FREEZE    validation report_uri -> physical_from_logical_uri()
VERIFIED / FREEZE    escaped / absolute / drive / backslash / alias URI fail closed

VERIFIED / FREEZE  P1-01 manifest check semantic honesty
VERIFIED / FREEZE    ARTIFACT_MANIFEST_INTEGRITY renamed to
                     ARTIFACT_MANIFEST_PRESENT_AND_SEALED
VERIFIED / FREEZE    no longer overclaims recomputation not supported by current schema

VERIFIED / FREEZE  full CI matrix green
```

当前唯一 blocker：

```text
P0-01  meta_artifact_check_execution 的“positive execution proof”本身
       仍可由 caller 直接声明；没有真实 scanner 执行边界。
```

因此：

```text
R4-B2     -> DONE / REOPENED
R4-B2.1   -> DONE / REOPENED（仅 DQ execution truth 未闭合）
R4-B2.2   -> START / ACTIVE NEXT
CR-2      -> BLOCKED
```

除真实 regression，不重开 R4-B2.1 已通过的 seal / transaction / URI / manifest-name 部分，也不重开 R4-B1/A3/A2/CR-1 冻结链。

---

# 1. 已通过并冻结的 R4-B2.1 部分

## 1.1 Full Seal Consumption —— VERIFIED / FREEZE

`_b2_recheck()` 已真正把以下字段从“写入 metadata”升级为 publish correctness input：

```text
validation_contract_hash
required_checks_hash
validator_code_commit
validation_version
artifact_manifest_hash
component_manifest_hash
report_uri / report_hash
```

并形成：

```text
ledger
  <-> persisted validation report
  <-> CURRENT validation contract
  <-> CURRENT artifact/component registry identity
  <-> CURRENT physical component bytes
```

这一部分满足 R4-B2.1 P0-02，冻结。

## 1.2 Full Transaction-Internal Preconditions —— VERIFIED / FREEZE

`publish_snapshot()` 现在在 `BEGIN TRANSACTION` 后调用 `_resolve_publish_preconditions()` 和 `_b2_recheck()`；snapshot / artifact / feature set / run / universe / validation head / seal / component bytes 的权威读取都发生在事务内，写入只消费事务内事实。

满足 Option A，冻结。

## 1.3 Logical-URI Confinement —— VERIFIED / FREEZE

validator 与 publish final recheck 都已回到 frozen：

```python
physical_from_logical_uri(data_root, uri)
```

不再直接 `Path(data_root) / uri`。恶意 logical URI 对抗测试覆盖 data_root 外 perfect sentinel，冻结。

## 1.4 Manifest Check Rename —— VERIFIED / FREEZE

`ARTIFACT_MANIFEST_PRESENT_AND_SEALED` 与实际证明能力一致；exact component integrity 继续由 component manifest seal + COMPONENT_* checks 负责。冻结。

---

# 2. 唯一剩余 P0：Execution Proof 仍是 Caller Assertion

R4-B2.1 的目标是解决：

```text
bad-fact table empty
!=
scan actually ran and found zero issues
```

新增 `meta_artifact_check_execution` 的方向是对的，但当前生产 API：

```python
record_artifact_check_execution(
    conn,
    feature_artifact_set_id=...,
    check_id=...,
    scan_contract_version=...,
    producer=...,
    scanned_component_manifest_hash=...,
)
```

**并不执行任何 scan。**

它只校验字符串非空 / check_id 在两个 DQ check 中，然后直接：

```text
INSERT INTO meta_artifact_check_execution
```

因此调用者完全可以：

```text
1. 从 registry 读取当前 components
2. 调用公开 compute_component_manifest_hash() 得到 current hash
3. record_artifact_check_execution(
       check_id="IDENTITY_FALLBACK_ZERO",
       scan_contract_version="anything-nonempty",
       producer="anything-nonempty",
       scanned_component_manifest_hash=current_hash,
   )
4. 对 BLOCKING_DQ_ZERO 重复一次
5. 不写任何 bad finding
6. validate_artifact_for_publish()
7. 两项 DQ check PASS
```

这不是 positive execution proof，而是：

```text
caller self-declare “I executed the scan”
```

它与此前已经关闭的两类绕过是同构的：

```text
B1: caller self-declare APPROVED
B2: caller self-declare 0 counts
B2.1 current: caller self-declare scan executed
```

不能因为 row 不包含 `count/result/status` 就认为不可伪造；“scan 是否执行”本身就是决定 PASS 的关键事实。

## 2.1 当前 mock 路径实际证明了这个问题

`mock_e2e.py` 并没有执行 identity-fallback scan 或 blocking-DQ scan。它只是：

```text
读取 component rows
-> 自己 compute_component_manifest_hash
-> 对两个 check 调 record_artifact_check_execution
-> validate_artifact_for_publish
```

因此当前 happy path 正是在使用“声明执行记录”获得 PASS，而不是以实际 scanner 结果获得 PASS。

## 2.2 scan contract 也没有被执行端固定 / 消费端验证

当前 `record_artifact_check_execution()` 只要求 `scan_contract_version` 非空；validator 读取 proof 后只检查：

```text
proof.scanned_component_manifest_hash == current_component_manifest_hash
```

但没有要求：

```text
proof.scan_contract_version == CURRENT DQ_SCAN_CONTRACT_VERSION
```

`producer` 也只需要非空，没有与实际 checker implementation / code identity 绑定。

因此：

```text
scan_contract_version="fake-v0"
producer="attacker"
current manifest hash
```

仍可成为 PASS 前置条件。

本项 P0。

---

# 3. R4-B2.2 必须采用的结构：Execution Proof 必须是 Scanner 的内部产物

不要继续为 `record_artifact_check_execution()` 增加更多 caller 参数或 metadata 字段。

正确结构应是：

```text
run_required_artifact_dq_scan(...)
  -> resolve CURRENT artifact/component identity itself
  -> resolve CURRENT supported checker/scan contract itself
  -> ACTUALLY execute the required check against authoritative input
  -> derive findings from scan result
  -> persist any findings
  -> write execution-completion proof LAST
  -> commit / return
```

然后：

```text
validate_artifact_for_publish()
  -> consumes only completion proof produced by governed scanner
  -> proof exact artifact identity == current
  -> proof current scan contract == supported scan contract
  -> derive findings/counts
  -> PASS / FAIL / NOT_TESTABLE
```

关键不是函数名，可以调整；必须满足下面的结构性要求。

---

# 4. P0 Exit Requirements

## 4.1 删除 production caller-facing completion writer

生产 `src` 中不得继续暴露一个 callable 可以直接制造：

```text
meta_artifact_check_execution row
```

而不执行真实 scan。

因此当前：

```python
record_artifact_check_execution(...)
```

应：

- 从 production API 移除；或
- 变成只存在于 scanner 内部、且不能由 caller 提供 completion identity 的实现细节。

仅改成 `_record_*` 下划线不算关闭，B1.1 已经证明 Python 私有命名不是访问控制。

测试 fixture 若需要直接构造 execution row，应放在 `tests/`，不得为了测试便利保留 production bypass。

## 4.2 Scanner 自己计算 identity，caller 不得提交 scanned manifest hash

governed scanner 必须自己从 CURRENT registry 解析 components 并计算：

```text
scanned_component_manifest_hash
```

caller 不得把该 hash 作为“我扫了这些数据”的证明提交给 completion writer。

## 4.3 Scan contract / checker identity 必须 system-derived

至少要求：

```text
scan_contract_version == CURRENT DQ_SCAN_CONTRACT_VERSION
checker_id / checker_version / producer identity = system-derived
```

不能继续接受任意 caller-supplied non-empty string。

validator 应对 current contract fail closed：

```text
old / unknown / mismatched scan contract proof
-> NOT_TESTABLE / re-scan required
```

## 4.4 Completion proof 必须在 scan 真正完成后最后产生

最小顺序：

```text
BEGIN governed scan operation
  resolve exact input identity
  execute checker
  persist all detected findings
  persist scan evidence / details if required
  INSERT execution-completion proof LAST
COMMIT
```

如果 scanner：

```text
not implemented
throws
cannot read required input
cannot objectively establish the check
```

则不得写 completion row；validator 后续必须看到：

```text
NO compatible completion proof
-> NOT_TESTABLE
-> publish BLOCK
```

严禁 no-op scanner 为了让测试变绿直接写“completed”。

## 4.5 “真实 scan”必须有可说明的 authoritative input

对每个 DQ required check，scanner 必须明确它实际读取什么来判定：

```text
IDENTITY_FALLBACK_ZERO
BLOCKING_DQ_ZERO
```

如果当前系统尚不存在足以客观判定某 check 的 authoritative input，则本批**不要伪造扫描逻辑**；该 check 在 production 中应保持 NOT_TESTABLE，直到真正的 checker 数据链存在。

B2 correctness 的要求是：

```text
不能错误 PASS
```

不是为了在尚无客观数据时强行制造 production PASS。

Production P0-M-1B 本来就独立 BLOCKED，因此 fail-closed 不构成阶段阻塞理由。

---

# 5. 推荐最小设计

推荐：静态 typed checker registry + governed execution boundary。

示意：

```text
ArtifactDQCheckId
  IDENTITY_FALLBACK
  BLOCKING_DQ

ArtifactDQCheckerSpec
  check_id
  contract_version
  checker_version
  evaluator   # production-owned static function

run_artifact_dq_checks(conn, data_root, artifact_set_id)
  -> static registry lookup
  -> compute current component manifest internally
  -> evaluator(actual persisted input)
  -> persist findings derived from evaluator
  -> completion row LAST
```

注意：

- registry 不得是 caller 可注入 evaluator 的普通参数；
- caller 不得传 `passed=True` / `count=0` / `findings=[]` / `manifest_hash=...`；
- evaluator 若不可执行，返回 NOT_TESTABLE / raise，且没有 completion proof；
- completion proof 应记录 system-derived checker/contract identity；
- validation 只消费当前 supported checker contract 的 compatible completion proof。

若不采用 registry，也可以采用两个明确的 production scanner 函数；原则相同。

---

# 6. 必须增加的对抗测试

至少覆盖：

```text
1. production src 不存在 caller-facing record_artifact_check_execution bypass

2. caller 自己 compute current component_manifest_hash
   -> 无 API 可以直接写“scan completed”

3. no actual scan / no completion proof / zero bad findings
   -> DQ required check NOT_TESTABLE
   -> publish BLOCK

4. scanner throws before completion
   -> completion row count == 0
   -> validation NOT_TESTABLE

5. scanner detects a finding
   -> finding persisted
   -> completion written only after finding persistence
   -> validation FAIL

6. scanner genuinely runs and finds zero
   -> compatible completion proof exists
   -> validation DQ check PASS

7. component changes after successful scan
   -> old proof stale
   -> NOT_TESTABLE / rescan required

8. scan contract version evolves
   -> old proof no longer satisfies current validator
   -> NOT_TESTABLE / rescan required

9. arbitrary/unknown producer or checker version cannot satisfy current contract

10. one of the two required DQ scanners unavailable
    -> corresponding check NOT_TESTABLE
    -> publish BLOCK

11. existing B2.1 full seal / transaction / URI tests remain green

12. full CI matrix remains green
```

建议增加 structural/AST guard：

```text
production src 中所有 INSERT INTO meta_artifact_check_execution
只能位于实际 governed scan execution boundary 内；
该 boundary 的公开签名不得接受：
  scanned_component_manifest_hash
  result/status/pass
  finding_count/count
  completed_at
```

如果 producer/checker identity 由函数参数传入，也应视为未闭合，除非它只是从受控 static registry 中选 checker_id，而不是 caller 声明 provenance。

---

# 7. ADR / Governance Correction

ADR-021 Amendment E.2 当前写：

```text
meta_artifact_check_execution 记录某 governed scan 确实执行过
```

但 current runtime truth 只是：

```text
caller 可以调用 record_artifact_check_execution 写一行 execution metadata
```

因此下一批必须继续 **append amendment/correction**，不能删除历史：

```text
R4-B2.1 Reviewer REOPENED
execution-row presence != governed scanner execution truth
R4-B2.2 actual scan boundary closure
```

管理总册同步：

```text
R4-B2     DONE / REOPENED
R4-B2.1   DONE / REOPENED（P0-02/03/04 + P1 PASS/FREEZE；execution truth 未闭合）
R4-B2.2   ACTIVE NEXT
CR-2      BLOCKED_BY_R4-B2.2
Production P0-M-1B BLOCKED independently
```

DEVLOG append-only，记录：

```text
why: execution row remained caller-assertable
how: scanner owns execution + findings + completion
alternatives rejected: private helper / metadata-only proof / no-op scanner
cost/benefit
exact implementation SHA + job-level CI truth
```

本 Reviewer 由于 GitHub connector 对巨大 living document 的安全整文件重写成本过高，本次以本 focused reviewer document 作为仓库权威复审要求；下一开发提交必须同步 `docs/project/DEVELOPMENT_MANAGEMENT.md` / `docs/DEVLOG.md` / ADR-021 amendment。

---

# 8. R4-B2.2 Exit Gate

只有以下全部成立，Reviewer 才会直接：

```text
R4-B2 / B2.1 / B2.2 -> VERIFIED / CLOSED / FREEZE
CR-2 -> START
```

Exit Gate：

```text
[ ] execution completion cannot be caller-declared through production API
[ ] actual governed scanner executes before completion proof exists
[ ] scanner computes exact artifact/component identity internally
[ ] scan contract/checker provenance is system-derived and current-contract checked
[ ] zero findings without actual scan -> NOT_TESTABLE, never PASS
[ ] scanner failure/unavailability -> no completion proof -> NOT_TESTABLE
[ ] actual finding -> persisted -> validation FAIL
[ ] genuine zero scan -> PASS
[ ] stale component identity -> rescan required
[ ] stale scan contract/checker identity -> rescan required
[ ] B2.1 full seal consumption remains intact
[ ] B2.1 transaction-internal final recheck remains intact
[ ] frozen logical-URI confinement remains intact
[ ] manifest check honest-name semantics remains intact
[ ] append-only validation history / latest-head / atomic rollback remain intact
[ ] R4-B1/A3/A2/CR-1 frozen contracts show no regression
[ ] full required CI matrix green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR-021 match runtime truth
```

本批之后不再扩展 B2 范围。若上述 exit gate 全部通过，直接进入 **CR-2 Provider-Normalized + Quarantine**。

---

# 9. Implementation Mapping（开发方填写，2026-08-31）

## §4 P0 Exit Requirements

| Requirement（§4.1-4.5） | Implementation | Tests |
|---|---|---|
| §4.1 删除 production caller-facing completion writer | `record_artifact_check_execution` **从生产命名空间删除**（artifact_validation / artifact_dq_scan / pipeline package / publish module 均无此属性）；production 中 `INSERT INTO meta_artifact_check_execution` 唯一出现在 `run_required_artifact_dq_scan`（AST 守卫） | test_execution_proof_api_carries_no_result_params（重写：hasattr ×4 + 唯一 INSERT + 签名断言）+ test_no_caller_facing_completion_writer_in_production |
| §4.2 scanner 自己计算 identity | `run_required_artifact_dq_scan` 内部 `_resolve_components` + `compute_component_manifest_hash`；签名无 scanned_component_manifest_hash 参数 | test_caller_computed_manifest_cannot_declare_completion（复现 Reviewer §2 攻击：读 registry + 公开 hash 计算——无 API 可写 completion；合法路径只有 scanner，它不接受 manifest） |
| §4.3 contract / checker identity system-derived | completion row 的 scan_contract_version = CURRENT `DQ_SCAN_CONTRACT_VERSION`（"dq-scan-b2.2-v1"）；producer = `artifact-dq-scanner/{check_id}@{checker_version}`（registry 派生）；validator 三重校验（proof contract != CURRENT → NOT_TESTABLE；producer != system-derived → NOT_TESTABLE） | test_fake_producer_or_contract_cannot_satisfy_validator（raw INSERT fake contract + fake producer → 双 NOT_TESTABLE）+ test_scan_contract_version_evolution_requires_rescan |
| §4.4 completion proof 在 scan 真正完成后最后产生 | scan 单事务：evaluator 执行 → findings persist → completion INSERT LAST → COMMIT；evaluator raise → ROLLBACK → 零 completion row | test_scanner_failure_writes_no_completion（monkeypatch evaluator raise → rows == 0 → NOT_TESTABLE → BLOCK） |
| §4.5 真实 scan 有可说明的 authoritative input | IDENTITY_FALLBACK evaluator：feature parquet security_id（distinct）× dim_security.identity_key_version（FALLBACK 或未注册 → finding，fail closed）；BLOCKING_DQ evaluator：snapshot 五 fact 表 quality_flags（blocking 集 = QualityFlag 减 IDENTITY_FALLBACK）。**未伪造任何扫描逻辑**——两 check 均有真实数据源 | test_scanner_detects_identity_fallback_finding（UPDATE dim_security 为 FALLBACK → 真实发现 → FAIL）+ test_scanner_detects_blocking_dq_finding（INSERT STALE_WINDOW fact 行 → 真实发现 → FAIL）+ test_unregistered_identity_is_a_finding |

## §5 推荐最小设计（static typed checker registry + governed boundary）

| 设计要素 | Implementation |
|---|---|
| ArtifactDQCheckId | StrEnum（IDENTITY_FALLBACK_ZERO / BLOCKING_DQ_ZERO——值与 validation required-check id 一致，migration 012 语义连续） |
| ArtifactDQCheckerSpec（check_id / contract_version / checker_version / evaluator） | dataclass（含 finding_class；producer property = system-derived checker 身份） |
| run_artifact_dq_checks → `run_required_artifact_dq_scan(conn, data_root, artifact_set_id)` | registry lookup → 内部 compute manifest → evaluator(actual persisted input) → persist findings → completion LAST（§5 顺序图逐项对应） |
| registry 非 caller 可注入 | 模块级 tuple `ARTIFACT_DQ_CHECKERS`（production-owned；测试 monkeypatch 仅用于注入 raise 的 evaluator 验证失败语义） |
| caller 不得传 passed/count/findings/manifest_hash | 签名 == {conn, data_root, feature_artifact_set_id}（AST 断言） |
| evaluator 不可执行 → NOT_TESTABLE / raise，无 completion proof | raise → 事务 ROLLBACK → 零 row → validator NOT_TESTABLE |
| completion proof 记录 system-derived checker/contract identity | contract + producer 如上；validator current-contract + checker-identity 校验 |
| validation 只消费当前 supported checker contract 的 compatible proof | 三重校验（contract / producer / manifest）任一不匹配 → NOT_TESTABLE |

## §6 必须增加的对抗测试（12 项）

1. production 无 caller-facing record_artifact_check_execution bypass ✓（多模块 hasattr + AST 唯一 INSERT 边界）
2. caller 自己 compute manifest → 无 API 写 completed ✓（签名断言 + 攻击复现测试）
3. no scan / no proof / zero findings → NOT_TESTABLE → BLOCK ✓（test_no_execution_proof_is_not_testable_and_blocks——B2.1 测试在新结构下零回归）
4. scanner throws → completion count == 0 → NOT_TESTABLE ✓（test_scanner_failure_writes_no_completion）
5. scanner detects finding → persisted → completion 只在 finding 持久化后写 → validation FAIL ✓（两个真实检测测试；顺序由单事务结构保证）
6. genuinely runs and finds zero → PASS ✓（test_genuine_zero_scan_passes_and_publishes：proof contract/producer 断言 + publish 成功）
7. component changes after scan → stale → rescan ✓（test_stale_proof_blocks_after_component_change——B2.1 零回归）
8. contract version evolves → old proof 不满足 → rescan ✓（test_scan_contract_version_evolution_requires_rescan）
9. arbitrary/unknown producer 或 checker version 不满足 ✓（test_fake_producer_or_contract_cannot_satisfy_validator）
10. 两个 required scanner 之一 unavailable → NOT_TESTABLE → BLOCK ✓（monkeypatch 单 evaluator raise → 该 check 零 proof）
11. B2.1 full seal / transaction / URI tests remain green ✓（47 项既有测试全部通过，含 confinement 六项 attacker re-seal 场景适配）
12. full CI matrix green——推送后正向确认（见下）

## §6 AST/structural guard

production src 中所有 INSERT INTO meta_artifact_check_execution 只能位于 governed scan execution boundary ✓；该 boundary 公开签名不得接受 scanned_component_manifest_hash / result / status / pass / finding_count / count / completed_at ✓（断言 arg set == {conn, data_root, feature_artifact_set_id}）；producer/contract 由 static registry 派生而非函数参数 ✓。

## §7 治理

- **ADR-021 Amendment R4-B2.2**（F.1-F.5）：REOPEN 事实 + E.2"execution-row presence != governed scanner execution truth"修正 + 收口结构 + authoritative inputs + scanner failure 语义 + 治理状态（历史保留）
- DEVELOPMENT_MANAGEMENT.md：头部（R4-B2.1 大部分 FREEZE + R4-B2.2 ACTIVE + CR-2 BLOCKED_BY_R4-B2.2）+ §40/§41 重写 + §61 DM-CR-20260831-061
- DEVLOG append-only 新条目（why / how / alternatives rejected（caller 参数加固 / metadata-only proof / no-op scanner）/ cost-benefit / SHA + CI 推送后回填）
- 未自称 VERIFIED；Exit Gate CI 项推送后勾选

## §8 Exit Gate 对照

```text
[✓] execution completion cannot be caller-declared through production API
[✓] actual governed scanner executes before completion proof exists
[✓] scanner computes exact artifact/component identity internally
[✓] scan contract/checker provenance system-derived + current-contract checked
[✓] zero findings without actual scan -> NOT_TESTABLE, never PASS
[✓] scanner failure/unavailability -> no completion proof -> NOT_TESTABLE
[✓] actual finding -> persisted -> validation FAIL
[✓] genuine zero scan -> PASS
[✓] stale component identity -> rescan required
[✓] stale scan contract/checker identity -> rescan required
[✓] B2.1 full seal consumption intact（9 项 seal 测试零回归）
[✓] B2.1 transaction-internal final recheck intact（8 项 precondition 测试零回归）
[✓] frozen logical-URI confinement intact（7 项 confinement 测试零回归，含 attacker re-seal 适配）
[✓] manifest check honest-name semantics intact
[✓] append-only validation history / latest-head / atomic rollback intact
[✓] R4-B1/A3/A2/CR-1 frozen contracts no regression（全量 858/0）
[ ] full required CI matrix green（推送后正向确认回填）
[✓] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR-021 match runtime truth
```

## Verification Summary

- Local: **858 / 0**（848 → 858，+10）；ruff check / ruff format --check / mypy 全绿；CI 同款命令 `uv run pytest` 复验 858/0
- migration 012 表结构不变（列已够）；未新增 migration
- 本批之后不再扩展 B2 范围；Exit Gate 全过 → CR-2 START
