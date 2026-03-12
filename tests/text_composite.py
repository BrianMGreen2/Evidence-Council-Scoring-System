"""
tests/test_composite.py

Tests for evidence_council/scoring/composite.py

Coverage targets:
- ScoringConfig construction and validation
- All three built-in profiles
- compute_composite_score across component combinations
- consistency_component and approval_penalty functions
- rank_by_composite ordering and mutation behaviour
- is_close_call detection
- Serialisation via as_dict
"""

import pytest
from composite import (
    ScoringConfig,
    compute_composite_score,
    consistency_component,
    approval_penalty,
    rank_by_composite,
    is_close_call,
    _CONSISTENCY_REF_STDDEV,
    _APPROVAL_PENALTY_MAX,
)


# ---------------------------------------------------------------------------
# ScoringConfig construction
# ---------------------------------------------------------------------------

class TestScoringConfigConstruction:
    def test_valid_config(self):
        cfg = ScoringConfig(
            weight_ci_lower=0.45,
            weight_pass_rate=0.25,
            weight_cost=0.20,
            weight_consistency=0.10,
        )
        assert cfg.weight_ci_lower == 0.45

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            ScoringConfig(
                weight_ci_lower=0.40,
                weight_pass_rate=0.25,
                weight_cost=0.20,
                weight_consistency=0.10,  # total = 0.95
            )

    def test_negative_weight_raises(self):
        with pytest.raises(ValueError):
            ScoringConfig(
                weight_ci_lower=0.55,
                weight_pass_rate=0.25,
                weight_cost=0.20,
                weight_consistency=-0.00,  # triggers negative check via rounding edge
            )

    def test_weight_above_one_raises(self):
        with pytest.raises(ValueError):
            ScoringConfig(
                weight_ci_lower=1.10,
                weight_pass_rate=0.00,
                weight_cost=0.00,
                weight_consistency=-0.10,
            )

    def test_negative_close_call_margin_raises(self):
        with pytest.raises(ValueError, match="close_call_margin"):
            ScoringConfig(
                weight_ci_lower=0.45,
                weight_pass_rate=0.25,
                weight_cost=0.20,
                weight_consistency=0.10,
                close_call_margin=-0.01,
            )

    def test_frozen(self):
        cfg = ScoringConfig.default()
        with pytest.raises((AttributeError, TypeError)):
            cfg.weight_ci_lower = 0.99  # type: ignore

    def test_label_default(self):
        cfg = ScoringConfig(
            weight_ci_lower=0.45,
            weight_pass_rate=0.25,
            weight_cost=0.20,
            weight_consistency=0.10,
        )
        assert cfg.label == "custom"


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

class TestBuiltInProfiles:
    def _check_sums_to_one(self, cfg: ScoringConfig) -> None:
        total = (
            cfg.weight_ci_lower
            + cfg.weight_pass_rate
            + cfg.weight_cost
            + cfg.weight_consistency
        )
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_default_sums_to_one(self):
        self._check_sums_to_one(ScoringConfig.default())

    def test_healthcare_sums_to_one(self):
        self._check_sums_to_one(ScoringConfig.healthcare())

    def test_cost_sensitive_sums_to_one(self):
        self._check_sums_to_one(ScoringConfig.cost_sensitive())

    def test_default_label(self):
        assert ScoringConfig.default().label == "default"

    def test_healthcare_label(self):
        assert ScoringConfig.healthcare().label == "healthcare"

    def test_cost_sensitive_label(self):
        assert ScoringConfig.cost_sensitive().label == "cost_sensitive"

    def test_healthcare_lower_cost_weight_than_default(self):
        assert ScoringConfig.healthcare().weight_cost < ScoringConfig.default().weight_cost

    def test_healthcare_higher_consistency_than_default(self):
        assert ScoringConfig.healthcare().weight_consistency > ScoringConfig.default().weight_consistency

    def test_cost_sensitive_highest_cost_weight(self):
        assert (
            ScoringConfig.cost_sensitive().weight_cost
            > ScoringConfig.default().weight_cost
            > ScoringConfig.healthcare().weight_cost
        )

    def test_as_dict_keys(self):
        d = ScoringConfig.default().as_dict()
        for key in ("profile", "weight_ci_lower", "weight_pass_rate",
                    "weight_cost", "weight_consistency", "close_call_margin"):
            assert key in d

    def test_as_dict_profile_matches_label(self):
        cfg = ScoringConfig.healthcare()
        assert cfg.as_dict()["profile"] == "healthcare"


