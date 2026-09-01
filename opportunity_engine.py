from __future__ import annotations

from core_models import CompanySnapshot, MarketRegimeSnapshot, OpportunitySnapshot, TechnicalSnapshot
from scoring_utils import finite, grade, weighted


def build_opportunity(company: CompanySnapshot, tech: TechnicalSnapshot, market: MarketRegimeSnapshot) -> OpportunitySnapshot:
    components = {
        "Company Quality": company.score,
        "Trend / Leadership": tech.trend,
        "Relative Strength": tech.relative_strength,
        "Momentum / Demand": weighted([(tech.momentum, .60), (tech.demand, .40)]),
        "Market Regime": market.score,
    }
    target_weights = {
        "Company Quality": .30,
        "Trend / Leadership": .25,
        "Relative Strength": .15,
        "Momentum / Demand": .15,
        "Market Regime": .15,
    }
    valid = [(components[k], w) for k, w in target_weights.items() if finite(components[k])]
    score = weighted(valid)
    used_sum = sum(w for k, w in target_weights.items() if finite(components[k]))
    weights_used = {k: (w / used_sum if finite(components[k]) and used_sum else 0.0) for k, w in target_weights.items()}
    availability = used_sum
    confidence = 100 * min(1.0, (.55 * availability + .25 * company.coverage + .20 * market.data_quality))
    view = (
        "기업 품질과 가격 리더십이 함께 우호적입니다." if score >= 75
        else "관찰 가치가 높지만 일부 렌즈의 확인이 더 필요합니다." if score >= 65
        else "매력도 신호가 혼재합니다. 진입 Setup과 위험을 별도로 확인해야 합니다." if score >= 50
        else "현재 종목 매력도가 제한적이며 추세·기업·시장 중 약한 축의 개선이 필요합니다."
    )
    return OpportunitySnapshot(round(score, 1), grade(score), components, weights_used, round(confidence, 0), view)
