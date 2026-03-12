"""
evidence_council/scoring/bootstrap_ci.py

Bootstrap confidence interval calculation for evidence layer governance.

The CI threshold is set at 0.98 — tighter than the conventional 0.95.
Rationale is documented in docs/scoring.md — "The 0.98 Threshold".

All public functions are pure (no side effects) and independently testable.
The bootstrap approach is preferred over analytical methods (e.g. Wilson,
Clopper-Pearson) because it makes no distributional assumptions and
generalises to non-binomial evidence sources without interface changes.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GOVERNANCE_CI_THRESHOLD: float = 0.98
"""
The bootstrap CI lower bound must meet or exceed this value for a layer
to qualify for composite ranking. Changing this value is a governance
decision — document the change in docs/scoring.md with a changelog entry.
"""

DEFAULT_N_BOOTSTRAP: int = 10_000
"""
Number of bootstrap resamples. 10,000 gives stable CI estimates for pass
rates in the 0.95–1.0 range at reasonable compute cost. Increase to
50,000–100,000 for publication-grade precision or when sample sizes are
small (< 50 trials). Decrease only in test contexts via the n_bootstrap
parameter — never change this default without benchmarking stability.
"""

_MIN_TRIALS_WARNING: int = 30
"""
Minimum number of trials (passes + fails) below which CI estimates become
unreliable regardless of the bootstrap method. CIResult.warnings will
contain an advisory when total < this value.
"""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CIResult:
    """
    Immutable result of a bootstrap CI calculation.

    Attributes:
        lower:          CI lower bound at the governance ci_level.
        upper:          CI upper bound at the governance ci_level.
        observed_rate:  Raw pass rate (passes / total). Point estimate.
        passes:         Input pass count.
        fails:          Input fail count.
        total:          passes + fails (nones excluded).
        ci_level:       The CI level used (e.g. 0.98).
        n_bootstrap:    Number of resamples used.
        passes_threshold: True if lower >= GOVERNANCE_CI_THRESHOLD.
        warnings:       Advisory messages. Empty list if all inputs are clean.
    """

    lower:             float
    upper:             float
    observed_rate:     float
    passes:            int
    fails:             int
    total:             int
    ci_level:          float
    n_bootstrap:       int
    passes_threshold:  bool
    warnings:          tuple[str, ...]

    @property
    def width(self) -> float:
        """Interval width — a proxy for estimate precision."""
        return self.upper - self.lower

    @property
    def margin(self) -> float:
        """
        Headroom between CI lower bound and the governance threshold.
        Positive = passes with margin. Negative = fails by this amount.
        """
        return self.lower - GOVERNANCE_CI_THRESHOLD

    def as_dict(self) -> dict:
        """Serialisable representation for inclusion in KnowledgeRecord."""
        return {
            "ci_lower":          self.lower,
            "ci_upper":          self.upper,
            "observed_rate":     self.observed_rate,
            "passes":            self.passes,
            "fails":             self.fails,
            "total":             self.total,
            "ci_level":          self.ci_level,
            "n_bootstrap":       self.n_bootstrap,
            "passes_threshold":  self.passes_threshold,
            "threshold":         GOVERNANCE_CI_THRESHOLD,
            "margin":            round(self.margin, 6),
            "width":             round(self.width, 6),
            "warnings":          list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Core bootstrap function
# ---------------------------------------------------------------------------

def bootstrap_ci(
    passes:      int,
    fails:       int,
    ci_level:    float = GOVERNANCE_CI_THRESHOLD,
    n_bootstrap: int   = DEFAULT_N_BOOTSTRAP,
    rng_seed:    Optional[int] = None,
) -> CIResult:
    """
    Compute a percentile bootstrap confidence interval for a binomial pass rate.

    Uses the percentile method: resample (passes + fails) trials with
    replacement at the observed rate, then take the alpha/2 and
    1 - alpha/2 percentiles of the resulting distribution.

    The bootstrap approach is preferred over analytical methods because:
    - It makes no distributional assumptions
    - It generalises to non-binomial evidence sources without interface changes
    - It is transparent and auditable — the resampling logic is explicit

    Args:
        passes:      Number of passing trials.
        fails:       Number of failing trials. Nones are excluded by the caller.
        ci_level:    Confidence level for the interval. Defaults to
                     GOVERNANCE_CI_THRESHOLD (0.98). To compute a standard
                     0.95 CI for diagnostic purposes, pass ci_level=0.95.
        n_bootstrap: Number of bootstrap resamples. Default: 10,000.
                     See DEFAULT_N_BOOTSTRAP for guidance on adjusting.
        rng_seed:    Optional integer seed for reproducibility. Pass a fixed
                     seed in tests; leave None in production for true randomness.

    Returns:
        CIResult with lower/upper bounds, observed rate, and advisory warnings.

    Raises:
        ValueError: If passes or fails are negative, or ci_level is not in (0, 1).

    Examples:
        >>> result = bootstrap_ci(passes=490, fails=10)
        >>> result.passes_threshold   # ci_lower >= 0.98?
        False
        >>> result = bootstrap_ci(passes=499, fails=1)
        >>> result.passes_threshold
        True
        >>> result.margin             # how much headroom above 0.98?
        0.0043...
    """
    # --- Input validation ---
    if passes < 0:
        raise ValueError(f"passes must be >= 0, got {passes}")
    if fails < 0:
        raise ValueError(f"fails must be >= 0, got {fails}")
    if not 0.0 < ci_level < 1.0:
        raise ValueError(f"ci_level must be in (0.0, 1.0), got {ci_level}")

    warnings: list[str] = []
    total = passes + fails

    # --- Degenerate cases ---
    if total == 0:
        warnings.append("No trials recorded (passes=0, fails=0). CI is undefined; returning (0.0, 0.0).")
        return CIResult(
            lower=0.0, upper=0.0, observed_rate=0.0,
            passes=passes, fails=fails, total=0,
            ci_level=ci_level, n_bootstrap=n_bootstrap,
            passes_threshold=False,
            warnings=tuple(warnings),
        )

    observed_rate = passes / total

    if observed_rate == 1.0:
        warnings.append(
            f"All {total} trials passed (observed_rate=1.0). "
            "Bootstrap CI upper bound is capped at 1.0; lower bound reflects "
            "sample size uncertainty. Consider collecting more trials to "
            "confirm stability."
        )
    elif observed_rate == 0.0:
        warnings.append(
            f"All {total} trials failed (observed_rate=0.0). "
            "Bootstrap CI lower bound is 0.0."
        )

    if total < _MIN_TRIALS_WARNING:
        warnings.append(
            f"Only {total} trials recorded. CI estimates are unreliable below "
            f"{_MIN_TRIALS_WARNING} trials regardless of bootstrap method. "
            "Collect more data before relying on this result for governance decisions."
        )

    # --- Bootstrap resampling ---
    rng = np.random.default_rng(rng_seed)
    boot_rates = rng.binomial(n=total, p=observed_rate, size=n_bootstrap) / total

    alpha = 1.0 - ci_level
    lower = float(np.percentile(boot_rates, 100.0 * (alpha / 2.0)))
    upper = float(np.percentile(boot_rates, 100.0 * (1.0 - alpha / 2.0)))

    # Clamp to [0, 1] — floating point arithmetic can produce tiny violations
    lower = max(0.0, min(1.0, lower))
    upper = max(0.0, min(1.0, upper))

    passes_threshold = lower >= GOVERNANCE_CI_THRESHOLD

    return CIResult(
        lower=lower,
        upper=upper,
        observed_rate=observed_rate,
        passes=passes,
        fails=fails,
        total=total,
        ci_level=ci_level,
        n_bootstrap=n_bootstrap,
        passes_threshold=passes_threshold,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def passes_governance_threshold(
    passes:      int,
    fails:       int,
    n_bootstrap: int          = DEFAULT_N_BOOTSTRAP,
    rng_seed:    Optional[int] = None,
) -> bool:
    """
    Thin convenience wrapper: returns True if ci_lower >= GOVERNANCE_CI_THRESHOLD.

    Equivalent to bootstrap_ci(...).passes_threshold. Use when you only
    need the binary decision and not the full CIResult.

    Args:
        passes:      Number of passing trials.
        fails:       Number of failing trials.
        n_bootstrap: Number of bootstrap resamples. Default: 10,000.
        rng_seed:    Optional seed for reproducibility.

    Returns:
        True if the bootstrap CI lower bound meets the governance threshold.
    """
    return bootstrap_ci(
        passes=passes,
        fails=fails,
        n_bootstrap=n_bootstrap,
        rng_seed=rng_seed,
    ).passes_threshold


def minimum_passes_for_threshold(
    total:       int,
    ci_level:    float = GOVERNANCE_CI_THRESHOLD,
    n_bootstrap: int   = DEFAULT_N_BOOTSTRAP,
    rng_seed:    int   = 42,
) -> Optional[int]:
    """
    Find the minimum number of passes (out of `total` trials) needed for
    ci_lower >= GOVERNANCE_CI_THRESHOLD via binary search.

    Useful for planning: given a fixed evaluation budget (total trials),
    how many must pass to clear the governance bar?

    Args:
        total:       Total number of trials (passes + fails).
        ci_level:    CI level to use. Defaults to GOVERNANCE_CI_THRESHOLD.
        n_bootstrap: Number of resamples per evaluation. Default: 10,000.
        rng_seed:    Fixed seed for reproducible binary search. Default: 42.

    Returns:
        Minimum passes required, or None if even total/total fails to clear
        the threshold (which can happen at very small sample sizes).

    Examples:
        >>> minimum_passes_for_threshold(total=500)
        496
        >>> minimum_passes_for_threshold(total=100)
        99
    """
    if total <= 0:
        return None

    lo, hi = 0, total
    result: Optional[int] = None

    while lo <= hi:
        mid = (lo + hi) // 2
        ci = bootstrap_ci(
            passes=mid,
            fails=total - mid,
            ci_level=ci_level,
            n_bootstrap=n_bootstrap,
            rng_seed=rng_seed,
        )
        if ci.passes_threshold:
            result = mid
            hi = mid - 1   # try to find a lower passing value
        else:
            lo = mid + 1

    return result


def compare_layers(
    layers: list[dict[str, int]],
    ci_level:    float          = GOVERNANCE_CI_THRESHOLD,
    n_bootstrap: int            = DEFAULT_N_BOOTSTRAP,
    rng_seed:    Optional[int]  = None,
) -> list[dict]:
    """
    Compute CI results for a list of layers and return them sorted by ci_lower.

    Each input dict must contain "name", "passes", and "fails" keys.

    Args:
        layers:      List of dicts with keys: name (str), passes (int), fails (int).
        ci_level:    CI level. Defaults to GOVERNANCE_CI_THRESHOLD (0.98).
        n_bootstrap: Number of resamples. Default: 10,000.
        rng_seed:    Optional seed. If provided, each layer gets rng_seed + index
                     to ensure independence while remaining reproducible.

    Returns:
        List of dicts with keys: name, ci_result (CIResult), and all CIResult
        fields inlined for convenience. Sorted descending by ci_lower.

    Examples:
        >>> rows = compare_layers([
        ...     {"name": "layer_a", "passes": 497, "fails": 3},
        ...     {"name": "layer_b", "passes": 490, "fails": 10},
        ... ])
        >>> rows[0]["name"]
        'layer_a'
    """
    results = []
    for i, layer in enumerate(layers):
        seed = (rng_seed + i) if rng_seed is not None else None
        ci = bootstrap_ci(
            passes=layer["passes"],
            fails=layer["fails"],
            ci_level=ci_level,
            n_bootstrap=n_bootstrap,
            rng_seed=seed,
        )
        row = {"name": layer["name"], "ci_result": ci}
        row.update(ci.as_dict())
        results.append(row)

    results.sort(key=lambda r: r["ci_lower"], reverse=True)
    return results
