"""P0-M-1 Spike orchestrator (single entry point).

Usage (Windows/PowerShell, from repo root):

    # dry-run: validate the whole framework without credentials (CI-safe)
    uv run python scripts/spike/spike_runner.py --dry-run

    # real run on the controlled machine (requires AmazingData SDK installed)
    uv run python scripts/spike/spike_runner.py --phase b1
    uv run python scripts/spike/spike_runner.py --phase b3 --date 2026-08-14
    uv run python scripts/spike/spike_runner.py --phase all --month 2026-07

Phases (design ruling section 14, track B):
    b1  SDK environment verification
    b2  security master / historical codes (incl. delisted)
    b3  daily / status / limit / adj sampling
    b4  ST / delist / corp-action golden discovery
    b5  volume/amount/unit/cache/freshness over one month
    b6  free-float equivalence assessment (four-level verdict)
    b7  taxonomy / benchmark index assessment
    verdict  aggregate catalog -> GO_CORE / GO_DEGRADED / NO_GO draft

Every run appends auditable cases to data/spike/results/spike_case_catalog.*
and archives raw responses under data/spike/raw/.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adk_client import ProviderUnavailableError  # noqa: E402
from case_catalog import CaseCatalog, compute_overall_verdict  # noqa: E402
from samples_b1_sdk import run_b1  # noqa: E402
from samples_b2_b5 import (  # noqa: E402
    ProbeContext as ProbeContextB2B5,
)
from samples_b2_b5 import (
    probe_b2_security_master,
    probe_b3_core_facts,
    probe_b4_golden,
    probe_b5_units_coverage,
)
from samples_b6_b7 import (  # noqa: E402
    ProbeContext as ProbeContextB6B7,
)
from samples_b6_b7 import (
    probe_b6_free_float,
    probe_b7_taxonomy_index,
)

ALL_PHASES = ["b1", "b2", "b3", "b4", "b5", "b6", "b7"]


def _ctx_b2b5(spike_root: Path, catalog: CaseCatalog, module: str, dry_run: bool):
    return ProbeContextB2B5(
        spike_root=spike_root, catalog=catalog, dry_run=dry_run, module_name=module
    )


def _ctx_b6b7(spike_root: Path, catalog: CaseCatalog, module: str, dry_run: bool):
    return ProbeContextB6B7(
        spike_root=spike_root, catalog=catalog, dry_run=dry_run, module_name=module
    )


def run_phase(
    phase: str,
    *,
    spike_root: Path,
    module: str,
    dry_run: bool,
    sample_date: str,
    sample_month: str,
) -> dict[str, object]:
    results_dir = spike_root / "results"
    catalog = CaseCatalog(results_dir)
    catalog.load_existing()

    outputs: dict[str, object] = {"phase": phase}

    if phase == "b1":
        outputs["report"] = str(run_b1(module, spike_root, dry_run=dry_run))
    elif phase == "b2":
        outputs["b2"] = probe_b2_security_master(_ctx_b2b5(spike_root, catalog, module, dry_run))
    elif phase == "b3":
        outputs["b3"] = probe_b3_core_facts(
            _ctx_b2b5(spike_root, catalog, module, dry_run), sample_date
        )
    elif phase == "b4":
        outputs["b4"] = probe_b4_golden(
            _ctx_b2b5(spike_root, catalog, module, dry_run), sample_date
        )
    elif phase == "b5":
        outputs["b5"] = probe_b5_units_coverage(
            _ctx_b2b5(spike_root, catalog, module, dry_run), sample_month
        )
    elif phase == "b6":
        outputs["b6"] = probe_b6_free_float(
            _ctx_b6b7(spike_root, catalog, module, dry_run), sample_date
        )
    elif phase == "b7":
        outputs["b7"] = probe_b7_taxonomy_index(_ctx_b6b7(spike_root, catalog, module, dry_run))
    else:
        msg = f"unknown phase {phase!r}; valid: {ALL_PHASES + ['all', 'verdict']}"
        raise SystemExit(msg)

    catalog.flush()
    outputs["catalog"] = str(catalog.jsonl_path)
    return outputs


def run_verdict(spike_root: Path) -> dict[str, object]:
    """Aggregate the catalog into a draft three-level verdict.

    NOTE: this is a DRAFT scaffold. The capability verdicts fed in here come
    from case results; the final GO/NO-GO decision is written by the report
    author after human review of the evidence (design review node: Spike
    Report + M0 Exit Report submitted together).
    """
    catalog = CaseCatalog(spike_root / "results")
    catalog.load_existing()
    stats = catalog.stats()

    capability_verdicts: dict[str, str] = {}
    for case_type, counts in stats.items():
        if counts["FAIL"] > 0:
            capability_verdicts[case_type] = "FAIL"
        elif counts["PASS"] + counts["DIFF_EXPLAINED"] > 0:
            capability_verdicts[case_type] = "PASS"
        else:
            capability_verdicts[case_type] = "MISSING"

    draft = compute_overall_verdict(capability_verdicts)
    out = {
        "phase": "verdict",
        "case_stats": stats,
        "capability_verdicts": capability_verdicts,
        "draft_overall_verdict": draft,
        "caveat": "DRAFT - requires human review of evidence before submission",
    }
    results_dir = spike_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / "verdict_draft.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    out["path"] = str(path)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="P0-M-1 AmazingData Spike runner")
    parser.add_argument(
        "--phase",
        default="all",
        help=f"one of {ALL_PHASES + ['all', 'verdict']} (default: all)",
    )
    parser.add_argument("--module", default=os.environ.get("AMAZINGDATA_MODULE", "AmazingData"))
    parser.add_argument("--spike-root", default="data/spike")
    parser.add_argument("--date", default="2026-08-14", help="sample trade date for b3/b4/b6")
    parser.add_argument("--month", default="2026-07", help="sample month for b5 (YYYY-MM)")
    parser.add_argument("--dry-run", action="store_true", help="no SDK, fake client, CI-safe")
    args = parser.parse_args()

    spike_root = Path(args.spike_root)
    phases = ALL_PHASES + ["verdict"] if args.phase == "all" else [args.phase]

    for phase in phases:
        try:
            if phase == "verdict":
                out = run_verdict(spike_root)
            else:
                out = run_phase(
                    phase,
                    spike_root=spike_root,
                    module=args.module,
                    dry_run=args.dry_run,
                    sample_date=args.date,
                    sample_month=args.month,
                )
        except ProviderUnavailableError as exc:
            # expected outside the controlled machine; not a framework failure
            print(f"[{phase}] SKIPPED (SDK unavailable): {exc}")
            continue
        print(f"[{phase}] done -> {json.dumps(out, ensure_ascii=False, default=str)[:400]}")


if __name__ == "__main__":
    main()
