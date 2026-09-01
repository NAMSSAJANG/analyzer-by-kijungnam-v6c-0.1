from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots

from calibration_engine import run_setup_calibration
from company_engine import build_company_snapshot
from consensus_engine import build_consensus_v2
from history_store import SQLiteHistoryStore
from korean_stock_search import contains_hangul, load_krx_listing, search_krx_listing
from market_regime import build_market_regime, market_for_symbol
from opportunity_engine import build_opportunity
from quant_engine import build_quant_snapshot, financial_rows
from risk_engine import build_risk_snapshot
from scanner_engine import scan_market, top_views
from setup_engine import build_setups
from sr_engine import build_zones
from technical_engine import build_technical_snapshot

st.set_page_config(page_title="Stock Analyzer V6.0.9", page_icon="📈", layout="wide")

DB_FILE = Path(os.getenv("ANALYZER_DB_FILE", ".data/stock_analyzer_v6.sqlite"))
HISTORY = SQLiteHistoryStore(DB_FILE)

PULSE = {
    "S&P 500": "^GSPC", "Nasdaq 100": "^NDX", "SOX": "^SOX", "VIX": "^VIX",
    "Gold": "GC=F", "Silver": "SI=F", "WTI": "CL=F", "Copper": "HG=F",
    "USD/KRW": "KRW=X", "DXY": "DX-Y.NYB", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD",
}

PULSE_GUIDE = {
    "S&P 500": "미국 대형주 전반의 위험선호와 경기 기대를 확인합니다.",
    "Nasdaq 100": "미국 성장주·기술주 중심의 위험선호를 확인합니다.",
    "SOX": "글로벌 반도체 업종의 주도력과 사이클을 확인합니다.",
    "VIX": "미국 주식시장의 단기 변동성 기대입니다. 높을수록 위험회피가 강한 편입니다.",
    "Gold": "안전자산 선호와 실질금리·달러 흐름을 함께 읽는 참고 자산입니다.",
    "Silver": "귀금속이면서 산업 수요 영향도 받는 경기·유동성 보조지표입니다.",
    "WTI": "미국 원유 가격으로 경기·인플레이션·에너지 섹터 흐름을 확인합니다.",
    "Copper": "글로벌 제조업과 경기 민감도를 보는 대표적인 산업금속입니다.",
    "USD/KRW": "원·달러 환율입니다. 급등은 한국 주식의 외국인 수급에 부담이 될 수 있습니다.",
    "DXY": "달러 강도를 나타냅니다. 강달러는 글로벌 유동성에 부담이 될 수 있습니다.",
    "Bitcoin": "고위험 자산의 유동성·위험선호를 보조적으로 확인합니다.",
    "Ethereum": "가상자산 위험선호와 유동성 흐름을 보조적으로 확인합니다.",
}

RATE_GUIDE = {
    "US 2Y": "연준 정책 기대에 민감한 단기 국채금리입니다.",
    "US 5Y": "중기 성장·물가 기대를 반영하는 국채금리입니다.",
    "US 10Y": "주식 할인율과 장기 성장 기대의 핵심 기준 금리입니다.",
    "US 30Y": "초장기 물가·재정 부담과 장기 금리 기대를 반영합니다.",
    "HYG": "미국 하이일드 회사채 ETF · 위험선호와 신용 스트레스 참고",
    "LQD": "미국 투자등급 회사채 ETF · 우량 신용시장 흐름 참고",
    "10Y-2Y": "장단기 금리차 · 경기 사이클과 수익률곡선 참고",
    "Credit Spread proxy": "HYG와 LQD의 상대성과 · 신용 위험선호 대용값",
}

SERIES_STYLE = {
    "Opportunity": ("종목 매력도 (Opportunity)", "#6366f1", "top center"),
    "Pullback": ("눌림목 진입 (Pullback Entry)", "#ff6b45", "bottom center"),
    "Momentum Entry": ("모멘텀 진입 (Momentum Entry)", "#14d6a0", "top center"),
    "Quant": ("퀀트 종합 (Quant Composite)", "#6366f1", "top center"),
    "Trend": ("추세 (Trend)", "#ff6b45", "top center"),
    "Momentum": ("모멘텀 (Momentum)", "#14d6a0", "bottom center"),
    "Market Regime": ("시장 국면 (Market Regime)", "#fbbf24", "top center"),
}

COMPANY_FACTOR_LABELS = {
    "Growth": "성장성 (Growth)",
    "Profitability": "수익성 (Profitability)",
    "Balance Sheet": "재무건전성 (Balance Sheet)",
    "Cash Flow": "현금흐름 (Cash Flow)",
    "Valuation": "가치평가 (Valuation)",
}

COMPANY_FACTOR_GUIDE = {
    "Growth": "매출과 이익이 얼마나 빠르고 지속적으로 성장하는지를 봅니다. 높을수록 최근 성장 속도와 이익 확장성이 강하다는 의미입니다.",
    "Profitability": "매출을 이익으로 전환하는 능력과 자본 효율성을 봅니다. 마진과 ROE가 안정적일수록 높은 평가를 받습니다.",
    "Balance Sheet": "부채 부담과 유동성, 자본 구조의 안정성을 봅니다. 재무 여력이 충분할수록 경기 변동에 대응하기 유리합니다.",
    "Cash Flow": "회계상 이익이 실제 현금 창출로 이어지는지를 봅니다. 낮은 점수는 현금 창출력이나 관련 데이터의 추가 확인이 필요하다는 뜻입니다.",
    "Valuation": "현재 주가가 기업의 성장성과 수익성에 비해 어느 수준에서 거래되는지를 봅니다. 높은 점수가 절대적으로 싸다는 뜻은 아닙니다.",
}

AUX_LABELS = {
    "평균회귀": "평균회귀",
    "모멘텀": "모멘텀 (Momentum)",
    "다중 시간대": "다중 시간대",
    "낙폭 위치": "낙폭 위치",
    "수급 흐름": "수급 흐름 (Demand)",
    "Target Price Factor": "상단 여유도 (Target Price Factor)",
    "통계적 Z-Score": "통계적 Z-Score",
    "Relative Strength": "상대강도 (Relative Strength)",
    "Extension Balance": "가격 확장 균형 (Extension Balance)",
}

MARKET_LABEL_KO = {
    "Risk-On": "위험선호 우세",
    "Risk-On / Selective": "위험선호·선별장세",
    "Supportive / Selective": "우호적·선별장세",
    "Mixed": "혼조",
    "Risk-Off": "위험회피",
    "Stress": "시장 스트레스",
    "Neutral": "중립",
}

MARKET_COMPONENT_KO = {
    "Broad Market": "광범위 시장",
    "Growth / Tech": "성장주·기술주",
    "Credit": "신용시장",
    "Sector": "업종 흐름",
    "Volatility": "변동성",
    "Dollar / Liquidity": "달러·유동성",
    "Credit Breadth": "신용시장 폭",
    "KOSPI": "코스피",
    "KOSDAQ": "코스닥",
    "US Tech Lead": "미국 기술주 선행",
    "Global Sector": "글로벌 업종",
    "Global Risk": "글로벌 위험선호",
    "USD/KRW": "원·달러",
    "Global Volatility": "글로벌 변동성",
    "SOX Driver": "반도체 글로벌 드라이버",
}

st.markdown("""
<style>
.stApp{background:linear-gradient(180deg,#07111f 0%,#081525 100%)}
.block-container{padding-top:1.1rem;max-width:1480px;padding-bottom:4rem}
h1,h2,h3{letter-spacing:-.025em}
.v6-section{height:1px;margin:46px 0 20px}
.v6-card{box-sizing:border-box;border:1px solid #29415e;border-radius:16px;padding:19px;background:#0d1b2d;height:100%;min-height:176px;margin-bottom:18px}
.v6-card.compact{height:226px;min-height:226px;overflow:auto}.v6-card.summary{height:224px;min-height:224px;overflow:hidden}.v6-card.risk{height:220px;min-height:220px}.v6-card.entry{height:198px;min-height:198px;margin-bottom:20px}.v6-card.consensus-lens{height:206px;min-height:206px;overflow:hidden}
.v6-kicker{font-size:.72rem;font-weight:850;letter-spacing:.14em;color:#38bdf8;margin-bottom:9px}
.v6-value{font-size:2rem;font-weight:900;color:#f8fafc;line-height:1.15;margin:4px 0 8px}.v6-sub{color:#94a3b8;line-height:1.65;font-size:.88rem}
.v6-pill{display:inline-block;border-radius:99px;padding:4px 9px;background:#102c46;color:#7dd3fc;font-weight:750;margin:3px 4px 3px 0}
.decision{border:1px solid #315272;border-radius:18px;padding:22px;background:linear-gradient(135deg,#0d1b2d,#10243a);margin:15px 0 24px}
.decision h2{margin:.2rem 0 .8rem}.decision p{color:#dbeafe;line-height:1.78;margin:.42rem 0}
.brief-card{box-sizing:border-box;border:1px solid #29415e;border-radius:15px;padding:21px;background:#0d1b2d;height:286px;min-height:286px;color:#dbeafe;margin-bottom:22px;overflow:auto}
.brief-card.wide{height:auto;min-height:180px}.brief-card h3{color:#f8fafc;margin:.1rem 0 1rem;font-size:1.28rem}.brief-card p{line-height:1.78;margin:0;color:#dbeafe}
.status-green{color:#34d399}.status-teal{color:#2dd4bf}.status-blue{color:#60a5fa}.status-yellow{color:#fbbf24}.status-orange{color:#fb923c}.status-red{color:#fb7185}.status-muted{color:#94a3b8}
.zone{border-left:4px solid #38bdf8;background:#0d1b2d;border-radius:10px;padding:13px;margin:7px 0}.zone.r{border-left-color:#fb7185}
.explain{box-sizing:border-box;border:1px solid #29415e;border-radius:14px;padding:16px 18px;background:#0a1728;color:#cbd5e1;line-height:1.72;height:132px;min-height:132px;margin-bottom:18px}
.indicator-row{border:1px solid #29415e;border-left:3px solid #64748b;border-radius:11px;padding:13px 15px;margin:9px 0;background:#0d1b2d;display:flex;justify-content:space-between;gap:20px;align-items:center}
.indicator-row.good{border-left-color:#10b981}.indicator-row.bad{border-left-color:#ef4444}.indicator-row small{display:block;color:#8292a8;margin-top:5px;line-height:1.55}.indicator-row strong{text-align:right;white-space:nowrap}
.scenario{box-sizing:border-box;border-radius:13px;padding:17px;min-height:160px;height:100%}.scenario h4{margin:0 0 15px;font-size:1.1rem}.scenario p{margin:0;line-height:1.72}.up{background:#103c30;color:#6ee7b7}.mid{background:#102d4d;color:#7dd3fc}.down{background:#451d28;color:#fda4af}
.pulse-shell{box-sizing:border-box;border:1px solid #29415e;border-radius:13px;padding:14px;background:#0d1b2d;min-height:174px;margin-bottom:10px}
.pulse-head{display:flex;justify-content:space-between;gap:8px;align-items:baseline}.pulse-head b{color:#f8fafc}.pulse-up{color:#34d399}.pulse-down{color:#fb7185}
.cal-help{border:1px solid #315272;background:#0d1b2d;border-radius:14px;padding:15px 17px;line-height:1.72;color:#cbd5e1;margin:8px 0 15px}
.cal-current{box-sizing:border-box;border:1px solid #29415e;border-radius:15px;padding:18px 19px;background:#0d1b2d;min-height:190px;height:auto;margin-bottom:14px}.cal-current .score{font-size:2rem;font-weight:900;line-height:1.1;margin:8px 0}.cal-current .state{font-weight:850;margin-bottom:8px}.cal-compare{border:1px solid #315272;border-radius:16px;padding:18px 20px;background:linear-gradient(135deg,#0d1b2d,#10243a);margin:12px 0 20px;line-height:1.72}.cal-strategy{box-sizing:border-box;border:1px solid #29415e;border-radius:16px;padding:19px 20px;background:#0d1b2d;min-height:470px;height:auto;margin-bottom:18px;overflow:visible}.cal-stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}.cal-stat{border:1px solid #20344d;border-radius:11px;background:#0a1728;padding:10px 12px;min-height:88px}.cal-stat .k{color:#94a3b8;font-size:.76rem;font-weight:800;line-height:1.35}.cal-stat .v{font-size:1.18rem;font-weight:900;margin-top:4px;color:#f8fafc;line-height:1.25}.cal-tag{display:inline-block;border-radius:99px;padding:4px 9px;font-size:.78rem;font-weight:850;margin-left:6px}.cal-tag.ok{background:#123c32;color:#6ee7b7}.cal-tag.wait{background:#49371b;color:#fbbf24}.cal-tag.bad{background:#4a2028;color:#fda4af}.cal-style{border:1px solid #315272;border-radius:16px;padding:20px;background:#0a1728;margin:10px 0 20px}.cal-style h3{margin:.15rem 0 .65rem}.cal-section-note{color:#94a3b8;line-height:1.7;margin:-5px 0 14px}
.delta-card{box-sizing:border-box;border:1px solid #29415e;border-radius:12px;padding:12px 14px;background:#0d1b2d;min-height:92px;margin:4px 0 14px}.delta-label{color:#94a3b8;font-size:.78rem;font-weight:800;line-height:1.4}.delta-value{font-size:1.22rem;font-weight:900;margin-top:6px}.delta-change{font-size:.83rem;font-weight:800;margin-left:7px}
.risk-summary{border:1px solid #29415e;border-radius:12px;padding:13px 16px;background:#0a1728;margin:4px 0 10px;color:#cbd5e1;line-height:1.65}.consensus-summary{border:1px solid #315272;border-radius:16px;padding:18px 20px;background:linear-gradient(135deg,#0d1b2d,#10243a);margin:10px 0 16px;line-height:1.75;color:#dbeafe}.consensus-meter{border:1px solid #29415e;border-radius:13px;padding:14px 16px;background:#0a1728;min-height:104px}.consensus-meter .label{color:#94a3b8;font-size:.8rem;font-weight:800}.consensus-meter .value{font-size:1.7rem;font-weight:900;margin-top:7px;color:#f8fafc}
.entry-decision-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:18px 0 12px}.entry-decision-card{box-sizing:border-box;border:1px solid #29415e;border-radius:14px;padding:16px 17px;background:#0a1728;min-height:122px}.entry-decision-label{color:#94a3b8;font-size:.76rem;font-weight:850;line-height:1.45}.entry-decision-value{font-size:1.34rem;font-weight:900;margin-top:9px;line-height:1.35}.entry-decision-interpretation{border:1px solid #315272;border-radius:14px;padding:17px 19px;background:linear-gradient(135deg,#0d1b2d,#10243a);color:#dbeafe;line-height:1.75;margin-bottom:18px}.entry-decision-interpretation b{color:#f8fafc}
[data-testid="stMetricValue"]{font-size:clamp(1.4rem,2.5vw,2.1rem)}
[data-testid="stDataFrame"]{border:1px solid #29415e;border-radius:10px;overflow:hidden}
div[data-testid="stHorizontalBlock"]{gap:1.15rem;align-items:stretch}
div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-height:100%}
[data-testid="stDataFrame"]{margin-bottom:16px}
hr{margin:2rem 0 2.2rem!important}
@media(max-width:700px){.block-container{padding-left:.8rem;padding-right:.8rem}.v6-card,.brief-card,.scenario{height:auto;min-height:0}.indicator-row{align-items:flex-start}.entry-decision-grid{grid-template-columns:1fr 1fr}}
</style>
""", unsafe_allow_html=True)


