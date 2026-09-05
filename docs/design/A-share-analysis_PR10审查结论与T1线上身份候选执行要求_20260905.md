# A-share-analysis — PR #10 审查结论与 T1 线上身份候选执行要求

> Date: 2026-09-05  
> Reviewer baseline before PR #10: `c22a7111cda3ba9c86ca17aec4cfd85a2ee1955a`  
> PR #10 final head: `ebdd1ffb24020b67d6a44df3a068c0ced90286b1`  
> PR #10 CI: `33940091552` — Ubuntu 3.14 / Windows 3.12 / Windows 3.14 SUCCESS  
> PR #10 merge commit / current reviewed main baseline: `37aff08811c53ad8eedec7f8f2b17b215ede0396`  
> Scope: only post-PR #9 production-account identity qualification. Formal B1-B7, Data Sufficiency, Provider approval and backfill remain blocked.

---

## 1. Reviewer verdict

PR #10 is **ACCEPTED / MERGED AS A BLOCKED-PREFLIGHT GOVERNANCE RECORD**.

It records a truthful state:

```text
PR #9 identity contract             VERIFIED / CLOSED / MERGED
PR #10 blocked preflight record     ACCEPTED / MERGED
Offline SDK/runtime preflight       VERIFIED
Controlled online bootstrap (T1)    NOT COMPLETED
Current online status                NOT_TESTABLE_ACCOUNT / STOPPED BEFORE LOGIN
Human identity confirmation (T2)    BLOCKED
Production identity freeze (T3)     BLOCKED
Formal Production B1-B7             BLOCKED
Data Sufficiency Matrix              BLOCKED
Provider capability approval         BLOCKED
2020+ backfill                       BLOCKED
```

`NOT_TESTABLE_ACCOUNT` is not a failure of the identity contract and is not evidence of a Production account. It means the online path correctly stopped because the controlled Windows environment did not yet contain locally injected credentials.

No further review value is gained by submitting another documentation-only preflight that repeats the same state.

---

## 2. Next mandatory task — T1 controlled online bootstrap

The next meaningful update must attempt the real T1 entry point on the controlled Windows host with the official AmazingData/TGW SDK already verified locally.

Use only the repository entry point:

```text
uv run python scripts/spike/production_account_bootstrap.py
```

or, if the operator needs a local output file for inspection:

```text
uv run python scripts/spike/production_account_bootstrap.py --output <local-ignored-path>
```

Credentials must be injected **only** through the local process environment or an untracked local `.env` file. `.gitignore` already excludes `.env`, `*.token`, and `*.secret`.

Required local-only variables:

```text
TGW_USERNAME
TGW_PASSWORD
TGW_SERVER_VIP
TGW_SERVER_PORT
```

Never pass credentials, Token, host, port or account identifiers as CLI arguments. Never commit `.env` or any raw SDK output.

---

## 3. T1 acceptance gate

T1 can advance to T2 only when the bootstrap safe projection simultaneously shows all of the following:

```text
sdk_state == SDK_INSTALLED
runtime_verdict == RUNTIME_ACTUAL_LOAD_VERIFIED   # preferred formal evidence
AUTHENTICATED == YES
QUERY_READY == YES
ACCOUNT_PROFILE.profile_parsed == true
ACCOUNT_PROFILE.entitlement_verified == true
ACCOUNT_PROFILE.account_profile_id matches exactly UNKNOWN_[0-9a-f]{12}
ACCOUNT_PROFILE.profile_kind == UNKNOWN
ACCOUNT_PROFILE.permission_codes is non-empty safe numeric entitlement projection
production_identity_status == NOT_FROZEN
bootstrap_status == IDENTITY_CANDIDATE
config_written == false
human_confirmation_required == true
```

The exact `UNKNOWN_<12 lowercase hex>` value is the only candidate that may be presented for T2 review.

The following are explicit stop conditions and must **not** be upgraded or normalized into success:

