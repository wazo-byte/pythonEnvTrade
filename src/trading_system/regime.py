import pandas as pd


def classify_market_regime(data: pd.DataFrame) -> str:
    """Classify broad trend from already-calculated benchmark indicators."""
    row = data.iloc[-1]
    if row[["Close", "EMA20", "EMA50"]].isna().any():
        return "UNAVAILABLE"
    if row["Close"] > row["EMA20"] > row["EMA50"]:
        return "BULLISH"
    if row["Close"] < row["EMA20"] < row["EMA50"]:
        return "BEARISH"
    return "NEUTRAL"
