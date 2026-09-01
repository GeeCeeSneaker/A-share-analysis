"""CR-2 / CR-2.1 Provider-Normalization + Quarantine contract tests
(audit 20260831: "CR-2复审与CR-2.1最终SurfaceIdentity及CommitClosure收口要求").

Covers the CR-2 adversarial matrix (work requirement section 7):

1.  normalization consumes ONLY persisted raw evidence (no SDK calls)
2.  raw meta hash tamper -> BLOCK
3.  raw payload bytes tamper -> BLOCK
4.  required field missing -> MappingValidationError -> quarantine (no sentinel)
5.  unparsable required date -> quarantine (no 1970-01-01)
6.  unparsable required numeric -> quarantine (no 0.0)
7.  legal zero/0.0 not treated as missing
8.  row-wise accounting input == normalized + quarantined (silent drop fails)
9.  trade_calendar one invalid date -> whole payload quarantine, zero output
10. multi-table payload exact table routing (no take-first-table)
11. unsupported required surface -> BLOCKED_PENDING_MAPPER run BLOCK
12. mapper exception traceable to raw request/table/row locator
13. quarantine never leaks password/token/secret/credential
14. rerun same raw+contract -> deterministic / idempotent
15. same request id with conflicting raw evidence bytes -> BLOCK
16. normalized artifact URIs obey logical-URI confinement
17. source exchange failure separated from mapping quarantine
18. provider-normalized DTO stays provider-faithful (no canonical assumptions)

Plus the CR-2.1 final closure matrix (audit section 7):

- P0-01 surface identity: stock daily_bar and index daily_bar share
  (provider_dataset, endpoint) and route to DIFFERENT mappers ONLY
  through the persisted system-derived surface; legacy ambiguous raw
  fails closed (PAYLOAD_SURFACE_AMBIGUOUS), never a request-param guess
- P0-02 immutable registry: no public mutable registry object; the
  runner API accepts no spec/mapper/registry/surface
- P0-03 ONE exact replay policy for SUCCESS/PARTIAL/BLOCKED: the
  prior run closure (manifest bytes, outputs, quarantine exact set)
  is re-verified before an idempotent return; damaged/tampered
  existing runs fail closed (repair required); the mapper code
  fingerprint is system-derived and enters the run identity
- P0-04 atomic commit closure: manifest correctness bytes carry no
  wall-clock; outputs land first, the manifest anchor lands LAST;
  ledger + quarantine set commit in ONE transaction with a count
  assertion; injected DB failures roll back and recover on exact
  retry; the quarantine evidence is sealed as an exact set
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pytest

from ashare_state.normalization import (
    MAPPER_CODE_FINGERPRINT,
    NORMALIZATION_CONTRACT_VERSION,
    DatasetNormalizationSpec,
    NormalizationRunner,
    NormalizationRunnerError,
    QuarantineScope,
    SurfaceSupport,
    lookup_spec,
    registry_specs,
    specs_for,
)
from ashare_state.providers.amazingdata.endpoint_requirements import (
    SDK_METHOD_CLASSIFICATIONS,
)
from ashare_state.storage.raw_writer import RawWriter

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
PROVIDER_SOURCE = REPO_ROOT / "src" / "ashare_state" / "providers" / "amazingdata" / "provider.py"


# ----------------------------------------------------------------- fixtures


@dataclass
class _FakeEnvelope:
    provider: str = "amazingdata"
    provider_dataset: str = "daily_bar"
    endpoint: str = "MarketData.query_kline"
    request_id: str = ""
    request_params_hash: str = "h" * 16
    requested_at: str = "2026-08-31T00:00:00+00:00"
    received_at: str = "2026-08-31T00:00:01+00:00"
    sdk_version: str | None = "1.1.9"
    runtime_version: str | None = "V4.3.0"
    account_profile_id: str = "ACCOUNT_x"
    row_count: int = 2
    status: str = "OK"
    error_class: str | None = None
    duration_ms: float = 1.0
    attempt_count: int = 1
    capability_status: str | None = None
    request_params: dict[str, Any] | None = None
    # CR-2.1: the system-derived business surface persisted on the
    # envelope ("" emulates LEGACY evidence predating the field)
    normalization_surface: str = ""


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    from ashare_state.storage import apply_migrations

    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture
def env_root(tmp_path: Path) -> dict[str, Path]:
    return {
        "raw": tmp_path / "raw",
        "normalized": tmp_path / "normalized",
    }


def _persist_raw(
    roots: dict[str, Path],
    *,
    dataset: str,
    endpoint: str,
    request_id: str,
    payload: Any,
    params: dict[str, Any] | None = None,
    status: str = "OK",
    surface: str = "",
) -> None:
    """Persist raw evidence exactly the way the production pipeline
    does (RawWriter.write_success / write_failure). ``surface=""``
    emulates legacy evidence without the surface identity field."""
    writer = RawWriter(roots["raw"])
    env = _FakeEnvelope(
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=request_id,
        request_params=params or {},
        status=status,
        row_count=len(payload) if hasattr(payload, "__len__") else 1,
        normalization_surface=surface,
    )
    if status == "ERROR":
        env.error_class = "ProviderPermissionError"
        writer.write_failure(
            provider="amazingdata",
            dataset=dataset,
            request_id=request_id,
            envelope=env,
        )
    else:
        writer.write_success(
            provider="amazingdata",
            dataset=dataset,
            request_id=request_id,
            payload=payload,
            envelope=env,
        )


def _runner(conn, roots: dict[str, Path]) -> NormalizationRunner:
    return NormalizationRunner(
        conn,
        raw_root=roots["raw"],
        normalized_root=roots["normalized"],
    )


def _request_dir(roots: dict[str, Path], dataset: str, request_id: str) -> Path:
    return roots["normalized"] / f"provider=amazingdata/dataset={dataset}/raw_request={request_id}"


def _read_output(
    roots: dict[str, Path],
    dataset: str,
    request_id: str,
    output: str = "main",
    *,
    run_id: str | None = None,
):
    """Read back one normalized output table (canonical layout)."""
    import polars as pl

    if run_id is not None:
        path = (
            _request_dir(roots, dataset, request_id)
            / f"contract={NORMALIZATION_CONTRACT_VERSION}/run={run_id}/{output}.parquet"
        )
    else:
        matches = sorted(_request_dir(roots, dataset, request_id).rglob(f"{output}.parquet"))
        assert len(matches) == 1, f"expected exactly one {output} artifact, got {matches}"
        path = matches[0]
    return pl.read_parquet(path)


def _ledger_count(conn) -> int:
    return int(conn.execute("SELECT count(*) FROM meta_provider_normalization_run").fetchone()[0])


def _output_path(
    roots: dict[str, Path],
    dataset: str,
    request_id: str,
    output: str = "main",
    *,
    run_id: str | None = None,
) -> Path:
    if run_id is not None:
        return (
            _request_dir(roots, dataset, request_id)
            / f"contract={NORMALIZATION_CONTRACT_VERSION}/run={run_id}/{output}.parquet"
        )
    matches = sorted(_request_dir(roots, dataset, request_id).rglob(f"{output}.parquet"))
    assert len(matches) == 1, f"expected exactly one {output} artifact, got {matches}"
    return matches[0]


def _manifest_path(
    roots: dict[str, Path],
    dataset: str,
    request_id: str,
    *,
    run_id: str | None = None,
) -> Path:
    if run_id is not None:
        return (
            _request_dir(roots, dataset, request_id)
            / f"contract={NORMALIZATION_CONTRACT_VERSION}/run={run_id}/manifest.json"
        )
    matches = sorted(_request_dir(roots, dataset, request_id).rglob("manifest.json"))
    assert matches, "no manifest found"
    return matches[0]


def _has_manifest(roots: dict[str, Path], dataset: str, request_id: str) -> bool:
    return bool(list(_request_dir(roots, dataset, request_id).rglob("manifest.json")))


_DAILY_BAR_ROWS = [
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

# CR-2.1: the INDEX surface rides the same endpoint+dataset with
# INDEX_CODE rows (map_index_daily_row accepts INDEX_CODE/SECURITY_CODE)
_INDEX_BAR_ROWS = [
    {
        "INDEX_CODE": "000300",
        "KLINE_TIME": 20260814,
        "OPEN_PRICE": "4000.0",
        "HIGH_PRICE": "4050.0",
        "LOW_PRICE": "3990.0",
        "CLOSE_PRICE": "4020.5",
        "VOLUME": "123456789",
        "AMOUNT": "987654321.0",
    },
    {
        "INDEX_CODE": "000905",
        "KLINE_TIME": 20260814,
        "OPEN_PRICE": "6000.0",
        "HIGH_PRICE": "6060.0",
        "LOW_PRICE": "5980.0",
        "CLOSE_PRICE": "6030.5",
        "VOLUME": "222333444",
        "AMOUNT": "123123123.0",
    },
]


# ------------------------------------------------- CR-2.1 P0-01 surface identity


@pytest.mark.integration
class TestSurfaceIdentity:
    def test_stock_and_index_surfaces_route_to_distinct_mappers(self, conn, env_root):
        """The SAME (provider_dataset, endpoint) pair routes to the
        stock DailyBarDTO mapper or the index IndexDailyDTO mapper ONLY
        through the persisted system-derived surface - the two never
        collide."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-stock",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-index",
            payload=_INDEX_BAR_ROWS,
            surface="index_daily",
        )
        results = {
            "req-stock": _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-stock"
            ),
            "req-index": _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-index"
            ),
        }
        assert results["req-stock"].status == "SUCCESS"
        assert results["req-index"].status == "SUCCESS"
        assert results["req-stock"].normalization_surface == "daily_bar"
        assert results["req-index"].normalization_surface == "index_daily"
        assert (
            results["req-stock"].normalization_run_id != results["req-index"].normalization_run_id
        )
        stock = _read_output(env_root, "daily_bar", "req-stock")
        index = _read_output(env_root, "daily_bar", "req-index")
        # the STOCK surface keeps the provider-faithful daily-bar schema
        assert "provider_symbol" in stock.columns
        assert "index_code" not in stock.columns
        assert set(stock["provider_symbol"].to_list()) == {"600000.SH", "000001.SZ"}
        # the INDEX surface keeps the provider-faithful index schema
        assert "index_code" in index.columns
        assert "provider_symbol" not in index.columns
        assert set(index["index_code"].to_list()) == {"000300", "000905"}
        assert set(index["return_type"].to_list()) == {"UNVERIFIED"}

    def test_legacy_ambiguous_raw_fails_closed(self, conn, env_root):
        """Legacy raw evidence WITHOUT the surface field on an
        ambiguous (dataset, endpoint) pair BLOCKS with
        PAYLOAD_SURFACE_AMBIGUOUS - no symbol-prefix or request-param
        guessing, ever."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-legacy",
            payload=_INDEX_BAR_ROWS,  # index-shaped rows must NOT tip the guess
            surface="",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-legacy")
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SURFACE_AMBIGUOUS"
        assert "ambiguous" in (result.error_message or "")
        assert result.error_message is not None and "daily_bar" in result.error_message
        assert result.error_message is not None and "index_daily" in result.error_message
        # no output produced
        assert result.manifest_uri is None
        assert list((env_root["normalized"] / "provider=amazingdata").rglob("*.parquet")) == []

    def test_legacy_unambiguous_pair_still_routes(self, conn, env_root):
        """Legacy evidence on an UNAMBIGUOUS pair (single registry
        entry) still routes - backward compatibility without guessing."""
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-legacy-cal",
            payload=["20260810", "20260811"],
            params={"market": "SH"},
            surface="",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-legacy-cal"
        )
        assert result.status == "SUCCESS"

    def test_declared_surface_without_registry_entry_fails_closed(self, conn, env_root):
        """A persisted surface that matches NO registry entry blocks -
        even though the (dataset, endpoint) pair itself is routable for
        another surface."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-wrong-surface",
            payload=_DAILY_BAR_ROWS,
            surface="not_a_surface",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-wrong-surface"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SHAPE_UNSUPPORTED"
        assert "not_a_surface" in (result.error_message or "")

    def test_not_applicable_surface_fails_closed(self, conn, env_root):
        """InfoData.get_index_daily is classified NOT_APPLICABLE (the
        pipeline consumes query_kline instead) - raw evidence on it
        blocks, it never silently normalizes."""
        _persist_raw(
            env_root,
            dataset="index_daily",
            endpoint="InfoData.get_index_daily",
            request_id="req-na-surface",
            payload=[{"INDEX_CODE": "000300", "TRADE_DATE": "20260814"}],
            surface="index_daily",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="index_daily", request_id="req-na-surface"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SHAPE_UNSUPPORTED"
        assert "NOT_APPLICABLE" in (result.error_message or "")


# ------------------------------------------------- CR-2.1 P0-02 immutable registry


@pytest.mark.integration
class TestImmutableRegistry:
    def test_no_public_mutable_registry_object(self):
        """The ordinary import surface exposes NO mutable registry
        object: no DATASET_NORMALIZATION_REGISTRY, only read-only
        functions returning immutable snapshots."""
        import ashare_state.normalization as pkg

        assert not hasattr(pkg, "DATASET_NORMALIZATION_REGISTRY")
        import ashare_state.normalization.registry as registry_module

        assert not hasattr(registry_module, "DATASET_NORMALIZATION_REGISTRY")
        assert registry_module.__all__ and "DATASET_NORMALIZATION_REGISTRY" not in (
            registry_module.__all__
        )
        snapshot = registry_specs()
        assert isinstance(snapshot, tuple)
        assert len(snapshot) > 0

    def test_runner_api_accepts_no_spec_registry_mapper_or_surface(self):
        """The runner constructor and run() accept NO caller-supplied
        spec/registry/mapper and NO surface argument - the surface is
        always the persisted system-derived value."""
        init_params = inspect.signature(NormalizationRunner.__init__).parameters
        for forbidden in ("spec", "registry", "mapper", "mappers", "code_commit"):
            assert forbidden not in init_params, forbidden
        run_params = inspect.signature(NormalizationRunner.run).parameters
        for forbidden in ("spec", "registry", "mapper", "mappers", "surface", "code_commit"):
            assert forbidden not in run_params, forbidden

    def test_lookup_is_exact_typed_routing(self):
        stock = lookup_spec("amazingdata", "daily_bar", "daily_bar", "MarketData.query_kline")
        index = lookup_spec("amazingdata", "index_daily", "daily_bar", "MarketData.query_kline")
        assert stock is not None and index is not None
        assert stock is not index
        assert stock.mapper_version == "daily-bar-mapper-v1"
        assert index.mapper_version == "index-daily-mapper-v1"
        # wrong provider / unknown surface -> no fuzzy fallback
        assert lookup_spec("other", "daily_bar", "daily_bar", "MarketData.query_kline") is None
        assert lookup_spec("amazingdata", "zzz", "daily_bar", "MarketData.query_kline") is None
        # specs_for reports the ambiguity of the kline pair
        entries = specs_for("amazingdata", "daily_bar", "MarketData.query_kline")
        assert len(entries) == 2

    def test_evil_spec_injection_via_private_state_still_quarantines(
        self, conn, env_root, monkeypatch
    ):
        """A tests-only injected evil spec (monkeypatch of PRIVATE
        module state - never a production API) still goes through the
        full quarantine machinery: mapping failures are quarantined
        with exact row locators, not silently mapped."""
        import ashare_state.normalization.registry as registry_module

        def evil_map_row(row: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("evil mapper failure")

        evil = DatasetNormalizationSpec(
            normalization_surface="daily_bar",
            provider_dataset="daily_bar",
            endpoint="MarketData.query_kline",
            support=SurfaceSupport.SUPPORTED_NORMALIZATION,
            mapper_version="evil-mapper-v9",
            quarantine_scope=QuarantineScope.ROW,
            allow_partial=True,
            map_row=evil_map_row,
        )
        monkeypatch.setattr(
            registry_module,
            "_INDEX",
            {
                **registry_module._INDEX,
                ("amazingdata", "daily_bar", "daily_bar", "MarketData.query_kline"): evil,
            },
        )
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-evil",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-evil")
        # zero rows survived the evil mapper: BLOCKED (never a healthy
        # "partial"), with BOTH failures carried as quarantine evidence
        assert result.status == "BLOCKED"
        assert result.quarantined_count == 2
        rows = conn.execute(
            "SELECT error_class, error_message, raw_row_ordinal FROM meta_provider_quarantine "
            "WHERE raw_request_id = ? ORDER BY raw_row_ordinal",
            ["req-evil"],
        ).fetchall()
        assert all(str(r[0]) == "NORMALIZATION_INTERNAL_ERROR" for r in rows)
        assert all("evil mapper failure" in str(r[1]) for r in rows)

    def test_mutation_attempt_on_snapshot_is_inert(self):
        """Mutating the tuple snapshot is impossible; replacing an
        entry cannot be done without private module state."""
        snapshot = registry_specs()
        with pytest.raises(TypeError):
            snapshot[0] = snapshot[1]  # type: ignore[index]


# ------------------------------------------------- CR-2.1 P0-03 replay verification


@pytest.mark.integration
class TestReplayVerification:
    def test_success_rerun_is_verified_idempotent(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-replay",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-replay")
        assert first.idempotent_replay is False
        second = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-replay")
        assert second.idempotent_replay is True
        assert second.normalization_run_id == first.normalization_run_id
        assert second.manifest_hash == first.manifest_hash
        assert _ledger_count(conn) == 1

    def test_blocked_pending_mapper_rerun_is_idempotent(self, conn, env_root):
        """A BLOCKED run (unsupported surface) replays idempotently -
        one ledger row, no duplicate blocked runs."""
        _persist_raw(
            env_root,
            dataset="corporate_action",
            endpoint="InfoData.get_dividend",
            request_id="req-div-replay",
            payload=[{"SECURITY_CODE": "600000", "EX_DIVIDEND_DATE": "20260810"}],
            surface="corporate_action",
        )
        first = _runner(conn, env_root).run(
            provider_dataset="corporate_action", request_id="req-div-replay"
        )
        second = _runner(conn, env_root).run(
            provider_dataset="corporate_action", request_id="req-div-replay"
        )
        assert first.status == second.status == "BLOCKED"
        assert first.idempotent_replay is False
        assert second.idempotent_replay is True
        assert first.normalization_run_id == second.normalization_run_id
        assert _ledger_count(conn) == 1

    def test_source_exchange_failed_rerun_is_idempotent(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-err-replay",
            payload=[],
            status="ERROR",
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-err-replay"
        )
        second = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-err-replay"
        )
        assert first.status == second.status == "BLOCKED"
        assert first.error_class == second.error_class == "SOURCE_EXCHANGE_FAILED"
        assert second.idempotent_replay is True
        assert _ledger_count(conn) == 1

    def test_partial_rerun_is_idempotent_with_same_quarantine_set(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-partial-replay",
            payload=rows,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-partial-replay"
        )
        assert first.status == "PARTIAL"
        assert first.quarantined_count == 1
        second = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-partial-replay"
        )
        assert second.idempotent_replay is True
        assert second.quarantine_set_hash == first.quarantine_set_hash
        assert _ledger_count(conn) == 1
        count = int(
            conn.execute(
                "SELECT count(*) FROM meta_provider_quarantine WHERE raw_request_id = ?",
                ["req-partial-replay"],
            ).fetchone()[0]
        )
        assert count == 1

    def test_output_parquet_tamper_rerun_fails_closed(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-tamper-out",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-tamper-out"
        )
        assert first.status == "SUCCESS"
        output = _output_path(env_root, "daily_bar", "req-tamper-out")
        output.write_bytes(b"tampered-parquet-bytes")
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-tamper-out")

    def test_output_parquet_delete_rerun_fails_closed(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-del-out",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-del-out")
        _output_path(env_root, "daily_bar", "req-del-out").unlink()
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-del-out")

    def test_manifest_tamper_rerun_fails_closed(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-tamper-man",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-tamper-man")
        manifest = _manifest_path(env_root, "daily_bar", "req-tamper-man")
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        doc["normalized_count"] = 999  # forge a healthier truth
        manifest.write_text(json.dumps(doc, sort_keys=True, indent=1), encoding="utf-8")
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-tamper-man")

    def test_manifest_delete_rerun_fails_closed(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-del-man",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-del-man")
        _manifest_path(env_root, "daily_bar", "req-del-man").unlink()
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-del-man")

    def test_quarantine_row_deleted_rerun_fails_closed(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-qtz-del",
            payload=rows,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-qtz-del")
        assert first.status == "PARTIAL"
        conn.execute(
            "DELETE FROM meta_provider_quarantine WHERE raw_request_id = ?", ["req-qtz-del"]
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-qtz-del")

    def test_quarantine_row_updated_rerun_fails_closed(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-qtz-upd",
            payload=rows,
            surface="daily_bar",
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-qtz-upd")
        conn.execute(
            "UPDATE meta_provider_quarantine SET error_message = 'scrubbed-innocent' "
            "WHERE raw_request_id = ?",
            ["req-qtz-upd"],
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-qtz-upd")

    def test_legacy_row_without_seal_never_replays_as_healthy(self, conn, env_root):
        """A CR-2 legacy ledger row (no quarantine_set_hash seal) is
        never silently replay-verified as healthy."""
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-legacy-seal",
            payload=["20260810"],
            params={"market": "SH"},
            surface="",
        )
        first = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-legacy-seal"
        )
        assert first.status == "SUCCESS"
        # simulate a CR-2 row: strip the seals and the file-side manifest
        conn.execute(
            "UPDATE meta_provider_normalization_run SET quarantine_set_hash = NULL, "
            "mapper_code_hash = NULL, normalization_surface = NULL "
            "WHERE normalization_run_id = ?",
            [first.normalization_run_id],
        )
        _manifest_path(env_root, "trade_calendar", "req-legacy-seal").unlink()
        for parquet in (env_root["normalized"] / "provider=amazingdata").rglob("*.parquet"):
            parquet.unlink()
        with pytest.raises(NormalizationRunnerError, match="DAMAGED|legacy"):
            _runner(conn, env_root).run(
                provider_dataset="trade_calendar", request_id="req-legacy-seal"
            )

    def test_mapper_code_identity_change_creates_new_run(self, conn, env_root, monkeypatch):
        """The system-derived mapper code fingerprint is part of the
        run identity: a mapper implementation change yields a NEW run
        (history preserved, never overwritten)."""
        import ashare_state.normalization.registry as registry_module

        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-code-change",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-code-change"
        )
        # simulate a mapper implementation change
        monkeypatch.setattr(registry_module, "MAPPER_CODE_FINGERPRINT", "f" * 64)
        second = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-code-change"
        )
        assert second.normalization_run_id != first.normalization_run_id
        assert second.idempotent_replay is False
        assert _ledger_count(conn) == 2

    def test_two_clean_environments_same_manifest_identity(self, tmp_path):
        """Same raw bytes + same contract + same mapper code identity
        -> the SAME manifest correctness bytes in two clean environments
        (no wall-clock in the manifest identity)."""
        from ashare_state.storage import apply_migrations

        roots1 = {"raw": tmp_path / "e1" / "raw", "normalized": tmp_path / "e1" / "normalized"}
        _persist_raw(
            roots1,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-cross-env",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        conn1 = duckdb.connect(":memory:")
        apply_migrations(conn1, MIGRATIONS_DIR)
        result1 = NormalizationRunner(
            conn1, raw_root=roots1["raw"], normalized_root=roots1["normalized"]
        ).run(provider_dataset="daily_bar", request_id="req-cross-env")
        conn1.close()

        # environment 2: the SAME raw bytes (byte-for-byte copy)
        roots2 = {"raw": tmp_path / "e2" / "raw", "normalized": tmp_path / "e2" / "normalized"}
        shutil.copytree(roots1["raw"], roots2["raw"])
        conn2 = duckdb.connect(":memory:")
        apply_migrations(conn2, MIGRATIONS_DIR)
        result2 = NormalizationRunner(
            conn2, raw_root=roots2["raw"], normalized_root=roots2["normalized"]
        ).run(provider_dataset="daily_bar", request_id="req-cross-env")
        conn2.close()

        assert result1.manifest_hash == result2.manifest_hash
        assert result1.normalization_run_id == result2.normalization_run_id
        m1 = json.loads(
            _manifest_path(roots1, "daily_bar", "req-cross-env").read_text(encoding="utf-8")
        )
        m2 = json.loads(
            _manifest_path(roots2, "daily_bar", "req-cross-env").read_text(encoding="utf-8")
        )
        assert m1 == m2


# ------------------------------------------------- CR-2.1 P0-04 commit closure


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


@pytest.mark.integration
class TestAtomicCommitClosure:
    def test_ledger_insert_failure_then_exact_retry_recovers(self, conn, env_root):
        """Failure A closed: a ledger INSERT failure AFTER the file-side
        commit leaves deterministic files behind; the exact retry
        recovers (identical manifest bytes are a no-op) - ONE ledger
        row, no orphan/duplicate."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-db-fail",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        failing = _FailingConn(conn, "INSERT INTO meta_provider_normalization_run")
        with pytest.raises(NormalizationRunnerError, match="commit failed"):
            NormalizationRunner(
                failing, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
            ).run(provider_dataset="daily_bar", request_id="req-db-fail")
        assert _ledger_count(conn) == 0
        # the deterministic anchor survived: manifest exists
        assert _manifest_path(env_root, "daily_bar", "req-db-fail").is_file()
        # exact retry: identical bytes -> no-op -> ledger reconciled
        recovered = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-db-fail"
        )
        assert recovered.status == "SUCCESS"
        assert recovered.idempotent_replay is False  # first SUCCESSFUL ledger write
        assert _ledger_count(conn) == 1

    def test_quarantine_insert_failure_rolls_back_and_recovers(self, conn, env_root):
        """Failure B closed: a quarantine INSERT failure rolls the run
        row back (no partial main-path-healthy truth); the retry
        recovers the COMPLETE quarantine set."""
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-qtz-fail",
            payload=rows,
            surface="daily_bar",
        )
        failing = _FailingConn(conn, "INSERT INTO meta_provider_quarantine")
        with pytest.raises(NormalizationRunnerError, match="commit failed"):
            NormalizationRunner(
                failing, raw_root=env_root["raw"], normalized_root=env_root["normalized"]
            ).run(provider_dataset="daily_bar", request_id="req-qtz-fail")
        # transaction rolled back: NO run row survived
        assert _ledger_count(conn) == 0
        count = int(
            conn.execute(
                "SELECT count(*) FROM meta_provider_quarantine WHERE raw_request_id = ?",
                ["req-qtz-fail"],
            ).fetchone()[0]
        )
        assert count == 0
        # retry: complete recovery
        recovered = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-qtz-fail"
        )
        assert recovered.status == "PARTIAL"
        assert recovered.quarantined_count == 1
        assert _ledger_count(conn) == 1

    def test_multi_output_write_failure_leaves_no_valid_anchor(self, conn, env_root, monkeypatch):
        """A multi-output surface whose SECOND output write fails
        leaves NO valid final manifest anchor and NO ledger row; the
        retry recovers all three outputs + the manifest."""
        status_rows = [
            {
                "SECURITY_CODE": "600000",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20260814",
                "PRECLOSE": "10.0",
                "HIGH_LIMITED": "11.0",
                "LOW_LIMITED": "9.0",
                "IS_ST_SEC": "0",
                "IS_XR_SEC": "1",
                "IS_WD_SEC": "0",
            },
        ]
        _persist_raw(
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            request_id="req-multi-out",
            payload=status_rows,
            surface="security_status_history",
        )
        calls = {"n": 0}
        original = NormalizationRunner._write_immutable

        def fail_second(path: Path, data: bytes, run_id: str) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                msg = "injected output write failure"
                raise NormalizationRunnerError(msg)
            return original(path, data, run_id)

        monkeypatch.setattr(NormalizationRunner, "_write_immutable", staticmethod(fail_second))
        with pytest.raises(NormalizationRunnerError, match="injected output write failure"):
            _runner(conn, env_root).run(
                provider_dataset="history_stock_status", request_id="req-multi-out"
            )
        # no manifest anchor, no ledger row
        assert not _has_manifest(env_root, "history_stock_status", "req-multi-out")
        assert _ledger_count(conn) == 0
        # retry without the injection recovers
        result = _runner(conn, env_root).run(
            provider_dataset="history_stock_status", request_id="req-multi-out"
        )
        assert result.status == "SUCCESS"
        for output in ("security_status", "limit_price", "corporate_action"):
            assert _output_path(env_root, "history_stock_status", "req-multi-out", output).is_file()

    def test_manifest_correctness_bytes_carry_no_wall_clock(self, conn, env_root):
        """The manifest identity contains NO wall-clock and NO
        caller-declared provenance - only deterministic correctness
        bytes."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-no-clock",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-no-clock"
        )
        manifest = json.loads(
            _manifest_path(env_root, "daily_bar", "req-no-clock").read_text(encoding="utf-8")
        )
        assert (
            result.manifest_hash
            == hashlib.sha256(
                _manifest_path(env_root, "daily_bar", "req-no-clock").read_bytes()
            ).hexdigest()
        )
        assert "completed_at" not in manifest
        assert "started_at" not in manifest
        assert "code_commit" not in manifest
        assert manifest["mapper_code_hash"] == MAPPER_CODE_FINGERPRINT
        assert manifest["quarantine_set_hash"] == result.quarantine_set_hash

    def test_quarantine_set_hash_seals_exact_set(self, conn, env_root):
        """The quarantine_set_hash in the ledger and the manifest are
        the same seal, and it binds the semantic records exactly."""
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[0].pop("VOLUME")  # one bad row, one good row -> genuine PARTIAL
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-seal",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal")
        assert result.status == "PARTIAL"
        manifest = json.loads(
            _manifest_path(env_root, "daily_bar", "req-seal").read_text(encoding="utf-8")
        )
        ledger_hash = conn.execute(
            "SELECT quarantine_set_hash FROM meta_provider_normalization_run "
            "WHERE normalization_run_id = ?",
            [result.normalization_run_id],
        ).fetchone()[0]
        assert manifest["quarantine_set_hash"] == str(ledger_hash) == result.quarantine_set_hash
        # the quarantine ids are deterministic (uuid5) - a rerun never
        # produces a second row set
        ids = [
            str(r[0])
            for r in conn.execute(
                "SELECT quarantine_id FROM meta_provider_quarantine WHERE raw_request_id = ?",
                ["req-seal"],
            ).fetchall()
        ]
        assert len(ids) == len(set(ids)) == 1
        assert all(qid.startswith("qtz-") for qid in ids)


