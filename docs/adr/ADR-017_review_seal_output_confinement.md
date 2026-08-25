# ADR-017: Review Exact-Byte Seal + Output Confinement + Cross-Platform Byte Truth（R4-A2.9 / CR-1.2.5）

- 状态：ACCEPTED
- 日期：2026-08-25
- 依据：审计 R4-A2.8/CR-1.2.4 复审（裁决 REOPENED）→ R4-A2.9 / CR-1.2.5 开发工作要求（P0-01/02 + P1 + §5 CI truth）
- 关系：**amendment to ADR-016**（review 工具链的 seal 语义与输出边界收紧）
- 登记变更：DM-CR-20260825-017 / 018 / 019 / 020（管理总册 §61）

## 1. Review Exact-Byte Seal（P0-01，DM-CR-017）

**为什么**：旧实现两次独立读取 ACTIVE 文件——Read A 生成 REVIEWED 副本、
Read B（`_dataset_files_hash`）做 hash 复验。两者之间文件可被替换：hash
验证的是 Read B 的字节，封存的是 Read A 的字节（TOCTOU：swap→capture→
restore→verify→seal-tampered）。违反 review 工作流最基本的不变量：

> hash-validated ACTIVE bytes == bytes transformed == bytes sealed

**怎么改**：一次性 snapshot——`active_bytes = read_bytes()` 单次读取；
`_hash_snapshot([(rel, active_bytes)])` 用 manifest 同一算法对**内存字节**
计算；`_build_reviewed_text(active_bytes, ...)` 从**同一 snapshot** 构造
REVIEWED 副本。此点之后不再有任何对 ACTIVE 文件的第二次读取。工具输出
`sealed from ACTIVE snapshot sha256=<hash>` 供 reviewer 独立复核。

**备选与取舍**：
- 读两次但对两次结果做一致性比较（否——仍有第三窗口，且"验证的"与
  "封存的"仍可能不同字节序列）；
- 锁文件/OS 级 advisory lock（否——跨平台语义不一致，Windows/POSIX 行为
  差异大于收益）；
- **单次 snapshot（选）**——把"验证的字节"与"封存的字节"在构造上变成
  同一对象，TOCTOU 在结构上不可能。

**代价/收益**：snapshot 常驻内存（yaml 数 KB，可忽略）；换来 seal 身份
不可替换（对抗测试：preflight 后的读取返回篡改字节 → snapshot hash 复验
BLOCK，零输出；工具对 ACTIVE 文件的读取次数 = preflight + 恰好 1 次）。

## 2. Output Version Confinement（P0-02，DM-CR-018）

**为什么**：`--version` 未验证即拼入 `rules_root/versions/<version>`——
`../escape`、`foo/bar`、绝对路径、盘符样式可在 versions root 之外创建
目录/文件；且 mkdir/write 发生在部分校验之前（evidence 拷贝先于 version
冲突检查）。

**怎么改**：与输入 confinement 同一安全设计语言——**lexical first,
resolved confinement second, mutation last**：

```text
Step A（lexical，零 fs）: 单一组件语法 ^[A-Za-z0-9][A-Za-z0-9._-]*$，
    显式拒绝 '.'/'..'（分隔符/盘符/绝对路径在语法层即不可能）
Step B（resolved）: (versions_root/<id>).resolve() 必须位于 versions/ 内
Step C（顺序）: 全部确定性校验（ACTIVE 完整性/lineage/单文件/COMPILED/
    version 语法+confinement+不存在性/snapshot hash/artifact hash/
    REVIEWED 副本内存构建+临时沙箱解析）完成后才开始任何输出 mutation
```

**测试**：12 类非法 id（含 `.`/`..`/空/空格/前导连字符）→ 拒绝 +
**before/after 文件树快照零差异**（覆盖 versions/ 内创建与越界逃逸）；
既有版本冲突 → BLOCK 且**先于** evidence 拷贝（无部分输出）。

## 3. Staged Output / Failure Cleanup（P1，并入 017/018）

三阶段流（audit §4 的推荐顺序）：

```text
Phase 1 纯校验/snapshot（零输出 mutation）
Phase 2 staged 输出: evidence 内容寻址落位 + versions/.staging-<id>/ 中
    运行完整 review gate；失败 → 移除全部 staged 字节
Phase 3 publish: staging 目录原子改名为 versions/<id>/（不可变版本），
    ACTIVE manifest 最后原子替换
```

