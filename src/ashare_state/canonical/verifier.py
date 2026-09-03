"""CR-4.1: the ONE public canonical consumption boundary (audit
20260902 sections 3-4, CR-4 work requirement P0-A01/P0-A02).

SnapshotBuilder (and any future governed consumer) must NEVER
re-implement canonical correctness rules: it calls
``verify_canonical_run_for_consumption`` - the ONLY supported entry
point for reading canonical truth for downstream construction - which
reuses the exact CR-3 verification implementations (typed identity
seal, shared artifact closure verifier, findings truth + status
semantic recompute, sealed CR-2 authority + physical verification).
There is no second, weaker copy of any rule.

Deliberate distinction from the CR-3 continuity guard: consumption
does NOT require the sealed CR-2 inputs to still be part of the
CURRENT snapshot discovery (a later legitimate superset input world
must not retroactively break consumption of an already-minted
SUCCESS run) - but every consumed input must still exist in the
authoritative CR-2 ledger with an identical identity and healthy
physical / anchored evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ashare_state.canonical.canonicalizer import (
    _LEDGER_COLUMNS,
    CanonicalRunner,
    CanonicalRunSeal,
    _ledger_as_of,
)

__all__ = [
    "CanonicalConsumptionError",
    "VerifiedCanonicalRun",
    "verify_canonical_run_for_consumption",
]


class CanonicalConsumptionError(Exception):
    """A canonical run cannot be consumed: unknown id, damaged seal /
    artifacts / findings truth, non-SUCCESS status, or degraded
    upstream CR-2 evidence. Fail closed - no partial truth escapes."""


@dataclass(frozen=True)
class VerifiedCanonicalRun:
    """The verified canonical truth a downstream builder may consume:
    the ledger record, the verified manifest, the exact requested
    domain set and the materialized selected rows (read from the
    hash-verified selected.parquet inside the verification)."""

    canonical_run_id: str
    as_of: datetime
    requested_domains: tuple[str, ...]
    status: str
    ledger_record: dict[str, Any]
    manifest: dict[str, Any]
    selected_rows: tuple[dict[str, Any], ...]


def verify_canonical_run_for_consumption(
    conn: Any,
    canonical_run_id: str,
    *,
    raw_root: Path,
    normalized_root: Path,
) -> VerifiedCanonicalRun:
    """Verify ONE historical canonical run end-to-end for downstream
    consumption (CR-4 work requirement P0-A01):

    1. the ledger row exists;
    2. the typed identity seal verifies (deterministic manifest URI +
       bytes hash + manifest == ledger correctness fields + the FULL
       derived run identity physical recompute incl. the run-id UUID5
       cross-bind);
    3. the shared canonical artifact closure verifier passes
       (selected / decisions / findings exact set + deterministic URIs
       + physical hashes + semantic seals);
    4. the findings truth (DB == parquet == seal) holds and the
       status is RECOMPUTED from that truth;
    5. the verified status is SUCCESS (a BLOCKED run is explicitly
       rejected - its findings are a failure record, not truth);
    6. every sealed CR-2 input still exists in the authoritative CR-2
       ledger with an identical identity and healthy physical /
       anchored evidence (sealed-input physical verification
       symmetric with the first consume).

    Any problem -> CanonicalConsumptionError (fail closed; nothing is
    returned partially). Success -> the selected rows are materialized
    from the hash-verified selected.parquet."""
    runner = CanonicalRunner(conn, raw_root=raw_root, normalized_root=normalized_root)
    row = conn.execute(
        f"SELECT {', '.join(_LEDGER_COLUMNS)} FROM meta_canonicalization_run "
        "WHERE canonical_run_id = ?",
        [canonical_run_id],
    ).fetchone()
    if row is None:
        msg = (
            f"canonical run {canonical_run_id} does not exist in the canonical "
            "ledger - nothing to consume"
        )
        raise CanonicalConsumptionError(msg)
    record = dict(zip(_LEDGER_COLUMNS, row, strict=True))
    seal = CanonicalRunSeal.from_ledger(record)

    # 2. typed identity seal (deterministic URI + bytes hash + manifest ==
    # ledger + full derived identity physical recompute incl. run-id bind)
    manifest, identity_problems = runner._verify_historical_identity_seal(seal, record)  # noqa: SLF001 - the ONE shared implementation
    if identity_problems or manifest is None:
        detail = "; ".join(identity_problems) if identity_problems else "no verifiable seal"
        msg = f"canonical run {canonical_run_id} is DAMAGED and cannot be consumed: {detail}"
        raise CanonicalConsumptionError(msg)

    # 3. shared canonical artifact closure verifier
    artifact_problems, artifact_rows = runner._verify_canonical_artifacts_with_rows(  # noqa: SLF001
        record, manifest
    )
    if artifact_problems:
        msg = (
            f"canonical run {canonical_run_id} artifacts are DAMAGED and "
            f"cannot be consumed: {'; '.join(artifact_problems)}"
        )
        raise CanonicalConsumptionError(msg)

    # 4. findings truth (DB == parquet == seal) + status recompute
    verified_status, finding_problems = runner._verify_findings_truth(record, manifest)  # noqa: SLF001 - the ONE shared implementation
    if finding_problems:
        msg = (
            f"canonical run {canonical_run_id} findings truth is DAMAGED and "
            f"cannot be consumed: {'; '.join(finding_problems)}"
        )
        raise CanonicalConsumptionError(msg)

    # 5. only a verified SUCCESS may be consumed
    if verified_status != "SUCCESS":
        msg = (
            f"canonical run {canonical_run_id} is {verified_status} - only a "
            "verified SUCCESS run may be consumed for snapshot construction"
        )
        raise CanonicalConsumptionError(msg)

    # 6. every sealed CR-2 input: authoritative ledger identity + physical /
    # anchored health (no current-discovery-presence requirement)
    as_of_dt = _ledger_as_of(record)
    for entry in manifest.get("input_normalized_runs", []):
        run_id = str(entry.get("run_id"))
        authority_problems = runner._sealed_input_authority_problems(entry, run_id)  # noqa: SLF001 - the ONE shared implementation
        if authority_problems:
            msg = (
                f"canonical run {canonical_run_id} cannot be consumed - "
                f"sealed CR-2 input is degraded: {'; '.join(authority_problems)}"
            )
            raise CanonicalConsumptionError(msg)
        physical_problems = runner._verify_sealed_input(entry, as_of_dt)  # noqa: SLF001 - the ONE shared implementation
        if physical_problems:
            msg = (
                f"canonical run {canonical_run_id} cannot be consumed - "
                f"sealed CR-2 input is no longer intact: "
                f"{'; '.join(physical_problems)}"
            )
            raise CanonicalConsumptionError(msg)

    # Reuse the rows materialized from the exact bytes inside the shared
    # artifact verifier; never reread a mutable path after verification.
    rows = artifact_rows["selected"]
    try:
        requested_domains = tuple(
            str(d) for d in json_loads_domains(str(record["requested_domains_json"]))
        )
    except ValueError as exc:
        msg = f"canonical run {canonical_run_id} carries unreadable requested domains: {exc}"
        raise CanonicalConsumptionError(msg) from exc
    return VerifiedCanonicalRun(
        canonical_run_id=canonical_run_id,
        as_of=as_of_dt,
        requested_domains=requested_domains,
        status=verified_status,
        ledger_record=record,
        manifest=manifest,
        selected_rows=tuple(rows),
    )


def json_loads_domains(raw: str) -> list[str]:
    import json

    try:
        domains = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(domains, list) or not all(isinstance(d, str) for d in domains):
        raise ValueError("requested_domains_json is not a list of strings")
    return domains
