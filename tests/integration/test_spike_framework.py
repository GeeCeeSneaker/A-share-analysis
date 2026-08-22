"""Spike framework contract tests (Round-2 audit section 33, Spike group)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ashare_state.spike import (
    CaseCatalog,
    CaseResult,
    RunKind,
    RunStore,
    compute_verdict,
    new_run,
    run_dry_run,
)
from ashare_state.spike.model import SpikeCase


@pytest.fixture
def spike_root(tmp_path: Path) -> Path:
    return tmp_path / "spike"


class TestSpikeRunnerImports:
    def test_cli_entry_importable(self):
        """R2-P0-01 regression: the CLI entry must import cleanly."""
        import importlib.util

        entry = Path("scripts/spike/spike_runner.py")
        assert entry.is_file()
        spec = importlib.util.spec_from_file_location("spike_runner_cli", entry)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        assert hasattr(module, "main")

    def test_framework_imports(self):
        from ashare_state.spike import probes, runner, target, validators  # noqa: F401


class TestDryRunAllPhases:
    def test_dry_run_produces_all_phase_outputs(self, spike_root: Path):
        out = run_dry_run(spike_root, sample_date=20260814)
        phases = out["phases"]
        for phase in ("b2", "b3", "b4", "b5", "b6", "b7"):
            assert phase in phases, phase
        run_dir = Path(out["run_dir"])
        assert (run_dir / "spike_run.json").is_file()
        assert (run_dir / "cases" / "spike_case_catalog.jsonl").is_file()
        assert any((run_dir / "raw").glob("*.json"))
        # fake target: dry-run verdict is intentionally incomplete on history
        catalog_json = json.loads((run_dir / "spike_run.json").read_text(encoding="utf-8"))
        assert catalog_json["run_kind"] == "DRY_RUN"
        assert catalog_json["status"] == "CLOSED"


class TestDryRunNeverCountsForVerdict:
    def test_dry_run_verdict_refused(self, spike_root: Path):
        out = run_dry_run(spike_root)
        store = RunStore(spike_root)
        run = store.load_run(out["spike_run_id"], RunKind.DRY_RUN)
        with pytest.raises(Exception, match="PRODUCTION"):
            compute_verdict(store, run)

    def test_open_run_verdict_refused(self, spike_root: Path):
        run, store = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        with pytest.raises(Exception, match="close it before the verdict"):
            compute_verdict(store, run)


class TestVerdictScopedToOneRun:
    def test_verdict_aggregates_only_its_own_run(self, spike_root: Path):
        """Two closed production runs: a FAIL in run A never pollutes run B."""
        store = RunStore(spike_root)

        # run A: a single FAILING core case
        run_a, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog_a = CaseCatalog(store, run_a.spike_run_id)
        catalog_a.add(
            _case(
                run_a.spike_run_id,
                "A-SECMASTER-0001",
                "security_master_with_delisted",
                CaseResult.VALIDATED_FAIL,
            )
        )
        catalog_a.flush(store.run_dir(run_a))
        store.save_run(_closed(run_a))

        # run B: same capability PASSING (fresh evidence, same catalog file name)
        run_b, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog_b = CaseCatalog(store, run_b.spike_run_id)
        catalog_b.add(
            _case(
                run_b.spike_run_id,
                "B-SECMASTER-0001",
                "security_master_with_delisted",
                CaseResult.VALIDATED_PASS,
            )
        )
        catalog_b.flush(store.run_dir(run_b))
        store.save_run(_closed(run_b))

        verdict_b = compute_verdict(store, store.load_run(run_b.spike_run_id, RunKind.PRODUCTION))
        # run B's capability is PASS; the old FAIL in run A is invisible
        assert verdict_b.capability_status["security_master_with_delisted"] != "FAILED"

    def test_old_fail_not_counted_after_new_pass(self, spike_root: Path):
        """R2 section 5.3: historical FAIL must not pollute the new run."""
        store = RunStore(spike_root)
        run, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        catalog.add(_case(run.spike_run_id, "F-1", "daily_bar_units", CaseResult.VALIDATED_PASS))
        catalog.flush(store.run_dir(run))
        store.save_run(_closed(run))
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.capability_status["daily_bar_units"] == "PASS"


class TestCaseIdUniqueness:
    def test_duplicate_case_id_rejected(self, spike_root: Path):
        from ashare_state.spike.catalog import DuplicateCaseError

        run, store = new_run(run_kind=RunKind.TRIAL, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        catalog.add(
            _case(
                run.spike_run_id,
                "B3-ST-600000.SH-20260814",
                "historical_st_suspend",
                CaseResult.VALIDATED_PASS,
            )
        )
        with pytest.raises(DuplicateCaseError):
            catalog.add(
                _case(
                    run.spike_run_id,
                    "B3-ST-600000.SH-20260814",
                    "historical_st_suspend",
                    CaseResult.VALIDATED_FAIL,
                )
            )

    def test_semantic_case_ids_coexist(self, spike_root: Path):
        """R2 section 7: same endpoint, different semantics -> distinct ids."""
        run, store = new_run(run_kind=RunKind.TRIAL, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        catalog.add(
            _case(
                run.spike_run_id,
                "B3-ST-600000.SH-20260814",
                "historical_st_suspend",
                CaseResult.VALIDATED_PASS,
            )
        )
        catalog.add(
            _case(
                run.spike_run_id,
                "B3-LIMIT-600000.SH-20260814",
                "limit_price_and_no_limit_days",
                CaseResult.VALIDATED_PASS,
            )
        )


class TestUnvalidatedNeverPasses:
    def test_observed_is_not_pass(self):
        from ashare_state.spike.model import core_gate_satisfied

        assert not core_gate_satisfied(CaseResult.OBSERVED)
        assert not core_gate_satisfied(CaseResult.MISSING)
        assert not core_gate_satisfied(CaseResult.VALIDATED_FAIL)
        assert not core_gate_satisfied(CaseResult.NOT_TESTABLE_PERMISSION)
        assert core_gate_satisfied(CaseResult.VALIDATED_PASS)
        assert not core_gate_satisfied(CaseResult.DIFF_EXPLAINED)  # needs validator equivalence
        assert core_gate_satisfied(CaseResult.DIFF_EXPLAINED, equivalent_pass=True)

    def test_observed_only_run_is_incomplete(self, spike_root: Path):
        store = RunStore(spike_root)
        run, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        catalog.add(_case(run.spike_run_id, "O-1", "sw_taxonomy", CaseResult.OBSERVED))
        catalog.flush(store.run_dir(run))
        store.save_run(_closed(run))
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"


class TestCoreCoverageIncomplete:
    def test_missing_core_capability_yields_spike_incomplete(self, spike_root: Path):
        """Only ONE core capability has cases -> verdict SPIKE_INCOMPLETE,
        never NO_GO (R2 section 8)."""
        store = RunStore(spike_root)
        run, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        catalog.add(
            _case(
                run.spike_run_id, "P-1", "security_master_with_delisted", CaseResult.VALIDATED_PASS
            )
        )
        catalog.flush(store.run_dir(run))
        store.save_run(_closed(run))
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"
        assert len(verdict.missing_core) >= 7

    def test_full_core_pass_yields_go_degraded_without_optional(self, spike_root: Path):
        from ashare_state.spike.capabilities import CORE_CAPABILITIES

        store = RunStore(spike_root)
        run, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        for i, cap in enumerate(CORE_CAPABILITIES):
            for case_type in cap.required_case_types:
                catalog.add(
                    _case(
                        run.spike_run_id, f"C{i}-{case_type}", case_type, CaseResult.VALIDATED_PASS
                    )
                )
        catalog.flush(store.run_dir(run))
        store.save_run(_closed(run))
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "GO_DEGRADED"  # optional capabilities missing

    def test_failed_core_with_full_coverage_is_no_go(self, spike_root: Path):
        from ashare_state.spike.capabilities import CORE_CAPABILITIES

        store = RunStore(spike_root)
        run, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        for i, cap in enumerate(CORE_CAPABILITIES):
            for j, case_type in enumerate(cap.required_case_types):
                result = (
                    CaseResult.VALIDATED_FAIL
                    if cap.capability_id == "daily_bar_units"
                    else CaseResult.VALIDATED_PASS
                )
                catalog.add(_case(run.spike_run_id, f"C{i}{j}-{case_type}", case_type, result))
        catalog.flush(store.run_dir(run))
        store.save_run(_closed(run))
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "NO_GO"
        assert "daily_bar_units" in verdict.failed_core


class TestEvidenceIsolation:
    def test_trial_and_production_directories_disjoint(self, spike_root: Path):
        run_t, store = new_run(run_kind=RunKind.TRIAL, spike_root=spike_root)
        run_p, _ = new_run(run_kind=RunKind.PRODUCTION, spike_root=spike_root)
        dir_t = store.run_dir(run_t)
        dir_p = store.run_dir(run_p)
        assert dir_t != dir_p
        assert "trial" in str(dir_t)
        assert "production" in str(dir_p)

    def test_evidence_files_are_immutable(self, spike_root: Path):
        from ashare_state.spike.run_store import EvidenceImmutableError

        run, store = new_run(run_kind=RunKind.TRIAL, spike_root=spike_root)
        store.write_evidence(
            run, "req-1", endpoint="ep", provider_dataset="ds", params={}, payload={"a": 1}
        )
        with pytest.raises(EvidenceImmutableError):
            store.write_evidence(
                run, "req-1", endpoint="ep", provider_dataset="ds", params={}, payload={"a": 2}
            )

    def test_non_jsonable_payload_raises_instead_of_repr(self, spike_root: Path):
        """R2 section 6: repr() truncation is forbidden - lossless or fail."""
        run, store = new_run(run_kind=RunKind.TRIAL, spike_root=spike_root)

        class Opaque:
            pass

        with pytest.raises(TypeError, match="losslessly"):
            store.write_evidence(
                run, "req-2", endpoint="ep", provider_dataset="ds", params={}, payload=Opaque()
            )


class TestB7Capacity:
    def test_dry_run_includes_capacity_case(self, spike_root: Path):
        out = run_dry_run(spike_root)
        run_dir = Path(out["run_dir"])
        catalog_text = (run_dir / "cases" / "spike_case_catalog.jsonl").read_text(encoding="utf-8")
        assert "capacity_backfill" in catalog_text
        metrics = out["phases"]["b7"]
        for key in (
            "symbol_count",
            "row_count",
            "bytes_received",
            "request_count",
            "wall_clock_seconds",
        ):
            assert key in metrics, key


# ------------------------------------------------------------------ helpers


def _case(run_id: str, case_id: str, case_type: str, result: CaseResult) -> SpikeCase:
    return SpikeCase(
        case_id=case_id,
        spike_run_id=run_id,
        case_type=case_type,
        security="X",
        provider_symbol="X",
        trade_date="20260814",
        expected_value="expected",
        actual_value="actual",
        evidence_type="RAW_JSON",
        evidence_ref="raw/x.json",
        result=result,
    )


def _closed(run):
    from ashare_state.spike.model import SpikeRun

    return SpikeRun(
        spike_run_id=run.spike_run_id,
        run_kind=run.run_kind,
        provider=run.provider,
        account_profile_id=run.account_profile_id,
        sdk_version=run.sdk_version,
        runtime_version=run.runtime_version,
        code_commit=run.code_commit,
        environment_lock_hash=run.environment_lock_hash,
        config_hash=run.config_hash,
        started_at=run.started_at,
        ended_at="2026-08-22T00:00:00+00:00",
        status="CLOSED",
    )
