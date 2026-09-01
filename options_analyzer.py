from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


@dataclass(frozen=True)
class OptionSummary:
    call_volume: int
    put_volume: int
    call_oi: int
    put_oi: int
    volume_ratio: float
    oi_ratio: float
    call_iv: float
    put_iv: float
    atm_iv: float
    call_wall: float | None
    put_wall: float | None
    max_pain: float | None
    expected_move: float
    expected_low: float
    expected_high: float
    confirmation: str
    interpretation: str
    data_quality: float


@dataclass(frozen=True)
class OptionEntry:
    score: float
    factors: dict[str, float]
    interpretation: str
    details: dict[str, str]


def _number(value, default=0.0) -> float:
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def _total(frame: pd.DataFrame, column: str) -> int:
    if column not in frame:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).clip(lower=0).sum())


def _weighted_iv(frame: pd.DataFrame) -> float:
    if frame.empty or "impliedVolatility" not in frame:
        return float("nan")
    iv = pd.to_numeric(frame["impliedVolatility"], errors="coerce")
    weights = pd.to_numeric(frame.get("openInterest", 1), errors="coerce").fillna(0).clip(lower=0)
    valid = iv.between(0.001, 10) & iv.notna()
    if not valid.any():
        return float("nan")
    weights = weights[valid]
    return float(np.average(iv[valid], weights=weights)) if weights.sum() else float(iv[valid].median())


def _oi_wall(frame: pd.DataFrame) -> float | None:
    if frame.empty or not {"strike", "openInterest"}.issubset(frame.columns):
        return None
    oi = pd.to_numeric(frame["openInterest"], errors="coerce").fillna(0)
    if oi.max() <= 0:
        return None
    return float(pd.to_numeric(frame.loc[oi.idxmax(), "strike"], errors="coerce"))


def _atm_row(frame: pd.DataFrame, spot: float) -> pd.Series | None:
    if frame.empty or "strike" not in frame:
        return None
    strikes = pd.to_numeric(frame["strike"], errors="coerce")
    valid = strikes.notna()
    return frame.loc[(strikes[valid] - spot).abs().idxmin()] if valid.any() else None


def calculate_max_pain(calls: pd.DataFrame, puts: pd.DataFrame) -> float | None:
    """Settlement strike that minimizes aggregate intrinsic payout."""
    if calls.empty and puts.empty:
        return None
    def normalized(frame: pd.DataFrame) -> pd.DataFrame:
        strikes = pd.to_numeric(frame["strike"], errors="coerce") if "strike" in frame else pd.Series(index=frame.index, dtype=float)
        oi = pd.to_numeric(frame["openInterest"], errors="coerce").fillna(0) if "openInterest" in frame else pd.Series(0.0, index=frame.index)
        return frame.assign(strike=strikes, oi=oi).dropna(subset=["strike"])
    c, p = normalized(calls), normalized(puts)
    strikes = sorted(set(c.strike) | set(p.strike))
    if not strikes or c.oi.sum() + p.oi.sum() <= 0:
        return None
    payouts = {s: ((s - c.strike).clip(lower=0) * c.oi).sum() + ((p.strike - s).clip(lower=0) * p.oi).sum() for s in strikes}
    return float(min(payouts, key=payouts.get))


