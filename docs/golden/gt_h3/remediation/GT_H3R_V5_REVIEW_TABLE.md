# GT-H3R v5 12 条人工复审表

> 本表只复审 v5 整改后的 12 条案例。v4 的 113 条 APPROVE 不在本表重复审阅，
> 但必须由 carry-forward ledger 证明语义身份未变。机器封印仍需等待完整授权。

## 使用方法

1. 先打开每行“制度规则材料/主官方材料”和“案例适用性材料”列中的全部官方原文；不使用搜索摘要、接口输出或 AI 总结代替原文。
2. 复合事实的 5 条案例（AG-025 两条、AG-027 一条、AG-029 两条）必须同时核对规则材料和案例适用性材料；任一材料缺失或不支持精确事实即 REJECT。
3. 对照“必须核对”列检查代码、日期、事件、适用板块/规则和期望值。
4. 全部一致填 `APPROVE`；任一不一致、链接失效或原文不证明该事实，填 `REJECT` 并写一句原因。
5. 12 行完成后，真实 Owner/Human Reviewer 需在 PR 评论明确 12/12 结论、113 条沿用确认、
   `50` 已被中和或有明确含义，并给出 human marker。

## 变更范围

- v4 文件保持不可变；v5 仍为 125 条 `COMPILED` 案例。
- AG-054、AG-025、AG-029、AG-064 共 10 条只替换官方来源定位。
- AG-027、AG-096 共 2 条按裁决修正事实并重新编号。
- 本表的结果、反馈、审阅人和日期保持空白，不能直接写入 `REVIEWED`。
- 来源契约见 `GT_H3R_V5_SUPPORTING_OFFICIAL_SOURCES.jsonl`；其中 `evidence_status` 仅表示候选来源已声明，未表示事实已被 Human 证明。

