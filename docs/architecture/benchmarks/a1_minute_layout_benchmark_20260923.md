# A1 synthetic minute-layout benchmark

- Status: **REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION**
- Resource gates: **PASS**
- Source: synthetic deterministic data only; `provider_calls=0`.
- Shape: 1,080,000 rows/day × 20 days = 21,600,000 rows/open-month.
- Candidate layouts: L0 month/time-first; L1 month + 16 buckets/time-first; L2 month + 16 buckets/security-first.
- Candidate physical keys: UUID string, fixed 16-byte binary, INT64.
- W4-W8 are measured against both open fragments and closed-month compacted artifacts; L1/L2 W5/W6 select stable bucket candidates before `read_parquet`.
- `row_groups_touched` remains null when the installed DuckDB runtime does not expose a reliable value; no profiling subsystem is added.
- Runner Git head: `5d6635ec6b07488cc6997ad13610e0a8b076be5c`; runner blob SHA: `6514f8083e5cc7a812953b780d2740280b637aa1`; runner source SHA-256: `eae1e60d4ecb4d386fde0a317285989b4a1808bb6d76d5d17d51dd0d95a53fdb`.
- Synthetic numeric columns are placeholders; A0 numeric/provider-unit contract remains open.

## Resource gate summary

| key | layout | daily peak GiB | compaction peak GiB | short/long daily ratio | closed rewrite |
|---|---:|---:|---:|---:|---:|
| uuid_string | L0 | 0.240 | 0.248 | 1.01 | 0 |
| uuid_string | L1 | 0.216 | 0.265 | 1.06 | 0 |
| uuid_string | L2 | 0.238 | 0.246 | 1.04 | 0 |
| fixed16 | L0 | 0.258 | 0.258 | 1.04 | 0 |
| fixed16 | L1 | 0.214 | 0.260 | 1.01 | 0 |
| fixed16 | L2 | 0.223 | 0.225 | 1.06 | 0 |
| int64 | L0 | 0.311 | 0.317 | 1.04 | 0 |
| int64 | L1 | 0.208 | 0.234 | 1.04 | 0 |
| int64 | L2 | 0.206 | 0.216 | 1.13 | 0 |

## Interpretation

The result is evidence for A1 layout selection, not a provider numeric or minute-semantic approval. `files_with_matching_rows` is a query observation and `bytes_read_estimate` is the candidate Parquet byte set; exact kernel I/O counters are not claimed. A human/PM decision is still required before freezing the physical layout and starting the daily vertical refactor.
