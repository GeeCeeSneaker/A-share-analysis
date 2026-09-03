-- 023_feature_build.sql
-- CR-5 deterministic Feature Layer ledger.  Correctness fields mirror
-- the immutable feature manifest; timestamps are audit metadata only.

CREATE TABLE meta_feature_build (
    feature_run_id VARCHAR PRIMARY KEY,
    snapshot_id VARCHAR NOT NULL,
    snapshot_manifest_uri VARCHAR NOT NULL,
    snapshot_manifest_hash VARCHAR NOT NULL,
    snapshot_semantic_hash VARCHAR NOT NULL,
    snapshot_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
    readmodel_contract_version VARCHAR NOT NULL,
    readmodel_builder_code_fingerprint VARCHAR NOT NULL,
    feature_set_id VARCHAR NOT NULL,
    feature_set_version VARCHAR NOT NULL,
    feature_registry_version VARCHAR NOT NULL,
    feature_registry_hash VARCHAR NOT NULL,
    feature_contract_version VARCHAR NOT NULL,
    feature_builder_code_fingerprint VARCHAR NOT NULL,
    manifest_uri VARCHAR NOT NULL,
    manifest_hash VARCHAR NOT NULL,
    artifact_set_hash VARCHAR NOT NULL,
    feature_semantic_hash VARCHAR NOT NULL,
    finding_set_hash VARCHAR NOT NULL,
    security_row_count INTEGER NOT NULL,
    market_row_count INTEGER NOT NULL,
    finding_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    error_message VARCHAR,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_meta_feature_build_snapshot
    ON meta_feature_build (snapshot_id);
