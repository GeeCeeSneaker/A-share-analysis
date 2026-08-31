"""Typed dataset normalization registry (CR-2 P0-02, audit 20260831).

The registry is PRODUCTION-OWNED and STATIC: callers can neither
inject mappers nor skip surfaces. Every (provider_dataset, endpoint)
pair of the AmazingData provider surface is EXPLICITLY classified:

- SUPPORTED_NORMALIZATION: an exact mapper routes raw rows to typed
  provider-faithful DTOs (row scope) or the whole payload (calendar);
- BLOCKED_PENDING_MAPPER: the surface is a REQUIRED part of the
  provider surface but no sufficiently verified mapper exists yet -
  normalization FAILS CLOSED (run BLOCKED), never a silent skip that
  lets the run look SUCCESS;
- NOT_APPLICABLE: the surface is not a normalization input at all.

Provider-Normalized semantics (CR2-P0-09): the registered mappers are
the EXISTING provider-faithful mappers (``providers.amazingdata.
mapper``) - provider literals, provider units, unverified markers
(GALAXY_UNVERIFIED / UNVERIFIED) all pass through unchanged. No
canonical assumption is introduced here (that is CR-3's job).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
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
    map_industry_member_row,
    map_security_master_row,
    map_security_status_row,
    map_trade_calendar,
    project_limit_price,
)

__all__ = [
    "NORMALIZATION_CONTRACT_VERSION",
    "NormalizationErrorClass",
    "NormalizationRunStatus",
    "QuarantineScope",
    "SurfaceSupport",
    "DATASET_NORMALIZATION_REGISTRY",
    "DatasetNormalizationSpec",
    "lookup_spec",
    "mapper_identity_for",
]


#: CR-2 P0-03/P0-07: the normalization contract identity. Changing the
#: registry semantics (mapper wiring / scope policy) changes the
#: contract version and the idempotency key - prior runs are not
#: silently reused.
NORMALIZATION_CONTRACT_VERSION = "cr2-v1"


class SurfaceSupport(StrEnum):
    """CR2-P0-02: explicit classification of every provider surface."""

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
    - BLOCKED : whole-payload quarantine / unsupported surface / raw
                evidence invalid / source exchange failed / internal
                failure / partial not allowed"""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class NormalizationErrorClass(StrEnum):
    """CR2-P0-08: mapping errors are separated from provider errors."""

    RAW_EVIDENCE_INVALID = "RAW_EVIDENCE_INVALID"
    SOURCE_EXCHANGE_FAILED = "SOURCE_EXCHANGE_FAILED"
    PAYLOAD_SHAPE_UNSUPPORTED = "PAYLOAD_SHAPE_UNSUPPORTED"
    MAPPING_VALIDATION_FAILED = "MAPPING_VALIDATION_FAILED"
    NORMALIZATION_INTERNAL_ERROR = "NORMALIZATION_INTERNAL_ERROR"


#: a row mapper returns {output_name: DTO} - one DTO per output table
RowMapper = Callable[[dict[str, Any]], dict[str, Any]]
#: a whole-payload mapper receives the scalar column values + the
#: scrubbed request params and returns a single DTO
PayloadMapper = Callable[[list[Any], dict[str, Any]], Any]


@dataclass(frozen=True)
class DatasetNormalizationSpec:
    """The production-owned normalization declaration for ONE
    (provider_dataset, endpoint) surface.

    ``map_row`` returns a dict of output_name -> DTO; a failing row is
    quarantined (ROW scope). ``map_payload`` maps the whole payload at
    once (WHOLE_PAYLOAD scope - one invalid element quarantines the
    whole payload and produces ZERO normalized output).
    """

    provider_dataset: str
    endpoint: str
    support: SurfaceSupport
    mapper_version: str
    quarantine_scope: QuarantineScope
    allow_partial: bool
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


def _map_equity_structure(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_equity_structure_row(row)}


def _map_industry_member(row: dict[str, Any]) -> dict[str, Any]:
    return {"main": map_industry_member_row(row)}


def _map_calendar_payload(values: list[Any], params: dict[str, Any]) -> Any:
    market = str(params.get("market") or "SH")
    return map_trade_calendar(market, values)


