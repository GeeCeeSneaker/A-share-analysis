# P0-M-1 Spike Report — AmazingData Provider 验证（GO / NO-GO）

> 状态：**FRAMEWORK READY (R3) — PR8.1 CLI/Resume VERIFIED (CI) / FORMAL PRODUCTION RUN PENDING**
> 框架已通过第三轮审计整改（R3-0A/0B/0C/1A/1B）：Run 生命周期终态化、单 Run Verdict、账号门、完整 Provenance、语义 Validators v2、Golden Truth 进 Core Gate、Evidence Closure。
> 与 M0 Exit Report 同时提交设计者评审。

## 1. 执行摘要

| 项 | 值 |
|---|---|
| Spike 对象 | AmazingData（中国银河证券 格物金融服务平台）；Tushare 不可用（ADR-007） |
| 框架验证 | dry-run 全流程（FakeTarget）：八态 case / validators v2 / golden 逐案例对比 / 终态 run / verdict 引擎 + evidence closure 全部工作——**dry-run 中新 validators 当场抓到 fake 数据的北交所涨跌停制度违规，证明语义校验真实生效** |
| 仿真账号 | B1 连通性 DONE（2026-08-21）；权限码 3\|4\|32\|33 实际只开代码表 |
| 真实运行 | 官方 SDK 已在本地受控环境安装并通过脱敏直连冒烟；尚未启动 Production run |
| 当前结论 | **未评定 / Formal run pending**（SDK 冒烟通过，但仓库 runner、Production B1-B7、verdict 与矩阵证据尚未执行） |

## 2. 运行方式（R3 框架，与旧文档不同）

```powershell
# 框架自检（无凭证）
uv run python scripts/spike/spike_runner.py --dry-run

# 仿真账号 trial run（终态必然持久化：CLOSED/FAILED/ABORTED）
uv run python scripts/spike/spike_runner.py --trial --date <as-of>

# PRODUCTION：一个 run 跑全部阶段（R3-P0-02 单 Run Verdict 契约）
uv run python scripts/spike/spike_runner.py --production --date <as-of>

# Production replay-all recovery（身份六元组必须匹配；不接受 --phase bN）
uv run python scripts/spike/spike_runner.py --production --resume --run-id <id>

# verdict（仅 CLOSED 的 PRODUCTION run）
uv run python scripts/spike/spike_runner.py --verdict --run-id <id>
```

**证据目录（run-scoped，物理隔离）**：
```text
data/spike/{dry-run,trial,production}/<spike_run_id>/
    spike_run.json          # 含完整 provenance（40位SHA/uv.lock hash/config hash/账号画像）
    cases/                  # 逐案例目录（13字段 + equivalent_pass + evidence_hash）
    raw/                    # 无损不可变原始证据（含失败 exchange 的 ERROR envelope）
    verdict.json            # verdict + p0a/p0b/backfill eligibility
```

## 3. 三级结论与里程碑 Eligibility（分离输出）

| 结论 | 条件 |
|---|---|
| GO_CORE | 核心 8 能力全 PASS（validators 语义验证 + golden 数量达标） |
| GO_DEGRADED | 核心过 + 可选能力缺失（free-float/SW/capacity） |
| NO_GO | 覆盖完整且核心真失败（fail dominates pass） |
| SPIKE_INCOMPLETE | 覆盖缺失 / provenance 不完整 / evidence closure 失败 / golden 数量不足 |

verdict.json 同时输出（R3 §54）：
```json
{"p0a_eligible": true, "p0b_eligible": false, "historical_backfill_eligible": "PARTIAL"}
```

## 4. 核心能力矩阵（含 golden 最低数量）

| 能力 | min_valid_cases | golden 类型 |
|---|---|---|
| security_master_with_delisted | 20 | golden_delisted |
| daily_bar_units | 1 | —（独立证据源） |
| historical_st_suspend | 50 | golden_st_transition |
| limit_price_and_no_limit_days | 30 | golden_limit_regime |
| adj_factor_corporate_action_continuity | 20 | golden_corporate_action |
| history_start_2020 | 1 | — |
| symbol_mapping_unambiguous | 1 | —（单一 parser 规则） |
| sdk_permission_cache_freshness | 1 | —（真实 permission codes） |

内置 golden 种子（公开可查证事实）：`src/ashare_state/spike/golden_truth.py`（7 例）；正式 run 前由 operator 补齐至目标数量并核验 source_ref/source_hash。

## 4.1 当前历史边界合同（2026-09-04）

