"""
Given a final score and portfolio context, compute:
  - entry_price   (current price)
  - target_price  (analyst target from yfinance, or +15/25/35% based on conviction)
  - quantity      (position-size % of portfolio, capped by existing concentration)
  - action        (Strong Buy / Buy / Watch / Avoid)
"""

SCORE_TO_ACTION = {
    (75, 100): ("Strong Buy", 0.05),   # up to 5% of portfolio
    (60, 75):  ("Buy",        0.03),
    (45, 60):  ("Watch",      0.00),
    (0,  45):  ("Avoid",      0.00),
}

TARGET_UPSIDE = {
    "Strong Buy": 0.35,
    "Buy":        0.20,
    "Watch":      0.10,
    "Avoid":      0.05,
}


def _get_action_and_alloc(score: float) -> tuple[str, float]:
    for (lo, hi), (action, alloc) in SCORE_TO_ACTION.items():
        if lo <= score < hi or (hi == 100 and score == 100):
            return action, alloc
    return "Watch", 0.0


def compute_suggestion(
    symbol: str,
    score: float,
    info: dict,
    portfolio_value: float,
    existing_position,
) -> dict:
    current_price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or info.get("previousClose")
        or 0.0
    )
    analyst_target = info.get("targetMeanPrice")

    action, alloc_pct = _get_action_and_alloc(score)

    if analyst_target and analyst_target > current_price:
        target_price = round(analyst_target, 2)
    else:
        upside = TARGET_UPSIDE[action]
        target_price = round(current_price * (1 + upside), 2)

    # Position sizing: alloc_pct of portfolio, adjusted for existing holdings
    existing_qty = existing_position["quantity"] if existing_position else 0
    existing_value = existing_qty * current_price
    existing_pct = existing_value / portfolio_value if portfolio_value > 0 else 0

    # Don't suggest adding if already at or above target allocation
    max_new_value = max(0, portfolio_value * alloc_pct - existing_value)
    quantity = int(max_new_value // current_price) if current_price > 0 else 0

    upside_pct = (
        round((target_price - current_price) / current_price * 100, 1)
        if current_price > 0 else 0.0
    )

    return {
        "symbol": symbol,
        "action": action,
        "score": score,
        "current_price": round(current_price, 2),
        "target_price": target_price,
        "upside_pct": upside_pct,
        "suggested_quantity": quantity,
        "existing_quantity": existing_qty,
        "existing_pct_of_portfolio": round(existing_pct * 100, 1),
    }
