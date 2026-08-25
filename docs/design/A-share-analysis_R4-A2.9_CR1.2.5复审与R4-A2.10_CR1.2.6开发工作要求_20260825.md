# A-share-analysis：R4-A2.9 / CR-1.2.5 复审结论与 R4-A2.10 / CR-1.2.6 开发工作要求

> **Review Date**：2026-08-25 18:55 +08:00  
> **Reviewed Repository HEAD**：`8a6f4149e0f7090850b77c3b2e6a804b8ef45595`  
> **Primary Implementation Commit**：`793dfc1220e3d1b8669483c008a8596150b0dcd6`  
> **Cross-Platform CI Fix Commit**：`b429220663897060b7940c727d0e09ec902192de`  
> **Previous Reviewer Requirement Commit**：`905ab88313b8e939f88c6f40810c4a11b785650a`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED**  
> **Next Batch**：**R4-A2.10 Final Review Output Byte-Identity / Commit Closure + CR-1.2.6 Review Publish Integrity**  
> **CR-2**：**BLOCKED**  
> **R4-A3**：**BLOCKED**  
> **Production P0-M-1B**：**BLOCKED**

---

# 0. 裁决摘要

R4-A2.9 / CR-1.2.5 已经关闭上一轮两个原始 P0，并把 Ubuntu CI 中暴露的两个真实跨平台 correctness bug 修掉：

```text
PASS  ACTIVE input exact snapshot
      → active_bytes 单次 capture
      → manifest dataset_hash 从同一 snapshot bytes 验证
      → REVIEWED 内容从同一 snapshot 构造

PASS  --version output confinement
      → one safe path component
      → lexical first
      → resolved confinement
      → deterministic validation before rule-store mutation

PASS  Cross-platform CI truth
      → YAML/YML byte normalization 明确为 LF
      → content-addressed evidence 禁止 EOL normalize
      → Golden artifact ref 改为 platform-independent lexical-first confinement
      → current HEAD Actions full matrix green
```

当前 HEAD `8a6f4149...` 的 GitHub Actions run 46 已正向确认：

```text
Ubuntu  / Python 3.14 -> SUCCESS（Pytest SUCCESS）
Windows / Python 3.12 -> SUCCESS（Pytest SUCCESS）
Windows / Python 3.14 -> SUCCESS（Pytest SUCCESS）
workflow overall      -> SUCCESS
```

因此上一轮的 Ubuntu CI blocker 已关闭，后续不得再写成“optional Ubuntu 仍失败”。

但是 Reviewer 对 `scripts/rules/review.py` 的 Phase 2/3 做 byte-level 复核后，确认 exact-byte seal 还差最后一层：**输入 snapshot 已经 exact，但最终持久化的 REVIEWED bytes 与 ACTIVE manifest 所封存的 identity 仍可能脱离该 exact snapshot transform。**

本轮新增两个 blocking correctness 问题：

```text
P0-01  REVIEWED dataset 仍通过 Path.write_text() 落盘；
       Windows text-mode newline translation 可把内存 LF 文本写成 CRLF，
       所以 persisted bytes != exact transformed bytes

P0-02  publish 后又重新 read final rules.yaml，并用这次 read 计算
       manifest.dataset_hash；若 final file 在 gate 后、hash 前被替换，
       manifest 会“祝福”未经过 review gate 的新 bytes
```

这两个问题共同说明：

```text
hash-validated ACTIVE bytes
== bytes transformed in memory
```

已经成立；但：

```text
bytes transformed in memory
== bytes persisted as REVIEWED
== bytes whose identity is sealed into ACTIVE manifest
```

尚未结构性成立。

由于这正是人工 Trading Rule Review 的 immutable SoR seal 语义，本轮不能给 VERIFIED。

---

# 1. 本轮已通过并冻结的实现

## 1.1 ACTIVE input single-snapshot exactness —— PASS / FREEZE

保留现有：

```python
active_bytes = active_path.read_bytes()
snapshot_hash = _hash_snapshot([(active_rel, active_bytes)])
if snapshot_hash != active.dataset_hash:
    BLOCK

reviewed_text = _build_reviewed_text(active_bytes, ...)
```

现有 adversarial tests 已证明：

