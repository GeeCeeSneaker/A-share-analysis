# A-share-analysis：CR-2.3 复审与 CR-2.4 最终 Anchored Ingestion Boundary 收口要求

> **Review Date**：2026-09-01 14:26 +08:00  
> **Reviewed Repository HEAD**：`81d6b8d53a97cdcc7ee1cdfbd627d4dac2913e4d`  
> **Primary CR-2.3 Implementation**：`480dc7549bb512e9c187213e5010fab424248774`  
> **Reviewer Baseline / Requirements**：`323bbb51345d1fdca27b62f304727c8b0527f530`  
> **Frozen Baseline**：V1.3.2  
> **Review Verdict**：**REOPENED（仅剩 Anchored Ingestion Boundary wiring / enrollment correctness）**  
> **CR-2.3 已正确部分**：**Provider-owned operation spec / Raw anchor schema+runner verification / Output-set+Semantic seal PASS / FREEZE**  
> **Next Batch**：**CR-2.4 Final Anchored Raw Ingestion Boundary**  
> **CR-3**：**BLOCKED_BY_CR-2.4**  
> **Production P0-M-1B**：**BLOCKED independently**

---

# 0. Reviewer 裁决摘要

CR-2.3 对上一轮三个 P0 的设计方向均有实质实现。本轮正式确认以下内容 **PASS / FREEZE**，CR-2.4 不得推倒重写：

```text
PASS / FREEZE  ProviderOperationSpec typed immutable value
PASS / FREEZE  public generic call_exchange / _call_or_exchange 已撤销
PASS / FREEZE  private _execute_exchange(spec, fn, params)
PASS / FREEZE  endpoint / dataset / capability / surface / operation_id 全从 static spec 派生
PASS / FREEZE  daily_bar / index_daily 使用不同 operation spec
PASS / FREEZE  operation spec ↔ endpoint classification ↔ normalization registry structural guard 方向

PASS / FREEZE  migration 017 meta_raw_evidence_anchor schema
PASS / FREEZE  NormalizationRunner 在任何 meta parsing / routing / mapping 前查 anchor
PASS / FREEZE  RAW_ANCHOR_MISSING fail closed
PASS / FREEZE  RAW_ANCHOR_MISMATCH fail closed
PASS / FREEZE  legacy raw 不 auto-grandfather
PASS / FREEZE  evidence_conflict 降级为 diagnostic；normalization history 不再承担 trust root

PASS / FREEZE  normalized_output_set_hash ledger seal
PASS / FREEZE  normalized_semantic_hash ledger seal
PASS / FREEZE  manifest output_name exact-set == CURRENT spec.output_names
PASS / FREEZE  duplicate / missing / extra output 拒绝
PASS / FREEZE  output logical URI 由 ledger identity 重算
PASS / FREEZE  physical content hash / row count / schema hash 重算
PASS / FREEZE  physical output-set hash == ledger == manifest
PASS / FREEZE  physical normalized values semantic hash == ledger == manifest
PASS / FREEZE  pre-CR-2.3 missing output/semantic seal 的旧 run 不 healthy replay
PASS / FREEZE  CR-2.2 全历史 exact replay / full mapper fingerprint / quarantine seal
PASS / FREEZE  CR-2.1 atomic recoverable commit / no-silent-drop / provider-faithful / locator
```

Current HEAD CI run `33472968316` 为 **success**：Ubuntu Python 3.14 / Windows Python 3.12 / Windows Python 3.14，Ruff lint/format、Mypy、Pytest、Spike gates 均 green。

但是 Raw Trust Anchor 仍差最后一个 production correctness boundary：**anchor enrollment 机制存在，但当前正式 Raw evidence 写入链没有强制接线；测试通过依赖测试 helper 在 RawWriter 后手工调用 anchor recorder。** 同时 recorder 本身只 hash“调用时看到的 meta”，没有绑定 RawWriter 刚刚返回的 exact evidence hash，因此 write→anchor 之间仍有 TOCTOU / late-enrollment blessing 风险。

正式状态：

```text
CR-2      DONE / REOPENED
CR-2.1    DONE / REOPENED（机制冻结）
CR-2.2    DONE / REOPENED（机制冻结）
CR-2.3    DONE / REOPENED（3 个设计块中 2.5 个已冻结；仅 enrollment boundary 未闭环）
CR-2.4    START / ACTIVE NEXT
CR-3      BLOCKED_BY_CR-2.4
ADR-022   PROPOSED（不得提前 ACCEPTED）
```

