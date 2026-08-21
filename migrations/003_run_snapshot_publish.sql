-- 003_run_snapshot_publish.sql
-- Pipeline run / snapshot / feature artifact / publish skeleton.
-- Design ruling P0-2: the publish contract must be STRUCTURALLY closed in M0 --
-- meta_publish_snapshot binds data_snapshot_id + feature_artifact_set_id +
-- feature_set_version, so artifact tables must exist even while empty.

CREATE TABLE dim_universe (
    universe_id                 VARCHAR NOT NULL,
    universe_version            VARCHAR NOT NULL,
    name                        VARCHAR NOT NULL,
    rule_json                   VARCHAR NOT NULL,
    description                 VARCHAR,
    created_at                  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (universe_id, universe_version)
);

CREATE TABLE meta_pipeline_run (
    pipeline_run_id             VARCHAR PRIMARY KEY,
    run_type                    VARCHAR NOT NULL,      -- EOD / PREOPEN / BACKFILL / REBUILD
    phase                       VARCHAR,
    trade_date_start            DATE,
    trade_date_end              DATE,
    as_of_time                  TIMESTAMPTZ,
    status                      VARCHAR NOT NULL,      -- PENDING/RUNNING/FEATURE_VALIDATED/DEGRADED/FAILED/PUBLISHED
    started_at                  TIMESTAMPTZ,
    ended_at                    TIMESTAMPTZ,
    code_commit                 VARCHAR,
    environment_lock_hash       VARCHAR,
    config_hash                 VARCHAR,
    parent_run_id               VARCHAR,
    error_summary               VARCHAR
);

-- data_snapshot_id identifies the Canonical INPUT knowledge state only.
CREATE TABLE meta_data_snapshot (
    data_snapshot_id            VARCHAR PRIMARY KEY,
    as_of_time                  TIMESTAMPTZ NOT NULL,
    availability_policy_version VARCHAR,
    source_policy_version       VARCHAR,
    schema_version              VARCHAR,
    data_manifest_hash          VARCHAR NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL,
    status                      VARCHAR NOT NULL DEFAULT 'STAGING',  -- STAGING/DATA_VALIDATED/RETIRED
    parent_snapshot_id          VARCHAR,
    note                        VARCHAR
);

CREATE TABLE meta_data_snapshot_component (
    data_snapshot_id            VARCHAR NOT NULL,
    dataset                     VARCHAR NOT NULL,
    partition_key               VARCHAR,
    file_uri                    VARCHAR NOT NULL,      -- logical URI (relative to data_root, POSIX '/')
    content_hash                VARCHAR NOT NULL,
    schema_hash                 VARCHAR NOT NULL,
    row_count                   BIGINT NOT NULL,
    provider                    VARCHAR,
    source_revision             VARCHAR,
    PRIMARY KEY (data_snapshot_id, dataset, file_uri)
);

-- feature_artifact_set_id identifies one immutable Feature OUTPUT batch
-- (files + long-table rowsets) computed from one input snapshot.
CREATE TABLE meta_feature_artifact_set (
    feature_artifact_set_id     VARCHAR PRIMARY KEY,
    data_snapshot_id            VARCHAR NOT NULL,
    feature_set_version         VARCHAR NOT NULL,
    code_commit                 VARCHAR,
    environment_lock_hash       VARCHAR,
    config_hash                 VARCHAR,
    calc_run_id                 VARCHAR,
    artifact_manifest_hash      VARCHAR NOT NULL,
    status                      VARCHAR NOT NULL DEFAULT 'STAGING',  -- STAGING/FEATURE_VALIDATED/RETIRED
    created_at                  TIMESTAMPTZ NOT NULL,
    validated_at                TIMESTAMPTZ
);

CREATE TABLE meta_feature_artifact_component (
    feature_artifact_set_id     VARCHAR NOT NULL,
    layer                       VARCHAR NOT NULL,      -- BASE / DERIVED / FEATURE_AUX_FILE
    feature_family              VARCHAR NOT NULL,
    feature_family_version      VARCHAR NOT NULL,
    partition_key               VARCHAR,
    file_uri                    VARCHAR NOT NULL,      -- logical URI; exact-match comparisons only
    content_hash                VARCHAR NOT NULL,
    schema_hash                 VARCHAR NOT NULL,
    row_count                   BIGINT NOT NULL,
    calc_run_id                 VARCHAR,
    PRIMARY KEY (feature_artifact_set_id, file_uri)
);

-- Publish state machine: PUBLISHED / SUPERSEDED / WITHDRAWN.
-- Application layer enforces "at most one PUBLISHED per trade_date" inside the
-- publish transaction (DuckDB has no partial unique index).
CREATE TABLE meta_publish_snapshot (
    publish_id                  VARCHAR PRIMARY KEY,
    trade_date                  DATE NOT NULL,
    pipeline_run_id             VARCHAR,
    data_snapshot_id            VARCHAR NOT NULL,
    feature_artifact_set_id     VARCHAR NOT NULL,
    feature_set_version         VARCHAR NOT NULL,
    mart_version                VARCHAR,
    published_at                TIMESTAMPTZ,
    status                      VARCHAR NOT NULL,
    quality_grade               VARCHAR,
    previous_publish_id         VARCHAR
);

CREATE TABLE meta_publish_universe (
    publish_id                  VARCHAR NOT NULL,
    universe_id                 VARCHAR NOT NULL,
    universe_version            VARCHAR NOT NULL,
    PRIMARY KEY (publish_id, universe_id)
);
