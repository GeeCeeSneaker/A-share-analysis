# GT-H3 Human Review Bundle

> Status: **GT-H3A PREPARED / NOT SEALED**
>
> This bundle is a review aid. It contains no retrieved official evidence bytes > and does not mark any case REVIEWED.

## Candidate and authority

- ACTIVE truth version: `v4-candidate-20260906`
- ACTIVE dataset: `golden_cases_v4.jsonl`
- ACTIVE dataset SHA256: `8c356c4a98e174c53d0fb8b2f502325d931866d8988dff502c8a3e4b451d1b9b`
- ACTIVE case count: `125` (`COMPILED 125/125`, `REVIEWED 0/125`)
- Main baseline used for this preparation: `9979a0545531010b6b71fefe1f5d465aab349991`
- GT-H2 Reviewer closure: `5125393678`
- Required boundary: Human Reviewer must explicitly approve or reject every case before any GT-H3 seal manifest is constructed.

## Review boundary

1. Review the exact official artifact for each group and verify issuer, document/rule version, scope, date, symbol and expected semantics.
2. A source mismatch, an unresolvable artifact, or a fact that the artifact does not prove is `REJECT`; do not repair the Golden row in this workflow.
3. Fill one case-level decision row for every case in `review_decision_template.jsonl`; permitted decisions are `APPROVE` and `REJECT`.
4. A complete human statement must authorize the full 125-case set and identify the human marker to write as `reviewed_by`.
5. Only after that statement may a separate executable manifest be built with exactly `case`, `artifact`, `kind` and `note` per row.

The GT-H3 seal manifest must not contain `expect_fields`. Human Review cannot change `expected_fields`; any correction returns to candidate governance.

## Artifact-group index

The bundle contains `104` deterministic artifact groups covering `125` cases. Every group is currently `PENDING_HUMAN_REVIEW`; `preflight_sha256` is intentionally empty until the exact bytes are retrieved.

