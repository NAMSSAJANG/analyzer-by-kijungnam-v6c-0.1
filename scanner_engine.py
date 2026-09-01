from __future__ import annotations

from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from core_models import MarketRegimeSnapshot
from risk_engine import build_risk_snapshot
from setup_engine import build_setups
from sr_engine import build_zones
from technical_engine import build_technical_snapshot

FALLBACK_NASDAQ = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "META": "Meta", "AVGO": "Broadcom", "TSLA": "Tesla", "COST": "Costco", "NFLX": "Netflix",
    "AMD": "AMD", "PLTR": "Palantir", "QCOM": "Qualcomm", "MU": "Micron", "INTC": "Intel",
}
FALLBACK_SP500 = {**FALLBACK_NASDAQ, "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard", "LLY": "Eli Lilly", "XOM": "Exxon Mobil", "WMT": "Walmart", "UNH": "UnitedHealth", "CRM": "Salesforce", "ORCL": "Oracle"}
FALLBACK_KOSPI = {
    "005930.KS": "삼성전자", "000660.KS": "SK하이닉스", "005380.KS": "현대차", "000270.KS": "기아",
    "035420.KS": "NAVER", "207940.KS": "삼성바이오로직스", "105560.KS": "KB금융", "068270.KS": "셀트리온",
    "055550.KS": "신한지주", "005490.KS": "POSCO홀딩스", "066570.KS": "LG전자", "035720.KS": "카카오",
}


def _yahoo_symbol(symbol: str) -> str:
    return str(symbol).strip().replace(".", "-")


def index_universe(market: str, limit: int = 500) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        if market == "NASDAQ 100":
            payload = requests.get("https://api.nasdaq.com/api/quote/list-type/nasdaq100", headers={**headers, "Accept": "application/json, text/plain, */*", "Referer": "https://www.nasdaq.com/"}, timeout=15).json()
            rows = payload["data"]["data"]["rows"]
            return pd.DataFrame({"Symbol": [_yahoo_symbol(x["symbol"]) for x in rows], "Name": [x["companyName"] for x in rows]})
        if market == "S&P 500":
            html = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=headers, timeout=15).text
            table = pd.read_html(StringIO(html), attrs={"id": "constituents"})[0]
            return pd.DataFrame({"Symbol": table["Symbol"].map(_yahoo_symbol), "Name": table["Security"]}).head(limit)
        import FinanceDataReader as fdr
        listing = fdr.StockListing("KRX")
        code_col = next(x for x in ("Code", "Symbol") if x in listing.columns)
        target = "KOSDAQ" if market == "KOSDAQ" else "KOSPI"
        frame = listing[listing["Market"].astype(str).str.upper().eq(target)].copy()
        if "Marcap" in frame.columns:
            frame = frame.sort_values("Marcap", ascending=False).head(limit)
        suffix = ".KQ" if target == "KOSDAQ" else ".KS"
        return pd.DataFrame({"Symbol": frame[code_col].astype(str).str.zfill(6) + suffix, "Name": frame["Name"].astype(str)})
    except Exception:
        fallback = FALLBACK_NASDAQ if market == "NASDAQ 100" else FALLBACK_SP500 if market == "S&P 500" else FALLBACK_KOSPI
        return pd.DataFrame([{"Symbol": k, "Name": v} for k, v in fallback.items()])


def _history_for(raw: pd.DataFrame, symbol: str, single: bool) -> pd.DataFrame:
    if single:
        return raw
    try:
        if symbol in raw.columns.get_level_values(0):
            return raw[symbol]
        return raw.xs(symbol, axis=1, level=1)
    except Exception:
        return pd.DataFrame()


def scan_market(market: str, regime: MarketRegimeSnapshot, benchmark: pd.DataFrame | None = None, universe_limit: int = 220) -> tuple[pd.DataFrame, str]:
    universe = index_universe(market, universe_limit).drop_duplicates("Symbol")
    names = dict(zip(universe.Symbol, universe.Name))
    rows = []
    symbols = universe.Symbol.tolist()
    for start in range(0, len(symbols), 70):
        chunk = symbols[start:start+70]
        try:
            raw = yf.download(chunk, period="18mo", interval="1d", auto_adjust=True, progress=False, threads=True, group_by="ticker", timeout=25)
        except Exception:
            continue
        single = len(chunk) == 1 and not isinstance(raw.columns, pd.MultiIndex)
        for symbol in chunk:
            frame = _history_for(raw, symbol, single).dropna(how="all")
            if len(frame) < 220 or "Volume" not in frame:
                continue
            try:
                tech = build_technical_snapshot(frame, benchmark)
                risk = build_risk_snapshot(tech, regime, None)
                zones = build_zones(frame, tech)
                now = float(frame["Close"].dropna().iloc[-1])
                setups = build_setups(now, tech, regime, zones, risk)
            except Exception:
                continue
            proxy = .32*tech.trend + .18*tech.relative_strength + .20*tech.momentum + .12*tech.demand + .18*regime.score
            rows.append({
                "Symbol": symbol, "Name": names.get(symbol, symbol), "Opportunity Proxy": round(proxy, 1),
                "Trend": tech.trend, "RS": tech.relative_strength, "Momentum": tech.momentum,
                "Pullback": setups.pullback.score, "Pullback Status": setups.pullback.status,
                "Pullback Entry Price": setups.pullback.entry_price, "Pullback Stop": setups.pullback.stop_loss,
                "Pullback Target1": setups.pullback.target1,
                "Momentum Entry": setups.momentum.score, "Momentum Status": setups.momentum.status,
                "Momentum Entry Price": setups.momentum.entry_price, "Momentum Stop": setups.momentum.stop_loss,
                "Momentum Target1": setups.momentum.target1,
                "Preferred": setups.preferred, "Risk": risk.level,
                "Date": frame.index[-1],
            })
    if not rows:
        return pd.DataFrame(), "-"
    out = pd.DataFrame(rows)
    as_of = pd.to_datetime(out.Date, errors="coerce").max().strftime("%Y-%m-%d")
    return out, as_of


def top_views(scan: pd.DataFrame, n: int = 10) -> dict[str, pd.DataFrame]:
    if scan.empty:
        return {"Opportunity Leaders": scan, "Momentum Setups": scan, "Pullback Setups": scan}
    opportunity = scan.sort_values(["Opportunity Proxy", "Trend"], ascending=False).head(n)
    momentum = scan[scan["Momentum Status"].isin(["CONFIRMED", "EARLY BREAKOUT", "EXTENDED"])].sort_values(["Momentum Entry", "Opportunity Proxy"], ascending=False).head(n)
    pullback = scan[scan["Pullback Status"].isin(["READY", "DEVELOPING"])].sort_values(["Pullback", "Opportunity Proxy"], ascending=False).head(n)
    return {"Opportunity Leaders": opportunity, "Momentum Setups": momentum, "Pullback Setups": pullback}