```text
TRIAL_ACCOUNT_NOT_FREEZABLE
NOT_TESTABLE_ACCOUNT
NOT_TESTABLE_SDK
NOT_TESTABLE_PROFILE
NOT_TESTABLE_ENTITLEMENT
NOT_QUERY_READY
ERROR
FROZEN_IDENTITY_MATCH_REQUIRES_REVIEW   # unexpected at T1 while config is empty
```

If any stop condition occurs, record only the sanitized status and safe projection needed to explain the blocker. Do not attempt identity freeze, B1-B7 or fallback-to-Trial semantics.

---

## 4. Evidence allowed back into GitHub

The T1 PR may contain only the script's scrubbed/allowlisted projection and governance text derived from it.

Allowed evidence fields include:

```text
checked_at
platform
PYTHON_VERSION
SDK_ABI
sdk_state
AMAZINGDATA_PACKAGE_VERSION
PYTHON_TGW_PACKAGE_VERSION
TGW_RUNTIME_REPORTED_VERSION
runtime_verdict
NETWORK_REACHABLE
AUTHENTICATED
QUERY_READY
ACCOUNT_PROFILE.account_profile_id       # scrubbed generated id only
ACCOUNT_PROFILE.profile_kind
ACCOUNT_PROFILE.profile_parsed
ACCOUNT_PROFILE.entitlement_verified
ACCOUNT_PROFILE.permission_codes          # numeric safe projection only
ACCOUNT_PROFILE.subscribe_limit
ACCOUNT_PROFILE.weekly_flow_limit
ACCOUNT_PROFILE.used_week_flow
production_identity_status
bootstrap_status
config_written
human_confirmation_required
sdk_stderr_observed
```

Forbidden in GitHub, comments, screenshots, artifacts and logs:

```text
TGW_USERNAME
TGW_PASSWORD
Token / secret / credential material
real host / IP / port
raw login profile
raw SDK stdout/stderr
raw exception text containing provider/session/account details
local .env
SDK package binaries / wheels
```

If there is any uncertainty that a field is safe, omit it and report only the status code.

---

## 5. Required T1 handoff behavior

When a valid `IDENTITY_CANDIDATE` is produced:

1. Stop the workflow immediately after safe projection.
2. Keep `configs/production_account.yaml` unchanged and empty.
3. Open/update a focused T1 evidence PR containing only scrubbed facts.
4. State explicitly that the operator locally verified the run used the intended formal project account, without publishing the raw account name/credential/endpoint.
5. Wait for Owner/Reviewer T2 human confirmation of the scrubbed candidate.
6. Do not combine T1 evidence with the production identity freeze commit.

Only after T2 confirmation may a separate T3 governance PR set exactly:

```yaml
production_account_profile_id: "<confirmed UNKNOWN_12hex>"
confirmed_at: "<timezone-aware ISO-8601>"
confirmed_by: "<safe human/operator marker>"
```

That T3 PR must pass the full repository CI and receive Reviewer closure before formal Production B1-B7 is authorized.

---

## 6. Scope freeze until T1/T2/T3 close

Do not start any of the following in parallel:

```text
Formal Production B1-B7
Data Sufficiency Matrix execution
AmazingData GO / CONDITIONAL GO / NO-GO verdict
2020-01-01 -> current backfill
CR-7 or new data-domain expansion
strategy / backtest / portfolio / trading work
provider fallback or Trial-to-Production upgrade logic
```

The authoritative sequence remains:

```text
T1 controlled online bootstrap
-> T2 human-confirm scrubbed identity
-> T3 separate identity-freeze PR + full CI + Reviewer merge
-> one governed Production B1-B7 run
-> verdict + Data Sufficiency Matrix
-> Reviewer provider capability decision
-> 2020+ backfill and platform acceptance
```

---

## 7. Next review trigger

The next repository update is reviewable as meaningful progress when it contains either:

- a real scrubbed T1 online result; or
- a new concrete external blocker discovered after credentials were safely injected and login was actually attempted.

Do not create another PR that merely repeats `NOT_TESTABLE_ACCOUNT` because credentials were never provided locally.