| Group | Cases | Kind | Proposed local artifact | Official source |
|---|---:|---|---|---|
| `AG-001` | 2 | `EXCHANGE_RULEBOOK` | `artifact-001.html` | [BSE Trading Rules (Announcement [2021]15; effective 2021-11-15; 30% price-limit clause)](https://www.bse.cn/jygl_list/200010919.html) |
| `AG-002` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-002.pdf` | [CNINFO 000002 2021 annual profit-distribution implementation announcement; ex-date 2022-08-25](https://static.cninfo.com.cn/finalpage/2022-08-18/1214319792.PDF) |
| `AG-003` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-003.pdf` | [CNINFO 000002 2022 annual profit-distribution implementation announcement; ex-date 2023-08-25](https://static.cninfo.com.cn/finalpage/2023-08-21/1217577962.PDF) |
| `AG-004` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-004.pdf` | [CNINFO 000333 2021 annual profit-distribution implementation announcement; ex-date 2022-06-02](https://static.cninfo.com.cn/finalpage/2022-05-27/1213516434.PDF) |
| `AG-005` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-005.pdf` | [CNINFO 000333 2022 annual profit-distribution implementation announcement; ex-date 2023-06-01](https://static.cninfo.com.cn/finalpage/2023-05-25/1216898601.PDF) |
| `AG-006` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-006.pdf` | [CNINFO 000651 2021 annual profit-distribution implementation announcement; ex-date 2022-08-05](https://disc.static.szse.cn/disc/disk03/finalpage/2022-07-29/f1bcbfd5-1827-4754-813a-4daab09c217f.PDF) |
| `AG-007` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-007.pdf` | [CNINFO 000651 2022 annual profit-distribution implementation announcement; ex-date 2023-08-09](https://static.cninfo.com.cn/finalpage/2023-08-02/1217444821.PDF) |
| `AG-008` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-008.pdf` | [CNINFO 000858 2021 annual profit-distribution implementation announcement; ex-date 2022-06-29](https://static.cninfo.com.cn/finalpage/2022-06-22/1213776669.PDF) |
| `AG-009` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-009.pdf` | [CNINFO 000858 2022 annual profit-distribution implementation announcement; ex-date 2023-06-27](https://static.cninfo.com.cn/finalpage/2023-06-17/1217085394.PDF) |
| `AG-010` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-010.pdf` | [CNINFO company announcement: 东吴证券配股除权日 2020-03-23](https://static.cninfo.com.cn/finalpage/2020-03-23/1207391500.PDF) |
| `AG-011` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-011.pdf` | [CNINFO company announcement: 国海证券配股除权日 2020-01-14](https://static.cninfo.com.cn/finalpage/2020-01-09/1207235277.PDF) |
| `AG-012` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-012.pdf` | [CNINFO company announcement: 宁波银行配股除权日 2021-12-02](http://static.cninfo.com.cn/finalpage/2021-12-02/1211763892.PDF) |
| `AG-013` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-013.pdf` | [SSE 600036 2021 annual profit-distribution implementation announcement; ex-date 2022-07-15](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-07-08/600036_20220708_2_wBQHNFmu.pdf) |
| `AG-014` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-014.pdf` | [SSE 600036 2022 annual profit-distribution implementation announcement; ex-date 2023-07-13](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-07-06/600036_20230706_PLK0.pdf) |
| `AG-015` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-015.pdf` | [SSE 600104 2021 annual profit-distribution implementation announcement; ex-date 2022-07-15](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-07-08/600104_20220708_2_Cx62oZwE.pdf) |
| `AG-016` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-016.pdf` | [SSE 600104 2022 annual profit-distribution implementation announcement; ex-date 2023-07-19](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-07-12/600104_20230712_ONIE.pdf) |
| `AG-017` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-017.pdf` | [SSE 600519 2021 annual profit-distribution implementation announcement; ex-date 2022-06-30](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-06-24/600519_20220624_1_uyoZ4ubX.pdf) |
| `AG-018` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-018.pdf` | [SSE 600519 2022 annual profit-distribution implementation announcement; ex-date 2023-06-30](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-06-26/600519_20230626_V0SN.pdf) |
| `AG-019` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-019.pdf` | [SSE 600900 2021 annual profit-distribution implementation announcement; ex-date 2022-07-21](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-07-13/600900_20220713_1_zI17tKH7.pdf) |
| `AG-020` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-020.pdf` | [SSE 600900 2022 annual profit-distribution implementation announcement; ex-date 2023-07-21](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-07-17/600900_20230717_R4MO.pdf) |
| `AG-021` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-021.pdf` | [SSE 601318 2021 annual profit-distribution implementation announcement; ex-date 2022-06-20](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-06-11/601318_20220611_1_KRbdGZAx.pdf) |
| `AG-022` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-022.pdf` | [SSE 601318 2022 annual profit-distribution implementation announcement; ex-date 2023-06-14](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-06-07/601318_20230607_A9V4.pdf) |
| `AG-023` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-023.pdf` | [SSE 601398 2021 annual profit-distribution implementation announcement; ex-date 2022-07-12](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-07-05/601398_20220705_1_7xXht7EQ.pdf) |
| `AG-024` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-024.pdf` | [SSE 601398 2022 annual profit-distribution implementation announcement; ex-date 2023-07-17](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-07-11/601398_20230711_UH4E.pdf) |
| `AG-025` | 2 | `EXCHANGE_RULEBOOK` | `artifact-025.html` | [SSE Risk-Warning Board Trading Measures (exact rule page; 5% price-limit clause)](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20210531_5478105.shtml) |
| `AG-026` | 5 | `EXCHANGE_RULEBOOK` | `artifact-026.pdf` | [SSE STAR Market Trading Special Provisions (2019; beyond the first five listing days 20% price-limit clause)](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf) |
| `AG-027` | 2 | `EXCHANGE_RULEBOOK` | `artifact-027.pdf` | [SSE STAR Market Trading Special Provisions (2019; first five listing days no limit, later 20%)](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf) |
| `AG-028` | 6 | `EXCHANGE_RULEBOOK` | `artifact-028.html` | [SSE Trading Rules (exact rule page; main-board 10% price-limit clause)](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml) |
| `AG-029` | 2 | `EXCHANGE_RULEBOOK` | `artifact-029.html` | [SSE Trading Rules (exact rule page; main-board IPO first-day ±44%/−36% regime)](https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml) |
| `AG-030` | 1 | `SSE_ANNOUNCEMENT` | `artifact-030.pdf` | [SSE company announcement: ST 中安 risk-warning implementation effective 2022-05-06](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2022-05-05/600654_20220505_1_dNOo6yTW.pdf) |
| `AG-031` | 1 | `SSE_ANNOUNCEMENT` | `artifact-031.pdf` | [SSE company announcement: 大理药业 risk-warning implementation effective 2024-04-29](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-04-26/603963_20240426_ZG5D.pdf) |
| `AG-032` | 1 | `SSE_ANNOUNCEMENT` | `artifact-032.pdf` | [SSE company announcement: 宋都股份 risk-warning implementation effective 2023-05-05](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-04-29/600077_20230429_PNOI.pdf) |
| `AG-033` | 1 | `SSE_ANNOUNCEMENT` | `artifact-033.pdf` | [SSE company announcement: 庞大集团 risk-warning implementation effective 2023-05-05](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-04-29/601258_20230429_KZL0.pdf) |
| `AG-034` | 1 | `SSE_ANNOUNCEMENT` | `artifact-034.pdf` | [SSE company announcement: 慧辰股份 risk-warning implementation effective 2023-05-05](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-04-29/688500_20230429_MZM6.pdf) |
| `AG-035` | 1 | `SSE_ANNOUNCEMENT` | `artifact-035.pdf` | [SSE company announcement: 慧辰股份 risk-warning removal effective 2024-06-11](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2024-06-07/688500_20240607_1TNQ.pdf) |
| `AG-036` | 1 | `SSE_ANNOUNCEMENT` | `artifact-036.pdf` | [SSE company announcement: 莫高股份 risk-warning implementation effective 2023-05-04](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-04-28/600543_20230428_TL0Y.pdf) |
| `AG-037` | 1 | `SSE_ANNOUNCEMENT` | `artifact-037.pdf` | [SSE company announcement: 蓝光发展 risk-warning implementation effective 2023-05-04](https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2023-04-28/600466_20230428_CP1N.pdf) |
| `AG-038` | 1 | `SSE_ANNOUNCEMENT` | `artifact-038.html` | [SSE official announcement: 600593 risk warning effective 2021-07-22](http://www.sse.com.cn/disclosure/announcement/general/c/c_20210720_5526013.shtml) |
| `AG-039` | 1 | `SSE_ANNOUNCEMENT` | `artifact-039.html` | [SSE official delisting decision: 600837终止上市 effective 2025-03-04](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250226_10773005.shtml) |
| `AG-040` | 1 | `SSE_ANNOUNCEMENT` | `artifact-040.html` | [SSE official delisting decision: 601989终止上市 effective 2025-09-05](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250829_10790128.shtml) |
| `AG-041` | 1 | `SSE_ANNOUNCEMENT` | `artifact-041.html` | [SSE official delisting notice: 600068终止上市 effective 2021-09-13](http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20210909_82957014.shtml) |
| `AG-042` | 1 | `SSE_ANNOUNCEMENT` | `artifact-042.html` | [SSE official delisting notice: 600093摘牌 2022-06-23](http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220616_85759277.shtml) |
| `AG-043` | 1 | `SSE_ANNOUNCEMENT` | `artifact-043.html` | [SSE official delisting notice: 600145摘牌 2022-04-28](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220421_84964449.shtml) |
| `AG-044` | 1 | `SSE_ANNOUNCEMENT` | `artifact-044.html` | [SSE official delisting notice: 600190摘牌 2025-07-25](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250718_10785880.shtml) |
| `AG-045` | 1 | `SSE_ANNOUNCEMENT` | `artifact-045.html` | [SSE official delisting notice: 600225摘牌 2025-03-06](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250227_10773066.shtml) |
| `AG-046` | 1 | `SSE_ANNOUNCEMENT` | `artifact-046.html` | [SSE official delisting notice: 600421摘牌 2026-06-26](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20260622_10823158.shtml) |
| `AG-047` | 1 | `SSE_ANNOUNCEMENT` | `artifact-047.html` | [SSE official delisting notice: 600462摘牌 2025-07-21](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250714_10784844.shtml) |
| `AG-048` | 1 | `SSE_ANNOUNCEMENT` | `artifact-048.html` | [SSE official delisting notice: 600695摘牌 2022-06-14](http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20220607_85645623.shtml) |
| `AG-049` | 1 | `SSE_ANNOUNCEMENT` | `artifact-049.html` | [SSE official delisting notice: 600781摘牌 2023-06-28](http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20230619_90006973.shtml) |
| `AG-050` | 1 | `SSE_ANNOUNCEMENT` | `artifact-050.html` | [SSE official delisting notice: 601558摘牌 2020-07-02](http://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20200623_78480676.shtml) |
| `AG-051` | 1 | `SSE_ANNOUNCEMENT` | `artifact-051.html` | [SSE official risk-warning adjustment list: 600213 effective 2024-05-06](https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml) |
| `AG-052` | 1 | `SSE_ANNOUNCEMENT` | `artifact-052.html` | [SSE official risk-warning adjustment list: 603363 effective 2024-05-06](https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml) |
| `AG-053` | 1 | `SSE_ANNOUNCEMENT` | `artifact-053.html` | [SSE official risk-warning adjustment list: STAR 688282 effective 2024-05-06](https://www.sse.com.cn/disclosure/magin/announcement/ssereport/c/c_20240430_10753871.shtml) |
| `AG-054` | 5 | `EXCHANGE_RULEBOOK` | `artifact-054.html` | [SZSE ChiNext Trading Special Provisions (Notice [2020]515; effective with the 2020-08-24 reform; 20% clause)](https://www.szse.cn/disclosure/notice/general/t20200612_578381.html) |
| `AG-055` | 4 | `EXCHANGE_RULEBOOK` | `artifact-055.html` | [SZSE Trading Rules (exact historical rule page; ChiNext pre-2020-08-24 10% clause)](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html) |
| `AG-056` | 2 | `EXCHANGE_RULEBOOK` | `artifact-056.html` | [SZSE Trading Rules (exact historical rule page; rule 3.3.14 ST/*ST 5% clause)](https://www.szse.cn/disclosure/notice/general/t20060515_499577.html) |
| `AG-057` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-057.pdf` | [SZSE company announcement: 香农芯创配股除权日 2023-02-16](https://disc.static.szse.cn/disc/disk03/finalpage/2023-02-16/d2d8c9e3-0ad2-4a54-af01-e176019e9906.PDF) |
| `AG-058` | 1 | `COMPANY_ANNOUNCEMENT` | `artifact-058.pdf` | [SZSE company announcement: 鹭燕医药配股除权日 2020-09-17](https://disc.static.szse.cn/disc/disk02/finalpage/2020-09-17/4851a060-520a-4116-a303-00d7eb5aef65.PDF) |
| `AG-059` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-059.pdf` | [SZSE official announcement: *ST 中天 risk warning effective 2023-05-05](https://disc.static.szse.cn/disc/disk03/finalpage/2023-04-29/09ad58d3-6179-47a3-bba4-1cccf853ae04.PDF) |
| `AG-060` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-060.pdf` | [SZSE official announcement: *ST 中程 risk warning effective 2024-04-30](https://disc.static.szse.cn/disc/disk03/finalpage/2024-04-26/97177b91-6c27-437c-83e0-3c52d2f7b729.PDF) |
| `AG-061` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-061.pdf` | [SZSE official announcement: *ST 新文 risk warning effective 2022-04-29](https://disc.static.szse.cn/disc/disk03/finalpage/2023-01-30/58a93ed7-8b2f-4587-b43a-e9493b9daa60.PDF) |
| `AG-062` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-062.pdf` | [SZSE official announcement: *ST 海投 risk warning effective 2023-05-04](https://disc.static.szse.cn/disc/disk03/finalpage/2023-04-28/10329d33-dd5b-416b-a0cf-2af0a33c4e13.PDF) |
| `AG-063` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-063.pdf` | [SZSE official announcement: *ST 深南 risk warning effective 2022-04-21](https://disc.static.szse.cn/disc/disk03/finalpage/2022-04-20/d5512186-9d1c-4c2b-98a6-5a3d641e83a6.PDF) |
| `AG-064` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-064.pdf` | [SZSE official announcement: *ST 科华 risk warning effective 2022-05-06](http://disc.static.szse.cn/disc/disk02/finalpage/2022-04-30/a781efcd-39ab-4be8-9c80-0cc15863a36c.PDF) |
| `AG-065` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-065.pdf` | [SZSE official announcement: *ST 蓝盾 risk warning effective 2022-04-29](https://disc.static.szse.cn/disc/disk03/finalpage/2023-03-28/39fe9657-2530-48aa-9ff9-98cac5f2e15e.PDF) |
| `AG-066` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-066.pdf` | [SZSE official announcement: *ST 计通 risk warning effective 2022-08-08](https://disc.static.szse.cn/disc/disk03/finalpage/2022-08-05/832ecade-fa63-42d8-8520-388cdd3930cd.PDF) |
| `AG-067` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-067.pdf` | [SZSE official announcement: *ST 邦讯 risk warning effective 2021-04-29](http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-04-28/3a1e7c33-47d7-43d3-ba85-203b8221353e.PDF) |
| `AG-068` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-068.pdf` | [SZSE official announcement: *ST 金刚 risk warning effective 2021-04-28](http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-04-27/853620b1-b4a9-432d-9ee8-d8dcefd821d6.PDF) |
| `AG-069` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-069.pdf` | [SZSE official announcement: *ST 银河 risk warning effective 2022-05-06](http://disc.static.szse.cn/disc/disk03/finalpage/2022-04-30/b6d5b6a7-e992-4ff1-bd09-832e4e500651.PDF) |
| `AG-070` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-070.pdf` | [SZSE official announcement: *ST 雪发 risk warning effective 2022-05-06](http://disc.static.szse.cn/disc/disk03/finalpage/2022-04-30/4cb2d78e-0ec1-4c86-93b9-0d7e08127e5e.PDF) |
| `AG-071` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-071.pdf` | [SZSE official announcement: 000007 *ST removal effective 2022-07-01](https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-30/7de6ae82-da34-47da-a35b-71cbb965c01e.PDF) |
| `AG-072` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-072.pdf` | [SZSE official announcement: 000408 *ST removal effective 2021-05-12](https://disc.static.szse.cn/disc/disk02/finalpage/2021-05-11/f9006990-ffd3-40bb-9cb9-be8dc0511516.PDF) |
| `AG-073` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-073.pdf` | [SZSE official announcement: 002021 *ST removal effective 2024-06-03](https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-31/09907ab2-b9f4-4891-bfb4-21ed2cfa090d.PDF) |
| `AG-074` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-074.pdf` | [SZSE official announcement: 002058 *ST removal effective 2022-05-23](https://disc.static.szse.cn/disc/disk03/finalpage/2022-05-20/9ac63995-9ddd-4dca-ada2-f9fd0ead9e60.PDF) |
| `AG-075` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-075.pdf` | [SZSE official announcement: 002086 *ST removal effective 2024-06-12](https://disc.static.szse.cn/disc/disk03/finalpage/2024-06-07/cb052454-f6db-44e0-a320-079c4c14c864.PDF) |
| `AG-076` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-076.pdf` | [SZSE official announcement: 002482 full *ST removal effective 2024-06-18](https://disc.static.szse.cn/disc/disk03/finalpage/2024-06-14/11ae7c86-7e5d-4eba-9e5d-6bd0c31767db.PDF) |
| `AG-077` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-077.pdf` | [SZSE official announcement: 002513 *ST removal effective 2021-06-21](https://disc.static.szse.cn/disc/disk02/finalpage/2021-06-18/0acbdccf-207a-4bab-a5fb-a6bf8d8c515a.PDF) |
| `AG-078` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-078.pdf` | [SZSE official announcement: 300010 *ST removal effective 2024-06-13](https://disc.static.szse.cn/disc/disk03/finalpage/2024-06-12/f438ff5f-8b32-4d10-aaab-a8598162ef43.PDF) |
| `AG-079` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-079.pdf` | [SZSE official announcement: 300209 *ST removal effective 2025-05-13](https://disc.static.szse.cn/disc/disk03/finalpage/2025-05-09/f2d85e09-1b78-42bc-a128-f1862d6b0fe9.PDF) |
| `AG-080` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-080.pdf` | [SZSE official announcement: 300965 *ST removal effective 2025-05-06](https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-30/d8e3ad5c-377f-4d9c-8d6c-31a510424ff8.PDF) |
| `AG-081` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-081.pdf` | [SZSE official delisting notice: 000540摘牌 2023-06-30](https://disc.static.szse.cn/disc/disk03/finalpage/2023-06-28/2d0e5c9f-a6d7-4c00-9ac2-bf286ba715b8.PDF) |
| `AG-082` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-082.pdf` | [SZSE official delisting notice: 000611摘牌 2022-06-28](https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-28/0df4c2ca-295b-4581-a172-094d8cae8425.PDF) |
| `AG-083` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-083.pdf` | [SZSE official delisting notice: 000982摘牌 2024-08-12](https://disc.static.szse.cn/disc/disk03/finalpage/2024-08-12/c552bbd6-8940-49ef-bbd0-c2c83a3ece6d.PDF) |
| `AG-084` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-084.pdf` | [SZSE official delisting notice: 002118摘牌 2023-08-04](http://disc.static.szse.cn/disc/disk03/finalpage/2023-07-31/44450b39-f154-45b0-a05f-4878f0c55261.PDF) |
| `AG-085` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-085.pdf` | [SZSE official delisting notice: 002610摘牌 2024-08-12](https://disc.static.szse.cn/disc/disk03/finalpage/2024-08-09/1dc535d8-fbe2-42bb-bab6-cd90d0e12e64.PDF) |
| `AG-086` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-086.pdf` | [SZSE official delisting notice: 300064摘牌 2022-06-27](https://disc.static.szse.cn/disc/disk03/finalpage/2022-06-27/286a098f-56a5-4a5b-8e0d-1953eebf9f2f.PDF) |
| `AG-087` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-087.pdf` | [SZSE official delisting notice: 300208摘牌 2025-07-21](https://disc.static.szse.cn/disc/disk03/finalpage/2025-07-18/ff3f8315-18fd-48e8-a473-545bcb5a0a67.PDF) |
| `AG-088` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-088.pdf` | [SZSE official delisting notice: 300273摘牌 2023-07-06](https://disc.static.szse.cn/disc/disk03/finalpage/2023-07-05/776889cd-c8c1-48fb-b1a4-d0cf4819e8fd.PDF) |
| `AG-089` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-089.pdf` | [SZSE official disclosure referring to *ST 东洋 risk warning effective 2023-05-05](https://disc.static.szse.cn/disc/disk03/finalpage/2023-12-01/d12ed6af-2ddf-4be3-9c59-050a5484375e.PDF) |
| `AG-090` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-090.pdf` | [SZSE official disclosure referring to *ST 合泰 risk warning effective 2024-05-06](https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-16/a4389dc6-97e8-4f1b-a2cc-bae0de6e5dec.PDF) |
| `AG-091` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-091.pdf` | [SZSE official disclosure referring to *ST 吉药 risk warning effective 2024-04-30](https://disc.static.szse.cn/disc/disk03/finalpage/2025-03-10/cfd76336-3ab7-4c6d-8e17-8fdb4fe8c447.PDF) |
| `AG-092` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-092.pdf` | [SZSE official disclosure referring to *ST 名家汇 risk warning effective 2024-04-29](https://disc.static.szse.cn/disc/disk03/finalpage/2025-03-20/cd19ee3f-0bc9-4e4b-9477-af6b6fab7c4b.pdf) |
| `AG-093` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-093.pdf` | [SZSE official disclosure referring to *ST 天润 risk warning effective 2020-04-29](http://disc.static.szse.cn/download/disc/disk02/finalpage/2021-08-26/d61cb4c7-8be7-45c6-ace7-99e1faed88e1.PDF) |
| `AG-094` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-094.pdf` | [SZSE official disclosure referring to *ST 太安 risk warning effective 2023-05-05](https://disc.static.szse.cn/disc/disk03/finalpage/2024-04-30/20e9fe23-010b-4cd6-a0e8-cb71676efd21.PDF) |
| `AG-095` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-095.pdf` | [SZSE official disclosure referring to *ST 奇信 risk warning effective 2022-05-06](https://disc.static.szse.cn/disc/disk03/finalpage/2022-11-18/d507ec79-4364-4159-b566-3b52c4df5c48.PDF) |
| `AG-096` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-096.pdf` | [SZSE official disclosure referring to *ST 恒宇 risk warning effective 2024-04-29](https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-11/d1f5b09c-3741-4e64-8984-a65441b01dd1.pdf) |
| `AG-097` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-097.pdf` | [SZSE official disclosure referring to *ST 有树 risk warning effective 2024-04-29](https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-17/16f33a70-834e-42b8-a894-d8b5abe35535.pdf) |
| `AG-098` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-098.pdf` | [SZSE official disclosure referring to *ST 沈机 risk warning effective 2022-04-19](https://disc.static.szse.cn/disc/disk03/finalpage/2023-04-29/fc4e9195-d651-477a-9bb9-a1e5f52cc43a.PDF) |
| `AG-099` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-099.pdf` | [SZSE official disclosure referring to *ST 皇台 risk warning effective 2022-04-29](https://disc.static.szse.cn/disc/disk03/finalpage/2023-03-13/0637c8e3-59a6-45ce-a0e5-de996b4a72e5.PDF) |
| `AG-100` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-100.pdf` | [SZSE official disclosure referring to *ST 红阳 risk warning effective 2024-09-19](https://disc.static.szse.cn/disc/disk03/finalpage/2024-10-09/a133a2c9-9d40-4c92-85ac-3efed7d8359d.PDF) |
| `AG-101` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-101.pdf` | [SZSE official disclosure referring to *ST 越博 risk warning effective 2023-05-04](https://disc.static.szse.cn/disc/disk03/finalpage/2024-05-08/f32b3983-feec-44e5-ba43-1bf9ec15cf84.pdf) |
| `AG-102` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-102.pdf` | [SZSE official disclosure referring to *ST 迪威风险警示 effective 2024-04-30](https://disc.static.szse.cn/disc/disk03/finalpage/2025-04-29/30ec3b9a-dd82-4aaf-bf05-273e9edcb2a0.pdf) |
| `AG-103` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-103.pdf` | [SZSE official disclosure referring to *ST 顺利 risk warning effective 2022-05-06](https://disc.static.szse.cn/disc/disk03/finalpage/2023-03-13/fd76e611-9f68-4ddc-96de-7c8a37fc5fda.PDF) |
| `AG-104` | 1 | `SZSE_ANNOUNCEMENT` | `artifact-104.pdf` | [SZSE official disclosure referring to 002022 *ST removal effective 2023-04-04](https://disc.static.szse.cn/disc/disk03/finalpage/2024-03-22/e0b014e3-3416-4526-9063-9845e9e42a6f.PDF) |

## Tracked outputs

- `review_bundle_index.jsonl`: one row per unique official artifact group, including all case-specific semantics and retrieval placeholders.
- `review_decision_template.jsonl`: exactly one blank human decision row per ACTIVE case.
- This document: review instructions, authority and checkpoint state.

## Explicitly not done

- No official HTML/PDF bytes were retrieved or committed in Checkpoint A.
- No `REVIEWED` field, evidence hash, ACTIVE pointer advance or reviewed dataset was created.
- No `review.py` seal, GT-H3B, Formal Production B1-B7, Data Sufficiency, Provider capability approval, backfill, strategy, backtest or trading run was executed.
