"""Public CR-6 State consumption verifier with full deterministic replay."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.features.models import canonical_json, semantic_hash
from ashare_state.features.verifier import verify_feature_run_for_consumption
from ashare_state.state.builder import (
    STATE_LEDGER_COLUMNS,
    state_builder_code_fingerprint,
    state_manifest_uri,
)
from ashare_state.state.engine import compute_state_set
from ashare_state.state.models import (
    STATE_CONTRACT_VERSION,
    StateVerifierError,
    VerifiedStateRun,
    state_base_hash_from_primitives,
    state_id_from_base_hash,
)
from ashare_state.state.registry import (
    StateRegistryError,
    StateSet,
    compile_state_execution_plan,
    get_state_set,
)
from ashare_state.state.schema import (
    FINDING_CLASSES,
    STATE_ARTIFACT_NAMES,
    STATE_ENUM_VALUES,
    STATE_EVIDENCE_FEATURES,
    state_artifact_schema,
)

__all__ = [
    "StateVerifier",
    "verify_state_run_for_consumption",
]


def _required_text(values: Mapping[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value:
        raise StateVerifierError(f"{field} is missing from State provenance")
    return value


def _ledger_record(conn: Any, state_run_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {', '.join(STATE_LEDGER_COLUMNS)} FROM meta_state_build WHERE state_run_id = ?",
        [state_run_id],
    ).fetchone()
    if row is None:
        raise StateVerifierError(f"state run {state_run_id} does not exist in the State ledger")
    return dict(zip(STATE_LEDGER_COLUMNS, row, strict=True))


def _check_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise StateVerifierError(f"{field} is not a SHA-256 value")
    if any(char not in "0123456789abcdef" for char in value):
        raise StateVerifierError(f"{field} is not a SHA-256 value")
    return value


def _utc_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise StateVerifierError(f"State {field} is not timezone-aware")
    return value.astimezone(UTC)


def _artifact_set_hash(seals: Mapping[str, Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(seals).encode("utf-8")).hexdigest()


def _compare_rows(
    name: str,
    actual: Sequence[Mapping[str, Any]],
    expected: Sequence[Mapping[str, Any]],
) -> None:
    if len(actual) != len(expected):
        raise StateVerifierError(
            f"State {name} row count differs from deterministic replay: "
            f"{len(actual)} != {len(expected)}"
        )
    for position, (actual_row, expected_row) in enumerate(zip(actual, expected, strict=True)):
        if canonical_json(actual_row) != canonical_json(expected_row):
            differing_fields = [
                field
                for field in sorted(set(actual_row) | set(expected_row))
                if canonical_json(actual_row.get(field)) != canonical_json(expected_row.get(field))
            ]
            raise StateVerifierError(
                f"State {name} row {position} differs from deterministic replay "
                f"at fields: {', '.join(differing_fields)}"
            )


def _validate_state_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    state_run_id: str,
    state_set: StateSet,
    feature_run: Any,
) -> None:
    source_by_date = {row["trade_date"]: row for row in feature_run.market_rows}
    previous_date: date | None = None
    for row in rows:
        trade_date = row.get("trade_date")
        if not isinstance(trade_date, date):
            raise StateVerifierError("State trade_date is not a date")
        if previous_date is not None and trade_date <= previous_date:
            raise StateVerifierError("State market rows are not strictly date-sorted")
        previous_date = trade_date
        source = source_by_date.get(trade_date)
        if source is None:
            raise StateVerifierError("State row has no source Feature market date")
        if row.get("source_feature_run_id") != feature_run.feature_run_id:
            raise StateVerifierError("State row carries a foreign feature_run_id")
        if row.get("state_run_id") != state_run_id:
            raise StateVerifierError("State row carries a foreign state_run_id")
        if row.get("state_set_id") != state_set.state_set_id:
            raise StateVerifierError("State row carries a foreign state_set_id")
        if row.get("state_contract_version") != state_set.contract_version:
            raise StateVerifierError("State row carries a foreign contract version")
        if row.get("source_snapshot_id") != source.get("source_snapshot_id"):
            raise StateVerifierError("State row source_snapshot_id diverges from Feature")
        if row.get("source_canonical_run_id") != feature_run.canonical_run_id:
            raise StateVerifierError("State row source_canonical_run_id diverges from Feature")
        source_available = _utc_datetime(
            source.get("feature_available_at"),
            "feature_available_at",
        )
        if _utc_datetime(row.get("state_available_at"), "state_available_at") != source_available:
            raise StateVerifierError("State row available_at diverges from Feature")
        _check_sha256(
            row.get("source_feature_input_lineage_hash"),
            "source_feature_input_lineage_hash",
        )
        _check_sha256(row.get("input_lineage_hash"), "input_lineage_hash")
        for feature_name in STATE_EVIDENCE_FEATURES:
            evidence_name = f"evidence_{feature_name}"
            if row.get(evidence_name) != source.get(feature_name):
                raise StateVerifierError(f"State evidence {evidence_name} diverges from Feature")
        for state_name, allowed in STATE_ENUM_VALUES.items():
            value = row.get(state_name)
            if not isinstance(value, str) or value not in allowed:
                raise StateVerifierError(f"State {state_name} carries an unknown enum value")


def _validate_finding_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    state_set: StateSet,
) -> None:
    previous_key: tuple[date, str, str, str] | None = None
    for row in rows:
        trade_date = row.get("trade_date")
        state_name = row.get("state_name")
        finding_class = row.get("finding_class")
        detail_json = row.get("detail_json")
        if not isinstance(trade_date, date):
            raise StateVerifierError("State finding trade_date is not a date")
        if not isinstance(state_name, str) or state_name not in state_set.state_names:
            raise StateVerifierError("State finding has an unknown state_name")
        if not isinstance(finding_class, str) or finding_class not in FINDING_CLASSES:
            raise StateVerifierError("State finding has an unknown finding_class")
        if not isinstance(detail_json, str):
            raise StateVerifierError("State finding detail_json is not text")
        key = (trade_date, state_name, finding_class, detail_json)
        if previous_key is not None and key < previous_key:
            raise StateVerifierError("State findings are not deterministically sorted")
        previous_key = key


class StateVerifier:
    """Verify one immutable State run and replay its public Feature input."""

    def __init__(
        self,
        conn: Any,
        *,
        raw_root: Path,
        normalized_root: Path,
        readmodel_root: Path | None = None,
        feature_root: Path | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
        self.readmodel_root = Path(readmodel_root) if readmodel_root else self.normalized_root
        self.feature_root = Path(feature_root) if feature_root else self.normalized_root
        self.state_root = Path(state_root) if state_root else self.normalized_root

    def verify_state_run_for_consumption(self, state_run_id: str) -> VerifiedStateRun:
        record = _ledger_record(self.conn, state_run_id)
        if _required_text(record, "status") != "SUCCESS":
            raise StateVerifierError(
                f"state run {state_run_id} is not SUCCESS and is not consumable"
            )
        if record.get("error_message") is not None:
            raise StateVerifierError("SUCCESS State ledger row carries an error_message")
        feature_run_id = _required_text(record, "feature_run_id")
        state_set_id = _required_text(record, "state_set_id")
        try:
            state_set = get_state_set(state_set_id)
            compile_state_execution_plan(state_set)
        except StateRegistryError as exc:
            raise StateVerifierError(f"State Registry cannot be honestly executed: {exc}") from exc

        record_fields: tuple[tuple[str, Any], ...] = (
            ("state_run_id", state_run_id),
            ("state_contract_version", STATE_CONTRACT_VERSION),
            ("state_set_id", state_set.state_set_id),
            ("state_set_version", state_set.state_set_version),
            ("state_registry_version", state_set.state_registry_version),
            ("state_registry_hash", state_set.registry_hash),
        )
        for field, expected in record_fields:
            if str(record.get(field)) != str(expected):
                raise StateVerifierError(f"State ledger field {field} is not the current contract")

        manifest_uri = _required_text(record, "manifest_uri")
        expected_uri = state_manifest_uri(feature_run_id, state_run_id)
        if manifest_uri != expected_uri:
            raise StateVerifierError("State manifest URI is not deterministic")
        manifest_path = self.state_root / manifest_uri
        if not manifest_path.is_file():
            raise StateVerifierError(f"State manifest is missing: {manifest_uri}")
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != _required_text(record, "manifest_hash"):
            raise StateVerifierError("State manifest bytes do not match the ledger hash")
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StateVerifierError(f"State manifest is unreadable: {exc}") from exc
        if not isinstance(manifest, dict):
            raise StateVerifierError("State manifest must be a JSON object")

        manifest_fields: tuple[tuple[str, Any], ...] = (
            ("state_run_id", state_run_id),
            ("state_contract_version", state_set.contract_version),
            ("state_set_id", state_set.state_set_id),
            ("state_set_version", state_set.state_set_version),
            ("state_registry_version", state_set.state_registry_version),
            ("state_registry_hash", state_set.registry_hash),
            ("feature_run_id", feature_run_id),
            ("feature_manifest_uri", _required_text(record, "feature_manifest_uri")),
            ("feature_manifest_hash", _required_text(record, "feature_manifest_hash")),
            ("feature_semantic_hash", _required_text(record, "feature_semantic_hash")),
            ("feature_set_id", _required_text(record, "feature_set_id")),
            ("feature_registry_hash", _required_text(record, "feature_registry_hash")),
            (
                "state_builder_code_fingerprint",
                _required_text(record, "state_builder_code_fingerprint"),
            ),
            ("artifact_set_hash", _required_text(record, "artifact_set_hash")),
            ("state_semantic_hash", _required_text(record, "state_semantic_hash")),
            ("finding_set_hash", _required_text(record, "finding_set_hash")),
            ("state_row_count", int(record["state_row_count"])),
            ("finding_count", int(record["finding_count"])),
            ("status", "SUCCESS"),
            ("error_message", None),
        )
        for field, expected in manifest_fields:
            if field not in manifest:
                raise StateVerifierError(f"State manifest field {field} is missing")
            actual = manifest[field]
            if expected is None:
                matches = actual is None
            else:
                matches = str(actual) == str(expected)
            if not matches:
                raise StateVerifierError(f"State manifest field {field} does not match the ledger")

        current_fingerprint = state_builder_code_fingerprint()
        if manifest["state_builder_code_fingerprint"] != current_fingerprint:
            raise StateVerifierError(
                "State was built by a different State builder code fingerprint"
            )
        base_hash = state_base_hash_from_primitives(
            feature_run_id=feature_run_id,
            feature_manifest_hash=str(manifest["feature_manifest_hash"]),
            feature_semantic_hash=str(manifest["feature_semantic_hash"]),
            feature_set_id=str(manifest["feature_set_id"]),
            feature_registry_hash=str(manifest["feature_registry_hash"]),
            state_set_id=state_set.state_set_id,
            state_set_version=state_set.state_set_version,
            state_registry_version=state_set.state_registry_version,
            state_registry_hash=state_set.registry_hash,
            state_contract_version=state_set.contract_version,
            state_builder_code_fingerprint=current_fingerprint,
        )
        if manifest.get("state_base_hash") != base_hash:
            raise StateVerifierError("state_base_hash does not match State identity primitives")
        if state_id_from_base_hash(base_hash) != state_run_id:
            raise StateVerifierError("state_run_id does not match UUID5 identity recompute")

        try:
            feature_run = verify_feature_run_for_consumption(
                self.conn,
                feature_run_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
                readmodel_root=self.readmodel_root,
                feature_root=self.feature_root,
            )
        except Exception as exc:
            raise StateVerifierError(
                f"upstream Feature run {feature_run_id} cannot be verified"
            ) from exc
        if feature_run.feature_run_id != feature_run_id:
            raise StateVerifierError("upstream Feature verifier returned a foreign run")
        feature_record = feature_run.ledger_record
        provenance = (
            ("manifest_uri", manifest["feature_manifest_uri"]),
            ("manifest_hash", manifest["feature_manifest_hash"]),
            ("feature_semantic_hash", manifest["feature_semantic_hash"]),
            ("feature_registry_hash", manifest["feature_registry_hash"]),
        )
        for field, expected in provenance:
            if str(feature_record.get(field)) != str(expected):
                raise StateVerifierError(f"State upstream Feature {field} provenance diverges")
        if feature_run.feature_set_id != manifest["feature_set_id"]:
            raise StateVerifierError("State upstream Feature set diverges")

        computed = compute_state_set(
            feature_run,
            state_run_id=state_run_id,
            state_set=state_set,
        )
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict):
            raise StateVerifierError("State manifest carries no artifact map")
        if set(artifacts) != set(STATE_ARTIFACT_NAMES):
            raise StateVerifierError("State artifact set is not the exact V1 set")

        expected_rows: dict[str, list[Mapping[str, Any]]] = {
            "market_daily_state": list(computed.state_rows),
            "state_findings": list(computed.finding_rows),
        }
        actual_rows: dict[str, list[dict[str, Any]]] = {}
        physical_seals: dict[str, dict[str, Any]] = {}
        artifact_base_uri = manifest_uri.rsplit("/", 1)[0]
        for name in STATE_ARTIFACT_NAMES:
            entry = artifacts.get(name)
            if not isinstance(entry, dict):
                raise StateVerifierError(f"State artifact {name} has no seal entry")
            expected_artifact_uri = f"{artifact_base_uri}/{name}.parquet"
            if str(entry.get("uri")) != expected_artifact_uri:
                raise StateVerifierError(f"State artifact {name} URI is not deterministic")
            path = self.state_root / str(entry["uri"])
            if not path.is_file():
                raise StateVerifierError(f"State artifact {name} is missing")
            data = path.read_bytes()
            content_hash = hashlib.sha256(data).hexdigest()
            if content_hash != str(entry.get("content_hash")):
                raise StateVerifierError(f"State artifact {name} content is tampered")
            try:
                frame = pl.read_parquet(io.BytesIO(data))
            except Exception as exc:
                raise StateVerifierError(f"State artifact {name} is not readable parquet") from exc
            schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
            if schema_hash != str(entry.get("schema_hash")):
                raise StateVerifierError(f"State artifact {name} schema hash is rebound")
            if str(frame.schema) != str(state_artifact_schema(name)):
                raise StateVerifierError(
                    f"State artifact {name} schema differs from the State contract"
                )
            try:
                sealed_row_count = int(entry.get("row_count", -1))
            except (TypeError, ValueError) as exc:
                raise StateVerifierError(
                    f"State artifact {name} row_count is not an integer"
                ) from exc
            if isinstance(entry.get("row_count"), bool) or frame.height != sealed_row_count:
                raise StateVerifierError(f"State artifact {name} row count differs from its seal")
            rows = frame.to_dicts()
            semantic = semantic_hash(rows)
            if semantic != str(entry.get("semantic_hash")):
                raise StateVerifierError(f"State artifact {name} semantic seal is rebound")
            _compare_rows(name, rows, expected_rows[name])
            actual_rows[name] = rows
            physical_seals[name] = {
                "uri": str(entry["uri"]),
                "content_hash": content_hash,
                "schema_hash": schema_hash,
                "row_count": frame.height,
                "semantic_hash": semantic,
            }

        _validate_state_rows(
            actual_rows["market_daily_state"],
            state_run_id=state_run_id,
            state_set=state_set,
            feature_run=feature_run,
        )
        _validate_finding_rows(
            actual_rows["state_findings"],
            state_set=state_set,
        )
        if _artifact_set_hash(physical_seals) != str(manifest["artifact_set_hash"]):
            raise StateVerifierError("State artifact_set_hash does not match physical artifacts")
        if _artifact_set_hash(physical_seals) != str(record["artifact_set_hash"]):
            raise StateVerifierError("State artifact_set_hash does not match the ledger")

        actual_state_semantic = semantic_hash(actual_rows["market_daily_state"])
        actual_finding_hash = semantic_hash(actual_rows["state_findings"])
        if actual_state_semantic != str(manifest["state_semantic_hash"]):
            raise StateVerifierError("State semantic aggregate does not match the manifest")
        if actual_state_semantic != str(record["state_semantic_hash"]):
            raise StateVerifierError("State semantic aggregate does not match the ledger")
        if actual_finding_hash != str(manifest["finding_set_hash"]):
            raise StateVerifierError("State finding set does not match the manifest")
        if actual_finding_hash != str(record["finding_set_hash"]):
            raise StateVerifierError("State finding set does not match the ledger")

        physical_counts = {
            "state_row_count": len(actual_rows["market_daily_state"]),
            "finding_count": len(actual_rows["state_findings"]),
        }
        for field, actual_count in physical_counts.items():
            try:
                manifest_count = manifest[field]
                record_count = record[field]
                if isinstance(manifest_count, bool) or int(manifest_count) != actual_count:
                    raise StateVerifierError(f"State manifest {field} does not match physical rows")
                if isinstance(record_count, bool) or int(record_count) != actual_count:
                    raise StateVerifierError(f"State ledger {field} does not match physical rows")
            except (KeyError, TypeError, ValueError) as exc:
                raise StateVerifierError(f"State count field {field} is not an integer") from exc

        return VerifiedStateRun(
            state_run_id=state_run_id,
            feature_run_id=feature_run_id,
            state_set_id=state_set.state_set_id,
            manifest=manifest,
            ledger_record=record,
            state_rows=tuple(actual_rows["market_daily_state"]),
            finding_rows=tuple(actual_rows["state_findings"]),
        )


def verify_state_run_for_consumption(
    conn: Any,
    state_run_id: str,
    *,
    raw_root: Path,
    normalized_root: Path,
    readmodel_root: Path | None = None,
    feature_root: Path | None = None,
    state_root: Path | None = None,
) -> VerifiedStateRun:
    """Verify one State run for downstream descriptive-state consumption."""
    return StateVerifier(
        conn,
        raw_root=raw_root,
        normalized_root=normalized_root,
        readmodel_root=readmodel_root,
        feature_root=feature_root,
        state_root=state_root,
    ).verify_state_run_for_consumption(state_run_id)
