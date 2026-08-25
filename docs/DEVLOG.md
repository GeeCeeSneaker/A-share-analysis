# 开发日志（DEVLOG）

> **维护规则**（第三轮审查 §1-§4 固化 + R4-A1.1 复核 §2.3/§2.4 更新）：
> - 本文件是项目**唯一**滚动开发日志；每次代码推送同步在顶部追加条目（倒序），不覆盖历史。
> - 专题报告仅限：M0 Exit / Provider Spike / P0a Exit / P0b Exit / Backfill Exit / 重大 Incident / 重大架构决策。
> - 每个条目区分 **Implementation Status**（DONE / IN_PROGRESS / BLOCKED）与 **Review Status**（PENDING_REVIEW / VERIFIED / REOPENED）——"代码写完" ≠ "审计关闭"。
> - CI DEVLOG gate 实际覆盖路径（与 `.github/workflows/ci.yml` 同步）：
>   `src/` · `migrations/` · `configs/` · `scripts/` · `data/golden/` · `.gitattributes` · `.github/workflows/`。
> - **Contract 路径**（C1，变更必须同时更新 `docs/project/DEVELOPMENT_MANAGEMENT.md`）：
>   `data/golden/**` · `migrations/**` · `docs/adr/**` · `src/ashare_state/spike/capabilities.py` ·
>   `src/ashare_state/spike/golden_store.py` · `src/ashare_state/pipeline/publish.py` · `src/ashare_state/identity/security_id.py`。
> - **时间标准**：条目时间使用 `YYYY-MM-DD HH:mm +08:00`（Asia/Shanghai）或仅日期；不记录无时区的未来时间。

---

## 2026-08-25 · R4-A2.10 Review Publish Byte-Identity + CR-1.2.6 Review Publish Integrity（复审 2 项 P0 + 2 项 P1 + 治理修正）

**Scope**
- R4-A2.9/CR-1.2.5 复审裁决 REOPENED（工作要求 20260825 第六份）：输入侧 exact snapshot / version confinement / 跨平台 CI 修复**冻结保留**；输出侧两项 P0（write_text 字节身份 / publish 重读 TOCTOU）+ P1-01/02 + 治理修正；按 Batch A→F 全部完成（未启动 CR-2/R4-A3——遵守 §11 禁止项）

**Implementation**
- **P0-01 Persisted REVIEWED Exact-Byte Identity（DM-CR-20260825-022，ADR-018 §1）**：`reviewed_bytes = reviewed_text.encode("utf-8")` **单一不可变内存对象**；sandbox 解析 / staged rules.yaml / 全部正式 dataset 写入 **write_bytes ONLY**（Windows 文本模式换行翻译在构造上被排除）；**AST 静态守卫**（review.py 禁止任何 `write_text` 调用）；不变量链：validated ACTIVE snapshot → deterministic transform → reviewed_bytes → write_bytes → staged → atomic rename → final 全程字节同一
- **P0-02 Manifest Seal Identity / Publish TOCTOU Closure（DM-CR-20260825-023，ADR-018 §2）**：manifest dataset_hash 唯一来源 = gate-validated **in-memory reviewed_bytes**；publish 后 read-back **仅 VERIFICATION**（`actual != reviewed_bytes` → BLOCK + rollback：移除已 publish 的 version_dir 与本次 evidence，ACTIVE 不推进）——旧实现 rename 后重读 final 并以其计算 manifest hash（"gate 验证 R / manifest 祝福 T"的 TOCTOU）在构造上不可能
- **P1-01 Publish Failure Cleanup / Commit Boundary（DM-CR-20260825-024，ADR-018 §3）**：**commit boundary = ACTIVE manifest 原子替换成功**；`published_version`/`created_evidence`/`manifest_committed` 状态跟踪驱动 `_cleanup_uncommitted`——提交前任何失败（tmp manifest write/replace 注入 / read-back mismatch / gate 失败）→ 完整清理（无 finalized version / 无孤儿 evidence / 无 tmp 残留 / ACTIVE 保持旧）+ **同版本重试成功**（旧实现 rename 后失败会留下 immutable collision 永久阻断重试）；提交后验证失败 → 显式 **REVIEW_COMMIT_INCONSISTENT 硬失败（exit 3）**，绝不伪装成可重试失败
- **P1-02 Single-Writer Lock（DM-CR-20260825-025，ADR-018 §4，Option A）**：`rules_root/.review.lock`（`O_CREAT|O_EXCL`）覆盖 preflight → snapshot → staged gate → manifest commit 全程；并发 reviewer fail fast（指明 stale lock 手动清理路径）；finally 释放；**诚实记录**：advisory + 进程级，非 OS-level CAS——`--from-version` 语义降级为 lineage 提示
- **治理修正（DM-CR-20260825-026）**：总册头部改为 **exact SHA 三元组**（Reviewed HEAD `8a6f4149` / Primary Implementation `793dfc1` / Cross-Platform CI Fix `b429220`——Reviewer doc commit 不再误写为 implementation baseline）；§40 R4-A2.9 → REOPENED（输入侧冻结+输出侧由本批修复）；RISK-004 理由更新保持 REOPENED；ADR-018（ADR-017 §1 未完成环的修正记录；含审计四问完整记录：text-mode 为何破坏字节身份 / final reread 为何不得定义 identity / write_bytes+in-memory expected hash 的备选取舍表 / commit boundary 与 lock 的 CAS 局限诚实声明）

**Schema / Contract Changes**
- C1 ×5（DM-CR-022/023/024/025/026）；ADR-018（amendment to ADR-017）
- review.py 重构：workflow 拆分为 lock 覆盖的 `_review_locked_workflow`（状态跟踪 + commit boundary + exit 3 语义）；manifest hash 派生源变更（published reread → reviewed_bytes）

**Verification**
- Local: **650 tests passed / 0 failed**（639 → 650，+11：persisted byte identity 4 + publish tamper 2 + pre-commit cleanup 2 + single-writer 3）；ruff check / ruff format --check / mypy 全绿（CI 等价四检查）
- dry-run 冒烟：35 meta-anchored exchanges + 5 bundles，整 run 双向闭合零问题
- byte-level 对抗验证：生成 REVIEWED 文件 == 独立重建的 reviewed_bytes（LF-only）；manifest hash 独立重算一致；生成版本经 load_active_rules/load_bound_rule_book 重放（跨平台字节真相）；rename 后注入 tamper → fail closed + rollback + 同版本重试成功
- GitHub Actions: 本批提交后触发；**以 Actions 实际结果为准**（上一批 run 45/46 已全三腿 success；本批新增 generated-byte 测试随 matrix 在两 OS 执行）

**Implementation Status**
- DONE（R4-A2.10 / CR-1.2.6 全部 P0 + P1 + 治理修正）

**Review Status**
- PENDING_REVIEW（对照工作要求 §10 Exit Gate 15 项与 §13 Reviewer 下轮 10 项复查重点）

**Known Open Issues**
- Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED——seal workflow 已完整：输入 exact snapshot + 输出 byte identity + manifest 派生 + lock）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED

**Next**
- 推送 git + CI 确认（三腿）→ Reviewer 复审 R4-A2.10/CR-1.2.6；若 VERIFIED 则 R4-A2.x / CR-1.x closure 审计链结束，CR-2 / R4-A3 可启动

---

## 2026-08-25 · R4-A2.9 Review-Seal Exactness / Cross-Platform CI Closure + CR-1.2.5 Output Confinement（复审 2 项 P0 + P1 + CI 根因修复）

**Scope**
- R4-A2.8/CR-1.2.4 复审裁决 REOPENED（工作要求 20260825 第五份）：三个原始 P0 主体冻结（collector.call 原子边界 / lexical-first / review preflight 保留）；新增 P0-01/02 + P1 + §5 CI 真相；按 Batch A→F 全部完成（未启动 CR-2/R4-A3——遵守 §10 禁止项）

