# Scoring System

This document records the rationale behind Evidence Council's composite scoring weights and domain-specific profiles. **Weight changes are governance decisions and must be documented here** — the knowledge layer records *what* was scored; this file records *why* the scoring is designed the way it is.

---

## The 0.98 Threshold

Evidence Council uses a bootstrap confidence interval threshold of **0.98**, not the conventional 0.95.

The conventional 0.95 threshold was established for general statistical practice. In high-stakes evaluation contexts — AI probes gating safety-critical outputs, clinical decision support, regulated financial models — a false pass is materially more costly than a false flag. The 0.98 threshold means:

- The bootstrap CI is calculated at the 98% level, so the lower bound represents a tighter statistical guarantee
- A layer must be very consistently passing across its sample to clear the bar
- Borderline layers are more likely to be routed to the review council rather than auto-passed

If your deployment context has different tolerance for false passes vs. false flags, adjust `GOVERNANCE_CI_THRESHOLD` in `bootstrap_ci.py` and document the rationale in this file with a dated entry.

---

## Composite Score Components

The composite score ranks all layers that clear the 0.98 threshold. It is computed as:

```
composite = (
    W_CI_LOWER    * ci_lower
  + W_PASS_RATE   * pass_rate
  + W_COST        * (1.0 - cost_score)
  + W_CONSISTENCY * consistency_component
) * approval_penalty
```

Where `consistency_component = max(0.0, 1.0 - (std_dev / 0.15))` and `approval_penalty = 1.0 - (0.3 * (1.0 - approval_rate))`.

### Component Rationale

#### `ci_lower` — 45%

The CI lower bound is the primary signal because it captures both the pass rate *and* the statistical uncertainty around it. A layer with 95 passes out of 100 trials has a lower `ci_lower` than a layer with 980 passes out of 1000 trials, even if the raw pass rates are identical. Sample size and consistency are implicitly rewarded here.

This is intentionally the dominant weight. All other components are tiebreakers within the space of statistically strong layers.

#### `pass_rate` — 25%

Raw empirical performance. Included alongside `ci_lower` because the two are not redundant: CI lower bound can be similar across layers with different sample sizes and different raw rates. Pass rate ensures the composite is anchored to observed behavior, not just the width of the confidence interval.

#### `cost_score` (inverted) — 20%

Cost is domain-defined and caller-supplied. The default normalization assumes `0.0` = cheapest and `1.0` = most expensive. The composite uses `1.0 - cost_score` so cheaper layers score higher, all else being equal.

20% weight reflects the view that cost should influence selection but never override statistical quality. A cheap layer that barely clears 0.98 should not win over a slightly more expensive layer with a substantially higher `ci_lower`.

In healthcare and regulated contexts, the cost weight is typically reduced further — see domain profiles below.

#### Historical consistency — 10%

Standard deviation of `ci_lower` across all historical runs for this layer/probe/detector combination, normalized against a reference std-dev of 0.15 (empirically: layers with std-dev > 0.15 are considered highly inconsistent). Layers with low variance across runs are preferred because consistency is a proxy for reliability under distribution shift.

10% weight reflects that consistency is valuable but that a single high-quality run should not be heavily penalised for lacking history. New layers receive a consistency score of 0.0 (no history), which neither rewards nor heavily penalises them.

#### Approval rate penalty (multiplicative)

When human or agent reviewers reject a proposed layer, that verdict is recorded against the layer in the knowledge layer. The approval penalty is applied multiplicatively to the composite:

```
approval_penalty = 1.0 - (0.3 * (1.0 - approval_rate))
```

A layer with a 100% approval rate carries no penalty (factor = 1.0). A layer that has never been approved carries a 30% penalty (factor = 0.7). This ensures the council's accumulated judgement shapes future rankings without permanently disqualifying a layer — a layer that has been improved can recover its approval rate over time.

---

## Close Call Detection

