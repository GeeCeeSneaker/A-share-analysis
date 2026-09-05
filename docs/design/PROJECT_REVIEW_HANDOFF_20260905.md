# 项目全面审阅意见与管理交接 — 2026-09-05

## 1. 文档性质与证据边界

- 审阅基线：`73e337b350708e47873ffb54a1086aa48ad076e7`（提交前再次确认 main 未移动）。
- 授权范围：将本轮审阅意见提交仓库，供项目管理者接手。本次只提交文档，不实施代码修复、不修改生产配置、不执行线上账号验证、不合并 PR。
- 仓库访问方式：仅 GitHub 连接器。
- Implementation Status：REVIEW_DOCUMENTED / REMEDIATION_NOT_IMPLEMENTED。
- Review Status：PENDING_OWNER_REVIEW。本文不是 Owner 已批准的实施计划，也不替代现有设计裁决。
- 方法：核心处理链、相关测试、CI、运维及治理文档的静态检查；对部分纯函数进行本地、无账号、无 SDK 网络连接的合成输入探测。
- 限制：不是逐行覆盖全部仓库的形式化审计；未重跑完整测试矩阵、真实 SDK 链路、历史全量压测或灾难恢复演练。既有 CI 结果不冒充本次新证据。
- 安全：本文不包含真实账号、密码、Token、连接端点、原始 SDK 输出或专有 SDK 文件。

**总体判断（审阅意见）**：项目在不可变证据、内容校验及失败时拒绝继续方面已有基础，但生产验证、恢复操作与历史研究语义尚未形成完整闭环。“PR 已合并”“代码测试通过”“真实服务可用”必须分别记录。

## 2. 待分派事项总览

优先级是本轮建议，待 Owner 确认；不表示已经发现真实泄露、数据丢失或生产故障。所有事项当前均为 OPEN / UNASSIGNED。

| ID | 建议优先级 | 事项 | 证据类型 | 建议负责方向 |
|---|---|---|---|---|
| REV-01 | P1 | 身份预检运行时与权限判定不一致 | 静态确认 + 合成输入复现 | Provider / bootstrap |
| REV-02 | P1 | 脱敏和诊断输出保护不完整 | 合成输入复现 + 条件性风险路径 | Provider / 安全输出 |
| REV-03 | P1 | 孤儿文件识别未覆盖后续产物登记体系 | 静态确认；误报取决于目录布局 | Storage / recovery |
| REV-04 | P2 | CI 成功与平台验收含义不一致 | 配置事实；不是当前 CI 失败报告 | CI / 项目治理 |
| REV-05 | P1（历史研究前） | 历史采集与历史时点可用性语义不一致 | 实现与运维文档对照 | 数据契约 / 研究 |
| REV-06 | P1（无人值守前） | 原生 SDK 调用没有硬截止机制 | 实现明确的能力限制 | Provider / 运行可靠性 |
| REV-07 | P2 | 全量读取与重复处理的规模风险 | 静态风险；尚无性能结论 | 数据处理 / 性能 |
| REV-08 | P2 | 严格指纹缺少配套升级与重放策略 | 指纹与验证逻辑事实；兼容性设计风险 | 构建 / 版本治理 |

## 3. 详细发现与验收建议

### REV-01 — 身份预检状态可能与底层证据矛盾

**已确认**

- `_offline_safe_report` 仅根据 `sdk_state == SDK_INSTALLED` 输出 `OFFLINE_RUNTIME_VERIFIED`，没有要求运行时 verdict 通过。
- 在线 `_safe_report` 输出 `runtime_verdict`，但候选状态分支没有使用它作为门禁。
- `_safe_permission_codes` 允许数字与分隔符组成的非空字符串；只有分隔符也能通过。随后 `bool(permission_codes)` 被用作权限验证条件。

**合成输入复现摘要**

其余候选条件满足、冻结身份查询为无冻结配置的前提下：

| 输入变化 | 当前输出 | 问题 |
|---|---|---|
| SDK_INSTALLED + RUNTIME_PATH_AMBIGUOUS，在线认证和查询均 YES | runtime_verdict=NOT_VERIFIED；bootstrap_status=IDENTITY_CANDIDATE | 候选状态没有表达未通过的运行时证据 |
| SDK_INSTALLED + RUNTIME_PATH_AMBIGUOUS，offline=True | runtime_verdict=NOT_VERIFIED；bootstrap_status=OFFLINE_RUNTIME_VERIFIED | 离线结论自相矛盾 |
| 合法的测试用生成身份，permission_codes 只有 `|||`，其余条件满足 | entitlement_verified=true；bootstrap_status=IDENTITY_CANDIDATE | 没有真实代码项也视为有效权限 |