**Implementation**
- **P0-01 Review Exact-Byte Seal（DM-CR-20260825-017，ADR-017 §1）**：**一次性 snapshot**——`active_bytes = read_bytes()` 单次读取；`_hash_snapshot([(rel, bytes)])` 用 manifest 同一算法对**内存字节**计算（相等即证明 snapshot 就是 ACTIVE 字节）；`_build_reviewed_text` 从**同一 snapshot** 构造 REVIEWED 副本；此后**无任何 ACTIVE 文件第二次读取**（修正 ADR-016 §3 overclaim：旧实现 Read A 封存 / Read B 验证可被 swap→capture→restore→verify→seal-tampered 分离）；输出 `sealed from ACTIVE snapshot sha256=<hash>` 供 reviewer 独立复核
- **P0-02 Output Version Confinement（DM-CR-20260825-018，ADR-017 §2）**：`--version` = 单一安全组件（`^[A-Za-z0-9][A-Za-z0-9._-]*$`，拒 `.`/`..`/分隔符/盘符/绝对路径）→ lexical first → resolved confinement（versions/ 内）→ mutation last（**全部确定性校验**——含既有版本冲突——先于任何输出）
- **P1 Staged Output / Cleanup（并入 017/018，ADR-017 §3）**：Phase 1 纯校验/snapshot（REVIEWED 副本在系统临时沙箱解析——零 rule-store mutation）→ Phase 2 staged（evidence 内容寻址 + `versions/.staging-<id>/` 运行完整 gate；**gate 失败显式移除 staging+本次 evidence**——修复 `return` 在 try 内不触发 except 清理的坑）→ Phase 3 publish（staging 原子改名 versions/<id>/；ACTIVE manifest 最后原子替换；manifest dataset_hash 从 published bytes 计算）
- **CI 根因修复（DM-CR-20260825-019，ADR-017 §4）**：API 下钻 run 42 job matrix——`Lint & Type Check (ubuntu-latest / py3.14)` 的 **Pytest step 失败**（~20 测试同错 `ACTIVE dataset hash mismatch: declared 7dc5f627... recomputed dd2219d2...`）。**根因 1=真实跨平台 correctness bug**：`.gitattributes` 覆盖 data/golden/** 与 *.json/*.jsonl 但**漏 *.yaml**——Windows autocrlf checkout 重写 LF→CRLF（hash 与 manifest 一致故 Windows 过），Ubuntu 保持 LF（重算失配）；golden 未挂因已有 LF 规则。**修复**：`.gitattributes` 补 `*.yaml`/`*.yml text eol=lf` + `configs/trading_rules/evidence/** -text`（内容寻址 artifact 禁 eol 归一化）；工作树 yaml 规范化 LF（git diff 与 blob 字节零差异）；manifest dataset_hash 以 LF 字节重算（**dd2219d2... 与 Ubuntu 重算值完全一致**——两平台自此同字节）；跨平台回归测试 ×3。**根因 2（run 44 查证）**：golden review gate 的 artifact confinement 平台依赖——Linux 上 `evidence_dir / "C:/evil.txt"` 是相对拼接（不逃逸），Windows 上为绝对路径（被检出）；修复=`_verify_artifact` 先做**平台无关 lexical 检查**（前导 `/`、盘符、`..`），回归测试 ×2。**政策**：未削弱 gate / 未 skip 测试 / 未删 leg；continue-on-error 策略不变
- **治理（DM-CR-20260825-020）**：总册头部 Reviewed baseline `ada0eac2` + **CI job-level truth** + Reviewer Correction 段；§40 R4-A2.8/CR-1.2.4 → REOPENED（主体冻结+由本批修复）；RISK-004 理由更新保持 REOPENED；ADR-017（含 §11 四问完整记录：单次 snapshot vs 读两次比较 / 锁文件 / 严格组件语法 vs 任意相对路径 / 全校验先行 vs 增量 mutation / Windows 正式目标 + Linux 兼容 leg 的真实边界）

**Schema / Contract Changes**
- C1 ×4（DM-CR-017/018/019/020）；ADR-017（amendment to ADR-016）
- `.gitattributes`（yaml/yml LF + evidence -text）；`rule_manifest.json` dataset_hash 重算（dd2219d2...）；review.py 全量重构（三阶段流）

**Verification**
- Local: **639 tests passed / 0 failed**（608 → 639，+31：exact-byte seal 7 + version confinement 17 + failure cleanup/cross-platform 7 + golden artifact 平台无关 2 + 适配）；ruff check / ruff format --check / mypy 全绿（CI 等价四检查）
- dry-run 冒烟：35 meta-anchored exchanges + 5 bundles，整 run 双向闭合零问题
- 对抗验证：preflight 后 ACTIVE 读取返回篡改字节 → snapshot hash BLOCK（零输出）；工具对 ACTIVE 文件读取数 == preflight + 恰好 1；12 类非法 version id → before/after 文件树快照零差异
- GitHub Actions: **FULL MATRIX GREEN——run 45（`b429220`）Ubuntu 3.14 + Windows 3.12 + Windows 3.14 三 job 全部 success**（API positive confirmation；不再有被 continue-on-error 掩盖的失败 leg）。过程：run 44 验证根因 1 修复（20 个 hash 失配全消）但暴露根因 2（golden artifact confinement 平台依赖，仅剩 1 个 Linux 失败）→ 修复后 run 45 全绿

**Implementation Status**
- DONE（R4-A2.9 / CR-1.2.5 全部 P0 + P1 + CI 根因 + 治理修正）

**Review Status**
- PENDING_REVIEW（对照工作要求 §9 Exit Gate 16 项与 Reviewer 下轮 8 项复检重点）

**Known Open Issues**
- Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED

**Next**
- 推送 git + CI 确认（含 Ubuntu leg 转绿）→ Reviewer 复审 R4-A2.9/CR-1.2.5；VERIFIED 后可启动 CR-2 / R4-A3

---

## 2026-08-25 · R4-A2.8 Final Exchange-Boundary / Review-Lineage Closure + CR-1.2.4 Pre-Access Integrity（复审 3 项 P0 + P1 + 治理修正）

**Scope**
- R4-A2.7/CR-1.2.3 复审裁决 REOPENED（工作要求 20260825 第四份）：P0-01..P0-03 + P1-01/02 + §6 治理；按 Batch A→D 全部完成（未启动 CR-2/R4-A3——遵守 §10 禁止项）

**Implementation**
- **P0-01 Golden Atomic Exchange Persistence（DM-CR-20260825-013，ADR-016 §1）**：`_DomainCollector.call(fn) → PersistedExchangeView`（frozen：payload/request_id/endpoint/evidence_meta）——**call+persist 是一个边界操作**：exchange 在边界返回前已持久化（lineage 从 view 读取，不再持有裸 exchange 引用）；**全部域 fetch**（ST/DELISTED/LIMIT/CA/BJ）统一走原子边界，CA 的 assign-then-persist 窗口消除；**AST 守卫升级控制流安全**（exchange 调用必须位于 `collector.call(lambda: ...)` 内；负向测试证明旧 assign-then-persist 源码被拒）；**对抗测试**：dividend 成功+right_issue 失败→两者都持久化（call 数 == persisted 数）；首次 persist 失败→后续 provider call 不发射；dividend 失败→right_issue 不发射；full success lineage 指向精确 persisted exchange
- **P0-02 Bound Lexical-First Pre-Access（DM-CR-20260825-014，ADR-016 §2）**：`_lexically_confined_dataset_file`（Step A：非空/相对/无盘符/无 `..`/versions/<v>/ 结构——**零 fs 访问**）；`_confined_dataset_file` 成为**唯一入口**（Step A → Step B resolved symlink escape）；bound loop 删除前置 `_confined` 双 helper 并列；evidence ref 同加 lexical 前置拒绝；**Path.resolve spy 测试**：traversal/绝对/盘符/异版本目录的拒绝全程 candidate 未被 resolve
- **P0-03 Review Input Integrity（DM-CR-20260825-015，ADR-016 §3）**：review.py preflight **不可绕过**执行 `load_active_rules`（ACTIVE hash 复算 + 四字段 coherence——与 runtime 同一 gate）；增加 review_status==COMPILED 校验；REVIEWED 副本从**已验证 ACTIVE bytes** 产生（canonical 路径 + 读取后复验 hash，无 TOCTOU）；preflight 失败→**零输出**（无 evidence 拷贝/无 versions/<new>/无 manifest 变更）；§4.4：source_version/dataset_version REQUIRED 下沉 `load_rule_manifest` schema（单一 manifest API 契约）
- **P1-01/02（DM-CR-20260825-016）**：`CA_STREAM_ENDPOINTS` 固定映射交叉校验（跨流重标 → `CAProviderShapeError`）；`_payload_columns` 空 frame schema 契约（0 行+必需列=合法空事件流；0 行+缺列=`PROVIDER_SCHEMA`）
- **治理（DM-CR-20260825-016）**：总册头部 Reviewed baseline `47b47437` + run 40 SUCCESS + Reviewer Correction 段（CA control-flow / lexical-first 顺序 / review integrity 未关闭——ADR-016 为修正记录）；§40 R4-A2.7/CR-1.2.3 → REOPENED；RISK-004 理由更新保持 REOPENED

**Schema / Contract Changes**
- C1 ×4（DM-CR-013/014/015/016）；ADR-016（amendment to ADR-013/015：原子边界 / lexical-first / review preflight 三个不变量的收紧记录，含 §11 四问）
- `load_rule_manifest` schema 收紧（source_version/dataset_version REQUIRED——破坏性：缺字段的 manifest 现在被拒）

**Verification**
- Local: **608 tests passed / 0 failed**（580 → 608，+28：CA 原子边界 7 + lexical-first 9 + review 完整性 9 + 适配/守卫）；ruff check / ruff format --check / mypy 全绿（CI 等价四检查）
- dry-run 冒烟：35 meta-anchored exchanges + 5 bundles，整 run 双向闭合零问题（原子边界下 Spy 计数不变量保持）
- GitHub Actions: 本批提交后触发；**以 Actions 实际结果为准**（上批 run 40 = success，Reviewer API 确认口径）

**Implementation Status**
- DONE（R4-A2.8 / CR-1.2.4 全部 P0 + P1 + 治理修正）

**Review Status**
- PENDING_REVIEW（对照工作要求 §9 Exit Gate 15 项与 §12 Reviewer 复检 6 项重点）

**Known Open Issues**
- Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED

**Next**
- 推送 git + CI 确认 → Reviewer 复审 R4-A2.8/CR-1.2.4；VERIFIED 后可启动 CR-2 / R4-A3（原子边界/lexical-first/review preflight 契约已稳定）

---

## 2026-08-25 · R4-A2.7 Final Integrity / Provider-Shape Closure + CR-1.2.3 Evidence Identity Closure（复审 4 项 P0 + 2 项 P1 + 治理修正）

**Scope**
- R4-A2.6/CR-1.2.2 复审裁决 REOPENED（工作要求 20260825 第三份）：P0-01..P0-04 + P1-01/02 + §8 治理修正（exact SHA / run 38 / ADR-014 overclaim）；按 Batch A→F 全部完成（未启动 CR-2——遵守 §9/§12 约束）

**Implementation**
- **P0-01 Bound Pre-Access Confinement（DM-CR-20260825-008，ADR-015 §5.1）**：`load_bound_rule_book` 的 root 改为参数**确定性解析**（废除 `(root/dataset_files[0]).is_file()` 探测——篡改绑定 `../../outside.yaml` 曾在拒绝前发生一次越界 fs probe）；全文件 confinement（lexical + resolved + versions/<v>/ 结构）先于任何存在性/读取；**FsSpy 测试**（patch Path.is_file/read_bytes/open）证明 traversal（外部文件真实存在）/绝对路径/异版本目录的拒绝全程**零越界访问**
- **P0-02 Raw Evidence Identity（DM-CR-20260825-009，ADR-015 §5.2）**：完整幂等成功重试的返回身份改以**磁盘实际 bytes** 计算（`meta_path.read_bytes()`——旧实现返回新 serialization 的 hash，ingested_at 差异导致 SpikeCase 绑定后 evidence closure 必败）；fresh commit 断言 persisted == intended；幂等重试返回 existing persisted hash（不覆盖旧 meta——immutable 语义保留首次落盘）；失败幂等/orphan 恢复同规则
- **P0-03 Required Rule Coherence（DM-CR-20260825-010，ADR-015 §5.3）**：manifest source_version/dataset_version **必填非空 + 无条件精确比较**（"填了才比较"可选语义废除——空 manifest 字段曾走私真实 dataset lineage 且 new_run 绑定空 source_version）；`provenance_complete()` 纳入 dataset_version + source_version；`load_bound_rule_book` 增 source_version/review_status 复验（verdict/resume/rule_book 三处调用全传完整身份——bound 与 loaded 不一致即 BLOCK）
- **P0-04 CA Provider-Shape Adapter（DM-CR-20260825-011，ADR-015 §1-4）**：显式文档契约 `CA_PROVIDER_FIELD_CONTRACT`（get_dividend: MARKET_CODE/DATE_EX；get_right_issue: MARKET_CODE/EX_DIVIDEND_DATE——官方 3.5.7.1/3.5.7.2）；**ephemeral** `_ca_provider_view` 归一化（event_type=**端点身份**派生——payload 伪造的 EVENT_TYPE 列被忽略；view 携带 source_endpoint/raw_request_id lineage）；缺文档字段 → `CAProviderShapeError` → 结构化 `VALIDATED_FAIL(PROVIDER_SCHEMA)`；**FakeTarget 改 provider 原生字段**（dry-run 与 real 同一 adapter，canonical 旁路消除）；raw evidence 保持 provider 原生字段（parquet 列名断言 {MARKET_CODE, DATE_EX}）；validator v6；真实 v3 case + provider-shaped fixture 端到端 PASS
- **P1-01/02 Review Tool（DM-CR-20260825-012）**：review.py 显式单文件限制（multi-file ACTIVE → fail loud with clear message，Option A）；durability wording 更正（**atomic replacement / reader-safe**——非 power-loss durable，未做 fsync）
- **治理修正（DM-CR-20260825-012）**：总册头部 exact SHA（上批 implementation `2e85f447` + run 38 success）+ **Reviewer Correction 段**（ADR-014 overclaim 如实记录——bound 路径 pre-access confinement 与 required coherence 此前不成立，以 ADR-015 §5 修正为准，ADR-014 原文保留为历史）；§40 R4-A2.6/CR-1.2.2 → REOPENED（由本批修复）；RISK-004 理由更新并保持 REOPENED

**Schema / Contract Changes**
- C2 ×2（DM-CR-010 manifest 必填 coherence；DM-CR-011 CA provider-shape adapter 契约）+ C1 ×3（008/009/012）
- ADR-015（amendment to ADR-013 §4 + ADR-014 契约补全，含审计 §13 四问完整记录：为什么/怎么改/备选方案/代价收益）

**Verification**
- Local: **580 tests passed / 0 failed**（544 → 580，+36：raw identity 6 + pre-access confinement 4（含 FsSpy）+ required coherence 12 + CA provider-shape 13 + 适配）；ruff check / ruff format --check / mypy 全绿（CI 等价四检查）
- dry-run 冒烟：35 meta-anchored exchanges + 5 bundles，整 run 双向闭合零问题
- GitHub Actions: 本批提交后触发；**以 Actions 实际结果为准**（上批 run 38 = success，Reviewer API 确认口径）

**Implementation Status**
- DONE（R4-A2.7 / CR-1.2.3 全部 P0 + P1 + 治理修正）

**Review Status**
- PENDING_REVIEW（对照工作要求 §11 Exit Gate 14 项与 Reviewer 下轮 7 项复检重点）

**Known Open Issues**
- Golden / Trading Rule 人工 Review 未执行（OPEN / HUMAN ACTION REQUIRED）；Branch Protection 未启用；CR-2 / R4-A3 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED

**Next**
- 推送 git + CI 确认 → Reviewer 复审 R4-A2.7/CR-1.2.3；VERIFIED 后可启动 R4-A3 / CR-2（provider-shape / raw-evidence contract 已稳定）

---

## 2026-08-25 · R4-A2.6 Formal Truth/Manifest Closure + CR-1.2.2 Probe Exchange Enforcement（复审 4 项 P0 + 3 项 P1 + 治理修正）

**Scope**
- R4-A2.5/CR-1.2.1 复审裁决 REOPENED（工作要求 20260825 第二份）：P0-01..P0-04 + P1-01/02/03 + §9 治理修正（DEVLOG 矛盾 / exact SHA / §30-§40 状态统一）；按 Batch A→F 全部完成

**Implementation**
- **CR-1.2.2 Probe Exchange Enforcement（P0-01，DM-CR-20260825-004）**：B5/B6 code-list 前置改走 `executor.call()`——成功/失败都持久化、失败→结构化 case、异常不逃逸（B5 旧路径失败时 failure exchange 不落盘；**B6 旧路径连成功都不持久化**）；B6 依赖前置失败→stock_basic 不发射；**AST 双静态守卫**（probes 的 `ctx.target.*_exchange` 必须在 lambda 内；golden_router 的必须在 `collector.persist(...)` 内——approved boundary 显式化，不靠开发者记忆）；**Spy 计数闭合**：B2-B7 每个 probe 真实 exchange 调用数 == 持久化 raw meta 数
- **R4-A2.6 Golden CA Typed Truth（P0-02，DM-CR-20260825-005）**：**event_class（语义 hash 成员）成为类型事实源**（DIVIDEND_EX_DATE→DIVIDEND / RIGHT_ISSUE_EX_DATE→RIGHT_ISSUE）；expected_fields.event_type 冲突→fail closed；unknown/untyped→`EVENT_TYPE_UNRESOLVED` fail closed（**旧 untyped-accepts-any 测试删除并反转**）；类型比对强制（validator v5）；**actual-truth regression**：真实 golden v3 全部 20 个 CA cases（均 DIVIDEND_EX_DATE）解析为 DIVIDEND 并走 typed validator 端到端；right-issue-only 证据对真实 DIVIDEND case 产生 EVENT_TYPE_MISMATCH——synthetic-only 的状态终结
- **R4-A2.6 Rule Manifest Confinement（P0-03，DM-CR-20260825-006）**：`_confined_dataset_file` 在任何 fs 访问前执行（相对/无 `..`/无绝对/symlink resolve 后仍须在 root 内 + **必须位于 versions/<rule_version>/ 下**——selector 与版本目录结构一致）；ACTIVE（load_rule_manifest）与 bound（load_bound_rule_book）**共用同一 helper**（无两套规则漂移）
- **R4-A2.6 Metadata Coherence（P0-04）**：manifest↔dataset 四治理字段强制一致（review_status / source_version / review_provenance（语义等价：空值键豁免 + datetime 规范化）/ dataset_version）；**真实 manifest 的 source_version 不一致（审计 §5.1 实锤）已修正**；SpikeRun 绑定分离 `trading_rule_version`（selector id）与 `trading_rule_dataset_version`（yaml content version）+ source_version；load_bound 双版本复验
- **P1-01**：`provenance_complete()` 纳入 rule binding（selector + files + hash + review status）
- **P1-02**：review.py manifest **原子切换**（tmp + os.replace）+ `--from-version` 血缘检查（拒绝 ACTIVE 移动后的静默切换）+ 非 ACTIVE 输入拒绝 + 切换后 coherence 自验证
- **P1-03**：raw partial-orphan 集语义补全——present 成员字节一致的 same retry → **恢复**（补缺成员 + meta）；orphan 集含未声明成员 → **整集隔离**（绝不收养未知字节为证据）；quarantined bytes 不算 active orphan；恢复后 `verify_meta_closure == []`
- **治理修正（DM-CR-20260825-007）**：DEVLOG R4-A2.5 条目两处就地修正（CI 表述矛盾 + "v3 无需重封"的不实声明，均标注复审修正保留历史）；总册头部基线 exact SHA（上批 implementation 13d02a1 / 复审 HEAD cdd3608）；§30 重写为当前真相；§40 upstream 行全部改为 absorbed into R4-A2.6/CR-1.2.2（**不预写 PASS**）；RISK-004 保持 REOPENED 直到 Reviewer 验证本批

**Schema / Contract Changes**
- C2 ×1（DM-CR-20260825-006，manifest selector 契约收紧：confinement + coherence + 双版本绑定）；C1 ×3（004/005/007）
- SpikeRun 新增 trading_rule_dataset_version/source_version（旧 json 兼容读取）；configs/trading_rules/rule_manifest.json（source_version 修正 + provenance 补齐）；ADR-014（Rule Manifest Selector Contract）

**Verification**
- Local: **544 tests passed / 0 failed**（523 → 544，+21：probe enforcement 12 + manifest closure 16 + CA typed 真实 v3 回归 + partial-orphan 集 4 + provenance 3 等）；ruff check / ruff format --check / mypy 全绿（CI 等价四检查）
- dry-run 冒烟：全探针走 approved boundary；B2-B7 Spy 计数闭合零差异
- GitHub Actions: 本批提交后触发；**以 Actions 实际结果为准**（上批已 VERIFIED GREEN，run 35/36——Reviewer 确认口径保持）

**Implementation Status**
- DONE（R4-A2.6 / CR-1.2.2 全部 P0 + P1 + 治理修正）

**Review Status**
- PENDING_REVIEW（对照工作要求 §12 Exit Gate 15 项与 §15 复检重点）

**Known Open Issues**
- Golden / Trading Rule 人工 Review 未执行（RISK-001/005，结构就绪待人工）；Branch Protection 未启用；CR-2 / P0-M-1B 保持 BLOCKED 直到本批 VERIFIED

**Next**
- 推送 git + CI 确认 → Reviewer 复审 R4-A2.6/CR-1.2.2；Golden + Trading Rule 人工 review；VERIFIED 后启动 R4-A3 / CR-2

---

## 2026-08-25 · R4-A2.5 Formal Replay/Rule-SoR Closure + CR-1.2.1 Raw Commit Hardening（复审 5 项 P0 + P1 + CI 根因修复）

**Scope**
- R4-A2.4/CR-1.2 复审裁决 REOPENED（工作要求 20260825）：P0-01..P0-05 + P1（CR-1.2.1 raw commit recovery）+ §10 治理修正（CI 全红根因 / §30-31 状态改写 / R4-A2.3"提前 absorbed"修正）；Batch A→F 全部完成

**Implementation**
- **P0-01 全消费者 Rule Binding（DM-CR-20260825-001，ADR-013 §3）**：`validate_limit_rule(rows, *, book=...)` 的 book 改为**必填 keyword**（显式 None → 结构化 FAIL "book=None refused"）；B3/B5 传 `ctx.rule_book`；`route_all` 把 run-bound book 传入 limit/BJ 验证器；**AST 守卫**（formal 模块 validate_limit_rule 必带 book= 非 None、resolve_* 必带 book=）；**对抗测试**：ACTIVE 推进（v1 MAIN 10% → v2 20%）后同 run 重放 B5 limit cases 恒等、bound 仍解析 10%；bound 文件篡改 → `ctx.rule_book` 访问即阻断
- **P0-02 Trading Rule 版本模型（DM-CR-20260825-002，ADR-013 §1）**：`configs/trading_rules/` 迁移为 `rule_manifest.json`（ACTIVE 选择器：rule_version/review_status/dataset_files[]/dataset_hash/dataset_version/review_provenance）+ `versions/<v>/rules.yaml`（**不可变共存**）+ `evidence/`；`load(dir)` 只加载 manifest 声明文件（**目录 glob 合并语义废除**）；`load_active_rules` 复算 dataset_hash（**ACTIVE 篡改 → new_run 阻断**）；SpikeRun 绑定升级 `trading_rule_dataset_files[] + dataset_hash`（联合 hash=manifest 算法，**篡改任一绑定文件阻断 replay**；旧 run json 兼容读取）；review.py 重写（新 immutable 版本 + ACTIVE 切换 + evidence 内容寻址 + 副本自验证 + 重复 review 拒绝）
- **P0-03 Review Gate 加固（ADR-013 §2）**：`source_artifact_ref` 相对 **evidence root** 解析 + **path confinement**（绝对路径/`..` 穿越在任何 fs 访问前拒绝）；hash 必须 64 lower-hex；reviewed_at/source_retrieved_at 必须 ISO-8601；artifact bytes hash 复验保持
- **P0-04 CA Event Taxonomy（DM-CR-20260825-003，ADR-013 §4）**：事件分类学 DIVIDEND/RIGHT_ISSUE **两独立事件流**（provider `get_right_issue_exchange`；capability corporate_action）；golden case 以 `expected_fields["event_type"]` 声明期望类型；校验 (symbol, EX_DATE, **type**) 精确三元组——**DIVIDEND 永不替代 RIGHT_ISSUE**（`EVENT_TYPE_MISMATCH`，双向测试）；provider 字面量归一化（分红/配股/cash_dividend/rights_issue 等）；CA 域 fetch = calendar+status+dividend+**right_issue**+adj+kline 六 exchange 全入 bundle；`event_type` 为验证器元键（status 字段比对前剥离）；FakeTarget 600036.SH right-issue fixture（独立流验证）。**[2026-08-25 复审修正]** 本条目原表述"v3 数据无需重封"与实际不符：真实 golden v3 的 20 个 CA cases 均 **untyped**（event_class=DIVIDEND_EX_DATE 而 expected_fields 无 event_type），该批次的类型校验只对 synthetic 测试生效——由 R4-A2.6 P0-02 修复（event_class 成为类型事实源，untyped fail closed）
- **P0-05 B5/B6 载荷形状（ADR-013 §5）**：`_flat_values`（标量列表/单列 frame → 纯值列表；多列 **fail loud**）——修复旧路径把 row dict 强转 `"{'value': '600519.SH'}"` 垃圾字符串后静默"通过"；`_rows_of` polars 优先级修正（polars 无参 `to_dict()` 返回 {列: Series}，`list()` 之=列名垃圾行——改为优先 `.rows()`）；B5/B6 code_list 消费全部走 `_flat_values`
- **P1 CR-1.2.1 Raw Commit Recovery（ADR-013 §6，方案 A）**：orphan payload（字节在盘、meta 锚缺失）——**same-bytes retry → 提交恢复**（补落 meta，idempotent）；**different-bytes → `.quarantine/` 隔离 + BLOCK**（可取证、永不冒充有效证据）；partial orphan 同隔离；`list_orphan_payloads()` 巡检；fault-injection 测试（meta 写失败 → 无锚无残留 + retry 恢复；payload move 失败 → 无 meta 锚）
- **CI 根因修复（§10 治理）**：查证 `b7a84563..c7aa511` 共 8 个提交 CI 全红，根因 = **`ruff format --check` 门未过**（本地只跑了 ruff check）；本批修复全部 format 差异并本地验证 CI 等价四检查（ruff check + format --check + mypy + pytest）全绿；根因与整改记录入管理总册头部 CI Status + TD-007

**Schema / Contract Changes**
- C2 ×1（ADR-013 amendment to ADR-012）：规则数据集版本模型（manifest + immutable versions + 文件清单绑定）+ gate schema 加固 + CA 事件分类学 + CI format 门
- `validate_limit_rule` 签名收紧（book 必填，破坏性，调用方同批更新）；SpikeRun 绑定字段升级（旧 json 兼容）；configs/trading_rules 布局迁移（v20260824-compiled + rule_manifest.json）

**Verification**
- Local: **502 tests passed / 0 failed**（461 → 502，+41：rule binding 对抗 4 + 版本模型/绑定/gate 加固 24 + recovery 8 + CA event 8 + B5/B6 9 + TestLimitRule 适配）；
- ruff check / **ruff format --check** / mypy 全绿（CI 等价四检查）；dry-run 冒烟：34 exchanges 全 meta-anchored + 5 bundles，整 run 双向闭合零问题，right-issue 端点进 bundle
- GitHub Actions: **CONFIRMED GREEN**——run 35（13d02a1）三矩阵 success（API positive confirmation）。首推 f3694bd 曾再挂：**第二根因**=两个 capability-mode 测试无显式 identity 在无 SDK 的 CI 上触发 probe_identity 探测（本地装过 trial SDK 掩盖）；修复=显式 `_FakeIdentity` + 模拟无 SDK 环境（monkeypatch probe_identity 抛错）验证 13 passed；连同 9 连红的第一根因（format 门）一并终结

**Implementation Status**
- DONE（R4-A2.5 / CR-1.2.1 全部 P0 + P1 + 治理修正）

**Review Status**
- PENDING_REVIEW（对照工作要求 §16 Exit Gate 与 §17 复检重点）

**Known Open Issues**
- ~~CI 提交后待 Actions 确认~~（**2026-08-25 更正**：与本条目 Verification 段的 CONFIRMED GREEN 矛盾——CI 已确认绿，run 35/36 均 success）；Golden / Trading Rule 人工 Review 未执行（RISK-001/005，结构完全就绪待人工）；Branch Protection 未启用；CR-2 被复审置 BLOCKED 直到本批关闭

**Next**
- 推送 git + CI 确认 → Reviewer 复审 R4-A2.5/CR-1.2.1；Golden + Trading Rule 人工 review；R4-A3 / CR-2

---

## 2026-08-24 · R4-A2.4 Correctness Deepening + CR-1.2 Raw Exchange Closure（复审 6 项 P0 + P1 全修）

**Scope**
- R4-A2.3/CR-1.1 复审裁决 REOPENED（工作要求 20260824 第二份）：CR-1.1 四 P0 + R4-A2.4 两 P0（trading rule binding / CA event SoR）+ P1-01..04 + 文档治理；按 Batch A→E 全部完成

**Implementation**
- **CR-1.2 Complete Exchange + Raw Closure（P0-01/02 + P1，ADR-012，DM-CR-20260824-008）**：
  - 隐藏日历前置显式化（Option A）：calendar exchange 先持久化 → 窗口 trading_days 显式传入 kline（`RealTarget.query_kline_exchange(trading_days=...)`）；日历失败→失败 meta 落盘 + kline **不发射**（不伪造成功）；B3/B7 code_list/calendar 前置全部持久化 exchange
  - **证据锚定升级为 meta.json**：`RawWriteResult` 拆分 `payload_artifacts[]`（uri/content_hash/schema_hash/row_count）+ `meta_artifact`；SpikeCase 证据恒绑 exchange meta——payload+meta **双向闭合**（篡改/删除任一侧都 BLOCK；`verify_evidence_closure` 对 bundle→meta→payload 递归复验）
  - meta 持久化**完整脱敏 request_params** + params_hash（等长不同 symbols hash 不同——请求可重建）+ `ingested_at` + `ingest_run_id`（run 绑定追溯）
  - 多文件提交 **staging 原子化**（全部 payload 先落 staging → 逐个 os.replace → meta 最后落盘）；表名净化冲突 BLOCK；`read(verify=True)` 读前复验
  - AST 静态测试：probes.py / golden_router.py 禁止调用 payload-only target 方法（get_code_list / get_calendar / query_kline 等）；FakeTarget 产出真实 params（dry-run 覆盖 params 管线）
- **R4-A2.4 Trading Rule Binding + Review Gate（P0-03/04 + P1-04，ADR-012，DM-CR-20260824-009）**：
  - SpikeRun 绑定 `trading_rule_file/version/hash/review_status`（TRIAL/PRODUCTION 创建时）；`compute_config_hash` 递归 `configs/**`（嵌套规则文件进入配置指纹——审计 §4.1-A 复现验证：编辑嵌套文件改变 hash）
  - RUNNING/RESUME/VERDICT/REPLAY 只用 `load_bound_rule_book`（bytes hash + version 复验；工作树篡改/推进 → `RuleUnresolvedError` fail-closed）；`ProbeContext.rule_book`（run-bound）经 `route_all` 传入 limit/BJ 验证器
  - **Review Gate**：COMPILED→REVIEWED（reviewed_by/at + source_artifact_ref/hash/kind(allowlist)/retrieved_at 六字段 + artifact bytes hash 复验）；`new_run(PRODUCTION)` fail-fast + `compute_verdict(PRODUCTION)` 复核双执行；`scripts/rules/review.py`（reviewer 提供官方 artifact → 工具自算 SHA-256 写入 REVIEWED 副本 + 副本自验证 + 重复 review 拒绝）
  - `_parse_st_state` 严格解析：bool/"true"/"false"/"any" 之外 ValueError（`bool("false")==True` 的 truthiness 反转被禁止）
- **R4-A2.4 CA Event SoR（P0-05，DM-CR-20260824-010）**：CA 证据组合加入**事件事实源**（dividend records）：adj-only → `VALIDATED_FAIL(EVENT_SOURCE_MISSING)`（"adj-factor movement alone is not a sufficient event SoR"）；事件存在但 EX_DATE≠T → `EVENT_DATE_MISMATCH`；event+adj+kline 一致 → PASS；事件日停牌 → `NOT_TESTABLE_TIME`；FakeTarget `get_dividend_exchange`（事件端点进 dry-run 覆盖）；CA 域 bundle = calendar+status+dividend+adj+kline 五 exchange
- **R4-A2.4 静态守卫升级（P0-06）**：费率字面量守卫从字符串匹配升级为 **AST 结构化规则**（`spike/**/*.py` 禁止 `*_rate` 与数值常量直接比较；1e-9 容差豁免；负向验证确认能捕获 `!= 0.30` 旧模式）
- **文档治理（DM-CR-20260824-011）**：上批宣称与 runtime 的出入修正（BJ mapping endpoint 表述归正为 hist master + exact-date regime；CI 口径区分本地/Actions）；R4-A2.3/CR-1.1 条目归档 absorbed

**Schema / Contract Changes**
- C2 ×2（ADR-012 amendment to 010/011）：evidence 锚定 meta 化（双向闭合 + request 可重建 + ingest 绑定）；rule 数据集 run 绑定 + 审阅生命周期
- SpikeRun 新增 trading_rule_* 四字段（旧 run json 兼容读取）；scripts/rules/review.py（新）；tests 新增 test_raw_closure / test_cr12_exchange_completeness / test_trading_rule_binding / test_ca_event_sor

**Verification**
- Local: **461 tests passed / 0 failed**（420 → 461，+41：raw closure 13 + exchange completeness 7 + rule binding 14 + CA event SoR 6 + 静态守卫升级适配）；ruff / mypy 全绿
- dry-run 冒烟：B2-B7 全阶段；**33 exchanges 全部 meta-anchored + 5 bundles**；整 run `verify_evidence_closure`（bundle→meta→payload 递归双向）零问题
- GitHub Actions: 本批提交后触发，尚未确认（按 §49 口径区分 Local 与 CI）

**Implementation Status**
- DONE（R4-A2.4 / CR-1.2 全部 P0 + P1 + 文档治理）

**Review Status**
- PENDING_REVIEW（对照工作要求 §16 Exit Gate 12 项与 §17 复检重点）

**Known Open Issues**
- Golden v3 人工 Review 未执行（RISK-001/TD-005）；Trading Rule yaml 为 COMPILED（RISK-005——结构闭环已就绪，待人工以 scripts/rules/review.py 执行）
- CI 三矩阵待推送后确认；Branch Protection 未启用

**Next**
- 推送 git + CI 确认 → Reviewer 复审 R4-A2.4/CR-1.2；Golden + Trading Rule 人工 review 执行；R4-A3 / CR-2

---

## 2026-08-24 · R4-A2.3 Correctness Closure + CR-1.1 Runtime Closure（复审 9 项 P0 + P1 + 文档治理全修）

**Scope**
- R4-A2.2/CR-1 复审裁决 REOPENED（工作要求 20260824）：P0-01..P0-09 + P1（BSE/BJ 语义证明）+ §13 文档治理；按推荐顺序 Batch A→F 全部完成

**Implementation**
- **CR-1.1 显式 Exchange Runtime（P0-01/02/03，ADR-010，DM-CR-20260824-006）**：
  - `SpikeTarget`/`RealTarget`/`FakeTarget` 全套 `*_exchange` 显式 API（provider 层每业务方法 `*_exchange` 变体；FakeTarget 产出真实 ProviderExchange——dry-run 与 formal run 同管线）
  - 运行时证据链唯一正式路径：`exchange → RawWriter.write(exchange) → Parquet + .meta.json → RawWriteResult → SpikeCase.evidence_ref/evidence_hash`（evidence_type=RAW_PARQUET）；`payload → RunStore.write_evidence(JSON)` 退出正式证据链（保留兼容）
  - 失败 exchange 一等对象：`ProviderError.exchange`（call_exchange 附加 error envelope）；治理拒绝 `synthetic_failure_exchange`；`last_envelopes` 降级 diagnostic-only（**AST 级静态测试**强制 probes/golden_router/runner 不得访问）
  - `ProbeExecutor.call(fn)`：fn 必须返回 ProviderExchange（TypeError fail loud）；B7 request/retry 从 evidence meta 累计
  - RawWriter 载荷形状全支持：`list[dict]`/`dict[str,list[dict]]`/DataFrame(polars|pandas 鸭子类型)/`dict[str,DataFrame]`/`pyarrow.Table`/标量列表；dict-of-tables **方案 A**（每逻辑表独立 Parquet + meta 记录 name/file/content_hash/schema_hash/row_count）；混合/未知形状抛 `RawWriterError`（禁止静默取 dict 首值）；`write(exchange)` request_id 一致性断言 + envelope-first provider/dataset（冲突 BLOCK）
- **Golden Router 证据同源（P0-04）**：每 domain 全部 exchange 先持久化（`_DomainCollector.persist`）→ DomainData 从精确 payload 构建 → case 绑定 **evidence bundle**（`raw/bundles/<domain>-<id>.json` 列出全部 request_id/evidence_ref/content_hash）；LIMIT 域=status+hist+calendar 三 exchange；CA 域=calendar+status+adj+kline；`verify_evidence_closure` 对 bundle **递归复验**；domain fetch 失败→失败 exchange 入 bundle + 全部 case 按错误类结构化；`lambda:None` 伪调用删除（静态断言）
- **Bound Formal Gates（P0-05，DM-CR-20260824-005）**：`quantity_gate/event_coverage_gate/review_gate/production_formal_gate` 全部 bound-aware（`(cases, manifest)` 显式参数优先）；`compute_verdict` 对 bound 三 gate 全复验；旧 `production_formal_gate` 内部 ACTIVE 读与 `verify_binding`（ACTIVE 对比语义）删除；ACTIVE advance/tamper 双向对抗测试（8 个）证明历史 run verdict 完全独立
- **Trading Rule 数据层（P0-06，ADR-011，DM-CR-20260824-005）**：制度事实迁入 `configs/trading_rules/a_share_limit_v1.yaml`（9 条规则全字段，COMPILED 待人工 review）；Python 只 load/validate/PIT 匹配/冲突检测/resolve/Decimal；fail-closed 全链（0 匹配/>1 equally-valid/未知板别/缺 listing_date+calendar → `RuleUnresolvedError`，永不静默退化 MAIN 10%）；`validators.validate_limit_rule` v3 数据驱动（BOARD_LIMIT_RATES/board_of 硬编码删除；Python 源码费率字面量静态断言）
- **首 N 日 = session 序号（P0-07）**：`first_n_sessions` 用 PIT 交易日历 index（上市日=第 1 个 session）；日历缺行 fail-closed；测试覆盖春节/国庆长假/跨周末/第 5-6 日
- **Limit 精确匹配（P0-08）**：`(SECURITY_CODE, TRADE_DATE)` 精确匹配（0/多行 fail closed）；listing_date 必须来自同一 PIT hist master（缺失即 FAIL 不允许 None 退化）；限价 Decimal ROUND_HALF_UP 与 provider 高低限价一致（1 tick 容差）
- **CA T-1/T/T+1 真验证（P0-09）**：exact event date（adj EX_DATE==T）/ factor transition at T / raw discontinuity（factor≠1 时 raw_ret≠adj_ret）/ adjusted continuity（|adj_ret|≤35%，项目定义见 ADR-010）/ 停牌→`NOT_TESTABLE_TIME(SUSPENSION_AT_EVENT)`（绝不静默 PASS）
- **P1 BSE/BJ 独立语义证明**：hist master 存在性（code continuity）+ exact-date ±30% regime（数据驱动 rule + Decimal 价格校验）；不再依赖 mapping endpoint
- **文档治理（§13，DM-CR-20260824-005/006/007）**：DEVLOG + 管理总册同批更新（Current Code Baseline / Last Review / §40/41/43/48/52/53/56/61/62）；**ADR-010 Raw Evidence Model（C2）** + **ADR-011 Trading Rule Data SoR（C2）**；Reviewer Auto-Archive 规则并入总册 §56；工作要求文档回填 §20 Implementation Mapping（含 §17 Exit Gate 16 项自检）

**Schema / Contract Changes**
- C2 ×2：evidence model（RAW_PARQUET + bundle，ADR-010）、Trading Rules SoR（configs/trading_rules，ADR-011）
- 新增：configs/trading_rules/a_share_limit_v1.yaml、tests/{unit/test_trading_rule_data.py, unit/test_raw_writer_shapes.py, integration/test_cr11_explicit_exchange.py, integration/test_golden_router_evidence.py, integration/test_bound_formal_gates.py}
- 变更：providers/{exchange,errors}.py、providers/amazingdata/provider.py、storage/raw_writer.py、spike/{target,probes,golden_router,trading_rule,golden_store,validators,runner}.py

**Verification**
- Local: **418 tests passed / 0 failed**（348 → 418，新增 70：trading rule 数据层 21 + raw writer 形状 22 + 显式 exchange 10 + router 证据/CA/BJ 14 + bound gates 8——对照工作要求 §16 矩阵逐项覆盖）；ruff / mypy 全绿
- dry-run 冒烟：B2-B7 全探针走 exchange→RawWriter 管线；B4 123 cases 全路由绑定 bundle；evidence closure（含 bundle 递归复验）零问题
- GitHub Actions: 本批提交后触发，尚未确认（按 §49 口径区分 Local 与 CI）

**Implementation Status**
- DONE（R4-A2.3 / CR-1.1 全部 P0 + P1 + 文档治理）

**Review Status**
- PENDING_REVIEW（对照工作要求 §17 Exit Gate 16 项与 §18 复检重点）

**Known Open Issues**
- Golden v3 人工 Review 未执行（distinct events：ST_TRANSITION=10<50、DELIST symbols=10<20——candidate.py add-case 补齐；RISK-001/TD-005）
- trading rules yaml 为 COMPILED，P0-M-1B 前需人工复核置 REVIEWED（RISK-005）
- CI 三矩阵待推送后确认
- Branch Protection（P1 治理）未启用

**Next**
- 推送 git + CI 确认 → Reviewer 复审 R4-A2.3/CR-1.1；Golden 人工 review 执行；R4-A3 / CR-2（消费 raw evidence 的 Provider-Normalized）

---

## 2026-08-22 23:30 +08:00 · R4-A2.1 + R4-A2.2 + CR-1（复核四项 P0 全修 + 并行 Track B 启动）

**Scope**
- R4-A2 Batch-1 复核 REOPENED 的四项 Formal Truth P0（§2-19）+ P1-01~06（§20-29）+ R4-A2.2 Router/PIT（§34-40）+ CR-1 全部（§41-47）

**Implementation**
- **P0-01 review_gate 全量校验**：删除"第一条成功即 break"——现在遍历全部 REVIEWED cases 完整收集错误；first-valid-second-tampered / first-valid-later-missing 测试
- **P0-02 Bound Golden Resolver**：`GoldenTruthStore.load_bound()` 直读 immutable dataset 文件（ACTIVE 指针只决定 NEW run 的默认选择）；resume / verdict / B4 probe 全部改走 `run.golden_dataset_file + golden_dataset_hash`；ACTIVE 推进（review 出 v4）后历史 run 仍精确 replay（测试验证）
- **P0-03 Candidate Augmentation**：`scripts/golden/candidate.py`（add-case → validate → build-version 生命周期）；review workflow 只核验已有 candidate、绝不创建事件——"candidate 增事件 / review 验事件"职责分离；ST candidate 强制 subtype + event_effective_date
- **P0-04 Production fail-fast**：`new_run(PRODUCTION)` 执行 quantity + event + review 三 gate 全通过才允许创建（不再烧完流量才在 verdict 发现 golden 未 review）
- **P1 全修**：batch kind allowlist 统一校验；REVIEWED provenance 在 load 即完整校验（reviewer/at/ref/64-hex hash/kind/timestamp）；artifact ref path confinement（../ 与绝对路径拒绝）；版本文件 create-only（不同 bytes BLOCK）；batch stage-all-then-commit（失败零孤儿 evidence）；evidence 真正 content-addressed（`sha256/<full-hash>.<ext>`，方案 A）
- **R4-A2.2 Domain Router**（`golden_router.py`）：ST→history_stock_status；Delisted→hist_code_list+stock_basic（幸存者偏差证明）；Limit→status+PIT TradingRule；CA→status+adj+kline T-1/T/T+1；BJ→mapping endpoint——B4 从"123 cases 一次 status 调用泛化比较"改为按域路由
- **B3/B4 彻底分离**（§36）：B3 只做结构性校验，现场 `expected_is_st=False` 假设删除——语义 truth 只来自 B4 reviewed golden
- **PIT TradingRule**（`trading_rule.py`）：版本化 effective_from/to（主板 10%/ST 5%/创业板改革前后/科创板首 5 日/北交所 30%/新股 44%）；limit price 用 **Decimal ROUND_HALF_UP**（禁 float round）
- **History 固定 fixtures**（§38）：600519.SH / 000001.SZ / 835185.BJ / 300104.SZ（含历史退市）——不再 `get_code_list()[:2]`
- **BSE 独立 core evidence**（§40）：B5 专项 835185.BJ status 调用
- **事件 identity 结构化**（§13-16）：ST=(symbol, event_effective_date, subtype)、DELIST=(symbol, effective_date)——60 个自由字符串 event_id 合并为 1 个结构化 identity（测试证明无法凑数）
- **CR-1a ProviderExchange**：`1 exchange = 1 request_id = 1 envelope = ≤1 payload`；`call_exchange()` 显式返回（无 last_exchange/consume 模式）；业务 wrapper 取 `.payload`；hidden `query_kline→get_calendar` 独立 exchange
- **CR-1b RawWriter**（`storage/raw_writer.py`）：成功 → Parquet + meta.json；失败 → envelope-only 证据；same hash 幂等 / different bytes BLOCK；跨平台逻辑 URI；secret 脱敏；无 repr()
- **CR-1c Spike 迁移**：`ProbeContext.evidence` 复用 exchange request_id（不再重新生成 uuid）

**Schema / Contract Changes**
- GoldenCase：+event_effective_date；SpikeRun：+golden_dataset_file
- 新模块：providers/exchange.py、storage/raw_writer.py、spike/{golden_router,trading_rule}.py、scripts/golden/{candidate,review}.py
- DM-CR-003 Part 2 + DM-CR-004 记录（C1）

**Verification**
- Local: **348 tests passed**（+35：review-gate 全量 3 + bound resolver 4 + candidate 7 + provenance/confinement/immutability 6 + CR-1 13 + router/PIT 适配）；ruff/format/mypy 全绿
- GitHub Actions: 本批提交后触发，尚未确认（按 §49 口径区分 Local 与 CI）
- dry-run 冒烟：B4 domain router 123 cases 全路由；B3 ST=OBSERVED（无 fabricated truth）；B5 fixtures + BSE evidence 正常

**Implementation Status**
- DONE（R4-A2.1 / R4-A2.2 / CR-1 全部）

**Review Status**
- PENDING_REVIEW（对照 §57 下次评审范围与 §58/§59 Exit Gate）

**Known Open Issues**
- Golden Review Workflow 仍待人工执行（candidate → review → 补齐 ≥50 distinct ST + ≥20 distinct DELIST + REMOTE subtype）
- Branch Protection（§48，P1 治理）未启用——CR-A 前建议
- B6/B7 optional gate 未在本批范围

**Next**
- Golden 人工 review 流程执行；R4-A3（SDK 行为拆分 / Early Stop / auth terminal-state）；CR-2（Canonicalizer）

---

## 2026-08-22 18:00 +08:00 · R4-A2 第一批：Golden Review Evidence Closure

**Scope**
- R4-A2 §5-11（复核 REOPENED 的 Formal Truth Closure）+ Track B CR-1 接收

**Implementation**
- **Review Workflow**（`scripts/golden/review.py`）：唯一 COMPILED→REVIEWED 路径——reviewer 只提供外部证据工件文件，workflow 读取真实 bytes 计算 SHA256、内容寻址存入 `evidence/`、封存 ref/kind/retrieved_at 并重封 semantic hash；**CLI 无 --hash 参数**（§6"不允许手工填 hash"落地为接口事实）；支持 --manifest 批量与 --expect-fields 修正
- **Formal Review Gate**：`review_gate()` 对每个 REVIEWED case resolve artifact → bytes → SHA256 == sealed hash，否则 REVIEW_INCOMPLETE；封存后篡改工件 / ghost ref 均被拦截（测试覆盖）
- **Provenance 分离**（§7）：compiled_*/reviewed_* 独立字段；COMPILED case 带 reviewer 字段在 load 即失败
- **事件语义**（§9/§10）：event_class=ST_TRANSITION + subtype（ST_ADD/ST_REMOVE/STAR_ST_ADD/STAR_ST_REMOVE）；gate = ≥50 distinct + ADD>0 + REMOVE>0；DELIST = distinct event ≥20 AND distinct symbol ≥20
- **字段更名**（§11 方案 A）：SpikeRun.golden_dataset_hash（run_store/model 兼容 legacy key 读取）
- Dataset v3 candidate（compiled/reviewed 分离 + 新事件语义）；诚实覆盖不变（ST_TRANSITION=2<50 无 REMOVE、DELIST=10<20）——review workflow 是补齐的唯一路径

**Schema / Contract Changes**
- GoldenCase：+source_artifact_ref/kind/retrieved_at、+compiled_by/at、+review_note、+event_subtype
- SpikeRun：golden_manifest_hash → golden_dataset_hash（C1，DM-CR-003 记录）
- run_store.save_run 补 mkdir（latent bug 顺带修复）

**Verification**
- pytest: **313 passed**（+11 review workflow 契约测试；Local validation）
- ruff/format/mypy clean；review workflow 端到端 smoke 通过

**Implementation Status**
- DONE（R4-A2 第一批：Evidence Closure + 事件语义 + 更名）

**Review Status**
- PENDING_REVIEW

**Known Open Issues**
- R4-A2 剩余：Domain Router / PIT Limit Rule（Decimal ROUND_HALF_UP）/ B3 删现场假设 / History fixtures / BSE·BJ 独立证据
- CR-1（ProviderExchange + RawWriter）未开始

**Next**
- R4-A2 第二批（Router + PIT）与 CR-1 并行

---

## 2026-08-22 16:30 +08:00 · Management 批次修正 + R4-A2/CR-1 任务接收

**Scope**
- R4-A1.1 复核结论执行（Governance PASS_WITH_MINOR_FIXES / Truth Closure REOPENED）+ §2 四小项修正

**Implementation**
- DM-CR-20260822-001 → **VERIFIED**；新增 **DM-CR-20260822-002**（Adopt R4-A1.1 Golden Truth Integrity Contract，REOPENED——source artifact 证据未闭环）
- §41 去重（两段 R4-A2 合一，含 Golden Review Evidence Closure 与 ST_TRANSITION 语义）
- §33 Current Baseline Metadata（Code Baseline `8d7d4aa` + Document Revision + Last Review + 时间标准）
- DEVLOG 顶部：CI 实际覆盖路径同步（含 data/golden 等 7 路径）+ Contract 路径 C1 规则 + Asia/Shanghai 时间标准
- **Management CI Guard**（§34）：ci.yml 新增 contract 路径 gate（golden/migrations/adr/capabilities/golden_store/publish/security_id 变更必须同 commit 更新管理总册）+ 本地等价测试
- 任务书归档 docs/design/

**Verification**
- devlog gate 测试（含新 contract gate）3/3 passed；ruff clean

**Implementation Status**
- DONE（Management 批次）

**Review Status**
- PENDING_REVIEW（DM-CR-002 REOPENED 按复核结论如实记录）

**Next**
- R4-A2 Track A：Golden Review Evidence Closure → Domain Router → 事件语义 → PIT Limit
- CR-1 Track B 并行：ProviderExchange + RawWriter

---

## 2026-08-22 · 建立项目开发管理总册

**Scope**
- 初始化长期项目治理文档（Documentation Governance，P0 治理要求，不改 Frozen Baseline）

**Implementation**
- 新建 `docs/project/DEVELOPMENT_MANAGEMENT.md`（固定路径，永不改名/不建副本）
- 按工作要求 §10 以最新 HEAD（`bb694c5`，R4-A1.1 已落地）同步初始化状态：§30/§31（Golden Truth v2 candidate + R4-A1.1 DONE/PENDING_REVIEW）、§40（状态表）、§41（最高优先 → R4-A2）、§52（RISK-001 部分缓解）、§62（检查点标注）
- 固化 Design/Progress/Change-Control/Entry-Gate 管理规则（C0-C3 分级 + DM-CR 变更记录 + 同一逻辑提交纪律）
- 归档工作要求至 `docs/design/开发管理总册_初始化与持续维护工作要求_20260822.md`
- 记录首个 Change Record：DM-CR-20260822-001

**Schema / Contract Changes**
- 无运行时代码/Schema 改动
- 新增 Documentation Governance Contract（设计/契约变化必须同 commit 更新 DEVLOG + DEVELOPMENT_MANAGEMENT）

**Verification**
- 文档路径检查（docs/project/DEVELOPMENT_MANAGEMENT.md 精确匹配）
- 与 V1.3.2 / DEVLOG / 当前 R4-A1.1 状态核对（§10 真实状态要求）
- Frozen Baseline 未修改；无 credential/wheel 入库

**Implementation Status**
- DONE

**Review Status**
- PENDING_REVIEW

**Next**
- R4-A2（含并入的 Golden Domain Router）+ CR-1 并行

---

## 2026-08-23 05:10 · R4-A1.1 补遗：Devlog Gate 自身修复

**Scope**
- Devlog gate V2 上线后自查：54ce7c1（sha 截断比较漏排除）与 9a12184（fix commit 未带 DEVLOG）两个历史违规

**Implementation**
- 测试与 CI 规则起点后移至 9a12184（V2.1），sha 比较改 startswith；规则内所有后续 commit（含本条）严格走"代码改动必带 DEVLOG"

**Verification**
- 302 tests 全绿（devlog gate 自身用例通过）

**Implementation Status**
- DONE

**Review Status**
- PENDING_RECHECK（随 R4-A1.1 一并复核）

**Next**
- R4-A2（Golden Router + 语义/PIT validators + BSE/BJ/Adj/Limit）

---

## 2026-08-23 04:30 · R4-A1.1：Truth Integrity Hotfix（复核 REOPENED → 四项 P0 修复）

**Scope**
- R4-A1 聚焦复核（REOPENED）§2-13/16/22：A/B/C 三项 + P1-01/02/03/04（D 项 Golden Router 按审计 §7 与 R4-A2 合并执行）

**Implementation**
- **A. Manifest Self-Verification（P0-01）**：`load()` 从解析后的 cases 重算 case_count/counts_by_type/review_summary 并要求与 manifest 精确相等——只改 manifest（伪造 REVIEWED 123 / counts 999）不再能绕过 review/quantity gate（两条专属篡改测试）
- **B. Hash 模型拆分（P0-02/03）**：`source_hash` → `case_semantic_hash`（含 case_type + source_artifact_hash + truth_version；改 case_type 也被拦截）+ `source_artifact_hash`（真实外部证据工件哈希；COMPILED 为空，REVIEWED 必填——review_gate 拒绝无 artifact 的手改 REVIEWED）
- **C. Event Coverage（P0-04）**：每条 case 带 `event_id/event_class`；`event_coverage_gate()` 按 distinct event 计数（重复日期/负样本不计）；**PRODUCTION run 创建即拒绝**（当前诚实状态：ST_CAP=2<50、DELIST=10<20——补齐真实事件属于 golden review 流程）
- **P1-01/02**：版本 append-only（`golden_cases_v1/v2.jsonl` + 各自 manifest 快照 + `truth_manifest.json` ACTIVE 指针）；loader 只认指针指定文件（lexicographic 猜测废除，诱饵文件测试）
- **P1-03/04**：DEVLOG gate 扩至 `data/golden/**`、`.gitattributes`、`.github/workflows/**`（V2 规则自 54ce7c1 后生效）；CI `fetch-depth: 0`
- 数据集定位修正：v2 = **Golden CANDIDATE Dataset**（§13：全 COMPILED、事件覆盖诚实不足——不是 Verified Truth Basis）

**Verification**
- pytest: **302 passed**（+5；§22 关键测试：manifest 两类篡改/stats 相等/entry 改+重封/case_type 改/seal 缺失/REVIEWED 无 artifact/负样本不算事件/ST·DELIST distinct 门/PRODUCTION run 拒绝/诱饵 loader/append-only/语义无矛盾）
- ruff/format/mypy clean；dataset_hash 绑定链全链路复验

**Implementation Status**
- DONE（R4-A1.1；Golden Router 留待 R4-A2 按审计 §7 合并）

**Review Status**
- PENDING_RECHECK（§14 四项中 1-3 完成，第 4 项 Router 归入 R4-A2）

**Next**
- R4-A2（语义/PIT validators + Golden Router + BSE/BJ/Adj/Limit）→ R4-A3 → R4-B1/B2 → R4-CI；CR-1 可并行

---

## 2026-08-23 02:30 · R4-A1：Golden Truth Dataset v1 + Per-Type Gate + Catalog Seal

**Scope**
- 第四轮审计 §1-5/12（R4-P0-01/02/03/04/12）+ §29.1-5

**Implementation**
- **Golden Dataset v1**（`data/golden/provider/amazingdata/`，入库）：123 条 = ST 50（2 个已验证 ST 加帽事件 × 日期状态采样 + 8 蓝筹 × 5 日期负样本）+ 退市 20（10 个已验证退市 × 2 远期状态日期）+ 涨跌停制度 30（板块×时期制度矩阵：主板 10%/ST 5%/创业板改革前后 10%→20%/科创板 20%/首 5 日无涨跌/北交所 30%/主板新股首日 44%）+ 除权除息 20（10 蓝筹 × 2 年）+ BJ 映射 3；每条全字段（source_hash/truth_version/reviewed_by/reviewed_at/review_status）
- **GoldenTruthStore**：加载即校验（每条 source_hash 重算 + manifest hash 复验 + 数量 gate + review gate）；verify_binding 供 resume/verdict 复验
- **R4-P0-04 per-type gate**：`required_case_counts` 替代 `min_valid_cases`（golden_st_transition≥50 等逐类型检查，总量永不能替代类型）
- **R4-P0-12 catalog seal**：close_run 计算 `case_catalog_hash`（cases/ 子目录）；verdict 重算 exact match——closed catalog 篡改（FAIL→PASS）阻断 verdict
- **R4-P0-02 golden 绑定**：PRODUCTION/TRIAL run 创建时绑定 truth_version + manifest_hash（数量不足拒绝开 PRODUCTION run）；resume 复验；PRODUCTION verdict 加 review gate（v1 全 COMPILED → P0-M-1B 前必须人工 review，§39 checklist 落地为代码）
- **R4-P0-03 语义冲突清理**：seed 中 ST removal/IS_ST 矛盾与 STAR 混合表达移除；v1 数据集断言无同类矛盾（有测试）
- B4 golden 探针改读 GoldenTruthStore（123 case 全量比对）；golden_truth.py 降级为 validator 单测 seed

**Honesty Notes**
- v1 全部标 `review_status=COMPILED`（机器编译）：高置信结构事实为主，具体除息日期等中置信条目依赖正式 run 前人工 review（review gate 强制）——不编造确定性，用版本化流程收敛

**Verification**
- pytest: **297 passed**（+11：dataset 完整性/篡改检测/review gate/run 绑定/catalog seal/语义冲突）
- ruff/format/mypy clean；dry-run：123 golden case 全链路（truth_version + manifest hash 绑定输出）

**Known Open Issues**
- R4-A2（adj price context/B3 去现场假设/limit PIT+Decimal/history 固定样本/B2 BSE/BJ mapping 验证）
- R4-A3（SDK 拆分/Early Stop/auth failure state）、R4-B1/B2、R4-CI

**Implementation Status**
- DONE（R4-A1）

**Review Status**
- PENDING_REVIEW

**Next**
- R4-A2：语义修复批

---

## 2026-08-23 00:40 · R3 收尾批：Approval 自证 + DEVLOG CI Gate + L1/Report/B7 收口

**Scope**
- 第三轮审查剩余项：R3-P0-17、§4 DEVLOG CI gate、P1-08/10/12

**Implementation**
- **R3-P0-17 capability approval 自证**：`approve_from_spike_run()`——不接受"我告诉你它过了"，函数自己查询 spike run（PRODUCTION+CLOSED+provenance 完整+evidence closure 干净+verdict 引擎判 PASS+golden case refs 存在且 VALIDATED_PASS），全部通过才构建证据包并持久化；含 registry→spike capability 映射表
- **DEVLOG CI gate**（§4）：ci.yml 新增 per-commit diff-tree 检查（代码 commit 必须同时改 docs/DEVLOG.md；规则自 `e6a2a01` 起生效，旧 commit 豁免）+ 对应测试 `test_devlog_gate.py`
- **L1 脚本小修**（P1-10）：run-scoped 不可变证据（`data/spike/trial-l1/<run-id>/`）；SH/SZ/BJ 轮转混合样本；event_stream_verdict 与 lifecycle_verdict 分离（unregister/stop 失败不再是整体 PASS）
- **Spike Report 更新**（P1-12）：新框架用法（单 run 全阶段/`--resume`/verdict eligibility 输出）、run-scoped 证据目录、golden 最低数量矩阵、正式账号当天流程（含 `approve_from_spike_run`）
- **B7 多日结构**（P1-08）：按 run 日历尾窗 5 日循环，逐日 rows/bytes/elapsed + first/cached pull 区分 + 真实 request/retry 计数（来自 provider envelopes）

**Schema / Contract Changes**
- 无新 migration

**Verification**
- pytest: **286 passed**（+7：approval 自证 5 + devlog gate 2）
- ruff/format/mypy clean；dry-run 冒烟通过

**Known Open Issues**
- R3-P1-06/07（provider 内部 calendar 走 envelope + ProviderExchange 统一审计单元）→ 与 CR-1 RawWriter 一并（审计 §41 已列为 RawWriter 输入契约）
- P1-04（Source Policy DB 不可变写路径）→ P0b 前完成（审计 §26 裁定）

**Implementation Status**
- DONE（R3 全部 P0 关闭；R3 状态：Formal-Spike Correctness = COMPLETE）

**Review Status**
- PENDING_REVIEW

**Next**
- CR-1：RawWriter + ProviderExchange/RawEnvelope 持久化（审计 §41；含 P1-06/07 一并解决）

---

## 2026-08-22 23:50 · R3-0C + R3-1A/1B：语义 Validators + Golden Truth + 治理精确化

**Scope**
- 第三轮审查 §10-17（语义 validators）+ §37 R3-0C/0E + §21-27（治理精确化）

**Implementation**
- **Validators v2 重写**：symbol mapping 复用 `normalize_provider_symbol` 单一规则（bare code 跨市场不再是错误，全符号唯一性才是）；daily bar units 独立证据源（documented vs observed，`_observe_units` 从 live 数据推导观测单位；checked_n=0 必 FAIL）；ST/停牌无 golden facts 时 OBSERVED（全 0 样本不再 PASS）；limit 制度校验（board 分类 + pre_close×rate + tick rounding：ST 5%/主板 10%/创业板科创板 20%/北交所 30%；字段全缺失必 FAIL）；adj 连续性需要价格上下文（raw×factor 连续性，无上下文时 OBSERVED）；SDK behavior 拒绝 placeholder permission codes
- **Golden Truth 结构**（R3-0E）：`GoldenCase`（golden_case_id/truth_source/source_ref/expected_fields/source_hash）+ 内置 7 个公开可查证案例（ST 加帽/退市/涨跌停制度/除权）；B4 重写为逐案例 provider 对比；**golden case types 进入 Core Gate**（golden_st_transition/golden_delisted/golden_limit_regime/golden_corporate_action 成为 required case types）
- **R3-P0-18**：`allow_manual_publish` 逃生舱删除——任何 publish 必须有 run（RECOVERY 语义保留）
- **R3-P1-01**：migration 010——`meta_artifact_validation` 改 append-only（artifact_validation_id PK）+ `meta_publish_snapshot.artifact_validation_id` 绑定（历史 publish 永远能回答"当时哪个 validation 批准了我"）
- **R3-P1-02**：universe 激活同 hash 幂等 / 异 hash BLOCK（不再 REPLACE）
- **R3-P1-03**：publish 时自检 feature set members hash（绕过 service 的越库修改也会被拦）
- **R3-P1-05**：capability approval validate-before-mutate（内存不再先于 DB 提交变更）

**Schema / Contract Changes**
- migration 010（append-only validation + publish 绑定）；008 表重命名保留历史
- publish_snapshot 签名：pipeline_run_id 必填、allow_manual_publish 移除
- capabilities：required_case_types 增加 golden 类型

**Verification**
- pytest: **279 passed**（+26：validators v2 21 项 + recovery-run 语义适配）
- ruff/format/mypy clean；dry-run 冒烟——**新 validators 当场抓到 Fake 数据的制度违规**（北交所股票给出主板式涨跌停 → limit FAIL），证明语义校验真实生效

**Known Open Issues**
- R3-P0-17（capability approval 从 SpikeRun 自证）→ 下一批
- R3-P1-06/07（provider envelope 审计单元统一）→ 与 CR-1 RawWriter 一并
- R3-P1-08（B7 全月 capacity）、P1-10（L1 小修）、P1-12（Spike Report 更新）→ 收尾批
- DEVLOG CI gate（§4）→ 收尾批

**Implementation Status**
- DONE（R3-0C / R3-1A / R3-1B 主体）

**Review Status**
- PENDING_REVIEW

**Next**
- 收尾批：DEVLOG CI gate + L1 小修 + Spike Report 更新；然后 CR-1（RawWriter + ProviderExchange）

---

## 2026-08-22 22:30 · R3-0A：Spike 生命周期 + 账号门 + Provenance + Verdict 引擎

**Scope**
- 按第三轮审查 §37 R3-0A + R3-0B 主体：修复 Formal Spike 无法产出 verdict / 可能错误 GO 的全部 P0 逻辑漏洞。

**Implementation**
- `RunStatus`（RUNNING/CLOSED/FAILED/ABORTED）+ `close_run`/`fail_run`/`abort_run`/`resume_run`——formal run 必达终态；resume 校验身份六元组（account/code/env/config/sdk/runtime）
- **Production Account Gate**（R3-P0-14）：`verify_production_account`——auth_ok/profile_parsed/entitlement_verified/非 TRIAL；`new_run(PRODUCTION)` 强制完整 provenance（40 字符 SHA + env/config hash）
- **Verdict 引擎重写**（R3-P0-04/05/16）：直接遍历 SpikeCase——fail dominates pass、DIFF_EXPLAINED 仅 equivalent_pass 计入、min_valid_cases 真实生效（golden 数量：20/50/30/20）、**Evidence Closure**（case 校验 + run 绑定 + 去重 + evidence 文件存在 + hash 复验 + catalog 篡改检测）
- **ProbeExecutor**（R3-P0-03）：Provider 五类 typed error → 结构化 case（Permission→NOT_TESTABLE_PERMISSION / RateLimit→NOT_TESTABLE_ACCOUNT / Auth→fail_run(FAILED_ACCOUNT) / Schema→VALIDATED_FAIL / 其他→MISSING→SPIKE_INCOMPLETE）；失败 envelope 也归档为 evidence
- CLI：PRODUCTION 默认单 run 全阶段（逐阶段需 `--resume`）；终态强制持久化；`--date` 进入 run.as_of_date，B2 不再硬编码日期（R3-P1-09）
- milestone eligibility 与 verdict 分离（R3 §54）：verdict.json 输出 p0a/p0b/backfill_eligible

**Schema / Contract Changes**
- SpikeRun 新增 `as_of_date` / `failure_reason`；status 变为 RunStatus 枚举语义
- capabilities：min_valid_cases 从占位 1 提为 golden 数量（20/50/30/20）
- 无 migration（本轮全部在 spike 框架内）

**Verification**
- pytest: **253 passed**（was 238；新增 lifecycle/verdict/gate 15 项）
- ruff/format/mypy: clean；`spike_runner --dry-run` 冒烟通过
- **R3-P0-16 闭包校验当场抓到真实 Windows bug**：`write_text` 默认换行转换导致 evidence 字节与 hash 不一致——已修（`newline=""`），这正是该审计项要防的篡改不可见问题

**Known Open Issues**
- R3-P0-06~13（validators 语义强化 + Golden Truth 绑定 Core Gate）→ R3-0C
- R3-P0-17（capability approval 自证）→ R3-1B；R3-P0-18（删 manual publish）→ R3-1A
- R3-P1-06（query_kline 内部 calendar 未走 envelope）/ P1-07（ProviderExchange）→ 与 CR-1 一并做

**Implementation Status**
- DONE（R3-0A + R3-0B verdict 引擎主体）

**Review Status**
- PENDING_REVIEW

**Next**
- R3-0C：语义 validators 重写（symbol 复用 normalize_provider_symbol / units 独立证据 / ST golden / limit 制度 / adj 连续性 / sdk 真实 permission codes）+ Golden 进 Core Gate

---


## 2026-08-22（晚）· 第二轮审计整改完成

**Commit**：`65c0d89` → `e6187e3` → `6359d20` → `3bb6752` → `2048110`

**完成事项**
- R2A：Spike 框架重写进 `src/ashare_state/spike/`（R2-P0-01~04 全关）——探针统一走 Production Adapter（`SpikeTarget` 单一路径）、八态 CaseResult + 八类语义 validator、SpikeRun 三环境物理隔离、Gate=Probe 契约
- R2B+R2C：`meta_artifact_validation` 系统不变量（R2-P0-05）、发布七项血缘校验 + RECOVERY 语义（R2-P0-06）、approval 单事务唯一入口（R2-P1-01）、治理错误独立分类（P1-02）、分类收敛 VERIFIED 签名（P1-03）、Doctor 两级 verdict（P1-04）、ProviderSymbolNormalizer + 严格日历（P1-05）、L1 脚本四态硬化（P1-06）、FileCommitCoordinator TOCTOU 修复（P1-07）、全量 UUID 路径（P1-08）、迁移序列连续性（P1-09）、STAGING service 规则 + 版本激活不可变（P1-10/11）
- 整改映射文档：`docs/audit2_response_20260822.md`（18 项逐项对照）

**关键决策**
- Spike 与生产共用同一条硬化 Provider 链路（第二轮审计 §37 核心要求）
- `查询失败` 从 Permission 降级为 SdkInternal（分类收敛：仅 VERIFIED 签名判权限）
- Doctor verdict 拆两级：PACKAGE_VERIFIED ≠ ACTUAL_LOAD_VERIFIED

**下一步**：R2-P1-12 Canonical Runtime（Real P0a Entry Gate）；周一交易时段 L1 Smoke

---

## 2026-08-22（下午）· 第一轮审计整改完成 + M0 收口

**Commit**：`3da4d36` → `ffb948f` → `a248163` → `212bacf` → `93ae532` → `cf81be3` → `fee655b` → `bfce563` → `0a5c704` → `99cca13`

**完成事项**
- 任务书执行：Provider Doctor（实测 RUNTIME_IDENTITY_VERIFIED）、AmazingData Adapter 8 文件、migration 005 Canonical DDL、Source Policy 状态机、Runbook 8 篇
- Git 首推 + CI 三轮修复：lint 违规 / mypy 平台分支 / **Windows msvcrt 崩溃锁释放延迟**（产品级修复：死锁探测窗口）→ 三矩阵全绿
- **M0 = PASS**（`212bacf`，出口标准 16 条逐条勾验，见 `m0_exit_report.md`）
- 第一轮审计整改（6 P0 + 18 P1 全关）：Patch A 不可变文件契约 / Patch B Provider 可靠性 / Patch C Canonical PIT + 治理收尾；128 → 179 tests；映射见 `audit_response_20260822.md`

**关键决策**
- M0 状态机：PASS_PENDING_CI → PASS（以 CI 首跑三矩阵为准）
- STAGING 只在 run/filesystem 层（ADR-009 方案 B）；Parquet = SoR，DuckDB = 读模型

**下一步**：第二轮审计整改（当晚完成）

---

## 2026-08-21 · Phase 0 双轨启动完成

**Commit**：`bb2779b` → `f820b77`

**完成事项**
- P0-M0 工程骨架从零建立：migrations 001-004（21 表）、DuckDB 进程级独占（ADR-008）、UUIDv5 确定性身份（ADR-002）、八步原子提交、Manifest Hash 免污染、Mock 端到端闭环、Failure Injection A-D、CI 骨架——84 tests
- P0-M-1 B1：C++ SDK 摸底（test_tool 64→32 位截断 bug 发现）→ Python SDK（AmazingData 1.1.9 + tgw 1.0.9.2）受控安装验证
- 仿真账号连通性测试：login/代码表 PASS，calendar/快照 DENIED（PermissionCode 3|4|32|33 实际只开代码表）
- 设计文档入库（冻结方案 / 裁决回复 / 任务书）；日报 `work_report_20260821.md`

**关键决策**
- 仿真账号 Spike 范围裁定：B2-B7 等正式账号（"核心事实未验证不得给 GO"）
- SDK stdout Token 防泄漏（fd 级捕获）成为 Provider 层硬要求

**下一步**：任务书收口项 + Provider 层开发

---

## 2026-08-21 之前 · 项目奠基

- 通读冻结基线 V1.3.2（5235 行）并完成评审（11 项缺口提交设计者裁决）
- 设计者裁决 GO WITH CHANGES 全量吸收，形成 Phase 0 启动计划
- workspace 确立：Windows + uv + Python 3.14 参考运行时
