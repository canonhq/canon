"""Health score algorithm — composite metric of Canon value in an organization."""

from __future__ import annotations


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _normalize(value: float, in_lo: float, in_hi: float) -> float:
    if in_hi == in_lo:
        return 50.0
    return (value - in_lo) / (in_hi - in_lo) * 100


def _normalize_centered(value: float, lo: float, mid: float, hi: float) -> float:
    """Normalize so that mid maps to 50, lo maps to 0, hi maps to 100."""
    if value <= mid:
        if mid == lo:
            return 50.0
        return (value - lo) / (mid - lo) * 50.0
    else:
        if hi == mid:
            return 50.0
        return 50.0 + (value - mid) / (hi - mid) * 50.0


def compute_momentum(this_week, prev_week, four_wk_avg) -> float:
    if prev_week == 0 and this_week == 0:
        return 50.0
    if prev_week == 0:
        prev_week = max(this_week * 0.5, 1)
    if four_wk_avg == 0:
        four_wk_avg = max(this_week * 0.5, 1)
    wow = _clamp(this_week / prev_week, 0.5, 2.0)
    trend = _clamp(this_week / four_wk_avg, 0.5, 2.0)
    raw = wow * 0.6 + trend * 0.4
    return _normalize_centered(raw, 0.5, 1.0, 2.0)


def compute_freshness(specs: list[dict]) -> float | None:
    if not specs:
        return None
    total_weight = sum(s["ac_count"] for s in specs)
    if total_weight == 0:
        return None
    weighted_sum = 0.0
    for s in specs:
        gap = s["staleness_gap"]
        freshness = 100.0 if gap <= 7 else max(0.0, 100.0 - (gap - 7) * 5)
        weighted_sum += freshness * s["ac_count"]
    return weighted_sum / total_weight


def compute_time_to_ship(current_cycle: float, baseline_cycle: float) -> float:
    if baseline_cycle == 0:
        return 50.0
    if current_cycle == 0:
        return None
    ratio = _clamp(baseline_cycle / current_cycle, 0.5, 2.0)
    return _normalize_centered(ratio, 0.5, 1.0, 2.0)


def compute_health_score(momentum, freshness, time_to_ship) -> float | None:
    pillars = [(momentum, 0.35), (freshness, 0.30), (time_to_ship, 0.35)]
    available = [(s, w) for s, w in pillars if s is not None]
    if not available:
        return None
    total_weight = sum(w for _, w in available)
    return sum(s * w / total_weight for s, w in available)


def score_label(score: float | None) -> str:
    if score is None:
        return "Insufficient data"
    if score >= 80:
        return "Excellent"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Growing"
    return "Getting Started"
