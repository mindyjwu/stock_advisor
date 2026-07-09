"""
Database backend abstraction.

Defaults to a local SQLite file — zero configuration, the original behavior.
Set DATABASE_URL to a Postgres URL to use Postgres instead; nothing else in the
app changes:

    export DATABASE_URL="postgresql://user:pass@host:5432/stock_advisor"

Everything goes through connect(), which returns a small wrapper exposing a
uniform .execute(sql, params) / .executescript([...]) / .insert_returning_id()
interface and behaving as a commit-on-success context manager. SQL is written
with '?' placeholders (SQLite style); the wrapper rewrites them to '%s' for
Postgres, so call sites don't care which backend is active.
"""
import os
import pathlib

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

# Where the SQLite database lives when DATABASE_URL is not set.
SQLITE_PATH = pathlib.Path(__file__).parent / "advisor.db"

# ── Dialect-specific DDL fragments ──────────────────────────────────────────
PK_TYPE   = "BIGSERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
REAL_TYPE = "DOUBLE PRECISION"      if IS_POSTGRES else "REAL"


def _integrity_errors():
    if IS_POSTGRES:
        import psycopg
        return (psycopg.errors.IntegrityError,)
    import sqlite3
    return (sqlite3.IntegrityError,)

# Catch these to detect UNIQUE/constraint violations, whichever backend is live.
INTEGRITY_ERRORS = _integrity_errors()


def _q(sql: str) -> str:
    """Translate '?' placeholders to the active backend's style.
    (These modules never use a literal '?' in SQL, so a plain replace is safe.)"""
    return sql.replace("?", "%s") if IS_POSTGRES else sql


class _Conn:
    """Uniform connection wrapper. Commits on a clean exit, rolls back on error,
    and always closes — every call site opens a fresh short-lived connection,
    matching the original sqlite3 usage."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return self._raw.execute(_q(sql), params)

    def executescript(self, statements):
        """Run a list of individual statements — a portable replacement for
        sqlite3's executescript(), which Postgres does not provide."""
        for stmt in statements:
            if stmt and stmt.strip():
                self._raw.execute(_q(stmt))

    def insert_returning_id(self, sql, params=()):
        """INSERT a row and return its new id, portably (RETURNING on Postgres,
        cursor.lastrowid on SQLite)."""
        if IS_POSTGRES:
            cur = self._raw.execute(_q(sql) + " RETURNING id", params)
            return cur.fetchone()["id"]
        cur = self._raw.execute(_q(sql), params)
        return cur.lastrowid

    def rollback(self):
        self._raw.rollback()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                self._raw.rollback()
        finally:
            self._raw.close()
        return False


def connect():
    """Open a fresh connection to the active backend, with dict-style rows."""
    if IS_POSTGRES:
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    else:
        import sqlite3
        raw = sqlite3.connect(SQLITE_PATH)
        raw.row_factory = sqlite3.Row
    return _Conn(raw)


def backend_name() -> str:
    return "postgres" if IS_POSTGRES else "sqlite"
