# A-share-analysis CR-7：研究就绪日频数据层开发工作要求

**日期**：2026-09-12  
**基线**：`main@0630c757bd59df6c8e3235eb88621376be99a74e`  
**状态**：需求设计 / 待独立审阅 / 本文档不授权 Production 或第三次 Formal  
**目标仓库**：`GeeCeeSneaker/A-share-analysis`  
**主要下游**：`GeeCeeSneaker/Quantitative-Strategy-Research`

---

## 1. 为什么现在进入这个阶段

A-share-analysis 的目标不是建设一个“交易所公告数据库”，也不是在所有数据边界都解释到 100% 之后才开始量化研究。

项目的主要价值是：

> 把 A 股历史行情、成交、指数、可确认的交易状态以及由这些数据确定性计算出的特征和市场状态，整理成稳定、可复现、可直接研究的数据基础；然后由真实的策略研究持续反向提出新的数据需求。

前一阶段已经证明：AmazingData 的部分边界字段仍存在含义、历史状态或特殊记录无法完全确认的问题。但这些问题短期内不会阻塞趋势、动量、反转、量价、市场宽度、择时、轮动、风险和横截面研究。

因此从 CR-7 开始，项目采用以下工作原则：

1. **可靠且含义明确的数据，立即进入研究主线。**
2. **不确定的数据继续保存，但默认禁止研究使用。**
3. **不猜、不补、不为了“看起来完整”而修复不确定字段。**
4. **只有具体研究课题真正依赖某个不确定字段时，才重新打开对应问题。**
5. **交易所公告/一手文档在本阶段主要是数据校验工具，不是研究信号来源。**
6. **不再以 source-contract、第三次 Formal 或边界语义全部闭合为研究主线前置条件。**

这一原则不降低数据质量要求，而是把质量管理从“所有问题必须先解决”改成“明确哪些可以用、哪些暂时不用”。

---

## 2. CR-7 的直接目标

建设一个 **Research-Ready Daily Data Layer（研究就绪日频数据层）**，让下游研究代码不需要理解 AmazingData SDK、Provider 调用、raw artifact、公告检索或历史治理过程，就可以稳定读取研究数据。

第一阶段完成后，研究者应该能够用一个稳定入口回答类似问题：

- 过去 N 日涨幅、波动、成交额变化和未来收益有什么关系？
- 强趋势股票在不同市场环境下是否有不同延续概率？
- 高换手与低换手趋势的后续表现是否不同？
- 市场上涨/下跌家数、创新高/新低、涨跌幅分布是否有择时价值？
- 个股相对指数强弱是否具有持续性？
- 市场整体风险偏好变化时，不同类型信号表现如何？
- 后续行业/板块数据成熟后，板块扩散、轮动和强弱切换是否存在稳定规律？

CR-7 不是策略实现；它负责把数据整理到“可以安全、低摩擦做这些研究”的状态。

---

## 3. 与已有 CR-5 / CR-6 的关系

### 3.1 不重造 Feature Layer

CR-5 已经建立确定性 Feature Layer，当前代码中已有 `FeatureBuilder`、`FeatureEngine`、Feature Registry、Feature Verifier 和不可变 Feature Run 机制。

CR-7 必须复用该能力。

后续研究代码不得绕过 Feature Layer 重新从 Provider/raw 数据计算一套同名正式特征；确有实验性公式时，可以先存在研究仓库中，验证成熟后再按独立变更进入正式 Feature Registry。

### 3.2 不重造 Market State Layer

CR-6 已定义确定性 Market State Layer。

CR-7 的职责是给市场状态计算提供一个明确的“研究可用输入集合”和稳定输出入口，而不是重新定义一套平行的市场状态框架。

### 3.3 新增的是“研究消费边界”

CR-7 主要补足现有架构中研究者真正需要的一层：

```text
Provider / Raw
      ↓
Canonical / ReadModel
      ↓
Research Eligibility Gate   ← CR-7 新增重点
      ↓
Research Daily Panel
      ├──> CR-5 Verified Feature Run
      ├──> CR-6 Market State
      └──> Quantitative-Strategy-Research
```

研究仓库默认只能消费 `Research Eligibility Gate` 之后的数据。

---

## 4. 数据使用分级

CR-7 必须把数据分成至少三类，分类应机器可读，不得只写在文档中。

### A. `RESEARCH_ENABLED`

当前含义清楚、结构稳定、可以进入默认研究数据集的数据。

首批至少包括：

- 交易日期；
- 证券统一标识及当前已可靠映射的市场标识；
- 股票日线：open / high / low / close；
- volume / amount；
- 可可靠取得的 pre-close 或等价前收盘输入；
- 指数日线；
- 已经通过现有结构验证、且含义明确的数值型涨跌停相关输入；
- 从上述字段确定性计算出的基础收益、振幅、缺口、成交变化、价格位置等特征；
- CR-5 已正式注册并通过验证的特征；
- CR-6 在可用输入上生成的正式市场状态。

