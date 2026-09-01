from __future__ import annotations

import numpy as np
import pandas as pd

from core_models import TechnicalSnapshot
from scoring_utils import clip, scale, weighted


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = -delta.clip(upper=0).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / down.replace(0, np.nan))


def _adx(frame: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series]:
    up = frame["High"].diff()
    dn = -frame["Low"].diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([
        frame["High"] - frame["Low"],
        (frame["High"] - frame["Close"].shift()).abs(),
        (frame["Low"] - frame["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    p = 100 * pd.Series(plus, index=frame.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    m = 100 * pd.Series(minus, index=frame.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    adx = (100 * (p - m).abs() / (p + m).replace(0, np.nan)).ewm(alpha=1 / n, adjust=False).mean()
    return adx, atr


def build_technical_snapshot(frame: pd.DataFrame, benchmark: pd.DataFrame | None = None) -> TechnicalSnapshot:
    d = frame.dropna(subset=["Close"]).copy()
    if len(d) < 210:
        raise ValueError("최소 210거래일의 가격 데이터가 필요합니다.")
    c = d["Close"].astype(float)
    v = d.get("Volume", pd.Series(0.0, index=d.index)).fillna(0).astype(float)
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    rsi_series = _rsi(c)
    adx_series, atr_series = _adx(d)
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()

    def ret(n: int) -> float:
        return float((c.iloc[-1] / c.iloc[-min(n, len(c))] - 1) * 100)

    now = float(c.iloc[-1])
    atr = float(atr_series.iloc[-1])
    atr_pct = atr / max(now, 1e-9) * 100
    rsi = float(rsi_series.iloc[-1])
    adx = float(adx_series.iloc[-1])
    vol_ratio = float(v.iloc[-1] / max(v.tail(20).mean(), 1))
    dollar_volume = float((c.tail(20) * v.tail(20)).mean())
    slope50 = float((ema50.iloc[-1] / ema50.iloc[-21] - 1) * 100)
    slope200 = float((ema200.iloc[-1] / ema200.iloc[-21] - 1) * 100)

    trend = weighted([
        (scale(now / ema200.iloc[-1] - 1, -.15, .25), .22),
        (scale(ema20.iloc[-1] / ema50.iloc[-1] - 1, -.08, .10), .18),
        (scale(ema50.iloc[-1] / ema200.iloc[-1] - 1, -.12, .18), .18),
        (scale(slope50, -6, 10), .14),
        (scale(slope200, -4, 7), .08),
        (scale(ret(126), -25, 50), .10),
        (scale(ret(252), -35, 80), .10),
    ])
    momentum = weighted([
        (scale(rsi, 38, 78), .23),
        (scale(ret(22), -12, 22), .22),
        (scale(ret(66), -20, 40), .25),
        (scale((macd.iloc[-1] - signal.iloc[-1]) / max(now, 1e-9) * 100, -1.5, 1.5), .18),
        (scale(adx, 12, 42), .12),
    ])
    obv20 = obv.tail(20)
    obv_slope = float((obv20.iloc[-1] - obv20.iloc[0]) / max(v.tail(20).sum(), 1))
    up_volume = float(v.tail(20)[c.tail(20).diff() > 0].sum())
    down_volume = float(v.tail(20)[c.tail(20).diff() < 0].sum())
    up_down_ratio = up_volume / max(down_volume, 1)
    demand = weighted([
        (scale(vol_ratio, .55, 2.0), .30),
        (scale(obv_slope, -.25, .35), .35),
        (scale(up_down_ratio, .6, 1.8), .35),
    ])

    relative_strength = 50.0
    if benchmark is not None and not benchmark.empty and "Close" in benchmark:
        b = benchmark["Close"].dropna().astype(float)
        joined = pd.concat([c.rename("stock"), b.rename("bench")], axis=1).dropna()
        if len(joined) >= 66:
            s3 = (joined.stock.iloc[-1] / joined.stock.iloc[-66] - 1) * 100
            b3 = (joined.bench.iloc[-1] / joined.bench.iloc[-66] - 1) * 100
            s6 = (joined.stock.iloc[-1] / joined.stock.iloc[-126] - 1) * 100 if len(joined) >= 126 else s3
            b6 = (joined.bench.iloc[-1] / joined.bench.iloc[-126] - 1) * 100 if len(joined) >= 126 else b3
            relative_strength = weighted([(scale(s3 - b3, -15, 25), .60), (scale(s6 - b6, -25, 40), .40)])

    prior_high20 = float(c.iloc[-21:-1].max())
    prior_high60 = float(c.iloc[-61:-1].max())
    recent_high60 = float(c.tail(60).max())
    drawdown = (now / max(recent_high60, 1e-9) - 1) * 100
    z60 = float((now - c.tail(60).mean()) / max(c.tail(60).std(), 1e-9))
    last_ret = float((c.iloc[-1] / c.iloc[-2] - 1) * 100)
    day_range = float((d["High"].iloc[-1] - d["Low"].iloc[-1]) / max(now, 1e-9) * 100)

    return TechnicalSnapshot(
        trend=round(clip(trend), 1), momentum=round(clip(momentum), 1), demand=round(clip(demand), 1),
        relative_strength=round(clip(relative_strength), 1), rsi=round(rsi, 1), adx=round(adx, 1),
        atr=atr, atr_pct=round(atr_pct, 2), volume_ratio=round(vol_ratio, 2), dollar_volume=dollar_volume,
        ret_1m=round(ret(22), 2), ret_3m=round(ret(66), 2), ret_6m=round(ret(126), 2), ret_12m=round(ret(252), 2),
        ema20=float(ema20.iloc[-1]), ema50=float(ema50.iloc[-1]), ema200=float(ema200.iloc[-1]),
        dist_ema20_atr=round((now - ema20.iloc[-1]) / max(atr, 1e-9), 2),
        dist_ema50_atr=round((now - ema50.iloc[-1]) / max(atr, 1e-9), 2),
        z60=round(z60, 2), prior_high20=prior_high20, prior_high60=prior_high60, recent_high60=recent_high60,
        drawdown_from_high60=round(drawdown, 2), last_day_return=round(last_ret, 2), last_day_range_pct=round(day_range, 2),
        obv_slope=round(obv_slope, 3),
    )
