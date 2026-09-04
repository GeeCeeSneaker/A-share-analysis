"""Spike framework contract tests (R2 section 33 + R3 sections 5-20/57)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ashare_state.providers.amazingdata.session import AccountProfile
from ashare_state.spike import (
    CaseCatalog,
    CaseResult,
    RunKind,
    RunLifecycleError,
    RunStatus,
    RunStore,
    abort_run,
    close_run,
    compute_verdict,
    fail_run,
    new_run,
    resume_run,
    run_dry_run,
    verify_production_account,
)
from ashare_state.spike.model import RunFailureReason, SpikeCase

_SHA = "a" * 40


@pytest.fixture(autouse=True)
def _event_gate_relaxed(monkeypatch):
    """R4-A1.1: PRODUCTION runs now require the reviewed golden dataset
    (distinct-event coverage). These tests exercise OTHER gates.

    R4-A2.3: gates are bound-aware - signatures accept optional
    (cases, manifest); the relaxed stubs swallow any bound invocation."""
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "event_coverage_gate", lambda self, *a, **k: [])
    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self, *a, **k: [])
    monkeypatch.setattr(GoldenTruthStore, "production_formal_gate", lambda self, *a, **k: [])


@pytest.fixture
def spike_root(tmp_path: Path) -> Path:
    return tmp_path / "spike"


@pytest.fixture(autouse=True)
def _golden_review_gate_relaxed(monkeypatch):
    """Aggregation-semantics tests must not depend on the (real) golden
    dataset's review status - the review gate has dedicated tests in
    test_golden_truth_gates.py (audit R4-P0-01/02)."""
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self, *a, **k: [])


@pytest.fixture(autouse=True)
def _rule_review_gate_relaxed(monkeypatch):
    """R4-A2.4: aggregation-semantics tests must not depend on the rule
    dataset's review status - the trading-rule review gate has dedicated
    tests in test_trading_rule_binding.py."""
    from ashare_state.spike import trading_rule as rule_module

    monkeypatch.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])


@pytest.fixture(autouse=True)
def _frozen_production_identity(monkeypatch):
    """R4-A3.1 P0-03: freeze the positive production identity matching
    _prod_profile() so PRODUCTION runs can open in these tests. The real
    repo stays fail closed until the formal production account is
    human-confirmed (P0-M-1B); negative-gate tests keep their own
    non-matching profiles."""
    from ashare_state.providers.amazingdata import production_identity as pi

    frozen = pi.FrozenProductionIdentity(
        account_profile_id=_prod_profile().account_profile_id,
        confirmed_at="2026-08-27T00:00:00+00:00",
        confirmed_by="r4-a3.1-test",
    )
    monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)


def _prod_profile() -> AccountProfile:
    return AccountProfile.from_scrubbed(
        {
            "PermissionCode": "1|2|3|4|32|33",
            "SubscribeLimitNum": 5000,
            "TotalWeekFlow": 500,
        },
        provider="amazingdata",
        host="10.0.0.1",
        username="prod-user",
    )


def _production_run(spike_root: Path) -> tuple:
    run, store = new_run(
        run_kind=RunKind.PRODUCTION,
        spike_root=spike_root,
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="1.1.9",
        runtime_version="V4.3.0",
        account_profile_id=_prod_profile().account_profile_id,
        as_of_date="20260814",
        account_profile=_prod_profile(),
    )
    return run, store


def _write_case(
    store: RunStore,
    run,
    catalog: CaseCatalog,
    case_id: str,
    case_type: str,
    result: CaseResult,
    *,
    equivalent_pass: bool = False,
    payload: dict | None = None,
    spike_run_id: str | None = None,
) -> None:
    """Real evidence file + case (verdict closure re-verifies hashes)."""
    meta = store.write_evidence(
        run,
        f"req-{case_id}",
        endpoint="ep",
        provider_dataset="ds",
        params={},
        payload=payload or {"case": case_id},
    )
    is_diff = result is CaseResult.DIFF_EXPLAINED
    catalog.add(
        SpikeCase(
            case_id=case_id,
            spike_run_id=spike_run_id or run.spike_run_id,
            case_type=case_type,
            security="X",
            provider_symbol="X",
            trade_date="20260814",
            expected_value="expected",
            actual_value="actual",
            evidence_type="RAW_JSON",
            evidence_ref=str(meta["evidence_ref"]),
            result=result,
            reason_code="DOCUMENTED_UNIT_DIFFERENCE" if is_diff else "",
            validator_id="test_validator" if is_diff else "",
            validator_version="1.0.0" if is_diff else "",
            evidence_hash=str(meta["content_hash"]),
            equivalent_pass=equivalent_pass,
        )
    )


def _closed(run):
    return replace(run, status=RunStatus.CLOSED.value, ended_at="2026-08-22T00:00:00+00:00")


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
        # R4-A3.1 P0-01: b1 (formal runtime gate boundary) is now the
        # mandatory first phase of the dry run too
        for phase in ("b1", "b2", "b3", "b4", "b5", "b6", "b7"):
            assert phase in phases, phase
        run_dir = Path(out["run_dir"])
        assert (run_dir / "spike_run.json").is_file()
        assert (run_dir / "cases" / "spike_case_catalog.jsonl").is_file()
        # CR-1.1/R4-A2.3: raw evidence now flows ProviderExchange ->
        # RawWriter -> provider=*/dataset=*/ layout (Parquet + .meta.json),
        # plus golden domain bundles under raw/bundles/
        assert any((run_dir / "raw").glob("provider=*/dataset=*/*.meta.json"))
        assert any((run_dir / "raw").glob("provider=*/dataset=*/*.parquet"))
        assert any((run_dir / "raw" / "bundles").glob("*.json"))
        # every case's evidence_ref resolves and its hash closes
        from ashare_state.spike.catalog import CaseCatalog
        from ashare_state.spike.run_store import RunStore
        from ashare_state.spike.runner import verify_evidence_closure

        store = RunStore(spike_root)
        catalog = CaseCatalog(store, out["spike_run_id"])
        catalog.load(run_dir)
        dry_run = store.load_run(out["spike_run_id"], RunKind.DRY_RUN)
        assert verify_evidence_closure(store, dry_run, catalog) == []
        catalog_json = json.loads((run_dir / "spike_run.json").read_text(encoding="utf-8"))
        assert catalog_json["run_kind"] == "DRY_RUN"
        assert catalog_json["status"] == "CLOSED"


class TestRunLifecycle:
    """R3-P0-01: formal runs ALWAYS reach a terminal state."""

    def test_close_run_persists_closed(self, spike_root: Path):
        run, store = _production_run(spike_root)
        closed = close_run(store, run)
        assert closed.status == RunStatus.CLOSED.value
        assert store.load_run(run.spike_run_id, RunKind.PRODUCTION).status == "CLOSED"

    def test_failed_run_persists_terminal_state(self, spike_root: Path):
        run, store = _production_run(spike_root)
        failed = fail_run(store, run, RunFailureReason.FAILED_ACCOUNT)
        assert failed.status == RunStatus.FAILED.value
        loaded = store.load_run(run.spike_run_id, RunKind.PRODUCTION)
        assert loaded.status == "FAILED"
        assert loaded.failure_reason == "FAILED_ACCOUNT"
        # terminal: cannot close or fail again
        with pytest.raises(RunLifecycleError, match="only RUNNING"):
            close_run(store, failed)

    def test_abort_run_persists_terminal_state(self, spike_root: Path):
        run, store = _production_run(spike_root)
        aborted = abort_run(store, run)
        assert aborted.status == RunStatus.ABORTED.value

    def test_verdict_rejects_running_run(self, spike_root: Path):
        run, store = _production_run(spike_root)  # stays RUNNING
        with pytest.raises(Exception, match="close it before the verdict"):
            compute_verdict(store, run)

    def test_verdict_rejects_failed_run(self, spike_root: Path):
        run, store = _production_run(spike_root)
        fail_run(store, run, RunFailureReason.FAILED_ACCOUNT)
        with pytest.raises(Exception, match="close it before the verdict"):
            compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))

    def test_resume_uses_same_run(self, spike_root: Path):
        run, store = _production_run(spike_root)
        resumed = resume_run(
            store,
            run,
            account_profile_id=run.account_profile_id,
            code_commit=run.code_commit,
            environment_lock_hash=run.environment_lock_hash,
            config_hash=run.config_hash,
            sdk_version=run.sdk_version,
            runtime_version=run.runtime_version,
        )
        assert resumed.spike_run_id == run.spike_run_id

    def test_resume_identity_mismatch_refused(self, spike_root: Path):
        run, store = _production_run(spike_root)
        with pytest.raises(RunLifecycleError, match="identity mismatch"):
            resume_run(
                store,
                run,
                account_profile_id="ACCOUNT_OTHER",
                code_commit=run.code_commit,
                environment_lock_hash=run.environment_lock_hash,
                config_hash=run.config_hash,
                sdk_version=run.sdk_version,
                runtime_version=run.runtime_version,
            )

    def test_resume_terminal_run_refused(self, spike_root: Path):
        run, store = _production_run(spike_root)
        close_run(store, run)
        with pytest.raises(RunLifecycleError, match="only RUNNING"):
            resume_run(
                store,
                store.load_run(run.spike_run_id, RunKind.PRODUCTION),
                account_profile_id=run.account_profile_id,
                code_commit=run.code_commit,
                environment_lock_hash=run.environment_lock_hash,
                config_hash=run.config_hash,
                sdk_version=run.sdk_version,
                runtime_version=run.runtime_version,
            )


class TestProductionAccountGate:
    """R3-P0-14: trial/partial accounts cannot open PRODUCTION runs."""

    def test_trial_account_cannot_create_production_run(self, spike_root: Path):
        trial = AccountProfile.from_scrubbed(
            {"PermissionCode": "3|4|32|33", "SubscribeLimitNum": 100, "TotalWeekFlow": 10},
            host="h",
            username="trial",
        )
        with pytest.raises(Exception, match="TRIAL_SIMULATION"):
            new_run(
                run_kind=RunKind.PRODUCTION,
                spike_root=spike_root,
                code_commit=_SHA,
                environment_lock_hash="e" * 64,
                config_hash="c" * 64,
                sdk_version="1.1.9",
                runtime_version="V4.3.0",
                account_profile_id=trial.account_profile_id,
                account_profile=trial,
            )

    def test_unparsed_profile_refused(self):
        unparsed = AccountProfile(auth_ok=True, profile_parsed=False)
        with pytest.raises(Exception, match="not parsed"):
            verify_production_account(unparsed)

    def test_production_requires_complete_provenance(self, spike_root: Path):
        with pytest.raises(Exception, match="full 40-char"):
            new_run(
                run_kind=RunKind.PRODUCTION,
                spike_root=spike_root,
                code_commit="abc123",  # short SHA - forbidden for formal runs
                environment_lock_hash="e" * 64,
                config_hash="c" * 64,
                sdk_version="1.1.9",
                runtime_version="V4.3.0",
                account_profile_id="ACCOUNT_x",
                account_profile=_prod_profile(),
            )
        with pytest.raises(Exception, match="environment_lock_hash"):
            new_run(
                run_kind=RunKind.PRODUCTION,
                spike_root=spike_root,
                code_commit=_SHA,
                environment_lock_hash="",
                config_hash="c" * 64,
                sdk_version="1.1.9",
                runtime_version="V4.3.0",
                account_profile_id="ACCOUNT_x",
                account_profile=_prod_profile(),
            )

    def test_incomplete_provenance_forces_spike_incomplete(self, spike_root: Path):
        """R3-P0-15: even a CLOSED production run with unknown provenance
        cannot produce GO - verdict becomes SPIKE_INCOMPLETE."""
        run, store = _production_run(spike_root)
        # strip provenance out-of-band (simulating legacy run json)
        stripped = replace(run, code_commit="unknown", environment_lock_hash="")
        store.save_run(stripped)
        catalog = CaseCatalog(store, run.spike_run_id)
        _write_case(
            store, run, catalog, "P1", "security_master_with_delisted", CaseResult.VALIDATED_PASS
        )
        catalog.flush(store.run_dir(run))
        close_run(store, stripped)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"
        assert any("provenance" in reason for reason in verdict.blocking_reasons)


class TestVerdictEngine:
    """R3-P0-04/05/16: verdict iterates raw cases, honors equivalence,
    enforces min_valid_cases, and verifies evidence closure."""

    def _full_core_catalog(self, store, run, catalog, *, override=None, count=None, skip=()):
        from ashare_state.spike.capabilities import CORE_CAPABILITIES

        for i, cap in enumerate(CORE_CAPABILITIES):
            if cap.capability_id in skip:
                continue
            for j, case_type in enumerate(cap.required_case_types):
                result = CaseResult.VALIDATED_PASS
                if override and cap.capability_id in override:
                    result = override[cap.capability_id]
                n = count if count is not None else cap.required_case_counts[case_type]
                for k in range(n):
                    _write_case(store, run, catalog, f"C{i}{j}{k}-{case_type}", case_type, result)

    def test_diff_explained_without_equivalence_not_pass(self, spike_root: Path):
        """R3-P0-04 8.1: a capability whose ONLY cases are non-equivalent
        DIFF_EXPLAINED must not satisfy the gate (min_valid_cases unmet)."""
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        self._full_core_catalog(store, run, catalog, skip=("daily_bar_units",))
        _write_case(
            store,
            run,
            catalog,
            "D1-daily_bar_units",
            "daily_bar_units",
            CaseResult.DIFF_EXPLAINED,
            equivalent_pass=False,
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.capability_status["daily_bar_units"] != "PASS"
        assert verdict.verdict == "SPIKE_INCOMPLETE"  # min_valid_cases unmet

    def test_diff_explained_equivalent_can_pass(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        from ashare_state.spike.capabilities import CORE_CAPABILITIES

        for i, cap in enumerate(CORE_CAPABILITIES):
            for case_type in cap.required_case_types:
                if cap.capability_id == "daily_bar_units":
                    for k in range(cap.required_case_counts[case_type]):
                        _write_case(
                            store,
                            run,
                            catalog,
                            f"E{i}{k}-{case_type}",
                            case_type,
                            CaseResult.DIFF_EXPLAINED,
                            equivalent_pass=True,
                            payload={"reason": "DOCUMENTED_UNIT_DIFFERENCE"},
                        )
                else:
                    for k in range(cap.required_case_counts[case_type]):
                        _write_case(
                            store,
                            run,
                            catalog,
                            f"P{i}{k}-{case_type}",
                            case_type,
                            CaseResult.VALIDATED_PASS,
                        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.capability_status["daily_bar_units"] == "PASS"
        assert verdict.verdict == "GO_DEGRADED"

    def test_pass_plus_fail_is_fail(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        self._full_core_catalog(store, run, catalog)
        # daily_bar (min=1): 1 PASS already exists via full catalog; a FAIL
        # must dominate it (R3-P0-04 8.2)
        _write_case(
            store, run, catalog, "F1-daily_bar_units", "daily_bar_units", CaseResult.VALIDATED_FAIL
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.capability_status["daily_bar_units"] == "FAILED"
        assert verdict.verdict == "NO_GO"
        assert "daily_bar_units" in verdict.failed_core

    def test_min_valid_cases_enforced(self, spike_root: Path):
        """min_valid_cases=2: one passing case -> SPIKE_INCOMPLETE for that
        capability (audit R3-P0-05)."""
        from ashare_state.spike.capabilities import CORE_CAPABILITIES

        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        # historical_st_suspend: golden_st_transition requires 50 per-type
        # (R4-P0-04) - one case of EACH type only -> INCOMPLETE
        target_cap = next(
            c for c in CORE_CAPABILITIES if c.capability_id == "historical_st_suspend"
        )
        assert target_cap.required_case_counts["golden_st_transition"] >= 2
        # build: every other capability passes; st has only 1 valid case
        for i, cap in enumerate(CORE_CAPABILITIES):
            if cap.capability_id == "historical_st_suspend":
                # ONE case per required type: enough for
                # historical_st_suspend(1) but NOT golden_st_transition(50)
                for case_type in cap.required_case_types:
                    _write_case(
                        store,
                        run,
                        catalog,
                        f"S{i}-{case_type}-only-one",
                        case_type,
                        CaseResult.VALIDATED_PASS,
                    )
            else:
                for case_type in cap.required_case_types:
                    _write_case(
                        store,
                        run,
                        catalog,
                        f"P{i}-{case_type}",
                        case_type,
                        CaseResult.VALIDATED_PASS,
                    )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.capability_status["historical_st_suspend"] == "SPIKE_INCOMPLETE"
        assert verdict.verdict == "SPIKE_INCOMPLETE"

    def test_evidence_hash_mismatch_blocks_verdict(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        self._full_core_catalog(store, run, catalog)
        catalog.flush(store.run_dir(run))
        # tamper with one EVIDENCE file after flush - the glob target must be
        # the payload json (the case's evidence_ref), never a sibling
        # "<request_id>.meta.json" (which matches "*.json" too but is not a
        # case evidence_ref): an unsorted glob picks whichever entry the
        # filesystem yields first, which is platform dependent (NTFS returns
        # lexical order, ext4 returns directory order) - the resulting
        # verdict differed between Windows and the Ubuntu CI leg.
        tampered = next(
            p
            for p in sorted((store.run_dir(run) / "raw").glob("*.json"))
            if not p.name.endswith(".meta.json")
        )
        tampered.write_text('{"tampered": true}', encoding="utf-8")
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"
        assert any("hash mismatch" in reason for reason in verdict.blocking_reasons)

    def test_catalog_cross_run_case_blocks_verdict(self, spike_root: Path):
        """Simulate a tampered catalog JSONL: a foreign-run case line is
        appended after flush - the closure check must catch it."""
        import json as json_mod

        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        self._full_core_catalog(store, run, catalog)
        catalog.flush(store.run_dir(run))
        jsonl = store.run_dir(run) / "cases" / "spike_case_catalog.jsonl"
        foreign = SpikeCase(
            case_id="X1-daily_bar_units",
            spike_run_id="00000000-0000-0000-0000-000000000000",
            case_type="daily_bar_units",
            security="X",
            provider_symbol="X",
            trade_date="20260814",
            expected_value="expected",
            actual_value="actual",
            evidence_type="RAW_JSON",
            evidence_ref="raw/x.json",
            result=CaseResult.VALIDATED_PASS,
        )
        with jsonl.open("a", encoding="utf-8") as fh:
            payload = foreign.__dict__
            payload["result"] = str(foreign.result)
            fh.write(json_mod.dumps(payload, ensure_ascii=False) + "\n")
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"
        assert any("another run" in reason for reason in verdict.blocking_reasons)

    def test_full_core_pass_yields_go_degraded_without_optional(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        self._full_core_catalog(store, run, catalog)
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "GO_DEGRADED"
        # R3 section 54: milestone eligibility separated from verdict
        assert verdict.p0a_eligible is True
        assert verdict.p0b_eligible is False  # free-float missing
        assert verdict.historical_backfill_eligible == "PARTIAL"

    def test_failed_core_with_full_coverage_is_no_go(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        self._full_core_catalog(
            store, run, catalog, override={"daily_bar_units": CaseResult.VALIDATED_FAIL}
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "NO_GO"
        assert "daily_bar_units" in verdict.failed_core

    def test_missing_core_capability_yields_spike_incomplete(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        _write_case(
            store, run, catalog, "P-1", "security_master_with_delisted", CaseResult.VALIDATED_PASS
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"
        assert len(verdict.missing_core) >= 7


class TestVerdictScopedToOneRun:
    def test_verdict_aggregates_only_its_own_run(self, spike_root: Path):
        """Two closed production runs: a FAIL in run A never pollutes run B."""
        run_a, store = _production_run(spike_root)
        catalog_a = CaseCatalog(store, run_a.spike_run_id)
        _write_case(
            store,
            run_a,
            catalog_a,
            "A-1",
            "security_master_with_delisted",
            CaseResult.VALIDATED_FAIL,
        )
        catalog_a.flush(store.run_dir(run_a))
        close_run(store, run_a)

        run_b, _ = _production_run(spike_root)
        catalog_b = CaseCatalog(store, run_b.spike_run_id)
        _write_case(
            store,
            run_b,
            catalog_b,
            "B-1",
            "security_master_with_delisted",
            CaseResult.VALIDATED_PASS,
        )
        catalog_b.flush(store.run_dir(run_b))
        close_run(store, run_b)

        verdict_b = compute_verdict(store, store.load_run(run_b.spike_run_id, RunKind.PRODUCTION))
        assert verdict_b.capability_status["security_master_with_delisted"] != "FAILED"


class TestCaseIdUniqueness:
    def test_duplicate_case_id_rejected(self, spike_root: Path):
        from ashare_state.spike.catalog import DuplicateCaseError

        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)

        def bare(result: CaseResult) -> SpikeCase:
            return SpikeCase(
                case_id="B3-ST-600000.SH-20260814",
                spike_run_id=run.spike_run_id,
                case_type="historical_st_suspend",
                security="X",
                provider_symbol="X",
                trade_date="20260814",
                expected_value="expected",
                actual_value="actual",
                evidence_type="RAW_JSON",
                evidence_ref="raw/x.json",
                result=result,
            )

        catalog.add(bare(CaseResult.VALIDATED_PASS))
        with pytest.raises(DuplicateCaseError):
            catalog.add(bare(CaseResult.VALIDATED_FAIL))

    def test_semantic_case_ids_coexist(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        _write_case(
            store,
            run,
            catalog,
            "B3-ST-600000.SH-20260814",
            "historical_st_suspend",
            CaseResult.VALIDATED_PASS,
        )
        _write_case(
            store,
            run,
            catalog,
            "B3-LIMIT-600000.SH-20260814",
            "limit_price_and_no_limit_days",
            CaseResult.VALIDATED_PASS,
        )


class TestUnvalidatedNeverPasses:
    def test_observed_is_not_pass(self):
        from ashare_state.spike.model import core_gate_satisfied

        assert not core_gate_satisfied(CaseResult.OBSERVED)
        assert not core_gate_satisfied(CaseResult.MISSING)
        assert not core_gate_satisfied(CaseResult.VALIDATED_FAIL)
        assert not core_gate_satisfied(CaseResult.NOT_TESTABLE_PERMISSION)
        assert core_gate_satisfied(CaseResult.VALIDATED_PASS)
        assert not core_gate_satisfied(CaseResult.DIFF_EXPLAINED)
        assert core_gate_satisfied(CaseResult.DIFF_EXPLAINED, equivalent_pass=True)

    def test_observed_only_run_is_incomplete(self, spike_root: Path):
        run, store = _production_run(spike_root)
        catalog = CaseCatalog(store, run.spike_run_id)
        _write_case(store, run, catalog, "O-1", "sw_taxonomy", CaseResult.OBSERVED)
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict == "SPIKE_INCOMPLETE"


class TestEvidenceIsolation:
    def test_trial_and_production_directories_disjoint(self, spike_root: Path):
        run_t, store = new_run(run_kind=RunKind.TRIAL, spike_root=spike_root)
        run_p, _ = _production_run(spike_root)
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

class TestHistoryCoverageWiring:
    def test_dry_run_uses_2020_history_contract(self, spike_root: Path):
        out = run_dry_run(spike_root, sample_date=20260814)
        catalog_text = (
            Path(out["run_dir"]) / "cases" / "spike_case_catalog.jsonl"
        ).read_text(encoding="utf-8")

        assert "history_start_2020" in catalog_text
        assert "history_start_2018_plus_warmup" not in catalog_text
