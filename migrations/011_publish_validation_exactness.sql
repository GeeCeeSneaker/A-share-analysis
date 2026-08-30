-- 011_publish_validation_exactness.sql
-- R4-B2 (audit 20260830): Publish Validation Exactness.
--
-- 1. meta_artifact_dq_finding: append-only DQ FACTS. The B2 artifact
--    validator DERIVES identity_fallback_count / blocking_dq_count
--    from this table (SELECT count) - callers may append bad facts,
--    they can never append a PASS.
-- 2. meta_artifact_validation gains the B2 exact-seal columns:
--    the artifact/component identity the PASS was computed over, the
--    validation contract hash, and the persisted report binding
--    (report_uri + report_hash). Rows lacking the seal (pre-B2
--    legacy) are NOT publish-eligible - they require revalidation.

CREATE TABLE meta_artifact_dq_finding (
    finding_id               VARCHAR NOT NULL,
    feature_artifact_set_id  VARCHAR NOT NULL,
    finding_class            VARCHAR NOT NULL,   -- IDENTITY_FALLBACK / BLOCKING_DQ
    recorded_at              TIMESTAMPTZ NOT NULL,
    detail                   VARCHAR,
    PRIMARY KEY (finding_id)
);

ALTER TABLE meta_artifact_validation ADD COLUMN IF NOT EXISTS artifact_manifest_hash    VARCHAR;
ALTER TABLE meta_artifact_validation ADD COLUMN IF NOT EXISTS component_manifest_hash  VARCHAR;
ALTER TABLE meta_artifact_validation ADD COLUMN IF NOT EXISTS validation_contract_hash VARCHAR;
ALTER TABLE meta_artifact_validation ADD COLUMN IF NOT EXISTS report_uri               VARCHAR;
ALTER TABLE meta_artifact_validation ADD COLUMN IF NOT EXISTS report_hash              VARCHAR;
ALTER TABLE meta_artifact_validation ADD COLUMN IF NOT EXISTS required_checks_hash     VARCHAR;
