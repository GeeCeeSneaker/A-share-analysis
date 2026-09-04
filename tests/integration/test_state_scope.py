"""CR-6.3 static scope guards for the State layer."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ashare_state.state.schema import MARKET_STATE_COLUMNS, STATE_FINDING_COLUMNS

pytestmark = pytest.mark.integration

_STATE_ROOT = Path(__file__).resolve().parents[2] / "src" / "ashare_state" / "state"

_ALLOWED_FEATURE_IMPORTS = {
    "ashare_state.features.models": frozenset(
        {"VerifiedFeatureRun", "canonical_json", "semantic_hash"}
    ),
    "ashare_state.features.verifier": frozenset(
        {"verify_feature_run_for_consumption"}
    ),
}
_FORBIDDEN_LAYER_MODULES = (
    "ashare_state.providers",
    "ashare_state.normalization",
    "ashare_state.canonical",
    "ashare_state.snapshot",
    "ashare_state.readmodel",
)
_FORBIDDEN_RESEARCH_MODULES = (
    "ashare_state.strategy",
    "ashare_state.experiment",
    "ashare_state.forward_label",
    "ashare_state.backtest",
)
_FORBIDDEN_RESEARCH_NAMES = frozenset(
    {
        "strategy",
        "experiment",
        "forwardlabel",
        "forward_label",
        "backtest",
        "portfolio",
        "execution",
        "trading",
        "pnl",
        "signal",
        "recommendation",
        "probability",
        "position",
        "bull",
        "bear",
        "predict",
        "prediction",
        "future_return",
    }
)
_FORBIDDEN_FEATURE_SYMBOLS = frozenset(
    {
        "FeatureBuilder",
        "compute_feature_set",
        "build_feature_set",
        "build_feature_run",
    }
)
_EXPECTED_MARKET_STATE_COLUMNS = (
    "trade_date",
    "source_feature_run_id",
    "source_snapshot_id",
    "source_canonical_run_id",
    "state_run_id",
    "state_set_id",
    "state_contract_version",
    "state_available_at",
    "source_feature_input_lineage_hash",
    "input_lineage_hash",
    "universe_rule_id",
    "evidence_observed_security_count",
    "evidence_valid_raw_return_count",
    "evidence_advancer_count",
    "evidence_decliner_count",
    "evidence_unchanged_count",
    "evidence_advancer_ratio_observed",
    "evidence_mean_raw_return_observed",
    "evidence_median_raw_return_observed",
    "evidence_valid_ma20_count",
    "evidence_pct_above_ma20_observed",
    "evidence_valid_mom20_count",
    "evidence_pct_positive_mom20_observed",
    "return_center_state",
    "daily_participation_state",
    "trend_participation_state",
    "market_structure_state",
)
_EXPECTED_FINDING_COLUMNS = (
    "trade_date",
    "state_name",
    "finding_class",
    "detail_json",
)


def _state_modules() -> tuple[tuple[Path, ast.Module], ...]:
    modules = []
    for path in sorted(_STATE_ROOT.glob("*.py")):
        modules.append(
            (
                path,
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
            )
        )
    return tuple(modules)


def _module_is_forbidden(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in (*_FORBIDDEN_LAYER_MODULES, *_FORBIDDEN_RESEARCH_MODULES)
    )


def _node_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(node, (ast.Name, ast.Attribute)):
        names.add(node.id if isinstance(node, ast.Name) else node.attr)
    if isinstance(node, ast.arg):
        names.add(node.arg)
    if isinstance(node, ast.alias):
        names.add(node.name)
        if node.asname is not None:
            names.add(node.asname)
    if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef)):
        names.add(node.name)
    return names


def _import_scope_violations(path: Path, tree: ast.Module) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("ashare_state.features") or _module_is_forbidden(
                    alias.name
                ):
                    violations.append(f"{path.name}: forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _module_is_forbidden(module):
                violations.append(f"{path.name}: forbidden import {module}")
            elif module.startswith("ashare_state.features"):
                allowed = _ALLOWED_FEATURE_IMPORTS.get(module)
                if allowed is None:
                    violations.append(f"{path.name}: non-public Feature import {module}")
                else:
                    for alias in node.names:
                        if alias.name == "*" or alias.name not in allowed:
                            violations.append(
                                f"{path.name}: non-public Feature symbol {alias.name}"
                            )
        elif isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                _module_is_forbidden(node.args[0].value)
                or node.args[0].value.startswith("ashare_state.features")
            )
        ):
            violations.append(
                f"{path.name}: dynamic forbidden import {node.args[0].value}"
            )
    return violations


def _research_name_violations(path: Path, tree: ast.Module) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        names = _node_names(node)
        for name in sorted(names):
            if name.casefold() in _FORBIDDEN_RESEARCH_NAMES:
                violations.append(f"{path.name}: forbidden research identifier {name}")
    return violations


def _feature_implementation_violations(path: Path, tree: ast.Module) -> list[str]:
    violations = []
    for node in ast.walk(tree):
        for name in _node_names(node):
            if name in _FORBIDDEN_FEATURE_SYMBOLS:
                violations.append(f"{path.name}: duplicated Feature symbol {name}")
    return violations


def test_state_import_boundary_is_explicit() -> None:
    violations = []
    for path, tree in _state_modules():
        violations.extend(_import_scope_violations(path, tree))
    assert not violations, "\n".join(violations)


def test_state_does_not_duplicate_feature_implementation() -> None:
    violations = []
    for path, tree in _state_modules():
        violations.extend(_feature_implementation_violations(path, tree))
    assert not violations, "\n".join(violations)


def test_state_contains_no_research_or_predictive_identifiers() -> None:
    violations = []
    for path, tree in _state_modules():
        violations.extend(_research_name_violations(path, tree))
    assert not violations, "\n".join(violations)


def test_state_columns_are_the_frozen_non_future_contract() -> None:
    assert MARKET_STATE_COLUMNS == _EXPECTED_MARKET_STATE_COLUMNS
    assert STATE_FINDING_COLUMNS == _EXPECTED_FINDING_COLUMNS
    forbidden_tokens = (
        "backtest",
        "experiment",
        "forward",
        "future",
        "pnl",
        "portfolio",
        "predict",
        "probability",
        "signal",
        "strategy",
    )
    columns = (*MARKET_STATE_COLUMNS, *STATE_FINDING_COLUMNS)
    assert not [
        column
        for column in columns
        if any(token in column.casefold() for token in forbidden_tokens)
    ]
