# Runbook — 从零安装与恢复手册

目标：换一台干净机器，仅靠本目录文档完成安装、初始化、验证与恢复。

| 文档 | 内容 |
|---|---|
| [install_core.md](install_core.md) | 核心 runtime（uv + Python 3.14）与项目依赖安装 |
| [install_amazingdata.md](install_amazingdata.md) | AmazingData/TGW SDK 受控安装与验证 |
| [init_db.md](init_db.md) | DuckDB 从零初始化与迁移 |
| [provider_doctor.md](provider_doctor.md) | Runtime identity 与连通性诊断 |
| [run_spike.md](run_spike.md) | P0-M-1 Spike 各阶段运行 |
| [run_backfill.md](run_backfill.md) | 历史回补（正式账号 + Stage A-D 放量纪律） |
| [recover_duckdb.md](recover_duckdb.md) | DuckDB 故障恢复 |
| [publish_recovery.md](publish_recovery.md) | 发布中断恢复（Failure Injection A-D 对照） |

## 全局纪律

1. 所有命令在仓库根目录、PowerShell 下执行
2. 凭证只进 `.env`（已 gitignore）；任何日志/文档不得出现真实值
3. 任何"未实测能力 = APPROVED"的操作都被禁止（任务书 §21）
4. 遇到与文档不符的行为：先记录（provider_verification / risk_register），再修正文档
