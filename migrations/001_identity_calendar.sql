-- 001_identity_calendar.sql
-- Core identity and trading-context tables (design ruling P0-2 table set).
-- NOTE: meta_schema_version (the migration ledger itself) is bootstrapped by
-- the migration runner before this file executes; it is the ONLY table not
-- managed as a numbered migration.

CREATE TABLE dim_security (
    security_id         VARCHAR PRIMARY KEY,   -- UUIDv5(PROJECT_SECURITY_NAMESPACE, identity_key)
    identity_key_version VARCHAR NOT NULL DEFAULT 'SECURITY_IDENTITY_V1',
    symbol              VARCHAR NOT NULL,      -- display-only current local code
    initial_symbol      VARCHAR NOT NULL,      -- internal normalized code used in identity key
    exchange            VARCHAR NOT NULL,      -- SSE / SZSE / BSE
    current_name        VARCHAR,               -- display only
    asset_type          VARCHAR NOT NULL,      -- STOCK / ETF / INDEX / ...
    board               VARCHAR,               -- MAIN / CHINEXT / STAR / BSE / ...
    list_date           DATE,                  -- identity key input (frozen after first publish)
    delist_date         DATE,
    currency            VARCHAR NOT NULL DEFAULT 'CNY',
    active              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE bridge_security_provider_symbol (
    security_id         VARCHAR NOT NULL,
    provider            VARCHAR NOT NULL,
    provider_symbol     VARCHAR NOT NULL,
    valid_from          DATE NOT NULL,
    valid_to            DATE,                  -- exclusive; NULL = open interval
    mapping_version     VARCHAR NOT NULL,
    verified_at         TIMESTAMPTZ,
    PRIMARY KEY (provider, provider_symbol, valid_from)
);
-- DQ (V1.3.2 section 6.3, enforced in application layer): for any trade_date,
-- one (provider, provider_symbol) maps to at most one security_id; overlapping
-- intervals are a BLOCK, never auto-resolved to "latest".

CREATE TABLE dim_trade_calendar (
    exchange            VARCHAR NOT NULL,
    trade_date          DATE NOT NULL,
    is_open             BOOLEAN NOT NULL,
    calendar_version    VARCHAR NOT NULL,
    PRIMARY KEY (exchange, trade_date, calendar_version)
);
-- prev/next trade dates are derived via lag/lead, never stored physically.

CREATE TABLE dim_trading_rule (
    exchange            VARCHAR NOT NULL,
    asset_type          VARCHAR NOT NULL,
    board               VARCHAR,
    security_id         VARCHAR,               -- NULL = rule applies at class level
    valid_from          DATE NOT NULL,
    valid_to            DATE,
    price_tick          DOUBLE NOT NULL,       -- price comparison tolerance source
    has_price_limit     BOOLEAN NOT NULL,
    up_limit_rule       VARCHAR,
    down_limit_rule     VARCHAR,
    rule_version        VARCHAR NOT NULL,
    PRIMARY KEY (exchange, asset_type, valid_from, rule_version)
);
