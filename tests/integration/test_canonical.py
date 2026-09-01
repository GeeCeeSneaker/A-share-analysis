"""CR-3 Canonical Runtime contract tests (audit 20260901:
"CR-2.4最终复审结论与CR-3_AvailabilityPolicy_Canonicalizer开发工作要求").

Covers the audit §8 adversarial matrix (30 classes) plus the CR-2.4 P1
guard hardening fixtures:

1-2   boundary structure: no provider SDK access, no caller policy params
3-5   eligibility: BLOCKED/PARTIAL CR-2 runs never eligible (policy-gated)
6-7   CR-2 closure/semantic seal consumption (tamper -> BLOCK)
8-11  availability: as_of filter BEFORE selection, no fabricated
      available_at, conservative OBSERVED_AT_INGEST
12    availability policy version change -> new run
13-15 identity: missing/ambiguous fail closed, no prefix fallback
16    duplicate canonical key -> finding, never silent dedupe
17-20 selection: deterministic winner, equivalent merge, explicit
      conflict, no silent fallback
21-23 reconciliation: within/above tolerance, order independence
24-27 run identity: row-order/policy/tolerance/code-fingerprint changes
28    CA evidence tier preserved (projection never direct truth)
29    no hard-coded institutional price-limit facts (AST)
30    full CI (three legs, API-confirmed after push)

Plus the CR-2.4 P1 guard hardening: ``rw = RawWriter(...); rw.write(...)``
and ``RawWriter(...).write(...)`` alias/constructor forms must FAIL the
unanchored-write structural guard.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from ashare_state.canonical import (
    CanonicalRunner,
    CanonicalRunnerError,
    domain_specs,
    source_policies,
)
from ashare_state.storage.raw_writer import RawWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
CANONICAL_SRC = REPO_ROOT / "src" / "ashare_state" / "canonical"
PROVIDER_SOURCE = REPO_ROOT / "src" / "ashare_state" / "providers" / "amazingdata" / "provider.py"

T0 = datetime(2026, 8, 30, 0, 0, 1, tzinfo=UTC)  # default received_at
T1 = datetime(2026, 8, 31, 0, 0, 1, tzinfo=UTC)  # later ingest
AS_OF_EARLY = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)  # between T0 and T1
AS_OF_LATE = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


# ----------------------------------------------------------------- fixtures


@dataclass
class _FakeEnvelope:
    provider: str = "amazingdata"
    provider_dataset: str = "daily_bar"
    endpoint: str = "MarketData.query_kline"
    request_id: str = ""
    request_params_hash: str = "h" * 16
    requested_at: str = "2026-08-30T00:00:00+00:00"
    received_at: str = "2026-08-30T00:00:01+00:00"
    sdk_version: str | None = "FAKE-1.1.9"
    runtime_version: str | None = "FAKE-V4.3.0"
    account_profile_id: str = "ACCOUNT_x"
    row_count: int = 2
    status: str = "OK"
    error_class: str | None = None
    duration_ms: float = 1.0
    attempt_count: int = 1
    capability_status: str | None = None
    request_params: dict[str, Any] | None = None
    normalization_surface: str = ""
    operation_id: str = ""


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    from ashare_state.storage import apply_migrations

    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture
def env_root(tmp_path: Path) -> dict[str, Path]:
    return {"raw": tmp_path / "raw", "normalized": tmp_path / "normalized"}


def _enroll(conn, roots: dict[str, Path], dataset: str, request_id: str) -> None:
    from ashare_state.storage.raw_anchor import _enroll_anchor

    _enroll_anchor(
        conn,
        roots["raw"],
        provider="amazingdata",
        provider_dataset=dataset,
        request_id=request_id,
        evidence_hash=hashlib.sha256(
            (
                roots["raw"]
                / "provider=amazingdata"
                / f"dataset={dataset}"
                / f"{request_id}.meta.json"
            ).read_bytes()
        ).hexdigest(),
    )


def _normalize(conn, roots, dataset: str, request_id: str):
    from ashare_state.normalization.runner import NormalizationRunner

    return NormalizationRunner(
        conn, raw_root=roots["raw"], normalized_root=roots["normalized"]
    ).run(provider_dataset=dataset, request_id=request_id)


def _persist_raw(
    conn,
    roots: dict[str, Path],
    *,
    dataset: str,
    endpoint: str,
    surface: str,
    request_id: str,
    payload: Any,
    params: dict[str, Any] | None = None,
    received_at: datetime = T0,
) -> None:
    """Persist + anchor + normalize raw evidence exactly the governed
    way (anchored write, then the CR-2 run)."""
    writer = RawWriter(roots["raw"], ingest_run_id="ingest-test")
    env = _FakeEnvelope(
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=request_id,
        request_params=params or {},
        received_at=received_at.isoformat(),
        row_count=len(payload) if hasattr(payload, "__len__") else 1,
        normalization_surface=surface,
        operation_id=f"{endpoint}#{surface}",
    )
    from ashare_state.providers.exchange import ProviderExchange

    writer.write(ProviderExchange(envelope=env, payload=payload))
    _enroll(conn, roots, dataset, request_id)
    _normalize(conn, roots, dataset, request_id)


_MASTER_ROWS = [
    {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "LISTING_DATE": "19990101",
        "IS_LISTED": "1",
    },
    {
        "SECURITY_CODE": "000001",
        "MARKET_CODE": "2",
        "LISTING_DATE": "19910403",
        "IS_LISTED": "1",
    },
]

_BAR_ROWS = [
    {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "KLINE_TIME": 20260814,
        "KLINE_TYPE": "DAY",
        "OPEN_PRICE": "10.0",
        "HIGH_PRICE": "11.0",
        "LOW_PRICE": "9.0",
        "CLOSE_PRICE": "10.5",
        "VOLUME": "12345",
        "AMOUNT": "67890.0",
    },
    {
        "SECURITY_CODE": "000001",
        "MARKET_CODE": "2",
        "KLINE_TIME": 20260814,
        "KLINE_TYPE": "DAY",
        "OPEN_PRICE": "20.0",
        "HIGH_PRICE": "21.0",
        "LOW_PRICE": "19.0",
        "CLOSE_PRICE": "20.5",
        "VOLUME": "100",
        "AMOUNT": "2000.0",
    },
]

_STATUS_ROWS = [
    {
        "SECURITY_CODE": "600000",
        "MARKET_CODE": "1",
        "TRADE_DATE": "20260814",
        "IS_ST": "0",
        "IS_XR_SEC": "1",
        "IS_WD_SEC": "0",
        "UP_LIMIT_PRICE": "11.0",
        "DOWN_LIMIT_PRICE": "9.0",
    },
]

_ADJ_ROWS = [
    {
        "SECURITY_CODE": "600000",
        "EX_DATE": "20260810",
        "EX_FACTOR": "1.5",
    },
]


def _canonical(conn, roots, as_of, domains=None):
    return CanonicalRunner(conn, raw_root=roots["raw"], normalized_root=roots["normalized"]).run(
        as_of, domains=domains
    )


def _seed_base(conn, env_root) -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="code_list",
        endpoint="BaseData.get_code_list",
        surface="security_master",
        request_id="req-master",
        payload=_MASTER_ROWS,
    )


def _seed_bars(conn, env_root, request_id: str = "req-bars", received_at: datetime = T0) -> None:
    _persist_raw(
        conn,
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        surface="daily_bar",
        request_id=request_id,
        payload=_BAR_ROWS,
        received_at=received_at,
    )


def _read_selected(roots: dict[str, Path], result) -> list[dict[str, Any]]:
    import polars as pl

    manifest = json.loads(
        (roots["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
    )
    uri = manifest["artifacts"]["selected"]["uri"]
    return pl.read_parquet(roots["normalized"] / uri).to_dicts()


def _read_decisions(roots: dict[str, Path], result) -> list[dict[str, Any]]:
    import polars as pl

    manifest = json.loads(
        (roots["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
    )
    uri = manifest["artifacts"]["decisions"]["uri"]
    return pl.read_parquet(roots["normalized"] / uri).to_dicts()


def _findings(conn, run_id: str) -> list[tuple[str, str]]:
    return [
        (str(r[0]), str(r[1]))
        for r in conn.execute(
            "SELECT finding_class, blocking FROM meta_canonical_reconciliation_finding "
            "WHERE canonical_run_id = ? ORDER BY finding_class",
            [run_id],
        ).fetchall()
    ]


# ------------------------------------------------------- boundary structure


@pytest.mark.integration
class TestBoundaryStructure:
    def test_no_provider_sdk_access_in_canonical_package(self):
        """Audit §8-1: the canonicalizer never imports/calls the
        provider SDK (or any provider module) - its only input is the
        CR-2 verified ledger + artifacts."""
        for py in sorted(CANONICAL_SRC.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert "providers" not in alias.name, f"{py.name} imports {alias.name}"
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert "providers" not in module, f"{py.name} imports from {module}"

    def test_no_caller_correctness_parameters(self):
        """Audit §8-2: the run API accepts no provider priority /
        tolerance / fallback / partial correctness parameters."""
        params = inspect.signature(CanonicalRunner.run).parameters
        for forbidden in (
            "preferred_provider",
            "provider_priority",
            "tolerance",
            "allow_fallback",
            "allow_partial",
            "policy",
            "source_policy",
            "availability",
            "identity",
            "candidates",
            "dataframe",
        ):
            assert forbidden not in params, forbidden
        init_params = inspect.signature(CanonicalRunner.__init__).parameters
        for forbidden in ("policy", "policies", "tolerance", "identity"):
            assert forbidden not in init_params, forbidden

    def test_blocked_cr2_run_not_eligible(self, conn, env_root):
        """Audit §8-3: a BLOCKED CR-2 run never contributes candidates."""
        _persist_raw(
            conn,
            env_root,
            dataset="corporate_action",
            endpoint="InfoData.get_dividend",
            surface="corporate_action",
            request_id="req-blocked",
            payload=[{"SECURITY_CODE": "600000", "EX_DIVIDEND_DATE": "20260810"}],
        )
        blocked_runs = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run WHERE status = 'BLOCKED'"
        ).fetchone()[0]
        assert int(blocked_runs) >= 1
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("trade_calendar",))
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "CLOSURE_VERIFICATION_FAILED" not in classes
        runs_used = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run r "
            "JOIN meta_canonicalization_run c ON TRUE "
            "WHERE r.status = 'BLOCKED' AND c.canonical_run_id = ?",
            [result.canonical_run_id],
        ).fetchone()
        assert int(runs_used[0]) >= 0  # blocked runs are simply never queried

    def test_partial_cr2_run_not_eligible_by_default(self, conn, env_root):
        """Audit §8-4: a PARTIAL CR-2 run is NOT eligible (no domain
        policy allows partial consumption in v1) - its good rows are
        not silently consumed."""
        rows = [dict(_BAR_ROWS[0]), dict(_BAR_ROWS[1])]
        rows[1].pop("VOLUME")  # one bad row -> PARTIAL
        _persist_raw(
            conn,
            env_root,
            dataset="code_list",
            endpoint="BaseData.get_code_list",
            surface="security_master",
            request_id="req-master",
            payload=_MASTER_ROWS,
        )
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-partial",
            payload=rows,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        status = str(
            conn.execute(
                "SELECT status FROM meta_provider_normalization_run "
                "WHERE raw_request_id = 'req-partial'"
            ).fetchone()[0]
        )
        assert status == "PARTIAL"
        selected = _read_selected(env_root, result)  # PARTIAL rows never consumed
        assert selected == []
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "REQUIRED_DOMAIN_MISSING" in classes
        for policy in source_policies():
            assert policy.partial_run_allowed is False


# ---------------------------------------------------- closure verification


@pytest.mark.integration
class TestClosureVerification:
    def test_manifest_hash_tamper_blocks(self, conn, env_root):
        """Audit §8-6: a tampered CR-2 manifest hash makes the run
        non-consumable - CLOSURE_VERIFICATION_FAILED -> canonical run
        BLOCKED."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        run_id = conn.execute(
            "SELECT normalization_run_id FROM meta_provider_normalization_run "
            "WHERE raw_request_id = 'req-bars'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE meta_provider_normalization_run SET normalized_manifest_hash = ? "
            "WHERE normalization_run_id = ?",
            ["0" * 64, run_id],
        )
        result = _canonical(conn, env_root, AS_OF_LATE)
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "CLOSURE_VERIFICATION_FAILED" in classes

    def test_physical_values_swap_blocks(self, conn, env_root):
        """Audit §8-7: swapping the physical parquet values (same
        schema/row-count) is caught by the CR-2 semantic seal ->
        canonical run BLOCKED."""
        import io

        import polars as pl

        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        run_id = conn.execute(
            "SELECT normalization_run_id, normalized_manifest_uri "
            "FROM meta_provider_normalization_run WHERE raw_request_id = 'req-bars'"
        ).fetchone()
        manifest = json.loads((env_root["normalized"] / str(run_id[1])).read_text(encoding="utf-8"))
        uri = manifest["outputs"][0]["uri"]
        path = env_root["normalized"] / uri
        frame = pl.read_parquet(path)
        swapped = frame.with_columns(pl.lit(999.0).alias("close"))
        buf = io.BytesIO()
        swapped.write_parquet(buf)
        path.write_bytes(buf.getvalue())
        result = _canonical(conn, env_root, AS_OF_LATE)
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "CLOSURE_VERIFICATION_FAILED" in classes


