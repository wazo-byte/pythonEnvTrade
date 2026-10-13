import pandas as pd

REQUIRED = ["Open", "High", "Low", "Close", "Volume"]


def validate_ohlcv(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return sorted, duplicate-free valid rows plus validation messages.

    Missing/invalid price rows are removed rather than filled, so prices are never invented.
    """
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    data = frame.copy()
    data.index = pd.to_datetime(data.index, utc=True).tz_localize(None)
    messages: list[str] = []
    duplicates = int(data.index.duplicated().sum())
    if duplicates:
        messages.append(f"dropped {duplicates} duplicate timestamp(s)")
        data = data[~data.index.duplicated(keep="last")]
    data = data.sort_index()
    for column in REQUIRED:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    invalid = data[REQUIRED].isna().any(axis=1) | (data[["Open", "High", "Low", "Close"]] <= 0).any(axis=1) | (data["Volume"] < 0)
    if invalid.any():
        messages.append(f"dropped {int(invalid.sum())} row(s) with missing or invalid OHLCV")
        data = data.loc[~invalid]
    if data.empty:
        raise ValueError("No valid OHLCV rows remain")
    return data, messages
