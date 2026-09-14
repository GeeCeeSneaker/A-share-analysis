"""Bounded, offline CR-7 historical-materialization primitives.

This module deliberately accepts only an already verified in-memory
``VerifiedResearchProjection``.  It has no Provider, SDK, network, or
ordinary R1-publisher dependency.  The implementation is therefore useful for
contract fixtures and preflight tests without granting authority to materialize
the real 2020--2026H1 history.
"""

from __future__ import annotations

import io
import json
import os
import re
from calendar import monthrange
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import polars as pl

from ashare_state.providers.amazingdata.month_completeness import (
    AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION,
    AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION,
    AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION,
    MonthCompletenessError,
    MonthCompletenessEvaluation,
    _PositiveTradeFallbackEvidence,
    _snapshot_trade_observation,
    evaluate_month_completeness,
)
from ashare_state.research.models import (
    INDEX_PANEL_STATE,
    PRICE_BASIS,
    RESEARCH_SECURITY_DAILY_DATASET,
    RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
    UNIVERSE_BASIS,
    UNVERIFIED_CALLER_IDENTITY_SOURCE,
    CoverageState,
    ResearchEligibility,
    ResearchPanelError,
    ResearchSplit,
    canonical_json,
    ensure_utc_timestamp,
    parse_date_value,
    research_code_fingerprint,
    research_security_daily_schema,
    sha256_hex,
)
from ashare_state.research.panel import VerifiedResearchProjection
from ashare_state.research.splits import assign_research_split, split_windows
from ashare_state.storage.atomic_files import ImmutableFileExistsError, write_file_atomic

__all__ = [
    "AMAZINGDATA_ACQUISITION_RECEIPT_VERSION",
    "AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION",
    "AMAZINGDATA_CALENDAR_MARKET",
    "AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION",
    "AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION",
    "AMAZINGDATA_SECURITY_UNIVERSE_SELECTION",
    "AUTHORITATIVE_COVERAGE_EVIDENCE_VERSION",
    "AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD",
    "COMPLETE_OBSERVED_DAILY_BAR_SCOPE",
    "CoverageEvidenceClass",
    "AmazingDataAcquisitionReceipt",
    "AmazingDataExchangeReceipt",
    "AuthoritativeCoverageEvidence",
    "AuthoritativeSourceSelection",
    "VerifiedSourceSnapshot",
    "CoverageBasisDescriptor",
    "CoverageBasisError",
    "CoverageEvaluation",
    "HistoricalArtifact",
    "HistoricalMaterializationError",
    "HistoricalMaterializationPlan",
    "HistoricalMaterializationReader",
    "HistoricalReadError",
    "MaterializationConflictError",
    "MaterializationResult",
    "OfflineHistoricalMaterializer",
    "PartitionKey",
    "PARTIAL_OBSERVED_DAILY_BAR_SCOPE",
    "PositiveTradeFallbackOperation",
    "WriterRuntimeLock",
    "build_authoritative_coverage_evidence_from_acquisition",
    "build_fixture_coverage_basis_descriptor",
    "build_materialization_identity",
    "build_writer_runtime_lock_identity",
    "compute_coverage_basis_set_hash",
    "compute_dependency_lock_content_hash",
    "compute_idempotency_key",
    "compute_materialization_id",
    "compute_writer_runtime_lock_hash",
    "expected_partition_keys",
    "verify_coverage_basis",
]


HISTORICAL_MATERIALIZATION_CONTRACT_VERSION = "cr7-history-materialization-v1"
HISTORICAL_DATASET = RESEARCH_SECURITY_DAILY_DATASET
TARGET_WINDOW_START = date(2020, 1, 1)
TARGET_WINDOW_END = date(2026, 6, 30)
COVERAGE_BASIS_VERSION = "coverage-basis-v1"
COMPLETE_OBSERVED_DAILY_BAR_SCOPE = "COMPLETE_OBSERVED_DAILY_BAR_SCOPE"
PARTIAL_OBSERVED_DAILY_BAR_SCOPE = "PARTIAL_OBSERVED_DAILY_BAR_SCOPE"
COVERAGE_POLICY_VERSION = "coverage-basis-v1"
PARTITION_POLICY_VERSION = "monthly-route-v1"
WRITER_CONFIGURATION_VERSION = "cr7-writer-v1"
OFFLINE_FIXTURE_COMPLETE_METHOD = "OFFLINE_FIXTURE_COMPLETE_SCOPE_V1"
OFFLINE_FIXTURE_PARTIAL_METHOD = "OFFLINE_FIXTURE_PARTIAL_SCOPE_V1"
AUTHORITATIVE_COVERAGE_EVIDENCE_VERSION = "authoritative-coverage-evidence-v1"
AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD = "AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_V1"
AUTHORITATIVE_UPSTREAM_STATEMENT_KIND = "AMAZINGDATA_ACQUISITION_RECEIPT_V3"
AUTHORITATIVE_SOURCE_SELECTION_VERSION = "source-selection-retrieval-closure-20260912"
AUTHORITATIVE_SOURCE_CLASS = "amazingdata_provider_observation"
AUTHORITATIVE_PROVIDER = "amazingdata"
AUTHORITATIVE_RETRIEVAL_SURFACE = "history_acquisition"
AUTHORITATIVE_SOURCE_METHODS = (
    "BaseData.get_hist_code_list",
    "BaseData.get_calendar",
    "InfoData.get_history_stock_status",
    "MarketData.query_kline",
)
AMAZINGDATA_ACQUISITION_RECEIPT_VERSION = "amazingdata-history-acquisition-receipt-v3"
AMAZINGDATA_SECURITY_UNIVERSE_SELECTION = "EXTRA_STOCK_A_SH_SZ"
AMAZINGDATA_CALENDAR_MARKET = "SH"

_AMAZINGDATA_OPERATION_BINDINGS = {
    "BaseData.get_hist_code_list": (
        "BaseData.get_hist_code_list#security_master",
        "list[str]",
    ),
    "BaseData.get_calendar": ("BaseData.get_calendar#trade_calendar", "list[int]"),
    "InfoData.get_history_stock_status": (
        "InfoData.get_history_stock_status#security_status_history",
        "dict[str,dataframe|None]",
    ),
    "MarketData.query_kline": (
        "MarketData.query_kline#daily_bar",
        "dict[str,dataframe|None]",
    ),
}
_AMAZINGDATA_POSITIVE_TRADE_OPERATION_BINDING = (
    "MarketData.query_snapshot#trade_activity_snapshot",
    "dict[str,dataframe|None]",
)


class CoverageEvidenceClass(StrEnum):
    """Authority class attached to a recognized coverage method.

    Fixture methods can exercise the planner and storage protocol, but they
    must never satisfy the ordinary historical-reader publication boundary.
    The authoritative value is registered only for the reviewed typed
    evidence-sidecar method below.  A provider observation without that
    sidecar remains non-authoritative.
    """

    TEST_FIXTURE_ONLY = "TEST_FIXTURE_ONLY"
    AUTHORITATIVE_UPSTREAM = "AUTHORITATIVE_UPSTREAM"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class _CompletenessMethodSpec:
    state: CoverageState
    evidence_class: CoverageEvidenceClass


_RECOGNIZED_COMPLETENESS_METHODS = {
    OFFLINE_FIXTURE_COMPLETE_METHOD: _CompletenessMethodSpec(
        CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
        CoverageEvidenceClass.TEST_FIXTURE_ONLY,
    ),
    OFFLINE_FIXTURE_PARTIAL_METHOD: _CompletenessMethodSpec(
        CoverageState.PARTIAL_OBSERVED_DAILY_BAR_COVERAGE,
        CoverageEvidenceClass.TEST_FIXTURE_ONLY,
    ),
    AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD: _CompletenessMethodSpec(
        CoverageState.OBSERVED_DAILY_BAR_COVERAGE,
        CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM,
    ),
}
_ROUTES = ("research_enabled", "disabled", "experimental")
_EXPECTED_IDENTITY_FIELDS = (
    "contract_version",
    "target_dataset",
    "target_window_start",
    "target_window_end",
    "research_split_windows",
    "source_snapshot_id",
    "source_snapshot_as_of",
    "source_snapshot_manifest_hash",
    "source_snapshot_semantic_hash",
    "source_canonical_run_id",
    "source_readmodel_contract_version",
    "identity_view_version",
    "identity_view_hash",
    "identity_source_kind",
    "identity_source_lineage_hash",
    "schema_version",
    "price_basis",
    "universe_basis",
    "coverage_policy_version",
    "partition_policy_version",
    "build_code_fingerprint",
    "writer_runtime_lock_hash",
    "coverage_basis_set_hash",
)
_BASIS_FIELDS = (
    "coverage_basis_id",
    "coverage_basis_version",
    "research_split",
    "calendar_year",
    "calendar_month",
    "source_snapshot_id",
    "source_snapshot_manifest_hash",
    "source_domain",
    "claimed_scope_start",
    "claimed_scope_end",
    "source_selection_fingerprint",
    "completeness_method",
    "completeness_claim",
    "coverage_basis_artifact_uri",
    "coverage_basis_artifact_hash",
)
_BASIS_FIELDS_WITHOUT_HASH = tuple(
    field for field in _BASIS_FIELDS if field != "coverage_basis_artifact_hash"
)
_AUTHORITATIVE_EVIDENCE_FIELDS = (
    "evidence_id",
    "evidence_version",
    "coverage_basis_id",
    "source_snapshot_id",
    "source_snapshot_manifest_hash",
    "source_snapshot_as_of",
    "source_domain",
    "claimed_scope_start",
    "claimed_scope_end",
    "source_selection_fingerprint",
    "completeness_method",
    "completeness_claim",
    "source_selection",
    "acquisition_receipt",
    "upstream_source",
    "upstream_statement_kind",
    "upstream_statement_id",
    "upstream_statement_locator",
    "upstream_statement_hash",
    "upstream_inventory_id",
    "upstream_inventory_scope_start",
    "upstream_inventory_scope_end",
    "upstream_inventory_hash",
    "upstream_security_count",
    "upstream_session_count",
    "retrieved_at_utc",
    "available_at",
    "pit_as_of",
    "coverage_basis_evidence_uri",
)
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_OFFLINE_FIXTURE_ROWS = 10_000


class HistoricalMaterializationError(ResearchPanelError):
    """Base error for the bounded historical-materialization implementation."""


class CoverageBasisError(HistoricalMaterializationError):
    """Coverage evidence is absent, malformed, forged, or out of scope."""


class MaterializationConflictError(HistoricalMaterializationError):
    """An immutable staging or committed identity contains different bytes."""


class HistoricalReadError(HistoricalMaterializationError):
    """A historical materialization is not safe for ordinary reads."""


def _require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HistoricalMaterializationError(f"{field} must be a non-empty string")
    return value.strip()


def _require_sha256(value: Any, field: str) -> str:
    normalized = _require_non_empty_string(value, field)
    if _HASH_PATTERN.fullmatch(normalized) is None:
        raise HistoricalMaterializationError(f"{field} must be lower-case SHA-256 hex")
    return normalized


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise HistoricalMaterializationError(f"{field} must be a positive integer")
    return value


def _require_nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HistoricalMaterializationError(f"{field} must be a nonnegative integer")
    return value


def _safe_relative_uri(value: Any, field: str) -> str:
    uri = _require_non_empty_string(value, field).replace("\\", "/")
    windows = PureWindowsPath(uri)
    posix = PurePosixPath(uri)
    if uri.startswith("/") or windows.drive or any(part in {"", ".", ".."} for part in posix.parts):
        raise HistoricalMaterializationError(f"{field} must be a safe relative URI")
    return str(posix)


def _month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _yyyymmdd(value: date) -> int:
    return value.year * 10000 + value.month * 100 + value.day


def _day_to_date(value: int) -> date:
    if isinstance(value, bool) or not isinstance(value, int) or len(str(value)) != 8:
        raise CoverageBasisError("historical date is malformed")
    try:
        return date(value // 10000, (value // 100) % 100, value % 100)
    except ValueError as exc:
        raise CoverageBasisError("historical date is malformed") from exc


def _hash_pairs(values: Any) -> str:
    return sha256_hex(
        canonical_json([[symbol, trading_day] for symbol, trading_day in sorted(values)])
    )


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _schema_hash() -> str:
    schema = research_security_daily_schema()
    descriptor = [(name, str(schema[name])) for name in schema]
    return sha256_hex(canonical_json(descriptor))


def _coverage_rank(state: CoverageState) -> int:
    return {
        CoverageState.OBSERVED_DAILY_BAR_COVERAGE: 0,
        CoverageState.PARTIAL_OBSERVED_DAILY_BAR_COVERAGE: 1,
        CoverageState.UNRESOLVED_NOT_FOR_RESEARCH: 2,
    }[state]


@dataclass(frozen=True)
class AuthoritativeSourceSelection:
    """The reviewed source-selection binding for the CR-7 evidence path.

    A source-selection fingerprint is not an arbitrary caller label.  It is
    the hash of this exact, intentionally narrow binding.  The binding is
    still only a routing identity: it does not turn a provider response into
    completeness evidence without the typed acquisition receipt below.
    """

    selection_version: str
    source_class: str
    provider: str
    retrieval_surface: str
    methods: tuple[str, ...]
    source_domain: str
    selection_fingerprint: str

    def __post_init__(self) -> None:
        try:
            for field_name in (
                "selection_version",
                "source_class",
                "provider",
                "retrieval_surface",
                "source_domain",
            ):
                _require_non_empty_string(getattr(self, field_name), field_name)
            if not self.methods or any(
                not isinstance(method, str) or not method.strip() for method in self.methods
            ):
                raise CoverageBasisError("authoritative source-selection methods are malformed")
            if len(self.methods) != len(set(self.methods)):
                raise CoverageBasisError("authoritative source-selection methods are duplicated")
            fingerprint = _require_sha256(
                self.selection_fingerprint, "source_selection_fingerprint"
            )
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        if self.source_domain != "daily_bar":
            raise CoverageBasisError("authoritative source-selection domain must be daily_bar")
        expected_binding = {
            "selection_version": AUTHORITATIVE_SOURCE_SELECTION_VERSION,
            "source_class": AUTHORITATIVE_SOURCE_CLASS,
            "provider": AUTHORITATIVE_PROVIDER,
            "retrieval_surface": AUTHORITATIVE_RETRIEVAL_SURFACE,
            "methods": list(AUTHORITATIVE_SOURCE_METHODS),
            "source_domain": "daily_bar",
        }
        if self.as_dict(include_fingerprint=False) != expected_binding:
            raise CoverageBasisError(
                "authoritative source-selection binding is not the reviewed "
                "AmazingData history path"
            )
        if fingerprint != sha256_hex(canonical_json(expected_binding)):
            raise CoverageBasisError("source_selection_fingerprint does not match its binding")

    @classmethod
    def reviewed_amazingdata_history(cls) -> AuthoritativeSourceSelection:
        """Return the only source-selection binding accepted by this adapter."""
        binding: dict[str, Any] = {
            "selection_version": AUTHORITATIVE_SOURCE_SELECTION_VERSION,
            "source_class": AUTHORITATIVE_SOURCE_CLASS,
            "provider": AUTHORITATIVE_PROVIDER,
            "retrieval_surface": AUTHORITATIVE_RETRIEVAL_SURFACE,
            "methods": list(AUTHORITATIVE_SOURCE_METHODS),
            "source_domain": "daily_bar",
        }
        return cls(
            selection_version=binding["selection_version"],
            source_class=binding["source_class"],
            provider=binding["provider"],
            retrieval_surface=binding["retrieval_surface"],
            methods=tuple(binding["methods"]),
            source_domain=binding["source_domain"],
            selection_fingerprint=sha256_hex(canonical_json(binding)),
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AuthoritativeSourceSelection:
        fields = {
            "selection_version",
            "source_class",
            "provider",
            "retrieval_surface",
            "methods",
            "source_domain",
            "selection_fingerprint",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise CoverageBasisError("authoritative source-selection fields are not exact")
        methods = payload["methods"]
        if not isinstance(methods, list):
            raise CoverageBasisError("authoritative source-selection methods must be a list")
        try:
            return cls(
                selection_version=_require_non_empty_string(
                    payload["selection_version"], "selection_version"
                ),
                source_class=_require_non_empty_string(payload["source_class"], "source_class"),
                provider=_require_non_empty_string(payload["provider"], "provider"),
                retrieval_surface=_require_non_empty_string(
                    payload["retrieval_surface"], "retrieval_surface"
                ),
                methods=tuple(
                    _require_non_empty_string(method, "source-selection method")
                    for method in methods
                ),
                source_domain=_require_non_empty_string(payload["source_domain"], "source_domain"),
                selection_fingerprint=_require_sha256(
                    payload["selection_fingerprint"], "selection_fingerprint"
                ),
            )
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc

    def as_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "selection_version": self.selection_version,
            "source_class": self.source_class,
            "provider": self.provider,
            "retrieval_surface": self.retrieval_surface,
            "methods": list(self.methods),
            "source_domain": self.source_domain,
        }
        if include_fingerprint:
            payload["selection_fingerprint"] = self.selection_fingerprint
        return payload


@dataclass(frozen=True, init=False)
class VerifiedSourceSnapshot:
    """The already-verified CR-4 snapshot identity used by acquisition.

    The class deliberately has no public constructor.  A source snapshot is
    admitted to the authoritative path only from the typed
    ``VerifiedResearchProjection`` returned by the R1 read-model boundary;
    callers cannot pass a free-form id/hash/timestamp triple to mint a
    receipt.
    """

    source_snapshot_id: str
    source_snapshot_as_of: datetime
    source_snapshot_manifest_hash: str
    source_snapshot_semantic_hash: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("VerifiedSourceSnapshot must come from a verified projection")

    @classmethod
    def from_projection(cls, projection: VerifiedResearchProjection) -> VerifiedSourceSnapshot:
        if not isinstance(projection, VerifiedResearchProjection):
            raise CoverageBasisError("authoritative acquisition needs a verified source projection")
        try:
            source_snapshot_id = _require_non_empty_string(
                projection.source_snapshot_id, "source_snapshot_id"
            )
            source_snapshot_as_of = ensure_utc_timestamp(projection.source_snapshot_as_of)
            source_snapshot_manifest_hash = _require_sha256(
                projection.source_snapshot_manifest_hash, "source_snapshot_manifest_hash"
            )
            source_snapshot_semantic_hash = _require_sha256(
                projection.source_snapshot_semantic_hash, "source_snapshot_semantic_hash"
            )
        except (HistoricalMaterializationError, ResearchPanelError) as exc:
            raise CoverageBasisError("verified source snapshot identity is malformed") from exc
        obj = object.__new__(cls)
        object.__setattr__(obj, "source_snapshot_id", source_snapshot_id)
        object.__setattr__(obj, "source_snapshot_as_of", source_snapshot_as_of)
        object.__setattr__(obj, "source_snapshot_manifest_hash", source_snapshot_manifest_hash)
        object.__setattr__(obj, "source_snapshot_semantic_hash", source_snapshot_semantic_hash)
        return obj

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_as_of": self.source_snapshot_as_of,
            "source_snapshot_manifest_hash": self.source_snapshot_manifest_hash,
            "source_snapshot_semantic_hash": self.source_snapshot_semantic_hash,
        }


@dataclass(frozen=True)
class AmazingDataExchangeReceipt:
    """One retained, hash-addressed exchange in the approved history path."""

    method: str
    operation_id: str
    request_params_hash: str
    response_shape: str
    response_schema_hash: str
    response_content_hash: str
    row_count: int
    captured_evidence_uri: str
    captured_evidence_hash: str

    def __post_init__(self) -> None:
        try:
            for field_name in (
                "method",
                "operation_id",
                "response_shape",
                "captured_evidence_uri",
            ):
                _require_non_empty_string(getattr(self, field_name), field_name)
            for field_name in (
                "request_params_hash",
                "response_schema_hash",
                "response_content_hash",
                "captured_evidence_hash",
            ):
                _require_sha256(getattr(self, field_name), field_name)
            _safe_relative_uri(self.captured_evidence_uri, "captured_evidence_uri")
            if self.method == "MarketData.query_snapshot":
                _require_nonnegative_int(self.row_count, "row_count")
            else:
                _require_positive_int(self.row_count, "row_count")
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AmazingDataExchangeReceipt:
        fields = {
            "method",
            "operation_id",
            "request_params_hash",
            "response_shape",
            "response_schema_hash",
            "response_content_hash",
            "row_count",
            "captured_evidence_uri",
            "captured_evidence_hash",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise CoverageBasisError("AmazingData exchange receipt fields are not exact")
        try:
            return cls(
                method=_require_non_empty_string(payload["method"], "method"),
                operation_id=_require_non_empty_string(payload["operation_id"], "operation_id"),
                request_params_hash=_require_sha256(
                    payload["request_params_hash"], "request_params_hash"
                ),
                response_shape=_require_non_empty_string(
                    payload["response_shape"], "response_shape"
                ),
                response_schema_hash=_require_sha256(
                    payload["response_schema_hash"], "response_schema_hash"
                ),
                response_content_hash=_require_sha256(
                    payload["response_content_hash"], "response_content_hash"
                ),
                row_count=(
                    _require_nonnegative_int(payload["row_count"], "row_count")
                    if payload["method"] == "MarketData.query_snapshot"
                    else _require_positive_int(payload["row_count"], "row_count")
                ),
                captured_evidence_uri=_require_non_empty_string(
                    payload["captured_evidence_uri"], "captured_evidence_uri"
                ),
                captured_evidence_hash=_require_sha256(
                    payload["captured_evidence_hash"], "captured_evidence_hash"
                ),
            )
        except (HistoricalMaterializationError, KeyError, TypeError) as exc:
            raise CoverageBasisError("AmazingData exchange receipt is malformed") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "operation_id": self.operation_id,
            "request_params_hash": self.request_params_hash,
            "response_shape": self.response_shape,
            "response_schema_hash": self.response_schema_hash,
            "response_content_hash": self.response_content_hash,
            "row_count": self.row_count,
            "captured_evidence_uri": self.captured_evidence_uri,
            "captured_evidence_hash": self.captured_evidence_hash,
        }


@dataclass(frozen=True)
class PositiveTradeFallbackOperation:
    """One exact pair bound to one retained snapshot exchange."""

    security: str
    trading_day: int
    exchange: AmazingDataExchangeReceipt

    def __post_init__(self) -> None:
        try:
            if re.fullmatch(r"\d{6}\.(?:SH|SZ)", self.security) is None:
                raise CoverageBasisError("positive-trade fallback security is malformed")
            _day_to_date(self.trading_day)
        except (CoverageBasisError, TypeError) as exc:
            raise CoverageBasisError(str(exc)) from exc
        if not isinstance(self.exchange, AmazingDataExchangeReceipt):
            raise CoverageBasisError("positive-trade fallback exchange is not typed")
        operation_id, response_shape = _AMAZINGDATA_POSITIVE_TRADE_OPERATION_BINDING
        if (
            self.exchange.method != "MarketData.query_snapshot"
            or self.exchange.operation_id != operation_id
            or self.exchange.response_shape != response_shape
            or self.exchange.row_count <= 0
        ):
            raise CoverageBasisError("positive-trade fallback exchange is not an accepted snapshot")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PositiveTradeFallbackOperation:
        fields = {"security", "trading_day", "exchange"}
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise CoverageBasisError("positive-trade fallback operation fields are not exact")
        try:
            security = payload["security"]
            trading_day = payload["trading_day"]
            if not isinstance(security, str):
                raise CoverageBasisError("positive-trade fallback security is malformed")
            if isinstance(trading_day, bool) or not isinstance(trading_day, int):
                raise CoverageBasisError("positive-trade fallback date is malformed")
            return cls(
                security=security,
                trading_day=trading_day,
                exchange=AmazingDataExchangeReceipt.from_mapping(payload["exchange"]),
            )
        except (CoverageBasisError, KeyError, TypeError) as exc:
            raise CoverageBasisError("positive-trade fallback operation is malformed") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "security": self.security,
            "trading_day": self.trading_day,
            "exchange": self.exchange.as_dict(),
        }


