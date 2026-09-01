"""Provider-owned operation specs (CR-2.3, audit 20260901 section 2).

CR-2.2 removed the ``normalization_surface`` parameter from
``call_exchange`` but the surface was still derived from the caller-
supplied ``require_capability`` - an ordinary caller could still
construct an exchange whose endpoint/dataset/fn disagree with the
capability, merely relocating the caller-declared identity from one
field to another (same ruling as B1/B2: caller-declared correctness
identity is not system-derived).

CR-2.3 closes this: the provider facade exposes ONLY typed wrappers.
Each wrapper is bound to ONE private STATIC ``ProviderOperationSpec``
constant; the generic exchange executor is PRIVATE and consumes a spec -
endpoint / provider_dataset / capability / normalization_surface are
ALL derived from the spec, never from call arguments. An ordinary
production caller cannot freely combine a stock kline callable with an
index capability any more.

Structure (mirrors the frozen B2 scanner static-registry ruling):

- ``_OPERATION_SPECS`` is a PRIVATE module-level dict (immutable
  values); ordinary callers get read-only ``lookup_operation_spec``
  only. There is no exported mutable registry object.
- The spec constants below are the STATIC bindings the facade wrappers
  consume (each wrapper references exactly one constant; the binding
  is guarded by AST tests).
- Every spec is structurally cross-bound to BOTH governed contracts:
  ``(capability, endpoint)`` must exist in
  ``SDK_METHOD_CLASSIFICATIONS`` and
  ``(normalization_surface, provider_dataset, endpoint)`` must exist
  in the normalization registry (guarded by tests).
- The 3 NOT_APPLICABLE optional SDK surfaces (get_index_daily /
  get_industry_weight / get_industry_daily) deliberately have NO
  operation spec: the pipeline never exchanges on them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ProviderOperationSpec",
    "lookup_operation_spec",
    "operation_specs",
]


@dataclass(frozen=True)
class ProviderOperationSpec:
    """The provider-owned identity of ONE production exchange wrapper.

    ``operation_id`` is the stable unique id of the wrapper's exchange
    identity (``<endpoint>#<normalization_surface>``); it is persisted
    on the raw envelope / meta and on the raw evidence anchor for
    cross-binding. All other fields are the governed contract values
    the executor derives EVERYTHING from.
    """

    operation_id: str
    capability: str
    endpoint: str
    provider_dataset: str
    normalization_surface: str


def _spec(
    capability: str, endpoint: str, provider_dataset: str, normalization_surface: str
) -> ProviderOperationSpec:
    return ProviderOperationSpec(
        operation_id=f"{endpoint}#{normalization_surface}",
        capability=capability,
        endpoint=endpoint,
        provider_dataset=provider_dataset,
        normalization_surface=normalization_surface,
    )


#: STATIC spec constants - the wrapper bindings (one wrapper, one spec).
TRADE_CALENDAR = _spec(
    "trade_calendar", "BaseData.get_calendar", "trade_calendar", "trade_calendar"
)
CODE_LIST = _spec("security_master", "BaseData.get_code_list", "code_list", "security_master")
HIST_CODE_LIST = _spec(
    "security_master", "BaseData.get_hist_code_list", "hist_code_list", "security_master"
)
STOCK_BASIC = _spec("security_master", "InfoData.get_stock_basic", "stock_basic", "security_master")
HISTORY_STOCK_STATUS = _spec(
    "security_status_history",
    "InfoData.get_history_stock_status",
    "history_stock_status",
    "security_status_history",
)
ADJ_FACTOR = _spec("adj_factor", "BaseData.get_adj_factor", "adj_factor", "adj_factor")
BACKWARD_FACTOR = _spec(
    "adj_factor", "BaseData.get_backward_factor", "backward_factor", "adj_factor"
)
DIVIDEND = _spec(
    "corporate_action", "InfoData.get_dividend", "corporate_action", "corporate_action"
)
RIGHT_ISSUE = _spec(
    "corporate_action", "InfoData.get_right_issue", "corporate_action", "corporate_action"
)
BJ_CODE_MAPPING = _spec(
    "code_mapping_bj", "InfoData.get_bj_code_mapping", "code_mapping_bj", "code_mapping_bj"
)
EQUITY_STRUCTURE = _spec(
    "equity_structure", "InfoData.get_equity_structure", "equity_structure", "equity_structure"
)
INDUSTRY_BASE_INFO = _spec(
    "industry_taxonomy", "InfoData.get_industry_base_info", "industry_taxonomy", "industry_taxonomy"
)
INDUSTRY_CONSTITUENT = _spec(
    "industry_taxonomy",
    "InfoData.get_industry_constituent",
    "industry_taxonomy",
    "industry_taxonomy",
)
DAILY_BAR_KLINE = _spec("daily_bar", "MarketData.query_kline", "daily_bar", "daily_bar")
#: CR-2.3 P0-01: the index kline wrapper's DISTINCT operation identity -
#: same endpoint + dataset as the stock wrapper, a different
#: capability/surface. Only the two static specs distinguish them; no
#: caller can mix the two.
INDEX_DAILY_KLINE = _spec("index_daily", "MarketData.query_kline", "daily_bar", "index_daily")


#: PRIVATE static registry - one operation spec per production wrapper.
#: No public mutable registry object is exported (B2 static-registry
#: ruling); tests-only injection goes through monkeypatch of this
#: private module state.
_OPERATION_SPECS: dict[str, ProviderOperationSpec] = {
    spec.operation_id: spec
    for spec in (
        TRADE_CALENDAR,
        CODE_LIST,
        HIST_CODE_LIST,
        STOCK_BASIC,
        HISTORY_STOCK_STATUS,
        ADJ_FACTOR,
        BACKWARD_FACTOR,
        DIVIDEND,
        RIGHT_ISSUE,
        BJ_CODE_MAPPING,
        EQUITY_STRUCTURE,
        INDUSTRY_BASE_INFO,
        INDUSTRY_CONSTITUENT,
        DAILY_BAR_KLINE,
        INDEX_DAILY_KLINE,
    )
}


def lookup_operation_spec(operation_id: str) -> ProviderOperationSpec | None:
    """Read-only exact lookup (no fuzzy fallback)."""
    return _OPERATION_SPECS.get(operation_id)


def operation_specs() -> tuple[ProviderOperationSpec, ...]:
    """Read-only snapshot (immutable tuple) for structural guards."""
    return tuple(_OPERATION_SPECS.values())
