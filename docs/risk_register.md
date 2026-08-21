# Risk Register

> 详细 Owner、概率、状态、Review Date 按冻结基线 §40 维护；本文件聚焦 Phase 0 当前活跃风险。
> 更新纪律：新增风险只增不改历史；状态变化注明日期。

## 活跃风险

### R-001 Tushare 不可用 → 单源运行（新增 2026-08-21）

| 项 | 内容 |
|---|---|
| 影响 | P0b BLOCKED；free-float/申万行业/双源 Reconciliation 缺失；No-Go 预案 `FUSED_TS_SECURITY_CONTEXT_V1` 不可执行 |
| 概率 | 已发生（积分不足） |
| 监控 | `configs/providers.yaml` 状态；Spike B6/B7 结论 |
| 缓解 | ADR-007：Spike 四级等价评估；`NOT_RUN_NO_SECONDARY` 术语纪律；银河行业独立注册 GALAXY_xxx；不自动引入 AKShare |
| 触发条件 | AmazingData No-Go 且 Tushare 仍不可用 → P0a BLOCKED 上报设计者 |
| Review Date | Spike Report 提交时 |

### R-002 AmazingData 核心数据假设未实测即承担 Primary 候选（继承冻结基线，状态更新 2026-08-21）

| 项 | 内容 |
|---|---|
| 影响 | 历史状态/退市/涨跌停/复权/单位假设错误会传导到 P0a 全部 Canonical |
| 概率 | 中（文档能力已确认，实测未做） |
| 监控 | P0-M-1 Spike 案例目录（B2-B5）；`meta_provider_capability.verified_at` |
| 缓解 | Spike Go/No-Go 门禁在 P0a 之前；异常样本 Golden（50 ST/20 退市/30 涨跌停/20 除权） |
| Review Date | Spike Report 提交时 |

### R-003 uv 托管 Python 3.12 安装损坏（新增 2026-08-21，环境级）

| 项 | 内容 |
|---|---|
| 影响 | 本地开发环境 |
| 概率 | 已发生（untrusted mount point, os error 448） |
| 监控 | `.python-version` 固定 3.14 避开损坏安装 |
| 缓解 | 本地用系统 Python 3.14（满足 >=3.12）；CI 用 setup-uv 3.12 验证另一版本；可选修复：`uv python install 3.12 --reinstall` |
| Review Date | 首次 CI 全绿后关闭 |

### R-004 单人维护 bus factor（继承冻结基线 §40）

| 项 | 内容 |
|---|---|
| 缓解 | runbook 演练（未参与开发者按文档执行一次回补/恢复）；自动化测试 84 项；ADR/Provider Verification 文档化 |
| Review Date | P0a 完成时 |

## 已关闭风险

（无）
