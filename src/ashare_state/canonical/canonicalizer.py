"""Provider-Normalized -> Canonical runtime (CR-3 / CR-3.1 / CR-3.2, audit 20260901).

The ONE formal canonical boundary::

    ONE TRANSACTIONAL Materialized Canonical Input Snapshot:
      BEGIN (MVCC snapshot boundary BEFORE the first authoritative
      broad read) -> discover source + identity-master runs (each
      underlying SURFACE queried exactly once) -> closure verification
      (verify_normalized_run) + anchored availability evidence (raw
      meta bytes == sealed hash == anchor) -> materialize the EXACT
      SEALED output bytes (read -> hash-verify -> parse the SAME
      bytes) -> COMMIT
        -> governed identity bridge (PIT-available security_master ->
           security_id; future masters are discovery evidence but never
           resolve historical identities)
        -> typed availability derivation + as_of filter (BEFORE
           selection) + per-domain availability completeness
        -> source selection / EXACT reconciliation per static versioned
           SourcePolicy (honestly executed: unsupported declared values
           fail closed before any run)
        -> immutable canonical artifacts (selected/decisions/findings
           parquet - deterministic bytes, NO wall-clock - + manifest
           LAST) + canonicalization ledger row committed in ONE DuckDB
           transaction with count assertions

CR-3.2 closures (audit 20260901 "CR-3.1复审与CR-3.2最终TransactionalSnapshot
及PolicyExecution收口要求"):

- P0-01 the snapshot carries a REAL DB snapshot boundary (BEGIN before
  the first broad SELECT; surfaces queried once and deduplicated), the
  consumed rows are MATERIALIZED from the exact verified bytes inside
  that boundary, and no post-snapshot current-ledger/current-path
  reread can change the consumed truth; snapshot records are DEEPLY
  immutable typed dataclasses (frozen findings, tuple-frozen rows);
- P0-02 the identity master obeys the SAME PIT/anchored-evidence rules
  as market sources (anchor-verified received_at <= as_of before a
  master may enter the bridge; future masters stay discovery
  evidence; first-run and replay verification are symmetric) with
  typed findings IDENTITY_DATASET_MISSING /
  IDENTITY_DATASET_UNAVAILABLE_AT_ASOF / IDENTITY_EVIDENCE_INVALID;
- P0-03 the runtime HONESTLY executes the declared policy: every
  semantic field is guarded against unsupported values (evidence class,
  reconciliation, tolerance id/version, conflict action, fallback,
  partial) - declaring an unimplemented value fails closed before any
  canonical run instead of silently keeping old behavior under a new
  hash;
- P0-04 the full seal is typed and consumed: the manifest input
  entries carry the COMPLETE CR-2 seal per run (contract version,
  mapper identity + code hash, manifest + output-set + semantic seals,
  status, raw identity), the manifest URI itself is deterministically
  verified, and every explicit manifest provenance field
  (identity_master_input_set_hash / bridge policy version+hash /
  required_evidence_classes) is compared three-way against ledger and
  CURRENT values on replay;
- P0-05 the run identity is base identity (the input world) + a
  verification-state hash: an exact upstream repair yields a NEW
  deterministic run (never replaying a stale BLOCKED run), while a
  prior SUCCESS degraded by damage is refused (DAMAGED) and never
  silently replaced; repairs never overwrite historical BLOCKED
  evidence;
- P1 the snapshot is deeply immutable; ``domains=[]`` is rejected
  explicitly (None = all supported domains).

CR-3.4 closures (audit 20260902 "CR-3.3复审与CR-3.4最终ContinuitySeal
及VerificationReplay收口要求"):

- P0-01 the historical continuity guard verifies a typed HISTORICAL
  CANONICAL RUN SEAL (ledger == manifest explicit correctness fields ==
  physical recompute of input_seal_hash / input_set_hash /
  verification_state_hash over the manifest input entries) BEFORE
  trusting a prior manifest's input list - a canonical manifest +
  ledger outer-hash rebind can never launder a consumed input out of
  continuity evidence, and a prior manifest/ledger that fails the seal
  is itself HARD DAMAGED (no replacement of any kind may be minted);
- P0-02 first consume and replay share ONE verification evidence
  collector (``_collect_input_verification_evidence``): closure
  problems, anchored-evidence problems, exact-byte materialization
  problems, the derived verification enum and the canonical
  problem-evidence hash are ALWAYS collected by the same sequence with
  the same semantics - a materialization-only failure is replayed with
  the exact evidence it was first sealed with (never a contradictory
  empty problem set);
- P0-03 the manifest correctness identity fields
  (canonical_context_hash / base_identity_hash /
  verification_state_hash) are consumed on replay: manifest == ledger
  == current recompute (no display-only seal).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
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
    "CanonicalFinding",
    "CanonicalInputSnapshot",
    "CanonicalRunResult",
    "CanonicalRunSeal",
    "CanonicalRunner",
    "CanonicalRunnerError",
    "InputRunSeal",
    "InputVerificationEvidence",
    "MaterializedOutput",
    "SnapshotRun",
    "canonical_code_fingerprint",
]


class CanonicalRunnerError(RuntimeError):
    """The canonical boundary contract was violated (damaged prior run,
    identity dataset corruption, unreadable verified artifacts, naive
    as_of, unknown domain, unsupported declared policy, empty domain
    request, degraded inputs behind a prior SUCCESS)."""


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
    # migration 020 (CR-3.2)
    "base_identity_hash",
    "verification_state_hash",
    "input_seal_hash",
    "identity_master_input_set_hash",
    # migration 021 (CR-3.3)
    "canonical_context_hash",
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

#: verification outcomes of a discovered input run
V_HEALTHY = "HEALTHY"
V_CLOSURE_FAILED = "CLOSURE_FAILED"
V_AVAILABILITY_EVIDENCE_INVALID = "AVAILABILITY_EVIDENCE_INVALID"
V_IDENTITY_EVIDENCE_INVALID = "IDENTITY_EVIDENCE_INVALID"

#: CR-3.2 P0-03: the ONLY policy values the v1 runtime honestly executes
_SUPPORTED_POLICY_VALUES = {
    "required_evidence_class": "PROVIDER_NORMALIZED_VERIFIED",
    "reconciliation": "SINGLE_SOURCE_EXACT",
    "tolerance_rule_id": "exact-v1",
    "tolerance_rule_version": "1",
    "conflict_action": "BLOCK",
}


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


@dataclass(frozen=True)
class CanonicalFinding:
    """A DEEPLY immutable reconciliation finding (CR-3.2 P1-01)."""

    canonical_domain: str
    canonical_key: str
    finding_class: str
    provider: str | None
    source_normalization_run_id: str | None
    detail_json: str
    blocking: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_domain": self.canonical_domain,
            "canonical_key": self.canonical_key,
            "finding_class": self.finding_class,
            "provider": self.provider,
            "source_normalization_run_id": self.source_normalization_run_id,
            "detail_json": self.detail_json,
            "blocking": self.blocking,
        }


#: CR-3.4 P0-01: the IDENTITY field subset of an input seal - the
#: single source of truth for ``InputRunSeal.identity_dict`` AND for
#: the historical recompute over manifest entries: both must derive
#: the exact same input_set_hash from the exact same field set.
_INPUT_IDENTITY_FIELDS = (
    "run_id",
    "role",
    "provider",
    "normalization_surface",
    "provider_dataset",
    "endpoint",
    "raw_request_id",
    "raw_evidence_uri",
    "raw_evidence_hash",
    "normalization_contract_version",
    "mapper_identity",
    "mapper_code_hash",
    "normalized_manifest_uri",
    "normalized_manifest_hash",
    "normalized_output_set_hash",
    "normalized_semantic_hash",
    "status",
)


@dataclass(frozen=True)
class InputRunSeal:
    """CR-3.2 P0-04: the TYPED FULL CR-2 seal of one discovered input
    run - every frozen CR-2 identity/seal field is snapshotted here,
    enters the canonical manifest and the input_seal_hash, and is
    consumed three-way (snapshot == manifest == ledger) on replay."""

    run_id: str
    role: str  # source | identity_master
    provider: str
    normalization_surface: str
    provider_dataset: str
    endpoint: str
    raw_request_id: str
    raw_evidence_uri: str
    raw_evidence_hash: str
    normalization_contract_version: str
    mapper_identity: str
    mapper_code_hash: str
    normalized_manifest_uri: str
    normalized_manifest_hash: str
    normalized_output_set_hash: str
    normalized_semantic_hash: str
    status: str
    verification: str  # HEALTHY | CLOSURE_FAILED | *_INVALID
    received_at: str  # ISO (empty when the evidence is invalid)
    pit_available: bool  # anchored received_at <= as_of at snapshot time
    # CR-3.3 P0-02: canonical hash over the EXACT verification problem
    # evidence (run id + verification class + canonicalized closure /
    # anchored-evidence / materialization problem sets). HEALTHY seals
    # the empty problem set. The hash enters the verification STATE and
    # the manifest input seal (as_dict) but NEVER the base identity
    # (identity_dict) - so the same error class with a different cause
    # yields a NEW BLOCKED evidence run instead of replaying a stale
    # finding.
    verification_problem_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "provider": self.provider,
            "normalization_surface": self.normalization_surface,
            "provider_dataset": self.provider_dataset,
            "endpoint": self.endpoint,
            "raw_request_id": self.raw_request_id,
            "raw_evidence_uri": self.raw_evidence_uri,
            "raw_evidence_hash": self.raw_evidence_hash,
            "normalization_contract_version": self.normalization_contract_version,
            "mapper_identity": self.mapper_identity,
            "mapper_code_hash": self.mapper_code_hash,
            "normalized_manifest_uri": self.normalized_manifest_uri,
            "normalized_manifest_hash": self.normalized_manifest_hash,
            "normalized_output_set_hash": self.normalized_output_set_hash,
            "normalized_semantic_hash": self.normalized_semantic_hash,
            "status": self.status,
            "verification": self.verification,
            "received_at": self.received_at,
            "pit_available": self.pit_available,
            "verification_problem_hash": self.verification_problem_hash,
        }

    def identity_dict(self) -> dict[str, Any]:
        """The IDENTITY fields only - verification/received_at/
        pit_available are RUNTIME STATE (they enter the verification
        state hash / manifest evidence, never the base input identity:
        CR-3.2 P0-05 requires the base identity to stay stable across
        verification-state changes). CR-3.4 P0-01: the field set comes
        from the module-level ``_INPUT_IDENTITY_FIELDS`` single source
        of truth - the historical continuity guard recomputes the
        sealed input_set_hash from manifest entries with the SAME
        tuple."""
        return {field: getattr(self, field) for field in _INPUT_IDENTITY_FIELDS}

    def availability_row(self) -> dict[str, str]:
        """The identity subset consumed by the anchored-evidence
        verifier (raw meta bytes == sealed hash == anchor)."""
        return {
            "normalization_run_id": self.run_id,
            "provider": self.provider,
            "normalization_surface": self.normalization_surface,
            "provider_dataset": self.provider_dataset,
            "endpoint": self.endpoint,
            "raw_request_id": self.raw_request_id,
            "raw_evidence_uri": self.raw_evidence_uri,
            "raw_evidence_hash": self.raw_evidence_hash,
        }


@dataclass(frozen=True)
class CanonicalRunSeal:
    """CR-3.4 P0-01: the typed full seal of ONE canonical run as
    persisted in the ledger - the trust anchor the historical
    continuity guard verifies (ledger == manifest explicit
    correctness fields == physical recompute over the manifest input
    entries) BEFORE a prior manifest's input list may be trusted. A
    prior canonical manifest / ledger that fails this seal is itself
    DAMAGED (HARD DAMAGED): its input list is not consulted and no
    replacement of any kind may be minted."""

    canonical_run_id: str
    canonical_contract_version: str
    as_of: str
    idempotency_key: str
    status: str
    requested_domains_json: str
    requested_domains_hash: str
    input_set_hash: str
    input_seal_hash: str
    identity_dataset_hash: str
    identity_master_input_set_hash: str
    canonical_context_hash: str
    base_identity_hash: str
    verification_state_hash: str
    availability_policy_version: str
    availability_policy_hash: str
    source_policy_version: str
    source_policy_hash: str
    tolerance_policy_version: str
    tolerance_policy_hash: str
    code_fingerprint: str
    manifest_uri: str
    manifest_hash: str

    @classmethod
    def from_ledger(cls, record: Mapping[str, Any]) -> CanonicalRunSeal:
        return cls(
            canonical_run_id=str(record["canonical_run_id"]),
            canonical_contract_version=str(record["canonical_contract_version"]),
            as_of=_ledger_as_of(dict(record)).isoformat(),
            idempotency_key=str(record["idempotency_key"]),
            status=str(record["status"]),
            requested_domains_json=str(record["requested_domains_json"]),
            requested_domains_hash=str(record["requested_domains_hash"]),
            input_set_hash=str(record["input_set_hash"]),
            input_seal_hash=str(record["input_seal_hash"]),
            identity_dataset_hash=str(record["identity_dataset_hash"]),
            identity_master_input_set_hash=str(record["identity_master_input_set_hash"]),
            canonical_context_hash=str(record["canonical_context_hash"]),
            base_identity_hash=str(record["base_identity_hash"]),
            verification_state_hash=str(record["verification_state_hash"]),
            availability_policy_version=str(record["availability_policy_version"]),
            availability_policy_hash=str(record["availability_policy_hash"]),
            source_policy_version=str(record["source_policy_version"]),
            source_policy_hash=str(record["source_policy_hash"]),
            tolerance_policy_version=str(record["tolerance_policy_version"]),
            tolerance_policy_hash=str(record["tolerance_policy_hash"]),
            code_fingerprint=str(record["code_fingerprint"]),
            manifest_uri=str(record["manifest_uri"]) if record["manifest_uri"] else "",
            manifest_hash=str(record["manifest_hash"]) if record["manifest_hash"] else "",
        )


@dataclass(frozen=True)
class MaterializedOutput:
    """One materialized CR-2 output table: rows frozen as tuples of
    sorted item-tuples (deeply immutable), parsed from the EXACT bytes
    that were hash-verified inside the snapshot transaction."""

    output_name: str
    rows: tuple[tuple[tuple[str, Any], ...], ...]
    content_hash: str
    schema_hash: str

    def row_dicts(self) -> list[dict[str, Any]]:
        return [dict(items) for items in self.rows]


@dataclass(frozen=True)
class InputVerificationEvidence:
    """CR-3.4 P0-02: the ONE verification evidence state machine shared
    by first consume and replay - closure problems, anchored-evidence
    problems, exact-byte materialization problems, the derived
    verification enum and the canonical problem-evidence hash are
    ALWAYS produced by the same collection sequence with the same
    semantics (a materialization-only failure replays exactly)."""

    closure_problems: tuple[str, ...]
    anchored_evidence_problems: tuple[str, ...]
    materialization_problems: tuple[str, ...]
    verification: str
    received_at: datetime | None
    pit_available: bool
    verification_problem_hash: str
    #: materialized rows are retained only in first-consume mode; the
    #: replay mode discards them but runs the identical verification
    outputs: tuple[MaterializedOutput, ...] = ()


@dataclass(frozen=True)
class SnapshotRun:
    """One discovered input run inside the snapshot: its typed full
    seal plus its materialized (exact verified bytes) outputs."""

    seal: InputRunSeal
    outputs: tuple[MaterializedOutput, ...]

    def output(self, name: str) -> MaterializedOutput | None:
        for materialized in self.outputs:
            if materialized.output_name == name:
                return materialized
        return None


@dataclass(frozen=True)
class CanonicalInputSnapshot:
    """CR-3.2 P0-01: the ONE transactional, materialized, deeply
    immutable authoritative input world of a canonical run.

    Resolved inside a single DB snapshot boundary (BEGIN before the
    first authoritative broad SELECT, COMMIT after materialization).
    The run identity (base + verification state), the consumed
    candidates, the manifest and the ledger ALL derive from this object
    - never from a re-executed broad query or a current-path reread."""

    as_of: datetime
    requested_domains: tuple[str, ...]
    runs: tuple[SnapshotRun, ...]
    available_master_rows: tuple[tuple[tuple[str, Any], ...], ...]
    prefindings: tuple[CanonicalFinding, ...]
    master_input_set_hash: str
    identity_dataset_hash: str
    availability_policy_version: str
    availability_policy_hash: str
    source_policy_version: str
    source_policy_hash: str
    tolerance_policy_version: str
    tolerance_policy_hash: str
    code_fingerprint: str

    # ------------------------------------------------------------ derived
    @property
    def requested_domains_json(self) -> str:
        return json.dumps(list(self.requested_domains), separators=(",", ":"))

    @property
    def requested_domains_hash(self) -> str:
        return hashlib.sha256(self.requested_domains_json.encode("utf-8")).hexdigest()

    @property
    def seals(self) -> tuple[InputRunSeal, ...]:
        return tuple(run.seal for run in self.runs)

    @property
    def input_entries(self) -> tuple[dict[str, Any], ...]:
        return tuple(seal.as_dict() for seal in self.seals)

    @property
    def input_seal_hash(self) -> str:
        """Canonical hash over the TYPED full input seal (every seal
        field of every discovered run, order-stable). CR-3.5: derived
        through the shared entries-based formula (single source)."""
        return _input_hashes_from_entries(self.input_entries)[0]

    @property
    def input_set_hash(self) -> str:
        """Identity-only input set hash (stable across verification-
        state changes - the state enters verification_state_hash).
        CR-3.5: derived through the shared entries-based formula."""
        return _input_hashes_from_entries(self.input_entries)[1]

    @property
    def verification_state_hash(self) -> str:
        """CR-3.2 P0-05 + CR-3.3 P0-02: canonical hash over the
        per-input verification outcomes INCLUDING the exact problem
        evidence hash - the same error class with a different cause
        yields a NEW state (never a stale BLOCKED finding replay).
        CR-3.5: derived through the shared entries-based formula."""
        return _input_hashes_from_entries(self.input_entries)[2]

    @property
    def canonical_context_hash(self) -> str:
        """CR-3.3 P0-01: the REQUEST-WORLD identity - requested domain
        set + as_of + contract + availability/source/tolerance policy
        identities + identity bridge policy identity + canonical code
        fingerprint. Deliberately EXCLUDES the current CR-2 input set
        and the verification state: the historical SUCCESS continuity
        guard must still find a prior SUCCESS after its consumed CR-2
        inputs disappear / drift in the ledger (which changes the base
        identity but never the request world). CR-3.5 P0-02: derived
        through the shared primitive-based formula (single source)."""
        return _canonical_context_hash_from_primitives(
            requested_domains_hash=self.requested_domains_hash,
            as_of=self.as_of.isoformat(),
            canonical_contract_version=CANONICAL_CONTRACT_VERSION,
            availability_policy_version=self.availability_policy_version,
            availability_policy_hash=self.availability_policy_hash,
            source_policy_version=self.source_policy_version,
            source_policy_hash=self.source_policy_hash,
            tolerance_policy_version=self.tolerance_policy_version,
            tolerance_policy_hash=self.tolerance_policy_hash,
            identity_bridge_policy_version=_identity.identity_bridge_policy_version(),
            identity_bridge_policy_hash=_identity.identity_bridge_policy_hash(),
            code_fingerprint=self.code_fingerprint,
        )

    @property
    def base_identity_hash(self) -> str:
        """The input-world identity WITHOUT the verification state.
        CR-3.5 P0-02: derived through the shared primitive-based
        formula (single source)."""
        return _base_identity_hash_from_primitives(
            requested_domains_hash=self.requested_domains_hash,
            input_set_hash=self.input_set_hash,
            identity_dataset_hash=self.identity_dataset_hash,
            as_of=self.as_of.isoformat(),
            canonical_contract_version=CANONICAL_CONTRACT_VERSION,
            availability_policy_version=self.availability_policy_version,
            availability_policy_hash=self.availability_policy_hash,
            source_policy_version=self.source_policy_version,
            source_policy_hash=self.source_policy_hash,
            tolerance_policy_version=self.tolerance_policy_version,
            tolerance_policy_hash=self.tolerance_policy_hash,
            code_fingerprint=self.code_fingerprint,
        )

    @property
    def idempotency_key(self) -> str:
        """run id key = base identity + verification state (P0-05).
        CR-3.5 P0-02: derived through the shared formula (single
        source, cross-bound to canonical_run_id on every verify)."""
        return _idempotency_key_from_hashes(self.base_identity_hash, self.verification_state_hash)

    @property
    def has_verification_failures(self) -> bool:
        return any(seal.verification != V_HEALTHY for seal in self.seals)

    def source_runs_for(self, domain: str) -> tuple[SnapshotRun, ...]:
        """HEALTHY runs of the domain's surface/datasets (PIT
        availability is NOT filtered here - future candidates are built
        and excluded with EXCLUDED_FUTURE decisions by the run loop)."""
        spec = domain_spec(domain)
        return tuple(
            run
            for run in self.runs
            if run.seal.role == "source"
            and run.seal.normalization_surface == spec.normalization_surface
            and run.seal.provider_dataset in spec.provider_datasets
            and run.seal.verification == V_HEALTHY
        )


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


def _input_hashes_from_entries(
    entries: Sequence[Mapping[str, Any]],
) -> tuple[str, str, str]:
    """CR-3.4 P0-01: physically recompute the historical
    (input_seal_hash, input_set_hash, verification_state_hash) from a
    manifest's typed input entries - the SAME formulas
    ``CanonicalInputSnapshot`` derives from live seals, so a rebound
    input list (entries removed / altered / reordered) can never
    re-derive the sealed ledger hashes."""
    seal_list = [dict(entry) for entry in entries]
    identity_list = [
        {field: entry.get(field) for field in _INPUT_IDENTITY_FIELDS} for entry in entries
    ]
    state_list = [
        {
            "run_id": entry.get("run_id"),
            "verification": entry.get("verification"),
            "verification_problem_hash": entry.get("verification_problem_hash"),
        }
        for entry in entries
    ]
    return (
        hashlib.sha256(_canonical_json(seal_list).encode("utf-8")).hexdigest(),
        hashlib.sha256(_canonical_json(identity_list).encode("utf-8")).hexdigest(),
        hashlib.sha256(_canonical_json(state_list).encode("utf-8")).hexdigest(),
    )


def _requested_domains_hash_from_list(domains: Sequence[str]) -> str:
    """CR-3.5 P0-02: sha256 over the compact canonical JSON of the
    requested domain list - the PRIMITIVE behind the ledger/manifest
    ``requested_domains_hash`` (recomputed, never trusted)."""
    return hashlib.sha256(
        json.dumps(list(domains), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _master_input_set_hash_from_entries(entries: Sequence[Mapping[str, Any]]) -> str:
    """CR-3.5 P0-02: the identity-master input set hash derived from
    the PIT-available HEALTHY master entries - the SAME formula the
    live snapshot uses over seals, so the historical verifier
    physically recomputes it from the manifest input entries instead
    of trusting a ledger == manifest equality."""
    master_hashes = sorted(
        f"{entry.get('run_id')}:{entry.get('normalized_manifest_hash')}"
        for entry in entries
        if entry.get("role") == "identity_master"
        and entry.get("verification") == V_HEALTHY
        and bool(entry.get("pit_available"))
    )
    return hashlib.sha256("|".join(master_hashes).encode("utf-8")).hexdigest()


def _canonical_context_hash_from_primitives(
    *,
    requested_domains_hash: str,
    as_of: str,
    canonical_contract_version: str,
    availability_policy_version: str,
    availability_policy_hash: str,
    source_policy_version: str,
    source_policy_hash: str,
    tolerance_policy_version: str,
    tolerance_policy_hash: str,
    identity_bridge_policy_version: str,
    identity_bridge_policy_hash: str,
    code_fingerprint: str,
) -> str:
    """CR-3.5 P0-02: the canonical context hash derived from the
    PRIMITIVE request-world fields (+ the identity bridge policy
    identity) - the one derivation shared by the live snapshot, the
    replay verifier and the historical continuity verifier."""
    return hashlib.sha256(
        "|".join(
            (
                requested_domains_hash,
                as_of,
                canonical_contract_version,
                availability_policy_version,
                availability_policy_hash,
                source_policy_version,
                source_policy_hash,
                tolerance_policy_version,
                tolerance_policy_hash,
                identity_bridge_policy_version,
                identity_bridge_policy_hash,
                code_fingerprint,
            )
        ).encode("utf-8")
    ).hexdigest()


def _base_identity_hash_from_primitives(
    *,
    requested_domains_hash: str,
    input_set_hash: str,
    identity_dataset_hash: str,
    as_of: str,
    canonical_contract_version: str,
    availability_policy_version: str,
    availability_policy_hash: str,
    source_policy_version: str,
    source_policy_hash: str,
    tolerance_policy_version: str,
    tolerance_policy_hash: str,
    code_fingerprint: str,
) -> str:
    """CR-3.5 P0-02: the base identity hash derived from the primitive
    request-world fields + the identity-only input set + the identity
    dataset hash (no verification state, no bridge identity)."""
    return hashlib.sha256(
        "|".join(
            (
                requested_domains_hash,
                input_set_hash,
                identity_dataset_hash,
                as_of,
                canonical_contract_version,
                availability_policy_version,
                availability_policy_hash,
                source_policy_version,
                source_policy_hash,
                tolerance_policy_version,
                tolerance_policy_hash,
                code_fingerprint,
            )
        ).encode("utf-8")
    ).hexdigest()


def _idempotency_key_from_hashes(base_identity_hash: str, verification_state_hash: str) -> str:
    """CR-3.5 P0-02: idempotency key = base identity + verification
    state (the one derivation behind both the live run id and the
    historical run-id cross-bind)."""
    return hashlib.sha256(f"{base_identity_hash}|{verification_state_hash}".encode()).hexdigest()


def _canonical_run_id_from_idempotency(idempotency_key: str) -> str:
    """CR-3.5 P0-02: canonical_run_id = UUID5(run namespace,
    idempotency key) - the cross-bind recomputed on replay and
    historical continuity."""
    return str(uuid.uuid5(_RUN_NAMESPACE, idempotency_key))


def _status_error_from_findings(findings: Sequence[Mapping[str, Any]]) -> tuple[str, str | None]:
    """CR-3.5 P0-02: the canonical run status (and its derived error
    text) is a FUNCTION of the exact sealed findings truth - any
    blocking finding -> BLOCKED, otherwise SUCCESS. Live build, replay
    and historical continuity all derive it through this ONE helper;
    the ledger/manifest status fields are consumed AGAINST this
    recompute, never trusted as free strings."""
    blocking = [f for f in findings if bool(f.get("blocking"))]
    if blocking:
        classes = sorted({str(f.get("finding_class")) for f in blocking})
        return "BLOCKED", f"{len(blocking)} blocking finding(s): " + "; ".join(classes)
    return "SUCCESS", None


def _derived_run_identity_problems(
    *,
    entries: Sequence[Mapping[str, Any]],
    requested_domains: Sequence[str],
    as_of: str,
    ledger: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> list[str]:
    """CR-3.5 P0-02: physically recompute the FULL derived canonical
    run identity from the primitive request-world fields + the
    manifest input entries, and compare EVERY recomputation against
    the ledger typed seal:

        requested_domains_hash        <- compact JSON of the domain list
        input_seal_hash               <- manifest entries (full seal)
        input_set_hash                <- manifest entries (identity subset)
        verification_state_hash       <- manifest entries (state subset)
        identity_master_input_set_hash<- PIT-healthy master entries
        identity_dataset_hash         <- recompute(master set + bridge policy)
        canonical_context_hash        <- primitives + bridge policy identity
        base_identity_hash            <- primitives + input set + dataset hash
        idempotency_key               <- base + verification state
        canonical_run_id              <- UUID5(namespace, idempotency key)

    A ledger+manifest rebind of any derived field that does not
    replay this physical derivation is DAMAGED. Shared by the replay
    closure verifier AND the historical continuity seal verifier (the
    live build derives through the same module-level helpers)."""
    problems: list[str] = []
    bridge_version = str(manifest.get("identity_bridge_policy_version") or "")
    bridge_hash = str(manifest.get("identity_bridge_policy_hash") or "")
    if not bridge_version or not bridge_hash:
        problems.append("manifest carries no identity bridge policy identity")
    contract = str(ledger["canonical_contract_version"])
    availability_version = str(ledger["availability_policy_version"])
    availability_hash = str(ledger["availability_policy_hash"])
    source_version = str(ledger["source_policy_version"])
    source_hash = str(ledger["source_policy_hash"])
    tolerance_version = str(ledger["tolerance_policy_version"])
    tolerance_hash = str(ledger["tolerance_policy_hash"])
    fingerprint = str(ledger["code_fingerprint"])
    domains_hash_recompute = _requested_domains_hash_from_list(requested_domains)
    if domains_hash_recompute != str(ledger["requested_domains_hash"]):
        problems.append("requested_domains_hash does not match the requested domain list")
    seal_recompute, set_recompute, state_recompute = _input_hashes_from_entries(entries)
    master_recompute = _master_input_set_hash_from_entries(entries)
    # the dataset hash is recomputed with the run's OWN sealed bridge
    # policy identity (the manifest is the only persistence of that
    # world's bridge identity) - never the current code's, so a prior
    # run of an older bridge-policy world verifies against ITS world.
    dataset_recompute = _identity.identity_dataset_hash_with_bridge(
        master_recompute, bridge_version, bridge_hash
    )
    context_recompute = _canonical_context_hash_from_primitives(
        requested_domains_hash=domains_hash_recompute,
        as_of=as_of,
        canonical_contract_version=contract,
        availability_policy_version=availability_version,
        availability_policy_hash=availability_hash,
        source_policy_version=source_version,
        source_policy_hash=source_hash,
        tolerance_policy_version=tolerance_version,
        tolerance_policy_hash=tolerance_hash,
        identity_bridge_policy_version=bridge_version,
        identity_bridge_policy_hash=bridge_hash,
        code_fingerprint=fingerprint,
    )
    base_recompute = _base_identity_hash_from_primitives(
        requested_domains_hash=domains_hash_recompute,
        input_set_hash=set_recompute,
        identity_dataset_hash=dataset_recompute,
        as_of=as_of,
        canonical_contract_version=contract,
        availability_policy_version=availability_version,
        availability_policy_hash=availability_hash,
        source_policy_version=source_version,
        source_policy_hash=source_hash,
        tolerance_policy_version=tolerance_version,
        tolerance_policy_hash=tolerance_hash,
        code_fingerprint=fingerprint,
    )
    idempotency_recompute = _idempotency_key_from_hashes(base_recompute, state_recompute)
    run_id_recompute = _canonical_run_id_from_idempotency(idempotency_recompute)
    for field, recomputed in (
        ("input_seal_hash", seal_recompute),
        ("input_set_hash", set_recompute),
        ("verification_state_hash", state_recompute),
        ("identity_master_input_set_hash", master_recompute),
        ("identity_dataset_hash", dataset_recompute),
        ("canonical_context_hash", context_recompute),
        ("base_identity_hash", base_recompute),
        ("idempotency_key", idempotency_recompute),
    ):
        if recomputed != str(ledger[field]):
            problems.append(
                f"ledger {field} does not match the physical recompute from "
                "the manifest entries/primitives (derived seal rebind)"
            )
    if run_id_recompute != str(ledger["canonical_run_id"]):
        problems.append("canonical_run_id does not match UUID5 of the recomputed idempotency key")
    return problems


def _freeze(value: Any) -> Any:
    """Deeply freeze a parsed row value: lists -> tuples, dicts ->
    sorted item-tuples (deeply immutable snapshot representation)."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


