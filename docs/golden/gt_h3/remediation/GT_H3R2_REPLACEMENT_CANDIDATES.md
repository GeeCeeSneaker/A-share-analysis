# GT-H3R2 ST_TRANSITION 替换候选池（草案）

> 状态：**DRAFT / NOT CANONICAL / NOT INDEPENDENTLY REVIEWED / v5 IMMUTABLE / v6 NOT PUBLISHED**

## 1. 目的与边界

本文件为当前 15 条 `INVALID_ST_LEVEL_CHANGE` 准备的真实替换候选池。它不是 Golden 数据、不是独立复核结论，也不把原有无效条目改判为通过；在独立 Reviewer closure 前，不得据此生成 v6、写入 `REVIEWED` provenance 或解除 GT-H3B。

候选必须满足：同一官方一手原文明确给出代码、有效日、有效日前的普通简称，以及有效日后带 `*ST` 的简称；语义为 `false -> true`。本轮 15 份直链均以 HTTP 200 返回 PDF，并完成全文提取；表内只保存官方 URL 和复核定位，原始 bytes 不上传 GitHub。

CNINFO 查询接口只用于发现材料，不能作为证据；本表证据边界是下列 `static.cninfo.com.cn/finalpage/...PDF` 直链原文。当前 `reviewer_status` 统一为 `PENDING_INDEPENDENT_REVIEW`，开发者读取不等于独立 Reviewer 批准。

## 2. 15 条替换候选

| # | 候选案例 ID | provider_symbol | subtype | effective date | 原文证明的简称变化 | 官方原文（HTTP 200，全文已读） | Reviewer decision | Reviewer | Reviewed at | One-line feedback |
| ---: | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| 1 | `GT-H2-ST-ST_ADD-300495-20210507` | `300495.SZ` | `ST_ADD` | `20210507` | 美尚生态 → *ST美尚 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209893133.PDF)；p.1：证券代码 300495；公告同时写明 2021-05-07 起实施退市风险警示，简称由“美尚生态”变更为“*ST美尚”。 |  |  |  |  |  |
| 2 | `GT-H2-ST-ST_ADD-002640-20210507` | `002640.SZ` | `ST_ADD` | `20210507` | 跨境通 → *ST跨境 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209892047.PDF)；p.1：证券代码 002640；公告同时写明 2021-05-07 起实施退市及其他风险警示，简称由“跨境通”变更为“*ST跨境”。 |  |  |  |  |  |
| 3 | `GT-H2-ST-ST_ADD-600382-20210506` | `600382.SH` | `ST_ADD` | `20210506` | 广东明珠 → *ST明珠 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209878423.PDF)；p.1：证券代码 600382；公告写明退市风险警示起始日 2021-05-06，简称由“广东明珠”变更为“*ST明珠”。 |  |  |  |  |  |
| 4 | `GT-H2-ST-ST_ADD-600291-20210506` | `600291.SH` | `ST_ADD` | `20210506` | 西水股份 → *ST西水 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209878259.PDF)；p.1：证券代码 600291；公告写明退市风险警示起始日 2021-05-06，简称由“西水股份”变更为“*ST西水”。 |  |  |  |  |  |
| 5 | `GT-H2-ST-ST_ADD-600078-20210506` | `600078.SH` | `ST_ADD` | `20210506` | 澄星股份 → *ST澄星 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209877776.PDF)；p.1：证券代码 600078；公告写明退市风险警示起始日 2021-05-06，简称由“澄星股份”变更为“*ST澄星”。 |  |  |  |  |  |
| 6 | `GT-H2-ST-ST_ADD-600896-20210506` | `600896.SH` | `ST_ADD` | `20210506` | 览海医疗 → *ST海医 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209875156.PDF)；p.1：证券代码 600896；公告写明退市风险警示起始日 2021-05-06，简称由“览海医疗”变更为“*ST海医”。 |  |  |  |  |  |
| 7 | `GT-H2-ST-ST_ADD-600615-20210506` | `600615.SH` | `ST_ADD` | `20210506` | 丰华股份 → *ST丰华 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209874374.PDF)；p.1：证券代码 600615；公告写明退市风险警示起始日 2021-05-06，简称由“丰华股份”变更为“*ST丰华”。 |  |  |  |  |  |
| 8 | `GT-H2-ST-ST_ADD-000502-20210506` | `000502.SZ` | `ST_ADD` | `20210506` | 绿景控股 → *ST绿景 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209872529.PDF)；p.1：证券代码 000502；公告写明 2021-05-06 起实施退市风险警示，简称由“绿景控股”变更为“*ST绿景”。 |  |  |  |  |  |
| 9 | `GT-H2-ST-STAR_ST_ADD-688086-20220506` | `688086.SH` | `STAR_ST_ADD` | `20220506` | 紫晶存储 → *ST紫晶 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213274157.PDF)；p.1：证券代码 688086；公告列明简称由“紫晶存储”变更为“*ST紫晶”，实施退市风险警示起始日为 2022-05-06。 |  |  |  |  |  |
| 10 | `GT-H2-ST-ST_ADD-603603-20220506` | `603603.SH` | `ST_ADD` | `20220506` | 博天环境 → *ST博天 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213274090.PDF)；p.1：证券代码 603603；公告写明 2022-05-06 起实施风险警示，简称由“博天环境”变更为“*ST博天”。 |  |  |  |  |  |
| 11 | `GT-H2-ST-ST_ADD-002313-20220506` | `002313.SZ` | `ST_ADD` | `20220506` | 日海智能 → *ST日海 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213267451.PDF)；p.1：证券代码 002313；公告写明 2022-05-06 起实施退市及其他风险警示，简称由“日海智能”变更为“*ST日海”。 |  |  |  |  |  |
| 12 | `GT-H2-ST-ST_ADD-300301-20220506` | `300301.SZ` | `ST_ADD` | `20220506` | 长方集团 → *ST长方 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213267090.PDF)；p.1：证券代码 300301；公告写明 2022-05-06 起实施退市及其他风险警示，简称由“长方集团”变更为“*ST长方”。 |  |  |  |  |  |
| 13 | `GT-H2-ST-ST_ADD-002751-20220506` | `002751.SZ` | `ST_ADD` | `20220506` | 易尚展示 → *ST易尚 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213266378.PDF)；p.1：证券代码 002751；公告写明 2022-05-06 起实施退市及其他风险警示，简称由“易尚展示”变更为“*ST易尚”。 |  |  |  |  |  |
| 14 | `GT-H2-ST-ST_ADD-002316-20220506` | `002316.SZ` | `ST_ADD` | `20220506` | 亚联发展 → *ST亚联 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213265483.PDF)；p.1：证券代码 002316；公告写明 2022-05-06 起实施退市及其他风险警示，简称由“亚联发展”变更为“*ST亚联”。 |  |  |  |  |  |
| 15 | `GT-H2-ST-ST_ADD-002366-20220506` | `002366.SZ` | `ST_ADD` | `20220506` | 台海核电 → *ST海核 | [CNINFO official PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213263830.PDF)；p.1：证券代码 002366；公告写明 2022-05-06 起实施退市及其他风险警示，简称由“台海核电”变更为“*ST海核”。 |  |  |  |  |  |

