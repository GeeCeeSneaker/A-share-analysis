# A-share-analysis：PR #8.1 CLI 模式互斥与 Production Resume 诚实性收口要求

> Date: 2026-09-04  
> Upstream Reviewer baseline: `0774803829987207f6ad37d0b324136fb6f98a51`（PR #8 初审要求）  
> Reviewed developer HEAD: `3f25c093a74c4d3635a6609eec734282f225f10b`  
> Reviewed CI: GitHub Actions run `33877350670` / run 253 — Ubuntu 3.14、Windows 3.12、Windows 3.14 all SUCCESS；each leg `1422 passed`；Ruff / format / mypy / Spike / SDK-absent / DEVLOG / Management gates green。  
> Scope: **仅收口 formal CLI contract honesty / resume recovery；不重开 CR-6，不改变 Provider/Canonical/Feature/State 数据语义。**

---

## Current implementation update (2026-09-04)

> **Status**：VERIFIED (CI) / PENDING_REVIEW  
> **Chosen recovery model**：方案 A — replay-all recovery；本轮不新增 migration，不扩展 phase state machine。

当前实现已开始收口本文件提出的 P1：

- CLI 四种运行模式通过显式 mode-conflict 校验互斥；歧义命令在 SDK login、DB open、run mint 和 evidence write 之前 fail closed。
- Production `--resume` 只接受 replay-all；`--phase bN` 在任何副作用前拒绝。恢复创建 fresh unsealed `CaseCatalog`，不加载旧 partial catalog；成功的完整 B1-B7 replay 通过同一 run 目录覆盖 unsealed catalog，旧 raw/anchor 审计证据保留。
- `CLOSED` 表示 required phases 已执行完毕，semantic `VALIDATED_FAIL` 仍由 verdict 判为 `NO_GO`/blocking；只有 auth/account/framework fatal 进入 `FAILED`。
- focused tests 已覆盖 mode conflicts、partial catalog rebuild/replay-all、semantic CLOSED + verdict NO_GO，以及现有三平台回归；run 253 三平台 CI 已验证，当前实现状态转为 VERIFIED (CI)，等待人工 Reviewer 复审。

**CI verification record (2026-09-04)**

- GitHub Actions run `33877350670` / run `253` 在 Ubuntu 3.14、Windows 3.12、Windows 3.14 三矩阵全部成功；每腿 `1422 passed`，Ruff lint/format、mypy、Spike、SDK-absent、DEVLOG 和 Management gates 均通过。
- 该结果验证仓库内 CLI mode conflict、Production replay-all/fresh catalog、CLOSED 与 semantic FAIL 语义及现有回归；不等同于正式账号 identity/entitlement、真实 Production B1-B7、Golden/Data Sufficiency Matrix、verdict 或 Provider approval。
- `configs/production_account.yaml` 仍为空 profile，凭证、Token、host/port/raw profile 未写入仓库；PR #8 继续保持 DO NOT MERGE，等待人工复审。

## 0. Reviewer 结论

PR #8 初审提出的三个核心实现缺口现已关闭：

```text
PR8-P0-01 persistent anchored DuckDB wiring     VERIFIED / CLOSED
PR8-P0-02 formal as-of freeze / resume match    VERIFIED / CLOSED
PR8-P0-03 post-new_run terminalization          VERIFIED / CLOSED
```

当前实现已证明：

- Production / Trial 使用已迁移的持久 DuckDB connection；
- `ProbeContext` 所有 formal 路径都得到同一 `conn`，并继续经过 `AnchoredRawEvidenceWriter`；
- formal `:memory:` 被拒绝；
- 新 formal run 必须显式合法 `YYYYMMDD`；
- resume authoritative date 来自持久化 `SpikeRun.as_of_date`，显式日期不一致 fail closed；
- context construction / phase / catalog flush / anchor enrollment 等普通异常不会留下 RUNNING；
- persistent anchor reopen、日期冻结、context failure、anchor failure 等 focused tests 与三平台 CI 均已通过。

**因此不再重开上述三个 P0。**

