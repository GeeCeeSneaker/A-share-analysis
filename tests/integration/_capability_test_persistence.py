"""TEST-ONLY capability approval mechanics (R4-B1.2, audit 20260830
Option A).

R4-B1.2 P0-01 removed the test-only approval helpers from the
PRODUCTION module (``src/ashare_state/providers/amazingdata/
capability.py``): Python's ``_name`` convention is not access control,
and any helper there that writes APPROVED from a caller-built
``CapabilityEvidence`` is a structural bypass.

These helpers replicate the evidence-validation / DB-transaction /
cache-rebuild MECHANICS so tests can exercise them without fabricating
an entire formal spike run. They live in tests/ - importing them from
production code is impossible because production code does not import
test modules (and the R4-B1.2 structural guard asserts these names do
not exist in the production module at all).

IMPORTANT: these helpers are NOT an approval path. They perform the
same ``_validate_evidence`` rejection logic (including the positive
frozen production identity) but deliberately skip the formal-run
chain - that is precisely why they must live outside src/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

    from ashare_state.providers.amazingdata.capability import (
        Capability,
        CapabilityEvidence,
    )


def approve_in_memory_testonly(name: str, evidence: CapabilityEvidence) -> Capability:
    """In-memory approval with FULL evidence bundle (registry
    mechanics only - NOT a production path)."""
    from ashare_state.providers.amazingdata import capability as cap

    cap._validate_evidence(name, evidence)
    original = cap.CAPABILITY_REGISTRY[name]
    approved = cap.Capability(
        name=original.name,
        sdk_methods=original.sdk_methods,
        canonical_domains=original.canonical_domains,
        status=cap.CapabilityStatus.APPROVED,
        verified_at=evidence.approved_at,
        account_profile_id=evidence.account_profile_id,
    )
    cap.CAPABILITY_REGISTRY[name] = approved
    return approved


def approve_and_persist_testonly(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    evidence: CapabilityEvidence,
) -> Capability:
    """Persisted approval from a caller-built evidence bundle
    (transaction/cache mechanics only - NOT a production path).

    Replicates the R3-P1-05 validate-before-mutate / single-transaction
    / post-commit cache-rebuild semantics that
    ``approve_from_spike_run`` implements inline."""
    from ashare_state.providers.amazingdata import capability as cap

    cap._validate_evidence(name, evidence)
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
        cap.load_approvals(conn)
        raise
    cap.load_approvals(conn)
    return cap.CAPABILITY_REGISTRY[name]