#: the STATIC production registry (CR2-P0-02). Keyed by
#: (provider_dataset, endpoint) - exact routing, no fuzzy matching.
DATASET_NORMALIZATION_REGISTRY: dict[tuple[str, str], DatasetNormalizationSpec] = dict(
    _registry_pair
    for _registry_pair in (
        (
            ("trade_calendar", "BaseData.get_calendar"),
            DatasetNormalizationSpec(
                provider_dataset="trade_calendar",
                endpoint="BaseData.get_calendar",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="trade-calendar-mapper-v1",
                quarantine_scope=QuarantineScope.WHOLE_PAYLOAD,
                allow_partial=False,
                map_payload=_map_calendar_payload,
            ),
        ),
        (
            ("code_list", "BaseData.get_code_list"),
            DatasetNormalizationSpec(
                provider_dataset="code_list",
                endpoint="BaseData.get_code_list",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="security-master-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_security_master_mapper("EXTRA_STOCK_A"),
            ),
        ),
        (
            ("hist_code_list", "BaseData.get_hist_code_list"),
            DatasetNormalizationSpec(
                provider_dataset="hist_code_list",
                endpoint="BaseData.get_hist_code_list",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="security-master-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_security_master_mapper("HIST"),
            ),
        ),
        (
            ("stock_basic", "InfoData.get_stock_basic"),
            DatasetNormalizationSpec(
                provider_dataset="stock_basic",
                endpoint="InfoData.get_stock_basic",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="security-master-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_security_master_mapper("STOCK_BASIC"),
            ),
        ),
        (
            ("history_stock_status", "InfoData.get_history_stock_status"),
            DatasetNormalizationSpec(
                provider_dataset="history_stock_status",
                endpoint="InfoData.get_history_stock_status",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="status-triple-projection-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                output_names=("security_status", "limit_price", "corporate_action"),
                map_row=_map_status_row,
            ),
        ),
        (
            ("adj_factor", "BaseData.get_adj_factor"),
            DatasetNormalizationSpec(
                provider_dataset="adj_factor",
                endpoint="BaseData.get_adj_factor",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="adj-factor-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_map_adj_single,
            ),
        ),
        (
            ("backward_factor", "BaseData.get_backward_factor"),
            DatasetNormalizationSpec(
                provider_dataset="backward_factor",
                endpoint="BaseData.get_backward_factor",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="adj-factor-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_map_adj_backward,
            ),
        ),
        (
            ("corporate_action", "InfoData.get_dividend"),
            DatasetNormalizationSpec(
                provider_dataset="corporate_action",
                endpoint="InfoData.get_dividend",
                # B4 field semantics not yet verified - honest blocker
                support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
                mapper_version="none",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=False,
            ),
        ),
        (
            ("corporate_action", "InfoData.get_right_issue"),
            DatasetNormalizationSpec(
                provider_dataset="corporate_action",
                endpoint="InfoData.get_right_issue",
                support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
                mapper_version="none",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=False,
            ),
        ),
        (
            ("code_mapping_bj", "InfoData.get_bj_code_mapping"),
            DatasetNormalizationSpec(
                provider_dataset="code_mapping_bj",
                endpoint="InfoData.get_bj_code_mapping",
                # BJ mapping identity surface - no verified row mapper yet
                support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
                mapper_version="none",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=False,
            ),
        ),
        (
            ("equity_structure", "InfoData.get_equity_structure"),
            DatasetNormalizationSpec(
                provider_dataset="equity_structure",
                endpoint="InfoData.get_equity_structure",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="equity-structure-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_map_equity_structure,
            ),
        ),
        (
            ("industry_taxonomy", "InfoData.get_industry_base_info"),
            DatasetNormalizationSpec(
                provider_dataset="industry_taxonomy",
                endpoint="InfoData.get_industry_base_info",
                # base-info is the taxonomy DEFINITION surface, not the
                # membership surface - the member mapper does not apply
                support=SurfaceSupport.BLOCKED_PENDING_MAPPER,
                mapper_version="none",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=False,
            ),
        ),
        (
            ("industry_taxonomy", "InfoData.get_industry_constituent"),
            DatasetNormalizationSpec(
                provider_dataset="industry_taxonomy",
                endpoint="InfoData.get_industry_constituent",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="industry-member-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_map_industry_member,
            ),
        ),
        (
            ("daily_bar", "MarketData.query_kline"),
            DatasetNormalizationSpec(
                provider_dataset="daily_bar",
                endpoint="MarketData.query_kline",
                support=SurfaceSupport.SUPPORTED_NORMALIZATION,
                mapper_version="daily-bar-mapper-v1",
                quarantine_scope=QuarantineScope.ROW,
                allow_partial=True,
                map_row=_map_daily_bar,
            ),
        ),
    )
)


def lookup_spec(provider_dataset: str, endpoint: str) -> DatasetNormalizationSpec | None:
    """Exact (dataset, endpoint) routing - no fuzzy fallback."""
    return DATASET_NORMALIZATION_REGISTRY.get((provider_dataset, endpoint))


def mapper_identity_for(spec: DatasetNormalizationSpec) -> str:
    """SYSTEM-DERIVED mapper identity recorded on runs and quarantine
    records (registry entry identity, never a caller declaration)."""
    return f"{spec.provider_dataset}/{spec.endpoint}@{spec.mapper_version}"
