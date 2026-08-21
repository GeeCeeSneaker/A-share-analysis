# Runbook — P0-M-1 Spike 运行

> 前提：完成 SDK 安装验证（install_amazingdata.md）+ provider doctor 绿灯。
> 正式账号到位当天只做：配置凭证 → 运行脚本 → 分析结果（任务书 §11）。

## 1. 凭证配置

```powershell
Copy-Item .env.example .env
# 编辑 .env：TGW_USERNAME / TGW_PASSWORD / TGW_SERVER_VIP / TGG_SERVER_PORT
```

## 2. 顺序（任务书 §12：从核心到外围，依赖排序）

```powershell
uv run ashare provider-doctor --output data/spike/results/provider_doctor.json

# B2 Identity / Security Master（Gate：历史 SM 不满足 = P0a NO_GO）
uv run python scripts/spike/spike_runner.py --phase b2

# B3 Core Market Facts（Gate：任一核心事实不满足 = P0a NO_GO）
uv run python scripts/spike/spike_runner.py --phase b3 --date <近期交易日>

# B4 Corporate Action / Adjustment
uv run python scripts/spike/spike_runner.py --phase b4 --date <近期交易日>

# B5 Data Semantics / Unit / Cache / Freshness（输出 Endpoint-Level Unit Map）
uv run python scripts/spike/spike_runner.py --phase b5 --month 2026-07

# B6 Replacement Assessment（free-float 四级结论 + 行业 + Benchmark）
uv run python scripts/spike/spike_runner.py --phase b6 --date <近期交易日>
uv run python scripts/spike/spike_runner.py --phase b7

# 汇总草稿（人工复核后填 docs/spike_report_p0m1.md）
uv run python scripts/spike/spike_runner.py --phase verdict
```

## 3. L1 实时订阅（任务书 §1.2，必须交易时段）

```powershell
# 周一至周五 09:15-11:30 / 13:00-15:05，逐级放量
uv run python scripts/spike/l1_subscription_test.py --stage 1
uv run python scripts/spike/l1_subscription_test.py --stage 5
uv run python scripts/spike/l1_subscription_test.py --stage 20
uv run python scripts/spike/l1_subscription_test.py --stage 100
```

判定独立记录：`REALTIME_L1_SUBSCRIPTION` ≠ `HISTORICAL_SNAPSHOT_QUERY`
（后者 2026-08-21 已 DENIED，不影响前者结论）。

## 4. Gate 矩阵（任务书 §13）

| 核心能力 | Gate |
|---|---|
| Security Master / Daily Bar / Historical Status / Limit Price / Adj Factor+CA / Trade Calendar | 任一 FAIL → **P0a NO_GO** |
| free_share / SW taxonomy / 真实双源 Reconciliation | 缺失 → GO_DEGRADED（P0a 仍可进，P0b/M2 部分阻塞） |
| Historical Status = DEGRADED/FAIL | **P0a BLOCKED** |

## 5. 产物与归档

- `data/spike/results/spike_case_catalog.jsonl/.csv`：逐案证据（13 字段）
- `data/spike/raw/`：原始响应（凭证已脱敏）
- `data/spike/results/verdict_draft.json`：三级结论草稿（需人工复核）
- 差异必须归因 8 类 reason code 之一，无法解释 = FAIL
- 结论填入 `docs/spike_report_p0m1.md` + `docs/provider_verification/amazingdata.md`
