-- 006_canonical_governance_hardening.sql
-- Audit P0-05 + P1-16 (2026-08-22). Never modify applied 005.
--
-- Adds the Frozen-Baseline canonical governance columns that 005 lacked:
--   provider_dataset      which provider dataset fed this row
--   observation_type      provider observation kind literal
--   availability_kind     OBSERVED | CONSERVATIVE_ASSUMED (PIT proof)
--   data_version          provider data version (revision identity)
--   schema_version        provider-normalized schema version
--   selection_reason      why Source Policy selected this provider row
--
-- availability_kind rule: when the real availability moment is unknown
-- (historical backfill), available_at is computed from the versioned
-- Conservative Availability Policy and availability_kind is
-- CONSERVATIVE_ASSUMED. A NULL available_at is NOT a valid state for a
-- published fact - it means the row is not yet validated.
--
-- P1-16: pipeline runs now LOCK the source/availability policy versions
-- they executed under (Frozen Baseline backfill requirement).

ALTER TABLE fact_daily_bar            ADD COLUMN provider_dataset VARCHAR;
ALTER TABLE fact_daily_bar            ADD COLUMN observation_type VARCHAR;
ALTER TABLE fact_daily_bar            ADD COLUMN availability_kind VARCHAR DEFAULT 'CONSERVATIVE_ASSUMED' /* NOT NULL enforced by service invariant: DuckDB cannot ADD COLUMN with constraint */;
ALTER TABLE fact_daily_bar            ADD COLUMN data_version VARCHAR;
ALTER TABLE fact_daily_bar            ADD COLUMN schema_version VARCHAR;
ALTER TABLE fact_daily_bar            ADD COLUMN selection_reason VARCHAR;

ALTER TABLE fact_security_status_daily ADD COLUMN provider_dataset VARCHAR;
ALTER TABLE fact_security_status_daily ADD COLUMN observation_type VARCHAR;
ALTER TABLE fact_security_status_daily ADD COLUMN availability_kind VARCHAR DEFAULT 'CONSERVATIVE_ASSUMED' /* NOT NULL enforced by service invariant: DuckDB cannot ADD COLUMN with constraint */;
ALTER TABLE fact_security_status_daily ADD COLUMN data_version VARCHAR;
ALTER TABLE fact_security_status_daily ADD COLUMN schema_version VARCHAR;
ALTER TABLE fact_security_status_daily ADD COLUMN selection_reason VARCHAR;

ALTER TABLE fact_limit_price           ADD COLUMN provider_dataset VARCHAR;
ALTER TABLE fact_limit_price           ADD COLUMN observation_type VARCHAR;
ALTER TABLE fact_limit_price           ADD COLUMN availability_kind VARCHAR DEFAULT 'CONSERVATIVE_ASSUMED' /* NOT NULL enforced by service invariant: DuckDB cannot ADD COLUMN with constraint */;
ALTER TABLE fact_limit_price           ADD COLUMN data_version VARCHAR;
ALTER TABLE fact_limit_price           ADD COLUMN schema_version VARCHAR;
ALTER TABLE fact_limit_price           ADD COLUMN selection_reason VARCHAR;

ALTER TABLE fact_adj_factor            ADD COLUMN provider_dataset VARCHAR;
ALTER TABLE fact_adj_factor            ADD COLUMN observation_type VARCHAR;
ALTER TABLE fact_adj_factor            ADD COLUMN availability_kind VARCHAR DEFAULT 'CONSERVATIVE_ASSUMED' /* NOT NULL enforced by service invariant: DuckDB cannot ADD COLUMN with constraint */;
ALTER TABLE fact_adj_factor            ADD COLUMN data_version VARCHAR;
ALTER TABLE fact_adj_factor            ADD COLUMN schema_version VARCHAR;
ALTER TABLE fact_adj_factor            ADD COLUMN selection_reason VARCHAR;

ALTER TABLE fact_corporate_action      ADD COLUMN provider_dataset VARCHAR;
ALTER TABLE fact_corporate_action      ADD COLUMN observation_type VARCHAR;
ALTER TABLE fact_corporate_action      ADD COLUMN availability_kind VARCHAR DEFAULT 'CONSERVATIVE_ASSUMED' /* NOT NULL enforced by service invariant: DuckDB cannot ADD COLUMN with constraint */;
ALTER TABLE fact_corporate_action      ADD COLUMN data_version VARCHAR;
ALTER TABLE fact_corporate_action      ADD COLUMN schema_version VARCHAR;
ALTER TABLE fact_corporate_action      ADD COLUMN selection_reason VARCHAR;

-- P1-16: policy-version locking on pipeline runs (backfill reproducibility)
ALTER TABLE meta_pipeline_run          ADD COLUMN source_policy_version VARCHAR;
ALTER TABLE meta_pipeline_run          ADD COLUMN availability_policy_version VARCHAR;
