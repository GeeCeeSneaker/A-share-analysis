# Runbook — P0-M-1 Spike 运行

> 前提：完成 SDK 安装验证（install_amazingdata.md）+ provider doctor 绿灯。
> 当前正式账号 native SDK smoke 已完成，但只属于连通性证据；正式验证仍必须先跑 doctor，再执行单一 CLOSED PRODUCTION B1-B7 run。

## 1. 凭证配置

```powershell
Copy-Item .env.example .env
# 编辑 .env：TGW_USERNAME / TGW_PASSWORD / TGW_SERVER_VIP / TGW_SERVER_PORT
```

## 2. 执行顺序（正式账号：单一 Production run）

### 2.1 Runtime / account preflight

```powershell
# 离线：确认 wheel 版本与打包运行时；不需要凭证
uv run ashare provider-doctor --offline

# 在线：注入 .env 后确认实际加载、网络、认证、查询和脱敏账号画像
uv run ashare provider-doctor --output data/spike/results/provider_doctor.json
```

在线 doctor 必须得到实际加载路径与账号画像；`RUNTIME_PACKAGE_VERIFIED` 只表示 wheel 层验证，不能替代在线实际加载确认。若出现 `RUNTIME_PATH_AMBIGUOUS` 或 `RUNTIME_VERSION_MISMATCH`，先停止排查。

### 2.2 Formal B1-B7

Production 必须由一个 `RunKind.PRODUCTION` run 执行全部 B1-B7，不能把多个独立 run 拼成 verdict：

```powershell
# <latest-complete-trading-day> 必须是已完成交易日，不能是未来日期
uv run python scripts/spike/spike_runner.py --production --date <latest-complete-trading-day>

# 只有硬进程中断导致原 run 仍为 RUNNING 时才使用 --resume；普通 Python failure 会落为 FAILED，operator interrupt 会落为 ABORTED
# 省略 --date 时复用原 run 持久化的 as_of_date；若显式传入，必须与原值精确一致
# Production resume 采用 replay-all：重新执行完整 B1-B7；不接受 --phase bN
uv run python scripts/spike/spike_runner.py --production --resume --run-id <id>

# run CLOSED 后，单独计算正式 verdict
uv run python scripts/spike/spike_runner.py --verdict --run-id <id>
```

正常 Production 命令默认执行 `b1,b2,b3,b4,b5,b6,b7`；Production resume 也只采用 replay-all，不接受 caller 选择单一 phase。CLI 的 `--dry-run` / `--production` / `--trial` / `--verdict` 模式互斥，歧义组合会在登录、DB open、run mint 和 evidence write 之前拒绝。正式 runner 会在同一进程所有权下打开已迁移的持久 DuckDB，并让 `ProbeContext` 使用该连接写入 `meta_raw_evidence_anchor`。B2/B3/B4 的 blocking semantic FAIL 保持 `VALIDATED_FAIL`；只要执行完整，run 可以正确进入 `CLOSED`，正式 verdict 再给出 `NO_GO`/阻塞结果；auth/account/framework fatal 才进入 `FAILED`。

### 2.3 Trial / dry-run boundary

```powershell
# 无凭证框架自检
uv run python scripts/spike/spike_runner.py --dry-run

# 仿真账号证据（不能进入 Production verdict）
uv run python scripts/spike/spike_runner.py --trial --date <as-of>
```

Trial 与 dry-run 的目录、身份和证据必须与 Production 物理隔离。

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

| 能力 | Gate |
|---|---|
| `security_master_with_delisted` / `daily_bar_units` / `historical_st_suspend` / `limit_price_and_no_limit_days` / `adj_factor_corporate_action_continuity` / `history_start_2020` / `symbol_mapping_unambiguous` / `sdk_permission_cache_freshness` | 任一核心 FAIL → **P0a NO_GO** |
| `free_float_equivalence` / `sw_taxonomy` / `benchmark_index_availability` / `capacity_backfill` | Optional 逐项出结论；缺失时按 formal verdict 规则进入 GO_DEGRADED 或阻塞对应外围能力 |
| 历史状态 / 限价 / 复权 / 退市连续性 | Golden 或关键连续性缺口 → **fail closed** |

## 5. 产物与归档

Production run 的 run-scoped 产物位于：

- `data/spike/production/<run-id>/spike_run.json`
- `data/spike/production/<run-id>/cases/spike_case_catalog.jsonl/.csv`
- `data/spike/production/<run-id>/raw/`
- `data/spike/production/<run-id>/verdict.json`（执行 `--verdict` 后生成）

Preflight doctor 输出可写入 `data/spike/results/provider_doctor.json`；它不能代替 run-scoped B1-B7 evidence。原始响应必须经过现有 adapter/session 的 stdout 捕获和脱敏边界；凭证、Token、host/port 明文不得写入仓库、日志或提交。
