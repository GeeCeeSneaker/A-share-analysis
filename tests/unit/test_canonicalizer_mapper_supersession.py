from __future__ import annotations

import duckdb

from ashare_state.canonical.canonicalizer import CanonicalRunner
from ashare_state.normalization.registry import MAPPER_CODE_FINGERPRINT


def _run_row(run_id: str, request_id: str, mapper_hash: str) -> tuple[object, ...]:
    return (
        run_id,
        "amazingdata",
        "cr2",
        "history_stock_status",
        "InfoData.get_history_stock_status",
        request_id,
        f"provider=amazingdata/dataset=history_stock_status/{request_id}.meta.json",
        "a" * 64,
        "cr2.1-v1",
        "mapper-v1",
        mapper_hash,
        f"provider=amazingdata/dataset=history_stock_status/raw_request={request_id}/contract=cr2.1-v1/run={run_id}/manifest.json",
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "SUCCESS",
    )


def _runner(conn: duckdb.DuckDBPyConnection, tmp_path) -> CanonicalRunner:
    conn.execute(
        "CREATE TABLE meta_provider_normalization_run ("
        "normalization_run_id VARCHAR, provider VARCHAR, normalization_surface VARCHAR, "
        "provider_dataset VARCHAR, endpoint VARCHAR, raw_request_id VARCHAR, "
        "raw_evidence_uri VARCHAR, raw_evidence_hash VARCHAR, "
        "normalization_contract_version VARCHAR, mapper_identity VARCHAR, "
        "mapper_code_hash VARCHAR, normalized_manifest_uri VARCHAR, "
        "normalized_manifest_hash VARCHAR, normalized_output_set_hash VARCHAR, "
        "normalized_semantic_hash VARCHAR, status VARCHAR)"
    )
    return CanonicalRunner(conn, raw_root=tmp_path, normalized_root=tmp_path)


def test_current_mapper_replay_supersedes_only_same_request_stale_run(tmp_path) -> None:
    conn = duckdb.connect(":memory:")
    runner = _runner(conn, tmp_path)
    conn.executemany(
        "INSERT INTO meta_provider_normalization_run VALUES (" + ",".join("?" * 16) + ")",
        [
            _run_row("old-run", "request-replayed", "0" * 64),
            _run_row("current-run", "request-replayed", MAPPER_CODE_FINGERPRINT),
            _run_row("stale-only-run", "request-without-replay", "1" * 64),
        ],
    )

    rows = runner._surface_runs("cr2", ("history_stock_status",))

    assert [row["normalization_run_id"] for row in rows] == [
        "current-run",
        "stale-only-run",
    ]
    conn.close()