def summarize_options(calls: pd.DataFrame, puts: pd.DataFrame, spot: float, expiry: str, today: date | None = None) -> OptionSummary:
    call_volume, put_volume = _total(calls, "volume"), _total(puts, "volume")
    call_oi, put_oi = _total(calls, "openInterest"), _total(puts, "openInterest")
    volume_ratio = put_volume / call_volume if call_volume else float("nan")
    oi_ratio = put_oi / call_oi if call_oi else float("nan")
    call_iv, put_iv = _weighted_iv(calls), _weighted_iv(puts)
    call_atm, put_atm = _atm_row(calls, spot), _atm_row(puts, spot)
    atm_ivs = [_number(row.get("impliedVolatility"), float("nan")) for row in (call_atm, put_atm) if row is not None]
    atm_ivs = [x for x in atm_ivs if math.isfinite(x) and x > 0]
    fallback_ivs = [x for x in (call_iv, put_iv) if math.isfinite(x)]
    atm_iv = float(np.mean(atm_ivs)) if atm_ivs else (float(np.mean(fallback_ivs)) if fallback_ivs else float("nan"))
    today = today or datetime.now().date()
    days = max((datetime.strptime(expiry, "%Y-%m-%d").date() - today).days, 1)
    # ATM straddle is the most intuitive expiry move; IV is a robust fallback for sparse quotes.
    premiums = []
    for row in (call_atm, put_atm):
        if row is None:
            continue
        mid = (_number(row.get("bid")) + _number(row.get("ask"))) / 2
        premiums.append(mid if mid > 0 else _number(row.get("lastPrice")))
    straddle_move = sum(premiums) if len(premiums) == 2 and all(x > 0 for x in premiums) else 0
    iv_move = spot * atm_iv * math.sqrt(days / 365) if math.isfinite(atm_iv) else 0
    expected_move = straddle_move or iv_move
    ratios = [x for x in (volume_ratio, oi_ratio) if math.isfinite(x)]
    blended = float(np.mean(ratios)) if ratios else 1.0
    if blended <= 0.75:
        confirmation = "Bullish confirmation"
        direction = "콜 활동이 상대적으로 우세합니다."
    elif blended >= 1.25:
        confirmation = "Bearish / hedge-heavy"
        direction = "풋 활동이 상대적으로 높아 하방 경계 또는 헤지 수요가 관찰됩니다."
    else:
        confirmation = "Neutral confirmation"
        direction = "콜과 풋 활동이 대체로 균형적입니다."
    volatility = "내재변동성이 높아 가격 변동 폭이 클 수 있습니다." if math.isfinite(atm_iv) and atm_iv >= .50 else "내재변동성은 극단적으로 높지 않습니다."
    interpretation = f"{direction} {volatility} 옵션은 헤지·스프레드 거래도 포함하므로 방향을 단정하는 신호가 아니라 현물 분석의 보조 확인값으로 해석하세요."
    available_fields = sum(x > 0 for x in (call_volume + put_volume, call_oi + put_oi, expected_move)) + int(math.isfinite(atm_iv))
    quality = available_fields / 4
    return OptionSummary(call_volume, put_volume, call_oi, put_oi, volume_ratio, oi_ratio, call_iv, put_iv, atm_iv,
                         _oi_wall(calls), _oi_wall(puts), calculate_max_pain(calls, puts), expected_move,
                         max(0, spot - expected_move), spot + expected_move, confirmation, interpretation, quality)


def option_bias(summary: OptionSummary) -> str:
    ratios = [value for value in (summary.volume_ratio, summary.oi_ratio) if math.isfinite(value)]
    if not ratios:
        return "Neutral"
    blended = float(np.mean(ratios))
    if blended <= .65:
        return "Bullish"
    if blended <= .90:
        return "Mild Bullish"
    if blended < 1.10:
        return "Neutral"
    if blended < 1.50:
        return "Mild Bearish"
    return "Bearish"


def bias_style(bias: str) -> tuple[str, str]:
    return {
        "Bullish": ("🟢", "#22c55e"),
        "Mild Bullish": ("🟢", "#34d399"),
        "Neutral": ("🟡", "#fbbf24"),
        "Mild Bearish": ("🔴", "#fb7185"),
        "Bearish": ("🔴", "#ef4444"),
    }.get(bias, ("⚪", "#94a3b8"))


