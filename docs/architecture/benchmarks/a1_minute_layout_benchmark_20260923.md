# A1 synthetic minute-layout benchmark

- Status: **REVIEW_REQUIRED_FOR_ARCHITECTURE_SELECTION**
- Resource gates: **PASS**
- Source: synthetic deterministic data only; `provider_calls=0`.
- Shape: 1,080,000 rows/day × 20 days = 21,600,000 rows/open-month.
- Candidate layouts: L0 month/time-first; L1 month + 16 buckets/time-first; L2 month + 16 buckets/security-first.
- Candidate physical keys: UUID string, fixed 16-byte binary, INT64.
- Synthetic numeric columns are placeholders; A0 numeric/provider-unit contract remains open.

## Resource gate summary

| key | layout | daily peak GiB | compaction peak GiB | short/long daily ratio | closed rewrite |
|---|---:|---:|---:|---:|---:|
| uuid_string | L0 | 0.239 | 0.238 | 1.04 | 0 |
| uuid_string | L1 | 0.192 | 0.242 | 1.01 | 0 |
| uuid_string | L2 | 0.226 | 0.238 | 1.02 | 0 |
| fixed16 | L0 | 0.259 | 0.264 | 1.02 | 0 |
| fixed16 | L1 | 0.229 | 0.260 | 1.10 | 0 |
| fixed16 | L2 | 0.224 | 0.234 | 1.12 | 0 |
| int64 | L0 | 0.246 | 0.262 | 1.01 | 0 |
| int64 | L1 | 0.211 | 0.214 | 1.02 | 0 |
| int64 | L2 | 0.224 | 0.224 | 1.03 | 0 |

## Interpretation

The result is evidence for A1 layout selection, not a provider numeric or minute-semantic approval. `files_with_matching_rows` is a query observation and `bytes_read_estimate` is the candidate Parquet byte set; exact kernel I/O counters are not claimed. A human/PM decision is still required before freezing the physical layout and starting the daily vertical refactor.