```text
preflight 后 snapshot read 被换成 tampered bytes -> BLOCK
不存在第二次 ACTIVE read 可用来“恢复合法 hash、封存恶意第一次 read”
ACTIVE snapshot identity 不再被 read-again 替代
```

本项不重构回双读模型。

## 1.2 `--version` lexical-first output confinement —— PASS / FREEZE

保留：

```text
^[A-Za-z0-9][A-Za-z0-9._-]*$
+ explicit . / .. rejection
+ resolved confinement under versions/
+ existing-version collision before evidence mutation
```

12 类 unsafe id zero-side-effect 测试继续保留。

## 1.3 Golden artifact platform-independent confinement —— PASS / FREEZE

`golden_store._verify_artifact` 已不再依赖当前 OS 对 `C:/...` 的 Path 解释；drive-like / POSIX absolute / traversal 在 lexical 层先拒绝，再进入 resolved confinement。

这一修复关闭了 run 44 的剩余 Ubuntu-only failure。

## 1.4 CI full matrix —— PASS / POSITIVELY CONFIRMED

Reviewer 已正向核验当前 HEAD run 46：三个 matrix job 和各自 Pytest 都 success。

当前正确状态：

> **FULL MATRIX GREEN on current HEAD.**

历史 run 42 / run 44 的 Ubuntu failures 继续作为已修复历史保留，不应从 DEVLOG/ADR 删除。

## 1.5 上游主链继续冻结

本轮不重新打开：

```text
Golden Domain collector.call atomic exchange persistence
B5/B6 ProbeExecutor exchange persistence
Raw meta anchor + payload bidirectional closure
Raw persisted evidence identity / orphan recovery
Bound Rule lexical-first pre-access confinement
Rule Manifest metadata coherence / selector binding
Golden typed CA truth + provider-native ephemeral adapter
formal limit-rule explicit bound book
full request_params lineage
run-bound exact replay
```

---

# 2. P0-01：REVIEWED Persisted Bytes 不是 Exact Transformed Bytes

## 2.1 当前实现

`_build_reviewed_text(active_bytes, ...)` 返回 Python `str`，随后：

```python
sandbox_yaml.write_text(reviewed_text, encoding="utf-8")
...
staged_yaml.write_text(reviewed_text, encoding="utf-8")
```

最终 `staging_dir` 被 rename 为正式 version dir。

问题不在 YAML 语义，而在 **byte identity**。

在 Windows 文本模式下，写文本时 `\n` 可以被转换为平台换行；因此：

```text
ACTIVE snapshot bytes      = LF
_build_reviewed_text       = LF logical text
Path.write_text on Windows = may persist CRLF bytes
```

结果是：

```text
exact transformed bytes != persisted REVIEWED bytes
```

现有 `test_reviewed_content_derives_from_exact_snapshot` 使用：

```python
read_text(...).splitlines(keepends=True)
```

文本读取会做 universal-newline normalization，因此该测试可以在 persisted bytes 已发生 CRLF/LF 差异时仍然通过。

这与 ADR-017 的不变量：

> `hash-validated ACTIVE bytes == bytes transformed == bytes sealed`

不一致。

## 2.2 强制修复

review workflow 必须建立真正的 byte object：

```python
reviewed_text = _build_reviewed_text(active_bytes, ...)
reviewed_bytes = reviewed_text.encode("utf-8")
```

之后所有正式 dataset 输出必须使用：

```python
write_bytes(reviewed_bytes)
```

而不是 `write_text()`。

推荐：

```text
sandbox parse 可用 write_bytes(reviewed_bytes)
staging rules.yaml 必须 write_bytes(reviewed_bytes)
final version 只能由该 staged byte file 原子 publish
```

正式不变量升级为：

```text
validated ACTIVE snapshot bytes
      ↓ deterministic provenance transform
reviewed_bytes (single in-memory identity)
      ↓ write_bytes
staged rules bytes
      ↓ atomic rename
final REVIEWED rules bytes
```

不得让 OS newline translation 参与 identity 生成。

## 2.3 Required Tests

至少增加：

```text
[ ] generated REVIEWED rules.yaml bytes contain no CRLF on Windows CI
[ ] generated REVIEWED rules.yaml bytes contain no CRLF on Ubuntu CI
[ ] persisted final bytes == exact reviewed_bytes object
[ ] byte-level test，不得仅用 read_text/splitlines 做等价性断言
[ ] formal REVIEWED dataset write path 禁止 Path.write_text
[ ] generated REVIEWED version + manifest 可在另一平台 checkout/replay 后 hash 一致
```

