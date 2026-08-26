# A-share-analysis：R4-A2.10 / CR-1.2.6 复审结论与 R4-A2.11 / CR-1.2.7 开发工作要求

> **Review Date**：2026-08-25 21:43 +08:00  
> **Reviewed Repository HEAD**：`846fd458cc2c740f423699dabdbe0f4d48bf9c24`  
> **Primary Implementation Commit**：`8d29c16d2476a48e105b091a9ec63b2b39c3d77e`  
> **Previous Reviewer Requirement Commit**：`5423e7c256f96adeb324cdf1349da214602ecf62`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.11 Final Single-Writer Lineage Closure + CR-1.2.7 Review Parent-Identity Serialization**  
> **CR-2**：**BLOCKED**  
> **R4-A3**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. 裁决摘要

R4-A2.10 / CR-1.2.6 已经把上一轮两个 blocking byte-identity 问题和 publish failure cleanup 实质性关闭：

```text
PASS  REVIEWED persisted exact bytes
      → reviewed_text.encode("utf-8") = reviewed_bytes
      → sandbox / staged dataset 全部 write_bytes
      → formal review tool AST 禁止 write_text

PASS  manifest seal identity
      → manifest.dataset_hash 只从 gate-validated reviewed_bytes 派生
      → final read-back 只做 equality verification
      → publish-window tamper BLOCK + rollback，不会重新定义 seal identity

PASS  pre-commit publish cleanup
      → version publish 后、manifest commit 前失败会回收
         finalized version / 本次 evidence / staging / tmp manifest
      → old ACTIVE 保持
      → same-version retry 可重复

PASS  cross-platform CI
      → implementation run 48：Ubuntu 3.14 / Windows 3.12 / Windows 3.14 全 success
      → current HEAD run 49：三腿及各自 Pytest 全 success
```

因此以下实现允许 **PASS / FREEZE**，后续不得机械重开：

```text
ACTIVE input exact snapshot
--version lexical-first confinement
REVIEWED write_bytes byte identity
manifest hash source = reviewed_bytes
publish read-back verification-only
pre-commit cleanup / retry
Golden artifact platform-independent confinement
CA collector.call atomic boundary
Raw evidence identity
Bound Rule lexical-first confinement
Rule metadata coherence / run-bound replay
```

但是本批新引入的 `single-writer lock` 并没有满足上一轮任务书 §5 的明确 contract。

上一轮要求是：

```text
lock covers:
preflight -> snapshot -> staged gate -> manifest commit
```

当前实际控制流是：

```text
load_active_rules()
from-version / ACTIVE lineage check
ACTIVE dataset file identity check
COMPILED check
version target non-existence check
ACTIVE snapshot read + snapshot hash
artifact snapshot/hash
reviewed_bytes build + sandbox parse

THEN

os.open(.review.lock, O_CREAT|O_EXCL)

THEN

staged gate -> publish -> manifest commit
```

因此锁只序列化了 Phase 2/3，**没有序列化决定 parent identity 的 Phase 1**。

这会允许两个 reviewer 都基于同一个旧 ACTIVE 完成 preflight/snapshot，随后依次获得锁并提交；第二个 reviewer 获锁后没有重新验证 ACTIVE 已被第一个推进，可以用 stale parent snapshot 覆盖 selector。

这直接违反 Review lineage / single-writer contract，且 ADR-018 §4 当前关于“锁覆盖 preflight → snapshot → commit 全程”的描述与 runtime 不一致。

因此本轮仍为 **REOPENED**。

---

# 1. 已通过并冻结

## 1.1 Persisted REVIEWED exact-byte identity —— PASS / FREEZE

保留：

```python
reviewed_text = _build_reviewed_text(active_bytes, ...)
reviewed_bytes = reviewed_text.encode("utf-8")

sandbox_yaml.write_bytes(reviewed_bytes)
staged_yaml.write_bytes(reviewed_bytes)
```

正式 dataset 输出不得回退到 `Path.write_text()`。

保留 byte-level 回归：

```text
final read_bytes == expected reviewed_bytes
LF-only
manifest hash independent recompute
generated version load_active_rules / load_bound_rule_book PASS
AST no write_text
```

## 1.2 Manifest identity from reviewed_bytes —— PASS / FREEZE

保留：

```python
expected_dataset_hash = _hash_snapshot([(final_rel, reviewed_bytes)])
```

以及：

```python
actual_final_bytes = final_path.read_bytes()
if actual_final_bytes != reviewed_bytes:
    rollback / BLOCK
```

final filesystem reread 永远只能是 verification source，不能恢复成 identity source。