# ------------------------------------------------------------ CR-2 carried over


@pytest.mark.integration
class TestRawEvidenceSoleInput:
    def test_normalizes_persisted_raw_evidence(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-1",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-1")
        assert result.status == "SUCCESS"
        assert result.input_count == 2
        assert result.normalized_count == 2
        assert result.quarantined_count == 0
        assert result.manifest_uri is not None
        frame = _read_output(env_root, "daily_bar", "req-1")
        assert frame.height == 2
        assert set(frame["provider_symbol"].to_list()) == {"600000.SH", "000001.SZ"}

    def test_missing_raw_meta_is_caller_misuse(self, conn, env_root):
        with pytest.raises(NormalizationRunnerError, match="no raw meta"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-none")

    def test_raw_meta_hash_tamper_blocks(self, conn, env_root):
        """The persisted meta hash no longer matches the payload's
        content hash -> the verified reader rejects the evidence."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-tamper",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        meta_path = (
            env_root["raw"] / "provider=amazingdata" / "dataset=daily_bar" / "req-tamper.meta.json"
        )
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        doc["content_hash"] = "0" * 64
        meta_path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-tamper")
        assert result.status == "BLOCKED"
        assert result.error_class == "RAW_EVIDENCE_INVALID"

    def test_raw_payload_bytes_tamper_blocks(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-payload-tamper",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        import polars as pl

        payloads = list(
            (env_root["raw"] / "provider=amazingdata" / "dataset=daily_bar").glob(
                "req-payload-tamper*.parquet"
            )
        )
        assert payloads, "raw payload must exist"
        # rewrite with different bytes but keep the meta untouched
        frame = pl.read_parquet(payloads[0])
        frame = frame.with_columns(pl.lit("999.0").alias("CLOSE_PRICE"))
        frame.write_parquet(payloads[0])
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-payload-tamper"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "RAW_EVIDENCE_INVALID"

    def test_source_exchange_failure_is_not_a_mapping_quarantine(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-err",
            payload=[],
            status="ERROR",
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-err")
        assert result.status == "BLOCKED"
        assert result.error_class == "SOURCE_EXCHANGE_FAILED"
        assert result.quarantined_count == 0


@pytest.mark.integration
class TestNoSentinelNoSilentDrop:
    def test_required_field_missing_quarantines_without_sentinel(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0])]
        rows[0].pop("SECURITY_CODE")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-missing",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-missing")
        assert result.status == "BLOCKED"  # allow_partial=True but 100% bad rows
        q = conn.execute(
            "SELECT error_class, error_message, raw_row_ordinal FROM meta_provider_quarantine "
            "WHERE raw_request_id = ?",
            ["req-missing"],
        ).fetchone()
        assert str(q[0]) == "MAPPING_VALIDATION_FAILED"
        assert "SECURITY_CODE" in str(q[1])
        assert q[2] == 0
        frame = _read_output(env_root, "daily_bar", "req-missing")
        assert frame.height == 0  # nothing normalized - no sentinel row

    def test_unparsable_date_quarantines_no_epoch_sentinel(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0])]
        rows[0]["KLINE_TIME"] = "not-a-date"
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-bad-date",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-bad-date"
        )
        assert result.quarantined_count == 1
        error = conn.execute(
            "SELECT error_message FROM meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-bad-date"],
        ).fetchone()[0]
        assert "KLINE_TIME" in str(error)
        frame = _read_output(env_root, "daily_bar", "req-bad-date")
        assert frame.height == 0

    def test_unparsable_numeric_quarantines_no_zero_sentinel(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0])]
        rows[0]["CLOSE_PRICE"] = "abc"
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-bad-num",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-bad-num")
        assert result.quarantined_count == 1
        frame = _read_output(env_root, "daily_bar", "req-bad-num")
        assert frame.height == 0

    def test_legal_zero_not_treated_as_missing(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0])]
        rows[0]["VOLUME"] = "0"
        rows[0]["AMOUNT"] = "0.0"
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-zero",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-zero")
        assert result.status == "SUCCESS"
        frame = _read_output(env_root, "daily_bar", "req-zero")
        assert frame["volume"][0] == 0.0
        assert frame["amount"][0] == 0.0

    def test_row_accounting_invariant_machine_enforced(self, conn, env_root):
        """Mixed good/bad rows: input == normalized + quarantined for
        every combination - the runtime enforces it, and the counts in
        the ledger agree."""
        rows = []
        for i in range(4):
            row = dict(_DAILY_BAR_ROWS[i % 2])
            row["SECURITY_CODE"] = f"60000{i}"
            rows.append(row)
        rows[2].pop("VOLUME")  # one bad row
        rows[3]["AMOUNT"] = None  # another bad row
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-accounting",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-accounting"
        )
        assert result.input_count == 4
        assert result.normalized_count + result.quarantined_count == 4
        assert result.status == "PARTIAL"


@pytest.mark.integration
class TestWholePayloadQuarantine:
    def test_one_invalid_calendar_date_quarantines_whole_payload(self, conn, env_root):
        """One unparsable trading day -> ZERO normalized calendar + ONE
        whole-payload quarantine + BLOCKED run."""
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-cal-bad",
            payload=["20260810", "20260811", "not-a-date", "20260812"],
            params={"market": "SH"},
        )
        result = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-cal-bad"
        )
        assert result.status == "BLOCKED"
        assert result.quarantined_count == 1
        q = conn.execute(
            "SELECT quarantine_scope, raw_row_ordinal, error_class FROM "
            "meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-cal-bad"],
        ).fetchone()
        assert str(q[0]) == "WHOLE_PAYLOAD"
        assert q[1] is None
        assert str(q[2]) == "MAPPING_VALIDATION_FAILED"
        # zero normalized output: no manifest / no main parquet
        assert result.manifest_uri is None
        outputs = list(
            (env_root["normalized"] / "provider=amazingdata" / "dataset=trade_calendar").rglob(
                "*.parquet"
            )
        )
        assert outputs == []

    def test_valid_calendar_normalizes(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-cal-ok",
            payload=["20260810", "20260811"],
            params={"market": "SH"},
        )
        result = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-cal-ok"
        )
        assert result.status == "SUCCESS"
        assert result.normalized_count == 2
        frame = _read_output(env_root, "trade_calendar", "req-cal-ok")
        assert frame.height == 1  # one calendar DTO row
        assert frame["market"][0] == "SH"


@pytest.mark.integration
class TestRoutingAndUnsupported:
    def test_unsupported_surface_blocks_no_silent_skip(self, conn, env_root):
        """corporate_action (dividend) has no verified mapper yet:
        BLOCKED_PENDING_MAPPER -> run BLOCKED (never looks SUCCESS)."""
        _persist_raw(
            env_root,
            dataset="corporate_action",
            endpoint="InfoData.get_dividend",
            request_id="req-div",
            payload=[{"SECURITY_CODE": "600000", "EX_DIVIDEND_DATE": "20260810"}],
            surface="corporate_action",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="corporate_action", request_id="req-div"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SHAPE_UNSUPPORTED"
        assert "BLOCKED_PENDING_MAPPER" in (result.error_message or "")

    def test_unknown_surface_blocks(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="industry_taxonomy",
            endpoint="InfoData.get_industry_base_info",
            request_id="req-base-info",
            payload=[{"SECURITY_CODE": "600000", "SW_INDUSTRY_CODE": "310000"}],
            surface="industry_taxonomy",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="industry_taxonomy", request_id="req-base-info"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SHAPE_UNSUPPORTED"

    def test_multi_table_payload_requires_exact_table_routing(self, conn, env_root):
        """A multi-table raw payload for a spec with no source_table
        routing BLOCKS - taking the first table is forbidden."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-multi-table",
            payload={"table_a": _DAILY_BAR_ROWS, "table_b": _DAILY_BAR_ROWS},
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-multi-table"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SHAPE_UNSUPPORTED"
        assert "first table" in (result.error_message or "")


@pytest.mark.integration
class TestQuarantineEvidenceQuality:
    def test_quarantine_locates_exact_raw_row(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-locate",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-locate")
        assert result.quarantined_count == 1
        q = conn.execute(
            "SELECT raw_request_id, raw_row_ordinal, source_key, error_message, mapper_identity "
            "FROM meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-locate"],
        ).fetchone()
        assert str(q[0]) == "req-locate"
        assert q[1] == 1
        assert str(q[2]) == "000001"
        assert "VOLUME" in str(q[3])
        assert str(q[4]).startswith(
            "daily_bar/daily_bar/MarketData.query_kline@daily-bar-mapper-v1#"
        )

    def test_quarantine_never_leaks_secrets(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0])]
        rows[0].pop("SECURITY_CODE")
        rows[0]["password"] = "hunter2"
        rows[0]["api_token"] = "tok-123"
        rows[0]["client_secret"] = "s3cr3t"
        rows[0]["credentials_blob"] = "cred"
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-secrets",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-secrets")
        assert result.quarantined_count == 1
        ctx = conn.execute(
            "SELECT error_context_json FROM meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-secrets"],
        ).fetchone()[0]
        text = str(ctx)
        assert "hunter2" not in text
        assert "tok-123" not in text
        assert "s3cr3t" not in text
        assert "cred" not in text.replace("credentials", "")
        assert "[REDACTED]" in text

    def test_mapper_internal_exception_is_recorded_not_swallowed(self, conn, env_root):
        """A mapper crashing with an unexpected exception is recorded
        as NORMALIZATION_INTERNAL_ERROR quarantine evidence, never
        silently dropped."""
        import ashare_state.normalization.registry as registry_module

        def crashing_map_row(row: dict[str, Any]) -> dict[str, Any]:
            if row.get("SECURITY_CODE") == "000001":
                msg = "boom"
                raise RuntimeError(msg)
            from ashare_state.providers.amazingdata.mapper import map_daily_bar_row

            return {"main": map_daily_bar_row(row)}

        crashing = DatasetNormalizationSpec(
            normalization_surface="daily_bar",
            provider_dataset="daily_bar",
            endpoint="MarketData.query_kline",
            support=SurfaceSupport.SUPPORTED_NORMALIZATION,
            mapper_version="crashing-mapper-v1",
            quarantine_scope=QuarantineScope.ROW,
            allow_partial=True,
            map_row=crashing_map_row,
        )
        monkeypatch_holder = pytest.MonkeyPatch()
        monkeypatch_holder.setattr(
            registry_module,
            "_INDEX",
            {
                **registry_module._INDEX,
                ("amazingdata", "daily_bar", "daily_bar", "MarketData.query_kline"): crashing,
            },
        )
        try:
            _persist_raw(
                env_root,
                dataset="daily_bar",
                endpoint="MarketData.query_kline",
                request_id="req-crash",
                payload=_DAILY_BAR_ROWS,
                surface="daily_bar",
            )
            result = _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-crash"
            )
            assert result.status == "PARTIAL"
            assert result.quarantined_count == 1
            q = conn.execute(
                "SELECT error_class, error_message, raw_row_ordinal, mapper_identity "
                "FROM meta_provider_quarantine WHERE raw_request_id = ?",
                ["req-crash"],
            ).fetchone()
            assert str(q[0]) == "NORMALIZATION_INTERNAL_ERROR"
            assert "RuntimeError: boom" in str(q[1])
            assert q[2] == 1
            assert str(q[3]).startswith(
                "daily_bar/daily_bar/MarketData.query_kline@crashing-mapper-v1#"
            )
        finally:
            monkeypatch_holder.undo()