跨平台测试应直接比：

```text
bytes
sha256
```

而不是 logical text lines。

---

# 3. P0-02：Publish-Time Re-read 可重新打开 Seal Identity TOCTOU

## 3.1 当前实现

Phase 2 已对 staged reviewed book 做完整 gate：

```text
staged_yaml
→ TradingRuleBook.load
→ trading_rule_review_gate PASS
```

随后 Phase 3：

```python
staging_dir.replace(version_dir)
published_bytes = (version_dir / "rules.yaml").read_bytes()
manifest["dataset_hash"] = _hash_snapshot([(final_rel, published_bytes)])
```

这里 `published_bytes` 是**新的 filesystem read**，并且它被用于定义最终 ACTIVE manifest identity。

### 对抗场景

```text
T0  reviewed_bytes R 由 exact ACTIVE snapshot 构造
T1  staged R 通过 TradingRuleBook + review_gate
T2  staging rename -> final version_dir
T3  final rules.yaml 被替换成 T（保留相同 metadata，但修改规则内容）
T4  published_bytes = read(T)
T5  manifest.dataset_hash = hash(T)
T6  ACTIVE manifest replace
T7  load_active_rules 看到 T + hash(T) + coherent metadata -> 可 PASS
```

这会导致：

```text
human/review gate validated R
ACTIVE manifest sealed T
```

也就是旧 double-read 问题从 ACTIVE input 端被修掉后，又在 REVIEWED output publish 端出现。

## 3.2 强制修复

最终 manifest identity **只能**由已经 gate-validated 的 in-memory `reviewed_bytes` 派生：

```python
final_rel = f"versions/{version}/rules.yaml"
expected_dataset_hash = _hash_snapshot([(final_rel, reviewed_bytes)])
```

正式 publish 后允许做 read-back integrity check：

```python
actual_final_bytes = final_path.read_bytes()
if actual_final_bytes != reviewed_bytes:
    BLOCK / rollback before ACTIVE manifest advance
```

但 read-back 的角色只能是：

```text
verify persisted bytes == expected sealed bytes
```

禁止变成：

```text
read arbitrary current final bytes
→ use those bytes to DEFINE the manifest identity
```

因此：

```text
manifest.dataset_hash source of truth = reviewed_bytes identity
filesystem read-back              = verification only
```

## 3.3 Required Adversarial Tests

必须增加 publish-window mutation test：

```text
[ ] staged reviewed R passes gate
[ ] after rename, before manifest publish, inject/tamper final rules.yaml -> T
[ ] tool MUST NOT seal hash(T)
[ ] ACTIVE manifest MUST remain previous COMPILED selector
[ ] tampered final version must not be treated as successfully REVIEWED/ACTIVE
[ ] clean retry deterministic after cleanup
```

并直接断言：

```text
manifest.dataset_hash == hash(final_rel + reviewed_bytes)
```

而不是：

```text
manifest.dataset_hash == hash(whatever bytes happen to be on disk at publish-time read)
```

---

# 4. P1-01：Phase-3 Publish Failure Cleanup 仍不完整

当前 publish：

```python
staging_dir.replace(version_dir)
...
tmp_manifest.write_bytes(...)
tmp_manifest.replace(manifest_path)
```

但 `except` 里仍主要清：

```python
shutil.rmtree(staging_dir, ignore_errors=True)
```

一旦第一步 rename 已成功：

```text
staging_dir 已不存在
version_dir 已存在
```

如果随后 manifest temp write / replace 抛异常：

```text
ACTIVE 可能仍旧
finalized versions/<new>/ 已留下
本次 evidence 可能留下
retry same version -> immutable-version collision
```

这违反 staged workflow 的“失败后可确定性重试 / 不留下 misleading finalized output”目标。

## 4.1 最低要求

不要求引入复杂分布式事务；但本地 review 工具至少要明确 commit boundary：

```text
Before ACTIVE manifest atomic replace succeeds:
  failure = uncommitted
  → remove newly published version_dir
  → remove this run newly-created evidence
  → remove tmp manifest
  → ACTIVE remains old
  → same version retry possible

After ACTIVE manifest replace succeeds:
  operation = committed
  → post-commit verification failure必须进入显式 REVIEW_COMMIT_INCONSISTENT
    / rollback policy，不能伪装成普通可重试失败
```

