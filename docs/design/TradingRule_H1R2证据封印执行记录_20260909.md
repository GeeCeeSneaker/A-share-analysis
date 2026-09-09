# Trading Rule H1R2 证据封印执行记录

日期：2026-09-09（Asia/Shanghai）
状态：`EVIDENCE MATERIALIZED / BUNDLE VERIFIED / HUMAN REVIEW PENDING / NOT SEALED`

## 1. 执行基线与不可变性

- PR #35 已合并，执行分支从 clean `main@e096b0364d3dc5a00e21879fe5bd8fc4a758b07f` 建立。
- 合并后 `load_active_rules(configs/trading_rules)` 通过：ACTIVE `rule_version=v20260824-compiled`，`review_status=COMPILED`，旧 ACTIVE dataset hash 为 `dd2219d2383b01d2b8a5019ddf713d36a04f1badbeabe1aeffc7e20fa91ef2d8`。
- 当前 H1R2 candidate 为 `configs/trading_rules/versions/v20260909-h1r2-compiled/rules.yaml`，dataset version `2026-09-09.2`，14 条，非 ACTIVE、`COMPILED`。
- candidate manifest-style SHA-256（`versions/v20260909-h1r2-compiled/rules.yaml` 路径 + 原始 bytes）为 `6cb355fdaf5f9cc5fe2da09d9d0ecce18ee1e04378a42a25515364fd4019c55f`。
- 旧 `v20260909-h1-compiled`、旧 ACTIVE、ACTIVE selector 和 Golden v7 在本次执行准备中未修改。

## 2. Bundle 与原始材料

输入：[`trading_rule_h1_evidence_input.json`](../provider_verification/trading_rule_h1_evidence_input.json)
候选 source contract：14 个且仅 14 个 `rule_id`，19 个且仅 19 个 unique official URL。
发布 bundle：`configs/trading_rules/evidence/sha256/14f09ed0707b0ef1d84ae2dbe880f87bdd186d0c21e61e6387f26fa41bd403d0`
bundle ref/hash：`sha256/14f09ed0707b0ef1d84ae2dbe880f87bdd186d0c21e61e6387f26fa41bd403d0`
bundle bytes：`16,557`
raw artifact：`19` 个，合计 `1,702,416` bytes，均按 `evidence/sha256/<sha256>` 内容寻址。

canonical bundle 是由合并后的 `prepare_rule_evidence_bundle()` 从冻结 input 生成的发布载荷；输入中的本地 `artifact_path` 不会进入 bundle。bundle 和 raw artifact 已由 `validate_rule_evidence_bundle()` 重新校验，确认 schema、14/14 rule、required URL exact coverage、hash、size、content-address 与 path confinement 均通过。

## 3. 19 个 raw artifact 清单

artifact ref 是相对于 `configs/trading_rules/evidence/` 的路径；同一个 artifact 可以被多条规则复用，但 bundle 中每条规则的 source URL 仍逐条保留。

