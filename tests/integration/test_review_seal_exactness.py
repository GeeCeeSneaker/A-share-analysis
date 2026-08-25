"""R4-A2.9 P0-01: trading-rule review EXACT-BYTE SEAL tests (audit
20260825 #5 section 2).

The invariant:

    hash-checked ACTIVE bytes == bytes transformed == bytes sealed

The tool captures the ACTIVE bytes ONCE (a snapshot) and computes the
verification hash FROM THE SNAPSHOT - there is no second filesystem read
that could substitute seal identity (the old implementation read the file
for the REVIEWED copy and re-read it for hash verification: a swap
between the two reads sealed unverified bytes).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"


def _load_review_module():
    spec = importlib.util.spec_from_file_location(
        "rule_review_tool", REPO_ROOT / "scripts" / "rules" / "review.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "rules"
    vdir = root / "versions" / "v1-compiled"
    vdir.mkdir(parents=True)
    shutil.copy(RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml", vdir / "rules.yaml")
    doc = yaml.safe_load((vdir / "rules.yaml").read_text(encoding="utf-8"))
    rel = "versions/v1-compiled/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    (root / "rule_manifest.json").write_text(
        json.dumps(
            {
                "rule_version": "v1-compiled",
                "review_status": "COMPILED",
                "dataset_files": [rel],
                "dataset_hash": digest.hexdigest(),
                "source_version": str(doc.get("source_version", "")),
                "dataset_version": str(doc.get("version", "")),
                "review_provenance": {
                    "source_retrieved_at": str(doc.get("source_retrieved_at", ""))
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _argv(root: Path, artifact: Path, version: str = "v2-reviewed") -> list[str]:
    return [
        "review.py",
        "--rules",
        str(root / "versions" / "v1-compiled" / "rules.yaml"),
        "--artifact",
        str(artifact),
        "--kind",
        "EXCHANGE_NOTICE",
        "--reviewer",
        "tester",
        "--version",
        version,
        "--rules-root",
        str(root),
    ]


def _run_module(module, argv: list[str], capsys) -> int:
    old_argv = sys.argv
    sys.argv = argv
    try:
        code = module.main()
    finally:
        sys.argv = old_argv
    return code


def _assert_zero_mutation(root: Path) -> None:
    assert not (root / "versions" / "v2-reviewed").exists()
    evidence = root / "evidence"
    assert not evidence.exists() or not list(evidence.glob("*"))
    assert not [p for p in (root / "versions").iterdir() if p.name.startswith(".staging")]
    assert not [p for p in root.iterdir() if p.name.startswith(".rule_manifest")]
    doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
    assert doc["rule_version"] == "v1-compiled"


def _expected_snapshot_hash(root: Path) -> str:
    rel = "versions/v1-compiled/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode("utf-8"))
    digest.update((root / rel).read_bytes())
    return digest.hexdigest()


class TestExactByteSeal:
    def test_healthy_review_reports_snapshot_sha_and_seals(self, tmp_path, capsys):
        """A valid snapshot seals cleanly and the reported snapshot sha is
        the hash over the ACTIVE bytes (the reviewer can independently
        verify what was sealed)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        code = _run_module(module, _argv(root, artifact), capsys)
        assert code == 0
        out = capsys.readouterr().out
        expected = _expected_snapshot_hash(root)
        assert f"sha256={expected[:16]}" in out
        # ACTIVE unchanged; REVIEWED published
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v2-reviewed"

    def test_reviewed_content_derives_from_exact_snapshot(self, tmp_path, capsys):
        """The REVIEWED yaml is a pure provenance-transform of the EXACT
        hash-checked ACTIVE bytes: stripping the inserted seal block from
        the REVIEWED copy equals the ACTIVE bytes with the placeholder
        provenance lines removed."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        assert _run_module(module, _argv(root, artifact), capsys) == 0
        active_lines = (
            (root / "versions" / "v1-compiled" / "rules.yaml")
            .read_text(encoding="utf-8")
            .splitlines(keepends=True)
        )
        reviewed_lines = (
            (root / "versions" / "v2-reviewed" / "rules.yaml")
            .read_text(encoding="utf-8")
            .splitlines(keepends=True)
        )
        placeholder_keys = (
            "reviewed_by:",
            "reviewed_at:",
            "source_artifact_ref:",
            "source_artifact_hash:",
            "source_artifact_kind:",
            "source_retrieved_at:",
        )
        active_body = [
            line
            for line in active_lines
            if not line.startswith(placeholder_keys) and not line.startswith("review_status:")
        ]
        seal_keys = ("review_status:", *placeholder_keys)
        reviewed_body = [line for line in reviewed_lines if not line.startswith(seal_keys)]
        assert reviewed_body == active_body

    def test_snapshot_hash_mismatch_blocks_zero_output(self, tmp_path, monkeypatch, capsys):
        """The ACTIVE file is swapped between the preflight and the
        snapshot read -> the SNAPSHOT hash check blocks (never seals the
        swapped bytes), zero output mutation."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        from ashare_state.spike.trading_rule import load_active_rules

        active_yaml = root / "versions" / "v1-compiled" / "rules.yaml"
        valid_bytes = active_yaml.read_bytes()
        tampered_bytes = valid_bytes + b"\n# swapped in between reads\n"
        # learn how many reads the preflight performs, then tamper every
        # later read of the ACTIVE yaml (the snapshot read)
        counter = {"preflight": 0, "reads": 0}
        preflight_reads = 0
        original_read = Path.read_bytes

        def counting_read(self, *args, **kwargs):
            if self.resolve() == active_yaml.resolve():
                counter["reads"] += 1
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", counting_read)
        load_active_rules(root)
        preflight_reads = counter["reads"]
        monkeypatch.undo()

        # now: valid for the first preflight_reads, tampered afterwards
        state = {"n": 0}

        def swapping_read(self, *args, **kwargs):
            if self.resolve() == active_yaml.resolve():
                state["n"] += 1
                if state["n"] > preflight_reads:
                    return tampered_bytes
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", swapping_read)
        code = _run_module(module, _argv(root, artifact), capsys)
        monkeypatch.undo()
        assert code != 0
        err = capsys.readouterr().err
        assert "snapshot hash mismatch" in err
        _assert_zero_mutation(root)

    def test_no_second_read_can_substitute_seal_identity(self, tmp_path, monkeypatch, capsys):
        """Even with adversarial read interleaving (every read after the
        preflight returns DIFFERENT bytes), the tool either seals the
        verified snapshot or blocks - it can never seal bytes whose hash
        was not checked. Here the snapshot read returns tampered bytes:
        the tool must BLOCK (the old double-read implementation would have
        hash-verified a fresh valid read while sealing the tampered one)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        from ashare_state.spike.trading_rule import load_active_rules

        active_yaml = root / "versions" / "v1-compiled" / "rules.yaml"
        valid_bytes = active_yaml.read_bytes()
        tampered = valid_bytes + b"\n# evil substitution\n"
        counter = {"reads": 0}
        original_read = Path.read_bytes

        def counting(self, *args, **kwargs):
            if self.resolve() == active_yaml.resolve():
                counter["reads"] += 1
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", counting)
        load_active_rules(root)
        preflight_reads = counter["reads"]
        monkeypatch.undo()

        state = {"n": 0}

        def alternating(self, *args, **kwargs):
            if self.resolve() == active_yaml.resolve():
                state["n"] += 1
                if state["n"] > preflight_reads:
                    return tampered
                return valid_bytes
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", alternating)
        code = _run_module(module, _argv(root, artifact), capsys)
        monkeypatch.undo()
        assert code != 0
        # and nothing was sealed
        assert not (root / "versions" / "v2-reviewed").exists()
        doc = json.loads((root / "rule_manifest.json").read_text(encoding="utf-8"))
        assert doc["rule_version"] == "v1-compiled"

    def test_control_all_reads_valid_seals_verified_bytes(self, tmp_path, monkeypatch, capsys):
        """Control for the adversarial tests: with every read returning
        the true bytes the tool seals normally (the read counter sees the
        multi-read preflight and still succeeds)."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        original_read = Path.read_bytes
        calls = {"n": 0}

        def counting(self, *args, **kwargs):
            calls["n"] += 1
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", counting)
        code = _run_module(module, _argv(root, artifact), capsys)
        monkeypatch.undo()
        assert code == 0
        assert calls["n"] > 1  # multiple reads happened; identity held

    def test_single_snapshot_read_after_preflight(self, tmp_path, monkeypatch, capsys):
        """After the preflight the tool reads the ACTIVE yaml EXACTLY
        ONCE (the snapshot) - a second read would reopen the TOCTOU
        window the audit flagged."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        module = _load_review_module()
        from ashare_state.spike.trading_rule import load_active_rules

        active_yaml = root / "versions" / "v1-compiled" / "rules.yaml"
        counter = {"reads": 0}
        original_read = Path.read_bytes

        def counting(self, *args, **kwargs):
            if self.resolve() == active_yaml.resolve():
                counter["reads"] += 1
            return original_read(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_bytes", counting)
        load_active_rules(root)
        preflight_reads = counter["reads"]
        counter["reads"] = 0
        code = _run_module(module, _argv(root, artifact), capsys)
        monkeypatch.undo()
        assert code == 0
        # the tool's OWN preflight (load_active_rules) legitimately
        # re-reads the ACTIVE yaml; beyond that the tool reads it exactly
        # ONCE - the snapshot (no second read can substitute seal identity)
        assert counter["reads"] == preflight_reads + 1
        assert preflight_reads >= 1

    def test_mismatch_leaves_no_evidence_no_version_no_manifest(self, tmp_path, capsys):
        """Plain tampered ACTIVE (hash mismatch at the snapshot): zero
        output - no evidence artifact, no reviewed version, no manifest
        mutation."""
        root = _make_root(tmp_path)
        artifact = tmp_path / "notice.txt"
        artifact.write_text("official notice", encoding="utf-8")
        victim = root / "versions" / "v1-compiled" / "rules.yaml"
        victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        module = _load_review_module()
        code = _run_module(module, _argv(root, artifact), capsys)
        assert code != 0
        _assert_zero_mutation(root)
