"""Offline smoke tests for V6 pure scoring engines.

Run: python smoke_test.py
No network calls are made.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from company_engine import build_company_snapshot
from core_models import MarketRegimeSnapshot
from history_store import SQLiteHistoryStore
from opportunity_engine import build_opportunity
from quant_engine import build_quant_snapshot
from calibration_engine import run_setup_calibration
from risk_engine import build_risk_snapshot
from setup_engine import build_setups
from sr_engine import build_zones
from technical_engine import build_technical_snapshot


def make_momentum(seed=42):
    rng = np.random.default_rng(seed); n = 360; idx = pd.bdate_range("2025-01-01", periods=n)
    price = 100*np.exp(np.cumsum(.0012+rng.normal(0,.009,n))); price[-25:] *= np.linspace(1,1.16,25)
    close = pd.Series(price,index=idx); open_ = close.shift(1).fillna(close.iloc[0])*(1+rng.normal(0,.003,n))
    high = np.maximum(open_,close)*(1+rng.uniform(.002,.012,n)); low=np.minimum(open_,close)*(1-rng.uniform(.002,.012,n))
    vol = pd.Series(rng.integers(1_000_000,2_000_000,n),index=idx).astype(float); vol.iloc[-3:]*=1.8
    frame = pd.DataFrame({"Open":open_,"High":high,"Low":low,"Close":close,"Volume":vol})
    bench = frame.copy(); bench["Close"] = 100*np.exp(np.cumsum(.0005+rng.normal(0,.006,n)))
    return frame, bench


def make_pullback(seed=9):
    rng=np.random.default_rng(seed); n=360; idx=pd.bdate_range("2025-01-01",periods=n)
    close=pd.Series(100*np.exp(np.cumsum(.0015+rng.normal(0,.0045,n))),index=idx); peak=close.iloc[-6]
    close.iloc[-5:]=[peak*.993,peak*.982,peak*.972,peak*.965,peak*.974]
    open_=close.shift(1).fillna(close.iloc[0]); high=np.maximum(open_,close)*1.004; low=np.minimum(open_,close)*.996
    vol=pd.Series(rng.integers(1_000_000,1_600_000,n),index=idx).astype(float); vol.iloc[-5:-1]=650_000; vol.iloc[-1]=1_500_000
    frame=pd.DataFrame({"Open":open_,"High":high,"Low":low,"Close":close,"Volume":vol})
    bench=frame.copy(); bench["Close"]=100*np.exp(np.cumsum(.0006+rng.normal(0,.003,n)))
    return frame, bench


def main():
    market=MarketRegimeSnapshot("US",72,"Risk-On",{}, {},1.0,"")

    frame, bench = make_momentum(); tech=build_technical_snapshot(frame,bench); risk=build_risk_snapshot(tech,market,30); zones=build_zones(frame,tech); setup=build_setups(float(frame.Close.iloc[-1]),tech,market,zones,risk)
    assert setup.momentum.score > setup.pullback.score
    assert setup.preferred == "Momentum Preferred"
    assert setup.pullback.status == "NOT IN ZONE"

    # Price plan fields (V6.0.15): entry/stop/target must always be populated
    # and internally consistent (target above entry, entry above stop, R:R positive).
    for s in (setup.pullback, setup.momentum):
        assert s.entry_price is not None and s.stop_loss is not None
        assert s.target1 is not None and s.target2 is not None
        assert s.target2 >= s.target1 > s.entry_price
        assert s.entry_price > s.stop_loss
        if s.risk_reward1 is not None:
            assert s.risk_reward1 > 0
        if s.risk_reward2 is not None:
            assert s.risk_reward2 >= (s.risk_reward1 or 0)
        assert s.risk_pct is not None and s.risk_pct > 0

    frame2, bench2 = make_pullback(); tech2=build_technical_snapshot(frame2,bench2); risk2=build_risk_snapshot(tech2,market,40); zones2=build_zones(frame2,tech2); setup2=build_setups(float(frame2.Close.iloc[-1]),tech2,market,zones2,risk2)
    assert setup2.pullback.score > setup2.momentum.score
    assert setup2.pullback.status in ("DEVELOPING","READY")
    assert setup2.preferred == "Pullback Preferred"
    assert setup2.pullback.entry_price is not None and setup2.pullback.target1 > setup2.pullback.entry_price

    company=build_company_snapshot({"revenueGrowth":.22,"earningsGrowth":.28,"operatingMargins":.24,"profitMargins":.18,"returnOnEquity":.26,"debtToEquity":55,"currentRatio":1.6,"trailingPE":28,"forwardPE":24,"priceToBook":5,"totalRevenue":1e11,"freeCashflow":1.5e10})
    opportunity=build_opportunity(company,tech,market)
    assert opportunity.score > 60
    quant=build_quant_snapshot(frame,company,tech,market,zones.supports,zones.resistances)
    assert quant["score"] > 50
    assert set(quant["can_slim"]) == {"C","A","N","S","L","I","M"}

    missing=build_company_snapshot({"revenueGrowth":.18})
    assert missing.coverage < company.coverage
    assert missing.score is not None  # missing fields are excluded, not hard-coded to zero

    detail, summary = run_setup_calibration(frame, bench, threshold=60)
    assert not detail.empty
    required = {
        "Signals","Episodes","Validation 5D","Validation 10D","Validation 20D","Validation 60D",
        "Validation Episodes 20D","Max Episode Share 20D","Positive 20D","Median 20D"
    }
    assert required.issubset(summary.columns)
    for _, row in summary.iterrows():
        n = int(row["Validation 20D"])
        pos = int(row["Positive 20D"])
        hit = row["Hit 20D"]
        assert 0 <= pos <= n
        if n > 0:
            assert abs(float(hit) - (pos / n * 100)) < 1e-9
        assert int(row["Validation Episodes 20D"]) <= int(row["Episodes"])

    # Low thresholds must remain usable even when one long setup episode persists:
    # validation dates are drawn from qualifying days at horizon-specific gaps,
    # not only from episode starts.
    low_detail, low_summary = run_setup_calibration(frame, bench, threshold=30)
    assert not low_detail.empty
    for prefix in ("pullback", "momentum"):
        assert f"{prefix}_sample_20d" in low_detail.columns
        positions = list(np.flatnonzero(low_detail[f"{prefix}_sample_20d"].to_numpy(dtype=bool)))
        if len(positions) > 1:
            assert min(np.diff(positions)) >= 20

    with tempfile.TemporaryDirectory() as tmp:
        store=SQLiteHistoryStore(Path(tmp)/"history.sqlite")
        store.record("TEST", {"opportunity":80,"trend":82,"momentum":78,"pullback":55,"momentum_entry":84,"market":72,"risk":40,"preferred_setup":"Momentum Preferred"})
        assert len(store.rows("TEST")) == 1

    print("V6 offline smoke tests passed")


if __name__ == "__main__":
    main()
