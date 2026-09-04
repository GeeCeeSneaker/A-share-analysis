"""Focused formal Spike runner wiring tests (PR #8 review closure).

These tests use FakeTarget and a migrated temporary DuckDB only. They do not
load the native SDK, read credentials, or make network calls.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import duckdb
import pytest

from ashare_state import config as config_module
from ashare_state.config import AppConfig, Paths
from ashare_state.spike import (
    CaseCatalog,
    RunFailureReason,
    RunKind,
    RunLifecycleError,
    RunStatus,
    RunStore,
    SpikeRun,
)
from ashare_state.spike.target import FakeTarget
from ashare_state.storage.raw_anchor import RawAnchorError, lookup_raw_evidence_anchor

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = REPO_ROOT / "scripts" / "spike" / "spike_runner.py"


@pytest.fixture
def cli_module():
    spec = importlib.util.spec_from_file_location("spike_runner_formal_wiring", CLI_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


def _test_run(tmp_path: Path) -> tuple[SpikeRun, RunStore, CaseCatalog]:
    run = SpikeRun(
        spike_run_id=str(uuid.uuid4()),
        run_kind=RunKind.TRIAL,
        account_profile_id="TEST_PROFILE",
        as_of_date="20260903",
    )
    store = RunStore(tmp_path / "spike")
    store.initialize(run)
    catalog = CaseCatalog(store, run.spike_run_id)
    return run, store, catalog


def _patch_config(monkeypatch, db_path: Path) -> None:
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda _path=None: AppConfig(paths=Paths(duckdb_path=db_path)),
    )


@pytest.mark.integration
class TestFormalAnchorBoundary:
    def test_cli_context_uses_migrated_persistent_anchor_and_reopens(
        self, cli_module, monkeypatch, tmp_path: Path
    ):
        db_path = tmp_path / "formal" / "atlas.duckdb"
        _patch_config(monkeypatch, db_path)
        run, store, catalog = _test_run(tmp_path)

        with cli_module._formal_anchor_connection(REPO_ROOT) as conn:
            target = FakeTarget()
            ctx = cli_module._build_probe_context(run, store, catalog, target, conn)
            exchange = target.get_code_list_exchange("EXTRA_STOCK_A")
            evidence = ctx.evidence_from_exchange(exchange)
            request_id = evidence["request_id"]
            assert evidence["evidence_ref"].endswith(".meta.json")
            assert evidence["meta_hash"] == evidence["content_hash"]
            assert db_path.is_file()

        reopened = duckdb.connect(str(db_path), read_only=True)
        try:
            anchor = lookup_raw_evidence_anchor(
                reopened,
                provider="amazingdata",
                provider_dataset="code_list",
                request_id=request_id,
            )
        finally:
            reopened.close()
        assert anchor is not None
        assert anchor.evidence_hash == evidence["content_hash"]
        assert anchor.ingest_run_id == run.spike_run_id

    def test_formal_boundary_rejects_in_memory_anchor_db(
        self, cli_module, monkeypatch, tmp_path: Path
    ):
        _patch_config(monkeypatch, Path(":memory:"))
        with (
            pytest.raises(RunLifecycleError, match=":memory:"),
            cli_module._formal_anchor_connection(REPO_ROOT),
        ):
            pass


@pytest.mark.integration
class TestFormalDateAndLifecycle:
    def test_missing_production_date_is_refused_before_target_login(self, cli_module, monkeypatch):
        monkeypatch.setattr(
            cli_module,
            "_make_real_target",
            lambda: pytest.fail("missing-date validation must precede target login"),
        )
        monkeypatch.setattr(sys, "argv", ["spike_runner.py", "--production"])
        assert cli_module.main() == 2

    def test_resume_uses_frozen_run_date_and_mismatch_is_closed(
        self, cli_module, monkeypatch, tmp_path: Path
    ):
        run, store, catalog = _test_run(tmp_path)
        assert cli_module._resolve_resume_as_of_date(run, None) == 20260903
        with pytest.raises(RunLifecycleError, match="as-of date mismatch"):
            cli_module._resolve_resume_as_of_date(run, 20260904)
        assert store.load_run(run.spike_run_id, RunKind.TRIAL).status == RunStatus.RUNNING.value

        seen: dict[str, int] = {}

        def fake_phases(_ctx, _wanted, sample_date):
            seen["date"] = sample_date
            return {}

        monkeypatch.setattr(cli_module, "_run_phases", fake_phases)
        rc = cli_module._execute_run(
            run,
            store,
            catalog,
            FakeTarget(),
            conn=None,
            wanted=["b5"],
            sample_date=cli_module._resolve_resume_as_of_date(run, None),
            context_factory=lambda *_args: object(),
        )
        assert rc == 0
        assert seen["date"] == 20260903
        assert store.load_run(run.spike_run_id, RunKind.TRIAL).status == RunStatus.CLOSED.value

    def test_context_construction_failure_terminalizes_run(self, cli_module, tmp_path: Path):
        run, store, catalog = _test_run(tmp_path)

        def fail_factory(*_args):
            raise RuntimeError("injected context construction failure")

        rc = cli_module._execute_run(
            run,
            store,
            catalog,
            FakeTarget(),
            conn=object(),
            wanted=["b1"],
            sample_date=20260903,
            context_factory=fail_factory,
        )
        assert rc == 3
        failed = store.load_run(run.spike_run_id, RunKind.TRIAL)
        assert failed.status == RunStatus.FAILED.value
        assert failed.failure_reason == RunFailureReason.FRAMEWORK_ERROR.value
        assert failed.status not in (RunStatus.RUNNING.value, RunStatus.CLOSED.value)


@pytest.mark.integration
class TestAnchorFailureBoundary:
    def test_anchor_enrollment_failure_cannot_close_formal_run(
        self, cli_module, monkeypatch, tmp_path: Path
    ):
        run, store, catalog = _test_run(tmp_path)
        db_path = tmp_path / "formal" / "atlas.duckdb"
        _patch_config(monkeypatch, db_path)

        from ashare_state.storage import raw_anchor

        def fail_anchor(*_args, **_kwargs):
            raise RawAnchorError("injected anchor enrollment failure")

        monkeypatch.setattr(raw_anchor, "_enroll_anchor", fail_anchor)

        def one_exchange_phase(ctx, _wanted, _sample_date):
            exchange = ctx.target.get_code_list_exchange("EXTRA_STOCK_A")
            ctx.evidence_from_exchange(exchange)
            return {}

        monkeypatch.setattr(cli_module, "_run_phases", one_exchange_phase)
        with cli_module._formal_anchor_connection(REPO_ROOT) as conn:
            rc = cli_module._execute_run(
                run,
                store,
                catalog,
                FakeTarget(),
                conn,
                ["b1"],
                20260903,
            )
            assert rc == 3

        failed = store.load_run(run.spike_run_id, RunKind.TRIAL)
        assert failed.status == RunStatus.FAILED.value
        reopened = duckdb.connect(str(db_path), read_only=True)
        try:
            anchor = lookup_raw_evidence_anchor(
                reopened,
                provider="amazingdata",
                provider_dataset="code_list",
                request_id=next(
                    p.read_text(encoding="utf-8").split('"request_id": "')[1].split('"')[0]
                    for p in (store.raw_dir(run)).glob("provider=*/dataset=*/*.meta.json")
                ),
            )
        finally:
            reopened.close()
        assert anchor is None
        assert any(store.raw_dir(run).glob("provider=*/dataset=*/*.meta.json"))
