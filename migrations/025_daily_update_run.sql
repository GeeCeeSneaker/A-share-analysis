-- Bind an accepted daily-update operation to the existing Snapshot authority.
-- This is an operational receipt, not a second fact store.
CREATE TABLE meta_daily_update_run (
    update_run_id          VARCHAR PRIMARY KEY,
    through_date           DATE NOT NULL,
    base_snapshot_id       VARCHAR NOT NULL,
    snapshot_id            VARCHAR NOT NULL,
    manifest_uri           VARCHAR,
    manifest_hash          VARCHAR,
    repository_commit_sha  VARCHAR NOT NULL,
    worktree_dirty         BOOLEAN NOT NULL,
    session_count          INTEGER NOT NULL,
    expected_member_count  BIGINT NOT NULL,
    returned_bar_count     BIGINT NOT NULL,
    status                 VARCHAR NOT NULL,
    started_at             TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at           TIMESTAMP WITH TIME ZONE NOT NULL,
    CHECK (status IN ('BASELINE', 'SUCCESS')),
    CHECK (worktree_dirty = FALSE),
    CHECK (length(manifest_hash) = 64),
    CHECK (length(repository_commit_sha) = 40),
    CHECK (session_count >= 0),
    CHECK (expected_member_count >= 0),
    CHECK (returned_bar_count >= 0),
    CHECK (completed_at >= started_at)
);

CREATE INDEX idx_daily_update_through_date
    ON meta_daily_update_run (through_date, completed_at);
