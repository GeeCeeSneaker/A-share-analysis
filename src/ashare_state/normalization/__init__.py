"""Provider-Normalization boundary (CR-2 / CR-2.1, audit 20260831).

The formal normalization boundary: persisted Raw evidence ->
provider-faithful normalized parquet + first-class quarantine +
``meta_provider_normalization_run`` ledger. The registry is an
immutable PRIVATE static structure exposed through read-only lookup
functions only (CR-2.1 P0-02); ordinary callers can neither mutate it
nor hand the runner a spec/mapper/registry.
"""

from ashare_state.normalization.registry import (
    MAPPER_CODE_FINGERPRINT,
    NORMALIZATION_CONTRACT_VERSION,
    DatasetNormalizationSpec,
    NormalizationErrorClass,
    NormalizationRunStatus,
    QuarantineScope,
    SurfaceSupport,
    lookup_spec,
    mapper_identity_for,
    registry_specs,
    specs_for,
)
from ashare_state.normalization.runner import (
    NormalizationRunner,
    NormalizationRunnerError,
    NormalizationRunResult,
)

__all__ = [
    "MAPPER_CODE_FINGERPRINT",
    "NORMALIZATION_CONTRACT_VERSION",
    "DatasetNormalizationSpec",
    "NormalizationErrorClass",
    "NormalizationRunStatus",
    "NormalizationRunner",
    "NormalizationRunnerError",
    "NormalizationRunResult",
    "QuarantineScope",
    "SurfaceSupport",
    "lookup_spec",
    "mapper_identity_for",
    "registry_specs",
    "specs_for",
]
