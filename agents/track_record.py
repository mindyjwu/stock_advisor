"""
Verified track record — the leaderboard's core metric.

A member's score is the average return across their own *logged* buy decisions,
priced live. Because the leaderboard scores every public member on every view,
this is cached per user for a few minutes: without it, one page load fires a
price lookup for every decision of every member (an N+1 fan-out).

The result is (avg_return_pct, n_picks) or (None, 0) when there's nothing to
score. fetch_ticker_info already has its own disk cache; this adds an in-process
layer so the whole computation isn't repeated per request.
"""
import time

import data.loader as _loader
from db.store import get_decisions

_CACHE: dict = {}
_TTL_SECONDS = 300  # 5 minutes


def verified_return(user_id: int, ttl: int = _TTL_SECONDS):
    """Average % return across a user's 'bought' decisions. Cached per user."""
    now = time.monotonic()
    hit = _CACHE.get(user_id)
    if hit is not None and (now - hit[0]) < ttl:
        return hit[1]

    returns = []
    for d in get_decisions(user_id):
        if d.get("decision") != "bought":
            continue
        entry = d.get("price") or 0
        if entry <= 0:
            continue
        info = _loader.fetch_ticker_info(d["symbol"])
        current = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        if current and current > 0:
            returns.append((current - entry) / entry * 100)

    result = (round(sum(returns) / len(returns), 2), len(returns)) if returns else (None, 0)
    _CACHE[user_id] = (now, result)
    return result


def clear_cache():
    """Drop all cached track records (useful in tests)."""
    _CACHE.clear()
