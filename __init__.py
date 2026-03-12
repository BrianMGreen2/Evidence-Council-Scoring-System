"""
evidence_council
================

Exhaustive evidence layer governance — bootstrap CI scoring, composite
ranking, and human/agent review council for AI evaluation pipelines.

Public API
----------

Core evaluation:
    GovernanceEvaluator     Run exhaustive evidence layer evaluation
    EvidenceLayer           Input data structure for a single layer
    GovernanceResult        Full result of an evaluation run
    GovernanceDecision      Enum: PASS | SUBSTITUTED | FLAG

Scoring:
    ScoringConfig           Domain-specific weight profiles
    compute_composite_score Composite score calculation
    bootstrap_ci            Bootstrap CI at the 0.98 governance threshold
    CIResult                Immutable CI result with margin/width helpers

Knowledge layer:
    KnowledgeLayer          Append-only persistent artifact
    KnowledgeRecord         Single committed evaluation record

Review council:
    ReviewTask              Task emitted for human or agent review
    ReviewQueue             In-memory queue of pending ReviewTask objects

Constants:
    GOVERNANCE_CI_THRESHOLD 0.98 — the governance CI lower bound threshold

Typical usage
-------------

    from evidence_council import (
        GovernanceEvaluator,
        EvidenceLayer,
        KnowledgeLayer,
        ScoringConfig,
    )

    kl = KnowledgeLayer()

    evaluator = GovernanceEvaluator(
        knowledge_layer=kl,
        probe="probe.xss.reflection",
        detector="det.bert.toxic",
        scoring_config=ScoringConfig.healthcare(),
    )

    result = evaluator.evaluate(
        primary_layer=EvidenceLayer(name="layer_primary", passes=491, fails=9),
        candidate_layers=[
            EvidenceLayer(name="layer_semantic_v3", passes=497, fails=3, cost_score=0.4),
            EvidenceLayer(name="layer_regex_strict", passes=494, fails=6, cost_score=0.1),
        ],
    )

    print(result.decision)           # GovernanceDecision.SUBSTITUTED
    print(result.winner.layer.name)  # layer_semantic_v3
    print(result.winner.ci_lower)    # 0.9823

See docs/scoring.md for weight rationale and domain profile documentation.
"""

from evidence_council.evaluator import (
    GovernanceEvaluator,
    EvidenceLayer,
    GovernanceResult,
    GovernanceDecision,
    CandidateResult,
)
from evidence_council.knowledge_layer import (
    KnowledgeLayer,
    KnowledgeRecord,
)
from evidence_council.scoring.composite import (
    ScoringConfig,
    compute_composite_score,
    consistency_component,
    approval_penalty,
    rank_by_composite,
    is_close_call,
)
from evidence_council.scoring.bootstrap_ci import (
    bootstrap_ci,
    CIResult,
    passes_governance_threshold,
    minimum_passes_for_threshold,
    compare_layers,
    GOVERNANCE_CI_THRESHOLD,
    DEFAULT_N_BOOTSTRAP,
)
from evidence_council.reviewer.tasks import (
    ReviewTask,
    ReviewQueue,
    ReviewVerdict,
)

__version__ = "0.1.0"

__all__ = [
    # Core evaluation
    "GovernanceEvaluator",
    "EvidenceLayer",
    "GovernanceResult",
    "GovernanceDecision",
    "CandidateResult",
    # Knowledge layer
    "KnowledgeLayer",
    "KnowledgeRecord",
    # Scoring
    "ScoringConfig",
    "compute_composite_score",
    "consistency_component",
    "approval_penalty",
    "rank_by_composite",
    "is_close_call",
    # Bootstrap CI
    "bootstrap_ci",
    "CIResult",
    "passes_governance_threshold",
    "minimum_passes_for_threshold",
    "compare_layers",
    "GOVERNANCE_CI_THRESHOLD",
    "DEFAULT_N_BOOTSTRAP",
    # Review council
    "ReviewTask",
    "ReviewQueue",
    "ReviewVerdict",
]
