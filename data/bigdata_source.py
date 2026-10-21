"""
Bigdata.com (RavenPack) as the news/intelligence source.

Bigdata is a document-intelligence platform, not a price feed — so it powers
the parts of the app where it is genuinely better than scraping Yahoo: the
**News Mood** layer (entity-resolved, deduplicated institutional news instead
of noisy ticker-matched headlines) and richer qualitative context. Live prices
and fundamental ratios still come from yfinance (data/loader.py).

Everything here is OPTIONAL and feature-gated: with no Bigdata credentials, or
if the SDK isn't installed, `enabled()` is False and callers fall back to the
existing yfinance path — the app behaves exactly as before.

Credentials (set either in the environment / .env):
  BIGDATA_API_KEY=...                      # preferred
  — or —
  BIGDATA_USERNAME=...  BIGDATA_PASSWORD=...

Get an API key from your Bigdata.com account settings.
"""
import os
from functools import lru_cache

try:  # SDK is optional — guard the import so the app runs without it
    from bigdata_client import Bigdata
    from bigdata_client.query import Entity
    from bigdata_client.daterange import RollingDateRange
    from bigdata_client.models.search import DocumentType, SortBy
    _SDK_OK = True
except Exception:
    _SDK_OK = False

_client = None
_DATE_RANGES = None


def enabled() -> bool:
    """True only when the SDK is importable AND credentials are present."""
    if not _SDK_OK:
        return False
    return bool(os.environ.get("BIGDATA_API_KEY")
                or (os.environ.get("BIGDATA_USERNAME") and os.environ.get("BIGDATA_PASSWORD")))


def _get_client():
    global _client
    if _client is None:
        api_key = os.environ.get("BIGDATA_API_KEY")
        if api_key:
            _client = Bigdata(api_key=api_key)
        else:
            _client = Bigdata(os.environ.get("BIGDATA_USERNAME"),
                              os.environ.get("BIGDATA_PASSWORD"))
    return _client


@lru_cache(maxsize=2048)
def _resolve_entity(symbol: str):
    """Map a ticker to its Bigdata company entity id. Cached — a ticker's
    identity never changes. Returns None if it can't be resolved."""
    try:
        companies = _get_client().knowledge_graph.find_companies(symbol)
        if isinstance(companies, dict):  # dict form when a list is passed
            companies = companies.get(symbol, [])
        if not companies:
            return None
        sym = symbol.upper()
        # Prefer the exact ticker match; otherwise the top (most relevant) hit
        for c in companies:
            if (getattr(c, "ticker", "") or "").upper() == sym:
                return c.id
        return companies[0].id
    except Exception:
        return None


def _range(rolling_name: str):
    return getattr(RollingDateRange, rolling_name, RollingDateRange.LAST_SEVEN_DAYS)


def fetch_headlines(symbol: str, limit: int = 6, window: str = "LAST_SEVEN_DAYS") -> list:
    """Recent, deduplicated news headlines about this company from Bigdata.
    Returns [] on any failure so the caller can fall back to yfinance."""
    if not enabled():
        return []
    entity_id = _resolve_entity(symbol)
    if not entity_id:
        return []
    try:
        search = _get_client().search.new(
            Entity(entity_id), date_range=_range(window),
            sortby=SortBy.RELEVANCE, scope=DocumentType.NEWS,
        )
        docs = search.run(limit=max(limit * 2, 10))
        seen, out = set(), []
        for d in docs:
            h = (getattr(d, "headline", "") or "").strip()
            if h and h.lower() not in seen:
                seen.add(h.lower())
                out.append(h)
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def fetch_news_sentiment(symbol: str, window: str = "LAST_SEVEN_DAYS") -> float:
    """Average Bigdata document sentiment (-1 very negative … +1 very positive)
    for recent news, or None if unavailable. An institutional-NLP signal the
    app can surface alongside the Claude read."""
    if not enabled():
        return None
    entity_id = _resolve_entity(symbol)
    if not entity_id:
        return None
    try:
        search = _get_client().search.new(
            Entity(entity_id), date_range=_range(window), scope=DocumentType.NEWS,
        )
        docs = search.run(limit=25)
        vals = [float(d.sentiment) for d in docs if getattr(d, "sentiment", None) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None
    except Exception:
        return None


def company_profile(symbol: str) -> dict:
    """Qualitative entity facts from Bigdata's knowledge graph
    (name, description, sector, industry). {} if unavailable."""
    if not enabled():
        return {}
    try:
        companies = _get_client().knowledge_graph.find_companies(symbol)
        if isinstance(companies, dict):
            companies = companies.get(symbol, [])
        if not companies:
            return {}
        sym = symbol.upper()
        c = next((x for x in companies if (getattr(x, "ticker", "") or "").upper() == sym), companies[0])
        return {
            "name": getattr(c, "name", None),
            "description": getattr(c, "description", None),
            "sector": getattr(c, "sector", None),
            "industry": getattr(c, "industry", None),
        }
    except Exception:
        return {}
