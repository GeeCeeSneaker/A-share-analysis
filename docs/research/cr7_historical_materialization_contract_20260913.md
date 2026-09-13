# CR-7 历史研究数据物化合同（设计 / 离线预检）

日期：2026-09-13
基线：main@53257c36e8ada5576f5d2dfce0947710ee24694c
状态：DESIGN_ONLY_NOT_ACTIVE
机器合同：cr7_historical_materialization_contract_20260913.json

## 1. 这张切片解决什么问题

PR #51 已关闭 R1 研究消费筛选子切片。Issue #39 最新调度要求的下一步不是直接回填
2020–2026H1，而是先把历史物化的边界写成可审阅、可测试、可重放的合同。本文件因此只
定义未来实现必须遵守的输入、分区、覆盖、证据、恢复和验收规则；它不创建历史研究数据，
不接 Provider，也不授权任何生产或 Formal 操作。

目标数据集限定为 research_security_daily。research_index_daily 继续保持
DISABLED_UNVERIFIED_INDEX_IDENTITY，不因本设计获得启用资格。

## 2. 授权与硬边界

本合同明确关闭以下权限：

| 操作 | 本切片 |
| --- | --- |
| Provider / AmazingData 调用 | 禁止 |
| Production、--resume、--verdict | 禁止 |
| 第三次 Formal B1–B7 | 禁止 |
| 2020–2026H1 历史物化执行 | 禁止 |
| broad backfill / universe sweep | 禁止 |
| BSE mapping 激活 | 禁止 |
| index 激活、CR-5/R2 feature export | 禁止 |
| Golden、H1、global baseline 修改 | 禁止 |
| 策略实现或参数优化 | 禁止 |

合同只允许提交 JSON 设计和不触碰 Provider 的离线回归。凭证、真实 endpoint、Token、
Cookie、专有 SDK/runtime 和原始 Provider payload 不能进入 GitHub。

## 3. 输入资格与 PIT

未来实现必须从现有 ResearchPanelBuilder.build_from_readmodel 入口开始，只接受一个
已经通过 CR-4 完整验证的 ReadModel snapshot。一次物化不得把多个 snapshot、不同
canonical run 或未经验证的 caller rows 拼在一起。

最小输入身份必须包含：

- source_snapshot_id、source_snapshot_as_of；
- snapshot manifest hash 和 semantic hash；
- source_canonical_run_id、source_readmodel_contract_version；
- versioned identity_view 的版本、hash、source kind 和 lineage hash；
- 已验证 security-master normalized output 的 manifest/output/schema/set/semantic
  证据；
- 对每一行重新确认 available_at <= materialization_as_of。

Snapshot、ReadModel、identity lineage 和物理 artifact 的完整性验证必须发生在行筛选、
分区和任何输出 hash 之前。不能使用当前 code-list 反推出历史可交易性，也不能从
security_id 猜 symbol 或 exchange。

## 4. 目标窗口与分区

研究主样本是闭区间 2020-01-01 至 2026-06-30：

| split | 日期闭区间 | 用途 |
| --- | --- | --- |
| development | 2020-01-01–2023-12-31 | 探索和规则开发 |
| validation_a | 2024-01-01–2025-12-31 | 验证 Development 结论 |
| holdout | 2026-01-01–2026-06-30 | 最终独立检验 |

2020 年以前的数据只能作为 warm-up / PIT 输入，不进入本物化主样本；2026-07-01
之后的数据也不属于本合同。

建议的逻辑日期分区键是：

    research_split + calendar_year + calendar_month

route 是该日期分区下面独立的物理 artifact 子键：

    research_route + research_split + calendar_year + calendar_month

按该窗口计算，逻辑月份分区数固定为 48（Development）+ 24（Validation A）+ 6
（Holdout）= 78。inventory 必须先显式登记全部 78 个日期逻辑分区，再在每个日期
分区下显式登记各 route 的计数和 coverage state，并为实际存在的 enabled、disabled
或 experimental route 保存独立 artifact descriptor；不存在的 route 不能被悄悄当成
“市场没有交易”或“全市场零事件”。

