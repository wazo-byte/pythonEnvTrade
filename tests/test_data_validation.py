import pandas as pd
from trading_system.data.validation import validate_ohlcv


def test_validation_drops_duplicate_and_missing_rows():
    dates = pd.to_datetime(["2024-01-02", "2024-01-01", "2024-01-01"])
    frame = pd.DataFrame({"Open": [1, 2, 2], "High": [1, 2, 2], "Low": [1, 2, 2], "Close": [1, None, 2], "Volume": [1, 1, 1]}, index=dates)
    valid, messages = validate_ohlcv(frame)
    assert len(valid) == 2
    assert valid.index.is_monotonic_increasing
    assert any("duplicate" in note for note in messages)
