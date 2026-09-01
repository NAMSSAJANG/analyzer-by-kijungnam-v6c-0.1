from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class CompanySnapshot:
    score: float | None
    coverage: float
    confidence: str
    factors: Mapping[str, float | None]
    raw: Mapping[str, float | None]
    relative: Mapping[str, float | None] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class TechnicalSnapshot:
    trend: float
    momentum: float
    demand: float
    relative_strength: float
    rsi: float
    adx: float
    atr: float
    atr_pct: float
    volume_ratio: float
    dollar_volume: float
    ret_1m: float
    ret_3m: float
    ret_6m: float
    ret_12m: float
    ema20: float
    ema50: float
    ema200: float
    dist_ema20_atr: float
    dist_ema50_atr: float
    z60: float
    prior_high20: float
    prior_high60: float
    recent_high60: float
    drawdown_from_high60: float
    last_day_return: float
    last_day_range_pct: float
    obv_slope: float


@dataclass(frozen=True)
class MarketRegimeSnapshot:
    market: str
    score: float
    label: str
    components: Mapping[str, float]
    states: Mapping[str, str]
    data_quality: float
    interpretation: str


@dataclass(frozen=True)
class PriceZone:
    kind: str
    low: float
    high: float
    center: float
    strength: float
    label: str
    sources: tuple[str, ...]


@dataclass(frozen=True)
class SetupScore:
    name: str
    score: float
    status: str
    factors: Mapping[str, float]
    details: Mapping[str, str]
    trigger: float | None = None
    invalidation: float | None = None
    zone: tuple[float, float] | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    target1: float | None = None
    target2: float | None = None
    risk_reward1: float | None = None
    risk_reward2: float | None = None
    risk_pct: float | None = None


@dataclass(frozen=True)
class SetupSnapshot:
    pullback: SetupScore
    momentum: SetupScore
    preferred: str
    summary: str


@dataclass(frozen=True)
class RiskSnapshot:
    score: float
    level: str
    extension: str
    volatility: str
    earnings: str
    liquidity: str
    market: str
    position_size_multiplier: float
    details: Mapping[str, str]


@dataclass(frozen=True)
class OpportunitySnapshot:
    score: float
    grade: str
    components: Mapping[str, float | None]
    weights_used: Mapping[str, float]
    data_confidence: float
    interpretation: str


@dataclass(frozen=True)
class ConsensusSnapshot:
    supportive: int
    available: int
    signal_agreement: int
    data_confidence: int
    headline: str
    pattern: str
    interpretation: str
    lenses: Mapping[str, str]