@pytest.mark.integration
class TestDeterministicReplay:
    def test_deterministic_semantic_output(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-det",
            payload=list(reversed(_DAILY_BAR_ROWS)),  # input order flipped
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-det")
        assert result.status == "SUCCESS"
        frame = _read_output(env_root, "daily_bar", "req-det")
        # sorted output: input order does not leak into the artifact
        assert frame["provider_symbol"].to_list() == sorted(frame["provider_symbol"].to_list())

    def test_conflicting_raw_evidence_bytes_block(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-conflict",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-conflict")
        assert first.status == "SUCCESS"
        # simulate the impossible: same request id, different evidence
        meta_path = (
            env_root["raw"]
            / "provider=amazingdata"
            / "dataset=daily_bar"
            / "req-conflict.meta.json"
        )
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        doc["request_params_hash"] = "f" * 64
        meta_path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
        second = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-conflict"
        )
        assert second.status == "BLOCKED"
        assert second.error_class == "RAW_EVIDENCE_INVALID"
        assert "conflicting raw evidence" in (second.error_message or "")
        assert _ledger_count(conn) == 2  # history preserved, never overwritten


@pytest.mark.integration
class TestLogicalURIConfinement:
    def test_normalized_artifact_uris_are_canonical(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-uri",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-uri")
        assert result.manifest_uri == (
            f"provider=amazingdata/dataset=daily_bar/raw_request=req-uri/"
            f"contract={NORMALIZATION_CONTRACT_VERSION}/run={result.normalization_run_id}/"
            "manifest.json"
        )

    @pytest.mark.parametrize(
        "evil",
        ["../escape", "a/b", "a\\b", "..", "sp ace", "a:b"],
    )
    def test_evil_request_id_fails_closed(self, conn, env_root, evil):
        with pytest.raises(NormalizationRunnerError):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id=evil)


