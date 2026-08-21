-- 005_canonical_facts.sql
-- Canonical selected-layer DDL for FIVE fact domains (task book section 8).
-- Discipline:
--   * provider-normalized rows are routed by FACT DOMAIN (task book 1.3);
--     one provider endpoint (get_history_stock_status) feeds THREE tables.
--   * reconciliation_status defaults to NOT_RUN_NO_SECONDARY while no
--     second source exists (task book 9); single-source validation is a
--     SEPARATE quality_flags concept, never a PASS.
--   * units are CANONICAL in these tables (shares / CNY); unit conversion
--     happens in the provider mapper via meta_provider_field_map, whose
--     unit map itself is evidence-gated by Spike B5.
--   * every row carries data_snapshot_id for full lineage.

CREATE TABLE IF NOT EXISTS fact_daily_bar (
    data_snapshot_id      VARCHAR NOT NULL,
    security_id           VARCHAR NOT NULL,
    trade_date            DATE    NOT NULL,
    open                  DOUBLE,
    high                  DOUBLE,
    low                   DOUBLE,
    close                 DOUBLE,
    pre_close             DOUBLE,
    volume_shares         BIGINT,          -- canonical unit: shares
    amount_cny            DOUBLE,          -- canonical unit: CNY
    selected_provider     VARCHAR NOT NULL,
    source_policy_version VARCHAR NOT NULL,
    source_revision       VARCHAR,
    reconciliation_status VARCHAR NOT NULL DEFAULT 'NOT_RUN_NO_SECONDARY',
    available_at          TIMESTAMPTZ,
    quality_flags         VARCHAR,
    ingested_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (data_snapshot_id, security_id, trade_date)
);

CREATE TABLE IF NOT EXISTS fact_security_status_daily (
    data_snapshot_id      VARCHAR NOT NULL,
    security_id           VARCHAR NOT NULL,
    trade_date            DATE    NOT NULL,
    is_listed             BOOLEAN,
    is_st                 BOOLEAN,
    is_suspended          BOOLEAN,
    is_delisting_period   BOOLEAN,
    trading_status        VARCHAR,         -- provider-coded status literal
    selected_provider     VARCHAR NOT NULL,
    source_policy_version VARCHAR NOT NULL,
    source_revision       VARCHAR,
    reconciliation_status VARCHAR NOT NULL DEFAULT 'NOT_RUN_NO_SECONDARY',
    available_at          TIMESTAMPTZ,
    quality_flags         VARCHAR,
    ingested_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (data_snapshot_id, security_id, trade_date)
);

CREATE TABLE IF NOT EXISTS fact_limit_price (
    data_snapshot_id      VARCHAR NOT NULL,
    security_id           VARCHAR NOT NULL,
    trade_date            DATE    NOT NULL,
    pre_close             DOUBLE,
    up_limit              DOUBLE,
    down_limit            DOUBLE,
    has_price_limit       BOOLEAN,         -- false on no-limit days (IPO etc.)
    limit_rule_id         VARCHAR,         -- dim_trading_rule reference
    selected_provider     VARCHAR NOT NULL,
    source_policy_version VARCHAR NOT NULL,
    source_revision       VARCHAR,
    reconciliation_status VARCHAR NOT NULL DEFAULT 'NOT_RUN_NO_SECONDARY',
    available_at          TIMESTAMPTZ,
    quality_flags         VARCHAR,
    ingested_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (data_snapshot_id, security_id, trade_date)
);

CREATE TABLE IF NOT EXISTS fact_adj_factor (
    data_snapshot_id      VARCHAR NOT NULL,
    security_id           VARCHAR NOT NULL,
    trade_date            DATE    NOT NULL,  -- ex date
    adj_factor            DOUBLE NOT NULL,
    factor_type           VARCHAR NOT NULL,  -- SINGLE | BACKWARD
    effective_date        DATE,
    selected_provider     VARCHAR NOT NULL,
    source_policy_version VARCHAR NOT NULL,
    source_revision       VARCHAR,
    reconciliation_status VARCHAR NOT NULL DEFAULT 'NOT_RUN_NO_SECONDARY',
    available_at          TIMESTAMPTZ,
    quality_flags         VARCHAR,
    ingested_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (data_snapshot_id, security_id, trade_date, factor_type)
);

CREATE TABLE IF NOT EXISTS fact_corporate_action (
    data_snapshot_id      VARCHAR NOT NULL,
    security_id           VARCHAR NOT NULL,
    event_date            DATE,
    ex_date               DATE    NOT NULL,
    event_type            VARCHAR NOT NULL,  -- DIVIDEND | RIGHT_ISSUE | SPLIT | ...
    is_ex_dividend        BOOLEAN NOT NULL DEFAULT FALSE,
    is_ex_rights          BOOLEAN NOT NULL DEFAULT FALSE,
    provider_fields_json  VARCHAR,           -- faithful provider extras
    selected_provider     VARCHAR NOT NULL,
    source_policy_version VARCHAR NOT NULL,
    source_revision       VARCHAR,
    available_at          TIMESTAMPTZ,
    quality_flags         VARCHAR,
    ingested_at           TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (data_snapshot_id, security_id, ex_date, event_type)
);
