from __future__ import annotations

from core_models import EntryTranche, MarketRegimeSnapshot, RiskSnapshot, SetupScore, SetupSnapshot, TechnicalSnapshot
from scoring_utils import clip, scale, weighted
from sr_engine import ZoneSet


def _nearest_support(zones: ZoneSet):
    return zones.supports[0] if zones.supports else None


def _nearest_resistance(zones: ZoneSet):
    return zones.resistances[0] if zones.resistances else None


def _pullback_tranches(support, entry_ref: float, atr: float) -> tuple[EntryTranche, ...]:
    """Ladder INTO a defined support zone (top -> bottom), all sharing the same
    stop below the zone. This is not 'average down indefinitely' — it is
    bounded by the zone's own invalidation level, so buying lower within the
    zone means a better price against the same stop, not a widening risk."""
    if support:
        upper, mid, lower = support.high, support.center, support.low
    else:
        upper, mid, lower = entry_ref + atr * 0.3, entry_ref, entry_ref - atr * 0.3
    return (
        EntryTranche("1차 진입", round(upper, 4), 40.0, "지지 구간 상단에 처음 진입"),
        EntryTranche("2차 진입", round(mid, 4), 30.0, "지지 구간 중심까지 눌릴 때 추가"),
        EntryTranche("3차 진입", round(lower, 4), 30.0, "지지 구간 하단까지 눌렸을 때 마지막 물량 추가"),
    )


def _momentum_tranches(trigger: float, atr: float) -> tuple[EntryTranche, ...]:
    """Pyramid UP as a breakout proves itself, rather than committing full size
    at the first tick above the trigger."""
    t1, t2, t3 = trigger, trigger + atr * 0.6, trigger + atr * 1.4
    return (
        EntryTranche("1차 진입", round(t1, 4), 40.0, "돌파 트리거 가격에 최초 진입"),
        EntryTranche("2차 진입", round(t2, 4), 30.0, "돌파 이후 상승이 유지되는지 확인하며 추가"),
        EntryTranche("3차 진입", round(t3, 4), 30.0, "후속 상승이 이어질 때 마지막 물량 추가"),
    )


def _targets_from_resistance(entry_ref: float, zones: ZoneSet, atr: float, mult1: float, mult2: float) -> tuple[float, float]:
    """Pick 1st/2nd target prices above entry_ref from known resistance zones,
    falling back to ATR multiples when structure is not available so a target
    is always shown rather than left blank."""
    above = [z for z in zones.resistances if z.center > entry_ref]
    t1 = above[0].center if above else entry_ref + max(atr, entry_ref * .004) * mult1
    remaining = [z for z in above if z.center > t1 + atr * .3]
    t2 = remaining[0].center if remaining else max(t1 + atr * (mult2 - mult1), entry_ref + atr * mult2)
    return t1, t2


def _risk_reward(entry_ref: float, stop: float | None, target: float) -> float | None:
    if stop is None:
        return None
    risk = entry_ref - stop
    if risk <= 0:
        return None
    return round((target - entry_ref) / risk, 2)


