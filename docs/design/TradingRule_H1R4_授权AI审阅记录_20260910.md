# Trading Rule H1R4 授权 AI 审阅记录

日期：2026-09-10（Asia/Shanghai）
候选：`v20260910-h1r4-compiled`（dataset `2026-09-10.2`）
候选状态：`COMPILED`、非 `ACTIVE`
候选 manifest-style SHA-256：`ed17a49745291a7729650e1fa8b783cb6ae6c187aee68d68aca47aafb24f4d68`
Canonical bundle：`sha256/115971e9ecb35c34d364c708ca74f8db9fcb233d03d5d7e5f6c6bef02f02d0f4`（18,606 bytes）
证据规模：20 个唯一官方 URL、20 个去重 raw artifact、1,736,924 bytes；输入来源行 41 条。

## 1. 身份与状态

- **审阅身份**：`owner-authorized-ai-reviewer`。
- **授权依据**：项目 Owner 在 Issue #34 comment `5612090090` 明确授权助手完成 H1 14 条独立实质核验，并要求仓库 provenance 如实标记为 AI；这不表示项目 Owner 亲自阅读或签署了结果。
- **实质审阅依据**：PR #37 review `5162234439` 的 2020+ 14/14 PASS，以及合并前独立 delta re-review `5162769985` 的 PASS/MERGE AUTHORIZED；后者确认 H1R4 BSE binding blocker 已关闭。
- **当前状态**：`14/14 SUBSTANTIVE AI PASS / REVIEWED SEALED / ACTIVE MOVED / FINAL PR INDEPENDENT REVIEW AND CI PENDING`。

本记录是 Owner 授权下的 AI 审阅 provenance，不是“人工审阅”或项目 Owner 本人签署。H1R4 相比 H1R3 只向 `BSE_IPO_DAY_NO_LIMIT.source_ref` 增加既有历史 BSE Trading Rules URL；其他交易语义字段保持一致。独立 Reviewer 已接受该单一 binding delta；最终 seal 仅在本记录所述固定参数和封存后门禁通过后完成，仍需 final reviewed-seal PR 的独立复核与 CI 才能合并。

## 2. 14 条实质核验结果

