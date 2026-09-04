# A-share-analysis：PR #8.1 复审与 P0-AD-01.1 Production Bootstrap I/O 安全收口要求

> Date: 2026-09-04  
> Reviewer baseline: `a40a370f3da6defc57974d060a1b9cdb49df11d8`  
> Reviewed developer HEAD: `cb72b12e5b9c14dd69217647fa862a9db1435dc1`  
> Reviewed PR: #8 `codex/provider-governance-sync-20260904`  
> Reviewed CI: GitHub Actions run `33883710813` / run `262` — Ubuntu 3.14、Windows 3.12、Windows 3.14 all SUCCESS；Windows 3.14 实测 `1425 passed`；Ruff / format / mypy / Spike / SDK-absent / DEVLOG / Management gates green。  
> Scope: **关闭 PR #8.1 CLI/Resume honesty；仅收口新增 P0-AD-01 bootstrap 的 credential-bearing I/O safety，不重开 CR-5/CR-6，不改变 Provider/Canonical/Feature/State 数据语义。**

---

## 0. Reviewer verdict

本轮从 Reviewer baseline `a40a370f...` 到 developer HEAD `cb72b12e...` 共审查 12 个增量提交。结论分两部分：

```text
PR #8 original anchored-wiring P0s        VERIFIED / CLOSED
PR #8.1 CLI mode honesty                  VERIFIED / CLOSED
PR #8.1 Production replay-all resume      VERIFIED / CLOSED
PR #8.1 CLOSED vs semantic FAIL contract  VERIFIED / CLOSED
P0-AD-01 production bootstrap             PASS / KEEP architecture
P0-AD-01.1 bootstrap I/O safety           START / ACTIVE
PR #8                                     DO NOT MERGE YET
Production P0-M-1B controlled live run    BLOCKED_BY_P0-AD-01.1
AmazingData capability approval           BLOCKED independently
CR-5 / ADR-025                            VERIFIED / CLOSED / FREEZE
CR-6 / ADR-026                            VERIFIED / CLOSED / FREEZE
```

本轮**不重开** CR-5 / CR-6。剩余问题不涉及 Feature/State 公式、PIT、State identity、artifact/replay，也不需要 migration。

---

# 1. PR #8.1 — CLI mode / Production Resume honesty：VERIFIED / CLOSED

## 1.1 CLI 四模式互斥已真实落地

`scripts/spike/spike_runner.py` 当前在任何 dry-run / doctor target / DB / run side effect 之前构造：

```python
selected_modes = [
    flag
    for flag, enabled in (
        ("--dry-run", args.dry_run),
        ("--production", args.production),
        ("--trial", args.trial),
        ("--verdict", args.verdict),
    )
    if enabled
]
```

`len(selected_modes) > 1` 立即 non-zero fail closed，不再用固定控制流优先级猜 operator 意图。

Focused test 已参数化覆盖 6 组两两冲突，并把 `_make_real_target` / `run_dry_run` / `RunStore` 替换为 fail-on-call stub，证明冲突发生在正式副作用之前。

**Reviewer status：VERIFIED / CLOSED。**

## 1.2 Production resume 已统一为 replay-all

当前 `_resolve_wanted_phases()` 明确：

- 新 Production run 只允许完整 B1-B7；
- Production `--resume` 只允许 replay-all；
- `--production --resume ... --phase b5` 在登录之前拒绝；
- Trial 仍可保持其独立 phase selection 语义。

恢复路径使用 `_build_resume_catalog()` 创建 fresh unsealed catalog，不再 load crash 前 partial catalog，因此不会因为 replay-all 重放产生 duplicate case；旧 Raw / `meta_raw_evidence_anchor` 仍作为 append-only audit history 保留。

Focused test 已构造 RUNNING Production + stale partial catalog，验证 fresh catalog 从空开始、B1-B7 全部 replay、成功后最终 catalog 只包含重建后的完整 membership，之后 run 才进入 CLOSED。