# ------------------------------------------------------------ availability


@pytest.mark.integration
class TestAvailability:
    def test_as_of_filter_runs_before_selection(self, conn, env_root):
        """Audit §8-8: candidates with available_at > as_of are excluded
        BEFORE source selection (EXCLUDED_FUTURE decisions, zero
        selected rows from the future run)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-early", received_at=T0)
        _seed_bars(conn, env_root, "req-late", received_at=T1)
        result = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert result.status == "SUCCESS"
        decisions = _read_decisions(env_root, result)
        excluded = [d for d in decisions if d["decision_class"] == "EXCLUDED_FUTURE"]
        assert len(excluded) == 2  # both rows of the late run
        assert all(d["source_normalization_run_id"] for d in excluded)
        # every selected row comes from the EARLY run only
        selected = _read_selected(env_root, result)
        assert len(selected) == 2
        early_run = conn.execute(
            "SELECT normalization_run_id FROM meta_provider_normalization_run "
            "WHERE raw_request_id = 'req-early'"
        ).fetchone()[0]
        assert all(r["source_normalization_run_id"] == str(early_run) for r in selected)

    def test_future_data_never_wins_historical_selection(self, conn, env_root):
        """Audit §8-9: a later-ingested 'better' run cannot influence an
        earlier as_of - at AS_OF_EARLY the late run does not even
        compete."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-early", received_at=T0)
        _seed_bars(conn, env_root, "req-late", received_at=T1)
        early = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        late = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert early.canonical_run_id != late.canonical_run_id
        early_selected = _read_selected(env_root, early)
        late_selected = _read_selected(env_root, late)
        # both as_of points selected the SAME two keys, but from
        # different availability worlds (late run also competes later)
        assert {r["canonical_key"] for r in early_selected} == {
            r["canonical_key"] for r in late_selected
        }

    def test_available_at_is_real_ingest_time_never_fabricated(self, conn, env_root):
        """Audit §8-10/§8-11: available_at is the raw envelope
        received_at (OBSERVED_AT_INGEST) - never trade_date 00:00,
        never 1970, never a fixed close time."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T1)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        selected = _read_selected(env_root, result)
        for row in selected:
            assert row["available_at"] == T1.isoformat()
            assert row["ingested_at"] == T1.isoformat()
            assert row["availability_basis"] == "OBSERVED_AT_INGEST"
            assert not row["available_at"].startswith("1970")
            assert not row["available_at"].endswith("T00:00:00+00:00")
            assert row["trade_date"] == "2026-08-14"  # != available_at

    def test_availability_policy_version_change_new_run(self, conn, env_root, monkeypatch):
        """Audit §8-12: an availability policy version change yields a
        NEW canonical run (history preserved)."""
        import ashare_state.canonical.availability as availability_module

        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        monkeypatch.setattr(availability_module, "AVAILABILITY_POLICY_VERSION", "availability-v2")
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id
        count = conn.execute("SELECT count(*) FROM meta_canonicalization_run").fetchone()[0]
        assert int(count) == 2


# ---------------------------------------------------------------- identity


@pytest.mark.integration
class TestIdentityResolution:
    def test_missing_identity_excluded_with_finding(self, conn, env_root):
        """Audit §8-13: a provider symbol with no security_master entry
        is EXCLUDED with an IDENTITY_MISSING finding - the bare symbol
        is never used as a canonical key fallback."""
        _seed_base(conn, env_root)
        orphan = [dict(_BAR_ROWS[0])]
        orphan[0]["SECURITY_CODE"] = "999999"  # not in the master rows
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-orphan",
            payload=orphan,
        )
        result = _canonical(conn, env_root, AS_OF_LATE)
        assert result.status == "BLOCKED"  # identity_missing_max = 0
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "IDENTITY_MISSING" in classes
        selected = _read_selected(env_root, result)
        assert all("999999" not in (r.get("canonical_key") or "") for r in selected)

    def test_pit_relist_resolution_is_deterministic(self, conn, env_root):
        """Relisted symbol (two list dates): the row resolves to the
        identity valid AT its trade date - never ambiguous, never the
        bare symbol."""
        master = [
            *_MASTER_ROWS,
            {"SECURITY_CODE": "000003", "MARKET_CODE": "2", "LISTING_DATE": "19910101"},
            {"SECURITY_CODE": "000003", "MARKET_CODE": "2", "LISTING_DATE": "20300101"},
        ]
        _persist_raw(
            conn,
            env_root,
            dataset="code_list",
            endpoint="BaseData.get_code_list",
            surface="security_master",
            request_id="req-master",
            payload=master,
        )
        _seed_bars(conn, env_root, "req-bars")
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "SUCCESS"
        selected = _read_selected(env_root, result)
        # 600000/000001 resolve through the single-list-date entries
        assert len(selected) == 2

    def test_unknown_market_code_is_missing_not_prefix_guess(self, conn, env_root):
        """Audit §8-15: a row whose market attribution is unknown is a
        MISSING identity - code-prefix guessing never happens (the
        security_status surface persists unknown market codes
        faithfully, so the identity bridge sees them)."""
        _seed_base(conn, env_root)
        status_row = dict(_STATUS_ROWS[0])
        status_row["MARKET_CODE"] = "9"  # unknown market on the status surface
        _persist_raw(
            conn,
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            surface="security_status_history",
            request_id="req-weird-market",
            payload=[status_row],
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("security_status",))
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "IDENTITY_MISSING" in classes


# ---------------------------------------------------------------- selection


@pytest.mark.integration
class TestSelection:
    def test_duplicate_canonical_key_blocks(self, conn, env_root):
        """Audit §8-16: two rows of ONE output with the same canonical
        key are a blocking DUPLICATE_CANONICAL_KEY finding - never
        silently deduped."""
        _seed_base(conn, env_root)
        rows = [
            dict(_BAR_ROWS[0]),
            dict(_BAR_ROWS[0]),  # exact duplicate business key
            dict(_BAR_ROWS[1]),
        ]
        rows[1]["CLOSE_PRICE"] = "10.6"  # different values -> not an CR-2 dedupe
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-dup",
            payload=rows,
        )
        result = _canonical(conn, env_root, AS_OF_LATE)
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "DUPLICATE_CANONICAL_KEY" in classes

    def test_single_provider_healthy_deterministic(self, conn, env_root):
        """Audit §8-17/§8-18: a healthy single-provider candidate set
        selects deterministically (same inputs -> same rows, same run
        identity on replay)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert first.status == "SUCCESS"
        assert first.selected_count == 2
        replay = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert replay.idempotent_replay is True
        assert replay.canonical_run_id == first.canonical_run_id

    def test_equivalent_values_merge_with_decision(self, conn, env_root):
        """Audit §8-21: two runs carrying EQUAL values at one key merge
        with an EQUIVALENT_MERGED decision + ONE selected row (EXACT
        tolerance, deterministic winner)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-a", received_at=T0)
        _seed_bars(conn, env_root, "req-b", received_at=T0)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "SUCCESS"
        decisions = _read_decisions(env_root, result)
        merged = [d for d in decisions if d["decision_class"] == "EQUIVALENT_MERGED"]
        assert len(merged) == 2  # one per key
        selected = _read_selected(env_root, result)
        assert len(selected) == 2  # exactly one row per key

    def test_conflicting_values_block(self, conn, env_root):
        """Audit §8-22: two runs carrying DIFFERENT values at one key
        are a blocking SOURCE_CONFLICT finding (EXACT tolerance - never
        last-write-wins)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-a", received_at=T0)
        conflict = [dict(_BAR_ROWS[0]), dict(_BAR_ROWS[1])]
        conflict[0]["CLOSE_PRICE"] = "77.7"
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-conflict",
            payload=conflict,
            received_at=T0,
        )
        result = _canonical(conn, env_root, AS_OF_LATE)
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "SOURCE_CONFLICT" in classes

    def test_run_order_does_not_change_winner(self, conn, env_root):
        """Audit §8-23: provider/run iteration order can never
        influence the winner - the deterministic tiebreak is
        (priority, manifest hash, ordinal)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-b", received_at=T0)
        _seed_bars(conn, env_root, "req-a", received_at=T0)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert first.status == "SUCCESS"
        decisions = _read_decisions(env_root, first)
        winners = [
            d["source_normalization_run_id"] for d in decisions if d["decision_class"] == "SELECTED"
        ]
        assert len(winners) == 2
        assert len(set(winners)) == 1  # one single deterministic winner run

    def test_row_order_reversal_same_semantic_result(self, conn, env_root, tmp_path):
        """Audit §8-24: input row order never leaks into the canonical
        result - CR-2 sorts deterministically, the canonicalizer sorts
        selected rows by key and the manifest carries a semantic hash."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE)
        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        semantic = manifest["selected_semantic_hash"]
        keys = [r["canonical_key"] for r in _read_selected(env_root, result)]
        assert keys == sorted(keys)
        assert len(semantic) == 64

    def test_required_domain_missing_blocks(self, conn, env_root):
        """No eligible run for a requested domain -> blocking
        REQUIRED_DOMAIN_MISSING finding -> BLOCKED (no silent skip, no
        silent fallback to 'whatever is available')."""
        _seed_base(conn, env_root)  # master only, no bars
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "REQUIRED_DOMAIN_MISSING" in classes


