"""Exact Endpoint Requirement Proof tests (R4-B1, audit 20260828).

The audit finding: the formal ENDPOINT gate's probe was a
capability-chosen call - a stand-in endpoint (``get_stock_basic``
proving ``industry_taxonomy``; a calendar probe proving ``daily_bar``)
could mark the gate PASS, and approval consumed only case-id naming.

B1 fixes this with the Endpoint Requirement Contract
(``providers.amazingdata.endpoint_requirements``):

- B1-01: the contract is a typed, structurally-validated table covering
  EVERY registered capability (no scattered if/else);
- B1-02: the ENDPOINT gate fires ONE EXACT probe per declared
  requirement; envelope endpoint/dataset mismatch is a blocking FAIL -
  stand-ins can never PASS (tested adversarially below);
- B1-03: permission/endpoint/business separation is preserved;
- B1-04: approval consumes the exact endpoint identity - per-
  requirement proof cases + the hash-anchored REPORT artifact
  re-verification (tamper = fail closed);
- B1-05: the structural guard - registered requirements == formal
  endpoint proof plan coverage (a new capability cannot silently miss
  the boundary).
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from ashare_state.providers.amazingdata.capability import CAPABILITY_REGISTRY
from ashare_state.providers.amazingdata.endpoint_requirements import (
    ENDPOINT_REQUIREMENTS,
    SDK_METHOD_CLASSIFICATIONS,
    EndpointRequirementMode,
    SdkMethodProofClass,
    endpoint_requirement_case_id,
    endpoint_requirements_for,
    sdk_method_classifications_for,
    validate_endpoint_requirements,
)
from ashare_state.providers.amazingdata.provider import RawEnvelope
from ashare_state.providers.errors import ProviderPermissionError
from ashare_state.providers.exchange import ProviderExchange
from ashare_state.providers.runtime_gates import GateKind, GateStatus
from ashare_state.spike.catalog import CaseCatalog
from ashare_state.spike.formal_gates import (
    ENDPOINT_PROBE_SPECS,
    GATE_PLAN_SPECS,
    FormalRuntimeGateExecutor,
    probe_b1_formal_gates,
)
from ashare_state.spike.model import CaseResult, RunKind
from ashare_state.spike.probes import ProbeContext
from ashare_state.spike.runner import new_run
from ashare_state.spike.target import FakeTarget

_SHA = "a" * 40
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


@pytest.fixture
def conn():
    connection = duckdb.connect(":memory:")
    from ashare_state.storage import apply_migrations

    apply_migrations(connection, MIGRATIONS_DIR)
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def _event_gate_relaxed(monkeypatch):
    from ashare_state.spike.golden_store import GoldenTruthStore

    monkeypatch.setattr(GoldenTruthStore, "event_coverage_gate", lambda self: [])
    monkeypatch.setattr(GoldenTruthStore, "review_gate", lambda self: [])


@pytest.fixture(autouse=True)
def _rule_review_gate_relaxed(monkeypatch):
    from ashare_state.spike import trading_rule as rule_module

    monkeypatch.setattr(rule_module, "trading_rule_review_gate", lambda book, **k: [])


def _ctx(tmp_path: Path, target=None, context_cls=ProbeContext) -> ProbeContext:
    run, store = new_run(
        run_kind=RunKind.DRY_RUN,
        spike_root=tmp_path / "spike",
        code_commit=_SHA,
        environment_lock_hash="e" * 64,
        config_hash="c" * 64,
        sdk_version="FAKE-1.1.9",
        runtime_version="FAKE-V4.3.0",
        account_profile_id="TRIAL_SIMULATION_FAKE",
        as_of_date="20260814",
    )
    catalog = CaseCatalog(store, run.spike_run_id)
    return context_cls(run, store, catalog, target or FakeTarget())


def _raw_files(ctx: ProbeContext) -> list[Path]:
    return sorted(ctx.store.raw_dir(ctx.run).rglob("*.meta.json"))


def _case_by_id(ctx: ProbeContext, case_id: str):
    for case in ctx.catalog.cases:
        if case.case_id == case_id:
            return case
    return None


class _StandInEndpointTarget(FakeTarget):
    """A LYING endpoint surface: the requirement's declared endpoint is
    answered by a DIFFERENT endpoint's exchange (the stand-in bug the
    audit describes). For industry_taxonomy: get_industry_base_info
    returns a stock_basic exchange."""

    def get_industry_base_info_exchange(self, code_list: list[str]):
        return super().get_stock_basic_exchange(code_list)


class _DeniedIndustryTarget(FakeTarget):
    """The exact endpoint is REFUSED with a first-class permission
    failure exchange (endpoint identity correct, call denied)."""

    def get_industry_base_info_exchange(self, code_list: list[str]):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="industry_taxonomy",
            endpoint="InfoData.get_industry_base_info",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


class _ConstituentDeniedTarget(FakeTarget):
    """R4-B1.2 (audit 20260830 P0-02): base_info PASSES but the
    CONSTITUENT membership endpoint is DENIED - the
    bridge_industry_member deliverable cannot be built, so the
    endpoint proof must FAIL (proving a representative endpoint !=
    proving the capability's necessary delivery surface)."""

    def get_industry_constituent_exchange(self, code_list: list[str]):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="industry_taxonomy",
            endpoint="InfoData.get_industry_constituent",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


class _DeniedCodeListTarget(FakeTarget):
    """The PERMISSION probe is refused (entitlement denied)."""

    def get_code_list_exchange(self, security_type=None):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="code_list",
            endpoint="BaseData.get_code_list",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


class _SecurityMasterHistDeniedTarget(FakeTarget):
    """R4-B1.1 (audit 20260830 P0-01): the current-snapshot listing
    (get_code_list) is available but the HISTORICAL rebuild
    (get_hist_code_list) is DENIED. security_master is
    security_master_with_delisted - the survivorship requirement makes
    the historical endpoint REQUIRED, so the snapshot alone must NOT
    satisfy the endpoint proof. The shared permission-probe surface
    (EXTRA_STOCK_A) stays available so the block is attributable to
    the ENDPOINT gate."""

    def get_hist_code_list_exchange(self, security_type, start_date, end_date):
        env = RawEnvelope(
            provider="amazingdata",
            provider_dataset="hist_code_list",
            endpoint="BaseData.get_hist_code_list",
            status="ERROR",
            error_class="ProviderPermissionError",
        )
        error = ProviderPermissionError("entitlement denied")
        error.exchange = ProviderExchange(envelope=env, payload=None)
        raise error


@pytest.mark.integration
class TestEndpointRequirementContract:
    """B1-01: the typed contract is structurally valid and covers every
    registered capability."""

    def test_contract_is_structurally_valid(self):
        assert validate_endpoint_requirements() == []

    def test_contract_covers_every_registered_capability(self):
        registry_caps = set(CAPABILITY_REGISTRY)
        contract_caps = {
            r.capability for r in ENDPOINT_REQUIREMENTS if r.proof_role.value == "ENDPOINT_PROOF"
        }
        assert contract_caps == registry_caps

    def test_every_requirement_has_an_exact_probe_factory(self):
        missing = [
            r.requirement_id
            for r in ENDPOINT_REQUIREMENTS
            if r.requirement_id not in ENDPOINT_PROBE_SPECS
        ]
        assert missing == []

    def test_no_extra_probe_specs_beyond_the_contract(self):
        contract_ids = {r.requirement_id for r in ENDPOINT_REQUIREMENTS}
        assert set(ENDPOINT_PROBE_SPECS) == contract_ids

    def test_required_requirements_carry_no_group(self):
        for req in ENDPOINT_REQUIREMENTS:
            if req.mode is EndpointRequirementMode.REQUIRED:
                assert req.group_id is None

    def test_alternative_groups_have_at_least_two_members(self):
        groups: dict[str, list[str]] = {}
        for req in ENDPOINT_REQUIREMENTS:
            if req.mode is EndpointRequirementMode.ALTERNATIVE_GROUP:
                groups.setdefault(req.group_id or "", []).append(req.requirement_id)
        for group_id, members in groups.items():
            assert len(members) >= 2, group_id

    def test_security_master_hist_endpoint_is_required(self):
        """R4-B1.1 (audit 20260830 P0-01): the survivorship requirement
        of security_master_with_delisted makes the HISTORICAL listing
        endpoint REQUIRED - the current-snapshot get_code_list is NOT
        an endpoint requirement (withdrawn 'official alternatives')."""
        reqs = endpoint_requirements_for("security_master")
        assert [r.endpoint for r in reqs] == ["BaseData.get_hist_code_list"]
        assert all(r.mode is EndpointRequirementMode.REQUIRED for r in reqs)

    def test_every_registry_sdk_method_is_explicitly_classified(self):
        """R4-B1.1 (audit 20260830 section 2.3): every registry
        sdk_method has an explicit classification entry - no method may
        be silently present or absent from the proof contract."""
        classified = {(e.capability, e.endpoint) for e in SDK_METHOD_CLASSIFICATIONS}
        registry_pairs = {
            (name, method)
            for name, cap in CAPABILITY_REGISTRY.items()
            for method in cap.sdk_methods
        }
        assert classified == registry_pairs, (
            f"unclassified={sorted(registry_pairs - classified)}, "
            f"stale={sorted(classified - registry_pairs)}"
        )

    def test_adj_factor_backward_factor_is_option_b(self):
        """R4-B1.1 (audit 20260830 section 2.2): the ADR-020 'each
        REQUIRED' overclaim is resolved per Option B - only the
        forward-adjustment endpoint is a requirement; backward factor
        is explicitly OPTIONAL_NON_APPROVAL_SURFACE with a reason."""
        classifications = {e.endpoint: e for e in sdk_method_classifications_for("adj_factor")}
        assert classifications["BaseData.get_adj_factor"].classification is (
            SdkMethodProofClass.REQUIRED_ENDPOINT_PROOF
        )
        assert classifications["BaseData.get_backward_factor"].classification is (
            SdkMethodProofClass.OPTIONAL_NON_APPROVAL_SURFACE
        )
        assert classifications["BaseData.get_backward_factor"].reason
        # the runtime contract agrees with Option B
        assert [r.endpoint for r in endpoint_requirements_for("adj_factor")] == [
            "BaseData.get_adj_factor"
        ]


@pytest.mark.integration
class TestExactEndpointProof:
    """B1-02: one exact probe per requirement; mismatch = blocking FAIL."""

    def test_every_capability_proves_its_exact_endpoint(self, tmp_path: Path):
        """The happy path: all ten capabilities, every requirement's
        probe exchange endpoint MATCHES the declaration - PASS."""
        ctx = _ctx(tmp_path)
        out = probe_b1_formal_gates(ctx)
        assert out["count"] == len(GATE_PLAN_SPECS)
        assert all(v == "PASS" for v in out["capabilities"].values())
        # every requirement has its own proof case, PASS, evidence-bound
        for capability in GATE_PLAN_SPECS:
            for req in endpoint_requirements_for(capability):
                case = _case_by_id(ctx, endpoint_requirement_case_id(req))
                assert case is not None, (capability, req.requirement_id)
                assert case.result is CaseResult.VALIDATED_PASS
                assert case.evidence_ref.endswith(".meta.json")
                assert req.endpoint in case.expected_value

    def test_stand_in_endpoint_is_a_blocking_fail(self, tmp_path: Path):
        """industry_taxonomy answered by a stock_basic exchange: the
        gate FAILS, the proof case is VALIDATED_FAIL, and the mismatch
        is recorded - a stand-in can never mark the gate PASS."""
        ctx = _ctx(tmp_path, target=_StandInEndpointTarget())
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["industry_taxonomy"](ctx))

        assert not bound.report.all_passed
        assert bound.report.early_stopped
        assert bound.report.blocked_by is GateKind.ENDPOINT_AVAILABLE
        endpoint_result = next(
            r for r in bound.report.results if r.kind is GateKind.ENDPOINT_AVAILABLE
        )
        assert endpoint_result.status is GateStatus.FAIL
        assert "endpoint mismatch" in endpoint_result.reason
        req = endpoint_requirements_for("industry_taxonomy")[0]
        outcome = bound.endpoint_outcomes[req.requirement_id]
        assert outcome.status is GateStatus.FAIL
        assert outcome.actual_endpoint == "InfoData.get_stock_basic"
        assert outcome.actual_endpoint != req.endpoint
        # the proof case records the exact mismatch
        case = _case_by_id(ctx, endpoint_requirement_case_id(req))
        assert case is not None
        assert case.result is CaseResult.VALIDATED_FAIL
        assert "actual_endpoint=InfoData.get_stock_basic" in case.actual_value
        # the stand-in exchange itself WAS persisted (failure evidence
        # is still evidence) and the business probe never fired
        assert bound.probes[GateKind.BUSINESS_DATA].fired == 0

    def test_denied_exact_endpoint_is_fail_not_fallback(self, tmp_path: Path):
        """The exact endpoint is permission-denied: the requirement FAILs
        (correct endpoint identity, denied call) - there is NO fallback
        to an unrelated endpoint; the failure exchange is persisted."""
        ctx = _ctx(tmp_path, target=_DeniedIndustryTarget())
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["industry_taxonomy"](ctx))

        assert not bound.report.all_passed
        assert bound.report.blocked_by is GateKind.ENDPOINT_AVAILABLE
        req = endpoint_requirements_for("industry_taxonomy")[0]
        outcome = bound.endpoint_outcomes[req.requirement_id]
        assert outcome.status is GateStatus.FAIL
        assert outcome.actual_endpoint == req.endpoint  # identity correct
        assert "providerpermissionerror" in outcome.reason.lower()
        # the failure exchange is persisted and bound
        assert outcome.binding is not None
        assert outcome.binding.evidence_uri.endswith(".meta.json")

    def test_permission_denial_leaves_endpoint_probes_unfired(self, tmp_path: Path):
        """B1-03: permission/endpoint separation - a denied permission
        probe means ZERO endpoint requirement probes fire."""
        ctx = _ctx(tmp_path, target=_DeniedCodeListTarget())
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["daily_bar"](ctx))

        assert bound.report.blocked_by is GateKind.PERMISSION
        assert all(p.fired == 0 for p in bound.endpoint_probes.values())
        # no requirement case was fabricated
        for req in endpoint_requirements_for("daily_bar"):
            assert _case_by_id(ctx, endpoint_requirement_case_id(req)) is None

    def test_hist_denied_snapshot_available_is_endpoint_fail(self, tmp_path: Path):
        """R4-B1.1 (audit 20260830 P0-01): security_master is
        security_master_with_delisted - with get_code_list PASS but
        get_hist_code_list DENIED, the ENDPOINT gate FAILS (the
        snapshot is a non-approval surface), the pipeline early-stops,
        and the business probe never fires."""
        ctx = _ctx(tmp_path, target=_SecurityMasterHistDeniedTarget())
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["security_master"](ctx))

        assert not bound.report.all_passed
        assert bound.report.early_stopped
        assert bound.report.blocked_by is GateKind.ENDPOINT_AVAILABLE
        endpoint_result = next(
            r for r in bound.report.results if r.kind is GateKind.ENDPOINT_AVAILABLE
        )
        assert endpoint_result.status is GateStatus.FAIL
        assert "get_hist_code_list" in endpoint_result.reason
        # the failure exchange is persisted and the proof case is FAIL
        req = endpoint_requirements_for("security_master")[0]
        assert req.endpoint == "BaseData.get_hist_code_list"
        outcome = bound.endpoint_outcomes[req.requirement_id]
        assert outcome.status is GateStatus.FAIL
        assert outcome.actual_endpoint == req.endpoint
        assert outcome.binding is not None
        case = _case_by_id(ctx, endpoint_requirement_case_id(req))
        assert case is not None
        assert case.result is CaseResult.VALIDATED_FAIL
        # early stop: the business probe (the hist business fetch)
        # never fired - the endpoint gate blocked it first
        assert bound.probes[GateKind.BUSINESS_DATA].fired == 0

    def test_snapshot_alone_can_never_satisfy_the_proof(self, tmp_path: Path):
        """The R4-B1 'official alternatives' grouping, withdrawn
        (audit 20260830 P0-01): a snapshot-only world (hist endpoint
        denied) can NEVER approve security_master - the endpoint proof
        case is VALIDATED_FAIL and the REPORT artifact records the
        honest failure (which the approval cross-binding refuses)."""
        import json

        ctx = _ctx(tmp_path, target=_SecurityMasterHistDeniedTarget())
        out = probe_b1_formal_gates(ctx)
        assert out["capabilities"]["security_master"] == "BLOCKED_BY_ENDPOINT_AVAILABLE"
        req = endpoint_requirements_for("security_master")[0]
        case = _case_by_id(ctx, endpoint_requirement_case_id(req))
        assert case is not None
        assert case.result is CaseResult.VALIDATED_FAIL
        artifact = ctx.store.run_dir(ctx.run) / "gates" / "security_master.json"
        doc = json.loads(artifact.read_text(encoding="utf-8"))
        entry = next(
            e for e in doc["endpoint_requirements"] if e["requirement_id"] == req.requirement_id
        )
        assert entry["status"] == "FAIL"
        assert entry["actual_endpoint"] == req.endpoint