@pytest.mark.integration
class TestProviderFaithfulOutput:
    def test_daily_bar_preserves_provider_units_and_literals(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-faithful",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-faithful")
        frame = _read_output(env_root, "daily_bar", "req-faithful")
        by_symbol = {
            frame["provider_symbol"][i]: {col: frame[col][i] for col in frame.columns}
            for i in range(frame.height)
        }
        # provider symbol rule (600000 -> 600000.SH), provider units untouched
        assert set(by_symbol) == {"600000.SH", "000001.SZ"}
        stock_row = by_symbol["600000.SH"]
        assert stock_row["kline_type"] == "DAY"
        assert stock_row["kline_time"] == 20260814
        assert stock_row["open"] == 10.0  # provider unit passed through
        assert stock_row["volume"] == 12345.0
        assert stock_row["amount"] == 67890.0

    def test_industry_member_keeps_unverified_marker(self, conn, env_root):
        rows = [
            {
                "SECURITY_CODE": "600000",
                "INDUSTRY_CODE": "310000",
                "INDUSTRY_LEVEL": "1",
                "INDUSTRY_IN_DATE": "20200101",
                "CURRENT_SIGN": "1",
            }
        ]
        _persist_raw(
            env_root,
            dataset="industry_taxonomy",
            endpoint="InfoData.get_industry_constituent",
            request_id="req-industry",
            payload=rows,
            surface="industry_taxonomy",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="industry_taxonomy", request_id="req-industry"
        )
        assert result.status == "SUCCESS"
        frame = _read_output(env_root, "industry_taxonomy", "req-industry")
        assert frame["taxonomy_owner"][0] == "GALAXY_UNVERIFIED"

    def test_status_routes_to_three_outputs(self, conn, env_root):
        status_rows = [
            {
                "SECURITY_CODE": "600000",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20260814",
                "PRECLOSE": "10.0",
                "HIGH_LIMITED": "11.0",
                "LOW_LIMITED": "9.0",
                "IS_ST_SEC": "0",
                "IS_XR_SEC": "1",
                "IS_WD_SEC": "0",
            },
        ]
        _persist_raw(
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            request_id="req-status",
            payload=status_rows,
            surface="security_status_history",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="history_stock_status", request_id="req-status"
        )
        assert result.status == "SUCCESS"
        for output in ("security_status", "limit_price", "corporate_action"):
            frame = _read_output(env_root, "history_stock_status", "req-status", output)
            assert frame.height == 1
        corporate = _read_output(env_root, "history_stock_status", "req-status", "corporate_action")
        assert corporate["event_type"][0] == "STATUS_FLAG_PROJECTION"
        limit = _read_output(env_root, "history_stock_status", "req-status", "limit_price")
        assert limit["up_limit"][0] == 11.0
        assert limit["down_limit"][0] == 9.0


