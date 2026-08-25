# ADR-015: Corporate-Action Provider-Shape Validation Adapter（R4-A2.7 / CR-1.2.3）

- 状态：ACCEPTED
- 日期：2026-08-25
- 依据：审计 R4-A2.6/CR-1.2.2 复审（裁决 REOPENED）→ R4-A2.7 / CR-1.2.3 开发工作要求 P0-04（§5）；同批 P0-01/02/03 为 ADR-014 的 fail-closed 契约补全（见 §3）
- 关系：**amendment to ADR-013 §4**（CA 事件类型语义模型不变；provider payload 适配补全）
- 登记变更：DM-CR-20260825-011（管理总册 §61）

## 1. 问题（为什么要改）

Golden CA validator 此前消费 canonical-like 字段（SECURITY_CODE / EX_DATE /
EVENT_TYPE），而 AmazingData 官方文档（3.5.7.1 get_dividend / 3.5.7.2
get_right_issue）的真实字段是：

```text
get_dividend:    MARKET_CODE（证券代码）/ DATE_EX（除权除息日）
get_right_issue: MARKET_CODE / EX_DIVIDEND_DATE（除权日）
```

FakeTarget 也合成 canonical 字段——CI 证明的是 "validator works with
synthetic canonical rows"，而非 "real payload → validator"。真实账号上 symbol/
date 将永远不匹配。同时 EVENT_TYPE 并非 provider 字段（此前被伪造成 payload
列）。

## 2. 决策（怎么改）

在 **Spike semantic validation 边界**增加 ephemeral（in-memory）adapter：

```
raw ProviderExchange payload（provider 原生字段，落盘不可变）
    → _ca_provider_view(stream, rows, source_endpoint, raw_request_id)
      MARKET_CODE→security_code；DATE_EX/EX_DIVIDEND_DATE→ex_date；
      event_type = 端点身份派生（DIVIDEND / RIGHT_ISSUE，绝不来自 payload）
    → canonical validator view（含 source_endpoint/raw_request_id lineage）
    → Golden CA typed validator（v6，消费小写语义字段）
```

- `CA_PROVIDER_FIELD_CONTRACT` 显式声明两流的文档字段契约；
- 缺文档字段（MARKET_CODE / DATE_EX / EX_DIVIDEND_DATE）→
  `CAProviderShapeError` → route_all 转**结构化 `VALIDATED_FAIL
  (PROVIDER_SCHEMA)`**（fail loud，绝不静默空行集/别名猜测）；
- payload 中即使出现 EVENT_TYPE 列也**忽略**（类型只来自端点身份）；
- FakeTarget 改为 provider 原生字段——dry-run 与 real provider 走**同一**
  adapter，无 canonical 旁路；
- raw evidence 永远保持 provider 原生字段名（adapter 不回写、不持久化）。

## 3. 备选方案（为什么没选）

| 备选 | 不选的原因 |
|---|---|
| 修改 raw evidence 归一化字段 | 违反 Raw SoR 不可变原则——raw 必须保留 provider 原生字节/字段（审计 §5.4 明令禁止） |
| validator 直接理解 provider 字段（多别名探测） | "first plausible alias wins" 正是审计 §5.5 明令禁止的静默模式；字段契约会散落在 validator 内部，无显式 lineage |
| 启动 CR-2 Provider-Normalized 持久化层 | 审计 §5.4 明确本批只解决 Spike validator 边界；在 provider-shape/raw-evidence contract 稳定前启动 CR-2 会传播不稳定契约 |

## 4. 代价与收益

- **收益**：真实 provider payload（文档字段名）端到端可达 typed validator；
  dry-run/CI 覆盖与真实 schema 一致；EVENT_TYPE 伪造消除；缺字段 fail loud；
  lineage（endpoint/request_id）使每个语义行可追溯到精确的持久化 exchange。
- **代价**：CA 域 fetch 多一层 view 转换（可忽略的内存成本）；validator 字段
  访问从小写语义字段读取（测试已全部迁移）；若 SDK 实际字段与文档漂移，
  需在 P0-M-1B live evidence 中记录并版本化 schema mapping（契约集中于一处
  `CA_PROVIDER_FIELD_CONTRACT`，漂移影响面最小）。

## 5. 同批的 ADR-014 契约补全（P0-01/02/03）

审计复核确认三处实现偏离 ADR-014 已声明的契约，本批补全（详见 DM-CR-008/
009/010）：

1. **Bound pre-access confinement**：`load_bound_rule_book` 的 root 曾按
   `dataset_files[0]` 探测（fs probe 先于 confinement）——改为参数**确定性**
   root + 全文件 confinement 先于任何存在性/读取（FsSpy 测试证明零越界访问）；
2. **Raw evidence identity**：完整幂等重试返回的 hash 曾取自未持久化的新
   serialization（ingested_at 差异）——改为**读回磁盘 bytes** 计算
   evidence_hash（fresh commit 断言 persisted==intended）；
3. **Required coherence**：source_version / dataset_version 曾是"填了才比较"
   的可选语义——改为 manifest 必填非空 + 无条件精确比较；provenance_complete
   纳入 dataset_version + source_version；bound replay 复验 source_version/
   review_status。
