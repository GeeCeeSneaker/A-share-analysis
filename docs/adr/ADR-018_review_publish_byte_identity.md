# ADR-018: Review Publish Byte-Identity + Manifest Seal from reviewed_bytes（R4-A2.10 / CR-1.2.6）

- 状态：ACCEPTED
- 日期：2026-08-25
- 依据：审计 R4-A2.9/CR-1.2.5 复审（裁决 REOPENED）→ R4-A2.10 / CR-1.2.6 开发工作要求（P0-01/02 + P1-01/02）
- 关系：**amendment to ADR-017**（输入侧 exact snapshot 已成立；本 ADR 闭合输出侧）
- 登记变更：DM-CR-20260825-022 / 023 / 024 / 025 / 026（管理总册 §61）

## 0. 修正记录（ADR-017 §1 的未完成部分）

ADR-017 声明的完整不变量：

```text
hash-validated ACTIVE bytes == bytes transformed == bytes sealed
```

在 R4-A2.9 批次只成立到：

```text
hash-validated ACTIVE bytes == transformed logical content
```

未成立的两环由本 ADR 闭合：

```text
transformed exact bytes == persisted REVIEWED bytes   （P0-01）
persisted REVIEWED bytes == manifest-sealed bytes     （P0-02）
```

ADR-017 原文保留为历史；以本 ADR 为准。

## 1. 为什么 text-mode output 破坏 byte identity（P0-01，DM-CR-022）

`_build_reviewed_text` 返回 `str`，旧实现用 `Path.write_text(...,
encoding="utf-8")` 落盘。Windows 文本模式会把 `\n` 翻译为平台换行：

```text
ACTIVE snapshot bytes      = LF（.gitattributes 已强制）
_build_reviewed_text       = LF logical text
Path.write_text on Windows = 可持久化为 CRLF bytes
```

于是 `persisted bytes != exact transformed bytes`。既有
`test_reviewed_content_derives_from_exact_snapshot` 用
`read_text().splitlines(keepends=True)` 断言——universal-newline 读取把
CRLF/LF 差异归一化，**文本等价测试对字节漂移盲**。

### 决策

```text
reviewed_text.encode("utf-8") → reviewed_bytes（单一不可变内存对象）
sandbox 解析 / staged rules.yaml / 全部正式 dataset 写入 → write_bytes ONLY
最终不变量链：
  validated ACTIVE snapshot bytes
    ↓ deterministic provenance transform
  reviewed_bytes（单一内存身份）
    ↓ write_bytes（无 OS 换行翻译）
  staged bytes ──atomic rename──> final REVIEWED bytes
```

### 备选与取舍

| 备选 | 不选原因 |
|---|---|
| 继续用 write_text + `newline="\n"` 参数 | 仍依赖每个调用点记得传参；write_bytes 在构造上排除翻译，不靠纪律 |
| 用 .gitattributes 规范化生成物 | 审计 §11 明令禁止（runtime output 的 byte-exact 不能外包给 checkout 配置；且 .gitattributes 只作用于 git 传输，不作用于工具直接写盘） |
| 文本行等价测试当作字节等价 | universal-newline 归一化使测试失真（正是本轮漏洞的检测盲区） |

### 代价/收益

代价：reviewed_bytes 全程携带（KB 级，可忽略）；任何未来输出路径必须
write_bytes（AST 静态守卫锁定：review.py 禁止 `write_text` 调用）。
收益：生成数据集在 Windows/Ubuntu **byte-identical**（LF-stable）；
manifest hash 可独立重算（测试证明）。

## 2. 为什么 final reread 不得定义 manifest identity（P0-02，DM-CR-023）

旧 Phase 3：

```python
staging_dir.replace(version_dir)
published_bytes = (version_dir / "rules.yaml").read_bytes()   # 新的 fs read
manifest["dataset_hash"] = _hash_snapshot([(final_rel, published_bytes)])
```

对抗场景（审计 §3.1）：gate 验证 R（T1）→ rename（T2）→ final 被替换为
T（T3）→ reread 得 T（T4）→ manifest 封存 hash(T)（T5）→ ACTIVE 指向 T
且 load_active_rules 通过（T7）——**gate 验证了 R，manifest 祝福了 T**。
这是 R4-A2.9 已修的输入侧 double-read TOCTOU 在输出侧的镜像。

### 决策

```text
manifest identity 的唯一来源 = gate-validated in-memory reviewed_bytes：
    expected_dataset_hash = _hash_snapshot([(final_rel, reviewed_bytes)])
publish 后 read-back 仅作 VERIFICATION：
    actual_final != reviewed_bytes → BLOCK + rollback（ACTIVE 不推进）
```

read-back 的角色被构造性地限定为"验证持久化字节 == 期望封存字节"，
不可能变成"读取任意当前字节来定义 manifest 身份"。

### 备选与取舍

- rename 前把 hash 算好、rename 后不读（否——放弃了"持久化字节确实等于
  期望"的免费完整性校验；read-back-as-verification 零成本且防 rename
  窗口替换）；
- 对 final 文件做 open+fcntl 锁（否——跨平台语义不一致）。

## 3. Publish 失败清理 / commit boundary（P1-01，DM-CR-024）

明确 commit boundary：**ACTIVE manifest 原子替换成功 = 提交点**。

```text
提交前（uncommitted）失败 → 移除：新 published version_dir、本次创建的
  evidence、staging、tmp manifest；ACTIVE 保持旧 selector；同版本重试可行
  （published_version / created_evidence / manifest_committed 状态跟踪驱动）
提交后失败 → 显式 REVIEW_COMMIT_INCONSISTENT 硬失败（exit 3）：
  ACTIVE 已指向新版本，任何不一致需要人工介入，绝不伪装成可重试失败
```

注入测试：tmp manifest write 失败 / manifest replace 失败 → 完整清理 +
同版本重试成功。

## 4. Single-Writer Lock（P1-02，DM-CR-025，Option A）

`rules_root/.review.lock`（`O_CREAT|O_EXCL`）覆盖
preflight → snapshot → staged gate → manifest commit 全程；并发 reviewer
fail fast；finally 释放。

**诚实记录**：这是 advisory + 进程级锁，**不是 OS-level CAS**——崩溃后的
stale lock 需人工删除（错误信息指明路径）；check 与 replace 之间仍非原子
CAS，正式并发写由"single writer"运维契约兜底。`--from-version` 仅是
lineage 提示，从不构成并发 CAS（本 ADR 明确降级其语义）。

## 5. 测试与验证

- **650 tests / 0 failed**（639 → 650，+11：persisted byte identity 4 +
  publish-window tamper 2 + pre-commit cleanup 2 + single-writer lock 3）；
  ruff check / format --check / mypy 全绿；
- byte-level 断言（read_bytes 直接比较 + 独立重算 manifest hash +
  LF-only + AST 禁 write_text）；生成版本经 load_active_rules /
  load_bound_rule_book 重放验证（跨平台字节真相）；
- CI：本批提交后以 Actions 实际结果为准（上一批 run 45/46 已全三腿
  success；本批新增的 generated-byte 测试随 matrix 在两 OS 执行）。