## 1.3 Pre-commit cleanup / commit boundary —— PASS / FREEZE

当前：

```text
manifest atomic replace success = commit boundary
before commit failure -> cleanup + old ACTIVE + deterministic retry
after commit verification failure -> REVIEW_COMMIT_INCONSISTENT hard failure
```

本轮测试覆盖 tmp manifest write / manifest replace / publish-window tamper，主体通过。

## 1.4 CI —— PASS / POSITIVELY CONFIRMED

Reviewer 正向核验：

```text
run 48 @ 8d29c16d...
Ubuntu 3.14  SUCCESS / Pytest SUCCESS
Windows 3.12 SUCCESS / Pytest SUCCESS
Windows 3.14 SUCCESS / Pytest SUCCESS

run 49 @ 846fd458...
Ubuntu 3.14  SUCCESS / Pytest SUCCESS
Windows 3.12 SUCCESS / Pytest SUCCESS
Windows 3.14 SUCCESS / Pytest SUCCESS
```

CI 本轮不是 blocker。

---

# 2. P0-01：Single-Writer Lock 获取过晚，stale parent review 可覆盖新 ACTIVE

## 2.1 当前代码问题

当前 `main()` 在拿锁前已经完成所有 parent-dependent 状态读取：

```python
active_book, active = load_active_rules(rules_root)
...
version_dir = _validate_version_id(...)
if version_dir.exists(): ...
...
active_bytes = active_path.read_bytes()
snapshot_hash = ...
...
reviewed_bytes = reviewed_text.encode("utf-8")
...
TradingRuleBook.load(sandbox_yaml)

# 到这里以后才：
lock_fd = os.open(lock_path, O_CREAT | O_EXCL | O_WRONLY)
```

ADR-018 / commit message 则声明：

```text
.review.lock spans preflight -> snapshot -> staged gate -> manifest commit
```

runtime 与 contract 不一致。

## 2.2 可复现的并发错误场景

设 ACTIVE 起点为 `v1-compiled`：

```text
Reviewer A:
  load ACTIVE v1
  snapshot v1
  build reviewed_bytes A -> target v2-reviewed
  尚未拿锁

Reviewer B:
  load ACTIVE v1
  snapshot v1
  build reviewed_bytes B -> target v3-reviewed
  尚未拿锁

A 获取 lock
  staged gate A
  commit ACTIVE -> v2-reviewed
  release lock

B 获取 lock
  不再 load/recheck ACTIVE
  仍使用旧 parent v1 snapshot
  staged gate B
  commit ACTIVE -> v3-reviewed
```

最终：

```text
ACTIVE = v3-reviewed
但 B 的 human review parent = stale v1-compiled
v2-reviewed 的 selector advance 被 B 覆盖
```

锁虽然让 Phase 2/3 串行，却没有让 **parent selection** 串行，因此不是有效的 single-writer lineage serialization。

这不是理论上的 OS CAS 讨论，而是两个遵守工具 contract 的 reviewer/process 就能形成的 stale-preflight race。

现有测试只覆盖：

```text
已有 .review.lock -> second run fail fast
successful run -> lock removed
failed run -> lock removed
```

没有覆盖：

```text
two reviewers both finish Phase 1 against same parent before either gets lock
```

因此当前测试存在 control-flow blind spot。

---

# 3. 强制修复

## 3.1 首选方案：Lock-before-SoR-Preflight（Option A，推荐）

把 `.review.lock` 获取前移到所有 ACTIVE-dependent / mutable-version-store 检查之前。

允许在锁前完成：

```text
CLI parse
纯 lexical 参数格式检查（不依赖当前 ACTIVE）
必要的 rules_root 基础存在性检查
```

但以下必须在持锁期间完成：

```text
load_active_rules()
--from-version lineage check
--rules == ACTIVE dataset check
ACTIVE COMPILED check
version target confinement + non-existence check
ACTIVE snapshot read + hash verification
artifact snapshot / reviewed_bytes build
sandbox parse
staged gate
publish
manifest commit
post-commit verification（至少到 committed result 已明确）
```

即正式控制流：

```text
acquire .review.lock
  ↓
ACTIVE integrity + parent identity
  ↓
ACTIVE snapshot
  ↓
review transform
  ↓
staged review gate
  ↓
publish
  ↓
ACTIVE manifest commit
  ↓
post-commit verification
  ↓
release .review.lock
```

锁不能只包 `_review_locked_workflow()`。

## 3.2 可接受备选：Lock 后重新验证 captured parent（Option B）

如坚持把部分 Phase 1 留在锁外，则获得锁后、任何 staged mutation 前必须重新执行 ACTIVE parent identity verification：

