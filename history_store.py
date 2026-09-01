from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class HistoryTrend:
    dates: tuple[str, ...]
    values: tuple[float, ...]
    change: float | None
    label: str


class SQLiteHistoryStore:
    """Local persistent history store. Set ANALYZER_DB_FILE to move the database.

    Streamlit Community Cloud can still reset local disk on redeploy. The adapter is
    intentionally isolated so a remote database can replace it later without changing
    the scoring engines.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _init(self):
        with self._connect() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS score_history (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    opportunity REAL,
                    company REAL,
                    trend REAL,
                    momentum REAL,
                    relative_strength REAL,
                    pullback REAL,
                    momentum_entry REAL,
                    market REAL,
                    risk REAL,
                    preferred_setup TEXT,
                    metadata TEXT,
                    PRIMARY KEY(symbol, date)
                )"""
            )

    def record(self, symbol: str, scores: Mapping, as_of: date | None = None, metadata: Mapping | None = None):
        row_date = (as_of or date.today()).isoformat()
        cols = ["opportunity", "company", "trend", "momentum", "relative_strength", "pullback", "momentum_entry", "market", "risk"]
        values = [scores.get(k) for k in cols]
        preferred = str(scores.get("preferred_setup", ""))
        payload = json.dumps(dict(metadata or {}), ensure_ascii=False)
        with self._connect() as con:
            con.execute(
                """INSERT INTO score_history(symbol,date,opportunity,company,trend,momentum,relative_strength,pullback,momentum_entry,market,risk,preferred_setup,metadata)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(symbol,date) DO UPDATE SET
                    opportunity=excluded.opportunity, company=excluded.company, trend=excluded.trend,
                    momentum=excluded.momentum, relative_strength=excluded.relative_strength,
                    pullback=excluded.pullback, momentum_entry=excluded.momentum_entry,
                    market=excluded.market, risk=excluded.risk, preferred_setup=excluded.preferred_setup,
                    metadata=excluded.metadata""",
                [symbol, row_date, *values, preferred, payload],
            )

    def rows(self, symbol: str, limit: int = 60) -> list[dict]:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            result = con.execute("SELECT * FROM score_history WHERE symbol=? ORDER BY date DESC LIMIT ?", (symbol, limit)).fetchall()
        return [dict(x) for x in reversed(result)]

    def recent(self, symbol: str, key: str, count: int = 5) -> HistoryTrend:
        rows = [x for x in self.rows(symbol, max(count, 20)) if x.get(key) is not None][-count:]
        dates = tuple(str(x["date"]) for x in rows)
        values = tuple(float(x[key]) for x in rows)
        change = round(values[-1] - values[0], 1) if len(values) > 1 else None
        label = "Improving" if change is not None and change >= 3 else "Weakening" if change is not None and change <= -3 else "Stable"
        return HistoryTrend(dates, values, change, label)

    def export_json(self) -> str:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            rows = [dict(x) for x in con.execute("SELECT * FROM score_history ORDER BY symbol,date").fetchall()]
        return json.dumps(rows, ensure_ascii=False, indent=2)

    def import_json(self, payload: bytes | str) -> int:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError("History JSON must be a list")
        count = 0
        for row in rows:
            scores = {k: row.get(k) for k in ("opportunity", "company", "trend", "momentum", "relative_strength", "pullback", "momentum_entry", "market", "risk")}
            scores["preferred_setup"] = row.get("preferred_setup", "")
            metadata = json.loads(row.get("metadata") or "{}") if isinstance(row.get("metadata"), str) else {}
            self.record(row["symbol"], scores, date.fromisoformat(row["date"]), metadata)
            count += 1
        return count
