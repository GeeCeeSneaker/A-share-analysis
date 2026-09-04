# A-share-analysis：PR #8 复审与 Production Runner Anchored Wiring 收口要求

> Date: 2026-09-04  
> Reviewed PR: #8 `codex/provider-governance-sync-20260904`  
> Reviewer baseline: `dda8c000d8585a95a66a91fbaa5072427053abb8`  
> Reviewed developer HEAD: `55ec75e856bef41a61fb5c407b4e6a683e88555e`  
> Reviewed CI: GitHub Actions run `33862579248` / run 244 — Ubuntu 3.14、Windows 3.12、Windows 3.14 all SUCCESS；Ruff / format / mypy / full pytest / Spike / SDK-absent green；Windows 3.14 DEVLOG / Management gates green。

## 1. Reviewer verdict

PR #8 的治理同步方向 **PASS / KEEP**：

- ADR-026 / ADR index 已正确同步到 CR-6 final closure；
- CR-6 work requirement 已正确记录 `VERIFIED / CLOSED / FREEZE`；
- `docs/provider_verification/amazingdata.md` 已把“历史试用账号证据”“正式账号 native SDK smoke”“正式 production identity/entitlement 尚未冻结”三者拆开；
- 2020+ history contract 没有被扩大或重写；
- native SDK smoke 没有被误写成 formal B1-B7 / Golden / Data Sufficiency / capability approval。

但 Reviewer 在核对 PR #8 新 runbook 与实际执行源码时发现：**正式 Production CLI 当前并不能按 runbook 所述安全执行**。因此正式状态为：

```text
CR-6 / ADR-026                         VERIFIED / CLOSED / FREEZE（不重开）
2020+ history contract                 VERIFIED / KEEP（不重开）
PR #8 governance truth sync            PASS / KEEP
Production Runner Anchored Wiring      REOPENED / ACTIVE
Production P0-M-1B                     BLOCKED
AmazingData capability approval        BLOCKED
PR #8                                  DO NOT MERGE YET
```

本轮只收口正式 Spike runner 的执行边界，不增加 Provider/Canonical/Feature/State 语义。

---

## 2. P0-01 — Production / Trial CLI 没有给 `ProbeContext` 传入 anchor ledger connection

当前 frozen evidence boundary 要求：

```text
ProviderExchange
  -> AnchoredRawEvidenceWriter
  -> RawWriter file commit
  -> meta_raw_evidence_anchor DuckDB ledger enrollment
  -> evidence ready
```

`src/ashare_state/spike/probes.py::ProbeContext.__init__` 当前签名为：

```python
ProbeContext(run, store, catalog, target, conn)
```

其中 `conn` 被 `AnchoredRawEvidenceWriter` 用来写 `meta_raw_evidence_anchor`。

`run_dry_run()` 已正确使用 migrated in-memory DuckDB 并通过 `_probe_context(..., conn)` 进入同一 anchored boundary；但是正式 CLI `scripts/spike/spike_runner.py` 的 Production / Trial 路径仍然调用旧签名：

```python
ctx = ProbeContext(run, store, catalog, target)
```

因此 runbook 新写的：

```powershell
uv run python scripts/spike/spike_runner.py --production --date <date>
```

当前会在真正 phases 开始前发生 constructor failure，而 CI 的 `--dry-run` 不覆盖该路径。

### Required closure

1. Formal `--production` / `--trial` 必须获得一个**持久化、已迁移**的 DuckDB connection，并传给 `ProbeContext`；
2. **Production / Trial 不得使用 `:memory:` anchor DB**。Dry-run 可继续使用 in-memory；
3. 优先复用项目已有正式 DB ownership：
   - `load_config().paths.duckdb_path`；
   - `DuckDBConnectionManager(...).owner("read_write")`；
   - `apply_migrations(...)` 在 formal probe 写入前确认 migration 017+ / current chain 可用；
4. DB connection 的生命周期至少覆盖整个 run 的正式 evidence 写入，并按项目 DuckDB 单进程独占纪律正常关闭；
5. 不得为解决该问题绕过 `AnchoredRawEvidenceWriter`，也不得退回直接 `RawWriter`；
6. 正式 run 结束后重新打开同一持久 DB，必须能查到本次 run 写入的 `meta_raw_evidence_anchor`，并且 `ingest_run_id == spike_run_id`。