| # | official source URL | kind / role | artifact ref | bytes | rules |
|---:|---|---|---|---:|---|
| 1 | https://docs.static.szse.cn/www/disclosure/notice/general/W020200612831351578076.pdf | EXCHANGE_RULEBOOK / RULE | `sha256/c4ea293e2f1e86c5083fa7b606ceb5cf621885ff539e05bf089a7efd5fa7c20f` | 279208 | CHINEXT_REGISTRATION, CHINEXT_REGISTRATION_FIRST5 |
| 2 | https://docs.static.szse.cn/www/lawrules/rule/trade/W020260424690713155663.pdf | EXCHANGE_RULEBOOK / RULE | `sha256/9b66f8b0db70f84a25ef1ccb4ee2351001724e408117552d75f6d8993483c586` | 282084 | CHINEXT_REGISTRATION, CHINEXT_REGISTRATION_FIRST5, MAIN_BOARD_FIRST5_NO_LIMIT, MAIN_BOARD_NORMAL, MAIN_BOARD_ST_CURRENT |
| 3 | https://investor.szse.cn/knowledge/qa/t20230306_599093.html | EXCHANGE_NOTICE / RULE | `sha256/b001c495439287f9a78f4fca8a9c93c22008f7be2ac2773799c0e61f9779b501` | 42009 | MAIN_BOARD_FIRST5_NO_LIMIT |
| 4 | https://www.bse.cn/uploads/6/file/public/202209/20220924113331_fwbg1kr3qu.docx | EXCHANGE_RULEBOOK / TRANSITION | `sha256/6617761b2bcc369d1f6a766b47cd91b0e4b3f99dd2024325b27c13c82f20da10` | 110291 | BSE_LIMIT |
| 5 | https://www.bse.cn/uploads/6/file/public/202209/20220924123627_d6405jicv9.docx | EXCHANGE_RULEBOOK / RULE | `sha256/c63dd4af0f21f13cca0edb9959874e2c909aabbc164fceda1321c57c44725919` | 72236 | BSE_LIMIT |
| 6 | https://www.bse.cn/uploads/6/file/public/202604/20260424170528_52kqyhc7p9.docx | EXCHANGE_RULEBOOK / RULE | `sha256/56145494879dbb8192e9f6e2b5c91cbad102364de83b799c14b263f9a7c50cd2` | 82385 | BSE_IPO_DAY_NO_LIMIT, BSE_LIMIT |
| 7 | https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988761.shtml | EXCHANGE_NOTICE / RULE | `sha256/3c36939015910aee528854af2897dff2995f73407945eda10e2311d699e1d453` | 34223 | MAIN_BOARD_IPO_DAY |
| 8 | https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230201_5715605.shtml | EXCHANGE_NOTICE / RULE | `sha256/1f29d81f8566e3fdef2c3ad93121e7194099ba40bc19e83566c488bfb8f0f414` | 54346 | MAIN_BOARD_FIRST5_NO_LIMIT |
| 9 | https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230217_5716420.shtml | EXCHANGE_NOTICE / TRANSITION | `sha256/e1d0b62160c999c2dab5e123113225c1f703bf75e1367f6ff6e9beeae50b0dc6` | 40849 | MAIN_BOARD_IPO_DAY |
| 10 | https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml | EXCHANGE_NOTICE / TRANSITION | `sha256/18223769e90665229ef7eead3c7e68c7397787a7913340773a57e8127546f09b` | 28607 | MAIN_BOARD_ST_CURRENT, MAIN_BOARD_ST_HISTORICAL_SH |
| 11 | https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/c_20230418_5720136.shtml | EXCHANGE_RULEBOOK / RULE | `sha256/09c05c6b4ee1106dbf24bfea968564dce3c2ec5c652bf3138cd578e6363215b6` | 95933 | MAIN_BOARD_NORMAL |
| 12 | https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10785118/files/8c544552dc7e4c83a863440179f0b9de.pdf | EXCHANGE_RULEBOOK / RULE | `sha256/e751bcc6470c49a4de98c5dce32d03e926927f0825d3f9c469274b802e748b6a` | 268491 | STAR_MARKET, STAR_MARKET_FIRST5 |
| 13 | https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20121216_10785153.shtml | EXCHANGE_RULEBOOK / RULE | `sha256/5293a15cbddec99b56d2063306e1a975fa7d8f3b6d4dcfa9868eb21ba7d0992e` | 43937 | MAIN_BOARD_ST_HISTORICAL_SH |
| 14 | https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/10816482/files/959da0158c65434daa8a43a6e32be7ba.docx | EXCHANGE_RULEBOOK / RULE | `sha256/fc922c433438b2636cb631eab25cca405209712acbb6aaded768c45456ff8888` | 65302 | MAIN_BOARD_FIRST5_NO_LIMIT, MAIN_BOARD_NORMAL, MAIN_BOARD_ST_CURRENT, STAR_MARKET, STAR_MARKET_FIRST5 |
| 15 | https://www.szse.cn/aboutus/trends/news/t20140613_518480.html | EXCHANGE_NOTICE / RULE | `sha256/d793af76b76cb17b97580323284d478b4a5f5743927816dcb610ca74074de726` | 40419 | MAIN_BOARD_IPO_DAY |
| 16 | https://www.szse.cn/aboutus/trends/news/t20230404_599697.html | EXCHANGE_NOTICE / APPLICABILITY | `sha256/553dee689fbb9dee894871f2d7a6c6b555ae27880cacb7944d163d0894c13e81` | 13331 | MAIN_BOARD_FIRST5_NO_LIMIT, MAIN_BOARD_IPO_DAY |
| 17 | https://www.szse.cn/disclosure/notice/general/t20060515_499577.html | EXCHANGE_RULEBOOK / RULE | `sha256/8ac9e917ef0c70a9bacd2769f468bf84584f4c229790c469b47c73cba40cd31e` | 113649 | CHINEXT_PRE_REGISTRATION_NORMAL, MAIN_BOARD_NORMAL, MAIN_BOARD_ST_HISTORICAL_SZ |
| 18 | https://www.szse.cn/disclosure/notice/general/t20200710_579459.html | EXCHANGE_NOTICE / TRANSITION | `sha256/c1ddedd1f5829690db8e7338925d3bc1b3485f937cd2e9a523b81f4188e7c31b` | 15713 | CHINEXT_PRE_REGISTRATION_NORMAL, CHINEXT_PRE_REGISTRATION_ST |
| 19 | https://www.szse.cn/lawrules/service/member/t20260630_621404.html | EXCHANGE_NOTICE / TRANSITION | `sha256/fe4df31efcc2c8ecab178c11d3569d8bec2c528c45e65c8ba35bc6b742ce79de` | 19403 | MAIN_BOARD_ST_CURRENT, MAIN_BOARD_ST_HISTORICAL_SZ |

## 4. 人工审阅与 seal 状态

- 14 行操作表：[`TradingRule_H1_人工审阅操作表_20260909.md`](TradingRule_H1_人工审阅操作表_20260909.md)。当前所有结果仍为 `待填`。
- 人工 Reviewer 必须实际打开 bundle 中每个 `source_url` 对应的 raw artifact，确认数值/语义、适用证券范围、生效时间和 2020+ 边界；复合规则需确认 `RULE` 与适用性/过渡证据闭合。
- 本记录不构成 `APPROVE`，不写入 reviewer marker，不运行 `scripts/rules/review.py --candidate`。只有 14/14 `APPROVE`、独立 Reviewer 关闭 hash/URL/immutability 检查后，才允许按 Issue #34 运行一次性 seal。
- ACTIVE、Golden v7、Formal Production 和任何账号/密码/endpoint/Token/Cookie/profile/Provider 原始输出均未改变或提交。

## 5. 可复核命令与后续门禁

本轮已执行并通过：

```text
uv run python -c "... load_active_rules(...) ..."
uv run python -c "... prepare_rule_evidence_bundle(...) ..."
uv run python -c "... validate_rule_evidence_bundle(...) ..."
```

后续必须在独立 PR 中完成 focused H1 evidence/seal tests、全量 pytest、Ruff、mypy、`uv pip check`、`git diff --check` 和三平台 CI。CI 通过不等于 seal 通过；在独立 Reviewer 审阅并合并前，Formal Production B1-B7 继续禁止。
