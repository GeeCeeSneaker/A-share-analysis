"""CR-2 Provider-Normalized + Quarantine contract tests (audit 20260831).

Covers the required adversarial matrix (work requirement section 7):

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

Plus the structural guard: every provider (dataset, endpoint) surface
is explicitly classified in the static registry.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pytest

from ashare_state.normalization import (
    DATASET_NORMALIZATION_REGISTRY,
    NORMALIZATION_CONTRACT_VERSION,
    NormalizationRunner,
    NormalizationRunnerError,
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
) -> None:
    """Persist raw evidence exactly the way the production pipeline
    does (RawWriter.write_success / write_failure)."""
    writer = RawWriter(roots["raw"])
    env = _FakeEnvelope(
        provider_dataset=dataset,
        endpoint=endpoint,
        request_id=request_id,
        request_params=params or {},
        status=status,
        row_count=len(payload) if hasattr(payload, "__len__") else 1,
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
        code_commit="test-commit",
    )


def _read_output(roots: dict[str, Path], dataset: str, request_id: str, output: str = "main"):
    """Read back one normalized output table (canonical layout)."""
    import polars as pl

    uri = (
        f"provider=amazingdata/dataset={dataset}/"
        f"raw_request={request_id}/"
        f"contract={NORMALIZATION_CONTRACT_VERSION}/{output}.parquet"
    )
    return pl.read_parquet(roots["normalized"] / uri)


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


# ------------------------------------------------------- structural guards


@pytest.mark.integration
class TestRegistryStructuralGuard:
    def test_every_provider_surface_is_explicitly_classified(self):
        """AST-extract every (dataset, endpoint) pair the provider
        declares and require an explicit registry entry - a new surface
        without a classification decision fails the guard."""
        src = PROVIDER_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        pairs: set[tuple[str, str]] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "_call_or_exchange"):
                continue
            args = [
                a for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ]
            if len(args) >= 2:
                pairs.add((args[1].value, args[0].value))
        assert pairs, "no provider surfaces found - guard is broken"
        registry_pairs = {
            (s.provider_dataset, s.endpoint) for s in DATASET_NORMALIZATION_REGISTRY.values()
        }
        assert registry_pairs == pairs, (
            f"unclassified={sorted(pairs - registry_pairs)}, stale={sorted(registry_pairs - pairs)}"
        )

    def test_supported_specs_have_mappers(self):
        for spec in DATASET_NORMALIZATION_REGISTRY.values():
            if str(spec.support) == "SUPPORTED_NORMALIZATION":
                assert spec.map_row is not None or spec.map_payload is not None, spec

    def test_runner_has_no_provider_calls(self):
        """P0-01: the normalization package never touches the provider
        SDK - no provider-module import, no SDK symbol."""
        pkg_root = REPO_ROOT / "src" / "ashare_state" / "normalization"
        for path in pkg_root.rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            assert "from ashare_state.providers.amazingdata.provider import" not in src, path.name
            assert "AmazingDataProvider" not in src, path.name
            assert "import AmazingData" not in src, path.name


# ------------------------------------------------------------- core P0-01


@pytest.mark.integration
class TestRawEvidenceSoleInput:
    def test_normalizes_persisted_raw_evidence(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-ok-1",
            payload=_DAILY_BAR_ROWS,
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-ok-1")
        assert result.status == "SUCCESS"
        assert result.input_count == 2
        assert result.normalized_count == 2
        assert result.quarantined_count == 0
        # first-class persisted output (P0-03)
        assert result.manifest_uri is not None
        manifest_path = env_root["normalized"] / result.manifest_uri
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["raw_request_id"] == "req-ok-1"
        assert manifest["normalization_contract_version"] == NORMALIZATION_CONTRACT_VERSION
        assert manifest["outputs"][0]["row_count"] == 2
        # the ledger row binds the exact raw evidence
        row = conn.execute(
            "SELECT raw_evidence_uri, raw_evidence_hash, status FROM "
            "meta_provider_normalization_run WHERE normalization_run_id = ?",
            [result.normalization_run_id],
        ).fetchone()
        assert str(row[0]).endswith("req-ok-1.meta.json")
        assert str(row[1]) == manifest["raw_evidence_hash"]
        assert str(row[2]) == "SUCCESS"

    def test_missing_raw_meta_is_caller_misuse(self, conn, env_root):
        with pytest.raises(NormalizationRunnerError, match="no raw meta"):
            _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="nope")

    def test_raw_meta_hash_tamper_blocks(self, conn, env_root):
        """Corrupt the meta JSON so closure verification fails."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-tamper-meta",
            payload=_DAILY_BAR_ROWS,
        )
        meta = (
            env_root["raw"]
            / "provider=amazingdata"
            / "dataset=daily_bar"
            / "req-tamper-meta.meta.json"
        )
        doc = json.loads(meta.read_text(encoding="utf-8"))
        doc["tables"][0]["content_hash"] = "f" * 64  # lie about the payload hash
        meta.write_text(json.dumps(doc), encoding="utf-8")
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-tamper-meta"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "RAW_EVIDENCE_INVALID"
        assert "closure" in (result.error_message or "")

    def test_raw_payload_bytes_tamper_blocks(self, conn, env_root):
        """Replace the payload parquet bytes on disk (meta untouched)."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-tamper-bytes",
            payload=_DAILY_BAR_ROWS,
        )
        payload = (
            env_root["raw"]
            / "provider=amazingdata"
            / "dataset=daily_bar"
            / "req-tamper-bytes.parquet"
        )
        payload.write_bytes(payload.read_bytes() + b"\x00tamper")
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-tamper-bytes"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "RAW_EVIDENCE_INVALID"

    def test_source_exchange_failure_is_not_a_mapping_quarantine(self, conn, env_root):
        """A FAILED exchange (ERROR meta, no payload) is BLOCKED with
        SOURCE_EXCHANGE_FAILED - and produces ZERO quarantine rows."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-failed-exchange",
            payload=None,
            status="ERROR",
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-failed-exchange"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "SOURCE_EXCHANGE_FAILED"
        quarantines = conn.execute(
            "SELECT count(*) FROM meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-failed-exchange"],
        ).fetchone()
        assert int(quarantines[0]) == 0


