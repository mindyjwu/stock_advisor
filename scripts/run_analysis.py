"""
Core pipeline: runs all agents on the watchlist and returns ranked suggestions.
Parallelized: yfinance fetches run concurrently, sentiment is a single batch LLM call.
Typical runtime: ~8-15 seconds for a 68-stock watchlist.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from concurrent.futures import ThreadPoolExecutor, as_completed

from data.loader import (
    load_watchlist, load_holdings, load_user_settings, fetch_ticker_info,
    fetch_price_history, fetch_vix, current_portfolio_value, holdings_by_symbol
)
from agents.fundamentals import score_fundamentals
from agents.technicals import score_technicals
from agents.sentiment import score_sentiment_batch
from agents.regime import detect_regime, aggregate_score
from agents.position_sizer import compute_suggestion
from db.store import init_db, log_suggestion


def _fetch_one(item):
    """Fetch all yfinance data for one watchlist item. Runs in a thread."""
    symbol = item["symbol"]
    info = fetch_ticker_info(symbol)
    history = fetch_price_history(symbol)
    fund = score_fundamentals(info)
    tech = score_technicals(history)
    return {
        "symbol":    symbol,
        "industry":  item.get("industry", "Unknown"),
        "info":      info,
        "fund":      fund,
        "tech":      tech,
    }


def run_analysis(
    user_id: int,
    status_cb=None,
    use_llm_regime: bool = True,
    max_workers: int = 20,
) -> tuple:
    """Returns (suggestions_list, regime_dict) sorted by score desc, scoped to
    one user's watchlist and holdings.

    max_workers controls parallel yfinance threads. 20 is safe for most
    networks; lower it if you see rate-limit errors.
    """
    init_db()

    vix = fetch_vix()
    if status_cb:
        status_cb("Detecting market regime…")
    regime = detect_regime(vix, use_llm=use_llm_regime)

    # If this user saved a custom factor mix (How It Works page), it overrides
    # the regime's automatic weights for every analysis they run.
    settings = load_user_settings(user_id)
    if settings.get("weights_mode") == "custom":
        w = settings.get("weights") or {}
        total = sum(max(0.0, float(w.get(k, 0) or 0)) for k in ("fund", "tech", "sent"))
        if total > 0:
            regime = dict(
                regime,
                fund=round(max(0.0, float(w.get("fund", 0) or 0)) / total, 3),
                tech=round(max(0.0, float(w.get("tech", 0) or 0)) / total, 3),
                sent=round(max(0.0, float(w.get("sent", 0) or 0)) / total, 3),
                source="user",
                rationale="Using your custom factor mix (set on the How It Works page)",
            )

    holdings = load_holdings(user_id)
    portfolio_value = current_portfolio_value(holdings)
    by_symbol = holdings_by_symbol(holdings)
    watchlist = load_watchlist(user_id)

    if status_cb:
        status_cb(f"Fetching data for {len(watchlist)} stocks in parallel…")

    partial = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_one, item): item["symbol"] for item in watchlist}
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                res = fut.result()
                partial[res["symbol"]] = res
                if status_cb and done % 10 == 0:
                    status_cb(f"Fetched {done}/{len(watchlist)} stocks…")
            except Exception:
                pass

    if status_cb:
        status_cb("Scoring sentiment with AI (one batch call)…")

    symbols_scored = list(partial.keys())
    sent_scores = score_sentiment_batch(symbols_scored)

    results = []
    for symbol, pr in partial.items():
        sent = sent_scores.get(symbol, {"score": 50.0, "reasons": []})
        final = aggregate_score(pr["fund"]["score"], pr["tech"]["score"], sent["score"], regime)

        suggestion = compute_suggestion(
            symbol, final, pr["info"], portfolio_value, by_symbol.get(symbol)
        )
        suggestion["industry"]      = pr["industry"]
        suggestion["day_change_pct"] = pr["info"].get("regularMarketChangePercent")
        suggestion["headlines"]     = sent.get("headlines", [])
        _info = pr["info"]
        suggestion["stats"] = {
            "market_cap":     _info.get("marketCap"),
            "pe":             _info.get("trailingPE"),
            "day_change_pct": _info.get("regularMarketChangePercent"),
            "wk52_change":    _info.get("52WeekChange"),
            "profit_margin":  _info.get("profitMargins"),
            "rev_growth":     _info.get("revenueGrowth"),
            "div_yield":      _info.get("dividendYield"),
            "beta":           _info.get("beta"),
            "wk52_high":      _info.get("fiftyTwoWeekHigh"),
        }

        all_reasons = pr["fund"]["reasons"] + pr["tech"]["reasons"] + sent["reasons"]

        # Agreement signal: three independent models agreeing is a stronger
        # signal than one loud model dragging the average up
        _f, _t, _s = pr["fund"]["score"], pr["tech"]["score"], sent["score"]
        _spread = max(_f, _t, _s) - min(_f, _t, _s)
        if min(_f, _t, _s) >= 60 and _spread <= 25:
            suggestion["confidence"] = "aligned"
            all_reasons.append("All three factors agree — extra confidence")
        elif _spread >= 35:
            suggestion["confidence"] = "mixed"
            all_reasons.append("Heads-up: the three factors disagree on this one")
        else:
            suggestion["confidence"] = "normal"

        suggestion["reasons"]    = all_reasons
        suggestion["fund_score"] = pr["fund"]["score"]
        suggestion["tech_score"] = pr["tech"]["score"]
        suggestion["sent_score"] = sent["score"]

        log_suggestion(
            user_id, suggestion, pr["fund"]["score"], pr["tech"]["score"], sent["score"],
            regime["key"], all_reasons
        )
        results.append(suggestion)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results, regime


if __name__ == "__main__":
    import time
    from db.users import get_owner
    owner = get_owner()
    if not owner:
        sys.exit("No accounts yet — sign up in the app first (the first account becomes the owner).")
    t0 = time.time()
    suggestions, regime = run_analysis(owner["id"], status_cb=print)
    elapsed = time.time() - t0
    print(f"\nRegime: {regime['label']}  (VIX {regime['vix']})")
    print(f"Weights → Fund:{regime['fund']} Tech:{regime['tech']} Sent:{regime['sent']}")
    print(f"Completed in {elapsed:.1f}s\n")
    for s in suggestions:
        print(f"{s['action']:10} {s['symbol']:6} score={s['score']} "
              f"price=${s['current_price']} → ${s['target_price']} "
              f"(+{s['upside_pct']}%)  qty={s['suggested_quantity']}")
