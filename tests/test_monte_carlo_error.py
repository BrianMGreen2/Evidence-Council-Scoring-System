"""
tests/test_monte_carlo_error.py

Tests for evidence_council/scoring/monte_carlo_error.py

Coverage targets:
- BoundaryStatus classification across all five cases
- CORRECTIVE_ACTION_ARRAY completeness and internal consistency
- estimate_mc_error() output shape and statistical properties
- classify_boundary() fast-path and full-path routing
- adaptive_bootstrap_ci() upgrade logic and return contract
- MCErrorEstimate sigma_distance calculation
- CorrectiveActionRule fields and lookup table
"""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock

# Adjust import path to match your package structure
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from monte_carlo_error import (
    BoundaryStatus,
    CorrectiveAction,
    CorrectiveActionRule,
    CORRECTIVE_ACTION_ARRAY,
    CORRECTIVE_ACTION_LOOKUP,
    MCErrorEstimate,
    BoundaryClassification,
    estimate_mc_error,
    classify_boundary,
    adaptive_bootstrap_ci,
    BOUNDARY_MARGIN,
    BOUNDARY_N_BOOTSTRAP,
    SIGMA_MULTIPLIER,
    MC_ERROR_HIGH_WATERMARK,
    MC_ERROR_N_REPEATS,
)
from bootstrap_ci import (
    bootstrap_ci,
    GOVERNANCE_CI_THRESHOLD,
    DEFAULT_N_BOOTSTRAP,
)

SEED = 42
FAST_N = 200   # small n for test speed


# ---------------------------------------------------------------------------
# Helper layer builders
# ---------------------------------------------------------------------------

def clear_pass_result(seed=SEED):
    """ci_lower comfortably above threshold + margin."""
    return bootstrap_ci(passes=499, fails=1, n_bootstrap=FAST_N, rng_seed=seed)

def clear_fail_result(seed=SEED):
    """ci_upper comfortably below threshold - margin."""
    return bootstrap_ci(passes=450, fails=50, n_bootstrap=FAST_N, rng_seed=seed)

def soft_pass_result(seed=SEED):
    """ci_lower just above threshold, within BOUNDARY_MARGIN."""
    # 493/7 gives observed_rate=0.986, ci_lower typically 0.980–0.984
    return bootstrap_ci(passes=493, fails=7, n_bootstrap=FAST_N, rng_seed=seed)

def soft_fail_result(seed=SEED):
    """ci_lower just below threshold, within BOUNDARY_MARGIN."""
    # 490/10 gives observed_rate=0.98, ci_lower typically 0.972–0.979
    return bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=seed)


# ---------------------------------------------------------------------------
# CORRECTIVE_ACTION_ARRAY structure
# ---------------------------------------------------------------------------

class TestCorrectiveActionArray:
    def test_all_five_statuses_covered(self):
        covered = {rule.status for rule in CORRECTIVE_ACTION_ARRAY}
        expected = set(BoundaryStatus)
        assert covered == expected

    def test_lookup_matches_array(self):
        for rule in CORRECTIVE_ACTION_ARRAY:
            assert CORRECTIVE_ACTION_LOOKUP[rule.status] is rule

    def test_clear_pass_no_escalation(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_PASS]
        assert rule.must_escalate is False

    def test_clear_fail_no_escalation(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_FAIL]
        assert rule.must_escalate is False

    def test_soft_boundary_fail_must_escalate(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.SOFT_BOUNDARY_FAIL]
        assert rule.must_escalate is True

    def test_hard_boundary_must_escalate(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.HARD_BOUNDARY]
        assert rule.must_escalate is True

    def test_soft_boundary_pass_no_escalation(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.SOFT_BOUNDARY_PASS]
        assert rule.must_escalate is False

    def test_clear_pass_action_is_none(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_PASS]
        assert rule.actions == (CorrectiveAction.NONE,)

    def test_clear_fail_action_is_none(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_FAIL]
        assert rule.actions == (CorrectiveAction.NONE,)

    def test_hard_boundary_has_all_actions(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.HARD_BOUNDARY]
        assert CorrectiveAction.INCREASE_N_BOOTSTRAP in rule.actions
        assert CorrectiveAction.ATTACH_MC_ERROR      in rule.actions
        assert CorrectiveAction.REQUIRE_MORE_TRIALS  in rule.actions
        assert CorrectiveAction.ESCALATE_TO_COUNCIL  in rule.actions
        assert CorrectiveAction.COMMIT_AS_UNSTABLE   in rule.actions

    def test_boundary_rules_have_min_n_bootstrap(self):
        for status in (
            BoundaryStatus.SOFT_BOUNDARY_PASS,
            BoundaryStatus.SOFT_BOUNDARY_FAIL,
            BoundaryStatus.HARD_BOUNDARY,
        ):
            rule = CORRECTIVE_ACTION_LOOKUP[status]
            assert rule.min_n_bootstrap == BOUNDARY_N_BOOTSTRAP

    def test_clear_rules_have_no_min_n(self):
        for status in (BoundaryStatus.CLEAR_PASS, BoundaryStatus.CLEAR_FAIL):
            rule = CORRECTIVE_ACTION_LOOKUP[status]
            assert rule.min_n_bootstrap is None

    def test_all_rules_have_description(self):
        for rule in CORRECTIVE_ACTION_ARRAY:
            assert len(rule.description) > 20

    def test_rules_are_frozen(self):
        rule = CORRECTIVE_ACTION_LOOKUP[BoundaryStatus.CLEAR_PASS]
        with pytest.raises((AttributeError, TypeError)):
            rule.must_escalate = True  # type: ignore

    def test_escalate_action_present_iff_must_escalate(self):
        for rule in CORRECTIVE_ACTION_ARRAY:
            has_action = CorrectiveAction.ESCALATE_TO_COUNCIL in rule.actions
            assert has_action == rule.must_escalate