def _amazingdata_capture_catalog(
    *,
    source_selection_fingerprint: str,
    source_snapshot_id: str,
    source_snapshot_manifest_hash: str,
    source_snapshot_semantic_hash: str,
    source_snapshot_as_of: datetime,
    requested_scope_start: date,
    requested_scope_end: date,
    operations: tuple[AmazingDataExchangeReceipt, ...],
    semantic_operations: tuple[AmazingDataExchangeReceipt, ...],
    positive_trade_operations: tuple[PositiveTradeFallbackOperation, ...],
    completeness_evaluation: MonthCompletenessEvaluation,
) -> dict[str, Any]:
    """Return the deterministic catalog identity used as the receipt proof."""
    return {
        "receipt_version": AMAZINGDATA_ACQUISITION_RECEIPT_VERSION,
        "source_selection_fingerprint": source_selection_fingerprint,
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_manifest_hash": source_snapshot_manifest_hash,
        "source_snapshot_semantic_hash": source_snapshot_semantic_hash,
        "source_snapshot_as_of": source_snapshot_as_of,
        "requested_scope_start": requested_scope_start,
        "requested_scope_end": requested_scope_end,
        "operations": [operation.as_dict() for operation in operations],
        "semantic_operations": [operation.as_dict() for operation in semantic_operations],
        "positive_trade_fallback_version": AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION,
        "positive_trade_operations": [
            operation.as_dict() for operation in positive_trade_operations
        ],
        "completeness_evaluation": completeness_evaluation.as_dict(),
    }


@dataclass(frozen=True, init=False)
class _VerifiedAmazingDataCapture:
    """Facts emitted only after the reviewed provider path has validated data.

    This is intentionally private and has no public constructor.  Keeping the
    derived counts, ranges and retrieval timestamp behind one typed object
    prevents the receipt issuer from exposing a call surface that accepts
    caller-selected authority facts one field at a time.
    """

    requested_scope_start: date
    requested_scope_end: date
    security_universe_count: int
    security_universe_hash: str
    calendar_trading_day_count: int
    calendar_trading_days_hash: str
    returned_first_date: date
    returned_last_date: date
    returned_trading_day_count: int
    returned_trading_days_hash: str
    returned_row_count: int
    operations: tuple[AmazingDataExchangeReceipt, ...]
    semantic_operations: tuple[AmazingDataExchangeReceipt, ...]
    positive_trade_operations: tuple[PositiveTradeFallbackOperation, ...]
    completeness_evaluation: MonthCompletenessEvaluation
    retrieved_at_utc: datetime

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("verified AmazingData capture must come from the provider path")

    @classmethod
    def _from_provider(
        cls,
        *,
        requested_scope_start: date,
        requested_scope_end: date,
        security_universe_count: int,
        security_universe_hash: str,
        calendar_trading_day_count: int,
        calendar_trading_days_hash: str,
        returned_first_date: date,
        returned_last_date: date,
        returned_trading_day_count: int,
        returned_trading_days_hash: str,
        returned_row_count: int,
        operations: tuple[AmazingDataExchangeReceipt, ...],
        semantic_operations: tuple[AmazingDataExchangeReceipt, ...],
        positive_trade_operations: tuple[PositiveTradeFallbackOperation, ...],
        completeness_evaluation: MonthCompletenessEvaluation,
        retrieved_at_utc: datetime,
    ) -> _VerifiedAmazingDataCapture:
        obj = object.__new__(cls)
        for field_name, value in {
            "requested_scope_start": requested_scope_start,
            "requested_scope_end": requested_scope_end,
            "security_universe_count": security_universe_count,
            "security_universe_hash": security_universe_hash,
            "calendar_trading_day_count": calendar_trading_day_count,
            "calendar_trading_days_hash": calendar_trading_days_hash,
            "returned_first_date": returned_first_date,
            "returned_last_date": returned_last_date,
            "returned_trading_day_count": returned_trading_day_count,
            "returned_trading_days_hash": returned_trading_days_hash,
            "returned_row_count": returned_row_count,
            "operations": operations,
            "semantic_operations": semantic_operations,
            "positive_trade_operations": positive_trade_operations,
            "completeness_evaluation": completeness_evaluation,
            "retrieved_at_utc": retrieved_at_utc,
        }.items():
            object.__setattr__(obj, field_name, value)
        obj._validate()
        return obj

    def _validate(self) -> None:
        for field_name in (
            "requested_scope_start",
            "requested_scope_end",
            "returned_first_date",
            "returned_last_date",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, date) or isinstance(value, datetime):
                raise CoverageBasisError(f"capture {field_name} must be a date")
        if self.requested_scope_start.day != 1 or self.requested_scope_end != _month_end(
            self.requested_scope_start.year, self.requested_scope_start.month
        ):
            raise CoverageBasisError("capture scope must be one complete calendar month")
        if self.returned_first_date > self.returned_last_date or (
            self.returned_first_date < self.requested_scope_start
            or self.returned_last_date > self.requested_scope_end
        ):
            raise CoverageBasisError("capture returned date range is outside requested scope")
        for field_name in (
            "security_universe_hash",
            "calendar_trading_days_hash",
            "returned_trading_days_hash",
        ):
            _require_sha256(getattr(self, field_name), f"capture {field_name}")
        for field_name in (
            "security_universe_count",
            "calendar_trading_day_count",
            "returned_trading_day_count",
            "returned_row_count",
        ):
            _require_positive_int(getattr(self, field_name), f"capture {field_name}")
        if (
            not isinstance(self.operations, tuple)
            or len(self.operations) != len(AUTHORITATIVE_SOURCE_METHODS)
            or any(
                not isinstance(operation, AmazingDataExchangeReceipt)
                for operation in self.operations
            )
        ):
            raise CoverageBasisError("capture exchange set is not typed or complete")
        operations_by_method = {operation.method: operation for operation in self.operations}
        if set(operations_by_method) != set(AUTHORITATIVE_SOURCE_METHODS):
            raise CoverageBasisError("capture exchange method set is not reviewed")
        if len(operations_by_method) != len(self.operations):
            raise CoverageBasisError("capture exchange methods are duplicated")
        if (
            not isinstance(self.semantic_operations, tuple)
            or len(self.semantic_operations) != self.calendar_trading_day_count
            or any(
                not isinstance(operation, AmazingDataExchangeReceipt)
                for operation in self.semantic_operations
            )
            or any(
                operation.method != "BaseData.get_hist_code_list"
                or operation.response_shape != "list[str]"
                for operation in self.semantic_operations
            )
        ):
            raise CoverageBasisError("capture exact-session semantic exchanges are malformed")
        if not isinstance(self.completeness_evaluation, MonthCompletenessEvaluation):
            raise CoverageBasisError("capture completeness evaluation is not typed")
        if (
            not isinstance(self.positive_trade_operations, tuple)
            or any(
                not isinstance(operation, PositiveTradeFallbackOperation)
                for operation in self.positive_trade_operations
            )
            or len(self.positive_trade_operations)
            != self.completeness_evaluation.positive_trade_pair_count
            or len(
                {
                    (operation.security, operation.trading_day)
                    for operation in self.positive_trade_operations
                }
            )
            != len(self.positive_trade_operations)
            or _hash_pairs(
                (operation.security, operation.trading_day)
                for operation in self.positive_trade_operations
            )
            != self.completeness_evaluation.positive_trade_pair_set_hash
        ):
            raise CoverageBasisError("capture positive-trade fallback exchanges are malformed")
        if not self.completeness_evaluation.accepted:
            raise CoverageBasisError("capture completeness evaluation is not accepted")
        evaluation = self.completeness_evaluation
        if (
            evaluation.positive_trade_fallback_version
            != AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION
        ):
            raise CoverageBasisError("capture positive-trade fallback version is not reviewed")
        if (
            evaluation.monthly_security_count != self.security_universe_count
            or evaluation.monthly_security_set_hash != self.security_universe_hash
            or evaluation.session_count != self.calendar_trading_day_count
            or evaluation.session_set_hash != self.calendar_trading_days_hash
            or evaluation.returned_first_date != self.returned_first_date
            or evaluation.returned_last_date != self.returned_last_date
            or evaluation.returned_trading_day_count != self.returned_trading_day_count
            or evaluation.returned_trading_days_hash != self.returned_trading_days_hash
            or evaluation.returned_row_count != self.returned_row_count
        ):
            raise CoverageBasisError("capture completeness evaluation is not derived")
        if (
            operations_by_method["BaseData.get_hist_code_list"].row_count
            != self.security_universe_count
        ):
            raise CoverageBasisError(
                "capture universe count is not derived from the retained response"
            )
        if (
            operations_by_method["BaseData.get_calendar"].row_count
            < self.calendar_trading_day_count
        ):
            raise CoverageBasisError(
                "capture calendar response does not cover the requested window"
            )
        if operations_by_method["MarketData.query_kline"].row_count != self.returned_row_count:
            raise CoverageBasisError("capture bar count is not derived from the retained response")
        try:
            ensure_utc_timestamp(self.retrieved_at_utc)
        except ResearchPanelError as exc:
            raise CoverageBasisError("capture retrieval timestamp is invalid") from exc


