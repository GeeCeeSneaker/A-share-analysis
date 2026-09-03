-- 022_snapshot_build.sql
-- CR-4.2 (audit 20260902 section 5, work requirement P0-A12):
-- the SNAPSHOT build ledger. One row per built snapshot; the
-- immutable file-side anchor (manifest bytes hash) lets the exact
-- retry replay idempotently.

CREATE TABLE meta_snapshot_build (
    snapshot_id VARCHAR PRIMARY KEY,
    canonical_run_id VARCHAR NOT NULL,
    canonical_manifest_uri VARCHAR NOT NULL,
    canonical_manifest_hash VARCHAR NOT NULL,
    canonical_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    requested_domains_json VARCHAR NOT NULL,
    requested_domains_hash VARCHAR NOT NULL,
    snapshot_contract_version VARCHAR NOT NULL,
    builder_code_fingerprint VARCHAR NOT NULL,
    manifest_uri VARCHAR,
    manifest_hash VARCHAR,
    artifact_set_hash VARCHAR,
    snapshot_semantic_hash VARCHAR,
    row_count_total INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    error_message VARCHAR,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_meta_snapshot_build_canonical
    ON meta_snapshot_build (canonical_run_id);
