# 开发日志（DEVLOG）

> **维护规则**（第三轮审查 §1-§4 固化）：
> - 本文件是项目**唯一**滚动开发日志；每次代码推送同步在顶部追加条目（倒序），不覆盖历史。
> - 专题报告仅限：M0 Exit / Provider Spike / P0a Exit / P0b Exit / Backfill Exit / 重大 Incident / 重大架构决策。
> - 每个条目区分 **Implementation Status**（DONE / IN_PROGRESS / BLOCKED）与 **Review Status**（PENDING_REVIEW / VERIFIED / REOPENED）——"代码写完" ≠ "审计关闭"。
> - CI gate：代码 commit（src/migrations/configs/scripts）必须同时修改本文件（test_code_commit_requires_devlog_change + CI diff-tree 检查）。

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
