"""Provider-Normalized -> Canonical runtime (CR-3, audit 20260901).

The ONE formal canonical boundary::

    CR-2 eligible Provider-Normalized runs (SUCCESS only; PARTIAL only
      where the domain SourcePolicy allows it - none does in v1)
        -> read-only closure verification (verify_normalized_run)
        -> governed identity bridge (security_master -> security_id,
           fail closed on missing/ambiguous)
        -> typed availability derivation + as_of filter
           (BEFORE any source selection - CR3-P0-03)
        -> source selection / EXACT reconciliation per static
           versioned SourcePolicy (no caller injection - CR3-P0-07)
        -> immutable canonical artifacts (selected/decisions/findings
           parquet + manifest LAST) + canonicalization ledger row
           committed in ONE DuckDB transaction with count assertions

Machine-enforced invariants:

- P0-01 the canonicalizer's ONLY input is the CR-2 verified
  Provider-Normalized ledger + artifacts (+ the raw meta for the
  conservative OBSERVED_AT_INGEST availability); it never calls the
  provider SDK, never re-maps raw payloads, never accepts caller
  DataFrames, never bypasses CR-2 seals;
- P0-04 available_at is the typed OBSERVED_AT_INGEST moment from the
  raw envelope (never trade_date 00:00 / 1970 / a hard-coded close
  time);
- P0-08 no silent fallback: unavailable preferred sources yield
  REQUIRED_DOMAIN_MISSING findings; any fallback would be an explicit
  FALLBACK_SELECTED decision under policy (none is allowed in v1);
- P0-09 reconciliation is EXACT per key: equal values merge with an
  EQUIVALENT_MERGED decision (deterministic winner), unequal values
  are a blocking SOURCE_CONFLICT finding - never last-write-wins;
- P0-13/P0-14 the run identity is deterministic over the exact input
  set + as_of + contract + identity/availability/source/tolerance
  policy identities + the canonicalizer code fingerprint; a prior run
  with the same identity is closure-re-verified before an idempotent
  replay (tampered/missing artifacts fail closed);
- P0-15 the state machine is SUCCESS / BLOCKED (PARTIAL only by
  policy, never by the caller).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from ashare_state.canonical import availability as _availability
from ashare_state.canonical import source_policy as _source_policy
from ashare_state.canonical.availability import derive_available_at
from ashare_state.canonical.eligibility import (
    CANONICAL_CONTRACT_VERSION,
    DomainEligibility,
    domain_spec,
    supported_domains,
)
from ashare_state.canonical.identity import IdentityBridge
from ashare_state.normalization.runner import verify_normalized_run

__all__ = [
    "CanonicalRunner",
    "CanonicalRunnerError",
    "CanonicalRunResult",
    "canonical_code_fingerprint",
]


class CanonicalRunnerError(RuntimeError):
    """The canonical boundary contract was violated (damaged prior run,
    identity dataset corruption, unreadable verified artifacts)."""


_RUN_NAMESPACE = uuid.UUID("b7a3c1d5-9e2f-4a6b-8c4d-7f5e3a2b1c90")
_FINDING_NAMESPACE = uuid.UUID("c8b4d2e6-1f3a-5b7c-9d5e-8a6f4b3c2d01")

#: provider market code -> suffix (verified provider semantics shared
#: with the frozen CR-2 mapper; NOT bare-code prefix guessing)
_MARKET_SUFFIX = {"1": ".SH", "2": ".SZ", "3": ".BJ"}

_LEDGER_COLUMNS = (
    "canonical_run_id",
    "as_of",
    "canonical_contract_version",
    "input_set_hash",
    "identity_dataset_hash",
    "availability_policy_version",
    "availability_policy_hash",
    "source_policy_version",
    "source_policy_hash",
    "tolerance_policy_version",
    "tolerance_policy_hash",
    "code_fingerprint",
    "manifest_uri",
    "manifest_hash",
    "selected_count",
    "decision_count",
    "finding_count",
    "status",
    "error_message",
    "idempotency_key",
    "idempotent_replay",
    "started_at",
    "completed_at",
    "finding_set_hash",
)

_FINDING_COLUMNS = (
    "finding_id",
    "canonical_run_id",
    "canonical_domain",
    "canonical_key",
    "finding_class",
    "provider",
    "source_normalization_run_id",
    "detail_json",
    "blocking",
    "created_at",
)

_FINDING_SEMANTIC_FIELDS = (
    "canonical_domain",
    "canonical_key",
    "finding_class",
    "provider",
    "source_normalization_run_id",
    "detail_json",
    "blocking",
)


@dataclass(frozen=True)
class CanonicalRunResult:
    canonical_run_id: str
    as_of: str
    status: str
    selected_count: int
    decision_count: int
    finding_count: int
    manifest_uri: str | None
    manifest_hash: str | None
    idempotent_replay: bool
    domains: tuple[str, ...] = ()
    finding_set_hash: str | None = None
    error_message: str | None = None


def canonical_code_fingerprint() -> str:
    """SHA-256 over the governed canonical module sources (line-ending
    normalized) - SYSTEM-DERIVED, entering the canonical run identity
    (a canonicalizer code change yields a NEW run, history preserved)."""
    import ashare_state.canonical.availability as _availability
    import ashare_state.canonical.canonicalizer as _canonicalizer
    import ashare_state.canonical.eligibility as _eligibility
    import ashare_state.canonical.identity as _identity
    import ashare_state.canonical.source_policy as _source_policy

    digest = hashlib.sha256()
    for module in (_canonicalizer, _eligibility, _availability, _identity, _source_policy):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            msg = f"canonical module {module!r} has no source file - cannot fingerprint"
            raise RuntimeError(msg)
        source = Path(module_file).read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(source).to_bytes(8, "big"))
        digest.update(source)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _finding_set_hash(findings: list[dict[str, Any]]) -> str:
    ordered = sorted(
        findings, key=lambda f: _canonical_json({k: f.get(k) for k in _FINDING_SEMANTIC_FIELDS})
    )
    semantic = [{field: f.get(field) for field in _FINDING_SEMANTIC_FIELDS} for f in ordered]
    return hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        return date.fromisoformat(text[:10])
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    msg = f"unparsable date {value!r}"
    raise CanonicalRunnerError(msg)


def _parse_ts(value: Any) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _align_schema(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Union-align heterogeneous domain rows so one parquet artifact
    can carry them (missing fields -> None, order stable)."""
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return [{key: row.get(key) for key in keys} for row in rows]


