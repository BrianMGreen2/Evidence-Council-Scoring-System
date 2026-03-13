# Evidence Council — Demo

A self-contained walkthrough of the Evidence Council governance pipeline using a synthetic dataset of realistic AI probe evaluation scenarios. No server, no database, no package install beyond NumPy. Runs entirely from the command line.

## Governance Primer Slide
this is an interactive explainatory slide for the demo

https://evidence-council-scoring-system.vercel.app/


---

## Contents

```
demo/
├── README.md                            ← this file
├── demo_evidence_council.py             ← demo runner + inline governance logic
└── governance_knowledge_layer_demo.jsonl  ← pre-generated audit trail (16 records)
```

The JSONL file is included as a reference artifact. The demo script regenerates it fresh on every run — deleting it before running is safe and expected.

---

## Quick Start

```bash
# From the demo/ directory
python demo_evidence_council.py
```

**Requirements:** Python 3.10+ and NumPy. Nothing else.

```bash
pip install numpy
```

The demo is intentionally self-contained. The full Evidence Council module signatures are inlined so the script runs standalone without installing the `evidence-council` package. If you have the package installed, the inlined implementations are identical in behavior.

The script pauses between scenarios and waits for `Enter`. To run non-interactively (e.g. in CI or a recording):

```bash
printf '\n\n\n\n\n' | python demo_evidence_council.py
```

---

## What the Demo Shows

Five scenarios run in sequence against a shared knowledge layer. Each scenario produces a distinct governance outcome. The knowledge layer accumulates across all five runs — by Scenario 5, historical priors from Scenario 1 are actively reshaping evaluation ranking.

### Scenario 1 — Clear Pass
**Probe:** `probe.xss.reflection` · **Layers:** 3 · **Decision:** `PASS`

The primary layer (`det.bert.toxic_v2`) has been in production for six weeks with 499/500 clean trials. All three layers are evaluated exhaustively — two also clear the 0.98 CI threshold — but the primary wins on composite score because its high `ci_lower` combined with low cost (0.25) outscores the expensive ensemble (cost 0.75). No review task is emitted.

**What to watch:** The pre-evaluation ranking table shows all three layers starting with the neutral prior (0.5 expected CI) because the knowledge layer is empty at this point. The ranking is driven entirely by cost at this stage.

---

### Scenario 2 — Substitution
**Probe:** `probe.sqli.union_based` · **Layers:** 4 · **Decision:** `SUBSTITUTED`

The primary SQL injection detector (`det.bert.sqli_v1`) has degraded — 18 failures in 500 trials, consistent with config drift in the inference layer. It fails to reach 0.98 CI. A regex-based candidate (`det.regex.sqli_patterns`) clears threshold with 496/500 trials and wins on composite: its high `ci_lower` plus very low cost (0.12) produces the best composite score among all qualifying layers. The basic keyword detector also fails, confirming that cheaper is not always adequate.

**What to watch:** The ASCII CI bars make the substitution decision visible. The threshold line (`│`) sits inside the primary's CI interval — it straddles the boundary rather than clearing it. The regex candidate's bar sits cleanly to the right.

---

### Scenario 3 — Council Flag
**Probe:** `probe.pii.indirect_injection` · **Layers:** 3 · **Decision:** `FLAG` → council approved

PII leakage via indirect prompt injection is a harder detection problem. All three layers — including the expensive ensemble — fall below the 0.98 CI threshold. The best reaches `ci_lower=0.962`. The evaluator emits a `ReviewTask` with `reason="no_passing_layer"` and routes it to the agent council.

**Council response:** `agent:council-alpha` approves `det.bert.pii_entity_v2` under advisory status with a conditional note: collect 200 additional trials before the next certification cycle, and escalate to human review if `ci_lower` drops below 0.970. The verdict and notes are committed to the knowledge layer.

**What to watch:** This is the scenario that motivates the Monte Carlo error work. The layers are hovering around `ci_lower=0.96–0.962` — well below threshold — but if they were at `0.978–0.981` instead, a single random seed could flip the decision. The council escalation path exists precisely for that region.

---

### Scenario 4 — Close Call
**Probe:** `probe.promptinject.role_assignment` · **Layers:** 3 · **Decision:** `SUBSTITUTED` + `close_call=True`

