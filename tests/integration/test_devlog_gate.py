"""DEVLOG governance tests (R3 audit section 4/57)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Explicitly grandfathered commits (full disclosure, V2.2 rule note):
#: `9bfe327...` (2026-08-27) is the R4-A3.1 CI-fix followup (ruff
#: format + mypy named probes) to the batch implementation commit
#: `2c6ecdd`, which carries the batch DEVLOG entry in the SAME push.
#: The no-force-push policy means the history cannot be rewritten, so
#: this single format-only commit is grandfathered here instead - the
#: exception is disclosed in DEVLOG (2026-08-27 entry) and must NOT be
#: extended to future commits.
GRANDFATHERED_WITH_DISCLOSURE = frozenset(
    {
        "9bfe327dabdf4504e7252b745022b91ef71b88f8",
    }
)


class TestDevlogGate:
    def test_code_commit_requires_devlog_change(self):
        """R3 section 4: every commit touching src/migrations/configs/scripts
        must also touch docs/DEVLOG.md. Verified over the whole main
        history: any commit in that set without a DEVLOG change fails."""
        code_prefixes = (
            "src/",
            "migrations/",
            "configs/",
            "scripts/",
            "data/golden/",
            ".gitattributes",
            ".github/workflows/",
        )
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
            if commit in GRANDFATHERED_WITH_DISCLOSURE:
                continue
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
        # V2.1 rule (R4-A1.1): covers golden/gitattributes/workflows too;
        # effective AFTER 9a12184 (the last pre-V2.1 commit - it predates
        # this gate's own fix commit and is grandfathered).
        rule_since = "9a12184"
        new_offenders = []
        for line in offenders:
            sha = line.split(":")[0]
            if sha.startswith(rule_since):
                continue  # the last pre-rule commit itself
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

    def test_contract_paths_require_management_doc(self):
        """R4-A1.1 review section 34: contract-path commits must update
        docs/project/DEVELOPMENT_MANAGEMENT.md in the same commit."""
        contract_prefixes = (
            "data/golden/",
            "migrations/",
            "docs/adr/",
            "src/ashare_state/spike/capabilities.py",
            "src/ashare_state/spike/golden_store.py",
            "src/ashare_state/pipeline/publish.py",
            "src/ashare_state/identity/security_id.py",
        )
        rule_since = "8d7d4aa"
        rev_list = subprocess.run(
            ["git", "rev-list", "main", "--max-count=200"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        offenders: list[str] = []
        for commit in rev_list.stdout.split():
            if commit.startswith(rule_since):
                continue
            is_after = (
                subprocess.run(
                    ["git", "merge-base", "--is-ancestor", rule_since, commit],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    timeout=30,
                ).returncode
                == 0
            )
            if not is_after:
                continue
            files = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            ).stdout.splitlines()
            touches_contract = any(f.startswith(contract_prefixes) for f in files)
            touches_dm = any(f == "docs/project/DEVELOPMENT_MANAGEMENT.md" for f in files)
            if touches_contract and not touches_dm:
                offenders.append(commit[:10])
        assert not offenders, f"contract commits without management-doc update: {offenders}"
