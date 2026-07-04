import json
import pathlib
import shutil
import yfinance as yf
import pandas as pd
from functools import lru_cache

ROOT = pathlib.Path(__file__).parent.parent
# Legacy single-user files — migrated into the owner's folder on first signup
LEGACY_WATCHLIST_PATH = ROOT / "data" / "watchlist.json"
LEGACY_HOLDINGS_PATH = ROOT / "data" / "holdings.json"
USERS_DIR = ROOT / "data" / "users"

# Starter watchlist for brand-new accounts
DEFAULT_WATCHLIST = [
    {"symbol": "AAPL", "industry": "Technology"},
    {"symbol": "MSFT", "industry": "Technology"},
    {"symbol": "NVDA", "industry": "Technology"},
    {"symbol": "JPM",  "industry": "Financials"},
    {"symbol": "JNJ",  "industry": "Healthcare"},
    {"symbol": "XOM",  "industry": "Energy"},
    {"symbol": "COST", "industry": "Consumer Staples"},
    {"symbol": "DIS",  "industry": "Communication Services"},
]


def _user_dir(user_id: int) -> pathlib.Path:
    d = USERS_DIR / str(int(user_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def migrate_legacy_to_user(user_id: int):
    """Move the pre-account watchlist/holdings files into this user's folder.
    Called once, when the first (owner) account is created."""
    d = _user_dir(user_id)
    for legacy, name in ((LEGACY_WATCHLIST_PATH, "watchlist.json"),
                         (LEGACY_HOLDINGS_PATH, "holdings.json")):
        target = d / name
        if legacy.exists() and not target.exists():
            shutil.copy2(legacy, target)
            legacy.rename(legacy.with_suffix(".json.migrated"))


def load_watchlist(user_id: int) -> list[dict]:
    path = _user_dir(user_id) / "watchlist.json"
    if not path.exists():
        save_watchlist(user_id, list(DEFAULT_WATCHLIST))
        return list(DEFAULT_WATCHLIST)
    with open(path) as f:
        return json.load(f)["tickers"]


def load_holdings(user_id: int) -> dict:
    path = _user_dir(user_id) / "holdings.json"
    if not path.exists():
        return {"cash": 0.0, "positions": []}
    with open(path) as f:
        return json.load(f)


INFO_CACHE_DIR = ROOT / "data" / "cache" / "info"
INFO_CACHE_TTL_SECONDS = 15 * 60  # fresh enough for prices, avoids re-fetching 500 tickers


# maxsize must cover a full ~500-ticker S&P scan, or the cache thrashes
@lru_cache(maxsize=1024)
def fetch_ticker_info(symbol: str) -> dict:
    # Disk cache layer: makes repeat scans near-instant across app restarts
    cache_file = INFO_CACHE_DIR / f"{symbol.upper()}.json"
    try:
        import time
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < INFO_CACHE_TTL_SECONDS:
            with open(cache_file) as f:
                return json.load(f)
    except Exception:
        pass
    t = yf.Ticker(symbol)
    info = t.info or {}
    try:
        INFO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w") as f:
            json.dump(info, f, default=str)
    except Exception:
        pass
    return info


def fetch_price_history_bulk(symbols: list, period: str = "3mo", chunk_size: int = 60) -> dict:
    """Download price history for MANY tickers in a few batched yfinance
    requests — dramatically faster than one call per ticker for a market scan.
    yfinance's own threads=True is broken in 1.x, so we chunk the universe and
    parallelize the chunks ourselves. Returns {symbol: DataFrame}; symbols
    that fail are simply absent."""
    from concurrent.futures import ThreadPoolExecutor

    out = {}
    if not symbols:
        return out
    chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]

    def _one_chunk(chunk):
        try:
            return chunk, yf.download(
                tickers=" ".join(chunk), period=period, group_by="ticker",
                threads=False, progress=False,
            )
        except Exception:
            return chunk, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for chunk, df in ex.map(_one_chunk, chunks):
            if df is None or df.empty:
                continue
            for s in chunk:
                try:
                    sub = df[s].dropna(how="all") if len(chunk) > 1 else df.dropna(how="all")
                    if not sub.empty:
                        sub = sub.copy()
                        sub.index = sub.index.tz_localize(None)
                        out[s] = sub
                except Exception:
                    continue
    return out


@lru_cache(maxsize=1024)
def fetch_price_history(symbol: str, period: str = "6mo") -> pd.DataFrame:
    t = yf.Ticker(symbol)
    df = t.history(period=period)
    df.index = df.index.tz_localize(None)
    return df


def fetch_vix() -> float:
    """Return latest VIX close. Falls back to 20.0 on failure."""
    try:
        df = yf.Ticker("^VIX").history(period="5d")
        return float(df["Close"].iloc[-1])
    except Exception:
        return 20.0


def current_portfolio_value(holdings: dict) -> float:
    total = holdings.get("cash", 0.0)
    for pos in holdings.get("positions", []):
        info = fetch_ticker_info(pos["symbol"])
        price = info.get("currentPrice") or info.get("regularMarketPrice") or pos["cost_basis"]
        total += price * pos["quantity"]
    return total


def holdings_by_symbol(holdings: dict) -> dict:
    return {p["symbol"]: p for p in holdings.get("positions", [])}


def save_watchlist(user_id: int, tickers: list[dict]):
    with open(_user_dir(user_id) / "watchlist.json", "w") as f:
        json.dump({"tickers": tickers}, f, indent=2)
    fetch_ticker_info.cache_clear()
    fetch_price_history.cache_clear()


def save_holdings(user_id: int, holdings: dict):
    with open(_user_dir(user_id) / "holdings.json", "w") as f:
        json.dump(holdings, f, indent=2)
    fetch_ticker_info.cache_clear()


def holdings_total_value(holdings: dict) -> float:
    """Sum imported_value (from broker) across positions + cash, if available."""
    total = holdings.get("cash", 0.0)
    for p in holdings.get("positions", []):
        total += p.get("current_value") or (p.get("cost_basis", 0) * p.get("quantity", 0))
    return total
