"""CR-4.2: the versioned SNAPSHOT schema registry (audit 20260902
section 5, CR-4 work requirement P0-A09).

Every canonical supported domain has exactly ONE declared snapshot
table schema: the exact column set, the logical dtype of every
column, the nullability contract and the canonical-key arity. The
builder projects canonical selected rows through this registry with
STRICT typing (wrong type / missing non-nullable identity -> fail
closed); the verifier and the DuckDB ReadModel consume the same
registry, so there is no second, divergent schema anywhere.

Lineage (P0-A08): the snapshot row PRESERVES every canonical
selected-row lineage field verbatim and adds exactly two snapshot
projections (``canonical_run_id`` / ``snapshot_id``) - clearly
marked, never mistaken for canonical truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import polars as pl

__all__ = [
    "SNAPSHOT_CONTRACT_VERSION",
    "ColumnSpec",
    "DomainSnapshotSchema",
    "KeyBinding",
    "DType",
    "SnapshotSchemaError",
    "domain_snapshot_schema",
    "polars_domain_schema",
    "project_selected_row",
    "project_verified_canonical_snapshot",
    "snapshot_domains",
    "validate_canonical_key",
]


#: CR-4 snapshot contract identity.
SNAPSHOT_CONTRACT_VERSION = "snapshot-v1"


class SnapshotSchemaError(Exception):
    """A canonical selected row cannot be projected into the snapshot
    schema (wrong type, missing non-nullable identity, bad key, PIT
    violation). Fail closed - no partial snapshot truth."""


class DType(StrEnum):
    STRING = "string"
    INT64 = "int64"
    FLOAT64 = "float64"
    BOOLEAN = "boolean"
    DATE = "date"
    TIMESTAMP_UTC = "timestamp_utc"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    dtype: DType
    nullable: bool
    #: when set, the column is a KEY PROJECTION: its value is decoded
    #: from the canonical_key JSON array at this index (P0-A08 - a
    #: decoded key component, never mistaken for canonical payload)
    key_index: int | None = None


@dataclass(frozen=True)
class KeyBinding:
    """Binds a canonical key component to its typed snapshot column."""

    key_index: int
    column_name: str


def _lineage_columns(requires_security_identity: bool) -> tuple[ColumnSpec, ...]:
    """The lineage block every snapshot table carries verbatim from the
    canonical selected rows (P0-A08) + the two snapshot projections."""
    cols: list[ColumnSpec] = [
        ColumnSpec("canonical_domain", DType.STRING, nullable=False),
        ColumnSpec("canonical_key", DType.STRING, nullable=False),
    ]
    if requires_security_identity:
        cols.append(ColumnSpec("security_id", DType.STRING, nullable=False))
    cols.extend(
        [
            ColumnSpec("trade_date", DType.DATE, nullable=False),
            ColumnSpec("available_at", DType.TIMESTAMP_UTC, nullable=False),
            ColumnSpec("ingested_at", DType.TIMESTAMP_UTC, nullable=False),
            ColumnSpec("availability_basis", DType.STRING, nullable=False),
            ColumnSpec("availability_policy_version", DType.STRING, nullable=False),
            ColumnSpec("selected_provider", DType.STRING, nullable=False),
            ColumnSpec("source_normalization_run_id", DType.STRING, nullable=False),
            ColumnSpec("source_output_name", DType.STRING, nullable=False),
            ColumnSpec("source_row_ordinal", DType.INT64, nullable=False),
            ColumnSpec("source_row_identity_hash", DType.STRING, nullable=False),
            ColumnSpec("source_raw_request_id", DType.STRING, nullable=False),
            ColumnSpec("source_raw_evidence_hash", DType.STRING, nullable=False),
            ColumnSpec("source_mapper_identity", DType.STRING, nullable=False),
            ColumnSpec("source_policy_version", DType.STRING, nullable=False),
            ColumnSpec("canonical_contract_version", DType.STRING, nullable=False),
            # snapshot projections (NOT canonical truth; added by CR-4)
            ColumnSpec("canonical_run_id", DType.STRING, nullable=False),
            ColumnSpec("snapshot_id", DType.STRING, nullable=False),
        ]
    )
    return tuple(cols)


def _domain_schema(
    domain: str,
    payload: tuple[tuple[str, DType, bool], ...],
    *,
    requires_security_identity: bool,
    key_arity: int,
    key_projections: dict[str, int] | None = None,
    key_bindings: tuple[tuple[int, str], ...] = (),
    stable_sort_key: tuple[str, ...] = ("canonical_key",),
) -> DomainSnapshotSchema:
    cols = list(_lineage_columns(requires_security_identity))
    payload_start = 2 + (1 if requires_security_identity else 0)
    cols = (
        cols[:payload_start]
        + [ColumnSpec(name, dtype, nullable=nullable) for name, dtype, nullable in payload]
        + cols[payload_start:]
    )
    projections = key_projections or {}
    cols.extend(
        ColumnSpec(name, DType.STRING, nullable=False, key_index=index)
        for name, index in sorted(projections.items())
    )
    return DomainSnapshotSchema(
        domain=domain,
        columns=tuple(cols),
        key_arity=key_arity,
        key_bindings=tuple(KeyBinding(index, name) for index, name in key_bindings),
        stable_sort_key=stable_sort_key,
    )


@dataclass(frozen=True)
class DomainSnapshotSchema:
    domain: str
    columns: tuple[ColumnSpec, ...]
    #: expected canonical_key JSON-array arity for this domain
    key_arity: int
    #: explicit bindings from canonical key components to snapshot columns
    key_bindings: tuple[KeyBinding, ...] = ()
    #: deterministic physical row ordering for this domain
    stable_sort_key: tuple[str, ...] = ("canonical_key",)


_F = DType.FLOAT64
_S = DType.STRING
_I = DType.INT64

_DOMAIN_SCHEMAS: tuple[DomainSnapshotSchema, ...] = (
    _domain_schema(
        "trade_calendar",
        (("market", _S, False),),
        requires_security_identity=False,
        key_arity=2,
        key_bindings=((0, "market"), (1, "trade_date")),
    ),
    _domain_schema(
        "daily_bar",
        (
            ("open", _F, True),
            ("high", _F, True),
            ("low", _F, True),
            ("close", _F, True),
            ("pre_close", _F, True),
            ("volume", _F, True),
            ("amount", _F, True),
        ),
        requires_security_identity=True,
        key_arity=2,
        key_bindings=((0, "security_id"), (1, "trade_date")),
    ),
    _domain_schema(
        "security_status",
        (
            ("pre_close", _F, True),
            ("high_limited", _F, True),
            ("low_limited", _F, True),
            ("price_high_lmt_rate", _F, True),
            ("price_low_lmt_rate", _F, True),
            ("is_st_sec", _I, True),
            ("is_susp_sec", _I, True),
            ("is_wd_sec", _I, True),
            ("is_xr_sec", _I, True),
        ),
        requires_security_identity=True,
        key_arity=2,
        key_bindings=((0, "security_id"), (1, "trade_date")),
    ),
    _domain_schema(
        "limit_price",
        (
            ("pre_close", _F, True),
            ("up_limit", _F, True),
            ("down_limit", _F, True),
            ("up_limit_rate", _F, True),
            ("down_limit_rate", _F, True),
        ),
        requires_security_identity=True,
        key_arity=2,
        key_bindings=((0, "security_id"), (1, "trade_date")),
    ),
    _domain_schema(
        "adj_factor",
        (
            ("adj_factor", _F, True),
            ("backward_factor", _F, True),
        ),
        requires_security_identity=True,
        key_arity=3,
        key_projections={"factor_type": 2},
        key_bindings=((0, "security_id"), (1, "trade_date")),
    ),
)

_SCHEMA_BY_DOMAIN: dict[str, DomainSnapshotSchema] = {s.domain: s for s in _DOMAIN_SCHEMAS}


def snapshot_domains() -> tuple[str, ...]:
    return tuple(s.domain for s in _DOMAIN_SCHEMAS)


def polars_domain_schema(domain: str) -> pl.Schema:
    """The polars schema (exact column order + logical types) for ONE
    domain's snapshot parquet - the single mapping from the registry
    dtypes to the physical parquet types."""
    mapping: dict[DType, pl.DataType] = {
        DType.STRING: pl.String(),
        DType.INT64: pl.Int64(),
        DType.FLOAT64: pl.Float64(),
        DType.BOOLEAN: pl.Boolean(),
        DType.DATE: pl.Date(),
        DType.TIMESTAMP_UTC: pl.Datetime(time_unit="us", time_zone="UTC"),
    }
    schema = domain_snapshot_schema(domain)
    return pl.Schema([(col.name, mapping[col.dtype]) for col in schema.columns])


def domain_snapshot_schema(domain: str) -> DomainSnapshotSchema:
    schema = _SCHEMA_BY_DOMAIN.get(domain)
    if schema is None:
        raise SnapshotSchemaError(f"domain {domain!r} has no snapshot schema")
    return schema


def validate_canonical_key(domain: str, canonical_key: str) -> None:
    """P0-A07: the canonical_key MUST be the canonical JSON encoding of
    a typed natural-key tuple - decode, arity check, string check and
    re-encode round-trip. Any drift from the typed encoding is a fail
    closed correctness problem (the downstream schema relies on the
    key being well-formed)."""
    schema = domain_snapshot_schema(domain)
    try:
        parts = json.loads(canonical_key)
    except json.JSONDecodeError as exc:
        raise SnapshotSchemaError(
            f"domain {domain} canonical_key is not valid JSON: {canonical_key!r}"
        ) from exc
    if not isinstance(parts, list):
        raise SnapshotSchemaError(
            f"domain {domain} canonical_key is not a JSON array: {canonical_key!r}"
        )
    if len(parts) != schema.key_arity:
        raise SnapshotSchemaError(
            f"domain {domain} canonical_key arity {len(parts)} != expected "
            f"{schema.key_arity}: {canonical_key!r}"
        )
    if not all(isinstance(p, str) and p for p in parts):
        raise SnapshotSchemaError(
            f"domain {domain} canonical_key carries a non-string/empty component: {canonical_key!r}"
        )
    reencoded = json.dumps(parts, separators=(",", ":"), ensure_ascii=False)
    if reencoded != canonical_key:
        raise SnapshotSchemaError(
            f"domain {domain} canonical_key is not the canonical JSON encoding "
            f"(round-trip mismatch): {canonical_key!r} != {reencoded!r}"
        )


def _convert(value: Any, spec: ColumnSpec, domain: str) -> Any:
    if value is None:
        if not spec.nullable:
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} is non-nullable but the "
                "canonical row carries None"
            )
        return None
    if spec.dtype is DType.STRING:
        if not isinstance(value, str):
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} expects a string, got "
                f"{type(value).__name__}: {value!r}"
            )
        return value
    if spec.dtype is DType.FLOAT64:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} expects a number, got "
                f"{type(value).__name__}: {value!r}"
            )
        return float(value)
    if spec.dtype is DType.INT64:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} expects an integer, got "
                f"{type(value).__name__}: {value!r}"
            )
        return int(value)
    if spec.dtype is DType.BOOLEAN:
        if not isinstance(value, bool):
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} expects a boolean, got "
                f"{type(value).__name__}: {value!r}"
            )
        return value
    if spec.dtype is DType.DATE:
        if not isinstance(value, str):
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} expects an ISO date string, "
                f"got {type(value).__name__}: {value!r}"
            )
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} carries an unparseable date: {value!r}"
            ) from exc
    if spec.dtype is DType.TIMESTAMP_UTC:
        if not isinstance(value, str):
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} expects an ISO timestamp "
                f"string, got {type(value).__name__}: {value!r}"
            )
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} carries an unparseable timestamp: {value!r}"
            ) from exc
        if parsed.tzinfo is None:
            raise SnapshotSchemaError(
                f"domain {domain} column {spec.name} carries a naive timestamp "
                f"(timezone semantics required): {value!r}"
            )
        return parsed.astimezone(UTC)
    raise SnapshotSchemaError(f"unknown dtype {spec.dtype}")  # pragma: no cover


def project_selected_row(
    domain: str,
    selected_row: dict[str, Any],
    *,
    canonical_run_id: str,
    snapshot_id: str,
    as_of: datetime,
) -> dict[str, Any]:
    """Project ONE canonical selected row into the snapshot schema:
    validate the canonical key round-trip, assert the PIT contract
    (available_at <= as_of), then STRICT dtype projection through the
    registry (missing non-nullable identity / wrong type -> fail
    closed). Lineage fields are preserved verbatim; only
    ``canonical_run_id`` / ``snapshot_id`` are added as projections."""
    schema = domain_snapshot_schema(domain)
    if selected_row.get("canonical_domain") != domain:
        raise SnapshotSchemaError(
            f"domain {domain} selected row carries a foreign canonical_domain: "
            f"{selected_row.get('canonical_domain')!r}"
        )
    canonical_key = selected_row.get("canonical_key")
    if not isinstance(canonical_key, str) or not canonical_key:
        raise SnapshotSchemaError(
            f"domain {domain} selected row carries no canonical_key: {selected_row!r}"
        )
    validate_canonical_key(domain, canonical_key)
    key_parts = json.loads(canonical_key)
    projected: dict[str, Any] = {}
    for spec in schema.columns:
        if spec.name == "canonical_run_id":
            value: Any = canonical_run_id
        elif spec.name == "snapshot_id":
            value = snapshot_id
        elif spec.key_index is not None:
            # a KEY PROJECTION: decoded from the typed canonical key
            value = key_parts[spec.key_index]
        else:
            value = selected_row.get(spec.name)
        projected[spec.name] = _convert(value, spec, domain)
    # Explicit natural-key bindings are part of the schema contract:
    # canonical_key components must agree with the typed row identity.
    for binding in schema.key_bindings:
        value = projected[binding.column_name]
        if isinstance(value, datetime) or isinstance(value, date):
            typed_key_value = value.isoformat()
        else:
            typed_key_value = value
        if typed_key_value != key_parts[binding.key_index]:
            raise SnapshotSchemaError(
                f"domain {domain} canonical_key component {binding.key_index} "
                f"does not match {binding.column_name}: "
                f"{key_parts[binding.key_index]!r} != {typed_key_value!r}"
            )
    # PIT contract (P0-A08): every consumed row was available at as_of
    available_at = projected["available_at"]
    if available_at > as_of:
        raise SnapshotSchemaError(
            f"domain {domain} row {canonical_key} violates the PIT contract: "
            f"available_at {available_at.isoformat()} > as_of {as_of.isoformat()}"
        )
    return projected



def project_verified_canonical_snapshot(
    verified_canonical: Any, *, snapshot_id: str
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Replay one verified canonical run through the snapshot registry.

    This is the single deterministic projection used by both the builder
    and the snapshot verifier. It groups only the already verified selected
    rows, validates their domain/key/typed/PIT contracts, rejects duplicate
    natural keys, and returns rows in the registry's stable order.
    """
    try:
        requested_domains = tuple(
            str(domain) for domain in verified_canonical.requested_domains
        )
    except (AttributeError, TypeError) as exc:
        raise SnapshotSchemaError("verified canonical run has no requested domain set") from exc
    if not requested_domains or len(set(requested_domains)) != len(requested_domains):
        raise SnapshotSchemaError("verified canonical run carries an empty or duplicate domain set")
    for domain in requested_domains:
        domain_snapshot_schema(domain)

    canonical_run_id = getattr(verified_canonical, "canonical_run_id", None)
    if not isinstance(canonical_run_id, str) or not canonical_run_id:
        raise SnapshotSchemaError("verified canonical run carries no canonical_run_id")
    as_of = getattr(verified_canonical, "as_of", None)
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise SnapshotSchemaError("verified canonical run carries no timezone-aware as_of")
    as_of = as_of.astimezone(UTC)

    grouped: dict[str, list[dict[str, Any]]] = {domain: [] for domain in requested_domains}
    for row in verified_canonical.selected_rows:
        if not isinstance(row, dict):
            raise SnapshotSchemaError(
                f"verified canonical selected row is not a mapping: {row!r}"
            )
        domain = row.get("canonical_domain")
        if domain not in grouped:
            raise SnapshotSchemaError(
                f"canonical run emitted domain {domain!r} outside the requested domain set"
            )
        grouped[domain].append(row)

    projected_by_domain: dict[str, tuple[dict[str, Any], ...]] = {}
    for domain in requested_domains:
        projected = [
            project_selected_row(
                domain,
                row,
                canonical_run_id=canonical_run_id,
                snapshot_id=snapshot_id,
                as_of=as_of,
            )
            for row in grouped[domain]
        ]
        keys = [row["canonical_key"] for row in projected]
        if len(set(keys)) != len(keys):
            raise SnapshotSchemaError(f"domain {domain} carries duplicate canonical keys")
        schema = domain_snapshot_schema(domain)
        projected.sort(key=lambda row: tuple(row[name] for name in schema.stable_sort_key))
        projected_by_domain[domain] = tuple(projected)
    return projected_by_domain
