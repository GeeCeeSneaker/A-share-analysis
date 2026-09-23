# Issue #80 — daily_bar vertical-slice evidence

Date: 2026-09-23  
Architecture baseline: Issue #79 decision, `L0 + fixed16 UUID`, time-first monthly partitions.  
Scope: local fixtures and synthetic rows only; `provider_calls=0`; no Issue #76 history migration.

## Data-plane change

| Layer | Previous daily path | Issue #80 path |
|---|---|---|
| Canonical | Full daily rows in run-level `selected.parquet` | One monthly fixed16 fact Parquet per logical partition; row-varying lineage in a key-aligned sidecar; partition-constant lineage in the small manifest |
| Snapshot | Physical daily OHLCV Parquet copy | Logical manifest references the exact Canonical partition set; zero daily fact Parquet files |
| ReadModel | Durable DuckDB daily fact table | `rm_daily_bar` is a view over only the manifest-referenced fact/lineage files |
| Active R1 publisher | Full-history Python projection handoff | DuckDB predicates and selected columns feed bounded Arrow batches; streamed Parquet outputs are committed before the manifest |

Counting only durable full OHLCV fact payloads and excluding Raw evidence: the prior active chain had three copies (Canonical selected artifact, Snapshot artifact, and ReadModel table); the new chain has one (Canonical fact). The lineage sidecar contains no OHLCV columns and is not a second fact copy.

The three-month integration fixture (June–August 2026, two rows per month) produces three fact Parquets, three lineage Parquets, and three partition manifests. Its Snapshot directory contains zero Parquet files. The ReadModel integration tests assert that `rm_daily_bar` is a view and that ordinary open does not read/hash the full fact history.

## Correctness and semantic evidence

- `security_id` is Arrow `fixed_size_binary[16]`, written as Parquet `FIXED_LEN_BYTE_ARRAY(16)` in both fact and lineage; deep reconstruction round-trips the governed UUID exactly.
- Fact logical keys remain `(security_id, trade_date)`, sorted by `(trade_date, UUID bytes)`. The fact schema contains the seven daily values plus those two key fields.
- Closed-month immutability is evaluated in the exchange-local `Asia/Shanghai` market clock, while the sealed `market_as_of` instant remains normalized to UTC.
- `data_revision` equals the deterministic logical content hash. A layout-revision-only rewrite preserves both; changed content in an open month gets a new revision; changed content in a closed month fails before publishing another revision.
- A new-month append emits only that month's partition and leaves the closed prior-month fact bytes unchanged. Partition fact and lineage are atomically committed before the partition manifest; the Canonical run manifest/ledger remains the outer publication boundary.
- Existing R1 integration assertions still produce 2 Development, 2 Validation, and 2 Holdout rows for the deterministic fixture. Date/security/column filters return only matching rows, the active publisher succeeds when `prepare_verified_projection` is patched to fail, and exact replay retains identical content and manifest hashes.
- Explicit Snapshot deep audit streams partition batches and detects fact tampering. Routine Snapshot/ReadModel open checks small manifests, bindings, schemas and Parquet footers without a total-row semantic hash scan.

## Resource sample

A deterministic synthetic January 2026 partition used 20 dates × 5,000 UUID identities = **100,000 rows**. The Canonical partition writer produced one fact Parquet, one lineage Parquet, and one 1,851-byte partition manifest. DuckDB read that exact fact file externally: `COUNT(*)=100000`; the UUID/date point lookup returned `close=10.5`. Windows `GetProcessMemoryInfo` reported peak working set **293,695,488 bytes (0.274 GiB)** for this writer-plus-external-scan process.

This is a reproducible partition-writer/query resource sample, not a claim about a full production CanonicalRunner or 78-month migration. Snapshot, ReadModel and R1 end-to-end behavior is covered by integration tests on deterministic fixtures. No provider SDK or account was used.

## Compatibility boundary and remaining work

- `prepare_verified_projection()` still exposes a whole-history Python projection because Issue #76 historical materialization consumes `VerifiedResearchProjection`. The active R1 `build_from_readmodel()` path no longer calls it; an integration test enforces this. Removing or migrating that separate Issue #76 handoff is out of this issue's scope.
- The explicit generic Canonical compatibility verifier still returns a materialized `VerifiedCanonicalRun` projection. It is not called by routine logical Snapshot/ReadModel/R1 consumption; the daily Snapshot deep-audit path streams batches and does not retain all fact rows.
- Canonical selection still materializes rows for its entire input snapshot. This slice exercises monthly Canonical inputs and a month-bounded partition writer; it does not establish bounded memory for a multi-year Canonical input. Do not pass the complete retained 78-month archive as one Canonical run; the separately authorized Issue #76 migration must remain month/partition bounded.
- The repository's anchored raw envelope currently names its response-arrival timestamp `received_at`; the new `source_vintage_as_of` is derived from those verified source receipts, independently of `market_as_of`. No claim is made that a current receipt timestamp proves a historical market-data vintage.
- The full repository command `pytest tests -q` was stopped at 48% because it was outside this slice's focused QA and had not produced a final result; it is **not** counted as a pass. The complete affected-scope runs below both exited 0.

## Local QA

All commands used the repository source via `PYTHONPATH=src` and the local Python 3.12 environment.

```text
ruff check <all changed source and test files>                         PASS
pytest tests/integration/test_snapshot.py tests/integration/test_readmodel.py
       tests/integration/test_r1_research_panel_integration.py
       tests/integration/test_features.py tests/unit/test_atomic_files.py
       tests/unit/test_r1_research_panel.py tests/unit/test_daily_bar_partition.py
       tests/unit/test_cr7_historical_materialization_contract.py
       tests/unit/test_cr7_historical_materialization.py -q             PASS
pytest tests/integration/test_canonical.py -q                           PASS
```

Exact-head GitHub CI is a separate exit gate; record its status in the PR conversation against the submitted head.
