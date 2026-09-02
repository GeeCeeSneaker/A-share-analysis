# A-share-analysis：CR-3.3 复审与 CR-3.4 最终 Continuity Seal / Verification Replay 收口要求

> **Review Date**：2026-09-02 10:22 +08:00  
> **Reviewed Repository HEAD**：`b5fdc27b9f2fd9c262c7dc6dae9aa665b9494bc1`  
> **Primary CR-3.3 Implementation**：`f8b80b3212ff299f52ee3fb0308c248fd16c17df`  
> **Reviewer Baseline / Requirements**：`9ec2fcad9d10c19834a0042f0ebb0f07f8cfc5a9`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **CR-3.3 已正确部分**：**绝大部分 PASS / FREEZE**  
> **Next Batch**：**CR-3.4 Final Historical Canonical Seal Trust + Verification Evidence Replay Symmetry**  
> **ADR-023**：**PROPOSED / NOT ACCEPTED**  
> **CR-4**：**BLOCKED_BY_CR-3.4**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-3.3 已经正确解决上一轮最主要的两类问题，以下机制本轮正式 **PASS / FREEZE**，CR-3.4 不得推倒重写：

```text
PASS / FREEZE  canonical_context_hash 把 request-world 与 current input set / verification state 分离
PASS / FREEZE  historical continuity guard 按 context 查历史 non-BLOCKED canonical runs
PASS / FREEZE  prior sealed CR-2 run DELETE -> DAMAGED（正常未篡改 historical seal 情况）
PASS / FREEZE  prior CR-2 status drift -> DAMAGED
PASS / FREEZE  prior CR-2 manifest uri/hash / mapper / semantic seal drift -> DAMAGED
PASS / FREEZE  prior CR-2 physical / anchor degradation -> DAMAGED
PASS / FREEZE  current input superset 合法产生新 canonical world
PASS / FREEZE  exact restoration 可恢复 historical replay
PASS / FREEZE  identity master 同样进入 continuity guard
PASS / FREEZE  verification_problem_hash 进入 InputRunSeal / input_seal / verification_state
PASS / FREEZE  同 error class 不同 anchor/closure cause 产生新的 BLOCKED evidence run（现有覆盖路径）
PASS / FREEZE  exact same anchor/closure failure 可 idempotent replay（现有覆盖路径）
PASS / FREEZE  source finding reserved scope input:<surface> + affected_domains
PASS / FREEZE  damaged != unavailable 的 finding precedence
PASS / FREEZE  InputRunSeal 21 / identity_dict 17 的治理计数修正
PASS / FREEZE  migration 021 additive；018/019/020 未改写
PASS / FREEZE  implementation 1116/0；current HEAD CI 三平台全绿
```

Current docs HEAD `b5fdc27...` GitHub Actions run `33582260013`：Windows 3.12 / Windows 3.14 / Ubuntu 3.14 全 success，Ruff / Format / Mypy / Pytest / Spike gates 全绿。

但继续按 CR-3.3 自己定义的 adversarial / rebind trust model 审查，仍有 **3 个 P0 correctness blockers**。其中 P0-01 会直接绕过 CR-3.3 的核心 Historical Input Continuity；P0-02 会造成 materialization-only failure 的 first-run/replay evidence 不对称；P0-03 是 Canonical manifest full-seal 的显式 correctness identity 字段未完全消费。

正式状态：

```text
CR-2 / 2.1 / 2.2 / 2.3 / 2.4     VERIFIED / CLOSED / FREEZE
CR-3                                DONE / REOPENED
CR-3.1                              DONE / REOPENED（已吸收）
CR-3.2                              DONE / REOPENED（已吸收）
CR-3.3                              DONE / REOPENED（主体 PASS / FREEZE）
CR-3.4                              START / ACTIVE NEXT
ADR-023                             PROPOSED
CR-4                                BLOCKED_BY_CR-3.4
Production P0-M-1B                  BLOCKED independently
```

---

# 1. P0-01：Historical Continuity Guard 仍信任可被 rebind 的历史 Canonical input list

## 1.1 当前实现的正确部分

