from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from core_models import CompanySnapshot, MarketRegimeSnapshot, PriceZone, TechnicalSnapshot
from scoring_utils import clip, finite, scale, weighted


def build_quant_snapshot(
    frame: pd.DataFrame,
    company: CompanySnapshot,
    tech: TechnicalSnapshot,
    market: MarketRegimeSnapshot,
    supports: tuple[PriceZone, ...] | list[PriceZone] = (),
    resistances: tuple[PriceZone, ...] | list[PriceZone] = (),
) -> dict:
    """Explainability layer for V6.

    Quant Composite intentionally excludes Market Regime from its score so it does
    not duplicate Opportunity. Market is shown as a separate CAN SLIM/context lens.
    """
    quant_score = weighted([
        (company.score, .35),
        (tech.trend, .25),
        (tech.momentum, .15),
        (tech.demand, .10),
        (tech.relative_strength, .15),
    ])

    d = frame.dropna(subset=["Close"]).copy()
    c = d["Close"].astype(float)
    v = d.get("Volume", pd.Series(0.0, index=d.index)).fillna(0).astype(float)
    now = float(c.iloc[-1])
    high52 = float(c.tail(252).max())
    low52 = float(c.tail(252).min())
    pos52 = (now - low52) / max(high52 - low52, 1e-9) * 100

    raw = company.raw
    earnings_growth = raw.get("earnings_growth")
    revenue_growth = raw.get("revenue_growth")
    roe = raw.get("roe")

    c_score = weighted([
        (scale(earnings_growth, -10, 40) if finite(earnings_growth) else None, .70),
        (scale(revenue_growth, -5, 30) if finite(revenue_growth) else None, .30),
    ]) if finite(earnings_growth) or finite(revenue_growth) else None
    a_score = weighted([
        (company.factors.get("Profitability"), .65),
        (scale(roe, 0, 30) if finite(roe) else None, .35),
    ]) if company.factors.get("Profitability") is not None or finite(roe) else None
    n_score = weighted([(tech.trend, .55), (scale(pos52, 35, 98), .45)])
    s_score = weighted([(scale(tech.volume_ratio, .55, 1.8), .45), (tech.demand, .55)])
    l_score = weighted([(tech.relative_strength, .65), (tech.trend, .35)])
    i_score = tech.demand
    m_score = market.score
    can_slim = {"C": c_score, "A": a_score, "N": n_score, "S": s_score, "L": l_score, "I": i_score, "M": m_score}

    target = None
    if resistances:
        candidates = [z.center for z in resistances if z.center > now]
        if candidates:
            target = min(candidates)
    target_factor = 50.0 if target is None else clip(50 + (target / now - 1) * 220)

    mean_reversion = clip(50 - tech.z60 * 18)
    drawdown_safety = clip(100 - abs(min(tech.drawdown_from_high60, 0)) * 2.0)
    extension_balance = clip(100 - max(tech.dist_ema20_atr, 0) * 22 - max(tech.rsi - 72, 0) * 2)
    aux = {
        "평균회귀": mean_reversion,
        "모멘텀": tech.momentum,
        "다중 시간대": tech.trend,
        "낙폭 위치": drawdown_safety,
        "수급 흐름": tech.demand,
        "Target Price Factor": target_factor,
        "통계적 Z-Score": clip(50 - tech.z60 * 15),
        "Relative Strength": tech.relative_strength,
        "Extension Balance": extension_balance,
    }

    # Extra indicator series for the detailed chart. These are view-only and do
    # not feed back into V6 scores.
    ema20 = c.ewm(span=20, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    mid = c.rolling(20).mean()
    std = c.rolling(20).std()
    bb_upper = mid + 2 * std
    bb_lower = mid - 2 * std
    typical = (d["High"] + d["Low"] + d["Close"]) / 3
    vwap = (typical * v).cumsum() / v.cumsum().replace(0, np.nan)
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    return {
        "score": round(float(quant_score), 1),
        "factors": {
            "Company Quality": company.score,
            "Trend": tech.trend,
            "Momentum": tech.momentum,
            "Demand / Supply": tech.demand,
            "Relative Strength": tech.relative_strength,
        },
        "can_slim": {k: None if v is None or not finite(v) else round(float(v), 1) for k, v in can_slim.items()},
        "aux": {k: round(float(v), 1) for k, v in aux.items()},
        "high52": high52,
        "low52": low52,
        "position52": round(pos52, 1),
        "chart": {
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "vwap": vwap,
            "obv": obv,
            "macd": macd,
            "macd_signal": macd_signal,
        },
        "technical_rows": [
            ("RSI (14)", f"{tech.rsi:.1f}", "0~100 강도 지표 · 70 이상은 과열 가능성이 있으나 강한 추세에서는 강도 신호일 수도 있습니다."),
            ("ADX", f"{tech.adx:.1f}", "추세의 방향이 아닌 강도 · 25 이상이면 추세 존재, 40 이상이면 강한 추세로 참고합니다."),
            ("ATR%", f"{tech.atr_pct:.2f}%", "현재가 대비 평균 변동폭 · 높을수록 손절 폭과 비중을 보수적으로 잡아야 합니다."),
            ("EMA20 거리", f"{tech.dist_ema20_atr:+.2f} ATR", "20일선에서 얼마나 확장됐는지 ATR 단위로 봅니다. Pullback과 Momentum에서 해석이 달라집니다."),
            ("12M 수익률", f"{tech.ret_12m:+.1f}%", "장기 가격 리더십 참고값입니다."),
            ("3M 수익률", f"{tech.ret_3m:+.1f}%", "최근 약 3개월의 상승/하락 속도입니다."),
            ("거래량 비율", f"{tech.volume_ratio:.2f}x", "20일 평균 대비 현재 거래량 · 1배는 평균, 1.2배 이상은 비교적 활발합니다."),
            ("OBV 기울기", f"{tech.obv_slope:+.3f}", "거래량 누적 방향의 대용지표입니다. 실제 기관 보유 데이터는 아닙니다."),
            ("MACD 방향", "상승" if macd.iloc[-1] > macd_signal.iloc[-1] else "하락", "MACD가 시그널 위인지 아래인지 확인합니다."),
        ],
    }


def financial_rows(company: CompanySnapshot, info: Mapping) -> list[tuple[str, str, str]]:
    raw = company.raw
    def fmt(v, suffix="", digits=1):
        return "—" if not finite(v) else f"{float(v):,.{digits}f}{suffix}"
    market_cap = info.get("marketCap")
    return [
        ("PER", fmt(raw.get("trailing_pe"), digits=1), "주가÷주당이익 · 업종 성장률과 함께 비교합니다."),
        ("Forward PER", fmt(raw.get("forward_pe"), digits=1), "예상 이익 기준 밸류에이션 · 전망치 변화에 민감합니다."),
        ("PBR", fmt(raw.get("price_to_book"), digits=2), "주가÷주당순자산 · 자산 구조가 다른 업종끼리 단순 비교하지 않습니다."),
        ("ROE", fmt(raw.get("roe"), "%", 1), "자기자본 수익성 · 부채 효과와 함께 확인합니다."),
        ("EPS 성장률", fmt(raw.get("earnings_growth"), "%", 1), "최근 공개 이익 성장률 · 기저효과와 일회성 이익을 확인합니다."),
        ("매출 성장률", fmt(raw.get("revenue_growth"), "%", 1), "최근 공개 매출 성장률입니다."),
        ("영업이익률", fmt(raw.get("operating_margin"), "%", 1), "본업 수익성의 대용지표입니다."),
        ("FCF Margin", fmt(raw.get("fcf_margin"), "%", 1), "매출 대비 잉여현금흐름 비율입니다."),
        ("부채비율", fmt(raw.get("debt_to_equity"), "%", 1), "업종별 기준 차이가 크므로 상대평가와 함께 봅니다."),
        ("시가총액", "—" if not finite(market_cap) else f"{float(market_cap)/1e9:,.1f}B", "Yahoo 원자료의 통화 기준 시장가치입니다."),
    ]