When the top-2 qualifying layers have composite scores within `CLOSE_CALL_MARGIN = 0.03` of each other, a `ReviewTask` is emitted even if a winner could be selected algorithmically. This is intentional: a 3-point composite margin is within the noise of the weight assumptions, and genuinely ambiguous cases should involve the council.

If your deployment has the agent council fully operational and you want to reduce human review volume, `CLOSE_CALL_MARGIN` can be tightened. Document any change here.

---

## Domain Profiles

Scoring weights should reflect the cost structure and risk tolerance of the deployment context. The following profiles are built in and available via `ScoringConfig`.

### `ScoringConfig.default()`

General AI evaluation. Balances statistical quality, pass rate, cost, and consistency.

| Component | Weight |
|---|---|
| `ci_lower` | 0.45 |
| `pass_rate` | 0.25 |
| `cost_score` (inverted) | 0.20 |
| consistency | 0.10 |

**Use when:** Running garak probe pipelines, general LLM safety evaluation, no strong domain-specific cost or consistency requirements.

---

### `ScoringConfig.healthcare()`

Clinical and regulated healthcare contexts. Statistical reliability and consistency are weighted heavily; cost is de-emphasised because the cost of a governance failure outweighs the cost of a more expensive evidence layer.

| Component | Weight |
|---|---|
| `ci_lower` | 0.50 |
| `pass_rate` | 0.30 |
| `cost_score` (inverted) | 0.05 |
| consistency | 0.15 |

**Use when:** Evaluating AI systems in clinical decision support, diagnostic assistance, patient-facing outputs, or any context subject to FDA, HIPAA, HL7 FHIR, or CMS governance requirements. The higher consistency weight reflects that a layer which performs well on average but varies across runs is a liability in regulated audit trails.

**Rationale for reducing cost weight to 0.05:** In healthcare, the cost differential between evidence layers is rarely material relative to the cost of a compliance failure, a misclassification in a clinical context, or the overhead of a manual review cycle triggered by a false pass.

---

### `ScoringConfig.cost_sensitive()`

High-throughput evaluation where cost per evaluation is a binding constraint. Statistical quality floor is maintained, but cost is promoted as a primary tiebreaker.

| Component | Weight |
|---|---|
| `ci_lower` | 0.40 |
| `pass_rate` | 0.20 |
| `cost_score` (inverted) | 0.35 |
| consistency | 0.05 |

**Use when:** Running large-scale evaluation sweeps, CI/CD pipelines with budget constraints, or any context where the volume of evaluations makes cost a first-class concern. Note that the 0.98 threshold is unchanged — cost sensitivity affects selection among qualifying layers only, not the statistical bar for qualification.

---

## Adding a New Profile

To add a domain profile:

1. Add a classmethod to `ScoringConfig` in `evidence_council/scoring/composite.py`
2. Verify weights sum to 1.0
3. Add an entry to this file with the weight table, rationale, and intended use context
4. Include a dated changelog entry below

Domain profiles are governance decisions. They should be reviewed and approved before being used in a production evaluation pipeline, and the approval should be noted in the changelog.

---

## Changelog

All weight changes, threshold changes, and new profile additions are recorded here.

| Date | Change | Rationale | Author |
|---|---|---|---|
| 2025-03-11 | Initial weights established: CI 0.45 / pass rate 0.25 / cost 0.20 / consistency 0.10 | Baseline for general AI probe evaluation | BrianMGreen2 |
| 2025-03-11 | CI threshold set to 0.98 | Higher bar than conventional 0.95; appropriate for safety-critical evaluation contexts | BrianMGreen2 |
| 2025-03-11 | Healthcare profile added: CI 0.50 / pass rate 0.30 / cost 0.05 / consistency 0.15 | Regulatory and clinical contexts require stronger consistency guarantees and de-emphasise cost | BrianMGreen2 |
| 2025-03-11 | Cost-sensitive profile added: CI 0.40 / pass rate 0.20 / cost 0.35 / consistency 0.05 | High-throughput pipelines where cost is a binding constraint | BrianMGreen2 |
