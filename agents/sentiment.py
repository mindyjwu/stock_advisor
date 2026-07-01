"""Scores a stock 0-100 on news/sentiment using Claude to read recent headlines."""
import os
import json
import yfinance as yf
from anthropic import Anthropic

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _fetch_headlines(symbol: str, limit: int = 8) -> list[str]:
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
        resp = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        data = json.loads(text)
        return {"score": round(float(data["score"]), 1), "reasons": data.get("reasons", [])}
    except Exception as e:
        return {"score": 50.0, "reasons": [f"Sentiment scoring failed: {e}"]}