def build_setups(now: float, tech: TechnicalSnapshot, market: MarketRegimeSnapshot, zones: ZoneSet, risk: RiskSnapshot) -> SetupSnapshot:
    support = _nearest_support(zones)
    resistance = _nearest_resistance(zones)

    if support:
        support_distance_atr = abs(now - support.center) / max(tech.atr, 1e-9)
        support_proximity = clip(100 - support_distance_atr * 34 + (support.strength - 50) * .20)
    else:
        support_distance_atr = 99
        support_proximity = 35.0

    ema_position = weighted([
        (scale(abs(tech.dist_ema20_atr), 0, 2.3, reverse=True), .60),
        (scale(abs(tech.dist_ema50_atr), 0, 3.5, reverse=True), .40),
    ])
    drawdown_abs = abs(tech.drawdown_from_high60)
    # Healthy pullbacks are usually neither zero nor deep breakdowns. Reward a
    # moderate 4~7% reset instead of treating deeper drawdowns as automatically better.
    depth = clip(100 - abs(drawdown_abs - 5.5) * 12)
    if drawdown_abs < 1.0:
        depth = min(depth, 35.0)
    elif drawdown_abs > 16:
        depth = min(depth, 25.0)
    volume_pullback = scale(tech.volume_ratio, .55, 1.10, reverse=True)
    if tech.last_day_return > 0 and tech.volume_ratio >= 1.0:
        volume_pullback = max(volume_pullback, 68)
    # Pullback stabilization differs from momentum strength: mid-range RSI and
    # decelerated-but-intact momentum are desirable here.
    rsi_stable = clip(100 - abs(tech.rsi - 52) * 4.0)
    momentum_reset = clip(100 - abs(tech.momentum - 55) * 1.8)
    momentum_stable = weighted([(rsi_stable, .55), (momentum_reset, .45)])
    pull_factors = {
        "Trend Quality": tech.trend,
        "Support Proximity": support_proximity,
        "EMA Position": ema_position,
        "Pullback Depth": depth,
        "Volume Pattern": volume_pullback,
        "Momentum Stabilization": momentum_stable,
        "Market": market.score,
    }
    pull_score = weighted([
        (pull_factors["Trend Quality"], .20), (pull_factors["Support Proximity"], .25),
        (pull_factors["EMA Position"], .15), (pull_factors["Pullback Depth"], .15),
        (pull_factors["Volume Pattern"], .10), (pull_factors["Momentum Stabilization"], .10),
        (pull_factors["Market"], .05),
    ])
    invalidation = support.low - tech.atr * .55 if support else min(tech.ema50, now - tech.atr * 1.5)
    if tech.trend < 40 or now < tech.ema200:
        pull_status = "INVALIDATED"
    elif risk.extension in ("High", "Extreme") and support_distance_atr > 1.5:
        pull_status = "NOT IN ZONE"
    elif pull_score >= 78 and support_distance_atr <= 1.25:
        pull_status = "READY"
    elif pull_score >= 62:
        pull_status = "DEVELOPING"
    elif support_distance_atr > 2.5:
        pull_status = "NOT IN ZONE"
    else:
        pull_status = "STRUCTURE WARNING" if tech.trend < 55 else "NOT IN ZONE"

    breakout20 = (now / max(tech.prior_high20, 1e-9) - 1) * 100
    breakout60 = (now / max(tech.prior_high60, 1e-9) - 1) * 100
    breakout = weighted([
        (scale(breakout20, -4, 4), .45),
        (scale(breakout60, -5, 5), .55),
    ])
    if now >= tech.prior_high60 and tech.volume_ratio >= 1.2:
        breakout = max(breakout, 86)
    volume_confirm = weighted([(scale(tech.volume_ratio, .7, 2.0), .75), (tech.demand, .25)])
    mom_factors = {
        "Trend Strength": tech.trend,
        "Breakout": breakout,
        "Momentum": tech.momentum,
        "Volume Confirmation": volume_confirm,
        "Relative Strength": tech.relative_strength,
        "Market": market.score,
    }
    mom_score = weighted([
        (mom_factors["Trend Strength"], .25), (mom_factors["Breakout"], .20),
        (mom_factors["Momentum"], .20), (mom_factors["Volume Confirmation"], .15),
        (mom_factors["Relative Strength"], .10), (mom_factors["Market"], .10),
    ])
    trigger = max(tech.prior_high20, tech.prior_high60)
    mom_invalidation = min(trigger - tech.atr * .65, tech.ema20 - tech.atr * .35)
    if tech.trend < 45 and breakout < 45:
        mom_status = "FAILED BREAKOUT"
    elif risk.extension in ("High", "Extreme") and mom_score >= 65:
        mom_status = "EXTENDED"
    elif mom_score >= 80 and now >= trigger and tech.volume_ratio >= 1.1:
        mom_status = "CONFIRMED"
    elif mom_score >= 68 and breakout >= 60:
        mom_status = "EARLY BREAKOUT"
    else:
        mom_status = "WATCH"

    pull_details = {
        "Trend Quality": f"Trend {tech.trend:.1f}",
        "Support Proximity": f"가까운 지지까지 {support_distance_atr:.2f} ATR" if support else "신뢰 가능한 지지 Zone 부족",
        "EMA Position": f"EMA20 {tech.dist_ema20_atr:+.2f} ATR · EMA50 {tech.dist_ema50_atr:+.2f} ATR",
        "Pullback Depth": f"60일 고점 대비 {tech.drawdown_from_high60:.1f}%",
        "Volume Pattern": f"20일 평균 대비 거래량 {tech.volume_ratio:.2f}x",
        "Momentum Stabilization": f"RSI {tech.rsi:.1f} · Momentum {tech.momentum:.1f}",
        "Market": f"{market.label} {market.score:.1f}",
    }
    mom_details = {
        "Trend Strength": f"Trend {tech.trend:.1f}",
        "Breakout": f"20D {breakout20:+.1f}% · 60D {breakout60:+.1f}%",
        "Momentum": f"Momentum {tech.momentum:.1f} · RSI {tech.rsi:.1f}",
        "Volume Confirmation": f"거래량 {tech.volume_ratio:.2f}x · Demand {tech.demand:.1f}",
        "Relative Strength": f"시장 대비 RS {tech.relative_strength:.1f}",
        "Market": f"{market.label} {market.score:.1f}",
    }
    pull_entry_ref = support.center if support else now
    pull_target1, pull_target2 = _targets_from_resistance(pull_entry_ref, zones, tech.atr, 2.2, 3.8)
    pull_risk_pct = (pull_entry_ref - invalidation) / pull_entry_ref * 100 if pull_entry_ref > 0 else None
    pull = SetupScore("Pullback", round(clip(pull_score), 1), pull_status, pull_factors, pull_details,
                      invalidation=round(invalidation, 4), zone=(support.low, support.high) if support else None,
                      entry_price=round(pull_entry_ref, 4), stop_loss=round(invalidation, 4),
                      target1=round(pull_target1, 4), target2=round(pull_target2, 4),
                      risk_reward1=_risk_reward(pull_entry_ref, invalidation, pull_target1),
                      risk_reward2=_risk_reward(pull_entry_ref, invalidation, pull_target2),
                      risk_pct=round(pull_risk_pct, 2) if pull_risk_pct is not None else None,
                      tranches=_pullback_tranches(support, pull_entry_ref, tech.atr))

    mom_entry_ref = max(now, trigger)
    mom_target1, mom_target2 = _targets_from_resistance(mom_entry_ref, zones, tech.atr, 2.5, 4.2)
    mom_risk_pct = (mom_entry_ref - mom_invalidation) / mom_entry_ref * 100 if mom_entry_ref > 0 else None
    momentum = SetupScore("Momentum", round(clip(mom_score), 1), mom_status, mom_factors, mom_details,
                          trigger=round(trigger, 4), invalidation=round(mom_invalidation, 4),
                          zone=(resistance.low, resistance.high) if resistance else None,
                          entry_price=round(mom_entry_ref, 4), stop_loss=round(mom_invalidation, 4),
                          target1=round(mom_target1, 4), target2=round(mom_target2, 4),
                          risk_reward1=_risk_reward(mom_entry_ref, mom_invalidation, mom_target1),
                          risk_reward2=_risk_reward(mom_entry_ref, mom_invalidation, mom_target2),
                          risk_pct=round(mom_risk_pct, 2) if mom_risk_pct is not None else None,
                          tranches=_momentum_tranches(trigger, tech.atr))

    actionable_pull = pull.status in ("READY", "DEVELOPING") and pull.score >= 62
    actionable_mom = momentum.status in ("CONFIRMED", "EARLY BREAKOUT", "EXTENDED") and momentum.score >= 62
    if actionable_pull and actionable_mom and abs(pull.score - momentum.score) < 8:
        preferred = "Both Valid"
    elif actionable_mom and momentum.score >= pull.score + 4:
        preferred = "Momentum Preferred"
    elif actionable_pull:
        preferred = "Pullback Preferred"
    elif actionable_mom:
        preferred = "Momentum Preferred"
    else:
        preferred = "No Clear Setup"
    summary = (
        "눌림목과 모멘텀 진입이 모두 유효합니다. 가격 반응에 따라 더 가까운 Setup을 선택하세요." if preferred == "Both Valid"
        else "가격 위치보다 추세·돌파의 지속성이 우세해 Momentum 접근이 더 적합합니다." if preferred == "Momentum Preferred"
        else "강한 구조를 유지하면서 지지 Zone에 가까워 Pullback 접근이 더 유리합니다." if preferred == "Pullback Preferred"
        else "현재는 명확한 신규 진입 Setup이 부족합니다. 지지 형성 또는 돌파 확인을 기다리는 편이 낫습니다."
    )
    return SetupSnapshot(pull, momentum, preferred, summary)
