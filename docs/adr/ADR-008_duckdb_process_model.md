# ADR-008: DuckDB 进程级独占所有权模型

- 状态：ACCEPTED
- 日期：2026-08-21
- 决策人：设计者裁决（GO WITH CHANGES P0-1）
- 影响范围：`src/ashare_state/storage/connection.py`、所有 DuckDB 使用方

## 背景与问题

DuckDB 当前官方并发模型：

```text
模式 A：一个进程以 read-write 打开，可在该进程内部并发读写；
模式 B：多个进程以 read-only 打开，但此时不能同时存在写进程。
```

初版启动方案曾考虑"写进程独占 + 读侧 read-only 连接退避重试"，这隐含了**跨进程读写并存**的错误预期，设计者裁决否决。

## 决策

Phase 0 采用**数据库文件进程级独占所有权（DB Owner）**：

```text
atlas.duckdb 在任一时刻：
    要么由一个 Pipeline/CLI 进程持有（read_write 或 read_only）
    不承诺任何跨进程读写并存
```

实现要点（`DuckDBConnectionManager`）：

1. **外部排他 Gate**：数据库旁的锁文件（`atlas.duckdb.owner.lock`），Windows 用 `msvcrt.locking`、POSIX 用 `fcntl.flock` 做跨进程字节锁；
2. **第二个进程获取时立即失败**（`DatabaseOwnedError`，携带当前 owner 的 pid/mode 诊断信息）；`wait=True` 可选轮询等待；
3. **同进程内**：同模式 owner 可重入（引用计数）；混模式请求被显式拒绝（`OwnerModeConflictError`）；
4. **崩溃恢复**：OS 文件锁随进程终止自动释放——owner 被 kill 后数据库立即可用；残留的锁**文件**（无锁状态）不影响启动。

## 不做的事

- 不实现多进程读写锁/读写协调器；
- 不为"API 在 EOD 写入期间零中断读取"提前工程化——该需求出现时单独触发 ADR，候选方案：单一 Owner 服务进程 / 读副本快照 / 元数据迁移服务型 DB / 届时的 client-server 路径。

## 测试（`tests/integration/test_db_owner.py`，裁决要求全 4 项）

1. 两个写进程竞争：第二个明确失败（子进程实测）；
2. 写进程持有期间：从不断言"应该可以读"（所有权对所有模式拒绝）；
3. owner 异常退出（kill）：锁立即可恢复；
4. 锁残留文件：不造成永久阻塞。

## Phase 1 触发条件

当出现"查询服务需在 EOD 窗口内持续可用"的真实需求时，重开 ADR 评估（届时 FastAPI 已进入关键路径）。