@dataclass(frozen=True, init=False)
class AmazingDataAcquisitionReceipt:
    """Typed proof emitted only by the reviewed AmazingData acquisition path.

    ``init=False`` is intentional.  The public object can be rehydrated for
    committed-reader replay, but a new authoritative receipt can only be
    issued by the private provider-path factory after response validation.
    Counts, timestamps and opaque statement bytes are not constructor inputs.
    """

    receipt_id: str
    receipt_version: str
    source_selection: AuthoritativeSourceSelection
    source_snapshot_id: str
    source_snapshot_manifest_hash: str
    source_snapshot_semantic_hash: str
    source_snapshot_as_of: datetime
    requested_scope_start: date
    requested_scope_end: date
    security_universe_selection: str
    security_universe_id: str
    security_universe_count: int
    security_universe_hash: str
    calendar_market: str
    calendar_scope_start: date
    calendar_scope_end: date
    calendar_trading_day_count: int
    calendar_trading_days_hash: str
    returned_security_count: int
    returned_security_set_hash: str
    returned_first_date: date
    returned_last_date: date
    returned_trading_day_count: int
    returned_trading_days_hash: str
    returned_row_count: int
    operations: tuple[AmazingDataExchangeReceipt, ...]
    semantic_operations: tuple[AmazingDataExchangeReceipt, ...]
    positive_trade_fallback_version: str
    positive_trade_operations: tuple[PositiveTradeFallbackOperation, ...]
    completeness_evaluation: MonthCompletenessEvaluation
    retrieved_at_utc: datetime
    available_at: datetime
    pit_as_of: datetime
    source_capture_uri: str
    source_capture_hash: str
    completeness_statement_id: str
    receipt_hash: str
    _provenance: str = dataclass_field(default="", init=False, repr=False, compare=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError(
            "AmazingDataAcquisitionReceipt must come from the reviewed acquisition path"
        )

    @classmethod
    def _construct(
        cls,
        values: Mapping[str, Any],
        *,
        provenance: str,
    ) -> AmazingDataAcquisitionReceipt:
        obj = object.__new__(cls)
        for field_name in (
            "receipt_id",
            "receipt_version",
            "source_selection",
            "source_snapshot_id",
            "source_snapshot_manifest_hash",
            "source_snapshot_semantic_hash",
            "source_snapshot_as_of",
            "requested_scope_start",
            "requested_scope_end",
            "security_universe_selection",
            "security_universe_id",
            "security_universe_count",
            "security_universe_hash",
            "calendar_market",
            "calendar_scope_start",
            "calendar_scope_end",
            "calendar_trading_day_count",
            "calendar_trading_days_hash",
            "returned_security_count",
            "returned_security_set_hash",
            "returned_first_date",
            "returned_last_date",
            "returned_trading_day_count",
            "returned_trading_days_hash",
            "returned_row_count",
            "operations",
            "semantic_operations",
            "positive_trade_fallback_version",
            "positive_trade_operations",
            "completeness_evaluation",
            "retrieved_at_utc",
            "available_at",
            "pit_as_of",
            "source_capture_uri",
            "source_capture_hash",
            "completeness_statement_id",
            "receipt_hash",
        ):
            object.__setattr__(obj, field_name, values[field_name])
        object.__setattr__(obj, "_provenance", provenance)
        obj._validate()
        return obj

    @property
    def is_verified_capture(self) -> bool:
        return self._provenance == "verified_capture"

    def capture_catalog(self) -> dict[str, Any]:
        """Return the canonical catalog whose hash identifies this receipt."""
        return _amazingdata_capture_catalog(
            source_selection_fingerprint=self.source_selection.selection_fingerprint,
            source_snapshot_id=self.source_snapshot_id,
            source_snapshot_manifest_hash=self.source_snapshot_manifest_hash,
            source_snapshot_semantic_hash=self.source_snapshot_semantic_hash,
            source_snapshot_as_of=self.source_snapshot_as_of,
            requested_scope_start=self.requested_scope_start,
            requested_scope_end=self.requested_scope_end,
            operations=self.operations,
            semantic_operations=self.semantic_operations,
            positive_trade_operations=self.positive_trade_operations,
            completeness_evaluation=self.completeness_evaluation,
        )

    def verify_retained_capture(self, raw_root: Path | str) -> None:
        """Replay the catalog and every retained RawWriter evidence anchor.

        The receipt hash is not treated as a standalone trust root.  This
        method follows its catalog URI and each exchange evidence URI back to
        immutable local bytes, then rechecks the RawWriter payload closure.
        """
        root = Path(raw_root)
        expected_catalog = canonical_json(self.capture_catalog()).encode("utf-8")
        catalog_path = root.joinpath(*self.source_capture_uri.split("/"))
        if not catalog_path.is_file():
            raise CoverageBasisError("AmazingData capture catalog is not retained")
        if catalog_path.read_bytes() != expected_catalog:
            raise CoverageBasisError("AmazingData capture catalog bytes changed")
        if sha256_hex(expected_catalog) != self.source_capture_hash:
            raise CoverageBasisError("AmazingData capture catalog hash changed")

        from ashare_state.storage.raw_writer import verify_meta_closure

        for operation in self.operations:
            evidence_path = root.joinpath(*operation.captured_evidence_uri.split("/"))
            if not evidence_path.is_file():
                raise CoverageBasisError(
                    f"AmazingData retained evidence is missing for {operation.method}"
                )
            evidence_bytes = evidence_path.read_bytes()
            if sha256_hex(evidence_bytes) != operation.captured_evidence_hash:
                raise CoverageBasisError(
                    f"AmazingData retained evidence hash changed for {operation.method}"
                )
            try:
                evidence = json.loads(evidence_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CoverageBasisError(
                    f"AmazingData retained evidence is not valid JSON for {operation.method}"
                ) from exc
            if not isinstance(evidence, Mapping):
                raise CoverageBasisError(
                    f"AmazingData retained evidence is not an object for {operation.method}"
                )
            if not _retained_request_matches_receipt(
                self,
                operation.method,
                evidence.get("request_params"),
            ):
                raise CoverageBasisError(
                    f"AmazingData retained request scope changed for {operation.method}"
                )
            if (
                evidence.get("status") != "OK"
                or evidence.get("operation_id") != operation.operation_id
                or evidence.get("request_params_hash") != operation.request_params_hash
                or evidence.get("content_hash") != operation.response_content_hash
                or evidence.get("row_count") != operation.row_count
            ):
                raise CoverageBasisError(
                    f"AmazingData retained evidence identity changed for {operation.method}"
                )
            tables = evidence.get("tables")
            if not isinstance(tables, list):
                raise CoverageBasisError(
                    f"AmazingData retained evidence tables are malformed for {operation.method}"
                )
            schema_parts = sorted(
                (str(table.get("name")), str(table.get("schema_hash")))
                for table in tables
                if isinstance(table, Mapping)
            )
            if len(schema_parts) != len(tables) or sha256_hex(canonical_json(schema_parts)) != (
                operation.response_schema_hash
            ):
                raise CoverageBasisError(
                    f"AmazingData retained evidence schema changed for {operation.method}"
                )
            problems = verify_meta_closure(evidence_path.parent, dict(evidence))
            if problems:
                raise CoverageBasisError(
                    f"AmazingData retained payload closure failed for {operation.method}: "
                    + "; ".join(problems)
                )
        for operation in self.semantic_operations:
            evidence_path = root.joinpath(*operation.captured_evidence_uri.split("/"))
            if not evidence_path.is_file():
                raise CoverageBasisError("AmazingData retained exact-session evidence is missing")
            evidence_bytes = evidence_path.read_bytes()
            if sha256_hex(evidence_bytes) != operation.captured_evidence_hash:
                raise CoverageBasisError("AmazingData retained exact-session evidence hash changed")
            try:
                evidence = json.loads(evidence_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CoverageBasisError(
                    "AmazingData retained exact-session evidence is not valid JSON"
                ) from exc
            if not isinstance(evidence, Mapping):
                raise CoverageBasisError(
                    "AmazingData retained exact-session evidence is not an object"
                )
            if not _retained_request_matches_receipt(
                self,
                operation.method,
                evidence.get("request_params"),
                exact_session=True,
            ):
                raise CoverageBasisError("AmazingData retained exact-session request scope changed")
            if (
                evidence.get("status") != "OK"
                or evidence.get("operation_id") != operation.operation_id
                or evidence.get("request_params_hash") != operation.request_params_hash
                or evidence.get("content_hash") != operation.response_content_hash
                or evidence.get("row_count") != operation.row_count
            ):
                raise CoverageBasisError(
                    "AmazingData retained exact-session evidence identity changed"
                )
            tables = evidence.get("tables")
            if not isinstance(tables, list):
                raise CoverageBasisError(
                    "AmazingData retained exact-session evidence tables are malformed"
                )
            schema_parts = sorted(
                (str(table.get("name")), str(table.get("schema_hash")))
                for table in tables
                if isinstance(table, Mapping)
            )
            if len(schema_parts) != len(tables) or sha256_hex(canonical_json(schema_parts)) != (
                operation.response_schema_hash
            ):
                raise CoverageBasisError(
                    "AmazingData retained exact-session evidence schema changed"
                )
            problems = verify_meta_closure(evidence_path.parent, dict(evidence))
            if problems:
                raise CoverageBasisError(
                    "AmazingData retained exact-session payload closure failed: "
                    + "; ".join(problems)
                )

        for fallback in self.positive_trade_operations:
            operation = fallback.exchange
            evidence_path = root.joinpath(*operation.captured_evidence_uri.split("/"))
            if not evidence_path.is_file():
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot evidence is missing"
                )
            evidence_bytes = evidence_path.read_bytes()
            if sha256_hex(evidence_bytes) != operation.captured_evidence_hash:
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot evidence hash changed"
                )
            try:
                evidence = json.loads(evidence_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot evidence is not valid JSON"
                ) from exc
            if not isinstance(evidence, Mapping):
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot evidence is not an object"
                )
            if not _retained_request_matches_receipt(
                self,
                operation.method,
                evidence.get("request_params"),
                exact_snapshot=True,
                snapshot_security=fallback.security,
                snapshot_trading_day=fallback.trading_day,
            ):
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot request scope changed"
                )
            if (
                evidence.get("status") != "OK"
                or evidence.get("operation_id") != operation.operation_id
                or evidence.get("request_params_hash") != operation.request_params_hash
                or evidence.get("content_hash") != operation.response_content_hash
                or evidence.get("row_count") != operation.row_count
            ):
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot identity changed"
                )
            tables = evidence.get("tables")
            if not isinstance(tables, list):
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot tables are malformed"
                )
            schema_parts = sorted(
                (str(table.get("name")), str(table.get("schema_hash")))
                for table in tables
                if isinstance(table, Mapping)
            )
            if len(schema_parts) != len(tables) or sha256_hex(canonical_json(schema_parts)) != (
                operation.response_schema_hash
            ):
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot schema changed"
                )
            problems = verify_meta_closure(evidence_path.parent, dict(evidence))
            if problems:
                raise CoverageBasisError(
                    "AmazingData retained positive-trade snapshot payload closure failed: "
                    + "; ".join(problems)
                )

        try:
            base_operations = {operation.method: operation for operation in self.operations}
            calendar_payload, _calendar_meta = _read_retained_operation_payload(
                root, self, base_operations["BaseData.get_calendar"]
            )
            code_payload, _code_meta = _read_retained_operation_payload(
                root, self, base_operations["BaseData.get_hist_code_list"]
            )
            status_payload, _status_meta = _read_retained_operation_payload(
                root, self, base_operations["InfoData.get_history_stock_status"]
            )
            daily_payload, _daily_meta = _read_retained_operation_payload(
                root, self, base_operations["MarketData.query_kline"]
            )
            exact_day_universes: dict[int, list[str]] = {}
            for operation in self.semantic_operations:
                payload, meta = _read_retained_operation_payload(
                    root, self, operation, exact_session=True
                )
                params = meta.get("request_params")
                if not isinstance(params, Mapping) or not isinstance(params.get("start_date"), int):
                    raise CoverageBasisError(
                        "AmazingData retained exact-session request is malformed"
                    )
                exact_day_universes[int(params["start_date"])] = _single_value_column(payload)
            positive_trade_pairs: list[tuple[str, int]] = []
            positive_trade_hashes: dict[tuple[str, int], str] = {}
            for fallback in self.positive_trade_operations:
                payload, _meta = _read_retained_operation_payload(
                    root,
                    self,
                    fallback.exchange,
                    exact_snapshot=True,
                    snapshot_security=fallback.security,
                    snapshot_trading_day=fallback.trading_day,
                )
                positive, errors = _snapshot_trade_observation(
                    payload,
                    symbol=fallback.security,
                    trading_day=fallback.trading_day,
                )
                if errors or not positive:
                    raise CoverageBasisError(
                        "AmazingData retained positive-trade snapshot no longer proves activity"
                    )
                positive_trade_pairs.append((fallback.security, fallback.trading_day))
                positive_trade_hashes[(fallback.security, fallback.trading_day)] = (
                    fallback.exchange.request_params_hash
                )
            positive_trade_evidence = _PositiveTradeFallbackEvidence._from_provider(  # noqa: SLF001
                queried_pairs=positive_trade_pairs,
                positive_pairs=positive_trade_pairs,
                request_params_by_pair=positive_trade_hashes,
            )
            evaluation = evaluate_month_completeness(
                monthly_symbols=_single_value_column(code_payload),
                trading_days=_calendar_values_for_receipt(calendar_payload, self),
                exact_day_universes=exact_day_universes,
                status_payload=status_payload,
                daily_bar_payload=daily_payload,
                positive_trade_fallback=(positive_trade_evidence if positive_trade_pairs else None),
            )
        except (KeyError, MonthCompletenessError, CoverageBasisError) as exc:
            raise CoverageBasisError(
                "AmazingData retained completeness semantics could not be replayed"
            ) from exc
        if evaluation.as_dict() != self.completeness_evaluation.as_dict():
            raise CoverageBasisError(
                "AmazingData retained completeness evaluation changed during replay"
            )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> AmazingDataAcquisitionReceipt:
        fields = {
            "receipt_id",
            "receipt_version",
            "source_selection",
            "source_snapshot_id",
            "source_snapshot_manifest_hash",
            "source_snapshot_semantic_hash",
            "source_snapshot_as_of",
            "requested_scope_start",
            "requested_scope_end",
            "security_universe_selection",
            "security_universe_id",
            "security_universe_count",
            "security_universe_hash",
            "calendar_market",
            "calendar_scope_start",
            "calendar_scope_end",
            "calendar_trading_day_count",
            "calendar_trading_days_hash",
            "returned_security_count",
            "returned_security_set_hash",
            "returned_first_date",
            "returned_last_date",
            "returned_trading_day_count",
            "returned_trading_days_hash",
            "returned_row_count",
            "operations",
            "semantic_operations",
            "positive_trade_fallback_version",
            "positive_trade_operations",
            "completeness_evaluation",
            "retrieved_at_utc",
            "available_at",
            "pit_as_of",
            "source_capture_uri",
            "source_capture_hash",
            "completeness_statement_id",
            "receipt_hash",
        }
        if not isinstance(payload, Mapping) or set(payload) != fields:
            raise CoverageBasisError("AmazingData acquisition receipt fields are not exact")
        try:
            raw_operations = payload["operations"]
            if not isinstance(raw_operations, list):
                raise CoverageBasisError("AmazingData acquisition receipt operations are malformed")
            raw_semantic_operations = payload["semantic_operations"]
            if not isinstance(raw_semantic_operations, list):
                raise CoverageBasisError(
                    "AmazingData exact-session semantic operations are malformed"
                )
            raw_positive_trade_operations = payload["positive_trade_operations"]
            if not isinstance(raw_positive_trade_operations, list):
                raise CoverageBasisError(
                    "AmazingData positive-trade fallback operations are malformed"
                )
            values: dict[str, Any] = {
                "receipt_id": _require_non_empty_string(payload["receipt_id"], "receipt_id"),
                "receipt_version": _require_non_empty_string(
                    payload["receipt_version"], "receipt_version"
                ),
                "source_selection": AuthoritativeSourceSelection.from_mapping(
                    payload["source_selection"]
                ),
                "source_snapshot_id": _require_non_empty_string(
                    payload["source_snapshot_id"], "source_snapshot_id"
                ),
                "source_snapshot_manifest_hash": _require_sha256(
                    payload["source_snapshot_manifest_hash"], "source_snapshot_manifest_hash"
                ),
                "source_snapshot_semantic_hash": _require_sha256(
                    payload["source_snapshot_semantic_hash"], "source_snapshot_semantic_hash"
                ),
                "source_snapshot_as_of": ensure_utc_timestamp(payload["source_snapshot_as_of"]),
                "requested_scope_start": parse_date_value(payload["requested_scope_start"]),
                "requested_scope_end": parse_date_value(payload["requested_scope_end"]),
                "security_universe_selection": _require_non_empty_string(
                    payload["security_universe_selection"], "security_universe_selection"
                ),
                "security_universe_id": _require_non_empty_string(
                    payload["security_universe_id"], "security_universe_id"
                ),
                "security_universe_count": _require_positive_int(
                    payload["security_universe_count"], "security_universe_count"
                ),
                "security_universe_hash": _require_sha256(
                    payload["security_universe_hash"], "security_universe_hash"
                ),
                "calendar_market": _require_non_empty_string(
                    payload["calendar_market"], "calendar_market"
                ),
                "calendar_scope_start": parse_date_value(payload["calendar_scope_start"]),
                "calendar_scope_end": parse_date_value(payload["calendar_scope_end"]),
                "calendar_trading_day_count": _require_positive_int(
                    payload["calendar_trading_day_count"], "calendar_trading_day_count"
                ),
                "calendar_trading_days_hash": _require_sha256(
                    payload["calendar_trading_days_hash"], "calendar_trading_days_hash"
                ),
                "returned_security_count": _require_positive_int(
                    payload["returned_security_count"], "returned_security_count"
                ),
                "returned_security_set_hash": _require_sha256(
                    payload["returned_security_set_hash"], "returned_security_set_hash"
                ),
                "returned_first_date": parse_date_value(payload["returned_first_date"]),
                "returned_last_date": parse_date_value(payload["returned_last_date"]),
                "returned_trading_day_count": _require_positive_int(
                    payload["returned_trading_day_count"], "returned_trading_day_count"
                ),
                "returned_trading_days_hash": _require_sha256(
                    payload["returned_trading_days_hash"], "returned_trading_days_hash"
                ),
                "returned_row_count": _require_positive_int(
                    payload["returned_row_count"], "returned_row_count"
                ),
                "operations": tuple(
                    AmazingDataExchangeReceipt.from_mapping(operation)
                    for operation in raw_operations
                ),
                "semantic_operations": tuple(
                    AmazingDataExchangeReceipt.from_mapping(operation)
                    for operation in raw_semantic_operations
                ),
                "positive_trade_fallback_version": _require_non_empty_string(
                    payload["positive_trade_fallback_version"],
                    "positive_trade_fallback_version",
                ),
                "positive_trade_operations": tuple(
                    PositiveTradeFallbackOperation.from_mapping(operation)
                    for operation in raw_positive_trade_operations
                ),
                "completeness_evaluation": MonthCompletenessEvaluation.from_mapping(
                    payload["completeness_evaluation"]
                ),
                "retrieved_at_utc": ensure_utc_timestamp(payload["retrieved_at_utc"]),
                "available_at": ensure_utc_timestamp(payload["available_at"]),
                "pit_as_of": ensure_utc_timestamp(payload["pit_as_of"]),
                "source_capture_uri": _require_non_empty_string(
                    payload["source_capture_uri"], "source_capture_uri"
                ),
                "source_capture_hash": _require_sha256(
                    payload["source_capture_hash"], "source_capture_hash"
                ),
                "completeness_statement_id": _require_non_empty_string(
                    payload["completeness_statement_id"], "completeness_statement_id"
                ),
                "receipt_hash": _require_sha256(payload["receipt_hash"], "receipt_hash"),
            }
        except (HistoricalMaterializationError, ResearchPanelError, KeyError, TypeError) as exc:
            raise CoverageBasisError("AmazingData acquisition receipt is malformed") from exc
        return cls._construct(values, provenance="replayed_catalog")

    def _validate(self) -> None:
        try:
            for field_name in (
                "receipt_id",
                "receipt_version",
                "source_snapshot_id",
                "security_universe_selection",
                "security_universe_id",
                "calendar_market",
                "source_capture_uri",
                "completeness_statement_id",
                "positive_trade_fallback_version",
            ):
                _require_non_empty_string(getattr(self, field_name), field_name)
            for field_name in (
                "source_snapshot_manifest_hash",
                "source_snapshot_semantic_hash",
                "security_universe_hash",
                "calendar_trading_days_hash",
                "returned_security_set_hash",
                "returned_trading_days_hash",
                "source_capture_hash",
                "receipt_hash",
            ):
                _require_sha256(getattr(self, field_name), field_name)
            _safe_relative_uri(self.source_capture_uri, "source_capture_uri")
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        if self.receipt_version != AMAZINGDATA_ACQUISITION_RECEIPT_VERSION:
            raise CoverageBasisError("unknown AmazingData acquisition receipt version")
        if self.source_selection != AuthoritativeSourceSelection.reviewed_amazingdata_history():
            raise CoverageBasisError(
                "receipt source selection is not the reviewed AmazingData path"
            )
        if self.security_universe_selection != AMAZINGDATA_SECURITY_UNIVERSE_SELECTION:
            raise CoverageBasisError("receipt security universe selection is not reviewed")
        if self.calendar_market != AMAZINGDATA_CALENDAR_MARKET:
            raise CoverageBasisError("receipt calendar market is not reviewed")
        if self.positive_trade_fallback_version != AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION:
            raise CoverageBasisError("receipt positive-trade fallback version is not reviewed")
        if not isinstance(self.operations, tuple) or len(self.operations) != len(
            AUTHORITATIVE_SOURCE_METHODS
        ):
            raise CoverageBasisError("receipt must contain exactly the reviewed exchanges")
        operations_by_method = {operation.method: operation for operation in self.operations}
        if set(operations_by_method) != set(AUTHORITATIVE_SOURCE_METHODS):
            raise CoverageBasisError("receipt exchange method set is not exact")
        if len(operations_by_method) != len(self.operations):
            raise CoverageBasisError("receipt exchange methods are duplicated")
        for method, (operation_id, response_shape) in _AMAZINGDATA_OPERATION_BINDINGS.items():
            operation = operations_by_method[method]
            if operation.operation_id != operation_id:
                raise CoverageBasisError("receipt operation identity is not provider-derived")
            if operation.response_shape != response_shape:
                raise CoverageBasisError("receipt response shape is not the reviewed shape")
        if (
            not isinstance(self.semantic_operations, tuple)
            or len(self.semantic_operations) != self.calendar_trading_day_count
            or any(
                not isinstance(operation, AmazingDataExchangeReceipt)
                or operation.method != "BaseData.get_hist_code_list"
                or operation.response_shape != "list[str]"
                for operation in self.semantic_operations
            )
        ):
            raise CoverageBasisError("receipt exact-session semantic operations are malformed")
        if (
            not isinstance(self.positive_trade_operations, tuple)
            or any(
                not isinstance(operation, PositiveTradeFallbackOperation)
                for operation in self.positive_trade_operations
            )
            or len(
                {
                    (operation.security, operation.trading_day)
                    for operation in self.positive_trade_operations
                }
            )
            != len(self.positive_trade_operations)
            or tuple(
                (operation.trading_day, operation.security)
                for operation in self.positive_trade_operations
            )
            != tuple(
                sorted(
                    (operation.trading_day, operation.security)
                    for operation in self.positive_trade_operations
                )
            )
        ):
            raise CoverageBasisError("receipt positive-trade fallback operations are malformed")
        if not isinstance(self.completeness_evaluation, MonthCompletenessEvaluation):
            raise CoverageBasisError("receipt completeness evaluation is not typed")
        evaluation = self.completeness_evaluation
        try:
            evaluation.require_accepted()
        except ValueError as exc:
            raise CoverageBasisError("receipt completeness evaluation is not accepted") from exc
        if evaluation.rule_version != AMAZINGDATA_MONTH_COMPLETENESS_RULE_VERSION:
            raise CoverageBasisError("receipt completeness rule version is not reviewed")
        if (
            evaluation.applicability_semantics_version
            != AMAZINGDATA_APPLICABILITY_SEMANTICS_VERSION
        ):
            raise CoverageBasisError("receipt applicability semantics version is not reviewed")
        if (
            evaluation.positive_trade_fallback_version != self.positive_trade_fallback_version
            or len(self.positive_trade_operations) != evaluation.positive_trade_pair_count
            or _hash_pairs(
                (operation.security, operation.trading_day)
                for operation in self.positive_trade_operations
            )
            != evaluation.positive_trade_pair_set_hash
        ):
            raise CoverageBasisError("receipt positive-trade fallback facts are not derived")
        for field_name in (
            "requested_scope_start",
            "requested_scope_end",
            "calendar_scope_start",
            "calendar_scope_end",
            "returned_first_date",
            "returned_last_date",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, date) or isinstance(value, datetime):
                raise CoverageBasisError(f"{field_name} must be a date")
        if self.requested_scope_start.day != 1 or self.requested_scope_end != _month_end(
            self.requested_scope_start.year, self.requested_scope_start.month
        ):
            raise CoverageBasisError("receipt requested scope must be one complete calendar month")
        if any(
            not (
                self.requested_scope_start
                <= _day_to_date(operation.trading_day)
                <= self.requested_scope_end
            )
            for operation in self.positive_trade_operations
        ):
            raise CoverageBasisError("receipt positive-trade fallback scope is outside month")
        if (self.calendar_scope_start, self.calendar_scope_end) != (
            self.requested_scope_start,
            self.requested_scope_end,
        ):
            raise CoverageBasisError("receipt calendar scope does not match requested scope")
        if self.security_universe_id != (
            f"hist-code-list:{self.security_universe_selection}:{self.security_universe_hash}"
        ):
            raise CoverageBasisError("receipt security universe identity is not derived")
        if self.returned_security_count != self.security_universe_count:
            raise CoverageBasisError(
                "receipt returned security count differs from requested universe"
            )
        if self.returned_security_set_hash != self.security_universe_hash:
            raise CoverageBasisError("receipt returned security universe hash differs")
        if self.returned_first_date > self.returned_last_date or (
            self.returned_first_date < self.requested_scope_start
            or self.returned_last_date > self.requested_scope_end
        ):
            raise CoverageBasisError("receipt returned date range is outside requested scope")
        if self.returned_trading_day_count != self.calendar_trading_day_count:
            raise CoverageBasisError("receipt returned trading-day count differs from calendar")
        if self.returned_trading_days_hash != self.calendar_trading_days_hash:
            raise CoverageBasisError("receipt returned trading-day hash differs from calendar")
        if (
            evaluation.monthly_security_count != self.security_universe_count
            or evaluation.monthly_security_set_hash != self.security_universe_hash
            or evaluation.session_count != self.calendar_trading_day_count
            or evaluation.session_set_hash != self.calendar_trading_days_hash
            or evaluation.returned_row_count != self.returned_row_count
            or evaluation.returned_bar_pair_count != self.returned_row_count
            or evaluation.returned_first_date != self.returned_first_date
            or evaluation.returned_last_date != self.returned_last_date
            or evaluation.returned_trading_day_count != self.returned_trading_day_count
            or evaluation.returned_trading_days_hash != self.returned_trading_days_hash
            or evaluation.missing_required_pair_count != 0
            or evaluation.extra_returned_pair_count != 0
            or evaluation.unresolved_pair_count != 0
        ):
            raise CoverageBasisError("receipt completeness evaluation is not derived")
        try:
            source_snapshot_as_of = ensure_utc_timestamp(self.source_snapshot_as_of)
            retrieved_at = ensure_utc_timestamp(self.retrieved_at_utc)
            available_at = ensure_utc_timestamp(self.available_at)
            pit_as_of = ensure_utc_timestamp(self.pit_as_of)
        except ResearchPanelError as exc:
            raise CoverageBasisError("receipt timestamps are invalid") from exc
        if available_at != retrieved_at:
            raise CoverageBasisError(
                "receipt available_at must be derived from exchange receipt time"
            )
        if pit_as_of != source_snapshot_as_of:
            raise CoverageBasisError("receipt PIT must be the verified source snapshot as_of")
        if retrieved_at > pit_as_of:
            raise CoverageBasisError("receipt was retrieved after its verified PIT snapshot")
        capture_catalog = self.capture_catalog()
        if self.source_capture_hash != sha256_hex(canonical_json(capture_catalog)):
            raise CoverageBasisError("receipt source capture catalog hash does not match")
        expected_receipt_id = f"amazingdata-history-receipt-{self.source_capture_hash[:32]}"
        if self.receipt_id != expected_receipt_id:
            raise CoverageBasisError("receipt id is not derived from the capture catalog")
        if self.source_capture_uri != f"source_capture/amazingdata/{self.receipt_id}.json":
            raise CoverageBasisError("receipt source capture URI is not derived")
        if (
            self.completeness_statement_id
            != f"amazingdata-complete-{self.source_capture_hash[:32]}"
        ):
            raise CoverageBasisError("receipt completeness statement id is not derived")
        if self.receipt_hash != sha256_hex(
            canonical_json(self.as_dict(include_receipt_hash=False))
        ):
            raise CoverageBasisError("receipt hash does not match canonical receipt fields")
        _require_positive_int(self.security_universe_count, "security_universe_count")
        _require_positive_int(self.calendar_trading_day_count, "calendar_trading_day_count")
        _require_positive_int(self.returned_security_count, "returned_security_count")
        _require_positive_int(self.returned_trading_day_count, "returned_trading_day_count")
        _require_positive_int(self.returned_row_count, "returned_row_count")

    def as_dict(self, *, include_receipt_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "receipt_id": self.receipt_id,
            "receipt_version": self.receipt_version,
            "source_selection": self.source_selection.as_dict(),
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_manifest_hash": self.source_snapshot_manifest_hash,
            "source_snapshot_semantic_hash": self.source_snapshot_semantic_hash,
            "source_snapshot_as_of": self.source_snapshot_as_of,
            "requested_scope_start": self.requested_scope_start,
            "requested_scope_end": self.requested_scope_end,
            "security_universe_selection": self.security_universe_selection,
            "security_universe_id": self.security_universe_id,
            "security_universe_count": self.security_universe_count,
            "security_universe_hash": self.security_universe_hash,
            "calendar_market": self.calendar_market,
            "calendar_scope_start": self.calendar_scope_start,
            "calendar_scope_end": self.calendar_scope_end,
            "calendar_trading_day_count": self.calendar_trading_day_count,
            "calendar_trading_days_hash": self.calendar_trading_days_hash,
            "returned_security_count": self.returned_security_count,
            "returned_security_set_hash": self.returned_security_set_hash,
            "returned_first_date": self.returned_first_date,
            "returned_last_date": self.returned_last_date,
            "returned_trading_day_count": self.returned_trading_day_count,
            "returned_trading_days_hash": self.returned_trading_days_hash,
            "returned_row_count": self.returned_row_count,
            "operations": [operation.as_dict() for operation in self.operations],
            "semantic_operations": [operation.as_dict() for operation in self.semantic_operations],
            "positive_trade_fallback_version": self.positive_trade_fallback_version,
            "positive_trade_operations": [
                operation.as_dict() for operation in self.positive_trade_operations
            ],
            "completeness_evaluation": self.completeness_evaluation.as_dict(),
            "retrieved_at_utc": self.retrieved_at_utc,
            "available_at": self.available_at,
            "pit_as_of": self.pit_as_of,
            "source_capture_uri": self.source_capture_uri,
            "source_capture_hash": self.source_capture_hash,
            "completeness_statement_id": self.completeness_statement_id,
        }
        if include_receipt_hash:
            payload["receipt_hash"] = self.receipt_hash
        return payload