def money(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:,.2f}" if abs(value) < 10000 else f"{value:,.0f}"


def pct(value: float | None, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "—"
    return f"{value:+.{digits}f}%"


def score_color(value: float) -> str:
    return "#22c55e" if value >= 80 else "#34d399" if value >= 65 else "#94a3b8" if value >= 50 else "#fb923c" if value >= 35 else "#fb7185"


def grade_ko(value: float) -> str:
    if value >= 85: return "매우 강함"
    if value >= 75: return "강함"
    if value >= 65: return "양호"
    if value >= 50: return "중립"
    if value >= 35: return "약함"
    return "매우 약함"


def status_class(text: str) -> str:
    t = text.upper()
    if any(x in t for x in ("READY", "CONFIRMED", "PREFERRED", "RISK-ON", "STRONG", "LOW")):
        return "status-green"
    if any(x in t for x in ("DEVELOPING", "WATCH", "MIXED", "NEUTRAL", "MODERATE", "SELECTIVE")):
        return "status-yellow"
    if any(x in t for x in ("EXTENDED", "WARNING", "ELEVATED", "UPCOMING", "HIGH")):
        return "status-orange"
    return "status-red"


def entry_status_class(setup) -> str:
    """User-facing color hierarchy for entry readiness."""
    status = str(setup.status).upper()
    if status in ("READY", "CONFIRMED"):
        return "status-green"
    if status in ("DEVELOPING", "EARLY BREAKOUT"):
        return "status-teal"
    if status in ("WATCH", "NOT IN ZONE"):
        return "status-yellow"
    if status in ("EXTENDED", "STRUCTURE WARNING"):
        return "status-orange"
    return "status-red"


def entry_status_note(setup) -> str:
    status = str(setup.status).upper()
    notes = {
        "READY": "가격·지지 조건이 우호적이어서 실제 진입 후보로 검토할 수 있는 단계입니다.",
        "DEVELOPING": "조건이 상당 부분 형성됐지만 지지 반응이나 가격 안정 확인이 한 번 더 필요합니다.",
        "NOT IN ZONE": "상승 구조는 유지될 수 있지만 현재 가격이 눌림목 진입 구간과는 거리가 있습니다.",
        "STRUCTURE WARNING": "눌림목의 질이 약해져 지지 회복을 먼저 확인하는 편이 좋습니다.",
        "CONFIRMED": "돌파·추세·수급 조건이 함께 확인되어 모멘텀 진입 후보로 볼 수 있습니다.",
        "EARLY BREAKOUT": "초기 돌파 신호가 나타났지만 거래량과 돌파 가격 유지 여부를 더 확인해야 합니다.",
        "WATCH": "아직 돌파 강도가 충분하지 않아 저항 돌파와 거래량 증가를 기다리는 단계입니다.",
        "EXTENDED": "상승 흐름은 강하지만 가격 확장이 커 신규 진입은 작은 비중이나 재지지를 우선합니다.",
        "FAILED BREAKOUT": "돌파 구조가 약해져 신규 진입보다 가격 구조 회복을 먼저 확인해야 합니다.",
    }
    return notes.get(status, "현재 진입 조건을 지지·거래량·시장환경과 함께 확인합니다.")


def risk_item_class(kind: str, raw_state: str) -> str:
    state = str(raw_state)
    upper = state.upper()
    if kind == "liquidity":
        if upper.startswith("HIGH"): return "status-green"
        if upper.startswith("NORMAL"): return "status-teal"
        if upper.startswith("THIN"): return "status-orange"
        return "status-red"
    if kind == "earnings":
        if upper.startswith("NORMAL") or upper.startswith("UNKNOWN"): return "status-green"
        if upper.startswith("UPCOMING"): return "status-yellow"
        if upper.startswith("EARNINGS SOON"): return "status-orange"
        return "status-red"
    if kind == "market":
        if upper.startswith("LOW"): return "status-green"
        if upper.startswith("MODERATE"): return "status-yellow"
        return "status-red"
    if upper.startswith("LOW") or upper.startswith("NORMAL"):
        return "status-green"
    if upper.startswith("ELEVATED"):
        return "status-orange"
    if upper.startswith("HIGH"):
        return "status-orange"
    if upper.startswith("EXTREME"):
        return "status-red"
    return "status-muted"


PULLBACK_STATUS = {
    "READY": "진입 유리",
    "DEVELOPING": "진입 검토",
    "NOT IN ZONE": "관망 · 눌림 대기",
    "STRUCTURE WARNING": "주의 · 구조 확인",
}
MOMENTUM_STATUS = {
    "CONFIRMED": "진입 유리",
    "EARLY BREAKOUT": "초기 돌파 확인",
    "WATCH": "관망 · 돌파 확인",
    "EXTENDED": "과열 주의 · 소규모 접근",
    "FAILED BREAKOUT": "진입 보류 · 돌파 실패",
}
PREFERRED_STATUS = {
    "Momentum Preferred": "모멘텀 접근 (Momentum)",
    "Pullback Preferred": "눌림목 접근 (Pullback)",
    "Both Valid": "두 방식 모두 가능 (Both Valid)",
    "No Clear Setup": "뚜렷한 우선 방식 없음",
}


def setup_status_ko(setup) -> str:
    table = PULLBACK_STATUS if setup.name == "Pullback" else MOMENTUM_STATUS
    return table.get(setup.status, setup.status)


def preferred_ko(value: str) -> str:
    return PREFERRED_STATUS.get(value, value)


def entry_decision_view(setups):
    """Separate relative setup preference from actual entry readiness."""
    pull, mom = setups.pullback, setups.momentum
    preferred = setups.preferred

    if preferred == "Pullback Preferred":
        approach = "눌림목 접근 (Pullback)"
        if str(pull.status).upper() == "READY":
            state, cls = "진입 유리", "status-green"
            text = (
                "좋은 눌림목이 실제로 형성된 상태입니다. 상승 구조를 유지하면서 지지구간과의 거리가 가까워졌고 "
                "가격 메리트도 개선됐습니다. 지지 반응과 거래량 패턴이 유지된다면 눌림목 분할 진입을 검토할 수 있습니다."
            )
        else:
            state, cls = "진입 검토", "status-teal"
            text = (
                "두 진입 방식 중에서는 눌림목 접근이 더 적합합니다. 다만 아직 완전히 성숙한 눌림목은 아니므로 "
                "지지 유지와 반등 확인을 한 번 더 확인한 뒤 분할 접근하는 편이 유리합니다."
            )
    elif preferred == "Momentum Preferred":
        approach = "모멘텀 접근 (Momentum)"
        status = str(mom.status).upper()
        if status == "CONFIRMED":
            state, cls = "진입 유리", "status-green"
            text = (
                "강한 추세와 돌파 흐름이 실제로 확인된 상태입니다. 현재는 눌림을 오래 기다리면 오히려 강한 상승 흐름을 "
                "놓칠 수 있습니다. 다만 거래량 확인과 가격 확장 Risk를 함께 보면서 초기 비중을 조절하는 것이 중요합니다."
            )
        elif status == "EXTENDED":
            state, cls = "과열 주의", "status-orange"
            text = (
                "모멘텀 접근이 상대적으로 적합하지만 가격 확장이 커진 상태입니다. 강한 흐름을 인정하되 추격 비중을 줄이고, "
                "돌파 가격 재지지나 짧은 조정을 확인하는 편이 안전합니다."
            )
        else:
            state, cls = "진입 검토", "status-teal"
            text = (
                "모멘텀 접근이 상대적으로 적합하고 초기 돌파 신호가 형성되고 있습니다. 눌림을 기다리기보다 돌파 가격 유지와 "
                "거래량 증가를 확인하면서 분할 진입을 검토할 수 있는 단계입니다."
            )
    elif preferred == "Both Valid":
        approach = "두 방식 모두 가능 (Pullback / Momentum)"
        if str(pull.status).upper() == "READY" and str(mom.status).upper() == "CONFIRMED":
            state, cls = "진입 유리", "status-green"
        else:
            state, cls = "진입 검토", "status-teal"
        text = (
            "눌림목과 모멘텀 조건이 모두 유효합니다. 돌파 후 첫 재지지처럼 두 Setup이 겹치는 구간일 수 있으므로, "
            "현재가와 지지 Zone·Trigger 중 더 가까운 조건을 기준으로 진입 방식을 선택하는 편이 좋습니다."
        )
    else:
        diff = pull.score - mom.score
        if diff >= 8:
            approach = "눌림목 관찰 (Pullback Watch)"
            state, cls = "관망 · 조건 확인", "status-yellow"
            text = (
                "둘 중 굳이 고르면 Pullback이 상대적으로 낫지만 아직 실제 진입 준비는 부족합니다. "
                "지지구간 접근과 가격 안정, 반등 확인이 더 필요하므로 현재는 관망이 우선입니다."
            )
        elif diff <= -8:
            approach = "모멘텀 관찰 (Momentum Watch)"
            state, cls = "관망 · 돌파 확인", "status-yellow"
            text = (
                "모멘텀 점수가 상대적으로 높지만 실제 돌파·거래량 확인 조건은 아직 부족합니다. "
                "저항 돌파와 거래량 증가가 확인되기 전까지는 추격보다 관망이 적절합니다."
            )
        else:
            approach = "뚜렷한 우선 방식 없음"
            state, cls = "관망", "status-yellow"
            text = (
                "눌림목과 모멘텀 어느 쪽도 현재 뚜렷한 우위를 만들지 못했습니다. 좋은 종목이어도 지금은 신규 진입 Setup이 부족할 수 있으므로 "
                "지지 형성 또는 돌파 확인을 기다리는 편이 좋습니다."
            )
    return {"approach": approach, "state": state, "class": cls, "interpretation": text}


def risk_ko(value: str) -> str:
    return {"LOW":"낮음", "MODERATE":"보통", "HIGH":"높음", "EXTREME":"매우 높음"}.get(value, value)


def market_label_ko(value: str) -> str:
    return MARKET_LABEL_KO.get(value, value)


def market_region_ko(value: str) -> str:
    return {"US": "미국", "KR": "한국"}.get(value, value)


def market_components_frame(market) -> pd.DataFrame:
    return pd.DataFrame([
        {"구성요소": MARKET_COMPONENT_KO.get(k, k), "점수": v}
        for k, v in market.components.items()
    ])


def risk_state_ko(value: str) -> str:
    text = str(value)
    replacements = {
        "Event Risk": "이벤트 위험", "Earnings Soon": "실적 임박", "Upcoming": "실적 예정",
        "Unknown / Normal": "일정 불명 · 정상", "Normal": "정상", "Low": "낮음",
        "Elevated": "높음", "High": "높음", "Extreme": "매우 높음",
        "Thin": "낮음", "Weak": "매우 낮음", "Moderate": "보통",
    }
    for src, dst in replacements.items():
        if text.startswith(src):
            return text.replace(src, dst, 1)
    return replacements.get(text, text)


PULLBACK_FACTOR_KO = {
    "Trend Quality": "추세 품질",
    "Support Proximity": "지지구간 접근도",
    "EMA Position": "이동평균 위치",
    "Pullback Depth": "조정 깊이",
    "Volume Pattern": "거래량 패턴",
    "Momentum Stabilization": "모멘텀 안정화",
    "Market": "시장환경",
}
MOMENTUM_FACTOR_KO = {
    "Trend Strength": "추세 강도",
    "Breakout": "돌파 강도",
    "Momentum": "모멘텀",
    "Volume Confirmation": "거래량 확인",
    "Relative Strength": "상대강도",
    "Market": "시장환경",
}


def _multiline_card_label(label: str) -> str:
    if "(" in label and ")" in label:
        ko, rest = label.split("(", 1)
        return f"{ko.strip()}<br><span style='color:#94a3b8'>({rest}</span>"
    return label


def score_card(label: str, value: float | None, subtitle: str = "", compact: bool = False, summary: bool = False):
    if value is None:
        shown, color, state = "N/A", "#94a3b8", "데이터 부족"
    else:
        shown, color, state = f"{value:.1f}", score_color(value), grade_ko(value)
    cls = "v6-card compact" if compact else "v6-card summary" if summary else "v6-card"
    label_html = _multiline_card_label(label) if summary else label
    st.markdown(f"<div class='{cls}'><div class='v6-kicker'>{label_html}</div><div class='v6-value' style='color:{color}'>{shown}</div><div style='color:{color};font-weight:800;margin-bottom:6px'>{state}</div><div class='v6-sub'>{subtitle}</div></div>", unsafe_allow_html=True)


def briefing(title: str, body: str, kicker: str = "AI BRIEF", wide: bool = False):
    cls = "brief-card wide" if wide else "brief-card"
    st.markdown(f"<div class='{cls}'><div class='v6-kicker'>{kicker}</div><h3>{title}</h3><p>{body}</p></div>", unsafe_allow_html=True)


def indicator_row(label: str, value: str, guide: str, tone: str = "neutral"):
    cls = "indicator-row" + (" good" if tone == "good" else " bad" if tone == "bad" else "")
    st.markdown(f"<div class='{cls}'><div><b>{label}</b><small>{guide}</small></div><strong>{value}</strong></div>", unsafe_allow_html=True)


@st.cache_data(ttl=900, show_spinner=False)
def prices(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    d = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False, threads=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    return d.dropna(how="all")


@st.cache_data(ttl=21600, show_spinner=False)
def treasury_yields() -> pd.DataFrame:
    """미 재무부 공식 일별 국채 수익률(2Y/5Y/10Y/30Y)을 불러옵니다."""
    year=datetime.now(timezone.utc).year
    url="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    response=requests.get(
        url,
        params={"data":"daily_treasury_yield_curve","field_tdr_date_value":year},
        timeout=6,
        headers={"User-Agent":"StockAnalyzer/6"},
    )
    response.raise_for_status()
    rows=[]
    field_map={"BC_2YEAR":"US 2Y","BC_5YEAR":"US 5Y","BC_10YEAR":"US 10Y","BC_30YEAR":"US 30Y"}
    for properties in ET.fromstring(response.content).iter():
        if properties.tag.rsplit("}",1)[-1] != "properties":
            continue
        values={child.tag.rsplit("}",1)[-1]: child.text for child in properties}
        raw_date=values.get("NEW_DATE") or values.get("Date")
        if not raw_date:
            continue
        row={"date":pd.to_datetime(raw_date,errors="coerce")}
        for source,target in field_map.items():
            row[target]=pd.to_numeric(values.get(source),errors="coerce")
        rows.append(row)
    if not rows:
        raise ValueError("Treasury yield rows are missing")
    return pd.DataFrame(rows).set_index("date").sort_index().dropna(how="all")


@st.cache_data(ttl=3600, show_spinner=False)
def info(symbol: str) -> dict:
    try:
        return yf.Ticker(symbol).get_info() or {}
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def news(symbol: str) -> list[tuple[str, str, str]]:
    try:
        rows = yf.Ticker(symbol).news[:8]
        out = []
        for x in rows:
            c = x.get("content", x)
            title = c.get("title") or x.get("title")
            if title:
                out.append((title, c.get("summary", ""), (c.get("canonicalUrl") or {}).get("url") or x.get("link", "")))
        return out
    except Exception:
        return []


@st.cache_data(ttl=86400, show_spinner=False)
def krx_listing():
    return load_krx_listing()


@st.cache_data(ttl=300, show_spinner=False)
def search_symbol(query: str):
    q = query.strip()
    if not q:
        return []
    merged = []
    is_hangul = contains_hangul(q)
    if is_hangul or re.fullmatch(r"\d{1,6}", q):
        try:
            merged.extend(search_krx_listing(q, krx_listing()))
        except Exception:
            pass
    try:
        data = requests.get(
            "https://query2.finance.yahoo.com/v1/finance/search",
            params={"q": q, "quotesCount": 10, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
        ).json()
        merged.extend({
            "symbol": x.get("symbol"),
            "name": x.get("longname") or x.get("shortname") or x.get("symbol"),
            "exchange": x.get("exchDisp", ""), "type": x.get("quoteType", ""),
        } for x in data.get("quotes", []) if x.get("symbol"))
    except Exception:
        pass
    if not merged and not is_hangul:
        merged = [{"symbol": q.upper(), "name": q.upper(), "exchange": "직접 입력", "type": ""}]
    unique, seen = [], set()
    for row in merged:
        if row["symbol"] not in seen:
            seen.add(row["symbol"]); unique.append(row)
    return unique[:10]


US_PEERS = {
    "technology": ["MSFT", "AAPL", "NVDA", "AVGO", "ORCL", "AMD", "QCOM", "MU"],
    "financial services": ["JPM", "BAC", "GS", "MS", "WFC"],
    "healthcare": ["LLY", "JNJ", "ABBV", "MRK", "UNH"],
    "consumer cyclical": ["AMZN", "TSLA", "HD", "MCD", "NKE"],
    "communication services": ["META", "GOOGL", "NFLX", "TMUS", "DIS"],
    "energy": ["XOM", "CVX", "COP", "SLB", "EOG"],
}
KR_PEERS = {
    "technology": ["005930.KS", "000660.KS", "066570.KS", "035420.KS"],
    "financial services": ["105560.KS", "055550.KS", "086790.KS", "316140.KS"],
    "consumer cyclical": ["005380.KS", "000270.KS", "012330.KS"],
    "healthcare": ["207940.KS", "068270.KS", "326030.KS"],
    "basic materials": ["005490.KS", "051910.KS", "011170.KS"],
}


@st.cache_data(ttl=21600, show_spinner=False)
def peer_infos(symbol: str, sector: str, region: str):
    pool = (KR_PEERS if region == "KR" else US_PEERS).get((sector or "").lower(), [])
    symbols = [x for x in pool if x != symbol][:5]
    out = []
    good_symbols = []
    for ticker in symbols:
        try:
            payload = yf.Ticker(ticker).get_info() or {}
            if payload:
                out.append(payload); good_symbols.append(ticker)
        except Exception:
            continue
    return out, good_symbols


@st.cache_data(ttl=3600, show_spinner=False)
def earnings_days(symbol: str) -> int | None:
    try:
        cal = yf.Ticker(symbol).calendar
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date") or cal.get("EarningsDate")
            if isinstance(raw, (list, tuple)) and raw: raw = raw[0]
            if raw is not None:
                dt = pd.Timestamp(raw)
                if dt.tzinfo is not None: dt = dt.tz_localize(None)
                return (dt.normalize() - pd.Timestamp.now().normalize()).days
    except Exception:
        pass
    return None


def benchmark_symbol(symbol: str) -> str:
    return "^KS11" if market_for_symbol(symbol) == "KR" else "^GSPC"


def build_full_analysis(symbol: str):
    frame = prices(symbol, "2y")
    if len(frame) < 210:
        raise ValueError("최소 210거래일의 가격 데이터가 필요합니다.")
    inf = info(symbol)
    region = market_for_symbol(symbol)
    sector = inf.get("sector", "")
    benchmark = prices(benchmark_symbol(symbol), "2y")
    tech = build_technical_snapshot(frame, benchmark)
    market = build_market_regime(symbol, sector, prices)
    peers, peer_symbols = peer_infos(symbol, sector, region)
    company = build_company_snapshot(inf, peers)

    option_view = None
    option_label = "N/A"
    try:
        from options_analyzer import get_option_snapshot, option_bias
        option_view, _, _, _ = get_option_snapshot(symbol, float(frame.Close.iloc[-1]))
        if option_view:
            option_label = option_bias(option_view)
    except Exception:
        pass

    zones = build_zones(
        frame, tech,
        option_put_wall=option_view.put_wall if option_view else None,
        option_call_wall=option_view.call_wall if option_view else None,
    )
    risk = build_risk_snapshot(tech, market, earnings_days(symbol))
    now = float(frame.Close.iloc[-1])
    setups = build_setups(now, tech, market, zones, risk)
    opportunity = build_opportunity(company, tech, market)
    consensus = build_consensus_v2(company, tech, setups, market, option_label, option_view.data_quality if option_view else None)
    quant = build_quant_snapshot(frame, company, tech, market, zones.supports, zones.resistances)
    return dict(
        frame=frame, info=inf, region=region, sector=sector, benchmark=benchmark, tech=tech, market=market,
        company=company, zones=zones, risk=risk, setups=setups, opportunity=opportunity,
        consensus=consensus, option=option_view, option_label=option_label, peer_symbols=peer_symbols,
        peers=peers, now=now, quant=quant,
    )


def reconstructed_trajectory(a: dict, count: int = 10) -> pd.DataFrame:
    """가격 데이터를 이용해 최근 실제 거래일 기준으로 점수 흐름을 재구성합니다.

    현재 Company Quality와 현재 시장 국면은 고정합니다. 따라서 이 차트는
    점수의 최근 방향을 설명하기 위한 참고용이며 point-in-time 펀더멘털 백테스트가 아닙니다.
    """
    d = a["frame"]
    rows = []
    dates = list(d.index[-max(count * 3, count):])
    for date_value in dates:
        hist = d.loc[d.index <= date_value]
        if len(hist) < 210:
            continue
        bench_hist = a["benchmark"].loc[a["benchmark"].index <= date_value] if not a["benchmark"].empty else None
        try:
            tech = build_technical_snapshot(hist, bench_hist)
            zones = build_zones(hist, tech)
            risk = build_risk_snapshot(tech, a["market"], None)
            setups = build_setups(float(hist.Close.iloc[-1]), tech, a["market"], zones, risk)
            opp = build_opportunity(a["company"], tech, a["market"])
            quant = build_quant_snapshot(hist, a["company"], tech, a["market"], zones.supports, zones.resistances)
            rows.append({
                "date": pd.Timestamp(date_value),
                "Opportunity": opp.score,
                "Quant": quant["score"],
                "Trend": tech.trend,
                "Momentum": tech.momentum,
                "Pullback": setups.pullback.score,
                "Momentum Entry": setups.momentum.score,
            })
        except Exception:
            continue
    return pd.DataFrame(rows).tail(count).reset_index(drop=True)


def _five_day_delta(values: pd.Series) -> tuple[float | None, float | None]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return None, None
    current = float(clean.iloc[-1])
    if len(clean) < 2:
        return current, None
    start_value = float(clean.iloc[-5] if len(clean) >= 5 else clean.iloc[0])
    return current, current - start_value


def _render_trajectory_summary(plot: pd.DataFrame, columns: list[str]) -> None:
    valid_cols = [c for c in columns if c in plot]
    if not valid_cols:
        return
    cols = st.columns(len(valid_cols))
    for slot, key_name in zip(cols, valid_cols):
        display, color, _ = SERIES_STYLE.get(key_name, (key_name, "#cbd5e1", "top center"))
        current, delta = _five_day_delta(plot[key_name])
        if current is None:
            current_text, delta_text, delta_color = "N/A", "5D N/A", "#94a3b8"
        else:
            current_text = f"{current:.1f}"
            if delta is None:
                delta_text, delta_color = "5D N/A", "#94a3b8"
            else:
                arrow = "▲" if delta > 0.05 else "▼" if delta < -0.05 else "—"
                delta_text = f"{arrow} {delta:+.1f} / 5D"
                delta_color = "#34d399" if delta > .05 else "#fb7185" if delta < -.05 else "#94a3b8"
        with slot:
            st.markdown(
                f"<div class='delta-card'><div class='delta-label'>{display}</div>"
                f"<div class='delta-value' style='color:{color}'>{current_text}"
                f"<span class='delta-change' style='color:{delta_color}'>{delta_text}</span></div></div>",
                unsafe_allow_html=True,
            )


def _annotation_shifts(values_by_series: dict[str, float]) -> dict[str, int]:
    """Place labels close to their own marker while avoiding nearby series."""
    valid = [(name, value) for name, value in values_by_series.items() if np.isfinite(value)]
    if not valid:
        return {}
    ordered = sorted(valid, key=lambda item: item[1])
    if len(ordered) == 1:
        return {ordered[0][0]: 12}
    if len(ordered) == 2:
        return {ordered[0][0]: -12, ordered[1][0]: 12}

    shifts = {ordered[0][0]: -12, ordered[-1][0]: 12}
    for idx in range(1, len(ordered) - 1):
        name, value = ordered[idx]
        lower_gap = value - ordered[idx - 1][1]
        upper_gap = ordered[idx + 1][1] - value
        base = 10 if min(lower_gap, upper_gap) >= 8 else 12
        if upper_gap - lower_gap >= 5:
            shifts[name] = base
        elif lower_gap - upper_gap >= 5:
            shifts[name] = -base
        else:
            shifts[name] = base if idx % 2 == 0 else -base
    return shifts


def trajectory_chart(frame: pd.DataFrame, columns: list[str], key: str, title: str):
    if frame.empty or len(frame) < 2:
        st.info("최근 거래일 변화 차트를 계산할 데이터가 충분하지 않습니다.")
        return

    plot = frame.dropna(subset=["date"]).tail(10).reset_index(drop=True)
    st.markdown(f"### {title}")
    if len(plot) < 10:
        st.caption(f"현재 계산 가능한 실제 거래일은 {len(plot)}개입니다. 데이터가 확보되면 최대 10영업일을 표시합니다.")

    _render_trajectory_summary(plot, columns)

    x = list(range(len(plot)))
    ticktext = [pd.Timestamp(v).strftime("%m.%d") for v in plot["date"]]
    fig = go.Figure()
    series_values: dict[str, pd.Series] = {}

    for col in columns:
        if col not in plot:
            continue
        display, color, _ = SERIES_STYLE.get(col, (col, "#cbd5e1", "top center"))
        values = pd.to_numeric(plot[col], errors="coerce")
        series_values[col] = values
        fig.add_trace(go.Scatter(
            x=x,
            y=values,
            mode="lines+markers",
            name=display,
            line=dict(width=2.7, color=color, shape="spline"),
            marker=dict(size=8, color=color, line=dict(width=1.3, color="#07111f")),
            cliponaxis=False,
            customdata=ticktext,
            hovertemplate=f"{display}<br>%{{customdata}} · %{{y:.1f}}점<extra></extra>",
        ))

    # Numeric labels are annotations rather than trace text so they never sit on
    # top of the marker/line.  The vertical shift is recalculated per trading day
    # according to the relative position of each series.
    for i in x:
        values_now = {name: float(values.iloc[i]) for name, values in series_values.items() if i < len(values) and np.isfinite(values.iloc[i])}
        shifts = _annotation_shifts(values_now)
        for series_name, value in values_now.items():
            display, color, _ = SERIES_STYLE.get(series_name, (series_name, "#cbd5e1", "top center"))
            fig.add_annotation(
                x=i, y=value, text=f"{value:.0f}", showarrow=False,
                yshift=shifts.get(series_name, 12),
                font=dict(color=color, size=11),
                bgcolor="rgba(7,17,31,.82)",
                borderpad=1.5,
            )

    fig.update_layout(
        height=350,
        margin=dict(l=22, r=28, t=36, b=46),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0a1728",
        font=dict(color="#cbd5e1"),
        legend=dict(orientation="h", y=1.12),
        yaxis=dict(range=[-4, 108], gridcolor="rgba(148,163,184,.22)", fixedrange=True, zeroline=False),
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(148,163,184,.14)",
            gridwidth=1,
            fixedrange=True,
            tickmode="array",
            tickvals=x,
            ticktext=ticktext,
            ticks="outside",
            ticklen=4,
            range=[-0.25, max(len(x) - .75, .25)],
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, key=key)
    st.caption("최근 실제 거래일 기준 참고 차트 · 현재 기업 품질과 시장 국면을 고정하고 각 거래일의 가격·거래량·기술 구조를 재계산합니다. 상단 요약은 최근 5개 거래일의 첫 값과 현재 값 차이입니다.")

def build_briefings(a: dict) -> dict[str, str]:
    tech, company, market, risk, setups, opp = a["tech"], a["company"], a["market"], a["risk"], a["setups"], a["opportunity"]
    q = a["quant"]

    factor_pairs = [(k, v) for k, v in company.factors.items() if v is not None and np.isfinite(v)]
    strongest = max(factor_pairs, key=lambda x: x[1], default=("N/A", 0))
    weakest = min(factor_pairs, key=lambda x: x[1], default=("N/A", 0))
    strongest_name = COMPANY_FACTOR_LABELS.get(strongest[0], strongest[0])
    weakest_name = COMPANY_FACTOR_LABELS.get(weakest[0], weakest[0])

    company_text = (
        f"기업 품질(Company Quality)은 {company.score:.0f}점이고, 현재 불러온 재무 데이터의 커버리지는 {company.coverage*100:.0f}%입니다. "
        if company.score is not None else
        "기업 품질은 공개 재무 데이터가 충분하지 않아 제한적으로 계산됐습니다. "
    )
    company_text += (
        f"가장 강한 축은 {strongest_name} {strongest[1]:.0f}점, 상대적으로 더 확인할 축은 {weakest_name} {weakest[1]:.0f}점입니다. "
        "제공되지 않은 재무 항목은 0점으로 처리하지 않고 계산에서 제외한 뒤, 남아 있는 항목의 비중을 다시 맞춥니다. "
        "동일·유사 업종 비교 데이터가 충분한 경우에는 절대평가와 업종 내 상대평가를 함께 반영합니다."
    )

    trend_view = "중장기 상승 구조가 강하게 유지되고 있습니다." if tech.trend >= 75 else "중장기 추세는 우호적이지만 추가 확인이 필요합니다." if tech.trend >= 60 else "중장기 추세가 아직 뚜렷하지 않습니다."
    momentum_view = "최근 상승 추진력도 강합니다." if tech.momentum >= 70 else "모멘텀은 중립권이라 추세에 비해 단기 가속은 제한적입니다." if tech.momentum >= 45 else "단기 모멘텀이 약해 반등·돌파 확인이 필요합니다."
    demand_view = "거래량과 수급 확인도 우호적입니다." if tech.demand >= 65 else "거래량·수급 확인은 아직 강하지 않습니다." if tech.demand >= 40 else "수급 점수가 낮아 가격 상승을 뒷받침하는 거래량 확인이 부족합니다."
    rs_view = "시장 대비 가격 리더십이 매우 강합니다." if tech.relative_strength >= 80 else "시장 대비 상대강도는 우호적입니다." if tech.relative_strength >= 60 else "시장 대비 상대강도가 뚜렷하지 않습니다."
    quant_text = (
        f"퀀트 종합(Quant Composite)은 {q['score']:.0f}점입니다. 추세 {tech.trend:.0f}점, 모멘텀 {tech.momentum:.0f}점, "
        f"수급 {tech.demand:.0f}점, 상대강도 {tech.relative_strength:.0f}점으로 구성 상태를 나눠서 봅니다. "
        f"{trend_view} {momentum_view} {demand_view} 현재 거래량은 20일 평균의 {tech.volume_ratio:.2f}배이고 RSI는 {tech.rsi:.1f}입니다. {rs_view}"
    )

    pull_label, mom_label = setup_status_ko(setups.pullback), setup_status_ko(setups.momentum)
    entry_view = entry_decision_view(setups)
    entry_text = (
        f"눌림목 진입(Pullback Entry)은 {setups.pullback.score:.0f}점 · {pull_label}, 모멘텀 진입(Momentum Entry)은 {setups.momentum.score:.0f}점 · {mom_label}입니다. "
        f"우선 방식은 {entry_view['approach']}, 현재 진입 상태는 {entry_view['state']}입니다. "
        f"{entry_view['interpretation']} 실제 신규 진입에서는 점수만 보지 말고 참고 Zone, Trigger, 무효화선과 거래량 확인을 함께 보세요."
    )

    market_text = (
        f"{market_region_ko(market.market)} 시장 국면(Market Regime)은 {market.score:.0f}점 · {market_label_ko(market.label)}입니다. "
        f"종합 위험도는 {risk.score:.0f}점 · {risk_ko(risk.level)}이며, 가격 확장 {risk_state_ko(risk.extension)}, 변동성 {risk_state_ko(risk.volatility)}, "
        f"유동성 {risk_state_ko(risk.liquidity)} 상태입니다. 위험 점수는 좋은 종목을 자동으로 나쁜 종목으로 만들기보다, 신규 진입 비중과 확인 조건을 더 보수적으로 조정하는 데 사용합니다. "
        "시장 국면이 혼조일 때는 지수 방향보다 종목 자체의 상대강도와 지지 유지가 더 중요해집니다."
    )

    entry_view = entry_decision_view(setups)
    overall_text = (
        f"종목 매력도(Opportunity)는 {opp.score:.0f}점 · {grade_ko(opp.score)}입니다. 이 점수는 기업 품질, 추세·리더십, 상대강도, 모멘텀·수급, 시장환경을 합쳐 '관찰할 가치가 높은 종목인가'를 평가하며, 현재 가격이 바로 좋은 매수 가격이라는 뜻은 아닙니다. "
        f"현재 우선 방식은 {entry_view['approach']}, 진입 상태는 {entry_view['state']}, 위험 수준은 {risk_ko(risk.level)}, 시장 국면은 {market_label_ko(market.label)}입니다. "
        f"{opp.interpretation} 따라서 종목 매력도와 실제 진입 타이밍을 분리해서 보고, Entry Engine과 Risk Engine의 확인 조건을 함께 읽는 것이 V6의 핵심입니다."
    )
    return {"overall": overall_text, "company": company_text, "quant": quant_text, "entry": entry_text, "market": market_text}

def render_ai_briefings(a: dict):
    texts = build_briefings(a)
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("AI 종합 브리핑")
    briefing("종합 AI 브리핑", texts["overall"], "DECISION BRIEF", wide=True)
    c1, c2 = st.columns(2)
    with c1: briefing("기업 브리핑", texts["company"], "COMPANY")
    with c2: briefing("추세·퀀트 브리핑", texts["quant"], "QUANT / TREND")
    c3, c4 = st.columns(2)
    with c3: briefing("진입 브리핑", texts["entry"], "ENTRY SETUP")
    with c4: briefing("시장·리스크 브리핑", texts["market"], "MARKET / RISK")


def render_entry_engine(a: dict):
    setups = a["setups"]
    view = entry_decision_view(setups)
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("Entry Engine V3 · 진입 방식")
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("<div class='explain'><b>🎯 눌림목 진입 (Pullback Entry)</b><br>상승 구조를 유지한 종목이 EMA·지지구간 부근으로 조정받았는지 평가합니다. 좋은 종목을 더 유리한 가격에서 살 수 있는지, 손절 거리가 합리적인지, 거래량 감소가 건강한 조정인지 확인합니다.</div>", unsafe_allow_html=True)
    with e2:
        st.markdown("<div class='explain'><b>🚀 모멘텀 진입 (Momentum Entry)</b><br>저항 돌파·신고가 접근·상대강도·거래량 증가를 통해 강한 상승 흐름을 따라갈 수 있는지 평가합니다. RSI가 높더라도 강한 추세와 수급이 확인되면 단순 과열로 자동 감점하지 않습니다.</div>", unsafe_allow_html=True)

    pull_cls = entry_status_class(setups.pullback)
    mom_cls = entry_status_class(setups.momentum)
    st.markdown(
        f"<div class='entry-decision-grid'>"
        f"<div class='entry-decision-card'><div class='entry-decision-label'>눌림목 진입<br><span style='color:#64748b'>(Pullback Entry)</span></div><div class='entry-decision-value' style='color:{score_color(setups.pullback.score)}'>{setups.pullback.score:.1f}</div><div class='{pull_cls}' style='font-weight:850'>{setup_status_ko(setups.pullback)}</div></div>"
        f"<div class='entry-decision-card'><div class='entry-decision-label'>모멘텀 진입<br><span style='color:#64748b'>(Momentum Entry)</span></div><div class='entry-decision-value' style='color:{score_color(setups.momentum.score)}'>{setups.momentum.score:.1f}</div><div class='{mom_cls}' style='font-weight:850'>{setup_status_ko(setups.momentum)}</div></div>"
        f"<div class='entry-decision-card'><div class='entry-decision-label'>우선 방식<br><span style='color:#64748b'>(Preferred Approach)</span></div><div class='entry-decision-value'>{view['approach']}</div></div>"
        f"<div class='entry-decision-card'><div class='entry-decision-label'>현재 진입 상태<br><span style='color:#64748b'>(Entry Readiness)</span></div><div class='entry-decision-value {view['class']}'>{view['state']}</div></div>"
        f"</div><div class='entry-decision-interpretation'><b>해석</b><br>{view['interpretation']}</div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns(2)
    for col, setup, icon in ((c1, setups.pullback, "🎯"), (c2, setups.momentum, "🚀")):
        with col:
            setup_title = "눌림목 진입 상세 (Pullback Entry)" if setup.name == "Pullback" else "모멘텀 진입 상세 (Momentum Entry)"
            st.markdown(f"<div class='v6-kicker' style='margin:8px 0 10px'>{icon} {setup_title}</div>", unsafe_allow_html=True)
            factor_map = PULLBACK_FACTOR_KO if setup.name == "Pullback" else MOMENTUM_FACTOR_KO
            rows = [{"요소": factor_map.get(k, k), "점수": round(v,1), "해석": (f"{market_label_ko(a['market'].label)} {a['market'].score:.1f}" if k=="Market" else setup.details[k])} for k,v in setup.factors.items()]
            st.dataframe(
                pd.DataFrame(rows), hide_index=True, use_container_width=True, height=300,
                column_config={"점수": st.column_config.ProgressColumn("점수", min_value=0, max_value=100, format="%.1f")},
                key=f"entry_{setup.name}_{a['now']}",
            )
            zone = f"참고 Zone {money(setup.zone[0])} ~ {money(setup.zone[1])}" if setup.zone else "참고 Zone · 현재 명확한 Zone 없음"
            trigger = f"Trigger {money(setup.trigger)}" if setup.trigger else "Trigger · 해당 없음"
            invalid = f"Invalidation {money(setup.invalidation)}" if setup.invalidation else "Invalidation · N/A"
            st.caption(f"{zone}  ·  {trigger}  ·  {invalid}")

def render_risk_engine(a: dict):
    risk = a["risk"]
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("Risk Engine · 위험 점검")
    rcols = st.columns(5)
    items = [
        ("가격 확장 (Extension)", "extension", risk.extension, risk_state_ko(risk.extension), risk.details["Extension"]),
        ("변동성 (Volatility)", "volatility", risk.volatility, risk_state_ko(risk.volatility), risk.details["Volatility"]),
        ("실적 일정 (Earnings)", "earnings", risk.earnings, risk_state_ko(risk.earnings), risk.details["Earnings"]),
        ("유동성 (Liquidity)", "liquidity", risk.liquidity, risk_state_ko(risk.liquidity), risk.details["Liquidity"]),
        ("시장 위험 (Market Risk)", "market", risk.market, risk_state_ko(risk.market), f"{market_label_ko(a['market'].label)} · {a['market'].score:.1f}"),
    ]
    for col, (label, kind, raw, value, detail) in zip(rcols, items):
        with col:
            cls = risk_item_class(kind, raw)
            st.markdown(
                f"<div class='v6-card risk'><div class='v6-kicker'>{label}</div>"
                f"<div class='{cls}' style='font-size:1.22rem;font-weight:900;margin:7px 0 10px'>{value}</div>"
                f"<div class='v6-sub'>{detail}</div></div>",
                unsafe_allow_html=True,
            )
    overall_cls = "status-green" if risk.level == "LOW" else "status-yellow" if risk.level == "MODERATE" else "status-orange" if risk.level == "HIGH" else "status-red"
    st.markdown(
        f"<div class='risk-summary'><b>종합 위험도</b> · <span class='{overall_cls}'><b>{risk.score:.1f} / 100 · {risk_ko(risk.level)}</b></span> &nbsp; | &nbsp; "
        f"초기 비중 보정 <b>{risk.position_size_multiplier:.2f}×</b><br>위험은 종목 매력도(Opportunity)를 직접 깎기보다, 신규 진입 비중과 확인 조건을 보수적으로 조정하는 데 사용합니다.</div>",
        unsafe_allow_html=True,
    )

def render_company_summary(a: dict):
    company = a["company"]
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("기업 품질 (Company Quality V2)")
    st.caption(f"현재 재무 데이터 커버리지 {company.coverage*100:.0f}% · 평가 신뢰도 {company.confidence}. 제공되지 않은 재무 항목은 0점 처리하지 않고 점수 계산에서 제외합니다.")
    if company.notes:
        st.info(" ".join(company.notes))
    fcols = st.columns(5)
    for col, (label, value) in zip(fcols, company.factors.items()):
        with col:
            score_card(
                COMPANY_FACTOR_LABELS.get(label, label),
                value,
                COMPANY_FACTOR_GUIDE.get(label, "기업 품질의 세부 축을 평가합니다."),
                compact=True,
            )
    if company.relative:
        rel = pd.DataFrame([{"지표": k, "업종 상대점수": v} for k,v in company.relative.items() if v is not None])
        if not rel.empty:
            with st.expander("업종 상대평가 상세"):
                st.dataframe(rel, hide_index=True, use_container_width=True,
                             column_config={"업종 상대점수": st.column_config.ProgressColumn("업종 상대점수", min_value=0,max_value=100,format="%.1f")})
                st.caption("자동 동종업종 후보: " + (", ".join(a["peer_symbols"]) if a["peer_symbols"] else "후보가 충분하지 않습니다."))

def render_consensus(a: dict):
    cons = a["consensus"]
    company, tech, setups, market = a["company"], a["tech"], a["setups"], a["market"]
    quant = a["quant"]
    option_label = a.get("option_label", "N/A")

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("Analysis Consensus · 분석 관점 일치도")
    st.caption("종합 판단 요약이 '현재 이 종목의 상태'를 보여준다면, Consensus는 서로 다른 분석 관점이 그 판단을 얼마나 같은 방향으로 지지하는지 교차 확인합니다.")

    lens_cols = st.columns(5)
    lens_items = [
        ("기업 분석", "Company Quality", company.score, grade_ko(company.score) if company.score is not None else "데이터 부족", f"데이터 커버리지 {company.coverage*100:.0f}%"),
        ("퀀트·추세", "Quant / Trend", quant["score"], grade_ko(quant["score"]), f"퀀트 {quant['score']:.0f} · 추세 {tech.trend:.0f}"),
        ("진입 판단", "Entry Decision", max(setups.pullback.score, setups.momentum.score), entry_decision_view(setups)["approach"], f"현재 상태 {entry_decision_view(setups)['state']} · 눌림목 {setups.pullback.score:.0f} / 모멘텀 {setups.momentum.score:.0f}"),
        ("시장 국면", "Market Regime", market.score, market_label_ko(market.label), f"데이터 품질 {market.data_quality*100:.0f}%"),
        ("옵션 확인", "Options Confirmation", None, option_label if option_label != "N/A" else "N/A", "현물 판단의 보조 확인값"),
    ]
    for col, (ko, en, score, state, note) in zip(lens_cols, lens_items):
        with col:
            if score is None:
                shown, color = state, "#94a3b8"
            else:
                shown, color = f"{score:.1f}", score_color(float(score))
            st.markdown(
                f"<div class='v6-card consensus-lens'><div class='v6-kicker'>{ko}<br><span style='color:#64748b'>{en}</span></div>"
                f"<div class='v6-value' style='color:{color}'>{shown}</div>"
                f"<div style='font-weight:850;color:{color};line-height:1.35'>{state}</div>"
                f"<div class='v6-sub' style='margin-top:8px'>{note}</div></div>",
                unsafe_allow_html=True,
            )

    m1, m2 = st.columns(2)
    with m1:
        st.markdown(f"<div class='consensus-meter'><div class='label'>Signal Agreement · 신호 일치도</div><div class='value'>{cons.signal_agreement}%</div><div class='v6-sub'>각 렌즈의 방향이 얼마나 같은 쪽을 가리키는지 보여줍니다. 상승 확률이 아닙니다.</div></div>", unsafe_allow_html=True)
    with m2:
        st.markdown(f"<div class='consensus-meter'><div class='label'>Data Confidence · 데이터 신뢰도</div><div class='value'>{cons.data_confidence}%</div><div class='v6-sub'>재무·시장·옵션 등 원자료의 커버리지와 충실도를 나타냅니다.</div></div>", unsafe_allow_html=True)

    st.markdown(
        f"<div class='consensus-summary'><div class='v6-kicker'>CONSENSUS INTERPRETATION</div>"
        f"<b>{cons.headline}</b> · {cons.pattern}<br><br>{cons.interpretation}</div>",
        unsafe_allow_html=True,
    )
    with st.expander("Consensus 계산에 사용된 원래 Lens 상태 보기"):
        st.dataframe(pd.DataFrame([{"Lens":k,"판단":v} for k,v in cons.lenses.items()]), hide_index=True, use_container_width=True)
        st.caption("Signal Agreement는 렌즈 방향의 일치도, Data Confidence는 원자료 충실도입니다. 둘 다 미래 수익률이나 상승 확률을 뜻하지 않습니다.")


def render_scenarios(a: dict):
    setups, zones, tech = a["setups"], a["zones"], a["tech"]
    support = zones.supports[0] if zones.supports else None
    resistance = zones.resistances[0] if zones.resistances else None
    pull_zone = setups.pullback.zone or ((support.low,support.high) if support else None)
    trigger = setups.momentum.trigger or (resistance.center if resistance else tech.prior_high20)
    invalid = min(x for x in [setups.pullback.invalidation, setups.momentum.invalidation] if x is not None) if any(x is not None for x in [setups.pullback.invalidation,setups.momentum.invalidation]) else None
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("대응 시나리오")
    c1,c2,c3=st.columns(3)
    with c1:
        st.markdown(f"<div class='scenario up'><h4>🟢 Bull · 돌파 지속</h4><p><b>조건</b> {money(trigger)} 상향 돌파/지지 + 거래량 확인<br><b>대응</b> Momentum 점수가 유지될 때 소규모 분할 접근<br><b>확인</b> 상대강도와 거래량 동반 여부</p></div>", unsafe_allow_html=True)
    with c2:
        zone_txt = f"{money(pull_zone[0])} ~ {money(pull_zone[1])}" if pull_zone else "새 지지 Zone"
        st.markdown(f"<div class='scenario mid'><h4>🟡 Base · 눌림/지지</h4><p><b>조건</b> {zone_txt} 부근 안정화<br><b>대응</b> 지지 반응 확인 시 Pullback 분할 접근<br><b>주의</b> 지지 확인 전 박스 중앙 추격 자제</p></div>", unsafe_allow_html=True)
    with c3:
        st.markdown(f"<div class='scenario down'><h4>🔴 Bear · 무효화</h4><p><b>조건</b> {money(invalid)} 종가 이탈 또는 돌파 실패<br><b>대응</b> 신규 진입 중단·비중 축소 검토<br><b>재평가</b> 다음 지지 구간과 시장 국면 확인</p></div>", unsafe_allow_html=True)


def render_sr_and_chart(a: dict):
    tech,zones = a["tech"],a["zones"]
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("Support / Resistance Zones")
    left,right=st.columns(2)
    with left:
        st.markdown("**Support**")
        if not zones.supports: st.info("신뢰 가능한 Support Zone이 부족합니다.")
        for z in zones.supports:
            st.markdown(f"<div class='zone'><b>{money(z.low)} ~ {money(z.high)}</b> · {z.label} ({z.strength:.0f})<br><span class='v6-sub'>{' · '.join(z.sources)}</span></div>", unsafe_allow_html=True)
    with right:
        st.markdown("**Resistance**")
        if not zones.resistances: st.info("현재가 위의 명확한 Resistance Zone이 부족합니다.")
        for z in zones.resistances:
            st.markdown(f"<div class='zone r'><b>{money(z.low)} ~ {money(z.high)}</b> · {z.label} ({z.strength:.0f})<br><span class='v6-sub'>{' · '.join(z.sources)}</span></div>", unsafe_allow_html=True)

    st.subheader("가격 차트 · 지지와 저항")
    d=a["frame"].tail(252)
    fig=go.Figure(go.Candlestick(x=d.index,open=d.Open,high=d.High,low=d.Low,close=d.Close,name="Price"))
    for value,name_,color in ((tech.ema20,"EMA20","#38bdf8"),(tech.ema50,"EMA50","#f59e0b"),(tech.ema200,"EMA200","#a855f7")):
        fig.add_hline(y=value,line_dash="dot",line_color=color,annotation_text=name_)
    for z in zones.supports[:3]: fig.add_hrect(y0=z.low,y1=z.high,fillcolor="rgba(56,189,248,.08)",line_width=0)
    for z in zones.resistances[:3]: fig.add_hrect(y0=z.low,y1=z.high,fillcolor="rgba(251,113,133,.08)",line_width=0)
    fig.update_layout(height=550,xaxis_rangeslider_visible=False,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#0a1728",font=dict(color="#cbd5e1"),xaxis=dict(gridcolor="#20344d"),yaxis=dict(gridcolor="#20344d"))
    st.plotly_chart(fig,use_container_width=True)


def render_analysis(a: dict, symbol: str):
    inf,tech,market,company,risk,setups,opp = a["info"],a["tech"],a["market"],a["company"],a["risk"],a["setups"],a["opportunity"]
    name=inf.get("longName") or inf.get("shortName") or symbol
    st.header(f"{name} · {symbol}")
    st.caption(f"V6.0.9 종합분석 · 데이터 기준 {pd.Timestamp(a['frame'].index[-1]).date()} · {a['region']} Market · Sector {a['sector'] or 'N/A'}")

    st.subheader("종합 판단 요약")
    entry_view = entry_decision_view(setups)
    rcls=status_class(risk.level)
    st.markdown(f"""<div class='decision'><div class='v6-kicker'>V6 MULTI-LENS DECISION SUMMARY</div>
    <h2>종목 매력도 (Opportunity) {opp.score:.1f} · {grade_ko(opp.score)}</h2>
    <p><b>우선 방식 (Preferred Approach)</b> · <span class='{entry_view['class']}'>{entry_view['approach']}</span> &nbsp; | &nbsp; <b>현재 진입 상태</b> · <span class='{entry_view['class']}'>{entry_view['state']}</span><br>
    <b>위험</b> · <span class='{rcls}'>{risk_ko(risk.level)}</span> &nbsp; | &nbsp; <b>시장 국면</b> · {market_label_ko(market.label)}</p>
    <p>{opp.interpretation} {entry_view['interpretation']}</p></div>""", unsafe_allow_html=True)

    cols=st.columns(5)
    items=[
        ("종목 매력도 (Opportunity)",opp.score,"좋은 종목인가를 평가 · Entry/Risk는 별도"),
        ("기업 품질 (Company Quality)",company.score,f"데이터 커버리지 {company.coverage*100:.0f}% · {company.confidence}"),
        ("추세·리더십 (Trend / Leadership)",tech.trend,f"12M {tech.ret_12m:+.1f}%"),
        ("상대강도 (Relative Strength)",tech.relative_strength,"시장 벤치마크 대비 가격 리더십"),
        ("모멘텀·수급 (Momentum / Demand)",.60*tech.momentum+.40*tech.demand,f"RSI {tech.rsi:.1f} · 거래량 {tech.volume_ratio:.2f}x"),
    ]
    for col,item in zip(cols,items):
        with col: score_card(*item, summary=True)

    # 사용자가 가장 먼저 읽을 수 있는 해설 → 실행 판단 → 위험 → 교차검증 순서
    render_ai_briefings(a)
    render_entry_engine(a)
    render_risk_engine(a)
    render_consensus(a)

    traj=reconstructed_trajectory(a,10)
    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    with st.expander("종목 매력도 · 눌림목 진입 · 모멘텀 진입 점수 읽는 법", expanded=False):
        st.markdown("""
- **종목 매력도 (Opportunity)**: 기업 품질·추세·상대강도·모멘텀/수급·시장환경을 종합해 **관찰할 가치가 높은 종목인지** 평가합니다. 현재 매수가격이 좋은지와는 별개입니다.
- **눌림목 진입 (Pullback Entry)**: 상승 구조를 유지하면서 지지구간·EMA 부근으로 조정됐는지 평가합니다. 가격 메리트와 손절 거리, 건강한 거래량 감소를 중요하게 봅니다.
- **모멘텀 진입 (Momentum Entry)**: 돌파·신고가 접근·상대강도·거래량 증가를 이용해 **강한 흐름을 따라갈 수 있는지** 평가합니다. RSI가 높다는 이유만으로 자동 감점하지 않습니다.
        """)
    trajectory_chart(traj,["Opportunity","Pullback","Momentum Entry"],f"overall_traj_{symbol}","최근 10영업일 · 종목 매력도와 진입 변화")

    # 아래부터는 판단의 근거를 더 깊게 보는 상세 영역
    render_company_summary(a)

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("시장 국면 상세 (Market Regime)")
    m1,m2=st.columns([1,2])
    with m1: score_card(f"{market_region_ko(market.market)} 시장 국면 (Market Regime)",market.score,f"{market_label_ko(market.label)} · 데이터 품질 {market.data_quality*100:.0f}%")
    with m2:
        st.dataframe(market_components_frame(market),hide_index=True,use_container_width=True,height=190,column_config={"점수":st.column_config.ProgressColumn("점수", min_value=0, max_value=100, format="%.1f")})
    st.caption(f"{market_region_ko(market.market)} 시장은 현재 **{market_label_ko(market.label)}** 상태로 해석합니다. 지수·업종·변동성·신용·환율 등 구성요소를 함께 확인하세요.")

    render_scenarios(a)
    render_sr_and_chart(a)

    data_date=pd.Timestamp(a["frame"].index[-1]).date()
    HISTORY.record(symbol,{"opportunity":opp.score,"company":company.score,"trend":tech.trend,"momentum":tech.momentum,"relative_strength":tech.relative_strength,"pullback":setups.pullback.score,"momentum_entry":setups.momentum.score,"market":market.score,"risk":risk.score,"preferred_setup":setups.preferred},data_date,{"version":"6.0.6","source":"recorded"})

    with st.expander("최근 뉴스"):
        rows=news(symbol)
        if not rows: st.info("현재 불러온 뉴스가 없습니다.")
        for title,summary,url in rows:
            st.markdown(f"**[{title}]({url})**" if url else f"**{title}**")
            st.caption((summary or "제목 기반 참고 뉴스")[:260])


def render_quant_chart(a: dict):
    q=a["quant"]; d=a["frame"].tail(130); idx=d.index; chart=q["chart"]
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[.72,.28],vertical_spacing=.04,specs=[[{}],[{"secondary_y":True}]])
    fig.add_trace(go.Scatter(x=idx,y=d.Close,line=dict(color="#f8fafc",width=2.5),name="Close"),row=1,col=1)
    for srs,n,c,ds in [(chart["ema20"],"EMA20","#3b82f6",None),(chart["ema50"],"EMA50","#f59e0b",None),(chart["ema200"],"EMA200","#a855f7","dash")]:
        fig.add_trace(go.Scatter(x=idx,y=srs.reindex(idx),line=dict(color=c,width=1.6,dash=ds),name=n),row=1,col=1)
    fig.add_trace(go.Scatter(x=idx,y=chart["bb_upper"].reindex(idx),line=dict(color="#64748b",width=1,dash="dot"),name="BB Upper"),row=1,col=1)
    fig.add_trace(go.Scatter(x=idx,y=chart["bb_lower"].reindex(idx),line=dict(color="#64748b",width=1,dash="dot"),fill="tonexty",fillcolor="rgba(100,116,139,.08)",name="BB Lower"),row=1,col=1)
    colors=np.where(d.Close>=d.Open,"#38bdf8","#fb7185")
    fig.add_trace(go.Bar(x=idx,y=d.Volume,marker_color=colors,name="Volume"),row=2,col=1)
    fig.add_trace(go.Scatter(x=idx,y=chart["obv"].reindex(idx),line=dict(color="#f59e0b",width=1.5),name="OBV"),row=2,col=1,secondary_y=True)
    fig.update_layout(height=590,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="#0a1728",font=dict(color="#cbd5e1"),legend=dict(orientation="h"),margin=dict(l=30,r=25,t=55,b=25))
    fig.update_xaxes(gridcolor="#20344d"); fig.update_yaxes(gridcolor="#20344d")
    st.plotly_chart(fig,use_container_width=True)


def render_can_slim(a: dict):
    q=a["quant"]; can=q["can_slim"]
    desc={"C":"최근 이익·매출 성장","A":"연간 수익성·ROE","N":"신고가·새로운 모멘텀","S":"거래량 수급","L":"시장 주도력","I":"기관 수급 대용","M":"시장 방향"}
    guide={
        "C":"최근 EPS/매출 성장률을 결합합니다. 극단값은 기저효과·일회성 이익을 확인해야 합니다.",
        "A":"ROE와 Profitability를 중심으로 장기 수익성을 봅니다.",
        "N":"추세와 52주 가격 위치를 결합해 새로운 모멘텀 여부를 봅니다.",
        "S":"최근 거래량과 Demand를 결합합니다. Pullback과 Momentum에서는 거래량 의미가 다를 수 있습니다.",
        "L":"시장 대비 Relative Strength와 추세 리더십을 봅니다.",
        "I":"OBV·거래량 기반 Demand 대용지표이며 실제 기관 보유자료는 아닙니다.",
        "M":"현재 미국/한국 시장 국면 점수입니다.",
    }
    st.subheader("CAN SLIM 분석")
    st.caption("V6의 Opportunity 점수와 별개의 보조 프레임워크입니다. 원형 CAN SLIM의 공개 데이터 대용지표를 사용하며 제공되지 않은 값은 임의로 0점 처리하지 않습니다.")
    cols=st.columns(4)
    for i,(k,v) in enumerate(can.items()):
        with cols[i%4]: score_card(f"{k} · {desc[k]}",v,guide[k],compact=True)
    with st.expander("CAN SLIM 점수 읽는 법"):
        st.markdown("**공통 기준** · 50점은 중립, 65점 이상은 우호적, 80점 이상은 강한 신호로 봅니다. 한 항목의 고득점보다 여러 항목이 함께 개선되는지가 중요합니다.\n\nCAN SLIM은 V6의 주 점수에 중복 합산하지 않고, 다른 관점에서 현재 상태를 읽는 보조 렌즈로 사용합니다.")


def render_aux_quant(a: dict):
    aux=a["quant"]["aux"]
    guides={
        "평균회귀":"최근 평균에서 벗어난 정도입니다. 50은 중립, 높을수록 평균 아래에서 반등 여지가 커질 수 있습니다.",
        "모멘텀":"RSI·최근 수익률·MACD·ADX를 결합한 상승 추진력입니다.",
        "다중 시간대":"중기·장기 이동평균과 수익률 정렬 정도입니다.",
        "낙폭 위치":"최근 고점 대비 낙폭을 상태 점수로 변환합니다. 미래 하락 위험을 보장하지 않습니다.",
        "수급 흐름":"거래량·OBV·상승/하락 거래량을 이용한 Demand 대용지표입니다.",
        "Target Price Factor":"현재가에서 가장 가까운 상단 Resistance Zone까지의 여유를 단순 참고점수로 변환합니다. 공식 목표주가가 아닙니다.",
        "통계적 Z-Score":"최근 60일 평균에서 가격이 얼마나 벗어났는지 변환한 상태점수입니다.",
        "Relative Strength":"시장 벤치마크보다 얼마나 강한 흐름인지 보여줍니다.",
        "Extension Balance":"EMA20 이격과 RSI를 이용해 추격 부담을 봅니다. Momentum 자체의 강도와는 별도입니다.",
    }
    with st.expander("보조 퀀트 지표",expanded=False):
        st.caption("보조 점수는 50을 중립으로 읽습니다. 방향 확인용이며 단독 매수·매도 신호로 사용하지 않습니다.")
        cols=st.columns(2)
        for i,(k,v) in enumerate(aux.items()):
            with cols[i%2]: score_card(AUX_LABELS.get(k,k),v,guides[k],compact=True)


def render_peer_comparison(a: dict, symbol: str):
    st.subheader("동일/유사 업종 경쟁사 비교")
    defaults=[symbol]+list(a["peer_symbols"])
    raw=st.text_input("비교 티커 · 쉼표로 수정",value=", ".join(defaults),key=f"peer_edit_{symbol}")
    symbols=list(dict.fromkeys([x.strip().upper() for x in raw.split(",") if x.strip()]))[:6]
    rows=[]
    for ticker in symbols:
        payload=info(ticker)
        try:
            d=prices(ticker,"1y"); c=d.Close.dropna(); ret=(c.iloc[-1]/c.iloc[0]-1)*100 if len(c)>1 else np.nan
        except Exception: ret=np.nan
        rows.append({
            "종목":payload.get("shortName") or payload.get("longName") or ticker,"티커":ticker,
            "시가총액":(payload.get("marketCap") or np.nan)/1e9,"PER":payload.get("trailingPE",np.nan),"PBR":payload.get("priceToBook",np.nan),
            "ROE":(payload.get("returnOnEquity") or np.nan)*100,"영업이익률":(payload.get("operatingMargins") or np.nan)*100,"12M":ret,
        })
    pf=pd.DataFrame(rows)
    if pf.empty:
        st.info("비교 가능한 경쟁사 데이터가 없습니다.")
    else:
        st.dataframe(pf.style.format({"시가총액":"{:,.1f}B","PER":"{:.1f}","PBR":"{:.2f}","ROE":"{:.1f}%","영업이익률":"{:.1f}%","12M":"{:+.1f}%"},na_rep="—"),hide_index=True,use_container_width=True)
    st.caption("자동 후보군은 참고용이며 직접 티커를 수정할 수 있습니다. 사업구조가 다른 기업이 섞일 수 있으므로 단순 수치 비교보다 업종·성장단계 차이를 함께 확인하세요.")


def render_quant_analysis(a: dict, symbol: str):
    inf,tech,company,q=a["info"],a["tech"],a["company"],a["quant"]
    name=inf.get("longName") or inf.get("shortName") or symbol
    st.header(f"퀀트분석 · {name} ({symbol})")
    st.caption("V6 퀀트 종합점수는 기업 품질 + 추세 + 모멘텀 + 수급 + 상대강도를 묶은 설명용 정량 점수입니다. 시장 국면과 진입 점수는 중복을 피하기 위해 별도로 봅니다.")
    c1,c2,c3,c4,c5=st.columns(5)
    for col,(label,value,sub) in zip([c1,c2,c3,c4,c5],[
        ("퀀트 종합 (Quant Composite)",q["score"],"시장환경·진입 점수 제외"),("추세 (Trend)",tech.trend,"중장기 구조"),("모멘텀 (Momentum)",tech.momentum,f"RSI {tech.rsi:.1f}"),("수급 (Demand)",tech.demand,f"거래량 {tech.volume_ratio:.2f}x"),("상대강도 (Relative Strength)",tech.relative_strength,"시장 대비"),
    ]):
        with col: score_card(label,value,sub)

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("AI 퀀트 브리핑")
    q_state = grade_ko(q["score"])
    trend_view = "중장기 추세가 강하게 유지되고 있습니다." if tech.trend >= 75 else "중장기 추세는 우호적이지만 추가 확인이 필요합니다." if tech.trend >= 60 else "중장기 추세가 아직 뚜렷하지 않습니다."
    momentum_view = "단기 모멘텀도 강합니다." if tech.momentum >= 75 else "단기 모멘텀은 중립권입니다." if tech.momentum >= 45 else "단기 모멘텀이 약합니다."
    demand_view = "거래량과 수급이 상승 흐름을 확인하고 있습니다." if tech.demand >= 65 else "거래량·수급 확인은 아직 제한적입니다."
    rs_view = "시장 대비 상대강도가 매우 우수합니다." if tech.relative_strength >= 80 else "시장 대비 상대강도는 우호적입니다." if tech.relative_strength >= 65 else "시장 대비 상대강도 우위는 뚜렷하지 않습니다."
    briefing(
        "퀀트 종합 브리핑",
        f"퀀트 종합점수는 {q['score']:.1f}점({q_state})입니다. 추세 {tech.trend:.1f}점, 모멘텀 {tech.momentum:.1f}점, 수급 {tech.demand:.1f}점, 상대강도 {tech.relative_strength:.1f}점입니다. {trend_view} {momentum_view} {demand_view} {rs_view}",
        "QUANT DECISION",
        wide=True,
    )
    qb1, qb2 = st.columns(2)
    with qb1:
        briefing("추세·모멘텀 해석", f"추세 {tech.trend:.1f}점 · 모멘텀 {tech.momentum:.1f}점 · RSI {tech.rsi:.1f}. {trend_view} {momentum_view}", "TREND / MOMENTUM")
    with qb2:
        briefing("수급·상대강도 해석", f"수급 {tech.demand:.1f}점 · 거래량 {tech.volume_ratio:.2f}배 · 상대강도 {tech.relative_strength:.1f}점. {demand_view} {rs_view}", "DEMAND / RS")

    traj=reconstructed_trajectory(a,10)
    st.markdown("<div class='v6-section'></div>",unsafe_allow_html=True)
    trajectory_chart(traj,["Quant","Trend","Momentum"],f"quant_traj_{symbol}","퀀트 점수 · 최근 10영업일 변화")
    if not traj.empty:
        first,last=traj.iloc[0],traj.iloc[-1]
        st.info(f"최근 10영업일 참고 흐름 · 퀀트 종합 {first['Quant']:.0f} → {last['Quant']:.0f}, 추세 {first['Trend']:.0f} → {last['Trend']:.0f}, 모멘텀 {first['Momentum']:.0f} → {last['Momentum']:.0f}")

    st.markdown("<div class='v6-section'></div>",unsafe_allow_html=True)
    st.subheader("가격 · 추세 · 거래량")
    render_quant_chart(a)
    st.info(f"핵심 관찰 · 현재 52주 범위의 {q['position52']:.1f}% 위치 · Trend {tech.trend:.1f} · RSI {tech.rsi:.1f} · 거래량 {tech.volume_ratio:.2f}x · Relative Strength {tech.relative_strength:.1f}")

    st.markdown("<div class='v6-section'></div>",unsafe_allow_html=True)
    render_can_slim(a)
    render_aux_quant(a)

    st.markdown("<div class='v6-section'></div>",unsafe_allow_html=True)
    st.subheader("기술 지표")
    for label,value,guide in q["technical_rows"]:
        tone="bad" if label=="ATR%" and tech.atr_pct>=6 else "good" if label in ("12M 수익률","3M 수익률") and not value.startswith("-") else "neutral"
        indicator_row(label,value,guide,tone)

    st.markdown("<div class='v6-section'></div>",unsafe_allow_html=True)
    st.subheader("재무 지표")
    for label,value,guide in financial_rows(company,inf): indicator_row(label,value,guide,"neutral")

    render_peer_comparison(a,symbol)


def pulse_card(name: str, ticker: str, key: str):
    try:
        daily=prices(ticker,"1mo","1d"); c=daily.Close.dropna()
        if len(c)<2:
            raise ValueError
        current=float(c.iloc[-1]); change=(current/float(c.iloc[-2])-1)*100
        try:
            intraday=prices(ticker,"5d","15m"); s=intraday.Close.dropna().tail(40)
            y=(s/s.iloc[0]-1)*100 if len(s)>2 else (c.tail(20)/c.tail(20).iloc[0]-1)*100
            x=s.index if len(s)>2 else c.tail(20).index
        except Exception:
            y=(c.tail(20)/c.tail(20).iloc[0]-1)*100; x=c.tail(20).index
        color="#34d399" if change>=0 else "#fb7185"
        arrow="▲" if change>=0 else "▼"
        st.markdown(
            f"<div class='pulse-shell'><div class='pulse-head'><b>{name}</b><span style='color:{color};font-weight:850'>{arrow} {abs(change):.2f}%</span></div>"
            f"<div class='v6-value' style='font-size:1.35rem;margin-top:7px'>{money(current)}</div>"
            f"<div class='v6-sub'>{PULSE_GUIDE.get(name,'시장 흐름을 확인하는 보조지표입니다.')}</div></div>",
            unsafe_allow_html=True,
        )
        fig=go.Figure(go.Scatter(x=x,y=y,mode="lines",line=dict(width=2.2,color=color),fill="tozeroy"))
        fig.add_hline(y=0,line_width=1,line_color="#64748b")
        fig.update_layout(height=74,margin=dict(l=2,r=2,t=2,b=0),showlegend=False,paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",xaxis_visible=False,yaxis_visible=False)
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False},key=key)
    except Exception:
        st.markdown(f"<div class='pulse-shell'><b>{name}</b><div class='v6-sub'>데이터 없음 · {PULSE_GUIDE.get(name,'')}</div></div>",unsafe_allow_html=True)


def regime_history(symbol: str, sector: str, count: int = 10) -> pd.DataFrame:
    try:
        ref=prices("^GSPC" if market_for_symbol(symbol)=="US" else "^KS11","3mo")
        dates=list(ref.index[-max(count*3,count):])
        rows=[]
        for dt in dates:
            try:
                snap=build_market_regime(symbol,sector,prices,as_of=pd.Timestamp(dt).date())
                rows.append({"date":pd.Timestamp(dt),"Market Regime":snap.score})
            except Exception:
                continue
        return pd.DataFrame(rows).tail(count).reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


def render_market_dashboard():
    st.header("시장환경 대시보드")
    st.caption("V6의 미국/한국 시장 국면 판단에 V5의 Market Health·10영업일 변화·Market Pulse·금리/신용시장 해석을 결합했습니다.")

    selected = st.radio("시장 기준", ["미국 시장", "한국 시장"], horizontal=True, key="market_dashboard_region")
    is_us = selected == "미국 시장"
    market = build_market_regime("SPY" if is_us else "005930.KS", "technology", prices)
    history_symbol = "SPY" if is_us else "005930.KS"

    top1, top2, top3 = st.columns([1.05, .9, 1.45])
    with top1:
        score_card("시장 건강도", market.score, f"{market_label_ko(market.label)} · 데이터 품질 {market.data_quality*100:.0f}%")
    with top2:
        st.metric("시장 등급", market_label_ko(market.label))
        confidence = min(95, round(55 + abs(market.score - 50) * .7 + market.data_quality * 15))
        st.metric("판단 신뢰도", f"{confidence}%")
    with top3:
        if market.score >= 65:
            brief = "시장 위험선호가 우호적입니다. 강한 종목의 추세 지속 가능성을 열어두되 과열·변동성은 별도로 확인하세요."
        elif market.score >= 48:
            brief = "시장 방향성이 혼재합니다. 지수보다 종목별 상대강도와 지지 확인, 비중 관리가 더 중요합니다."
        else:
            brief = "위험회피 성격이 강합니다. 신규 진입 기준을 높이고 현금·손절·무효화 기준을 보수적으로 관리하는 편이 유리합니다."
        briefing("AI 시장 브리핑", f"{selected} 국면 점수는 {market.score:.1f}점이며 {market_label_ko(market.label)} 상태입니다. {brief}", "MARKET BRIEF", wide=True)

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    trajectory_chart(
        regime_history(history_symbol, "technology", 10),
        ["Market Regime"],
        f"market_regime_10d_{'us' if is_us else 'kr'}",
        f"{selected} · 최근 10영업일 시장 국면 변화",
    )

    with st.expander("시장 국면 구성요소 상세", expanded=False):
        st.dataframe(
            market_components_frame(market),
            hide_index=True,
            use_container_width=True,
            column_config={"점수": st.column_config.ProgressColumn("점수", min_value=0, max_value=100, format="%.1f")},
        )
        st.caption(f"{selected}은 현재 **{market_label_ko(market.label)}** 상태로 해석합니다. 개별 구성요소보다 여러 축이 같은 방향으로 움직이는지 확인하는 것이 중요합니다.")

    with st.expander("Market Pulse 12 · 주요 자산", expanded=False):
        st.caption("각 자산의 최근 변화와 의미를 함께 표시합니다. 하루 상승/하락만으로 시장 국면을 단정하지 말고, 10영업일 추세와 함께 보세요.")
        items=list(PULSE.items())
        for i in range(0,len(items),4):
            cols=st.columns(4)
            for j,(name,ticker) in enumerate(items[i:i+4]):
                with cols[j]:
                    pulse_card(name,ticker,f"pulse_{ticker}_{i+j}")

    with st.expander("금리 · 신용시장 보조 패널", expanded=False):
        st.caption("금리와 신용시장은 주식의 할인율과 위험선호를 확인하는 보조 축입니다. 한 지표의 하루 움직임보다 방향과 조합을 함께 보세요.")
        cols=st.columns(4)
        try:
            official_rates=treasury_yields()
        except Exception:
            official_rates=pd.DataFrame()

        yahoo_fallback={"US 5Y":"^FVX","US 10Y":"^TNX","US 30Y":"^TYX"}
        rate_values={}
        for col,name in zip(cols,["US 2Y","US 5Y","US 10Y","US 30Y"]):
            try:
                series=pd.Series(dtype=float)
                source=""
                if not official_rates.empty and name in official_rates:
                    series=official_rates[name].dropna()
                    source="미 재무부"
                if series.empty and name in yahoo_fallback:
                    series=prices(yahoo_fallback[name],"1mo").Close.dropna()
                    source="Yahoo"
                if len(series)<1:
                    raise ValueError
                val=float(series.iloc[-1])
                ch=val-float(series.iloc[-2]) if len(series)>1 else np.nan
                rate_values[name]=val
                col.metric(name,f"{val:.2f}%",None if not np.isfinite(ch) else f"{ch:+.2f}%p")
                col.caption(RATE_GUIDE[name]+f" · {source}")
            except Exception:
                col.metric(name,"N/A")
                col.caption(RATE_GUIDE[name])

        cols=st.columns(4)
        for col,(name,ticker) in zip(cols[:2],[("HYG","HYG"),("LQD","LQD")]):
            try:
                c=prices(ticker,"1mo").Close.dropna(); val=float(c.iloc[-1]); ch=(val/c.iloc[-2]-1)*100
                col.metric(name,money(val),pct(ch))
            except Exception:
                col.metric(name,"N/A")
            col.caption(RATE_GUIDE[name])
        spread_curve=rate_values.get("US 10Y",np.nan)-rate_values.get("US 2Y",np.nan)
        cols[2].metric("10Y-2Y",f"{spread_curve:+.2f}%p" if np.isfinite(spread_curve) else "N/A")
        cols[2].caption(RATE_GUIDE["10Y-2Y"])
        try:
            hyg=prices("HYG","6mo").Close.squeeze(); lqd=prices("LQD","6mo").Close.squeeze()
            spread=(hyg.iloc[-1]/hyg.iloc[-20]-lqd.iloc[-1]/lqd.iloc[-20])*100
            cols[3].metric("Credit Spread proxy",f"{spread:+.2f}%")
        except Exception:
            cols[3].metric("Credit Spread proxy","N/A")
        cols[3].caption(RATE_GUIDE["Credit Spread proxy"])


def render_scanner_section():
    st.markdown("### 🔥 V6 종목 스캐너")
    st.caption("시장 전체를 훑어 **종목 매력도 / 모멘텀 진입 / 눌림목 진입** 후보를 찾습니다. 개별 종목 분석과는 별도의 후보 탐색 기능입니다.")

    with st.expander("스캐너 점수 읽는 법", expanded=False):
        st.markdown("""
- **종목 매력도 상위**: 추세·상대강도·모멘텀·수급·시장환경을 빠르게 스캔한 예비 순위입니다. 속도를 위해 개별 종목의 Company Quality는 상세 분석에서 다시 계산합니다.
- **모멘텀 진입 후보**: 돌파·추세·거래량·상대강도가 우호적인 종목을 찾습니다. 강한 흐름을 따라가는 전략입니다.
- **눌림목 진입 후보**: 상승 구조를 유지하면서 지지구간이나 이동평균 부근으로 조정된 종목을 찾습니다. 가격 메리트와 지지 가능성을 중시합니다.
        """)

    market_name=st.radio("시장",["NASDAQ 100","S&P 500","KOSPI","KOSDAQ"],horizontal=True,key="scanner_market")
    if st.button("스캐너 실행 / 갱신",type="primary",key="run_scanner"):
        with st.spinner(f"{market_name}의 후보를 계산하는 중입니다..."):
            region_symbol="005930.KS" if market_name in ("KOSPI","KOSDAQ") else "SPY"
            regime=build_market_regime(region_symbol,"technology",prices)
            bench=prices("^KS11" if market_name in ("KOSPI","KOSDAQ") else "^GSPC","18mo")
            scan,as_of=scan_market(market_name,regime,bench,universe_limit=220 if market_name!="S&P 500" else 320)
            st.session_state["scan_result"]=scan
            st.session_state["scan_as_of"]=as_of
            st.session_state["scan_market"]=market_name

    scan=st.session_state.get("scan_result",pd.DataFrame())
    if not scan.empty:
        st.caption(f"{st.session_state.get('scan_as_of','-')} 종가 기준 · {st.session_state.get('scan_market','')}")
        views=top_views(scan)
        tab_defs=[
            ("🔥 종목 매력도 상위","Opportunity Leaders"),
            ("🚀 모멘텀 진입 후보","Momentum Setups"),
            ("🎯 눌림목 진입 후보","Pullback Setups"),
        ]
        tabs=st.tabs([x[0] for x in tab_defs])
        for tab,(_,key) in zip(tabs,tab_defs):
            with tab:
                frame=views[key].copy()
                shown=frame[["Name","Symbol","Opportunity Proxy","Trend","RS","Momentum","Pullback","Pullback Status","Momentum Entry","Momentum Status","Risk"]].copy()
                shown["Pullback Status"]=shown["Pullback Status"].map(lambda x:PULLBACK_STATUS.get(x,x))
                shown["Momentum Status"]=shown["Momentum Status"].map(lambda x:MOMENTUM_STATUS.get(x,x))
                shown["Risk"]=shown["Risk"].map(risk_ko)
                shown=shown.rename(columns={
                    "Name":"종목","Symbol":"티커","Opportunity Proxy":"종목 매력도(예비)","Trend":"추세",
                    "RS":"상대강도","Momentum":"모멘텀","Pullback":"눌림목 진입",
                    "Pullback Status":"눌림목 상태","Momentum Entry":"모멘텀 진입",
                    "Momentum Status":"모멘텀 상태","Risk":"위험",
                })
                event=st.dataframe(shown,hide_index=True,use_container_width=True,on_select="rerun",selection_mode="single-row",key=f"scan_{key}")
                selected=event.selection.rows if event and hasattr(event,"selection") else []
                if selected:
                    row=frame.iloc[selected[0]]
                    st.session_state["symbol"]=row.Symbol
                    st.success(f"선택 종목: {row.Name} · {row.Symbol} — 아래 개별 종목 분석에서 바로 확인할 수 있습니다.")
    else:
        st.info("스캐너 실행 버튼을 누르면 선택한 시장의 후보를 계산합니다.")


def _cal_row(summary: pd.DataFrame, setup: str):
    if summary.empty:
        return None
    rows = summary.loc[summary["Setup"] == setup]
    return rows.iloc[0] if not rows.empty else None


def _safe_num(row, key: str, default=np.nan):
    try:
        value = float(row[key])
        return value if np.isfinite(value) else default
    except Exception:
        return default


def _validation_sample_confidence(n: int) -> tuple[str, str, str]:
    """Readable sample-size guide for 20D non-overlapping validation cases."""
    if n < 5:
        return "매우 제한적", "status-red", "검증 사례가 적어 결과 변동성이 큽니다. 참고 수준으로만 보세요."
    if n < 10:
        return "제한적", "status-orange", "방향성은 참고할 수 있지만 몇 사례의 영향이 크게 남을 수 있습니다."
    if n < 15:
        return "참고 가능", "status-yellow", "반복되는 경향을 보기 시작할 수 있으나 시장 국면 차이를 함께 확인해야 합니다."
    return "비교적 충분", "status-green", "현재 검증창의 20D 비중복 기준에서는 비교적 많은 사례가 확보됐습니다. 그래도 미래 확률로 해석하지 않습니다."


def _calibration_style(summary: pd.DataFrame) -> tuple[str, str, str]:
    """Simple, explainable comparison of the two historical entry styles."""
    p, m = _cal_row(summary, "Pullback"), _cal_row(summary, "Momentum")
    if p is None or m is None:
        return "❔ 판단 자료 부족", "status-muted", "두 진입 방식의 과거 자료가 모두 확보되지 않아 성향을 비교하기 어렵습니다."
    p_n, m_n = int(p.get("Validation 20D", 0)), int(m.get("Validation 20D", 0))
    if p_n < 5 and m_n < 5:
        return "❔ 판단 자료 부족", "status-muted", "20D 검증 사례가 적어 눌림목형·모멘텀형을 구분하기에는 아직 표본이 부족합니다."

    p_points = m_points = 0
    p_med, m_med = _safe_num(p, "Median 20D"), _safe_num(m, "Median 20D")
    p_hit, m_hit = _safe_num(p, "Hit 20D"), _safe_num(m, "Hit 20D")
    p_mdd, m_mdd = _safe_num(p, "Avg MDD20"), _safe_num(m, "Avg MDD20")
    if np.isfinite(p_med) and np.isfinite(m_med) and abs(p_med - m_med) >= 3:
        p_points += p_med > m_med
        m_points += m_med > p_med
    if np.isfinite(p_hit) and np.isfinite(m_hit) and abs(p_hit - m_hit) >= 10:
        p_points += p_hit > m_hit
        m_points += m_hit > p_hit
    if np.isfinite(p_mdd) and np.isfinite(m_mdd) and abs(p_mdd - m_mdd) >= 2:
        p_points += p_mdd > m_mdd  # less negative drawdown is better
        m_points += m_mdd > p_mdd

    if p_n >= 5 and p_points >= 2 and p_points > m_points:
        return "🎯 눌림목형", "status-teal", "이 검증기간에서는 강한 상승을 추격하기보다 조정·지지 구간을 활용한 눌림목 접근이 상대적으로 더 안정적이거나 효율적인 결과를 보였습니다."
    if m_n >= 5 and m_points >= 2 and m_points > p_points:
        return "🚀 모멘텀형", "status-green", "이 검증기간에서는 조정을 오래 기다리기보다 강한 돌파·추세를 따라가는 모멘텀 접근이 상대적으로 더 좋은 결과를 보였습니다."
    if p_n >= 5 and m_n >= 5:
        return "⚖️ 혼합형", "status-blue", "두 진입 방식 모두 의미 있는 과거 사례가 있으며 어느 한쪽이 뚜렷하게 우월하다고 보기 어렵습니다. 현재 Setup의 완성도와 Risk를 함께 보는 편이 좋습니다."
    return "❔ 자료 제한", "status-muted", "한쪽 진입 방식의 20D 검증 사례가 부족해 종목의 Entry 성향을 단정하기 어렵습니다. 충분한 사례가 있는 쪽은 참고자료로만 활용하세요."


def _strategy_validation_text(row, setup: str) -> tuple[str, str]:
    ko = "눌림목 진입" if setup == "Pullback" else "모멘텀 진입"
    if row is None or int(row.get("Validation 20D", 0)) == 0:
        return "자료 부족", f"검증 기준 이상인 {ko}의 20D 비중복 검증 사례가 없어 과거 성과를 해석하기 어렵습니다."

    n = int(row.get("Validation 20D", 0))
    episodes = int(row.get("Episodes", 0))
    hit = _safe_num(row, "Hit 20D")
    med = _safe_num(row, "Median 20D")
    avg = _safe_num(row, "Avg 20D")
    mdd = _safe_num(row, "Avg MDD20")
    conf, _, conf_note = _validation_sample_confidence(n)

    if n < 5:
        tone = "자료 제한"
    elif np.isfinite(hit) and np.isfinite(med) and hit >= 70 and med > 0:
        tone = "과거 결과 우호적"
    elif np.isfinite(hit) and np.isfinite(med) and hit >= 55 and med > 0:
        tone = "과거 결과 보통 이상"
    else:
        tone = "과거 결과 혼조"

    parts = [f"Setup 구간은 {episodes}회였고, 20영업일 성과가 서로 지나치게 겹치지 않도록 최소 20거래일 간격으로 추린 검증 사례 {n}회를 기준으로 봅니다."]
    if np.isfinite(hit):
        parts.append(f"이 중 20영업일 뒤 상승한 사례 비율은 {hit:.0f}%였습니다.")
    if np.isfinite(med) and np.isfinite(avg):
        gap = abs(avg - med)
        parts.append(f"대표 수익률(중앙값)은 {med:+.1f}%, 평균 수익률은 {avg:+.1f}%였습니다.")
        if gap >= 6:
            parts.append("평균과 대표 수익률 차이가 커 일부 큰 상승·하락 사례가 평균에 영향을 줬을 가능성이 있습니다.")
        else:
            parts.append("평균과 대표 수익률이 크게 벌어지지 않아 결과가 특정 한두 사례에만 치우친 정도는 상대적으로 작습니다.")
    if np.isfinite(mdd):
        parts.append(f"진입 후 20영업일 동안의 평균 최대 하락폭은 {mdd:.1f}%였습니다.")
    parts.append(f"표본 신뢰도는 '{conf}'입니다. {conf_note}")
    return tone, " ".join(parts)


def _historical_alignment(setup_name: str, current_score: float, threshold: int, row) -> tuple[str, str, str]:
    ko = "눌림목" if setup_name == "Pullback" else "모멘텀"
    if current_score < threshold:
        return "아직 확인 필요", "status-yellow", f"현재 {ko} 진입 점수 {current_score:.1f}점은 과거 검증 사례 포함 기준 {threshold}점보다 낮습니다. 현재 방식이 상대적으로 더 나을 수는 있지만, 아직 '강한 과거 Setup'과 같은 강도까지 올라온 것은 아닙니다."
    if row is None or int(row.get("Validation 20D", 0)) < 5:
        return "자료 제한", "status-muted", f"현재 {ko} 진입 점수는 {threshold}점 이상이지만 과거 20D 검증 사례가 충분하지 않아 정합성을 강하게 판단하기 어렵습니다."
    hit = _safe_num(row, "Hit 20D")
    med = _safe_num(row, "Median 20D")
    if np.isfinite(hit) and np.isfinite(med) and hit >= 65 and med > 0:
        return "높음", "status-green", f"현재 {ko} 진입 점수 {current_score:.1f}점은 검증 기준을 충족하며, 과거 같은 기준 이상의 20D 비중복 검증 사례도 대체로 우호적인 결과를 보였습니다. 현재 신호와 과거 패턴의 정합성이 높은 편입니다."
    if np.isfinite(med) and med > 0:
        return "보통", "status-teal", f"현재 {ko} 진입 점수는 검증 기준을 충족합니다. 과거 결과도 평균적으로는 긍정적이었지만 일관성이 아주 높다고 보기는 어려워 Risk와 현재 시장환경을 함께 확인하는 편이 좋습니다."
    return "낮음", "status-orange", f"현재 {ko} 진입 점수 자체는 검증 기준을 충족하지만, 과거 같은 강도의 신호 이후 결과는 일관적이지 않았습니다. 현재 점수만으로 추격하거나 과신하기보다 진입 비중과 무효화 조건을 보수적으로 보는 편이 좋습니다."


def render_calibration(a: dict, symbol: str):
    setups = a["setups"]
    current_view = entry_decision_view(setups)
    pull, mom = setups.pullback, setups.momentum

    st.header(f"과거 진입 검증 (Entry Calibration) · {symbol}")
    st.caption("종합분석의 현재 눌림목·모멘텀 Entry 점수를 그대로 가져와, 과거 가격 기반 동일 Setup 규칙에서 비슷한 강도의 신호가 실제로 어떻게 움직였는지 확인합니다. 미래 수익률을 예측하거나 보장하는 확률값은 아닙니다.")

    st.subheader("1. 현재 진입 상태")
    c1, c2 = st.columns(2)
    for col, setup, title in [
        (c1, pull, "🎯 눌림목 진입 (Pullback)"),
        (c2, mom, "🚀 모멘텀 진입 (Momentum)"),
    ]:
        color = score_color(setup.score)
        with col:
            st.markdown(
                f"<div class='cal-current'><div class='v6-kicker'>{title}</div>"
                f"<div class='score' style='color:{color}'>{setup.score:.1f} / 100</div>"
                f"<div class='state {entry_status_class(setup)}'>{setup_status_ko(setup)}</div>"
                f"<div class='v6-sub'>{entry_status_note(setup)}</div></div>",
                unsafe_allow_html=True,
            )
    st.markdown(
        f"<div class='cal-compare'><div class='v6-kicker'>CURRENT ENTRY DECISION</div>"
        f"<b>우선 진입 방식</b> · {current_view['approach']}<br>"
        f"<b>현재 진입 상태</b> · <span class='{current_view['class']}'>{current_view['state']}</span><br><br>"
        f"{current_view['interpretation']}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("2. 과거 검증 기준")
    st.markdown("<div class='cal-section-note'>이 기준은 현재 Entry 점수를 바꾸는 값이 아닙니다. 과거 사례 중 어느 정도 이상을 '강한 Setup 검증 사례'로 포함할지 정하는 기준선이며, 눌림목과 모멘텀에 동일하게 적용됩니다.</div>", unsafe_allow_html=True)
    threshold = st.slider(
        "검증 사례 포함 기준점수",
        60, 90, 75,
        help="과거 눌림목·모멘텀 Entry 점수가 이 값 이상이었던 날짜만 검증 후보로 모읍니다. 현재 점수 자체를 보정하거나 변경하지 않습니다.",
    )
    if threshold < 70:
        mode_txt = "넓은 기준 · 사례 수는 늘지만 약한 Setup도 함께 포함될 수 있습니다."
    elif threshold < 80:
        mode_txt = "균형 기준 · 사례 수와 Setup 강도의 균형을 보는 구간입니다."
    else:
        mode_txt = "엄격 기준 · 사례 수는 줄지만 더 강한 Setup만 남깁니다."

    def current_threshold_line(name: str, score: float) -> str:
        ok = score >= threshold
        tag = "기준 충족" if ok else "기준 미달"
        cls = "ok" if ok else "wait"
        symbol_ = "✓" if ok else "—"
        return f"<b>{name}</b> {score:.1f}점 <span class='cal-tag {cls}'>{symbol_} {tag}</span>"

    st.markdown(
        f"<div class='cal-help'><b>검증 기준 {threshold} / 100</b><br>"
        f"{current_threshold_line('눌림목 진입', pull.score)}<br>"
        f"{current_threshold_line('모멘텀 진입', mom.score)}<br><br>"
        f"<span class='status-yellow'>{mode_txt}</span></div>",
        unsafe_allow_html=True,
    )
    with st.expander("검증 기준과 현재 Entry 점수의 관계"):
        st.markdown(f"""
- 현재 종합분석의 **눌림목 진입 {pull.score:.1f}점 / 모멘텀 진입 {mom.score:.1f}점**을 그대로 표시합니다.
- **검증 기준 {threshold}점**은 과거 사례를 골라내기 위한 기준입니다. 현재 Entry 점수를 {threshold}점으로 보정하는 값이 아닙니다.
- 과거 각 거래일에서 눌림목 또는 모멘텀 점수가 {threshold}점 이상이면 해당 전략의 검증 후보로 분류합니다.
- Calibration에서는 과거 시점 재무 데이터 누출을 피하기 위해 **가격·거래량·기술 구조 중심**으로 재계산하며, 과거 Market Regime 데이터가 아직 완전하지 않아 시장 점수는 50점(중립)으로 고정합니다. 따라서 종합분석의 오늘 점수와 과거 재계산 점수는 완전히 같은 조건은 아닙니다.
        """)

    run = st.button("과거 진입 검증 실행", type="primary")
    cache_key = f"calibration_result_v609_{symbol}_{threshold}"
    if run:
        try:
            with st.spinner("과거 각 거래일의 눌림목·모멘텀 Setup을 재구성하는 중입니다..."):
                detail, summary = run_setup_calibration(a["frame"], a["benchmark"], float(threshold))
            st.session_state[cache_key] = (detail, summary)
        except Exception as exc:
            st.error(f"과거 진입 검증 실패: {exc}")

    result = st.session_state.get(cache_key)
    if not result:
        st.info("위의 기준점수를 확인한 뒤 **과거 진입 검증 실행**을 누르면 이 종목의 눌림목·모멘텀 과거 성향과 현재 신호의 정합성을 보여줍니다.")
        return

    detail, summary = result
    if summary.empty:
        st.info("현재 기준에서는 충분한 과거 검증 결과가 없습니다. 기준점수를 조금 낮추거나 더 긴 가격 이력이 확보된 종목에서 다시 확인해 보세요.")
        return

    if not detail.empty:
        st.caption(f"검증 신호 평가 구간 · {detail['date'].iloc[0]} ~ {detail['date'].iloc[-1]} · 공통 기준 {threshold}점")
        st.markdown(
            f"<div class='cal-help'><b>이번 검증에서 사례를 세는 기준</b><br>"
            f"① <b>기준 이상 거래일</b> · Entry 점수가 {threshold}점 이상인 모든 거래일<br>"
            f"② <b>Setup 구간</b> · 같은 강한 신호가 이어지는 기간을 한 구간으로 묶습니다. 기준 아래 상태가 <b>3거래일 이상</b> 이어진 뒤 다시 {threshold}점 이상이 되면 새 구간으로 봅니다.<br>"
            f"③ <b>20D 검증 사례</b> · 20영업일 뒤 성과가 서로 과도하게 겹치지 않도록 Setup 구간 시작일끼리 <b>최소 20거래일</b> 간격을 둡니다.<br>"
            f"④ <b>성과 기준</b> · 구간 시작일 종가 대비 5·10·20·60영업일 후 수익률과, 첫 20영업일 동안의 최대 하락폭을 봅니다.<br><br>"
            f"<span class='v6-sub'>Entry 계산에는 각 과거 시점까지 최소 약 230거래일의 가격 이력을 확보하고, 최근 최대 420거래일 범위에서 검증합니다. 60영업일 이후 성과를 계산할 수 있도록 최신 약 60거래일은 새 검증 신호 후보에서 제외합니다.</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("3. 이 종목의 과거 Entry 성향")
    style_name, style_cls, style_text = _calibration_style(summary)
    st.markdown(
        f"<div class='cal-style'><div class='v6-kicker'>HISTORICAL ENTRY STYLE</div>"
        f"<h3 class='{style_cls}'>{style_name}</h3><div class='v6-sub'>{style_text}</div></div>",
        unsafe_allow_html=True,
    )

    st.subheader("4. 진입 방식별 과거 검증")
    p_row, m_row = _cal_row(summary, "Pullback"), _cal_row(summary, "Momentum")
    cards = st.columns(2)
    for col, row, setup_name, title in [
        (cards[0], p_row, "Pullback", "🎯 눌림목 진입 (Pullback)"),
        (cards[1], m_row, "Momentum", "🚀 모멘텀 진입 (Momentum)"),
    ]:
        with col:
            if row is None:
                st.markdown(f"<div class='cal-strategy'><div class='v6-kicker'>{title}</div><div class='v6-sub'>검증 자료가 없습니다.</div></div>", unsafe_allow_html=True)
                continue
            n = int(row.get("Validation 20D", 0))
            pos = int(row.get("Positive 20D", 0))
            episodes = int(row.get("Episodes", 0))
            hit = _safe_num(row, "Hit 20D")
            med = _safe_num(row, "Median 20D")
            avg = _safe_num(row, "Avg 20D")
            mdd = _safe_num(row, "Avg MDD20")
            tone, explanation = _strategy_validation_text(row, setup_name)
            confidence, confidence_cls, _ = _validation_sample_confidence(n)
            # Positive count and hit rate are generated from the same 20D validation cohort.
            hit_text = f"{pos} / {n} ({hit:.0f}%)" if n and np.isfinite(hit) else "—"
            med_text = f"{med:+.1f}%" if np.isfinite(med) else "—"
            avg_text = f"{avg:+.1f}%" if np.isfinite(avg) else "—"
            mdd_text = f"{mdd:.1f}%" if np.isfinite(mdd) else "—"
            st.markdown(
                f"<div class='cal-strategy'><div class='v6-kicker'>{title}</div>"
                f"<div style='font-weight:900;color:#f8fafc'>{tone}</div>"
                f"<div class='cal-stat-grid'>"
                f"<div class='cal-stat'><div class='k'>20D 검증 사례</div><div class='v'>{n}회</div></div>"
                f"<div class='cal-stat'><div class='k'>20일 후 상승 사례</div><div class='v'>{hit_text}</div></div>"
                f"<div class='cal-stat'><div class='k'>대표 수익률 · 20D Median</div><div class='v'>{med_text}</div></div>"
                f"<div class='cal-stat'><div class='k'>평균 수익률 · 20D Average</div><div class='v'>{avg_text}</div></div>"
                f"<div class='cal-stat'><div class='k'>평균 최대 하락폭 · MDD20</div><div class='v'>{mdd_text}</div></div>"
                f"<div class='cal-stat'><div class='k'>Setup 구간</div><div class='v'>{episodes}회</div></div>"f"<div class='cal-stat'><div class='k'>기준 이상 거래일</div><div class='v'>{int(row.get('Signals', 0))}일</div></div>"f"<div class='cal-stat'><div class='k'>표본 신뢰도</div><div class='v {confidence_cls}'>{confidence}</div></div>"
                f"</div><div class='v6-sub'>{explanation}</div></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
    st.subheader("5. 현재 신호 × 과거 검증")
    preferred = setups.preferred
    if preferred == "Pullback Preferred":
        align_name, align_cls, align_text = _historical_alignment("Pullback", pull.score, threshold, p_row)
    elif preferred == "Momentum Preferred":
        align_name, align_cls, align_text = _historical_alignment("Momentum", mom.score, threshold, m_row)
    elif preferred == "Both Valid":
        p_align = _historical_alignment("Pullback", pull.score, threshold, p_row)
        m_align = _historical_alignment("Momentum", mom.score, threshold, m_row)
        if p_align[0] == "높음" and m_align[0] == "높음":
            align_name, align_cls = "높음", "status-green"
        elif "낮음" in (p_align[0], m_align[0]):
            align_name, align_cls = "혼조", "status-yellow"
        else:
            align_name, align_cls = "보통", "status-teal"
        align_text = f"눌림목: {p_align[2]} 모멘텀: {m_align[2]}"
    else:
        if pull.score >= mom.score:
            align_name, align_cls, align_text = _historical_alignment("Pullback", pull.score, threshold, p_row)
        else:
            align_name, align_cls, align_text = _historical_alignment("Momentum", mom.score, threshold, m_row)
        if max(pull.score, mom.score) < threshold:
            align_name, align_cls = "아직 확인 필요", "status-yellow"

    st.markdown(
        f"<div class='cal-compare'><div class='v6-kicker'>CURRENT × HISTORICAL VALIDATION</div>"
        f"<b>현재 우선 방식</b> · {current_view['approach']}<br>"
        f"<b>과거 정합성</b> · <span class='{align_cls}'>{align_name}</span><br><br>{align_text}<br><br>"
        f"<span class='v6-sub'>과거 정합성이 높다는 것은 비슷한 강도의 과거 Setup이 상대적으로 잘 작동했다는 뜻이지, 향후 상승 확률이나 예상 수익률을 의미하지 않습니다.</span></div>",
        unsafe_allow_html=True,
    )

    with st.expander("기간별 상세 통계 보기"):
        shown = summary.rename(columns={
            "Setup": "진입 방식",
            "Signals": "기준 이상 거래일",
            "Episodes": "Setup 구간",
            "Validation 20D": "20D 검증 사례",
            "Positive 20D": "20일 후 상승 사례",
            "Hit 20D": "20일 후 상승 비율",
            "Median 20D": "대표 수익률 20D",
            "Avg 5D": "평균 5D",
            "Avg 10D": "평균 10D",
            "Avg 20D": "평균 20D",
            "Avg 60D": "평균 60D",
            "Avg MDD20": "평균 최대 하락폭 20D",
        }).copy()
        shown["진입 방식"] = shown["진입 방식"].map({"Pullback": "눌림목 진입 (Pullback)", "Momentum": "모멘텀 진입 (Momentum)"}).fillna(shown["진입 방식"])
        visible_cols = [
            "진입 방식", "기준 이상 거래일", "Setup 구간", "20D 검증 사례", "20일 후 상승 사례",
            "20일 후 상승 비율", "대표 수익률 20D", "평균 5D", "평균 10D", "평균 20D",
            "평균 60D", "평균 최대 하락폭 20D",
        ]
        shown = shown[[c for c in visible_cols if c in shown.columns]]
        fmt = {
            "20일 후 상승 비율": "{:.1f}%",
            "대표 수익률 20D": "{:+.2f}%",
            "평균 5D": "{:+.2f}%",
            "평균 10D": "{:+.2f}%",
            "평균 20D": "{:+.2f}%",
            "평균 60D": "{:+.2f}%",
            "평균 최대 하락폭 20D": "{:+.2f}%",
        }
        st.dataframe(shown.style.format(fmt, na_rep="—"), hide_index=True, use_container_width=True)
        st.markdown("""
**쉽게 읽는 법**
- **Setup 구간**: 기준점수 이상인 날이 이어지는 구간을 하나로 묶은 횟수입니다. 기준 아래 상태가 3거래일 이상 이어진 뒤 다시 기준 이상이 되면 새로운 구간으로 봅니다.
- **20D 검증 사례**: 20영업일 성과 구간이 너무 겹치지 않도록 Setup 구간 시작일끼리 최소 20거래일 간격을 둔 사례입니다. 메인 20D 해석은 이 사례를 기준으로 계산합니다.
- **20일 후 상승 비율**: 20D 검증 사례 중 20영업일 뒤 주가가 신호 시작일보다 높았던 비율입니다. 미래 상승확률을 뜻하지 않습니다.
- **대표 수익률 (Median)**: 20D 검증 사례들의 수익률을 순서대로 세웠을 때 가운데 값입니다. 몇 번의 큰 급등·급락 영향이 적어 **'보통 사례가 어느 정도였는가'**를 볼 때 유용합니다.
- **평균 수익률 (Average)**: 모든 20D 검증 사례의 수익률을 더해 나눈 값입니다. 큰 급등 한두 번이 있으면 대표 수익률보다 높아질 수 있습니다.
- **평균 최대 하락폭 (MDD20)**: 진입 후 20영업일 동안 중간에 얼마나 크게 밀렸는지를 평균낸 값입니다. 0에 가까울수록 진입 후 흔들림이 작았다는 뜻입니다.
- **평균 60D**: 같은 20D 검증 사례를 60영업일까지 추적한 보조 수치입니다. 사례 시작 간격은 20거래일이므로 60D 구간끼리는 일부 겹칠 수 있어 장기 참고값으로만 봅니다.
        """)
        if (summary["Validation 20D"] < 5).any():
            st.warning("20D 검증 사례가 5개 미만인 진입 방식이 있습니다. 해당 결과는 참고 수준으로만 보고 기준을 낮추거나 더 긴 데이터가 확보된 뒤 다시 비교하는 편이 좋습니다.")

    with st.expander("과거 검증 원자료 보기"):
        st.dataframe(detail.tail(250), hide_index=True, use_container_width=True)
        st.caption("원자료의 pullback/momentum은 과거 각 거래일에서 재계산한 Entry 점수이며, fwd_5d~60d는 이후 실제 가격 수익률입니다. Calibration은 과거 시장 국면을 중립으로 고정한 가격 기반 검증입니다.")

    st.caption("과거 결과는 미래 성과를 보장하지 않습니다. Calibration은 현재 Entry Engine을 보조하는 Historical Validation Layer로 사용하고, 현재 시장환경·Risk·옵션·기업 품질과 함께 해석하세요.")


# -------------------- App shell --------------------
st.title("Stock Analyzer by Kijungnam")
st.caption("V6.0.9 · MULTI-LENS SETUP & DECISION SYSTEM · Decision Summary & Consensus")

with st.expander("🔥 V6 종목 스캐너 · 시장 전체 후보 찾기", expanded=False):
    render_scanner_section()

st.markdown("<div class='v6-section'></div>", unsafe_allow_html=True)
st.subheader("종목 검색")
query=st.text_input("티커 또는 회사명",placeholder="예: NVDA, Micron, 삼성전자, 005930")
results=search_symbol(query) if query else []
if results:
    labels=[f"{x['name']} · {x['symbol']} · {x.get('exchange','')}" for x in results]
    choice=st.selectbox("검색 후보",labels)
    selected_symbol=results[labels.index(choice)]["symbol"]
    if st.button("분석 시작",type="primary",use_container_width=True):
        st.session_state["symbol"]=selected_symbol
symbol=st.session_state.get("symbol","")
if symbol:
    st.caption(f"현재 선택 종목 · {info(symbol).get('longName') or info(symbol).get('shortName') or symbol} · {symbol}")

mode=st.radio("개별 분석 메뉴",["📊 종합분석","🎯 퀀트분석","🧩 옵션분석","🌎 시장환경","🧪 과거 진입 검증","💾 History"],horizontal=True,label_visibility="collapsed")
st.divider()

analysis=None
if symbol and mode in ("📊 종합분석","🎯 퀀트분석","🧩 옵션분석","🧪 과거 진입 검증"):
    try:
        with st.spinner(f"{symbol} · V6.0.9 엔진을 계산하는 중입니다..."): analysis=build_full_analysis(symbol)
    except Exception as exc: st.error(f"분석을 계산하지 못했습니다: {exc}")

if mode=="📊 종합분석":
    if not symbol: st.info("먼저 종목을 검색해 주세요.")
    elif analysis: render_analysis(analysis,symbol)

elif mode=="🎯 퀀트분석":
    if not symbol: st.info("먼저 종목을 검색해 주세요.")
    elif analysis: render_quant_analysis(analysis,symbol)

elif mode=="🧩 옵션분석":
    if not symbol: st.info("먼저 종목을 검색해 주세요.")
    else:
        try:
            from options_analyzer import render_options
            base=analysis or build_full_analysis(symbol)
            support=base["zones"].supports[0].center if base["zones"].supports else None
            resistance=base["zones"].resistances[0].center if base["zones"].resistances else None
            render_options(symbol,base["now"],money,support,resistance)
        except Exception as exc: st.warning(f"옵션분석을 표시할 수 없습니다: {exc}")

elif mode=="🌎 시장환경": render_market_dashboard()

elif mode=="🧪 과거 진입 검증":
    if not symbol or not analysis: st.info("먼저 종목을 검색한 뒤 과거 진입 검증을 실행해 주세요.")
    else: render_calibration(analysis,symbol)

elif mode=="💾 History":
    st.header("V6 History Database")
    st.caption(f"현재 DB: {DB_FILE}. 로컬/자체 서버에서는 SQLite로 저장됩니다. Streamlit Community Cloud는 재배포 시 로컬 디스크가 초기화될 수 있어 JSON 백업 기능을 함께 제공합니다.")
    st.download_button("전체 History JSON 내보내기",HISTORY.export_json(),"stock_analyzer_v6_history.json","application/json")
    uploaded=st.file_uploader("History JSON 가져오기",type="json")
    if uploaded and st.button("History 가져오기"):
        try: st.success(f"{HISTORY.import_json(uploaded.getvalue())}개 레코드를 가져왔습니다.")
        except Exception as exc: st.error(f"가져오기 실패: {exc}")
    if symbol:
        rows=HISTORY.rows(symbol,100)
        if rows: st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        else: st.info("현재 선택 종목의 V6 저장 이력이 없습니다.")
