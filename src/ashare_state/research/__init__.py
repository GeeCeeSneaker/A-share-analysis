"""CR-7 R1 research-ready security daily panel.

R1 consumes only a verified CR-4 ReadModel snapshot.  It publishes an
immutable, versioned Parquet panel with an explicit semantic manifest.  The
index panel remains disabled until the repository has a verified index
identity/read-model contract.
"""

from ashare_state.research.eligibility import EligibilityDecision, evaluate_daily_bar
from ashare_state.research.models import (
    INDEX_PANEL_STATE,
    PRICE_BASIS,
    RESEARCH_CONTRACT_VERSION,
    RESEARCH_DATASET_VERSION,
    RESEARCH_SECURITY_DAILY_DATASET,
    RESEARCH_SECURITY_DAILY_FIELDS,
    RESEARCH_SECURITY_DAILY_SCHEMA_VERSION,
    UNIVERSE_BASIS,
    CoverageState,
    DataQualityState,
    ExclusionReason,
    IdentityRecord,
    IdentityView,
    IndexPanelState,
    ResearchEligibility,
    ResearchManifest,
    ResearchManifestError,
    ResearchPanelError,
    ResearchReaderError,
    ResearchSplit,
    research_security_daily_schema,
)
from ashare_state.research.panel import ResearchBuildResult, ResearchPanelBuilder
from ashare_state.research.reader import (
    ResearchPanelReader,
    load_disabled_research_security_daily,
    load_research_security_daily,
)
from ashare_state.research.splits import (
    assert_research_split_date,
    assign_research_split,
    split_window,
)

__all__ = [
    "CoverageState",
    "DataQualityState",
    "EligibilityDecision",
    "ExclusionReason",
    "INDEX_PANEL_STATE",
    "IdentityRecord",
    "IdentityView",
    "IndexPanelState",
    "PRICE_BASIS",
    "RESEARCH_CONTRACT_VERSION",
    "RESEARCH_DATASET_VERSION",
    "RESEARCH_SECURITY_DAILY_DATASET",
    "RESEARCH_SECURITY_DAILY_FIELDS",
    "RESEARCH_SECURITY_DAILY_SCHEMA_VERSION",
    "ResearchBuildResult",
    "ResearchEligibility",
    "ResearchManifest",
    "ResearchManifestError",
    "ResearchPanelBuilder",
    "ResearchPanelError",
    "ResearchPanelReader",
    "ResearchReaderError",
    "ResearchSplit",
    "UNIVERSE_BASIS",
    "assign_research_split",
    "assert_research_split_date",
    "evaluate_daily_bar",
    "load_disabled_research_security_daily",
    "load_research_security_daily",
    "research_security_daily_schema",
    "split_window",
]