如果开发者认为 formal Spike 应使用独立 run-scoped anchor DB，而不是平台主 DuckDB，必须先提交明确的设计理由、下游 normalization 如何定位同一 anchor ledger、迁移/备份/恢复语义；在 Reviewer 接受前不得自行改变 CR-2.4 的“ledger outside raw filesystem”权威边界。

---

## 3. P0-02 — Production / resume 的 as-of 日期当前可静默漂移

当前 CLI：

```python
parser.add_argument("--date", type=int, default=20260824)
```

新 run 把 `args.date` 写入 `SpikeRun.as_of_date`，但 resume 后仍然调用：

```python
_run_phases(ctx, wanted, args.date)
```

因此 runbook 当前给出的：

```powershell
uv run python scripts/spike/spike_runner.py \
  --production --resume --run-id <id> --phase b5
```

如果没有再次显式传 `--date`，就会用历史默认 `20260824` 跑 probe，而不是原 run 的 frozen `as_of_date`。这违反 single-run / single-as-of contract，也会污染 PIT / freshness / history evidence。

### Required closure

1. Production 新 run 不允许依赖历史硬编码默认日期；正式 run 必须显式得到一个合法 `YYYYMMDD` as-of；
2. `--resume` 时 authoritative as-of 必须来自已持久化的 `run.as_of_date`；
3. 如果 resume 同时显式提供 `--date`，必须 exact-match 原 run，否则 fail closed；
4. `_run_phases()` 必须只接收这个 resolved/frozen effective as-of；
5. runbook 示例同步真实行为；
6. 不得用 wall-clock today 隐式替代 as-of，也不得在一个 Production run 内跨日期执行不同 phase。

推荐把 argparse `--date` 默认改为 `None`，然后按模式解析；实现方式可不同，但上述行为是合同。

---

## 4. P0-03 — `RUNNING` lifecycle terminalization 没有覆盖 context/DB construction failure

当前正式 CLI 的顺序是：

```text
login
 -> new_run()        # 已持久化 RUNNING
 -> CaseCatalog
 -> ProbeContext(...)  # 当前就在这里因缺 conn 可失败
 -> try:
      _run_phases(...)
      close_run(...)
    except ...:
      fail/abort
```

也就是说，`ProbeContext` / anchor DB wiring 如果在 `new_run()` 之后失败，因为它位于 lifecycle try/except 之外，run 可以永久残留 `RUNNING`。

这直接违背既有 R3-P0-01：formal run 必须到达明确终态。

### Required closure

- 尽可能把 formal DB open / migration readiness 放在 `new_run()` **之前**，避免基础设施不可用时先铸造 RUNNING run；
- 一旦 `new_run()` 成功，后续 `ProbeContext` construction、phase setup、catalog flush 等可能失败的路径都必须落入 terminalization boundary；
- 可恢复硬进程 crash 留下 RUNNING 是 `--resume` 的合理场景；普通 Python exception / constructor failure 不应留下 RUNNING；
- injected context-construction failure 必须有测试证明 run 最终是 FAILED（或按冻结分类的其他明确 terminal status），而不是 RUNNING。

---

## 5. P1-01 — 当前 runbook 还有两个 contract-honesty 小问题

### 5.1 `provider_doctor.md` 表格写入了 literal `\n`

当前 branch 文件中存在：

```text
| RUNTIME_PACKAGE_VERIFIED | ... | 先在线运行 doctor |\n| RUNTIME_VERSION_MISMATCH | ...
```

应恢复为正常 Markdown 两行。

### 5.2 `doctor.py` module docstring 仍声称旧 verdict

runtime 行为已实现：

```text
RUNTIME_PACKAGE_VERIFIED
RUNTIME_ACTUAL_LOAD_VERIFIED
RUNTIME_VERSION_MISMATCH
RUNTIME_PATH_AMBIGUOUS
```

但 `src/ashare_state/providers/amazingdata/doctor.py` 顶部 docstring 仍写旧的 `RUNTIME_IDENTITY_VERIFIED`。既然 PR #8 的目标是 contract truth synchronization，应一并校正注释/文档，不改变 runtime 行为。

### 5.3 resume wording

runbook 应明确：`--resume` 只接受**仍处于 RUNNING 的原 run**。普通 Python failure 会 terminalize 为 FAILED，operator interrupt 会 ABORTED；这些终态不得 resume。只有例如硬进程中断导致 run 仍为 RUNNING 时，才进入 resume 语义。

---

## 6. Mandatory focused test matrix

