# A-share-analysis：PR #9 首轮复审与 P0-M-1B.0.1 Positive Identity Contract Honesty 收口要求

> Date: 2026-09-05  
> Upstream Reviewer baseline: `4a5aedafbec2b128b1656d1e152a6938ae0c88c9`  
> Reviewed PR: #9 `P0-M-1B.0 harden positive production identity gates`  
> Reviewed developer HEAD: `cfc9243581fdc6f855b5a7e5972879e3d039247c`  
> Verified code CI: `66ab5ec7429b95d81142a4acf18ecf89f7daf8fd` -> GitHub Actions run `33899576457` / run 277, Ubuntu 3.14 + Windows 3.12 + Windows 3.14 SUCCESS, each leg `1449 passed`; Ruff / format / mypy / Spike / SDK-absent and applicable DEVLOG / Management gates green.  
> Current branch docs-only HEAD run 279 was still executing at review time.  
> Scope: only positive production identity / bootstrap candidate honesty. Do not start formal Production B1-B7 and do not approve Provider capability.

---

## 0. Reviewer conclusion

PR #9 的总体方向 **PASS / KEEP**：

- `configs/production_account.yaml` 仍为空；没有伪造 live identity；
- malformed / unconfirmed / extra-field / sensitive-marker config fail closed；
- auth / parsed-profile / entitlement / exact-match gate 得到强化；
- `RunKind.PRODUCTION` 不能单独升级 account identity；
- bootstrap 对 profile id / permission codes / quota 输出增加 allowlist projection；
- local offline preflight 只证明 SDK/runtime 与安全输出链，不是 live account truth；
- 没有越界执行 B1-B7、Data Sufficiency、verdict 或 Provider approval。

但本轮发现一个 **P0 merge blocker**，包含两个同源子问题：当前“scrubbed profile id”校验比真实 `AccountProfile` 生成合同宽，且 bootstrap 没有在 `IDENTITY_CANDIDATE` 前排除已知 Trial 身份。

因此正式状态：

```text
PR #8 / PR #8.1 / P0-AD-01(.1)     VERIFIED / CLOSED / MERGED
P0-M-1B.0 identity-gate architecture PASS / KEEP
P0-M-1B.0 local offline preflight     VERIFIED / KEEP
P0-M-1B.0.1 identity contract honesty START / ACTIVE
PR #9                                  DO NOT MERGE YET
production_account.yaml                EMPTY / KEEP
Formal Production B1-B7                BLOCKED
AmazingData Provider approval          BLOCKED
```

---

## 1. P0-01 — freezable identity shape must equal the current real generator contract

当前 `AccountProfile.from_scrubbed()` 的实际 identity 生成合同是：

```text
non-trial -> UNKNOWN_<12 lowercase hex>
trial     -> TRIAL_SIMULATION_<12 lowercase hex>
```

其中 digest 固定为 SHA-256 前 12 hex。

但 PR #9 新增：

```python
_PROFILE_ID_RE = re.compile(r"^[A-Z][A-Z0-9_-]{0,31}_[0-9a-f]{6,64}$")
```

它会把以下当前真实生成器永远不会产生、且部分属于历史废弃语义的值也视为 scrubbed-valid：

```text
ACCOUNT_abcdef123456       # legacy fail-open naming，必须拒绝
PRODUCTION_abcdef123456    # 当前 AccountProfile 从不直接生成 PRODUCTION id
OTHER_abcdef               # arbitrary kind
UNKNOWN_abcdef             # wrong digest length
UNKNOWN_<64 hex>           # wrong digest length
```

`_valid_frozen_identity()` 当前只额外排除 `TRIAL_* / FAKE_*`，因此 `ACCOUNT_*` / `PRODUCTION_*` / arbitrary kind 仍可被 config loader 接受。

这是 positive allowlist contract 的 honesty 问题：**冻结配置只能接受当前受控 live bootstrap / AccountProfile 真正能够产生的 identity，不应接受“看起来像 digest”的任意字符串。**

### Required closure

优先拆成两个显式 predicate：

```text
is_generated_scrubbed_profile_id
  = UNKNOWN_[0-9a-f]{12}
    OR TRIAL_SIMULATION_[0-9a-f]{12}

is_freezable_production_candidate_id
  = UNKNOWN_[0-9a-f]{12} ONLY
```

命名可不同，但语义必须等价。

要求：

1. bootstrap safe projection 可以保留真实 generated Trial id，以便明确诊断其为 Trial；
2. frozen `production_account.yaml` 只能接受 freezable non-trial candidate：当前即 `UNKNOWN_<12hex>`；
3. 必须拒绝 legacy `ACCOUNT_*`、伪造 `PRODUCTION_*`、`FAKE_*`、任意其他 kind；
4. digest 长度必须与当前生成器一致为 12，不得使用 6..64 宽泛范围；
5. future identity-version 变化必须作为显式 contract/version change，不得提前用宽 regex 静默兼容。

---

## 2. P0-02 — known Trial account must never become `IDENTITY_CANDIDATE`

当前 bootstrap 流程：

```text
profile id scrubbed-valid
+ AUTHENTICATED=YES
+ entitlement_verified
+ QUERY_READY=YES
+ not already frozen
=> IDENTITY_CANDIDATE
```