# ---------------------------------------------------------------------------
# consistency_component
# ---------------------------------------------------------------------------

class TestConsistencyComponent:
    def test_zero_stddev_returns_one(self):
        assert consistency_component(0.0) == pytest.approx(1.0)

    def test_ref_stddev_returns_zero(self):
        assert consistency_component(_CONSISTENCY_REF_STDDEV) == pytest.approx(0.0)

    def test_above_ref_clamped_to_zero(self):
        assert consistency_component(_CONSISTENCY_REF_STDDEV * 2) == 0.0

    def test_monotonically_decreasing(self):
        values = [consistency_component(s) for s in [0.0, 0.05, 0.10, 0.15, 0.20]]
        assert values == sorted(values, reverse=True)

    def test_midpoint(self):
        mid = _CONSISTENCY_REF_STDDEV / 2
        assert consistency_component(mid) == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# approval_penalty
# ---------------------------------------------------------------------------

class TestApprovalPenalty:
    def test_full_approval_no_penalty(self):
        assert approval_penalty(1.0) == pytest.approx(1.0)

    def test_zero_approval_max_penalty(self):
        expected = 1.0 - _APPROVAL_PENALTY_MAX
        assert approval_penalty(0.0) == pytest.approx(expected)

    def test_monotonically_increasing(self):
        values = [approval_penalty(r) for r in [0.0, 0.25, 0.5, 0.75, 1.0]]
        assert values == sorted(values)

    def test_midpoint(self):
        # approval_rate=0.5 → penalty = 1 - (0.30 * 0.5) = 0.85
        assert approval_penalty(0.5) == pytest.approx(1.0 - _APPROVAL_PENALTY_MAX * 0.5)


# ---------------------------------------------------------------------------
# compute_composite_score
# ---------------------------------------------------------------------------

class TestComputeCompositeScore:
    def test_perfect_layer_scores_high(self):
        score = compute_composite_score(
            ci_lower=0.99, pass_rate=1.0, cost_score=0.0,
            historical_stddev=0.0, reviewer_approval=1.0,
        )
        assert score > 0.90

    def test_poor_layer_scores_low(self):
        score = compute_composite_score(
            ci_lower=0.50, pass_rate=0.60, cost_score=1.0,
            historical_stddev=0.20, reviewer_approval=0.0,
        )
        assert score < 0.50

    def test_higher_ci_lower_gives_higher_score(self):
        s_high = compute_composite_score(ci_lower=0.99, pass_rate=0.98, cost_score=0.3)
        s_low  = compute_composite_score(ci_lower=0.95, pass_rate=0.98, cost_score=0.3)
        assert s_high > s_low

    def test_lower_cost_gives_higher_score(self):
        s_cheap     = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.1)
        s_expensive = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.9)
        assert s_cheap > s_expensive

    def test_lower_stddev_gives_higher_score(self):
        s_consistent   = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.3, historical_stddev=0.0)
        s_inconsistent = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.3, historical_stddev=0.14)
        assert s_consistent > s_inconsistent

    def test_approval_penalty_applied(self):
        s_approved = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.3, reviewer_approval=1.0)
        s_rejected = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.3, reviewer_approval=0.0)
        assert s_approved > s_rejected

    def test_custom_config_changes_score(self):
        default_score     = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.9, config=ScoringConfig.default())
        healthcare_score  = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.9, config=ScoringConfig.healthcare())
        cost_score_val    = compute_composite_score(ci_lower=0.98, pass_rate=0.99, cost_score=0.9, config=ScoringConfig.cost_sensitive())
        # Cost-sensitive should penalise high cost more than default
        assert cost_score_val < default_score

    def test_defaults_use_default_profile(self):
        score_explicit = compute_composite_score(
            ci_lower=0.98, pass_rate=0.99, cost_score=0.3,
            config=ScoringConfig.default(),
        )
        score_implicit = compute_composite_score(
            ci_lower=0.98, pass_rate=0.99, cost_score=0.3,
        )
        assert score_explicit == pytest.approx(score_implicit, abs=1e-10)


