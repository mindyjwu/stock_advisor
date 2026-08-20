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


def evaluate_sell(position: dict, info: dict = None, price_history=None,
                  ai_score: float = None) -> dict:
    """Return a sell recommendation for a single held position.

    position: {symbol, quantity, cost_basis, current_price?, current_value?,
               unrealized_gl_pct?}
    info:     yfinance-style info dict (valuation, growth, analyst target)
    price_history: DataFrame with a 'Close' column (and ideally 'Volume')
    ai_score: the latest composite 0-100 score, if an analysis has been run

    Returns {symbol, verdict (Hold|Trim|Sell), urgency 0-100, reasons[],
             gl_pct, current_price, quantity, suggested_sell_qty, flags}.
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

    # ── Technicals: trend, momentum, drawdown ────────────────────────────────
    if price_history is not None and not getattr(price_history, "empty", True) and len(price_history) >= 30:
        close = price_history["Close"]
        last = float(close.iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float(close.mean())
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())

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

    if verdict == "Hold" and not reasons:
        reasons.append("Signals still look healthy — nothing here says sell.")

    suggested = None
    if verdict == "Sell":
        suggested = int(qty)
    elif verdict == "Trim":
        suggested = int(qty // 2)

    return {
        "symbol": symbol,
        "verdict": verdict,
        "urgency": urgency,
        "reasons": reasons,
        "gl_pct": round(gl_pct, 1) if gl_pct is not None else None,
        "current_price": round(price, 2) if price else None,
        "quantity": qty,
        "suggested_sell_qty": suggested,
        "flags": flags,
    }


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
        return evaluate_sell(p, info, hist, ai_scores.get(sym))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_one, positions))
    results.sort(key=lambda r: r["urgency"], reverse=True)
    return results
