-- 015_normalization_surface_closure.sql
-- CR-2.1 (audit 20260831, CR-2.1 sections 2-5): final normalization
-- surface identity + replay verification + commit closure.
--
-- meta_provider_normalization_run gains:
--   normalization_surface - the SYSTEM-DERIVED business surface persisted
--                           by the provider facade on the raw envelope
--                           (capability identity, never a request-param
--                           guess). Disambiguates surfaces that share one
--                           (provider_dataset, endpoint) pair - stock
--                           daily_bar and index daily_bar both ride
--                           MarketData.query_kline.
--   mapper_code_hash     - the governed mapper implementation fingerprint
--                          (SHA-256 over the mapper + DTO module sources)
--                          entering the exact run identity: a mapper code
--                          change yields a NEW run identity without anyone
--                          remembering to bump a version string.
--   quarantine_set_hash  - canonical hash over the sorted semantic
--                          quarantine records of the run - the run's
--                          quarantine evidence is sealed as an exact set;
--                          UPDATE/DELETE/missing rows become detectable
--                          from the run manifest/ledger binding alone.
--
-- Legacy CR-2 rows (migration 014) keep NULL here: they predate the
-- surface identity and are never silently replay-verified as healthy
-- (the runner fails closed on rows missing the seal columns).

ALTER TABLE meta_provider_normalization_run ADD COLUMN IF NOT EXISTS normalization_surface VARCHAR;
ALTER TABLE meta_provider_normalization_run ADD COLUMN IF NOT EXISTS mapper_code_hash VARCHAR;
ALTER TABLE meta_provider_normalization_run ADD COLUMN IF NOT EXISTS quarantine_set_hash VARCHAR;
