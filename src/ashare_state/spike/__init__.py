"""Spike framework (Round-2 audit R2A rewrite).

The spike framework lives in the production package (not scripts/) so
mypy/pytest/coverage cover the code that produces GO/NO-GO evidence.

Layout:
    model.py         SpikeRun / CaseResult / SpikeCase (run-scoped identity)
    run_store.py     physical isolation per run kind + immutable evidence
    catalog.py       run-scoped case catalog (duplicate-id rejection)
    capabilities.py  gate contract == probe contract (coverage -> SPIKE_INCOMPLETE)
    validators.py    SEMANTIC validators (call success is never PASS)
    target.py        single SDK access path (hardened adapter / fake for dry-run)
    probes.py        B2-B7 probes + golden pipeline
    runner.py        orchestration + run-scoped verdict
"""

from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.model import CaseResult, RunKind, SpikeCase, SpikeRun, core_gate_satisfied
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.run_store import RunStore
from ashare_state.spike.runner import (
    SpikeVerdict,
    compute_verdict,
    current_code_commit,
    new_run,
    run_dry_run,
)

__all__ = [
    "CaseCatalog",
    "CaseResult",
    "ProbeContext",
    "RunKind",
    "RunStore",
    "SpikeCase",
    "SpikeRun",
    "SpikeVerdict",
    "compute_verdict",
    "core_gate_satisfied",
    "current_code_commit",
    "new_run",
    "run_dry_run",
]