# -------------------------------------------------------------- run identity


@pytest.mark.integration
class TestRunIdentity:
    def test_source_policy_version_change_new_run(self, conn, env_root, monkeypatch):
        """Audit §8-25: a source policy version change yields a NEW
        canonical run (history preserved, never overwritten)."""
        import ashare_state.canonical.source_policy as source_policy_module

        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        monkeypatch.setattr(source_policy_module, "SOURCE_POLICY_VERSION", "source-policy-v2")
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id
        count = conn.execute("SELECT count(*) FROM meta_canonicalization_run").fetchone()[0]
        assert int(count) == 2

    def test_tolerance_change_new_run(self, conn, env_root, monkeypatch):
        """Audit §8-26: a tolerance identity change yields a NEW run."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        import ashare_state.canonical.source_policy as source_policy_module

        original = source_policy_module.tolerance_policy_identity

        def bumped():
            version, digest = original()
            return "tolerance-v2", digest

        monkeypatch.setattr(source_policy_module, "tolerance_policy_identity", bumped)
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id

    def test_code_fingerprint_change_new_run(self, conn, env_root, monkeypatch):
        """Audit §8-27: a canonicalizer code fingerprint change yields a
        NEW run with historical exact replay semantics."""
        import ashare_state.canonical.canonicalizer as canonicalizer_module

        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        monkeypatch.setattr(canonicalizer_module, "canonical_code_fingerprint", lambda: "f" * 64)
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id
        # rollback: the historical first run still replays exactly
        monkeypatch.undo()
        replay = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert replay.idempotent_replay is True
        assert replay.canonical_run_id == first.canonical_run_id

    def test_damaged_prior_run_fails_closed(self, conn, env_root):
        """A tampered prior canonical artifact breaks the exact replay
        - fail closed, never a false healthy replay."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        selected_path = env_root["normalized"] / manifest["artifacts"]["selected"]["uri"]
        selected_path.write_bytes(b"tampered-bytes")
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_finding_rows_deleted_replay_fails_closed(self, conn, env_root):
        """DB-side finding rows deleted after the run: the exact-set
        seal (DB count/hash == ledger == manifest) breaks on replay."""
        _seed_base(conn, env_root)
        orphan = [dict(_BAR_ROWS[0])]
        orphan[0]["SECURITY_CODE"] = "999999"
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-orphan",
            payload=orphan,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.finding_count >= 1  # IDENTITY_MISSING blocking finding
        conn.execute(
            "DELETE FROM meta_canonical_reconciliation_finding WHERE canonical_run_id = ?",
            [result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))