def option_entry_readiness(summary: OptionSummary, calls: pd.DataFrame, puts: pd.DataFrame, spot: float, expiry: str) -> OptionEntry:
    bias = option_bias(summary)
    direction = {"Bullish": 88, "Mild Bullish": 72, "Neutral": 50, "Mild Bearish": 68, "Bearish": 82}[bias]
    total_oi, total_volume = summary.call_oi + summary.put_oi, summary.call_volume + summary.put_volume
    activity = min(100, 18 * math.log10(max(total_oi, 1)) + 12 * math.log10(max(total_volume, 1)))
    spreads = []
    for frame in (calls, puts):
        if not {"strike", "bid", "ask"}.issubset(frame.columns): continue
        nearby = frame.loc[(pd.to_numeric(frame["strike"], errors="coerce")-spot).abs().nsmallest(5).index]
        for _, row in nearby.iterrows():
            bid, ask = _number(row.get("bid")), _number(row.get("ask")); mid = (bid + ask) / 2
            if mid > 0 and ask >= bid: spreads.append((ask-bid)/mid)
    median_spread = float(np.median(spreads)) if spreads else .5
    spread_score = max(0, 100 - median_spread * 180)
    liquidity = .6 * activity + .4 * spread_score
    iv_efficiency = 50 if not math.isfinite(summary.atm_iv) else max(0, min(100, 100-summary.atm_iv*100))
    if bias in ("Bullish", "Mild Bullish"):
        reward = summary.call_wall-spot if summary.call_wall and summary.call_wall>spot else summary.expected_move
        risk = spot-summary.put_wall if summary.put_wall and summary.put_wall<spot else summary.expected_move
    elif bias in ("Bearish", "Mild Bearish"):
        reward = spot-summary.put_wall if summary.put_wall and summary.put_wall<spot else summary.expected_move
        risk = summary.call_wall-spot if summary.call_wall and summary.call_wall>spot else summary.expected_move
    else: reward=risk=summary.expected_move
    rr = reward/max(risk,1e-9) if reward>0 else 0
    risk_reward = max(0,min(100,35+rr*30))
    days=max((datetime.strptime(expiry,"%Y-%m-%d").date()-datetime.now().date()).days,1)
    time_decay=max(0,min(100,(days-5)/40*100))
    factors={"Direction":direction,"IV Efficiency":iv_efficiency,"Liquidity":liquidity,"Risk / Reward":risk_reward,"Time / DTE":time_decay}
    details={
        "Direction":f"Option Bias {bias}를 진입 방향 확인도로 변환했습니다.",
        "IV Efficiency":f"ATM IV {_fmt_iv(summary.atm_iv)}입니다. IV가 높을수록 매수 프리미엄 부담을 크게 봅니다.",
        "Liquidity":f"총 OI {total_oi:,}, 거래량 {total_volume:,}, 근접 행사가 중간 호가 스프레드 {median_spread*100:.1f}%를 반영합니다.",
        "Risk / Reward":f"주요 OI Wall과 예상 변동범위의 보상/위험 비율 {rr:.2f}배를 반영합니다.",
        "Time / DTE":f"선택 만기까지 {days}일입니다. 5일 이하는 시간가치 감소 위험을 가장 높게 봅니다.",
    }
    weights={"Direction":.30,"IV Efficiency":.15,"Liquidity":.25,"Risk / Reward":.20,"Time / DTE":.10}
    score=round(sum(factors[k]*weights[k] for k in factors),1)
    if liquidity<45: note="방향성보다 유동성 부족과 넓은 호가가 우선 위험요인입니다."
    elif iv_efficiency<45 and bias in ("Bullish","Mild Bullish"): note="상승 방향성은 있지만 IV와 프리미엄 부담이 높아 단순 Call보다 손익이 제한된 스프레드 구조를 함께 비교할 환경입니다."
    elif time_decay<40: note="만기가 짧아 시간가치 감소 민감도가 높으므로 포지션 유지기간을 보수적으로 봐야 합니다."
    else: note="방향성·유동성·만기 구조가 대체로 균형적이지만 최대손실과 손익분기점을 별도로 확인해야 합니다."
    return OptionEntry(score,{k:round(v,1) for k,v in factors.items()},note,details)


def price_confluence(summary: OptionSummary, support: float | None, resistance: float | None, spot: float) -> tuple[str, str]:
    tolerance = max(abs(spot) * .025, 1e-9)
    support_match = support is not None and summary.put_wall is not None and abs(support - summary.put_wall) <= tolerance
    resistance_match = resistance is not None and summary.call_wall is not None and abs(resistance - summary.call_wall) <= tolerance
    if support_match and resistance_match:
        return "HIGH CONFLUENCE", "기술적 지지·저항과 옵션 주요 Strike가 모두 근접합니다."
    if support_match or resistance_match:
        return "PARTIAL CONFLUENCE", "한쪽 주요 가격대가 일치하며 다른 구간은 추가 확인이 필요합니다."
    return "DIVERGENCE", "기술적 가격대와 옵션 OI 집중 구간이 달라 단기 반응을 확인할 필요가 있습니다."


def get_option_snapshot(symbol: str, spot: float, expiry: str | None = None):
    if symbol.upper().endswith((".KS", ".KQ")):
        return None, None, None, ()
    expirations = option_expirations(symbol)
    if not expirations:
        return None, None, None, ()
    selected = expiry if expiry in expirations else expirations[0]
    calls, puts = option_chain(symbol, selected)
    if calls.empty and puts.empty:
        return None, None, None, expirations
    return summarize_options(calls, puts, spot, selected), calls, puts, expirations


