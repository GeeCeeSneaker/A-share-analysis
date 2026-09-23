"""Monthly L0 storage for the authoritative daily-bar fact plane.

The Parquet fact contains only the governed UUID key, trade date and the
seven daily market values.  Row-level evidence that still has a concrete
consumer is kept in a narrow key-aligned sidecar; partition-constant lineage
is sealed once in the manifest.  Snapshot and DuckDB layers reference these
files instead of copying their rows.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from ashare_state.canonical.daily_bar_event import (
    DailyBarEventContractError,
    daily_bar_event_eligibility_binding,
    daily_bar_latest_session_close_at,
    validate_daily_bar_event_eligibility_binding,
)
from ashare_state.storage.atomic_files import write_file_atomic
from ashare_state.storage.paths import validate_logical_uri

DAILY_BAR_PARTITION_CONTRACT = "security-bar-1d-v2"
DAILY_BAR_LAYOUT_REVISION = "l0-month-fixed16-v1"
DAILY_BAR_FACT_SCHEMA_VERSION = "security-bar-1d-fact-v1"
DAILY_BAR_FACT_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
)
_DERIVED_COLUMNS = frozenset(
    {"canonical_domain", "canonical_key", "canonical_run_id", "security_id", "trade_date"}
)
_LINEAGE_KEY_COLUMNS = ("security_id", "trade_date")
_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
_SOURCE_VINTAGE_RECEIPT_FIELDS = (
    "run_id",
    "role",
    "provider",
    "provider_dataset",
    "endpoint",
    "raw_request_id",
    "raw_evidence_uri",
    "raw_evidence_hash",
    "normalized_manifest_uri",
    "normalized_manifest_hash",
    "received_at",
)


class DailyBarPartitionError(ValueError):
    """Daily-bar partition data or a sealed artifact is invalid."""


def _canonical_json(value: Any) -> str:
    def default(item: Any) -> str:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        raise TypeError(f"unsupported value in daily-bar seal: {type(item).__name__}")

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=default
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _immutable_write(path: Path, payload: bytes) -> None:
    write_file_atomic(path, payload, allow_existing_identical=True)


def _trade_date(value: Any) -> date:
    if isinstance(value, datetime):
        raise DailyBarPartitionError("trade_date must be a date, not a datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise DailyBarPartitionError(f"invalid trade_date {value!r}") from exc
    raise DailyBarPartitionError(f"invalid trade_date type {type(value).__name__}")


def normalize_source_vintage_evidence(
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], datetime]:
    """Validate and bind the exact retained receipts used for daily truth."""
    if isinstance(evidence, (str, bytes)) or not isinstance(evidence, Sequence) or not evidence:
        raise DailyBarPartitionError("daily-bar source-vintage evidence must be a non-empty list")
    normalized: list[dict[str, str]] = []
    seen_runs: set[str] = set()
    for index, entry in enumerate(evidence):
        if not isinstance(entry, Mapping) or set(entry) != set(_SOURCE_VINTAGE_RECEIPT_FIELDS):
            raise DailyBarPartitionError(
                f"source-vintage receipt {index} has an unexpected field set"
            )
        receipt = {field: str(entry[field]).strip() for field in _SOURCE_VINTAGE_RECEIPT_FIELDS}
        empty_fields = [field for field in _SOURCE_VINTAGE_RECEIPT_FIELDS if not receipt[field]]
        if empty_fields:
            raise DailyBarPartitionError(
                f"source-vintage receipt {index} has empty fields {empty_fields}"
            )
        if receipt["role"] != "source" or receipt["provider_dataset"] != "daily_bar":
            raise DailyBarPartitionError(
                "daily-bar source-vintage evidence must use daily_bar source runs only"
            )
        if receipt["run_id"] in seen_runs:
            raise DailyBarPartitionError("source-vintage evidence repeats a normalization run")
        seen_runs.add(receipt["run_id"])
        for name in ("raw_evidence_hash", "normalized_manifest_hash"):
            if re.fullmatch(r"[0-9a-f]{64}", receipt[name]) is None:
                raise DailyBarPartitionError(
                    f"source-vintage receipt {index} has an invalid {name}"
                )
        try:
            receipt["normalized_manifest_uri"] = validate_logical_uri(
                receipt["normalized_manifest_uri"]
            )
        except ValueError as exc:
            raise DailyBarPartitionError(
                f"source-vintage receipt {index} has an invalid normalized manifest URI"
            ) from exc
        try:
            received_at = datetime.fromisoformat(receipt["received_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise DailyBarPartitionError(
                f"source-vintage receipt {index} has an invalid received_at"
            ) from exc
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise DailyBarPartitionError(
                f"source-vintage receipt {index} received_at must be timezone-aware"
            )
        receipt["received_at"] = received_at.astimezone(UTC).isoformat()
        normalized.append(receipt)
    if not normalized:
        raise DailyBarPartitionError("source-vintage evidence does not bind a daily_bar source")
    normalized.sort(key=lambda item: (item["role"], item["provider_dataset"], item["run_id"]))
    source_vintage_as_of = max(datetime.fromisoformat(item["received_at"]) for item in normalized)
    return normalized, source_vintage_as_of


def _identity(value: Any) -> tuple[UUID, bytes]:
    try:
        parsed = UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DailyBarPartitionError(f"invalid governed security_id {value!r}") from exc
    return parsed, parsed.bytes


def _lineage_polars_dtype(values: Sequence[Any]) -> Any:
    """Choose a lossless physical dtype for one row-varying lineage field."""
    present = [value for value in values if value is not None]
    if not present:
        return pl.String
    kinds = {
        "bool"
        if isinstance(value, bool)
        else "int"
        if isinstance(value, int)
        else "float"
        if isinstance(value, float)
        else "datetime"
        if isinstance(value, datetime)
        else "date"
        if isinstance(value, date)
        else "string"
        if isinstance(value, str)
        else "binary"
        if isinstance(value, bytes)
        else type(value).__name__
        for value in present
    }
    if len(kinds) != 1:
        raise DailyBarPartitionError(
            f"row-varying lineage field has mixed physical types: {sorted(kinds)}"
        )
    kind = next(iter(kinds))
    if kind == "bool":
        return pl.Boolean
    if kind == "int":
        return pl.Int64
    if kind == "float":
        return pl.Float64
    if kind == "datetime":
        aware = {value.tzinfo is not None for value in present}
        if len(aware) != 1:
            raise DailyBarPartitionError("lineage datetime mixes aware and naive values")
        timezone = "UTC" if next(iter(aware)) else None
        return pl.Datetime("us", timezone)
    if kind == "date":
        return pl.Date
    if kind == "string":
        return pl.String
    if kind == "binary":
        return pl.Binary
    raise DailyBarPartitionError(f"unsupported row-varying lineage type: {kind}")


def _partition_base_uri(
    partition_id: str, data_revision: str, layout_revision: str, artifact_set_hash: str
) -> str:
    return (
        "canonical/security_bar_1d/"
        f"partition={partition_id}/data_revision={data_revision}/"
        f"layout_revision={layout_revision}/artifact_set={artifact_set_hash}"
    )


def _iter_monthly_entries(
    rows: Iterable[Mapping[str, Any]],
) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Validate time-first input and retain only the current month in memory."""
    partition_id: str | None = None
    entries: list[dict[str, Any]] = []
    previous_key: tuple[date, bytes] | None = None
    for source in rows:
        if source.get("canonical_domain") != "daily_bar":
            raise DailyBarPartitionError("partition input contains a non-daily_bar row")
        security_id, physical_id = _identity(source.get("security_id"))
        trade_day = _trade_date(source.get("trade_date"))
        key = (trade_day, physical_id)
        if previous_key is not None and key <= previous_key:
            raise DailyBarPartitionError(
                "daily_bar partition input is not strictly time-first sorted"
            )
        previous_key = key
        next_partition = trade_day.strftime("%Y-%m")
        if partition_id is not None and next_partition != partition_id:
            yield partition_id, entries
            entries = []
        partition_id = next_partition

        expected_key = _canonical_json([str(security_id), trade_day.isoformat()])
        if source.get("canonical_key") != expected_key:
            raise DailyBarPartitionError("daily_bar row canonical key diverges from its identity")
        payload = {field: source.get(field) for field in DAILY_BAR_FACT_FIELDS}
        fact = {"security_id": physical_id, "trade_date": trade_day, **payload}
        logical = {
            "security_id": str(security_id),
            "trade_date": trade_day.isoformat(),
            **payload,
        }
        lineage = {
            str(name): value
            for name, value in source.items()
            if name not in _DERIVED_COLUMNS and name not in DAILY_BAR_FACT_FIELDS
        }
        entries.append(
            {"fact": fact, "logical": logical, "lineage": lineage, "security_id": physical_id}
        )
    if partition_id is not None:
        yield partition_id, entries