不重开 R4-B2/B1/A3/A2/CR-1 冻结链，也不重写 CR-2.3 已通过的 operation spec / output semantic seal。

---

# 1. CR-2.3 已通过能力

## 1.1 Provider-Owned Operation Spec —— VERIFIED / FREEZE

当前 `operations.py` 定义 typed `ProviderOperationSpec`：

```text
operation_id
capability
endpoint
provider_dataset
normalization_surface
```

Provider facade 的公开 wrapper 绑定 static spec；generic executor 为 private `_execute_exchange(spec, fn, params)`。股票日线与指数日线共享 `MarketData.query_kline + daily_bar dataset`，但分别固定绑定 `DAILY_BAR_KLINE` / `INDEX_DAILY_KLINE`。

因此普通 production callable 不再允许自由拼装 endpoint / dataset / capability / surface。本方向满足上一轮 P0-01，冻结。

## 1.2 Raw Anchor 数据模型 + Normalization 消费逻辑 —— PASS / FREEZE

migration 017 新增 `meta_raw_evidence_anchor`，anchor row 保存 request 维度的 exact meta evidence hash；`NormalizationRunner.run()` 在 JSON parse、closure verification、routing、mapping 之前查 anchor：

```text
anchor missing  -> RAW_ANCHOR_MISSING / BLOCKED
hash mismatch   -> RAW_ANCHOR_MISMATCH / BLOCKED
hash exact      -> 才允许继续 parse/route/map
```

这正确解决了“Runner 自己第一次看到的 meta 不能成为 trust root”。该表结构和 runner verification 方向冻结。

## 1.3 Output Exact Set + Semantic Value Seal —— VERIFIED / FREEZE

当前 runner materialize `spec.output_names` 的完整集合，ledger 增加：

```text
normalized_output_set_hash
normalized_semantic_hash
```

Replay 会精确验证：

```text
manifest output_name exact set == current spec.output_names
no duplicate / missing / extra
logical URI == ledger identity 推导的 canonical URI
physical content/schema/row_count recompute
physical output-set hash == ledger == manifest
physical normalized values semantic hash == ledger == manifest
```

因此：

- `security_status_history` 少 `corporate_action` 一份不能 replay；
- 多塞一份 undeclared output 不能 replay；
- 换成同 schema/row-count 但值不同的 parquet，即使同步修改 content hash / manifest hash，也会被 semantic seal 拒绝。

本方向满足上一轮 P0-03，冻结。

---

# 2. Remaining P0：Raw Anchor 尚未形成 production-owned enrollment boundary

## 2.1 当前真实 formal evidence path 没有写 anchor

当前 `src/ashare_state/spike/probes.py::ProbeContext.evidence_from_exchange()` 是现有正式 provider evidence 路径之一：

```text
ProviderExchange
 -> self.raw_writer.write(exchange)
 -> 直接构造 evidence_meta 并返回
```

它没有调用 `record_raw_evidence_anchor()`。

而 CR-2.3 integration test helper `_persist_raw(...)` 为了让测试通过，显式执行：

```text
RawWriter.write_success / write_failure
then
record_raw_evidence_anchor(...)
```

即测试当前是在**模拟一个尚未接入 production 的 governed ingestion flow**。

直接后果：

```text
真实 Probe / Formal provider evidence
 -> RawWriter 成功
 -> 没有 meta_raw_evidence_anchor row
 -> NormalizationRunner
 -> RAW_ANCHOR_MISSING
```

因此当前代码会“安全地 fail closed”，但无法形成可用的 Raw -> Provider-Normalized 正式数据链。这是 production wiring blocker，不是测试覆盖率问题。

## 2.2 Anchor recorder 还存在 late-enrollment / TOCTOU blessing 风险

当前 `record_raw_evidence_anchor(conn, raw_root, provider, provider_dataset, request_id)`：

```text
找到当前 meta 文件
 -> read current bytes
 -> sha256(current bytes)
 -> 若没有旧 anchor，INSERT 这份 hash
```

它没有接收/验证 **RawWriter 刚刚返回的 `RawWriteResult.evidence_hash`**。

因此如果存在：

```text
RawWriter.write(exchange)
 -> 返回 evidence_hash = H1
 -> 在 anchor recorder 被调用前，meta bytes 被换成 H2
 -> record_raw_evidence_anchor() 第一次看到 H2
 -> anchor ledger 写入 H2
```

则 anchor 会把 late-tampered bytes 当成首次真值。

