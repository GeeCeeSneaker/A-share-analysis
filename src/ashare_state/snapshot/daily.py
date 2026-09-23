"""Logical daily-bar Snapshot seal consumption and explicit deep audit.

Ordinary consumption checks the small logical manifests, exact partition
bindings, artifact footers and file existence. It deliberately does not hash
or scan the daily fact payloads; that work belongs to the explicit deep audit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from ashare_state.canonical.canonicalizer import _canonical_json, _rows_semantic_hash
from ashare_state.canonical.daily_bar import (
    DAILY_BAR_FACT_FIELDS,
    DAILY_BAR_PARTITION_CONTRACT,
    DailyBarPartitionError,
    iter_daily_bar_partition_rows,
)
from ashare_state.canonical.verifier import (
    CanonicalConsumptionError,
    read_canonical_run_manifest,
)
from ashare_state.snapshot.builder import (
    LOGICAL_DAILY_SNAPSHOT_CONTRACT,
    SNAPSHOT_LEDGER_COLUMNS,
    logical_daily_snapshot_manifest_uri,
    snapshot_builder_code_fingerprint,
)
from ashare_state.snapshot.models import (
    SnapshotVerifierError,
    VerifiedSnapshot,
    snapshot_base_hash_from_primitives,
    snapshot_id_from_base_hash,
)
from ashare_state.storage.paths import validate_logical_uri

_FACT_NAMES = ("security_id", "trade_date", *DAILY_BAR_FACT_FIELDS)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise SnapshotVerifierError(f"logical daily snapshot {field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotVerifierError(f"logical daily snapshot {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise SnapshotVerifierError(f"logical daily snapshot {field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _json_equal(left: Any, right: Any) -> bool:
    return _canonical_json(left) == _canonical_json(right)


def _parquet_metadata(
    path: Path,
    expected_names: tuple[str, ...],
    *,
    fixed16_identity: bool = False,
    expected_schema_hash: str,
) -> int:
    try:
        parquet = pq.ParquetFile(path)
        metadata = parquet.metadata
        schema = parquet.schema_arrow
    except Exception as exc:  # noqa: BLE001 - fail closed at the artifact boundary
        raise SnapshotVerifierError(
            f"daily partition Parquet footer is unreadable: {path}"
        ) from exc
    if metadata is None or tuple(schema.names) != expected_names:
        raise SnapshotVerifierError(f"daily partition Parquet schema is invalid: {path}")
    if fixed16_identity and schema.field("security_id").type != pa.binary(16):
        raise SnapshotVerifierError(f"daily partition identity is not fixed16 UUID: {path}")
    schema_hash = hashlib.sha256(str(schema).encode("utf-8")).hexdigest()
    if schema_hash != expected_schema_hash:
        raise SnapshotVerifierError(f"daily partition schema hash differs from its seal: {path}")
    return int(metadata.num_rows)


def validate_canonical_daily_partition_set(
    normalized_root: Path,
    partitions: list[dict[str, Any]],
    *,
    market_as_of: datetime,
    source_vintage_as_of: datetime,
) -> None:
    """Validate exact small partition seals and Parquet footers, not fact payloads."""
    partition_vintages = [
        _utc(entry.get("source_vintage_as_of"), field="partition source_vintage_as_of")
        for entry in partitions
    ]
    if max(partition_vintages, default=source_vintage_as_of) != source_vintage_as_of:
        raise SnapshotVerifierError("Snapshot source_vintage_as_of differs from its partitions")
    for entry in partitions:
        partition_uri = validate_logical_uri(str(entry.get("partition_manifest_uri", "")))
        partition_path = Path(normalized_root) / partition_uri
        if not partition_path.is_file() or _sha256_file(partition_path) != str(
            entry.get("partition_manifest_hash")
        ):
            raise SnapshotVerifierError(
                "Canonical daily-bar partition manifest is missing/tampered"
            )
        try:
            partition_doc = json.loads(partition_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotVerifierError(
                "Canonical daily-bar partition manifest is unreadable"
            ) from exc
        if not isinstance(partition_doc, dict):
            raise SnapshotVerifierError("Canonical daily-bar partition manifest root is invalid")
        variable_fields = partition_doc.get("variable_fields")
        if not isinstance(variable_fields, list) or any(
            not isinstance(name, str) for name in variable_fields
        ):
            raise SnapshotVerifierError("Canonical daily-bar variable lineage schema is invalid")
        if (
            partition_doc.get("contract_version") != DAILY_BAR_PARTITION_CONTRACT
            or partition_doc.get("logical_partition_id") != entry.get("logical_partition_id")
            or partition_doc.get("data_revision") != entry.get("data_revision")
            or partition_doc.get("logical_content_hash") != entry.get("logical_content_hash")
            or partition_doc.get("layout_revision") != entry.get("layout_revision")
            or partition_doc.get("artifact_set_hash") != entry.get("artifact_set_hash")
            or partition_doc.get("market_as_of") != market_as_of.isoformat()
            or partition_doc.get("source_vintage_as_of") != entry.get("source_vintage_as_of")
            or int(partition_doc.get("row_count", -1)) != int(entry.get("row_count", -2))
        ):
            raise SnapshotVerifierError("Canonical daily-bar partition manifest binding differs")
        for key, expected_names in (
            ("fact_artifact", _FACT_NAMES),
            ("lineage_artifact", ("security_id", "trade_date", *variable_fields)),
        ):
            artifact = partition_doc.get(key)
            if not isinstance(artifact, dict) or artifact != entry.get(key):
                raise SnapshotVerifierError(f"daily partition {key} differs from Canonical seal")
            uri = validate_logical_uri(str(artifact.get("uri", "")))
            path = Path(normalized_root) / uri
            if not path.is_file():
                raise SnapshotVerifierError(f"daily partition artifact missing: {uri}")
            if _parquet_metadata(
                path,
                tuple(expected_names),
                fixed16_identity=True,
                expected_schema_hash=str(artifact.get("schema_hash", "")),
            ) != int(entry["row_count"]):
                raise SnapshotVerifierError(f"daily partition artifact row count differs: {uri}")


def _load_sealed_snapshot(
    conn: Any,
    snapshot_id: str,
    *,
    normalized_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], datetime, datetime, datetime]:
    row = conn.execute(
        f"SELECT {', '.join(SNAPSHOT_LEDGER_COLUMNS)} FROM meta_snapshot_build "
        "WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchone()
    if row is None:
        raise SnapshotVerifierError(f"snapshot {snapshot_id} does not exist in the snapshot ledger")
    record = dict(zip(SNAPSHOT_LEDGER_COLUMNS, row, strict=True))
    if str(record["snapshot_contract_version"]) != LOGICAL_DAILY_SNAPSHOT_CONTRACT:
        raise SnapshotVerifierError("snapshot does not use the logical daily-bar contract")
    if str(record["status"]) != "SUCCESS":
        raise SnapshotVerifierError("only SUCCESS logical daily snapshots may be consumed")
    market_as_of = record["canonical_as_of"]
    if not isinstance(market_as_of, datetime):
        raise SnapshotVerifierError("logical daily snapshot ledger has no market_as_of")
    market_as_of = (
        market_as_of.astimezone(UTC) if market_as_of.tzinfo else market_as_of.replace(tzinfo=UTC)
    )

    try:
        _canonical_record, canonical_manifest, canonical_as_of = read_canonical_run_manifest(
            conn, str(record["canonical_run_id"]), normalized_root=Path(normalized_root)
        )
    except CanonicalConsumptionError as exc:
        raise SnapshotVerifierError(
            f"logical daily snapshot Canonical seal is invalid: {exc}"
        ) from exc
    if canonical_as_of != market_as_of:
        raise SnapshotVerifierError("logical daily snapshot market_as_of differs from Canonical")
    if str(_canonical_record["manifest_uri"]) != str(record["canonical_manifest_uri"]) or str(
        _canonical_record["manifest_hash"]
    ) != str(record["canonical_manifest_hash"]):
        raise SnapshotVerifierError("logical daily snapshot Canonical provenance is rebound")
    canonical_partitions = canonical_manifest.get("daily_bar_partitions", [])
    if not isinstance(canonical_partitions, list) or any(
        not isinstance(entry, dict) for entry in canonical_partitions
    ):
        raise SnapshotVerifierError("Canonical daily-bar partition manifest list is invalid")
    source_vintage_as_of = max(
        (
            _utc(entry.get("source_vintage_as_of"), field="partition source_vintage_as_of")
            for entry in canonical_partitions
        ),
        default=market_as_of,
    )
    expected_uri = logical_daily_snapshot_manifest_uri(
        snapshot_id, market_as_of, source_vintage_as_of
    )
    manifest_uri = validate_logical_uri(str(record["manifest_uri"]))
    if manifest_uri != expected_uri:
        raise SnapshotVerifierError("logical daily snapshot manifest URI is not deterministic")

    manifest_path = Path(normalized_root) / manifest_uri
    if not manifest_path.is_file():
        raise SnapshotVerifierError(f"logical daily snapshot manifest missing: {manifest_uri}")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != str(record["manifest_hash"]):
        raise SnapshotVerifierError("logical daily snapshot manifest hash differs from ledger")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotVerifierError("logical daily snapshot manifest is unreadable") from exc
    if not isinstance(manifest, dict):
        raise SnapshotVerifierError("logical daily snapshot manifest root is invalid")

    manifest_source_vintage_as_of = _utc(
        manifest.get("source_vintage_as_of"), field="source_vintage_as_of"
    )
    if manifest_source_vintage_as_of != source_vintage_as_of:
        raise SnapshotVerifierError("Snapshot source_vintage_as_of differs from Canonical")
    try:
        requested_domains = json.loads(str(record["requested_domains_json"]))
    except json.JSONDecodeError as exc:
        raise SnapshotVerifierError("logical daily snapshot ledger domains are unreadable") from exc
    if (
        not isinstance(requested_domains, list)
        or manifest.get("requested_domains") != requested_domains
    ):
        raise SnapshotVerifierError("logical daily snapshot domains differ from the ledger")
    expected_fields = {
        "snapshot_id": snapshot_id,
        "snapshot_contract_version": LOGICAL_DAILY_SNAPSHOT_CONTRACT,
        "canonical_run_id": str(record["canonical_run_id"]),
        "canonical_manifest_uri": str(record["canonical_manifest_uri"]),
        "canonical_manifest_hash": str(record["canonical_manifest_hash"]),
        "market_as_of": market_as_of.isoformat(),
        "canonical_requested_domains_hash": str(record["requested_domains_hash"]),
        "snapshot_builder_code_fingerprint": str(record["builder_code_fingerprint"]),
        "artifact_set_hash": str(record["artifact_set_hash"]),
        "snapshot_semantic_hash": str(record["snapshot_semantic_hash"]),
        "status": "SUCCESS",
    }
    if any(str(manifest.get(key)) != value for key, value in expected_fields.items()):
        raise SnapshotVerifierError("logical daily snapshot manifest differs from its ledger seal")
    if (
        str(manifest.get("snapshot_builder_code_fingerprint"))
        != snapshot_builder_code_fingerprint()
    ):
        raise SnapshotVerifierError("snapshot was built by a DIFFERENT snapshot builder")
    if int(manifest.get("row_count_total", -1)) != int(record["row_count_total"]):
        raise SnapshotVerifierError("logical daily snapshot row_count_total differs from ledger")

    base_hash = snapshot_base_hash_from_primitives(
        canonical_run_id=str(manifest["canonical_run_id"]),
        canonical_manifest_hash=str(manifest["canonical_manifest_hash"]),
        canonical_requested_domains_hash=str(manifest["canonical_requested_domains_hash"]),
        canonical_selected_semantic_hash=str(manifest["canonical_selected_semantic_hash"]),
        canonical_as_of=str(manifest["market_as_of"]),
        snapshot_contract_version=LOGICAL_DAILY_SNAPSHOT_CONTRACT,
        snapshot_builder_code_fingerprint=str(manifest["snapshot_builder_code_fingerprint"]),
    )
    if (
        manifest.get("snapshot_base_hash") != base_hash
        or snapshot_id_from_base_hash(base_hash) != snapshot_id
    ):
        raise SnapshotVerifierError("logical daily snapshot identity does not recompute")

    if str(manifest.get("canonical_selected_semantic_hash")) != str(
        _canonical_record["selected_semantic_hash"]
    ):
        raise SnapshotVerifierError("logical daily snapshot Canonical semantic seal is rebound")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(requested_domains):
        raise SnapshotVerifierError("logical daily snapshot artifact set differs from domains")
    canonical_partitions = canonical_manifest.get("daily_bar_partitions")
    daily_artifact = artifacts.get("daily_bar")
    if "daily_bar" in requested_domains:
        if not isinstance(canonical_partitions, list) or not isinstance(daily_artifact, dict):
            raise SnapshotVerifierError("logical daily snapshot has no Canonical partition set")
        if daily_artifact.get("kind") != "canonical_partition_set":
            raise SnapshotVerifierError(
                "daily_bar Snapshot artifact is not a logical partition set"
            )
        partitions = daily_artifact.get("partitions")
        if not isinstance(partitions, list) or not _json_equal(partitions, canonical_partitions):
            raise SnapshotVerifierError(
                "daily_bar Snapshot does not reference exact Canonical partitions"
            )
        if any(not isinstance(entry, dict) for entry in canonical_partitions):
            raise SnapshotVerifierError("Canonical daily-bar partition descriptor is invalid")
        expected_daily_semantic_hash = hashlib.sha256(
            _canonical_json(
                [
                    {
                        "logical_partition_id": entry["logical_partition_id"],
                        "data_revision": entry["data_revision"],
                        "logical_content_hash": entry["logical_content_hash"],
                        "row_count": int(entry["row_count"]),
                    }
                    for entry in canonical_partitions
                ]
            ).encode("utf-8")
        ).hexdigest()
        if expected_daily_semantic_hash != str(daily_artifact.get("semantic_hash")):
            raise SnapshotVerifierError("daily_bar logical Snapshot semantic hash differs")
        expected_daily_artifact_set_hash = hashlib.sha256(
            _canonical_json(
                [
                    {
                        "logical_partition_id": entry["logical_partition_id"],
                        "layout_revision": entry["layout_revision"],
                        "artifact_set_hash": entry["artifact_set_hash"],
                        "partition_manifest_uri": entry["partition_manifest_uri"],
                        "partition_manifest_hash": entry["partition_manifest_hash"],
                    }
                    for entry in canonical_partitions
                ]
            ).encode("utf-8")
        ).hexdigest()
        if expected_daily_artifact_set_hash != str(daily_artifact.get("artifact_set_hash")):
            raise SnapshotVerifierError("daily_bar physical artifact-set hash differs")
        if int(daily_artifact.get("row_count", -1)) != sum(
            int(entry.get("row_count", -1)) for entry in canonical_partitions
        ):
            raise SnapshotVerifierError("daily_bar partition-set row count is invalid")
        validate_canonical_daily_partition_set(
            Path(normalized_root),
            canonical_partitions,
            market_as_of=market_as_of,
            source_vintage_as_of=source_vintage_as_of,
        )

    artifact_row_count = 0
    for domain, entry in artifacts.items():
        if not isinstance(entry, dict):
            raise SnapshotVerifierError(f"snapshot artifact descriptor for {domain} is invalid")
        artifact_row_count += int(entry.get("row_count", -1))
        if domain == "daily_bar":
            continue
        if entry.get("kind") != "snapshot_parquet":
            raise SnapshotVerifierError(f"non-daily artifact {domain} has an unexpected kind")
        uri = validate_logical_uri(str(entry.get("uri", "")))
        path = Path(normalized_root) / uri
        if not path.is_file() or _sha256_file(path) != str(entry.get("content_hash")):
            raise SnapshotVerifierError(f"small Snapshot artifact {domain} is missing/tampered")
        try:
            frame = pl.read_parquet(path)
        except Exception as exc:  # noqa: BLE001 - small dimension artifacts only
            raise SnapshotVerifierError(f"small Snapshot artifact {domain} is unreadable") from exc
        schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
        rows = frame.to_dicts()
        if (
            schema_hash != str(entry.get("schema_hash"))
            or frame.height != int(entry.get("row_count", -1))
            or _rows_semantic_hash(rows) != str(entry.get("semantic_hash"))
        ):
            raise SnapshotVerifierError(f"small Snapshot artifact {domain} seal differs")
    if artifact_row_count != int(record["row_count_total"]):
        raise SnapshotVerifierError("logical daily snapshot aggregate row count differs")
    if hashlib.sha256(_canonical_json(artifacts).encode("utf-8")).hexdigest() != str(
        record["artifact_set_hash"]
    ):
        raise SnapshotVerifierError("logical daily snapshot artifact_set_hash does not recompute")
    semantic_hash = hashlib.sha256(
        _canonical_json({name: item["semantic_hash"] for name, item in artifacts.items()}).encode(
            "utf-8"
        )
    ).hexdigest()
    if semantic_hash != str(record["snapshot_semantic_hash"]):
        raise SnapshotVerifierError("logical daily snapshot semantic hash does not recompute")
    return record, manifest, market_as_of, source_vintage_as_of, canonical_as_of


def consume_logical_daily_snapshot(
    conn: Any,
    snapshot_id: str,
    *,
    normalized_root: Path,
) -> VerifiedSnapshot:
    """Consume a logical daily snapshot without scanning fact payloads."""
    record, manifest, market_as_of, source_vintage_as_of, _ = _load_sealed_snapshot(
        conn, snapshot_id, normalized_root=normalized_root
    )
    domains = tuple(str(item) for item in manifest["requested_domains"])
    return VerifiedSnapshot(
        snapshot_id=snapshot_id,
        canonical_run_id=str(manifest["canonical_run_id"]),
        as_of=market_as_of,
        requested_domains=domains,
        ledger_record=record,
        manifest=manifest,
        domain_rows=dict.fromkeys(domains, ()),
        market_as_of=market_as_of,
        source_vintage_as_of=source_vintage_as_of,
    )


def deep_verify_logical_daily_snapshot(
    conn: Any,
    snapshot_id: str,
    *,
    raw_root: Path,
    normalized_root: Path,
) -> VerifiedSnapshot:
    """Explicitly scan and audit exact Canonical daily facts and lineage.

    Rows are streamed and not retained in the returned Snapshot object. Raw
    acquisition ledgers are not replayed here; Canonical's own producer audit
    owns that boundary, while this audit checks the sealed daily artifacts.
    """
    verified = consume_logical_daily_snapshot(conn, snapshot_id, normalized_root=normalized_root)
    del raw_root  # the explicit daily fact audit does not reacquire/replay provider inputs

    for entry in verified.manifest["artifacts"]["daily_bar"]["partitions"]:
        digest = hashlib.sha256()
        digest.update(b"[")
        first = True
        count = 0
        try:
            for row in iter_daily_bar_partition_rows(normalized_root, entry):
                if not first:
                    digest.update(b",")
                first = False
                logical = {
                    "security_id": str(row["security_id"]),
                    "trade_date": row["trade_date"],
                    **{field: row.get(field) for field in DAILY_BAR_FACT_FIELDS},
                }
                digest.update(_canonical_json(logical).encode("utf-8"))
                count += 1
        except (DailyBarPartitionError, OSError, ValueError, TypeError, KeyError) as exc:
            raise SnapshotVerifierError(f"daily-bar deep audit failed: {exc}") from exc
        digest.update(b"]")
        logical_hash = digest.hexdigest()
        if count != int(entry["row_count"]):
            raise SnapshotVerifierError("daily-bar deep audit row count differs")
        if logical_hash != str(entry["logical_content_hash"]):
            raise SnapshotVerifierError("daily-bar logical content hash does not match fact rows")
        if str(entry["data_revision"]) != logical_hash:
            raise SnapshotVerifierError("daily-bar data_revision differs from logical content hash")
    return verified
