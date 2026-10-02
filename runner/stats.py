"""Robust summary statistics for repeated timings."""
from __future__ import annotations

import statistics


def percentile(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(runs: list[float], noisy_pct: float = 10.0) -> dict:
    med = statistics.median(runs)
    iqr = percentile(runs, 0.75) - percentile(runs, 0.25)
    iqr_pct = (iqr / med * 100.0) if med > 0 else 0.0
    return {"median_ms": med, "min_ms": min(runs), "p95_ms": percentile(runs, 0.95),
            "iqr_pct": round(iqr_pct, 3), "noisy": iqr_pct > noisy_pct}
