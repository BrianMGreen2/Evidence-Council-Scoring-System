# Contributing to Evidence Council

Thank you for your interest in contributing. Evidence Council is a governance
library — contributions to scoring logic, profiles, and thresholds carry extra
responsibility because they affect downstream governance decisions in real
evaluation pipelines. Please read this document before opening a PR.

---

## Ground rules

1. **Scoring changes are governance decisions.** Any change to composite
   weights, the CI threshold, `close_call_margin`, or domain profiles must
   be accompanied by an entry in `docs/scoring.md` and `CHANGELOG.md`
   explaining the rationale. A PR that changes numbers without documentation
   will not be merged.

2. **The knowledge layer schema is append-only.** New fields may be added to
   `KnowledgeRecord`; existing fields may not be renamed or removed without a
   migration path and a major version bump. The JSONL file may be committed
   to version control by users — breaking their history is not acceptable.

3. **Tests are required.** Every new public function needs tests. Every bug
   fix needs a regression test. The test suite runs in CI on every PR.

4. **Reviewer IDs are a shared contract.** The `human:<n>` / `agent:<n>`
   convention is used by both the Python API and the React dashboard. If you
   change the format, both must be updated together.

---

## Setting up a development environment

```bash
git clone https://github.com/BrianMGreen2/evidence-council.git
cd evidence-council

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Verify everything works:

```bash
pytest
ruff check .
mypy evidence_council/
```

---

## Running the test suite

```bash
# All tests
pytest

# With coverage report
pytest --cov=evidence_council --cov-report=term-missing

# Single file
pytest tests/test_bootstrap_ci.py -v

# Single test
pytest tests/test_evaluator.py::TestDecisionSubstituted::test_winner_is_highest_composite_not_first_pass -v
```

Tests use `n_bootstrap=500` and `rng_seed=42` for speed and reproducibility.
Do not change these in the test fixtures — determinism is required for CI.

---

## Code style

Evidence Council uses `ruff` for linting and formatting, and `mypy` in strict
mode for type checking.

```bash
ruff check .          # lint
ruff format .         # format
mypy evidence_council/
```

These run automatically in CI. PRs with lint or type errors will not be merged.

Key conventions:
- Public functions and classes require type annotations
- Docstrings use the Google style (`Args:`, `Returns:`, `Raises:`)
- Constants that represent governance decisions are `UPPER_SNAKE_CASE` and
  documented with a comment explaining what changing them means
- `frozen=True` dataclasses for all result and config types — immutability
  matters when values are committed to the knowledge layer

---

## Adding a new domain scoring profile

1. Add a `@classmethod` to `ScoringConfig` in
   `evidence_council/scoring/composite.py`
2. Ensure weights sum to exactly 1.0 (validated at construction)
3. Add the profile to `docs/scoring.md` with:
   - Weight table
   - Intended use context
   - Rationale for each weight relative to the default profile
   - Dated changelog entry
4. Add tests in `tests/test_composite.py` covering:
   - Weights sum to 1.0
   - Label is set correctly
   - At least one meaningful comparison against the default profile
5. Export the new classmethod from `evidence_council/scoring/__init__.py`
   and `evidence_council/__init__.py`

---

## Adding a new scoring component

New components (beyond CI lower bound, pass rate, cost, consistency) are
significant changes. Before implementation, open an issue to discuss:

- What the component measures and why it belongs in the composite score
- How it is normalised to [0, 1]
- Which weight it would take from existing components (weights must sum to 1.0)
- Whether it requires changes to `KnowledgeRecord` (schema impact)
- Whether existing domain profiles need to be updated

A new component that requires `KnowledgeRecord` changes will trigger a minor
version bump and a migration note in `CHANGELOG.md`.

---

## Submitting a pull request

1. Fork the repository and create a branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes with tests and documentation.

3. Run the full check suite locally before pushing:
   ```bash
   pytest && ruff check . && mypy evidence_council/
   ```

4. Open a PR against `main` with:
   - A clear description of what changed and why
   - A reference to any related issues
   - For scoring changes: confirmation that `docs/scoring.md` is updated

5. PRs require at least one approving review before merge.

---

## Reporting issues

Please include:
- Evidence Council version (`pip show evidence-council`)
- Python version
- A minimal reproducible example
- The full traceback if applicable
- For governance/scoring questions: the domain context (healthcare, general
  AI eval, etc.) so the discussion is grounded correctly

---

## Roadmap and areas actively seeking contribution

- **Agent council routing** — `ReviewQueue` iteration and task dispatch
  for multi-agent review workflows
- **FHIR R4 export** — adapter to format `KnowledgeRecord` as FHIR
  `AuditEvent` resources for healthcare integration
- **CLI** — `evidence-council evaluate` entry point
- **`ScoringConfig` registry** — named profile management for multi-deployment
  environments
- **Additional domain profiles** — financial services, legal/compliance,
  education. Proposals welcome via issues.
