"""R4-A2.5 P0-05: B5/B6 payload-shape robustness tests (audit 20260825
section 6).

The real SDK may return scalar lists (calendar ints / code strings) for
payload-only convenience methods. The old consumption pattern coerced
row dicts into GARBAGE strings ("{'value': '600519.SH'}") and silently
"passed". _flat_values flattens scalar lists correctly and FAILS LOUD on
multi-column payloads that cannot be flattened.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _anchored_ctx import anchored_conn

from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import RunKind
from ashare_state.spike.probes import (
    ProbeContext,
    _flat_values,
    probe_b5_units_pit_freshness,
)
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget

_SHA = "c" * 40


def _ctx(tmp_path: Path) -> ProbeContext:
    run, store = new_run(
        run_kind=RunKind.DRY_RUN,
        spike_root=tmp_path / "spike",
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TRIAL_SIMULATION_FAKE",
        as_of_date="20260814",
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    return ProbeContext(run, store, catalog, FakeTarget(), anchored_conn())


class TestFlatValues:
    def test_scalar_list_flattens(self):
        assert _flat_values(["600519.SH", "000001.SZ"]) == ["600519.SH", "000001.SZ"]
        assert _flat_values([20220630, 20220701]) == [20220630, 20220701]

    def test_single_scalar_wraps(self):
        assert _flat_values("600519.SH") == ["600519.SH"]

    def test_none_is_empty(self):
        assert _flat_values(None) == []

    def test_single_column_dict_rows_flatten(self):
        assert _flat_values([{"value": "x"}, {"value": "y"}]) == ["x", "y"]
        assert _flat_values([{"code": "x"}]) == ["x"]

    def test_multi_column_rows_fail_loud(self):
        """A multi-column row cannot be flattened to a scalar list - the
        helper raises instead of producing garbage strings."""
        with pytest.raises(ValueError, match="cannot be flattened"):
            _flat_values([{"code": "600519.SH", "name": "MOUTAI"}])

    def test_dataframe_single_column_flattens(self):
        polars = pytest.importorskip("polars")
        frame = polars.DataFrame({"code": ["600519.SH", "000001.SZ"]})
        assert _flat_values(frame) == ["600519.SH", "000001.SZ"]

    def test_dataframe_multi_column_fails_loud(self):
        polars = pytest.importorskip("polars")
        frame = polars.DataFrame({"code": ["600519.SH"], "name": ["MOUTAI"]})
        with pytest.raises(ValueError, match="cannot be flattened"):
            _flat_values(frame)


class TestB5SymbolExtraction:
    def test_b5_symbols_are_clean_strings_not_row_dicts(self, tmp_path: Path):
        """End-to-end: the dry-run B5 symbol-mapping case consumes REAL
        symbol strings (no "{'value': ...}" garbage from row coercion)."""
        ctx = _ctx(tmp_path)
        metrics = probe_b5_units_pit_freshness(ctx, 20220601)
        assert metrics["symbols"] > 0
        sym_cases = [c for c in ctx.catalog.cases if c.case_type == "symbol_mapping_unambiguous"]
        assert sym_cases
        # the catalog json (expected/actual payloads) never contains
        # row-dict garbage strings from coercion
        ctx.catalog.flush(ctx.store.run_dir(ctx.run))
        catalog_path = ctx.store.run_dir(ctx.run) / "cases" / "spike_case_catalog.jsonl"
        text = catalog_path.read_text(encoding="utf-8")
        assert "{'value'" not in text
        # the symbol-mapping case itself validated over clean strings
        from ashare_state.spike.model import CaseResult

        assert any(c.result is CaseResult.VALIDATED_PASS for c in sym_cases)

    def test_scalar_list_payload_via_fake_code_list(self):
        """FakeTarget's code list IS a scalar list - the B5 path must
        consume it through _flat_values (both helpers agree)."""
        target = FakeTarget()
        payload = target.get_code_list_exchange("EXTRA_STOCK_A").payload
        assert isinstance(payload, list)
        assert all(isinstance(item, str) for item in payload)
        flat = _flat_values(payload)
        assert flat == payload
