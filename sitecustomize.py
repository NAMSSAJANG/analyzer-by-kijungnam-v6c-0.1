"""
Stock Analyzer V5-a0.1 — Korean Search Hotfix

Place this file in the repository root next to app.py.

Python imports ``sitecustomize`` automatically during interpreter startup.
This hotfix patches only FinanceDataReader.StockListing("KRX") so the existing
app.py can keep its original search logic while recovering from upstream KRX
listing failures.

No scoring, consensus, options, entry, market, or UI logic is changed.
"""

from __future__ import annotations


def _install_krx_hotfix() -> None:
    try:
        import pandas as pd
        import FinanceDataReader as fdr
    except Exception:
        return

    original = fdr.StockListing
    if getattr(original, "_kijungnam_search_hotfix", False):
        return

    def _normalize(frame, market_hint="KRX"):
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return pd.DataFrame(columns=["Code", "Name", "Market"])

        code_col = next((c for c in ("Code", "Symbol") if c in frame.columns), None)
        if code_col is None or "Name" not in frame.columns:
            return pd.DataFrame(columns=["Code", "Name", "Market"])

        keep = [code_col, "Name"] + (["Market"] if "Market" in frame.columns else [])
        out = frame[keep].copy().rename(columns={code_col: "Code"})

        out["Code"] = (
            out["Code"]
            .astype(str)
            .str.extract(r"(\d+)", expand=False)
            .fillna("")
            .str.zfill(6)
        )
        out["Name"] = out["Name"].astype(str)

        if "Market" not in out:
            out["Market"] = market_hint
        else:
            out["Market"] = out["Market"].fillna(market_hint).astype(str)

        out = out[out["Code"].str.fullmatch(r"\d{6}", na=False)]
        return out.drop_duplicates(["Code", "Market"])

    def _builtin_fallback():
        # Reuse the KOSPI fallback already included in this project.
        try:
            from top10_ranking import FALLBACK_KOSPI

            return pd.DataFrame(
                [
                    {
                        "Code": symbol.split(".")[0],
                        "Name": name,
                        "Market": "KOSPI",
                    }
                    for symbol, name in FALLBACK_KOSPI.items()
                ]
            )
        except Exception:
            # Minimal emergency list if top10_ranking cannot be imported.
            return pd.DataFrame(
                [
                    ("005930", "삼성전자", "KOSPI"),
                    ("000660", "SK하이닉스", "KOSPI"),
                    ("373220", "LG에너지솔루션", "KOSPI"),
                    ("207940", "삼성바이오로직스", "KOSPI"),
                    ("005380", "현대차", "KOSPI"),
                    ("000270", "기아", "KOSPI"),
                    ("068270", "셀트리온", "KOSPI"),
                    ("105560", "KB금융", "KOSPI"),
                    ("035420", "NAVER", "KOSPI"),
                    ("055550", "신한지주", "KOSPI"),
                    ("005490", "POSCO홀딩스", "KOSPI"),
                    ("012330", "현대모비스", "KOSPI"),
                    ("028260", "삼성물산", "KOSPI"),
                    ("066570", "LG전자", "KOSPI"),
                    ("035720", "카카오", "KOSPI"),
                ],
                columns=["Code", "Name", "Market"],
            )

    def resilient_stock_listing(market, *args, **kwargs):
        # All non-KRX calls behave exactly as FinanceDataReader originally intended.
        if str(market).upper() != "KRX":
            return original(market, *args, **kwargs)

        # 1. Original aggregate endpoint.
        try:
            frame = _normalize(original("KRX", *args, **kwargs))
            if not frame.empty:
                return frame
        except Exception:
            pass

        # 2. Reconstruct from separate KOSPI / KOSDAQ listings.
        frames = []
        for exchange in ("KOSPI", "KOSDAQ"):
            try:
                frame = _normalize(
                    original(exchange, *args, **kwargs),
                    exchange,
                )
                if not frame.empty:
                    frames.append(frame)
            except Exception:
                pass

        if frames:
            return (
                pd.concat(frames, ignore_index=True, sort=False)
                .drop_duplicates(["Code", "Market"])
            )

        # 3. Alternate DESC endpoints.
        frames = []
        for exchange in ("KOSPI", "KOSDAQ"):
            try:
                frame = _normalize(
                    original(f"{exchange}-DESC", *args, **kwargs),
                    exchange,
                )
                if not frame.empty:
                    frames.append(frame)
            except Exception:
                pass

        if frames:
            return (
                pd.concat(frames, ignore_index=True, sort=False)
                .drop_duplicates(["Code", "Market"])
            )

        # 4. Aggregate DESC endpoint.
        try:
            frame = _normalize(original("KRX-DESC", *args, **kwargs))
            if not frame.empty:
                return frame
        except Exception:
            pass

        # 5. Existing project fallback — ensures major KOSPI names never become
        #    raw Korean strings such as ticker="삼성전자".
        return _builtin_fallback()

    resilient_stock_listing._kijungnam_search_hotfix = True
    fdr.StockListing = resilient_stock_listing


_install_krx_hotfix()

