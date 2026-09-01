-- 019_canonical_replay_seal.sql
-- CR-3.1 (audit 20260901 "CR-3复审与CR-3.1最终CanonicalInputSnapshot及ReplaySeal
-- 收口要求" sections 1/5/7): canonical run identity / replay seal closure.
--
-- meta_canonicalization_run gains:
--   requested_domains_json  - the deduped, sorted exact domain set of the
--                              run (P0-01: the requested domain set is part
--                              of the canonical run identity; requesting
--                              daily_bar must never replay a trade_calendar
--                              run's artifacts)
--   requested_domains_hash  - canonical hash of that set
--   selected_semantic_hash  - replay-time physical recompute seal of the
--                             selected rows (P0-07: selected.parquet values
--                             are re-derived and compared three-way:
--                             ledger == manifest == physical)
--   decision_set_hash       - replay-time physical recompute seal of the
--                             decision rows (same three-way consumption)
--
-- The ledger already carries input_set_hash / identity_dataset_hash /
-- policy identities / code_fingerprint / finding_set_hash; 019 does not
-- modify 018.

ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS requested_domains_json VARCHAR;
ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS requested_domains_hash VARCHAR;
ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS selected_semantic_hash VARCHAR;
ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS decision_set_hash VARCHAR;
