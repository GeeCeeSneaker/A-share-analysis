# Phase 0 开发测试工作报告

> 报告日期：2026-08-21
> 报告范围：P0-M0 工程骨架 + P0-M-1 Provider Spike（B1 阶段）
> 依据文档：`docs/design/A股市场态势数据基座_日频模块_V1.3.2_开发方案.md`（冻结基线）、`docs/design/Phase0_启动方案_设计评审与裁决回复.md`（设计者裁决 GO WITH CHANGES）
> Git：首次提交 `bb2779b`（62 文件，13033 行）

---

## 一、工作概述

按设计者裁决的双轨并行策略推进 Phase 0：

- **轨 A（P0-M0 工程骨架）**：从空仓库建立可安装、可测试、可从零迁移初始化的单机数据系统骨架，全量吸收设计者 P0/P1 级裁决（DuckDB 进程独占、Manifest 身份规则、Security ID 补充规则、真实 CI 等）
- **轨 B（P0-M-1 Spike）**：完成 AmazingData/TGW 数据源 SDK 摸底、Python SDK 安装验证与仿真账号连通性测试（B1 阶段）；B2-B7 因仿真账号权限受限顺延至正式账号

## 二、轨 A：P0-M0 工程骨架完成情况

### 2.1 设计者裁决落地情况（全部落地）

| 裁决 | 实现位置 | 验证方式 |
|---|---|---|
| P0-1 DuckDB 进程级独占所有权 | `storage/connection.py`（锁文件排他 Gate + Owner 诊断） | 4 项裁决测试：双写竞争第二者明确失败 / kill 后锁立即恢复 / 残留锁文件不阻塞 / 同进程混模式显式拒绝 |
| P0-2 表集结构闭合 | `migrations/001-004`（21 张表） | `EXPECTED_TABLES` 断言测试 |
| P0-3 feature_set_version 注册载体 | `004_feature_governance.sql`（meta_feature_set + member，definition_hash 排序生成） | Mock 闭环中 artifact 创建前强制注册 |
| P0-4 file_uri 精确比较 | `storage/paths.py`（逻辑 URI：无盘符/正斜杠/无 `..`） | 大小写碰撞 BLOCK 测试 |
| P0-5 Manifest Hash 免污染 | `ComponentIdentity`（结构性排除路径/run_id/时间戳） | 跨根目录同 Hash + 插入顺序无关测试 |
| 裁决-7 Windows 八步原子提交 | `storage/atomic_files.py` | 顺序/SHA-256 校验/同卷 replace 测试 |
| 裁决-8 Migration checksum | `storage/migrations.py` | 篡改已应用 SQL → BLOCK；失败完整 ROLLBACK 测试 |
| Security ID 四补充 | `identity/security_id.py` | 固定命名空间 `b2e7b5e4-…`、标准化 symbol、缺 list_date 禁止 PUBLISHED、双重建一致测试 |

### 2.2 核心交付物

**迁移层**（4 个 SQL，21 张表）：
- `001_identity_calendar`：dim_security / bridge_security_provider_symbol / dim_trade_calendar / dim_trading_rule
- `002_provider_governance`：meta_data_source / capability / field_map / source_policy(Schema) / tolerance_rule / ingest_run
- `003_run_snapshot_publish`：dim_universe / meta_pipeline_run / meta_data_snapshot(+component) / **meta_feature_artifact_set(+component)** / meta_publish_snapshot(+universe)
- `004_feature_governance`：meta_feature_set(+member)

**运行时层**（`src/ashare_state/`）：
- 确定性身份（UUIDv5 + 发布冻结语义）
- 存储基座（DB Owner / 迁移器 / 原子提交 / 逻辑 URI）
- Provider 层（四类 Protocol + 注册表 + 确定性 Mock Fixture）
- 发布事务服务（原子 SUPERSEDED→PUBLISHED 切换 + Published/Exact 双读取 + 孤儿文件探测）
- Mock 端到端闭环（Mock → Canonical Parquet → Snapshot → Feature Artifact → Publish）
- CLI（`init-db` / `migrate` / `security-id-check` / `self-test`，全部幂等）