即使正常运行中窗口很短，也不能把 correctness 建立在“希望中间没人改文件”上。Trust anchor 必须绑定**RawWriter commit 当次已经产出的 exact evidence identity**，而不是由一个可以任意晚调用的 enrollment helper重新定义初始 hash。

## 2.3 当前 recorder 仍是普通可调用 enrollment primitive

`raw_anchor.py` 当前 `__all__` 公开 `record_raw_evidence_anchor`。真正的 production contract 应当是一个“Raw write + anchor enrollment”不可拆分的受治理边界；普通业务路径不应先自由写 Raw，再在任意时点决定是否/何时 enroll anchor。

不要求防 Python 私有符号 monkeypatch 或拥有 DB 管理权限的恶意 DBA；要求与 B1/B2 anti-bypass 一致：**正常 production callable 不提供绕开 anchored write 的路径。**

---

# 3. CR-2.4 Required Closure：Anchored Raw Ingestion Boundary

## 3.1 建立一个 production-owned anchored writer / persistence boundary

建议实现等价结构（命名可调整）：

```text
AnchoredRawEvidenceWriter / persist_exchange_with_anchor
  inputs:
    conn
    raw_root
    ProviderExchange
    ingest_run_id

  internally:
    RawWriter.write(exchange)
      -> RawWriteResult
    reread final meta bytes
    require sha256(final meta bytes) == RawWriteResult.evidence_hash
    require meta uri == RawWriteResult.evidence_uri/meta_uri
    require meta request/provider/dataset/operation_id/surface
            == exchange envelope / provider-owned operation identity
    insert immutable meta_raw_evidence_anchor
    return RawWriteResult + anchor
```

关键：anchor expected hash 来源是**本次 RawWriter commit 的 output identity**。最终 reread 是 verify-only；不能由 reread 的 bytes 在没有 RawWriteResult cross-binding 的情况下自行定义首次真值。

## 3.2 所有 production provider-evidence 写入必须切到 anchored boundary

至少更新现有：

```text
ProbeContext.evidence_from_exchange
failure_evidence -> evidence_from_exchange
formal gate / endpoint proof persistence paths（如存在直接 RawWriter.write）
其他 src/ 下 production provider RawWriter.write/write_success/write_failure 调用点
```

要求：

- production provider evidence 写入后必然有 anchor；
- SUCCESS exchange / ERROR exchange 都要 anchor；
- 不允许某条“正常正式入口”继续直接 RawWriter.write 后绕过 anchor；
- `NormalizationRunner` 仍只负责 lookup/verify anchor，不负责补建 anchor。

推荐 structural guard：扫描 `src/ashare_state` 中 RawWriter 的 write/write_success/write_failure 正式调用点，只允许 anchored boundary 内部（reader-only `RawWriter.read` 不受此限制）。Tests-only direct RawWriter 可保留用于 legacy/tamper 对抗场景。

## 3.3 Anchor enrollment 必须可恢复但不可 rebaseline

Failure sequence：

```text
RawWriter file-side commit 成功
anchor DB INSERT 暂时失败
```

必须：

- 本次 governed ingest 视为失败 / incomplete，不得继续宣称 evidence ready；
- Raw bytes 保留，仍没有 anchor，因此 Normalization fail closed；
- exact retry 同一 exchange / same bytes：RawWriter idempotent -> returned H1；anchor enrollment 成功 -> 正常闭合；
- retry 不得产生第二套不同 evidence identity。

若已存在 anchor H1：

```text
same bytes H1 -> idempotent
current meta H2 -> hard fail
```

anchor 永不 rebaseline。

## 3.4 Anchor record API 收口

推荐：

- 将 raw anchor INSERT primitive private/internal；
- 对 production 公布的是 anchored persistence boundary，而不是“给任意现有 request 建立首次 anchor”的普通 API；
- tests 如需制造 legacy/unanchored data，用 tests-only helper 或 private monkeypatch。

如果保留 public recorder，则必须要求 caller 提供不可伪造/不可自报的 `RawWriteResult`（或等价内部 capability token），并严格 cross-bind，不接受单纯 `request_id -> 现场 hash -> enroll`。

---

# 4. Mandatory Adversarial Tests

CR-2.4 至少增加：

