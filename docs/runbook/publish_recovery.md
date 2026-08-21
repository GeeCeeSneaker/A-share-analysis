# Runbook — 发布中断恢复（Failure Injection A-D 实战对照）

> 原子发布契约：文件落盘 → Snapshot 登记 → Artifact 完成 → Publish 事务
> 切指针。任何一步崩溃都有确定的恢复语义（自动化测试已覆盖，此处是
> 人工操作对照）。

## 场景 A：文件已移动，DB 未登记（orphan）

**症状**：data 目录出现 manifest 未登记的 parquet。
**恢复语义**：对读取层不可见（无害）；可被启动恢复检查发现。
**操作**：

```powershell
# 探测（只报告，不删除）
uv run python -c "from ashare_state.pipeline import find_orphan_files; ..."
# 确认后人工删除（审计记录到 run log）
```

## 场景 B：Snapshot 已登记，未发布

**症状**：`meta_data_snapshot` 有 DATA_VALIDATED 行，但该 trade_date 的
latest publish 仍指向旧版本。
**恢复语义**：**无需恢复**——这就是契约行为（未发布 = 读者看不到）。
**操作**：重跑发布步骤即可（发布事务幂等入口）。

## 场景 C：Artifact 已验证，Publish 事务前崩溃

**症状**：`meta_feature_artifact_set` 有 FEATURE_VALIDATED 行，
latest publish 仍指向旧 artifact set。
**恢复语义**：新 artifact 对读者不可见；重跑 publish 事务。
**操作**：确认 artifact manifest 完整后重新发布。

## 场景 D：Publish 事务中途失败

**症状**：发布事务异常（如唯一键冲突）。
**恢复语义**：整个事务 ROLLBACK——旧 PUBLISHED 原样保持，无半成品
SUPERSEDED 残留。
**操作**：修数据（如重复 universe 行）后重跑发布；**不需要**人工修表。

## 通用纪律

1. 任何恢复操作前先复制 DuckDB 当日快照（recover_duckdb.md §3）
2. 恢复后验证：`latest_published()` 指向预期 publish_id；
   `artifact_files_for_publish()` 的每个 file 都过 content_hash 校验
3. 恢复动作记录进 run log（时间/原因/动作/验证结果）
