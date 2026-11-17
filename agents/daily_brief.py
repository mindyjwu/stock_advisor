"""
Daily Brief — turns a portfolio into a short list of if-then price rules.

The goal is a page someone can read in five minutes a day:

  * every holding gets a plain stance (Bull / Neutral / Bear) with the reasons,
  * every holding gets a few fixed price levels ("if it closes below $X, sell
    half", "if it reaches $Y, sell a third", "if it dips to $Z, add $250"),
  * each morning the page only has to answer: did anything hit a level?

Design choices that matter:

  * Rules are ANCHORED. They are computed once (when a statement is uploaded or
    a holding first appears) and stored per user. A stop that is recomputed
    from today's price every day drifts down with the stock and never fires.
  * Floors only ratchet UP (a trailing stop), never down.
  * Distances are volatility-scaled (multiples of the 14-day average true
    range) and clamped, so a utility and a small-cap get sensibly different
    room.
  * Everything is mechanical and explainable. Nothing here places orders, and
    none of it is personalised financial advice.
"""
import json
import math
from datetime import date, datetime, timedelta

import pandas as pd

from data.loader import _user_dir

PLAN_FILE = "daily_brief.json"
NEAR_PCT = 0.03            # "getting close" = within 3% of a level
DEFAULT_SETTINGS = {
    "monthly_budget": 1000.0,   # new money per month; buy rules size off this
    "max_weight": 0.08,         # flag any single position above this share
    "hide_below": 0.0,          # hide positions smaller than this ($)
}

# Per-stance rule recipe. Distances are ATR multiples, clamped to [lo, hi] as a
# fraction of price so the numbers stay sane for very calm or very wild stocks.
RECIPES = {
    "Bull": {
        "floor": (3.0, 0.07, 0.22), "floor_fraction": 0.5,
        "targets": [((5.0, 0.12, 0.45), 0.25)],
        "dip": (1.5, 0.035, 0.11),
        "deadline_days": None,
    },
    "Neutral": {
        "floor": (2.5, 0.06, 0.20), "floor_fraction": 0.5,
        "targets": [((2.5, 0.06, 0.25), 1 / 3), ((5.0, 0.12, 0.45), 1 / 3)],
        "dip": (2.0, 0.05, 0.14),          # only used when the trend is up
        "deadline_days": 45,               # only used when sitting on a real loss
    },
    "Bear": {
        "floor": (1.5, 0.04, 0.15), "floor_fraction": 1.0,
        "targets": [((2.0, 0.05, 0.20), 0.5)],
        "dip": None,
        "deadline_days": 30,
    },
}


# ── small helpers ─────────────────────────────────────────────────────────────
def _f(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _today() -> date:
    return date.today()


def _px(v: float) -> float:
    return round(v, 2) if v >= 1 else round(v, 3)


# ── per-holding market metrics ────────────────────────────────────────────────
def compute_metrics(hist: pd.DataFrame, info: dict = None) -> dict:
    """Everything the stance and the rules need, from one price history.
    Returns None when there is not enough history to say anything."""
    if hist is None or len(hist) < 30 or "Close" not in hist:
        return None
    info = info or {}
    h = hist.dropna(subset=["Close"])
    if getattr(h.index, "tz", None) is not None:
        h = h.copy()
        h.index = h.index.tz_localize(None)
    c = h["Close"].astype(float)
    px = float(c.iloc[-1])
    if px <= 0:
        return None
    prev = float(c.iloc[-2])
    hi = h["High"].astype(float) if "High" in h else c
    lo = h["Low"].astype(float) if "Low" in h else c
    tr = pd.concat([hi - lo, (hi - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    if not atr or not math.isfinite(atr):
        atr = px * 0.02

    def ret(days):
        return float(px / c.iloc[-1 - days] - 1) if len(c) > days else None

    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    rsi = float(100 - 100 / (1 + up / dn)) if dn > 0 else 100.0

    year = c.tail(252)
    tgt = _f(info.get("targetMeanPrice"))
    n_an = int(_f(info.get("numberOfAnalystOpinions")) or 0)
    return {
        "price": px, "prev_close": prev, "day_pct": px / prev - 1 if prev else 0.0,
        "day_low": float(lo.iloc[-1]), "day_high": float(hi.iloc[-1]),
        "asof": str(pd.Timestamp(h.index[-1]).date()),
        "atr": atr, "atr_pct": atr / px,
        "sma50": float(c.tail(50).mean()) if len(c) >= 50 else None,
        "sma200": float(c.tail(200).mean()) if len(c) >= 200 else None,
        "hi52": float(year.max()), "lo52": float(year.min()),
        "from_high": px / float(year.max()) - 1,
        "r1m": ret(21), "r3m": ret(63),
        # A "1y" download is ~250 rows; use the oldest row once we have most of a year.
        "r12m": ret(min(251, len(c) - 1)) if len(c) >= 240 else None,
        "rsi": rsi,
        "target": tgt, "n_analysts": n_an,
        "upside": (tgt / px - 1) if tgt else None,
        "rec_mean": _f(info.get("recommendationMean")),
        "rev_growth": _f(info.get("revenueGrowth")),
        "profit_margin": _f(info.get("profitMargins")),
        "forward_pe": _f(info.get("forwardPE")),
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "closes": c, "highs": hi,  # kept for "has it hit since the rules were set"
    }


# ── stance: Bull / Neutral / Bear, with the reasons ───────────────────────────
def assess_stance(m: dict) -> dict:
    """Score -100..+100 from trend, momentum, analysts and fundamentals.
    Every point added or removed leaves a plain-English reason behind."""
    score, good, bad = 0, [], []

    def add(points, text):
        nonlocal score
        score += points
        (good if points > 0 else bad).append(text)

    px = m["price"]
    if m["sma200"]:
        if px > m["sma200"]:
            add(20, f"Above its 200-day average (${m['sma200']:,.2f}) — long-term trend is up")
        else:
            add(-20, f"Below its 200-day average (${m['sma200']:,.2f}) — long-term trend is down")
        if m["sma50"]:
            if m["sma50"] > m["sma200"]:
                add(10, "50-day average is above the 200-day")
            else:
                add(-10, "50-day average has fallen below the 200-day")
    elif m["sma50"]:
        add(10 if px > m["sma50"] else -10,
            f"{'Above' if px > m['sma50'] else 'Below'} its 50-day average (${m['sma50']:,.2f})")

    if m["r3m"] is not None:
        if m["r3m"] > 0.05:
            add(10, f"Up {m['r3m']:.0%} over three months")
        elif m["r3m"] < -0.10:
            add(-10, f"Down {abs(m['r3m']):.0%} over three months")
    if m["r12m"] is not None:
        add(10 if m["r12m"] > 0 else -10,
            f"{'Up' if m['r12m'] > 0 else 'Down'} {abs(m['r12m']):.0%} over twelve months")

    if m["from_high"] > -0.10:
        add(10, f"Within {abs(m['from_high']):.0%} of its 52-week high")
    elif m["from_high"] < -0.35:
        add(-15, f"{abs(m['from_high']):.0%} below its 52-week high")

    if m["upside"] is not None and m["n_analysts"] >= 5:
        if m["upside"] > 0.15:
            add(15, f"{m['n_analysts']} analysts' average target is {m['upside']:.0%} above the price")
        elif m["upside"] < 0:
            add(-10, f"Price is already above the average analyst target (${m['target']:,.2f})")
    if m["rec_mean"] is not None and m["n_analysts"] >= 5:
        if m["rec_mean"] <= 2.0:
            add(5, "Analysts rate it Buy on average")
        elif m["rec_mean"] >= 3.0:
            add(-10, "Analysts rate it Hold or worse on average")

    if m["rev_growth"] is not None:
        if m["rev_growth"] > 0.10:
            add(10, f"Sales growing {m['rev_growth']:.0%} a year")
        elif m["rev_growth"] < 0:
            add(-10, f"Sales shrinking {abs(m['rev_growth']):.0%} a year")
    if m["profit_margin"] is not None:
        if m["profit_margin"] > 0:
            add(5, "Profitable")
        else:
            add(-10, "Not yet profitable")

    label = "Bull" if score >= 25 else "Bear" if score <= -25 else "Neutral"
    return {"label": label, "score": int(_clamp(score, -100, 100)), "for": good, "against": bad}


# ── rule construction (anchored at creation time) ─────────────────────────────
def _dist(m: dict, spec: tuple) -> float:
    k, lo, hi = spec
    return _clamp(k * m["atr_pct"], lo, hi)


def build_rules(m: dict, stance_label: str, gain_pct: float = None, today: date = None) -> dict:
    """Create the stored plan entry for one holding at today's price."""
    today = today or _today()
    r = RECIPES[stance_label]
    px = m["price"]
    rules = []

    floor = _px(px * (1 - _dist(m, r["floor"])))
    rules.append({"id": "floor", "kind": "sell", "trigger": "below", "price": floor,
                  "fraction": r["floor_fraction"], "done": None})

    first_target = None
    for i, (spec, frac) in enumerate(r["targets"], start=1):
        t = px * (1 + _dist(m, spec))
        # For the stretch target, prefer the analysts' average when it is in range.
        if i == len(r["targets"]) and stance_label != "Bear" and m.get("target") and m["n_analysts"] >= 5:
            lo_t, hi_t = px * (1 + r["targets"][-1][0][1]), px * (1 + r["targets"][-1][0][2])
            if lo_t <= m["target"] <= hi_t:
                t = m["target"]
        t = _px(t)
        first_target = first_target or t
        rules.append({"id": f"target{i}", "kind": "sell", "trigger": "above", "price": t,
                      "fraction": frac, "done": None})

    # "If it hasn't recovered by <date>, sell more" — for weak or losing positions.
    wants_deadline = r["deadline_days"] and (
        stance_label == "Bear" or (gain_pct is not None and gain_pct <= -0.15))
    if wants_deadline:
        rules.append({"id": "deadline", "kind": "sell", "trigger": "deadline", "price": first_target,
                      "by": (today + timedelta(days=r["deadline_days"])).isoformat(),
                      "fraction": 0.5, "done": None})

    # Buying: only where the evidence is constructive.
    uptrend = bool(m["sma200"] and px > m["sma200"])
    if r["dip"] and (stance_label == "Bull" or uptrend):
        dip = _px(px * (1 - _dist(m, r["dip"])))
        if dip > floor * 1.015:
            rules.append({"id": "dip", "kind": "buy", "trigger": "below", "price": dip,
                          "guard": floor, "done": None})

    return {"created": today.isoformat(), "ref_price": _px(px), "stance": stance_label, "rules": rules}


# ── plan persistence ──────────────────────────────────────────────────────────
def load_plan(user_id: int) -> dict:
    path = _user_dir(user_id) / PLAN_FILE
    plan = {}
    if path.exists():
        try:
            with open(path) as f:
                plan = json.load(f)
        except Exception:
            plan = {}
    plan.setdefault("entries", {})
    plan.setdefault("statement", None)
    plan.setdefault("log", [])
    plan["settings"] = {**DEFAULT_SETTINGS, **(plan.get("settings") or {})}
    return plan


def save_plan(user_id: int, plan: dict):
    with open(_user_dir(user_id) / PLAN_FILE, "w") as f:
        json.dump(plan, f, indent=2)


def _rule(entry: dict, rule_id: str):
    return next((x for x in entry["rules"] if x["id"] == rule_id), None)


def _fired(rule: dict, m: dict, today: date, since: str = None) -> bool:
    """Is this rule's condition met right now? (ignores 'done')
    `since` is the date the rules were set; deadline rules only count closes after it."""
    px = m["price"]
    if rule["trigger"] == "below":
        if rule["kind"] == "buy":   # a dip is only buyable while the price is actually there
            return px <= rule["price"] and px > rule.get("guard", 0)
        return px <= rule["price"] or _hit_date(rule, m, since) is not None
    if rule["trigger"] == "above":
        # Today's intraday high only counts if today's bar came after the rules
        # were set — otherwise a spike from earlier in the session would "hit" a
        # target that did not exist yet.
        fresh_bar = not since or m.get("asof", "") > since
        return (px >= rule["price"] or (fresh_bar and m["day_high"] >= rule["price"])
                or _hit_date(rule, m, since) is not None)
    if rule["trigger"] == "deadline":
        return today >= date.fromisoformat(rule["by"]) and not _recovered(rule, m, since)
    return False


def _hit_date(rule: dict, m: dict, since: str = None):
    """First day AFTER the rules were set on which a sell level was crossed.
    Sell rules are sticky: a floor that was closed below, or a target that was
    touched, stays 'hit' until the user marks it done — so skipping a day of
    checking the page never hides something that happened."""
    if not since or rule["kind"] != "sell" or rule["trigger"] not in ("below", "above"):
        return None
    series = m.get("closes") if rule["trigger"] == "below" else m.get("highs")
    if series is None:
        return None
    after = series[series.index > pd.Timestamp(since)]
    hits = after[after <= rule["price"]] if rule["trigger"] == "below" else after[after >= rule["price"]]
    return hits.index[0].date() if len(hits) else None


def _recovered(rule: dict, m: dict, since: str = None) -> bool:
    """Deadline rules clear themselves once the stock closes above the bar."""
    closes = m.get("closes")
    if closes is None:
        return m["price"] >= rule["price"]
    if since:
        closes = closes[closes.index >= pd.Timestamp(since)]
    return bool(len(closes) and float(closes.max()) >= rule["price"])


def sync_plan(plan: dict, positions: list, metrics: dict, stances: dict,
              today: date = None, rebuild: bool = False) -> bool:
    """Bring the stored plan in line with what is held today.

      * new holdings get rules; sold holdings are dropped
      * a changed stance rebuilds that holding's rules (unless a sell rule is
        firing right now — re-anchoring would hide it)
      * floors trail upward as the price rises

    Returns True when the plan changed and should be saved.
    """
    today = today or _today()
    changed = False
    held = {p["symbol"]: p for p in positions}
    entries = plan["entries"]

    for sym in list(entries):
        if sym not in held:
            del entries[sym]
            changed = True

    for sym, p in held.items():
        m = metrics.get(sym)
        if not m:
            continue
        label = stances[sym]["label"]
        cost = _f(p.get("cost_basis"))
        gain_pct = (m["price"] / cost - 1) if cost else None
        entry = entries.get(sym)

        if entry is None or rebuild:
            entries[sym] = build_rules(m, label, gain_pct, today)
            changed = True
            continue

        firing = any(x["kind"] == "sell" and not x["done"] and _fired(x, m, today, entry.get("created"))
                     for x in entry["rules"])
        if entry.get("stance") != label and not firing:
            fresh = build_rules(m, label, gain_pct, today)
            fresh["stance_changed_from"] = entry.get("stance")
            entries[sym] = fresh
            changed = True
            continue

        # Trailing floor: only ever moves up, and only while nothing is firing.
        floor = _rule(entry, "floor")
        if floor and not floor["done"] and not firing:
            candidate = _px(m["price"] * (1 - _dist(m, RECIPES[entry["stance"]]["floor"])))
            if candidate > floor["price"] * 1.005:
                floor["price"] = candidate
                dip = _rule(entry, "dip")
                spec = RECIPES[entry["stance"]]["dip"]
                if dip and spec and not dip["done"]:
                    new_dip = _px(m["price"] * (1 - _dist(m, spec)))
                    if new_dip > candidate * 1.015:
                        dip["price"], dip["guard"] = new_dip, candidate
                changed = True
    return changed


def mark_done(plan: dict, symbol: str, rule_id: str, metrics: dict, stances: dict,
              positions: list, today: date = None):
    """The user acted on a rule: log it and re-anchor that holding's rules at
    today's price so the page stops nagging about a level already dealt with."""
    today = today or _today()
    entry = plan["entries"].get(symbol)
    if not entry:
        return
    rule = _rule(entry, rule_id)
    plan["log"].append({"date": today.isoformat(), "symbol": symbol, "rule": rule_id,
                        "price": rule["price"] if rule else None})
    plan["log"] = plan["log"][-200:]
    m = metrics.get(symbol)
    p = next((x for x in positions if x["symbol"] == symbol), None)
    if m and p:
        cost = _f(p.get("cost_basis"))
        plan["entries"][symbol] = build_rules(
            m, stances[symbol]["label"], (m["price"] / cost - 1) if cost else None, today)


# ── evaluation: turn stored rules + live prices into sentences ────────────────
_FRACTION_WORDS = {0.25: "a quarter", 1 / 3: "a third", 0.5: "half", 1.0: "all"}


def _fraction_word(fr: float) -> str:
    for k, w in _FRACTION_WORDS.items():
        if abs(fr - k) < 0.01:
            return w
    return f"{fr:.0%}"


def _shares_text(q: float) -> str:
    if abs(q - round(q)) < 0.005:
        return f"{q:,.0f}"
    return f"{q:,.1f}" if q >= 10 else f"{q:,.2f}" if q >= 1 else f"{q:,.3f}"


def evaluate_rules(entry: dict, m: dict, qty: float, add_dollars: float,
                   can_add: bool, today: date = None) -> list:
    today = today or _today()
    px = m["price"]
    out = []
    for rule in entry["rules"]:
        kind, trig, level = rule["kind"], rule["trigger"], rule["price"]
        fired = _fired(rule, m, today, entry.get("created"))
        dist = level / px - 1                      # signed distance from price to level
        status = "waiting"
        detail = ""

        if trig == "deadline":
            by = date.fromisoformat(rule["by"])
            days_left = (by - today).days
            if _recovered(rule, m, entry.get("created")):
                status = "cleared"
            elif fired:
                status = "triggered"
            elif days_left <= 5:
                status = "near"
            detail = f"{max(days_left, 0)} day{'s' if days_left != 1 else ''} left"
        elif fired:
            status = "triggered"
            hit = _hit_date(rule, m, entry.get("created"))
            if hit and hit != today:
                detail = f"hit {hit:%b} {hit.day}"
        elif abs(dist) <= NEAR_PCT:
            status = "near"

        if kind == "buy" and not can_add:
            status = "blocked"

        if kind == "sell":
            fr = rule["fraction"]
            sh = qty * fr
            amount = sh * px
            what = "sell all of it" if fr >= 0.999 else f"sell {_fraction_word(fr)}"
            size = f"{_shares_text(sh)} share{'s' if abs(sh - 1) > 1e-9 else ''}, about ${amount:,.0f}"
            if rule["id"] == "floor":
                text = f"If it closes below ${level:,.2f} → {what} ({size})"
                why = "Protects you if the drop keeps going."
            elif trig == "deadline":
                by_d = date.fromisoformat(rule["by"])
                text = (f"If it hasn't closed above ${level:,.2f} by "
                        f"{by_d:%b} {by_d.day} → {what} ({size})")
                why = "Stops a weak position from sitting as dead money."
            else:
                text = f"If it reaches ${level:,.2f} → {what} ({size})"
                why = "Locks in some profit on strength; the rest keeps running."
        else:
            text = f"If it dips to ${level:,.2f} and holds above the floor → add about ${add_dollars:,.0f}"
            why = "Buys a pullback in something whose trend is still up."
            if not can_add:
                why = "Paused: this position is already at your size cap."

        if status == "cleared":
            why = "Cleared — it closed above the bar."

        out.append({**rule, "status": status, "text": text, "why": why, "detail": detail,
                    "distance": dist})
    return out


def _long_term_share(lots: list, today: date) -> float:
    """Share of the position held over a year (lower US tax rate on gains)."""
    total = lt = 0.0
    for lot in lots or []:
        q = _f(lot.get("quantity")) or 0
        total += q
        try:
            d = datetime.strptime(lot["date"], "%d %b %Y").date()
            if (today - d).days > 365:
                lt += q
        except Exception:
            continue
    return lt / total if total else None


def build_brief(positions: list, cash: float, plan: dict, hist: dict, infos: dict,
                today: date = None, rebuild: bool = False) -> dict:
    """The whole page as data. `hist` is {symbol: OHLC DataFrame}, `infos` is
    {symbol: yfinance-style info dict}; both may be missing symbols.
    Mutates `plan` in place; brief["plan_changed"] says whether to save it."""
    today = today or _today()
    settings = plan["settings"]
    lots = ((plan.get("statement") or {}).get("lots")) or {}
    names = ((plan.get("statement") or {}).get("names")) or {}

    metrics, stances = {}, {}
    for p in positions:
        sym = p["symbol"]
        m = compute_metrics(hist.get(sym), infos.get(sym))
        if m:
            metrics[sym] = m
            stances[sym] = assess_stance(m)

    plan_changed = sync_plan(plan, positions, metrics, stances, today, rebuild=rebuild)

    def value_of(p):
        m = metrics.get(p["symbol"])
        px = m["price"] if m else (_f(p.get("cost_basis")) or 0)
        return (_f(p.get("quantity")) or 0) * px

    equity = sum(value_of(p) for p in positions)
    total = equity + (cash or 0)
    add_dollars = max(25.0, round(settings["monthly_budget"] / 4 / 25) * 25)

    cards = []
    for p in positions:
        sym = p["symbol"]
        qty = _f(p.get("quantity")) or 0
        cost = _f(p.get("cost_basis")) or 0
        m = metrics.get(sym)
        value = value_of(p)
        weight = value / total if total else 0
        card = {"symbol": sym, "name": names.get(sym) or sym, "quantity": qty, "cost_basis": cost,
                "value": value, "weight": weight, "has_data": bool(m)}
        if not m:
            card.update({"stance": {"label": "No data", "score": 0, "for": [], "against": []},
                         "rules": [], "price": None, "gain": None, "gain_pct": None,
                         "day_pct": None, "oversized": False, "n_triggered": 0, "n_near": 0,
                         "closest": None, "lt_share": None})
            cards.append(card)
            continue

        oversized = weight > settings["max_weight"]
        rules = evaluate_rules(plan["entries"][sym], m, qty, add_dollars,
                               can_add=not oversized, today=today)
        active = [x for x in rules if x["status"] in ("waiting", "near", "triggered")]
        price_rules = [x for x in active if x["trigger"] != "deadline"]
        card.update({
            "name": m["name"] or card["name"], "sector": m["sector"],
            "price": m["price"], "day_pct": m["day_pct"], "asof": m["asof"],
            "gain": value - cost * qty if cost else None,
            "gain_pct": (m["price"] / cost - 1) if cost else None,
            "stance": stances[sym], "rules": rules,
            "stance_changed_from": plan["entries"][sym].get("stance_changed_from"),
            "plan_date": plan["entries"][sym].get("created"),
            "oversized": oversized,
            "trim_to_cap": max(0.0, value - settings["max_weight"] * total) if oversized else 0.0,
            "n_triggered": sum(1 for x in rules if x["status"] == "triggered"),
            "n_near": sum(1 for x in rules if x["status"] == "near"),
            "closest": min((abs(x["distance"]) for x in price_rules), default=None),
            "lt_share": _long_term_share(lots.get(sym), today),
            "stats": {k: m[k] for k in ("sma50", "sma200", "hi52", "lo52", "from_high", "r1m", "r3m",
                                         "r12m", "rsi", "atr_pct", "target", "n_analysts", "upside",
                                         "forward_pe", "rev_growth")},
        })
        cards.append(card)

    cards.sort(key=lambda c: -c["value"])
    live = [c for c in cards if c["has_data"]]
    day_change = sum(c["value"] * c["day_pct"] / (1 + c["day_pct"]) for c in live if c["day_pct"] is not None)

    def flat(status):
        return [{**r, "symbol": c["symbol"], "name": c["name"], "now": c["price"]}
                for c in cards for r in c["rules"] if r["status"] == status]

    return {
        "cards": cards,
        "triggered": flat("triggered"),
        "near": flat("near"),
        "summary": {
            "equity": equity, "cash": cash or 0, "total": total,
            "day_change": day_change,
            "day_pct": day_change / (equity - day_change) if equity - day_change else 0,
            "counts": {k: sum(1 for c in cards if c["stance"]["label"] == k)
                       for k in ("Bull", "Neutral", "Bear", "No data")},
            "value_by_stance": {k: sum(c["value"] for c in cards if c["stance"]["label"] == k)
                                for k in ("Bull", "Neutral", "Bear", "No data")},
            "oversized": [c["symbol"] for c in cards if c.get("oversized")],
            "asof": max((c["asof"] for c in live), default=None),
            "add_dollars": add_dollars,
        },
        "plan_changed": plan_changed,
        "metrics": metrics, "stances": stances,   # for mark_done; not for display
    }
