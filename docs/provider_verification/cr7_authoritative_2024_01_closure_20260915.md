# CR-7 2024-01 权威闭环执行记录（2026-09-15）

状态：`STOP(BLOCKED)`；bounded materializer/reader 整改（含 identity scope binding）已在本分支
完成并待独立审阅，仍不铸造
authoritative receipt、不执行真实 materialization、不执行 Stage B。

本记录对应 Issue #59 当前要求，只检查 `2024-01`。原始 provider payload、账号凭证、私有
endpoint、SDK/runtime 和本地 raw 均不进入 GitHub；本文件只保留脱敏的运行结论、计数和边界。

## 已确认事实

| 检查项 | 结果 |
|---|---|
| 要求基线 | `1a14c87d19d527c56170df8bc9c24fccf69d55b3` |
| 实际开发基线 | `1a14c87d19d527c56170df8bc9c24fccf69d55b3` |
| 基线为当前 HEAD 祖先 | `TRUE` |
| 本地 SDK | `AmazingData==1.1.9`，已从工作区归档包安装 |
| 本地 TGW | `tgw==1.0.9.2`，运行时实际加载校验通过 |
| 本地账号 bootstrap | 网络可达、认证成功、查询就绪；脱敏画像与冻结身份匹配 |
| 凭证是否进入 Git | `FALSE`；只从未跟踪本地 `.env` 读取 |
| 工作区依赖归档 | `vendor/amazingdata/`，49 个文件，约 210,130,779 bytes；目录被 `.gitignore` 排除 |
| bounded scope 整改 | 已实现显式 typed partition scope；默认 78 月合同保持不变 |
| 历史物化聚焦回归 | 27 passed |
| 全仓 pytest | exit code `0` |
| ruff check / format / mypy | 全部通过；mypy 108 source files 无问题 |
| 可验证 ReadModel snapshot | `UNAVAILABLE` |
| authoritative acquisition receipt | `NOT_ISSUED` |
| retained raw replay | `NOT_STARTED` |
| coverage basis / materializer | `NOT_ENTERED` |
| ordinary reader proof | `NOT_STARTED` |
| Stage B / 78-month work | `NOT_RUN`、仍未授权 |

## 阻断一：verified source snapshot 不存在

当前本地可找到的 5 个 Atlas 数据库均没有可消费的 verified ReadModel/Canonical snapshot：

- `rm_snapshot_meta`、`rm_daily_bar`：0 行；
- canonical/readmodel 相关的 snapshot/build/run 表：0 行；
- 没有可供 `ResearchPanelBuilder.prepare_verified_projection()` 读取的已封存 snapshot manifest。

代码入口 `src/ashare_state/research/panel.py:163` 要求通过已验证的 ReadModel snapshot 和
canonical manifest 产生 `VerifiedResearchProjection`。上一轮 SPIKE 的报告、历史 raw、空的
fixture projection 或手工填写的 hash 都不能替代这个输入，否则会把 caller 数据误标为已验证
source snapshot。因而本次没有调用 `AmazingDataHistoryAcquisition.acquire_month()`，也没有把
任何真实响应提升为 authority。

解除条件：项目管理者提供一个能由现有 ReadModel/Canonical 校验链成功打开的本地 snapshot
根（或按既有链路授权并完成该 snapshot 的构建），同时保留其 snapshot id、manifest hash、
semantic hash、canonical run id 和 PIT；这些值可以脱敏记录，但不能用占位值代替。

## 已完成的最小整改：bounded materializer/reader

前置检查发现的单月合同不一致已在当前分支修正，且没有改变默认全窗口行为：

- `OfflineHistoricalMaterializer.plan/materialize()` 接受非空、去重、窗口内的 typed
  `materialization_partitions`；省略参数仍使用既有 78 个月窗口。
- 有界范围会裁剪范围外 projection rows，并让 coverage evaluation、artifact、inventory、
  basis 和 completeness evidence 只覆盖目标分区；范围外 coverage descriptor 会 fail closed。
- manifest 写入版本化 `materialization_scope`，其确定性 SHA-256 同时进入
  `materialization_identity`；因此同一 source/projection 的不同 scope 会产生不同的
  `idempotency_key`/`materialization_id`。reader 按 manifest scope 验证 inventory、每个
  enabled 分区的 authoritative evidence，并拒绝跨出已发布范围的读取。
- idempotent replay 复用同一 scope；manifest scope 改变、内容改变或 retained evidence 不一致时
  仍走既有 conflict/fail-closed 路径。
- 新测试覆盖单分区读取、跨分区拒绝、相同 scope replay、不同 scope 生成不同 identity 和变更
  内容冲突；既有 78 月测试也通过。

这项整改只证明代码边界可以承接一个月；测试使用的 fake receipt/fixture 不能作为生产 authority，
也不替代真实 2024-01 acquisition。

该整改尚需独立 exact-head 审阅；在真实 source snapshot 到位前，不运行会产生生产 receipt 的
acquisition。

## 当前唯一实质阻断

仍没有可由现有 ReadModel/Canonical 校验链打开的 verified source snapshot。当前本地检查的 5 个
Atlas 数据库中，`rm_snapshot_meta`、`rm_daily_bar` 以及 snapshot/build/run 相关记录均为 0；
因此无法合法构造 `VerifiedResearchProjection`，也无法执行 Issue #59 要求的真实 acquisition。

## 最小下一步要求

1. 项目管理者提供一个能由现有 ReadModel/Canonical 链成功打开的真实 source snapshot，保留
   snapshot id、manifest/semantic hash、canonical run id 和 PIT；账号可用本身不足以替代它。
2. 对当前分支的 bounded scope 整改做独立 exact-head 审阅并等待 CI 通过；本地 focused/full QA
   已通过。
3. 审阅通过且 snapshot 到位后，才运行唯一授权的 2024-01 acquisition，并按 Issue 顺序完成
   raw anchor、completeness PASS、receipt replay、coverage
   basis、atomic materialization、ordinary reader、idempotent replay/conflict fail-closed。
4. 在上述闭环独立审阅通过前，继续禁止 `2020-01`、`2026-01`、78 月回补、Formal B1-B7、
   Production、BSE/index、CR-5/R2、Golden/H1、baseline 和策略工作。

## 结论

本轮不是账号/网络阻断；bounded 发布合同已完成最小代码整改，当前唯一实质阻断是缺少可验证
source snapshot，另需独立审阅该整改。保持 fail-closed 是当前唯一可审计结论。下一次运行不得
复用本记录中的任何占位或历史 SPIKE 观察来铸造 receipt。