# ---------------------------------------------------------------------------
# rank_by_composite
# ---------------------------------------------------------------------------

class TestRankByComposite:
    BASE_CANDIDATES = [
        {"name": "layer_a", "ci_lower": 0.985, "pass_rate": 0.992, "cost_score": 0.3},
        {"name": "layer_b", "ci_lower": 0.981, "pass_rate": 0.988, "cost_score": 0.1},
        {"name": "layer_c", "ci_lower": 0.990, "pass_rate": 0.995, "cost_score": 0.7},
    ]

    def _fresh(self):
        import copy
        return copy.deepcopy(self.BASE_CANDIDATES)

    def test_sorted_descending(self):
        ranked = rank_by_composite(self._fresh())
        scores = [r["composite_score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_composite_score_added(self):
        ranked = rank_by_composite(self._fresh())
        for r in ranked:
            assert "composite_score" in r
            assert isinstance(r["composite_score"], float)

    def test_scoring_profile_added(self):
        ranked = rank_by_composite(self._fresh())
        for r in ranked:
            assert r["scoring_profile"] == "default"

    def test_custom_profile_label(self):
        ranked = rank_by_composite(self._fresh(), config=ScoringConfig.healthcare())
        for r in ranked:
            assert r["scoring_profile"] == "healthcare"

    def test_all_candidates_present(self):
        ranked = rank_by_composite(self._fresh())
        assert len(ranked) == 3

    def test_mutates_in_place(self):
        candidates = self._fresh()
        result = rank_by_composite(candidates)
        assert result is candidates  # same list object

    def test_optional_fields_default(self):
        """historical_stddev and reviewer_approval should default gracefully."""
        candidates = [{"name": "x", "ci_lower": 0.982, "pass_rate": 0.990, "cost_score": 0.4}]
        ranked = rank_by_composite(candidates)
        assert ranked[0]["composite_score"] > 0

    def test_empty_list(self):
        assert rank_by_composite([]) == []


# ---------------------------------------------------------------------------
# is_close_call
# ---------------------------------------------------------------------------

class TestIsCloseCall:
    def test_close_scores_returns_true(self):
        ranked = [
            {"composite_score": 0.880},
            {"composite_score": 0.875},  # gap = 0.005 < 0.03
        ]
        assert is_close_call(ranked) is True

    def test_distant_scores_returns_false(self):
        ranked = [
            {"composite_score": 0.900},
            {"composite_score": 0.860},  # gap = 0.04 > 0.03
        ]
        assert is_close_call(ranked) is False

    def test_single_candidate_returns_false(self):
        ranked = [{"composite_score": 0.880}]
        assert is_close_call(ranked) is False

    def test_empty_returns_false(self):
        assert is_close_call([]) is False

    def test_exactly_at_margin_returns_false(self):
        """Gap == margin is not a close call (strict less-than)."""
        cfg = ScoringConfig.default()
        ranked = [
            {"composite_score": 0.900},
            {"composite_score": 0.900 - cfg.close_call_margin},
        ]
        assert is_close_call(ranked, config=cfg) is False

    def test_custom_margin(self):
        cfg = ScoringConfig(
            weight_ci_lower=0.45,
            weight_pass_rate=0.25,
            weight_cost=0.20,
            weight_consistency=0.10,
            close_call_margin=0.10,  # wider margin
        )
        ranked = [
            {"composite_score": 0.900},
            {"composite_score": 0.865},  # gap = 0.035 < 0.10 → close call
        ]
        assert is_close_call(ranked, config=cfg) is True

    def test_uses_top_two_only(self):
        """A large gap between 2nd and 3rd should not affect close call detection."""
        ranked = [
            {"composite_score": 0.880},
            {"composite_score": 0.876},  # gap = 0.004 → close call
            {"composite_score": 0.700},  # irrelevant
        ]
        assert is_close_call(ranked) is True
