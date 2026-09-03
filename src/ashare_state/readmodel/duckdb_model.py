"""CR-4.3: the DuckDB ReadModel rebuild (audit 20260902 section 6).

``DuckDBReadModel.rebuild(snapshot_id)``:

- the ONLY input is the verified snapshot (``verify_snapshot`` - no
  direct parquet/file trust);
- builds into a TEMPORARY database file, applies the declared
  ``rm_<domain>`` tables + ``rm_snapshot_meta`` + ``rm_domain_meta``;
- validates the LOGICAL semantic exactness IN the temp database
  (per-domain row counts / semantic hashes recomputed from the table
  contents / canonical-key uniqueness / schema exactness / explicit
  timezone semantics);
- atomically replaces the deterministic target
  (``readmodel/contract=readmodel-v1/snapshot=<id>/readmodel.duckdb``);
- any failure leaves the previous target untouched and the temp file
  removed (no partial / corrupt / half-built model is ever visible).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from ashare_state.canonical.canonicalizer import _canonical_json, _rows_semantic_hash
from ashare_state.readmodel.schema import (
    _DTYPE_TO_DUCKDB,
    READMODEL_CONTRACT_VERSION,
    duckdb_domain_columns,
    duckdb_domain_table_name,
)
from ashare_state.snapshot.models import SnapshotVerifierError
from ashare_state.snapshot.schema import domain_snapshot_schema
from ashare_state.snapshot.verifier import verify_snapshot

__all__ = [
    "DuckDBReadModel",
    "ReadModelBuildResult",
    "ReadModelError",
    "readmodel_builder_code_fingerprint",
    "readmodel_db_uri",
]


def readmodel_builder_code_fingerprint() -> str:
    """Hash the exact source set that governs ReadModel construction."""
    import ashare_state.readmodel.duckdb_model as _model
    import ashare_state.readmodel.schema as _schema
    import ashare_state.snapshot.schema as _snapshot_schema

    digest = hashlib.sha256()
    for module in (_snapshot_schema, _schema, _model):
        module_file = getattr(module, "__file__", None)
        if module_file is None:  # pragma: no cover
            raise ReadModelError(f"module {module!r} has no source file")
        source = Path(module_file).read_bytes().decode("utf-8")
        normalized = source.replace("\r\n", "\n").replace("\r", "\n")
        digest.update(module.__name__.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(normalized.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def _normalize_seal_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize ONE fetched DuckDB row for the semantic seal: the
    session timezone may render TIMESTAMP WITH TIME ZONE values as a
    non-UTC offset - the semantic truth is the UTC instant (the same
    instant the snapshot parquet carries)."""
    return {
        k: (v.astimezone(UTC) if isinstance(v, datetime) and v.tzinfo is not None else v)
        for k, v in row.items()
    }


class ReadModelError(Exception):
    """The readmodel cannot be rebuilt or is inconsistent with the
    verified snapshot. Fail closed."""


@dataclass(frozen=True)
class ReadModelBuildResult:
    snapshot_id: str
    canonical_run_id: str
    db_uri: str
    table_set: tuple[str, ...]
    row_count_total: int
    readmodel_contract_version: str


def readmodel_db_uri(snapshot_id: str) -> str:
    """The deterministic (root-relative) DuckDB path for ONE snapshot's
    readmodel."""
    return (
        f"readmodel/contract={READMODEL_CONTRACT_VERSION}/snapshot={snapshot_id}/readmodel.duckdb"
    )


