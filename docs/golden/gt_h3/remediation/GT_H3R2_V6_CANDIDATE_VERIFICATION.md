# GT-H3R2 v6 candidate verification

> Status: **STAGED / NON-ACTIVE / COMPILED ONLY / HUMAN REVIEW REQUIRED FOR 15 NEW CASES / REVIEW SEAL NOT RUN**

## Bound inputs

- Source: v5-candidate-20260907
- Source dataset SHA256: 5ab7ddf7a03115ad475cf85b3660e09414b0399004097f6121a3624e7330122c
- Target: v6-candidate-20260908
- Target dataset SHA256: d11b6cd0314e9a1b63e1728668f61bfacc29f97b255f00f40fcdb98e9d0b1b0c
- Active pointer: remains v5-candidate-20260907

## Recomputed checks

| Check | Result |
| --- | ---: |
| Total rows | 125 |
| ST_TRANSITION structural identities | 50 |
| ST_ADD / ST_REMOVE | 38 / 12 |
| Other 75 Golden cases review identity unchanged | PASS |
| v5 → v6 carry-forward | 110 eligible / 15 not eligible |
| v6 audit rows | 50 PASS with reviewed official PRE/EFFECTIVE locators |
| Review summary | COMPILED 125 |

The carry-forward count is recomputed from review_identity_hash; 110 is only the expected sanity check for this exact 15-for-15 plan, not a hard-coded acceptance shortcut.

## Lineage and review boundary

The 15 v5 rows classified as INVALID_ST_LEVEL_CHANGE are DROP-only source rows. The 15 added cases carry explicit accounting lineage back to the replaced v5 source IDs; the relation is not semantic equivalence. All 15 added rows remain COMPILED, have empty reviewer provenance, and require fresh Human Review.

The committed verifier is read-only. It checks the v5 immutable source binding, plan operation counts, v6 manifest self-consistency, exact audit coverage, structural uniqueness, unchanged-case identities, and carry-forward hashes. The active pointer is deliberately not advanced; review.py, GT-H3B, and production publication remain blocked.