```text
1. ProbeContext.evidence_from_exchange 成功后，anchor row 必然存在
2. Provider ERROR/failure evidence 落盘后，anchor row 也必然存在
3. production src structural guard：不得存在绕开 anchored boundary 的 RawWriter.write* provider-evidence 写入
4. RawWriter commit H1 -> 在 anchor enrollment 前篡改 meta 为 H2 -> enrollment HARD FAIL，不得 anchor H2
5. anchored boundary 中 anchor INSERT 注入失败 -> 整体 ingest 不宣称成功；Normalization RAW_ANCHOR_MISSING
6. 上述失败后 same exact evidence retry -> anchor 成功补齐；只产生一个 immutable anchor
7. 已有 H1 anchor，重复 same H1 -> idempotent
8. 已有 H1 anchor，尝试 H2 -> hard conflict / no rebaseline
9. anchored healthy raw -> NormalizationRunner SUCCESS/PARTIAL 正常工作
10. legacy direct RawWriter without anchor -> 继续 RAW_ANCHOR_MISSING fail closed（已有 CR-2.3 测试保留）
11. first-consume meta-only tamper -> anchor mismatch before route/map（已有测试保留）
12. operation_id / endpoint / surface cross-binding 与 exchange envelope 不一致 -> anchor enrollment BLOCK
13. CR-2.3 output exact-set / semantic tamper matrix全部保持 green
14. CR-2.2 historical exact replay / full mapper fingerprint / schema recheck保持 green
15. CR-2.1 atomic commit / quarantine seal / no-silent-drop保持 green
16. migration 017 from-zero + upgrade保持 green
17. Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green
```

---

# 5. CR-2.4 Scope Boundary

允许：

```text
raw anchor enrollment API / internal primitive
anchored raw evidence writer / persistence boundary
ProbeContext / formal persistence wiring
必要的 tests / governance docs / ADR-022 Amendment D
```

禁止：

```text
重写 ProviderOperationSpec
重写 NormalizationRunner anchor lookup semantics
重写 output-set / semantic seal
AvailabilityPolicy / SourcePolicy / Canonicalization
SnapshotBuilder / ReadModel
```

CR-3 仍未启动。

---

# 6. CR-2.4 Exit Gate

只有以下全部通过，才允许 CR-2 全链 CLOSED：

```text
[ ] anchored raw persistence 是正式 production 写入边界
[ ] formal/spike evidence 成功与失败路径均自动生成 anchor
[ ] RawWriter commit result evidence hash 与 anchor exact cross-binding
[ ] write→anchor 间 meta tamper 不可能被首次 enroll 为新真值
[ ] anchor enrollment failure fail closed 且 exact retry 可恢复
[ ] production normal callable 不存在 unanchored RawWriter write bypass
[ ] anchor 永不 rebaseline
[ ] existing CR-2.3 operation spec / output-set / semantic seal无 regression
[ ] existing CR-2.2 / 2.1 frozen contracts无 regression
[ ] migration 017 chain green
[ ] full CI green
```

全部通过后 Reviewer 下一轮直接：

```text
CR-2 / CR-2.1 / CR-2.2 / CR-2.3 / CR-2.4 -> VERIFIED / CLOSED / FREEZE
ADR-022 -> ACCEPTED
CR-3 AvailabilityPolicy + Canonicalizer -> START
Production P0-M-1B -> BLOCKED independently
```

Reviewer 应同时推送 CR-2 closure doc + **CR-3 详细开发工作要求**，不再扩张 CR-2 scope。

---

# 7. Governance

下一开发批次同步：

```text
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
docs/adr/ADR-022_provider_normalization_quarantine.md
本 Reviewer CR-2.4 requirement doc 的 implementation mapping
```

ADR-022 在 Reviewer 最终关闭 CR-2 前保持 `PROPOSED`。

---

# 8. 面向项目 Owner 的中文进度

当前不是“CR-2 又推倒了”。实际情况是：

```text
Provider 身份规则             ✅ 已锁死
Raw anchor 数据结构/校验      ✅ 已完成
标准化输出集合完整性          ✅ 已完成
标准化实际值 semantic seal    ✅ 已完成
历史 exact replay             ✅ 已完成
故障恢复 / quarantine         ✅ 已完成

最后剩余：
RawWriter 写完以后，
必须由同一个正式受治理流程
立即、强制、可验证地把这次写入的 exact hash 登记成 anchor。
```

也就是“保险柜和验钞机都装好了，现在只差把正式收款窗口强制接到验钞机上，不能让业务人员自己先收钱、以后再决定什么时候补登记”。

---

# 9. Implementation Mapping（开发方填写，2026-09-01）

## §3.1 AnchoredRawEvidenceWriter