```text
current ACTIVE rule_version
current ACTIVE dataset_hash
current dataset_files
current source_version / dataset_version / review_status
```

必须与 Phase 1 captured parent 完全一致；否则：

```text
STALE_PARENT / LINEAGE_MOVED
→ zero output
→ release lock
→ operator must restart review from current ACTIVE
```

由于拿锁后其他合作 reviewer 无法推进 ACTIVE，recheck 后到 commit 的窗口才被 single-writer contract 封住。

若采用 Option B，ADR-018 §4 必须修正为“Phase 1 optimistic snapshot + lock-acquire parent recheck + serialized commit”，不得继续声称锁本身覆盖 preflight/snapshot。

**不要**用仅在 commit 前无锁 recheck 的方案；上一轮已经明确该 check 不是 CAS。

---

# 4. Required Tests

必须增加真正的 stale-parent concurrency regression，而不是只测试锁文件存在。

最低验收：

```text
[ ] lock acquisition dominates load_active_rules / ACTIVE snapshot
    （若 Option A，可用 control-flow/static guard + runtime counter）

[ ] Reviewer A 基于 v1 开始并持锁时，Reviewer B 不能完成 ACTIVE preflight/snapshot

[ ] 模拟 B 在锁外捕获 v1、A 先 commit v2、B 后获得锁
    -> B 必须 BLOCK 为 stale parent（若采用 Option B）
    -> 绝不能把 ACTIVE 从 v2 覆盖成基于 v1 的 v3

[ ] stale-parent rejection = zero new version / zero new evidence / no manifest advance

[ ] A commit 后 B 重新从 current ACTIVE 启动时，正常的新 review 才允许继续

[ ] same target-version race 不会 silent overwrite；immutable version 仍保持

[ ] lock success/failure release tests 保留

[ ] existing exact-byte / manifest identity / cleanup / CI matrix tests 全保持
```

建议增加一条结构性 guard：

```text
os.open(.review.lock, O_EXCL)
MUST execute before first load_active_rules() in the formal review path
```

如果代码重构为 helper，则 guard 应验证 formal entrypoint 的调用顺序，而非只查 AST 中“两个调用都存在”。

---

# 5. Governance Correction

本批必须同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
ADR-018 amendment / 新 ADR（如需要）
```

必须明确记录：

```text
R4-A2.10 / CR-1.2.6 = Implementation DONE / Review REOPENED
P0 byte-identity 主体 = PASS / frozen
publish cleanup = PASS / frozen
DM-CR-20260825-025 single-writer = REOPENED
原因 = lock acquired AFTER parent-dependent Phase 1，未覆盖 advertised scope
RISK-004 remains REOPENED
CR-2 remains BLOCKED
R4-A3 remains BLOCKED
P0-M-1B remains BLOCKED
```

ADR-018 §4 当前“lock covers preflight → snapshot → staged gate → manifest commit”属于 overclaim；历史不要删除，追加 Reviewer Correction / amendment。

建议 Change IDs：

```text
DM-CR-20260825-027  Review Parent-Identity Serialization Closure
DM-CR-20260825-028  Single-Writer Lock Scope / Stale-Parent Regression
DM-CR-20260825-029  R4-A2.10 Reviewer Governance Correction
```

---

# 6. 推荐实施顺序

```text
Batch A — Lock Scope Fix
  acquire before ACTIVE-dependent preflight
  or lock-acquire + full captured-parent recheck

Batch B — Stale-Parent Adversarial Test
  two-reviewer interleaving
  prove v1-based B cannot overwrite A's v2 advance

Batch C — Whole Review Regression
  exact-byte seal
  manifest identity
  publish rollback
  output confinement
  ACTIVE replay

Batch D — Whole-system Regression
  CA atomic boundary
  Raw closure
  Bound Rule replay
  dry-run closure

Batch E — Governance
  DEVLOG
  DEVELOPMENT_MANAGEMENT
  ADR correction
  exact current CI truth
