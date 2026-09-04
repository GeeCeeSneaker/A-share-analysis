# A-share-analysis：PR #8 最终关闭与 P0-M-1B.0 受控正式账号身份冻结工作要求

> Date: 2026-09-05  
> Reviewer upstream baseline: `1cbff8ae82bc67cf0101c449ee080b5e28ccb782`  
> Approved PR #8 code/docs HEAD: `c62576e5cfd5512c6b5f156ebd3d14db01d6c3a5`  
> Final verification: GitHub Actions run `33891800441` / run 267 — Ubuntu py3.14, Windows py3.12, Windows py3.14 all SUCCESS; Windows py3.14 reports `1427 passed`; Ruff / format / mypy / Spike / SDK-absent / DEVLOG / Management gates green.  
> PR #8 merge commit: `74ae84e0e6950f7f7dc926d225be105fdb99279a`  

---

## 0. Reviewer final decision

PR #8 is **VERIFIED / CLOSED / MERGED**.

Formal status:

```text
CR-5 / ADR-025                         VERIFIED / CLOSED / FREEZE
CR-6 / ADR-026                         VERIFIED / CLOSED / FREEZE
2020+ history contract                 VERIFIED / KEEP
PR #8 anchored runner P0s              VERIFIED / CLOSED
PR #8.1 CLI / resume honesty           VERIFIED / CLOSED
P0-AD-01 bootstrap boundary            VERIFIED / CLOSED
P0-AD-01.1 bootstrap I/O safety        VERIFIED / CLOSED
PR #8                                  MERGED
AmazingData production identity        NOT YET FROZEN
Formal Production B1-B7                NOT YET EXECUTED
Data Sufficiency Matrix                NOT YET EXECUTED
Provider capability approval           BLOCKED
```

This merge does **not** approve AmazingData as a production provider. It only establishes a sufficiently controlled mechanism to begin formal production identity validation.

---

## 1. P0-AD-01.1 closure evidence

Reviewer independently verified the two previous blockers are closed.

### 1.1 Offline zero credential read

`production_account_bootstrap.py --offline` now branches before `load_env()` and calls doctor with `credentials=None` only. Offline report projects runtime/package facts only and does not inspect production identity/account profile.

Focused adversarial test fails immediately if `load_env()` or frozen production identity is touched in offline mode.

### 1.2 Online stderr containment

Credential-bearing bootstrap now executes doctor within `sdk_stderr_into()`:

- OS fd2/native writes are redirected to a temporary file;
- Python `sys.stderr` is redirected separately;
- raw stderr text is never returned in the bootstrap report;
- only boolean `sdk_stderr_observed` is retained;
- exception text is not emitted;
- fd2 is restored after success and failure paths.

Focused tests inject a secret through both `os.write(2, ...)` and `print(..., file=sys.stderr)`, assert no secret in terminal stdout/stderr or persisted JSON, and verify fd2 works normally after the bootstrap call.

### 1.3 Existing frozen boundaries remain intact

- `configs/production_account.yaml` is still empty;
- no credential / Token / host / port / raw profile enters Git;
- no migration changed;
- CR-5 / CR-6 semantics are untouched;
- CLI mode conflict and Production replay-all resume remain fail closed.

---

# 2. Next active work: P0-M-1B.0 Controlled Production Identity Freeze

Purpose: obtain one **human-confirmed scrubbed production account identity** using the merged controlled bootstrap. This stage still does not run formal B1-B7 until the identity is separately frozen.

## 2.1 Required execution order

On the controlled Windows environment containing the official AmazingData SDK and real account runtime credentials:

```powershell
# Optional runtime-only preflight; must not read .env
uv run python scripts/spike/production_account_bootstrap.py --offline \
  --output data/spike/results/production_account_bootstrap_offline.json

# Controlled live identity candidate
uv run python scripts/spike/production_account_bootstrap.py \
  --output data/spike/results/production_account_bootstrap_live.json
```

The operator must capture only the scrubbed result. Do not paste credentials, Token, raw SDK stdout/stderr, host, port, or raw logon profile into GitHub.

## 2.2 Live bootstrap acceptance gate

The live bootstrap is acceptable for human review only when all are true:

```text
sdk_state == SDK_INSTALLED
runtime_verdict == RUNTIME_ACTUAL_LOAD_VERIFIED
NETWORK_REACHABLE == REACHABLE
AUTHENTICATED == YES
QUERY_READY == YES
ACCOUNT_PROFILE.profile_parsed == true
ACCOUNT_PROFILE.entitlement_verified == true
ACCOUNT_PROFILE.account_profile_id is present and scrubbed
bootstrap_status == IDENTITY_CANDIDATE
  or FROZEN_IDENTITY_MATCH_REQUIRES_REVIEW
config_written == false
human_confirmation_required == true
```

A non-zero exit, SDK/runtime ambiguity, auth failure, missing profile, empty PermissionCode, query-not-ready, or any secret leakage means **STOP / DO NOT FREEZE**.

`sdk_stderr_observed=true` is not automatically failure; it means stderr existed but was contained. The operator must not recover or publish its raw text merely to inspect it. If runtime behavior needs diagnosis, add a new explicitly scrubbed diagnostic field rather than dumping raw stderr.

## 2.3 Human confirmation

A human Reviewer/Owner must verify that the scrubbed `account_profile_id` belongs to the intended formal AmazingData account for this project.

Only after that human confirmation may a separate governance commit fill:

```yaml
production_account_profile_id: "<scrubbed stable id>"
confirmed_at: "<ISO-8601 with timezone>"
confirmed_by: "<approved human/operator identifier or role>"
```

in `configs/production_account.yaml`.

The governance commit must contain no username, password, Token, host, port, raw entitlement JSON, or raw profile.

---

# 3. Identity-freeze code/governance requirements

The commit that changes `configs/production_account.yaml` from empty to non-empty is a formal contract change and must in the **same commit** update:

```text
configs/production_account.yaml
docs/DEVLOG.md
docs/project/DEVELOPMENT_MANAGEMENT.md
```

and add/retain focused tests proving:

1. exact live scrubbed profile id -> `AccountKind.PRODUCTION`;
2. any different unknown account -> refused;
3. known trial profile -> refused;
4. unparsed profile -> refused;
5. profile with missing PermissionCode -> refused;
6. empty/unconfirmed config -> no production identity;
7. malformed config -> fail closed;
8. `RunKind.PRODUCTION` alone never upgrades account identity;
9. no secret appears in config/test fixtures/logs.

Do not alter historical migrations for this step.

---

# 4. Formal Production B1-B7 remains blocked until identity freeze

After the identity-freeze commit is merged and its three-platform CI is green, start **P0-M-1B.1 Formal Production Spike** using one run only:

```powershell
uv run python scripts/spike/spike_runner.py --production --date <latest-complete-trading-day>
uv run python scripts/spike/spike_runner.py --verdict --run-id <id>
```

Rules remain frozen:

- one Production run owns B1-B7;
- no caller-selected partial Production phase;
- hard-crash recovery uses replay-all on the same RUNNING run;
- formal raw evidence must be anchored in persistent migrated DuckDB;
- `VALIDATED_FAIL` may exist in an execution-complete CLOSED run; verdict decides NO_GO;
- trial/native-smoke/bootstrap evidence cannot substitute for Production cases;
- 2020-01-01 remains the history contract start;
- no Provider capability can be APPROVED before formal verdict + Data Sufficiency + Reviewer review.

---

# 5. Mandatory handoff evidence for next Reviewer turn

When P0-M-1B.0 is updated, provide via repository only:

```text
1. scrubbed bootstrap evidence summary (no credentials/raw profile)
2. exact scrubbed candidate account_profile_id
3. bootstrap status/runtime verdict/query-ready summary
4. human confirmation record
5. identity-freeze commit SHA (if confirmation passes)
6. focused identity gate test mapping
7. three-platform CI run id + result
8. explicit statement that formal B1-B7 has NOT yet been executed, unless identity freeze already merged
```

If the controlled live bootstrap fails, record the failure class and safe diagnostics, keep `production_account.yaml` empty, and do not proceed to B1-B7.

---

# 6. Scope guard

Do not use this stage to add new Provider interfaces, index/industry expansion, new State semantics, CR-7, strategy logic, or research factors.

Current priority is deliberately narrow:

```text
controlled bootstrap
  -> human-confirm scrubbed identity
  -> freeze exact allowlist
  -> formal B1-B7
  -> verdict
  -> Data Sufficiency Matrix
  -> Reviewer decision on AmazingData capability
```

This sequence is now the authoritative next-stage handoff.