"""Typed dataset normalization registry (CR-2 / CR-2.1, audit 20260831).

CR-2.1 hardening (audit "CR-2复审与CR-2.1收口要求" sections 2-4):

- **P0-01 surface identity**: the registry is keyed by the typed
  quadruple ``(provider, normalization_surface, provider_dataset,
  endpoint)``. The business surface is a SYSTEM-DERIVED value persisted
  by the provider facade on the raw envelope (the capability identity
  of the exchange), never a request-parameter guess. Two business
  surfaces sharing ONE endpoint+dataset pair - stock ``daily_bar`` and
  index ``daily_bar`` both ride ``MarketData.query_kline`` - route to
  DIFFERENT mappers. Legacy raw evidence lacking the surface field on
  an ambiguous endpoint FAILS CLOSED (``PAYLOAD_SURFACE_AMBIGUOUS``).
- **P0-02 immutable registry**: the production registry is a PRIVATE
  tuple + private exact index; ordinary callers get read-only lookup
  functions only. No mutable registry object is exported and the
  runner accepts no caller-supplied spec/mapper/registry (the
  Python-level monkeypatch of private module state is a tests-only
  facility, mirroring the frozen B2 scanner boundary ruling).
- **P0-03 mapper code identity**: every spec identity carries the
  system-derived ``MAPPER_CODE_FINGERPRINT`` (SHA-256 over the governed
  mapper + DTO module sources, line-ending normalized for cross-OS
  determinism). A mapper implementation change therefore produces a
  NEW run identity without anyone remembering to bump a version
  string; the fingerprint enters the idempotency key and the manifest.
- **P0-01 coverage**: every capability/SDK-method surface of the
  provider contract is EXPLICITLY classified - including the optional
  surfaces the pipeline does not consume (``InfoData.get_index_daily``,
  ``get_industry_weight``, ``get_industry_daily``) which are declared
  ``NOT_APPLICABLE`` instead of vanishing from structural truth.

Provider-Normalized semantics (CR2-P0-09) are unchanged: the
registered mappers are the EXISTING provider-faithful mappers -
provider literals, provider units and unverified markers pass through
unchanged; no canonical assumption is introduced here (CR-3's job).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ashare_state.providers.amazingdata.dto import (
    CorporateActionDTO,
    LimitPriceDTO,
    SecurityStatusDTO,
)
from ashare_state.providers.amazingdata.mapper import (
    corporate_action_flags,
    map_adj_factor_row,
    map_daily_bar_row,
    map_equity_structure_row,
    map_index_daily_row,
    map_industry_member_row,
    map_security_master_row,
    map_security_status_row,
    map_trade_calendar,
    project_limit_price,
)

__all__ = [
    "MAPPER_CODE_FINGERPRINT",
    "NORMALIZATION_CONTRACT_VERSION",
    "DatasetNormalizationSpec",
    "NormalizationErrorClass",
    "NormalizationRunStatus",
    "QuarantineScope",
    "SurfaceSupport",
    "lookup_spec",
    "mapper_identity_for",
    "registry_specs",
    "specs_for",
]


#: CR-2 P0-03/P0-07 + CR-2.1: the normalization contract identity.
#: CR-2.1 changes the registry semantics (typed surface key, index
#: routing, explicit NOT_APPLICABLE coverage) - the version bump
#: guarantees prior CR-2 runs are never silently replay-reused.
NORMALIZATION_CONTRACT_VERSION = "cr2.1-v1"


class SurfaceSupport(StrEnum):
    """CR2-P0-02 / CR-2.1 §2.4: explicit classification of EVERY
    provider capability surface."""

    SUPPORTED_NORMALIZATION = "SUPPORTED_NORMALIZATION"
    BLOCKED_PENDING_MAPPER = "BLOCKED_PENDING_MAPPER"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class QuarantineScope(StrEnum):
    ROW = "ROW"
    WHOLE_PAYLOAD = "WHOLE_PAYLOAD"


class NormalizationRunStatus(StrEnum):
    """CR2-P0-10: machine-defined run status.

    - SUCCESS : every input row normalized, quarantine_count == 0
    - PARTIAL : row-level quarantine exists AND the registry allows
                retained good rows for this dataset
    - BLOCKED : whole-payload quarantine / unsupported or ambiguous
                surface / raw evidence invalid / source exchange
                failed / internal failure / partial not allowed"""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class NormalizationErrorClass(StrEnum):
    """CR2-P0-08 + CR-2.1 §2.3: mapping errors, provider errors and
    surface-identity ambiguity are separated."""

    RAW_EVIDENCE_INVALID = "RAW_EVIDENCE_INVALID"
    SOURCE_EXCHANGE_FAILED = "SOURCE_EXCHANGE_FAILED"
    PAYLOAD_SURFACE_AMBIGUOUS = "PAYLOAD_SURFACE_AMBIGUOUS"
    PAYLOAD_SHAPE_UNSUPPORTED = "PAYLOAD_SHAPE_UNSUPPORTED"
    MAPPING_VALIDATION_FAILED = "MAPPING_VALIDATION_FAILED"
    NORMALIZATION_INTERNAL_ERROR = "NORMALIZATION_INTERNAL_ERROR"


#: a row mapper returns {output_name: DTO} - one DTO per output table
RowMapper = Callable[[dict[str, Any]], dict[str, Any]]
#: a whole-payload mapper receives the scalar column values + the
#: scrubbed request params and returns a single DTO
PayloadMapper = Callable[[list[Any], dict[str, Any]], Any]


def _module_source_fingerprint() -> str:
    """CR-2.1 P0-03 (audit section 4.3, option B): the governed mapper
    implementation hash. SHA-256 over the mapper + DTO module sources,
    line-ending normalized so a CRLF checkout of the SAME code yields
    the SAME identity on every OS. This value is SYSTEM-DERIVED at
    import time - it cannot be declared by a caller."""
    import ashare_state.providers.amazingdata.dto as _dto_module
    import ashare_state.providers.amazingdata.mapper as _mapper_module

    digest = hashlib.sha256()
    for module in (_mapper_module, _dto_module):
        module_file = getattr(module, "__file__", None)
        if not module_file:
            msg = f"mapper module {module!r} has no source file - cannot fingerprint"
            raise RuntimeError(msg)
        source = Path(module_file).read_bytes().replace(b"\r\n", b"\n")
        digest.update(len(source).to_bytes(8, "big"))
        digest.update(source)
    return digest.hexdigest()


#: the system-derived mapper implementation fingerprint entering every
#: spec identity / idempotency key / manifest (CR-2.1 P0-03).
MAPPER_CODE_FINGERPRINT: str = _module_source_fingerprint()


@dataclass(frozen=True)
class DatasetNormalizationSpec:
    """The production-owned normalization declaration for ONE
    (provider, normalization_surface, provider_dataset, endpoint)
    surface.

    ``map_row`` returns a dict of output_name -> DTO; a failing row is
    quarantined (ROW scope). ``map_payload`` maps the whole payload at
    once (WHOLE_PAYLOAD scope - one invalid element quarantines the
    whole payload and produces ZERO normalized output).
    """

    normalization_surface: str
    provider_dataset: str
    endpoint: str
    support: SurfaceSupport
    mapper_version: str
    quarantine_scope: QuarantineScope
    allow_partial: bool
    provider: str = "amazingdata"
    output_names: tuple[str, ...] = ("main",)
    map_row: RowMapper | None = None
    map_payload: PayloadMapper | None = None
    source_table: str | None = None  # exact table routing for multi-table payloads


def _security_master_mapper(source_label: str) -> RowMapper:
    def map_row(row: dict[str, Any]) -> dict[str, Any]:
        return {"main": map_security_master_row(row, source=source_label)}

    return map_row


def _map_status_row(row: dict[str, Any]) -> dict[str, Any]:
    """history_stock_status routes to THREE provider-faithful outputs
    (task book 1.3): the full-field status mirror, the limit-price
    projection, and the corporate-action flag projection."""
    status: SecurityStatusDTO = map_security_status_row(row)
    symbol, ex_date, is_ex_div, is_ex_rights = corporate_action_flags(status)
    limit: LimitPriceDTO = project_limit_price(status)
    corporate = CorporateActionDTO(
        provider_symbol=symbol,
        event_date=None,
        ex_date=ex_date,
        # honest projection marker - the flags come from the status
        # surface, not from a dedicated CA event endpoint
        event_type="STATUS_FLAG_PROJECTION",
        is_ex_dividend=is_ex_div,
        is_ex_rights=is_ex_rights,
    )
    return {
        "security_status": status,
        "limit_price": limit,
        "corporate_action": corporate,
    }


def _map_adj_single(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_adj_factor_row(row, factor_type="SINGLE")}


def _map_adj_backward(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_adj_factor_row(row, factor_type="BACKWARD")}


def _map_daily_bar(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_daily_bar_row(row)}


def _map_index_daily(row: dict[str, Any]) -> dict[str, Any]:
    """CR-2.1 P0-01: the INDEX daily surface rides the SAME
    MarketData.query_kline + provider_dataset=daily_bar pair as the
    stock surface - only the persisted system-derived business surface
    distinguishes the two mappers."""
    return {"main": map_index_daily_row(row)}


def _map_equity_structure(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_equity_structure_row(row)}


def _map_industry_member(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_industry_member_row(row)}


def _map_calendar_payload(values: list[Any], params: dict[str, Any]) -> Any:
    market = str(params.get("market") or "SH")
    return map_trade_calendar(market, values)


#: CR-2.1 P0-02: the STATIC production registry - a PRIVATE immutable
#: tuple. The module exposes read-only lookup functions only; there is
#: NO exported mutable registry object an ordinary caller could mutate
#: to inject a mapper (the B2 scanner static-registry ruling applies).
_REGISTRY_SPECS: tuple[DatasetNormalizationSpec, ...] = (
    DatasetNormalizationSpec(
        normalization_surface="trade_calendar",
        provider_dataset="trade_calendar",
        endpoint="BaseData.get_calendar",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="trade-calendar-mapper-v1",
        quarantine_scope=QuarantineScope.WHOLE_PAYLOAD,
        allow_partial=False,
        map_payload=_map_calendar_payload,
    ),
    DatasetNormalizationSpec(
        normalization_surface="security_master",
        provider_dataset="code_list",
        endpoint="BaseData.get_code_list",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="security-master-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_security_master_mapper("EXTRA_STOCK_A"),
    ),
    DatasetNormalizationSpec(
        normalization_surface="security_master",
        provider_dataset="hist_code_list",
        endpoint="BaseData.get_hist_code_list",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="security-master-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_security_master_mapper("HIST"),
    ),
    DatasetNormalizationSpec(
        normalization_surface="security_master",
        provider_dataset="stock_basic",
        endpoint="InfoData.get_stock_basic",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="security-master-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_security_master_mapper("STOCK_BASIC"),
    ),
    DatasetNormalizationSpec(
        normalization_surface="security_status_history",
        provider_dataset="history_stock_status",
        endpoint="InfoData.get_history_stock_status",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="status-triple-projection-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        output_names=("security_status", "limit_price", "corporate_action"),
        map_row=_map_status_row,
    ),
    DatasetNormalizationSpec(
        normalization_surface="adj_factor",
        provider_dataset="adj_factor",
        endpoint="BaseData.get_adj_factor",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="adj-factor-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_map_adj_single,
    ),
    DatasetNormalizationSpec(
        normalization_surface="adj_factor",
        provider_dataset="backward_factor",
        endpoint="BaseData.get_backward_factor",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="adj-factor-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_map_adj_backward,
    ),
    DatasetNormalizationSpec(
        normalization_surface="corporate_action",
        provider_dataset="corporate_action",
        endpoint="InfoData.get_dividend",
        # B4 field semantics not yet verified - honest blocker
        support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
    DatasetNormalizationSpec(
        normalization_surface="corporate_action",
        provider_dataset="corporate_action",
        endpoint="InfoData.get_right_issue",
        support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
    DatasetNormalizationSpec(
        normalization_surface="code_mapping_bj",
        provider_dataset="code_mapping_bj",
        endpoint="InfoData.get_bj_code_mapping",
        # BJ mapping identity surface - no verified row mapper yet
        support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
    DatasetNormalizationSpec(
        normalization_surface="equity_structure",
        provider_dataset="equity_structure",
        endpoint="InfoData.get_equity_structure",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="equity-structure-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_map_equity_structure,
    ),
    DatasetNormalizationSpec(
        normalization_surface="industry_taxonomy",
        provider_dataset="industry_taxonomy",
        endpoint="InfoData.get_industry_base_info",
        # base-info is the taxonomy DEFINITION surface, not the
        # membership surface - the member mapper does not apply
        support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
    DatasetNormalizationSpec(
        normalization_surface="industry_taxonomy",
        provider_dataset="industry_taxonomy",
        endpoint="InfoData.get_industry_constituent",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="industry-member-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_map_industry_member,
    ),
    DatasetNormalizationSpec(
        normalization_surface="daily_bar",
        provider_dataset="daily_bar",
        endpoint="MarketData.query_kline",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="daily-bar-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_map_daily_bar,
    ),
    # CR-2.1 P0-01: the INDEX daily business surface. Same
    # (provider_dataset, endpoint) as the stock daily_bar surface -
    # ONLY the persisted system-derived normalization_surface
    # distinguishes them; guessing from symbol prefixes or request
    # params is forbidden.
    DatasetNormalizationSpec(
        normalization_surface="index_daily",
        provider_dataset="daily_bar",
        endpoint="MarketData.query_kline",
        support=SurfaceSupport.SUPPORTED_NORMALIZATION,
        mapper_version="index-daily-mapper-v1",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=True,
        map_row=_map_index_daily,
    ),
    # ---- CR-2.1 §2.4: optional SDK surfaces explicitly NOT_APPLICABLE
    # (documented in SDK_METHOD_CLASSIFICATIONS as
    # OPTIONAL_NON_APPROVAL_SURFACE; the pipeline does not consume
    # them - they must not vanish from structural truth).
    DatasetNormalizationSpec(
        normalization_surface="index_daily",
        provider_dataset="index_daily",
        endpoint="InfoData.get_index_daily",
        support=SurfaceSupport.NOT_APPLICABLE,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
    DatasetNormalizationSpec(
        normalization_surface="industry_taxonomy",
        provider_dataset="industry_weight",
        endpoint="InfoData.get_industry_weight",
        support=SurfaceSupport.NOT_APPLICABLE,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
    DatasetNormalizationSpec(
        normalization_surface="industry_taxonomy",
        provider_dataset="industry_daily",
        endpoint="InfoData.get_industry_daily",
        support=SurfaceSupport.NOT_APPLICABLE,
        mapper_version="none",
        quarantine_scope=QuarantineScope.ROW,
        allow_partial=False,
    ),
)


def _build_index() -> dict[tuple[str, str, str, str], DatasetNormalizationSpec]:
    index: dict[tuple[str, str, str, str], DatasetNormalizationSpec] = {}
    for spec in _REGISTRY_SPECS:
        key = (spec.provider, spec.normalization_surface, spec.provider_dataset, spec.endpoint)
        if key in index:
            msg = f"duplicate normalization registry key {key}"
            raise RuntimeError(msg)
        index[key] = spec
    return index


#: CR-2.1 P0-02: the PRIVATE exact index - (provider, surface,
#: dataset, endpoint) -> spec. Never exported.
_REGISTRY_INDEX: dict[tuple[str, str, str, str], DatasetNormalizationSpec] = _build_index()

#: module-level alias consumed by tests through monkeypatch ONLY
#: (tests-only injection of private module state, audit section 3.1).
#: Production code reads it exclusively through ``lookup_spec`` /
#: ``specs_for`` / ``registry_specs``.
_INDEX = _REGISTRY_INDEX


def lookup_spec(
    provider: str, normalization_surface: str, provider_dataset: str, endpoint: str
) -> DatasetNormalizationSpec | None:
    """Exact typed routing - no fuzzy fallback."""
    return _INDEX.get((provider, normalization_surface, provider_dataset, endpoint))


def specs_for(
    provider: str, provider_dataset: str, endpoint: str
) -> tuple[DatasetNormalizationSpec, ...]:
    """Every registry spec matching (provider, dataset, endpoint) -
    ANY business surface. More than one match means the pair is
    AMBIGUOUS and only the persisted surface identity can route."""
    return tuple(
        spec
        for spec in _REGISTRY_SPECS
        if spec.provider == provider
        and spec.provider_dataset == provider_dataset
        and spec.endpoint == endpoint
    )


def registry_specs() -> tuple[DatasetNormalizationSpec, ...]:
    """Read-only snapshot of the production registry (immutable
    tuple - callers cannot add/replace/delete a production spec)."""
    return _REGISTRY_SPECS


def mapper_identity_for(spec: DatasetNormalizationSpec) -> str:
    """SYSTEM-DERIVED mapper identity recorded on runs and quarantine
    records: registry entry identity + the governed mapper code
    fingerprint (never a caller declaration, never a hand-bumped
    version alone)."""
    return (
        f"{spec.normalization_surface}/{spec.provider_dataset}/{spec.endpoint}"
        f"@{spec.mapper_version}#{MAPPER_CODE_FINGERPRINT[:16]}"
    )