但在最终 CLI contract 审核中发现两个此前测试矩阵未覆盖的新 P1 merge blockers，以及一处 Reviewer 自身的状态语义表述需要更正。PR #8 暂时继续 **DO NOT MERGE**，进入一个很窄的 PR #8.1 收口。

正式状态：

```text
CR-5 / ADR-025                         VERIFIED / CLOSED / FREEZE
CR-6 / ADR-026                         VERIFIED / CLOSED / FREEZE（不重开）
2020+ history contract                 VERIFIED / KEEP（不重开）
PR #8 original anchored-wiring P0s     VERIFIED / CLOSED
PR #8.1 CLI / resume honesty           VERIFIED (CI) / PENDING_REVIEW
Production P0-M-1B                     BLOCKED independently
AmazingData capability approval        BLOCKED independently
PR #8                                  DO NOT MERGE YET
```

---

## 1. P1-01 — 初审发现：CLI 运行模式不是互斥合同

当前 `scripts/spike/spike_runner.py` 分别声明：

```python
--dry-run
--production
--trial
--verdict
```

但四者不是 mutually-exclusive group，也没有显式冲突检查；控制流只是按：

```text
dry-run -> verdict -> production/trial
```

顺序解释。

因此以下歧义命令不会 fail closed：

```text
--production --trial
--dry-run --production
--verdict --production --run-id <id>
```

例如 `--production --trial` 会被当前表达式：

```python
run_kind = RunKind.PRODUCTION if args.production else RunKind.TRIAL
```

静默解释为 Production；`--dry-run --production` 则会优先执行 dry-run。

正式取证 CLI 不应该替 operator 猜模式。命令模式是 run identity / evidence namespace 的一部分，歧义必须在登录、DB open、run mint、evidence write 之前拒绝。

### Required closure

优先使用 `argparse.add_mutually_exclusive_group()` 或等价显式验证，使以下模式最多只能选择一个：

```text
DRY_RUN
PRODUCTION
TRIAL
VERDICT
```

并满足：

1. 任意双模式/多模式组合 exit non-zero；
2. zero SDK login / zero DB mutation / zero SpikeRun / zero evidence；
3. 错误信息明确指出 mode conflict；
4. 不得通过“固定优先级”静默选择某一种模式；
5. runbook / module usage 与真实 parser 同步。

---

## 2. P1-02 — 初审发现：Production `--resume` 存在两套冲突语义

当前代码与文档存在以下冲突：

### 2.1 module usage / parser 默认语义

模块顶部示例：

```text
--production --resume --run-id <id>
```

而 `--phase` 默认是 `all`，因此该命令会重新进入全部 B1-B7。

### 2.2 runbook 语义

当前 `docs/runbook/run_spike.md` 示例却是：

```text
--production --resume --run-id <id> --phase b5
```

即把 resume 描述为“从某一 phase 继续”。

### 2.3 当前持久化模型并不支持诚实的任意 phase continuation

`CaseCatalog.add()` 只把 case 放入内存；正式 catalog 的 `flush()` 发生在 `_execute_run()` 的 phase execution 之后。换言之，一个真正的 hard process crash 可能已经留下 durable raw evidence / anchor rows，但此前 phase 的内存 case catalog 尚未形成完整持久 checkpoint。

同时 `_execute_run()` 对任何 `wanted` 列表执行完成后都会 `close_run()`。因此若一个 RUNNING Production run 用：

```text
--resume ... --phase b5
```

恢复，当前实现会在 b5 执行后尝试 CLOSED，而不是自动保证 b1-b7 的完整 catalog 已经重建并执行完毕。

这不会直接制造 GO（verdict 仍有完整性门），但会把正式 recovery path 变成“命令看似恢复成功，run 实际可能 CLOSED + SPIKE_INCOMPLETE”，并让同一个 CLI 同时声称 replay-all 与 continue-from-phase 两种语义。

### Required decision

PR #8.1 必须选择 **一种且只有一种** Production resume 合同，并在代码、tests、runbook、DEVLOG / Management 中一致落地。