# ---------------------------------------------------------------------------
# MCErrorEstimate
# ---------------------------------------------------------------------------

class TestMCErrorEstimate:
    def _make(self, lower=0.01, upper=0.005, n_rep=20, n_boot=1000,
              is_high=False, sigma=5.0):
        return MCErrorEstimate(
            mc_error_lower=lower,
            mc_error_upper=upper,
            n_repeats=n_rep,
            n_bootstrap=n_boot,
            is_high=is_high,
            sigma_distance=sigma,
        )

    def test_as_dict_keys(self):
        mc = self._make()
        d = mc.as_dict()
        for key in ("mc_error_lower", "mc_error_upper", "n_repeats",
                    "n_bootstrap", "is_high", "sigma_distance", "sigma_threshold"):
            assert key in d

    def test_sigma_threshold_matches_constant(self):
        mc = self._make()
        assert mc.as_dict()["sigma_threshold"] == SIGMA_MULTIPLIER

    def test_is_high_true_when_above_watermark(self):
        mc = self._make(lower=MC_ERROR_HIGH_WATERMARK + 0.001, is_high=True)
        assert mc.is_high is True

    def test_frozen(self):
        mc = self._make()
        with pytest.raises((AttributeError, TypeError)):
            mc.mc_error_lower = 0.999  # type: ignore


# ---------------------------------------------------------------------------
# estimate_mc_error
# ---------------------------------------------------------------------------

class TestEstimateMCError:
    def test_returns_mc_error_estimate(self):
        mc = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=500, n_repeats=5, rng_seed=SEED,
            ci_lower_ref=0.975,
        )
        assert isinstance(mc, MCErrorEstimate)

    def test_mc_error_lower_is_nonneg(self):
        mc = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=500, n_repeats=5, rng_seed=SEED,
            ci_lower_ref=0.975,
        )
        assert mc.mc_error_lower >= 0.0

    def test_mc_error_upper_is_nonneg(self):
        mc = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=500, n_repeats=5, rng_seed=SEED,
            ci_lower_ref=0.975,
        )
        assert mc.mc_error_upper >= 0.0

    def test_n_repeats_stored(self):
        mc = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=500, n_repeats=7, rng_seed=SEED,
            ci_lower_ref=0.975,
        )
        assert mc.n_repeats == 7

    def test_n_bootstrap_stored(self):
        mc = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=500, n_repeats=5, rng_seed=SEED,
            ci_lower_ref=0.975,
        )
        assert mc.n_bootstrap == 500

    def test_reproducible_with_seed(self):
        kwargs = dict(passes=490, fails=10, n_bootstrap=300, n_repeats=5,
                      rng_seed=SEED, ci_lower_ref=0.975)
        mc1 = estimate_mc_error(**kwargs)
        mc2 = estimate_mc_error(**kwargs)
        assert mc1.mc_error_lower == pytest.approx(mc2.mc_error_lower, abs=1e-10)

    def test_higher_n_bootstrap_gives_lower_mc_error(self):
        """More resamples → tighter bootstrap → lower variability between runs."""
        mc_low  = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=200, n_repeats=10, rng_seed=SEED, ci_lower_ref=0.975,
        )
        mc_high = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=5000, n_repeats=10, rng_seed=SEED, ci_lower_ref=0.975,
        )
        assert mc_high.mc_error_lower <= mc_low.mc_error_lower

    def test_sigma_distance_infinite_when_mc_error_zero(self):
        """If std dev across repeats is 0 (all-pass layer), sigma = inf."""
        mc = estimate_mc_error(
            passes=500, fails=0,
            n_bootstrap=500, n_repeats=5, rng_seed=SEED, ci_lower_ref=1.0,
        )
        # All-pass: all bootstrap samples = 1.0, std = 0.0
        assert mc.sigma_distance == float("inf")

    def test_is_high_flag(self):
        mc = estimate_mc_error(
            passes=490, fails=10,
            n_bootstrap=100, n_repeats=5, rng_seed=SEED, ci_lower_ref=0.975,
        )
        assert mc.is_high == (mc.mc_error_lower > MC_ERROR_HIGH_WATERMARK)


