"""CR-7 R1 research-panel contracts and immutable manifest models.

This module is deliberately independent of Provider and Raw layers.  The
builder consumes an already verified ReadModel, and this module only defines
the contract that makes the resulting research artefact safe to consume.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

import polars as pl

__all__ = [
    "CoverageState",
    "DataQualityState",
    "ExclusionReason",
    "IdentityRecord",
    "IdentityView",
    "INDEX_PANEL_STATE",
    "IndexPanelState",
    "PRICE_BASIS",
    "RESEARCH_CONTRACT_VERSION",
    "RESEARCH_DATASET_VERSION",
    "RESEARCH_SECURITY_DAILY_DATASET",
    "RESEARCH_SECURITY_DAILY_FIELDS",
    "RESEARCH_SECURITY_DAILY_SCHEMA_VERSION",
    "ResearchEligibility",
    "ResearchManifest",
    "ResearchManifestError",
    "ResearchPanelError",
    "ResearchReaderError",
    "ResearchSplit",
    "UNIVERSE_BASIS",
    "canonical_json",
    "ensure_utc_timestamp",
    "parse_date_value",
    "research_code_fingerprint",
    "research_security_daily_schema",
    "sha256_hex",
    "split_windows",
    "validate_manifest_semantics",
]


RESEARCH_CONTRACT_VERSION = "research-v1"
RESEARCH_SECURITY_DAILY_DATASET = "research_security_daily"
RESEARCH_DATASET_VERSION = "research-security-daily-v1"
RESEARCH_SECURITY_DAILY_SCHEMA_VERSION = "research-security-daily-v1"

# These are contract values, not display labels.  Do not broaden them in a
# reader: changing either semantic requires a new research contract/version.
PRICE_BASIS = "UNADJUSTED_CANONICAL"
UNIVERSE_BASIS = "OBSERVED_DAILY_BAR_UNIVERSE"


class ResearchPanelError(RuntimeError):
    """A research panel cannot be built from a verified, coherent input."""


class ResearchManifestError(ResearchPanelError):
    """A research manifest is missing, malformed, or semantically unsafe."""


class ResearchReaderError(ResearchManifestError):
    """A published research artefact fails read-time integrity checks."""


class ResearchEligibility(StrEnum):
    ENABLED = "RESEARCH_ENABLED"
    DISABLED_UNRESOLVED = "RESEARCH_DISABLED_UNRESOLVED"
    EXPERIMENTAL = "RESEARCH_EXPERIMENTAL"


class ResearchSplit(StrEnum):
    DEVELOPMENT = "development"
    VALIDATION_A = "validation_a"
    HOLDOUT = "holdout"
    WARMUP = "warmup"
    OUTSIDE_WINDOW = "outside_window"


class CoverageState(StrEnum):
    OBSERVED_DAILY_BAR_COVERAGE = "OBSERVED_DAILY_BAR_COVERAGE"
    PARTIAL_OBSERVED_DAILY_BAR_COVERAGE = "PARTIAL_OBSERVED_DAILY_BAR_COVERAGE"
    UNRESOLVED_NOT_FOR_RESEARCH = "UNRESOLVED_NOT_FOR_RESEARCH"


class IndexPanelState(StrEnum):
    DISABLED_UNVERIFIED_INDEX_IDENTITY = "DISABLED_UNVERIFIED_INDEX_IDENTITY"


INDEX_PANEL_STATE = IndexPanelState.DISABLED_UNVERIFIED_INDEX_IDENTITY.value


class ExclusionReason(StrEnum):
    OUTSIDE_RESEARCH_WINDOW = "outside_research_window"
    IDENTITY_UNRESOLVED = "identity_unresolved"
    IDENTITY_CONFLICT = "identity_conflict"
    UPSTREAM_UNRESOLVED = "upstream_unresolved"
    MISSING_REQUIRED_VALUE = "missing_required_value"
    NON_FINITE_VALUE = "non_finite_value"
    INVALID_OHLC = "invalid_ohlc"


class DataQualityState(StrEnum):
    VERIFIED = "VERIFIED"
    UNRESOLVED = "UNRESOLVED"
    INVALID = "INVALID"


RESEARCH_SECURITY_DAILY_FIELDS: tuple[str, ...] = (
    "trade_date",
    "security_id",
    "symbol",
    "exchange",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "research_split",
    "research_eligibility",
    "research_exclusion_reason",
    "data_quality_state",
    "available_at",
    "source_snapshot_id",
    "source_readmodel_contract_version",
    "source_canonical_run_id",
    "source_canonical_domain",
    "source_canonical_key",
    "source_row_identity_hash",
    "identity_view_version",
    "identity_view_hash",
)


def research_security_daily_schema() -> pl.Schema:
    """Return the one physical schema used by every R1 security artifact."""
    return pl.Schema(
        [
            ("trade_date", pl.Date()),
            ("security_id", pl.String()),
            ("symbol", pl.String()),
            ("exchange", pl.String()),
            ("open", pl.Float64()),
            ("high", pl.Float64()),
            ("low", pl.Float64()),
            ("close", pl.Float64()),
            ("pre_close", pl.Float64()),
            ("volume", pl.Float64()),
            ("amount", pl.Float64()),
            ("research_split", pl.String()),
            ("research_eligibility", pl.String()),
            ("research_exclusion_reason", pl.String()),
            ("data_quality_state", pl.String()),
            ("available_at", pl.Datetime(time_unit="us", time_zone="UTC")),
            ("source_snapshot_id", pl.String()),
            ("source_readmodel_contract_version", pl.String()),
            ("source_canonical_run_id", pl.String()),
            ("source_canonical_domain", pl.String()),
            ("source_canonical_key", pl.String()),
            ("source_row_identity_hash", pl.String()),
            ("identity_view_version", pl.String()),
            ("identity_view_hash", pl.String()),
        ]
    )


_SPLIT_WINDOWS: dict[ResearchSplit, tuple[date, date]] = {
    ResearchSplit.DEVELOPMENT: (date(2020, 1, 1), date(2023, 12, 31)),
    ResearchSplit.VALIDATION_A: (date(2024, 1, 1), date(2025, 12, 31)),
    ResearchSplit.HOLDOUT: (date(2026, 1, 1), date(2026, 6, 30)),
}


def split_windows() -> dict[ResearchSplit, tuple[date, date]]:
    """Return a copy of the inclusive R1 split boundaries."""
    return dict(_SPLIT_WINDOWS)


def parse_date_value(value: date | datetime | str) -> date:
    """Parse a date-like value without changing its calendar day."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ResearchPanelError(f"invalid ISO date {value!r}") from exc
    raise ResearchPanelError(f"expected date-like value, got {type(value).__name__}")