def _retained_request_matches_receipt(
    receipt: AmazingDataAcquisitionReceipt,
    method: str,
    request_params: Any,
    *,
    exact_session: bool = False,
    exact_snapshot: bool = False,
    snapshot_security: str | None = None,
    snapshot_trading_day: int | None = None,
) -> bool:
    """Check the scrubbed RawWriter request against receipt-derived scope."""
    if not isinstance(request_params, Mapping):
        return False
    params = dict(request_params)
    start = _yyyymmdd(receipt.requested_scope_start)
    end = _yyyymmdd(receipt.requested_scope_end)
    if method == "BaseData.get_calendar":
        return params == {"market": receipt.calendar_market}
    if method == "BaseData.get_hist_code_list":
        if exact_session:
            start_date = params.get("start_date")
            end_date = params.get("end_date")
            if (
                isinstance(start_date, bool)
                or not isinstance(start_date, int)
                or isinstance(end_date, bool)
                or not isinstance(end_date, int)
            ):
                return False
            return params == {
                "security_type": receipt.security_universe_selection,
                "start_date": start_date,
                "end_date": start_date,
            }
        return params == {
            "security_type": receipt.security_universe_selection,
            "start_date": start,
            "end_date": end,
        }
    if method == "InfoData.get_history_stock_status":
        code_list = params.get("code_list")
        return (
            params.get("begin_date") == start
            and params.get("end_date") == end
            and params.get("is_local") is False
            and isinstance(code_list, list)
            and code_list == sorted(code_list)
            and len(code_list) == receipt.security_universe_count
            and len(code_list) == len(set(code_list))
            and sha256_hex(canonical_json(code_list)) == receipt.security_universe_hash
        )
    if method == "MarketData.query_snapshot":
        if (
            not exact_snapshot
            or not isinstance(snapshot_security, str)
            or re.fullmatch(r"\d{6}\.(?:SH|SZ)", snapshot_security) is None
            or snapshot_trading_day is None
            or isinstance(snapshot_trading_day, bool)
            or not isinstance(snapshot_trading_day, int)
        ):
            return False
        try:
            snapshot_date = _day_to_date(snapshot_trading_day)
        except CoverageBasisError:
            return False
        if (
            snapshot_date < receipt.requested_scope_start
            or snapshot_date > receipt.requested_scope_end
        ):
            return False
        return params == {
            "code_list": [snapshot_security],
            "begin_date": snapshot_trading_day,
            "end_date": snapshot_trading_day,
            "begin_time": 93000000,
            "end_time": 150000000,
        }
    if method != "MarketData.query_kline":
        return False
    expected_keys = {
        "code_list",
        "begin_date",
        "end_date",
        "kline_type",
        "period",
        "trading_days",
    }
    if set(params) != expected_keys:
        return False
    if params.get("begin_date") != start or params.get("end_date") != end:
        return False
    if params.get("kline_type") != "DAY" or params.get("period") != 10008:
        return False
    code_list = params.get("code_list")
    if (
        not isinstance(code_list, list)
        or not code_list
        or any(
            not isinstance(value, str) or re.fullmatch(r"\d{6}\.(?:SH|SZ)", value) is None
            for value in code_list
        )
        or code_list != sorted(code_list)
        or len(code_list) != len(set(code_list))
        or len(code_list) != receipt.security_universe_count
        or sha256_hex(canonical_json(code_list)) != receipt.security_universe_hash
    ):
        return False
    trading_days = params.get("trading_days")
    return (
        isinstance(trading_days, list)
        and bool(trading_days)
        and all(
            isinstance(value, int) and not isinstance(value, bool) and len(str(value)) == 8
            for value in trading_days
        )
        and trading_days == sorted(trading_days)
        and len(trading_days) == len(set(trading_days))
        and len(trading_days) == receipt.calendar_trading_day_count
        and sha256_hex(canonical_json(trading_days)) == receipt.calendar_trading_days_hash
    )


def _read_retained_operation_payload(
    root: Path,
    receipt: AmazingDataAcquisitionReceipt,
    operation: AmazingDataExchangeReceipt,
    *,
    exact_session: bool = False,
    exact_snapshot: bool = False,
    snapshot_security: str | None = None,
    snapshot_trading_day: int | None = None,
) -> tuple[Any, Mapping[str, Any]]:
    """Read one already-closed operation for semantic replay."""
    evidence_path = root.joinpath(*operation.captured_evidence_uri.split("/"))
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageBasisError("AmazingData retained operation meta is unreadable") from exc
    if not isinstance(evidence, Mapping):
        raise CoverageBasisError("AmazingData retained operation meta is malformed")
    if not _retained_request_matches_receipt(
        receipt,
        operation.method,
        evidence.get("request_params"),
        exact_session=exact_session,
        exact_snapshot=exact_snapshot,
        snapshot_security=snapshot_security,
        snapshot_trading_day=snapshot_trading_day,
    ):
        raise CoverageBasisError("AmazingData retained operation request changed")
    provider = _text_or_empty(evidence.get("provider"))
    dataset = _text_or_empty(evidence.get("provider_dataset"))
    request_id = _text_or_empty(evidence.get("request_id"))
    if not all(value for value in (provider, dataset, request_id)):
        raise CoverageBasisError("AmazingData retained operation identity is malformed")
    from ashare_state.storage.raw_writer import read_raw_payload

    try:
        payload = read_raw_payload(
            root,
            provider=provider,
            dataset=dataset,
            request_id=request_id,
            verify=True,
        )
    except Exception as exc:  # noqa: BLE001 - replay boundary normalizes failure
        raise CoverageBasisError("AmazingData retained operation payload is unreadable") from exc
    return payload, evidence


def _text_or_empty(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _single_value_column(payload: Any) -> list[Any]:
    """Read the scalar ``value`` table emitted for a provider list."""
    if not hasattr(payload, "columns") or "value" not in {
        str(column) for column in payload.columns
    }:
        raise CoverageBasisError("AmazingData retained list payload shape changed")
    try:
        column = payload["value"]
        if hasattr(column, "to_list"):
            values = column.to_list()
        elif hasattr(column, "tolist"):
            values = column.tolist()
        elif hasattr(column, "to_pylist"):
            values = column.to_pylist()
        else:
            values = list(column)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise CoverageBasisError("AmazingData retained list payload is unreadable") from exc
    return list(values)


def _calendar_values_for_receipt(
    payload: Any,
    receipt: AmazingDataAcquisitionReceipt,
) -> list[int]:
    """Reapply the acquisition calendar's in-month projection during replay."""
    values = _single_value_column(payload)
    scoped: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int) or len(str(value)) != 8:
            raise CoverageBasisError("AmazingData retained calendar value is malformed")
        parsed = _day_to_date(value)
        if receipt.requested_scope_start <= parsed <= receipt.requested_scope_end:
            scoped.append(value)
    if len(scoped) != len(set(scoped)) or not scoped:
        raise CoverageBasisError("AmazingData retained calendar scope is malformed")
    return sorted(scoped)


def _issue_amazingdata_acquisition_receipt(
    *,
    source_snapshot: VerifiedSourceSnapshot,
    capture: _VerifiedAmazingDataCapture,
) -> AmazingDataAcquisitionReceipt:
    """Issue a receipt from facts validated by the AmazingData provider path.

    This is intentionally private and accepts no statement bytes, caller
    timestamps, counts, or caller-selected authority labels.  The provider
    adapter is the only in-repository issuer.
    """
    if not isinstance(source_snapshot, VerifiedSourceSnapshot):
        raise CoverageBasisError("receipt issuer needs a verified source snapshot")
    if not isinstance(capture, _VerifiedAmazingDataCapture):
        raise CoverageBasisError("receipt issuer needs a verified provider capture")
    selection = AuthoritativeSourceSelection.reviewed_amazingdata_history()
    ordered_operations = tuple(
        next((operation for operation in capture.operations if operation.method == method), None)
        for method in AUTHORITATIVE_SOURCE_METHODS
    )
    if any(operation is None for operation in ordered_operations):
        raise CoverageBasisError("receipt issuer did not receive the reviewed exchange set")
    normalized_operations = tuple(
        operation for operation in ordered_operations if operation is not None
    )
    capture_catalog = _amazingdata_capture_catalog(
        source_selection_fingerprint=selection.selection_fingerprint,
        source_snapshot_id=source_snapshot.source_snapshot_id,
        source_snapshot_manifest_hash=source_snapshot.source_snapshot_manifest_hash,
        source_snapshot_semantic_hash=source_snapshot.source_snapshot_semantic_hash,
        source_snapshot_as_of=source_snapshot.source_snapshot_as_of,
        requested_scope_start=capture.requested_scope_start,
        requested_scope_end=capture.requested_scope_end,
        operations=normalized_operations,
        semantic_operations=capture.semantic_operations,
        positive_trade_operations=capture.positive_trade_operations,
        completeness_evaluation=capture.completeness_evaluation,
    )
    capture_hash = sha256_hex(canonical_json(capture_catalog))
    receipt_id = f"amazingdata-history-receipt-{capture_hash[:32]}"
    base: dict[str, Any] = {
        "receipt_id": receipt_id,
        "receipt_version": AMAZINGDATA_ACQUISITION_RECEIPT_VERSION,
        "source_selection": selection,
        "source_snapshot_id": source_snapshot.source_snapshot_id,
        "source_snapshot_manifest_hash": source_snapshot.source_snapshot_manifest_hash,
        "source_snapshot_semantic_hash": source_snapshot.source_snapshot_semantic_hash,
        "source_snapshot_as_of": source_snapshot.source_snapshot_as_of,
        "requested_scope_start": capture.requested_scope_start,
        "requested_scope_end": capture.requested_scope_end,
        "security_universe_selection": AMAZINGDATA_SECURITY_UNIVERSE_SELECTION,
        "security_universe_id": (
            f"hist-code-list:{AMAZINGDATA_SECURITY_UNIVERSE_SELECTION}:{capture.security_universe_hash}"
        ),
        "security_universe_count": capture.security_universe_count,
        "security_universe_hash": capture.security_universe_hash,
        "calendar_market": AMAZINGDATA_CALENDAR_MARKET,
        "calendar_scope_start": capture.requested_scope_start,
        "calendar_scope_end": capture.requested_scope_end,
        "calendar_trading_day_count": capture.calendar_trading_day_count,
        "calendar_trading_days_hash": capture.calendar_trading_days_hash,
        "returned_security_count": capture.security_universe_count,
        "returned_security_set_hash": capture.security_universe_hash,
        "returned_first_date": capture.returned_first_date,
        "returned_last_date": capture.returned_last_date,
        "returned_trading_day_count": capture.returned_trading_day_count,
        "returned_trading_days_hash": capture.returned_trading_days_hash,
        "returned_row_count": capture.returned_row_count,
        "operations": normalized_operations,
        "semantic_operations": capture.semantic_operations,
        "positive_trade_fallback_version": AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION,
        "positive_trade_operations": capture.positive_trade_operations,
        "completeness_evaluation": capture.completeness_evaluation,
        "retrieved_at_utc": ensure_utc_timestamp(capture.retrieved_at_utc),
        "available_at": ensure_utc_timestamp(capture.retrieved_at_utc),
        "pit_as_of": source_snapshot.source_snapshot_as_of,
        "source_capture_uri": f"source_capture/amazingdata/{receipt_id}.json",
        "source_capture_hash": capture_hash,
        "completeness_statement_id": f"amazingdata-complete-{capture_hash[:32]}",
    }
    serialized_base = base | {
        "source_selection": selection.as_dict(),
        "operations": [operation.as_dict() for operation in normalized_operations],
        "semantic_operations": [operation.as_dict() for operation in capture.semantic_operations],
        "positive_trade_fallback_version": AMAZINGDATA_POSITIVE_TRADE_FALLBACK_VERSION,
        "positive_trade_operations": [
            operation.as_dict() for operation in capture.positive_trade_operations
        ],
        "completeness_evaluation": capture.completeness_evaluation.as_dict(),
    }
    base["receipt_hash"] = sha256_hex(canonical_json(serialized_base))
    return AmazingDataAcquisitionReceipt._construct(
        base | {"source_selection": selection}, provenance="verified_capture"
    )


