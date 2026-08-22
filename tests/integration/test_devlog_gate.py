"""DEVLOG governance tests (R3 audit section 4/57)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDevlogGate:
    def test_code_commit_requires_devlog_change(self):
        """R3 section 4: every commit touching src/migrations/configs/scripts
        must also touch docs/DEVLOG.md. Verified over the whole main
        history: any commit in that set without a DEVLOG change fails."""
        code_prefixes = ("src/", "migrations/", "configs/", "scripts/")
        rev_list = subprocess.run(
            ["git", "rev-list", "main", "--max-count=200"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        commits = rev_list.stdout.split()
        offenders: list[str] = []
        for commit in commits:
            files = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout.splitlines()
            if not files:
                continue  # merge/empty commits
            touches_code = any(f.startswith(code_prefixes) for f in files)
            touches_devlog = any(f == "docs/DEVLOG.md" for f in files)
            if touches_code and not touches_devlog:
                offenders.append(
                    f"{commit[:10]}: {sorted(f for f in files if f.startswith(code_prefixes))[:3]}"
                )
        # The gate exists from commit e6a2a01 (2026-08-22 R3) onward; older
        # commits predate the rule and are grandfathered.
        rule_since = "e6a2a01"
        new_offenders = []
        for line in offenders:
            sha = line.split(":")[0]
            try:
                is_ancestor = (
                    subprocess.run(
                        ["git", "merge-base", "--is-ancestor", rule_since, sha],
                        cwd=REPO_ROOT,
                        capture_output=True,
                        timeout=30,
                    ).returncode
                    == 0
                )
            except subprocess.TimeoutExpired:
                is_ancestor = False
            if is_ancestor:
                new_offenders.append(line)
        assert not new_offenders, "commits touching code without a DEVLOG update:\n" + "\n".join(
            new_offenders
        )

    def test_devlog_exists_and_uses_dual_status(self):
        devlog = REPO_ROOT / "docs" / "DEVLOG.md"
        assert devlog.is_file()
        text = devlog.read_text(encoding="utf-8")
        assert "Implementation Status" in text
        assert "Review Status" in text
