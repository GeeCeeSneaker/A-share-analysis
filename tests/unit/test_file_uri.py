"""Logical URI rules tests (design ruling P0-4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ashare_state.storage.paths import (
    AbsolutePathError,
    CaseCollisionError,
    LogicalUriError,
    assert_no_case_collisions,
    physical_from_logical_uri,
    to_logical_uri,
    validate_logical_uri,
)


class TestToLogicalUri:
    def test_relative_posix_output(self, tmp_path: Path):
        p = tmp_path / "canonical" / "fact_daily_bar" / "year=2026" / "part-1.parquet"
        assert to_logical_uri(tmp_path, p) == "canonical/fact_daily_bar/year=2026/part-1.parquet"

    def test_case_is_preserved(self, tmp_path: Path):
        p = tmp_path / "Feature" / "Trend" / "A.parquet"
        assert to_logical_uri(tmp_path, p) == "Feature/Trend/A.parquet"

    def test_escape_rejected(self, tmp_path: Path):
        other = tmp_path.parent / "elsewhere" / "x.parquet"
        with pytest.raises(AbsolutePathError):
            to_logical_uri(tmp_path, other)


class TestValidateLogicalUri:
    def test_valid(self):
        assert validate_logical_uri("a/b/c.parquet") == "a/b/c.parquet"

    @pytest.mark.parametrize(
        "bad",
        [
            "",  # empty
            "/abs/path.parquet",  # leading slash
            "C:/data/x.parquet",  # drive letter
            "c:\\data\\x.parquet",  # backslashes
            "../escape.parquet",  # parent traversal
            "http://evil/x.parquet",  # scheme
        ],
    )
    def test_invalid(self, bad):
        with pytest.raises(LogicalUriError):
            validate_logical_uri(bad)


class TestCaseCollision:
    def test_exact_collapse_blocked(self):
        with pytest.raises(CaseCollisionError, match="case collision"):
            assert_no_case_collisions(["Feature/Trend/a.parquet", "feature/trend/a.parquet"])

    def test_distinct_names_allowed(self):
        assert_no_case_collisions(
            ["Feature/Trend/a.parquet", "Feature/Trend/b.parquet", "feature/vol/A.parquet"]
        )


class TestRoundTrip:
    def test_uri_round_trip(self, tmp_path: Path):
        uri = "canonical/fact_daily_bar/year=2026/month=08/part-0001.parquet"
        physical = physical_from_logical_uri(tmp_path, uri)
        assert to_logical_uri(tmp_path, physical) == uri