# -------------------------------------------------- quarantine semantics


def _run_with_bad_row(conn, env_root, bad_row: dict[str, Any], request_id: str):
    rows = [dict(_DAILY_BAR_ROWS[0]), bad_row]
    _persist_raw(
        env_root,
        dataset="daily_bar",
        endpoint="MarketData.query_kline",
        request_id=request_id,
        payload=rows,
    )
    return _runner(conn, env_root).run(provider_dataset="daily_bar", request_id=request_id)


@pytest.mark.integration
class TestNoSentinelNoSilentDrop:
    def test_required_field_missing_quarantines_without_sentinel(self, conn, env_root):
        bad = dict(_DAILY_BAR_ROWS[1])
        del bad["CLOSE_PRICE"]
        result = _run_with_bad_row(conn, env_root, bad, "req-missing-close")
        assert result.status == "PARTIAL"
        assert result.input_count == 2
        assert result.normalized_count == 1
        assert result.quarantined_count == 1
        q = conn.execute(
            "SELECT raw_row_ordinal, error_class, error_message, error_context_json "
            "FROM meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-missing-close"],
        ).fetchone()
        assert int(q[0]) == 1  # deterministic locator: second row
        assert str(q[1]) == "MAPPING_VALIDATION_FAILED"
        assert "CLOSE_PRICE" in str(q[2])
        # the normalized artifact contains NO sentinel for the bad row
        run_row = conn.execute(
            "SELECT normalized_manifest_uri FROM meta_provider_normalization_run "
            "WHERE normalization_run_id = ?",
            [result.normalization_run_id],
        ).fetchone()
        manifest = json.loads(
            (env_root["normalized"] / str(run_row[0])).read_text(encoding="utf-8")
        )
        out_uri = manifest["outputs"][0]["uri"]
        import polars as pl

        frame = pl.read_parquet(env_root["normalized"] / out_uri)
        assert frame.height == 1
        assert str(frame["provider_symbol"][0]) == "600000.SH"

    def test_unparsable_date_quarantines_no_epoch_sentinel(self, conn, env_root):
        good = dict(_DAILY_BAR_ROWS[0])
        good["KLINE_TIME"] = "20260814"  # homogeneous string column
        bad = dict(_DAILY_BAR_ROWS[1])
        bad["KLINE_TIME"] = "not-a-date"
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-bad-date",
            payload=[good, bad],
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-bad-date"
        )
        assert result.status == "PARTIAL"  # row quarantined; good rows retained
        assert result.input_count == 2
        assert result.normalized_count == 1
        assert result.quarantined_count == 1
        q = conn.execute(
            "SELECT error_message FROM meta_provider_quarantine WHERE raw_request_id = ?",
            ["req-bad-date"],
        ).fetchone()
        assert "KLINE_TIME" in str(q[0])

    def test_unparsable_numeric_quarantines_no_zero_sentinel(self, conn, env_root):
        bad = dict(_DAILY_BAR_ROWS[1])
        bad["CLOSE_PRICE"] = "garbage"
        result = _run_with_bad_row(conn, env_root, bad, "req-bad-numeric")
        assert result.status == "PARTIAL"
        assert result.quarantined_count == 1

    def test_legal_zero_not_treated_as_missing(self, conn, env_root):
        """A legal 0.0 close must normalize (first_present semantics),
        never be mistaken for a missing value."""
        rows = [dict(_DAILY_BAR_ROWS[0])]
        rows[0]["CLOSE_PRICE"] = 0.0
        rows[0]["OPEN_PRICE"] = 0.0
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-zero",
            payload=rows,
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-zero")
        assert result.status == "SUCCESS"
        assert result.normalized_count == 1
        frame = _read_output(env_root, "daily_bar", "req-zero")
        assert float(frame["close"][0]) == 0.0
        assert float(frame["open"][0]) == 0.0

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
            request_id="req-multi",
            payload={
                "kline": _DAILY_BAR_ROWS,
                "other": [{"X": 1}],
            },
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-multi")
        assert result.status == "BLOCKED"
        assert result.error_class == "PAYLOAD_SHAPE_UNSUPPORTED"
        assert "first table" in (result.error_message or "")


