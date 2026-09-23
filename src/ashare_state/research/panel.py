"""Build the CR-7 R1 security daily panel from a verified ReadModel."""

from __future__ import annotations

import hashlib
import io
import json
import math
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from ashare_state.canonical.identity import (
    approved_provider_identity_events,
    identity_event_for_provider_symbol,
)
from ashare_state.canonical.verifier import read_canonical_run_manifest
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
from ashare_state.research.splits import assign_research_split, split_window
from ashare_state.storage.atomic_files import commit_staged_file_atomic, write_file_atomic
from ashare_state.storage.paths import physical_from_logical_uri

__all__ = ["ResearchBuildResult", "ResearchPanelBuilder", "VerifiedResearchProjection"]


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


@dataclass(frozen=True)
class VerifiedResearchProjection:
    """Verified, non-publishing R1 projection handed to a later materializer.

    This object contains only in-memory rows and source provenance.  Creating
    it never writes an R1 artifact, manifest, publication marker, or pointer.
    The historical materializer can therefore validate coverage and construct
    its own staging transaction without crossing the ordinary R1 publication
    boundary.
    """

    rows: tuple[dict[str, Any], ...]
    source_snapshot_id: str
    source_snapshot_as_of: datetime
    source_canonical_run_id: str
    source_readmodel_contract_version: str
    source_snapshot_manifest_hash: str
    source_snapshot_semantic_hash: str
    identity_view: IdentityView


