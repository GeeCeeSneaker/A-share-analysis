"""CR-5 FeatureBuilder: verified ReadModel -> immutable PIT features."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from ashare_state.features.engine import (
    FEATURE_ARTIFACT_NAMES,
    ComputedFeatureSet,
    compute_feature_set,
    frame_for_artifact,
)
from ashare_state.features.models import (
    FEATURE_CONTRACT_VERSION,
    FeatureBuildResult,
    FeatureBuilderError,
    feature_base_hash_from_primitives,
    feature_id_from_base_hash,
    semantic_hash,
)
from ashare_state.features.registry import FeatureRegistryError, get_feature_set
from ashare_state.readmodel import (
    READMODEL_CONTRACT_VERSION,
    DuckDBReadModel,
    ReadModelError,
    duckdb_domain_columns,
    readmodel_builder_code_fingerprint,
)
from ashare_state.snapshot import verify_snapshot
from ashare_state.storage.atomic_files import write_file_atomic

__all__ = [
    "FEATURE_LEDGER_COLUMNS",
    "FeatureBuilder",
    "feature_base_dir",
    "feature_builder_code_fingerprint",
    "feature_manifest_uri",
]


FEATURE_LEDGER_COLUMNS = (
    "feature_run_id",
    "snapshot_id",
    "snapshot_manifest_uri",
    "snapshot_manifest_hash",
    "snapshot_semantic_hash",
    "snapshot_as_of",
    "readmodel_contract_version",
    "readmodel_builder_code_fingerprint",
    "feature_set_id",
    "feature_set_version",
    "feature_registry_version",
    "feature_registry_hash",
    "feature_contract_version",
    "feature_builder_code_fingerprint",
    "manifest_uri",
    "manifest_hash",
    "artifact_set_hash",
    "feature_semantic_hash",
    "finding_set_hash",
    "security_row_count",
    "market_row_count",
    "finding_count",
    "status",
    "error_message",
    "started_at",
    "completed_at",
)


def feature_builder_code_fingerprint() -> str:
    """Hash every source module that governs feature correctness."""
    import ashare_state.features.builder as _builder
    import ashare_state.features.engine as _engine
    import ashare_state.features.formulas as _formulas
    import ashare_state.features.models as _models
    import ashare_state.features.registry as _registry
    import ashare_state.features.verifier as _verifier

    digest = hashlib.sha256()
    for module in (
        _models,
        _registry,
        _formulas,
        _engine,
        _builder,
        _verifier,
    ):
        module_file = getattr(module, "__file__", None)
        if module_file is None:  # pragma: no cover
            raise FeatureBuilderError(f"feature module {module!r} has no source file")
        source = Path(module_file).read_bytes().decode("utf-8")
        digest.update(module.__name__.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def feature_base_dir(snapshot_id: str, feature_run_id: str) -> str:
    return (
        f"feature/contract={FEATURE_CONTRACT_VERSION}/"
        f"snapshot={snapshot_id}/run={feature_run_id}"
    )


def feature_manifest_uri(snapshot_id: str, feature_run_id: str) -> str:
    return f"{feature_base_dir(snapshot_id, feature_run_id)}/manifest.json"


def _assert_immutable_compatible(path: Path, data: bytes) -> None:
    if not path.exists():
        return
    if not path.is_file() or path.read_bytes() != data:
        raise FeatureBuilderError(
            f"immutable feature artifact conflict: {path} exists with different bytes"
        )


def _write_immutable(path: Path, data: bytes) -> None:
    """Write once or accept exact identical residue during recovery."""
    try:
        write_file_atomic(path, data, allow_existing_identical=True)
    except Exception as exc:
        raise FeatureBuilderError(f"feature immutable publication failed at {path}: {exc}") from exc


def _feature_manifest_semantic_hash(
    security_rows: tuple[dict[str, Any], ...],
    market_rows: tuple[dict[str, Any], ...],
) -> str:
    return semantic_hash((*security_rows, *market_rows))


class FeatureBuilder:
    """Build one feature run from one verified ReadModel snapshot."""

    def __init__(
        self,
        conn: Any,
        *,
        raw_root: Path,
        normalized_root: Path,
        readmodel_root: Path | None = None,
        feature_root: Path | None = None,
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
        self.readmodel_root = Path(readmodel_root) if readmodel_root else self.normalized_root
        self.feature_root = Path(feature_root) if feature_root else self.normalized_root

    def _load_verified_readmodel(
        self,
        snapshot_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
        """Open the public verified boundary and retrieve only typed rows."""
        model = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
            readmodel_root=self.readmodel_root,
        )
        try:
            db = model.open_read_only(snapshot_id)
        except ReadModelError as exc:
            raise FeatureBuilderError(
                f"feature input ReadModel {snapshot_id} is not consumable: {exc}"
            ) from exc

        try:
            meta_row = db.execute(
                "SELECT snapshot_id, canonical_run_id, canonical_as_of, "
                "readmodel_contract_version, snapshot_builder_code_fingerprint, "
                "readmodel_builder_code_fingerprint "
                "FROM rm_snapshot_meta"
            ).fetchall()
            if len(meta_row) != 1:
                raise FeatureBuilderError(
                    "verified ReadModel rm_snapshot_meta must carry exactly one row"
                )
            meta = meta_row[0]
            columns = tuple(duckdb_domain_columns("daily_bar"))
            table_names = {
                str(row[0])
                for row in db.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'main'"
                ).fetchall()
            }
            if "rm_daily_bar" not in table_names:
                raise FeatureBuilderError(
                    f"snapshot {snapshot_id} has no rm_daily_bar input table"
                )
            query = (
                "SELECT "
                + ", ".join(columns)
                + " FROM rm_daily_bar "
                "ORDER BY security_id, trade_date, canonical_key"
            )
            fetched_rows = db.execute(query).fetchall()
            readmodel_rows = [
                dict(zip(columns, row, strict=True))
                for row in fetched_rows
            ]
            metadata = {
                "snapshot_id": str(meta[0]),
                "canonical_run_id": str(meta[1]),
                "canonical_as_of": meta[2],
                "readmodel_contract_version": str(meta[3]),
                "snapshot_builder_code_fingerprint": str(meta[4]),
                "readmodel_builder_code_fingerprint": str(meta[5]),
            }
        except FeatureBuilderError:
            raise
        except Exception as exc:
            raise FeatureBuilderError(
                f"verified ReadModel {snapshot_id} cannot provide typed daily bars: {exc}"
            ) from exc
        finally:
            db.close()

        # The public Snapshot verifier supplies identity seals and as_of
        # metadata only. Feature values still come exclusively from the
        # verified ReadModel rows above.
        try:
            verified_snapshot = verify_snapshot(
                self.conn,
                snapshot_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
        except Exception as exc:
            raise FeatureBuilderError(
                f"snapshot {snapshot_id} verification metadata is unavailable: {exc}"
            ) from exc
        if metadata["snapshot_id"] != snapshot_id:
            raise FeatureBuilderError("ReadModel snapshot_id does not match the explicit input")
        if metadata["canonical_run_id"] != verified_snapshot.canonical_run_id:
            raise FeatureBuilderError("ReadModel canonical_run_id does not match its snapshot")
        if metadata["readmodel_contract_version"] != READMODEL_CONTRACT_VERSION:
            raise FeatureBuilderError("ReadModel contract version is not the current contract")
        if metadata["canonical_as_of"].astimezone(UTC) != verified_snapshot.as_of:
            raise FeatureBuilderError("ReadModel canonical_as_of does not match its snapshot")
        if metadata["snapshot_builder_code_fingerprint"] != str(
            verified_snapshot.manifest["snapshot_builder_code_fingerprint"]
        ):
            raise FeatureBuilderError("ReadModel snapshot builder fingerprint is foreign")
        return metadata, readmodel_rows, verified_snapshot

    def build(self, snapshot_id: str, feature_set_id: str) -> FeatureBuildResult:
        """Build one explicit snapshot/feature-set pair."""
        started = datetime.now(UTC)
        try:
            feature_set = get_feature_set(feature_set_id)
        except FeatureRegistryError as exc:
            raise FeatureBuilderError(str(exc)) from exc

        metadata, readmodel_rows, verified_snapshot = self._load_verified_readmodel(snapshot_id)
        snapshot_record = verified_snapshot.ledger_record
        feature_fingerprint = feature_builder_code_fingerprint()
        snapshot_manifest_hash = str(snapshot_record["manifest_hash"])
        snapshot_semantic_hash = str(snapshot_record["snapshot_semantic_hash"])
        snapshot_as_of = verified_snapshot.as_of.isoformat()
        readmodel_contract = str(metadata["readmodel_contract_version"])
        readmodel_fingerprint = str(metadata["readmodel_builder_code_fingerprint"])
        base_hash = feature_base_hash_from_primitives(
            snapshot_id=snapshot_id,
            snapshot_manifest_hash=snapshot_manifest_hash,
            snapshot_semantic_hash=snapshot_semantic_hash,
            snapshot_as_of=snapshot_as_of,
            readmodel_contract_version=readmodel_contract,
            readmodel_builder_code_fingerprint=readmodel_fingerprint,
            feature_set_id=feature_set.feature_set_id,
            feature_set_version=feature_set.feature_set_version,
            feature_registry_version=feature_set.feature_registry_version,
            feature_registry_hash=feature_set.registry_hash,
            feature_contract_version=FEATURE_CONTRACT_VERSION,
            feature_builder_code_fingerprint=feature_fingerprint,
        )
        feature_run_id = feature_id_from_base_hash(base_hash)

        existing = self.conn.execute(
            "SELECT 1 FROM meta_feature_build WHERE feature_run_id = ?",
            [feature_run_id],
        ).fetchone()
        if existing is not None:
            from ashare_state.features.verifier import verify_feature_run_for_consumption

            current = verify_feature_run_for_consumption(
                self.conn,
                feature_run_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
                readmodel_root=self.readmodel_root,
                feature_root=self.feature_root,
            )
            return FeatureBuildResult(
                feature_run_id=current.feature_run_id,
                snapshot_id=current.snapshot_id,
                feature_set_id=current.feature_set_id,
                manifest_uri=str(current.ledger_record["manifest_uri"]),
                manifest_hash=str(current.ledger_record["manifest_hash"]),
                artifact_set_hash=str(current.ledger_record["artifact_set_hash"]),
                feature_semantic_hash=str(current.ledger_record["feature_semantic_hash"]),
                finding_set_hash=str(current.ledger_record["finding_set_hash"]),
                security_row_count=int(current.ledger_record["security_row_count"]),
                market_row_count=int(current.ledger_record["market_row_count"]),
                finding_count=int(current.ledger_record["finding_count"]),
                status=str(current.ledger_record["status"]),
                idempotent_replay=True,
            )

        computed: ComputedFeatureSet = compute_feature_set(
            readmodel_rows,
            snapshot_id=snapshot_id,
            canonical_run_id=str(metadata["canonical_run_id"]),
            feature_run_id=feature_run_id,
            feature_set=feature_set,
            snapshot_as_of=verified_snapshot.as_of,
        )
        artifact_rows = {
            "security_daily_features": computed.security_rows,
            "market_daily_features": computed.market_rows,
            "feature_findings": computed.finding_rows,
        }
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_payloads: dict[str, bytes] = {}
        base_dir = feature_base_dir(snapshot_id, feature_run_id)
        for name in FEATURE_ARTIFACT_NAMES:
            frame = frame_for_artifact(name, artifact_rows[name])
            buffer = io.BytesIO()
            frame.write_parquet(buffer)
            data = buffer.getvalue()
            artifacts[name] = {
                "uri": f"{base_dir}/{name}.parquet",
                "content_hash": hashlib.sha256(data).hexdigest(),
                "schema_hash": hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest(),
                "row_count": frame.height,
                "semantic_hash": semantic_hash(frame.to_dicts()),
            }
            artifact_payloads[name] = data

        artifact_set_hash = hashlib.sha256(
            json.dumps(
                artifacts,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        feature_semantic = _feature_manifest_semantic_hash(
            computed.security_rows,
            computed.market_rows,
        )
        finding_set_hash = semantic_hash(computed.finding_rows)
        manifest = {
            "feature_run_id": feature_run_id,
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "feature_base_hash": base_hash,
            "feature_builder_code_fingerprint": feature_fingerprint,
            "feature_set_id": feature_set.feature_set_id,
            "feature_set_version": feature_set.feature_set_version,
            "feature_registry_version": feature_set.feature_registry_version,
            "feature_registry_hash": feature_set.registry_hash,
            "snapshot_id": snapshot_id,
            "snapshot_manifest_uri": str(snapshot_record["manifest_uri"]),
            "snapshot_manifest_hash": snapshot_manifest_hash,
            "snapshot_semantic_hash": snapshot_semantic_hash,
            "snapshot_as_of": snapshot_as_of,
            "readmodel_contract_version": readmodel_contract,
            "readmodel_builder_code_fingerprint": readmodel_fingerprint,
            "price_basis": feature_set.price_basis,
            "window_basis": "OBSERVED_SECURITY_BARS",
            "universe_rule_id": feature_set.universe_rule_id,
            "artifacts": artifacts,
            "artifact_set_hash": artifact_set_hash,
            "feature_semantic_hash": feature_semantic,
            "finding_set_hash": finding_set_hash,
            "security_row_count": len(computed.security_rows),
            "market_row_count": len(computed.market_rows),
            "finding_count": len(computed.finding_rows),
            "status": "SUCCESS",
        }
        manifest_uri = feature_manifest_uri(snapshot_id, feature_run_id)
        manifest_bytes = json.dumps(
            manifest,
            sort_keys=True,
            indent=1,
            ensure_ascii=False,
        ).encode("utf-8")

        write_plan = [
            (self.feature_root / artifacts[name]["uri"], artifact_payloads[name])
            for name in FEATURE_ARTIFACT_NAMES
        ]
        write_plan.append((self.feature_root / manifest_uri, manifest_bytes))
        for path, data in write_plan:
            _assert_immutable_compatible(path, data)
        for path, data in write_plan[:-1]:
            _write_immutable(path, data)
        _write_immutable(write_plan[-1][0], write_plan[-1][1])

        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        completed = datetime.now(UTC)
        self._commit_ledger(
            feature_run_id=feature_run_id,
            snapshot_id=snapshot_id,
            snapshot_manifest_uri=str(snapshot_record["manifest_uri"]),
            snapshot_manifest_hash=snapshot_manifest_hash,
            snapshot_semantic_hash=snapshot_semantic_hash,
            snapshot_as_of=verified_snapshot.as_of,
            readmodel_contract_version=readmodel_contract,
            readmodel_builder_code_fingerprint=readmodel_fingerprint,
            feature_set_id=feature_set.feature_set_id,
            feature_set_version=feature_set.feature_set_version,
            feature_registry_version=feature_set.feature_registry_version,
            feature_registry_hash=feature_set.registry_hash,
            feature_contract_version=FEATURE_CONTRACT_VERSION,
            feature_builder_code_fingerprint=feature_fingerprint,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            feature_semantic_hash=feature_semantic,
            finding_set_hash=finding_set_hash,
            security_row_count=len(computed.security_rows),
            market_row_count=len(computed.market_rows),
            finding_count=len(computed.finding_rows),
            started=started,
            completed=completed,
        )
        return FeatureBuildResult(
            feature_run_id=feature_run_id,
            snapshot_id=snapshot_id,
            feature_set_id=feature_set.feature_set_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            feature_semantic_hash=feature_semantic,
            finding_set_hash=finding_set_hash,
            security_row_count=len(computed.security_rows),
            market_row_count=len(computed.market_rows),
            finding_count=len(computed.finding_rows),
            status="SUCCESS",
            idempotent_replay=False,
        )

    def _commit_ledger(self, **values: Any) -> None:
        self.conn.execute("BEGIN TRANSACTION")
        try:
            duplicate = self.conn.execute(
                "SELECT 1 FROM meta_feature_build WHERE feature_run_id = ?",
                [values["feature_run_id"]],
            ).fetchone()
            if duplicate is not None:
                raise FeatureBuilderError(
                    f"feature run {values['feature_run_id']} already exists in the ledger"
                )
            row = [
                values[column]
                for column in FEATURE_LEDGER_COLUMNS
                if column not in {"manifest_uri", "manifest_hash", "artifact_set_hash",
                                  "feature_semantic_hash", "finding_set_hash",
                                  "security_row_count", "market_row_count", "finding_count",
                                  "status", "error_message", "started_at", "completed_at"}
            ]
            row.extend(
                [
                    values["manifest_uri"],
                    values["manifest_hash"],
                    values["artifact_set_hash"],
                    values["feature_semantic_hash"],
                    values["finding_set_hash"],
                    values["security_row_count"],
                    values["market_row_count"],
                    values["finding_count"],
                    "SUCCESS",
                    None,
                    values["started"],
                    values["completed"],
                ]
            )
            self.conn.execute(
                f"INSERT INTO meta_feature_build ({', '.join(FEATURE_LEDGER_COLUMNS)}) "
                f"VALUES ({', '.join(['?'] * len(FEATURE_LEDGER_COLUMNS))})",
                row,
            )
            self.conn.execute("COMMIT")
        except Exception:
            import contextlib

            with contextlib.suppress(Exception):
                self.conn.execute("ROLLBACK")
            raise