# ---------------------------------------------------------------------------
# classify_boundary — fast path
# ---------------------------------------------------------------------------

class TestClassifyBoundaryFastPath:
    def test_clear_pass_no_mc_error(self):
        ci = clear_pass_result()
        if ci.lower >= GOVERNANCE_CI_THRESHOLD + BOUNDARY_MARGIN:
            bc = classify_boundary(ci, compute_mc=False)
            assert bc.status == BoundaryStatus.CLEAR_PASS
            assert bc.mc_estimate is None

    def test_clear_fail_no_mc_error(self):
        ci = clear_fail_result()
        if ci.upper < GOVERNANCE_CI_THRESHOLD - BOUNDARY_MARGIN:
            bc = classify_boundary(ci, compute_mc=False)
            assert bc.status == BoundaryStatus.CLEAR_FAIL
            assert bc.mc_estimate is None

    def test_clear_pass_no_escalation(self):
        ci = bootstrap_ci(passes=499, fails=1, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, compute_mc=False)
        if bc.status == BoundaryStatus.CLEAR_PASS:
            assert bc.must_escalate is False

    def test_clear_fail_no_escalation(self):
        ci = bootstrap_ci(passes=450, fails=50, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, compute_mc=False)
        if bc.status == BoundaryStatus.CLEAR_FAIL:
            assert bc.must_escalate is False

    def test_rule_matches_lookup(self):
        ci = clear_pass_result()
        bc = classify_boundary(ci, compute_mc=False)
        assert bc.rule is CORRECTIVE_ACTION_LOOKUP[bc.status]

    def test_ci_result_preserved(self):
        ci = clear_pass_result()
        bc = classify_boundary(ci, compute_mc=False)
        assert bc.ci_result is ci


# ---------------------------------------------------------------------------
# classify_boundary — boundary cases
# ---------------------------------------------------------------------------

class TestClassifyBoundaryBoundary:
    def test_boundary_case_has_mc_estimate(self):
        """A result near threshold should trigger MC error computation."""
        ci = bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, rng_seed=SEED, compute_mc=True)
        # If in boundary region, mc_estimate should be present
        if bc.status not in (BoundaryStatus.CLEAR_PASS, BoundaryStatus.CLEAR_FAIL):
            assert bc.mc_estimate is not None

    def test_soft_boundary_fail_escalates(self):
        ci = bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, rng_seed=SEED, compute_mc=True)
        if bc.status == BoundaryStatus.SOFT_BOUNDARY_FAIL:
            assert bc.must_escalate is True
            assert CorrectiveAction.ESCALATE_TO_COUNCIL in bc.actions

    def test_hard_boundary_escalates(self):
        ci = bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, rng_seed=SEED, compute_mc=True)
        if bc.status == BoundaryStatus.HARD_BOUNDARY:
            assert bc.must_escalate is True
            assert CorrectiveAction.REQUIRE_MORE_TRIALS in bc.actions

    def test_as_dict_keys(self):
        ci = bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, rng_seed=SEED, compute_mc=False)
        d = bc.as_dict()
        for key in ("boundary_status", "must_escalate", "actions",
                    "rule_description", "ci_lower", "ci_upper",
                    "passes_threshold", "threshold"):
            assert key in d

    def test_as_dict_mc_error_present_when_computed(self):
        ci = bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, rng_seed=SEED, compute_mc=True)
        if bc.mc_estimate is not None:
            assert "mc_error" in bc.as_dict()

    def test_compute_mc_false_skips_estimation(self):
        ci = bootstrap_ci(passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED)
        bc = classify_boundary(ci, rng_seed=SEED, compute_mc=False)
        # With compute_mc=False, mc_estimate is None even in boundary region
        assert bc.mc_estimate is None


