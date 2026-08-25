# A-share-analysis：R4-A2.8 / CR-1.2.4 复审结论与 R4-A2.9 / CR-1.2.5 开发工作要求

> **Review Date**：2026-08-25 16:26 +08:00  
> **Reviewed Repository HEAD**：`ada0eac2d973730605f7af65f57e72a22e1483c1`  
> **Previous Reviewer Requirement Commit**：`ba4a3eecaa0bcb6fd4699588f56584cc3108ab07`  
> **Frozen Baseline**：V1.3.2  
> **Review Scope**：R4-A2.8 Final Exchange-Boundary / Review-Lineage Closure、CR-1.2.4 Pre-Access Integrity、ADR-016、Trading Rule Human Review Seal、CI Matrix Truth、治理同步  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.9 Review-Seal Exactness / Cross-Platform CI Closure + CR-1.2.5 Output Confinement**  
> **CR-2**：**BLOCKED**  
> **R4-A3**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. 裁决摘要

本轮上一批要求的三个原始 P0 均已取得实质性闭环，允许冻结其主体设计：

```text
Golden Domain Atomic Exchange Persistence
→ provider call 与 RawWriter persist 合并进入 collector.call
→ 一次调用成功后先持久化，才允许下一次 provider call
→ 第二次调用失败时，第一次成功 exchange 已在 bundle 中
→ RawWriter persist 失败时，后续 provider call 不再发射

Bound Rule Lexical-First Confinement
→ root 不再根据 dataset_files[] 探测
→ traversal / absolute / drive / foreign-version 在 lexical 层先拒绝
→ symlink escape 只在 lexical 合法后进入 resolve 检查

Trading Rule Review Input Integrity Gate
→ review.py preflight 已改为 load_active_rules()
→ ACTIVE dataset hash / manifest↔dataset coherence 先验证
→ tampered ACTIVE / hash mismatch / metadata mismatch 均在输出前 BLOCK
```

CI 方面，当前 HEAD 的 GitHub Actions **run 42 overall = success**；两个 required Windows legs（Python 3.12 / 3.14）通过。但 Reviewer 进一步下钻 job matrix 后确认：**Ubuntu Python 3.14 的 Pytest job 实际失败**，只是 workflow 通过 `continue-on-error` 将该 leg 标记为 non-required，因此不能表述为“全矩阵绿色”。

继续审查 `scripts/rules/review.py` 后，又确认两个会影响 Trading Rule immutable SoR 的 blocking correctness 问题：

```text
P0-01  Review seal 对 ACTIVE 输入进行了两次独立读取，
       hash 验证的 bytes 与最终封存为 REVIEWED 的 bytes 不保证是同一快照

P0-02  --version 未在任何输出 mutation 前做严格 path-component confinement，
       ../ / absolute / nested / drive-like 输入可能在 versions root 之外创建目录/文件
```

第一个问题会破坏“Reviewer 实际验证的字节 == 被封存字节”；第二个问题会破坏 version store 的输出边界。两者均位于人工 Review / immutable SoR 的正式封存工具链，不能带入 VERIFIED。

因此本轮正式裁决仍为 **REOPENED**。

---

# 1. 本轮已通过并冻结的实现

## 1.1 Golden Domain `collector.call()` 原子边界 —— PASS

当前 `_DomainCollector.call(fn)` 的正确语义是：

```text
fn() -> ProviderExchange
  ↓
ctx.evidence_from_exchange(exchange)
  ↓
RawWriter.write(exchange)
  ↓
collector._record(meta)
  ↓
才返回 exchange.payload / lineage
```

因此同一 domain 内：

```text
call A success
→ A persist complete
→ call B may start
```

而不是旧实现：

```text
call A
call B
persist A
persist B
```

`tests/integration/test_ca_atomic_boundary.py` 已覆盖：

```text
[PASS] dividend success + right_issue failure -> dividend meta 已存在
[PASS] right_issue failure -> kline 不再发射
[PASS] persist failure -> subsequent provider calls 不发射
[PASS] normalized CA view lineage 指向 exact persisted exchange
```

本项后续禁止回退为 assign-then-persist 静态放行模型。

## 1.2 Bound Rule lexical-first confinement —— PASS

当前：

```text
lexical relative-path checks
→ versions/<rule_version>/ structural check
→ resolve() only for lexically valid ref
→ symlink/root escape check
→ is_file/read/hash
```

