"""
SQLite memory layer. All tables are scoped per user account.

Tables:
  suggestions         — every scored suggestion with date, scores, action, prices
  saved_picks         — user-saved stocks, tagged by industry list
  alerts              — fired alert log (deduped per user)
  scans               — persisted market scans (last 5 per user)
  portfolio_snapshots — daily portfolio value/G-L point, for the equity curve
  decisions           — what the user actually did with a pick (bought / passed)
  imports             — audit log of CSV/PDF holdings imports (with undo backup)

Databases created before accounts existed are migrated in place: a user_id
column is added and pre-account rows are claimed by the owner at first signup
(see claim_legacy_rows).
"""
import json
from datetime import datetime
from typing import Optional

from db.connection import (
    connect as _conn, IS_POSTGRES, PK_TYPE, REAL_TYPE, INTEGRITY_ERRORS,
)

# Table names touched by the pre-account → owner migration.
_LEGACY_TABLES = ("suggestions", "saved_picks", "alerts", "scans")


def _has_column(con, table: str, column: str) -> bool:
    return any(r["name"] == column for r in con.execute(f"PRAGMA table_info({table})"))


def _migrate_schema(con):
    """Add user_id to pre-account SQLite tables. saved_picks/alerts need a
    rebuild because their UNIQUE constraints must become per-user.

    Only ever runs on SQLite: Postgres is always a fresh deployment whose
    CREATE TABLE statements already include user_id."""
    if IS_POSTGRES:
        return

    for table in ("suggestions", "scans"):
        if not _has_column(con, table, "user_id"):
            con.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER")

    if not _has_column(con, "saved_picks", "user_id"):
        con.executescript([
            """CREATE TABLE saved_picks_new (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id  INTEGER,
                symbol   TEXT NOT NULL,
                industry TEXT,
                note     TEXT,
                saved_at TEXT NOT NULL,
                UNIQUE(user_id, symbol)
            )""",
            """INSERT INTO saved_picks_new (id, user_id, symbol, industry, note, saved_at)
                SELECT id, NULL, symbol, industry, note, saved_at FROM saved_picks""",
            "DROP TABLE saved_picks",
            "ALTER TABLE saved_picks_new RENAME TO saved_picks",
        ])

    if not _has_column(con, "alerts", "user_id"):
        con.executescript([
            """CREATE TABLE alerts_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                symbol     TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message    TEXT NOT NULL,
                fired_at   TEXT NOT NULL,
                dedup_key  TEXT NOT NULL,
                UNIQUE(user_id, dedup_key)
            )""",
            """INSERT INTO alerts_new (id, user_id, symbol, alert_type, message, fired_at, dedup_key)
                SELECT id, NULL, symbol, alert_type, message, fired_at, dedup_key FROM alerts""",
            "DROP TABLE alerts",
            "ALTER TABLE alerts_new RENAME TO alerts",
        ])


def init_db():
    # DDL is written once with dialect placeholders ({pk}/{real}) so the same
    # schema materializes on either backend.
    schema = [
        f"""CREATE TABLE IF NOT EXISTS suggestions (
            id          {PK_TYPE},
            user_id     INTEGER,
            symbol      TEXT    NOT NULL,
            run_at      TEXT    NOT NULL,
            action      TEXT,
            score       {REAL_TYPE},
            fund_score  {REAL_TYPE},
            tech_score  {REAL_TYPE},
            sent_score  {REAL_TYPE},
            regime      TEXT,
            current_price {REAL_TYPE},
            target_price  {REAL_TYPE},
            upside_pct    {REAL_TYPE},
            suggested_qty INTEGER,
            reasons     TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS saved_picks (
            id       {PK_TYPE},
            user_id  INTEGER,
            symbol   TEXT NOT NULL,
            industry TEXT,
            note     TEXT,
            saved_at TEXT NOT NULL,
            UNIQUE(user_id, symbol)
        )""",
        f"""CREATE TABLE IF NOT EXISTS alerts (
            id         {PK_TYPE},
            user_id    INTEGER,
            symbol     TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message    TEXT NOT NULL,
            fired_at   TEXT NOT NULL,
            dedup_key  TEXT NOT NULL,
            UNIQUE(user_id, dedup_key)
        )""",
        f"""CREATE TABLE IF NOT EXISTS scans (
            id      {PK_TYPE},
            user_id INTEGER,
            run_at  TEXT NOT NULL,
            regime  TEXT,
            "full"  TEXT,
            pass1   TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id           {PK_TYPE},
            user_id      INTEGER,
            snap_date    TEXT NOT NULL,
            snap_at      TEXT NOT NULL,
            total_value  {REAL_TYPE},
            equity_value {REAL_TYPE},
            cash         {REAL_TYPE},
            total_cost   {REAL_TYPE},
            total_gl     {REAL_TYPE},
            n_positions  INTEGER,
            UNIQUE(user_id, snap_date)
        )""",
        f"""CREATE TABLE IF NOT EXISTS decisions (
            id         {PK_TYPE},
            user_id    INTEGER,
            symbol     TEXT NOT NULL,
            decision   TEXT NOT NULL,
            action     TEXT,
            price      {REAL_TYPE},
            score      {REAL_TYPE},
            decided_at TEXT NOT NULL,
            UNIQUE(user_id, symbol)
        )""",
        f"""CREATE TABLE IF NOT EXISTS imports (
            id          {PK_TYPE},
            user_id     INTEGER,
            imported_at TEXT NOT NULL,
            source      TEXT,
            filename    TEXT,
            n_positions INTEGER,
            cash        {REAL_TYPE},
            mode        TEXT,
            backup_path TEXT
        )""",
    ]
    with _conn() as con:
        con.executescript(schema)
        _migrate_schema(con)