### B. `RESEARCH_DISABLED_UNRESOLVED`

数据可以保存、可以进入 canonical/raw lineage，但默认研究入口必须排除。

当前至少包括：

- 尚未完全确认的历史上市/退市状态语义；
- 少量身份或日期异常的历史 ST/停牌记录；
- 尚未确认进度码/关键日期含义的公司行为记录；
- 需要进一步处理的 BSE 历史代码边界；
- 尚未完成适用性验证的历史退市测试 fixture；
- 未来发现的任何“值存在但含义不能确认”的字段。

规则：

- 不删除；
- 不静默纠正；
- 不用猜测值填充；
- 不进入默认研究 Panel；
- 保留原因码，例如 `semantic_unresolved`、`identity_unresolved`、`date_unresolved`、`fixture_deferred`；
- 研究课题明确需要时再单独开需求解决。

### C. `RESEARCH_EXPERIMENTAL`

可以用于探索，但尚未晋升为正式平台数据，例如未来早期行业/概念映射或实验特征。

必须满足：

- 与正式数据物理或逻辑隔离；
- 输出中明确 `experimental=true`；
- 不得被正式 baseline、正式因子或策略报告误认为已验证平台字段。

---

## 5. 第一版 Research Daily Panel

第一批实现目标是建立一个稳定的股票日频研究表和一个指数日频研究表。

### 5.1 `research_security_daily`

建议以 `trade_date + security_id` 为唯一研究粒度。

第一版至少提供：

#### 身份

- `trade_date`
- `security_id`
- `symbol`
- `exchange`

#### 原始日频研究字段

- `open`
- `high`
- `low`
- `close`
- `pre_close`（仅在来源可靠时）
- `volume`
- `amount`

#### 基础确定性衍生字段

优先复用 CR-5 已有公式/正式特征，不重复计算逻辑。第一版研究消费至少应方便取得：

- 1 日收益；
- 多周期滞后收益（例如 5/10/20/60 个交易日，具体正式注册以 CR-5 Registry 为准）；
- 日内收益；
- 开盘缺口；
- 振幅；
- 成交额相对近期均值；
- 收盘价相对近期均值；
- 可由现有可靠字段确定性计算的波动类指标。

这里的目标不是一次把所有因子做完，而是提供可以高效探索的基础积木。

#### 研究资格字段

必须有机器可读的研究资格信息，例如：

- `research_eligible`
- `research_exclusion_reason`
- `data_quality_state`
- `source_snapshot_id` / `readmodel_snapshot_id`
- `feature_run_id`（存在正式特征时）

字段命名可以按现有代码规范调整，但语义必须存在。

### 5.2 `research_index_daily`

至少包括：

- `trade_date`
- `index_id`
- OHLC
- volume / amount（来源存在且可靠时）
- 1 日与常用多周期收益
- 基础波动指标
- 对应 snapshot / lineage identity

指数数据主要用于：

- 个股相对强弱；
- 市场环境；
- beta/超额收益类研究；
- CR-6 市场状态输入。

---

## 6. 研究时间分区必须固化

平台必须给研究者明确的时间用途标签，而不是靠研究脚本自己记忆。

正式基线保持：

| 时间 | 用途 | 规则 |
|---|---|---|
| 2020-01-01 ～ 2023-12-31 | Development | 可以探索、提出规则、开发特征 |
| 2024-01-01 ～ 2025-12-31 | Validation A | 验证 Development 中形成的结论，不能反复追着结果调规则 |
| 2026-01-01 ～ 2026-06-30 | Holdout | 只用于最终独立检验，不得用于选择规则、阈值或特征 |
| 2020 前 | Warm-up / PIT only | 仅在计算窗口、状态初始化或 PIT 需要时使用，不是当前研究主样本 |

实现要求：

- Research Panel 或稳定 loader 必须能返回 `research_split`；
- 默认研究 API 必须支持显式选择 `development` / `validation_a` / `holdout`；
- 不允许一个模糊的默认参数把 Holdout 自动混入开发数据；
- Holdout 可以提前物化，但默认探索接口不得自动加载它；
- 测试必须覆盖分区边界日期。

---

## 7. 下游使用接口

CR-7 第一版必须提供一个稳定、简单的消费入口。

研究者不应该写：

```text
调用 AmazingData → 清洗 → 猜字段 → 拼 read model → 自己算正式特征
```

而应该能够表达类似：

```python
panel = load_research_security_daily(
    start="2020-01-01",
    end="2023-12-31",
    split="development",
)
```

或者使用项目最终确定的等价接口。

要求：

