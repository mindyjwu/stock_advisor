"""Scores a stock 0-100 on fundamentals: valuation, growth, balance sheet health."""


def score_fundamentals(info: dict) -> dict:
    pe = info.get("trailingPE")
    peg = info.get("pegRatio")
    rev_growth = info.get("revenueGrowth")
    profit_margin = info.get("profitMargins")
    debt_to_equity = info.get("debtToEquity")

    points = []
    reasons = []

    # Valuation: lower PE/PEG is better, but penalize negative/missing
    if pe and pe > 0:
        if pe < 15:
            points.append(90); reasons.append(f"Attractive valuation (P/E {pe:.1f})")
        elif pe < 25:
            points.append(65); reasons.append(f"Reasonable valuation (P/E {pe:.1f})")
        elif pe < 40:
            points.append(40); reasons.append(f"Elevated valuation (P/E {pe:.1f})")
        else:
            points.append(20); reasons.append(f"Expensive valuation (P/E {pe:.1f})")
    else:
        points.append(50); reasons.append("P/E unavailable")

    if peg and peg > 0:
        if peg < 1:
            points.append(85); reasons.append(f"PEG < 1 ({peg:.2f}) suggests undervalued growth")
        elif peg < 2:
            points.append(55)
        else:
            points.append(30); reasons.append(f"High PEG ({peg:.2f})")

    if rev_growth is not None:
        if rev_growth > 0.15:
            points.append(85); reasons.append(f"Strong revenue growth ({rev_growth*100:.1f}%)")
        elif rev_growth > 0.05:
            points.append(60)
        elif rev_growth > 0:
            points.append(45)
        else:
            points.append(20); reasons.append(f"Declining revenue ({rev_growth*100:.1f}%)")

    if profit_margin is not None:
        if profit_margin > 0.20:
            points.append(85); reasons.append(f"High profit margin ({profit_margin*100:.1f}%)")
        elif profit_margin > 0.10:
            points.append(60)
        elif profit_margin > 0:
            points.append(40)
        else:
            points.append(15); reasons.append("Unprofitable")

    if debt_to_equity is not None:
        if debt_to_equity < 50:
            points.append(75); reasons.append("Low debt load")
        elif debt_to_equity < 150:
            points.append(50)
        else:
            points.append(25); reasons.append(f"High debt/equity ({debt_to_equity:.0f})")

    score = sum(points) / len(points) if points else 50.0
    return {"score": round(score, 1), "reasons": reasons}
