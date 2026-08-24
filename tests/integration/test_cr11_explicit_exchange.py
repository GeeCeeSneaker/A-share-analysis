"""CR-1.1 runtime closure tests (audit R4-A2.3 section 3).

The runtime chain is EXPLICIT end to end:
    target.*_exchange -> ProviderExchange -> RawWriter (Parquet + meta)
    -> RawWriteResult -> SpikeCase.evidence_ref/evidence_hash

A FAILED exchange is a FIRST-CLASS object: ProviderError.exchange carries
the error envelope; failure evidence is envelope-only and every case
still binds to hash-verified raw evidence. NO runtime path may
reverse-search provider.last_envelopes (diagnostic-only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import RunKind
from ashare_state.spike.probes import ProbeContext, ProbeExecutor
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.storage.raw_writer import RawWriter

_SHA = "b" * 40


def _ctx(tmp_path: Path, target=None) -> ProbeContext:
    run, store = new_run(
        run_kind=RunKind.DRY_RUN,
        spike_root=tmp_path / "spike",
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TRIAL_SIMULATION_FAKE",
        as_of_date="20260814",
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    return ProbeContext(run, store, catalog, target or FakeTarget())


class _BrokenTarget(FakeTarget):
    """Raises a REAL provider error carrying a first-class failed
    exchange (as call_exchange does for real SDK failures)."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    def get_history_stock_status_exchange(
        self, start_date: int, end_date: int, code_list: list[str]
    ) -> ProviderExchange:
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="history_stock_status",
            endpoint="InfoData.get_history_stock_status",
            requested_at="2026-08-24T00:00:00+00:00",
            received_at="2026-08-24T00:00:01+00:00",
            status="ERROR",
            error_class=type(self._error).__name__,
            account_profile_id="TRIAL_TEST",
        )
        self._error.exchange = ProviderExchange(envelope=env, payload=None)
        raise self._error


