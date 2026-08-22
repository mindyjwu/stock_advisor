"""
Advisor scorecard — how good were the calls, actually?

The leaderboard's verified_return answers "what's my average return." This goes
further and grades decision *quality* on the `decisions` the user logged:

  • bought picks   → return since the logged entry price (paper performance)
  • passed picks   → where the stock went after you passed (opportunity cost)
  • score calibration → did higher AI scores actually earn higher returns?
  • decision accuracy → bought-and-rose + passed-and-fell, over everything priced

The heavy lifting is a PURE function, build_scorecard(decisions, price_lookup),
so it's trivially testable offline with a fake price map. scorecard(user_id)
just wires in the DB and live prices, with a short per-user cache because the
API scores this on every page load.
"""
import time

import data.loader as _loader
from db.store import get_decisions

_CACHE: dict = {}
_TTL_SECONDS = 300  # 5 minutes

# AI-score buckets used to check whether the score is predictive of returns.
_SCORE_BUCKETS = [
    ("75+", 75, float("inf")),
    ("60–75", 60, 75),
    ("<60", float("-inf"), 60),
]


def _current_price(symbol: str):
    info = _loader.fetch_ticker_info(symbol)
    return info.get("currentPrice") or info.get("regularMarketPrice") or None


def _bucket(score):
    if score is None:
        return None
    for label, lo, hi in _SCORE_BUCKETS:
        if lo <= score < hi:
            return label
    return None


def build_scorecard(decisions: list, price_lookup) -> dict:
    """Pure grading core. `decisions` is a list of dicts with symbol / decision /
    price / score; `price_lookup(symbol)` returns a current price or None.
    Returns a nested summary (see module docstring)."""
    picks = []
    for d in decisions:
        entry = d.get("price") or 0
        current = price_lookup(d["symbol"])
        move = None
        if entry and entry > 0 and current and current > 0:
            move = round((current - entry) / entry * 100, 2)
        picks.append({
            "symbol": d["symbol"],
            "decision": d.get("decision"),
            "action": d.get("action"),
            "score": d.get("score"),
            "entry": entry or None,
            "current": current,
            "return_pct": move,
        })

    bought = [p for p in picks if p["decision"] == "bought" and p["return_pct"] is not None]
    passed = [p for p in picks if p["decision"] == "passed" and p["return_pct"] is not None]

    # ── bought: paper performance ───────────────────────────────────────────
    b_returns = [p["return_pct"] for p in bought]
    bought_summary = {
        "n_priced": len(bought),
        "avg_return": round(sum(b_returns) / len(b_returns), 2) if b_returns else None,
        "hit_rate": round(sum(r > 0 for r in b_returns) / len(b_returns) * 100, 1) if b_returns else None,
        "best": max(bought, key=lambda p: p["return_pct"], default=None),
        "worst": min(bought, key=lambda p: p["return_pct"], default=None),
    }

    # ── passed: opportunity cost ────────────────────────────────────────────
    p_moves = [p["return_pct"] for p in passed]
    passed_summary = {
        "n_priced": len(passed),
        "avg_move": round(sum(p_moves) / len(p_moves), 2) if p_moves else None,
        "missed_winners": sum(m > 0 for m in p_moves),   # passed, then it rose
        "avoided_losers": sum(m <= 0 for m in p_moves),  # passed, then it fell/flat
    }

    # ── decision accuracy: right on both sides ──────────────────────────────
    correct = sum(p["return_pct"] > 0 for p in bought) + sum(p["return_pct"] <= 0 for p in passed)
    total_priced = len(bought) + len(passed)
    decision_accuracy = round(correct / total_priced * 100, 1) if total_priced else None

    # ── score calibration: is a higher AI score worth more return? ──────────
    calibration = []
    for label, _lo, _hi in _SCORE_BUCKETS:
        bucket_returns = [p["return_pct"] for p in bought if _bucket(p["score"]) == label]
        if bucket_returns:
            calibration.append({
                "bucket": label,
                "n": len(bucket_returns),
                "avg_return": round(sum(bucket_returns) / len(bucket_returns), 2),
            })

    return {
        "n_decisions": len(picks),
        "n_bought": sum(p["decision"] == "bought" for p in picks),
        "n_passed": sum(p["decision"] == "passed" for p in picks),
        "bought": bought_summary,
        "passed": passed_summary,
        "decision_accuracy": decision_accuracy,
        "score_calibration": calibration,
        "picks": sorted(picks, key=lambda p: (p["return_pct"] is None, -(p["return_pct"] or 0))),
    }


def scorecard(user_id: int, ttl: int = _TTL_SECONDS) -> dict:
    """Live scorecard for a user, cached per user for `ttl` seconds."""
    now = time.monotonic()
    hit = _CACHE.get(user_id)
    if hit is not None and (now - hit[0]) < ttl:
        return hit[1]
    result = build_scorecard(get_decisions(user_id), _current_price)
    _CACHE[user_id] = (now, result)
    return result


def clear_cache():
    """Drop all cached scorecards (useful in tests)."""
    _CACHE.clear()