def ensure_utc_timestamp(value: datetime | str) -> datetime:
    """Return an aware UTC instant; naive timestamps fail closed."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResearchPanelError(f"invalid ISO timestamp {value!r}") from exc
    if value.tzinfo is None:
        raise ResearchPanelError("available_at/build_timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        return ensure_utc_timestamp(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float cannot enter deterministic JSON")
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize contract values with deterministic key and time handling."""
    return json.dumps(
        _json_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_hex(data: bytes | str) -> str:
    """Return a lower-case SHA-256 digest."""
    payload = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class IdentityRecord:
    """One versioned point-in-time identity mapping.

    ``valid_to`` is exclusive, matching the existing identity bridge
    convention.  The research layer never derives symbol/exchange from a
    UUID; it only consumes this explicit, versioned join artifact.
    """

    security_id: str
    symbol: str
    exchange: str
    valid_from: date
    valid_to: date | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "security_id": self.security_id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
        }


@dataclass(frozen=True)
class IdentityView:
    """Immutable version/hash wrapper around identity join rows."""

    version: str
    content_hash: str
    records: tuple[IdentityRecord, ...]

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Mapping[str, Any]],
        *,
        version: str,
    ) -> IdentityView:
        if not version.strip():
            raise ResearchPanelError("identity view version must not be empty")
        records: list[IdentityRecord] = []
        for ordinal, row in enumerate(rows):
            try:
                raw_security_id = row["security_id"]
                raw_symbol = row["symbol"]
                raw_exchange = row["exchange"]
                if not all(
                    isinstance(value, str) and value.strip()
                    for value in (raw_security_id, raw_symbol, raw_exchange)
                ):
                    raise TypeError("security_id/symbol/exchange must be non-empty strings")
                security_id = raw_security_id.strip()
                symbol = raw_symbol.strip()
                exchange = raw_exchange.strip().upper()
                valid_from = parse_date_value(row["valid_from"])
                raw_valid_to = row.get("valid_to")
                valid_to = None if raw_valid_to is None else parse_date_value(raw_valid_to)
            except (KeyError, TypeError, ResearchPanelError) as exc:
                raise ResearchPanelError(
                    f"identity view row {ordinal} is malformed: {exc}"
                ) from exc
            if not security_id or not symbol or exchange not in {"SSE", "SZSE", "BSE"}:
                raise ResearchPanelError(
                    f"identity view row {ordinal} has invalid security identity"
                )
            if valid_to is not None and valid_to <= valid_from:
                raise ResearchPanelError(
                    f"identity view row {ordinal} has non-positive validity interval"
                )
            records.append(
                IdentityRecord(
                    security_id=security_id,
                    symbol=symbol,
                    exchange=exchange,
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
            )

        records.sort(
            key=lambda record: (
                record.security_id,
                record.valid_from,
                record.valid_to or date.max,
                record.symbol,
                record.exchange,
            )
        )
        for previous, current in zip(records, records[1:], strict=False):
            if previous.security_id != current.security_id:
                continue
            if previous.valid_to is None or current.valid_from < previous.valid_to:
                raise ResearchPanelError(
                    "identity view contains overlapping validity intervals for "
                    f"security_id {current.security_id}"
                )
        content_hash = sha256_hex(canonical_json([record.as_dict() for record in records]))
        return cls(version=version.strip(), content_hash=content_hash, records=tuple(records))

    def resolve(self, security_id: str, trade_date: date) -> IdentityRecord | None:
        """Resolve exactly one identity at a date, or return unresolved."""
        matches = [
            record
            for record in self.records
            if record.security_id == security_id
            and record.valid_from <= trade_date
            and (record.valid_to is None or trade_date < record.valid_to)
        ]
        if len(matches) > 1:  # defensive: construction already rejects overlap
            raise ResearchPanelError(
                f"identity view resolves more than one row for {security_id} on {trade_date}"
            )
        return matches[0] if matches else None


@dataclass(frozen=True)
class ArtifactMetadata:
    name: str
    uri: str
    split: str
    research_eligible: bool
    content_hash: str
    semantic_hash: str
    schema_hash: str
    row_count: int
    byte_size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "split": self.split,
            "research_eligible": self.research_eligible,
            "content_hash": self.content_hash,
            "semantic_hash": self.semantic_hash,
            "schema_hash": self.schema_hash,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True)