class TestExplicitExchangeSuccessChain:
    def test_exchange_persists_parquet_and_meta_with_case_lineage(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        exchange = ctx.target.get_history_stock_status_exchange(
            20220601, 20220630, ["600519.SH"]
        )
        meta = ctx.evidence_from_exchange(exchange)
        # evidence ref is run-relative and resolvable; CR-1.2: the case
        # evidence is the exchange META (bidirectional closure anchor)
        assert meta["evidence_ref"].startswith("dry_run/")
        assert meta["evidence_ref"].endswith(".meta.json")
        assert meta["content_hash"]
        artifact = ctx.store.spike_root / meta["evidence_ref"]
        assert artifact.is_file()
        import hashlib

        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == meta["content_hash"]
        # CR-1.2: payload artifacts listed separately, each with its hash
        assert meta["payload_artifacts"]
        payload = meta["payload_artifacts"][0]
        assert payload["uri"].endswith(".parquet")
        payload_path = ctx.store.spike_root / payload["uri"]
        assert payload_path.is_file()
        assert (
            hashlib.sha256(payload_path.read_bytes()).hexdigest() == payload["content_hash"]
        )
        assert meta["meta_ref"] == meta["evidence_ref"]
        assert meta["meta_hash"] == meta["content_hash"]
        # request_id lineage: the case binds the EXCHANGE's request id
        assert meta["request_id"] == exchange.request_id

    def test_same_endpoint_two_exchanges_two_artifacts(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        first = ctx.target.get_history_stock_status_exchange(20220601, 20220601, ["600519.SH"])
        second = ctx.target.get_history_stock_status_exchange(20220602, 20220602, ["600519.SH"])
        meta1 = ctx.evidence_from_exchange(first)
        meta2 = ctx.evidence_from_exchange(second)
        assert meta1["request_id"] != meta2["request_id"]
        assert meta1["evidence_ref"] != meta2["evidence_ref"]
        assert (ctx.store.spike_root / meta1["evidence_ref"]).is_file()
        assert (ctx.store.spike_root / meta2["evidence_ref"]).is_file()

    def test_executor_returns_payload_and_binds_evidence(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        executor = ProbeExecutor(ctx)
        payload, meta = executor.call(
            "BaseData.get_hist_code_list",
            lambda: ctx.target.get_hist_code_list_exchange(
                "EXTRA_STOCK_A_SH_SZ", 19900101, 20260814
            ),
            failure_case_type="security_master_with_delisted",
        )
        assert payload is not None
        assert meta["endpoint"] == "BaseData.get_hist_code_list"
        assert meta["status"] == "OK"
        assert meta["evidence_ref"]


class TestFailureExchangeFirstClass:
    def test_failed_exchange_becomes_envelope_only_case_evidence(self, tmp_path: Path):
        error = ProviderPermissionError("entitlement denied for dataset")
        ctx = _ctx(tmp_path, target=_BrokenTarget(error))
        executor = ProbeExecutor(ctx)
        payload, meta = executor.call(
            "InfoData.get_history_stock_status",
            lambda: ctx.target.get_history_stock_status_exchange(20220101, 20221231, ["835185.BJ"]),
            failure_case_type="historical_st_suspend",
        )
        assert payload is None
        # the case was structured (NOT_TESTABLE_PERMISSION), evidence intact
        assert len(ctx.catalog.cases) == 1
        case = ctx.catalog.cases[0]
        assert case.result.value == "NOT_TESTABLE_PERMISSION"
        assert case.evidence_hash
        evidence_path = ctx.store.spike_root / case.evidence_ref
        assert evidence_path.is_file()
        assert case.evidence_ref.endswith(".meta.json")  # envelope-only evidence
        import hashlib
        import json

        assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == case.evidence_hash
        doc = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert doc["status"] == "ERROR"
        assert doc["error_class"] == "ProviderPermissionError"
        # meta carries the failed exchange's request id (first-class lineage)
        assert meta["request_id"] == error.exchange.request_id

    def test_failure_without_exchange_uses_honest_synthetic_envelope(self, tmp_path: Path):
        error = ProviderPermissionError("gate rejection before SDK call")
        assert error.exchange is None
        ctx = _ctx(tmp_path)
        meta = ctx.failure_evidence(error, endpoint="X.y", dataset="ds")
        assert meta["status"] == "ERROR"
        assert meta["request_id"]
        evidence_path = ctx.store.spike_root / meta["evidence_ref"]
        assert evidence_path.is_file()

    def test_error_object_carries_failed_exchange_attribute(self):
        """ProviderError.exchange is the CR-1.1 first-class failure hook."""
        error = ProviderPermissionError("denied")
        assert error.exchange is None
        env = RawEnvelope(provider="amazingdata", provider_dataset="ds", endpoint="e")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        assert error.exchange.envelope is env


class TestProbeContract:
    def test_executor_rejects_non_exchange_return(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        executor = ProbeExecutor(ctx)
        with pytest.raises(TypeError, match="ProviderExchange"):
            executor.call(
                "BaseData.get_calendar",
                lambda: ctx.target.get_calendar(),  # payload, not exchange!
                failure_case_type="sdk_permission_cache_freshness",
            )

    def test_no_runtime_last_envelopes_lookup(self):
        """CR-1.1 audit section 3.2-B: correctness/lineage modules must
        never reverse-search provider.last_envelopes (AST-level check -
        docstrings may mention it, attribute ACCESS may not)."""
        import ast

        for source_file in (
            "src/ashare_state/spike/probes.py",
            "src/ashare_state/spike/golden_router.py",
            "src/ashare_state/spike/runner.py",
        ):
            tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
            offenders = [
                node.attr
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr == "last_envelopes"
            ]
            assert not offenders, (
                f"{source_file} accesses provider.last_envelopes - the "
                "runtime must consume explicit ProviderExchange objects only"
            )

    def test_raw_writer_write_is_the_unified_entry(self, tmp_path: Path):
        """The runtime evidence pipeline writes via write(exchange)."""
        ctx = _ctx(tmp_path)
        assert isinstance(ctx.raw_writer, RawWriter)
        exchange = ctx.target.get_calendar_exchange()
        result = ctx.raw_writer.write(exchange)
        assert result.request_id == exchange.request_id
        assert result.evidence_hash
