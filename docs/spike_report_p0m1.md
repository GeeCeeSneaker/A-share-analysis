# P0-M-1 Spike Report — AmazingData Provider 验证（GO / NO-GO）

> 状态：**FRAMEWORK READY (R3) — FORMAL ACCOUNT DETAILS RECEIVED / OFFICIAL SDK BLOCKED**
> 框架已通过第三轮审计整改（R3-0A/0B/0C/1A/1B）：Run 生命周期终态化、单 Run Verdict、账号门、完整 Provenance、语义 Validators v2、Golden Truth 进 Core Gate、Evidence Closure。
> 与 M0 Exit Report 同时提交设计者评审。

## 1. 执行摘要

| 项 | 值 |
|---|---|
| Spike 对象 | AmazingData（中国银河证券 格物金融服务平台）；Tushare 不可用（ADR-007） |
| 框架验证 | dry-run 全流程（FakeTarget）：八态 case / validators v2 / golden 逐案例对比 / 终态 run / verdict 引擎 + evidence closure 全部工作——**dry-run 中新 validators 当场抓到 fake 数据的北交所涨跌停制度违规，证明语义校验真实生效** |
| 仿真账号 | B1 连通性 DONE（2026-08-21）；权限码 3\|4\|32\|33 实际只开代码表 |
| 真实运行 | 已收到连接信息；官方 SDK 未安装，尚未启动 Production run |
| 当前结论 | **未评定 / 当前阻塞**（网络可达但 SDK 缺失，登录画像与 B1-B7 未执行） |

## 2. 运行方式（R3 框架，与旧文档不同）

```powershell
# 框架自检（无凭证）
uv run python scripts/spike/spike_runner.py --dry-run

# 仿真账号 trial run（终态必然持久化：CLOSED/FAILED/ABORTED）
uv run python scripts/spike/spike_runner.py --trial --date <as-of>

# PRODUCTION：一个 run 跑全部阶段（R3-P0-02 单 Run Verdict 契约）
uv run python scripts/spike/spike_runner.py --production --date <as-of>

# 中断续跑（身份六元组必须匹配）
uv run python scripts/spike/spike_runner.py --production --resume --run-id <id> --phase b5

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

## 4.2 当前正式账号验证尝试（2026-09-04）

- 两个 Owner 提供的候选服务端口均通过独立 TCP 可达性探测；这不是认证或数据权限证据。
- 当前受控 Python 3.14.6 环境未安装官方 `AmazingData` / `tgw` wheel，因此未发送登录请求，`ACCOUNT_PROFILE`、正式 B1-B7、verdict 和 Data Sufficiency Matrix 均未生成。
- 凭据未写入仓库；`production_account.yaml` 继续为空。下一步是安装并记录官方 wheel 指纹，再重跑 doctor 和单一 Production run。

## 5. Early Stop（R3 §53）

B2/B3/B4 任一 blocking FAIL → run 终态 FAILED → verdict NO_GO；NOT_TESTABLE / 框架不完整 → SPIKE_INCOMPLETE（**不误记为 NO_GO**）。

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
