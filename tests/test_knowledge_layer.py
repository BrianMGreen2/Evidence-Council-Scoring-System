"""
tests/test_knowledge_layer.py

Tests for evidence_council/knowledge_layer.py

Coverage targets:
- Commit and reload (append-only persistence)
- rank_candidates ordering and prior calculation
- historical_consistency (std-dev across runs)
- reviewer_approval_rate (optimistic prior, convergence)
- update_reviewer_verdict (patch and rewrite)
- Forward-compatibility (unknown fields in JSONL are skipped)
- Empty and single-record edge cases
"""

import json
import pytest
import tempfile
from pathlib import Path
from knowledge_layer import KnowledgeLayer, KnowledgeRecord, compute_composite_score


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_record(**kwargs) -> KnowledgeRecord:
    defaults = dict(
        layer_name="layer_a",
        probe="probe.xss",
        detector="det.bert",
        ci_lower=0.983,
        ci_upper=0.996,
        pass_rate=0.991,
        passes=495,
        fails=5,
        cost_score=0.3,
        latency_ms=100.0,
        governance_decision="pass",
        composite_score=0.871,
    )
    defaults.update(kwargs)
    return KnowledgeRecord(**defaults)


@pytest.fixture
def tmp_kl(tmp_path):
    """KnowledgeLayer backed by a temporary file."""
    return KnowledgeLayer(path=tmp_path / "kl.jsonl")


@pytest.fixture
def populated_kl(tmp_path):
    """KnowledgeLayer with several pre-committed records."""
    kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
    kl.commit(make_record(layer_name="layer_a", probe="probe.xss", ci_lower=0.983, composite_score=0.871))
    kl.commit(make_record(layer_name="layer_a", probe="probe.xss", ci_lower=0.981, composite_score=0.865))
    kl.commit(make_record(layer_name="layer_b", probe="probe.xss", ci_lower=0.975, composite_score=0.840))
    kl.commit(make_record(layer_name="layer_c", probe="probe.xss", ci_lower=0.991, composite_score=0.890))
    return kl


# ---------------------------------------------------------------------------
# Construction and persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_empty_layer_has_no_records(self, tmp_kl):
        assert tmp_kl._records == []

    def test_commit_adds_record(self, tmp_kl):
        tmp_kl.commit(make_record())
        assert len(tmp_kl._records) == 1

    def test_commit_writes_to_file(self, tmp_kl):
        tmp_kl.commit(make_record())
        assert tmp_kl.path.exists()
        lines = tmp_kl.path.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_commit_is_valid_json(self, tmp_kl):
        tmp_kl.commit(make_record())
        line = tmp_kl.path.read_text().strip()
        parsed = json.loads(line)
        assert parsed["layer_name"] == "layer_a"

    def test_multiple_commits_append(self, tmp_kl):
        tmp_kl.commit(make_record(layer_name="layer_a"))
        tmp_kl.commit(make_record(layer_name="layer_b"))
        lines = tmp_kl.path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_reload_restores_records(self, tmp_path):
        path = tmp_path / "kl.jsonl"
        kl1 = KnowledgeLayer(path=path)
        kl1.commit(make_record(layer_name="layer_a"))
        kl1.commit(make_record(layer_name="layer_b"))

        kl2 = KnowledgeLayer(path=path)
        assert len(kl2._records) == 2
        assert kl2._records[0].layer_name == "layer_a"
        assert kl2._records[1].layer_name == "layer_b"

    def test_nonexistent_file_loads_empty(self, tmp_path):
        kl = KnowledgeLayer(path=tmp_path / "does_not_exist.jsonl")
        assert kl._records == []

    def test_forward_compat_skips_unknown_fields(self, tmp_path):
        """Records with extra/unknown fields should be skipped gracefully."""
        path = tmp_path / "kl.jsonl"
        # Write a record with an unknown field
        bad_record = {"unknown_field_xyz": 42, "layer_name": "layer_a"}
        path.write_text(json.dumps(bad_record) + "\n")
        kl = KnowledgeLayer(path=path)
        # Should load without error and skip the malformed record
        assert len(kl._records) == 0


# ---------------------------------------------------------------------------
# history_for
# ---------------------------------------------------------------------------

