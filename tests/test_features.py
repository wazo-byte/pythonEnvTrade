import pandas as pd
from trading_system.features import chronological_split, make_supervised_dataset


def test_future_labels_do_not_leak_into_features_or_last_horizon():
    index = pd.date_range("2024-01-01", periods=8)
    data = pd.DataFrame({"Close": [10, 11, 12, 13, 14, 15, 16, 17], **{column: range(8) for column in ["EMA20", "EMA50", "RSI14", "MACD", "MACDSignal", "MACDHistogram", "Volatility20"]}}, index=index)
    features, labels = make_supervised_dataset(data, horizon=2)
    assert len(features) == 6
    assert features.index[-1] == index[5]
    assert labels.iloc[0] == 12 / 10 - 1


def test_chronological_split_never_shuffles_periods():
    index = pd.date_range("2024-01-01", periods=10)
    features = pd.DataFrame({"x": range(10)}, index=index)
    splits = chronological_split(features, pd.Series(range(10), index=index))
    assert splits["train"][0].index.max() < splits["validation"][0].index.min() < splits["test"][0].index.min()
