import pandas as pd


def add_indicators(data: pd.DataFrame, settings: dict) -> pd.DataFrame:
    s = settings["strategy"]
    out = data.copy()
    close = out["Close"]
    out["EMA20"] = close.ewm(span=s["ema_fast"], adjust=False, min_periods=s["ema_fast"]).mean()
    out["EMA50"] = close.ewm(span=s["ema_slow"], adjust=False, min_periods=s["ema_slow"]).mean()
    delta = close.diff()
    gains, losses = delta.clip(lower=0), -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / s["rsi_period"], adjust=False, min_periods=s["rsi_period"]).mean()
    average_loss = losses.ewm(alpha=1 / s["rsi_period"], adjust=False, min_periods=s["rsi_period"]).mean()
    relative_strength = average_gain / average_loss.where(average_loss != 0, 1.0)
    rsi = 100 - (100 / (1 + relative_strength))
    rsi = rsi.mask((average_gain == 0) & (average_loss == 0), 50.0)
    rsi = rsi.mask((average_loss == 0) & (average_gain > 0), 100.0)
    out["RSI14"] = rsi
    fast = close.ewm(span=s["macd_fast"], adjust=False, min_periods=s["macd_slow"]).mean()
    slow = close.ewm(span=s["macd_slow"], adjust=False, min_periods=s["macd_slow"]).mean()
    out["MACD"] = fast - slow
    out["MACDSignal"] = out["MACD"].ewm(span=s["macd_signal"], adjust=False, min_periods=s["macd_signal"]).mean()
    out["MACDHistogram"] = out["MACD"] - out["MACDSignal"]
    out["Volatility20"] = close.pct_change().rolling(20, min_periods=20).std() * (252**0.5)
    return out