@pytest.mark.integration
class TestStatusMachine:
    def test_all_good_rows_success(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-good",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-good")
        assert result.status == "SUCCESS"
        assert result.error_class is None

    def test_row_quarantine_partial_when_allowed(self, conn, env_root):
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-partial",
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-partial")
        assert result.status == "PARTIAL"

    def test_whole_payload_quarantine_blocks(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-cal-block",
            payload=["20260810", "bad"],
            params={"market": "SH"},
        )
        result = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-cal-block"
        )
        assert result.status == "BLOCKED"


# ---------------------------------------------------------- structural guards


def _facade_surfaces() -> set[tuple[str, str, str]]:
    """AST-extract every (require_capability, dataset, endpoint)
    triple the provider facade declares via _call_or_exchange."""
    tree = ast.parse(PROVIDER_SOURCE.read_text(encoding="utf-8"))
    surfaces: set[tuple[str, str, str]] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "_call_or_exchange":
            continue
        endpoint = (
            node.args[0].value
            if len(node.args) > 0 and isinstance(node.args[0], ast.Constant)
            else None
        )
        dataset = (
            node.args[1].value
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
            else None
        )
        capability = None
        for kw in node.keywords:
            if kw.arg == "require_capability" and isinstance(kw.value, ast.Constant):
                capability = kw.value.value
        if endpoint and dataset and capability:
            surfaces.add((str(capability), str(dataset), str(endpoint)))
    return surfaces


