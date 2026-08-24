"""Spike runner: lifecycle, provenance, verdict engine (R3 sections 5-20/37).

R3 corrections applied here:
- R3-P0-01: close_run/fail_run/abort_run - formal runs ALWAYS reach a
  terminal state (persisted via save_run).
- R3-P0-02: resume_run validates same identity triple (account profile /
  code commit / env+config hashes / sdk+runtime) and RUNNING status.
- R3-P0-14: new_production_run verifies the account profile is complete,
  entitlement-verified and NOT a trial simulation.
- R3-P0-15: provenance is REQUIRED - full 40-char git SHA (clean tree),
  uv.lock hash, config hash; incomplete provenance forces
  SPIKE_INCOMPLETE at verdict time.
- R3-P0-04/05/16: the verdict engine iterates SpikeCase objects directly
  (never compressed stats): equivalent_pass is honored, any blocking
  VALIDATED_FAIL dominates, min_valid_cases is enforced, and evidence
  closure (hash re-verification + catalog validation) runs before any
  GO/NO_GO.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ashare_state.spike.capabilities import (
    CORE_CAPABILITIES,
    OPTIONAL_CAPABILITIES,
    SpikeCapabilityDefinition,
)
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import (
    TERMINAL_RUN_STATUSES,
    CaseResult,
    RunFailureReason,
    RunKind,
    RunStatus,
    SpikeRun,
    core_gate_satisfied,
)
from ashare_state.spike.run_store import RunStore, RunStoreError
from ashare_state.spike.target import make_dry_run_target

if TYPE_CHECKING:
    from ashare_state.providers.amazingdata.session import AccountProfile


class VerdictError(RuntimeError):
    """Verdict misuse (e.g. non-production run, open run)."""


class RunLifecycleError(RuntimeError):
    """Illegal run lifecycle transition (R3-P0-01)."""


class ProductionAccountGateError(RunLifecycleError):
    """The logged-in account may not open a PRODUCTION run (R3-P0-14)."""


# ------------------------------------------------------------------ lifecycle


def _replace(run: SpikeRun, **changes: Any) -> SpikeRun:
    from dataclasses import replace

    return replace(run, **changes)


def close_run(store: RunStore, run: SpikeRun) -> SpikeRun:
    """RUNNING -> CLOSED (all requested phases executed). Terminal.

    R4-P0-12: sealing the case catalog - the closed catalog is an
    IMMUTABLE artifact. case_catalog_hash is computed from the catalog
    bytes and stored on the run; the verdict re-computes and exact-matches
    it, so post-close edits (FAIL->PASS, expected_value, validator_id,
    equivalent_pass) block the verdict.
    """
    if run.status != RunStatus.RUNNING.value:
        msg = f"run {run.spike_run_id} is {run.status}; only RUNNING runs close"
        raise RunLifecycleError(msg)
    catalog_path = store.run_dir(run) / "cases" / "spike_case_catalog.jsonl"
    if not catalog_path.is_file():
        # an empty run still seals an (empty) catalog: closed-run immutability
        # holds uniformly; verdicts over empty runs are SPIKE_INCOMPLETE
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_bytes(b"")
    catalog_hash = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    closed = _replace(
        run,
        status=RunStatus.CLOSED.value,
        ended_at=_now(),
        case_catalog_hash=catalog_hash,
    )
    store.save_run(closed)
    return closed


def fail_run(store: RunStore, run: SpikeRun, reason: RunFailureReason) -> SpikeRun:
    """RUNNING -> FAILED(reason). Terminal - e.g. ProviderAuthError."""
    if run.status != RunStatus.RUNNING.value:
        msg = f"run {run.spike_run_id} is {run.status}; only RUNNING runs fail"
        raise RunLifecycleError(msg)
    failed = _replace(
        run, status=RunStatus.FAILED.value, ended_at=_now(), failure_reason=str(reason)
    )
    store.save_run(failed)
    return failed


def abort_run(store: RunStore, run: SpikeRun) -> SpikeRun:
    """RUNNING -> ABORTED (operator interrupt). Terminal."""
    if run.status != RunStatus.RUNNING.value:
        msg = f"run {run.spike_run_id} is {run.status}; only RUNNING runs abort"
        raise RunLifecycleError(msg)
    aborted = _replace(run, status=RunStatus.ABORTED.value, ended_at=_now())
    store.save_run(aborted)
    return aborted


def resume_run(
    store: RunStore,
    run: SpikeRun,
    *,
    account_profile_id: str,
    code_commit: str,
    environment_lock_hash: str,
    config_hash: str,
    sdk_version: str | None,
    runtime_version: str | None,
) -> SpikeRun:
    """R3-P0-02: continue an EXISTING running run - the identity triple must
    match exactly, otherwise continuation is refused."""
    if run.status != RunStatus.RUNNING.value:
        msg = (
            f"run {run.spike_run_id} is {run.status}; only RUNNING runs can resume "
            "(terminal runs are immutable)"
        )
        raise RunLifecycleError(msg)
    mismatches = []
    if run.account_profile_id != account_profile_id:
        mismatches.append("account_profile_id")
    if run.code_commit != code_commit:
        mismatches.append("code_commit")
    if run.environment_lock_hash != environment_lock_hash:
        mismatches.append("environment_lock_hash")
    if run.config_hash != config_hash:
        mismatches.append("config_hash")
    if (run.sdk_version or "") != (sdk_version or ""):
        mismatches.append("sdk_version")
    if (run.runtime_version or "") != (runtime_version or ""):
        mismatches.append("runtime_version")
    if mismatches:
        msg = (
            f"resume refused for run {run.spike_run_id}: identity mismatch in "
            f"{mismatches} - open a NEW run instead"
        )
        raise RunLifecycleError(msg)
    # R4A2-P0-02: resume resolves the RUN-BOUND dataset (never ACTIVE)
    if run.golden_truth_version:
        from ashare_state.spike.golden_store import GoldenTruthStore

        GoldenTruthStore().load_bound(
            dataset_file=run.golden_dataset_file,
            truth_version=run.golden_truth_version,
            dataset_hash=run.golden_dataset_hash,
        )
    return run


# ----------------------------------------------------------------- provenance


def current_code_commit(repo_root: Path | None = None, *, require_clean: bool = False) -> str:
    """FULL 40-char commit SHA for run provenance (R3-P0-15).

    require_clean: refuse (raise) when the working tree is dirty - formal
    production runs must be reproducible from the recorded commit.
    """
    root = repo_root or Path.cwd()
    try:
        if require_clean:
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            if dirty.stdout.strip():
                msg = (
                    "working tree is dirty; formal production runs require a "
                    "clean tree (commit or stash first)"
                )
                raise RunLifecycleError(msg)
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        sha = out.stdout.strip()
        if len(sha) != 40:
            msg = f"expected full 40-char SHA, got {sha!r}"
            raise RunLifecycleError(msg)
        return sha
    except RunLifecycleError:
        raise
    except Exception as exc:  # noqa: BLE001 - provenance failure is fatal for formal runs
        raise RunLifecycleError(f"code commit provenance unavailable: {exc}") from exc


def compute_environment_lock_hash(repo_root: Path | None = None) -> str:
    """SHA-256 of uv.lock (environment reproducibility identity)."""
    root = repo_root or Path.cwd()
    lock = root / "uv.lock"
    if not lock.is_file():
        msg = "uv.lock not found; environment provenance unavailable"
        raise RunLifecycleError(msg)
    return hashlib.sha256(lock.read_bytes()).hexdigest()


def compute_config_hash(repo_root: Path | None = None) -> str:
    """Deterministic hash over configs/*.yaml (sorted by name)."""
    root = repo_root or Path.cwd()
    config_dir = root / "configs"
    if not config_dir.is_dir():
        msg = "configs/ not found; config provenance unavailable"
        raise RunLifecycleError(msg)
    digest = hashlib.sha256()
    for path in sorted(config_dir.glob("*.yaml")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


# ------------------------------------------------------------------- new runs


def verify_production_account(profile: AccountProfile) -> None:
    """R3-P0-14: PRODUCTION runs need a complete, non-trial account."""
    problems: list[str] = []
    if not profile.auth_ok:
        problems.append("auth_ok is False")
    if not profile.profile_parsed:
        problems.append("logon profile not parsed (entitlements unknown)")
    if not profile.entitlement_verified:
        problems.append("entitlement not verified (PermissionCode missing)")
    if profile.account_profile_id == "UNKNOWN":
        problems.append("account_profile_id is UNKNOWN")
    if profile.account_profile_id.startswith("TRIAL_SIMULATION"):
        problems.append(
            "TRIAL_SIMULATION account may not open PRODUCTION runs (use --trial for trial evidence)"
        )
    if problems:
        msg = "production account gate refused: " + "; ".join(problems)
        raise ProductionAccountGateError(msg)


def new_run(
    *,
    run_kind: RunKind,
    spike_root: Path,
    code_commit: str = "unknown",
    environment_lock_hash: str = "",
    config_hash: str = "",
    sdk_version: str | None = None,
    runtime_version: str | None = None,
    account_profile_id: str = "UNKNOWN",
    as_of_date: str = "",
    account_profile: AccountProfile | None = None,
) -> tuple[SpikeRun, RunStore]:
    import uuid as uuid_module

    if run_kind is RunKind.PRODUCTION:
        if account_profile is None:
            msg = "PRODUCTION runs require the logged-in account profile"
            raise ProductionAccountGateError(msg)
        verify_production_account(account_profile)
        # R3-P0-15: formal runs REQUIRE complete provenance at creation
        if len(code_commit) != 40:
            msg = "PRODUCTION runs require a full 40-char code commit"
            raise RunLifecycleError(msg)
        if not environment_lock_hash or not config_hash:
            msg = "PRODUCTION runs require environment_lock_hash and config_hash"
            raise RunLifecycleError(msg)
    # R4-P0-01/02 + R4A2-P0-02/04: formal runs BIND the golden dataset at
    # creation; PRODUCTION additionally requires the FULL review gate
    # (fail fast - never burn production-account flow on unreviewed truth)
    golden_truth_version = ""
    golden_dataset_file = ""
    golden_dataset_hash = ""
    if run_kind in (RunKind.PRODUCTION, RunKind.TRIAL):
        from ashare_state.spike.golden_store import GoldenTruthStore

        golden_store = GoldenTruthStore()
        golden_cases, golden_manifest = golden_store.load()
        if run_kind is RunKind.PRODUCTION:
            missing = golden_store.quantity_gate()
            missing_events = golden_store.event_coverage_gate()
            review_problems = golden_store.review_gate()
            blocking = missing + missing_events + review_problems
            if blocking:
                msg = (
                    "PRODUCTION run refused: golden dataset not formal-truth "
                    f"ready: {blocking} (audit R4A2-P0-04: quantity + events "
                    "+ review gates all pass BEFORE a production run starts)"
                )
                raise RunLifecycleError(msg)
        golden_truth_version = golden_manifest.truth_version
        golden_dataset_file = golden_manifest.dataset_file
        golden_dataset_hash = golden_manifest.dataset_hash
        _ = golden_cases
    run = SpikeRun(
        spike_run_id=str(uuid_module.uuid4()),
        run_kind=run_kind,
        code_commit=code_commit,
        environment_lock_hash=environment_lock_hash,
        config_hash=config_hash,
        sdk_version=sdk_version,
        runtime_version=runtime_version,
        account_profile_id=account_profile_id,
        as_of_date=as_of_date,
        golden_truth_version=golden_truth_version,
        golden_dataset_file=golden_dataset_file,
        golden_dataset_hash=golden_dataset_hash,
    )
    store = RunStore(spike_root)
    store.initialize(run)
    return run, store


# ------------------------------------------------------------------ dry run


def run_dry_run(
    spike_root: Path,
    *,
    sample_date: int = 20260814,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Framework self-test: full pipeline over FakeTarget, isolated under
    data/spike/dry-run/<run-id>/ (can never enter a production verdict)."""
    target = make_dry_run_target()
    run, store = new_run(run_kind=RunKind.DRY_RUN, spike_root=spike_root)
    catalog = CaseCatalog(store, run.spike_run_id)
    ctx = _probe_context(run, store, catalog, target)
    outputs: dict[str, Any] = {"spike_run_id": run.spike_run_id, "phases": {}}
    from ashare_state.spike.probes import (
        probe_b2_security_master,
        probe_b3_core_facts,
        probe_b4_golden,
        probe_b5_units_pit_freshness,
        probe_b6_replacement,
        probe_b7_capacity,
    )

    outputs["phases"]["b2"] = probe_b2_security_master(ctx)
    outputs["phases"]["b3"] = probe_b3_core_facts(ctx, sample_date)
    outputs["phases"]["b4"] = probe_b4_golden(ctx, sample_date)
    outputs["phases"]["b5"] = probe_b5_units_pit_freshness(ctx, sample_date)
    outputs["phases"]["b6"] = probe_b6_replacement(ctx, sample_date)
    outputs["phases"]["b7"] = probe_b7_capacity(ctx, sample_date)
    run_dir = store.run_dir(run)
    catalog.flush(run_dir)
    closed = close_run(store, run)
    outputs["run_dir"] = str(run_dir)
    outputs["status"] = closed.status
    return outputs


def _probe_context(run, store, catalog, target):
    from ashare_state.spike.probes import ProbeContext

    return ProbeContext(run, store, catalog, target)


# ------------------------------------------------------------- verdict engine


@dataclass(frozen=True)
class SpikeVerdict:
    verdict: str  # GO_CORE | GO_DEGRADED | NO_GO | SPIKE_INCOMPLETE
    run_id: str
    run_kind: str
    capability_status: dict[str, str]
    missing_core: list[str]
    failed_core: list[str]
    missing_optional: list[str]
    case_stats: dict[str, dict[str, int]]
    blocking_reasons: list[str] = field(default_factory=list)
    p0a_eligible: bool = False
    p0b_eligible: bool = False
    historical_backfill_eligible: str = "NO"  # NO | PARTIAL | YES

    def to_json(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "spike_run_id": self.run_id,
            "run_kind": self.run_kind,
            "capability_status": self.capability_status,
            "missing_core": self.missing_core,
            "failed_core": self.failed_core,
            "missing_optional": self.missing_optional,
            "case_stats": self.case_stats,
            "blocking_reasons": self.blocking_reasons,
            "milestone_eligibility": {
                "p0a_eligible": self.p0a_eligible,
                "p0b_eligible": self.p0b_eligible,
                "historical_backfill_eligible": self.historical_backfill_eligible,
            },
        }


def compute_verdict(store: RunStore, run: SpikeRun) -> SpikeVerdict:
    """Run-scoped verdict aggregation (R3-P0-04/05/16).

    Iterates SpikeCase objects DIRECTLY (never compressed stats):
    - any blocking VALIDATED_FAIL -> capability FAILED (fail dominates pass)
    - DIFF_EXPLAINED counts only when equivalent_pass=True
    - min_valid_cases enforced per capability
    - evidence closure verified first: catalog re-validation, case run-id
      match, evidence file existence + hash match
    - incomplete provenance -> SPIKE_INCOMPLETE regardless of cases
    """
    store.assert_verdict_eligible(run)
    blocking: list[str] = []
    if not run.provenance_complete():
        blocking.append("R3-P0-15: run provenance incomplete (code/env/config/sdk/runtime/account)")

    catalog = CaseCatalog(store, run.spike_run_id)
    catalog.load(store.run_dir(run))
    cases = catalog.cases
    closure = verify_evidence_closure(store, run, catalog)
    blocking.extend(closure)

    # R4-P0-12: catalog seal - recompute the closed catalog's hash and
    # exact-match it; post-close edits block the verdict
    catalog_path = store.run_dir(run) / "cases" / "spike_case_catalog.jsonl"
    if not run.case_catalog_hash:
        blocking.append("R4-P0-12: run has no case_catalog_hash (not sealed at close)")
    elif catalog_path.is_file():
        import hashlib as _hashlib

        actual = _hashlib.sha256(catalog_path.read_bytes()).hexdigest()
        if actual != run.case_catalog_hash:
            blocking.append(
                "R4-P0-12: case catalog hash mismatch - the closed catalog "
                "was edited (closed catalogs are immutable artifacts)"
            )
    # R4A2-P0-02: verdict resolves the RUN-BOUND immutable dataset (never
    # the ACTIVE pointer); historical verdicts replay against the exact
    # dataset the run was created with, even after ACTIVE advances.
    if run.golden_truth_version:
        from ashare_state.spike.golden_store import GoldenTruthStore

        try:
            golden_store = GoldenTruthStore()
            _, bound_manifest = golden_store.load_bound(
                dataset_file=run.golden_dataset_file,
                truth_version=run.golden_truth_version,
                dataset_hash=run.golden_dataset_hash,
            )
            # R4-P0-01 + audit section 39: production verdicts need reviewed
            # truth - evaluated over the BOUND dataset, not ACTIVE.
            # R4-A2.3 P0-05: ALL formal gates (quantity + events + review)
            # are bound-aware - pass the bound cases themselves so an
            # ACTIVE advance/tamper can never leak into the verdict.
            if run.run_kind == RunKind.PRODUCTION:
                bound_cases, bound_manifest = golden_store.load_bound(
                    dataset_file=run.golden_dataset_file,
                    truth_version=run.golden_truth_version,
                    dataset_hash=run.golden_dataset_hash,
                )
                blocking.extend(
                    golden_store.production_formal_gate(bound_cases, bound_manifest)
                )
        except Exception as exc:  # noqa: BLE001 - integrity error blocks the verdict
            blocking.append(f"golden truth binding violated: {exc}")

    capability_status: dict[str, str] = {}
    missing_core: list[str] = []
    failed_core: list[str] = []
    missing_optional: list[str] = []

    for cap in CORE_CAPABILITIES:
        status = _capability_status_from_cases(cap, cases)
        capability_status[cap.capability_id] = status
        if status == "FAILED":
            failed_core.append(cap.capability_id)
        elif status != "PASS":
            missing_core.append(cap.capability_id)

    for cap in OPTIONAL_CAPABILITIES:
        status = _capability_status_from_cases(cap, cases)
        capability_status[cap.capability_id] = status
        if status != "PASS":
            missing_optional.append(cap.capability_id)

    if blocking or missing_core:
        verdict = "SPIKE_INCOMPLETE"
    elif failed_core:
        verdict = "NO_GO"
    elif missing_optional:
        verdict = "GO_DEGRADED"
    else:
        verdict = "GO_CORE"

    # R3 section 54: milestone eligibility separated from provider verdict
    core_all_pass = not missing_core and not failed_core and not blocking
    optional_ok = {c.capability_id for c in OPTIONAL_CAPABILITIES} - set(missing_optional)
    p0a_eligible = core_all_pass
    p0b_eligible = core_all_pass and "free_float_equivalence" in optional_ok
    backfill = "NO"
    if core_all_pass:
        backfill = "YES" if "capacity_backfill" in optional_ok else "PARTIAL"

    return SpikeVerdict(
        verdict=verdict,
        run_id=run.spike_run_id,
        run_kind=str(run.run_kind),
        capability_status=capability_status,
        missing_core=missing_core,
        failed_core=failed_core,
        missing_optional=missing_optional,
        case_stats=catalog.stats(),
        blocking_reasons=blocking,
        p0a_eligible=p0a_eligible,
        p0b_eligible=p0b_eligible,
        historical_backfill_eligible=backfill,
    )


def _capability_status_from_cases(cap: SpikeCapabilityDefinition, cases: list[Any]) -> str:
    """Per-capability verdict from RAW cases (R3-P0-04/05 + R4-P0-04).

    - any VALIDATED_FAIL -> FAILED (fail dominates pass)
    - DIFF_EXPLAINED counts toward valid cases ONLY with equivalent_pass
    - EVERY required case type must reach its OWN minimum count
      (required_case_counts); total volume can never substitute
    - required case type absent -> MISSING
    """
    required_types = set(cap.required_case_types)
    relevant = [c for c in cases if c.case_type in required_types]
    if not relevant:
        return "MISSING"
    if any(c.result is CaseResult.VALIDATED_FAIL for c in relevant):
        return "FAILED"
    valid_by_type: dict[str, int] = {}
    for case_type in cap.required_case_types:
        valid_by_type[case_type] = sum(
            1
            for c in relevant
            if c.case_type == case_type
            and core_gate_satisfied(c.result, equivalent_pass=c.equivalent_pass)
        )
    for case_type, minimum in cap.required_case_counts.items():
        if valid_by_type.get(case_type, 0) < minimum:
            return "SPIKE_INCOMPLETE"
    return "PASS"


def verify_evidence_closure(store: RunStore, run: SpikeRun, catalog: CaseCatalog) -> list[str]:
    """R3-P0-16: re-verify all evidence before any verdict.

    Checks: case validation, run-id binding, duplicate ids, evidence file
    existence, evidence hash match.

    R4-A2.3 (audit section 6.3): evidence BUNDLES (golden domain routing)
    are additionally opened and every exchange they list is re-verified
    (file exists + hash matches) - the multi-endpoint lineage closes.
    """
    import hashlib

    problems: list[str] = []
    seen_ids: set[str] = set()
    verified_bundles: dict[str, list[str]] = {}
    for case in catalog.cases:
        try:
            case.validate()
        except ValueError as exc:
            problems.append(f"case validation failed: {exc}")
            continue
        if case.spike_run_id != run.spike_run_id:
            problems.append(f"case {case.case_id} binds another run")
        if case.case_id in seen_ids:
            problems.append(f"duplicate case id {case.case_id}")
        seen_ids.add(case.case_id)
        if not case.evidence_hash:
            problems.append(f"case {case.case_id} has no evidence hash")
            continue
        evidence_path = store.spike_root / case.evidence_ref
        if not evidence_path.is_file():
            problems.append(f"evidence missing: {case.evidence_ref}")
            continue
        actual = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
        if actual != case.evidence_hash:
            problems.append(f"evidence hash mismatch: {case.evidence_ref}")
            continue
        # evidence bundle: verify every referenced raw artifact as well
        if case.evidence_ref.endswith(".json") and "/bundles/" in case.evidence_ref:
            bundle_problems = verified_bundles.get(case.evidence_ref)
            if bundle_problems is None:
                bundle_problems = _verify_evidence_bundle(
                    store, case.evidence_ref, evidence_path
                )
                verified_bundles[case.evidence_ref] = bundle_problems
            problems.extend(bundle_problems)
    return problems


def _verify_evidence_bundle(
    store: RunStore, bundle_ref: str, bundle_path: Path
) -> list[str]:
    """Re-verify every raw exchange listed inside an evidence bundle
    manifest (audit section 6.3): each evidence_ref must exist and its
    content hash must match."""
    import hashlib
    import json

    problems: list[str] = []
    try:
        doc = json.loads(bundle_path.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as exc:
        return [f"evidence bundle unreadable: {bundle_ref} ({exc})"]
    for entry in doc.get("exchanges", []):
        ref = str(entry.get("evidence_ref", ""))
        expected_hash = str(entry.get("content_hash", ""))
        if not ref or not expected_hash:
            problems.append(f"bundle {bundle_ref}: exchange entry missing ref/hash")
            continue
        artifact_path = store.spike_root / ref
        if not artifact_path.is_file():
            problems.append(f"bundle {bundle_ref}: listed evidence missing: {ref}")
            continue
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != expected_hash:
            problems.append(f"bundle {bundle_ref}: listed evidence hash mismatch: {ref}")
    return problems


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


__all__ = [
    "CaseCatalog",
    "CaseResult",
    "ProductionAccountGateError",
    "RunFailureReason",
    "RunKind",
    "RunLifecycleError",
    "RunStatus",
    "RunStore",
    "RunStoreError",
    "SpikeRun",
    "SpikeVerdict",
    "TERMINAL_RUN_STATUSES",
    "VerdictError",
    "abort_run",
    "close_run",
    "compute_config_hash",
    "compute_environment_lock_hash",
    "compute_verdict",
    "core_gate_satisfied",
    "current_code_commit",
    "fail_run",
    "new_run",
    "resume_run",
    "run_dry_run",
    "verify_evidence_closure",
    "verify_production_account",
]
