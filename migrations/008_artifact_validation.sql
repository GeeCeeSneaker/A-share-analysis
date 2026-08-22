-- 008_artifact_validation.sql
-- Round-2 audit R2-P0-05 (2026-08-22): artifact validation records make the
-- fallback / blocking-DQ publish gate a SYSTEM invariant instead of a
-- caller assertion.

CREATE TABLE meta_artifact_validation (
    feature_artifact_set_id     VARCHAR PRIMARY KEY,
    validation_version          VARCHAR NOT NULL,
    identity_fallback_count     INTEGER NOT NULL,
    blocking_dq_count           INTEGER NOT NULL,
    validated_at                TIMESTAMPTZ NOT NULL,
    validator_code_commit       VARCHAR,
    validation_hash             VARCHAR,
    details_json                VARCHAR
);

-- R2-P0-06: full lineage binding. publish gate compares
-- artifact.calc_run_id == run, run/artifact (code_commit, env lock, config)
-- and run/snapshot (source & availability policy versions). 003 already
-- carries those columns; no schema change needed for them.
