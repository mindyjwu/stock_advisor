"""
Sell-side companion to the buy engine.

The rest of the app scores *watchlist* candidates for buying. This module looks
at stocks you already **hold** and asks the opposite question: is it time to
sell or trim? It reuses the same technical indicators (RSI/MACD/moving averages)
but adds the things a buy screen ignores — your cost basis (stop-loss and
profit-taking), the analyst price target, and whether the AI thesis has decayed.

evaluate_sell() is a pure function (easy to test). evaluate_holdings() fetches
data for every position a user holds and ranks them by how urgently they warrant
a look.
"""
import math

from agents.technicals import _rsi, _macd

# Verdict thresholds on the 0-100 urgency scale.
TRIM_AT = 35
SELL_AT = 60


def _f(v):
    try:
        x = float(v)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


def _order_plan(verdict, price, flags):
    """Recommend HOW to place the order: a concrete limit price + plain advice.

    - Urgent exits (downtrend / stop-loss breach): limit ~1% under to exit
      promptly, with a market order as the fast alternative.
    - Profit-taking on a big winner: limit ~1% above — sell into strength.
    - Adding to a winner: patient limit ~1% below — buy on a small dip.
    - Otherwise: limit at today's price to lock in the level you see.
    """
    if not price or price <= 0 or verdict == "Hold":
        return None
    urgent = "downtrend" in flags["technical"] or "stop-loss" in flags["risk"]
    if verdict in ("Sell", "Trim") and urgent:
        lim = round(price * 0.99, 2)
        return {"order_type": "Limit", "limit_price": lim,
                "advice": f"Set a **limit-sell at ${lim:,.2f}** (~1% below today's ${price:,.2f}) to "
                          f"exit promptly without chasing it down. In a fast drop, a **market order** "
                          f"gets you out immediately."}
    if verdict in ("Sell", "Trim") and "big winner" in flags["risk"]:
        lim = round(price * 1.01, 2)
        return {"order_type": "Limit", "limit_price": lim,
                "advice": f"Sell into strength: a **limit-sell at ${lim:,.2f}** (~1% above ${price:,.2f}) "
                          f"captures the gain if buyers keep pushing."}
    if verdict in ("Sell", "Trim"):
        lim = round(price, 2)
        return {"order_type": "Limit", "limit_price": lim,
                "advice": f"A **limit-sell at ${lim:,.2f}** (today's price) locks in the level you see now, "
                          f"rather than accepting whatever a market order fills at."}
    if verdict == "Add":
        lim = round(price * 0.99, 2)
        return {"order_type": "Limit", "limit_price": lim,
                "advice": f"No rush — a **limit-buy at ${lim:,.2f}** (~1% below ${price:,.2f}) lets you "
                          f"add on a small dip instead of paying up."}
    return None


_REC_LABEL = {
    "strong_buy": "Strong Buy", "buy": "Buy", "outperform": "Buy",
    "hold": "Hold", "neutral": "Hold",
    "underperform": "Sell", "sell": "Sell", "strong_sell": "Strong Sell",
}


def _analyst_view(info, price):
    """Wall Street consensus from the data feed, so the user can compare our
    position-management call against the analysts' company rating."""
    key = (info.get("recommendationKey") or "").lower()
    n = _f(info.get("numberOfAnalystOpinions"))
    target = _f(info.get("targetMeanPrice"))
    if key in ("", "none") and not n and not target:
        return None
    upside = round((target / price - 1) * 100, 1) if (target and price and price > 0) else None
    return {
        "rating": _REC_LABEL.get(key, key.replace("_", " ").title() or None),
        "mean": _f(info.get("recommendationMean")),   # 1=Strong Buy … 5=Strong Sell
        "n_analysts": int(n) if n else None,
        "target": round(target, 2) if target else None,
        "target_upside_pct": upside,
    }


def _stop_loss_price(price, sma50):
    """A protective stop for holds: the higher of ~10% below price or the
    50-day average (a common 'the trend has broken' line), rounded."""
    if not price or price <= 0:
        return None
    floor = price * 0.90
    ref = max(floor, sma50) if (sma50 and sma50 < price) else floor
    return round(ref, 2)


