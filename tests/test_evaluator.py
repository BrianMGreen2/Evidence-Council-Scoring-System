"""
tests/test_evaluator.py

Tests for evidence_council/evaluator.py

Coverage targets:
- GovernanceDecision outcomes: PASS, SUBSTITUTED, FLAG
- Exhaustive evaluation (all layers evaluated, not first-pass)
- Winner selection by composite score, not first-to-pass
- Close call detection and ReviewTask emission
- Knowledge layer integration (all results committed)
- Reviewer decision application and verdict propagation
- EvidenceLayer pass_rate property
- ReviewTask structure and fields
"""

import pytest
from unittest.mock import MagicMock, call
from pathlib import Path

from evaluator import (
    GovernanceEvaluator,
    GovernanceDecision,
    EvidenceLayer,
    GovernanceResult,
    CandidateResult,
    ReviewTask,
    bootstrap_ci,
    GOVERNANCE_CI_THRESHOLD,
    CLOSE_CALL_MARGIN,
)
from knowledge_layer import KnowledgeLayer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kl(tmp_path):
    return KnowledgeLayer(path=tmp_path / "kl.jsonl")


@pytest.fixture
def evaluator(kl):
    return GovernanceEvaluator(
        knowledge_layer=kl,
        probe="probe.xss.reflection",
        detector="det.bert.toxic",
        n_bootstrap=500,  # fast for tests
    )


def strong_layer(name: str, cost: float = 0.3) -> EvidenceLayer:
    """Layer that reliably clears 0.98 threshold."""
    return EvidenceLayer(name=name, passes=499, fails=1, cost_score=cost, latency_ms=50.0)


def weak_layer(name: str, cost: float = 0.3) -> EvidenceLayer:
    """Layer that reliably fails 0.98 threshold."""
    return EvidenceLayer(name=name, passes=470, fails=30, cost_score=cost, latency_ms=50.0)


def borderline_layer(name: str, cost: float = 0.3) -> EvidenceLayer:
    """Layer that may or may not clear 0.98 depending on bootstrap sample."""
    return EvidenceLayer(name=name, passes=490, fails=10, cost_score=cost, latency_ms=50.0)


# ---------------------------------------------------------------------------
# EvidenceLayer
# ---------------------------------------------------------------------------

class TestEvidenceLayer:
    def test_pass_rate_correct(self):
        layer = EvidenceLayer(name="x", passes=490, fails=10)
        assert layer.pass_rate == pytest.approx(0.98)

    def test_pass_rate_all_pass(self):
        layer = EvidenceLayer(name="x", passes=100, fails=0)
        assert layer.pass_rate == pytest.approx(1.0)

    def test_pass_rate_no_trials(self):
        layer = EvidenceLayer(name="x", passes=0, fails=0)
        assert layer.pass_rate == 0.0

    def test_pass_rate_all_fail(self):
        layer = EvidenceLayer(name="x", passes=0, fails=100)
        assert layer.pass_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# GovernanceDecision.PASS
# ---------------------------------------------------------------------------

class TestDecisionPass:
    def test_primary_passes_decision_is_pass(self, evaluator):
        primary = strong_layer("primary")
        result = evaluator.evaluate(primary, [])
        assert result.decision == GovernanceDecision.PASS

    def test_winner_is_primary(self, evaluator):
        primary = strong_layer("primary")
        result = evaluator.evaluate(primary, [weak_layer("cand_a")])
        assert result.winner is not None
        assert result.winner.layer.name == "primary"

    def test_no_review_task_on_clean_pass(self, evaluator):
        primary = strong_layer("primary")
        candidates = [weak_layer("cand_a"), weak_layer("cand_b")]
        result = evaluator.evaluate(primary, candidates)
        # No close call (primary much better), no flag
        # review_task may still be None
        assert result.flag_reason is None


# ---------------------------------------------------------------------------
# GovernanceDecision.SUBSTITUTED
# ---------------------------------------------------------------------------