`canonical_context_hash` 的方向正确：它不包含 current input set / verification state，因此 CR-2 ledger run DELETE / status drift / seal drift 不会让历史 SUCCESS 从 continuity 查询范围中消失。

`_check_historical_continuity(snapshot)` 也会：

1. 按 `canonical_context_hash` 找历史 non-BLOCKED canonical run；
2. 读取历史 canonical manifest；
3. 遍历 `manifest.input_normalized_runs`；
4. 对每个 prior CR-2 run 检查 current ledger existence / seal identity / physical+anchor health / current discovery presence。

正常历史 manifest 未被重新绑定时，这条链已经能正确阻断 CR-2 DELETE / drift。

## 1.2 仍存在的 trust gap

但 `_continuity_problems_for()` 当前在把历史 `manifest.input_normalized_runs` 当成“历史真实 consumed input set”之前，只检查：

```text
manifest file exists
sha256(manifest bytes) == meta_canonicalization_run.manifest_hash
JSON readable
```

它没有先证明：

```text
historical manifest.input_normalized_runs
 -> recomputed input_seal_hash == historical ledger.input_seal_hash
 -> recomputed input_set_hash == historical ledger.input_set_hash
 -> manifest canonical_run_id / status / requested domains / context / base / state
    == historical canonical ledger seal
```

因此 rebind 路径成立：

```text
C1 historical SUCCESS originally consumed CR-2 A + B

1. edit C1 manifest.input_normalized_runs: remove A
2. recompute C1 manifest bytes hash
3. UPDATE meta_canonicalization_run.manifest_hash = new hash
   (leave historical input_seal_hash / input_set_hash unchanged)
4. DELETE CR-2 A from meta_provider_normalization_run
5. invoke same canonical context
```

当前 continuity guard：

- outer manifest hash passes（因为 ledger.manifest_hash 一起被改）；
- historical input list no longer contains A；
- therefore it never checks A disappearance；
- historical dependency A has been laundered out of continuity evidence。

这直接违反 CR-3.3 P0-01：**历史 SUCCESS 的已消费输入不能通过 Canonical manifest+ledger outer-hash rebind 被“遗忘”。**

## 1.3 Required Closure

Continuity Guard 在信任 prior `input_normalized_runs` 前，必须先验证一个 **Historical Canonical Run Seal**，至少：

```text
ledger canonical_run_id
ledger status
ledger requested_domains_json/hash
ledger canonical_context_hash
ledger base_identity_hash
ledger verification_state_hash
ledger input_set_hash
ledger input_seal_hash
ledger identity_dataset_hash
ledger identity_master_input_set_hash
ledger policy identities
ledger code_fingerprint
ledger manifest_uri/hash

== historical manifest explicit fields
== recompute(manifest.input_normalized_runs)
```

其中必须物理重算：

```text
historical_input_seal_hash = hash(canonical JSON of manifest input entries full seal)
historical_input_set_hash  = hash(canonical JSON of manifest input identity subset)
historical_verification_state_hash = hash(run_id + verification + verification_problem_hash)
```

若 prior canonical manifest / ledger 自己已经 DAMAGED：

```text
HARD DAMAGED
no replacement may be minted
```

不得继续用这份 manifest 的 input list 做 continuity 判断。

推荐把 CR-3.2/3.3 现有 replay full-seal comparison 中可复用部分抽成 typed `CanonicalRunSeal` / `_verify_historical_canonical_seal()`，避免 continuity 再维护第二套较弱验证器。

### Mandatory adversarial tests

1. SUCCESS A+B -> edit historical manifest input list remove A -> rehash manifest + update only ledger.manifest_hash -> DELETE CR-2 A -> same context MUST DAMAGED / zero new canonical run。
2. Same but alter one prior input seal field in manifest + rebind manifest_hash -> continuity MUST DAMAGED before trusting input list。
3. Rebind historical manifest `input_seal_hash` field + outer hash only -> DAMAGED。
4. Rebind historical manifest `input_set_hash` / `verification_state_hash` / `base_identity_hash` / `canonical_context_hash` + outer hash -> DAMAGED。
5. Healthy untouched historical manifest + legitimate new CR-2 input superset -> still allowed new canonical run（positive control）。

---

