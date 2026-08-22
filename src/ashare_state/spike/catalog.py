"""Run-scoped case catalog (audit R2 sections 5/7).

- Every catalog lives under its run directory (physical isolation).
- (spike_run_id, case_id) is the uniqueness key; duplicates are REJECTED.
- Case ids must encode semantics; a bare method+date id cannot be
  registered when multiple semantic case types share an endpoint.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from ashare_state.spike.model import CaseResult, SpikeCase
from ashare_state.spike.run_store import RunStore


class DuplicateCaseError(RuntimeError):
    """A case with the same (spike_run_id, case_id) already exists."""


class CaseCatalog:
    def __init__(self, store: RunStore, spike_run_id: str) -> None:
        self.store = store
        self.spike_run_id = spike_run_id
        self._cases: list[SpikeCase] = []

    # --------------------------------------------------------------- paths
    def _jsonl_path(self, run_dir: Path) -> Path:
        return run_dir / "cases" / "spike_case_catalog.jsonl"

    def _csv_path(self, run_dir: Path) -> Path:
        return run_dir / "cases" / "spike_case_catalog.csv"

    # ------------------------------------------------------------------ io
    def add(self, case: SpikeCase) -> None:
        if case.spike_run_id != self.spike_run_id:
            msg = (
                f"case {case.case_id} binds run {case.spike_run_id}, "
                f"catalog is for {self.spike_run_id}"
            )
            raise ValueError(msg)
        case.validate()
        if any(c.case_id == case.case_id for c in self._cases):
            msg = (
                f"duplicate case_id {case.case_id!r} in run {self.spike_run_id}; "
                "case ids must encode semantics to stay unique"
            )
            raise DuplicateCaseError(msg)
        self._cases.append(case)

    def load(self, run_dir: Path) -> None:
        path = self._jsonl_path(run_dir)
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                payload["result"] = CaseResult(payload["result"])
                self._cases.append(SpikeCase(**payload))

    def flush(self, run_dir: Path) -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "cases").mkdir(parents=True, exist_ok=True)
        jsonl = self._jsonl_path(run_dir)
        with jsonl.open("w", encoding="utf-8") as fh:
            for case in self._cases:
                payload = asdict(case)
                payload["result"] = str(case.result)
                fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        with self._csv_path(run_dir).open("w", encoding="utf-8", newline="") as fh:
            import csv

            names = [f.name for f in fields(SpikeCase)]
            writer = csv.DictWriter(fh, fieldnames=names)
            writer.writeheader()
            for case in self._cases:
                payload = asdict(case)
                payload["result"] = str(case.result)
                writer.writerow(payload)
        return jsonl

    # ------------------------------------------------------------- queries
    @property
    def cases(self) -> list[SpikeCase]:
        return list(self._cases)

    def by_type(self, case_type: str) -> list[SpikeCase]:
        return [c for c in self._cases if c.case_type == case_type]

    def stats(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for c in self._cases:
            bucket = out.setdefault(c.case_type, {})
            bucket[str(c.result)] = bucket.get(str(c.result), 0) + 1
        return out