失败清理语义：gate 失败 → staging 目录与本次创建的 evidence 均移除、
无 finalized version、ACTIVE 不推进、无 temp 残留；失败后重试确定性
（同 root 重跑成功且恰好产出一个版本）。

## 4. Cross-Platform Byte Truth（CI 根因修复，DM-CR-019）

**为什么（Reviewer 下钻 job matrix 的实锤）**：run 42 的
`Lint & Type Check (ubuntu-latest / py3.14)` job 中 **Pytest step 失败**，
约 20 个测试同错：`ACTIVE trading rule dataset hash mismatch: declared
7dc5f627..., recomputed dd2219d2...`。根因是**真实跨平台 correctness
bug**，非环境依赖：`.gitattributes` 覆盖了 `data/golden/**`/`*.json`/
`*.jsonl` 但**漏了 `*.yaml`**——Windows checkout（autocrlf）把 LF 重写为
CRLF（本地 hash=7dc5f627 与 manifest 一致，Windows CI 通过），Ubuntu
checkout 保持 LF（重算 dd2219d2，失配）。golden 未挂恰因其已有 LF 规则。

**怎么改**：
1. `.gitattributes`：`*.yaml text eol=lf` + `*.yml text eol=lf`
   （规则数据集与 golden truth 同等字节精确治理）；同时
   `configs/trading_rules/evidence/** -text`（内容寻址 artifact 的 sha256
   即其名字，绝不允许 eol 归一化）；
2. 工作树 yaml 规范化为 LF（`git diff` 验证与 blob 字节完全一致）；
   `rule_manifest.json` 的 `dataset_hash` 以 LF 字节重算——新值
   `dd2219d2...` 与 Ubuntu 的重算值**完全一致**（两个平台自此同字节）；
3. 回归测试：规则 yaml 无 CRLF、.gitattributes 规则存在、工作树 ==
   git blob 字节。

**第二个平台依赖 bug（run 44 查证）**：hash 修复后 Ubuntu 仅剩
`test_absolute_artifact_ref_rejected` 失败——golden review gate 的
artifact confinement 用 `evidence_dir / ref` 后做 resolved 比较：Linux 上
`evidence_dir / "C:/evil.txt"` 是**相对**拼接（不逃逸，gate 报"不存在"
而非"越界"），Windows 上盘符使其绝对（被检出）。修复：`_verify_artifact`
先做**平台无关的 lexical 检查**（前导 `/`、盘符前缀、`..` 穿越——与其他
confinement 同一"lexical first, resolved second"设计语言），回归测试 ×2
（盘符/POSIX 绝对路径在两平台同拒）。

**政策记录（§5.2）**：本失败属于第 1 类（真实跨平台 correctness bug），
已修复并加回归；**不是**通过削弱 gate / skip 测试 / 删除 Ubuntu leg 制造
的绿色。CI 真相（job-level）：required Windows 3.12/3.14 PASS；optional
Ubuntu 3.14 Pytest 曾 FAIL（根因如上）；run 42 overall SUCCESS 仅因
`continue-on-error: ${{ !matrix.required }}` 策略——该策略保持不变。

## 5. 治理修正（DM-CR-020）

ADR-016 §3 曾声明"REVIEWED 副本从已验证 ACTIVE bytes 产生"——该声明在
double-read 缺陷修复前是 overclaim（验证与封存可被替换字节分离）。本 ADR
§1 为修正记录；ADR-016 原文保留为历史。Reviewer baseline：上一批
implementation `ada0eac2d973730605f7af65f57e72a22e1483c1`（run 42）。

## 6. 测试与验证

- **637 tests / 0 failed**（608 → 637，+29：exact-byte seal 7 +
  version confinement 14 + failure cleanup 4 + 跨平台回归 3 + review 工具
  既有 9 项适配后保持）；ruff check / format --check / mypy 全绿；
- dry-run 冒烟：35 meta-anchored exchanges + 5 bundles，闭合零问题；
- 提交后以 Actions 实际结果为准（重点观察 Ubuntu 3.14 leg 是否转绿）。
