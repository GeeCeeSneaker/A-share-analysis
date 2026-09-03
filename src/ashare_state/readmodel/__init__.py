"""CR-4.3: the DuckDB ReadModel layer.

``DuckDBReadModel.rebuild`` derives the query model from a VERIFIED
snapshot (the snapshot verifier is the ONLY input); the rebuild is
atomic (temp build -> logical seal -> replace) and its logical truth
is validated against the snapshot seals. No providers, no Raw, no
feature computation.
"""

from ashare_state.readmodel.duckdb_model import (
    DuckDBReadModel,
    ReadModelBuildResult,
    ReadModelError,
    readmodel_builder_code_fingerprint,
    readmodel_db_uri,
)
from ashare_state.readmodel.schema import (
    READMODEL_CONTRACT_VERSION,
    duckdb_domain_columns,
    duckdb_domain_table_name,
    duckdb_type_of,
)

__all__ = [
    "DuckDBReadModel",
    "READMODEL_CONTRACT_VERSION",
    "ReadModelBuildResult",
    "ReadModelError",
    "duckdb_domain_columns",
    "duckdb_domain_table_name",
    "duckdb_type_of",
    "readmodel_builder_code_fingerprint",
    "readmodel_db_uri",
]
