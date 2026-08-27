"""R4-A2.4 + R4-A2.5 trading-rule binding / review gate / version model
tests (audit 20260825 sections 2-4).

P0-02 version model:
    rule_manifest.json (ACTIVE selector) + versions/<v>/rules.yaml
    (immutable coexisting versions) + evidence/ (sealed artifacts).
    The manifest dataset_hash is recomputed over the FULL declared file
    list - tampering ANY file (or the manifest) blocks new_run.

P0-03 gate hardening: evidence refs are path-confined (no absolute / '..'),
hashes are 64 lower-hex, timestamps are ISO-8601.

P0-01: every formal limit consumer resolves through the run-bound book
(validate_limit_rule requires an explicit book; probes pass ctx.rule_book).
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
    load_active_rules,
    load_bound_rule_book,
    load_rule_manifest,
    trading_rule_review_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"
_SHA = "e" * 40


def _manifest_hash(root: Path, rel_files: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(rel_files):
        digest.update(rel.replace("\\", "/").encode("utf-8"))
        digest.update((root / rel).read_bytes())
    return digest.hexdigest()


def _write_manifest(
    root: Path,
    *,
    rule_version: str,
    review_status: str,
    dataset_files: list[str],
    dataset_version: str,
    source_version: str = "",
    provenance: dict | None = None,
) -> None:
    if not source_version:
        # R4-A2.6 P0-04: keep the manifest's governance metadata coherent
        # with the dataset files it selects (read it from the first file)
        doc = yaml.safe_load((root / dataset_files[0]).read_text(encoding="utf-8"))
        source_version = str(doc.get("source_version", ""))
    (root / "rule_manifest.json").write_text(
        json.dumps(
            {
                "rule_version": rule_version,
                "review_status": review_status,
                "dataset_files": dataset_files,
                "dataset_hash": _manifest_hash(root, dataset_files),
                "source_version": source_version,
                "dataset_version": dataset_version,
                "review_provenance": provenance or {},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture
def rules_env(tmp_path: Path, monkeypatch):
    """A tmp rules root with BOTH versions coexisting (immutable versions
    model) + a sealed evidence artifact; ACTIVE initially -> COMPILED."""
    root = tmp_path / "configs" / "trading_rules"
    compiled_dir = root / "versions" / "v1-compiled"
    compiled_dir.mkdir(parents=True)
    shutil.copy(
        RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml", compiled_dir / "rules.yaml"
    )
    # build the REVIEWED version (same discipline as scripts/rules/review.py)
    doc = yaml.safe_load((compiled_dir / "rules.yaml").read_text(encoding="utf-8"))
    doc["review_status"] = "REVIEWED"
    doc["reviewed_by"] = "human-reviewer"
    doc["reviewed_at"] = "2026-08-25T00:00:00+00:00"
    doc["source_artifact_ref"] = "sse_notice_2022.txt"  # RELATIVE to evidence/
    doc["source_artifact_hash"] = hashlib.sha256(
        b"official exchange notice: price limit rules 2022"
    ).hexdigest()
    doc["source_artifact_kind"] = "EXCHANGE_NOTICE"
    doc["source_retrieved_at"] = "2026-08-25T00:00:00+00:00"
    reviewed_dir = root / "versions" / "v2-reviewed"
    reviewed_dir.mkdir(parents=True)
    (reviewed_dir / "rules.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8"
    )
    evidence = root / "evidence"
    evidence.mkdir()
    (evidence / "sse_notice_2022.txt").write_bytes(
        b"official exchange notice: price limit rules 2022"
    )
    _write_manifest(
        root,
        rule_version="v1-compiled",
        review_status="COMPILED",
        dataset_files=["versions/v1-compiled/rules.yaml"],
        dataset_version=doc["version"],
        # mirror the compiled yaml's non-empty provenance value so the
        # manifest <-> dataset coherence check holds (R4-A2.6 P0-04)
        provenance={"source_retrieved_at": "2026-08-24"},
    )
    monkeypatch.setattr(TradingRuleBook, "_default_rules_dir", classmethod(lambda cls: root))
    return root


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


def _relax_golden_gates(mp: pytest.MonkeyPatch) -> None:
    """Isolate the RULE gate: golden gates have dedicated tests."""
    from ashare_state.spike.golden_store import GoldenTruthStore

    mp.setattr(GoldenTruthStore, "quantity_gate", lambda self, *a, **k: [])
    mp.setattr(GoldenTruthStore, "event_coverage_gate", lambda self, *a, **k: [])
    mp.setattr(GoldenTruthStore, "review_gate", lambda self, *a, **k: [])


def _flip_active_to_reviewed(root: Path) -> None:
    """Point the ACTIVE manifest at the REVIEWED version with COHERENT
    governance metadata (R4-A2.6 P0-04)."""
    reviewed = TradingRuleBook.load(root / "versions" / "v2-reviewed" / "rules.yaml")
    _write_manifest(
        root,
        rule_version="v2-reviewed",
        review_status="REVIEWED",
        dataset_files=["versions/v2-reviewed/rules.yaml"],
        dataset_version=reviewed.version,
        provenance={
            key: reviewed.review_provenance[key]
            for key in (
                "reviewed_by",
                "reviewed_at",
                "source_artifact_ref",
                "source_artifact_hash",
                "source_artifact_kind",
                "source_retrieved_at",
            )
        },
    )


class TestConfigHashRecursion:
    def test_nested_trading_rules_are_in_config_identity(self, tmp_path: Path):
        root = tmp_path
        (root / "configs" / "trading_rules" / "versions" / "v1").mkdir(parents=True)
        (root / "configs" / "top.yaml").write_text("a: 1\n", encoding="utf-8")
        rule_file = root / "configs" / "trading_rules" / "versions" / "v1" / "rules.yaml"
        rule_file.write_text("version: v1\n", encoding="utf-8")
        before = compute_config_hash(root)
        rule_file.write_text("version: v2\n", encoding="utf-8")
        after = compute_config_hash(root)
        assert before != after


class TestVersionModel:
    def test_both_versions_coexist_and_active_selects(self, rules_env):
        compiled = TradingRuleBook.load(rules_env / "versions" / "v1-compiled" / "rules.yaml")
        reviewed = TradingRuleBook.load(rules_env / "versions" / "v2-reviewed" / "rules.yaml")
        assert compiled.review_status == "COMPILED"
        assert reviewed.review_status == "REVIEWED"
        # ACTIVE initially -> COMPILED
        book, manifest = load_active_rules(rules_env)
        assert book.review_status == "COMPILED"
        assert manifest.rule_version == "v1-compiled"
        # ACTIVE advance -> REVIEWED; the COMPILED files are untouched
        _flip_active_to_reviewed(rules_env)
        book2, manifest2 = load_active_rules(rules_env)
        assert book2.review_status == "REVIEWED"
        assert manifest2.rule_version == "v2-reviewed"
        assert (
            TradingRuleBook.load(
                rules_env / "versions" / "v1-compiled" / "rules.yaml"
            ).review_status
            == "COMPILED"
        )

    def test_active_dataset_tamper_blocks_load(self, rules_env):
        victim = rules_env / "versions" / "v1-compiled" / "rules.yaml"
        victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        with pytest.raises(RuleUnresolvedError, match="dataset hash mismatch"):
            load_active_rules(rules_env)

    def test_manifest_hash_tamper_blocks_load(self, rules_env):
        # flip the manifest's declared hash to a different value
        path = rules_env / "rule_manifest.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["dataset_hash"] = "0" * 64
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(RuleUnresolvedError, match="dataset hash mismatch"):
            load_active_rules(rules_env)

    def test_manifest_missing_file_blocks_load(self, rules_env):
        path = rules_env / "rule_manifest.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["dataset_files"] = ["versions/never-existed/rules.yaml"]
        path.write_text(json.dumps(doc), encoding="utf-8")
        # R4-A2.6 P0-03: the version-dir mismatch is caught by the
        # structural confinement BEFORE any fs access
        with pytest.raises(RuleUnresolvedError, match="escapes the rule SoR boundary"):
            load_active_rules(rules_env)


class TestRunBinding:
    def test_trial_run_binds_full_dataset_identity(self, tmp_path: Path, rules_env):
        run, _store = _trial_run(tmp_path / "spike")
        assert run.trading_rule_version
        assert run.trading_rule_dataset_files == ["versions/v1-compiled/rules.yaml"]
        assert len(run.trading_rule_dataset_hash) == 64
        assert run.trading_rule_review_status == "COMPILED"
        # the binding hash equals the manifest algorithm over the files
        assert run.trading_rule_dataset_hash == _manifest_hash(
            rules_env, list(run.trading_rule_dataset_files)
        )

    def test_binding_survives_active_advance(self, tmp_path: Path, rules_env):
        """Adversarial: the run binds v1-COMPILED; ACTIVE then advances to
        the v2-REVIEWED version. The BOUND load still resolves v1 (and its
        review status stays COMPILED at binding time)."""
        run, _store = _trial_run(tmp_path / "spike")
        _flip_active_to_reviewed(rules_env)
        bound = load_bound_rule_book(
            rule_version=run.trading_rule_version,
            dataset_files=run.trading_rule_dataset_files,
            dataset_hash=run.trading_rule_dataset_hash,
            rules_root=rules_env,
        )
        assert bound.review_status == "COMPILED"

    def test_binding_blocks_on_bound_file_tamper(self, tmp_path: Path, rules_env):
        run, _store = _trial_run(tmp_path / "spike")
        victim = rules_env / "versions" / "v1-compiled" / "rules.yaml"
        victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        with pytest.raises(RuleUnresolvedError, match="dataset hash mismatch"):
            load_bound_rule_book(
                rule_version=run.trading_rule_version,
                dataset_files=run.trading_rule_dataset_files,
                dataset_hash=run.trading_rule_dataset_hash,
                rules_root=rules_env,
            )

    def test_binding_version_mismatch_refused(self, tmp_path: Path, rules_env):
        """R4-A2.6: rule_version is the SELECTOR id - a binding claiming a
        different selector than the bound files' structural location
        (versions/<id>/) is refused."""
        run, _store = _trial_run(tmp_path / "spike")
        with pytest.raises(RuleUnresolvedError, match="bound dataset file rejected"):
            load_bound_rule_book(
                rule_version="v999-different",
                dataset_files=run.trading_rule_dataset_files,
                dataset_hash=run.trading_rule_dataset_hash,
                rules_root=rules_env,
            )

    def test_binding_dataset_content_version_mismatch_refused(self, tmp_path: Path, rules_env):
        """The dataset CONTENT version (yaml version) is bound separately
        and re-verified on replay (R4-A2.6 P0-04)."""
        run, _store = _trial_run(tmp_path / "spike")
        with pytest.raises(RuleUnresolvedError, match="content version mismatch"):
            load_bound_rule_book(
                rule_version=run.trading_rule_version,
                dataset_files=run.trading_rule_dataset_files,
                dataset_hash=run.trading_rule_dataset_hash,
                dataset_version="9999-01-01.0",
                rules_root=rules_env,
            )

    def test_run_json_persists_dataset_binding(self, tmp_path: Path, rules_env):
        run, store = _trial_run(tmp_path / "spike")
        doc = json.loads((store.run_dir(run) / "spike_run.json").read_text(encoding="utf-8"))
        assert doc["trading_rule_version"]
        assert doc["trading_rule_dataset_files"] == ["versions/v1-compiled/rules.yaml"]
        assert doc["trading_rule_dataset_hash"]
        assert doc["trading_rule_review_status"] == "COMPILED"


class TestReviewGate:
    @pytest.fixture(autouse=True)
    def _frozen_production_identity(self, monkeypatch):
        """R4-A3.1 P0-03: freeze the positive production identity matching
        _prod_profile() - these tests exercise the RULE gate, not the
        account gate (fail closed in the real repo)."""
        from ashare_state.providers.amazingdata import production_identity as pi

        frozen = pi.FrozenProductionIdentity(
            account_profile_id=_prod_profile().account_profile_id,
            confirmed_at="2026-08-27T00:00:00+00:00",
            confirmed_by="r4-a3.1-test",
        )
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)

    def test_compiled_rules_block_production_new_run(self, tmp_path: Path, rules_env):
        """P0-04: COMPILED rule candidates may NOT enter production (the
        golden gates are relaxed here - the RULE gate is what refuses)."""
        with pytest.MonkeyPatch.context() as mp:
            _relax_golden_gates(mp)
            book, _manifest = load_active_rules(rules_env)
            assert book.review_status == "COMPILED"
            problems = trading_rule_review_gate(book, rules_root=rules_env)
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
        _flip_active_to_reviewed(rules_env)
        with pytest.MonkeyPatch.context() as mp:
            _relax_golden_gates(mp)
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

    def test_bound_artifact_tamper_blocks_gate(self, rules_env):
        book = TradingRuleBook.load(rules_env / "versions" / "v2-reviewed" / "rules.yaml")
        assert trading_rule_review_gate(book, rules_root=rules_env) == []
        artifact = rules_env / "evidence" / "sse_notice_2022.txt"
        artifact.write_bytes(b"tampered official bytes")
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("source artifact hash mismatch" in p for p in problems)

    def test_reviewed_without_provenance_blocks(self, rules_env):
        doc = yaml.safe_load(
            (rules_env / "versions" / "v1-compiled" / "rules.yaml").read_text(encoding="utf-8")
        )
        doc["review_status"] = "REVIEWED"  # no provenance fields!
        bare = rules_env / "versions" / "v2-bare" / "rules.yaml"
        bare.parent.mkdir(parents=True)
        bare.write_text(yaml.safe_dump(doc), encoding="utf-8")
        book = TradingRuleBook.load(bare)
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("missing provenance" in p for p in problems)

    def test_bad_artifact_kind_rejected(self, rules_env):
        book = TradingRuleBook.load(rules_env / "versions" / "v2-reviewed" / "rules.yaml")
        book.review_provenance["source_artifact_kind"] = "WIKIPEDIA"
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("source_artifact_kind" in p for p in problems)


class TestGateHardening:
    """R4-A2.5 P0-03 (audit 20260825 section 4.6): review-gate evidence
    hardening - traversal/absolute refs rejected BEFORE fs access, hash
    schema, timestamp schema."""

    @staticmethod
    def _reviewed_book_with_ref(rules_env, **overrides):
        doc = yaml.safe_load(
            (rules_env / "versions" / "v2-reviewed" / "rules.yaml").read_text(encoding="utf-8")
        )
        for key, value in overrides.items():
            doc[key] = value
        target = rules_env / "versions" / "v3-hardened" / "rules.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        return TradingRuleBook.load(target)

    def test_absolute_path_ref_rejected(self, rules_env):
        import platform

        if platform.system() == "Windows":
            ref = "C:/Windows/system32/config.sys"
        else:
            ref = "/etc/passwd"
        book = self._reviewed_book_with_ref(rules_env, source_artifact_ref=ref)
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("must be relative" in p or "rejected" in p for p in problems)

    def test_dotdot_traversal_rejected(self, rules_env):
        book = self._reviewed_book_with_ref(rules_env, source_artifact_ref="../../secrets.txt")
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        # R4-A2.8 P0-02: lexical '..' rejection fires BEFORE any resolve -
        # the message is the traversal rejection, not the escape detection
        assert any("must not traverse" in p or "escapes the evidence root" in p for p in problems)

    def test_non_hex_hash_rejected(self, rules_env):
        book = self._reviewed_book_with_ref(rules_env, source_artifact_hash="NOT-A-SHA256")
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("64 lower-hex" in p for p in problems)

    def test_bad_timestamp_rejected(self, rules_env):
        book = self._reviewed_book_with_ref(rules_env, reviewed_at="yesterday-ish")
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("reviewed_at" in p and "ISO-8601" in p for p in problems)

    def test_missing_artifact_reported(self, rules_env):
        book = self._reviewed_book_with_ref(rules_env, source_artifact_ref="no-such-notice.txt")
        problems = trading_rule_review_gate(book, rules_root=rules_env)
        assert any("not found" in p for p in problems)


class TestReviewScript:
    def test_review_script_creates_new_version_and_flips_active(self, tmp_path: Path):
        """scripts/rules/review.py: COMPILED -> REVIEWED as a NEW immutable
        version; the ACTIVE manifest flips; the output passes the gate
        (self-verified)."""
        import subprocess
        import sys

        root = tmp_path / "rules"
        compiled_dir = root / "versions" / "v1-compiled"
        compiled_dir.mkdir(parents=True)
        shutil.copy(
            RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml",
            compiled_dir / "rules.yaml",
        )
        # coherent governance metadata (R4-A2.7 P0-03): source_version and
        # the non-empty provenance value mirror the dataset file
        compiled_doc = yaml.safe_load((compiled_dir / "rules.yaml").read_text(encoding="utf-8"))
        (root / "rule_manifest.json").write_text(
            json.dumps(
                {
                    "rule_version": "v1-compiled",
                    "review_status": "COMPILED",
                    "dataset_files": ["versions/v1-compiled/rules.yaml"],
                    "dataset_hash": _manifest_hash(root, ["versions/v1-compiled/rules.yaml"]),
                    "source_version": str(compiled_doc.get("source_version", "")),
                    "dataset_version": str(compiled_doc.get("version", "")),
                    "review_provenance": {
                        "source_retrieved_at": str(compiled_doc.get("source_retrieved_at", ""))
                    },
                }
            ),
            encoding="utf-8",
        )
        artifact = tmp_path / "official_notice.txt"
        artifact.write_text("SSE notice 2022 price limits", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "rules" / "review.py"),
                "--rules",
                str(compiled_dir / "rules.yaml"),
                "--artifact",
                str(artifact),
                "--kind",
                "EXCHANGE_NOTICE",
                "--reviewer",
                "test-reviewer",
                "--version",
                "v2-reviewed",
                "--rules-root",
                str(root),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )
        assert result.returncode == 0, result.stderr
        # ACTIVE flipped to the reviewed version; the compiled original is
        # untouched (immutable coexistence)
        manifest = load_rule_manifest(root)
        assert manifest.rule_version == "v2-reviewed"
        assert manifest.review_status == "REVIEWED"
        assert TradingRuleBook.load(compiled_dir / "rules.yaml").review_status == "COMPILED"
        book, _m = load_active_rules(root)
        assert trading_rule_review_gate(book, rules_root=root) == []
        # a second review of the already-reviewed version is refused
        result2 = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "rules" / "review.py"),
                "--rules",
                str(root / "versions" / "v2-reviewed" / "rules.yaml"),
                "--artifact",
                str(artifact),
                "--kind",
                "EXCHANGE_NOTICE",
                "--reviewer",
                "test-reviewer",
                "--version",
                "v3-again",
                "--rules-root",
                str(root),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            env={"PYTHONIOENCODING": "utf-8", "PATH": ""},
        )
        assert result2.returncode != 0


class TestFormalBookRequired:
    def test_validate_limit_rule_refuses_book_none(self):
        """P0-01: explicit book=None is the old silent-fallback footgun -
        the validator refuses it with a structured FAIL."""
        from ashare_state.spike import validators
        from ashare_state.spike.model import CaseResult

        rows = [
            {
                "SECURITY_CODE": "600000",
                "MARKET_CODE": "1",
                "TRADE_DATE": "20240102",
                "PRECLOSE": 10.0,
                "HIGH_LIMITED": 11.0,
                "LOW_LIMITED": 9.0,
                "IS_ST_SEC": "0",
            }
        ]
        out = validators.validate_limit_rule(rows, book=None)
        assert out.result is CaseResult.VALIDATED_FAIL
        assert "book=None refused" in out.actual

    def test_validate_limit_rule_requires_book_kwarg(self):
        """The book parameter has NO default - omitting it is a TypeError
        (fail loud), so the formal runtime can never silently fall back."""
        from ashare_state.spike import validators

        with pytest.raises(TypeError, match="book"):
            validators.validate_limit_rule([])  # type: ignore[call-arg]


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
        doc = yaml.safe_load(
            (RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        doc["rules"][0]["st_state"] = "maybe"
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(ValueError, match="st_state"):
            TradingRuleBook.load(bad)

    def test_string_false_parses_as_false_not_true(self, tmp_path: Path):
        doc = yaml.safe_load(
            (RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        doc["rules"][0]["st_state"] = "false"
        good = tmp_path / "good.yaml"
        good.write_text(yaml.safe_dump(doc), encoding="utf-8")
        book = TradingRuleBook.load(good)
        assert book.rules[0].st_state is False
