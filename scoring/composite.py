"""
evidence_council/scoring/composite.py

Composite scoring for evidence layer governance.

The composite score ranks all layers that clear the 0.98 CI threshold.
Weight choices and domain profile rationale are documented in docs/scoring.md.
Any changes to defaults or profiles must be accompanied by a changelog
entry in that file.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Reference normalisation constant for consistency component.
# Layers with historical std-dev >= this value score 0 on consistency.
# See docs/scoring.md — "Historical consistency" for rationale.
# ---------------------------------------------------------------------------
_CONSISTENCY_REF_STDDEV = 0.15

# Maximum fractional penalty applied to layers with 0% reviewer approval.
# approval_penalty = 1.0 - (APPROVAL_PENALTY_MAX * (1.0 - approval_rate))
_APPROVAL_PENALTY_MAX = 0.30


# ---------------------------------------------------------------------------
# ScoringConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoringConfig:
    """
    Composite score weights for evidence layer ranking.

    All four weights must sum to 1.0. Validation is performed at construction.

    Attributes:
        weight_ci_lower:    Weight for bootstrap CI lower bound (primary signal).
        weight_pass_rate:   Weight for raw empirical pass rate.
        weight_cost:        Weight for cost efficiency (applied to 1 - cost_score).
        weight_consistency: Weight for historical std-dev stability.
        close_call_margin:  Composite score margin within which a ReviewTask is
                            emitted even when a winner exists. See docs/scoring.md.
        label:              Human-readable profile name for logging and audit records.
    """

    weight_ci_lower:    float
    weight_pass_rate:   float
    weight_cost:        float
    weight_consistency: float
    close_call_margin:  float = 0.03
    label:              str   = "custom"

    def __post_init__(self) -> None:
        total = self.weight_ci_lower + self.weight_pass_rate + self.weight_cost + self.weight_consistency
        if not abs(total - 1.0) < 1e-6:
            raise ValueError(
                f"ScoringConfig weights must sum to 1.0, got {total:.6f}. "
                f"(ci_lower={self.weight_ci_lower}, pass_rate={self.weight_pass_rate}, "
                f"cost={self.weight_cost}, consistency={self.weight_consistency})"
            )
        for name, val in [
            ("weight_ci_lower",    self.weight_ci_lower),
            ("weight_pass_rate",   self.weight_pass_rate),
            ("weight_cost",        self.weight_cost),
            ("weight_consistency", self.weight_consistency),
        ]:
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{name} must be in [0.0, 1.0], got {val}")
        if self.close_call_margin < 0.0:
            raise ValueError(f"close_call_margin must be >= 0.0, got {self.close_call_margin}")

    # ------------------------------------------------------------------
    # Built-in domain profiles
    # ------------------------------------------------------------------

    @classmethod
    def default(cls) -> "ScoringConfig":
        """
        General AI evaluation profile.

        Balances statistical quality, pass rate, cost, and consistency.
        Appropriate for garak probe pipelines and general LLM safety evaluation.

        See docs/scoring.md — ScoringConfig.default() for full rationale.
        """
        return cls(
            weight_ci_lower=0.45,
            weight_pass_rate=0.25,
            weight_cost=0.20,
            weight_consistency=0.10,
            label="default",
        )

    @classmethod
    def healthcare(cls) -> "ScoringConfig":
        """
        Clinical and regulated healthcare profile.

        Statistical reliability and consistency are weighted heavily.
        Cost is de-emphasised: in regulated contexts the cost of a governance
        failure outweighs the cost of a more expensive evidence layer.

        Appropriate for: clinical decision support, diagnostic assistance,
        patient-facing outputs, FDA/HIPAA/HL7 FHIR/CMS governed systems.

        See docs/scoring.md — ScoringConfig.healthcare() for full rationale.
        """
        return cls(
            weight_ci_lower=0.50,
            weight_pass_rate=0.30,
            weight_cost=0.05,
            weight_consistency=0.15,
            label="healthcare",
        )

    @classmethod
    def cost_sensitive(cls) -> "ScoringConfig":
        """
        High-throughput, cost-constrained evaluation profile.

        Cost is promoted as a primary tiebreaker while the 0.98 CI threshold
        remains unchanged — cost sensitivity affects selection among qualifying
        layers only, not the statistical bar for qualification.

        Appropriate for: large-scale evaluation sweeps, CI/CD pipelines with
        budget constraints, high-volume production evaluation.

        See docs/scoring.md — ScoringConfig.cost_sensitive() for full rationale.
        """
        return cls(
            weight_ci_lower=0.40,
            weight_pass_rate=0.20,
            weight_cost=0.35,
            weight_consistency=0.05,
            label="cost_sensitive",
        )

    def as_dict(self) -> dict[str, float | str]:
        """Serialisable representation for inclusion in KnowledgeRecord metadata."""
        return {
            "profile":           self.label,
            "weight_ci_lower":   self.weight_ci_lower,
            "weight_pass_rate":  self.weight_pass_rate,
            "weight_cost":       self.weight_cost,
            "weight_consistency":self.weight_consistency,
            "close_call_margin": self.close_call_margin,
        }


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def consistency_component(historical_stddev: float) -> float:
    """
    Normalise historical std-dev of ci_lower into a [0, 1] score.

    A std-dev of 0.0 (perfectly consistent) returns 1.0.
    A std-dev >= _CONSISTENCY_REF_STDDEV (0.15) returns 0.0.
    Layers with no history (stddev=0.0) are treated as maximally consistent
    for their first run — neither rewarded for history nor penalised for lacking it.

    Args:
        historical_stddev: Standard deviation of ci_lower across prior runs.

    Returns:
        Consistency component in [0.0, 1.0].
    """
    return max(0.0, 1.0 - (historical_stddev / _CONSISTENCY_REF_STDDEV))


def approval_penalty(approval_rate: float) -> float:
    """
    Multiplicative penalty factor derived from reviewer approval history.

    A layer with 100% approval carries no penalty (returns 1.0).
    A layer with 0% approval carries a 30% penalty (returns 0.7).
    New layers with no review history receive an optimistic prior of 1.0
    (no penalty) — this is set in KnowledgeLayer.reviewer_approval_rate().

    Args:
        approval_rate: Fraction of reviewer verdicts that were "approved" (0.0–1.0).

    Returns:
        Penalty multiplier in [1 - _APPROVAL_PENALTY_MAX, 1.0].
    """
    return 1.0 - (_APPROVAL_PENALTY_MAX * (1.0 - approval_rate))


def compute_composite_score(
    ci_lower:           float,
    pass_rate:          float,
    cost_score:         float,
    historical_stddev:  float = 0.0,
    reviewer_approval:  float = 1.0,
    config:             ScoringConfig | None = None,
) -> float:
    """
    Compute the composite governance score for an evidence layer.

    Higher is better. Score is in [0, 1] under normal inputs.

    Formula:
        composite = (
            W_CI_LOWER    * ci_lower
          + W_PASS_RATE   * pass_rate
          + W_COST        * (1.0 - cost_score)
          + W_CONSISTENCY * consistency_component(historical_stddev)
        ) * approval_penalty(reviewer_approval)

    See docs/scoring.md for full component rationale and weight choices.

    Args:
        ci_lower:           Bootstrap CI lower bound at the governance threshold.
        pass_rate:          Raw empirical pass rate (passes / (passes + fails)).
        cost_score:         Normalised cost in [0.0, 1.0]; 0.0 = cheapest.
        historical_stddev:  Std-dev of ci_lower across prior runs for this layer.
                            Pass 0.0 for first-run layers (neutral prior).
        reviewer_approval:  Fraction of reviewer verdicts that were "approved".
                            Pass 1.0 for layers with no review history (optimistic prior).
        config:             ScoringConfig profile. Defaults to ScoringConfig.default().

    Returns:
        Composite score as a float. Typically in [0.0, 1.0]; may slightly
        exceed 1.0 if ci_lower or pass_rate are above 1.0 due to floating
        point — callers should treat the value as a relative ranking signal,
        not an absolute probability.
    """
    cfg = config or ScoringConfig.default()

    cost_component   = 1.0 - cost_score
    consist_comp     = consistency_component(historical_stddev)
    penalty          = approval_penalty(reviewer_approval)

    raw = (
          cfg.weight_ci_lower    * ci_lower
        + cfg.weight_pass_rate   * pass_rate
        + cfg.weight_cost        * cost_component
        + cfg.weight_consistency * consist_comp
    )

    return raw * penalty


def rank_by_composite(
    candidates: list[dict],
    config: ScoringConfig | None = None,
) -> list[dict]:
    """
    Sort a list of candidate dicts by composite score (descending).

    Each dict must contain:
        ci_lower, pass_rate, cost_score
    And optionally:
        historical_stddev (default 0.0)
        reviewer_approval (default 1.0)

    The composite score is added to each dict under the key "composite_score"
    and the profile label under "scoring_profile".

    Args:
        candidates: List of candidate dicts (mutated in place with scores).
        config:     ScoringConfig profile. Defaults to ScoringConfig.default().

    Returns:
        The same list, sorted descending by composite_score.
    """
    cfg = config or ScoringConfig.default()

    for c in candidates:
        c["composite_score"] = compute_composite_score(
            ci_lower=          c["ci_lower"],
            pass_rate=         c["pass_rate"],
            cost_score=        c["cost_score"],
            historical_stddev= c.get("historical_stddev", 0.0),
            reviewer_approval= c.get("reviewer_approval", 1.0),
            config=            cfg,
        )
        c["scoring_profile"] = cfg.label

    candidates.sort(key=lambda x: x["composite_score"], reverse=True)
    return candidates


def is_close_call(
    ranked: list[dict],
    config: ScoringConfig | None = None,
) -> bool:
    """
    Return True if the top-2 composite scores are within close_call_margin.

    A close call triggers a ReviewTask even when a clear winner exists,
    because a margin within close_call_margin is within the noise of the
    weight assumptions. See docs/scoring.md — Close Call Detection.

    Args:
        ranked: List of candidate dicts already sorted by composite_score
                (as returned by rank_by_composite).
        config: ScoringConfig profile. Defaults to ScoringConfig.default().

    Returns:
        True if len(ranked) >= 2 and the score gap is within close_call_margin.
    """
    cfg = config or ScoringConfig.default()
    if len(ranked) < 2:
        return False
    gap = ranked[0]["composite_score"] - ranked[1]["composite_score"]
    return gap < cfg.close_call_margin
