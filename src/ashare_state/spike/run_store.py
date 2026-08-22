"""SpikeRun store: physical isolation per run kind (audit R2 sections 5/6).

Layout (audit R2 section 6 / 24.4):

    data/spike/dry-run/<spike_run_id>/
        spike_run.json
        cases/spike_case_catalog.jsonl (+ .csv)
        raw/<request_id>.json | .parquet

Dry-run, trial and production evidence NEVER share a directory, so fake
evidence can never leak into a production verdict.

Raw evidence rules:
- file name = <request_id> (UUID) -> no same-second overwrite risk
- writing an existing request_id is a hard error (immutable evidence)
- payload is archived losslessly (json lines of dicts/lists; DataFrames
  serialized to records) - repr() truncation is forbidden
- content_hash is computed and recorded in the evidence metadata
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_state.spike.model import RunKind, SpikeRun


class EvidenceImmutableError(RuntimeError):
    """Attempted to overwrite existing raw evidence (forbidden)."""


class RunStoreError(RuntimeError):
    """Run-store misuse (e.g. verdict on a dry-run run)."""


@dataclass
class RunStore:
    """Filesystem layout for one spike run."""

    spike_root: Path

    def run_dir(self, run: SpikeRun) -> Path:
        return self.spike_root / run.run_kind.value.lower() / run.spike_run_id

    def cases_dir(self, run: SpikeRun) -> Path:
        return self.run_dir(run) / "cases"

    def raw_dir(self, run: SpikeRun) -> Path:
        return self.run_dir(run) / "raw"

    # ------------------------------------------------------------ lifecycle
    def initialize(self, run: SpikeRun) -> Path:
        run_dir = self.run_dir(run)
        if run_dir.exists():
            msg = f"run dir already exists: {run_dir}"
            raise RunStoreError(msg)
        self.cases_dir(run).mkdir(parents=True, exist_ok=True)
        self.raw_dir(run).mkdir(parents=True, exist_ok=True)
        self.save_run(run)
        return run_dir

    def save_run(self, run: SpikeRun) -> None:
        path = self.run_dir(run) / "spike_run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(run.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")

    def load_run(self, spike_run_id: str, run_kind: RunKind) -> SpikeRun:
        path = self.spike_root / run_kind.value.lower() / spike_run_id / "spike_run.json"
        if not path.is_file():
            msg = f"spike run not found: {path}"
            raise RunStoreError(msg)
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SpikeRun(
            spike_run_id=payload["spike_run_id"],
            run_kind=RunKind(payload["run_kind"]),
            provider=payload.get("provider", "amazingdata"),
            account_profile_id=payload.get("account_profile_id", "UNKNOWN"),
            sdk_version=payload.get("sdk_version"),
            runtime_version=payload.get("runtime_version"),
            code_commit=payload.get("code_commit", "unknown"),
            environment_lock_hash=payload.get("environment_lock_hash", ""),
            config_hash=payload.get("config_hash", ""),
            as_of_date=payload.get("as_of_date", ""),
            golden_truth_version=payload.get("golden_truth_version", ""),
            golden_dataset_hash=payload.get(
                "golden_dataset_hash", payload.get("golden_manifest_hash", "")
            ),
            case_catalog_hash=payload.get("case_catalog_hash", ""),
            started_at=payload.get("started_at", ""),
            ended_at=payload.get("ended_at"),
            status=payload.get("status", "RUNNING"),
            failure_reason=payload.get("failure_reason"),
        )

    def assert_verdict_eligible(self, run: SpikeRun) -> None:
        """Verdicts only ever aggregate a closed PRODUCTION run (R2-P0-04)."""
        if run.run_kind is not RunKind.PRODUCTION:
            msg = (
                f"verdict is only allowed for PRODUCTION runs; {run.spike_run_id} is {run.run_kind}"
            )
            raise RunStoreError(msg)
        if run.status != "CLOSED":
            msg = f"run {run.spike_run_id} is {run.status}; close it before the verdict"
            raise RunStoreError(msg)

    # -------------------------------------------------------------- evidence
    def write_evidence(
        self,
        run: SpikeRun,
        request_id: str,
        *,
        endpoint: str,
        provider_dataset: str,
        params: dict[str, Any],
        payload: Any,
        account_profile_id: str = "",
        sdk_version: str | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, Any]:
        """Lossless, immutable raw evidence for one SDK exchange."""
        path = self.raw_dir(run) / f"{request_id}.json"
        if path.exists():
            raise EvidenceImmutableError(
                f"raw evidence {request_id} already exists; evidence is immutable"
            )
        lossless = _to_lossless(payload)
        document = {
            "request_id": request_id,
            "endpoint": endpoint,
            "provider_dataset": provider_dataset,
            "request_params": _scrub(params),
            "account_profile_id": account_profile_id,
            "sdk_version": sdk_version,
            "runtime_version": runtime_version,
            "payload": lossless,
        }
        text = json.dumps(document, ensure_ascii=False, default=str, indent=1)
        # newline="": NO platform newline translation - the recorded
        # content_hash must match the file BYTES exactly (evidence closure
        # re-verifies them; the default \n -> \r\n translation on Windows
        # broke hash equality - found by the R3-P0-16 closure check).
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        import hashlib

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        metadata = {
            "request_id": request_id,
            "provider_dataset": provider_dataset,
            "endpoint": endpoint,
            "account_profile_id": account_profile_id,
            "sdk_version": sdk_version,
            "runtime_version": runtime_version,
            "content_hash": content_hash,
            "row_count": _count_rows(lossless),
            "evidence_ref": path.relative_to(self.spike_root).as_posix(),
        }
        meta_path = self.raw_dir(run) / f"{request_id}.meta.json"
        meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        return metadata


def _scrub(params: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in params.items():
        if any(s in str(k).lower() for s in ("password", "token", "secret", "credential")):
            out[k] = "***MASKED***"
        else:
            out[k] = v
    return out


def _to_lossless(payload: Any) -> Any:
    """Lossless conversion for JSON archiving.

    DataFrame -> records list; other non-JSON shapes are converted via a
    STRICT converter that fails loudly rather than repr()-truncating
    (audit R2 section 6: repr() truncation makes 'verbatim archived'
    false).
    """
    if payload is None or isinstance(payload, (bool, int, float, str)):
        return payload
    if isinstance(payload, dict):
        return {str(k): _to_lossless(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_to_lossless(v) for v in payload]
    # pandas DataFrame / Series
    to_dict = getattr(payload, "to_dict", None)
    records = getattr(payload, "to_records", None)
    if callable(records):
        try:
            rows = payload.reset_index().to_dict(orient="records")
            return {"__frame__": [_to_lossless(r) for r in rows]}
        except Exception:  # noqa: BLE001 - fall through to strict failure
            pass
    if callable(to_dict):
        return _to_lossless(to_dict())
    raise TypeError(
        f"evidence payload of type {type(payload).__name__} cannot be archived "
        "losslessly; convert it explicitly (repr() truncation is forbidden)"
    )


def _count_rows(lossless: Any) -> int:
    if isinstance(lossless, dict):
        if "__frame__" in lossless:
            return len(lossless["__frame__"])
        return sum(_count_rows(v) for v in lossless.values())
    if isinstance(lossless, list):
        return len(lossless)
    return 1
