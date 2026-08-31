-- 014_provider_normalization.sql
-- CR-2 (audit 20260831): Provider-Normalized + Quarantine runtime.
--
-- meta_provider_normalization_run: one row per normalization execution
-- over ONE persisted raw evidence request. Lineage/summary only - the
-- normalized bytes live in immutable parquet artifacts under the
-- normalized root, bound by the manifest recorded here.
--
-- meta_provider_quarantine: append-only first-class quarantine
-- evidence. Every record locates the exact raw source (request /
-- table / row ordinal) and carries a scrubbed structured error
-- context. Fixing a mapper produces a NEW normalization run - history
-- is never deleted to hide failures.

CREATE TABLE meta_provider_normalization_run (
    normalization_run_id          VARCHAR PRIMARY KEY,
    provider                      VARCHAR NOT NULL,
    provider_dataset              VARCHAR NOT NULL,
    endpoint                      VARCHAR,
    raw_request_id                VARCHAR NOT NULL,
    raw_evidence_uri              VARCHAR NOT NULL,
    raw_evidence_hash             VARCHAR NOT NULL,
    raw_payload_kind              VARCHAR,
    normalization_contract_version VARCHAR NOT NULL,
    mapper_identity               VARCHAR NOT NULL,
    normalized_manifest_uri       VARCHAR,
    normalized_manifest_hash      VARCHAR,
    input_count                   INTEGER NOT NULL,
    normalized_count              INTEGER NOT NULL,
    quarantined_count             INTEGER NOT NULL,
    status                        VARCHAR NOT NULL,   -- SUCCESS / PARTIAL / BLOCKED
    error_class                   VARCHAR,            -- RAW_EVIDENCE_INVALID / SOURCE_EXCHANGE_FAILED / PAYLOAD_SHAPE_UNSUPPORTED / MAPPING_VALIDATION_FAILED / NORMALIZATION_INTERNAL_ERROR
    error_message                 VARCHAR,
    idempotency_key               VARCHAR NOT NULL,
    idempotent_replay             BOOLEAN NOT NULL DEFAULT FALSE,
    started_at                    TIMESTAMPTZ NOT NULL,
    completed_at                  TIMESTAMPTZ
);

CREATE TABLE meta_provider_quarantine (
    quarantine_id                 VARCHAR PRIMARY KEY,
    normalization_run_id          VARCHAR NOT NULL,
    provider                      VARCHAR NOT NULL,
    provider_dataset              VARCHAR NOT NULL,
    raw_request_id                VARCHAR NOT NULL,
    raw_evidence_uri              VARCHAR NOT NULL,
    raw_evidence_hash             VARCHAR NOT NULL,
    raw_table_name                VARCHAR,            -- NULL for single-table payloads
    raw_row_ordinal               INTEGER,            -- ROW scope only
    source_key                    VARCHAR,            -- natural key when available
    quarantine_scope              VARCHAR NOT NULL,   -- ROW / WHOLE_PAYLOAD
    error_class                   VARCHAR NOT NULL,
    error_message                 VARCHAR NOT NULL,
    error_context_json            VARCHAR,            -- scrubbed structured context
    mapper_identity               VARCHAR NOT NULL,
    normalization_contract_version VARCHAR NOT NULL,
    created_at                    TIMESTAMPTZ NOT NULL
);
