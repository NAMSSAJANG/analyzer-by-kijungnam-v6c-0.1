from __future__ import annotations

from core_models import CompanySnapshot, ConsensusSnapshot, MarketRegimeSnapshot, SetupSnapshot, TechnicalSnapshot


def _score_direction(score: float | None, positive: float = 65, negative: float = 45) -> int:
    if score is None:
        return 0
    return 1 if score >= positive else -1 if score < negative else 0


def _option_direction(label: str | None) -> int:
    text = (label or "").lower()
    if "bull" in text or "positive" in text:
        return 1
    if "bear" in text or "negative" in text:
        return -1
    return 0


def build_consensus_v2(
    company: CompanySnapshot,
    tech: TechnicalSnapshot,
    setups: SetupSnapshot,
    market: MarketRegimeSnapshot,
    option_label: str | None = None,
    option_quality: float | None = None,
) -> ConsensusSnapshot:
    lenses: dict[str, str] = {}
    directions: dict[str, int] = {}
    qualities: list[float] = []

    if company.score is not None:
        directions["Company"] = _score_direction(company.score)
        lenses["Company"] = "Strong" if company.score >= 75 else "Good" if company.score >= 65 else "Neutral" if company.score >= 45 else "Weak"
        qualities.append(company.coverage)
    directions["Trend"] = _score_direction(tech.trend)
    lenses["Trend"] = "Strong" if tech.trend >= 75 else "Good" if tech.trend >= 65 else "Neutral" if tech.trend >= 45 else "Weak"
    qualities.append(1.0)

    if setups.preferred == "No Clear Setup":
        setup_dir = -1 if max(setups.pullback.score, setups.momentum.score) < 50 else 0
    else:
        setup_dir = 1
    directions["Setup"] = setup_dir
    lenses["Setup"] = setups.preferred
    qualities.append(1.0)

    directions["Market"] = _score_direction(market.score, 62, 45)
    lenses["Market"] = market.label
    qualities.append(market.data_quality)

    if option_label and option_label != "N/A":
        directions["Options"] = _option_direction(option_label)
        lenses["Options"] = option_label
        qualities.append(max(0.0, min(1.0, option_quality if option_quality is not None else .6)))

    values = list(directions.values())
    positive = sum(v > 0 for v in values)
    negative = sum(v < 0 for v in values)
    neutral = sum(v == 0 for v in values)
    available = len(values)
    dominant = max(positive, negative, neutral) if values else 0
    signal_agreement = round(100 * dominant / max(available, 1))
    data_confidence = round(100 * sum(qualities) / max(len(qualities), 1))

    if positive >= max(3, available - 1):
        pattern = "Broad Alignment"
        headline = f"{positive} / {available} Supportive"
    elif directions.get("Company", 0) > 0 and directions.get("Trend", 0) > 0 and directions.get("Setup", 0) <= 0:
        pattern = "Quality vs Timing"
        headline = "Strong Stock · Setup Incomplete"
    elif directions.get("Trend", 0) > 0 and directions.get("Market", 0) < 0:
        pattern = "Market Conflict"
        headline = "Stock Strength · Market Headwind"
    elif "Options" in directions and directions["Options"] < 0 and positive >= 2:
        pattern = "Options Divergence"
        headline = "Spot Strength · Options Caution"
    elif negative >= max(3, available - 1):
        pattern = "Broad Weakness"
        headline = "Weak Alignment"
    else:
        pattern = "Mixed"
        headline = "Mixed / Selective"

    if pattern == "Broad Alignment":
        interpretation = "기업·추세·진입·시장 렌즈가 대체로 같은 방향입니다. 다만 Risk 패널과 무효화 기준은 별도로 적용해야 합니다."
    elif pattern == "Quality vs Timing":
        interpretation = "종목 자체와 추세는 우호적이지만 현재 진입 Setup이 충분히 성숙하지 않았습니다. 좋은 종목과 좋은 가격을 구분해서 보세요."
    elif pattern == "Market Conflict":
        interpretation = "개별 종목의 상대강도는 좋지만 시장환경이 역풍입니다. 비중을 줄이고 지지 확인을 더 엄격하게 적용하는 편이 유리합니다."
    elif pattern == "Options Divergence":
        interpretation = "현물 구조는 우호적이지만 옵션시장이 경계하고 있습니다. 옵션은 보조 확인값으로 사용하고 가격·거래량 반응을 우선 확인하세요."
    elif pattern == "Broad Weakness":
        interpretation = "여러 렌즈가 동시에 약해 신규 진입보다 구조 회복을 먼저 확인하는 편이 낫습니다."
    else:
        interpretation = "렌즈 간 방향이 섞여 있습니다. 단일 종합점수보다 Preferred Setup과 Risk 상태를 우선해서 해석하세요."

    return ConsensusSnapshot(positive, available, signal_agreement, data_confidence, headline, pattern, interpretation, lenses)