**CI 与质量门禁**：
- `.github/workflows/ci.yml`：真实 runner（Windows 必须 + Linux 推荐），不装 SDK、零凭证
- 本地门禁：ruff（lint+format）/ mypy / pytest 全绿

### 2.3 测试与质量指标

| 指标 | 数值 |
|---|---|
| 测试总数 | **84 个全部通过**（unit 38 + integration 46） |
| mypy | 21 个源文件，0 错误 |
| ruff lint + format | 0 违规 |
| Failure Injection A-D | 全部通过（A 孤儿文件可探测可清理 / B latest 仍旧版 / C 未发布 artifact 不可见 / D 事务失败旧 PUBLISHED 保持且无残留 SUPERSEDED） |
| 双重建确定性 | Security ID 一致 + 连 Manifest Hash 都一致 |

### 2.4 M0 出口标准结论

修订版 10 条增量出口标准 + 原方案 6 条标准**逐条勾验通过**（详见 `docs/m0_exit_report.md`）：

> **M0: PASS**（唯一待回填项：CI 首次运行——仓库尚未推送 GitHub）

## 三、轨 B：P0-M-1 Spike 完成情况（B1 阶段）

### 3.1 SDK 摸底（C++ → Python 路径确认）

| 项 | 结果 |
|---|---|
| C++ SDK（TGW V1.0.8） | 运行库已安装（`C:\Users\Public\Documents\mdga_file\lib`），DLL 加载链验证完整；test_tool 存在 64→32 位配置解析 bug（已绕过，不影响 SDK 本身） |
| 手册能力面 | C++ 手册 177 页 + Python 手册全文提取归档（`data/spike/manual_extract/`） |
| Python SDK | 官方存在，从银河获取后完成受控安装：`AmazingData==1.1.9`（cp314）+ `tgw==1.0.9.2`，SHA-256 已记录，**未写入 uv.lock**（符合设计裁决 9） |

### 3.2 API 能力面确认（import 实测 + 手册交叉验证）

与设计文档需求逐项对上：

- `get_history_stock_status`：**字段与 `fact_security_status_daily` 一一对应**（HIGH_LIMITED/LOW_LIMITED/IS_ST_SEC/IS_SUSP_SEC/IS_WD_SEC/IS_XR_SEC...）
- `get_hist_code_list`（20130101 起，退市包含性待实测）、`get_stock_basic`（IS_LISTED 退市标志）
- `get_adj_factor` + `get_backward_factor`（复权因子）
- **行业四件套**（`get_industry_base_info/constituent/daily/weight`，taxonomy 归属待实测——申万 or 银河自编，按 ADR-007 纪律不预设结论）
- `get_bj_code_mapping`（北交所新旧代码对照——Symbol Mapping 关键证据）
- `get_equity_structure`（股本结构——B6 free-float 四级等价评估入口）
- `get_index_constituent/weight`（指数成分——Benchmark 入口）
- `DownloadInfoData` 51 个批量下载方法（未来 backfill 用）
- 本地缓存机制（`local_path + is_local`）

### 3.3 连通性测试（仿真账号，B1 完成）

| 探针 | 结果 | 说明 |
|---|---|---|
| 登录认证 | ✅ PASS | `120.86.124.106:8600`，Token 签发，账号参数返回（订阅 100 / 周流量 10GB / 权限码 `3|4|32|33`） |
| 代码表 | ✅ PASS | 5549 只 A 股（后缀式 `600000.SH`） |
| 交易日历 / 历史代码表 / 复权因子 | ⛔ DENIED | 服务端拒绝（权限码不含） |
| Level-1 快照 | ⛔ DENIED | 重试 2-4 分钟后"查询失败"（权限码不含） |

**结论**：网络/认证/SDK 数据面链路全部打通，B1 连通性验证使命完成；仿真账号实际只开放代码表。流量消耗约 0.08GB / 10GB。

**顺带产出的生产 Adapter 防御清单**（4 条，已入档 provider_verification §2.2）：
1. SDK login 向 stdout 打印含 Token 的 logon json——Adapter 不得转发 SDK stdout
2. 无权限请求 → SDK 内部 TypeError（无类型化错误）——Adapter 必须全调用包装
3. `query_snapshot` 失败前重试 2-4 分钟——需显式超时
4. `get_code_info` 签名与手册不符——正式账号后核对