这些是纯函数合成输入结果，不是正式账号返回数据；没有证明当前真实 doctor 一定产生上述组合。

**建议**

由 Owner 明确各阶段允许的 runtime verdict；状态机据此统一判定。将权限字段解析为非空数字代码集合，再验证语义。身份解析、权限代码存在与数据能力批准继续分开。

**验收**

- [ ] runtime 未验证或歧义时不再输出与证据矛盾的 VERIFIED / 可交付候选状态。
- [ ] 空串、空白、纯分隔符、混合非法字符均不作为有效权限证据。
- [ ] 保留正常候选、Trial 拒绝、冻结身份人工审阅及非零退出回归。
- [ ] 将上述合成场景固化为仓库测试，并记录实际测试结果。

来源：[scripts/spike/production_account_bootstrap.py:88](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/scripts/spike/production_account_bootstrap.py#L88)。

### REV-02 — 脱敏保护没有覆盖全部结构与入口

**已确认**

- `scrub_dict` 递归处理字典，不处理列表内部的字典；合成结构 `{"items": [{"Token": "SYNTHETIC_AUDIT_SENTINEL"}]}` 中该测试字符串仍被保留。
- session 的部分登录异常携带原异常文本；doctor 将异常字符串截取后放入 `auth_error`；普通 `provider-doctor` 直接输出/保存报告。
- SDK stdout/stderr 捕获使用临时文件。它们不是提交到 Git 的日志，但“原始文本从不持久化”不能被理解为绝不进入临时磁盘介质。

**风险边界**

没有发现或验证真实凭证泄露。风险在于 SDK 异常或非预期嵌套结构包含敏感值时，现有保护不足。bootstrap 的安全投影不能自动覆盖其他 CLI 入口；截断异常不是脱敏。

**建议与验收**

- [ ] 统一 bootstrap、doctor、CLI、生命周期错误的安全输出边界。
- [ ] 递归处理列表/字典组合；日志测试使用纯合成 sentinel。
- [ ] stdout、stderr、异常报告和输出文件均不能出现测试敏感值。
- [ ] 明确临时文件的权限、清理和落盘威胁模型；如要求原文不落盘，选择适当的受控捕获实现并验证不会阻塞。
- [ ] 不把本发现描述成已发生安全事件，也不把真实账号内容放进回归样本。

来源：[src/ashare_state/providers/amazingdata/stdout_capture.py:48](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/providers/amazingdata/stdout_capture.py#L48)；[src/ashare_state/providers/amazingdata/session.py:189](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/providers/amazingdata/session.py#L189)；[src/ashare_state/providers/amazingdata/doctor.py:237](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/providers/amazingdata/doctor.py#L237)；[src/ashare_state/cli.py:106](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/cli.py#L106)。

### REV-03 — 孤儿识别与后续登记体系不匹配

**已确认**

`find_orphan_files` 扫描 `data_root` 下全部 Parquet，却仅查询 `meta_feature_artifact_component` 与 `meta_data_snapshot_component`。后续 normalization / snapshot / feature / state 模块还通过独立运行登记表及 manifest 管理产物。

当这些产物目录位于被扫描根目录下、但文件不在上述两张表时，合法文件会被报告为 orphan。检查器只报告、不删除；恢复文档却指导确认后人工删除，存在误操作风险。

**建议与验收**

- [ ] 从所有受支持登记表和 manifest 建立完整的文件引用关系；统一路径根与 URI 规则。
- [ ] 已被任一有效 manifest 引用的合法文件不得成为可清理孤儿。
- [ ] 未知版本、损坏 manifest、正在写入的文件和无法确认归属的路径默认保护。
- [ ] 增加 dry-run、隔离区、宽限期及审计记录，不直接把“旧表中不存在”解释为可删除。
- [ ] 用 normalization / snapshot / feature / state 合法产物及真正孤儿补充回归测试。
- [ ] 把恢复文档中的占位命令替换为可执行且经演练的操作说明。

来源：[src/ashare_state/pipeline/publish.py:781](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/pipeline/publish.py#L781)；[migrations/014_provider_normalization.sql](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/migrations/014_provider_normalization.sql)；[src/ashare_state/snapshot/builder.py](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/snapshot/builder.py)；[src/ashare_state/features/builder.py](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/features/builder.py)；[src/ashare_state/state/builder.py](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/state/builder.py)；[docs/runbook/publish_recovery.md:7](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/docs/runbook/publish_recovery.md#L7)。

### REV-04 — CI 绿灯不是三平台全部通过，更不是生产验证

**已确认**

Windows/Python 3.12 与 Ubuntu/Python 3.14 配置 `required: false`，job 使用 `continue-on-error`。CI 明确不安装真实 SDK、没有真实账号凭证。

因此必须区分工作流总体成功、每腿成功、SDK 真实验证。这里不是说已有成功记录造假或当前矩阵失败。

**建议与验收**

- [ ] Owner 统一现行文档的三平台验收要求与实际阻断配置；若某平台是建议项，应明确标注。
- [ ] 故意失败的必需矩阵能够阻断交付；建议矩阵失败不得被汇总成“全部通过”。
- [ ] 状态报告分别列出静态检查、各平台测试、受控本地 SDK 验证。
- [ ] 可另行评估取消过期 CI、减少重复流水线；不能以提速为由绕过门禁。
- [ ] 保持公共 CI 无生产凭证、无专有 SDK 的边界。

来源：[.github/workflows/ci.yml:9](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/.github/workflows/ci.yml#L9)。

### REV-05 — 历史数据与历史时点可知数据需要分开建模

**已确认**

当前五类域的 availability 均为 `OBSERVED_AT_INGEST`，`derive_available_at` 返回 `received_at`。今天采集的历史记录不能据此作为过去某时点已经可用的记录。

旧回填 runbook 仍描述 `CONSERVATIVE_ASSUMED` 规则，并保留 2014/2015 起始范围；需要与现行 2020+ 要求及实现对齐。

**判断**

采用采集时点是保守策略，不是应该直接删除的限制。问题是研究用途与文档承诺不清，可能使“历史回填完成”被误解为“无前视偏差回测数据已就绪”。

**建议与验收**

- [ ] 明确交易/生效时间、实际采集时间、来源发布时间及假设可用时间的区别。
- [ ] 如新增历史研究视图，采用版本化可用性规则并披露假设；不得覆写真实采集时间冒充历史已知。
- [ ] 同一历史交易日记录在“采集前/采集后”的 as-of 查询符合已批准语义。
- [ ] 回填范围、当前 runbook、配置说明和测试一致。
- [ ] 历史研究验收单独检查可用性假设，不仅检查行数和日期覆盖。

来源：[src/ashare_state/canonical/availability.py:66](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/canonical/availability.py#L66)；[docs/runbook/run_backfill.md:19](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/docs/runbook/run_backfill.md#L19)；[configs/base.yaml](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/configs/base.yaml)；[docs/design/A-share-analysis_星耀数智正式验证历史边界调整_2020Plus_20260904.md](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/docs/design/A-share-analysis_星耀数智正式验证历史边界调整_2020Plus_20260904.md)。

### REV-06 — 重试预算不能终止不返回的原生调用

**已确认**

`run_with_budget` 同步执行 `fn()`，在异常返回后检查预算；源码明确声明这不是硬超时。若原生 SDK 一直不返回，这一层不能终止它。

**建议与验收**

- [ ] 无人值守前建立受控子进程或等效隔离机制，外部截止时间到达后可可靠停止。
- [ ] 登录卡死、查询卡死、子进程异常退出均有合成测试与必要的受控现场验证。
- [ ] 超时后留下明确失败状态，不出现半发布、永久占锁或无限增长的孤立进程。
- [ ] 对重试使用幂等边界和总预算；清理过程不输出敏感原文。
- [ ] 文档继续准确使用“重试预算”，不要提前宣称硬超时已完成。

来源：[src/ashare_state/providers/amazingdata/timeout.py:1](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/providers/amazingdata/timeout.py#L1)。

### REV-07 — 全量读取与重复验证需要规模证据

**已确认的代码路径**

Canonical 查询对应数据面的全部成功归一化运行；Feature 从 `rm_daily_bar` 全量 `fetchall()` 后转换为 Python 字典列表。部分物化路径还会同时经历文件字节、DataFrame 和 Python 行对象。

**未验证**

没有此次全历史压测结果，不能断言具体内存峰值、耗时、吞吐量或必然 OOM。

**建议与验收**

- [ ] 按现行允许范围分阶段扩展股票数、历史长度和重复运行次数。
- [ ] 记录峰值内存、总耗时、读取字节、增量重跑成本与测试环境。
- [ ] Owner 先定义可接受资源上限与完成时限，再判断是否达标。
- [ ] 按证据选择分区裁剪、流式批处理、增量运行索引与校验缓存。
- [ ] 性能优化前后产物语义、完整性校验和 PIT 结果保持一致；不直接跳过校验。

来源：[src/ashare_state/canonical/canonicalizer.py:2033](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/canonical/canonicalizer.py#L2033)；[src/ashare_state/features/builder.py:198](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/features/builder.py#L198)。

### REV-08 — 严格代码指纹应配套历史版本重放方案

**已确认**

Feature 指纹覆盖多个模块的完整源码（只规范化换行）；注释修改也会改变指纹。验证器要求产物指纹与当前代码一致。

**判断**

这是严格失败关闭策略，不是应无条件放宽的缺陷。但新版不能直接接受旧版产物时，必须有明确的历史环境恢复、兼容性裁决或重建路径。

**建议与验收**

- [ ] 保存产物对应源码提交、依赖锁定及运行环境引用，不包含秘密。
- [ ] 分开管理数据契约版本、算法语义版本、构建源码指纹与兼容性规则。
- [ ] 用旧产物验证“旧环境可重放”“新环境明确拒绝或经批准兼容”“必要时受控重建”。
- [ ] 语义变更与非语义变更均有升级测试。
- [ ] 不通过删除 fingerprint 检查或忽略 hash mismatch 来解决兼容性问题。

来源：[src/ashare_state/features/builder.py:79](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/features/builder.py#L79)；[src/ashare_state/features/verifier.py:369](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/features/verifier.py#L369)；[src/ashare_state/snapshot/verifier.py](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/snapshot/verifier.py)；[src/ashare_state/state/verifier.py](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/src/ashare_state/state/verifier.py)。

## 4. 管理接手与现行任务衔接

基线文档明确：PR #10 合并的是 blocked-preflight 记录，T1 线上验证尚未完成；重复提交相同状态的预检文档没有新增审阅价值。本文是用户要求的新审阅发现交接，不是新的 T1 完成证据。

现行顺序仍然是受控 T1 → 人工 T2 → 单独 T3 配置冻结，再按治理要求进入后续正式能力验证。本文不批准提前开展历史回填，不把身份候选等同于 Provider capability approval。

来源：[docs/design/A-share-analysis_PR10审查结论与T1线上身份候选执行要求_20260905.md:20](https://github.com/GeeCeeSneaker/A-share-analysis/blob/73e337b350708e47873ffb54a1086aa48ad076e7/docs/design/A-share-analysis_PR10审查结论与T1线上身份候选执行要求_20260905.md#L20)。

接手建议：

1. Owner 对 REV-01 至 REV-08 逐项确认优先级、范围、负责人和目标里程碑；本文不替管理者虚构负责人或截止日期。
2. 优先收敛身份判定、安全输出和恢复误报；由 Owner 决定哪些是下一次受控测试的前置修复。
3. 对真实运行记录分别列出代码 SHA、运行环境、实际执行步骤、脱敏结果和未执行项。缺少本地配置载体与缺少授权应分别判断；不得仅因没有配置文件就推断没有授权。
4. 在运行前核对受控副本与目标源码提交，不能把旧副本的结果写成 clean-main 验证。
5. 建立一个简短的当前状态入口，链接历史裁决与本文；历史文档保留，不继续散落相互矛盾的“已完成”状态。
6. 继续遵守单一授权写入身份治理，不要求新增 GitHub 账号或形式上的自我批准。

## 5. 关闭记录模板

每个 REV 事项单独记录：

- ID / Owner 确认后的优先级 / 负责人 / 目标里程碑。
- Implementation Status 与 Review Status，禁止把 DOCUMENTED 当成 FIXED。
- 实施 PR、代码提交 SHA、测试命令或 Actions 链接、实际结果。
- 合成测试 / 真实 SDK 验证 / 规模压测 / 人工确认各自适用与否。
- 未完成的验收项、具体原因、下一步动作；如延期或不采纳，记录 Owner 决策与风险接受理由。
- 只有验收证据齐备并经现行治理确认后才 CLOSED。

本次交付范围：审阅意见文档及 DEVLOG 交接记录。代码、配置、SDK、真实账号状态和以上整改事项均未因本次提交而改变。