`tests/integration/test_lexical_first_confinement.py` 已把 `resolve/is_file/read_bytes/open` 纳入 probe，证明 traversal / absolute / foreign-version 等 lexical-invalid 输入在 candidate filesystem resolution 前拒绝。

这一 contract 保留。

## 1.3 Trading Rule ACTIVE integrity preflight —— PASS

review 工具已从：

```python
load_rule_manifest(rules_root)
```

升级为：

```python
active_book, active_manifest = load_active_rules(rules_root)
```

因此 ACTIVE candidate 在进入人工 seal 流程前必须先通过：

```text
dataset hash
review_status
source_version
dataset_version
review_provenance coherence
```

现有 `test_review_input_integrity.py` 已覆盖 tampered bytes / tampered manifest hash / metadata mismatch 与 zero-output rejection。

此项主体通过；下面 P0-01 是 **seal snapshot exactness** 的更深一层问题，不回退这一 preflight。

## 1.4 上轮其它基础闭环继续冻结

本轮不重新打开：

```text
RawWriter persisted evidence identity
Raw meta anchor + payload bidirectional closure
full request_params lineage
run-bound Trading Rule exact replay
CA provider-native Raw + ephemeral semantic adapter
Golden typed CA truth
hidden calendar explicit prerequisite
B5/B6 ProbeExecutor boundary
```

---

# 2. P0-01：Trading Rule Review Seal 不是 Exact-Byte Snapshot

## 2.1 当前实现问题

当前 `scripts/rules/review.py` 的核心顺序仍类似：

```python
active_book, active = load_active_rules(rules_root)
...
active_bytes = active_path.read_bytes()
...
if _dataset_files_hash(rules_root, [active_rel]) != active.dataset_hash:
    BLOCK
...
reviewed output = transform(active_bytes)
```

这里存在两个独立 read：

```text
Read A -> active_bytes                 （最终用于生成 REVIEWED copy）
Read B -> _dataset_files_hash(...)     （用于和 manifest.dataset_hash 比较）
```

所以当前只能证明：

```text
Read B == ACTIVE manifest hash
```

不能证明：

```text
Read A == Read B
```

### 对抗场景

```text
T0: load_active_rules() 验证合法 V
T1: active_path 被替换为篡改 bytes T
T2: review.py Read A，捕获 T
T3: active_path 被恢复为合法 V
T4: _dataset_files_hash() Read B，hash(V) == manifest.dataset_hash -> PASS
T5: REVIEWED copy 却由 Read A 的 T 生成
```

结果：

```text
被 hash 验证的 bytes = V
被人工 seal 的 bytes = T
```

这违反 immutable review workflow 最基本的不变量：

> **The exact bytes validated against ACTIVE identity must be the exact bytes transformed and sealed into the REVIEWED version.**

ADR-016 / 当前实现说明若声称“exact ACTIVE bytes 被验证并封存”，需要做 Reviewer Correction，不能继续 overclaim。

## 2.2 强制修复

单文件 ACTIVE 的当前 Option A 下，推荐建立一次性 snapshot：

```python
active_bytes = active_path.read_bytes()
active_snapshot_hash = dataset_hash_from_snapshot(
    [(active_rel, active_bytes)]
)
if active_snapshot_hash != active.dataset_hash:
    BLOCK

# 后续 REVIEWED copy 只能使用 active_bytes
reviewed_bytes = build_reviewed_copy(active_bytes, ...)
```

关键要求：

```text
hash checked bytes
== bytes transformed
== bytes sealed provenance parent
```

从 snapshot 创建完成后，不得再为“确认”重新读取 ACTIVE 文件并用第二次 read 替代 snapshot 身份。

如果以后支持 multi-file，则 snapshot 必须是：

```text
[(rel_path, bytes), ...]
```

并对整组 snapshot 计算 manifest 算法的 combined hash。

## 2.3 Required Tests

至少增加：

```text
[ ] valid ACTIVE snapshot -> PASS
[ ] captured snapshot hash mismatch -> BLOCK before any output
[ ] mock / monkeypatch successive active-file reads return different bytes
    -> 工具不得出现“第二次 read 验证通过、第一次 read 被封存”的情况
[ ] reviewed output content must be derivable from EXACT hash-checked snapshot
[ ] mismatch -> no evidence artifact
[ ] mismatch -> no reviewed version dir
[ ] mismatch -> no manifest temp/final mutation
```

