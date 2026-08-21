# P0-M-1 Spike Report — AmazingData Provider 验证（GO / NO-GO）

> 状态：**FRAMEWORK READY — AWAITING LIVE RUN**
> 本报告框架已就绪；三级结论待受控机器上真实账号运行 `scripts/spike/spike_runner.py` 后填写。
> 与 M0 Exit Report 同时提交设计者评审（设计裁决第 18 节要求的下一次 Review 节点）。

## 1. 执行摘要

| 项 | 值 |
|---|---|
| Spike 对象 | AmazingData（中国银河证券 星耀数智）唯一可用 Provider；Tushare 积分不足（ADR-007） |
| 框架验证 | dry-run 全流程通过（无凭证、CI 安全）：B1-B7 案例落盘 + 证据归档 + verdict 草稿聚合 |
| 真实运行 | 待执行（需受控机器安装 SDK + .env 凭证） |
| 当前结论 | **未评定**（核心事实未验证前不得给 GO） |

## 2. 三级结论定义（设计裁决第 4 节）

| 结论 | 条件 | 对里程碑的影响 |
|---|---|---|
| **GO_CORE** | 核心事实 8 项全部通过（见 §4） | 允许进入 P0a |
| **GO_DEGRADED** | 核心事实通过，但 free-float / SW taxonomy / 真实双源 reconciliation 缺失 | P0a GO；P0b 与部分 P0-M2 BLOCKED |
| **NO_GO** | 任一核心事实无法满足 Frozen 要求 | P0a BLOCKED，上报设计者（不自动切 AKShare） |

## 3. 能力评估矩阵（真实运行后填写）

### 3.1 核心事实（全部必须 PASS）

| # | 能力 | 结论 | 证据（case catalog 引用） |
|---|---|---|---|
| 1 | Security Master / 历史代码含退市 | 待填 | |
| 2 | Daily OHLCV/amount 单位明确 | 待填 | |
| 3 | ST/停牌历史样本正确（50 加/脱帽） | 待填 | |
| 4 | up/down limit 与无涨跌幅限制日正确 | 待填 | |
| 5 | Adj Factor / Corporate Action 连续性 | 待填 | |
| 6 | 历史起点满足 2018 分析 + Warmup | 待填 | |
| 7 | Symbol Mapping 无关键歧义 | 待填 | |
| 8 | SDK/权限/缓存/freshness 行为已记录 | 待填 | |

### 3.2 允许缺失项（BLOCK P0b/M2，不阻塞 P0a）

| # | 能力 | 四级结论 | 证据 |
|---|---|---|---|
| 1 | `free_share / turnover_rate_f` 语义等价 | 待填（EXACT/DERIVABLE/ALTERNATIVE/MISSING） | |
| 2 | SW taxonomy | 待填 | |
| 3 | 真实双源 Reconciliation | MISSING（结构性：无第二源，ADR-007） | |

### 3.3 里程碑状态汇总

| 里程碑 | 状态 | 依据 |
|---|---|---|
| P0a（AmazingData 最小纵贯线） | 待定 | 核心事实 Spike 结论 |
| P0b（Tushare Essential + Source Policy + Reconciliation） | 预计 BLOCKED | ADR-007：Tushare 积分不足 |
| P0-M2（Historical Backfill） | 部分待定 | SW/自由流通相关部分受 3.2 影响 |

## 4. 证据与可审计性

- 案例目录：`data/spike/results/spike_case_catalog.jsonl`（+ CSV 导出），13 字段完整（case_id → checked_at）；
- 原始响应：`data/spike/raw/`（凭证已脱敏：password/token/secret 键值一律 MASKED）；
- 每个差异必须归因到 8 类 reason code 之一（CORPORATE_ACTION / PRICE_TICK_ROUNDING / AFTER_HOURS_INCLUDED / SESSION_BOUNDARY / SYMBOL_MAPPING / SOURCE_REVISION / PROVIDER_TIMING / DOCUMENTED_UNIT_DIFFERENCE），**无法解释即 FAIL**；
- verdict 草稿由 `spike_runner.py --phase verdict` 生成（`verdict_draft.json`），最终结论需人工复核证据后填写本报告。

## 5. No-Go 预案（ADR-007 §决策 5）

若核心事实 NO_GO 且 Tushare 仍不可用：**P0a BLOCKED**。可选动作：
1. 补足 Tushare 积分，启用 `FUSED_TS_SECURITY_CONTEXT_V1`；
2. 新候选 Provider 单独 Spike + Source Policy 审批；
3. 形成新 ADR 后再批准。

**AKShare 不因"免费能拿到"自动升级为生产 fallback。**

## 6. 运行指引（受控机器）

```powershell
# 0. 安装 SDK（券商本地 wheel）并记录到 docs/provider_verification/amazingdata.md §1
uv pip install <path-to-amazingdata-wheel>

# 1. 配置凭证
Copy-Item .env.example .env   # 填入真实值

# 2. 逐阶段运行（串行限流 + 指数退避已内置）
uv run python scripts/spike/spike_runner.py --phase b1
uv run python scripts/spike/spike_runner.py --phase b2
uv run python scripts/spike/spike_runner.py --phase b3 --date <近期交易日>
uv run python scripts/spike/spike_runner.py --phase b4 --date <近期交易日>
uv run python scripts/spike/spike_runner.py --phase b5 --month 2026-07
uv run python scripts/spike/spike_runner.py --phase b6 --date <近期交易日>
uv run python scripts/spike/spike_runner.py --phase b7

# 3. 汇总草稿结论（人工复核后填写本报告 §3）
uv run python scripts/spike/spike_runner.py --phase verdict
```

> 注意：SDK 方法名（`query_kline` / `get_history_stock_status` 等）为占位，B1/B3 首次真实调用时按实际 SDK surface 修正 `scripts/spike/samples_*.py` 中的调用点；本框架的目录/证据/结论结构不变。
