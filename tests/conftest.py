"""
Shared pytest fixtures.

Runs against SQLite by default (a fresh temp DB per test). In CI it also runs
against Postgres when DATABASE_URL is set — the fixtures drop and recreate the
schema each test so the two paths behave identically. Network (yfinance) is
mocked so tests are deterministic and offline.
"""
import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from db import connection  # noqa: E402

ALL_TABLES = [
    "login_attempts", "reports", "blocks", "post_likes", "posts", "follows",
    "shared_watchlists", "profiles", "imports", "decisions",
    "portfolio_snapshots", "scans", "alerts", "saved_picks", "suggestions",
    "users",
]


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Give every test an empty schema on whichever backend is active."""
    if not connection.IS_POSTGRES:
        monkeypatch.setattr(connection, "SQLITE_PATH", tmp_path / "test.db")

    import data.loader as loader
    monkeypatch.setattr(loader, "USERS_DIR", tmp_path / "users")

    import db.users as users
    import db.store as store
    import db.community as community

    if connection.IS_POSTGRES:
        with connection.connect() as con:
            for t in ALL_TABLES:
                con.execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    users.init_users()
    store.init_db()
    community.init_community()

    from agents import track_record, scorecard
    track_record.clear_cache()
    scorecard.clear_cache()
    yield


def _fake_info(symbol):
    # A deterministic quote; a couple of symbols get richer data for sell tests.
    table = {
        "WEAK": {"currentPrice": 40.0, "regularMarketPrice": 40.0,
                 "trailingPE": 80, "revenueGrowth": -0.1, "profitMargins": -0.05},
        "NVDA": {"currentPrice": 142.0, "regularMarketPrice": 142.0,
                 "trailingPE": 58, "revenueGrowth": 0.22, "profitMargins": 0.5},
    }
    return table.get(symbol, {"currentPrice": 100.0, "regularMarketPrice": 100.0})


def _fake_history(symbol, period="6mo"):
    n = 210
    trend = -0.004 if symbol == "WEAK" else 0.003
    prices = [100.0]
    for _ in range(1, n):
        prices.append(prices[-1] * (1 + trend))
    idx = pd.date_range("2025-01-01", periods=n)
    return pd.DataFrame({"Close": prices, "Volume": [1_000_000] * n}, index=idx)


_fake_info.cache_clear = lambda: None
_fake_history.cache_clear = lambda: None


@pytest.fixture(autouse=True)
def mock_prices(monkeypatch):
    """Patch yfinance access so no test hits the network."""
    import data.loader as loader
    monkeypatch.setattr(loader, "fetch_ticker_info", _fake_info)
    monkeypatch.setattr(loader, "fetch_price_history", _fake_history)
    yield