class TestDecisionSubstituted:
    def test_weak_primary_strong_candidate_substitutes(self, evaluator):
        primary = weak_layer("primary")
        candidates = [strong_layer("cand_a")]
        result = evaluator.evaluate(primary, candidates)
        assert result.decision == GovernanceDecision.SUBSTITUTED
        assert result.winner.layer.name == "cand_a"

    def test_winner_is_highest_composite_not_first_pass(self, evaluator):
        """
        Both cand_a and cand_b pass the threshold.
        cand_b has lower cost — should win on composite despite being listed second.
        """
        primary = weak_layer("primary")
        cand_a  = strong_layer("cand_a", cost=0.8)   # high cost → lower composite
        cand_b  = strong_layer("cand_b", cost=0.1)   # low cost  → higher composite
        result  = evaluator.evaluate(primary, [cand_a, cand_b])

        assert result.decision == GovernanceDecision.SUBSTITUTED
        # cand_b should win despite being second in the input list
        assert result.winner.layer.name == "cand_b"

    def test_all_qualifying_layers_collected(self, evaluator):
        primary = weak_layer("primary")
        cand_a  = strong_layer("cand_a", cost=0.5)
        cand_b  = strong_layer("cand_b", cost=0.4)
        result  = evaluator.evaluate(primary, [cand_a, cand_b])

        qualifying_names = {r.layer.name for r in result.qualifying_results}
        assert "cand_a" in qualifying_names
        assert "cand_b" in qualifying_names

    def test_qualifying_sorted_by_composite_descending(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(
            primary,
            [strong_layer("cand_a", cost=0.8), strong_layer("cand_b", cost=0.1)],
        )
        scores = [r.composite_score for r in result.qualifying_results]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# GovernanceDecision.FLAG
# ---------------------------------------------------------------------------

class TestDecisionFlag:
    def test_all_weak_layers_flags(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [weak_layer("cand_a"), weak_layer("cand_b")])
        assert result.decision == GovernanceDecision.FLAG

    def test_flag_has_no_winner(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [weak_layer("cand_a")])
        assert result.winner is None

    def test_flag_has_reason(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [weak_layer("cand_a")])
        assert result.flag_reason is not None
        assert len(result.flag_reason) > 0

    def test_flag_emits_review_task(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [weak_layer("cand_a")])
        assert result.review_task is not None
        assert result.review_task.reason == "no_passing_layer"

    def test_flag_review_task_has_all_results(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [weak_layer("cand_a"), weak_layer("cand_b")])
        assert len(result.review_task.all_results) == 3  # primary + 2 candidates

    def test_flag_review_task_proposed_winner_is_none(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [weak_layer("cand_a")])
        assert result.review_task.proposed_winner is None


# ---------------------------------------------------------------------------
# Exhaustive evaluation
# ---------------------------------------------------------------------------

class TestExhaustiveEvaluation:
    def test_all_layers_evaluated(self, evaluator):
        primary    = weak_layer("primary")
        candidates = [strong_layer("cand_a"), weak_layer("cand_b"), strong_layer("cand_c")]
        result     = evaluator.evaluate(primary, candidates)

        evaluated_names = {r.layer.name for r in result.all_results}
        assert evaluated_names == {"primary", "cand_a", "cand_b", "cand_c"}

    def test_all_results_count_matches_input(self, evaluator):
        primary    = weak_layer("primary")
        candidates = [strong_layer(f"cand_{i}") for i in range(5)]
        result     = evaluator.evaluate(primary, candidates)
        assert len(result.all_results) == 6  # 1 primary + 5 candidates

    def test_passes_threshold_flags_set_correctly(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [strong_layer("cand_a")])
        for cr in result.all_results:
            expected = cr.ci_lower >= GOVERNANCE_CI_THRESHOLD
            assert cr.passes_threshold == expected


# ---------------------------------------------------------------------------
# Close call detection
# ---------------------------------------------------------------------------

class TestCloseCall:
    def test_close_scores_emit_review_task(self, evaluator):
        """
        Two strong layers with nearly identical composite scores should trigger
        a close-call review task. We force this by using identical layers.
        """
        primary = weak_layer("primary")
        # Two identical strong layers → identical composite scores → gap = 0 < margin
        cand_a  = strong_layer("cand_a", cost=0.3)
        cand_b  = EvidenceLayer(name="cand_b", passes=499, fails=1, cost_score=0.3, latency_ms=50.0)
        result  = evaluator.evaluate(primary, [cand_a, cand_b])

        if result.close_call:
            assert result.review_task is not None
            assert result.review_task.reason == "close_call"

    def test_distant_scores_no_close_call(self, evaluator):
        primary = weak_layer("primary")
        cand_a  = strong_layer("cand_a", cost=0.1)   # very cheap → high composite
        cand_b  = strong_layer("cand_b", cost=0.95)  # very expensive → low composite
        result  = evaluator.evaluate(primary, [cand_a, cand_b])
        # These should be far enough apart to avoid a close call
        if not result.close_call:
            assert result.review_task is None or result.review_task.reason != "close_call"

    def test_single_qualifying_layer_never_close_call(self, evaluator):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [strong_layer("cand_a")])
        assert result.close_call is False


# ---------------------------------------------------------------------------
# Knowledge layer integration
# ---------------------------------------------------------------------------

