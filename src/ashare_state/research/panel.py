"""Build the CR-7 R1 security daily panel from a verified ReadModel."""

from __future__ import annotations

import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.readmodel import (
    READMODEL_CONTRACT_VERSION,
    DuckDBReadModel,
    ReadModelError,
    duckdb_domain_columns,
)
from ashare_state.research.eligibility import evaluate_daily_bar
from ashare_state.research.models import (
    INDEX_PANEL_STATE,
    PRICE_BASIS,
    RESEARCH_CONTRACT_VERSION,
    RESEARCH_DATASET_VERSION,
    RESEARCH_SECURITY_DAILY_DATASET,
    RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
    UNIVERSE_BASIS,
    ArtifactMetadata,
    CoverageState,
    IdentityView,
    ResearchEligibility,
    ResearchManifest,
    ResearchPanelError,
    ResearchSplit,
    canonical_json,
    ensure_utc_timestamp,
    research_code_fingerprint,
    research_security_daily_schema,
    sha256_hex,
)
from ashare_state.research.splits import assign_research_split
from ashare_state.snapshot import verify_snapshot
from ashare_state.storage.atomic_files import write_file_atomic

__all__ = ["ResearchBuildResult", "ResearchPanelBuilder"]


_NUMERIC_FIELDS = ("open", "high", "low", "close", "pre_close", "volume", "amount")
_REQUIRED_LINEAGE_FIELDS = (
    "canonical_domain",
    "canonical_key",
    "security_id",
    "trade_date",
    "available_at",
    "canonical_run_id",
    "snapshot_id",
    "source_row_identity_hash",
)
_ARTIFACT_NAMES = (
    ResearchSplit.DEVELOPMENT.value,
    ResearchSplit.VALIDATION_A.value,
    ResearchSplit.HOLDOUT.value,
    "disabled",
)


@dataclass(frozen=True)
class ResearchBuildResult:
    dataset_id: str
    manifest_uri: str
    manifest_hash: str
    content_hash: str
    enabled_row_count: int
    disabled_row_count: int
    idempotent_replay: bool


