import pandas as pd

from agents.sell_signals import evaluate_sell, evaluate_holdings
import db.users as U
import data.loader as L


def _hist(trend, n=210, start=100.0):
    prices = [start]
    for _ in range(1, n):
        prices.append(prices[-1] * (1 + trend))
    idx = pd.date_range("2025-01-01", periods=n)
    return pd.DataFrame({"Close": prices, "Volume": [1e6] * n}, index=idx)


UP = _hist(0.004)
DOWN = _hist(-0.004)


def test_healthy_position_holds():
    r = evaluate_sell(
        {"symbol": "AAA", "quantity": 10, "cost_basis": 220,
         "current_price": float(UP["Close"].iloc[-1])},
        {"trailingPE": 22, "revenueGrowth": 0.18, "profitMargins": 0.25}, UP, ai_score=78)
    assert r["verdict"] == "Hold" and r["urgency"] < 35


def test_downtrend_stoploss_sells():
    last = float(DOWN["Close"].iloc[-1])
    r = evaluate_sell(
        {"symbol": "BBB", "quantity": 10, "cost_basis": last / 0.7, "current_price": last},
        {"trailingPE": 80, "revenueGrowth": -0.1, "profitMargins": -0.05}, DOWN, ai_score=38)
    assert r["verdict"] == "Sell"
    assert "stop-loss" in r["flags"]["risk"]
    assert "downtrend" in r["flags"]["technical"]
    assert r["suggested_sell_qty"] == 10  # sell all


def test_big_winner_trims():
    r = evaluate_sell(
        {"symbol": "CCC", "quantity": 20, "cost_basis": 50, "current_price": 100},
        {"trailingPE": 60, "revenueGrowth": 0.2, "profitMargins": 0.3, "targetMeanPrice": 95},
        UP, ai_score=70)
    assert r["verdict"] in ("Trim", "Sell")
    assert r["suggested_sell_qty"] is not None


def test_sparse_data_holds():
    r = evaluate_sell({"symbol": "DDD", "quantity": 5, "cost_basis": 100, "current_price": 95},
                      {}, None, None)
    assert r["verdict"] == "Hold"
    assert r["reasons"]  # has the "looks healthy" message


def test_evaluate_holdings_batch(monkeypatch):
    # loader is auto-mocked by conftest: WEAK -> downtrend + weak fundamentals
    uid = U.create_user("holder", "password123")["user"]["id"]
    L.save_holdings(uid, {"cash": 0.0, "positions": [
        {"symbol": "WEAK", "quantity": 10, "cost_basis": 100, "unrealized_gl_pct": -60},
        {"symbol": "NVDA", "quantity": 5, "cost_basis": 60, "unrealized_gl_pct": 137},
    ]})
    out = evaluate_holdings(uid, ai_scores={"WEAK": 38})
    by = {r["symbol"]: r for r in out}
    assert by["WEAK"]["verdict"] == "Sell"
    # ranked by urgency, most urgent first
    assert [r["urgency"] for r in out] == sorted([r["urgency"] for r in out], reverse=True)
