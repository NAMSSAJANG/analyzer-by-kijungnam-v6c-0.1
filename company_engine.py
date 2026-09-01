from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from core_models import CompanySnapshot
from scoring_utils import finite, percentile_score, scale, weighted


def _pct(info: Mapping, key: str) -> float | None:
    value = info.get(key)
    if not finite(value):
        return None
    return float(value) * 100


def _num(info: Mapping, key: str) -> float | None:
    value = info.get(key)
    return float(value) if finite(value) else None


def extract_company_raw(info: Mapping) -> dict[str, float | None]:
    revenue = _num(info, "totalRevenue")
    free_cash_flow = _num(info, "freeCashflow")
    fcf_margin = None if not revenue or not free_cash_flow else free_cash_flow / revenue * 100
    return {
        "revenue_growth": _pct(info, "revenueGrowth"),
        "earnings_growth": _pct(info, "earningsGrowth"),
        "operating_margin": _pct(info, "operatingMargins"),
        "profit_margin": _pct(info, "profitMargins"),
        "roe": _pct(info, "returnOnEquity"),
        "debt_to_equity": _num(info, "debtToEquity"),
        "current_ratio": _num(info, "currentRatio"),
        "trailing_pe": _num(info, "trailingPE"),
        "forward_pe": _num(info, "forwardPE"),
        "price_to_book": _num(info, "priceToBook"),
        "fcf_margin": fcf_margin,
    }


def _absolute_scores(raw: Mapping[str, float | None]) -> dict[str, float | None]:
    return {
        "Growth": weighted([
            (scale(raw.get("revenue_growth"), -5, 30) if finite(raw.get("revenue_growth")) else None, .50),
            (scale(raw.get("earnings_growth"), -10, 35) if finite(raw.get("earnings_growth")) else None, .50),
        ]) if any(finite(raw.get(k)) for k in ("revenue_growth", "earnings_growth")) else None,
        "Profitability": weighted([
            (scale(raw.get("operating_margin"), 0, 30) if finite(raw.get("operating_margin")) else None, .35),
            (scale(raw.get("profit_margin"), 0, 25) if finite(raw.get("profit_margin")) else None, .25),
            (scale(raw.get("roe"), 0, 30) if finite(raw.get("roe")) else None, .40),
        ]) if any(finite(raw.get(k)) for k in ("operating_margin", "profit_margin", "roe")) else None,
        "Balance Sheet": weighted([
            (scale(raw.get("debt_to_equity"), 0, 220, reverse=True) if finite(raw.get("debt_to_equity")) else None, .65),
            (scale(raw.get("current_ratio"), .6, 2.2) if finite(raw.get("current_ratio")) else None, .35),
        ]) if any(finite(raw.get(k)) for k in ("debt_to_equity", "current_ratio")) else None,
        "Cash Flow": scale(raw.get("fcf_margin"), -5, 22) if finite(raw.get("fcf_margin")) else None,
        "Valuation": weighted([
            (scale(raw.get("forward_pe"), 8, 45, reverse=True) if finite(raw.get("forward_pe")) else None, .45),
            (scale(raw.get("trailing_pe"), 8, 50, reverse=True) if finite(raw.get("trailing_pe")) else None, .35),
            (scale(raw.get("price_to_book"), 1, 12, reverse=True) if finite(raw.get("price_to_book")) else None, .20),
        ]) if any(finite(raw.get(k)) for k in ("forward_pe", "trailing_pe", "price_to_book")) else None,
    }


