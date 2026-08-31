"""Provider-Normalized + Quarantine runtime (CR-2, audit 20260831)."""

from ashare_state.normalization.registry import (
    DATASET_NORMALIZATION_REGISTRY,
    NORMALIZATION_CONTRACT_VERSION,
    DatasetNormalizationSpec,
    NormalizationErrorClass,
    NormalizationRunStatus,
    QuarantineScope,
    SurfaceSupport,
    lookup_spec,
    mapper_identity_for,
)
from ashare_state.normalization.runner import (
    NormalizationRunner,
    NormalizationRunnerError,
    NormalizationRunResult,
)

__all__ = [
    "DATASET_NORMALIZATION_REGISTRY",
    "NORMALIZATION_CONTRACT_VERSION",
    "DatasetNormalizationSpec",
    "NormalizationErrorClass",
    "NormalizationRunResult",
    "NormalizationRunStatus",
    "NormalizationRunner",
    "NormalizationRunnerError",
    "QuarantineScope",
    "SurfaceSupport",
    "lookup_spec",
    "mapper_identity_for",
]
