#!/usr/bin/env python3
"""
Copy an existing SQLite database into Postgres.

Existing single-user / SQLite deployments run this once when moving to
Postgres so their real data (accounts, holdings history, suggestions,
decisions, imports…) comes along — it isn't only for fresh installs.

Usage:
    export DATABASE_URL="postgresql://user:pass@host:5432/stock_advisor"
    python3 scripts/migrate_to_postgres.py                 # from db/advisor.db
    python3 scripts/migrate_to_postgres.py --sqlite path   # from another file
    python3 scripts/migrate_to_postgres.py --truncate      # overwrite target

Row ids are preserved (so user_id links stay intact) and each table's id
sequence is advanced past the highest imported id.
"""
import argparse
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from db import connection  # noqa: E402

# Copy order: users first, then everything keyed by user_id.
TABLES = [
    "users", "suggestions", "saved_picks", "alerts", "scans",
    "portfolio_snapshots", "decisions", "imports",
]


def _table_exists(src, name: str) -> bool:
    return src.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def main():
    ap = argparse.ArgumentParser(description="Migrate SQLite data into Postgres.")
    ap.add_argument("--sqlite", default=str(connection.SQLITE_PATH),
                    help="source SQLite file (default: db/advisor.db)")
    ap.add_argument("--truncate", action="store_true",
                    help="clear target tables before copying")
    args = ap.parse_args()

    if not connection.IS_POSTGRES:
        sys.exit("DATABASE_URL is not a Postgres URL — set it to your target first.")

    src_path = pathlib.Path(args.sqlite)
    if not src_path.exists():
        sys.exit(f"SQLite source not found: {src_path}")

    print(f"Source : {src_path}")
    print(f"Target : Postgres ({connection.DATABASE_URL.rsplit('@', 1)[-1]})")

    # Materialize the schema on the target.
    from db.users import init_users
    from db.store import init_db
    init_users()
    init_db()

    src = sqlite3.connect(src_path)
    src.row_factory = sqlite3.Row

    total = 0
    with connection.connect() as tgt:
        if args.truncate:
            for t in reversed(TABLES):
                tgt.execute(f"DELETE FROM {t}")
            print("Target tables cleared (--truncate).")

        for t in TABLES:
            if not _table_exists(src, t):
                continue
            rows = src.execute(f"SELECT * FROM {t}").fetchall()
            if not rows:
                continue

            existing = tgt.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            if existing and not args.truncate:
                print(f"  {t:20s} target already has {existing} rows — skipped "
                      "(use --truncate to overwrite)")
                continue

            cols = list(rows[0].keys())
            # Double-quote every identifier so reserved words like "full" work.
            collist = ", ".join(f'"{c}"' for c in cols)
            placeholders = ", ".join(["?"] * len(cols))
            insert = f"INSERT INTO {t} ({collist}) VALUES ({placeholders})"
            for r in rows:
                tgt.execute(insert, tuple(r[c] for c in cols))

            # Advance the id sequence past the imported rows.
            tgt.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                f"(SELECT COALESCE(MAX(id), 1) FROM {t}))"
            )
            print(f"  {t:20s} copied {len(rows)} rows")
            total += len(rows)

    src.close()
    print(f"\nDone — {total} rows migrated to Postgres.")


if __name__ == "__main__":
    main()