@dataclass(frozen=True)
class AuthoritativeCoverageEvidence:
    """Sealed, non-fixture proof package for one complete logical month.

    The provider payload is never embedded here.  The sidecar embeds a typed
    AmazingData acquisition receipt whose operation hashes point to retained
    RawWriter evidence and a canonical capture catalog.  Its own canonical
    bytes/hash and PIT timestamps are persisted by the historical materializer.
    The explicit receipt kind and complete claim are required; any response
    observation outside the reviewed full-scope path is deliberately not
    sufficient.
    """

    evidence_id: str
    evidence_version: str
    coverage_basis_id: str
    source_snapshot_id: str
    source_snapshot_manifest_hash: str
    source_snapshot_as_of: datetime
    source_domain: str
    claimed_scope_start: date
    claimed_scope_end: date
    source_selection_fingerprint: str
    completeness_method: str
    completeness_claim: str
    source_selection: AuthoritativeSourceSelection
    acquisition_receipt: AmazingDataAcquisitionReceipt
    upstream_source: str
    upstream_statement_kind: str
    upstream_statement_id: str
    upstream_statement_locator: str
    upstream_statement_hash: str
    upstream_inventory_id: str
    upstream_inventory_scope_start: date
    upstream_inventory_scope_end: date
    upstream_inventory_hash: str
    upstream_security_count: int
    upstream_session_count: int
    retrieved_at_utc: datetime
    available_at: datetime
    pit_as_of: datetime
    coverage_basis_evidence_uri: str
    coverage_basis_evidence_hash: str
    artifact_bytes: bytes

    def __post_init__(self) -> None:
        try:
            for field_name in (
                "evidence_id",
                "evidence_version",
                "coverage_basis_id",
                "source_snapshot_id",
                "source_domain",
                "source_selection_fingerprint",
                "completeness_method",
                "completeness_claim",
                "upstream_source",
                "upstream_statement_kind",
                "upstream_statement_id",
                "upstream_statement_locator",
                "upstream_inventory_id",
                "coverage_basis_evidence_uri",
            ):
                _require_non_empty_string(getattr(self, field_name), field_name)
            _require_sha256(self.source_snapshot_manifest_hash, "source_snapshot_manifest_hash")
            _require_sha256(self.source_selection_fingerprint, "source_selection_fingerprint")
            _require_sha256(self.upstream_statement_hash, "upstream_statement_hash")
            _require_sha256(self.upstream_inventory_hash, "upstream_inventory_hash")
            _require_sha256(self.coverage_basis_evidence_hash, "coverage_basis_evidence_hash")
            _safe_relative_uri(self.coverage_basis_evidence_uri, "coverage_basis_evidence_uri")
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        if self.evidence_version != AUTHORITATIVE_COVERAGE_EVIDENCE_VERSION:
            raise CoverageBasisError("unknown authoritative coverage evidence version")
        if self.source_domain != "daily_bar":
            raise CoverageBasisError(
                "authoritative coverage evidence source_domain must be daily_bar"
            )
        if self.completeness_method != AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD:
            raise CoverageBasisError("authoritative coverage evidence uses an unknown method")
        if self.completeness_claim != COMPLETE_OBSERVED_DAILY_BAR_SCOPE:
            raise CoverageBasisError(
                "authoritative coverage evidence must explicitly claim complete daily-bar scope"
            )
        if self.upstream_source != AUTHORITATIVE_PROVIDER:
            raise CoverageBasisError("authoritative coverage evidence names an unreviewed provider")
        if self.upstream_statement_kind != AUTHORITATIVE_UPSTREAM_STATEMENT_KIND:
            raise CoverageBasisError("authoritative inventory/range statement kind is missing")
        if not isinstance(self.source_selection, AuthoritativeSourceSelection):
            raise CoverageBasisError(
                "authoritative coverage evidence needs a typed source selection"
            )
        if not isinstance(self.acquisition_receipt, AmazingDataAcquisitionReceipt):
            raise CoverageBasisError(
                "authoritative coverage evidence needs an AmazingData acquisition receipt"
            )
        if self.source_selection_fingerprint != self.source_selection.selection_fingerprint:
            raise CoverageBasisError(
                "source-selection fingerprint does not match the typed binding"
            )
        receipt = self.acquisition_receipt
        if receipt.source_selection != self.source_selection:
            raise CoverageBasisError("authoritative evidence receipt source-selection changed")
        if (
            receipt.requested_scope_start != self.claimed_scope_start
            or receipt.requested_scope_end != self.claimed_scope_end
        ):
            raise CoverageBasisError("authoritative evidence receipt scope does not match")
        if (
            self.source_snapshot_id != receipt.source_snapshot_id
            or self.source_snapshot_manifest_hash != receipt.source_snapshot_manifest_hash
            or self.source_snapshot_as_of != receipt.source_snapshot_as_of
            or self.source_selection_fingerprint != receipt.source_selection.selection_fingerprint
            or self.upstream_statement_id != receipt.completeness_statement_id
            or self.upstream_statement_locator != receipt.source_capture_uri
            or self.upstream_statement_hash != receipt.receipt_hash
            or self.upstream_inventory_id != receipt.security_universe_id
            or self.upstream_inventory_scope_start != receipt.requested_scope_start
            or self.upstream_inventory_scope_end != receipt.requested_scope_end
            or self.upstream_inventory_hash != receipt.security_universe_hash
            or self.upstream_security_count != receipt.security_universe_count
            or self.upstream_session_count != receipt.calendar_trading_day_count
            or self.retrieved_at_utc != receipt.retrieved_at_utc
            or self.available_at != receipt.available_at
            or self.pit_as_of != receipt.pit_as_of
        ):
            raise CoverageBasisError(
                "authoritative evidence is not derived from its acquisition receipt"
            )
        if any(
            token in self.upstream_statement_locator.lower()
            for token in ("password", "token", "cookie", "secret", "authorization")
        ):
            raise CoverageBasisError("upstream statement locator contains a sensitive token")
        for field_name in (
            "claimed_scope_start",
            "claimed_scope_end",
            "upstream_inventory_scope_start",
            "upstream_inventory_scope_end",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, date) or isinstance(value, datetime):
                raise CoverageBasisError(f"{field_name} must be a date")
        if (self.claimed_scope_start, self.claimed_scope_end) != (
            self.upstream_inventory_scope_start,
            self.upstream_inventory_scope_end,
        ):
            raise CoverageBasisError("upstream inventory scope does not match claimed scope")
        for field_name in (
            "source_snapshot_as_of",
            "retrieved_at_utc",
            "available_at",
            "pit_as_of",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise CoverageBasisError(f"{field_name} must be timezone-aware")
            try:
                object.__setattr__(self, field_name, ensure_utc_timestamp(value))
            except ResearchPanelError as exc:
                raise CoverageBasisError(f"{field_name} is not a valid UTC timestamp") from exc
        if self.available_at > self.pit_as_of:
            raise CoverageBasisError("authoritative evidence is not available at its PIT as_of")
        if self.pit_as_of > self.source_snapshot_as_of:
            raise CoverageBasisError(
                "authoritative evidence PIT as_of is after the source snapshot"
            )
        if self.retrieved_at_utc < self.available_at:
            raise CoverageBasisError("authoritative evidence was retrieved before it was available")
        for field_name in ("upstream_security_count", "upstream_session_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise CoverageBasisError(f"{field_name} must be a positive integer")
        if not isinstance(self.artifact_bytes, bytes):
            raise CoverageBasisError("authoritative coverage evidence artifact_bytes must be bytes")
        expected_bytes = canonical_json(self.as_dict(include_artifact_hash=False)).encode("utf-8")
        if self.artifact_bytes != expected_bytes:
            raise CoverageBasisError("authoritative coverage evidence bytes are not canonical")
        if sha256_hex(self.artifact_bytes) != self.coverage_basis_evidence_hash:
            raise CoverageBasisError("authoritative coverage evidence hash does not match bytes")

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        artifact_bytes: bytes,
        artifact_hash: str,
    ) -> AuthoritativeCoverageEvidence:
        if not isinstance(payload, Mapping) or set(payload) != set(_AUTHORITATIVE_EVIDENCE_FIELDS):
            raise CoverageBasisError("authoritative coverage evidence fields are not exact")
        if not isinstance(artifact_bytes, bytes):
            raise CoverageBasisError("authoritative coverage evidence artifact_bytes must be bytes")
        try:
            parsed = {
                field_name: _require_non_empty_string(payload[field_name], field_name)
                for field_name in (
                    "evidence_id",
                    "evidence_version",
                    "coverage_basis_id",
                    "source_snapshot_id",
                    "source_domain",
                    "source_selection_fingerprint",
                    "completeness_method",
                    "completeness_claim",
                    "upstream_source",
                    "upstream_statement_kind",
                    "upstream_statement_id",
                    "upstream_statement_locator",
                    "upstream_inventory_id",
                    "coverage_basis_evidence_uri",
                )
            }
            dates = {
                field_name: parse_date_value(payload[field_name])
                for field_name in (
                    "claimed_scope_start",
                    "claimed_scope_end",
                    "upstream_inventory_scope_start",
                    "upstream_inventory_scope_end",
                )
            }
            timestamps = {
                field_name: ensure_utc_timestamp(payload[field_name])
                for field_name in (
                    "source_snapshot_as_of",
                    "retrieved_at_utc",
                    "available_at",
                    "pit_as_of",
                )
            }
            selection = AuthoritativeSourceSelection.from_mapping(payload["source_selection"])
            acquisition_receipt = AmazingDataAcquisitionReceipt.from_mapping(
                payload["acquisition_receipt"]
            )
            snapshot_hash = _require_sha256(
                payload["source_snapshot_manifest_hash"], "source_snapshot_manifest_hash"
            )
            _require_sha256(parsed["source_selection_fingerprint"], "source_selection_fingerprint")
            statement_hash = _require_sha256(
                payload["upstream_statement_hash"], "upstream_statement_hash"
            )
            inventory_hash = _require_sha256(
                payload["upstream_inventory_hash"], "upstream_inventory_hash"
            )
            evidence_hash = _require_sha256(artifact_hash, "coverage_basis_evidence_hash")
        except (HistoricalMaterializationError, ResearchPanelError, KeyError, TypeError) as exc:
            raise CoverageBasisError("authoritative coverage evidence is malformed") from exc
        return cls(
            evidence_id=parsed["evidence_id"],
            evidence_version=parsed["evidence_version"],
            coverage_basis_id=parsed["coverage_basis_id"],
            source_snapshot_id=parsed["source_snapshot_id"],
            source_snapshot_manifest_hash=snapshot_hash,
            source_snapshot_as_of=timestamps["source_snapshot_as_of"],
            source_domain=parsed["source_domain"],
            claimed_scope_start=dates["claimed_scope_start"],
            claimed_scope_end=dates["claimed_scope_end"],
            source_selection_fingerprint=parsed["source_selection_fingerprint"],
            completeness_method=parsed["completeness_method"],
            completeness_claim=parsed["completeness_claim"],
            source_selection=selection,
            acquisition_receipt=acquisition_receipt,
            upstream_source=parsed["upstream_source"],
            upstream_statement_kind=parsed["upstream_statement_kind"],
            upstream_statement_id=parsed["upstream_statement_id"],
            upstream_statement_locator=parsed["upstream_statement_locator"],
            upstream_statement_hash=statement_hash,
            upstream_inventory_id=parsed["upstream_inventory_id"],
            upstream_inventory_scope_start=dates["upstream_inventory_scope_start"],
            upstream_inventory_scope_end=dates["upstream_inventory_scope_end"],
            upstream_inventory_hash=inventory_hash,
            upstream_security_count=payload["upstream_security_count"],
            upstream_session_count=payload["upstream_session_count"],
            retrieved_at_utc=timestamps["retrieved_at_utc"],
            available_at=timestamps["available_at"],
            pit_as_of=timestamps["pit_as_of"],
            coverage_basis_evidence_uri=parsed["coverage_basis_evidence_uri"],
            coverage_basis_evidence_hash=evidence_hash,
            artifact_bytes=artifact_bytes,
        )

    def as_dict(self, *, include_artifact_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "evidence_id": self.evidence_id,
            "evidence_version": self.evidence_version,
            "coverage_basis_id": self.coverage_basis_id,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_manifest_hash": self.source_snapshot_manifest_hash,
            "source_snapshot_as_of": self.source_snapshot_as_of,
            "source_domain": self.source_domain,
            "claimed_scope_start": self.claimed_scope_start,
            "claimed_scope_end": self.claimed_scope_end,
            "source_selection_fingerprint": self.source_selection_fingerprint,
            "completeness_method": self.completeness_method,
            "completeness_claim": self.completeness_claim,
            "source_selection": self.source_selection.as_dict(),
            "acquisition_receipt": self.acquisition_receipt.as_dict(),
            "upstream_source": self.upstream_source,
            "upstream_statement_kind": self.upstream_statement_kind,
            "upstream_statement_id": self.upstream_statement_id,
            "upstream_statement_locator": self.upstream_statement_locator,
            "upstream_statement_hash": self.upstream_statement_hash,
            "upstream_inventory_id": self.upstream_inventory_id,
            "upstream_inventory_scope_start": self.upstream_inventory_scope_start,
            "upstream_inventory_scope_end": self.upstream_inventory_scope_end,
            "upstream_inventory_hash": self.upstream_inventory_hash,
            "upstream_security_count": self.upstream_security_count,
            "upstream_session_count": self.upstream_session_count,
            "retrieved_at_utc": self.retrieved_at_utc,
            "available_at": self.available_at,
            "pit_as_of": self.pit_as_of,
            "coverage_basis_evidence_uri": self.coverage_basis_evidence_uri,
        }
        if include_artifact_hash:
            payload["coverage_basis_evidence_hash"] = self.coverage_basis_evidence_hash
        return payload


def build_authoritative_coverage_evidence_from_acquisition(
    partition: PartitionKey,
    acquisition_receipt: AmazingDataAcquisitionReceipt,
) -> AuthoritativeCoverageEvidence:
    """Build one authoritative sidecar from a verified AmazingData receipt.

    The receipt is the only authority input.  Evidence ids, scope, inventory
    hashes, counts and all time fields are derived from it; arbitrary source
    bytes, caller timestamps and caller completeness labels are not accepted.
    """
    if not isinstance(acquisition_receipt, AmazingDataAcquisitionReceipt):
        raise CoverageBasisError("authoritative evidence needs a typed acquisition receipt")
    if not acquisition_receipt.is_verified_capture:
        raise CoverageBasisError(
            "authoritative evidence must be issued by the AmazingData acquisition path"
        )
    if (
        acquisition_receipt.requested_scope_start != partition.scope_start
        or acquisition_receipt.requested_scope_end != partition.scope_end
    ):
        raise CoverageBasisError("acquisition receipt scope does not match the partition")
    evidence_id = f"amazingdata-evidence-{partition.logical_key}-{acquisition_receipt.receipt_id}"
    coverage_basis_id = (
        f"amazingdata-basis-{partition.logical_key}-{acquisition_receipt.receipt_id}"
    )
    coverage_basis_evidence_uri = (
        f"coverage_basis_evidence/{partition.research_split.value}/"
        f"{partition.calendar_year:04d}-{partition.calendar_month:02d}.json"
    )
    base: dict[str, Any] = {
        "evidence_id": evidence_id,
        "evidence_version": AUTHORITATIVE_COVERAGE_EVIDENCE_VERSION,
        "coverage_basis_id": coverage_basis_id,
        "source_snapshot_id": acquisition_receipt.source_snapshot_id,
        "source_snapshot_manifest_hash": acquisition_receipt.source_snapshot_manifest_hash,
        "source_snapshot_as_of": acquisition_receipt.source_snapshot_as_of,
        "source_domain": "daily_bar",
        "claimed_scope_start": partition.scope_start,
        "claimed_scope_end": partition.scope_end,
        "source_selection_fingerprint": acquisition_receipt.source_selection.selection_fingerprint,
        "completeness_method": AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD,
        "completeness_claim": COMPLETE_OBSERVED_DAILY_BAR_SCOPE,
        "source_selection": acquisition_receipt.source_selection.as_dict(),
        "acquisition_receipt": acquisition_receipt.as_dict(),
        "upstream_source": AUTHORITATIVE_PROVIDER,
        "upstream_statement_kind": AUTHORITATIVE_UPSTREAM_STATEMENT_KIND,
        "upstream_statement_id": acquisition_receipt.completeness_statement_id,
        "upstream_statement_locator": acquisition_receipt.source_capture_uri,
        "upstream_statement_hash": acquisition_receipt.receipt_hash,
        "upstream_inventory_id": acquisition_receipt.security_universe_id,
        "upstream_inventory_scope_start": acquisition_receipt.requested_scope_start,
        "upstream_inventory_scope_end": acquisition_receipt.requested_scope_end,
        "upstream_inventory_hash": acquisition_receipt.security_universe_hash,
        "upstream_security_count": acquisition_receipt.security_universe_count,
        "upstream_session_count": acquisition_receipt.calendar_trading_day_count,
        "retrieved_at_utc": acquisition_receipt.retrieved_at_utc,
        "available_at": acquisition_receipt.available_at,
        "pit_as_of": acquisition_receipt.pit_as_of,
        "coverage_basis_evidence_uri": coverage_basis_evidence_uri,
    }
    artifact_bytes = canonical_json(base).encode("utf-8")
    return AuthoritativeCoverageEvidence(
        evidence_id=evidence_id,
        evidence_version=AUTHORITATIVE_COVERAGE_EVIDENCE_VERSION,
        coverage_basis_id=coverage_basis_id,
        source_snapshot_id=acquisition_receipt.source_snapshot_id,
        source_snapshot_manifest_hash=acquisition_receipt.source_snapshot_manifest_hash,
        source_snapshot_as_of=acquisition_receipt.source_snapshot_as_of,
        source_domain="daily_bar",
        claimed_scope_start=partition.scope_start,
        claimed_scope_end=partition.scope_end,
        source_selection_fingerprint=acquisition_receipt.source_selection.selection_fingerprint,
        completeness_method=AUTHORITATIVE_UPSTREAM_INVENTORY_RANGE_METHOD,
        completeness_claim=COMPLETE_OBSERVED_DAILY_BAR_SCOPE,
        source_selection=acquisition_receipt.source_selection,
        acquisition_receipt=acquisition_receipt,
        upstream_source=AUTHORITATIVE_PROVIDER,
        upstream_statement_kind=AUTHORITATIVE_UPSTREAM_STATEMENT_KIND,
        upstream_statement_id=acquisition_receipt.completeness_statement_id,
        upstream_statement_locator=acquisition_receipt.source_capture_uri,
        upstream_statement_hash=acquisition_receipt.receipt_hash,
        upstream_inventory_id=acquisition_receipt.security_universe_id,
        upstream_inventory_scope_start=acquisition_receipt.requested_scope_start,
        upstream_inventory_scope_end=acquisition_receipt.requested_scope_end,
        upstream_inventory_hash=acquisition_receipt.security_universe_hash,
        upstream_security_count=acquisition_receipt.security_universe_count,
        upstream_session_count=acquisition_receipt.calendar_trading_day_count,
        retrieved_at_utc=acquisition_receipt.retrieved_at_utc,
        available_at=acquisition_receipt.available_at,
        pit_as_of=acquisition_receipt.pit_as_of,
        coverage_basis_evidence_uri=coverage_basis_evidence_uri,
        coverage_basis_evidence_hash=sha256_hex(artifact_bytes),
        artifact_bytes=artifact_bytes,
    )


@dataclass(frozen=True, order=True)
class PartitionKey:
    """One logical split/year/month partition in the CR-7 window."""

    research_split: ResearchSplit
    calendar_year: int
    calendar_month: int

    def __post_init__(self) -> None:
        if isinstance(self.calendar_year, bool) or not isinstance(self.calendar_year, int):
            raise HistoricalMaterializationError("calendar_year must be an integer")
        if self.research_split not in {
            ResearchSplit.DEVELOPMENT,
            ResearchSplit.VALIDATION_A,
            ResearchSplit.HOLDOUT,
        }:
            raise HistoricalMaterializationError(
                f"{self.research_split.value} is not a historical research partition"
            )
        if not 1 <= self.calendar_month <= 12:
            raise HistoricalMaterializationError("calendar_month must be between 1 and 12")
        try:
            date(self.calendar_year, self.calendar_month, 1)
        except ValueError as exc:
            raise HistoricalMaterializationError(
                "calendar_year is not a valid calendar year"
            ) from exc

    @property
    def logical_key(self) -> str:
        return f"{self.research_split.value}:{self.calendar_year:04d}-{self.calendar_month:02d}"

    @property
    def scope_start(self) -> date:
        return date(self.calendar_year, self.calendar_month, 1)

    @property
    def scope_end(self) -> date:
        return _month_end(self.calendar_year, self.calendar_month)

    def as_dict(self) -> dict[str, Any]:
        return {
            "research_split": self.research_split.value,
            "calendar_year": self.calendar_year,
            "calendar_month": self.calendar_month,
            "logical_key": self.logical_key,
        }


def expected_partition_keys() -> tuple[PartitionKey, ...]:
    """Return all 78 logical calendar-month keys in split order."""
    keys: list[PartitionKey] = []
    for research_split, (start, end) in split_windows().items():
        cursor = start.replace(day=1)
        while cursor <= end:
            keys.append(PartitionKey(research_split, cursor.year, cursor.month))
            cursor = _next_month(cursor)
    return tuple(keys)


@dataclass(frozen=True)
class CoverageBasisDescriptor:
    """A sealed, typed completeness descriptor for one enabled month.

    ``artifact_bytes`` must be the exact canonical UTF-8 JSON bytes for the
    descriptor with ``coverage_basis_artifact_hash`` omitted.  Keeping those
    bytes on the typed object lets the verifier check the evidence itself,
    rather than trusting a caller-provided hash or a label.
    """

    coverage_basis_id: str
    coverage_basis_version: str
    research_split: ResearchSplit
    calendar_year: int
    calendar_month: int
    source_snapshot_id: str
    source_snapshot_manifest_hash: str
    source_domain: str
    claimed_scope_start: date
    claimed_scope_end: date
    source_selection_fingerprint: str
    completeness_method: str
    completeness_claim: str
    coverage_basis_artifact_uri: str
    coverage_basis_artifact_hash: str
    artifact_bytes: bytes
    authoritative_evidence: AuthoritativeCoverageEvidence | None = dataclass_field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        """Keep direct dataclass construction subject to the same seal checks."""
        for field in (
            "coverage_basis_id",
            "coverage_basis_version",
            "source_snapshot_id",
            "source_domain",
            "source_selection_fingerprint",
            "completeness_method",
            "completeness_claim",
            "coverage_basis_artifact_uri",
        ):
            try:
                _require_non_empty_string(getattr(self, field), field)
            except HistoricalMaterializationError as exc:
                raise CoverageBasisError(str(exc)) from exc
        if self.coverage_basis_version != COVERAGE_BASIS_VERSION:
            raise CoverageBasisError("unknown coverage_basis_version")
        if not isinstance(self.research_split, ResearchSplit):
            raise CoverageBasisError("research_split must be a typed ResearchSplit")
        try:
            partition = PartitionKey(self.research_split, self.calendar_year, self.calendar_month)
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        if self.source_domain != "daily_bar":
            raise CoverageBasisError("coverage basis source_domain must be daily_bar")
        if not isinstance(self.claimed_scope_start, date) or isinstance(
            self.claimed_scope_start, datetime
        ):
            raise CoverageBasisError("claimed_scope_start must be a date")
        if not isinstance(self.claimed_scope_end, date) or isinstance(
            self.claimed_scope_end, datetime
        ):
            raise CoverageBasisError("claimed_scope_end must be a date")
        if (self.claimed_scope_start, self.claimed_scope_end) != (
            partition.scope_start,
            partition.scope_end,
        ):
            raise CoverageBasisError("coverage basis scope is not the logical calendar month")
        if self.completeness_method not in _RECOGNIZED_COMPLETENESS_METHODS:
            raise CoverageBasisError("unknown versioned completeness_method")
        method_spec = _RECOGNIZED_COMPLETENESS_METHODS[self.completeness_method]
        if method_spec.evidence_class is CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM:
            evidence = self.authoritative_evidence
            if not isinstance(evidence, AuthoritativeCoverageEvidence):
                raise CoverageBasisError(
                    "authoritative completeness method requires a typed evidence sidecar"
                )
            if (
                evidence.coverage_basis_id != self.coverage_basis_id
                or evidence.source_snapshot_id != self.source_snapshot_id
                or evidence.source_snapshot_manifest_hash != self.source_snapshot_manifest_hash
                or evidence.source_domain != self.source_domain
                or evidence.claimed_scope_start != self.claimed_scope_start
                or evidence.claimed_scope_end != self.claimed_scope_end
                or evidence.source_selection_fingerprint != self.source_selection_fingerprint
                or evidence.completeness_method != self.completeness_method
                or evidence.completeness_claim != self.completeness_claim
            ):
                raise CoverageBasisError("authoritative coverage evidence binding changed")
        elif self.authoritative_evidence is not None:
            raise CoverageBasisError(
                "fixture or unresolved completeness cannot carry authoritative evidence"
            )
        expected_claim = (
            COMPLETE_OBSERVED_DAILY_BAR_SCOPE
            if self.state is CoverageState.OBSERVED_DAILY_BAR_COVERAGE
            else PARTIAL_OBSERVED_DAILY_BAR_SCOPE
        )
        if self.completeness_claim != expected_claim:
            raise CoverageBasisError("completeness_method and completeness_claim disagree")
        try:
            _require_sha256(self.source_snapshot_manifest_hash, "source_snapshot_manifest_hash")
            _require_sha256(self.coverage_basis_artifact_hash, "coverage_basis_artifact_hash")
            _safe_relative_uri(self.coverage_basis_artifact_uri, "coverage_basis_artifact_uri")
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        if not isinstance(self.artifact_bytes, bytes):
            raise CoverageBasisError("coverage basis artifact_bytes must be bytes")
        expected_bytes = canonical_json(self.as_dict(include_artifact_hash=False)).encode("utf-8")
        if self.artifact_bytes != expected_bytes:
            raise CoverageBasisError("coverage basis artifact bytes are not exactly canonical")
        if sha256_hex(self.artifact_bytes) != self.coverage_basis_artifact_hash:
            raise CoverageBasisError("coverage basis artifact hash does not match exact bytes")

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        artifact_bytes: bytes,
        authoritative_evidence: AuthoritativeCoverageEvidence | None = None,
    ) -> CoverageBasisDescriptor:
        if not isinstance(payload, Mapping):
            raise CoverageBasisError("coverage basis must be an object")
        if set(payload) != set(_BASIS_FIELDS):
            missing = sorted(set(_BASIS_FIELDS).difference(payload))
            extra = sorted(set(payload).difference(_BASIS_FIELDS))
            raise CoverageBasisError(
                f"coverage basis fields are not exact; missing={missing}, extra={extra}"
            )
        if not isinstance(artifact_bytes, bytes):
            raise CoverageBasisError("coverage basis artifact_bytes must be bytes")

        string_fields = (
            "coverage_basis_id",
            "coverage_basis_version",
            "research_split",
            "source_snapshot_id",
            "source_snapshot_manifest_hash",
            "source_domain",
            "source_selection_fingerprint",
            "completeness_method",
            "completeness_claim",
            "coverage_basis_artifact_uri",
        )
        try:
            values = {
                field: _require_non_empty_string(payload[field], field) for field in string_fields
            }
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        if values["coverage_basis_version"] != COVERAGE_BASIS_VERSION:
            raise CoverageBasisError("unknown coverage_basis_version")
        try:
            research_split = ResearchSplit(values["research_split"])
        except ValueError as exc:
            raise CoverageBasisError("coverage basis names an unknown research split") from exc
        if research_split not in {
            ResearchSplit.DEVELOPMENT,
            ResearchSplit.VALIDATION_A,
            ResearchSplit.HOLDOUT,
        }:
            raise CoverageBasisError("coverage basis cannot target warmup/outside_window")
        year = payload["calendar_year"]
        month = payload["calendar_month"]
        if isinstance(year, bool) or not isinstance(year, int):
            raise CoverageBasisError("calendar_year must be an integer")
        if isinstance(month, bool) or not isinstance(month, int):
            raise CoverageBasisError("calendar_month must be an integer")
        try:
            partition = PartitionKey(research_split, year, month)
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        try:
            scope_start = parse_date_value(payload["claimed_scope_start"])
            scope_end = parse_date_value(payload["claimed_scope_end"])
        except ResearchPanelError as exc:
            raise CoverageBasisError("coverage basis has invalid claimed scope") from exc
        if (scope_start, scope_end) != (partition.scope_start, partition.scope_end):
            raise CoverageBasisError(
                "coverage basis scope must equal the complete logical calendar month"
            )
        if values["source_domain"] != "daily_bar":
            raise CoverageBasisError("coverage basis source_domain must be daily_bar")
        try:
            completeness_state = _RECOGNIZED_COMPLETENESS_METHODS[
                values["completeness_method"]
            ].state
        except KeyError as exc:
            raise CoverageBasisError(
                f"unknown versioned completeness_method {values['completeness_method']!r}"
            ) from exc
        expected_claim = (
            COMPLETE_OBSERVED_DAILY_BAR_SCOPE
            if completeness_state is CoverageState.OBSERVED_DAILY_BAR_COVERAGE
            else PARTIAL_OBSERVED_DAILY_BAR_SCOPE
        )
        if values["completeness_claim"] != expected_claim:
            raise CoverageBasisError("completeness_method and completeness_claim disagree")
        try:
            source_manifest_hash = _require_sha256(
                values["source_snapshot_manifest_hash"], "source_snapshot_manifest_hash"
            )
            artifact_hash = _require_sha256(
                payload["coverage_basis_artifact_hash"], "coverage_basis_artifact_hash"
            )
        except HistoricalMaterializationError as exc:
            raise CoverageBasisError(str(exc)) from exc
        uri = _safe_relative_uri(
            values["coverage_basis_artifact_uri"], "coverage_basis_artifact_uri"
        )
        normalized: dict[str, Any] = {
            "coverage_basis_id": values["coverage_basis_id"],
            "coverage_basis_version": values["coverage_basis_version"],
            "research_split": research_split,
            "calendar_year": year,
            "calendar_month": month,
            "source_snapshot_id": values["source_snapshot_id"],
            "source_snapshot_manifest_hash": source_manifest_hash,
            "source_domain": values["source_domain"],
            "claimed_scope_start": scope_start,
            "claimed_scope_end": scope_end,
            "source_selection_fingerprint": values["source_selection_fingerprint"],
            "completeness_method": values["completeness_method"],
            "completeness_claim": values["completeness_claim"],
            "coverage_basis_artifact_uri": uri,
        }
        expected_bytes = canonical_json(normalized).encode("utf-8")
        if artifact_bytes != expected_bytes:
            raise CoverageBasisError(
                "coverage basis artifact bytes are not the exact canonical descriptor bytes"
            )
        if sha256_hex(artifact_bytes) != artifact_hash:
            raise CoverageBasisError("coverage basis artifact hash does not match exact bytes")
        return cls(
            **normalized,
            coverage_basis_artifact_hash=artifact_hash,
            artifact_bytes=artifact_bytes,
            authoritative_evidence=authoritative_evidence,
        )

    @property
    def partition_key(self) -> PartitionKey:
        return PartitionKey(self.research_split, self.calendar_year, self.calendar_month)

    @property
    def state(self) -> CoverageState:
        return _RECOGNIZED_COMPLETENESS_METHODS[self.completeness_method].state

    @property
    def evidence_class(self) -> CoverageEvidenceClass:
        return _RECOGNIZED_COMPLETENESS_METHODS[self.completeness_method].evidence_class

    @property
    def sort_key(self) -> tuple[str, int, int, str]:
        return (
            self.research_split.value,
            self.calendar_year,
            self.calendar_month,
            "research_enabled",
        )

    def as_dict(self, *, include_artifact_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "coverage_basis_id": self.coverage_basis_id,
            "coverage_basis_version": self.coverage_basis_version,
            "research_split": self.research_split.value,
            "calendar_year": self.calendar_year,
            "calendar_month": self.calendar_month,
            "source_snapshot_id": self.source_snapshot_id,
            "source_snapshot_manifest_hash": self.source_snapshot_manifest_hash,
            "source_domain": self.source_domain,
            "claimed_scope_start": self.claimed_scope_start.isoformat(),
            "claimed_scope_end": self.claimed_scope_end.isoformat(),
            "source_selection_fingerprint": self.source_selection_fingerprint,
            "completeness_method": self.completeness_method,
            "completeness_claim": self.completeness_claim,
            "coverage_basis_artifact_uri": self.coverage_basis_artifact_uri,
        }
        if include_artifact_hash:
            payload["coverage_basis_artifact_hash"] = self.coverage_basis_artifact_hash
        return payload


