import pandas as pd
from trading_system.fx import fx_rate_series


def test_historical_fx_uses_prior_close_for_execution_and_current_close_for_valuation():
    sessions = pd.date_range("2024-01-01", periods=3)
    history = pd.DataFrame({"Close": [4.0, 5.0, 6.0]}, index=sessions)
    settings = {"portfolio": {"base_currency": "USD", "fx_history": {"MYR": {"invert": True}}}}
    execution, valuation = fx_rate_series(settings, "MYR", list(sessions), history)
    assert pd.isna(execution.iloc[0])
    assert execution.iloc[2] == .2
    assert valuation.iloc[2] == 1 / 6
