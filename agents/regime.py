"""
Determines current market regime and sets weights for the three scoring agents.

Two modes:
  - VIX rule-based (fallback, no API key needed)
  - LLM-driven: Claude reads today's macro headlines and classifies the regime,
    sets weights, and gives a one-line rationale.

Regimes:
  calm      fundamentals dominate
  mixed     balanced weighting
  volatile  sentiment and technicals dominate
"""
import os
import json
from anthropic import Anthropic

REGIMES = {
    "calm":     {"label": "Calm / Fundamental-driven", "fund": 0.50, "tech": 0.30, "sent": 0.20},
    "mixed":    {"label": "Mixed market",              "fund": 0.35, "tech": 0.35, "sent": 0.30},
    "volatile": {"label": "Volatile / Sentiment-driven","fund": 0.20, "tech": 0.35, "sent": 0.45},
}

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def detect_regime_vix(vix: float) -> dict:
    if vix < 18:
        key = "calm"
    elif vix <= 28:
        key = "mixed"
    else:
        key = "volatile"
    return {"key": key, "vix": round(vix, 2), "source": "vix_rule",
            "rationale": f"VIX at {vix:.1f}", **REGIMES[key]}


def _fetch_macro_headlines(limit: int = 12) -> list[str]:
    """Pull recent headlines for major market proxies (SPY, ^GSPC) as a macro read."""
    import yfinance as yf
    headlines = []
    for symbol in ("SPY", "^GSPC"):
        try:
            news = yf.Ticker(symbol).news or []
        except Exception:
            news = []
        for item in news:
            title = item.get("title") or item.get("content", {}).get("title")
            if title and title not in headlines:
                headlines.append(title)
        if len(headlines) >= limit:
            break
    return headlines[:limit]


def detect_regime_llm(vix: float) -> dict:
    """LLM-driven regime classification. Falls back to VIX rule on any failure."""
    fallback = detect_regime_vix(vix)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        fallback["rationale"] = "ANTHROPIC_API_KEY not set — used VIX rule instead"
        return fallback

    headlines = _fetch_macro_headlines()
    if not headlines:
        fallback["rationale"] = "No macro headlines found — used VIX rule instead"
        return fallback

    prompt = f"""You are a market regime classifier for a stock advisory tool. \
Classify today's market regime as one of: "calm", "mixed", "volatile".

  - calm: low volatility, steady fundamentals-driven market, news flow is routine
  - mixed: moderate uncertainty, mixed signals, no dominant driver
  - volatile: high volatility, news/macro events dominating price action (Fed decisions, \
geopolitical shocks, earnings surprises, panic/euphoria)

Current VIX: {vix:.1f}

Recent market headlines:
{chr(10).join(f"- {h}" for h in headlines)}

Respond ONLY with JSON: {{"key": "calm|mixed|volatile", "rationale": "one sentence explaining why"}}"""

    try:
        model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
        resp = _get_client().messages.create(
            model=model_id,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = json.loads(text)
        key = data["key"] if data["key"] in REGIMES else fallback["key"]
        return {
            "key": key,
            "vix": round(vix, 2),
            "source": "llm",
            "rationale": data.get("rationale", ""),
            **REGIMES[key],
        }
    except Exception as e:
        fallback["rationale"] = f"LLM regime detection failed ({e}) — used VIX rule instead"
        return fallback


def detect_regime(vix: float, use_llm: bool = True) -> dict:
    if use_llm:
        return detect_regime_llm(vix)
    return detect_regime_vix(vix)


def aggregate_score(fund: float, tech: float, sent: float, regime: dict) -> float:
    return round(
        fund * regime["fund"] + tech * regime["tech"] + sent * regime["sent"], 1
    )
