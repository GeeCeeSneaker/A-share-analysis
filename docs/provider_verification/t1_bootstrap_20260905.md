# T1 Controlled Online Bootstrap Evidence（脱敏）

> Date: 2026-09-05  
> Status: **IDENTITY_CANDIDATE / PENDING_T2 / CONFIG_EMPTY**  
> This document contains only the bootstrap safe diagnostic projection. It is not a Provider capability approval, Production B1-B7 result, or identity freeze.

## 1. Execution binding

| Field | Value |
|---|---|
| Source code tree used | `6671c6e388163b9cb15137f716247b36d0290cc4` |
| H1 merge commit containing the source tree | `c9787d243be5ca02a46496e38d5401fbf38a255b` |
| Current main checked after merge | `9b08d40b4318dbd6a7784a14a9e86a743374713f` |
| Controlled platform | Windows (`win32`) |
| Python | `3.14.6` |
| AmazingData package | `1.1.9` |
| Python TGW package | `1.0.9.2` |
| SDK ABI | `cpython314/win32-x64` |
| TGW runtime reported version | `V4.3.0.260626-rc2.0-YHZQ` |
| checked_at | `2026-09-05T13:36:45.179509+00:00` |

Credentials were injected only into the local process environment. Username, password, endpoint, Token, raw profile and raw SDK output are intentionally omitted.

## 2. Scrubbed T1 projection

| Field | Value |
|---|---|
| `sdk_state` | `SDK_INSTALLED` |
| `runtime_verdict` | `RUNTIME_ACTUAL_LOAD_VERIFIED` |
| `NETWORK_REACHABLE` | `REACHABLE` |
| `AUTHENTICATED` | `YES` |
| `QUERY_READY` | `YES` |
| `ACCOUNT_PROFILE.account_profile_id` | `UNKNOWN_24e2ff401792` |
| `ACCOUNT_PROFILE.profile_kind` | `UNKNOWN` |
| `ACCOUNT_PROFILE.profile_parsed` | `true` |
| `ACCOUNT_PROFILE.entitlement_verified` | `true` |
| `ACCOUNT_PROFILE.permission_codes` | `2|3|4|6|7|11|12|13|29|30|31|32|33|16|17|18|19|20|21|22|23|24|25|26|27|28` |
| `ACCOUNT_PROFILE.subscribe_limit` | `0` |
| `ACCOUNT_PROFILE.weekly_flow_limit` | `1000000000` |
| `ACCOUNT_PROFILE.used_week_flow` | `0.35` |
| `production_identity_status` | `NOT_FROZEN` |
| `bootstrap_status` | `IDENTITY_CANDIDATE` |
| `config_written` | `false` |
| `human_confirmation_required` | `true` |
| `sdk_stderr_observed` | `false` |

## 3. Gate and next action

The candidate satisfies the repository T1 gate and is the only result that may be submitted for T2. Execution stopped immediately after the safe projection.

- `configs/production_account.yaml` remains unchanged and empty.
- No identity-freeze, Production B1-B7, Data Sufficiency, verdict, Provider capability approval or backfill was run.
- T2 requires Owner/Reviewer to confirm outside the SDK inference boundary that the exact scrubbed ID `UNKNOWN_24e2ff401792` belongs to the intended formal project account.
- Until T2 confirmation, keep the production identity unfrozen and do not create a T3 configuration PR.
