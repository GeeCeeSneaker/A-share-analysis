"""R4-A2.5 P0-01 adversarial tests (audit 20260825 section 2).

Every formal limit consumer resolves through the RUN-BOUND rule book:
  - a run bound to vN keeps producing IDENTICAL validation results after
    the ACTIVE dataset advances to vN+1 with DIFFERENT rate semantics
  - tampering the BOUND dataset blocks replay (already covered in
    test_trading_rule_binding; here we prove the END-TO-END effect on the
    B5 limit validation output)
  - AST guard: no formal runtime call to validate_limit_rule without an
    explicit book, and no resolve_* call in probes/golden_router without
    a book= argument
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml
from _anchored_ctx import anchored_conn

from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import RunKind
from ashare_state.spike.probes import ProbeContext, probe_b5_units_pit_freshness
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget
from ashare_state.spike.trading_rule import (
    RuleUnresolvedError,
    TradingRuleBook,
    load_active_rules,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "configs" / "trading_rules"
_SHA = "a" * 40


def _make_rules_root(tmp_path: Path, *, main_rate: float) -> Path:
    """Build a tmp rules root whose ACTIVE v1 dataset has a configurable
    MAIN board rate (so v2 can genuinely change semantics)."""
    root = tmp_path / "configs" / "trading_rules"
    v1 = root / "versions" / "v1"
    v1.mkdir(parents=True)
    doc = yaml.safe_load(
        (RULES_DIR / "versions" / "v20260824-compiled" / "rules.yaml").read_text(encoding="utf-8")
    )
    for rule in doc["rules"]:
        if rule["rule_id"] == "MAIN_BOARD_NORMAL":
            rule["up_rate"] = main_rate
            rule["down_rate"] = main_rate
    (v1 / "rules.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    import hashlib
    import json

    rel = "versions/v1/rules.yaml"
    digest = hashlib.sha256()
    digest.update(rel.encode())
    digest.update((root / rel).read_bytes())
    # coherent governance metadata (R4-A2.6 P0-04): source_version and the
    # non-empty provenance value mirror the dataset file
    (root / "rule_manifest.json").write_text(
        json.dumps(
            {
                "rule_version": "v1",
                "review_status": "COMPILED",
                "dataset_files": [rel],
                "dataset_hash": digest.hexdigest(),
                "source_version": doc.get("source_version", ""),
                "dataset_version": doc["version"],
                "review_provenance": {
                    "source_retrieved_at": str(doc.get("source_retrieved_at", ""))
                },
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    return root


def _manifest_hash(root: Path, rel: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(rel.encode())
    digest.update((root / rel).read_bytes())
    return digest.hexdigest()


def _ctx_with_rules(tmp_path: Path, rules_root: Path, monkeypatch) -> ProbeContext:
    """The rules-root patch stays ACTIVE for the whole test (the bound
    loader resolves through the default rules dir at access time)."""
    monkeypatch.setattr(
        TradingRuleBook,
        "_default_rules_dir",
        classmethod(lambda cls: rules_root),
    )
    run, store = new_run(
        run_kind=RunKind.TRIAL,
        spike_root=tmp_path / "spike",
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="1.1.9",
        runtime_version="V4.3.0",
        account_profile_id="TRIAL_TEST",
        as_of_date="20260814",
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    return ProbeContext(run, store, catalog, FakeTarget(), anchored_conn())


class TestBoundVsActiveSemantics:
    def test_b5_limit_result_invariant_under_active_advance(self, tmp_path: Path, monkeypatch):
        """Adversarial: a TRIAL run binds v1 (MAIN 10%); ACTIVE then
        advances to v2 with MAIN 20% (different semantics). The run's
        B5/B3 limit validation still evaluates against the BOUND v1 - the
        run's cases are IDENTICAL before and after the ACTIVE advance."""
        # v1: MAIN 10% (the fake quotes' 600519 pre 1800 -> 1980/1620)
        root_v1 = _make_rules_root(tmp_path, main_rate=0.10)
        ctx = _ctx_with_rules(tmp_path, root_v1, monkeypatch)
        probe_b5_units_pit_freshness(ctx, 20220601)
        limit_cases_before = [
            (c.case_id, str(c.result)) for c in ctx.catalog.cases if "limit" in c.case_type
        ]
        assert limit_cases_before

        # ACTIVE advance: v2 flips MAIN to 20% (different rate semantics)
        v2 = root_v1 / "versions" / "v2"
        v2.mkdir()
        doc = yaml.safe_load(
            (root_v1 / "versions" / "v1" / "rules.yaml").read_text(encoding="utf-8")
        )
        for rule in doc["rules"]:
            if rule["rule_id"] == "MAIN_BOARD_NORMAL":
                rule["up_rate"] = 0.20
                rule["down_rate"] = 0.20
        (v2 / "rules.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        rel = "versions/v2/rules.yaml"
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(rel.encode())
        digest.update((root_v1 / rel).read_bytes())
        (root_v1 / "rule_manifest.json").write_text(
            json.dumps(
                {
                    "rule_version": "v2",
                    "review_status": "COMPILED",
                    "dataset_files": [rel],
                    "dataset_hash": digest.hexdigest(),
                    "source_version": doc.get("source_version", ""),
                    "dataset_version": doc["version"],
                    "review_provenance": {
                        "source_retrieved_at": str(doc.get("source_retrieved_at", ""))
                    },
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        # ACTIVE is now v2 (20%) - verify the ACTIVE semantics really changed
        book_v2, manifest_v2 = load_active_rules(root_v1)
        assert manifest_v2.rule_version == "v2"
        regime_v2 = book_v2.resolve_limit_regime(
            exchange="SH", code="600519.SH", trade_date="20220601"
        )
        assert float(regime_v2.up_rate) == 0.20

        # the BOUND book (run binding) still resolves v1 (10%)
        regime_bound = ctx.rule_book.resolve_limit_regime(
            exchange="SH", code="600519.SH", trade_date="20220601"
        )
        assert float(regime_bound.up_rate) == 0.10

        # re-running the probe on the SAME run reproduces the SAME limit
        # cases (they evaluate against the BOUND dataset, not ACTIVE v2)
        catalog2 = CaseCatalog(ctx.store, ctx.run.spike_run_id)
        ctx2 = ProbeContext(ctx.run, ctx.store, catalog2, FakeTarget(), anchored_conn())
        probe_b5_units_pit_freshness(ctx2, 20220601)
        limit_cases_after = [
            (c.case_id, str(c.result)) for c in ctx2.catalog.cases if "limit" in c.case_type
        ]
        assert limit_cases_after == limit_cases_before

    def test_bound_dataset_tamper_blocks_replay_of_run(self, tmp_path: Path, monkeypatch):
        """Tampering the run's BOUND dataset file after creation: the
        rule_book property (used by every formal consumer) fails closed."""
        root = _make_rules_root(tmp_path, main_rate=0.10)
        ctx = _ctx_with_rules(tmp_path / "run2", root, monkeypatch)
        assert ctx.rule_book  # sanity: binding resolves before tamper
        victim = root / "versions" / "v1" / "rules.yaml"
        victim.write_bytes(victim.read_bytes() + b"\n# tampered\n")
        with pytest.raises(RuleUnresolvedError, match="hash mismatch"):
            _ = ctx.rule_book


class TestStaticBookUsage:
    def test_formal_modules_never_call_validate_limit_rule_without_book(self):
        """AST guard: every call to validate_limit_rule in probes.py /
        golden_router.py must pass an explicit book= keyword."""
        for source_file in (
            "src/ashare_state/spike/probes.py",
            "src/ashare_state/spike/golden_router.py",
        ):
            tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "validate_limit_rule":
                    keywords = {kw.arg for kw in node.keywords}
                    assert "book" in keywords, (
                        f"{source_file}:{node.lineno} calls validate_limit_rule "
                        "without an explicit book= (R4-A2.5 P0-01)"
                    )
                    book_value = next(kw.value for kw in node.keywords if kw.arg == "book")
                    # book=None literal is the forbidden silent fallback
                    assert not (
                        isinstance(book_value, ast.Constant) and book_value.value is None
                    ), f"{source_file}:{node.lineno} passes book=None"

    def test_resolvers_in_formal_modules_pass_book(self):
        """AST guard: resolve_limit_regime / resolve_trading_rule calls in
        the formal runtime carry a book= argument (router passes the
        run-bound book down)."""
        for source_file in (
            "src/ashare_state/spike/validators.py",
            "src/ashare_state/spike/golden_router.py",
        ):
            tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if isinstance(func, ast.Name) and func.id in (
                    "resolve_limit_regime",
                    "resolve_trading_rule",
                ):
                    keywords = {kw.arg for kw in node.keywords}
                    assert "book" in keywords, (
                        f"{source_file}:{node.lineno} calls {func.id} without "
                        "book= - formal paths must use the run-bound book"
                    )
