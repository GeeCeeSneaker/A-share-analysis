# P0-M0 Exit Report — 工程骨架出口验收

> 日期：2026-08-21
> 依据：《A股市场态势数据基座（日频模块）V1.3.2 开发方案》第 31 节 P0-M0 出口标准 +
> 设计者裁决《Phase0 启动方案 设计评审与裁决回复》第 15 节修订版出口标准
> 验收方式：本地 Windows（Python 3.14.6 + uv）全量测试 + CI（Windows 必须 / Linux 推荐）

## 1. 设计者修订版出口标准逐条勾验

| # | 标准 | 状态 | 证据 |
|---|---|---|---|
| 1 | DuckDB 不依赖"跨进程写者 + read-only 读者可同时存在"的假设 | PASS | `storage/connection.py` 实现进程级排他 Owner（外部锁文件 Gate：msvcrt/fcntl）；`tests/integration/test_db_owner.py` 覆盖裁决要求的全 4 项测试：双写进程竞争第二个明确失败、写持有期间所有权拒绝（从不断言并发读可用）、Owner 被 kill 后锁立即可恢复、残留锁文件不阻塞启动 |
| 2 | Migration 文件有 checksum，已执行 migration 被修改时 BLOCK | PASS | `storage/migrations.py`：SHA-256 登记 + 篡改检测在任何新迁移执行**之前**完成；`test_migrations.py::test_modified_applied_migration_blocks` 与 `test_tamper_check_runs_before_any_new_migration` |
| 3 | Snapshot Manifest Hash 与机器绝对路径、随机 run_id 无关 | PASS | `ComponentIdentity` 数据类结构上**不含** file_uri/路径/run_id/时间戳字段（`test_cross_root_manifest.py::test_run_id_in_physical_layout_does_not_pollute` 直接断言字段集）；身份 Hash 仅由 7 个逻辑字段排序生成 |
| 4 | Windows/Linux 对同一逻辑 component 集合生成相同 Manifest Hash | PASS* | 本地 Windows：`test_cross_root_manifest.py::test_same_content_two_roots_same_hash`（两个独立根目录同 Hash）；Linux 侧由 CI ubuntu-latest runner 运行同一测试套件验证（*待 CI 首次运行确认） |
| 5 | file_uri 精确比较，case collision 自动 BLOCK | PASS | `storage/paths.py`：逻辑 URI（相对 data_root/正斜杠/无盘符/无 `..`）；`test_file_uri.py::test_exact_collapse_blocked` |
| 6 | meta_feature_artifact_set/component Schema 已存在 | PASS | `migrations/003_run_snapshot_publish.sql`；`test_migrations.py::EXPECTED_TABLES` 断言 21 张表全建 |
| 7 | feature_set_version 在首次 Feature Artifact 前有可解析 Registry | PASS | `migrations/004_feature_governance.sql`（meta_feature_set + member，definition_hash 由排序成员生成）；`test_mock_pipeline.py::test_feature_set_registry_resolvable`；`mock_e2e` 在创建 artifact set 前强制注册 |
| 8 | Security ID 缺 list_date 不允许正式 PUBLISHED | PASS | `identity/security_id.py::assert_publishable()` 抛 `IdentityPublishBlockedError`；`test_security_id.py::test_fallback_identity_blocked_from_publish` |
| 9 | 模拟"文件落盘后崩溃 / Snapshot 后崩溃 / Publish 事务失败"的恢复测试通过 | PASS | `tests/integration/test_failure_injection.py` 场景 A（orphan 不可见且可被 startup check 探测）/ B（latest 仍旧版）/ C（artifact 不可被 latest 读到）/ D（事务失败旧 PUBLISHED 保持、无残留 SUPERSEDED） |
| 10 | 真实 CI 不安装 AmazingData SDK，Mock 全测试通过 | PASS | `.github/workflows/ci.yml`：uv sync（无 SDK）+ 显式 `import AmazingData` 缺失断言步骤；本地等效验证（当前环境无 SDK，84 tests 全过） |

## 2. 原方案第 31 节 P0-M0 出口标准

