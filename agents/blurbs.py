"""
Plain-English company blurbs: what each company does and how it makes money.

Source: yfinance's longBusinessSummary, compressed to 1-2 beginner-friendly
sentences by a single batched Claude call. Falls back to the summary's first
sentences when no API key is available. Cached on disk indefinitely —
business models rarely change, so each symbol costs at most one LLM visit.
"""
import json
import os
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor

from anthropic import Anthropic

from data.loader import fetch_ticker_info

CACHE_PATH = pathlib.Path(__file__).parent.parent / "data" / "cache" / "blurbs.json"
PROFILE_CACHE_PATH = pathlib.Path(__file__).parent.parent / "data" / "cache" / "profiles.json"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def _load_cache() -> dict:
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=1)
    except Exception:
        pass


def _fallback(info: dict):
    """First 1-2 sentences of the official business summary."""
    s = (info.get("longBusinessSummary") or "").strip()
    if not s:
        return None
    parts = re.split(r"(?<=\.)\s+", s)
    out = " ".join(parts[:2]).strip()
    if len(out) > 280:
        out = out[:277].rsplit(" ", 1)[0] + "…"
    return out


def _llm_batch(symbols: list, infos: dict) -> dict:
    lines = []
    for s in symbols:
        summary = (infos.get(s, {}).get("longBusinessSummary") or "")[:500]
        name = infos.get(s, {}).get("shortName") or s
        lines.append(f"{s} ({name}): {summary or '(no summary available)'}")

    prompt = f"""For each company below, write 1-2 SHORT sentences for a beginner investor:
what the company actually does, and its main way of making money. Plain English,
no jargon, no hype. Base it on the provided summary; if none, use what you know.

{chr(10).join(lines)}

Respond ONLY with JSON mapping each ticker to its blurb:
{{"XYZ": "Makes ... Its main revenue comes from ...", ...}}"""

    model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
    resp = _get_client().messages.create(
        model=model_id, max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    data = json.loads(text)
    return {k.upper(): v.strip() for k, v in data.items() if isinstance(v, str) and v.strip()}


def _fmt_employees(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return None
    if n >= 1000:
        return f"{n/1000:.0f}k employees" if n >= 10000 else f"{n:,} employees"
    return f"{n:,} employees"


def _profile_facts(info: dict) -> dict:
    hq = ", ".join([x for x in (info.get("city"), info.get("state") or info.get("country")) if x]) or None
    return {
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "employees": _fmt_employees(info.get("fullTimeEmployees")),
        "hq": hq,
        "website": info.get("website"),
    }


def _profile_llm_batch(symbols: list, infos: dict) -> dict:
    lines = []
    for s in symbols:
        i = infos.get(s, {})
        summary = (i.get("longBusinessSummary") or "")[:900]
        name = i.get("longName") or i.get("shortName") or s
        lines.append(f"{s} ({name}) — {i.get('sector','?')} / {i.get('industry','?')}:\n{summary or '(no summary)'}")

    prompt = f"""For each company, write a short qualitative profile for a beginner investor.
Cover, in 3-4 plain sentences: (1) what it actually makes or sells, (2) who its
customers are, (3) how it makes money, and (4) what makes it distinctive or its
competitive position (its "moat", brand, scale, or key risk). No hype, no jargon,
no stock advice — just help them understand the business.

{chr(10).join(lines)}

Respond ONLY with JSON mapping each ticker to its profile paragraph:
{{"XYZ": "3-4 sentence plain-English profile", ...}}"""

    model_id = os.environ.get("ADVISOR_AI_MODEL", "claude-sonnet-4-6")
    resp = _get_client().messages.create(
        model=model_id, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    data = json.loads(text)
    return {k.upper(): v.strip() for k, v in data.items() if isinstance(v, str) and v.strip()}


def get_profiles(symbols: list) -> dict:
    """Richer company profiles for the buy recommendations:
    {symbol: {narrative, sector, industry, employees, hq, website}}.
    The narrative is AI-written (cached forever); facts come live from the feed."""
    symbols = [s.upper() for s in symbols if s]
    try:
        with open(PROFILE_CACHE_PATH) as f:
            narr_cache = json.load(f)
    except Exception:
        narr_cache = {}

    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = dict(zip(symbols, ex.map(lambda s: fetch_ticker_info(s), symbols)))

    missing = [s for s in symbols if s not in narr_cache]
    if missing and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            new = _profile_llm_batch(missing, infos)
        except Exception:
            new = {}
        for s in missing:
            if new.get(s):
                narr_cache[s] = new[s]
        try:
            PROFILE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(PROFILE_CACHE_PATH, "w") as f:
                json.dump(narr_cache, f, indent=1)
        except Exception:
            pass

    out = {}
    for s in symbols:
        info = infos.get(s, {})
        narrative = narr_cache.get(s) or _fallback(info)
        out[s] = dict(_profile_facts(info), narrative=narrative)
    return out


def get_blurbs(symbols: list) -> dict:
    """Returns {symbol: blurb} for every symbol it can describe. Cached."""
    symbols = [s.upper() for s in symbols if s]
    cache = _load_cache()
    out = {s: cache[s] for s in symbols if s in cache}
    missing = [s for s in symbols if s not in cache]
    if not missing:
        return out

    with ThreadPoolExecutor(max_workers=8) as ex:
        infos = dict(zip(missing, ex.map(lambda s: fetch_ticker_info(s), missing)))

    llm = {}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            llm = _llm_batch(missing, infos)
        except Exception:
            llm = {}

    for s in missing:
        blurb = llm.get(s) or _fallback(infos.get(s, {}))
        if blurb:
            cache[s] = blurb
            out[s] = blurb
    _save_cache(cache)
    return out