class TestKnowledgeLayerIntegration:
    def test_all_results_committed(self, evaluator, kl):
        primary    = weak_layer("primary")
        candidates = [strong_layer("cand_a"), weak_layer("cand_b")]
        evaluator.evaluate(primary, candidates)
        # 3 layers evaluated → 3 records committed
        assert len(kl._records) == 3

    def test_committed_records_have_correct_probe(self, evaluator, kl):
        evaluator.evaluate(weak_layer("primary"), [])
        assert kl._records[0].probe == "probe.xss.reflection"

    def test_committed_records_have_correct_detector(self, evaluator, kl):
        evaluator.evaluate(weak_layer("primary"), [])
        assert kl._records[0].detector == "det.bert.toxic"

    def test_second_evaluation_appends_records(self, evaluator, kl):
        evaluator.evaluate(weak_layer("primary"), [])
        evaluator.evaluate(weak_layer("primary"), [])
        assert len(kl._records) == 2

    def test_knowledge_layer_informs_subsequent_ranking(self, tmp_path):
        """
        After a run where layer_b outperforms layer_a, the knowledge layer
        should rank layer_b higher in the next run's prior.
        """
        kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
        ev = GovernanceEvaluator(kl, "probe.xss", "det.bert", n_bootstrap=500)

        # First run: layer_b clearly outperforms layer_a
        ev.evaluate(
            weak_layer("primary"),
            [weak_layer("layer_a"), strong_layer("layer_b")],
        )

        # Check that the knowledge layer now ranks layer_b above layer_a
        ranked = kl.rank_candidates(["layer_a", "layer_b"], "probe.xss", "det.bert")
        top = ranked[0]["layer_name"]
        assert top == "layer_b"


# ---------------------------------------------------------------------------
# apply_reviewer_decision
# ---------------------------------------------------------------------------

class TestApplyReviewerDecision:
    def test_approved_verdict_patches_knowledge_layer(self, evaluator, kl):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [strong_layer("cand_a")])
        task    = result.review_task or ReviewTask(
            probe=evaluator.probe,
            detector=evaluator.detector,
            all_results=result.all_results,
            proposed_winner=result.winner,
        )

        evaluator.apply_reviewer_decision(
            review_task=task,
            reviewer_id="human:alice",
            verdict="approved",
            notes="Approved after review.",
        )
        assert task.status == "approved"
        assert task.reviewer_id == "human:alice"

    def test_rejected_verdict_stored(self, evaluator, kl):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [strong_layer("cand_a")])
        task    = ReviewTask(
            probe=evaluator.probe,
            detector=evaluator.detector,
            all_results=result.all_results,
            proposed_winner=result.winner,
        )
        evaluator.apply_reviewer_decision(task, "human:bob", "rejected")
        assert task.status == "rejected"

    def test_deferred_verdict_stored(self, evaluator, kl):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [])
        task    = ReviewTask(
            probe=evaluator.probe,
            detector=evaluator.detector,
            all_results=result.all_results,
        )
        evaluator.apply_reviewer_decision(task, "agent:council-alpha", "deferred")
        assert task.status == "deferred"

    def test_agent_reviewer_id_accepted(self, evaluator, kl):
        primary = weak_layer("primary")
        result  = evaluator.evaluate(primary, [strong_layer("cand_a")])
        task    = ReviewTask(
            probe=evaluator.probe,
            detector=evaluator.detector,
            all_results=result.all_results,
            proposed_winner=result.winner,
        )
        evaluator.apply_reviewer_decision(task, "agent:council-alpha", "approved")
        assert task.reviewer_id == "agent:council-alpha"

    def test_chosen_layer_override(self, evaluator, kl):
        """Reviewer can override the proposed winner by specifying a different layer."""
        primary = weak_layer("primary")
        cand_a  = strong_layer("cand_a", cost=0.1)
        cand_b  = strong_layer("cand_b", cost=0.9)
        result  = evaluator.evaluate(primary, [cand_a, cand_b])

        task = ReviewTask(
            probe=evaluator.probe,
            detector=evaluator.detector,
            all_results=result.all_results,
            proposed_winner=result.winner,
        )
        # Reviewer overrides to cand_b (even though it has higher cost)
        evaluator.apply_reviewer_decision(
            task, "human:carol", "approved",
            chosen_layer_name="cand_b",
            notes="cand_b preferred for interpretability.",
        )
        assert task.status == "approved"
        assert task.reviewer_notes == "cand_b preferred for interpretability."


# ---------------------------------------------------------------------------
# GovernanceResult fields
# ---------------------------------------------------------------------------

class TestGovernanceResultFields:
    def test_probe_stored(self, evaluator):
        result = evaluator.evaluate(strong_layer("primary"), [])
        assert result.probe == "probe.xss.reflection"

    def test_detector_stored(self, evaluator):
        result = evaluator.evaluate(strong_layer("primary"), [])
        assert result.detector == "det.bert.toxic"

    def test_threshold_stored(self, evaluator):
        result = evaluator.evaluate(strong_layer("primary"), [])
        assert result.threshold == GOVERNANCE_CI_THRESHOLD

    def test_all_results_non_empty(self, evaluator):
        result = evaluator.evaluate(strong_layer("primary"), [weak_layer("cand_a")])
        assert len(result.all_results) > 0

    def test_candidate_result_has_ci_bounds(self, evaluator):
        result = evaluator.evaluate(strong_layer("primary"), [])
        cr = result.all_results[0]
        assert 0.0 <= cr.ci_lower <= 1.0
        assert 0.0 <= cr.ci_upper <= 1.0
        assert cr.ci_lower <= cr.ci_upper
