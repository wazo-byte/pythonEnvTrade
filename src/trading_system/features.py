"""Feature and label preparation for future supervised-model experiments."""
import pandas as pd

FEATURE_COLUMNS = ["EMA20", "EMA50", "RSI14", "MACD", "MACDSignal", "MACDHistogram", "Volatility20"]


def make_supervised_dataset(data: pd.DataFrame, horizon: int = 5) -> tuple[pd.DataFrame, pd.Series]:
    """Return decision-time features and a future-return label, with no trailing unknown labels."""
    if horizon < 1:
        raise ValueError("horizon must be at least one bar")
    target = data["Close"].shift(-horizon).div(data["Close"]).sub(1).rename(f"future_return_{horizon}d")
    combined = data[FEATURE_COLUMNS].join(target).dropna()
    return combined[FEATURE_COLUMNS], combined[target.name]


def chronological_split(features: pd.DataFrame, labels: pd.Series, train: float = 0.60, validation: float = 0.20) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    """Split ordered observations without shuffling; the final slice is held out for testing."""
    if not 0 < train < 1 or not 0 < validation < 1 or train + validation >= 1:
        raise ValueError("train and validation must be positive and sum to less than one")
    if not features.index.equals(labels.index) or len(features) < 3:
        raise ValueError("features and labels must share an index and contain at least three rows")
    train_end, validation_end = int(len(features) * train), int(len(features) * (train + validation))
    if train_end == 0 or validation_end == train_end or validation_end == len(features):
        raise ValueError("split leaves an empty partition")
    return {
        "train": (features.iloc[:train_end], labels.iloc[:train_end]),
        "validation": (features.iloc[train_end:validation_end], labels.iloc[train_end:validation_end]),
        "test": (features.iloc[validation_end:], labels.iloc[validation_end:]),
    }
