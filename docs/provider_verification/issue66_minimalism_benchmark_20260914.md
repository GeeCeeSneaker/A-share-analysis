# Issue #66 最小化基准（合成数据）

日期：2026-09-14
用途：验证 RawWriter 对大型同构 provider map 的布局优化，以及一次 raw closure 校验后复用
`VerifiedRawEvidence` 句柄的边界成本。

## 测试条件

- 环境：本地 Windows 工作区，项目 `uv` 环境；不加载 AmazingData SDK，不连接网络，不使用真实
  账号、真实 endpoint 或真实 provider payload。
- 合成输入：5,000 个正常成员，每个成员 4 行、4 列，合计 20,000 行；另加入 1 个已知形态的
  零行零列 DataFrame 和 1 个显式 `None`，共 5,002 个逻辑成员。
- legacy 对照：临时把打包阈值设为 10,000，强制使用原来的“一成员一 Parquet”布局；零行零列
  成员因此仍占一个物理文件。
- 当前布局：阈值设为 128，使用一个 request-level Parquet，并在表内保留
  `__ashare_member__` 成员键；meta 同时保留成员 inventory 与每个成员的原始列名。零行零列
  成员不制造伪行，而由 inventory 重建为 `(0, 0)`；显式 `None` 仍不落物理表。
- 每种布局均实际执行 `RawWriter.write()`、`verify_raw_evidence()` 和带验证句柄的读取，读取后
  校验成员数、总行数、零列空表和 `None` 的形态。packed 读取使用一次 `partition_by` 分组，
  不对每个成员重复过滤完整 packed frame。

## 结果

| 指标 | legacy：5,001 文件 | packed：1 文件 | 变化 |
| --- | ---: | ---: | ---: |
| Parquet 文件数 | 5,001 | 1 | -99.98% |
| Parquet 物理字节 | 7,174,641 | 84,344 | -98.82% |
| 持久化耗时 | 45,911.01 ms | 3,609.53 ms | -92.14% |
| 完整 raw closure 校验 | 44,985.21 ms | 53.97 ms | -99.88% |
| 带 verified handle 的读/重建 | 14,919.95 ms | 3,032.02 ms | -79.68% |

## 解读与边界

该结果只说明在同一合成 payload、同一机器和同一代码路径下，文件数及物理校验成本显著下降；
它不是实际 AmazingData 月份的吞吐承诺。小型或异构 map、成员名缺失、保留列冲突、非空零列
成员或 Arrow 无法安全拼接时仍回退到原有布局。零行零列表格不被制造成伪数据，显式 `None`
也不被混同为空表；meta 中的成员 inventory 用于读取时恢复两者的逻辑形态。读取基准包含
分组与每个逻辑成员的 DataFrame 重建，避免只测写入而遗漏下游消费成本。

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
