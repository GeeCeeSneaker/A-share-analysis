# A-share-analysis AUDIT-H1 关闭与 T1 正式线上身份候选执行要求

> Date: 2026-09-05  
> Reviewer baseline before merge: `c939b747a46d4fc2ef62b8a427b431751346449a`  
> AUDIT-H1 PR: #12  
> Reviewed PR head: `6671c6e388163b9cb15137f716247b36d0290cc4`  
> Reviewer review: `5121303998`  
> Final CI: GitHub Actions `33965305245` / run 301 SUCCESS  
> Merge commit: `c9787d243be5ca02a46496e38d5401fbf38a255b`  
> Status: **AUDIT-H1 VERIFIED / CLOSED / T1 CONTROLLED ONLINE BOOTSTRAP RE-AUTHORIZED**

## 1. Reviewer closure

AUDIT-H1 scope is closed:

- REV-01 runtime / entitlement honesty: CLOSED;
- REV-02A Safe Diagnostic Projection: CLOSED;
- REV-04 three-platform CI gate honesty: CLOSED.

Windows 3.14、Windows 3.12、Ubuntu 3.14 are now all required CI legs. Run 301 completed SUCCESS on all three; Windows 3.14 full pytest reported `1539 passed`, with Ruff lint/format, mypy, Spike, SDK-absent, DEVLOG and Management gates successful.

`configs/production_account.yaml` remains empty. This closure does **not** freeze a production identity, approve AmazingData capability, approve B1-B7, or authorize backfill.

REV-02B / REV-03 / REV-05 / REV-06 / REV-07 / REV-08 remain governed follow-up work at their previously assigned gates and are not reopened into T1.

## 2. Current authoritative sequence

```text
AUDIT-H1                         VERIFIED / CLOSED
    ↓
T1 controlled online bootstrap  AUTHORIZED
    ↓
T2 human identity confirmation  BLOCKED BY T1 CANDIDATE
    ↓
T3 identity-freeze PR            BLOCKED BY T2
    ↓
Formal Production B1-B7         BLOCKED BY T3 MERGE + GREEN CI
    ↓
Data Sufficiency Matrix         BLOCKED BY FORMAL RUN
    ↓
Provider capability decision    BLOCKED BY REVIEW
    ↓
2020+ backfill                   BLOCKED BY PROVIDER APPROVAL + LATER GATES
```

Do not start B1-B7, capability approval, historical backfill, strategy, backtest or trading work during T1.

## 3. T1 controlled execution contract

### 3.1 Environment

Use a controlled Windows environment with the official AmazingData/TGW runtime already verified for the project. Start from a clean checkout of current `main` containing merge commit `c9787d243be5ca02a46496e38d5401fbf38a255b` or later Reviewer-authorized documentation-only head.

Credentials may be injected only by:

- local process environment `TGW_*`; or
- a local `.env` that remains Git-ignored and untracked.

Never put username, password, Token, real endpoint, raw profile, raw SDK stdout/stderr or proprietary SDK files in Git, PR body, issue, review comment or persistent evidence.

### 3.2 Unique T1 entry point

Run the controlled bootstrap entry only:

```powershell
uv run python scripts/spike/production_account_bootstrap.py --output data/spike/results/production_account_bootstrap.json
```

The local JSON file is under gitignored data storage. It is not itself a repository artifact. Only its allowlisted scrubbed facts may be transcribed into governance documentation.

Do not use ordinary `provider-doctor` as a substitute for T1 evidence.

## 4. T1 success gate

A result may be handed to Reviewer/Owner as an identity candidate only when all of the following are true in one controlled execution:

```text
sdk_state == SDK_INSTALLED
runtime_verdict == RUNTIME_ACTUAL_LOAD_VERIFIED
AUTHENTICATED == YES
QUERY_READY == YES
ACCOUNT_PROFILE.profile_parsed == true
ACCOUNT_PROFILE.entitlement_verified == true
ACCOUNT_PROFILE.account_profile_id == UNKNOWN_<12 lowercase hex>
ACCOUNT_PROFILE.profile_kind == UNKNOWN
ACCOUNT_PROFILE.permission_codes contains >= 1 parsed ASCII decimal code
production_identity_status == NOT_FROZEN
bootstrap_status == IDENTITY_CANDIDATE
config_written == false
human_confirmation_required == true
```

`permission_codes` proves only that numeric entitlement evidence exists. It does not approve any dataset capability.

On `IDENTITY_CANDIDATE`, **stop immediately**. Do not edit `configs/production_account.yaml`; do not run B1-B7.

## 5. Allowed repository evidence after a successful T1

Open one focused documentation PR. Record only allowlisted scrubbed facts needed for review:

- source code / main SHA used for the run;
- controlled environment class (Windows, Python version, SDK package/runtime versions);
- checked_at timestamp;
- `sdk_state` / `runtime_verdict`;
- `AUTHENTICATED` / `QUERY_READY`;
- scrubbed generated `account_profile_id`;
- `profile_kind` / `profile_parsed` / `entitlement_verified`;
- normalized numeric `permission_codes`;
- `production_identity_status`;
- `bootstrap_status`;
- `config_written` and `human_confirmation_required`.

Do not commit the raw local bootstrap file merely because the current projection is expected to be safe. Keep the durable repository record intentionally minimal.

Update the applicable provider-verification / DEVLOG / DEVELOPMENT_MANAGEMENT truth in the same governed documentation batch if their current-status statements change.

## 6. Failure / stop states

These are valid T1 outcomes and must not be normalized into success:

- `NOT_TESTABLE_SDK`;
- `NOT_TESTABLE_RUNTIME`;
- `NOT_TESTABLE_ACCOUNT`;
- `NOT_TESTABLE_PROFILE`;
- `NOT_TESTABLE_ENTITLEMENT`;
- `NOT_QUERY_READY`;
- `TRIAL_ACCOUNT_NOT_FREEZABLE`;
- `FROZEN_IDENTITY_MISMATCH`;
- `ERROR`.

If one occurs, record only the stable scrubbed state/code and relevant allowlisted runtime facts. Do not add raw SDK error text to explain the failure. Do not change identity config.

A new external blocker discovered after credentials are safely injected is meaningful progress; another credential-absent preflight with no new fact is not.

## 7. T2 human confirmation

T2 is a human governance decision, not an SDK inference.

After a valid `IDENTITY_CANDIDATE`, Owner/Reviewer must confirm that the exact scrubbed generated profile ID belongs to the formal project account intended for production qualification.

Until that explicit confirmation exists:

```text
production_account.yaml          MUST REMAIN EMPTY
Production identity              NOT FROZEN
Formal Production B1-B7          BLOCKED
Provider capability approval     BLOCKED
```

Only after T2 may a separate T3 identity-freeze PR be created.

## 8. Next developer task

**Task: execute T1 once under the contract above and stop at the first truthful terminal result.**

No additional code optimization is authorized before T1 unless execution exposes a concrete correctness/safety blocker. Do not expand AUDIT-H1 into REV-03/05/06/07/08 work during this step.