class CanonicalRunner:
    """The formal canonical runtime. Inputs are the CR-2 ledger +
    verified artifacts ONLY - there is no provider/SDK access, no
    caller-supplied candidates, and no correctness-policy parameter
    anywhere in the API (``run(as_of, domains=...)`` - as_of is the PIT
    query point, domains selects WHICH governed domains to build)."""

    def __init__(
        self,
        conn: Any,
        *,
        raw_root: Path | str,
        normalized_root: Path | str,
    ) -> None:
        self.conn = conn
        self.raw_root = Path(raw_root)
        self.normalized_root = Path(normalized_root)

    # ---------------------------------------------------------------- api
    def run(
        self,
        as_of: datetime | str,
        *,
        domains: tuple[str, ...] | list[str] | None = None,
    ) -> CanonicalRunResult:
        started = datetime.now(UTC)
        as_of_dt = as_of if isinstance(as_of, datetime) else _parse_ts(as_of)
        as_of_dt = as_of_dt.astimezone(UTC)
        requested = tuple(domains) if domains else supported_domains()
        for domain in requested:
            spec = domain_spec(domain)
            if spec.eligibility is not DomainEligibility.CANONICAL_SUPPORTED:
                msg = (
                    f"canonical domain {domain!r} is {spec.eligibility.value} - "
                    "it can never produce canonical rows (no silent skip)"
                )
                raise CanonicalRunnerError(msg)

        # ------------------------------ exact replay lookup (history-wide)
        fingerprint = canonical_code_fingerprint()
        idempotency_key = self._run_identity(as_of_dt, fingerprint)
        run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
        prior = self.conn.execute(
            "SELECT canonical_run_id FROM meta_canonicalization_run WHERE canonical_run_id = ?",
            [run_id],
        ).fetchone()
        if prior is not None:
            return self._require_verified_replay(run_id, idempotency_key)

        # ------------------------------------------ eligible CR-2 runs
        eligible, findings = self._collect_verified_runs(requested)

        # ------------------------------------------ identity bridge
        bridge, master_rows = self._build_identity_bridge()

        # ------------------------------------------ candidates per domain
        selected_rows: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        identity_missing_count = 0

        for domain in requested:
            policy = _source_policy.source_policy_for(domain)
            candidates: list[dict[str, Any]] = []
            for run_row in eligible.get(domain, []):
                candidates.extend(self._build_candidates(domain, run_row, bridge))
            # ---- availability filter BEFORE selection (CR3-P0-03)
            available: list[dict[str, Any]] = []
            for candidate in candidates:
                if candidate["available_at"] <= as_of_dt:
                    available.append(candidate)
                else:
                    decisions.append(
                        self._decision(domain, candidate, "EXCLUDED_FUTURE", "available_at > as_of")
                    )
            # ---- identity resolution findings (fail closed, never a
            # bare-symbol key fallback)
            for candidate in available:
                if candidate.get("identity_status") == "MISSING":
                    identity_missing_count += 1
            rows, domain_decisions, domain_findings = self._select(domain, policy, available)
            selected_rows.extend(rows)
            decisions.extend(domain_decisions)
            findings.extend(domain_findings)

        for domain in requested:
            if not eligible.get(domain):
                findings.append(
                    self._finding(
                        domain,
                        "",
                        "REQUIRED_DOMAIN_MISSING",
                        None,
                        None,
                        {"reason": "no eligible verified candidate at this as_of"},
                        blocking=True,
                    )
                )
        if identity_missing_count > 0:
            findings.append(
                self._finding(
                    "daily_bar",
                    "",
                    "IDENTITY_MISSING",
                    None,
                    None,
                    {
                        "count": identity_missing_count,
                        "reason": (
                            "provider symbols without a governed security_master "
                            "identity entry were EXCLUDED (never a bare-symbol "
                            "canonical key fallback)"
                        ),
                    },
                    blocking=True,
                )
            )

        blocking = [f for f in findings if f["blocking"]]
        if blocking:
            status = "BLOCKED"
            error = f"{len(blocking)} blocking finding(s): " + "; ".join(
                sorted({str(f["finding_class"]) for f in blocking})
            )
        else:
            status = "SUCCESS"
            error = None

        # ------------------------------------------ deterministic artifacts
        manifest_uri, manifest_hash, finding_seal = self._write_artifacts(
            run_id=run_id,
            as_of_dt=as_of_dt,
            requested=requested,
            eligible=eligible,
            bridge=bridge,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            selected_rows=selected_rows,
            decisions=decisions,
            findings=findings,
            status=status,
        )
        completed = datetime.now(UTC)
        self._commit_ledger(
            run_id=run_id,
            as_of_dt=as_of_dt,
            fingerprint=fingerprint,
            idempotency_key=idempotency_key,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            selected_count=len(selected_rows),
            decision_count=len(decisions),
            findings=findings,
            finding_seal=finding_seal,
            status=status,
            error=error,
            started=started,
            completed=completed,
        )
        return CanonicalRunResult(
            canonical_run_id=run_id,
            as_of=as_of_dt.isoformat(),
            status=status,
            selected_count=len(selected_rows),
            decision_count=len(decisions),
            finding_count=len(findings),
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            idempotent_replay=False,
            domains=tuple(requested),
            finding_set_hash=finding_seal,
            error_message=error,
        )

    # ------------------------------------------------------------- inputs
    def _collect_verified_runs(
        self, requested: tuple[str, ...]
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Eligible CR-2 runs per domain: SUCCESS status only (PARTIAL is
        eligible only where the domain policy allows - none does in
        v1), each closure-verified read-only before consumption."""
        eligible: dict[str, list[dict[str, Any]]] = {}
        findings: list[dict[str, Any]] = []
        for domain in requested:
            spec = domain_spec(domain)
            for run_row in self._surface_runs(spec.normalization_surface, spec.provider_datasets):
                problems = verify_normalized_run(
                    self.conn,
                    run_row["normalization_run_id"],
                    raw_root=self.raw_root,
                    normalized_root=self.normalized_root,
                )
                if problems:
                    findings.append(
                        self._finding(
                            domain,
                            "",
                            "CLOSURE_VERIFICATION_FAILED",
                            run_row["provider"],
                            run_row["normalization_run_id"],
                            {"problems": problems},
                            blocking=True,
                        )
                    )
                    continue
                eligible.setdefault(domain, []).append(run_row)
        return eligible, findings

    def _surface_runs(
        self, normalization_surface: str, provider_datasets: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT normalization_run_id, provider, normalization_surface, "
            "provider_dataset, raw_request_id, raw_evidence_uri, raw_evidence_hash, "
            "normalization_contract_version, mapper_identity, "
            "normalized_manifest_uri, normalized_manifest_hash, status "
            "FROM meta_provider_normalization_run "
            "WHERE provider = 'amazingdata' AND normalization_surface = ? "
            "AND provider_dataset IN (" + ",".join("?" * len(provider_datasets)) + ") "
            "AND status = 'SUCCESS' ORDER BY normalization_run_id",
            [normalization_surface, *provider_datasets],
        ).fetchall()
        return [
            {
                "normalization_run_id": str(r[0]),
                "provider": str(r[1]),
                "normalization_surface": str(r[2]),
                "provider_dataset": str(r[3]),
                "raw_request_id": str(r[4]),
                "raw_evidence_uri": str(r[5]),
                "raw_evidence_hash": str(r[6]),
                "normalization_contract_version": str(r[7]),
                "mapper_identity": str(r[8]),
                "normalized_manifest_uri": str(r[9]),
                "normalized_manifest_hash": str(r[10]),
                "status": str(r[11]),
            }
            for r in rows
        ]

    def _build_identity_bridge(self) -> tuple[IdentityBridge, list[dict[str, Any]]]:
        """The governed identity dataset: ALL verified security_master
        runs across every master dataset (code_list / hist_code_list /
        stock_basic)."""
        master_rows: list[dict[str, Any]] = []
        dataset_parts: list[str] = []
        for run_row in self._surface_runs(
            "security_master", ("code_list", "hist_code_list", "stock_basic")
        ):
            problems = verify_normalized_run(
                self.conn,
                run_row["normalization_run_id"],
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
            if problems:
                continue
            dataset_parts.append(
                f"{run_row['normalization_run_id']}:{run_row['normalized_manifest_hash']}"
            )
            master_rows.extend(self._read_output_rows(run_row["normalization_run_id"], "main"))
        dataset_hash = hashlib.sha256("|".join(dataset_parts).encode("utf-8")).hexdigest()
        return IdentityBridge(master_rows, dataset_hash=dataset_hash), master_rows

    # --------------------------------------------------------- candidates
    def _build_candidates(
        self, domain: str, run_row: dict[str, Any], bridge: IdentityBridge
    ) -> list[dict[str, Any]]:
        """Deterministic candidates from ONE verified CR-2 run: each row
        of the domain's output table with its availability (raw envelope
        received_at), identity and lineage. Availability is attached but
        NOT filtered here - the filter runs before selection."""
        spec = domain_spec(domain)
        received_at = self._received_at(run_row)
        available_at = derive_available_at(domain, received_at)
        rows = self._read_output_rows(run_row["normalization_run_id"], spec.output_name)
        manifest = self._read_manifest(run_row)
        output_meta = {str(o.get("output_name")): o for o in manifest.get("outputs", [])}.get(
            spec.output_name, {}
        )

        candidates: list[dict[str, Any]] = []
        for ordinal, row in enumerate(rows):
            row_identity = hashlib.sha256(_canonical_json(row).encode("utf-8")).hexdigest()
            if domain == "trade_calendar":
                # one CR-2 calendar row carries the whole market's days;
                # expand to one candidate per (market, trade_date)
                for day in row.get("trading_days") or []:
                    trade_date = _as_date(day)
                    key = (str(row.get("market")), trade_date.isoformat())
                    candidates.append(
                        self._candidate(
                            domain,
                            spec,
                            run_row,
                            ordinal,
                            row_identity,
                            output_meta,
                            key,
                            {"market": row.get("market")},
                            trade_date,
                            None,
                            "RESOLVED_NOT_REQUIRED",
                            received_at,
                            available_at,
                        )
                    )
                continue
            trade_date = self._trade_date_of(domain, row)
            security_id: str | None = None
            identity_status = "RESOLVED_NOT_REQUIRED"
            if spec.requires_security_identity:
                symbol = self._provider_symbol_of(domain, row)
                if symbol is None:
                    identity_status = "MISSING"
                else:
                    security_id = bridge.resolve(symbol, trade_date)
                    identity_status = "RESOLVED" if security_id else "MISSING"
            key = self._natural_key(domain, row, security_id, trade_date)
            payload = {field: row.get(field) for field in spec.payload_fields}
            candidates.append(
                self._candidate(
                    domain,
                    spec,
                    run_row,
                    ordinal,
                    row_identity,
                    output_meta,
                    key,
                    payload,
                    trade_date,
                    security_id,
                    identity_status,
                    received_at,
                    available_at,
                )
            )
        return candidates

    def _candidate(
        self,
        domain: str,
        spec: Any,
        run_row: dict[str, Any],
        ordinal: int,
        row_identity: str,
        output_meta: dict[str, Any],
        key: tuple[Any, ...],
        payload: dict[str, Any],
        trade_date: date,
        security_id: str | None,
        identity_status: str,
        received_at: datetime,
        available_at: datetime,
    ) -> dict[str, Any]:
        return {
            "domain": domain,
            "key": key,
            "key_json": _canonical_json(list(key)),
            "identity_status": identity_status,
            "security_id": security_id,
            "trade_date": trade_date.isoformat(),
            "payload": payload,
            "provider": run_row["provider"],
            "run_row": run_row,
            "output_name": spec.output_name,
            "ordinal": ordinal,
            "row_identity": row_identity,
            "available_at": available_at,
            "received_at": received_at,
            "run_manifest_hash": str(run_row["normalized_manifest_hash"]),
            "output_content_hash": str(output_meta.get("content_hash") or ""),
        }

    def _select(
        self, domain: str, policy: Any, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Deterministic source selection + EXACT reconciliation over
        the PIT-available candidates of ONE domain.

        Selection order: (provider priority index, run manifest hash,
        row ordinal) - fully deterministic, provider iteration order can
        never influence the winner. Equal values at one key merge with
        an EQUIVALENT_MERGED decision; unequal values are a blocking
        SOURCE_CONFLICT finding (EXACT tolerance - never
        last-write-wins). Duplicate keys within one run output are a
        blocking DUPLICATE_CANONICAL_KEY finding (never silent dedupe)."""
        usable = [c for c in candidates if c["identity_status"] != "MISSING"]
        by_key: dict[tuple, list[dict[str, Any]]] = {}
        for candidate in usable:
            by_key.setdefault(candidate["key"], []).append(candidate)

        selected: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        priority = {p: i for i, p in enumerate(policy.priority_providers)}

        for key in sorted(by_key, key=_canonical_json):
            group = sorted(
                by_key[key],
                key=lambda c: (
                    priority.get(c["provider"], len(priority)),
                    c["run_manifest_hash"],
                    c["ordinal"],
                ),
            )
            winner = group[0]
            for other in group[1:]:
                if self._payload_equal(winner, other):
                    decisions.append(
                        self._decision(
                            domain,
                            other,
                            "EQUIVALENT_MERGED",
                            "equal values (EXACT tolerance); deterministic winner "
                            f"{winner['run_row']['normalization_run_id'][:12]}",
                        )
                    )
                else:
                    findings.append(
                        self._finding(
                            domain,
                            winner["key_json"],
                            "SOURCE_CONFLICT",
                            other["provider"],
                            other["run_row"]["normalization_run_id"],
                            {
                                "winner_run": winner["run_row"]["normalization_run_id"],
                                "winner_values": winner["payload"],
                                "conflicting_run": other["run_row"]["normalization_run_id"],
                                "conflicting_values": other["payload"],
                                "tolerance": policy.tolerance_rule_id,
                            },
                            blocking=True,
                        )
                    )
            decisions.append(
                self._decision(domain, winner, "SELECTED", "deterministic policy winner")
            )
            selected.append(self._canonical_row(domain, winner))

        seen: set[tuple[str, str]] = set()
        for candidate in usable:
            marker = (candidate["run_row"]["normalization_run_id"], candidate["key_json"])
            if marker in seen:
                findings.append(
                    self._finding(
                        domain,
                        candidate["key_json"],
                        "DUPLICATE_CANONICAL_KEY",
                        candidate["provider"],
                        candidate["run_row"]["normalization_run_id"],
                        {"output_name": candidate["output_name"]},
                        blocking=True,
                    )
                )
            else:
                seen.add(marker)
        return selected, decisions, findings

    # ------------------------------------------------------------ helpers
    def _run_identity(self, as_of_dt: datetime, fingerprint: str) -> str:
        input_set = self._input_set_hash()
        identity_hash = self._identity_dataset_hash()
        tolerance_version, tolerance_hash = _source_policy.tolerance_policy_identity()
        return hashlib.sha256(
            "|".join(
                (
                    input_set,
                    identity_hash,
                    as_of_dt.isoformat(),
                    CANONICAL_CONTRACT_VERSION,
                    _availability.availability_policy_version(),
                    _availability.availability_policy_hash(),
                    _source_policy.source_policy_version(),
                    _source_policy.source_policy_hash(),
                    tolerance_version,
                    tolerance_hash,
                    fingerprint,
                )
            ).encode("utf-8")
        ).hexdigest()

    def _relevant_surfaces(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        surfaces: dict[str, set[str]] = {}
        for domain in (*supported_domains(), "security_master"):
            spec = domain_spec(domain)
            surfaces.setdefault(spec.normalization_surface, set()).update(spec.provider_datasets)
        return tuple(
            (surface, tuple(sorted(datasets))) for surface, datasets in sorted(surfaces.items())
        )

    def _input_set_hash(self) -> str:
        parts: list[str] = []
        for surface, datasets in self._relevant_surfaces():
            for run_row in self._surface_runs(surface, datasets):
                parts.append(
                    f"{run_row['normalization_run_id']}:{run_row['normalized_manifest_hash']}"
                )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _identity_dataset_hash(self) -> str:
        parts = [
            f"{r['normalization_run_id']}:{r['normalized_manifest_hash']}"
            for r in self._surface_runs(
                "security_master", ("code_list", "hist_code_list", "stock_basic")
            )
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _read_manifest(self, run_row: dict[str, Any]) -> dict[str, Any]:
        path = self.normalized_root / str(run_row["normalized_manifest_uri"])
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_output_rows(self, run_id: str, output_name: str) -> list[dict[str, Any]]:
        row = self.conn.execute(
            "SELECT normalized_manifest_uri FROM meta_provider_normalization_run "
            "WHERE normalization_run_id = ?",
            [run_id],
        ).fetchone()
        if row is None or row[0] is None:
            msg = f"normalization run {run_id} carries no manifest uri"
            raise CanonicalRunnerError(msg)
        manifest = json.loads((self.normalized_root / str(row[0])).read_text(encoding="utf-8"))
        for output in manifest.get("outputs", []):
            if str(output.get("output_name")) == output_name:
                frame = pl.read_parquet(self.normalized_root / str(output.get("uri")))
                return frame.to_dicts()
        return []

    def _received_at(self, run_row: dict[str, Any]) -> datetime:
        """The conservative OBSERVED_AT_INGEST moment: the provider
        answer time persisted on the raw envelope (read from the CR-2
        bound raw evidence). Never trade_date 00:00 / 1970 / a fixed
        close time."""
        meta_path = self.raw_root / str(run_row["raw_evidence_uri"])
        doc = json.loads(meta_path.read_text(encoding="utf-8"))
        return _parse_ts(doc["received_at"])

    @staticmethod
    def _trade_date_of(domain: str, row: dict[str, Any]) -> date:
        if domain == "daily_bar":
            return _as_date(row["kline_time"])
        if domain == "adj_factor":
            return _as_date(row["ex_date"])
        return _as_date(row["trade_date"])

    @staticmethod
    def _provider_symbol_of(domain: str, row: dict[str, Any]) -> str | None:
        symbol = str(row.get("provider_symbol") or "")
        if symbol:
            return symbol
        if domain == "security_status":
            market = str(row.get("market_code") or "")
            suffix = _MARKET_SUFFIX.get(market)
            if suffix is None:
                return None
            return f"{row.get('security_code')}{suffix}"
        return None

    @staticmethod
    def _natural_key(
        domain: str, row: dict[str, Any], security_id: str | None, trade_date: date
    ) -> tuple[Any, ...]:
        if domain == "adj_factor":
            return (str(security_id), trade_date.isoformat(), str(row.get("factor_type")))
        if domain == "trade_calendar":
            return (str(row.get("market")), trade_date.isoformat())
        return (str(security_id), trade_date.isoformat())

    @staticmethod
    def _payload_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
        return _canonical_json(a["payload"]) == _canonical_json(b["payload"])

    def _canonical_row(self, domain: str, candidate: dict[str, Any]) -> dict[str, Any]:
        spec = domain_spec(domain)
        run_row = candidate["run_row"]
        row: dict[str, Any] = {
            "canonical_domain": domain,
            "canonical_key": candidate["key_json"],
        }
        if spec.requires_security_identity:
            row["security_id"] = candidate["security_id"]
        row.update(candidate["payload"])
        row.update(
            {
                "trade_date": candidate["trade_date"],
                "available_at": candidate["available_at"].isoformat(),
                "ingested_at": candidate["received_at"].isoformat(),
                "availability_basis": "OBSERVED_AT_INGEST",
                "availability_policy_version": _availability.availability_policy_version(),
                "selected_provider": candidate["provider"],
                "source_normalization_run_id": run_row["normalization_run_id"],
                "source_output_name": candidate["output_name"],
                "source_row_ordinal": candidate["ordinal"],
                "source_row_identity_hash": candidate["row_identity"],
                "source_raw_request_id": run_row["raw_request_id"],
                "source_raw_evidence_hash": run_row["raw_evidence_hash"],
                "source_mapper_identity": run_row["mapper_identity"],
                "source_policy_version": _source_policy.source_policy_version(),
                "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
            }
        )
        return row

    @staticmethod
    def _decision(
        domain: str, candidate: dict[str, Any], decision_class: str, reason: str
    ) -> dict[str, Any]:
        return {
            "canonical_domain": domain,
            "canonical_key": candidate["key_json"],
            "decision_class": decision_class,
            "provider": candidate["provider"],
            "source_normalization_run_id": candidate["run_row"]["normalization_run_id"],
            "source_row_ordinal": candidate["ordinal"],
            "available_at": candidate["available_at"].isoformat(),
            "reason": reason,
        }

    @staticmethod
    def _finding(
        domain: str,
        key_json: str,
        finding_class: str,
        provider: str | None,
        source_run_id: str | None,
        detail: dict[str, Any],
        *,
        blocking: bool,
    ) -> dict[str, Any]:
        return {
            "canonical_domain": domain,
            "canonical_key": key_json,
            "finding_class": finding_class,
            "provider": provider,
            "source_normalization_run_id": source_run_id,
            "detail_json": _canonical_json(detail),
            "blocking": blocking,
        }

    # ------------------------------------------------------------ replay
    def _require_verified_replay(self, run_id: str, idempotency_key: str) -> CanonicalRunResult:
        row = self.conn.execute(
            f"SELECT {', '.join(_LEDGER_COLUMNS)} FROM meta_canonicalization_run "
            "WHERE canonical_run_id = ?",
            [run_id],
        ).fetchone()
        if row is None:
            msg = f"prior canonical run {run_id} missing from the ledger - repair required"
            raise CanonicalRunnerError(msg)
        record = dict(zip(_LEDGER_COLUMNS, row, strict=True))
        if str(record["idempotency_key"]) != idempotency_key:
            msg = f"prior canonical run {run_id} identity mismatch - repair required"
            raise CanonicalRunnerError(msg)
        problems = self._verify_closure(record)
        if problems:
            msg = (
                f"existing canonical run {run_id} is DAMAGED - idempotent replay "
                f"refused, repair required: {'; '.join(problems)}"
            )
            raise CanonicalRunnerError(msg)
        return CanonicalRunResult(
            canonical_run_id=str(record["canonical_run_id"]),
            as_of=str(record["as_of"]),
            status=str(record["status"]),
            selected_count=int(record["selected_count"]),
            decision_count=int(record["decision_count"]),
            finding_count=int(record["finding_count"]),
            manifest_uri=str(record["manifest_uri"]) if record["manifest_uri"] else None,
            manifest_hash=str(record["manifest_hash"]) if record["manifest_hash"] else None,
            idempotent_replay=True,
            finding_set_hash=str(record["finding_set_hash"])
            if record["finding_set_hash"]
            else None,
            error_message=str(record["error_message"]) if record["error_message"] else None,
        )

    def _verify_closure(self, record: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        manifest_uri = record["manifest_uri"]
        manifest_hash = record["manifest_hash"]
        if not manifest_uri or not manifest_hash:
            return ["ledger row carries no manifest binding"]
        manifest_path = self.normalized_root / str(manifest_uri)
        if not manifest_path.is_file():
            return [f"canonical manifest missing: {manifest_uri}"]
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != str(manifest_hash):
            return [f"canonical manifest bytes do not match the ledger hash: {manifest_uri}"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field, expected in (
            ("canonical_run_id", str(record["canonical_run_id"])),
            ("canonical_contract_version", str(record["canonical_contract_version"])),
            ("idempotency_key", str(record["idempotency_key"])),
            ("status", str(record["status"])),
        ):
            if str(manifest.get(field)) != expected:
                problems.append(f"manifest field {field} does not match the ledger")
        if int(manifest.get("finding_count", -1)) != int(record["finding_count"]):
            problems.append("manifest finding_count does not match the ledger")
        for artifact in ("selected", "decisions", "findings"):
            entry = manifest.get("artifacts", {}).get(artifact)
            if entry is None:
                problems.append(f"manifest carries no {artifact} artifact entry")
                continue
            path = self.normalized_root / str(entry.get("uri"))
            if not path.is_file():
                problems.append(f"canonical {artifact} artifact missing: {entry.get('uri')}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != str(entry.get("content_hash")):
                problems.append(f"canonical {artifact} artifact bytes tampered")
                continue
            frame = pl.read_parquet(path)
            if frame.height != int(entry.get("row_count", -1)):
                problems.append(f"canonical {artifact} artifact row count mismatch")
        rows = self.conn.execute(
            f"SELECT {', '.join(_FINDING_SEMANTIC_FIELDS)} FROM "
            "meta_canonical_reconciliation_finding WHERE canonical_run_id = ? "
            "ORDER BY finding_id",
            [str(record["canonical_run_id"])],
        ).fetchall()
        if len(rows) != int(record["finding_count"]):
            problems.append(
                f"finding count mismatch: ledger {int(record['finding_count'])} vs {len(rows)}"
            )
        db_findings = [dict(zip(_FINDING_SEMANTIC_FIELDS, r, strict=True)) for r in rows]
        if _finding_set_hash(db_findings) != str(record["finding_set_hash"]):
            problems.append("finding exact-set seal mismatch (tampered or missing rows)")
        return problems

    # ----------------------------------------------------------- artifacts
    def _write_artifacts(
        self,
        *,
        run_id: str,
        as_of_dt: datetime,
        requested: tuple[str, ...],
        eligible: dict[str, list[dict[str, Any]]],
        bridge: IdentityBridge,
        fingerprint: str,
        idempotency_key: str,
        selected_rows: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        status: str,
    ) -> tuple[str | None, str | None, str]:
        tolerance_version, tolerance_hash = _source_policy.tolerance_policy_identity()
        base_uri = (
            f"canonical/contract={CANONICAL_CONTRACT_VERSION}/"
            f"as_of={as_of_dt.strftime('%Y%m%dT%H%M%SZ')}/run={run_id}"
        )
        base_path = self.normalized_root / base_uri
        base_path.mkdir(parents=True, exist_ok=True)

        # bind deterministic finding ids before sealing
        for position, finding in enumerate(findings):
            finding["finding_id"] = f"cf-{uuid.uuid5(_FINDING_NAMESPACE, f'{run_id}:{position}')}"
            finding["canonical_run_id"] = run_id
            finding["created_at"] = datetime.now(UTC).isoformat()
        finding_seal = _finding_set_hash(findings)

        artifacts: dict[str, dict[str, Any]] = {}
        import io

        for name, rows in (
            ("selected", _align_schema(selected_rows)),
            ("decisions", _align_schema(decisions)),
            ("findings", _align_schema(findings)),
        ):
            frame = pl.DataFrame(rows)
            if frame.height > 0:
                frame = frame.sort(frame.columns)
            uri = f"{base_uri}/{name}.parquet"
            path = self.normalized_root / uri
            buf = io.BytesIO()
            frame.write_parquet(buf)
            data = buf.getvalue()
            self._write_immutable(path, data, run_id)
            artifacts[name] = {
                "uri": uri,
                "content_hash": hashlib.sha256(data).hexdigest(),
                "schema_hash": hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest(),
                "row_count": frame.height,
            }

        semantic = hashlib.sha256(
            _canonical_json(sorted(_canonical_json(r) for r in selected_rows)).encode("utf-8")
        ).hexdigest()
        manifest = {
            "canonical_run_id": run_id,
            "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
            "as_of": as_of_dt.isoformat(),
            "idempotency_key": idempotency_key,
            "requested_domains": list(requested),
            "input_normalized_runs": sorted(
                f"{run['normalization_run_id']}:{run['normalized_manifest_hash']}"
                for runs in eligible.values()
                for run in runs
            ),
            "input_set_hash": self._input_set_hash(),
            "identity_dataset_hash": bridge.dataset_hash,
            "availability_policy_version": _availability.availability_policy_version(),
            "availability_policy_hash": _availability.availability_policy_hash(),
            "source_policy_version": _source_policy.source_policy_version(),
            "source_policy_hash": _source_policy.source_policy_hash(),
            "tolerance_policy_version": tolerance_version,
            "tolerance_policy_hash": tolerance_hash,
            "code_fingerprint": fingerprint,
            "artifacts": artifacts,
            "selected_semantic_hash": semantic,
            "selected_count": len(selected_rows),
            "decision_count": len(decisions),
            "finding_count": len(findings),
            "finding_set_hash": finding_seal,
            "status": status,
        }
        manifest_uri = f"{base_uri}/manifest.json"
        manifest_bytes = json.dumps(
            manifest, sort_keys=True, indent=1, ensure_ascii=False, default=str
        ).encode("utf-8")
        self._write_immutable(self.normalized_root / manifest_uri, manifest_bytes, run_id)
        return manifest_uri, hashlib.sha256(manifest_bytes).hexdigest(), finding_seal

    def _commit_ledger(
        self,
        *,
        run_id: str,
        as_of_dt: datetime,
        fingerprint: str,
        idempotency_key: str,
        manifest_uri: str | None,
        manifest_hash: str | None,
        selected_count: int,
        decision_count: int,
        findings: list[dict[str, Any]],
        finding_seal: str,
        status: str,
        error: str | None,
        started: datetime,
        completed: datetime,
    ) -> None:
        tolerance_version, tolerance_hash = _source_policy.tolerance_policy_identity()
        self.conn.execute("BEGIN TRANSACTION")
        try:
            dup = self.conn.execute(
                "SELECT 1 FROM meta_canonicalization_run WHERE canonical_run_id = ?",
                [run_id],
            ).fetchone()
            if dup is not None:
                msg = (
                    f"canonical run {run_id} already exists in the ledger - "
                    "conflicting duplicate execution (repair required)"
                )
                raise CanonicalRunnerError(msg)
            self.conn.execute(
                f"INSERT INTO meta_canonicalization_run ({', '.join(_LEDGER_COLUMNS)}) "
                f"VALUES ({', '.join(['?'] * len(_LEDGER_COLUMNS))})",
                [
                    run_id,
                    as_of_dt,
                    CANONICAL_CONTRACT_VERSION,
                    self._input_set_hash(),
                    self._identity_dataset_hash(),
                    _availability.availability_policy_version(),
                    _availability.availability_policy_hash(),
                    _source_policy.source_policy_version(),
                    _source_policy.source_policy_hash(),
                    tolerance_version,
                    tolerance_hash,
                    fingerprint,
                    manifest_uri,
                    manifest_hash,
                    selected_count,
                    decision_count,
                    len(findings),
                    status,
                    error,
                    idempotency_key,
                    False,
                    started,
                    completed,
                    finding_seal,
                ],
            )
            for finding in findings:
                self.conn.execute(
                    f"INSERT INTO meta_canonical_reconciliation_finding "
                    f"({', '.join(_FINDING_COLUMNS)}) VALUES "
                    f"({', '.join(['?'] * len(_FINDING_COLUMNS))})",
                    [
                        finding["finding_id"],
                        run_id,
                        finding["canonical_domain"],
                        finding["canonical_key"],
                        finding["finding_class"],
                        finding["provider"],
                        finding["source_normalization_run_id"],
                        finding["detail_json"],
                        bool(finding["blocking"]),
                        finding["created_at"],
                    ],
                )
            persisted = self.conn.execute(
                "SELECT count(*) FROM meta_canonical_reconciliation_finding "
                "WHERE canonical_run_id = ?",
                [run_id],
            ).fetchone()
            persisted_count = int(persisted[0]) if persisted is not None else -1
            if persisted_count != len(findings):
                msg = (
                    f"canonical finding set persistence mismatch for run {run_id}: "
                    f"expected {len(findings)}, persisted {persisted_count}"
                )
                raise CanonicalRunnerError(msg)
            self.conn.execute("COMMIT")
        except Exception as exc:
            import contextlib

            with contextlib.suppress(Exception):
                self.conn.execute("ROLLBACK")
            if isinstance(exc, CanonicalRunnerError):
                raise
            msg = f"canonical ledger commit failed for run {run_id}: {exc}"
            raise CanonicalRunnerError(msg) from exc

    @staticmethod
    def _write_immutable(path: Path, data: bytes, run_id: str) -> None:
        from ashare_state.storage.atomic_files import write_file_atomic

        if path.exists():
            if path.read_bytes() == data:
                return
            msg = (
                f"canonical artifact conflict at {path}: the file exists with "
                f"different bytes (run {run_id}) - canonical artifacts are immutable"
            )
            raise CanonicalRunnerError(msg)
        write_file_atomic(path, data)