本轮不允许只靠 `--dry-run` 或 CLI import test 宣称 formal runner 已验证。至少补以下 focused evidence：

1. **Formal CLI context wiring**：fake target/session + migrated temp DuckDB，走 Production/Trial CLI 的真实 `ProbeContext` construction，证明不会出现 missing `conn`；禁止真实 SDK/network；
2. **Persistent anchor**：formal fake exchange 写入后关闭 connection，再打开同一 DB，`lookup_raw_evidence_anchor(...)` 能命中 exact hash / request / `ingest_run_id`；
3. **No in-memory formal DB**：Production / Trial formal path 结构测试或注入测试证明不会选择 `:memory:`；
4. **Missing production date refused**：没有显式/解析后的 formal as-of 时 fail closed；
5. **Resume uses frozen date**：原 run `as_of_date=20260903`，resume 不传 date，B5/B6 接收到的必须仍是 `20260903`；
6. **Resume date mismatch refused**：原 run `20260903` + CLI `--date 20260904` -> fail closed、zero new phase evidence；
7. **Context construction failure terminalizes**：new_run 后注入 ProbeContext failure，run 不得残留 RUNNING；
8. **Closed/FAILED/ABORTED cannot resume**：保持现有 frozen lifecycle regression；
9. **Anchor failure fail closed**：anchor DB enrollment failure不能把 raw evidence 当 ready，也不能产生正常 CLOSED production run；
10. Full existing regression + Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff / format / mypy / Spike / SDK-absent / governance all green。

建议同时升级现有 `TestSpikeRunnerImports`：importable 只能证明语法/导入，不代表 formal CLI wiring 可运行。

---

## 7. Governance / scope

允许修改：

```text
scripts/spike/spike_runner.py
src/ashare_state/spike/runner.py        # only if a shared helper is the cleanest solution
src/ashare_state/providers/amazingdata/doctor.py  # docstring/comment truth only unless a real defect is found
tests/* focused formal CLI / anchor / resume tests
docs/runbook/*
docs/provider_verification/amazingdata.md if wording needs sync
docs/DEVLOG.md append-only
docs/project/DEVELOPMENT_MANAGEMENT.md
this work requirement / PR body status
```

不得修改：

```text
CR-5 Feature formulas / PIT semantics
CR-6 State rules / identity / artifacts
migration 017 or historical migrations
2020-01-01 history boundary
Provider capability APPROVED state
production_account.yaml with guessed identity
Golden truth to fabricate PASS
trading-rule review status to fabricate PASS
credentials / Token / host / port / raw local profile
```

如果 formal wiring 需要新的持久 schema，禁止改历史 migration；新增 migration 025+ 并先说明必要性。Reviewer 当前判断**不应需要新 schema**。

每个 code/contract commit 必须继续满足 DEVLOG / DEVELOPMENT_MANAGEMENT 同步门；历史 DEVLOG append-only。

---

## 8. Exit gate

全部成立才允许 PR #8 merge：

```text
[ ] formal Production/Trial path uses a migrated persistent DuckDB connection
[ ] ProbeContext receives conn on every formal path
[ ] formal evidence leaves durable meta_raw_evidence_anchor rows
[ ] no formal :memory: anchor ledger
[ ] production new run has explicit/frozen as-of
[ ] resume uses original run.as_of_date
[ ] resume date mismatch fails closed
[ ] post-new_run constructor/setup exception cannot leave ordinary RUNNING residue
[ ] focused formal CLI wiring tests green without real SDK/network
[ ] provider_doctor literal \n fixed
[ ] doctor verdict docstring matches runtime
[ ] runbook resume wording matches lifecycle
[ ] production_account.yaml remains empty until human profile freeze
[ ] no capability approval / no fabricated Golden or Data Sufficiency PASS
[ ] full three-platform CI + governance gates green
[ ] no CR-5/CR-6 semantic change
```

Then Reviewer may set:

```text
Production Runner Anchored Wiring  VERIFIED / CLOSED / FREEZE
PR #8                              APPROVED_TO_MERGE
```

After merge, the next external-evidence step is still:

```text
human-confirm scrubbed production identity + entitlement
 -> online provider-doctor
 -> one CLOSED PRODUCTION B1-B7 run
 -> --verdict --run-id
 -> Golden / Data Sufficiency review
 -> Reviewer capability verdict
```

Native SDK smoke remains useful connectivity evidence only and cannot skip any of these gates.
