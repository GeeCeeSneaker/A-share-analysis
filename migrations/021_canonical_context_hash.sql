-- 021_canonical_context_hash.sql
-- CR-3.3 (audit 20260902 "CR-3.2复审与CR-3.3最终HistoricalInputContinuity
-- 及VerificationEvidence收口要求" section 1): canonical historical input
-- continuity guard.
--
-- meta_canonicalization_run gains:
--   canonical_context_hash - the REQUEST-WORLD identity (requested domain
--                             set + as_of + contract + availability/source/
--                             tolerance policy identities + identity bridge
--                             policy identity + canonical code fingerprint).
--                             Deliberately EXCLUDES the current CR-2 input
--                             set and the verification state: the historical
--                             SUCCESS continuity guard must still find a
--                             prior SUCCESS after its consumed CR-2 inputs
--                             disappear / drift in the ledger (which changes
--                             the base identity but never the request world).
--
-- Migration 020 is untouched.

ALTER TABLE meta_canonicalization_run ADD COLUMN IF NOT EXISTS canonical_context_hash VARCHAR;
