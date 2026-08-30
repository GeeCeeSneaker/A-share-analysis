-- 012_publish_validation_closure.sql
-- R4-B2.1 (audit 20260830): final validation truth + transaction closure.
--
-- meta_artifact_check_execution: POSITIVE execution proof for the DQ
-- required checks (P0-01). A row records that a governed scan RAN:
-- which check, over which exact component identity, under which scan
-- contract, by which producer, completed when. It deliberately carries
-- NO count and NO result - findings remain append-only facts in
-- meta_artifact_dq_finding and the validator DERIVES the counts.
-- absence of bad findings is therefore never proof of zero findings:
-- without a matching execution proof bound to the CURRENT component
-- manifest the required check is NOT_TESTABLE (blocking).

CREATE TABLE meta_artifact_check_execution (
    execution_id                     VARCHAR NOT NULL,
    feature_artifact_set_id          VARCHAR NOT NULL,
    check_id                         VARCHAR NOT NULL,   -- IDENTITY_FALLBACK_ZERO / BLOCKING_DQ_ZERO
    scan_contract_version            VARCHAR NOT NULL,   -- DQ scan contract identity
    producer                         VARCHAR NOT NULL,   -- runner identity (code commit / runner id)
    scanned_component_manifest_hash  VARCHAR NOT NULL,   -- EXACT scan input identity
    completed_at                     TIMESTAMPTZ NOT NULL,
    detail                           VARCHAR,
    PRIMARY KEY (execution_id)
);