class TestHistoryFor:
    def test_returns_matching_records(self, populated_kl):
        hist = populated_kl.history_for("layer_a", probe="probe.xss")
        assert len(hist) == 2
        assert all(r.layer_name == "layer_a" for r in hist)

    def test_no_probe_filter_returns_all(self, populated_kl):
        hist = populated_kl.history_for("layer_a")
        assert len(hist) == 2

    def test_unknown_layer_returns_empty(self, populated_kl):
        hist = populated_kl.history_for("layer_unknown", probe="probe.xss")
        assert hist == []

    def test_detector_filter(self, tmp_path):
        kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
        kl.commit(make_record(layer_name="layer_a", detector="det.bert"))
        kl.commit(make_record(layer_name="layer_a", detector="det.other"))
        hist = kl.history_for("layer_a", detector="det.bert")
        assert len(hist) == 1
        assert hist[0].detector == "det.bert"


# ---------------------------------------------------------------------------
# historical_consistency
# ---------------------------------------------------------------------------

class TestHistoricalConsistency:
    def test_single_record_returns_zero(self, tmp_kl):
        tmp_kl.commit(make_record(layer_name="layer_a", ci_lower=0.983))
        assert tmp_kl.historical_consistency("layer_a") == 0.0

    def test_zero_records_returns_zero(self, tmp_kl):
        assert tmp_kl.historical_consistency("layer_a") == 0.0

    def test_identical_ci_lowers_return_zero(self, tmp_kl):
        tmp_kl.commit(make_record(layer_name="layer_a", ci_lower=0.983))
        tmp_kl.commit(make_record(layer_name="layer_a", ci_lower=0.983))
        assert tmp_kl.historical_consistency("layer_a") == pytest.approx(0.0, abs=1e-10)

    def test_varied_ci_lowers_return_nonzero(self, populated_kl):
        std = populated_kl.historical_consistency("layer_a", probe="probe.xss")
        assert std > 0.0

    def test_consistency_increases_with_variance(self, tmp_kl):
        tmp_kl.commit(make_record(layer_name="layer_a", ci_lower=0.980))
        tmp_kl.commit(make_record(layer_name="layer_a", ci_lower=0.982))
        std_small = tmp_kl.historical_consistency("layer_a")

        tmp_kl.commit(make_record(layer_name="layer_b", ci_lower=0.960))
        tmp_kl.commit(make_record(layer_name="layer_b", ci_lower=0.999))
        std_large = tmp_kl.historical_consistency("layer_b")

        assert std_large > std_small


# ---------------------------------------------------------------------------
# reviewer_approval_rate
# ---------------------------------------------------------------------------

class TestReviewerApprovalRate:
    def test_no_reviews_returns_one(self, tmp_kl):
        tmp_kl.commit(make_record(layer_name="layer_a"))
        assert tmp_kl.reviewer_approval_rate("layer_a") == pytest.approx(1.0)

    def test_all_approved_returns_one(self, tmp_path):
        kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="approved"))
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="approved"))
        assert kl.reviewer_approval_rate("layer_a") == pytest.approx(1.0)

    def test_all_rejected_returns_zero(self, tmp_path):
        kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="rejected"))
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="rejected"))
        assert kl.reviewer_approval_rate("layer_a") == pytest.approx(0.0)

    def test_mixed_verdicts(self, tmp_path):
        kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="approved"))
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="rejected"))
        kl.commit(make_record(layer_name="layer_a", reviewer_verdict="approved"))
        assert kl.reviewer_approval_rate("layer_a") == pytest.approx(2 / 3)

    def test_unknown_layer_returns_one(self, tmp_kl):
        """Optimistic prior for layers never reviewed."""
        assert tmp_kl.reviewer_approval_rate("never_seen") == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------

