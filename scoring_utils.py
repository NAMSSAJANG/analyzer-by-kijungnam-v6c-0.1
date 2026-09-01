from __future__ import annotations

import math
from typing import Iterable

import numpy as np


def clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return float(max(low, min(high, value)))


def finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def scale(value: float, low: float, high: float, reverse: bool = False) -> float:
    if not finite(value) or high == low:
        return float("nan")
    score = clip((float(value) - low) / (high - low) * 100)
    return 100 - score if reverse else score


def weighted(parts: Iterable[tuple[float | None, float]], default: float = 50.0) -> float:
    valid = [(float(v), float(w)) for v, w in parts if v is not None and finite(v) and w > 0]
    if not valid:
        return float(default)
    total_w = sum(w for _, w in valid)
    return float(sum(v * w for v, w in valid) / total_w)


def grade(value: float) -> str:
    if value >= 85:
        return "Elite"
    if value >= 75:
        return "Strong"
    if value >= 65:
        return "Good"
    if value >= 50:
        return "Neutral"
    if value >= 35:
        return "Weak"
    return "Very Weak"


def percentile_score(value: float | None, peers: list[float]) -> float | None:
    if value is None or not finite(value):
        return None
    clean = np.array([float(x) for x in peers if finite(x)], dtype=float)
    if len(clean) < 3:
        return None
    return float((clean <= float(value)).mean() * 100)
