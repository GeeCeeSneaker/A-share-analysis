-- 004_feature_governance.sql
-- Lightweight Feature Set Registry (design ruling P0-3): feature_set_version
-- must be resolvable to an auditable member list BEFORE the first
-- feature_artifact_set is created (required by P0a, built in M0).

CREATE TABLE meta_feature_set (
    feature_set_version         VARCHAR PRIMARY KEY,
    definition_hash             VARCHAR NOT NULL,      -- hash over sorted member definitions
    status                      VARCHAR NOT NULL,      -- DRAFT / ACTIVE / RETIRED
    created_at                  TIMESTAMPTZ NOT NULL,
    note                        VARCHAR
);

CREATE TABLE meta_feature_set_member (
    feature_set_version         VARCHAR NOT NULL,
    feature_id                  VARCHAR NOT NULL,
    feature_version             VARCHAR NOT NULL,
    param_set_id                VARCHAR NOT NULL,
    PRIMARY KEY (feature_set_version, feature_id, feature_version, param_set_id)
);
-- definition_hash is computed from members sorted by
-- (feature_id, feature_version, param_set_id) so it never depends on
-- insertion order (design ruling P0-3).
