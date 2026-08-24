"""Golden truth dataset gates (R4-A1.1 hotfix, audit sections 2-13/22)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import (
    GoldenTruthError,
    GoldenTruthStore,
)
from ashare_state.spike.model import RunKind
from ashare_state.spike.runner import RunLifecycleError, new_run

REPO_GOLDEN = Path(__file__).resolve().parents[2] / "data" / "golden" / "provider" / "amazingdata"


@pytest.fixture(autouse=True)
def _rule_review_gate_relaxed(monkeypatch):
    """R4-A2.4: golden-gate tests exercise the GOLDEN review lifecycle;
    the trading-rule review gate has dedicated tests in
    test_trading_rule_binding.py."""
    from ashare_state.spike import trading_rule as rule_module

    monkeypatch.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "data" / "golden" / "provider" / "amazingdata"
    shutil.copytree(REPO_GOLDEN, root)
    monkeypatch.setattr("ashare_state.spike.golden_store.GOLDEN_ROOT", root)
    monkeypatch.chdir(tmp_path)
    return root


@pytest.fixture(autouse=True)
def _no_autoload_fixture_guard():
    """golden_env-dependent tests mutate an isolated copy; tests that do
    NOT use golden_env still resolve the repo dataset via chdir."""


def _active(root: Path) -> dict:
    return json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))


def _dataset(root: Path) -> Path:
    return root / _active(root)["dataset_file"]


def _reseal(root: Path) -> None:
    """Recompute the ACTIVE manifest's dataset hash after a dataset edit
    (simulating a careful attacker who reseals the pointer)."""
    active = _active(root)
    active["dataset_hash"] = hashlib.sha256(_dataset(root).read_bytes()).hexdigest()
    (root / "truth_manifest.json").write_text(
        json.dumps(active, indent=2), encoding="utf-8", newline="\n"
    )


class TestManifestSelfVerification:
    def test_manifest_stats_equal_recomputed_stats(self):
        _, manifest = GoldenTruthStore(REPO_GOLDEN).load()
        assert manifest.case_count == 123
        assert manifest.counts_by_type["golden_st_transition"] == 50

    def test_manifest_review_summary_tamper_detected(self, golden_env: Path):
        active = _active(golden_env)
        active["review_summary"] = {"COMPILED": 0, "REVIEWED": 123}
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active, indent=2), encoding="utf-8", newline="\n"
        )
        with pytest.raises(GoldenTruthError, match="review_summary != recomputed"):
            GoldenTruthStore(golden_env).load()

    def test_manifest_counts_by_type_tamper_detected(self, golden_env: Path):
        active = _active(golden_env)
        active["counts_by_type"]["golden_st_transition"] = 999
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active, indent=2), encoding="utf-8", newline="\n"
        )
        with pytest.raises(GoldenTruthError, match="counts_by_type != recomputed"):
            GoldenTruthStore(golden_env).load()

    def test_dataset_edit_breaks_active_pointer_hash(self, golden_env: Path):
        ds = _dataset(golden_env)
        ds.write_text(ds.read_text(encoding="utf-8") + "\n", encoding="utf-8", newline="\n")
        with pytest.raises(GoldenTruthError, match="dataset hash mismatch"):
            GoldenTruthStore(golden_env).load()


class TestCaseSemanticHash:
    def test_entry_edit_detected_even_after_reseal(self, golden_env: Path):
        ds = _dataset(golden_env)
        lines = ds.read_text(encoding="utf-8").splitlines()
        doc = json.loads(lines[0])
        # first row is the positive Kangmei cap sample (IS_ST_SEC True) -
        # flip the truth to False without touching its semantic hash
        doc["expected_fields"] = {"IS_ST_SEC": False}
        lines[0] = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        ds.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        _reseal(golden_env)  # attacker reseals the pointer hash too
        with pytest.raises(GoldenTruthError, match="case_semantic_hash"):
            GoldenTruthStore(golden_env).load()

    def test_case_type_edit_breaks_case_semantic_hash(self, golden_env: Path):
        """P0-03: case_type is INSIDE the semantic hash."""
        ds = _dataset(golden_env)
        lines = ds.read_text(encoding="utf-8").splitlines()
        doc = json.loads(lines[0])
        doc["case_type"] = "golden_delisted"  # re-type the claim
        lines[0] = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        ds.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        _reseal(golden_env)
        with pytest.raises(GoldenTruthError, match="case_semantic_hash"):
            GoldenTruthStore(golden_env).load()

    def test_missing_seal_field_rejected(self, golden_env: Path):
        ds = _dataset(golden_env)
        lines = ds.read_text(encoding="utf-8").splitlines()
        doc = json.loads(lines[0])
        doc.pop("case_semantic_hash")
        lines[0] = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        ds.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        _reseal(golden_env)
        with pytest.raises(GoldenTruthError, match="missing seal fields"):
            GoldenTruthStore(golden_env).load()


class TestReviewGate:
    def test_reviewed_requires_source_artifact_hash(self, golden_env: Path, monkeypatch):
        """P0-06: hand-edited REVIEWED flags are caught - either by the
        manifest self-verification (stats drift) or, when made
        self-consistent, by the review gate demanding the artifact hash."""
        ds = _dataset(golden_env)
        lines = ds.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            doc = json.loads(line)
            doc["review_status"] = "REVIEWED"  # hand-edited, no artifact hash
            lines[i] = json.dumps(doc, ensure_ascii=False, sort_keys=True)
        ds.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        _reseal(golden_env)
        active = _active(golden_env)
        active["review_summary"] = {"REVIEWED": 123}  # attacker fixes stats too
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active, indent=2), encoding="utf-8", newline="\n"
        )
        # R4-A2.1 hardening: incomplete REVIEWED provenance now fails at LOAD
        # (stronger than the old gate-only check)
        with pytest.raises(GoldenTruthError, match="provenance incomplete"):
            GoldenTruthStore(golden_env).load()

    def test_review_gate_uses_cases_not_manifest_claim(self):
        problems = GoldenTruthStore(REPO_GOLDEN).review_gate()
        assert problems and "REVIEWED 0/123" in problems[0]


class TestEventCoverageGate:
    def test_negative_st_samples_do_not_count_as_st_transition_events(self):
        _, manifest = GoldenTruthStore(REPO_GOLDEN).load()
        # 40 negative ROWS but only 8 distinct negative-sample events;
        # neither counts toward ST_CAP (which is honestly 2)
        assert manifest.distinct_events.get("NEGATIVE_SAMPLE", 0) == 8
        assert manifest.distinct_events.get("ST_TRANSITION", 0) == 2  # honest count

    def test_st_gate_requires_distinct_transition_events(self):
        """Structural identity (audit section 14): the 10 ST rows over 2
        real events (state-sampled dates) collapse to 10 distinct
        (symbol, effective_date) identities - still far below 50."""
        problems = GoldenTruthStore(REPO_GOLDEN).event_coverage_gate()
        assert any("ST_TRANSITION events 10 < 50" in p for p in problems)

    def test_delist_gate_requires_distinct_securities(self):
        """Structural identities (10 symbols x 2 dates = 20) pass the event
        count, but the distinct-SYMBOL gate still blocks at 10."""
        problems = GoldenTruthStore(REPO_GOLDEN).event_coverage_gate()
        assert any("distinct delisted securities 10 < 20" in p for p in problems)

    def test_production_run_refused_until_event_coverage_complete(
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
        with pytest.raises(RunLifecycleError, match="ST_TRANSITION|DELIST|distinct"):
            new_run(
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


class TestLoaderSelection:
    def test_loader_uses_manifest_selected_dataset_not_lexicographic_latest(self, golden_env: Path):
        """P1-02: a lexicographically-later file must not be picked - only
        the ACTIVE manifest's dataset_file loads."""
        # plant a decoy that sorts AFTER v2
        decoy = golden_env / "golden_cases_v9.jsonl"
        decoy.write_text(
            json.dumps({"golden_case_id": "DECOY"}) + "\n", encoding="utf-8", newline="\n"
        )
        cases, manifest = GoldenTruthStore(golden_env).load()
        assert manifest.dataset_file == "golden_cases_v3.jsonl"
        assert all(c.golden_case_id != "DECOY" for c in cases)

    def test_version_is_append_only(self):
        """P1-01: v1 dataset file still exists (never overwritten)."""
        assert (REPO_GOLDEN / "golden_cases_v1.jsonl").is_file()
        assert (REPO_GOLDEN / "golden_cases_v3.jsonl").is_file()


