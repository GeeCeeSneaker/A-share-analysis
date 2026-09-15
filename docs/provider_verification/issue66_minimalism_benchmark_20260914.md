# Issue #66 最小化基准（合成数据）

日期：2026-09-14
用途：验证 RawWriter 对大型同构 provider map 的布局优化，以及一次 raw closure 校验后复用
`VerifiedRawEvidence` 句柄的边界成本。

## 测试条件

- 环境：本地 Windows 工作区，项目 `uv` 环境；不加载 AmazingData SDK，不连接网络，不使用真实
  账号、真实 endpoint 或真实 provider payload。
- 合成输入：5,000 个成员，每个成员 4 行、4 列，合计 20,000 行；所有成员 Arrow schema 相同，
  没有 `None` 成员。
- legacy 对照：临时把打包阈值设为 5,001，强制使用原来的“一成员一 Parquet”布局。
- 当前布局：阈值设为 128，使用一个 request-level Parquet，并在表内保留
  `__ashare_member__` 成员键；meta 同时保留成员 inventory。
- 每种布局均实际执行 `RawWriter.write()`、`verify_raw_evidence()` 和带验证句柄的读取，读取后
  校验成员数与总行数。

## 结果

| 指标 | legacy：5,000 文件 | packed：1 文件 | 变化 |
| --- | ---: | ---: | ---: |
| Parquet 文件数 | 5,000 | 1 | -99.98% |
| Parquet 物理字节 | 7,350,000 | 55,630 | -99.24% |
| 持久化耗时 | 43,506.66 ms | 2,245.52 ms | -94.84% |
| 完整 raw closure 校验 | 35,719.97 ms | 13.94 ms | -99.96% |

## 解读与边界

该结果只说明在同一合成 payload、同一机器和同一代码路径下，文件数及物理校验成本显著下降；
它不是实际 AmazingData 月份的吞吐承诺。小型或异构 map、成员名缺失、保留列冲突或 Arrow 无法
安全拼接时仍回退到原有布局。`None` 成员和空表不被制造成伪数据，meta 中的成员 inventory
用于读取时恢复其逻辑形态。

真实 Stage A raw 不在仓库，本轮没有执行 Stage B、78 月物化、正式账号测试或生产取数。实际
上线前仍需在独立审阅后，用已授权的最小 `2024-01` acquisition/materializer proof 验证 packed
布局与现有 anchored raw、normalization、reader 的兼容性。

## 下游边界的静态前后测量

本轮没有可安全公开的真实生产数据，因此下表记录的是代码路径计数，不冒充吞吐基准：

| 边界 | 整改前 | 整改后 | 意义 |
| --- | ---: | ---: | --- |
| Snapshot 消费时递归调用完整 canonical verifier | 1 | 0 | 先消费 canonical manifest/projection seal；owner 深审仍可显式调用 |
| Feature/R1 打开 ReadModel 后再次验证同一 snapshot | 2 | 1 | `open_read_only_with_snapshot()` 一次打开并交接已验证 snapshot |
| Publish 事务内读取/哈希大报告、组件和 DQ 输入 | 是 | 否 | 重量校验移到事务前；事务内只重绑小型 DB seal 和不变量 |

这些变化不等于实际端到端耗时承诺。真实 snapshot/readmodel open、构建峰值内存和发布耗时
需要在后续获准的最小 authoritative proof 上另行测量；Stage B、78 月回补和正式生产取数仍
保持 blocked。

## 评价对象的持久化收敛

`MonthCompletenessEvaluation` 现在只持久化：单一 `rule_version`、月度输入身份、最终
required/returned pair seal、missing/extra/unresolved 数量、结构性错误、正交易 pair seal
以及分类汇总。`applicable`、`suspended`、`not_applicable` 的中间集合哈希和评价内的重复
子版本字段已移除；交易 fallback 的 provider-operation 版本仍留在 acquisition receipt，
因为它是 receipt 对具体 fallback 操作的边界契约，而不是评价中间结果。
