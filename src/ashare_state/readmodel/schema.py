"""CR-4.3: the DuckDB ReadModel schema mapping (audit 20260902
section 6, P0-B06/P0-B07).

Every snapshot registry dtype maps to exactly ONE DuckDB column type;
the rebuild creates each ``rm_<domain>`` table with EXACTLY this
declared type set (never an implicit cast) and the post-build logical
seal re-checks the physical table schema against this same mapping.
Timezone semantics are explicit: TIMESTAMP_UTC columns are DuckDB
``TIMESTAMP WITH TIME ZONE`` (UTC instant round-trip).
"""

from __future__ import annotations

from ashare_state.snapshot.schema import DType, domain_snapshot_schema

__all__ = [
    "READMODEL_CONTRACT_VERSION",
    "duckdb_domain_columns",
    "duckdb_domain_table_name",
    "duckdb_type_of",
]


#: CR-4 readmodel contract identity.
READMODEL_CONTRACT_VERSION = "readmodel-v1"

_DTYPE_TO_DUCKDB: dict[DType, str] = {
    DType.STRING: "VARCHAR",
    DType.INT64: "BIGINT",
    DType.FLOAT64: "DOUBLE",
    DType.BOOLEAN: "BOOLEAN",
    DType.DATE: "DATE",
    DType.TIMESTAMP_UTC: "TIMESTAMP WITH TIME ZONE",
}


def duckdb_type_of(dtype: DType) -> str:
    return _DTYPE_TO_DUCKDB[dtype]


def duckdb_domain_table_name(domain: str) -> str:
    return f"rm_{domain}"


def duckdb_domain_columns(domain: str) -> dict[str, str]:
    """The ordered {column name -> DuckDB type} map for ONE domain's
    ``rm_<domain>`` table - the single source for CREATE TABLE and for
    the post-build schema-exactness seal."""
    schema = domain_snapshot_schema(domain)
    return {col.name: _DTYPE_TO_DUCKDB[col.dtype] for col in schema.columns}
