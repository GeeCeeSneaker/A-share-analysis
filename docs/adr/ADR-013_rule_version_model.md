# ADR-013: Trading Rule Version Model + CA Event Taxonomy（R4-A2.5 / CR-1.2.1）

- 状态：ACCEPTED
- 日期：2026-08-25
- 依据：审计 R4-A2.4/CR-1.2 复审（裁决 REOPENED）→ R4-A2.5 / CR-1.2.1 开发工作要求（P0-01..05 + P1）
- 关系：**amendment to ADR-012**（rule binding 升级为版本模型；raw commit 增加 orphan 恢复语义）
- 登记变更：DM-CR-20260825-001 / 002 / 003（管理总册 §61）

## 1. Trading Rule 版本模型（P0-02，amendment to ADR-012 §2.1）

ADR-012 的绑定以"规则目录当前状态"为单位；本修订升级为与 Golden Truth 一致的
**immutable versions + ACTIVE selector** 模型：

```
configs/trading_rules/
    rule_manifest.json          # ACTIVE selector（单一无歧义指针）
    versions/
        v20260824-compiled/rules.yaml    # COMPILED 候选（不可变）
        v20260825-reviewed/rules.yaml    # REVIEWED（人工复核后，不可变）
    evidence/                   # 已封存的官方 source artifacts
```

- manifest：`rule_version`（选择器 id）/ `review_status` / `dataset_files[]` /
  `dataset_hash`（对每个文件 rel-path+bytes 的联合 hash）/ `dataset_version`
  （yaml 内容版本，与 rule_version 是两个概念）/ `review_provenance`；
- `TradingRuleBook.load(dir)` 只加载 manifest 声明的文件——**目录 glob 合并语义废除**
  （COMPILED 与 REVIEWED 共存不再产生歧义）；`load(file)` 为单文件显式加载；
- `load_active_rules()` 复算 dataset_hash（**ACTIVE 数据篡改在 new_run 即阻断**）；
- SpikeRun 绑定 `trading_rule_version + dataset_files[] + dataset_hash`
  （R4-A2.4 的单 file/hash 字段废除，兼容读取旧 run json）；
  `load_bound_rule_book` 按文件清单逐文件校验联合 hash——**篡改任一绑定文件阻断 replay**；
- ACTIVE 推进（新 REVIEWED 版本）不影响历史 run 的绑定解析（对抗测试证明）。

## 2. Review Gate 证据加固（P0-03）

`trading_rule_review_gate` 的 provenance 校验从"存在性"升级为**结构化 schema**：

- `source_artifact_ref` 相对 **evidence root**（rules_root/evidence）解析，且
  path-confined：绝对路径与 `..` 穿越在任何文件系统访问**之前**拒绝；
- `source_artifact_hash` 必须 64 位小写 hex；`reviewed_at`/`source_retrieved_at`
  必须 ISO-8601；`source_artifact_kind` allowlist；
- artifact bytes 仍须与封存 hash 一致。

## 3. 正式消费者全部走 run-bound book（P0-01）

- `validate_limit_rule(rows, *, book=...)` 的 `book` 成为**必填 keyword**
  （无默认值；显式 `book=None` 得到结构化 FAIL——旧静默回退工作树 SoR 的路径
  从签名上消失）；
- probes（B3/B5）传 `ctx.rule_book`；`route_all` 把 run-bound book 传入
  limit/BJ 验证器；
- AST 守卫（测试）：probes/golden_router 中 `validate_limit_rule` 调用必须带
  `book=` 且不得为 `None` 字面量；`resolve_*` 调用必须带 `book=`。

## 4. CA Event Taxonomy（P0-04）

- 事件类型分类学：`DIVIDEND` / `RIGHT_ISSUE`（provider 字面量归一化：
  cash_dividend/分红/派息 → DIVIDEND；rights_issue/配股 → RIGHT_ISSUE；未知值
  原样大写进入精确比较，fail-closed）；
- **dividend 与 right-issue 是两条独立事件流**：provider 增
  `get_right_issue_exchange`（capability corporate_action →
  InfoData.get_right_issue）；CA 域 fetch = calendar + status + dividend +
  **right issue** + adj + kline（六 exchange 全入 bundle）；
- Golden case 用 `expected_fields["event_type"]` 声明期望类型（载体是
  expected_fields，天然进入 semantic hash，v3 数据无需重封）；校验 = 精确
  (symbol, EX_DATE, **type**) 三元组——DIVIDEND 记录**永不**替代 RIGHT_ISSUE
  期望（反之亦然），不匹配 → `VALIDATED_FAIL(EVENT_TYPE_MISMATCH)`；
- 未声明类型的 legacy case 仍按精确日期校验（无回归）；
- `event_type` 是验证器元键：status 行字段比对前剥离。

## 5. B5/B6 载荷形状（P0-05）

- `_flat_values(payload)`：标量列表 / 单列 frame → 纯值列表；多列载荷
  **fail loud**（ValueError），杜绝旧行为把 row dict 强转成
  `"{'value': '600519.SH'}"` 垃圾字符串后静默"通过"；
- `_rows_of` 修正 polars 优先级（polars 的无参 `to_dict()` 返回
  {列: Series}，`list()` 之是列名——旧路径的静默垃圾行）；
- B5/B6 的 code_list 消费全部走 `_flat_values`。

## 6. Raw Commit Recovery（CR-1.2.1，P1，方案 A）

中断的多文件提交可能留下 **orphan payload**（字节在盘、meta 锚缺失）：

- **same-request retry 且字节一致** → 提交恢复（补落 meta，idempotent）；
- **retry 字节不同** → orphan 移入 `.quarantine/`（可取证、永不冒充有效证据）
  且写入 BLOCK；
- partial orphan（多表只落了一半）同样隔离；
- `list_orphan_payloads(raw_root)` 巡检接口（健康存储返回空）；
- `_commit_files` 的 payload 落位对"已存在且字节一致"跳过（恢复语义）；
- fault-injection 测试覆盖：meta 写失败 → 无锚无残留、后续 retry 恢复；
  payload move 失败 → 无 meta 锚（meta 最后落盘语义保持）。

## 7. 测试与验证

- **502 tests / 0 failed**（461 → 502，+41）；ruff（含 format）/ mypy 全绿；
- dry-run 冒烟：34 exchanges（全 meta-anchored）+ 5 bundles，整 run 双向闭合
  零问题；right-issue 端点进 bundle；B5 symbol 提取无垃圾字符串。

## 后果

- 规则数据集与 golden truth 走完全同构的生命周期（immutable versions +
  ACTIVE + review + 绑定），P0-M-1B 的制度事实就绪路径与 truth 一致；
- CI 增加 `ruff format --check` 门（本批根因修复：此前 8 个提交 CI 全红均
  为 format 检查未过）；
- CR-2 将消费 raw exchange（meta-anchored）构建 provider-normalized 层。
