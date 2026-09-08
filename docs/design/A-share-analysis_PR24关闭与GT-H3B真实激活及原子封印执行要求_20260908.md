# A-share-analysis — PR #24 关闭与 GT-H3B 真实激活及原子封印执行要求

日期：2026-09-08

## 1. Reviewer 最终裁决

PR #24（`feat: add GT-H3B case-bound evidence contract and safe promotion`）在 final head `2029689ab7f1ee25b30fd0c030aff19d55e8e190` 上完成独立复审。

- Reviewer final review：`5138283876`
- final test-merge：`dfc2a13423a74d884163830a004b0d315e89e8f3`
- test-merge composition：`main@d45e96b16bab1638bd199eba5bccab11a904a731 + head@2029689ab7f1ee25b30fd0c030aff19d55e8e190`
- final CI：run `34192456642` / #422，Windows 3.12、Windows 3.14、Ubuntu 3.14 全部 SUCCESS；full pytest 1609 passed
- merge commit：`f2a4ca48453c781b118ca9e969f0ed3c6879701b`

裁决：**GT-H3B-P0 / P1 / P1.1 VERIFIED；P0-BYPASS-01 CLOSED；PR #24 MERGED。**

本裁决只关闭工具与信任边界实现，不代表 v6 已经 ACTIVE，也不代表 REVIEWED seal 已经运行。

## 2. 当前唯一授权工作：GT-H3B 受控真实执行

下一阶段不得再扩展 Golden truth、不得新增候选、不得修改 v4/v5/v6 versioned bytes。只允许按已经验证的合同执行以下顺序。

### Phase A — governed v6 promotion

执行既有 `promote-existing` 路径，将 `v6-candidate-20260908` 从 staged candidate 安全推进为 ACTIVE。

必须满足：

1. 当前 ACTIVE 必须是预期旧版本；异常 ACTIVE fail closed。
2. v4/v5/v6 versioned dataset/manifest bytes 必须与冻结 SHA 完全一致。
3. v5→v6 rebuild plan、110/15 review identity、50/50 ST transition audit 必须重新验证。
4. 不允许手工编辑 `truth_manifest.json`。
5. promotion 成功后立即记录 ACTIVE truth version、dataset file/hash、case count、review summary 与全部 gate 结果。

Phase A 失败时禁止进入 Phase B。

### Phase B — 125/125 official evidence materialization

以冻结合同：

`docs/golden/gt_h3/gt_h3b/v6_case_evidence_source_contract.jsonl`

为唯一来源映射权威。合同 SHA256：

`3c235e35d1a09f0171322a7f0c610edb3cbe3d5ad8c6afc701f7b90afa77d3bb`

要求：

1. 125 个 case exactly once；不得替换 case、URL 或 kind。
2. ordinary case 获取合同中精确 official `source_ref` 的原始 bytes。
3. 五个 composite case 必须同时获取并保留有序 `RULE -> APPLICABILITY` 两份原始 bytes，构造 deterministic `EVIDENCE_BUNDLE`。
4. evidence 下载/获取过程可以使用浏览器或受控下载工具，但最终 review manifest 必须逐项与冻结合同完全匹配。
5. 不使用搜索摘要、二手网页、AI 摘要或人工重写内容替代 official raw bytes。
6. 获取失败、HTTP/反爬/跳转导致无法确认原始官方 bytes 时 fail closed，记录具体 case/source_ref；不得静默换源。
7. 不提交账号、Token、Cookie、IP、Provider 凭据或其他敏感信息。

### Phase C — one atomic 125/125 REVIEWED seal

构造完整 125-entry review manifest，并一次性执行：

```bash
uv run python scripts/golden/review.py --manifest <gt_h3b_125_manifest.json> --reviewer project-owner
```

要求：

1. review manifest 覆盖 ACTIVE 125/125 exactly once。
2. 禁止任何 `expect_fields`。
3. ordinary entry 必须声明 `sources`；composite entry 必须声明 `bundle_sources`。
4. `review.py` 必须在 staging 前通过 frozen case/source/kind contract 校验。
5. authoritative evidence SHA256 只由 `review.py` 对真实 bytes 计算。
6. publication 顺序保持 evidence -> versioned reviewed dataset/manifest -> ACTIVE last。
7. 任意失败不得留下半发布状态；rollback/recovery 必须符合 PR #24 已验证语义。
8. 不允许分批 N/125 seal，不允许手工把 review_status 改成 REVIEWED。

## 3. 预期成功状态

成功后至少应满足：

```text
ACTIVE truth version            = 新的 reviewed Golden version（以实际工具生成结果为准）
case_count                      = 125
review_summary                  = REVIEWED 125/125
review_readiness_gate           = []
quantity_gate                   = []
event_coverage_gate             = []
production_formal_gate          = []
source_artifact_hash            = 125/125 非空且与 evidence bytes 精确匹配
source_artifact_ref             = 125/125 content-addressed
old v1-v6 versioned files       = byte-identical / immutable
```

不得预先假设 reviewed version 名称或编号；以 `review.py` 实际 create-only 结果为准。

## 4. 执行 PR / 审计记录要求

建议新建独立执行 PR，例如：

`chore: execute GT-H3B reviewed golden seal`

该 PR / 记录必须包含：

- source main SHA；
- Phase A promotion 命令与结果；
- promotion 后 ACTIVE version/hash/case count/gates；
- 125-entry manifest 的 SHA256；
- official evidence materialization summary：125 case、ordinary 数、composite 5、bundle 5；
- seal 命令、exit code、生成 reviewed version、dataset hash；
- REVIEWED 125/125 与所有 gate 结果；
- evidence store 数量与 hash consistency 验证；
- v1-v6 immutable verification；
- final required CI run ID（Windows 3.14、Windows 3.12、Ubuntu 3.14）；
- 明确声明未执行 Formal Production B1-B7。

不要在 PR body 或日志中粘贴大批原始 evidence 内容；记录可审计 identity/hash 即可。

## 5. Reviewer 下一步

仓库更新后，独立 Reviewer 只复核：

1. promotion 是否通过受治理路径完成；
2. ACTIVE 是否确为冻结 v6；
3. 125/125 evidence 是否与 frozen source contract 精确绑定；
4. 5 个 bundle 是否包含完整有序 RULE/APPLICABILITY raw members；
5. REVIEWED seal 是否一次性原子完成；
6. reviewed dataset/manifest/evidence hash 是否自洽；
7. v1-v6 是否保持 immutable；
8. final-head/current-main test-merge 与三平台 CI 是否通过。

只有 Reviewer 明确给出 `GT-H3B REVIEWED GOLDEN VERIFIED / CLOSED` 并合并该执行结果后，才允许启动一次 controlled Formal Production B1-B7。

## 6. 当前禁止事项

在 GT-H3B reviewed Golden 关闭前继续禁止：

- Formal Production B1-B7；
- Provider capability GO / CONDITIONAL GO；
- Data Sufficiency verdict；
- 2020+ full backfill；
- REV-03 orphan deletion/recovery cleanup；
- unattended large backfill；
- strategy/backtest/live trading work用于反向修改 Golden truth。
