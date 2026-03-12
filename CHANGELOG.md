# Changelog

All notable changes to Evidence Council are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Evidence Council uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version history maps directly to the scoring weight changelog in
`docs/scoring.md` — governance decisions and code releases are versioned
together intentionally.

---

## [Unreleased]

### Planned
- Agent council integration (multi-agent `ReviewQueue` routing)
- `ScoringConfig` registry for named profile management across deployments
- FHIR R4 export adapter for healthcare audit trail integration
- CLI entry point: `evidence-council evaluate`

---

## [0.1.0] — 2026-03-12

### Added

**Core evaluation pipeline**
- `GovernanceEvaluator` — exhaustive evidence layer evaluation against the
  0.98 bootstrap CI threshold; all qualifying layers are scored and ranked,
  not first-pass selected
- `EvidenceLayer` — input data structure for a single evidence layer with
  `passes`, `fails`, `cost_score`, and `latency_ms`
- `GovernanceResult` — full evaluation result carrying decision, winner,
  all candidate results, qualifying results, and optional `ReviewTask`
- `GovernanceDecision` enum — `PASS`, `SUBSTITUTED`, `FLAG`
- `CandidateResult` — per-layer result with CI bounds, composite score,
  consistency, approval rate, and attached `KnowledgeRecord`

**Bootstrap CI scoring (`evidence_council.scoring.bootstrap_ci`)**
- `bootstrap_ci()` — percentile bootstrap CI at configurable `ci_level`
  (default 0.98); pure function with no side effects
- `CIResult` — immutable result dataclass with `margin`, `width`, `as_dict()`
- `passes_governance_threshold()` — convenience wrapper returning bool
- `minimum_passes_for_threshold()` — binary search planning utility: given
  a fixed trial budget, how many must pass to clear the governance bar?
- `compare_layers()` — multi-layer CI comparison sorted by `ci_lower`
- Degenerate input handling with advisory `warnings` (zero trials, all pass,
  all fail, low sample count)

**Composite scoring (`evidence_council.scoring.composite`)**
- `ScoringConfig` — frozen dataclass with weight validation (must sum to 1.0)
- Three built-in domain profiles: `default()`, `healthcare()`, `cost_sensitive()`
- `compute_composite_score()` — weighted combination of CI lower bound,
  pass rate, cost efficiency, and historical consistency with multiplicative
  approval rate penalty
- `consistency_component()` — normalised std-dev stability score
- `approval_penalty()` — multiplicative penalty from reviewer approval history
- `rank_by_composite()` — sorts candidate dicts by composite score in place
- `is_close_call()` — detects when top-2 scores are within `close_call_margin`

**Knowledge layer (`evidence_council.knowledge_layer`)**
- `KnowledgeLayer` — append-only JSONL persistent artifact; committed to
  version control as the longitudinal governance record
- `KnowledgeRecord` — single committed evaluation record with all scoring
  fields, reviewer verdict fields, and a stable `run_id`
- `rank_candidates()` — recency-weighted prior ranking using EWMA over
  historical `ci_lower` values; approval rate penalty applied
- `historical_consistency()` — std-dev of `ci_lower` across prior runs
- `reviewer_approval_rate()` — fraction of approved verdicts; optimistic
  prior (1.0) for layers with no review history
- `update_reviewer_verdict()` — patches a committed record and rewrites the
  JSONL file; supports both human and agent reviewer IDs

**Review council (`evidence_council.reviewer`)**
- `ReviewTask` — unit of work emitted for human or agent review; reasons:
  `no_passing_layer`, `close_call`, `reviewer_rejection`
- `ReviewVerdict` — `str` enum: `APPROVED`, `REJECTED`, `DEFERRED`
- `ReviewTask.resolve()` — applies a verdict with timestamp
- `ReviewTask.requeue_as_rejection()` — creates a child task with elevated
  priority and `parent_task_id` audit link
- `ReviewQueue` — in-memory ordered queue sorted by priority then `created_at`;
  supports iteration, filtering by reason/probe, and mid-iteration enqueue
- Reviewer ID convention: `human:<n>` and `agent:<n>` use the same interface

**Reviewer dashboard (`evidence_council/reviewer/ui/reviewer_ui.jsx`)**
- React dashboard for pending `ReviewTask` queue
- Side-by-side CI bar visualisation for all evaluated layers
- Reviewer can override proposed winner by selecting any qualifying layer
- Verdict (`approved` / `rejected` / `deferred`) and notes committed back
  to knowledge layer
- Sidebar stats: pending count, close calls, no-pass count, resolved count
- Persistent storage via `window.storage` API

**Scoring documentation**
- `docs/scoring.md` — composite weight rationale, domain profile documentation,
  close call detection explanation, and versioned changelog of all weight
  and threshold decisions

**Test suite**
- `tests/test_bootstrap_ci.py` — 50+ cases covering normal operation,
  degenerate inputs, threshold behaviour, reproducibility, and all helpers
- `tests/test_composite.py` — full coverage of `ScoringConfig` validation,
  all three profiles, scoring functions, ranking, and close call detection
- `tests/test_knowledge_layer.py` — persistence, reload, history queries,
  consistency, approval rate, ranking, and verdict patching
- `tests/test_evaluator.py` — PASS/SUBSTITUTED/FLAG decisions, exhaustive
  evaluation guarantee, winner selection by composite not first-pass,
  close call detection, knowledge layer integration, and reviewer decisions

### Governance decisions (see `docs/scoring.md` for full rationale)
- CI threshold set to **0.98** (tighter than conventional 0.95)
- Default composite weights: CI lower 45% / pass rate 25% / cost 20% / consistency 10%
- Healthcare profile: CI lower 50% / pass rate 30% / cost 5% / consistency 15%
- Cost-sensitive profile: CI lower 40% / pass rate 20% / cost 35% / consistency 5%
- Close call margin: **0.03** composite score gap triggers review even when
  a winner exists

---

[Unreleased]: https://github.com/BrianMGreen2/evidence-council/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BrianMGreen2/evidence-council/releases/tag/v0.1.0