def _peer_relative(raw: Mapping[str, float | None], peer_raw: Sequence[Mapping[str, float | None]]) -> dict[str, float | None]:
    higher_better = {
        "revenue_growth": "Revenue Growth",
        "earnings_growth": "Earnings Growth",
        "operating_margin": "Operating Margin",
        "profit_margin": "Profit Margin",
        "roe": "ROE",
        "fcf_margin": "FCF Margin",
        "current_ratio": "Current Ratio",
    }
    lower_better = {
        "debt_to_equity": "Debt / Equity",
        "forward_pe": "Forward PE",
        "trailing_pe": "Trailing PE",
        "price_to_book": "Price / Book",
    }
    out: dict[str, float | None] = {}
    for key, label in higher_better.items():
        vals = [x.get(key) for x in peer_raw if finite(x.get(key))]
        out[label] = percentile_score(raw.get(key), vals)
    for key, label in lower_better.items():
        vals = [x.get(key) for x in peer_raw if finite(x.get(key))]
        pct = percentile_score(raw.get(key), vals)
        out[label] = None if pct is None else 100 - pct
    return out


def build_company_snapshot(info: Mapping, peer_infos: Sequence[Mapping] | None = None) -> CompanySnapshot:
    raw = extract_company_raw(info)
    absolute = _absolute_scores(raw)
    peer_raw = [extract_company_raw(x) for x in (peer_infos or [])]
    relative = _peer_relative(raw, peer_raw) if peer_raw else {}

    def rel_weight(parts):
        return weighted(parts) if any(finite(v) for v, _ in parts) else None

    rel_groups = {
        "Growth": rel_weight([(relative.get("Revenue Growth"), .5), (relative.get("Earnings Growth"), .5)]) if relative else None,
        "Profitability": rel_weight([(relative.get("Operating Margin"), .35), (relative.get("Profit Margin"), .25), (relative.get("ROE"), .4)]) if relative else None,
        "Balance Sheet": rel_weight([(relative.get("Debt / Equity"), .65), (relative.get("Current Ratio"), .35)]) if relative else None,
        "Cash Flow": relative.get("FCF Margin") if relative else None,
        "Valuation": rel_weight([(relative.get("Forward PE"), .45), (relative.get("Trailing PE"), .35), (relative.get("Price / Book"), .2)]) if relative else None,
    }
    factors: dict[str, float | None] = {}
    for name in absolute:
        abs_score = absolute[name]
        rel_score = rel_groups.get(name)
        if finite(abs_score) and finite(rel_score):
            factors[name] = weighted([(abs_score, .55), (rel_score, .45)])
        elif finite(abs_score):
            factors[name] = float(abs_score)
        elif finite(rel_score):
            factors[name] = float(rel_score)
        else:
            factors[name] = None

    factor_weights = {"Growth": .30, "Profitability": .30, "Balance Sheet": .15, "Cash Flow": .10, "Valuation": .15}
    valid = [(factors[k], w) for k, w in factor_weights.items() if finite(factors[k])]
    score = weighted(valid) if valid else None

    raw_fields = list(raw.values())
    raw_coverage = sum(finite(v) for v in raw_fields) / max(len(raw_fields), 1)
    relative_available = [v for v in relative.values() if finite(v)]
    relative_coverage = len(relative_available) / max(len(relative), 1) if relative else 0.0
    coverage = min(1.0, .80 * raw_coverage + .20 * relative_coverage)
    confidence = "High" if coverage >= .78 else "Medium" if coverage >= .55 else "Low"

    notes = []
    if raw_coverage < .65:
        notes.append("공개 재무 데이터 일부가 제공되지 않아 해당 항목은 점수 계산에서 제외했습니다.")
    if peer_infos and relative_coverage >= .35:
        notes.append("동일/유사 업종 후보군의 상대 순위를 절대평가와 함께 반영했습니다.")
    elif not peer_infos:
        notes.append("업종 상대평가 자료가 없어 절대평가 중심으로 계산했습니다.")
    return CompanySnapshot(
        None if score is None else round(float(score), 1),
        round(coverage, 3), confidence,
        {k: None if v is None or not finite(v) else round(float(v), 1) for k, v in factors.items()},
        raw,
        {k: None if v is None or not finite(v) else round(float(v), 1) for k, v in relative.items()},
        tuple(notes),
    )
