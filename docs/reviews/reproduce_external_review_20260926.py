"""Offline diagnostics for the 2026-09-26 external review.

Run from a locked project environment. All market rows are synthetic and all
databases/artifacts live in a TemporaryDirectory. No provider or account access.
These observations describe the reviewed baseline; they are not tests that a
future implementation must keep passing. --wheel optionally checks a locally
built wheel, with the current environment supplying its locked dependencies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import duckdb
import polars as pl

from ashare_state.features.engine import compute_feature_set
from ashare_state.features.registry import FEATURE_SET_ID, get_feature_set
from ashare_state.providers.amazingdata.timeout import RetryPolicy, TimeBudget, run_with_budget
from ashare_state.providers.errors import ProviderNetworkError
from ashare_state.research import IdentityView, ResearchPanelBuilder, ResearchPanelReader
from ashare_state.research.eligibility import evaluate_daily_bar
from ashare_state.research.models import IdentityRecord, ResearchSplit
from ashare_state.storage.migrations import MigrationTamperedError, apply_migrations


def source_row(day: date) -> dict:
    return {
        "canonical_domain": "daily_bar",
        "canonical_key": json.dumps(["review-security", day.isoformat()], separators=(",", ":")),
        "security_id": "review-security",
        "trade_date": day,
        "available_at": datetime(2026, 7, 1, 8, tzinfo=UTC),
        "canonical_run_id": "review-canonical",
        "snapshot_id": "review-snapshot",
        "source_row_identity_hash": f"synthetic-{day.isoformat()}",
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "pre_close": 10.0,
        "volume": 100.0,
        "amount": 1050.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="Locally built ashare_state wheel")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    evidence = {
        "reviewed_baseline": "76e8581701098da9896309cd976f62207a3b0510",
        "python": sys.version.split()[0],
        "synthetic_only": True,
    }
    with tempfile.TemporaryDirectory(prefix="ashare-external-review-") as td:
        root = Path(td)
        lf, crlf = root / "lf", root / "crlf"
        lf.mkdir()
        crlf.mkdir()
        name = "001_identity_calendar.sql"
        sql = (repo / "migrations" / name).read_bytes().replace(b"\r\n", b"\n")
        (lf / name).write_bytes(sql)
        (crlf / name).write_bytes(sql.replace(b"\n", b"\r\n"))
        db = duckdb.connect(str(root / "migration.duckdb"))
        try:
            apply_migrations(db, lf)
            try:
                apply_migrations(db, crlf)
                outcome = "accepted"
            except MigrationTamperedError:
                outcome = "MigrationTamperedError"
            evidence["migration_eol"] = {
                "sql_text_equal": (lf / name).read_text() == (crlf / name).read_text(),
                "outcome": outcome,
            }
        finally:
            db.close()

        rows = [source_row(date(2020, 1, 2)), source_row(date(2020, 1, 3))]
        identity = IdentityView.from_rows(
            [
                {
                    "security_id": "review-security",
                    "symbol": "600000",
                    "exchange": "SSE",
                    "valid_from": "1999-01-01",
                }
            ],
            version="external-review-fixture",
        )
        builder = ResearchPanelBuilder(
            None,
            raw_root=root / "raw",
            normalized_root=root / "normalized",
            research_root=root / "research",
        )
        built = builder._build_fixture_from_rows(
            rows,
            source_snapshot_id="review-snapshot",
            source_snapshot_as_of="2026-09-01T00:00:00+00:00",
            source_canonical_run_id="review-canonical",
            source_readmodel_contract_version="readmodel-v1",
            source_snapshot_manifest_hash="a" * 64,
            source_snapshot_semantic_hash="b" * 64,
            identity_view=identity,
            build_timestamp="2026-09-26T00:00:00+00:00",
        )
        reader = ResearchPanelReader.from_manifest(
            root / "research" / built.manifest_uri,
            allow_test_fixture=True,
        )
        calls = []
        original_read = pl.read_parquet

        def traced_read(*positional, **keywords):
            frame = original_read(*positional, **keywords)
            calls.append({"rows": frame.height, "columns": frame.width, "reader_kwargs": keywords})
            return frame

        with patch("ashare_state.research.reader.pl.read_parquet", side_effect=traced_read):
            selected = reader.load_security_daily(
                split="development",
                start="2020-01-02",
                end="2020-01-02",
                security_ids=["review-security"],
                columns=["close"],
            )
        evidence["r1_filter_pushdown"] = {
            "parquet_reads": calls,
            "returned_rows": selected.height,
            "returned_columns": selected.width,
        }
        evidence["r1_time_basis"] = {
            "trade_date": rows[0]["trade_date"].isoformat(),
            "available_at": rows[0]["available_at"].isoformat(),
            "default_reader_returns_row": selected.height == 1,
            "fixture_only": True,
        }

        zero = source_row(date(2020, 1, 2))
        zero.update(dict.fromkeys(("open", "high", "low", "close", "volume", "amount"), 0.0))
        decision = evaluate_daily_bar(
            zero,
            split=ResearchSplit.DEVELOPMENT,
            identity=IdentityRecord("review-security", "600000", "SSE", date(1999, 1, 1)),
        )
        computed = compute_feature_set(
            [zero],
            snapshot_id="review-snapshot",
            canonical_run_id="review-canonical",
            feature_run_id="external-review-fixture",
            feature_set=get_feature_set(FEATURE_SET_ID),
            snapshot_as_of=datetime(2026, 9, 1, tzinfo=UTC),
        )
        evidence["zero_price"] = {
            "eligibility": decision.eligibility.value,
            "quality": decision.data_quality_state.value,
            "raw_return_1": computed.security_rows[0]["raw_return_1"],
            "valid_raw_return_count": computed.market_rows[0]["valid_raw_return_count"],
            "mean_raw_return_observed": computed.market_rows[0]["mean_raw_return_observed"],
        }

        if args.wheel:
            install = root / "wheel_install"
            with zipfile.ZipFile(args.wheel.resolve()) as archive:
                names = archive.namelist()
                archive.extractall(install)
            command = (
                "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                "from ashare_state.cli import init_db; init_db(db_path=Path(sys.argv[2]))"
            )
            completed = subprocess.run(
                [sys.executable, "-c", command, str(install), str(root / "wheel.duckdb")],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            evidence["wheel"] = {
                "sql_file_count": sum(name.endswith(".sql") for name in names),
                "init_db_exit": completed.returncode,
                "migration_directory_missing": "migrations directory not found" in completed.stderr,
            }

    clock = {"now": 0.0, "attempts": 0}

    def attempt():
        clock["attempts"] += 1
        if clock["attempts"] == 1:
            raise ProviderNetworkError("synthetic network failure")
        return "retried after deadline"

    def fake_sleep(seconds):
        clock["now"] += seconds

    with patch(
        "ashare_state.providers.amazingdata.timeout.time.monotonic",
        side_effect=lambda: clock["now"],
    ):
        outcome = run_with_budget(
            attempt,
            budget=TimeBudget(query_timeout_seconds=0.05),
            retry=RetryPolicy(max_retries=1, backoff_base_seconds=1.0, jitter_fraction=0.0),
            endpoint="fixture",
            sleep=fake_sleep,
        )
    evidence["retry_budget"] = dict(
        clock, configured_budget=0.05, returned=outcome, fake_clock=True
    )
    evidence["linked_return_counterexample"] = {
        "previous_close": 10.0,
        "cash_dividend": 1.0,
        "reference_preclose": 9.0,
        "close": 9.9,
        "close_over_reference_return": 9.9 / 9.0 - 1.0,
        "pre_tax_cash_holding_return": (9.9 + 1.0) / 10.0 - 1.0,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
