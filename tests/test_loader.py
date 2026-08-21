"""
Tests for the yfinance resilience layer in data.loader.

The conftest autouse `mock_prices` fixture swaps loader.fetch_ticker_info /
fetch_price_history at the module-attribute level so nothing hits the network.
We grab references to the REAL functions at import time (before any fixture
runs) so we can exercise the actual retry path, and we patch yfinance itself.
"""
import pytest

import data.loader as loader
# Real, un-mocked references captured at collection time (pre-fixture).
_real_fetch_info = loader.fetch_ticker_info
_real_fetch_history = loader.fetch_price_history


class _FlakyTicker:
    """A yf.Ticker stand-in that fails the first `fail_times` accesses, then
    succeeds. Records how many times it was constructed so we can assert on
    the number of retries."""
    calls = 0

    def __init__(self, symbol, fail_times, payload):
        pass

    @classmethod
    def factory(cls, fail_times, payload):
        def _make(symbol):
            cls.calls += 1
            t = object.__new__(cls)
            t._fail = cls.calls <= fail_times
            t._payload = payload
            return t
        return _make

    @property
    def info(self):
        if self._fail:
            raise ConnectionError("yahoo blipped")
        return self._payload

    def history(self, period="6mo"):
        if self._fail:
            raise ConnectionError("yahoo blipped")
        import pandas as pd
        idx = pd.date_range("2025-01-01", periods=3, tz="America/New_York")
        return pd.DataFrame({"Close": [1.0, 2.0, 3.0]}, index=idx)


# ── _retry unit tests ────────────────────────────────────────────────────────

def test_retry_returns_first_success():
    calls = []
    out = loader._retry(lambda: calls.append(1) or "ok")
    assert out == "ok" and len(calls) == 1


def test_retry_succeeds_after_transient(monkeypatch):
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)
    n = {"i": 0}

    def flaky():
        n["i"] += 1
        if n["i"] < 3:
            raise ConnectionError("blip")
        return "recovered"

    assert loader._retry(flaky) == "recovered"
    assert n["i"] == 3  # failed twice, succeeded on the third


def test_retry_reraises_after_exhausting(monkeypatch):
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)
    n = {"i": 0}

    def always_fail():
        n["i"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError, match="permanent"):
        loader._retry(always_fail)
    assert n["i"] == loader._FETCH_RETRIES  # tried exactly `retries` times


def test_retry_exponential_backoff(monkeypatch):
    slept = []
    monkeypatch.setattr(loader.time, "sleep", lambda s: slept.append(s))
    with pytest.raises(RuntimeError):
        loader._retry(lambda: (_ for _ in ()).throw(RuntimeError("x")),
                      retries=4, base_delay=0.5)
    # 3 sleeps between 4 attempts: 0.5, 1.0, 2.0 — no sleep after the last try
    assert slept == [0.5, 1.0, 2.0]


# ── integration: the fetch functions actually retry & don't poison the cache ──

def test_fetch_price_history_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)
    _FlakyTicker.calls = 0
    monkeypatch.setattr(loader.yf, "Ticker",
                        _FlakyTicker.factory(fail_times=2, payload=None))
    _real_fetch_history.cache_clear()
    df = _real_fetch_history("FLAKY1")
    assert list(df["Close"]) == [1.0, 2.0, 3.0]
    assert df.index.tz is None                 # tz stripped as usual
    assert _FlakyTicker.calls == 3             # two failures + one success


def test_lru_cache_never_caches_a_failure(monkeypatch):
    """A transient outage must NOT be cached: after it recovers, the next call
    returns real data instead of a stuck error/empty."""
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)
    _real_fetch_history.cache_clear()

    # First: fail on every attempt -> the call raises (nothing cached).
    _FlakyTicker.calls = 0
    monkeypatch.setattr(loader.yf, "Ticker",
                        _FlakyTicker.factory(fail_times=99, payload=None))
    with pytest.raises(ConnectionError):
        _real_fetch_history("FLAKY2")

    # Then: yahoo recovers. Because the failure wasn't cached, this re-runs.
    _FlakyTicker.calls = 0
    monkeypatch.setattr(loader.yf, "Ticker",
                        _FlakyTicker.factory(fail_times=0, payload=None))
    df = _real_fetch_history("FLAKY2")
    assert list(df["Close"]) == [1.0, 2.0, 3.0]


def test_fetch_ticker_info_retries(monkeypatch, tmp_path):
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)
    monkeypatch.setattr(loader, "INFO_CACHE_DIR", tmp_path / "info")
    _FlakyTicker.calls = 0
    monkeypatch.setattr(loader.yf, "Ticker",
                        _FlakyTicker.factory(fail_times=1,
                                             payload={"currentPrice": 123.0}))
    _real_fetch_info.cache_clear()
    info = _real_fetch_info("FLAKY3")
    assert info["currentPrice"] == 123.0
    assert _FlakyTicker.calls == 2             # one failure + one success


def test_fetch_vix_falls_back_on_persistent_failure(monkeypatch):
    monkeypatch.setattr(loader.time, "sleep", lambda s: None)

    def boom(symbol):
        raise ConnectionError("down")

    monkeypatch.setattr(loader.yf, "Ticker", boom)
    assert loader.fetch_vix() == 20.0
