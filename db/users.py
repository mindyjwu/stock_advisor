"""
User accounts and password authentication.

Passwords are never stored in plain text — only PBKDF2-HMAC-SHA256 hashes with
a per-user random salt and 200k iterations (stdlib only, no extra deps).

The FIRST account ever created becomes the app owner and automatically
inherits all pre-existing single-user data: the legacy watchlist/holdings
JSON files and every DB row written before accounts existed.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional

from db.connection import connect as _conn, IS_POSTGRES, INTEGRITY_ERRORS

PBKDF2_ITERATIONS = 200_000

USERNAME_RULES = "3-20 characters: letters, numbers, underscores"

# Brute-force protection: lock an account after this many consecutive failed
# logins, for this long. Applies to both the Streamlit and API sign-ins.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def init_users():
    with _conn() as con:
        if IS_POSTGRES:
            # Case-insensitive uniqueness via a functional index (Postgres has
            # no COLLATE NOCASE).
            con.executescript([
                """CREATE TABLE IF NOT EXISTS users (
                    id           BIGSERIAL PRIMARY KEY,
                    username     TEXT NOT NULL,
                    display_name TEXT,
                    pw_hash      TEXT NOT NULL,
                    is_owner     INTEGER NOT NULL DEFAULT 0,
                    created_at   TEXT NOT NULL
                )""",
                "CREATE UNIQUE INDEX IF NOT EXISTS users_username_lower ON users (lower(username))",
            ])
        else:
            con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT,
                pw_hash      TEXT NOT NULL,
                is_owner     INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL
            )""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            username     TEXT PRIMARY KEY,
            failed_count INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT
        )""")


def lockout_remaining_seconds(username: str) -> int:
    """Seconds until a locked account can try again (0 if not locked)."""
    key = (username or "").strip().lower()
    if not key:
        return 0
    with _conn() as con:
        row = con.execute(
            "SELECT locked_until FROM login_attempts WHERE username=?", (key,)
        ).fetchone()
    if not row or not row["locked_until"]:
        return 0
    try:
        remaining = (datetime.fromisoformat(row["locked_until"]) - datetime.utcnow()).total_seconds()
    except (ValueError, TypeError):
        return 0
    return int(remaining) if remaining > 0 else 0


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt, expected = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), expected)
    except Exception:
        return False


def _row_to_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "is_owner": bool(row["is_owner"]),
    }


def validate_username(username: str) -> Optional[str]:
    """Returns an error message, or None if valid."""
    u = (username or "").strip()
    if not (3 <= len(u) <= 20) or not u.replace("_", "").isalnum():
        return f"Username must be {USERNAME_RULES}."
    return None


def create_user(username: str, password: str, display_name: str = "") -> dict:
    """Create an account. Returns {'user': ...} on success or {'error': msg}."""
    init_users()
    err = validate_username(username)
    if err:
        return {"error": err}
    if len(password or "") < 8:
        return {"error": "Password must be at least 8 characters."}

    with _conn() as con:
        first_user = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 0
        try:
            user_id = con.insert_returning_id(
                "INSERT INTO users (username, display_name, pw_hash, is_owner, created_at) VALUES (?,?,?,?,?)",
                (username.strip(), (display_name or "").strip(), hash_password(password),
                 1 if first_user else 0, datetime.utcnow().isoformat()),
            )
        except INTEGRITY_ERRORS:
            con.rollback()  # clear the aborted tx (matters on Postgres)
            return {"error": "That username is already taken."}

    if first_user:
        # Owner inherits everything from the pre-account era
        from data.loader import migrate_legacy_to_user
        from db.store import claim_legacy_rows
        migrate_legacy_to_user(user_id)
        claim_legacy_rows(user_id)

    return {"user": get_user(user_id)}


def authenticate(username: str, password: str) -> Optional[dict]:
    """Return the user on success, or None on failure OR while locked out.
    Call lockout_remaining_seconds() to tell the two apart for the UI."""
    init_users()
    uname = (username or "").strip()
    key = uname.lower()
    now = datetime.utcnow()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?)", (uname,)
        ).fetchone()
        att = con.execute(
            "SELECT failed_count, locked_until FROM login_attempts WHERE username=?", (key,)
        ).fetchone()

        # Currently locked? Reject without even checking the password.
        if att and att["locked_until"]:
            try:
                if now < datetime.fromisoformat(att["locked_until"]):
                    return None
            except (ValueError, TypeError):
                pass

        if row and verify_password(password or "", row["pw_hash"]):
            if att:
                con.execute("DELETE FROM login_attempts WHERE username=?", (key,))
            return _row_to_user(row)

        # Failed attempt: increment, and lock once the threshold is hit.
        failed = (att["failed_count"] if att else 0) + 1
        locked_until = None
        if failed >= MAX_FAILED_LOGINS:
            locked_until = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            failed = 0  # start a fresh count after the lock expires
        con.execute(
            "INSERT INTO login_attempts (username, failed_count, locked_until) VALUES (?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET "
            "failed_count=excluded.failed_count, locked_until=excluded.locked_until",
            (key, failed, locked_until),
        )
    return None


def get_user(user_id: int) -> Optional[dict]:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_owner() -> Optional[dict]:
    init_users()
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE is_owner = 1 LIMIT 1").fetchone()
    return _row_to_user(row) if row else None
