from __future__ import annotations

import numpy as np
import pandas as pd

from core_models import MarketRegimeSnapshot
from risk_engine import build_risk_snapshot
from setup_engine import build_setups
from sr_engine import build_zones
from technical_engine import build_technical_snapshot


EPISODE_RESET_DAYS = 3
HORIZONS = (5, 10, 20, 60)
PRIMARY_HORIZON = 20
MAX_CALIBRATION_WINDOW = 420
MIN_TECH_HISTORY = 230
CALIBRATION_LOGIC_VERSION = "v614"


def _episode_metadata(mask: pd.Series, reset_days: int = EPISODE_RESET_DAYS) -> tuple[np.ndarray, np.ndarray]:
    """Return episode ids and setup-start flags for qualifying rows.

    Qualifying rows that are interrupted by fewer than `reset_days` below-threshold
    rows remain part of the same setup episode. A genuinely new episode starts only
    after the score has stayed below threshold for at least `reset_days` rows.

    Episode ids are assigned only to qualifying rows; non-qualifying rows receive 0.
    """
    values = mask.fillna(False).to_numpy(dtype=bool)
    episode_ids = np.zeros(len(values), dtype=int)
    starts = np.zeros(len(values), dtype=bool)

    current_episode = 0
    in_episode = False
    below_run = reset_days

    for idx, is_signal in enumerate(values):
        if is_signal:
            if not in_episode and below_run >= reset_days:
                current_episode += 1
                starts[idx] = True
                in_episode = True
            episode_ids[idx] = current_episode
            below_run = 0
        else:
            if in_episode:
                below_run += 1
                if below_run >= reset_days:
                    in_episode = False
            else:
                below_run = min(reset_days, below_run + 1)

    return episode_ids, starts


def _spaced_qualified_indices(mask: pd.Series, outcome: pd.Series, min_gap: int) -> list[int]:
    """Select non-overlapping-ish validation dates from all qualifying days.

    Unlike the older episode-start-only method, this may select multiple validation
    dates from one long setup episode when they are separated by at least `min_gap`
    trading rows. This is important for low thresholds (e.g. 30-50), where a stock
    can remain above the threshold for months and would otherwise misleadingly look
    like it has too few validation cases.
    """
    m = mask.fillna(False).to_numpy(dtype=bool)
    valid_outcome = pd.to_numeric(outcome, errors="coerce").notna().to_numpy(dtype=bool)
    candidates = np.flatnonzero(m & valid_outcome)
    if len(candidates) == 0:
        return []

    selected = [int(candidates[0])]
    last = selected[0]
    for idx in candidates[1:]:
        idx = int(idx)
        if idx - last >= min_gap:
            selected.append(idx)
            last = idx
    return selected


def _episode_concentration(episode_ids: np.ndarray, positions: list[int]) -> tuple[int, float]:
    """Return number of represented episodes and largest episode share (%)."""
    if not positions:
        return 0, np.nan
    ids = [int(episode_ids[i]) for i in positions if int(episode_ids[i]) > 0]
    if not ids:
        return 0, np.nan
    counts = pd.Series(ids).value_counts()
    return int(len(counts)), float(counts.iloc[0] / len(ids) * 100)