# 2. P0-02：materialization-only failure 的 verification evidence first-run / replay 不对称

## 2.1 当前实现

`_snapshot_run()` 的 problem evidence 正确包含：

```text
run_id
verification
closure_problems
anchored_evidence_problems
materialization_problems
```

并把 hash 写入 `InputRunSeal.verification_problem_hash`。

当：

```text
verify_normalized_run() passes
anchor passes
_materialize_outputs() fails
```

当前 snapshot 会：

```text
verification = CLOSURE_FAILED
materialization_problems = [actual problem]
verification_problem_hash = H(materialization problem included)
```

这条路径是现实存在的 TOCTOU protection path：CR-3.2 明确要求 closure verify 后 materialize SAME exact bytes；文件可能在两步之间被换掉，materialization recheck 必须能独立失败。

## 2.2 replay 不对称

`_verify_sealed_input()` 对 INVALID sealed input 当前重新计算：

```text
closure_problems = verify_normalized_run(...)
anchor_problems = ...
materialization_problems = []   # hard-coded
```

因此它没有能力重建 first-run seal 中的 materialization problem evidence。

DEVLOG/implementation rationale 写“INVALID seal 会短路 materialization，所以 replay materialization problems 恒空”，但生产代码实际不是这样：**run 可以先 HEALTHY，通过 closure+anchor 后在 `_materialize_outputs()` 才变为 CLOSURE_FAILED。**

结果：

- first-run seal 可以包含 non-empty `materialization_problems`；
- replay invalid verifier 永远构造 empty materialization list；
- exact evidence hash 无法对称重建。

## 2.3 Required Closure

必须让 **first consume 与 replay 共用同一 verification evidence collector / state machine**。

推荐：

```text
_collect_input_verification_evidence(run identity, role, as_of, materialize_mode)
 -> closure problems
 -> anchor problems
 -> if closure+anchor healthy: exact-byte materialization verify
 -> materialization problems
 -> derived verification enum
 -> canonical problem evidence
 -> problem hash
```

first-run 可额外返回 materialized rows；replay 可丢弃 rows，但必须运行同一 verification sequence / semantics。

不能存在两份“看起来类似但 problem evidence 字段不同”的逻辑。

### Mandatory tests

1. monkeypatch / second actor：让 CR-2 closure verify 通过后、Canonical materialization 前替换 output bytes -> first canonical BLOCKED，seal `materialization_problems` non-empty。
2. 保持该 exact physical failure，不做其它改变 -> next invocation 的行为必须符合定义的 exact evidence semantics；不得因 replay verifier 固定 `materialization_problems=[]` 产生自相矛盾。
3. 恢复 exact bytes -> recovery semantics 正确；历史 BLOCKED evidence 保留。
4. materialization failure cause A -> cause B -> problem hash/run identity 按 exact evidence 变化。

---

# 3. P0-03：Canonical manifest 仍有 correctness identity 字段“写入但 replay 不消费”

当前 `_write_artifacts()` manifest 显式写入：

```text
canonical_context_hash
base_identity_hash
verification_state_hash
```

但 `_verify_closure()` 的 manifest <-> ledger field-by-field comparison 当前没有这三个字段。

虽然 replay 的 `expected_provenance` 会比较：

```text
ledger field == current snapshot
```

但这不能证明：

```text
manifest explicit field == ledger/current
```

因此仍存在：

```text
edit manifest.canonical_context_hash/base_identity_hash/verification_state_hash
-> rehash manifest
-> update ledger.manifest_hash
-> other ledger correctness fields unchanged
```

manifest 会自相矛盾但 verifier 可能继续通过。

这与 CR-3.2/CR-3.3 已确立的规则冲突：**所有显式 correctness provenance 字段都必须被消费，不允许 display-only seal。**

## Required Closure

把以下至少加入 manifest typed binding：

```text
canonical_context_hash == ledger == current recompute
base_identity_hash == ledger == current recompute
verification_state_hash == ledger == current recompute
```

并增加 rebind tests：每个字段单独改 manifest + update outer manifest_hash，replay 必须 DAMAGED。

同时结合 P0-01，continuity 使用 historical manifest 前也必须消费这些字段，而不是只在 normal exact replay 中消费。