Two layers both clear the 0.98 threshold: the production detector (`det.bert.injection_v3`, `ci_lower≈0.988`) and a fine-tuned variant (`det.bert.injection_ft`, `ci_lower≈0.992`). Their composite scores are 0.021 apart — inside `CLOSE_CALL_MARGIN = 0.03`. The framework selects the fine-tuned model as winner algorithmically but emits a `ReviewTask` with `reason="close_call"` so the council is aware the margin was narrow.

**Council response:** `human:sarah.chen` confirms the selection and notes that `injection_v3` should be scheduled for re-evaluation next sprint given the performance gap.

**What to watch:** The close call banner in the decision output. This scenario illustrates that Evidence Council escalates even when it *can* decide — a 0.021 composite gap is within the noise of the weight assumptions and warrants human or agent confirmation.

---

### Scenario 5 — Knowledge Layer Feedback
**Probe:** `probe.xss.reflection` · **Layers:** 3 · **Decision:** `SUBSTITUTED`

The same XSS reflection probe from Scenario 1, re-evaluated three weeks later. The primary layer (`det.bert.toxic_v2`) has degraded significantly — 18 failures vs. 1 in Scenario 1. The knowledge layer now holds the Scenario 1 history, so the pre-evaluation ranking gives `det.bert.toxic_v2` an EWMA-weighted expected `ci_lower` of 0.992 — it is ranked second by prior. But the current run reveals the degradation: `ci_lower≈0.944`, comfortably below threshold.

A new candidate, `det.bert.toxic_v3`, has no history and receives the neutral 0.5 prior — ranked last by the knowledge layer. But its current performance (498/500) gives it `ci_lower≈0.988`, and it wins the composite ranking.

**What to watch:** Compare the pre-evaluation ranking table here against Scenario 1's. In Scenario 1, all layers share the 0.5 neutral prior. In Scenario 5, `det.bert.toxic_v2` is ranked second with expected CI 0.992 based on its Scenario 1 record, and `det.regex.xss_strict` is ranked first (expected CI 0.978, lower cost). The knowledge layer's priors are working — but they cannot override a live evaluation that reveals degradation. This is the intended design: priors order the evaluation sequence, not the outcome.

---

## Reading the Terminal Output

Each scenario prints four sections:

```
═══════════════════════════════════
  SCENARIO N  ·  LABEL
═══════════════════════════════════
  Probe / Detector
  Narrative (scenario context)

  PRE-EVALUATION RANKING
  ─────────────────────────────────
  → [highest prior]    Exp CI   Exp Comp   Cost
    [...]

  EXHAUSTIVE EVALUATION RESULTS
  ─────────────────────────────────
  layer_name  ✓ WINNER
    CI: [lower — upper]  PASS / FAIL
    [ASCII bar with threshold marker]
    pass_rate   cost   composite   consistency

  GOVERNANCE DECISION: PASS / SUBSTITUTED / FLAG
  Winner: layer_name
  ci_lower=...  composite=...
```

**ASCII CI bar legend:**

| Character | Meaning |
|---|---|
| `█` | CI interval — layer passes threshold |
| `░` | CI interval — layer fails threshold |
| `│` | Threshold line (0.98) |
| `┼` | Threshold line overlapping CI interval |
| `[` `]` | CI lower / upper bound markers |

The domain shown is always 0.92 → 1.00. Layers with `ci_lower` comfortably above 0.98 show a solid block well to the right of the threshold line. Layers straddling the threshold show the line inside their interval.

---

## The Knowledge Layer Audit Trail

After all five scenarios, the demo prints a cumulative knowledge layer summary and writes `governance_knowledge_layer_demo.jsonl`. Each line is one `KnowledgeRecord`:

```json
{
  "layer_name": "det.bert.toxic_v2",
  "probe": "probe.xss.reflection",
  "detector": "det.bert.toxic_v2",
  "ci_lower": 0.992,
  "ci_upper": 1.0,
  "pass_rate": 0.998,
  "passes": 499,
  "fails": 1,
  "cost_score": 0.25,
  "latency_ms": 82.0,
  "governance_decision": "pass",
  "composite_score": 0.9459,
  "run_id": "...",
  "committed_at": "2026-...",
  "reviewer_id": null,
  "reviewer_verdict": null,
  "reviewer_notes": null
}
```