推荐让测试直接捕获：

```text
validated_snapshot_sha
review_source_snapshot_sha
```

并断言两者恒等，而不是仅断言最终脚本 exit code。

---

# 3. P0-02：`--version` 输出路径未受限于 Version SoR

## 3.1 当前问题

当前工具直接使用：

```python
version_dir = rules_root / "versions" / args.version
version_dir.mkdir(parents=True)
reviewed_path = version_dir / "rules.yaml"
```

但 `args.version` 在此之前没有被验证为**单一安全路径组件**。

危险/错误输入包括：

```text
../escape
../../escape
foo/bar
foo\bar
/absolute/path
C:\absolute-or-drive-like
.
..
```

在 Path join / normalization 下，其中部分输入可以逃出：

```text
rules_root/versions/
```

而且当前 mutation（mkdir/write/copy）可能发生在后续 manifest coherence gate 之前。

这违反：

```text
immutable version output
→ must always stay inside rules_root/versions/<one-version-id>/
```

## 3.2 强制修复

### Step A — lexical validation before ANY mutation

建议把 version id contract 明确为：

```text
one path component only
non-empty
not . / ..
no / or \
no drive prefix
no absolute path
```

可使用严格 allowlist：

```regex
^[A-Za-z0-9][A-Za-z0-9._-]*$
```

并额外拒绝 `.` / `..`。

### Step B — resolved confinement

在 `exists/mkdir/write` 之前：

```python
versions_root = (rules_root / "versions").resolve()
candidate = (versions_root / version_id).resolve()
candidate.relative_to(versions_root)
```

### Step C — no mutation before all deterministic validation passes

以下检查应全部早于 evidence copy / version mkdir：

```text
ACTIVE integrity
from-version lineage
input file == ACTIVE file
single-file support
ACTIVE COMPILED
version id lexical validation
version target confinement
version target non-existence
artifact readable/hashable
reviewer/kind required arguments
```

## 3.3 Required Tests

```text
[ ] --version ../escape -> reject, zero side effects
[ ] --version ../../escape -> reject, zero side effects
[ ] --version foo/bar -> reject
[ ] --version foo\bar -> reject
[ ] absolute path -> reject
[ ] Windows drive-like C:\... -> reject
[ ] . / .. -> reject
[ ] valid v20260825-reviewed -> output ONLY under versions/<id>/
[ ] unsafe value cannot create evidence artifact
[ ] unsafe value cannot create version dir outside versions root
[ ] unsafe value cannot touch ACTIVE manifest
```

本项应与输入 path confinement 使用同一安全设计语言：**lexical first, resolved confinement second, mutation last**。

---

# 4. P1：Review Workflow Staging / Failure Cleanup

当前 review workflow 已经比早期版本安全，但仍建议把所有输出 mutation 做成明确 staged flow。

推荐顺序：

```text
Phase 1 - pure validation / snapshot
  active integrity
  lineage
  version confinement
  snapshot exact hash
  artifact hash
  reviewed bytes build in memory
  reviewed book/gate validation via temp sandbox if necessary

Phase 2 - staged output
  stage artifact
  stage reviewed version
  stage manifest

Phase 3 - publish
  publish immutable version
  publish evidence artifact
  atomic replace ACTIVE manifest last
```

若任一步失败：

```text
no ACTIVE advance
no misleading finalized REVIEWED version
no unexplained orphan temp/version/evidence
```

不要求本批建立复杂事务系统，但必须至少保证**所有 deterministic validation failure = zero output mutation**。

---

# 5. CI Truth：Required Gate PASS，但不是全矩阵 GREEN

## 5.1 Reviewer 正向核验

当前 implementation HEAD：

```text
ada0eac2d973730605f7af65f57e72a22e1483c1
```

Actions：

```text
run 42
workflow overall conclusion = success
```

Job 级别：

```text
Windows / Python 3.12 / required=true  -> PASS
Windows / Python 3.14 / required=true  -> PASS
Ubuntu  / Python 3.14 / required=false -> Pytest FAILED
```

workflow 当前明确通过：

```yaml
continue-on-error: ${{ !matrix.required }}
```

让 Ubuntu leg 失败时不使 overall run 失败。

因此正确状态只能写：

> **Required Windows CI Gate = PASS; overall workflow = SUCCESS; optional Ubuntu 3.14 leg = FAILED at Pytest.**

不得写：

