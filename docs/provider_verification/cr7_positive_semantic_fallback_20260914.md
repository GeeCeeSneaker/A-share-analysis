# CR-7 同源正向交易事实 fallback 探针摘要

日期：2026-09-14
实现 exact head：`dfb0e4875f17fe7dd3bbbfdf5bc608e642833782`
机器 receipt：[cr7_positive_semantic_fallback_20260914.json](cr7_positive_semantic_fallback_20260914.json)

## 审阅范围

本次只使用 Owner-approved 的 AmazingData，固定检查保留状态 schema blocker 对应的一个成员和
`2024-01`。适用性来自保留交易日历及 22 个精确 `[D,D]` historical code-list 请求；没有查询其他
成员、月份或数据源，没有运行 Stage B、78 月物化、Formal/Production、BSE/index、CR-5/R2、
Golden/H1、baseline 或策略工作。

调用面是 `MarketData.query_snapshot`，时间窗固定为 `09:30:00.000`–`15:00:00.000`。报告和本摘要
不包含证券值、账号、密码、私有 endpoint、raw payload 或专有 SDK/runtime。

## 合同与判定

安装的 `AmazingData==1.1.9` / `tgw==1.0.9.2` 暴露以下候选活动字段：

| 候选事实 | 字段 | 正向条件 |
|---|---|---|
| 交易笔数 | `num_trades` | 有限且严格 `> 0` |
| 成交量 | `total_volume_trade` / 转换后的 `volume` | 有限且严格 `> 0` |
| 成交额 | `total_value_trade` / 转换后的 `amount` | 有限且严格 `> 0` |

当前证据等级是“公开字段名 + typed annotation + SDK conversion surface”。没有找到独立供应商字段
说明原文，所以没有推导单位，也没有把空响应、非空响应、价格/盘口、零值或 callback 标签解释为
交易事实。正式是否接受这组候选合同由独立 Reviewer/Owner 决定。

## exact-head 观察

- 适用交易日：22；返回数据日：22；正向候选字段通过：22/22。
- 返回帧：每帧 35 列，合计 96,781 行；每个适用日均有正向候选字段行。
- callback：22 次，`data` 非空 22 次；callback 状态标签仅作诊断记录，不参与正向语义判定。
- 本地证据：22 个分日 raw exchange，状态为 `PERSISTED_LOCAL_IGNORED_ONLY`；GitHub 仅保留脱敏的
  shape、计数、日期和 hash。

## 结论与下一道门

探针结论：`PROVIDER_SEMANTIC_RESOLVED`。实现状态：`EVIDENCE_ONLY_PENDING_REVIEW`。

这不是正式 fallback、capability approval 或全库历史完整性证明。`fallback_rule_encoded=false`，
没有修改 `month_completeness.py`，没有生成 authoritative receipt/materializer。下一步由独立
Reviewer/Owner 核对 exact head、机器 receipt、请求范围、字段合同等级及脱敏边界；在其明确裁决前，
Stage A 的 unresolved pair 和所有受禁工作保持不变。