**Reviewer status：VERIFIED / CLOSED。**

## 1.3 CLOSED 与 semantic FAIL 语义已纠正

当前 runbook 已恢复冻结模型：

```text
CLOSED  = required execution completed; semantic cases may PASS or FAIL
FAILED  = auth/account/framework fatal execution failure
ABORTED = operator interrupt
```

blocking `VALIDATED_FAIL` 不再被误写成 framework `FAILED`；formal verdict 仍负责把 CLOSED catalog 中的 blocking semantic fail 判为 `NO_GO` / blocker。

**Reviewer status：VERIFIED / CLOSED。**

## 1.4 PR #8.1 CI evidence

最终 docs-inclusive PR HEAD `cb72b12e...` 的 run `33883710813` / run `262` 三平台全部 SUCCESS。Windows 3.14 job 实测：

```text
1425 passed
Ruff lint                 SUCCESS
Ruff format               SUCCESS
mypy                      SUCCESS
Spike framework gates     SUCCESS
AmazingData SDK absent    SUCCESS
DEVLOG gate               SUCCESS
Management gate           SUCCESS
```

因此不再为 CLI/Resume honesty 创建 PR #8.2。

---

# 2. 新增 P0-AD-01 bootstrap：架构方向 PASS / KEEP

本轮额外新增 `scripts/spike/production_account_bootstrap.py`。Reviewer 接受其总体方向：

- credentials 只来自 environment / local `.env`，不接受 CLI 明文 credentials；
- 输出是 allowlisted scrubbed report，不直接输出 doctor raw report；
- `auth_error` / raw detail 等字段不进入 bootstrap report；
- `account_profile_id` 仍只是 scrubbed stable identity；
- `production_identity_status` 在 allowlist 未冻结时保持 `NOT_FROZEN`；
- 工具不会自动写 `configs/production_account.yaml`；
- `human_confirmation_required=True`；
- 建议输出目录 `data/spike/results/...` 被 `.gitignore` 的 `data/*` 覆盖；
- 当前 `configs/production_account.yaml` 仍为空 profile；
- bootstrap CI 不被解释成 B1-B7 / Data Sufficiency / capability approval。

这些设计均应保留。

但在真正把正式账号凭证交给这个入口之前，还存在两个必须 fail-closed 的 I/O contract blockers。

---

# 3. P0-AD-01.1-A — `--offline` 文档声称“不读取 credentials”，实现实际仍读取 `.env`

当前 parser help / Provider Verification 明确声称：

```text
--offline 只验证 SDK/runtime，不读取或使用账号凭证
```

但当前 `main()` 的实际顺序是：

```python
env = load_env(args.env_file)
credentials = None if args.offline else _credentials_from_env(env)
```

即使 `--offline`，仍然先打开并解析 `.env`，把 `TGW_USERNAME/TGW_PASSWORD/TGW_SERVER_VIP/TGW_SERVER_PORT` 读入当前进程，只是随后不传给 doctor。

当前 test 也只证明：

```text
offline -> run_doctor(credentials=None)
```

它没有证明：

```text
offline -> zero .env read / zero credential materialization
```

这不是数据正确性问题，但属于正式凭证工具的 contract honesty 问题。

## Required closure

`--offline` 必须在逻辑上完全绕过 credential loading：

推荐：

```python
if args.offline:
    env = {}
    credentials = None
else:
    env = load_env(args.env_file)
    credentials = _credentials_from_env(env)
```

或等价实现。

Mandatory test：

1. `--offline` 时 monkeypatch `load_env` 为 fail-on-call，命令仍成功进入 offline doctor；
2. `--offline --env-file <secret-file>` 不读取该文件；
3. offline report 不包含任何 account/profile truth，只能是 runtime/package facts；
4. 不得通过“读取但不使用”来声称“不读取”。

