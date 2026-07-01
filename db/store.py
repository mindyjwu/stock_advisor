"""
SQLite memory layer.

Tables:
  suggestions  — every scored suggestion with date, scores, action, prices
  saved_picks  — user-saved stocks, tagged by industry list
"""
import sqlite3
import json
import pathlib
from datetime import datetime
from typing import Optional

DB_PATH = pathlib.Path(__file__).parent / "advisor.db"


def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            run_at      TEXT    NOT NULL,
            action      TEXT,
            score       REAL,
            fund_score  REAL,
            tech_score  REAL,
            sent_score  REAL,
            regime      TEXT,
            current_price REAL,
            target_price  REAL,
            upside_pct    REAL,
            suggested_qty INTEGER,
            reasons     TEXT
        );

        CREATE TABLE IF NOT EXISTS saved_picks (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol   TEXT NOT NULL,
            industry TEXT,
            note     TEXT,
            saved_at TEXT NOT NULL,
            UNIQUE(symbol)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol     TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message    TEXT NOT NULL,
            fired_at   TEXT NOT NULL,
            dedup_key  TEXT NOT NULL,
            UNIQUE(dedup_key)
        );
        """)


def log_suggestion(suggestion: dict, fund_score: float, tech_score: float, sent_score: float,
                   regime_key: str, reasons: list[str]):
    with _conn() as con:
        con.execute("""
        INSERT INTO suggestions
          (symbol, run_at, action, score, fund_score, tech_score, sent_score,
           regime, current_price, target_price, upside_pct, suggested_qty, reasons)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            suggestion["symbol"],
            datetime.utcnow().isoformat(),
            suggestion["action"],
            suggestion["score"],
            fund_score, tech_score, sent_score,
            regime_key,
            suggestion["current_price"],
            suggestion["target_price"],
            suggestion["upside_pct"],
            suggestion["suggested_quantity"],
            json.dumps(reasons),
        ))


def save_pick(symbol: str, industry: str, note: str = ""):
    with _conn() as con:
        con.execute("""
        INSERT INTO saved_picks (symbol, industry, note, saved_at)
        VALUES (?,?,?,?)
        ON CONFLICT(symbol) DO UPDATE SET industry=excluded.industry, note=excluded.note
        """, (symbol.upper(), industry, note, datetime.utcnow().isoformat()))


def remove_pick(symbol: str):
    with _conn() as con:
        con.execute("DELETE FROM saved_picks WHERE symbol=?", (symbol.upper(),))


def get_saved_picks() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM saved_picks ORDER BY industry, symbol").fetchall()
        return [dict(r) for r in rows]


def log_alert(symbol: str, alert_type: str, message: str, dedup_key: str) -> bool:
    """Logs an alert if not already fired for this dedup_key. Returns True if newly logged."""
    with _conn() as con:
        try:
            con.execute("""
            INSERT INTO alerts (symbol, alert_type, message, fired_at, dedup_key)
            VALUES (?,?,?,?,?)
            """, (symbol.upper(), alert_type, message, datetime.utcnow().isoformat(), dedup_key))
            return True
        except sqlite3.IntegrityError:
            return False  # already fired


def get_recent_alerts(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM alerts ORDER BY fired_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_performance_snapshot() -> list[dict]:
    """For each symbol, return its earliest logged suggestion as a baseline for P&L calc."""
    with _conn() as con:
        rows = con.execute("""
            SELECT symbol, action, current_price as entry_price, target_price, run_at
            FROM suggestions
            GROUP BY symbol
            HAVING run_at = MIN(run_at)
            ORDER BY symbol
        """).fetchall()
        return [dict(r) for r in rows]


def get_latest_run_suggestions() -> list[dict]:
    """Most recent logged suggestion per symbol — lets pages that need scores
    (e.g. Invest Cash) work after a restart without re-running the analysis."""
    with _conn() as con:
        rows = con.execute("""
            SELECT s.* FROM suggestions s
            JOIN (SELECT symbol, MAX(run_at) AS latest FROM suggestions GROUP BY symbol) t
              ON s.symbol = t.symbol AND s.run_at = t.latest
            ORDER BY s.score DESC
        """).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"]) if d["reasons"] else []
            d["suggested_quantity"] = d.pop("suggested_qty", 0)
            result.append(d)
        return result


def get_suggestion_history(symbol: Optional[str] = None, limit: int = 50) -> list[dict]:
    with _conn() as con:
        if symbol:
            rows = con.execute(
                "SELECT * FROM suggestions WHERE symbol=? ORDER BY run_at DESC LIMIT ?",
                (symbol.upper(), limit)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM suggestions ORDER BY run_at DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"]) if d["reasons"] else []
            result.append(d)
        return result
