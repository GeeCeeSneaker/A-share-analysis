"""Golden truth dataset gates (audit R4-P0-01/02/03/04/12, section 40)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import (
    REQUIRED_GOLDEN_COUNTS,
    GoldenTruthError,
    GoldenTruthStore,
)
from ashare_state.spike.model import RunKind
from ashare_state.spike.runner import close_run, new_run

REPO_GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden" / "provider" / "amazingdata"


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    """Isolated copy of the real dataset at the RELATIVE path structure
    (data/golden/provider/amazingdata) + chdir, so the default
    GoldenTruthStore() resolves it."""
    root = tmp_path / "data" / "golden" / "provider" / "amazingdata"
    shutil.copytree(REPO_GOLDEN, root)
    monkeypatch.setattr("ashare_state.spike.golden_store.GOLDEN_ROOT", root)
    monkeypatch.chdir(tmp_path)
    return root


class TestDatasetIntegrity:
    def test_repo_dataset_loads_and_seals(self):
        cases, manifest = GoldenTruthStore(REPO_GOLDEN).load()
        assert manifest.case_count == len(cases) == 123
        assert manifest.quantities_complete

    def test_required_minimums_match_core_gate(self):
        assert REQUIRED_GOLDEN_COUNTS == {
            "golden_st_transition": 50,
            "golden_delisted": 20,
            "golden_limit_regime": 30,
            "golden_corporate_action": 20,
        }

    def test_manifest_hash_mismatch_detected(self, golden_env: Path):
        jsonl = golden_env / "golden_cases_v1.jsonl"
        jsonl.write_text(
            jsonl.read_text(encoding="utf-8") + json.dumps({"tampered": True}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(GoldenTruthError, match="manifest hash mismatch"):
            GoldenTruthStore(golden_env).load()

    def test_entry_edit_without_reseal_detected(self, golden_env: Path):
        """R4-P0-02: editing one entry (FAIL->PASS style) breaks its
        source_hash even when the manifest is re-sealed."""
        jsonl = golden_env / "golden_cases_v1.jsonl"
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        doc = json.loads(lines[0])
        # flip the truth (first entry is an IS_ST_SEC=False negative case)
        doc["expected_fields"] = {"IS_ST_SEC": True}
        lines[0] = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        manifest_path = golden_env / "truth_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["manifest_hash"] = hashlib.sha256(jsonl.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with pytest.raises(GoldenTruthError, match="source_hash mismatch"):
            GoldenTruthStore(golden_env).load()

    def test_missing_seal_field_rejected(self, golden_env: Path):
        jsonl = golden_env / "golden_cases_v1.jsonl"
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        doc = json.loads(lines[0])
        doc.pop("source_hash")
        lines[0] = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        manifest_path = golden_env / "truth_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["manifest_hash"] = hashlib.sha256(jsonl.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with pytest.raises(GoldenTruthError, match="missing seal fields"):
            GoldenTruthStore(golden_env).load()


class TestReviewGate:
    def test_compiled_dataset_blocks_production_verdict(self):
        """Audit section 39: v1 ships COMPILED entries -> review gate
        returns blocking reasons (production verdicts become
        SPIKE_INCOMPLETE until the human review completes)."""
        _, manifest = GoldenTruthStore(REPO_GOLDEN).load()
        assert not manifest.fully_reviewed
        problems = GoldenTruthStore(REPO_GOLDEN).review_gate()
        assert problems and "not fully human-reviewed" in problems[0]

    def test_quantity_gate_passes_on_v1(self):
        assert GoldenTruthStore(REPO_GOLDEN).quantity_gate() == []


class TestRunBinding:
    def test_production_run_binds_golden_at_creation(
        self, tmp_path: Path, monkeypatch, golden_env: Path
    ):
        monkeypatch.chdir(tmp_path)
        from ashare_state.providers.amazingdata.session import AccountProfile

        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            provider="amazingdata",
            host="h",
            username="u",
        )
        run, store = new_run(
            run_kind=RunKind.PRODUCTION,
            spike_root=tmp_path / "spike",
            code_commit="a" * 40,
            environment_lock_hash="e" * 64,
            config_hash="c" * 64,
            sdk_version="1.1.9",
            runtime_version="V4.3.0",
            account_profile_id=profile.account_profile_id,
            account_profile=profile,
        )
        assert run.golden_truth_version
        assert len(run.golden_manifest_hash) == 64
        # persisted through save/load
        loaded = store.load_run(run.spike_run_id, RunKind.PRODUCTION)
        assert loaded.golden_truth_version == run.golden_truth_version
        assert loaded.provenance_complete()

    def test_binding_drift_detected_on_verify(self, golden_env: Path):
        store_obj = GoldenTruthStore(golden_env)
        _, manifest = store_obj.load()
        with pytest.raises(GoldenTruthError, match="drifted"):
            store_obj.verify_binding(
                truth_version="v999-other", manifest_hash=manifest.manifest_hash
            )
        with pytest.raises(GoldenTruthError, match="manifest_hash drifted"):
            store_obj.verify_binding(truth_version=manifest.truth_version, manifest_hash="0" * 64)


class TestCatalogSeal:
    def test_closed_catalog_tamper_blocks_verdict(
        self, tmp_path: Path, monkeypatch, golden_env: Path
    ):
        """R4-P0-12: editing the closed catalog (FAIL->PASS) is detected by
        the verdict's seal re-computation."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "ashare_state.spike.golden_store.GoldenTruthStore.review_gate",
            lambda self: [],
        )
        from ashare_state.providers.amazingdata.session import AccountProfile
        from ashare_state.spike import CaseCatalog, CaseResult, compute_verdict
        from ashare_state.spike.model import SpikeCase

        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            provider="amazingdata",
            host="h",
            username="u",
        )
        run, store = new_run(
            run_kind=RunKind.PRODUCTION,
            spike_root=tmp_path / "spike",
            code_commit="a" * 40,
            environment_lock_hash="e" * 64,
            config_hash="c" * 64,
            sdk_version="1.1.9",
            runtime_version="V4.3.0",
            account_profile_id=profile.account_profile_id,
            account_profile=profile,
        )
        catalog = CaseCatalog(store, run.spike_run_id)
        # one failing case -> tamper it to PASS after close
        meta = store.write_evidence(
            run,
            "req-1",
            endpoint="ep",
            provider_dataset="ds",
            params={},
            payload={"x": 1},
        )
        catalog.add(
            SpikeCase(
                case_id="T1",
                spike_run_id=run.spike_run_id,
                case_type="daily_bar_units",
                security="X",
                provider_symbol="X",
                trade_date="20260814",
                expected_value="e",
                actual_value="a",
                evidence_type="RAW_JSON",
                evidence_ref=str(meta["evidence_ref"]),
                result=CaseResult.VALIDATED_FAIL,
                evidence_hash=str(meta["content_hash"]),
            )
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        # verdict sees the FAIL -> NO_GO path (fail dominates)
        verdict = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert verdict.verdict in ("NO_GO", "SPIKE_INCOMPLETE")
        assert verdict.capability_status["daily_bar_units"] == "FAILED"
        # ---- the tamper: edit the closed catalog FAIL -> PASS
        catalog_path = store.run_dir(run) / "cases" / "spike_case_catalog.jsonl"
        tampered = catalog_path.read_text(encoding="utf-8").replace(
            "VALIDATED_FAIL", "VALIDATED_PASS"
        )
        catalog_path.write_text(tampered, encoding="utf-8")
        verdict2 = compute_verdict(store, store.load_run(run.spike_run_id, RunKind.PRODUCTION))
        assert "R4-P0-12" in " ".join(verdict2.blocking_reasons)
        assert verdict2.verdict == "SPIKE_INCOMPLETE"


class TestSemanticConflictFix:
    def test_v1_has_no_st_removal_contradiction(self):
        """R4-P0-03: no case claims 'ST removal' while expecting IS_ST
        True; no case mixes 20% and no-limit on the same day."""
        cases, _ = GoldenTruthStore(REPO_GOLDEN).load()
        for case in cases:
            if case.case_type == "golden_st_transition":
                assert not (
                    "removal" in case.truth_source.lower()
                    and case.expected_fields.get("IS_ST_SEC") is True
                ), case.golden_case_id
            if case.case_type == "golden_limit_regime":
                fields = case.expected_fields
                has_no_limit = fields.get("HIGH_LIMITED", "x") is None
                has_rate = "PRICE_HIGH_LMT_RATE" in fields
                assert not (has_no_limit and has_rate), case.golden_case_id
