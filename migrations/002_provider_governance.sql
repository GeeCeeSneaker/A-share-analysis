-- 002_provider_governance.sql
-- Provider metadata & source governance tables (schema only in M0;
-- meta_source_policy logic activates in P0b per design ruling).

CREATE TABLE meta_data_source (
    source_id                   VARCHAR PRIMARY KEY,   -- e.g. 'amazingdata.history_stock_status'
    provider                    VARCHAR NOT NULL,
    dataset                     VARCHAR NOT NULL,
    history_start               DATE,
    update_policy               VARCHAR NOT NULL,      -- EOD / PREOPEN / IRREGULAR / STREAM
    conservative_available_time TIME,                  -- historical PIT conservative rule
    point_in_time_grade         VARCHAR NOT NULL,      -- A / B / C
    observation_type            VARCHAR NOT NULL,      -- DIRECT / DERIVED / PROVIDER_DERIVED / SEMANTIC_LABEL
    permission_note             VARCHAR,
    verified_at                 TIMESTAMPTZ,
    note                        VARCHAR
);

CREATE TABLE meta_provider_capability (
    provider                    VARCHAR NOT NULL,
    capability                  VARCHAR NOT NULL,      -- DAILY_BAR / MINUTE_BAR / HIST_L1 / ...
    asset_class                 VARCHAR,
    frequency                   VARCHAR,
    history_supported           BOOLEAN,
    realtime_supported          BOOLEAN,
    point_in_time_grade         VARCHAR,
    permission_note             VARCHAR,
    transport                   VARCHAR,
    adapter_version             VARCHAR,
    verified_at                 TIMESTAMPTZ,
    PRIMARY KEY (provider, capability)
);

CREATE TABLE meta_provider_field_map (
    provider                    VARCHAR NOT NULL,
    dataset                     VARCHAR NOT NULL,
    source_field                VARCHAR NOT NULL,
    canonical_field             VARCHAR NOT NULL,
    source_unit                 VARCHAR,
    canonical_unit              VARCHAR,
    transform_rule              VARCHAR,
    timezone                    VARCHAR,
    null_policy                 VARCHAR,
    mapping_version             VARCHAR NOT NULL,
    verified_at                 TIMESTAMPTZ,
    PRIMARY KEY (provider, dataset, source_field, mapping_version)
);

-- Source Policy: governed config, NOT a runtime switch (V1.3.2 section 6.37).
-- M0 creates schema only; APPROVED entries and overlap checks activate in P0b.
-- Until Provider Spike passes, primaries stay CANDIDATE.
CREATE TABLE meta_source_policy (
    source_policy_version       VARCHAR NOT NULL,
    policy_entry_id             VARCHAR NOT NULL,
    policy_status               VARCHAR NOT NULL DEFAULT 'CANDIDATE',
    canonical_dataset           VARCHAR NOT NULL,
    canonical_field_or_group    VARCHAR NOT NULL,
    selection_scope             VARCHAR NOT NULL,      -- DATASET / FIELD / FUSED_DATASET
    priority_order_json         VARCHAR,
    fusion_rule_id              VARCHAR,
    required_observation_type   VARCHAR,
    min_pit_grade               VARCHAR,
    tolerance_rule_id           VARCHAR,
    fallback_policy             VARCHAR,
    conflict_action             VARCHAR NOT NULL,      -- BLOCK / QUARANTINE / WARN
    valid_from                  DATE NOT NULL,
    valid_to                    DATE,
    rationale                   VARCHAR,
    created_at                  TIMESTAMPTZ NOT NULL,
    approved_at                 TIMESTAMPTZ,
    PRIMARY KEY (source_policy_version, policy_entry_id)
);

CREATE TABLE meta_tolerance_rule (
    tolerance_rule_id           VARCHAR NOT NULL,
    dataset                     VARCHAR NOT NULL,
    field_name                  VARCHAR NOT NULL,
    comparison_type             VARCHAR NOT NULL,      -- ABS / REL / PRICE_TICK / EXACT / ENUM_EQ
    abs_tolerance               DOUBLE,
    rel_tolerance               DOUBLE,
    price_tick_multiplier       DOUBLE,
    null_equivalence_rule       VARCHAR,
    severity_on_fail            VARCHAR NOT NULL,
    rule_version                VARCHAR NOT NULL,
    rationale                   VARCHAR,
    PRIMARY KEY (tolerance_rule_id, rule_version)
);

CREATE TABLE meta_ingest_run (
    run_id                      VARCHAR PRIMARY KEY,
    pipeline_run_id             VARCHAR,
    source_id                   VARCHAR NOT NULL,
    partition_key               VARCHAR,
    trade_date_start            DATE,
    trade_date_end              DATE,
    started_at                  TIMESTAMPTZ,
    ended_at                    TIMESTAMPTZ,
    status                      VARCHAR NOT NULL,
    row_count                   BIGINT,
    bytes_received              BIGINT,
    request_count               BIGINT,
    credits_used                DOUBLE,
    retry_count                 BIGINT DEFAULT 0,
    checkpoint                  VARCHAR,
    error                       VARCHAR,
    content_hash                VARCHAR
);