class ResearchManifest:
    """Typed view of the immutable R1 manifest."""

    dataset_name: str
    research_contract_version: str
    research_dataset_version: str
    dataset_id: str
    manifest_uri: str
    build_code_fingerprint: str
    schema_version: str
    schema_hash: str
    source_snapshot_id: str
    source_snapshot_as_of: str
    source_snapshot_manifest_hash: str
    source_snapshot_semantic_hash: str
    source_canonical_run_id: str
    source_readmodel_contract_version: str
    identity_view_version: str
    identity_view_hash: str
    feature_run_id: str | None
    feature_registry_version: str | None
    price_basis: str
    universe_basis: str
    coverage_state: str
    index_panel_state: str
    build_timestamp: str
    config_hash: str
    content_hash: str
    artifact_set_hash: str
    enabled_row_count: int
    disabled_row_count: int
    default_read_splits: tuple[str, ...]
    artifacts: tuple[ArtifactMetadata, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ResearchManifest:
        validate_manifest_semantics(payload)
        try:
            artifact_payload = payload["artifacts"]
            if not isinstance(artifact_payload, Mapping):
                raise TypeError("artifacts must be an object")
            artifacts = tuple(
                ArtifactMetadata(
                    name=str(name),
                    uri=str(value["uri"]),
                    split=str(value["split"]),
                    research_eligible=bool(value["research_eligible"]),
                    content_hash=str(value["content_hash"]),
                    semantic_hash=str(value["semantic_hash"]),
                    schema_hash=str(value["schema_hash"]),
                    row_count=int(value["row_count"]),
                    byte_size=int(value["byte_size"]),
                )
                for name, value in sorted(artifact_payload.items())
            )
            build_timestamp = ensure_utc_timestamp(str(payload["build_timestamp"])).isoformat()
            default_read_splits = tuple(str(item) for item in payload["default_read_splits"])
            result = cls(
                dataset_name=str(payload["dataset_name"]),
                research_contract_version=str(payload["research_contract_version"]),
                research_dataset_version=str(payload["research_dataset_version"]),
                dataset_id=str(payload["dataset_id"]),
                manifest_uri=str(payload["manifest_uri"]),
                build_code_fingerprint=str(payload["build_code_fingerprint"]),
                schema_version=str(payload["schema_version"]),
                schema_hash=str(payload["schema_hash"]),
                source_snapshot_id=str(payload["source_snapshot_id"]),
                source_snapshot_as_of=ensure_utc_timestamp(
                    str(payload["source_snapshot_as_of"])
                ).isoformat(),
                source_snapshot_manifest_hash=str(payload["source_snapshot_manifest_hash"]),
                source_snapshot_semantic_hash=str(payload["source_snapshot_semantic_hash"]),
                source_canonical_run_id=str(payload["source_canonical_run_id"]),
                source_readmodel_contract_version=str(payload["source_readmodel_contract_version"]),
                identity_view_version=str(payload["identity_view_version"]),
                identity_view_hash=str(payload["identity_view_hash"]),
                feature_run_id=(
                    None
                    if payload.get("feature_run_id") is None
                    else str(payload["feature_run_id"])
                ),
                feature_registry_version=(
                    None
                    if payload.get("feature_registry_version") is None
                    else str(payload["feature_registry_version"])
                ),
                price_basis=str(payload["price_basis"]),
                universe_basis=str(payload["universe_basis"]),
                coverage_state=str(payload["coverage_state"]),
                index_panel_state=str(payload["index_panel_state"]),
                build_timestamp=build_timestamp,
                config_hash=str(payload["config_hash"]),
                content_hash=str(payload["content_hash"]),
                artifact_set_hash=str(payload["artifact_set_hash"]),
                enabled_row_count=int(payload["enabled_row_count"]),
                disabled_row_count=int(payload["disabled_row_count"]),
                default_read_splits=default_read_splits,
                artifacts=artifacts,
            )
        except (KeyError, TypeError, ValueError, ResearchPanelError) as exc:
            if isinstance(exc, ResearchManifestError):
                raise
            raise ResearchManifestError(f"malformed research manifest: {exc}") from exc
        _validate_manifest_shape(result)
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "research_contract_version": self.research_contract_version,
            "research_dataset_version": self.research_dataset_version,
            "dataset_id": self.dataset_id,
            "manifest_uri": self.manifest_uri,
            "build_code_fingerprint": self.build_code_fingerprint,
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_as_of": self.source_snapshot_as_of,
            "source_snapshot_manifest_hash": self.source_snapshot_manifest_hash,
            "source_snapshot_semantic_hash": self.source_snapshot_semantic_hash,
            "source_canonical_run_id": self.source_canonical_run_id,
            "source_readmodel_contract_version": self.source_readmodel_contract_version,
            "identity_view_version": self.identity_view_version,
            "identity_view_hash": self.identity_view_hash,
            "feature_run_id": self.feature_run_id,
            "feature_registry_version": self.feature_registry_version,
            "price_basis": self.price_basis,
            "universe_basis": self.universe_basis,
            "coverage_state": self.coverage_state,
            "index_panel_state": self.index_panel_state,
            "build_timestamp": self.build_timestamp,
            "config_hash": self.config_hash,
            "content_hash": self.content_hash,
            "artifact_set_hash": self.artifact_set_hash,
            "enabled_row_count": self.enabled_row_count,
            "disabled_row_count": self.disabled_row_count,
            "default_read_splits": list(self.default_read_splits),
            "artifacts": {artifact.name: artifact.as_dict() for artifact in self.artifacts},
        }

    def artifact(self, name: str) -> ArtifactMetadata:
        for artifact in self.artifacts:
            if artifact.name == name:
                return artifact
        raise ResearchManifestError(f"manifest has no artifact {name!r}")


