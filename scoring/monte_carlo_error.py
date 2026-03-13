"""
evidence_council/scoring/monte_carlo_error.py

Monte Carlo error estimation, boundary case detection, and corrective
action array for bootstrap CI governance decisions.

Monte Carlo error arises because bootstrap CI is itself a stochastic
estimator — two runs with different seeds produce slightly different
ci_lower values. Near the 0.98 governance threshold, this noise can
flip a PASS/FAIL decision without any real change in layer quality.

This module provides:
  - MCErrorEstimate      Dataclass holding MC error statistics for a CI run
  - BoundaryStatus       Enum classifying how close a result is to threshold
  - CorrectiveAction     Enum of available responses to MC error
  - CorrectiveActionRule Dataclass mapping boundary status to actions
  - CORRECTIVE_ACTION_ARRAY  The ordered rule table consumed by the evaluator
  - estimate_mc_error()  Repeated-bootstrap MC error estimation
  - classify_boundary()  Classify a CIResult against the action array
  - adaptive_bootstrap_ci()  Drop-in replacement for bootstrap_ci() with
                             adaptive n and MC error attached

Design principles
-----------------
1. Quantify rather than suppress. MC error is real and bounded; the right
   response is to measure it and route uncertain decisions to the council.

2. Escalate at the boundary. A layer whose ci_lower is within 3 * mc_error
   of the threshold is statistically unstable — the governance response is
   escalation, not false precision.

3. The knowledge layer accumulates evidence. A genuinely borderline layer
   will show high historical_stddev, which lowers its composite score and
   deprioritises it in future runs. The corrective action array is the
   per-run safety net; the knowledge layer is the longitudinal one.

4. Reproducibility via rng_seed. Every MC error estimate is seeded so
   the result committed to the knowledge layer can be approximated in audit.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from evidence_council.scoring.bootstrap_ci import (
    bootstrap_ci,
    CIResult,
    GOVERNANCE_CI_THRESHOLD,
    DEFAULT_N_BOOTSTRAP,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Boundary margin around the governance threshold.
#: Layers with |ci_lower - threshold| < BOUNDARY_MARGIN trigger adaptive logic.
BOUNDARY_MARGIN: float = 0.02

#: Multiplier of mc_error_lower used to classify hard boundary cases.
#: If |ci_lower - threshold| < SIGMA_MULTIPLIER * mc_error_lower → HARD boundary.
SIGMA_MULTIPLIER: float = 3.0

#: n_bootstrap used for boundary cases (5× the default).
BOUNDARY_N_BOOTSTRAP: int = 50_000

#: Number of repeated bootstrap runs used to estimate MC standard error.
#: 20 repeats gives a stable std estimate without excessive compute.
MC_ERROR_N_REPEATS: int = 20

#: If mc_error_lower exceeds this value the estimate itself is unreliable.
MC_ERROR_HIGH_WATERMARK: float = 0.005


# ---------------------------------------------------------------------------
# BoundaryStatus
# ---------------------------------------------------------------------------

class BoundaryStatus(str, Enum):
    """
    Classification of a CI result relative to the governance threshold
    and the estimated Monte Carlo error.

    CLEAR_PASS
        ci_lower >= threshold + BOUNDARY_MARGIN.
        Decision is statistically stable. No corrective action needed.

    CLEAR_FAIL
        ci_upper < threshold - BOUNDARY_MARGIN.
        Layer is comfortably below threshold. No corrective action needed.

    SOFT_BOUNDARY_PASS
        ci_lower >= threshold but within BOUNDARY_MARGIN of it.
        Passes, but MC noise could flip this to a fail on another run.
        Corrective: increase n_bootstrap, attach MC error to record.

    SOFT_BOUNDARY_FAIL
        ci_lower < threshold but within BOUNDARY_MARGIN of it.
        Fails, but MC noise could flip this to a pass on another run.
        Corrective: increase n_bootstrap, escalate to review council.

    HARD_BOUNDARY
        |ci_lower - threshold| < SIGMA_MULTIPLIER * mc_error_lower.
        Decision is within the noise envelope of the estimator itself.
        Corrective: maximum n_bootstrap, mandatory council escalation,
        flag in knowledge layer as statistically unstable.
    """
    CLEAR_PASS         = "clear_pass"
    CLEAR_FAIL         = "clear_fail"
    SOFT_BOUNDARY_PASS = "soft_boundary_pass"
    SOFT_BOUNDARY_FAIL = "soft_boundary_fail"
    HARD_BOUNDARY      = "hard_boundary"


# ---------------------------------------------------------------------------
# CorrectiveAction
# ---------------------------------------------------------------------------

class CorrectiveAction(str, Enum):
    """
    Available corrective actions in response to MC error classification.

    NONE
        No action required. Proceed with standard evaluation flow.

    INCREASE_N_BOOTSTRAP
        Re-run bootstrap_ci with BOUNDARY_N_BOOTSTRAP resamples.
        Reduces MC error at the cost of compute.

    ATTACH_MC_ERROR
        Compute and commit mc_error_lower / mc_error_upper to the
        KnowledgeRecord. Adds auditability without changing the decision.

    ESCALATE_TO_COUNCIL
        Emit a ReviewTask with reason="boundary_instability". The council
        (human or agent) makes the final call on a boundary decision.

    REQUIRE_MORE_TRIALS
        Flag that the evidence layer needs more evaluation trials before
        the CI estimate is reliable. Commit with a "needs_more_data" warning.

    COMMIT_AS_UNSTABLE
        Commit the result to the knowledge layer with is_boundary=True.
        The historical_stddev will accumulate across runs and naturally
        deprioritise this layer via the composite score's consistency component.
    """
    NONE                 = "none"
    INCREASE_N_BOOTSTRAP = "increase_n_bootstrap"
    ATTACH_MC_ERROR      = "attach_mc_error"
    ESCALATE_TO_COUNCIL  = "escalate_to_council"
    REQUIRE_MORE_TRIALS  = "require_more_trials"
    COMMIT_AS_UNSTABLE   = "commit_as_unstable"


# ---------------------------------------------------------------------------
# CorrectiveActionRule
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CorrectiveActionRule:
    """
    A single row in the corrective action array.

    Maps a BoundaryStatus to an ordered sequence of corrective actions,
    a minimum n_bootstrap override, and a flag indicating whether a
    ReviewTask must be emitted.

    Attributes:
        status:           The BoundaryStatus this rule applies to.
        actions:          Ordered list of CorrectiveAction to apply.
                          Applied in sequence; all actions execute unless
                          the evaluator short-circuits on ESCALATE_TO_COUNCIL.
        min_n_bootstrap:  Minimum n_bootstrap to enforce when this rule fires.
                          None = use whatever the caller specified.
        must_escalate:    If True, a ReviewTask is emitted regardless of
                          whether the layer passes or fails the threshold.
        description:      Human-readable explanation for audit logs and
                          conference slides.
    """
    status:          BoundaryStatus
    actions:         tuple[CorrectiveAction, ...]
    min_n_bootstrap: Optional[int]
    must_escalate:   bool
    description:     str


# ---------------------------------------------------------------------------
# CORRECTIVE_ACTION_ARRAY
# ---------------------------------------------------------------------------

CORRECTIVE_ACTION_ARRAY: tuple[CorrectiveActionRule, ...] = (

    CorrectiveActionRule(
        status=BoundaryStatus.CLEAR_PASS,
        actions=(CorrectiveAction.NONE,),
        min_n_bootstrap=None,
        must_escalate=False,
        description=(
            "Layer comfortably clears threshold (ci_lower >= threshold + margin). "
            "Monte Carlo error is not material to this decision. "
            "Proceed with standard composite ranking."
        ),
    ),

    CorrectiveActionRule(
        status=BoundaryStatus.CLEAR_FAIL,
        actions=(CorrectiveAction.NONE,),
        min_n_bootstrap=None,
        must_escalate=False,
        description=(
            "Layer comfortably fails threshold (ci_upper < threshold - margin). "
            "Monte Carlo error cannot plausibly flip this to a pass. "
            "Record result and continue."
        ),
    ),

    CorrectiveActionRule(
        status=BoundaryStatus.SOFT_BOUNDARY_PASS,
        actions=(
            CorrectiveAction.INCREASE_N_BOOTSTRAP,
            CorrectiveAction.ATTACH_MC_ERROR,
            CorrectiveAction.COMMIT_AS_UNSTABLE,
        ),
        min_n_bootstrap=BOUNDARY_N_BOOTSTRAP,
        must_escalate=False,
        description=(
            "Layer passes but ci_lower is within BOUNDARY_MARGIN of threshold. "
            "MC noise could flip this decision on another run. "
            "Increase n_bootstrap to 50,000, attach mc_error to KnowledgeRecord, "
            "and commit with is_boundary=True so historical_stddev accumulates. "
            "No council escalation required unless composite scores are close."
        ),
    ),

    CorrectiveActionRule(
        status=BoundaryStatus.SOFT_BOUNDARY_FAIL,
        actions=(
            CorrectiveAction.INCREASE_N_BOOTSTRAP,
            CorrectiveAction.ATTACH_MC_ERROR,
            CorrectiveAction.ESCALATE_TO_COUNCIL,
            CorrectiveAction.COMMIT_AS_UNSTABLE,
        ),
        min_n_bootstrap=BOUNDARY_N_BOOTSTRAP,
        must_escalate=True,
        description=(
            "Layer fails but ci_lower is within BOUNDARY_MARGIN of threshold. "
            "MC noise could flip this to a pass. "
            "Increase n_bootstrap, attach mc_error, escalate to review council "
            "with reason='boundary_instability'. Council decides whether the layer "
            "qualifies given the statistical uncertainty."
        ),
    ),

    CorrectiveActionRule(
        status=BoundaryStatus.HARD_BOUNDARY,
        actions=(
            CorrectiveAction.INCREASE_N_BOOTSTRAP,
            CorrectiveAction.ATTACH_MC_ERROR,
            CorrectiveAction.REQUIRE_MORE_TRIALS,
            CorrectiveAction.ESCALATE_TO_COUNCIL,
            CorrectiveAction.COMMIT_AS_UNSTABLE,
        ),
        min_n_bootstrap=BOUNDARY_N_BOOTSTRAP,
        must_escalate=True,
        description=(
            "ci_lower is within SIGMA_MULTIPLIER * mc_error_lower of threshold. "
            "The decision is inside the noise envelope of the estimator itself — "
            "it cannot be resolved by more bootstrap resamples alone. "
            "Increase n_bootstrap, attach mc_error, flag that more evaluation "
            "trials are needed, and escalate to review council with "
            "reason='boundary_instability'. Commit as statistically unstable "
            "so the knowledge layer deprioritises this layer via consistency score."
        ),
    ),
)

#: Lookup by BoundaryStatus for O(1) rule retrieval.
CORRECTIVE_ACTION_LOOKUP: dict[BoundaryStatus, CorrectiveActionRule] = {
    rule.status: rule for rule in CORRECTIVE_ACTION_ARRAY
}


# ---------------------------------------------------------------------------
# MCErrorEstimate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MCErrorEstimate:
    """
    Monte Carlo standard error of bootstrap CI bounds.

    Computed by repeating the bootstrap n_repeats times with independent
    seeds and taking the std dev of the resulting lower/upper bounds.

    Attributes:
        mc_error_lower:   Std dev of ci_lower across n_repeats runs.
        mc_error_upper:   Std dev of ci_upper across n_repeats runs.
        n_repeats:        Number of bootstrap repetitions used.
        n_bootstrap:      Resamples per repetition.
        is_high:          True if mc_error_lower > MC_ERROR_HIGH_WATERMARK.
                          When True, the MC error estimate itself may be
                          unreliable — recommend more evaluation trials.
        sigma_distance:   |ci_lower - threshold| / mc_error_lower.
                          How many sigmas the decision is from the boundary.
                          < SIGMA_MULTIPLIER (3.0) → HARD_BOUNDARY territory.
    """
    mc_error_lower: float
    mc_error_upper: float
    n_repeats:      int
    n_bootstrap:    int
    is_high:        bool
    sigma_distance: float

    def as_dict(self) -> dict:
        return {
            "mc_error_lower":  round(self.mc_error_lower, 6),
            "mc_error_upper":  round(self.mc_error_upper, 6),
            "n_repeats":       self.n_repeats,
            "n_bootstrap":     self.n_bootstrap,
            "is_high":         self.is_high,
            "sigma_distance":  round(self.sigma_distance, 4),
            "sigma_threshold": SIGMA_MULTIPLIER,
        }


# ---------------------------------------------------------------------------
# BoundaryClassification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BoundaryClassification:
    """
    Full classification of a CI result against the corrective action array.

    Attributes:
        ci_result:    The original CIResult being classified.
        mc_estimate:  MC error estimate. None if not computed (clear cases).
        status:       BoundaryStatus classification.
        rule:         The matching CorrectiveActionRule from the array.
        actions:      Shorthand alias for rule.actions.
        must_escalate:Shorthand alias for rule.must_escalate.
    """
    ci_result:     CIResult
    mc_estimate:   Optional[MCErrorEstimate]
    status:        BoundaryStatus
    rule:          CorrectiveActionRule

    @property
    def actions(self) -> tuple[CorrectiveAction, ...]:
        return self.rule.actions

    @property
    def must_escalate(self) -> bool:
        return self.rule.must_escalate

    def as_dict(self) -> dict:
        d = {
            "boundary_status":  self.status.value,
            "must_escalate":    self.must_escalate,
            "actions":          [a.value for a in self.actions],
            "rule_description": self.rule.description,
            "ci_lower":         self.ci_result.lower,
            "ci_upper":         self.ci_result.upper,
            "passes_threshold": self.ci_result.passes_threshold,
            "threshold":        GOVERNANCE_CI_THRESHOLD,
        }
        if self.mc_estimate:
            d["mc_error"] = self.mc_estimate.as_dict()
        return d


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def estimate_mc_error(
    passes:      int,
    fails:       int,
    ci_level:    float        = GOVERNANCE_CI_THRESHOLD,
    n_bootstrap: int          = BOUNDARY_N_BOOTSTRAP,
    n_repeats:   int          = MC_ERROR_N_REPEATS,
    rng_seed:    Optional[int] = None,
    ci_lower_ref: float       = 0.0,
) -> MCErrorEstimate:
    """
    Estimate Monte Carlo standard error of bootstrap CI bounds.

    Repeats the bootstrap n_repeats times with independent seeds derived
    from rng_seed (or random if None) and computes std dev of ci_lower
    and ci_upper across repetitions.

    Args:
        passes:       Number of passing trials.
        fails:        Number of failing trials.
        ci_level:     CI level. Defaults to GOVERNANCE_CI_THRESHOLD (0.98).
        n_bootstrap:  Resamples per repetition. Use BOUNDARY_N_BOOTSTRAP
                      (50,000) for boundary cases.
        n_repeats:    Number of independent repetitions. Default: 20.
        rng_seed:     Base seed. Each repetition uses rng_seed + i for
                      independence while remaining reproducible. None = random.
        ci_lower_ref: Reference ci_lower value for sigma_distance calculation.
                      Pass the ci_lower from the primary bootstrap_ci() call.

    Returns:
        MCErrorEstimate with mc_error_lower, mc_error_upper, sigma_distance.
    """
    lowers: list[float] = []
    uppers: list[float] = []

    for i in range(n_repeats):
        seed = (rng_seed + i) if rng_seed is not None else None
        result = bootstrap_ci(
            passes=passes,
            fails=fails,
            ci_level=ci_level,
            n_bootstrap=n_bootstrap,
            rng_seed=seed,
        )
        lowers.append(result.lower)
        uppers.append(result.upper)

    mc_error_lower = float(np.std(lowers))
    mc_error_upper = float(np.std(uppers))
    is_high        = mc_error_lower > MC_ERROR_HIGH_WATERMARK

    sigma_distance = (
        abs(ci_lower_ref - GOVERNANCE_CI_THRESHOLD) / mc_error_lower
        if mc_error_lower > 0 else float("inf")
    )

    return MCErrorEstimate(
        mc_error_lower=mc_error_lower,
        mc_error_upper=mc_error_upper,
        n_repeats=n_repeats,
        n_bootstrap=n_bootstrap,
        is_high=is_high,
        sigma_distance=sigma_distance,
    )


def classify_boundary(
    ci_result:   CIResult,
    rng_seed:    Optional[int] = None,
    compute_mc:  bool          = True,
) -> BoundaryClassification:
    """
    Classify a CIResult against the corrective action array.

    Fast-path for clear cases (no MC error computation needed).
    Computes MC error only when ci_lower is within BOUNDARY_MARGIN
    of GOVERNANCE_CI_THRESHOLD.

    Args:
        ci_result:  CIResult from bootstrap_ci().
        rng_seed:   Seed for MC error estimation. Passed to estimate_mc_error().
        compute_mc: If False, skip MC error estimation (useful in tests for speed).

    Returns:
        BoundaryClassification with status, rule, and optional mc_estimate.
    """
    lower     = ci_result.lower
    upper     = ci_result.upper
    threshold = GOVERNANCE_CI_THRESHOLD
    margin    = BOUNDARY_MARGIN

    # ── Fast-path: clear cases ────────────────────────────────────────
    if lower >= threshold + margin:
        return BoundaryClassification(
            ci_result=ci_result,
            mc_estimate=None,
            status=BoundaryStatus.CLEAR_PASS,
            rule=CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_PASS],
        )

    if upper < threshold - margin:
        return BoundaryClassification(
            ci_result=ci_result,
            mc_estimate=None,
            status=BoundaryStatus.CLEAR_FAIL,
            rule=CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_FAIL],
        )

    # ── Boundary region: compute MC error ─────────────────────────────
    mc = None
    if compute_mc:
        mc = estimate_mc_error(
            passes=ci_result.passes,
            fails=ci_result.fails,
            ci_level=ci_result.ci_level,
            n_bootstrap=BOUNDARY_N_BOOTSTRAP,
            rng_seed=rng_seed,
            ci_lower_ref=lower,
        )

    # ── Hard boundary: within SIGMA_MULTIPLIER * mc_error ────────────
    if mc is not None and mc.sigma_distance < SIGMA_MULTIPLIER:
        return BoundaryClassification(
            ci_result=ci_result,
            mc_estimate=mc,
            status=BoundaryStatus.HARD_BOUNDARY,
            rule=CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.HARD_BOUNDARY],
        )

    # ── Soft boundary: passes or fails within margin ──────────────────
    if lower >= threshold:
        status = BoundaryStatus.SOFT_BOUNDARY_PASS
    else:
        status = BoundaryStatus.SOFT_BOUNDARY_FAIL

    return BoundaryClassification(
        ci_result=ci_result,
        mc_estimate=mc,
        status=status,
        rule=CORRECTIVE_ACTION_LOOKUP[status],
    )


def adaptive_bootstrap_ci(
    passes:      int,
    fails:       int,
    ci_level:    float         = GOVERNANCE_CI_THRESHOLD,
    n_bootstrap: int           = DEFAULT_N_BOOTSTRAP,
    rng_seed:    Optional[int] = None,
    compute_mc:  bool          = True,
) -> tuple[CIResult, BoundaryClassification]:
    """
    Drop-in replacement for bootstrap_ci() with adaptive n and MC error.

    Runs a standard bootstrap_ci() first. If the result is in the boundary
    region, re-runs with BOUNDARY_N_BOOTSTRAP and computes MC error.
    Returns both the (possibly upgraded) CIResult and full BoundaryClassification.

    Args:
        passes:      Passing trial count.
        fails:       Failing trial count.
        ci_level:    CI level. Defaults to GOVERNANCE_CI_THRESHOLD.
        n_bootstrap: Initial resamples. Upgraded to BOUNDARY_N_BOOTSTRAP
                     automatically if a boundary case is detected.
        rng_seed:    Seed for reproducibility.
        compute_mc:  Whether to compute MC error for boundary cases.

    Returns:
        Tuple of (CIResult, BoundaryClassification).
        The CIResult is the highest-n_bootstrap result obtained.

    Example:
        >>> ci, classification = adaptive_bootstrap_ci(passes=490, fails=10)
        >>> classification.status
        BoundaryStatus.SOFT_BOUNDARY_FAIL
        >>> classification.must_escalate
        True
        >>> classification.actions
        (CorrectiveAction.INCREASE_N_BOOTSTRAP, CorrectiveAction.ATTACH_MC_ERROR,
         CorrectiveAction.ESCALATE_TO_COUNCIL, CorrectiveAction.COMMIT_AS_UNSTABLE)
    """
    # Initial run
    ci = bootstrap_ci(
        passes=passes,
        fails=fails,
        ci_level=ci_level,
        n_bootstrap=n_bootstrap,
        rng_seed=rng_seed,
    )

    # Fast-path classification (no MC needed for clear cases)
    classification = classify_boundary(ci, rng_seed=rng_seed, compute_mc=False)

    if classification.status in (BoundaryStatus.CLEAR_PASS, BoundaryStatus.CLEAR_FAIL):
        return ci, classification

    # Boundary case: upgrade n_bootstrap and re-run
    upgraded_n = max(n_bootstrap, BOUNDARY_N_BOOTSTRAP)
    if upgraded_n > n_bootstrap:
        ci = bootstrap_ci(
            passes=passes,
            fails=fails,
            ci_level=ci_level,
            n_bootstrap=upgraded_n,
            rng_seed=rng_seed,
        )

    # Full classification with MC error
    classification = classify_boundary(ci, rng_seed=rng_seed, compute_mc=compute_mc)
    return ci, classification
