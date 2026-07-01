"""
Alert trigger rules, evaluated against fresh suggestion results.

Trigger types:
  - strong_buy_flip   action newly becomes "Strong Buy" (wasn't on the previous run)
  - price_target_hit  current price has reached/exceeded the computed target price
  - big_move          intraday price move vs previous close exceeds threshold
"""
from datetime import date

BIG_MOVE_PCT = 5.0


def check_triggers(results: list[dict], previous_actions: dict) -> list[dict]:
    """
    results: list of suggestion dicts from run_analysis (must include 'info' is NOT required;
              expects symbol, action, score, current_price, target_price).
    previous_actions: {symbol: last_action} from the prior run, for flip detection.
    Returns list of alert dicts: {symbol, type, message, dedup_key}
    """
    today = date.today().isoformat()
    alerts = []

    for r in results:
        symbol = r["symbol"]
        action = r["action"]
        prev = previous_actions.get(symbol)

        if action == "Strong Buy" and prev != "Strong Buy":
            alerts.append({
                "symbol": symbol,
                "type": "strong_buy_flip",
                "message": f"{symbol} just became a Strong Buy (score {r['score']}) at ${r['current_price']}",
                "dedup_key": f"{symbol}:strong_buy_flip:{today}",
            })

        if r["current_price"] >= r["target_price"] and r["target_price"] > 0:
            alerts.append({
                "symbol": symbol,
                "type": "price_target_hit",
                "message": f"{symbol} hit its target price: ${r['current_price']} >= ${r['target_price']}",
                "dedup_key": f"{symbol}:price_target_hit:{today}",
            })

        day_change_pct = r.get("day_change_pct")
        if day_change_pct is not None and abs(day_change_pct) >= BIG_MOVE_PCT:
            direction = "up" if day_change_pct > 0 else "down"
            alerts.append({
                "symbol": symbol,
                "type": "big_move",
                "message": f"{symbol} is {direction} {abs(day_change_pct):.1f}% today (${r['current_price']})",
                "dedup_key": f"{symbol}:big_move:{today}",
            })

    return alerts
