"""Provider-Normalized -> Canonical runtime (CR-3 / CR-3.1, audit 20260901).

The ONE formal canonical boundary::

    ONE authoritative CanonicalInputSnapshot (resolved ONCE per run:
      requested domain exact set + verified CR-2 source runs + verified
      identity master runs + policy identities + code fingerprint)
        -> read-only closure verification (verify_normalized_run)
        -> anchored availability evidence verification (raw meta bytes
           == sealed raw_evidence_hash == meta_raw_evidence_anchor)
        -> governed identity bridge (security_master -> security_id)
        -> typed availability derivation + as_of filter (BEFORE
           selection) + per-domain availability completeness
        -> source selection / EXACT reconciliation per static versioned
           SourcePolicy (no caller injection)
        -> immutable canonical artifacts (selected/decisions/findings
           parquet - deterministic bytes, NO wall-clock - + manifest
           LAST) + canonicalization ledger row committed in ONE DuckDB
           transaction with count assertions

CR-3.1 closures (audit 20260901 "CR-3复审与CR-3.1...收口要求"):

- P0-01 the REQUESTED DOMAIN SET (deduped, sorted) enters the canonical
  run identity; the ledger and manifest seal it explicitly. Requesting
  daily_bar can never replay a trade_calendar run's artifacts;
- P0-02 availability completeness is machine-judged per domain: zero
  PIT-available candidates while eligible verified runs exist is
  REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF (blocking) - future-only data can
  never make a historical canonical world look "successfully empty";
- P0-03 the run identity, the consumed candidates, the manifest AND
  the ledger all derive from ONE immutable snapshot resolved before any
  authoritative broad read is repeated - a mid-run normalization-run
  insertion cannot leak into the current run (only the NEXT invocation
  sees it, producing a new run identity);
- P0-04 the availability moment is only read from raw meta bytes whose
  exact SHA-256 equals BOTH the normalization run's sealed
  raw_evidence_hash AND the authoritative meta_raw_evidence_anchor
  entry (identity cross-bound) - a post-normalization received_at edit
  can never move future data into historical availability;
- P0-05 exactly ONE identity binding semantics
  (identity_dataset_hash = hash(master input set + bridge policy
  version + bridge policy hash)) feeds the run identity, the manifest
  and the ledger;
- P0-06 the source policy hash covers EVERY semantic field of every
  policy entry (asdict + canonical JSON) - no forgotten field can keep
  a stale hash;
- P0-07 the replay consumes the FULL seal: CURRENT snapshot identities
  == ledger == manifest == replay-time physical recompute (selected /
  decisions / findings semantics, artifact exact set, deterministic
  URIs, schemas, row counts) AND re-verifies every sealed CR-2 source
  run closure + its anchored availability evidence;
- P0-08 the deterministic correctness artifacts carry NO wall-clock
  (findings.parquet has no created_at) so a DB-commit failure recovers
  on the exact retry with byte-identical files;
- P1 identity findings report their TRUE domain; naive datetimes are
  rejected (naive strings are parsed under the documented fixed-UTC
  rule); the domain matrix counts 13 domains (5/2/6).
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
from ashare_state.canonical import identity as _identity
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
    "CanonicalInputSnapshot",
    "CanonicalRunner",
    "CanonicalRunnerError",
    "CanonicalRunResult",
    "canonical_code_fingerprint",
]


class CanonicalRunnerError(RuntimeError):
    """The canonical boundary contract was violated (damaged prior run,
    identity dataset corruption, unreadable verified artifacts, naive
    as_of, unknown domain)."""


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
    # migration 019 (CR-3.1)
    "requested_domains_json",
    "requested_domains_hash",
    "selected_semantic_hash",
    "decision_set_hash",
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

#: semantic fields of a finding entering the exact-set seal (the DB-side
#: created_at is transaction-time audit metadata ONLY - never part of
#: the deterministic correctness bytes)
_FINDING_SEMANTIC_FIELDS = (
    "canonical_domain",
    "canonical_key",
    "finding_class",
    "provider",
    "source_normalization_run_id",
    "detail_json",
    "blocking",
)

#: the exact artifact set of every canonical run
_ARTIFACT_NAMES = ("selected", "decisions", "findings")

#: identity fields of a manifest input entry (CR-3.1 P0-07: the replay
#: re-verifies every sealed CR-2 source run + its anchored evidence)
_INPUT_ENTRY_FIELDS = (
    "run_id",
    "role",
    "provider",
    "normalization_surface",
    "provider_dataset",
    "endpoint",
    "raw_request_id",
    "raw_evidence_uri",
    "raw_evidence_hash",
    "normalized_manifest_hash",
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
    import ashare_state.canonical.availability as _availability_module
    import ashare_state.canonical.canonicalizer as _canonicalizer
    import ashare_state.canonical.eligibility as _eligibility
    import ashare_state.canonical.identity as _identity_module
    import ashare_state.canonical.source_policy as _source_policy_module

    digest = hashlib.sha256()
    for module in (
        _canonicalizer,
        _eligibility,
        _availability_module,
        _identity_module,
        _source_policy_module,
    ):
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


def _rows_semantic_hash(rows: list[dict[str, Any]]) -> str:
    """Deterministic semantic identity of artifact rows (sorted canonical
    JSON) - the replay-time physical recompute seal basis."""
    return hashlib.sha256(
        _canonical_json(sorted(_canonical_json(r) for r in rows)).encode("utf-8")
    ).hexdigest()


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


def _parse_as_of(as_of: datetime | str) -> datetime:
    """CR-3.1 P1 (audit section 9.3): as_of parsing is deterministic
    across platforms. Naive datetimes are REJECTED (their local-time
    interpretation depends on the host); naive strings are parsed under
    the documented FIXED-UTC rule."""
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None:
            msg = (
                "as_of datetime must be timezone-aware - a naive datetime's "
                "interpretation depends on the host local timezone "
                "(CR-3.1 audit 20260901 section 9.3)"
            )
            raise CanonicalRunnerError(msg)
        return as_of.astimezone(UTC)
    text = str(as_of)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)  # fixed documented rule: naive = UTC
    return parsed.astimezone(UTC)


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


def _input_entry(run_row: dict[str, Any], role: str) -> dict[str, str]:
    return {
        "run_id": str(run_row["normalization_run_id"]),
        "role": role,
        "provider": str(run_row["provider"]),
        "normalization_surface": str(run_row["normalization_surface"]),
        "provider_dataset": str(run_row["provider_dataset"]),
        "endpoint": str(run_row["endpoint"]),
        "raw_request_id": str(run_row["raw_request_id"]),
        "raw_evidence_uri": str(run_row["raw_evidence_uri"]),
        "raw_evidence_hash": str(run_row["raw_evidence_hash"]),
        "normalized_manifest_hash": str(run_row["normalized_manifest_hash"]),
    }


@dataclass(frozen=True)
class CanonicalInputSnapshot:
    """CR-3.1 P0-03 (audit section 3): the ONE immutable authoritative
    input world of a canonical run, resolved ONCE before anything else.
    The run identity, the consumed candidates, the manifest and the
    ledger ALL derive from this object - never from a re-executed broad
    query against the moving current DB.

    ``entries`` is the DISCOVERED input set (every SUCCESS CR-2 run on
    the relevant surfaces - including any run found DAMAGED during
    verification, which yields a blocking prefinding). Keeping damaged
    runs inside the input identity is what makes a post-success tamper
    surface as a DAMAGED replay instead of silently minting a new run
    identity."""

    as_of: datetime
    requested_domains: tuple[str, ...]
    source_runs: dict[str, tuple[dict[str, Any], ...]]
    master_rows: tuple[dict[str, Any], ...]
    prefindings: tuple[dict[str, Any], ...]
    entries: tuple[dict[str, str], ...]
    input_set_hash: str
    master_input_set_hash: str
    identity_dataset_hash: str
    availability_policy_version: str
    availability_policy_hash: str
    source_policy_version: str
    source_policy_hash: str
    tolerance_policy_version: str
    tolerance_policy_hash: str
    code_fingerprint: str

    @property
    def requested_domains_json(self) -> str:
        return json.dumps(list(self.requested_domains), separators=(",", ":"))

    @property
    def requested_domains_hash(self) -> str:
        return hashlib.sha256(self.requested_domains_json.encode("utf-8")).hexdigest()

    def run_identity(self) -> str:
        """The deterministic idempotency key: exact input set + requested
        domain set + as_of + contract + identity/policy identities +
        code fingerprint. Any change yields a NEW run (history
        preserved)."""
        return hashlib.sha256(
            "|".join(
                (
                    self.requested_domains_hash,
                    self.input_set_hash,
                    self.identity_dataset_hash,
                    self.as_of.isoformat(),
                    CANONICAL_CONTRACT_VERSION,
                    self.availability_policy_version,
                    self.availability_policy_hash,
                    self.source_policy_version,
                    self.source_policy_hash,
                    self.tolerance_policy_version,
                    self.tolerance_policy_hash,
                    self.code_fingerprint,
                )
            ).encode("utf-8")
        ).hexdigest()

    def input_entries(self) -> list[dict[str, str]]:
        return list(self.entries)


class CanonicalRunner:
    """The formal canonical runtime. Inputs are the CR-2 ledger +
    verified artifacts ONLY - there is no provider/SDK access, no
    caller-supplied candidates, and no correctness-policy parameter
    anywhere in the API (``run(as_of, domains=...)`` - as_of is the PIT
    query point, domains selects WHICH governed domains to build; both
    are part of the run identity)."""

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
        as_of_dt = _parse_as_of(as_of)
        requested = tuple(sorted(set(domains))) if domains else supported_domains()
        for domain in requested:
            spec = domain_spec(domain)
            if spec.eligibility is not DomainEligibility.CANONICAL_SUPPORTED:
                msg = (
                    f"canonical domain {domain!r} is {spec.eligibility.value} - "
                    "it can never produce canonical rows (no silent skip)"
                )
                raise CanonicalRunnerError(msg)
        self._assert_policy_honestly_consumed()

        # ------------------------ ONE authoritative snapshot (P0-03)
        snapshot = self._build_snapshot(as_of_dt, requested)

        # ------------------------ exact replay lookup (history-wide)
        idempotency_key = snapshot.run_identity()
        run_id = str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))
        prior = self.conn.execute(
            "SELECT canonical_run_id FROM meta_canonicalization_run WHERE canonical_run_id = ?",
            [run_id],
        ).fetchone()
        if prior is not None:
            return self._require_verified_replay(run_id, idempotency_key, snapshot)

        findings: list[dict[str, Any]] = list(snapshot.prefindings)
        bridge = IdentityBridge(
            list(snapshot.master_rows), master_input_set_hash=snapshot.master_input_set_hash
        )

        # ------------------------------------------ candidates per domain
        selected_rows: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        identity_missing_by_domain: dict[str, int] = {}

        for domain in requested:
            policy = _source_policy.source_policy_for(domain)
            candidates: list[dict[str, Any]] = []
            for run_row in snapshot.source_runs.get(domain, ()):
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
            # ---- availability completeness (CR-3.1 P0-02): eligible
            # verified runs existing while ZERO candidates are
            # PIT-available is a blocking failure - future-only data
            # must never make a historical world "successfully empty"
            if not snapshot.source_runs.get(domain):
                findings.append(
                    self._finding(
                        domain,
                        "",
                        "REQUIRED_DOMAIN_MISSING",
                        None,
                        None,
                        {"reason": "no eligible verified CR-2 run for this domain"},
                        blocking=True,
                    )
                )
            elif not available:
                findings.append(
                    self._finding(
                        domain,
                        "",
                        "REQUIRED_DOMAIN_UNAVAILABLE_AT_ASOF",
                        None,
                        None,
                        {
                            "reason": (
                                "eligible verified runs exist but zero candidates "
                                "are PIT-available at this as_of"
                            )
                        },
                        blocking=True,
                    )
                )
            identity_missing_by_domain[domain] = sum(
                1 for c in available if c["identity_status"] == "MISSING"
            )
            rows, domain_decisions, domain_findings = self._select(domain, policy, available)
            selected_rows.extend(rows)
            decisions.extend(domain_decisions)
            findings.extend(domain_findings)

        # ---- truthful per-domain identity findings (CR-3.1 P1-9.1)
        for domain, missing in identity_missing_by_domain.items():
            if missing <= 0:
                continue
            policy = _source_policy.source_policy_for(domain)
            findings.append(
                self._finding(
                    domain,
                    "",
                    "IDENTITY_MISSING",
                    None,
                    None,
                    {
                        "count": missing,
                        "identity_missing_max": policy.identity_missing_max,
                        "reason": (
                            "provider symbols without a governed security_master "
                            "identity entry were EXCLUDED (never a bare-symbol "
                            "canonical key fallback)"
                        ),
                    },
                    blocking=missing > policy.identity_missing_max,
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
        manifest_uri, manifest_hash, finding_seal, selected_semantic, decision_set = (
            self._write_artifacts(
                run_id=run_id,
                snapshot=snapshot,
                idempotency_key=idempotency_key,
                selected_rows=selected_rows,
                decisions=decisions,
                findings=findings,
                status=status,
            )
        )
        completed = datetime.now(UTC)
        self._commit_ledger(
            run_id=run_id,
            snapshot=snapshot,
            idempotency_key=idempotency_key,
            manifest_uri=manifest_uri,
            manifest_hash=manifest_hash,
            selected_count=len(selected_rows),
            decision_count=len(decisions),
            selected_semantic=selected_semantic,
            decision_set=decision_set,
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
            domains=snapshot.requested_domains,
            finding_set_hash=finding_seal,
            error_message=error,
        )

    # -------------------------------------------------------- snapshot
    def _build_snapshot(
        self, as_of_dt: datetime, requested: tuple[str, ...]
    ) -> CanonicalInputSnapshot:
        """Resolve the ONE authoritative input world (every broad query
        happens exactly HERE). Tests may wrap this method to simulate a
        mid-run insertion race - production never exposes such a hook."""
        source_runs: dict[str, list[dict[str, Any]]] = {}
        prefindings: list[dict[str, Any]] = []
        discovered: list[dict[str, str]] = []
        for domain in requested:
            spec = domain_spec(domain)
            for run_row in self._surface_runs(spec.normalization_surface, spec.provider_datasets):
                # the DISCOVERED input set includes every SUCCESS run -
                # even one found DAMAGED below (its blocking prefinding
                # is the honest record). Keeping damaged runs inside the
                # input identity makes a post-success tamper surface as
                # a DAMAGED replay instead of minting a new run identity.
                discovered.append(_input_entry(run_row, "source"))
                closure_problems = verify_normalized_run(
                    self.conn,
                    run_row["normalization_run_id"],
                    raw_root=self.raw_root,
                    normalized_root=self.normalized_root,
                )
                anchor_problems, received_at = self._verify_anchored_availability(run_row)
                if closure_problems:
                    prefindings.append(
                        self._finding(
                            domain,
                            "",
                            "CLOSURE_VERIFICATION_FAILED",
                            run_row["provider"],
                            run_row["normalization_run_id"],
                            {"problems": closure_problems},
                            blocking=True,
                        )
                    )
                if anchor_problems:
                    prefindings.append(
                        self._finding(
                            domain,
                            "",
                            "AVAILABILITY_EVIDENCE_INVALID",
                            run_row["provider"],
                            run_row["normalization_run_id"],
                            {"problems": anchor_problems},
                            blocking=True,
                        )
                    )
                if closure_problems or anchor_problems:
                    continue
                run_row["received_at"] = received_at
                source_runs.setdefault(domain, []).append(run_row)
        # identity master dataset (auxiliary; always resolved)
        verified_master_rows: list[dict[str, Any]] = []
        for run_row in self._surface_runs(
            "security_master", ("code_list", "hist_code_list", "stock_basic")
        ):
            discovered.append(_input_entry(run_row, "identity_master"))
            problems = verify_normalized_run(
                self.conn,
                run_row["normalization_run_id"],
                raw_root=self.raw_root,
                normalized_root=self.normalized_root,
            )
            if problems:
                prefindings.append(
                    self._finding(
                        "security_master",
                        "",
                        "CLOSURE_VERIFICATION_FAILED",
                        run_row["provider"],
                        run_row["normalization_run_id"],
                        {"problems": problems},
                        blocking=True,
                    )
                )
                continue
            verified_master_rows.extend(
                self._read_output_rows(run_row["normalization_run_id"], "main")
            )
        frozen_source_runs = {domain: tuple(runs) for domain, runs in sorted(source_runs.items())}
        master_entries = [e for e in discovered if e["role"] == "identity_master"]
        master_input_set_hash = hashlib.sha256(
            "|".join(
                sorted(f"{e['run_id']}:{e['normalized_manifest_hash']}" for e in master_entries)
            ).encode("utf-8")
        ).hexdigest()
        entries = tuple(sorted(discovered, key=_canonical_json))
        input_set_hash = hashlib.sha256(_canonical_json(list(entries)).encode("utf-8")).hexdigest()
        tolerance_version, tolerance_hash = _source_policy.tolerance_policy_identity()
        return CanonicalInputSnapshot(
            as_of=as_of_dt,
            requested_domains=requested,
            source_runs=frozen_source_runs,
            master_rows=tuple(verified_master_rows),
            prefindings=tuple(prefindings),
            entries=entries,
            input_set_hash=input_set_hash,
            master_input_set_hash=master_input_set_hash,
            identity_dataset_hash=_identity.identity_dataset_hash(master_input_set_hash),
            availability_policy_version=_availability.availability_policy_version(),
            availability_policy_hash=_availability.availability_policy_hash(),
            source_policy_version=_source_policy.source_policy_version(),
            source_policy_hash=_source_policy.source_policy_hash(),
            tolerance_policy_version=tolerance_version,
            tolerance_policy_hash=tolerance_hash,
            code_fingerprint=canonical_code_fingerprint(),
        )

    def _verify_run_intact(self, run_row: dict[str, Any]) -> list[str]:
        """CR-2 closure verification + CR-3.1 P0-04 anchored
        availability evidence (replay-side reuse)."""
        problems = verify_normalized_run(
            self.conn,
            run_row["normalization_run_id"],
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        anchor_problems, _ = self._verify_anchored_availability(run_row)
        return problems + anchor_problems

    def _verify_anchored_availability(
        self, run_row: dict[str, Any]
    ) -> tuple[list[str], datetime | None]:
        """CR-3.1 P0-04: the availability moment may ONLY be read from
        raw meta bytes whose exact SHA-256 equals BOTH the
        normalization run's sealed raw_evidence_hash AND the
        authoritative meta_raw_evidence_anchor entry (identity
        cross-bound). Returns (problems, received_at|None)."""
        from ashare_state.storage.raw_anchor import lookup_raw_evidence_anchor

        problems: list[str] = []
        meta_path = self.raw_root / str(run_row["raw_evidence_uri"])
        if not meta_path.is_file():
            return [f"raw evidence meta missing: {run_row['raw_evidence_uri']}"], None
        meta_bytes = meta_path.read_bytes()
        current_hash = hashlib.sha256(meta_bytes).hexdigest()
        if current_hash != str(run_row["raw_evidence_hash"]):
            return (
                [
                    "raw meta bytes no longer match the normalization run's "
                    "sealed raw_evidence_hash (post-normalization tamper)"
                ],
                None,
            )
        anchor = lookup_raw_evidence_anchor(
            self.conn,
            provider=str(run_row["provider"]),
            provider_dataset=str(run_row["provider_dataset"]),
            request_id=str(run_row["raw_request_id"]),
        )
        if anchor is None:
            return ["no meta_raw_evidence_anchor row for this raw evidence"], None
        if anchor.evidence_hash != current_hash:
            return ["raw evidence anchor hash mismatch"], None
        try:
            doc = json.loads(meta_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return [f"raw meta unreadable: {exc}"], None
        # identity cross-binding: anchor == run == meta
        for field, expected in (
            ("evidence_uri", str(run_row["raw_evidence_uri"])),
            ("provider", str(run_row["provider"])),
            ("provider_dataset", str(run_row["provider_dataset"])),
            ("normalization_surface", str(run_row["normalization_surface"])),
            ("endpoint", str(run_row["endpoint"])),
        ):
            anchor_value = str(getattr(anchor, field))
            if anchor_value != expected:
                problems.append(f"anchor {field} {anchor_value!r} != run {expected!r}")
        for meta_field, expected in (
            ("provider", str(run_row["provider"])),
            ("provider_dataset", str(run_row["provider_dataset"])),
            ("request_id", str(run_row["raw_request_id"])),
            ("endpoint", str(run_row["endpoint"])),
            ("normalization_surface", str(run_row["normalization_surface"])),
            ("operation_id", str(anchor.operation_id)),
        ):
            if str(doc.get(meta_field, "")) != expected:
                problems.append(f"raw meta {meta_field} does not match the sealed identity")
        if problems:
            return problems, None
        return [], _parse_ts(doc["received_at"])

    def _assert_policy_honestly_consumed(self) -> None:
        """CR-3.1 P0-06: the runtime must HONESTLY consume the declared
        policy fields - v1 supports no fallback providers and no
        partial-run consumption; declaring either without runtime
        support fails loudly instead of silently ignoring the field."""
        for policy in _source_policy.source_policies():
            if policy.allowed_fallback_providers:
                msg = (
                    f"source policy for {policy.domain} declares fallback providers "
                    "but the runtime implements no fallback selection path - "
                    "bump the policy with runtime support, never silently ignore it"
                )
                raise CanonicalRunnerError(msg)
            if policy.partial_run_allowed:
                msg = (
                    f"source policy for {policy.domain} allows PARTIAL CR-2 runs "
                    "but the runtime consumes SUCCESS runs only - bump the "
                    "policy with runtime support, never silently ignore it"
                )
                raise CanonicalRunnerError(msg)

    # ------------------------------------------------------------- inputs
    def _surface_runs(
        self, normalization_surface: str, provider_datasets: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT normalization_run_id, provider, normalization_surface, "
            "provider_dataset, endpoint, raw_request_id, raw_evidence_uri, "
            "raw_evidence_hash, normalization_contract_version, mapper_identity, "
            "normalized_manifest_uri, normalized_manifest_hash, status "
            "FROM meta_provider_normalization_run "
            "WHERE provider = 'amazingdata' AND normalization_surface = ? "
            "AND provider_dataset IN (" + ",".join("?" * len(provider_datasets)) + ") "
            "AND status = 'SUCCESS' ORDER BY normalization_run_id",
            [normalization_surface, *provider_datasets],
        ).fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            result.append(
                {
                    "normalization_run_id": str(r[0]),
                    "provider": str(r[1]),
                    "normalization_surface": str(r[2]),
                    "provider_dataset": str(r[3]),
                    "endpoint": str(r[4]),
                    "raw_request_id": str(r[5]),
                    "raw_evidence_uri": str(r[6]),
                    "raw_evidence_hash": str(r[7]),
                    "normalization_contract_version": str(r[8]),
                    "mapper_identity": str(r[9]),
                    "normalized_manifest_uri": str(r[10]),
                    "normalized_manifest_hash": str(r[11]),
                    "status": str(r[12]),
                }
            )
        return result

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

    # --------------------------------------------------------- candidates
    def _build_candidates(
        self, domain: str, run_row: dict[str, Any], bridge: IdentityBridge
    ) -> list[dict[str, Any]]:
        """Deterministic candidates from ONE verified snapshot run row:
        each row of the domain's output table with its availability
        (the anchored received_at resolved during the snapshot), identity
        and lineage. Availability is attached but NOT filtered here -
        the filter runs before selection."""
        spec = domain_spec(domain)
        received_at = run_row["received_at"]
        available_at = derive_available_at(domain, received_at)
        rows = self._read_output_rows(run_row["normalization_run_id"], spec.output_name)
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
    def _read_manifest(self, run_row: dict[str, Any]) -> dict[str, Any]:
        path = self.normalized_root / str(run_row["normalized_manifest_uri"])
        return json.loads(path.read_text(encoding="utf-8"))

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
        if domain in ("security_status", "limit_price"):
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
    def _require_verified_replay(
        self, run_id: str, idempotency_key: str, snapshot: CanonicalInputSnapshot
    ) -> CanonicalRunResult:
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
        problems = self._verify_closure(record, snapshot)
        if problems:
            msg = (
                f"existing canonical run {run_id} is DAMAGED - idempotent replay "
                f"refused, repair required: {'; '.join(problems)}"
            )
            raise CanonicalRunnerError(msg)
        domains = tuple(json.loads(str(record["requested_domains_json"])))
        return CanonicalRunResult(
            canonical_run_id=str(record["canonical_run_id"]),
            as_of=_ledger_as_of(record).isoformat(),
            status=str(record["status"]),
            selected_count=int(record["selected_count"]),
            decision_count=int(record["decision_count"]),
            finding_count=int(record["finding_count"]),
            manifest_uri=str(record["manifest_uri"]) if record["manifest_uri"] else None,
            manifest_hash=str(record["manifest_hash"]) if record["manifest_hash"] else None,
            idempotent_replay=True,
            domains=domains,
            finding_set_hash=str(record["finding_set_hash"])
            if record["finding_set_hash"]
            else None,
            error_message=str(record["error_message"]) if record["error_message"] else None,
        )

    def _verify_closure(
        self, record: dict[str, Any], snapshot: CanonicalInputSnapshot
    ) -> list[str]:
        """CR-3.1 P0-07: the FULL seal is consumed on every replay -
        CURRENT snapshot identities == ledger == manifest == replay-time
        physical recompute, plus re-verification of every sealed CR-2
        source run closure and its anchored availability evidence."""
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

        # ---- CURRENT provenance == ledger (defense in depth on top of
        # the exact idempotency key - catches ledger tampering)
        expected_provenance = (
            ("requested_domains_json", snapshot.requested_domains_json),
            ("requested_domains_hash", snapshot.requested_domains_hash),
            ("input_set_hash", snapshot.input_set_hash),
            ("identity_dataset_hash", snapshot.identity_dataset_hash),
            ("availability_policy_version", snapshot.availability_policy_version),
            ("availability_policy_hash", snapshot.availability_policy_hash),
            ("source_policy_version", snapshot.source_policy_version),
            ("source_policy_hash", snapshot.source_policy_hash),
            ("tolerance_policy_version", snapshot.tolerance_policy_version),
            ("tolerance_policy_hash", snapshot.tolerance_policy_hash),
            ("code_fingerprint", snapshot.code_fingerprint),
        )
        for field, expected in expected_provenance:
            if str(record.get(field)) != expected:
                problems.append(f"ledger {field} does not match the current provenance")

        # ---- ledger == manifest (typed seal, field by field)
        expected_manifest = (
            ("canonical_run_id", str(record["canonical_run_id"])),
            ("canonical_contract_version", str(record["canonical_contract_version"])),
            ("as_of", _ledger_as_of(record).isoformat()),
            ("idempotency_key", str(record["idempotency_key"])),
            ("status", str(record["status"])),
            ("input_set_hash", str(record["input_set_hash"])),
            ("identity_dataset_hash", str(record["identity_dataset_hash"])),
            ("availability_policy_version", str(record["availability_policy_version"])),
            ("availability_policy_hash", str(record["availability_policy_hash"])),
            ("source_policy_version", str(record["source_policy_version"])),
            ("source_policy_hash", str(record["source_policy_hash"])),
            ("tolerance_policy_version", str(record["tolerance_policy_version"])),
            ("tolerance_policy_hash", str(record["tolerance_policy_hash"])),
            ("code_fingerprint", str(record["code_fingerprint"])),
            ("requested_domains_hash", str(record["requested_domains_hash"])),
            ("selected_semantic_hash", str(record["selected_semantic_hash"])),
            ("decision_set_hash", str(record["decision_set_hash"])),
            ("finding_set_hash", str(record["finding_set_hash"])),
        )
        for field, expected in expected_manifest:
            if str(manifest.get(field)) != expected:
                problems.append(f"manifest field {field} does not match the ledger seal")
        manifest_domains = manifest.get("requested_domains")
        if list(manifest_domains or []) != json.loads(str(record["requested_domains_json"])):
            problems.append("manifest requested_domains does not match the ledger seal")
        if int(manifest.get("selected_count", -1)) != int(record["selected_count"]):
            problems.append("manifest selected_count does not match the ledger")
        if int(manifest.get("decision_count", -1)) != int(record["decision_count"]):
            problems.append("manifest decision_count does not match the ledger")
        if int(manifest.get("finding_count", -1)) != int(record["finding_count"]):
            problems.append("manifest finding_count does not match the ledger")

        # ---- artifact exact set + deterministic URI + physical recompute
        artifacts = manifest.get("artifacts", {})
        if set(artifacts) != set(_ARTIFACT_NAMES):
            problems.append(
                f"manifest artifact set is not exactly {sorted(_ARTIFACT_NAMES)}: "
                f"{sorted(artifacts)}"
            )
        artifact_rows: dict[str, list[dict[str, Any]]] = {}
        for name in _ARTIFACT_NAMES:
            entry = artifacts.get(name)
            if entry is None:
                continue
            expected_uri = self._expected_artifact_uri(record, name)
            if str(entry.get("uri")) != expected_uri:
                problems.append(
                    f"canonical {name} artifact uri is not the deterministic "
                    f"recompute ({entry.get('uri')!r} != {expected_uri!r})"
                )
            path = self.normalized_root / str(entry.get("uri"))
            if not path.is_file():
                problems.append(f"canonical {name} artifact missing: {entry.get('uri')}")
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != str(entry.get("content_hash")):
                problems.append(f"canonical {name} artifact bytes tampered")
                continue
            frame = pl.read_parquet(path)
            if frame.height != int(entry.get("row_count", -1)):
                problems.append(f"canonical {name} artifact row count mismatch")
            actual_schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
            if actual_schema_hash != str(entry.get("schema_hash")):
                problems.append(f"canonical {name} artifact schema mismatch (rebind)")
            artifact_rows[name] = frame.to_dicts()

        # ---- semantic seals: physical recompute == manifest == ledger
        if "selected" in artifact_rows:
            recomputed = _rows_semantic_hash(artifact_rows["selected"])
            if recomputed != str(record["selected_semantic_hash"]) or recomputed != str(
                manifest.get("selected_semantic_hash")
            ):
                problems.append("selected semantic seal mismatch (values changed)")
        if "decisions" in artifact_rows:
            recomputed = _rows_semantic_hash(artifact_rows["decisions"])
            if recomputed != str(record["decision_set_hash"]) or recomputed != str(
                manifest.get("decision_set_hash")
            ):
                problems.append("decision semantic seal mismatch (values changed)")

        # ---- findings three-way: parquet == DB == seal
        db_rows = self.conn.execute(
            "SELECT finding_id, canonical_domain, canonical_key, finding_class, "
            "provider, source_normalization_run_id, detail_json, blocking "
            "FROM meta_canonical_reconciliation_finding WHERE canonical_run_id = ? "
            "ORDER BY finding_id",
            [str(record["canonical_run_id"])],
        ).fetchall()
        if len(db_rows) != int(record["finding_count"]):
            problems.append(
                f"finding count mismatch: ledger {int(record['finding_count'])} vs {len(db_rows)}"
            )
        db_findings = [dict(zip(_FINDING_SEMANTIC_FIELDS, r[1:], strict=True)) for r in db_rows]
        db_finding_ids = [str(r[0]) for r in db_rows]
        if _finding_set_hash(db_findings) != str(record["finding_set_hash"]):
            problems.append("DB finding exact-set seal mismatch (tampered or missing rows)")
        if "findings" in artifact_rows:
            parquet_rows = artifact_rows["findings"]
            parquet_ids = sorted(str(r.get("finding_id")) for r in parquet_rows)
            if parquet_ids != sorted(db_finding_ids):
                problems.append("findings parquet ids diverge from the DB finding set")
            parquet_semantic = [
                {field: r.get(field) for field in _FINDING_SEMANTIC_FIELDS} for r in parquet_rows
            ]
            if _finding_set_hash(parquet_semantic) != str(record["finding_set_hash"]):
                problems.append("findings parquet semantic set diverges from the seal")

        # ---- re-verify every sealed CR-2 source run + anchored evidence
        for entry in manifest.get("input_normalized_runs", []):
            run_row = {
                "normalization_run_id": str(entry.get("run_id")),
                "provider": str(entry.get("provider")),
                "normalization_surface": str(entry.get("normalization_surface")),
                "provider_dataset": str(entry.get("provider_dataset")),
                "endpoint": str(entry.get("endpoint")),
                "raw_request_id": str(entry.get("raw_request_id")),
                "raw_evidence_uri": str(entry.get("raw_evidence_uri")),
                "raw_evidence_hash": str(entry.get("raw_evidence_hash")),
                "normalized_manifest_hash": str(entry.get("normalized_manifest_hash")),
            }
            entry_problems = self._verify_run_intact(run_row)
            if entry_problems:
                problems.append(
                    f"sealed CR-2 source run {run_row['normalization_run_id']} is no "
                    f"longer intact: {'; '.join(entry_problems)}"
                )
        # ---- the sealed input set == the manifest input set
        sealed_entries = manifest.get("input_normalized_runs", [])
        if _canonical_json(sorted(sealed_entries, key=_canonical_json)) != _canonical_json(
            sorted(snapshot.input_entries(), key=_canonical_json)
        ):
            problems.append("manifest input set does not match the current snapshot")
        return problems

    def _expected_artifact_uri(self, record: dict[str, Any], name: str) -> str:
        base = self._expected_base_uri(record)
        return f"{base}/{name}.parquet"

    def _expected_base_uri(self, record: dict[str, Any]) -> str:
        as_of_dt = _ledger_as_of(record)
        return (
            f"canonical/contract={record['canonical_contract_version']}/"
            f"as_of={as_of_dt.strftime('%Y%m%dT%H%M%SZ')}/"
            f"run={record['canonical_run_id']}"
        )

    # ----------------------------------------------------------- artifacts
    def _write_artifacts(
        self,
        *,
        run_id: str,
        snapshot: CanonicalInputSnapshot,
        idempotency_key: str,
        selected_rows: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        findings: list[dict[str, Any]],
        status: str,
    ) -> tuple[str | None, str | None, str, str, str]:
        """Deterministic correctness artifacts. NO wall-clock anywhere
        (CR-3.1 P0-08): findings carry NO created_at in the parquet -
        the DB-side created_at is transaction-time audit metadata bound
        only at commit - so a DB failure after the file writes recovers
        on the exact retry with byte-identical files."""
        base_uri = (
            f"canonical/contract={CANONICAL_CONTRACT_VERSION}/"
            f"as_of={snapshot.as_of.strftime('%Y%m%dT%H%M%SZ')}/run={run_id}"
        )
        base_path = self.normalized_root / base_uri
        base_path.mkdir(parents=True, exist_ok=True)

        # bind deterministic finding ids before sealing (uuid5 - no clock)
        for position, finding in enumerate(findings):
            finding["finding_id"] = f"cf-{uuid.uuid5(_FINDING_NAMESPACE, f'{run_id}:{position}')}"
            finding["canonical_run_id"] = run_id
        finding_seal = _finding_set_hash(findings)
        selected_semantic = _rows_semantic_hash(selected_rows)
        decision_set = _rows_semantic_hash(decisions)

        import io

        artifacts: dict[str, dict[str, Any]] = {}
        parquet_rows = {
            "selected": _align_schema(selected_rows),
            "decisions": _align_schema(decisions),
            # findings parquet: deterministic fields ONLY (no created_at)
            "findings": _align_schema(
                [
                    {
                        "finding_id": f["finding_id"],
                        "canonical_run_id": f["canonical_run_id"],
                        **{field: f.get(field) for field in _FINDING_SEMANTIC_FIELDS},
                    }
                    for f in findings
                ]
            ),
        }
        for name in _ARTIFACT_NAMES:
            rows = parquet_rows[name]
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

        manifest = {
            "canonical_run_id": run_id,
            "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
            "as_of": snapshot.as_of.isoformat(),
            "idempotency_key": idempotency_key,
            "requested_domains": list(snapshot.requested_domains),
            "requested_domains_hash": snapshot.requested_domains_hash,
            "input_normalized_runs": snapshot.input_entries(),
            "input_set_hash": snapshot.input_set_hash,
            "identity_master_input_set_hash": snapshot.master_input_set_hash,
            "identity_bridge_policy_version": _identity.identity_bridge_policy_version(),
            "identity_bridge_policy_hash": _identity.identity_bridge_policy_hash(),
            "identity_dataset_hash": snapshot.identity_dataset_hash,
            "availability_policy_version": snapshot.availability_policy_version,
            "availability_policy_hash": snapshot.availability_policy_hash,
            "source_policy_version": snapshot.source_policy_version,
            "source_policy_hash": snapshot.source_policy_hash,
            "tolerance_policy_version": snapshot.tolerance_policy_version,
            "tolerance_policy_hash": snapshot.tolerance_policy_hash,
            "required_evidence_classes": {
                p.domain: p.required_evidence_class for p in _source_policy.source_policies()
            },
            "code_fingerprint": snapshot.code_fingerprint,
            "artifacts": artifacts,
            "selected_semantic_hash": selected_semantic,
            "decision_set_hash": decision_set,
            "finding_set_hash": finding_seal,
            "selected_count": len(selected_rows),
            "decision_count": len(decisions),
            "finding_count": len(findings),
            "status": status,
        }
        manifest_uri = f"{base_uri}/manifest.json"
        manifest_bytes = json.dumps(
            manifest, sort_keys=True, indent=1, ensure_ascii=False, default=str
        ).encode("utf-8")
        self._write_immutable(self.normalized_root / manifest_uri, manifest_bytes, run_id)
        return (
            manifest_uri,
            hashlib.sha256(manifest_bytes).hexdigest(),
            finding_seal,
            selected_semantic,
            decision_set,
        )

    def _commit_ledger(
        self,
        *,
        run_id: str,
        snapshot: CanonicalInputSnapshot,
        idempotency_key: str,
        manifest_uri: str | None,
        manifest_hash: str | None,
        selected_count: int,
        decision_count: int,
        selected_semantic: str,
        decision_set: str,
        findings: list[dict[str, Any]],
        finding_seal: str,
        status: str,
        error: str | None,
        started: datetime,
        completed: datetime,
    ) -> None:
        """One DuckDB transaction: dup check + run INSERT + full finding
        set + count assertion. A failure rolls everything back; the
        deterministic file-side anchor lets the exact retry recover
        (byte-identical no-op writes, then the ledger commit)."""
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
                    snapshot.as_of,
                    CANONICAL_CONTRACT_VERSION,
                    snapshot.input_set_hash,
                    snapshot.identity_dataset_hash,
                    snapshot.availability_policy_version,
                    snapshot.availability_policy_hash,
                    snapshot.source_policy_version,
                    snapshot.source_policy_hash,
                    snapshot.tolerance_policy_version,
                    snapshot.tolerance_policy_hash,
                    snapshot.code_fingerprint,
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
                    snapshot.requested_domains_json,
                    snapshot.requested_domains_hash,
                    selected_semantic,
                    decision_set,
                ],
            )
            # transaction-time audit metadata ONLY (never part of the
            # deterministic correctness bytes - CR-3.1 P0-08)
            now = datetime.now(UTC)
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
                        now,
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


def _ledger_as_of(record: dict[str, Any]) -> datetime:
    value = record["as_of"]
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return _parse_ts(value)