@pytest.mark.integration
class TestQuarantineEvidenceQuality:
    def test_quarantine_locates_exact_raw_row(self, conn, env_root):
        bad = dict(_DAILY_BAR_ROWS[1])
        bad["SECURITY_CODE"] = ""  # required field missing
        _run_with_bad_row(conn, env_root, bad, "req-locator")
        q = conn.execute(
            "SELECT raw_request_id, raw_table_name, raw_row_ordinal, source_key, "
            "raw_evidence_uri, mapper_identity FROM meta_provider_quarantine "
            "WHERE raw_request_id = ?",
            ["req-locator"],
        ).fetchone()
        assert str(q[0]) == "req-locator"
        assert q[1] is None  # single-table payload
        assert int(q[2]) == 1
        assert str(q[3]) == "" or q[3] is None  # no natural key on the bad row
        assert str(q[4]).endswith("req-locator.meta.json")
        assert str(q[5]).startswith("daily_bar/MarketData.query_kline@")

    def test_quarantine_never_leaks_secrets(self, conn, env_root):
        """The mapper error context may echo the offending raw row; the
        quarantine record must scrub credential-shaped keys."""
        from ashare_state.normalization import registry as registry_module
        from ashare_state.providers.errors import MappingValidationError

        secret_row = {
            "SECURITY_CODE": "600000",
            "MARKET_CODE": "1",
            "KLINE_TIME": 20260814,
            "KLINE_TYPE": "DAY",
            "OPEN_PRICE": "1",
            "HIGH_PRICE": "1",
            "LOW_PRICE": "1",
            "CLOSE_PRICE": "1",
            "VOLUME": "1",
            "AMOUNT": "1",
            "password": "hunter2",
            "api_token": "abc",
        }

        def evil_mapper(row: dict[str, Any]) -> dict[str, Any]:
            raise MappingValidationError("boom", context={"row": secret_row, "token": "leak-me"})

        spec = registry_module.DatasetNormalizationSpec(
            provider_dataset="daily_bar",
            endpoint="MarketData.query_kline",
            support=registry_module.SurfaceSupport.SUPPORTED_NORMALIZATION,
            mapper_version="evil-v1",
            quarantine_scope=registry_module.QuarantineScope.ROW,
            allow_partial=True,
            map_row=evil_mapper,
        )
        registry_module.DATASET_NORMALIZATION_REGISTRY[("daily_bar", "MarketData.query_kline")] = (
            spec
        )
        try:
            _persist_raw(
                env_root,
                dataset="daily_bar",
                endpoint="MarketData.query_kline",
                request_id="req-secret",
                payload=[_DAILY_BAR_ROWS[0]],
            )
            result = _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-secret"
            )
            assert result.quarantined_count == 1
            q = conn.execute(
                "SELECT error_context_json, error_message FROM meta_provider_quarantine "
                "WHERE raw_request_id = ?",
                ["req-secret"],
            ).fetchone()
            blob = str(q[0]) + str(q[1])
            assert "hunter2" not in blob
            assert "leak-me" not in blob
            assert "[REDACTED]" in str(q[0])
        finally:
            registry_module.DATASET_NORMALIZATION_REGISTRY[
                ("daily_bar", "MarketData.query_kline")
            ] = _original_daily_bar_spec()

    def test_mapper_internal_exception_is_recorded_not_swallowed(self, conn, env_root):
        """A non-MappingValidationError mapper exception becomes a
        quarantine record with NORMALIZATION_INTERNAL_ERROR and an
        exact row locator - never a silent drop."""
        from ashare_state.normalization import registry as registry_module

        def boom_mapper(row: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("mapper exploded")

        spec = registry_module.DatasetNormalizationSpec(
            provider_dataset="daily_bar",
            endpoint="MarketData.query_kline",
            support=registry_module.SurfaceSupport.SUPPORTED_NORMALIZATION,
            mapper_version="boom-v1",
            quarantine_scope=registry_module.QuarantineScope.ROW,
            allow_partial=True,
            map_row=boom_mapper,
        )
        registry_module.DATASET_NORMALIZATION_REGISTRY[("daily_bar", "MarketData.query_kline")] = (
            spec
        )
        try:
            _persist_raw(
                env_root,
                dataset="daily_bar",
                endpoint="MarketData.query_kline",
                request_id="req-boom",
                payload=_DAILY_BAR_ROWS,
            )
            result = _runner(conn, env_root).run(
                provider_dataset="daily_bar", request_id="req-boom"
            )
            assert result.status == "BLOCKED"  # internal errors block
            assert result.quarantined_count == 2
            q = conn.execute(
                "SELECT raw_row_ordinal, error_class FROM meta_provider_quarantine "
                "WHERE raw_request_id = ? ORDER BY raw_row_ordinal",
                ["req-boom"],
            ).fetchall()
            assert [int(r[0]) for r in q] == [0, 1]
            assert {str(r[1]) for r in q} == {"NORMALIZATION_INTERNAL_ERROR"}
        finally:
            registry_module.DATASET_NORMALIZATION_REGISTRY[
                ("daily_bar", "MarketData.query_kline")
            ] = _original_daily_bar_spec()


def _original_daily_bar_spec():
    from ashare_state.normalization import registry as registry_module
    from ashare_state.providers.amazingdata.mapper import map_daily_bar_row

    def map_row(row: dict[str, Any]) -> dict[str, Any]:
        return {"main": map_daily_bar_row(row)}

    return registry_module.DatasetNormalizationSpec(
        provider_dataset="daily_bar",
        endpoint="MarketData.query_kline",
        support=registry_module.SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="daily-bar-mapper-v1",
        quarantine_scope=registry_module.QuarantineScope.ROW,
        allow_partial=True,
        map_row=map_row,
    )


# -------------------------------------------------- idempotency / replay


@pytest.mark.integration
class TestDeterministicReplay:
    def _prepared(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-replay",
            payload=_DAILY_BAR_ROWS,
        )
        runner = _runner(conn, env_root)
        first = runner.run(provider_dataset="daily_bar", request_id="req-replay")
        assert first.status == "SUCCESS"
        return runner, first

    def test_rerun_is_idempotent(self, conn, env_root):
        runner, first = self._prepared(conn, env_root)
        second = runner.run(provider_dataset="daily_bar", request_id="req-replay")
        assert second.idempotent_replay is True
        assert second.normalization_run_id == first.normalization_run_id
        assert second.manifest_hash == first.manifest_hash
        runs = conn.execute(
            "SELECT count(*) FROM meta_provider_normalization_run WHERE raw_request_id = ?",
            ["req-replay"],
        ).fetchone()
        assert int(runs[0]) == 1  # no duplicate ledger rows

    def test_deterministic_semantic_output(self, conn, env_root):
        """Same raw bytes + contract: two SEPARATE roots produce the
        same semantic hash (order / formatting independent)."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-det",
            payload=list(reversed(_DAILY_BAR_ROWS)),  # different input ORDER
        )
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-det-2",
            payload=_DAILY_BAR_ROWS,
        )
        runner = _runner(conn, env_root)
        r1 = runner.run(provider_dataset="daily_bar", request_id="req-det")
        r2 = runner.run(provider_dataset="daily_bar", request_id="req-det-2")
        m1 = json.loads((env_root["normalized"] / r1.manifest_uri).read_text(encoding="utf-8"))
        m2 = json.loads((env_root["normalized"] / r2.manifest_uri).read_text(encoding="utf-8"))
        assert m1["semantic_hash"] == m2["semantic_hash"]  # row order irrelevant

    def test_conflicting_raw_evidence_bytes_block(self, conn, env_root):
        """Same request id persisted once, then the meta file is
        REWRITTEN with different bytes (simulating an externally
        replaced evidence) -> BLOCK."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-conflict",
            payload=_DAILY_BAR_ROWS,
        )
        _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-conflict")
        # externally rewrite the meta with different content
        meta = (
            env_root["raw"]
            / "provider=amazingdata"
            / "dataset=daily_bar"
            / "req-conflict.meta.json"
        )
        doc = json.loads(meta.read_text(encoding="utf-8"))
        doc["duration_ms"] = 999.0  # any byte-level change
        meta.write_text(json.dumps(doc), encoding="utf-8")
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-conflict"
        )
        assert result.status == "BLOCKED"
        assert result.error_class == "RAW_EVIDENCE_INVALID"
        assert "conflicting raw evidence" in (result.error_message or "")


