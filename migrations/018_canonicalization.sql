-- 018_canonicalization.sql
-- CR-3 (audit 20260901 "CR-2.4最终复审结论与CR-3_AvailabilityPolicy_Canonicalizer
-- 开发工作要求" sections 5-6): Provider-Normalized -> Canonical runtime.
--
-- meta_canonicalization_run: the canonical run ledger. One row per
-- deterministic canonical run identity (exact normalized input set +
-- as_of + contract + identity/availability/source/tolerance policy
-- identities + canonicalizer code fingerprint). A prior row with the
-- same identity is re-verified before an idempotent replay.
--
-- meta_canonical_reconciliation_finding: first-class findings
-- (identity missing/ambiguous, duplicate canonical key, source
-- conflict, closure verification failure, required domain missing).
-- Blocking findings make the run BLOCKED. Per-row selection decisions
-- live in the immutable decisions.parquet artifact - the DB keeps
-- run-level seals/summaries only (audit section 6).

CREATE TABLE meta_canonicalization_run (
    canonical_run_id            VARCHAR PRIMARY KEY,
    as_of                       TIMESTAMPTZ NOT NULL,
    canonical_contract_version  VARCHAR NOT NULL,
    input_set_hash              VARCHAR NOT NULL,   -- exact set of eligible CR-2 run manifest hashes
    identity_dataset_hash       VARCHAR NOT NULL,   -- security_master identity dataset + bridge policy identity
    availability_policy_version VARCHAR NOT NULL,
    availability_policy_hash    VARCHAR NOT NULL,
    source_policy_version       VARCHAR NOT NULL,
    source_policy_hash          VARCHAR NOT NULL,
    tolerance_policy_version    VARCHAR NOT NULL,
    tolerance_policy_hash       VARCHAR NOT NULL,
    code_fingerprint            VARCHAR NOT NULL,   -- canonicalizer + policy module source SHA-256
    manifest_uri                VARCHAR,
    manifest_hash               VARCHAR,
    selected_count              INTEGER NOT NULL,
    decision_count              INTEGER NOT NULL,
    finding_count               INTEGER NOT NULL,
    status                      VARCHAR NOT NULL,   -- SUCCESS / PARTIAL / BLOCKED
    error_message               VARCHAR,
    idempotency_key             VARCHAR NOT NULL,
    idempotent_replay           BOOLEAN NOT NULL DEFAULT FALSE,
    started_at                  TIMESTAMPTZ NOT NULL,
    completed_at                TIMESTAMPTZ NOT NULL,
    finding_set_hash            VARCHAR              -- exact-set seal over the run's findings
);

CREATE TABLE meta_canonical_reconciliation_finding (
    finding_id                  VARCHAR NOT NULL,
    canonical_run_id            VARCHAR NOT NULL,
    canonical_domain            VARCHAR NOT NULL,
    canonical_key               VARCHAR NOT NULL,   -- canonical JSON of the natural key
    finding_class               VARCHAR NOT NULL,   -- IDENTITY_MISSING / IDENTITY_AMBIGUOUS / DUPLICATE_CANONICAL_KEY /
                                                    -- SOURCE_CONFLICT / CLOSURE_VERIFICATION_FAILED / REQUIRED_DOMAIN_MISSING
    provider                    VARCHAR,
    source_normalization_run_id VARCHAR,
    detail_json                 VARCHAR,             -- scrubbed structured evidence summary
    blocking                    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at                  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (finding_id, canonical_run_id)
);
