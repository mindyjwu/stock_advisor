"""Scores a stock 0-100 on technicals: RSI, MACD, moving average trend."""
import pandas as pd
import numpy as np


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def _macd(close: pd.Series) -> tuple[float, float]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])


def score_technicals(price_history: pd.DataFrame) -> dict:
    if price_history is None or price_history.empty or len(price_history) < 30:
        return {"score": 50.0, "reasons": ["Insufficient price history"]}

    close = price_history["Close"]
    points = []
    reasons = []

    rsi = _rsi(close)
    if rsi < 30:
        points.append(80); reasons.append(f"RSI {rsi:.0f} — oversold, potential bounce")
    elif rsi < 50:
        points.append(60)
    elif rsi < 70:
        points.append(50)
    else:
        points.append(25); reasons.append(f"RSI {rsi:.0f} — overbought")

    macd_line, signal_line = _macd(close)
    if macd_line > signal_line:
        points.append(70); reasons.append("MACD bullish crossover")
    else:
        points.append(35); reasons.append("MACD bearish")

    sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else close.mean()
    sma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else close.mean()
    last = close.iloc[-1]

    if last > sma50 > sma200:
        points.append(80); reasons.append("Price above 50/200 SMA — uptrend")
    elif last > sma50:
        points.append(60)
    elif last < sma50 < sma200:
        points.append(25); reasons.append("Price below 50/200 SMA — downtrend")
    else:
        points.append(40)

    vol_avg = price_history["Volume"].rolling(20).mean().iloc[-1]
    vol_last = price_history["Volume"].iloc[-1]
    if vol_avg and vol_last > vol_avg * 1.5:
        reasons.append("Volume spike vs 20-day average")

    score = sum(points) / len(points)
    return {"score": round(score, 1), "reasons": reasons}
