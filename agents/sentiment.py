"""Scores stocks 0-100 on news/sentiment using Claude."""
import os
import json
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
from anthropic import Anthropic

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _fetch_headlines(symbol: str, limit: int = 5) -> list:
    try:
        news = yf.Ticker(symbol).news or []
    except Exception:
        news = []
    headlines = []
    for item in news[:limit]:
        title = item.get("title") or item.get("content", {}).get("title")
        if title:
            headlines.append(title)
    return headlines


def score_sentiment(symbol: str) -> dict:
    headlines = _fetch_headlines(symbol)
    if not headlines:
        return {"score": 50.0, "reasons": ["No recent headlines found"]}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"score": 50.0, "reasons": ["ANTHROPIC_API_KEY not set — sentiment skipped"]}

    prompt = f"""You are a financial sentiment scorer. Given these recent headlines about {symbol}, \
score overall sentiment from 0 (very bearish) to 100 (very bullish), with 50 being neutral.

Headlines:
{chr(10).join(f"- {h}" for h in headlines)}

Respond ONLY with JSON: {{"score": <number 0-100>, "reasons": ["short reason 1", "short reason 2"]}}"""

    try:
        model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
        resp = _get_client().messages.create(
            model=model_id, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = json.loads(text)
        return {"score": round(float(data["score"]), 1), "reasons": data.get("reasons", [])}
    except Exception as e:
        return {"score": 50.0, "reasons": [f"Sentiment scoring failed: {e}"]}


def score_sentiment_batch(symbols: list) -> dict:
    """Score all symbols in ONE Claude call. Returns {symbol: {score, reasons}}.
    Falls back to 50/neutral on any failure. Much faster than one call per stock."""
    if not symbols:
        return {}

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {s: {"score": 50.0, "reasons": ["ANTHROPIC_API_KEY not set"]} for s in symbols}

    # Fetch headlines in parallel
    all_headlines = {}

    def _fetch(sym):
        return sym, _fetch_headlines(sym, limit=4)

    with ThreadPoolExecutor(max_workers=20) as ex:
        for sym, hl in ex.map(lambda s: _fetch(s), symbols):
            if hl:
                all_headlines[sym] = hl

    if not all_headlines:
        return {s: {"score": 50.0, "reasons": ["No headlines found"]} for s in symbols}

    lines = []
    for sym in symbols:
        hl = all_headlines.get(sym, [])
        if hl:
            lines.append(f"{sym}: " + " | ".join(hl[:3]))
        else:
            lines.append(f"{sym}: (no headlines)")

    prompt = f"""You are a financial sentiment scorer. Score each stock's sentiment 0-100 (50=neutral, 0=very bearish, 100=very bullish).

{chr(10).join(lines)}

Respond ONLY with compact JSON mapping every ticker to its score and 1-2 short reasons.
Example format: {{"AAPL": {{"score": 65, "reasons": ["strong iPhone demand"]}}, "MSFT": {{"score": 72, "reasons": ["AI revenue beat"]}}}}
Include ALL tickers listed above, even those with no headlines (score them 50)."""

    try:
        model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
        resp = _get_client().messages.create(
            model=model_id, max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = json.loads(text)
        out = {}
        for sym in symbols:
            entry = data.get(sym, {})
            out[sym] = {
                "score":     round(float(entry.get("score", 50)), 1),
                "reasons":   entry.get("reasons", []),
                "headlines": all_headlines.get(sym, []),
            }
        return out
    except Exception as e:
        return {s: {"score": 50.0, "reasons": [f"Batch sentiment failed: {e}"]} for s in symbols}
