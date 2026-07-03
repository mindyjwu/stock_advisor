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
from data.loader import fetch_ticker_info, fetch_price_history, fetch_vix, load_holdings, current_portfolio_value, holdings_by_symbol
from agents.fundamentals import score_fundamentals
from agents.technicals import score_technicals
from agents.sentiment import score_sentiment_batch
from agents.regime import detect_regime, aggregate_score
from agents.position_sizer import compute_suggestion
from db.store import init_db, log_suggestion, save_scan


def _cheap_score(fund_score: float, tech_score: float) -> float:
    """Blend of fundamentals + technicals only, used to rank for shortlisting."""
    return round(fund_score * 0.6 + tech_score * 0.4, 1)


def _scan_one(item):
    """Fetch + cheap-score one ticker. Runs in a thread."""
    symbol = item["symbol"]
    info = fetch_ticker_info(symbol)
    history = fetch_price_history(symbol, period="3mo")
    fund = score_fundamentals(info)
    tech = score_technicals(history)
    return {
        "symbol": symbol,
        "industry": item.get("industry", "Unknown"),
        "fund_score": fund["score"],
        "tech_score": tech["score"],
        "cheap_score": _cheap_score(fund["score"], tech["score"]),
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

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_scan_one, item): item["symbol"] for item in universe}
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
    shortlist = pass1_results[:shortlist_size]

    holdings = load_holdings(user_id)
    portfolio_value = current_portfolio_value(holdings)
    by_symbol = holdings_by_symbol(holdings)

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