| Requirement | Implementation | Tests |
|---|---|---|
| production-owned anchored writer | `raw_anchor.py::AnchoredRawEvidenceWriter.write_exchange(exchange)`（五步：RawWriter.write → verify-only reread → identity cross-binding → enroll → return） | `test_probe_context_success_enrolls_anchor` / `test_anchored_healthy_raw_normalizes_successfully` |
| reread == RawWriteResult.evidence_hash | TOCTOU verify-only 比对（hash 不等 → RawAnchorError HARD FAIL） | `test_toctou_tamper_between_commit_and_enrollment_fails`（commit 后 enrollment 前换 meta bytes → FAIL；零 anchor 行） |
| meta uri == commit uri | evidence_uri == meta_uri == canonical request-addressed uri 断言 | 同上路径（uri cross-binding 在 identity 检查内） |
| meta request/provider/dataset/operation_id/surface == envelope | `_ENVELOPE_IDENTITY_FIELDS` 六字段全比对（不一致 → BLOCK） | `test_meta_identity_tamper_blocks_enrollment`（monkeypatch `_meta_bytes` 伪造 endpoint → cross-binding FAIL；零 anchor） |
| insert immutable anchor keyed to commit identity | `_enroll_anchor(..., evidence_hash=result.evidence_hash)` | `test_probe_context_success_enrolls_anchor`（anchor.evidence_hash == meta["content_hash"]） |

## §3.2 Production 写入全部接线

| Requirement | Implementation | Tests |
|---|---|---|
| ProbeContext.evidence_from_exchange 生成 anchor | `ProbeContext.__init__(..., conn)`（必需参数）；`raw_writer` = AnchoredRawEvidenceWriter | `test_probe_context_success_enrolls_anchor` |
| failure_evidence 也 anchor | `failure_evidence` → 同一 `write_exchange` | `test_probe_context_failure_evidence_enrolls_anchor`（ERROR exchange → anchor + payload_kind=failure） |
| run_dry_run 走 production 写路径 | in-memory migrated DB（repo migrations 全链）供 ProbeContext | 既有 `test_dry_run_produces_all_phase_outputs` / `test_dry_run_includes_b1_phase` 回归（全 phase 绿） |
| 结构守卫：无 unanchored RawWriter write bypass | AST 扫描 src/：write/write_success/write_failure 调用点仅 raw_writer.py + raw_anchor.py 白名单 | `test_no_unanchored_raw_writer_write_in_production_src` |
| src/ 其他写入点 | 逐一核对：src/ 中 RawWriter 实例化仅 probes.py（已接线）+ normalization/runner.py（只读 reader） | 同上结构守卫 |

## §3.3 可恢复不可 rebaseline

| Requirement | Implementation | Tests |
|---|---|---|
| anchor INSERT 失败 → ingest 失败 + evidence 不 ready | write_exchange 直接传播异常 | `test_anchor_insert_failure_fails_ingest_then_exact_retry_recovers`（注入失败 → 无 anchor → Normalization RAW_ANCHOR_MISSING） |
| exact retry 恢复 + 单一 identity | RawWriter idempotent（same bytes ignoring ingested_at → evidence_hash = 首 commit H1）→ enrollment 成功 | 同上（retry → idempotent=True → 一行 anchor → anchor_hash == result.evidence_hash → Normalization SUCCESS） |
| 已有 H1 + same H1 → idempotent | `_enroll_anchor` lookup-first | `test_repeat_same_evidence_is_idempotent_one_anchor`（两次写 → 一行 anchor） |
| 已有 H1 + H2 → hard conflict | RawWriter 不可变写先行 + anchor CONFLICT | `test_different_bytes_same_request_hard_conflicts`（不同 payload → RawWriterError；anchor 仍仅 H1） |

## §3.4 API 收口

| Requirement | Implementation | Tests |
|---|---|---|
| INSERT primitive private | `_enroll_anchor`（evidence_hash 必填声明 commit identity；verify-only） | `test_public_recorder_api_is_closed`（`record_raw_evidence_anchor` 不在 `__all__`/无属性；公开面全非下划线） |
| public = anchored boundary + 只读 lookup | `__all__`：AnchoredRawEvidenceWriter / persist_exchange_with_anchor / lookup_raw_evidence_anchor / RawEvidenceAnchor / RawAnchorError | 同上 |
| tests legacy 夹具走私有 primitive | `_persist_raw` anchor 路径 + governed-reingest 测试改用 `_enroll_anchor` | 既有 anchor 测试矩阵回归全绿 |