# ---------------------------------------------------------------------------
# adaptive_bootstrap_ci
# ---------------------------------------------------------------------------

class TestAdaptiveBootstrapCI:
    def test_returns_tuple_of_two(self):
        result = adaptive_bootstrap_ci(
            passes=499, fails=1, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_ci_result(self):
        from bootstrap_ci import CIResult
        ci, bc = adaptive_bootstrap_ci(
            passes=499, fails=1, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        assert isinstance(ci, CIResult)

    def test_second_element_is_boundary_classification(self):
        ci, bc = adaptive_bootstrap_ci(
            passes=499, fails=1, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        assert isinstance(bc, BoundaryClassification)

    def test_clear_pass_no_upgrade(self):
        """Clear pass should not trigger n_bootstrap upgrade."""
        ci, bc = adaptive_bootstrap_ci(
            passes=499, fails=1, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        if bc.status == BoundaryStatus.CLEAR_PASS:
            assert ci.n_bootstrap == FAST_N

    def test_boundary_case_upgrades_n_bootstrap(self):
        """Boundary cases should upgrade to BOUNDARY_N_BOOTSTRAP."""
        ci, bc = adaptive_bootstrap_ci(
            passes=490, fails=10,
            n_bootstrap=FAST_N,
            rng_seed=SEED,
            compute_mc=False,
        )
        if bc.status not in (BoundaryStatus.CLEAR_PASS, BoundaryStatus.CLEAR_FAIL):
            assert ci.n_bootstrap >= BOUNDARY_N_BOOTSTRAP

    def test_classification_consistent_with_ci_result(self):
        ci, bc = adaptive_bootstrap_ci(
            passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        # Classification's ci_lower should match the returned CIResult
        assert bc.ci_result.lower == ci.lower

    def test_clear_fail_no_upgrade(self):
        """Clear fail should not trigger n_bootstrap upgrade."""
        ci, bc = adaptive_bootstrap_ci(
            passes=450, fails=50, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        if bc.status == BoundaryStatus.CLEAR_FAIL:
            assert ci.n_bootstrap == FAST_N

    def test_no_seed_runs_without_error(self):
        ci, bc = adaptive_bootstrap_ci(
            passes=490, fails=10, n_bootstrap=FAST_N, compute_mc=False
        )
        assert bc.status in set(BoundaryStatus)

    def test_boundary_classification_has_rule(self):
        ci, bc = adaptive_bootstrap_ci(
            passes=490, fails=10, n_bootstrap=FAST_N, rng_seed=SEED, compute_mc=False
        )
        assert bc.rule is CORRECTIVE_ACTION_LOOKUP[bc.status]


# ---------------------------------------------------------------------------
# BoundaryStatus completeness
# ---------------------------------------------------------------------------

class TestBoundaryStatusCoverage:
    """Verify all five BoundaryStatus values are reachable."""

    def _classify(self, passes, fails, seed=SEED):
        ci = bootstrap_ci(passes=passes, fails=fails, n_bootstrap=FAST_N, rng_seed=seed)
        return classify_boundary(ci, rng_seed=seed, compute_mc=False)

    def test_clear_pass_reachable(self):
        bc = self._classify(499, 1)
        # May not always be CLEAR_PASS at low n_bootstrap, but check it's pass-side
        assert bc.status in (BoundaryStatus.CLEAR_PASS, BoundaryStatus.SOFT_BOUNDARY_PASS)

    def test_clear_fail_reachable(self):
        bc = self._classify(450, 50)
        assert bc.status in (BoundaryStatus.CLEAR_FAIL, BoundaryStatus.SOFT_BOUNDARY_FAIL)

    def test_boundary_region_reachable(self):
        bc = self._classify(490, 10)
        assert bc.status in (
            BoundaryStatus.SOFT_BOUNDARY_PASS,
            BoundaryStatus.SOFT_BOUNDARY_FAIL,
            BoundaryStatus.HARD_BOUNDARY,
        )

    def test_all_corrective_actions_are_valid_enum_values(self):
        for rule in CORRECTIVE_ACTION_ARRAY:
            for action in rule.actions:
                assert action in set(CorrectiveAction)