# ------------------------------------------------------- URI confinement


@pytest.mark.integration
class TestLogicalURIConfinement:
    def test_normalized_artifact_uris_are_canonical(self, conn, env_root):
        """Generated URIs are canonical logical URIs (relative, forward
        slashes, no drive/alias) and resolve through the frozen helper."""
        from ashare_state.storage.paths import validate_logical_uri

        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-uri",
            payload=_DAILY_BAR_ROWS,
        )
        result = _runner(conn, env_root).run(provider_dataset="daily_bar", request_id="req-uri")
        assert result.manifest_uri
        manifest = json.loads(
            (env_root["normalized"] / result.manifest_uri).read_text(encoding="utf-8")
        )
        uris = [result.manifest_uri] + [o["uri"] for o in manifest["outputs"]]
        for uri in uris:
            validate_logical_uri(uri)  # raises on ../ absolute drive alias
            assert "\\" not in uri
            assert not uri.startswith("/")

    @pytest.mark.parametrize("evil", ["../escape", "/abs", "C:/drive", "a/b", "a\\b", ".."])
    def test_evil_request_id_fails_closed(self, conn, env_root, evil):
        """A request_id that would escape the normalized root is
        rejected by the runner BEFORE any path construction."""
        runner = _runner(conn, env_root)
        with pytest.raises(NormalizationRunnerError, match="unsafe request_id"):
            runner.run(provider_dataset="daily_bar", request_id=evil)