`history_start_2020` 只验证 `2020-01-01 -> latest complete trading day` 的必要覆盖；2020 年以前的缺失不会导致 `GO_CORE` 失败，也不触发常规回填。2020-01-01 之后的关键连续性缺口仍必须 fail closed。正式生产 verdict 仍为未评定，原因是正式账号画像和 B1-B7 生产证据尚未提供。

## 4.2 SDK 安装前正式账号验证尝试（2026-09-04，历史记录）

- 两个 Owner 提供的候选服务端口均通过独立 TCP 可达性探测；这不是认证或数据权限证据。
- 当前受控 Python 3.14.6 环境未安装官方 `AmazingData` / `tgw` wheel，因此未发送登录请求，`ACCOUNT_PROFILE`、正式 B1-B7、verdict 和 Data Sufficiency Matrix 均未生成。
- 凭据未写入仓库；`production_account.yaml` 继续为空。下一步是安装并记录官方 wheel 指纹，再重跑 doctor 和单一 Production run。

## 4.3 2026-09-04 本地 SDK 冒烟结果（非 Production run）

- Python 3.14.6 中导入官方 `AmazingData==1.1.9`、`tgw==1.0.9.2` 与 `tables` 成功；TGW 自报 runtime `V4.3.0.260626-rc2.0-YHZQ`，`uv pip check` 通过。
- 正式账号登录成功，profile 可解析且权限/功能权限字段存在；stdout/stderr 均在测试边界内捕获，未落盘账号、Token 或原始日志。
- 单日/小样本直连接口均完成：calendar 8,719；沪深代码 5,215；历史代码列表（2026-09-03）5,215；北交所映射 248；stock basic 1；history status 1；adj factor 8,719；dividend 54；right issue 0；equity structure 68；industry base 511；industry constituent、股票日线、指数日线均返回结构化结果；logout 正常。
- 这只证明 SDK 原生调用链在本地可用；它不产生 run-scoped raw evidence，不满足正式 B1-B7、Golden/Data Sufficiency Matrix、verdict 或 Provider approval。完整历史覆盖只在形式化 Production run 中按 2020+ 合同执行。
- 依赖 wheel 已留在本地被忽略的 `vendor/amazingdata/`；`configs/production_account.yaml` 继续为空。由于当前本地环境未装入仓库源码，形式化 runner 尚未执行。


## 4.4 P0-AD-01 脱敏身份 bootstrap 工具

`scripts/spike/production_account_bootstrap.py` 已作为正式账号身份检查的受控入口加入仓库。它只从环境/.env 读取凭证，输出 allowlisted scrubbed profile，支持 `--offline` runtime 检查且完全绕过凭证加载，不会写入 `configs/production_account.yaml`；online doctor 调用由 fd2/Python stderr containment 包裹。真实账号 identity 仍需 Owner/Reviewer 人工确认，B1-B7、verdict 和 Data Sufficiency Matrix 继续待执行，P0-AD-01.1 最终状态等待 CI。

- run `33881832744`（run `258`）三平台均通过，每腿 `1425 passed`；bootstrap 代码边界已获得 CI 证据，但正式 production identity、B1-B7、Data Sufficiency Matrix 和 verdict 仍未执行。

## 5. Early Stop（R3 §53）

B2/B3/B4 任一 blocking semantic FAIL → case 保持 VALIDATED_FAIL；若执行本身完成，run 正确进入 CLOSED，正式 verdict 输出 NO_GO。只有 auth/account/framework fatal execution failure 才进入 FAILED；NOT_TESTABLE / 框架不完整 → SPIKE_INCOMPLETE（**不误记为 NO_GO**）。

## 6. 正式账号到位当天的流程（R3 §52）

```text
Provider Doctor（RUNTIME_ACTUAL_LOAD_VERIFIED）
→ 验证 Production Account Profile（非 TRIAL、entitlement 完整）
→ --production --date <as-of>（单 run 全阶段 + 逐阶段 Core Gate）
→ Close Run（终态必然持久化）
→ --verdict --run-id（evidence closure 自动复验 hash）
→ 人工复核
→ approve_from_spike_run()（R3-P0-17：审批从 run 自证，不接受口头"它过了"）
```

## 7. L1 实时订阅（独立能力，交易时段实测）

```powershell
uv run python scripts/spike/l1_subscription_test.py --stage 1   # → 5 → 20
# stage 100 仅用于订阅上限行为；不得用试用账号推断平台容量
```

输出 run-scoped 不可变证据（`data/spike/trial-l1/<run-id>/`）+ 双 verdict（event_stream / lifecycle 分离）。

## 8. No-Go 预案

见 ADR-007：核心 NO_GO 且 Tushare 不可用 → P0a BLOCKED 上报设计者；AKShare 不自动升级生产 fallback。
