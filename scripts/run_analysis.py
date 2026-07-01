"""
Core pipeline: runs all agents on the watchlist and returns ranked suggestions.
Call this from the dashboard or CLI.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from data.loader import (
    load_watchlist, load_holdings, fetch_ticker_info,
    fetch_price_history, fetch_vix, current_portfolio_value, holdings_by_symbol
)
from agents.fundamentals import score_fundamentals
from agents.technicals import score_technicals
from agents.sentiment import score_sentiment
from agents.regime import detect_regime, aggregate_score
from agents.position_sizer import compute_suggestion
from db.store import init_db, log_suggestion


def run_analysis(status_cb=None, use_llm_regime: bool = True) -> tuple[list[dict], dict]:
    """Returns (suggestions_list, regime_dict) sorted by score desc."""
    init_db()

    vix = fetch_vix()
    if status_cb:
        status_cb("Detecting market regime...")
    regime = detect_regime(vix, use_llm=use_llm_regime)

    holdings = load_holdings()
    portfolio_value = current_portfolio_value(holdings)
    by_symbol = holdings_by_symbol(holdings)
    watchlist = load_watchlist()

    results = []
    for item in watchlist:
        symbol = item["symbol"]
        industry = item.get("industry", "Unknown")
        if status_cb:
            status_cb(f"Analyzing {symbol}...")

        info = fetch_ticker_info(symbol)
        history = fetch_price_history(symbol)

        fund = score_fundamentals(info)
        tech = score_technicals(history)
        sent = score_sentiment(symbol)

        final = aggregate_score(fund["score"], tech["score"], sent["score"], regime)

        suggestion = compute_suggestion(
            symbol, final, info, portfolio_value, by_symbol.get(symbol)
        )
        suggestion["industry"] = industry
        suggestion["day_change_pct"] = info.get("regularMarketChangePercent")

        all_reasons = fund["reasons"] + tech["reasons"] + sent["reasons"]
        suggestion["reasons"] = all_reasons
        suggestion["fund_score"] = fund["score"]
        suggestion["tech_score"] = tech["score"]
        suggestion["sent_score"] = sent["score"]

        log_suggestion(suggestion, fund["score"], tech["score"], sent["score"],
                       regime["key"], all_reasons)
        results.append(suggestion)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results, regime


if __name__ == "__main__":
    suggestions, regime = run_analysis(status_cb=print)
    print(f"\nRegime: {regime['label']}  (VIX {regime['vix']})")
    print(f"Weights → Fund:{regime['fund']} Tech:{regime['tech']} Sent:{regime['sent']}\n")
    for s in suggestions:
        print(f"{s['action']:10} {s['symbol']:6} score={s['score']} "
              f"price=${s['current_price']} → ${s['target_price']} "
              f"(+{s['upside_pct']}%)  qty={s['suggested_quantity']}")
