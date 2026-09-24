from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "spike" / "issue76_c1_migrate.py"
_SPEC = importlib.util.spec_from_file_location("issue76_c1_migrate_test_target", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_project_supplemental_identity_rows = _MODULE._project_supplemental_identity_rows


def _row(**values: object) -> tuple[tuple[str, object], ...]:
    return tuple(sorted(values.items()))


def test_supplement_projects_only_exact_listdate_from_authorized_request() -> None:
    ordinary = _row(provider_symbol="000001.SZ", list_date="1991-04-03", raw_request="other")
    supplement_a = _row(
        provider_symbol="600593.SH",
        list_date="1992-03-27",
        raw_request="approved-request",
        name="mutable current name",
        delist_date=None,
    )
    supplement_b = _row(
        provider_symbol="688001.SH",
        list_date="2019-07-22",
        raw_request="approved-request",
        name="another mutable name",
        industry="mutable sector",
    )
    out_of_scope = _row(
        provider_symbol="600592.SH",
        list_date="1992-03-26",
        raw_request="approved-request",
        name="not in the authorized scope",
    )

    projected = _project_supplemental_identity_rows(
        (ordinary, supplement_a, supplement_b, out_of_scope),
        request_id="approved-request",
        expected_facts={"600593.SH": "1992-03-27", "688001.SH": "2019-07-22"},
    )

    assert projected == (
        ordinary,
        _row(provider_symbol="600593.SH", list_date="1992-03-27"),
        _row(provider_symbol="688001.SH", list_date="2019-07-22"),
    )


@pytest.mark.parametrize(
    "rows",
    [
        (_row(provider_symbol="600593.SH", list_date="1992-03-27", raw_request="approved"),),
        (
            _row(provider_symbol="600593.SH", list_date="1992-03-27", raw_request="approved"),
            _row(provider_symbol="600593.SH", list_date="1992-03-27", raw_request="approved"),
        ),
        (_row(provider_symbol="600593.SH", list_date="1992-03-28", raw_request="approved"),),
    ],
)
def test_supplement_fails_closed_on_missing_duplicate_or_conflicting_facts(
    rows: tuple[tuple[tuple[str, object], ...], ...],
) -> None:
    with pytest.raises(RuntimeError, match="LISTDATE"):
        _project_supplemental_identity_rows(
            rows,
            request_id="approved",
            expected_facts={"600593.SH": "1992-03-27", "688001.SH": "2019-07-22"},
        )