建议保存：

```text
old manifest bytes / old selector identity
created_evidence flag
published_version flag
manifest_committed flag
```

以驱动明确 cleanup。

## 4.2 Required Tests

```text
[ ] inject failure after staging rename but before tmp manifest write
[ ] inject tmp manifest write failure
[ ] inject manifest replace failure
[ ] all pre-commit failures -> old ACTIVE + no new finalized version + no new orphan evidence/temp
[ ] same version retry succeeds after failure
[ ] post-commit verification failure has explicit hard-failure semantics
```

---

# 5. P1-02：Review Publish Single-Writer / Lineage Recheck

现有 `--from-version` 只在 Phase 1 验证 ACTIVE lineage。长流程中若另一个 reviewer/process 已推进 ACTIVE，本次 Phase 3 仍可能覆盖新的 selector。

本批至少二选一：

### Option A（推荐，简单）

明确 review tool 为 single-writer operation，并使用跨平台可接受的 lock/lease，锁覆盖：

```text
preflight -> snapshot -> staged gate -> manifest commit
```

### Option B

在 manifest commit 前重新检查 ACTIVE selector/manifest identity 仍等于 Phase 1 captured parent；发生变化则 abort + cleanup。

若仅做 Option B，需要在 ADR 里诚实说明 check 与 replace 之间仍非 OS-level CAS；正式并发写仍由“single writer”运维契约兜底。

本项可作为 P1，但必须记录，不允许继续把 `--from-version` 描述成完整并发 CAS。

---

# 6. CI 结论与回归要求

## 6.1 当前 CI —— VERIFIED GREEN

当前 HEAD run 46：

```text
Ubuntu 3.14   job SUCCESS / Pytest SUCCESS
Windows 3.12  job SUCCESS / Pytest SUCCESS
Windows 3.14  job SUCCESS / Pytest SUCCESS
```

run 45 (`b429220...`) 也已全三腿成功。

因此：

```text
DM-CR-20260825-019 root-cause investigation = CLOSED
```

但新增 P0-01 说明当前 matrix 还缺一个**generated-review-byte**测试；CI 绿不等于该 byte-level contract 已被测试。

## 6.2 下一批新增跨平台 contract test

必须在 Windows + Ubuntu 都执行：

```text
generate reviewed version in temp root
→ read_bytes(final rules.yaml)
→ assert byte identity / no CRLF drift
→ compute manifest hash independently
→ load_active_rules
```

该测试要验证 review tool **生成的数据集**，不能只验证仓库中已经由 `.gitattributes` 规范化的 compiled YAML。

---

# 7. Governance 修正

