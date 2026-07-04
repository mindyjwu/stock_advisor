"""
LLM-powered niche discovery: trace the supply chains of your best-performing
holdings to lesser-known public companies riding the same trend.

Example: you own NVDA and it's up big → AI datacenters need power →
electrical equipment, grid operators, uranium miners → suggest the smaller
names in that chain you probably haven't looked at.

One Claude call per discovery run; every suggested ticker is then validated
against live market data and cheap-scored before it's shown.
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor

from anthropic import Anthropic

from data.loader import fetch_ticker_info, fetch_price_history
from agents.fundamentals import score_fundamentals
from agents.technicals import score_technicals

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _top_winners(holdings: dict, n: int = 5) -> list:
    """Best-performing meaningful positions (by unrealized gain %)."""
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    positions = [p for p in holdings.get("positions", []) if _f(p.get("current_value")) > 300]
    positions.sort(key=lambda p: _f(p.get("unrealized_gl_pct")), reverse=True)
    return positions[:n]


def _validate_idea(idea: dict) -> dict:
    """Attach live data + cheap scores; returns None if the ticker is bogus."""
    sym = (idea.get("ticker") or "").upper().strip()
    if not sym or not sym.replace(".", "").replace("-", "").isalnum():
        return None
    try:
        info = fetch_ticker_info(sym)
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price:
            return None
        history = fetch_price_history(sym, "3mo")
        fund = score_fundamentals(info)
        tech = score_technicals(history)
        return {
            "symbol":      sym,
            "company":     idea.get("company", sym),
            "via":         idea.get("via", ""),
            "connection":  idea.get("connection", ""),
            "price":       round(float(price), 2),
            "market_cap":  info.get("marketCap"),
            "fund_score":  fund["score"],
            "tech_score":  tech["score"],
            "cheap_score": round(fund["score"] * 0.6 + tech["score"] * 0.4, 1),
            "reasons":     (fund["reasons"] + tech["reasons"])[:3],
        }
    except Exception:
        return None


def discover_niche_ideas(holdings: dict, exclude_symbols: set, max_ideas: int = 10) -> dict:
    """Returns {"winners": [...], "ideas": [...]} or {"error": msg}."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"error": "ANTHROPIC_API_KEY not set — this feature needs the AI key."}

    winners = _top_winners(holdings)
    if not winners:
        return {"error": "No meaningful positions found — import your portfolio first."}

    winner_lines = "\n".join(
        f"- {p['symbol']} ({p.get('description', '')}): up {p.get('unrealized_gl_pct', 0):.0f}% "
        f"(${p.get('current_value', 0):,.0f} position)"
        for p in winners
    )
    exclude_note = ", ".join(sorted(exclude_symbols)[:60])

    prompt = f"""You are an equity research analyst specializing in supply-chain analysis.

An investor's best-performing holdings are:
{winner_lines}

For each winner, think through its supply chain and demand chain (suppliers, \
infrastructure it depends on, second-order beneficiaries — e.g. AI chips → \
datacenters → electricity → grid equipment / uranium / cooling).

Suggest {max_ideas} LESSER-KNOWN US-listed public companies positioned to benefit \
from the same trends. Rules:
- Prefer small and mid caps (under ~$50B). NO mega-caps (Apple, Microsoft, Google, Amazon, Meta, Tesla, Broadcom, etc.)
- Do NOT suggest any of these (already owned/tracked): {exclude_note}
- Real, currently traded US tickers only (NYSE/NASDAQ). No ETFs, no OTC.
- Spread across the different winners, not all from one chain.

Respond ONLY with a JSON array:
[{{"ticker": "XYZ", "company": "Name", "via": "NVDA", "connection": "one sentence: how it benefits from the same trend"}}]"""

    try:
        model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
        resp = _get_client().messages.create(
            model=model_id, max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        raw_ideas = json.loads(text)
    except Exception as e:
        return {"error": f"AI discovery failed: {e}"}

    raw_ideas = [i for i in raw_ideas if (i.get("ticker") or "").upper() not in exclude_symbols]

    with ThreadPoolExecutor(max_workers=10) as ex:
        validated = [r for r in ex.map(_validate_idea, raw_ideas) if r is not None]

    validated.sort(key=lambda x: x["cheap_score"], reverse=True)
    return {"winners": [p["symbol"] for p in winners], "ideas": validated}
