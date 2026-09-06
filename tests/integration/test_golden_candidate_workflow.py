"""Golden candidate augmentation + structural event identity tests (R4A2-P0-03, sections 9-16)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import (
    GoldenTruthError,
    GoldenTruthStore,
    delist_event_identity,
    recompute_manifest_statistics,
    semantic_hash_for_doc,
    st_event_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_GOLDEN = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
CANDIDATE_SCRIPT = REPO_ROOT / "scripts" / "golden" / "candidate.py"


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "data" / "golden" / "provider" / "amazingdata"
    shutil.copytree(REPO_GOLDEN, root)
    # These workflow tests exercise the legacy-to-v4 transition from the
    # immutable v3 fixture. The repository ACTIVE pointer is v4 after GT-H2.
    for name in ("golden_cases_v4.jsonl", "truth_manifest_v4.json"):
        (root / name).unlink(missing_ok=True)
    (root / "truth_manifest.json").write_text(
        (root / "truth_manifest_v3.json").read_text(encoding="utf-8"),
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr("ashare_state.spike.golden_store.GOLDEN_ROOT", root)
    monkeypatch.chdir(tmp_path)
    return root


def _run_candidate(root: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CANDIDATE_SCRIPT), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )


def _st_candidate(case_id: str, symbol: str, effective: str, subtype: str) -> dict:
    return {
        "golden_case_id": case_id,
        "case_type": "golden_st_transition",
        "provider_symbol": symbol,
        "trade_date": effective,
        "truth_source": "SSE announcement",
        "source_ref": "sse.com.cn",
        "expected_fields": {"IS_ST_SEC": subtype in ("ST_ADD", "STAR_ST_ADD")},
        "event_id": f"ST-{symbol}-{effective}",
        "event_class": "ST_TRANSITION",
        "event_subtype": subtype,
        "event_effective_date": effective,
    }


def _plan_for_staged(root: Path) -> Path:
    """Create a clean-rebuild plan that drops legacy structural rows."""
    active = json.loads((root / "truth_manifest.json").read_text(encoding="utf-8"))
    dataset = root / str(active["dataset_file"])
    source = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line]
    staged = [
        json.loads(line)
        for line in (root / "candidate_staging.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    operations = [
        {
            "op": "DROP" if doc["event_class"] in {"ST_TRANSITION", "DELIST"} else "KEEP",
            "golden_case_id": doc["golden_case_id"],
        }
        for doc in source
    ]
    operations.extend({"op": "ADD", "case": doc} for doc in staged)
    plan = root.parent / "rebuild.json"
    plan.write_text(
        json.dumps(
            {
                "source_truth_version": active["truth_version"],
                "source_dataset_hash": active["dataset_hash"],
                "operations": operations,
            }
        ),
        encoding="utf-8",
    )
    return plan


class TestCandidateAugmentation:
    def test_full_lifecycle_add_validate_rebuild(self, golden_env: Path):
        inp = golden_env.parent / "new_events.jsonl"
        inp.write_text(
            json.dumps(_st_candidate("GT-ST-NEW-001", "600000.SH", "20240101", "ST_ADD")) + "\n",
            encoding="utf-8",
        )
        r1 = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert r1.returncode == 0, r1.stderr
        r2 = _run_candidate(golden_env, "validate")
        assert r2.returncode == 0, r2.stderr
        plan = _plan_for_staged(golden_env)
        r3 = _run_candidate(
            golden_env,
            "rebuild",
            "--plan",
            str(plan),
            "--truth-version",
            "v4-candidate-20260906",
        )
        assert r3.returncode == 0, r3.stderr
        # new version is ACTIVE and loadable, contains the new case
        cases, manifest = GoldenTruthStore(golden_env).load()
        assert manifest.case_count == 94
        assert any(c.golden_case_id == "GT-ST-NEW-001" for c in cases)
        # the new case is COMPILED (augmentation never reviews)
        new_case = next(c for c in cases if c.golden_case_id == "GT-ST-NEW-001")
        assert new_case.review_status == "COMPILED"
        assert new_case.event_effective_date == "20240101"
        assert manifest.manifest_schema == 2
        assert manifest.distinct_events["ST_TRANSITION"] == 1
        assert manifest.st_add_events == 1
        stats = recompute_manifest_statistics(cases)
        assert manifest.distinct_events == stats["distinct_events"]
        assert manifest.st_remove_events == stats["st_remove_events"]
        assert manifest.distinct_delisted_securities == stats["distinct_delisted_securities"]
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        active["st_add_events"] = 999
        (golden_env / "truth_manifest.json").write_text(
            json.dumps(active), encoding="utf-8", newline="\n"
        )
        with pytest.raises(GoldenTruthError, match="st_add_events"):
            GoldenTruthStore(golden_env).load()
        # prior version file untouched (append-only)
        assert (golden_env / "golden_cases_v3.jsonl").is_file()

    def test_implicit_build_version_is_rejected(self, golden_env: Path):
        result = _run_candidate(golden_env, "build-version")
        assert result.returncode != 0
        assert "explicit KEEP/REPLACE/DROP/ADD" in result.stderr

    def test_st_candidate_requires_subtype_and_effective_date(self, golden_env: Path):
        bad = _st_candidate("GT-ST-BAD-1", "600000.SH", "20240101", "ST_ADD")
        bad.pop("event_subtype")
        inp = golden_env.parent / "bad.jsonl"
        inp.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        result = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert result.returncode != 0
        assert "event_subtype" in result.stderr

        bad_date = _st_candidate("GT-ST-BAD-1B", "600000.SH", "20240230", "ST_ADD")
        inp.write_text(json.dumps(bad_date) + "\n", encoding="utf-8")
        result = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert result.returncode != 0
        assert "calendar date" in result.stderr

    def test_delist_candidate_requires_explicit_effective_date(self, golden_env: Path):
        bad = {
            "golden_case_id": "GT-DELIST-BAD-1",
            "case_type": "golden_delisted",
            "provider_symbol": "600000.SH",
            "trade_date": "20240101",
            "truth_source": "SSE announcement",
            "source_ref": "sse.com.cn",
            "expected_fields": {"IS_DELISTED": True},
            "event_id": "DELIST-600000-2024",
            "event_class": "DELIST",
        }
        inp = golden_env.parent / "bad_delist.jsonl"
        inp.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        result = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert result.returncode != 0
        assert "event_effective_date" in result.stderr

    def test_augmentation_cannot_add_reviewed(self, golden_env: Path):
        doc = _st_candidate("GT-ST-BAD-2", "600000.SH", "20240101", "ST_ADD")
        doc["review_status"] = "REVIEWED"
        inp = golden_env.parent / "bad2.jsonl"
        inp.write_text(json.dumps(doc) + "\n", encoding="utf-8")
        result = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert result.returncode != 0
        assert "COMPILED" in result.stderr

    def test_duplicate_case_id_rejected(self, golden_env: Path):
        inp = golden_env.parent / "dup.jsonl"
        inp.write_text(
            json.dumps(_st_candidate("GT-ST-600518-20190506", "600000.SH", "20240101", "ST_ADD"))
            + "\n",
            encoding="utf-8",
        )
        result = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert result.returncode != 0
        assert "duplicate" in result.stderr


class TestStructuralEventIdentity:
    def test_v4_semantic_hash_seals_event_identity_fields(self):
        doc = {
            "golden_case_id": "G",
            "case_type": "golden_st_transition",
            "provider_symbol": "600000.SH",
            "trade_date": "20240102",
            "truth_source": "s",
            "source_ref": "r",
            "expected_fields": {"IS_ST_SEC": True},
            "source_artifact_hash": "",
            "truth_version": "v4-candidate-test",
            "event_id": "source-alias",
            "event_class": "ST_TRANSITION",
            "event_subtype": "ST_ADD",
            "event_effective_date": "20240101",
        }
        original = semantic_hash_for_doc(doc)
        doc["event_id"] = "renamed-alias"
        assert semantic_hash_for_doc(doc) != original

    def test_event_id_strings_cannot_inflate_st_count(self):
        """Audit section 13: fifty distinct free-form event_id strings
        over ONE real event still count as ONE structural event."""
        from ashare_state.spike.validators import GoldenCase

        identities = set()
        for i in range(50):
            case = GoldenCase(
                golden_case_id=f"G{i}",
                case_type="golden_st_transition",
                provider_symbol="600000.SH",
                trade_date="20240110",
                truth_source="s",
                source_ref="r",
                expected_fields={"IS_ST_SEC": True},
                event_id=f"FAKE-EVENT-{i:03d}",  # inflated ids
                event_class="ST_TRANSITION",
                event_subtype="ST_ADD",
                event_effective_date="20240101",  # ONE real effective date
            )
            identities.add(st_event_identity(case))
        assert len(identities) == 1  # structural identity collapses the fakes

    def test_st_identity_includes_subtype(self):
        from ashare_state.spike.validators import GoldenCase

        base: dict = {
            "golden_case_id": "G",
            "case_type": "golden_st_transition",
            "provider_symbol": "600000.SH",
            "trade_date": "20240110",
            "truth_source": "s",
            "source_ref": "r",
            "expected_fields": {},
            "event_class": "ST_TRANSITION",
            "event_effective_date": "20240101",
        }
        add = GoldenCase(**base, event_id="1", event_subtype="ST_ADD")
        remove = GoldenCase(**base, event_id="1", event_subtype="ST_REMOVE")
        assert st_event_identity(add) != st_event_identity(remove)

    def test_repeated_observations_count_one_structural_event(self):
        from ashare_state.spike.validators import GoldenCase

        st_cases = [
            GoldenCase(
                golden_case_id=f"ST-{i}",
                case_type="golden_st_transition",
                provider_symbol="600000.SH",
                trade_date=f"202401{i + 1:02d}",
                truth_source="s",
                source_ref="r",
                expected_fields={"IS_ST_SEC": True},
                event_id=f"ALIAS-{i}",
                event_class="ST_TRANSITION",
                event_subtype="ST_ADD",
                event_effective_date="20240101",
            )
            for i in range(10)
        ]
        delist_cases = [
            GoldenCase(
                golden_case_id=f"DELIST-{i}",
                case_type="golden_delisted",
                provider_symbol="600001.SH",
                trade_date=f"202402{i + 1:02d}",
                truth_source="s",
                source_ref="r",
                expected_fields={"IS_DELISTED": True},
                event_id=f"ALIAS-DELIST-{i}",
                event_class="DELIST",
                event_effective_date="20240201",
            )
            for i in range(10)
        ]
        stats = recompute_manifest_statistics(st_cases + delist_cases)
        assert stats["distinct_events"]["ST_TRANSITION"] == 1
        assert stats["st_add_events"] == 1
        assert stats["distinct_events"]["DELIST"] == 1
        assert stats["distinct_delisted_securities"] == 1
        assert len({delist_event_identity(case) for case in delist_cases}) == 1

    def test_repeated_observations_publish_and_count_one_structural_event(self, golden_env: Path):
        """Different observations of one event are legal dataset rows."""
        first = _st_candidate("GT-ST-OBS-001", "600000.SH", "20240506", "ST_ADD")
        second = _st_candidate("GT-ST-OBS-002", "600000.SH", "20240506", "ST_ADD")
        second["trade_date"] = "20240507"
        second["event_id"] = "same-event-different-source-alias"
        inp = golden_env.parent / "fakes.jsonl"
        inp.write_text("".join(json.dumps(e) + "\n" for e in (first, second)), encoding="utf-8")
        assert _run_candidate(golden_env, "add-case", "--input", str(inp)).returncode == 0
        plan = _plan_for_staged(golden_env)
        result = _run_candidate(
            golden_env,
            "rebuild",
            "--plan",
            str(plan),
            "--truth-version",
            "v4-candidate-20260906",
        )
        assert result.returncode == 0, result.stderr
        cases, manifest = GoldenTruthStore(golden_env).load()
        observations = [c for c in cases if c.golden_case_id.startswith("GT-ST-OBS-")]
        assert len(observations) == 2
        assert {c.trade_date for c in observations} == {"20240506", "20240507"}
        assert {c.event_id for c in observations} == {
            "ST-600000.SH-20240506",
            "same-event-different-source-alias",
        }
        assert manifest.manifest_schema == 2
        assert manifest.distinct_events["ST_TRANSITION"] == 1
        assert manifest.st_add_events == 1
        stats = recompute_manifest_statistics(cases)
        assert manifest.distinct_events == stats["distinct_events"]
        assert manifest.st_add_events == stats["st_add_events"]
        assert manifest.st_remove_events == stats["st_remove_events"]
        assert manifest.distinct_delisted_securities == stats["distinct_delisted_securities"]

    def test_rebuild_replaces_structural_row_and_preserves_v3(self, golden_env: Path):
        active = json.loads((golden_env / "truth_manifest.json").read_text(encoding="utf-8"))
        dataset = golden_env / str(active["dataset_file"])
        legacy_bytes = dataset.read_bytes()
        source = [
            json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line
        ]
        replacement_id = "GT-ST-600518-20190506"
        replacement = next(doc for doc in source if doc["golden_case_id"] == replacement_id)
        replacement["event_effective_date"] = "20190506"
        operations = []
        for doc in source:
            if doc["golden_case_id"] == replacement_id:
                operations.append(
                    {"op": "REPLACE", "golden_case_id": replacement_id, "case": replacement}
                )
            elif doc["event_class"] in {"ST_TRANSITION", "DELIST"}:
                operations.append({"op": "DROP", "golden_case_id": doc["golden_case_id"]})
            else:
                operations.append({"op": "KEEP", "golden_case_id": doc["golden_case_id"]})
        plan = golden_env.parent / "replace.json"
        plan.write_text(
            json.dumps(
                {
                    "source_truth_version": active["truth_version"],
                    "source_dataset_hash": active["dataset_hash"],
                    "operations": operations,
                }
            ),
            encoding="utf-8",
        )
        result = _run_candidate(golden_env, "rebuild", "--plan", str(plan))
        assert result.returncode == 0, result.stderr
        cases, _ = GoldenTruthStore(golden_env).load()
        replaced = next(case for case in cases if case.golden_case_id == replacement_id)
        assert replaced.event_effective_date == "20190506"
        assert (golden_env / "golden_cases_v3.jsonl").read_bytes() == legacy_bytes