class TestBoundGoldenResolver:
    """R4A2-P0-02: runs resolve their BOUND immutable dataset, never ACTIVE."""

    def _bound_run(self, golden_env: Path, tmp_path: Path):
        """Create a PRODUCTION run bound to the CURRENT ACTIVE dataset."""
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
        from ashare_state.providers.amazingdata.session import AccountProfile
        from ashare_state.spike.golden_store import GoldenTruthStore
        from ashare_state.spike.runner import new_run

        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            provider="amazingdata",
            host="h",
            username="u",
        )
        # relax entry gates (this test exercises BINDING, not review)
        import ashare_state.spike.golden_store as gs

        original = gs.GoldenTruthStore.event_coverage_gate
        gs.GoldenTruthStore.event_coverage_gate = lambda self: []
        gs.GoldenTruthStore.review_gate = lambda self: []
        try:
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
        finally:
            gs.GoldenTruthStore.event_coverage_gate = original
        return run, store, GoldenTruthStore(golden_env)

    def test_run_bound_golden_survives_active_pointer_advance(
        self, golden_env: Path, tmp_path: Path
    ):
        run, store, store_obj = self._bound_run(golden_env, tmp_path)
        bound_file, bound_version, bound_hash = (
            run.golden_dataset_file,
            run.golden_truth_version,
            run.golden_dataset_hash,
        )
        # advance ACTIVE by reviewing one case (creates a new version)
        art = golden_env.parent / "adv.txt"
        art.write_text("advance evidence", encoding="utf-8")
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "scripts/golden/review.py"),
                "--root",
                str(golden_env),
                "--case",
                "GT-ST-600518-20190506",
                "--artifact",
                str(art),
                "--kind",
                "SSE_ANNOUNCEMENT",
                "--reviewer",
                "bob",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        # ACTIVE has advanced past the bound version...
        _, new_manifest = store_obj.load()
        assert new_manifest.truth_version != bound_version
        # ...but the run still resolves its OWN bound dataset exactly
        cases, manifest = store_obj.load_bound(bound_file, bound_version, bound_hash)
        assert manifest.case_count == 123
        assert len(cases) == 123

    def test_bound_dataset_hash_mismatch_blocks(self, golden_env: Path, tmp_path: Path):
        run, store, store_obj = self._bound_run(golden_env, tmp_path)
        with pytest.raises(GoldenTruthError, match="hash mismatch"):
            store_obj.load_bound(run.golden_dataset_file, run.golden_truth_version, "0" * 64)

    def test_missing_bound_dataset_blocks(self, golden_env: Path, tmp_path: Path):
        run, store, store_obj = self._bound_run(golden_env, tmp_path)
        with pytest.raises(GoldenTruthError, match="does not exist"):
            store_obj.load_bound(
                "golden_cases_v99.jsonl", run.golden_truth_version, run.golden_dataset_hash
            )

    def test_run_json_persists_dataset_file(self, golden_env: Path, tmp_path: Path):
        run, store, store_obj = self._bound_run(golden_env, tmp_path)
        loaded = store.load_run(run.spike_run_id, RunKind.PRODUCTION)
        assert loaded.golden_dataset_file == run.golden_dataset_file
        assert loaded.golden_dataset_file.endswith(".jsonl")


class TestSemanticConflictFix:
    def test_v2_has_no_st_removal_contradiction(self):
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