---

# 4. P0-AD-01.1-B — SDK stderr 当前仍直通 console，无法证明 bootstrap 的 “never printed” 安全声明

当前 bootstrap module docstring 声称：

```text
Credentials ... are never printed, persisted, or passed as CLI arguments.
```

而共享 `stdout_capture.py` 的冻结实现明确写明：

```text
stderr (SDK logs, MinLogLevel>=1) is NOT captured: it stays on console.
```

`AmazingDataSession.login()` / `logout()` 通过 `sdk_stdout_into()` 隔离 fd1；`run_doctor()` 的 query call 也只包 fd1。也就是说：

```text
SDK native stdout -> governed capture
SDK native stderr -> console passthrough
```

当前 bootstrap focused test 把 `run_doctor` 替换成纯 Python lambda，并且只断言 `capsys.readouterr().out` 和 output file 不含 secret；它没有模拟/证明 native fd2 / Python stderr 的敏感输出边界。

Reviewer 当前没有证据证明 AmazingData/tgw **一定会**把 credentials/Token 写入 stderr；但同样也没有证据可以支撑“never printed”这一强安全声明。在正式账号凭证进入受控 bootstrap 之前，这一边界必须变成可证明的 fail-closed contract。

## Required closure

正式 credential-bearing bootstrap 必须建立 **fd2 containment**。实现可选，但必须满足行为合同：

1. online bootstrap 调用 `run_doctor(credentials=...)` 期间，SDK / Python stderr 不得直接透传到 operator console；
2. raw stderr 不得写入 bootstrap JSON、DEVLOG、Git、PR、normal logs；
3. 若需要保留诊断，只允许把 stderr 归类为 scrubbed / allowlisted fact，例如 `sdk_stderr_observed=true`、错误类型等，不得持久化原文；
4. temp capture 若用于实现，必须是 ephemeral、退出自动删除；
5. 不得把 raw stderr 拼入 exception string 后再次 print；
6. 不能破坏现有 fd1 Token capture、re-entrant/parallel serialization 纪律。

优先方案：

- 在 bootstrap 外层对 `run_doctor()` 增加独立 OS-level fd2 临时 containment；或
- 把现有 SDK capture 抽象为受测试的 stdout+stderr formal I/O boundary，但不得为了本批重构无关 Provider 数据语义。

Mandatory adversarial tests：

1. monkeypatched doctor 使用 `os.write(2, b"MUST_NOT_APPEAR_ANYWHERE")`；bootstrap 返回后该 secret 不得出现在真实 fd2/stdout/output JSON；
2. doctor 同时 `print(secret, file=sys.stderr)`，同样不得外泄；
3. doctor 返回 raw dict 内含 `auth_error/detail/host/token/password` secret，allowlist projection 继续不输出；
4. error path / exception path 同样不得把 raw stderr 或 exception detail带到 console/report；
5. fd2 capture restore 必须经测试，bootstrap 后普通 stderr 能正常工作；
6. Windows 3.12 / 3.14 + Ubuntu 3.14 全部通过。

如果开发者能够以真实 SDK 官方合同 + 可重复测试证明 fd2 从不包含 credential/token/profile 敏感内容，也可提交证据请求改为 documented passthrough；在 Reviewer 接受前默认按 fail-closed 处理。

---

# 5. 非 blocker，但必须保持的边界

以下当前实现方向正确，不要在 P0-AD-01.1 中改坏：

```text
IDENTITY_CANDIDATE exit success != Provider APPROVED
production_identity_status=NOT_FROZEN until governed human allowlist commit
human_confirmation_required=True
configs/production_account.yaml remains empty before confirmation
permission/quota summary may be scrubbed evidence; no username/password/Token/host/port
bootstrap output under data/ remains local/ignored
no automatic allowlist write
no Production B1-B7 before identity freeze
no CR-5 / CR-6 semantic change
no migration change
```

