"""Public CR-5 Feature consumption verifier.

The verifier consumes only hash-verified bytes and replays the shared
feature engine against the same verified ReadModel. Artifact seals are
not treated as proof of derivation by themselves.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.features.builder import (
    FEATURE_LEDGER_COLUMNS,
    feature_builder_code_fingerprint,
    feature_manifest_uri,
)
from ashare_state.features.engine import (
    FEATURE_ARTIFACT_NAMES,
    compute_feature_set,
    feature_artifact_schema,
)
from ashare_state.features.models import (
    FEATURE_CONTRACT_VERSION,
    FeatureVerifierError,
    VerifiedFeatureRun,
    canonical_json,
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
)
from ashare_state.snapshot import SnapshotVerifierError, verify_snapshot

__all__ = [
    "FeatureVerifier",
    "verify_feature_run_for_consumption",
]


def _ledger_record(conn: Any, feature_run_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {', '.join(FEATURE_LEDGER_COLUMNS)} FROM meta_feature_build "
        "WHERE feature_run_id = ?",
        [feature_run_id],
    ).fetchone()
    if row is None:
        raise FeatureVerifierError(
            f"feature run {feature_run_id} does not exist in the feature ledger"
        )
    return dict(zip(FEATURE_LEDGER_COLUMNS, row, strict=True))


def _utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FeatureVerifierError(f"feature {field} is not a timezone-aware timestamp")
    return value.astimezone(UTC)


def _artifact_set_hash(seals: dict[str, dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(seals).encode("utf-8")).hexdigest()


def _feature_semantic_hash(
    security_rows: tuple[dict[str, Any], ...],
    market_rows: tuple[dict[str, Any], ...],
) -> str:
    return semantic_hash((*security_rows, *market_rows))


def _readmodel_rows(
    db: Any,
    *,
    snapshot_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = db.execute(
        "SELECT snapshot_id, canonical_run_id, canonical_as_of, "
        "readmodel_contract_version, snapshot_builder_code_fingerprint, "
        "readmodel_builder_code_fingerprint "
        "FROM rm_snapshot_meta"
    ).fetchall()
    if len(meta) != 1:
        raise FeatureVerifierError("verified ReadModel rm_snapshot_meta must carry exactly one row")
    meta_row = meta[0]
    columns = tuple(duckdb_domain_columns("daily_bar"))
    table_names = {
        str(row[0])
        for row in db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
    }
    if "rm_daily_bar" not in table_names:
        raise FeatureVerifierError(f"snapshot {snapshot_id} has no rm_daily_bar input table")
    query = (
        "SELECT " + ", ".join(columns) + " FROM rm_daily_bar "
        "ORDER BY security_id, trade_date, canonical_key"
    )
    rows = [dict(zip(columns, row, strict=True)) for row in db.execute(query).fetchall()]
    metadata = {
        "snapshot_id": str(meta_row[0]),
        "canonical_run_id": str(meta_row[1]),
        "canonical_as_of": meta_row[2],
        "readmodel_contract_version": str(meta_row[3]),
        "snapshot_builder_code_fingerprint": str(meta_row[4]),
        "readmodel_builder_code_fingerprint": str(meta_row[5]),
    }
    return metadata, rows


def _compare_rows(
    name: str,
    actual: list[dict[str, Any]],
    expected: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> None:
    expected_list = list(expected)
    if len(actual) != len(expected_list):
        raise FeatureVerifierError(
            f"feature {name} row count differs from deterministic replay: "
            f"{len(actual)} != {len(expected_list)}"
        )
    for position, (actual_row, expected_row) in enumerate(zip(actual, expected_list, strict=True)):
        if canonical_json(actual_row) != canonical_json(expected_row):
            raise FeatureVerifierError(
                f"feature {name} row {position} differs from Verified ReadModel replay"
            )


def _check_sha256(value: Any, field: str) -> str:
    text = str(value)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise FeatureVerifierError(f"feature {field} is not a SHA-256 value")
    return text


def _validate_rows(
    *,
    security_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
    finding_rows: list[dict[str, Any]],
    snapshot_id: str,
    feature_run_id: str,
    feature_set_id: str,
    snapshot_as_of: datetime,
    expected_security_columns: tuple[str, ...],
) -> None:
    business_columns = expected_security_columns[9:]
    security_keys: list[tuple[str, Any]] = []
    previous_key: tuple[str, Any] | None = None
    for row in security_rows:
        if row["source_snapshot_id"] != snapshot_id:
            raise FeatureVerifierError("feature security row carries a foreign source_snapshot_id")
        if row["feature_run_id"] != feature_run_id:
            raise FeatureVerifierError("feature security row carries a foreign feature_run_id")
        if row["feature_set_id"] != feature_set_id:
            raise FeatureVerifierError("feature security row carries a foreign feature_set_id")
        if row["feature_contract_version"] != FEATURE_CONTRACT_VERSION:
            raise FeatureVerifierError("feature security row carries a foreign feature contract")
        available_at = _utc_datetime(row["feature_available_at"], "feature_available_at")
        if available_at > snapshot_as_of:
            raise FeatureVerifierError("feature security row is available after snapshot_as_of")
        _check_sha256(row["input_lineage_hash"], "input_lineage_hash")
        key = (str(row["security_id"]), row["trade_date"])
        if previous_key is not None and key < previous_key:
            raise FeatureVerifierError("feature security rows are not deterministically sorted")
        if key in security_keys:
            raise FeatureVerifierError("feature security rows have duplicate security/date keys")
        security_keys.append(key)
        previous_key = key
        for column in business_columns:
            value = row[column]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
            ):
                raise FeatureVerifierError(
                    f"feature security {column} contains a non-finite or invalid value"
                )

    market_dates: list[Any] = []
    for row in market_rows:
        if row["source_snapshot_id"] != snapshot_id:
            raise FeatureVerifierError("feature market row carries a foreign source_snapshot_id")
        if row["feature_run_id"] != feature_run_id:
            raise FeatureVerifierError("feature market row carries a foreign feature_run_id")
        if row["feature_set_id"] != feature_set_id:
            raise FeatureVerifierError("feature market row carries a foreign feature_set_id")
        if row["universe_rule_id"] != "OBSERVED_DAILY_BAR_UNIVERSE":
            raise FeatureVerifierError("feature market row carries a foreign universe rule")
        available_at = _utc_datetime(row["feature_available_at"], "feature_available_at")
        if available_at > snapshot_as_of:
            raise FeatureVerifierError("feature market row is available after snapshot_as_of")
        _check_sha256(row["input_lineage_hash"], "input_lineage_hash")
        trade_date = row["trade_date"]
        if market_dates and trade_date < market_dates[-1]:
            raise FeatureVerifierError("feature market rows are not deterministically sorted")
        if trade_date in market_dates:
            raise FeatureVerifierError("feature market rows have duplicate trade_date keys")
        market_dates.append(trade_date)
        for column in (
            "advancer_ratio_observed",
            "mean_raw_return_observed",
            "median_raw_return_observed",
            "pct_above_ma20_observed",
            "pct_positive_mom20_observed",
            "total_amount_observed",
        ):
            value = row[column]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
            ):
                raise FeatureVerifierError(
                    f"feature market {column} contains a non-finite or invalid value"
                )

    for row in finding_rows:
        if row["scope"] not in {"security_daily", "market_daily"}:
            raise FeatureVerifierError("feature finding has an unknown scope")
        if row["scope"] == "market_daily" and row["security_id"] is not None:
            raise FeatureVerifierError("market finding carries a security_id")
        _check_sha256(
            hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest(),
            "finding row",
        )


class FeatureVerifier:
    """Verify one immutable feature run and replay its formulas."""

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

    def verify_feature_run_for_consumption(self, feature_run_id: str) -> VerifiedFeatureRun:
        record = _ledger_record(self.conn, feature_run_id)
        if str(record["status"]) != "SUCCESS":
            raise FeatureVerifierError(
                f"feature run {feature_run_id} has status {record['status']!r}; "
                "only SUCCESS runs are consumable"
            )
        try:
            feature_set = get_feature_set(str(record["feature_set_id"]))
        except FeatureRegistryError as exc:
            raise FeatureVerifierError(str(exc)) from exc

        required_record_fields = (
            ("feature_run_id", feature_run_id),
            ("feature_contract_version", FEATURE_CONTRACT_VERSION),
            ("feature_set_id", feature_set.feature_set_id),
            ("feature_set_version", feature_set.feature_set_version),
            ("feature_registry_version", feature_set.feature_registry_version),
            ("feature_registry_hash", feature_set.registry_hash),
            ("status", "SUCCESS"),
        )
        for field, expected in required_record_fields:
            if str(record[field]) != str(expected):
                raise FeatureVerifierError(
                    f"feature ledger field {field} is not the current contract"
                )

        manifest_uri = str(record["manifest_uri"])
        expected_uri = feature_manifest_uri(str(record["snapshot_id"]), feature_run_id)
        if manifest_uri != expected_uri:
            raise FeatureVerifierError(
                f"feature manifest URI is not deterministic: {manifest_uri!r} != {expected_uri!r}"
            )
        manifest_path = self.feature_root / manifest_uri
        if not manifest_path.is_file():
            raise FeatureVerifierError(f"feature manifest is missing: {manifest_uri}")
        manifest_bytes = manifest_path.read_bytes()
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_hash != str(record["manifest_hash"]):
            raise FeatureVerifierError("feature manifest bytes do not match the ledger hash")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FeatureVerifierError(f"feature manifest is unreadable: {exc}") from exc

        manifest_fields: tuple[tuple[str, str | int], ...] = (
            ("feature_run_id", feature_run_id),
            ("feature_contract_version", str(record["feature_contract_version"])),
            ("feature_set_id", str(record["feature_set_id"])),
            ("feature_set_version", str(record["feature_set_version"])),
            ("feature_registry_version", str(record["feature_registry_version"])),
            ("feature_registry_hash", str(record["feature_registry_hash"])),
            ("snapshot_id", str(record["snapshot_id"])),
            ("snapshot_manifest_uri", str(record["snapshot_manifest_uri"])),
            ("snapshot_manifest_hash", str(record["snapshot_manifest_hash"])),
            ("snapshot_semantic_hash", str(record["snapshot_semantic_hash"])),
            (
                "snapshot_as_of",
                _utc_datetime(record["snapshot_as_of"], "snapshot_as_of").isoformat(),
            ),
            ("readmodel_contract_version", str(record["readmodel_contract_version"])),
            (
                "readmodel_builder_code_fingerprint",
                str(record["readmodel_builder_code_fingerprint"]),
            ),
            ("feature_builder_code_fingerprint", str(record["feature_builder_code_fingerprint"])),
            ("artifact_set_hash", str(record["artifact_set_hash"])),
            ("feature_semantic_hash", str(record["feature_semantic_hash"])),
            ("finding_set_hash", str(record["finding_set_hash"])),
            ("security_row_count", int(record["security_row_count"])),
            ("market_row_count", int(record["market_row_count"])),
            ("finding_count", int(record["finding_count"])),
            ("status", "SUCCESS"),
        )
        for field, expected_manifest_value in manifest_fields:
            if str(manifest.get(field)) != str(expected_manifest_value):
                raise FeatureVerifierError(
                    f"feature manifest field {field} does not match the ledger"
                )

        current_feature_fingerprint = feature_builder_code_fingerprint()
        if str(manifest["feature_builder_code_fingerprint"]) != current_feature_fingerprint:
            raise FeatureVerifierError(
                "feature was built by a different feature builder code fingerprint"
            )
        base_hash = feature_base_hash_from_primitives(
            snapshot_id=str(manifest["snapshot_id"]),
            snapshot_manifest_hash=str(manifest["snapshot_manifest_hash"]),
            snapshot_semantic_hash=str(manifest["snapshot_semantic_hash"]),
            snapshot_as_of=str(manifest["snapshot_as_of"]),
            readmodel_contract_version=str(manifest["readmodel_contract_version"]),
            readmodel_builder_code_fingerprint=str(manifest["readmodel_builder_code_fingerprint"]),
            feature_set_id=str(manifest["feature_set_id"]),
            feature_set_version=str(manifest["feature_set_version"]),
            feature_registry_version=str(manifest["feature_registry_version"]),
            feature_registry_hash=str(manifest["feature_registry_hash"]),
            feature_contract_version=str(manifest["feature_contract_version"]),
            feature_builder_code_fingerprint=current_feature_fingerprint,
        )
        if str(manifest.get("feature_base_hash")) != base_hash:
            raise FeatureVerifierError(
                "feature_base_hash does not match feature identity primitives"
            )
        if feature_id_from_base_hash(base_hash) != feature_run_id:
            raise FeatureVerifierError("feature_run_id does not match UUID5 identity recompute")

        try:
            verified_snapshot = verify_snapshot(
                self.conn,
                str(manifest["snapshot_id"]),
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
        except SnapshotVerifierError as exc:
            raise FeatureVerifierError(f"upstream snapshot cannot be verified: {exc}") from exc
        if str(verified_snapshot.ledger_record["manifest_uri"]) != str(
            manifest["snapshot_manifest_uri"]
        ):
            raise FeatureVerifierError("feature snapshot manifest URI provenance diverged")
        if str(verified_snapshot.ledger_record["manifest_hash"]) != str(
            manifest["snapshot_manifest_hash"]
        ):
            raise FeatureVerifierError("feature snapshot manifest hash provenance diverged")
        if str(verified_snapshot.ledger_record["snapshot_semantic_hash"]) != str(
            manifest["snapshot_semantic_hash"]
        ):
            raise FeatureVerifierError("feature snapshot semantic provenance diverged")

        model = DuckDBReadModel(
            self.conn,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
            readmodel_root=self.readmodel_root,
        )
        try:
            db = model.open_read_only(str(manifest["snapshot_id"]))
        except ReadModelError as exc:
            raise FeatureVerifierError(
                f"upstream ReadModel cannot be verified-opened: {exc}"
            ) from exc
        try:
            metadata, readmodel_rows = _readmodel_rows(
                db,
                snapshot_id=str(manifest["snapshot_id"]),
            )
        finally:
            db.close()
        if metadata["canonical_run_id"] != verified_snapshot.canonical_run_id:
            raise FeatureVerifierError("feature ReadModel canonical_run_id provenance diverged")
        if metadata["readmodel_contract_version"] != READMODEL_CONTRACT_VERSION:
            raise FeatureVerifierError("feature ReadModel contract version diverged")
        if metadata["readmodel_contract_version"] != str(manifest["readmodel_contract_version"]):
            raise FeatureVerifierError("feature ReadModel contract does not match feature manifest")
        if metadata["readmodel_builder_code_fingerprint"] != str(
            manifest["readmodel_builder_code_fingerprint"]
        ):
            raise FeatureVerifierError("feature ReadModel builder fingerprint diverged")
        if _utc_datetime(metadata["canonical_as_of"], "canonical_as_of") != verified_snapshot.as_of:
            raise FeatureVerifierError("feature ReadModel canonical_as_of diverged")

        computed = compute_feature_set(
            readmodel_rows,
            snapshot_id=str(manifest["snapshot_id"]),
            canonical_run_id=verified_snapshot.canonical_run_id,
            feature_run_id=feature_run_id,
            feature_set=feature_set,
            snapshot_as_of=verified_snapshot.as_of,
        )

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise FeatureVerifierError("feature manifest carries no artifact map")
        if set(artifacts) != set(FEATURE_ARTIFACT_NAMES):
            raise FeatureVerifierError("feature artifact set is not the exact V1 artifact set")

        actual_rows: dict[str, list[dict[str, Any]]] = {}
        physical_seals: dict[str, dict[str, Any]] = {}
        expected_rows = {
            "security_daily_features": list(computed.security_rows),
            "market_daily_features": list(computed.market_rows),
            "feature_findings": list(computed.finding_rows),
        }
        for name in FEATURE_ARTIFACT_NAMES:
            entry = artifacts.get(name)
            if not isinstance(entry, dict):
                raise FeatureVerifierError(f"feature artifact {name} has no seal entry")
            artifact_base_uri = feature_manifest_uri(
                str(manifest["snapshot_id"]), feature_run_id
            ).rsplit("/", 1)[0]
            expected_artifact_uri = f"{artifact_base_uri}/{name}.parquet"
            if str(entry.get("uri")) != expected_artifact_uri:
                raise FeatureVerifierError(f"feature artifact {name} URI is not deterministic")
            path = self.feature_root / str(entry["uri"])
            if not path.is_file():
                raise FeatureVerifierError(f"feature artifact {name} is missing")
            data = path.read_bytes()
            content_hash = hashlib.sha256(data).hexdigest()
            if content_hash != str(entry.get("content_hash")):
                raise FeatureVerifierError(f"feature artifact {name} content is tampered")
            frame = pl.read_parquet(io.BytesIO(data))
            actual_schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
            if actual_schema_hash != str(entry.get("schema_hash")):
                raise FeatureVerifierError(f"feature artifact {name} schema hash is rebound")
            if str(frame.schema) != str(feature_artifact_schema(name)):
                raise FeatureVerifierError(f"feature artifact {name} schema differs from registry")
            if frame.height != int(entry.get("row_count", -1)):
                raise FeatureVerifierError(f"feature artifact {name} row count differs from seal")
            rows = frame.to_dicts()
            actual_semantic_hash = semantic_hash(rows)
            if actual_semantic_hash != str(entry.get("semantic_hash")):
                raise FeatureVerifierError(f"feature artifact {name} semantic seal is rebound")
            _compare_rows(name, rows, expected_rows[name])
            actual_rows[name] = rows
            physical_seals[name] = {
                "uri": str(entry["uri"]),
                "content_hash": content_hash,
                "schema_hash": actual_schema_hash,
                "row_count": frame.height,
                "semantic_hash": actual_semantic_hash,
            }

        if _artifact_set_hash(physical_seals) != str(manifest["artifact_set_hash"]):
            raise FeatureVerifierError(
                "feature artifact_set_hash does not match physical artifacts"
            )
        if _artifact_set_hash(physical_seals) != str(record["artifact_set_hash"]):
            raise FeatureVerifierError("feature artifact_set_hash does not match the ledger")
        actual_feature_semantic = _feature_semantic_hash(
            tuple(actual_rows["security_daily_features"]),
            tuple(actual_rows["market_daily_features"]),
        )
        if actual_feature_semantic != str(manifest["feature_semantic_hash"]):
            raise FeatureVerifierError("feature semantic aggregate does not match artifacts")
        if actual_feature_semantic != str(record["feature_semantic_hash"]):
            raise FeatureVerifierError("feature semantic aggregate does not match the ledger")
        actual_finding_hash = semantic_hash(actual_rows["feature_findings"])
        if actual_finding_hash != str(manifest["finding_set_hash"]):
            raise FeatureVerifierError("feature finding set does not match the manifest")
        if actual_finding_hash != str(record["finding_set_hash"]):
            raise FeatureVerifierError("feature finding set does not match the ledger")

        _validate_rows(
            security_rows=actual_rows["security_daily_features"],
            market_rows=actual_rows["market_daily_features"],
            finding_rows=actual_rows["feature_findings"],
            snapshot_id=str(manifest["snapshot_id"]),
            feature_run_id=feature_run_id,
            feature_set_id=str(manifest["feature_set_id"]),
            snapshot_as_of=verified_snapshot.as_of,
            expected_security_columns=(
                "security_id",
                "trade_date",
                "source_snapshot_id",
                "source_canonical_run_id",
                "feature_run_id",
                "feature_set_id",
                "feature_contract_version",
                "feature_available_at",
                "input_lineage_hash",
                "raw_return_1",
                "gap_open_raw",
                "intraday_return_raw",
                "amplitude_preclose_raw",
                "ma_close_obs_5",
                "ma_close_obs_20",
                "ma_close_obs_60",
                "close_to_ma_obs_5",
                "close_to_ma_obs_20",
                "close_to_ma_obs_60",
                "return_lag_obs_5",
                "return_lag_obs_20",
                "return_lag_obs_60",
                "amount_to_mean_obs_20",
                "vol_raw_return_obs_20",
            ),
        )
        return VerifiedFeatureRun(
            feature_run_id=feature_run_id,
            snapshot_id=str(manifest["snapshot_id"]),
            canonical_run_id=verified_snapshot.canonical_run_id,
            feature_set_id=str(manifest["feature_set_id"]),
            manifest=manifest,
            ledger_record=record,
            security_rows=tuple(actual_rows["security_daily_features"]),
            market_rows=tuple(actual_rows["market_daily_features"]),
            finding_rows=tuple(actual_rows["feature_findings"]),
        )


def verify_feature_run_for_consumption(
    conn: Any,
    feature_run_id: str,
    *,
    raw_root: Path,
    normalized_root: Path,
    readmodel_root: Path | None = None,
    feature_root: Path | None = None,
) -> VerifiedFeatureRun:
    """Verify one feature run for downstream State/Research consumption."""
    return FeatureVerifier(
        conn,
        raw_root=raw_root,
        normalized_root=normalized_root,
        readmodel_root=readmodel_root,
        feature_root=feature_root,
    ).verify_feature_run_for_consumption(feature_run_id)