class TestRankCandidates:
    def test_returns_all_layers(self, populated_kl):
        ranked = populated_kl.rank_candidates(
            ["layer_a", "layer_b", "layer_c"],
            probe="probe.xss",
            detector="det.bert",
        )
        assert len(ranked) == 3
        names = {r["layer_name"] for r in ranked}
        assert names == {"layer_a", "layer_b", "layer_c"}

    def test_sorted_descending_by_composite(self, populated_kl):
        ranked = populated_kl.rank_candidates(
            ["layer_a", "layer_b", "layer_c"],
            probe="probe.xss",
            detector="det.bert",
        )
        scores = [r["expected_composite"] for r in ranked]
        assert scores == sorted(scores, reverse=True)

    def test_required_keys_present(self, populated_kl):
        ranked = populated_kl.rank_candidates(
            ["layer_a"],
            probe="probe.xss",
            detector="det.bert",
        )
        for key in ("layer_name", "expected_ci_lower", "expected_pass_rate",
                    "cost_score", "consistency", "approval_rate", "expected_composite"):
            assert key in ranked[0]

    def test_unseen_layer_gets_neutral_prior(self, tmp_kl):
        ranked = tmp_kl.rank_candidates(
            ["never_seen_layer"],
            probe="probe.xss",
            detector="det.bert",
        )
        assert ranked[0]["expected_ci_lower"] == pytest.approx(0.5)
        assert ranked[0]["expected_pass_rate"] == pytest.approx(0.5)

    def test_cost_map_applied(self, populated_kl):
        ranked_cheap = populated_kl.rank_candidates(
            ["layer_a", "layer_b"],
            probe="probe.xss",
            detector="det.bert",
            cost_map={"layer_a": 0.1, "layer_b": 0.9},
        )
        ranked_expensive = populated_kl.rank_candidates(
            ["layer_a", "layer_b"],
            probe="probe.xss",
            detector="det.bert",
            cost_map={"layer_a": 0.9, "layer_b": 0.1},
        )
        # Cost changes should shift composite scores
        score_a_cheap     = next(r["expected_composite"] for r in ranked_cheap     if r["layer_name"] == "layer_a")
        score_a_expensive = next(r["expected_composite"] for r in ranked_expensive if r["layer_name"] == "layer_a")
        assert score_a_cheap > score_a_expensive

    def test_approval_penalty_affects_ranking(self, tmp_path):
        kl = KnowledgeLayer(path=tmp_path / "kl.jsonl")
        # layer_a: good CI, bad reviewer approval
        kl.commit(make_record(layer_name="layer_a", ci_lower=0.990, reviewer_verdict="rejected"))
        kl.commit(make_record(layer_name="layer_a", ci_lower=0.990, reviewer_verdict="rejected"))
        # layer_b: slightly lower CI, perfect approval
        kl.commit(make_record(layer_name="layer_b", ci_lower=0.985, reviewer_verdict="approved"))
        kl.commit(make_record(layer_name="layer_b", ci_lower=0.985, reviewer_verdict="approved"))

        ranked = kl.rank_candidates(["layer_a", "layer_b"], probe="probe.xss", detector="det.bert")
        # Despite higher raw CI, layer_a should be penalised by rejection history
        top = ranked[0]["layer_name"]
        assert top == "layer_b"


# ---------------------------------------------------------------------------
# update_reviewer_verdict
# ---------------------------------------------------------------------------

class TestUpdateReviewerVerdict:
    def test_updates_record_in_memory(self, tmp_kl):
        record = make_record()
        tmp_kl.commit(record)
        success = tmp_kl.update_reviewer_verdict(
            run_id=record.run_id,
            reviewer_id="human:alice",
            verdict="approved",
            notes="Looks good",
        )
        assert success is True
        assert tmp_kl._records[0].reviewer_id == "human:alice"
        assert tmp_kl._records[0].reviewer_verdict == "approved"
        assert tmp_kl._records[0].reviewer_notes == "Looks good"

    def test_updates_persist_to_file(self, tmp_path):
        path = tmp_path / "kl.jsonl"
        kl1 = KnowledgeLayer(path=path)
        record = make_record()
        kl1.commit(record)
        kl1.update_reviewer_verdict(record.run_id, "human:bob", "rejected")

        kl2 = KnowledgeLayer(path=path)
        assert kl2._records[0].reviewer_verdict == "rejected"
        assert kl2._records[0].reviewer_id == "human:bob"

    def test_unknown_run_id_returns_false(self, tmp_kl):
        tmp_kl.commit(make_record())
        success = tmp_kl.update_reviewer_verdict("nonexistent-id", "human:alice", "approved")
        assert success is False

    def test_only_target_record_updated(self, tmp_path):
        path = tmp_path / "kl.jsonl"
        kl = KnowledgeLayer(path=path)
        r1 = make_record(layer_name="layer_a")
        r2 = make_record(layer_name="layer_b")
        kl.commit(r1)
        kl.commit(r2)

        kl.update_reviewer_verdict(r1.run_id, "human:alice", "approved")

        assert kl._records[0].reviewer_verdict == "approved"
        assert kl._records[1].reviewer_verdict is None

    def test_agent_reviewer_id_accepted(self, tmp_kl):
        record = make_record()
        tmp_kl.commit(record)
        tmp_kl.update_reviewer_verdict(record.run_id, "agent:council-alpha", "approved")
        assert tmp_kl._records[0].reviewer_id == "agent:council-alpha"
