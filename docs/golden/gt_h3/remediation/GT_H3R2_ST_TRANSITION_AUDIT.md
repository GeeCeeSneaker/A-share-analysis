# GT-H3R2 ST_TRANSITION 全量审计台账

> 状态：**v6 CANDIDATE AUDIT READY / 50 条 PASS / v5 IMMUTABLE / ACTIVE 仍为 v5 / FINAL INDEPENDENT CLOSURE PENDING**

## 1. 审计边界

本台账现逐行绑定非 ACTIVE 的 v6-candidate-20260908 50 条 ST_TRANSITION。v5 golden_cases_v5.jsonl 与 truth_manifest_v5.json 保持 immutable，活动指针仍指向 v5；本台账是 build/review evidence，不扩展 Golden row schema，也不把 expected_fields 当作状态转换证明。

判定规则冻结为：ST_ADD/STAR_ST_ADD 必须由官方一手材料证明 effective date 前 IS_ST_SEC=false、effective date 后 IS_ST_SEC=true；ST_REMOVE/STAR_ST_REMOVE 必须证明 true -> false。ST→*ST、*ST→ST、仅增加/移除退市风险层级，均不属于二元 ST_TRANSITION。

## 2. v6 candidate 结果

| 项目 | 数量 | 说明 |
| --- | ---: | --- |
| v6 ST_TRANSITION 总行数 | 50 | structural identity 按 (provider_symbol, event_effective_date, event_subtype) 计算 |
| PASS / transition_valid=true | 50 | 35 条 v5 身份未变并沿用已完成官方双核定位；15 条为新官方 CNINFO 二元 ST_ADD 候选 |
| ADD / REMOVE | 38 / 12 | v6 manifest 与逐行审计一致；未用层级变化凑数 |
| 审计证据状态 | 50 / 50 | PRE、EFFECTIVE 两侧均为 OFFICIAL_SOURCE_REVIEWED，官方 host 与 locator 完整 |
| v5 invalid 残留 | 0 | 15 条旧 INVALID_ST_LEVEL_CHANGE 已从 v6 DROP，未改判为 PASS |
| 可直接发布 | 否 | v6 仍是非 ACTIVE candidate；新增/替换 15 条尚待新的 Human Review，最终 Reviewer closure 也未完成 |

## 3. v5 → v6 变更范围

- DROP：当前 v5 审计识别的 15 条 INVALID_ST_LEVEL_CHANGE，完整列表见 v5→v6 rebuild plan。
- ADD：15 条新的官方 CNINFO 二元 false -> true 候选，完整案例字段、直链和 lineage 见 replacement candidate pool 与 v6 dataset。
- KEEP：其余 110 条 v5 身份保持；非 ST 的其余 75 条 review identity 全部相等，未发生语义漂移。
- carry-forward：review_identity_hash 由 ledger 重算，110 条 eligible / 15 条 not eligible；110 是当前 15-for-15 方案的 sanity check，不是写死的通过数字。
- 15 条 ADD 均保持 COMPILED，没有 reviewer provenance，不能自动继承 Human Review。

## 4. 15 条新增候选的官方证据

每条新增候选的 PRE/EFFECTIVE 证据均来自同一份官方 CNINFO PDF，已完成 HTTP 200 与全文读取；JSONL 中分别保留两侧 locator：

| 案例 | 代码 | 生效日 | 原文简称变化 | 官方 PDF |
| --- | --- | ---: | --- | --- |
| GT-H2-ST-ST_ADD-300495-20210507 | 300495.SZ | 20210507 | 美尚生态 → *ST美尚 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209893133.PDF) |
| GT-H2-ST-ST_ADD-002640-20210507 | 002640.SZ | 20210507 | 跨境通 → *ST跨境 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209892047.PDF) |
| GT-H2-ST-ST_ADD-600382-20210506 | 600382.SH | 20210506 | 广东明珠 → *ST广珠 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209878423.PDF) |
| GT-H2-ST-ST_ADD-600291-20210506 | 600291.SH | 20210506 | 西水股份 → *ST西水 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209878259.PDF) |
| GT-H2-ST-ST_ADD-600078-20210506 | 600078.SH | 20210506 | 澄星股份 → *ST澄星 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209877776.PDF) |
| GT-H2-ST-ST_ADD-600896-20210506 | 600896.SH | 20210506 | 览海医疗 → *ST海医 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209875156.PDF) |
| GT-H2-ST-ST_ADD-600615-20210506 | 600615.SH | 20210506 | 丰华股份 → *ST丰华 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209874374.PDF) |
| GT-H2-ST-ST_ADD-000502-20210506 | 000502.SZ | 20210506 | 绿景控股 → *ST绿景 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2021-04-30/1209872529.PDF) |
| GT-H2-ST-STAR_ST_ADD-688086-20220506 | 688086.SH | 20220506 | 紫晶存储 → *ST紫晶 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213274157.PDF) |
| GT-H2-ST-ST_ADD-603603-20220506 | 603603.SH | 20220506 | 博天环境 → *ST博天 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213274090.PDF) |
| GT-H2-ST-ST_ADD-002313-20220506 | 002313.SZ | 20220506 | 日海智能 → *ST日海 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213267451.PDF) |
| GT-H2-ST-ST_ADD-300301-20220506 | 300301.SZ | 20220506 | 长方集团 → *ST长方 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213267090.PDF) |
| GT-H2-ST-ST_ADD-002751-20220506 | 002751.SZ | 20220506 | 易尚展示 → *ST易尚 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213266378.PDF) |
| GT-H2-ST-ST_ADD-002316-20220506 | 002316.SZ | 20220506 | 亚联发展 → *ST亚联 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213265483.PDF) |
| GT-H2-ST-ST_ADD-002366-20220506 | 002366.SZ | 20220506 | 台海核电 → *ST海核 | [CNINFO PDF](https://static.cninfo.com.cn/finalpage/2022-04-30/1213263830.PDF) |

特别校正：600382.SH 原文简称变化是 **广东明珠 → *ST广珠**；该修正已同步到候选池、v6 truth_source 和审计 locator。

## 5. 机器验收与治理边界

已提交 v6 dataset、v6 manifest、v5→v6 rebuild plan、v5→v6 carry-forward ledger 和 v6 candidate verifier。验证器重算并绑定：125 总量、50 条 ST_TRANSITION、38/12 双向配额、无重复 ST structural identity、其他 75 条 review identity 不变、110/15 carry-forward、全量 50 PASS 审计。truth_manifest.json 活动指针仍保持 v5，不执行 review.py，不写入 REVIEWED provenance，不解除 GT-H3B。

下一步是三平台 final-head/current-main CI，随后返回独立 Reviewer 做 closure；任一新增 Human Review 或独立复核不通过，都必须继续保持 v6 非 ACTIVE。