---

# 4. CR-3.4 Scope Boundary

CR-3.4 只允许修改：

```text
src/ashare_state/canonical/canonicalizer.py
migrations/022_*（仅当确有必要；优先不新增 schema）
tests/integration/test_canonical.py
tests/integration/test_migrations.py（仅 schema 变化时）
ADR-023 Amendment D
DEVLOG
DEVELOPMENT_MANAGEMENT
本工作要求 Implementation Mapping
```

禁止进入：

- CR-4 SnapshotBuilder；
- DuckDB ReadModel rebuild；
- Feature / State；
- Provider / Normalization 新业务语义；
- Availability / SourcePolicy 新行为；
- 新 provider fallback；
- production account / Golden / Trading Rule 人工裁决。

CR-3.3 已 PASS/FREEZE 的 transaction snapshot / PIT master / policy execution / continuity context / normal CR-2 ledger drift guard / finding truthfulness 不得推倒重写。

---

# 5. CR-3.4 Exit Gate

全部满足后才允许关闭 CR-3 全链：

```text
[ ] historical canonical manifest 在 continuity 使用前做 typed full-seal verify
[ ] prior input list 不能通过 manifest + ledger outer-hash rebind 被改写
[ ] historical input_seal_hash 从 manifest entries 物理重算并与 ledger 比较
[ ] historical input_set_hash 从 manifest entries identity subset 物理重算并与 ledger 比较
[ ] historical verification_state_hash 从 manifest entries 物理重算并与 ledger 比较
[ ] canonical_context/base/state 三 identity manifest == ledger == recompute
[ ] prior canonical manifest/ledger damaged -> HARD DAMAGED，zero replacement
[ ] legitimate healthy superset additions 仍允许新 run
[ ] first-run/replay 共用对称 verification evidence semantics
[ ] materialization-only problem 可被 replay verifier 精确重建/判定
[ ] exact materialization failure repeat 不产生自相矛盾
[ ] materialization cause change 产生新的 exact evidence identity
[ ] exact repair recovery 正确且历史 BLOCKED 保留
[ ] CR-3.3 historical continuity existing 11 tests remain green
[ ] CR-3.3 verification/finding/count existing tests remain green
[ ] CR-3.2 transaction/PIT/policy/full seal frozen regression remain green
[ ] CR-2.x / R4 frozen chain remain green
[ ] migration from-zero / upgrade / idempotent green if schema changes
[ ] Windows 3.12 + Windows 3.14 + Ubuntu 3.14 full CI green
[ ] ADR-023 remains PROPOSED until Reviewer closure
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT synchronized
```

若以上全通过，Reviewer 下一步直接：

```text
CR-3 / CR-3.1 / CR-3.2 / CR-3.3 / CR-3.4 -> VERIFIED / CLOSED / FREEZE
ADR-023 -> ACCEPTED
CR-4 SnapshotBuilder + DuckDB ReadModel Rebuild -> START
```

---

# 6. Owner View

当前不是 Canonical 主体功能不足。CR-3.3 已把“历史成功依赖不能因为 CR-2 ledger 漂移而被忘掉”这一大方向修正确；本轮剩余问题集中在 **谁有资格证明历史 input list 是真的**，以及 **失败证据是否能 first-run/replay 用同一把尺子重建**。

```text
Canonical 主体转换                PASS
PIT 行情                           PASS
PIT identity master                PASS
Transactional materialized snapshot PASS
Honest SourcePolicy execution       PASS
Canonical artifacts/full replay     PASS 主体
Historical input continuity         PASS 主体

CR-3.4 final:
  historical Canonical seal trust   FIX
  materialization evidence symmetry FIX
  context/base/state manifest bind  FIX
```

这是 CR-3 关闭前最后一层“历史审计证据本身也不能被重新绑定”的收口。

---

# 7. Implementation Mapping（CR-3.4，2026-09-02）

