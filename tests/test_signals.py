import pandas as pd
from trading_system.signals import classify


SETTINGS = {"strategy": {"rsi_min": 45, "rsi_max": 70}}


def test_buy_requires_all_transparent_rules():
    row = pd.Series({"EMA20": 11, "EMA50": 10, "RSI14": 55, "MACD": 1, "MACDSignal": 0})
    assert classify(row, SETTINGS)[0] == "BUY"
    row["RSI14"] = 90
    signal, explanation = classify(row, SETTINGS)
    assert signal == "WATCH" and "RSI range" in explanation