@dataclass(frozen=True)
class _VerifiedResearchContext:
    """Small verified source bindings used by the bounded R1 publisher."""

    source_snapshot_id: str
    source_snapshot_as_of: datetime
    source_canonical_run_id: str
    source_readmodel_contract_version: str
    source_snapshot_manifest_hash: str
    source_snapshot_semantic_hash: str
    identity_view: IdentityView


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
        projection = self._prepare_verified_projection_context(snapshot_id)
        try:
            coverage = CoverageState(coverage_state)
        except ValueError as exc:
            raise ResearchPanelError(f"unknown coverage_state {coverage_state!r}") from exc
        built_at = ensure_utc_timestamp(build_timestamp)
        batches = self.iter_projected_daily_batches(
            snapshot_id,
            split=None,
            batch_size=32_768,
        )
        return self._publish(
            batches,
            source_snapshot_id=projection.source_snapshot_id,
            source_snapshot_as_of=projection.source_snapshot_as_of,
            source_canonical_run_id=projection.source_canonical_run_id,
            source_readmodel_contract_version=projection.source_readmodel_contract_version,
            source_snapshot_manifest_hash=projection.source_snapshot_manifest_hash,
            source_snapshot_semantic_hash=projection.source_snapshot_semantic_hash,
            identity_view=projection.identity_view,
            build_timestamp=built_at,
            coverage_state=coverage,
            publication_mode=AUTHORITATIVE_READMODEL_PUBLICATION,
        )

    def _prepare_verified_projection_context(self, snapshot_id: str) -> _VerifiedResearchContext:
        """Validate small source bindings without materializing daily facts."""
        model = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
            readmodel_root=self.readmodel_root,
        )
        try:
            db, verified_snapshot = model.open_read_only_with_snapshot(snapshot_id)
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
            canonical_run_id = str(meta[1])
        except ResearchPanelError:
            raise
        except Exception as exc:
            raise ResearchPanelError(
                f"verified ReadModel {snapshot_id} cannot provide typed daily bars: {exc}"
            ) from exc
        finally:
            db.close()

        if canonical_run_id != verified_snapshot.canonical_run_id:
            raise ResearchPanelError("ReadModel canonical_run_id does not match its snapshot")
        try:
            _canonical_record, canonical_manifest, canonical_as_of = read_canonical_run_manifest(
                self.conn,
                canonical_run_id,
                normalized_root=self.normalized_root,
            )
        except Exception as exc:
            raise ResearchPanelError(
                f"canonical run {canonical_run_id} manifest seal is unavailable: {exc}"
            ) from exc
        if canonical_as_of != verified_snapshot.as_of:
            raise ResearchPanelError("ReadModel and canonical run as_of values do not match")
        identity_view = self._identity_view_from_canonical_manifest(
            canonical_manifest,
            canonical_run_id=canonical_run_id,
            canonical_as_of=canonical_as_of,
        )
        record = verified_snapshot.ledger_record
        return _VerifiedResearchContext(
            source_snapshot_id=snapshot_id,
            source_snapshot_as_of=verified_snapshot.as_of,
            source_canonical_run_id=canonical_run_id,
            source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
            source_snapshot_manifest_hash=str(record["manifest_hash"]),
            source_snapshot_semantic_hash=str(record["snapshot_semantic_hash"]),
            identity_view=identity_view,
        )

    def prepare_verified_projection(self, snapshot_id: str) -> VerifiedResearchProjection:
        """Verify one ReadModel snapshot and return rows without publishing.

        The method deliberately stops immediately before the existing R1
        ``_publish`` boundary.  It is the only boundary a future historical
        materializer may consume: no coverage label, caller identity, or
        publication side effect is accepted here.
        """
        model = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
            readmodel_root=self.readmodel_root,
        )
        try:
            db, verified_snapshot = model.open_read_only_with_snapshot(snapshot_id)
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

        if canonical_run_id != verified_snapshot.canonical_run_id:
            raise ResearchPanelError("ReadModel canonical_run_id does not match its snapshot")
        try:
            _canonical_record, canonical_manifest, canonical_as_of = read_canonical_run_manifest(
                self.conn,
                canonical_run_id,
                normalized_root=self.normalized_root,
            )
        except Exception as exc:
            raise ResearchPanelError(
                f"canonical run {canonical_run_id} manifest seal is unavailable: {exc}"
            ) from exc
        if canonical_as_of != verified_snapshot.as_of:
            raise ResearchPanelError("ReadModel and canonical run as_of values do not match")
        identity_view = self._identity_view_from_canonical_manifest(
            canonical_manifest,
            canonical_run_id=canonical_run_id,
            canonical_as_of=canonical_as_of,
        )
        record = verified_snapshot.ledger_record
        projected = self._project_rows(
            rows,
            source_snapshot_id=snapshot_id,
            source_snapshot_as_of=verified_snapshot.as_of,
            source_canonical_run_id=canonical_run_id,
            source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
            identity_view=identity_view,
        )
        return VerifiedResearchProjection(
            rows=tuple(projected),
            source_snapshot_id=snapshot_id,
            source_snapshot_as_of=verified_snapshot.as_of,
            source_canonical_run_id=canonical_run_id,
            source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
            source_snapshot_manifest_hash=str(record["manifest_hash"]),
            source_snapshot_semantic_hash=str(record["snapshot_semantic_hash"]),
            identity_view=identity_view,
        )

    def iter_projected_daily_batches(
        self,
        snapshot_id: str,
        *,
        split: ResearchSplit | str | None = None,
        start: date | str | None = None,
        end: date | str | None = None,
        security_ids: Sequence[str] | None = None,
        columns: Sequence[str] | None = None,
        batch_size: int = 32_768,
    ) -> Iterator[pl.DataFrame]:
        """Yield verified R1 rows as bounded Polars batches.

        Date/split and UUID filters are applied by DuckDB before rows cross
        into Python. The row classifier and identity/PIT rules are the same
        implementation used by full R1 publication; no whole-history
        ``fetchall`` or list-of-dicts hand-off is created.
        """
        if batch_size <= 0:
            raise ResearchPanelError("batch_size must be positive")
        if split is None:
            lower = parse_date_value(start) if start is not None else None
            upper = parse_date_value(end) if end is not None else None
        else:
            try:
                split_start, split_end = split_window(ResearchSplit(split))
            except ValueError as exc:
                raise ResearchPanelError(f"unknown research split {split!r}") from exc
            except Exception as exc:
                if isinstance(exc, ResearchPanelError):
                    raise
                raise ResearchPanelError(f"invalid research split {split!r}") from exc
            requested_start = parse_date_value(start) if start is not None else split_start
            requested_end = parse_date_value(end) if end is not None else split_end
            lower = max(split_start, requested_start)
            upper = min(split_end, requested_end)
        if lower is not None and upper is not None and lower > upper:
            return

        if columns is not None and not columns:
            raise ResearchPanelError("columns must select at least one research field")
        output_columns = tuple(
            columns if columns is not None else research_security_daily_schema().names()
        )
        allowed_output = set(research_security_daily_schema().names())
        unknown_columns = sorted(set(output_columns) - allowed_output)
        if unknown_columns:
            raise ResearchPanelError(f"unknown projected research columns: {unknown_columns}")
        requested_ids = tuple(sorted({str(value).strip() for value in security_ids or ()}))
        if any(not value for value in requested_ids):
            raise ResearchPanelError("security_ids must not contain empty values")
        if security_ids is not None and not requested_ids:
            return

        model = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
            readmodel_root=self.readmodel_root,
        )
        try:
            db, verified_snapshot = model.open_read_only_with_snapshot(snapshot_id)
        except ReadModelError as exc:
            raise ResearchPanelError(
                f"research input ReadModel {snapshot_id} is not consumable: {exc}"
            ) from exc
        try:
            meta = db.execute(
                "SELECT snapshot_id, canonical_run_id, canonical_as_of, "
                "readmodel_contract_version FROM rm_snapshot_meta"
            ).fetchone()
            if meta is None or str(meta[0]) != snapshot_id:
                raise ResearchPanelError("verified ReadModel metadata does not match the snapshot")
            if str(meta[3]) != READMODEL_CONTRACT_VERSION:
                raise ResearchPanelError("ReadModel contract version is not readmodel-v1")
            canonical_run_id = str(meta[1])
            if canonical_run_id != verified_snapshot.canonical_run_id:
                raise ResearchPanelError("ReadModel canonical_run_id does not match its snapshot")
            _canonical_record, canonical_manifest, canonical_as_of = read_canonical_run_manifest(
                self.conn,
                canonical_run_id,
                normalized_root=self.normalized_root,
            )
            if canonical_as_of != verified_snapshot.as_of:
                raise ResearchPanelError("ReadModel and Canonical market_as_of values differ")
            identity_view = self._identity_view_from_canonical_manifest(
                canonical_manifest,
                canonical_run_id=canonical_run_id,
                canonical_as_of=canonical_as_of,
            )

            source_columns = (
                "canonical_domain",
                "canonical_key",
                "security_id",
                "trade_date",
                "available_at",
                "canonical_run_id",
                "snapshot_id",
                "source_row_identity_hash",
                *_NUMERIC_FIELDS,
            )
            sql = "SELECT " + ", ".join(f'"{name}"' for name in source_columns)
            sql += " FROM rm_daily_bar"
            conditions: list[str] = []
            params: list[Any] = []
            if lower is not None:
                conditions.append("trade_date >= ?")
                params.append(lower)
            if upper is not None:
                conditions.append("trade_date <= ?")
                params.append(upper)
            if requested_ids:
                conditions.append("security_id IN (" + ", ".join("?" for _ in requested_ids) + ")")
                params.extend(requested_ids)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY trade_date, security_id, canonical_key"
            batches = db.execute(sql, params).to_arrow_reader(batch_size=batch_size)
            previous_key: tuple[date, str] | None = None
            result_schema = research_security_daily_schema()
            for batch in batches:
                source_rows = batch.to_pylist()
                if not source_rows:
                    continue
                first_key = (source_rows[0]["trade_date"], str(source_rows[0]["security_id"]))
                if previous_key is not None and first_key <= previous_key:
                    raise ResearchPanelError(
                        "filtered ReadModel has duplicate or unsorted daily keys"
                    )
                projected = self._project_rows(
                    source_rows,
                    source_snapshot_id=snapshot_id,
                    source_snapshot_as_of=verified_snapshot.as_of,
                    source_canonical_run_id=canonical_run_id,
                    source_readmodel_contract_version=READMODEL_CONTRACT_VERSION,
                    identity_view=identity_view,
                )
                last = source_rows[-1]
                previous_key = (last["trade_date"], str(last["security_id"]))
                frame = pl.DataFrame(projected, schema=result_schema, strict=False)
                yield frame.select(list(output_columns))
        except ResearchPanelError:
            raise
        except Exception as exc:
            raise ResearchPanelError(
                f"verified ReadModel {snapshot_id} cannot stream projected daily batches: {exc}"
            ) from exc
        finally:
            db.close()

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

    def _identity_view_from_canonical_manifest(
        self,
        manifest: Mapping[str, Any],
        *,
        canonical_run_id: str,
        canonical_as_of: datetime,
    ) -> IdentityView:
        """Materialize identity from the canonical manifest's sealed inputs.

        The canonical owner has already deep-verified this run.  This R1
        consumer checks the referenced manifest/output hashes it actually
        reads, without invoking the full canonical verifier recursively.
        """
        entries = manifest.get("input_normalized_runs")
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
                canonical_run_id=canonical_run_id,
                canonical_as_of=canonical_as_of,
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

        # Keep the approved code-change event in the verified view even when
        # one side is absent from the provider's current stock_basic output:
        # historical code-list membership and current stock_basic are
        # intentionally separate provider shapes.  This is one exact static
        # event, not alias discovery.
        for event in approved_provider_identity_events():
            for provider_symbol in (
                event.old_provider_symbol,
                event.new_provider_symbol,
            ):
                symbol, _ = provider_symbol.rsplit(".", 1)
                record = IdentityRecord(
                    security_id=event.security_id,
                    symbol=symbol,
                    exchange=event.exchange,
                    valid_from=(
                        event.original_list_date
                        if provider_symbol == event.old_provider_symbol
                        else event.effective_from
                    ),
                    valid_to=(
                        event.effective_from
                        if provider_symbol == event.old_provider_symbol
                        else None
                    ),
                )
                key = (record.security_id, record.valid_from, record.symbol, record.exchange)
                existing = records_by_key.get(key)
                if existing is not None and existing != record:
                    raise ResearchPanelError(
                        "approved identity event conflicts with verified identity source "
                        f"for {provider_symbol}"
                    )
                records_by_key[key] = record
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
        raw_delist_date = row.get("delist_date")
        delist_date = None if raw_delist_date is None else parse_date_value(raw_delist_date)
        event = identity_event_for_provider_symbol(provider_symbol)
        if event is not None:
            if (
                raw_list_date is not None
                and parse_date_value(raw_list_date) != event.original_list_date
            ):
                raise ResearchPanelError(
                    f"approved identity event {provider_symbol!r} has a provider list_date "
                    f"different from {event.original_list_date.isoformat()}"
                )
            interval = event.interval_for(provider_symbol)
            if interval is None:  # pragma: no cover - guarded by exact event lookup
                raise ResearchPanelError(
                    f"approved identity event has no interval for {provider_symbol!r}"
                )
            valid_from, valid_to = interval
            return IdentityRecord(
                security_id=event.security_id,
                symbol=symbol,
                exchange=event.exchange,
                valid_from=valid_from,
                valid_to=valid_to,
                delist_date=delist_date,
            )
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
            delist_date=delist_date,
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
            current_identity = identity_view.current(security_id)
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
                    # Identity validation above is explicitly PIT.  Ordinary
                    # R1 presentation is explicitly current-code-first: a
                    # dated historical row such as 2024's 300114 must not
                    # leak the old code after the approved 2025 change.
                    "symbol": current_identity.symbol if current_identity else None,
                    "exchange": current_identity.exchange if current_identity else None,
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
        rows: Iterable[Mapping[str, Any]] | Iterable[pl.DataFrame],
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

        def source_batches() -> Iterator[pl.DataFrame]:
            if isinstance(rows, Sequence):
                # Test-only fixture input is intentionally small and may arrive
                # unsorted. Keep that boundary deterministic while production
                # ReadModel publication below remains batch-bounded.
                artifact_rows: dict[str, list[Mapping[str, Any]]] = {
                    split: [] for split in _ARTIFACT_NAMES
                }
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
                    for offset in range(0, len(artifact_rows[name]), 32_768):
                        yield pl.DataFrame(
                            artifact_rows[name][offset : offset + 32_768],
                            schema=schema,
                            strict=True,
                        )
                return
            for batch in rows:
                if not isinstance(batch, pl.DataFrame):
                    raise ResearchPanelError(
                        "streamed research publication requires bounded Polars batches"
                    )
                if batch.columns != schema.names():
                    raise ResearchPanelError("streamed research batch schema does not match R1")
                yield batch

        arrow_schema = pl.DataFrame(schema=schema, strict=True).to_arrow().schema
        semantic_digests = {name: hashlib.sha256() for name in _ARTIFACT_NAMES}
        for digest in semantic_digests.values():
            digest.update(b"[")
        row_counts = dict.fromkeys(_ARTIFACT_NAMES, 0)
        semantic_row_counts = dict.fromkeys(_ARTIFACT_NAMES, 0)
        previous_keys: dict[str, tuple[date, str, str] | None] = dict.fromkeys(
            _ARTIFACT_NAMES, None
        )
        self.research_root.mkdir(parents=True, exist_ok=True)
        artifacts: list[ArtifactMetadata] = []
        artifact_replay: dict[str, bool] = {}
        with tempfile.TemporaryDirectory(
            prefix=f".{dataset_id}-", dir=self.research_root
        ) as staging_name:
            staging_root = Path(staging_name)
            staged_paths = {name: staging_root / f"{name}.parquet" for name in _ARTIFACT_NAMES}
            with ExitStack() as stack:
                if not isinstance(rows, Sequence) and hasattr(rows, "close"):
                    stack.callback(rows.close)  # type: ignore[attr-defined]
                writers = {
                    name: stack.enter_context(
                        pq.ParquetWriter(
                            staged_paths[name],
                            arrow_schema,
                            compression="zstd",
                            write_statistics=False,
                        )
                    )
                    for name in _ARTIFACT_NAMES
                }
                for batch in source_batches():
                    for name in _ARTIFACT_NAMES:
                        if name == "disabled":
                            part = batch.filter(
                                pl.col("research_eligibility") != ResearchEligibility.ENABLED.value
                            )
                        else:
                            part = batch.filter(
                                (
                                    pl.col("research_eligibility")
                                    == ResearchEligibility.ENABLED.value
                                )
                                & (pl.col("research_split") == name)
                            )
                        if part.is_empty():
                            continue
                        table = part.to_arrow()
                        if not table.schema.equals(arrow_schema, check_metadata=False):
                            table = table.cast(arrow_schema)
                        writers[name].write_table(table)
                        row_counts[name] += part.height
                        for row in part.iter_rows(named=True):
                            key = (
                                row["trade_date"],
                                str(row["security_id"]),
                                str(row["source_canonical_key"]),
                            )
                            previous = previous_keys[name]
                            if previous is not None and key <= previous:
                                raise ResearchPanelError(
                                    f"{name} research rows are duplicated or not time-first sorted"
                                )
                            previous_keys[name] = key
                            digest = semantic_digests[name]
                            if semantic_row_counts[name] > 0:
                                digest.update(b",")
                            digest.update(canonical_json(row).encode("utf-8"))
                            semantic_row_counts[name] += 1
            for digest in semantic_digests.values():
                digest.update(b"]")
            for name in _ARTIFACT_NAMES:
                final_path = self.research_root / base_dir / f"{name}.parquet"
                before = final_path.is_file()
                artifact_replay[name] = before
                file_hash = commit_staged_file_atomic(
                    final_path,
                    staged_paths[name],
                    allow_existing_identical=True,
                )
                artifacts.append(
                    ArtifactMetadata(
                        name=name,
                        uri=str(base_dir / f"{name}.parquet").replace("\\", "/"),
                        split=name,
                        research_eligible=name != "disabled",
                        content_hash=file_hash,
                        semantic_hash=semantic_digests[name].hexdigest(),
                        schema_hash=schema_hash,
                        row_count=row_counts[name],
                        byte_size=final_path.stat().st_size,
                    )
                )

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
        idempotent_replay = all(artifact_replay.values())
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
