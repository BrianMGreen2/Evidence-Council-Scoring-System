"""
knowledge_layer.py

Persistent knowledge artifact for evidence layer performance history.
Committed after every governance evaluation; read dynamically to rank
candidate_layers before exhaustive CI evaluation begins.

Schema (JSONL, one record per commit):
  {
    "committed_at": "<ISO-8601>",
    "probe": str,
    "detector": str,
    "layer_name": str,
    "ci_lower": float,
    "ci_upper": float,
    "pass_rate": float,
    "passes": int,
    "fails": int,
    "cost_score": float,          # lower = cheaper (0.0–1.0 normalized)
    "latency_ms": float,
    "governance_decision": str,   # "pass" | "substituted" | "flag"
    "reviewer_id": str | null,
    "reviewer_verdict": str | null,  # "approved" | "rejected" | "deferred"
    "composite_score": float,     # computed ranking score at commit time
    "run_id": str
  }
"""

from __future__ import annotations

import json
import uuid
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict, field


KNOWLEDGE_LAYER_PATH = Path("governance_knowledge_layer.jsonl")

# Composite score weights — tune as the council of agents matures
WEIGHT_CI_LOWER    = 0.45
WEIGHT_PASS_RATE   = 0.25
WEIGHT_COST        = 0.20   # inverted: lower cost = higher score
WEIGHT_CONSISTENCY = 0.10   # reward low variance across historical runs


@dataclass
class KnowledgeRecord:
    layer_name: str
    probe: str
    detector: str
    ci_lower: float
    ci_upper: float
    pass_rate: float
    passes: int
    fails: int
    cost_score: float          # 0.0 (cheapest) – 1.0 (most expensive)
    latency_ms: float
    governance_decision: str
    composite_score: float
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    committed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reviewer_id: Optional[str] = None
    reviewer_verdict: Optional[str] = None   # "approved" | "rejected" | "deferred"
    reviewer_notes: Optional[str] = None


def compute_composite_score(
    ci_lower: float,
    pass_rate: float,
    cost_score: float,
    consistency: float = 0.0,   # std-dev of historical ci_lower values; 0 = first run
) -> float:
    """
    Composite ranking score in [0, 1]. Higher is better.
    
    - ci_lower:     statistical lower bound — primary signal
    - pass_rate:    raw empirical performance
    - cost_score:   inverted (1 - cost) so cheap layers score higher
    - consistency:  inverted std-dev so stable layers score higher
    """
    cost_component = 1.0 - cost_score
    # Normalise consistency: assume std-dev > 0.15 is "very inconsistent"
    consistency_component = max(0.0, 1.0 - (consistency / 0.15))

    return (
        WEIGHT_CI_LOWER    * ci_lower
        + WEIGHT_PASS_RATE   * pass_rate
        + WEIGHT_COST        * cost_component
        + WEIGHT_CONSISTENCY * consistency_component
    )


class KnowledgeLayer:
    """
    Append-only JSONL knowledge artifact.
    Reads all history at init; exposes ranked layer recommendations
    for a given (probe, detector) context.
    """

    def __init__(self, path: Path = KNOWLEDGE_LAYER_PATH):
        self.path = path
        self._records: list[KnowledgeRecord] = []
        self._load()

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self._records.append(KnowledgeRecord(**json.loads(line)))
                    except (TypeError, KeyError):
                        pass   # forward-compat: skip records with new fields

    def commit(self, record: KnowledgeRecord) -> None:
        """Append a new record to the knowledge layer and keep in-memory cache."""
        self._records.append(record)
        with self.path.open("a") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def history_for(
        self,
        layer_name: str,
        probe: Optional[str] = None,
        detector: Optional[str] = None,
    ) -> list[KnowledgeRecord]:
        """Return all records for a layer, optionally scoped to probe/detector."""
        return [
            r for r in self._records
            if r.layer_name == layer_name
            and (probe is None or r.probe == probe)
            and (detector is None or r.detector == detector)
        ]

    def historical_consistency(
        self,
        layer_name: str,
        probe: Optional[str] = None,
        detector: Optional[str] = None,
    ) -> float:
        """Std-dev of ci_lower over historical runs (0.0 if < 2 records)."""
        hist = self.history_for(layer_name, probe, detector)
        values = [r.ci_lower for r in hist]
        return statistics.stdev(values) if len(values) >= 2 else 0.0

    def reviewer_approval_rate(self, layer_name: str) -> float:
        """Fraction of human/agent reviews that approved this layer."""
        reviewed = [
            r for r in self._records
            if r.layer_name == layer_name and r.reviewer_verdict is not None
        ]
        if not reviewed:
            return 1.0   # no history → optimistic prior
        approved = sum(1 for r in reviewed if r.reviewer_verdict == "approved")
        return approved / len(reviewed)

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    def rank_candidates(
        self,
        layer_names: list[str],
        probe: str,
        detector: str,
        cost_map: Optional[dict[str, float]] = None,
    ) -> list[dict]:
        """
        Return layer_names sorted by expected composite score (descending).
        Layers with no history get a neutral prior.
        Used to ORDER candidate evaluation — but ALL passing layers are still
        evaluated exhaustively; this ordering only determines eval sequence.

        Returns list of dicts:
            { layer_name, expected_ci_lower, expected_pass_rate,
              cost_score, consistency, approval_rate, expected_composite }
        """
        cost_map = cost_map or {}
        ranked = []

        for name in layer_names:
            hist = self.history_for(name, probe, detector)
            if hist:
                # Use ewma-style recency weighting (recent records weight more)
                weights = [1.5 ** i for i in range(len(hist))]
                total_w = sum(weights)
                exp_ci_lower  = sum(r.ci_lower   * w for r, w in zip(hist, weights)) / total_w
                exp_pass_rate = sum(r.pass_rate  * w for r, w in zip(hist, weights)) / total_w
            else:
                # Neutral prior for unseen layers
                exp_ci_lower  = 0.5
                exp_pass_rate = 0.5

            cost_score  = cost_map.get(name, 0.5)
            consistency = self.historical_consistency(name, probe, detector)
            approval_rt = self.reviewer_approval_rate(name)

            # Penalise layers that reviewers frequently reject
            approval_penalty = 1.0 - (0.3 * (1.0 - approval_rt))

            composite = compute_composite_score(
                exp_ci_lower, exp_pass_rate, cost_score, consistency
            ) * approval_penalty

            ranked.append({
                "layer_name":        name,
                "expected_ci_lower": round(exp_ci_lower, 4),
                "expected_pass_rate":round(exp_pass_rate, 4),
                "cost_score":        cost_score,
                "consistency":       round(consistency, 4),
                "approval_rate":     round(approval_rt, 4),
                "expected_composite":round(composite, 4),
            })

        ranked.sort(key=lambda x: x["expected_composite"], reverse=True)
        return ranked

    def update_reviewer_verdict(
        self,
        run_id: str,
        reviewer_id: str,
        verdict: str,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Patch a committed record with a reviewer verdict.
        Rewrites the JSONL file (records are small; this is acceptable).
        """
        updated = False
        for r in self._records:
            if r.run_id == run_id:
                r.reviewer_id = reviewer_id
                r.reviewer_verdict = verdict
                r.reviewer_notes = notes
                updated = True
                break
        if updated:
            with self.path.open("w") as f:
                for r in self._records:
                    f.write(json.dumps(asdict(r)) + "\n")
        return updated