## §4 对抗测试矩阵对照（17 项）

```text
[✓] 1  ProbeContext.evidence_from_exchange 成功后 anchor row 必然存在
[✓] 2  ERROR/failure evidence 落盘后 anchor row 必然存在
[✓] 3  结构守卫：无绕开 anchored boundary 的 RawWriter.write* 写入
[✓] 4  RawWriter commit H1 -> enrollment 前篡改 H2 -> HARD FAIL，不 anchor H2
[✓] 5  anchor INSERT 注入失败 -> ingest 不宣称成功；Normalization RAW_ANCHOR_MISSING
[✓] 6  同一 evidence exact retry -> anchor 补齐；仅一个 immutable anchor
[✓] 7  已有 H1，重复 same H1 -> idempotent
[✓] 8  已有 H1，尝试 H2 -> hard conflict / no rebaseline
[✓] 9  anchored healthy raw -> NormalizationRunner SUCCESS
[✓] 10 legacy direct RawWriter without anchor -> RAW_ANCHOR_MISSING（CR-2.3 回归保持）
[✓] 11 first-consume meta-only tamper -> anchor mismatch before route/map（CR-2.3 回归保持）
[✓] 12 operation_id/endpoint/surface 与 envelope 不一致 -> enrollment BLOCK
[✓] 13 CR-2.3 output exact-set / semantic tamper 矩阵保持 green
[✓] 14 CR-2.2 historical exact replay / full fingerprint / schema recheck 保持 green
[✓] 15 CR-2.1 atomic commit / quarantine seal / no-silent-drop 保持 green
[✓] 16 migration 017 from-zero + upgrade 保持 green
[✓] 17 Windows 3.12 / Windows 3.14 / Ubuntu 3.14 full CI green（run `33482144065`，implementation `3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc`，三腿 success + Windows 3.14 腿 DEVLOG/Management-doc gate success，2026-09-01 API positive confirmation）
```

## §6 Exit Gate 对照（11 项）

```text
[✓] anchored raw persistence 是正式 production 写入边界（AnchoredRawEvidenceWriter + 结构守卫）
[✓] formal/spike evidence 成功与失败路径均自动生成 anchor（ProbeContext 接线；run_dry_run 同路径）
[✓] RawWriter commit result evidence hash 与 anchor exact cross-binding（verify-only reread + enroll keyed to commit identity）
[✓] write→anchor 间 meta tamper 不可能被首次 enroll 为新真值（TOCTOU HARD FAIL 测试）
[✓] anchor enrollment failure fail closed 且 exact retry 可恢复（注入失败 + retry 测试）
[✓] production normal callable 不存在 unanchored RawWriter write bypass（AST 结构守卫 + ProbeContext conn 必需）
[✓] anchor 永不 rebaseline（same-H1 idempotent / H2 hard conflict 测试）
[✓] existing CR-2.3 operation spec / output-set / semantic seal 无 regression（104 项回归全绿）
[✓] existing CR-2.2 / 2.1 frozen contracts 无 regression（回归全绿）
[✓] migration 017 chain green（17 链 from-zero/upgrade/idempotent/tamper 回归）
[✓] full CI green（run `33482144065` 三腿 success，API positive confirmation）
```

## Verification Summary

- Local: **985 / 0**（975 → 985，+10：TestAnchoredIngestionBoundary 10 项；normalization 114 = 104 回归 + 10 新增；13 个 spike/formal-gate 测试文件 ProbeContext 接线后全绿）；ruff check / ruff format / mypy 全绿（63 文件零错）；CI 同款命令 `uv run pytest` 复验 985/0
- ADR-022 Amendment D（status 仍 PROPOSED）；无 schema 变更（复用 migration 017 anchor 表）；已冻结语义零重写（operation spec / runner anchor lookup / output-set semantic seal 均未改动）
- **Implementation SHA：`3bc5c53d2217f2b01d26766eabe470b7bcc4d5bc`；CI run `33482144065` 三腿 success**（Ubuntu 3.14 + Windows 3.12/3.14 各腿 Ruff lint / Ruff format / Mypy / Pytest / Spike gates / SDK-absent 全 success，Windows 3.14 腿 DEVLOG gate + Management-doc gate success；2026-09-01 API positive confirmation，一次通过零修复轮次）
- §4 矩阵 17 项 / §6 Exit Gate 11 项全过（CI 项据 API positive confirmation 关闭）；SHA 由 docs 回填 commit 补记（历史不改写——本 Mapping 一次写成后仅补记本节）
