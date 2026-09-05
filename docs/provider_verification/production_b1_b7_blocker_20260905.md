# Formal Production B1-B7 预检阻断记录

> 记录日期：2026-09-05（Asia/Shanghai）  
> 记录时间：2026-09-05T23:23:51+08:00  
> 目标源码：`main` @ `b1f85de4b35eb3480534f93bbdcd9f91a52f3830`  
> 文档性质：安全投影后的执行阻断记录，不是 Formal B1-B7 结果证据

## 1. 结论

已按 T3 授权的唯一正式入口尝试执行：

```text
uv run python scripts/spike/spike_runner.py --production --date 20260904
```

项目交易日历通过 Provider 门面确认 `20260904` 是当前截止日前最近的完整交易日（安全摘要：日历行数 8719，最近日期 `20260904`）。

运行器完成了本地 SDK 登录和冻结身份的精确匹配检查，但在创建 `RunKind.PRODUCTION` / `SpikeRun` 之前，被 Golden Truth 前置门 fail-closed 拒绝：

```text
PRODUCTION run refused
```

因此本次没有正式 `run_id`，没有 B1-B7 执行结果，也没有同一 run 的 verdict。

## 2. 已确认事实

| 项目 | 结果 |
|---|---|
| 目标 RunKind | `PRODUCTION` |
| as_of_date | `20260904` |
| 账号身份 | 冻结 scrubbed ID `UNKNOWN_24e2ff401792`，精确匹配检查通过后才进入 Golden 门 |
| 本地环境 | Windows / Python 3.14.6 |
| SDK 绑定 | AmazingData 1.1.9 / tgw 1.0.9.2 |
| TGW runtime | `V4.3.0.260626-rc2.0-YHZQ` |
| 运行器退出语义 | `formal run refused`，退出码 2 |
| SpikeRun 是否创建 | 否 |
| B1-B7 是否执行 | 否 |
| verdict 是否计算 | 否 |
| 凭证/真实端点是否写入本 PR | 否 |

## 3. 阻断原因

当前主分支 Golden Truth 数据仍未满足生产 run 创建前的硬门：

1. `golden_st_transition` 的结构化 `ST_TRANSITION` 事件为 10，要求至少 50；
2. 没有 `ST_REMOVE` / `STAR_ST_REMOVE` 事件；
3. 不同退市证券数量为 10，要求至少 20；
4. 人工复核状态为 `REVIEWED 0/123`，当前条目仍为 `COMPILED`。

这些是运行器根据现有 Golden Truth 与 review gate 重新计算出的阻断事实，不是通过日志猜测或把失败 case 拼接得到的结论。

## 4. 状态语义

本次不得标记为 `FAILED`、`ABORTED` 或 `CLOSED`：

- `FAILED` / `ABORTED` / `CLOSED` 都要求已有正式 run 生命周期；
- 本次在 `new_run` 的生产前置校验阶段退出，尚未铸造 `SpikeRun`；
- 因而没有可供 `--verdict --run-id` 使用的 ID。

也不允许用 T1 bootstrap、provider-doctor、dry-run、Trial 或旧 smoke 结果替代本次 Formal B1-B7 结果。

## 5. 下一步解除条件

在重新申请/执行 Formal Production B1-B7 前，项目管理者需要：

- 补齐并验证至少 50 个结构化、可追溯的 `ST_TRANSITION` 事件，且同时包含 ADD 与 REMOVE 子类型；
- 补齐至少 20 个不同退市证券的可追溯事件；
- 为 123 个 Golden 条目完成真实人工复核及来源 artifact/hash 闭合；
- 重新生成并自验证 ACTIVE manifest，保持 dataset 内容、统计、事件覆盖和 review provenance 一致；
- 通过必需 CI，并在文档中记录新的授权边界；
- 完成后，才可依据同一治理流程重新执行一次完整 B1-B7，并仅对该次实际达到 `CLOSED` 的 run 计算 verdict。

在上述条件满足前，不应批准 Provider capability、Data Sufficiency Matrix、2020+ backfill 或策略/交易工作。

## 6. 审阅检查清单

- [x] 目标日期来自 Provider 交易日历事实，不是周末日期猜测；
- [x] 使用 Production 全阶段入口，未选择单 phase；
- [x] 冻结身份没有被改写或绕过；
- [x] 阻断发生在 run 创建前，生命周期语义保持诚实；
- [x] 未生成或上传账号密码、Token、真实地址、raw profile、raw SDK 输出、专有 SDK 文件；
- [ ] Formal B1-B7 已实际执行；
- [ ] 同一 run 的正式 verdict 已产生；
- [ ] Provider capability / Data Sufficiency / backfill 已获后续 Reviewer 授权。