@st.cache_data(ttl=900, show_spinner=False)
def option_expirations(symbol: str) -> tuple[str, ...]:
    return tuple(yf.Ticker(symbol).options or ())


@st.cache_data(ttl=300, show_spinner=False)
def option_chain(symbol: str, expiry: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    chain = yf.Ticker(symbol).option_chain(expiry)
    return chain.calls.copy(), chain.puts.copy()


def _fmt_ratio(value: float) -> str:
    return "—" if not math.isfinite(value) else f"{value:.2f}"


def _fmt_iv(value: float) -> str:
    return "—" if not math.isfinite(value) else f"{value * 100:.1f}%"


def _oi_chart(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> go.Figure:
    def nearby(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["strike"] = pd.to_numeric(out.get("strike"), errors="coerce")
        out["openInterest"] = pd.to_numeric(out.get("openInterest"), errors="coerce").fillna(0)
        out = out.dropna(subset=["strike"])
        if out.empty:
            return out
        window = out.iloc[(out["strike"] - spot).abs().argsort()[:24]]
        return window.sort_values("strike")
    c, p = nearby(calls), nearby(puts)
    fig = go.Figure()
    fig.add_bar(x=c.get("strike", []), y=c.get("openInterest", []), name="Call OI", marker_color="#38bdf8")
    fig.add_bar(x=p.get("strike", []), y=p.get("openInterest", []), name="Put OI", marker_color="#fb7185")
    fig.add_vline(x=spot, line_dash="dot", line_color="#f8fafc", annotation_text="현재가")
    fig.update_layout(barmode="group", height=390, margin=dict(l=10, r=10, t=35, b=10), xaxis_title="Strike", yaxis_title="Open Interest",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", legend_orientation="h")
    return fig


def render_options(symbol: str, spot: float, money, support=None, resistance=None) -> None:
    st.header(f"옵션분석 · {symbol}")
    st.caption("옵션 거래 추천이 아닌 현물 분석 보완용 정보입니다. 옵션 신호는 기존 종합점수에 반영되지 않습니다.")
    if symbol.upper().endswith((".KS", ".KQ")):
        st.info("KOSPI·KOSDAQ 종목은 현재 사용 중인 무료 데이터 소스에서 개별 종목 옵션 체인을 제공하지 않습니다. 종합분석·퀀트분석·시장환경은 계속 정상적으로 이용할 수 있습니다.")
        return
    try:
        expirations = option_expirations(symbol)
    except Exception:
        expirations = ()
    if not expirations:
        st.info("이 종목에서 이용 가능한 옵션 만기를 찾지 못했습니다. 옵션 미상장 종목이거나 데이터 제공이 일시적으로 제한된 경우입니다. 다른 분석 탭에는 영향이 없습니다.")
        return
    expiry = st.selectbox("만기 선택", expirations, format_func=lambda x: f"{x} · {(datetime.strptime(x, '%Y-%m-%d').date() - datetime.now().date()).days}일")
    try:
        summary, calls, puts, _ = get_option_snapshot(symbol, spot, expiry)
        if summary is None: raise ValueError("empty option chain")
    except Exception:
        st.warning("선택한 만기의 옵션 체인을 현재 불러올 수 없습니다. 잠시 후 다시 시도하거나 다른 만기를 선택해 주세요. 기존 분석 기능은 정상적으로 사용할 수 있습니다.")
        return
    st.subheader("Options Market Summary")
    bias = option_bias(summary)
    bias_icon, bias_color = bias_style(bias)
    st.markdown(f"<div style='border:1px solid {bias_color};border-left:5px solid {bias_color};border-radius:14px;padding:14px 16px;background:#0d1b2d;margin-bottom:12px'><div style='color:#94a3b8;font-size:.78rem;font-weight:800;letter-spacing:.1em'>OPTION MARKET BIAS</div><div style='color:{bias_color};font-size:1.45rem;font-weight:850;margin-top:5px'>{bias_icon} {bias}</div></div>", unsafe_allow_html=True)
    cols = st.columns(4)
    cols[0].metric("Option Bias", f"{bias_icon} {bias}")
    cols[1].metric("ATM Implied Volatility", _fmt_iv(summary.atm_iv))
    cols[2].metric("Put / Call Volume", _fmt_ratio(summary.volume_ratio))
    cols[3].metric("Put / Call OI", _fmt_ratio(summary.oi_ratio))
    st.caption(f"Option Confirmation: {summary.confirmation} · Option Confidence: {summary.data_quality * 100:.0f}% (데이터 충실도 기반)")
    entry=option_entry_readiness(summary,calls,puts,spot,expiry)
    st.subheader(f"OPTION ENTRY · {entry.score:.1f} / 100")
    entry_rows=[]
    for name,value in entry.factors.items():
        icon="🟢" if value>=65 else "🟡" if value>=45 else "🔴"
        entry_rows.append({"요소":name,"점수":value,"상태":icon,"해석":entry.details[name]})
    st.dataframe(pd.DataFrame(entry_rows),hide_index=True,use_container_width=True,
                 column_config={"점수":st.column_config.ProgressColumn("점수",min_value=0,max_value=100,format="%.1f")})
    st.info(f"**AI 판단** · {entry.interpretation} Option Entry는 옵션시장 방향이 아니라 현재 체인의 진입 준비도를 나타내며 기존 종합점수에는 반영되지 않습니다.")
    st.info(summary.interpretation)
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Call / Put Activity")
        table = pd.DataFrame({"구분": ["Call", "Put"], "Volume": [summary.call_volume, summary.put_volume],
                              "Open Interest": [summary.call_oi, summary.put_oi], "평균 IV": [_fmt_iv(summary.call_iv), _fmt_iv(summary.put_iv)]})
        st.dataframe(table, hide_index=True, use_container_width=True)
    with c2:
        st.subheader("Expected Move")
        st.metric(f"{expiry} 만기 예상 변동폭", f"± {money(summary.expected_move)}")
        st.metric("옵션시장 예상 범위", f"{money(summary.expected_low)} ~ {money(summary.expected_high)}")
        if math.isfinite(summary.atm_iv):
            move7 = spot * summary.atm_iv * math.sqrt(7 / 365)
            move30 = spot * summary.atm_iv * math.sqrt(30 / 365)
            st.caption(f"7D IV 범위 {money(max(0, spot-move7))} ~ {money(spot+move7)} · 30D IV 범위 {money(max(0, spot-move30))} ~ {money(spot+move30)}")
        st.caption("ATM 콜·풋의 중간가격 합계를 우선 사용하고, 호가가 부족하면 ATM IV 기반 1표준편차 범위를 사용합니다.")
    st.subheader("IV State")
    iv_state = "Elevated" if math.isfinite(summary.atm_iv) and summary.atm_iv >= .50 else "Normal" if math.isfinite(summary.atm_iv) else "N/A"
    iv1, iv2, iv3 = st.columns(3)
    iv1.metric("Current IV", _fmt_iv(summary.atm_iv)); iv2.metric("20D Avg", "N/A"); iv3.metric("60D Avg", "N/A")
    st.caption(f"IV State: {iv_state} · 무료 체인은 과거 IV 시계열을 제공하지 않아 20D/60D 평균을 임의 추정하지 않습니다. 실적 전후에는 IV 상승과 IV Crush 가능성을 확인하세요.")
    st.subheader("주요 Open Interest 집중 Strike")
    w1, w2, w3 = st.columns(3)
    w1.metric("Call OI 집중", "—" if summary.call_wall is None else money(summary.call_wall))
    w2.metric("Put OI 집중", "—" if summary.put_wall is None else money(summary.put_wall))
    w3.metric("Max Pain", "—" if summary.max_pain is None else money(summary.max_pain))
    st.caption("Max Pain은 옵션 포지션의 균형 참고값이며 해당 가격으로 반드시 수렴한다는 의미가 아닙니다.")
    if support is not None or resistance is not None:
        label, detail = price_confluence(summary, support, resistance, spot)
        st.subheader("Technical × Options")
        st.info(f"**{label}** · {detail} Technical {money(support) if support else '—'} / {money(resistance) if resistance else '—'} · Options {money(summary.put_wall) if summary.put_wall else '—'} / {money(summary.call_wall) if summary.call_wall else '—'}")
    st.plotly_chart(_oi_chart(calls, puts, spot), use_container_width=True, config={"displayModeBar": False})
    with st.expander("Option Chain 원본 데이터"):
        left, right = st.columns(2)
        show = ["contractSymbol", "strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"]
        left.markdown("**CALL**"); left.dataframe(calls[[x for x in show if x in calls]], hide_index=True, use_container_width=True)
        right.markdown("**PUT**"); right.dataframe(puts[[x for x in show if x in puts]], hide_index=True, use_container_width=True)