```

禁止继续扩展新的 Provider / Canonical / Feature 功能来分散这一最后的 review-lineage closure。

---

# 7. Exit Gate

R4-A2.11 / CR-1.2.7 只有同时满足以下条件，Reviewer 才应结束连续 R4-A2.x / CR-1.x 审计链：

```text
[ ] single-writer lock/serialization covers parent selection through commit
[ ] stale parent cannot commit after ACTIVE advanced
[ ] ACTIVE parent identity is established while serialized
[ ] exact ACTIVE snapshot remains intact
[ ] reviewed_bytes exact persisted identity remains intact
[ ] manifest identity remains derived only from reviewed_bytes
[ ] final reread remains verification-only
[ ] pre-commit cleanup / deterministic retry remains intact
[ ] output confinement remains intact
[ ] CA / Raw / Bound Rule upstream closures remain intact
[ ] full CI matrix green
[ ] docs match runtime (no lock-scope overclaim)
```

若以上全部通过且无新的 formal correctness regression：

```text
R4-A2.x / CR-1.x Review -> VERIFIED
RISK-004 -> 按其剩余定义重新评估关闭
CR-2 Provider-Normalized + Quarantine -> 可启动实施
R4-A3 SDK/Lifecycle/Early Stop -> 可重新排期启动
```

但即使 R4-A2.x / CR-1.x VERIFIED：

```text
Production P0-M-1B 仍保持 BLOCKED
```

直到额外满足：

```text
Golden Truth 人工 Review
Trading Rule 人工 Review（使用最终 VERIFIED 的 review workflow）
正式 Production Account Profile
Provider Doctor = RUNTIME_ACTUAL_LOAD_VERIFIED
正式权限 / endpoint / entry gates
```

Trial / Fake / CI 永远不能替代正式 Provider business truth。

---

# 8. 变更记录四问

本批 notes / ADR 必须回答：

```text
1. 为什么原 lock placement 不能构成 single-writer lineage serialization？
2. 如何保证 parent identity 在 serialization boundary 内建立？
3. 为什么选择 lock-before-preflight 或 lock-acquire parent-recheck；替代方案为何不选？
4. 成本与收益是什么？
```

重点写清：

```text
“Phase 2/3 串行” != “review parent lineage 串行”
```

这是本批最后需要封闭的正式语义。

---

# 9. Implementation Mapping（Developer 回填，2026-08-25）

> 本批：R4-A2.11 Final Single-Writer Lineage Closure + CR-1.2.7 Review Parent-Identity Serialization（Batch A→E 全部完成；**未启动 CR-2 / R4-A3 / 新 Provider/Canonical/Feature**——遵守 §6 禁止项）。
> 测试基线：**658 passed / 0 failed**（650 → 658，+8）；CI 等价四检查（ruff check + format --check + mypy + pytest）本地全绿；dry-run 冒烟 35 exchanges + 5 bundles 双向闭合零问题；既有全部契约测试零回归。
> Change IDs：DM-CR-20260825-027/028/029；ADR-018 **§4 amendment**（修正性重排——不新建 ADR，历史原文保留 + 修正记录）。
> CI：本批提交后以 Actions 实际结果为准（上批 run 48/49 已三腿 success，CI 非 blocker）。
> **§8 四问对照**：①原 placement 为何不构成 single-writer lineage serialization——锁只串行化 Phase 2/3 提交，parent selection（load_active_rules/snapshot）在锁外，stale-preflight race 实测可复现（两个 reviewer 基于同一旧 parent 完成 Phase 1 后依次提交，第二个覆盖第一个的 advance）；②parent identity 如何在 serialization boundary 内建立——lock-before-preflight：锁内执行 load_active_rules（parent selection）→ snapshot → transform → gate → commit → post-commit verification 全程；③为何选 Option A（lock-before-preflight）而非 Option B（recheck）——A 使 ADR-018 原广告语义成立且单一代码路径（B 需双份 parent 验证逻辑 + ADR 改写为 optimistic snapshot 语义，且两份验证逻辑必然漂移）；④成本 = 持锁时间稍长（preflight 纳入，竞争时快速失败），收益 = stale-parent 覆盖在构造上不可能。

## §3 强制修复（P0-01）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 3.1 Option A：lock 前移到 ACTIVE-dependent 读取之前 | `review.py`：`main()` Phase 0——CLI parse + `rules_path.is_file()`/`artifact.is_file()`（基础存在性）后即 `os.open(.review.lock, O_CREAT\|O_EXCL)`；整个 workflow 在 `_review_workflow_locked` 内（load_active_rules / lineage / COMPILED / version confinement+non-existence / snapshot / reviewed_bytes / sandbox / staged gate / publish / manifest commit / post-commit verification 全在锁内） | lineage::test_preflight_runs_only_while_lock_held + test_structural_guard_lock_before_preflight |
| 3.1 锁前仅 CLI parse / lexical / 基础存在性 | 同上（rules_path/artifact 存在性属"必要的 rules_root 基础存在性检查"） | 并发锁测试证明 ACTIVE 读取为 0 |
| 3.1 锁不能只包 _review_locked_workflow | `_review_locked_workflow` 改名 `_review_workflow_locked` 且包含 Phase 1（原锁外的全部校验/snapshot/sandbox 移入） | 全量 658 零回归 |

## §4 Required Tests

| 验收项 | 测试 |
|---|---|
| lock acquisition dominates load_active_rules / ACTIVE snapshot（control-flow/static guard + runtime counter） | test_preflight_runs_only_while_lock_held（runtime counter：`lock_exists_at_preflight is True`）+ test_structural_guard_lock_before_preflight（AST：O_EXCL open 行号 < 首个 load_active_rules；BitOr 嵌套 flag 匹配） |
| B 持 stale Phase-1 capture、A 先 commit v2、B 后获锁 → BLOCK 为 stale parent；绝不能把 ACTIVE 从 v2 覆盖成基于 v1 的 v3 | test_stale_parent_blocks_and_never_overwrites_advance（`--from-version v1` → "ACTIVE manifest is v2-reviewed" BLOCK；ACTIVE 保持 v2；无 v3；无新 evidence；无 temp；锁释放）+ test_default_from_version_also_blocks_after_advance（无 --from-version 时 stale --rules 被 input==ACTIVE 拒绝） |
| stale-parent rejection = zero new version / evidence / manifest advance | 同上（零输出断言嵌入） |
| A commit 后 B 从 current ACTIVE 重启正常 | test_b_restarting_from_current_active_succeeds（新 COMPILED 候选 v2b → v3 正常推进） |
| same target-version race 不 silent overwrite；immutable version 保持 | test_same_target_version_never_silently_overwrites（v2-reviewed 首版字节逐字节不动；ACTIVE 不被覆盖） |
| lock success/failure release 保持 | test_lock_released_on_success_and_failure + test_concurrent_lock_blocks_before_any_active_read（fail fast 且 load_active_rules 计数 == 0） |
| existing exact-byte / manifest identity / cleanup / CI matrix 全保持 | 全量 658 零回归（TestPersistedByteIdentity / TestPublishWindowTamper / TestPreCommitFailureCleanup / TestSingleWriterLock 等全部通过） |
| 结构性 guard（os.open O_EXCL 先于首个 load_active_rules；helper 化后验证 entrypoint 调用顺序而非仅"两调用都存在"） | test_structural_guard_lock_before_preflight（单文件内行号序 = formal entrypoint 的执行序；锁在 main() 内、preflight 在被调函数内，行号序即调用序） |

## §5 Governance（DM-CR-20260825-029）

| 要求 | 落实 |
|---|---|
| DEVLOG / 总册 / ADR amendment | DEVLOG 顶部新条目（历史保留）；总册头部（Reviewed HEAD 846fd458 + Reviewer Correction：PASS-FREEZE 分列 + lock scope overclaim）+ §40/§41/§52/§61/§62；ADR-018 §4 amendment（修正记录置于节首，原文保留）+ ADR-000 索引标注 |
| R4-A2.10 = Implementation DONE / Review REOPENED；P0 byte-identity 主体 = PASS/frozen；publish cleanup = PASS/frozen；DM-CR-025 = REOPENED；原因记录 | §40 精确分列 + 头部 Reviewer Correction + DM-CR-029 条目 |
| RISK-004 / CR-2 / R4-A3 / P0-M-1B 保持 | §52（理由更新）/ §41（BLOCKED 保持） |

## §7 Exit Gate 自检

```text
[x] single-writer lock/serialization covers parent selection through commit（lock-before-preflight + 三重证明）
[x] stale parent cannot commit after ACTIVE advanced（--from-version BLOCK + input==ACTIVE BLOCK，双向）
[x] ACTIVE parent identity is established while serialized（runtime counter：preflight 仅在持锁时执行）
[x] exact ACTIVE snapshot remains intact（既有 7 项测试零回归）
[x] reviewed_bytes exact persisted identity remains intact（TestPersistedByteIdentity 零回归）
[x] manifest identity remains derived only from reviewed_bytes（test_manifest_hash_derives_from_reviewed_bytes 零回归）
[x] final reread remains verification-only（TestPublishWindowTamper 零回归）
[x] pre-commit cleanup / deterministic retry remains intact（TestPreCommitFailureCleanup 零回归）
[x] output confinement remains intact（17 项 version-confinement 测试零回归）
[x] CA / Raw / Bound Rule upstream closures remain intact（全量 658 零回归）
[~] full CI matrix green —— 上批 run 48/49 已三腿 success；本批提交后以 Actions 实际结果为准（不预写）
[x] docs match runtime (no lock-scope overclaim)（ADR-018 §4 amendment + 总册 Reviewer Correction + DEVLOG 同批更新）
```

已知开放项（如实声明）：Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED。