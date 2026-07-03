"""
Deposit-driven allocation engine.

Turns "I want to invest $X" into a concrete, diversified buy plan using the
blended factor scores from the latest analysis run.

Steps:
  1. Optionally re-blend the three factor scores with user-chosen weights
     (quantitative fundamentals, quantitative technicals, qualitative AI
     sentiment). Default is the regime-adjusted blend from the analysis.
  2. Keep only stocks scoring above the risk profile's bar.
  3. Weight dollars by conviction: (score − 50) raised to the profile's
     concentration exponent, so higher scores get disproportionately more.
  4. Enforce per-stock and per-sector caps, and skip stocks that are already
     a big slice of the existing portfolio.
  5. Round to shares and sweep leftover cash into the highest-conviction
     affordable picks.

Pure functions, no network calls — safe to recompute live in the UI.
"""

import math


def _num(v, default=0.0) -> float:
    """Float coercion that treats None/NaN/inf/unparseable as `default`."""
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


PROFILES = {
    "cautious": dict(
        key="cautious",
        label="Cautious",
        emoji="🛡️",
        min_score=65,
        exponent=1.0,
        max_stock_pct=0.20,
        max_sector_pct=0.35,
        max_positions=8,
        concentration_limit=0.08,
        description="Only the highest-conviction picks, spread thin — no stock takes more than 20% of your deposit.",
    ),
    "balanced": dict(
        key="balanced",
        label="Balanced",
        emoji="⚖️",
        min_score=60,
        exponent=1.6,
        max_stock_pct=0.30,
        max_sector_pct=0.45,
        max_positions=6,
        concentration_limit=0.10,
        description="Focused but still diversified — the sweet spot for most people.",
    ),
    "aggressive": dict(
        key="aggressive",
        label="Aggressive",
        emoji="🚀",
        min_score=58,
        exponent=2.4,
        max_stock_pct=0.40,
        max_sector_pct=0.60,
        max_positions=5,
        concentration_limit=0.15,
        description="Concentrates your money in the few strongest signals — bigger swings both ways.",
    ),
}


def _action_for(score: float) -> str:
    if score >= 75: return "Strong Buy"
    if score >= 60: return "Buy"
    if score >= 45: return "Watch"
    return "Avoid"


def conviction_label(score: float) -> str:
    if score >= 78: return "Very strong signals"
    if score >= 70: return "Strong signals"
    if score >= 63: return "Good signals"
    return "Decent signals"


def blend_scores(results: list, weights: dict) -> list:
    """Re-blend fund/tech/sent scores with custom weights (normalized here).

    Each result must carry fund_score / tech_score / sent_score. Returns new
    dicts sorted by the re-blended score; originals are not mutated.
    """
    total = sum(max(0.0, _num(weights.get(k))) for k in ("fund", "tech", "sent")) or 1.0
    wf = max(0.0, _num(weights.get("fund"))) / total
    wt = max(0.0, _num(weights.get("tech"))) / total
    ws = max(0.0, _num(weights.get("sent"))) / total

    out = []
    for r in results:
        f = _num(r.get("fund_score"), 50)
        t = _num(r.get("tech_score"), 50)
        s = _num(r.get("sent_score"), 50)
        rr = dict(r)
        rr["score"] = round(f * wf + t * wt + s * ws, 1)
        rr["action"] = _action_for(rr["score"])
        out.append(rr)
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def portfolio_context(holdings: dict) -> dict:
    """Existing portfolio value and each symbol's share of it (no network)."""
    cash = _num(holdings.get("cash"))
    total = cash
    values = {}
    for p in holdings.get("positions", []):
        v = _num(p.get("current_value"))
        if v <= 0:
            v = _num(p.get("cost_basis")) * _num(p.get("quantity"))
        values[p["symbol"]] = values.get(p["symbol"], 0.0) + v
        total += v
    pct = {s: (v / total if total > 0 else 0.0) for s, v in values.items()}
    return {"total_value": total, "position_pct": pct, "position_value": values}


def _clamp_and_redistribute(weights: dict, cap: float, rounds: int = 4) -> dict:
    """Clamp each weight to `cap`, pushing the excess onto the unclamped ones."""
    w = dict(weights)
    for _ in range(rounds):
        total = sum(w.values()) or 1.0
        w = {k: v / total for k, v in w.items()}
        over = {k: v - cap for k, v in w.items() if v > cap}
        if not over:
            return w
        excess = sum(over.values())
        under = {k: v for k, v in w.items() if v < cap}
        under_total = sum(under.values())
        for k in w:
            if k in over:
                w[k] = cap
            elif under_total > 0:
                w[k] += excess * (w[k] / under_total)
    total = sum(w.values()) or 1.0
    return {k: v / total for k, v in w.items()}


def _why_text(r: dict) -> str:
    reasons = [x for x in (r.get("reasons") or []) if x][:3]
    if reasons:
        return " · ".join(reasons)
    return f"Blended score of {r.get('score', 0):.0f}/100 across fundamentals, trend, and news sentiment."


def build_plan(
    deposit: float,
    results: list,
    holdings: dict,
    profile_key: str = "balanced",
    weights: dict = None,
    allow_fractional: bool = True,
    max_positions: int = None,
) -> dict:
    """Build a buy plan for `deposit` dollars from scored analysis results.

    Returns {picks, skipped, leftover, invested, stats, profile}.
    Each pick: symbol, dollars, shares, pct_of_deposit, price, score, action,
    conviction, why, sector, existing_pct.
    """
    profile = PROFILES.get(profile_key, PROFILES["balanced"])
    n_max = max_positions or profile["max_positions"]
    deposit = float(deposit or 0)

    scored = blend_scores(results, weights) if weights else sorted(
        results, key=lambda x: x.get("score", 0), reverse=True
    )

    ctx = portfolio_context(holdings)
    skipped = []
    candidates = []
    seen = set()

    for r in scored:
        sym = r["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        score = _num(r.get("score"))
        price = _num(r.get("current_price"))
        existing_pct = ctx["position_pct"].get(sym, 0.0)

        if score < profile["min_score"]:
            if score >= profile["min_score"] - 8:  # only note near-misses, not the whole watchlist
                skipped.append({"symbol": sym, "score": score,
                                "reason": f"Score {score:.0f} is below this profile's bar of {profile['min_score']}"})
            continue
        if price <= 0:
            skipped.append({"symbol": sym, "score": score, "reason": "No live price available"})
            continue
        if not allow_fractional and price > deposit:
            skipped.append({"symbol": sym, "score": score,
                            "reason": f"One share (${price:,.0f}) costs more than your whole deposit"})
            continue
        if existing_pct >= profile["concentration_limit"]:
            skipped.append({"symbol": sym, "score": score,
                            "reason": f"Already {existing_pct*100:.0f}% of your portfolio — adding more would over-concentrate"})
            continue
        candidates.append(dict(r, _existing_pct=existing_pct))
        if len(candidates) >= n_max:
            break

    if not candidates or deposit <= 0:
        return {"picks": [], "skipped": skipped, "leftover": deposit, "invested": 0.0,
                "profile": profile, "stats": {"n": 0, "avg_score": 0, "sectors": {}}}

    # Conviction weights: score above neutral, raised to the profile exponent.
    raw = {}
    for r in candidates:
        w = max(1.0, float(r["score"]) - 50.0) ** profile["exponent"]
        if r["_existing_pct"] >= profile["concentration_limit"] / 2:
            w *= 0.5  # already own a meaningful slice — go easier
        raw[r["symbol"]] = w

    w = _clamp_and_redistribute(raw, profile["max_stock_pct"])

    # Sector cap: scale down overweight sectors, hand the excess to the rest.
    by_sym = {r["symbol"]: r for r in candidates}
    sectors = {}
    for sym, wt in w.items():
        sec = by_sym[sym].get("industry") or by_sym[sym].get("sector") or "Other"
        sectors.setdefault(sec, []).append(sym)
    for _ in range(2):
        excess = 0.0
        capped_syms = set()
        for sec, syms in sectors.items():
            sec_w = sum(w[s] for s in syms)
            if sec_w > profile["max_sector_pct"] and len(sectors) > 1:
                scale = profile["max_sector_pct"] / sec_w
                for s in syms:
                    excess += w[s] * (1 - scale)
                    w[s] *= scale
                    capped_syms.add(s)
        if excess <= 1e-9:
            break
        free = [s for s in w if s not in capped_syms]
        free_total = sum(w[s] for s in free)
        for s in free:
            w[s] += excess * (w[s] / free_total) if free_total > 0 else 0
    w = _clamp_and_redistribute(w, profile["max_stock_pct"])

    # Dollars → shares. Drop tiny tickets so the plan stays actionable.
    min_ticket = max(25.0, deposit * 0.02)
    picks = []
    for r in candidates:
        # Hard dollar cap per stock: with few candidates, normalized weights can
        # exceed the cap (1 candidate → weight 1.0). Better to leave cash unspent.
        dollars = min(w[r["symbol"]], profile["max_stock_pct"]) * deposit
        if dollars < min_ticket:
            skipped.append({"symbol": r["symbol"], "score": r["score"],
                            "reason": f"Its slice (${dollars:,.0f}) was too small to be worth a trade"})
            continue
        price = float(r["current_price"])
        if allow_fractional:
            # Floor at 4 decimals — rounding up can overspend on high-priced stocks
            shares = math.floor(dollars / price * 10000) / 10000
        else:
            shares = int(dollars // price)
            if shares == 0:
                skipped.append({"symbol": r["symbol"], "score": r["score"],
                                "reason": f"Share price ${price:,.0f} is bigger than its ${dollars:,.0f} slice — turn on fractional shares to include it"})
                continue
        picks.append(dict(r, _shares=shares))

    # Whole-share remainder sweep: spend leftover on the strongest affordable picks.
    spent = sum(p["_shares"] * float(p["current_price"]) for p in picks)
    if not allow_fractional:
        leftover = deposit - spent
        changed = True
        while changed and leftover > 0:
            changed = False
            for p in sorted(picks, key=lambda x: x["score"], reverse=True):
                price = float(p["current_price"])
                new_val = (p["_shares"] + 1) * price
                if price <= leftover and new_val <= deposit * (profile["max_stock_pct"] + 0.10):
                    p["_shares"] += 1
                    leftover -= price
                    changed = True
        spent = deposit - leftover

    invested = sum(p["_shares"] * float(p["current_price"]) for p in picks)
    leftover = max(0.0, deposit - invested)

    out_picks = []
    for p in sorted(picks, key=lambda x: x["_shares"] * float(x["current_price"]), reverse=True):
        price = float(p["current_price"])
        dollars = p["_shares"] * price
        out_picks.append({
            "symbol":         p["symbol"],
            "dollars":        round(dollars, 2),
            "shares":         p["_shares"],
            "price":          round(price, 2),
            "pct_of_deposit": round(dollars / deposit * 100, 1) if deposit else 0,
            "score":          p["score"],
            "action":         p.get("action", _action_for(p["score"])),
            "conviction":     conviction_label(p["score"]),
            "why":            _why_text(p),
            "sector":         p.get("industry") or p.get("sector") or "Other",
            "existing_pct":   round(p["_existing_pct"] * 100, 1),
            "fund_score":     p.get("fund_score"),
            "tech_score":     p.get("tech_score"),
            "sent_score":     p.get("sent_score"),
            "target_price":   p.get("target_price"),
            "upside_pct":     p.get("upside_pct"),
        })

    sector_mix = {}
    for p in out_picks:
        sector_mix[p["sector"]] = sector_mix.get(p["sector"], 0.0) + p["dollars"]
    avg_score = (sum(p["score"] * p["dollars"] for p in out_picks) / invested) if invested else 0

    return {
        "picks": out_picks,
        "skipped": skipped,
        "leftover": round(leftover, 2),
        "invested": round(invested, 2),
        "profile": profile,
        "stats": {
            "n": len(out_picks),
            "avg_score": round(avg_score, 1),
            "sectors": {k: round(v, 2) for k, v in sorted(sector_mix.items(), key=lambda kv: -kv[1])},
        },
    }