| # | `rule_id` | AI 实质结果 | 已核对的官方原文定位与结论 |
|---:|---|---|---|
| 1 | `MAIN_BOARD_NORMAL` | `PASS (AI)` | 沪深主板规则与 2026 现行规则支持普通股票日涨跌幅 10%；现有 venue/code mapping 与 2020+ 候选范围相容。 |
| 2 | `MAIN_BOARD_ST_HISTORICAL_SH` | `PASS (AI)` | SSE 风险警示板办法第七条支持历史 5%；SSE 2026 风险警示调整材料支持 2026-07-06 切换，SH 风险警示适用关系成立。 |
| 3 | `MAIN_BOARD_ST_HISTORICAL_SZ` | `PASS (AI)` | SZSE 历史交易规则风险警示条款支持 5%；SZSE 2026 业务指南支持 2026-07-06 切换，SZ 主板代码范围与 `st_state=true` 关系成立。 |
| 4 | `MAIN_BOARD_ST_CURRENT` | `PASS (AI)` | SSE 2026 现行规则及沪深两所 2026 调整/指南材料支持 2026-07-06 起风险警示 10%，当前日期不会回落到旧 5%。 |
| 5 | `MAIN_BOARD_IPO_DAY` | `PASS (AI)` | SSE 2014 通知 §I 与 SZSE 2014 问答支持有效申报价 144%/64%，可换算为上市首日 +44%/−36%；沪深首批注册制主板 2023-04-10 上市材料支持 `effective_to=20230409`。 |
| 6 | `MAIN_BOARD_FIRST5_NO_LIMIT` | `PASS (AI)` | SSE/SZSE 主板 IPO 说明与首批上市公告支持 2023-04-10 起上市后前 5 个交易日不限价，第 6 个交易日回到普通规则；同一通用规则对 ST 状态不另造独立制度。 |
| 7 | `CHINEXT_PRE_REGISTRATION_NORMAL` | `PASS (AI)` | SZSE 改革前规则支持普通创业板 10%；2020-08-21 官方实施日期问答明确特别规定自 2020-08-24 起施行，旧区间至 2020-08-23。 |
| 8 | `CHINEXT_PRE_REGISTRATION_ST` | `PASS (AI)` | SZSE 改革前材料支持创业板 ST/*ST 为 5%；同一官方实施日期材料闭合 2020-08-24 切换边界。 |
| 9 | `CHINEXT_REGISTRATION` | `PASS (AI)` | 《创业板交易特别规定》§2.1 支持注册制创业板普通交易日 20%；官方实施日期问答支持自 2020-08-24 起适用，现行规则继续覆盖。 |
| 10 | `CHINEXT_REGISTRATION_FIRST5` | `PASS (AI)` | 《创业板交易特别规定》§2.1 支持 IPO 上市后前 5 个交易日不限价，第 6 个交易日适用 20%；按交易日计数，日期边界有一手来源。 |
| 11 | `STAR_MARKET` | `PASS (AI)` | 《科创板股票交易特别规定》第十八条支持前 5 个交易日后普通交易日涨跌幅 20%；科创板代码/venue mapping 与现行 SSE 规则覆盖相容。 |
| 12 | `STAR_MARKET_FIRST5` | `PASS (AI)` | 同一规定第十八条支持科创板 IPO 上市后前 5 个交易日不限价，第 6 个交易日为 20%；按交易日计数。 |
| 13 | `BSE_LIMIT` | `PASS (AI)` | BSE 2021 Trading Rules §3.3.11、§10.6 与 2026 现行规则支持北交所普通交易日 30%，历史起点为 2021-11-15；上市首日由单独规则优先处理。 |
| 14 | `BSE_IPO_DAY_NO_LIMIT` | `PASS (AI)` | BSE 2021 Trading Rules §3.3.12(a)、§10.6 与 2026 现行规则支持公开发行股票上市首日不限价、后续交易日 30%；H1R4 已将历史 URL 直接加入本行 source contract。该新增 binding 仍待独立 Reviewer 做 delta acceptance。 |

以上结果只覆盖项目已经确定的 2020+ 研究范围；不扩展为 1998 年以前的历史法律真值，也不把代码前缀 mapping 误写成交易所正文逐字列举的事实。

## 3. H1R4 单一 delta 的独立复核清单（已完成）

独立 Reviewer 已按以下范围复核 H1R3→H1R4 变化，不必重新打开其他 13 条已通过的实质材料：

1. `BSE_IPO_DAY_NO_LIMIT.source_ref` 新增且仅新增 `https://www.bse.cn/uploads/6/file/public/202209/20220924123627_d6405jicv9.docx`；
2. H1R4 evidence input 的第 14 条包含同一 URL 与 `trading_rule_h1_sources/bse_200010919.docx`；
3. source catalog 将该 byte-identical artifact 绑定到 `BSE_LIMIT` 与 `BSE_IPO_DAY_NO_LIMIT`，其 SHA-256 为 `c63dd4af0f21f13cca0edb9959874e2c909aabbc164fceda1321c57c44725919`；
4. canonical bundle exact coverage、hash、路径约束和唯一来源计数仍通过，未新增 raw artifact；
5. H1R3 与 H1R4 的 14 条交易语义字段完全相同；H1R3、Golden 和 Formal 状态未被改写，ACTIVE 仅在后述一次性 seal 中从旧 COMPILED 父版本迁移到新 REVIEWED 版本；
6. 本记录和 CLI 使用 `owner-authorized-ai-reviewer`，没有声称 human reviewer 或 Owner 本人完成阅读。

## 4. 封存执行与当前硬边界

- 从合并后的 clean `main@1af86215312b088859300521e4bb164f149e3717` 建立独立 final reviewed-seal 分支；封存前生命周期修正提交为 `6a8c0f562169c6543e0bced0a381548432f03523`，封存提交为 `6a01414cf00d0093e17771447ea4660a757f60ea`。
- `scripts/rules/review.py --candidate` 已按 Issue #34 固定参数仅执行一次，生成 `v20260910-h1r4-reviewed` 并将 ACTIVE 指向该版本；候选 `v20260910-h1r4-compiled` 保持 `COMPILED`、非 ACTIVE。
- REVIEWED dataset hash 为 `b8f3b94f6492a4ad5d5186ee4d26232bfffc92074e26ea7641eb794bb63e186b`，`reviewed_by` 为 `owner-authorized-ai-reviewer`；canonical evidence bundle 为 `sha256/115971e9ecb35c34d364c708ca74f8db9fcb233d03d5d7e5f6c6bef02f02d0f4`（18,606 bytes），20 个唯一 raw artifact、1,736,924 bytes。封存后 review/evidence gate 均为空问题，候选、旧 ACTIVE 和旧 COMPILED 版本字节不变。
- 未运行或消耗 Formal Production/B1-B7；未执行生产入口、Data Sufficiency、Provider capability、backfill、策略/回测或交易。
- 不包含账号、密码、IP、端口、Token、Cookie、profile、Provider 原始输出或专有 SDK/runtime 文件。

## 5. 最终封存审计摘要

- 封存前完整质量门禁：Ruff check、format、mypy，以及全量 pytest `1687 passed, 3 skipped`。
- 封存后验证：ACTIVE 为 `v20260910-h1r4-reviewed` / `REVIEWED` / 14 条；`trading_rule_review_gate(..., require_evidence_bundle=True)` 返回空问题；REVIEWED YAML 不含候选版 `Candidate only` 或 `human-reviewed` 文本，并含最终授权 AI provenance 说明。
- 当前待完成项仅是 final reviewed-seal PR 的 required CI 与独立 Reviewer PASS；在其通过和合并前，Formal B1-B7 仍禁止。
