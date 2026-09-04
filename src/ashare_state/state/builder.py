"""CR-6.2 StateBuilder: verified Feature -> immutable descriptive State."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ashare_state.features.models import canonical_json, semantic_hash
from ashare_state.features.verifier import verify_feature_run_for_consumption
from ashare_state.state.engine import ComputedStateSet, compute_state_set
from ashare_state.state.models import (
    STATE_CONTRACT_VERSION,
    StateBuilderError,
    StateBuildResult,
    state_base_hash_from_primitives,
    state_id_from_base_hash,
)
from ashare_state.state.registry import (
    StateRegistryError,
    compile_state_execution_plan,
    get_state_set,
)
from ashare_state.state.schema import (
    STATE_ARTIFACT_NAMES,
    frame_for_artifact,
)
from ashare_state.storage.atomic_files import write_file_atomic

__all__ = [
    "STATE_LEDGER_COLUMNS",
    "StateBuilder",
    "state_base_dir",
    "state_builder_code_fingerprint",
    "state_manifest_uri",
]


STATE_LEDGER_COLUMNS = (
    "state_run_id",
    "feature_run_id",
    "feature_manifest_uri",
    "feature_manifest_hash",
    "feature_semantic_hash",
    "feature_set_id",
    "feature_registry_hash",
    "state_set_id",
    "state_set_version",
    "state_registry_version",
    "state_registry_hash",
    "state_contract_version",
    "state_builder_code_fingerprint",
    "manifest_uri",
    "manifest_hash",
    "artifact_set_hash",
    "state_semantic_hash",
    "finding_set_hash",
    "state_row_count",
    "finding_count",
    "status",
    "error_message",
    "started_at",
    "completed_at",
)


def state_builder_code_fingerprint() -> str:
    """Hash every source module that governs State correctness."""
    import ashare_state.state.builder as _builder
    import ashare_state.state.engine as _engine
    import ashare_state.state.models as _models
    import ashare_state.state.registry as _registry
    import ashare_state.state.schema as _schema
    import ashare_state.state.verifier as _verifier

    digest = hashlib.sha256()
    for module in (
        _models,
        _registry,
        _schema,
        _engine,
        _builder,
        _verifier,
    ):
        module_file = getattr(module, "__file__", None)
        if module_file is None:  # pragma: no cover
            raise StateBuilderError(f"state module {module!r} has no source file")
        source = Path(module_file).read_bytes().decode("utf-8")
        digest.update(module.__name__.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(source.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def state_base_dir(feature_run_id: str, state_run_id: str) -> str:
    prefix = f"state/contract={STATE_CONTRACT_VERSION}"
    return f"{prefix}/feature_run={feature_run_id}/run={state_run_id}"


def state_manifest_uri(feature_run_id: str, state_run_id: str) -> str:
    return f"{state_base_dir(feature_run_id, state_run_id)}/manifest.json"


def _required_text(values: Mapping[str, Any], field: str) -> str:
    value = values.get(field)
    if not isinstance(value, str) or not value:
        raise StateBuilderError(f"{field} is missing from the verified Feature provenance")
    return value


def _artifact_set_hash(seals: Mapping[str, Mapping[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(seals).encode("utf-8")).hexdigest()


def _assert_immutable_compatible(path: Path, data: bytes) -> None:
    if not path.exists():
        return
    if not path.is_file() or path.read_bytes() != data:
        raise StateBuilderError(
            f"immutable State artifact conflict: {path} exists with different bytes"
        )


def _write_immutable(path: Path, data: bytes) -> None:
    try:
        write_file_atomic(path, data, allow_existing_identical=True)
    except Exception as exc:
        raise StateBuilderError(
            f"State immutable publication failed at {path}: {exc}"
        ) from exc


def _result_from_record(
    record: Mapping[str, Any],
    *,
    idempotent_replay: bool,
) -> StateBuildResult:
    return StateBuildResult(
        state_run_id=_required_text(record, "state_run_id"),
        feature_run_id=_required_text(record, "feature_run_id"),
        state_set_id=_required_text(record, "state_set_id"),
        manifest_uri=_required_text(record, "manifest_uri"),
        manifest_hash=_required_text(record, "manifest_hash"),
        artifact_set_hash=_required_text(record, "artifact_set_hash"),
        state_semantic_hash=_required_text(record, "state_semantic_hash"),
        finding_set_hash=_required_text(record, "finding_set_hash"),
        state_row_count=int(record["state_row_count"]),
        finding_count=int(record["finding_count"]),
        status=_required_text(record, "status"),
        idempotent_replay=idempotent_replay,
    )


class StateBuilder:
    """Build one explicit State run from one verified Feature run."""

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

    def build(self, feature_run_id: str, state_set_id: str) -> StateBuildResult:
        """Build one explicit Feature/State-set pair."""
        started = datetime.now(UTC)
        if not isinstance(feature_run_id, str) or not feature_run_id:
            raise StateBuilderError("feature_run_id must be an explicit non-empty string")
        if not isinstance(state_set_id, str) or not state_set_id:
            raise StateBuilderError("state_set_id must be an explicit non-empty string")
        try:
            state_set = get_state_set(state_set_id)
            compile_state_execution_plan(state_set)
        except StateRegistryError as exc:
            raise StateBuilderError(
                f"State Registry cannot be honestly executed: {exc}"
            ) from exc

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
            raise StateBuilderError(
                f"verified Feature run {feature_run_id} is not consumable"
            ) from exc
        if feature_run.feature_run_id != feature_run_id:
            raise StateBuilderError("public Feature verifier returned a foreign feature_run_id")

        feature_record = feature_run.ledger_record
        if _required_text(feature_record, "feature_run_id") != feature_run_id:
            raise StateBuilderError("Feature ledger provenance does not match the explicit input")
        feature_manifest_uri_value = _required_text(feature_record, "manifest_uri")
        feature_manifest_hash = _required_text(feature_record, "manifest_hash")
        feature_semantic = _required_text(feature_record, "feature_semantic_hash")
        feature_registry_hash = _required_text(feature_record, "feature_registry_hash")
        feature_set_id = feature_run.feature_set_id
        if not feature_set_id:
            raise StateBuilderError("verified Feature run has no feature_set_id")
        state_fingerprint = state_builder_code_fingerprint()
        base_hash = state_base_hash_from_primitives(
            feature_run_id=feature_run_id,
            feature_manifest_hash=feature_manifest_hash,
            feature_semantic_hash=feature_semantic,
            feature_set_id=feature_set_id,
            feature_registry_hash=feature_registry_hash,
            state_set_id=state_set.state_set_id,
            state_set_version=state_set.state_set_version,
            state_registry_version=state_set.state_registry_version,
            state_registry_hash=state_set.registry_hash,
            state_contract_version=state_set.contract_version,
            state_builder_code_fingerprint=state_fingerprint,
        )
        state_run_id = state_id_from_base_hash(base_hash)

        existing = self.conn.execute(
            "SELECT 1 FROM meta_state_build WHERE state_run_id = ?",
            [state_run_id],
        ).fetchone()
        if existing is not None:
            from ashare_state.state.verifier import verify_state_run_for_consumption

            try:
                current = verify_state_run_for_consumption(
                    self.conn,
                    state_run_id,
                    raw_root=self.raw_root,
                    normalized_root=self.normalized_root,
                    readmodel_root=self.readmodel_root,
                    feature_root=self.feature_root,
                    state_root=self.state_root,
                )
            except Exception as exc:
                raise StateBuilderError(
                    f"existing State run {state_run_id} is not consumable"
                ) from exc
            return _result_from_record(current.ledger_record, idempotent_replay=True)

        computed: ComputedStateSet = compute_state_set(
            feature_run,
            state_run_id=state_run_id,
            state_set=state_set,
        )
        artifact_rows = {
            "market_daily_state": computed.state_rows,
            "state_findings": computed.finding_rows,
        }
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_payloads: dict[str, bytes] = {}
        base_dir = state_base_dir(feature_run_id, state_run_id)
        for name in STATE_ARTIFACT_NAMES:
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

        artifact_set_hash = _artifact_set_hash(artifacts)
        manifest_uri = state_manifest_uri(feature_run_id, state_run_id)
        manifest = {
            "state_run_id": state_run_id,
            "state_contract_version": state_set.contract_version,
            "state_base_hash": base_hash,
            "state_builder_code_fingerprint": state_fingerprint,
            "state_set_id": state_set.state_set_id,
            "state_set_version": state_set.state_set_version,
            "state_registry_version": state_set.state_registry_version,
            "state_registry_hash": state_set.registry_hash,
            "feature_run_id": feature_run_id,
            "feature_manifest_uri": feature_manifest_uri_value,
            "feature_manifest_hash": feature_manifest_hash,
            "feature_semantic_hash": feature_semantic,
            "feature_set_id": feature_set_id,
            "feature_registry_hash": feature_registry_hash,
            "artifacts": artifacts,
            "artifact_set_hash": artifact_set_hash,
            "state_semantic_hash": computed.state_semantic_hash,
            "finding_set_hash": computed.finding_set_hash,
            "state_row_count": len(computed.state_rows),
            "finding_count": len(computed.finding_rows),
            "status": "SUCCESS",
            "error_message": None,
        }
        manifest_bytes = json.dumps(
            manifest,
            sort_keys=True,
            indent=1,
            ensure_ascii=False,
        ).encode("utf-8")

        write_plan = [
            (self.state_root / artifacts[name]["uri"], artifact_payloads[name])
            for name in STATE_ARTIFACT_NAMES
        ]
        write_plan.append((self.state_root / manifest_uri, manifest_bytes))
        for path, data in write_plan:
            _assert_immutable_compatible(path, data)
        for path, data in write_plan[:-1]:
            _write_immutable(path, data)
        _write_immutable(write_plan[-1][0], write_plan[-1][1])

        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        completed = datetime.now(UTC)
        ledger_values: dict[str, Any] = {
            "state_run_id": state_run_id,
            "feature_run_id": feature_run_id,
            "feature_manifest_uri": feature_manifest_uri_value,
            "feature_manifest_hash": feature_manifest_hash,
            "feature_semantic_hash": feature_semantic,
            "feature_set_id": feature_set_id,
            "feature_registry_hash": feature_registry_hash,
            "state_set_id": state_set.state_set_id,
            "state_set_version": state_set.state_set_version,
            "state_registry_version": state_set.state_registry_version,
            "state_registry_hash": state_set.registry_hash,
            "state_contract_version": state_set.contract_version,
            "state_builder_code_fingerprint": state_fingerprint,
            "manifest_uri": manifest_uri,
            "manifest_hash": manifest_hash,
            "artifact_set_hash": artifact_set_hash,
            "state_semantic_hash": computed.state_semantic_hash,
            "finding_set_hash": computed.finding_set_hash,
            "state_row_count": len(computed.state_rows),
            "finding_count": len(computed.finding_rows),
            "status": "SUCCESS",
            "error_message": None,
            "started_at": started,
            "completed_at": completed,
        }
        self._commit_ledger(ledger_values)
        return StateBuildResult(
            state_run_id=state_run_id,
            feature_run_id=feature_run_id,
            state_set_id=state_set.state_set_id,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            artifact_set_hash=artifact_set_hash,
            state_semantic_hash=computed.state_semantic_hash,
            finding_set_hash=computed.finding_set_hash,
            state_row_count=len(computed.state_rows),
            finding_count=len(computed.finding_rows),
            status="SUCCESS",
            idempotent_replay=False,
        )

    def _commit_ledger(self, values: Mapping[str, Any]) -> None:
        self.conn.execute("BEGIN TRANSACTION")
        try:
            duplicate = self.conn.execute(
                "SELECT 1 FROM meta_state_build WHERE state_run_id = ?",
                [values["state_run_id"]],
            ).fetchone()
            if duplicate is not None:
                raise StateBuilderError(
                    f"State run {values['state_run_id']} already exists in the ledger"
                )
            row = [values[column] for column in STATE_LEDGER_COLUMNS]
            self.conn.execute(
                f"INSERT INTO meta_state_build ({', '.join(STATE_LEDGER_COLUMNS)}) "
                f"VALUES ({', '.join(['?'] * len(STATE_LEDGER_COLUMNS))})",
                row,
            )
            self.conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                self.conn.execute("ROLLBACK")
            raise
