from __future__ import annotations

from core_models import MarketRegimeSnapshot, RiskSnapshot, TechnicalSnapshot
from scoring_utils import clip, scale, weighted


def build_risk_snapshot(tech: TechnicalSnapshot, market: MarketRegimeSnapshot, earnings_days: int | None = None) -> RiskSnapshot:
    ext_metric = max(tech.dist_ema20_atr, 0) + max(tech.rsi - 70, 0) / 8
    extension_risk = scale(ext_metric, .5, 3.5)
    extension = "Normal" if extension_risk < 35 else "Elevated" if extension_risk < 65 else "High" if extension_risk < 85 else "Extreme"

    vol_risk = scale(tech.atr_pct, 1.3, 7.0)
    volatility = "Low" if vol_risk < 25 else "Normal" if vol_risk < 50 else "Elevated" if vol_risk < 75 else "Extreme"

    if earnings_days is None or earnings_days < 0:
        earnings_risk = 20.0; earnings = "Unknown / Normal"
    elif earnings_days <= 2:
        earnings_risk = 95.0; earnings = f"Event Risk · D-{earnings_days}"
    elif earnings_days <= 7:
        earnings_risk = 78.0; earnings = f"Earnings Soon · D-{earnings_days}"
    elif earnings_days <= 21:
        earnings_risk = 45.0; earnings = f"Upcoming · D-{earnings_days}"
    else:
        earnings_risk = 20.0; earnings = f"Normal · D-{earnings_days}"

    if tech.dollar_volume >= 100_000_000:
        liquidity_risk, liquidity = 10.0, "High"
    elif tech.dollar_volume >= 20_000_000:
        liquidity_risk, liquidity = 25.0, "Normal"
    elif tech.dollar_volume >= 5_000_000:
        liquidity_risk, liquidity = 50.0, "Thin"
    else:
        liquidity_risk, liquidity = 78.0, "Weak"

    market_risk = 100 - market.score
    market_state = "Low" if market_risk < 30 else "Moderate" if market_risk < 55 else "High"
    score = weighted([
        (extension_risk, .34), (vol_risk, .22), (earnings_risk, .20), (liquidity_risk, .10), (market_risk, .14)
    ])
    level = "LOW" if score < 30 else "MODERATE" if score < 55 else "HIGH" if score < 75 else "EXTREME"
    multiplier = 1.0 if score < 30 else .75 if score < 55 else .50 if score < 75 else .25
    details = {
        "Extension": f"EMA20 대비 {tech.dist_ema20_atr:+.2f} ATR · RSI {tech.rsi:.1f}",
        "Volatility": f"ATR {tech.atr_pct:.2f}%",
        "Earnings": earnings,
        "Liquidity": f"20일 평균 거래대금 약 {tech.dollar_volume:,.0f}",
        "Market": f"{market.market} Regime {market.label} · {market.score:.1f}",
    }
    return RiskSnapshot(round(clip(score), 1), level, extension, volatility, earnings, liquidity, market_state, multiplier, details)
