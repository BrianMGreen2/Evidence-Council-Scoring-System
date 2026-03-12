"""
evidence_council.scoring
========================

Scoring primitives for evidence layer governance.

Modules
-------
bootstrap_ci
    Bootstrap confidence interval calculation at the 0.98 governance
    threshold. Pure functions with no side effects; independently testable.

composite
    ScoringConfig domain profiles and compute_composite_score. Weights
    combine CI lower bound, pass rate, cost efficiency, and historical
    consistency into a single ranking signal.

All weight choices and domain profile rationale are documented in
docs/scoring.md. Changes to defaults must include a changelog entry there.
"""

from evidence_council.scoring.bootstrap_ci import (
    bootstrap_ci,
    passes_governance_threshold,
    minimum_passes_for_threshold,
    compare_layers,
    CIResult,
    GOVERNANCE_CI_THRESHOLD,
    DEFAULT_N_BOOTSTRAP,
)
from evidence_council.scoring.composite import (
    ScoringConfig,
    compute_composite_score,
    consistency_component,
    approval_penalty,
    rank_by_composite,
    is_close_call,
)

__all__ = [
    # bootstrap_ci
    "bootstrap_ci",
    "passes_governance_threshold",
    "minimum_passes_for_threshold",
    "compare_layers",
    "CIResult",
    "GOVERNANCE_CI_THRESHOLD",
    "DEFAULT_N_BOOTSTRAP",
    # composite
    "ScoringConfig",
    "compute_composite_score",
    "consistency_component",
    "approval_penalty",
    "rank_by_composite",
    "is_close_call",
]
