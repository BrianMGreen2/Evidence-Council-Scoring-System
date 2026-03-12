"""
evaluator.py

Exhaustive governance evaluator.
- Ranks candidate_layers via KnowledgeLayer BEFORE evaluation (ordering only)
- Evaluates ALL candidates that reach the 0.98 CI threshold
- Selects winner by composite score across ALL qualifying candidates
- Commits every result to the knowledge layer
- Emits a ReviewTask when no candidate passes OR when composite scores are close
"""

from __future__ import annotations

import uuid
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from knowledge_layer import (
    KnowledgeLayer,
    KnowledgeRecord,
    compute_composite_score,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOVERNANCE_CI_THRESHOLD  = 0.98
N_BOOTSTRAP              = 10_000
# If the top-2 composite scores are within this margin, escalate to review
CLOSE_CALL_MARGIN        = 0.03


class GovernanceDecision(Enum):
    PASS        = "pass"         # primary layer cleared threshold
    SUBSTITUTED = "substituted"  # winner is a candidate layer, not primary
    FLAG        = "flag"         # no layer cleared threshold


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EvidenceLayer:
    name: str
    passes: int
    fails: int
    nones: int = 0
    cost_score: float = 0.5      # 0.0 cheapest – 1.0 most expensive
    latency_ms: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        total = self.passes + self.fails
        return self.passes / total if total > 0 else 0.0


@dataclass
class CandidateResult:
    layer: EvidenceLayer
    ci_lower: float
    ci_upper: float
    passes_threshold: bool
    composite_score: float
    consistency: float
    approval_rate: float
    knowledge_record: KnowledgeRecord


@dataclass
class GovernanceResult:
    decision: GovernanceDecision
    winner: Optional[CandidateResult]
    all_results: list[CandidateResult]         # all evaluated, sorted by composite
    qualifying_results: list[CandidateResult]  # only those >= 0.98 threshold
    probe: str
    detector: str
    threshold: float
    close_call: bool = False
    flag_reason: Optional[str] = None
    review_task: Optional["ReviewTask"] = None


@dataclass
class ReviewTask:
    """
    Emitted whenever human or agent review is needed.
    Consumed by the reviewer interface / agent council.
    """
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    reason: str = ""                   # "no_passing_layer" | "close_call" | "reviewer_rejection"
    probe: str = ""
    detector: str = ""
    qualifying_results: list[CandidateResult] = field(default_factory=list)
    all_results: list[CandidateResult] = field(default_factory=list)
    proposed_winner: Optional[CandidateResult] = None
    status: str = "pending"            # "pending" | "approved" | "rejected" | "deferred"
    reviewer_id: Optional[str] = None
    reviewer_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------

def bootstrap_ci(
    passes: int,
    fails: int,
    n_bootstrap: int = N_BOOTSTRAP,
    ci_level: float = GOVERNANCE_CI_THRESHOLD,
    rng_seed: Optional[int] = None,
) -> tuple[float, float]:
    rng = np.random.default_rng(rng_seed)
    total = passes + fails
    if total == 0:
        return (0.0, 0.0)
    observed = passes / total
    samples = rng.binomial(total, observed, size=n_bootstrap) / total
    alpha = 1.0 - ci_level
    lower = float(np.percentile(samples, 100 * (alpha / 2)))
    upper = float(np.percentile(samples, 100 * (1 - alpha / 2)))
    return lower, upper


# ---------------------------------------------------------------------------
# Core evaluator
# ---------------------------------------------------------------------------

class GovernanceEvaluator:
    """
    Exhaustive evaluator with knowledge-layer-informed ranking.

    Usage:
        kl = KnowledgeLayer()
        ev = GovernanceEvaluator(kl, probe="probe.name", detector="det.name")
        result = ev.evaluate(primary_layer, candidate_layers, cost_map={...})
    """

    def __init__(
        self,
        knowledge_layer: KnowledgeLayer,
        probe: str,
        detector: str,
        threshold: float = GOVERNANCE_CI_THRESHOLD,
        n_bootstrap: int = N_BOOTSTRAP,
    ):
        self.kl         = knowledge_layer
        self.probe      = probe
        self.detector   = detector
        self.threshold  = threshold
        self.n_bootstrap = n_bootstrap

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        primary_layer: EvidenceLayer,
        candidate_layers: list[EvidenceLayer],
        cost_map: Optional[dict[str, float]] = None,
    ) -> GovernanceResult:
        """
        1. Rank ALL layers (primary + candidates) via knowledge layer priors
        2. Evaluate every layer exhaustively
        3. Collect ALL layers that clear the 0.98 threshold
        4. Score all qualifying layers by composite metric
        5. Select winner = highest composite among qualifying
        6. Emit ReviewTask if: no winners, close call, or threshold margin is tight
        7. Commit all results to knowledge layer
        """
        all_layers = [primary_layer] + candidate_layers
        cost_map = cost_map or {l.name: l.cost_score for l in all_layers}

        # Step 1 — rank by knowledge-layer priors (ordering only)
        ranking = self.kl.rank_candidates(
            [l.name for l in all_layers],
            self.probe,
            self.detector,
            cost_map,
        )
        rank_order = {r["layer_name"]: i for i, r in enumerate(ranking)}
        all_layers.sort(key=lambda l: rank_order.get(l.name, 999))

        # Step 2 — exhaustive evaluation of every layer
        all_results: list[CandidateResult] = []
        for layer in all_layers:
            result = self._evaluate_layer(layer)
            all_results.append(result)

        # Step 3 — collect qualifying layers
        qualifying = [r for r in all_results if r.passes_threshold]

        # Step 4+5 — sort qualifying by composite score; winner = highest
        qualifying.sort(key=lambda r: r.composite_score, reverse=True)
        winner = qualifying[0] if qualifying else None

        # Step 6 — close-call detection
        close_call = (
            len(qualifying) >= 2
            and (qualifying[0].composite_score - qualifying[1].composite_score) < CLOSE_CALL_MARGIN
        )

        # Step 7 — determine decision
        if winner is None:
            decision = GovernanceDecision.FLAG
            flag_reason = self._build_flag_reason(all_results)
        elif winner.layer.name == primary_layer.name:
            decision = GovernanceDecision.PASS
            flag_reason = None
        else:
            decision = GovernanceDecision.SUBSTITUTED
            flag_reason = None

        # Build review task if needed
        review_task = None
        if decision == GovernanceDecision.FLAG or close_call:
            review_task = ReviewTask(
                reason="no_passing_layer" if decision == GovernanceDecision.FLAG else "close_call",
                probe=self.probe,
                detector=self.detector,
                qualifying_results=qualifying,
                all_results=all_results,
                proposed_winner=winner,
            )

        # Commit all results to knowledge layer
        for r in all_results:
            self.kl.commit(r.knowledge_record)

        result = GovernanceResult(
            decision=decision,
            winner=winner,
            all_results=all_results,
            qualifying_results=qualifying,
            probe=self.probe,
            detector=self.detector,
            threshold=self.threshold,
            close_call=close_call,
            flag_reason=flag_reason,
            review_task=review_task,
        )

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_layer(self, layer: EvidenceLayer) -> CandidateResult:
        ci_lower, ci_upper = bootstrap_ci(
            layer.passes, layer.fails,
            n_bootstrap=self.n_bootstrap,
            ci_level=self.threshold,
        )
        passes_threshold = ci_lower >= self.threshold
        consistency      = self.kl.historical_consistency(layer.name, self.probe, self.detector)
        approval_rate    = self.kl.reviewer_approval_rate(layer.name)

        composite = compute_composite_score(
            ci_lower, layer.pass_rate, layer.cost_score, consistency
        ) * (1.0 - 0.3 * (1.0 - approval_rate))   # approval penalty

        record = KnowledgeRecord(
            layer_name=layer.name,
            probe=self.probe,
            detector=self.detector,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            pass_rate=layer.pass_rate,
            passes=layer.passes,
            fails=layer.fails,
            cost_score=layer.cost_score,
            latency_ms=layer.latency_ms,
            governance_decision=(
                "pass" if passes_threshold else "flag"
            ),
            composite_score=composite,
        )

        return CandidateResult(
            layer=layer,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            passes_threshold=passes_threshold,
            composite_score=composite,
            consistency=consistency,
            approval_rate=approval_rate,
            knowledge_record=record,
        )

    def _build_flag_reason(self, results: list[CandidateResult]) -> str:
        best = max(results, key=lambda r: r.ci_lower)
        return (
            f"No evidence layer reached CI lower bound >= {self.threshold:.2f}. "
            f"Best was '{best.layer.name}' with ci_lower={best.ci_lower:.4f} "
            f"(pass_rate={best.layer.pass_rate:.3f})"
        )

    # ------------------------------------------------------------------
    # Reviewer integration
    # ------------------------------------------------------------------

    def apply_reviewer_decision(
        self,
        review_task: ReviewTask,
        reviewer_id: str,
        verdict: str,                  # "approved" | "rejected" | "deferred"
        chosen_layer_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """
        Patch knowledge layer records with reviewer verdict.
        If reviewer overrides the proposed winner, update accordingly.
        """
        review_task.status       = verdict
        review_task.reviewer_id  = reviewer_id
        review_task.reviewer_notes = notes

        target_name = chosen_layer_name or (
            review_task.proposed_winner.layer.name
            if review_task.proposed_winner else None
        )

        for cr in review_task.all_results:
            v = "approved" if cr.layer.name == target_name and verdict == "approved" else (
                "rejected" if verdict == "rejected" else "deferred"
            )
            self.kl.update_reviewer_verdict(
                run_id=cr.knowledge_record.run_id,
                reviewer_id=reviewer_id,
                verdict=v,
                notes=notes,
            )