右侧四列由独立 Reviewer 填写；开发者不预填裁决。共同预期：`pre_effective_is_st=false`、`effective_is_st=true`、`transition_valid=true`。688086 使用 `STAR_ST_ADD`，其余使用 `ST_ADD`。候选案例 ID、代码和有效日均未与当前 v5 50 条 ST_TRANSITION 重复；最终仍须由 Reviewer 复核后再写入 v6 行。

## 3. 当前必须移出的 15 条无效源行

下列源行目前均为 `pre=true, effective=true`，不能通过补证改成二元加帽事件：

- `GT-H2-ST-ST_ADD-600654-20220506`
- `GT-H2-ST-ST_ADD-300064-20210428`
- `GT-H2-ST-ST_ADD-002113-20200429`
- `GT-H2-ST-ST_ADD-000806-20220506`
- `GT-H2-ST-ST_ADD-002781-20220506`
- `GT-H2-ST-ST_ADD-000606-20220506`
- `GT-H2-ST-ST_ADD-000410-20220419`
- `GT-H2-ST-ST_ADD-000616-20230504`
- `GT-H2-ST-ST_ADD-002433-20230505`
- `GT-H2-ST-ST_ADD-002086-20230505`
- `GT-H2-ST-ST_ADD-300108-20240430`
- `GT-H2-ST-ST_ADD-300209-20240429`
- `GT-H2-ST-ST_ADD-300167-20240430`
- `GT-H2-ST-ST_ADD-000525-20240919`
- `GT-H2-ST-ST_ADD-300506-20240429`

这是“删除旧源行 + 新增真实候选”的候选池，不是旧 ID 到新 ID 的语义映射；逐项 DROP/ADD 或 REPLACE 操作必须在 Reviewer closure 后另行编制并保留 lineage。

## 4. 独立 Reviewer 逐案反馈要求

Reviewer 请对每一行实际打开直链 PDF 原文，至少确认：

1. HTTP 200、确为官方 PDF，并读取包含事件字段的全文，而不是搜索摘要或接口返回；
2. 代码与候选 ID/provider_symbol 一致；
3. 原文同时出现有效日前普通简称与有效日后 `*ST` 简称，且有效日明确；
4. `ST_ADD/STAR_ST_ADD` 的二元方向确为 `false -> true`，不是 ST→*ST 或其他风险层级变化；
5. 案例不与 v5 现有 ST_TRANSITION 身份重复。

反馈只填写：`APPROVE`、`REJECT` 或 `NEED_MORE_EVIDENCE`，并附一句原文定位；不能用“开发者已核过”替代独立复核。任一候选被 REJECT/NEED_MORE_EVIDENCE，都不能进入清洁 v6。

## 5. Reviewer closure 后的开发顺序

- 保持 v5 文件、v4/v5 hash、既有 113 carry-forward 结论不变；不把 v5 审计台账回写 Golden。
- 依据 Reviewer 结果，把无效 15 行做真实 DROP/REPLACE，并从通过的候选池补足真实 ST_TRANSITION；不得降低“至少 50”配额，也不得把层级变化重新计入。
- 生成带 source lineage 的 v6 candidate 后，重新验证 125 总量、50 条 ST_TRANSITION、38 ADD/12 REMOVE、身份唯一性、其他事件语义和版本迁移关系；v6 的 carry-forward 数量须重新计算，不能沿用 113 的 v4→v5 结论。
- 只有清洁 v6 与独立 Reviewer closure 均完成，才允许按仓库文档决定是否进入 `review.py`、GT-H3B、Data Sufficiency 和后续发布门。

## 6. 本轮结论

候选池已具备下一轮独立复核所需的 15 份官方原文入口，但当前项目仍为 **PUBLICATION BLOCKED / PENDING REVIEW**。本文件本身不改变 50 行审计台账的 35 PASS / 15 INVALID 统计。
