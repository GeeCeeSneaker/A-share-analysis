"""Golden candidate augmentation + structural event identity tests (R4A2-P0-03, sections 9-16)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ashare_state.spike.golden_store import (
    GoldenTruthStore,
    st_event_identity,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_GOLDEN = REPO_ROOT / "data" / "golden" / "provider" / "amazingdata"
CANDIDATE_SCRIPT = REPO_ROOT / "scripts" / "golden" / "candidate.py"


@pytest.fixture
def golden_env(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "data" / "golden" / "provider" / "amazingdata"
    shutil.copytree(REPO_GOLDEN, root)
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


class TestCandidateAugmentation:
    def test_full_lifecycle_add_validate_build(self, golden_env: Path):
        inp = golden_env.parent / "new_events.jsonl"
        inp.write_text(
            json.dumps(_st_candidate("GT-ST-NEW-001", "600000.SH", "20240101", "ST_ADD")) + "\n",
            encoding="utf-8",
        )
        r1 = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert r1.returncode == 0, r1.stderr
        r2 = _run_candidate(golden_env, "validate")
        assert r2.returncode == 0, r2.stderr
        r3 = _run_candidate(golden_env, "build-version")
        assert r3.returncode == 0, r3.stderr
        # new version is ACTIVE and loadable, contains the new case
        cases, manifest = GoldenTruthStore(golden_env).load()
        assert manifest.case_count == 124
        assert any(c.golden_case_id == "GT-ST-NEW-001" for c in cases)
        # the new case is COMPILED (augmentation never reviews)
        new_case = next(c for c in cases if c.golden_case_id == "GT-ST-NEW-001")
        assert new_case.review_status == "COMPILED"
        assert new_case.event_effective_date == "20240101"
        # prior version file untouched (append-only)
        assert (golden_env / "golden_cases_v3.jsonl").is_file()

    def test_st_candidate_requires_subtype_and_effective_date(self, golden_env: Path):
        bad = _st_candidate("GT-ST-BAD-1", "600000.SH", "20240101", "ST_ADD")
        bad.pop("event_subtype")
        inp = golden_env.parent / "bad.jsonl"
        inp.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        result = _run_candidate(golden_env, "add-case", "--input", str(inp))
        assert result.returncode != 0
        assert "event_subtype" in result.stderr

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

    def test_event_gate_counts_structural_identities(self, golden_env: Path):
        """Adding 60 fake-id cases over ONE real event still counts as ONE
        structural identity: 11 = v3's 10 sampled dates (600518 x5, 002450
        x5) + the 60 fakes collapsed into exactly 1."""
        entries = [
            _st_candidate(f"GT-ST-FAKE-{i:03d}", "600000.SH", "20240506", "ST_ADD")
            for i in range(60)
        ]
        inp = golden_env.parent / "fakes.jsonl"
        inp.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
        assert _run_candidate(golden_env, "add-case", "--input", str(inp)).returncode == 0
        assert _run_candidate(golden_env, "build-version").returncode == 0
        problems = GoldenTruthStore(golden_env).event_coverage_gate()
        # 10 v3 sampled-date identities + 1 new = 11 (NOT 70: the 60
        # free-form event_ids collapse into one structural identity)
        assert any("distinct ST_TRANSITION events 11 < 50" in p for p in problems)
