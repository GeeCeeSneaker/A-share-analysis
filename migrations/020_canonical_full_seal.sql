-- 020_canonical_full_seal.sql
-- CR-3.2 (audit 20260901 "CR-3.1复审与CR-3.2最终TransactionalSnapshot及
-- PolicyExecution收口要求" sections 4/5): canonical full seal + verification
-- state transition columns.
--
-- meta_canonicalization_run gains:
--   base_identity_hash          - the deterministic identity WITHOUT the
--                                 verification state (requested set + input
--                                 entries + identity hash + as_of + contract
--                                 + policies + code fingerprint). Used to
--                                 locate historical runs of the SAME input
--                                 world across verification-state changes.
--   verification_state_hash     - canonical hash over the per-input-run
--                                 verification outcomes of the snapshot.
--                                 Together with base_identity_hash it forms
--                                 the run id: an exact upstream repair (same
--                                 base, healthy state again... or changed
--                                 state) yields a NEW run identity instead
--                                 of replaying a stale BLOCKED run, while a
--                                 SUCCESS run degraded by damage is refused
--                                 (DAMAGED), never silently replaced.
--   input_seal_hash             - canonical hash over the TYPED full CR-2
--                                 seal of every input run (incl. contract
--                                 version / mapper identity + code hash /
--                                 manifest + output-set + semantic seals /
--                                 status / raw identity) - the exact input
--                                 binding consumed three-way by snapshot /
--                                 manifest / ledger on replay.
--   identity_master_input_set_hash - the PIT-available identity master run
--                                 set hash (future masters are discovered
--                                 evidence but never enter the bridge).
--
-- The ledger already carries the CR-3/CR-3.1 columns; 020 does not modify
-- 018/019.

ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS base_identity_hash VARCHAR;
ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS verification_state_hash VARCHAR;
ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS input_seal_hash VARCHAR;
ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS identity_master_input_set_hash VARCHAR;