| 序号 | 原案例 ID | v5 案例 ID | 分组 | 变更类型 | 事件类型 | 证券代码 | 交易日 | 制度规则材料/主官方材料 | 案例适用性材料（复合事实必填） | 必须核对 | 结果 | 简短反馈 | 审阅人 | 审阅日期 |
|---:|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | GT-LIMIT-ST5-600518-20190603 | GT-LIMIT-ST5-600518-20190603 | AG-025 | 仅换证据 | 涨跌停制度 | 600518.SH | 2019-06-03 | [SSE Risk-Warning Board Trading Measures (5% price-limit clause)](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml) | [SSE market disclosure naming 600518 as ST康美 (2019-05-31)](https://www.sse.com.cn/market/sseindex/diclosure/c/c_20190531_4830732.shtml) | 核对 600518.SH 在 2019-06-03 是否适用该交易所/板块规则；原文应支持：涨幅上限 5%；跌幅上限 5%。 |  |  |  |  |
| 2 | GT-LIMIT-ST5-600518-20191028 | GT-LIMIT-ST5-600518-20191028 | AG-025 | 仅换证据 | 涨跌停制度 | 600518.SH | 2019-10-28 | [SSE Risk-Warning Board Trading Measures (5% price-limit clause)](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml) | [SSE 600518 retrospective disclosure (ST status from 2019-05-21)](https://www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2021-11-27/600518_20211127_2_wfwElR2q.pdf) | 核对 600518.SH 在 2019-10-28 是否适用该交易所/板块规则；原文应支持：涨幅上限 5%；跌幅上限 5%。 |  |  |  |  |
| 3 | GT-LIMIT-CN20-300750 | GT-LIMIT-CN20-300750 | AG-054 | 仅换证据 | 涨跌停制度 | 300750.SZ | 2021-06-01 | [SZSE ChiNext Trading Special Provisions (20% clause)](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf) | —（本行非复合事实） | 核对 300750.SZ 在 2021-06-01 是否适用该交易所/板块规则；原文应支持：涨幅上限 20%；跌幅上限 20%。 |  |  |  |  |
| 4 | GT-LIMIT-CN20-300059 | GT-LIMIT-CN20-300059 | AG-054 | 仅换证据 | 涨跌停制度 | 300059.SZ | 2021-06-01 | [SZSE ChiNext Trading Special Provisions (20% clause)](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf) | —（本行非复合事实） | 核对 300059.SZ 在 2021-06-01 是否适用该交易所/板块规则；原文应支持：涨幅上限 20%；跌幅上限 20%。 |  |  |  |  |
| 5 | GT-LIMIT-CN20-300015 | GT-LIMIT-CN20-300015 | AG-054 | 仅换证据 | 涨跌停制度 | 300015.SZ | 2021-06-01 | [SZSE ChiNext Trading Special Provisions (20% clause)](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf) | —（本行非复合事实） | 核对 300015.SZ 在 2021-06-01 是否适用该交易所/板块规则；原文应支持：涨幅上限 20%；跌幅上限 20%。 |  |  |  |  |
| 6 | GT-LIMIT-CN20-300124 | GT-LIMIT-CN20-300124 | AG-054 | 仅换证据 | 涨跌停制度 | 300124.SZ | 2021-06-01 | [SZSE ChiNext Trading Special Provisions (20% clause)](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf) | —（本行非复合事实） | 核对 300124.SZ 在 2021-06-01 是否适用该交易所/板块规则；原文应支持：涨幅上限 20%；跌幅上限 20%。 |  |  |  |  |
| 7 | GT-LIMIT-CN20-300274 | GT-LIMIT-CN20-300274 | AG-054 | 仅换证据 | 涨跌停制度 | 300274.SZ | 2021-06-01 | [SZSE ChiNext Trading Special Provisions (20% clause)](https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf) | —（本行非复合事实） | 核对 300274.SZ 在 2021-06-01 是否适用该交易所/板块规则；原文应支持：涨幅上限 20%；跌幅上限 20%。 |  |  |  |  |
| 8 | GT-LIMIT-STARNO-20200723 | GT-LIMIT-STAR20-688981-20200723 | AG-027 | 事实修正 | 涨跌停制度 | 688981.SH | 2020-07-23 | [SSE STAR Market Trading Special Provisions (20% after first five days)](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf) | [SSE STAR listing notice for 688981 (listed 2020-07-16)](https://star.sse.com.cn/disclosure/listedinfo/bulletin/star/c/688981_20200715_1.pdf) | 核对 688981.SH 在 2020-07-23 是否适用该交易所/板块规则；原文应支持：涨幅上限 20%。 |  |  |  |  |
| 9 | GT-LIMIT-IPO44-601995 | GT-LIMIT-IPO44-601995 | AG-029 | 仅换证据 | 上市初期涨跌幅 | 601995.SH | 2020-11-02 | [SSE 2014 new-listing trading supervision notice (44%/36% bounds)](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml) | [SSE official retrospective disclosure for 601995 listing](https://static.sse.com.cn/disclosure/bond/announcement/company/c/new/2023-04-04/175906_20230404_LS9E.pdf) | 核对官方原文是否同时证明代码 601995.SH、交易日 2020-11-02 和期望值：涨幅上限 44%；跌幅上限 36%。 |  |  |  |  |
| 10 | GT-LIMIT-IPO44-605499 | GT-LIMIT-IPO44-605499 | AG-029 | 仅换证据 | 上市初期涨跌幅 | 605499.SH | 2021-05-27 | [SSE 2014 new-listing trading supervision notice (44%/36% bounds)](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml) | [SSE listing announcement for 605499](https://www.sse.com.cn/disclosure/announcement/listing/ipo/c/c_20210526_81718214.shtml) | 核对官方原文是否同时证明代码 605499.SH、交易日 2021-05-27 和期望值：涨幅上限 44%；跌幅上限 36%。 |  |  |  |  |
| 11 | GT-H2-ST-ST_ADD-002022-20220506 | GT-H2-ST-ST_ADD-002022-20220506 | AG-064 | 仅换证据 | ST/风险警示变更 | 002022.SZ | 2022-05-06 | [CNINFO official announcement for 002022 risk warning](https://static.cninfo.com.cn/finalpage/2022-04-30/1213259774.PDF) | —（本行非复合事实） | 核对官方公告是否明确 002022.SZ 自 2022-05-06 起新增 ST/风险警示；交易日为 2022-05-06，期望值：ST 标记=True。 |  |  |  |  |
| 12 | GT-H2-ST-ST_ADD-300965-20240429 | GT-H2-ST-ST_ADD-300965-20240426 | AG-096 | 事实修正 | ST/风险警示变更 | 300965.SZ | 2024-04-26 | [CNINFO official disclosure for 300965 risk warning](https://static.cninfo.com.cn/finalpage/2024-04-25/1219804789.PDF) | —（本行非复合事实） | 核对官方公告是否明确 300965.SZ 自 2024-04-26 起新增 ST/风险警示；交易日为 2024-04-26，期望值：ST 标记=True。 |  |  |  |  |
