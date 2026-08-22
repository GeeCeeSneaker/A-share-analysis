"""Provider capability registry (task book sections 3.1 / 10, audit P1-03).

Discipline: an AmazingData capability that has not passed the REAL-account
Spike may only ever be CANDIDATE. Approval flow:
    real account -> spike -> golden -> provider verification ->
    source-policy dry-run -> APPROVED

Audit P1-03: meta_provider_capability (migration 007 columns) is the
AUTHORITATIVE state; the in-memory registry is a session cache synced
explicitly via load_approvals()/persist_approval().
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection


class CapabilityStatus(StrEnum):
    CANDIDATE = "CANDIDATE"  # API surface exists; data NOT yet verified
    APPROVED = "APPROVED"  # real-account spike + golden passed
    RETIRED = "RETIRED"  # deprecated / replaced by another endpoint


@dataclass(frozen=True)
class CapabilityEvidence:
    """Mandatory bundle for APPROVED (audit P1-03)."""

    spike_report_ref: str
    provider_verification_ref: str
    golden_case_refs: tuple[str, ...]
    dry_run_ref: str
    approved_by: str
    approved_at: str
    account_profile_id: str


class CapabilityGovernanceError(RuntimeError):
    """Illegal capability governance transition / incomplete evidence."""


@dataclass(frozen=True)
class Capability:
    name: str  # e.g. "security_master"
    sdk_methods: tuple[str, ...]
    canonical_domains: tuple[str, ...]  # fact domains this capability feeds
    status: CapabilityStatus = CapabilityStatus.CANDIDATE
    verified_at: str | None = None  # set only on APPROVED
    account_profile_id: str | None = None  # which account verified it


# Registry seeded from the 2026-08-21 manual + smoke evidence.
# EVERYTHING is CANDIDATE until the production-account Spike (task book 21.1).
CAPABILITY_REGISTRY: dict[str, Capability] = {
    cap.name: cap
    for cap in [
        Capability(
            name="trade_calendar",
            sdk_methods=("BaseData.get_calendar",),
            canonical_domains=("fact_trade_calendar",),
        ),
        Capability(
            name="security_master",
            sdk_methods=(
                "BaseData.get_code_list",
                "BaseData.get_hist_code_list",
                "InfoData.get_stock_basic",
            ),
            canonical_domains=("dim_security", "bridge_security_provider_symbol"),
        ),
        Capability(
            name="code_mapping_bj",
            sdk_methods=("InfoData.get_bj_code_mapping",),
            canonical_domains=("bridge_security_provider_symbol",),
        ),
        Capability(
            name="daily_bar",
            sdk_methods=("MarketData.query_kline",),
            canonical_domains=("fact_daily_bar",),
        ),
        Capability(
            name="security_status_history",
            sdk_methods=("InfoData.get_history_stock_status",),
            # task book 1.3: one endpoint, THREE fact domains - never merged
            canonical_domains=(
                "fact_security_status_daily",
                "fact_limit_price",
                "fact_corporate_action",
            ),
        ),
        Capability(
            name="adj_factor",
            sdk_methods=("BaseData.get_adj_factor", "BaseData.get_backward_factor"),
            canonical_domains=("fact_adj_factor",),
        ),
        Capability(
            name="corporate_action",
            sdk_methods=("InfoData.get_dividend", "InfoData.get_right_issue"),
            canonical_domains=("fact_corporate_action",),
        ),
        Capability(
            name="equity_structure",
            sdk_methods=("InfoData.get_equity_structure",),
            canonical_domains=("fact_equity_structure",),  # B6 assessment
        ),
        Capability(
            name="industry_taxonomy",
            sdk_methods=(
                "InfoData.get_industry_base_info",
                "InfoData.get_industry_constituent",
                "InfoData.get_industry_weight",
                "InfoData.get_industry_daily",
            ),
            canonical_domains=("bridge_industry_member",),
        ),
        Capability(
            name="index_daily",
            sdk_methods=("InfoData.get_index_daily", "MarketData.query_kline"),
            canonical_domains=("fact_index_daily",),
        ),
    ]
}


def capability_status(name: str) -> CapabilityStatus:
    cap = CAPABILITY_REGISTRY.get(name)
    if cap is None:
        msg = f"unknown capability {name!r}; registered: {sorted(CAPABILITY_REGISTRY)}"
        raise KeyError(msg)
    return cap.status


def approve_capability(name: str, evidence: CapabilityEvidence) -> Capability:
    """In-memory approval with FULL evidence bundle (audit P1-03).

    Persistence to the authoritative table happens via persist_approval().
    """
    cap = CAPABILITY_REGISTRY[name]
    missing = [
        field
        for field, value in (
            ("spike_report_ref", evidence.spike_report_ref),
            ("provider_verification_ref", evidence.provider_verification_ref),
            ("golden_case_refs", evidence.golden_case_refs),
            ("dry_run_ref", evidence.dry_run_ref),
            ("approved_by", evidence.approved_by),
            ("approved_at", evidence.approved_at),
            ("account_profile_id", evidence.account_profile_id),
        )
        if not value
    ]
    if missing:
        msg = (
            f"capability approval evidence incomplete for {name!r}; "
            f"missing: {missing} (audit P1-03: real spike + golden + "
            "verification + dry-run + account profile required)"
        )
        raise CapabilityGovernanceError(msg)
    if cap.status is CapabilityStatus.RETIRED:
        msg = f"capability {name!r} is RETIRED; approval refused"
        raise CapabilityGovernanceError(msg)
    approved = Capability(
        name=cap.name,
        sdk_methods=cap.sdk_methods,
        canonical_domains=cap.canonical_domains,
        status=CapabilityStatus.APPROVED,
        verified_at=evidence.approved_at,
        account_profile_id=evidence.account_profile_id,
    )
    CAPABILITY_REGISTRY[name] = approved
    return approved


# ------------------------------------------ persistence (P1-03 / R2-P1-01)


def approve_and_persist_capability(
    conn: DuckDBPyConnection,
    name: str,
    evidence: CapabilityEvidence,
) -> Capability:
    """The ONLY public approval path (audit R2-P1-01).

    One transaction: validate evidence -> UPSERT governance fields only
    (existing metadata columns are preserved) -> COMMIT -> reload the
    registry from the DB, so memory and the authoritative table can never
    disagree. Broken evidence raises BEFORE any write; a failed write
    ROLLBACKs and restores the cache from the DB.
    """
    # validate FIRST (raises before any write)
    approve_capability(name, evidence)
    existing = conn.execute(
        "SELECT 1 FROM meta_provider_capability WHERE provider = 'amazingdata' AND capability = ?",
        [name],
    ).fetchone()
    conn.execute("BEGIN TRANSACTION")
    try:
        if existing is None:
            conn.execute(
                "INSERT INTO meta_provider_capability "
                "(provider, capability, status, spike_report_ref, "
                "provider_verification_ref, golden_case_refs, dry_run_ref, "
                "account_profile_id, approved_by, adapter_version, verified_at) "
                "VALUES ('amazingdata', ?, 'APPROVED', ?, ?, ?, ?, ?, ?, NULL, ?)",
                [
                    name,
                    evidence.spike_report_ref,
                    evidence.provider_verification_ref,
                    ",".join(evidence.golden_case_refs),
                    evidence.dry_run_ref,
                    evidence.account_profile_id,
                    evidence.approved_by,
                    evidence.approved_at,
                ],
            )
        else:
            # R2-P1-01 12.3: UPDATE touches ONLY governance fields -
            # existing metadata columns can never be erased
            conn.execute(
                "UPDATE meta_provider_capability SET status = 'APPROVED', "
                "spike_report_ref = ?, provider_verification_ref = ?, "
                "golden_case_refs = ?, dry_run_ref = ?, account_profile_id = ?, "
                "approved_by = ?, verified_at = ? "
                "WHERE provider = 'amazingdata' AND capability = ?",
                [
                    evidence.spike_report_ref,
                    evidence.provider_verification_ref,
                    ",".join(evidence.golden_case_refs),
                    evidence.dry_run_ref,
                    evidence.account_profile_id,
                    evidence.approved_by,
                    evidence.approved_at,
                    name,
                ],
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        # memory was mutated by approve_capability above -> restore from
        # the authoritative DB so cache never says APPROVED while DB
        # does not (R2-P1-01 12.2)
        load_approvals(conn)
        raise
    # post-commit: rebuild the cache from the authoritative table
    load_approvals(conn)
    return CAPABILITY_REGISTRY[name]


def load_approvals(conn: DuckDBPyConnection) -> dict[str, CapabilityStatus]:
    """Sync the in-memory registry from the authoritative table.

    Full sync semantics (audit R2-P1-01 12.4):
    - restores complete provenance (verified_at / account_profile_id)
    - DB status OVERRIDES the cached state in BOTH directions: a DB
      CANDIDATE row actively demotes a stale cached APPROVED.
    """
    rows = conn.execute(
        "SELECT capability, status, verified_at, account_profile_id "
        "FROM meta_provider_capability WHERE provider = 'amazingdata'"
    ).fetchall()
    loaded: dict[str, CapabilityStatus] = {}
    for capability, status, verified_at, account_profile_id in rows:
        key = str(capability)
        try:
            db_status = CapabilityStatus(str(status))
        except ValueError:
            # unknown status literal in db: fail safe to CANDIDATE
            db_status = CapabilityStatus.CANDIDATE
        loaded[key] = db_status
        cap = CAPABILITY_REGISTRY.get(key)
        if cap is not None:
            # unconditional override: DB is authoritative, cache is cache
            CAPABILITY_REGISTRY[key] = Capability(
                name=cap.name,
                sdk_methods=cap.sdk_methods,
                canonical_domains=cap.canonical_domains,
                status=db_status,
                verified_at=str(verified_at) if verified_at else cap.verified_at,
                account_profile_id=str(account_profile_id)
                if account_profile_id
                else cap.account_profile_id,
            )
    return loaded