@pytest.mark.integration
class TestRegistryStructuralGuard:
    def test_every_provider_facade_surface_is_explicitly_classified(self):
        """CR-2.1 coverage guard: every provider facade exchange
        surface (capability, dataset, endpoint) has an explicit
        registry entry, and every non-NOT_APPLICABLE registry entry is
        backed by a facade wrapper - no silent presence/absence on
        either side."""
        facade = _facade_surfaces()
        assert len(facade) >= 15  # the full exchange facade
        production = {
            (spec.normalization_surface, spec.provider_dataset, spec.endpoint)
            for spec in registry_specs()
            if spec.support is SurfaceSupport.SUPPORTED_NORMALIZATION
        }
        blocked = {
            (spec.normalization_surface, spec.provider_dataset, spec.endpoint)
            for spec in registry_specs()
            if spec.support is SurfaceSupport.BLOCKED_PENDING_MAPPER
        }
        # every facade wrapper is classified in the registry
        assert facade == production | blocked
        # the ambiguous kline pair carries TWO distinct facade wrappers
        kline = {entry for entry in facade if entry[2] == "MarketData.query_kline"}
        assert ("daily_bar", "daily_bar", "MarketData.query_kline") in kline
        assert ("index_daily", "daily_bar", "MarketData.query_kline") in kline

    def test_sdk_method_classifications_cross_checked_with_registry(self):
        """CR-2.1 audit section 2.4: every SDK capability/endpoint
        surface of the provider contract has an explicit normalization
        classification - OPTIONAL_NON_APPROVAL surfaces are declared
        NOT_APPLICABLE instead of vanishing from structural truth."""
        sdk = {(c.capability, c.endpoint) for c in SDK_METHOD_CLASSIFICATIONS}
        registry = {(spec.normalization_surface, spec.endpoint) for spec in registry_specs()}
        assert sdk == registry
        assert len(sdk) == 18  # 15 consumable + 3 NOT_APPLICABLE
        not_applicable = {
            (spec.normalization_surface, spec.endpoint)
            for spec in registry_specs()
            if spec.support is SurfaceSupport.NOT_APPLICABLE
        }
        assert not_applicable == {
            ("index_daily", "InfoData.get_index_daily"),
            ("industry_taxonomy", "InfoData.get_industry_weight"),
            ("industry_taxonomy", "InfoData.get_industry_daily"),
        }

    def test_supported_specs_have_mappers(self):
        for spec in registry_specs():
            if spec.support is SurfaceSupport.SUPPORTED_NORMALIZATION:
                assert spec.map_row is not None or spec.map_payload is not None
            if spec.support is SurfaceSupport.BLOCKED_PENDING_MAPPER:
                assert spec.map_row is None and spec.map_payload is None

    def test_runner_has_no_provider_calls(self):
        """AST: the runner source contains no provider/SDK access -
        its only input is the persisted raw evidence."""
        runner_source = (
            REPO_ROOT / "src" / "ashare_state" / "normalization" / "runner.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(runner_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert (
                    "providers.amazingdata" not in module
                    or module.endswith("mapper")
                    or module.endswith("dto")
                    or module.endswith("errors")
                ), f"runner imports provider module {module}"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "ashare_state.providers.amazingdata.provider"

    def test_mapper_code_fingerprint_is_system_derived(self):
        """The mapper code fingerprint is a full SHA-256 over the
        governed mapper + DTO module sources and enters every spec
        identity."""
        assert len(MAPPER_CODE_FINGERPRINT) == 64
        for spec in registry_specs():
            identity_suffix = (
                f"{spec.normalization_surface}/{spec.provider_dataset}/{spec.endpoint}"
            )
            assert identity_suffix  # identities carry the typed surface

    def test_provider_facade_kline_wrappers_declare_distinct_surfaces(self):
        """CR-2.2 P0-01 (audit 20260901 section 2): the surface identity
        is STRICTLY derived from the provider-owned capability contract
        - query_kline_exchange and query_index_kline_exchange
        distinguish themselves ONLY via require_capability, and NO
        _call_or_exchange call site carries a normalization_surface
        override (an ordinary caller can never declare a correctness
        identity)."""
        tree = ast.parse(PROVIDER_SOURCE.read_text(encoding="utf-8"))
        capability_by_wrapper: dict[str, list[str]] = {}
        surface_overrides: list[str] = []
        for class_node in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            # scope attribution to METHOD-level function defs only -
            # nested closures (e.g. invoke) never own an exchange call
            for method in (n for n in class_node.body if isinstance(n, ast.FunctionDef)):
                for node in ast.walk(method):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "_call_or_exchange"
                    ):
                        for kw in node.keywords:
                            if kw.arg == "require_capability" and isinstance(
                                kw.value, ast.Constant
                            ):
                                capability_by_wrapper.setdefault(method.name, []).append(
                                    str(kw.value.value)
                                )
                            if kw.arg == "normalization_surface":
                                surface_overrides.append(method.name)
        assert surface_overrides == [], (
            f"call sites still declare a caller-side surface override: {surface_overrides}"
        )
        assert capability_by_wrapper.get("query_kline_exchange") == ["daily_bar"]
        assert capability_by_wrapper.get("query_index_kline_exchange") == ["index_daily"]

    def test_call_exchange_has_no_surface_override_parameter(self):
        """CR-2.2 P0-01: the low-level ``call_exchange`` signature
        exposes NO normalization_surface parameter - a caller passing
        capability='daily_bar' can never produce an index_daily surface
        envelope, and the surface derivation is capability-only."""
        from ashare_state.providers.amazingdata.provider import AmazingDataProvider

        params = inspect.signature(AmazingDataProvider.call_exchange).parameters
        assert "normalization_surface" not in params
        source = PROVIDER_SOURCE.read_text(encoding="utf-8")
        assert 'surface_identity = str(require_capability or "")' in source