### 3.4 Spike 框架（已就绪，待正式账号）

`scripts/spike/`：B1-B7 探针模块 + 编排器（串行限流/指数退避/凭证脱敏）+ 案例目录（13 字段 + 8 类差异归因）+ 三级结论聚合（GO_CORE / GO_DEGRADED / NO_GO）。dry-run 全流程已验证（无凭证、CI 安全）。

## 四、关键发现与风险状态

| 风险 | 状态 |
|---|---|
| Tushare 不可用单源运行（ADR-007） | 未变：P0b 预计 BLOCKED；Spike B6/B7 待正式账号实测后按四级结论评估 |
| AmazingData 核心假设未实测（R-002） | **部分缓解**：API 能力面确认与设计需求对齐（行业/状态/复权/北交所映射全有），但数据本身未验证 |
| 仿真账号权限不足 | **新增**：B2-B7 与 GO/NO-GO 全部顺延至正式账号 |
| uv 托管 Python 3.12 损坏 | 已绕过（系统 Python 3.14 + `.python-version` 固定；CI 用 3.12 验证） |

**积极发现**：行业接口存在、按日证券状态字段完整、北交所新旧代码映射存在——多项原判"MISSING 风险"的能力面上看是存在的（数据质量仍待正式账号实测）。

## 五、下一步工作计划

### 5.1 等待外部条件（不阻塞开发）

1. **正式 TGW 账号**（用户申请中）→ 触发 B2-B7 完整 Spike 与 GO/NO-GO 评定
2. **GitHub 仓库推送** → 触发 CI 首跑（Windows + Linux），回填 M0 出口报告遗留项

### 5.2 可立即开展（无账号依赖，按优先级）

| 优先级 | 工作项 | 说明 |
|---|---|---|
| P1 | **AmazingData 生产 Adapter 骨架** | lazy import + 全调用包装（None/TypeError 双防御）+ stdout Token 拦截 + 显式超时——B1 发现的 4 条防御直接落码；Mock 测试驱动，正式账号到位即插即用 |
| P1 | **Canonical selected 层 DDL（P0a 前置）** | 按裁决第 5 节：fact_daily_bar/limit/status/adj 四个业务事实域建表 + Provider-normalized DTO 契约 + 字段映射（单位换算留待 B5 实测后填） |
| P2 | **Ingest Run 记录与 Source Policy 治理骨架** | meta_ingest_run 写入路径 + Source Policy 状态机（CANDIDATE→APPROVED）+ `NOT_RUN_NO_SECONDARY` 单源状态落地 |
| P2 | **runbook 初稿** | 单人 bus factor 缓解：从零安装→迁移→回补→恢复的演练文档 |
| P3 | **Spike B2-B7 探针脚本实化** | 按已确认的 API 面把占位方法名换成真实调用（`get_history_stock_status` 等），正式账号到位当天即可开跑 |

### 5.3 里程碑视图

```text
当前: M0 PASS + B1 DONE ──┬─→ [无依赖线] P1/P2 项推进
                          └─→ [等正式账号] B2-B7 → Spike Report → GO/NO-GO
                                          ↓
                                    同步 Gate: M0 PASS + Spike >= GO_DEGRADED
                                          ↓
                                    P0a 最小纵贯线（Canonical + Trend/PV 骨架）
```

### 5.4 下次设计者评审节点

按裁决第 18 节：**M0 Exit Report + Spike Report 双报告同时提交**——M0 侧已就绪，Spike Report 待正式账号跑完后填写结论部分。

---

## 附：交付物索引

| 类别 | 路径 |
|---|---|
| 冻结设计文档 | `docs/design/`（V1.3.2 方案 + 设计者裁决） |
| M0 出口报告 | `docs/m0_exit_report.md` |
| ADR | `docs/adr/`（索引 + ADR-007 + ADR-008） |
| Provider 验证 | `docs/provider_verification/amazingdata.md` |
| Spike 报告框架 | `docs/spike_report_p0m1.md` |
| 风险登记册 | `docs/risk_register.md` |
| 连通性证据 | `data/spike/results/connectivity.json`（gitignored，本地保存） |
| 本报告 | `docs/work_report_20260821.md` |
