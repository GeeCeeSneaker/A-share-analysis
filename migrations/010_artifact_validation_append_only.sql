-- 010_artifact_validation_append_only.sql
-- Audit R3-P1-01: meta_artifact_validation becomes APPEND-ONLY and
-- publishes bind the exact validation they were approved under.
--
-- The 008 table (PK = feature_artifact_set_id, INSERT OR REPLACE) allowed
-- a later FAIL to overwrite the PASS an old publish relied on. This
-- migration:
--   1. renames the 008 table to preserve history,
--   2. creates the append-only ledger (PK = artifact_validation_id),
--   3. migrates existing rows with generated ids,
--   4. adds meta_publish_snapshot.artifact_validation_id so every publish
--      answers "which validation approved me".

ALTER TABLE meta_artifact_validation RENAME TO meta_artifact_validation_v008;

CREATE TABLE IF NOT EXISTS meta_artifact_validation (
    artifact_validation_id  VARCHAR NOT NULL,
    feature_artifact_set_id VARCHAR NOT NULL,
    validation_version      VARCHAR NOT NULL,
    validator_code_commit   VARCHAR,
    identity_fallback_count INTEGER NOT NULL DEFAULT 0,
    blocking_dq_count       INTEGER NOT NULL DEFAULT 0,
    validated_at            TIMESTAMPTZ NOT NULL,
    detail                  VARCHAR,
    PRIMARY KEY (artifact_validation_id)
);

INSERT INTO meta_artifact_validation (
    artifact_validation_id, feature_artifact_set_id, validation_version,
    validator_code_commit, identity_fallback_count, blocking_dq_count,
    validated_at, detail
)
SELECT
    'mig010-' || feature_artifact_set_id,
    feature_artifact_set_id,
    COALESCE(validation_version, 'unknown'),
    NULL,
    identity_fallback_count,
    blocking_dq_count,
    COALESCE(validated_at, now()),
    'migrated from v008 table by 010'
FROM meta_artifact_validation_v008;

ALTER TABLE meta_publish_snapshot ADD COLUMN artifact_validation_id VARCHAR;