#### 推荐方案 A — Replay-all recovery（本阶段优先）

当前没有独立 phase checkpoint ledger，因此最小、最诚实方案是：

```text
RUNNING Production run
  -> verify same account/code/env/config/sdk/runtime/as_of
  -> resume always rebuild/replay B1-B7 as one complete run
  -> build a fresh unsealed CaseCatalog for the RUNNING run
  -> overwrite/rebuild only the RUNNING run's unsealed catalog
  -> close only after complete B1-B7 returns
```

要求：

1. Production `--resume` 不接受 `--phase bN`；若显式 phase 不是 `all`，fail closed；
2. module usage 与 runbook 都只展示 replay-all resume；
3. RUNNING run 上已有的 partial/unsealed catalog 不得通过 `load()+rerun all` 导致 duplicate case；必须有明确的 rebuild/replace 规则；
4. 旧 raw evidence / anchor rows仍保留审计，不静默删除；新 replay 的 catalog 绑定本次真正使用的 evidence；
5. 完整 B1-B7 后才 CLOSED；
6. verdict 仍只消费 sealed CLOSED catalog。

这种方案不需要新增 schema，也不需要扩展 phase state machine，适合当前一次性 Production Spike。

#### 可接受方案 B — 真正的 checkpointed phase resume

如果开发者坚持 `--resume --phase b5` 这种 continuation，则必须先实现真实、原子、可验证的 phase checkpoint/progress：

- 每个已完成 phase 的 catalog/evidence membership 有持久且可验证的 checkpoint；
- resume 从 checkpoint **推导** remaining phases，而不是由 caller 随意声明；
- 已完成 phase 不重复、未完成 phase 不跳过；
- normal return 仍必须得到一个完整 terminal run；
- crash during checkpoint 不得产生“看起来完成但 membership 不完整”的状态。

该方案明显更复杂，除非已有实际需求，否则 Reviewer 不建议在 P0-M-1B 前引入。

---

## 3. Reviewer Correction — `CLOSED` 与 semantic FAIL 的状态语义

上一份 PR #8 Reviewer 要求 / 当前 runbook 中存在一句过强表述：

> “B2/B3/B4 的 blocking FAIL 必须使 run 进入终态 FAILED。”

本次对 frozen `SpikeRun` model 和 verdict contract 复核后，**该句由 Reviewer 正式更正**。

当前被冻结的模型明确规定：

```text
CLOSED = all requested/required phases executed; semantic cases may PASS or FAIL
FAILED = account/auth/framework fatal execution failure
ABORTED = operator interrupt
```

`VALIDATED_FAIL` 是否阻断能力批准，由 sealed CLOSED catalog + formal verdict 的 Core Gate 判定；semantic FAIL 不应被重新解释成 framework FAILED。

正确要求是：

```text
blocking semantic FAIL
  -> case remains VALIDATED_FAIL / equivalent=false
  -> run may correctly reach CLOSED if execution itself completed
  -> formal verdict must produce NO_GO / blocking outcome
  -> NEVER rewrite semantic FAIL into PASS
```

只有 auth/account fatal、anchor/framework failure 等执行失败才进入 `FAILED`。

### Required closure

1. 修正 `docs/runbook/run_spike.md` 中“blocking FAIL -> run FAILED”的表述；
2. 保持现有 `RunStatus` / `RunFailureReason` frozen semantics，不为本 PR 新增错误状态；
3. 增加/保留测试证明 CLOSED run 内存在 blocking `VALIDATED_FAIL` 时，formal verdict 仍 fail closed / NO_GO；
4. 不把 `CLOSED` 误写为“所有 case PASS”。

---

## 4. Mandatory focused tests

PR #8.1 至少补以下无需真实 SDK / network 的 focused evidence：

1. `--production --trial` mode conflict refused before login / DB / run creation；
2. `--dry-run --production` refused；
3. `--verdict --production --run-id ...` refused；
4. 其他双模式组合由参数化测试覆盖；
5. Production resume 合同只有一种：
   - 采用方案 A：resume 默认为/强制 replay all；`--phase b5` refused；
   - 采用方案 B：checkpoint-derived remaining phase tests 完整覆盖；
