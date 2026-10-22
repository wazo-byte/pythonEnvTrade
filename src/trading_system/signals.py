import pandas as pd


def classify(row: pd.Series, settings: dict) -> tuple[str, str]:
    s = settings["strategy"]
    required = ["EMA20", "EMA50", "RSI14", "MACD", "MACDSignal"]
    if row[required].isna().any():
        return "NO-SIGNAL", "insufficient history for indicators"
    trend = row["EMA20"] > row["EMA50"]
    momentum = s["rsi_min"] <= row["RSI14"] <= s["rsi_max"]
    confirmation = row["MACD"] > row["MACDSignal"]
    failures = [name for name, passed in (("trend", trend), ("RSI range", momentum), ("MACD confirmation", confirmation)) if not passed]
    return ("BUY" if not failures else "WATCH"), ("all baseline rules passed" if not failures else "failed: " + ", ".join(failures))


def latest_signal(ticker: str, data: pd.DataFrame, settings: dict, validation: list[str]) -> dict:
    row = data.iloc[-1]
    signal, explanation = classify(row, settings)
    return {"ticker": ticker, "timestamp": data.index[-1].isoformat(), "latest_price": row["Close"], "ema20": row["EMA20"], "ema50": row["EMA50"], "rsi14": row["RSI14"], "macd": row["MACD"], "macd_signal": row["MACDSignal"], "volume_ratio20": row["VolumeRatio20"], "signal": signal, "explanation": explanation, "data_status": "; ".join(validation) or "valid"}