| 标准 | 状态 | 证据 |
|---|---|---|
| 干净机器可安装并跑测试 | PASS | `uv sync` + `uv run pytest`（README 快速开始）；`uv.lock` 已提交 |
| 两次干净重建固定 Security Fixture 的 UUIDv5 完全一致 | PASS | `test_security_id.py::TestDeterminismAcrossRebuilds` + `test_mock_pipeline.py::test_two_clean_rebuilds_produce_identical_hashes`（连 Manifest Hash 都一致） |
| DuckDB migration 可从 0 初始化 | PASS | `test_migrations.py::test_all_tables_created`；CLI `ashare init-db` |
| Secret 不进 Git/日志 | PASS | `.gitignore`（.env）+ `logging_setup.py` 注册式脱敏 filter + `test_secret_masking.py`（password/token/username 等 6 类） |
| CI 不安装真实 Provider SDK、不含真实凭证 | PASS | ci.yml 无 SDK 步骤 + SDK absence 断言 + `.env.example` 占位模板 |
| 单 Writer 规则自动测试 | PASS | `test_db_owner.py`（含跨进程 subprocess 竞争与 kill 恢复） |

## 3. 交付物清单

```text
migrations/001_identity_calendar.sql        身份/日历/交易规则表
migrations/002_provider_governance.sql      Provider 元数据 + Source Policy(Schema) + 容差规则
migrations/003_run_snapshot_publish.sql     Run/Snapshot/Artifact/Publish 闭合骨架
migrations/004_feature_governance.sql       Feature Set Registry（裁决 P0-3）
src/ashare_state/
├─ domain/types.py                          全部状态枚举（含 NOT_RUN_NO_SECONDARY 纪律）
├─ identity/security_id.py                  UUIDv5 固定命名空间 b2e7b5e4-28f5-5384-8508-bcc20755d552
├─ providers/{base,registry,mock}/          四类 Protocol + 确定性 Fixture Provider
├─ storage/{connection,migrations,atomic_files,paths}.py
├─ pipeline/{publish,mock_e2e}.py           原子发布事务 + Published/Exact readers + Mock 闭环
├─ config.py / logging_setup.py / cli.py
tests/                                      84 tests（unit 38 + integration 46）
.github/workflows/ci.yml                    真实 CI（Windows 必须 + Linux）
```

## 4. 遗留事项（不阻塞 M0 出口，移交后续里程碑）

1. **CI 首次运行确认**：仓库尚未推送到 GitHub，ci.yml 的 Linux runner 验证项 #4 待首次 CI 运行后回填本报告。
2. **git 初始提交**：仓库已 `git init`，待用户确认后做首次提交（含 uv.lock）。
3. **Canonical selected 层 DDL**：按裁决第 5 节留待 P0a 前完成（fact_daily_bar/limit/status/adj 四域契约）。
4. ~~ADR-001..006 索引 + ADR-007/008 正文~~：**已交付**（`docs/adr/ADR-000_adr_index.md`、`ADR-007_p0m0_tushare_unavailable.md`、`ADR-008_duckdb_process_model.md`），随 Spike 报告框架（`docs/spike_report_p0m1.md`）、Provider Verification 模板（`docs/provider_verification/amazingdata.md`）与风险登记册（`docs/risk_register.md`）一并提供。
5. uv 托管 Python 3.12 安装在本机损坏（untrusted mount point），本地开发使用系统 Python 3.14（满足 requires-python >=3.12）；CI 使用 setup-uv 的 3.12。已用 `.python-version` 固定本地版本避免 uv 反复触碰损坏安装。
6. **Spike 真实运行**：框架已就绪（dry-run 全流程验证），待受控机器安装 AmazingData SDK 后执行（运行指引见 `docs/spike_report_p0m1.md` §6）；SDK 方法名为占位，首次真实调用时按实际 SDK surface 修正。

## 5. 结论

P0-M0 出口标准（含设计者修订版 10 条增量）**全部满足**，工程骨架达到冻结基线的结构闭合要求：
三层身份（data_snapshot_id / feature_artifact_set_id / publish_id）在 Schema 与
运行时（发布事务 + Published/Exact readers）两个层面均可用且被测试覆盖。

**M0: PASS_PENDING_CI**（任务书 §1.1 裁定：CI 首跑通过——Windows+3.14 必选矩阵——后改为 PASS；CI 矩阵已升级为 Windows+3.14 REQUIRED / Windows+3.12 / Linux+3.14）
