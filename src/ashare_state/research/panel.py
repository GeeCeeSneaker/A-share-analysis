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

from ashare_state.canonical.verifier import (
    CanonicalConsumptionError,
    verify_canonical_run_for_consumption,
)
from ashare_state.identity import resolve_security_identity
from ashare_state.readmodel import (
    READMODEL_CONTRACT_VERSION,
    DuckDBReadModel,
    ReadModelError,
    duckdb_domain_columns,
)
from ashare_state.research.eligibility import evaluate_daily_bar
from ashare_state.research.models import (
    AUTHORITATIVE_READMODEL_PUBLICATION,
    INDEX_PANEL_STATE,
    PRICE_BASIS,
    RESEARCH_CONTRACT_VERSION,
    RESEARCH_DATASET_VERSION,
    RESEARCH_SECURITY_DAILY_DATASET,
    RESEARCH_SECURITY_DAILY_FIXTURE_DATASET,
    RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
    TEST_ONLY_ROWS_PUBLICATION,
    UNIVERSE_BASIS,
    VERIFIED_SECURITY_MASTER_SOURCE,
    ArtifactMetadata,
    CoverageState,
    IdentityRecord,
    IdentitySource,
    IdentityView,
    ResearchEligibility,
    ResearchManifest,
    ResearchPanelError,
    ResearchSplit,
    canonical_json,
    ensure_utc_timestamp,
    parse_date_value,
    research_code_fingerprint,
    research_security_daily_schema,
    sha256_hex,
)
from ashare_state.research.splits import assign_research_split
from ashare_state.snapshot import verify_snapshot
from ashare_state.storage.atomic_files import write_file_atomic
from ashare_state.storage.paths import physical_from_logical_uri

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
_IDENTITY_SUFFIX_TO_EXCHANGE = {".SH": "SSE", ".SZ": "SZSE", ".BJ": "BSE"}


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
        build_timestamp: datetime | str,
        coverage_state: CoverageState | str = CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
    ) -> ResearchBuildResult:
        """Read one hash-verified ReadModel snapshot and publish R1 artifacts.

        The identity join is derived from the verified canonical run's sealed
        ``security_master`` output.  Callers cannot inject display identity
        rows into the authoritative publication path.
        """
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
        try:
            verified_canonical = verify_canonical_run_for_consumption(
                self.conn,
                canonical_run_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
        except CanonicalConsumptionError as exc:
            raise ResearchPanelError(
                f"canonical run {canonical_run_id} is not a verified identity source: {exc}"
            ) from exc
        if verified_canonical.as_of != verified_snapshot.as_of:
            raise ResearchPanelError("ReadModel and canonical run as_of values do not match")
        identity_view = self._identity_view_from_verified_canonical(verified_canonical)
        record = verified_snapshot.ledger_record
        try:
            coverage = CoverageState(coverage_state)
        except ValueError as exc:
            raise ResearchPanelError(f"unknown coverage_state {coverage_state!r}") from exc
        built_at = ensure_utc_timestamp(build_timestamp)
        projected = self._project_rows(
            rows,
            source_snapshot_id=snapshot_id,
            source_snapshot_as_of=verified_snapshot.as_of,
            source_canonical_run_id=canonical_run_id,
            source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
            identity_view=identity_view,
        )
        return self._publish(
            projected,
            source_snapshot_id=snapshot_id,
            source_snapshot_as_of=verified_snapshot.as_of,
            source_canonical_run_id=canonical_run_id,
            source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
            source_snapshot_manifest_hash=str(record["manifest_hash"]),
            source_snapshot_semantic_hash=str(record["snapshot_semantic_hash"]),
            identity_view=identity_view,
            build_timestamp=built_at,
            coverage_state=coverage,
            publication_mode=AUTHORITATIVE_READMODEL_PUBLICATION,
        )

    def _build_fixture_from_rows(
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
        """Build a visibly test-only fixture from caller-supplied rows.

        This private helper is intentionally not an authoritative publisher.
        Its manifest uses ``TEST_ONLY_ROWS`` and a distinct dataset name that
        the ordinary R1 reader rejects.  Authoritative publication is only
        reachable through ``build_from_readmodel``.
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
            publication_mode=TEST_ONLY_ROWS_PUBLICATION,
        )

    def _identity_view_from_verified_canonical(self, canonical: Any) -> IdentityView:
        """Materialize identity only from verified CR-2 security-master outputs."""
        entries = canonical.manifest.get("input_normalized_runs")
        if not isinstance(entries, list):
            raise ResearchPanelError("verified canonical manifest has no input lineage")
        records_by_key: dict[tuple[str, date, str, str], IdentityRecord] = {}
        sources: list[IdentitySource] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ResearchPanelError("verified canonical input lineage is malformed")
            if entry.get("role") != "identity_master":
                continue
            if entry.get("normalization_surface") != "security_master":
                continue
            if entry.get("verification") != "HEALTHY" or entry.get("pit_available") is not True:
                continue
            source, rows = self._read_verified_identity_output(
                entry,
                canonical_run_id=canonical.canonical_run_id,
                canonical_as_of=canonical.as_of,
            )
            sources.append(source)
            for ordinal, row in enumerate(rows):
                record = self._identity_record_from_master_row(row, ordinal=ordinal)
                if record is None:
                    continue
                key = (record.security_id, record.valid_from, record.symbol, record.exchange)
                existing = records_by_key.get(key)
                if existing is not None and existing != record:
                    raise ResearchPanelError(
                        "verified identity sources disagree for "
                        f"{record.security_id} at {record.valid_from}"
                    )
                records_by_key[key] = record
        if not sources:
            return IdentityView._without_verified_source()  # noqa: SLF001 - fail-closed state
        return IdentityView._from_verified_security_master(  # noqa: SLF001 - verified boundary
            tuple(records_by_key.values()),
            sources=tuple(sources),
        )

    def _read_verified_identity_output(
        self,
        entry: Mapping[str, Any],
        *,
        canonical_run_id: str,
        canonical_as_of: datetime,
    ) -> tuple[IdentitySource, list[dict[str, Any]]]:
        """Read the exact bytes already verified by the canonical consumer."""
        try:
            manifest_uri = str(entry["normalized_manifest_uri"])
            manifest_hash = str(entry["normalized_manifest_hash"])
            manifest_path = physical_from_logical_uri(self.normalized_root, manifest_uri)
            if not manifest_path.is_file():
                raise ResearchPanelError(f"identity source manifest is missing: {manifest_uri}")
            manifest_bytes = manifest_path.read_bytes()
            if sha256_hex(manifest_bytes) != manifest_hash:
                raise ResearchPanelError("identity source manifest hash changed after verification")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, Mapping):
                raise ResearchPanelError("identity source manifest root is not an object")
            outputs = manifest.get("outputs")
            if not isinstance(outputs, list):
                raise ResearchPanelError("identity source manifest has no output list")
            if any(not isinstance(output, Mapping) for output in outputs):
                raise ResearchPanelError("identity source output metadata is malformed")
            main_outputs = [output for output in outputs if output.get("output_name") == "main"]
            if len(main_outputs) != 1:
                raise ResearchPanelError("identity source must have exactly one main output")
            output = main_outputs[0]
            output_uri = str(output["uri"])
            output_path = physical_from_logical_uri(self.normalized_root, output_uri)
            if not output_path.is_file():
                raise ResearchPanelError(f"identity source output is missing: {output_uri}")
            output_bytes = output_path.read_bytes()
            output_hash = sha256_hex(output_bytes)
            if output_hash != str(output["content_hash"]):
                raise ResearchPanelError("identity source output hash changed after verification")
            frame = pl.read_parquet(io.BytesIO(output_bytes))
            output_schema_hash = sha256_hex(str(frame.schema))
            if output_schema_hash != str(output["schema_hash"]):
                raise ResearchPanelError("identity source output schema changed after verification")
            if frame.height != int(output["row_count"]):
                raise ResearchPanelError(
                    "identity source output row count changed after verification"
                )
            source = IdentitySource.from_mapping(
                {
                    "source_kind": VERIFIED_SECURITY_MASTER_SOURCE,
                    "canonical_run_id": canonical_run_id,
                    "canonical_as_of": canonical_as_of.isoformat(),
                    "normalization_run_id": str(entry["run_id"]),
                    "provider": str(entry["provider"]),
                    "normalization_surface": str(entry["normalization_surface"]),
                    "provider_dataset": str(entry["provider_dataset"]),
                    "endpoint": str(entry["endpoint"]),
                    "normalized_manifest_uri": manifest_uri,
                    "normalized_manifest_hash": manifest_hash,
                    "normalized_output_name": "main",
                    "normalized_output_uri": output_uri,
                    "normalized_output_hash": output_hash,
                    "normalized_output_schema_hash": output_schema_hash,
                    "normalized_output_row_count": frame.height,
                    "normalized_output_set_hash": str(entry["normalized_output_set_hash"]),
                    "normalized_semantic_hash": str(entry["normalized_semantic_hash"]),
                    "verification": "HEALTHY",
                    "pit_available": True,
                }
            )
            return source, frame.to_dicts()
        except ResearchPanelError:
            raise
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
            raise ResearchPanelError(f"identity source output is malformed: {exc}") from exc

    @staticmethod
    def _identity_record_from_master_row(
        row: Mapping[str, Any], *, ordinal: int
    ) -> IdentityRecord | None:
        provider_symbol = row.get("provider_symbol")
        if provider_symbol is None or not isinstance(provider_symbol, str):
            raise ResearchPanelError(f"verified identity row {ordinal} has no provider_symbol")
        provider_symbol = provider_symbol.strip().upper()
        if "." not in provider_symbol:
            raise ResearchPanelError(
                f"verified identity row {ordinal} has no exchange suffix; identity is disabled"
            )
        symbol, suffix = provider_symbol.rsplit(".", 1)
        suffix = f".{suffix}"
        exchange = _IDENTITY_SUFFIX_TO_EXCHANGE.get(suffix)
        if exchange is None:
            raise ResearchPanelError(
                f"verified identity row {ordinal} has an unknown exchange suffix"
            )
        raw_list_date = row.get("list_date")
        if raw_list_date is None:
            # Match the existing governed bridge: no list date cannot produce
            # a publishable identity; the corresponding bar remains unresolved.
            return None
        list_date = parse_date_value(raw_list_date)
        resolved = resolve_security_identity(exchange, "STOCK", symbol, list_date)
        return IdentityRecord(
            security_id=str(resolved.security_id),
            symbol=symbol,
            exchange=exchange,
            valid_from=list_date,
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
        publication_mode: str = AUTHORITATIVE_READMODEL_PUBLICATION,
    ) -> ResearchBuildResult:
        if publication_mode == AUTHORITATIVE_READMODEL_PUBLICATION:
            if not identity_view.can_publish_authoritatively:
                raise ResearchPanelError(
                    "authoritative R1 publication requires a verified identity source or "
                    "an explicit no-source disabled view"
                )
            dataset_name = RESEARCH_SECURITY_DAILY_DATASET
        elif publication_mode == TEST_ONLY_ROWS_PUBLICATION:
            dataset_name = RESEARCH_SECURITY_DAILY_FIXTURE_DATASET
        else:
            raise ResearchPanelError(f"unsupported research publication_mode {publication_mode!r}")
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
            "publication_mode": publication_mode,
            "dataset_name": dataset_name,
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
            "identity_source_kind": identity_view.source_kind,
            "identity_source_lineage_hash": identity_view.source_lineage_hash,
            "price_basis": PRICE_BASIS,
            "universe_basis": UNIVERSE_BASIS,
            "config_hash": config_hash,
        }
        dataset_id = f"rsd-{sha256_hex(canonical_json(build_identity))[:32]}"
        base_dir = (
            Path("research")
            / f"contract={RESEARCH_CONTRACT_VERSION}"
            / f"dataset={dataset_name}"
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
            dataset_name=dataset_name,
            publication_mode=publication_mode,
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
            identity_source_kind=identity_view.source_kind,
            identity_source_lineage_hash=identity_view.source_lineage_hash,
            identity_sources=identity_view.sources,
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
