-- 009_universe_activation.sql
-- Audit R2-P1-11: universe activation ledger (rule_hash immutability).

CREATE TABLE IF NOT EXISTS universe_activation (
    universe_id        VARCHAR NOT NULL,
    universe_version   VARCHAR NOT NULL,
    rule_hash          VARCHAR NOT NULL,
    activated_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (universe_id, universe_version)
);
