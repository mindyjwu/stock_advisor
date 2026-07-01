"""
S&P 500 ticker universe. Fetches from Wikipedia and caches to disk;
falls back to the cached file if offline.
"""
import pathlib
import json
import io
import urllib.request
import pandas as pd

CACHE_PATH = pathlib.Path(__file__).parent / "sp500_cache.json"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def fetch_sp500() -> list[dict]:
    try:
        req = urllib.request.Request(WIKI_URL, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=15).read()
        tables = pd.read_html(io.BytesIO(html))
        df = tables[0]
        tickers = [
            {"symbol": row["Symbol"].replace(".", "-"), "industry": row["GICS Sector"]}
            for _, row in df.iterrows()
        ]
        CACHE_PATH.write_text(json.dumps(tickers, indent=2))
        return tickers
    except Exception:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text())
        raise RuntimeError("Could not fetch S&P 500 list and no cache available")


def load_sp500(force_refresh: bool = False) -> list[dict]:
    if not force_refresh and CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text())
    return fetch_sp500()