@pytest.mark.integration
class TestIndustryConstituentRequiredSurface:
    """R4-B1.2 P0-02 (audit 20260830): the canonical deliverable of
    industry_taxonomy is bridge_industry_member - security <->
    industry MEMBERSHIP. base_info alone proves the taxonomy
    definition surface; constituent is REQUIRED, so base_info PASS +
    constituent DENIED must FAIL the endpoint proof."""

    def test_base_info_pass_constituent_denied_is_endpoint_fail(self, tmp_path: Path):
        """base_info PASS + constituent DENIED -> ENDPOINT FAIL ->
        early stop -> BUSINESS probe fired == 0; the constituent
        failure exchange is persisted and its proof case is
        VALIDATED_FAIL -> approval impossible."""
        ctx = _ctx(tmp_path, target=_ConstituentDeniedTarget())
        executor = FormalRuntimeGateExecutor(ctx)
        bound = executor.execute(GATE_PLAN_SPECS["industry_taxonomy"](ctx))

        assert not bound.report.all_passed
        assert bound.report.early_stopped
        assert bound.report.blocked_by is GateKind.ENDPOINT_AVAILABLE
        endpoint_result = next(
            r for r in bound.report.results if r.kind is GateKind.ENDPOINT_AVAILABLE
        )
        assert endpoint_result.status is GateStatus.FAIL
        assert "get_industry_constituent" in endpoint_result.reason
        # base_info PASSED, constituent FAILED
        outcomes = {
            req.requirement_id: bound.endpoint_outcomes[req.requirement_id]
            for req in endpoint_requirements_for("industry_taxonomy")
        }
        base_req = next(
            r
            for r in endpoint_requirements_for("industry_taxonomy")
            if r.endpoint.endswith("get_industry_base_info")
        )
        const_req = next(
            r
            for r in endpoint_requirements_for("industry_taxonomy")
            if r.endpoint.endswith("get_industry_constituent")
        )
        assert outcomes[base_req.requirement_id].status is GateStatus.PASS
        assert outcomes[const_req.requirement_id].status is GateStatus.FAIL
        # the failure exchange is persisted and bound (correct identity)
        const_outcome = outcomes[const_req.requirement_id]
        assert const_outcome.actual_endpoint == const_req.endpoint
        assert const_outcome.binding is not None
        assert const_outcome.binding.evidence_uri.endswith(".meta.json")
        # the proof cases record the split verdict
        assert (
            _case_by_id(ctx, endpoint_requirement_case_id(base_req)).result
            is CaseResult.VALIDATED_PASS
        )
        const_case = _case_by_id(ctx, endpoint_requirement_case_id(const_req))
        assert const_case is not None
        assert const_case.result is CaseResult.VALIDATED_FAIL
        # early stop: the business probe never fired
        assert bound.probes[GateKind.BUSINESS_DATA].fired == 0

    def test_constituent_denied_run_cannot_be_approved(self, tmp_path: Path):
        """Full B1 chain: with constituent denied, b1 marks the
        capability BLOCKED - approval cannot happen (the failing proof
        case + honest REPORT entry refuse it downstream)."""
        import json

        ctx = _ctx(tmp_path, target=_ConstituentDeniedTarget())
        out = probe_b1_formal_gates(ctx)
        assert out["capabilities"]["industry_taxonomy"].startswith("BLOCKED_BY")
        artifact = ctx.store.run_dir(ctx.run) / "gates" / "industry_taxonomy.json"
        doc = json.loads(artifact.read_text(encoding="utf-8"))
        statuses = {e["requirement_id"]: e["status"] for e in doc["endpoint_requirements"]}
        const_req = next(
            r
            for r in endpoint_requirements_for("industry_taxonomy")
            if r.endpoint.endswith("get_industry_constituent")
        )
        assert statuses[const_req.requirement_id] == "FAIL"

    def test_canonical_deliverable_required_surfaces_match_requirements(self):
        """Structural guard (audit 20260830 section 3.3): for every
        multi-endpoint capability, the REQUIRED endpoint requirements
        must match the canonical deliverable's necessary surfaces - a
        declared sdk_method being classified OPTIONAL while the
        deliverable needs it is exactly the R4-B1.1 form-compliant /
        semantically-distorted failure this guard prevents."""
        # the canonical-deliverable necessary surfaces, pinned per
        # multi-endpoint capability (design decision, explicit)
        canonical_required = {
            "security_master": {"BaseData.get_hist_code_list"},
            "adj_factor": {"BaseData.get_adj_factor"},
            "corporate_action": {"InfoData.get_dividend", "InfoData.get_right_issue"},
            "industry_taxonomy": {
                "InfoData.get_industry_base_info",
                "InfoData.get_industry_constituent",
            },
            "index_daily": {"MarketData.query_kline"},
        }
        for capability, expected in canonical_required.items():
            actual = {r.endpoint for r in endpoint_requirements_for(capability)}
            assert actual == expected, (
                f"{capability}: REQUIRED surfaces {sorted(actual)} != canonical "
                f"deliverable surfaces {sorted(expected)}"
            )


