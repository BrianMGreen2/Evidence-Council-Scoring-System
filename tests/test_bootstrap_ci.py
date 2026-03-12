"""
tests/test_bootstrap_ci.py

Tests for evidence_council/scoring/bootstrap_ci.py

Coverage targets:
- Normal operation across a range of pass rates
- Degenerate inputs (zero trials, all pass, all fail)
- Warning generation
- Threshold behaviour at and around 0.98
- Reproducibility via rng_seed
- Convenience helpers: passes_governance_threshold, minimum_passes_for_threshold
- compare_layers ordering and independence
"""

import pytest
from bootstrap_ci import (
    bootstrap_ci,
    passes_governance_threshold,
    minimum_passes_for_threshold,
    compare_layers,
    CIResult,
    GOVERNANCE_CI_THRESHOLD,
    DEFAULT_N_BOOTSTRAP,
    _MIN_TRIALS_WARNING,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEED = 42
N = 1_000  # reduced n_bootstrap for speed in tests — stability checked separately


# ---------------------------------------------------------------------------
# CIResult properties
# ---------------------------------------------------------------------------

class TestCIResultProperties:
    def test_width(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r.width == pytest.approx(r.upper - r.lower, abs=1e-10)

    def test_margin_positive_when_passes(self):
        r = bootstrap_ci(passes=499, fails=1, n_bootstrap=N, rng_seed=SEED)
        assert r.margin > 0

    def test_margin_negative_when_fails(self):
        r = bootstrap_ci(passes=480, fails=20, n_bootstrap=N, rng_seed=SEED)
        assert r.margin < 0

    def test_as_dict_keys(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        d = r.as_dict()
        for key in ("ci_lower", "ci_upper", "observed_rate", "passes", "fails",
                    "total", "ci_level", "n_bootstrap", "passes_threshold",
                    "threshold", "margin", "width", "warnings"):
            assert key in d, f"Missing key: {key}"

    def test_as_dict_threshold_matches_constant(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r.as_dict()["threshold"] == GOVERNANCE_CI_THRESHOLD

    def test_frozen(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        with pytest.raises((AttributeError, TypeError)):
            r.lower = 0.5  # type: ignore


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_negative_passes_raises(self):
        with pytest.raises(ValueError, match="passes must be >= 0"):
            bootstrap_ci(passes=-1, fails=10)

    def test_negative_fails_raises(self):
        with pytest.raises(ValueError, match="fails must be >= 0"):
            bootstrap_ci(passes=10, fails=-1)

    def test_ci_level_zero_raises(self):
        with pytest.raises(ValueError, match="ci_level must be in"):
            bootstrap_ci(passes=10, fails=0, ci_level=0.0)

    def test_ci_level_one_raises(self):
        with pytest.raises(ValueError, match="ci_level must be in"):
            bootstrap_ci(passes=10, fails=0, ci_level=1.0)

    def test_ci_level_negative_raises(self):
        with pytest.raises(ValueError, match="ci_level must be in"):
            bootstrap_ci(passes=10, fails=0, ci_level=-0.5)


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------

class TestDegenerateInputs:
    def test_zero_trials_returns_zeros(self):
        r = bootstrap_ci(passes=0, fails=0, n_bootstrap=N, rng_seed=SEED)
        assert r.lower == 0.0
        assert r.upper == 0.0
        assert r.observed_rate == 0.0
        assert r.total == 0
        assert r.passes_threshold is False

    def test_zero_trials_produces_warning(self):
        r = bootstrap_ci(passes=0, fails=0, n_bootstrap=N, rng_seed=SEED)
        assert any("undefined" in w.lower() for w in r.warnings)

    def test_all_pass_produces_warning(self):
        r = bootstrap_ci(passes=100, fails=0, n_bootstrap=N, rng_seed=SEED)
        assert any("1.0" in w for w in r.warnings)

    def test_all_fail_produces_warning(self):
        r = bootstrap_ci(passes=0, fails=100, n_bootstrap=N, rng_seed=SEED)
        assert any("0.0" in w for w in r.warnings)

    def test_all_pass_upper_is_one(self):
        r = bootstrap_ci(passes=100, fails=0, n_bootstrap=N, rng_seed=SEED)
        assert r.upper == pytest.approx(1.0, abs=1e-6)

    def test_all_fail_lower_is_zero(self):
        r = bootstrap_ci(passes=0, fails=100, n_bootstrap=N, rng_seed=SEED)
        assert r.lower == pytest.approx(0.0, abs=1e-6)

    def test_small_sample_warning(self):
        r = bootstrap_ci(passes=15, fails=5, n_bootstrap=N, rng_seed=SEED)
        assert any(str(_MIN_TRIALS_WARNING) in w for w in r.warnings)

    def test_adequate_sample_no_small_warning(self):
        r = bootstrap_ci(passes=90, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert not any(str(_MIN_TRIALS_WARNING) in w for w in r.warnings)


# ---------------------------------------------------------------------------
# CI bounds behaviour
# ---------------------------------------------------------------------------

class TestCIBounds:
    def test_lower_leq_observed_rate(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r.lower <= r.observed_rate

    def test_upper_geq_observed_rate(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r.upper >= r.observed_rate

    def test_lower_leq_upper(self):
        for passes in [10, 50, 100, 490, 499]:
            r = bootstrap_ci(passes=passes, fails=500 - passes, n_bootstrap=N, rng_seed=SEED)
            assert r.lower <= r.upper

    def test_bounds_in_unit_interval(self):
        for passes in [0, 1, 250, 499, 500]:
            r = bootstrap_ci(passes=passes, fails=500 - passes, n_bootstrap=N, rng_seed=SEED)
            assert 0.0 <= r.lower <= 1.0
            assert 0.0 <= r.upper <= 1.0

    def test_wider_ci_at_lower_confidence(self):
        r98 = bootstrap_ci(passes=490, fails=10, ci_level=0.98, n_bootstrap=N, rng_seed=SEED)
        r95 = bootstrap_ci(passes=490, fails=10, ci_level=0.95, n_bootstrap=N, rng_seed=SEED)
        # 0.98 CI should be wider (lower lower-bound, higher upper-bound)
        assert r98.lower <= r95.lower
        assert r98.upper >= r95.upper

    def test_more_passes_gives_higher_lower_bound(self):
        r_low  = bootstrap_ci(passes=450, fails=50, n_bootstrap=N, rng_seed=SEED)
        r_high = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r_high.lower > r_low.lower

    def test_larger_sample_gives_narrower_interval(self):
        r_small = bootstrap_ci(passes=49,  fails=1,  n_bootstrap=N, rng_seed=SEED)
        r_large = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r_large.width < r_small.width


# ---------------------------------------------------------------------------
# Governance threshold behaviour
# ---------------------------------------------------------------------------

class TestGovernanceThreshold:
    def test_clear_pass(self):
        """High pass rate with large sample should clear 0.98."""
        r = bootstrap_ci(passes=499, fails=1, n_bootstrap=N, rng_seed=SEED)
        assert r.passes_threshold is True

    def test_clear_fail(self):
        """Low pass rate should not clear 0.98."""
        r = bootstrap_ci(passes=470, fails=30, n_bootstrap=N, rng_seed=SEED)
        assert r.passes_threshold is False

    def test_passes_threshold_consistent_with_lower(self):
        """passes_threshold must always agree with lower >= GOVERNANCE_CI_THRESHOLD."""
        for passes in [450, 470, 490, 495, 498, 499, 500]:
            r = bootstrap_ci(passes=passes, fails=500 - passes, n_bootstrap=N, rng_seed=SEED)
            assert r.passes_threshold == (r.lower >= GOVERNANCE_CI_THRESHOLD)

    def test_observed_rate_stored_correctly(self):
        r = bootstrap_ci(passes=400, fails=100, n_bootstrap=N, rng_seed=SEED)
        assert r.observed_rate == pytest.approx(0.80, abs=1e-10)

    def test_total_stored_correctly(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r.total == 500
        assert r.passes == 490
        assert r.fails == 10


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_same_seed_same_result(self):
        r1 = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        r2 = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=SEED)
        assert r1.lower == r2.lower
        assert r1.upper == r2.upper

    def test_different_seed_different_result(self):
        r1 = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=1)
        r2 = bootstrap_ci(passes=490, fails=10, n_bootstrap=N, rng_seed=2)
        # Not guaranteed to differ but overwhelmingly likely at n=1000
        assert r1.lower != r2.lower or r1.upper != r2.upper

    def test_no_seed_runs_without_error(self):
        r = bootstrap_ci(passes=490, fails=10, n_bootstrap=N)
        assert isinstance(r, CIResult)


# ---------------------------------------------------------------------------
# passes_governance_threshold convenience wrapper
# ---------------------------------------------------------------------------

class TestPassesGovernanceThreshold:
    def test_returns_true_for_strong_layer(self):
        assert passes_governance_threshold(passes=499, fails=1, n_bootstrap=N, rng_seed=SEED) is True

    def test_returns_false_for_weak_layer(self):
        assert passes_governance_threshold(passes=470, fails=30, n_bootstrap=N, rng_seed=SEED) is False

    def test_agrees_with_bootstrap_ci(self):
        for passes in [450, 480, 495, 499]:
            expected = bootstrap_ci(passes=passes, fails=500 - passes, n_bootstrap=N, rng_seed=SEED).passes_threshold
            actual   = passes_governance_threshold(passes=passes, fails=500 - passes, n_bootstrap=N, rng_seed=SEED)
            assert actual == expected


# ---------------------------------------------------------------------------
# minimum_passes_for_threshold
# ---------------------------------------------------------------------------

class TestMinimumPassesForThreshold:
    def test_returns_int(self):
        result = minimum_passes_for_threshold(total=500, n_bootstrap=N, rng_seed=SEED)
        assert isinstance(result, int)

    def test_result_passes_threshold(self):
        total  = 500
        min_p  = minimum_passes_for_threshold(total=total, n_bootstrap=N, rng_seed=SEED)
        assert min_p is not None
        r = bootstrap_ci(passes=min_p, fails=total - min_p, n_bootstrap=N, rng_seed=SEED)
        assert r.passes_threshold is True

    def test_one_below_minimum_fails(self):
        total = 500
        min_p = minimum_passes_for_threshold(total=total, n_bootstrap=N, rng_seed=SEED)
        assert min_p is not None
        if min_p > 0:
            r = bootstrap_ci(passes=min_p - 1, fails=total - (min_p - 1), n_bootstrap=N, rng_seed=SEED)
            assert r.passes_threshold is False

    def test_zero_total_returns_none(self):
        assert minimum_passes_for_threshold(total=0, n_bootstrap=N, rng_seed=SEED) is None

    def test_larger_total_requires_fewer_proportional_passes(self):
        """Larger samples need a lower pass rate to clear the threshold."""
        min_100  = minimum_passes_for_threshold(total=100,  n_bootstrap=N, rng_seed=SEED)
        min_1000 = minimum_passes_for_threshold(total=1000, n_bootstrap=N, rng_seed=SEED)
        assert min_100 is not None and min_1000 is not None
        rate_100  = min_100  / 100
        rate_1000 = min_1000 / 1000
        assert rate_1000 <= rate_100


# ---------------------------------------------------------------------------
# compare_layers
# ---------------------------------------------------------------------------

class TestCompareLayers:
    LAYERS = [
        {"name": "layer_a", "passes": 497, "fails": 3},
        {"name": "layer_b", "passes": 490, "fails": 10},
        {"name": "layer_c", "passes": 499, "fails": 1},
    ]

    def test_sorted_descending_by_ci_lower(self):
        results = compare_layers(self.LAYERS, n_bootstrap=N, rng_seed=SEED)
        lowers = [r["ci_lower"] for r in results]
        assert lowers == sorted(lowers, reverse=True)

    def test_all_layers_present(self):
        results = compare_layers(self.LAYERS, n_bootstrap=N, rng_seed=SEED)
        names = {r["name"] for r in results}
        assert names == {"layer_a", "layer_b", "layer_c"}

    def test_ci_result_attached(self):
        results = compare_layers(self.LAYERS, n_bootstrap=N, rng_seed=SEED)
        for r in results:
            assert isinstance(r["ci_result"], CIResult)

    def test_inlined_fields_match_ci_result(self):
        results = compare_layers(self.LAYERS, n_bootstrap=N, rng_seed=SEED)
        for r in results:
            assert r["ci_lower"]  == r["ci_result"].lower
            assert r["ci_upper"]  == r["ci_result"].upper
            assert r["pass_rate"] == r["ci_result"].observed_rate

    def test_seeded_independence(self):
        """Each layer should get a different seed — results should be reproducible."""
        r1 = compare_layers(self.LAYERS, n_bootstrap=N, rng_seed=SEED)
        r2 = compare_layers(self.LAYERS, n_bootstrap=N, rng_seed=SEED)
        for a, b in zip(r1, r2):
            assert a["ci_lower"] == b["ci_lower"]

    def test_empty_list(self):
        results = compare_layers([], n_bootstrap=N, rng_seed=SEED)
        assert results == []

    def test_single_layer(self):
        results = compare_layers(
            [{"name": "only", "passes": 490, "fails": 10}],
            n_bootstrap=N, rng_seed=SEED,
        )
        assert len(results) == 1
        assert results[0]["name"] == "only"