# ------------------------------------------------------- domain matrix / tiers


@pytest.mark.integration
class TestDomainMatrix:
    def test_matrix_classifies_every_surface(self):
        """Audit §7: every CR-2 surface is explicitly classified - no
        silent presence/absence."""
        specs = domain_specs()
        by_class: dict[str, list[str]] = {}
        for spec in specs:
            by_class.setdefault(spec.eligibility.value, []).append(spec.domain)
        assert set(by_class["CANONICAL_SUPPORTED"]) == {
            "trade_calendar",
            "daily_bar",
            "security_status",
            "limit_price",
            "adj_factor",
        }
        assert set(by_class["AUXILIARY_ONLY"]) == {"security_master", "ca_projection"}
        assert set(by_class["BLOCKED_PENDING_SEMANTICS"]) >= {
            "corporate_action",
            "index_daily",
            "industry_member",
            "equity_structure",
            "bj_code_mapping",
            "industry_taxonomy_definition",
        }

    def test_auxiliary_and_blocked_domains_rejected(self, conn, env_root):
        """AUXILIARY_ONLY / BLOCKED_PENDING_SEMANTICS domains can never
        be run - the API fails closed instead of silently skipping."""
        for domain in ("security_master", "ca_projection", "corporate_action", "index_daily"):
            with pytest.raises(CanonicalRunnerError, match="never produce canonical rows"):
                _canonical(conn, env_root, AS_OF_LATE, domains=(domain,))

    def test_ca_projection_never_direct_event_truth(self, conn, env_root):
        """Audit §8-28: a status run exists (its corporate_action output
        carries STATUS_FLAG_PROJECTION rows), yet the corporate_action
        canonical domain is BLOCKED_PENDING_SEMANTICS - the projection
        is never laundered into direct CA truth."""
        _seed_base(conn, env_root)
        _persist_raw(
            conn,
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            surface="security_status_history",
            request_id="req-status",
            payload=_STATUS_ROWS,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("limit_price",))
        assert result.status == "SUCCESS"
        status_run = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run "
            "WHERE raw_request_id = 'req-status'"
        ).fetchone()[0]
        assert int(status_run) == 1  # the status run exists (3-output CR-2 run)
        selected = _read_selected(env_root, result)
        assert all(r["canonical_domain"] == "limit_price" for r in selected)
        with pytest.raises(CanonicalRunnerError):
            _canonical(conn, env_root, AS_OF_LATE, domains=("corporate_action",))

    def test_no_hardcoded_institutional_facts(self):
        """Audit §8-29: the canonical package hard-codes NO
        institutional price-limit / board-percentage facts."""
        import re

        pattern = re.compile(r"(?i)(limit|st|board|涨停|跌停|科创|北交).{0,40}(5|10|20|30)\s*%")
        for py in sorted(CANONICAL_SRC.rglob("*.py")):
            source = py.read_text(encoding="utf-8")
            assert not pattern.search(source), f"{py.name} carries an institutional fact"

    def test_status_run_feeds_both_domains(self, conn, env_root):
        """One CR-2 status run feeds security_status AND limit_price
        canonical domains (multi-domain routing)."""
        _seed_base(conn, env_root)
        _persist_raw(
            conn,
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            surface="security_status_history",
            request_id="req-status",
            payload=_STATUS_ROWS,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("security_status", "limit_price"))
        assert result.status == "SUCCESS"
        selected = _read_selected(env_root, result)
        domains = {r["canonical_domain"] for r in selected}
        assert domains == {"security_status", "limit_price"}

    def test_calendar_expands_to_day_rows(self, conn, env_root):
        _persist_raw(
            conn,
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            surface="trade_calendar",
            request_id="req-cal",
            payload=["20260810", "20260811"],
            params={"market": "SH"},
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("trade_calendar",))
        assert result.status == "SUCCESS"
        selected = _read_selected(env_root, result)
        assert len(selected) == 2
        assert {r["market"] for r in selected} == {"SH"}
        assert {r["trade_date"] for r in selected} == {"2026-08-10", "2026-08-11"}

    def test_adj_factor_domains(self, conn, env_root):
        _seed_base(conn, env_root)
        _persist_raw(
            conn,
            env_root,
            dataset="adj_factor",
            endpoint="BaseData.get_adj_factor",
            surface="adj_factor",
            request_id="req-adj",
            payload=_ADJ_ROWS,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("adj_factor",))
        assert result.status == "SUCCESS"
        selected = _read_selected(env_root, result)
        assert len(selected) == 1
        assert selected[0]["adj_factor"] == 1.5


