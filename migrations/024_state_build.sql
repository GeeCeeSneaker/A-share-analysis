-- 024_state_build.sql
-- CR-6.2 deterministic State Layer ledger. Correctness fields mirror the
-- immutable State manifest; timestamps are audit metadata only.

CREATE TABLE meta_state_build (
    state_run_id VARCHAR PRIMARY KEY,
    feature_run_id VARCHAR NOT NULL,
    feature_manifest_uri VARCHAR NOT NULL,
    feature_manifest_hash VARCHAR NOT NULL,
    feature_semantic_hash VARCHAR NOT NULL,
    feature_set_id VARCHAR NOT NULL,
    feature_registry_hash VARCHAR NOT NULL,
    state_set_id VARCHAR NOT NULL,
    state_set_version VARCHAR NOT NULL,
    state_registry_version VARCHAR NOT NULL,
    state_registry_hash VARCHAR NOT NULL,
    state_contract_version VARCHAR NOT NULL,
    state_builder_code_fingerprint VARCHAR NOT NULL,
    manifest_uri VARCHAR NOT NULL,
    manifest_hash VARCHAR NOT NULL,
    artifact_set_hash VARCHAR NOT NULL,
    state_semantic_hash VARCHAR NOT NULL,
    finding_set_hash VARCHAR NOT NULL,
    state_row_count INTEGER NOT NULL,
    finding_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    error_message VARCHAR,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_meta_state_build_feature
    ON meta_state_build (feature_run_id);