def write_daily_bar_partitions(
    rows: Iterable[Mapping[str, Any]],
    *,
    normalized_root: Path,
    source_snapshot_as_of: datetime,
    source_vintage_evidence_by_partition: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, Any], ...]:
    """Write daily rows into immutable monthly L0 partitions.

    The function is called only at the Canonical producer boundary. Exact
    retries reuse identical bytes; a logical correction receives a new
    ``data_revision`` while the prior closed-month artifact remains intact.
    """
    if source_snapshot_as_of.tzinfo is None or source_snapshot_as_of.utcoffset() is None:
        raise DailyBarPartitionError("source_snapshot_as_of must be timezone-aware")
    results: list[dict[str, Any]] = []
    root = Path(normalized_root)
    for partition_id, entries in _iter_monthly_entries(rows):
        try:
            partition_evidence = source_vintage_evidence_by_partition[partition_id]
        except KeyError as exc:
            raise DailyBarPartitionError(
                f"daily-bar partition {partition_id} has no source-vintage evidence"
            ) from exc
        normalized_vintage_evidence, source_vintage_as_of = normalize_source_vintage_evidence(
            partition_evidence
        )
        try:
            market_as_of = daily_bar_latest_session_close_at(
                max(item["fact"]["trade_date"] for item in entries)
            )
        except DailyBarEventContractError as exc:
            raise DailyBarPartitionError(f"daily-bar event boundary is invalid: {exc}") from exc
        if market_as_of > source_snapshot_as_of:
            raise DailyBarPartitionError(
                "daily-bar event boundary is after the source snapshot cutoff"
            )
        if source_vintage_as_of > source_snapshot_as_of:
            raise DailyBarPartitionError(
                "source_vintage_as_of is after the retained source snapshot cutoff"
            )
        logical_digest = hashlib.sha256()
        logical_digest.update(b"[")
        for ordinal, entry in enumerate(entries):
            if ordinal:
                logical_digest.update(b",")
            logical_digest.update(_canonical_json(entry["logical"]).encode("utf-8"))
        logical_digest.update(b"]")
        logical_content_hash = logical_digest.hexdigest()
        data_revision = logical_content_hash

        metadata_names = (
            sorted(set().union(*(entry["lineage"].keys() for entry in entries))) if entries else []
        )
        constant_fields: dict[str, Any] = {}
        variable_fields: list[str] = []
        for field in metadata_names:
            values = [entry["lineage"].get(field) for entry in entries]
            encoded = {_canonical_json(value) for value in values}
            if len(encoded) == 1:
                constant_fields[field] = values[0]
            else:
                variable_fields.append(field)

        fact_rows = [entry["fact"] for entry in entries]
        fact_schema: dict[str, Any] = {
            "security_id": pl.Binary,
            "trade_date": pl.Date,
            **dict.fromkeys(DAILY_BAR_FACT_FIELDS, pl.Float64),
        }
        fact_frame = pl.DataFrame(fact_rows, schema=fact_schema, strict=True)
        fact_table = fact_frame.to_arrow().set_column(
            0,
            pa.field("security_id", pa.binary(16)),
            pa.array([entry["security_id"] for entry in entries], type=pa.binary(16)),
        )
        fact_buffer = io.BytesIO()
        pq.write_table(fact_table, fact_buffer, compression="zstd", write_statistics=True)
        fact_bytes = fact_buffer.getvalue()

        lineage_rows = [
            {
                "security_id": entry["security_id"],
                "trade_date": entry["fact"]["trade_date"],
                **{field: entry["lineage"].get(field) for field in variable_fields},
            }
            for entry in entries
        ]
        lineage_schema: dict[str, Any] = {"security_id": pl.Binary, "trade_date": pl.Date}
        for field in variable_fields:
            lineage_schema[field] = _lineage_polars_dtype(
                [entry["lineage"].get(field) for entry in entries]
            )
        lineage_frame = pl.DataFrame(lineage_rows, schema=lineage_schema, strict=True)
        lineage_table = lineage_frame.to_arrow().set_column(
            0,
            pa.field("security_id", pa.binary(16)),
            pa.array([entry["security_id"] for entry in entries], type=pa.binary(16)),
        )
        lineage_buffer = io.BytesIO()
        pq.write_table(lineage_table, lineage_buffer, compression="zstd", write_statistics=True)
        lineage_bytes = lineage_buffer.getvalue()

        fact_content_hash = _sha256(fact_bytes)
        lineage_content_hash = _sha256(lineage_bytes)
        artifact_set_hash = _sha256(
            _canonical_json(
                {
                    "fact_content_hash": fact_content_hash,
                    "fact_schema_hash": _sha256(str(fact_table.schema).encode("utf-8")),
                    "lineage_content_hash": lineage_content_hash,
                    "lineage_schema_hash": _sha256(str(lineage_table.schema).encode("utf-8")),
                    "row_count": len(entries),
                    "layout_revision": DAILY_BAR_LAYOUT_REVISION,
                }
            ).encode("utf-8")
        )
        base_uri = _partition_base_uri(
            partition_id, data_revision, DAILY_BAR_LAYOUT_REVISION, artifact_set_hash
        )
        fact_uri = f"{base_uri}/fact.parquet"
        lineage_uri = f"{base_uri}/lineage.parquet"

        manifest = {
            "contract_version": DAILY_BAR_PARTITION_CONTRACT,
            "logical_partition_id": f"security_bar_1d:{partition_id}",
            "partition": partition_id,
            "market_as_of": market_as_of.astimezone(UTC).isoformat(),
            "source_vintage_as_of": source_vintage_as_of.astimezone(UTC).isoformat(),
            "source_vintage_evidence": normalized_vintage_evidence,
            "event_eligibility": daily_bar_event_eligibility_binding(),
            "schema_version": DAILY_BAR_FACT_SCHEMA_VERSION,
            "logical_key": ["security_id", "trade_date"],
            "data_revision": data_revision,
            "logical_content_hash": logical_content_hash,
            "layout_revision": DAILY_BAR_LAYOUT_REVISION,
            "artifact_set_hash": artifact_set_hash,
            "row_count": len(entries),
            "min_trade_date": min(item["fact"]["trade_date"] for item in entries).isoformat(),
            "max_trade_date": max(item["fact"]["trade_date"] for item in entries).isoformat(),
            "fact_artifact": {
                "uri": fact_uri,
                "content_hash": fact_content_hash,
                "schema_hash": _sha256(str(fact_table.schema).encode("utf-8")),
                "row_count": len(entries),
            },
            "lineage_artifact": {
                "uri": lineage_uri,
                "content_hash": lineage_content_hash,
                "schema_hash": _sha256(str(lineage_table.schema).encode("utf-8")),
                "row_count": len(entries),
            },
            "constant_fields": constant_fields,
            "variable_fields": variable_fields,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=1, ensure_ascii=False).encode(
            "utf-8"
        )
        manifest_uri = f"{base_uri}/manifest_sha256={_sha256(manifest_bytes)}/manifest.json"
        fact_path = root / fact_uri
        lineage_path = root / lineage_uri
        manifest_path = root / manifest_uri

        current_partition = source_snapshot_as_of.astimezone(_MARKET_TIMEZONE).strftime("%Y-%m")
        if partition_id < current_partition:
            prior_manifests = root / "canonical" / "security_bar_1d" / f"partition={partition_id}"
            if prior_manifests.is_dir():
                for prior_path in prior_manifests.rglob("manifest.json"):
                    try:
                        prior = json.loads(prior_path.read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise DailyBarPartitionError(
                            f"closed-month manifest is unreadable: {prior_path}"
                        ) from exc
                    if (
                        prior.get("logical_partition_id") == f"security_bar_1d:{partition_id}"
                        and prior.get("data_revision") != data_revision
                    ):
                        raise DailyBarPartitionError(
                            f"closed daily-bar month {partition_id} changed logical facts"
                        )
        for path, payload in (
            (fact_path, fact_bytes),
            (lineage_path, lineage_bytes),
            (manifest_path, manifest_bytes),
        ):
            if path.exists() and (not path.is_file() or path.read_bytes() != payload):
                raise DailyBarPartitionError(f"immutable daily-bar artifact conflict: {path}")
        _immutable_write(fact_path, fact_bytes)
        _immutable_write(lineage_path, lineage_bytes)
        _immutable_write(manifest_path, manifest_bytes)
        results.append(
            {
                "logical_partition_id": manifest["logical_partition_id"],
                "partition": partition_id,
                "data_revision": data_revision,
                "logical_content_hash": logical_content_hash,
                "layout_revision": DAILY_BAR_LAYOUT_REVISION,
                "artifact_set_hash": artifact_set_hash,
                "partition_manifest_uri": manifest_uri,
                "partition_manifest_hash": _sha256(manifest_bytes),
                "fact_artifact": manifest["fact_artifact"],
                "lineage_artifact": manifest["lineage_artifact"],
                "row_count": len(entries),
                "min_trade_date": manifest["min_trade_date"],
                "max_trade_date": manifest["max_trade_date"],
                "market_as_of": manifest["market_as_of"],
                "source_vintage_as_of": manifest["source_vintage_as_of"],
                "source_vintage_evidence": manifest["source_vintage_evidence"],
                "event_eligibility": manifest["event_eligibility"],
            }
        )
    return tuple(results)


def iter_daily_bar_partition_rows(
    normalized_root: Path,
    partition_entry: Mapping[str, Any],
    *,
    batch_size: int = 32_768,
) -> Iterator[dict[str, Any]]:
    """Deep-audit one exact partition and reconstruct Canonical row semantics.

    This is deliberately a batch iterator for the explicit producer/deep-audit
    path. Ordinary snapshot and research opens consume the small seals only.
    """
    if batch_size <= 0:
        raise DailyBarPartitionError("batch_size must be positive")
    manifest_uri = validate_logical_uri(str(partition_entry["partition_manifest_uri"]))
    manifest_path = Path(normalized_root) / manifest_uri
    if not manifest_path.is_file():
        raise DailyBarPartitionError(f"daily-bar partition manifest missing: {manifest_uri}")
    manifest_bytes = manifest_path.read_bytes()
    if _sha256(manifest_bytes) != str(partition_entry["partition_manifest_hash"]):
        raise DailyBarPartitionError(
            "daily-bar partition manifest bytes do not match the Canonical seal"
        )
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("contract_version") != DAILY_BAR_PARTITION_CONTRACT
    ):
        raise DailyBarPartitionError("daily-bar partition contract is invalid")
    try:
        validate_daily_bar_event_eligibility_binding(manifest.get("event_eligibility"))
        source_vintage_evidence_value = manifest.get("source_vintage_evidence")
        if not isinstance(source_vintage_evidence_value, list):
            raise DailyBarPartitionError("daily-bar source-vintage evidence is not a list")
        source_vintage_evidence, source_vintage_as_of = normalize_source_vintage_evidence(
            source_vintage_evidence_value
        )
    except (DailyBarEventContractError, DailyBarPartitionError) as exc:
        raise DailyBarPartitionError(f"daily-bar temporal contract is invalid: {exc}") from exc
    if (
        manifest.get("source_vintage_evidence") != source_vintage_evidence
        or manifest.get("source_vintage_as_of") != source_vintage_as_of.isoformat()
        or partition_entry.get("source_vintage_evidence") != source_vintage_evidence
        or partition_entry.get("source_vintage_as_of") != source_vintage_as_of.isoformat()
        or partition_entry.get("event_eligibility") != daily_bar_event_eligibility_binding()
    ):
        raise DailyBarPartitionError("daily-bar temporal contract binding diverges")
    if manifest.get("data_revision") != partition_entry.get("data_revision"):
        raise DailyBarPartitionError("daily-bar partition data_revision binding diverges")
    if manifest.get("artifact_set_hash") != partition_entry.get("artifact_set_hash"):
        raise DailyBarPartitionError("daily-bar partition artifact_set_hash binding diverges")

    fact_entry = manifest.get("fact_artifact")
    lineage_entry = manifest.get("lineage_artifact")
    if not isinstance(fact_entry, dict) or not isinstance(lineage_entry, dict):
        raise DailyBarPartitionError("daily-bar partition artifact descriptors are missing")
    fact_uri = validate_logical_uri(str(fact_entry.get("uri")))
    lineage_uri = validate_logical_uri(str(lineage_entry.get("uri")))
    fact_path = Path(normalized_root) / fact_uri
    lineage_path = Path(normalized_root) / lineage_uri
    for path, entry in ((fact_path, fact_entry), (lineage_path, lineage_entry)):
        if not path.is_file() or _sha256_file(path) != str(entry.get("content_hash")):
            raise DailyBarPartitionError(f"daily-bar partition bytes are missing/tampered: {path}")

    fact_parquet = pq.ParquetFile(fact_path)
    lineage_parquet = pq.ParquetFile(lineage_path)
    if fact_parquet.schema_arrow.field("security_id").type != pa.binary(
        16
    ) or lineage_parquet.schema_arrow.field("security_id").type != pa.binary(16):
        raise DailyBarPartitionError("daily-bar identity columns are not fixed16 UUIDs")
    if _sha256(str(fact_parquet.schema_arrow).encode("utf-8")) != str(
        fact_entry.get("schema_hash")
    ) or _sha256(str(lineage_parquet.schema_arrow).encode("utf-8")) != str(
        lineage_entry.get("schema_hash")
    ):
        raise DailyBarPartitionError("daily-bar partition schema hash does not match its seal")
    expected_count = int(manifest.get("row_count", -1))
    if (
        fact_parquet.metadata is None
        or lineage_parquet.metadata is None
        or fact_parquet.metadata.num_rows != expected_count
        or lineage_parquet.metadata.num_rows != expected_count
    ):
        raise DailyBarPartitionError("daily-bar partition row-count seal mismatch")
    if expected_count != int(partition_entry.get("row_count", -1)):
        raise DailyBarPartitionError("Canonical daily-bar partition row count diverges")

    constant_fields = manifest.get("constant_fields")
    variable_fields = manifest.get("variable_fields")
    if not isinstance(constant_fields, dict) or not isinstance(variable_fields, list):
        raise DailyBarPartitionError("daily-bar partition lineage descriptor is invalid")
    fact_batches = fact_parquet.iter_batches(batch_size=batch_size)
    lineage_batches = lineage_parquet.iter_batches(batch_size=batch_size)
    fact_count = 0
    for fact_batch, lineage_batch in zip(fact_batches, lineage_batches, strict=True):
        fact_rows = fact_batch.to_pylist()
        lineage_rows = lineage_batch.to_pylist()
        if len(fact_rows) != len(lineage_rows):
            raise DailyBarPartitionError("daily-bar fact/lineage batch row counts diverge")
        for fact, lineage in zip(fact_rows, lineage_rows, strict=True):
            security_id = str(UUID(bytes=bytes(fact["security_id"])))
            trade_day = _trade_date(fact["trade_date"])
            if (
                lineage.get("security_id") != fact.get("security_id")
                or _trade_date(lineage.get("trade_date")) != trade_day
            ):
                raise DailyBarPartitionError("daily-bar lineage index key diverges from fact key")
            row = dict(constant_fields)
            row.update(
                {
                    str(name): value
                    for name, value in lineage.items()
                    if name not in _LINEAGE_KEY_COLUMNS
                }
            )
            row.update({field: fact.get(field) for field in DAILY_BAR_FACT_FIELDS})
            row.update(
                {
                    "canonical_domain": "daily_bar",
                    "security_id": security_id,
                    "trade_date": trade_day.isoformat(),
                    "canonical_key": _canonical_json([security_id, trade_day.isoformat()]),
                }
            )
            yield row
            fact_count += 1
    if fact_count != expected_count:
        raise DailyBarPartitionError("daily-bar partition stream row count mismatch")


def deep_verify_daily_bar_partitions(
    normalized_root: Path,
    partition_entries: Iterable[Mapping[str, Any]],
    *,
    batch_size: int = 32_768,
) -> tuple[dict[str, Any], ...]:
    """Return exact selected-row mappings for Canonical's explicit deep audit."""
    rows: list[dict[str, Any]] = []
    for entry in partition_entries:
        rows.extend(
            iter_daily_bar_partition_rows(
                normalized_root,
                entry,
                batch_size=batch_size,
            )
        )
    return tuple(rows)