def evaluate_sell(position: dict, info: dict = None, price_history=None,
                  ai_score: float = None, position_pct: float = None) -> dict:
    """Return a sell/hold/add recommendation for a single held position.

    position: {symbol, quantity, cost_basis, current_price?, current_value?,
               unrealized_gl_pct?}
    info:     yfinance-style info dict (valuation, growth, analyst target)
    price_history: DataFrame with a 'Close' column (and ideally 'Volume')
    ai_score: the latest composite 0-100 score, if an analysis has been run
    position_pct: this position's share of the whole portfolio (0-1), used to
                  avoid recommending you add to something already oversized

    Returns {symbol, verdict (Sell|Trim|Hold|Add), urgency 0-100, reasons[],
             gl_pct, current_price, quantity, suggested_sell_qty, flags,
             order_type, limit_price, order_advice, stop_loss_price}.
    """
    info = info or {}
    symbol = position.get("symbol", "?")
    qty = _f(position.get("quantity")) or 0
    cost_basis = _f(position.get("cost_basis"))
    price = (_f(position.get("current_price")) or _f(info.get("currentPrice"))
             or _f(info.get("regularMarketPrice")))

    gl_pct = _f(position.get("unrealized_gl_pct"))
    if gl_pct is None and cost_basis and price and cost_basis > 0:
        gl_pct = (price - cost_basis) / cost_basis * 100

    urgency = 0.0
    reasons = []
    flags = {"technical": [], "valuation": [], "risk": []}
    sma50_ref = None

    # ── Technicals: trend, momentum, drawdown ────────────────────────────────
    if price_history is not None and not getattr(price_history, "empty", True) and len(price_history) >= 30:
        close = price_history["Close"]
        last = float(close.iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float(close.mean())
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
        sma50_ref = sma50

        if last < sma50 and last < sma200 and sma50 <= sma200:
            urgency += 25
            reasons.append("In a downtrend — price is below both its 50- and 200-day averages")
            flags["technical"].append("downtrend")
        elif last < sma50:
            urgency += 12
            reasons.append("Price has slipped below its 50-day average")
            flags["technical"].append("below 50-day")

        rsi = _rsi(close)
        if rsi is not None and rsi >= 75:
            urgency += 16
            reasons.append(f"Overbought (RSI {rsi:.0f}) — the recent run may be overextended")
            flags["technical"].append("overbought")

        macd_line, signal_line = _macd(close)
        if macd_line < signal_line:
            urgency += 10
            reasons.append("Momentum is fading (MACD turned bearish)")
            flags["technical"].append("MACD bearish")

        high = float(close.max())
        if high > 0:
            drawdown = last / high - 1
            if drawdown <= -0.20:
                urgency += 14
                reasons.append(f"Down {abs(drawdown) * 100:.0f}% from its recent high")
                flags["technical"].append("deep drawdown")

    # ── Valuation / fundamentals ─────────────────────────────────────────────
    pe = _f(info.get("trailingPE")) or _f(info.get("forwardPE"))
    if pe and pe > 50:
        urgency += 10
        reasons.append(f"Expensive valuation (P/E {pe:.0f})")
        flags["valuation"].append("expensive")

    rev_growth = _f(info.get("revenueGrowth"))
    if rev_growth is not None and rev_growth < 0:
        urgency += 12
        reasons.append(f"Revenue is shrinking ({rev_growth * 100:.0f}%)")
        flags["valuation"].append("revenue declining")

    margin = _f(info.get("profitMargins"))
    if margin is not None and margin < 0:
        urgency += 8
        reasons.append("Company is currently unprofitable")
        flags["valuation"].append("unprofitable")

    target = _f(info.get("targetMeanPrice"))
    if target and price and target <= price:
        urgency += 10
        reasons.append("Trading at or above the average analyst price target")
        flags["valuation"].append("above analyst target")

    # ── Position risk & profit-taking (needs your cost basis) ────────────────
    if gl_pct is not None:
        if gl_pct <= -20:
            urgency += 28
            reasons.append(f"Down {abs(gl_pct):.0f}% from your cost — past a typical stop-loss level")
            flags["risk"].append("stop-loss")
        elif gl_pct >= 100:
            urgency += 18
            reasons.append(f"Up {gl_pct:.0f}% — a large gain; consider locking in some profit")
            flags["risk"].append("big winner")
        elif gl_pct >= 50:
            urgency += 10
            reasons.append(f"Up {gl_pct:.0f}% — you could take some profit off the table")
            flags["risk"].append("big winner")

    # ── AI thesis decay ──────────────────────────────────────────────────────
    if ai_score is not None:
        if ai_score < 45:
            urgency += 24
            reasons.append(f"AI score has dropped to {ai_score:.0f}/100 — the case for holding has weakened")
            flags["risk"].append("weak score")
        elif ai_score < 55:
            urgency += 12
            reasons.append(f"AI score is only lukewarm ({ai_score:.0f}/100)")

    urgency = round(min(100.0, urgency))
    if urgency >= SELL_AT:
        verdict = "Sell"
    elif urgency >= TRIM_AT:
        verdict = "Trim"
    else:
        verdict = "Hold"

    # ── Buy-more opportunity: only when it's clearly NOT a sell ───────────────
    # A holding you should add to is one the AI still rates highly, that isn't
    # stretched at its highs, and that you aren't already over-concentrated in.
    add_reasons = []
    if verdict == "Hold" and ai_score is not None and ai_score >= 65:
        add_reasons.append(f"AI still rates it strongly ({ai_score:.0f}/100) — the thesis is intact")
        hi = _f(info.get("fiftyTwoWeekHigh"))
        if hi and price and price < 0.92 * hi:
            add_reasons.append(f"{(1 - price / hi) * 100:.0f}% below its 52-week high — you'd be adding at a fair entry")
        if target and price and target > price * 1.10:
            add_reasons.append(f"analyst target ${target:.0f} implies +{(target / price - 1) * 100:.0f}% more upside")
        if gl_pct is not None and gl_pct > 0:
            add_reasons.append(f"already working for you (+{gl_pct:.0f}%) — a proven winner in your book")
        # Concentration guard: don't pile into something that's already a big slice
        if position_pct is not None and position_pct >= 0.15:
            add_reasons = []
        elif len(add_reasons) < 2:  # need a real reason beyond the score alone
            add_reasons = []
    if add_reasons:
        verdict = "Add"
        reasons = add_reasons

    if verdict == "Hold" and not reasons:
        reasons.append("Signals still look healthy — nothing here says sell.")

    suggested = None
    if verdict == "Sell":
        suggested = int(qty)
    elif verdict == "Trim":
        suggested = int(qty // 2)

    order = _order_plan(verdict, price, flags)
    stop = _stop_loss_price(price, sma50_ref)

    # ── Money math: what you'd actually pocket / lose ────────────────────────
    # Total cost of the whole position, from the broker if available.
    position_cost = _f(position.get("total_cost"))
    if position_cost is None and cost_basis is not None:
        position_cost = cost_basis * qty
    position_value = _f(position.get("current_value"))
    if position_value is None and price is not None:
        position_value = price * qty
    unrealized_gl_dollar = _f(position.get("unrealized_gl"))
    if unrealized_gl_dollar is None and position_value is not None and position_cost is not None:
        unrealized_gl_dollar = position_value - position_cost

    # Realized profit/loss if they follow the sell suggestion, at the sell
    # price we're recommending (limit price), for the suggested share count.
    realized_if_sold = proceeds_if_sold = None
    if verdict in ("Sell", "Trim") and suggested and cost_basis is not None:
        _sell_px = (order["limit_price"] if order else None) or price
        if _sell_px:
            proceeds_if_sold = round(_sell_px * suggested, 2)
            realized_if_sold = round((_sell_px - cost_basis) * suggested, 2)

    return {
        "symbol": symbol,
        "verdict": verdict,
        "urgency": urgency,
        "reasons": reasons,
        "gl_pct": round(gl_pct, 1) if gl_pct is not None else None,
        "current_price": round(price, 2) if price else None,
        "quantity": qty,
        "cost_basis": round(cost_basis, 2) if cost_basis is not None else None,
        "position_cost": round(position_cost, 2) if position_cost is not None else None,
        "position_value": round(position_value, 2) if position_value is not None else None,
        "unrealized_gl_dollar": round(unrealized_gl_dollar, 2) if unrealized_gl_dollar is not None else None,
        "proceeds_if_sold": proceeds_if_sold,
        "realized_if_sold": realized_if_sold,
        "analyst": _analyst_view(info, price),
        "suggested_sell_qty": suggested,
        "flags": flags,
        "order_type": order["order_type"] if order else None,
        "limit_price": order["limit_price"] if order else None,
        "order_advice": order["advice"] if order else None,
        "stop_loss_price": stop,
    }


def ai_sell_review_batch(items: list) -> dict:
    """News-aware 'second opinion' on mechanical SELL flags.

    The rest of this module is purely mechanical — it sees a downtrend and says
    sell, blind to *why*. This asks Claude to read each name's recent headlines
    and known catalysts and judge whether the sell is confirmed by the story, or
    whether there's a specific, credible reason to hold through the weakness
    (a turnaround, a policy tailwind like US-foundry support for INTC, or bad
    news already priced in).

    items: [{symbol, reasons[], gl_pct}]  (typically just the extreme sells)
    Returns {symbol: {stance: Confirm|Reconsider|Mixed, rationale, catalyst}}.
    Empty dict if no API key or on failure — the mechanical verdict still stands.
    """
    import os, json
    from concurrent.futures import ThreadPoolExecutor
    from agents.sentiment import _fetch_headlines, _get_client

    if not items or not os.environ.get("ANTHROPIC_API_KEY"):
        return {}

    symbols = [it["symbol"] for it in items]
    with ThreadPoolExecutor(max_workers=min(10, len(symbols))) as ex:
        heads = dict(zip(symbols, ex.map(lambda s: _fetch_headlines(s, 5), symbols)))

    blocks = []
    for it in items:
        s = it["symbol"]
        hl = heads.get(s) or ["(no recent headlines found)"]
        gl = it.get("gl_pct")
        gl_txt = f"your position is {'up' if (gl or 0) >= 0 else 'down'} {abs(gl):.0f}%" if gl is not None else ""
        blocks.append(f"{s} — mechanical sell signals: {'; '.join(it.get('reasons', [])[:4])}. "
                      f"{gl_txt}\n  Recent headlines:\n    - " + "\n    - ".join(hl[:5]))

    prompt = f"""You are a skeptical portfolio risk analyst giving a second opinion.
Our mechanical model flagged each stock below as a SELL from price/valuation
signals alone — it cannot read news. Decide whether the news and known
catalysts CONFIRM the sell, or whether there is a SPECIFIC, credible reason to
hold through the weakness (a real turnaround, a policy/industry tailwind, or the
bad news already being priced in).

Be honest and disciplined: most downtrends are real. Only say "Reconsider" when
you can name a concrete catalyst — never a vague hope. Prefer "Confirm" when the
weakness looks fundamental.

{chr(10).join(blocks)}

Respond ONLY with JSON mapping each ticker to:
{{"SYMB": {{"stance": "Confirm" | "Reconsider" | "Mixed", "rationale": "1-2 plain sentences a beginner understands", "catalyst": "short phrase, or null if none"}}}}"""

    try:
        model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
        resp = _get_client().messages.create(
            model=model_id, max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = json.loads(text)
        out = {}
        for s in symbols:
            e = data.get(s) or {}
            if e.get("rationale"):
                out[s] = {
                    "stance": e.get("stance", "Mixed"),
                    "rationale": e["rationale"].strip(),
                    "catalyst": (e.get("catalyst") or "").strip() or None,
                }
        return out
    except Exception:
        return {}


def evaluate_holdings(user_id: int, ai_scores: dict = None, max_workers: int = 12) -> list:
    """Run evaluate_sell over every position a user holds, fetching market data
    in parallel. Returns a list sorted by urgency (most urgent first).

    ai_scores: optional {symbol: score} from the latest analysis run, so the
    thesis-decay signal is included when scores are available.
    """
    from concurrent.futures import ThreadPoolExecutor
    from data.loader import load_holdings, fetch_ticker_info, fetch_price_history

    positions = load_holdings(user_id).get("positions", [])
    if not positions:
        return []
    ai_scores = ai_scores or {}

    # Each position's share of the portfolio, so we don't tell you to add to
    # something you already hold too much of.
    _total_val = 0.0
    for p in positions:
        v = _f(p.get("current_value")) or ((_f(p.get("cost_basis")) or 0) * (_f(p.get("quantity")) or 0))
        _total_val += v or 0

    def _pct(p):
        if _total_val <= 0:
            return None
        v = _f(p.get("current_value")) or ((_f(p.get("cost_basis")) or 0) * (_f(p.get("quantity")) or 0))
        return (v or 0) / _total_val

    def _one(p):
        sym = p["symbol"]
        try:
            info = fetch_ticker_info(sym)
        except Exception:
            info = {}
        try:
            hist = fetch_price_history(sym, period="6mo")
        except Exception:
            hist = None
        return evaluate_sell(p, info, hist, ai_scores.get(sym), _pct(p))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_one, positions))
    results.sort(key=lambda r: r["urgency"], reverse=True)
    return results
