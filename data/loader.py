import json
import pathlib
import yfinance as yf
import pandas as pd
from functools import lru_cache

ROOT = pathlib.Path(__file__).parent.parent
WATCHLIST_PATH = ROOT / "data" / "watchlist.json"
HOLDINGS_PATH = ROOT / "data" / "holdings.json"


def load_watchlist() -> list[dict]:
    with open(WATCHLIST_PATH) as f:
        return json.load(f)["tickers"]


def load_holdings() -> dict:
    with open(HOLDINGS_PATH) as f:
        return json.load(f)


@lru_cache(maxsize=64)
def fetch_ticker_info(symbol: str) -> dict:
    t = yf.Ticker(symbol)
    return t.info or {}


@lru_cache(maxsize=64)
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


def save_watchlist(tickers: list[dict]):
    with open(WATCHLIST_PATH, "w") as f:
        json.dump({"tickers": tickers}, f, indent=2)
    fetch_ticker_info.cache_clear()
    fetch_price_history.cache_clear()


def save_holdings(holdings: dict):
    with open(HOLDINGS_PATH, "w") as f:
        json.dump(holdings, f, indent=2)
    fetch_ticker_info.cache_clear()


def holdings_total_value(holdings: dict) -> float:
    """Sum imported_value (from broker) across positions + cash, if available."""
    total = holdings.get("cash", 0.0)
    for p in holdings.get("positions", []):
        total += p.get("current_value") or (p.get("cost_basis", 0) * p.get("quantity", 0))
    return total
