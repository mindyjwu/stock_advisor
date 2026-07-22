"""
Community layer — the social side of Stock Advisor.

Everything here is private by default. A user only appears to others once they
opt in (profiles.is_public), and their track record is only shown if they
additionally opt in to sharing returns (profiles.share_returns). We deliberately
never store or expose dollar amounts here — only percentages, picks, and text.

Tables (all dual-backend via db.connection, same as db/store.py):
  profiles          — bio, avatar, and the two opt-in visibility flags
  follows           — follower_id -> followed_id
  posts             — short messages, optionally attached to a ticker (threads)
  post_likes        — one like per (post, user)
  shared_watchlists — a published, cloneable list of tickers
  blocks            — blocker_id hides blocked_id (both directions in feeds)
  reports           — lightweight moderation queue for the app owner
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from db.connection import connect as _conn, PK_TYPE

MAX_POST_LEN = 500
MAX_BIO_LEN = 280
MAX_WATCHLIST_NAME_LEN = 60
# Simple anti-spam: at most this many posts per user in the trailing window.
_POST_RATE_LIMIT = 10
_POST_RATE_WINDOW = timedelta(minutes=5)


def init_community():
    schema = [
        """CREATE TABLE IF NOT EXISTS profiles (
            user_id       INTEGER PRIMARY KEY,
            bio           TEXT,
            avatar        TEXT,
            is_public     INTEGER NOT NULL DEFAULT 0,
            share_returns INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS follows (
            id          {PK_TYPE},
            follower_id INTEGER NOT NULL,
            followed_id INTEGER NOT NULL,
            created_at  TEXT NOT NULL,
            UNIQUE(follower_id, followed_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS posts (
            id         {PK_TYPE},
            user_id    INTEGER NOT NULL,
            ticker     TEXT,
            body       TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS post_likes (
            id         {PK_TYPE},
            post_id    INTEGER NOT NULL,
            user_id    INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(post_id, user_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS shared_watchlists (
            id         {PK_TYPE},
            user_id    INTEGER NOT NULL,
            name       TEXT NOT NULL,
            tickers    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS blocks (
            id         {PK_TYPE},
            blocker_id INTEGER NOT NULL,
            blocked_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(blocker_id, blocked_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS reports (
            id             {PK_TYPE},
            reporter_id    INTEGER NOT NULL,
            target_user_id INTEGER,
            post_id        INTEGER,
            reason         TEXT,
            created_at     TEXT NOT NULL
        )""",
    ]
    with _conn() as con:
        con.executescript(schema)


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Profiles ────────────────────────────────────────────────────────────────
def ensure_profile(user_id: int):
    with _conn() as con:
        con.execute(
            "INSERT INTO profiles (user_id, updated_at) VALUES (?,?) "
            "ON CONFLICT(user_id) DO NOTHING",
            (user_id, _now()),
        )


def get_profile(user_id: int) -> dict:
    ensure_profile(user_id)
    with _conn() as con:
        row = con.execute("""
            SELECT p.user_id, p.bio, p.avatar, p.is_public, p.share_returns,
                   u.display_name, u.username
            FROM profiles p JOIN users u ON u.id = p.user_id
            WHERE p.user_id = ?
        """, (user_id,)).fetchone()
    d = dict(row)
    d["is_public"] = bool(d["is_public"])
    d["share_returns"] = bool(d["share_returns"])
    d["display_name"] = d["display_name"] or d["username"]
    d["avatar"] = d["avatar"] or "🙂"
    return d


def update_profile(user_id: int, bio: str, avatar: str,
                   is_public: bool, share_returns: bool):
    ensure_profile(user_id)
    with _conn() as con:
        con.execute("""
            UPDATE profiles
            SET bio=?, avatar=?, is_public=?, share_returns=?, updated_at=?
            WHERE user_id=?
        """, ((bio or "")[:MAX_BIO_LEN], (avatar or "🙂")[:8],
              1 if is_public else 0, 1 if share_returns else 0, _now(), user_id))


def get_public_sharers(exclude_user_id: Optional[int] = None) -> list[dict]:
    """Users who opted into BOTH being public and sharing returns — the only
    accounts eligible for the leaderboard."""
    with _conn() as con:
        rows = con.execute("""
            SELECT p.user_id, p.avatar, p.bio, u.display_name, u.username
            FROM profiles p JOIN users u ON u.id = p.user_id
            WHERE p.is_public = 1 AND p.share_returns = 1
        """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if exclude_user_id is not None and d["user_id"] == exclude_user_id:
            continue
        d["display_name"] = d["display_name"] or d["username"]
        d["avatar"] = d["avatar"] or "🙂"
        out.append(d)
    return out


def get_public_profiles(viewer_id: int, limit: int = 100) -> list[dict]:
    """All public profiles (for a member directory), minus anyone blocked."""
    blocked = get_block_pair_ids(viewer_id)
    with _conn() as con:
        rows = con.execute("""
            SELECT p.user_id, p.avatar, p.bio, p.share_returns, u.display_name, u.username
            FROM profiles p JOIN users u ON u.id = p.user_id
            WHERE p.is_public = 1
            ORDER BY u.display_name
        """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d["user_id"] in blocked:
            continue
        d["display_name"] = d["display_name"] or d["username"]
        d["avatar"] = d["avatar"] or "🙂"
        d["share_returns"] = bool(d["share_returns"])
        out.append(d)
    return out[:limit]


# ── Follows ─────────────────────────────────────────────────────────────────
def follow(follower_id: int, followed_id: int):
    if follower_id == followed_id:
        return
    with _conn() as con:
        con.execute(
            "INSERT INTO follows (follower_id, followed_id, created_at) VALUES (?,?,?) "
            "ON CONFLICT(follower_id, followed_id) DO NOTHING",
            (follower_id, followed_id, _now()),
        )


def unfollow(follower_id: int, followed_id: int):
    with _conn() as con:
        con.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?",
                    (follower_id, followed_id))


def is_following(follower_id: int, followed_id: int) -> bool:
    with _conn() as con:
        return con.execute(
            "SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?",
            (follower_id, followed_id),
        ).fetchone() is not None


def get_following_ids(user_id: int) -> set:
    with _conn() as con:
        rows = con.execute("SELECT followed_id FROM follows WHERE follower_id=?",
                           (user_id,)).fetchall()
    return {r["followed_id"] for r in rows}


def follow_counts(user_id: int) -> dict:
    with _conn() as con:
        followers = con.execute("SELECT COUNT(*) AS n FROM follows WHERE followed_id=?",
                                (user_id,)).fetchone()["n"]
        following = con.execute("SELECT COUNT(*) AS n FROM follows WHERE follower_id=?",
                                (user_id,)).fetchone()["n"]
    return {"followers": followers, "following": following}


# ── Blocks & reports ────────────────────────────────────────────────────────
def block(blocker_id: int, blocked_id: int):
    if blocker_id == blocked_id:
        return
    with _conn() as con:
        con.execute(
            "INSERT INTO blocks (blocker_id, blocked_id, created_at) VALUES (?,?,?) "
            "ON CONFLICT(blocker_id, blocked_id) DO NOTHING",
            (blocker_id, blocked_id, _now()),
        )


def unblock(blocker_id: int, blocked_id: int):
    with _conn() as con:
        con.execute("DELETE FROM blocks WHERE blocker_id=? AND blocked_id=?",
                    (blocker_id, blocked_id))


def get_blocked_ids(user_id: int) -> set:
    """Users this person has blocked."""
    with _conn() as con:
        rows = con.execute("SELECT blocked_id FROM blocks WHERE blocker_id=?",
                           (user_id,)).fetchall()
    return {r["blocked_id"] for r in rows}


def get_block_pair_ids(user_id: int) -> set:
    """Everyone to hide from this user's view: people they blocked AND people
    who blocked them (so a blocked user also can't see the blocker)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT blocked_id AS other FROM blocks WHERE blocker_id=? "
            "UNION SELECT blocker_id AS other FROM blocks WHERE blocked_id=?",
            (user_id, user_id),
        ).fetchall()
    return {r["other"] for r in rows}


def report(reporter_id: int, target_user_id: Optional[int] = None,
           post_id: Optional[int] = None, reason: str = ""):
    with _conn() as con:
        con.execute(
            "INSERT INTO reports (reporter_id, target_user_id, post_id, reason, created_at) "
            "VALUES (?,?,?,?,?)",
            (reporter_id, target_user_id, post_id, (reason or "")[:MAX_POST_LEN], _now()),
        )


# ── Posts & threads ─────────────────────────────────────────────────────────
def create_post(user_id: int, body: str, ticker: Optional[str] = None) -> dict:
    body = (body or "").strip()
    if not body:
        return {"error": "Post can't be empty."}
    if len(body) > MAX_POST_LEN:
        return {"error": f"Keep it under {MAX_POST_LEN} characters."}
    cutoff = (datetime.utcnow() - _POST_RATE_WINDOW).isoformat()
    with _conn() as con:
        recent = con.execute(
            "SELECT COUNT(*) AS n FROM posts WHERE user_id=? AND created_at > ?",
            (user_id, cutoff),
        ).fetchone()["n"]
        if recent >= _POST_RATE_LIMIT:
            return {"error": "You're posting too fast — take a short break."}
        con.execute(
            "INSERT INTO posts (user_id, ticker, body, created_at) VALUES (?,?,?,?)",
            (user_id, (ticker or None) and ticker.upper(), body, _now()),
        )
    return {"ok": True}


def delete_post(user_id: int, post_id: int):
    """Delete own post (and its likes)."""
    with _conn() as con:
        con.execute("DELETE FROM posts WHERE id=? AND user_id=?", (post_id, user_id))
        con.execute("DELETE FROM post_likes WHERE post_id=?", (post_id,))


def _decorate_posts(rows, viewer_id: int, blocked: set) -> list[dict]:
    out = []
    with _conn() as con:
        liked = {r["post_id"] for r in con.execute(
            "SELECT post_id FROM post_likes WHERE user_id=?", (viewer_id,)).fetchall()}
        for r in rows:
            d = dict(r)
            if d["user_id"] in blocked:
                continue
            d["display_name"] = d["display_name"] or d["username"]
            d["avatar"] = d["avatar"] or "🙂"
            d["likes"] = con.execute(
                "SELECT COUNT(*) AS n FROM post_likes WHERE post_id=?",
                (d["id"],)).fetchone()["n"]
            d["liked"] = d["id"] in liked
            d["is_own"] = d["user_id"] == viewer_id
            out.append(d)
    return out


_POST_SELECT = """
    SELECT po.id, po.user_id, po.ticker, po.body, po.created_at,
           pr.avatar, u.display_name, u.username
    FROM posts po
    JOIN users u ON u.id = po.user_id
    LEFT JOIN profiles pr ON pr.user_id = po.user_id
"""


def get_ticker_posts(ticker: str, viewer_id: int, limit: int = 60) -> list[dict]:
    blocked = get_block_pair_ids(viewer_id)
    with _conn() as con:
        rows = con.execute(
            _POST_SELECT + " WHERE po.ticker=? ORDER BY po.created_at DESC LIMIT ?",
            (ticker.upper(), limit + len(blocked) + 5),
        ).fetchall()
    return _decorate_posts(rows, viewer_id, blocked)[:limit]


def get_feed(user_id: int, limit: int = 50) -> list[dict]:
    """Posts from people the user follows, plus their own, newest first."""
    following = get_following_ids(user_id) | {user_id}
    blocked = get_block_pair_ids(user_id)
    ids = list(following - blocked)
    if not ids:
        return []
    placeholders = ",".join(["?"] * len(ids))
    with _conn() as con:
        rows = con.execute(
            _POST_SELECT + f" WHERE po.user_id IN ({placeholders}) "
            "ORDER BY po.created_at DESC LIMIT ?",
            (*ids, limit),
        ).fetchall()
    return _decorate_posts(rows, user_id, blocked)[:limit]


def get_recent_posts(viewer_id: int, limit: int = 50) -> list[dict]:
    """Global recent posts (the town square), minus blocked users."""
    blocked = get_block_pair_ids(viewer_id)
    with _conn() as con:
        rows = con.execute(
            _POST_SELECT + " ORDER BY po.created_at DESC LIMIT ?",
            (limit + len(blocked) + 5,),
        ).fetchall()
    return _decorate_posts(rows, viewer_id, blocked)[:limit]


def like_post(user_id: int, post_id: int):
    with _conn() as con:
        con.execute(
            "INSERT INTO post_likes (post_id, user_id, created_at) VALUES (?,?,?) "
            "ON CONFLICT(post_id, user_id) DO NOTHING",
            (post_id, user_id, _now()),
        )


def unlike_post(user_id: int, post_id: int):
    with _conn() as con:
        con.execute("DELETE FROM post_likes WHERE post_id=? AND user_id=?",
                    (post_id, user_id))


# ── Shared watchlists ───────────────────────────────────────────────────────
def publish_watchlist(user_id: int, name: str, tickers: list) -> dict:
    name = (name or "").strip()[:MAX_WATCHLIST_NAME_LEN]
    if not name:
        return {"error": "Give your list a name."}
    if not tickers:
        return {"error": "Your watchlist is empty — add tickers first."}
    with _conn() as con:
        con.execute(
            "INSERT INTO shared_watchlists (user_id, name, tickers, created_at) VALUES (?,?,?,?)",
            (user_id, name, json.dumps(tickers), _now()),
        )
    return {"ok": True}


def delete_shared_watchlist(user_id: int, list_id: int):
    with _conn() as con:
        con.execute("DELETE FROM shared_watchlists WHERE id=? AND user_id=?",
                    (list_id, user_id))


def _decorate_lists(rows, viewer_id: int, blocked: set) -> list[dict]:
    out = []
    for r in rows:
        d = dict(r)
        if d["user_id"] in blocked:
            continue
        d["display_name"] = d["display_name"] or d["username"]
        d["avatar"] = d["avatar"] or "🙂"
        try:
            d["tickers"] = json.loads(d["tickers"]) if d["tickers"] else []
        except Exception:
            d["tickers"] = []
        d["is_own"] = d["user_id"] == viewer_id
        out.append(d)
    return out


_LIST_SELECT = """
    SELECT sw.id, sw.user_id, sw.name, sw.tickers, sw.created_at,
           pr.avatar, u.display_name, u.username
    FROM shared_watchlists sw
    JOIN users u ON u.id = sw.user_id
    LEFT JOIN profiles pr ON pr.user_id = sw.user_id
"""


def get_shared_watchlists(viewer_id: int, limit: int = 50) -> list[dict]:
    blocked = get_block_pair_ids(viewer_id)
    with _conn() as con:
        rows = con.execute(
            _LIST_SELECT + " ORDER BY sw.created_at DESC LIMIT ?",
            (limit + len(blocked) + 5,),
        ).fetchall()
    return _decorate_lists(rows, viewer_id, blocked)[:limit]


def get_shared_watchlist(list_id: int) -> Optional[dict]:
    with _conn() as con:
        row = con.execute(_LIST_SELECT + " WHERE sw.id=?", (list_id,)).fetchone()
    if not row:
        return None
    return _decorate_lists([row], -1, set())[0]