6. 方案 A 下构造 RUNNING run + partial/unsealed catalog，resume 不因 duplicate case 失败，最终 catalog 是完整的单一重建结果；
7. 方案 A 下 resume 完成后 B1-B7 均有完整 evidence/case membership，之后才 CLOSED；
8. resume identity/as-of mismatch regressions继续全绿；
9. blocking `VALIDATED_FAIL` + execution-complete -> CLOSED，但 verdict NO_GO / blocker；
10. full existing regression + Windows 3.12 / Windows 3.14 / Ubuntu 3.14 + Ruff / format / mypy / Spike / SDK-absent / DEVLOG / Management all green。

禁止用 wall-clock timing 作为 correctness proof。

---

## 5. Governance / scope

允许修改：

```text
scripts/spike/spike_runner.py
src/ashare_state/spike/runner.py          # only if replay/checkpoint helper needed
src/ashare_state/spike/catalog.py         # only if explicit RUNNING rebuild semantics needed
tests/* focused CLI/resume/verdict tests
docs/runbook/*
docs/DEVLOG.md                            # append-only
docs/project/DEVELOPMENT_MANAGEMENT.md
this PR #8.1 requirement status
```

不得修改：

```text
CR-5 Feature semantics
CR-6 State rules / identity / artifact / replay semantics
migration 024 or historical migrations
2020-01-01 history boundary
Provider capability APPROVED state
production_account.yaml with guessed identity
Golden truth / Data Sufficiency result to fabricate PASS
credentials / Token / host / port / raw profile
```

若方案 A 可完成，**不得新增 migration**。若选择方案 B 并认为必须持久化 phase checkpoint schema，先写设计理由并新增 025+ migration，禁止修改历史 migration。

每个 code/contract commit继续遵守 DEVLOG / Management 同步门；历史 DEVLOG append-only。

---

## 6. Exit gate

全部成立才允许 PR #8 merge：

```text
[x] original persistent anchor wiring remains correct
[x] original formal as-of freeze remains correct
[x] original terminalization boundary remains correct
[x] CLI modes are mutually exclusive / ambiguous commands fail before side effects
[x] Production resume has exactly one documented and implemented recovery model
[x] no caller-selected partial resume can accidentally mint an incomplete CLOSED production run
[x] partial/unsealed RUNNING catalog handling is deterministic and explicit
[x] CLOSED vs FAILED semantic wording corrected to frozen model truth
[x] blocking VALIDATED_FAIL cannot become GO
[x] focused tests above green without native SDK/network
[x] production_account.yaml remains empty until human profile freeze
[x] no capability approval / no fabricated Golden or Data Sufficiency PASS
[x] full three-platform CI + governance gates green
[x] no CR-5 / CR-6 semantic change
```

通过后 Reviewer 才可裁决：

```text
PR #8.1 CLI / resume honesty          VERIFIED / CLOSED
Production Runner infrastructure     VERIFIED / CLOSED / READY_FOR_FORMAL_ACCOUNT_VALIDATION
PR #8                                APPROVED_TO_MERGE
Production P0-M-1B                   remains BLOCKED until real formal evidence
AmazingData capability approval      remains BLOCKED until formal B1-B7 + sufficiency + verdict + human review
```

---

## 7. Owner-facing meaning

这轮不是在继续“优化框架”，而是在防止正式账号第一次取证时出现一种很难察觉的操作事故：**命令写得含糊，程序却替人猜了一个模式；或者恢复命令看起来成功，实际却把不完整 run 提前 CLOSED。**

现有 anchor / PIT / lifecycle 主体已经通过。PR #8.1 只把 CLI 入口做成真正 fail-closed，并把 resume 语义收成一个可解释、可测试、可审计的模型。完成后，仓库侧 Production runner 基础设施即可冻结，下一步才是正式账号 identity → online doctor → 单一 B1-B7 → Data Sufficiency → verdict → Provider approval 的外部证据链。
