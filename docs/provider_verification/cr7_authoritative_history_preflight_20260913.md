# CR-7 三个月真实源预检收据摘要

日期：2026-09-13
Issue：#55  `P0: CR-7 authoritative historical evidence and bounded real-source preflight`
基线：`main@2e9bdc36544c5320072969a2888180b6dfec2c7a`
实现提交：`624595f1d246597a9119959af975aa5f8eafd6ff`
机器收据：[`cr7_authoritative_history_preflight_20260913.json`](cr7_authoritative_history_preflight_20260913.json)
GitHub 提交字节 SHA-256：`364cee560ae69e1651e619060308741398170414b49de878e5405fba1a8c9449`

## 结论

预检结果为 **`FAIL_CLOSED_BLOCKED`**。三个固定月份的 Provider 观察均成功，但当前来源合同
没有提供可审计的上游 inventory/range completeness statement，不能证明该月份的完整
`daily_bar` 范围及其历史可用性/PIT 语义。因此：

- `authoritative_evidence`：`NOT_PRODUCED`；
- 阻断码：`UPSTREAM_COMPLETENESS_STATEMENT_MISSING`；
- `materializer`：`NOT_ENTERED_FAIL_CLOSED`；
- 没有把 SDK/HTTP 成功、返回行数、日历结果、日期连续性或单个哨兵的日线结果升级为 `COMPLETE`。

## 固定范围与实际观察

| split | 月份 | 固定调用 | 调用结果 | 观察计数（calendar / code-list / sentinel） |
| --- | --- | --- | --- | --- |
| Development | 2020-01 | 3 | `OK / OK / OK` | 8724 / 3769 / 16 |
| Validation A | 2024-01 | 3 | `OK / OK / OK` | 8724 / 5106 / 22 |
| Holdout | 2026-01 | 3 | `OK / OK / OK` | 8724 / 5186 / 20 |

计数仅是脱敏的观察摘要，不是完整性证明；所有请求参数、操作标识和内容哈希均在机器收据
中保留，未保留证券代码、账号资料、服务地址或原始 Provider payload。

## 边界与后续阻断

本次只调用已审阅的 AmazingData history surface，每月最多一个 daily-bar sentinel；原始交换
只写入本地 ignored raw 目录，未进入 GitHub。未执行 78 月物化、broad backfill、universe sweep、
第三次 Formal/B1-B7、Production、`--resume`、`--verdict`、BSE/index 激活、CR-5/R2、Golden/H1、
baseline 或策略工作。

解除当前阻断所需的最小补充材料是：由上游或等价可审计来源明确声明每个目标月份的完整
daily_bar inventory/range，并独立说明其历史可用性与 PIT/available-at 语义；在该材料进入
typed sidecar 并通过 writer/reader 重验前，普通 reader 和 materializer 必须保持关闭。

账号、密码、IP、端口、Token、Cookie、专有 SDK/runtime 和原始 Provider payload 不得进入 GitHub。