> Reviewed base：CR-3.3 复审 reopen commit `33d0901`（本工作要求）；implementation commit `fce2ca43a35b95d61dc390647fdc46d844d9b1a5`（GitHub Actions **run 33591527697 三腿 success**，2026-09-02 API positive confirmation：Windows 3.14 + Windows 3.12 + Ubuntu 3.14 各腿 Ruff lint / Ruff format / Mypy / Pytest / Spike gates / SDK-absent / DEVLOG gate / Management-doc gate 全 success，一次通过零修复轮次）。总体 **1136/0**（1116 → 1136，+20 项对抗测试）；ruff check / ruff format / mypy 全绿；**零新 migration**（§4 允许范围内刻意决策：三收口全部为 canonicalizer runtime 侧，020/021 已有全部所需列，migration 链保持 21）。

## 7.1 P0-01 Historical Canonical Run Seal Trust

| 要求 | 实现 |
| --- | --- |
| typed `CanonicalRunSeal` | `src/ashare_state/canonical/canonicalizer.py` 新增 frozen dataclass `CanonicalRunSeal`（23 字段：canonical_run_id / canonical_contract_version / as_of / idempotency_key / status / requested_domains_json+hash / input_set_hash / input_seal_hash / identity_dataset_hash / identity_master_input_set_hash / canonical_context_hash / base_identity_hash / verification_state_hash / 三 policy version+hash / code_fingerprint / manifest_uri+hash），`from_ledger(record)` 构造；导出于 canonical `__init__` |
| `_verify_historical_canonical_seal()` | 同文件新方法：验证序列 = manifest_uri/hash 非空 → deterministic manifest URI（`_expected_base_uri` + `/manifest.json`）→ 文件存在 → bytes hash == ledger.manifest_hash → JSON 可读 → 20 组 manifest 显式 correctness 字段 == ledger seal → requested_domains == json.loads(ledger json) → `input_normalized_runs` 是 list → 三 hash 物理重算 == ledger。任何 problem → 返回 `(None, problems)`，调用方不再用该 input list 做 continuity 判断 |
| historical_input_seal_hash 物理重算 | 模块函数 `_input_hashes_from_entries(entries)`（与 `CanonicalInputSnapshot` 同公式）：`sha256(_canonical_json(全 seal entries))` |
| historical_input_set_hash 物理重算（identity subset） | `_input_hashes_from_entries`：identity subset 由模块级 `_INPUT_IDENTITY_FIELDS`（17 字段 tuple，**单一事实源**）提取；`InputRunSeal.identity_dict()` 同步改为从该 tuple 构造（杜绝两套字段集各自演化） |
| historical_verification_state_hash 物理重算 | `_input_hashes_from_entries`：`sha256(_canonical_json([{run_id, verification, verification_problem_hash}]))` |
| prior manifest/ledger damaged → HARD DAMAGED，no replacement | `_check_historical_continuity`：seal verify 返回 problems 即并入该 prior run 的 continuity problems → `CanonicalRunnerError`（不 mint 任何 run；`_canonical_count` 断言保持） |
| continuity 使用历史 manifest 前消费（§3 要求） | `_check_historical_continuity` 的 SELECT 由 4 列扩为全 `_LEDGER_COLUMNS`；`_continuity_problems_for`（弱验证器）删除，per-input 检查逻辑保留为 `_continuity_problems_for_input`（不变，18 项 FREEZE 机制零重写） |

**Mandatory adversarial tests（§1.3）→ `tests/integration/test_canonical.py::TestHistoricalCanonicalSealTrust`（9 项）**

| 要求 | 测试 |
| --- | --- |
| 1. input list 去 A + rehash + ledger.manifest_hash + DELETE CR-2 A → DAMAGED / 零新 run | `test_input_list_rebind_then_cr2_delete_damaged`（重算 input_seal/input_set/verification_state 三 hash 均失配 → 在信任 input list 前 DAMAGED；`_canonical_count == 1`） |
| 2. 改一个 prior input seal 字段 + rebind → 信任 input list 前 DAMAGED | `test_input_entry_seal_field_rebind_damaged`（entry.mapper_code_hash 篡改 → 重算失配） |
| 3. manifest `input_seal_hash` 字段 + 外层 hash → DAMAGED | `test_manifest_input_seal_hash_field_rebind_damaged`（manifest 字段 != ledger seal） |
| 4. `input_set_hash` / `verification_state_hash` / `base_identity_hash` / `canonical_context_hash` + 外层 hash → DAMAGED | `test_manifest_identity_field_rebind_damaged`（4 参数 parametrize） |
| 5. 健康未动历史 manifest + 合法新 CR-2 superset → 允许新 run | `test_historical_manifest_seal_positive_superset`（`idempotent_replay is False`、新 run_id、`_canonical_count == 2`） |
| 补充：prior manifest 文件缺失 → HARD DAMAGED | `test_prior_manifest_missing_hard_damaged` |