1. 下游不需要 Provider 凭证即可读取已经发布的研究数据；
2. 不需要理解 Provider SDK；
3. 不需要手工排除 unresolved 字段；
4. 默认只返回研究允许的数据；
5. 可以追溯到 snapshot / feature run；
6. 同一发布版本重复读取结果稳定；
7. 优先支持 Parquet + Python API，不强制引入数据库服务作为第一版前置条件。

---

## 8. 首批市场研究能力

CR-7 建成后的第一批研究重点围绕“从数据发现规律”，而不是围绕公告内容。

### 8.1 个股趋势与动量

支持研究：

- 5/10/20/60 日收益分层；
- 趋势持续时间；
- 趋势斜率与波动；
- 距离近期高点/低点；
- 放量/缩量条件下的趋势延续；
- 强趋势后的延续与反转概率。

### 8.2 量价关系

支持研究：

- 成交额放大倍数；
- 量价同步/背离；
- 高成交额突破；
- 放量上涨、放量下跌之后的条件收益；
- 流动性变化与信号稳定性。

### 8.3 横截面强弱

支持研究：

- 同日收益排名；
- 相对指数强弱；
- 不同波动/成交特征下的未来收益分布；
- 极端强弱分位的持续/反转。

### 8.4 市场宽度与市场状态

在不依赖未确认生命周期字段的前提下，先基于当日实际可观察股票集合研究：

- 上涨/下跌家数；
- 收益分布；
- 强势股比例；
- 新高/新低类统计（只在窗口数据完整时）；
- 成交额扩张/收缩；
- 指数趋势与全市场个股行为是否一致；
- CR-6 市场状态与策略表现的条件关系。

市场宽度必须记录当日有效样本数，不能把“缺数据”直接当作“未上涨/未创新高”。

### 8.5 行业/板块轮动

这是重要方向，但不是 CR-7 R1 的阻塞项。

只有行业/板块分类数据达到研究可用标准后再进入正式研究层。此前可以作为 `RESEARCH_EXPERIMENTAL` 独立推进，不得阻塞股票/指数主线。

---

## 9. 实施工作包

### R1 — Research Panel v1（下一步立即实施）

目标：让可靠的股票/指数日线真正能被研究仓库直接消费。

必须完成：

1. 定义机器可读的 research eligibility / exclusion contract；
2. 建立 `research_security_daily`；
3. 建立 `research_index_daily`；
4. 接入现有 Canonical/ReadModel 和 CR-5 Verified Feature Run；
5. 加入 research split；
6. 提供稳定 Python/Parquet 读取入口；
7. unresolved 数据默认排除但继续保存；
8. 完成 schema、确定性、分区、禁用字段、lineage 回归测试。

R1 **不要求**：

- 解决所有历史 ST/停牌异常；
- 解决所有退市 PIT；
- 完成全部公司行为语义；
- 激活 BSE 边界数据；
- 全市场行业/概念分类；
- 第三次 Formal Production；
- 策略参数优化。

### R2 — Research Feature / Market-State Export

目标：让 CR-5 / CR-6 的正式输出以研究友好方式与 R1 Panel 对齐。

包括：

- feature run 与 research panel 的 join contract；
- 市场宽度基础特征；
- 指数环境特征；
- market-state 输出；
- feature/state 版本绑定；
- 研究仓库读取示例与回归样本。

### R3 — Sector / Industry / Theme Research Layer

目标：补足板块轮动和扩散研究。

前提是分类数据自身达到可用标准。优先解决研究需要的最小分类集合，不追求一次覆盖所有主题标签。

### R4 — Research Feedback Loop

目标：让 `Quantitative-Strategy-Research` 的真实研究结果反向驱动数据平台。

以后新增数据需求必须回答：

> 哪个具体研究问题需要它？如果没有它，研究结论会受到什么影响？

只有能回答这个问题的数据债，才进入优先修复队列。

---

## 10. R1 验收标准

R1 只有同时满足以下条件才算完成。

### 10.1 数据正确性

- 股票/指数研究表只包含允许字段；
- `RESEARCH_DISABLED_UNRESOLVED` 不会从默认 loader 泄漏；
- 不对 unresolved 状态做隐式补值；
- 日期、symbol/security_id 主键无静默重复；
- OHLC 基本约束和数值字段基础校验通过；
- 缺失值有明确处理规则，不用 0 替代“未知”。

### 10.2 确定性

相同：

- source/readmodel snapshot；
- 代码版本；
- feature registry/version；
- 配置；

必须生成相同的研究输出内容哈希。

### 10.3 时间边界

- Development / Validation A / Holdout 标签正确；
- Holdout 不进入默认开发读取；
- 滚动窗口不得读取未来数据；
- PIT 适用的正式字段继续遵循已有 `available_at <= as_of` 约束。

### 10.4 可追溯性

每个已发布研究数据集至少能追溯：

