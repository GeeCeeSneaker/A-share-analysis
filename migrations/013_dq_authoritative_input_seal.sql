-- 013_dq_authoritative_input_seal.sql
-- R4-B2.3 (audit 20260831): checker-specific authoritative input seal.
--
-- The completion proof previously sealed only the scanned component
-- manifest - but the IDENTITY_FALLBACK checker also reads
-- dim_security.identity_key_version and the BLOCKING_DQ checker reads
-- the artifact's bound snapshot + canonical fact quality_flags. Any
-- of those inputs can change AFTER a genuine zero scan while the
-- component manifest stays identical (stale proof -> false PASS).
--
-- meta_artifact_check_execution gains:
--   authoritative_input_hash  - checker-specific fingerprint of the
--                               EXACT inputs the evaluator consumed
--                               (machine-recomputable, stable, never
--                               caller-supplied)
--   scanned_data_snapshot_id  - explicit audit record of the snapshot
--                               the BLOCKING_DQ evaluator scanned
--
-- Legacy rows without the input seal are NOT proof-compatible:
-- the validator fails closed on them (rescan + revalidation
-- required, no grandfather).

ALTER TABLE meta_artifact_check_execution ADD COLUMN IF NOT EXISTS authoritative_input_hash VARCHAR;
ALTER TABLE meta_artifact_check_execution ADD COLUMN IF NOT EXISTS scanned_data_snapshot_id VARCHAR;
