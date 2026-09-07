# A-share-analysis · GT-H3B 前置独立二次复核门（2026-09-07）

## 状态

**GT-H3B SEAL 暂停 / INDEPENDENT SECOND REVIEW REQUIRED**

Owner 已完成 125-case Human Review，并明确授权 GT-H3B；但 Owner 同时要求在正式 seal 前由项目 Reviewer 对完整 125 条 Golden case 再做一次独立复核。该要求优先于此前 GT-H3B 执行授权。

## 独立性原则

1. 不把 Owner 的 APPROVE 当作事实正确性的先验结论；仅把 v5 candidate 作为待核验对象。
2. 对每条 case 独立判断 `PASS / REJECT / NEED_MORE_EVIDENCE`。
3. 优先使用交易所、上市公司交易所披露、证监会等官方一手来源；Provider-under-test、搜索摘要、媒体和策略/回测结果不能作为 Golden truth。
4. 对复合事实必须分别验证 RULE 与 APPLICABILITY；规则正确不自动证明某证券在某日期适用该规则。
5. 对 ST/DELIST 必须验证证券、事件类型、effective date/subtype；不得用观察日代替生效日。
6. 对 LIMIT_REGIME 必须验证制度、实施时间、板块/证券适用性和精确比例/无涨跌幅边界。
7. 对 DIVIDEND/RIGHT_ISSUE 必须验证证券、事件类型和除权除息日。
8. 发现任何事实错误或证据不足，不得通过 `expect_fields` 在 review.py 内修真值；回到 candidate governance 修复后再复核。

## 放行条件

只有当 125 条全部得到独立 Reviewer 的 `PASS`，且不存在 `REJECT / NEED_MORE_EVIDENCE`，才恢复 GT-H3B：

- materialize/hash official evidence bytes；
- 对复合事实保留完整证据链；
- 125/125 single atomic REVIEWED seal；
- `--reviewer project-owner`；
- seal PR 必须经 final CI + independent Reviewer closure + merge 后，才允许 Formal Production B1-B7。

在独立复核完成前：`review.py`、GT-H3B seal、Formal Production、Data Sufficiency、Provider verdict、2020+ backfill 均 BLOCKED。
