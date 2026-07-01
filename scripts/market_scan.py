"""
Two-pass broad market scan over the S&P 500:

  Pass 1 (cheap): fundamentals + technicals only, no LLM calls, run across all ~500 tickers.
  Pass 2 (full):  fundamentals + technicals + sentiment, run only on the top N shortlist
                  from pass 1 — keeps LLM/API cost bounded.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from data.sp500 import load_sp500
from data.loader import fetch_ticker_info, fetch_price_history, fetch_vix, load_holdings, current_portfolio_value, holdings_by_symbol
from agents.fundamentals import score_fundamentals
from agents.technicals import score_technicals
from agents.sentiment import score_sentiment
from agents.regime import detect_regime, aggregate_score
from agents.position_sizer import compute_suggestion
from db.store import init_db, log_suggestion


def _cheap_score(fund_score: float, tech_score: float) -> float:
    """Blend of fundamentals + technicals only, used to rank for shortlisting."""
    return round(fund_score * 0.6 + tech_score * 0.4, 1)


def scan_market(shortlist_size: int = 25, status_cb=None) -> tuple[list[dict], list[dict], dict]:
    """
    Returns (full_results, pass1_results, regime).
    full_results: fully scored shortlist (with sentiment), sorted desc.
    pass1_results: all ~500 tickers with cheap score, sorted desc (for transparency).
    """
    init_db()

    vix = fetch_vix()
    if status_cb:
        status_cb("Detecting market regime...")
    regime = detect_regime(vix, use_llm=True)

    universe = load_sp500()
    pass1_results = []

    for i, item in enumerate(universe):
        symbol = item["symbol"]
        if status_cb and i % 25 == 0:
            status_cb(f"Pass 1: scanning {i+1}/{len(universe)} ({symbol})...")
        try:
            info = fetch_ticker_info(symbol)
            history = fetch_price_history(symbol, period="3mo")
            fund = score_fundamentals(info)
            tech = score_technicals(history)
            cheap = _cheap_score(fund["score"], tech["score"])
            pass1_results.append({
                "symbol": symbol,
                "industry": item.get("industry", "Unknown"),
                "fund_score": fund["score"],
                "tech_score": tech["score"],
                "cheap_score": cheap,
                "info": info,
                "fund_reasons": fund["reasons"],
                "tech_reasons": tech["reasons"],
            })
        except Exception:
            continue

    pass1_results.sort(key=lambda x: x["cheap_score"], reverse=True)
    shortlist = pass1_results[:shortlist_size]

    holdings = load_holdings()
    portfolio_value = current_portfolio_value(holdings)
    by_symbol = holdings_by_symbol(holdings)

    full_results = []
    for i, item in enumerate(shortlist):
        symbol = item["symbol"]
        if status_cb:
            status_cb(f"Pass 2: full scoring {i+1}/{len(shortlist)} ({symbol})...")

        sent = score_sentiment(symbol)
        final = aggregate_score(item["fund_score"], item["tech_score"], sent["score"], regime)

        suggestion = compute_suggestion(
            symbol, final, item["info"], portfolio_value, by_symbol.get(symbol)
        )
        suggestion["industry"] = item["industry"]
        all_reasons = item["fund_reasons"] + item["tech_reasons"] + sent["reasons"]
        suggestion["reasons"] = all_reasons
        suggestion["fund_score"] = item["fund_score"]
        suggestion["tech_score"] = item["tech_score"]
        suggestion["sent_score"] = sent["score"]

        log_suggestion(suggestion, item["fund_score"], item["tech_score"], sent["score"],
                       regime["key"], all_reasons)
        full_results.append(suggestion)

    full_results.sort(key=lambda x: x["score"], reverse=True)

    # strip bulky 'info' dicts from pass1 before returning
    for r in pass1_results:
        r.pop("info", None)

    return full_results, pass1_results, regime


if __name__ == "__main__":
    full, pass1, regime = scan_market(shortlist_size=25, status_cb=print)
    print(f"\nScanned {len(pass1)} S&P 500 tickers, shortlisted top 25 for full scoring.")
    print(f"Regime: {regime['label']} (source={regime['source']})  {regime.get('rationale','')}\n")
    for s in full[:15]:
        print(f"{s['action']:10} {s['symbol']:6} score={s['score']} "
              f"price=${s['current_price']} → ${s['target_price']} (+{s['upside_pct']}%)")
