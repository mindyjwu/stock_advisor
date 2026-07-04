"""
Two-pass broad market scan over the S&P 500:

  Pass 1 (cheap): fundamentals + technicals only, no LLM calls, run across all ~500 tickers
                  in parallel (20 threads, same pattern as run_analysis).
  Pass 2 (full):  fundamentals + technicals + sentiment on the top N shortlist from pass 1.
                  Sentiment is ONE batched LLM call — keeps API cost and latency bounded.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from concurrent.futures import ThreadPoolExecutor, as_completed

from data.sp500 import load_sp500
from data.loader import (
    fetch_ticker_info, fetch_price_history, fetch_price_history_bulk, fetch_vix,
    load_holdings, load_watchlist, current_portfolio_value, holdings_by_symbol,
)
from agents.fundamentals import score_fundamentals
from agents.technicals import score_technicals
from agents.sentiment import score_sentiment_batch
from agents.regime import detect_regime, aggregate_score
from agents.position_sizer import compute_suggestion
from agents.screener import score_styles, diversify_shortlist
from db.store import init_db, log_suggestion, save_scan


def _cheap_score(fund_score: float, tech_score: float, best_style_score: float) -> float:
    """Pre-LLM ranking blend. The style term rewards stocks that are a clear,
    coherent kind of pick (strong value, strong momentum, …) over ones that
    are merely mediocre everywhere."""
    return round(fund_score * 0.45 + tech_score * 0.35 + best_style_score * 0.20, 1)


def _scan_one(item, history=None):
    """Fetch + cheap-score one ticker. Runs in a thread. `history` comes from
    the bulk download; falls back to a per-ticker fetch if missing."""
    symbol = item["symbol"]
    info = fetch_ticker_info(symbol)
    if history is None:
        history = fetch_price_history(symbol, period="3mo")
    fund = score_fundamentals(info)
    tech = score_technicals(history)
    style = score_styles(info, history)
    best_style_score = max(style["styles"].values()) if style["styles"] else 50.0
    return {
        "symbol": symbol,
        "industry": item.get("industry", "Unknown"),
        "fund_score": fund["score"],
        "tech_score": tech["score"],
        "cheap_score": _cheap_score(fund["score"], tech["score"], best_style_score),
        "styles": style["styles"],
        "best_style": style["best_style"],
        "style_chips": style["chips"],
        "info": info,
        "fund_reasons": fund["reasons"],
        "tech_reasons": tech["reasons"],
    }


def scan_market(user_id: int, shortlist_size: int = 25, status_cb=None, max_workers: int = 20) -> tuple[list[dict], list[dict], dict]:
    """
    Returns (full_results, pass1_results, regime).
    full_results: fully scored shortlist (with sentiment), sorted desc.
    pass1_results: all ~500 tickers with cheap score, sorted desc (for transparency).

    max_workers controls parallel yfinance threads for pass 1; lower it if you
    see rate-limit errors.
    """
    init_db()

    vix = fetch_vix()
    if status_cb:
        status_cb("Detecting market regime...")
    regime = detect_regime(vix, use_llm=True)

    universe = load_sp500()
    pass1_results = []

    if status_cb:
        status_cb(f"Bulk-downloading 3-month prices for {len(universe)} tickers...")
    hist_map = fetch_price_history_bulk([u["symbol"] for u in universe], period="3mo")

    if status_cb:
        status_cb("Scoring fundamentals + technicals in parallel...")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_scan_one, item, hist_map.get(item["symbol"])): item["symbol"]
                   for item in universe}
        done = 0
        for fut in as_completed(futures):
            done += 1
            if status_cb and done % 25 == 0:
                status_cb(f"Pass 1: scanned {done}/{len(universe)} tickers...")
            try:
                pass1_results.append(fut.result())
            except Exception:
                continue

    pass1_results.sort(key=lambda x: x["cheap_score"], reverse=True)
    # Sector-diverse shortlist: don't let one hot sector crowd out everything
    shortlist = diversify_shortlist(pass1_results, shortlist_size)

    holdings = load_holdings(user_id)
    watch_symbols = {t["symbol"] for t in load_watchlist(user_id)}
    portfolio_value = current_portfolio_value(holdings)
    by_symbol = holdings_by_symbol(holdings)

    # How many holdings the user already has per industry (for "fits your
    # portfolio" notes on the scan page)
    _uni_industry = {u["symbol"]: u.get("industry", "Unknown") for u in universe}
    held_by_industry = {}
    for held_sym in by_symbol:
        ind = _uni_industry.get(held_sym)
        if ind:
            held_by_industry[ind] = held_by_industry.get(ind, 0) + 1

    if status_cb:
        status_cb(f"Pass 2: scoring sentiment for top {len(shortlist)} with AI (one batch call)...")
    sent_scores = score_sentiment_batch([s["symbol"] for s in shortlist])

    full_results = []
    for item in shortlist:
        symbol = item["symbol"]
        sent = sent_scores.get(symbol, {"score": 50.0, "reasons": []})
        final = aggregate_score(item["fund_score"], item["tech_score"], sent["score"], regime)

        suggestion = compute_suggestion(
            symbol, final, item["info"], portfolio_value, by_symbol.get(symbol)
        )
        suggestion["industry"] = item["industry"]
        suggestion["headlines"] = sent.get("headlines", [])
        suggestion["styles"] = item.get("styles", {})
        suggestion["best_style"] = item.get("best_style")
        suggestion["style_chips"] = item.get("style_chips", [])
        suggestion["held"] = symbol in by_symbol
        suggestion["in_watchlist"] = symbol in watch_symbols
        suggestion["held_in_industry"] = held_by_industry.get(item["industry"], 0)
        _info = item.get("info") or {}
        suggestion["stats"] = {
            "market_cap":     _info.get("marketCap"),
            "pe":             _info.get("trailingPE"),
            "day_change_pct": _info.get("regularMarketChangePercent"),
            "wk52_change":    _info.get("52WeekChange"),
            "profit_margin":  _info.get("profitMargins"),
            "rev_growth":     _info.get("revenueGrowth"),
            "div_yield":      _info.get("dividendYield"),
            "beta":           _info.get("beta"),
        }
        all_reasons = item["fund_reasons"] + item["tech_reasons"] + sent["reasons"]
        suggestion["reasons"] = all_reasons
        suggestion["fund_score"] = item["fund_score"]
        suggestion["tech_score"] = item["tech_score"]
        suggestion["sent_score"] = sent["score"]

        log_suggestion(user_id, suggestion, item["fund_score"], item["tech_score"], sent["score"],
                       regime["key"], all_reasons)
        full_results.append(suggestion)

    full_results.sort(key=lambda x: x["score"], reverse=True)

    # strip bulky 'info' dicts from pass1 before returning
    for r in pass1_results:
        r.pop("info", None)

    save_scan(user_id, full_results, pass1_results, regime)
    return full_results, pass1_results, regime


if __name__ == "__main__":
    from db.users import get_owner
    owner = get_owner()
    if not owner:
        sys.exit("No accounts yet — sign up in the app first (the first account becomes the owner).")
    full, pass1, regime = scan_market(owner["id"], shortlist_size=25, status_cb=print)
    print(f"\nScanned {len(pass1)} S&P 500 tickers, shortlisted top 25 for full scoring.")
    print(f"Regime: {regime['label']} (source={regime['source']})  {regime.get('rationale','')}\n")
    for s in full[:15]:
        print(f"{s['action']:10} {s['symbol']:6} score={s['score']} "
              f"price=${s['current_price']} → ${s['target_price']} (+{s['upside_pct']}%)")