class ResearchPanelBuilder:
    """Thin R1 publisher with a verified ReadModel-only input boundary."""

    def __init__(
        self,
        conn: Any,
        *,
        raw_root: Path,
        normalized_root: Path,
        readmodel_root: Path | None = None,
        research_root: Path | None = None,
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
        self.readmodel_root = Path(readmodel_root) if readmodel_root else self.normalized_root
        self.research_root = Path(research_root) if research_root else self.normalized_root

    def build_from_readmodel(
        self,
        snapshot_id: str,
        *,
        identity_view: IdentityView,
        build_timestamp: datetime | str,
        coverage_state: CoverageState | str = CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
    ) -> ResearchBuildResult:
        """Read one hash-verified ReadModel snapshot and publish R1 artifacts."""
        model = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
            readmodel_root=self.readmodel_root,
        )
        try:
            db = model.open_read_only(snapshot_id)
        except ReadModelError as exc:
            raise ResearchPanelError(
                f"research input ReadModel {snapshot_id} is not consumable: {exc}"
            ) from exc

        try:
            meta_rows = db.execute(
                "SELECT snapshot_id, canonical_run_id, canonical_as_of, "
                "readmodel_contract_version FROM rm_snapshot_meta"
            ).fetchall()
            if len(meta_rows) != 1:
                raise ResearchPanelError("verified ReadModel metadata must contain exactly one row")
            meta = meta_rows[0]
            if str(meta[0]) != snapshot_id:
                raise ResearchPanelError("ReadModel snapshot_id does not match explicit input")
            if str(meta[3]) != READMODEL_CONTRACT_VERSION:
                raise ResearchPanelError("ReadModel contract version is not readmodel-v1")
            tables = {
                str(row[0])
                for row in db.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            }
            if "rm_daily_bar" not in tables:
                raise ResearchPanelError("R1 security panel requires rm_daily_bar")
            columns = tuple(duckdb_domain_columns("daily_bar"))
            fetched = db.execute(
                "SELECT "
                + ", ".join(columns)
                + " FROM rm_daily_bar ORDER BY security_id, trade_date, canonical_key"
            ).fetchall()
            rows = [dict(zip(columns, row, strict=True)) for row in fetched]
            canonical_run_id = str(meta[1])
        except ResearchPanelError:
            raise
        except Exception as exc:
            raise ResearchPanelError(
                f"verified ReadModel {snapshot_id} cannot provide typed daily bars: {exc}"
            ) from exc
        finally:
            db.close()

        try:
            verified_snapshot = verify_snapshot(
                self.conn,
                snapshot_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
        except Exception as exc:
            raise ResearchPanelError(
                f"snapshot {snapshot_id} verification metadata is unavailable: {exc}"
            ) from exc
        if canonical_run_id != verified_snapshot.canonical_run_id:
            raise ResearchPanelError("ReadModel canonical_run_id does not match its snapshot")
        record = verified_snapshot.ledger_record
        return self.build_from_verified_rows(
            rows,
            source_snapshot_id=snapshot_id,
            source_snapshot_as_of=verified_snapshot.as_of,
            source_canonical_run_id=canonical_run_id,
            source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
            source_snapshot_manifest_hash=str(record["manifest_hash"]),
            source_snapshot_semantic_hash=str(record["snapshot_semantic_hash"]),
            identity_view=identity_view,
            build_timestamp=build_timestamp,
            coverage_state=coverage_state,
        )

    def build_from_verified_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        source_snapshot_id: str,
        source_snapshot_as_of: datetime | str,
        source_canonical_run_id: str,
        source_readmodel_contract_version: str,
        source_snapshot_manifest_hash: str,
        source_snapshot_semantic_hash: str,
        identity_view: IdentityView,
        build_timestamp: datetime | str,
        coverage_state: CoverageState | str = CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
    ) -> ResearchBuildResult:
        """Publish from rows already obtained through the verified boundary.

        This method is useful for a fixed offline fixture, but callers must
        provide the same lineage fields that ``build_from_readmodel`` obtains.
        It does not accept Provider, Raw, or unversioned identity inputs.
        """
        if not source_snapshot_id or not source_canonical_run_id:
            raise ResearchPanelError("source snapshot and canonical run IDs are required")
        if source_readmodel_contract_version != READMODEL_CONTRACT_VERSION:
            raise ResearchPanelError("research input must use readmodel-v1")
        try:
            coverage = CoverageState(coverage_state)
        except ValueError as exc:
            raise ResearchPanelError(f"unknown coverage_state {coverage_state!r}") from exc
        built_at = ensure_utc_timestamp(build_timestamp)
        snapshot_as_of = ensure_utc_timestamp(source_snapshot_as_of)
        projected = self._project_rows(
            rows,
            source_snapshot_id=source_snapshot_id,
            source_snapshot_as_of=snapshot_as_of,
            source_canonical_run_id=source_canonical_run_id,
            source_readmodel_contract_version=source_readmodel_contract_version,
            identity_view=identity_view,
        )
        return self._publish(
            projected,
            source_snapshot_id=source_snapshot_id,
            source_snapshot_as_of=snapshot_as_of,
            source_canonical_run_id=source_canonical_run_id,
            source_readmodel_contract_version=source_readmodel_contract_version,
            source_snapshot_manifest_hash=source_snapshot_manifest_hash,
            source_snapshot_semantic_hash=source_snapshot_semantic_hash,
            identity_view=identity_view,
            build_timestamp=built_at,
            coverage_state=coverage,
        )

    @staticmethod
    def index_panel_status() -> str:
        """Expose the explicit R1 boundary: index daily is not enabled."""
        return INDEX_PANEL_STATE

    def _project_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        source_snapshot_id: str,
        source_snapshot_as_of: datetime,
        source_canonical_run_id: str,
        source_readmodel_contract_version: str,
        identity_view: IdentityView,
    ) -> list[dict[str, Any]]:
        projected: list[dict[str, Any]] = []
        seen_keys: set[tuple[date, str]] = set()
        for ordinal, source in enumerate(rows):
            self._validate_lineage(
                source,
                ordinal=ordinal,
                source_snapshot_id=source_snapshot_id,
                source_canonical_run_id=source_canonical_run_id,
            )
            trade_date = source["trade_date"]
            if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
                raise ResearchPanelError(f"daily bar row {ordinal} has an invalid trade_date")
            security_id = str(source["security_id"]).strip()
            key = (trade_date, security_id)
            if key in seen_keys:
                raise ResearchPanelError(
                    "duplicate research primary key "
                    f"trade_date={trade_date} security_id={security_id}"
                )
            seen_keys.add(key)
            available_at = ensure_utc_timestamp(source["available_at"])
            if available_at > source_snapshot_as_of:
                raise ResearchPanelError(
                    "daily bar available_at is after the source snapshot as_of; PIT read blocked"
                )
            identity = identity_view.resolve(security_id, trade_date)
            identity_conflict = self._identity_conflict(source, identity)
            split = assign_research_split(trade_date)
            decision = evaluate_daily_bar(
                source,
                split=split,
                identity=identity,
                identity_conflict=identity_conflict,
            )
            numeric = {
                field: self._number(source.get(field), field=field, ordinal=ordinal)
                for field in _NUMERIC_FIELDS
            }
            projected.append(
                {
                    "trade_date": trade_date,
                    "security_id": security_id,
                    "symbol": identity.symbol if identity else None,
                    "exchange": identity.exchange if identity else None,
                    **numeric,
                    "research_split": split.value,
                    "research_eligibility": decision.eligibility.value,
                    "research_exclusion_reason": (
                        decision.exclusion_reason.value if decision.exclusion_reason else None
                    ),
                    "data_quality_state": decision.data_quality_state.value,
                    "available_at": available_at,
                    "source_snapshot_id": source_snapshot_id,
                    "source_readmodel_contract_version": source_readmodel_contract_version,
                    "source_canonical_run_id": source_canonical_run_id,
                    "source_canonical_domain": str(source["canonical_domain"]),
                    "source_canonical_key": str(source["canonical_key"]),
                    "source_row_identity_hash": str(source["source_row_identity_hash"]),
                    "identity_view_version": identity_view.version,
                    "identity_view_hash": identity_view.content_hash,
                }
            )
        return projected

    @staticmethod
    def _validate_lineage(
        source: Mapping[str, Any],
        *,
        ordinal: int,
        source_snapshot_id: str,
        source_canonical_run_id: str,
    ) -> None:
        missing = [field for field in _REQUIRED_LINEAGE_FIELDS if field not in source]
        if missing:
            raise ResearchPanelError(f"daily bar row {ordinal} lacks lineage fields {missing}")
        for field in (
            "canonical_domain",
            "canonical_key",
            "security_id",
            "canonical_run_id",
            "snapshot_id",
            "source_row_identity_hash",
        ):
            if not isinstance(source[field], str) or not source[field].strip():
                raise ResearchPanelError(
                    f"daily bar row {ordinal} field {field} is not a non-empty string"
                )
        if source["canonical_domain"] != "daily_bar":
            raise ResearchPanelError(
                "research security panel accepts only canonical daily_bar rows"
            )
        if str(source["snapshot_id"]) != source_snapshot_id:
            raise ResearchPanelError(
                "daily bar row snapshot_id does not match the explicit snapshot"
            )
        if str(source["canonical_run_id"]) != source_canonical_run_id:
            raise ResearchPanelError(
                "daily bar row canonical_run_id does not match the explicit source run"
            )

    @staticmethod
    def _number(value: Any, *, field: str, ordinal: int) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ResearchPanelError(
                f"daily bar row {ordinal} field {field} is not a typed numeric value"
            )
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ResearchPanelError(
                f"daily bar row {ordinal} field {field} is non-finite; source remains blocked"
            )
        return numeric

    @staticmethod
    def _identity_conflict(source: Mapping[str, Any], identity: Any) -> bool:
        if identity is None:
            return False
        source_symbol = source.get("symbol")
        source_exchange = source.get("exchange")
        return (source_symbol is not None and str(source_symbol).strip() != identity.symbol) or (
            source_exchange is not None
            and str(source_exchange).strip().upper() != identity.exchange
        )

    def _publish(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        source_snapshot_id: str,
        source_snapshot_as_of: datetime,
        source_canonical_run_id: str,
        source_readmodel_contract_version: str,
        source_snapshot_manifest_hash: str,
        source_snapshot_semantic_hash: str,
        identity_view: IdentityView,
        build_timestamp: datetime,
        coverage_state: CoverageState,
    ) -> ResearchBuildResult:
        code_fingerprint = research_code_fingerprint()
        schema = research_security_daily_schema()
        schema_descriptor = [(name, str(schema[name])) for name in schema]
        schema_hash = sha256_hex(canonical_json(schema_descriptor))
        config = {
            "coverage_state": coverage_state.value,
            "default_read_splits": list(_ARTIFACT_NAMES[:3]),
            "feature_run_id": None,
            "feature_registry_version": None,
            "index_panel_state": INDEX_PANEL_STATE,
        }
        config_hash = sha256_hex(canonical_json(config))
        build_identity = {
            "research_contract_version": RESEARCH_CONTRACT_VERSION,
            "research_dataset_version": RESEARCH_DATASET_VERSION,
            "schema_version": RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
            "schema_hash": schema_hash,
            "build_code_fingerprint": code_fingerprint,
            "source_snapshot_id": source_snapshot_id,
            "source_snapshot_as_of": source_snapshot_as_of,
            "source_snapshot_manifest_hash": source_snapshot_manifest_hash,
            "source_snapshot_semantic_hash": source_snapshot_semantic_hash,
            "source_canonical_run_id": source_canonical_run_id,
            "source_readmodel_contract_version": source_readmodel_contract_version,
            "identity_view_version": identity_view.version,
            "identity_view_hash": identity_view.content_hash,
            "price_basis": PRICE_BASIS,
            "universe_basis": UNIVERSE_BASIS,
            "config_hash": config_hash,
        }
        dataset_id = f"rsd-{sha256_hex(canonical_json(build_identity))[:32]}"
        base_dir = (
            Path("research")
            / f"contract={RESEARCH_CONTRACT_VERSION}"
            / f"dataset={RESEARCH_SECURITY_DAILY_DATASET}"
            / f"version={RESEARCH_DATASET_VERSION}"
            / f"build={dataset_id}"
        )
        artifact_rows: dict[str, list[Mapping[str, Any]]] = {split: [] for split in _ARTIFACT_NAMES}
        for row in rows:
            name = (
                str(row["research_split"])
                if row["research_eligibility"] == ResearchEligibility.ENABLED.value
                else "disabled"
            )
            artifact_rows[name].append(row)
        for name in _ARTIFACT_NAMES:
            artifact_rows[name].sort(
                key=lambda row: (
                    str(row["trade_date"]),
                    str(row["security_id"]),
                    str(row["source_canonical_key"]),
                )
            )

        artifacts: list[ArtifactMetadata] = []
        artifact_payloads: dict[str, bytes] = {}
        for name in _ARTIFACT_NAMES:
            frame = pl.DataFrame(artifact_rows[name], schema=schema, strict=True)
            buffer = io.BytesIO()
            frame.write_parquet(buffer, compression="zstd", statistics=False)
            payload = buffer.getvalue()
            semantic_hash = sha256_hex(canonical_json(frame.to_dicts()))
            artifact = ArtifactMetadata(
                name=name,
                uri=str(base_dir / f"{name}.parquet").replace("\\", "/"),
                split=name,
                research_eligible=name != "disabled",
                content_hash=sha256_hex(payload),
                semantic_hash=semantic_hash,
                schema_hash=schema_hash,
                row_count=frame.height,
                byte_size=len(payload),
            )
            artifacts.append(artifact)
            artifact_payloads[name] = payload

        ordered_artifacts = tuple(sorted(artifacts, key=lambda artifact: artifact.name))
        content_hash = sha256_hex(
            canonical_json(
                {
                    "schema_hash": schema_hash,
                    "artifacts": [
                        {
                            "name": artifact.name,
                            "semantic_hash": artifact.semantic_hash,
                            "row_count": artifact.row_count,
                        }
                        for artifact in ordered_artifacts
                    ],
                }
            )
        )
        artifact_set_hash = sha256_hex(
            canonical_json(
                [artifact.as_dict() | {"name": artifact.name} for artifact in ordered_artifacts]
            )
        )
        manifest_uri = str(base_dir / "manifest.json").replace("\\", "/")
        enabled_count = sum(
            artifact.row_count for artifact in artifacts if artifact.research_eligible
        )
        disabled_count = next(
            artifact.row_count for artifact in artifacts if artifact.name == "disabled"
        )
        manifest = ResearchManifest(
            dataset_name=RESEARCH_SECURITY_DAILY_DATASET,
            research_contract_version=RESEARCH_CONTRACT_VERSION,
            research_dataset_version=RESEARCH_DATASET_VERSION,
            dataset_id=dataset_id,
            manifest_uri=manifest_uri,
            build_code_fingerprint=code_fingerprint,
            schema_version=RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
            schema_hash=schema_hash,
            source_snapshot_id=source_snapshot_id,
            source_snapshot_as_of=source_snapshot_as_of.isoformat(),
            source_snapshot_manifest_hash=source_snapshot_manifest_hash,
            source_snapshot_semantic_hash=source_snapshot_semantic_hash,
            source_canonical_run_id=source_canonical_run_id,
            source_readmodel_contract_version=source_readmodel_contract_version,
            identity_view_version=identity_view.version,
            identity_view_hash=identity_view.content_hash,
            feature_run_id=None,
            feature_registry_version=None,
            price_basis=PRICE_BASIS,
            universe_basis=UNIVERSE_BASIS,
            coverage_state=coverage_state.value,
            index_panel_state=INDEX_PANEL_STATE,
            build_timestamp=build_timestamp.isoformat(),
            config_hash=config_hash,
            content_hash=content_hash,
            artifact_set_hash=artifact_set_hash,
            enabled_row_count=enabled_count,
            disabled_row_count=disabled_count,
            default_read_splits=tuple(_ARTIFACT_NAMES[:3]),
            artifacts=ordered_artifacts,
        )
        manifest_bytes = json.dumps(
            manifest.as_dict(),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        manifest_path = self.research_root / manifest_uri
        idempotent_replay = True
        artifacts_by_name = {artifact.name: artifact for artifact in artifacts}
        for name in _ARTIFACT_NAMES:
            path = self.research_root / artifacts_by_name[name].uri
            before = path.is_file()
            write_file_atomic(path, artifact_payloads[name], allow_existing_identical=True)
            idempotent_replay = idempotent_replay and before
        before_manifest = manifest_path.is_file()
        write_file_atomic(manifest_path, manifest_bytes, allow_existing_identical=True)
        idempotent_replay = idempotent_replay and before_manifest
        return ResearchBuildResult(
            dataset_id=dataset_id,
            manifest_uri=manifest_uri,
            manifest_hash=sha256_hex(manifest_bytes),
            content_hash=content_hash,
            enabled_row_count=enabled_count,
            disabled_row_count=disabled_count,
            idempotent_replay=idempotent_replay,
        )
