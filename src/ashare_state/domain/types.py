"""Core domain enums and constants (V1.3.2 Frozen Baseline semantics).

These enums are the single source of truth for status values that cross
module boundaries and enter DuckDB storage. Never inline these strings.
"""

from __future__ import annotations

from enum import StrEnum


class ObservationType(StrEnum):
    """V1.3.2 section 1.3: information priority hierarchy."""

    DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
    DERIVED_FACT = "DERIVED_FACT"
    PROVIDER_DERIVED = "PROVIDER_DERIVED"
    SEMANTIC_LABEL = "SEMANTIC_LABEL"


class AvailabilityKind(StrEnum):
    """V1.3.2 section 2.3 / 6.0: how available_at was established."""

    OBSERVED = "OBSERVED"
    CONSERVATIVE_ASSUMED = "CONSERVATIVE_ASSUMED"


class AvailabilityStatus(StrEnum):
    """Spike-derived evidence maturity for availability rules (design ruling 12)."""

    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"


class IdentityKeyVersion(StrEnum):
    """ADR-002: deterministic security identity key versions."""

    SECURITY_IDENTITY_V1 = "SECURITY_IDENTITY_V1"
    SECURITY_IDENTITY_V1_FALLBACK = "SECURITY_IDENTITY_V1_FALLBACK"


class SnapshotStatus(StrEnum):
    """V1.3.2 section 6.40."""

    STAGING = "STAGING"
    DATA_VALIDATED = "DATA_VALIDATED"
    RETIRED = "RETIRED"


class ArtifactSetStatus(StrEnum):
    """V1.3.2 section 6.41A."""

    STAGING = "STAGING"
    FEATURE_VALIDATED = "FEATURE_VALIDATED"
    RETIRED = "RETIRED"


class PublishStatus(StrEnum):
    """V1.3.2 section 6.44 / design ruling: publish state machine."""

    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class PipelineRunStatus(StrEnum):
    """V1.3.2 section 6.42."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FEATURE_VALIDATED = "FEATURE_VALIDATED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    PUBLISHED = "PUBLISHED"


class ReconciliationStatus(StrEnum):
    """Design ruling 3.4: single-source self-checks are NOT reconciliation.

    When only one provider is active, the only honest value is
    NOT_RUN_NO_SECONDARY. Forging PASS is forbidden.
    """

    NOT_RUN_NO_SECONDARY = "NOT_RUN_NO_SECONDARY"
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class EquivalenceVerdict(StrEnum):
    """Design ruling 3.1: four-level capability assessment for provider substitution."""

    EXACT_EQUIVALENT = "EXACT_EQUIVALENT"
    DERIVABLE_EQUIVALENT = "DERIVABLE_EQUIVALENT"
    ALTERNATIVE_SEMANTICS = "ALTERNATIVE_SEMANTICS"
    MISSING = "MISSING"


class SpikeVerdict(StrEnum):
    """Design ruling 4: three-level overall Spike conclusion."""

    GO_CORE = "GO_CORE"
    GO_DEGRADED = "GO_DEGRADED"
    NO_GO = "NO_GO"


class DifferenceReasonCode(StrEnum):
    """Design ruling 11: explainable difference attribution categories.

    A Spike case difference without one of these reason codes is a FAIL.
    """

    CORPORATE_ACTION = "CORPORATE_ACTION"
    PRICE_TICK_ROUNDING = "PRICE_TICK_ROUNDING"
    AFTER_HOURS_INCLUDED = "AFTER_HOURS_INCLUDED"
    SESSION_BOUNDARY = "SESSION_BOUNDARY"
    SYMBOL_MAPPING = "SYMBOL_MAPPING"
    SOURCE_REVISION = "SOURCE_REVISION"
    PROVIDER_TIMING = "PROVIDER_TIMING"
    DOCUMENTED_UNIT_DIFFERENCE = "DOCUMENTED_UNIT_DIFFERENCE"


class QualityFlag(StrEnum):
    """Quality flags used across canonical layers (extensible)."""

    IDENTITY_FALLBACK = "IDENTITY_FALLBACK"
    STALE_WINDOW = "STALE_WINDOW"
    BENCHMARK_UNAVAILABLE = "BENCHMARK_UNAVAILABLE"
    INVALID_LIMIT_RANGE = "INVALID_LIMIT_RANGE"
    NO_LIMIT_RULE = "NO_LIMIT_RULE"
    LOW_SAMPLE = "LOW_SAMPLE"
