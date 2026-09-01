from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from core_models import MarketRegimeSnapshot
from scoring_utils import clip, scale, weighted


US_SECTOR_PROXY = {
    "technology": "XLK", "financial services": "XLF", "financial": "XLF",
    "healthcare": "XLV", "consumer cyclical": "XLY", "consumer defensive": "XLP",
    "communication services": "XLC", "communication": "XLC", "energy": "XLE",
    "industrials": "XLI", "basic materials": "XLB", "real estate": "XLRE", "utilities": "XLU",
}
KR_GLOBAL_PROXY = {
    "technology": "^SOX", "semiconductors": "^SOX", "financial services": "^KS11",
    "consumer cyclical": "^KS11", "healthcare": "^KS11", "industrials": "^KS11",
    "basic materials": "^KS11", "energy": "CL=F",
}


def market_for_symbol(symbol: str) -> str:
    return "KR" if symbol.upper().endswith((".KS", ".KQ")) else "US"


def _trend_score(close: pd.Series) -> float:
    c = close.dropna().astype(float)
    if len(c) < 55:
        return 50.0
    ma20 = c.rolling(20).mean().iloc[-1]
    ma50 = c.rolling(50).mean().iloc[-1]
    slope50 = (c.rolling(50).mean().iloc[-1] / c.rolling(50).mean().iloc[-11] - 1) * 100
    return weighted([
        (scale(c.iloc[-1] / ma50 - 1, -.08, .12), .50),
        (scale(ma20 / ma50 - 1, -.05, .07), .30),
        (scale(slope50, -4, 6), .20),
    ])


def _series(loader: Callable, symbol: str, period: str = "8mo", as_of=None) -> pd.Series:
    try:
        d = loader(symbol, period)
        c = d["Close"].dropna()
        if as_of is not None:
            c = c.loc[pd.to_datetime(c.index).date <= pd.Timestamp(as_of).date()]
        return c
    except Exception:
        return pd.Series(dtype=float)


def build_market_regime(symbol: str, sector: str | None, loader: Callable, as_of=None) -> MarketRegimeSnapshot:
    region = market_for_symbol(symbol)
    sector_key = (sector or "").lower()
    components: dict[str, float] = {}
    states: dict[str, str] = {}

    if region == "US":
        specs = [
            ("Broad Market", "^GSPC", .22),
            ("Growth / Tech", "^NDX", .18),
            ("Credit", "HYG", .13),
            ("Sector", US_SECTOR_PROXY.get(sector_key, "SPY"), .17),
        ]
        weighted_parts = []
        for label, ticker, weight in specs:
            c = _series(loader, ticker, as_of=as_of)
            if not c.empty:
                sc = _trend_score(c); components[label] = round(sc, 1); weighted_parts.append((sc, weight))
        vix = _series(loader, "^VIX", "3mo", as_of)
        if not vix.empty:
            v = float(vix.iloc[-1]); sc = clip(82 - max(v - 13, 0) * 3.0)
            components["Volatility"] = round(sc, 1); states["Volatility"] = "Calm" if v < 17 else "Normal" if v < 23 else "Elevated" if v < 30 else "Stress"
            weighted_parts.append((sc, .15))
        dxy = _series(loader, "DX-Y.NYB", "6mo", as_of)
        if len(dxy) >= 22:
            ch = (dxy.iloc[-1] / dxy.iloc[-22] - 1) * 100
            sc = scale(ch, -5, 6, reverse=True); components["Dollar / Liquidity"] = round(sc, 1); weighted_parts.append((sc, .07))
        lqd = _series(loader, "LQD", "6mo", as_of)
        hyg = _series(loader, "HYG", "6mo", as_of)
        if len(lqd) >= 22 and len(hyg) >= 22:
            spread_proxy = (hyg.iloc[-1] / hyg.iloc[-22] - lqd.iloc[-1] / lqd.iloc[-22]) * 100
            sc = scale(spread_proxy, -3, 3); components["Credit Breadth"] = round(sc, 1); weighted_parts.append((sc, .08))
        score = weighted(weighted_parts)
        label = "Risk-On" if score >= 72 else "Risk-On / Selective" if score >= 62 else "Mixed" if score >= 48 else "Risk-Off" if score >= 35 else "Stress"
        states["Regime"] = label
        interpretation = f"미국 시장은 {label} 상태입니다. 광범위 지수·성장주·섹터·변동성·신용·달러 흐름을 분리해 평가했습니다."
    else:
        specs = [
            ("KOSPI", "^KS11", .24),
            ("KOSDAQ", "^KQ11", .10),
            ("US Tech Lead", "^NDX", .10),
            ("Global Sector", KR_GLOBAL_PROXY.get(sector_key, "^GSPC"), .18),
            ("Global Risk", "HYG", .08),
        ]
        weighted_parts = []
        for label, ticker, weight in specs:
            c = _series(loader, ticker, as_of=as_of)
            if not c.empty:
                sc = _trend_score(c); components[label] = round(sc, 1); weighted_parts.append((sc, weight))
        fx = _series(loader, "KRW=X", "6mo", as_of)
        if len(fx) >= 22:
            fx_ch = (fx.iloc[-1] / fx.iloc[-22] - 1) * 100
            sc = scale(fx_ch, -4, 6, reverse=True)
            components["USD/KRW"] = round(sc, 1); states["FX"] = "KRW Supportive" if fx_ch < 0 else "KRW Weakening"
            weighted_parts.append((sc, .14))
        vix = _series(loader, "^VIX", "3mo", as_of)
        if not vix.empty:
            v = float(vix.iloc[-1]); sc = clip(82 - max(v - 13, 0) * 3.0)
            components["Global Volatility"] = round(sc, 1); states["Volatility"] = "Calm" if v < 17 else "Normal" if v < 23 else "Elevated" if v < 30 else "Stress"
            weighted_parts.append((sc, .10))
        sox = _series(loader, "^SOX", "6mo", as_of)
        if not sox.empty and "semi" in sector_key:
            sc = _trend_score(sox); components["SOX Driver"] = round(sc, 1); weighted_parts.append((sc, .06))
        score = weighted(weighted_parts)
        label = "Risk-On" if score >= 72 else "Supportive / Selective" if score >= 62 else "Mixed" if score >= 48 else "Risk-Off" if score >= 35 else "Stress"
        states["Regime"] = label
        interpretation = f"한국 시장은 {label} 상태입니다. 국내 지수뿐 아니라 원·달러와 미국 기술주/글로벌 섹터 흐름을 외부 드라이버로 함께 반영했습니다."

    quality = min(1.0, len(components) / (6 if region == "US" else 7))
    return MarketRegimeSnapshot(region, round(clip(score), 1), label, components, states, round(quality, 2), interpretation)
