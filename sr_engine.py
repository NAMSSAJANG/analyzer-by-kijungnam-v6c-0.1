from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core_models import PriceZone, TechnicalSnapshot
from scoring_utils import clip


@dataclass(frozen=True)
class ZoneSet:
    supports: tuple[PriceZone, ...]
    resistances: tuple[PriceZone, ...]


def _pivots(frame: pd.DataFrame, left: int = 3, right: int = 3) -> list[tuple[float, str]]:
    d = frame.tail(180)
    highs = d["High"].astype(float)
    lows = d["Low"].astype(float)
    out: list[tuple[float, str]] = []
    for i in range(left, len(d) - right):
        if highs.iloc[i] >= highs.iloc[i-left:i+right+1].max():
            out.append((float(highs.iloc[i]), "Swing High"))
        if lows.iloc[i] <= lows.iloc[i-left:i+right+1].min():
            out.append((float(lows.iloc[i]), "Swing Low"))
    return out[-24:]


def _volume_nodes(frame: pd.DataFrame, bins: int = 18) -> list[tuple[float, str]]:
    d = frame.tail(120).dropna(subset=["Close"]).copy()
    if d.empty or "Volume" not in d:
        return []
    lo, hi = float(d["Low"].min()), float(d["High"].max())
    if hi <= lo:
        return []
    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2
    idx = np.clip(np.digitize(d["Close"].astype(float), edges) - 1, 0, bins - 1)
    volume = np.zeros(bins)
    for bucket, vol in zip(idx, d["Volume"].fillna(0).astype(float)):
        volume[int(bucket)] += max(vol, 0)
    if volume.max() <= 0:
        return []
    strongest = np.argsort(volume)[-3:]
    return [(float(centers[i]), "Volume Node") for i in strongest]


def build_zones(frame: pd.DataFrame, tech: TechnicalSnapshot, option_put_wall: float | None = None, option_call_wall: float | None = None) -> ZoneSet:
    d = frame.dropna(subset=["Close"]).copy()
    now = float(d["Close"].iloc[-1])
    tolerance = max(tech.atr * .65, now * .008)
    candidates: list[tuple[float, str, float]] = []
    candidates.extend((p, s, 1.0) for p, s in _pivots(d))
    candidates.extend((p, s, 1.15) for p, s in _volume_nodes(d))
    candidates.extend([
        (tech.ema20, "EMA20", 1.10),
        (tech.ema50, "EMA50", 1.20),
        (tech.ema200, "EMA200", 1.00),
        (tech.prior_high20, "20D Breakout", 1.10),
        (tech.prior_high60, "60D Breakout", 1.25),
        (float(d["Low"].tail(20).min()), "20D Low", 1.0),
        (float(d["Low"].tail(50).min()), "50D Low", 1.0),
        (float(d["High"].tail(252).max()), "52W High", 1.15),
    ])
    if option_put_wall is not None and np.isfinite(option_put_wall):
        candidates.append((float(option_put_wall), "Put Wall", 1.35))
    if option_call_wall is not None and np.isfinite(option_call_wall):
        candidates.append((float(option_call_wall), "Call Wall", 1.35))

    clusters: list[list[tuple[float, str, float]]] = []
    for item in sorted(candidates, key=lambda x: x[0]):
        if not np.isfinite(item[0]) or item[0] <= 0:
            continue
        if not clusters or abs(item[0] - np.mean([x[0] for x in clusters[-1]])) > tolerance:
            clusters.append([item])
        else:
            clusters[-1].append(item)

    supports: list[PriceZone] = []
    resistances: list[PriceZone] = []
    for cluster in clusters:
        prices = [x[0] for x in cluster]
        sources = tuple(dict.fromkeys(x[1] for x in cluster))
        weights = [x[2] for x in cluster]
        center = float(np.average(prices, weights=weights))
        low, high = center - tolerance * .42, center + tolerance * .42
        raw_strength = 34 + 13 * len(sources) + 8 * sum(w - 1 for w in weights)
        strength = clip(raw_strength)
        label = "Strong" if strength >= 75 else "Medium" if strength >= 55 else "Weak"
        kind = "support" if center <= now else "resistance"
        zone = PriceZone(kind, round(low, 4), round(high, 4), round(center, 4), round(strength, 1), label, sources)
        (supports if kind == "support" else resistances).append(zone)

    supports.sort(key=lambda z: z.center, reverse=True)
    resistances.sort(key=lambda z: z.center)
    return ZoneSet(tuple(supports[:5]), tuple(resistances[:5]))