`IDENTITY_CANDIDATE` 的 exit code 0 可理解为“候选身份采集成功”，但文档必须继续明确它**不表示** Production identity 已确认，也不表示 capability approval。

---

# 6. Mandatory P0-AD-01.1 exit gate

全部满足才允许 Reviewer 放行 PR #8：

```text
[x] PR #8.1 CLI modes mutually exclusive
[x] ambiguous CLI combinations have zero formal side effects
[x] Production resume = replay-all only
[x] fresh unsealed catalog rebuild avoids duplicate partial cases
[x] replay-all completes B1-B7 before CLOSED
[x] semantic VALIDATED_FAIL may coexist with CLOSED and verdict blocks it
[x] persistent anchor / frozen as-of / terminalization regressions remain green

[ ] --offline performs zero env/.env credential read
[ ] offline fail-on-load_env test green
[ ] online bootstrap contains fd2 / stderr during credential-bearing doctor call
[ ] injected native-style os.write(2, secret) cannot escape
[ ] Python stderr secret cannot escape
[ ] exception/error path cannot emit raw credential-bearing detail
[ ] fd2 capture restore proven
[ ] stdout Token capture / parallel capture regressions remain green
[ ] configs/production_account.yaml remains empty
[ ] no Provider approval / no fabricated Golden/Data Sufficiency truth
[ ] no CR-5 / CR-6 / migration semantic change
[ ] full 3-platform CI + governance gates green
[ ] DEVLOG append-only + DEVELOPMENT_MANAGEMENT sync
```

---

# 7. Merge / controlled-run order after closure

在 P0-AD-01.1 全部关闭后：

```text
P0-AD-01.1 VERIFIED / CLOSED
  -> PR #8 APPROVED_TO_MERGE
  -> merge to main
  -> use clean merged main for controlled online bootstrap
  -> human reviews scrubbed identity candidate
  -> separate governed commit freezes production_account_profile_id
  -> verify exact live identity match
  -> execute ONE Production B1-B7 run
  -> CLOSED run -> formal verdict
  -> Data Sufficiency Matrix
  -> Reviewer decides AmazingData capability approval
```

不得在本 PR 里根据 CI fake/injected evidence 自动填写 `production_account.yaml`。

---

## 7.1 Developer implementation status (2026-09-04)

当前开发提交仅收口 P0-AD-01.1 的两个 I/O blocker，最终状态等待三平台 CI：

- `--offline` 分支应完全绕过 `load_env` 和 production identity 读取，并把输出限制为 runtime/package facts。
- online `run_doctor` 调用应在 OS fd2 与 Python `sys.stderr` 两层 containment 内执行；只保留 scrubbed `sdk_stderr_observed`，不保留 stderr 原文。
- 对抗测试覆盖 env-file 绕过、native-style fd2、Python stderr、异常路径和 fd2 restore；不改变 Provider 数据语义、migration、CR-5 或 CR-6。
- 在 CI 终态前，P0-AD-01.1 状态保持 `IN_PROGRESS / CI_PENDING / PENDING_REVIEW`，不得据此放行合并或正式 Production B1-B7。

# 8. Developer handoff

下一批只做 **P0-AD-01.1**。不要继续扩展新的 Provider 接口、Data Sufficiency、CR-7、策略层或 State 语义。

实现完成后必须同步：

- 本文件 current status / evidence；
- `docs/DEVLOG.md`（append-only）；
- `docs/project/DEVELOPMENT_MANAGEMENT.md`；
- `docs/provider_verification/amazingdata.md` 中 offline / stderr 安全口径；
- PR #8 body；
- final 3-platform GitHub Actions run id / pass counts。

若 P0-AD-01.1 全部通过，下一次 Reviewer 目标是**直接关闭 PR #8 并批准合并**，不再新开 PR #8.2，除非发现新的真实 P0/P1 correctness/security blocker。