def validate_manifest_semantics(
    payload: Mapping[str, Any],
    *,
    allow_non_observed_coverage: bool = True,
) -> None:
    """Reject semantic widening before any research rows are returned."""
    required = {
        "dataset_name",
        "research_contract_version",
        "research_dataset_version",
        "dataset_id",
        "manifest_uri",
        "build_code_fingerprint",
        "schema_version",
        "schema_hash",
        "source_snapshot_id",
        "source_snapshot_as_of",
        "source_snapshot_manifest_hash",
        "source_snapshot_semantic_hash",
        "source_canonical_run_id",
        "source_readmodel_contract_version",
        "identity_view_version",
        "identity_view_hash",
        "feature_run_id",
        "feature_registry_version",
        "price_basis",
        "universe_basis",
        "coverage_state",
        "index_panel_state",
        "build_timestamp",
        "config_hash",
        "content_hash",
        "artifact_set_hash",
        "enabled_row_count",
        "disabled_row_count",
        "default_read_splits",
        "artifacts",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ResearchManifestError(f"research manifest is missing fields: {missing}")
    if payload["dataset_name"] != RESEARCH_SECURITY_DAILY_DATASET:
        raise ResearchManifestError("R1 reader accepts only research_security_daily")
    if payload["research_contract_version"] != RESEARCH_CONTRACT_VERSION:
        raise ResearchManifestError("unsupported research contract version")
    if payload["research_dataset_version"] != RESEARCH_DATASET_VERSION:
        raise ResearchManifestError("unsupported research dataset version")
    if payload["schema_version"] != RESEARCH_SECURITY_DAILY_SCHEMA_VERSION:
        raise ResearchManifestError("unsupported research security schema version")
    if payload["price_basis"] != PRICE_BASIS:
        raise ResearchManifestError(
            "research price_basis must remain UNADJUSTED_CANONICAL; adjusted or total-return "
            "semantics are not accepted"
        )
    if payload["universe_basis"] != UNIVERSE_BASIS:
        raise ResearchManifestError(
            "research universe_basis must remain OBSERVED_DAILY_BAR_UNIVERSE; "
            "ALL_A_SHARES is not accepted"
        )
    try:
        coverage = CoverageState(str(payload["coverage_state"]))
    except ValueError as exc:
        raise ResearchManifestError("unknown coverage_state") from exc
    if (
        not allow_non_observed_coverage
        and coverage is not CoverageState.OBSERVED_DAILY_BAR_COVERAGE
    ):
        raise ResearchReaderError(
            "default research loader refuses partial or unresolved coverage_state"
        )
    if payload["index_panel_state"] != INDEX_PANEL_STATE:
        raise ResearchManifestError(
            "research_index_daily cannot be enabled until index identity semantics are verified"
        )
    if (
        payload.get("feature_run_id") is not None
        or payload.get("feature_registry_version") is not None
    ):
        raise ResearchManifestError(
            "R1 does not expose CR-5 feature columns; feature lineage belongs to the "
            "R2 join contract"
        )


def _validate_manifest_shape(manifest: ResearchManifest) -> None:
    if manifest.default_read_splits != (
        ResearchSplit.DEVELOPMENT.value,
        ResearchSplit.VALIDATION_A.value,
        ResearchSplit.HOLDOUT.value,
    ):
        raise ResearchManifestError("default_read_splits must list the three explicit R1 splits")
    expected_names = {
        ResearchSplit.DEVELOPMENT.value,
        ResearchSplit.VALIDATION_A.value,
        ResearchSplit.HOLDOUT.value,
        "disabled",
    }
    actual_names = {artifact.name for artifact in manifest.artifacts}
    if actual_names != expected_names or len(manifest.artifacts) != len(expected_names):
        raise ResearchManifestError(
            f"research artifact set {sorted(actual_names)} != {sorted(expected_names)}"
        )
    if manifest.enabled_row_count < 0 or manifest.disabled_row_count < 0:
        raise ResearchManifestError("manifest row counts must be non-negative")
    for artifact in manifest.artifacts:
        if artifact.row_count < 0 or artifact.byte_size < 0:
            raise ResearchManifestError("artifact counts must be non-negative")
        if (
            len(artifact.content_hash) != 64
            or len(artifact.semantic_hash) != 64
            or len(artifact.schema_hash) != 64
        ):
            raise ResearchManifestError("artifact hashes must be SHA-256 hex")
        if artifact.name == "disabled":
            if artifact.research_eligible or artifact.split != "disabled":
                raise ResearchManifestError("disabled artifact has an unsafe declaration")
        elif not artifact.research_eligible or artifact.split != artifact.name:
            raise ResearchManifestError(
                f"enabled artifact {artifact.name} has an unsafe declaration"
            )


def research_code_fingerprint() -> str:
    """Hash the R1 implementation source, normalized across line endings."""
    digest = hashlib.sha256()
    package_dir = Path(__file__).parent
    for path in sorted(package_dir.glob("*.py")):
        source = path.read_bytes().decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()