每个 route artifact 都必须只属于一个 split、一个 route 和一个年月，行按
trade_date, security_id, source_canonical_key 稳定排序。重复
trade_date + security_id 主键、重复 route artifact key、缺失日期逻辑分区、跨 split
行或越过目标窗口的行都必须 fail closed。

## 5. 研究资格与 BSE / disabled 隔离

每行沿用 R1 的机器资格分类：

- RESEARCH_ENABLED：进入 enabled route；
- RESEARCH_DISABLED_UNRESOLVED：保留到 disabled route，不进入普通读取；
- RESEARCH_EXPERIMENTAL：与正式 enabled route 物理或逻辑隔离，默认不可读。

没有可验证的身份、日期、字段语义或 PIT 证据时，不补值、不删除、不把未知解释成
零收益或负向事件。disabled 行必须保留原因码、source lineage 和原始可诊断身份。

BSE 在本阶段继续执行 DISABLE_ALL_BSE_ROWS_IN_R1：即使 symbol/exchange 已被
解析且 OHLCV 结构有效，也只能进入 disabled，并标记
bse_identity_boundary_unresolved。本合同不激活 835185/920185 mapping，也不
把 BSE 行移入研究主样本。

## 6. 覆盖状态不是行数

每个分区和整体物化都要有明确覆盖状态：

- OBSERVED_DAILY_BAR_COVERAGE：输入范围和完整性证据覆盖该分区；计数仍只描述
  实际观察到的日线行；
- PARTIAL_OBSERVED_DAILY_BAR_COVERAGE：分区可读，但输入明确只有部分覆盖；
- UNRESOLVED_NOT_FOR_RESEARCH：覆盖、身份、日期适用性或来源完整性无法建立，必须
  继续隔离。

对每个 route 独立聚合状态；enabled route 的整体状态取其声明分区中最差状态，顺序为
OBSERVED < PARTIAL < UNRESOLVED。不能因为有很多行、月份连续或 row count
看起来合理，就把 PARTIAL / UNRESOLVED 提升为 OBSERVED。缺失 bar 也不能转成
零值、下跌、未发生事件或排名中的负向样本。

disabled / experimental route 的覆盖状态单独留在诊断 inventory 中，不会因为已知
被排除的 BSE 或其他 unresolved 行而把可靠的 enabled route 降级；反过来，enabled
route 的覆盖缺口也不能被 disabled 行数抵消。

普通 reader 只有在 materialization 已提交且选中的分区覆盖状态为
OBSERVED_DAILY_BAR_COVERAGE 时才能读取。PARTIAL 或 UNRESOLVED 必须由未来
另行批准的显式诊断合同处理，不能通过模糊默认参数绕过。

横截面和宽度统计若未来接入，必须随结果保留 observed security count、有效值计数
和 coverage state；OBSERVED_DAILY_BAR_UNIVERSE 绝不等于 ALL_A_SHARES，
也不宣称 survivorship-bias-free。

## 7. 确定性、幂等和不可覆盖

物化身份由以下字段的 compact、sorted-key、UTF-8 canonical JSON 组成：

- 合同、schema、分区与 coverage policy 版本；
- 目标数据集和完整窗口；
- 三个 split 的闭区间；
- 唯一 source snapshot / canonical / ReadModel 身份及所有 hash；
- identity view 和 source lineage 身份；
- UNADJUSTED_CANONICAL 与 OBSERVED_DAILY_BAR_UNIVERSE；
- build code fingerprint。

build_timestamp 是审计字段，不能进入 identity 或输出内容 hash。合同固定：

    idempotency_key = sha256(canonical_json(materialization_identity))
    materialization_id = rhm-<full lowercase idempotency_key>

相同 identity 再执行时必须先验证 manifest、inventory、每个分区的字节、schema、row
count、semantic hash 和主键，再返回 IDEMPOTENT_REPLAY，不得覆盖已有文件。相同
ID 但字节或元数据不一致是 MATERIALIZATION_IDENTITY_CONFLICT，必须失败关闭；禁止
last-write-wins。不同 identity 必须进入不同确定性 materialization 目录，并保留既有
发布物。

