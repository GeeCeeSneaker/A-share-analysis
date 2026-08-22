"""Spike runner: orchestration + run-scoped verdict (audit R2 sections 5/8/24).

Verdict rules (R2-P0-04 + section 8):
- Verdict aggregates ONE closed PRODUCTION run (dry-run/trial refused).
- Core capability coverage missing -> SPIKE_INCOMPLETE (never NO_GO).
- NO_GO only when coverage complete AND a core capability genuinely failed.
- GO_CORE: all core VALIDATED_PASS (DIFF_EXPLAINED counts only with
  per-case validator equivalence).
- GO_DEGRADED: core complete & passing, optional capabilities missing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ashare_state.spike.capabilities import (
    ALL_CAPABILITIES,
    CORE_CAPABILITIES,
    OPTIONAL_CAPABILITIES,
    coverage,
)
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunKind, SpikeRun, core_gate_satisfied
from ashare_state.spike.probes import (
    ProbeContext,
    probe_b2_security_master,
    probe_b3_core_facts,
    probe_b4_golden,
    probe_b5_units_pit_freshness,
    probe_b6_replacement,
    probe_b7_capacity,
)
from ashare_state.spike.run_store import RunStore
from ashare_state.spike.target import make_dry_run_target


class VerdictError(RuntimeError):
    """Verdict misuse (e.g. non-production run, open run)."""


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
        }


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
) -> tuple[SpikeRun, RunStore]:
    import uuid as uuid_module

    run = SpikeRun(
        spike_run_id=str(uuid_module.uuid4()),
        run_kind=run_kind,
        code_commit=code_commit,
        environment_lock_hash=environment_lock_hash,
        config_hash=config_hash,
        sdk_version=sdk_version,
        runtime_version=runtime_version,
        account_profile_id=account_profile_id,
    )
    store = RunStore(spike_root)
    store.initialize(run)
    return run, store


def current_code_commit(repo_root: Path | None = None) -> str:
    """Best-effort commit id for run provenance."""
    try:
        root = repo_root or Path.cwd()
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - provenance is best-effort, never fatal
        return "unknown"


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
    ctx = ProbeContext(run, store, catalog, target)
    outputs: dict[str, Any] = {"spike_run_id": run.spike_run_id, "phases": {}}
    outputs["phases"]["b2"] = probe_b2_security_master(ctx)
    outputs["phases"]["b3"] = probe_b3_core_facts(ctx, sample_date)
    outputs["phases"]["b4"] = probe_b4_golden(ctx, sample_date)
    outputs["phases"]["b5"] = probe_b5_units_pit_freshness(ctx, sample_date)
    outputs["phases"]["b6"] = probe_b6_replacement(ctx, sample_date)
    outputs["phases"]["b7"] = probe_b7_capacity(ctx, sample_date)
    run_dir = store.run_dir(run)
    catalog.flush(run_dir)
    run = SpikeRun(
        **{**run.to_json(), "run_kind": run.run_kind, "ended_at": _now(), "status": "CLOSED"}
    )
    store.save_run(run)
    outputs["run_dir"] = str(run_dir)
    return outputs


def compute_verdict(store: RunStore, run: SpikeRun) -> SpikeVerdict:
    """Run-scoped verdict aggregation (R2 sections 5/8)."""
    store.assert_verdict_eligible(run)
    catalog = CaseCatalog(store, run.spike_run_id)
    catalog.load(store.run_dir(run))
    stats = catalog.stats()

    core_reports = coverage(CORE_CAPABILITIES, stats)
    optional_reports = coverage(OPTIONAL_CAPABILITIES, stats)

    capability_status: dict[str, str] = {}
    missing_core: list[str] = []
    failed_core: list[str] = []
    for rep in core_reports:
        if rep.missing_case_types:
            capability_status[rep.capability_id] = "MISSING"
            missing_core.append(rep.capability_id)
        elif rep.fail_count > 0 and rep.pass_count == 0:
            capability_status[rep.capability_id] = "FAILED"
            failed_core.append(rep.capability_id)
        elif rep.pass_count == 0:
            capability_status[rep.capability_id] = "NOT_VALIDATED"
            missing_core.append(rep.capability_id)
        else:
            capability_status[rep.capability_id] = "PASS"

    missing_optional: list[str] = []
    for rep in optional_reports:
        if rep.missing_case_types or rep.pass_count == 0:
            capability_status[rep.capability_id] = "MISSING"
            missing_optional.append(rep.capability_id)
        elif rep.fail_count > 0 and rep.pass_count == 0:
            capability_status[rep.capability_id] = "FAILED"
        else:
            capability_status[rep.capability_id] = "PASS"

    if missing_core:
        verdict = "SPIKE_INCOMPLETE"
    elif failed_core:
        verdict = "NO_GO"
    elif missing_optional:
        verdict = "GO_DEGRADED"
    else:
        verdict = "GO_CORE"

    return SpikeVerdict(
        verdict=verdict,
        run_id=run.spike_run_id,
        run_kind=str(run.run_kind),
        capability_status=capability_status,
        missing_core=missing_core,
        failed_core=failed_core,
        missing_optional=missing_optional,
        case_stats=stats,
    )


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


__all__ = [
    "SpikeVerdict",
    "VerdictError",
    "compute_verdict",
    "current_code_commit",
    "new_run",
    "run_dry_run",
    "RunKind",
    "SpikeRun",
    "RunStore",
    "CaseCatalog",
    "ProbeContext",
    "core_gate_satisfied",
    "CaseResult",
    "ALL_CAPABILITIES",
]
