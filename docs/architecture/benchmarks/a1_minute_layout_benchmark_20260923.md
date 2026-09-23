# A1 synthetic minute-layout benchmark

- Status: **REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION**
- Resource gates: **PASS**
- Source: synthetic deterministic data only; `provider_calls=0`.
- Shape: 1,080,000 rows/day × 20 days = 21,600,000 rows/open-month.
- Candidate layouts: L0 month/time-first; L1 month + 16 buckets/time-first; L2 month + 16 buckets/security-first.
- Candidate physical keys: UUID string, fixed 16-byte binary, INT64.
- W4-W8 are measured against both open fragments and closed-month compacted artifacts; L1/L2 W5/W6 select stable bucket candidates before `read_parquet`.
- `row_groups_touched` remains null when the installed DuckDB runtime does not expose a reliable value; no profiling subsystem is added.
- Runner Git head: `f940ec782a816e6b63d6a13c462af5441e8256c0`; runner blob SHA: `f91f891ac2dca782603753685c4106308626d15f`; runner source SHA-256: `ad535f18c5de11b154a7291ad2cb4ac0c3384f15acaf2d35c6cfe644384f86d8`.
- Synthetic numeric columns are placeholders; A0 numeric/provider-unit contract remains open.

## Resource gate summary

| key | layout | daily peak GiB | compaction peak GiB | short/long daily ratio | closed rewrite |
|---|---:|---:|---:|---:|---:|
| uuid_string | L0 | 0.234 | 0.244 | 1.04 | 0 |
| uuid_string | L1 | 0.202 | 0.261 | 1.03 | 0 |
| uuid_string | L2 | 0.202 | 0.231 | 1.16 | 0 |
| fixed16 | L0 | 0.278 | 0.283 | 1.15 | 0 |
| fixed16 | L1 | 0.209 | 0.278 | 1.02 | 0 |
| fixed16 | L2 | 0.213 | 0.223 | 1.11 | 0 |
| int64 | L0 | 0.250 | 0.251 | 1.02 | 0 |
| int64 | L1 | 0.202 | 0.232 | 1.02 | 0 |
| int64 | L2 | 0.199 | 0.210 | 1.07 | 0 |

## Interpretation

The result is evidence for A1 layout selection, not a provider numeric or minute-semantic approval. `files_with_matching_rows` is a query observation and `bytes_read_estimate` is the candidate Parquet byte set; exact kernel I/O counters are not claimed. A human/PM decision is still required before freezing the physical layout and starting the daily vertical refactor.