def build_fixture_coverage_basis_descriptor(
    partition: PartitionKey,
    *,
    source_snapshot_id: str,
    source_snapshot_manifest_hash: str,
    source_selection_fingerprint: str,
    coverage_basis_id: str | None = None,
    partial: bool = False,
) -> CoverageBasisDescriptor:
    """Build a deterministic fixture-only basis descriptor.

    This helper hard-codes the recognized offline method.  It cannot be used
    to assert that a real Provider or upstream archive is complete.
    """
    method = OFFLINE_FIXTURE_PARTIAL_METHOD if partial else OFFLINE_FIXTURE_COMPLETE_METHOD
    claim = PARTIAL_OBSERVED_DAILY_BAR_SCOPE if partial else COMPLETE_OBSERVED_DAILY_BAR_SCOPE
    base: dict[str, Any] = {
        "coverage_basis_id": coverage_basis_id or f"fixture-basis-{partition.logical_key}",
        "coverage_basis_version": COVERAGE_BASIS_VERSION,
        "research_split": partition.research_split.value,
        "calendar_year": partition.calendar_year,
        "calendar_month": partition.calendar_month,
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_manifest_hash": source_snapshot_manifest_hash,
        "source_domain": "daily_bar",
        "claimed_scope_start": partition.scope_start,
        "claimed_scope_end": partition.scope_end,
        "source_selection_fingerprint": source_selection_fingerprint,
        "completeness_method": method,
        "completeness_claim": claim,
        "coverage_basis_artifact_uri": (
            f"coverage_basis/{partition.research_split.value}/"
            f"{partition.calendar_year:04d}-{partition.calendar_month:02d}.json"
        ),
    }
    artifact_bytes = canonical_json(base).encode("utf-8")
    payload = base | {"coverage_basis_artifact_hash": sha256_hex(artifact_bytes)}
    return CoverageBasisDescriptor.from_mapping(payload, artifact_bytes=artifact_bytes)


@dataclass(frozen=True)
class CoverageEvaluation:
    partition: PartitionKey
    state: CoverageState
    evidence_class: CoverageEvidenceClass
    descriptor: CoverageBasisDescriptor | None
    reason: str


def verify_coverage_basis(
    projection: VerifiedResearchProjection,
    descriptors: Sequence[CoverageBasisDescriptor],
) -> tuple[CoverageEvaluation, ...]:
    """Verify basis descriptors and derive coverage without caller promotion."""
    seen_descriptors: set[PartitionKey] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, CoverageBasisDescriptor):
            raise CoverageBasisError("coverage basis input must use typed descriptors")
        key = descriptor.partition_key
        if key in seen_descriptors:
            raise CoverageBasisError(f"duplicate coverage basis for {key.logical_key}")
        seen_descriptors.add(key)
        if descriptor.source_snapshot_id != projection.source_snapshot_id:
            raise CoverageBasisError("coverage basis source_snapshot_id does not match projection")
        if descriptor.source_snapshot_manifest_hash != projection.source_snapshot_manifest_hash:
            raise CoverageBasisError(
                "coverage basis source_snapshot_manifest_hash does not match projection"
            )
        if descriptor.authoritative_evidence is not None and (
            descriptor.authoritative_evidence.source_snapshot_as_of
            != ensure_utc_timestamp(projection.source_snapshot_as_of)
        ):
            raise CoverageBasisError(
                "authoritative coverage evidence source snapshot PIT does not match projection"
            )

    enabled_keys: set[PartitionKey] = set()
    for ordinal, row in enumerate(projection.rows):
        if not isinstance(row, Mapping):
            raise CoverageBasisError(f"projection row {ordinal} is not an object")
        if row.get("research_eligibility") != ResearchEligibility.ENABLED.value:
            continue
        trade_date = row.get("trade_date")
        if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
            raise CoverageBasisError(f"projection row {ordinal} has invalid trade_date")
        split = assign_research_split(trade_date)
        if split in {ResearchSplit.WARMUP, ResearchSplit.OUTSIDE_WINDOW}:
            raise CoverageBasisError("an enabled projection row is outside the research window")
        enabled_keys.add(PartitionKey(split, trade_date.year, trade_date.month))

    extra = seen_descriptors.difference(enabled_keys)
    if extra:
        raise CoverageBasisError(
            "coverage basis must describe an enabled logical partition; extra keys: "
            + ", ".join(sorted(key.logical_key for key in extra))
        )
    evaluations: list[CoverageEvaluation] = []
    for key in expected_partition_keys():
        matched_descriptor = next(
            (candidate for candidate in descriptors if candidate.partition_key == key), None
        )
        if key not in enabled_keys:
            evaluations.append(
                CoverageEvaluation(
                    partition=key,
                    state=CoverageState.UNRESOLVED_NOT_FOR_RESEARCH,
                    evidence_class=CoverageEvidenceClass.UNRESOLVED,
                    descriptor=None,
                    reason="no_enabled_rows_in_partition",
                )
            )
        elif matched_descriptor is None:
            evaluations.append(
                CoverageEvaluation(
                    partition=key,
                    state=CoverageState.UNRESOLVED_NOT_FOR_RESEARCH,
                    evidence_class=CoverageEvidenceClass.UNRESOLVED,
                    descriptor=None,
                    reason="missing_coverage_basis_descriptor",
                )
            )
        else:
            evaluations.append(
                CoverageEvaluation(
                    partition=key,
                    state=matched_descriptor.state,
                    evidence_class=matched_descriptor.evidence_class,
                    descriptor=matched_descriptor,
                    reason="verified_versioned_coverage_basis",
                )
            )
    return tuple(evaluations)


def _aggregate_coverage_evidence(
    evaluations: Sequence[CoverageEvaluation],
) -> CoverageEvidenceClass:
    """Classify the complete target window, failing closed for any gap."""
    if len(evaluations) != len(expected_partition_keys()):
        return CoverageEvidenceClass.UNRESOLVED
    if any(
        evaluation.state is CoverageState.UNRESOLVED_NOT_FOR_RESEARCH
        or evaluation.evidence_class is CoverageEvidenceClass.UNRESOLVED
        for evaluation in evaluations
    ):
        return CoverageEvidenceClass.UNRESOLVED
    evidence_classes = {evaluation.evidence_class for evaluation in evaluations}
    if len(evidence_classes) != 1:
        return CoverageEvidenceClass.UNRESOLVED
    return next(iter(evidence_classes))


def compute_coverage_basis_set_hash(
    descriptors: Sequence[CoverageBasisDescriptor],
) -> str:
    """Hash sorted basis descriptors and any authoritative sidecar hashes."""
    ordered = sorted(descriptors, key=lambda descriptor: descriptor.sort_key)
    payload: list[dict[str, Any]] = []
    for descriptor in ordered:
        item = {"research_route": "research_enabled", **descriptor.as_dict()}
        if descriptor.authoritative_evidence is not None:
            item["authoritative_evidence_hash"] = (
                descriptor.authoritative_evidence.coverage_basis_evidence_hash
            )
        payload.append(item)
    return sha256_hex(canonical_json(payload))


def compute_dependency_lock_content_hash(lock_bytes: bytes) -> str:
    """Hash exact dependency-lock bytes without reading or naming a path."""
    if not isinstance(lock_bytes, bytes):
        raise HistoricalMaterializationError("dependency lock content must be bytes")
    return sha256_hex(lock_bytes)


@dataclass(frozen=True)
class WriterRuntimeLock:
    """The portable writer identity used in materialization replay identity."""

    dependency_lock_content_hash: str
    python_runtime_identity: str
    parquet_writer_engine_identity: str
    writer_configuration_version: str

    def __post_init__(self) -> None:
        try:
            _require_sha256(self.dependency_lock_content_hash, "dependency_lock_content_hash")
            _require_non_empty_string(self.python_runtime_identity, "python_runtime_identity")
            _require_non_empty_string(
                self.parquet_writer_engine_identity, "parquet_writer_engine_identity"
            )
            _require_non_empty_string(
                self.writer_configuration_version, "writer_configuration_version"
            )
        except HistoricalMaterializationError as exc:
            raise HistoricalMaterializationError(str(exc)) from exc

    def as_dict(self) -> dict[str, str]:
        return {
            "dependency_lock_content_hash": self.dependency_lock_content_hash,
            "python_runtime_identity": self.python_runtime_identity,
            "parquet_writer_engine_identity": self.parquet_writer_engine_identity,
            "writer_configuration_version": self.writer_configuration_version,
        }

    @property
    def content_hash(self) -> str:
        return sha256_hex(canonical_json(self.as_dict()))


def build_writer_runtime_lock_identity(
    *,
    dependency_lock_content_hash: str,
    python_runtime_identity: str,
    parquet_writer_engine_identity: str,
    writer_configuration_version: str = WRITER_CONFIGURATION_VERSION,
) -> dict[str, str]:
    """Return only the four contract-approved writer identity fields."""
    return WriterRuntimeLock(
        dependency_lock_content_hash=_require_sha256(
            dependency_lock_content_hash, "dependency_lock_content_hash"
        ),
        python_runtime_identity=_require_non_empty_string(
            python_runtime_identity, "python_runtime_identity"
        ),
        parquet_writer_engine_identity=_require_non_empty_string(
            parquet_writer_engine_identity, "parquet_writer_engine_identity"
        ),
        writer_configuration_version=_require_non_empty_string(
            writer_configuration_version, "writer_configuration_version"
        ),
    ).as_dict()


def compute_writer_runtime_lock_hash(
    *,
    dependency_lock_content_hash: str,
    python_runtime_identity: str,
    parquet_writer_engine_identity: str,
    writer_configuration_version: str = WRITER_CONFIGURATION_VERSION,
) -> str:
    return sha256_hex(
        canonical_json(
            build_writer_runtime_lock_identity(
                dependency_lock_content_hash=dependency_lock_content_hash,
                python_runtime_identity=python_runtime_identity,
                parquet_writer_engine_identity=parquet_writer_engine_identity,
                writer_configuration_version=writer_configuration_version,
            )
        )
    )


