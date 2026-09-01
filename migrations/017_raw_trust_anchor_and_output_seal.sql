-- 017_raw_trust_anchor_and_output_seal.sql
-- CR-2.3 (audit 20260901, "CR-2.2复审与CR-2.3最终RawTrustAnchor及
-- OutputSeal收口要求" sections 2-4): the raw evidence trust anchor +
-- the expected-output exact set / semantic-value seal.
--
-- meta_raw_evidence_anchor: the AUTHORITATIVE ingestion-time hash of
--   the persisted raw .meta.json EXACT BYTES, recorded OUTSIDE the raw
--   filesystem by the governed ingestion control flow the moment
--   RawWriter commits the meta (meta lands LAST). CR-2 normalization
--   looks up the expected evidence hash HERE before any routing -
--   the runner never treats "the first meta bytes it happens to see"
--   as a trust root, so a first-consume meta-only tamper (surface /
--   endpoint / params / account fields edited while payload hashes
--   stay consistent) fails closed against the anchor.
--
-- meta_provider_normalization_run gains:
--   normalized_output_set_hash - canonical hash over the sorted
--       (output_name, canonical logical uri, content_hash,
--       schema_hash, row_count) tuples of the run's EXACT materialized
--       output set. Three-way bound: ledger == manifest == replay-time
--       physical recompute. Removing a required output from the
--       manifest and rebinding both hashes breaks the exact-set
--       comparison against the CURRENT registry spec.output_names and
--       the ledger seal.
--   normalized_semantic_hash - the semantic identity of the
--       normalized RECORDS (canonical sorted JSON over all output
--       tables). Three-way bound: ledger == manifest == replay-time
--       recompute from the physical parquet values - swapping the
--       parquet for same-schema/same-row-count different VALUES and
--       rebinding content/manifest hashes still breaks it.
--
-- evidence_conflict (migration 016) is DEMOTED to a diagnostic/audit
-- attribute: the CR-2 correctness trust root is the anchor ledger,
-- not the normalization run history. Legacy rows keep their values;
-- legacy raw WITHOUT an anchor fails closed (no auto-grandfathering -
-- a 015-era laundering history can never be silently blessed).

CREATE TABLE IF NOT EXISTS meta_raw_evidence_anchor (
    provider VARCHAR NOT NULL,
    provider_dataset VARCHAR NOT NULL,
    request_id VARCHAR NOT NULL,
    evidence_uri VARCHAR NOT NULL,
    evidence_hash VARCHAR NOT NULL,
    endpoint VARCHAR,
    operation_id VARCHAR,
    normalization_surface VARCHAR,
    payload_kind VARCHAR,
    ingest_run_id VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (provider, provider_dataset, request_id)
);

ALTER TABLE meta_provider_normalization_run ADD COLUMN IF NOT EXISTS normalized_output_set_hash VARCHAR;
ALTER TABLE meta_provider_normalization_run ADD COLUMN IF NOT EXISTS normalized_semantic_hash VARCHAR;
