"""
Style-based screening for the market scan.

Scores each stock 0-100 against five classic investing styles using data the
scan already fetched (no extra network calls):

  value     cheap relative to earnings/growth (P/E, PEG, price/book)
  growth    revenue and earnings expanding fast
  momentum  price trending up over the last 3 months
  quality   profitable, efficient, low debt
  dividend  meaningful, sustainable payout

Each stock gets a best_style tag and human-readable chips — the scan page
uses these so a beginner can tell WHAT KIND of pick something is, and can
filter recommendations by the style they want.
"""
import math

STYLE_META = {
    "value":    {"label": "Value",    "emoji": "💎", "blurb": "priced low for what the company earns"},
    "growth":   {"label": "Growth",   "emoji": "🌱", "blurb": "sales and profits expanding fast"},
    "momentum": {"label": "Momentum", "emoji": "🚀", "blurb": "price trending strongly upward"},
    "quality":  {"label": "Quality",  "emoji": "🛡️", "blurb": "very profitable with low debt"},
    "dividend": {"label": "Dividend", "emoji": "💰", "blurb": "pays you cash regularly"},
}


def _num(v, default=None):
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def _avg(points):
    return round(sum(points) / len(points), 1) if points else 50.0


def _score_value(info) -> float:
    points = []
    pe = _num(info.get("trailingPE"))
    if pe is not None and pe > 0:
        points.append(90 if pe < 12 else 70 if pe < 18 else 45 if pe < 28 else 20)
    peg = _num(info.get("pegRatio"))
    if peg is not None and peg > 0:
        points.append(90 if peg < 1 else 60 if peg < 2 else 25)
    pb = _num(info.get("priceToBook"))
    if pb is not None and pb > 0:
        points.append(80 if pb < 1.5 else 60 if pb < 3 else 35)
    return _avg(points)


def _score_growth(info) -> float:
    points = []
    rg = _num(info.get("revenueGrowth"))
    if rg is not None:
        points.append(95 if rg > 0.25 else 75 if rg > 0.12 else 50 if rg > 0.04 else 20)
    eg = _num(info.get("earningsGrowth"))
    if eg is not None:
        points.append(95 if eg > 0.30 else 75 if eg > 0.15 else 50 if eg > 0.05 else 20)
    return _avg(points)


def _score_momentum(info, history) -> float:
    points = []
    if history is not None and len(history) >= 40:
        close = history["Close"]
        ret_3mo = (close.iloc[-1] / close.iloc[0] - 1) * 100
        points.append(95 if ret_3mo > 20 else 75 if ret_3mo > 8 else 50 if ret_3mo > 0 else 20)
        sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else close.mean()
        points.append(75 if close.iloc[-1] > sma50 else 30)
    chg_52w = _num(info.get("52WeekChange"))
    if chg_52w is not None:
        points.append(90 if chg_52w > 0.4 else 70 if chg_52w > 0.15 else 45 if chg_52w > 0 else 20)
    return _avg(points)


def _score_quality(info) -> float:
    points = []
    pm = _num(info.get("profitMargins"))
    if pm is not None:
        points.append(95 if pm > 0.25 else 75 if pm > 0.15 else 50 if pm > 0.05 else 15)
    roe = _num(info.get("returnOnEquity"))
    if roe is not None:
        points.append(90 if roe > 0.25 else 70 if roe > 0.12 else 45 if roe > 0 else 15)
    de = _num(info.get("debtToEquity"))
    if de is not None:
        points.append(85 if de < 40 else 60 if de < 120 else 25)
    return _avg(points)


def _score_dividend(info) -> float:
    dy = _num(info.get("dividendYield"))
    if dy is None or dy <= 0:
        return 0.0
    # yfinance sometimes reports 0.034, sometimes 3.4 — normalize to percent
    dy_pct = dy * 100 if dy < 1 else dy
    points = [90 if dy_pct > 3.5 else 70 if dy_pct > 2 else 45 if dy_pct > 1 else 25]
    payout = _num(info.get("payoutRatio"))
    if payout is not None and payout > 0:
        # very high payout ratios are a sustainability red flag
        points.append(80 if payout < 0.6 else 45 if payout < 0.85 else 15)
    return _avg(points)


def score_styles(info: dict, history) -> dict:
    """Returns {styles: {name: 0-100}, best_style, chips: [str, ...]}."""
    styles = {
        "value":    _score_value(info),
        "growth":   _score_growth(info),
        "momentum": _score_momentum(info, history),
        "quality":  _score_quality(info),
        "dividend": _score_dividend(info),
    }
    strong = {k: v for k, v in styles.items() if v >= 65}
    best = max(strong, key=strong.get) if strong else None
    chips = [
        f"{STYLE_META[k]['emoji']} {STYLE_META[k]['label']}"
        for k, v in sorted(styles.items(), key=lambda kv: -kv[1]) if v >= 65
    ][:3]
    return {"styles": styles, "best_style": best, "chips": chips}


def diversify_shortlist(ranked: list, size: int, sector_cap_frac: float = 0.35) -> list:
    """Pick the top `size` from a ranked list while capping any one sector to
    ~35% of the shortlist — recommendations shouldn't be one big tech bet.

    If the cap leaves slots unfilled, it is relaxed one notch at a time (so
    the extra slots still go to the most diverse mix available, in rank
    order) instead of falling back to pure rank."""
    cap = max(2, int(size * sector_cap_frac))
    picked, counts, chosen = [], {}, set()
    while len(picked) < min(size, len(ranked)):
        for r in ranked:
            if len(picked) >= size:
                break
            if id(r) in chosen:
                continue
            sec = r.get("industry") or "Unknown"
            if counts.get(sec, 0) < cap:
                picked.append(r)
                chosen.add(id(r))
                counts[sec] = counts.get(sec, 0) + 1
        cap += 1
    return picked