## 7.2 P0-02 Verification Evidence Replay Symmetry

| 要求 | 实现 |
| --- | --- |
| `_collect_input_verification_evidence(run identity, role, as_of, materialize_mode)` | 同文件新方法 + frozen dataclass `InputVerificationEvidence`（closure_problems / anchored_evidence_problems / materialization_problems / verification / received_at / pit_available / verification_problem_hash / outputs）：closure verify → anchor verify →（closure+anchor 健康时）exact-byte materialization verify → derived enum → canonical problem evidence hash |
| first-run 额外返回物化行 | `_snapshot_run` 调用 collector（`keep_rows=True`）：findings 由 evidence 三组 problems 分别生成（closure / evidence / materialization——互斥语义与 CR-3.3 完全一致）；seal 的 verification / received_at / pit_available / verification_problem_hash 全部来自 evidence；`outputs=evidence.outputs` |
| replay 丢弃行但同一序列/语义 | `_verify_sealed_input` INVALID 分支以 sealed entry 重建完整 17 字段 run_row，调用同一 collector（`keep_rows=False`），比对 `evidence.verification_problem_hash == sealed verification_problem_hash`；删除原硬编码 `materialization_problems=[]` 的第二套 evidence 构造 |
| 不存在两套相似但字段不同的逻辑 | problem evidence dict 只在 collector 内构造一次（run_id / verification / closure_problems / anchored_evidence_problems / materialization_problems，全部 sorted） |

**Mandatory tests（§2.3）→ `TestMaterializationEvidenceSymmetry`（4 项）**：第二演员由 racy closure monkeypatch 模拟（restore exact good bytes → real closure verify 通过 → 再次损坏 output）：

| 要求 | 测试 |
| --- | --- |
| 1. closure 过、output bytes 换 → first run BLOCKED，seal materialization_problems 非空 | `test_materialization_only_failure_first_run_blocked`（断言 finding detail 含 bytes mismatch、entry.verification == CLOSURE_FAILED、`verification_problem_hash` == 测试内独立重算的 exact evidence hash——含非空 materialization_problems） |
| 2. exact physical failure 保持 → 下次调用符合 exact evidence semantics，无自相矛盾 | `test_exact_materialization_failure_idempotent_replay`（同一 BLOCKED run 幂等 replay，`_canonical_count == 1`——旧实现此处必报 evidence drift） |
| 3. exact bytes 恢复 → recovery 语义正确，历史 BLOCKED 保留 | `test_exact_repair_recovery_preserves_blocked_history`（新 SUCCESS run + BLOCKED 历史 append-only） |
| 4. cause A → cause B → problem hash / run identity 按 exact evidence 变化 | `test_materialization_cause_change_new_evidence_run`（bytes mismatch → artifact missing：两个不同 BLOCKED run，两种 cause 的 finding 并存） |

## 7.3 P0-03 Manifest Correctness Identity Binding

| 要求 | 实现 |
| --- | --- |
| canonical_context_hash == ledger == current recompute | `_verify_closure` 的 `expected_manifest` 增加 `("canonical_context_hash", ledger)`（manifest == ledger）——与既有 `expected_provenance`（ledger == current snapshot）构成三方闭环；`("base_identity_hash", ...)`、`("verification_state_hash", ...)` 同 |
| rebind tests：每字段单独改 manifest + update outer hash → replay DAMAGED | `TestManifestCorrectnessIdentityBinding::test_identity_field_rebind_replay_damaged`（3 参数 parametrize，SUCCESS run——由 continuity 历史 seal 消费拦截）；`test_identity_field_rebind_blocked_replay_damaged`（3 参数 parametrize，BLOCKED run——continuity 跳过，由 `_verify_closure` typed manifest binding 拦截）；`test_identity_fields_three_way_binding`（三方绑定 positive control：manifest == ledger == `_build_snapshot` 重算） |
| continuity 使用 historical manifest 前也消费（§3 末段） | §7.1 的 `_verify_historical_canonical_seal` expected_fields 显式包含三字段 |