def claim_legacy_rows(user_id: int):
    """Assign every pre-account row to the owner. Called once at first signup."""
    init_db()
    with _conn() as con:
        for table in ("suggestions", "saved_picks", "alerts", "scans"):
            con.execute(f"UPDATE {table} SET user_id = ? WHERE user_id IS NULL", (user_id,))


def log_suggestion(user_id: int, suggestion: dict, fund_score: float, tech_score: float,
                   sent_score: float, regime_key: str, reasons: list[str]):
    with _conn() as con:
        con.execute("""
        INSERT INTO suggestions
          (user_id, symbol, run_at, action, score, fund_score, tech_score, sent_score,
           regime, current_price, target_price, upside_pct, suggested_qty, reasons)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user_id,
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


def save_pick(user_id: int, symbol: str, industry: str, note: str = ""):
    with _conn() as con:
        con.execute("""
        INSERT INTO saved_picks (user_id, symbol, industry, note, saved_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(user_id, symbol) DO UPDATE SET industry=excluded.industry, note=excluded.note
        """, (user_id, symbol.upper(), industry, note, datetime.utcnow().isoformat()))


def remove_pick(user_id: int, symbol: str):
    with _conn() as con:
        con.execute("DELETE FROM saved_picks WHERE user_id=? AND symbol=?", (user_id, symbol.upper()))


def get_saved_picks(user_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM saved_picks WHERE user_id=? ORDER BY industry, symbol", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def log_alert(user_id: int, symbol: str, alert_type: str, message: str, dedup_key: str) -> bool:
    """Logs an alert if not already fired for this dedup_key. Returns True if newly logged."""
    with _conn() as con:
        try:
            con.execute("""
            INSERT INTO alerts (user_id, symbol, alert_type, message, fired_at, dedup_key)
            VALUES (?,?,?,?,?,?)
            """, (user_id, symbol.upper(), alert_type, message,
                  datetime.utcnow().isoformat(), dedup_key))
            return True
        except INTEGRITY_ERRORS:
            con.rollback()  # clear the aborted tx (matters on Postgres)
            return False  # already fired


def get_recent_alerts(user_id: int, limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM alerts WHERE user_id=? ORDER BY fired_at DESC LIMIT ?", (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_performance_snapshot(user_id: int) -> list[dict]:
    """For each symbol, return its earliest logged suggestion as a baseline for P&L calc."""
    with _conn() as con:
        # Portable "earliest row per symbol": match each row against the min
        # run_at for its symbol (SQLite's bare-column GROUP BY isn't valid on
        # Postgres).
        rows = con.execute("""
            SELECT symbol, action, current_price as entry_price, target_price, run_at
            FROM suggestions s
            WHERE user_id=?
              AND run_at = (SELECT MIN(run_at) FROM suggestions s2
                            WHERE s2.user_id = s.user_id AND s2.symbol = s.symbol)
            ORDER BY symbol
        """, (user_id,)).fetchall()
        return [dict(r) for r in rows]


def save_scan(user_id: int, full_results: list[dict], pass1_results: list[dict], regime: dict):
    """Persist a market scan so it survives app restarts. Keeps only the latest 5 per user."""
    with _conn() as con:
        con.execute(
            'INSERT INTO scans (user_id, run_at, regime, "full", pass1) VALUES (?,?,?,?,?)',
            (user_id, datetime.utcnow().isoformat(), json.dumps(regime),
             json.dumps(full_results), json.dumps(pass1_results)),
        )
        con.execute("""
            DELETE FROM scans WHERE user_id = ? AND id NOT IN
              (SELECT id FROM scans WHERE user_id = ? ORDER BY run_at DESC LIMIT 5)
        """, (user_id, user_id))


def get_last_scan(user_id: int) -> Optional[dict]:
    """Most recent saved scan as {run_at, regime, full, pass1}, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM scans WHERE user_id=? ORDER BY run_at DESC LIMIT 1", (user_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "run_at": row["run_at"],
            "regime": json.loads(row["regime"]) if row["regime"] else None,
            "full":   json.loads(row["full"]) if row["full"] else [],
            "pass1":  json.loads(row["pass1"]) if row["pass1"] else [],
        }


def get_latest_run_suggestions(user_id: int) -> list[dict]:
    """Most recent logged suggestion per symbol — lets pages that need scores
    (e.g. Invest Cash) work after a restart without re-running the analysis."""
    with _conn() as con:
        rows = con.execute("""
            SELECT s.* FROM suggestions s
            JOIN (SELECT symbol, MAX(run_at) AS latest FROM suggestions
                  WHERE user_id = ? GROUP BY symbol) t
              ON s.symbol = t.symbol AND s.run_at = t.latest
            WHERE s.user_id = ?
            ORDER BY s.score DESC
        """, (user_id, user_id)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"]) if d["reasons"] else []
            d["suggested_quantity"] = d.pop("suggested_qty", 0)
            result.append(d)
        return result


def get_suggestion_history(user_id: int, symbol: Optional[str] = None, limit: int = 50) -> list[dict]:
    with _conn() as con:
        if symbol:
            rows = con.execute(
                "SELECT * FROM suggestions WHERE user_id=? AND symbol=? ORDER BY run_at DESC LIMIT ?",
                (user_id, symbol.upper(), limit)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM suggestions WHERE user_id=? ORDER BY run_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d["reasons"]) if d["reasons"] else []
            result.append(d)
        return result


# ── Portfolio snapshots (equity curve) ──────────────────────────────────────
def record_portfolio_snapshot(user_id: int, total_value: float, equity_value: float,
                              cash: float, total_cost: float, total_gl: float,
                              n_positions: int):
    """Store one portfolio value point. Upserts per UTC day so the equity curve
    has a single, latest point per day no matter how often it's called."""
    now = datetime.utcnow()
    with _conn() as con:
        con.execute("""
        INSERT INTO portfolio_snapshots
          (user_id, snap_date, snap_at, total_value, equity_value, cash,
           total_cost, total_gl, n_positions)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id, snap_date) DO UPDATE SET
          snap_at=excluded.snap_at, total_value=excluded.total_value,
          equity_value=excluded.equity_value, cash=excluded.cash,
          total_cost=excluded.total_cost, total_gl=excluded.total_gl,
          n_positions=excluded.n_positions
        """, (user_id, now.strftime("%Y-%m-%d"), now.isoformat(),
              total_value, equity_value, cash, total_cost, total_gl, n_positions))


def get_portfolio_snapshots(user_id: int, limit: int = 365) -> list[dict]:
    """Daily snapshots oldest-first, ready to plot as an equity curve."""
    with _conn() as con:
        rows = con.execute("""
            SELECT * FROM portfolio_snapshots WHERE user_id=?
            ORDER BY snap_date DESC LIMIT ?
        """, (user_id, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]


# ── Decisions (what the user actually did) ──────────────────────────────────
def record_decision(user_id: int, symbol: str, decision: str, action: str = None,
                    price: float = None, score: float = None):
    """Record 'bought' or 'passed' for a symbol. One decision per symbol per
    user — re-recording overwrites the previous one."""
    with _conn() as con:
        con.execute("""
        INSERT INTO decisions (user_id, symbol, decision, action, price, score, decided_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(user_id, symbol) DO UPDATE SET
          decision=excluded.decision, action=excluded.action,
          price=excluded.price, score=excluded.score, decided_at=excluded.decided_at
        """, (user_id, symbol.upper(), decision, action, price, score,
              datetime.utcnow().isoformat()))


def remove_decision(user_id: int, symbol: str):
    with _conn() as con:
        con.execute("DELETE FROM decisions WHERE user_id=? AND symbol=?",
                    (user_id, symbol.upper()))


def get_decisions(user_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM decisions WHERE user_id=? ORDER BY decided_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_decision_map(user_id: int) -> dict:
    """{symbol: 'bought'|'passed'} for quick lookup when rendering cards."""
    return {d["symbol"]: d["decision"] for d in get_decisions(user_id)}


# ── Import audit log ────────────────────────────────────────────────────────
def log_import(user_id: int, source: str, filename: str, n_positions: int,
               cash: float, mode: str, backup_path: str = None):
    with _conn() as con:
        con.execute("""
        INSERT INTO imports
          (user_id, imported_at, source, filename, n_positions, cash, mode, backup_path)
        VALUES (?,?,?,?,?,?,?,?)
        """, (user_id, datetime.utcnow().isoformat(), source, filename,
              n_positions, cash, mode, backup_path))


def get_imports(user_id: int, limit: int = 20) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM imports WHERE user_id=? ORDER BY imported_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_import(user_id: int) -> Optional[dict]:
    rows = get_imports(user_id, limit=1)
    return rows[0] if rows else None