## 8. staging、恢复与原子发布

未来执行必须先写到：

    research_security_daily/.staging/<materialization_id>/

staging 中的分区文件、排序 inventory 和 manifest 都不能被普通 reader 发现。只有
所有分区完成以下检查后，才能生成 _SUCCESS.json：

1. source snapshot / ReadModel / identity lineage 已验证；
2. 每个 route artifact 的 schema、字节 hash、semantic hash、row count、主键和日期
   范围已重算；
3. inventory 与 78 个预期日期逻辑分区集合精确一致，且每个嵌套 route artifact
   descriptor 与实际非空 artifact 精确一致；
4. aggregate partition_inventory_hash、artifact_set_hash 和 content_hash 已
   从实际内容重算；
5. manifest 中 publication_state、coverage 和 lineage 与上述结果一致。

_SUCCESS.json 记录已提交 manifest hash，只能在以上检查全部成功后写入。reader 只认
有效 marker 和 COMMITTED manifest；缺 marker、缺分区、旧 staging 或失败临时文件
均不可读。

未来允许 resume，但只能复用同一 materialization identity 的 staging 分区，而且每个
已存在分区仍需完整重验。resume 不得改变 source snapshot、split、policy、schema 或
code identity。任意失败都不能改变旧的 committed materialization，也不能暴露新的
半成品。

## 9. 证据与 inventory

每个分区至少要留下以下不含敏感数据的证据：

- route、split、年月和确定性 URI；
- row count、enabled/disabled count、min/max trade date；
- Parquet 精确字节数与 SHA-256；
- schema hash、canonical-row semantic hash；
- source snapshot id 和 coverage state。

整体 manifest 还要绑定 target window、split windows、78 个日期逻辑分区及其 route
descriptor、所有 source/readmodel/identity
lineage、policy/schema/code 版本、分区 inventory、inventory hash、artifact set hash、
aggregate content hash、build timestamp 和 publication state。

哈希输入不能包含 retrieval time、filesystem mtime、temporary path、credentials 或
raw Provider payload。原始 Provider 返回若未来确有合法留存需求，仍必须遵守既有本地
ignored/raw 规则；本合同不授权将其上传仓库。

## 10. 有界离线验收夹具

机器合同附带 cr7-history-materialization-boundary-fixture-v1，只描述 verified
ReadModel 形状，不访问 Provider。夹具覆盖：

- 六个 split 闭区间边界日期；
- 一个 BSE 835185 行，必须在 disabled route；
- 一个 identity unresolved 行，必须保留在 disabled route；
- 2019-12-31 和 2026-07-01 两个窗口外行，必须不被物化；
- sparse fixture 下仍要求 inventory 声明 78 个日期逻辑月份，route 子项单独计数；
- all-observed、partial-input、unresolved-input 三种 coverage 聚合场景；
- 相同 identity 重放、变更行或 source hash、冲突覆盖和无 Provider 调用。

该夹具不提供真实市场覆盖结论，不替换 2020 baseline，不把 601558 或 600068 激活为
历史 fixture，也不产生任何 Golden/H1 或 Formal 结果。

## 11. 后续实现前必须满足的闸门

本设计完成后，项目管理者和独立 Reviewer 仍需先接受：

1. 输入 snapshot / ReadModel / identity lineage 的绑定字段；
2. 78 逻辑月份的分区与 exact inventory 规则；
3. coverage 聚合与普通 reader fail-closed 规则；
4. identity、row、snapshot 变化下的幂等和冲突行为；
5. staging / resume / atomic publication 规则；
6. 分区与 manifest hash 的可重算性；
7. 有界夹具的离线断言。

只有这些设计闸门接受后，才能另开实现 PR；还需要新的明确调度授权，才能执行
2020–2026H1 物化。当前不宣称历史已物化、不宣称全覆盖、不宣称 R2 或 Formal 已就绪。
