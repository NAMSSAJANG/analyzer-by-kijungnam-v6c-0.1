from __future__ import annotations

import re
from collections.abc import Callable, Mapping

import pandas as pd


_HANGUL = re.compile(r"[가-힣]")
_EMPTY = pd.DataFrame(columns=["Code", "Name", "Market"])


def contains_hangul(value: str) -> bool:
    return bool(_HANGUL.search(str(value)))


def _normalise_listing(frame: pd.DataFrame, market_hint: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _EMPTY.copy()
    code_col = next((name for name in ("Code", "Symbol") if name in frame.columns), None)
    name_col = next((name for name in ("Name", "Company", "CompanyName") if name in frame.columns), None)
    if code_col is None or name_col is None:
        return _EMPTY.copy()
    columns = [code_col, name_col] + (["Market"] if "Market" in frame.columns else [])
    out = frame[columns].copy().rename(columns={code_col: "Code", name_col: "Name"})
    out["Code"] = out["Code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    out["Name"] = out["Name"].astype(str).str.strip()
    if "Market" not in out:
        out["Market"] = market_hint
    else:
        out["Market"] = out["Market"].fillna(market_hint).astype(str)
    return out.dropna(subset=["Code"]).drop_duplicates(["Code", "Market"])


def _fallback_frame(fallback: Mapping[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Code": [symbol.split(".", 1)[0] for symbol in fallback],
            "Name": list(fallback.values()),
            "Market": ["KOSDAQ" if symbol.endswith(".KQ") else "KOSPI" for symbol in fallback],
        }
    )


def load_krx_listing(
    stock_listing: Callable[[str], pd.DataFrame] | None = None,
    fallback: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Load Korean listings in resilient stages, ending with the built-in KOSPI map."""
    if stock_listing is None:
        import FinanceDataReader as fdr

        stock_listing = fdr.StockListing

    stages = (("KRX",), ("KOSPI", "KOSDAQ"), ("KOSPI-DESC", "KOSDAQ-DESC"), ("KRX-DESC",))
    for sources in stages:
        frames = []
        for source in sources:
            try:
                market_hint = "KOSDAQ" if source.startswith("KOSDAQ") else "KOSPI" if source.startswith("KOSPI") else "KRX"
                frame = _normalise_listing(stock_listing(source), market_hint)
                if not frame.empty:
                    frames.append(frame)
            except Exception:
                continue
        if frames:
            return pd.concat(frames, ignore_index=True).drop_duplicates(["Code", "Market"])

    if fallback is None:
        from top10_ranking import FALLBACK_KOSPI

        fallback = FALLBACK_KOSPI
    return _fallback_frame(fallback)


def search_krx_listing(query: str, listing: pd.DataFrame, limit: int = 10) -> list[dict[str, str]]:
    query = query.strip()
    if listing.empty or not query:
        return []
    if query.isdigit():
        mask = listing["Code"].astype(str).str.startswith(query.zfill(6))
    else:
        mask = listing["Name"].astype(str).str.contains(query, case=False, regex=False)
    results = []
    for _, row in listing.loc[mask].head(limit).iterrows():
        market = str(row.get("Market", "KRX"))
        suffix = ".KQ" if "KOSDAQ" in market.upper() else ".KS"
        results.append(
            {"symbol": f"{row['Code']}{suffix}", "name": str(row["Name"]), "exchange": market, "type": "Equity"}
        )
    return results
