import pandas as pd
from trading_system.indicators import add_indicators


def settings():
    return {"strategy": {"ema_fast": 2, "ema_slow": 3, "rsi_period": 2, "rsi_min": 40, "rsi_max": 80, "macd_fast": 2, "macd_slow": 3, "macd_signal": 2}}


def test_indicators_have_warmup_then_values():
    close = pd.Series(range(10, 20), index=pd.date_range("2024-01-01", periods=10))
    data = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1})
    result = add_indicators(data, settings())
    assert result["EMA20"].iloc[0] != result["EMA20"].iloc[0]
    assert result["EMA50"].notna().iloc[-1]
    assert result["MACDSignal"].notna().iloc[-1]