# ------------------------------------------------- provider-faithful DTOs


@pytest.mark.integration
class TestProviderFaithfulOutput:
    def test_daily_bar_preserves_provider_units_and_literals(self, conn, env_root):
        """volume/amount keep the provider's raw numeric values; the
        provider symbol keeps the provider suffix format."""
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-faithful",
            payload=_DAILY_BAR_ROWS,
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-faithful"
        )
        assert result.status == "SUCCESS"
        frame = _read_output(env_root, "daily_bar", "req-faithful")
        # canonical sort orders 000001.SZ first - locate by symbol
        symbols = list(frame["provider_symbol"])
        assert set(symbols) == {"600000.SH", "000001.SZ"}  # provider format
        row_600000 = frame.filter(frame["provider_symbol"] == "600000.SH")
        assert float(row_600000["volume"][0]) == 12345.0  # provider unit, unchanged
        assert row_600000["kline_type"][0] == "DAY"  # provider literal

    def test_industry_member_keeps_unverified_marker(self, conn, env_root):
        """taxonomy_owner stays GALAXY_UNVERIFIED - CR-2 does not
        canonicalize unverified provider semantics."""
        rows = [
            {
                "SECURITY_CODE": "600000",
                "INDUSTRY_CODE": "310000",
                "INDUSTRY_LEVEL": "1",
                "CURRENT_SIGN": "1",
            }
        ]
        _persist_raw(
            env_root,
            dataset="industry_taxonomy",
            endpoint="InfoData.get_industry_constituent",
            request_id="req-industry",
            payload=rows,
        )
        result = _runner(conn, env_root).run(
            provider_dataset="industry_taxonomy", request_id="req-industry"
        )
        assert result.status == "SUCCESS"
        frame = _read_output(env_root, "industry_taxonomy", "req-industry")
        assert frame["taxonomy_owner"][0] == "GALAXY_UNVERIFIED"

    def test_status_routes_to_three_outputs(self, conn, env_root):
        """history_stock_status produces THREE provider-faithful output
        tables (status mirror + limit-price + CA-flag projections)."""
        rows = [
            {
                "MARKET_CODE": "1",
                "SECURITY_CODE": "600000",
                "TRADE_DATE": "20260814",
                "PRECLOSE": "10.0",
                "HIGH_LIMITED": "11.0",
                "LOW_LIMITED": "9.0",
                "IS_ST_SEC": "0",
                "IS_WD_SEC": "1",
                "IS_XR_SEC": "0",
            }
        ]
        _persist_raw(
            env_root,
            dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            request_id="req-status",
            payload=rows,
        )
        result = _runner(conn, env_root).run(
            provider_dataset="history_stock_status", request_id="req-status"
        )
        assert result.status == "SUCCESS"
        manifest = json.loads(
            (env_root["normalized"] / result.manifest_uri).read_text(encoding="utf-8")
        )
        output_names = {o["output_name"] for o in manifest["outputs"]}
        assert output_names == {"security_status", "limit_price", "corporate_action"}
        import polars as pl

        limit = pl.read_parquet(
            env_root["normalized"]
            / next(o["uri"] for o in manifest["outputs"] if o["output_name"] == "limit_price")
        )
        assert float(limit["up_limit"][0]) == 11.0
        ca = pl.read_parquet(
            env_root["normalized"]
            / next(o["uri"] for o in manifest["outputs"] if o["output_name"] == "corporate_action")
        )
        assert bool(ca["is_ex_dividend"][0]) is True  # IS_WD_SEC -> ex-dividend flag


# ------------------------------------------------------------ status machine


@pytest.mark.integration
class TestStatusMachine:
    def test_all_good_rows_success(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="daily_bar",
            endpoint="MarketData.query_kline",
            request_id="req-status-ok",
            payload=_DAILY_BAR_ROWS,
        )
        result = _runner(conn, env_root).run(
            provider_dataset="daily_bar", request_id="req-status-ok"
        )
        assert result.status == "SUCCESS"
        assert result.quarantined_count == 0

    def test_row_quarantine_partial_when_allowed(self, conn, env_root):
        bad = dict(_DAILY_BAR_ROWS[1])
        bad["CLOSE_PRICE"] = "x"
        result = _run_with_bad_row(conn, env_root, bad, "req-status-partial")
        assert result.status == "PARTIAL"

    def test_whole_payload_quarantine_blocks(self, conn, env_root):
        _persist_raw(
            env_root,
            dataset="trade_calendar",
            endpoint="BaseData.get_calendar",
            request_id="req-status-blocked",
            payload=["bad"],
            params={"market": "SH"},
        )
        result = _runner(conn, env_root).run(
            provider_dataset="trade_calendar", request_id="req-status-blocked"
        )
        assert result.status == "BLOCKED"
