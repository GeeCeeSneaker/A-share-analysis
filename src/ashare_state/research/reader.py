"""Stable, fail-closed Python/Parquet reader for R1 research artifacts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import polars as pl

from ashare_state.research.models import (
    RESEARCH_SECURITY_DAILY_FIELDS,
    ResearchEligibility,
    ResearchManifest,
    ResearchReaderError,
    ResearchSplit,
    canonical_json,
    parse_date_value,
    research_security_daily_schema,
    sha256_hex,
    validate_manifest_semantics,
)
from ashare_state.research.splits import split_window

__all__ = [
    "ResearchPanelReader",
    "load_disabled_research_security_daily",
    "load_research_security_daily",
]


class ResearchPanelReader:
    """Read one immutable manifest without exposing disabled rows by default."""

    def __init__(
        self,
        manifest_path: Path,
        manifest: ResearchManifest,
        *,
        allow_test_fixture: bool = False,
    ) -> None:
        self.manifest_path = manifest_path
        self.manifest = manifest
        self._allow_test_fixture = allow_test_fixture

    @classmethod
    def from_manifest(
        cls,
        manifest_path: str | Path,
        *,
        allow_test_fixture: bool = False,
    ) -> ResearchPanelReader:
        path = Path(manifest_path)
        if not path.is_file():
            raise ResearchReaderError(f"research manifest does not exist: {path}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("manifest root must be an object")
            validate_manifest_semantics(
                payload,
                allow_non_observed_coverage=True,
                allow_test_fixture=allow_test_fixture,
            )
            manifest = ResearchManifest.from_mapping(
                payload,
                allow_test_fixture=allow_test_fixture,
            )
        except ResearchReaderError:
            raise
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ResearchReaderError(f"cannot parse research manifest {path}: {exc}") from exc
        if Path(manifest.manifest_uri).name != path.name:
            raise ResearchReaderError("manifest_uri does not identify the supplied manifest")
        return cls(path, manifest, allow_test_fixture=allow_test_fixture)

    def load_security_daily(
        self,
        *,
        split: ResearchSplit | str,
        start: date | str | None = None,
        end: date | str | None = None,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Load one explicit split; holdout is never an implicit default."""
        validate_manifest_semantics(
            self.manifest.as_dict(),
            allow_non_observed_coverage=False,
            allow_test_fixture=self._allow_test_fixture,
        )
        self._verify_aggregate_seals()
        try:
            readable_split = ResearchSplit(split)
        except ValueError as exc:
            raise ResearchReaderError(f"unknown readable split {split!r}") from exc
        if readable_split not in {
            ResearchSplit.DEVELOPMENT,
            ResearchSplit.VALIDATION_A,
            ResearchSplit.HOLDOUT,
        }:
            raise ResearchReaderError(f"{readable_split.value} is not a default-readable split")
        start_date, end_date = self._requested_range(readable_split, start, end)
        artifact = self.manifest.artifact(readable_split.value)
        frame = self._read_verified_artifact(artifact.name)
        frame = frame.filter(
            (pl.col("trade_date") >= pl.lit(start_date))
            & (pl.col("trade_date") <= pl.lit(end_date))
        )
        return self._select_columns(frame, columns)

    def load_disabled_security_daily(
        self,
        *,
        columns: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        """Explicit diagnostic access to preserved disabled rows.

        This method is intentionally separate from ``load_security_daily`` so
        an ordinary research read cannot accidentally include unresolved data.
        """
        validate_manifest_semantics(
            self.manifest.as_dict(),
            allow_non_observed_coverage=True,
            allow_test_fixture=self._allow_test_fixture,
        )
        self._verify_aggregate_seals()
        frame = self._read_verified_artifact("disabled")
        return self._select_columns(frame, columns)

    def _requested_range(
        self,
        split: ResearchSplit,
        start: date | str | None,
        end: date | str | None,
    ) -> tuple[date, date]:
        window_start, window_end = split_window(split)
        start_date = window_start if start is None else parse_date_value(start)
        end_date = window_end if end is None else parse_date_value(end)
        if start_date < window_start or end_date > window_end or start_date > end_date:
            raise ResearchReaderError(
                f"requested range {start_date}..{end_date} crosses {split.value} boundaries"
            )
        return start_date, end_date

    def _read_verified_artifact(self, name: str) -> pl.DataFrame:
        artifact = self.manifest.artifact(name)
        artifact_path = self.manifest_path.parent / Path(artifact.uri).name
        if artifact_path.parent.resolve() != self.manifest_path.parent.resolve():
            raise ResearchReaderError("artifact URI escapes the immutable manifest directory")
        if not artifact_path.is_file():
            raise ResearchReaderError(f"research artifact does not exist: {artifact_path}")
        payload = artifact_path.read_bytes()
        if sha256_hex(payload) != artifact.content_hash:
            raise ResearchReaderError(f"research artifact bytes changed: {artifact.name}")
        try:
            frame = pl.read_parquet(artifact_path)
        except Exception as exc:
            raise ResearchReaderError(
                f"cannot read research artifact {artifact.name}: {exc}"
            ) from exc
        expected_schema = research_security_daily_schema()
        actual_schema = [(field, str(frame.schema[field])) for field in frame.schema]
        expected_descriptor = [(field, str(expected_schema[field])) for field in expected_schema]
        if actual_schema != expected_descriptor or artifact.schema_hash != sha256_hex(
            canonical_json(expected_descriptor)
        ):
            raise ResearchReaderError(f"research artifact schema changed: {artifact.name}")
        if frame.height != artifact.row_count:
            raise ResearchReaderError(f"research artifact row count changed: {artifact.name}")
        if sha256_hex(canonical_json(frame.to_dicts())) != artifact.semantic_hash:
            raise ResearchReaderError(
                f"research artifact semantic content changed: {artifact.name}"
            )
        if name == "disabled":
            if (
                frame.height
                and frame.get_column("research_eligibility")
                .eq(ResearchEligibility.ENABLED.value)
                .any()
            ):
                raise ResearchReaderError("disabled artifact contains enabled rows")
        elif (
            artifact.research_eligible
            and frame.height
            and frame.get_column("research_eligibility").ne(ResearchEligibility.ENABLED.value).any()
        ):
            raise ResearchReaderError(f"enabled artifact {name} contains disabled rows")
        return frame

    def _verify_aggregate_seals(self) -> None:
        artifacts = list(self.manifest.artifacts)
        expected_content_hash = sha256_hex(
            canonical_json(
                {
                    "schema_hash": self.manifest.schema_hash,
                    "artifacts": [
                        {
                            "name": artifact.name,
                            "semantic_hash": artifact.semantic_hash,
                            "row_count": artifact.row_count,
                        }
                        for artifact in artifacts
                    ],
                }
            )
        )
        expected_artifact_set_hash = sha256_hex(
            canonical_json([artifact.as_dict() | {"name": artifact.name} for artifact in artifacts])
        )
        if expected_content_hash != self.manifest.content_hash:
            raise ResearchReaderError("research manifest content_hash seal is inconsistent")
        if expected_artifact_set_hash != self.manifest.artifact_set_hash:
            raise ResearchReaderError("research manifest artifact_set_hash seal is inconsistent")
        enabled_count = sum(
            artifact.row_count for artifact in artifacts if artifact.research_eligible
        )
        disabled_count = self.manifest.artifact("disabled").row_count
        if (
            enabled_count != self.manifest.enabled_row_count
            or disabled_count != self.manifest.disabled_row_count
        ):
            raise ResearchReaderError("research manifest row-count seals are inconsistent")

    @staticmethod
    def _select_columns(frame: pl.DataFrame, columns: Sequence[str] | None) -> pl.DataFrame:
        if columns is None:
            return frame
        requested = tuple(columns)
        unknown = sorted(set(requested).difference(RESEARCH_SECURITY_DAILY_FIELDS))
        if unknown:
            raise ResearchReaderError(f"unknown research fields requested: {unknown}")
        if len(set(requested)) != len(requested):
            raise ResearchReaderError("research field selection contains duplicates")
        return frame.select(list(requested))


def load_research_security_daily(
    manifest_path: str | Path,
    *,
    split: ResearchSplit | str,
    start: date | str | None = None,
    end: date | str | None = None,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Load a selected, verified R1 split; ``split`` is intentionally required."""
    return ResearchPanelReader.from_manifest(manifest_path).load_security_daily(
        split=split,
        start=start,
        end=end,
        columns=columns,
    )


def load_disabled_research_security_daily(
    manifest_path: str | Path,
    *,
    columns: Sequence[str] | None = None,
) -> pl.DataFrame:
    """Load preserved disabled rows only for explicit diagnostics."""
    return ResearchPanelReader.from_manifest(manifest_path).load_disabled_security_daily(
        columns=columns
    )