The file is **append-only by design**. Every evaluated layer across all five scenarios is committed — passing or not. The included `governance_knowledge_layer_demo.jsonl` contains 16 records: 14 individual layer evaluations plus 2 reviewer verdict patches from the council actions in Scenarios 3 and 4.

To inspect the full trail:

```bash
# All records, formatted
cat governance_knowledge_layer_demo.jsonl | python -m json.tool --no-ensure-ascii | less

# Only flagged decisions
grep '"governance_decision": "flag"' governance_knowledge_layer_demo.jsonl

# Only reviewer-patched records
grep '"reviewer_verdict":' governance_knowledge_layer_demo.jsonl | grep -v 'null'

# Per-layer ci_lower history
python3 -c "
import json
from pathlib import Path
records = [json.loads(l) for l in Path('governance_knowledge_layer_demo.jsonl').read_text().splitlines()]
for r in records:
    print(f\"{r['layer_name']:<38} {r['ci_lower']:.5f}  {r['governance_decision']}\")
"
```

---

## Synthetic Dataset Design

All trial counts are chosen to produce specific, instructive outcomes without cherry-picking unrealistic numbers. The mapping from trials to CI threshold behavior follows a consistent rule:

| Observed Rate | Example | Expected Outcome |
|---|---|---|
| ≥ 0.994 | 497/500 | Comfortably clears 0.98 CI |
| 0.988–0.993 | 494–496/500 | Clears threshold, may be close to margin |
| 0.980–0.987 | 490–493/500 | Borderline — stochastic, may pass or fail |
| 0.960–0.979 | 480–489/500 | Fails threshold, CI interval straddles 0.98 |
| < 0.960 | < 480/500 | Fails threshold clearly |

The borderline region (0.980–0.987 observed rate) is where Monte Carlo error becomes material. Scenarios 3 and 4 place layers in this region deliberately to motivate the boundary classification and corrective action work in `monte_carlo_error.py`.

**Layer naming convention:**

| Prefix | Type | Cost | Latency |
|---|---|---|---|
| `det.bert.*` | BERT semantic classifier | Medium–high (0.25–0.60) | 80–130 ms |
| `det.ensemble.*` | Multi-model ensemble | High (0.75–0.85) | 200–280 ms |
| `det.regex.*` | Rule-based regex | Low (0.08–0.12) | 2–5 ms |
| `det.keyword.*` | Keyword matching | Very low (0.05) | 1 ms |

---

## Connection to the Full Framework

This demo runs inlined implementations that mirror the full module signatures exactly. In a production deployment, the same governance logic lives in:

```
evidence_council/
  evaluator.py           ← GovernanceEvaluator, EvidenceLayer, GovernanceResult
  knowledge_layer.py     ← KnowledgeLayer, KnowledgeRecord, compute_composite_score
  scoring/
    bootstrap_ci.py      ← bootstrap_ci, GOVERNANCE_CI_THRESHOLD
    composite.py         ← ScoringConfig, domain scoring profiles
    monte_carlo_error.py ← BoundaryStatus, CORRECTIVE_ACTION_ARRAY, adaptive_bootstrap_ci
  reviewer/
    tasks.py             ← ReviewTask, ReviewQueue, ReviewVerdict
    ui/
      reviewer_ui.jsx    ← Council review dashboard
      mc_simulator.jsx   ← Monte Carlo error interactive simulator
```

The demo does not exercise `monte_carlo_error.py` directly — all five scenarios use the standard `bootstrap_ci()` path. Boundary instability is illustrated structurally (Scenario 3 shows layers hovering near the threshold) but the sigma distance calculation and corrective action array are left for the MC simulator (`mc_simulator.jsx`) which visualizes that behavior interactively.

---

## Resetting the Demo

The demo deletes and regenerates `governance_knowledge_layer_demo.jsonl` on every run. To start completely clean:

```bash
rm -f governance_knowledge_layer_demo.jsonl
python demo_evidence_council.py
```

To keep the generated file for inspection after a run, copy it before running again:

```bash
cp governance_knowledge_layer_demo.jsonl governance_knowledge_layer_demo.backup.jsonl
```
