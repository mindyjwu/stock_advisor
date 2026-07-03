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


# maxsize must cover a full ~500-ticker S&P scan, or the cache thrashes
@lru_cache(maxsize=1024)
def fetch_ticker_info(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    return t.info or {}


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