下一批同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
ADR-018（或 ADR-017 amendment）
```

## 7.1 当前 baseline 必须写 exact SHA

当前总册头部：

```text
Current Code Baseline: 本批提交 ...
```

仍不是机器可核验的 exact SHA。

下一批必须改成至少：

```text
Reviewed Repository HEAD = 8a6f4149e0f7090850b77c3b2e6a804b8ef45595
Primary Implementation   = 793dfc1220e3d1b8669483c008a8596150b0dcd6
Current Repository HEAD   = <next actual SHA>
```

Reviewer doc commit 不应被误写成 implementation baseline。

## 7.2 状态

复核后当前真相：

```text
R4-A2.9 / CR-1.2.5 = DONE / REOPENED
R4-A2.10 / CR-1.2.6 = NEXT ACTIVE BATCH
RISK-004             = REOPENED
CR-2                 = BLOCKED
R4-A3                = BLOCKED
Production P0-M-1B   = BLOCKED
```

## 7.3 ADR Correction

ADR-017 的：

```text
hash-validated ACTIVE bytes == bytes transformed == bytes sealed
```

当前只完成到：

```text
hash-validated ACTIVE bytes == transformed logical content
```

未完成：

```text
transformed exact bytes == persisted REVIEWED bytes == manifest-sealed bytes
```

不得删除 ADR-017 历史；新增 ADR-018 或明确 amendment，记录：

```text
为什么 text-mode output 破坏 byte identity
为什么 final reread 不得定义 manifest identity
为什么选择 write_bytes + in-memory expected hash
考虑过哪些替代方案
成本/收益
```

---

# 8. 推荐实施顺序

## Batch A — Persisted Review Byte Identity

```text
reviewed_text -> reviewed_bytes exactly once
all dataset writes use write_bytes
byte-level generated-output tests
Windows/Ubuntu generated version parity
```

## Batch B — Manifest Seal Identity

```text
expected final dataset hash from reviewed_bytes + final relative path
publish read-back = verification only
post-rename tamper adversarial
never bless arbitrary final reread bytes
```

## Batch C — Publish Failure Cleanup

```text
track uncommitted/published/committed state
cleanup finalized version/evidence/tmp before manifest commit
retry same version after injected failure
```

## Batch D — Single-Writer / Commit Lineage

```text
lock or explicit single-writer + pre-commit lineage recheck
record CAS limitation honestly
```

## Batch E — Whole-System Regression

```text
CA atomic boundary
ProbeExecutor persistence
Raw closure/recovery
Rule bound replay
Golden typed CA
Rule lexical-first
review exact input snapshot
version output confinement
```

## Batch F — Governance

```text
DEVLOG
DEVELOPMENT_MANAGEMENT exact SHAs/status
ADR correction/amendment
CI current run truth
```

---

# 9. Minimum Acceptance Matrix

## 9.1 Input seal（保持）

```text
[ ] active snapshot captured once
[ ] snapshot hash uses captured bytes
[ ] tampered snapshot blocks before output
[ ] no ACTIVE double-read identity substitution
```

## 9.2 Persisted output byte identity（新增 P0）

```text
[ ] reviewed_bytes is explicit immutable in-memory object
[ ] staged rules uses write_bytes(reviewed_bytes)
[ ] final rules bytes == reviewed_bytes
[ ] no CRLF platform translation in generated REVIEWED dataset
[ ] byte-level test runs on Windows and Ubuntu
```

## 9.3 Manifest identity（新增 P0）

```text
[ ] expected manifest hash derives from reviewed_bytes
[ ] filesystem reread is verification-only
[ ] post-gate final-file tamper cannot be blessed
[ ] manifest does not advance on read-back mismatch
```

## 9.4 Failure cleanup（P1）

```text
[ ] manifest-write failure leaves old ACTIVE
[ ] manifest-replace failure leaves old ACTIVE
[ ] pre-commit failure leaves no finalized new version
[ ] pre-commit failure leaves no newly-created orphan evidence/tmp
[ ] same version retry deterministic
```

## 9.5 Existing contracts（保持）

```text
[ ] unsafe --version zero side effects
[ ] bound Rule lexical-first
[ ] Golden artifact lexical-first cross-platform
[ ] CA call->persist atomic boundary
[ ] Raw evidence closure/recovery
[ ] exact replay unchanged after ACTIVE advance
```

## 9.6 CI

```text
[ ] ruff check
[ ] ruff format --check
[ ] mypy
[ ] pytest
[ ] Windows 3.12 success
[ ] Windows 3.14 success
[ ] Ubuntu 3.14 success
[ ] generated REVIEWED byte-identity test participates in both OS families
```

---

# 10. Exit Gate

R4-A2.10 / CR-1.2.6 只有同时满足以下条件才允许 Reviewer 给最终 VERIFIED：

```text
[ ] validated ACTIVE snapshot identity remains exact
[ ] transformed REVIEWED identity is represented as reviewed_bytes
[ ] persisted REVIEWED bytes equal reviewed_bytes exactly
[ ] no text-mode/EOL transformation can alter formal dataset bytes
[ ] manifest dataset_hash is derived from reviewed_bytes identity
[ ] final-file reread cannot substitute a different seal identity
[ ] post-gate/pre-manifest tamper fails closed
[ ] invalid --version remains zero-side-effect blocked
[ ] pre-commit publish failures clean new version/evidence/temp
[ ] same version retry after failed uncommitted publish is deterministic
[ ] review lineage concurrency policy is explicit
[ ] old CA/Raw/Bound-Rule/Golden contracts remain green
[ ] current GitHub Actions all three legs green
[ ] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR match runtime
[ ] management docs contain exact SHAs, not “本批提交”
[ ] RISK-004 remains REOPENED until this Reviewer gate passes
```

若全部满足且无新的 formal correctness regression，下一轮应结束连续 R4-A2.x / CR-1.x closure 审计链：

```text
R4-A2.x / CR-1.x -> VERIFIED
CR-2             -> may start
R4-A3            -> may start/re-evaluate
```

但：

```text
Production P0-M-1B remains BLOCKED
```

直到额外满足：

```text
Golden Truth human review
Trading Rule human review using verified seal workflow
formal Production Account Profile
Provider Doctor actual runtime verified
formal entry gates
```

---

# 11. 禁止事项

本批 VERIFIED 前禁止：

```text
CR-2 Provider-Normalized main implementation
R4-A3 formal dependent implementation
Production P0-M-1B
```

同时禁止：

```text
用 .gitattributes 代替 runtime review output 的 byte-exact write
用 text normalization test 代替 byte-level identity test
继续用 final-file reread bytes 定义 manifest identity
通过 skip/optional 化测试掩盖 generated-byte failure
把 orphan finalized version 当作“无害日志”而忽略 retry 语义
修改已经冻结的 CA/Raw/Bound Rule 架构来绕过本轮问题
```

允许并行：

```text
Golden / Trading Rule 官方 source artifact 准备
formal account 外部准备
CR-2/R4-A3 design-only analysis（不启动受本门依赖的正式实现）
```

---

# 12. 建议 Change IDs

```text
DM-CR-20260825-022 — Persisted REVIEWED Exact-Byte Identity
DM-CR-20260825-023 — Manifest Seal Identity / Publish TOCTOU Closure
DM-CR-20260825-024 — Review Publish Failure Cleanup / Retry Semantics
DM-CR-20260825-025 — Review Single-Writer / Commit-Lineage Policy
DM-CR-20260825-026 — R4-A2.9 Reviewer Governance Correction
```

---

# 13. Reviewer 下轮复查重点

下一轮只重点查：

```text
1. review.py 是否生成 reviewed_bytes，并用 write_bytes 持久化 formal rule dataset
2. generated REVIEWED file 在 Windows/Ubuntu 是否 byte-identical / LF-stable
3. manifest.dataset_hash 是否来自 reviewed_bytes，而不是 final reread
4. rename 后注入 tamper 是否只能 FAIL CLOSED，绝不能被 manifest 重新 hash/祝福
5. manifest write/replace failure 后是否无 orphan finalized version，same-version retry 是否成功
6. --version confinement / ACTIVE input snapshot 是否无回归
7. CA / Raw / Bound Rule / Golden contracts 是否无回归
8. current HEAD Actions 三腿是否全绿
9. DEVELOPMENT_MANAGEMENT 是否改为 exact SHA + R4-A2.9 REOPENED + R4-A2.10 active
10. RISK-004 是否直到 Reviewer VERIFIED 前保持 REOPENED
```

---

# 14. Implementation Mapping（Developer 回填，2026-08-25）

> 本批：R4-A2.10 Review Publish Byte-Identity + CR-1.2.6 Review Publish Integrity（Batch A→F 全部完成；**未启动 CR-2 / R4-A3**——遵守 §11 禁止项）。
> 测试基线：**650 passed / 0 failed**（639 → 650，+11）；CI 等价四检查（ruff check + format --check + mypy + pytest）本地全绿；dry-run 冒烟 35 exchanges + 5 bundles 双向闭合零问题。
> Change IDs：DM-CR-20260825-022/023/024/025/026；**ADR-018**（amendment to ADR-017；§0 修正记录 + 审计四问完整记录）。
> CI：本批提交后以 Actions 实际结果为准（上批 run 45/46 已全三腿 success；本批新增 generated-byte 测试随 matrix 在两 OS 执行——测试对象是**工具生成的**数据集，非仓库已提交 yaml）。
> **§11 四问对照**：见 ADR-018 §1 备选取舍表（write_bytes vs write_text+newline 参数 vs .gitattributes vs 文本行等价）、§2（reread-as-verification vs 不读）、§3（commit boundary 状态机 vs 分布式事务）、§4（Option A lock + CAS 局限诚实声明 vs Option B recheck）。

## P0-01（Persisted Byte Identity，§2）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 2.2 reviewed_bytes 显式不可变对象 | `review.py`：`reviewed_bytes = reviewed_text.encode("utf-8")`（一次编码，全程唯一身份） | integrity::TestPersistedByteIdentity |
| 2.2 全部 dataset 写入 write_bytes | sandbox `sandbox_yaml.write_bytes(reviewed_bytes)`；staged `staged_yaml.write_bytes(reviewed_bytes)` | 同上 |
| 2.3 Windows CI 无 CRLF | byte-level 断言（read_bytes 直接比较——非 read_text/splitlines） | integrity::test_final_bytes_lf_only_and_equal_reviewed_bytes（`b"\r\n" not in final_bytes` + `final_bytes == 独立重建的 reviewed_bytes`） |
| 2.3 Ubuntu CI 同（两 OS matrix 均跑） | 测试是纯 pytest，随 CI matrix 在 Windows+Ubuntu 执行 | CI matrix 本身 |
| 2.3 persisted final bytes == reviewed_bytes | read-back verification（实现）+ 独立重建断言（测试） | 同上 + test_manifest_hash_derives_from_reviewed_bytes |
| 2.3 formal write path 禁 write_text | **AST 静态守卫**（review.py 全文件禁 `write_text` 调用——文本模式在构造上排除） | integrity::test_formal_dataset_writes_use_write_bytes_only |
| 2.3 另一平台 replay hash 一致 | 生成版本经 load_active_rules + load_bound_rule_book（dataset_version/source/review 完整身份）重放 | integrity::test_generated_version_replays_on_lf_semantics |

## P0-02（Manifest Seal Identity，§3）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 3.2 expected hash 从 reviewed_bytes 派生 | `expected_dataset_hash = _hash_snapshot([(final_rel, reviewed_bytes)])`（Phase 3 内、rename 前） | integrity::test_manifest_hash_derives_from_reviewed_bytes（独立重算一致） |
| 3.2 read-back = verification only | `actual_final_bytes != reviewed_bytes` → `_cleanup_uncommitted()` + BLOCK（ACTIVE 不推进） | integrity::test_post_rename_tamper_fails_closed_and_rolls_back |
| 3.3 rename 后 tamper 不能被祝福 | monkeypatch Path.replace：rename 后写 tampered bytes → fail closed + version_dir 回滚 + ACTIVE 保持 v1-compiled + dataset_files 不变 | 同上 |
| 3.3 manifest 不因 read-back mismatch 推进 | rollback 路径显式 | 同上 |
| 3.3 manifest.dataset_hash == hash(final_rel + reviewed_bytes) | 构造保证 + 测试独立重算 | test_manifest_hash_derives_from_reviewed_bytes |
| 3.3 tamper 后 clean retry 确定性 | rollback 移除 version_dir → 同版本重试成功 | test_tampered_retry_is_deterministic |

## P1-01（Failure Cleanup，§4）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| 4.1 commit boundary 状态跟踪 | `published_version` / `created_evidence` / `manifest_committed` + `_cleanup_uncommitted()` | 见下 |
| 4.1 manifest write 失败 → 旧 ACTIVE + 无新 version + 无孤儿 evidence/tmp + 同版本重试 | 注入 tmp manifest write 失败 → 异常传播前完整清理 | integrity::test_manifest_write_failure_full_cleanup_and_retry |
| 4.1 manifest replace 失败同上 | 注入 replace 失败 | integrity::test_manifest_replace_failure_full_cleanup_and_retry |
| 4.1 post-commit 显式硬失败 | `REVIEW_COMMIT_INCONSISTENT`（exit 3；manifest hash/selector 不符或 coherence 失败时） | （commit 后路径——注入点在 load 阶段，代码路径明确区分 exit 3） |

## P1-02（Single-Writer，§5）

| 要求 | 实现位置 | 测试 |
|---|---|---|
| Option A lock 覆盖全程 | `rules_root/.review.lock`（O_CREAT\|O_EXCL；含 pid+时间戳）在 preflight 后、workflow 前创建；finally 释放 | integrity::TestSingleWriterLock |
| 并发 fail fast | FileExistsError → 明确错误（含 stale lock 手动清理指引） | test_concurrent_review_blocked_by_lock（零 mutation + 外来锁不被删） |
| lock 释放（成功/失败） | finally 块 | test_lock_released_after_successful_run / after_failed_run |
| CAS 局限诚实记录 | ADR-018 §4（advisory + 进程级；stale lock 人工清理；--from-version 降级为 lineage 提示） | — |

## §6 CI（回归要求）

| 要求 | 落实 |
|---|---|
| 6.2 generated-review-byte 测试两 OS 执行 | TestPersistedByteIdentity 全部为生成数据集的 byte-level 测试（非 .gitattributes 规范化的已提交 yaml）；随 CI matrix Windows+Ubuntu 执行 |
| 6.1 当前 CI 真相 | 总册头部：run 46（Reviewed HEAD 8a6f4149）全三腿 success；不再写"optional Ubuntu 仍失败" |

## §7 Governance（DM-CR-20260825-026）

| 要求 | 落实 |
|---|---|
| 7.1 exact SHA | 总册头部三元组：Reviewed HEAD `8a6f4149e0f7090850b77c3b2e6a804b8ef45595` / Primary Implementation `793dfc1220e3d1b8669483c008a8596150b0dcd6` / Cross-Platform CI Fix `b429220663897060b7940c727d0e09ec902192de`；本批 implementation SHA 由同批后续 docs commit 记录（Reviewer doc commit 不误写为 baseline） |
| 7.2 状态 | §40：R4-A2.9 → REOPENED（输入侧冻结+输出侧由 R4-A2.10 修复）；R4-A2.10 → PENDING_REVIEW；RISK-004 保持 REOPENED |
| 7.3 ADR correction | ADR-018 §0 修正记录（ADR-017 不变量只完成到 transformed logical content；本批闭合两环）+ 索引标注 amended by；历史原文保留 |

## §9 Minimum Acceptance Matrix 对照

```text
9.1 Input seal（保持）: [x] snapshot 一次捕获 [x] hash 用捕获字节 [x] 篡改先于输出阻断 [x] 无双读替换（既有 7 项测试全保持通过）
9.2 Persisted output byte identity: [x] reviewed_bytes 显式对象 [x] staged 用 write_bytes [x] final == reviewed_bytes [x] 无 CRLF [x] byte-level 两 OS
9.3 Manifest identity: [x] hash 源于 reviewed_bytes [x] reread 仅验证 [x] post-gate tamper fail closed [x] mismatch 不推进
9.4 Failure cleanup: [x] write 失败旧 ACTIVE [x] replace 失败旧 ACTIVE [x] 无 finalized 新 version [x] 无孤儿 evidence/tmp [x] 同版本重试确定性
9.5 Existing contracts: [x] unsafe --version（17 项保持）[x] bound lexical-first [x] golden artifact 平台无关 [x] CA 原子边界 [x] raw closure/recovery [x] exact replay（全量 650 绿）
9.6 CI: [x] ruff/format/mypy/pytest 本地全绿 [~] 三腿 Actions 以本批提交后实际结果为准 [x] generated byte-identity 测试参与两 OS
```

## §10 Exit Gate 自检

```text
[x] validated ACTIVE snapshot identity remains exact（输入侧冻结保持）
[x] transformed REVIEWED identity represented as reviewed_bytes
[x] persisted REVIEWED bytes equal reviewed_bytes exactly（byte-level 断言）
[x] no text-mode/EOL transformation can alter formal dataset bytes（write_bytes only + AST 守卫）
[x] manifest dataset_hash derived from reviewed_bytes identity
[x] final-file reread cannot substitute a different seal identity（verification-only）
[x] post-gate/pre-manifest tamper fails closed（对抗测试）
[x] invalid --version remains zero-side-effect blocked（保持）
[x] pre-commit publish failures clean new version/evidence/temp（注入测试 ×2）
[x] same version retry after failed uncommitted publish is deterministic
[x] review lineage concurrency policy is explicit（Option A lock + CAS 局限记录）
[x] old CA/Raw/Bound-Rule/Golden contracts remain green（全量 650）
[~] current GitHub Actions all three legs green —— 上批 run 46 已三腿 success；本批提交后以实际结果为准（不预写）
[x] DEVLOG / DEVELOPMENT_MANAGEMENT / ADR match runtime（同批更新）
[x] management docs contain exact SHAs（三元组 + 本批 SHA 由 docs commit 记录）
[x] RISK-004 remains REOPENED until this Reviewer gate passes
```

已知开放项（如实声明）：Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED。
