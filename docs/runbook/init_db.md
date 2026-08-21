# Runbook — DuckDB 初始化与迁移

## 1. 从零初始化

```powershell
uv run ashare init-db
# 或指定路径
uv run ashare init-db --db-path data/db/atlas.duckdb
```

输出 `applied N migration(s)` 即成功；再次运行输出 `database already up to date`（幂等）。

## 2. 迁移内容（版本递增，永不修改已发布文件）

| 版本 | 内容 |
|---|---|
| 001 | 身份/日历/交易规则（dim_security 等 5 表） |
| 002 | Provider 治理（meta_data_source 等 6 表） |
| 003 | Run/Snapshot/Artifact/Publish 闭合（7 表） |
| 004 | Feature Set Registry（2 表） |
| 005 | Canonical 5 事实域（fact_daily_bar / security_status / limit_price / adj_factor / corporate_action） |

## 3. 防篡改纪律

- 每个 migration 的 SHA-256 记录在 `meta_schema_version`
- **已应用的 migration 文件内容被修改 → 启动直接 BLOCK**
  （`MigrationTamperedError`；有自动化测试）
- 新变更 = 新增 `006_xxx.sql`，永远不改旧文件

## 4. 单 Writer 纪律（ADR-008）

- atlas.duckdb 任一时刻只被**一个进程**持有（读或写）
- 第二进程连接会得到 `DatabaseOwnedError`（含当前 owner pid/mode）
- owner 崩溃后 OS 锁自动释放，无需人工清理
- 残留的 `.owner.lock` **文件**不影响启动（删除它反而有竞态风险，勿删）

## 5. 故障

| 症状 | 处置 |
|---|---|
| `MigrationTamperedError` | `git diff migrations/` 找出被改文件；还原或新增迁移 |
| 事务中途断电 | 单个 migration 事务内执行，重跑 init-db 即恢复 |
| `database is owned by another process` | 找到持有进程（锁文件里有 pid）或等待其退出 |