```text
all CI green
full matrix green
Windows/Linux all pass
```

## 5.2 下一批要求

必须调查 Ubuntu Pytest failure 根因并记录：

### 若属于真实跨平台 correctness / filesystem semantics 问题

修复，并增加回归。

### 若属于明确的非目标平台/环境依赖问题

则管理文档必须明确当前正式支持边界，例如：

```text
Formal Phase-0 Runtime Target = Windows
Linux = compatibility / recommended CI only, not formal gate yet
```

但不能因为失败而静默弱化新的 required gate；任何 CI policy 变化必须记录为什么 / 取舍 / 成本收益。

本批禁止简单通过：

```text
continue-on-error everywhere
skip failing test
remove Ubuntu leg
```

来制造绿色。

---

# 6. Governance Closure

本批完成后必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

并确保当前真相包括：

```text
Reviewed code baseline = ada0eac2d973730605f7af65f57e72a22e1483c1
R4-A2.8 / CR-1.2.4 = Implementation DONE / Review REOPENED
R4-A2.9 / CR-1.2.5 = next active batch
RISK-004 remains REOPENED until Reviewer verifies next batch
CR-2 BLOCKED
R4-A3 BLOCKED
P0-M-1B BLOCKED
```

CI 状态必须写 job-level truth：

```text
required Windows 3.12/3.14 PASS
optional Ubuntu 3.14 Pytest FAIL
run 42 overall SUCCESS due continue-on-error policy
```

ADR-016 如存在“exact snapshot already sealed / exact ACTIVE bytes”过度声明，不能删除历史；新增 Reviewer Correction / ADR amendment，说明本轮发现的 double-read seal gap。

建议 Change IDs：

```text
DM-CR-20260825-017  Trading Rule Review Exact-Byte Seal
DM-CR-20260825-018  Trading Rule Review Output-Version Confinement
DM-CR-20260825-019  Cross-Platform CI Truth / Policy Closure
DM-CR-20260825-020  R4-A2.8 Reviewer Governance Correction
DM-CR-20260825-021  Review Workflow Staged Output / Cleanup（P1，可并入 017/018）
```

---

# 7. 推荐实施顺序

```text
Batch A — Exact-Byte Review Snapshot
  capture once
  hash same snapshot
  build reviewed copy from same snapshot
  adversarial double-read test

Batch B — Output Version Confinement
  safe version-id grammar
  lexical first
  resolved confinement
  zero mutation on invalid id

Batch C — Review Output Staging / Cleanup
  deterministic validations before mutation
  temporary/staged output cleanup
  ACTIVE manifest publish last

Batch D — Ubuntu CI Investigation / Policy Truth
  reproduce failure
  classify correctness vs non-formal compatibility issue
  fix or document support boundary

Batch E — Whole-Workflow Adversarial Regression
  review seal lineage
  CA atomic boundary
  Rule replay
  Raw closure
  dry-run closure

Batch F — Governance
  DEVLOG
  DEVELOPMENT_MANAGEMENT
  ADR correction/amendment
  exact CI truth
```

不要启动 CR-2 / R4-A3 来分散当前最后的 SoR closure 工作。

---

# 8. 最低验收矩阵

## 8.1 Golden Domain atomic boundary（保持回归）

```text
[ ] first success exchange persisted before second provider call
[ ] second provider failure -> first success remains in evidence bundle
[ ] persist failure -> no later provider call
[ ] no formal target.*_exchange outside collector.call / ProbeExecutor.call
```

## 8.2 Rule pre-access（保持回归）

```text
[ ] traversal/absolute/drive/foreign-version reject before resolve/read
[ ] lexical valid symlink escape -> resolve then reject before read
[ ] valid bound dataset replay PASS
```

## 8.3 Review input / exact snapshot

```text
[ ] load_active_rules preflight required
[ ] tampered ACTIVE bytes -> zero-output BLOCK
[ ] tampered manifest hash -> zero-output BLOCK
[ ] metadata incoherence -> zero-output BLOCK
[ ] single captured snapshot hash == ACTIVE manifest dataset_hash
[ ] EXACT same snapshot bytes used to build REVIEWED output
[ ] successive-read/mutation adversarial cannot seal unvalidated bytes
```

## 8.4 Output confinement

```text
[ ] ../ / ../../ / absolute / nested / backslash / drive-like version ids BLOCK
[ ] invalid version id -> zero version/evidence/manifest side effects
[ ] valid version output confined under rules_root/versions/<version>/
[ ] existing immutable version collision -> BLOCK before other output mutation
```

