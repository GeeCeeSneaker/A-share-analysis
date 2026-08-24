# ADR-010: Raw Evidence Model（显式 ProviderExchange → RawWriter → Evidence Bundle）

- 状态：ACCEPTED
- 日期：2026-08-24
- 依据：审计 R4-A2.2 复审（裁决 REOPENED）→ R4-A2.3/CR-1.1 开发工作要求（P0-01/P0-02/P0-04），§3-§6
- 影响契约：§13 Raw Writer、§43（audit 43 exchange 契约）、SpikeCase evidence model —— C2 级变化（正式 evidence model 变更，按管理总册 C2 流程登记：DM-CR-20260824-006）

## 背景

CR-1 已引入 ProviderExchange（1 次真实 SDK 调用 = 1 个 request_id = 1 个 RawEnvelope = ≤1 个 payload）与 RawWriter。但复审发现运行时链路不完整：

1. Spike 探针实际消费的是 payload 便捷方法，失败时的 envelope 依赖 `provider.last_envelopes` 反查（共享状态，运行时正确性路径禁止）；
2. RawWriter 尚未真正接入 spike 运行时——正式 provider 证据链仍是 `payload → RunStore.write_evidence(JSON)`；
3. 金价路由（B4）的验证数据与 evidence 不是同一次 Provider Exchange（`lambda: None` 伪调用）。

## 决策

### 1. 运行时证据链（唯一正式路径）

```
target.*_exchange()        # 显式取得 ProviderExchange（成功或失败）
    → RawWriter.write(exchange)
        成功: dataset 目录下 <request_id>.parquet + <request_id>.meta.json
        失败: envelope-only <request_id>.meta.json（请求审计记录永不丢失）
    → RawWriteResult(evidence_uri, evidence_hash, ...)
    → SpikeCase.evidence_ref / evidence_hash
```

- `ProbeExecutor.call(fn)` 的 `fn` 必须返回 ProviderExchange（返回其它对象直接 TypeError，fail loud）；
- 失败的 exchange 是一等对象：`ProviderError.exchange` 携带错误 envelope（由 `call_exchange` 附加），调用方不依赖任何共享状态即可获得 request_id / envelope / attempt_count / error_class / requested_at / received_at；
- `provider.last_envelopes` 降级为 diagnostic-only（AST 级测试强制 probes/golden_router/runner 不得访问）；
- 未经真实 SDK 调用的治理拒绝（如 capability gate）用 `synthetic_failure_exchange` 诚实记录（新 request_id，不冒充 SDK exchange）。

### 2. RawWriter 载荷形状（P0-03）

必须支持：`list[dict]`、`dict[str, list[dict]]`、DataFrame（polars/pandas 鸭子类型）、`dict[str, DataFrame]`、`pyarrow.Table`、标量列表（如交易日历）。

- dict-of-tables 采用方案 A：每个逻辑表独立 Parquet（`<request_id>/<table>.parquet`），meta 记录每表 hash/schema/行数；
- "取 dict 第一个 value"被禁止——混合/不支持形状抛 `RawWriterError`；
- `write(exchange)` 断言 `exchange.request_id == envelope.request_id`；provider/dataset 以 envelope 为准，外部传值冲突即 BLOCK；
- 单表 content_hash = payload bytes sha256（保持经典语义）；多表为联合 hash；evidence_uri/evidence_hash 指向 case 实际绑定的证据文件（单表=parquet，多表/失败=meta.json）。

### 3. 金价路由 Evidence Bundle（P0-04）

每个 domain fetch 的所有 exchange 先经 RawWriter 持久化，DomainData 从这些**精确 payload** 构建；随后写 bundle manifest（`raw/bundles/<domain>-<id>.json`），列出该 domain 全部 exchange 的 evidence_ref/content_hash/request_id。

- 该 domain 的所有 SpikeCase 绑定 bundle（evidence_ref=bundle 路径，evidence_hash=bundle bytes hash）；
- 多端点 lineage（如 LIMIT 域的 status + hist master + calendar）在一个 bundle 内闭合；
- `verify_evidence_closure` 对 bundle 递归复验：bundle hash + 其列出的每个 raw artifact 存在且 hash 匹配；
- domain fetch 失败：失败 exchange（envelope-only）也进入 bundle，全部 case 按错误类别结构化（NOT_TESTABLE_PERMISSION / NOT_TESTABLE_ACCOUNT / VALIDATED_FAIL / MISSING）。

### 4. 兼容性

- `RunStore.write_evidence`（JSON）保留为测试/旧数据兼容 API，但**不再是正式 provider 证据链**；SpikeCase.evidence_type 从 `RAW_JSON` 变为 `RAW_PARQUET`；
- RawWriter 旧入口 `write_success/write_failure` 保留为兼容包装，内部统一走 `write(exchange)`。

## 后果

- dry-run（FakeTarget 产出真实 ProviderExchange）与 formal run 走**同一条**证据管线，框架自检覆盖审计闭环；
- evidence closure 校验的字节封闭性从单文件扩展到 bundle 递归；
- 审计可以对任意 case 追溯：bundle → 每个 raw exchange（request_id/endpoint/hash）→ meta.json（envelope 全字段，脱敏）。