但这个判断没有检查 `profile_kind == TRIAL`。

因此一个真实：

```text
TRIAL_SIMULATION_<12hex>
```

只要 login / PermissionCode / query-ready 都成功，就会被输出：

```text
profile_kind = TRIAL
bootstrap_status = IDENTITY_CANDIDATE
```

这两个字段互相矛盾，也违反项目 truth ladder：Trial 只能产生 connectivity / trial evidence，绝不能成为 production identity freeze candidate。

虽然当前 `_valid_frozen_identity()` 后续会拒绝 `TRIAL_*`，但受控 bootstrap 本身必须在人工确认之前就诚实 fail closed，不能先把 Trial 标成 candidate 再依赖下一层兜底。

### Required closure

在 `IDENTITY_CANDIDATE` 判定前加入显式 freezability gate：

```text
if profile is generated Trial:
    bootstrap_status = TRIAL_ACCOUNT_NOT_FREEZABLE  # 或等价明确名称
    exit non-zero
    config_written = false
    never IDENTITY_CANDIDATE
```

要求：

1. known Trial 登录成功也不能 candidate；
2. legacy/arbitrary kind 即使满足宽字符串格式也不能 candidate；
3. only exact current non-trial generated id + runtime/auth/profile/entitlement/query gates 才能 `IDENTITY_CANDIDATE`；
4. frozen exact-match 路径仍可保持 `FROZEN_IDENTITY_MATCH_REQUIRES_REVIEW`；
5. 不允许 caller/run-kind/手工字段把 Trial/unknown legacy id 升级为 Production。

---

## 3. Mandatory focused tests

至少新增以下测试：

1. `is_generated_scrubbed_profile_id("UNKNOWN_<12hex>") == True`；
2. `is_generated_scrubbed_profile_id("TRIAL_SIMULATION_<12hex>") == True`；
3. freezable predicate 对 `UNKNOWN_<12hex>` 为 True；
4. freezable predicate 对 `TRIAL_SIMULATION_<12hex>` 为 False；
5. config loader rejects `ACCOUNT_<12hex>`；
6. config loader rejects `PRODUCTION_<12hex>`；
7. config loader rejects arbitrary `OTHER_<12hex>`；
8. rejects wrong digest lengths 6 / 11 / 13 / 64；
9. rejects uppercase hex / whitespace / malformed values；
10. online bootstrap with successful known Trial profile -> nonzero + explicit non-freezable status + never `IDENTITY_CANDIDATE`；
11. online bootstrap with legacy/arbitrary id -> nonzero + never candidate；
12. exact generated non-trial UNKNOWN id + valid auth/entitlement/query -> `IDENTITY_CANDIDATE`；
13. exact frozen UNKNOWN id + valid live profile -> `PRODUCTION` + review status path unchanged；
14. RunKind.PRODUCTION anti-upgrade regression remains green；
15. full existing regression + 3-platform CI + DEVLOG/Management gates green。

Tests use only test-only host/sentinel; never real endpoint or credential material.

---

## 4. Scope / governance

Allowed changes:

```text
src/ashare_state/providers/amazingdata/production_identity.py
scripts/spike/production_account_bootstrap.py
tests/integration/test_production_identity.py
tests/integration/test_production_account_bootstrap.py
docs/DEVLOG.md                         # append-only, same code commit
docs/project/DEVELOPMENT_MANAGEMENT.md # contract sync, same commit
docs/provider_verification/* / spike report only for truth sync
this reviewer requirement status
```

Forbidden in this closure:

```text
write non-empty configs/production_account.yaml
real credentials / token / host / port / raw profile
formal Production B1-B7
Data Sufficiency verdict
Provider APPROVED
CR-5 / CR-6 semantic changes
migration changes
new Provider operations
strategy / research scope
```

The current local offline bootstrap evidence remains valid as SDK/runtime preflight evidence only. Do not rerun live online bootstrap until this merge blocker is closed and PR #9 is merged to main.

---

## 5. Exit gate

P0-M-1B.0.1 is closed only when:

```text
[ ] generated scrubbed id shape exactly matches current AccountProfile generator
[ ] freezable identity is current non-trial generated id only
[ ] legacy ACCOUNT_* rejected
[ ] fake PRODUCTION_* / arbitrary kind rejected
[ ] wrong digest lengths rejected
[ ] known Trial online bootstrap can never IDENTITY_CANDIDATE
[ ] exact non-trial generated identity can candidate
[ ] exact frozen identity can match Production
[ ] config remains empty in repository
[ ] no live B1-B7 / approval scope
[ ] all existing identity/bootstrap regressions green
[ ] Windows 3.12 / Windows 3.14 / Ubuntu 3.14 all green
[ ] Ruff / format / mypy / Spike / SDK-absent green
[ ] Windows 3.14 DEVLOG + Management gates green
```

When all pass, Reviewer may:

```text
P0-M-1B.0.1 VERIFIED / CLOSED
P0-M-1B.0 repository gate READY_FOR_CONTROLLED_ONLINE_RUN
PR #9 APPROVED_TO_MERGE
```

Only after PR #9 merges may the controlled online bootstrap be run from clean main. The resulting scrubbed `UNKNOWN_<12hex>` candidate must then be human-reviewed before a separate governance commit freezes `configs/production_account.yaml`.