@pytest.mark.integration
class TestApprovalConsumesExactEndpointIdentity:
    """B1-04: approval re-verifies endpoint identities from the
    hash-anchored REPORT artifact - tamper = fail closed."""

    def _approve(self, conn, tmp_path, run):
        from ashare_state.providers.amazingdata import capability as capability_module

        return capability_module.approve_from_spike_run(
            conn,
            "daily_bar",
            spike_root=tmp_path / "spike",
            spike_run_id=run.spike_run_id,
            approved_by="designer",
            capability_case_refs=("DB0",),
        )

    def _tampered_run(self, monkeypatch, tmp_path: Path, *, tamper=None, tamper_after_bind=None):
        """A CLOSED production run whose formal gate REPORT artifact is
        TAMPERED after the fact (via the artifact mutate hooks). The
        frozen production identity is patched for the WHOLE test via
        monkeypatch (auto-restored)."""
        from ashare_state.providers.amazingdata import production_identity as pi
        from ashare_state.providers.amazingdata.session import AccountProfile
        from ashare_state.spike import close_run
        from ashare_state.spike.model import SpikeCase

        profile = AccountProfile.from_scrubbed(
            {"PermissionCode": "1|2", "SubscribeLimitNum": 5000, "TotalWeekFlow": 500},
            host="h",
            username="u",
        )
        frozen = _make_frozen_identity(profile)
        monkeypatch.setattr(pi, "load_frozen_production_identity", lambda *a, **k: frozen)
        run, store = new_run(
            run_kind=RunKind.PRODUCTION,
            spike_root=tmp_path / "spike",
            code_commit=_SHA,
            environment_lock_hash="e" * 64,
            config_hash="c" * 64,
            sdk_version="1.1.9",
            runtime_version="V4.3.0",
            account_profile_id=profile.account_profile_id,
            account_profile=profile,
        )
        catalog = CaseCatalog(store, run.spike_run_id)
        cases = [("DB0", "daily_bar_units", CaseResult.VALIDATED_PASS)]
        for case_id, case_type, result in cases:
            meta = store.write_evidence(
                run,
                f"req-{case_id}",
                endpoint="ep",
                provider_dataset="ds",
                params={},
                payload={"case": case_id},
            )
            catalog.add(
                SpikeCase(
                    case_id=case_id,
                    spike_run_id=run.spike_run_id,
                    case_type=case_type,
                    security="X",
                    provider_symbol="X",
                    trade_date="20260814",
                    expected_value="e",
                    actual_value="a",
                    evidence_type="RAW_JSON",
                    evidence_ref=str(meta["evidence_ref"]),
                    result=result,
                    evidence_hash=str(meta["content_hash"]),
                )
            )
        _add_gate_proof_with_hook(
            store, run, catalog, "daily_bar", tamper=tamper, tamper_after_bind=tamper_after_bind
        )
        catalog.flush(store.run_dir(run))
        close_run(store, run)
        return run

    def test_approval_refuses_tampered_artifact(self, conn, tmp_path: Path, monkeypatch):
        """Tamper the REPORT artifact bytes AFTER the REPORT case hash
        was recorded (append whitespace - the JSON structure stays
        intact, so the entry checks WOULD pass, but the artifact hash no
        longer matches the case) -> approval refused (fail closed)."""
        run = self._tampered_run(
            monkeypatch,
            tmp_path,
            tamper_after_bind=lambda path: path.write_text(
                path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            ),
        )
        from ashare_state.providers.amazingdata import capability as capability_module

        with pytest.raises(capability_module.CapabilityGovernanceError, match="hash"):
            self._approve(conn, tmp_path, run)

    def test_approval_refuses_stand_in_actual_endpoint(self, conn, tmp_path: Path, monkeypatch):
        """Rewrite the artifact so daily_bar's actual_endpoint is a
        calendar (the stand-in bug) AND re-bind the REPORT case hash to
        the tampered bytes: approval STILL refuses - the contract
        endpoint no longer matches the recorded identity."""
        run = self._tampered_run(
            monkeypatch,
            tmp_path,
            tamper=lambda path: _mutate_artifact(path, actual_endpoint="BaseData.get_calendar"),
        )
        from ashare_state.providers.amazingdata import capability as capability_module

        with pytest.raises(capability_module.CapabilityGovernanceError, match="stand-in"):
            self._approve(conn, tmp_path, run)

    def test_approval_refuses_missing_required_case(self, conn, tmp_path: Path, monkeypatch):
        """Remove one REQUIRED requirement's proof case: approval
        refuses (the exact endpoint is unproven)."""
        run = self._tampered_run(monkeypatch, tmp_path, tamper=None)
        # drop the endpoint requirement case from the catalog jsonl
        run_dir = run_dir_of(tmp_path, run)
        catalog_path = run_dir / "cases" / "spike_case_catalog.jsonl"
        lines = [
            line
            for line in catalog_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and json.loads(line)["case_id"]
            != endpoint_requirement_case_id(endpoint_requirements_for("daily_bar")[0])
        ]
        catalog_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        from ashare_state.providers.amazingdata import capability as capability_module

        with pytest.raises(
            capability_module.CapabilityGovernanceError, match="endpoint requirement proof"
        ):
            self._approve(conn, tmp_path, run)