## 8.5 Failure cleanup

```text
[ ] deterministic preflight failure leaves no temp files
[ ] failed reviewed-book validation leaves no finalized version
[ ] failed seal never advances ACTIVE
[ ] retry after failure remains deterministic
```

## 8.6 CI / whole system

```text
[ ] ruff check
[ ] ruff format --check
[ ] mypy
[ ] pytest
[ ] required Windows 3.12 PASS
[ ] required Windows 3.14 PASS
[ ] Ubuntu result investigated and recorded accurately
[ ] dry-run evidence closure zero problems
[ ] no last_envelopes correctness consumer
[ ] no payload-only formal provider calls
```

---

# 9. Exit Gate

R4-A2.9 / CR-1.2.5 只有同时满足以下条件，才允许 Developer 标记 DONE / PENDING_REVIEW：

```text
[ ] hash-validated ACTIVE bytes == bytes transformed into REVIEWED copy
[ ] no second-read TOCTOU can substitute seal identity
[ ] --version is one safe confined component
[ ] invalid output version has zero side effects
[ ] all deterministic review validation happens before durable output mutation
[ ] ACTIVE manifest changes last and only after reviewed version passes gates
[ ] old CA atomic exchange boundary remains closed
[ ] old lexical-first rule confinement remains closed
[ ] old Raw evidence identity remains closed
[ ] required Windows CI gates green
[ ] Ubuntu failure root cause / support policy recorded truthfully
[ ] DEVLOG updated
[ ] DEVELOPMENT_MANAGEMENT updated
[ ] ADR correction/amendment where required
[ ] important changes record why/how/alternatives/cost-benefit
```

Reviewer 下轮重点只复查：

```text
1. review.py 是否只 capture ACTIVE bytes 一次并使用该 snapshot 做 hash + seal
2. adversarial successive-read/mutation 是否无法封存未验证 bytes
3. --version ../ / absolute / nested 输入是否在任何 mutation 前拒绝
4. failed review 是否零 finalized output / 不推进 ACTIVE
5. CA collector.call atomic boundary 是否无回归
6. lexical-first rule confinement 是否无回归
7. Ubuntu Pytest failure 根因和 CI policy 是否被准确处理
8. current Actions / exact HEAD / governance 状态是否一致
```

---

# 10. 禁止事项

本批期间禁止：

```text
CR-2 Provider-Normalized + Quarantine
R4-A3 SDK/Lifecycle expansion
Production P0-M-1B
```

同时禁止：

```text
为转绿而把 required Windows gate 改 optional
删除/skip 失败测试而不解释根因
删除 Ubuntu leg 以隐藏兼容性事实
用二次读取 ACTIVE 文件替代 exact snapshot seal
允许 --version 作为任意相对/绝对 path
修改 provider-native Raw 字段来规避 validation adapter
扩大到新的架构层或 Feature/State 工作
```

---

# 11. 变更记录四问

每项重要修复必须在 Notes / ADR 中回答：

```text
1. 为什么要改？
2. 是怎么改的？
3. 考虑过哪些替代方案，为什么没选？
4. 代价与收益是什么？
```

本批必须至少覆盖：

```text
Exact-byte seal:
  single immutable snapshot vs read-again verification

Output confinement:
  strict version-id component vs arbitrary relative path

Review staging:
  all-validation-first vs incremental mutation

CI policy:
  Windows formal target + Linux compatibility leg 的真实边界与未来计划
```

---

# 12. 后续阶段约束

在本批 Reviewer **VERIFIED** 前：

```text
CR-2 Provider-Normalized + Quarantine = BLOCKED
R4-A3 SDK/Lifecycle/Early Stop         = BLOCKED
Production P0-M-1B                    = BLOCKED
```

本批 VERIFIED 后，可以重新评估启动：

```text
CR-2 Provider-Normalized + Quarantine
R4-A3 SDK/Lifecycle/Early Stop
```

但 Production P0-M-1B 仍需额外满足：

```text
Golden Truth 人工 Review
Trading Rule 人工 Review（使用本批闭合后的 exact-byte seal workflow）
正式 Production Account Profile
Provider Doctor actual runtime verified
formal entry gates
```

Trial / Fake / CI 成功仍不得作为正式 Provider business truth 的替代证据。
