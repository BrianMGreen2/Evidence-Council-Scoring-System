# Evidence Council Scoring System

**Exhaustive evidence layer governance — bootstrap CI scoring, composite ranking, and human/agent review council for AI evaluation pipelines.**

Evidence Council is a standalone scoring and governance framework for AI probe evaluation. It evaluates every candidate evidence layer exhaustively against a 0.98 bootstrap confidence interval threshold, ranks all qualifying layers by composite score, and routes ambiguous or failing evaluations to a review council — human, agent, or both.

Designed to be domain-agnostic, uet aligned with many healthcare use cases where a high confidence interval is needed: works with [garak](https://github.com/NVIDIA/garak) probe pipelines out of the box and adapts to healthcare, financial, and other regulated evaluation contexts via configurable `ScoringConfig` profiles.

---

## Why Evidence Council?

Most evaluation pipelines apply a single evidence layer and accept the first result that clears a threshold. Evidence Council rejects that pattern for high-stakes contexts:

- **Exhaustive, not first-pass** — every candidate layer is evaluated; no layer auto-wins by being first
- **Composite scoring** — CI lower bound, pass rate, cost, and historical consistency are weighted together
- **Persistent knowledge layer** — every evaluation result is committed to an append-only artifact that informs future rankings via recency-weighted priors
- **Council review** — close calls and failures are routed to a `ReviewTask` queue consumed by human reviewers or a configurable agent council
- **Domain profiles** — scoring weights are swappable without touching governance logic

---

## Quickstart

```bash
pip install evidence-council
```

```python
from evidence_council.evaluator import GovernanceEvaluator, EvidenceLayer
from evidence_council.knowledge_layer import KnowledgeLayer

kl = KnowledgeLayer()  # reads/writes governance_knowledge_layer.jsonl

evaluator = GovernanceEvaluator(
    knowledge_layer=kl,
    probe="probe.xss.reflection",
    detector="det.bert.toxic",
)

primary = EvidenceLayer(name="layer_primary", passes=491, fails=9, cost_score=0.3)
candidates = [
    EvidenceLayer(name="layer_semantic_v3", passes=497, fails=3, cost_score=0.4),
    EvidenceLayer(name="layer_regex_strict", passes=494, fails=6, cost_score=0.1),
]

result = evaluator.evaluate(primary, candidates)

print(result.decision)          # GovernanceDecision.SUBSTITUTED
print(result.winner.layer.name) # layer_semantic_v3
print(result.winner.ci_lower)   # 0.9823
```

---

## How It Works

### 1. Knowledge-Informed Ranking

Before any layer is evaluated, `KnowledgeLayer.rank_candidates()` orders candidates by **expected composite score** derived from historical runs. Recency-weighted priors mean recent performance counts more than stale runs. Layers that reviewers have repeatedly rejected are penalised. This ordering determines evaluation sequence — not the winner.

### 2. Exhaustive Evaluation

Every layer — primary and all candidates — is evaluated via **bootstrap confidence interval at 0.98**. This is tighter than the conventional 0.95: a layer must be very consistently passing to clear this bar.

```
ci_lower, ci_upper = bootstrap_ci(passes, fails, ci_level=0.98, n_bootstrap=10_000)
passes_threshold = ci_lower >= 0.98
```

### 3. Composite Scoring

All layers that clear the threshold are scored:

| Component | Weight | Notes |
|---|---|---|
| `ci_lower` | 45% | Primary signal — statistical lower bound |
| `pass_rate` | 25% | Raw empirical performance |
| `cost_score` (inverted) | 20% | Cheaper layers score higher |
| Historical consistency | 10% | Low std-dev across runs scores higher |

An **approval rate penalty** is applied multiplicatively: layers that reviewers frequently reject receive a lower effective composite score in future evaluations.

Weights are overridable via `ScoringConfig` for domain-specific deployments.

### 4. Winner Selection

The layer with the **highest composite score among all qualifying layers** is proposed as the winner. If the top-2 composite scores are within `CLOSE_CALL_MARGIN = 0.03`, a `ReviewTask` is emitted even though a winner could be selected algorithmically — because a 3-point margin is genuinely ambiguous.

### 5. Knowledge Layer Commit

Every evaluated layer — passing or not — is committed to the knowledge layer JSONL artifact. This file is intended to be **committed to version control** alongside your evaluation configs. It is the system's memory.

### 6. Review Council

`ReviewTask` objects are emitted when:
- No layer clears the 0.98 threshold (`reason: "no_passing_layer"`)
- Top-2 qualifying layers are within `CLOSE_CALL_MARGIN` (`reason: "close_call"`)

Tasks are consumed by the reviewer interface (React dashboard) or directly via `GovernanceEvaluator.apply_reviewer_decision()`. The `reviewer_id` field accepts both `human:name` and `agent:council-name` identifiers — the same interface works for human reviewers today and an agent council as it is built out.

---

## Scoring Profiles

Pass a `ScoringConfig` to use domain-specific weights:

```python
from evidence_council.scoring.composite import ScoringConfig

# Healthcare profile: cost matters less, consistency matters more
healthcare = ScoringConfig(
    weight_ci_lower=0.50,
    weight_pass_rate=0.30,
    weight_cost=0.05,
    weight_consistency=0.15,
)

evaluator = GovernanceEvaluator(kl, probe, detector, scoring_config=healthcare)
```

Built-in profiles:

| Profile | Use case |
|---|---|
| `ScoringConfig.default()` | General AI evaluation |
| `ScoringConfig.healthcare()` | Clinical/regulated — consistency and CI weighted heavily |
| `ScoringConfig.cost_sensitive()` | High-throughput — cost weighted heavily |

---

## Knowledge Layer

The knowledge layer is an **append-only JSONL file** (`governance_knowledge_layer.jsonl` by default). Each line is a `KnowledgeRecord`:

```json
{
  "committed_at": "2025-03-11T14:22:01Z",
  "run_id": "a3f9c1d2-...",
  "probe": "probe.xss.reflection",
  "detector": "det.bert.toxic",
  "layer_name": "layer_semantic_v3",
  "ci_lower": 0.9823,
  "ci_upper": 0.9961,
  "pass_rate": 0.991,
  "passes": 497,
  "fails": 3,
  "cost_score": 0.4,
  "latency_ms": 142.3,
  "composite_score": 0.871,
  "governance_decision": "pass",
  "reviewer_id": null,
  "reviewer_verdict": null,
  "reviewer_notes": null
}
```

**Commit this file to your repository.** It is the longitudinal record of your governance system's decisions and the input to future ranking priors.

---

## Reviewer Interface

A React dashboard (`evidence_council/reviewer/ui/`) provides a queue interface for pending `ReviewTask` objects. Features:

- Side-by-side CI bar visualization for all evaluated layers
- Reviewer can override proposed winner by selecting any qualifying layer
- Verdict (`approved` / `rejected` / `deferred`) and notes are written back to the knowledge layer
- `reviewer_id` supports both human (`human:name`) and agent (`agent:council-alpha`) identifiers

---
## Architecture
```mermaid
---
title: Evidence Council Scoring System — Architecture
---

flowchart TD
    %% ── External inputs ───────────────────────────────────────────────
    PROBE(["`**Probe**
    probe.xss.reflection
    probe.sqli.union
    probe.prompt.injection`"])

    DETECTOR(["`**Detector**
    det.bert.toxic
    det.semantic.v4`"])

    LAYERS(["`**Evidence Layers**
    Primary Layer
    Candidate Layers 1..N`"])

    %% ── Knowledge Layer ───────────────────────────────────────────────
    subgraph KL["📚 Knowledge Layer  —  governance_knowledge_layer.jsonl"]
        direction TB
        KL_RANK["`**rank_candidates()**
        EWMA recency-weighted priors
        Approval rate penalty
        Returns ordered layer list`"]

        KL_COMMIT["`**commit()**
        Append-only JSONL write
        Every layer, every run
        Stable run_id per record`"]

        KL_PATCH["`**update_reviewer_verdict()**
        Patches verdict + reviewer_id
        Rewrites JSONL in place`"]

        KL_HIST["`**historical_consistency()**
        Std-dev of ci_lower
        Across prior runs`"]

        KL_APPR["`**reviewer_approval_rate()**
        Optimistic prior = 1.0
        Converges with verdicts`"]
    end

    %% ── Scoring Engine ────────────────────────────────────────────────
    subgraph SCORE["⚙️  Scoring Engine"]
        direction TB

        subgraph BCI["bootstrap_ci.py"]
            BCI_CORE["`**bootstrap_ci()**
            ci_level = 0.98
            n = 10,000 resamples
            Returns CIResult`"]
            BCI_THRESH{"`ci_lower
            ≥ 0.98?`"}
        end

        subgraph COMP["composite.py"]
            COMP_SCORE["`**compute_composite_score()**
            CI lower    45%
            Pass rate   25%
            Cost        20%
            Consistency 10%
            × approval penalty`"]
            COMP_CFG["`**ScoringConfig**
            default()
            healthcare()
            cost_sensitive()`"]
            COMP_CLOSE{"`Score gap
            < 0.03?`"}
        end
    end

    %% ── Governance Evaluator ──────────────────────────────────────────
    subgraph GE["🏛️  GovernanceEvaluator"]
        direction TB
        GE_RANK["`**1. Rank via KL priors**
        Order candidates
        before evaluation`"]

        GE_EVAL["`**2. Evaluate ALL layers**
        Exhaustive — no first-pass win
        Primary + every candidate`"]

        GE_COLLECT["`**3. Collect qualifying**
        All layers where
        ci_lower ≥ 0.98`"]

        GE_WINNER["`**4. Select winner**
        Highest composite score
        among qualifying layers`"]

        GE_DECIDE{"`Decision`"}
    end

    %% ── Outcomes ──────────────────────────────────────────────────────
    OUT_PASS(["`✅  PASS
    Primary layer
    cleared threshold`"])

    OUT_SUB(["`🔄  SUBSTITUTED
    Candidate layer
    wins on composite`"])

    OUT_FLAG(["`🚩  FLAG
    No layer cleared
    threshold`"])

    %% ── Review Council ────────────────────────────────────────────────
    subgraph RC["👥  Review Council"]
        direction TB
        RC_QUEUE["`**ReviewQueue**
        Priority-ordered
        Pending tasks`"]

        RC_TASK["`**ReviewTask**
        reason: no_passing_layer
        reason: close_call
        reason: reviewer_rejection`"]

        RC_VERDICT["`**ReviewVerdict**
        APPROVED
        REJECTED → requeue
        DEFERRED → elevate priority`"]

        subgraph REVIEWERS["Reviewers"]
            direction LR
            HUMAN["`👤 Human
            human:name`"]
            AGENT["`🤖 Agent
            agent:council-alpha`"]
        end
    end

    %% ── Dashboard ─────────────────────────────────────────────────────
    UI["`**Reviewer Dashboard**
    reviewer_ui.jsx
    CI bar visualisation
    Override proposed winner
    Verdict → KL patch`"]

    %% ── Flow ──────────────────────────────────────────────────────────
    PROBE       --> GE_RANK
    DETECTOR    --> GE_RANK
    LAYERS      --> GE_RANK

    KL_RANK     --> GE_RANK
    KL_HIST     --> COMP_SCORE
    KL_APPR     --> COMP_SCORE

    GE_RANK     --> GE_EVAL
    GE_EVAL     --> BCI_CORE
    BCI_CORE    --> BCI_THRESH
    BCI_THRESH  -->|Yes| GE_COLLECT
    BCI_THRESH  -->|No — recorded| GE_EVAL

    COMP_CFG    --> COMP_SCORE
    GE_COLLECT  --> COMP_SCORE
    COMP_SCORE  --> GE_WINNER
    GE_WINNER   --> COMP_CLOSE
    COMP_CLOSE  -->|No| GE_DECIDE
    COMP_CLOSE  -->|Yes → emit task| RC_TASK

    GE_EVAL     --> KL_COMMIT
    GE_DECIDE   -->|Primary wins| OUT_PASS
    GE_DECIDE   -->|Candidate wins| OUT_SUB
    GE_DECIDE   -->|None qualify| OUT_FLAG

    OUT_FLAG    --> RC_TASK
    RC_TASK     --> RC_QUEUE
    RC_QUEUE    --> REVIEWERS
    HUMAN       --> RC_VERDICT
    AGENT       --> RC_VERDICT
    RC_VERDICT  -->|Approved| KL_PATCH
    RC_VERDICT  -->|Rejected| RC_TASK
    RC_VERDICT  -->|Deferred| RC_QUEUE

    RC_QUEUE    --> UI
    UI          --> RC_VERDICT

    KL_PATCH    -.->|Updates approval rate| KL_APPR
    KL_COMMIT   -.->|Feeds next run priors| KL_RANK
    KL_COMMIT   -.->|Feeds consistency| KL_HIST

    %% ── Styles ────────────────────────────────────────────────────────
    classDef input      fill:#1e3a5f,stroke:#3b82f6,color:#e2e8f0
    classDef klnode     fill:#14532d,stroke:#22c55e,color:#e2e8f0
    classDef scorenode  fill:#1e1b4b,stroke:#818cf8,color:#e2e8f0
    classDef genode     fill:#431407,stroke:#f97316,color:#e2e8f0
    classDef outcome    fill:#0f172a,stroke:#64748b,color:#e2e8f0
    classDef rcnode     fill:#4a1942,stroke:#c084fc,color:#e2e8f0
    classDef ui         fill:#1c1917,stroke:#a8a29e,color:#e2e8f0
    classDef decision   fill:#292524,stroke:#78716c,color:#e2e8f0

    class PROBE,DETECTOR,LAYERS input
    class KL_RANK,KL_COMMIT,KL_PATCH,KL_HIST,KL_APPR klnode
    class BCI_CORE,BCI_THRESH,COMP_SCORE,COMP_CFG,COMP_CLOSE scorenode
    class GE_RANK,GE_EVAL,GE_COLLECT,GE_WINNER,GE_DECIDE genode
    class OUT_PASS,OUT_SUB,OUT_FLAG outcome
    class RC_QUEUE,RC_TASK,RC_VERDICT,HUMAN,AGENT rcnode
    class UI ui
  ```

## Project Structure

```
evidence-council/
├── evidence_council/
│   ├── __init__.py
│   ├── evaluator.py          # GovernanceEvaluator, EvidenceLayer, GovernanceResult
│   ├── knowledge_layer.py    # KnowledgeLayer, KnowledgeRecord, commit/rank/patch
│   └── scoring/
│       ├── __init__.py
│       ├── composite.py      # ScoringConfig, compute_composite_score
│       └── bootstrap_ci.py   # bootstrap_ci, GOVERNANCE_CI_THRESHOLD
│   └── reviewer/
│       ├── __init__.py
│       ├── tasks.py          # ReviewTask, ReviewQueue
│       └── ui/
│           └── reviewer_ui.jsx
├── tests/
├── docs/
│   └── scoring.md            # composite weight rationale and domain profiles
├── README.md
└── pyproject.toml
```

---

## Contributing

Pull requests welcome. When adding a new scoring component or changing default weights, update `docs/scoring.md` with the rationale — the weight choices are governance decisions and should be documented as such.

---

## License

Creative Commons