def run_dir_of(tmp_path: Path, run) -> Path:
    return tmp_path / "spike" / "production" / run.spike_run_id


def _make_frozen_identity(profile):
    from ashare_state.providers.amazingdata import production_identity as pi

    return pi.FrozenProductionIdentity(
        account_profile_id=profile.account_profile_id,
        confirmed_at="2026-08-28T00:00:00+00:00",
        confirmed_by="r4-b1-test",
    )


def _patch_frozen_identity(frozen):
    from ashare_state.providers.amazingdata import production_identity as pi

    original_loader = pi.load_frozen_production_identity

    def _frozen(*args, **kwargs):
        return frozen

    pi.load_frozen_production_identity = _frozen
    return original_loader


def _restore_frozen_identity(original_loader):
    from ashare_state.providers.amazingdata import production_identity as pi

    pi.load_frozen_production_identity = original_loader


def _mutate_artifact(path: Path, *, actual_endpoint: str) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    for entry in doc.get("endpoint_requirements", []):
        entry["actual_endpoint"] = actual_endpoint
    path.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")


def _add_gate_proof_with_hook(
    store, run, catalog, capability: str, tamper=None, tamper_after_bind=None
) -> None:
    """Like the fixture in test_capability_approval_from_spike but with
    two optional tamper hooks on the REPORT artifact:

    - ``tamper`` runs BEFORE the REPORT case hash is computed (the hash
      is re-bound to the tampered bytes - isolates the endpoint-
      identity re-verification, not the hash check);
    - ``tamper_after_bind`` runs AFTER the case is recorded (the case
      hash still matches the ORIGINAL bytes - isolates the hash
      mismatch re-verification)."""
    import hashlib
    import json

    from ashare_state.providers.amazingdata.capability import FORMAL_GATE_CASE_TYPE
    from ashare_state.spike.model import SpikeCase

    def _gate_case(case_id: str, meta) -> None:
        catalog.add(
            SpikeCase(
                case_id=case_id,
                spike_run_id=run.spike_run_id,
                case_type=FORMAL_GATE_CASE_TYPE,
                security="GATE",
                provider_symbol="GATE",
                trade_date="20260814",
                expected_value="e",
                actual_value="a",
                evidence_type="RAW_JSON",
                evidence_ref=str(meta["evidence_ref"]),
                result=CaseResult.VALIDATED_PASS,
                evidence_hash=str(meta["content_hash"]),
            )
        )

    for suffix in ("PERMISSION", "BUSINESS"):
        case_id = f"GATE-{capability}-{suffix}"
        meta = store.write_evidence(
            run,
            f"req-{case_id}",
            endpoint="ep",
            provider_dataset="ds",
            params={},
            payload={"gate": suffix},
        )
        _gate_case(case_id, meta)

    endpoint_entries = []
    for req in endpoint_requirements_for(capability):
        case_id = endpoint_requirement_case_id(req)
        meta = store.write_evidence(
            run,
            f"req-{case_id}",
            endpoint=req.endpoint,
            provider_dataset=req.provider_dataset,
            params={},
            payload={"endpoint_proof": req.requirement_id},
        )
        _gate_case(case_id, meta)
        endpoint_entries.append(
            {
                "requirement_id": req.requirement_id,
                "capability": req.capability,
                "expected_endpoint": req.endpoint,
                "actual_endpoint": req.endpoint,
                "provider_dataset": req.provider_dataset,
                "actual_dataset": req.provider_dataset,
                "mode": req.mode.value,
                "group_id": req.group_id,
                "status": "PASS",
                "reason": "fixture proof",
                "request_id": f"req-{case_id}",
                "evidence_uri": str(meta["evidence_ref"]),
                "evidence_hash": str(meta["content_hash"]),
            }
        )

    report_doc = {
        "capability": capability,
        "run_id": run.spike_run_id,
        "all_passed": True,
        "early_stopped": False,
        "blocked_by": None,
        "gates": [],
        "endpoint_requirements": endpoint_entries,
    }
    gates_dir = store.run_dir(run) / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    report_path = gates_dir / f"{capability}.json"
    report_path.write_text(json.dumps(report_doc, indent=2, sort_keys=True), encoding="utf-8")
    if tamper is not None:
        tamper(report_path)
    rel = f"{run.run_kind.value.lower()}/{run.spike_run_id}/gates/{capability}.json"
    catalog.add(
        SpikeCase(
            case_id=f"GATE-{capability}-REPORT",
            spike_run_id=run.spike_run_id,
            case_type=FORMAL_GATE_CASE_TYPE,
            security="GATE",
            provider_symbol="GATE",
            trade_date="20260814",
            expected_value="e",
            actual_value="a",
            evidence_type="RAW_JSON",
            evidence_ref=rel,
            result=CaseResult.VALIDATED_PASS,
            evidence_hash=hashlib.sha256(report_path.read_bytes()).hexdigest(),
        )
    )
    if tamper_after_bind is not None:
        tamper_after_bind(report_path)


@pytest.mark.integration
class TestStructuralGuard:
    """B1-05 final: registered requirements == formal endpoint proof
    plan coverage - a new capability cannot silently miss the boundary."""

    def test_gate_plan_requirements_match_the_contract(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        for capability, build_plan in GATE_PLAN_SPECS.items():
            plan = build_plan(ctx)
            assert plan.endpoint_requirements == endpoint_requirements_for(capability), capability

    def test_registry_capabilities_all_have_plans(self):
        assert set(GATE_PLAN_SPECS) == set(CAPABILITY_REGISTRY)