class DuckDBReadModel:
    """Rebuilds (and opens) the DuckDB read model from a verified
    snapshot. Deterministic per snapshot id; the rebuild is atomic
    (temp build -> logical seal -> os.replace)."""

    def __init__(
        self,
        conn: Any,
        *,
        raw_root: Path,
        normalized_root: Path,
        readmodel_root: Path | None = None,
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)
        self.readmodel_root = Path(readmodel_root) if readmodel_root else self.normalized_root

    # ------------------------------------------------------------ rebuild
    def rebuild(self, snapshot_id: str) -> ReadModelBuildResult:
        verified = verify_snapshot(
            self.conn,
            snapshot_id,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        db_uri = readmodel_db_uri(snapshot_id)
        target = self.readmodel_root / db_uri
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / ".readmodel.building.duckdb"
        if tmp.exists():
            tmp.unlink()

        try:
            db = duckdb.connect(str(tmp))
            try:
                self._create_tables(db, verified)
                self._insert_meta(db, verified)
                self._validate_logical_seal(db, verified)
            finally:
                db.close()
            # atomic replace: the previous target (same snapshot id,
            # logically identical truth) is replaced only after the
            # temp build fully validated
            tmp.replace(target)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise

        table_set = self._expected_table_set(verified.requested_domains)
        return ReadModelBuildResult(
            snapshot_id=snapshot_id,
            canonical_run_id=verified.canonical_run_id,
            db_uri=db_uri,
            table_set=table_set,
            row_count_total=sum(len(rows) for rows in verified.domain_rows.values()),
            readmodel_contract_version=READMODEL_CONTRACT_VERSION,
        )

    # ------------------------------------------------------------- tables
    @staticmethod
    def _expected_table_set(requested_domains: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            sorted(
                [duckdb_domain_table_name(d) for d in requested_domains]
                + ["rm_domain_meta", "rm_snapshot_meta"]
            )
        )

    def _create_tables(self, db: duckdb.DuckDBPyConnection, verified: Any) -> None:
        db.execute(
            """
            CREATE TABLE rm_snapshot_meta (
                snapshot_id VARCHAR PRIMARY KEY,
                snapshot_contract_version VARCHAR NOT NULL,
                canonical_run_id VARCHAR NOT NULL,
                canonical_as_of TIMESTAMP WITH TIME ZONE NOT NULL,
                requested_domains VARCHAR NOT NULL,
                readmodel_contract_version VARCHAR NOT NULL,
                snapshot_builder_code_fingerprint VARCHAR NOT NULL,
                readmodel_builder_code_fingerprint VARCHAR NOT NULL
            )
            """
        )
        db.execute(
            """
            CREATE TABLE rm_domain_meta (
                snapshot_id VARCHAR NOT NULL,
                domain VARCHAR NOT NULL,
                artifact_uri VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                semantic_hash VARCHAR NOT NULL,
                PRIMARY KEY (snapshot_id, domain)
            )
            """
        )
        for domain in verified.requested_domains:
            schema = domain_snapshot_schema(domain)
            column_sql = ", ".join(
                f"{col.name} {_DTYPE_TO_DUCKDB[col.dtype]}{' NOT NULL' if not col.nullable else ''}"
                for col in schema.columns
            )
            table = duckdb_domain_table_name(domain)
            db.execute(f"CREATE TABLE {table} ({column_sql}, PRIMARY KEY (canonical_key))")
            parquet_path = (
                (self.normalized_root / str(verified.manifest["artifacts"][domain]["uri"]))
                .resolve()
                .as_posix()
            )
            # hive_partitioning=false: the artifact path carries
            # contract=/as_of=/snapshot= segments that DuckDB would
            # otherwise misread as partition columns
            db.execute(
                f"INSERT INTO {table} SELECT * FROM "
                f"read_parquet('{parquet_path}', hive_partitioning=false)"
            )

    def _insert_meta(self, db: duckdb.DuckDBPyConnection, verified: Any) -> None:
        db.execute(
            "INSERT INTO rm_snapshot_meta VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                verified.snapshot_id,
                str(verified.manifest["snapshot_contract_version"]),
                verified.canonical_run_id,
                verified.as_of,
                _canonical_json(list(verified.requested_domains)),
                READMODEL_CONTRACT_VERSION,
                str(verified.manifest["snapshot_builder_code_fingerprint"]),
                readmodel_builder_code_fingerprint(),
            ],
        )
        for domain in verified.requested_domains:
            entry = verified.manifest["artifacts"][domain]
            db.execute(
                "INSERT INTO rm_domain_meta VALUES (?, ?, ?, ?, ?)",
                [
                    verified.snapshot_id,
                    domain,
                    str(entry["uri"]),
                    int(entry["row_count"]),
                    str(entry["semantic_hash"]),
                ],
            )

    # ------------------------------------------------------ logical seal
    def _validate_logical_seal(self, db: duckdb.DuckDBPyConnection, verified: Any) -> None:
        """P0-B06/P0-B07/P0-B08: the LOGICAL truth of the built model
        must equal the verified snapshot truth exactly - row counts,
        per-domain semantic hashes recomputed FROM THE TABLE CONTENTS,
        canonical-key uniqueness, schema exactness (declared DuckDB
        types, explicit timezone semantics) and the meta tables."""
        problems: list[str] = []
        tables = {
            r[0]
            for r in db.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        expected_tables = set(self._expected_table_set(verified.requested_domains))
        if tables != expected_tables:
            problems.append(f"table set {sorted(tables)} != expected {sorted(expected_tables)}")
        for domain in verified.requested_domains:
            table = duckdb_domain_table_name(domain)
            entry = verified.manifest["artifacts"][domain]
            # schema exactness (declared DuckDB types, explicit tz)
            declared = duckdb_domain_columns(domain)
            actual = {
                r[0]: r[1]
                for r in db.execute(
                    f"SELECT column_name, data_type FROM information_schema.columns "
                    f"WHERE table_schema = 'main' AND table_name = '{table}' "
                    "ORDER BY ordinal_position"
                ).fetchall()
            }
            if list(actual) != list(declared):
                problems.append(f"{table} column set/order diverges from the registry")
            elif actual != declared:
                problems.append(
                    f"{table} column types diverge from the declared readmodel "
                    f"schema: { {k: actual[k] for k in actual if actual[k] != declared[k]} }"
                )
            # row count
            count_row = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            count = int(count_row[0]) if count_row is not None else -1
            if count != int(entry["row_count"]):
                problems.append(f"{table} row count {count} != snapshot seal {entry['row_count']}")
            # key uniqueness
            distinct_row = db.execute(
                f"SELECT COUNT(DISTINCT canonical_key) FROM {table}"
            ).fetchone()
            distinct = int(distinct_row[0]) if distinct_row is not None else -1
            if distinct != count:
                problems.append(f"{table} canonical_key uniqueness violated")
            # semantic exactness from the table contents (datetime
            # values normalized back to UTC - the DuckDB session
            # timezone otherwise shifts the string serialization)
            rows = db.execute(f"SELECT * FROM {table}").fetchall()
            col_names = list(duckdb_domain_columns(domain))
            dicts = [_normalize_seal_row(dict(zip(col_names, r, strict=True))) for r in rows]
            semantic = _rows_semantic_hash(dicts)
            if semantic != str(entry["semantic_hash"]):
                problems.append(f"{table} logical semantic hash diverges from the snapshot seal")
        # meta tables: every provenance field is part of the logical seal.
        meta = db.execute(
            "SELECT snapshot_id, snapshot_contract_version, canonical_run_id, "
            "canonical_as_of, requested_domains, readmodel_contract_version, "
            "snapshot_builder_code_fingerprint, readmodel_builder_code_fingerprint "
            "FROM rm_snapshot_meta"
        ).fetchall()
        if len(meta) != 1:
            problems.append("rm_snapshot_meta must carry exactly one row")
        else:
            row = meta[0]
            if str(row[0]) != verified.snapshot_id:
                problems.append("rm_snapshot_meta snapshot_id mismatch")
            if str(row[1]) != str(verified.manifest["snapshot_contract_version"]):
                problems.append("rm_snapshot_meta snapshot_contract_version mismatch")
            if str(row[2]) != verified.canonical_run_id:
                problems.append("rm_snapshot_meta canonical_run_id mismatch")
            db_as_of = row[3]
            if (
                not isinstance(db_as_of, datetime)
                or db_as_of.tzinfo is None
                or db_as_of.astimezone(UTC) != verified.as_of.astimezone(UTC)
            ):
                problems.append("rm_snapshot_meta canonical_as_of mismatch")
            if str(row[4]) != _canonical_json(list(verified.requested_domains)):
                problems.append("rm_snapshot_meta requested_domains mismatch")
            if str(row[5]) != READMODEL_CONTRACT_VERSION:
                problems.append("rm_snapshot_meta readmodel_contract_version mismatch")
            if str(row[6]) != str(verified.manifest["snapshot_builder_code_fingerprint"]):
                problems.append("rm_snapshot_meta snapshot_builder_code_fingerprint mismatch")
            if str(row[7]) != readmodel_builder_code_fingerprint():
                problems.append("rm_snapshot_meta readmodel_builder_code_fingerprint mismatch")

        domain_meta_rows = db.execute(
            "SELECT snapshot_id, domain, artifact_uri, row_count, semantic_hash FROM rm_domain_meta"
        ).fetchall()
        expected_domains = set(verified.requested_domains)
        seen_domains: dict[str, tuple[Any, int, Any]] = {}
        for row in domain_meta_rows:
            row_snapshot_id = str(row[0])
            domain = str(row[1])
            if row_snapshot_id != verified.snapshot_id:
                problems.append(f"rm_domain_meta {domain} carries a foreign snapshot_id")
            if domain not in expected_domains:
                problems.append(f"rm_domain_meta carries an unexpected domain {domain}")
                continue
            if domain in seen_domains:
                problems.append(f"rm_domain_meta carries duplicate domain {domain}")
                continue
            seen_domains[domain] = (row[2], int(row[3]), row[4])
        if set(seen_domains) != expected_domains:
            problems.append("rm_domain_meta domain set mismatch")
        for domain in expected_domains:
            if domain not in seen_domains:
                continue
            entry = verified.manifest["artifacts"][domain]
            uri, count, semantic = seen_domains[domain]
            if uri != str(entry["uri"]) or count != int(entry["row_count"]):
                problems.append(f"rm_domain_meta {domain} row mismatch")
            if str(semantic) != str(entry["semantic_hash"]):
                problems.append(f"rm_domain_meta {domain} semantic hash mismatch")
        if problems:
            msg = (
                f"readmodel rebuild for snapshot {verified.snapshot_id} failed the "
                f"logical seal: {'; '.join(problems)}"
            )
            raise ReadModelError(msg)

    # --------------------------------------------------------------- open
    def _open_verified_read_only(self, snapshot_id: str) -> tuple[duckdb.DuckDBPyConnection, Any]:
        target = self.readmodel_root / readmodel_db_uri(snapshot_id)
        if not target.is_file():
            msg = f"readmodel for snapshot {snapshot_id} has not been built: {target}"
            raise ReadModelError(msg)
        try:
            verified = verify_snapshot(
                self.conn,
                snapshot_id,
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
        except SnapshotVerifierError as exc:
            # A readmodel handle must never expose an unverified snapshot.
            raise ReadModelError(
                f"readmodel for snapshot {snapshot_id} cannot verify its snapshot provenance: {exc}"
            ) from exc
        db: duckdb.DuckDBPyConnection | None = None
        try:
            db = duckdb.connect(str(target), read_only=True)
            self._validate_logical_seal(db, verified)
        except ReadModelError:
            if db is not None:
                db.close()
            raise
        except Exception as exc:
            if db is not None:
                db.close()
            raise ReadModelError(
                f"readmodel for snapshot {snapshot_id} failed verified-open: {exc}"
            ) from exc
        assert db is not None
        return db, verified

    def verify_readmodel(self, snapshot_id: str) -> Any:
        """Verify the snapshot and logical ReadModel seal, then close it."""
        db, verified = self._open_verified_read_only(snapshot_id)
        db.close()
        return verified

    def open_read_only(self, snapshot_id: str) -> duckdb.DuckDBPyConnection:
        """Open only a ReadModel whose snapshot and logical seal verify."""
        db, _ = self._open_verified_read_only(snapshot_id)
        return db