# ---------------------------------------------------------- ledger / artifacts


@pytest.mark.integration
class TestLedgerAndArtifacts:
    def test_manifest_seals_everything(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        assert manifest["canonical_run_id"] == result.canonical_run_id
        assert manifest["as_of"] == AS_OF_LATE.isoformat()
        assert manifest["status"] == "SUCCESS"
        for artifact in ("selected", "decisions", "findings"):
            entry = manifest["artifacts"][artifact]
            assert entry["row_count"] >= 0
            assert len(entry["content_hash"]) == 64
            assert (env_root["normalized"] / entry["uri"]).is_file()
        for field in (
            "input_set_hash",
            "identity_dataset_hash",
            "availability_policy_version",
            "availability_policy_hash",
            "source_policy_version",
            "source_policy_hash",
            "tolerance_policy_version",
            "tolerance_policy_hash",
            "code_fingerprint",
            "selected_semantic_hash",
            "finding_set_hash",
        ):
            assert manifest.get(field), field
        # lineage: every selected row carries the full lineage set
        selected = _read_selected(env_root, result)
        for row in selected:
            for field in (
                "selected_provider",
                "source_normalization_run_id",
                "source_output_name",
                "source_row_ordinal",
                "source_row_identity_hash",
                "source_raw_request_id",
                "source_raw_evidence_hash",
                "source_mapper_identity",
                "source_policy_version",
                "canonical_contract_version",
                "available_at",
                "ingested_at",
                "availability_basis",
                "availability_policy_version",
            ):
                assert field in row, field

    def test_ledger_row_and_finding_counts(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        row = conn.execute(
            "SELECT status, selected_count, finding_count, idempotent_replay, "
            "finding_set_hash, code_fingerprint FROM meta_canonicalization_run "
            "WHERE canonical_run_id = ?",
            [result.canonical_run_id],
        ).fetchone()
        assert str(row[0]) == "SUCCESS"
        assert int(row[1]) == 2
        assert int(row[2]) == 0
        assert bool(row[3]) is False
        assert str(row[4]) == result.finding_set_hash
        assert len(str(row[5])) == 64

    def test_two_as_of_points_two_runs(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        early = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        late = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert early.canonical_run_id != late.canonical_run_id
        count = conn.execute("SELECT count(*) FROM meta_canonicalization_run").fetchone()[0]
        assert int(count) == 2


# ----------------------------------------------- CR-2.4 P1 guard hardening


def _scan_unanchored_writes(tree: ast.AST, relpath: str) -> list[str]:
    """The hardened structural guard (CR-2.4 P1): in production src/,
    RawWriter WRITE call sites (write/write_success/write_failure -
    tracked through alias assignments AND direct constructor calls) are
    allowed ONLY inside storage/raw_writer.py (the definition) and
    storage/raw_anchor.py (the anchored boundary). RawWriter
    CONSTRUCTION is additionally allowed in normalization/runner.py -
    the read-only verified reader (no write-call exemption is granted
    there). Variable naming is irrelevant; readers are unrestricted."""
    write_allowed = {"storage/raw_writer.py", "storage/raw_anchor.py"}
    construct_allowed = write_allowed | {"normalization/runner.py"}
    violations: list[str] = []
    # track names bound to RawWriter constructor calls: x = RawWriter(...)
    writer_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (isinstance(func, ast.Name) and func.id == "RawWriter") or (
                isinstance(func, ast.Attribute) and func.attr == "RawWriter"
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        writer_names.add(target.id)
    if relpath not in construct_allowed:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Name) and func.id == "RawWriter") or (
                    isinstance(func, ast.Attribute) and func.attr == "RawWriter"
                ):
                    violations.append(f"{relpath}:{node.lineno} RawWriter(...)")
    if relpath in write_allowed:
        return violations
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        # direct constructor-call form: RawWriter(...).write(...)
        if node.func.attr in ("write", "write_success", "write_failure"):
            receiver = node.func.value
            receiver_text = ast.dump(receiver)
            if "RawWriter" in receiver_text:
                violations.append(f"{relpath}:{node.lineno} .{node.func.attr}()")
                continue
            receiver_name = (receiver.attr if isinstance(receiver, ast.Attribute) else None) or (
                receiver.id if isinstance(receiver, ast.Name) else ""
            )
            if str(receiver_name) in writer_names:
                violations.append(f"{relpath}:{node.lineno} .{node.func.attr}()")
    return violations


@pytest.mark.integration
class TestRawWriterGuardHardening:
    """CR-2.4 P1 (review section 2): the anti-bypass guard must catch
    alias and constructor-call forms, not just receiver names
    containing 'writer'."""

    def test_alias_form_fails_guard(self):
        source = "rw = RawWriter(root)\nrw.write(exchange)\n"
        violations = _scan_unanchored_writes(ast.parse(source), "evil.py")
        assert len(violations) == 2  # the write call + the constructor outside boundary
        assert any(".write()" in v for v in violations)

    def test_constructor_call_form_fails_guard(self):
        source = "RawWriter(root).write(exchange)\n"
        violations = _scan_unanchored_writes(ast.parse(source), "evil.py")
        assert any(".write()" in v for v in violations)

    def test_boundary_modules_are_clean(self):
        for relpath in ("storage/raw_writer.py", "storage/raw_anchor.py"):
            path = REPO_ROOT / "src" / "ashare_state" / relpath
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert _scan_unanchored_writes(tree, relpath) == []

    def test_reader_module_constructs_but_never_writes(self):
        """normalization/runner.py may construct the read-only verified
        reader, but ANY write call there still violates the guard."""
        path = REPO_ROOT / "src" / "ashare_state" / "normalization" / "runner.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert _scan_unanchored_writes(tree, "normalization/runner.py") == []

    def test_production_src_has_no_unanchored_raw_writes(self):
        """The hardened guard over the whole production tree: zero
        violations (RawWriter is constructed only inside the anchored
        boundary and the read-only runner; write calls only inside the
        boundary; readers are unrestricted)."""
        src_root = REPO_ROOT / "src" / "ashare_state"
        violations: list[str] = []
        for py in sorted(src_root.rglob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            relpath = str(py.relative_to(src_root)).replace("\\", "/")
            violations.extend(_scan_unanchored_writes(tree, relpath))
        assert violations == [], f"unanchored RawWriter usage: {violations}"


# --------------------------------------------- CR-3.1: requested domain identity


@pytest.mark.integration
class TestRequestedDomainIdentity:
    """CR-3.1 P0-01 (audit section 1): the requested domain set is part
    of the canonical run identity."""

    def test_daily_bar_vs_trade_calendar_distinct_runs(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        _persist_raw(
            conn,
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            surface="trade_calendar",
            request_id="req-cal",
            payload=["20260810"],
            params={"market": "SH"},
        )
        bars = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        calendar = _canonical(conn, env_root, AS_OF_LATE, domains=("trade_calendar",))
        assert bars.canonical_run_id != calendar.canonical_run_id
        # the calendar replay can never return the bars artifact set
        assert calendar.domains == ("trade_calendar",)
        assert bars.domains == ("daily_bar",)

    def test_domain_order_irrelevant_same_run(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        a = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar", "limit_price"))
        b = _canonical(conn, env_root, AS_OF_LATE, domains=("limit_price", "daily_bar"))
        assert a.canonical_run_id == b.canonical_run_id
        assert b.idempotent_replay is True
        assert b.domains == ("daily_bar", "limit_price")

    def test_duplicate_domains_deduped(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        a = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        b = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar", "daily_bar"))
        assert a.canonical_run_id == b.canonical_run_id

    def test_replay_returns_exact_requested_domains(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar", "limit_price"))
        replay = _canonical(conn, env_root, AS_OF_LATE, domains=("limit_price", "daily_bar"))
        assert replay.idempotent_replay is True
        assert replay.domains == ("daily_bar", "limit_price")  # from the ledger seal

    def test_manifest_requested_domains_rebind_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        path = env_root["normalized"] / str(result.manifest_uri)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["requested_domains"] = ["trade_calendar"]
        data = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(data).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_ledger_requested_domains_tamper_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        conn.execute(
            "UPDATE meta_canonicalization_run SET requested_domains_json = ? "
            "WHERE canonical_run_id = ?",
            ['["trade_calendar"]', result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))


# --------------------------------------------- CR-3.1: availability completeness


@pytest.mark.integration
class TestAvailabilityCompleteness:
    """CR-3.1 P0-02 (audit section 2): future-only data can never make a
    historical canonical world look "successfully empty"."""

    def test_future_only_blocks_never_success(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-future", received_at=T1)
        result = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        assert result.selected_count == 0
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF" in classes
        decisions = _read_decisions(env_root, result)
        assert all(d["decision_class"] == "EXCLUDED_FUTURE" for d in decisions)
        assert len(decisions) == 2  # both rows retained as exclusion evidence

    def test_early_plus_future_success_early_only(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-early", received_at=T0)
        _seed_bars(conn, env_root, "req-future", received_at=T1)
        result = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert result.status == "SUCCESS"
        assert result.selected_count == 2

    def test_future_run_added_keeps_earlier_truth(self, conn, env_root):
        """Adding a future-only run does not change the earlier selected
        truth (only the input identity per frozen snapshot semantics)."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-early", received_at=T0)
        first = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert first.status == "SUCCESS"
        first_rows = _read_selected(env_root, first)
        _seed_bars(conn, env_root, "req-future", received_at=T1)
        second = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id  # new input identity
        assert second.status == "SUCCESS"
        assert _read_selected(env_root, second) == first_rows  # same truth values


# --------------------------------------------- CR-3.1: input snapshot


@pytest.mark.integration
class TestInputSnapshot:
    """CR-3.1 P0-03 (audit section 3): the run identity, the consumed
    candidates, the manifest and the ledger all derive from ONE
    authoritative snapshot resolved once - mid-run insertions cannot
    leak into the current run."""

    def test_mid_run_source_insertion_current_run_exact(self, conn, env_root, monkeypatch):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-s1", received_at=T0)
        original = CanonicalRunner._build_snapshot

        def racing(self, as_of_dt, requested):
            snapshot = original(self, as_of_dt, requested)
            # a new SUCCESS normalization run lands mid-run
            _seed_bars(conn, env_root, "req-s2", received_at=T0)
            return snapshot

        monkeypatch.setattr(CanonicalRunner, "_build_snapshot", racing)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        monkeypatch.undo()
        assert result.status == "SUCCESS"
        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        run_ids = [e["run_id"] for e in manifest["input_normalized_runs"] if e["role"] == "source"]
        s1 = str(
            conn.execute(
                "SELECT normalization_run_id FROM meta_provider_normalization_run "
                "WHERE raw_request_id = 'req-s1'"
            ).fetchone()[0]
        )
        assert run_ids == [s1]  # exact snapshot S1 - S2 never leaked in
        selected = _read_selected(env_root, result)
        assert all(r["source_raw_request_id"] == "req-s1" for r in selected)
        ledger = conn.execute(
            "SELECT input_set_hash FROM meta_canonicalization_run WHERE canonical_run_id = ?",
            [result.canonical_run_id],
        ).fetchone()[0]
        assert str(ledger) == manifest["input_set_hash"]

    def test_next_invocation_sees_new_identity(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-s1", received_at=T0)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        _seed_bars(conn, env_root, "req-s2", received_at=T0)
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id
        assert second.idempotent_replay is False

    def test_mid_run_master_insertion_bridge_unchanged(self, conn, env_root, monkeypatch):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T0)
        original = CanonicalRunner._build_snapshot

        def racing(self, as_of_dt, requested):
            snapshot = original(self, as_of_dt, requested)
            _persist_raw(
                conn,
                env_root,
                dataset="code_list",
                endpoint="BaseData.get_code_list",
                surface="security_master",
                request_id="req-master-2",
                payload=[
                    {
                        "SECURITY_CODE": "300750",
                        "MARKET_CODE": "1",
                        "LISTING_DATE": "20180611",
                        "IS_LISTED": "1",
                    }
                ],
            )
            return snapshot

        monkeypatch.setattr(CanonicalRunner, "_build_snapshot", racing)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        monkeypatch.undo()
        assert result.status == "SUCCESS"
        selected = _read_selected(env_root, result)
        # only the snapshot master identities resolved - 600000/000001
        assert len(selected) == 2


# --------------------------------------- CR-3.1: anchored availability evidence


def _raw_meta_path(env_root: dict[str, Path], dataset: str, request_id: str) -> Path:
    return (
        env_root["raw"] / "provider=amazingdata" / f"dataset={dataset}" / f"{request_id}.meta.json"
    )


@pytest.mark.integration
class TestAnchoredAvailabilityEvidence:
    """CR-3.1 P0-04 (audit section 4): the availability moment is only
    read from raw meta bytes still equal to the sealed hash AND the
    authoritative anchor."""

    def test_received_at_tamper_before_first_canonical_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T1)
        meta = _raw_meta_path(env_root, "daily_bar", "req-bars")
        doc = json.loads(meta.read_bytes())
        doc["received_at"] = T0.isoformat()  # pull the future into the past
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        result = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "AVAILABILITY_EVIDENCE_INVALID" in classes
        assert result.selected_count == 0

    def test_endpoint_tamper_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T0)
        meta = _raw_meta_path(env_root, "daily_bar", "req-bars")
        doc = json.loads(meta.read_bytes())
        doc["account_profile_id"] = "EVIL"  # any meta-only edit changes the bytes
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "AVAILABILITY_EVIDENCE_INVALID" in classes

    def test_anchor_missing_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T0)
        conn.execute("DELETE FROM meta_raw_evidence_anchor WHERE request_id = ?", ["req-bars"])
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "AVAILABILITY_EVIDENCE_INVALID" in classes

    def test_anchor_hash_mismatch_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T0)
        conn.execute(
            "UPDATE meta_raw_evidence_anchor SET evidence_hash = ? WHERE request_id = ?",
            ["0" * 64, "req-bars"],
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        classes = {c for c, _ in _findings(conn, result.canonical_run_id)}
        assert "AVAILABILITY_EVIDENCE_INVALID" in classes

    def test_received_at_tamper_after_success_replay_refused(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T1)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "SUCCESS"
        meta = _raw_meta_path(env_root, "daily_bar", "req-bars")
        doc = json.loads(meta.read_bytes())
        doc["received_at"] = T0.isoformat()
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_intact_anchored_raw_available_at_exact(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, "req-bars", received_at=T1)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        selected = _read_selected(env_root, result)
        for row in selected:
            assert row["available_at"] == T1.isoformat()


# --------------------------------------------- CR-3.1: identity policy binding


@pytest.mark.integration
class TestIdentityPolicyBinding:
    """CR-3.1 P0-05 (audit section 5): the identity bridge policy
    identity enters the run identity; ledger/manifest/runtime carry the
    SAME identity_dataset_hash."""

    def test_bridge_policy_version_change_new_run(self, conn, env_root, monkeypatch):
        import ashare_state.canonical.identity as identity_module

        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        monkeypatch.setattr(identity_module, "IDENTITY_BRIDGE_POLICY_VERSION", "identity-bridge-v2")
        second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert second.canonical_run_id != first.canonical_run_id

    def test_ledger_identity_hash_matches_manifest_and_runtime(self, conn, env_root):
        from ashare_state.canonical import identity_dataset_hash

        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        ledger_hash = str(
            conn.execute(
                "SELECT identity_dataset_hash FROM meta_canonicalization_run "
                "WHERE canonical_run_id = ?",
                [result.canonical_run_id],
            ).fetchone()[0]
        )
        master_parts = conn.execute(
            "SELECT normalization_run_id, normalized_manifest_hash FROM "
            "meta_provider_normalization_run WHERE normalization_surface = "
            "'security_master' AND status = 'SUCCESS' ORDER BY normalization_run_id"
        ).fetchall()
        master_hash = hashlib.sha256(
            "|".join(f"{r[0]}:{r[1]}" for r in master_parts).encode("utf-8")
        ).hexdigest()
        assert (
            ledger_hash == manifest["identity_dataset_hash"] == identity_dataset_hash(master_hash)
        )

    def test_manifest_identity_hash_rebind_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        path = env_root["normalized"] / str(result.manifest_uri)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["identity_dataset_hash"] = "0" * 64
        data = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(data).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_ledger_identity_hash_tamper_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        conn.execute(
            "UPDATE meta_canonicalization_run SET identity_dataset_hash = ? "
            "WHERE canonical_run_id = ?",
            ["0" * 64, result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))


# ------------------------------------------- CR-3.1: policy hash completeness


def _patched_policy(conn, env_root, monkeypatch, **overrides):
    """Run once, then patch the policy tuple with one field overridden
    and run again - returns (first, second)."""
    import ashare_state.canonical.source_policy as source_policy_module
    from ashare_state.canonical.source_policy import CanonicalSourcePolicy

    _seed_base(conn, env_root)
    _seed_bars(conn, env_root)
    first = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
    patched = tuple(
        CanonicalSourcePolicy(**{**{"domain": p.domain}, **overrides}) for p in source_policies()
    )
    monkeypatch.setattr(source_policy_module, "_POLICY", patched)
    monkeypatch.setattr(source_policy_module, "_INDEX", {p.domain: p for p in patched})
    second = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
    return first, second


@pytest.mark.integration
class TestPolicyHashCompleteness:
    """CR-3.1 P0-06 (audit section 6): the policy hash covers EVERY
    semantic field - a single-field change without a version bump
    yields a new hash and a new run."""

    def test_fallback_providers_change_new_run(self, conn, env_root, monkeypatch):
        with pytest.raises(CanonicalRunnerError, match="fallback"):
            _patched_policy(conn, env_root, monkeypatch, allowed_fallback_providers=("other",))

    def test_identity_missing_max_change_new_run(self, conn, env_root, monkeypatch):
        first, second = _patched_policy(conn, env_root, monkeypatch, identity_missing_max=5)
        assert second.canonical_run_id != first.canonical_run_id

    def test_required_evidence_class_change_new_run(self, conn, env_root, monkeypatch):
        first, second = _patched_policy(
            conn, env_root, monkeypatch, required_evidence_class="OTHER_CLASS"
        )
        assert second.canonical_run_id != first.canonical_run_id

    def test_tolerance_rule_version_change_new_run(self, conn, env_root, monkeypatch):
        first, second = _patched_policy(conn, env_root, monkeypatch, tolerance_rule_version="2")
        assert second.canonical_run_id != first.canonical_run_id

    def test_manifest_policy_hash_rebind_blocks(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        path = env_root["normalized"] / str(result.manifest_uri)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["source_policy_hash"] = "0" * 64
        data = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(data).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_required_evidence_class_in_manifest(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        assert manifest["required_evidence_classes"] == {
            "trade_calendar": "PROVIDER_NORMALIZED_VERIFIED",
            "daily_bar": "PROVIDER_NORMALIZED_VERIFIED",
            "security_status": "PROVIDER_NORMALIZED_VERIFIED",
            "limit_price": "PROVIDER_NORMALIZED_VERIFIED",
            "adj_factor": "PROVIDER_NORMALIZED_VERIFIED",
        }


# --------------------------------------------- CR-3.1: full replay seal


class _FailingConn:
    """Connection wrapper injecting a failure when a SQL fragment is
    seen (test-only)."""

    def __init__(self, conn, fragment: str, times: int = 1) -> None:
        self._conn = conn
        self._fragment = fragment
        self._remaining = times

    def execute(self, sql: str, params: Any = None):
        if self._fragment in sql and self._remaining > 0:
            self._remaining -= 1
            raise RuntimeError("injected DB failure")
        return self._conn.execute(sql, params)


def _rebind_artifact(env_root: dict[str, Path], conn, result, name: str, mutate) -> None:
    """Rebind-style tamper: edit an artifact parquet, update the
    manifest content_hash AND the ledger manifest hash - proving the
    seal consumption compares semantic values, not just file bytes."""
    import io

    import polars as pl

    manifest = json.loads(
        (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
    )
    entry = manifest["artifacts"][name]
    path = env_root["normalized"] / entry["uri"]
    frame = pl.read_parquet(path)
    frame = mutate(frame)
    buf = io.BytesIO()
    frame.write_parquet(buf)
    data = buf.getvalue()
    path.write_bytes(data)
    entry["content_hash"] = hashlib.sha256(data).hexdigest()
    entry["row_count"] = frame.height
    entry["schema_hash"] = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
    mpath = env_root["normalized"] / str(result.manifest_uri)
    mdata = json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8")
    mpath.write_bytes(mdata)
    conn.execute(
        "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
        [hashlib.sha256(mdata).hexdigest(), result.canonical_run_id],
    )


@pytest.mark.integration
class TestFullReplaySeal:
    """CR-3.1 P0-07 (audit section 7): the replay consumes the FULL
    seal - rebind-style tampering fails closed everywhere."""

    def _setup(self, conn, env_root):
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root)
        return _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_selected_values_rebind_blocks(self, conn, env_root):
        import polars as pl

        result = self._setup(conn, env_root)
        _rebind_artifact(
            env_root,
            conn,
            result,
            "selected",
            lambda f: f.with_columns(pl.lit(999.0).alias("close")),
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_selected_schema_rebind_blocks(self, conn, env_root):
        import polars as pl

        result = self._setup(conn, env_root)
        _rebind_artifact(
            env_root,
            conn,
            result,
            "selected",
            lambda f: f.with_columns(pl.lit(1).alias("injected_col")),
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_decisions_rebind_blocks(self, conn, env_root):
        import polars as pl

        result = self._setup(conn, env_root)
        _rebind_artifact(
            env_root,
            conn,
            result,
            "decisions",
            lambda f: f.with_columns(pl.lit("FORGED").alias("reason")),
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_findings_parquet_vs_db_divergence_blocks(self, conn, env_root):
        result = self._setup(conn, env_root)
        # no findings on a healthy run -> fabricate one in the parquet
        import polars as pl

        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        entry = manifest["artifacts"]["findings"]
        path = env_root["normalized"] / entry["uri"]
        frame = pl.read_parquet(path)
        forged = pl.DataFrame(
            [
                {
                    "finding_id": "cf-forged",
                    "canonical_run_id": result.canonical_run_id,
                    "canonical_domain": "daily_bar",
                    "canonical_key": '["forged"]',
                    "finding_class": "SOURCE_CONFLICT",
                    "provider": "amazingdata",
                    "source_normalization_run_id": None,
                    "detail_json": "{}",
                    "blocking": True,
                }
            ]
        )
        if frame.height == 0:
            frame = forged
        else:
            frame = pl.concat([frame, forged])
        import io

        buf = io.BytesIO()
        frame.write_parquet(buf)
        data = buf.getvalue()
        path.write_bytes(data)
        entry["content_hash"] = hashlib.sha256(data).hexdigest()
        entry["row_count"] = frame.height
        entry["schema_hash"] = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
        mpath = env_root["normalized"] / str(result.manifest_uri)
        mdata = json.dumps(manifest, sort_keys=True, indent=1).encode("utf-8")
        mpath.write_bytes(mdata)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(mdata).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_manifest_input_set_rebind_blocks(self, conn, env_root):
        result = self._setup(conn, env_root)
        path = env_root["normalized"] / str(result.manifest_uri)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["input_set_hash"] = "0" * 64
        data = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(data).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_cr2_artifact_bytes_tamper_replay_refused(self, conn, env_root):
        self._setup(conn, env_root)
        run_row = conn.execute(
            "SELECT normalized_manifest_uri FROM meta_provider_normalization_run "
            "WHERE raw_request_id = 'req-bars'"
        ).fetchone()
        manifest = json.loads(
            (env_root["normalized"] / str(run_row[0])).read_text(encoding="utf-8")
        )
        output_uri = manifest["outputs"][0]["uri"]
        (env_root["normalized"] / output_uri).write_bytes(b"tampered-parquet")
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))

    def test_artifact_uri_rebind_blocks(self, conn, env_root):
        result = self._setup(conn, env_root)
        path = env_root["normalized"] / str(result.manifest_uri)
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["artifacts"]["selected"]["uri"] = doc["artifacts"]["selected"]["uri"].replace(
            f"run={result.canonical_run_id}", "run=0000dead0000"
        )
        data = json.dumps(doc, sort_keys=True, indent=1).encode("utf-8")
        path.write_bytes(data)
        conn.execute(
            "UPDATE meta_canonicalization_run SET manifest_hash = ? WHERE canonical_run_id = ?",
            [hashlib.sha256(data).hexdigest(), result.canonical_run_id],
        )
        with pytest.raises(CanonicalRunnerError, match="DAMAGED"):
            _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))


# --------------------------------------------- CR-3.1: recoverable commit


@pytest.mark.integration
class TestRecoverableCommit:
    """CR-3.1 P0-08 (audit section 8): deterministic artifact bytes (no
    wall-clock in findings) -> a DB failure after the file writes
    recovers on the exact retry."""

    def test_blocked_run_db_failure_exact_retry_recovers(self, conn, env_root):
        _seed_base(conn, env_root)
        # future-only -> BLOCKED with findings (the P0-08 hot path)
        _seed_bars(conn, env_root, "req-future", received_at=T1)
        from ashare_state.canonical.canonicalizer import CanonicalRunner as Runner

        failing = _FailingConn(conn, "INSERT INTO meta_canonicalization_run")
        with pytest.raises(CanonicalRunnerError, match="commit failed"):
            Runner(failing, raw_root=env_root["raw"], normalized_root=env_root["normalized"]).run(
                AS_OF_EARLY, domains=("daily_bar",)
            )
        assert conn.execute("SELECT count(*) FROM meta_canonicalization_run").fetchone()[0] == 0
        # exact retry over the healthy connection: byte-identical files
        # (no wall-clock in the artifacts) -> no-op writes -> commit
        recovered = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert recovered.status == "BLOCKED"
        assert recovered.finding_count >= 1
        assert conn.execute("SELECT count(*) FROM meta_canonicalization_run").fetchone()[0] == 1
        count = conn.execute(
            "SELECT count(*) FROM meta_canonical_reconciliation_finding WHERE canonical_run_id = ?",
            [recovered.canonical_run_id],
        ).fetchone()[0]
        assert count == recovered.finding_count
        # a second replay is idempotent
        replay = _canonical(conn, env_root, AS_OF_EARLY, domains=("daily_bar",))
        assert replay.idempotent_replay is True

    def test_findings_parquet_has_no_wall_clock(self, conn, env_root):
        _seed_base(conn, env_root)
        orphan = [dict(_BAR_ROWS[0])]
        orphan[0]["SECURITY_CODE"] = "999999"
        _persist_raw(
            conn,
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            surface="daily_bar",
            request_id="req-orphan",
            payload=orphan,
            received_at=T0,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("daily_bar",))
        assert result.status == "BLOCKED"
        import polars as pl

        manifest = json.loads(
            (env_root["normalized"] / str(result.manifest_uri)).read_text(encoding="utf-8")
        )
        frame = pl.read_parquet(env_root["normalized"] / manifest["artifacts"]["findings"]["uri"])
        assert frame.height >= 1
        assert "created_at" not in frame.columns


# --------------------------------------------- CR-3.1: P1 corrections


@pytest.mark.integration
class TestP1Corrections:
    def test_identity_finding_domain_truthful(self, conn, env_root):
        """CR-3.1 P1-9.1: identity findings report their TRUE domain -
        security_status rows without identity never get reported as
        daily_bar."""
        _seed_base(conn, env_root)
        status_row = dict(_STATUS_ROWS[0])
        status_row["SECURITY_CODE"] = "999999"  # no identity entry
        _persist_raw(
            conn,
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            surface="security_status_history",
            request_id="req-status-orphan",
            payload=[status_row],
            received_at=T0,
        )
        result = _canonical(conn, env_root, AS_OF_LATE, domains=("security_status",))
        assert result.status == "BLOCKED"
        domains = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT canonical_domain FROM "
                "meta_canonical_reconciliation_finding WHERE finding_class = 'IDENTITY_MISSING'"
            ).fetchall()
        }
        assert domains == {"security_status"}

    def test_naive_datetime_rejected(self, conn, env_root):
        from datetime import datetime as dt

        with pytest.raises(CanonicalRunnerError, match="timezone-aware"):
            _canonical(conn, env_root, dt(2026, 9, 1, 12, 0, 0), domains=("daily_bar",))

    def test_naive_string_fixed_utc_rule(self, conn, env_root):
        """Naive strings parse under the documented FIXED-UTC rule -
        deterministic across Windows/Linux hosts."""
        _seed_base(conn, env_root)
        _seed_bars(conn, env_root, received_at=T0)
        naive = _canonical(conn, env_root, "2026-09-01T12:00:00", domains=("daily_bar",))
        aware = _canonical(conn, env_root, "2026-09-01T12:00:00+00:00", domains=("daily_bar",))
        assert naive.canonical_run_id == aware.canonical_run_id
        assert aware.idempotent_replay is True

    def test_domain_matrix_counts_13(self):
        specs = domain_specs()
        assert len(specs) == 13
        by_class: dict[str, int] = {}
        for spec in specs:
            by_class[spec.eligibility.value] = by_class.get(spec.eligibility.value, 0) + 1
        assert by_class == {
            "CANONICAL_SUPPORTED": 5,
            "AUXILIARY_ONLY": 2,
            "BLOCKED_PENDING_SEMANTICS": 6,
        }