# ------------------------------------------------- CR-2.2 P0-02: provenance


def _meta_path(roots: dict[str, Path], dataset: str, request_id: str) -> Path:
    return roots["raw"] / "provider=amazingdata" / f"dataset={dataset}" / f"{request_id}.meta.json"


@pytest.mark.integration
class TestRawEvidenceBindingPermanence:
    """CR-2.2 P0-02A (audit 20260901 section 3): a request's raw
    evidence hash is a PERMANENT binding - a conflicting hash is an
    INCIDENT HARD BLOCK that can never be legitimized by the BLOCK run
    that observed it."""

    def test_hash_conflict_blocks_repeatedly(self, conn, env_root):
        """H1 SUCCESS -> tamper to H2 -> BLOCKED; the SECOND and THIRD
        runs of the same tampered evidence are STILL BLOCKED (the
        conflict BLOCK run does not become the new baseline), and the
        conflict replays idempotently."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-perm",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-perm")
        assert first.status == "SUCCESS"
        meta = _meta_path(env_root, "daily_bar", "req-perm")
        original = meta.read_bytes()
        doc = json.loads(original)
        doc["request_params_hash"] = "f" * 64
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        blocked_ids = []
        for _ in range(3):
            result = _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-perm"
            )
            assert result.status == "BLOCKED"
            assert result.error_class == "RAW_EVIDENCE_INVALID"
            assert "conflicting raw evidence" in (result.error_message or "")
            blocked_ids.append(result.normalization_run_id)
        # the three conflict observations replay the SAME conflict run
        assert blocked_ids[1] == blocked_ids[0] and blocked_ids[2] == blocked_ids[0]
        # no SUCCESS/PARTIAL run is ever bound to the tampered hash
        tampered_hash = hashlib.sha256(meta.read_bytes()).hexdigest()
        healthy = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run "
            "WHERE raw_request_id = ? AND raw_evidence_hash = ? "
            "AND status != 'BLOCKED'",
            ["req-perm", tampered_hash],
        ).fetchone()[0]
        assert int(healthy) == 0
        # the conflict run is explicitly marked (excluded from baseline)
        marked = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run "
            "WHERE raw_request_id = ? AND evidence_conflict = TRUE",
            ["req-perm"],
        ).fetchone()[0]
        assert int(marked) >= 1
        # exactly one SUCCESS run (the original H1 lineage) + conflict runs
        successes = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run "
            "WHERE raw_request_id = ? AND status = 'SUCCESS'",
            ["req-perm"],
        ).fetchone()[0]
        assert int(successes) == 1

    def test_surface_swap_tamper_never_succeeds(self, conn, env_root):
        """A tampered meta whose surface field is flipped to index_daily
        changes the meta BYTES (hash conflict) and can NEVER produce an
        index_daily SUCCESS run - the conflict blocks before routing."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-swap",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        assert (
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-swap").status
            == "SUCCESS"
        )
        meta = _meta_path(env_root, "daily_bar", "req-swap")
        doc = json.loads(meta.read_bytes())
        doc["normalization_surface"] = "index_daily"  # forge the surface
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        for _ in range(2):
            result = _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-swap"
            )
            assert result.status == "BLOCKED"
            assert result.error_class == "RAW_EVIDENCE_INVALID"
        index_success = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run "
            "WHERE raw_request_id = ? AND normalization_surface = 'index_daily' "
            "AND status != 'BLOCKED'",
            ["req-swap"],
        ).fetchone()[0]
        assert int(index_success) == 0

    def test_repaired_hash_replays_original_run(self, conn, env_root):
        """H1 SUCCESS -> H2 conflict BLOCK -> the raw evidence is
        REPAIRED back to the exact original bytes -> the ORIGINAL H1 run
        is replayed idempotently (no new run, no duplicate)."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-repair",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        first = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-repair")
        assert first.status == "SUCCESS"
        meta = _meta_path(env_root, "daily_bar", "req-repair")
        original = meta.read_bytes()
        doc = json.loads(original)
        doc["request_params_hash"] = "f" * 64
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        conflict = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-repair"
        )
        assert conflict.status == "BLOCKED"
        # repair: restore the exact original bytes
        meta.write_bytes(original)
        repaired = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-repair"
        )
        assert repaired.status == "SUCCESS"
        assert repaired.idempotent_replay is True
        assert repaired.normalization_run_id == first.normalization_run_id
        # lineage: one SUCCESS run + one conflict run, nothing else
        assert _ledger_count(conn) == 2

    def test_mapper_rollback_replays_historical_run(self, conn, env_root, monkeypatch):
        """mapper identity A -> B -> back to A: the rollback EXACTLY
        replays the historical A run (full-history exact lookup - no
        duplicate-PK error, no B-shadowed latest-run comparison)."""
        import ashare_state.normalization.registry as registry_module

        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-roll",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        run_a = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-roll")
        assert run_a.status == "SUCCESS" and run_a.idempotent_replay is False
        monkeypatch.setattr(registry_module, "MAPPER_CODE_FINGERPRINT", "b" * 64)
        run_b = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-roll")
        assert run_b.status == "SUCCESS"
        assert run_b.normalization_run_id != run_a.normalization_run_id
        monkeypatch.undo()
        replay_a = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-roll")
        assert replay_a.idempotent_replay is True
        assert replay_a.normalization_run_id == run_a.normalization_run_id
        assert replay_a.manifest_hash == run_a.manifest_hash
        assert _ledger_count(conn) == 2  # exactly A + B, no duplicates

    def test_contract_rollback_replays_historical_run(self, conn, env_root, monkeypatch):
        """contract version A -> B -> back to A: same exact-replay
        semantics across contract identity changes."""
        import ashare_state.normalization.registry as registry_module

        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-croll",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        run_a = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-croll")
        monkeypatch.setattr(registry_module, "NORMALIZATION_CONTRACT_VERSION", "cr2.2-test-v9")
        run_b = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-croll")
        assert run_b.normalization_run_id != run_a.normalization_run_id
        monkeypatch.undo()
        replay_a = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-croll")
        assert replay_a.idempotent_replay is True
        assert replay_a.normalization_run_id == run_a.normalization_run_id
        assert _ledger_count(conn) == 2


@pytest.mark.integration
class TestFullMapperIdentity:
    def test_first16_collision_yields_distinct_run(self, conn, env_root, monkeypatch):
        """CR-2.2 P0-03 (audit 4.1): two mapper fingerprints sharing the
        first 16 hex chars (identical DISPLAY identity) yield DISTINCT
        run identities - the full SHA-256 enters the idempotency key."""
        import ashare_state.normalization.registry as registry_module

        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-fp16",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        run_a = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-fp16")
        real_fp = registry_module.MAPPER_CODE_FINGERPRINT
        colliding_fp = real_fp[:16] + "e" * 48  # same display prefix
        monkeypatch.setattr(registry_module, "MAPPER_CODE_FINGERPRINT", colliding_fp)
        run_b = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-fp16")
        assert run_b.normalization_run_id != run_a.normalization_run_id
        assert run_b.idempotent_replay is False
        assert _ledger_count(conn) == 2


def _rebind_manifest(env_root: dict[str, Path], conn, result, dataset: str, mutate) -> None:
    """Rebind-style tamper: edit the manifest JSON, rewrite the file AND
    update the ledger's normalized_manifest_hash to match - proving the
    seal consumption compares semantic fields, not just file bytes."""
    path = _manifest_path(
        env_root, dataset, result.raw_request_id, run_id=result.normalization_run_id
    )
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    data = json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False).encode("utf-8")
    path.write_bytes(data)
    conn.execute(
        "UPDATE meta_provider_normalization_run SET normalized_manifest_hash = ? "
        "WHERE normalization_run_id = ?",
        [hashlib.sha256(data).hexdigest(), result.normalization_run_id],
    )


@pytest.mark.integration
class TestFullSealConsumption:
    """CR-2.2 P0-03 (audit 20260901 section 4): the full provenance seal
    is CONSUMED on every replay - manifest == ledger == current contract
    + FULL mapper fingerprint, with schema/counts/quarantine seals all
    recomputed. Rebind tampering fails closed."""

    def _partial_run(self, conn, env_root, request_id: str):
        rows = [dict(_DAILY_BAR_ROWS[0]), dict(_DAILY_BAR_ROWS[1])]
        rows[1].pop("VOLUME")
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id=request_id,
            payload=rows,
            surface="daily_bar",
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id=request_id)
        assert result.status == "PARTIAL"
        return result

    def test_manifest_surface_field_tamper_rebind_blocks(self, conn, env_root):
        result = self._partial_run(conn, env_root, "req-seal-surface")
        _rebind_manifest(
            env_root,
            conn,
            result,
            "daily_bar",
            lambda doc: doc.__setitem__("normalization_surface", "index_daily"),
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-surface")

    def test_manifest_status_tamper_rebind_blocks(self, conn, env_root):
        result = self._partial_run(conn, env_root, "req-seal-status")
        _rebind_manifest(
            env_root,
            conn,
            result,
            "daily_bar",
            lambda doc: doc.__setitem__("status", "SUCCESS"),
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-status")

    def test_ledger_status_flip_without_manifest_blocks(self, conn, env_root):
        """A BLOCKED run whose ledger status is flipped to SUCCESS has
        no manifest - SUCCESS without a manifest binding is not
        replayable as healthy (typed manifest policy)."""
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-seal-flip",
            payload=["20260810", "bad"],
            params={"market": "SH"},
        )
        result = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-seal-flip"
        )
        assert result.status == "BLOCKED"
        assert result.manifest_uri is None
        conn.execute(
            "UPDATE meta_provider_normalization_run SET status = 'SUCCESS' "
            "WHERE normalization_run_id = ?",
            [result.normalization_run_id],
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(
                provider_dataset="trade_calendar", request_id="req-seal-flip"
            )

    def test_manifest_counts_tamper_rebind_blocks(self, conn, env_root):
        result = self._partial_run(conn, env_root, "req-seal-counts")
        _rebind_manifest(
            env_root,
            conn,
            result,
            "daily_bar",
            lambda doc: doc.__setitem__("input_count", 999),
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-counts")

    def test_manifest_quarantine_set_hash_tamper_rebind_blocks(self, conn, env_root):
        result = self._partial_run(conn, env_root, "req-seal-qtz")
        _rebind_manifest(
            env_root,
            conn,
            result,
            "daily_bar",
            lambda doc: doc.__setitem__("quarantine_set_hash", "0" * 64),
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-qtz")

    def test_ledger_quarantine_seal_tamper_blocks(self, conn, env_root):
        """The ledger's quarantine_set_hash is edited (manifest
        untouched): the three-way binding (DB recompute == ledger ==
        manifest) breaks on both sides."""
        result = self._partial_run(conn, env_root, "req-seal-lqtz")
        conn.execute(
            "UPDATE meta_provider_normalization_run SET quarantine_set_hash = ? "
            "WHERE normalization_run_id = ?",
            ["0" * 64, result.normalization_run_id],
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-lqtz")

    def test_ledger_mapper_code_hash_tamper_blocks(self, conn, env_root):
        """The ledger's mapper_code_hash no longer matches the CURRENT
        system-derived fingerprint (defense in depth on top of the exact
        key - catches ledger tampering explicitly)."""
        result = self._partial_run(conn, env_root, "req-seal-lmch")
        conn.execute(
            "UPDATE meta_provider_normalization_run SET mapper_code_hash = ? "
            "WHERE normalization_run_id = ?",
            ["0" * 64, result.normalization_run_id],
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-lmch")

    def test_manifest_mapper_code_hash_tamper_rebind_blocks(self, conn, env_root):
        result = self._partial_run(conn, env_root, "req-seal-mch")
        _rebind_manifest(
            env_root,
            conn,
            result,
            "daily_bar",
            lambda doc: doc.__setitem__("mapper_code_hash", "0" * 64),
        )
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-mch")

    def test_output_schema_hash_recompute_blocks(self, conn, env_root):
        """The physical parquet is swapped for a different-schema frame
        AND the manifest content_hash is rebound to match - the
        RECOMPUTED schema seal still fails closed."""
        import io

        import polars as pl

        result = self._partial_run(conn, env_root, "req-seal-schema")
        output_path = _output_path(
            env_root, "daily_bar", "req-seal-schema", run_id=result.normalization_run_id
        )
        frame = pl.read_parquet(output_path)
        swapped = frame.with_columns(pl.lit(1).alias("injected_col"))
        buf = io.BytesIO()
        swapped.write_parquet(buf)
        new_bytes = buf.getvalue()
        output_path.write_bytes(new_bytes)

        def mutate(doc: dict) -> None:
            for output in doc.get("outputs", []):
                if output.get("uri", "").endswith("main.parquet"):
                    output["content_hash"] = hashlib.sha256(new_bytes).hexdigest()

        _rebind_manifest(env_root, conn, result, "daily_bar", mutate)
        with pytest.raises(NormalizationRunnerError, match="DAMAGED"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-seal-schema")

    def test_blocked_conflict_run_replays_idempotently(self, conn, env_root):
        """The conflict INCIDENT run itself replays idempotently (one
        ledger row per distinct conflict identity) while remaining
        excluded from the baseline."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-conflict-replay",
            payload=_DAILY_BAR_ROWS,
            surface="daily_bar",
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-conflict-replay")
        meta = _meta_path(env_root, "daily_bar", "req-conflict-replay")
        doc = json.loads(meta.read_bytes())
        doc["request_params_hash"] = "f" * 64
        meta.write_bytes(json.dumps(doc, sort_keys=True).encode("utf-8"))
        first = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-conflict-replay"
        )
        assert first.status == "BLOCKED" and first.idempotent_replay is False
        second = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-conflict-replay"
        )
        assert second.status == "BLOCKED" and second.idempotent_replay is True
        assert second.normalization_run_id == first.normalization_run_id
        conflict_rows = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run "
            "WHERE raw_request_id = ? AND evidence_conflict = TRUE",
            ["req-conflict-replay"],
        ).fetchone()[0]
        assert int(conflict_rows) == 1