def build_materialization_identity(
    projection: VerifiedResearchProjection,
    *,
    writer_runtime_lock_hash: str,
    coverage_basis_set_hash: str,
    build_code_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build the exact contract identity; wall-clock fields never enter it."""
    writer_hash = _require_sha256(writer_runtime_lock_hash, "writer_runtime_lock_hash")
    basis_hash = _require_sha256(coverage_basis_set_hash, "coverage_basis_set_hash")
    code_fingerprint = _require_sha256(
        build_code_fingerprint or research_code_fingerprint(), "build_code_fingerprint"
    )
    source_manifest_hash = _require_sha256(
        projection.source_snapshot_manifest_hash, "source_snapshot_manifest_hash"
    )
    source_semantic_hash = _require_sha256(
        projection.source_snapshot_semantic_hash, "source_snapshot_semantic_hash"
    )
    split_payload = {
        split.value: {"start": start.isoformat(), "end": end.isoformat()}
        for split, (start, end) in split_windows().items()
    }
    identity = {
        "contract_version": HISTORICAL_MATERIALIZATION_CONTRACT_VERSION,
        "target_dataset": HISTORICAL_DATASET,
        "target_window_start": TARGET_WINDOW_START.isoformat(),
        "target_window_end": TARGET_WINDOW_END.isoformat(),
        "research_split_windows": split_payload,
        "source_snapshot_id": _require_non_empty_string(
            projection.source_snapshot_id, "source_snapshot_id"
        ),
        "source_snapshot_as_of": ensure_utc_timestamp(projection.source_snapshot_as_of).isoformat(),
        "source_snapshot_manifest_hash": source_manifest_hash,
        "source_snapshot_semantic_hash": source_semantic_hash,
        "source_canonical_run_id": _require_non_empty_string(
            projection.source_canonical_run_id, "source_canonical_run_id"
        ),
        "source_readmodel_contract_version": _require_non_empty_string(
            projection.source_readmodel_contract_version, "source_readmodel_contract_version"
        ),
        "identity_view_version": _require_non_empty_string(
            projection.identity_view.version, "identity_view_version"
        ),
        "identity_view_hash": _require_sha256(
            projection.identity_view.content_hash, "identity_view_hash"
        ),
        "identity_source_kind": _require_non_empty_string(
            projection.identity_view.source_kind, "identity_source_kind"
        ),
        "identity_source_lineage_hash": _require_sha256(
            projection.identity_view.source_lineage_hash, "identity_source_lineage_hash"
        ),
        "schema_version": RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
        "price_basis": PRICE_BASIS,
        "universe_basis": UNIVERSE_BASIS,
        "coverage_policy_version": COVERAGE_POLICY_VERSION,
        "partition_policy_version": PARTITION_POLICY_VERSION,
        "build_code_fingerprint": code_fingerprint,
        "writer_runtime_lock_hash": writer_hash,
        "coverage_basis_set_hash": basis_hash,
    }
    if tuple(identity) != _EXPECTED_IDENTITY_FIELDS:
        raise HistoricalMaterializationError("materialization identity field order changed")
    return identity


def compute_idempotency_key(identity: Mapping[str, Any]) -> str:
    """Hash canonical JSON of exactly the merged contract identity fields."""
    if set(identity) != set(_EXPECTED_IDENTITY_FIELDS):
        raise HistoricalMaterializationError("materialization identity fields are not exact")
    return sha256_hex(canonical_json(identity))


def compute_materialization_id(identity: Mapping[str, Any]) -> str:
    return f"rhm-{compute_idempotency_key(identity)}"


def _route_for_row(row: Mapping[str, Any], ordinal: int) -> str:
    eligibility = row.get("research_eligibility")
    route_by_eligibility = {
        ResearchEligibility.ENABLED.value: "research_enabled",
        ResearchEligibility.DISABLED_UNRESOLVED.value: "disabled",
        ResearchEligibility.EXPERIMENTAL.value: "experimental",
    }
    if not isinstance(eligibility, str) or eligibility not in route_by_eligibility:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} has unknown research_eligibility"
        )
    route = route_by_eligibility[eligibility]
    if str(row.get("exchange") or "").strip().upper() == "BSE":
        if route == "research_enabled":
            raise HistoricalMaterializationError(
                "BSE row attempted to enter the research_enabled route"
            )
        # The current eligibility contract uses the lower-case exclusion
        # reason.  Do not let an unrelated disabled BSE row silently become a
        # future research route.
        if row.get("research_exclusion_reason") != "bse_identity_boundary_unresolved":
            raise HistoricalMaterializationError(
                "BSE disabled row lacks the explicit identity-boundary reason"
            )
    return route


def _validate_projection_row(
    row: Mapping[str, Any],
    *,
    ordinal: int,
    projection: VerifiedResearchProjection,
) -> tuple[date, ResearchSplit, str]:
    schema = research_security_daily_schema()
    expected_fields = set(schema)
    if set(row) != expected_fields:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} fields do not match the R1 schema"
        )
    trade_date = row.get("trade_date")
    if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
        raise HistoricalMaterializationError(f"projection row {ordinal} has invalid trade_date")
    assigned_split = assign_research_split(trade_date)
    try:
        declared_split = ResearchSplit(str(row["research_split"]))
    except ValueError as exc:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} has an unknown research_split"
        ) from exc
    if assigned_split != declared_split:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} research_split does not match trade_date"
        )
    if row.get("source_snapshot_id") != projection.source_snapshot_id:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} source_snapshot_id does not match projection"
        )
    if row.get("source_canonical_run_id") != projection.source_canonical_run_id:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} source_canonical_run_id does not match projection"
        )
    if row.get("source_readmodel_contract_version") != projection.source_readmodel_contract_version:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} readmodel contract does not match projection"
        )
    if row.get("identity_view_version") != projection.identity_view.version:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} identity_view_version does not match projection"
        )
    if row.get("identity_view_hash") != projection.identity_view.content_hash:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} identity_view_hash does not match projection"
        )
    route = _route_for_row(row, ordinal)
    if row.get("source_canonical_domain") != "daily_bar":
        raise HistoricalMaterializationError(
            f"projection row {ordinal} source_canonical_domain is not daily_bar"
        )
    exclusion_reason = row.get("research_exclusion_reason")
    if route == "research_enabled" and exclusion_reason is not None:
        raise HistoricalMaterializationError(
            f"projection row {ordinal} enabled route carries an exclusion reason"
        )
    if route != "research_enabled" and (
        not isinstance(exclusion_reason, str) or not exclusion_reason.strip()
    ):
        raise HistoricalMaterializationError(
            f"projection row {ordinal} disabled route lacks an exclusion reason"
        )
    if route == "research_enabled" and row.get("data_quality_state") != "VERIFIED":
        raise HistoricalMaterializationError(
            f"projection row {ordinal} enabled route is not VERIFIED"
        )
    return trade_date, declared_split, route


@dataclass(frozen=True)
class HistoricalArtifact:
    """One immutable route/split/month Parquet artifact in a plan."""

    route: str
    partition: PartitionKey
    relative_path: str
    uri: str
    payload: bytes
    content_hash: str
    semantic_hash: str
    schema_hash: str
    row_count: int
    byte_size: int
    coverage_state: CoverageState | None
    coverage_basis_id: str | None
    coverage_basis_artifact_hash: str | None
    min_trade_date: date
    max_trade_date: date

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route,
            "research_split": self.partition.research_split.value,
            "calendar_year": self.partition.calendar_year,
            "calendar_month": self.partition.calendar_month,
            "relative_path": self.relative_path,
            "uri": self.uri,
            "content_hash": self.content_hash,
            "semantic_hash": self.semantic_hash,
            "schema_hash": self.schema_hash,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
            "coverage_state": self.coverage_state.value if self.coverage_state else None,
            "coverage_basis_id": self.coverage_basis_id,
            "coverage_basis_artifact_hash": self.coverage_basis_artifact_hash,
            "min_trade_date": self.min_trade_date.isoformat(),
            "max_trade_date": self.max_trade_date.isoformat(),
        }


def _route_inventory_entry(
    route: str,
    artifact: HistoricalArtifact | None,
    *,
    coverage_evaluation: CoverageEvaluation | None = None,
) -> dict[str, Any]:
    if route == "research_enabled" and coverage_evaluation is None:
        raise HistoricalMaterializationError(
            "research_enabled inventory requires an explicit coverage evaluation"
        )
    evaluation_state = (
        coverage_evaluation.state.value
        if route == "research_enabled" and coverage_evaluation is not None
        else None
    )
    evaluation_evidence_class = (
        coverage_evaluation.evidence_class.value
        if route == "research_enabled" and coverage_evaluation is not None
        else None
    )
    evaluation_reason = (
        coverage_evaluation.reason
        if route == "research_enabled" and coverage_evaluation is not None
        else None
    )
    if artifact is None:
        return {
            "row_count": 0,
            "artifact_present": False,
            "relative_path": None,
            "uri": None,
            "content_hash": None,
            "semantic_hash": None,
            "schema_hash": None,
            "byte_size": 0,
            "coverage_state": evaluation_state,
            "coverage_evidence_class": evaluation_evidence_class,
            "coverage_reason": evaluation_reason,
            "coverage_basis_id": None,
            "coverage_basis_artifact_hash": None,
        }
    if route == "research_enabled":
        if coverage_evaluation is None:  # pragma: no cover - guarded above
            raise HistoricalMaterializationError(
                "research_enabled inventory requires an explicit coverage evaluation"
            )
        if artifact.coverage_state is not coverage_evaluation.state:
            raise HistoricalMaterializationError(
                "research_enabled artifact coverage disagrees with its partition evaluation"
            )
    return {
        "row_count": artifact.row_count,
        "artifact_present": True,
        "relative_path": artifact.relative_path,
        "uri": artifact.uri,
        "content_hash": artifact.content_hash,
        "semantic_hash": artifact.semantic_hash,
        "schema_hash": artifact.schema_hash,
        "byte_size": artifact.byte_size,
        "coverage_state": artifact.coverage_state.value if artifact.coverage_state else None,
        "coverage_evidence_class": evaluation_evidence_class,
        "coverage_reason": evaluation_reason,
        "coverage_basis_id": artifact.coverage_basis_id,
        "coverage_basis_artifact_hash": artifact.coverage_basis_artifact_hash,
    }


def _coverage_basis_relative_path(descriptor: CoverageBasisDescriptor) -> str:
    return (
        f"coverage_basis/{descriptor.research_split.value}/"
        f"year={descriptor.calendar_year:04d}/month={descriptor.calendar_month:02d}/"
        f"{descriptor.coverage_basis_artifact_hash}.json"
    )


def _coverage_basis_file_entry(descriptor: CoverageBasisDescriptor) -> dict[str, Any]:
    return {
        "coverage_basis_id": descriptor.coverage_basis_id,
        "declared_uri": descriptor.coverage_basis_artifact_uri,
        "relative_path": _coverage_basis_relative_path(descriptor),
        "content_hash": descriptor.coverage_basis_artifact_hash,
        "byte_size": len(descriptor.artifact_bytes),
    }


def _coverage_basis_evidence_relative_path(
    evidence: AuthoritativeCoverageEvidence,
) -> str:
    return f"coverage_basis_evidence/{evidence.coverage_basis_evidence_hash}.json"


def _coverage_basis_evidence_file_entry(
    evidence: AuthoritativeCoverageEvidence,
) -> dict[str, Any]:
    return {
        "coverage_basis_id": evidence.coverage_basis_id,
        "declared_uri": evidence.coverage_basis_evidence_uri,
        "relative_path": _coverage_basis_evidence_relative_path(evidence),
        "content_hash": evidence.coverage_basis_evidence_hash,
        "byte_size": len(evidence.artifact_bytes),
    }


@dataclass(frozen=True)
class HistoricalMaterializationPlan:
    """Fully computed, but not yet published, historical materialization."""

    materialization_identity: dict[str, Any]
    idempotency_key: str
    materialization_id: str
    coverage_state: CoverageState
    coverage_evidence_class: CoverageEvidenceClass
    coverage_basis_descriptors: tuple[CoverageBasisDescriptor, ...]
    coverage_evaluations: tuple[CoverageEvaluation, ...]
    identity_sources: tuple[dict[str, Any], ...]
    artifacts: tuple[HistoricalArtifact, ...]
    logical_partition_inventory: tuple[dict[str, Any], ...]
    partition_inventory_hash: str
    artifact_set_hash: str
    content_hash: str
    excluded_row_count: int
    excluded_reason_counts: dict[str, int]

    def manifest(self, *, build_timestamp: datetime | str) -> dict[str, Any]:
        built_at = ensure_utc_timestamp(build_timestamp)
        identity_view = self._identity_view_manifest()
        return {
            "dataset_name": HISTORICAL_DATASET,
            "contract_version": HISTORICAL_MATERIALIZATION_CONTRACT_VERSION,
            "schema_version": RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
            "publication_state": "COMMITTED",
            "materialization_id": self.materialization_id,
            "idempotency_key": self.idempotency_key,
            "materialization_identity": self.materialization_identity,
            "build_timestamp": built_at,
            "source_provenance": {
                "source_snapshot_id": self.materialization_identity["source_snapshot_id"],
                "source_snapshot_as_of": self.materialization_identity["source_snapshot_as_of"],
                "source_snapshot_manifest_hash": self.materialization_identity[
                    "source_snapshot_manifest_hash"
                ],
                "source_snapshot_semantic_hash": self.materialization_identity[
                    "source_snapshot_semantic_hash"
                ],
                "source_canonical_run_id": self.materialization_identity["source_canonical_run_id"],
                "source_readmodel_contract_version": self.materialization_identity[
                    "source_readmodel_contract_version"
                ],
                "identity_view": identity_view,
            },
            "price_basis": PRICE_BASIS,
            "universe_basis": UNIVERSE_BASIS,
            "coverage_state": self.coverage_state.value,
            "coverage_evidence_class": self.coverage_evidence_class.value,
            "coverage_policy_version": COVERAGE_POLICY_VERSION,
            "coverage_basis_set_hash": self.materialization_identity["coverage_basis_set_hash"],
            "coverage_basis_descriptors": [
                descriptor.as_dict() for descriptor in self.coverage_basis_descriptors
            ],
            "coverage_basis_artifacts": [
                _coverage_basis_file_entry(descriptor)
                for descriptor in self.coverage_basis_descriptors
            ],
            "coverage_basis_evidence": [
                _coverage_basis_evidence_file_entry(descriptor.authoritative_evidence)
                for descriptor in self.coverage_basis_descriptors
                if descriptor.authoritative_evidence is not None
            ],
            "partition_policy_version": PARTITION_POLICY_VERSION,
            "research_split_windows": self.materialization_identity["research_split_windows"],
            "target_window": {
                "start": TARGET_WINDOW_START,
                "end": TARGET_WINDOW_END,
                "inclusive": True,
            },
            "writer_runtime_lock_hash": self.materialization_identity["writer_runtime_lock_hash"],
            "build_code_fingerprint": self.materialization_identity["build_code_fingerprint"],
            "bse_policy": "DISABLE_ALL_BSE_ROWS_IN_R1",
            "index_panel_state": INDEX_PANEL_STATE,
            "read_policy": {
                "ordinary_read_requires": CoverageState.OBSERVED_DAILY_BAR_COVERAGE.value,
                "ordinary_read_requires_evidence_class": (
                    CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM.value
                ),
                "partial_or_unresolved": "BLOCKED",
            },
            "logical_partition_count": len(self.logical_partition_inventory),
            "logical_partition_inventory": self.logical_partition_inventory,
            "partition_inventory_uri": "partition_inventory.json",
            "partition_inventory_hash": self.partition_inventory_hash,
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "artifact_set_hash": self.artifact_set_hash,
            "content_hash": self.content_hash,
            "excluded_row_count": self.excluded_row_count,
            "excluded_reason_counts": self.excluded_reason_counts,
        }

    def _identity_view_manifest(self) -> dict[str, Any]:
        return {
            "version": self.materialization_identity["identity_view_version"],
            "content_hash": self.materialization_identity["identity_view_hash"],
            "source_kind": self.materialization_identity["identity_source_kind"],
            "source_lineage_hash": self.materialization_identity["identity_source_lineage_hash"],
            "sources": self.identity_sources,
        }


class OfflineHistoricalMaterializer:
    """Plan and atomically publish only bounded offline fixture materializations."""

    def __init__(
        self,
        root: Path,
        *,
        writer_runtime_lock_hash: str,
        build_code_fingerprint: str | None = None,
        authoritative_capture_root: Path | str | None = None,
    ) -> None:
        self.root = Path(root)
        self.writer_runtime_lock_hash = _require_sha256(
            writer_runtime_lock_hash, "writer_runtime_lock_hash"
        )
        self.build_code_fingerprint = build_code_fingerprint
        self.authoritative_capture_root = (
            Path(authoritative_capture_root) if authoritative_capture_root is not None else None
        )

    def plan(
        self,
        projection: VerifiedResearchProjection,
        *,
        coverage_bases: Sequence[CoverageBasisDescriptor] = (),
    ) -> HistoricalMaterializationPlan:
        if not isinstance(projection, VerifiedResearchProjection):
            raise HistoricalMaterializationError(
                "historical materialization requires VerifiedResearchProjection"
            )
        if projection.identity_view.source_kind == UNVERIFIED_CALLER_IDENTITY_SOURCE:
            raise HistoricalMaterializationError(
                "unverified caller identity rows cannot enter historical materialization"
            )
        if len(projection.rows) > _MAX_OFFLINE_FIXTURE_ROWS:
            raise HistoricalMaterializationError(
                f"offline fixture is limited to {_MAX_OFFLINE_FIXTURE_ROWS} rows"
            )
        normalized_rows: list[dict[str, Any]] = []
        seen_primary_keys: set[tuple[date, str]] = set()
        excluded_reasons: Counter[str] = Counter()
        for ordinal, raw_row in enumerate(projection.rows):
            if not isinstance(raw_row, Mapping):
                raise HistoricalMaterializationError(f"projection row {ordinal} is not an object")
            row = dict(raw_row)
            trade_date, declared_split, _ = _validate_projection_row(
                row, ordinal=ordinal, projection=projection
            )
            security_id = row.get("security_id")
            if not isinstance(security_id, str) or not security_id.strip():
                raise HistoricalMaterializationError(
                    f"projection row {ordinal} has an invalid security_id"
                )
            primary_key = (trade_date, security_id.strip())
            if primary_key in seen_primary_keys:
                raise HistoricalMaterializationError(
                    "duplicate historical primary key "
                    f"trade_date={trade_date} security_id={security_id}"
                )
            seen_primary_keys.add(primary_key)
            if declared_split in {ResearchSplit.WARMUP, ResearchSplit.OUTSIDE_WINDOW}:
                if row["research_eligibility"] == ResearchEligibility.ENABLED.value:
                    raise HistoricalMaterializationError(
                        "an enabled row cannot be outside the historical research window"
                    )
                reason = str(row.get("research_exclusion_reason") or "outside_research_window")
                excluded_reasons[reason] += 1
                continue
            normalized_rows.append(row)

        normalized_projection = VerifiedResearchProjection(
            rows=tuple(normalized_rows),
            source_snapshot_id=projection.source_snapshot_id,
            source_snapshot_as_of=projection.source_snapshot_as_of,
            source_canonical_run_id=projection.source_canonical_run_id,
            source_readmodel_contract_version=projection.source_readmodel_contract_version,
            source_snapshot_manifest_hash=projection.source_snapshot_manifest_hash,
            source_snapshot_semantic_hash=projection.source_snapshot_semantic_hash,
            identity_view=projection.identity_view,
        )
        descriptors = tuple(coverage_bases)
        evaluations = verify_coverage_basis(normalized_projection, descriptors)
        if any(descriptor.authoritative_evidence is not None for descriptor in descriptors) and (
            self.authoritative_capture_root is None
        ):
            raise HistoricalMaterializationError(
                "authoritative materialization requires the retained AmazingData capture root"
            )
        evaluation_by_key = {evaluation.partition: evaluation for evaluation in evaluations}
        basis_hash = compute_coverage_basis_set_hash(descriptors)
        identity = build_materialization_identity(
            projection,
            writer_runtime_lock_hash=self.writer_runtime_lock_hash,
            coverage_basis_set_hash=basis_hash,
            build_code_fingerprint=self.build_code_fingerprint,
        )
        idempotency_key = compute_idempotency_key(identity)
        materialization_id = f"rhm-{idempotency_key}"
        grouped: dict[tuple[PartitionKey, str], list[dict[str, Any]]] = defaultdict(list)
        for ordinal, row in enumerate(normalized_rows):
            trade_date, declared_split, route = _validate_projection_row(
                row, ordinal=ordinal, projection=normalized_projection
            )
            key = PartitionKey(declared_split, trade_date.year, trade_date.month)
            grouped[(key, route)].append(row)

        schema_hash = _schema_hash()
        artifacts: list[HistoricalArtifact] = []
        artifact_by_key: dict[tuple[PartitionKey, str], HistoricalArtifact] = {}
        for key in expected_partition_keys():
            for route in _ROUTES:
                rows = grouped.get((key, route), [])
                if not rows:
                    continue
                rows.sort(
                    key=lambda row: (
                        str(row["trade_date"]),
                        str(row["security_id"]),
                        str(row["source_canonical_key"]),
                    )
                )
                frame = pl.DataFrame(rows, schema=research_security_daily_schema(), strict=True)
                buffer = io.BytesIO()
                frame.write_parquet(buffer, compression="zstd", statistics=False)
                payload = buffer.getvalue()
                evaluation = evaluation_by_key[key]
                coverage_state = (
                    evaluation.state
                    if route == "research_enabled"
                    else CoverageState.UNRESOLVED_NOT_FOR_RESEARCH
                )
                descriptor = evaluation.descriptor if route == "research_enabled" else None
                relative_path = (
                    f"route={route}/split={key.research_split.value}/"
                    f"year={key.calendar_year:04d}/month={key.calendar_month:02d}/data.parquet"
                )
                uri = (
                    f"{HISTORICAL_DATASET}/contract={HISTORICAL_MATERIALIZATION_CONTRACT_VERSION}/"
                    f"materialization={materialization_id}/{relative_path}"
                )
                artifact = HistoricalArtifact(
                    route=route,
                    partition=key,
                    relative_path=relative_path,
                    uri=uri,
                    payload=payload,
                    content_hash=sha256_hex(payload),
                    semantic_hash=sha256_hex(canonical_json(frame.to_dicts())),
                    schema_hash=schema_hash,
                    row_count=frame.height,
                    byte_size=len(payload),
                    coverage_state=coverage_state,
                    coverage_basis_id=descriptor.coverage_basis_id if descriptor else None,
                    coverage_basis_artifact_hash=(
                        descriptor.coverage_basis_artifact_hash if descriptor else None
                    ),
                    min_trade_date=min(row["trade_date"] for row in rows),
                    max_trade_date=max(row["trade_date"] for row in rows),
                )
                _verify_artifact_payload(artifact, payload)
                artifacts.append(artifact)
                artifact_by_key[(key, route)] = artifact

        logical_inventory: list[dict[str, Any]] = []
        for key in expected_partition_keys():
            evaluation = evaluation_by_key[key]
            routes = {
                route: _route_inventory_entry(
                    route,
                    artifact_by_key.get((key, route)),
                    coverage_evaluation=evaluation if route == "research_enabled" else None,
                )
                for route in _ROUTES
            }
            logical_inventory.append(
                {
                    "research_split": key.research_split.value,
                    "calendar_year": key.calendar_year,
                    "calendar_month": key.calendar_month,
                    "logical_key": key.logical_key,
                    "routes": routes,
                }
            )
        ordered_artifacts = tuple(
            sorted(
                artifacts,
                key=lambda artifact: (
                    artifact.route,
                    artifact.partition.research_split.value,
                    artifact.partition.calendar_year,
                    artifact.partition.calendar_month,
                ),
            )
        )
        inventory_tuple = tuple(logical_inventory)
        partition_inventory_hash = sha256_hex(canonical_json(inventory_tuple))
        artifact_set_hash = sha256_hex(
            canonical_json([artifact.as_dict() for artifact in ordered_artifacts])
        )
        content_hash = sha256_hex(
            canonical_json(
                {
                    "schema_hash": schema_hash,
                    "artifacts": [
                        {
                            "route": artifact.route,
                            "research_split": artifact.partition.research_split.value,
                            "calendar_year": artifact.partition.calendar_year,
                            "calendar_month": artifact.partition.calendar_month,
                            "content_hash": artifact.content_hash,
                            "semantic_hash": artifact.semantic_hash,
                            "row_count": artifact.row_count,
                        }
                        for artifact in ordered_artifacts
                    ],
                    "partition_inventory_hash": partition_inventory_hash,
                    "coverage_basis_set_hash": basis_hash,
                    "writer_runtime_lock_hash": self.writer_runtime_lock_hash,
                    "excluded_row_count": sum(excluded_reasons.values()),
                }
            )
        )
        coverage_state = max(
            (evaluation.state for evaluation in evaluations),
            key=_coverage_rank,
        )
        coverage_evidence_class = _aggregate_coverage_evidence(evaluations)
        return HistoricalMaterializationPlan(
            materialization_identity=identity,
            idempotency_key=idempotency_key,
            materialization_id=materialization_id,
            coverage_state=coverage_state,
            coverage_evidence_class=coverage_evidence_class,
            coverage_basis_descriptors=tuple(sorted(descriptors, key=lambda item: item.sort_key)),
            coverage_evaluations=evaluations,
            identity_sources=tuple(source.as_dict() for source in projection.identity_view.sources),
            artifacts=ordered_artifacts,
            logical_partition_inventory=inventory_tuple,
            partition_inventory_hash=partition_inventory_hash,
            artifact_set_hash=artifact_set_hash,
            content_hash=content_hash,
            excluded_row_count=sum(excluded_reasons.values()),
            excluded_reason_counts=dict(sorted(excluded_reasons.items())),
        )

    def materialize(
        self,
        projection: VerifiedResearchProjection,
        *,
        coverage_bases: Sequence[CoverageBasisDescriptor] = (),
        build_timestamp: datetime | str,
    ) -> MaterializationResult:
        """Publish one plan through non-readable staging and a directory rename."""
        plan = self.plan(projection, coverage_bases=coverage_bases)
        manifest = plan.manifest(build_timestamp=build_timestamp)
        manifest_bytes = _pretty_json_bytes(manifest)
        inventory_bytes = _pretty_json_bytes(list(plan.logical_partition_inventory))
        marker_for_manifest = _success_marker(plan, sha256_hex(manifest_bytes))
        marker_bytes = _pretty_json_bytes(marker_for_manifest)
        dataset_root = self.root / HISTORICAL_DATASET
        final_dir = (
            dataset_root
            / f"contract={HISTORICAL_MATERIALIZATION_CONTRACT_VERSION}"
            / f"materialization={plan.materialization_id}"
        )
        if final_dir.exists():
            return self._verify_existing_final(plan, final_dir)

        stage_dir = dataset_root / ".staging" / plan.materialization_id
        stage_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            if stage_dir.exists():
                self._validate_stage_extras(stage_dir, plan)
            for artifact in plan.artifacts:
                self._write_staged_file(stage_dir / artifact.relative_path, artifact.payload)
            for descriptor in plan.coverage_basis_descriptors:
                self._write_staged_file(
                    stage_dir / _coverage_basis_relative_path(descriptor),
                    descriptor.artifact_bytes,
                )
                if descriptor.authoritative_evidence is not None:
                    self._write_staged_file(
                        stage_dir
                        / _coverage_basis_evidence_relative_path(descriptor.authoritative_evidence),
                        descriptor.authoritative_evidence.artifact_bytes,
                    )
            self._write_staged_file(stage_dir / "partition_inventory.json", inventory_bytes)
            stage_manifest = stage_dir / "manifest.json"
            if stage_manifest.exists():
                existing_manifest_bytes = stage_manifest.read_bytes()
                existing_manifest = _load_json_object(existing_manifest_bytes, "staged manifest")
                _assert_manifest_identity(existing_manifest, plan)
                manifest_bytes = existing_manifest_bytes
                marker_for_manifest = _success_marker(plan, sha256_hex(manifest_bytes))
                marker_bytes = _pretty_json_bytes(marker_for_manifest)
            else:
                self._write_staged_file(stage_manifest, manifest_bytes)
            self._write_staged_file(stage_dir / "_SUCCESS.json", marker_bytes)
            self._verify_staged(plan, stage_dir)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(stage_dir, final_dir)  # noqa: PTH105 - atomic directory publication
            except FileExistsError:
                return self._verify_existing_final(plan, final_dir)
        except ImmutableFileExistsError as exc:
            raise MaterializationConflictError(str(exc)) from exc
        manifest_hash = sha256_hex(manifest_bytes)
        return MaterializationResult(
            materialization_id=plan.materialization_id,
            idempotency_key=plan.idempotency_key,
            manifest_uri=(
                f"{HISTORICAL_DATASET}/contract={HISTORICAL_MATERIALIZATION_CONTRACT_VERSION}/"
                f"materialization={plan.materialization_id}/manifest.json"
            ),
            success_uri=(
                f"{HISTORICAL_DATASET}/contract={HISTORICAL_MATERIALIZATION_CONTRACT_VERSION}/"
                f"materialization={plan.materialization_id}/_SUCCESS.json"
            ),
            manifest_hash=manifest_hash,
            content_hash=plan.content_hash,
            partition_inventory_hash=plan.partition_inventory_hash,
            idempotent_replay=False,
        )

    def _write_staged_file(self, path: Path, payload: bytes) -> None:
        try:
            write_file_atomic(path, payload, allow_existing_identical=True)
        except ImmutableFileExistsError:
            raise

    @staticmethod
    def _validate_stage_extras(stage_dir: Path, plan: HistoricalMaterializationPlan) -> None:
        if not stage_dir.is_dir():
            raise MaterializationConflictError("staging identity is not a directory")
        expected = {artifact.relative_path for artifact in plan.artifacts}
        expected.update(
            _coverage_basis_relative_path(descriptor)
            for descriptor in plan.coverage_basis_descriptors
        )
        expected.update(
            _coverage_basis_evidence_relative_path(descriptor.authoritative_evidence)
            for descriptor in plan.coverage_basis_descriptors
            if descriptor.authoritative_evidence is not None
        )
        expected.update({"partition_inventory.json", "manifest.json", "_SUCCESS.json"})
        for path in stage_dir.rglob("*"):
            if path.is_file():
                relative = path.relative_to(stage_dir).as_posix()
                if relative not in expected and not relative.startswith(".tmp-"):
                    raise MaterializationConflictError(
                        f"staging contains unexpected file {relative!r}"
                    )

    def _verify_staged(self, plan: HistoricalMaterializationPlan, stage_dir: Path) -> None:
        for artifact in plan.artifacts:
            path = stage_dir / artifact.relative_path
            if not path.is_file():
                raise HistoricalMaterializationError(
                    f"staged artifact is missing: {artifact.relative_path}"
                )
            _verify_artifact_payload(artifact, path.read_bytes())
        for descriptor in plan.coverage_basis_descriptors:
            path = stage_dir / _coverage_basis_relative_path(descriptor)
            if not path.is_file() or path.read_bytes() != descriptor.artifact_bytes:
                raise MaterializationConflictError(
                    f"coverage basis bytes changed for {descriptor.coverage_basis_id}"
                )
            if descriptor.authoritative_evidence is not None:
                evidence_path = stage_dir / _coverage_basis_evidence_relative_path(
                    descriptor.authoritative_evidence
                )
                if (
                    not evidence_path.is_file()
                    or evidence_path.read_bytes()
                    != descriptor.authoritative_evidence.artifact_bytes
                ):
                    raise MaterializationConflictError(
                        "authoritative coverage evidence bytes changed for "
                        f"{descriptor.coverage_basis_id}"
                    )
                capture_root = self.authoritative_capture_root
                if capture_root is None:  # pragma: no cover - plan() guards this
                    raise MaterializationConflictError(
                        "authoritative materialization capture root is not configured"
                    )
                try:
                    descriptor.authoritative_evidence.acquisition_receipt.verify_retained_capture(
                        capture_root
                    )
                except CoverageBasisError as exc:
                    raise MaterializationConflictError(
                        "authoritative AmazingData capture proof chain is not replayable"
                    ) from exc
        inventory_path = stage_dir / "partition_inventory.json"
        inventory_bytes = inventory_path.read_bytes()
        inventory = _load_json_list(inventory_bytes, "staged partition inventory")
        if (
            inventory != list(plan.logical_partition_inventory)
            or sha256_hex(canonical_json(inventory)) != plan.partition_inventory_hash
        ):
            raise MaterializationConflictError("staged partition inventory bytes changed")
        manifest_path = stage_dir / "manifest.json"
        marker_path = stage_dir / "_SUCCESS.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = _load_json_object(manifest_bytes, "staged manifest")
        _assert_manifest_identity(manifest, plan)
        marker = _load_json_object(marker_path.read_bytes(), "staged success marker")
        _assert_success_marker(marker, plan, sha256_hex(manifest_bytes))

    def _verify_existing_final(
        self,
        plan: HistoricalMaterializationPlan,
        final_dir: Path,
    ) -> MaterializationResult:
        manifest_path = final_dir / "manifest.json"
        marker_path = final_dir / "_SUCCESS.json"
        if not manifest_path.is_file() or not marker_path.is_file():
            raise MaterializationConflictError(
                "materialization identity already exists without a valid committed marker"
            )
        manifest_bytes = manifest_path.read_bytes()
        manifest = _load_json_object(manifest_bytes, "committed manifest")
        _assert_manifest_identity(manifest, plan)
        _assert_success_marker(
            _load_json_object(marker_path.read_bytes(), "committed success marker"),
            plan,
            sha256_hex(manifest_bytes),
        )
        self._verify_staged(plan, final_dir)
        return MaterializationResult(
            materialization_id=plan.materialization_id,
            idempotency_key=plan.idempotency_key,
            manifest_uri=(
                f"{HISTORICAL_DATASET}/contract={HISTORICAL_MATERIALIZATION_CONTRACT_VERSION}/"
                f"materialization={plan.materialization_id}/manifest.json"
            ),
            success_uri=(
                f"{HISTORICAL_DATASET}/contract={HISTORICAL_MATERIALIZATION_CONTRACT_VERSION}/"
                f"materialization={plan.materialization_id}/_SUCCESS.json"
            ),
            manifest_hash=sha256_hex(manifest_bytes),
            content_hash=plan.content_hash,
            partition_inventory_hash=plan.partition_inventory_hash,
            idempotent_replay=True,
        )


@dataclass(frozen=True)
class MaterializationResult:
    materialization_id: str
    idempotency_key: str
    manifest_uri: str
    success_uri: str
    manifest_hash: str
    content_hash: str
    partition_inventory_hash: str
    idempotent_replay: bool


def _pretty_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_ready(value),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, datetime):
        return ensure_utc_timestamp(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, CoverageState):
        return value.value
    if isinstance(value, ResearchSplit):
        return value.value
    return value


def _load_json_object(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalMaterializationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise HistoricalMaterializationError(f"{label} must be a JSON object")
    return value


def _load_json_list(data: bytes, label: str) -> list[Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HistoricalReadError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, list):
        raise HistoricalReadError(f"{label} must be a JSON array")
    return value


def _success_marker(plan: HistoricalMaterializationPlan, manifest_hash: str) -> dict[str, Any]:
    return {
        "committed": True,
        "materialization_id": plan.materialization_id,
        "idempotency_key": plan.idempotency_key,
        "manifest_hash": manifest_hash,
        "partition_inventory_hash": plan.partition_inventory_hash,
        "artifact_set_hash": plan.artifact_set_hash,
        "content_hash": plan.content_hash,
    }


def _assert_manifest_identity(
    manifest: Mapping[str, Any],
    plan: HistoricalMaterializationPlan,
) -> None:
    if manifest.get("dataset_name") != HISTORICAL_DATASET:
        raise MaterializationConflictError("manifest dataset changed")
    if manifest.get("contract_version") != HISTORICAL_MATERIALIZATION_CONTRACT_VERSION:
        raise MaterializationConflictError("manifest contract changed")
    if manifest.get("schema_version") != RESEARCH_SECURITY_DAILY_SCHEMA_VERSION:
        raise MaterializationConflictError("manifest schema version changed")
    if (
        manifest.get("price_basis") != PRICE_BASIS
        or manifest.get("universe_basis") != UNIVERSE_BASIS
    ):
        raise MaterializationConflictError("manifest research semantics changed")
    if manifest.get("publication_state") != "COMMITTED":
        raise MaterializationConflictError("manifest is not in the committed state")
    if manifest.get("materialization_id") != plan.materialization_id:
        raise MaterializationConflictError("manifest materialization_id does not match")
    if manifest.get("idempotency_key") != plan.idempotency_key:
        raise MaterializationConflictError("manifest idempotency_key does not match")
    if manifest.get("materialization_identity") != plan.materialization_identity:
        raise MaterializationConflictError("materialization identity changed")
    if manifest.get("coverage_state") != plan.coverage_state.value:
        raise MaterializationConflictError("materialization coverage_state changed")
    if manifest.get("coverage_evidence_class") != plan.coverage_evidence_class.value:
        raise MaterializationConflictError("materialization coverage evidence class changed")
    if manifest.get("coverage_basis_descriptors") != [
        descriptor.as_dict() for descriptor in plan.coverage_basis_descriptors
    ]:
        raise MaterializationConflictError("coverage basis descriptor inventory changed")
    if manifest.get("coverage_basis_artifacts") != [
        _coverage_basis_file_entry(descriptor) for descriptor in plan.coverage_basis_descriptors
    ]:
        raise MaterializationConflictError("coverage basis artifact inventory changed")
    if manifest.get("coverage_basis_evidence") != [
        _coverage_basis_evidence_file_entry(descriptor.authoritative_evidence)
        for descriptor in plan.coverage_basis_descriptors
        if descriptor.authoritative_evidence is not None
    ]:
        raise MaterializationConflictError("authoritative coverage evidence inventory changed")
    if manifest.get("partition_inventory_hash") != plan.partition_inventory_hash:
        raise MaterializationConflictError("partition inventory hash changed")
    if manifest.get("artifact_set_hash") != plan.artifact_set_hash:
        raise MaterializationConflictError("artifact set hash changed")
    if manifest.get("content_hash") != plan.content_hash:
        raise MaterializationConflictError("materialization content hash changed")
    if manifest.get("logical_partition_inventory") != list(plan.logical_partition_inventory):
        raise MaterializationConflictError("logical partition inventory changed")
    if manifest.get("artifacts") != [artifact.as_dict() for artifact in plan.artifacts]:
        raise MaterializationConflictError("partition artifact inventory changed")


def _assert_success_marker(
    marker: Mapping[str, Any],
    plan: HistoricalMaterializationPlan,
    manifest_hash: str,
) -> None:
    expected = _success_marker(plan, manifest_hash)
    if dict(marker) != expected:
        raise MaterializationConflictError("_SUCCESS marker is missing or inconsistent")


def _verify_artifact_payload(artifact: HistoricalArtifact, payload: bytes) -> None:
    if sha256_hex(payload) != artifact.content_hash:
        raise MaterializationConflictError(f"artifact bytes changed for {artifact.relative_path}")
    try:
        frame = pl.read_parquet(io.BytesIO(payload))
    except Exception as exc:
        raise HistoricalMaterializationError(
            f"artifact is not readable Parquet: {artifact.relative_path}"
        ) from exc
    actual_schema_hash = _schema_hash_from_frame(frame)
    if actual_schema_hash != artifact.schema_hash:
        raise MaterializationConflictError(f"artifact schema changed for {artifact.relative_path}")
    if frame.height != artifact.row_count:
        raise MaterializationConflictError(
            f"artifact row count changed for {artifact.relative_path}"
        )
    if sha256_hex(canonical_json(frame.to_dicts())) != artifact.semantic_hash:
        raise MaterializationConflictError(
            f"artifact semantic hash changed for {artifact.relative_path}"
        )
    if frame.height:
        key_frame = frame.select(["trade_date", "security_id"])
        if key_frame.unique().height != frame.height:
            raise MaterializationConflictError(
                f"artifact has duplicate primary keys: {artifact.relative_path}"
            )
        if set(frame.get_column("research_split").unique().to_list()) != {
            artifact.partition.research_split.value
        }:
            raise MaterializationConflictError(
                f"artifact mixes research splits: {artifact.relative_path}"
            )
        expected_eligibility = {
            "research_enabled": ResearchEligibility.ENABLED.value,
            "disabled": ResearchEligibility.DISABLED_UNRESOLVED.value,
            "experimental": ResearchEligibility.EXPERIMENTAL.value,
        }[artifact.route]
        if set(frame.get_column("research_eligibility").unique().to_list()) != {
            expected_eligibility
        }:
            raise MaterializationConflictError(
                f"artifact mixes research routes: {artifact.relative_path}"
            )


def _schema_hash_from_frame(frame: pl.DataFrame) -> str:
    descriptor = [(name, str(frame.schema[name])) for name in frame.schema]
    return sha256_hex(canonical_json(descriptor))


def _resolve_relative_file(parent: Path, relative_path: str) -> Path:
    safe = _safe_relative_uri(relative_path, "relative_path")
    candidate = (parent / Path(*PurePosixPath(safe).parts)).resolve()
    resolved_parent = parent.resolve()
    try:
        candidate.relative_to(resolved_parent)
    except ValueError as exc:
        raise HistoricalReadError("artifact path escapes the committed materialization") from exc
    return candidate


@dataclass(frozen=True)
class HistoricalMaterializationReader:
    """Ordinary reader gate for the separate CR-7 committed contract."""

    manifest_path: Path
    manifest: dict[str, Any]

    @classmethod
    def from_manifest(
        cls,
        manifest_path: Path,
        *,
        authoritative_capture_root: Path | str | None = None,
    ) -> HistoricalMaterializationReader:
        path = Path(manifest_path)
        if ".staging" in path.parts:
            raise HistoricalReadError("staging materializations are never readable")
        if path.name != "manifest.json" or not path.is_file():
            raise HistoricalReadError("historical manifest.json is missing")
        manifest_bytes = path.read_bytes()
        manifest = _load_json_object(manifest_bytes, "historical manifest")
        if manifest.get("dataset_name") != HISTORICAL_DATASET:
            raise HistoricalReadError("manifest is not research_security_daily")
        if manifest.get("contract_version") != HISTORICAL_MATERIALIZATION_CONTRACT_VERSION:
            raise HistoricalReadError("unknown historical materialization contract")
        if manifest.get("schema_version") != RESEARCH_SECURITY_DAILY_SCHEMA_VERSION:
            raise HistoricalReadError("unknown historical research schema")
        if (
            manifest.get("price_basis") != PRICE_BASIS
            or manifest.get("universe_basis") != UNIVERSE_BASIS
        ):
            raise HistoricalReadError("historical research semantics changed")
        if manifest.get("publication_state") != "COMMITTED":
            raise HistoricalReadError("historical materialization is not committed")
        if manifest.get("coverage_state") != CoverageState.OBSERVED_DAILY_BAR_COVERAGE.value:
            raise HistoricalReadError(
                "ordinary historical reader refuses partial or unresolved coverage"
            )
        if (
            manifest.get("coverage_evidence_class")
            != CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM.value
        ):
            raise HistoricalReadError(
                "ordinary historical reader refuses non-authoritative coverage evidence"
            )
        read_policy = manifest.get("read_policy")
        if not isinstance(read_policy, Mapping) or (
            read_policy.get("ordinary_read_requires_evidence_class")
            != CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM.value
        ):
            raise HistoricalReadError("historical reader authority policy is missing or changed")
        marker_path = path.parent / "_SUCCESS.json"
        if not marker_path.is_file():
            raise HistoricalReadError("committed historical materialization lacks _SUCCESS.json")
        marker = _load_json_object(marker_path.read_bytes(), "historical success marker")
        if marker.get("committed") is not True:
            raise HistoricalReadError("historical success marker is not committed")
        if marker.get("manifest_hash") != sha256_hex(manifest_bytes):
            raise HistoricalReadError("historical manifest hash does not match _SUCCESS")
        if marker.get("materialization_id") != manifest.get("materialization_id"):
            raise HistoricalReadError("historical marker materialization identity mismatch")
        for field in ("partition_inventory_hash", "artifact_set_hash", "content_hash"):
            if marker.get(field) != manifest.get(field):
                raise HistoricalReadError(f"historical marker {field} mismatch")
        identity = manifest.get("materialization_identity")
        if not isinstance(identity, Mapping) or set(identity) != set(_EXPECTED_IDENTITY_FIELDS):
            raise HistoricalReadError("historical materialization identity is malformed")
        try:
            expected_materialization_id = compute_materialization_id(identity)
        except HistoricalMaterializationError as exc:
            raise HistoricalReadError("historical materialization identity is invalid") from exc
        if expected_materialization_id != manifest.get("materialization_id"):
            raise HistoricalReadError("historical materialization identity hash mismatch")
        inventory_path = path.parent / "partition_inventory.json"
        if not inventory_path.is_file():
            raise HistoricalReadError("historical partition inventory is missing")
        inventory = _load_json_list(inventory_path.read_bytes(), "historical partition inventory")
        if len(inventory) != 78 or inventory != manifest.get("logical_partition_inventory"):
            raise HistoricalReadError("historical logical partition inventory changed")
        if sha256_hex(canonical_json(inventory)) != manifest.get("partition_inventory_hash"):
            raise HistoricalReadError("historical partition inventory hash changed")
        expected_keys = set(expected_partition_keys())
        inventory_keys: set[PartitionKey] = set()
        for raw_inventory in inventory:
            if not isinstance(raw_inventory, Mapping):
                raise HistoricalReadError("historical logical partition inventory is malformed")
            try:
                inventory_key = PartitionKey(
                    ResearchSplit(str(raw_inventory["research_split"])),
                    raw_inventory["calendar_year"],
                    raw_inventory["calendar_month"],
                )
            except (KeyError, TypeError, ValueError, HistoricalMaterializationError) as exc:
                raise HistoricalReadError(
                    "historical logical partition inventory has an invalid partition"
                ) from exc
            inventory_keys.add(inventory_key)
            routes = raw_inventory.get("routes")
            enabled_route = routes.get("research_enabled") if isinstance(routes, Mapping) else None
            if not isinstance(enabled_route, Mapping):
                raise HistoricalReadError(
                    "historical logical partition inventory lacks research_enabled coverage"
                )
            if (
                enabled_route.get("coverage_state")
                != CoverageState.OBSERVED_DAILY_BAR_COVERAGE.value
                or enabled_route.get("coverage_evidence_class")
                != CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM.value
                or enabled_route.get("artifact_present") is not True
            ):
                raise HistoricalReadError(
                    "ordinary historical reader requires complete enabled-route inventory"
                )
        if inventory_keys != expected_keys:
            raise HistoricalReadError("historical logical partition inventory has wrong scope")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise HistoricalReadError("historical manifest has no artifact inventory")
        if sha256_hex(canonical_json(artifacts)) != manifest.get("artifact_set_hash"):
            raise HistoricalReadError("historical artifact set hash changed")
        basis_descriptors = manifest.get("coverage_basis_descriptors")
        basis_files = manifest.get("coverage_basis_artifacts")
        evidence_files = manifest.get("coverage_basis_evidence")
        if (
            not isinstance(basis_descriptors, list)
            or not isinstance(basis_files, list)
            or not isinstance(evidence_files, list)
        ):
            raise HistoricalReadError("historical coverage-basis evidence is missing")
        if len(basis_descriptors) != len(basis_files):
            raise HistoricalReadError("historical coverage-basis evidence is incomplete")
        if len(evidence_files) != len(basis_descriptors):
            raise HistoricalReadError(
                "ordinary historical reader requires one authoritative evidence sidecar per basis"
            )
        parsed_bases: list[CoverageBasisDescriptor] = []
        try:
            expected_snapshot_as_of = ensure_utc_timestamp(str(identity["source_snapshot_as_of"]))
        except (HistoricalMaterializationError, ResearchPanelError) as exc:
            raise HistoricalReadError("historical materialization snapshot PIT is invalid") from exc
        expected_snapshot_id = identity.get("source_snapshot_id")
        expected_snapshot_hash = identity.get("source_snapshot_manifest_hash")
        if not isinstance(expected_snapshot_id, str) or not expected_snapshot_id:
            raise HistoricalReadError("historical materialization source snapshot id is invalid")
        try:
            expected_snapshot_hash = _require_sha256(
                expected_snapshot_hash, "source_snapshot_manifest_hash"
            )
        except HistoricalMaterializationError as exc:
            raise HistoricalReadError(
                "historical materialization source snapshot hash is invalid"
            ) from exc
        for raw_descriptor, raw_file, raw_evidence_file in zip(
            basis_descriptors, basis_files, evidence_files, strict=True
        ):
            if (
                not isinstance(raw_descriptor, Mapping)
                or not isinstance(raw_file, Mapping)
                or not isinstance(raw_evidence_file, Mapping)
            ):
                raise HistoricalReadError("historical coverage-basis evidence is malformed")
            basis_path = _resolve_relative_file(path.parent, str(raw_file.get("relative_path")))
            if not basis_path.is_file():
                raise HistoricalReadError("historical coverage-basis artifact is missing")
            basis_bytes = basis_path.read_bytes()
            evidence_path = _resolve_relative_file(
                path.parent, str(raw_evidence_file.get("relative_path"))
            )
            if not evidence_path.is_file():
                raise HistoricalReadError("authoritative coverage evidence sidecar is missing")
            evidence_bytes = evidence_path.read_bytes()
            try:
                evidence = AuthoritativeCoverageEvidence.from_mapping(
                    _load_json_object(evidence_bytes, "authoritative coverage evidence"),
                    artifact_bytes=evidence_bytes,
                    artifact_hash=str(raw_evidence_file.get("content_hash")),
                )
            except (CoverageBasisError, HistoricalMaterializationError) as exc:
                raise HistoricalReadError(
                    "authoritative coverage evidence sidecar is invalid"
                ) from exc
            if dict(raw_evidence_file) != _coverage_basis_evidence_file_entry(evidence):
                raise HistoricalReadError("authoritative coverage evidence inventory changed")
            if (
                evidence.source_snapshot_id != expected_snapshot_id
                or evidence.source_snapshot_manifest_hash != expected_snapshot_hash
            ):
                raise HistoricalReadError("authoritative coverage evidence source snapshot changed")
            if evidence.source_snapshot_as_of != expected_snapshot_as_of:
                raise HistoricalReadError("authoritative coverage evidence snapshot PIT changed")
            if authoritative_capture_root is None:
                raise HistoricalReadError(
                    "ordinary historical reader requires the retained AmazingData capture root"
                )
            try:
                evidence.acquisition_receipt.verify_retained_capture(authoritative_capture_root)
            except CoverageBasisError as exc:
                raise HistoricalReadError(
                    "authoritative AmazingData capture proof chain is not replayable"
                ) from exc
            try:
                descriptor = CoverageBasisDescriptor.from_mapping(
                    raw_descriptor,
                    artifact_bytes=basis_bytes,
                    authoritative_evidence=evidence,
                )
            except CoverageBasisError as exc:
                raise HistoricalReadError("historical coverage-basis artifact is invalid") from exc
            if dict(raw_file) != _coverage_basis_file_entry(descriptor):
                raise HistoricalReadError("historical coverage-basis inventory changed")
            if descriptor.evidence_class is not CoverageEvidenceClass.AUTHORITATIVE_UPSTREAM:
                raise HistoricalReadError(
                    "ordinary historical reader refuses fixture-only coverage evidence"
                )
            parsed_bases.append(descriptor)
        if (
            len(parsed_bases) != len(expected_keys)
            or {descriptor.partition_key for descriptor in parsed_bases} != expected_keys
        ):
            raise HistoricalReadError("historical coverage-basis scope is incomplete")
        if compute_coverage_basis_set_hash(tuple(parsed_bases)) != manifest.get(
            "coverage_basis_set_hash"
        ):
            raise HistoricalReadError("historical coverage-basis set hash changed")
        for raw_artifact in artifacts:
            if not isinstance(raw_artifact, Mapping):
                raise HistoricalReadError("historical artifact inventory is malformed")
            if raw_artifact.get("route") != "research_enabled":
                continue
            artifact_path = _resolve_relative_file(path.parent, str(raw_artifact["relative_path"]))
            if not artifact_path.is_file():
                raise HistoricalReadError("historical artifact is missing")
            payload = artifact_path.read_bytes()
            if sha256_hex(payload) != raw_artifact.get("content_hash"):
                raise HistoricalReadError("historical artifact content hash changed")
            try:
                frame = pl.read_parquet(io.BytesIO(payload))
            except Exception as exc:
                raise HistoricalReadError("historical artifact is not readable Parquet") from exc
            if frame.height != raw_artifact.get("row_count"):
                raise HistoricalReadError("historical artifact row count changed")
            if _schema_hash_from_frame(frame) != raw_artifact.get("schema_hash"):
                raise HistoricalReadError("historical artifact schema changed")
            if sha256_hex(canonical_json(frame.to_dicts())) != raw_artifact.get("semantic_hash"):
                raise HistoricalReadError("historical artifact semantic hash changed")
        return cls(manifest_path=path, manifest=manifest)

    def load_security_daily(
        self,
        *,
        split: ResearchSplit | str,
        start: date | str | None = None,
        end: date | str | None = None,
        security_ids: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        try:
            research_split = ResearchSplit(split)
        except ValueError as exc:
            raise HistoricalReadError(f"unknown research split {split!r}") from exc
        if research_split not in {
            ResearchSplit.DEVELOPMENT,
            ResearchSplit.VALIDATION_A,
            ResearchSplit.HOLDOUT,
        }:
            raise HistoricalReadError("warmup/outside_window is not an ordinary read split")
        window_start, window_end = split_windows()[research_split]
        start_date = window_start if start is None else parse_date_value(start)
        end_date = window_end if end is None else parse_date_value(end)
        if start_date < window_start or end_date > window_end or start_date > end_date:
            raise HistoricalReadError("historical read range crosses its split window")
        if security_ids is not None:
            if not isinstance(security_ids, Sequence) or isinstance(security_ids, str):
                raise HistoricalReadError("security_ids must be a sequence")
            normalized_ids = []
            for security_id in security_ids:
                if not isinstance(security_id, str) or not security_id.strip():
                    raise HistoricalReadError("security_ids must contain non-empty strings")
                normalized_ids.append(security_id.strip())
            if len(normalized_ids) != len(set(normalized_ids)):
                raise HistoricalReadError("security_ids must not contain duplicates")
        else:
            normalized_ids = None
        frames: list[pl.DataFrame] = []
        for raw_artifact in self.manifest["artifacts"]:
            if (
                raw_artifact.get("route") != "research_enabled"
                or raw_artifact.get("research_split") != research_split.value
            ):
                continue
            artifact_path = _resolve_relative_file(
                self.manifest_path.parent, str(raw_artifact["relative_path"])
            )
            frames.append(pl.read_parquet(artifact_path))
        if not frames:
            return pl.DataFrame(schema=research_security_daily_schema())
        result = pl.concat(frames, how="vertical")
        result = result.filter(pl.col("trade_date").is_between(start_date, end_date, closed="both"))
        if normalized_ids is not None:
            result = result.filter(pl.col("security_id").is_in(normalized_ids))
        return result.sort(["trade_date", "security_id", "source_canonical_key"])