- research dataset version；
- build code fingerprint / commit；
- source/readmodel snapshot；
- feature run（如适用）；
- schema version；
- output content hash；
- build timestamp。

### 10.5 下游可用性

在不调用 Provider 的环境中，`Quantitative-Strategy-Research` 必须能够：

1. 读取 Development 的任意日期区间；
2. 选择所需基础字段和正式特征；
3. 按股票/日期过滤；
4. 获取对应指数数据；
5. 明确知道数据版本；
6. 不需要自己处理 disabled/unresolved 字段。

### 10.6 性能

第一版不追求极端优化，但必须避免逐股票逐日 Provider 风格访问。

目标是研究者能够以列式批量方式读取一个完整研究区间；具体性能基线在 R1 实现 PR 中用本地可复现 benchmark 固定，不在本需求文档提前拍数字。

---

## 11. 明确暂缓的数据技术债

以下项目保留，但不再阻塞 R1/R2：

| 技术债 | 当前处理 | 何时重新打开 |
|---|---|---|
| 历史精确上市/退市 PIT | 保存，默认禁用 | 研究明确依赖历史可交易 universe 时 |
| 异常 ST/停牌行 | 保存/隔离 | 策略明确需要 ST/停牌过滤时 |
| 公司行为部分日期/进度语义 | 保存/隔离 | 需要严格复权、事件研究或跨除权连续性时 |
| BSE 历史代码边界 | 已知问题、按需处理 | BSE 纳入目标研究 universe 时 |
| 601558/600068 历史 fixture | deferred | 需要重新证明历史退市覆盖时 |
| CNINFO / 交易所公告检索自动化 | 不扩展 | 某个具体边界事实确实无法由主数据解决时 |

任何技术债重新打开时，应单独形成小任务，不得再次把整个研究平台冻结。

---

## 12. 不允许出现的实现方式

CR-7 明确禁止：

1. 为了让 Panel 看起来完整，猜测 unresolved 字段；
2. 在下游研究代码里直接访问 Provider 并形成第二套正式数据口径；
3. 复制 CR-5 的正式公式造成同名特征双实现；
4. 用 Holdout 结果选择阈值或特征；
5. 因一个边界字段 unresolved 而阻止所有可靠数据进入研究；
6. 再建设一套泛化 multi-provider 框架作为 R1 前置；
7. 把公告正文、新闻或文本内容直接当成 CR-7 的默认交易信号数据；
8. 为了通过测试而删除、隐藏或改写原始异常数据。

---

## 13. R1 推荐代码边界

具体目录由实现者结合现有结构确定，但原则上应是薄层，而不是新平台。

建议能力边界：

```text
src/ashare_state/research/
    eligibility.py      # research-enabled / disabled / experimental 判定
    panel.py            # security/index daily panel build
    splits.py           # Development / Validation A / Holdout
    models.py           # schema / manifest
    reader.py           # stable downstream read API
```

如果现有模块已有同等能力，应扩展现有模块，不为了目录整齐重复造轮子。

Research Layer 可以引用 CR-5 的 verified feature artifacts，但不得反向修改 feature artifact。

---

## 14. R1 实现 PR 的最小交付物

下一张实现 PR 应至少包含：

- research eligibility machine contract；
- R1 schema/version；
- security daily panel builder；
- index daily panel builder；
- research split implementation；
- stable reader；
- immutable/versioned manifest；
- unit tests；
- 至少一个小规模固定 fixture/integration test，证明从已验证输入 → research panel → reader 全链路可复现；
- 对 disabled unresolved 数据“不进入默认研究输出”的回归测试；
- 文档中的最小下游使用示例。

第一张实现 PR **不做全历史大规模回填**。先证明接口、口径、确定性和研究可用性，再单独安排历史物化。

---

## 15. 后续调度顺序

本需求文档通过审阅并合并后，按以下顺序推进：

1. **R1 contract + small-fixture implementation**；
2. R1 独立审阅/CI；
3. 小范围 research dataset build，验证真实研究消费；
4. 再决定 2020–2026H1 的历史物化方式；
5. R2 Feature/Market-State export；
6. 将稳定数据接口交给 `Quantitative-Strategy-Research`；
7. 用真实研究问题驱动 R3 和暂缓数据技术债。

在这条主线上，source-contract/公告语义不再作为主动扩展方向。

---

## 16. CR-7 完成定义

CR-7 整体完成，不意味着所有 A 股数据问题都解决，而意味着：

> 我们已经拥有一个稳定、确定、默认安全的日频研究数据入口；研究者可以围绕趋势、动量、反转、量价、横截面和市场状态持续探索规律；平台知道哪些数据可以用、哪些暂时不能用，并且未解决的边界问题不会再无条件阻塞研究主线。

这就是下一阶段判断工作的核心标准。
