# Issue #59 · current-code-first identity event and 2024-01 source-chain replay

状态：`IDENTITY_FIX_IMPLEMENTED / SOURCE_CHAIN_VERIFIED / AUTHORITATIVE_CLOSURE_VERIFIED / REVIEW_PENDING`

## 范围与依据

- Issue：[#59](https://github.com/GeeCeeSneaker/A-share-analysis/issues/59)
- 调度依据：Issue comment `5691600928`
- clean main：`c360354bee8698c8a2db61a607d0bb3dcefd0ddb`
- 本地实现分支：`investigate/issue59-identity-event-20260916`
- 事件来源：Owner-approved official SZSE/CNINFO static security-identity event，按 Issue #59 记录；本报告不扩展为第二个市场数据源。

## 已实现的最小行为

| 项目 | 结果 |
|---|---|
| 历史 provider symbol | `300114.SZ`，`[2010-08-27, 2025-02-17)` |
| 当前 provider symbol | `302132.SZ`，`[2025-02-17, ∞)` |
| 原始上市日 | `2010-08-27` |
| 稳定身份 | 两个 symbol 共用同一 ADR-002 派生 `security_id` |
| bridge policy | `identity-bridge-v2` |
| 默认 current lookup | `302132.SZ` |
| 2024 PIT lookup | `300114.SZ` |
| 5,106-member universe | 未修改 |

实现复用现有 identity/provider-symbol bridge，只增加一个静态事件记录、current lookup
和显式 PIT 解析；没有新增通用 alias engine、corporate-action framework、service、表层级
或多源 reconciliation。

## 2024-01 source-chain replay

为避免把旧代码生成的 normalization 运行误当成当前代码的可消费输入，本地复制了此前已
锚定的 retained raw，并新建隔离 DuckDB ledger。旧 ledger 未修改、旧 raw 未修改；新 ledger
只重新验证原 anchor，再按当前 mapper 代码重建运行。旧 normalization 指纹被 closure verifier
拒绝属于预期的 fail-closed 行为，不是通过删除历史记录绕过。

| 层级 | 结果 |
|---|---|
| `trade_calendar` normalization | `SUCCESS`, 8,726 rows |
| `hist_code_list` normalization | `SUCCESS`, 5,106 rows |
| `stock_basic` normalization | `SUCCESS`, 5,105 rows |
| `daily_bar` normalization | `SUCCESS`, 112,075 rows |
| Canonical | `SUCCESS`, selected 112,075, findings 0 |
| Snapshot | `SUCCESS`, 112,075 rows |
| ReadModel | `SUCCESS`, 112,075 rows |
| `prepare_verified_projection()` | `SUCCESS`, 112,075 rows |
| current identity lookup | `302132.SZ` |

这一步只证明当前代码能够消费已锚定 source input 并完整通过
`Canonical -> Snapshot -> ReadModel -> prepare_verified_projection()`；它不是本次新的
AmazingData acquisition，也没有生成 authoritative receipt、coverage basis 或 materialization。

## QA

已通过 identity bridge、Canonical identity/PIT、R1 current/PIT display 及完整 Canonical
回归；命令与精确结果记录在 DEVLOG 和 PR 中。真实 raw、DuckDB、SDK/runtime、账号 profile、
凭证、Token、Cookie 和私有 endpoint 均只存在本地忽略目录或运行环境。

## 已完成的 2024-01 authoritative closure

随后按 Issue #59 的唯一授权范围，以正式账号通过进程环境变量登录，并明确使用
`ProviderUseMode.SPIKE` 完成一次真实采集。`SPIKE` 是代码层调用门控，不等于 Formal B1-B7
或 Production capability 已批准；账号值、profile、私有地址和 provider 原始响应不在本报告。

| 检查项 | 结果 |
|---|---|
| 证券 universe | 5,106 |
| 交易日 | 22 |
| returned daily rows | 112,075 |
| required / returned pairs | 112,075 / 112,075 |
| missing / extra / unresolved | 0 / 0 / 0 |
| structural errors | 空 |
| completeness | `PASS` |
| 分类 | `SUSPENSION_NON_TRADING=132`; `NOT_APPLICABLE_SESSION=125`; `POSITIVE_TRADE_COUNT_ACTIVE=22` |
| receipt | 已签发，二次 `verify_retained_capture()` 通过 |
| coverage | authoritative evidence 与 basis 均成功构造 |
| bounded materialization | `validation_a:2024-01` 成功 |
| ordinary reader | 读回 112,075 行 |
| replay / conflict | `idempotent_replay=true`；修改内容的重放被 `MaterializationConflictError` 阻断 |

完整脱敏 receipt、coverage、materialization ID/hash 和本地捕获目录见同批
`cr7_issue59_authoritative_2024_01_closure_20260916.md` 及对应 JSON。原始捕获、DuckDB、
Parquet 和 SDK/runtime 仍只保存在本地忽略目录，未进入 Git。

## 下一步与边界

本分支只需完成本地 QA、提交 Draft PR 并等待独立 PM 审阅；不能自行标记 Production 或
推进 Stage B。`2020-01`、`2026-01`、78 月回补、Formal/Production、BSE/index、CR-5/R2、
Golden/H1、baseline 和策略工作均未授权。
