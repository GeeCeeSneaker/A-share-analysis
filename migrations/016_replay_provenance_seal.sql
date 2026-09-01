-- 016_replay_provenance_seal.sql
-- CR-2.2 (audit 20260901, "CR-2.1复审与CR-2.2最终ReplayProvenanceSeal
-- 收口要求" sections 3-4): raw-evidence binding conflict marking +
-- full provenance seal.
--
-- meta_provider_normalization_run gains:
--   evidence_conflict - TRUE iff this run was BLOCKED specifically
--                       because its raw evidence hash did not match the
--                       request's existing trusted raw binding (an
--                       INCIDENT HARD BLOCK, audit section 3.4 Option A).
--                       Conflict runs are recorded for audit but NEVER
--                       become the request's raw-evidence baseline: a
--                       tampered meta hash cannot be legitimized by the
--                       very BLOCK run that observed it.
--
-- Legacy rows default FALSE - every pre-016 run binds the hash it read,
-- which is exactly the trusted-baseline semantics.

ALTER TABLE meta_provider_normalization_run
    ADD COLUMN IF NOT EXISTS evidence_conflict BOOLEAN DEFAULT FALSE;
