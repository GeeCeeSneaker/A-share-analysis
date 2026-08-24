"""R4-A2.4 trading-rule binding + review gate tests (audit sections 4-5).

P0-03: the run BINDS the rule dataset (file/version/hash/review_status);
RUNNING/RESUME/VERDICT/REPLAY read ONLY the bound dataset - a working-tree
advance/tamper can never leak into a historical run. compute_config_hash
covers configs/** recursively.

P0-04: COMPILED -> REVIEWED review gate (same discipline as golden
truth); PRODUCTION new_run/verdict REQUIRE REVIEWED; the bound source
artifact hash is re-verified.

P1-04: strict st_state parsing (no truthiness inversion).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from ashare_state.providers.amazingdata.session import AccountProfile
from ashare_state.spike.model import RunKind
from ashare_state.spike.runner import (
    RunLifecycleError,
    compute_config_hash,
    new_run,
)
from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    TradingRuleBook,
    load_bound_rule_book,
    trading_rule_review_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"
_SHA = "e" * 40


@pytest.fixture
def rules_env(tmp_path: Path, monkeypatch):
    """Tmp rules layout:
        tmp/configs/trading_rules/            REVIEWED (loader default) + evidence/
        tmp/configs/trading_rules_compiled/   COMPILED (for the block test)
    """
    rules_root = tmp_path / "configs" / "trading_rules"
    compiled_root = tmp_path / "configs" / "trading_rules_compiled"
    rules_root.mkdir(parents=True)
    compiled_root.mkdir(parents=True)
    shutil.copy(RULES_DIR / "a_share_limit_v1.yaml", compiled_root / "a_share_limit_v1.yaml")
    evidence = rules_root / "evidence"
    evidence.mkdir()
    artifact = evidence / "sse_notice_2022.txt"
    artifact.write_text("official exchange notice: price limit rules 2022", encoding="utf-8")
    # build the REVIEWED dataset (same discipline as scripts/rules/review.py)
    doc = yaml.safe_load((RULES_DIR / "a_share_limit_v1.yaml").read_text(encoding="utf-8"))
    doc["review_status"] = "REVIEWED"
    doc["reviewed_by"] = "human-reviewer"
    doc["reviewed_at"] = "2026-08-24T00:00:00+00:00"
    doc["source_artifact_ref"] = "evidence/sse_notice_2022.txt"
    doc["source_artifact_hash"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    doc["source_artifact_kind"] = "EXCHANGE_NOTICE"
    doc["source_retrieved_at"] = "2026-08-24T00:00:00+00:00"
    (rules_root / "a_share_limit_v1_reviewed.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8"
    )
    monkeypatch.setattr(
        TradingRuleBook, "_default_rules_dir", classmethod(lambda cls: rules_root)
    )
    return rules_root


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


def _trial_run(spike_root: Path, **overrides):
    kwargs = {
        "run_kind": RunKind.TRIAL,
        "spike_root": spike_root,
        "code_commit": _SHA,
        "environment_lock_hash": "e" * 64,
        "config_hash": "c" * 64,
        "sdk_version": "1.1.9",
        "runtime_version": "V4.3.0",
        "account_profile_id": "TRIAL_TEST",
        "as_of_date": "20260814",
    }
    kwargs.update(overrides)
    return new_run(**kwargs)


class TestConfigHashRecursion:
    def test_nested_trading_rules_are_in_config_identity(self, tmp_path: Path):
        root = tmp_path
        (root / "configs" / "trading_rules").mkdir(parents=True)
        (root / "configs" / "top.yaml").write_text("a: 1\n", encoding="utf-8")
        (root / "configs" / "trading_rules" / "rules.yaml").write_text(
            "version: v1\n", encoding="utf-8"
        )
        before = compute_config_hash(root)
        # editing the NESTED rule file changes the config hash
        (root / "configs" / "trading_rules" / "rules.yaml").write_text(
            "version: v2\n", encoding="utf-8"
        )
        after = compute_config_hash(root)
        assert before != after


class TestRunBinding:
    def test_trial_run_binds_rule_dataset_identity(self, tmp_path: Path, rules_env):
        run, _store = _trial_run(tmp_path / "spike")
        assert run.trading_rule_file
        assert run.trading_rule_version
        assert len(run.trading_rule_hash) == 64
        assert run.trading_rule_review_status == "REVIEWED"
        # the bound file resolves and its bytes hash matches the binding
        bound_path = Path(run.trading_rule_file)
        assert bound_path.name  # repo-relative convention
        actual = hashlib.sha256(
            (rules_env / bound_path.name).read_bytes()
        ).hexdigest()
        assert actual == run.trading_rule_hash

    def test_binding_survives_working_tree_advance(self, tmp_path: Path, rules_env):
        """Adversarial: after the run binds the rules, the bound file
        CHANGES on disk - the bound loader must refuse (fail closed), not
        silently use the new content."""
        run, _store = _trial_run(tmp_path / "spike")
        bound_name = Path(run.trading_rule_file).name
        bound_file = rules_env / bound_name
        original_bytes = bound_file.read_bytes()
        bound_file.write_bytes(original_bytes + b"\n# tampered\n")
        with pytest.raises(RuleUnresolvedError, match="hash mismatch"):
            load_bound_rule_book(
                rule_file=run.trading_rule_file,
                rule_version=run.trading_rule_version,
                rule_hash=run.trading_rule_hash,
                repo_root=rules_env.parent.parent,
            )

    def test_binding_version_mismatch_refused(self, tmp_path: Path, rules_env):
        run, _store = _trial_run(tmp_path / "spike")
        with pytest.raises(RuleUnresolvedError, match="version mismatch"):
            load_bound_rule_book(
                rule_file=run.trading_rule_file,
                rule_version="v999-different",
                rule_hash=run.trading_rule_hash,
                repo_root=rules_env.parent.parent,
            )

    def test_run_json_persists_rule_binding(self, tmp_path: Path, rules_env):
        run, store = _trial_run(tmp_path / "spike")
        doc = json.loads(
            (store.run_dir(run) / "spike_run.json").read_text(encoding="utf-8")
        )
        assert doc["trading_rule_file"]
        assert doc["trading_rule_version"]
        assert doc["trading_rule_hash"]
        assert doc["trading_rule_review_status"]


class TestReviewGate:
    def test_compiled_rules_block_production_new_run(self, tmp_path: Path, rules_env):
        """P0-04: COMPILED rule candidates may NOT enter production (the
        golden gates are relaxed here - their blocking has dedicated
        tests - so the RULE gate is what refuses)."""
        from ashare_state.spike.golden_store import GoldenTruthStore

        compiled_root = rules_env.parent / "trading_rules_compiled"
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                TradingRuleBook,
                "_default_rules_dir",
                classmethod(lambda cls: compiled_root),
            )
            mp.setattr(GoldenTruthStore, "quantity_gate", lambda self, *a, **k: [])
            mp.setattr(
                GoldenTruthStore, "event_coverage_gate", lambda self, *a, **k: []
            )
            mp.setattr(GoldenTruthStore, "review_gate", lambda self, *a, **k: [])
            book = TradingRuleBook.load()
            assert book.review_status == "COMPILED"
            problems = trading_rule_review_gate(book)
            assert any("not fully human-reviewed" in p for p in problems)
            with pytest.raises(RunLifecycleError, match="trading rule dataset not reviewed"):
                new_run(
                    run_kind=RunKind.PRODUCTION,
                    spike_root=tmp_path / "spike",
                    code_commit=_SHA,
                    environment_lock_hash="e" * 64,
                    config_hash="c" * 64,
                    sdk_version="1.1.9",
                    runtime_version="V4.3.0",
                    account_profile_id=_prod_profile().account_profile_id,
                    as_of_date="20260814",
                    account_profile=_prod_profile(),
                )

    def test_reviewed_rules_pass_gate_and_production_opens(self, tmp_path: Path, rules_env):
        """The golden gates are monkeypatched away here (their production
        blocking has dedicated tests) - this test isolates the RULE gate."""
        from ashare_state.spike.golden_store import GoldenTruthStore

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                GoldenTruthStore,
                "quantity_gate",
                lambda self, *a, **k: [],
            )
            mp.setattr(
                GoldenTruthStore,
                "event_coverage_gate",
                lambda self, *a, **k: [],
            )
            mp.setattr(
                GoldenTruthStore,
                "review_gate",
                lambda self, *a, **k: [],
            )
            run, _store = new_run(
                run_kind=RunKind.PRODUCTION,
                spike_root=tmp_path / "spike",
                code_commit=_SHA,
                environment_lock_hash="e" * 64,
                config_hash="c" * 64,
                sdk_version="1.1.9",
                runtime_version="V4.3.0",
                account_profile_id=_prod_profile().account_profile_id,
                as_of_date="20260814",
                account_profile=_prod_profile(),
            )
            assert run.trading_rule_review_status == "REVIEWED"

    def test_bound_artifact_tamper_blocks_gate(self, tmp_path: Path, rules_env):
        """REVIEWED dataset whose source artifact no longer hashes to the
        sealed value -> review gate BLOCKS (verdict-side re-verification)."""
        book = TradingRuleBook.load(rules_env / "a_share_limit_v1_reviewed.yaml")
        assert trading_rule_review_gate(book, rules_root=rules_env) == []
        artifact = rules_env / "evidence" / "sse_notice_2022.txt"
        artifact.write_bytes(b"tampered official bytes")
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("source artifact hash mismatch" in p for p in problems)

    def test_reviewed_without_provenance_blocks(self, tmp_path: Path, rules_env):
        compiled_root = rules_env.parent / "trading_rules_compiled"
        doc = yaml.safe_load(
            (compiled_root / "a_share_limit_v1.yaml").read_text(encoding="utf-8")
        )
        doc["review_status"] = "REVIEWED"  # no provenance fields!
        bare = rules_env / "bare_reviewed.yaml"
        bare.write_text(yaml.safe_dump(doc), encoding="utf-8")
        book = TradingRuleBook.load(bare)
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("missing provenance" in p for p in problems)

    def test_bad_artifact_kind_rejected(self, tmp_path: Path, rules_env):
        book = TradingRuleBook.load(rules_env / "a_share_limit_v1_reviewed.yaml")
        book.review_provenance["source_artifact_kind"] = "WIKIPEDIA"
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("source_artifact_kind" in p for p in problems)


class TestReviewScript:
    def test_review_script_creates_verified_reviewed_copy(self, tmp_path: Path):
        """scripts/rules/review.py: COMPILED -> REVIEWED with artifact
        hashing; the output passes the review gate (self-verified)."""
        import subprocess
        import sys

        work = tmp_path / "rules"
        work.mkdir()
        shutil.copy(RULES_DIR / "a_share_limit_v1.yaml", work / "rules.yaml")
        artifact = tmp_path / "official_notice.txt"
        artifact.write_text("SSE notice 2022 price limits", encoding="utf-8")
        out = work / "rules_reviewed.yaml"
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "rules" / "review.py"),
                "--rules",
                str(work / "rules.yaml"),
                "--artifact",
                str(artifact),
                "--kind",
                "EXCHANGE_NOTICE",
                "--reviewer",
                "test-reviewer",
                "--out",
                str(out),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )
        assert result.returncode == 0, result.stderr
        reviewed = TradingRuleBook.load(out)
        assert reviewed.review_status == "REVIEWED"
        assert trading_rule_review_gate(reviewed, rules_root=out.parent) == []
        # already-reviewed input refuses a second review
        result2 = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "rules" / "review.py"),
                "--rules",
                str(out),
                "--artifact",
                str(artifact),
                "--kind",
                "EXCHANGE_NOTICE",
                "--reviewer",
                "test-reviewer",
                "--out",
                str(work / "again.yaml"),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )
        assert result2.returncode != 0


class TestStStateParsing:
    def test_explicit_booleans_parse(self):
        from ashare_state.spike.trading_rule import _parse_st_state

        assert _parse_st_state(True) is True
        assert _parse_st_state(False) is False
        assert _parse_st_state(None) is None
        assert _parse_st_state("any") is None
        assert _parse_st_state("ANY") is None
        assert _parse_st_state("true") is True
        assert _parse_st_state("False") is False

    def test_ambiguous_strings_fail_closed(self):
        """P1-04: bool('false') is True - truthiness parsing would SILENTLY
        INVERT the rule; it must raise instead."""
        from ashare_state.spike.trading_rule import _parse_st_state

        for bad in ("maybe", "0", "1", "yes", "no", ""):
            with pytest.raises(ValueError, match="st_state"):
                _parse_st_state(bad)

    def test_rule_file_with_ambiguous_st_state_rejected(self, tmp_path: Path):
        doc = yaml.safe_load((RULES_DIR / "a_share_limit_v1.yaml").read_text(encoding="utf-8"))
        doc["rules"][0]["st_state"] = "maybe"
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(ValueError, match="st_state"):
            TradingRuleBook.load(bad)

    def test_string_false_parses_as_false_not_true(self, tmp_path: Path):
        doc = yaml.safe_load((RULES_DIR / "a_share_limit_v1.yaml").read_text(encoding="utf-8"))
        doc["rules"][0]["st_state"] = "false"
        good = tmp_path / "good.yaml"
        good.write_text(yaml.safe_dump(doc), encoding="utf-8")
        book = TradingRuleBook.load(good)
        assert book.rules[0].st_state is False