def run_setup_calibration(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame | None = None,
    threshold: float = 75.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Price-only historical validation for Entry Engine V3.

    Important definitions
    ---------------------
    * threshold=40 means Entry Score >= 40 (40-100), not "around 40".
    * Qualifying day: any historical row with Pullback/Momentum score >= threshold.
    * Setup episode: a broader regime of qualifying rows. The episode ends only
      after at least 3 consecutive below-threshold calibration rows.
    * Validation date: a qualifying date selected for a given forward horizon.
      Validation dates are spaced by that horizon (5/10/20/60 trading rows) to
      reduce overlapping outcome windows. One long episode can therefore provide
      multiple validation dates if it persists long enough.
    * Reference price: the validation date's close, not necessarily the episode start.

    Fundamental data is excluded to avoid point-in-time leakage. Historical Market
    Regime is held neutral (50) until a true point-in-time regime store is available.
    """
    d = frame.dropna(subset=["Close"]).copy()
    if len(d) < 330:
        raise ValueError("Calibration requires at least ~330 trading days.")

    rows: list[dict] = []
    neutral_market = MarketRegimeSnapshot(
        "CAL", 50.0, "Neutral", {"Calibration": 50.0}, {"Regime": "Neutral"},
        1.0, "Calibration neutral market"
    )

    start = max(MIN_TECH_HISTORY, len(d) - MAX_CALIBRATION_WINDOW)
    end = len(d)  # Keep recent rows; each horizon separately filters unavailable outcomes.

    for i in range(start, end):
        hist = d.iloc[: i + 1]
        bench_hist = None
        if benchmark is not None and not benchmark.empty:
            bench_hist = benchmark.loc[benchmark.index <= hist.index[-1]]
        try:
            tech = build_technical_snapshot(hist, bench_hist)
            risk = build_risk_snapshot(tech, neutral_market, None)
            zones = build_zones(hist, tech)
            now = float(hist["Close"].iloc[-1])
            setups = build_setups(now, tech, neutral_market, zones, risk)
        except Exception:
            continue

        forward: dict[int, float] = {}
        for horizon in HORIZONS:
            if i + horizon < len(d):
                forward[horizon] = (float(d["Close"].iloc[i + horizon]) / now - 1) * 100
            else:
                forward[horizon] = np.nan

        if i + PRIMARY_HORIZON < len(d):
            future20 = d["Close"].iloc[i + 1 : i + PRIMARY_HORIZON + 1].astype(float)
            mdd20 = ((future20 / now) - 1).min() * 100 if len(future20) == PRIMARY_HORIZON else np.nan
        else:
            mdd20 = np.nan

        rows.append({
            "date": pd.Timestamp(hist.index[-1]).date().isoformat(),
            "close": now,
            "pullback": setups.pullback.score,
            "momentum": setups.momentum.score,
            "pullback_status": setups.pullback.status,
            "momentum_status": setups.momentum.status,
            "fwd_5d": forward[5],
            "fwd_10d": forward[10],
            "fwd_20d": forward[20],
            "fwd_60d": forward[60],
            "mdd_20d": mdd20,
        })

    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail, pd.DataFrame()

    summary_rows: list[dict] = []
    for name, col, prefix in (
        ("Pullback", "pullback", "pullback"),
        ("Momentum", "momentum", "momentum"),
    ):
        mask = pd.to_numeric(detail[col], errors="coerce") >= float(threshold)
        episode_ids, setup_starts = _episode_metadata(mask, reset_days=EPISODE_RESET_DAYS)

        detail[f"{prefix}_qualified"] = mask.to_numpy(dtype=bool)
        detail[f"{prefix}_episode"] = episode_ids
        detail[f"{prefix}_setup_start"] = setup_starts

        sample_positions: dict[int, list[int]] = {}
        sample_frames: dict[int, pd.DataFrame] = {}
        for horizon in HORIZONS:
            positions = _spaced_qualified_indices(mask, detail[f"fwd_{horizon}d"], min_gap=horizon)
            sample_positions[horizon] = positions
            flag = np.zeros(len(detail), dtype=bool)
            if positions:
                flag[positions] = True
            detail[f"{prefix}_sample_{horizon}d"] = flag
            sample_frames[horizon] = detail.iloc[positions].copy() if positions else detail.iloc[0:0].copy()

        sig20 = sample_frames[20]
        n20 = int(len(sig20))
        positive20 = int((sig20["fwd_20d"] > 0).sum()) if n20 else 0
        represented_eps20, max_ep_share20 = _episode_concentration(episode_ids, sample_positions[20])

        def avg_for(h: int) -> float:
            s = sample_frames[h]
            return float(s[f"fwd_{h}d"].mean()) if not s.empty else np.nan

        summary_rows.append({
            "Setup": name,
            "Threshold": float(threshold),
            "Signals": int(mask.sum()),
            "Episodes": int(setup_starts.sum()),
            "Validation 5D": int(len(sample_frames[5])),
            "Validation 10D": int(len(sample_frames[10])),
            "Validation 20D": n20,
            "Validation 60D": int(len(sample_frames[60])),
            "Validation Episodes 20D": represented_eps20,
            "Max Episode Share 20D": max_ep_share20,
            "Positive 20D": positive20,
            "Hit 20D": float(positive20 / n20 * 100) if n20 else np.nan,
            "Median 20D": float(sig20["fwd_20d"].median()) if n20 else np.nan,
            "Avg 5D": avg_for(5),
            "Avg 10D": avg_for(10),
            "Avg 20D": avg_for(20),
            "Avg 60D": avg_for(60),
            "Avg MDD20": float(sig20["mdd_20d"].mean()) if n20 else np.nan,
            "Episode Reset Days": EPISODE_RESET_DAYS,
            "Sample Gap 5D": 5,
            "Sample Gap 10D": 10,
            "Sample Gap 20D": 20,
            "Sample Gap 60D": 60,
            "Logic Version": CALIBRATION_LOGIC_VERSION,
        })

    return detail, pd.DataFrame(summary_rows)
