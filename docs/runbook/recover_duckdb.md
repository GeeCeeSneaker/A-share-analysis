# Runbook — DuckDB 故障恢复

## 1. 单 Writer 锁问题

| 症状 | 原因 | 处置 |
|---|---|---|
| `DatabaseOwnedError` | 另一进程持有（锁文件含 owner pid/mode） | 等待其退出；或按 pid 结束该进程 |
| owner 崩溃后仍连不上 | 极小概率：OS 锁延迟释放 | 等 1-2 秒重试；OS 文件锁随进程死亡自动释放（有自动化测试） |
| 残留 `.owner.lock` 文件 | 崩溃残留 | **无需删除**（未锁定的文件不阻塞；删除反而引入竞态） |

## 2. 迁移中断恢复

- 单个 migration 在事务内执行：中断后重跑 `uv run ashare init-db`，
  已应用的跳过、中断的从零重放
- 出现 `MigrationTamperedError`：`git diff migrations/` 还原被改文件

## 3. 数据库文件损坏

每日 CHECKPOINT 后的一致性快照是恢复基线（V1.3.2 §39.6）：

```powershell
# 恢复最近快照（写连接空闲时）
Copy-Item data/db/atlas.duckdb.bak.<date> data/db/atlas.duckdb
uv run ashare init-db    # 补齐快照之后的新迁移
```

数据本体（Parquet）不受影响——DuckDB 只存元数据与指针，恢复元库后
按 manifest 重新校验 content_hash 即可对账（`find_orphan_files` 探测
未登记文件）。

## 4. 发布指针不一致

见 [publish_recovery.md](publish_recovery.md)。
