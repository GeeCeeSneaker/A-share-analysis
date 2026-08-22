-- 007_capability_governance.sql
-- Audit P1-03 (2026-08-22): meta_provider_capability becomes the
-- AUTHORITATIVE capability state; in-memory registry is a cache.
-- Approval must bind the full evidence bundle (spike report + golden
-- cases + provider verification + approver + account profile).

ALTER TABLE meta_provider_capability ADD COLUMN status VARCHAR DEFAULT 'CANDIDATE';
ALTER TABLE meta_provider_capability ADD COLUMN spike_report_ref VARCHAR;
ALTER TABLE meta_provider_capability ADD COLUMN provider_verification_ref VARCHAR;
ALTER TABLE meta_provider_capability ADD COLUMN golden_case_refs VARCHAR;
ALTER TABLE meta_provider_capability ADD COLUMN dry_run_ref VARCHAR;
ALTER TABLE meta_provider_capability ADD COLUMN account_profile_id VARCHAR;
ALTER TABLE meta_provider_capability ADD COLUMN approved_by VARCHAR;