## 7.4 Scope Boundary 合规

只修改：`src/ashare_state/canonical/canonicalizer.py`（+ `canonical/__init__.py` 导出，无行为）、`tests/integration/test_canonical.py`、ADR-023 Amendment D（§9.1-§9.5）、ADR-000 索引、`docs/DEVLOG.md`（追加条目；同时更正 CR-3.3 条目中“replay 恒空”的错误 rationale——历史原文保留，新条目内声明更正）、`docs/project/DEVELOPMENT_MANAGEMENT.md`（DM-20260902-072）、本 Mapping。**未新增 migration 022**（复审允许“仅当确有必要”）；未触碰 SnapshotBuilder / ReadModel / Feature / State / Provider / Policy / production 人工项；CR-3.3 FREEZE 的 18 项机制零重写（`_continuity_problems_for_input` / finding precedence / seal 结构原样，131 项回归全绿）。

## 7.5 Exit Gate 自检

```text
[x] historical canonical manifest 在 continuity 使用前做 typed full-seal verify      -> _verify_historical_canonical_seal（deterministic URI + bytes + 20 显式字段 + 三 hash 重算）
[x] prior input list 不能通过 manifest + ledger outer-hash rebind 被改写              -> TestHistoricalCanonicalSealTrust 1/2/3/4（重算锚定 ledger seal）
[x] historical input_seal_hash 从 manifest entries 物理重算并与 ledger 比较           -> _input_hashes_from_entries seal hash
[x] historical input_set_hash 从 entries identity subset 物理重算并与 ledger 比较     -> _input_hashes_from_entries identity hash（_INPUT_IDENTITY_FIELDS）
[x] historical verification_state_hash 从 entries 物理重算并与 ledger 比较            -> _input_hashes_from_entries state hash
[x] canonical_context/base/state 三 identity manifest == ledger == recompute          -> _verify_closure expected_manifest + expected_provenance 三方闭环 + 三方绑定测试
[x] prior canonical manifest/ledger damaged -> HARD DAMAGED，zero replacement          -> seal problems 并入 continuity raise；_canonical_count 断言
[x] legitimate healthy superset additions 仍允许新 run                                -> positive control 测试
[x] first-run/replay 共用对称 verification evidence semantics                        -> _collect_input_verification_evidence 唯一构造点
[x] materialization-only problem 可被 replay verifier 精确重建/判定                  -> INVALID 分支 collector（keep_rows=False）
[x] exact materialization failure repeat 不产生自相矛盾                              -> idempotent replay 测试（旧实现此处必报 drift）
[x] materialization cause change 产生新的 exact evidence identity                    -> cause A→B 双 run 测试
[x] exact repair recovery 正确且历史 BLOCKED 保留                                    -> recovery 测试 + append-only 断言
[x] CR-3.3 historical continuity existing 11 tests remain green                      -> 131 项回归全绿
[x] CR-3.3 verification/finding/count existing tests remain green                    -> 同上
[x] CR-3.2 transaction/PIT/policy/full seal frozen regression remain green           -> 同上
[x] CR-2.x / R4 frozen chain remain green                                            -> 全量 1136/0
[x] migration from-zero / upgrade / idempotent green if schema changes               -> N/A（零 schema 变化，21 链不变）
[x] Windows 3.12 + Windows 3.14 + Ubuntu 3.14 full CI green                          -> run 33591527697 三腿 success（2026-09-02 API positive confirmation，一次通过零修复轮次）
[x] ADR-023 remains PROPOSED until Reviewer closure                                  -> status 行保持 PROPOSED（Amendment D 追加）
[x] DEVLOG / DEVELOPMENT_MANAGEMENT synchronized                                    -> DEVLOG 新条目 + DM-20260902-072 + 头部/§40/§41/§44/§61
```