def _rows_semantic_hash(rows: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        _canonical_json(sorted(_canonical_json(r) for r in rows)).encode("utf-8")
    ).hexdigest()


def _finding_set_hash(findings: Sequence[Mapping[str, Any]]) -> str:
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
    """CR-3.1 P1: as_of parsing is deterministic across platforms. Naive
    datetimes are REJECTED; naive strings are parsed under the
    documented FIXED-UTC rule."""
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


def _finding(
    domain: str,
    key_json: str,
    finding_class: str,
    provider: str | None,
    source_run_id: str | None,
    detail: dict[str, Any],
    *,
    blocking: bool,
) -> CanonicalFinding:
    return CanonicalFinding(
        canonical_domain=domain,
        canonical_key=key_json,
        finding_class=finding_class,
        provider=provider,
        source_normalization_run_id=source_run_id,
        detail_json=_canonical_json(detail),
        blocking=blocking,
    )


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
        # CR-3.2 P1-03: explicit empty semantics - None = all supported
        # domains; an EMPTY collection is rejected (never a truthiness
        # accident that silently builds everything).
        if domains is None:
            requested = supported_domains()
        else:
            if len(domains) == 0:
                msg = (
                    "domains=[] is not a valid canonical request - pass None "
                    "to build all supported domains, or a non-empty collection"
                )
                raise CanonicalRunnerError(msg)
            requested = tuple(sorted(set(domains)))
        for domain in requested:
            spec = domain_spec(domain)
            if spec.eligibility is not DomainEligibility.CANONICAL_SUPPORTED:
                msg = (
                    f"canonical domain {domain!r} is {spec.eligibility.value} - "
                    "it can never produce canonical rows (no silent skip)"
                )
                raise CanonicalRunnerError(msg)
        self._assert_policy_honestly_executed()

        # ------------------------ ONE transactional materialized snapshot
        snapshot = self._build_snapshot(as_of_dt, requested)

        # ------------- CR-3.3 P0-01 historical input continuity guard
        self._check_historical_continuity(snapshot)

        # ------------------------ exact replay lookup (history-wide)
        idempotency_key = snapshot.idempotency_key
        run_id = _canonical_run_id_from_idempotency(idempotency_key)
        prior = self.conn.execute(
            "SELECT canonical_run_id FROM meta_canonicalization_run WHERE canonical_run_id = ?",
            [run_id],
        ).fetchone()
        if prior is not None:
            return self._require_verified_replay(run_id, idempotency_key, snapshot)

        findings: list[CanonicalFinding] = list(snapshot.prefindings)
        bridge = IdentityBridge(
            [dict(items) for items in snapshot.available_master_rows],
            master_input_set_hash=snapshot.master_input_set_hash,
        )

        # ------------------------------------------ identity dataset state
        identity_required = [d for d in requested if domain_spec(d).requires_security_identity]
        available_masters = [
            s for s in snapshot.runs if s.seal.role == "identity_master" and s.seal.pit_available
        ]
        discovered_masters = [s for s in snapshot.runs if s.seal.role == "identity_master"]
        if identity_required:
            invalid_masters = [
                s
                for s in discovered_masters
                if s.seal.verification in (V_CLOSURE_FAILED, V_IDENTITY_EVIDENCE_INVALID)
            ]
            if invalid_masters:
                for run_snapshot in invalid_masters:
                    findings.append(
                        _finding(
                            "security_master",
                            "",
                            "IDENTITY_EVIDENCE_INVALID",
                            run_snapshot.seal.provider,
                            run_snapshot.seal.run_id,
                            {"verification": run_snapshot.seal.verification},
                            blocking=True,
                        )
                    )
            elif discovered_masters and not available_masters:
                findings.append(
                    _finding(
                        "security_master",
                        "",
                        "IDENTITY_DATASET_UNAVAILABLE_AT_ASOF",
                        None,
                        None,
                        {
                            "reason": (
                                "identity master runs exist but none is "
                                "PIT-available at this as_of - future identity "
                                "knowledge must not resolve historical rows"
                            )
                        },
                        blocking=True,
                    )
                )
            elif not discovered_masters:
                findings.append(
                    _finding(
                        "security_master",
                        "",
                        "IDENTITY_DATASET_MISSING",
                        None,
                        None,
                        {"reason": "no verified security_master run discovered"},
                        blocking=True,
                    )
                )

        # ------------------------------------------ candidates per domain
        selected_rows: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        identity_missing_by_domain: dict[str, int] = {}

        for domain in requested:
            policy = _source_policy.source_policy_for(domain)
            candidates: list[dict[str, Any]] = []
            for run_snapshot in snapshot.source_runs_for(domain):
                candidates.extend(self._build_candidates(domain, run_snapshot, bridge))
            available: list[dict[str, Any]] = []
            for candidate in candidates:
                if candidate["available_at"] <= as_of_dt:
                    available.append(candidate)
                else:
                    decisions.append(
                        self._decision(domain, candidate, "EXCLUDED_FUTURE", "available_at > as_of")
                    )
            eligible_verified = [
                s
                for s in snapshot.runs
                if s.seal.role == "source"
                and s.seal.normalization_surface == domain_spec(domain).normalization_surface
                and s.seal.provider_dataset in domain_spec(domain).provider_datasets
            ]
            healthy_verified = [s for s in eligible_verified if s.seal.verification == V_HEALTHY]
            # CR-3.3 P1-02 finding precedence (audit 20260902 section 4):
            # no discovered run -> MISSING; discovered but damaged ->
            # closure/evidence findings only (damage is NOT unavailability);
            # healthy runs but all received_at > as_of -> UNAVAILABLE.
            if not eligible_verified:
                findings.append(
                    _finding(
                        domain,
                        "",
                        "REQUIRED_DOMAIN_MISSING",
                        None,
                        None,
                        {"reason": "no eligible verified CR-2 run for this domain"},
                        blocking=True,
                    )
                )
            elif not healthy_verified:
                pass  # damaged inputs already carry closure/evidence findings
            elif not available:
                findings.append(
                    _finding(
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

        for domain, missing in identity_missing_by_domain.items():
            if missing <= 0:
                continue
            policy = _source_policy.source_policy_for(domain)
            findings.append(
                _finding(
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

        # CR-3.5 P0-02: status + derived error text are FUNCTIONS of
        # the exact findings truth - live build, replay and historical
        # continuity share this one derivation, so a status rebind that
        # does not replay the sealed findings truth is DAMAGED.
        status, error = _status_error_from_findings([f.as_dict() for f in findings])

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
    def _check_historical_continuity(self, snapshot: CanonicalInputSnapshot) -> None:
        """CR-3.3 P0-01 + CR-3.4 P0-01 + CR-3.5 P0-01 + CR-3.6 P0-01
        (audits 20260902 section 1): historical input continuity guard
        with SELECTION-FREE, pre-verification-trust-free discovery.

        CR-3.6 closes the last discovery hole: NO correctness-bearing
        field may exclude a historical canonical row before its
        identity seal is verified. The discovery is a broad full-table
        scan (ORDER BY canonical_run_id) with no WHERE clause and no
        Python-side pre-filter - not status, not the derived context
        hash, and not the primitive request-world fields either (a
        single-field drift of requested_domains_hash / as_of /
        contract / a policy identity / the code fingerprint previously
        removed the row from the candidate set before the verifier
        ever saw it).

        Every historical row then passes the typed identity seal
        (deterministic manifest URI + bytes hash + manifest == ledger
        correctness fields + the full derived-identity physical
        recompute). A row whose identity seal cannot be established is
        GLOBAL / HISTORICAL CANONICAL LEDGER DAMAGED: the system
        cannot safely prove the damaged record is unrelated to the
        current request world, so it fails closed and mints nothing.

        Only after the identity seal verifies is the (now physically
        derived) request world interpreted:

        - a verified different request world -> safely skipped;
        - a verified same-world row: the canonical artifact closure
          (selected / decisions / findings - exact set, deterministic
          URIs, physical hashes, semantic seals) and the findings ->
          status semantic truth are verified before anything else;
        - a verified genuine historical BLOCKED -> not a SUCCESS
          continuity dependency (its exact repair / recovery is
          allowed to proceed);
        - a verified same-world SUCCESS -> every sealed input run must
          still exist in the current authoritative CR-2 ledger with an
          identical identity and healthy physical / anchored evidence
          (a SUPERSET current input set is a legitimate new world and
          flows on normally).

        Any problem -> DAMAGED (no replacement of any kind may be
        minted)."""
        candidate_rows = self.conn.execute(
            f"SELECT {', '.join(_LEDGER_COLUMNS)} FROM meta_canonicalization_run "
            "ORDER BY canonical_run_id"
        ).fetchall()
        current_seal_by_run = {seal.run_id: seal for seal in snapshot.seals}
        for row in candidate_rows:
            record = dict(zip(_LEDGER_COLUMNS, row, strict=True))
            seal = CanonicalRunSeal.from_ledger(record)
            manifest, identity_problems = self._verify_historical_identity_seal(seal, record)
            if identity_problems or manifest is None:
                detail = "; ".join(identity_problems) if identity_problems else "no verifiable seal"
                msg = (
                    f"historical canonical ledger row {seal.canonical_run_id} is DAMAGED "
                    f"(GLOBAL): {detail} - the row's request-world identity can no "
                    "longer be safely established, so it cannot be proven unrelated "
                    "to the current request world; no new canonical run may be "
                    "minted until the historical evidence is restored "
                    "(CR-3.6 audit 20260902 section 1)"
                )
                raise CanonicalRunnerError(msg)
            # verified, physically derived world membership
            if seal.canonical_context_hash != snapshot.canonical_context_hash:
                continue  # a verified different request world is safely skipped
            # same verified world: CR-3.6 P0-02 canonical artifact closure
            problems = self._verify_canonical_artifacts(record, manifest)
            # CR-3.5 P0-02 findings truth -> status semantic recompute
            verified_status, finding_problems = self._verify_findings_truth(record, manifest)
            problems.extend(finding_problems)
            if problems:
                msg = (
                    f"prior canonical run {seal.canonical_run_id} is DAMAGED: "
                    f"{'; '.join(problems)} - the prior run and its sealed "
                    "evidence can no longer be trusted and no replacement may "
                    "be minted; restore the exact upstream evidence to replay "
                    "the historical run (CR-3.6 audit 20260902 sections 1-2)"
                )
                raise CanonicalRunnerError(msg)
            # verified, physically derived historical status
            if verified_status == "BLOCKED":
                continue  # genuine historical BLOCKED: not a SUCCESS dependency
            for entry in manifest.get("input_normalized_runs", []):
                run_id = str(entry.get("run_id"))
                problems.extend(
                    self._continuity_problems_for_input(entry, run_id, current_seal_by_run)
                )
            if problems:
                msg = (
                    f"prior canonical run {seal.canonical_run_id} consumed inputs "
                    f"that are no longer intact: {'; '.join(problems)} - the "
                    "prior run is DAMAGED and no replacement may be minted; "
                    "restore the exact upstream evidence to replay the "
                    "historical run (CR-3.3 audit 20260902 section 1 + "
                    "CR-3.6 audit 20260902 section 1)"
                )
                raise CanonicalRunnerError(msg)

    def _verify_historical_identity_seal(
        self, seal: CanonicalRunSeal, record: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str]]:
        """CR-3.4 P0-01 + CR-3.5 P0-02 + CR-3.6 P0-01: typed
        IDENTITY-seal verification of ONE historical canonical run
        BEFORE its request-world membership, its manifest input list
        or its claimed status may be interpreted - the deterministic
        manifest URI, the manifest bytes against the ledger hash,
        EVERY explicit manifest correctness field against the ledger
        seal, and the physical recompute of the ENTIRE derived run
        identity (input hashes + master set + dataset hash + canonical
        context + base identity + idempotency key + run id) from the
        manifest input entries and the primitive request-world fields.
        Any problem -> the historical row is GLOBAL / HISTORICAL
        CANONICAL LEDGER DAMAGED: its world membership cannot be
        safely established, it cannot be proven unrelated to the
        current request world, and no replacement of any kind may be
        minted. Returns (manifest, problems). The findings -> status
        semantic truth (``_verify_findings_truth``) is deliberately
        NOT part of the identity seal: it runs only for SAME-world
        rows after world membership is verified."""
        if not seal.manifest_uri or not seal.manifest_hash:
            return None, ["prior canonical ledger row carries no manifest binding"]
        record_for_uri = {
            "canonical_contract_version": seal.canonical_contract_version,
            "as_of": seal.as_of,
            "canonical_run_id": seal.canonical_run_id,
        }
        expected_manifest_uri = f"{self._expected_base_uri(record_for_uri)}/manifest.json"
        if seal.manifest_uri != expected_manifest_uri:
            return (
                None,
                [
                    f"prior canonical manifest_uri {seal.manifest_uri!r} is not the "
                    f"deterministic anchor {expected_manifest_uri!r} (rebind)"
                ],
            )
        manifest_path = self.normalized_root / seal.manifest_uri
        if not manifest_path.is_file():
            return None, [f"prior canonical manifest missing: {seal.manifest_uri}"]
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != seal.manifest_hash:
            return None, ["prior canonical manifest bytes do not match the ledger hash (rebind)"]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, [f"prior canonical manifest unreadable: {exc}"]
        problems: list[str] = []
        expected_fields = (
            ("canonical_run_id", seal.canonical_run_id),
            ("canonical_contract_version", seal.canonical_contract_version),
            ("as_of", seal.as_of),
            ("idempotency_key", seal.idempotency_key),
            ("status", seal.status),
            ("requested_domains_hash", seal.requested_domains_hash),
            ("input_set_hash", seal.input_set_hash),
            ("input_seal_hash", seal.input_seal_hash),
            ("identity_dataset_hash", seal.identity_dataset_hash),
            ("identity_master_input_set_hash", seal.identity_master_input_set_hash),
            ("canonical_context_hash", seal.canonical_context_hash),
            ("base_identity_hash", seal.base_identity_hash),
            ("verification_state_hash", seal.verification_state_hash),
            ("availability_policy_version", seal.availability_policy_version),
            ("availability_policy_hash", seal.availability_policy_hash),
            ("source_policy_version", seal.source_policy_version),
            ("source_policy_hash", seal.source_policy_hash),
            ("tolerance_policy_version", seal.tolerance_policy_version),
            ("tolerance_policy_hash", seal.tolerance_policy_hash),
            ("code_fingerprint", seal.code_fingerprint),
        )
        for field, expected in expected_fields:
            if str(manifest.get(field)) != expected:
                problems.append(
                    f"prior canonical manifest field {field} does not match the "
                    "ledger seal (manifest rebind)"
                )
        try:
            ledger_domains = json.loads(seal.requested_domains_json)
        except json.JSONDecodeError:
            problems.append("prior canonical ledger requested_domains_json is unreadable")
            ledger_domains = None
        if (
            ledger_domains is not None
            and list(manifest.get("requested_domains") or []) != ledger_domains
        ):
            problems.append(
                "prior canonical manifest requested_domains does not match the ledger seal (rebind)"
            )
        entries = manifest.get("input_normalized_runs")
        if not isinstance(entries, list):
            problems.append("prior canonical manifest carries no typed input list")
            return None, problems
        seal_recompute, set_recompute, state_recompute = _input_hashes_from_entries(entries)
        if seal_recompute != seal.input_seal_hash:
            problems.append(
                "prior canonical input_seal_hash does not match the manifest "
                "input entries (input list rebind)"
            )
        if set_recompute != seal.input_set_hash:
            problems.append(
                "prior canonical input_set_hash does not match the manifest "
                "input entries (input list rebind)"
            )
        if state_recompute != seal.verification_state_hash:
            problems.append(
                "prior canonical verification_state_hash does not match the "
                "manifest input entries (input list rebind)"
            )
        # CR-3.5 P0-02: the ENTIRE derived run identity is physically
        # recomputed from the manifest input entries + the primitive
        # request-world fields (ledger) + the manifest bridge policy
        # identity, and compared against the ledger seal.
        problems.extend(
            _derived_run_identity_problems(
                entries=entries,
                requested_domains=list(manifest.get("requested_domains") or []),
                as_of=seal.as_of,
                ledger=record,
                manifest=manifest,
            )
        )
        if problems:
            return None, problems
        return manifest, []

    def _sealed_input_authority_problems(self, entry: dict[str, Any], run_id: str) -> list[str]:
        """CR-4.1: authority + physical health of ONE sealed CR-2 input
        of a historical canonical run - ledger existence, identity
        equality and anchored/physical health, WITHOUT the
        current-discovery-presence requirement. Shared by the
        historical continuity guard (which additionally demands
        presence in the current discovery) and the CR-4 public
        consumption verifier (a later legitimate superset world must
        not retroactively break consumption of an already-minted
        SUCCESS run)."""
        problems: list[str] = []
        row = self.conn.execute(
            "SELECT provider, normalization_surface, provider_dataset, endpoint, "
            "raw_request_id, raw_evidence_uri, raw_evidence_hash, "
            "normalization_contract_version, mapper_identity, mapper_code_hash, "
            "normalized_manifest_uri, normalized_manifest_hash, "
            "normalized_output_set_hash, normalized_semantic_hash, status "
            "FROM meta_provider_normalization_run WHERE normalization_run_id = ?",
            [run_id],
        ).fetchone()
        if row is None:
            return [
                f"sealed input run {run_id} no longer exists in the CR-2 ledger (disappearance)"
            ]
        current = dict(
            zip(
                (
                    "provider",
                    "normalization_surface",
                    "provider_dataset",
                    "endpoint",
                    "raw_request_id",
                    "raw_evidence_uri",
                    "raw_evidence_hash",
                    "normalization_contract_version",
                    "mapper_identity",
                    "mapper_code_hash",
                    "normalized_manifest_uri",
                    "normalized_manifest_hash",
                    "normalized_output_set_hash",
                    "normalized_semantic_hash",
                    "status",
                ),
                row,
                strict=True,
            )
        )
        for field, expected in current.items():
            if str(entry.get(field, "")) != str(expected):
                problems.append(
                    f"sealed input run {run_id} ledger field {field} drifted: "
                    f"sealed {entry.get(field)!r} != current {expected!r}"
                )
        if problems:
            return problems
        # identity intact: physical + anchored verification must still be healthy
        run_row = {
            "normalization_run_id": run_id,
            **current,
        }
        anchor_problems, _ = self._verify_anchored_availability(run_row)
        if anchor_problems:
            problems.extend(
                f"sealed input run {run_id} anchored evidence degraded: {p}"
                for p in anchor_problems
            )
        closure_problems = verify_normalized_run(
            self.conn,
            run_id,
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        problems.extend(
            f"sealed input run {run_id} closure degraded: {p}" for p in closure_problems
        )
        return problems

    def _continuity_problems_for_input(
        self,
        entry: dict[str, Any],
        run_id: str,
        current_seal_by_run: dict[str, InputRunSeal],
    ) -> list[str]:
        """Continuity problems of ONE sealed input run of a prior
        canonical run: ledger existence, identity equality, physical /
        anchored health (symmetric with first consume) AND presence in
        the current snapshot discovery (same context => same surface
        plan; absence would be unexplainable discovery drift)."""
        problems = self._sealed_input_authority_problems(entry, run_id)
        if problems:
            return problems
        # healthy + identity intact: the prior input must also be present in
        # the CURRENT snapshot discovery (same context => same surface plan;
        # absence would be unexplainable discovery drift)
        if run_id not in current_seal_by_run:
            problems.append(
                f"sealed input run {run_id} is healthy but absent from the "
                "current snapshot discovery (unexplainable drift)"
            )
        return problems

    def _build_snapshot(
        self, as_of_dt: datetime, requested: tuple[str, ...]
    ) -> CanonicalInputSnapshot:
        """CR-3.2 P0-01: resolve the ONE authoritative input world inside
        a REAL DB snapshot boundary - BEGIN before the first broad
        SELECT, every underlying surface queried exactly once, every
        consumed output MATERIALIZED from exact hash-verified bytes,
        COMMIT. Tests may monkeypatch internal query hooks to inject
        concurrent writes BETWEEN the broad reads - production never
        exposes such a hook."""
        self.conn.execute("BEGIN TRANSACTION")
        try:
            surfaces = self._surface_plan(requested)
            discovered: dict[str, list[dict[str, Any]]] = {}
            for surface, datasets in surfaces:
                discovered[f"{surface}|{','.join(datasets)}"] = self._surface_runs(
                    surface, datasets
                )
            runs: list[SnapshotRun] = []
            prefindings: list[CanonicalFinding] = []
            available_master_rows: list[tuple[tuple[str, Any], ...]] = []
            for key, run_rows in sorted(discovered.items()):
                surface = key.split("|")[0]
                role = "identity_master" if surface == "security_master" else "source"
                for run_row in run_rows:
                    snapshot_run, findings = self._snapshot_run(run_row, role, as_of_dt, requested)
                    runs.append(snapshot_run)
                    prefindings.extend(findings)
                    if (
                        role == "identity_master"
                        and snapshot_run.seal.verification == V_HEALTHY
                        and snapshot_run.seal.pit_available
                    ):
                        master_output = snapshot_run.output("main")
                        if master_output is not None:
                            available_master_rows.extend(master_output.rows)
            self.conn.execute("COMMIT")
        except Exception:
            import contextlib

            with contextlib.suppress(Exception):
                self.conn.execute("ROLLBACK")
            raise

        seals = tuple(run.seal for run in runs)
        # CR-3.5 P0-02: master set hash derived through the shared
        # entries-based formula (the historical verifier recomputes the
        # SAME value from the manifest input entries).
        master_input_set_hash = _master_input_set_hash_from_entries(
            [seal.as_dict() for seal in seals]
        )
        tolerance_version, tolerance_hash = _source_policy.tolerance_policy_identity()
        return CanonicalInputSnapshot(
            as_of=as_of_dt,
            requested_domains=requested,
            runs=tuple(runs),
            available_master_rows=tuple(available_master_rows),
            prefindings=tuple(prefindings),
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

    @staticmethod
    def _surface_plan(requested: tuple[str, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """CR-3.2 P1-02: one broad query per underlying SURFACE (union of
        the datasets of every domain that consumes it) - a surface
        shared by several requested domains is discovered exactly once."""
        surfaces: dict[str, set[str]] = {}
        for domain in requested:
            spec = domain_spec(domain)
            surfaces.setdefault(spec.normalization_surface, set()).update(spec.provider_datasets)
        surfaces.setdefault("security_master", set()).update(
            ("code_list", "hist_code_list", "stock_basic")
        )
        return tuple(
            (surface, tuple(sorted(datasets))) for surface, datasets in sorted(surfaces.items())
        )

    def _snapshot_run(
        self, run_row: dict[str, Any], role: str, as_of_dt: datetime, requested: tuple[str, ...]
    ) -> tuple[SnapshotRun, list[CanonicalFinding]]:
        """Verify one discovered run (CR-2 closure + anchored
        availability + exact-byte materialization - all through the
        ONE shared evidence collector, CR-3.4 P0-02) and MATERIALIZE
        its outputs from the exact hash-verified bytes inside the
        snapshot boundary.

        CR-3.3 P1-01: source-scope findings carry the reserved input
        scope ``input:<normalization_surface>`` (never the meaningless
        "source") and seal the affected requested domains in detail.
        CR-3.3 P0-02: the seal carries the verification_problem_hash
        over the exact canonicalized problem evidence."""
        findings: list[CanonicalFinding] = []
        surface = str(run_row["normalization_surface"])
        if role == "identity_master":
            scope = "security_master"
            affected: list[str] = []
        else:
            # reserved input-scope schema + affected requested domains
            scope = f"input:{surface}"
            affected = sorted(
                domain
                for domain in requested
                if domain_spec(domain).normalization_surface == surface
            )
        evidence = self._collect_input_verification_evidence(
            run_row, role, as_of_dt, keep_rows=True
        )
        if evidence.closure_problems:
            findings.append(
                _finding(
                    scope,
                    "",
                    "CLOSURE_VERIFICATION_FAILED",
                    run_row["provider"],
                    run_row["normalization_run_id"],
                    {"problems": list(evidence.closure_problems), "affected_domains": affected},
                    blocking=True,
                )
            )
        if evidence.anchored_evidence_problems:
            finding_class = (
                "IDENTITY_EVIDENCE_INVALID"
                if role == "identity_master"
                else "AVAILABILITY_EVIDENCE_INVALID"
            )
            findings.append(
                _finding(
                    scope,
                    "",
                    finding_class,
                    run_row["provider"],
                    run_row["normalization_run_id"],
                    {
                        "problems": list(evidence.anchored_evidence_problems),
                        "affected_domains": affected,
                    },
                    blocking=True,
                )
            )
        if evidence.materialization_problems:
            findings.append(
                _finding(
                    scope,
                    "",
                    "CLOSURE_VERIFICATION_FAILED",
                    run_row["provider"],
                    run_row["normalization_run_id"],
                    {
                        "problems": list(evidence.materialization_problems),
                        "affected_domains": affected,
                    },
                    blocking=True,
                )
            )
        seal = InputRunSeal(
            run_id=str(run_row["normalization_run_id"]),
            role=role,
            provider=str(run_row["provider"]),
            normalization_surface=str(run_row["normalization_surface"]),
            provider_dataset=str(run_row["provider_dataset"]),
            endpoint=str(run_row["endpoint"]),
            raw_request_id=str(run_row["raw_request_id"]),
            raw_evidence_uri=str(run_row["raw_evidence_uri"]),
            raw_evidence_hash=str(run_row["raw_evidence_hash"]),
            normalization_contract_version=str(run_row["normalization_contract_version"]),
            mapper_identity=str(run_row["mapper_identity"]),
            mapper_code_hash=str(run_row["mapper_code_hash"]),
            normalized_manifest_uri=str(run_row["normalized_manifest_uri"]),
            normalized_manifest_hash=str(run_row["normalized_manifest_hash"]),
            normalized_output_set_hash=str(run_row["normalized_output_set_hash"]),
            normalized_semantic_hash=str(run_row["normalized_semantic_hash"]),
            status=str(run_row["status"]),
            verification=evidence.verification,
            received_at=evidence.received_at.isoformat() if evidence.received_at else "",
            pit_available=evidence.pit_available,
            verification_problem_hash=evidence.verification_problem_hash,
        )
        return SnapshotRun(seal=seal, outputs=evidence.outputs), findings

    def _collect_input_verification_evidence(
        self,
        run_row: dict[str, Any],
        role: str,
        as_of_dt: datetime,
        *,
        keep_rows: bool,
    ) -> InputVerificationEvidence:
        """CR-3.4 P0-02: the ONE verification evidence collector -
        first consume (``_snapshot_run``) and replay
        (``_verify_sealed_input``) run the SAME sequence with the SAME
        semantics: CR-2 closure verification -> anchored availability
        evidence -> (only when closure + anchor are healthy) exact-byte
        materialization verification -> derived verification enum ->
        canonical problem-evidence hash. ``keep_rows`` only controls
        whether the materialized rows are returned; the verification
        sequence itself is identical, so a materialization-only
        failure is replayed with the exact evidence hash it was first
        sealed with (never a contradictory empty problem set)."""
        closure_problems = verify_normalized_run(
            self.conn,
            str(run_row["normalization_run_id"]),
            raw_root=self.raw_root,
            normalized_root=self.normalized_root,
        )
        anchor_problems, received_at = self._verify_anchored_availability(run_row)
        verification = V_HEALTHY
        if closure_problems:
            verification = V_CLOSURE_FAILED
        elif anchor_problems:
            verification = (
                V_IDENTITY_EVIDENCE_INVALID
                if role == "identity_master"
                else V_AVAILABILITY_EVIDENCE_INVALID
            )
        pit_available = bool(
            verification == V_HEALTHY and received_at is not None and received_at <= as_of_dt
        )
        outputs: list[MaterializedOutput] = []
        materialization_problems: list[str] = []
        if verification == V_HEALTHY:
            materialized, materialization_problems = self._materialize_outputs(run_row)
            if materialization_problems:
                verification = V_CLOSURE_FAILED
                pit_available = False
            elif keep_rows:
                outputs = materialized
        problem_evidence = {
            "run_id": str(run_row["normalization_run_id"]),
            "verification": verification,
            "closure_problems": sorted(closure_problems),
            "anchored_evidence_problems": sorted(anchor_problems),
            "materialization_problems": sorted(materialization_problems),
        }
        problem_hash = hashlib.sha256(_canonical_json(problem_evidence).encode("utf-8")).hexdigest()
        return InputVerificationEvidence(
            closure_problems=tuple(closure_problems),
            anchored_evidence_problems=tuple(anchor_problems),
            materialization_problems=tuple(materialization_problems),
            verification=verification,
            received_at=received_at,
            pit_available=pit_available,
            verification_problem_hash=problem_hash,
            outputs=tuple(outputs),
        )

    def _materialize_outputs(
        self, run_row: dict[str, Any]
    ) -> tuple[list[MaterializedOutput], list[str]]:
        """Read the EXACT sealed output bytes (hash-verify each read
        against the manifest entry) and parse the SAME bytes into frozen
        rows - the candidate builder never rereads a current path."""
        import io

        problems: list[str] = []
        manifest_path = self.normalized_root / str(run_row["normalized_manifest_uri"])
        if not manifest_path.is_file():
            return [], [f"normalized manifest missing: {run_row['normalized_manifest_uri']}"]
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != str(run_row["normalized_manifest_hash"]):
            return [], ["normalized manifest bytes do not match the ledger hash"]
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return [], [f"normalized manifest unreadable: {exc}"]
        outputs: list[MaterializedOutput] = []
        for entry in manifest.get("outputs", []):
            output_name = str(entry.get("output_name"))
            uri = str(entry.get("uri"))
            path = self.normalized_root / uri
            if not path.is_file():
                problems.append(f"output artifact missing: {uri}")
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != str(entry.get("content_hash")):
                problems.append(f"output artifact bytes do not match the sealed hash: {uri}")
                continue
            try:
                frame = pl.read_parquet(io.BytesIO(data))
            except Exception as exc:  # noqa: BLE001 - reported as problems
                problems.append(f"output artifact unreadable: {uri}: {exc}")
                continue
            if frame.height != int(entry.get("row_count", -1)):
                problems.append(f"output artifact row count mismatch: {uri}")
                continue
            rows = tuple(
                tuple(sorted((str(k), _freeze(v)) for k, v in row.items()))
                for row in frame.to_dicts()
            )
            outputs.append(
                MaterializedOutput(
                    output_name=output_name,
                    rows=rows,
                    content_hash=str(entry.get("content_hash")),
                    schema_hash=str(entry.get("schema_hash")),
                )
            )
        return outputs, problems

    def _verify_anchored_availability(
        self, run_row: dict[str, Any]
    ) -> tuple[list[str], datetime | None]:
        """CR-3.1 P0-04 / CR-3.2 P0-02: the availability moment may ONLY
        be read from raw meta bytes whose exact SHA-256 equals BOTH the
        normalization run's sealed raw_evidence_hash AND the
        authoritative meta_raw_evidence_anchor entry (identity
        cross-bound). Applies to market sources AND identity masters
        symmetrically."""
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

    def _assert_policy_honestly_executed(self) -> None:
        """CR-3.2 P0-03: the runtime HONESTLY executes the declared
        policy - every semantic field is guarded against values the v1
        runtime does not implement. Declaring an unsupported value
        fails closed BEFORE any canonical run instead of silently
        keeping the old behavior under a new hash."""
        for policy in _source_policy.source_policies():
            for field, supported in _SUPPORTED_POLICY_VALUES.items():
                declared = getattr(policy, field)
                if declared != supported:
                    msg = (
                        f"source policy for {policy.domain} declares "
                        f"{field}={declared!r} but the v1 runtime only executes "
                        f"{field}={supported!r} - declaring an unimplemented "
                        "value fails closed; ship the field value, runtime "
                        "implementation, decision/finding semantics and tests "
                        "TOGETHER (CR-3.2 audit 20260901 section 3)"
                    )
                    raise CanonicalRunnerError(msg)
            if policy.allowed_fallback_providers:
                msg = (
                    f"source policy for {policy.domain} declares fallback providers "
                    "but the runtime implements no fallback selection path - "
                    "declaring an unimplemented value fails closed"
                )
                raise CanonicalRunnerError(msg)
            if policy.partial_run_allowed:
                msg = (
                    f"source policy for {policy.domain} allows PARTIAL CR-2 runs "
                    "but the runtime consumes SUCCESS runs only - declaring an "
                    "unimplemented value fails closed"
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
            "mapper_code_hash, normalized_manifest_uri, normalized_manifest_hash, "
            "normalized_output_set_hash, normalized_semantic_hash, status "
            "FROM meta_provider_normalization_run "
            "WHERE provider = 'amazingdata' AND normalization_surface = ? "
            "AND provider_dataset IN (" + ",".join("?" * len(provider_datasets)) + ") "
            "AND status = 'SUCCESS' ORDER BY normalization_run_id",
            [normalization_surface, *provider_datasets],
        ).fetchall()
        columns = (
            "normalization_run_id",
            "provider",
            "normalization_surface",
            "provider_dataset",
            "endpoint",
            "raw_request_id",
            "raw_evidence_uri",
            "raw_evidence_hash",
            "normalization_contract_version",
            "mapper_identity",
            "mapper_code_hash",
            "normalized_manifest_uri",
            "normalized_manifest_hash",
            "normalized_output_set_hash",
            "normalized_semantic_hash",
            "status",
        )
        return [dict(zip(columns, row, strict=True)) for row in rows]

    # --------------------------------------------------------- candidates
    def _build_candidates(
        self, domain: str, run_snapshot: SnapshotRun, bridge: IdentityBridge
    ) -> list[dict[str, Any]]:
        """Deterministic candidates from ONE materialized snapshot run:
        each row of the domain's output with its availability (the
        anchored received_at sealed on the snapshot), identity and
        lineage. Rows come from the EXACT verified bytes materialized
        inside the snapshot - never from a current-path reread."""
        spec = domain_spec(domain)
        seal = run_snapshot.seal
        received_at = _parse_ts(seal.received_at)
        available_at = derive_available_at(domain, received_at)
        output = run_snapshot.output(spec.output_name)
        if output is None:
            return []
        candidates: list[dict[str, Any]] = []
        for ordinal, row_items in enumerate(output.rows):
            row = dict(row_items)
            row_identity = hashlib.sha256(_canonical_json(row).encode("utf-8")).hexdigest()
            if domain == "trade_calendar":
                # one CR-2 calendar row carries the whole market's days;
                # expand to one candidate per (market, trade_date)
                trading_days = row.get("trading_days") or ()
                for day in trading_days:
                    trade_date = _as_date(day)
                    key = (str(row.get("market")), trade_date.isoformat())
                    candidates.append(
                        self._candidate(
                            domain,
                            spec,
                            seal,
                            output,
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
                    seal,
                    output,
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
        seal: InputRunSeal,
        output: MaterializedOutput,
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
            "provider": seal.provider,
            "seal": seal,
            "output_name": spec.output_name,
            "output": output,
            "ordinal": ordinal,
            "row_identity": row_identity,
            "available_at": available_at,
            "received_at": received_at,
            "run_manifest_hash": seal.normalized_manifest_hash,
        }

    def _select(
        self, domain: str, policy: Any, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[CanonicalFinding]]:
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
        findings: list[CanonicalFinding] = []
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
                            f"{winner['seal'].run_id[:12]}",
                        )
                    )
                else:
                    findings.append(
                        _finding(
                            domain,
                            winner["key_json"],
                            "SOURCE_CONFLICT",
                            other["provider"],
                            other["seal"].run_id,
                            {
                                "winner_run": winner["seal"].run_id,
                                "winner_values": winner["payload"],
                                "conflicting_run": other["seal"].run_id,
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
            marker = (candidate["seal"].run_id, candidate["key_json"])
            if marker in seen:
                findings.append(
                    _finding(
                        domain,
                        candidate["key_json"],
                        "DUPLICATE_CANONICAL_KEY",
                        candidate["provider"],
                        candidate["seal"].run_id,
                        {"output_name": candidate["output_name"]},
                        blocking=True,
                    )
                )
            else:
                seen.add(marker)
        return selected, decisions, findings

    # ------------------------------------------------------------ helpers
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
        seal: InputRunSeal = candidate["seal"]
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
                "source_normalization_run_id": seal.run_id,
                "source_output_name": candidate["output_name"],
                "source_row_ordinal": candidate["ordinal"],
                "source_row_identity_hash": candidate["row_identity"],
                "source_raw_request_id": seal.raw_request_id,
                "source_raw_evidence_hash": seal.raw_evidence_hash,
                "source_mapper_identity": seal.mapper_identity,
                "source_policy_version": _source_policy.source_policy_version(),
                "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
            }
        )
        return row

    @staticmethod
    def _decision(
        domain: str, candidate: dict[str, Any], decision_class: str, reason: str
    ) -> dict[str, Any]:
        seal: InputRunSeal = candidate["seal"]
        return {
            "canonical_domain": domain,
            "canonical_key": candidate["key_json"],
            "decision_class": decision_class,
            "provider": candidate["provider"],
            "source_normalization_run_id": seal.run_id,
            "source_row_ordinal": candidate["ordinal"],
            "available_at": candidate["available_at"].isoformat(),
            "reason": reason,
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

    def _verify_findings_truth(
        self, record: dict[str, Any], manifest: dict[str, Any]
    ) -> tuple[str, list[str]]:
        """CR-3.5 P0-02: the exact sealed findings truth is the ONLY
        basis of the canonical run status - ``any blocking finding ->
        BLOCKED, otherwise SUCCESS`` - and of the derived error text.
        The findings are verified three-way (DB rows == findings
        parquet == finding_set_hash seal) and the status/error are
        then RECOMPUTED from that truth and consumed AGAINST the
        ledger/manifest status/error fields. Shared by the replay
        closure verifier AND the historical continuity seal verifier
        (the live build derives through the same
        ``_status_error_from_findings`` helper) - a status rebind that
        does not replay the sealed findings truth is DAMAGED."""
        problems: list[str] = []
        run_id = str(record["canonical_run_id"])
        db_rows = self.conn.execute(
            "SELECT finding_id, canonical_domain, canonical_key, finding_class, "
            "provider, source_normalization_run_id, detail_json, blocking "
            "FROM meta_canonical_reconciliation_finding WHERE canonical_run_id = ? "
            "ORDER BY finding_id",
            [run_id],
        ).fetchall()
        if len(db_rows) != int(record["finding_count"]):
            problems.append(
                f"finding count mismatch: ledger {int(record['finding_count'])} vs {len(db_rows)}"
            )
        db_findings = [dict(zip(_FINDING_SEMANTIC_FIELDS, r[1:], strict=True)) for r in db_rows]
        db_finding_ids = [str(r[0]) for r in db_rows]
        if _finding_set_hash(db_findings) != str(record["finding_set_hash"]):
            problems.append("DB finding exact-set seal mismatch (tampered or missing rows)")
        if str(manifest.get("finding_set_hash")) != str(record["finding_set_hash"]):
            problems.append("manifest finding_set_hash does not match the ledger seal")
        if int(manifest.get("finding_count", -1)) != int(record["finding_count"]):
            problems.append("manifest finding_count does not match the ledger")
        artifacts = manifest.get("artifacts")
        entry = artifacts.get("findings") if isinstance(artifacts, dict) else None
        if not isinstance(entry, dict):
            problems.append("manifest carries no findings artifact seal")
        else:
            expected_uri = self._expected_artifact_uri(record, "findings")
            if str(entry.get("uri")) != expected_uri:
                problems.append("findings artifact uri is not the deterministic recompute")
            path = self.normalized_root / str(entry.get("uri"))
            if not path.is_file():
                problems.append(f"findings artifact missing: {entry.get('uri')}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != str(entry.get("content_hash")):
                problems.append("findings artifact bytes tampered")
            else:
                frame = pl.read_parquet(path)
                if frame.height != int(entry.get("row_count", -1)):
                    problems.append("findings artifact row count mismatch")
                parquet_rows = frame.to_dicts()
                parquet_ids = sorted(str(r.get("finding_id")) for r in parquet_rows)
                if parquet_ids != sorted(db_finding_ids):
                    problems.append("findings parquet ids diverge from the DB finding set")
                parquet_semantic = [
                    {field: r.get(field) for field in _FINDING_SEMANTIC_FIELDS}
                    for r in parquet_rows
                ]
                if _finding_set_hash(parquet_semantic) != str(record["finding_set_hash"]):
                    problems.append("findings parquet semantic set diverges from the seal")
        status_recompute, error_recompute = _status_error_from_findings(db_findings)
        if status_recompute != str(record["status"]):
            problems.append(
                f"status does not match the sealed findings truth: ledger "
                f"{record['status']!r} vs recomputed {status_recompute!r}"
            )
        ledger_error = record["error_message"]
        ledger_error = str(ledger_error) if ledger_error not in (None, "") else None
        if error_recompute != ledger_error:
            problems.append("error_message does not match the sealed findings truth")
        return status_recompute, problems

    def _verify_closure(
        self, record: dict[str, Any], snapshot: CanonicalInputSnapshot
    ) -> list[str]:
        """CR-3.2 P0-04: the FULL typed seal is consumed on every replay
        - CURRENT snapshot identities == ledger == manifest ==
        replay-time physical recompute, with every explicit manifest
        provenance field compared (not display-only), the deterministic
        manifest URI verified, the typed full CR-2 input seal verified
        field-by-field against the physical artifacts, and every sealed
        input run's closure + anchored availability evidence
        re-verified."""
        problems: list[str] = []
        manifest_uri = record["manifest_uri"]
        manifest_hash = record["manifest_hash"]
        if not manifest_uri or not manifest_hash:
            return ["ledger row carries no manifest binding"]
        # deterministic manifest anchor URI (P0-04 section 4.3)
        expected_manifest_uri = f"{self._expected_base_uri(record)}/manifest.json"
        if str(manifest_uri) != expected_manifest_uri:
            return [
                f"ledger manifest_uri {manifest_uri!r} is not the deterministic "
                f"anchor {expected_manifest_uri!r}"
            ]
        manifest_path = self.normalized_root / str(manifest_uri)
        if not manifest_path.is_file():
            return [f"canonical manifest missing: {manifest_uri}"]
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != str(manifest_hash):
            return [f"canonical manifest bytes do not match the ledger hash: {manifest_uri}"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # ---- CURRENT provenance == ledger (defense in depth)
        expected_provenance = (
            ("requested_domains_json", snapshot.requested_domains_json),
            ("requested_domains_hash", snapshot.requested_domains_hash),
            ("input_set_hash", snapshot.input_set_hash),
            ("identity_dataset_hash", snapshot.identity_dataset_hash),
            ("identity_master_input_set_hash", snapshot.master_input_set_hash),
            ("base_identity_hash", snapshot.base_identity_hash),
            ("verification_state_hash", snapshot.verification_state_hash),
            ("input_seal_hash", snapshot.input_seal_hash),
            ("canonical_context_hash", snapshot.canonical_context_hash),
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
            ("input_seal_hash", str(record["input_seal_hash"])),
            # CR-3.4 P0-03: the manifest correctness identity fields are
            # CONSUMED on replay (manifest == ledger == current
            # recompute via expected_provenance above) - no
            # display-only seal
            ("canonical_context_hash", str(record["canonical_context_hash"])),
            ("base_identity_hash", str(record["base_identity_hash"])),
            ("verification_state_hash", str(record["verification_state_hash"])),
            ("identity_dataset_hash", str(record["identity_dataset_hash"])),
            ("identity_master_input_set_hash", str(record["identity_master_input_set_hash"])),
            ("identity_bridge_policy_version", _identity.identity_bridge_policy_version()),
            ("identity_bridge_policy_hash", _identity.identity_bridge_policy_hash()),
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
        # CR-3.2 P0-04: the EXPLICIT provenance maps are consumed, not
        # display-only - required_evidence_classes must equal the
        # CURRENT declared policy exactly
        if manifest.get("required_evidence_classes") != {
            p.domain: p.required_evidence_class for p in _source_policy.source_policies()
        }:
            problems.append("manifest required_evidence_classes diverge from the current policy")

        # ---- typed full input seal: manifest entries == CURRENT snapshot
        sealed_entries = manifest.get("input_normalized_runs", [])
        current_entries = [seal.as_dict() for seal in snapshot.seals]
        if _canonical_json(sealed_entries) != _canonical_json(current_entries):
            problems.append("manifest typed input seal does not match the current snapshot")

        # ---- CR-3.5 P0-02: derived run identity physical closure -
        # ledger == physical recompute from the manifest entries +
        # primitive request-world fields (current == ledger via
        # expected_provenance above; manifest == ledger via the typed
        # seal above; the recompute closes the third side).
        problems.extend(
            _derived_run_identity_problems(
                entries=sealed_entries,
                requested_domains=json.loads(str(record["requested_domains_json"])),
                as_of=_ledger_as_of(record).isoformat(),
                ledger=record,
                manifest=manifest,
            )
        )

        # ---- CR-3.6 P0-02: shared canonical artifact closure verifier
        # (the SAME read-only verifier the historical continuity path
        # consumes for same-world rows - no second weaker copy).
        problems.extend(self._verify_canonical_artifacts(record, manifest))

        # ---- findings truth + status semantic recompute (CR-3.5 P0-02):
        # DB == findings parquet == finding_set_hash seal, and the
        # status/error recomputed from that exact truth against the
        # ledger fields (a status rebind that does not replay the
        # sealed findings truth is DAMAGED).
        _, finding_problems = self._verify_findings_truth(record, manifest)
        problems.extend(finding_problems)

        # ---- re-verify every sealed input run: typed seal vs physical
        # artifacts + anchored evidence (symmetric with first consume)
        for entry in sealed_entries:
            entry_problems = self._verify_sealed_input(entry, snapshot.as_of)
            if entry_problems:
                problems.append(
                    f"sealed CR-2 input run {entry.get('run_id')} is no longer "
                    f"intact: {'; '.join(entry_problems)}"
                )
        return problems

    def _verify_canonical_artifacts(
        self, record: dict[str, Any], manifest: dict[str, Any]
    ) -> list[str]:
        """CR-3.6 P0-02: the ONE shared read-only canonical ARTIFACT
        closure verifier - the artifact exact set (selected /
        decisions / findings), the deterministic artifact URIs, the
        physical content hashes / row counts / schema hashes, and the
        selected / decision semantic seals. Consumed by BOTH the exact
        replay closure verifier (``_verify_closure``) and the
        historical continuity path for every same-world row - a
        same-world prior SUCCESS whose OWN selected / decisions
        artifacts are damaged can never be laundered into a new
        superset run, and a genuine historical BLOCKED must keep its
        recorded evidence internally intact before it may be
        classified as genuine. The findings artifact's DB / parquet /
        seal three-way truth and the status recompute live in the
        shared ``_verify_findings_truth``."""
        problems: list[str] = []
        if int(manifest.get("selected_count", -1)) != int(record["selected_count"]):
            problems.append("manifest selected_count does not match the ledger")
        if int(manifest.get("decision_count", -1)) != int(record["decision_count"]):
            problems.append("manifest decision_count does not match the ledger")
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
        return problems

    def _verify_sealed_input(self, entry: dict[str, Any], as_of_dt: datetime) -> list[str]:
        """Seal-based verification of ONE sealed input run (CR-3.2 P0-04
        + CR-3.3 P0-02 + CR-3.4 P0-02). For a HEALTHY sealed input the
        physical artifacts are checked against the typed seal (manifest
        bytes / output content+schema+row-count / the CR-2 manifest's own
        seal fields / raw meta + anchor) and the input must STILL be
        healthy. For an INVALID sealed input (a BLOCKED run's recorded
        failure) the replay runs the SAME shared verification evidence
        collector as the first consume - including the exact-byte
        materialization verification whenever closure + anchor are
        currently healthy - and the collected problem-evidence hash
        must equal the sealed verification_problem_hash: the exact same
        failure replays, a changed cause does not (it produced a
        different run identity upstream and never reaches this
        branch)."""
        problems: list[str] = []
        run_row = {
            "normalization_run_id": str(entry.get("run_id")),
            "provider": str(entry.get("provider")),
            "normalization_surface": str(entry.get("normalization_surface")),
            "provider_dataset": str(entry.get("provider_dataset")),
            "endpoint": str(entry.get("endpoint")),
            "raw_request_id": str(entry.get("raw_request_id")),
            "raw_evidence_uri": str(entry.get("raw_evidence_uri")),
            "raw_evidence_hash": str(entry.get("raw_evidence_hash")),
            "normalization_contract_version": str(entry.get("normalization_contract_version")),
            "mapper_identity": str(entry.get("mapper_identity")),
            "mapper_code_hash": str(entry.get("mapper_code_hash")),
            "normalized_manifest_uri": str(entry.get("normalized_manifest_uri")),
            "normalized_manifest_hash": str(entry.get("normalized_manifest_hash")),
            "normalized_output_set_hash": str(entry.get("normalized_output_set_hash")),
            "normalized_semantic_hash": str(entry.get("normalized_semantic_hash")),
            "status": str(entry.get("status")),
        }
        sealed_verification = str(entry.get("verification", "HEALTHY"))
        if sealed_verification != "HEALTHY":
            # CR-3.4 P0-02: the replay runs the SAME evidence collector
            # as the first consume - a materialization-only failure
            # (closure + anchor healthy, exact-byte materialization
            # damaged) is rebuilt exactly instead of being
            # short-circuited to a contradictory empty problem set.
            evidence = self._collect_input_verification_evidence(
                run_row,
                str(entry.get("role", "source")),
                as_of_dt,
                keep_rows=False,
            )
            if evidence.verification_problem_hash != str(entry.get("verification_problem_hash")):
                problems.append(
                    "sealed failure evidence no longer matches the current "
                    "problem set (verification evidence drift)"
                )
            return problems
        anchor_problems, _ = self._verify_anchored_availability(run_row)
        problems.extend(anchor_problems)

        manifest_uri = str(entry.get("normalized_manifest_uri"))
        manifest_path = self.normalized_root / manifest_uri
        if not manifest_path.is_file():
            problems.append(f"normalized manifest missing: {manifest_uri}")
            return problems
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != str(entry.get("normalized_manifest_hash")):
            problems.append("normalized manifest bytes do not match the sealed hash")
            return problems
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            problems.append(f"normalized manifest unreadable: {exc}")
            return problems
        # the manifest's own CR-2 seal fields == the typed input seal
        for manifest_field, seal_field in (
            ("normalization_contract_version", "normalization_contract_version"),
            ("mapper_identity", "mapper_identity"),
            ("mapper_code_hash", "mapper_code_hash"),
            ("output_set_hash", "normalized_output_set_hash"),
            ("semantic_hash", "normalized_semantic_hash"),
        ):
            if str(manifest.get(manifest_field)) != str(entry.get(seal_field)):
                problems.append(
                    f"CR-2 manifest {manifest_field} diverges from the typed input seal"
                )
        for output in manifest.get("outputs", []):
            uri = str(output.get("uri"))
            path = self.normalized_root / uri
            if not path.is_file():
                problems.append(f"output artifact missing: {uri}")
                continue
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != str(output.get("content_hash")):
                problems.append(f"output artifact bytes tampered: {uri}")
                continue
            frame = pl.read_parquet(path)
            if frame.height != int(output.get("row_count", -1)):
                problems.append(f"output artifact row count mismatch: {uri}")
            schema_hash = hashlib.sha256(str(frame.schema).encode("utf-8")).hexdigest()
            if schema_hash != str(output.get("schema_hash")):
                problems.append(f"output artifact schema mismatch: {uri}")
        return problems

    def _expected_artifact_uri(self, record: dict[str, Any], name: str) -> str:
        return f"{self._expected_base_uri(record)}/{name}.parquet"

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
        findings: list[CanonicalFinding],
        status: str,
    ) -> tuple[str | None, str | None, str, str, str]:
        """Deterministic correctness artifacts. NO wall-clock anywhere
        (findings carry no created_at in the parquet - the DB-side
        created_at is transaction-time audit metadata bound only at
        commit), so a DB failure after the file writes recovers on the
        exact retry with byte-identical files."""
        base_uri = (
            f"canonical/contract={CANONICAL_CONTRACT_VERSION}/"
            f"as_of={snapshot.as_of.strftime('%Y%m%dT%H%M%SZ')}/run={run_id}"
        )
        base_path = self.normalized_root / base_uri
        base_path.mkdir(parents=True, exist_ok=True)

        finding_dicts = [f.as_dict() for f in findings]
        for position, finding_dict in enumerate(finding_dicts):
            finding_dict["finding_id"] = (
                f"cf-{uuid.uuid5(_FINDING_NAMESPACE, f'{run_id}:{position}')}"
            )
            finding_dict["canonical_run_id"] = run_id
        finding_seal = _finding_set_hash(finding_dicts)
        # CR-4 implementation finding (CR-3 latent defect, declared for
        # Reviewer adjudication in the CR-4 batch): the semantic seals
        # are computed over the SCHEMA-ALIGNED rows - the exact rows
        # written to the parquet artifacts - so the replay verifier's
        # recompute from the parquet can never diverge on multi-domain
        # runs (single-domain behavior is byte-identical: aligning rows
        # whose key sets already agree is a no-op).
        aligned_selected = _align_schema(selected_rows)
        aligned_decisions = _align_schema(decisions)
        selected_semantic = _rows_semantic_hash(aligned_selected)
        decision_set = _rows_semantic_hash(aligned_decisions)

        import io

        artifacts: dict[str, dict[str, Any]] = {}
        parquet_rows = {
            "selected": aligned_selected,
            "decisions": aligned_decisions,
            # findings parquet: deterministic fields ONLY (no created_at)
            "findings": _align_schema(
                [
                    {
                        "finding_id": f_dict["finding_id"],
                        "canonical_run_id": f_dict["canonical_run_id"],
                        **{field: f_dict.get(field) for field in _FINDING_SEMANTIC_FIELDS},
                    }
                    for f_dict in finding_dicts
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
            "input_normalized_runs": [seal.as_dict() for seal in snapshot.seals],
            "input_set_hash": snapshot.input_set_hash,
            "input_seal_hash": snapshot.input_seal_hash,
            "canonical_context_hash": snapshot.canonical_context_hash,
            "base_identity_hash": snapshot.base_identity_hash,
            "verification_state_hash": snapshot.verification_state_hash,
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
        findings: list[CanonicalFinding],
        finding_seal: str,
        status: str,
        error: str | None,
        started: datetime,
        completed: datetime,
    ) -> None:
        """One DuckDB transaction: dup check + run INSERT + full finding
        set + count assertion. A failure rolls everything back; the
        deterministic file-side anchor lets the exact retry recover."""
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
                    snapshot.base_identity_hash,
                    snapshot.verification_state_hash,
                    snapshot.input_seal_hash,
                    snapshot.master_input_set_hash,
                    snapshot.canonical_context_hash,
                ],
            )
            # transaction-time audit metadata ONLY (never part of the
            # deterministic correctness bytes)
            now = datetime.now(UTC)
            for position, finding in enumerate(findings):
                f_dict = finding.as_dict()
                finding_id = f"cf-{uuid.uuid5(_FINDING_NAMESPACE, f'{run_id}:{position}')}"
                self.conn.execute(
                    f"INSERT INTO meta_canonical_reconciliation_finding "
                    f"({', '.join(_FINDING_COLUMNS)}) VALUES "
                    f"({', '.join(['?'] * len(_FINDING_COLUMNS))})",
                    [
                        finding_id,
                        run_id,
                        f_dict["canonical_domain"],
                        f_dict["canonical_key"],
                        f_dict["finding_class"],
                        f_dict["provider"],
                        f_dict["source_normalization_run_id"],
                        f_dict["detail_json"],
                        bool(f_dict["blocking"]),
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
